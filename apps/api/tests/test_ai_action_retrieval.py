# ruff: noqa: E402
import atexit
import importlib
import os
import shutil
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-s1-retrieval-"))
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
    AIActionLog, AIUsageEvent, Membership, Notebook, NotebookPage,
    Project, User, Workspace,
)


def setup_function() -> None:
    # Re-bind module-level engine/SessionLocal in case another test module
    # reloaded the session module after this one was imported.
    global engine, SessionLocal
    engine = _s.engine
    SessionLocal = _s.SessionLocal
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


# Initial values; setup_function will keep these fresh.
engine = _s.engine
SessionLocal = _s.SessionLocal


def _public_headers() -> dict[str, str]:
    return {"origin": "http://localhost:3000"}


def _verification_code_key(email: str, purpose: str) -> str:
    import hashlib
    raw = f"{email.lower().strip()}:{purpose}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _register_client(email: str = "u@x.co") -> tuple[TestClient, dict]:
    from app.services.runtime_state import runtime_state
    client = TestClient(main_module.app)
    client.post(
        "/api/v1/auth/send-code",
        json={"email": email, "purpose": "register"},
        headers=_public_headers(),
    )
    entry = runtime_state.get_json("verify_code", _verification_code_key(email, "register"))
    code = str(entry["code"])
    resp = client.post(
        "/api/v1/auth/register",
        json={
            "email": email, "password": "pass1234pass",
            "display_name": "Test", "code": code,
        },
        headers=_public_headers(),
    )
    assert resp.status_code == 200, resp.text
    info = resp.json()
    csrf = client.get("/api/v1/auth/csrf", headers=_public_headers()).json()["csrf_token"]
    client.headers.update({
        "origin": "http://localhost:3000",
        "x-csrf-token": csrf,
        "x-workspace-id": info["workspace"]["id"],
    })
    return client, {"ws_id": info["workspace"]["id"], "user_id": info["user"]["id"]}


def _seed_n_logs(n: int, email: str = "u@x.co") -> tuple[TestClient, dict]:
    client, auth = _register_client(email)
    ws_id, user_id = auth["ws_id"], auth["user_id"]
    with SessionLocal() as db:
        project = Project(workspace_id=ws_id, name="P")
        db.add(project); db.commit(); db.refresh(project)
        notebook = Notebook(workspace_id=ws_id, project_id=project.id,
                            created_by=user_id, title="NB", slug="nb")
        db.add(notebook); db.commit(); db.refresh(notebook)
        page = NotebookPage(notebook_id=notebook.id, created_by=user_id,
                            title="T", slug="t", plain_text="x")
        db.add(page); db.commit(); db.refresh(page)
        page_id = page.id
        notebook_id = notebook.id

        base = datetime.now(timezone.utc)
        for i in range(n):
            log = AIActionLog(
                workspace_id=ws_id, user_id=user_id,
                notebook_id=notebook_id, page_id=page_id,
                action_type="selection.rewrite", scope="selection",
                status="completed", duration_ms=100 + i,
                output_summary=f"out {i}", trace_metadata={},
                created_at=base - timedelta(seconds=i),
            )
            db.add(log); db.commit(); db.refresh(log)
            db.add(AIUsageEvent(
                workspace_id=ws_id, user_id=user_id, action_log_id=log.id,
                event_type="llm_completion", prompt_tokens=5, completion_tokens=5,
                total_tokens=10, count_source="exact", meta_json={},
            ))
        db.commit()
    return client, {"ws_id": ws_id, "user_id": user_id, "page_id": page_id}


def test_list_returns_page_logs_paginated() -> None:
    client, fx = _seed_n_logs(60)
    resp = client.get(f"/api/v1/pages/{fx['page_id']}/ai-actions?limit=50")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 50
    assert body["next_cursor"] is not None
    assert body["items"][0]["usage"]["total_tokens"] == 10


def test_list_second_page_does_not_overlap() -> None:
    client, fx = _seed_n_logs(60, email="u2@x.co")
    first = client.get(f"/api/v1/pages/{fx['page_id']}/ai-actions?limit=30").json()
    cursor = first["next_cursor"]
    second = client.get(
        f"/api/v1/pages/{fx['page_id']}/ai-actions?limit=30&cursor={cursor}"
    ).json()
    first_ids = {i["id"] for i in first["items"]}
    second_ids = {i["id"] for i in second["items"]}
    assert first_ids.isdisjoint(second_ids)
