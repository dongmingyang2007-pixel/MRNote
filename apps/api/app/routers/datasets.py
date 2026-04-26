from datetime import datetime, timezone
import hashlib
import io
from uuid import uuid4

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
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
from app.models import Annotation, DataItem, Dataset, DatasetVersion, DocumentVersion, User
from app.models.study import StudyAsset
from app.routers.utils import get_data_item_in_workspace, get_dataset_in_workspace, get_project_in_workspace_or_404
from app.schemas.dataset import (
    AnnotationCreateRequest,
    AnnotationOut,
    DataItemContentOut,
    DataItemContentUpdate,
    DataItemOut,
    DatasetCommitRequest,
    DatasetCreate,
    DatasetOut,
    DatasetVersionOut,
)
from app.services.audit import write_audit_log
from app.services import storage as storage_service
from app.services.storage import create_presigned_get
from app.services.upload_validation import is_safe_preview_media_type
from app.tasks.worker_tasks import cleanup_deleted_dataset, index_data_item


router = APIRouter(tags=["datasets"])

_INLINE_PREVIEW_MEDIA_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "image/bmp",
    "image/tiff",
    "text/plain",
    "text/markdown",
    "text/csv",
    "application/json",
}

_EDITABLE_TEXT_MEDIA_TYPES = {
    "text/plain",
    "text/markdown",
    "text/csv",
    "text/css",
    "text/javascript",
    "application/json",
    "application/javascript",
    "application/x-javascript",
}

_EDITABLE_TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".csv",
    ".tsv",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".env",
    ".log",
    ".rst",
    ".tex",
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".java",
    ".c",
    ".cc",
    ".cpp",
    ".cxx",
    ".h",
    ".hpp",
    ".cs",
    ".go",
    ".rs",
    ".rb",
    ".php",
    ".swift",
    ".kt",
    ".kts",
    ".scala",
    ".r",
    ".sql",
    ".sh",
    ".bash",
    ".zsh",
    ".fish",
    ".ps1",
    ".vue",
    ".svelte",
}

_PDF_HIGHLIGHT_COLORS = {
    "rgba(252, 211, 77, 0.45)",
    "rgba(96, 165, 250, 0.35)",
    "rgba(52, 211, 153, 0.35)",
    "rgba(248, 113, 113, 0.35)",
}
_PDF_HIGHLIGHT_MAX_RECTS = 64
_PDF_HIGHLIGHT_MAX_TEXT = 4000
_PDF_HIGHLIGHT_MAX_LINKS = 20


def _sanitize_item_meta(meta_json: dict | None) -> dict:
    return strip_object_key_fields(meta_json or {})


def _validate_annotation_payload(annotation_type: str, payload: dict) -> dict:
    if annotation_type != "pdf_highlight":
        return payload
    page = payload.get("page")
    text = payload.get("text", "")
    color = payload.get("color", "rgba(252, 211, 77, 0.45)")
    rects = payload.get("rects")
    links = payload.get("links", [])
    note = payload.get("note", "")
    if not isinstance(page, int) or page < 1 or page > 10000:
        raise ApiError("invalid_input", "Invalid PDF highlight page", status_code=400)
    if not isinstance(text, str) or len(text) > _PDF_HIGHLIGHT_MAX_TEXT:
        raise ApiError("invalid_input", "Invalid PDF highlight text", status_code=400)
    if not isinstance(color, str) or color not in _PDF_HIGHLIGHT_COLORS:
        raise ApiError("invalid_input", "Invalid PDF highlight color", status_code=400)
    if not isinstance(rects, list) or not rects or len(rects) > _PDF_HIGHLIGHT_MAX_RECTS:
        raise ApiError("invalid_input", "Invalid PDF highlight rectangles", status_code=400)
    clean_rects: list[dict[str, float]] = []
    for rect in rects:
        if not isinstance(rect, dict):
            raise ApiError("invalid_input", "Invalid PDF highlight rectangle", status_code=400)
        clean_rect: dict[str, float] = {}
        for key in ("x", "y", "width", "height"):
            value = rect.get(key)
            if not isinstance(value, (int, float)):
                raise ApiError("invalid_input", "Invalid PDF highlight rectangle", status_code=400)
            numeric = float(value)
            if numeric < 0 or numeric > 10000 or key in {"width", "height"} and numeric <= 0:
                raise ApiError("invalid_input", "Invalid PDF highlight rectangle", status_code=400)
            clean_rect[key] = numeric
        clean_rects.append(clean_rect)
    if not isinstance(note, str) or len(note) > 2000:
        raise ApiError("invalid_input", "Invalid PDF highlight note", status_code=400)
    if not isinstance(links, list) or len(links) > _PDF_HIGHLIGHT_MAX_LINKS:
        raise ApiError("invalid_input", "Invalid PDF highlight links", status_code=400)
    clean_links = []
    for link in links:
        if not isinstance(link, dict):
            raise ApiError("invalid_input", "Invalid PDF highlight link", status_code=400)
        kind = link.get("kind")
        link_id = link.get("id")
        title = link.get("title", "")
        if kind not in {"page", "memory"} or not isinstance(link_id, str) or len(link_id) > 64:
            raise ApiError("invalid_input", "Invalid PDF highlight link", status_code=400)
        if not isinstance(title, str) or len(title) > 200:
            raise ApiError("invalid_input", "Invalid PDF highlight link", status_code=400)
        clean_links.append({"kind": kind, "id": link_id, "title": title})
    return {
        "page": page,
        "text": text,
        "color": color,
        "rects": clean_rects,
        "note": note,
        "links": clean_links,
    }


