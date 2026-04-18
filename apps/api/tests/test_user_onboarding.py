# ruff: noqa: E402
"""Tests for POST /api/v1/auth/onboarding/complete."""

import atexit
import importlib
import os
import shutil
import tempfile
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-onboarding-"))
atexit.register(lambda: shutil.rmtree(TEST_TEMP_DIR, ignore_errors=True))
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_TEMP_DIR / 'test.db'}"
os.environ["ENV"] = "test"
os.environ["COOKIE_DOMAIN"] = ""
os.environ["DEMO_MODE"] = "true"

import app.core.config as config_module
config_module.get_settings.cache_clear()
config_module.settings = config_module.get_settings()
import app.db.session as session_module
importlib.reload(session_module)
import app.main as main_module
importlib.reload(main_module)

from fastapi.testclient import TestClient

from app.db.base import Base
import app.db.session as _s
from app.models import User


def setup_function() -> None:
    Base.metadata.drop_all(bind=_s.engine)
    Base.metadata.create_all(bind=_s.engine)
    from app.services.runtime_state import runtime_state
    runtime_state._memory = runtime_state._memory.__class__()


def _public_headers() -> dict[str, str]:
    return {"origin": "http://localhost:3000"}


def _register_client(email: str = "onboarding@x.co") -> tuple[TestClient, dict]:
    import hashlib
    from app.services.runtime_state import runtime_state
    client = TestClient(main_module.app)
    client.post(
        "/api/v1/auth/send-code",
        json={"email": email, "purpose": "register"},
        headers=_public_headers(),
    )
    raw = f"{email.lower().strip()}:register"
    code_key = hashlib.sha256(raw.encode()).hexdigest()
    code = str(runtime_state.get_json("verify_code", code_key)["code"])
    info = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "pass1234pass",
            "display_name": "Test",
            "code": code,
        },
        headers=_public_headers(),
    ).json()
    csrf = client.get(
        "/api/v1/auth/csrf", headers=_public_headers(),
    ).json()["csrf_token"]
    client.headers.update({
        "origin": "http://localhost:3000",
        "x-csrf-token": csrf,
        "x-workspace-id": info["workspace"]["id"],
    })
    return client, {
        "ws_id": info["workspace"]["id"],
        "user_id": info["user"]["id"],
    }


def test_complete_onboarding_sets_timestamp() -> None:
    client, info = _register_client("t1@x.co")
    resp = client.post("/api/v1/auth/onboarding/complete", json={})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["onboarding_completed_at"] is not None

    with _s.SessionLocal() as db:
        user = db.query(User).filter(User.id == info["user_id"]).first()
        assert user is not None
        assert user.onboarding_completed_at is not None


def test_complete_onboarding_idempotent() -> None:
    client, info = _register_client("t2@x.co")
    r1 = client.post("/api/v1/auth/onboarding/complete", json={})
    assert r1.status_code == 200, r1.text
    first_ts = r1.json()["onboarding_completed_at"]
    assert first_ts is not None

    r2 = client.post("/api/v1/auth/onboarding/complete", json={})
    assert r2.status_code == 200, r2.text
    second_ts = r2.json()["onboarding_completed_at"]
    # Timestamp preserved (not updated) on second call.
    assert second_ts == first_ts

    with _s.SessionLocal() as db:
        user = db.query(User).filter(User.id == info["user_id"]).first()
        assert user is not None
        # DB value unchanged
        assert user.onboarding_completed_at.isoformat() == first_ts
