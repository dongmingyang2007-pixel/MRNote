"""StudyDeck + StudyCard CRUD and review endpoints (S4)."""

from __future__ import annotations

from datetime import datetime, timezone
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