def _is_completed_data_item(item: DataItem) -> bool:
    status = (item.meta_json or {}).get("upload_status")
    return status in {None, "completed", "index_failed"}


def _read_data_item_bytes(item: DataItem) -> bytes:
    obj = storage_service.get_s3_client().get_object(
        Bucket=settings.s3_private_bucket,
        Key=item.object_key,
    )
    body = obj["Body"]
    try:
        return body.read()
    finally:
        close = getattr(body, "close", None)
        if callable(close):
            close()


def _filename_extension(filename: str) -> str:
    lowered = filename.lower()
    if "." not in lowered:
        return ""
    return f".{lowered.rsplit('.', 1)[-1]}"


def _is_editable_text_item(item: DataItem) -> bool:
    media_type = (item.media_type or "").split(";", 1)[0].strip().lower()
    if media_type.startswith("text/") or media_type in _EDITABLE_TEXT_MEDIA_TYPES:
        return True
    return _filename_extension(item.filename) in _EDITABLE_TEXT_EXTENSIONS


def _enqueue_data_item_reindex(
    db: Session,
    item: DataItem,
    workspace_id: str,
    user_id: str,
) -> None:
    dataset = db.get(Dataset, item.dataset_id)
    project_id = str(dataset.project_id) if dataset else ""
    if project_id:
        if settings.env == "test":
            index_data_item(item.id)
        else:
            index_data_item.delay(item.id)

    from app.tasks.worker_tasks import ingest_study_asset_task

    linked_assets = (
        db.query(StudyAsset)
        .filter(StudyAsset.data_item_id == item.id, StudyAsset.status != "deleted")
        .all()
    )
    for asset in linked_assets:
        asset.status = "pending"
        asset.updated_at = datetime.now(timezone.utc)
    if linked_assets:
        db.commit()
    for asset in linked_assets:
        if settings.env == "test":
            ingest_study_asset_task(str(asset.id), str(workspace_id), user_id)
        else:
            ingest_study_asset_task.delay(str(asset.id), str(workspace_id), user_id)


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
        payload_json=_validate_annotation_payload(payload.type, payload.payload_json),
        created_by=current_user.id,
    )
    db.add(annotation)
    db.commit()
    db.refresh(annotation)
    return {
        "annotation": {
            "id": annotation.id,
            "type": annotation.type,
            "payload_json": annotation.payload_json,
            "created_at": annotation.created_at.isoformat()
            if annotation.created_at
            else None,
            "created_by": annotation.created_by,
        }
    }


