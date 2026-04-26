"""Workspace-level read endpoints (storage usage + budget visibility).

Kept tiny on purpose: this is just the read-side surface for things the
frontend needs to render (storage quota bar in settings, "near quota"
toast on the upload button). Mutations live on their respective routers
(uploads, references, etc).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import (
    get_current_user,
    get_current_workspace_id,
    get_db_session,
)
from app.models import User
from app.services.storage_quota import get_workspace_storage_usage


router = APIRouter(tags=["workspace"])


@router.get("/api/v1/workspaces/me/storage-usage")
def my_workspace_storage_usage(
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
) -> dict:
    """Return live byte counts + quota for the caller's active workspace.

    Used by the references library / settings page to render a quota bar.
    The response shape is intentionally flat so the frontend can render
    `total_bytes / quota_bytes` without further math.
    """
    _ = current_user  # request scoped — keeps the auth dependency sticky
    usage = get_workspace_storage_usage(db, workspace_id=str(workspace_id))
    return {
        "workspace_id": usage.workspace_id,
        "raw_bytes": usage.raw_bytes,
        "version_bytes": usage.version_bytes,
        "reserved_bytes": usage.reserved_bytes,
        "total_bytes": usage.total_bytes,
        "quota_bytes": usage.quota_bytes,
        "available_bytes": usage.available_bytes,
        "is_unlimited": usage.is_unlimited,
        "is_over_quota": usage.is_over_quota,
    }
