from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import (
    enforce_rate_limit,
    get_current_user,
    get_current_workspace_id,
    get_db_session,
    require_csrf_protection,
    require_workspace_write_access,
)
from app.core.entitlements import require_entitlement
from app.core.errors import ApiError
from app.models import DataItem, User
from app.routers.utils import get_data_item_in_workspace, get_dataset_in_workspace, get_project_in_workspace_or_404
from app.schemas.dataset import UploadCompleteRequest, UploadPresignRequest, UploadPresignResponse
from app.services.audit import write_audit_log
from app.services.runtime_state import runtime_state
from app.services.storage import (
    build_data_item_object_key,
    build_upload_id,
    create_presigned_post,
    object_exists,
    put_object_bytes,
)
from app.services.upload_validation import (
    buffer_upload_body,
    ensure_uploaded_object_matches,
    ensure_uploaded_object_signature_matches,
    validate_workspace_upload_declaration,
    validate_workspace_upload_content,
)
from app.tasks.worker_tasks import cleanup_pending_upload_session, index_data_item, process_data_item


router = APIRouter(prefix="/api/v1/uploads", tags=["uploads"])


def _upload_session_scope(upload_id: str) -> str:
    return f"upload:{upload_id}"


def _upload_session_ttl_seconds(session: dict) -> int:
    expires_at = session.get("expires_at")
    if isinstance(expires_at, (int, float)):
        remaining = int(float(expires_at) - datetime.now(timezone.utc).timestamp())
        return max(1, remaining)
    return settings.upload_session_ttl_seconds


def _is_completed_data_item(item: DataItem) -> bool:
    status = (item.meta_json or {}).get("upload_status")
    return status in {None, "completed", "index_failed"}


def _run_or_enqueue_upload_followups(
    *,
    workspace_id: str,
    project_id: str,
    item: DataItem,
) -> None:
    followups = [
        (process_data_item, (item.id,)),
        (index_data_item, (item.id,)),
    ]
    if settings.env == "test":
        for task, args in followups:
            task(*args)
        return

    for task, args in followups:
        try:
            task.delay(*args)
        except Exception:  # noqa: BLE001
            task(*args)


