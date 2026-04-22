"""Retrieval API for AI action logs (S1)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import (
    get_current_user,
    get_current_workspace_id,
    get_current_workspace_role,
    get_db_session,
    is_workspace_privileged_role,
)
from app.core.errors import ApiError
from app.models import AIActionLog, AIUsageEvent, Membership, Notebook, NotebookPage, User

pages_router = APIRouter(prefix="/api/v1/pages", tags=["ai-actions"])
detail_router = APIRouter(prefix="/api/v1/ai-actions", tags=["ai-actions"])


def _parse_cursor(cursor: str | None) -> datetime | None:
    if not cursor:
        return None
    try:
        return datetime.fromisoformat(cursor.replace("Z", "+00:00"))
    except ValueError:
        raise ApiError("invalid_input", "Bad cursor", status_code=400)


def _serialize_log(log: AIActionLog, total_tokens: int) -> dict[str, Any]:
    return {
        "id": log.id,
        "action_type": log.action_type,
        "scope": log.scope,
        "status": log.status,
        "model_id": log.model_id,
        "duration_ms": log.duration_ms,
        "output_summary": log.output_summary,
        "created_at": log.created_at.isoformat(),
        "usage": {"total_tokens": total_tokens},
    }


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


def _get_page_if_readable(
    db: Session,
    *,
    page_id: str,
    workspace_id: str,
    current_user_id: str,
    workspace_role: str,
) -> NotebookPage | None:
    page = db.query(NotebookPage).filter(NotebookPage.id == page_id).first()
    if page is None:
        return None
    notebook = db.query(Notebook).filter(Notebook.id == page.notebook_id).first()
    if notebook is None or not _can_read_notebook(
        notebook,
        workspace_id=workspace_id,
        current_user_id=current_user_id,
        workspace_role=workspace_role,
    ):
        return None
    return page


@pages_router.get("/{page_id}/ai-actions")
def list_page_ai_actions(
    page_id: str,
    limit: int = 50,
    cursor: str | None = None,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    workspace_role: str = Depends(get_current_workspace_role),
) -> dict[str, Any]:
    page = _get_page_if_readable(
        db,
        page_id=page_id,
        workspace_id=workspace_id,
        current_user_id=str(current_user.id),
        workspace_role=workspace_role,
    )
    if page is None:
        raise ApiError("not_found", "Page not found", status_code=404)
    limit = max(1, min(limit, 100))
    q = (
        db.query(AIActionLog)
        .filter(AIActionLog.page_id == page_id)
        .filter(AIActionLog.workspace_id == workspace_id)
    )
    if not is_workspace_privileged_role(workspace_role):
        q = q.filter(AIActionLog.user_id == current_user.id)
    cur = _parse_cursor(cursor)
    if cur:
        q = q.filter(AIActionLog.created_at < cur)
    rows = q.order_by(AIActionLog.created_at.desc()).limit(limit + 1).all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    if not rows:
        return {"items": [], "next_cursor": None}

    log_ids = [r.id for r in rows]
    totals = dict(
        db.query(AIUsageEvent.action_log_id, AIUsageEvent.total_tokens)
        .filter(AIUsageEvent.action_log_id.in_(log_ids))
        .all()
    )

    items = [_serialize_log(r, totals.get(r.id, 0)) for r in rows]
    next_cursor = rows[-1].created_at.isoformat() if has_more else None
    return {"items": items, "next_cursor": next_cursor}


import json as _json
import logging

from botocore.exceptions import ClientError

from app.core.config import settings
from app.services import storage as storage_service

_logger = logging.getLogger(__name__)


def _deref_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict) or "_overflow_ref" not in payload:
        return payload
    try:
        client = storage_service.get_s3_client()
        resp = client.get_object(
            Bucket=settings.s3_ai_action_payloads_bucket,
            Key=payload["_overflow_ref"],
        )
        return _json.loads(resp["Body"].read().decode("utf-8"))
    except (ClientError, Exception):  # noqa: BLE001
        _logger.exception("ai-actions: overflow deref failed")
        return payload


@detail_router.get("/{log_id}")
def get_ai_action_detail(
    log_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
) -> dict[str, Any]:
    log = db.query(AIActionLog).filter(
        AIActionLog.id == log_id,
        AIActionLog.workspace_id == workspace_id,
    ).first()
    if log is None:
        raise ApiError("not_found", "Action log not found", status_code=404)

    if str(log.user_id) != str(current_user.id):
        membership = db.query(Membership).filter(
            Membership.workspace_id == workspace_id,
            Membership.user_id == current_user.id,
        ).first()
        if not membership or membership.role != "owner":
            raise ApiError("forbidden", "Not allowed", status_code=403)

    usage_rows = (
        db.query(AIUsageEvent)
        .filter(AIUsageEvent.action_log_id == log.id)
        .order_by(AIUsageEvent.created_at.asc())
        .all()
    )

    return {
        "id": log.id,
        "workspace_id": log.workspace_id,
        "user_id": log.user_id,
        "notebook_id": log.notebook_id,
        "page_id": log.page_id,
        "block_id": log.block_id,
        "action_type": log.action_type,
        "scope": log.scope,
        "status": log.status,
        "model_id": log.model_id,
        "duration_ms": log.duration_ms,
        "input_json": _deref_payload(log.input_json),
        "output_json": _deref_payload(log.output_json),
        "output_summary": log.output_summary,
        "error_code": log.error_code,
        "error_message": log.error_message,
        "trace_metadata": log.trace_metadata,
        "created_at": log.created_at.isoformat(),
        "usage_events": [
            {
                "id": u.id,
                "event_type": u.event_type,
                "model_id": u.model_id,
                "prompt_tokens": u.prompt_tokens,
                "completion_tokens": u.completion_tokens,
                "total_tokens": u.total_tokens,
                "audio_seconds": u.audio_seconds,
                "file_count": u.file_count,
                "count_source": u.count_source,
                "meta_json": u.meta_json,
            }
            for u in usage_rows
        ],
    }
