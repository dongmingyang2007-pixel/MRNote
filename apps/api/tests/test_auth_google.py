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


# ---------------------------------------------------------------------------
# /auth/google/callback
# ---------------------------------------------------------------------------


def _stub_callback(client: TestClient, id_claims: dict, session_overrides: dict):
    """Patch Authlib so the callback hits our branches without a real Google hop.

    Works in two steps:
    1. Hit ``/authorize`` with a patched ``authorize_redirect`` that stashes
       our desired session state; the signed session cookie stays on the
       TestClient for step 2.
    2. Hit ``/callback`` with patched token-exchange + id-token parsing.
    """
    from starlette.responses import Response as StarletteResponse

    async def seed(request, redirect_uri, **kwargs):
        for k, v in session_overrides.items():
            request.session[k] = v
        return StarletteResponse(status_code=204)

    async def fake_token(request, **kwargs):
        return {"access_token": "at", "id_token": "it"}

    async def fake_parse(request, token, **kwargs):
        return id_claims

    previous = settings.google_oauth_enabled
    settings.google_oauth_enabled = True
    try:
        with patch(
            "app.routers.auth.oauth.google.authorize_redirect",
            new=AsyncMock(side_effect=seed),
        ):
            client.get(
                "/api/v1/auth/google/authorize?next=/app",
                headers=public_headers(),
                follow_redirects=False,
            )
        with patch(
            "app.routers.auth.oauth.google.authorize_access_token",
            new=AsyncMock(side_effect=fake_token),
        ), patch(
            "app.routers.auth.oauth.google.parse_id_token",
            new=AsyncMock(side_effect=fake_parse),
        ):
            return client.get(
                "/api/v1/auth/google/callback?code=X&state=Y",
                headers=public_headers(),
                follow_redirects=False,
            )
    finally:
        settings.google_oauth_enabled = previous


def test_callback_creates_new_user(client: TestClient):
    from sqlalchemy import select

    from app.models import OAuthIdentity, User

    resp = _stub_callback(
        client,
        id_claims={
            "sub": "109876",
            "email": "new@gmail.com",
            "email_verified": True,
            "name": "New User",
        },
        session_overrides={"oauth_mode": "signin", "oauth_next": "/app"},
    )
    assert resp.status_code == 302
    assert resp.headers["location"] == "/app"
    # The redirect MUST carry Set-Cookie for access_token — otherwise the
    # browser ends up on /app unauthenticated and gets bounced back to /login.
    cookie_headers = resp.headers.get_list("set-cookie")
    assert any(
        h.startswith(f"{settings.access_cookie_name}=") for h in cookie_headers
    ), f"access_token cookie missing from callback redirect: {cookie_headers}"
    with SessionLocal() as db:
        user = db.execute(select(User).where(User.email == "new@gmail.com")).scalar_one()
        assert user.password_hash is None
        ident = db.execute(
            select(OAuthIdentity).where(OAuthIdentity.user_id == user.id)
        ).scalar_one()
        assert ident.provider == "google"
        assert ident.provider_id == "109876"


def test_callback_auto_links_existing_email(client: TestClient):
    from sqlalchemy import select

    from app.models import OAuthIdentity, User, Workspace, Membership

    with SessionLocal() as db:
        existing = User(email="exists@gmail.com", password_hash="hashed")
        ws = Workspace(name="exists Workspace", plan="free")
        db.add(existing)
        db.add(ws)
        db.flush()
        db.add(Membership(workspace_id=ws.id, user_id=existing.id, role="owner"))
        db.commit()
        existing_id = existing.id

    resp = _stub_callback(
        client,
        id_claims={
            "sub": "200",
            "email": "exists@gmail.com",
            "email_verified": True,
            "name": "X",
        },
        session_overrides={"oauth_mode": "signin", "oauth_next": "/app"},
    )
    assert resp.status_code == 302
    with SessionLocal() as db:
        ident = db.execute(
            select(OAuthIdentity).where(OAuthIdentity.user_id == existing_id)
        ).scalar_one()
        assert ident.provider_id == "200"
        users = db.execute(
            select(User).where(User.email == "exists@gmail.com")
        ).scalars().all()
        assert len(users) == 1


def test_callback_rejects_unverified_email(client: TestClient):
    resp = _stub_callback(
        client,
        id_claims={
            "sub": "300",
            "email": "x@y.com",
            "email_verified": False,
            "name": "X",
        },
        session_overrides={"oauth_mode": "signin", "oauth_next": "/app"},
    )
    assert resp.status_code == 302
    assert "error=google_email_unverified" in resp.headers["location"]


