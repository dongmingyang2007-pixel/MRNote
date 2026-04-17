"""S6 Billing — webhook event handlers."""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

import stripe
from sqlalchemy.orm import Session

from app.core.entitlements import refresh_workspace_entitlements
from app.models import Subscription, SubscriptionItem, Workspace

logger = logging.getLogger(__name__)


def _ts(seconds: int | None) -> datetime | None:
    if seconds is None:
        return None
    return datetime.fromtimestamp(int(seconds), tz=timezone.utc)


def _set_workspace_plan(db: Session, *, workspace_id: str, plan: str) -> None:
    ws = db.get(Workspace, workspace_id)
    if ws is not None:
        ws.plan = plan
        db.add(ws)


def handle_checkout_session_completed(
    db: Session, payload_obj: dict[str, Any],
) -> None:
    metadata = payload_obj.get("metadata") or {}
    workspace_id = metadata.get("mrai_workspace_id")
    plan = metadata.get("mrai_plan")
    cycle = metadata.get("mrai_cycle")
    if not (workspace_id and plan and cycle):
        logger.warning("checkout.session.completed missing mrai metadata")
        return

    if payload_obj.get("mode") == "subscription":
        sub_id = payload_obj.get("subscription")
        details = stripe.Subscription.retrieve(sub_id) if sub_id else None
        period_start = _ts(details["current_period_start"]) if details else None
        period_end = _ts(details["current_period_end"]) if details else None
        cancel_flag = bool(details.get("cancel_at_period_end")) if details else False
        sub = Subscription(
            workspace_id=workspace_id,
            stripe_subscription_id=sub_id,
            plan=plan, billing_cycle=cycle,
            status="active", provider="stripe_recurring",
            current_period_start=period_start,
            current_period_end=period_end,
            cancel_at_period_end=cancel_flag,
        )
        db.add(sub); db.commit(); db.refresh(sub)
        if details:
            for item in (details.get("items") or {}).get("data") or []:
                db.add(SubscriptionItem(
                    subscription_id=sub.id,
                    stripe_subscription_item_id=item.get("id"),
                    stripe_price_id=(item.get("price") or {}).get("id", ""),
                    quantity=int(item.get("quantity", 1)),
                ))
            db.commit()
    else:
        days = 365 if cycle == "yearly" else 30
        sub = Subscription(
            workspace_id=workspace_id,
            stripe_subscription_id=None,
            plan=plan, billing_cycle=cycle,
            status="manual", provider="stripe_one_time",
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=days),
        )
        db.add(sub); db.commit()

    _set_workspace_plan(db, workspace_id=workspace_id, plan=plan)
    db.commit()
    refresh_workspace_entitlements(db, workspace_id=workspace_id)


def handle_subscription_updated(
    db: Session, payload_obj: dict[str, Any],
) -> None:
    sub_id = payload_obj.get("id")
    sub = (
        db.query(Subscription)
        .filter(Subscription.stripe_subscription_id == sub_id)
        .first()
    )
    if sub is None:
        return
    sub.status = payload_obj.get("status", sub.status)
    sub.cancel_at_period_end = bool(payload_obj.get("cancel_at_period_end"))
    cps = payload_obj.get("current_period_start")
    cpe = payload_obj.get("current_period_end")
    if cps is not None:
        sub.current_period_start = _ts(cps)
    if cpe is not None:
        sub.current_period_end = _ts(cpe)
    db.add(sub); db.commit()
    refresh_workspace_entitlements(db, workspace_id=sub.workspace_id)


def handle_subscription_deleted(
    db: Session, payload_obj: dict[str, Any],
) -> None:
    sub_id = payload_obj.get("id")
    sub = (
        db.query(Subscription)
        .filter(Subscription.stripe_subscription_id == sub_id)
        .first()
    )
    if sub is None:
        return
    sub.status = "canceled"
    db.add(sub); db.commit()
    _set_workspace_plan(db, workspace_id=sub.workspace_id, plan="free")
    db.commit()
    refresh_workspace_entitlements(db, workspace_id=sub.workspace_id)


def handle_invoice_paid(
    db: Session, payload_obj: dict[str, Any],
) -> None:
    sub_id = payload_obj.get("subscription")
    if not sub_id:
        return
    sub = (
        db.query(Subscription)
        .filter(Subscription.stripe_subscription_id == sub_id)
        .first()
    )
    if sub is None:
        return
    period_end = _ts(payload_obj.get("period_end"))
    if period_end is not None:
        sub.current_period_end = period_end
        db.add(sub); db.commit()


def handle_invoice_payment_failed(
    db: Session, payload_obj: dict[str, Any],
) -> None:
    sub_id = payload_obj.get("subscription")
    if not sub_id:
        return
    sub = (
        db.query(Subscription)
        .filter(Subscription.stripe_subscription_id == sub_id)
        .first()
    )
    if sub is None:
        return
    sub.status = "past_due"
    db.add(sub); db.commit()
