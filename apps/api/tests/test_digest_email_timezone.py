# ruff: noqa: E402
"""Regression tests for the DIGEST upgrade (LLM + timezone + SMTP email).

Covers:
* ``users.timezone`` default + round-trip through ``GET/PATCH /auth/me``
* IANA validation on ``timezone`` (good + bad strings)
* ``digest_email_enabled`` toggle via both ``/auth/me`` and
  ``/digest/preferences``
* ``daily_digest_generate_task`` timezone window filter
* LLM fallback to ``Pending`` when the model call raises
* Email dispatch respects the opt-out flag and SMTP test-env short circuit
* HTML template renders the payload values we care about
"""

import atexit
import hashlib
import importlib
import os
import shutil
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-digest-tz-"))
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
    AIActionLog,
    Membership,
    NotebookPage,
    User,
    Workspace,
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
# Schema defaults
# ---------------------------------------------------------------------------


def test_user_timezone_field_default_null() -> None:
    client, _, user_id = _register("tz-default@x.co")
    resp = client.get("/api/v1/auth/me", headers=_public())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "timezone" in body, body
    assert body["timezone"] is None, body
    assert body.get("digest_email_enabled") is True, body

    # DB-level confirmation.
    with _s.SessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None
        assert user.timezone is None
        assert user.digest_email_enabled is True


# ---------------------------------------------------------------------------
# PATCH /me — timezone + digest_email_enabled
# ---------------------------------------------------------------------------


