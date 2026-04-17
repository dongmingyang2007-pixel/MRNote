"""Counters used by require_entitlement for counted-cap entitlements."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    AIUsageEvent, Notebook, NotebookPage, StudyAsset,
)


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
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return int(
        db.query(func.count(AIUsageEvent.id))
        .filter(AIUsageEvent.workspace_id == workspace_id)
        .filter(AIUsageEvent.created_at >= month_start)
        .scalar() or 0
    )
