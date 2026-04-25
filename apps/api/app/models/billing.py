from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
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


class CustomerAccount(
    Base,
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    UpdatedAtMixin,
):
    __tablename__ = "customer_accounts"
    __table_args__ = (
        UniqueConstraint("workspace_id", name="uq_customer_accounts_workspace"),
        UniqueConstraint("stripe_customer_id", name="uq_customer_accounts_stripe_customer_id"),
    )

    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stripe_customer_id: Mapped[str] = mapped_column(String(64), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    default_payment_method_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )


class Subscription(
    Base,
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    UpdatedAtMixin,
):
    __tablename__ = "subscriptions"
    __table_args__ = (
        UniqueConstraint(
            "stripe_subscription_id",
            name="uq_subscriptions_stripe_subscription_id",
        ),
        CheckConstraint(
            "plan IN ('free','pro','power','team')",
            name="ck_subscriptions_plan",
        ),
        CheckConstraint(
            "billing_cycle IN ('monthly','yearly','none')",
            name="ck_subscriptions_billing_cycle",
        ),
        CheckConstraint(
            "status IN ('active','past_due','canceled','trialing','manual','incomplete')",
            name="ck_subscriptions_status",
        ),
        CheckConstraint(
            "provider IN ('stripe_recurring','stripe_one_time','free')",
            name="ck_subscriptions_provider",
        ),
    )

    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    plan: Mapped[str] = mapped_column(String(20), nullable=False)
    billing_cycle: Mapped[str] = mapped_column(String(10), default="monthly", nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    current_period_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    seats: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    cancel_at_period_end: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    # HIGH-5: Track when this workspace last used a trial so we don't grant
    # a fresh 14-day trial every checkout. Nullable so historical rows
    # (pre-migration) keep behaving and never-trialed workspaces stay null.
    trial_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class SubscriptionItem(
    Base,
    UUIDPrimaryKeyMixin,
    TimestampMixin,
):
    __tablename__ = "subscription_items"
    __table_args__ = (
        UniqueConstraint(
            "stripe_subscription_item_id",
            name="uq_subscription_items_stripe_id",
        ),
    )

    subscription_id: Mapped[str] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stripe_subscription_item_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    stripe_price_id: Mapped[str] = mapped_column(String(64), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class Entitlement(
    Base,
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    UpdatedAtMixin,
):
    __tablename__ = "entitlements"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "key",
            name="uq_entitlements_workspace_key",
        ),
        CheckConstraint(
            "source IN ('plan','admin_override','trial')",
            name="ck_entitlements_source",
        ),
    )

    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    key: Mapped[str] = mapped_column(String(80), nullable=False)
    value_int: Mapped[int | None] = mapped_column(Integer, nullable=True)
    value_bool: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    source: Mapped[str] = mapped_column(String(20), default="plan", nullable=False)


class BillingEvent(
    Base,
    UUIDPrimaryKeyMixin,
    TimestampMixin,
):
    __tablename__ = "billing_events"
    __table_args__ = (
        UniqueConstraint(
            "stripe_event_id",
            name="uq_billing_events_stripe_event_id",
        ),
    )

    stripe_event_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


__all__ = [
    "CustomerAccount",
    "Subscription",
    "SubscriptionItem",
    "Entitlement",
    "BillingEvent",
]