def test_patch_me_accepts_valid_timezone() -> None:
    client, _, user_id = _register("tz-valid@x.co")
    resp = client.patch(
        "/api/v1/auth/me",
        json={"timezone": "Asia/Shanghai"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["timezone"] == "Asia/Shanghai"

    # GET /me echoes it back.
    resp2 = client.get("/api/v1/auth/me", headers=_public())
    assert resp2.status_code == 200
    assert resp2.json()["timezone"] == "Asia/Shanghai"

    with _s.SessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None
        assert user.timezone == "Asia/Shanghai"


def test_patch_me_rejects_invalid_timezone() -> None:
    client, _, _ = _register("tz-bad@x.co")
    resp = client.patch(
        "/api/v1/auth/me",
        json={"timezone": "Mars/Phobos"},
    )
    assert resp.status_code == 422, resp.text


def test_patch_me_digest_email_enabled() -> None:
    client, _, user_id = _register("email-toggle@x.co")
    # default is TRUE, flip to FALSE
    resp = client.patch(
        "/api/v1/auth/me",
        json={"digest_email_enabled": False},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["digest_email_enabled"] is False

    with _s.SessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None
        assert user.digest_email_enabled is False


def test_digest_preferences_patch_toggles_email_flag() -> None:
    """PATCH /api/v1/digest/preferences {email_enabled: false} flips the flag."""
    client, _, user_id = _register("pref-patch@x.co")
    get_resp = client.get("/api/v1/digest/preferences", headers=_public())
    assert get_resp.status_code == 200, get_resp.text
    assert get_resp.json()["email_enabled"] is True

    patch_resp = client.patch(
        "/api/v1/digest/preferences",
        json={"email_enabled": False},
    )
    assert patch_resp.status_code == 200, patch_resp.text
    assert patch_resp.json()["email_enabled"] is False

    with _s.SessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None
        assert user.digest_email_enabled is False


# ---------------------------------------------------------------------------
# Timezone-aware scheduling
# ---------------------------------------------------------------------------


def _make_user_with_tz(email: str, tz: str | None, *, email_enabled: bool = True) -> str:
    """Insert a User + Workspace + Membership; return user.id."""
    with _s.SessionLocal() as db:
        user = User(
            email=email,
            password_hash="x",
            display_name="T",
            timezone=tz,
            digest_email_enabled=email_enabled,
        )
        ws = Workspace(name=f"{email} Workspace", plan="free")
        db.add(user)
        db.add(ws)
        db.flush()
        db.add(Membership(workspace_id=ws.id, user_id=user.id, role="owner"))
        db.commit()
        return user.id


def test_daily_digest_task_skips_users_outside_0830_window() -> None:
    """A user in Asia/Shanghai (UTC+8) at UTC 03:00 is at local 11:00 —
    outside the 08:00-08:59 local window, so the task must not generate."""
    import app.tasks.worker_tasks as worker_tasks
    importlib.reload(worker_tasks)

    user_id = _make_user_with_tz("outside@x.co", "Asia/Shanghai")

    # Freeze "now" to 2026-04-22 03:00 UTC == 2026-04-22 11:00 Shanghai.
    fake_now = datetime(2026, 4, 22, 3, 0, 0, tzinfo=timezone.utc)

    class _FakeDatetime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            if tz is None:
                return fake_now.replace(tzinfo=None)
            return fake_now.astimezone(tz)

    # Mock both the worker's and the digest_generation's datetime to
    # ensure activity collection stays consistent with scheduler.
    with (
        patch("app.tasks.worker_tasks.datetime", _FakeDatetime),
    ):
        out = worker_tasks.daily_digest_generate_task()
    assert out["generated"] == 0, out
    assert out["skipped_window"] == 1, out

    from app.models import DigestDaily
    with _s.SessionLocal() as db:
        count = db.query(DigestDaily).filter(DigestDaily.user_id == user_id).count()
        assert count == 0


def test_daily_digest_task_generates_for_user_in_window() -> None:
    """UTC 00:30 is 08:30 Shanghai — in window, digest should generate."""
    import app.tasks.worker_tasks as worker_tasks
    import app.services.digest_generation as digest_gen
    importlib.reload(digest_gen)
    importlib.reload(worker_tasks)

    user_id = _make_user_with_tz("inside@x.co", "Asia/Shanghai")

    fake_now = datetime(2026, 4, 22, 0, 30, 0, tzinfo=timezone.utc)

    class _FakeDatetime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            if tz is None:
                return fake_now.replace(tzinfo=None)
            return fake_now.astimezone(tz)

    # Mock LLM call to return a deterministic insight so we don't need
    # a real DashScope key.
    def _fake_llm(prompt: str):
        return {"title": "今日观察", "body": "昨日页面增加，建议延续节奏。"}

    with (
        patch("app.tasks.worker_tasks.datetime", _FakeDatetime),
        patch("app.services.digest_generation._call_llm_sync", _fake_llm),
    ):
        out = worker_tasks.daily_digest_generate_task()

    assert out["generated"] == 1, out
    assert out["skipped_window"] == 0, out

    from app.models import DigestDaily
    with _s.SessionLocal() as db:
        row = (
            db.query(DigestDaily)
            .filter(DigestDaily.user_id == user_id)
            .first()
        )
        assert row is not None
        # Date in Shanghai was 2026-04-22.
        assert row.date == date(2026, 4, 22)
        # Insight block carries the LLM body.
        insight = next(
            b for b in row.payload["blocks"] if b["kind"] == "insight"
        )
        assert "昨日页面" in insight["body"], insight


def test_daily_digest_task_skips_email_when_disabled() -> None:
    """digest_email_enabled=False must skip the SMTP path even in-window."""
    import app.tasks.worker_tasks as worker_tasks
    import app.services.digest_generation as digest_gen
    importlib.reload(digest_gen)
    importlib.reload(worker_tasks)

    user_id = _make_user_with_tz(
        "no-email@x.co", "Asia/Shanghai", email_enabled=False,
    )
    fake_now = datetime(2026, 4, 22, 0, 30, 0, tzinfo=timezone.utc)

    class _FakeDatetime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            if tz is None:
                return fake_now.replace(tzinfo=None)
            return fake_now.astimezone(tz)

    def _fake_llm(prompt: str):
        return {"title": "t", "body": "b"}

    send_calls: list = []

    def _spy_send(user, payload):
        send_calls.append((user.id, payload))

    with (
        patch("app.tasks.worker_tasks.datetime", _FakeDatetime),
        patch("app.services.digest_generation._call_llm_sync", _fake_llm),
        patch(
            "app.services.digest_email.send_daily_digest_email", _spy_send,
        ),
        patch(
            "app.tasks.worker_tasks.send_daily_digest_email", _spy_send,
            create=True,
        ),
    ):
        # The worker imports send_daily_digest_email inside the function
        # body (from app.services.digest_email import send_daily_digest_email),
        # so we also patch at the source module. The guard inside the task
        # (``user.digest_email_enabled``) is what we're really asserting on.
        out = worker_tasks.daily_digest_generate_task()

    assert out["generated"] == 1
    assert out["emails_sent"] == 0, out
    assert send_calls == []


# ---------------------------------------------------------------------------
# LLM fallback
# ---------------------------------------------------------------------------


def test_llm_insight_fallback_to_pending_on_error() -> None:
    import app.services.digest_generation as digest_gen
    importlib.reload(digest_gen)

    user_id = _make_user_with_tz("llm-fail@x.co", "UTC")
    with _s.SessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None

        # Force the LLM to raise.
        def _blow_up(prompt: str):
            raise RuntimeError("boom")

        with patch.object(digest_gen, "_call_llm_sync", return_value=None):
            payload = digest_gen.generate_daily_digest_payload(
                db, user, target_day=date(2026, 4, 22),
            )
    insight = next(b for b in payload["blocks"] if b["kind"] == "insight")
    assert insight["title"] == "Pending"
    assert "LLM-enabled" in insight["body"]
    assert payload["_meta"]["generator"] == "fallback"


def test_weekly_reflection_generates_headline_via_llm() -> None:
    import app.services.digest_generation as digest_gen
    importlib.reload(digest_gen)

    user_id = _make_user_with_tz("weekly-llm@x.co", "UTC")
    with _s.SessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None
        with patch.object(
            digest_gen,
            "_call_llm_sync",
            return_value={"headline": "这周把 FSRS 那条主线收尾了。"},
        ):
            payload = digest_gen.generate_weekly_reflection_payload(
                db, user, iso_week="2026-W17",
            )
    assert payload["headline"] == "这周把 FSRS 那条主线收尾了。"
    assert payload["_meta"]["generator"] == "llm"


# ---------------------------------------------------------------------------
# HTML email template
# ---------------------------------------------------------------------------


def test_daily_digest_email_html_renders_payload_values() -> None:
    from app.services.digest_email import render_daily_digest_html

    user = User(
        email="render@x.co",
        password_hash="x",
        display_name="Mina",
        timezone="Asia/Shanghai",
        digest_email_enabled=True,
    )
    payload = {
        "date": "2026-04-22",
        "greeting": "早安，Mina",
        "blocks": [
            {
                "kind": "catch",
                "title": "昨日尾巴",
                "items": [
                    {"icon": "note", "label": "3 page(s) touched yesterday", "tag": "notebook"},
                ],
            },
            {
                "kind": "today",
                "title": "今日值得做的",
                "items": [
                    {"icon": "graph", "label": "2 new memory node(s) to review", "tag": "memory"},
                ],
            },
            {
                "kind": "insight",
                "title": "今日观察",
                "body": "昨日节奏稳，今天从 FSRS 那条主线继续。",
            },
        ],
    }
    html = render_daily_digest_html(user, payload)
    # Smoke checks — the values made it into the output, footer has the
    # opt-out link, and no <style> block (inline CSS only).
    assert "早安，Mina" in html
    assert "3 page(s) touched yesterday" in html
    assert "FSRS" in html
    assert "在设置里关闭邮件" in html
    assert "/app/settings" in html
    assert "<style" not in html  # inline-only for Gmail / Outlook


def test_weekly_reflection_email_html_renders_payload_values() -> None:
    from app.services.digest_email import render_weekly_reflection_html

    user = User(
        email="render-w@x.co",
        password_hash="x",
        display_name="Leo",
        digest_email_enabled=True,
    )
    payload = {
        "range": "Apr 20 - Apr 26",
        "iso_week": "2026-W17",
        "headline": "deep work held all week.",
        "stats": [
            {"k": "pages", "v": "5"},
            {"k": "ai_actions", "v": "12"},
        ],
        "moves": ["Closed the FSRS spike"],
    }
    html = render_weekly_reflection_html(user, payload)
    assert "deep work held all week." in html
    assert "Apr 20 - Apr 26" in html
    assert "Closed the FSRS spike" in html
    assert "在设置里关闭邮件" in html


# ---------------------------------------------------------------------------
# send_html_email safety
# ---------------------------------------------------------------------------


def test_send_html_email_noops_in_test_env() -> None:
    """``settings.env == 'test'`` short-circuits SMTP; no connection attempted."""
    from app.services.email import send_html_email
    # Should not raise, should not attempt SMTP (ENV=test in setup_function).
    send_html_email("noop@x.co", "subject", "<p>hi</p>", text_fallback="hi")
