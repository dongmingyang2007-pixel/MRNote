"""Attachment URL fetch API (S2)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import (
    get_current_user,
    get_current_workspace_id,
    get_current_workspace_role,
    get_db_session,
    is_workspace_privileged_role,
)
from app.core.errors import ApiError
from app.models import Notebook, NotebookAttachment, NotebookPage, User
from app.services import storage as storage_service

router = APIRouter(prefix="/api/v1/attachments", tags=["attachments"])


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


@router.get("/{attachment_id}/url")
def get_attachment_url(
    attachment_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    workspace_role: str = Depends(get_current_workspace_role),
) -> dict[str, Any]:

    att = db.query(NotebookAttachment).filter_by(id=attachment_id).first()
    if att is None:
        raise ApiError("not_found", "Attachment not found", status_code=404)

    page = db.query(NotebookPage).filter_by(id=att.page_id).first()
    if page is None:
        raise ApiError("not_found", "Attachment page missing", status_code=404)
    nb = (
        db.query(Notebook)
        .filter(Notebook.id == page.notebook_id, Notebook.workspace_id == workspace_id)
        .first()
    )
    if nb is None or not _can_read_notebook(
        nb,
        workspace_id=workspace_id,
        current_user_id=str(current_user.id),
        workspace_role=workspace_role,
    ):
        raise ApiError("not_found", "Attachment not found", status_code=404)

    object_key = (att.meta_json or {}).get("object_key")
    if not object_key:
        raise ApiError("not_found", "Attachment object key missing", status_code=404)

    expires_in = settings.s3_presign_expire_seconds
    url = storage_service.create_presigned_get(
        bucket_name=settings.s3_notebook_attachments_bucket,
        object_key=object_key,
        download_name=att.title or (att.meta_json or {}).get("filename") or "attachment",
        expires_seconds=expires_in,
    )
    return {"url": url, "expires_in_seconds": expires_in}
