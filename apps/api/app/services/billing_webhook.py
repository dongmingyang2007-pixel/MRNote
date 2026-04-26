"""S6 Billing — webhook event handlers.

Wave 1 A4 hardenings (see tmp/bug_audit/03_billing_abuse.md):

* HIGH-4  — one-time payments extend the existing manual Subscription
            instead of stacking a fresh row each time the user pays.
* HIGH-5  — when Stripe confirms a trialing subscription we stamp
            Subscription.trial_used_at so the checkout endpoint can
            refuse to grant the 14-day trial a second time.
* MEDIUM-11 — invoice.paid fetches the authoritative period_end off
            stripe.Subscription.retrieve(), not the possibly-narrower
            `period_end` on the invoice itself.
* LOW-18  — charge.refunded now cancels the associated manual
            Subscription and refreshes entitlements.
* LOW-20  — subscription.updated re-reads the Stripe items array so
            seat changes made in the portal propagate to Subscription.seats.
* LOW-21  — checkout.session.completed cross-validates the
            client-supplied mrai_plan metadata against the price on the
            Stripe subscription; mismatches are rejected.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

import stripe
from sqlalchemy.orm import Session

from app.core.entitlements import refresh_workspace_entitlements
from app.models import CustomerAccount, Subscription, SubscriptionItem, Workspace
from app.services import stripe_client

logger = logging.getLogger(__name__)


_TRIALING_STATUS = "trialing"
_STRIPE_SUBSCRIPTION_STATUSES = {
    "active",
    "past_due",
    "canceled",
    "trialing",
    "manual",
    "incomplete",
    "incomplete_expired",
    "unpaid",
    "paused",
}


def _ts(seconds: int | None) -> datetime | None:
    if seconds is None:
        return None
    return datetime.fromtimestamp(int(seconds), tz=timezone.utc)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _set_workspace_plan(db: Session, *, workspace_id: str, plan: str) -> None:
    ws = db.get(Workspace, workspace_id)
    if ws is not None:
        ws.plan = plan
        db.add(ws)


def _coerce_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _find_active_one_time_sub(
    db: Session, *, workspace_id: str,
) -> Subscription | None:
    now = _now_utc()
    candidates = (
        db.query(Subscription)
        .filter(Subscription.workspace_id == workspace_id)
        .filter(Subscription.provider == "stripe_one_time")
        .filter(Subscription.status == "manual")
        .all()
    )
    for sub in candidates:
        end = _coerce_aware(sub.current_period_end)
        if end is not None and end > now:
            return sub
    return None


def _replace_subscription_items(
    db: Session, *, subscription_row: Subscription, details: dict[str, Any],
) -> None:
    """Replace existing SubscriptionItem rows with the Stripe snapshot.

    Also updates ``subscription_row.seats`` to the summed quantity so
    Portal-side seat edits reflect in entitlement calculations (LOW-20).
    """
    items = (details.get("items") or {}).get("data") or []
    # Drop existing items so we don't double-insert on updates.
    db.query(SubscriptionItem).filter(
        SubscriptionItem.subscription_id == subscription_row.id,
    ).delete(synchronize_session=False)
    total_seats = 0
    for item in items:
        qty = int(item.get("quantity", 1))
        total_seats += qty
        db.add(SubscriptionItem(
            subscription_id=subscription_row.id,
            stripe_subscription_item_id=item.get("id"),
            stripe_price_id=(item.get("price") or {}).get("id", ""),
            quantity=qty,
        ))
    if total_seats > 0:
        subscription_row.seats = total_seats
        db.add(subscription_row)


def _expected_price_for_plan(plan: str, cycle: str) -> str | None:
    try:
        return stripe_client.stripe_price_id_for(plan, cycle)
    except Exception:  # noqa: BLE001
        return None


def _metadata_matches_subscription_price(
    *, plan: str, cycle: str, details: dict[str, Any] | None,
) -> bool:
    """LOW-21 cross-check: metadata-declared plan/cycle must match the
    Stripe subscription's first line-item price. If we can't verify we
    err on the side of accepting (Stripe is the source of truth for the
    charge and signature is already validated); we only reject on an
    actual observed mismatch.
    """
    if not details:
        return True
    items = (details.get("items") or {}).get("data") or []
    if not items:
        return True
    first_price = (items[0].get("price") or {}).get("id")
    if not first_price:
        return True
    expected = _expected_price_for_plan(plan, cycle)
    if not expected:
        return True
    return first_price == expected


def _customer_matches_workspace(
    db: Session,
    *,
    workspace_id: str,
    stripe_customer_id: str | None,
) -> bool:
    if not stripe_customer_id:
        return False
    return (
        db.query(CustomerAccount)
        .filter(
            CustomerAccount.workspace_id == workspace_id,
            CustomerAccount.stripe_customer_id == stripe_customer_id,
        )
        .first()
        is not None
    )


def _normalize_subscription_status(status: object) -> str:
    normalized = str(status or "incomplete").strip()
    if normalized in _STRIPE_SUBSCRIPTION_STATUSES:
        return normalized
    logger.warning("Unknown Stripe subscription status %s; mapping to incomplete", normalized)
    return "incomplete"


def _apply_one_time_payment(
    db: Session,
    *,
    workspace_id: str,
    plan: str,
    cycle: str,
) -> None:
    days = 365 if cycle == "yearly" else 30
    existing = _find_active_one_time_sub(db, workspace_id=workspace_id)
    if existing is not None:
        current_end = _coerce_aware(existing.current_period_end) or _now_utc()
        existing.current_period_end = current_end + timedelta(days=days)
        existing.plan = plan
        existing.billing_cycle = cycle
        db.add(existing)
        db.commit()
    else:
        sub = Subscription(
            workspace_id=workspace_id,
            stripe_subscription_id=None,
            plan=plan,
            billing_cycle=cycle,
            status="manual",
            provider="stripe_one_time",
            current_period_start=_now_utc(),
            current_period_end=_now_utc() + timedelta(days=days),
        )
        db.add(sub)
        db.commit()

    _set_workspace_plan(db, workspace_id=workspace_id, plan=plan)
    db.commit()
    refresh_workspace_entitlements(db, workspace_id=workspace_id)


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
    if not _customer_matches_workspace(
        db,
        workspace_id=workspace_id,
        stripe_customer_id=payload_obj.get("customer"),
    ):
        logger.warning("checkout.session.completed customer/workspace mismatch")
        return

    if payload_obj.get("mode") == "subscription":
        sub_id = payload_obj.get("subscription")
        details = stripe.Subscription.retrieve(sub_id) if sub_id else None

        if not _metadata_matches_subscription_price(
            plan=plan, cycle=cycle, details=details,
        ):
            logger.warning(
                "checkout.session.completed metadata mismatch: "
                "plan=%s cycle=%s stripe_sub=%s — refusing to apply",
                plan, cycle, sub_id,
            )
            return

        period_start = _ts(details["current_period_start"]) if details else None
        period_end = _ts(details["current_period_end"]) if details else None
        cancel_flag = bool(details.get("cancel_at_period_end")) if details else False
        status = _normalize_subscription_status(details.get("status") if details else None)
        sub = (
            db.query(Subscription)
            .filter(Subscription.stripe_subscription_id == sub_id)
            .first()
        )
        if sub is None:
            sub = (
                db.query(Subscription)
                .filter(
                    Subscription.workspace_id == workspace_id,
                    Subscription.stripe_subscription_id.is_(None),
                    Subscription.provider == "stripe_recurring",
                    Subscription.status == "incomplete",
                    Subscription.plan == plan,
                    Subscription.billing_cycle == cycle,
                )
                .order_by(Subscription.created_at.desc())
                .first()
            )
        if sub is None:
            sub = Subscription(
                workspace_id=workspace_id,
                stripe_subscription_id=sub_id,
                plan=plan,
                billing_cycle=cycle,
                status=status,
                provider="stripe_recurring",
                current_period_start=period_start,
                current_period_end=period_end,
                cancel_at_period_end=cancel_flag,
            )
        else:
            sub.workspace_id = workspace_id
            sub.stripe_subscription_id = sub_id
            sub.plan = plan
            sub.billing_cycle = cycle
            sub.status = status
            sub.provider = "stripe_recurring"
            sub.current_period_start = period_start
            sub.current_period_end = period_end
            sub.cancel_at_period_end = cancel_flag
        # HIGH-5: mark trial_used_at when the subscription starts in
        # trialing state so a subsequent checkout can't grant another
        # 14-day trial on the same workspace.
        if status == _TRIALING_STATUS:
            sub.trial_used_at = sub.trial_used_at or _now_utc()
        db.add(sub); db.commit(); db.refresh(sub)
        if details:
            _replace_subscription_items(
                db, subscription_row=sub, details=details,
            )
            db.commit()
    else:
        if payload_obj.get("payment_status") != "paid":
            logger.info(
                "checkout.session.completed one-time payment pending for workspace %s",
                workspace_id,
            )
            return
        _apply_one_time_payment(db, workspace_id=workspace_id, plan=plan, cycle=cycle)
        return

    _set_workspace_plan(db, workspace_id=workspace_id, plan=plan)
    db.commit()
    refresh_workspace_entitlements(db, workspace_id=workspace_id)


def handle_checkout_session_async_payment_succeeded(
    db: Session, payload_obj: dict[str, Any],
) -> None:
    metadata = payload_obj.get("metadata") or {}
    workspace_id = metadata.get("mrai_workspace_id")
    plan = metadata.get("mrai_plan")
    cycle = metadata.get("mrai_cycle")
    if not (workspace_id and plan and cycle):
        logger.warning("checkout.session.async_payment_succeeded missing mrai metadata")
        return
    if not _customer_matches_workspace(
        db,
        workspace_id=workspace_id,
        stripe_customer_id=payload_obj.get("customer"),
    ):
        logger.warning("checkout.session.async_payment_succeeded customer/workspace mismatch")
        return
    if payload_obj.get("mode") != "payment" or payload_obj.get("payment_status") != "paid":
        return
    _apply_one_time_payment(db, workspace_id=workspace_id, plan=plan, cycle=cycle)


def handle_checkout_session_async_payment_failed(
    db: Session, payload_obj: dict[str, Any],
) -> None:
    metadata = payload_obj.get("metadata") or {}
    workspace_id = metadata.get("mrai_workspace_id")
    if workspace_id:
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
    new_status = _normalize_subscription_status(payload_obj.get("status", sub.status))
    sub.status = new_status
    sub.cancel_at_period_end = bool(payload_obj.get("cancel_at_period_end"))
    cps = payload_obj.get("current_period_start")
    cpe = payload_obj.get("current_period_end")
    if cps is not None:
        sub.current_period_start = _ts(cps)
    if cpe is not None:
        sub.current_period_end = _ts(cpe)

    # HIGH-5: persist trial_used_at the first time we see trialing status.
    if new_status == _TRIALING_STATUS and sub.trial_used_at is None:
        sub.trial_used_at = _now_utc()

    # LOW-20: re-sync seats from Stripe items so Portal-side changes land.
    items_payload = payload_obj.get("items")
    if items_payload:
        _replace_subscription_items(
            db, subscription_row=sub, details={"items": items_payload},
        )

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

    # MEDIUM-11: Read the authoritative current_period_end off the
    # Subscription object rather than trusting the invoice's period_end
    # (the invoice covers the billing period, not the subscription term).
    period_end: datetime | None = None
    try:
        details = stripe.Subscription.retrieve(sub_id)
        if details is not None:
            period_end = _ts(details.get("current_period_end"))
    except Exception:  # noqa: BLE001
        logger.exception(
            "invoice.paid: stripe.Subscription.retrieve failed for %s", sub_id,
        )
    if period_end is None:
        # Last-resort fallback: the old behaviour.
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


def handle_charge_refunded(
    db: Session, payload_obj: dict[str, Any],
) -> None:
    """LOW-18: a refunded one-time charge should cancel the associated
    manual subscription and refresh entitlements so the user loses the
    paid plan immediately. For recurring subs Stripe emits a dedicated
    customer.subscription.updated/deleted event; those paths already
    clear the row and do not need this handler.
    """
    metadata = payload_obj.get("metadata") or {}
    workspace_id = metadata.get("mrai_workspace_id")
    # Charges don't carry our metadata reliably (the checkout session
    # does, but by the time of refund it's the PaymentIntent that lands
    # here). Fall back to customer lookup.
    if not workspace_id:
        customer_id = payload_obj.get("customer")
        if not customer_id:
            return
        from app.models import CustomerAccount
        ca = (
            db.query(CustomerAccount)
            .filter(CustomerAccount.stripe_customer_id == customer_id)
            .first()
        )
        if ca is None:
            return
        workspace_id = ca.workspace_id

    # Pick the most-recent manual sub for this workspace.
    sub = (
        db.query(Subscription)
        .filter(Subscription.workspace_id == workspace_id)
        .filter(Subscription.provider == "stripe_one_time")
        .filter(Subscription.status == "manual")
        .order_by(Subscription.created_at.desc())
        .first()
    )
    if sub is None:
        return
    sub.status = "canceled"
    db.add(sub)
    _set_workspace_plan(db, workspace_id=workspace_id, plan="free")
    db.commit()
    refresh_workspace_entitlements(db, workspace_id=workspace_id)
