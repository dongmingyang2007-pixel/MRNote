"""Homepage daily/weekly digest API — spec §2.3.

Four endpoints:

* ``GET  /api/v1/digest/daily?date=YYYY-MM-DD``      — fetch the generated daily card
* ``POST /api/v1/digest/daily/mark-read``            — dismiss today's card (204)
* ``GET  /api/v1/digest/weekly?week=YYYY-Www``       — fetch the generated weekly card
* ``POST /api/v1/digest/weekly/save-as-page``        — materialize weekly card as a NotebookPage

All reads require an authenticated user; all writes add CSRF + origin
checks. Query params are parsed strictly (bad date / iso_week ⇒ 400).
404 responses carry ``{error:{code:"not_generated", ...}}`` so the
frontend can distinguish "nothing to show yet" from a real error.
"""

from __future__ import annotations

from datetime import date as _date_type
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import (
    get_current_user,
    get_db_session,
    require_allowed_origin,
    require_csrf_protection,
)
from app.core.errors import ApiError
from app.models import (
    DigestDaily,
    DigestWeekly,
    Membership,
    Notebook,
    NotebookPage,
    User,
)
from app.schemas.digest import (
    DigestDailyMarkReadRequest,
    DigestDailyOut,
    DigestPreferencesOut,
    DigestPreferencesPatchRequest,
    DigestWeeklyOut,
    DigestWeeklySaveAsPageRequest,
    DigestWeeklySaveAsPageResponse,
)
from app.services.audit import write_audit_log

# Keep the iso_week validator here so the router's API contract is
# self-describing — matches the Pydantic pattern in schemas/digest.py.
import re
_ISO_WEEK_RE = re.compile(r"^\d{4}-W(?:0[1-9]|[1-4][0-9]|5[0-3])$")


