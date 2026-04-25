from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base_class import Base, TimestampMixin, UUIDPrimaryKeyMixin, UpdatedAtMixin


class ProactiveDigest(
    Base,
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    UpdatedAtMixin,
):
    __tablename__ = "proactive_digests"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "kind",
            "period_start",
            "series_key",
            name="uq_proactive_digests_project_kind_period_series",
        ),
        CheckConstraint(
            "status IN ('unread','read','dismissed')",
            name="ck_proactive_digests_status",
        ),
    )

    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))

    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    series_key: Mapped[str] = mapped_column(String(64), default="", nullable=False)

    title: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    content_markdown: Mapped[str] = mapped_column(Text, default="", nullable=False)
    content_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    status: Mapped[str] = mapped_column(String(20), default="unread", nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    model_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    action_log_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


Index(
    "ix_proactive_digests_user_status_created",
    ProactiveDigest.user_id,
    ProactiveDigest.status,
    ProactiveDigest.created_at.desc(),
)

Index(
    "ix_proactive_digests_project_kind_period",
    ProactiveDigest.project_id,
    ProactiveDigest.kind,
    ProactiveDigest.period_start.desc(),
)


__all__ = [
    "ProactiveDigest",
]
