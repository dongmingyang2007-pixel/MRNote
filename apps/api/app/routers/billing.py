"""S6 Billing API: checkout / checkout-onetime / portal / me / plans / webhook."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import (
    get_current_user, get_current_workspace_id, get_current_workspace_role, get_db_session,
    is_workspace_privileged_role,
    require_csrf_protection,
)
from app.core.entitlements import resolve_entitlement
from app.core.errors import ApiError
from app.models import (
    BillingEvent,
    CustomerAccount,
    Notebook,
    NotebookPage,
    StudyAsset,
    Subscription,
    User,
)
from app.schemas.billing import (
    BillingMeResponse,
    CheckoutOnetimeRequest,
    CheckoutRequest,
    CheckoutResponse,
    PlansResponse,
    PortalResponse,
)
from app.services import billing_webhook, stripe_client
from app.services.plan_entitlements import (
    ENTITLEMENT_KEYS, PLAN_ENTITLEMENTS,
)
from app.services.quota_counters import count_ai_actions_this_month

router = APIRouter(prefix="/api/v1/billing", tags=["billing"])


def _require_billing_access(workspace_role: str) -> None:
    if is_workspace_privileged_role(workspace_role):
        return
    raise ApiError("forbidden", "Only workspace owners can manage billing", status_code=403)


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
    db.add(ca)
    db.commit()
    db.refresh(ca)
    return ca


def _require_billing_configured() -> None:
    if not settings.stripe_api_key:
        raise ApiError(
            "billing_not_configured",
            "Billing is not configured for this environment. "
            "Operator must set STRIPE_API_KEY and STRIPE_PRICE_* env vars.",
            status_code=503,
        )


_ACTIVE_SUBSCRIPTION_STATUSES = ("active", "past_due", "manual", "trialing")
_PENDING_CHECKOUT_HOLD_SECONDS = 24 * 60 * 60


def _workspace_has_active_paid_subscription(
    db: Session, *, workspace_id: str,
) -> bool:
    """HIGH-5: block stacking a fresh checkout when there's already an
    active non-trialing subscription. Users must cancel via the portal
    first so we don't end up with parallel Pro + Power lines.
    """
    now = datetime.now(timezone.utc)
    return db.query(Subscription).filter(
        Subscription.workspace_id == workspace_id,
    ).filter(
        or_(
            Subscription.status.in_(_ACTIVE_SUBSCRIPTION_STATUSES),
            (
                (Subscription.status == "incomplete")
                & (
                    (Subscription.current_period_end.is_(None))
                    | (Subscription.current_period_end > now)
                )
            ),
        )
    ).first() is not None


def _workspace_has_used_trial(db: Session, *, workspace_id: str) -> bool:
    """HIGH-5: grant trial_period_days=14 only if this workspace has
    never trialed before. trial_used_at is stamped from the webhook
    (checkout.session.completed / subscription.updated) the first time
    we see trialing status.
    """
    return db.query(Subscription).filter(
        Subscription.workspace_id == workspace_id,
    ).filter(
        or_(
            Subscription.status == "trialing",
            Subscription.trial_used_at.is_not(None),
        )
    ).first() is not None


def _reserve_trial_checkout(
    db: Session,
    *,
    workspace_id: str,
    plan: str,
    cycle: str,
    seats: int,
) -> bool:
    """Persist a one-shot trial reservation before Stripe session creation."""
    from app.models import Workspace

    (
        db.query(Workspace)
        .filter(Workspace.id == workspace_id)
        .with_for_update()
        .first()
    )
    if _workspace_has_active_paid_subscription(db, workspace_id=workspace_id):
        raise ApiError(
            "subscription_exists",
            "You already have an active subscription. "
            "Manage or cancel it from the billing portal before starting a new plan.",
            status_code=409,
        )
    if _workspace_has_used_trial(db, workspace_id=workspace_id):
        return False
    now = datetime.now(timezone.utc)
    db.add(Subscription(
        workspace_id=workspace_id,
        stripe_subscription_id=None,
        plan=plan,
        billing_cycle=cycle,
        status="incomplete",
        provider="stripe_recurring",
        current_period_start=now,
        current_period_end=now + timedelta(seconds=_PENDING_CHECKOUT_HOLD_SECONDS),
        seats=seats,
        trial_used_at=now,
    ))
    db.commit()
    return True


@router.post("/checkout", response_model=CheckoutResponse)
def post_checkout(
    payload: CheckoutRequest,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    workspace_role: str = Depends(get_current_workspace_role),
    _: None = Depends(require_csrf_protection),
) -> CheckoutResponse:
    _require_billing_access(workspace_role)
    _require_billing_configured()
    if payload.plan != "team" and payload.seats != 1:
        raise ApiError("invalid_input",
                       "seats only valid for team plan", status_code=400)
    try:
        price_id = stripe_client.stripe_price_id_for(payload.plan, payload.cycle)
    except ValueError:
        raise ApiError(
            "billing_not_configured",
            "Billing plan prices are not configured.",
            status_code=503,
        )
    if not price_id:
        raise ApiError(
            "billing_not_configured",
            "Billing plan prices are not configured.",
            status_code=503,
        )
    # HIGH-5: refuse to open a second active subscription on the same
    # workspace. The user must cancel the current plan from the portal
    # first; otherwise we'd end up double-billing or granting overlapping
    # entitlements (Pro + Power).
    if _workspace_has_active_paid_subscription(db, workspace_id=workspace_id):
        raise ApiError(
            "subscription_exists",
            "You already have an active subscription. "
            "Manage or cancel it from the billing portal before starting a new plan.",
            status_code=409,
        )
    ca = _ensure_customer(db, workspace_id=workspace_id, user=current_user)
    # Pro / Power get a 14-day trial; Team is treated as enterprise-like
    # and starts paid immediately. HIGH-5: trial is one-shot per workspace.
    trial_days: int | None = None
    reserved_trial = False
    if payload.plan in ("pro", "power"):
        if _reserve_trial_checkout(
            db,
            workspace_id=workspace_id,
            plan=payload.plan,
            cycle=payload.cycle,
            seats=payload.seats,
        ):
            trial_days = 14
            reserved_trial = True
        else:
            trial_days = None
    try:
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
    except Exception:
        if reserved_trial:
            pending = (
                db.query(Subscription)
                .filter(
                    Subscription.workspace_id == workspace_id,
                    Subscription.status == "incomplete",
                    Subscription.stripe_subscription_id.is_(None),
                )
                .order_by(Subscription.created_at.desc())
                .first()
            )
            if pending is not None:
                pending.status = "canceled"
                db.add(pending)
                db.commit()
        raise
    return CheckoutResponse(checkout_url=url)


@router.post("/checkout-onetime", response_model=CheckoutResponse)
def post_checkout_onetime(
    payload: CheckoutOnetimeRequest,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    workspace_role: str = Depends(get_current_workspace_role),
    _: None = Depends(require_csrf_protection),
) -> CheckoutResponse:
    _require_billing_access(workspace_role)
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
    workspace_role: str = Depends(get_current_workspace_role),
    _: None = Depends(require_csrf_protection),
) -> PortalResponse:
    _require_billing_access(workspace_role)
    ca = db.query(CustomerAccount).filter_by(workspace_id=workspace_id).first()
    if ca is None:
        raise ApiError("not_found",
                       "No Stripe customer for this workspace", status_code=404)
    url = stripe_client.create_billing_portal_session(
        stripe_customer_id=ca.stripe_customer_id,
        return_url=settings.stripe_billing_portal_return_url,
    )
    return PortalResponse(portal_url=url)


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

    ai_actions_count = count_ai_actions_this_month(db, workspace_id)
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


def _mask_price_id(pid: str | None) -> str | None:
    """MEDIUM-16: don't leak the full Stripe price_id on a public list;
    return a short suffix so the UI can still distinguish plans for
    tracking/analytics if needed, but enumeration of our exact price
    tokens is blocked. None plans (free) stay None.
    """
    if not pid:
        return None
    if len(pid) <= 8:
        return "masked"
    return f"****{pid[-4:]}"


@router.get("/plans", response_model=PlansResponse)
def get_plans() -> PlansResponse:
    plans = []
    for plan_id, ents in PLAN_ENTITLEMENTS.items():
        if plan_id == "free":
            prices = {"monthly": None, "yearly": None}
        else:
            prices = {
                "monthly": _mask_price_id(
                    stripe_client.stripe_price_id_for(plan_id, "monthly"),
                ),
                "yearly": _mask_price_id(
                    stripe_client.stripe_price_id_for(plan_id, "yearly"),
                ),
            }
        plans.append({
            "id": plan_id,
            "stripe_prices": prices,
            "entitlements": ents,
        })
    return PlansResponse(plans=plans)


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
        existing = db.query(BillingEvent).filter_by(stripe_event_id=event_id).first()
        if existing is None or (existing.processed_at is not None and not existing.error):
            return JSONResponse(status_code=200, content={"ok": True, "skipped": True})
        existing.error = None
        db.add(existing)
        db.commit()

    payload_obj = (event.get("data") or {}).get("object") or {}

    try:
        if event_type == "checkout.session.completed":
            billing_webhook.handle_checkout_session_completed(db, payload_obj)
        elif event_type == "checkout.session.async_payment_succeeded":
            billing_webhook.handle_checkout_session_async_payment_succeeded(db, payload_obj)
        elif event_type == "checkout.session.async_payment_failed":
            billing_webhook.handle_checkout_session_async_payment_failed(db, payload_obj)
        elif event_type == "customer.subscription.updated":
            billing_webhook.handle_subscription_updated(db, payload_obj)
        elif event_type == "customer.subscription.deleted":
            billing_webhook.handle_subscription_deleted(db, payload_obj)
        elif event_type == "invoice.paid":
            billing_webhook.handle_invoice_paid(db, payload_obj)
        elif event_type == "invoice.payment_failed":
            billing_webhook.handle_invoice_payment_failed(db, payload_obj)
        elif event_type == "charge.refunded":
            # LOW-18: cancel the manual subscription on refund.
            billing_webhook.handle_charge_refunded(db, payload_obj)
        be = db.query(BillingEvent).filter_by(stripe_event_id=event_id).first()
        if be is not None:
            be.processed_at = datetime.now(timezone.utc)
            db.add(be)
            db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        be = db.query(BillingEvent).filter_by(stripe_event_id=event_id).first()
        if be is not None:
            be.error = str(exc)[:500]
            db.add(be)
            db.commit()
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": "webhook_processing_failed"},
        )

    return JSONResponse(status_code=200, content={"ok": True})
