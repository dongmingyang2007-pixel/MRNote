"""Counters used by require_entitlement for counted-cap entitlements."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    AIUsageEvent, Notebook, NotebookPage, QuotaCounter, StudyAsset, Workspace,
)


AI_ACTIONS_MONTHLY_KEY = "ai.actions.monthly"


def _month_start_utc() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def count_notebooks(db: Session, workspace_id: str) -> int:
    return int(
        db.query(func.count(Notebook.id))
        .filter(Notebook.workspace_id == workspace_id)
        .scalar() or 0
    )


def count_pages(db: Session, workspace_id: str) -> int:
    return int(
        db.query(func.count(NotebookPage.id))
        .join(Notebook, Notebook.id == NotebookPage.notebook_id)
        .filter(Notebook.workspace_id == workspace_id)
        .scalar() or 0
    )


def count_study_assets(db: Session, workspace_id: str) -> int:
    return int(
        db.query(func.count(StudyAsset.id))
        .join(Notebook, Notebook.id == StudyAsset.notebook_id)
        .filter(Notebook.workspace_id == workspace_id)
        .scalar() or 0
    )


def count_ai_actions_this_month(db: Session, workspace_id: str) -> int:
    month_start = _month_start_utc()
    usage_events = int(
        db.query(func.count(AIUsageEvent.id))
        .filter(AIUsageEvent.workspace_id == workspace_id)
        .filter(AIUsageEvent.created_at >= month_start)
        .scalar() or 0
    )
    reserved_counter = (
        db.query(QuotaCounter)
        .filter(
            QuotaCounter.workspace_id == workspace_id,
            QuotaCounter.key == AI_ACTIONS_MONTHLY_KEY,
            QuotaCounter.period_start == month_start,
        )
        .first()
    )
    if reserved_counter is None:
        return usage_events
    return max(usage_events, int(reserved_counter.used_count or 0))


def reserve_ai_action_quota(db: Session, *, workspace_id: str, limit: int) -> int:
    """Reserve one monthly AI action and return the pre-reservation usage.

    This closes the check-then-use race: the counter row is updated before
    a model call starts, under the workspace row lock. AIUsageEvent rows
    remain the audit trail; this counter is the concurrency gate.
    """
    month_start = _month_start_utc()
    (
        db.query(Workspace)
        .filter(Workspace.id == workspace_id)
        .with_for_update()
        .first()
    )
    event_count = int(
        db.query(func.count(AIUsageEvent.id))
        .filter(AIUsageEvent.workspace_id == workspace_id)
        .filter(AIUsageEvent.created_at >= month_start)
        .scalar() or 0
    )
    counter = (
        db.query(QuotaCounter)
        .filter(
            QuotaCounter.workspace_id == workspace_id,
            QuotaCounter.key == AI_ACTIONS_MONTHLY_KEY,
            QuotaCounter.period_start == month_start,
        )
        .with_for_update()
        .first()
    )
    current = event_count
    if counter is None:
        counter = QuotaCounter(
            workspace_id=workspace_id,
            key=AI_ACTIONS_MONTHLY_KEY,
            period_start=month_start,
            used_count=event_count,
        )
        db.add(counter)
        db.flush()
    else:
        current = max(event_count, int(counter.used_count or 0))
        if current != counter.used_count:
            counter.used_count = current

    if current >= limit:
        db.add(counter)
        db.flush()
        return current

    counter.used_count = current + 1
    db.add(counter)
    db.flush()
    return current
