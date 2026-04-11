from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import (
    get_current_user,
    get_current_workspace_id,
    get_db_session,
    require_csrf_protection,
    require_workspace_write_access,
)
from app.core.errors import ApiError
from app.core.sanitize import strip_object_key_fields
from app.models import Annotation, DataItem, Dataset, DatasetVersion, User
from app.routers.utils import get_data_item_in_workspace, get_dataset_in_workspace, get_project_in_workspace_or_404
from app.schemas.dataset import (
    AnnotationCreateRequest,
    AnnotationOut,
    DataItemOut,
    DatasetCommitRequest,
    DatasetCreate,
    DatasetOut,
    DatasetVersionOut,
)
from app.services.audit import write_audit_log
from app.services.storage import create_presigned_get
from app.services.upload_validation import is_safe_preview_media_type
from app.tasks.worker_tasks import cleanup_deleted_dataset


router = APIRouter(tags=["datasets"])


def _sanitize_item_meta(meta_json: dict | None) -> dict:
    return strip_object_key_fields(meta_json or {})


def _is_completed_data_item(item: DataItem) -> bool:
    status = (item.meta_json or {}).get("upload_status")
    return status in {None, "completed"}


def _build_annotation_out(annotation: Annotation) -> AnnotationOut:
    return AnnotationOut(
        id=annotation.id,
        type=annotation.type,
        payload_json=annotation.payload_json,
        created_at=annotation.created_at,
    )


def _get_tagged_item_ids(
    db: Session,
    *,
    dataset_id: str,
    tag: str,
    item_ids: set[str] | None = None,
) -> set[str]:
    if item_ids is not None and not item_ids:
        return set()
    query = (
        db.query(Annotation)
        .join(DataItem, DataItem.id == Annotation.data_item_id)
        .filter(
            Annotation.type == "tag",
            DataItem.dataset_id == dataset_id,
            DataItem.deleted_at.is_(None),
        )
    )
    if item_ids is not None:
        query = query.filter(DataItem.id.in_(sorted(item_ids)))
    tagged_item_ids: set[str] = set()
    for ann in query.all():
        if tag in (ann.payload_json.get("tags") or []):
            tagged_item_ids.add(ann.data_item_id)
    return tagged_item_ids


def _build_data_item_out(item: DataItem) -> DataItemOut:
    return DataItemOut(
        id=item.id,
        dataset_id=item.dataset_id,
        filename=item.filename,
        media_type=item.media_type,
        size_bytes=item.size_bytes,
        sha256=item.sha256,
        width=item.width,
        height=item.height,
        meta_json=_sanitize_item_meta(item.meta_json),
        preview_url=(
            create_presigned_get(
                bucket_name=settings.s3_private_bucket,
                object_key=item.object_key,
            )
            if is_safe_preview_media_type(item.media_type)
            else None
        ),
        download_url=create_presigned_get(
            bucket_name=settings.s3_private_bucket,
            object_key=item.object_key,
            download_name=item.filename,
        ),
        created_at=item.created_at,
        annotations=[],
    )


@router.get("/api/v1/datasets", response_model=list[DatasetOut])
def list_datasets(
    project_id: str,
    db: Session = Depends(get_db_session),
    workspace_id: str = Depends(get_current_workspace_id),
) -> list[DatasetOut]:
    project = get_project_in_workspace_or_404(db, project_id, workspace_id)

    items = (
        db.query(Dataset)
        .filter(Dataset.project_id == project_id, Dataset.deleted_at.is_(None))
        .order_by(Dataset.created_at.desc())
        .all()
    )
    return [DatasetOut.model_validate(item, from_attributes=True) for item in items]


