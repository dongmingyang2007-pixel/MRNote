# ruff: noqa: E402
import atexit
import importlib
import os
import shutil
import tempfile
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-s1-wiring-"))
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
from unittest.mock import patch

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models import (
    AIActionLog, AIUsageEvent,
    Notebook, NotebookPage, Project, User, Workspace,
)
from app.services.dashscope_stream import StreamChunk


def setup_function() -> None:
    # Re-acquire the current engine/SessionLocal — other test modules may
    # reload app.db.session with a different DATABASE_URL at import time.
    import app.db.session as _session_module
    global SessionLocal, engine
    SessionLocal = _session_module.SessionLocal
    engine = _session_module.engine
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    # Reset the in-memory runtime_state backend so rate-limit counters and
    # any stale verify_code entries from a previous test do not leak.
    from app.services.runtime_state import runtime_state
    runtime_state._memory = runtime_state._memory.__class__()  # type: ignore[attr-defined]


def _public_headers() -> dict[str, str]:
    return {"origin": "http://localhost:3000"}


def _verification_code_key(email: str, purpose: str) -> str:
    import hashlib
    raw = f"{email.lower().strip()}:{purpose}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _issue_code(client: TestClient, email: str, purpose: str = "register") -> str:
    from app.services.runtime_state import runtime_state
    resp = client.post(
        "/api/v1/auth/send-code",
        json={"email": email, "purpose": purpose},
        headers=_public_headers(),
    )
    assert resp.status_code == 200
    entry = runtime_state.get_json("verify_code", _verification_code_key(email, purpose))
    assert entry is not None
    return str(entry["code"])


