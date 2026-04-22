from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from app.models import AIActionLog, NotebookPage, StudyAsset, StudyCard, StudyDeck


STUDY_ACTION_TYPES = (
    "study.ask",
    "study.flashcards",
    "study.quiz",
    "study.review_card",
)

AI_ONLY_ACTION_TYPES = (
    "study.ask",
    "study.flashcards",
    "study.quiz",
)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _fallback_action_summary(action_type: str) -> str:
    mapping = {
        "study.ask": "Asked the study assistant",
        "study.flashcards": "Generated flashcards",
        "study.quiz": "Generated a quiz",
        "study.review_card": "Reviewed a flashcard",
    }
    return mapping.get(action_type, action_type)


def collect_study_insights(
    db: Session,
    *,
    notebook_id: str,
    period_days: int = 7,
) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    period_start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=max(1, period_days) - 1)

    assets = (
        db.query(StudyAsset)
        .filter(
            StudyAsset.notebook_id == notebook_id,
            StudyAsset.status != "deleted",
        )
        .all()
    )
    indexed_assets = [asset for asset in assets if asset.status == "indexed"]
    generated_pages = int(
        db.query(func.count(NotebookPage.id))
        .filter(
            NotebookPage.notebook_id == notebook_id,
            NotebookPage.slug.like("study-asset-%"),
        )
        .scalar()
        or 0
    )

    active_decks = (
        db.query(StudyDeck)
        .filter(
            StudyDeck.notebook_id == notebook_id,
            StudyDeck.archived_at.is_(None),
        )
        .all()
    )
    deck_ids = [deck.id for deck in active_decks]

    total_cards = 0
    new_cards = 0
    due_cards = 0
    weak_cards_count = 0
    confusions_logged = 0
    deck_pressure: list[dict[str, object]] = []
    weak_cards: list[dict[str, object]] = []

    if deck_ids:
        cards_query = db.query(StudyCard).filter(StudyCard.deck_id.in_(deck_ids))
        due_filter = or_(
            StudyCard.next_review_at.is_(None),
            StudyCard.next_review_at <= now,
        )
        weak_filter = or_(
            StudyCard.consecutive_failures > 0,
            StudyCard.lapse_count > 0,
        )

        total_cards = cards_query.count()
        new_cards = cards_query.filter(StudyCard.review_count == 0).count()
        due_cards = cards_query.filter(due_filter).count()
        weak_cards_count = cards_query.filter(weak_filter).count()
        confusions_logged = cards_query.filter(
            StudyCard.confusion_memory_written_at.is_not(None),
            StudyCard.confusion_memory_written_at >= period_start,
            StudyCard.confusion_memory_written_at <= now,
        ).count()

        deck_rows = (
            db.query(
                StudyDeck.id,
                StudyDeck.name,
                StudyDeck.card_count,
                func.coalesce(
                    func.sum(case((due_filter, 1), else_=0)),
                    0,
                ).label("due_cards"),
                func.max(StudyCard.last_review_at).label("last_review_at"),
                func.min(StudyCard.next_review_at).label("next_due_at"),
            )
            .outerjoin(StudyCard, StudyCard.deck_id == StudyDeck.id)
            .filter(
                StudyDeck.notebook_id == notebook_id,
                StudyDeck.archived_at.is_(None),
            )
            .group_by(StudyDeck.id, StudyDeck.name, StudyDeck.card_count)
            .all()
        )
        deck_pressure = [
            {
                "deck_id": row.id,
                "deck_name": row.name,
                "total_cards": int(row.card_count or 0),
                "due_cards": int(row.due_cards or 0),
                "last_review_at": _as_utc(row.last_review_at),
                "next_due_at": _as_utc(row.next_due_at),
            }
            for row in deck_rows
            if int(row.card_count or 0) > 0
        ]
        deck_pressure.sort(
            key=lambda item: (
                -int(item["due_cards"]),
                -int(item["total_cards"]),
                item["deck_name"],
            ),
        )

        weak_rows = (
            db.query(StudyCard, StudyDeck.name)
            .join(StudyDeck, StudyDeck.id == StudyCard.deck_id)
            .filter(
                StudyDeck.notebook_id == notebook_id,
                StudyDeck.archived_at.is_(None),
                weak_filter,
            )
            .order_by(
                StudyCard.consecutive_failures.desc(),
                StudyCard.lapse_count.desc(),
                StudyCard.review_count.asc(),
                StudyCard.updated_at.desc(),
            )
            .limit(6)
            .all()
        )
        weak_cards = [
            {
                "card_id": card.id,
                "deck_id": card.deck_id,
                "deck_name": deck_name,
                "front": card.front[:180],
                "review_count": int(card.review_count or 0),
                "lapse_count": int(card.lapse_count or 0),
                "consecutive_failures": int(card.consecutive_failures or 0),
                "next_review_at": _as_utc(card.next_review_at),
            }
            for card, deck_name in weak_rows
        ]

    action_rows = (
        db.query(AIActionLog)
        .filter(
            AIActionLog.notebook_id == notebook_id,
            AIActionLog.action_type.in_(STUDY_ACTION_TYPES),
            AIActionLog.created_at >= period_start,
            AIActionLog.created_at <= now,
        )
        .order_by(AIActionLog.created_at.desc())
        .all()
    )

    action_counter: Counter[str] = Counter()
    day_buckets: dict[str, dict[str, int]] = {}
    active_days: set[str] = set()

    for row in action_rows:
        action_counter[row.action_type] += 1
        created_at = _as_utc(row.created_at) or now
        day_key = created_at.date().isoformat()
        bucket = day_buckets.setdefault(day_key, {"review_count": 0, "ai_action_count": 0})
        if row.action_type == "study.review_card":
            bucket["review_count"] += 1
        elif row.action_type in AI_ONLY_ACTION_TYPES:
            bucket["ai_action_count"] += 1
        active_days.add(day_key)

    daily_activity: list[dict[str, object]] = []
    for offset in range(max(1, period_days)):
        date_value = (period_start + timedelta(days=offset)).date().isoformat()
        bucket = day_buckets.get(date_value, {"review_count": 0, "ai_action_count": 0})
        daily_activity.append(
            {
                "date": date_value,
                "review_count": bucket["review_count"],
                "ai_action_count": bucket["ai_action_count"],
            }
        )

    recent_actions = [
        {
            "id": row.id,
            "action_type": row.action_type,
            "summary": (row.output_summary or "").strip()[:180] or _fallback_action_summary(row.action_type),
            "created_at": _as_utc(row.created_at) or now,
        }
        for row in action_rows[:6]
    ]

    action_counts = [
        {
            "action_type": action_type,
            "count": int(action_counter.get(action_type, 0)),
        }
        for action_type in STUDY_ACTION_TYPES
    ]

    return {
        "period_start": period_start,
        "period_end": now,
        "active_days": len(active_days),
        "totals": {
            "assets": len(assets),
            "indexed_assets": len(indexed_assets),
            "generated_pages": generated_pages,
            "chunks": sum(int(asset.total_chunks or 0) for asset in indexed_assets),
            "decks": len(active_decks),
            "cards": total_cards,
            "new_cards": new_cards,
            "due_cards": due_cards,
            "weak_cards": weak_cards_count,
            "reviewed_this_week": int(action_counter.get("study.review_card", 0)),
            "ai_actions_this_week": sum(int(action_counter.get(action_type, 0)) for action_type in AI_ONLY_ACTION_TYPES),
            "confusions_logged": confusions_logged,
        },
        "action_counts": action_counts,
        "daily_activity": daily_activity,
        "deck_pressure": deck_pressure[:4],
        "weak_cards": weak_cards,
        "recent_actions": recent_actions,
    }
