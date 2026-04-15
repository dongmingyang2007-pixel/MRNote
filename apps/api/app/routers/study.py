from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import (
    get_current_user,
    get_current_workspace_id,
    get_db_session,
    require_csrf_protection,
    require_workspace_write_access,
)
from app.core.errors import ApiError
from app.models import Notebook, StudyAsset, StudyChunk, User
from app.schemas.study import (
    PaginatedStudyAssets,
    PaginatedStudyChunks,
    StudyAssetCreate,
    StudyAssetOut,
    StudyChunkOut,
)

router = APIRouter(
    prefix="/api/v1/notebooks/{notebook_id}/study",
    tags=["study"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_notebook_or_404(db: Session, notebook_id: str, workspace_id: str) -> Notebook:
    notebook = (
        db.query(Notebook)
        .filter(Notebook.id == notebook_id, Notebook.workspace_id == workspace_id)
        .first()
    )
    if not notebook:
        raise ApiError("not_found", "Notebook not found", status_code=404)
    return notebook


def _get_asset_or_404(
    db: Session, notebook_id: str, asset_id: str, workspace_id: str,
) -> StudyAsset:
    _get_notebook_or_404(db, notebook_id, workspace_id)
    asset = (
        db.query(StudyAsset)
        .filter(StudyAsset.id == asset_id, StudyAsset.notebook_id == notebook_id)
        .first()
    )
    if not asset or asset.status == "deleted":
        raise ApiError("not_found", "Study asset not found", status_code=404)
    return asset


# ---------------------------------------------------------------------------
# Study Asset CRUD
# ---------------------------------------------------------------------------


@router.get("", response_model=PaginatedStudyAssets)
def list_study_assets(
    notebook_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
) -> PaginatedStudyAssets:
    _ = current_user
    _get_notebook_or_404(db, notebook_id, workspace_id)
    query = (
        db.query(StudyAsset)
        .filter(
            StudyAsset.notebook_id == notebook_id,
            StudyAsset.status != "deleted",
        )
    )
    total = query.count()
    items = query.order_by(StudyAsset.created_at.desc()).offset(offset).limit(limit).all()
    return PaginatedStudyAssets(
        items=[StudyAssetOut.model_validate(item, from_attributes=True) for item in items],
        total=total,
    )


@router.post("", response_model=StudyAssetOut)
def create_study_asset(
    notebook_id: str,
    payload: StudyAssetCreate,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _: None = Depends(require_csrf_protection),
) -> StudyAssetOut:
    _get_notebook_or_404(db, notebook_id, workspace_id)

    asset = StudyAsset(
        notebook_id=notebook_id,
        data_item_id=payload.data_item_id,
        title=payload.title,
        asset_type=payload.asset_type,
        status="pending",
        created_by=current_user.id,
    )
    db.add(asset)
    db.flush()
    db.commit()
    db.refresh(asset)

    from app.tasks.worker_tasks import ingest_study_asset_task

    ingest_study_asset_task.delay(
        str(asset.id),
        str(workspace_id),
        str(current_user.id),
    )
    return StudyAssetOut.model_validate(asset, from_attributes=True)


@router.get("/{asset_id}", response_model=StudyAssetOut)
def get_study_asset(
    notebook_id: str,
    asset_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
) -> StudyAssetOut:
    _ = current_user
    asset = _get_asset_or_404(db, notebook_id, asset_id, workspace_id)
    return StudyAssetOut.model_validate(asset, from_attributes=True)


@router.get("/{asset_id}/chunks", response_model=PaginatedStudyChunks)
def list_study_chunks(
    notebook_id: str,
    asset_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
) -> PaginatedStudyChunks:
    _ = current_user
    _get_asset_or_404(db, notebook_id, asset_id, workspace_id)
    query = (
        db.query(StudyChunk)
        .filter(StudyChunk.asset_id == asset_id)
    )
    total = query.count()
    items = query.order_by(StudyChunk.chunk_index).offset(offset).limit(limit).all()
    return PaginatedStudyChunks(
        items=[StudyChunkOut.model_validate(item, from_attributes=True) for item in items],
        total=total,
    )


@router.delete("/{asset_id}")
def delete_study_asset(
    notebook_id: str,
    asset_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _: None = Depends(require_csrf_protection),
) -> dict:
    _ = current_user
    asset = _get_asset_or_404(db, notebook_id, asset_id, workspace_id)
    asset.status = "deleted"
    asset.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True, "status": "deleted"}


@router.post("/{asset_id}/ingest")
def reingest_study_asset(
    notebook_id: str,
    asset_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _: None = Depends(require_csrf_protection),
) -> dict:
    asset = _get_asset_or_404(db, notebook_id, asset_id, workspace_id)

    asset.status = "pending"
    asset.updated_at = datetime.now(timezone.utc)
    db.commit()

    from app.tasks.worker_tasks import ingest_study_asset_task

    ingest_study_asset_task.delay(
        str(asset.id),
        str(workspace_id),
        str(current_user.id),
    )

    return {"ok": True, "status": "queued", "asset_id": str(asset.id)}
