# ruff: noqa: E402
"""Regression tests for C1 (chat quota + usage ledger) and C3 (TOCTOU lock).

C1 ensures every LLM-touching chat endpoint enforces ai.actions.monthly and
(where applicable) voice.enabled, and writes an AIUsageEvent so the counter
actually advances. Without these, Free users could call paid models forever
while the counter read 0.

C3 ensures counted-quota checks serialize on the Workspace row so concurrent
creators can't both observe current<limit and both insert.
"""
import atexit
import hashlib
import importlib
import io
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-c1c3-"))
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

import app.core.entitlements as entitlements_module
import app.routers.chat as chat_router
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models import AIActionLog, AIUsageEvent, Subscription, User
from app.services.runtime_state import runtime_state


def setup_function() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    runtime_state._memory = runtime_state._memory.__class__()


def _public() -> dict[str, str]:
    return {"origin": "http://localhost:3000"}


def _register(email: str = "u@x.co") -> tuple[TestClient, str]:
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
    client.headers.update({
        "origin": "http://localhost:3000",
        "x-csrf-token": csrf,
        "x-workspace-id": ws_id,
    })
    return client, ws_id


def _upgrade(workspace_id: str, plan: str = "pro") -> None:
    """Give the workspace an active Pro (or higher) subscription."""
    from app.core.entitlements import refresh_workspace_entitlements
    with SessionLocal() as db:
        db.add(Subscription(
            workspace_id=workspace_id,
            plan=plan, status="active",
            provider="free", billing_cycle="monthly",
        ))
        db.commit()
        refresh_workspace_entitlements(db, workspace_id=workspace_id)


def _make_conversation(client: TestClient) -> str:
    project = client.post(
        "/api/v1/projects",
        json={"name": "Proj", "description": "x", "default_chat_mode": "standard"},
    ).json()
    conv = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "T"},
    ).json()
    return conv["id"]


def _fill_ai_quota(workspace_id: str, n: int) -> None:
    """Insert n AIUsageEvent rows in the current calendar month so
    count_ai_actions_this_month() returns >= n."""
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        user_id = db.query(User.id).first()[0]
        log = AIActionLog(
            workspace_id=workspace_id,
            user_id=user_id,
            action_type="test",
            scope="project",
            status="completed",
        )
        db.add(log)
        db.commit()
        db.refresh(log)
        for _ in range(n):
            db.add(AIUsageEvent(
                workspace_id=workspace_id,
                user_id=user_id,
                action_log_id=log.id,
                event_type="test",
                count_source="exact",
                created_at=now,
            ))
        db.commit()


# ---------------------------------------------------------------------------
# C1: ai.actions.monthly gate on chat endpoints
# ---------------------------------------------------------------------------

def test_chat_messages_blocked_when_ai_actions_quota_exhausted() -> None:
    """A Free workspace at its 50 ai.actions.monthly cap gets 402 on /messages.

    Before the C1 fix, chat endpoints had no entitlement gate at all, so a
    free user could chat unlimited times.
    """
    client, ws_id = _register("c1-msg@x.co")
    conv_id = _make_conversation(client)
    _fill_ai_quota(ws_id, 50)  # Free cap = 50

    resp = client.post(
        f"/api/v1/chat/conversations/{conv_id}/messages",
        json={"content": "hi"},
    )
    assert resp.status_code == 402, resp.text
    body = resp.json()
    code = body.get("error", {}).get("code") or body.get("code")
    assert code == "plan_limit_reached", body


def test_chat_stream_blocked_when_ai_actions_quota_exhausted() -> None:
    client, ws_id = _register("c1-stream@x.co")
    conv_id = _make_conversation(client)
    _fill_ai_quota(ws_id, 50)

    resp = client.post(
        f"/api/v1/chat/conversations/{conv_id}/stream",
        json={"content": "hi"},
    )
    assert resp.status_code == 402, resp.text
    code = resp.json().get("error", {}).get("code")
    assert code == "plan_limit_reached"


def test_chat_image_blocked_when_ai_actions_quota_exhausted() -> None:
    client, ws_id = _register("c1-image@x.co")
    conv_id = _make_conversation(client)
    _fill_ai_quota(ws_id, 50)

    resp = client.post(
        f"/api/v1/chat/conversations/{conv_id}/image",
        data={"prompt": "describe"},
        files={"image": ("x.png", io.BytesIO(b"\x89PNG\r\n\x1a\n"), "image/png")},
    )
    assert resp.status_code == 402, resp.text
    code = resp.json().get("error", {}).get("code")
    assert code == "plan_limit_reached"


# ---------------------------------------------------------------------------
# C1: voice.enabled gate on voice/dictate/speech
# ---------------------------------------------------------------------------

def test_chat_voice_blocked_on_free_plan() -> None:
    """Free plan has voice.enabled=False. /voice must 402 before reaching ASR."""
    client, _ = _register("c1-voice@x.co")
    conv_id = _make_conversation(client)
    resp = client.post(
        f"/api/v1/chat/conversations/{conv_id}/voice",
        files={"audio": ("r.webm", io.BytesIO(b"\x00\x00"), "audio/webm")},
    )
    assert resp.status_code == 402, resp.text
    code = resp.json().get("error", {}).get("code")
    assert code == "plan_required"


