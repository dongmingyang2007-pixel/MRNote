"""NotebookBlock CRUD endpoints (spec §13.3).

Design notes:
    The authoritative page content lives on ``NotebookPage.content_json``
    (TipTap ProseMirror JSON). The ``notebook_blocks`` DB table is a derived
    view kept in sync here so search scopes (``search_dispatcher.py``) can
    query blocks without re-walking the doc.

    Each block exposes a stable uuid: it is stored inside the TipTap node's
    ``attrs.block_id`` on create and surfaces as ``BlockOut.id`` on every
    read. The ``NotebookBlock`` row uses the same id as its primary key so
    callers get a round-trippable identifier.

    This yields a block-centric API surface while keeping the TipTap doc as
    the single source of truth for page rendering.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.deps import (
    get_current_user,
    get_current_workspace_id,
    get_current_workspace_role,
    get_db_session,
    require_csrf_protection,
    require_workspace_write_access,
)
from app.core.errors import ApiError
from app.core.notebook_access import assert_notebook_readable
from app.models import (
    Notebook,
    NotebookBlock,
    NotebookPage,
    User,
)
from app.schemas.block import (
    BlockCreate,
    BlockOut,
    BlockReorderPayload,
    BlockUpdate,
)

pages_blocks_router = APIRouter(prefix="/api/v1/pages", tags=["blocks"])
blocks_router = APIRouter(prefix="/api/v1/blocks", tags=["blocks"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BLOCK_TYPE_TO_TIPTAP: dict[str, str] = {
    "heading": "heading",
    "paragraph": "paragraph",
    "bullet_list": "bulletList",
    "numbered_list": "orderedList",
    "checklist": "taskList",
    "quote": "blockquote",
    "code": "codeBlock",
    "latex": "mathBlock",
    "whiteboard": "whiteboard",
    "image": "image",
    "file": "file",
    "ai_output": "aiOutput",
    "callout": "callout",
    "divider": "horizontalRule",
    "reference": "reference",
    "task": "taskItem",
    "flashcard": "flashcard",
}

_TIPTAP_TO_BLOCK_TYPE: dict[str, str] = {v: k for k, v in _BLOCK_TYPE_TO_TIPTAP.items()}


def _extract_block_plain_text(node: dict[str, Any]) -> str:
    """Walk a TipTap node and concatenate inline text."""
    parts: list[str] = []

    def walk(n: dict[str, Any]) -> None:
        if n.get("type") == "text":
            parts.append(str(n.get("text") or ""))
        for child in n.get("content", []) or []:
            if isinstance(child, dict):
                walk(child)

    walk(node)
    return "".join(parts)


def _get_page_or_404(
    db: Session,
    *,
    page_id: str,
    workspace_id: str,
    current_user_id: str,
    workspace_role: str,
    require_not_archived: bool = False,
) -> NotebookPage:
    page = db.query(NotebookPage).filter(NotebookPage.id == page_id).first()
    if not page:
        raise ApiError("not_found", "Page not found", status_code=404)
    notebook = db.query(Notebook).filter(Notebook.id == page.notebook_id).first()
    assert_notebook_readable(
        notebook,
        workspace_id=workspace_id,
        current_user_id=current_user_id,
        workspace_role=workspace_role,
        not_found_message="Page not found",
    )
    if require_not_archived:
        # HIGH-7: notebook-level archive cascades; parent notebook archived
        # means all child pages are effectively gone.
        if notebook and notebook.archived_at is not None:
            raise ApiError("not_found", "Page not found", status_code=404)
        if page.is_archived:
            raise ApiError("not_found", "Page not found", status_code=404)
    return page


def _ensure_doc(page: NotebookPage) -> dict[str, Any]:
    """Return the page's TipTap doc, normalizing if malformed."""
    doc = page.content_json if isinstance(page.content_json, dict) else {}
    if doc.get("type") != "doc":
        doc = {"type": "doc", "content": []}
    if not isinstance(doc.get("content"), list):
        doc["content"] = []
    # Every top-level node must have a stable block_id.
    for node in doc["content"]:
        if isinstance(node, dict):
            attrs = node.setdefault("attrs", {})
            if not attrs.get("block_id"):
                attrs["block_id"] = str(uuid4())
    return doc


