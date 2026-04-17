from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class CheckoutRequest(BaseModel):
    plan: str = Field(..., pattern=r"^(pro|power|team)$")
    cycle: str = Field(..., pattern=r"^(monthly|yearly)$")
    seats: int = Field(default=1, ge=1, le=100)


class CheckoutOnetimeRequest(BaseModel):
    plan: str = Field(..., pattern=r"^(pro|power|team)$")
    cycle: str = Field(..., pattern=r"^(monthly|yearly)$")
    payment_method: str = Field(..., pattern=r"^(alipay|wechat_pay)$")
    seats: int = Field(default=1, ge=1, le=100)


class CheckoutResponse(BaseModel):
    checkout_url: str


class PortalResponse(BaseModel):
    portal_url: str


class BillingMeResponse(BaseModel):
    plan: str
    status: str
    billing_cycle: str
    current_period_end: datetime | None
    seats: int
    cancel_at_period_end: bool
    provider: str
    entitlements: dict[str, Any]
    usage_this_month: dict[str, int]


class PlansResponse(BaseModel):
    plans: list[dict[str, Any]]
