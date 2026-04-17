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