def _sync_blocks_table(db: Session, page: NotebookPage) -> list[NotebookBlock]:
    """Replace ``notebook_blocks`` rows for this page with the current doc.

    We drop existing rows and recreate from the TipTap top-level children so
    the search index stays aligned with the doc. The block row's id equals
    the node's ``attrs.block_id``.
    """
    doc = _ensure_doc(page)
    # Wipe existing rows for this page
    db.query(NotebookBlock).filter(NotebookBlock.page_id == page.id).delete(
        synchronize_session=False,
    )
    rows: list[NotebookBlock] = []
    for idx, node in enumerate(doc.get("content") or []):
        if not isinstance(node, dict):
            continue
        attrs = node.setdefault("attrs", {})
        block_id = str(attrs.get("block_id") or uuid4())
        attrs["block_id"] = block_id
        tiptap_type = str(node.get("type") or "paragraph")
        block_type = _TIPTAP_TO_BLOCK_TYPE.get(tiptap_type, tiptap_type)
        plain = _extract_block_plain_text(node)[:8000]
        row = NotebookBlock(
            id=block_id,
            page_id=page.id,
            block_type=block_type,
            sort_order=idx,
            content_json=node,
            plain_text=plain,
            created_by=page.created_by,
            metadata_json={},
        )
        rows.append(row)
        db.add(row)
    return rows


def _doc_block_to_out(node: dict[str, Any], page_id: str, sort_order: int) -> BlockOut:
    attrs = node.get("attrs") if isinstance(node.get("attrs"), dict) else {}
    block_id = str(attrs.get("block_id") or uuid4())
    tiptap_type = str(node.get("type") or "paragraph")
    block_type = _TIPTAP_TO_BLOCK_TYPE.get(tiptap_type, tiptap_type)
    return BlockOut(
        id=block_id,
        page_id=page_id,
        block_type=block_type,
        sort_order=sort_order,
        content_json=node,
        plain_text=_extract_block_plain_text(node)[:8000],
    )


def _recompute_page_plain_text(doc: dict[str, Any]) -> str:
    out: list[str] = []
    for node in doc.get("content") or []:
        if isinstance(node, dict):
            text = _extract_block_plain_text(node)
            if text:
                out.append(text)
    return "\n".join(out)


def _commit_doc(db: Session, page: NotebookPage, doc: dict[str, Any]) -> None:
    # JSON columns don't track in-place mutations of their held dict; without
    # flag_modified SQLAlchemy won't emit an UPDATE even though the dict
    # content has changed. `deepcopy` gives a fresh reference but some test
    # SQLite drivers still compare by identity, so belt-and-braces.
    from copy import deepcopy
    fresh = deepcopy(doc)
    page.content_json = fresh
    flag_modified(page, "content_json")
    page.plain_text = _recompute_page_plain_text(fresh)
    page.last_edited_at = datetime.now(timezone.utc)
    page.updated_at = datetime.now(timezone.utc)
    _sync_blocks_table(db, page)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@pages_blocks_router.post("/{page_id}/blocks", response_model=BlockOut)
def create_block(
    page_id: str,
    payload: BlockCreate,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    workspace_role: str = Depends(get_current_workspace_role),
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf: None = Depends(require_csrf_protection),
) -> BlockOut:
    page = _get_page_or_404(
        db,
        page_id=page_id,
        workspace_id=workspace_id,
        current_user_id=str(current_user.id),
        workspace_role=workspace_role,
        require_not_archived=True,
    )

    doc = _ensure_doc(page)
    tiptap_type = _BLOCK_TYPE_TO_TIPTAP.get(payload.block_type, payload.block_type)
    # Start from caller-supplied content_json if provided (TipTap doc fragment),
    # otherwise build an empty node of the right type.
    raw_content = payload.content_json or {}
    if raw_content.get("type") and isinstance(raw_content.get("type"), str):
        node = dict(raw_content)
    else:
        node = {
            "type": tiptap_type,
            "content": raw_content.get("content", []) if isinstance(raw_content, dict) else [],
            "attrs": dict(raw_content.get("attrs", {})) if isinstance(raw_content, dict) else {},
        }
    node.setdefault("attrs", {})
    node["attrs"]["block_id"] = str(uuid4())

    sort_order = payload.sort_order
    current_content = list(doc.get("content") or [])
    if sort_order is None or sort_order > len(current_content):
        sort_order = len(current_content)
    sort_order = max(0, sort_order)
    current_content.insert(sort_order, node)
    doc["content"] = current_content

    _commit_doc(db, page, doc)
    db.commit()
    return _doc_block_to_out(node, page.id, sort_order)


