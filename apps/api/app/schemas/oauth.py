"""Schemas for OAuth identity endpoints (Google / Apple / …)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class OAuthIdentityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    provider: str
    provider_email: str | None
    linked_at: datetime


class SetPasswordRequest(BaseModel):
    new_password: str = Field(min_length=8, max_length=200)
    # Optional — required when the user already has a password.
    current_password: str | None = None


class OAuthDisconnectResponse(BaseModel):
    success: bool


class SetPasswordResponse(BaseModel):
    success: bool
