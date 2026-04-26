import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy import func, or_
from sqlalchemy.orm import Session
from starlette.responses import PlainTextResponse

from app.core.config import settings
from app.core.deps import (
    can_access_workspace_conversation,
    get_current_user,
    get_current_workspace_id,
    get_db_session,
    is_workspace_privileged_role,
    require_csrf_protection,
    require_workspace_write_access,
)
from app.core.errors import ApiError
from app.models import (
    Notebook,
    NotebookAttachment,
    NotebookPage,
    NotebookPageVersion,
    Project,
    StudyAsset,
    AIActionLog,
    Membership,
    User,
)
from app.core.entitlements import require_entitlement
from app.services import storage as storage_service
from app.services.ai_action_logger import action_log_context
from app.services.quota_counters import (
    count_ai_actions_this_month,
    count_notebooks,
    count_pages,
)
from app.services.upload_validation import (
    UPLOAD_SIGNATURE_READ_BYTES,
    validate_workspace_upload_declaration,
    validate_workspace_upload_signature,
)
from app.schemas.block import PageDuplicatePayload, PageMovePayload
from app.schemas.notebook import (
    NotebookCreate,
    NotebookHomeAIAction,
    NotebookHomeAISummary,
    NotebookHomeFocusItem,
    NotebookHomeNotebook,
    NotebookHomeOut,
    NotebookHomePage,
    NotebookHomeStudyAsset,
    NotebookOut,
    NotebookUpdate,
    PageCreate,
    PageListItem,
    PageOut,
    PageUpdate,
    PageVersionOut,
    PaginatedNotebooks,
    PaginatedPages,
)
from app.services.audit import write_audit_log