def _register_user(client: TestClient, email: str) -> dict:
    code = _issue_code(client, email, "register")
    resp = client.post(
        "/api/v1/auth/register",
        json={
            "email": email, "password": "pass1234pass",
            "display_name": "Test", "code": code,
        },
        headers=_public_headers(),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _seed_fixture(client: TestClient, email: str = "u@x.co") -> dict:
    info = _register_user(client, email)
    ws_id = info["workspace"]["id"]
    user_id = info["user"]["id"]
    with SessionLocal() as db:
        project = Project(workspace_id=ws_id, name="P")
        db.add(project); db.commit(); db.refresh(project)
        notebook = Notebook(
            workspace_id=ws_id, project_id=project.id, created_by=user_id,
            title="NB", slug="nb",
        )
        db.add(notebook); db.commit(); db.refresh(notebook)
        page = NotebookPage(
            notebook_id=notebook.id, created_by=user_id, title="T", slug="t",
            plain_text="some page text here",
        )
        db.add(page); db.commit(); db.refresh(page)
        return {
            "ws_id": ws_id, "user_id": user_id, "user_email": email,
            "project_id": project.id,
            "notebook_id": notebook.id, "page_id": page.id,
        }


def _finalize_client_auth(client: TestClient, ws_id: str) -> None:
    csrf = client.get("/api/v1/auth/csrf", headers=_public_headers()).json()["csrf_token"]
    client.headers.update({
        "origin": "http://localhost:3000",
        "x-csrf-token": csrf,
        "x-workspace-id": ws_id,
    })


async def _fake_stream(*_a, **_kw):
    yield StreamChunk(content="改写后的文字", finish_reason=None)
    yield StreamChunk(
        content="", finish_reason="stop",
        usage={"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17},
        model_id="qwen-plus",
    )


def test_selection_action_creates_log_and_usage() -> None:
    client = TestClient(main_module.app)
    fx = _seed_fixture(client, email="t1@x.co")
    _finalize_client_auth(client, fx["ws_id"])

    with patch(
        "app.routers.notebook_ai.chat_completion_stream",
        side_effect=lambda *a, **kw: _fake_stream(),
    ):
        resp = client.post(
            "/api/v1/ai/notebook/selection-action",
            json={
                "page_id": fx["page_id"],
                "selected_text": "原文",
                "action_type": "rewrite",
            },
        )
        _ = resp.text   # drain SSE body

    assert resp.status_code == 200
    with SessionLocal() as db:
        logs = db.query(AIActionLog).all()
        assert len(logs) == 1
        log = logs[0]
        assert log.action_type == "selection.rewrite"
        assert log.scope == "selection"
        assert log.status == "completed"
        assert log.page_id == fx["page_id"]

        usages = db.query(AIUsageEvent).filter_by(action_log_id=log.id).all()
        assert len(usages) == 1
        assert usages[0].event_type == "llm_completion"
        assert usages[0].prompt_tokens == 12
        assert usages[0].count_source == "exact"


def test_page_action_creates_log_and_usage() -> None:
    client = TestClient(main_module.app)
    fx = _seed_fixture(client, email="t2@x.co")
    _finalize_client_auth(client, fx["ws_id"])

    with patch(
        "app.routers.notebook_ai.chat_completion_stream",
        side_effect=lambda *a, **kw: _fake_stream(),
    ):
        resp = client.post(
            "/api/v1/ai/notebook/page-action",
            json={"page_id": fx["page_id"], "action_type": "summarize"},
        )
        _ = resp.text

    assert resp.status_code == 200
    with SessionLocal() as db:
        logs = db.query(AIActionLog).all()
        assert len(logs) == 1
        assert logs[0].action_type == "page.summarize"
        assert logs[0].scope == "page"
        assert db.query(AIUsageEvent).count() == 1


async def _fake_assemble_context(*_a, **_kw):
    from app.services.retrieval_orchestration import RetrievalContext, RetrievalSource
    return RetrievalContext(
        system_prompt="SYS",
        sources=[
            RetrievalSource(source_type="memory", source_id="m1", title="M", snippet="s"),
            RetrievalSource(source_type="related_page", source_id="p1", title="P", snippet="s"),
        ],
    )


def test_ask_creates_log_with_retrieval_sources() -> None:
    client = TestClient(main_module.app)
    fx = _seed_fixture(client, email="t3@x.co")
    _finalize_client_auth(client, fx["ws_id"])

    with patch(
        "app.routers.notebook_ai.chat_completion_stream",
        side_effect=lambda *a, **kw: _fake_stream(),
    ), patch(
        "app.services.retrieval_orchestration.assemble_context",
        side_effect=_fake_assemble_context,
    ):
        resp = client.post(
            "/api/v1/ai/notebook/ask",
            json={"page_id": fx["page_id"], "message": "what is X?", "history": []},
        )
        _ = resp.text

    assert resp.status_code == 200
    with SessionLocal() as db:
        log = db.query(AIActionLog).one()
    assert log.action_type == "ask"
    assert log.scope == "notebook"   # related_page present → notebook scope
    sources = log.trace_metadata.get("retrieval_sources") or []
    assert len(sources) == 2
    assert {s["type"] for s in sources} == {"memory", "related_page"}


async def _fake_whiteboard_summary(*_a, **_kw):
    return {"summary": "a sketch of X", "memory_count": 2, "tokens": 42}


def test_whiteboard_summarize_creates_log() -> None:
    client = TestClient(main_module.app)
    fx = _seed_fixture(client, email="t4@x.co")
    _finalize_client_auth(client, fx["ws_id"])

    with patch(
        "app.services.whiteboard_service.extract_whiteboard_memories",
        side_effect=_fake_whiteboard_summary,
    ):
        resp = client.post(
            "/api/v1/ai/notebook/whiteboard-summarize",
            json={"page_id": fx["page_id"], "elements": []},
        )

    assert resp.status_code == 200
    with SessionLocal() as db:
        log = db.query(AIActionLog).one()
    assert log.action_type == "whiteboard.summarize"
    assert log.scope == "selection"
    assert log.status == "completed"