@router.post("/api/v1/datasets", response_model=DatasetOut)
def create_dataset(
    payload: DatasetCreate,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _: None = Depends(require_csrf_protection),
) -> DatasetOut:
    project = get_project_in_workspace_or_404(db, payload.project_id, workspace_id)

    dataset = Dataset(project_id=payload.project_id, name=payload.name, type=payload.type)
    db.add(dataset)
    write_audit_log(
        db,
        workspace_id=workspace_id,
        actor_user_id=current_user.id,
        action="dataset.create",
        target_type="dataset",
        target_id=dataset.id,
    )
    db.commit()
    db.refresh(dataset)
    return DatasetOut.model_validate(dataset, from_attributes=True)


@router.get("/api/v1/datasets/{dataset_id}", response_model=DatasetOut)
def get_dataset(
    dataset_id: str,
    db: Session = Depends(get_db_session),
    workspace_id: str = Depends(get_current_workspace_id),
) -> DatasetOut:
    dataset = get_dataset_in_workspace(db, dataset_id=dataset_id, workspace_id=workspace_id)
    if not dataset:
        raise ApiError("not_found", "Dataset not found", status_code=404)
    return DatasetOut.model_validate(dataset, from_attributes=True)


@router.delete("/api/v1/datasets/{dataset_id}")
def delete_dataset(
    dataset_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _: None = Depends(require_csrf_protection),
) -> dict:
    dataset = get_dataset_in_workspace(db, dataset_id=dataset_id, workspace_id=workspace_id)
    if not dataset:
        raise ApiError("not_found", "Dataset not found", status_code=404)

    dataset.deleted_at = datetime.now(timezone.utc)
    dataset.cleanup_status = "pending"
    write_audit_log(
        db,
        workspace_id=workspace_id,
        actor_user_id=current_user.id,
        action="dataset.delete_requested",
        target_type="dataset",
        target_id=dataset.id,
    )
    db.commit()
    try:
        cleanup_deleted_dataset.delay(dataset.id)
    except Exception:  # noqa: BLE001
        cleanup_deleted_dataset(dataset.id)
    return {"ok": True, "status": "accepted"}


@router.get("/api/v1/datasets/{dataset_id}/items", response_model=list[DataItemOut])
def list_items(
    dataset_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    tag: str | None = None,
    db: Session = Depends(get_db_session),
    workspace_id: str = Depends(get_current_workspace_id),
) -> list[DataItemOut]:
    dataset = get_dataset_in_workspace(db, dataset_id=dataset_id, workspace_id=workspace_id)
    if not dataset:
        raise ApiError("not_found", "Dataset not found", status_code=404)

    query = db.query(DataItem).filter(DataItem.dataset_id == dataset_id, DataItem.deleted_at.is_(None))
    items = [item for item in query.order_by(DataItem.created_at.desc()).all() if _is_completed_data_item(item)]
    if tag:
        tagged_item_ids = _get_tagged_item_ids(db, dataset_id=dataset_id, tag=tag, item_ids={item.id for item in items})
        items = [item for item in items if item.id in tagged_item_ids]
    items = items[offset : offset + limit]

    item_ids = [item.id for item in items]
    annotations_by_item_id: dict[str, list[Annotation]] = {item_id: [] for item_id in item_ids}
    if item_ids:
        for annotation in db.query(Annotation).filter(Annotation.data_item_id.in_(item_ids)).all():
            annotations_by_item_id.setdefault(annotation.data_item_id, []).append(annotation)

    out: list[DataItemOut] = []
    for item in items:
        annotations = annotations_by_item_id.get(item.id, [])
        if tag:
            annotations = [
                ann for ann in annotations if ann.type == "tag" and tag in (ann.payload_json.get("tags") or [])
            ]
        item_out = _build_data_item_out(item)
        item_out.annotations = [_build_annotation_out(ann) for ann in annotations]
        out.append(item_out)
    return out


@router.get("/api/v1/datasets/{dataset_id}/versions", response_model=list[DatasetVersionOut])
def list_dataset_versions(
    dataset_id: str,
    db: Session = Depends(get_db_session),
    workspace_id: str = Depends(get_current_workspace_id),
) -> list[DatasetVersionOut]:
    dataset = get_dataset_in_workspace(db, dataset_id=dataset_id, workspace_id=workspace_id)
    if not dataset:
        raise ApiError("not_found", "Dataset not found", status_code=404)

    versions = (
        db.query(DatasetVersion)
        .filter(DatasetVersion.dataset_id == dataset.id)
        .order_by(DatasetVersion.version.desc())
        .all()
    )
    return [DatasetVersionOut.model_validate(v, from_attributes=True) for v in versions]