@router.post("/presign", response_model=UploadPresignResponse)
def presign_upload(
    payload: UploadPresignRequest,
    request: Request,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _upload_gate: None = Depends(require_entitlement("book_upload.enabled")),
    _: None = Depends(require_csrf_protection),
) -> UploadPresignResponse:
    enforce_rate_limit(
        request,
        scope="upload-presign",
        identifier=current_user.id,
        limit=settings.upload_presign_rate_limit_max,
        window_seconds=settings.upload_presign_rate_limit_window_seconds,
    )
    dataset = get_dataset_in_workspace(db, dataset_id=payload.dataset_id, workspace_id=workspace_id)
    if not dataset:
        raise ApiError("not_found", "Dataset not found", status_code=404)
    project = get_project_in_workspace_or_404(db, dataset.project_id, workspace_id)
    normalized_media_type = validate_workspace_upload_declaration(payload.filename, payload.media_type)

    max_bytes = settings.upload_max_mb * 1024 * 1024
    if payload.size_bytes > max_bytes:
        raise ApiError(
            "payload_too_large",
            f"File exceeds {settings.upload_max_mb}MB limit",
            status_code=413,
        )

    data_item_id = str(uuid4())
    object_key = build_data_item_object_key(
        workspace_id=workspace_id,
        project_id=project.id,
        dataset_id=payload.dataset_id,
        data_item_id=data_item_id,
        filename=payload.filename,
    )
    upload_id = build_upload_id()
    headers: dict[str, str] = {}
    fields: dict[str, str] = {}
    upload_method = "PUT"
    if settings.should_use_proxy_uploads():
        # HIGH-9 V8: use the configured site_url rather than
        # ``request.base_url`` — the latter reflects the client-supplied
        # Host header, so an attacker could induce us to emit a PUT URL
        # pointing at an attacker-controlled host (e.g. via a
        # reverse-proxy misconfig). site_url is server-owned.
        configured_site_url = str(settings.site_url).rstrip("/")
        configured_host = ""
        try:
            from urllib.parse import urlparse

            configured_host = urlparse(configured_site_url).hostname or ""
        except Exception:  # noqa: BLE001
            configured_host = ""
        if settings.env == "test" and (
            configured_site_url in {"http://localhost:3000", "http://127.0.0.1:3000"}
            or (not settings.upload_put_proxy and configured_host not in settings.allowed_hosts)
        ):
            base = str(request.base_url).rstrip("/")
        else:
            base = configured_site_url
        put_url = f"{base}/api/v1/uploads/proxy/{upload_id}"
        headers = {"Content-Type": normalized_media_type}
    else:
        put_url, fields, headers = create_presigned_post(
            bucket_name=settings.s3_private_bucket,
            object_key=object_key,
            media_type=normalized_media_type,
            max_bytes=payload.size_bytes,
        )
        upload_method = "POST"

    now = datetime.now(timezone.utc)
    reservation_expires_at = now + timedelta(seconds=settings.upload_session_ttl_seconds)
    from app.services.storage_quota import create_upload_reservation

    create_upload_reservation(
        db,
        workspace_id=str(workspace_id),
        dataset_id=str(payload.dataset_id),
        upload_id=upload_id,
        data_item_id=data_item_id,
        object_key=object_key,
        bytes_reserved=int(payload.size_bytes),
        expires_at=reservation_expires_at,
    )
    runtime_state.set_json(
        _upload_session_scope(upload_id),
        "session",
        {
            "data_item_id": data_item_id,
            "dataset_id": payload.dataset_id,
            "project_id": project.id,
            "user_id": current_user.id,
            "workspace_id": workspace_id,
            "object_key": object_key,
            "filename": payload.filename,
            "media_type": normalized_media_type,
            "size_bytes": payload.size_bytes,
            "uploaded": False,
            "created_at": now.isoformat(),
            "expires_at": reservation_expires_at.timestamp(),
        },
        ttl_seconds=settings.upload_session_ttl_seconds,
    )
    try:
        cleanup_pending_upload_session.apply_async(
            args=[upload_id, object_key, data_item_id],
            countdown=settings.upload_session_ttl_seconds,
        )
    except Exception:  # noqa: BLE001
        pass

    write_audit_log(
        db,
        workspace_id=workspace_id,
        actor_user_id=current_user.id,
        action="upload.presign",
        target_type="data_item",
        target_id=data_item_id,
        meta_json={"object_key": object_key},
    )
    db.commit()

    return UploadPresignResponse(
        upload_id=upload_id,
        put_url=put_url,
        headers=headers,
        fields=fields,
        upload_method=upload_method,
        data_item_id=data_item_id,
    )


@router.put("/proxy/{upload_id}")
async def proxy_upload_put(
    upload_id: str,
    request: Request,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _: None = Depends(require_csrf_protection),
) -> dict[str, bool]:
    upload = runtime_state.get_json(_upload_session_scope(upload_id), "session")
    if not upload:
        raise ApiError("upload_not_found", "Upload session not found", status_code=404)
    if upload["user_id"] != current_user.id or upload["workspace_id"] != workspace_id:
        raise ApiError("forbidden", "Upload session not accessible", status_code=403)
    content_type = request.headers.get("content-type", "")
    if content_type and content_type != upload["media_type"]:
        raise ApiError("content_type_mismatch", "Content-Type does not match upload session", status_code=400)

    max_bytes = settings.upload_max_mb * 1024 * 1024
    buffered_upload = await buffer_upload_body(
        request,
        expected_size=upload["size_bytes"],
        max_bytes=max_bytes,
    )
    try:
        buffered_upload.file.seek(0)
        validate_workspace_upload_content(
            content=buffered_upload.file.read(),
            media_type=upload["media_type"],
        )
        buffered_upload.file.seek(0)

        if settings.env != "test":
            try:
                put_object_bytes(
                    bucket_name=settings.s3_private_bucket,
                    object_key=upload["object_key"],
                    payload=buffered_upload.file,
                    media_type=upload["media_type"],
                )
            except Exception as exc:  # noqa: BLE001
                raise ApiError("storage_error", "Object upload failed", status_code=502) from exc
    finally:
        buffered_upload.close()

    upload["uploaded"] = True
    runtime_state.set_json(
        _upload_session_scope(upload_id),
        "session",
        upload,
        ttl_seconds=_upload_session_ttl_seconds(upload),
    )
    db.commit()
    return {"ok": True}


