from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base_class import Base, TimestampMixin, UUIDPrimaryKeyMixin, UpdatedAtMixin


class Notebook(Base, UUIDPrimaryKeyMixin, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "notebooks"

    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(Text, default="", nullable=False)
    slug: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    icon: Mapped[str | None] = mapped_column(String(100), nullable=True)
    cover_image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    notebook_type: Mapped[str] = mapped_column(String(20), default="personal", nullable=False)
    visibility: Mapped[str] = mapped_column(String(20), default="private", nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class NotebookPage(Base, UUIDPrimaryKeyMixin, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "notebook_pages"

    notebook_id: Mapped[str] = mapped_column(
        ForeignKey("notebooks.id", ondelete="CASCADE"), index=True
    )
    parent_page_id: Mapped[str | None] = mapped_column(
        ForeignKey("notebook_pages.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(Text, default="", nullable=False)
    slug: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    page_type: Mapped[str] = mapped_column(String(20), default="document", nullable=False)
    content_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    plain_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    summary_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    ai_keywords_json: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    ai_status_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    embedding_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)


class NotebookBlock(Base, UUIDPrimaryKeyMixin, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "notebook_blocks"

    page_id: Mapped[str] = mapped_column(
        ForeignKey("notebook_pages.id", ondelete="CASCADE"), index=True
    )
    block_type: Mapped[str] = mapped_column(String(30), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    content_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    plain_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class NotebookPageVersion(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "notebook_page_versions"
    __table_args__ = (
        UniqueConstraint("page_id", "version_no", name="uq_page_versions_page_version"),
    )

    page_id: Mapped[str] = mapped_column(
        ForeignKey("notebook_pages.id", ondelete="CASCADE"), index=True
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    snapshot_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    source: Mapped[str] = mapped_column(String(20), default="autosave", nullable=False)
    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class NotebookAttachment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "notebook_attachments"

    page_id: Mapped[str] = mapped_column(
        ForeignKey("notebook_pages.id", ondelete="CASCADE"), index=True
    )
    data_item_id: Mapped[str | None] = mapped_column(
        ForeignKey("data_items.id", ondelete="SET NULL"), nullable=True
    )
    attachment_type: Mapped[str] = mapped_column(String(20), default="other", nullable=False)
    title: Mapped[str] = mapped_column(Text, default="", nullable=False)
    meta_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class NotebookSelectionMemoryLink(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Spec §5.1 / §9.5 — bidirectional link between a page selection and a Memory.

    Populated when a memory candidate extracted from a notebook page is
    promoted (see `routers/notebooks.py :: confirm_memory_candidate`). Lets
    the UI show "this span has produced these memories" without re-scanning
    evidences, and lets memory detail show "this memory came from this page
    span".
    """

    __tablename__ = "notebook_selection_memory_links"

    page_id: Mapped[str] = mapped_column(
        ForeignKey("notebook_pages.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    block_id: Mapped[str | None] = mapped_column(
        ForeignKey("notebook_blocks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    start_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    memory_id: Mapped[str] = mapped_column(
        ForeignKey("memories.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    evidence_id: Mapped[str | None] = mapped_column(
        ForeignKey("memory_evidences.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )


__all__ = [
    "Notebook",
    "NotebookPage",
    "NotebookBlock",
    "NotebookPageVersion",
    "NotebookAttachment",
    "NotebookSelectionMemoryLink",
]
