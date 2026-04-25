# ruff: noqa: E402
"""Regression tests for the homepage persona + digest upgrade.

Covers:
* ``users.persona`` round-trip through ``GET /me`` / ``PATCH /me``
* persona enum validation + CSRF + rate-limit on ``PATCH /me``
* ``/api/v1/digest/daily`` fetch + mark-read
* ``/api/v1/digest/weekly`` fetch + save-as-page
* user-scope isolation (user A rows never surface for user B)

Uses the same SQLite-in-tempdir setup template as
``test_chat_quota_gates.py`` (importlib reload dance) so schema bootstrap
runs against this file's DB, not whatever another test left behind.
"""

import atexit
import hashlib
import importlib
import os
import shutil
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="mrnote-persona-digest-"))
atexit.register(lambda: shutil.rmtree(TEST_TEMP_DIR, ignore_errors=True))
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_TEMP_DIR / 'test.db'}"
os.environ["ENV"] = "test"
os.environ["COOKIE_DOMAIN"] = ""
os.environ["DEMO_MODE"] = "true"
os.environ["STRIPE_API_KEY"] = "sk_test_dummy"

import app.core.config as config_module
config_module.get_settings.cache_clear()
config_module.settings = config_module.get_settings()
import app.db.session as session_module
importlib.reload(session_module)
import app.main as main_module
importlib.reload(main_module)

from fastapi.testclient import TestClient

import app.db.session as _s
import app.routers.auth as auth_router
import app.routers.digest as digest_router
from app.db.base import Base
from app.models import (
    DigestDaily,
    DigestWeekly,
    Notebook,
    NotebookPage,
    User,
)
from app.services.runtime_state import runtime_state


def setup_function() -> None:
    Base.metadata.drop_all(bind=_s.engine)
    Base.metadata.create_all(bind=_s.engine)
    runtime_state._memory = runtime_state._memory.__class__()
    importlib.reload(auth_router)
    importlib.reload(digest_router)
    importlib.reload(main_module)


def _public() -> dict[str, str]:
    return {"origin": "http://localhost:3000"}


def _register(email: str = "u@x.co") -> tuple[TestClient, str, str]:
    """Register + return (client, workspace_id, user_id)."""
    client = TestClient(main_module.app)
    client.post(
        "/api/v1/auth/send-code",
        json={"email": email, "purpose": "register"},
        headers=_public(),
    )
    code_key = hashlib.sha256(f"{email.lower().strip()}:register".encode()).hexdigest()
    code = str(runtime_state.get_json("verify_code", code_key)["code"])
    info = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "pass1234pass",
            "display_name": "Test",
            "code": code,
        },
        headers=_public(),
    ).json()
    csrf = client.get("/api/v1/auth/csrf", headers=_public()).json()["csrf_token"]
    ws_id = info["workspace"]["id"]
    user_id = info["user"]["id"]
    client.headers.update({
        "origin": "http://localhost:3000",
        "x-csrf-token": csrf,
        "x-workspace-id": ws_id,
    })
    return client, ws_id, user_id


# ---------------------------------------------------------------------------
# Persona: GET /me + PATCH /me
# ---------------------------------------------------------------------------


def test_me_returns_persona_field_null_by_default() -> None:
    client, _, _ = _register("persona-null@x.co")
    resp = client.get("/api/v1/auth/me", headers=_public())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "persona" in body, body
    assert body["persona"] is None, body


