"""Block-level schemas for the NotebookBlock CRUD API (spec §13.3).

The API surface is block-centric even though the underlying storage remains
the TipTap ProseMirror JSON on `NotebookPage.content_json`. Blocks have stable
UUIDs stored in the node's `attrs.block_id`, so the same id round-trips
across create → patch → delete → reorder.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


# Spec §5.1.3 block_type whitelist. Schema-level validation only — the DB
# column is `String(30)` without a CheckConstraint so future block kinds can
# ship without a migration.
BlockType = Literal[
    "heading",
    "paragraph",
    "bullet_list",
    "numbered_list",
    "checklist",
    "quote",
    "code",
    "latex",
    "whiteboard",
    "image",
    "file",
    "ai_output",
    "callout",
    "divider",
    "reference",
    "task",
    "flashcard",
]


class BlockCreate(BaseModel):
    block_type: BlockType
    content_json: dict[str, Any] = Field(default_factory=dict)
    sort_order: int | None = None


class BlockUpdate(BaseModel):
    content_json: dict[str, Any] | None = None
    sort_order: int | None = None
    block_type: BlockType | None = None


class BlockOut(BaseModel):
    id: str
    page_id: str
    block_type: str
    sort_order: int
    content_json: dict[str, Any] = Field(default_factory=dict)
    plain_text: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None


class BlockReorderPayload(BaseModel):
    block_ids: list[str]


# Spec §13 — page duplicate / move payload shapes
class PageDuplicatePayload(BaseModel):
    title: str | None = None  # optional override, else "<original> (copy)"


class PageMovePayload(BaseModel):
    notebook_id: str | None = None  # if omitted, page stays in its notebook
    parent_page_id: str | None = None  # explicit None is allowed → move to root
    sort_order: int | None = None


# Spec §8.1 — AI scope enum (7 values)
AIScope = Literal[
    "selection",
    "page",
    "notebook",
    "project",
    "user_memory",
    "study_asset",
    "web",
]
