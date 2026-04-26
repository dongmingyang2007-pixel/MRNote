from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Study Asset
# ---------------------------------------------------------------------------


class StudyAssetCreate(BaseModel):
    title: str
    asset_type: str = "pdf"
    data_item_id: str | None = None


class StudyAssetOut(BaseModel):
    id: str
    notebook_id: str
    data_item_id: str | None = None
    title: str
    asset_type: str
    status: str
    total_chunks: int
    metadata_json: dict[str, Any] | None = None
    tags: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class StudyAssetTagsUpdate(BaseModel):
    tags: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("tags", mode="before")
    @classmethod
    def _normalize_tags(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            return []
        cleaned: list[str] = []
        seen: set[str] = set()
        for raw in value:
            if not isinstance(raw, str):
                continue
            tag = raw.strip()
            if not tag:
                continue
            tag = tag[:32]
            if tag in seen:
                continue
            seen.add(tag)
            cleaned.append(tag)
        return cleaned


class PaginatedStudyAssets(BaseModel):
    items: list[StudyAssetOut]
    total: int


# ---------------------------------------------------------------------------
# Study Chunk
# ---------------------------------------------------------------------------


class StudyChunkOut(BaseModel):
    id: str
    asset_id: str
    chunk_index: int
    heading: str
    content: str
    page_number: int | None = None


class PaginatedStudyChunks(BaseModel):
    items: list[StudyChunkOut]
    total: int


# ---------------------------------------------------------------------------
# Study Insights
# ---------------------------------------------------------------------------


class StudyInsightsTotalsOut(BaseModel):
    assets: int
    indexed_assets: int
    generated_pages: int
    chunks: int
    decks: int
    cards: int
    new_cards: int
    due_cards: int
    weak_cards: int
    reviewed_this_week: int
    ai_actions_this_week: int
    confusions_logged: int


class StudyInsightsActionCountOut(BaseModel):
    action_type: str
    count: int


class StudyInsightsDayOut(BaseModel):
    date: str
    review_count: int
    ai_action_count: int


class StudyInsightsDeckPressureOut(BaseModel):
    deck_id: str
    deck_name: str
    total_cards: int
    due_cards: int
    last_review_at: datetime | None = None
    next_due_at: datetime | None = None


class StudyInsightsWeakCardOut(BaseModel):
    card_id: str
    deck_id: str
    deck_name: str
    front: str
    review_count: int
    lapse_count: int
    consecutive_failures: int
    next_review_at: datetime | None = None


class StudyInsightsRecentActionOut(BaseModel):
    id: str
    action_type: str
    summary: str
    created_at: datetime


class StudyInsightsOut(BaseModel):
    period_start: datetime
    period_end: datetime
    active_days: int
    totals: StudyInsightsTotalsOut
    action_counts: list[StudyInsightsActionCountOut]
    daily_activity: list[StudyInsightsDayOut]
    deck_pressure: list[StudyInsightsDeckPressureOut]
    weak_cards: list[StudyInsightsWeakCardOut]
    recent_actions: list[StudyInsightsRecentActionOut]