@router.get("/api/v1/data-items/{data_item_id}/annotations")
def list_annotations(
    data_item_id: str,
    type: str | None = Query(default=None),
    db: Session = Depends(get_db_session),
    workspace_id: str = Depends(get_current_workspace_id),
) -> dict:
    """List annotations for a data item, optionally filtered by type.

    Used by the PDF viewer to fetch saved highlights / notes on open.
    """
    item = get_data_item_in_workspace(
        db, data_item_id=data_item_id, workspace_id=workspace_id
    )
    if not item:
        raise ApiError("not_found", "Data item not found", status_code=404)
    if not _is_completed_data_item(item):
        raise ApiError("not_found", "Data item not found", status_code=404)

    query = db.query(Annotation).filter(Annotation.data_item_id == item.id)
    if type:
        query = query.filter(Annotation.type == type)
    rows = query.order_by(Annotation.created_at.asc()).all()
    return {
        "items": [
            {
                "id": ann.id,
                "type": ann.type,
                "payload_json": ann.payload_json,
                "created_at": ann.created_at.isoformat()
                if ann.created_at
                else None,
                "created_by": ann.created_by,
            }
            for ann in rows
        ]
    }


@router.patch("/api/v1/annotations/{annotation_id}")
def update_annotation(
    annotation_id: str,
    payload: dict,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _: None = Depends(require_csrf_protection),
) -> dict:
    """Update annotation payload. Used by the highlight edit dialog to
    set/replace note/color/links without recreating the row."""
    annotation = db.query(Annotation).filter(Annotation.id == annotation_id).first()
    if not annotation:
        raise ApiError("not_found", "Annotation not found", status_code=404)
    item = get_data_item_in_workspace(
        db, data_item_id=annotation.data_item_id, workspace_id=workspace_id
    )
    if not item:
        raise ApiError("not_found", "Annotation not found", status_code=404)

    incoming_payload = payload.get("payload_json")
    if not isinstance(incoming_payload, dict):
        raise ApiError(
            "invalid_input", "payload_json must be an object", status_code=400
        )
    annotation.payload_json = _validate_annotation_payload(annotation.type, incoming_payload)
    db.commit()
    db.refresh(annotation)
    return {
        "annotation": {
            "id": annotation.id,
            "type": annotation.type,
            "payload_json": annotation.payload_json,
            "created_at": annotation.created_at.isoformat()
            if annotation.created_at
            else None,
            "created_by": annotation.created_by,
        }
    }


@router.delete("/api/v1/annotations/{annotation_id}")
def delete_annotation(
    annotation_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _: None = Depends(require_csrf_protection),
) -> dict:
    """Delete an annotation. Workspace ownership is enforced via the
    annotation's data_item → dataset → project → workspace chain."""
    annotation = db.query(Annotation).filter(Annotation.id == annotation_id).first()
    if not annotation:
        raise ApiError("not_found", "Annotation not found", status_code=404)
    item = get_data_item_in_workspace(
        db, data_item_id=annotation.data_item_id, workspace_id=workspace_id
    )
    if not item:
        raise ApiError("not_found", "Annotation not found", status_code=404)
    db.delete(annotation)
    db.commit()
    return {"ok": True}