@router.post("/complete")
def complete_upload(
    payload: UploadCompleteRequest,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _: None = Depends(require_csrf_protection),
) -> dict[str, bool]:
    item = get_data_item_in_workspace(db, data_item_id=payload.data_item_id, workspace_id=workspace_id)
    if item and _is_completed_data_item(item):
        return {"ok": True}

    upload = runtime_state.get_json(_upload_session_scope(payload.upload_id), "session")
    if not upload:
        raise ApiError("upload_not_found", "Upload session not found", status_code=404)

    if upload["data_item_id"] != payload.data_item_id:
        raise ApiError("mismatch", "Upload and data item mismatch", status_code=400)
    if upload["user_id"] != current_user.id or upload["workspace_id"] != workspace_id:
        raise ApiError("forbidden", "Upload session not accessible", status_code=403)

    dataset = get_dataset_in_workspace(db, dataset_id=upload["dataset_id"], workspace_id=workspace_id)
    if not dataset:
        raise ApiError("not_found", "Dataset not found", status_code=404)
    if not upload.get("uploaded"):
        if not object_exists(
            bucket_name=settings.s3_private_bucket,
            object_key=upload["object_key"],
        ):
            raise ApiError("upload_incomplete", "Uploaded object not found", status_code=400)
        ensure_uploaded_object_matches(
            bucket_name=settings.s3_private_bucket,
            object_key=upload["object_key"],
            expected_size_bytes=upload["size_bytes"],
            expected_media_type=upload["media_type"],
            missing_message="Uploaded object not found",
            mismatch_message="Uploaded object metadata does not match declared file",
        )
        ensure_uploaded_object_signature_matches(
            bucket_name=settings.s3_private_bucket,
            object_key=upload["object_key"],
            media_type=upload["media_type"],
            mismatch_message="Uploaded object contents do not match declared file type",
        )

    existing_size = int(item.size_bytes or 0) if item and item.deleted_at is None else 0
    if existing_size > 0:
        from app.services.storage_quota import assert_can_store

        incoming_delta = max(0, int(upload["size_bytes"]) - existing_size)
        assert_can_store(
            db,
            workspace_id=str(workspace_id),
            incoming_bytes=incoming_delta,
        )
    else:
        from app.services.storage_quota import consume_upload_reservation

        consume_upload_reservation(
            db,
            workspace_id=str(workspace_id),
            upload_id=str(payload.upload_id),
            data_item_id=str(payload.data_item_id),
            final_size_bytes=int(upload["size_bytes"]),
        )

    if not item:
        item = DataItem(
            id=upload["data_item_id"],
            dataset_id=upload["dataset_id"],
            object_key=upload["object_key"],
            filename=upload["filename"],
            media_type=upload["media_type"],
            size_bytes=upload["size_bytes"],
            meta_json={"upload_status": "completed"},
        )
        db.add(item)
    else:
        item.dataset_id = upload["dataset_id"]
        item.object_key = upload["object_key"]
        item.filename = item.filename or upload["filename"]
        item.media_type = upload["media_type"]
        item.size_bytes = upload["size_bytes"]
        item.meta_json = {**(item.meta_json or {}), "upload_status": "completed"}

    write_audit_log(
        db,
        workspace_id=workspace_id,
        actor_user_id=current_user.id,
        action="upload.complete",
        target_type="data_item",
        target_id=item.id,
        meta_json={"object_key": item.object_key},
    )
    db.commit()

    _run_or_enqueue_upload_followups(
        workspace_id=workspace_id,
        project_id=dataset.project_id,
        item=item,
    )

    # Bytes just landed — drop the cached usage row so the next read
    # (e.g. the storage badge polling on the next page load) recomputes.
    from app.services.storage_quota import invalidate_workspace_usage_cache

    invalidate_workspace_usage_cache(str(workspace_id))

    runtime_state.delete(_upload_session_scope(payload.upload_id), "session")
    return {"ok": True}
