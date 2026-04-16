"""S5 proactive services: pure source-material collectors.

None of these functions call an LLM — they only aggregate SQL data
into dicts that the prompt-builder / rule engine downstream can
consume. Keeping them pure makes the 8 unit tests trivial.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    AIActionLog, Memory, MemoryEvidence, Notebook, NotebookPage,
    StudyCard, StudyDeck,
)
from app.services.memory_metadata import get_memory_kind, get_subject_kind
from app.services.memory_v2 import find_reconfirm_candidates


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _project_notebook_ids(db: Session, project_id: str) -> list[str]:
    rows = db.query(Notebook.id).filter(Notebook.project_id == project_id).all()
    return [r[0] for r in rows]


def _as_utc(value: datetime | None) -> datetime | None:
    """Coerce naive datetimes (e.g. from SQLite round-trips) to UTC-aware."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _summarize_action_logs(
    db: Session, *, notebook_ids: list[str],
    period_start: datetime, period_end: datetime, sample_limit: int = 5,
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    if not notebook_ids:
        return {}, []
    counts_rows = (
        db.query(AIActionLog.action_type, func.count(AIActionLog.id))
        .filter(AIActionLog.notebook_id.in_(notebook_ids))
        .filter(AIActionLog.created_at >= period_start)
        .filter(AIActionLog.created_at <= period_end)
        .group_by(AIActionLog.action_type)
        .all()
    )
    counts = {action_type: int(n) for action_type, n in counts_rows}

    sample_rows = (
        db.query(AIActionLog)
        .filter(AIActionLog.notebook_id.in_(notebook_ids))
        .filter(AIActionLog.created_at >= period_start)
        .filter(AIActionLog.created_at <= period_end)
        .order_by(AIActionLog.created_at.desc())
        .limit(sample_limit)
        .all()
    )
    samples = [
        {
            "action_log_id": r.id,
            "action_type": r.action_type,
            "output_summary": (r.output_summary or "")[:200],
            "created_at": r.created_at.isoformat(),
        }
        for r in sample_rows
    ]
    return counts, samples


def _page_edits(
    db: Session, *, notebook_ids: list[str],
    period_start: datetime, period_end: datetime, limit: int = 10,
) -> list[dict[str, Any]]:
    if not notebook_ids:
        return []
    rows = (
        db.query(NotebookPage)
        .filter(NotebookPage.notebook_id.in_(notebook_ids))
        .filter(NotebookPage.last_edited_at >= period_start)
        .filter(NotebookPage.last_edited_at <= period_end)
        .order_by(NotebookPage.last_edited_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "page_id": p.id,
            "title": p.title or "(untitled)",
            "last_edited_at": p.last_edited_at.isoformat() if p.last_edited_at else None,
        }
        for p in rows
    ]


# ---------------------------------------------------------------------------
# Collectors
# ---------------------------------------------------------------------------


def collect_daily_materials(
    db: Session,
    *,
    project_id: str,
    period_start: datetime,
    period_end: datetime,
) -> dict[str, Any]:
    notebook_ids = _project_notebook_ids(db, project_id)
    action_counts, action_samples = _summarize_action_logs(
        db, notebook_ids=notebook_ids,
        period_start=period_start, period_end=period_end,
    )
    page_edits = _page_edits(
        db, notebook_ids=notebook_ids,
        period_start=period_start, period_end=period_end,
    )
    reconfirm_memories = find_reconfirm_candidates(
        db, project_id=project_id, limit=5, now=period_end,
    )
    reconfirm_items = [
        {
            "memory_id": m.id,
            "fact": m.content[:200],
            "age_days": max(
                0,
                (_as_utc(period_end) - _as_utc(m.created_at)).days,
            ),
            "reason": "stale",
        }
        for m in reconfirm_memories
    ]
    return {
        "action_counts": action_counts,
        "action_samples": action_samples,
        "page_edits": page_edits,
        "reconfirm_items": reconfirm_items,
    }


