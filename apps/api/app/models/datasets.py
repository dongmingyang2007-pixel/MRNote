from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base_class import Base, TimestampMixin, UUIDPrimaryKeyMixin, UpdatedAtMixin


class Dataset(Base, UUIDPrimaryKeyMixin, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "datasets"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(Text, default="images", nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cleanup_status: Mapped[str] = mapped_column(Text, default="none", nullable=False)


class DataItem(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "data_items"

    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"))
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    media_type: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(nullable=False, default=0)
    sha256: Mapped[str | None] = mapped_column(Text, nullable=True)
    width: Mapped[int | None] = mapped_column(nullable=True)
    height: Mapped[int | None] = mapped_column(nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(nullable=True)
    meta_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DocumentVersion(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("data_item_id", "version", name="uq_document_versions_item_version"),
    )

    data_item_id: Mapped[str] = mapped_column(
        ForeignKey("data_items.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(nullable=False)  # monotonic per data_item
    object_key: Mapped[str] = mapped_column(Text, nullable=False)  # snapshot S3 key
    size_bytes: Mapped[int] = mapped_column(nullable=False, default=0)
    sha256: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_type: Mapped[str] = mapped_column(Text, nullable=False)
    saved_via: Mapped[str] = mapped_column(Text, default="onlyoffice", nullable=False)
    saved_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class Annotation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "annotations"

    data_item_id: Mapped[str] = mapped_column(ForeignKey("data_items.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class DatasetVersion(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "dataset_versions"
    __table_args__ = (
        UniqueConstraint("dataset_id", "version", name="uq_dataset_versions_dataset_version"),
    )

    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(nullable=False)
    commit_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    item_count: Mapped[int] = mapped_column(default=0, nullable=False)
    frozen_item_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


Index("idx_data_items_dataset", DataItem.dataset_id)

Index("idx_data_items_sha", DataItem.sha256)

Index("idx_annotations_item", Annotation.data_item_id)

Index("idx_dsv_dataset", DatasetVersion.dataset_id)

Index("idx_dv_item_version", DocumentVersion.data_item_id, DocumentVersion.version)


__all__ = [
    "Dataset",
    "DataItem",
    "Annotation",
    "DatasetVersion",
    "DocumentVersion",
]
