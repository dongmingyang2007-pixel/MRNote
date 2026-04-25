from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text as sql_text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base_class import Base, TimestampMixin, UUIDPrimaryKeyMixin, UpdatedAtMixin


class StudyAsset(Base, UUIDPrimaryKeyMixin, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "study_assets"

    notebook_id: Mapped[str] = mapped_column(
        ForeignKey("notebooks.id", ondelete="CASCADE"), index=True
    )
    data_item_id: Mapped[str | None] = mapped_column(
        ForeignKey("data_items.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(Text, default="", nullable=False)
    asset_type: Mapped[str] = mapped_column(String(20), default="pdf", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    total_chunks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # Spec §5.1.6 — StudyAsset metadata columns. DB columns were added in
    # migration 202604220005; these Mapped[] declarations bind them to the
    # ORM so we can read/write from Python instead of reaching for raw SQL.
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    author: Mapped[str | None] = mapped_column(String(200), nullable=True)
    page_id: Mapped[str | None] = mapped_column(
        ForeignKey("notebook_pages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))


class StudyChunk(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "study_chunks"

    asset_id: Mapped[str] = mapped_column(
        ForeignKey("study_assets.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    heading: Mapped[str] = mapped_column(Text, default="", nullable=False)
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # Spec §5.1.7 — chunk-level summary + keyword surface so retrieval can
    # rank by topical keywords and UIs can preview chunks without scanning
    # the full body. DB columns added by migration 202604230002.
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False, server_default="")
    keywords_json: Mapped[list[Any]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
        server_default=sql_text("'[]'"),
    )
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class StudyDeck(Base, UUIDPrimaryKeyMixin, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "study_decks"

    notebook_id: Mapped[str] = mapped_column(
        ForeignKey("notebooks.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    card_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class StudyCard(Base, UUIDPrimaryKeyMixin, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "study_cards"

    deck_id: Mapped[str] = mapped_column(
        ForeignKey("study_decks.id", ondelete="CASCADE"), index=True
    )
    front: Mapped[str] = mapped_column(Text, nullable=False)
    back: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    difficulty: Mapped[float] = mapped_column(Float, default=5.0, nullable=False)
    stability: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    last_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_review_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    review_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    lapse_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    confusion_memory_written_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


Index(
    "ix_study_cards_deck_due",
    StudyCard.deck_id,
    StudyCard.next_review_at.asc(),
)

Index(
    "ix_study_cards_deck_created",
    StudyCard.deck_id,
    StudyCard.created_at.desc(),
)


__all__ = [
    "StudyAsset",
    "StudyChunk",
    "StudyDeck",
    "StudyCard",
]
