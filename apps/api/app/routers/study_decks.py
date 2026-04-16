"""StudyDeck + StudyCard CRUD and review endpoints (S4)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
from app.models import Notebook, StudyCard, StudyDeck, User
from app.schemas.study_decks import (
    CardCreate,
    CardOut,
    CardPatch,
    DeckCreate,
    DeckOut,
    DeckPatch,
    PaginatedDecks,
)

notebooks_decks_router = APIRouter(
    prefix="/api/v1/notebooks", tags=["study-decks"]
)
decks_router = APIRouter(prefix="/api/v1/decks", tags=["study-decks"])
cards_router = APIRouter(prefix="/api/v1/cards", tags=["study-decks"])


def _get_notebook_or_404(db: Session, notebook_id: str, workspace_id: str) -> Notebook:
    nb = (
        db.query(Notebook)
        .filter(Notebook.id == notebook_id, Notebook.workspace_id == workspace_id)
        .first()
    )
    if nb is None:
        raise ApiError("not_found", "Notebook not found", status_code=404)
    return nb


def _get_deck_or_404(db: Session, deck_id: str, workspace_id: str) -> StudyDeck:
    deck = db.query(StudyDeck).filter(StudyDeck.id == deck_id).first()
    if deck is None:
        raise ApiError("not_found", "Deck not found", status_code=404)
    nb = (
        db.query(Notebook)
        .filter(Notebook.id == deck.notebook_id, Notebook.workspace_id == workspace_id)
        .first()
    )
    if nb is None:
        raise ApiError("not_found", "Deck not found", status_code=404)
    return deck


def _get_card_or_404(db: Session, card_id: str, workspace_id: str) -> StudyCard:
    card = db.query(StudyCard).filter(StudyCard.id == card_id).first()
    if card is None:
        raise ApiError("not_found", "Card not found", status_code=404)
    # Verify workspace through deck → notebook
    _get_deck_or_404(db, card.deck_id, workspace_id)
    return card


# ---------------------------------------------------------------------------
# Deck endpoints
# ---------------------------------------------------------------------------


@notebooks_decks_router.get("/{notebook_id}/decks", response_model=PaginatedDecks)
def list_decks(
    notebook_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
) -> PaginatedDecks:
    _ = current_user
    _get_notebook_or_404(db, notebook_id, workspace_id)
    rows = (
        db.query(StudyDeck)
        .filter(StudyDeck.notebook_id == notebook_id)
        .order_by(StudyDeck.created_at.desc())
        .all()
    )
    return PaginatedDecks(
        items=[DeckOut.model_validate(r, from_attributes=True) for r in rows],
        total=len(rows),
    )


@notebooks_decks_router.post("/{notebook_id}/decks", response_model=DeckOut)
def create_deck(
    notebook_id: str,
    payload: DeckCreate,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf: None = Depends(require_csrf_protection),
) -> DeckOut:
    _get_notebook_or_404(db, notebook_id, workspace_id)
    deck = StudyDeck(
        notebook_id=notebook_id,
        name=payload.name,
        description=payload.description,
        created_by=str(current_user.id),
    )
    db.add(deck); db.commit(); db.refresh(deck)
    return DeckOut.model_validate(deck, from_attributes=True)


@decks_router.get("/{deck_id}", response_model=DeckOut)
def get_deck(
    deck_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
) -> DeckOut:
    _ = current_user
    deck = _get_deck_or_404(db, deck_id, workspace_id)
    return DeckOut.model_validate(deck, from_attributes=True)


@decks_router.patch("/{deck_id}", response_model=DeckOut)
def patch_deck(
    deck_id: str,
    payload: DeckPatch,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf: None = Depends(require_csrf_protection),
) -> DeckOut:
    _ = current_user
    deck = _get_deck_or_404(db, deck_id, workspace_id)
    if payload.name is not None:
        deck.name = payload.name
    if payload.description is not None:
        deck.description = payload.description
    if payload.archived is True:
        deck.archived_at = datetime.now(timezone.utc)
    elif payload.archived is False:
        deck.archived_at = None
    db.add(deck); db.commit(); db.refresh(deck)
    return DeckOut.model_validate(deck, from_attributes=True)


@decks_router.delete("/{deck_id}")
def delete_deck(
    deck_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf: None = Depends(require_csrf_protection),
) -> dict[str, Any]:
    _ = current_user
    deck = _get_deck_or_404(db, deck_id, workspace_id)
    db.delete(deck); db.commit()
    return {"ok": True}


from app.schemas.study_decks import CardOut  # noqa: E402 — keep grouped


@decks_router.get("/{deck_id}/cards")
def list_cards(
    deck_id: str,
    due_only: bool = False,
    limit: int = 50,
    cursor: str | None = None,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
) -> dict[str, Any]:
    _ = current_user
    _get_deck_or_404(db, deck_id, workspace_id)

    q = db.query(StudyCard).filter(StudyCard.deck_id == deck_id)
    if due_only:
        now = datetime.now(timezone.utc)
        q = q.filter(
            (StudyCard.next_review_at.is_(None)) | (StudyCard.next_review_at <= now)
        )
    if cursor:
        try:
            cursor_dt = datetime.fromisoformat(cursor.replace("Z", "+00:00"))
        except ValueError:
            raise ApiError("invalid_input", "Bad cursor", status_code=400)
        q = q.filter(StudyCard.created_at < cursor_dt)
    rows = q.order_by(StudyCard.created_at.desc()).limit(max(1, min(limit, 100)) + 1).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = rows[-1].created_at.isoformat() if rows and has_more else None
    return {
        "items": [CardOut.model_validate(r, from_attributes=True).model_dump(mode="json") for r in rows],
        "next_cursor": next_cursor,
    }


@decks_router.post("/{deck_id}/cards", response_model=CardOut)
def create_card(
    deck_id: str,
    payload: CardCreate,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf: None = Depends(require_csrf_protection),
) -> CardOut:
    _ = current_user
    deck = _get_deck_or_404(db, deck_id, workspace_id)
    card = StudyCard(
        deck_id=deck.id,
        front=payload.front,
        back=payload.back,
        source_type=payload.source_type,
        source_ref=payload.source_ref,
    )
    db.add(card)
    deck.card_count = (deck.card_count or 0) + 1
    db.add(deck)
    db.commit(); db.refresh(card)
    return CardOut.model_validate(card, from_attributes=True)


@cards_router.patch("/{card_id}", response_model=CardOut)
def patch_card(
    card_id: str,
    payload: CardPatch,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf: None = Depends(require_csrf_protection),
) -> CardOut:
    _ = current_user
    card = _get_card_or_404(db, card_id, workspace_id)
    if payload.front is not None:
        card.front = payload.front
    if payload.back is not None:
        card.back = payload.back
    db.add(card); db.commit(); db.refresh(card)
    return CardOut.model_validate(card, from_attributes=True)


@cards_router.delete("/{card_id}")
def delete_card(
    card_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf: None = Depends(require_csrf_protection),
) -> dict[str, Any]:
    _ = current_user
    card = _get_card_or_404(db, card_id, workspace_id)
    deck = db.query(StudyDeck).filter(StudyDeck.id == card.deck_id).first()
    if deck and deck.card_count > 0:
        deck.card_count -= 1
        db.add(deck)
    db.delete(card); db.commit()
    return {"ok": True}


from app.schemas.study_decks import ReviewRequest, ReviewResponse  # noqa: E402
from app.services.ai_action_logger import action_log_context
from app.services.fsrs import schedule_next


@decks_router.post("/{deck_id}/review/next")
async def review_next(
    deck_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf: None = Depends(require_csrf_protection),
) -> dict[str, Any]:
    """Return the next due card for this deck, or `{card: null, queue_empty: true}`."""
    _ = current_user
    deck = _get_deck_or_404(db, deck_id, workspace_id)

    now = datetime.now(timezone.utc)
    q = (
        db.query(StudyCard)
        .filter(StudyCard.deck_id == deck.id)
        .filter(
            (StudyCard.next_review_at.is_(None)) | (StudyCard.next_review_at <= now)
        )
        .order_by(StudyCard.next_review_at.asc().nullsfirst())
        .limit(1)
    )
    card = q.first()
    if card is None:
        return {"card": None, "queue_empty": True}

    days_since = 0.0
    if card.last_review_at:
        last = card.last_review_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        delta = (now - last).total_seconds()
        days_since = max(0.0, delta / 86400.0)

    return {
        "card": {
            "id": card.id,
            "front": card.front,
            "back": card.back,
            "review_count": card.review_count,
            "days_since_last": round(days_since, 3),
        },
        "queue_empty": False,
    }


@cards_router.post("/{card_id}/review", response_model=ReviewResponse)
async def review_card(
    card_id: str,
    payload: ReviewRequest,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf: None = Depends(require_csrf_protection),
) -> ReviewResponse:
    card = _get_card_or_404(db, card_id, workspace_id)
    deck = db.query(StudyDeck).filter(StudyDeck.id == card.deck_id).first()
    notebook_id = deck.notebook_id if deck else None
    now = datetime.now(timezone.utc)

    days_since = 0.0
    if card.last_review_at:
        last = card.last_review_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        days_since = max(0.0, (now - last).total_seconds() / 86400.0)

    update = schedule_next(
        difficulty=card.difficulty,
        stability=card.stability,
        rating=payload.rating,
        days_since_last_review=days_since,
    )

    async with action_log_context(
        db,
        workspace_id=str(workspace_id),
        user_id=str(current_user.id),
        action_type="study.review_card",
        scope="notebook",
        notebook_id=str(notebook_id) if notebook_id else None,
        page_id=None,
        block_id=str(card.id),
    ) as log:
        log.set_input({
            "rating": payload.rating,
            "days_since_last": round(days_since, 3),
            "marked_confused": payload.marked_confused,
        })

        card.difficulty = update.difficulty
        card.stability = update.stability
        card.last_review_at = now
        card.next_review_at = now + timedelta(days=update.next_interval_days)
        card.review_count += 1
        if payload.rating == 1:
            card.lapse_count += 1
            card.consecutive_failures += 1
        else:
            card.consecutive_failures = 0

        fire_confusion = False
        if card.confusion_memory_written_at is None and (
            card.consecutive_failures >= 3 or payload.marked_confused
        ):
            fire_confusion = True
            card.confusion_memory_written_at = now

        db.add(card); db.commit(); db.refresh(card)

        log.set_output({
            "next_review_at": card.next_review_at.isoformat(),
            "difficulty": card.difficulty,
            "stability": card.stability,
            "consecutive_failures": card.consecutive_failures,
            "fired_confusion_task": fire_confusion,
        })

    if fire_confusion:
        trigger = "manual" if payload.marked_confused else "consecutive_failures"
        from app.tasks.worker_tasks import process_study_confusion_task
        process_study_confusion_task.delay(
            str(card.id),
            str(current_user.id),
            str(workspace_id),
            trigger,
        )

    return ReviewResponse(
        ok=True,
        next_review_at=card.next_review_at,
        consecutive_failures=card.consecutive_failures,
    )
