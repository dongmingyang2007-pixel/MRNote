from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class DigestListItem(BaseModel):
    id: str
    kind: str
    title: str
    period_start: datetime
    period_end: datetime
    status: str
    created_at: datetime


class PaginatedDigests(BaseModel):
    items: list[DigestListItem]
    next_cursor: str | None
    unread_count: int


class DigestDetail(BaseModel):
    id: str
    workspace_id: str
    project_id: str
    user_id: str
    kind: str
    title: str
    period_start: datetime
    period_end: datetime
    content_markdown: str
    content_json: dict[str, Any]
    status: str
    read_at: datetime | None
    dismissed_at: datetime | None
    model_id: str | None
    action_log_id: str | None
    created_at: datetime
    updated_at: datetime


class GenerateNowRequest(BaseModel):
    kind: str = Field(..., pattern=r"^(daily_digest|weekly_reflection|deviation_reminder|relationship_reminder)$")
    project_id: str


class AckResponse(BaseModel):
    ok: bool = True
