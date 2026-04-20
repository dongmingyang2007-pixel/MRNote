# ruff: noqa: E402
"""Tests for Google OAuth routes.

Uses the same SQLite test harness as ``test_api_integration`` so that the
Starlette ``SessionMiddleware`` + auth router interact against a real app
instance.
"""

import atexit
import importlib
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-api-oauth-tests-"))
atexit.register(lambda: shutil.rmtree(TEST_TEMP_DIR, ignore_errors=True))

DB_PATH = TEST_TEMP_DIR / "test_oauth.db"
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
os.environ["ENV"] = "test"
os.environ["COOKIE_DOMAIN"] = ""
os.environ["OAUTH_SESSION_SECRET"] = "test-oauth-secret-minimum-length-32-chars"
os.environ["GOOGLE_CLIENT_ID"] = "test-google-client-id.apps.googleusercontent.com"
os.environ["GOOGLE_CLIENT_SECRET"] = "test-google-client-secret"

import app.core.config as config_module

config_module.get_settings.cache_clear()
config_module.settings = config_module.get_settings()

import app.db.session as session_module

importlib.reload(session_module)

import app.main as main_module

importlib.reload(main_module)

from app.core.config import settings
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.services.model_catalog_seed import seed_model_catalog
from app.services.runtime_state import runtime_state


ORIGIN = "http://localhost:3000"


def setup_function() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_model_catalog(db)
    with runtime_state._memory._lock:
        runtime_state._memory._data.clear()


def public_headers() -> dict[str, str]:
    return {"origin": ORIGIN}


@pytest.fixture
def client() -> TestClient:
    return TestClient(main_module.app)


@pytest.fixture
def oauth_enabled():
    previous = settings.google_oauth_enabled
    settings.google_oauth_enabled = True
    try:
        yield
    finally:
        settings.google_oauth_enabled = previous


# ---------------------------------------------------------------------------
# /auth/google/authorize
# ---------------------------------------------------------------------------


def test_authorize_redirects_to_google(client: TestClient, oauth_enabled):
    from starlette.responses import RedirectResponse

    async def fake_redirect(request, redirect_uri, **kwargs):
        # Authlib normally stashes state/nonce in request.session; we don't
        # need to replicate that for the route unit test — just prove we
        # reached it and got a 302 to Google.
        return RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth?state=abc")

    with patch(
        "app.routers.auth.oauth.google.authorize_redirect",
        new=AsyncMock(side_effect=fake_redirect),
    ):
        resp = client.get(
            "/api/v1/auth/google/authorize?next=/app/notebooks",
            headers=public_headers(),
            follow_redirects=False,
        )
    assert resp.status_code in (302, 307)
    assert "accounts.google.com" in resp.headers.get("location", "")


def test_authorize_404_when_flag_off(client: TestClient):
    # Explicitly off (setup_function does not touch the flag)
    previous = settings.google_oauth_enabled
    settings.google_oauth_enabled = False
    try:
        resp = client.get(
            "/api/v1/auth/google/authorize?next=/app",
            headers=public_headers(),
            follow_redirects=False,
        )
    finally:
        settings.google_oauth_enabled = previous
    assert resp.status_code == 404


def test_authorize_rejects_unsafe_next(client: TestClient, oauth_enabled):
    from starlette.responses import RedirectResponse

    captured: dict[str, str | None] = {}

    async def capture(request, redirect_uri, **kwargs):
        captured["next"] = request.session.get("oauth_next")
        captured["mode"] = request.session.get("oauth_mode")
        return RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth?state=abc")

    with patch(
        "app.routers.auth.oauth.google.authorize_redirect",
        new=AsyncMock(side_effect=capture),
    ):
        client.get(
            "/api/v1/auth/google/authorize?next=https://evil.com",
            headers=public_headers(),
            follow_redirects=False,
        )
    # Unsafe next URL should be replaced with the safe default
    assert captured["next"] == "/app"
    assert captured["mode"] == "signin"


def test_authorize_connect_mode_without_login_redirects_to_login(
    client: TestClient, oauth_enabled
):
    resp = client.get(
        "/api/v1/auth/google/authorize?mode=connect",
        headers=public_headers(),
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/login" in resp.headers.get("location", "")
    assert "auth_required" in resp.headers.get("location", "")
