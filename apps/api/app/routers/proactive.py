"""S5 Proactive digests API."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import (
    get_current_user,
    get_current_workspace_id,
    get_db_session,
    require_csrf_protection,
    require_workspace_write_access,
)
from app.core.errors import ApiError
from app.models import ProactiveDigest, Project, User
from app.schemas.proactive import (
    AckResponse,
    DigestDetail,
    DigestListItem,
    GenerateNowRequest,
    PaginatedDigests,
)

router = APIRouter(prefix="/api/v1/digests", tags=["proactive"])


def _parse_cursor(cursor: str | None) -> datetime | None:
    if not cursor:
        return None
    try:
        return datetime.fromisoformat(cursor.replace("Z", "+00:00"))
    except ValueError:
        raise ApiError("invalid_input", "Bad cursor", status_code=400)


def _verify_workspace(digest: ProactiveDigest, workspace_id: str) -> None:
    if digest.workspace_id != workspace_id:
        raise ApiError("not_found", "Digest not found", status_code=404)


@router.get("/unread-count")
def unread_count(
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
) -> dict[str, int]:
    n = (
        db.query(ProactiveDigest)
        .filter(ProactiveDigest.workspace_id == workspace_id)
        .filter(ProactiveDigest.status == "unread")
        .count()
    )
    return {"unread_count": int(n)}


@router.get("", response_model=PaginatedDigests)
def list_digests(
    kind: str | None = None,
    status: str | None = None,
    limit: int = 20,
    cursor: str | None = None,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
) -> PaginatedDigests:
    limit = max(1, min(limit, 100))
    q = (
        db.query(ProactiveDigest)
        .filter(ProactiveDigest.workspace_id == workspace_id)
    )
    if kind:
        q = q.filter(ProactiveDigest.kind == kind)
    if status:
        q = q.filter(ProactiveDigest.status == status)
    cur = _parse_cursor(cursor)
    if cur:
        q = q.filter(ProactiveDigest.created_at < cur)
    rows = q.order_by(ProactiveDigest.created_at.desc()).limit(limit + 1).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = rows[-1].created_at.isoformat() if rows and has_more else None

    unread_total = (
        db.query(ProactiveDigest)
        .filter(ProactiveDigest.workspace_id == workspace_id)
        .filter(ProactiveDigest.status == "unread")
        .count()
    )

    return PaginatedDigests(
        items=[DigestListItem.model_validate(r, from_attributes=True) for r in rows],
        next_cursor=next_cursor,
        unread_count=int(unread_total),
    )


@router.get("/{digest_id}", response_model=DigestDetail)
def get_digest(
    digest_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
) -> DigestDetail:
    d = db.query(ProactiveDigest).filter_by(id=digest_id).first()
    if d is None:
        raise ApiError("not_found", "Digest not found", status_code=404)
    _verify_workspace(d, workspace_id)
    return DigestDetail.model_validate(d, from_attributes=True)


@router.post("/{digest_id}/read", response_model=AckResponse)
def mark_read(
    digest_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _: None = Depends(require_workspace_write_access),
    __: None = Depends(require_csrf_protection),
) -> AckResponse:
    d = db.query(ProactiveDigest).filter_by(id=digest_id).first()
    if d is None or d.workspace_id != workspace_id:
        raise ApiError("not_found", "Digest not found", status_code=404)
    if d.status != "read":
        d.status = "read"
        d.read_at = datetime.now(timezone.utc)
        db.add(d); db.commit()
    return AckResponse(ok=True)


@router.post("/{digest_id}/dismiss", response_model=AckResponse)
def mark_dismissed(
    digest_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _: None = Depends(require_workspace_write_access),
    __: None = Depends(require_csrf_protection),
) -> AckResponse:
    d = db.query(ProactiveDigest).filter_by(id=digest_id).first()
    if d is None or d.workspace_id != workspace_id:
        raise ApiError("not_found", "Digest not found", status_code=404)
    if d.status != "dismissed":
        d.status = "dismissed"
        d.dismissed_at = datetime.now(timezone.utc)
        db.add(d); db.commit()
    return AckResponse(ok=True)


@router.post("/generate-now")
def generate_now(
    payload: GenerateNowRequest,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _: None = Depends(require_workspace_write_access),
    __: None = Depends(require_csrf_protection),
) -> dict[str, Any]:
    project = db.query(Project).filter_by(id=payload.project_id).first()
    if project is None or project.workspace_id != workspace_id:
        raise ApiError("not_found", "Project not found", status_code=404)

    now = datetime.now(timezone.utc)
    if payload.kind == "daily_digest":
        period_start = now - timedelta(hours=24)
    elif payload.kind == "weekly_reflection":
        period_start = now - timedelta(days=7)
    elif payload.kind == "deviation_reminder":
        period_start = now - timedelta(days=7)
    elif payload.kind == "relationship_reminder":
        period_start = now - timedelta(days=30)
    else:
        raise ApiError("invalid_input", "Bad kind", status_code=400)

    from app.tasks.worker_tasks import generate_proactive_digest_task
    task = generate_proactive_digest_task.delay(
        payload.project_id, payload.kind,
        period_start.isoformat(), now.isoformat(),
    )
    return {"ok": True, "task_id": task.id if hasattr(task, "id") else None}
