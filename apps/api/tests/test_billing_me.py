# ruff: noqa: E402
import atexit, importlib, os, shutil, tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="mrnote-s6-me-"))
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

from app.db.base import Base
import app.db.session as _s


def setup_function() -> None:
    Base.metadata.drop_all(bind=_s.engine)
    Base.metadata.create_all(bind=_s.engine)
    from app.services.runtime_state import runtime_state
    runtime_state._memory = runtime_state._memory.__class__()


def _public_headers() -> dict[str, str]:
    return {"origin": "http://localhost:3000"}


def _register_client(email: str = "u@x.co") -> tuple[TestClient, dict]:
    import hashlib
    from app.services.runtime_state import runtime_state
    client = TestClient(main_module.app)
    client.post("/api/v1/auth/send-code",
                json={"email": email, "purpose": "register"},
                headers=_public_headers())
    raw = f"{email.lower().strip()}:register"
    code_key = hashlib.sha256(raw.encode()).hexdigest()
    code = str(runtime_state.get_json("verify_code", code_key)["code"])
    info = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "pass1234pass",
              "display_name": "Test", "code": code},
        headers=_public_headers(),
    ).json()
    csrf = client.get("/api/v1/auth/csrf",
                     headers=_public_headers()).json()["csrf_token"]
    client.headers.update({
        "origin": "http://localhost:3000",
        "x-csrf-token": csrf,
        "x-workspace-id": info["workspace"]["id"],
    })
    return client, {"ws_id": info["workspace"]["id"]}


def test_me_default_returns_free_plan() -> None:
    client, _ = _register_client("me1@x.co")
    resp = client.get("/api/v1/billing/me")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["plan"] == "free"
    assert body["entitlements"]["voice.enabled"] is False
    assert body["entitlements"]["notebooks.max"] == 1
    assert "ai.actions" in body["usage_this_month"]


def test_me_returns_pro_plan_when_active() -> None:
    client, auth = _register_client("me2@x.co")
    from app.models import Subscription
    with _s.SessionLocal() as db:
        db.add(Subscription(
            workspace_id=auth["ws_id"], plan="pro",
            billing_cycle="monthly", status="active",
            provider="stripe_recurring",
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
        ))
        db.commit()
    resp = client.get("/api/v1/billing/me")
    body = resp.json()
    assert body["plan"] == "pro"
    assert body["entitlements"]["voice.enabled"] is True


def test_plans_returns_four_descriptors() -> None:
    client, _ = _register_client("p1@x.co")
    resp = client.get("/api/v1/billing/plans")
    body = resp.json()
    assert "plans" in body
    assert {p["id"] for p in body["plans"]} == {"free", "pro", "power", "team"}
