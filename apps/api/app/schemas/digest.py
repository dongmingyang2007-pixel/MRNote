"""Pydantic schemas for the homepage ``/api/v1/digest/*`` API.

Spec: ``升级说明-Persona与Digest.md`` §2.3. These types mirror the
``DailyDigest`` / ``WeeklyReflection`` TypeScript shapes in the homepage
bundle — the server is allowed to add fields (forward-compat) but should
not drop fields the mock data relies on.

Payload shape is intentionally loose (`dict[str, Any]`) rather than
fully-typed blocks because the homepage consumes the payload as-is and
we want the stub generator to evolve without thrashing the wire schema.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Daily
# ---------------------------------------------------------------------------


class DigestDailyOut(BaseModel):
    """The JSON body returned by ``GET /api/v1/digest/daily``.

    ``payload`` matches the ``DailyDigest`` TS type in the homepage bundle
    (blocks: catch / today / insight). ``read_at`` is null until the user
    dismisses the digest via ``/daily/mark-read``.
    """

    date: date
    payload: dict[str, Any]
    read_at: datetime | None = None
    created_at: datetime


class DigestDailyMarkReadRequest(BaseModel):
    date: date


# ---------------------------------------------------------------------------
# Weekly
# ---------------------------------------------------------------------------


_ISO_WEEK_PATTERN = r"^\d{4}-W(?:0[1-9]|[1-4][0-9]|5[0-3])$"


class DigestWeeklyOut(BaseModel):
    iso_week: str = Field(..., pattern=_ISO_WEEK_PATTERN)
    payload: dict[str, Any]
    saved_page_id: str | None = None
    created_at: datetime


class DigestWeeklySaveAsPageRequest(BaseModel):
    """``POST /api/v1/digest/weekly/save-as-page`` body.

    ``pickOption`` is the optional "next-week main thread" pick the user
    chose in the UI; when present we surface it at the top of the new
    page. Keeping the key as ``pickOption`` (camelCase) matches the TS
    definition in the spec so the frontend can reuse its types verbatim.
    """

    week: str = Field(..., pattern=_ISO_WEEK_PATTERN)
    pickOption: str | None = None  # noqa: N815 — matches TS spec literal

    @field_validator("pickOption")
    @classmethod
    def _strip_pick_option(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class DigestWeeklySaveAsPageResponse(BaseModel):
    page_id: str


# ---------------------------------------------------------------------------
# Preferences (email opt-out)
# ---------------------------------------------------------------------------


class DigestPreferencesPatchRequest(BaseModel):
    """``PATCH /api/v1/digest/preferences`` body.

    Narrow surface for now — email toggle only. Kept separate from the
    broader ``/auth/me`` PATCH so a settings page that just flips the
    email toggle doesn't need to know about persona/timezone wiring.
    """

    email_enabled: bool


class DigestPreferencesOut(BaseModel):
    email_enabled: bool
    timezone: str | None = None