def test_chat_dictate_blocked_on_free_plan() -> None:
    client, _ = _register("c1-dictate@x.co")
    conv_id = _make_conversation(client)
    resp = client.post(
        f"/api/v1/chat/conversations/{conv_id}/dictate",
        files={"audio": ("r.webm", io.BytesIO(b"\x00\x00"), "audio/webm")},
    )
    assert resp.status_code == 402, resp.text
    assert resp.json().get("error", {}).get("code") == "plan_required"


def test_chat_speech_blocked_on_free_plan() -> None:
    client, _ = _register("c1-speech@x.co")
    conv_id = _make_conversation(client)
    resp = client.post(
        f"/api/v1/chat/conversations/{conv_id}/speech",
        json={"content": "hello"},
    )
    assert resp.status_code == 402, resp.text
    assert resp.json().get("error", {}).get("code") == "plan_required"


def test_chat_voice_passes_gate_on_pro_plan(monkeypatch) -> None:
    """Pro has voice.enabled=True. /voice should pass the gates and reach
    downstream code (which may fail for other reasons, but not with 402)."""
    client, ws_id = _register("c1-voice-pro@x.co")
    conv_id = _make_conversation(client)
    _upgrade(ws_id, "pro")

    # Stub downstream so we don't actually hit dashscope
    monkeypatch.setattr(chat_router.settings, "dashscope_api_key", "test-key")

    async def _fake_voice_pipeline(*args, **kwargs):
        return {
            "text_input": "hello",
            "text_response": "hi there",
            "audio_response": None,
            "reasoning_content": None,
            "sources": [],
            "retrieval_trace": {},
        }
    monkeypatch.setattr(chat_router, "orchestrate_voice_inference", _fake_voice_pipeline)

    resp = client.post(
        f"/api/v1/chat/conversations/{conv_id}/voice",
        files={"audio": ("r.webm", io.BytesIO(b"\x00\x00" * 16), "audio/webm")},
    )
    # Not a 402 plan_required / plan_limit_reached; exact status depends on
    # upload-validation, but the gate itself is cleared.
    assert resp.status_code != 402, resp.text


# ---------------------------------------------------------------------------
# C1: usage event is written on success so the counter advances
# ---------------------------------------------------------------------------

def test_chat_messages_writes_ai_usage_event_on_success(monkeypatch) -> None:
    """After a successful /messages call, an AIUsageEvent row must exist so
    count_ai_actions_this_month() increments. Without this, the gate is
    self-defeating (counter stays 0 forever)."""
    client, ws_id = _register("c1-usage@x.co")
    conv_id = _make_conversation(client)
    _upgrade(ws_id, "pro")

    monkeypatch.setattr(chat_router.settings, "dashscope_api_key", "test-key")

    async def _fake_inference(*args, **kwargs):
        return "stub reply"
    monkeypatch.setattr(chat_router, "orchestrate_inference", _fake_inference)

    before = _ai_usage_count(ws_id)
    resp = client.post(
        f"/api/v1/chat/conversations/{conv_id}/messages",
        json={"content": "hello"},
    )
    assert resp.status_code == 200, resp.text
    after = _ai_usage_count(ws_id)
    assert after == before + 1


def _ai_usage_count(workspace_id: str) -> int:
    with SessionLocal() as db:
        return db.query(AIUsageEvent).filter(
            AIUsageEvent.workspace_id == workspace_id
        ).count()


# ---------------------------------------------------------------------------
# C3: counted quota check serializes via Workspace row lock
# ---------------------------------------------------------------------------

def test_counted_quota_gate_acquires_workspace_row_lock(monkeypatch) -> None:
    """The require_entitlement counter path must SELECT ... FOR UPDATE on
    Workspace before reading the counter, so concurrent creators serialize.

    We spy on with_for_update() to confirm it's invoked during a counted
    quota check. (SQLite silently ignores it; Postgres acquires a row lock
    held until transaction commit.)"""
    client, _ = _register("c3-lock@x.co")

    called: list[bool] = []
    original = entitlements_module.Workspace

    from sqlalchemy.orm import Query as _Query
    orig_for_update = _Query.with_for_update

    def spy(self, *args, **kwargs):  # type: ignore[no-redef]
        # Only record calls in the entitlement path; heuristic: the query
        # targets the Workspace entity.
        descs = getattr(self, "column_descriptions", [])
        if descs and any(d.get("entity") is original for d in descs):
            called.append(True)
        return orig_for_update(self, *args, **kwargs)

    monkeypatch.setattr(_Query, "with_for_update", spy)

    # Any counted-quota endpoint will do; /notebooks uses notebooks.max.
    resp = client.post("/api/v1/notebooks", json={"title": "N"})
    assert resp.status_code in (200, 201), resp.text
    assert called, "with_for_update should have been called on Workspace"


def test_free_notebook_cap_still_enforced() -> None:
    """Regression: after the C3 lock change, the serial path still blocks."""
    client, _ = _register("c3-cap@x.co")
    r1 = client.post("/api/v1/notebooks", json={"title": "A"})
    assert r1.status_code in (200, 201), r1.text
    r2 = client.post("/api/v1/notebooks", json={"title": "B"})
    assert r2.status_code == 402, r2.text
    code = r2.json().get("error", {}).get("code")
    assert code == "plan_limit_reached"
