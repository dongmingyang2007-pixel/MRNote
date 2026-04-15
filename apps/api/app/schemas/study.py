from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


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
    created_at: datetime
    updated_at: datetime


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
