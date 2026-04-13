from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Notebook
# ---------------------------------------------------------------------------


class NotebookCreate(BaseModel):
    title: str = ""
    description: str = ""
    notebook_type: str = "personal"
    visibility: str = "private"
    project_id: str | None = None
    icon: str | None = None


class NotebookUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    icon: str | None = None
    cover_image_url: str | None = None
    notebook_type: str | None = None
    visibility: str | None = None
    archived_at: datetime | None = None


class NotebookOut(BaseModel):
    id: str
    workspace_id: str
    project_id: str | None = None
    created_by: str
    title: str
    slug: str
    description: str
    icon: str | None = None
    cover_image_url: str | None = None
    notebook_type: str
    visibility: str
    archived_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class PaginatedNotebooks(BaseModel):
    items: list[NotebookOut]
    total: int


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------


class PageCreate(BaseModel):
    title: str = ""
    page_type: str = "document"
    parent_page_id: str | None = None
    content_json: dict[str, Any] = Field(default_factory=dict)
    sort_order: int = 0


class PageUpdate(BaseModel):
    title: str | None = None
    content_json: dict[str, Any] | None = None
    parent_page_id: str | None = None
    page_type: str | None = None
    sort_order: int | None = None
    is_pinned: bool | None = None
    is_archived: bool | None = None


class PageOut(BaseModel):
    id: str
    notebook_id: str
    parent_page_id: str | None = None
    created_by: str
    title: str
    slug: str
    page_type: str
    content_json: dict[str, Any] = Field(default_factory=dict)
    plain_text: str = ""
    summary_text: str = ""
    ai_keywords_json: list[Any] = Field(default_factory=list)
    sort_order: int = 0
    is_pinned: bool = False
    is_archived: bool = False
    last_edited_at: datetime | None = None
    source_conversation_id: str | None = None
    created_at: datetime
    updated_at: datetime


class PageListItem(BaseModel):
    id: str
    notebook_id: str
    parent_page_id: str | None = None
    title: str
    slug: str
    page_type: str
    sort_order: int = 0
    is_pinned: bool = False
    is_archived: bool = False
    last_edited_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class PaginatedPages(BaseModel):
    items: list[PageListItem]
    total: int


# ---------------------------------------------------------------------------
# Page Version
# ---------------------------------------------------------------------------


class PageVersionOut(BaseModel):
    id: str
    page_id: str
    version_no: int
    source: str
    created_by: str | None = None
    created_at: datetime
