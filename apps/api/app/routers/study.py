from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import (
    get_current_user,
    get_current_workspace_id,
    get_current_workspace_role,
    get_db_session,
    is_workspace_privileged_role,
    require_csrf_protection,
    require_workspace_write_access,
)
from app.core.entitlements import require_entitlement
from app.core.errors import ApiError
from app.models import Notebook, StudyAsset, StudyChunk, User
from app.routers.utils import get_data_item_in_workspace
from app.services.quota_counters import count_study_assets
from app.schemas.study import (
    PaginatedStudyAssets,
    PaginatedStudyChunks,
    StudyAssetCreate,
    StudyAssetOut,
    StudyChunkOut,
    StudyInsightsOut,
)
from app.services.study_insights import collect_study_insights

router = APIRouter(
    prefix="/api/v1/notebooks/{notebook_id}/study",
    tags=["study"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
    notebook_id: str,
    workspace_id: str,
    *,
    current_user_id: str,
    workspace_role: str,
) -> Notebook:
    notebook = (
        db.query(Notebook)
        .filter(Notebook.id == notebook_id, Notebook.workspace_id == workspace_id)
        .first()
    )
    if not notebook or not _can_read_notebook(
        notebook,
        workspace_id=workspace_id,
        current_user_id=current_user_id,
        workspace_role=workspace_role,
    ):
        raise ApiError("not_found", "Notebook not found", status_code=404)
    return notebook


def _get_asset_or_404(
    db: Session,
    notebook_id: str,
    asset_id: str,
    workspace_id: str,
    *,
    current_user_id: str,
    workspace_role: str,
) -> StudyAsset:
    _get_notebook_or_404(
        db,
        notebook_id,
        workspace_id,
        current_user_id=current_user_id,
        workspace_role=workspace_role,
    )
    asset = (
        db.query(StudyAsset)
        .filter(StudyAsset.id == asset_id, StudyAsset.notebook_id == notebook_id)
        .first()
    )
    if not asset or asset.status == "deleted":
        raise ApiError("not_found", "Study asset not found", status_code=404)
    return asset


def _get_asset_global_or_404(
    db: Session,
    asset_id: str,
    workspace_id: str,
    *,
    current_user_id: str,
    workspace_role: str,
) -> StudyAsset:
    asset = (
        db.query(StudyAsset)
        .join(Notebook, Notebook.id == StudyAsset.notebook_id)
        .filter(
            StudyAsset.id == asset_id,
            Notebook.workspace_id == workspace_id,
        )
        .first()
    )
    notebook = db.get(Notebook, asset.notebook_id) if asset else None
    if (
        not asset
        or asset.status == "deleted"
        or notebook is None
        or not _can_read_notebook(
            notebook,
            workspace_id=workspace_id,
            current_user_id=current_user_id,
            workspace_role=workspace_role,
        )
    ):
        raise ApiError("not_found", "Study asset not found", status_code=404)
    return asset


def _build_paginated_study_chunks(
    db: Session,
    *,
    asset_id: str,
    limit: int,
    offset: int,
) -> PaginatedStudyChunks:
    query = db.query(StudyChunk).filter(StudyChunk.asset_id == asset_id)
    total = query.count()
    items = query.order_by(StudyChunk.chunk_index).offset(offset).limit(limit).all()
    return PaginatedStudyChunks(
        items=[StudyChunkOut.model_validate(item, from_attributes=True) for item in items],
        total=total,
    )


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
    workspace_role: str = Depends(get_current_workspace_role),
) -> PaginatedStudyAssets:
    _get_notebook_or_404(
        db,
        notebook_id,
        workspace_id,
        current_user_id=str(current_user.id),
        workspace_role=workspace_role,
    )
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
    workspace_role: str = Depends(get_current_workspace_role),
    _write_guard: None = Depends(require_workspace_write_access),
    _: None = Depends(require_csrf_protection),
    _quota: None = Depends(require_entitlement("study_assets.max", counter=count_study_assets)),
    _book: None = Depends(require_entitlement("book_upload.enabled")),
) -> StudyAssetOut:
    _get_notebook_or_404(
        db,
        notebook_id,
        workspace_id,
        current_user_id=str(current_user.id),
        workspace_role=workspace_role,
    )
    if payload.data_item_id:
        data_item = get_data_item_in_workspace(
            db,
            data_item_id=payload.data_item_id,
            workspace_id=workspace_id,
        )
        if data_item is None:
            raise ApiError("not_found", "Study source file not found", status_code=404)

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


