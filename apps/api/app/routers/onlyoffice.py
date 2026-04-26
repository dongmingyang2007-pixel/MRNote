"""ONLYOFFICE Document Server endpoints.

- `GET /config` is called by the browser (session auth) and returns the
  signed editor config the frontend hands to DocsAPI.
- `GET /content` is called by the ONLYOFFICE container itself (no session
  cookie available) using the scoped JWT token in the URL.
- `POST /callback` is also called by the ONLYOFFICE container — it
  reports save events and we pull the new file bytes back from a URL
  ONLYOFFICE provides.

Callback intentionally skips CSRF: ONLYOFFICE Server cannot present
csrf cookies. Authentication is the scoped JWT bound to (data_item, user).
"""

from __future__ import annotations

import hashlib
import ipaddress
import io
import socket
from datetime import datetime, timezone
from tempfile import SpooledTemporaryFile
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import (
    enforce_rate_limit,
    get_current_user,
    get_current_workspace_id,
    get_current_workspace_role,
    get_db_session,
    is_workspace_write_role,
)
from app.core.errors import ApiError
from app.models import DataItem, User
from app.routers.utils import get_data_item_in_workspace
from app.services import storage as storage_service
from app.services.onlyoffice import (
    build_editor_config,
    document_key,
    is_onlyoffice_eligible,
    verify_onlyoffice_payload,
    verify_scoped_token,
)


router = APIRouter(prefix="/api/v1/onlyoffice", tags=["onlyoffice"])


# Status codes ONLYOFFICE Server emits in the callback body.
_STATUS_EDITING = 1
_STATUS_READY_TO_SAVE = 2
_STATUS_SAVE_ERROR = 3
_STATUS_CLOSED_NO_CHANGES = 4
_STATUS_FORCE_SAVE = 6
_STATUS_FORCE_SAVE_ERROR = 7

_SAVE_STATUSES = {_STATUS_READY_TO_SAVE, _STATUS_FORCE_SAVE}


def _ensure_enabled() -> None:
    if not settings.onlyoffice_enabled:
        raise ApiError(
            "onlyoffice_disabled",
            "ONLYOFFICE integration is not enabled on this server.",
            status_code=503,
        )
    if not settings.onlyoffice_jwt_secret:
        raise ApiError(
            "onlyoffice_misconfigured",
            "ONLYOFFICE JWT secret is missing.",
            status_code=503,
        )


def _is_completed_data_item(item: DataItem) -> bool:
    status = (item.meta_json or {}).get("upload_status")
    return status in {None, "completed", "index_failed"}


