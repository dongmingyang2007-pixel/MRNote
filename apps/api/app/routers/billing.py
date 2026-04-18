"""S6 Billing API: checkout / checkout-onetime / portal / me / plans / webhook."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import (
    get_current_user, get_current_workspace_id, get_db_session,
    require_csrf_protection,
)
from app.core.errors import ApiError
from app.models import CustomerAccount, User
from app.schemas.billing import (
    CheckoutOnetimeRequest, CheckoutRequest, CheckoutResponse, PortalResponse,
)
from app.services import stripe_client

router = APIRouter(prefix="/api/v1/billing", tags=["billing"])


def _ensure_customer(
    db: Session, *, workspace_id: str, user: User,
) -> CustomerAccount:
    ca = db.query(CustomerAccount).filter_by(workspace_id=workspace_id).first()
    if ca is not None:
        return ca
    stripe_customer_id = stripe_client.get_or_create_customer(
        workspace_id=workspace_id,
        email=getattr(user, "email", None),
    )
    ca = CustomerAccount(
        workspace_id=workspace_id,
        stripe_customer_id=stripe_customer_id,
        email=getattr(user, "email", None),
    )
    db.add(ca); db.commit(); db.refresh(ca)
    return ca


@router.post("/checkout", response_model=CheckoutResponse)
def post_checkout(
    payload: CheckoutRequest,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _: None = Depends(require_csrf_protection),
) -> CheckoutResponse:
    if payload.plan != "team" and payload.seats != 1:
        raise ApiError("invalid_input",
                       "seats only valid for team plan", status_code=400)
    ca = _ensure_customer(db, workspace_id=workspace_id, user=current_user)
    price_id = stripe_client.stripe_price_id_for(payload.plan, payload.cycle)
    # Pro / Power get a 14-day trial; Team is treated as enterprise-like
    # and starts paid immediately.
    trial_days = 14 if payload.plan in ("pro", "power") else None
    url = stripe_client.create_checkout_session_subscription(
        stripe_customer_id=ca.stripe_customer_id,
        price_id=price_id,
        quantity=payload.seats,
        success_url=settings.stripe_checkout_success_url,
        cancel_url=settings.stripe_checkout_cancel_url,
        metadata={
            "mrai_workspace_id": workspace_id,
            "mrai_plan": payload.plan,
            "mrai_cycle": payload.cycle,
        },
        trial_period_days=trial_days,
    )
    return CheckoutResponse(checkout_url=url)


@router.post("/checkout-onetime", response_model=CheckoutResponse)
def post_checkout_onetime(
    payload: CheckoutOnetimeRequest,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _: None = Depends(require_csrf_protection),
) -> CheckoutResponse:
    if payload.plan != "team" and payload.seats != 1:
        raise ApiError("invalid_input",
                       "seats only valid for team plan", status_code=400)
    ca = _ensure_customer(db, workspace_id=workspace_id, user=current_user)
    amount_cents = stripe_client.one_time_unit_amount_cents(
        payload.plan, payload.cycle,
    )
    product_id = stripe_client.stripe_product_id_for(payload.plan)
    url = stripe_client.create_checkout_session_one_time(
        stripe_customer_id=ca.stripe_customer_id,
        product_id=product_id,
        unit_amount_cents=amount_cents,
        quantity=payload.seats,
        payment_method=payload.payment_method,
        success_url=settings.stripe_checkout_success_url,
        cancel_url=settings.stripe_checkout_cancel_url,
        metadata={
            "mrai_workspace_id": workspace_id,
            "mrai_plan": payload.plan,
            "mrai_cycle": payload.cycle,
            "mrai_one_time": "1",
        },
    )
    return CheckoutResponse(checkout_url=url)


@router.post("/portal", response_model=PortalResponse)
def post_portal(
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),  # noqa: ARG001
    workspace_id: str = Depends(get_current_workspace_id),
    _: None = Depends(require_csrf_protection),
) -> PortalResponse:
    ca = db.query(CustomerAccount).filter_by(workspace_id=workspace_id).first()
    if ca is None:
        raise ApiError("not_found",
                       "No Stripe customer for this workspace", status_code=404)
    url = stripe_client.create_billing_portal_session(
        stripe_customer_id=ca.stripe_customer_id,
        return_url=settings.stripe_billing_portal_return_url,
    )
    return PortalResponse(portal_url=url)


from datetime import datetime, timezone

from sqlalchemy import func

from app.core.entitlements import resolve_entitlement
from app.models import (
    AIUsageEvent, Notebook, NotebookPage, StudyAsset, Subscription,
)
from app.schemas.billing import BillingMeResponse, PlansResponse
from app.services.plan_entitlements import (
    ENTITLEMENT_KEYS, PLAN_ENTITLEMENTS,
)


def _month_start_utc() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


@router.get("/me", response_model=BillingMeResponse)
def get_me(
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),  # noqa: ARG001
    workspace_id: str = Depends(get_current_workspace_id),
) -> BillingMeResponse:
    sub = (
        db.query(Subscription)
        .filter(Subscription.workspace_id == workspace_id)
        .filter(Subscription.status.in_(
            ("active", "past_due", "trialing", "manual"),
        ))
        .order_by(Subscription.created_at.desc())
        .first()
    )
    plan = sub.plan if sub else "free"
    ents = {key: resolve_entitlement(db, workspace_id=workspace_id, key=key)
            for key in ENTITLEMENT_KEYS}

    month_start = _month_start_utc()
    ai_actions_count = (
        db.query(func.count(AIUsageEvent.id))
        .filter(AIUsageEvent.workspace_id == workspace_id)
        .filter(AIUsageEvent.created_at >= month_start)
        .scalar()
    ) or 0
    notebooks_count = (
        db.query(func.count(Notebook.id))
        .filter(Notebook.workspace_id == workspace_id)
        .scalar()
    ) or 0
    pages_count = (
        db.query(func.count(NotebookPage.id))
        .join(Notebook, Notebook.id == NotebookPage.notebook_id)
        .filter(Notebook.workspace_id == workspace_id)
        .scalar()
    ) or 0
    study_assets_count = (
        db.query(func.count(StudyAsset.id))
        .join(Notebook, Notebook.id == StudyAsset.notebook_id)
        .filter(Notebook.workspace_id == workspace_id)
        .scalar()
    ) or 0

    return BillingMeResponse(
        plan=plan,
        status=sub.status if sub else "active",
        billing_cycle=sub.billing_cycle if sub else "none",
        current_period_end=sub.current_period_end if sub else None,
        seats=sub.seats if sub else 1,
        cancel_at_period_end=sub.cancel_at_period_end if sub else False,
        provider=sub.provider if sub else "free",
        entitlements=ents,
        usage_this_month={
            "ai.actions": int(ai_actions_count),
            "notebooks": int(notebooks_count),
            "pages": int(pages_count),
            "study_assets": int(study_assets_count),
        },
    )


@router.get("/plans", response_model=PlansResponse)
def get_plans() -> PlansResponse:
    plans = []
    for plan_id, ents in PLAN_ENTITLEMENTS.items():
        if plan_id == "free":
            prices = {"monthly": None, "yearly": None}
        else:
            prices = {
                "monthly": stripe_client.stripe_price_id_for(plan_id, "monthly"),
                "yearly": stripe_client.stripe_price_id_for(plan_id, "yearly"),
            }
        plans.append({
            "id": plan_id,
            "stripe_prices": prices,
            "entitlements": ents,
        })
    return PlansResponse(plans=plans)


from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.models import BillingEvent
from app.services import billing_webhook


@router.post("/webhook")
async def post_webhook(
    request: Request,
    db: Session = Depends(get_db_session),
) -> JSONResponse:
    payload_bytes = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    try:
        event = stripe_client.verify_webhook(payload_bytes, sig_header)
    except Exception:
        return JSONResponse(status_code=400, content={"error": "invalid_signature"})

    event_id = event.get("id", "")
    event_type = event.get("type", "")

    try:
        db.add(BillingEvent(
            stripe_event_id=event_id,
            event_type=event_type,
            payload_json=event,
        ))
        db.commit()
    except IntegrityError:
        db.rollback()
        return JSONResponse(status_code=200, content={"ok": True, "skipped": True})

    payload_obj = (event.get("data") or {}).get("object") or {}

    try:
        if event_type == "checkout.session.completed":
            billing_webhook.handle_checkout_session_completed(db, payload_obj)
        elif event_type == "customer.subscription.updated":
            billing_webhook.handle_subscription_updated(db, payload_obj)
        elif event_type == "customer.subscription.deleted":
            billing_webhook.handle_subscription_deleted(db, payload_obj)
        elif event_type == "invoice.paid":
            billing_webhook.handle_invoice_paid(db, payload_obj)
        elif event_type == "invoice.payment_failed":
            billing_webhook.handle_invoice_payment_failed(db, payload_obj)
        be = db.query(BillingEvent).filter_by(stripe_event_id=event_id).first()
        if be is not None:
            be.processed_at = datetime.now(timezone.utc)
            db.add(be); db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        be = db.query(BillingEvent).filter_by(stripe_event_id=event_id).first()
        if be is not None:
            be.error = str(exc)[:500]
            db.add(be); db.commit()

    return JSONResponse(status_code=200, content={"ok": True})