def collect_weekly_materials(
    db: Session,
    *,
    project_id: str,
    period_start: datetime,
    period_end: datetime,
) -> dict[str, Any]:
    notebook_ids = _project_notebook_ids(db, project_id)
    action_counts, action_samples = _summarize_action_logs(
        db, notebook_ids=notebook_ids,
        period_start=period_start, period_end=period_end,
        sample_limit=10,
    )
    page_edits = _page_edits(
        db, notebook_ids=notebook_ids,
        period_start=period_start, period_end=period_end,
        limit=20,
    )

    # StudyCard aggregates over decks whose notebook is in the project
    if notebook_ids:
        deck_ids = [
            d[0]
            for d in (
                db.query(StudyDeck.id)
                .filter(StudyDeck.notebook_id.in_(notebook_ids))
                .all()
            )
        ]
    else:
        deck_ids = []
    if deck_ids:
        cards = (
            db.query(StudyCard)
            .filter(StudyCard.deck_id.in_(deck_ids))
            .all()
        )
        cards_reviewed = sum(c.review_count for c in cards)
        lapse_count = sum(c.lapse_count for c in cards)
        confusions_logged = sum(
            1 for c in cards
            if getattr(c, "confusion_memory_written_at", None) is not None
        )
    else:
        cards_reviewed = 0
        lapse_count = 0
        confusions_logged = 0

    # Blocker tasks: action_type=="task.reopen" in window
    blocker_rows: list[AIActionLog] = []
    if notebook_ids:
        blocker_rows = (
            db.query(AIActionLog)
            .filter(AIActionLog.notebook_id.in_(notebook_ids))
            .filter(AIActionLog.action_type == "task.reopen")
            .filter(AIActionLog.created_at >= period_start)
            .filter(AIActionLog.created_at <= period_end)
            .order_by(AIActionLog.created_at.desc())
            .limit(10)
            .all()
        )
    blocker_tasks = [
        {
            "action_log_id": r.id,
            "block_id": r.block_id,
            "created_at": r.created_at.isoformat(),
        }
        for r in blocker_rows
    ]

    return {
        "action_counts": action_counts,
        "action_samples": action_samples,
        "page_edits": page_edits,
        "study_stats": {
            "cards_reviewed": cards_reviewed,
            "lapse_count": lapse_count,
            "confusions_logged": confusions_logged,
        },
        "blocker_tasks": blocker_tasks,
    }


def collect_goal_materials(
    db: Session,
    *,
    project_id: str,
    period_start: datetime,
    period_end: datetime,
) -> dict[str, Any]:
    memories = (
        db.query(Memory)
        .filter(Memory.project_id == project_id)
        .filter(Memory.node_status == "active")
        .all()
    )
    goals = [m for m in memories if get_memory_kind(m) == "goal"][:10]
    goal_payload = [
        {
            "memory_id": g.id,
            "content": g.content,
            # Surfaced as "importance" for downstream LLM prompt semantics.
            # The column on Memory is actually `confidence`; we preserve the
            # public dict key that generator.py expects.
            "importance": float(g.confidence or 0.0),
        }
        for g in goals
    ]

    notebook_ids = _project_notebook_ids(db, project_id)
    _, action_samples = _summarize_action_logs(
        db, notebook_ids=notebook_ids,
        period_start=period_start, period_end=period_end,
        sample_limit=15,
    )
    page_edits = _page_edits(
        db, notebook_ids=notebook_ids,
        period_start=period_start, period_end=period_end,
        limit=10,
    )
    activity_blurbs = [
        s["output_summary"] for s in action_samples if s["output_summary"]
    ]
    activity_blurbs += [p["title"] for p in page_edits]
    activity_summary = " · ".join(activity_blurbs)[:500]

    return {
        "goals": goal_payload,
        "activity_summary": activity_summary,
    }


def collect_relationship_materials(
    db: Session,
    *,
    project_id: str,
    now: datetime | None = None,
    stale_days: int = 30,
) -> list[dict[str, Any]]:
    resolved_now = now or datetime.now(timezone.utc)
    memories = (
        db.query(Memory)
        .filter(Memory.project_id == project_id)
        .filter(Memory.node_status == "active")
        .all()
    )
    out: list[dict[str, Any]] = []
    # TODO(perf): This is an N+1 query — we fetch last-evidence per-memory.
    # At expected scale (~hundreds of person memories per project) it's
    # acceptable; when that grows, rewrite as a single GROUP BY memory_id
    # with MAX(created_at) + LEFT JOIN for the no-evidence branch.
    for memory in memories:
        if get_subject_kind(memory) != "person":
            continue
        last_evidence = (
            db.query(MemoryEvidence)
            .filter(MemoryEvidence.memory_id == memory.id)
            .order_by(MemoryEvidence.created_at.desc())
            .first()
        )
        if last_evidence is None:
            out.append({
                "memory_id": memory.id,
                "person_label": memory.content[:120],
                "last_mention_at": None,
                "days_since": None,
            })
            continue
        last_created_at = _as_utc(last_evidence.created_at)
        days = (_as_utc(resolved_now) - last_created_at).days
        if days <= stale_days:
            continue
        out.append({
            "memory_id": memory.id,
            "person_label": memory.content[:120],
            "last_mention_at": last_created_at.isoformat(),
            "days_since": days,
        })
    return out
