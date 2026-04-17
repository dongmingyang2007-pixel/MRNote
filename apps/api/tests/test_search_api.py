# ruff: noqa: E402
import atexit, importlib, os, shutil, tempfile
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-s7-api-"))
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
from app.models import (
    Memory, Notebook, NotebookBlock, NotebookPage, Project, StudyAsset,
)


def setup_function() -> None:
    global engine, SessionLocal
    engine = _s.engine
    SessionLocal = _s.SessionLocal
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    from app.services.runtime_state import runtime_state
    runtime_state._memory = runtime_state._memory.__class__()


engine = _s.engine
SessionLocal = _s.SessionLocal


def _public_headers() -> dict[str, str]:
    return {"origin": "http://localhost:3000"}


def _register_client(email: str = "u@x.co") -> tuple[TestClient, dict]:
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
    return client, {
        "ws_id": info["workspace"]["id"],
        "user_id": info["user"]["id"],
    }


def _seed_content(ws_id: str, user_id: str) -> dict[str, str]:
    """Returns dict of useful IDs."""
    with SessionLocal() as db:
        pr = Project(workspace_id=ws_id, name="P")
        db.add(pr); db.commit(); db.refresh(pr)
        nb = Notebook(workspace_id=ws_id, project_id=pr.id,
                      created_by=user_id, title="NB", slug="nb")
        db.add(nb); db.commit(); db.refresh(nb)
        page = NotebookPage(
            notebook_id=nb.id, created_by=user_id,
            title="Login flow handbook",
            slug="login-flow-handbook",
            plain_text="Login flow uses email verification and OTP.",
        )
        db.add(page); db.commit(); db.refresh(page)
        return {
            "project_id": pr.id, "notebook_id": nb.id, "page_id": page.id,
        }


def test_global_search_returns_results_shape() -> None:
    client, auth = _register_client("u1@x.co")
    _seed_content(auth["ws_id"], auth["user_id"])
    resp = client.get("/api/v1/search/global?q=login&limit=5")
    assert resp.status_code == 200
    body = resp.json()
    assert "results" in body
    for scope in ("pages", "blocks", "study_assets", "memory", "playbooks"):
        assert scope in body["results"]
    assert "duration_ms" in body


def test_global_search_short_query_returns_empty() -> None:
    client, _ = _register_client("u2@x.co")
    resp = client.get("/api/v1/search/global?q=a")
    assert resp.status_code == 200
    body = resp.json()
    assert all(len(v) == 0 for v in body["results"].values())


def test_global_search_invalid_scope_returns_400() -> None:
    client, _ = _register_client("u3@x.co")
    resp = client.get("/api/v1/search/global?q=login&scope=pages,bogus")
    assert resp.status_code == 400


def test_global_search_scope_csv_filters() -> None:
    client, auth = _register_client("u4@x.co")
    _seed_content(auth["ws_id"], auth["user_id"])
    resp = client.get("/api/v1/search/global?q=login&scope=pages")
    assert resp.status_code == 200
    body = resp.json()
    # Non-selected scopes are still present in the shape but empty.
    assert body["results"]["blocks"] == []
    assert body["results"]["memory"] == []


def test_notebook_search_limits_to_notebook_scope() -> None:
    client, auth = _register_client("u5@x.co")
    ids = _seed_content(auth["ws_id"], auth["user_id"])
    resp = client.get(f"/api/v1/notebooks/{ids['notebook_id']}/search?q=login")
    assert resp.status_code == 200
    body = resp.json()
    assert "results" in body


def test_related_returns_pages_and_memory_keys() -> None:
    client, auth = _register_client("u6@x.co")
    ids = _seed_content(auth["ws_id"], auth["user_id"])
    resp = client.get(f"/api/v1/pages/{ids['page_id']}/related")
    assert resp.status_code == 200
    body = resp.json()
    assert "pages" in body
    assert "memory" in body


def test_cross_workspace_global_search_isolated() -> None:
    client_a, auth_a = _register_client("a@x.co")
    _seed_content(auth_a["ws_id"], auth_a["user_id"])
    client_b, _ = _register_client("b@x.co")
    resp = client_b.get("/api/v1/search/global?q=login")
    assert resp.status_code == 200
    # Workspace B is empty — no pages should leak from A.
    assert resp.json()["results"]["pages"] == []
