from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class DeckCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str = ""


class DeckPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    archived: bool | None = None


class DeckOut(BaseModel):
    id: str
    notebook_id: str
    name: str
    description: str
    card_count: int
    created_by: str
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PaginatedDecks(BaseModel):
    items: list[DeckOut]
    total: int


class CardCreate(BaseModel):
    front: str = Field(..., min_length=1)
    back: str = Field(..., min_length=1)
    source_type: str = "manual"
    source_ref: str | None = None


class CardPatch(BaseModel):
    front: str | None = Field(default=None, min_length=1)
    back: str | None = Field(default=None, min_length=1)


class CardOut(BaseModel):
    id: str
    deck_id: str
    front: str
    back: str
    source_type: str
    source_ref: str | None
    difficulty: float
    stability: float
    last_review_at: datetime | None
    next_review_at: datetime | None
    review_count: int
    lapse_count: int
    consecutive_failures: int
    created_at: datetime
    updated_at: datetime


class ReviewRequest(BaseModel):
    rating: int = Field(..., ge=1, le=4)
    marked_confused: bool = False


class ReviewResponse(BaseModel):
    ok: bool = True
    next_review_at: datetime | None
    consecutive_failures: int
