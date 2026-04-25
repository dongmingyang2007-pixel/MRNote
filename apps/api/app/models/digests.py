from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base_class import Base, TimestampMixin, UUIDPrimaryKeyMixin, UpdatedAtMixin


class DigestDaily(Base, UUIDPrimaryKeyMixin, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "digest_daily"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "date",
            name="uq_digest_daily_user_date",
        ),
    )

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class DigestWeekly(Base, UUIDPrimaryKeyMixin, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "digest_weekly"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "iso_week",
            name="uq_digest_weekly_user_iso_week",
        ),
    )

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # "2026-W17" — 12 chars is plenty; String(12) prevents oversize values
    # from accidentally bypassing the UniqueConstraint by hash collision.
    iso_week: Mapped[str] = mapped_column(String(12), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    saved_page_id: Mapped[str | None] = mapped_column(
        ForeignKey("notebook_pages.id", ondelete="SET NULL"),
        nullable=True,
    )


Index(
    "ix_digest_daily_user_date",
    DigestDaily.user_id,
    DigestDaily.date.desc(),
)

Index(
    "ix_digest_weekly_user_iso_week",
    DigestWeekly.user_id,
    DigestWeekly.iso_week.desc(),
)


__all__ = [
    "DigestDaily",
    "DigestWeekly",
]
