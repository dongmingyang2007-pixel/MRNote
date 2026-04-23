from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, field_validator


# Homepage spec §1.7 — three persona values live at the product layer
# (Hero pill, registration step 2, Settings → Profile). Null means "not
# yet set"; the API never infers a value server-side.
PersonaValue = Literal["student", "researcher", "pm"]


class SendCodeRequest(BaseModel):
    email: EmailStr
    purpose: str = "register"

    @field_validator("email", mode="after")
    @classmethod
    def _normalize_email(cls, value: EmailStr) -> str:
        return value.strip().lower()

    @field_validator("purpose")
    @classmethod
    def _validate_purpose(cls, value: str) -> str:
        if value not in ("register", "reset"):
            raise ValueError("purpose must be 'register' or 'reset'")
        return value


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    display_name: str | None = None
    code: str

    @field_validator("email", mode="after")
    @classmethod
    def _normalize_email(cls, value: EmailStr) -> str:
        return value.strip().lower()

    @field_validator("password")
    @classmethod
    def _validate_password(cls, value: str) -> str:
        if len(value) < 12:
            raise ValueError("Password must be at least 12 characters long")
        return value

    @field_validator("code")
    @classmethod
    def _validate_code(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Verification code is required")
        return value.strip()


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    password: str
    code: str

    @field_validator("email", mode="after")
    @classmethod
    def _normalize_email(cls, value: EmailStr) -> str:
        return value.strip().lower()

    @field_validator("password")
    @classmethod
    def _validate_password(cls, value: str) -> str:
        if len(value) < 12:
            raise ValueError("Password must be at least 12 characters long")
        return value

    @field_validator("code")
    @classmethod
    def _validate_code(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Verification code is required")
        return value.strip()


class LoginRequest(BaseModel):
    email: EmailStr
    password: str

    @field_validator("email", mode="after")
    @classmethod
    def _normalize_email(cls, value: EmailStr) -> str:
        return value.strip().lower()

    @field_validator("password")
    @classmethod
    def _validate_password(cls, value: str) -> str:
        if len(value) < 12:
            raise ValueError("Password must be at least 12 characters long")
        return value


class UserOut(BaseModel):
    id: str
    email: EmailStr
    display_name: str | None
    created_at: datetime
    onboarding_completed_at: datetime | None = None
    # Homepage persona selector — null until the user picks one.
    persona: PersonaValue | None = None


class MePatchRequest(BaseModel):
    """PATCH /api/v1/auth/me body.

    Today only ``persona`` is patchable. Keeping the request model
    narrow so mis-typed JSON keys don't silently no-op — Pydantic will
    still accept the body but only these fields are honored.
    """

    # Explicit Optional so the caller can clear the value back to null
    # ("I no longer identify as student/researcher/pm") — the write path
    # treats missing vs null differently: missing leaves the column alone,
    # null writes NULL. See ``update_me`` in routers/auth.py.
    persona: PersonaValue | None = None


class WorkspaceOut(BaseModel):
    id: str
    name: str
    plan: str
    created_at: datetime


class AuthResponse(BaseModel):
    user: UserOut
    workspace: WorkspaceOut
    access_token_expires_in_seconds: int