@router.post("/api/v1/data-items/{data_item_id}/annotations")
def create_annotation(
    data_item_id: str,
    payload: AnnotationCreateRequest,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _: None = Depends(require_csrf_protection),
) -> dict:
    item = get_data_item_in_workspace(db, data_item_id=data_item_id, workspace_id=workspace_id)
    if not item:
        raise ApiError("not_found", "Data item not found", status_code=404)
    if not _is_completed_data_item(item):
        raise ApiError("not_found", "Data item not found", status_code=404)

    annotation = Annotation(
        id=str(uuid4()),
        data_item_id=item.id,
        type=payload.type,
        payload_json=payload.payload_json,
        created_by=current_user.id,
    )
    db.add(annotation)
    db.commit()
    db.refresh(annotation)
    return {"annotation": {"id": annotation.id, "type": annotation.type, "payload_json": annotation.payload_json}}


@router.get("/api/v1/data-items/{data_item_id}", response_model=DataItemOut)
def get_data_item(
    data_item_id: str,
    db: Session = Depends(get_db_session),
    workspace_id: str = Depends(get_current_workspace_id),
) -> DataItemOut:
    item = get_data_item_in_workspace(db, data_item_id=data_item_id, workspace_id=workspace_id)
    if not item:
        raise ApiError("not_found", "Data item not found", status_code=404)
    if not _is_completed_data_item(item):
        raise ApiError("not_found", "Data item not found", status_code=404)

    annotations = db.query(Annotation).filter(Annotation.data_item_id == item.id).all()
    item_out = _build_data_item_out(item)
    item_out.annotations = [_build_annotation_out(ann) for ann in annotations]
    return item_out


@router.post("/api/v1/datasets/{dataset_id}/commit")
def commit_dataset(
    dataset_id: str,
    payload: DatasetCommitRequest,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _: None = Depends(require_csrf_protection),
) -> dict:
    dataset = get_dataset_in_workspace(db, dataset_id=dataset_id, workspace_id=workspace_id)
    if not dataset:
        raise ApiError("not_found", "Dataset not found", status_code=404)

    query = db.query(DataItem).filter(DataItem.dataset_id == dataset.id, DataItem.deleted_at.is_(None))
    completed_items = [item for item in query.order_by(DataItem.created_at.desc()).all() if _is_completed_data_item(item)]
    if payload.freeze_filter and payload.freeze_filter.get("tag"):
        tag = payload.freeze_filter["tag"]
        tagged_item_ids = _get_tagged_item_ids(db, dataset_id=dataset.id, tag=tag, item_ids={item.id for item in completed_items})
        completed_items = [item for item in completed_items if item.id in tagged_item_ids]

    item_ids = [item.id for item in completed_items]
    max_version = (
        db.query(func.max(DatasetVersion.version)).filter(DatasetVersion.dataset_id == dataset.id).scalar() or 0
    )
    dataset_version = DatasetVersion(
        dataset_id=dataset.id,
        version=max_version + 1,
        commit_message=payload.commit_message,
        item_count=len(item_ids),
        frozen_item_ids=item_ids,
        created_by=current_user.id,
    )
    db.add(dataset_version)
    write_audit_log(
        db,
        workspace_id=workspace_id,
        actor_user_id=current_user.id,
        action="dataset_version.create",
        target_type="dataset_version",
        target_id=dataset_version.id,
        meta_json={"dataset_id": dataset.id, "version": dataset_version.version},
    )
    db.commit()
    db.refresh(dataset_version)
    return {"dataset_version": DatasetVersionOut.model_validate(dataset_version, from_attributes=True)}
