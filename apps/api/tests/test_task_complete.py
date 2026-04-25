# ruff: noqa: E402
import atexit, importlib, os, shutil, tempfile
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="mrnote-s2-task-"))
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
    AIActionLog, Notebook, NotebookPage, Project, User, Workspace,
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
    csrf = client.get("/api/v1/auth/csrf", headers=_public_headers()).json()["csrf_token"]
    client.headers.update({
        "origin": "http://localhost:3000",
        "x-csrf-token": csrf,
        "x-workspace-id": info["workspace"]["id"],
    })
    return client, {"ws_id": info["workspace"]["id"], "user_id": info["user"]["id"]}


def _seed_page(ws_id: str, user_id: str) -> str:
    with SessionLocal() as db:
        pr = Project(workspace_id=ws_id, name="P"); db.add(pr); db.commit(); db.refresh(pr)
        nb = Notebook(workspace_id=ws_id, project_id=pr.id, created_by=user_id,
                      title="NB", slug="nb")
        db.add(nb); db.commit(); db.refresh(nb)
        pg = NotebookPage(notebook_id=nb.id, created_by=user_id, title="T",
                          slug="t", plain_text="x")
        db.add(pg); db.commit(); db.refresh(pg)
        return pg.id


def test_task_complete_creates_action_log() -> None:
    client, auth = _register_client("t1@x.co")
    page_id = _seed_page(auth["ws_id"], auth["user_id"])
    block_id = "11111111-2222-3333-4444-555555555555"

    resp = client.post(
        f"/api/v1/pages/{page_id}/tasks/{block_id}/complete",
        json={"completed": True, "completed_at": "2026-04-16T12:00:00+00:00"},
    )
    assert resp.status_code == 200

    with SessionLocal() as db:
        log = db.query(AIActionLog).one()
    assert log.action_type == "task.complete"
    assert log.block_id == block_id
    assert log.page_id == page_id
    assert log.input_json["completed"] is True


def test_task_reopen_uses_reopen_action_type() -> None:
    client, auth = _register_client("t2@x.co")
    page_id = _seed_page(auth["ws_id"], auth["user_id"])
    block_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    resp = client.post(
        f"/api/v1/pages/{page_id}/tasks/{block_id}/complete",
        json={"completed": False, "completed_at": None},
    )
    assert resp.status_code == 200

    with SessionLocal() as db:
        log = db.query(AIActionLog).one()
    assert log.action_type == "task.reopen"
    assert log.input_json["completed"] is False


def test_task_cross_workspace_404() -> None:
    _client_a, auth_a = _register_client("a@x.co")
    page_id = _seed_page(auth_a["ws_id"], auth_a["user_id"])

    client_b, _ = _register_client("b@x.co")
    resp = client_b.post(
        f"/api/v1/pages/{page_id}/tasks/xxx/complete",
        json={"completed": True},
    )
    assert resp.status_code == 404
