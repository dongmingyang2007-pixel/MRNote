"""Attachment URL fetch API (S2)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import (
    get_current_user,
    get_current_workspace_id,
    get_db_session,
)
from app.core.errors import ApiError
from app.models import Notebook, NotebookAttachment, NotebookPage, User
from app.services import storage as storage_service

router = APIRouter(prefix="/api/v1/attachments", tags=["attachments"])


@router.get("/{attachment_id}/url")
def get_attachment_url(
    attachment_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
) -> dict[str, Any]:
    _ = current_user

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
    if nb is None:
        raise ApiError("not_found", "Attachment not found", status_code=404)

    object_key = (att.meta_json or {}).get("object_key")
    if not object_key:
        raise ApiError("not_found", "Attachment object key missing", status_code=404)

    presign_client = storage_service.get_s3_client()
    try:
        presign_client = storage_service.get_s3_presign_client()
    except Exception:  # noqa: BLE001
        pass

    expires_in = settings.s3_presign_expire_seconds
    url = presign_client.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": settings.s3_notebook_attachments_bucket,
            "Key": object_key,
        },
        ExpiresIn=expires_in,
    )
    return {"url": url, "expires_in_seconds": expires_in}
