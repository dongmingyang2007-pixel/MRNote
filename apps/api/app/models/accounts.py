from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    text as sql_text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base_class import Base, TimestampMixin, UUIDPrimaryKeyMixin


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    # Homepage persona selector — spec §1.7.
    # Nullable: account-level value is absent until the user first picks one
    # in Hero pill, registration step 2, or Settings → Profile. Valid values
    # are enforced by a CHECK constraint in Postgres (migration 202604240002);
    # SQLite skips the CHECK since it silently ignores constraint violations
    # anyway, and the Pydantic MePatch model gates the enum on the write path.
    persona: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Per-user IANA timezone (e.g. "Asia/Shanghai"). Null means the scheduler
    # falls back to UTC. Populated by PATCH /api/v1/auth/me; validated at the
    # write path via ``zoneinfo.ZoneInfo``.
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Toggle for digest emails (daily digest + weekly reflection). Default TRUE
    # so users opt-out rather than opt-in; per-user flip via PATCH /auth/me or
    # PATCH /digest/preferences.
    digest_email_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default=sql_text("true"),
        nullable=False,
    )


class Workspace(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "workspaces"

    name: Mapped[str] = mapped_column(Text, nullable=False)
    plan: Mapped[str] = mapped_column(Text, default="free", nullable=False)


class Membership(Base, TimestampMixin):
    __tablename__ = "memberships"

    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(Text, default="owner", nullable=False)


class OAuthIdentity(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """External identity provider link (Google / Apple / GitHub / …).

    One row per (provider, provider_id) — keyed on the provider's stable user ID
    (Google calls it `sub`), so email changes at the provider don't orphan the
    link. `provider_email` is a display snapshot, never used for lookup.
    """

    __tablename__ = "oauth_identities"
    __table_args__ = (
        UniqueConstraint("provider", "provider_id", name="uq_oauth_provider_id"),
        UniqueConstraint("provider", "user_id", name="uq_oauth_provider_user"),
    )

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    provider_id: Mapped[str] = mapped_column(Text, nullable=False)
    provider_email: Mapped[str | None] = mapped_column(Text, nullable=True)
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class ApiKey(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "api_keys"

    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    key_hash: Mapped[str] = mapped_column(Text, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    workspace_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True, index=True
    )
    actor_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(Text, nullable=False)
    target_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    meta_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


__all__ = [
    "User",
    "Workspace",
    "Membership",
    "OAuthIdentity",
    "ApiKey",
    "AuditLog",
]
