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


class NotebookHomeNotebook(BaseModel):
    id: str
    title: str
    description: str
    notebook_type: str
    updated_at: datetime
    page_count: int = 0
    study_asset_count: int = 0
    ai_action_count: int = 0


class NotebookHomePage(BaseModel):
    id: str
    notebook_id: str
    notebook_title: str
    title: str
    updated_at: datetime
    last_edited_at: datetime | None = None
    plain_text_preview: str = ""


class NotebookHomeStudyAsset(BaseModel):
    id: str
    notebook_id: str
    notebook_title: str
    title: str
    status: str
    asset_type: str
    total_chunks: int
    created_at: datetime


class NotebookHomeAIAction(BaseModel):
    id: str
    notebook_id: str | None = None
    page_id: str | None = None
    notebook_title: str | None = None
    page_title: str | None = None
    action_type: str
    output_summary: str
    created_at: datetime


class NotebookHomeFocusItem(BaseModel):
    notebook_id: str
    notebook_title: str
    page_count: int = 0
    study_asset_count: int = 0
    ai_action_count: int = 0


class NotebookHomeAISummary(BaseModel):
    actions_today: int
    top_action_types: list[dict[str, int | str]] = Field(default_factory=list)
    recent_actions: list[NotebookHomeAIAction] = Field(default_factory=list)


class NotebookHomeOut(BaseModel):
    notebooks: list[NotebookHomeNotebook]
    recent_pages: list[NotebookHomePage]
    continue_writing: list[NotebookHomePage]
    recent_study_assets: list[NotebookHomeStudyAsset]
    ai_today: NotebookHomeAISummary
    work_themes: list[NotebookHomeFocusItem]
    long_term_focus: list[NotebookHomeFocusItem]
    recommended_pages: list[NotebookHomePage]


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
