import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session
from starlette.responses import PlainTextResponse

from app.core.config import settings
from app.core.deps import (
    get_current_user,
    get_current_workspace_id,
    get_db_session,
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
    User,
)
from app.services import storage as storage_service
from app.services.ai_action_logger import action_log_context
from app.schemas.notebook import (
    NotebookCreate,
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


def _get_page_or_404(db: Session, page_id: str, workspace_id: str) -> NotebookPage:
    """Fetch a page and verify workspace ownership through its notebook."""
    page = db.query(NotebookPage).filter(NotebookPage.id == page_id).first()
    if not page:
        raise ApiError("not_found", "Page not found", status_code=404)
    notebook = (
        db.query(Notebook)
        .filter(Notebook.id == page.notebook_id, Notebook.workspace_id == workspace_id)
        .first()
    )
    if not notebook:
        raise ApiError("not_found", "Page not found", status_code=404)
    return page


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
    _ = current_user
    query = db.query(Notebook).filter(
        Notebook.workspace_id == workspace_id,
        Notebook.archived_at.is_(None),
    )
    items = query.order_by(Notebook.created_at.desc()).all()
    return PaginatedNotebooks(
        items=[NotebookOut.model_validate(item, from_attributes=True) for item in items],
        total=len(items),
    )


@router.post("", response_model=NotebookOut)
def create_notebook(
    payload: NotebookCreate,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _: None = Depends(require_csrf_protection),
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
    _ = current_user
    notebook = (
        db.query(Notebook)
        .filter(Notebook.id == notebook_id, Notebook.workspace_id == workspace_id)
        .first()
    )
    if not notebook:
        raise ApiError("not_found", "Notebook not found", status_code=404)
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
    notebook = (
        db.query(Notebook)
        .filter(Notebook.id == notebook_id, Notebook.workspace_id == workspace_id)
        .first()
    )
    if not notebook:
        raise ApiError("not_found", "Notebook not found", status_code=404)

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
    notebook = (
        db.query(Notebook)
        .filter(Notebook.id == notebook_id, Notebook.workspace_id == workspace_id)
        .first()
    )
    if not notebook:
        raise ApiError("not_found", "Notebook not found", status_code=404)

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
    _ = current_user
    notebook = (
        db.query(Notebook)
        .filter(Notebook.id == notebook_id, Notebook.workspace_id == workspace_id)
        .first()
    )
    if not notebook:
        raise ApiError("not_found", "Notebook not found", status_code=404)

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
) -> PageOut:
    notebook = (
        db.query(Notebook)
        .filter(Notebook.id == notebook_id, Notebook.workspace_id == workspace_id)
        .first()
    )
    if not notebook:
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

    notebook = (
        db.query(Notebook)
        .filter(Notebook.id == notebook_id, Notebook.workspace_id == workspace_id, Notebook.archived_at.is_(None))
        .first()
    )
    if not notebook:
        raise ApiError("not_found", "Notebook not found", status_code=404)

    conversation = (
        db.query(Conversation)
        .filter(Conversation.id == conversation_id, Conversation.workspace_id == workspace_id)
        .first()
    )
    if not conversation:
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
    _ = current_user
    query = (
        db.query(NotebookPage)
        .join(Notebook, Notebook.id == NotebookPage.notebook_id)
        .filter(Notebook.workspace_id == workspace_id, Notebook.archived_at.is_(None))
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
    _ = current_user
    page = db.query(NotebookPage).filter(NotebookPage.id == page_id).first()
    if not page:
        raise ApiError("not_found", "Page not found", status_code=404)
    # Verify workspace ownership through notebook
    notebook = (
        db.query(Notebook)
        .filter(Notebook.id == page.notebook_id, Notebook.workspace_id == workspace_id)
        .first()
    )
    if not notebook:
        raise ApiError("not_found", "Page not found", status_code=404)
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
    page = db.query(NotebookPage).filter(NotebookPage.id == page_id).first()
    if not page:
        raise ApiError("not_found", "Page not found", status_code=404)
    notebook = (
        db.query(Notebook)
        .filter(Notebook.id == page.notebook_id, Notebook.workspace_id == workspace_id)
        .first()
    )
    if not notebook:
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
    page = db.query(NotebookPage).filter(NotebookPage.id == page_id).first()
    if not page:
        raise ApiError("not_found", "Page not found", status_code=404)
    notebook = (
        db.query(Notebook)
        .filter(Notebook.id == page.notebook_id, Notebook.workspace_id == workspace_id)
        .first()
    )
    if not notebook:
        raise ApiError("not_found", "Page not found", status_code=404)

    write_audit_log(
        db,
        workspace_id=workspace_id,
        actor_user_id=current_user.id,
        action="notebook_page.delete",
        target_type="notebook_page",
        target_id=page.id,
    )
    db.delete(page)
    db.commit()
    return {"ok": True, "status": "deleted"}


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
    the S2 attachments bucket and returns the new NotebookAttachment row."""
    _ = current_user
    page = _get_page_or_404(db, page_id, workspace_id)

    body = await file.read()
    size = len(body)
    max_bytes = settings.notebook_attachment_max_bytes
    if size > max_bytes:
        raise ApiError(
            "file_too_large",
            f"Attachment exceeds {max_bytes} bytes",
            status_code=413,
        )

    safe_name = storage_service.sanitize_filename(file.filename or "file")
    object_key = f"{workspace_id}/{page.id}/{uuid4().hex}/{safe_name}"

    storage_service.get_s3_client().put_object(
        Bucket=settings.s3_notebook_attachments_bucket,
        Key=object_key,
        Body=body,
        ContentType=file.content_type or "application/octet-stream",
    )

    attachment = NotebookAttachment(
        page_id=page.id,
        data_item_id=None,
        attachment_type=_classify_attachment(file.content_type),
        title=title or safe_name,
        meta_json={
            "object_key": object_key,
            "mime_type": file.content_type or "application/octet-stream",
            "size_bytes": size,
        },
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)

    return {
        "attachment_id": attachment.id,
        "filename": safe_name,
        "mime_type": file.content_type or "application/octet-stream",
        "size_bytes": size,
        "attachment_type": attachment.attachment_type,
    }


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
    page = _get_page_or_404(db, page_id, workspace_id)

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
    _ = current_user
    _get_page_or_404(db, page_id, workspace_id)
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
    _ = current_user
    page = _get_page_or_404(db, page_id, workspace_id)

    if format == "markdown":
        md = _tiptap_json_to_markdown(page.content_json, page.title)
        return PlainTextResponse(content=md, media_type="text/markdown")
    else:
        return PlainTextResponse(content=page.plain_text, media_type="text/plain")


# ---------------------------------------------------------------------------
# Page memory connections
# ---------------------------------------------------------------------------


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
    _get_page_or_404(db, page_id, workspace_id)

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
        notebook = db.query(Notebook).filter(Notebook.id == _get_page_or_404(db, page_id, workspace_id).notebook_id).first()
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
    _ = current_user
    page = _get_page_or_404(db, page_id, workspace_id)
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
    page = _get_page_or_404(db, page_id, workspace_id)
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
    _ = current_user
    _get_page_or_404(db, page_id, workspace_id)
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
    db.commit()
    return {"ok": True}


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
    page = _get_page_or_404(db, page_id, workspace_id)
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