@router.get("/api/v1/data-items/{data_item_id}/preview")
def preview_data_item(
    data_item_id: str,
    db: Session = Depends(get_db_session),
    workspace_id: str = Depends(get_current_workspace_id),
) -> StreamingResponse:
    item = get_data_item_in_workspace(db, data_item_id=data_item_id, workspace_id=workspace_id)
    if not item or not _is_completed_data_item(item):
        raise ApiError("not_found", "Data item not found", status_code=404)

    media_type = (item.media_type or "application/octet-stream").split(";", 1)[0].strip().lower()
    if media_type not in _INLINE_PREVIEW_MEDIA_TYPES and not is_safe_preview_media_type(media_type):
        raise ApiError("unsupported_media_type", "This file cannot be previewed inline", status_code=415)

    body = _read_data_item_bytes(item)
    safe_name = storage_service.sanitize_filename(item.filename or "reference")
    return StreamingResponse(
        io.BytesIO(body),
        media_type=media_type,
        headers={
            "Content-Disposition": f'inline; filename="{safe_name}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/api/v1/data-items/{data_item_id}/content", response_model=DataItemContentOut)
def get_data_item_content(
    data_item_id: str,
    db: Session = Depends(get_db_session),
    workspace_id: str = Depends(get_current_workspace_id),
) -> DataItemContentOut:
    item = get_data_item_in_workspace(db, data_item_id=data_item_id, workspace_id=workspace_id)
    if not item or not _is_completed_data_item(item):
        raise ApiError("not_found", "Data item not found", status_code=404)
    if not _is_editable_text_item(item):
        raise ApiError("unsupported_media_type", "This file cannot be edited as text", status_code=415)

    body = _read_data_item_bytes(item)
    try:
        content = body.decode("utf-8")
    except UnicodeDecodeError:
        content = body.decode("utf-8", errors="replace")
    return DataItemContentOut(
        id=item.id,
        filename=item.filename,
        media_type=item.media_type,
        content=content,
    )


@router.put("/api/v1/data-items/{data_item_id}/content", response_model=DataItemContentOut)
def update_data_item_content(
    data_item_id: str,
    payload: DataItemContentUpdate,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _: None = Depends(require_csrf_protection),
) -> DataItemContentOut:
    item = get_data_item_in_workspace(db, data_item_id=data_item_id, workspace_id=workspace_id)
    if not item or not _is_completed_data_item(item):
        raise ApiError("not_found", "Data item not found", status_code=404)
    if not _is_editable_text_item(item):
        raise ApiError("unsupported_media_type", "This file cannot be edited as text", status_code=415)

    body = payload.content.encode("utf-8")
    storage_service.put_object_bytes(
        bucket_name=settings.s3_private_bucket,
        object_key=item.object_key,
        payload=body,
        media_type=item.media_type or "text/plain",
    )
    item.size_bytes = len(body)
    item.sha256 = hashlib.sha256(body).hexdigest()
    item.meta_json = {
        **(item.meta_json or {}),
        "upload_status": "completed",
        "edited_in_notebook": True,
        "edited_at": datetime.now(timezone.utc).isoformat(),
    }
    db.commit()
    _enqueue_data_item_reindex(db, item, str(workspace_id), str(current_user.id))
    return DataItemContentOut(
        id=item.id,
        filename=item.filename,
        media_type=item.media_type,
        content=payload.content,
    )


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


@router.get("/api/v1/data-items/{data_item_id}/versions")
def list_data_item_versions(
    data_item_id: str,
    db: Session = Depends(get_db_session),
    workspace_id: str = Depends(get_current_workspace_id),
) -> list[dict]:
    item = get_data_item_in_workspace(db, data_item_id=data_item_id, workspace_id=workspace_id)
    if not item:
        raise ApiError("not_found", "Data item not found", status_code=404)
    versions = (
        db.query(DocumentVersion)
        .filter(DocumentVersion.data_item_id == item.id)
        .order_by(DocumentVersion.version.desc())
        .all()
    )
    return [
        {
            "id": v.id,
            "version": v.version,
            "size_bytes": v.size_bytes,
            "media_type": v.media_type,
            "saved_via": v.saved_via,
            "saved_by": v.saved_by,
            "note": v.note,
            "created_at": v.created_at.isoformat() if v.created_at else None,
        }
        for v in versions
    ]


@router.post("/api/v1/data-items/{data_item_id}/versions/{version_id}/restore")
def restore_data_item_version(
    data_item_id: str,
    version_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _: None = Depends(require_csrf_protection),
) -> dict:
    item = get_data_item_in_workspace(db, data_item_id=data_item_id, workspace_id=workspace_id)
    if not item:
        raise ApiError("not_found", "Data item not found", status_code=404)
    version = (
        db.query(DocumentVersion)
        .filter(DocumentVersion.id == version_id, DocumentVersion.data_item_id == item.id)
        .first()
    )
    if not version:
        raise ApiError("not_found", "Version not found", status_code=404)

    # Snapshot current state first so the restore itself is reversible.
    from app.services.document_versions import write_version_snapshot, restore_version
    write_version_snapshot(
        db, item=item, saved_by=str(current_user.id),
        saved_via="restore_pre", note=f"auto-snapshot before restoring v{version.version}",
    )
    restore_version(db, item=item, version=version)

    db.commit()
    _enqueue_data_item_reindex(db, item, str(workspace_id), str(current_user.id))
    return {"ok": True, "version": version.version}