def test_callback_existing_oauth_signs_in(client: TestClient):
    from app.models import OAuthIdentity, User, Workspace, Membership

    with SessionLocal() as db:
        u = User(email="linked@gmail.com", password_hash=None)
        ws = Workspace(name="linked Workspace", plan="free")
        db.add(u)
        db.add(ws)
        db.flush()
        db.add(Membership(workspace_id=ws.id, user_id=u.id, role="owner"))
        db.add(OAuthIdentity(
            user_id=u.id, provider="google", provider_id="400",
            provider_email="linked@gmail.com",
        ))
        db.commit()

    resp = _stub_callback(
        client,
        id_claims={
            "sub": "400",
            "email": "new-email@gmail.com",
            "email_verified": True,
            "name": "X",
        },  # user changed their Google email
        session_overrides={"oauth_mode": "signin", "oauth_next": "/app"},
    )
    assert resp.status_code == 302
    assert resp.headers["location"] == "/app"


# ---------------------------------------------------------------------------
# /auth/identities + /auth/google/disconnect + /auth/password
# ---------------------------------------------------------------------------


def _login_existing_user(client: TestClient, user_id: str) -> dict[str, str]:
    """Seed TestClient cookies + CSRF so authenticated requests just work.

    Returns headers including `x-csrf-token` and `origin` for CSRF-protected
    endpoints.
    """
    from app.core.security import create_access_token

    token = create_access_token(user_id)
    client.cookies.set(settings.access_cookie_name, token)
    resp = client.get("/api/v1/auth/csrf", headers=public_headers())
    assert resp.status_code == 200, resp.text
    csrf = resp.json()["csrf_token"]
    return {"origin": ORIGIN, "x-csrf-token": csrf}


def test_identities_returns_linked_accounts(client: TestClient):
    from app.models import OAuthIdentity, User

    with SessionLocal() as db:
        u = User(email="u@x.com", password_hash="p")
        db.add(u)
        db.flush()
        db.add(OAuthIdentity(
            user_id=u.id, provider="google",
            provider_id="9001", provider_email="u@x.com",
        ))
        db.commit()
        uid = u.id

    _login_existing_user(client, uid)
    resp = client.get("/api/v1/auth/identities", headers=public_headers())
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data) == 1
    assert data[0]["provider"] == "google"
    assert data[0]["provider_email"] == "u@x.com"


def test_disconnect_blocks_user_without_password(client: TestClient):
    from app.models import OAuthIdentity, User

    with SessionLocal() as db:
        u = User(email="oauth-only@x.com", password_hash=None)
        db.add(u)
        db.flush()
        db.add(OAuthIdentity(
            user_id=u.id, provider="google",
            provider_id="9002", provider_email="oauth-only@x.com",
        ))
        db.commit()
        uid = u.id

    auth_headers = _login_existing_user(client, uid)
    resp = client.post(
        "/api/v1/auth/google/disconnect",
        headers=auth_headers,
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error"]["code"] == "password_required"


def test_disconnect_succeeds_when_user_has_password(client: TestClient):
    from sqlalchemy import select

    from app.models import OAuthIdentity, User

    with SessionLocal() as db:
        u = User(email="both@x.com", password_hash="hashed")
        db.add(u)
        db.flush()
        db.add(OAuthIdentity(
            user_id=u.id, provider="google",
            provider_id="9003", provider_email="both@x.com",
        ))
        db.commit()
        uid = u.id

    auth_headers = _login_existing_user(client, uid)
    resp = client.post("/api/v1/auth/google/disconnect", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    with SessionLocal() as db:
        remaining = db.execute(
            select(OAuthIdentity).where(OAuthIdentity.user_id == uid)
        ).scalars().all()
        assert remaining == []


def test_set_password_for_oauth_only_user(client: TestClient):
    from app.models import User

    with SessionLocal() as db:
        u = User(email="no-pw@x.com", password_hash=None)
        db.add(u)
        db.commit()
        uid = u.id

    auth_headers = _login_existing_user(client, uid)
    resp = client.put(
        "/api/v1/auth/password",
        json={"new_password": "NewStrongPass123"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    with SessionLocal() as db:
        u = db.get(User, uid)
        assert u.password_hash is not None


def test_change_password_requires_current_when_one_exists(client: TestClient):
    from app.core.security import hash_password
    from app.models import User

    with SessionLocal() as db:
        u = User(email="has-pw@x.com", password_hash=hash_password("CurrentPass123"))
        db.add(u)
        db.commit()
        uid = u.id

    auth_headers = _login_existing_user(client, uid)

    # Missing current_password → 400
    resp = client.put(
        "/api/v1/auth/password",
        json={"new_password": "NewPass123"},
        headers=auth_headers,
    )
    assert resp.status_code == 400

    # Wrong current_password → 400
    resp = client.put(
        "/api/v1/auth/password",
        json={"new_password": "NewPass123", "current_password": "Wrong"},
        headers=auth_headers,
    )
    assert resp.status_code == 400

    # Correct → 200
    resp = client.put(
        "/api/v1/auth/password",
        json={"new_password": "NewPass123", "current_password": "CurrentPass123"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
