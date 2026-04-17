# ruff: noqa: E402
import atexit, importlib, os, shutil, tempfile
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-s6-quota-"))
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


def _public() -> dict[str, str]:
    return {"origin": "http://localhost:3000"}


def _register_client(email: str = "u@x.co") -> tuple[TestClient, dict]:
    import hashlib
    from app.services.runtime_state import runtime_state
    client = TestClient(main_module.app)
    client.post("/api/v1/auth/send-code",
                json={"email": email, "purpose": "register"},
                headers=_public())
    raw = f"{email.lower().strip()}:register"
    code_key = hashlib.sha256(raw.encode()).hexdigest()
    code = str(runtime_state.get_json("verify_code", code_key)["code"])
    info = client.post("/api/v1/auth/register",
                       json={"email": email, "password": "pass1234pass",
                             "display_name": "Test", "code": code},
                       headers=_public()).json()
    csrf = client.get("/api/v1/auth/csrf",
                     headers=_public()).json()["csrf_token"]
    client.headers.update({"origin": "http://localhost:3000",
                          "x-csrf-token": csrf,
                          "x-workspace-id": info["workspace"]["id"]})
    return client, {"ws_id": info["workspace"]["id"]}


def test_free_plan_notebooks_max_blocks_second_create() -> None:
    """Free plan allows 1 notebook; second POST returns 402."""
    client, _ = _register_client("nb1@x.co")
    r1 = client.post("/api/v1/notebooks", json={"title": "First"})
    assert r1.status_code in (200, 201), r1.text
    r2 = client.post("/api/v1/notebooks", json={"title": "Second"})
    assert r2.status_code == 402, r2.text
    body = r2.json()
    # Errors are wrapped under "error"; tolerate "detail" too.
    code = body.get("error", {}).get("code") or body.get("code")
    assert code == "plan_limit_reached", body


def test_me_reflects_free_entitlements_after_gates_in_place() -> None:
    """Sanity: /me still works with gates active (free workspace)."""
    client, _ = _register_client("me-after-gate@x.co")
    me = client.get("/api/v1/billing/me").json()
    assert me["entitlements"]["voice.enabled"] is False
    assert me["entitlements"]["notebooks.max"] == 1