@router.get("/insights", response_model=StudyInsightsOut)
def get_study_insights(
    notebook_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    workspace_role: str = Depends(get_current_workspace_role),
) -> StudyInsightsOut:
    _get_notebook_or_404(
        db,
        notebook_id,
        workspace_id,
        current_user_id=str(current_user.id),
        workspace_role=workspace_role,
    )
    return StudyInsightsOut.model_validate(
        collect_study_insights(db, notebook_id=notebook_id),
    )


@router.get("/{asset_id}", response_model=StudyAssetOut)
def get_study_asset(
    notebook_id: str,
    asset_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    workspace_role: str = Depends(get_current_workspace_role),
) -> StudyAssetOut:
    asset = _get_asset_or_404(
        db,
        notebook_id,
        asset_id,
        workspace_id,
        current_user_id=str(current_user.id),
        workspace_role=workspace_role,
    )
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
    workspace_role: str = Depends(get_current_workspace_role),
) -> PaginatedStudyChunks:
    _get_asset_or_404(
        db,
        notebook_id,
        asset_id,
        workspace_id,
        current_user_id=str(current_user.id),
        workspace_role=workspace_role,
    )
    return _build_paginated_study_chunks(db, asset_id=asset_id, limit=limit, offset=offset)


@router.delete("/{asset_id}")
def delete_study_asset(
    notebook_id: str,
    asset_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    workspace_role: str = Depends(get_current_workspace_role),
    _write_guard: None = Depends(require_workspace_write_access),
    _: None = Depends(require_csrf_protection),
) -> dict:
    asset = _get_asset_or_404(
        db,
        notebook_id,
        asset_id,
        workspace_id,
        current_user_id=str(current_user.id),
        workspace_role=workspace_role,
    )
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
    workspace_role: str = Depends(get_current_workspace_role),
    _write_guard: None = Depends(require_workspace_write_access),
    _: None = Depends(require_csrf_protection),
) -> dict:
    asset = _get_asset_or_404(
        db,
        notebook_id,
        asset_id,
        workspace_id,
        current_user_id=str(current_user.id),
        workspace_role=workspace_role,
    )

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


# Alias router to match spec §13.4 naming (/study-assets). Shares all handlers.
router_aliased = APIRouter(
    prefix="/api/v1/notebooks/{notebook_id}/study-assets",
    tags=["study"],
    include_in_schema=False,
)
router_aliased.add_api_route(
    "", list_study_assets, methods=["GET"], response_model=PaginatedStudyAssets,
)
router_aliased.add_api_route(
    "", create_study_asset, methods=["POST"], response_model=StudyAssetOut,
)
router_aliased.add_api_route(
    "/{asset_id}", get_study_asset, methods=["GET"], response_model=StudyAssetOut,
)
router_aliased.add_api_route(
    "/{asset_id}/chunks", list_study_chunks, methods=["GET"],
    response_model=PaginatedStudyChunks,
)
router_aliased.add_api_route(
    "/{asset_id}", delete_study_asset, methods=["DELETE"],
)
router_aliased.add_api_route(
    "/{asset_id}/ingest", reingest_study_asset, methods=["POST"],
)


# Global study-asset routes defined by build spec §13.4.
asset_router = APIRouter(
    prefix="/api/v1/study-assets",
    tags=["study"],
)


@asset_router.get("/{asset_id}", response_model=StudyAssetOut)
def get_study_asset_global(
    asset_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    workspace_role: str = Depends(get_current_workspace_role),
) -> StudyAssetOut:
    asset = _get_asset_global_or_404(
        db,
        asset_id,
        workspace_id,
        current_user_id=str(current_user.id),
        workspace_role=workspace_role,
    )
    return StudyAssetOut.model_validate(asset, from_attributes=True)


@asset_router.get("/{asset_id}/chunks", response_model=PaginatedStudyChunks)
def list_study_chunks_global(
    asset_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    workspace_role: str = Depends(get_current_workspace_role),
) -> PaginatedStudyChunks:
    _get_asset_global_or_404(
        db,
        asset_id,
        workspace_id,
        current_user_id=str(current_user.id),
        workspace_role=workspace_role,
    )
    return _build_paginated_study_chunks(db, asset_id=asset_id, limit=limit, offset=offset)


@asset_router.post("/{asset_id}/ingest")
def reingest_study_asset_global(
    asset_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    workspace_role: str = Depends(get_current_workspace_role),
    _write_guard: None = Depends(require_workspace_write_access),
    _: None = Depends(require_csrf_protection),
) -> dict:
    asset = _get_asset_global_or_404(
        db,
        asset_id,
        workspace_id,
        current_user_id=str(current_user.id),
        workspace_role=workspace_role,
    )

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