def _validate_callback_download_url(download_url: str) -> str:
    parsed = urlparse(download_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or not parsed.hostname:
        raise ValueError("invalid callback download URL")
    if parsed.username or parsed.password:
        raise ValueError("callback download URL must not contain credentials")

    expected_origin = settings.normalize_origin(settings.onlyoffice_doc_server_url)
    actual_origin = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    if actual_origin != expected_origin:
        raise ValueError("callback download URL origin is not allowed")

    try:
        resolved = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("callback download URL host cannot be resolved") from exc
    for info in resolved:
        address = info[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            continue
        if (
            ip.is_multicast
            or ip.is_unspecified
            or ip.is_link_local
            or ip.is_reserved
            or (settings.is_production and (ip.is_private or ip.is_loopback))
        ):
            raise ValueError("callback download URL resolves to a disallowed address")
    return download_url


@router.get("/documents/{data_item_id}/config")
def get_editor_config(
    data_item_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    workspace_role: str = Depends(get_current_workspace_role),
) -> dict[str, Any]:
    _ensure_enabled()
    item = get_data_item_in_workspace(
        db, data_item_id=data_item_id, workspace_id=workspace_id
    )
    if not item or not _is_completed_data_item(item):
        raise ApiError("not_found", "Document not found", status_code=404)
    if not is_onlyoffice_eligible(item.filename, item.media_type):
        raise ApiError(
            "unsupported_format",
            "This file type cannot be opened in the Office editor.",
            status_code=415,
        )

    return build_editor_config(
        item,
        current_user,
        can_edit=is_workspace_write_role(workspace_role),
    )


@router.get("/documents/{data_item_id}/content")
def get_document_content(
    data_item_id: str,
    token: str = Query(...),
    db: Session = Depends(get_db_session),
) -> StreamingResponse:
    """Streamed by ONLYOFFICE Document Server when the editor opens.

    Auth is the scoped JWT (download). No session cookie is available
    because the request originates from the ONLYOFFICE container.
    """
    _ensure_enabled()
    try:
        verify_scoped_token(
            token, expected_action="download", expected_data_item_id=data_item_id
        )
    except ValueError as exc:
        raise ApiError("invalid_token", str(exc), status_code=401) from exc

    item = db.query(DataItem).filter(DataItem.id == data_item_id).first()
    if not item or not _is_completed_data_item(item):
        raise ApiError("not_found", "Document not found", status_code=404)

    obj = storage_service.get_s3_client().get_object(
        Bucket=settings.s3_private_bucket,
        Key=item.object_key,
    )
    body_bytes = obj["Body"].read()
    safe_name = storage_service.sanitize_filename(item.filename or "document")
    return StreamingResponse(
        io.BytesIO(body_bytes),
        media_type=item.media_type or "application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/documents/{data_item_id}/callback")
def receive_callback(
    request: Request,
    data_item_id: str,
    token: str = Query(...),
    body: dict[str, Any] = Body(default_factory=dict),
    db: Session = Depends(get_db_session),
) -> dict[str, int]:
    """Save callback from ONLYOFFICE Document Server.

    Spec: https://api.onlyoffice.com/editors/callback
    Returns `{"error": 0}` on success per ONLYOFFICE convention.

    Note: this endpoint deliberately omits the CSRF dependency — the
    ONLYOFFICE container can't present csrf cookies. The scoped JWT is
    the auth boundary.
    """
    _ensure_enabled()
    try:
        token_payload = verify_scoped_token(
            token, expected_action="callback", expected_data_item_id=data_item_id
        )
    except ValueError as exc:
        raise ApiError("invalid_token", str(exc), status_code=401) from exc

    user_id = str(token_payload.get("uid") or "")
    if not user_id:
        raise ApiError("invalid_token", "Missing user binding", status_code=401)

    # The Document Server must run with JWT_ENABLED=true. The callback body
    # is wrapped in a JWT under `token`; never trust the unsigned outer JSON.
    inner_token = body.get("token")
    if not isinstance(inner_token, str) or not inner_token:
        raise ApiError(
            "invalid_doc_token", "ONLYOFFICE body JWT is required", status_code=401
        )
    try:
        payload: dict[str, Any] = verify_onlyoffice_payload(inner_token)
    except Exception as exc:  # noqa: BLE001
        raise ApiError(
            "invalid_doc_token", "ONLYOFFICE body JWT invalid", status_code=401
        ) from exc

    item = db.query(DataItem).filter(DataItem.id == data_item_id).first()
    if not item:
        raise ApiError("not_found", "Document not found", status_code=404)
    if not is_onlyoffice_eligible(item.filename, item.media_type):
        raise ApiError("unsupported_format", "Unsupported document format", status_code=415)

    status_code = int(payload.get("status", 0))
    download_url = payload.get("url")
    payload_key = payload.get("key")
    if payload_key and str(payload_key) != document_key(item):
        raise ApiError("invalid_doc_key", "ONLYOFFICE document key mismatch", status_code=401)
    if status_code in _SAVE_STATUSES:
        if not payload_key:
            raise ApiError("invalid_doc_key", "ONLYOFFICE document key is required", status_code=401)
        if not isinstance(download_url, str) or not download_url:
            return {"error": 1}
        try:
            download_url = _validate_callback_download_url(download_url)
        except ValueError:
            return {"error": 1}

    if status_code in _SAVE_STATUSES and download_url:
        enforce_rate_limit(
            request,
            scope="onlyoffice:callback-save",
            identifier=str(data_item_id),
            limit=settings.onlyoffice_callback_rate_limit_max,
            window_seconds=settings.onlyoffice_callback_rate_limit_window_seconds,
        )
        # Stream the saved file to a spooled temp buffer (RAM ≤ 1 MiB, then
        # spills to /tmp), then hand the file handle to S3 so boto3 chunks
        # the upload. This avoids holding the entire document in API
        # process memory — a 50 MB PPTX previously consumed 50 MB of RAM
        # per concurrent forcesave; now it stays in /tmp instead.
        spool_threshold_bytes = 1024 * 1024  # 1 MiB before spilling to disk
        max_bytes = max(
            settings.upload_max_mb * 1024 * 1024,
            64 * 1024 * 1024,  # ONLYOFFICE saves can exceed UPLOAD_MAX_MB
        )
        buffer = SpooledTemporaryFile(max_size=spool_threshold_bytes)
        sha = hashlib.sha256()
        size = 0
        try:
            with httpx.Client(timeout=120.0, follow_redirects=False) as client:
                with client.stream("GET", download_url) as resp:
                    resp.raise_for_status()
                    for chunk in resp.iter_bytes(chunk_size=64 * 1024):
                        if not chunk:
                            continue
                        size += len(chunk)
                        if size > max_bytes:
                            raise ValueError(
                                f"ONLYOFFICE save payload exceeds {max_bytes} bytes",
                            )
                        sha.update(chunk)
                        buffer.write(chunk)
        except Exception:  # noqa: BLE001
            buffer.close()
            # Don't 500 — return error code to ONLYOFFICE so it retries.
            return {"error": 1}

        workspace_id = _resolve_workspace_for_item(db, item)
        if not workspace_id:
            buffer.close()
            return {"error": 1}
        try:
            from app.services.storage_quota import assert_can_store

            incoming_quota_bytes = max(0, int(size) - int(item.size_bytes or 0)) + int(size)
            assert_can_store(
                db,
                workspace_id=workspace_id,
                incoming_bytes=incoming_quota_bytes,
            )
        except Exception:  # noqa: BLE001
            buffer.close()
            return {"error": 1}

        try:
            buffer.seek(0)
            storage_service.put_object_bytes(
                bucket_name=settings.s3_private_bucket,
                object_key=item.object_key,
                payload=buffer,
                media_type=item.media_type or "application/octet-stream",
            )
        finally:
            buffer.close()

        item.size_bytes = size
        item.sha256 = sha.hexdigest()
        item.meta_json = {
            **(item.meta_json or {}),
            "upload_status": "completed",
            "edited_in_notebook": True,
            "edited_at": datetime.now(timezone.utc).isoformat(),
            "edited_via": "onlyoffice",
        }
        from app.services.document_versions import write_version_snapshot
        write_version_snapshot(
            db, item=item, saved_by=user_id, saved_via="onlyoffice",
        )
        db.commit()

        # Re-trigger the same study/index pipeline real saves use.
        if workspace_id:
            from app.routers.datasets import _enqueue_data_item_reindex

            _enqueue_data_item_reindex(db, item, workspace_id, user_id)

            # The new version snapshot adds bytes; bust the storage
            # usage cache so the next badge poll reflects them.
            from app.services.storage_quota import (
                invalidate_workspace_usage_cache,
            )

            invalidate_workspace_usage_cache(workspace_id)

    # Status 1 (editing started) and 4 (closed without changes) are no-op
    # acknowledgements. Status 3 / 7 are save errors we just acknowledge —
    # the user retries from the editor.
    return {"error": 0}


def _resolve_workspace_for_item(db: Session, item: DataItem) -> str | None:
    """Resolve the workspace that owns this data item via dataset→project."""
    from app.models import Dataset, Project

    if not item.dataset_id:
        return None
    dataset = db.get(Dataset, item.dataset_id)
    if not dataset or not dataset.project_id:
        return None
    project = db.get(Project, dataset.project_id)
    if not project or not project.workspace_id:
        return None
    return str(project.workspace_id)
