"""Thin wrapper around the Stripe SDK so the router stays mockable
and we don't sprinkle stripe.* calls everywhere."""

from __future__ import annotations

from typing import Any

import stripe

from app.core.config import settings


def _init() -> None:
    stripe.api_key = settings.stripe_api_key


def get_or_create_customer(*, workspace_id: str, email: str | None = None) -> str:
    """Return the Stripe customer ID for this workspace, creating one if
    we don't already have a record.

    MEDIUM-12: the original implementation always called
    ``stripe.Customer.create`` which could produce orphan Customers on
    race conditions (two concurrent ``_ensure_customer`` calls both miss
    the local ``customer_accounts`` row). We now ask Stripe first:

        stripe.Customer.search(query='metadata["mrai_workspace_id"]:"X"')

    If a matching customer exists we reuse it; otherwise we create one
    with an idempotency key derived from the workspace_id so even a
    retried call lands on the same Stripe-side resource.
    """
    _init()

    # 1) Prefer Stripe-side lookup by metadata. If the search API is
    #    unavailable (older SDK / mocked tests) we silently fall back to
    #    the create path.
    try:
        search_fn = getattr(stripe.Customer, "search", None)
        if callable(search_fn):
            query = f'metadata["mrai_workspace_id"]:"{workspace_id}"'
            result = search_fn(query=query, limit=1)
            data = (result.get("data") if isinstance(result, dict)
                    else getattr(result, "data", None)) or []
            if data:
                first = data[0]
                cid = first.get("id") if isinstance(first, dict) else getattr(first, "id", None)
                if cid:
                    return cid
    except Exception:  # noqa: BLE001
        # Don't let a search failure block checkout; fall through.
        pass

    # 2) Create with an idempotency key so repeated retries collide on
    #    the same Stripe resource instead of producing orphans.
    customer = stripe.Customer.create(
        email=email or None,
        metadata={"mrai_workspace_id": workspace_id},
        idempotency_key=f"mrai-customer-create-{workspace_id}",
    )
    return customer["id"]


def create_checkout_session_subscription(
    *,
    stripe_customer_id: str,
    price_id: str,
    quantity: int,
    success_url: str,
    cancel_url: str,
    metadata: dict[str, str] | None = None,
    trial_period_days: int | None = None,
) -> str:
    """Returns the Checkout session URL for redirect.

    If ``trial_period_days`` is a positive integer, Stripe will start the
    subscription in trialing state for that many days (via
    ``subscription_data.trial_period_days``) — no charge until the trial
    ends. Pass ``None`` to create a subscription without a trial.
    """
    _init()
    session_kwargs: dict[str, Any] = {
        "mode": "subscription",
        "customer": stripe_customer_id,
        "line_items": [{"price": price_id, "quantity": quantity}],
        "success_url": success_url,
        "cancel_url": cancel_url,
        "metadata": metadata or {},
    }
    if trial_period_days is not None and trial_period_days > 0:
        session_kwargs["subscription_data"] = {
            "trial_period_days": trial_period_days,
        }
    session = stripe.checkout.Session.create(**session_kwargs)
    return session["url"]


def create_checkout_session_one_time(
    *,
    stripe_customer_id: str,
    product_id: str,
    unit_amount_cents: int,
    quantity: int,
    payment_method: str,
    success_url: str,
    cancel_url: str,
    metadata: dict[str, str] | None = None,
) -> str:
    """One-time payment (Alipay / WeChat Pay) — no recurring."""
    _init()
    session = stripe.checkout.Session.create(
        mode="payment",
        customer=stripe_customer_id,
        payment_method_types=[payment_method],
        line_items=[
            {
                "quantity": quantity,
                "price_data": {
                    "currency": "usd",
                    "product": product_id,
                    "unit_amount": unit_amount_cents,
                },
            },
        ],
        success_url=success_url,
        cancel_url=cancel_url,
        metadata=metadata or {},
    )
    return session["url"]


def create_billing_portal_session(
    *,
    stripe_customer_id: str,
    return_url: str,
) -> str:
    _init()
    session = stripe.billing_portal.Session.create(
        customer=stripe_customer_id,
        return_url=return_url,
    )
    return session["url"]


def verify_webhook(
    payload_bytes: bytes,
    sig_header: str,
) -> dict[str, Any]:
    """Verify Stripe-Signature header and return the parsed event dict."""
    _init()
    event = stripe.Webhook.construct_event(
        payload=payload_bytes,
        sig_header=sig_header,
        secret=settings.stripe_webhook_secret,
    )
    return dict(event)


# ---------------------------------------------------------------------------
# Plan ↔ Stripe ID lookup helpers
# ---------------------------------------------------------------------------


def stripe_price_id_for(plan: str, cycle: str) -> str:
    """Return the Stripe Price ID for the (plan, cycle) tuple."""
    table = {
        ("pro", "monthly"): settings.stripe_price_pro_monthly,
        ("pro", "yearly"): settings.stripe_price_pro_yearly,
        ("power", "monthly"): settings.stripe_price_power_monthly,
        ("power", "yearly"): settings.stripe_price_power_yearly,
        ("team", "monthly"): settings.stripe_price_team_monthly,
        ("team", "yearly"): settings.stripe_price_team_yearly,
    }
    pid = table.get((plan, cycle))
    if not pid:
        raise ValueError(f"unknown plan/cycle: {plan}/{cycle}")
    return pid


def stripe_product_id_for(plan: str) -> str:
    """Return the Stripe Product ID for the plan."""
    table = {
        "pro": "prod_ULxidFvV2ivzrz",
        "power": "prod_ULxiNIox1PRZaw",
        "team": "prod_ULxi7uvs66Dup5",
    }
    pid = table.get(plan)
    if not pid:
        raise ValueError(f"unknown plan: {plan}")
    return pid


def one_time_unit_amount_cents(plan: str, cycle: str) -> int:
    """Mirror the recurring price points for one-time payment fallback."""
    table = {
        ("pro", "monthly"): 1000,
        ("pro", "yearly"): 10200,
        ("power", "monthly"): 2500,
        ("power", "yearly"): 25500,
        ("team", "monthly"): 1500,
        ("team", "yearly"): 15300,
    }
    return table[(plan, cycle)]