router = APIRouter(prefix="/api/v1/digest", tags=["digest"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_date_query(raw: str | None) -> _date_type:
    """Parse ?date=YYYY-MM-DD; default to today UTC if absent."""
    if raw is None or raw == "":
        return datetime.now(timezone.utc).date()
    try:
        return _date_type.fromisoformat(raw)
    except (TypeError, ValueError) as exc:
        raise ApiError(
            "invalid_input", "date must be YYYY-MM-DD", status_code=400,
        ) from exc


def _validate_iso_week(raw: str | None) -> str:
    if not raw:
        raise ApiError(
            "invalid_input", "week is required (format: YYYY-Www)",
            status_code=400,
        )
    if not _ISO_WEEK_RE.match(raw):
        raise ApiError(
            "invalid_input", "week must be YYYY-Www (e.g. 2026-W17)",
            status_code=400,
        )
    return raw


def _not_generated(kind: str) -> ApiError:
    return ApiError(
        "not_generated",
        f"{kind} digest has not been generated yet",
        status_code=404,
    )


def _pick_default_notebook(db: Session, user: User) -> Notebook | None:
    """Return the notebook the user should save weekly reflections into.

    Strategy: pick the earliest-created, non-archived notebook in any
    workspace the user is a member of, created_by the user. If none
    exists we return None — the caller surfaces ``no_default_notebook``
    instead of silently creating one.
    """
    membership_ids = (
        db.query(Membership.workspace_id)
        .filter(Membership.user_id == user.id)
        .all()
    )
    workspace_ids = [row[0] for row in membership_ids if row[0]]
    if not workspace_ids:
        return None
    return (
        db.query(Notebook)
        .filter(
            Notebook.workspace_id.in_(workspace_ids),
            Notebook.created_by == user.id,
            Notebook.archived_at.is_(None),
        )
        .order_by(Notebook.created_at.asc())
        .first()
    )


# ---------------------------------------------------------------------------
# Daily
# ---------------------------------------------------------------------------


@router.get("/daily", response_model=DigestDailyOut)
def get_daily_digest(
    request: Request,
    date: str | None = Query(default=None),
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> DigestDailyOut:
    require_allowed_origin(request)
    target_day = _parse_date_query(date)
    row = (
        db.execute(
            select(DigestDaily)
            .where(
                DigestDaily.user_id == current_user.id,
                DigestDaily.date == target_day,
            )
        )
        .scalar_one_or_none()
    )
    if row is None:
        raise _not_generated("daily")
    return DigestDailyOut(
        date=row.date,
        payload=row.payload or {},
        read_at=row.read_at,
        created_at=row.created_at,
    )


@router.post("/daily/mark-read", status_code=204)
def mark_daily_digest_read(
    payload: DigestDailyMarkReadRequest,
    request: Request,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(require_csrf_protection),
) -> Response:
    require_allowed_origin(request)
    row = (
        db.execute(
            select(DigestDaily)
            .where(
                DigestDaily.user_id == current_user.id,
                DigestDaily.date == payload.date,
            )
        )
        .scalar_one_or_none()
    )
    if row is None:
        raise _not_generated("daily")
    if row.read_at is None:
        row.read_at = datetime.now(timezone.utc)
        db.add(row)
        db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Weekly
# ---------------------------------------------------------------------------


@router.get("/weekly", response_model=DigestWeeklyOut)
def get_weekly_digest(
    request: Request,
    week: str | None = Query(default=None),
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> DigestWeeklyOut:
    require_allowed_origin(request)
    iso_week = _validate_iso_week(week)
    row = (
        db.execute(
            select(DigestWeekly)
            .where(
                DigestWeekly.user_id == current_user.id,
                DigestWeekly.iso_week == iso_week,
            )
        )
        .scalar_one_or_none()
    )
    if row is None:
        raise _not_generated("weekly")
    return DigestWeeklyOut(
        iso_week=row.iso_week,
        payload=row.payload or {},
        saved_page_id=row.saved_page_id,
        created_at=row.created_at,
    )


@router.post("/weekly/save-as-page", response_model=DigestWeeklySaveAsPageResponse)
def save_weekly_as_page(
    payload: DigestWeeklySaveAsPageRequest,
    request: Request,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(require_csrf_protection),
) -> DigestWeeklySaveAsPageResponse:
    """Materialize a weekly reflection as a ``NotebookPage``.

    Spec §2.3. The user picks this from the weekly card's "save as page"
    affordance; we drop a ready-to-edit page in their default notebook
    and persist a back-pointer on ``digest_weekly.saved_page_id`` so we
    can show "already saved" state on subsequent reads.
    """
    require_allowed_origin(request)
    _ = _validate_iso_week(payload.week)

    row = (
        db.execute(
            select(DigestWeekly)
            .where(
                DigestWeekly.user_id == current_user.id,
                DigestWeekly.iso_week == payload.week,
            )
        )
        .scalar_one_or_none()
    )
    if row is None:
        raise _not_generated("weekly")

    notebook = _pick_default_notebook(db, current_user)
    if notebook is None:
        raise ApiError(
            "no_default_notebook",
            "Create a notebook first before saving a weekly reflection.",
            status_code=400,
        )

    # Render the payload into both a TipTap doc (for content_json) and
    # a plain-text shadow (for search / preview) — notebooks always
    # store both.
    from app.services.digest_generation import (
        render_weekly_reflection_markdown,
        render_weekly_reflection_tiptap,
    )
    from app.routers.notebooks import make_slug

    payload_json = row.payload or {}
    tiptap_doc = render_weekly_reflection_tiptap(
        payload_json, pick_option=payload.pickOption,
    )
    markdown = render_weekly_reflection_markdown(
        payload_json, pick_option=payload.pickOption,
    )
    range_label = payload_json.get("range") or payload.week
    title = f"本周反思 · {range_label}"

    page = NotebookPage(
        notebook_id=notebook.id,
        created_by=current_user.id,
        title=title,
        slug=make_slug(title),
        page_type="document",
        content_json=tiptap_doc,
        plain_text=markdown,
        sort_order=0,
    )
    db.add(page)
    db.flush()

    row.saved_page_id = page.id
    db.add(row)
    write_audit_log(
        db,
        workspace_id=notebook.workspace_id,
        actor_user_id=current_user.id,
        action="digest.weekly.save_as_page",
        target_type="notebook_page",
        target_id=page.id,
        meta_json={"iso_week": payload.week, "pick_option": payload.pickOption},
    )
    db.commit()

    return DigestWeeklySaveAsPageResponse(page_id=page.id)


# ---------------------------------------------------------------------------
# Preferences (email opt-out)
# ---------------------------------------------------------------------------


@router.get("/preferences", response_model=DigestPreferencesOut)
def get_digest_preferences(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> DigestPreferencesOut:
    """Return the current user's digest preferences (email toggle + tz)."""
    require_allowed_origin(request)
    return DigestPreferencesOut(
        email_enabled=bool(getattr(current_user, "digest_email_enabled", True)),
        timezone=getattr(current_user, "timezone", None),
    )


@router.patch("/preferences", response_model=DigestPreferencesOut)
def patch_digest_preferences(
    payload: DigestPreferencesPatchRequest,
    request: Request,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(require_csrf_protection),
) -> DigestPreferencesOut:
    """Toggle digest email delivery for the current user.

    Only ``email_enabled`` is patchable here; timezone lives on the
    ``/auth/me`` PATCH so we don't duplicate IANA validation.
    """
    require_allowed_origin(request)
    current_user.digest_email_enabled = bool(payload.email_enabled)
    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    return DigestPreferencesOut(
        email_enabled=bool(current_user.digest_email_enabled),
        timezone=getattr(current_user, "timezone", None),
    )
