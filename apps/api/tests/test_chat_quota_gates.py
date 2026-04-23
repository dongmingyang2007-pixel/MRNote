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
import app.db.session as _s
import app.routers.chat as chat_router
import app.routers.realtime as realtime_router
from app.db.base import Base
from app.models import (
    AIActionLog,
    AIUsageEvent,
    Conversation,
    Project,
    Subscription,
    User,
)
from app.services.runtime_state import runtime_state


def setup_function() -> None:
    # Resolve engine/SessionLocal dynamically — other test files may have
    # reloaded app.db.session after import time, rebinding these on the
    # module object. Looking them up via `_s.` picks the current bindings
    # so setup and the FastAPI app hit the same DB.
    Base.metadata.drop_all(bind=_s.engine)
    Base.metadata.create_all(bind=_s.engine)
    runtime_state._memory = runtime_state._memory.__class__()
    # `realtime.py` and `chat.py` did `from app.db.session import SessionLocal`
    # at their own import time. Subsequent reloads of `app.db.session` by
    # other test modules leave those local bindings pointing at a stale
    # engine (no tables). Reload the routers here so every test sees the
    # current SessionLocal.
    importlib.reload(chat_router)
    importlib.reload(realtime_router)
    importlib.reload(main_module)


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
    with _s.SessionLocal() as db:
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
    with _s.SessionLocal() as db:
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
    with _s.SessionLocal() as db:
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


# ---------------------------------------------------------------------------
# C2: realtime WebSocket voice.enabled gate
#
# Each ws endpoint previously authenticated via access-token cookie alone,
# leaving voice.enabled only on the HTTP /ws-ticket route — so a client
# that skipped the ticket flow (just opened wss with its cookie) got the
# full realtime voice pipeline regardless of plan.
# ---------------------------------------------------------------------------

def _create_project_and_conversation(workspace_id: str, user_id: str) -> tuple[str, str]:
    """Insert project+conversation rows directly (bypassing billing gates
    that aren't under test). Project has no created_by column."""
    with _s.SessionLocal() as db:
        project = Project(
            workspace_id=workspace_id,
            name="Realtime Proj",
            description="x",
        )
        db.add(project)
        db.commit()
        db.refresh(project)
        conv = Conversation(
            workspace_id=workspace_id,
            project_id=project.id,
            title="T",
            created_by=user_id,
        )
        db.add(conv)
        db.commit()
        db.refresh(conv)
        return project.id, conv.id


def _user_id_for_workspace(workspace_id: str) -> str:
    from app.models import Membership
    with _s.SessionLocal() as db:
        return db.query(Membership.user_id).filter(
            Membership.workspace_id == workspace_id
        ).first()[0]


def test_realtime_voice_ws_blocked_on_free_plan(monkeypatch) -> None:
    """Free workspace can authenticate the WebSocket but must be told
    plan_required and disconnected before any upstream resource opens."""
    monkeypatch.setattr(realtime_router.settings, "dashscope_api_key", "test-key")
    client, ws_id = _register("c2-voice@x.co")
    uid = _user_id_for_workspace(ws_id)
    project_id, conv_id = _create_project_and_conversation(ws_id, uid)

    with client.websocket_connect(
        "/api/v1/realtime/voice", headers=_public()
    ) as websocket:
        websocket.send_json({
            "type": "session.start",
            "conversation_id": conv_id,
            "project_id": project_id,
        })
        msg = websocket.receive_json()
        assert msg["type"] == "error", msg
        assert msg["code"] == "plan_required", msg


def test_realtime_composed_voice_ws_blocked_on_free_plan(monkeypatch) -> None:
    monkeypatch.setattr(realtime_router.settings, "dashscope_api_key", "test-key")
    client, ws_id = _register("c2-composed@x.co")
    uid = _user_id_for_workspace(ws_id)
    project_id, conv_id = _create_project_and_conversation(ws_id, uid)

    with client.websocket_connect(
        "/api/v1/realtime/composed-voice", headers=_public()
    ) as websocket:
        websocket.send_json({
            "type": "session.start",
            "conversation_id": conv_id,
            "project_id": project_id,
        })
        msg = websocket.receive_json()
        assert msg["type"] == "error", msg
        assert msg["code"] == "plan_required", msg


def test_realtime_dictate_ws_blocked_on_free_plan(monkeypatch) -> None:
    """/dictate had the gate before this audit but regress-test it so it
    stays enforced."""
    monkeypatch.setattr(realtime_router.settings, "dashscope_api_key", "test-key")
    client, ws_id = _register("c2-dictate@x.co")
    uid = _user_id_for_workspace(ws_id)
    project_id, conv_id = _create_project_and_conversation(ws_id, uid)

    with client.websocket_connect(
        "/api/v1/realtime/dictate", headers=_public()
    ) as websocket:
        websocket.send_json({
            "type": "session.start",
            "conversation_id": conv_id,
            "project_id": project_id,
        })
        msg = websocket.receive_json()
        assert msg["type"] == "error", msg
        assert msg["code"] == "plan_required", msg


def test_realtime_voice_ws_passes_on_pro_plan(monkeypatch) -> None:
    """Sanity: Pro workspaces clear the voice gate and reach session.ready.
    We stub the upstream realtime WS so the test doesn't actually dial out.
    """
    monkeypatch.setattr(realtime_router.settings, "dashscope_api_key", "test-key")

    # Stub upstream connection so RealtimeSession.connect_upstream /
    # send_initial_session_update don't try to hit dashscope.
    from app.services.realtime_bridge import SessionState

    async def _fake_connect(self):
        self._upstream_ws = object()  # placeholder — we end before using it
    async def _fake_update(self, _system_prompt):
        self.state = SessionState.READY
    monkeypatch.setattr(
        "app.services.realtime_bridge.RealtimeSession.connect_upstream",
        _fake_connect,
    )
    monkeypatch.setattr(
        "app.services.realtime_bridge.RealtimeSession.send_initial_session_update",
        _fake_update,
    )

    client, ws_id = _register("c2-voice-pro@x.co")
    _upgrade(ws_id, "pro")
    uid = _user_id_for_workspace(ws_id)
    project_id, conv_id = _create_project_and_conversation(ws_id, uid)

    with client.websocket_connect(
        "/api/v1/realtime/voice", headers=_public()
    ) as websocket:
        websocket.send_json({
            "type": "session.start",
            "conversation_id": conv_id,
            "project_id": project_id,
        })
        msg = websocket.receive_json()
        # Must not be the plan gate — gate cleared.
        assert not (msg.get("type") == "error" and msg.get("code") == "plan_required"), msg
        websocket.send_json({"type": "session.end"})