router = APIRouter(prefix="/api/v1/notebooks", tags=["notebooks"])
pages_router = APIRouter(prefix="/api/v1/pages", tags=["pages"])
study_assets_router = APIRouter(prefix="/api/v1/study-assets", tags=["study-assets"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_slug(title: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", title.lower().strip())
    slug = re.sub(r"[\s_]+", "-", slug)
    return slug[:200] if slug else str(uuid4())[:8]


def extract_plain_text(content_json: dict) -> str:
    """Walk TipTap ProseMirror JSON and extract plain text."""
    parts: list[str] = []

    def walk(node: dict) -> None:
        if node.get("type") == "text":
            parts.append(node.get("text", ""))
        for child in node.get("content", []):
            if isinstance(child, dict):
                walk(child)

    if isinstance(content_json, dict):
        walk(content_json)
    return "\n".join(parts)


def _get_page_or_404(
    db: Session,
    page_id: str,
    workspace_id: str,
    *,
    current_user_id: str,
    workspace_role: str,
) -> NotebookPage:
    """Fetch a page and verify workspace ownership through its notebook."""
    page = db.query(NotebookPage).filter(NotebookPage.id == page_id).first()
    if not page:
        raise ApiError("not_found", "Page not found", status_code=404)
    notebook = db.query(Notebook).filter(Notebook.id == page.notebook_id).first()
    if not notebook or not _can_read_notebook(
        notebook,
        workspace_id=workspace_id,
        current_user_id=current_user_id,
        workspace_role=workspace_role,
    ):
        raise ApiError("not_found", "Page not found", status_code=404)
    return page


def _get_workspace_role(db: Session, *, workspace_id: str, user_id: str) -> str:
    membership = (
        db.query(Membership)
        .filter(
            Membership.workspace_id == workspace_id,
            Membership.user_id == user_id,
        )
        .first()
    )
    if membership is None:
        raise ApiError("forbidden", "Workspace access denied", status_code=403)
    return membership.role or "owner"


def _filter_readable_notebooks(
    query,
    *,
    current_user_id: str,
    workspace_role: str,
):
    if is_workspace_privileged_role(workspace_role):
        return query
    return query.filter(
        or_(
            Notebook.visibility != "private",
            Notebook.created_by == current_user_id,
        )
    )


def _can_read_notebook(
    notebook: Notebook,
    *,
    workspace_id: str,
    current_user_id: str,
    workspace_role: str,
) -> bool:
    if str(notebook.workspace_id) != str(workspace_id):
        return False
    if (notebook.visibility or "private") != "private":
        return True
    return is_workspace_privileged_role(workspace_role) or str(notebook.created_by) == str(current_user_id)


def _get_notebook_or_404(
    db: Session,
    *,
    notebook_id: str,
    workspace_id: str,
    current_user_id: str,
    workspace_role: str,
) -> Notebook:
    query = db.query(Notebook).filter(
        Notebook.id == notebook_id,
        Notebook.workspace_id == workspace_id,
    )
    notebook = _filter_readable_notebooks(
        query,
        current_user_id=current_user_id,
        workspace_role=workspace_role,
    ).first()
    if notebook is None:
        raise ApiError("not_found", "Notebook not found", status_code=404)
    return notebook


def _filter_ai_actions_for_viewer(
    query,
    *,
    current_user_id: str,
    workspace_role: str,
):
    if is_workspace_privileged_role(workspace_role):
        return query
    return query.filter(AIActionLog.user_id == current_user_id)


def _tiptap_json_to_markdown(content_json: dict, title: str = "") -> str:
    """Convert TipTap ProseMirror JSON to Markdown."""
    parts: list[str] = []
    if title:
        parts.append(f"# {title}\n")

    def walk(node: dict, depth: int = 0) -> None:
        node_type = node.get("type", "")
        content = node.get("content", [])
        attrs = node.get("attrs", {})

        if node_type == "heading":
            level = attrs.get("level", 1)
            text = _extract_text_from_node(node)
            parts.append(f"\n{'#' * level} {text}\n")
        elif node_type == "paragraph":
            text = _extract_text_from_node(node)
            if text.strip():
                parts.append(f"\n{text}\n")
        elif node_type == "bulletList":
            for item in content:
                if isinstance(item, dict):
                    text = _extract_text_from_node(item)
                    parts.append(f"- {text}")
            parts.append("")
        elif node_type == "orderedList":
            for i, item in enumerate(content, 1):
                if isinstance(item, dict):
                    text = _extract_text_from_node(item)
                    parts.append(f"{i}. {text}")
            parts.append("")
        elif node_type == "taskList":
            for item in content:
                if isinstance(item, dict):
                    checked = item.get("attrs", {}).get("checked", False)
                    text = _extract_text_from_node(item)
                    mark = "x" if checked else " "
                    parts.append(f"- [{mark}] {text}")
            parts.append("")
        elif node_type == "codeBlock":
            lang = attrs.get("language", "")
            text = _extract_text_from_node(node)
            parts.append(f"\n```{lang}\n{text}\n```\n")
        elif node_type == "blockquote":
            text = _extract_text_from_node(node)
            for line in text.split("\n"):
                parts.append(f"> {line}")
            parts.append("")
        elif node_type == "horizontalRule":
            parts.append("\n---\n")
        elif node_type == "mathBlock":
            latex = attrs.get("latex", "")
            parts.append(f"\n$$\n{latex}\n$$\n")
        elif node_type == "inlineMath":
            latex = attrs.get("latex", "")
            parts.append(f"${latex}$")
        elif node_type == "callout":
            text = _extract_text_from_node(node)
            parts.append(f"\n> **Note:** {text}\n")
        elif node_type == "image":
            src = attrs.get("src", "")
            alt = attrs.get("alt", "")
            parts.append(f"\n![{alt}]({src})\n")
        elif node_type == "doc":
            for child in content:
                if isinstance(child, dict):
                    walk(child, depth)
        else:
            for child in content:
                if isinstance(child, dict):
                    walk(child, depth)

    if isinstance(content_json, dict):
        walk(content_json)

    return "\n".join(parts).strip() + "\n"


def _extract_text_from_node(node: dict) -> str:
    """Recursively extract plain text from a ProseMirror node."""
    if node.get("type") == "text":
        return node.get("text", "")
    parts = []
    for child in node.get("content", []):
        if isinstance(child, dict):
            parts.append(_extract_text_from_node(child))
    return "".join(parts)


# ---------------------------------------------------------------------------
# Notebook CRUD
# ---------------------------------------------------------------------------


@router.get("", response_model=PaginatedNotebooks)
def list_notebooks(
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
) -> PaginatedNotebooks:
    workspace_role = _get_workspace_role(
        db,
        workspace_id=workspace_id,
        user_id=str(current_user.id),
    )
    query = db.query(Notebook).filter(
        Notebook.workspace_id == workspace_id,
        Notebook.archived_at.is_(None),
    )
    items = _filter_readable_notebooks(
        query,
        current_user_id=str(current_user.id),
        workspace_role=workspace_role,
    ).order_by(Notebook.created_at.desc()).all()
    return PaginatedNotebooks(
        items=[NotebookOut.model_validate(item, from_attributes=True) for item in items],
        total=len(items),
    )


@router.get("/home", response_model=NotebookHomeOut)
def get_notebook_home(
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
) -> NotebookHomeOut:
    workspace_role = _get_workspace_role(
        db,
        workspace_id=workspace_id,
        user_id=str(current_user.id),
    )
    notebooks = (
        _filter_readable_notebooks(
            db.query(Notebook).filter(
                Notebook.workspace_id == workspace_id,
                Notebook.archived_at.is_(None),
            ),
            current_user_id=str(current_user.id),
            workspace_role=workspace_role,
        )
        .order_by(Notebook.updated_at.desc())
        .all()
    )
    if not notebooks:
        return NotebookHomeOut(
            notebooks=[],
            recent_pages=[],
            continue_writing=[],
            recent_study_assets=[],
            ai_today=NotebookHomeAISummary(actions_today=0),
            work_themes=[],
            long_term_focus=[],
            recommended_pages=[],
        )

    notebook_ids = [notebook.id for notebook in notebooks]
    notebook_titles = {notebook.id: notebook.title for notebook in notebooks}

    page_counts = {
        notebook_id: int(count)
        for notebook_id, count in (
            db.query(NotebookPage.notebook_id, func.count(NotebookPage.id))
            .filter(
                NotebookPage.notebook_id.in_(notebook_ids),
                NotebookPage.is_archived.is_(False),
            )
            .group_by(NotebookPage.notebook_id)
            .all()
        )
    }
    study_asset_counts = {
        notebook_id: int(count)
        for notebook_id, count in (
            db.query(StudyAsset.notebook_id, func.count(StudyAsset.id))
            .filter(
                StudyAsset.notebook_id.in_(notebook_ids),
                StudyAsset.status != "deleted",
            )
            .group_by(StudyAsset.notebook_id)
            .all()
        )
    }
    ai_action_counts = {
        notebook_id: int(count)
        for notebook_id, count in (
            _filter_ai_actions_for_viewer(
                db.query(AIActionLog.notebook_id, func.count(AIActionLog.id)),
                current_user_id=str(current_user.id),
                workspace_role=workspace_role,
            )
            .filter(
                AIActionLog.workspace_id == workspace_id,
                AIActionLog.notebook_id.in_(notebook_ids),
            )
            .group_by(AIActionLog.notebook_id)
            .all()
        )
        if notebook_id
    }

    notebook_cards = [
        NotebookHomeNotebook(
            id=notebook.id,
            title=notebook.title,
            description=notebook.description,
            notebook_type=notebook.notebook_type,
            updated_at=notebook.updated_at,
            page_count=page_counts.get(notebook.id, 0),
            study_asset_count=study_asset_counts.get(notebook.id, 0),
            ai_action_count=ai_action_counts.get(notebook.id, 0),
        )
        for notebook in notebooks
    ]

    page_rows = (
        db.query(NotebookPage)
        .filter(
            NotebookPage.notebook_id.in_(notebook_ids),
            NotebookPage.is_archived.is_(False),
        )
        .all()
    )
    page_rows.sort(
        key=lambda page: page.last_edited_at or page.updated_at or page.created_at,
        reverse=True,
    )
    recent_pages = [
        NotebookHomePage(
            id=page.id,
            notebook_id=page.notebook_id,
            notebook_title=notebook_titles.get(page.notebook_id, ""),
            title=page.title,
            updated_at=page.updated_at,
            last_edited_at=page.last_edited_at,
            plain_text_preview=(page.plain_text or "")[:180],
        )
        for page in page_rows[:8]
    ]

    study_rows = (
        db.query(StudyAsset)
        .filter(
            StudyAsset.notebook_id.in_(notebook_ids),
            StudyAsset.status != "deleted",
        )
        .order_by(StudyAsset.created_at.desc())
        .limit(8)
        .all()
    )
    recent_study_assets = [
        NotebookHomeStudyAsset(
            id=asset.id,
            notebook_id=asset.notebook_id,
            notebook_title=notebook_titles.get(asset.notebook_id, ""),
            title=asset.title,
            status=asset.status,
            asset_type=asset.asset_type,
            total_chunks=asset.total_chunks,
            created_at=asset.created_at,
        )
        for asset in study_rows
    ]

    action_rows = (
        _filter_ai_actions_for_viewer(
            db.query(AIActionLog, NotebookPage.title, Notebook.title),
            current_user_id=str(current_user.id),
            workspace_role=workspace_role,
        )
        .outerjoin(NotebookPage, NotebookPage.id == AIActionLog.page_id)
        .outerjoin(Notebook, Notebook.id == AIActionLog.notebook_id)
        .filter(AIActionLog.workspace_id == workspace_id)
        .filter(
            (AIActionLog.notebook_id.is_(None))
            | (AIActionLog.notebook_id.in_(notebook_ids))
        )
        .order_by(AIActionLog.created_at.desc())
        .limit(8)
        .all()
    )
    recent_actions = [
        NotebookHomeAIAction(
            id=action.id,
            notebook_id=action.notebook_id,
            page_id=action.page_id,
            notebook_title=notebook_title,
            page_title=page_title,
            action_type=action.action_type,
            output_summary=action.output_summary,
            created_at=action.created_at,
        )
        for action, page_title, notebook_title in action_rows
    ]

    now = datetime.now(timezone.utc)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    actions_today = int(
        _filter_ai_actions_for_viewer(
            db.query(func.count(AIActionLog.id)),
            current_user_id=str(current_user.id),
            workspace_role=workspace_role,
        )
        .filter(
            AIActionLog.workspace_id == workspace_id,
            AIActionLog.created_at >= start_of_day,
        )
        .scalar()
        or 0
    )
    top_action_types = [
        {"action_type": action_type, "count": int(count)}
        for action_type, count in (
            _filter_ai_actions_for_viewer(
                db.query(AIActionLog.action_type, func.count(AIActionLog.id)),
                current_user_id=str(current_user.id),
                workspace_role=workspace_role,
            )
            .filter(
                AIActionLog.workspace_id == workspace_id,
                AIActionLog.created_at >= start_of_day,
            )
            .group_by(AIActionLog.action_type)
            .order_by(func.count(AIActionLog.id).desc())
            .limit(3)
            .all()
        )
    ]

    ranked_notebooks = sorted(
        notebook_cards,
        key=lambda notebook: (
            notebook.study_asset_count * 4
            + notebook.ai_action_count * 3
            + notebook.page_count * 2,
            notebook.updated_at,
        ),
        reverse=True,
    )
    work_themes = [
        NotebookHomeFocusItem(
            notebook_id=notebook.id,
            notebook_title=notebook.title,
            page_count=notebook.page_count,
            study_asset_count=notebook.study_asset_count,
            ai_action_count=notebook.ai_action_count,
        )
        for notebook in ranked_notebooks[:3]
    ]
    long_term_focus = [
        NotebookHomeFocusItem(
            notebook_id=notebook.id,
            notebook_title=notebook.title,
            page_count=notebook.page_count,
            study_asset_count=notebook.study_asset_count,
            ai_action_count=notebook.ai_action_count,
        )
        for notebook in sorted(
            notebook_cards,
            key=lambda notebook: (
                notebook.study_asset_count * 5 + notebook.page_count,
                notebook.updated_at,
            ),
            reverse=True,
        )[:3]
    ]

    recommended_pages: list[NotebookHomePage] = []
    seen_page_ids: set[str] = set()
    for page in recent_pages:
        notebook = next((item for item in notebook_cards if item.id == page.notebook_id), None)
        if notebook is None:
            continue
        if notebook.page_count == 0 and notebook.study_asset_count == 0 and notebook.ai_action_count == 0:
            continue
        if page.id in seen_page_ids:
            continue
        recommended_pages.append(page)
        seen_page_ids.add(page.id)
        if len(recommended_pages) == 3:
            break

    if len(recommended_pages) < 3:
        for page in recent_pages:
            if page.id in seen_page_ids:
                continue
            recommended_pages.append(page)
            seen_page_ids.add(page.id)
            if len(recommended_pages) == 3:
                break

    return NotebookHomeOut(
        notebooks=notebook_cards,
        recent_pages=recent_pages,
        continue_writing=recent_pages[:3],
        recent_study_assets=recent_study_assets,
        ai_today=NotebookHomeAISummary(
            actions_today=actions_today,
            top_action_types=top_action_types,
            recent_actions=recent_actions,
        ),
        work_themes=work_themes,
        long_term_focus=long_term_focus,
        recommended_pages=recommended_pages,
    )


@router.post("", response_model=NotebookOut)
def create_notebook(
    payload: NotebookCreate,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _: None = Depends(require_csrf_protection),
    _quota: None = Depends(require_entitlement("notebooks.max", counter=count_notebooks)),
) -> NotebookOut:
    notebook = Notebook(
        workspace_id=workspace_id,
        created_by=current_user.id,
        title=payload.title,
        slug=make_slug(payload.title),
        description=payload.description,
        notebook_type=payload.notebook_type,
        visibility=payload.visibility,
        project_id=payload.project_id,
        icon=payload.icon,
    )
    db.add(notebook)
    db.flush()
    if not notebook.project_id:
        from app.services.memory_roots import ensure_project_assistant_root
        project = Project(
            workspace_id=workspace_id,
            name=f"Notebook: {payload.title or 'Untitled'}",
        )
        db.add(project)
        db.flush()
        root_memory, _ = ensure_project_assistant_root(db, project, reparent_orphans=False)
        project.assistant_root_memory_id = root_memory.id
        notebook.project_id = project.id
    write_audit_log(
        db,
        workspace_id=workspace_id,
        actor_user_id=current_user.id,
        action="notebook.create",
        target_type="notebook",
        target_id=notebook.id,
    )
    db.commit()
    db.refresh(notebook)
    return NotebookOut.model_validate(notebook, from_attributes=True)


@router.get("/{notebook_id}", response_model=NotebookOut)
def get_notebook(
    notebook_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
) -> NotebookOut:
    notebook = _get_notebook_or_404(
        db,
        notebook_id=notebook_id,
        workspace_id=workspace_id,
        current_user_id=str(current_user.id),
        workspace_role=_get_workspace_role(
            db,
            workspace_id=workspace_id,
            user_id=str(current_user.id),
        ),
    )
    return NotebookOut.model_validate(notebook, from_attributes=True)


@router.patch("/{notebook_id}", response_model=NotebookOut)
def update_notebook(
    notebook_id: str,
    payload: NotebookUpdate,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _: None = Depends(require_csrf_protection),
) -> NotebookOut:
    notebook = _get_notebook_or_404(
        db,
        notebook_id=notebook_id,
        workspace_id=workspace_id,
        current_user_id=str(current_user.id),
        workspace_role=_get_workspace_role(
            db,
            workspace_id=workspace_id,
            user_id=str(current_user.id),
        ),
    )

    if payload.title is not None:
        notebook.title = payload.title
        notebook.slug = make_slug(payload.title)
    if payload.description is not None:
        notebook.description = payload.description
    if payload.icon is not None:
        notebook.icon = payload.icon
    if payload.cover_image_url is not None:
        notebook.cover_image_url = payload.cover_image_url
    if payload.notebook_type is not None:
        notebook.notebook_type = payload.notebook_type
    if payload.visibility is not None:
        notebook.visibility = payload.visibility
    if payload.archived_at is not None:
        notebook.archived_at = payload.archived_at
    notebook.updated_at = datetime.now(timezone.utc)

    write_audit_log(
        db,
        workspace_id=workspace_id,
        actor_user_id=current_user.id,
        action="notebook.update",
        target_type="notebook",
        target_id=notebook.id,
    )
    db.commit()
    db.refresh(notebook)
    return NotebookOut.model_validate(notebook, from_attributes=True)


@router.delete("/{notebook_id}")
def delete_notebook(
    notebook_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _: None = Depends(require_csrf_protection),
) -> dict:
    notebook = _get_notebook_or_404(
        db,
        notebook_id=notebook_id,
        workspace_id=workspace_id,
        current_user_id=str(current_user.id),
        workspace_role=_get_workspace_role(
            db,
            workspace_id=workspace_id,
            user_id=str(current_user.id),
        ),
    )

    notebook.archived_at = datetime.now(timezone.utc)
    notebook.updated_at = datetime.now(timezone.utc)

    write_audit_log(
        db,
        workspace_id=workspace_id,
        actor_user_id=current_user.id,
        action="notebook.delete",
        target_type="notebook",
        target_id=notebook.id,
    )
    db.commit()
    return {"ok": True, "status": "archived"}


# ---------------------------------------------------------------------------
# Pages under a Notebook
# ---------------------------------------------------------------------------


@router.get("/{notebook_id}/pages", response_model=PaginatedPages)
def list_pages(
    notebook_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
) -> PaginatedPages:
    _get_notebook_or_404(
        db,
        notebook_id=notebook_id,
        workspace_id=workspace_id,
        current_user_id=str(current_user.id),
        workspace_role=_get_workspace_role(
            db,
            workspace_id=workspace_id,
            user_id=str(current_user.id),
        ),
    )

    items = (
        db.query(NotebookPage)
        .filter(NotebookPage.notebook_id == notebook_id)
        .order_by(NotebookPage.sort_order, NotebookPage.created_at.desc())
        .all()
    )
    return PaginatedPages(
        items=[PageListItem.model_validate(item, from_attributes=True) for item in items],
        total=len(items),
    )


@router.post("/{notebook_id}/pages", response_model=PageOut)
def create_page(
    notebook_id: str,
    payload: PageCreate,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _: None = Depends(require_csrf_protection),
    _quota: None = Depends(require_entitlement("pages.max", counter=count_pages)),
) -> PageOut:
    notebook = _get_notebook_or_404(
        db,
        notebook_id=notebook_id,
        workspace_id=workspace_id,
        current_user_id=str(current_user.id),
        workspace_role=_get_workspace_role(
            db,
            workspace_id=workspace_id,
            user_id=str(current_user.id),
        ),
    )
    # HIGH-7: reject writes under an archived notebook.
    if notebook.archived_at is not None:
        raise ApiError("not_found", "Notebook not found", status_code=404)

    page = NotebookPage(
        notebook_id=notebook_id,
        created_by=current_user.id,
        title=payload.title,
        slug=make_slug(payload.title),
        page_type=payload.page_type,
        parent_page_id=payload.parent_page_id,
        content_json=payload.content_json,
        plain_text=extract_plain_text(payload.content_json),
        sort_order=payload.sort_order,
    )
    db.add(page)
    db.flush()
    write_audit_log(
        db,
        workspace_id=workspace_id,
        actor_user_id=current_user.id,
        action="notebook_page.create",
        target_type="notebook_page",
        target_id=page.id,
    )
    db.commit()
    db.refresh(page)
    return PageOut.model_validate(page, from_attributes=True)


@router.post("/{notebook_id}/pages/from-conversation", response_model=PageOut)
def create_page_from_conversation(
    notebook_id: str,
    payload: dict[str, Any],
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf: None = Depends(require_csrf_protection),
) -> PageOut:
    """Create a page from a conversation's messages."""
    from app.models import Conversation, Message

    conversation_id = payload.get("conversation_id", "")
    if not conversation_id:
        raise ApiError("invalid_input", "conversation_id is required", status_code=400)

    notebook = _get_notebook_or_404(
        db,
        notebook_id=notebook_id,
        workspace_id=workspace_id,
        current_user_id=str(current_user.id),
        workspace_role=_get_workspace_role(
            db,
            workspace_id=workspace_id,
            user_id=str(current_user.id),
        ),
    )
    if notebook.archived_at is not None:
        raise ApiError("not_found", "Notebook not found", status_code=404)

    conversation = (
        db.query(Conversation)
        .filter(Conversation.id == conversation_id, Conversation.workspace_id == workspace_id)
        .first()
    )
    if not conversation:
        raise ApiError("not_found", "Conversation not found", status_code=404)
    if not can_access_workspace_conversation(
        current_user_id=str(current_user.id),
        workspace_role=_get_workspace_role(
            db,
            workspace_id=workspace_id,
            user_id=str(current_user.id),
        ),
        conversation_created_by=conversation.created_by,
    ):
        raise ApiError("not_found", "Conversation not found", status_code=404)

    messages = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
        .all()
    )

    # Build TipTap JSON from messages
    blocks: list[dict] = []
    for msg in messages:
        role_label = "User" if msg.role == "user" else "AI"
        blocks.append({
            "type": "heading",
            "attrs": {"level": 3},
            "content": [{"type": "text", "text": role_label}],
        })
        # Split content into paragraphs
        for paragraph in (msg.content or "").split("\n\n"):
            if paragraph.strip():
                blocks.append({
                    "type": "paragraph",
                    "content": [{"type": "text", "text": paragraph.strip()}],
                })

    content_json = {"type": "doc", "content": blocks} if blocks else {}
    plain_text = "\n".join(m.content or "" for m in messages)
    title = conversation.title or "Conversation Notes"

    page = NotebookPage(
        notebook_id=notebook_id,
        created_by=current_user.id,
        title=title,
        slug=make_slug(title),
        page_type="document",
        content_json=content_json,
        plain_text=plain_text,
        source_conversation_id=conversation_id,
    )
    db.add(page)
    write_audit_log(db, workspace_id=workspace_id, actor_user_id=current_user.id,
                    action="page.create_from_conversation", target_type="page", target_id=page.id)
    db.commit()
    db.refresh(page)
    return PageOut.model_validate(page, from_attributes=True)


# ---------------------------------------------------------------------------
# Page direct access (pages_router)
# ---------------------------------------------------------------------------


@pages_router.get("/search")
def search_pages(
    q: str = "",
    notebook_id: str | None = None,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
) -> PaginatedPages:
    """Search pages by plain_text content within workspace notebooks."""
    workspace_role = _get_workspace_role(
        db,
        workspace_id=workspace_id,
        user_id=str(current_user.id),
    )
    query = _filter_readable_notebooks(
        db.query(NotebookPage)
        .join(Notebook, Notebook.id == NotebookPage.notebook_id)
        .filter(
            Notebook.workspace_id == workspace_id,
            Notebook.archived_at.is_(None),
        ),
        current_user_id=str(current_user.id),
        workspace_role=workspace_role,
    ).filter(NotebookPage.is_archived.is_(False))
    if notebook_id:
        _get_notebook_or_404(
            db,
            notebook_id=notebook_id,
            workspace_id=workspace_id,
            current_user_id=str(current_user.id),
            workspace_role=workspace_role,
        )
    if notebook_id:
        query = query.filter(NotebookPage.notebook_id == notebook_id)
    if q.strip():
        safe_q = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.filter(NotebookPage.plain_text.ilike(f"%{safe_q}%", escape="\\"))
    items = query.order_by(NotebookPage.updated_at.desc()).limit(50).all()
    return PaginatedPages(
        items=[PageListItem.model_validate(item, from_attributes=True) for item in items],
        total=len(items),
    )


@pages_router.get("/{page_id}", response_model=PageOut)
def get_page(
    page_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
) -> PageOut:
    page = _get_page_or_404(
        db,
        page_id,
        workspace_id,
        current_user_id=str(current_user.id),
        workspace_role=_get_workspace_role(
            db,
            workspace_id=workspace_id,
            user_id=str(current_user.id),
        ),
    )
    return PageOut.model_validate(page, from_attributes=True)


@pages_router.patch("/{page_id}", response_model=PageOut)
def update_page(
    page_id: str,
    payload: PageUpdate,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _: None = Depends(require_csrf_protection),
) -> PageOut:
    page = _get_page_or_404(
        db,
        page_id,
        workspace_id,
        current_user_id=str(current_user.id),
        workspace_role=_get_workspace_role(
            db,
            workspace_id=workspace_id,
            user_id=str(current_user.id),
        ),
    )
    # HIGH-7: block writes to pages inside an archived notebook. Allow the
    # un-archive path (payload.is_archived explicitly False) to go through so
    # the UI can recover a mistakenly-deleted page.
    notebook = db.query(Notebook).filter(Notebook.id == page.notebook_id).first()
    if notebook is not None and notebook.archived_at is not None:
        raise ApiError("not_found", "Notebook not found", status_code=404)
    if page.is_archived and payload.is_archived is not False:
        # Only a restore (is_archived=False) may touch an archived page.
        raise ApiError("not_found", "Page not found", status_code=404)

    if payload.title is not None:
        page.title = payload.title
        page.slug = make_slug(payload.title)
    if payload.content_json is not None:
        page.content_json = payload.content_json
        page.plain_text = extract_plain_text(payload.content_json)
    if payload.parent_page_id is not None:
        page.parent_page_id = payload.parent_page_id
    if payload.page_type is not None:
        page.page_type = payload.page_type
    if payload.sort_order is not None:
        page.sort_order = payload.sort_order
    if payload.is_pinned is not None:
        page.is_pinned = payload.is_pinned
    if payload.is_archived is not None:
        page.is_archived = payload.is_archived
    page.last_edited_at = datetime.now(timezone.utc)
    page.updated_at = datetime.now(timezone.utc)

    write_audit_log(
        db,
        workspace_id=workspace_id,
        actor_user_id=current_user.id,
        action="notebook_page.update",
        target_type="notebook_page",
        target_id=page.id,
    )
    db.commit()
    db.refresh(page)
    return PageOut.model_validate(page, from_attributes=True)


@pages_router.delete("/{page_id}")
def delete_page(
    page_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _: None = Depends(require_csrf_protection),
) -> dict:
    """Soft-delete a notebook page.

    Spec §26 requires delete operations to preserve the evidence chain.
    Hard-deleting a page cascades into ``notebook_page_versions`` and
    ``notebook_blocks`` and breaks every ``MemoryEvidence`` whose
    ``metadata_json.source_id`` pointed at this page. We therefore flip
    ``is_archived`` and update ``last_edited_at``; the ``purge_stale_records``
    background task is responsible for eventually hard-deleting archived rows.
    """
    page = _get_page_or_404(
        db,
        page_id,
        workspace_id,
        current_user_id=str(current_user.id),
        workspace_role=_get_workspace_role(
            db,
            workspace_id=workspace_id,
            user_id=str(current_user.id),
        ),
    )

    page.is_archived = True
    page.last_edited_at = datetime.now(timezone.utc)
    page.updated_at = datetime.now(timezone.utc)
    write_audit_log(
        db,
        workspace_id=workspace_id,
        actor_user_id=current_user.id,
        action="notebook_page.archive",
        target_type="notebook_page",
        target_id=page.id,
    )
    db.commit()
    return {"ok": True, "status": "archived"}


@pages_router.post("/{page_id}/duplicate", response_model=PageOut)
def duplicate_page(
    page_id: str,
    payload: PageDuplicatePayload | None = None,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _: None = Depends(require_csrf_protection),
) -> PageOut:
    """Duplicate a page into the same notebook/parent.

    Copies the TipTap doc verbatim (regenerating every ``attrs.block_id`` so
    the clone has its own stable block identifiers), clones NotebookBlock
    rows and NotebookAttachment rows. Does not copy page versions — the
    clone starts a fresh history.
    """
    page = _get_page_or_404(
        db,
        page_id,
        workspace_id,
        current_user_id=str(current_user.id),
        workspace_role=_get_workspace_role(
            db,
            workspace_id=workspace_id,
            user_id=str(current_user.id),
        ),
    )
    # Archived notebook or archived page → 404 to avoid spawning orphan rows.
    notebook = db.query(Notebook).filter(Notebook.id == page.notebook_id).first()
    if notebook is None or notebook.archived_at is not None:
        raise ApiError("not_found", "Notebook not found", status_code=404)
    if page.is_archived:
        raise ApiError("not_found", "Page not found", status_code=404)

    new_title = (payload.title if payload and payload.title else f"{page.title} (copy)")
    # Clone doc, regenerating every top-level node's block_id
    from copy import deepcopy
    new_doc = deepcopy(page.content_json) if isinstance(page.content_json, dict) else {}
    if isinstance(new_doc.get("content"), list):
        for node in new_doc["content"]:
            if isinstance(node, dict):
                attrs = node.setdefault("attrs", {})
                attrs["block_id"] = str(uuid4())

    new_page = NotebookPage(
        notebook_id=page.notebook_id,
        created_by=current_user.id,
        parent_page_id=page.parent_page_id,
        title=new_title,
        slug=make_slug(new_title),
        page_type=page.page_type,
        content_json=new_doc,
        plain_text=page.plain_text,
        summary_text=page.summary_text,
        ai_keywords_json=list(page.ai_keywords_json or []),
        sort_order=page.sort_order + 1,
    )
    db.add(new_page)
    db.flush()

    # Clone NotebookBlock rows aligned with the regenerated block_ids
    from app.models import NotebookBlock as _NB
    old_blocks = db.query(_NB).filter(_NB.page_id == page.id).order_by(_NB.sort_order).all()
    if isinstance(new_doc.get("content"), list):
        new_block_ids = [
            (n.get("attrs") or {}).get("block_id")
            for n in new_doc["content"] if isinstance(n, dict)
        ]
    else:
        new_block_ids = []
    for idx, src in enumerate(old_blocks):
        bid = (
            new_block_ids[idx]
            if idx < len(new_block_ids) and new_block_ids[idx]
            else str(uuid4())
        )
        db.add(_NB(
            id=bid,
            page_id=new_page.id,
            block_type=src.block_type,
            sort_order=src.sort_order,
            content_json=deepcopy(src.content_json) if isinstance(src.content_json, dict) else {},
            plain_text=src.plain_text or "",
            created_by=current_user.id,
            metadata_json=deepcopy(src.metadata_json) if isinstance(src.metadata_json, dict) else {},
        ))

    # Clone attachments (keep the S3 object_key — attachments remain shared,
    # which is acceptable because the object_key is still scoped to the
    # workspace and deletion is per-attachment row).
    attachments = (
        db.query(NotebookAttachment)
        .filter(NotebookAttachment.page_id == page.id)
        .all()
    )
    for att in attachments:
        db.add(NotebookAttachment(
            page_id=new_page.id,
            data_item_id=att.data_item_id,
            attachment_type=att.attachment_type,
            title=att.title,
            meta_json=dict(att.meta_json or {}),
        ))

    write_audit_log(
        db,
        workspace_id=workspace_id,
        actor_user_id=current_user.id,
        action="notebook_page.duplicate",
        target_type="notebook_page",
        target_id=new_page.id,
    )
    db.commit()
    db.refresh(new_page)
    return PageOut.model_validate(new_page, from_attributes=True)


@pages_router.post("/{page_id}/move", response_model=PageOut)
def move_page(
    page_id: str,
    payload: PageMovePayload,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _: None = Depends(require_csrf_protection),
) -> PageOut:
    """Move a page to a different notebook and/or reparent it in place.

    Target notebook must live in the same workspace and be readable by the
    caller (visibility + archive checks). Cross-workspace moves are 404
    (never leak a foreign notebook's existence).
    """
    page = _get_page_or_404(
        db,
        page_id,
        workspace_id,
        current_user_id=str(current_user.id),
        workspace_role=_get_workspace_role(
            db,
            workspace_id=workspace_id,
            user_id=str(current_user.id),
        ),
    )
    source_notebook = db.query(Notebook).filter(Notebook.id == page.notebook_id).first()
    if source_notebook is None or source_notebook.archived_at is not None:
        raise ApiError("not_found", "Notebook not found", status_code=404)

    workspace_role = _get_workspace_role(
        db,
        workspace_id=workspace_id,
        user_id=str(current_user.id),
    )

    target_notebook = source_notebook
    if payload.notebook_id and str(payload.notebook_id) != str(page.notebook_id):
        target_notebook = _get_notebook_or_404(
            db,
            notebook_id=str(payload.notebook_id),
            workspace_id=workspace_id,
            current_user_id=str(current_user.id),
            workspace_role=workspace_role,
        )
        if target_notebook.archived_at is not None:
            raise ApiError("not_found", "Notebook not found", status_code=404)

    # Parent page (if given) must live in the destination notebook.
    parent_id = payload.parent_page_id
    if parent_id:
        parent = db.query(NotebookPage).filter(NotebookPage.id == parent_id).first()
        if parent is None or str(parent.notebook_id) != str(target_notebook.id):
            raise ApiError(
                "invalid_input",
                "parent_page_id must reside in the target notebook",
                status_code=400,
            )
        # Prevent moving a page under itself or any of its descendants.
        visited: set[str] = set()
        cur = parent
        while cur is not None and cur.id not in visited:
            visited.add(cur.id)
            if str(cur.id) == str(page.id):
                raise ApiError(
                    "invalid_input",
                    "cannot move a page under itself",
                    status_code=400,
                )
            if not cur.parent_page_id:
                break
            cur = db.query(NotebookPage).filter(NotebookPage.id == cur.parent_page_id).first()

    page.notebook_id = target_notebook.id
    page.parent_page_id = parent_id
    if payload.sort_order is not None:
        page.sort_order = max(0, int(payload.sort_order))
    page.last_edited_at = datetime.now(timezone.utc)
    page.updated_at = datetime.now(timezone.utc)

    write_audit_log(
        db,
        workspace_id=workspace_id,
        actor_user_id=current_user.id,
        action="notebook_page.move",
        target_type="notebook_page",
        target_id=page.id,
    )
    db.commit()
    db.refresh(page)
    return PageOut.model_validate(page, from_attributes=True)


# ---------------------------------------------------------------------------
# Page attachments (S2)
# ---------------------------------------------------------------------------


_ATTACHMENT_TYPE_MAP: dict[str, str] = {
    "application/pdf": "pdf",
    "image/png": "image",
    "image/jpeg": "image",
    "image/gif": "image",
    "image/webp": "image",
    "audio/mpeg": "audio",
    "audio/wav": "audio",
    "video/mp4": "video",
}


def _classify_attachment(mime: str | None) -> str:
    if not mime:
        return "other"
    if mime in _ATTACHMENT_TYPE_MAP:
        return _ATTACHMENT_TYPE_MAP[mime]
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("audio/"):
        return "audio"
    if mime.startswith("video/"):
        return "video"
    return "other"


@pages_router.post("/{page_id}/attachments/upload")
async def upload_page_attachment(
    page_id: str,
    file: UploadFile = File(...),
    title: str = Form(""),
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf: None = Depends(require_csrf_protection),
) -> dict[str, Any]:
    """Upload a file as an attachment of the page. Stores the binary in
    the S2 attachments bucket and returns the new NotebookAttachment row.

    Security (audit V1/V2/V5):
    - Reject HTML/SVG/XML via extension and MIME blacklist.
    - Validate declared MIME against extension whitelist.
    - Check magic bytes (signature) before writing to S3.
    - Stream-read body with a size cap so oversized uploads are rejected
      without buffering the full payload into memory.
    - Force ``Content-Type: application/octet-stream`` on S3 PUT unless the
      declared MIME is in the attachment whitelist — blocks stored XSS if
      the MinIO reverse-proxy shares a cookie domain with the app.
    """
    page = _get_page_or_404(
        db,
        page_id,
        workspace_id,
        current_user_id=str(current_user.id),
        workspace_role=_get_workspace_role(
            db,
            workspace_id=workspace_id,
            user_id=str(current_user.id),
        ),
    )
    # HIGH-7: reject attachment writes on archived notebook/page.
    notebook_for_attach = db.query(Notebook).filter(Notebook.id == page.notebook_id).first()
    if (
        notebook_for_attach is None
        or notebook_for_attach.archived_at is not None
        or page.is_archived
    ):
        raise ApiError("not_found", "Page not found", status_code=404)

    max_bytes = settings.notebook_attachment_max_bytes

    # V5: size pre-check via the multipart-part size (or Content-Length
    # header) before touching the request body. Streaming read below is
    # the true guard; this is a fast-fail so we never even start reading
    # an obviously-too-large upload.
    declared_length: int | None = None
    part_size = getattr(file, "size", None)
    if isinstance(part_size, int) and part_size >= 0:
        declared_length = part_size
    else:
        headers = getattr(file, "headers", None)
        header_length = None
        if headers is not None:
            try:
                header_length = headers.get("content-length")
            except Exception:  # noqa: BLE001
                header_length = None
        if header_length is not None:
            try:
                declared_length = int(header_length)
            except (TypeError, ValueError):
                declared_length = None
    if declared_length is not None and declared_length > max_bytes:
        raise ApiError(
            "file_too_large",
            f"Attachment exceeds {max_bytes} bytes",
            status_code=413,
        )

    # V1 + V5: streaming read with +1 byte to detect overflow without
    # buffering arbitrary-size payloads.
    chunks: list[bytes] = []
    total = 0
    chunk_size = 1024 * 1024  # 1 MiB
    while True:
        piece = await file.read(chunk_size)
        if not piece:
            break
        total += len(piece)
        if total > max_bytes:
            raise ApiError(
                "file_too_large",
                f"Attachment exceeds {max_bytes} bytes",
                status_code=413,
            )
        chunks.append(piece)
    body = b"".join(chunks)
    size = len(body)

    filename = file.filename or "file"
    # V1: reject extension blacklist first (fast fail before any S3 I/O).
    lowered = filename.lower()
    for bad_ext in storage_service.ATTACHMENT_EXTENSION_BLACKLIST:
        if lowered.endswith(bad_ext):
            raise ApiError(
                "unsupported_media_type",
                "Uploaded file type is not allowed",
                status_code=415,
            )

    declared_mime = (file.content_type or "application/octet-stream").split(";", 1)[0].strip().lower()
    # V1: reject blacklisted MIME types outright.
    if declared_mime in storage_service.ATTACHMENT_MIME_BLACKLIST:
        raise ApiError(
            "unsupported_media_type",
            "Uploaded file type is not allowed",
            status_code=415,
        )

    # V1: run the shared workspace upload declaration guard when the
    # extension is recognized. Falls back to a safer coerced media type
    # for unknown extensions (e.g. .zip, .log). Declaration failures
    # raise ApiError directly.
    try:
        canonical_mime = validate_workspace_upload_declaration(filename, declared_mime)
    except ApiError:
        raise
    except Exception:
        canonical_mime = "application/octet-stream"

    # V1: magic-bytes / signature check. Only the first ~8KiB is peeked.
    # For declared MIME types we know how to validate we require a match;
    # anything unknown silently passes as octet-stream.
    prefix = body[:UPLOAD_SIGNATURE_READ_BYTES]
    try:
        validate_workspace_upload_signature(prefix=prefix, media_type=canonical_mime)
    except ApiError:
        raise

    # V2: force application/octet-stream at rest unless the declared
    # canonical MIME is in the whitelist. This means uploaded .zip files
    # still render their "real" type only if they came in as the right
    # MIME + signature.
    if canonical_mime in storage_service.ATTACHMENT_MIME_WHITELIST:
        storage_mime = canonical_mime
    else:
        storage_mime = "application/octet-stream"

    safe_name = storage_service.sanitize_filename(filename)
    object_key = f"{workspace_id}/{page.id}/{uuid4().hex}/{safe_name}"

    storage_service.get_s3_client().put_object(
        Bucket=settings.s3_notebook_attachments_bucket,
        Key=object_key,
        Body=body,
        ContentType=storage_mime,
    )

    attachment = NotebookAttachment(
        page_id=page.id,
        data_item_id=None,
        attachment_type=_classify_attachment(canonical_mime),
        title=title or safe_name,
        meta_json={
            "object_key": object_key,
            "mime_type": storage_mime,
            "declared_mime_type": canonical_mime,
            "size_bytes": size,
        },
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)

    return {
        "attachment_id": attachment.id,
        "filename": safe_name,
        "mime_type": storage_mime,
        "size_bytes": size,
        "attachment_type": attachment.attachment_type,
    }


@pages_router.delete("/{page_id}/attachments/{attachment_id}")
def delete_page_attachment(
    page_id: str,
    attachment_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf: None = Depends(require_csrf_protection),
) -> dict[str, Any]:
    """Delete an attachment row and its S3 object (spec §13.4).

    Nested path here (not spec's ``DELETE /api/v1/attachments/{id}``) because
    ``attachments.py`` already registers a ``GET /{id}/url`` on the flat
    prefix; we also register ``delete_attachment`` there for the flat shape.
    This nested variant is the primary path — it keeps workspace resolution
    cheap (page → notebook → workspace) and matches the upload path's
    structure.
    """
    page = _get_page_or_404(
        db,
        page_id,
        workspace_id,
        current_user_id=str(current_user.id),
        workspace_role=_get_workspace_role(
            db,
            workspace_id=workspace_id,
            user_id=str(current_user.id),
        ),
    )
    notebook = db.query(Notebook).filter(Notebook.id == page.notebook_id).first()
    if notebook is None or notebook.archived_at is not None:
        raise ApiError("not_found", "Page not found", status_code=404)

    att = (
        db.query(NotebookAttachment)
        .filter(
            NotebookAttachment.id == attachment_id,
            NotebookAttachment.page_id == page.id,
        )
        .first()
    )
    if att is None:
        raise ApiError("not_found", "Attachment not found", status_code=404)

    object_key = (att.meta_json or {}).get("object_key")
    if object_key:
        try:
            storage_service.get_s3_client().delete_object(
                Bucket=settings.s3_notebook_attachments_bucket,
                Key=object_key,
            )
        except Exception:
            # Best-effort — DB row removal is the authoritative delete.
            import logging
            logging.getLogger(__name__).warning(
                "delete_page_attachment: S3 delete failed for key=%s", object_key,
                exc_info=True,
            )

    db.delete(att)
    write_audit_log(
        db,
        workspace_id=workspace_id,
        actor_user_id=current_user.id,
        action="notebook_attachment.delete",
        target_type="notebook_attachment",
        target_id=str(attachment_id),
    )
    db.commit()
    return {"ok": True, "status": "deleted", "attachment_id": attachment_id}


# ---------------------------------------------------------------------------
# Page version history
# ---------------------------------------------------------------------------


@pages_router.post("/{page_id}/snapshot", response_model=PageVersionOut)
def create_page_snapshot(
    page_id: str,
    payload: dict[str, Any] | None = None,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf: None = Depends(require_csrf_protection),
) -> PageVersionOut:
    """Create a manual snapshot of the current page content."""
    page = _get_page_or_404(
        db,
        page_id,
        workspace_id,
        current_user_id=str(current_user.id),
        workspace_role=_get_workspace_role(
            db,
            workspace_id=workspace_id,
            user_id=str(current_user.id),
        ),
    )

    # Get next version number
    latest_version = (
        db.query(NotebookPageVersion)
        .filter(NotebookPageVersion.page_id == page_id)
        .order_by(NotebookPageVersion.version_no.desc())
        .first()
    )
    next_version = (latest_version.version_no + 1) if latest_version else 1

    version = NotebookPageVersion(
        page_id=page_id,
        version_no=next_version,
        snapshot_json=page.content_json,
        snapshot_text=page.plain_text,
        source=(payload or {}).get("source", "manual"),
        created_by=current_user.id,
    )
    db.add(version)
    db.commit()
    db.refresh(version)
    return PageVersionOut.model_validate(version, from_attributes=True)


@pages_router.get("/{page_id}/versions")
def list_page_versions(
    page_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
) -> list[PageVersionOut]:
    """List all snapshots for a page."""
    _get_page_or_404(
        db,
        page_id,
        workspace_id,
        current_user_id=str(current_user.id),
        workspace_role=_get_workspace_role(
            db,
            workspace_id=workspace_id,
            user_id=str(current_user.id),
        ),
    )
    versions = (
        db.query(NotebookPageVersion)
        .filter(NotebookPageVersion.page_id == page_id)
        .order_by(NotebookPageVersion.version_no.desc())
        .all()
    )
    return [PageVersionOut.model_validate(v, from_attributes=True) for v in versions]


# ---------------------------------------------------------------------------
# Page export
# ---------------------------------------------------------------------------


@pages_router.get("/{page_id}/export")
def export_page(
    page_id: str,
    format: str = "markdown",
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
) -> PlainTextResponse:
    """Export page content as Markdown."""
    page = _get_page_or_404(
        db,
        page_id,
        workspace_id,
        current_user_id=str(current_user.id),
        workspace_role=_get_workspace_role(
            db,
            workspace_id=workspace_id,
            user_id=str(current_user.id),
        ),
    )

    if format == "markdown":
        md = _tiptap_json_to_markdown(page.content_json, page.title)
        return PlainTextResponse(content=md, media_type="text/markdown")
    else:
        return PlainTextResponse(content=page.plain_text, media_type="text/plain")


# ---------------------------------------------------------------------------
# Page memory connections
# ---------------------------------------------------------------------------


@router.post("/{notebook_id}/memory/extract-from-text")
async def extract_memory_from_selection(
    notebook_id: str,
    payload: dict[str, Any],
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf: None = Depends(require_csrf_protection),
) -> dict:
    """Run the memory pipeline against an arbitrary text snippet.

    Used by the reference-document viewer: the user highlights a passage in
    a PDF / Office file and asks "extract memory from this". We resolve
    project context from the notebook and run the same UnifiedMemoryPipeline
    that page extraction uses, so the resulting candidates land in the
    same memory panel.
    """
    text = str(payload.get("text") or "").strip()
    if not text:
        raise ApiError("invalid_input", "text is required", status_code=400)

    notebook = (
        db.query(Notebook)
        .filter(Notebook.id == notebook_id, Notebook.workspace_id == workspace_id)
        .first()
    )
    if not notebook:
        raise ApiError("not_found", "Notebook not found", status_code=404)
    if not _can_read_notebook(
        notebook,
        workspace_id=workspace_id,
        current_user_id=str(current_user.id),
        workspace_role=_get_workspace_role(
            db, workspace_id=workspace_id, user_id=str(current_user.id),
        ),
    ):
        raise ApiError("not_found", "Notebook not found", status_code=404)
    if not notebook.project_id:
        raise ApiError(
            "no_project",
            "Notebook is not linked to a project; memory extraction requires one.",
            status_code=400,
        )

    source_label = str(payload.get("source_label") or "")[:200]
    source_ref = str(payload.get("source_ref") or "")[:200]

    from app.services.note_memory_bridge import extract_memory_from_text

    extraction = await extract_memory_from_text(
        db,
        notebook_id=str(notebook.id),
        workspace_id=str(workspace_id),
        user_id=str(current_user.id),
        text=text,
        source_label=source_label,
        source_ref=source_ref,
    )
    db.commit()
    if extraction.graph_changed:
        from app.services.memory_graph_events import bump_project_memory_graph_revision

        bump_project_memory_graph_revision(
            workspace_id=str(workspace_id), project_id=str(notebook.project_id)
        )
    return {
        "run_id": extraction.run.id if extraction.run else None,
        "status": extraction.run.status if extraction.run else "no_content",
        "item_count": len(extraction.items or []),
    }


@pages_router.get("/{page_id}/highlight-references")
def list_page_highlight_references(
    page_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
) -> dict:
    """Return PDF highlights that link back to this page.

    Each highlight is a `pdf_highlight` annotation whose payload's
    `links` array contains `{kind: "page", id: <page_id>}`. The query
    crosses annotations → data_items → datasets → projects to enforce
    workspace ownership; foreign-workspace highlights are dropped.
    """
    page = _get_page_or_404(
        db,
        page_id,
        workspace_id,
        current_user_id=str(current_user.id),
        workspace_role=_get_workspace_role(
            db, workspace_id=workspace_id, user_id=str(current_user.id),
        ),
    )
    _ = page  # access-checked

    from app.models import Annotation, DataItem, Dataset, Project, StudyAsset

    from sqlalchemy import or_

    rows = (
        db.query(Annotation, DataItem, Dataset, Project, StudyAsset)
        .join(DataItem, DataItem.id == Annotation.data_item_id)
        .join(Dataset, Dataset.id == DataItem.dataset_id)
        .join(Project, Project.id == Dataset.project_id)
        .outerjoin(StudyAsset, StudyAsset.data_item_id == DataItem.id)
        .filter(
            Annotation.type == "pdf_highlight",
            Project.workspace_id == workspace_id,
            DataItem.deleted_at.is_(None),
            # Allow PDF highlights without a StudyAsset (e.g. attachment
            # highlights) but hide ones whose asset was soft-deleted, since
            # clicking them would 404 on `/study-assets/{asset_id}`.
            or_(StudyAsset.id.is_(None), StudyAsset.status != "deleted"),
        )
        .all()
    )
    items: list[dict[str, Any]] = []
    for ann, item, _ds, _proj, asset in rows:
        payload = ann.payload_json or {}
        links = payload.get("links")
        if not isinstance(links, list):
            continue
        if not any(
            isinstance(link, dict)
            and link.get("kind") == "page"
            and link.get("id") == page_id
            for link in links
        ):
            continue
        items.append(
            {
                "annotation_id": str(ann.id),
                "data_item_id": str(item.id),
                "asset_id": str(asset.id) if asset else None,
                "asset_title": (asset.title if asset else item.filename)
                or item.filename,
                "page": int(payload.get("page") or 0) or None,
                "text": str(payload.get("text") or "")[:280],
                "color": payload.get("color"),
                "note": payload.get("note"),
                "created_at": ann.created_at.isoformat()
                if ann.created_at
                else None,
            }
        )
    items.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return {"items": items}


@pages_router.post("/{page_id}/memory/extract")
async def extract_page_memories(
    page_id: str,
    background: bool = False,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf: None = Depends(require_csrf_protection),
) -> dict:
    """Trigger memory extraction from page content.

    Uses the full UnifiedMemoryPipeline (12-stage pipeline).
    Pass ``?background=true`` to run asynchronously via Celery.
    """
    page = _get_page_or_404(
        db,
        page_id,
        workspace_id,
        current_user_id=str(current_user.id),
        workspace_role=_get_workspace_role(
            db,
            workspace_id=workspace_id,
            user_id=str(current_user.id),
        ),
    )

    if background:
        from app.tasks.worker_tasks import extract_notebook_page_memories
        task = extract_notebook_page_memories.delay(
            str(workspace_id), str(page_id), str(current_user.id),
        )
        return {"status": "queued", "task_id": task.id}

    from app.services.note_memory_bridge import extract_memory_candidates
    extraction = await extract_memory_candidates(
        db, page_id=page_id, workspace_id=workspace_id, user_id=str(current_user.id),
    )
    db.commit()
    if extraction.graph_changed:
        from app.services.memory_graph_events import bump_project_memory_graph_revision
        notebook = db.query(Notebook).filter(Notebook.id == page.notebook_id).first()
        if notebook and notebook.project_id:
            bump_project_memory_graph_revision(workspace_id=str(workspace_id), project_id=str(notebook.project_id))
    return {
        "run_id": extraction.run.id if extraction.run else None,
        "status": extraction.run.status if extraction.run else "no_content",
        "item_count": len(extraction.items or []),
    }


@pages_router.get("/{page_id}/memory/links")
def get_page_memory_links(
    page_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
) -> dict:
    """Get memory candidates extracted from this page."""
    page = _get_page_or_404(
        db,
        page_id,
        workspace_id,
        current_user_id=str(current_user.id),
        workspace_role=_get_workspace_role(
            db,
            workspace_id=workspace_id,
            user_id=str(current_user.id),
        ),
    )
    _ = page

    # Find write runs for this page
    from app.models import MemoryWriteRun, MemoryWriteItem
    runs = (
        db.query(MemoryWriteRun)
        .filter(MemoryWriteRun.metadata_json["source_type"].as_string() == "notebook_page")
        .filter(MemoryWriteRun.metadata_json["source_id"].as_string() == page_id)
        .order_by(MemoryWriteRun.created_at.desc())
        .limit(5)
        .all()
    )
    run_ids = [r.id for r in runs]
    if not run_ids:
        return {"items": []}

    items = (
        db.query(MemoryWriteItem)
        .filter(MemoryWriteItem.run_id.in_(run_ids))
        .order_by(MemoryWriteItem.created_at.desc())
        .all()
    )

    return {
        "items": [
            {
                "id": item.id,
                "fact": item.candidate_text or "",
                "category": item.category or "fact",
                "importance": "high" if (item.importance or 0) > 0.7 else ("medium" if (item.importance or 0) > 0.3 else "low"),
                "decision": item.decision or "pending",
            }
            for item in items
        ]
    }


@pages_router.post("/{page_id}/memory/confirm")
async def confirm_memory_candidate(
    page_id: str,
    payload: dict[str, Any],
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf: None = Depends(require_csrf_protection),
) -> dict:
    """Confirm a memory candidate — runs the full promote pipeline.

    Creates a real Memory node with embedding and evidence, not just a
    decision flag change.
    """
    page = _get_page_or_404(
        db,
        page_id,
        workspace_id,
        current_user_id=str(current_user.id),
        workspace_role=_get_workspace_role(
            db,
            workspace_id=workspace_id,
            user_id=str(current_user.id),
        ),
    )
    item_id = payload.get("item_id", "")
    from app.models import MemoryWriteItem, MemoryWriteRun
    item = (
        db.query(MemoryWriteItem)
        .join(MemoryWriteRun, MemoryWriteRun.id == MemoryWriteItem.run_id)
        .filter(MemoryWriteItem.id == item_id, MemoryWriteRun.workspace_id == workspace_id)
        .first()
    )
    if not item:
        raise ApiError("not_found", "Memory item not found", status_code=404)

    notebook = db.query(Notebook).filter(Notebook.id == page.notebook_id).first()
    project_id = str(notebook.project_id) if notebook and notebook.project_id else None
    if not project_id:
        raise ApiError("bad_request", "Notebook has no linked project", status_code=400)

    from app.services.unified_memory_pipeline import promote_write_item

    memory = await promote_write_item(
        db,
        item=item,
        workspace_id=workspace_id,
        project_id=project_id,
        user_id=str(current_user.id),
    )
    # Spec §5.1 / §9.5: record the page-span ↔ memory bridge so the UI can
    # show "this span produced these memories" without re-scanning evidence.
    if memory is not None:
        from app.models import (
            MemoryEvidence as _Evidence,
            NotebookSelectionMemoryLink as _Link,
        )
        item_meta = item.metadata_json if isinstance(item.metadata_json, dict) else {}
        start_offset = item_meta.get("start_offset")
        end_offset = item_meta.get("end_offset")
        block_id = item_meta.get("block_id") or payload.get("block_id")
        evidence = (
            db.query(_Evidence)
            .filter(
                _Evidence.memory_id == memory.id,
                _Evidence.source_type == "notebook_page",
            )
            .order_by(_Evidence.created_at.desc())
            .first()
        )
        db.add(_Link(
            page_id=page.id,
            block_id=str(block_id) if block_id else None,
            start_offset=int(start_offset) if isinstance(start_offset, int) else None,
            end_offset=int(end_offset) if isinstance(end_offset, int) else None,
            memory_id=memory.id,
            evidence_id=evidence.id if evidence else None,
        ))
    db.commit()
    # Bump graph revision AFTER commit so Redis revision is consistent with DB state
    if memory:
        from app.services.memory_graph_events import bump_project_memory_graph_revision
        bump_project_memory_graph_revision(workspace_id=str(workspace_id), project_id=project_id)
    return {
        "ok": True,
        "memory_id": str(memory.id) if memory else None,
    }


@pages_router.post("/{page_id}/memory/reject")
def reject_memory_candidate(
    page_id: str,
    payload: dict[str, Any],
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf: None = Depends(require_csrf_protection),
) -> dict:
    """Reject a memory extraction candidate."""
    _get_page_or_404(
        db,
        page_id,
        workspace_id,
        current_user_id=str(current_user.id),
        workspace_role=_get_workspace_role(
            db,
            workspace_id=workspace_id,
            user_id=str(current_user.id),
        ),
    )
    item_id = payload.get("item_id", "")
    reason = str(payload.get("reason", "")).strip() or None
    from app.models import Memory, MemoryWriteItem, MemoryWriteRun
    item = (
        db.query(MemoryWriteItem)
        .join(MemoryWriteRun, MemoryWriteRun.id == MemoryWriteItem.run_id)
        .filter(MemoryWriteItem.id == item_id, MemoryWriteRun.workspace_id == workspace_id)
        .first()
    )
    if not item:
        raise ApiError("not_found", "Memory item not found", status_code=404)
    item.decision = "rejected"
    # Record rejection reason in metadata for future confidence adjustment
    meta = dict(item.metadata_json or {}) if isinstance(item.metadata_json, dict) else {}
    meta["rejection_reason"] = reason
    meta["rejected_by"] = str(current_user.id)
    item.metadata_json = meta

    if item.target_memory_id:
        target_memory = db.get(Memory, item.target_memory_id)
        if (
            target_memory is not None
            and target_memory.workspace_id == workspace_id
            and target_memory.node_status == "active"
        ):
            target_memory.confidence = min(
                float(target_memory.confidence or 0.0),
                max(float(item.importance or 0.0) - 0.2, 0.0),
            )
            target_meta = (
                dict(target_memory.metadata_json or {})
                if isinstance(target_memory.metadata_json, dict)
                else {}
            )
            target_meta["last_rejected_write_item_id"] = item.id
            target_meta["last_rejected_at"] = datetime.now(timezone.utc).isoformat()
            if reason:
                target_meta["last_rejection_reason"] = reason
            target_memory.metadata_json = target_meta

    # Spec §9.0.3: downrank future same-class candidates by matching the
    # first 100 chars of raw/candidate text (cheap lexical fingerprint) —
    # avoids a new DB column while still curbing the "extract the same
    # sentence 5 times" abuse pattern.
    fingerprint = (item.candidate_text or "")[:100].strip()
    rejected_lineage: list[str] = []
    if fingerprint:
        # Constrain to runs in the same workspace. `MemoryWriteRun.id in
        # MemoryWriteItem.run_id` is a straight join (run_id is a FK).
        similar = (
            db.query(MemoryWriteItem)
            .join(MemoryWriteRun, MemoryWriteRun.id == MemoryWriteItem.run_id)
            .filter(
                MemoryWriteRun.workspace_id == workspace_id,
                MemoryWriteItem.id != item.id,
                MemoryWriteItem.decision == "pending",
            )
            .limit(200)
            .all()
        )
        # Short-enough prefix to catch genuine paraphrases, long enough to
        # avoid false positives across unrelated content.
        prefix_len = min(len(fingerprint), 30)
        prefix = fingerprint[:prefix_len]
        for sibling in similar:
            sib_text = (sibling.candidate_text or "")[:100].strip()
            if not sib_text or not sib_text.startswith(prefix):
                continue
            # Halve the importance (downrank) on pending look-alikes.
            sibling.importance = max(0.0, float(sibling.importance or 0.0) * 0.5)
            sib_meta = (
                dict(sibling.metadata_json or {})
                if isinstance(sibling.metadata_json, dict)
                else {}
            )
            sib_meta["downranked_by_rejection_of"] = item.id
            sib_meta["downranked_at"] = datetime.now(timezone.utc).isoformat()
            sibling.metadata_json = sib_meta
            rejected_lineage.append(str(sibling.id))

    if rejected_lineage:
        # Capture the downrank event on the rejected item's trace so audits
        # can see what else the rejection touched.
        trace = dict(meta.get("rejected_lineage") or {}) if isinstance(meta, dict) else {}
        trace[datetime.now(timezone.utc).isoformat()] = rejected_lineage
        meta["rejected_lineage"] = trace
        item.metadata_json = meta

    db.commit()
    return {"ok": True, "downranked_count": len(rejected_lineage)}


@pages_router.get("/{page_id}/memory/trace")
def get_page_memory_trace(
    page_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
) -> dict:
    """Full memory trace for a page: evidence → memory → subject → playbook."""
    _get_page_or_404(
        db,
        page_id,
        workspace_id,
        current_user_id=str(current_user.id),
        workspace_role=_get_workspace_role(
            db,
            workspace_id=workspace_id,
            user_id=str(current_user.id),
        ),
    )

    from app.models import (
        Memory,
        MemoryEvidence,
        MemoryView,
        MemoryWriteItem,
        MemoryWriteRun,
    )

    runs = (
        db.query(MemoryWriteRun)
        .filter(MemoryWriteRun.metadata_json["source_type"].as_string() == "notebook_page")
        .filter(MemoryWriteRun.metadata_json["source_id"].as_string() == page_id)
        .order_by(MemoryWriteRun.created_at.desc())
        .limit(20)
        .all()
    )
    run_ids = [r.id for r in runs]
    if not run_ids:
        return {"page_id": page_id, "memories": []}

    items = (
        db.query(MemoryWriteItem)
        .filter(MemoryWriteItem.run_id.in_(run_ids))
        .filter(MemoryWriteItem.target_memory_id.isnot(None))
        .order_by(MemoryWriteItem.created_at.desc())
        .all()
    )

    memory_ids = [i.target_memory_id for i in items if i.target_memory_id]
    memories = {
        m.id: m
        for m in db.query(Memory)
        .filter(Memory.id.in_(memory_ids), Memory.workspace_id == workspace_id)
        .all()
    } if memory_ids else {}

    evidence_by_memory: dict[str, list] = {}
    if memory_ids:
        for ev in (
            db.query(MemoryEvidence)
            .filter(MemoryEvidence.memory_id.in_(memory_ids))
            .order_by(MemoryEvidence.created_at.desc())
            .limit(200)
            .all()
        ):
            meta = ev.metadata_json if isinstance(ev.metadata_json, dict) else {}
            source_ref = (
                ev.chunk_id
                or ev.message_id
                or ev.data_item_id
                or meta.get("page_id")
                or meta.get("source_id")
            )
            evidence_by_memory.setdefault(str(ev.memory_id), []).append({
                "id": str(ev.id),
                "source_type": ev.source_type,
                "source_id": source_ref,
                "excerpt": (ev.quote_text or "")[:200],
                "created_at": ev.created_at.isoformat() if ev.created_at else None,
            })

    playbooks_by_memory: dict[str, list] = {}
    if memory_ids:
        # Playbooks link to memories via MemoryView.source_subject_id (the
        # subject a playbook is about). We surface playbooks whose subject
        # is either the memory itself or its parent subject.
        subject_ids = {
            str(m.subject_memory_id) for m in memories.values() if m.subject_memory_id
        }
        anchor_ids = set(str(mid) for mid in memory_ids) | subject_ids
        if anchor_ids:
            views = (
                db.query(MemoryView)
                .filter(MemoryView.source_subject_id.in_(anchor_ids))
                .filter(MemoryView.view_type == "playbook")
                .all()
            )
            for view in views:
                key = str(view.source_subject_id)
                playbooks_by_memory.setdefault(key, []).append({
                    "view_id": str(view.id),
                    "view_type": view.view_type,
                    "excerpt": (view.content or "")[:160],
                })

    # Resolve subject labels when a memory hangs off a subject node
    subject_ids_needed = {
        m.subject_memory_id for m in memories.values() if m.subject_memory_id
    }
    subject_content: dict[str, str] = {}
    if subject_ids_needed:
        for sm in (
            db.query(Memory)
            .filter(Memory.id.in_(subject_ids_needed))
            .all()
        ):
            subject_content[str(sm.id)] = sm.content or ""

    trace = []
    for item in items:
        mem = memories.get(item.target_memory_id)
        if not mem:
            continue
        pb = list(playbooks_by_memory.get(str(mem.id), []))
        if mem.subject_memory_id:
            pb.extend(playbooks_by_memory.get(str(mem.subject_memory_id), []))
        trace.append({
            "write_item_id": str(item.id),
            "memory_id": str(mem.id),
            "content": (mem.content or "")[:240],
            "category": mem.category,
            "node_type": mem.node_type,
            "confidence": float(mem.confidence or 0.0),
            "status": mem.node_status,
            "subject_memory_id": (
                str(mem.subject_memory_id) if mem.subject_memory_id else None
            ),
            "subject_label": (
                subject_content.get(str(mem.subject_memory_id), "")[:160]
                if mem.subject_memory_id
                else ""
            ),
            "evidence": evidence_by_memory.get(str(mem.id), []),
            "playbooks": pb,
            "decision": item.decision,
            "created_at": item.created_at.isoformat() if item.created_at else None,
        })

    return {"page_id": page_id, "memories": trace}


@study_assets_router.post("/{asset_id}/generate-deck")
async def generate_deck_from_asset(
    asset_id: str,
    payload: dict[str, Any] | None = None,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf: None = Depends(require_csrf_protection),
    _ai_quota: None = Depends(
        require_entitlement("ai.actions.monthly", counter=count_ai_actions_this_month),
    ),
) -> dict[str, Any]:
    """Spec §13.4 — build a StudyDeck + StudyCards from a study asset.

    Routes through `study_ai.generate_flashcards` at the service layer by
    directly calling the same LLM helper `_run_llm_json` and deck/card
    persistence. We keep this endpoint thin so the business logic stays in
    `study_ai` — on a real study-pipeline refactor this can be inlined to a
    single service function.
    """
    asset = db.query(StudyAsset).filter(StudyAsset.id == asset_id).first()
    if asset is None:
        raise ApiError("not_found", "Study asset not found", status_code=404)
    notebook = db.query(Notebook).filter(Notebook.id == asset.notebook_id).first()
    workspace_role = _get_workspace_role(
        db,
        workspace_id=workspace_id,
        user_id=str(current_user.id),
    )
    from app.core.notebook_access import assert_notebook_readable
    assert_notebook_readable(
        notebook,
        workspace_id=workspace_id,
        current_user_id=str(current_user.id),
        workspace_role=workspace_role,
        not_found_message="Study asset not found",
    )

    body = payload or {}
    count = int(body.get("count", 10))
    if count < 1 or count > 20:
        raise ApiError("invalid_input", "count must be 1-20", status_code=400)
    deck_name = str(body.get("name") or f"{asset.title or 'Deck'} — Auto")
    deck_description = str(body.get("description") or "")

    # Pull chunk text (limit to 8k to match flashcards endpoint)
    from app.models import StudyChunk, StudyCard, StudyDeck
    chunks = (
        db.query(StudyChunk)
        .filter(StudyChunk.asset_id == asset.id)
        .order_by(StudyChunk.chunk_index)
        .limit(20)
        .all()
    )
    source_text = "\n\n".join((c.content or "") for c in chunks)[:8000]
    if not source_text.strip():
        raise ApiError(
            "invalid_input",
            "Study asset has no chunk content yet (run ingest first)",
            status_code=400,
        )

    from app.routers.study_ai import _FLASHCARDS_SYSTEM, _run_llm_json
    prompt = f"Produce exactly {count} flashcards from the following text.\n\n{source_text}"

    import json as _json
    async with action_log_context(
        db,
        workspace_id=str(workspace_id),
        user_id=str(current_user.id),
        action_type="study.generate_deck",
        scope="study_asset",
        notebook_id=str(asset.notebook_id),
    ) as log:
        log.set_input({"asset_id": asset_id, "count": count})
        raw = await _run_llm_json(_FLASHCARDS_SYSTEM, prompt)
        try:
            parsed = _json.loads(raw)
            cards = parsed.get("cards") or []
            if not isinstance(cards, list) or not cards:
                raise ValueError("cards missing")
            for c in cards:
                if not isinstance(c.get("front"), str) or not isinstance(c.get("back"), str):
                    raise ValueError("bad card shape")
        except Exception:
            raise ApiError("llm_bad_output", "LLM returned invalid JSON", status_code=422)

        deck = StudyDeck(
            notebook_id=asset.notebook_id,
            name=deck_name[:120],
            description=deck_description,
            card_count=len(cards),
            created_by=current_user.id,
        )
        db.add(deck)
        db.flush()
        for c in cards:
            db.add(StudyCard(
                deck_id=deck.id,
                front=c["front"],
                back=c["back"],
                source_type="study_asset",
                source_ref=str(asset.id)[:64],
            ))
        log.set_output({"deck_id": deck.id, "card_count": len(cards)})
        log.record_usage(
            event_type="llm_completion",
            prompt_tokens=max(1, len(prompt) // 4),
            completion_tokens=max(1, len(raw) // 4),
            count_source="estimated",
        )
        db.commit()
        return {"deck_id": deck.id, "card_count": len(cards)}


@pages_router.post("/{page_id}/tasks/{block_id}/complete")
async def complete_task_block(
    page_id: str,
    block_id: str,
    payload: dict[str, Any],
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf: None = Depends(require_csrf_protection),
) -> dict[str, Any]:
    """Record a task-block completion toggle as an AIActionLog.

    No LLM usage is involved — this is a pure audit entry so later
    subsystems (S5 proactive services) can mine it.
    """
    page = _get_page_or_404(
        db,
        page_id,
        workspace_id,
        current_user_id=str(current_user.id),
        workspace_role=_get_workspace_role(
            db,
            workspace_id=workspace_id,
            user_id=str(current_user.id),
        ),
    )
    completed = bool(payload.get("completed", True))
    completed_at = payload.get("completed_at")

    async with action_log_context(
        db,
        workspace_id=str(workspace_id),
        user_id=str(current_user.id),
        action_type="task.complete" if completed else "task.reopen",
        scope="page",
        notebook_id=str(page.notebook_id),
        page_id=str(page.id),
        block_id=block_id,
    ) as log:
        log.set_input({
            "block_id": block_id,
            "completed": completed,
            "completed_at": completed_at,
        })
        log.set_output({"ok": True})

    return {"ok": True}
