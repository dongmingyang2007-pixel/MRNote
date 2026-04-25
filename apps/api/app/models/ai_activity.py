from __future__ import annotations

from typing import Any

from sqlalchemy import (
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base_class import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AIActionLog(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "ai_action_logs"

    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    notebook_id: Mapped[str | None] = mapped_column(
        ForeignKey("notebooks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    page_id: Mapped[str | None] = mapped_column(
        ForeignKey("notebook_pages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    block_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    action_type: Mapped[str] = mapped_column(String(60), nullable=False)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="running", nullable=False)
    model_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    input_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    output_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    output_summary: Mapped[str] = mapped_column(Text, default="", nullable=False)

    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    trace_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class AIUsageEvent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "ai_usage_events"

    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    action_log_id: Mapped[str] = mapped_column(
        ForeignKey("ai_action_logs.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    model_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    audio_seconds: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    file_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    count_source: Mapped[str] = mapped_column(String(10), default="exact", nullable=False)
    meta_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


Index(
    "ix_ai_action_logs_workspace_created",
    AIActionLog.workspace_id,
    AIActionLog.created_at.desc(),
)

Index(
    "ix_ai_action_logs_page_created",
    AIActionLog.page_id,
    AIActionLog.created_at.desc(),
)

Index(
    "ix_ai_action_logs_user_created",
    AIActionLog.user_id,
    AIActionLog.created_at.desc(),
)

Index(
    "ix_ai_usage_events_workspace_created",
    AIUsageEvent.workspace_id,
    AIUsageEvent.created_at.desc(),
)


__all__ = [
    "AIActionLog",
    "AIUsageEvent",
]
