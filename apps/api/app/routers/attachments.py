"""Attachment URL fetch API (S2)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import (
    get_current_user,
    get_current_workspace_id,
    get_current_workspace_role,
    get_db_session,
    is_workspace_privileged_role,
    require_csrf_protection,
    require_workspace_write_access,
)
from app.core.errors import ApiError
from app.models import Notebook, NotebookAttachment, NotebookPage, User
from app.services import storage as storage_service
from app.services.audit import write_audit_log

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


@router.delete("/{attachment_id}", status_code=204)
def delete_attachment_flat(
    attachment_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    workspace_role: str = Depends(get_current_workspace_role),
    _write: None = Depends(require_workspace_write_access),
    _csrf: None = Depends(require_csrf_protection),
) -> Response:
    """Delete an attachment by id (spec §13.4 flat path).

    Resolves workspace ownership via the attachment's page → notebook chain,
    applies the same visibility gate as ``notebooks.delete_page_attachment``,
    then deletes the S3 object (best-effort) and the DB row (authoritative).
    A 204 is returned on success; 404 hides cross-workspace and private-
    notebook misses (never leak existence).
    """
    att = db.query(NotebookAttachment).filter_by(id=attachment_id).first()
    if att is None:
        raise ApiError("not_found", "Attachment not found", status_code=404)

    page = db.query(NotebookPage).filter_by(id=att.page_id).first()
    if page is None:
        raise ApiError("not_found", "Attachment not found", status_code=404)

    notebook = (
        db.query(Notebook)
        .filter(Notebook.id == page.notebook_id, Notebook.workspace_id == workspace_id)
        .first()
    )
    if notebook is None or notebook.archived_at is not None:
        raise ApiError("not_found", "Attachment not found", status_code=404)
    if not _can_read_notebook(
        notebook,
        workspace_id=workspace_id,
        current_user_id=str(current_user.id),
        workspace_role=workspace_role,
    ):
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
            logging.getLogger(__name__).warning(
                "delete_attachment_flat: S3 delete failed for key=%s", object_key,
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
    return Response(status_code=204)