@blocks_router.patch("/{block_id}", response_model=BlockOut)
def update_block(
    block_id: str,
    payload: BlockUpdate,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    workspace_role: str = Depends(get_current_workspace_role),
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf: None = Depends(require_csrf_protection),
) -> BlockOut:
    # Resolve block → page via the derived blocks table
    row = db.query(NotebookBlock).filter(NotebookBlock.id == block_id).first()
    if not row:
        raise ApiError("not_found", "Block not found", status_code=404)
    page = _get_page_or_404(
        db,
        page_id=row.page_id,
        workspace_id=workspace_id,
        current_user_id=str(current_user.id),
        workspace_role=workspace_role,
        require_not_archived=True,
    )

    doc = _ensure_doc(page)
    content = list(doc.get("content") or [])
    idx = next(
        (
            i for i, n in enumerate(content)
            if isinstance(n, dict) and (n.get("attrs") or {}).get("block_id") == block_id
        ),
        None,
    )
    if idx is None:
        raise ApiError("not_found", "Block not found", status_code=404)

    node = dict(content[idx])
    if payload.content_json is not None:
        # Merge: keep the existing attrs.block_id even if caller sent a new
        # fragment. Also keep the tiptap type unless caller explicitly
        # overrides block_type.
        new_node = dict(payload.content_json) if isinstance(payload.content_json, dict) else {}
        if "type" in new_node:
            node["type"] = new_node["type"]
        if "content" in new_node:
            node["content"] = new_node["content"]
        if "text" in new_node:
            node["text"] = new_node["text"]
        merged_attrs = dict(node.get("attrs") or {})
        if isinstance(new_node.get("attrs"), dict):
            merged_attrs.update(new_node["attrs"])
        merged_attrs["block_id"] = block_id
        node["attrs"] = merged_attrs

    if payload.block_type is not None:
        node["type"] = _BLOCK_TYPE_TO_TIPTAP.get(payload.block_type, payload.block_type)

    # Replace in content
    content[idx] = node

    if payload.sort_order is not None:
        new_order = max(0, min(payload.sort_order, len(content) - 1))
        if new_order != idx:
            item = content.pop(idx)
            content.insert(new_order, item)
            idx = new_order

    doc["content"] = content
    _commit_doc(db, page, doc)
    db.commit()
    return _doc_block_to_out(node, page.id, idx)


@blocks_router.delete("/{block_id}")
def delete_block(
    block_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    workspace_role: str = Depends(get_current_workspace_role),
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf: None = Depends(require_csrf_protection),
) -> dict[str, Any]:
    row = db.query(NotebookBlock).filter(NotebookBlock.id == block_id).first()
    if not row:
        raise ApiError("not_found", "Block not found", status_code=404)
    page = _get_page_or_404(
        db,
        page_id=row.page_id,
        workspace_id=workspace_id,
        current_user_id=str(current_user.id),
        workspace_role=workspace_role,
        require_not_archived=True,
    )

    doc = _ensure_doc(page)
    content = [
        n for n in (doc.get("content") or [])
        if not (
            isinstance(n, dict) and (n.get("attrs") or {}).get("block_id") == block_id
        )
    ]
    doc["content"] = content
    _commit_doc(db, page, doc)
    db.commit()
    return {"ok": True, "status": "deleted", "block_id": block_id}


@pages_blocks_router.post("/{page_id}/reorder-blocks")
def reorder_blocks(
    page_id: str,
    payload: BlockReorderPayload,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    workspace_role: str = Depends(get_current_workspace_role),
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf: None = Depends(require_csrf_protection),
) -> dict[str, Any]:
    page = _get_page_or_404(
        db,
        page_id=page_id,
        workspace_id=workspace_id,
        current_user_id=str(current_user.id),
        workspace_role=workspace_role,
        require_not_archived=True,
    )

    doc = _ensure_doc(page)
    content = list(doc.get("content") or [])
    by_id: dict[str, dict[str, Any]] = {}
    for node in content:
        if not isinstance(node, dict):
            continue
        bid = (node.get("attrs") or {}).get("block_id")
        if bid:
            by_id[str(bid)] = node

    requested_ids = [str(bid) for bid in (payload.block_ids or [])]
    missing = [bid for bid in requested_ids if bid not in by_id]
    if missing:
        raise ApiError(
            "invalid_input",
            f"Unknown block ids: {missing}",
            status_code=400,
        )
    # Preserve any blocks not mentioned by keeping them in original order
    # after the explicitly-ordered ones.
    ordered_nodes = [by_id[bid] for bid in requested_ids]
    seen = set(requested_ids)
    for node in content:
        if not isinstance(node, dict):
            continue
        bid = (node.get("attrs") or {}).get("block_id")
        if bid and bid not in seen:
            ordered_nodes.append(node)

    doc["content"] = ordered_nodes
    _commit_doc(db, page, doc)
    db.commit()
    return {
        "ok": True,
        "block_ids": [
            (n.get("attrs") or {}).get("block_id") for n in ordered_nodes
        ],
    }


@pages_blocks_router.get("/{page_id}/blocks", response_model=list[BlockOut])
def list_blocks(
    page_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    workspace_role: str = Depends(get_current_workspace_role),
) -> list[BlockOut]:
    page = _get_page_or_404(
        db,
        page_id=page_id,
        workspace_id=workspace_id,
        current_user_id=str(current_user.id),
        workspace_role=workspace_role,
    )
    doc = _ensure_doc(page)
    out: list[BlockOut] = []
    for idx, node in enumerate(doc.get("content") or []):
        if isinstance(node, dict):
            out.append(_doc_block_to_out(node, page.id, idx))
    return out