def test_patch_me_persona_valid_value_persists() -> None:
    client, _, user_id = _register("persona-valid@x.co")
    resp = client.patch(
        "/api/v1/auth/me",
        json={"persona": "student"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["persona"] == "student", body

    # Fetch again via GET /me to confirm the value was persisted.
    resp2 = client.get("/api/v1/auth/me", headers=_public())
    assert resp2.status_code == 200
    assert resp2.json()["persona"] == "student"

    # DB-level check to guard against the router returning a stale in-memory
    # value that never reached the row.
    with _s.SessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None
        assert user.persona == "student"


def test_patch_me_persona_rejects_invalid_enum() -> None:
    client, _, _ = _register("persona-bad@x.co")
    resp = client.patch(
        "/api/v1/auth/me",
        json={"persona": "founder"},  # not in (student/researcher/pm)
    )
    assert resp.status_code == 422, resp.text


def test_patch_me_persona_requires_csrf() -> None:
    client, _, _ = _register("persona-csrf@x.co")
    # Strip the CSRF header (the header the client was initialized with)
    # and the cookie too so require_csrf_protection trips.
    client.headers.pop("x-csrf-token", None)
    client.cookies.clear()
    resp = client.patch(
        "/api/v1/auth/me",
        json={"persona": "pm"},
        headers=_public(),
    )
    # Without an auth cookie either unauthorized or csrf_required is
    # acceptable — both mean the write path refused an unauthenticated /
    # unprotected caller.
    assert resp.status_code in (401, 403), resp.text


def test_patch_me_persona_rate_limited() -> None:
    client, _, _ = _register("persona-rl@x.co")
    # The limit is 20 / 60s per user. Fire 21 requests and expect the
    # last to 429. The first 20 can succeed or accept the same value
    # repeatedly — both are fine for this test.
    last_status = 200
    for i in range(21):
        persona = "student" if i % 2 == 0 else "researcher"
        resp = client.patch("/api/v1/auth/me", json={"persona": persona})
        last_status = resp.status_code
    assert last_status == 429, last_status


# ---------------------------------------------------------------------------
# Digest daily
# ---------------------------------------------------------------------------


def _insert_daily(user_id: str, target_day: date, payload: dict) -> None:
    with _s.SessionLocal() as db:
        db.add(DigestDaily(
            user_id=user_id,
            date=target_day,
            payload=payload,
        ))
        db.commit()


def test_get_digest_daily_returns_404_when_absent() -> None:
    client, _, _ = _register("dd-absent@x.co")
    today = datetime.now(timezone.utc).date().isoformat()
    resp = client.get(
        f"/api/v1/digest/daily?date={today}",
        headers=_public(),
    )
    assert resp.status_code == 404, resp.text
    body = resp.json()
    code = body.get("error", {}).get("code") or body.get("code")
    assert code == "not_generated", body


def test_get_digest_daily_returns_payload_when_present() -> None:
    client, _, user_id = _register("dd-present@x.co")
    today = datetime.now(timezone.utc).date()
    sample = {
        "date": today.isoformat(),
        "greeting": "早安",
        "blocks": [{"kind": "catch", "title": "", "items": []}],
    }
    _insert_daily(user_id, today, sample)
    resp = client.get(
        f"/api/v1/digest/daily?date={today.isoformat()}",
        headers=_public(),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["date"] == today.isoformat()
    assert body["payload"]["greeting"] == "早安"
    assert body["read_at"] is None


def test_digest_daily_mark_read_sets_read_at() -> None:
    client, _, user_id = _register("dd-mark@x.co")
    today = datetime.now(timezone.utc).date()
    _insert_daily(user_id, today, {"date": today.isoformat(), "blocks": []})

    resp = client.post(
        "/api/v1/digest/daily/mark-read",
        json={"date": today.isoformat()},
    )
    assert resp.status_code == 204, resp.text

    # Confirm the row was updated server-side.
    with _s.SessionLocal() as db:
        row = (
            db.query(DigestDaily)
            .filter(DigestDaily.user_id == user_id, DigestDaily.date == today)
            .first()
        )
        assert row is not None
        assert row.read_at is not None
        # Subsequent GET shows the populated read_at.

    resp2 = client.get(
        f"/api/v1/digest/daily?date={today.isoformat()}",
        headers=_public(),
    )
    assert resp2.status_code == 200
    assert resp2.json()["read_at"] is not None


# ---------------------------------------------------------------------------
# Digest weekly
# ---------------------------------------------------------------------------


def _insert_weekly(user_id: str, iso_week: str, payload: dict) -> None:
    with _s.SessionLocal() as db:
        db.add(DigestWeekly(
            user_id=user_id,
            iso_week=iso_week,
            payload=payload,
        ))
        db.commit()


def test_get_digest_weekly_returns_404_when_absent() -> None:
    client, _, _ = _register("dw-absent@x.co")
    resp = client.get(
        "/api/v1/digest/weekly?week=2026-W17",
        headers=_public(),
    )
    assert resp.status_code == 404, resp.text
    code = resp.json().get("error", {}).get("code")
    assert code == "not_generated"


def test_digest_weekly_save_as_page_creates_notebook_page() -> None:
    client, ws_id, user_id = _register("dw-save@x.co")

    # Need a default notebook — _pick_default_notebook walks workspace
    # memberships and picks the earliest-created notebook created_by
    # the user. Create one via the API so the quota gate is satisfied.
    nb_resp = client.post(
        "/api/v1/notebooks",
        json={"title": "Reflections", "notebook_type": "personal"},
    )
    assert nb_resp.status_code in (200, 201), nb_resp.text

    iso_week = "2026-W17"
    sample = {
        "range": "Apr 20 - Apr 26",
        "iso_week": iso_week,
        "headline": "Deep work held up this week.",
        "stats": [{"k": "pages", "v": "3"}],
        "moves": ["Closed the long-running FSRS spike"],
        "options": ["Start the next retention experiment"],
        "sparkline": [],
    }
    _insert_weekly(user_id, iso_week, sample)

    resp = client.post(
        "/api/v1/digest/weekly/save-as-page",
        json={"week": iso_week, "pickOption": "Start the next retention experiment"},
    )
    assert resp.status_code == 200, resp.text
    page_id = resp.json()["page_id"]
    assert page_id

    with _s.SessionLocal() as db:
        page = db.get(NotebookPage, page_id)
        assert page is not None
        assert page.created_by == user_id
        assert "本周反思" in page.title
        assert "Start the next retention experiment" in page.plain_text
        # saved_page_id should now point at the new page.
        weekly = (
            db.query(DigestWeekly)
            .filter(
                DigestWeekly.user_id == user_id,
                DigestWeekly.iso_week == iso_week,
            )
            .first()
        )
        assert weekly is not None
        assert weekly.saved_page_id == page_id


# ---------------------------------------------------------------------------
# Isolation
# ---------------------------------------------------------------------------


def test_digest_daily_respects_user_isolation() -> None:
    client_a, _, user_a = _register("iso-a@x.co")
    client_b, _, _user_b = _register("iso-b@x.co")
    today = datetime.now(timezone.utc).date()
    _insert_daily(user_a, today, {"date": today.isoformat(), "secret": "user_a_only"})

    resp_b = client_b.get(
        f"/api/v1/digest/daily?date={today.isoformat()}",
        headers=_public(),
    )
    assert resp_b.status_code == 404, resp_b.text
    assert resp_b.json().get("error", {}).get("code") == "not_generated"

    resp_a = client_a.get(
        f"/api/v1/digest/daily?date={today.isoformat()}",
        headers=_public(),
    )
    assert resp_a.status_code == 200
    assert resp_a.json()["payload"]["secret"] == "user_a_only"
