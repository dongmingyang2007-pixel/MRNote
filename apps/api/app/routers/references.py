"""Reference document creation: blank Word/PPT/Excel/PDF inside a notebook.

The flow mirrors the upload pipeline: produce bytes → write to S3 →
create DataItem + StudyAsset → trigger study ingest. The new asset
shows up in the same `/study-assets` listing the references library
already consumes, so the frontend doesn't need a separate listing.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import (
    get_current_user,
    get_current_workspace_id,
    get_current_workspace_role,
    get_db_session,
    require_csrf_protection,
    require_workspace_write_access,
)
from app.core.entitlements import require_entitlement
from app.core.errors import ApiError
from app.models import DataItem, Dataset, Notebook, StudyAsset, User
from app.routers.study import _get_notebook_or_404
from app.schemas.study import StudyAssetOut
from app.services import storage as storage_service
from app.services.document_templates import (
    DOC_TYPE_MEDIA,
    DocType,
    generate_blank_document,
)
from app.services.quota_counters import count_study_assets


router = APIRouter(
    prefix="/api/v1/notebooks/{notebook_id}/references",
    tags=["references"],
)


class ReferenceCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    doc_type: Literal["docx", "xlsx", "pptx", "pdf"]


def _ensure_knowledge_dataset(db: Session, project_id: str) -> Dataset:
    """Find or create the default 'knowledge' dataset for the project.

    Mirrors the frontend `ensureKnowledgeDataset` helper so server-initiated
    document creation lands in the same dataset users see in the library.
    """
    dataset = (
        db.query(Dataset)
        .filter(Dataset.project_id == project_id, Dataset.deleted_at.is_(None))
        .order_by(Dataset.created_at.asc())
        .first()
    )
    if dataset is not None:
        return dataset
    dataset = Dataset(project_id=project_id, name="Default Knowledge", type="text")
    db.add(dataset)
    db.flush()
    return dataset


def _trigger_post_upload_pipeline(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    item: DataItem,
    asset: StudyAsset,
    user_id: str,
) -> None:
    """Kick off the same indexing chain real uploads use.

    Inline in test env (consistent with existing helpers in
    apps/api/app/routers/datasets.py) so the test suite stays
    deterministic without celery."""
    from app.tasks.worker_tasks import index_data_item, ingest_study_asset_task

    if settings.env == "test":
        index_data_item(item.id)
        ingest_study_asset_task(str(asset.id), str(workspace_id), str(user_id))
        return

    try:
        index_data_item.delay(item.id)
    except Exception:  # noqa: BLE001
        index_data_item(item.id)
    try:
        ingest_study_asset_task.delay(
            str(asset.id), str(workspace_id), str(user_id)
        )
    except Exception:  # noqa: BLE001
        ingest_study_asset_task(str(asset.id), str(workspace_id), str(user_id))


@router.post("/create", response_model=StudyAssetOut)
def create_blank_reference(
    notebook_id: str,
    payload: ReferenceCreateRequest,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    workspace_role: str = Depends(get_current_workspace_role),
    _write_guard: None = Depends(require_workspace_write_access),
    _: None = Depends(require_csrf_protection),
    _quota: None = Depends(
        require_entitlement("study_assets.max", counter=count_study_assets)
    ),
    _book: None = Depends(require_entitlement("book_upload.enabled")),
) -> StudyAssetOut:
    notebook: Notebook = _get_notebook_or_404(
        db,
        notebook_id,
        workspace_id,
        current_user_id=str(current_user.id),
        workspace_role=workspace_role,
    )
    if not notebook.project_id:
        raise ApiError(
            "no_project",
            "Notebook is not linked to a project; cannot create reference.",
            status_code=400,
        )

    doc_type: DocType = payload.doc_type
    media_type, extension, asset_type = DOC_TYPE_MEDIA[doc_type]
    body = generate_blank_document(doc_type, payload.title)

    # Storage quota gate (same 402 path used by uploads/presign).
    from app.services.storage_quota import assert_can_store

    assert_can_store(
        db,
        workspace_id=str(workspace_id),
        incoming_bytes=len(body),
    )

    dataset = _ensure_knowledge_dataset(db, str(notebook.project_id))

    filename = f"{payload.title}.{extension}"
    safe_filename = storage_service.sanitize_filename(filename)
    data_item_id = str(uuid4())
    object_key = storage_service.build_data_item_object_key(
        str(workspace_id),
        str(notebook.project_id),
        str(dataset.id),
        data_item_id,
        safe_filename,
    )

    storage_service.put_object_bytes(
        bucket_name=settings.s3_private_bucket,
        object_key=object_key,
        payload=body,
        media_type=media_type,
    )

    item = DataItem(
        id=data_item_id,
        dataset_id=dataset.id,
        object_key=object_key,
        filename=safe_filename,
        media_type=media_type,
        size_bytes=len(body),
        sha256=hashlib.sha256(body).hexdigest(),
        meta_json={
            "upload_status": "completed",
            "created_blank": True,
            "doc_type": doc_type,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    db.add(item)
    db.flush()

    asset = StudyAsset(
        notebook_id=notebook_id,
        data_item_id=item.id,
        title=payload.title,
        asset_type=asset_type,
        status="pending",
        created_by=current_user.id,
    )
    db.add(asset)
    db.flush()
    db.commit()
    db.refresh(asset)

    _trigger_post_upload_pipeline(
        db,
        workspace_id=str(workspace_id),
        project_id=str(notebook.project_id),
        item=item,
        asset=asset,
        user_id=str(current_user.id),
    )

    # Storage usage just changed — let the badge / next quota check
    # recompute instead of serving the pre-create cached snapshot.
    from app.services.storage_quota import invalidate_workspace_usage_cache

    invalidate_workspace_usage_cache(str(workspace_id))

    return StudyAssetOut.model_validate(asset, from_attributes=True)
