"""Retrieval API for AI action logs (S1)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import (
    get_current_user,
    get_current_workspace_id,
    get_db_session,
)
from app.core.errors import ApiError
from app.models import AIActionLog, AIUsageEvent, Membership, User

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


@pages_router.get("/{page_id}/ai-actions")
def list_page_ai_actions(
    page_id: str,
    limit: int = 50,
    cursor: str | None = None,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
) -> dict[str, Any]:
    _ = current_user
    limit = max(1, min(limit, 100))
    q = (
        db.query(AIActionLog)
        .filter(AIActionLog.page_id == page_id)
        .filter(AIActionLog.workspace_id == workspace_id)
    )
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
