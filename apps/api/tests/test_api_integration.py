# ruff: noqa: E402

import atexit
import asyncio
import base64
from datetime import datetime, timezone
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
from types import SimpleNamespace

from botocore.exceptions import ClientError
from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocketDisconnect

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-api-tests-"))
atexit.register(lambda: shutil.rmtree(TEST_TEMP_DIR, ignore_errors=True))

DB_PATH = TEST_TEMP_DIR / "test_api.db"
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
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

import app.routers.auth as auth_router
import app.routers.chat as chat_router
import app.routers.memory as memory_router
import app.routers.realtime as realtime_router
import app.routers.uploads as uploads_router
from app.services.dashscope_client import SearchSource
import app.services.dashscope_responses as dashscope_responses_service
import app.services.dashscope_stream as dashscope_stream_service
import app.services.assistant_markdown as assistant_markdown_service
import app.services.memory_compaction as memory_compaction_service
import app.services.memory_graph_events as memory_graph_events_service
import app.services.memory_file_context as memory_file_context_service
import app.services.memory_graph_repair as memory_graph_repair_service
import app.services.memory_category_tree as memory_category_tree_service
import app.services.memory_context as memory_context_service
import app.services.memory_metadata as memory_metadata_service
import app.services.memory_v2 as memory_v2_service
import app.services.project_cleanup as project_cleanup_service
import app.services.orchestrator as orchestrator_service
import app.services.ai_gateway_tool_selection as ai_gateway_tool_selection_service
from app.core.config import settings
from app.core.deps import revoke_user_tokens
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models import (
    AuditLog,
    Conversation,
    DataItem,
    Dataset,
    Memory,
    MemoryEdge,
    Message,
    Membership,
    MemoryFile,
    MemoryView,
    ModelVersion,
    PipelineConfig,
    Project,
    User,
    Workspace,
)
from app.services.model_catalog_seed import seed_model_catalog
from app.services.memory_roots import (
    ensure_project_assistant_root,
    ensure_project_subject,
    ensure_project_user_subject,
)
from app.services import storage as storage_service
from app.services.runtime_state import runtime_state
import app.tasks.worker_tasks as worker_tasks

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


def verification_code_key(email: str, purpose: str) -> str:
    raw = f"{email.lower().strip()}:{purpose}"
    return hashlib.sha256(raw.encode()).hexdigest()


def issue_verification_code(client: TestClient, email: str, purpose: str = "register") -> str:
    resp = client.post(
        "/api/v1/auth/send-code",
        json={"email": email, "purpose": purpose},
        headers=public_headers(),
    )
    assert resp.status_code == 200

    entry = runtime_state.get_json("verify_code", verification_code_key(email, purpose))
    assert entry is not None
    return str(entry["code"])


def csrf_headers(client: TestClient, workspace_id: str | None = None) -> dict[str, str]:
    resp = client.get("/api/v1/auth/csrf", headers=public_headers())
    assert resp.status_code == 200
    headers = {"origin": ORIGIN, "x-csrf-token": resp.json()["csrf_token"]}
    if workspace_id:
        headers["x-workspace-id"] = workspace_id
    return headers


def add_workspace_membership(workspace_id: str, email: str, role: str) -> str:
    with SessionLocal() as db:
        user_id = db.query(User.id).filter(User.email == email).first()
        assert user_id is not None
        membership = Membership(workspace_id=workspace_id, user_id=user_id[0], role=role)
        db.add(membership)
        db.commit()
        return user_id[0]


def create_conversation_record(workspace_id: str, project_id: str, created_by: str, title: str) -> str:
    with SessionLocal() as db:
        conversation = Conversation(
            workspace_id=workspace_id,
            project_id=project_id,
            title=title,
            created_by=created_by,
        )
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
        return conversation.id


def register_user(client: TestClient, email: str, display_name: str = "User") -> dict:
    code = issue_verification_code(client, email, "register")
    resp = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "pass1234pass",
            "display_name": display_name,
            "code": code,
        },
        headers=public_headers(),
    )
    assert resp.status_code == 200
    return resp.json()


def create_project(client: TestClient, name: str = "P1") -> dict:
    resp = client.post(
        "/api/v1/projects",
        json={"name": name, "description": "demo", "default_chat_mode": "standard"},
        headers=csrf_headers(client),
    )
    assert resp.status_code == 200
    return resp.json()


def create_dataset(client: TestClient, project_id: str, name: str = "D1") -> dict:
    resp = client.post(
        "/api/v1/datasets",
        json={"project_id": project_id, "name": name, "type": "images"},
        headers=csrf_headers(client),
    )
    assert resp.status_code == 200
    return resp.json()


def upload_fixture(filename: str) -> tuple[bytes, str]:
    suffix = Path(filename).suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return (b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00", "image/jpeg")
    if suffix == ".png":
        return (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR", "image/png")
    if suffix == ".pdf":
        return (b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n", "application/pdf")
    if suffix == ".txt":
        return (b"hello from qihang\n", "text/plain")
    if suffix == ".md":
        return (b"# qihang\n", "text/markdown")
    if suffix == ".docx":
        return (b"PK\x03\x04\x14\x00\x00\x00\x08\x00", _DOCX_MEDIA_TYPE)
    raise AssertionError(f"Unsupported test fixture for {filename}")


def upload_item(client: TestClient, dataset_id: str, filename: str) -> str:
    payload_bytes, media_type = upload_fixture(filename)
    presign = client.post(
        "/api/v1/uploads/presign",
        json={
            "dataset_id": dataset_id,
            "filename": filename,
            "media_type": media_type,
            "size_bytes": len(payload_bytes),
        },
        headers=csrf_headers(client),
    )
    assert presign.status_code == 200
    payload = presign.json()

    put_resp = client.put(
        payload["put_url"],
        content=payload_bytes,
        headers={**payload["headers"], **csrf_headers(client)},
    )
    assert put_resp.status_code == 200

    complete = client.post(
        "/api/v1/uploads/complete",
        json={"upload_id": payload["upload_id"], "data_item_id": payload["data_item_id"]},
        headers=csrf_headers(client),
    )
    assert complete.status_code == 200
    return payload["data_item_id"]


def commit_dataset(client: TestClient, dataset_id: str, commit_message: str, freeze_filter: dict | None = None) -> dict:
    resp = client.post(
        f"/api/v1/datasets/{dataset_id}/commit",
        json={"commit_message": commit_message, "freeze_filter": freeze_filter},
        headers=csrf_headers(client),
    )
    assert resp.status_code == 200
    return resp.json()["dataset_version"]


def make_client_error(code: str, status_code: int) -> ClientError:
    return ClientError(
        {
            "Error": {"Code": code, "Message": "boom"},
            "ResponseMetadata": {"HTTPStatusCode": status_code},
        },
        "HeadObject",
    )


def upload_model_artifact(client: TestClient, model_id: str, filename: str) -> str:
    payload_bytes = b'{"ok": true}'
    presign = client.post(
        f"/api/v1/models/{model_id}/artifact-uploads/presign",
        json={"filename": filename, "media_type": "application/json", "size_bytes": len(payload_bytes)},
        headers=csrf_headers(client),
    )
    assert presign.status_code == 200
    payload = presign.json()

    put_resp = client.put(
        payload["put_url"],
        content=payload_bytes,
        headers={**payload["headers"], **csrf_headers(client)},
    )
    assert put_resp.status_code == 200
    return payload["artifact_upload_id"]


_DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class DummyRealtimeUpstream:
    def __init__(self, *, close_immediately: bool = False):
        self._queue: asyncio.Queue[str | None] = asyncio.Queue()
        if close_immediately:
            self._queue.put_nowait(None)

    def __aiter__(self):
        return self

    async def __anext__(self):
        message = await self._queue.get()
        if message is None:
            raise StopAsyncIteration
        return message

    async def close(self) -> None:
        await self._queue.put(None)

    async def send(self, _message: str) -> None:
        return None


def stub_realtime_upstream(
    monkeypatch,
    *,
    close_immediately: bool = False,
    connect_delay_seconds: float = 0.0,
    session_update_delay_seconds: float = 0.0,
    prompt_sink: list[str] | None = None,
    model_sink: list[str] | None = None,
) -> None:
    from app.services.realtime_bridge import SessionState

    async def fake_connect_upstream(self) -> None:
        if connect_delay_seconds:
            await asyncio.sleep(connect_delay_seconds)
        if model_sink is not None:
            model_sink.append(getattr(self, "upstream_model", ""))
        self._upstream_ws = DummyRealtimeUpstream(close_immediately=close_immediately)

    async def fake_send_session_update(self, _system_prompt: str) -> None:
        if prompt_sink is not None:
            prompt_sink.append(_system_prompt)
        if session_update_delay_seconds:
            await asyncio.sleep(session_update_delay_seconds)
        self.state = SessionState.READY

    monkeypatch.setattr("app.services.realtime_bridge.RealtimeSession.connect_upstream", fake_connect_upstream)
    monkeypatch.setattr("app.services.realtime_bridge.RealtimeSession.send_session_update", fake_send_session_update)
    monkeypatch.setattr("app.services.realtime_bridge.RealtimeSession.send_initial_session_update", fake_send_session_update)


def test_auth_cookie_and_me() -> None:
    client = TestClient(main_module.app)
    code = issue_verification_code(client, "u1@example.com", "register")
    resp = client.post(
        "/api/v1/auth/register",
        json={
            "email": "u1@example.com",
            "password": "pass1234pass",
            "display_name": "U1",
            "code": code,
        },
        headers=public_headers(),
    )
    assert resp.status_code == 200
    assert "access_token" in resp.cookies
    assert resp.json()["access_token_expires_in_seconds"] == config_module.settings.jwt_expire_minutes * 60

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    data = me.json()
    assert data["email"] == "u1@example.com"


def test_logout_revokes_stolen_access_token() -> None:
    client = TestClient(main_module.app)
    register_user(client, "logout@example.com", "Logout User")

    access_token = client.cookies.get(config_module.settings.access_cookie_name)
    assert access_token

    shadow = TestClient(main_module.app)
    shadow.cookies.set(config_module.settings.access_cookie_name, access_token)
    assert shadow.get("/api/v1/auth/me").status_code == 200

    logout = client.post("/api/v1/auth/logout", headers=csrf_headers(client))
    assert logout.status_code == 200

    denied = shadow.get("/api/v1/auth/me")
    assert denied.status_code == 401


def test_reset_password_revokes_existing_sessions() -> None:
    client = TestClient(main_module.app)
    register_user(client, "reset@example.com", "Reset User")

    access_token = client.cookies.get(config_module.settings.access_cookie_name)
    assert access_token

    shadow = TestClient(main_module.app)
    shadow.cookies.set(config_module.settings.access_cookie_name, access_token)
    assert shadow.get("/api/v1/auth/me").status_code == 200

    code = issue_verification_code(client, "reset@example.com", "reset")
    reset = client.post(
        "/api/v1/auth/reset-password",
        json={"email": "reset@example.com", "password": "newpass1234pass", "code": code},
        headers=public_headers(),
    )
    assert reset.status_code == 200

    denied = shadow.get("/api/v1/auth/me")
    assert denied.status_code == 401

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "reset@example.com", "password": "newpass1234pass"},
        headers=public_headers(),
    )
    assert login.status_code == 200


def test_realtime_websocket_auth_uses_cookie_and_rejects_revoked_token() -> None:
    client = TestClient(main_module.app)
    register_user(client, "realtime-revoked@example.com", "Realtime Revoked")

    access_token = client.cookies.get(config_module.settings.access_cookie_name)
    assert access_token

    shadow = TestClient(main_module.app)
    shadow.cookies.set(config_module.settings.access_cookie_name, access_token)

    logout = client.post("/api/v1/auth/logout", headers=csrf_headers(client))
    assert logout.status_code == 200

    with shadow.websocket_connect("/api/v1/realtime/voice", headers=public_headers()) as websocket:
        message = websocket.receive_json()
        assert message["type"] == "error"
        assert message["code"] == "unauthorized"


def test_realtime_ws_ticket_allows_cookie_free_websocket_session(monkeypatch) -> None:
    monkeypatch.setattr(realtime_router.settings, "dashscope_api_key", "test-key")
    stub_realtime_upstream(monkeypatch)

    client = TestClient(main_module.app)
    owner_info = register_user(client, "realtime-ticket@example.com", "Realtime Ticket")
    workspace_id = owner_info["workspace"]["id"]
    owner_user_id = owner_info["user"]["id"]
    project = create_project(client, "Realtime Ticket Project")
    conversation_id = create_conversation_record(
        workspace_id,
        project["id"],
        owner_user_id,
        "Ticket Voice",
    )

    ticket_response = client.get("/api/v1/realtime/ws-ticket", headers=public_headers())
    assert ticket_response.status_code == 200
    ticket = ticket_response.json()["ticket"]

    shadow = TestClient(main_module.app)
    with shadow.websocket_connect(
        f"/api/v1/realtime/voice?ticket={ticket}",
        headers=public_headers(),
    ) as websocket:
        websocket.send_json(
            {
                "type": "session.start",
                "conversation_id": conversation_id,
                "project_id": project["id"],
            }
        )
        ready = websocket.receive_json()
        assert ready["type"] == "session.ready"
        websocket.send_json({"type": "session.end"})


def test_realtime_ws_ticket_is_single_use(monkeypatch) -> None:
    monkeypatch.setattr(realtime_router.settings, "dashscope_api_key", "test-key")
    stub_realtime_upstream(monkeypatch)

    client = TestClient(main_module.app)
    owner_info = register_user(client, "realtime-ticket-once@example.com", "Realtime Ticket Once")
    workspace_id = owner_info["workspace"]["id"]
    owner_user_id = owner_info["user"]["id"]
    project = create_project(client, "Realtime Ticket Single Use")
    conversation_id = create_conversation_record(
        workspace_id,
        project["id"],
        owner_user_id,
        "Ticket Voice Once",
    )

    ticket_response = client.get("/api/v1/realtime/ws-ticket", headers=public_headers())
    assert ticket_response.status_code == 200
    ticket = ticket_response.json()["ticket"]

    shadow = TestClient(main_module.app)
    with shadow.websocket_connect(
        f"/api/v1/realtime/voice?ticket={ticket}",
        headers=public_headers(),
    ) as websocket:
        websocket.send_json(
            {
                "type": "session.start",
                "conversation_id": conversation_id,
                "project_id": project["id"],
            }
        )
        assert websocket.receive_json()["type"] == "session.ready"
        websocket.send_json({"type": "session.end"})

    with shadow.websocket_connect(
        f"/api/v1/realtime/voice?ticket={ticket}",
        headers=public_headers(),
    ) as websocket:
        message = websocket.receive_json()
        assert message["type"] == "error"
        assert message["code"] == "unauthorized"


def test_realtime_websocket_enforces_conversation_access(monkeypatch) -> None:
    monkeypatch.setattr(realtime_router.settings, "dashscope_api_key", "test-key")
    stub_realtime_upstream(monkeypatch)

    owner = TestClient(main_module.app)
    owner_info = register_user(owner, "realtime-owner@example.com", "Realtime Owner")
    workspace_id = owner_info["workspace"]["id"]
    owner_user_id = owner_info["user"]["id"]
    project = create_project(owner, "Realtime Project")
    conversation_id = create_conversation_record(workspace_id, project["id"], owner_user_id, "Owner Voice")

    viewer = TestClient(main_module.app)
    register_user(viewer, "realtime-viewer@example.com", "Realtime Viewer")
    add_workspace_membership(workspace_id, "realtime-viewer@example.com", "viewer")

    with owner.websocket_connect("/api/v1/realtime/voice", headers=public_headers()) as websocket:
        websocket.send_json(
            {
                "type": "session.start",
                "conversation_id": conversation_id,
                "project_id": project["id"],
                "workspace_id": "ignored-by-server",
            }
        )
        ready = websocket.receive_json()
        assert ready["type"] == "session.ready"
        websocket.send_json({"type": "session.end"})

    with viewer.websocket_connect("/api/v1/realtime/voice", headers=public_headers()) as websocket:
        websocket.send_json(
            {
                "type": "session.start",
                "conversation_id": conversation_id,
                "project_id": project["id"],
                "workspace_id": workspace_id,
            }
        )
        denied = websocket.receive_json()
        assert denied["type"] == "error"
        assert denied["code"] == "forbidden"


def test_realtime_websocket_ends_after_token_revocation(monkeypatch) -> None:
    monkeypatch.setattr(realtime_router.settings, "dashscope_api_key", "test-key")
    stub_realtime_upstream(monkeypatch)
    monkeypatch.setattr(realtime_router, "SESSION_MONITOR_INTERVAL_SECONDS", 0.01)

    client = TestClient(main_module.app)
    user_info = register_user(client, "realtime-live-revoke@example.com", "Realtime Live Revoke")
    project = create_project(client, "Realtime Revoke Project")
    conversation_id = create_conversation_record(
        user_info["workspace"]["id"],
        project["id"],
        user_info["user"]["id"],
        "Live Revoke",
    )

    with client.websocket_connect("/api/v1/realtime/voice", headers=public_headers()) as websocket:
        websocket.send_json(
            {
                "type": "session.start",
                "conversation_id": conversation_id,
                "project_id": project["id"],
                "workspace_id": user_info["workspace"]["id"],
            }
        )
        ready = websocket.receive_json()
        assert ready["type"] == "session.ready"

        revoke_user_tokens(user_info["user"]["id"])

        ended = websocket.receive_json()
        assert ended["type"] == "session.end"
        assert ended["reason"] == "auth_revoked"
        with pytest.raises(WebSocketDisconnect):
            websocket.receive_json()


def test_realtime_websocket_closes_when_upstream_disconnects(monkeypatch) -> None:
    monkeypatch.setattr(realtime_router.settings, "dashscope_api_key", "test-key")
    stub_realtime_upstream(monkeypatch, close_immediately=True)

    client = TestClient(main_module.app)
    user_info = register_user(client, "realtime-upstream-drop@example.com", "Realtime Upstream Drop")
    project = create_project(client, "Realtime Upstream Project")
    conversation_id = create_conversation_record(
        user_info["workspace"]["id"],
        project["id"],
        user_info["user"]["id"],
        "Upstream Drop",
    )

    with client.websocket_connect("/api/v1/realtime/voice", headers=public_headers()) as websocket:
        websocket.send_json(
            {
                "type": "session.start",
                "conversation_id": conversation_id,
                "project_id": project["id"],
            }
        )
        ready = websocket.receive_json()
        assert ready["type"] == "session.ready"

        error = websocket.receive_json()
        assert error["type"] == "error"
        assert error["code"] == "upstream_disconnected"

        with pytest.raises(WebSocketDisconnect):
            websocket.receive_json()


def test_realtime_websocket_times_out_during_upstream_setup(monkeypatch) -> None:
    monkeypatch.setattr(realtime_router.settings, "dashscope_api_key", "test-key")
    stub_realtime_upstream(monkeypatch, connect_delay_seconds=0.05)
    monkeypatch.setattr(realtime_router, "UPSTREAM_CONNECT_TIMEOUT_SECONDS", 0.01)

    client = TestClient(main_module.app)
    user_info = register_user(client, "realtime-timeout@example.com", "Realtime Timeout")
    project = create_project(client, "Realtime Timeout Project")
    conversation_id = create_conversation_record(
        user_info["workspace"]["id"],
        project["id"],
        user_info["user"]["id"],
        "Timeout",
    )

    with client.websocket_connect("/api/v1/realtime/voice", headers=public_headers()) as websocket:
        websocket.send_json(
            {
                "type": "session.start",
                "conversation_id": conversation_id,
                "project_id": project["id"],
            }
        )
        error = websocket.receive_json()
        assert error["type"] == "error"
        assert error["code"] == "upstream_timeout"


def test_realtime_websocket_initial_prompt_includes_recent_history(monkeypatch) -> None:
    monkeypatch.setattr(realtime_router.settings, "dashscope_api_key", "test-key")
    prompt_sink: list[str] = []
    stub_realtime_upstream(monkeypatch, prompt_sink=prompt_sink)

    client = TestClient(main_module.app)
    user_info = register_user(client, "realtime-history@example.com", "Realtime History")
    workspace_id = user_info["workspace"]["id"]
    project = create_project(client, "Realtime History Project")
    conversation_id = create_conversation_record(
        workspace_id,
        project["id"],
        user_info["user"]["id"],
        "History Conversation",
    )

    with SessionLocal() as db:
        db.add(Message(conversation_id=conversation_id, role="user", content="第一条历史消息"))
        db.add(Message(conversation_id=conversation_id, role="assistant", content="第一条历史回复"))
        db.commit()

    with client.websocket_connect("/api/v1/realtime/voice", headers=public_headers()) as websocket:
        websocket.send_json(
            {
                "type": "session.start",
                "conversation_id": conversation_id,
                "project_id": project["id"],
            }
        )
        ready = websocket.receive_json()
        assert ready["type"] == "session.ready"
        websocket.send_json({"type": "session.end"})

    assert prompt_sink
    assert "最近对话历史" in prompt_sink[0]
    assert "第一条历史消息" in prompt_sink[0]
    assert "第一条历史回复" in prompt_sink[0]


def test_realtime_post_turn_tasks_persists_metadata_and_notifies_client(monkeypatch) -> None:
    monkeypatch.setattr(realtime_router.settings, "dashscope_api_key", "test-key")
    monkeypatch.setattr(realtime_router.extract_memories, "delay", lambda *args, **kwargs: None)

    client = TestClient(main_module.app)
    user_info = register_user(client, "realtime-turn-persist@example.com", "Realtime Persist")
    workspace_id = user_info["workspace"]["id"]
    project = create_project(client, "Realtime Persist Project")
    conversation_id = create_conversation_record(
        workspace_id,
        project["id"],
        user_info["user"]["id"],
        "Realtime Persist Conversation",
    )

    class _DummyWebSocket:
        def __init__(self) -> None:
            self.payloads: list[dict[str, object]] = []

        async def send_json(self, payload: dict[str, object]) -> None:
            self.payloads.append(payload)

    ws = _DummyWebSocket()
    session = realtime_router.RealtimeSession(
        workspace_id=workspace_id,
        project_id=project["id"],
        conversation_id=conversation_id,
        user_id=user_info["user"]["id"],
    )
    session.turn_count = 1

    retrieval_trace = {
        "strategy": "subject_graph_v1",
        "memories": [{"id": "mem-1", "source": "semantic", "score": 0.93}],
        "knowledge_chunks": [],
        "linked_file_chunks": [],
    }

    asyncio.run(
        realtime_router._post_turn_tasks(
            ws,
            session,
            "你好",
            "你好，我在。",
            assistant_metadata_json={"retrieval_trace": retrieval_trace},
        )
    )

    assert ws.payloads
    assert ws.payloads[0]["type"] == "turn.persisted"
    assistant_payload = ws.payloads[0]["assistant_message"]
    assert isinstance(assistant_payload, dict)
    assert assistant_payload["metadata_json"]["retrieval_trace"]["strategy"] == "subject_graph_v1"

    with SessionLocal() as db:
        messages = (
            db.query(Message)
            .filter(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
            .all()
        )
        assert [message.role for message in messages] == ["user", "assistant"]
        assert messages[1].metadata_json["retrieval_trace"]["strategy"] == "subject_graph_v1"


def test_chat_serialize_message_exposes_preview_not_full_extracted_facts() -> None:
    message = Message(
        id="assistant-1",
        conversation_id="conv-1",
        role="assistant",
        content="已记录。",
        metadata_json={
            "memory_write_preview": {
                "summary": "新增永久记忆 1 条",
                "item_count": 1,
                "written_count": 1,
                "items": [
                    {
                        "id": "item-1",
                        "fact": "用户喜欢乌龙茶。",
                        "category": "偏好",
                        "importance": 0.92,
                        "triage_action": "promote",
                        "status": "permanent",
                    }
                ],
            },
            "extracted_facts": [
                {
                    "fact": "用户喜欢乌龙茶。",
                    "category": "偏好",
                    "importance": 0.92,
                    "triage_action": "promote",
                    "status": "permanent",
                }
            ],
            "memory_extraction_status": "completed",
        },
        created_at=datetime.now(timezone.utc),
    )

    payload = chat_router._serialize_message(message)

    assert "memory_write_preview" in payload.metadata_json
    assert "extracted_facts" not in payload.metadata_json
    assert payload.metadata_json["memory_write_preview"]["written_count"] == 1


def test_chat_live_metadata_uses_memory_write_preview() -> None:
    message = Message(
        id="assistant-2",
        conversation_id="conv-1",
        role="assistant",
        content="已记录。",
        metadata_json={
            "memory_write_preview": {
                "summary": "新增临时记忆 1 条",
                "item_count": 1,
                "written_count": 1,
                "items": [
                    {
                        "id": "item-2",
                        "fact": "用户计划今年去东京旅行。",
                        "category": "旅行.计划",
                        "importance": 0.84,
                        "status": "temporary",
                    }
                ],
            },
            "extracted_facts": [{"fact": "legacy", "category": "", "importance": 0.8}],
            "memories_extracted": "新增临时记忆 1 条",
            "memory_extraction_status": "completed",
            "memory_write_run_id": "run-1",
        },
        created_at=datetime.now(timezone.utc),
    )

    payload = chat_router._extract_live_message_metadata(message)

    assert payload is not None
    assert "memory_write_preview" in payload
    assert "extracted_facts" not in payload
    assert payload["memory_write_run_id"] == "run-1"


def test_upstream_listener_skips_post_turn_tasks_for_cancelled_response_done(monkeypatch) -> None:
    class _DummyClientWebSocket:
        def __init__(self) -> None:
            self.json_payloads: list[dict[str, object]] = []
            self.binary_payloads: list[bytes] = []

        async def send_json(self, payload: dict[str, object]) -> None:
            self.json_payloads.append(payload)

        async def send_bytes(self, payload: bytes) -> None:
            self.binary_payloads.append(payload)

    class _QueuedUpstream:
        def __init__(self, session, messages: list[dict[str, object]]) -> None:
            self._session = session
            self._messages = [json.dumps(message) for message in messages]

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self._messages:
                return self._messages.pop(0)
            self._session.state = self._session.state.CLOSING
            raise StopAsyncIteration

        async def send(self, _message: str) -> None:
            return None

    session = realtime_router.RealtimeSession(
        workspace_id="ws",
        project_id="project",
        conversation_id="conversation",
        user_id="user",
    )
    session._upstream_ws = _QueuedUpstream(session, [{"type": "response.done"}])
    session._ai_speaking = True
    session._current_transcript = "第一句"
    session._current_response_text = "旧回答"

    asyncio.run(session.cancel_response())

    posted: list[tuple[str, str]] = []

    async def fake_post_turn_tasks(_ws, _session, user_text: str, ai_text: str, **kwargs) -> None:
        del _ws, _session, kwargs
        posted.append((user_text, ai_text))

    monkeypatch.setattr(realtime_router, "_post_turn_tasks", fake_post_turn_tasks)

    ws = _DummyClientWebSocket()
    result = asyncio.run(realtime_router._upstream_listener(ws, session))

    assert result is None
    assert ws.json_payloads == []
    assert ws.binary_payloads == []
    assert posted == []


def test_realtime_refresh_context_clears_stale_retrieval_trace_on_failure(monkeypatch) -> None:
    session = realtime_router.RealtimeSession(
        workspace_id="ws",
        project_id="project",
        conversation_id="conversation",
        user_id="user",
    )
    session._active_turn_retrieval_trace = {"primary_subject_id": "subject-stale"}

    called = {"request_response": 0}

    async def fake_build_context(*args, **kwargs):
        raise RuntimeError("boom")

    async def fake_request_response() -> None:
        called["request_response"] += 1

    monkeypatch.setattr(realtime_router, "_build_realtime_context", fake_build_context)
    monkeypatch.setattr(session, "request_response", fake_request_response)

    asyncio.run(
        realtime_router._refresh_realtime_context_and_request_response(
            session,
            user_text="新的问题",
        )
    )

    assert session._active_turn_retrieval_trace is None
    assert called["request_response"] == 1


def test_schedule_realtime_context_refresh_debounces_repeated_transcript_completion(monkeypatch) -> None:
    session = realtime_router.RealtimeSession(
        workspace_id="ws",
        project_id="project",
        conversation_id="conversation",
        user_id="user",
    )
    session._awaiting_transcript_response = True

    called: list[str] = []

    async def fake_refresh(_session, *, user_text: str) -> None:
        called.append(user_text)

    monkeypatch.setattr(realtime_router, "_refresh_realtime_context_and_request_response", fake_refresh)
    monkeypatch.setattr(realtime_router, "REALTIME_TRANSCRIPT_SETTLE_SECONDS", 0.01)

    async def _run() -> None:
        realtime_router._schedule_realtime_context_refresh(session, user_text="第一句")
        await asyncio.sleep(0)
        realtime_router._schedule_realtime_context_refresh(session, user_text="第一句补充")
        await asyncio.sleep(0.03)

    asyncio.run(_run())

    assert called == ["第一句补充"]
    assert session._awaiting_transcript_response is False
    assert session._response_request_started_for_current_input is True


def test_upstream_listener_schedules_realtime_response_after_speech_stopped(monkeypatch) -> None:
    class _DummyClientWebSocket:
        def __init__(self) -> None:
            self.json_payloads: list[dict[str, object]] = []

        async def send_json(self, payload: dict[str, object]) -> None:
            self.json_payloads.append(payload)

        async def send_bytes(self, _payload: bytes) -> None:
            raise AssertionError("binary output is not expected in this test")

    class _QueuedUpstream:
        def __init__(self, session, messages: list[dict[str, object]]) -> None:
            self._session = session
            self._messages = [json.dumps(message) for message in messages]

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self._messages:
                return self._messages.pop(0)
            self._session.state = self._session.state.CLOSING
            raise StopAsyncIteration

        async def send(self, _message: str) -> None:
            return None

    session = realtime_router.RealtimeSession(
        workspace_id="ws",
        project_id="project",
        conversation_id="conversation",
        user_id="user",
    )
    session._upstream_ws = _QueuedUpstream(
        session,
        [
            {"type": "input_audio_buffer.speech_started"},
            {"type": "input_audio_buffer.speech_stopped"},
            {
                "type": "conversation.item.input_audio_transcription.completed",
                "transcript": "你好",
            },
        ],
    )

    called: list[str] = []

    async def fake_refresh(_session, *, user_text: str) -> None:
        called.append(user_text)

    monkeypatch.setattr(
        realtime_router,
        "_refresh_realtime_context_and_request_response",
        fake_refresh,
    )
    monkeypatch.setattr(realtime_router, "REALTIME_TRANSCRIPT_SETTLE_SECONDS", 0.01)

    async def _run() -> None:
        ws = _DummyClientWebSocket()
        result = await realtime_router._upstream_listener(ws, session)
        assert result is None
        await asyncio.sleep(0.03)
        assert ws.json_payloads == [{"type": "transcript.final", "text": "你好"}]

    asyncio.run(_run())

    assert called == ["你好"]
    assert session._awaiting_transcript_response is False
    assert session._response_request_started_for_current_input is True


def test_realtime_websocket_prefers_project_realtime_model_when_configured(monkeypatch) -> None:
    monkeypatch.setattr(realtime_router.settings, "dashscope_api_key", "test-key")
    model_sink: list[str] = []
    stub_realtime_upstream(monkeypatch, model_sink=model_sink)

    client = TestClient(main_module.app)
    user_info = register_user(client, "realtime-omni@example.com", "Realtime Omni")
    project = create_project(client, "Realtime Omni Project")

    update = client.patch(
        "/api/v1/pipeline",
        json={
            "project_id": project["id"],
            "model_type": "realtime",
            "model_id": "qwen3-omni-flash-realtime",
            "config_json": {},
        },
        headers=csrf_headers(client),
    )
    assert update.status_code == 200

    conversation_id = create_conversation_record(
        user_info["workspace"]["id"],
        project["id"],
        user_info["user"]["id"],
        "Realtime Omni Conversation",
    )

    with client.websocket_connect("/api/v1/realtime/voice", headers=public_headers()) as websocket:
        websocket.send_json(
            {
                "type": "session.start",
                "conversation_id": conversation_id,
                "project_id": project["id"],
            }
        )
        ready = websocket.receive_json()
        assert ready["type"] == "session.ready"
        websocket.send_json({"type": "session.end"})

    assert model_sink == ["qwen3-omni-flash-realtime"]


def test_realtime_websocket_accepts_continuous_camera_frames(monkeypatch) -> None:
    monkeypatch.setattr(realtime_router.settings, "dashscope_api_key", "test-key")
    stub_realtime_upstream(monkeypatch)
    captured_frames: list[bytes] = []

    async def fake_relay_image(self, image_bytes: bytes) -> None:
        captured_frames.append(image_bytes)

    monkeypatch.setattr(
        "app.services.realtime_bridge.RealtimeSession.relay_image_to_upstream",
        fake_relay_image,
    )

    client = TestClient(main_module.app)
    user_info = register_user(
        client,
        f"realtime-camera-{os.urandom(4).hex()}@example.com",
        "Realtime Camera",
    )
    project = create_project(client, "Realtime Camera Project")
    conversation_id = create_conversation_record(
        user_info["workspace"]["id"],
        project["id"],
        user_info["user"]["id"],
        "Realtime Camera Conversation",
    )

    frame_bytes = b"\xff\xd8\xff\xdbcamera-frame"
    frame_data_url = f"data:image/jpeg;base64,{base64.b64encode(frame_bytes).decode('utf-8')}"

    with client.websocket_connect("/api/v1/realtime/voice", headers=public_headers()) as websocket:
        websocket.send_json(
            {
                "type": "session.start",
                "conversation_id": conversation_id,
                "project_id": project["id"],
            }
        )
        ready = websocket.receive_json()
        assert ready["type"] == "session.ready"
        websocket.send_json(
            {
                "type": "input.image.append",
                "data_url": frame_data_url,
            }
        )
        websocket.send_json({"type": "session.end"})

    assert captured_frames == [frame_bytes]


def test_composed_realtime_websocket_runs_synthetic_pipeline(monkeypatch) -> None:
    monkeypatch.setattr(realtime_router.settings, "dashscope_api_key", "test-key")
    persisted_turns: list[tuple[str, str]] = []

    async def fake_orchestrate(
        _db,
        *,
        workspace_id: str,
        project_id: str,
        conversation_id: str,
        user_text: str,
        image_bytes: bytes | None = None,
        image_mime_type: str = "image/jpeg",
        video_bytes: bytes | None = None,
        video_mime_type: str = "video/mp4",
    ) -> dict[str, str]:
        assert workspace_id
        assert project_id
        assert conversation_id
        assert user_text == "你好"
        assert image_bytes is None
        assert video_bytes is None
        _ = image_mime_type
        _ = video_mime_type
        return {"text_input": "你好", "text_response": "你好，我在。"}

    async def fake_tts(_db, *, project_id: str, text: str) -> bytes:
        assert project_id
        assert text == "你好，我在。"
        return b"fake-mp3"

    async def fake_persist(_ws, _session, user_text: str, ai_text: str, **kwargs) -> None:
        del _ws, _session, kwargs
        persisted_turns.append((user_text, ai_text))

    class FakeRealtimeBridge:
        def __init__(self, model: str) -> None:
            self.model = model
            self.events: asyncio.Queue[dict[str, str]] = asyncio.Queue()

        async def connect(self) -> None:
            return None

        async def send_audio_chunk(self, audio_bytes: bytes) -> None:
            assert audio_bytes == b"pcm-turn"

        async def commit(self) -> None:
            await self.events.put({"type": "transcript.final", "text": "你好"})

        async def next_event(self) -> dict[str, str]:
            return await self.events.get()

        async def close(self) -> None:
            return None

    monkeypatch.setattr(realtime_router, "RealtimeTranscriptionBridge", FakeRealtimeBridge)
    monkeypatch.setattr("app.services.composed_realtime.orchestrate_synthetic_realtime_turn_from_text", fake_orchestrate)
    monkeypatch.setattr("app.services.composed_realtime.synthesize_realtime_speech_for_project", fake_tts)
    monkeypatch.setattr("app.routers.realtime._persist_composed_turn", fake_persist)

    client = TestClient(main_module.app)
    register_user(client, "synthetic-realtime@example.com", "Synthetic Realtime")
    project = create_project(client, "Synthetic Project")
    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Synthetic Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200
    conversation_id = conversation.json()["id"]

    with client.websocket_connect("/api/v1/realtime/composed-voice", headers=public_headers()) as websocket:
        websocket.send_json(
            {
                "type": "session.start",
                "project_id": project["id"],
                "conversation_id": conversation_id,
            }
        )
        ready = websocket.receive_json()
        assert ready["type"] == "session.ready"

        websocket.send_bytes(b"pcm-turn")
        websocket.send_json({"type": "audio.stop"})

        transcript = websocket.receive_json()
        assert transcript == {"type": "transcript.final", "text": "你好"}

        assistant_chunk = websocket.receive_json()
        assert assistant_chunk == {"type": "response.text", "text": "你好，我在。"}

        audio_meta = websocket.receive_json()
        assert audio_meta["type"] == "audio.meta"

        audio = websocket.receive_bytes()
        assert audio == b"fake-mp3"

        done = websocket.receive_json()
        assert done["type"] == "response.done"

    assert persisted_turns == [("你好", "你好，我在。")]


def test_composed_realtime_websocket_autostarts_turn_without_audio_stop(monkeypatch) -> None:
    monkeypatch.setattr(realtime_router.settings, "dashscope_api_key", "test-key")
    persisted_turns: list[tuple[str, str]] = []

    async def fake_orchestrate(
        _db,
        *,
        workspace_id: str,
        project_id: str,
        conversation_id: str,
        user_text: str,
        image_bytes: bytes | None = None,
        image_mime_type: str = "image/jpeg",
        video_bytes: bytes | None = None,
        video_mime_type: str = "video/mp4",
    ) -> dict[str, str]:
        assert workspace_id
        assert project_id
        assert conversation_id
        assert user_text == "你好"
        assert image_bytes is None
        assert video_bytes is None
        _ = image_mime_type
        _ = video_mime_type
        return {"text_input": "你好", "text_response": "你好，我在。"}

    async def fake_tts(_db, *, project_id: str, text: str) -> bytes:
        assert project_id
        assert text == "你好，我在。"
        return b"fake-mp3"

    async def fake_persist(_ws, _session, user_text: str, ai_text: str, **kwargs) -> None:
        del _ws, _session, kwargs
        persisted_turns.append((user_text, ai_text))

    class FakeRealtimeBridge:
        def __init__(self, model: str) -> None:
            self.model = model
            self.events: asyncio.Queue[dict[str, str]] = asyncio.Queue()
            self.sent_final = False

        async def connect(self) -> None:
            return None

        async def send_audio_chunk(self, audio_bytes: bytes) -> None:
            assert audio_bytes == b"pcm-turn"
            if not self.sent_final:
                self.sent_final = True
                await self.events.put({"type": "transcript.final", "text": "你好"})

        async def commit(self) -> None:
            raise AssertionError("audio.stop should not be required for this turn")

        async def next_event(self) -> dict[str, str]:
            return await self.events.get()

        async def close(self) -> None:
            return None

    monkeypatch.setattr(realtime_router, "RealtimeTranscriptionBridge", FakeRealtimeBridge)
    monkeypatch.setattr("app.services.composed_realtime.orchestrate_synthetic_realtime_turn_from_text", fake_orchestrate)
    monkeypatch.setattr("app.services.composed_realtime.synthesize_realtime_speech_for_project", fake_tts)
    monkeypatch.setattr("app.routers.realtime._persist_composed_turn", fake_persist)

    client = TestClient(main_module.app)
    register_user(client, "synthetic-realtime-autostart@example.com", "Synthetic Realtime Autostart")
    project = create_project(client, "Synthetic Autostart Project")
    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Synthetic Autostart Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200
    conversation_id = conversation.json()["id"]

    with client.websocket_connect("/api/v1/realtime/composed-voice", headers=public_headers()) as websocket:
        websocket.send_json(
            {
                "type": "session.start",
                "project_id": project["id"],
                "conversation_id": conversation_id,
            }
        )
        ready = websocket.receive_json()
        assert ready["type"] == "session.ready"

        websocket.send_bytes(b"pcm-turn")

        transcript = websocket.receive_json()
        assert transcript == {"type": "transcript.final", "text": "你好"}

        assistant_chunk = websocket.receive_json()
        assert assistant_chunk == {"type": "response.text", "text": "你好，我在。"}

        audio_meta = websocket.receive_json()
        assert audio_meta["type"] == "audio.meta"

        audio = websocket.receive_bytes()
        assert audio == b"fake-mp3"

        done = websocket.receive_json()
        assert done["type"] == "response.done"

        websocket.send_json({"type": "audio.stop"})
        websocket.send_json({"type": "session.end"})
        with pytest.raises(WebSocketDisconnect):
            websocket.receive_json()

    assert persisted_turns == [("你好", "你好，我在。")]


def test_composed_realtime_websocket_commits_after_asr_speech_stopped(monkeypatch) -> None:
    monkeypatch.setattr(realtime_router.settings, "dashscope_api_key", "test-key")
    persisted_turns: list[tuple[str, str]] = []

    async def fake_orchestrate(
        _db,
        *,
        workspace_id: str,
        project_id: str,
        conversation_id: str,
        user_text: str,
        image_bytes: bytes | None = None,
        image_mime_type: str = "image/jpeg",
        video_bytes: bytes | None = None,
        video_mime_type: str = "video/mp4",
    ) -> dict[str, str]:
        assert workspace_id
        assert project_id
        assert conversation_id
        assert user_text == "你好"
        assert image_bytes is None
        assert video_bytes is None
        _ = image_mime_type
        _ = video_mime_type
        return {"text_input": "你好", "text_response": "你好，我在。"}

    async def fake_tts(_db, *, project_id: str, text: str) -> bytes:
        assert project_id
        assert text == "你好，我在。"
        return b"fake-mp3"

    async def fake_persist(_ws, _session, user_text: str, ai_text: str, **kwargs) -> None:
        del _ws, _session, kwargs
        persisted_turns.append((user_text, ai_text))

    class FakeRealtimeBridge:
        def __init__(self, model: str) -> None:
            self.model = model
            self.events: asyncio.Queue[dict[str, str]] = asyncio.Queue()
            self.sent_stop = False

        async def connect(self) -> None:
            return None

        async def send_audio_chunk(self, audio_bytes: bytes) -> None:
            assert audio_bytes == b"pcm-turn"
            if not self.sent_stop:
                self.sent_stop = True
                await self.events.put({"type": "speech_stopped", "text": ""})

        async def commit(self) -> None:
            await self.events.put({"type": "transcript.final", "text": "你好"})

        async def next_event(self) -> dict[str, str]:
            return await self.events.get()

        async def close(self) -> None:
            return None

    monkeypatch.setattr(realtime_router, "RealtimeTranscriptionBridge", FakeRealtimeBridge)
    monkeypatch.setattr("app.services.composed_realtime.orchestrate_synthetic_realtime_turn_from_text", fake_orchestrate)
    monkeypatch.setattr("app.services.composed_realtime.synthesize_realtime_speech_for_project", fake_tts)
    monkeypatch.setattr("app.routers.realtime._persist_composed_turn", fake_persist)

    client = TestClient(main_module.app)
    register_user(client, "synthetic-realtime-speech-stopped@example.com", "Synthetic Realtime Speech Stopped")
    project = create_project(client, "Synthetic Speech Stopped Project")
    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Synthetic Speech Stopped Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200
    conversation_id = conversation.json()["id"]

    with client.websocket_connect("/api/v1/realtime/composed-voice", headers=public_headers()) as websocket:
        websocket.send_json(
            {
                "type": "session.start",
                "project_id": project["id"],
                "conversation_id": conversation_id,
            }
        )
        ready = websocket.receive_json()
        assert ready["type"] == "session.ready"

        websocket.send_bytes(b"pcm-turn")

        transcript = websocket.receive_json()
        assert transcript == {"type": "transcript.final", "text": "你好"}

        assistant_chunk = websocket.receive_json()
        assert assistant_chunk == {"type": "response.text", "text": "你好，我在。"}

        audio_meta = websocket.receive_json()
        assert audio_meta["type"] == "audio.meta"

        audio = websocket.receive_bytes()
        assert audio == b"fake-mp3"

        done = websocket.receive_json()
        assert done["type"] == "response.done"

    assert persisted_turns == [("你好", "你好，我在。")]


def test_composed_realtime_websocket_batches_transcripts_until_last_ai_reply(monkeypatch) -> None:
    monkeypatch.setattr(realtime_router.settings, "dashscope_api_key", "test-key")
    monkeypatch.setattr(
        realtime_router,
        "COMPOSED_AUTO_START_DEBOUNCE_SECONDS",
        1.0,
    )
    persisted_turns: list[tuple[str, str]] = []
    tts_segments: list[str] = []

    async def fake_orchestrate(
        _db,
        *,
        workspace_id: str,
        project_id: str,
        conversation_id: str,
        user_text: str,
        image_bytes: bytes | None = None,
        image_mime_type: str = "image/jpeg",
        video_bytes: bytes | None = None,
        video_mime_type: str = "video/mp4",
    ) -> dict[str, str]:
        assert workspace_id
        assert project_id
        assert conversation_id
        assert user_text == "第一句。第二句。"
        assert image_bytes is None
        assert video_bytes is None
        _ = image_mime_type
        _ = video_mime_type
        return {
            "text_input": user_text,
            "text_response": "收到：第一句。第二句。",
        }

    async def fake_tts(_db, *, project_id: str, text: str) -> bytes:
        assert project_id
        assert text in {"收到：第一句。", "第二句。"}
        tts_segments.append(text)
        return f"audio:{text}".encode("utf-8")

    async def fake_persist(_ws, _session, user_text: str, ai_text: str, **kwargs) -> None:
        del _ws, _session, kwargs
        persisted_turns.append((user_text, ai_text))

    class FakeRealtimeBridge:
        def __init__(self, model: str) -> None:
            self.model = model
            self.events: asyncio.Queue[dict[str, str]] = asyncio.Queue()
            self.chunk_count = 0

        async def connect(self) -> None:
            return None

        async def send_audio_chunk(self, audio_bytes: bytes) -> None:
            assert audio_bytes in {b"pcm-turn-1", b"pcm-turn-2"}
            self.chunk_count += 1
            if self.chunk_count == 1:
                await self.events.put({"type": "transcript.final", "text": "第一句。"})
            elif self.chunk_count == 2:
                await self.events.put({"type": "transcript.final", "text": "第二句。"})

        async def commit(self) -> None:
            raise AssertionError("audio.stop should not be required for this turn")

        async def next_event(self) -> dict[str, str]:
            return await self.events.get()

        async def close(self) -> None:
            return None

    monkeypatch.setattr(realtime_router, "RealtimeTranscriptionBridge", FakeRealtimeBridge)
    monkeypatch.setattr("app.services.composed_realtime.orchestrate_synthetic_realtime_turn_from_text", fake_orchestrate)
    monkeypatch.setattr("app.services.composed_realtime.synthesize_realtime_speech_for_project", fake_tts)
    monkeypatch.setattr("app.routers.realtime._persist_composed_turn", fake_persist)

    client = TestClient(main_module.app)
    register_user(client, "synthetic-realtime-batching@example.com", "Synthetic Realtime Batching")
    project = create_project(client, "Synthetic Batching Project")
    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Synthetic Batching Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200
    conversation_id = conversation.json()["id"]

    with client.websocket_connect("/api/v1/realtime/composed-voice", headers=public_headers()) as websocket:
        websocket.send_json(
            {
                "type": "session.start",
                "project_id": project["id"],
                "conversation_id": conversation_id,
            }
        )
        ready = websocket.receive_json()
        assert ready["type"] == "session.ready"

        websocket.send_bytes(b"pcm-turn-1")
        first = websocket.receive_json()
        assert first == {"type": "transcript.final", "text": "第一句。"}

        websocket.send_bytes(b"pcm-turn-2")
        second = websocket.receive_json()
        assert second == {"type": "transcript.final", "text": "第一句。第二句。"}

        assistant_chunk = websocket.receive_json()
        assert assistant_chunk == {"type": "response.text", "text": "收到：第一句。"}

        audio_meta = websocket.receive_json()
        assert audio_meta["type"] == "audio.meta"

        audio = websocket.receive_bytes()
        assert audio.decode("utf-8") == "audio:收到：第一句。"

        assistant_chunk_2 = websocket.receive_json()
        assert assistant_chunk_2 == {"type": "response.text", "text": "第二句。"}

        audio_2 = websocket.receive_bytes()
        assert audio_2.decode("utf-8") == "audio:第二句。"

        done = websocket.receive_json()
        assert done["type"] == "response.done"

    assert persisted_turns == [("第一句。第二句。", "收到：第一句。第二句。")]
    assert tts_segments == ["收到：第一句。", "第二句。"]


def test_composed_realtime_websocket_starts_turn_when_asr_final_times_out(monkeypatch) -> None:
    monkeypatch.setattr(realtime_router.settings, "dashscope_api_key", "test-key")
    monkeypatch.setattr(
        realtime_router,
        "COMPOSED_TRANSCRIPT_FINAL_TIMEOUT_SECONDS",
        0.01,
    )
    persisted_turns: list[tuple[str, str]] = []

    async def fake_orchestrate(
        _db,
        *,
        workspace_id: str,
        project_id: str,
        conversation_id: str,
        user_text: str,
        image_bytes: bytes | None = None,
        image_mime_type: str = "image/jpeg",
        video_bytes: bytes | None = None,
        video_mime_type: str = "video/mp4",
    ) -> dict[str, str]:
        assert workspace_id
        assert project_id
        assert conversation_id
        assert user_text == "你好"
        assert image_bytes is None
        assert video_bytes is None
        _ = image_mime_type
        _ = video_mime_type
        return {"text_input": "你好", "text_response": "你好，我在。"}

    async def fake_tts(_db, *, project_id: str, text: str) -> bytes:
        assert project_id
        assert text == "你好，我在。"
        return b"fake-mp3"

    async def fake_persist(_ws, _session, user_text: str, ai_text: str, **kwargs) -> None:
        del _ws, _session, kwargs
        persisted_turns.append((user_text, ai_text))

    class FakeRealtimeBridge:
        def __init__(self, model: str) -> None:
            self.model = model
            self.events: asyncio.Queue[dict[str, str]] = asyncio.Queue()
            self.sent_partial = False

        async def connect(self) -> None:
            return None

        async def send_audio_chunk(self, audio_bytes: bytes) -> None:
            assert audio_bytes == b"pcm-turn"
            if not self.sent_partial:
                self.sent_partial = True
                await self.events.put({"type": "transcript.partial", "text": "你好"})

        async def commit(self) -> None:
            return None

        async def next_event(self) -> dict[str, str]:
            return await self.events.get()

        async def close(self) -> None:
            return None

    monkeypatch.setattr(realtime_router, "RealtimeTranscriptionBridge", FakeRealtimeBridge)
    monkeypatch.setattr("app.services.composed_realtime.orchestrate_synthetic_realtime_turn_from_text", fake_orchestrate)
    monkeypatch.setattr("app.services.composed_realtime.synthesize_realtime_speech_for_project", fake_tts)
    monkeypatch.setattr("app.routers.realtime._persist_composed_turn", fake_persist)

    client = TestClient(main_module.app)
    register_user(client, "synthetic-realtime-timeout@example.com", "Synthetic Realtime Timeout")
    project = create_project(client, "Synthetic Timeout Project")
    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Synthetic Timeout Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200
    conversation_id = conversation.json()["id"]

    with client.websocket_connect("/api/v1/realtime/composed-voice", headers=public_headers()) as websocket:
        websocket.send_json(
            {
                "type": "session.start",
                "project_id": project["id"],
                "conversation_id": conversation_id,
            }
        )
        ready = websocket.receive_json()
        assert ready["type"] == "session.ready"

        websocket.send_bytes(b"pcm-turn")
        partial = websocket.receive_json()
        assert partial == {"type": "transcript.partial", "text": "你好"}

        websocket.send_json({"type": "audio.stop"})

        assistant_chunk = websocket.receive_json()
        assert assistant_chunk == {"type": "response.text", "text": "你好，我在。"}

        audio_meta = websocket.receive_json()
        assert audio_meta["type"] == "audio.meta"

        audio = websocket.receive_bytes()
        assert audio == b"fake-mp3"

        done = websocket.receive_json()
        assert done["type"] == "response.done"

    assert persisted_turns == [("你好", "你好，我在。")]


def test_composed_realtime_websocket_keeps_session_open_on_turn_failure(monkeypatch) -> None:
    monkeypatch.setattr(realtime_router.settings, "dashscope_api_key", "test-key")
    async def fake_orchestrate(
        _db,
        *,
        workspace_id: str,
        project_id: str,
        conversation_id: str,
        user_text: str,
        image_bytes: bytes | None = None,
        image_mime_type: str = "image/jpeg",
        video_bytes: bytes | None = None,
        video_mime_type: str = "video/mp4",
    ) -> dict[str, str]:
        assert workspace_id
        assert project_id
        assert conversation_id
        assert user_text == "你好"
        _ = image_bytes
        _ = image_mime_type
        _ = video_bytes
        _ = video_mime_type
        raise realtime_router.UpstreamServiceError("boom")

    class FakeRealtimeBridge:
        def __init__(self, model: str) -> None:
            self.model = model
            self.events: asyncio.Queue[dict[str, str]] = asyncio.Queue()

        async def connect(self) -> None:
            return None

        async def send_audio_chunk(self, audio_bytes: bytes) -> None:
            assert audio_bytes == b"pcm-turn"

        async def commit(self) -> None:
            await self.events.put({"type": "transcript.final", "text": "你好"})

        async def next_event(self) -> dict[str, str]:
            return await self.events.get()

        async def close(self) -> None:
            return None

    monkeypatch.setattr(realtime_router, "RealtimeTranscriptionBridge", FakeRealtimeBridge)
    monkeypatch.setattr("app.services.composed_realtime.orchestrate_synthetic_realtime_turn_from_text", fake_orchestrate)

    client = TestClient(main_module.app)
    register_user(client, "synthetic-turn-error@example.com", "Synthetic Turn Error")
    project = create_project(client, "Synthetic Turn Error Project")
    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Synthetic Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200
    conversation_id = conversation.json()["id"]

    with client.websocket_connect("/api/v1/realtime/composed-voice", headers=public_headers()) as websocket:
        websocket.send_json(
            {
                "type": "session.start",
                "project_id": project["id"],
                "conversation_id": conversation_id,
            }
        )
        ready = websocket.receive_json()
        assert ready["type"] == "session.ready"

        websocket.send_bytes(b"pcm-turn")
        websocket.send_json({"type": "audio.stop"})

        transcript = websocket.receive_json()
        assert transcript == {"type": "transcript.final", "text": "你好"}

        turn_error = websocket.receive_json()
        assert turn_error == {
            "type": "turn.error",
            "code": "upstream_unavailable",
            "message": "AI 暂时无响应，请重试",
        }

        websocket.send_json({"type": "session.end"})
        with pytest.raises(WebSocketDisconnect):
            websocket.receive_json()


def test_composed_realtime_websocket_interrupts_active_turn(monkeypatch) -> None:
    monkeypatch.setattr(realtime_router.settings, "dashscope_api_key", "test-key")
    interrupted = asyncio.Event()

    async def fake_orchestrate(
        _db,
        *,
        workspace_id: str,
        project_id: str,
        conversation_id: str,
        user_text: str,
        image_bytes: bytes | None = None,
        image_mime_type: str = "image/jpeg",
        video_bytes: bytes | None = None,
        video_mime_type: str = "video/mp4",
    ) -> dict[str, str]:
        assert workspace_id
        assert project_id
        assert conversation_id
        assert user_text == "第一句"
        _ = image_bytes
        _ = image_mime_type
        _ = video_bytes
        _ = video_mime_type
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            interrupted.set()
            raise
        return {"text_input": "第一句", "text_response": "不应该返回"}

    class FakeRealtimeBridge:
        def __init__(self, model: str) -> None:
            self.model = model
            self.events: asyncio.Queue[dict[str, str]] = asyncio.Queue()

        async def connect(self) -> None:
            return None

        async def send_audio_chunk(self, audio_bytes: bytes) -> None:
            assert audio_bytes == b"pcm-turn"

        async def commit(self) -> None:
            await self.events.put({"type": "transcript.final", "text": "第一句"})

        async def next_event(self) -> dict[str, str]:
            return await self.events.get()

        async def close(self) -> None:
            return None

    monkeypatch.setattr(realtime_router, "RealtimeTranscriptionBridge", FakeRealtimeBridge)
    monkeypatch.setattr("app.services.composed_realtime.orchestrate_synthetic_realtime_turn_from_text", fake_orchestrate)

    client = TestClient(main_module.app)
    register_user(client, "synthetic-interrupt@example.com", "Synthetic Interrupt")
    project = create_project(client, "Synthetic Interrupt Project")
    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Synthetic Interrupt Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200
    conversation_id = conversation.json()["id"]

    with client.websocket_connect("/api/v1/realtime/composed-voice", headers=public_headers()) as websocket:
        websocket.send_json(
            {
                "type": "session.start",
                "project_id": project["id"],
                "conversation_id": conversation_id,
            }
        )
        ready = websocket.receive_json()
        assert ready["type"] == "session.ready"

        websocket.send_bytes(b"pcm-turn")
        websocket.send_json({"type": "audio.stop"})

        transcript = websocket.receive_json()
        assert transcript == {"type": "transcript.final", "text": "第一句"}

        websocket.send_json({"type": "input.interrupt"})
        ack = websocket.receive_json()
        assert ack == {"type": "interrupt.ack"}

        websocket.send_json({"type": "session.end"})
        with pytest.raises(WebSocketDisconnect):
            websocket.receive_json()

    assert interrupted.is_set()


def test_composed_realtime_interrupt_keeps_all_user_input_since_last_reply(monkeypatch) -> None:
    monkeypatch.setattr(realtime_router.settings, "dashscope_api_key", "test-key")

    interrupted = asyncio.Event()
    orchestrate_calls: list[str] = []

    async def fake_orchestrate(
        _db,
        *,
        workspace_id: str,
        project_id: str,
        conversation_id: str,
        user_text: str,
        image_bytes: bytes | None = None,
        image_mime_type: str = "image/jpeg",
        video_bytes: bytes | None = None,
        video_mime_type: str = "video/mp4",
    ) -> dict[str, str]:
        assert workspace_id
        assert project_id
        assert conversation_id
        assert image_bytes is None
        assert image_mime_type == "image/jpeg"
        assert video_bytes is None
        _ = video_mime_type
        orchestrate_calls.append(user_text)

        if user_text == "我现在是大一。":
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                interrupted.set()
                raise
            raise AssertionError("first turn should be interrupted before completion")

        assert user_text == "我现在是大一。我在哪儿上大学？"
        return {
            "text_input": user_text,
            "text_response": "你刚才补充了年级和学校问题。",
        }

    async def fake_tts(_db, *, project_id: str, text: str) -> bytes:
        assert project_id
        assert text == "你刚才补充了年级和学校问题。"
        return b"fake-mp3"

    class FakeRealtimeBridge:
        def __init__(self, model: str) -> None:
            self.model = model
            self.events: asyncio.Queue[dict[str, str]] = asyncio.Queue()
            self._last_audio: bytes | None = None

        async def connect(self) -> None:
            return None

        async def send_audio_chunk(self, audio_bytes: bytes) -> None:
            assert audio_bytes in {b"pcm-turn-1", b"pcm-turn-2"}
            self._last_audio = audio_bytes

        async def commit(self) -> None:
            if self._last_audio == b"pcm-turn-1":
                await self.events.put({"type": "transcript.final", "text": "我现在是大一。"})
            elif self._last_audio == b"pcm-turn-2":
                await self.events.put({"type": "transcript.final", "text": "我在哪儿上大学？"})
            else:
                raise AssertionError("commit called without buffered audio")

        async def next_event(self) -> dict[str, str]:
            return await self.events.get()

        async def close(self) -> None:
            return None

    monkeypatch.setattr(realtime_router, "RealtimeTranscriptionBridge", FakeRealtimeBridge)
    monkeypatch.setattr("app.services.composed_realtime.orchestrate_synthetic_realtime_turn_from_text", fake_orchestrate)
    monkeypatch.setattr("app.services.composed_realtime.synthesize_realtime_speech_for_project", fake_tts)

    client = TestClient(main_module.app)
    register_user(client, "synthetic-accumulate-interrupt@example.com", "Synthetic Accumulate Interrupt")
    project = create_project(client, "Synthetic Accumulate Interrupt Project")
    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Synthetic Accumulate Interrupt Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200
    conversation_id = conversation.json()["id"]

    with client.websocket_connect("/api/v1/realtime/composed-voice", headers=public_headers()) as websocket:
        websocket.send_json(
            {
                "type": "session.start",
                "project_id": project["id"],
                "conversation_id": conversation_id,
            }
        )
        ready = websocket.receive_json()
        assert ready["type"] == "session.ready"

        websocket.send_bytes(b"pcm-turn-1")
        websocket.send_json({"type": "audio.stop"})

        first = websocket.receive_json()
        assert first == {"type": "transcript.final", "text": "我现在是大一。"}

        websocket.send_bytes(b"pcm-turn-2")
        ack = websocket.receive_json()
        assert ack == {"type": "interrupt.ack"}

        websocket.send_json({"type": "audio.stop"})

        second = websocket.receive_json()
        assert second == {
            "type": "transcript.final",
            "text": "我现在是大一。我在哪儿上大学？",
        }

        assistant_chunk = websocket.receive_json()
        assert assistant_chunk == {
            "type": "response.text",
            "text": "你刚才补充了年级和学校问题。",
        }

        audio_meta = websocket.receive_json()
        assert audio_meta["type"] == "audio.meta"

        audio = websocket.receive_bytes()
        assert audio == b"fake-mp3"

        done = websocket.receive_json()
        assert done == {"type": "response.done"}

        websocket.send_json({"type": "session.end"})
        try:
            close_event = websocket.receive()
        except WebSocketDisconnect:
            close_event = None
        if close_event is not None:
            if close_event["type"] == "websocket.send":
                persisted_payload = json.loads(close_event["text"])
                assert persisted_payload["type"] == "turn.persisted"
                close_event = websocket.receive()
            assert close_event["type"] == "websocket.close"

    assert interrupted.is_set()
    assert orchestrate_calls == [
        "我现在是大一。",
        "我现在是大一。我在哪儿上大学？",
    ]


def test_realtime_dictate_websocket_streams_partial_and_final_transcripts(monkeypatch) -> None:
    monkeypatch.setattr(realtime_router.settings, "dashscope_api_key", "test-key")

    class FakeRealtimeBridge:
        def __init__(self, model: str) -> None:
            assert model == "qwen3-asr-flash-realtime"
            self.events: asyncio.Queue[dict[str, str]] = asyncio.Queue()

        async def connect(self) -> None:
            return None

        async def send_audio_chunk(self, audio_bytes: bytes) -> None:
            assert audio_bytes == b"pcm-turn"
            await self.events.put({"type": "transcript.partial", "text": "你"})

        async def commit(self) -> None:
            await self.events.put({"type": "transcript.final", "text": "你好世界"})

        async def next_event(self) -> dict[str, str]:
            return await self.events.get()

        async def close(self) -> None:
            return None

    monkeypatch.setattr(realtime_router, "RealtimeTranscriptionBridge", FakeRealtimeBridge)

    client = TestClient(main_module.app)
    register_user(client, "realtime-dictate@example.com", "Realtime Dictate")
    project = create_project(client, "Realtime Dictate Project")
    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Realtime Dictate Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200
    conversation_id = conversation.json()["id"]

    with client.websocket_connect("/api/v1/realtime/dictate", headers=public_headers()) as websocket:
        websocket.send_json(
            {
                "type": "session.start",
                "project_id": project["id"],
                "conversation_id": conversation_id,
            }
        )

        ready = websocket.receive_json()
        assert ready == {"type": "session.ready"}

        websocket.send_bytes(b"pcm-turn")
        partial = websocket.receive_json()
        assert partial == {"type": "transcript.partial", "text": "你"}

        websocket.send_json({"type": "audio.stop"})
        final = websocket.receive_json()
        assert final == {"type": "transcript.final", "text": "你好世界"}

        websocket.send_json({"type": "session.end"})
        with pytest.raises(WebSocketDisconnect):
            websocket.receive_json()


def test_realtime_dictate_websocket_surfaces_upstream_connect_failure(monkeypatch) -> None:
    monkeypatch.setattr(realtime_router.settings, "dashscope_api_key", "test-key")

    class FakeRealtimeBridge:
        def __init__(self, model: str) -> None:
            assert model == "qwen3-asr-flash-realtime"

        async def connect(self) -> None:
            raise realtime_router.UpstreamServiceError("boom")

        async def close(self) -> None:
            return None

    monkeypatch.setattr(realtime_router, "RealtimeTranscriptionBridge", FakeRealtimeBridge)

    client = TestClient(main_module.app)
    register_user(client, "realtime-dictate-upstream@example.com", "Realtime Dictate Upstream")
    project = create_project(client, "Realtime Dictate Upstream Project")
    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Realtime Dictate Failure Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200
    conversation_id = conversation.json()["id"]

    with client.websocket_connect("/api/v1/realtime/dictate", headers=public_headers()) as websocket:
        websocket.send_json(
            {
                "type": "session.start",
                "project_id": project["id"],
                "conversation_id": conversation_id,
            }
        )

        ready = websocket.receive_json()
        assert ready == {"type": "session.ready"}

        websocket.send_bytes(b"pcm-turn")
        error = websocket.receive_json()
        assert error == {
            "type": "error",
            "code": "upstream_unavailable",
            "message": "AI 暂时无响应，请重试",
        }

        with pytest.raises(WebSocketDisconnect):
            websocket.receive_json()


def test_composed_realtime_websocket_falls_back_to_text_when_tts_fails(monkeypatch) -> None:
    monkeypatch.setattr(realtime_router.settings, "dashscope_api_key", "test-key")
    async def fake_orchestrate(
        _db,
        *,
        workspace_id: str,
        project_id: str,
        conversation_id: str,
        user_text: str,
        image_bytes: bytes | None = None,
        image_mime_type: str = "image/jpeg",
        video_bytes: bytes | None = None,
        video_mime_type: str = "video/mp4",
    ) -> dict[str, str]:
        assert workspace_id
        assert project_id
        assert conversation_id
        assert user_text == "你好"
        _ = image_bytes
        _ = image_mime_type
        _ = video_bytes
        _ = video_mime_type
        return {"text_input": "你好", "text_response": "这次先看文字。"}

    async def fake_tts(_db, *, project_id: str, text: str) -> bytes:
        assert project_id
        assert text == "这次先看文字。"
        raise realtime_router.UpstreamServiceError("tts boom")

    class FakeRealtimeBridge:
        def __init__(self, model: str) -> None:
            self.model = model
            self.events: asyncio.Queue[dict[str, str]] = asyncio.Queue()

        async def connect(self) -> None:
            return None

        async def send_audio_chunk(self, audio_bytes: bytes) -> None:
            assert audio_bytes == b"pcm-turn"

        async def commit(self) -> None:
            await self.events.put({"type": "transcript.final", "text": "你好"})

        async def next_event(self) -> dict[str, str]:
            return await self.events.get()

        async def close(self) -> None:
            return None

    monkeypatch.setattr(realtime_router, "RealtimeTranscriptionBridge", FakeRealtimeBridge)
    monkeypatch.setattr("app.services.composed_realtime.orchestrate_synthetic_realtime_turn_from_text", fake_orchestrate)
    monkeypatch.setattr("app.services.composed_realtime.synthesize_realtime_speech_for_project", fake_tts)

    client = TestClient(main_module.app)
    register_user(client, "synthetic-tts-fallback@example.com", "Synthetic TTS Fallback")
    project = create_project(client, "Synthetic TTS Fallback Project")
    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Synthetic Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200
    conversation_id = conversation.json()["id"]

    with client.websocket_connect("/api/v1/realtime/composed-voice", headers=public_headers()) as websocket:
        websocket.send_json(
            {
                "type": "session.start",
                "project_id": project["id"],
                "conversation_id": conversation_id,
            }
        )
        ready = websocket.receive_json()
        assert ready["type"] == "session.ready"

        websocket.send_bytes(b"pcm-turn")
        websocket.send_json({"type": "audio.stop"})

        transcript = websocket.receive_json()
        assert transcript == {"type": "transcript.final", "text": "你好"}

        assistant_chunk = websocket.receive_json()
        assert assistant_chunk == {"type": "response.text", "text": "这次先看文字。"}

        done = websocket.receive_json()
        assert done == {"type": "response.done"}

        notice = websocket.receive_json()
        assert notice == {
            "type": "turn.notice",
            "code": "audio_unavailable",
            "message": "语音输出暂时不可用，已切换为文字回复",
        }

        websocket.send_json({"type": "session.end"})
        try:
            close_event = websocket.receive()
        except WebSocketDisconnect:
            close_event = None
        if close_event is not None:
            if close_event["type"] == "websocket.send":
                persisted_payload = json.loads(close_event["text"])
                assert persisted_payload["type"] == "turn.persisted"
                close_event = websocket.receive()
            assert close_event["type"] == "websocket.close"


def test_composed_realtime_websocket_streams_partial_transcript_before_turn_completion(monkeypatch) -> None:
    monkeypatch.setattr(realtime_router.settings, "dashscope_api_key", "test-key")

    async def fake_orchestrate(
        _db,
        *,
        workspace_id: str,
        project_id: str,
        conversation_id: str,
        user_text: str,
        image_bytes: bytes | None = None,
        image_mime_type: str = "image/jpeg",
        video_bytes: bytes | None = None,
        video_mime_type: str = "video/mp4",
    ) -> dict[str, str]:
        assert workspace_id
        assert project_id
        assert conversation_id
        assert user_text == "你好"
        _ = image_bytes
        _ = image_mime_type
        _ = video_bytes
        _ = video_mime_type
        return {"text_input": "你好", "text_response": "我收到了。"}

    async def fake_tts(_db, *, project_id: str, text: str) -> bytes:
        assert project_id
        assert text == "我收到了。"
        return b""

    class FakeRealtimeBridge:
        def __init__(self, model: str) -> None:
            self.model = model
            self.events: asyncio.Queue[dict[str, str]] = asyncio.Queue()

        async def connect(self) -> None:
            return None

        async def send_audio_chunk(self, audio_bytes: bytes) -> None:
            assert audio_bytes == b"pcm-turn"
            await self.events.put({"type": "transcript.partial", "text": "你"})

        async def commit(self) -> None:
            await self.events.put({"type": "transcript.final", "text": "你好"})

        async def next_event(self) -> dict[str, str]:
            return await self.events.get()

        async def close(self) -> None:
            return None

    monkeypatch.setattr(realtime_router, "RealtimeTranscriptionBridge", FakeRealtimeBridge)
    monkeypatch.setattr("app.services.composed_realtime.orchestrate_synthetic_realtime_turn_from_text", fake_orchestrate)
    monkeypatch.setattr("app.services.composed_realtime.synthesize_realtime_speech_for_project", fake_tts)

    client = TestClient(main_module.app)
    register_user(client, "synthetic-partial@example.com", "Synthetic Partial")
    project = create_project(client, "Synthetic Partial Project")
    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Synthetic Partial Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200
    conversation_id = conversation.json()["id"]

    with client.websocket_connect("/api/v1/realtime/composed-voice", headers=public_headers()) as websocket:
        websocket.send_json(
            {
                "type": "session.start",
                "project_id": project["id"],
                "conversation_id": conversation_id,
            }
        )
        ready = websocket.receive_json()
        assert ready["type"] == "session.ready"

        websocket.send_bytes(b"pcm-turn")
        partial = websocket.receive_json()
        assert partial == {"type": "transcript.partial", "text": "你"}

        websocket.send_json({"type": "audio.stop"})
        final = websocket.receive_json()
        assert final == {"type": "transcript.final", "text": "你好"}

        assistant_chunk = websocket.receive_json()
        assert assistant_chunk == {"type": "response.text", "text": "我收到了。"}

        done = websocket.receive_json()
        assert done == {"type": "response.done"}

        websocket.send_json({"type": "session.end"})
        try:
            close_event = websocket.receive()
        except WebSocketDisconnect:
            close_event = None
        if close_event is not None:
            if close_event["type"] == "websocket.send":
                persisted_payload = json.loads(close_event["text"])
                assert persisted_payload["type"] == "turn.persisted"
                close_event = websocket.receive()
            assert close_event["type"] == "websocket.close"


def test_composed_realtime_uses_buffered_partial_when_commit_returns_empty(monkeypatch) -> None:
    monkeypatch.setattr(realtime_router.settings, "dashscope_api_key", "test-key")

    async def fake_orchestrate(
        _db,
        *,
        workspace_id: str,
        project_id: str,
        conversation_id: str,
        user_text: str,
        image_bytes: bytes | None = None,
        image_mime_type: str = "image/jpeg",
        video_bytes: bytes | None = None,
        video_mime_type: str = "video/mp4",
    ) -> dict[str, str]:
        assert workspace_id
        assert project_id
        assert conversation_id
        assert user_text == "现在几点了"
        assert image_bytes is None
        assert image_mime_type == "image/jpeg"
        assert video_bytes is None
        _ = video_mime_type
        return {"text_input": user_text, "text_response": "现在是测试时间。"}

    async def fake_tts(_db, *, project_id: str, text: str) -> bytes:
        assert project_id
        assert text == "现在是测试时间。"
        return b"fake-mp3"

    class FakeRealtimeBridge:
        def __init__(self, model: str) -> None:
            self.model = model
            self.events: asyncio.Queue[dict[str, str]] = asyncio.Queue()

        async def connect(self) -> None:
            return None

        async def send_audio_chunk(self, audio_bytes: bytes) -> None:
            assert audio_bytes == b"pcm-turn"
            await self.events.put({"type": "transcript.partial", "text": "现在几点了"})

        async def commit(self) -> None:
            await self.events.put({"type": "transcript.empty", "text": ""})

        async def next_event(self) -> dict[str, str]:
            return await self.events.get()

        async def close(self) -> None:
            return None

    monkeypatch.setattr(realtime_router, "RealtimeTranscriptionBridge", FakeRealtimeBridge)
    monkeypatch.setattr(
        "app.services.composed_realtime.orchestrate_synthetic_realtime_turn_from_text",
        fake_orchestrate,
    )
    monkeypatch.setattr(
        "app.services.composed_realtime.synthesize_realtime_speech_for_project",
        fake_tts,
    )

    client = TestClient(main_module.app)
    register_user(client, "synthetic-buffered-partial@example.com", "Synthetic Buffered Partial")
    project = create_project(client, "Synthetic Buffered Partial Project")
    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Synthetic Buffered Partial Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200
    conversation_id = conversation.json()["id"]

    with client.websocket_connect("/api/v1/realtime/composed-voice", headers=public_headers()) as websocket:
        websocket.send_json(
            {
                "type": "session.start",
                "project_id": project["id"],
                "conversation_id": conversation_id,
            }
        )
        ready = websocket.receive_json()
        assert ready["type"] == "session.ready"

        websocket.send_bytes(b"pcm-turn")
        partial = websocket.receive_json()
        assert partial == {"type": "transcript.partial", "text": "现在几点了"}

        websocket.send_json({"type": "audio.stop"})

        assistant_chunk = websocket.receive_json()
        assert assistant_chunk == {"type": "response.text", "text": "现在是测试时间。"}

        audio_meta = websocket.receive_json()
        assert audio_meta["type"] == "audio.meta"

        audio = websocket.receive_bytes()
        assert audio == b"fake-mp3"

        done = websocket.receive_json()
        assert done == {"type": "response.done"}

def test_composed_realtime_media_is_cleared_after_turn_starts(monkeypatch) -> None:
    monkeypatch.setattr(realtime_router.settings, "dashscope_api_key", "test-key")
    async def fake_orchestrate(
        _db,
        *,
        workspace_id: str,
        project_id: str,
        conversation_id: str,
        user_text: str,
        image_bytes: bytes | None = None,
        image_mime_type: str = "image/jpeg",
        video_bytes: bytes | None = None,
        video_mime_type: str = "video/mp4",
    ) -> dict[str, str]:
        assert workspace_id
        assert project_id
        assert conversation_id
        assert user_text == "看图"
        assert image_bytes is not None
        assert image_mime_type == "image/jpeg"
        assert video_bytes is None
        _ = video_mime_type
        return {"text_input": "看图", "text_response": "已看到图片。"}

    async def fake_tts(_db, *, project_id: str, text: str) -> bytes:
        assert project_id
        assert text == "已看到图片。"
        return b"fake-mp3"

    async def fake_persist(_ws, _session, user_text: str, ai_text: str, **kwargs) -> None:
        del _ws, _session, kwargs
        assert user_text == "看图"
        assert ai_text == "已看到图片。"

    class FakeRealtimeBridge:
        def __init__(self, model: str) -> None:
            self.model = model
            self.events: asyncio.Queue[dict[str, str]] = asyncio.Queue()

        async def connect(self) -> None:
            return None

        async def send_audio_chunk(self, audio_bytes: bytes) -> None:
            assert audio_bytes == b"pcm-turn"

        async def commit(self) -> None:
            await self.events.put({"type": "transcript.final", "text": "看图"})

        async def next_event(self) -> dict[str, str]:
            return await self.events.get()

        async def close(self) -> None:
            return None

    monkeypatch.setattr(realtime_router, "RealtimeTranscriptionBridge", FakeRealtimeBridge)
    monkeypatch.setattr("app.services.composed_realtime.orchestrate_synthetic_realtime_turn_from_text", fake_orchestrate)
    monkeypatch.setattr("app.services.composed_realtime.synthesize_realtime_speech_for_project", fake_tts)
    monkeypatch.setattr("app.routers.realtime._persist_composed_turn", fake_persist)

    client = TestClient(main_module.app)
    register_user(client, "synthetic-clear@example.com", "Synthetic Clear")
    project = create_project(client, "Synthetic Clear Project")
    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Synthetic Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200
    conversation_id = conversation.json()["id"]
    image_bytes, _ = upload_fixture("frame.jpg")
    image_payload = f"data:image/jpeg;base64,{base64.b64encode(image_bytes).decode()}"

    with client.websocket_connect("/api/v1/realtime/composed-voice", headers=public_headers()) as websocket:
        websocket.send_json(
            {
                "type": "session.start",
                "project_id": project["id"],
                "conversation_id": conversation_id,
            }
        )
        ready = websocket.receive_json()
        assert ready["type"] == "session.ready"

        websocket.send_json({"type": "media.set", "data_url": image_payload, "filename": "frame.jpg"})
        attached = websocket.receive_json()
        assert attached["type"] == "media.attached"

        websocket.send_bytes(b"pcm-turn")
        websocket.send_json({"type": "audio.stop"})

        transcript = websocket.receive_json()
        assert transcript == {"type": "transcript.final", "text": "看图"}

        cleared = websocket.receive_json()
        assert cleared == {"type": "media.cleared"}


def test_composed_realtime_camera_frames_are_buffered_as_video_context(monkeypatch) -> None:
    monkeypatch.setattr(realtime_router.settings, "dashscope_api_key", "test-key")

    async def fake_orchestrate(
        _db,
        *,
        workspace_id: str,
        project_id: str,
        conversation_id: str,
        user_text: str,
        image_bytes: bytes | None = None,
        image_mime_type: str = "image/jpeg",
        video_bytes: bytes | None = None,
        video_mime_type: str = "video/mp4",
        video_frame_data_urls: list[str] | None = None,
        video_fps: float = 1.0,
    ) -> dict[str, str]:
        assert workspace_id
        assert project_id
        assert conversation_id
        assert user_text == "看图"
        assert image_bytes is None
        assert video_bytes is None
        _ = image_mime_type
        _ = video_mime_type
        assert video_frame_data_urls is not None
        assert len(video_frame_data_urls) == 2
        assert all(frame.startswith("data:image/jpeg;base64,") for frame in video_frame_data_urls)
        assert video_fps == 1.0
        return {"text_input": "看图", "text_response": "我已经结合视频上下文理解了。"}

    async def fake_tts(_db, *, project_id: str, text: str) -> bytes:
        assert project_id
        assert text == "我已经结合视频上下文理解了。"
        return b"fake-mp3"

    class FakeRealtimeBridge:
        def __init__(self, model: str) -> None:
            self.model = model
            self.events: asyncio.Queue[dict[str, str]] = asyncio.Queue()

        async def connect(self) -> None:
            return None

        async def send_audio_chunk(self, audio_bytes: bytes) -> None:
            assert audio_bytes == b"pcm-turn"

        async def commit(self) -> None:
            await self.events.put({"type": "transcript.final", "text": "看图"})

        async def next_event(self) -> dict[str, str]:
            return await self.events.get()

        async def close(self) -> None:
            return None

    monkeypatch.setattr(realtime_router, "RealtimeTranscriptionBridge", FakeRealtimeBridge)
    monkeypatch.setattr("app.services.composed_realtime.orchestrate_synthetic_realtime_turn_from_text", fake_orchestrate)
    monkeypatch.setattr("app.services.composed_realtime.synthesize_realtime_speech_for_project", fake_tts)

    client = TestClient(main_module.app)
    register_user(client, "synthetic-frame-video@example.com", "Synthetic Frame Video")
    project = create_project(client, "Synthetic Frame Video Project")
    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Synthetic Frame Video Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200
    conversation_id = conversation.json()["id"]
    image_bytes, _ = upload_fixture("frame.jpg")
    image_payload = f"data:image/jpeg;base64,{base64.b64encode(image_bytes).decode()}"

    with client.websocket_connect("/api/v1/realtime/composed-voice", headers=public_headers()) as websocket:
        websocket.send_json(
            {
                "type": "session.start",
                "project_id": project["id"],
                "conversation_id": conversation_id,
            }
        )
        ready = websocket.receive_json()
        assert ready["type"] == "session.ready"

        websocket.send_json({"type": "media.frame.append", "data_url": image_payload, "fps": 1})
        websocket.send_json({"type": "media.frame.append", "data_url": image_payload, "fps": 1})
        websocket.send_bytes(b"pcm-turn")
        websocket.send_json({"type": "audio.stop"})

        transcript = websocket.receive_json()
        assert transcript == {"type": "transcript.final", "text": "看图"}

        cleared = websocket.receive_json()
        assert cleared == {"type": "media.cleared"}

        assistant_chunk = websocket.receive_json()
        assert assistant_chunk == {
            "type": "response.text",
            "text": "我已经结合视频上下文理解了。",
        }


def test_composed_realtime_preserves_pending_media_when_first_transcription_is_empty(monkeypatch) -> None:
    monkeypatch.setattr(realtime_router.settings, "dashscope_api_key", "test-key")

    async def fake_orchestrate(
        _db,
        *,
        workspace_id: str,
        project_id: str,
        conversation_id: str,
        user_text: str,
        image_bytes: bytes | None = None,
        image_mime_type: str = "image/jpeg",
        video_bytes: bytes | None = None,
        video_mime_type: str = "video/mp4",
    ) -> dict[str, str]:
        assert workspace_id
        assert project_id
        assert conversation_id
        assert user_text == "看图"
        assert image_bytes is not None
        assert image_mime_type == "image/jpeg"
        assert video_bytes is None
        _ = video_mime_type
        return {"text_input": "看图", "text_response": "已看到图片。"}

    async def fake_tts(_db, *, project_id: str, text: str) -> bytes:
        assert project_id
        assert text == "已看到图片。"
        return b"fake-mp3"

    commit_counter = {"count": 0}

    class FakeRealtimeBridge:
        def __init__(self, model: str) -> None:
            self.model = model
            self.events: asyncio.Queue[dict[str, str]] = asyncio.Queue()

        async def connect(self) -> None:
            return None

        async def send_audio_chunk(self, audio_bytes: bytes) -> None:
            assert audio_bytes in {b"pcm-empty", b"pcm-final"}

        async def commit(self) -> None:
            commit_counter["count"] += 1
            if commit_counter["count"] == 1:
                await self.events.put({"type": "transcript.empty", "text": ""})
            else:
                await self.events.put({"type": "transcript.final", "text": "看图"})

        async def next_event(self) -> dict[str, str]:
            return await self.events.get()

        async def close(self) -> None:
            return None

    monkeypatch.setattr(realtime_router, "RealtimeTranscriptionBridge", FakeRealtimeBridge)
    monkeypatch.setattr("app.services.composed_realtime.orchestrate_synthetic_realtime_turn_from_text", fake_orchestrate)
    monkeypatch.setattr("app.services.composed_realtime.synthesize_realtime_speech_for_project", fake_tts)

    client = TestClient(main_module.app)
    register_user(client, "synthetic-empty-media@example.com", "Synthetic Empty Media")
    project = create_project(client, "Synthetic Empty Media Project")
    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Synthetic Empty Media Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200
    conversation_id = conversation.json()["id"]
    image_bytes, _ = upload_fixture("frame.jpg")
    image_payload = f"data:image/jpeg;base64,{base64.b64encode(image_bytes).decode()}"

    with client.websocket_connect("/api/v1/realtime/composed-voice", headers=public_headers()) as websocket:
        websocket.send_json(
            {
                "type": "session.start",
                "project_id": project["id"],
                "conversation_id": conversation_id,
            }
        )
        ready = websocket.receive_json()
        assert ready["type"] == "session.ready"

        websocket.send_json({"type": "media.set", "data_url": image_payload, "filename": "frame.jpg"})
        attached = websocket.receive_json()
        assert attached["type"] == "media.attached"

        websocket.send_bytes(b"pcm-empty")
        websocket.send_json({"type": "audio.stop"})
        notice = websocket.receive_json()
        assert notice == {
            "type": "turn.notice",
            "code": "empty_transcription",
            "message": "未识别到语音，请重试。",
        }

        websocket.send_bytes(b"pcm-final")
        websocket.send_json({"type": "audio.stop"})

        final = websocket.receive_json()
        assert final == {"type": "transcript.final", "text": "看图"}

        cleared = websocket.receive_json()
        assert cleared == {"type": "media.cleared"}

        assistant_chunk = websocket.receive_json()
        assert assistant_chunk == {"type": "response.text", "text": "已看到图片。"}

        audio_meta = websocket.receive_json()
        assert audio_meta["type"] == "audio.meta"

        audio = websocket.receive_bytes()
        assert audio == b"fake-mp3"

        done = websocket.receive_json()
        assert done["type"] == "response.done"


def test_composed_realtime_media_set_rejects_oversized_payload(monkeypatch) -> None:
    monkeypatch.setattr(realtime_router.settings, "dashscope_api_key", "test-key")
    monkeypatch.setattr(realtime_router.settings, "realtime_media_max_mb", 0)

    client = TestClient(main_module.app)
    register_user(client, "synthetic-large@example.com", "Synthetic Large")
    project = create_project(client, "Synthetic Large Project")
    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Synthetic Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200

    image_bytes, _ = upload_fixture("frame.jpg")
    image_payload = f"data:image/jpeg;base64,{base64.b64encode(image_bytes).decode()}"

    with client.websocket_connect("/api/v1/realtime/composed-voice", headers=public_headers()) as websocket:
        websocket.send_json(
            {
                "type": "session.start",
                "project_id": project["id"],
                "conversation_id": conversation.json()["id"],
            }
        )
        assert websocket.receive_json()["type"] == "session.ready"

        websocket.send_json({"type": "media.set", "data_url": image_payload, "filename": "frame.jpg"})
        error = websocket.receive_json()
        assert error["type"] == "error"
        assert error["code"] == "payload_too_large"


def test_composed_realtime_media_set_rejects_signature_mismatch(monkeypatch) -> None:
    monkeypatch.setattr(realtime_router.settings, "dashscope_api_key", "test-key")
    client = TestClient(main_module.app)
    register_user(client, "synthetic-mismatch@example.com", "Synthetic Mismatch")
    project = create_project(client, "Synthetic Mismatch Project")
    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Synthetic Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200

    bad_payload = f"data:image/jpeg;base64,{base64.b64encode(b'<html>not-a-jpeg</html>').decode()}"

    with client.websocket_connect("/api/v1/realtime/composed-voice", headers=public_headers()) as websocket:
        websocket.send_json(
            {
                "type": "session.start",
                "project_id": project["id"],
                "conversation_id": conversation.json()["id"],
            }
        )
        assert websocket.receive_json()["type"] == "session.ready"

        websocket.send_json({"type": "media.set", "data_url": bad_payload, "filename": "frame.jpg"})
        error = websocket.receive_json()
        assert error["type"] == "error"
        assert error["code"] == "upload_mismatch"


def test_pipeline_patch_downgrades_synthetic_default_when_llm_loses_vision() -> None:
    client = TestClient(main_module.app)
    register_user(client, "pipeline-vision-downgrade@example.com", "Pipeline Vision Downgrade")
    project = create_project(client, "Pipeline Vision Downgrade Project")

    set_mode = client.patch(
        f"/api/v1/projects/{project['id']}",
        json={"default_chat_mode": "synthetic_realtime"},
        headers=csrf_headers(client),
    )
    assert set_mode.status_code == 200
    assert set_mode.json()["default_chat_mode"] == "synthetic_realtime"

    update_llm = client.patch(
        "/api/v1/pipeline",
        json={
          "project_id": project["id"],
          "model_type": "llm",
          "model_id": "deepseek-r1",
          "config_json": {},
        },
        headers=csrf_headers(client),
    )
    assert update_llm.status_code == 200

    refreshed = client.get(f"/api/v1/projects/{project['id']}")
    assert refreshed.status_code == 200
    assert refreshed.json()["default_chat_mode"] == "standard"


def test_reset_code_survives_incorrect_attempt() -> None:
    client = TestClient(main_module.app)
    register_user(client, "reset-code@example.com", "Reset Code")

    code = issue_verification_code(client, "reset-code@example.com", "reset")
    wrong = client.post(
        "/api/v1/auth/reset-password",
        json={"email": "reset-code@example.com", "password": "newpass1234pass", "code": "000000"},
        headers=public_headers(),
    )
    assert wrong.status_code == 400
    assert runtime_state.get_json("verify_code", verification_code_key("reset-code@example.com", "reset")) is not None

    correct = client.post(
        "/api/v1/auth/reset-password",
        json={"email": "reset-code@example.com", "password": "newpass1234pass", "code": code},
        headers=public_headers(),
    )
    assert correct.status_code == 200
    assert runtime_state.get_json("verify_code", verification_code_key("reset-code@example.com", "reset")) is None


def test_login_uses_dummy_verifier_for_missing_users(monkeypatch) -> None:
    client = TestClient(main_module.app)
    register_user(client, "login-existing@example.com", "Login Existing")

    verifier_inputs: list[str | None] = []

    def fake_verify_password_or_dummy(password: str, hashed_password: str | None) -> bool:
        verifier_inputs.append(hashed_password)
        return False

    monkeypatch.setattr(auth_router, "verify_password_or_dummy", fake_verify_password_or_dummy)

    missing = client.post(
        "/api/v1/auth/login",
        json={"email": "missing-login@example.com", "password": "badpass12345"},
        headers=public_headers(),
    )
    existing = client.post(
        "/api/v1/auth/login",
        json={"email": "login-existing@example.com", "password": "badpass12345"},
        headers=public_headers(),
    )

    assert missing.status_code == 401
    assert existing.status_code == 401
    assert verifier_inputs[0] is None
    assert isinstance(verifier_inputs[1], str) and verifier_inputs[1]


def test_unauthorized_error_shape() -> None:
    client = TestClient(main_module.app)
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 401
    err = resp.json()["error"]
    assert err["code"] == "unauthorized"
    assert isinstance(err["request_id"], str)
    assert err["request_id"]


def test_local_loopback_origins_are_allowed_for_auth() -> None:
    client = TestClient(main_module.app)
    resp = client.post(
        "/api/v1/auth/send-code",
        json={"email": "loopback@example.com", "purpose": "register"},
        headers={"origin": "http://127.0.0.1:3102"},
    )
    assert resp.status_code == 200

    blocked = client.post(
        "/api/v1/auth/send-code",
        json={"email": "blocked@example.com", "purpose": "register"},
        headers={"origin": "http://evil.example"},
    )
    assert blocked.status_code == 403


def test_workspace_rbac_forbidden() -> None:
    owner = TestClient(main_module.app)
    owner_info = register_user(owner, "owner@example.com", "Owner")
    owner_workspace_id = owner_info["workspace"]["id"]

    p1 = owner.post(
        "/api/v1/projects",
        json={"name": "P1", "description": "demo"},
        headers=csrf_headers(owner),
    )
    assert p1.status_code == 200

    other = TestClient(main_module.app)
    register_user(other, "other@example.com", "Other")

    resp = other.get("/api/v1/projects", headers={"x-workspace-id": owner_workspace_id})
    assert resp.status_code == 403


def test_workspace_header_is_required_when_user_has_multiple_workspaces() -> None:
    client = TestClient(main_module.app)
    user_info = register_user(client, "multi-workspace@example.com", "Multi Workspace")
    user_id = user_info["user"]["id"]

    with SessionLocal() as db:
        second_workspace = Workspace(name="Second Workspace", plan="free")
        db.add(second_workspace)
        db.flush()
        db.add(Membership(workspace_id=second_workspace.id, user_id=user_id, role="owner"))
        db.commit()
        second_workspace_id = second_workspace.id

    create_second = client.post(
        "/api/v1/projects",
        json={"name": "Workspace B Project", "description": "demo"},
        headers=csrf_headers(client, second_workspace_id),
    )
    assert create_second.status_code == 200

    ambiguous = client.get("/api/v1/projects", headers=public_headers())
    assert ambiguous.status_code == 409
    assert ambiguous.json()["error"]["code"] == "workspace_required"


def test_workspace_cookie_selects_membership_when_user_has_multiple_workspaces() -> None:
    client = TestClient(main_module.app)
    user_info = register_user(client, "multi-workspace-cookie@example.com", "Multi Workspace Cookie")
    user_id = user_info["user"]["id"]

    with SessionLocal() as db:
        second_workspace = Workspace(name="Cookie Workspace", plan="free")
        db.add(second_workspace)
        db.flush()
        db.add(Membership(workspace_id=second_workspace.id, user_id=user_id, role="owner"))
        db.commit()
        second_workspace_id = second_workspace.id

    create_second = client.post(
        "/api/v1/projects",
        json={"name": "Cookie Workspace Project", "description": "demo"},
        headers=csrf_headers(client, second_workspace_id),
    )
    assert create_second.status_code == 200

    client.cookies.set("mingrun_workspace_id", second_workspace_id)
    selected = client.get("/api/v1/projects", headers=public_headers())
    assert selected.status_code == 200
    assert [project["name"] for project in selected.json()["items"]] == ["Cookie Workspace Project"]


def test_conversation_access_respects_role_and_creator_boundary(monkeypatch) -> None:
    monkeypatch.setattr(chat_router.settings, "dashscope_api_key", "test-key")
    async def fake_orchestrate_inference(*args, **kwargs):
        return "mocked reply"
    monkeypatch.setattr(chat_router, "orchestrate_inference", fake_orchestrate_inference)
    owner = TestClient(main_module.app)
    owner_info = register_user(owner, "owner-boundary@example.com", "Owner Boundary")
    owner_workspace_id = owner_info["workspace"]["id"]
    project = create_project(owner, "Boundary Project")

    owner_conversation = owner.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Owner Thread"},
        headers=csrf_headers(owner),
    )
    assert owner_conversation.status_code == 200
    owner_conversation_id = owner_conversation.json()["id"]

    editor = TestClient(main_module.app)
    register_user(editor, "editor-boundary@example.com", "Editor Boundary")
    add_workspace_membership(owner_workspace_id, "editor-boundary@example.com", "editor")

    viewer = TestClient(main_module.app)
    register_user(viewer, "viewer-boundary@example.com", "Viewer Boundary")
    viewer_user_id = add_workspace_membership(owner_workspace_id, "viewer-boundary@example.com", "viewer")

    editor_conversation = editor.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Editor Thread"},
        headers=csrf_headers(editor, owner_workspace_id),
    )
    assert editor_conversation.status_code == 200
    editor_conversation_id = editor_conversation.json()["id"]

    viewer_conversation_id = create_conversation_record(
        owner_workspace_id,
        project["id"],
        viewer_user_id,
        "Viewer Thread",
    )

    viewer_list = viewer.get(
        f"/api/v1/chat/conversations?project_id={project['id']}",
        headers={"x-workspace-id": owner_workspace_id},
    )
    assert viewer_list.status_code == 200
    assert [item["id"] for item in viewer_list.json()] == [viewer_conversation_id]

    viewer_create = viewer.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Viewer Create"},
        headers=csrf_headers(viewer, owner_workspace_id),
    )
    assert viewer_create.status_code == 403

    viewer_write = viewer.post(
        f"/api/v1/chat/conversations/{viewer_conversation_id}/messages",
        json={"content": "viewer cannot write"},
        headers=csrf_headers(viewer, owner_workspace_id),
    )
    assert viewer_write.status_code == 403

    viewer_owner_access = viewer.get(
        f"/api/v1/chat/conversations/{owner_conversation_id}/messages",
        headers={"x-workspace-id": owner_workspace_id},
    )
    assert viewer_owner_access.status_code == 404

    editor_owner_access = editor.get(
        f"/api/v1/chat/conversations/{owner_conversation_id}/messages",
        headers={"x-workspace-id": owner_workspace_id},
    )
    assert editor_owner_access.status_code == 404

    editor_send = editor.post(
        f"/api/v1/chat/conversations/{editor_conversation_id}/messages",
        json={"content": "editor can write"},
        headers=csrf_headers(editor, owner_workspace_id),
    )
    assert editor_send.status_code == 200

    owner_view = owner.get(
        f"/api/v1/chat/conversations/{viewer_conversation_id}/messages",
        headers={"x-workspace-id": owner_workspace_id},
    )
    assert owner_view.status_code == 200


def test_viewer_role_is_read_only_across_workspace_mutations() -> None:
    owner = TestClient(main_module.app)
    owner_info = register_user(owner, "viewer-authz-owner@example.com", "Viewer Authz Owner")
    owner_workspace_id = owner_info["workspace"]["id"]
    project = create_project(owner, "Viewer Authz Project")
    dataset = create_dataset(owner, project["id"], "Viewer Authz Dataset")
    upload_item(owner, dataset["id"], "viewer-authz.jpg")
    version = commit_dataset(owner, dataset["id"], "seed dataset")

    model_resp = owner.post(
        "/api/v1/models",
        json={"project_id": project["id"], "name": "Viewer Authz Model", "task_type": "general"},
        headers=csrf_headers(owner),
    )
    assert model_resp.status_code == 200
    model_id = model_resp.json()["model"]["id"]

    viewer = TestClient(main_module.app)
    register_user(viewer, "viewer-authz@example.com", "Viewer Authz")
    add_workspace_membership(owner_workspace_id, "viewer-authz@example.com", "viewer")
    viewer_headers = csrf_headers(viewer, owner_workspace_id)

    responses = [
        viewer.patch(
            f"/api/v1/projects/{project['id']}",
            json={"name": "Blocked Rename"},
            headers=viewer_headers,
        ),
        viewer.post(
            "/api/v1/datasets",
            json={"project_id": project["id"], "name": "Blocked Dataset", "type": "images"},
            headers=viewer_headers,
        ),
        viewer.patch(
            "/api/v1/pipeline",
            json={"project_id": project["id"], "model_type": "llm", "model_id": "qwen3.5-plus", "config_json": {}},
            headers=viewer_headers,
        ),
        viewer.post(
            "/api/v1/uploads/presign",
            json={
                "dataset_id": dataset["id"],
                "filename": "blocked.jpg",
                "media_type": "image/jpeg",
                "size_bytes": 16,
            },
            headers=viewer_headers,
        ),
        viewer.post(
            "/api/v1/models",
            json={"project_id": project["id"], "name": "Blocked Model", "task_type": "general"},
            headers=viewer_headers,
        ),
        viewer.post(
            f"/api/v1/models/{model_id}/artifact-uploads/presign",
            json={"filename": "blocked.json", "media_type": "application/json", "size_bytes": 16},
            headers=viewer_headers,
        ),
        viewer.delete(
            f"/api/v1/projects/{project['id']}",
            headers=viewer_headers,
        ),
    ]

    for response in responses:
        assert response.status_code == 403



def test_upload_complete_triggers_processing() -> None:
    client = TestClient(main_module.app)
    register_user(client, "uploader@example.com", "Uploader")
    project = create_project(client, "Upload Project")
    dataset = create_dataset(client, project["id"], "Upload Dataset")

    data_item_id = upload_item(client, dataset["id"], "sample scene.jpg")

    items_resp = client.get(f"/api/v1/datasets/{dataset['id']}/items")
    assert items_resp.status_code == 200
    items = items_resp.json()
    item = next(i for i in items if i["id"] == data_item_id)
    assert item["sha256"] is not None
    assert item["width"] == 1024
    assert item["height"] == 768
    assert item["meta_json"]["processed"] is True
    assert item["meta_json"]["mock"] is True
    assert item["preview_url"]
    assert item["download_url"]
    assert "thumbnail_object_key" not in item["meta_json"]


def test_upload_presign_rejects_unsafe_active_content_types() -> None:
    client = TestClient(main_module.app)
    register_user(client, "unsafe-upload@example.com", "Unsafe Upload")
    project = create_project(client, "Unsafe Upload Project")
    dataset = create_dataset(client, project["id"], "Unsafe Upload Dataset")

    presign = client.post(
        "/api/v1/uploads/presign",
        json={
            "dataset_id": dataset["id"],
            "filename": "payload.svg",
            "media_type": "image/svg+xml",
            "size_bytes": 128,
        },
        headers=csrf_headers(client),
    )
    assert presign.status_code == 415
    assert presign.json()["error"]["code"] == "unsupported_media_type"


def test_upload_proxy_rejects_mismatched_image_payload() -> None:
    client = TestClient(main_module.app)
    register_user(client, "mismatch-upload@example.com", "Mismatch Upload")
    project = create_project(client, "Mismatch Project")
    dataset = create_dataset(client, project["id"], "Mismatch Dataset")
    payload_bytes = b"<html><body>not-an-image</body></html>"

    presign = client.post(
        "/api/v1/uploads/presign",
        json={
            "dataset_id": dataset["id"],
            "filename": "spoofed.jpg",
            "media_type": "image/jpeg",
            "size_bytes": len(payload_bytes),
        },
        headers=csrf_headers(client),
    )
    assert presign.status_code == 200
    payload = presign.json()

    put_resp = client.put(
        payload["put_url"],
        content=payload_bytes,
        headers={**payload["headers"], **csrf_headers(client)},
    )
    assert put_resp.status_code == 400
    assert put_resp.json()["error"]["code"] == "upload_mismatch"


def test_buffer_upload_body_spools_large_payloads_to_disk() -> None:
    from app.services.upload_validation import (
        UPLOAD_SPOOL_MAX_MEMORY_BYTES,
        buffer_upload_body,
    )

    class DummyUploadRequest:
        def __init__(self, payload: bytes) -> None:
            self.headers = {"content-length": str(len(payload))}
            self._payload = payload

        async def stream(self):
            midpoint = len(self._payload) // 2
            yield self._payload[:midpoint]
            yield self._payload[midpoint:]

    payload = b"x" * (UPLOAD_SPOOL_MAX_MEMORY_BYTES + 1)
    buffered_upload = asyncio.run(
        buffer_upload_body(
            DummyUploadRequest(payload),
            expected_size=len(payload),
            max_bytes=len(payload) + 1024,
        )
    )
    try:
        assert getattr(buffered_upload.file, "_rolled", False) is True
    finally:
        buffered_upload.close()


def test_non_previewable_uploads_do_not_get_preview_url() -> None:
    client = TestClient(main_module.app)
    register_user(client, "preview-safe@example.com", "Preview Safe")
    project = create_project(client, "Preview Project")
    dataset = create_dataset(client, project["id"], "Preview Dataset")

    data_item_id = upload_item(client, dataset["id"], "notes.txt")

    item_resp = client.get(f"/api/v1/data-items/{data_item_id}")
    assert item_resp.status_code == 200
    item = item_resp.json()
    assert item["preview_url"] is None
    assert item["download_url"]


def test_upload_complete_triggers_processing_and_indexing_followups(monkeypatch) -> None:
    class FakeTask:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple]] = []

        def __call__(self, *args):
            self.calls.append(("call", args))

        def delay(self, *args):
            self.calls.append(("delay", args))

    fake_process = FakeTask()
    fake_index = FakeTask()
    monkeypatch.setattr(uploads_router, "process_data_item", fake_process)
    monkeypatch.setattr(uploads_router, "index_data_item", fake_index)

    client = TestClient(main_module.app)
    user_info = register_user(client, "followup@example.com", "Followup User")
    workspace_id = user_info["workspace"]["id"]
    project = create_project(client, "Followup Project")
    dataset = create_dataset(client, project["id"], "Followup Dataset")

    data_item_id = upload_item(client, dataset["id"], "followup.pdf")

    with SessionLocal() as db:
        item = db.get(DataItem, data_item_id)
        assert item is not None
        assert fake_process.calls == [("call", (data_item_id,))]
        assert fake_index.calls == [
            ("call", (workspace_id, project["id"], data_item_id, item.object_key, item.filename))
        ]


def test_upload_is_hidden_until_complete() -> None:
    client = TestClient(main_module.app)
    register_user(client, "ghost@example.com", "Ghost User")
    project = create_project(client, "Ghost Project")
    dataset = create_dataset(client, project["id"], "Ghost Dataset")

    payload_bytes, _ = upload_fixture("ghost.jpg")
    presign = client.post(
        "/api/v1/uploads/presign",
        json={
            "dataset_id": dataset["id"],
            "filename": "ghost.jpg",
            "media_type": "image/jpeg",
            "size_bytes": len(payload_bytes),
        },
        headers=csrf_headers(client),
    )
    assert presign.status_code == 200

    items_before = client.get(f"/api/v1/datasets/{dataset['id']}/items")
    assert items_before.status_code == 200
    assert items_before.json() == []

    payload = presign.json()
    put_resp = client.put(
        payload["put_url"],
        content=payload_bytes,
        headers={**payload["headers"], **csrf_headers(client)},
    )
    assert put_resp.status_code == 200

    complete = client.post(
        "/api/v1/uploads/complete",
        json={"upload_id": payload["upload_id"], "data_item_id": payload["data_item_id"]},
        headers=csrf_headers(client),
    )
    assert complete.status_code == 200

    items_after = client.get(f"/api/v1/datasets/{dataset['id']}/items")
    assert items_after.status_code == 200
    assert [item["filename"] for item in items_after.json()] == ["ghost.jpg"]


def test_upload_presign_uses_post_policy_in_production(monkeypatch) -> None:
    client = TestClient(main_module.app)
    register_user(client, "post@example.com", "Post User")
    project = create_project(client, "Post Project")
    dataset = create_dataset(client, project["id"], "Post Dataset")

    monkeypatch.setattr(config_module.settings, "env", "production")
    monkeypatch.setattr(config_module.settings, "upload_put_proxy", False)
    monkeypatch.setattr(
        uploads_router,
        "create_presigned_post",
        lambda **kwargs: ("https://storage.example/upload", {"key": "object-key", "policy": "signed"}, {}),
    )

    resp = client.post(
        "/api/v1/uploads/presign",
        json={
            "dataset_id": dataset["id"],
            "filename": "post.jpg",
            "media_type": "image/jpeg",
            "size_bytes": 1024,
        },
        headers=csrf_headers(client),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["upload_method"] == "POST"
    assert body["fields"] == {"key": "object-key", "policy": "signed"}
    assert body["headers"] == {}


def test_cleanup_pending_upload_session_removes_orphan_state(monkeypatch) -> None:
    client = TestClient(main_module.app)
    register_user(client, "upload-cleanup@example.com", "Upload Cleanup")
    project = create_project(client, "Upload Cleanup Project")
    dataset = create_dataset(client, project["id"], "Upload Cleanup Dataset")

    presign = client.post(
        "/api/v1/uploads/presign",
        json={
            "dataset_id": dataset["id"],
            "filename": "orphan.jpg",
            "media_type": "image/jpeg",
            "size_bytes": 16,
        },
        headers=csrf_headers(client),
    )
    assert presign.status_code == 200
    payload = presign.json()
    session = runtime_state.get_json(f"upload:{payload['upload_id']}", "session")
    assert session is not None

    deleted: list[tuple[str, str]] = []

    def fake_delete_object(*, bucket_name: str, object_key: str) -> None:
        deleted.append((bucket_name, object_key))

    monkeypatch.setattr(project_cleanup_service, "delete_object", fake_delete_object)

    worker_tasks.cleanup_pending_upload_session(payload["upload_id"])

    assert (config_module.settings.s3_private_bucket, session["object_key"]) in deleted
    assert runtime_state.get_json(f"upload:{payload['upload_id']}", "session") is None


def test_cleanup_deleted_dataset_deletes_objects(monkeypatch) -> None:
    client = TestClient(main_module.app)
    register_user(client, "cleanup@example.com", "Cleanup User")
    project = create_project(client, "Cleanup Project")
    dataset = create_dataset(client, project["id"], "Cleanup Dataset")

    data_item_id = upload_item(client, dataset["id"], "cleanup.jpg")
    with SessionLocal() as db:
        data_item = db.get(DataItem, data_item_id)
        assert data_item is not None
        object_key = data_item.object_key

    deleted: list[tuple[str, str]] = []

    def fake_delete_object(*, bucket_name: str, object_key: str) -> None:
        deleted.append((bucket_name, object_key))

    monkeypatch.setattr(project_cleanup_service, "delete_object", fake_delete_object)

    worker_tasks.cleanup_deleted_dataset(dataset["id"])

    assert (config_module.settings.s3_private_bucket, object_key) in deleted
    with SessionLocal() as db:
        data_item = db.get(DataItem, data_item_id)
        assert data_item is not None
        assert data_item.deleted_at is not None
        assert data_item.meta_json["cleanup_marked"] is True


def test_cleanup_deleted_project_deletes_project_objects(monkeypatch) -> None:
    client = TestClient(main_module.app)
    register_user(client, "project-cleanup@example.com", "Project Cleanup User")
    project = create_project(client, "Project Cleanup")
    dataset = create_dataset(client, project["id"], "Project Cleanup Dataset")
    data_item_id = upload_item(client, dataset["id"], "project-cleanup.jpg")

    model_resp = client.post(
        "/api/v1/models",
        json={"project_id": project["id"], "name": "Cleanup Model", "task_type": "general"},
        headers=csrf_headers(client),
    )
    assert model_resp.status_code == 200
    model_id = model_resp.json()["model"]["id"]
    artifact_upload_id = upload_model_artifact(client, model_id, "project-report.json")

    version_resp = client.post(
        f"/api/v1/models/{model_id}/versions",
        json={"run_id": None, "artifact_upload_id": artifact_upload_id, "metrics_json": {"acc": 0.91}},
        headers=csrf_headers(client),
    )
    assert version_resp.status_code == 200
    model_version_id = version_resp.json()["model_version"]["id"]

    with SessionLocal() as db:
        data_item = db.get(DataItem, data_item_id)
        model_version = db.get(ModelVersion, model_version_id)
        assert data_item is not None
        assert model_version is not None
        data_object_key = data_item.object_key
        model_object_key = model_version.artifact_object_key

    deleted: list[tuple[str, str]] = []

    def fake_delete_object(*, bucket_name: str, object_key: str) -> None:
        deleted.append((bucket_name, object_key))

    monkeypatch.setattr(project_cleanup_service, "delete_object", fake_delete_object)

    worker_tasks.cleanup_deleted_project(project["id"])

    assert (config_module.settings.s3_private_bucket, data_object_key) in deleted
    assert (config_module.settings.s3_private_bucket, model_object_key) in deleted
    with SessionLocal() as db:
        assert db.get(Project, project["id"]) is None
        assert db.query(DataItem).filter(DataItem.id == data_item_id).first() is None
        assert db.query(ModelVersion).filter(ModelVersion.id == model_version_id).first() is None


def test_audit_log_redacts_object_keys() -> None:
    client = TestClient(main_module.app)
    register_user(client, "audit@example.com", "Audit User")
    project = create_project(client, "Audit Project")
    dataset = create_dataset(client, project["id"], "Audit Dataset")

    payload_bytes, _ = upload_fixture("audit.jpg")
    presign = client.post(
        "/api/v1/uploads/presign",
        json={
            "dataset_id": dataset["id"],
            "filename": "audit.jpg",
            "media_type": "image/jpeg",
            "size_bytes": len(payload_bytes),
        },
        headers=csrf_headers(client),
    )
    assert presign.status_code == 200

    with SessionLocal() as db:
        log = db.query(AuditLog).filter(AuditLog.action == "upload.presign").first()
        assert log is not None
        assert log.meta_json["object_key"] == "[redacted]"


def test_dataset_commit_versions_increment_and_filter() -> None:
    client = TestClient(main_module.app)
    register_user(client, "dataset@example.com", "Dataset User")
    project = create_project(client, "Dataset Project")
    dataset = create_dataset(client, project["id"], "Dataset A")

    item_keep = upload_item(client, dataset["id"], "keep.jpg")
    upload_item(client, dataset["id"], "drop.jpg")

    ann_resp = client.post(
        f"/api/v1/data-items/{item_keep}/annotations",
        json={"type": "tag", "payload_json": {"tags": ["keep"]}},
        headers=csrf_headers(client),
    )
    assert ann_resp.status_code == 200

    version1 = commit_dataset(client, dataset["id"], "only keep tag", {"tag": "keep"})
    assert version1["version"] == 1
    assert version1["item_count"] == 1
    assert version1["frozen_item_ids"] == [item_keep]

    version2 = commit_dataset(client, dataset["id"], "all items")
    assert version2["version"] == 2
    assert version2["item_count"] == 2
    assert len(version2["frozen_item_ids"]) == 2


def test_dataset_items_tag_filter_returns_only_matching_items() -> None:
    client = TestClient(main_module.app)
    register_user(client, "items@example.com", "Items User")
    project = create_project(client, "Items Project")
    dataset = create_dataset(client, project["id"], "Dataset Filter")

    item_keep = upload_item(client, dataset["id"], "keep.jpg")
    upload_item(client, dataset["id"], "drop.jpg")

    ann_resp = client.post(
        f"/api/v1/data-items/{item_keep}/annotations",
        json={"type": "tag", "payload_json": {"tags": ["keep", "featured"]}},
        headers=csrf_headers(client),
    )
    assert ann_resp.status_code == 200

    items_resp = client.get(f"/api/v1/datasets/{dataset['id']}/items?tag=keep")
    assert items_resp.status_code == 200
    items = items_resp.json()
    assert [item["id"] for item in items] == [item_keep]
    assert items[0]["annotations"] == [
        {
            "id": ann_resp.json()["annotation"]["id"],
            "type": "tag",
            "payload_json": {"tags": ["keep", "featured"]},
            "created_at": items[0]["annotations"][0]["created_at"],
        }
    ]

def test_schema_uses_named_indexes_without_duplicate_orm_indexes() -> None:
    expected_indexes = {
        "data_items": {"idx_data_items_dataset", "idx_data_items_sha"},
        "annotations": {"idx_annotations_item"},
        "dataset_versions": {"idx_dsv_dataset"},
        "training_jobs": {"idx_jobs_project"},
        "training_runs": {"idx_runs_job"},
        "metrics": {"idx_metrics_run"},
        "artifacts": {"idx_artifacts_run"},
        "models": {"idx_models_project"},
        "model_versions": {"idx_model_versions_model"},
    }
    for table_name, expected in expected_indexes.items():
        indexes = {index.name for index in Base.metadata.tables[table_name].indexes}
        assert expected.issubset(indexes)
        assert not {name for name in indexes if name.startswith("ix_")}


def test_model_version_alias_publish_and_rollback() -> None:
    client = TestClient(main_module.app)
    register_user(client, "model@example.com", "Model User")
    project = create_project(client, "Model Project")

    model_resp = client.post(
        "/api/v1/models",
        json={"project_id": project["id"], "name": "Assistant", "task_type": "general"},
        headers=csrf_headers(client),
    )
    assert model_resp.status_code == 200
    model_id = model_resp.json()["model"]["id"]

    artifact_v1 = upload_model_artifact(client, model_id, "report-v1.json")
    v1_resp = client.post(
        f"/api/v1/models/{model_id}/versions",
        json={"run_id": None, "artifact_upload_id": artifact_v1, "metrics_json": {"acc": 0.8}},
        headers=csrf_headers(client),
    )
    assert v1_resp.status_code == 200
    v1_id = v1_resp.json()["model_version"]["id"]
    assert v1_resp.json()["model_version"]["artifact_download_url"]

    artifact_v2 = upload_model_artifact(client, model_id, "report-v2.json")
    v2_resp = client.post(
        f"/api/v1/models/{model_id}/versions",
        json={"run_id": None, "artifact_upload_id": artifact_v2, "metrics_json": {"acc": 0.9}},
        headers=csrf_headers(client),
    )
    assert v2_resp.status_code == 200
    v2_id = v2_resp.json()["model_version"]["id"]

    publish_resp = client.post(
        f"/api/v1/models/{model_id}/aliases",
        json={"alias": "prod", "model_version_id": v1_id},
        headers=csrf_headers(client),
    )
    assert publish_resp.status_code == 200

    rollback_resp = client.post(
        f"/api/v1/models/{model_id}/rollback",
        json={"alias": "prod", "to_model_version_id": v2_id},
        headers=csrf_headers(client),
    )
    assert rollback_resp.status_code == 200

    detail_resp = client.get(f"/api/v1/models/{model_id}")
    assert detail_resp.status_code == 200
    aliases = detail_resp.json()["aliases"]
    prod_alias = next(a for a in aliases if a["alias"] == "prod")
    assert prod_alias["model_version_id"] == v2_id


def test_validation_error_shape_contains_request_id() -> None:
    client = TestClient(main_module.app)
    resp = client.post("/api/v1/auth/register", json={"password": "missing-email"}, headers=public_headers())
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == "validation_error"
    assert isinstance(body["error"]["request_id"], str)
    assert body["error"]["request_id"]
    assert body["error"]["details"]["errors"]
    assert all("input" not in error for error in body["error"]["details"]["errors"])


def test_login_rate_limit_ignores_spoofed_forwarded_for() -> None:
    client = TestClient(main_module.app)
    register_user(client, "ratelimit@example.com", "Rate Limit User")
    for i in range(5):
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "ratelimit@example.com", "password": "wrongpass1234"},
            headers={**public_headers(), "x-forwarded-for": f"198.51.100.{i}"},
        )
        assert resp.status_code == 401

    blocked = client.post(
        "/api/v1/auth/login",
        json={"email": "ratelimit@example.com", "password": "wrongpass1234"},
        headers={**public_headers(), "x-forwarded-for": "203.0.113.99"},
    )
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"


def test_origin_required_for_public_mutations() -> None:
    client = TestClient(main_module.app)
    resp = client.post(
        "/api/v1/auth/register",
        json={
            "email": "origin@example.com",
            "password": "pass1234pass",
            "display_name": "Origin",
            "code": "123456",
        },
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "origin_required"


def test_csrf_required_for_authenticated_mutations() -> None:
    client = TestClient(main_module.app)
    register_user(client, "csrf@example.com", "CSRF User")
    resp = client.post("/api/v1/projects", json={"name": "P1", "description": "demo"}, headers=public_headers())
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "csrf_required"


def test_refresh_csrf_reuses_existing_valid_token() -> None:
    client = TestClient(main_module.app)
    user_info = register_user(client, "csrf-reuse@example.com", "CSRF Reuse")
    workspace_id = user_info["workspace"]["id"]

    first = client.get("/api/v1/auth/csrf", headers=public_headers())
    assert first.status_code == 200
    second = client.get("/api/v1/auth/csrf", headers=public_headers())
    assert second.status_code == 200
    assert second.json()["csrf_token"] == first.json()["csrf_token"]

    create = client.post(
        "/api/v1/projects",
        json={"name": "Stable CSRF", "description": "demo"},
        headers={
            **public_headers(),
            "x-workspace-id": workspace_id,
            "x-csrf-token": first.json()["csrf_token"],
        },
    )
    assert create.status_code == 200


def test_storage_helpers_only_treat_missing_objects_as_absent(monkeypatch) -> None:
    class MissingClient:
        def head_object(self, **kwargs):
            raise make_client_error("NotFound", 404)

    class ForbiddenClient:
        def head_object(self, **kwargs):
            raise make_client_error("403", 403)

    monkeypatch.setattr(storage_service.settings, "env", "local")
    monkeypatch.setattr(storage_service, "get_s3_client", lambda: MissingClient())
    assert storage_service.object_exists(bucket_name="bucket", object_key="missing") is False
    assert storage_service.get_object_metadata(bucket_name="bucket", object_key="missing") is None

    monkeypatch.setattr(storage_service, "get_s3_client", lambda: ForbiddenClient())
    with pytest.raises(ClientError):
        storage_service.object_exists(bucket_name="bucket", object_key="forbidden")
    with pytest.raises(ClientError):
        storage_service.get_object_metadata(bucket_name="bucket", object_key="forbidden")


def test_create_presigned_get_preserves_unicode_download_name(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class DummyPresignClient:
        def generate_presigned_url(self, *, ClientMethod, Params, ExpiresIn):
            captured["client_method"] = ClientMethod
            captured["params"] = Params
            captured["expires_in"] = ExpiresIn
            return "https://example.com/presigned"

    monkeypatch.setattr(storage_service, "get_s3_presign_client", lambda: DummyPresignClient())
    url = storage_service.create_presigned_get(
        bucket_name="bucket",
        object_key="path/to/object",
        download_name="测试 图片.png",
    )

    assert url == "https://example.com/presigned"
    assert storage_service.sanitize_filename("测试 图片.png") == "测试_图片.png"
    disposition = captured["params"]["ResponseContentDisposition"]
    assert 'filename="测试_图片.png"' in disposition
    assert "filename*=UTF-8''%E6%B5%8B%E8%AF%95%20%E5%9B%BE%E7%89%87.png" in disposition


def test_pipeline_patch_persists_config_json() -> None:
    client = TestClient(main_module.app)
    register_user(client, "pipeline@example.com", "Pipeline")
    project = create_project(client, "Pipeline Project")

    payload = {
        "project_id": project["id"],
        "model_type": "tts",
        "model_id": "cosyvoice-v1",
        "config_json": {"voice_id": "cosy-cn", "speed": 1.1},
    }
    resp = client.patch(
        "/api/v1/pipeline",
        json=payload,
        headers=csrf_headers(client),
    )

    assert resp.status_code == 200
    assert resp.json()["config_json"] == payload["config_json"]

    current = client.get(f"/api/v1/pipeline?project_id={project['id']}")
    assert current.status_code == 200
    matching = [item for item in current.json()["items"] if item["model_type"] == "tts"]
    assert matching[0]["config_json"] == payload["config_json"]


def test_project_creation_seeds_default_pipeline() -> None:
    client = TestClient(main_module.app)
    register_user(client, "defaults@example.com", "Defaults")
    project = create_project(client, "Defaults Project")

    current = client.get(f"/api/v1/pipeline?project_id={project['id']}")
    assert current.status_code == 200
    items = {item["model_type"]: item["model_id"] for item in current.json()["items"]}
    assert items["llm"] == "qwen3.5-plus"
    assert items["asr"] == "paraformer-v2"
    assert items["tts"] == "cosyvoice-v1"
    assert items["vision"] == "qwen-vl-plus"
    assert items["realtime"] == "qwen3-omni-flash-realtime"
    assert items["realtime_asr"] == "qwen3-asr-flash-realtime"
    assert items["realtime_tts"] == "qwen3-tts-flash-realtime"
    assert project["default_chat_mode"] == "standard"


def test_pipeline_patch_rejects_realtime_model_in_chat_slot() -> None:
    client = TestClient(main_module.app)
    register_user(client, "pipeline-chat-guard@example.com", "Pipeline Chat Guard")
    project = create_project(client, "Pipeline Chat Guard Project")

    resp = client.patch(
        "/api/v1/pipeline",
        json={
            "project_id": project["id"],
            "model_type": "llm",
            "model_id": "qwen3-omni-flash-realtime",
            "config_json": {},
        },
        headers=csrf_headers(client),
    )

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_model_type"


def test_pipeline_patch_rejects_non_realtime_model_in_realtime_slot() -> None:
    client = TestClient(main_module.app)
    register_user(client, "pipeline-realtime-guard@example.com", "Pipeline Realtime Guard")
    project = create_project(client, "Pipeline Realtime Guard Project")

    resp = client.patch(
        "/api/v1/pipeline",
        json={
            "project_id": project["id"],
            "model_type": "realtime",
            "model_id": "qwen3.5-plus",
            "config_json": {},
        },
        headers=csrf_headers(client),
    )

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_model_type"


def test_send_message_does_not_duplicate_current_user_message(monkeypatch) -> None:
    client = TestClient(main_module.app)
    register_user(client, "chat@example.com", "Chat")
    project = create_project(client, "Chat Project")
    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200
    conversation_id = conversation.json()["id"]

    captured: dict[str, object] = {}

    async def fake_orchestrate_inference(*args, **kwargs):
        captured["user_message"] = kwargs["user_message"]
        captured["recent_messages"] = kwargs["recent_messages"]
        return "mocked ai reply"

    monkeypatch.setattr(chat_router.settings, "dashscope_api_key", "test-key")
    monkeypatch.setattr(chat_router, "orchestrate_inference", fake_orchestrate_inference)

    resp = client.post(
        f"/api/v1/chat/conversations/{conversation_id}/messages",
        json={"content": "hello world"},
        headers=csrf_headers(client),
    )

    assert resp.status_code == 200
    assert captured["user_message"] == "hello world"
    assert captured["recent_messages"] == []


def test_send_message_persists_reasoning_content_when_thinking_enabled(monkeypatch) -> None:
    client = TestClient(main_module.app)
    register_user(client, "chat-thinking@example.com", "Chat Thinking")
    project = create_project(client, "Chat Thinking Project")
    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200
    conversation_id = conversation.json()["id"]

    captured: dict[str, object] = {}

    async def fake_orchestrate_inference(*args, **kwargs):
        captured["enable_thinking"] = kwargs.get("enable_thinking")
        return {
            "content": "核心灵感\n: 先看相对论约束。",
            "reasoning_content": "🎯\n\n脑洞推导路径\n\n：\n\n先拆解问题，再形成回答。",
        }

    monkeypatch.setattr(chat_router.settings, "dashscope_api_key", "test-key")
    monkeypatch.setattr(chat_router, "orchestrate_inference", fake_orchestrate_inference)

    resp = client.post(
        f"/api/v1/chat/conversations/{conversation_id}/messages",
        json={"content": "帮我分析", "enable_thinking": True},
        headers=csrf_headers(client),
    )

    assert resp.status_code == 200
    assert captured["enable_thinking"] is True
    assert resp.json()["content"] == "核心灵感: 先看相对论约束。"
    assert resp.json()["reasoning_content"] == "🎯 脑洞推导路径：先拆解问题，再形成回答。"

    messages = client.get(
        f"/api/v1/chat/conversations/{conversation_id}/messages",
        headers={"origin": ORIGIN},
    )
    assert messages.status_code == 200
    assert messages.json()[1]["content"] == "核心灵感: 先看相对论约束。"
    assert messages.json()[1]["reasoning_content"] == "🎯 脑洞推导路径：先拆解问题，再形成回答。"


def test_send_message_persists_search_sources_metadata(monkeypatch) -> None:
    client = TestClient(main_module.app)
    register_user(client, "chat-sources@example.com", "Chat Sources")
    project = create_project(client, "Chat Sources Project")
    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200
    conversation_id = conversation.json()["id"]

    async def fake_orchestrate_inference(*args, **kwargs):
        del args, kwargs
        return {
            "content": "这是答案[ref_1]",
            "reasoning_content": None,
            "sources": [
                {
                    "index": 1,
                    "title": "Example Source",
                    "url": "https://example.com/story",
                    "domain": "example.com",
                    "site_name": "Example",
                    "summary": "A summarized source excerpt.",
                }
            ],
        }

    monkeypatch.setattr(chat_router.settings, "dashscope_api_key", "test-key")
    monkeypatch.setattr(chat_router, "orchestrate_inference", fake_orchestrate_inference)

    resp = client.post(
        f"/api/v1/chat/conversations/{conversation_id}/messages",
        json={"content": "帮我看下最新进展", "enable_search": True},
        headers=csrf_headers(client),
    )

    assert resp.status_code == 200
    assert resp.json()["metadata_json"]["sources"][0]["title"] == "Example Source"
    assert resp.json()["metadata_json"]["sources"][0]["url"] == "https://example.com/story"

    messages = client.get(
        f"/api/v1/chat/conversations/{conversation_id}/messages",
        headers={"origin": ORIGIN},
    )
    assert messages.status_code == 200
    assert messages.json()[1]["metadata_json"]["sources"][0]["domain"] == "example.com"
    assert messages.json()[1]["content"] == "这是答案[ref_1]"


def test_send_message_passes_assistant_message_id_to_memory_extraction(monkeypatch) -> None:
    client = TestClient(main_module.app)
    register_user(client, "chat-memory-id@example.com", "Chat Memory Id")
    project = create_project(client, "Chat Memory Id Project")
    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200
    conversation_id = conversation.json()["id"]

    captured: dict[str, object] = {}

    async def fake_orchestrate_inference(*args, **kwargs):
        del args, kwargs
        return "记住了"

    def fake_trigger_memory_extraction(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs

    monkeypatch.setattr(chat_router.settings, "dashscope_api_key", "test-key")
    monkeypatch.setattr(chat_router, "orchestrate_inference", fake_orchestrate_inference)
    monkeypatch.setattr(chat_router, "_trigger_memory_extraction", fake_trigger_memory_extraction)

    resp = client.post(
        f"/api/v1/chat/conversations/{conversation_id}/messages",
        json={"content": "我喜欢冰美式"},
        headers=csrf_headers(client),
    )

    assert resp.status_code == 200
    assert resp.json()["metadata_json"]["memory_extraction_status"] == "pending"
    assert resp.json()["metadata_json"]["memory_extraction_attempts"] == 0
    assert captured["kwargs"]["assistant_message_id"] == resp.json()["id"]


def test_send_message_passes_enable_search_preference(monkeypatch) -> None:
    client = TestClient(main_module.app)
    register_user(client, "chat-search@example.com", "Chat Search")
    project = create_project(client, "Chat Search Project")
    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200
    conversation_id = conversation.json()["id"]

    captured: dict[str, object] = {}

    async def fake_orchestrate_inference(*args, **kwargs):
        captured["enable_search"] = kwargs.get("enable_search")
        return {"content": "已开启搜索", "reasoning_content": None}

    monkeypatch.setattr(chat_router.settings, "dashscope_api_key", "test-key")
    monkeypatch.setattr(chat_router, "orchestrate_inference", fake_orchestrate_inference)

    resp = client.post(
        f"/api/v1/chat/conversations/{conversation_id}/messages",
        json={"content": "帮我查最新消息", "enable_search": True},
        headers=csrf_headers(client),
    )

    assert resp.status_code == 200
    assert captured["enable_search"] is True


def test_send_message_defers_auto_thinking_decision_for_simple_greeting(monkeypatch) -> None:
    client = TestClient(main_module.app)
    register_user(client, "chat-auto-greeting@example.com", "Chat Auto Greeting")
    project = create_project(client, "Chat Auto Greeting Project")
    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200
    conversation_id = conversation.json()["id"]

    captured: dict[str, object] = {}

    async def fake_orchestrate_inference(*args, **kwargs):
        captured["enable_thinking"] = kwargs.get("enable_thinking")
        return {"content": "你好呀", "reasoning_content": None}

    monkeypatch.setattr(chat_router.settings, "dashscope_api_key", "test-key")
    monkeypatch.setattr(chat_router, "orchestrate_inference", fake_orchestrate_inference)

    resp = client.post(
        f"/api/v1/chat/conversations/{conversation_id}/messages",
        json={"content": "你好"},
        headers=csrf_headers(client),
    )

    assert resp.status_code == 200
    assert captured["enable_thinking"] is None


def test_send_message_defers_auto_thinking_decision_for_analysis_prompt(monkeypatch) -> None:
    client = TestClient(main_module.app)
    register_user(client, "chat-auto-analysis@example.com", "Chat Auto Analysis")
    project = create_project(client, "Chat Auto Analysis Project")
    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200
    conversation_id = conversation.json()["id"]

    captured: dict[str, object] = {}

    async def fake_orchestrate_inference(*args, **kwargs):
        captured["enable_thinking"] = kwargs.get("enable_thinking")
        return {"content": "我来分析一下", "reasoning_content": "..." }

    monkeypatch.setattr(chat_router.settings, "dashscope_api_key", "test-key")
    monkeypatch.setattr(chat_router, "orchestrate_inference", fake_orchestrate_inference)

    resp = client.post(
        f"/api/v1/chat/conversations/{conversation_id}/messages",
        json={"content": "请分析一下这个方案的优缺点"},
        headers=csrf_headers(client),
    )

    assert resp.status_code == 200
    assert captured["enable_thinking"] is None


def test_stream_message_auto_disables_thinking_for_simple_greeting(monkeypatch) -> None:
    client = TestClient(main_module.app)
    register_user(client, "chat-stream-auto-greeting@example.com", "Chat Stream Auto Greeting")
    project = create_project(client, "Chat Stream Auto Greeting Project")
    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200
    conversation_id = conversation.json()["id"]

    captured: dict[str, object] = {}

    async def fake_search_similar(*args, **kwargs) -> list[dict]:
        return []

    async def fake_responses_completion_stream(
        input_items,
        model=None,
        *,
        enable_thinking=None,
        tools=None,
        tool_choice="auto",
        timeout=120.0,
        image_bytes=None,
        image_mime_type="image/jpeg",
    ):
        del input_items, model, tool_choice, timeout, image_bytes, image_mime_type
        captured["enable_thinking"] = enable_thinking
        captured["tools"] = tools
        yield dashscope_responses_service.ResponsesStreamChunk(reasoning_content="不该显示的思考")
        yield dashscope_responses_service.ResponsesStreamChunk(content="你好呀")
        yield dashscope_responses_service.ResponsesStreamChunk(finish_reason="completed")

    monkeypatch.setattr(chat_router.settings, "dashscope_api_key", "test-key")
    monkeypatch.setattr(orchestrator_service, "search_similar", fake_search_similar)
    monkeypatch.setattr(
        orchestrator_service,
        "responses_completion_stream",
        fake_responses_completion_stream,
    )

    resp = client.post(
        f"/api/v1/chat/conversations/{conversation_id}/stream",
        json={"content": "你好"},
        headers=csrf_headers(client),
    )

    assert resp.status_code == 200
    assert captured["enable_thinking"] is False
    assert isinstance(captured["tools"], list) and len(captured["tools"]) >= 1
    assert "event: reasoning" not in resp.text
    assert '"reasoning_content": null' in resp.text

    messages = client.get(
        f"/api/v1/chat/conversations/{conversation_id}/messages",
        headers={"origin": ORIGIN},
    )
    assert messages.status_code == 200
    assert messages.json()[1]["content"] == "你好呀"
    assert messages.json()[1]["reasoning_content"] is None


def test_stream_message_auto_enables_search_for_freshness_query(monkeypatch) -> None:
    client = TestClient(main_module.app)
    register_user(client, "chat-stream-search@example.com", "Chat Stream Search")
    project = create_project(client, "Chat Stream Search Project")
    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200
    conversation_id = conversation.json()["id"]

    captured: dict[str, object] = {}

    async def fake_search_similar(*args, **kwargs) -> list[dict]:
        return []

    async def fake_responses_completion_stream(
        input_items,
        model=None,
        *,
        enable_thinking=None,
        tools=None,
        tool_choice="auto",
        timeout=120.0,
        image_bytes=None,
        image_mime_type="image/jpeg",
    ):
        del input_items, model, enable_thinking, tool_choice, timeout, image_bytes, image_mime_type
        captured["tools"] = tools
        yield dashscope_responses_service.ResponsesStreamChunk(content="今天有雨")
        yield dashscope_responses_service.ResponsesStreamChunk(finish_reason="completed")

    monkeypatch.setattr(chat_router.settings, "dashscope_api_key", "test-key")
    monkeypatch.setattr(orchestrator_service, "search_similar", fake_search_similar)
    monkeypatch.setattr(
        orchestrator_service,
        "responses_completion_stream",
        fake_responses_completion_stream,
    )

    resp = client.post(
        f"/api/v1/chat/conversations/{conversation_id}/stream",
        json={"content": "今天上海天气怎么样"},
        headers=csrf_headers(client),
    )

    assert resp.status_code == 200
    assert {"type": "web_search"} in (captured["tools"] or [])
    assert "今天有雨" in resp.text


def test_stream_message_emits_and_persists_search_sources(monkeypatch) -> None:
    client = TestClient(main_module.app)
    register_user(client, "chat-stream-sources@example.com", "Chat Stream Sources")
    project = create_project(client, "Chat Stream Sources Project")
    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200
    conversation_id = conversation.json()["id"]

    async def fake_search_similar(*args, **kwargs) -> list[dict]:
        return []

    async def fake_responses_completion_stream(
        input_items,
        model=None,
        *,
        enable_thinking=None,
        tools=None,
        tool_choice="auto",
        timeout=120.0,
        image_bytes=None,
        image_mime_type="image/jpeg",
    ):
        del input_items, model, enable_thinking, tools, tool_choice, timeout, image_bytes, image_mime_type
        yield dashscope_responses_service.ResponsesStreamChunk(
            content="整理如下[ref_1]",
            search_sources=[
                SearchSource(
                    index=1,
                    title="Example Stream Source",
                    url="https://example.com/stream",
                    domain="example.com",
                    site_name="Example",
                    summary="Stream summary",
                )
            ],
        )
        yield dashscope_responses_service.ResponsesStreamChunk(finish_reason="completed")

    monkeypatch.setattr(chat_router.settings, "dashscope_api_key", "test-key")
    monkeypatch.setattr(orchestrator_service, "search_similar", fake_search_similar)
    monkeypatch.setattr(
        orchestrator_service,
        "responses_completion_stream",
        fake_responses_completion_stream,
    )

    resp = client.post(
        f"/api/v1/chat/conversations/{conversation_id}/stream",
        json={"content": "请查一下刚刚发生了什么", "enable_search": True},
        headers=csrf_headers(client),
    )

    assert resp.status_code == 200
    assert '"title": "Example Stream Source"' in resp.text
    assert '"url": "https://example.com/stream"' in resp.text

    messages = client.get(
        f"/api/v1/chat/conversations/{conversation_id}/messages",
        headers={"origin": ORIGIN},
    )
    assert messages.status_code == 200
    assert messages.json()[1]["metadata_json"]["sources"][0]["summary"] == "Stream summary"
    assert messages.json()[1]["content"] == "整理如下[ref_1]"


def test_stream_message_passes_assistant_message_id_to_memory_extraction(monkeypatch) -> None:
    client = TestClient(main_module.app)
    register_user(client, "chat-stream-memory-id@example.com", "Chat Stream Memory Id")
    project = create_project(client, "Chat Stream Memory Id Project")
    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200
    conversation_id = conversation.json()["id"]

    captured: dict[str, object] = {}

    async def fake_search_similar(*args, **kwargs) -> list[dict]:
        return []

    async def fake_responses_completion_stream(
        input_items,
        model=None,
        *,
        enable_thinking=None,
        tools=None,
        tool_choice="auto",
        timeout=120.0,
        image_bytes=None,
        image_mime_type="image/jpeg",
    ):
        del input_items, model, enable_thinking, tools, tool_choice, timeout, image_bytes, image_mime_type
        yield dashscope_responses_service.ResponsesStreamChunk(content="已经记住了")
        yield dashscope_responses_service.ResponsesStreamChunk(finish_reason="completed")

    def fake_trigger_memory_extraction(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs

    monkeypatch.setattr(chat_router.settings, "dashscope_api_key", "test-key")
    monkeypatch.setattr(orchestrator_service, "search_similar", fake_search_similar)
    monkeypatch.setattr(
        orchestrator_service,
        "responses_completion_stream",
        fake_responses_completion_stream,
    )
    monkeypatch.setattr(chat_router, "_trigger_memory_extraction", fake_trigger_memory_extraction)

    resp = client.post(
        f"/api/v1/chat/conversations/{conversation_id}/stream",
        json={"content": "我喜欢冰美式"},
        headers=csrf_headers(client),
    )

    assert resp.status_code == 200
    assert '"memory_extraction_status": "pending"' in resp.text
    messages = client.get(
        f"/api/v1/chat/conversations/{conversation_id}/messages",
        headers={"origin": ORIGIN},
    )
    assert messages.status_code == 200
    assert messages.json()[1]["metadata_json"]["memory_extraction_status"] == "pending"
    assert captured["kwargs"]["assistant_message_id"] == messages.json()[1]["id"]


def test_orchestrate_inference_stream_emits_message_start_before_preparation(monkeypatch) -> None:
    call_order: list[str] = []

    async def fake_resolve_enable_thinking(*args, **kwargs):
        del args, kwargs
        call_order.append("resolve_enable_thinking")
        return SimpleNamespace(enable_thinking=False)

    monkeypatch.setattr(
        orchestrator_service,
        "resolve_enable_thinking",
        fake_resolve_enable_thinking,
    )

    async def collect_first_event() -> dict[str, object]:
        generator = orchestrator_service.orchestrate_inference_stream(
            db=None,
            workspace_id="ws_1",
            project_id="proj_1",
            conversation_id="conv_1",
            user_message="你好",
            recent_messages=[],
        )
        first = await generator.__anext__()
        await generator.aclose()
        return first

    first_event = asyncio.run(collect_first_event())

    assert first_event == {"event": "message_start", "data": {"role": "assistant"}}
    assert call_order == []


def test_normalize_assistant_markdown_repairs_inline_bullets() -> None:
    normalized = assistant_markdown_service.normalize_assistant_markdown("-冰美式- 手冲- 冷萃")

    assert normalized == "- 冰美式\n- 手冲\n- 冷萃"


def test_normalize_assistant_markdown_repairs_sentence_prefixed_inline_bullets() -> None:
    normalized = assistant_markdown_service.normalize_assistant_markdown(
        "好的，我记住了。- 乌龙茶- 茉莉花茶"
    )

    assert normalized == "好的，我记住了。\n- 乌龙茶\n- 茉莉花茶"


def test_normalize_assistant_markdown_merges_dangling_colon_lines() -> None:
    normalized = assistant_markdown_service.normalize_assistant_markdown(
        "居住地逻辑\n: 长期定居北京，求学于伦敦。\n学术兴趣\n： 拓扑学。"
    )

    assert normalized == "居住地逻辑: 长期定居北京，求学于伦敦。\n学术兴趣： 拓扑学。"


def test_normalize_assistant_markdown_repairs_glued_headings() -> None:
    normalized = assistant_markdown_service.normalize_assistant_markdown(
        "薛定谔方程的启发式推导### 1. 出发点：德布罗意关系\n###5. 加入势能项"
    )

    assert normalized == (
        "薛定谔方程的启发式推导\n### 1. 出发点：德布罗意关系\n### 5. 加入势能项"
    )


def test_normalize_assistant_markdown_repairs_glued_math_commands() -> None:
    normalized = assistant_markdown_service.normalize_assistant_markdown(
        "$$\\frac{\\partial^2 \\psi}{\\partialx^2}=-k^2\\psi$$"
    )

    assert normalized == "$$\\frac{\\partial^2 \\psi}{\\partial x^2}=-k^2\\psi$$"


def test_normalize_assistant_markdown_repairs_compact_tables() -> None:
    normalized = assistant_markdown_service.normalize_assistant_markdown(
        "##理性总结| 步骤| 核心思想 | 局限性 ||------|----------|--------||德布罗意关系 | 波粒二象性 | 实验假设 ||平面波假设 | 自由粒子模型 | 仅适用于自由态 |"
    )

    assert normalized == (
        "## 理性总结\n"
        "| 步骤| 核心思想 | 局限性|\n"
        "|------|----------|--------|\n"
        "|德布罗意关系 | 波粒二象性 | 实验假设|\n"
        "|平面波假设 | 自由粒子模型 | 仅适用于自由态 |"
    )


def test_normalize_assistant_markdown_merges_punctuation_continuations() -> None:
    normalized = assistant_markdown_service.normalize_assistant_markdown(
        "薛定谔方程\n， 一句话：它是量子力学的“牛顿第二定律”。\n\nH是哈密顿算符\n： 通常 = 动能 + 势能。"
    )

    assert normalized == (
        "薛定谔方程，一句话：它是量子力学的“牛顿第二定律”。\n\n"
        "H是哈密顿算符： 通常 = 动能 + 势能。"
    )


def test_normalize_assistant_markdown_preserves_section_labels_and_lists() -> None:
    normalized = assistant_markdown_service.normalize_assistant_markdown(
        "核心要点\n：\n波函数 Ψ\n： 方程的解。\n\n关键优势\n---\n：\n· 自动处理约束。\n• 坐标无关性。"
    )

    assert normalized == (
        "核心要点：\n"
        "波函数 Ψ： 方程的解。\n\n"
        "关键优势：\n"
        "- 自动处理约束。\n"
        "- 坐标无关性。"
    )


def test_normalize_assistant_markdown_merges_standalone_emoji_headings() -> None:
    normalized = assistant_markdown_service.normalize_assistant_markdown(
        "🎯\n\n核心灵感\n\n:\n\n狄拉克当时在想。\n\n🔮\n\n脑洞推导路径\n\n：\n\n从经典相对论开始。"
    )

    assert normalized == "🎯 核心灵感: 狄拉克当时在想。\n\n🔮 脑洞推导路径：从经典相对论开始。"


def test_normalize_assistant_markdown_merges_short_fragment_continuations() -> None:
    normalized = assistant_markdown_service.normalize_assistant_markdown(
        "场景\n\n： 伦敦地铁（The Tube）那张经典的彩色线路图。\n\n脑洞\n\n： 这不仅仅是地图，这是一个巨大的\n\n拓扑网络\n\n！ 环线（CircleLine）是不是像一个完美的闭合轨道？"
    )

    assert normalized == (
        "场景： 伦敦地铁（The Tube）那张经典的彩色线路图。\n\n"
        "脑洞： 这不仅仅是地图，这是一个巨大的拓扑网络！环线（CircleLine）是不是像一个完美的闭合轨道？"
    )


def test_normalize_assistant_markdown_merges_quoted_followup_continuations() -> None:
    normalized = assistant_markdown_service.normalize_assistant_markdown(
        "脑洞\n\n： 每一滴雨落下都是概率云的坍缩\n\n“雨滴狄拉克方程”\n\n的诗？\n\n时空重叠感\n\n是不是超酷？"
    )

    assert normalized == (
        "脑洞： 每一滴雨落下都是概率云的坍缩“雨滴狄拉克方程”的诗？\n\n"
        "时空重叠感是不是超酷？"
    )


def test_normalize_assistant_markdown_repairs_fragmented_list_items() -> None:
    """Ported from frontend repairFragmentedListItems – streaming artefact repair."""
    # Dangling bold marker removed
    normalized = assistant_markdown_service.normalize_assistant_markdown(
        "- 第一项\n- **\n- 第二项"
    )
    assert "- **" not in normalized
    assert "- 第一项" in normalized
    assert "- 第二项" in normalized

    # Punctuation fragment merged
    normalized = assistant_markdown_service.normalize_assistant_markdown(
        "- 新仪式感\n- 。"
    )
    assert normalized.strip() == "- 新仪式感。"

    # Leading dangling star stripped
    normalized = assistant_markdown_service.normalize_assistant_markdown(
        "- *bold text continues"
    )
    assert "- bold text continues" in normalized


def test_build_and_call_llm_normalizes_assistant_markdown(monkeypatch) -> None:
    async def fake_resolve_enable_thinking(*args, **kwargs):
        del args, kwargs
        return SimpleNamespace(enable_thinking=False)

    async def fake_assemble_prompt_context(*args, **kwargs):
        del args, kwargs
        return ([{"role": "system", "content": "sys"}, {"role": "user", "content": "u"}], {})

    async def fake_resolve_search_options(*args, **kwargs):
        del args, kwargs
        return SimpleNamespace(enable_search=False, search_options=None)

    async def fake_chat_completion_detailed(*args, **kwargs):
        del args, kwargs
        return SimpleNamespace(
            content="-冰美式- 手冲- 冷萃",
            reasoning_content=None,
            search_sources=[],
        )

    monkeypatch.setattr(orchestrator_service, "resolve_enable_thinking", fake_resolve_enable_thinking)
    monkeypatch.setattr(orchestrator_service, "_assemble_prompt_context", fake_assemble_prompt_context)
    monkeypatch.setattr(orchestrator_service, "_resolve_search_options", fake_resolve_search_options)
    monkeypatch.setattr(orchestrator_service, "_load_model_capabilities", lambda *args, **kwargs: set())
    monkeypatch.setattr(orchestrator_service, "_should_use_responses_auto_tools", lambda **kwargs: False)
    monkeypatch.setattr(orchestrator_service, "chat_completion_detailed", fake_chat_completion_detailed)

    result = asyncio.run(
        orchestrator_service._build_and_call_llm(
            db=None,
            workspace_id="ws_1",
            project_id="proj_1",
            conversation_id="conv_1",
            user_message="请用 markdown 列表复述",
            recent_messages=[],
            llm_model_id="model_1",
        )
    )

    assert result["content"] == "- 冰美式\n- 手冲\n- 冷萃"


def test_orchestrate_inference_stream_normalizes_message_done_markdown(monkeypatch) -> None:
    async def fake_resolve_enable_thinking(*args, **kwargs):
        del args, kwargs
        return SimpleNamespace(enable_thinking=False)

    async def fake_resolve_search_options(*args, **kwargs):
        del args, kwargs
        return SimpleNamespace(enable_search=False, search_options=None)

    async def fake_assemble_prompt_context(*args, **kwargs):
        del args, kwargs
        return ([{"role": "system", "content": "sys"}, {"role": "user", "content": "u"}], {})

    async def fake_chat_completion_stream(*args, **kwargs):
        del args, kwargs
        yield SimpleNamespace(content="-冰美式- 手冲- 冷萃", reasoning_content=None, search_sources=[])

    monkeypatch.setattr(orchestrator_service, "resolve_pipeline_model_id", lambda *args, **kwargs: "model_1")
    monkeypatch.setattr(orchestrator_service, "resolve_enable_thinking", fake_resolve_enable_thinking)
    monkeypatch.setattr(orchestrator_service, "_resolve_search_options", fake_resolve_search_options)
    monkeypatch.setattr(orchestrator_service, "_assemble_prompt_context", fake_assemble_prompt_context)
    monkeypatch.setattr(orchestrator_service, "_load_model_capabilities", lambda *args, **kwargs: set())
    monkeypatch.setattr(orchestrator_service, "_should_use_responses_auto_tools", lambda **kwargs: False)
    monkeypatch.setattr(orchestrator_service, "chat_completion_stream", fake_chat_completion_stream)

    async def collect_events() -> list[dict[str, object]]:
        return [
            event
            async for event in orchestrator_service.orchestrate_inference_stream(
                db=None,
                workspace_id="ws_1",
                project_id="proj_1",
                conversation_id="conv_1",
                user_message="请用 markdown 列表复述",
                recent_messages=[],
            )
        ]

    events = asyncio.run(collect_events())
    token_event = next(event for event in events if event["event"] == "token")
    message_done = next(event for event in events if event["event"] == "message_done")

    assert token_event["data"]["content"] == "-冰美式- 手冲- 冷萃"
    assert token_event["data"]["snapshot"] == "- 冰美式\n- 手冲\n- 冷萃"
    assert message_done["data"]["content"] == "- 冰美式\n- 手冲\n- 冷萃"


def test_orchestrate_inference_stream_normalizes_reasoning_snapshots(monkeypatch) -> None:
    async def fake_resolve_enable_thinking(*args, **kwargs):
        del args, kwargs
        return SimpleNamespace(enable_thinking=True)

    async def fake_resolve_search_options(*args, **kwargs):
        del args, kwargs
        return SimpleNamespace(enable_search=False, search_options=None)

    async def fake_assemble_prompt_context(*args, **kwargs):
        del args, kwargs
        return ([{"role": "system", "content": "sys"}, {"role": "user", "content": "u"}], {})

    async def fake_chat_completion_stream(*args, **kwargs):
        del args, kwargs
        yield SimpleNamespace(
            content="最终回答",
            reasoning_content="🎯\n\n核心灵感\n\n：\n\n先拆解问题。",
            search_sources=[],
        )

    monkeypatch.setattr(orchestrator_service, "resolve_pipeline_model_id", lambda *args, **kwargs: "model_1")
    monkeypatch.setattr(orchestrator_service, "resolve_enable_thinking", fake_resolve_enable_thinking)
    monkeypatch.setattr(orchestrator_service, "_resolve_search_options", fake_resolve_search_options)
    monkeypatch.setattr(orchestrator_service, "_assemble_prompt_context", fake_assemble_prompt_context)
    monkeypatch.setattr(orchestrator_service, "_load_model_capabilities", lambda *args, **kwargs: set())
    monkeypatch.setattr(orchestrator_service, "_should_use_responses_auto_tools", lambda **kwargs: False)
    monkeypatch.setattr(orchestrator_service, "chat_completion_stream", fake_chat_completion_stream)

    async def collect_events() -> list[dict[str, object]]:
        return [
            event
            async for event in orchestrator_service.orchestrate_inference_stream(
                db=None,
                workspace_id="ws_1",
                project_id="proj_1",
                conversation_id="conv_1",
                user_message="请展开",
                recent_messages=[],
                enable_thinking=True,
            )
        ]

    events = asyncio.run(collect_events())
    reasoning_event = next(event for event in events if event["event"] == "reasoning")
    message_done = next(event for event in events if event["event"] == "message_done")

    assert reasoning_event["data"]["content"] == "🎯\n\n核心灵感\n\n：\n\n先拆解问题。"
    assert reasoning_event["data"]["snapshot"] == "🎯 核心灵感：先拆解问题。"
    assert message_done["data"]["reasoning_content"] == "🎯 核心灵感：先拆解问题。"


def test_orchestrate_inference_stream_uses_responses_auto_tools_with_new_signature(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_resolve_enable_thinking(*args, **kwargs):
        del args, kwargs
        return SimpleNamespace(enable_thinking=False)

    async def fake_resolve_search_options(*args, **kwargs):
        del args, kwargs
        return SimpleNamespace(enable_search=True, search_options=None)

    async def fake_assemble_prompt_context(*args, **kwargs):
        del args, kwargs
        return ([{"role": "system", "content": "sys"}, {"role": "user", "content": "u"}], {})

    async def fake_stream_llm_with_auto_tools(
        db,
        *,
        workspace_id,
        project_id,
        conversation_id,
        messages,
        llm_model_id,
        tool_definitions,
        response_enable_thinking,
    ):
        del db, workspace_id, project_id, conversation_id, messages, llm_model_id
        captured["tool_definitions"] = tool_definitions
        captured["response_enable_thinking"] = response_enable_thinking
        yield SimpleNamespace(content="自动工具回复", reasoning_content=None, search_sources=[])

    monkeypatch.setattr(orchestrator_service, "resolve_pipeline_model_id", lambda *args, **kwargs: "qwen3.5-plus")
    monkeypatch.setattr(orchestrator_service, "resolve_enable_thinking", fake_resolve_enable_thinking)
    monkeypatch.setattr(orchestrator_service, "_resolve_search_options", fake_resolve_search_options)
    monkeypatch.setattr(orchestrator_service, "_assemble_prompt_context", fake_assemble_prompt_context)
    monkeypatch.setattr(
        orchestrator_service,
        "_load_model_capabilities",
        lambda *args, **kwargs: {"responses_api", "function_calling"},
    )
    monkeypatch.setattr(orchestrator_service, "_load_llm_config_json", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        orchestrator_service,
        "_build_response_tool_definitions",
        lambda **kwargs: [{"type": "web_search"}],
    )
    monkeypatch.setattr(
        orchestrator_service,
        "_build_chat_function_tool_definitions",
        lambda **kwargs: [],
    )
    monkeypatch.setattr(
        orchestrator_service,
        "_stream_llm_with_auto_tools",
        fake_stream_llm_with_auto_tools,
    )

    async def collect_events() -> list[dict[str, object]]:
        return [
            event
            async for event in orchestrator_service.orchestrate_inference_stream(
                db=None,
                workspace_id="ws_1",
                project_id="proj_1",
                conversation_id="conv_1",
                user_message="帮我查一下官网",
                recent_messages=[],
            )
        ]

    events = asyncio.run(collect_events())
    message_done = next(event for event in events if event["event"] == "message_done")

    assert captured["tool_definitions"] == [{"type": "web_search"}]
    assert captured["response_enable_thinking"] is False
    assert message_done["data"]["content"] == "自动工具回复"


def test_responses_completion_stream_emits_final_message_items_without_duplication(monkeypatch) -> None:
    class FakeStreamResponse:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def raise_for_status(self) -> None:
            return None

        async def aiter_lines(self):
            lines = [
                "event: response.output_item.done",
                'data: {"item":{"type":"message","content":[{"type":"text","text":"来自最终消息项的回复"}]}}',
                "",
                "event: response.output_item.done",
                'data: {"item":{"type":"reasoning","summary":[{"text":"最终思考摘要"}]}}',
                "",
                "event: response.completed",
                (
                    'data: {"status":"completed","output":['
                    '{"type":"message","content":[{"type":"text","text":"来自最终消息项的回复"}]},'
                    '{"type":"reasoning","summary":[{"text":"最终思考摘要"}]}'
                    ']}'
                ),
                "",
            ]
            for line in lines:
                yield line

    class FakeClient:
        def stream(self, *args, **kwargs):
            return FakeStreamResponse()

    monkeypatch.setattr(dashscope_responses_service, "get_client", lambda: FakeClient())
    monkeypatch.setattr(dashscope_responses_service, "dashscope_headers", lambda: {})

    async def collect_chunks() -> list[object]:
        chunks = []
        async for chunk in dashscope_responses_service.responses_completion_stream(
            [{"role": "user", "content": "你好"}],
            model="qwen-test",
        ):
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(collect_chunks())

    assert [chunk.content for chunk in chunks if chunk.content] == ["来自最终消息项的回复"]
    assert [chunk.reasoning_content for chunk in chunks if chunk.reasoning_content] == ["最终思考摘要"]
    assert [chunk.finish_reason for chunk in chunks if chunk.finish_reason] == ["completed"]


def test_web_search_falls_back_offline_without_rule_hints() -> None:
    with SessionLocal() as db:
        decision = asyncio.run(
            orchestrator_service._resolve_search_options(
                db,
                llm_model_id="qwen3.5-plus",
                llm_capabilities={"web_search"},
                user_message="苹果 CEO 是谁",
                recent_messages=[],
                preference=None,
            )
        )

    assert decision.enable_search is False
    assert decision.route == "no_search"
    assert decision.source == "fallback"
    assert decision.search_options is None


def test_official_catalog_extends_llm_capabilities_for_qwen_flash_models() -> None:
    with SessionLocal() as db:
        capabilities = orchestrator_service._load_model_capabilities(
            db,
            model_id="qwen3.5-flash",
        )

    assert "function_calling" in capabilities
    assert "web_search" in capabilities
    assert "web_search_image" in capabilities
    assert "image_search" in capabilities
    assert "web_extractor" in capabilities
    assert "code_interpreter" in capabilities
    assert "file_search" in capabilities
    assert "mcp" in capabilities
    assert "deep_thinking" in capabilities
    assert "responses_api" in capabilities
    assert "vision" in capabilities


def test_build_response_tool_definitions_adds_supported_native_tools_and_configured_tools() -> None:
    with SessionLocal() as db:
        capabilities = orchestrator_service._load_model_capabilities(
            db,
            model_id="qwen3.5-plus",
        )

    tools = orchestrator_service._build_response_tool_definitions(
        llm_model_id="qwen3.5-plus",
        llm_capabilities=capabilities,
        enable_search=True,
        user_message="请读取这个网页 https://example.com ，帮我找几张适合 PPT 的背景图，顺便以图搜图找来源，并用 python 分析这个 csv。",
        image_bytes=b"uploaded-image",
        llm_config_json={
            "responses_native_tools": {
                "file_search": {
                    "vector_store_ids": ["vs_tool_123"],
                    "max_num_results": 6,
                },
                "mcp": {
                    "server_label": "Figma MCP",
                    "server_url": "https://mcp.example.com",
                },
            }
        },
    )

    tool_types = [str(tool.get("type")) for tool in tools]
    assert "function" in tool_types
    assert "web_search" in tool_types
    assert "web_extractor" in tool_types
    assert "web_search_image" in tool_types
    assert "image_search" in tool_types
    assert "code_interpreter" in tool_types
    assert "file_search" in tool_types
    assert "mcp" in tool_types

    file_search_tool = next(tool for tool in tools if tool.get("type") == "file_search")
    assert file_search_tool["vector_store_ids"] == ["vs_tool_123"]
    mcp_tool = next(tool for tool in tools if tool.get("type") == "mcp")
    assert mcp_tool["server_label"] == "Figma MCP"


def test_build_response_tool_definitions_includes_web_search_when_web_extractor_is_selected() -> None:
    with SessionLocal() as db:
        capabilities = orchestrator_service._load_model_capabilities(
            db,
            model_id="qwen3-max",
        )

    tools = orchestrator_service._build_response_tool_definitions(
        llm_model_id="qwen3-max",
        llm_capabilities=capabilities,
        enable_search=False,
        user_message="请提取这个网页的正文：https://help.aliyun.com/zh/model-studio/web-search-image",
        image_bytes=None,
        llm_config_json={},
    )

    tool_types = [str(tool.get("type")) for tool in tools]
    assert "web_extractor" in tool_types
    assert "web_search" in tool_types


def test_ai_gateway_tool_selection_prefilter_adds_dependencies_and_uses_query_rewrite(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_rewrite_query_for_tool_selection(*, user_message, recent_messages, config):
        del recent_messages, config
        captured["rewrite_user_message"] = user_message
        return "reverse image source lookup for uploaded diagram"

    async def fake_rerank_candidate_scores(*, query, candidates, config):
        del config
        captured["rerank_query"] = query
        captured["candidate_keys"] = [candidate.key for candidate in candidates]
        return [
            ai_gateway_tool_selection_service._CandidateScore(key="native:web_extractor", score=0.94),
            ai_gateway_tool_selection_service._CandidateScore(key="native:web_search", score=0.11),
            ai_gateway_tool_selection_service._CandidateScore(key="function:get_current_datetime", score=0.05),
        ]

    monkeypatch.setattr(
        ai_gateway_tool_selection_service,
        "_rewrite_query_for_tool_selection",
        fake_rewrite_query_for_tool_selection,
    )
    monkeypatch.setattr(
        ai_gateway_tool_selection_service,
        "_rerank_candidate_scores",
        fake_rerank_candidate_scores,
    )

    candidates = [
        ai_gateway_tool_selection_service.ToolSelectionCandidate(
            key="native:web_search",
            tool_name="web_search",
            category="native",
            description="Search the public web.",
            definition={"type": "web_search"},
        ),
        ai_gateway_tool_selection_service.ToolSelectionCandidate(
            key="native:web_extractor",
            tool_name="web_extractor",
            category="native",
            description="Extract content from a URL.",
            definition={"type": "web_extractor"},
            dependencies=("web_search",),
        ),
        ai_gateway_tool_selection_service.ToolSelectionCandidate(
            key="function:get_current_datetime",
            tool_name="get_current_datetime",
            category="function",
            description="Get current server time.",
            definition={
                "type": "function",
                "function": {"name": "get_current_datetime"},
            },
        ),
    ]

    result = asyncio.run(
        ai_gateway_tool_selection_service.select_tools_with_ai_gateway_prefilter(
            user_message="读一下这个网页并提取内容",
            recent_messages=[{"role": "user", "content": "上一个问题"}],
            candidates=candidates,
            llm_config_json={
                "ai_gateway_tool_selection": {
                    "enabled": True,
                    "trigger_tool_count": 1,
                    "top_n": 1,
                    "top_k_percent": 100,
                    "score_threshold": 0.0,
                    "query_rewrite_enabled": True,
                    "query_rewrite_turn_threshold": 1,
                }
            },
        )
    )

    assert captured["rewrite_user_message"] == "读一下这个网页并提取内容"
    assert captured["rerank_query"] == "reverse image source lookup for uploaded diagram"
    assert [candidate.tool_name for candidate in result.candidates] == ["web_search", "web_extractor"]
    assert result.trace.used_query_rewrite is True
    assert result.trace.source == "ai_gateway_prefilter"


def test_ai_gateway_tool_selection_bypasses_on_rerank_failure(monkeypatch) -> None:
    async def fake_rerank_candidate_scores(*, query, candidates, config):
        del query, candidates, config
        raise RuntimeError("rerank unavailable")

    monkeypatch.setattr(
        ai_gateway_tool_selection_service,
        "_rerank_candidate_scores",
        fake_rerank_candidate_scores,
    )

    candidates = [
        ai_gateway_tool_selection_service.ToolSelectionCandidate(
            key="function:get_current_datetime",
            tool_name="get_current_datetime",
            category="function",
            description="Get current server time.",
            definition={
                "type": "function",
                "function": {"name": "get_current_datetime"},
            },
        ),
        ai_gateway_tool_selection_service.ToolSelectionCandidate(
            key="function:search_project_memories",
            tool_name="search_project_memories",
            category="function",
            description="Search project memories.",
            definition={
                "type": "function",
                "function": {"name": "search_project_memories"},
            },
        ),
    ]

    result = asyncio.run(
        ai_gateway_tool_selection_service.select_tools_with_ai_gateway_prefilter(
            user_message="现在几点",
            recent_messages=[{"role": "user", "content": "前文"}],
            candidates=candidates,
            llm_config_json={
                "ai_gateway_tool_selection": {
                    "enabled": True,
                    "trigger_tool_count": 1,
                    "failure_mode": "bypass",
                    "query_rewrite_enabled": False,
                }
            },
        )
    )

    assert [candidate.key for candidate in result.candidates] == [candidate.key for candidate in candidates]
    assert result.trace.source == "ai_gateway_bypass"
    assert "rerank unavailable" in str(result.trace.failure_reason)


def test_response_enable_thinking_forces_required_native_tools_on_qwen3_max() -> None:
    assert orchestrator_service._response_enable_thinking_value(
        llm_model_id="qwen3-max",
        enable_thinking=False,
        tool_definitions=[{"type": "code_interpreter"}],
    ) is True
    assert orchestrator_service._response_enable_thinking_value(
        llm_model_id="qwen3-max",
        enable_thinking=False,
        tool_definitions=[{"type": "web_extractor"}],
    ) is True
    assert orchestrator_service._response_enable_thinking_value(
        llm_model_id="qwen3.5-plus",
        enable_thinking=False,
        tool_definitions=[{"type": "code_interpreter"}],
    ) is True
    assert orchestrator_service._response_enable_thinking_value(
        llm_model_id="qwen3.5-flash",
        enable_thinking=False,
        tool_definitions=[{"type": "web_extractor"}],
    ) is True


def test_build_and_call_llm_uses_responses_auto_tools_for_image_input_when_supported(monkeypatch) -> None:
    client = TestClient(main_module.app)
    register_user(client, "chat-image-responses@example.com", "Chat Image Responses")
    project = create_project(client, "Chat Image Responses Project")
    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Image Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200

    captured: dict[str, object] = {}

    async def fake_search_similar(*args, **kwargs) -> list[dict]:
        return []

    async def fake_responses_completion_detailed(
        input_items,
        *,
        model=None,
        enable_thinking=None,
        tools=None,
        tool_choice="auto",
        image_bytes=None,
        image_mime_type="image/jpeg",
    ):
        del input_items, model, enable_thinking, tool_choice
        captured["tools"] = tools
        captured["image_bytes"] = image_bytes
        captured["image_mime_type"] = image_mime_type
        return SimpleNamespace(
            content="我看到了图片内容",
            reasoning_content=None,
            search_sources=[],
            tool_calls=[],
        )

    async def fail_chat_completion_multimodal_detailed(*args, **kwargs):
        raise AssertionError("image input should use responses auto tools instead of legacy multimodal path")

    monkeypatch.setattr(orchestrator_service, "search_similar", fake_search_similar)
    monkeypatch.setattr(
        orchestrator_service,
        "responses_completion_detailed",
        fake_responses_completion_detailed,
    )
    monkeypatch.setattr(
        orchestrator_service,
        "chat_completion_multimodal_detailed",
        fail_chat_completion_multimodal_detailed,
    )

    with SessionLocal() as db:
        result = asyncio.run(
            orchestrator_service._build_and_call_llm(
                db,
                workspace_id=project["workspace_id"],
                project_id=project["id"],
                conversation_id=conversation.json()["id"],
                user_message="请描述这张图片",
                recent_messages=[],
                llm_model_id="qwen3.5-plus",
                image_bytes=b"image-binary",
                image_mime_type="image/png",
                enable_thinking=False,
                enable_search=True,
            )
        )

    assert result["content"] == "我看到了图片内容"
    assert captured["image_bytes"] == b"image-binary"
    assert captured["image_mime_type"] == "image/png"
    assert {"type": "web_search"} in (captured["tools"] or [])


def test_build_and_call_llm_uses_chat_function_tools_for_non_responses_models(monkeypatch) -> None:
    client = TestClient(main_module.app)
    register_user(client, "chat-function-tools@example.com", "Chat Function Tools")
    project = create_project(client, "Chat Function Tools Project")
    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Tool Loop Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200

    call_count = {"value": 0}
    captured_tool_payloads: list[dict[str, object] | None] = []
    captured_messages: list[list[dict[str, object]]] = []

    async def fake_search_similar(*args, **kwargs) -> list[dict]:
        return []

    async def fail_responses_completion_detailed(*args, **kwargs):
        raise AssertionError("non-responses models should not use responses auto tools")

    async def fake_chat_completion_detailed(
        messages,
        model=None,
        temperature=0.7,
        max_tokens=2048,
        enable_thinking=None,
        enable_search=None,
        search_options=None,
        tools=None,
        tool_choice=None,
        parallel_tool_calls=None,
    ):
        del model, temperature, max_tokens, enable_thinking, enable_search, search_options, tool_choice, parallel_tool_calls
        captured_tool_payloads.append(tools)
        captured_messages.append([dict(message) for message in messages])
        call_count["value"] += 1
        if call_count["value"] == 1:
            return SimpleNamespace(
                content="",
                reasoning_content=None,
                search_sources=[],
                tool_calls=[
                    SimpleNamespace(
                        id="tool-call-1",
                        name="get_current_datetime",
                        arguments='{"timezone":"Europe/London"}',
                        type="function",
                    )
                ],
            )
        return SimpleNamespace(
            content="工具调用成功",
            reasoning_content=None,
            search_sources=[],
            tool_calls=[],
        )

    monkeypatch.setattr(orchestrator_service, "search_similar", fake_search_similar)
    monkeypatch.setattr(
        orchestrator_service,
        "_assemble_prompt_context",
        lambda *args, **kwargs: asyncio.sleep(
            0,
            result=([{"role": "system", "content": "sys"}, {"role": "user", "content": "u"}], {}),
        ),
    )
    monkeypatch.setattr(
        orchestrator_service,
        "_resolve_search_options",
        lambda *args, **kwargs: asyncio.sleep(
            0,
            result=SimpleNamespace(enable_search=False, search_options=None),
        ),
    )
    monkeypatch.setattr(
        orchestrator_service,
        "resolve_enable_thinking",
        lambda *args, **kwargs: asyncio.sleep(0, result=SimpleNamespace(enable_thinking=False)),
    )
    monkeypatch.setattr(
        orchestrator_service,
        "responses_completion_detailed",
        fail_responses_completion_detailed,
    )
    monkeypatch.setattr(
        orchestrator_service,
        "chat_completion_detailed",
        fake_chat_completion_detailed,
    )

    with SessionLocal() as db:
        result = asyncio.run(
            orchestrator_service._build_and_call_llm(
                db,
                workspace_id=project["workspace_id"],
                project_id=project["id"],
                conversation_id=conversation.json()["id"],
                user_message="现在伦敦几点？",
                recent_messages=[],
                llm_model_id="deepseek-v3.2",
                enable_thinking=False,
                enable_search=False,
            )
        )

    assert result["content"] == "工具调用成功"
    assert call_count["value"] == 2
    assert captured_tool_payloads[0]
    first_tool_names = {
        tool["function"]["name"]
        for tool in captured_tool_payloads[0] or []
        if isinstance(tool, dict) and isinstance(tool.get("function"), dict)
    }
    assert "get_current_datetime" in first_tool_names
    assert any(message.get("role") == "tool" for message in captured_messages[1])


def test_build_and_call_llm_records_ai_gateway_tool_selection_trace(monkeypatch) -> None:
    client = TestClient(main_module.app)
    register_user(client, "tool-selection-trace@example.com", "Tool Selection Trace")
    project = create_project(client, "Tool Selection Trace Project")
    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Trace Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200

    captured: dict[str, object] = {}

    async def fake_search_similar(*args, **kwargs) -> list[dict]:
        return []

    async def fake_responses_completion_detailed(
        input_items,
        model=None,
        enable_thinking=None,
        tools=None,
        tool_choice="auto",
        timeout=90.0,
        image_bytes=None,
        image_mime_type="image/jpeg",
    ):
        del input_items, model, enable_thinking, tool_choice, timeout, image_bytes, image_mime_type
        captured["tools"] = tools
        return orchestrator_service.ChatCompletionResult(content="已完成")

    async def fake_select_response_tool_definitions(**kwargs):
        del kwargs
        return (
            [{"type": "web_search_image"}],
            {
                "source": "ai_gateway_prefilter",
                "candidate_count": 5,
                "selected_tool_names": ["web_search_image"],
                "applied": True,
                "query": "找一张适合演示的背景图",
            },
        )

    monkeypatch.setattr(orchestrator_service, "search_similar", fake_search_similar)
    monkeypatch.setattr(
        orchestrator_service,
        "_assemble_prompt_context",
        lambda *args, **kwargs: asyncio.sleep(
            0,
            result=([{"role": "system", "content": "sys"}, {"role": "user", "content": "u"}], {}),
        ),
    )
    monkeypatch.setattr(
        orchestrator_service,
        "_resolve_search_options",
        lambda *args, **kwargs: asyncio.sleep(
            0,
            result=SimpleNamespace(enable_search=False, search_options=None),
        ),
    )
    monkeypatch.setattr(
        orchestrator_service,
        "resolve_enable_thinking",
        lambda *args, **kwargs: asyncio.sleep(0, result=SimpleNamespace(enable_thinking=False)),
    )
    monkeypatch.setattr(
        orchestrator_service,
        "_select_response_tool_definitions",
        fake_select_response_tool_definitions,
    )
    monkeypatch.setattr(
        orchestrator_service,
        "responses_completion_detailed",
        fake_responses_completion_detailed,
    )

    with SessionLocal() as db:
        result = asyncio.run(
            orchestrator_service._build_and_call_llm(
                db,
                workspace_id=project["workspace_id"],
                project_id=project["id"],
                conversation_id=conversation.json()["id"],
                user_message="找一张适合演示的背景图",
                recent_messages=[],
                llm_model_id="qwen3.5-plus",
                enable_thinking=False,
                enable_search=False,
            )
        )

    assert captured["tools"] == [{"type": "web_search_image"}]
    assert result["retrieval_trace"]["tool_selection"]["source"] == "ai_gateway_prefilter"
    assert result["retrieval_trace"]["tool_selection"]["selected_tool_names"] == ["web_search_image"]


def test_build_and_call_llm_falls_back_to_legacy_multimodal_for_video_input(monkeypatch) -> None:
    client = TestClient(main_module.app)
    register_user(client, "chat-video-fallback@example.com", "Chat Video Fallback")
    project = create_project(client, "Chat Video Fallback Project")
    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Video Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200

    captured: dict[str, object] = {}

    async def fake_search_similar(*args, **kwargs) -> list[dict]:
        return []

    async def fail_responses_completion_detailed(*args, **kwargs):
        raise AssertionError("video input should not use responses auto tools")

    async def fake_chat_completion_multimodal_detailed(
        messages,
        *,
        model=None,
        audio_bytes=None,
        audio_mime_type="audio/wav",
        image_bytes=None,
        image_mime_type="image/jpeg",
        video_bytes=None,
        video_mime_type="video/mp4",
        temperature=0.7,
        max_tokens=2048,
        enable_thinking=None,
        enable_search=None,
        search_options=None,
        tools=None,
        tool_choice=None,
        parallel_tool_calls=None,
    ):
        del messages, model, audio_bytes, audio_mime_type, image_bytes, image_mime_type
        del temperature, max_tokens, enable_thinking, enable_search, search_options
        del tools, tool_choice, parallel_tool_calls
        captured["video_bytes"] = video_bytes
        captured["video_mime_type"] = video_mime_type
        return SimpleNamespace(
            content="我看到了视频内容",
            reasoning_content=None,
            search_sources=[],
            tool_calls=[],
        )

    monkeypatch.setattr(orchestrator_service, "search_similar", fake_search_similar)
    monkeypatch.setattr(
        orchestrator_service,
        "responses_completion_detailed",
        fail_responses_completion_detailed,
    )
    monkeypatch.setattr(
        orchestrator_service,
        "chat_completion_multimodal_detailed",
        fake_chat_completion_multimodal_detailed,
    )

    with SessionLocal() as db:
        result = asyncio.run(
            orchestrator_service._build_and_call_llm(
                db,
                workspace_id=project["workspace_id"],
                project_id=project["id"],
                conversation_id=conversation.json()["id"],
                user_message="请描述这个视频",
                recent_messages=[],
                llm_model_id="qwen3.5-plus",
                video_bytes=b"video-binary",
                video_mime_type="video/mp4",
                enable_thinking=False,
                enable_search=True,
            )
        )

    assert result["content"] == "我看到了视频内容"
    assert captured["video_bytes"] == b"video-binary"
    assert captured["video_mime_type"] == "video/mp4"


def test_thinking_classifier_handles_ambiguous_queries(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_chat_completion_detailed(
        messages,
        model=None,
        *,
        temperature=0.7,
        max_tokens=2048,
        enable_thinking=None,
        enable_search=None,
        search_options=None,
        tools=None,
        tool_choice=None,
        parallel_tool_calls=None,
    ):
        del messages, temperature, max_tokens, enable_search
        del search_options, tools, tool_choice, parallel_tool_calls
        captured["model"] = model
        captured["enable_thinking"] = enable_thinking
        return orchestrator_service.ChatCompletionResult(
            content=json.dumps(
                {
                    "enable_thinking": True,
                    "confidence": 0.87,
                    "reason": "The request benefits from deliberate decomposition.",
                }
            )
        )

    monkeypatch.setattr(orchestrator_service, "chat_completion_detailed", fake_chat_completion_detailed)

    with SessionLocal() as db:
        decision = asyncio.run(
            orchestrator_service.resolve_enable_thinking(
                db,
                project_id="proj-test",
                llm_model_id="qwen3.5-plus",
                user_message="I have several moving parts here and need a careful response.",
                recent_messages=[],
                preference=None,
            )
        )

    assert captured["model"] == "qwen3.5-flash"
    assert captured["enable_thinking"] is False
    assert decision.enable_thinking is True
    assert decision.source == "classifier"
    assert decision.confidence == pytest.approx(0.87)


def test_web_search_rules_keep_local_time_queries_offline(monkeypatch) -> None:
    classifier_called = False

    async def fake_chat_completion_detailed(
        messages,
        model=None,
        *,
        temperature=0.7,
        max_tokens=2048,
        enable_thinking=None,
        enable_search=None,
        search_options=None,
        tools=None,
        tool_choice=None,
        parallel_tool_calls=None,
    ):
        nonlocal classifier_called
        del messages, model, temperature, max_tokens, enable_thinking, enable_search
        del search_options, tools, tool_choice, parallel_tool_calls
        classifier_called = True
        return orchestrator_service.ChatCompletionResult(content="{}")

    monkeypatch.setattr(orchestrator_service, "chat_completion_detailed", fake_chat_completion_detailed)

    with SessionLocal() as db:
        decision = asyncio.run(
            orchestrator_service._resolve_search_options(
                db,
                llm_model_id="qwen3.5-plus",
                llm_capabilities={"web_search"},
                user_message="今天几号？",
                recent_messages=[],
                preference=None,
            )
        )

    assert classifier_called is False
    assert decision.enable_search is False
    assert decision.route == "local_only"
    assert decision.source == "rules"


def test_web_search_rules_enable_search_for_freshness_hints(monkeypatch) -> None:
    classifier_called = False

    async def fake_chat_completion_detailed(
        messages,
        model=None,
        *,
        temperature=0.7,
        max_tokens=2048,
        enable_thinking=None,
        enable_search=None,
        search_options=None,
        tools=None,
        tool_choice=None,
        parallel_tool_calls=None,
    ):
        nonlocal classifier_called
        del messages, model, temperature, max_tokens, enable_thinking, enable_search
        del search_options, tools, tool_choice, parallel_tool_calls
        classifier_called = True
        return orchestrator_service.ChatCompletionResult(content="{}")

    monkeypatch.setattr(orchestrator_service, "chat_completion_detailed", fake_chat_completion_detailed)

    with SessionLocal() as db:
        decision = asyncio.run(
            orchestrator_service._resolve_search_options(
                db,
                llm_model_id="qwen3.5-plus",
                llm_capabilities={"web_search"},
                user_message="今天英伟达股价多少？",
                recent_messages=[],
                preference=None,
            )
        )

    assert classifier_called is False
    assert decision.enable_search is True
    assert decision.route == "web_only"
    assert decision.source == "rules"


def test_chat_completion_stream_explicitly_sends_false_enable_thinking(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeStreamResponse:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            del exc_type, exc, tb
            return False

        def raise_for_status(self) -> None:
            return None

        async def aiter_lines(self):
            yield 'data: {"choices":[{"delta":{"content":"你好"},"finish_reason":null}]}'
            yield "data: [DONE]"

    class FakeClient:
        def stream(self, method, url, headers=None, json=None, timeout=None):
            captured["method"] = method
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            captured["timeout"] = timeout
            return FakeStreamResponse()

    monkeypatch.setattr(dashscope_stream_service, "get_client", lambda: FakeClient())

    async def collect_chunks() -> list[dashscope_stream_service.StreamChunk]:
        chunks: list[dashscope_stream_service.StreamChunk] = []
        async for chunk in dashscope_stream_service.chat_completion_stream(
            [{"role": "user", "content": "你好"}],
            model="qwen3.5-plus",
            enable_thinking=False,
        ):
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(collect_chunks())

    # Filter the empty synthetic closing chunk added by S1 (carries usage/model_id only).
    assert [chunk.content for chunk in chunks if chunk.content] == ["你好"]
    assert chunks[-1].finish_reason == "stop"
    assert isinstance(captured["json"], dict)
    assert captured["json"]["enable_thinking"] is False


def test_send_message_returns_explicit_error_when_model_api_is_unconfigured(monkeypatch) -> None:
    client = TestClient(main_module.app)
    register_user(client, "chat-unconfigured@example.com", "Chat Unconfigured")
    project = create_project(client, "Chat Unconfigured Project")
    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200
    conversation_id = conversation.json()["id"]

    monkeypatch.setattr(chat_router.settings, "dashscope_api_key", "")

    resp = client.post(
        f"/api/v1/chat/conversations/{conversation_id}/messages",
        json={"content": "hello world"},
        headers=csrf_headers(client),
    )

    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "model_api_unconfigured"

    messages = client.get(
        f"/api/v1/chat/conversations/{conversation_id}/messages",
        headers={"origin": ORIGIN},
    )
    assert messages.status_code == 200
    assert messages.json() == []


def test_send_message_survives_non_fatal_rag_failure(monkeypatch) -> None:
    client = TestClient(main_module.app)
    register_user(client, "chat-rag-failure@example.com", "Chat Rag Failure")
    project = create_project(client, "Chat Rag Failure Project")
    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200
    conversation_id = conversation.json()["id"]

    async def fake_search_similar(*args, **kwargs):
        raise RuntimeError("vector lookup failed")

    async def fake_responses_completion_detailed(
        input_items,
        *,
        model=None,
        enable_thinking=None,
        tools=None,
        tool_choice="auto",
        image_bytes=None,
        image_mime_type="image/jpeg",
    ):  # noqa: ARG001
        del input_items, model, enable_thinking, tools, tool_choice, image_bytes, image_mime_type
        return SimpleNamespace(content="rag fallback ok", reasoning_content=None, search_sources=[], tool_calls=[])

    monkeypatch.setattr(chat_router.settings, "dashscope_api_key", "test-key")
    monkeypatch.setattr(orchestrator_service, "search_similar", fake_search_similar)
    monkeypatch.setattr(
        orchestrator_service,
        "responses_completion_detailed",
        fake_responses_completion_detailed,
    )

    resp = client.post(
        f"/api/v1/chat/conversations/{conversation_id}/messages",
        json={"content": "hello world"},
        headers=csrf_headers(client),
    )

    assert resp.status_code == 200
    assert resp.json()["content"] == "rag fallback ok"

    messages = client.get(
        f"/api/v1/chat/conversations/{conversation_id}/messages",
        headers={"origin": ORIGIN},
    )
    assert messages.status_code == 200
    assert [item["role"] for item in messages.json()] == ["user", "assistant"]


def test_dictate_voice_input_transcribes_audio_without_creating_messages(monkeypatch) -> None:
    monkeypatch.setattr(chat_router.settings, "dashscope_api_key", "test-key")
    client = TestClient(main_module.app)
    register_user(client, "chat-dictate@example.com", "Chat Dictate")
    project = create_project(client, "Chat Dictate Project")
    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200
    conversation_id = conversation.json()["id"]

    async def fake_transcribe_audio_input_for_project(*args, **kwargs):
        assert kwargs["project_id"] == project["id"]
        assert kwargs["audio_bytes"] == b"voice-audio"
        assert kwargs["filename"] == "recording.webm"
        return "这是听写结果"

    monkeypatch.setattr(
        chat_router,
        "transcribe_audio_input_for_project",
        fake_transcribe_audio_input_for_project,
    )

    dictated = client.post(
        f"/api/v1/chat/conversations/{conversation_id}/dictate",
        files={"audio": ("recording.webm", b"voice-audio", "audio/webm")},
        headers=csrf_headers(client),
    )
    assert dictated.status_code == 200
    assert dictated.json()["text_input"] == "这是听写结果"

    messages = client.get(f"/api/v1/chat/conversations/{conversation_id}/messages")
    assert messages.status_code == 200
    assert messages.json() == []


def test_dictate_voice_input_accepts_media_type_parameters(monkeypatch) -> None:
    monkeypatch.setattr(chat_router.settings, "dashscope_api_key", "test-key")
    client = TestClient(main_module.app)
    register_user(client, "chat-dictate-codecs@example.com", "Chat Dictate Codecs")
    project = create_project(client, "Chat Dictate Codecs Project")
    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200
    conversation_id = conversation.json()["id"]

    async def fake_transcribe_audio_input_for_project(*args, **kwargs):
        assert kwargs["project_id"] == project["id"]
        assert kwargs["audio_bytes"] == b"voice-audio"
        assert kwargs["filename"] == "recording.webm"
        return "带参数的音频头也能过"

    monkeypatch.setattr(
        chat_router,
        "transcribe_audio_input_for_project",
        fake_transcribe_audio_input_for_project,
    )

    dictated = client.post(
        f"/api/v1/chat/conversations/{conversation_id}/dictate",
        files={"audio": ("recording.webm", b"voice-audio", "audio/webm;codecs=opus")},
        headers=csrf_headers(client),
    )
    assert dictated.status_code == 200
    assert dictated.json()["text_input"] == "带参数的音频头也能过"


def test_speech_endpoint_synthesizes_audio_without_creating_messages(monkeypatch) -> None:
    monkeypatch.setattr(chat_router.settings, "dashscope_api_key", "test-key")
    client = TestClient(main_module.app)
    register_user(client, "chat-speech@example.com", "Chat Speech")
    project = create_project(client, "Chat Speech Project")
    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200
    conversation_id = conversation.json()["id"]

    async def fake_synthesize_speech_for_project(*args, **kwargs):
        assert kwargs["project_id"] == project["id"]
        assert kwargs["text"] == "请朗读这段回复"
        return b"\x01\x02\x03"

    monkeypatch.setattr(
        chat_router,
        "synthesize_speech_for_project",
        fake_synthesize_speech_for_project,
    )

    spoken = client.post(
        f"/api/v1/chat/conversations/{conversation_id}/speech",
        json={"content": "请朗读这段回复"},
        headers=csrf_headers(client),
    )
    assert spoken.status_code == 200
    assert spoken.json()["audio_response"] == "AQID"

    messages = client.get(f"/api/v1/chat/conversations/{conversation_id}/messages")
    assert messages.status_code == 200
    assert messages.json() == []


def test_speech_endpoint_clamps_voice_reply_before_tts(monkeypatch) -> None:
    monkeypatch.setattr(chat_router.settings, "dashscope_api_key", "test-key")
    client = TestClient(main_module.app)
    register_user(client, "chat-speech-clamp@example.com", "Chat Speech Clamp")
    project = create_project(client, "Chat Speech Clamp Project")
    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200
    conversation_id = conversation.json()["id"]

    async def fake_synthesize_speech_for_project(*args, **kwargs):
        assert kwargs["project_id"] == project["id"]
        assert kwargs["text"] == "第一句先回答。第二句补充一点。"
        return b"\x01\x02\x03"

    monkeypatch.setattr(
        chat_router,
        "synthesize_speech_for_project",
        fake_synthesize_speech_for_project,
    )

    spoken = client.post(
        f"/api/v1/chat/conversations/{conversation_id}/speech",
        json={"content": "第一句先回答。第二句补充一点。第三句不应该再播了。"},
        headers=csrf_headers(client),
    )
    assert spoken.status_code == 200
    assert spoken.json()["audio_response"] == "AQID"


def test_transcribe_audio_input_for_project_falls_back_to_qwen3_asr_flash(monkeypatch) -> None:
    client = TestClient(main_module.app)
    register_user(client, "chat-asr-fallback@example.com", "Chat ASR Fallback")
    project = create_project(client, "Chat ASR Fallback Project")

    captured: dict[str, object] = {}

    async def fake_transcribe_audio(audio_bytes: bytes, filename: str = "audio.wav", model: str | None = None, content_type: str | None = None) -> str:
        captured["audio_bytes"] = audio_bytes
        captured["filename"] = filename
        captured["model"] = model
        return "fallback ok"

    monkeypatch.setattr("app.services.asr_client.transcribe_audio", fake_transcribe_audio)

    with SessionLocal() as db:
        result = asyncio.run(
            orchestrator_service.transcribe_audio_input_for_project(
                db,
                project_id=project["id"],
                audio_bytes=b"voice-audio",
                filename="recording.webm",
            )
        )

    assert result == "fallback ok"
    assert captured["audio_bytes"] == b"voice-audio"
    assert captured["filename"] == "recording.webm"
    assert captured["model"] == "qwen3-asr-flash"


def test_synthesize_speech_for_project_falls_back_to_qwen3_tts_flash(monkeypatch) -> None:
    client = TestClient(main_module.app)
    register_user(client, "chat-tts-fallback@example.com", "Chat TTS Fallback")
    project = create_project(client, "Chat TTS Fallback Project")

    captured: dict[str, object] = {}

    async def fake_synthesize_speech(text: str, model: str | None = None, voice: str = "Cherry") -> bytes:
        captured["text"] = text
        captured["model"] = model
        captured["voice"] = voice
        return b"\x01\x02"

    monkeypatch.setattr("app.services.tts_client.synthesize_speech", fake_synthesize_speech)

    with SessionLocal() as db:
        result = asyncio.run(
            orchestrator_service.synthesize_speech_for_project(
                db,
                project_id=project["id"],
                text="请朗读这段回复",
            )
        )

    assert result == b"\x01\x02"
    assert captured["text"] == "请朗读这段回复"
    assert captured["model"] == "qwen3-tts-flash"


def test_image_endpoint_uses_prompt_and_preserves_image_mime_type(monkeypatch) -> None:
    monkeypatch.setattr(chat_router.settings, "dashscope_api_key", "test-key")
    client = TestClient(main_module.app)
    register_user(client, "chat-image@example.com", "Chat Image")
    project = create_project(client, "Chat Image Project")
    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200
    conversation_id = conversation.json()["id"]

    captured: dict[str, object] = {}

    async def fake_orchestrate_voice_inference(*args, **kwargs):
        captured.update(kwargs)
        return {
            "text_input": "帮我看看这个图",
            "text_response": "这是一张测试图片。",
            "audio_response": b"\x01\x02\x03",
        }

    monkeypatch.setattr(chat_router, "orchestrate_voice_inference", fake_orchestrate_voice_inference)

    image_bytes, media_type = upload_fixture("example.png")
    response = client.post(
        f"/api/v1/chat/conversations/{conversation_id}/image",
        data={"prompt": "帮我看看这个图"},
        files={"image": ("example.png", image_bytes, media_type)},
        headers=csrf_headers(client),
    )

    assert response.status_code == 200
    assert captured["project_id"] == project["id"]
    assert captured["conversation_id"] == conversation_id
    assert captured["image_bytes"] == image_bytes
    assert captured["image_mime_type"] == "image/png"
    assert captured["text_input"] == "帮我看看这个图"
    assert response.json()["message"]["content"] == "这是一张测试图片。"
    assert response.json()["audio_response"] == "AQID"


def test_memory_routes_return_204_and_search_falls_back_without_embeddings() -> None:
    client = TestClient(main_module.app)
    register_user(client, "memory@example.com", "Memory")
    project = create_project(client, "Memory Project")

    first = client.post(
        "/api/v1/memory",
        json={"project_id": project["id"], "content": "用户喜欢黑咖啡", "category": "偏好", "type": "permanent"},
        headers=csrf_headers(client),
    )
    assert first.status_code == 200
    second = client.post(
        "/api/v1/memory",
        json={"project_id": project["id"], "content": "用户计划四月去东京", "category": "计划", "type": "permanent"},
        headers=csrf_headers(client),
    )
    assert second.status_code == 200

    edge = client.post(
        "/api/v1/memory/edges",
        json={
            "source_memory_id": first.json()["id"],
            "target_memory_id": second.json()["id"],
        },
        headers=csrf_headers(client),
    )
    assert edge.status_code == 200
    assert edge.json()["edge_type"] == "manual"

    search = client.post(
        "/api/v1/memory/search",
        json={"project_id": project["id"], "query": "黑咖啡", "top_k": 5},
        headers=csrf_headers(client),
    )
    assert search.status_code == 200
    results = search.json()
    assert len(results) == 1
    assert results[0]["memory"]["content"] == "用户喜欢黑咖啡"

    delete_edge = client.delete(
        f"/api/v1/memory/edges/{edge.json()['id']}",
        headers=csrf_headers(client),
    )
    assert delete_edge.status_code == 204
    assert delete_edge.content == b""

    delete_memory = client.delete(
        f"/api/v1/memory/{first.json()['id']}",
        headers=csrf_headers(client),
    )
    assert delete_memory.status_code == 204
    assert delete_memory.content == b""


def test_memory_backfill_populates_views_and_project_evidences() -> None:
    client = TestClient(main_module.app)
    user_info = register_user(client, "memory-backfill@example.com", "Memory Backfill")
    workspace_id = user_info["workspace"]["id"]
    user_id = user_info["user"]["id"]
    project = create_project(client, "Memory Backfill Project")

    conversation_id = create_conversation_record(
        workspace_id,
        project["id"],
        user_id,
        "Memory Backfill Thread",
    )
    with SessionLocal() as db:
        db.add(
            Message(
                conversation_id=conversation_id,
                role="user",
                content="我喜欢手冲咖啡。排查路由器时先检查电源，再确认指示灯，最后重启设备。昨天我调试了网络。",
            )
        )
        db.commit()

    subject = client.post(
        "/api/v1/memory",
        json={
            "project_id": project["id"],
            "content": "用户",
            "category": "主体",
            "type": "permanent",
            "node_type": "subject",
            "subject_kind": "user",
            "parent_memory_id": project["assistant_root_memory_id"],
        },
        headers=csrf_headers(client),
    )
    assert subject.status_code == 200
    subject_id = subject.json()["id"]

    profile = client.post(
        "/api/v1/memory",
        json={
            "project_id": project["id"],
            "content": "用户喜欢手冲咖啡",
            "category": "偏好.饮品",
            "type": "permanent",
            "parent_memory_id": subject_id,
            "source_conversation_id": conversation_id,
        },
        headers=csrf_headers(client),
    )
    assert profile.status_code == 200

    playbook = client.post(
        "/api/v1/memory",
        json={
            "project_id": project["id"],
            "content": "排查路由器时先检查电源，再确认指示灯，最后重启设备",
            "category": "方法.网络",
            "type": "permanent",
            "parent_memory_id": subject_id,
            "source_conversation_id": conversation_id,
        },
        headers=csrf_headers(client),
    )
    assert playbook.status_code == 200

    episodic = client.post(
        "/api/v1/memory",
        json={
            "project_id": project["id"],
            "content": "昨天调试了路由器网络",
            "category": "经历.网络",
            "type": "temporary",
            "parent_memory_id": subject_id,
            "source_conversation_id": conversation_id,
            "metadata_json": {"memory_kind": "episodic"},
        },
        headers=csrf_headers(client),
    )
    assert episodic.status_code == 200

    backfill = client.post(
        "/api/v1/memory/backfill",
        json={"project_id": project["id"]},
        headers=csrf_headers(client),
    )
    assert backfill.status_code == 200
    payload = backfill.json()
    assert payload["status"] == "completed"
    assert payload["summary"]["evidences_created"] >= 3
    assert payload["summary"]["profile_views_refreshed"] >= 1
    assert payload["summary"]["timeline_views_refreshed"] >= 1
    assert payload["summary"]["playbook_views_refreshed"] >= 1

    subject_detail = client.get(f"/api/v1/memory/{subject_id}")
    assert subject_detail.status_code == 200
    view_types = {item["view_type"] for item in subject_detail.json()["views"]}
    assert {"profile", "timeline", "playbook"}.issubset(view_types)

    profile_detail = client.get(f"/api/v1/memory/{profile.json()['id']}")
    assert profile_detail.status_code == 200
    assert profile_detail.json()["evidences"]

    view_response = client.get(f"/api/v1/memory/views?project_id={project['id']}")
    assert view_response.status_code == 200
    assert {"profile", "timeline", "playbook"}.issubset(
        {item["view_type"] for item in view_response.json()}
    )

    evidence_response = client.get(f"/api/v1/memory/evidences?project_id={project['id']}")
    assert evidence_response.status_code == 200
    evidence_memory_ids = {item["memory_id"] for item in evidence_response.json()}
    assert profile.json()["id"] in evidence_memory_ids
    assert playbook.json()["id"] in evidence_memory_ids
    assert episodic.json()["id"] in evidence_memory_ids


def test_project_creation_initializes_assistant_root_memory() -> None:
    client = TestClient(main_module.app)
    register_user(client, "memory-root@example.com", "Memory Root")
    project = create_project(client, "医生助手")

    assert project["assistant_root_memory_id"]

    graph = client.get(f"/api/v1/memory?project_id={project['id']}")
    assert graph.status_code == 200
    root = next(
        node
        for node in graph.json()["nodes"]
        if node["id"] == project["assistant_root_memory_id"]
    )
    assert root["metadata_json"]["node_kind"] == "assistant-root"
    assert root["content"] == "医生助手"
    assert root["parent_memory_id"] is None


def test_memory_creation_defaults_to_project_root_and_root_is_protected() -> None:
    client = TestClient(main_module.app)
    register_user(client, "memory-default-parent@example.com", "Memory Default Parent")
    project = create_project(client, "默认根记忆项目")
    root_id = project["assistant_root_memory_id"]

    memory = client.post(
        "/api/v1/memory",
        json={"project_id": project["id"], "content": "用户喜欢晨间沟通", "category": "偏好", "type": "permanent"},
        headers=csrf_headers(client),
    )
    assert memory.status_code == 200
    assert memory.json()["parent_memory_id"] == root_id

    search = client.post(
        "/api/v1/memory/search",
        json={"project_id": project["id"], "query": "默认根记忆项目", "top_k": 5},
        headers=csrf_headers(client),
    )
    assert search.status_code == 200
    assert search.json() == []

    update_root = client.patch(
        f"/api/v1/memory/{root_id}",
        json={"content": "不允许修改"},
        headers=csrf_headers(client),
    )
    assert update_root.status_code == 400
    assert update_root.json()["error"]["code"] == "bad_request"

    delete_root = client.delete(
        f"/api/v1/memory/{root_id}",
        headers=csrf_headers(client),
    )
    assert delete_root.status_code == 400
    assert delete_root.json()["error"]["code"] == "bad_request"


def test_memory_update_can_manually_rebind_and_disconnect_parent() -> None:
    client = TestClient(main_module.app)
    user_info = register_user(client, "memory-manual-parent@example.com", "Memory Manual Parent")
    workspace_id = user_info["workspace"]["id"]
    project = create_project(client, "手动父节点项目")
    root_id = project["assistant_root_memory_id"]

    child = client.post(
        "/api/v1/memory",
        json={"project_id": project["id"], "content": "用户来自中国", "category": "身份.国籍", "type": "permanent"},
        headers=csrf_headers(client),
    )
    assert child.status_code == 200

    with SessionLocal() as db:
        concept_parent = Memory(
            workspace_id=workspace_id,
            project_id=project["id"],
            content="用户正在准备主题分享",
            category="工作.项目",
            type="permanent",
            parent_memory_id=root_id,
            metadata_json={"memory_kind": "goal", "node_kind": "concept", "auto_generated": True},
        )
        db.add(concept_parent)
        db.commit()
        concept_parent_id = concept_parent.id

    rebind = client.patch(
        f"/api/v1/memory/{child.json()['id']}",
        json={"parent_memory_id": concept_parent_id},
        headers=csrf_headers(client),
    )
    assert rebind.status_code == 200
    rebound_body = rebind.json()
    assert rebound_body["parent_memory_id"] == concept_parent_id
    assert rebound_body["metadata_json"]["parent_binding"] == "manual"
    assert rebound_body["metadata_json"]["manual_parent_id"] == concept_parent_id

    graph_after_rebind = client.get(f"/api/v1/memory?project_id={project['id']}")
    assert graph_after_rebind.status_code == 200
    rebound_child = next(
        node for node in graph_after_rebind.json()["nodes"] if node["id"] == child.json()["id"]
    )
    assert rebound_child["parent_memory_id"] == concept_parent_id

    detach = client.patch(
        f"/api/v1/memory/{child.json()['id']}",
        json={"parent_memory_id": None},
        headers=csrf_headers(client),
    )
    assert detach.status_code == 200
    detached_body = detach.json()
    assert detached_body["parent_memory_id"] == root_id
    assert detached_body["metadata_json"]["parent_binding"] == "manual"
    assert detached_body["metadata_json"]["manual_parent_id"] is None


def test_memory_rejects_ordinary_primary_parent_binding() -> None:
    client = TestClient(main_module.app)
    register_user(client, "memory-leaf-parent@example.com", "Memory Leaf Parent")
    project = create_project(client, "叶子父节点限制")

    ordinary_parent = client.post(
        "/api/v1/memory",
        json={"project_id": project["id"], "content": "用户今年18岁", "category": "个人.年龄", "type": "permanent"},
        headers=csrf_headers(client),
    )
    assert ordinary_parent.status_code == 200

    create_under_ordinary = client.post(
        "/api/v1/memory",
        json={
            "project_id": project["id"],
            "content": "用户在读大学",
            "category": "教育.学校",
            "type": "permanent",
            "parent_memory_id": ordinary_parent.json()["id"],
        },
        headers=csrf_headers(client),
    )
    assert create_under_ordinary.status_code == 400
    assert create_under_ordinary.json()["error"]["code"] == "bad_request"

    child = client.post(
        "/api/v1/memory",
        json={"project_id": project["id"], "content": "用户来自中国", "category": "个人.籍贯", "type": "permanent"},
        headers=csrf_headers(client),
    )
    assert child.status_code == 200

    rebind = client.patch(
        f"/api/v1/memory/{child.json()['id']}",
        json={"parent_memory_id": ordinary_parent.json()["id"]},
        headers=csrf_headers(client),
    )
    assert rebind.status_code == 400
    assert rebind.json()["error"]["code"] == "bad_request"


def test_category_tree_sync_drops_legacy_ordinary_memory_parenting() -> None:
    client = TestClient(main_module.app)
    user_info = register_user(client, "memory-legacy-leaf@example.com", "Legacy Leaf")
    workspace_id = user_info["workspace"]["id"]
    project = create_project(client, "旧普通父节点")

    with SessionLocal() as db:
        project_row = db.get(Project, project["id"])
        assert project_row is not None
        root_memory, _ = ensure_project_assistant_root(db, project_row, reparent_orphans=False)
        parent = Memory(
            workspace_id=workspace_id,
            project_id=project["id"],
            content="我今年18岁。",
            category="个人.年龄",
            type="permanent",
            parent_memory_id=root_memory.id,
            metadata_json={"memory_kind": "profile"},
        )
        child = Memory(
            workspace_id=workspace_id,
            project_id=project["id"],
            content="我来自中国。",
            category="个人.籍贯",
            type="permanent",
            parent_memory_id=None,
            metadata_json={},
        )
        db.add_all([parent, child])
        db.flush()
        child.parent_memory_id = parent.id
        child.metadata_json = memory_metadata_service.set_manual_parent_binding({}, parent_memory_id=parent.id)
        db.commit()
        child_id = child.id
        root_id = root_memory.id

        summary = memory_category_tree_service.ensure_project_category_tree(
            db,
            workspace_id=workspace_id,
            project_id=project["id"],
        )
        db.commit()

        repaired_child = db.get(Memory, child_id)
        assert repaired_child is not None
        assert repaired_child.parent_memory_id == root_id
        assert repaired_child.metadata_json.get("parent_binding") == "auto"
        assert repaired_child.metadata_json.get("manual_parent_id") is None
        assert summary.reparented_nodes >= 1


def test_memory_create_rejects_legacy_category_and_summary_primary_nodes() -> None:
    client = TestClient(main_module.app)
    register_user(client, "memory-legacy-create@example.com", "Legacy Create")
    project = create_project(client, "旧节点创建限制")

    category_path_response = client.post(
        "/api/v1/memory",
        json={
            "project_id": project["id"],
            "content": "旧分类路径节点",
            "category": "数学.几何学",
            "metadata_json": {"concept_source": "category_path"},
        },
        headers=csrf_headers(client),
    )
    assert category_path_response.status_code == 400
    assert "legacy derived view" in category_path_response.json()["error"]["message"]

    summary_response = client.post(
        "/api/v1/memory",
        json={
            "project_id": project["id"],
            "content": "旧摘要节点",
            "category": "数学.几何学",
            "metadata_json": {"memory_kind": "summary"},
        },
        headers=csrf_headers(client),
    )
    assert summary_response.status_code == 400
    assert "derived views" in summary_response.json()["error"]["message"]


def test_memory_update_rejects_manual_parent_cycles() -> None:
    client = TestClient(main_module.app)
    register_user(client, "memory-parent-cycle@example.com", "Memory Parent Cycle")
    project = create_project(client, "父节点环路项目")

    parent = client.post(
        "/api/v1/memory",
        json={
            "project_id": project["id"],
            "content": "父节点概念",
            "category": "身份.姓名",
            "type": "permanent",
            "node_type": "concept",
        },
        headers=csrf_headers(client),
    )
    assert parent.status_code == 200

    child = client.post(
        "/api/v1/memory",
        json={"project_id": project["id"], "content": "子节点", "category": "身份.昵称", "type": "permanent"},
        headers=csrf_headers(client),
    )
    assert child.status_code == 200

    bind_child = client.patch(
        f"/api/v1/memory/{child.json()['id']}",
        json={"parent_memory_id": parent.json()["id"]},
        headers=csrf_headers(client),
    )
    assert bind_child.status_code == 200

    cycle_attempt = client.patch(
        f"/api/v1/memory/{parent.json()['id']}",
        json={"parent_memory_id": child.json()["id"]},
        headers=csrf_headers(client),
    )
    assert cycle_attempt.status_code == 400
    assert cycle_attempt.json()["error"]["code"] == "bad_request"


def test_memory_graph_backfills_legacy_project_root() -> None:
    client = TestClient(main_module.app)
    user_info = register_user(client, "memory-legacy@example.com", "Memory Legacy")
    workspace_id = user_info["workspace"]["id"]

    with SessionLocal() as db:
        project = Project(workspace_id=workspace_id, name="Legacy Assistant", description="demo")
        db.add(project)
        db.commit()
        db.refresh(project)

        orphan = Memory(
            workspace_id=workspace_id,
            project_id=project.id,
            content="历史记忆事实",
            category="事实",
            type="permanent",
            parent_memory_id=None,
            metadata_json={},
        )
        db.add(orphan)
        db.commit()
        db.refresh(orphan)
        project_id = project.id
        orphan_id = orphan.id

    graph = client.get(f"/api/v1/memory?project_id={project_id}")
    assert graph.status_code == 200
    body = graph.json()

    root = next(
        node
        for node in body["nodes"]
        if node.get("metadata_json", {}).get("node_kind") == "assistant-root"
    )
    orphan = next(node for node in body["nodes"] if node["id"] == orphan_id)

    assert root["content"] == "Legacy Assistant"
    assert orphan["parent_memory_id"] == root["id"]

    with SessionLocal() as db:
        project = db.get(Project, project_id)
        assert project is not None
        assert project.assistant_root_memory_id == root["id"]


def test_temporary_memory_requires_conversation_and_graph_includes_file_nodes() -> None:
    client = TestClient(main_module.app)
    register_user(client, "memory-files@example.com", "Memory Files")
    project = create_project(client, "Memory Files Project")
    dataset = create_dataset(client, project["id"], "Memory Files Dataset")
    data_item_id = upload_item(client, dataset["id"], "attachment.jpg")

    missing_conversation = client.post(
        "/api/v1/memory",
        json={
            "project_id": project["id"],
            "content": "临时记忆缺少对话",
            "type": "temporary",
        },
        headers=csrf_headers(client),
    )
    assert missing_conversation.status_code == 400
    assert missing_conversation.json()["error"]["code"] == "bad_request"

    memory = client.post(
        "/api/v1/memory",
        json={
            "project_id": project["id"],
            "content": "知识库文件",
            "category": "资料",
            "type": "permanent",
        },
        headers=csrf_headers(client),
    )
    assert memory.status_code == 200

    with SessionLocal() as db:
        db.add(MemoryFile(memory_id=memory.json()["id"], data_item_id=data_item_id))
        db.commit()

    graph = client.get(f"/api/v1/memory?project_id={project['id']}")
    assert graph.status_code == 200
    body = graph.json()

    file_node = next(node for node in body["nodes"] if node["category"] == "file")
    assert file_node["id"].startswith("file:")
    assert file_node["parent_memory_id"] == memory.json()["id"]
    assert file_node["metadata_json"]["filename"] == "attachment.jpg"
    assert file_node["metadata_json"]["memory_id"] == memory.json()["id"]

    file_edge = next(edge for edge in body["edges"] if edge["edge_type"] == "file")
    assert file_edge["source_memory_id"] == memory.json()["id"]
    assert file_edge["target_memory_id"] == file_node["id"]


def test_memory_graph_include_temporary_returns_visible_project_temporary_memories() -> None:
    client = TestClient(main_module.app)
    register_user(client, "memory-include-temp@example.com", "Memory Include Temp")
    project = create_project(client, "Include Temp Project")
    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Include Temp Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200
    conversation_id = conversation.json()["id"]

    temp_memory = client.post(
        "/api/v1/memory",
        json={
            "project_id": project["id"],
            "content": "用户喜欢乌龙茶。",
            "category": "饮食.偏好",
            "type": "temporary",
            "source_conversation_id": conversation_id,
        },
        headers=csrf_headers(client),
    )
    assert temp_memory.status_code == 200

    graph_without_temp = client.get(f"/api/v1/memory?project_id={project['id']}")
    assert graph_without_temp.status_code == 200
    assert all(node["id"] != temp_memory.json()["id"] for node in graph_without_temp.json()["nodes"])

    graph_with_temp = client.get(f"/api/v1/memory?project_id={project['id']}&include_temporary=true")
    assert graph_with_temp.status_code == 200
    temp_node = next(node for node in graph_with_temp.json()["nodes"] if node["id"] == temp_memory.json()["id"])
    assert temp_node["type"] == "temporary"
    assert temp_node["source_conversation_id"] == conversation_id


def test_temporary_memory_is_hidden_from_other_workspace_members() -> None:
    owner = TestClient(main_module.app)
    owner_info = register_user(owner, "memory-owner@example.com", "Memory Owner")
    owner_workspace_id = owner_info["workspace"]["id"]
    project = create_project(owner, "Private Memory Project")
    conversation = owner.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Private Thread"},
        headers=csrf_headers(owner),
    )
    assert conversation.status_code == 200
    conversation_id = conversation.json()["id"]

    temp_memory = owner.post(
        "/api/v1/memory",
        json={
            "project_id": project["id"],
            "content": "私人临时记忆-不要泄露",
            "category": "测试",
            "type": "temporary",
            "source_conversation_id": conversation_id,
        },
        headers=csrf_headers(owner),
    )
    assert temp_memory.status_code == 200
    temp_memory_id = temp_memory.json()["id"]

    viewer = TestClient(main_module.app)
    register_user(viewer, "memory-viewer@example.com", "Memory Viewer")
    add_workspace_membership(owner_workspace_id, "memory-viewer@example.com", "viewer")

    viewer_detail = viewer.get(
        f"/api/v1/memory/{temp_memory_id}",
        headers={"x-workspace-id": owner_workspace_id},
    )
    assert viewer_detail.status_code == 404

    viewer_graph = viewer.get(
        f"/api/v1/memory?project_id={project['id']}&conversation_id={conversation_id}",
        headers={"x-workspace-id": owner_workspace_id},
    )
    assert viewer_graph.status_code == 404

    viewer_search = viewer.post(
        "/api/v1/memory/search",
        json={"project_id": project["id"], "query": "私人临时记忆-不要泄露", "top_k": 5},
        headers=csrf_headers(viewer, owner_workspace_id),
    )
    assert viewer_search.status_code == 200
    assert viewer_search.json() == []

    viewer_stream = viewer.get(
        f"/api/v1/chat/conversations/{conversation_id}/memory-stream",
        headers={"x-workspace-id": owner_workspace_id},
    )
    assert viewer_stream.status_code == 404

    viewer_write = viewer.post(
        "/api/v1/memory",
        json={
            "project_id": project["id"],
            "content": "viewer cannot create memory",
            "type": "permanent",
        },
        headers=csrf_headers(viewer, owner_workspace_id),
    )
    assert viewer_write.status_code == 403


def test_memory_file_attach_and_detach_refreshes_detail() -> None:
    client = TestClient(main_module.app)
    register_user(client, "memory-attach@example.com", "Memory Attach")
    project = create_project(client, "Attach Project")
    dataset = create_dataset(client, project["id"], "Attach Dataset")
    data_item_id = upload_item(client, dataset["id"], "attach.pdf")
    with SessionLocal() as db:
        data_item = db.get(DataItem, data_item_id)
        assert data_item is not None
        data_item.meta_json = {**(data_item.meta_json or {}), "upload_status": "completed"}
        db.commit()

    memory = client.post(
        "/api/v1/memory",
        json={"project_id": project["id"], "content": "需要关联资料"},
        headers=csrf_headers(client),
    )
    assert memory.status_code == 200
    memory_id = memory.json()["id"]

    available = client.get(f"/api/v1/memory/{memory_id}/available-files")
    assert available.status_code == 200
    assert any(item["id"] == data_item_id for item in available.json())

    attached = client.post(
        f"/api/v1/memory/{memory_id}/files",
        json={"data_item_id": data_item_id},
        headers=csrf_headers(client),
    )
    assert attached.status_code == 200
    memory_file_id = attached.json()["id"]

    detail = client.get(f"/api/v1/memory/{memory_id}")
    assert detail.status_code == 200
    assert detail.json()["files"][0]["data_item_id"] == data_item_id
    assert any(
        evidence["source_type"] == "file" and evidence["data_item_id"] == data_item_id
        for evidence in detail.json()["evidences"]
    )

    deleted = client.delete(
        f"/api/v1/memory/files/{memory_file_id}",
        headers=csrf_headers(client),
    )
    assert deleted.status_code == 204

    refreshed = client.get(f"/api/v1/memory/{memory_id}")
    assert refreshed.status_code == 200
    assert refreshed.json()["files"] == []


def test_sync_memory_links_for_data_item_creates_only_missing_links(monkeypatch) -> None:
    client = TestClient(main_module.app)
    user_info = register_user(client, "memory-link@example.com", "Memory Link")
    workspace_id = user_info["workspace"]["id"]
    project = create_project(client, "Memory Link Project")
    dataset = create_dataset(client, project["id"], "Memory Link Dataset")
    data_item_id = upload_item(client, dataset["id"], "memory-link.txt")

    memory_a = client.post(
        "/api/v1/memory",
        json={"project_id": project["id"], "content": "心理学"},
        headers=csrf_headers(client),
    )
    assert memory_a.status_code == 200
    memory_b = client.post(
        "/api/v1/memory",
        json={"project_id": project["id"], "content": "医生"},
        headers=csrf_headers(client),
    )
    assert memory_b.status_code == 200

    with SessionLocal() as db:
        db.add(MemoryFile(memory_id=memory_a.json()["id"], data_item_id=data_item_id))
        db.commit()

    monkeypatch.setattr(
        memory_file_context_service,
        "find_related_memories_for_data_item",
        lambda *args, **kwargs: [
            {"memory_id": memory_a.json()["id"], "score": 0.95},
            {"memory_id": memory_b.json()["id"], "score": 0.91},
        ],
    )

    with SessionLocal() as db:
        created = memory_file_context_service.sync_memory_links_for_data_item(
            db,
            workspace_id=workspace_id,
            project_id=project["id"],
            data_item_id=data_item_id,
        )
        assert created == [memory_b.json()["id"]]

        links = {
            (memory_id, item_id)
            for memory_id, item_id in db.query(MemoryFile.memory_id, MemoryFile.data_item_id)
            .filter(MemoryFile.data_item_id == data_item_id)
            .all()
        }
        assert links == {
            (memory_a.json()["id"], data_item_id),
            (memory_b.json()["id"], data_item_id),
        }


def test_create_memory_triggers_auto_linking_for_existing_files(monkeypatch) -> None:
    client = TestClient(main_module.app)
    register_user(client, "memory-auto@example.com", "Memory Auto")
    project = create_project(client, "Memory Auto Project")

    calls: dict[str, str] = {}

    async def fake_embed_and_store(*args, **kwargs) -> str:
        calls["embedded_memory_id"] = kwargs["memory_id"]
        return "embedding-1"

    def fake_sync_data_item_links_for_memory(db, *, memory, **kwargs) -> list[str]:
        calls["linked_memory_id"] = memory.id
        return ["data-item-1"]

    monkeypatch.setattr(memory_router.settings, "dashscope_api_key", "test-key")
    monkeypatch.setattr(memory_router, "embed_and_store", fake_embed_and_store)
    monkeypatch.setattr(memory_router, "sync_data_item_links_for_memory", fake_sync_data_item_links_for_memory)

    created = client.post(
        "/api/v1/memory",
        json={"project_id": project["id"], "content": "与知识库自动关联"},
        headers=csrf_headers(client),
    )
    assert created.status_code == 200
    assert calls["embedded_memory_id"] == created.json()["id"]
    assert calls["linked_memory_id"] == created.json()["id"]


def test_memory_patch_does_not_allow_direct_type_mutation() -> None:
    client = TestClient(main_module.app)
    register_user(client, "memory-type@example.com", "Memory Type")
    project = create_project(client, "Memory Type Project")
    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Memory Type Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200

    created = client.post(
        "/api/v1/memory",
        json={
            "project_id": project["id"],
            "content": "临时记忆",
            "category": "测试",
            "type": "temporary",
            "source_conversation_id": conversation.json()["id"],
        },
        headers=csrf_headers(client),
    )
    assert created.status_code == 200

    updated = client.patch(
        f"/api/v1/memory/{created.json()['id']}",
        json={"type": "permanent", "content": "仍然是临时记忆"},
        headers=csrf_headers(client),
    )
    assert updated.status_code == 200
    assert updated.json()["type"] == "temporary"


def test_memory_edge_rejects_cross_project_links() -> None:
    client = TestClient(main_module.app)
    register_user(client, "memory-edge@example.com", "Memory Edge")
    project_a = create_project(client, "Project A")
    project_b = create_project(client, "Project B")

    first = client.post(
        "/api/v1/memory",
        json={"project_id": project_a["id"], "content": "A", "type": "permanent"},
        headers=csrf_headers(client),
    )
    second = client.post(
        "/api/v1/memory",
        json={"project_id": project_b["id"], "content": "B", "type": "permanent"},
        headers=csrf_headers(client),
    )
    assert first.status_code == 200
    assert second.status_code == 200

    resp = client.post(
        "/api/v1/memory/edges",
        json={
            "source_memory_id": first.json()["id"],
            "target_memory_id": second.json()["id"],
        },
        headers=csrf_headers(client),
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "bad_request"


def test_delete_conversation_returns_204_and_removes_temporary_memories() -> None:
    client = TestClient(main_module.app)
    register_user(client, "conversation-delete@example.com", "Conversation Delete")
    project = create_project(client, "Conversation Project")
    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200
    conversation_id = conversation.json()["id"]

    memory = client.post(
        "/api/v1/memory",
        json={
            "project_id": project["id"],
            "content": "对话里的临时记忆",
            "type": "temporary",
            "source_conversation_id": conversation_id,
        },
        headers=csrf_headers(client),
    )
    assert memory.status_code == 200

    deleted = client.delete(
        f"/api/v1/chat/conversations/{conversation_id}",
        headers=csrf_headers(client),
    )
    assert deleted.status_code == 204
    assert deleted.content == b""

    detail = client.get(f"/api/v1/memory/{memory.json()['id']}")
    assert detail.status_code == 404


def test_send_message_rate_limit_triggers_after_ten_requests(monkeypatch) -> None:
    monkeypatch.setattr(chat_router.settings, "dashscope_api_key", "test-key")
    async def fake_orchestrate_inference(*args, **kwargs):
        return "mocked reply"
    monkeypatch.setattr(chat_router, "orchestrate_inference", fake_orchestrate_inference)
    client = TestClient(main_module.app)
    register_user(client, "chat-limit@example.com", "Chat Limit")
    project = create_project(client, "Chat Limit Project")
    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200
    conversation_id = conversation.json()["id"]

    for index in range(10):
        resp = client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"content": f"message-{index}"},
            headers=csrf_headers(client),
        )
        assert resp.status_code == 200

    limited = client.post(
        f"/api/v1/chat/conversations/{conversation_id}/messages",
        json={"content": "message-over-limit"},
        headers=csrf_headers(client),
    )
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "rate_limited"


def test_model_catalog_detail_exposes_modalities_and_support_flags() -> None:
    client = TestClient(main_module.app)
    register_user(client, "catalog@example.com", "Catalog")

    detail = client.get("/api/v1/models/catalog/qwen3.5-plus")
    assert detail.status_code == 200

    payload = detail.json()
    assert payload["provider_display"] == "千问 · 阿里云"
    assert payload["canonical_model_id"] == "qwen3.5-plus"
    assert payload["model_id"] == "qwen3.5-plus"
    assert payload["id"] == "00000000-0000-0000-0000-000000000002"
    assert payload["official_category"] == "文本生成"
    assert payload["official_category_key"] == "text_generation"
    assert payload["input_modalities"] == ["text", "image", "video"]
    assert payload["output_modalities"] == ["text"]
    assert payload["supports_function_calling"] is True
    assert payload["supports_web_search"] is True
    assert payload["supports_structured_output"] is False
    assert payload["supports_cache"] is False
    assert payload["supported_tools"] == [
        "code_interpreter",
        "file_search",
        "function_calling",
        "image_search",
        "mcp",
        "web_extractor",
        "web_search",
        "web_search_image",
    ]
    assert payload["price_unit"] == "tokens"


def test_model_catalog_list_includes_qwen3_vl_plus_and_hides_qwen3_plus() -> None:
    client = TestClient(main_module.app)
    register_user(client, "catalog-list@example.com", "Catalog List")

    resp = client.get("/api/v1/models/catalog")
    assert resp.status_code == 200

    model_ids = {item["model_id"] for item in resp.json()}
    assert "qwen3-vl-plus" in model_ids
    assert "qwen3-plus" not in model_ids


def test_model_catalog_detail_supports_legacy_aliases() -> None:
    client = TestClient(main_module.app)
    register_user(client, "catalog-alias@example.com", "Catalog Alias")

    legacy_plus = client.get("/api/v1/models/catalog/qwen3-plus")
    assert legacy_plus.status_code == 200
    assert legacy_plus.json()["model_id"] == "qwen3.5-plus"
    assert legacy_plus.json()["canonical_model_id"] == "qwen3.5-plus"

    legacy_vl = client.get("/api/v1/models/catalog/qwen3-vl-plus")
    assert legacy_vl.status_code == 200
    assert legacy_vl.json()["model_id"] in {"qwen3-vl-plus", "qwen-vl-plus"}


def test_model_catalog_discover_view_returns_official_taxonomy_and_qwen_items() -> None:
    client = TestClient(main_module.app)
    register_user(client, "catalog-discover@example.com", "Catalog Discover")

    resp = client.get("/api/v1/models/catalog?view=discover")
    assert resp.status_code == 200

    payload = resp.json()
    assert "taxonomy" in payload
    assert "items" in payload
    assert any(item["key"] == "text_generation" for item in payload["taxonomy"])

    model_ids = {item["model_id"] for item in payload["items"]}
    assert "qwen3.5-plus" in model_ids
    assert "deepseek-v3.2" not in model_ids


def test_model_catalog_separates_chat_and_realtime_slots() -> None:
    client = TestClient(main_module.app)
    register_user(client, "catalog-slots@example.com", "Catalog Slots")

    llm = client.get("/api/v1/models/catalog?category=llm")
    assert llm.status_code == 200
    llm_ids = {item["model_id"] for item in llm.json()}
    assert "qwen3.5-plus" in llm_ids
    assert "qwen3-omni-flash-realtime" not in llm_ids

    realtime = client.get("/api/v1/models/catalog?category=realtime")
    assert realtime.status_code == 200
    realtime_items = realtime.json()
    realtime_ids = {item["model_id"] for item in realtime_items}
    assert "qwen3-omni-flash-realtime" in realtime_ids
    assert all(item["category"] == "realtime" for item in realtime_items)

    realtime_asr = client.get("/api/v1/models/catalog?category=realtime_asr")
    assert realtime_asr.status_code == 200
    realtime_asr_items = realtime_asr.json()
    assert "qwen3-asr-flash-realtime" in {item["model_id"] for item in realtime_asr_items}
    assert all(item["category"] == "realtime_asr" for item in realtime_asr_items)

    realtime_tts = client.get("/api/v1/models/catalog?category=realtime_tts")
    assert realtime_tts.status_code == 200
    realtime_tts_items = realtime_tts.json()
    assert "qwen3-tts-flash-realtime" in {item["model_id"] for item in realtime_tts_items}
    assert all(item["category"] == "realtime_tts" for item in realtime_tts_items)


def test_model_catalog_detail_supports_db_id_lookup_and_preserves_runtime_fields() -> None:
    client = TestClient(main_module.app)
    register_user(client, "catalog-db-id@example.com", "Catalog DB ID")

    detail = client.get("/api/v1/models/catalog/00000000-0000-0000-0000-000000000002")
    assert detail.status_code == 200

    payload = detail.json()
    assert payload["id"] == "00000000-0000-0000-0000-000000000002"
    assert payload["model_id"] == "qwen3.5-plus"
    assert payload["canonical_model_id"] == "qwen3.5-plus"
    assert payload["input_price"] == 0.0008
    assert payload["output_price"] == 0.0048
    assert payload["context_window"] == 1000000


def test_model_catalog_unknown_category_returns_empty_list() -> None:
    client = TestClient(main_module.app)
    register_user(client, "catalog-empty-category@example.com", "Catalog Empty Category")

    resp = client.get("/api/v1/models/catalog?category=unknown-slot")
    assert resp.status_code == 200
    assert resp.json() == []


def test_send_message_maps_upstream_failures_to_502_and_503(monkeypatch) -> None:
    client = TestClient(main_module.app)
    register_user(client, "chat-errors@example.com", "Chat Errors")
    project = create_project(client, "Chat Errors Project")
    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200
    conversation_id = conversation.json()["id"]

    monkeypatch.setattr(chat_router.settings, "dashscope_api_key", "test-key")

    async def fail_502(*args, **kwargs):
        raise chat_router.UpstreamServiceError("Model API unavailable")

    monkeypatch.setattr(chat_router, "orchestrate_inference", fail_502)
    bad_gateway = client.post(
        f"/api/v1/chat/conversations/{conversation_id}/messages",
        json={"content": "hello"},
        headers=csrf_headers(client),
    )
    assert bad_gateway.status_code == 502
    assert bad_gateway.json()["error"]["code"] == "model_api_unavailable"
    assert bad_gateway.json()["error"]["details"]["retry_after"] == 5

    async def fail_503(*args, **kwargs):
        raise chat_router.InferenceTimeoutError("Inference timeout")

    monkeypatch.setattr(chat_router, "orchestrate_inference", fail_503)
    timeout = client.post(
        f"/api/v1/chat/conversations/{conversation_id}/messages",
        json={"content": "hello again"},
        headers=csrf_headers(client),
    )
    assert timeout.status_code == 503
    assert timeout.json()["error"]["code"] == "inference_timeout"


def test_authenticated_presign_endpoints_are_rate_limited(monkeypatch) -> None:
    client = TestClient(main_module.app)
    register_user(client, "presign-limit@example.com", "Presign Limit")
    project = create_project(client, "Presign Project")
    dataset = create_dataset(client, project["id"], "Presign Dataset")

    monkeypatch.setattr(config_module.settings, "upload_presign_rate_limit_max", 2)
    monkeypatch.setattr(config_module.settings, "model_artifact_presign_rate_limit_max", 2)

    for index in range(2):
        resp = client.post(
            "/api/v1/uploads/presign",
            json={
                "dataset_id": dataset["id"],
                "filename": f"upload-{index}.jpg",
                "media_type": "image/jpeg",
                "size_bytes": 16,
            },
            headers=csrf_headers(client),
        )
        assert resp.status_code == 200

    upload_limited = client.post(
        "/api/v1/uploads/presign",
        json={
            "dataset_id": dataset["id"],
            "filename": "upload-over-limit.jpg",
            "media_type": "image/jpeg",
            "size_bytes": 16,
        },
        headers=csrf_headers(client),
    )
    assert upload_limited.status_code == 429
    assert upload_limited.json()["error"]["code"] == "rate_limited"

    model_resp = client.post(
        "/api/v1/models",
        json={"project_id": project["id"], "name": "Artifact Model", "task_type": "general"},
        headers=csrf_headers(client),
    )
    assert model_resp.status_code == 200
    model_id = model_resp.json()["model"]["id"]

    for index in range(2):
        resp = client.post(
            f"/api/v1/models/{model_id}/artifact-uploads/presign",
            json={
                "filename": f"artifact-{index}.json",
                "media_type": "application/json",
                "size_bytes": 16,
            },
            headers=csrf_headers(client),
        )
        assert resp.status_code == 200

    artifact_limited = client.post(
        f"/api/v1/models/{model_id}/artifact-uploads/presign",
        json={
            "filename": "artifact-over-limit.json",
            "media_type": "application/json",
            "size_bytes": 16,
        },
        headers=csrf_headers(client),
    )
    assert artifact_limited.status_code == 429
    assert artifact_limited.json()["error"]["code"] == "rate_limited"


def test_memory_stream_endpoint_is_rate_limited(monkeypatch) -> None:
    client = TestClient(main_module.app)
    register_user(client, "memory-stream@example.com", "Memory Stream")
    project = create_project(client, "Memory Stream Project")

    monkeypatch.setattr(config_module.settings, "sse_rate_limit_max", 0)

    blocked = client.get(f"/api/v1/memory/{project['id']}/stream")
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"


def test_extract_live_message_metadata_filters_valid_fields() -> None:
    message = Message(
        conversation_id="conv-test",
        role="assistant",
        content="先回答，再补记忆。",
        metadata_json={
            "extracted_facts": [
                {
                    "fact": "用户对拓扑学有持续兴趣",
                    "category": "学习.兴趣",
                    "importance": 0.93,
                    "status": "permanent",
                    "triage_action": "create",
                    "triage_reason": "长期稳定偏好",
                    "target_memory_id": "mem-123",
                },
                {
                    "fact": "   ",
                    "category": "无效",
                    "importance": 0.1,
                },
            ],
            "memories_extracted": "记录了用户的长期兴趣。",
            "memory_extraction_status": "completed",
            "memory_extraction_attempts": 2,
            "ignored": {"nested": True},
        },
    )

    payload = chat_router._extract_live_message_metadata(message)

    assert payload == {
        "extracted_facts": [
            {
                "fact": "用户对拓扑学有持续兴趣",
                "category": "学习.兴趣",
                "importance": 0.93,
                "status": "permanent",
                "triage_action": "create",
                "triage_reason": "长期稳定偏好",
                "target_memory_id": "mem-123",
            }
        ],
        "memories_extracted": "记录了用户的长期兴趣。",
        "memory_extraction_status": "completed",
        "memory_extraction_attempts": 2,
    }


def test_trigger_memory_extraction_runs_inline_thread_in_local_env(monkeypatch) -> None:
    call_args: list[tuple] = []
    called = threading.Event()

    original_env = config_module.settings.env
    original_api_key = config_module.settings.dashscope_api_key

    monkeypatch.setattr(config_module.settings, "env", "local")
    monkeypatch.setattr(config_module.settings, "dashscope_api_key", "test-key")

    def fake_execute_memory_extraction_job(*args):
        call_args.append(args)
        called.set()
        return True

    class FakeExtractTask:
        def delay(self, *args):  # pragma: no cover - should not be reached
            raise AssertionError("delay should not be used in local env")

    monkeypatch.setattr(worker_tasks, "execute_memory_extraction_job", fake_execute_memory_extraction_job)
    monkeypatch.setattr(worker_tasks, "extract_memories", FakeExtractTask())

    chat_router._trigger_memory_extraction(
        "ws_local",
        "proj_local",
        "conv_local",
        "user text",
        "assistant text",
        assistant_message_id="msg_local",
    )

    assert called.wait(timeout=2)
    assert call_args == [
        (
            "ws_local",
            "proj_local",
            "conv_local",
            "user text",
            "assistant text",
            "msg_local",
        )
    ]

    monkeypatch.setattr(config_module.settings, "env", original_env)
    monkeypatch.setattr(config_module.settings, "dashscope_api_key", original_api_key)


def test_execute_memory_extraction_job_retries_until_success(monkeypatch) -> None:
    attempts: list[int] = []

    def fake_run_memory_extraction(*args, attempt_index=1, **kwargs):
        del args, kwargs
        attempts.append(attempt_index)
        return attempt_index >= 2

    monkeypatch.setattr(worker_tasks, "run_memory_extraction", fake_run_memory_extraction)
    monkeypatch.setattr(worker_tasks.time, "sleep", lambda *_args, **_kwargs: None)

    succeeded = worker_tasks.execute_memory_extraction_job(
        "ws_retry",
        "proj_retry",
        "conv_retry",
        "user text",
        "assistant text",
        "msg_retry",
        max_attempts=3,
    )

    assert succeeded is True
    assert attempts == [1, 2]


def test_execute_memory_extraction_job_marks_failed_after_max_attempts(monkeypatch) -> None:
    attempts: list[int] = []
    failure_payload: dict[str, object] = {}

    def fake_run_memory_extraction(*args, attempt_index=1, **kwargs):
        del args, kwargs
        attempts.append(attempt_index)
        return False

    def fake_persist_failure(message_id: str | None, *, attempts: int, error_message: str) -> None:
        failure_payload["message_id"] = message_id
        failure_payload["attempts"] = attempts
        failure_payload["error_message"] = error_message

    monkeypatch.setattr(worker_tasks, "run_memory_extraction", fake_run_memory_extraction)
    monkeypatch.setattr(worker_tasks, "_persist_memory_extraction_failure", fake_persist_failure)
    monkeypatch.setattr(worker_tasks.time, "sleep", lambda *_args, **_kwargs: None)

    succeeded = worker_tasks.execute_memory_extraction_job(
        "ws_retry",
        "proj_retry",
        "conv_retry",
        "user text",
        "assistant text",
        "msg_retry",
        max_attempts=3,
    )

    assert succeeded is False
    assert attempts == [1, 2, 3]
    assert failure_payload == {
        "message_id": "msg_retry",
        "attempts": 3,
        "error_message": worker_tasks.MEMORY_EXTRACTION_FAILURE_SUMMARY,
    }


def test_extract_memories_persists_triage_results_for_frontend(monkeypatch) -> None:
    import app.services.dashscope_client as dashscope_client_module
    import app.services.embedding as embedding_service

    client = TestClient(main_module.app)
    user_info = register_user(client, "memory-triage@example.com", "Memory Triage")
    workspace_id = user_info["workspace"]["id"]
    project = create_project(client, "Memory Triage Project")
    conversation_id = create_conversation_record(
        workspace_id,
        project["id"],
        user_info["user"]["id"],
        "Memory Triage Conversation",
    )

    with SessionLocal() as db:
        existing_memory = Memory(
            workspace_id=workspace_id,
            project_id=project["id"],
            content="用户在帝国理工大学学习物理本科。",
            category="教育.身份",
            type="permanent",
            metadata_json={},
        )
        db.add(existing_memory)
        db.add(
            Message(
                conversation_id=conversation_id,
                role="assistant",
                content="这条消息稍后会被回写记忆元数据。",
                metadata_json={},
            )
        )
        db.commit()
        existing_memory_id = existing_memory.id

    async def fake_extract_completion(*args, **kwargs):
        return json.dumps(
            [
                {
                    "fact": "用户是帝国理工大学学习物理本科的中国留学生",
                    "category": "教育.身份",
                    "importance": 0.95,
                }
            ],
            ensure_ascii=False,
        )

    async def fake_find_duplicate(*args, **kwargs):
        return None, [0.11, 0.22, 0.33]

    async def fake_find_related(*args, **kwargs):
        return [
            {
                "memory_id": existing_memory_id,
                "category": "教育.身份",
                "content": "用户在帝国理工大学学习物理本科。",
            }
        ]

    async def fake_triage(*args, **kwargs):
        return {
            "action": "merge",
            "target_memory_id": existing_memory_id,
            "merged_content": "用户是帝国理工大学学习物理本科的中国留学生。",
            "reason": "新事实是对同一身份信息的更完整表述",
        }

    async def fake_embed_and_store(*args, **kwargs):
        return None

    monkeypatch.setattr(dashscope_client_module, "chat_completion", fake_extract_completion)
    monkeypatch.setattr(embedding_service, "find_duplicate_memory_with_vector", fake_find_duplicate)
    monkeypatch.setattr(embedding_service, "find_related_memories", fake_find_related)
    monkeypatch.setattr(embedding_service, "embed_and_store", fake_embed_and_store)
    monkeypatch.setattr(worker_tasks, "triage_memory", fake_triage)
    monkeypatch.setattr(worker_tasks, "compact_project_memories_task", lambda *args, **kwargs: None)

    worker_tasks.extract_memories(
        workspace_id,
        project["id"],
        conversation_id,
        "你能记下我是帝国理工大学学习物理本科的中国留学生吗？",
        "已记下，我后续会按这个背景来回答。",
    )

    with SessionLocal() as db:
        assistant_message = (
            db.query(Message)
            .filter(
                Message.conversation_id == conversation_id,
                Message.role == "assistant",
            )
            .order_by(Message.created_at.desc())
            .first()
        )
        assert assistant_message is not None
        metadata = assistant_message.metadata_json or {}
        extracted_facts = metadata.get("extracted_facts")
        assert isinstance(extracted_facts, list)
        assert extracted_facts[0]["fact"] == "用户是帝国理工大学学习物理本科的中国留学生"
        assert extracted_facts[0]["importance"] == 0.95
        assert extracted_facts[0]["status"] == "superseded"
        assert extracted_facts[0]["triage_action"] == "merge"
        assert extracted_facts[0]["triage_reason"] == "新事实是对同一身份信息的更完整表述"
        successor_id = extracted_facts[0]["target_memory_id"]
        assert successor_id != existing_memory_id
        assert extracted_facts[0]["supersedes_memory_id"] == existing_memory_id
        assert metadata["memories_extracted"] == "创建新版并替代旧事实 1 条"

        previous_memory = db.get(Memory, existing_memory_id)
        successor_memory = db.get(Memory, successor_id)
        assert previous_memory is not None
        assert successor_memory is not None
        assert previous_memory.content == "用户在帝国理工大学学习物理本科。"
        assert previous_memory.node_status == "superseded"
        assert successor_memory.content == "用户是帝国理工大学学习物理本科的中国留学生。"
        assert successor_memory.node_status == "active"
        assert successor_memory.lineage_key == previous_memory.lineage_key
        version_edge = (
            db.query(MemoryEdge)
            .filter(
                MemoryEdge.source_memory_id == successor_id,
                MemoryEdge.target_memory_id == existing_memory_id,
                MemoryEdge.edge_type == "supersedes",
            )
            .first()
        )
        assert version_edge is not None


def test_extract_memories_targets_explicit_assistant_message_id(monkeypatch) -> None:
    import app.services.dashscope_client as dashscope_client_module
    import app.services.embedding as embedding_service

    client = TestClient(main_module.app)
    user_info = register_user(client, "memory-target@example.com", "Memory Target")
    workspace_id = user_info["workspace"]["id"]
    project = create_project(client, "Memory Target Project")
    conversation_id = create_conversation_record(
        workspace_id,
        project["id"],
        user_info["user"]["id"],
        "Memory Target Conversation",
    )

    with SessionLocal() as db:
        first_assistant = Message(
            conversation_id=conversation_id,
            role="assistant",
            content="第一条 assistant",
            metadata_json={},
        )
        second_assistant = Message(
            conversation_id=conversation_id,
            role="assistant",
            content="第二条 assistant",
            metadata_json={},
        )
        db.add(first_assistant)
        db.add(second_assistant)
        db.commit()
        first_assistant_id = first_assistant.id
        second_assistant_id = second_assistant.id

    async def fake_extract_completion(*args, **kwargs):
        del args, kwargs
        return json.dumps(
            [
                {
                    "fact": "用户来自上海",
                    "category": "身份.背景",
                    "importance": 0.95,
                }
            ],
            ensure_ascii=False,
        )

    async def fake_find_duplicate(*args, **kwargs):
        del args, kwargs
        return None, [0.12, 0.34, 0.56]

    async def fake_find_related(*args, **kwargs):
        del args, kwargs
        return []

    async def fake_embed_and_store(*args, **kwargs):
        del args, kwargs
        return None

    async def fake_resolve_concept_parent(*args, **kwargs):
        del args, kwargs
        return None, False, None

    monkeypatch.setattr(dashscope_client_module, "chat_completion", fake_extract_completion)
    monkeypatch.setattr(embedding_service, "find_duplicate_memory_with_vector", fake_find_duplicate)
    monkeypatch.setattr(embedding_service, "find_related_memories", fake_find_related)
    monkeypatch.setattr(embedding_service, "embed_and_store", fake_embed_and_store)
    monkeypatch.setattr(worker_tasks, "_resolve_concept_parent", fake_resolve_concept_parent)
    monkeypatch.setattr(worker_tasks, "compact_project_memories_task", lambda *args, **kwargs: None)
    monkeypatch.setattr(worker_tasks, "repair_project_memory_graph_task", lambda *args, **kwargs: None)

    worker_tasks.extract_memories(
        workspace_id,
        project["id"],
        conversation_id,
        "请记住我来自上海",
        "已记住。",
        first_assistant_id,
    )

    with SessionLocal() as db:
        first_message = db.get(Message, first_assistant_id)
        second_message = db.get(Message, second_assistant_id)
        assert first_message is not None
        assert second_message is not None
        assert isinstance((first_message.metadata_json or {}).get("extracted_facts"), list)
        assert not (second_message.metadata_json or {}).get("extracted_facts")


def test_patch_active_fact_rejects_destructive_edit_and_supersede_route_versions_fact() -> None:
    client = TestClient(main_module.app)
    user_info = register_user(client, "memory-supersede@example.com", "Memory Supersede")
    workspace_id = user_info["workspace"]["id"]
    project = create_project(client, "Memory Supersede Project")

    memory = client.post(
        "/api/v1/memory",
        json={
            "project_id": project["id"],
            "content": "项目当前使用 REST API。",
            "category": "项目.接口",
        },
        headers=csrf_headers(client, workspace_id),
    )
    assert memory.status_code == 200
    memory_id = memory.json()["id"]

    patch_response = client.patch(
        f"/api/v1/memory/{memory_id}",
        json={"content": "项目当前使用 GraphQL API。"},
        headers=csrf_headers(client, workspace_id),
    )
    assert patch_response.status_code == 400

    supersede_response = client.post(
        f"/api/v1/memory/{memory_id}/supersede",
        json={
            "content": "项目当前使用 GraphQL API。",
            "category": "项目.接口",
            "reason": "manual_edit",
        },
        headers=csrf_headers(client, workspace_id),
    )
    assert supersede_response.status_code == 200
    successor = supersede_response.json()

    graph_response = client.get(
        "/api/v1/memory",
        params={"project_id": project["id"]},
        headers={"x-workspace-id": workspace_id},
    )
    assert graph_response.status_code == 200
    graph_node_ids = {node["id"] for node in graph_response.json()["nodes"]}
    assert successor["id"] in graph_node_ids
    assert memory_id not in graph_node_ids

    detail_response = client.get(
        f"/api/v1/memory/{successor['id']}",
        headers={"x-workspace-id": workspace_id},
    )
    assert detail_response.status_code == 200
    detail_body = detail_response.json()
    lineage_ids = {node["id"] for node in detail_body["lineage_nodes"]}
    assert memory_id in lineage_ids
    assert successor["id"] in lineage_ids
    assert any(edge["edge_type"] == "supersedes" for edge in detail_body["lineage_edges"])

    with SessionLocal() as db:
        previous = db.get(Memory, memory_id)
        current = db.get(Memory, successor["id"])
        assert previous is not None
        assert current is not None
        assert previous.node_status == "superseded"
        assert current.node_status == "active"
        assert previous.lineage_key == current.lineage_key


def test_build_memory_context_graph_first_dedupes_conflict_lineage_by_default() -> None:
    client = TestClient(main_module.app)
    user_info = register_user(client, "graph-first-conflict@example.com", "Graph First Conflict")
    workspace_id = user_info["workspace"]["id"]
    project = create_project(client, "Graph First Conflict Project")
    conversation_id = create_conversation_record(
        workspace_id,
        project["id"],
        user_info["user"]["id"],
        "Graph First Conflict Conversation",
    )

    with SessionLocal() as db:
        project_record = db.get(Project, project["id"])
        assert project_record is not None
        ensure_project_assistant_root(db, project_record, reparent_orphans=False)
        subject_memory, _ = ensure_project_user_subject(
            db,
            project_record,
            owner_user_id=user_info["user"]["id"],
        )
        lineage_key = "family-api-conflict"
        for content in ("项目当前使用 REST API。", "项目当前使用 GraphQL API。"):
            metadata = memory_metadata_service.normalize_memory_metadata(
                content=content,
                category="项目.接口",
                memory_type="permanent",
                metadata={
                    "node_type": "fact",
                    "node_status": "active",
                    "subject_memory_id": subject_memory.id,
                    "lineage_key": lineage_key,
                },
            )
            db.add(
                Memory(
                    workspace_id=workspace_id,
                    project_id=project["id"],
                    content=content,
                    category="项目.接口",
                    type="permanent",
                    node_type="fact",
                    parent_memory_id=subject_memory.id,
                    subject_memory_id=subject_memory.id,
                    node_status="active",
                    canonical_key=str(metadata.get("canonical_key") or "").strip() or None,
                    lineage_key=lineage_key,
                    metadata_json=metadata,
                )
            )
        db.commit()

    with SessionLocal() as db:
        context = asyncio.run(
            memory_context_service.build_memory_context(
                db,
                workspace_id=workspace_id,
                project_id=project["id"],
                conversation_id=conversation_id,
                user_message="这个项目现在用什么 API？",
                recent_messages=[],
                context_level="memory_only",
            )
        )

    fact_candidates = [
        candidate
        for candidate in context.selected_memories
        if candidate.memory.node_type == "fact" and candidate.memory.category == "项目.接口"
    ]
    assert len(fact_candidates) == 1
    assert context.retrieval_trace["graph_first"] is True
    assert context.retrieval_trace["has_conflict"] is True
    assert len(context.retrieval_trace["conflict_memory_ids"]) == 2
    assert len(context.retrieval_trace["active_fact_ids"]) == 1
    assert "项目当前使用 REST API。" not in context.system_prompt or "项目当前使用 GraphQL API。" not in context.system_prompt


def test_search_project_memories_for_tool_dedupes_same_lineage_by_default() -> None:
    client = TestClient(main_module.app)
    user_info = register_user(client, "tool-lineage-search@example.com", "Tool Lineage Search")
    workspace_id = user_info["workspace"]["id"]
    project = create_project(client, "Tool Lineage Search Project")
    conversation_id = create_conversation_record(
        workspace_id,
        project["id"],
        user_info["user"]["id"],
        "Tool Lineage Search Conversation",
    )

    with SessionLocal() as db:
        project_record = db.get(Project, project["id"])
        assert project_record is not None
        ensure_project_assistant_root(db, project_record, reparent_orphans=False)
        subject_memory, _ = ensure_project_user_subject(
            db,
            project_record,
            owner_user_id=user_info["user"]["id"],
        )
        lineage_key = "family-tool-search-api"
        created_ids: list[str] = []
        for content, confidence in (
            ("项目当前使用 REST API。", 0.45),
            ("项目当前使用 GraphQL API。", 0.85),
        ):
            metadata = memory_metadata_service.normalize_memory_metadata(
                content=content,
                category="项目.接口",
                memory_type="permanent",
                metadata={
                    "node_type": "fact",
                    "node_status": "active",
                    "subject_memory_id": subject_memory.id,
                    "lineage_key": lineage_key,
                    "source_confidence": confidence,
                },
            )
            memory = Memory(
                workspace_id=workspace_id,
                project_id=project["id"],
                content=content,
                category="项目.接口",
                type="permanent",
                node_type="fact",
                parent_memory_id=subject_memory.id,
                subject_memory_id=subject_memory.id,
                node_status="active",
                canonical_key=str(metadata.get("canonical_key") or "").strip() or None,
                lineage_key=lineage_key,
                metadata_json=metadata,
            )
            db.add(memory)
            db.flush()
            created_ids.append(memory.id)
        db.commit()

    async def fake_semantic_search(*args, **kwargs):
        return [
            {"memory_id": created_ids[0], "score": 0.88},
            {"memory_id": created_ids[1], "score": 0.91},
        ]

    with SessionLocal() as db:
        visible_results = asyncio.run(
            memory_context_service.search_project_memories_for_tool(
                db,
                workspace_id=workspace_id,
                project_id=project["id"],
                conversation_id=conversation_id,
                conversation_created_by=user_info["user"]["id"],
                query="这个项目现在用什么 API？",
                top_k=5,
                semantic_search_fn=fake_semantic_search,
            )
        )
        assert len(visible_results) == 1
        assert visible_results[0]["content"] == "项目当前使用 GraphQL API。"

        conflict_results = asyncio.run(
            memory_context_service.search_project_memories_for_tool(
                db,
                workspace_id=workspace_id,
                project_id=project["id"],
                conversation_id=conversation_id,
                conversation_created_by=user_info["user"]["id"],
                query="这个项目 API 有没有矛盾？",
                top_k=5,
                semantic_search_fn=fake_semantic_search,
            )
        )
    assert len(conflict_results) == 2


def test_memory_search_returns_layered_mixed_hits_for_playbook_queries() -> None:
    client = TestClient(main_module.app)
    user_info = register_user(client, "memory-layered-search@example.com", "Memory Layered Search")
    workspace_id = user_info["workspace"]["id"]
    user_id = user_info["user"]["id"]
    project = create_project(client, "Memory Layered Search Project")
    conversation_id = create_conversation_record(
        workspace_id,
        project["id"],
        user_id,
        "Memory Layered Search Conversation",
    )

    with SessionLocal() as db:
        project_record = db.get(Project, project["id"])
        assert project_record is not None
        ensure_project_assistant_root(db, project_record, reparent_orphans=False)
        subject_memory, _ = ensure_project_user_subject(
            db,
            project_record,
            owner_user_id=user_id,
        )
        playbook_content = "排查路由器时先检查电源，再确认指示灯，最后重启设备。"
        metadata = memory_metadata_service.normalize_memory_metadata(
            content=playbook_content,
            category="方法.网络",
            memory_type="permanent",
            metadata={
                "node_type": "fact",
                "node_status": "active",
                "subject_memory_id": subject_memory.id,
            },
        )
        playbook_memory = Memory(
            workspace_id=workspace_id,
            project_id=project["id"],
            content=playbook_content,
            category="方法.网络",
            type="permanent",
            node_type="fact",
            parent_memory_id=subject_memory.id,
            subject_memory_id=subject_memory.id,
            source_conversation_id=conversation_id,
            node_status="active",
            canonical_key=str(metadata.get("canonical_key") or "").strip() or None,
            lineage_key=str(metadata.get("lineage_key") or "").strip() or None,
            metadata_json=metadata,
        )
        db.add(playbook_memory)
        db.flush()
        memory_v2_service.record_memory_evidence(
            db,
            memory=playbook_memory,
            source_type="conversation",
            conversation_id=conversation_id,
            message_role="user",
            quote_text=playbook_content,
            confidence=0.92,
        )
        playbook_view = memory_v2_service.refresh_subject_playbook_view(
            db,
            subject_memory=subject_memory,
            source_memory_ids=[playbook_memory.id],
            source_text=playbook_content,
        )
        db.commit()
        playbook_memory_id = playbook_memory.id
        playbook_view_id = playbook_view.id if playbook_view is not None else None

    response = client.post(
        "/api/v1/memory/search",
        json={
            "project_id": project["id"],
            "query": "怎么排查路由器？",
            "top_k": 10,
        },
        headers=csrf_headers(client),
    )
    assert response.status_code == 200
    payload = response.json()
    result_types = {item["result_type"] for item in payload}
    assert {"memory", "view", "evidence"}.issubset(result_types)

    memory_hit = next(item for item in payload if item["result_type"] == "memory")
    assert memory_hit["memory"]["id"] == playbook_memory_id

    view_hit = next(item for item in payload if item["result_type"] == "view")
    assert view_hit["view"]["id"] == playbook_view_id
    assert view_hit["view"]["view_type"] == "playbook"
    assert view_hit["supporting_memory_id"] == playbook_memory_id

    evidence_hit = next(item for item in payload if item["result_type"] == "evidence")
    assert evidence_hit["memory"]["id"] == playbook_memory_id
    assert "检查电源" in evidence_hit["evidence"]["quote_text"]


def test_memory_search_explain_returns_trace_suppressed_candidates_and_subgraph(monkeypatch) -> None:
    client = TestClient(main_module.app)
    user_info = register_user(client, "memory-explain@example.com", "Memory Explain User")
    workspace_id = user_info["workspace"]["id"]
    user_id = user_info["user"]["id"]
    project = create_project(client, "Memory Explain Project")
    conversation_id = create_conversation_record(
        workspace_id,
        project["id"],
        user_id,
        "Memory Explain Conversation",
    )

    with SessionLocal() as db:
        project_record = db.get(Project, project["id"])
        assert project_record is not None
        ensure_project_assistant_root(db, project_record, reparent_orphans=False)
        subject_memory, _ = ensure_project_user_subject(
            db,
            project_record,
            owner_user_id=user_id,
        )
        visible_memory = Memory(
            workspace_id=workspace_id,
            project_id=project["id"],
            content="用户要求周报先给摘要。",
            category="偏好.写作",
            type="permanent",
            parent_memory_id=subject_memory.id,
            subject_memory_id=subject_memory.id,
            metadata_json={"memory_kind": "preference"},
        )
        suppressed_memory = Memory(
            workspace_id=workspace_id,
            project_id=project["id"],
            content="旧版周报喜欢先铺背景。",
            category="偏好.写作",
            type="permanent",
            parent_memory_id=subject_memory.id,
            subject_memory_id=subject_memory.id,
            metadata_json={"memory_kind": "preference", "suppression_reason": "superseded"},
        )
        db.add_all([visible_memory, suppressed_memory])
        db.commit()
        visible_memory_id = visible_memory.id
        suppressed_memory_id = suppressed_memory.id
        subject_id = subject_memory.id

    async def fake_explain(*args, **kwargs):
        del args, kwargs
        return {
            "hits": [
                {
                    "result_type": "memory",
                    "memory_id": visible_memory_id,
                    "score": 0.97,
                    "snippet": "用户要求周报先给摘要。",
                    "selection_reason": "matched stable preference",
                    "outcome_weight": 1.15,
                    "episode_id": "episode-memory-explain",
                }
            ],
            "trace": {
                "strategy": "layered_memory_v2",
                "query_type": "profile",
                "primary_subject_id": subject_id,
                "policy_flags": ["single_source_explicit"],
                "suppressed_memory_ids": [suppressed_memory_id],
            },
        }

    async def fake_subject_subgraph(*args, **kwargs):
        del args, kwargs
        return {
            "nodes": [
                {
                    "id": subject_id,
                    "workspace_id": workspace_id,
                    "project_id": project["id"],
                    "content": "Memory Explain User",
                    "category": "user",
                    "type": "permanent",
                    "metadata_json": {"node_type": "subject"},
                    "source_conversation_id": None,
                    "parent_memory_id": None,
                    "position_x": None,
                    "position_y": None,
                    "created_at": datetime.now(timezone.utc),
                    "updated_at": datetime.now(timezone.utc),
                },
                {
                    "id": visible_memory_id,
                    "workspace_id": workspace_id,
                    "project_id": project["id"],
                    "content": "用户要求周报先给摘要。",
                    "category": "偏好.写作",
                    "type": "permanent",
                    "metadata_json": {},
                    "source_conversation_id": None,
                    "parent_memory_id": subject_id,
                    "position_x": None,
                    "position_y": None,
                    "created_at": datetime.now(timezone.utc),
                    "updated_at": datetime.now(timezone.utc),
                },
            ],
            "edges": [
                {
                    "id": "edge-memory-explain",
                    "source_memory_id": subject_id,
                    "target_memory_id": visible_memory_id,
                    "edge_type": "parent",
                    "strength": 1.0,
                    "confidence": 1.0,
                    "created_at": datetime.now(timezone.utc),
                }
            ],
        }

    monkeypatch.setattr(memory_router, "explain_project_memory_hits_v2", fake_explain)
    monkeypatch.setattr(memory_router, "expand_subject_subgraph", fake_subject_subgraph)

    response = client.post(
        "/api/v1/memory/search/explain",
        json={
            "project_id": project["id"],
            "conversation_id": conversation_id,
            "query": "用户喜欢什么样的周报？",
            "top_k": 5,
        },
        headers=csrf_headers(client),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["trace"]["strategy"] == "layered_memory_v2"
    assert body["trace"]["query_type"] == "profile"
    assert body["hits"][0]["memory"]["id"] == visible_memory_id
    assert body["hits"][0]["selection_reason"] == "matched stable preference"
    assert body["suppressed_candidates"][0]["id"] == suppressed_memory_id
    assert {node["id"] for node in body["subgraph"]["nodes"]} == {subject_id, visible_memory_id}


def test_memory_subgraph_route_returns_parent_edge_for_visible_neighbors() -> None:
    client = TestClient(main_module.app)
    owner_info = register_user(client, "memory-subgraph@example.com", "Memory Subgraph User")
    workspace_id = owner_info["workspace"]["id"]
    project = create_project(client, "Memory Subgraph Project")

    subject = client.post(
        "/api/v1/memory",
        json={
            "project_id": project["id"],
            "content": "工作流",
            "category": "topic",
            "node_type": "subject",
            "subject_kind": "topic",
        },
        headers=csrf_headers(client, workspace_id),
    )
    assert subject.status_code == 200

    fact = client.post(
        "/api/v1/memory",
        json={
            "project_id": project["id"],
            "content": "夜间复盘前先整理当天任务。",
            "category": "方法.复盘",
            "parent_memory_id": subject.json()["id"],
        },
        headers=csrf_headers(client, workspace_id),
    )
    assert fact.status_code == 200

    response = client.post(
        f"/api/v1/memory/{fact.json()['id']}/subgraph",
        json={"depth": 2},
        headers=csrf_headers(client, workspace_id),
    )
    assert response.status_code == 200
    body = response.json()
    node_ids = {node["id"] for node in body["nodes"]}
    assert {subject.json()["id"], fact.json()["id"]}.issubset(node_ids)
    assert any(edge["edge_type"] == "parent" for edge in body["edges"])


def test_extract_memories_retries_with_user_only_fallback_when_primary_returns_empty(monkeypatch) -> None:
    import app.services.dashscope_client as dashscope_client_module
    import app.services.embedding as embedding_service

    client = TestClient(main_module.app)
    user_info = register_user(client, "memory-fallback@example.com", "Memory Fallback")
    workspace_id = user_info["workspace"]["id"]
    project = create_project(client, "Memory Fallback Project")
    conversation_id = create_conversation_record(
        workspace_id,
        project["id"],
        user_info["user"]["id"],
        "Memory Fallback Conversation",
    )

    with SessionLocal() as db:
        assistant_message = Message(
            conversation_id=conversation_id,
            role="assistant",
            content="已记住。",
            metadata_json={},
        )
        db.add(assistant_message)
        db.commit()
        assistant_message_id = assistant_message.id

    call_count = {"value": 0}

    async def fake_extract_completion(messages, *args, **kwargs):
        del args, kwargs
        call_count["value"] += 1
        prompt_text = messages[0]["content"]
        if call_count["value"] == 1:
            assert "禁止输出“用户偏好A和B”这类聚合句" in prompt_text
            return "[]"
        assert "只根据用户原话" in prompt_text
        assert "禁止输出“用户偏好A和B”这类聚合句" not in prompt_text
        return json.dumps(
            [
                {
                    "fact": "用户喜欢乌龙茶。",
                    "category": "饮食.偏好",
                    "importance": 0.95,
                },
                {
                    "fact": "用户喜欢茉莉花茶。",
                    "category": "饮食.偏好",
                    "importance": 0.95,
                },
            ],
            ensure_ascii=False,
        )

    async def fake_find_duplicate(*args, **kwargs):
        del args, kwargs
        return None, [0.18, 0.27, 0.36]

    async def fake_find_related(*args, **kwargs):
        del args, kwargs
        return []

    async def fake_embed_and_store(*args, **kwargs):
        del args, kwargs
        return None

    async def fake_resolve_concept_parent(*args, **kwargs):
        del args, kwargs
        return None, False, None

    monkeypatch.setattr(dashscope_client_module, "chat_completion", fake_extract_completion)
    monkeypatch.setattr(embedding_service, "find_duplicate_memory_with_vector", fake_find_duplicate)
    monkeypatch.setattr(embedding_service, "find_related_memories", fake_find_related)
    monkeypatch.setattr(embedding_service, "embed_and_store", fake_embed_and_store)
    monkeypatch.setattr(worker_tasks, "_resolve_concept_parent", fake_resolve_concept_parent)
    monkeypatch.setattr(worker_tasks, "compact_project_memories_task", lambda *args, **kwargs: None)
    monkeypatch.setattr(worker_tasks, "repair_project_memory_graph_task", lambda *args, **kwargs: None)

    worker_tasks.extract_memories(
        workspace_id,
        project["id"],
        conversation_id,
        "我喜欢乌龙茶，也喜欢茉莉花茶。请记住它们。",
        "已记住。",
        assistant_message_id,
    )

    with SessionLocal() as db:
        assistant_message = db.get(Message, assistant_message_id)
        assert assistant_message is not None
        metadata = assistant_message.metadata_json or {}
        extracted_facts = metadata.get("extracted_facts")
        assert call_count["value"] == 2
        assert isinstance(extracted_facts, list)
        assert len(extracted_facts) == 2
        assert metadata["memories_extracted"] == "新增永久记忆 2 条"


def test_extract_memories_writes_empty_summary_when_no_fact_is_extracted(monkeypatch) -> None:
    import app.services.dashscope_client as dashscope_client_module

    client = TestClient(main_module.app)
    user_info = register_user(client, "memory-empty-summary@example.com", "Memory Empty Summary")
    workspace_id = user_info["workspace"]["id"]
    project = create_project(client, "Memory Empty Summary Project")
    conversation_id = create_conversation_record(
        workspace_id,
        project["id"],
        user_info["user"]["id"],
        "Memory Empty Summary Conversation",
    )

    with SessionLocal() as db:
        assistant_message = Message(
            conversation_id=conversation_id,
            role="assistant",
            content="好的，我来列一下。",
            metadata_json={},
        )
        db.add(assistant_message)
        db.commit()
        assistant_message_id = assistant_message.id

    async def fake_extract_completion(*args, **kwargs):
        del args, kwargs
        return "[]"

    monkeypatch.setattr(dashscope_client_module, "chat_completion", fake_extract_completion)
    monkeypatch.setattr(worker_tasks, "compact_project_memories_task", lambda *args, **kwargs: None)

    worker_tasks.extract_memories(
        workspace_id,
        project["id"],
        conversation_id,
        "请把这段回复整理成项目符号列表，不要新增任何记忆。",
        "好的，我来列一下。",
        assistant_message_id,
    )

    with SessionLocal() as db:
        assistant_message = db.get(Message, assistant_message_id)
        assert assistant_message is not None
        metadata = assistant_message.metadata_json or {}
        assert metadata.get("extracted_facts") == []
        assert metadata.get("memories_extracted") == "本轮未提取到可保存记忆"


def test_extract_memories_heuristically_marks_duplicate_preferences_when_model_returns_empty(monkeypatch) -> None:
    import app.services.dashscope_client as dashscope_client_module
    import app.services.embedding as embedding_service

    client = TestClient(main_module.app)
    user_info = register_user(client, "memory-heuristic-duplicate@example.com", "Memory Heuristic Duplicate")
    workspace_id = user_info["workspace"]["id"]
    project = create_project(client, "Memory Heuristic Duplicate Project")
    conversation_id = create_conversation_record(
        workspace_id,
        project["id"],
        user_info["user"]["id"],
        "Memory Heuristic Duplicate Conversation",
    )

    with SessionLocal() as db:
        oolong = Memory(
            workspace_id=workspace_id,
            project_id=project["id"],
            content="用户喜欢乌龙茶。",
            category="饮食.偏好",
            type="temporary",
            metadata_json={"memory_kind": "preference"},
        )
        jasmine = Memory(
            workspace_id=workspace_id,
            project_id=project["id"],
            content="用户喜欢茉莉花茶。",
            category="饮食.偏好",
            type="temporary",
            metadata_json={"memory_kind": "preference"},
        )
        assistant_message = Message(
            conversation_id=conversation_id,
            role="assistant",
            content="好的，已记住。",
            metadata_json={},
        )
        db.add_all([oolong, jasmine, assistant_message])
        db.commit()
        oolong_id = oolong.id
        jasmine_id = jasmine.id
        assistant_message_id = assistant_message.id

    async def fake_extract_completion(*args, **kwargs):
        del args, kwargs
        return "[]"

    async def fake_find_duplicate(*args, **kwargs):
        text = kwargs.get("text", "")
        if "乌龙茶" in text:
            return {"memory_id": oolong_id}, [0.11, 0.22, 0.33]
        if "茉莉花茶" in text:
            return {"memory_id": jasmine_id}, [0.11, 0.22, 0.33]
        return None, [0.11, 0.22, 0.33]

    async def fake_find_related(*args, **kwargs):
        del args, kwargs
        return []

    async def fake_embed_and_store(*args, **kwargs):
        del args, kwargs
        return None

    monkeypatch.setattr(dashscope_client_module, "chat_completion", fake_extract_completion)
    monkeypatch.setattr(embedding_service, "find_duplicate_memory_with_vector", fake_find_duplicate)
    monkeypatch.setattr(embedding_service, "find_related_memories", fake_find_related)
    monkeypatch.setattr(embedding_service, "embed_and_store", fake_embed_and_store)
    monkeypatch.setattr(worker_tasks, "compact_project_memories_task", lambda *args, **kwargs: None)

    worker_tasks.extract_memories(
        workspace_id,
        project["id"],
        conversation_id,
        "我也很喜欢乌龙茶，平时还常喝茉莉花茶。",
        "好的，已记住。",
        assistant_message_id,
    )

    with SessionLocal() as db:
        assistant_message = db.get(Message, assistant_message_id)
        assert assistant_message is not None
        metadata = assistant_message.metadata_json or {}
        extracted_facts = metadata.get("extracted_facts")
        assert isinstance(extracted_facts, list)
        assert [item["fact"] for item in extracted_facts] == ["用户喜欢乌龙茶。", "用户喜欢茉莉花茶。"]
        assert all(item["status"] == "permanent" for item in extracted_facts)
        assert all(item["triage_action"] == "promote" for item in extracted_facts)
        assert metadata.get("memories_extracted") == "新增永久记忆 2 条"

        promoted = (
            db.query(Memory)
            .filter(
                Memory.project_id == project["id"],
                Memory.content.in_(["用户喜欢乌龙茶。", "用户喜欢茉莉花茶。"]),
            )
            .all()
        )
        assert len(promoted) == 2
        assert all(memory.type == "permanent" for memory in promoted)


def test_extract_facts_heuristically_ignores_instructional_prompt() -> None:
    facts = worker_tasks._extract_facts_heuristically(
        "只输出 markdown 无序列表，每个列表项单独占一行，列出我喜欢的饮品，不要添加任何其他内容。"
    )

    assert facts == []


def test_extract_memories_resolves_conversation_from_assistant_message_id(monkeypatch) -> None:
    import app.services.dashscope_client as dashscope_client_module
    import app.services.embedding as embedding_service

    client = TestClient(main_module.app)
    user_info = register_user(client, "memory-assistant-fallback@example.com", "Memory Assistant Fallback")
    workspace_id = user_info["workspace"]["id"]
    project = create_project(client, "Memory Assistant Fallback Project")
    conversation_id = create_conversation_record(
        workspace_id,
        project["id"],
        user_info["user"]["id"],
        "Memory Assistant Fallback Conversation",
    )

    with SessionLocal() as db:
        assistant_message = Message(
            conversation_id=conversation_id,
            role="assistant",
            content="已记住。",
            metadata_json={},
        )
        db.add(assistant_message)
        db.commit()
        assistant_message_id = assistant_message.id

    async def fake_extract_completion(*args, **kwargs):
        del args, kwargs
        return json.dumps(
            [
                {
                    "fact": "用户计划今年去东京旅行。",
                    "category": "旅行.计划",
                    "importance": 0.95,
                }
            ],
            ensure_ascii=False,
        )

    async def fake_find_duplicate(*args, **kwargs):
        del args, kwargs
        return None, [0.19, 0.27, 0.35]

    async def fake_find_related(*args, **kwargs):
        del args, kwargs
        return []

    async def fake_embed_and_store(*args, **kwargs):
        del args, kwargs
        return None

    async def fake_resolve_concept_parent(*args, **kwargs):
        del args, kwargs
        return None, False, None

    monkeypatch.setattr(dashscope_client_module, "chat_completion", fake_extract_completion)
    monkeypatch.setattr(embedding_service, "find_duplicate_memory_with_vector", fake_find_duplicate)
    monkeypatch.setattr(embedding_service, "find_related_memories", fake_find_related)
    monkeypatch.setattr(embedding_service, "embed_and_store", fake_embed_and_store)
    monkeypatch.setattr(worker_tasks, "_resolve_concept_parent", fake_resolve_concept_parent)
    monkeypatch.setattr(worker_tasks, "compact_project_memories_task", lambda *args, **kwargs: None)
    monkeypatch.setattr(worker_tasks, "repair_project_memory_graph_task", lambda *args, **kwargs: None)

    worker_tasks.extract_memories(
        workspace_id,
        project["id"],
        "missing-conversation-id",
        "我计划今年去东京旅行。",
        "已记住。",
        assistant_message_id,
    )

    with SessionLocal() as db:
        assistant_message = db.get(Message, assistant_message_id)
        assert assistant_message is not None
        metadata = assistant_message.metadata_json or {}
        extracted_facts = metadata.get("extracted_facts")
        assert isinstance(extracted_facts, list)
        assert extracted_facts[0]["fact"] == "用户计划今年去东京旅行。"


def test_extract_memories_resolves_non_user_subject_from_quoted_title(monkeypatch) -> None:
    import app.services.dashscope_client as dashscope_client_module
    import app.services.embedding as embedding_service

    client = TestClient(main_module.app)
    user_info = register_user(client, "memory-book-subject@example.com", "Memory Book Subject")
    workspace_id = user_info["workspace"]["id"]
    project = create_project(client, "Memory Book Project")
    conversation_id = create_conversation_record(
        workspace_id,
        project["id"],
        user_info["user"]["id"],
        "Memory Book Conversation",
    )

    with SessionLocal() as db:
        assistant_message = Message(
            conversation_id=conversation_id,
            role="assistant",
            content="已记住。",
            metadata_json={},
        )
        db.add(assistant_message)
        db.commit()
        assistant_message_id = assistant_message.id

    async def fake_extract_completion(*args, **kwargs):
        del args, kwargs
        return json.dumps(
            [
                {
                    "fact": "《数学物理原理》包含流形章节。",
                    "category": "书籍.章节",
                    "importance": 0.95,
                }
            ],
            ensure_ascii=False,
        )

    async def fake_find_duplicate(*args, **kwargs):
        del args, kwargs
        return None, [0.17, 0.29, 0.41]

    async def fake_find_related(*args, **kwargs):
        del args, kwargs
        return []

    async def fake_embed_and_store(*args, **kwargs):
        del args, kwargs
        return None

    async def fake_resolve_concept_parent(*args, **kwargs):
        del args, kwargs
        return None, False, None

    monkeypatch.setattr(dashscope_client_module, "chat_completion", fake_extract_completion)
    monkeypatch.setattr(embedding_service, "find_duplicate_memory_with_vector", fake_find_duplicate)
    monkeypatch.setattr(embedding_service, "find_related_memories", fake_find_related)
    monkeypatch.setattr(embedding_service, "embed_and_store", fake_embed_and_store)
    monkeypatch.setattr(worker_tasks, "_resolve_concept_parent", fake_resolve_concept_parent)
    monkeypatch.setattr(worker_tasks, "compact_project_memories_task", lambda *args, **kwargs: None)
    monkeypatch.setattr(worker_tasks, "repair_project_memory_graph_task", lambda *args, **kwargs: None)

    worker_tasks.extract_memories(
        workspace_id,
        project["id"],
        conversation_id,
        "请记住这本书《数学物理原理》包含流形章节。",
        "已记住。",
        assistant_message_id,
    )

    with SessionLocal() as db:
        subject = (
            db.query(Memory)
            .filter(
                Memory.project_id == project["id"],
                Memory.node_type == "subject",
                Memory.content == "数学物理原理",
            )
            .first()
        )
        fact_memory = (
            db.query(Memory)
            .filter(
                Memory.project_id == project["id"],
                Memory.content == "《数学物理原理》包含流形章节。",
            )
            .first()
        )
        assistant_message = db.get(Message, assistant_message_id)
        assert subject is not None
        assert subject.subject_kind == "book"
        assert fact_memory is not None
        assert fact_memory.subject_memory_id == subject.id
        assert fact_memory.parent_memory_id == subject.id
        extracted_facts = (assistant_message.metadata_json or {}).get("extracted_facts")
        assert isinstance(extracted_facts, list)
        assert extracted_facts[0]["subject_memory_id"] == subject.id
        assert extracted_facts[0]["subject_kind"] == "book"
        assert extracted_facts[0]["subject_resolution"] == "created_or_reused_subject"


def test_canonicalize_fact_text_for_storage_rewrites_deictic_pronouns() -> None:
    subject_memory = Memory(
        workspace_id="workspace",
        project_id="project",
        content="比那名居天子",
        category="custom",
        type="permanent",
        node_type="subject",
        subject_kind="custom",
        source_conversation_id=None,
        parent_memory_id=None,
        subject_memory_id=None,
        node_status="active",
        canonical_key=None,
        lineage_key=None,
        metadata_json={"node_type": "subject", "node_kind": "subject", "subject_kind": "custom"},
    )

    rewritten = worker_tasks._canonicalize_fact_text_for_storage(
        fact_text="她的天人设定很有辨识度。",
        user_message="她的天人设定很有辨识度。",
        subject_memory=subject_memory,
        subject_resolution="conversation_focus_subject",
    )

    assert rewritten == "比那名居天子的天人设定很有辨识度。"


def test_canonicalize_fact_text_for_storage_prefixes_subject_for_predicate_only_fact() -> None:
    subject_memory = Memory(
        workspace_id="workspace",
        project_id="project",
        content="比那名居天子",
        category="custom",
        type="permanent",
        node_type="subject",
        subject_kind="custom",
        source_conversation_id=None,
        parent_memory_id=None,
        subject_memory_id=None,
        node_status="active",
        canonical_key=None,
        lineage_key=None,
        metadata_json={"node_type": "subject", "node_kind": "subject", "subject_kind": "custom"},
    )

    rewritten = worker_tasks._canonicalize_fact_text_for_storage(
        fact_text="很有辨识度。",
        user_message="这个角色很有辨识度。",
        subject_memory=subject_memory,
        subject_resolution="conversation_focus_subject",
    )

    assert rewritten == "比那名居天子很有辨识度。"


def test_extract_memories_canonicalizes_deictic_non_user_fact_text(monkeypatch) -> None:
    import app.services.dashscope_client as dashscope_client_module
    import app.services.embedding as embedding_service

    client = TestClient(main_module.app)
    user_info = register_user(client, "memory-canonical-non-user@example.com", "Memory Canonical Non User")
    workspace_id = user_info["workspace"]["id"]
    project = create_project(client, "Memory Canonical Non User Project")
    conversation_id = create_conversation_record(
        workspace_id,
        project["id"],
        user_info["user"]["id"],
        "Memory Canonical Non User Conversation",
    )

    with SessionLocal() as db:
        project_model = db.get(Project, project["id"])
        assert project_model is not None
        subject_memory, _ = ensure_project_subject(
            db,
            project_model,
            subject_kind="custom",
            label="比那名居天子",
            owner_user_id=user_info["user"]["id"],
        )
        conversation = db.get(Conversation, conversation_id)
        assert conversation is not None
        conversation.metadata_json = {
            **(conversation.metadata_json or {}),
            "primary_subject_id": subject_memory.id,
        }
        assistant_message = Message(
            conversation_id=conversation_id,
            role="assistant",
            content="已记住。",
            metadata_json={},
        )
        db.add(assistant_message)
        db.commit()
        assistant_message_id = assistant_message.id

    async def fake_extract_completion(*args, **kwargs):
        del args, kwargs
        return json.dumps(
            [
                {
                    "fact": "她的天人设定很有辨识度。",
                    "category": "人物.设定",
                    "importance": 0.95,
                }
            ],
            ensure_ascii=False,
        )

    async def fake_find_duplicate(*args, **kwargs):
        del args, kwargs
        return None, [0.17, 0.29, 0.41]

    async def fake_find_related(*args, **kwargs):
        del args, kwargs
        return []

    async def fake_embed_and_store(*args, **kwargs):
        del args, kwargs
        return None

    async def fake_resolve_concept_parent(*args, **kwargs):
        del args, kwargs
        return None, False, None

    monkeypatch.setattr(dashscope_client_module, "chat_completion", fake_extract_completion)
    monkeypatch.setattr(embedding_service, "find_duplicate_memory_with_vector", fake_find_duplicate)
    monkeypatch.setattr(embedding_service, "find_related_memories", fake_find_related)
    monkeypatch.setattr(embedding_service, "embed_and_store", fake_embed_and_store)
    monkeypatch.setattr(worker_tasks, "_resolve_concept_parent", fake_resolve_concept_parent)
    monkeypatch.setattr(worker_tasks, "compact_project_memories_task", lambda *args, **kwargs: None)

    worker_tasks.extract_memories(
        workspace_id,
        project["id"],
        conversation_id,
        "她的天人设定很有辨识度。",
        "已记住。",
        assistant_message_id,
    )

    with SessionLocal() as db:
        fact_memory = (
            db.query(Memory)
            .filter(
                Memory.project_id == project["id"],
                Memory.content == "比那名居天子的天人设定很有辨识度。",
            )
            .first()
        )
        assistant_message = db.get(Message, assistant_message_id)
        assert fact_memory is not None
        extracted_facts = (assistant_message.metadata_json or {}).get("extracted_facts")
        assert isinstance(extracted_facts, list)
        assert extracted_facts[0]["fact"] == "比那名居天子的天人设定很有辨识度。"
        assert extracted_facts[0]["subject_label"] == "比那名居天子"
        assert extracted_facts[0]["subject_resolution"] == "conversation_focus_subject"


def test_temporary_preference_keeps_preference_memory_kind() -> None:
    metadata = memory_metadata_service.normalize_memory_metadata(
        content="用户喜欢冷萃咖啡。",
        category="饮食.偏好",
        memory_type="temporary",
        metadata={},
    )

    assert metadata["memory_kind"] == "preference"


def test_extract_memories_discards_aggregate_preference_fact(monkeypatch) -> None:
    import app.services.dashscope_client as dashscope_client_module
    import app.services.embedding as embedding_service

    client = TestClient(main_module.app)
    user_info = register_user(client, "memory-aggregate-filter@example.com", "Memory Aggregate Filter")
    workspace_id = user_info["workspace"]["id"]
    project = create_project(client, "Memory Aggregate Filter Project")
    conversation_id = create_conversation_record(
        workspace_id,
        project["id"],
        user_info["user"]["id"],
        "Memory Aggregate Filter Conversation",
    )

    with SessionLocal() as db:
        assistant_message = Message(
            conversation_id=conversation_id,
            role="assistant",
            content="已记住。",
            metadata_json={},
        )
        db.add(assistant_message)
        db.commit()
        assistant_message_id = assistant_message.id

    async def fake_extract_completion(*args, **kwargs):
        del args, kwargs
        return json.dumps(
            [
                {
                    "fact": "用户偏好乌龙茶和茉莉花茶。",
                    "category": "饮食.偏好",
                    "importance": 0.95,
                },
                {
                    "fact": "用户喜欢冷萃咖啡。",
                    "category": "饮食.偏好",
                    "importance": 0.95,
                },
            ],
            ensure_ascii=False,
        )

    async def fake_find_duplicate(*args, **kwargs):
        del args, kwargs
        return None, [0.14, 0.28, 0.42]

    async def fake_find_related(*args, **kwargs):
        del args, kwargs
        return []

    async def fake_embed_and_store(*args, **kwargs):
        del args, kwargs
        return None

    async def fake_resolve_concept_parent(*args, **kwargs):
        del args, kwargs
        return None, False, None

    monkeypatch.setattr(dashscope_client_module, "chat_completion", fake_extract_completion)
    monkeypatch.setattr(embedding_service, "find_duplicate_memory_with_vector", fake_find_duplicate)
    monkeypatch.setattr(embedding_service, "find_related_memories", fake_find_related)
    monkeypatch.setattr(embedding_service, "embed_and_store", fake_embed_and_store)
    monkeypatch.setattr(worker_tasks, "_resolve_concept_parent", fake_resolve_concept_parent)
    monkeypatch.setattr(worker_tasks, "compact_project_memories_task", lambda *args, **kwargs: None)

    worker_tasks.extract_memories(
        workspace_id,
        project["id"],
        conversation_id,
        "我喜欢冷萃咖啡，也喜欢乌龙茶和茉莉花茶。",
        "已记住。",
        assistant_message_id,
    )

    with SessionLocal() as db:
        saved_memories = (
            db.query(Memory)
            .filter(
                Memory.project_id == project["id"],
                Memory.content.in_(["用户偏好乌龙茶和茉莉花茶。", "用户喜欢冷萃咖啡。"]),
            )
            .all()
        )
        assistant_message = db.get(Message, assistant_message_id)
        assert [memory.content for memory in saved_memories] == ["用户喜欢冷萃咖啡。"]
        extracted_facts = (assistant_message.metadata_json or {}).get("extracted_facts")
        assert isinstance(extracted_facts, list)
        aggregate_entry = next(item for item in extracted_facts if item["fact"] == "用户偏好乌龙茶和茉莉花茶。")
        assert aggregate_entry["status"] == "discarded"
        assert "聚合型事实" in aggregate_entry["triage_reason"]
        assert "新增永久记忆 1 条" in assistant_message.metadata_json["memories_extracted"]
        assert "被 triage 丢弃 1 条" in assistant_message.metadata_json["memories_extracted"]


def test_validate_append_parent_downgrades_leaf_parent_to_sibling(monkeypatch) -> None:
    async def fake_validation_completion(*args, **kwargs):
        del args, kwargs
        return json.dumps({"relation": "parent", "reason": "旧记忆更泛化。"}, ensure_ascii=False)

    monkeypatch.setattr(worker_tasks.dashscope_client, "chat_completion", fake_validation_completion)

    candidate = Memory(
        workspace_id="ws_1",
        project_id="proj_1",
        content="用户喜欢喝冰美式。",
        category="饮食.偏好",
        type="permanent",
        metadata_json={"memory_kind": "preference"},
    )

    result = asyncio.run(
        worker_tasks._validate_append_parent(
            fact_text="用户喜欢冷萃咖啡。",
            fact_category="饮食.偏好",
            fact_memory_kind="preference",
            candidate_memory=candidate,
        )
    )

    assert result["relation"] == "sibling"


def test_memory_compaction_skips_concept_nodes() -> None:
    concept_memory = Memory(
        workspace_id="ws_1",
        project_id="proj_1",
        content="用户对咖啡感兴趣",
        category="饮食.偏好.咖啡",
        type="permanent",
        metadata_json={"memory_kind": "preference", "node_kind": "concept"},
    )

    assert memory_compaction_service._eligible_for_compaction(concept_memory) is False


def test_plan_concept_parent_uses_heuristic_for_non_user_fact_subject(monkeypatch) -> None:
    async def fail_completion(*args, **kwargs):
        raise AssertionError("fact concept heuristic should not call the LLM")

    monkeypatch.setattr(worker_tasks.dashscope_client, "chat_completion", fail_completion)

    subject = Memory(
        workspace_id="ws_1",
        project_id="proj_1",
        content="比那名居天子",
        category="人物",
        type="permanent",
        node_type="subject",
        metadata_json={"node_kind": "subject", "subject_kind": "person"},
    )

    result = asyncio.run(
        worker_tasks._plan_concept_parent(
            subject_memory=subject,
            fact_text="比那名居天子的天人设定很有辨识度。",
            fact_category="人物.设定",
            fact_memory_kind="fact",
        )
    )

    assert result == {
        "topic": "设定",
        "parent_text": "角色设定",
        "parent_category": "人物.设定",
        "reason": "根据分类和事实内容归入「角色设定」主题。",
    }


def test_plan_concept_parent_groups_user_profile_facts_under_structural_concept(monkeypatch) -> None:
    async def fail_completion(*args, **kwargs):
        raise AssertionError("user fact concept heuristic should not call the LLM")

    monkeypatch.setattr(worker_tasks.dashscope_client, "chat_completion", fail_completion)

    subject = Memory(
        workspace_id="ws_1",
        project_id="proj_1",
        content="用户",
        category="identity",
        type="permanent",
        node_type="subject",
        metadata_json={"node_kind": "subject", "subject_kind": "user"},
    )

    result = asyncio.run(
        worker_tasks._plan_concept_parent(
            subject_memory=subject,
            fact_text="用户现在是大一学生。",
            fact_category="教育.学业阶段",
            fact_memory_kind="fact",
        )
    )

    assert result == {
        "topic": "教育",
        "parent_text": "教育背景",
        "parent_category": "教育",
        "reason": "根据分类和事实内容归入「教育背景」主题。",
    }


def test_extract_memories_groups_specific_preference_under_concept_parent(monkeypatch) -> None:
    import app.services.dashscope_client as dashscope_client_module
    import app.services.embedding as embedding_service

    client = TestClient(main_module.app)
    user_info = register_user(client, "memory-concept@example.com", "Memory Concept")
    workspace_id = user_info["workspace"]["id"]
    project = create_project(client, "Memory Concept Project")
    conversation_id = create_conversation_record(
        workspace_id,
        project["id"],
        user_info["user"]["id"],
        "Memory Concept Conversation",
    )

    with SessionLocal() as db:
        assistant_message = Message(
            conversation_id=conversation_id,
            role="assistant",
            content="这条消息稍后会展示记忆变更。",
            metadata_json={},
        )
        db.add(assistant_message)
        db.commit()
        assistant_message_id = assistant_message.id

    async def fake_extract_completion(*args, **kwargs):
        del args, kwargs
        return json.dumps(
            [
                {
                    "fact": "用户喜欢喝冰美式",
                    "category": "偏好.饮品",
                    "importance": 0.95,
                }
            ],
            ensure_ascii=False,
        )

    async def fake_find_duplicate(*args, **kwargs):
        del args, kwargs
        return None, [0.21, 0.43, 0.65]

    async def fake_find_related(*args, **kwargs):
        del args, kwargs
        return []

    async def fake_embed_and_store(*args, **kwargs):
        del args, kwargs
        return None

    async def fake_plan_concept_parent(*args, **kwargs):
        del args, kwargs
        return {
            "topic": "咖啡",
            "parent_text": "用户对咖啡感兴趣",
            "parent_category": "偏好.饮品.咖啡",
            "reason": "冰美式属于咖啡偏好。",
        }

    monkeypatch.setattr(dashscope_client_module, "chat_completion", fake_extract_completion)
    monkeypatch.setattr(embedding_service, "find_duplicate_memory_with_vector", fake_find_duplicate)
    monkeypatch.setattr(embedding_service, "find_related_memories", fake_find_related)
    monkeypatch.setattr(embedding_service, "embed_and_store", fake_embed_and_store)
    monkeypatch.setattr(worker_tasks, "_plan_concept_parent", fake_plan_concept_parent)
    monkeypatch.setattr(worker_tasks, "compact_project_memories_task", lambda *args, **kwargs: None)

    worker_tasks.extract_memories(
        workspace_id,
        project["id"],
        conversation_id,
        "请记住我喜欢喝冰美式",
        "已记住。",
        assistant_message_id,
    )

    with SessionLocal() as db:
        concept_memory = (
            db.query(Memory)
            .filter(
                Memory.project_id == project["id"],
                Memory.content == "用户对咖啡感兴趣",
            )
            .first()
        )
        child_memory = (
            db.query(Memory)
            .filter(
                Memory.project_id == project["id"],
                Memory.content == "用户喜欢喝冰美式",
            )
            .first()
        )
        assistant_message = db.get(Message, assistant_message_id)
        assert concept_memory is not None
        assert child_memory is not None
        assert child_memory.parent_memory_id == concept_memory.id
        assert (concept_memory.metadata_json or {}).get("node_kind") == "concept"

        edge = (
            db.query(MemoryEdge)
            .filter(
                MemoryEdge.source_memory_id == concept_memory.id,
                MemoryEdge.target_memory_id == child_memory.id,
            )
            .first()
        )
        assert edge is not None

        metadata = assistant_message.metadata_json or {}
        extracted_facts = metadata.get("extracted_facts")
        assert isinstance(extracted_facts, list)
        assert "用户对咖啡感兴趣" in extracted_facts[0]["triage_reason"]
        assert metadata["memories_extracted"] == "新增永久记忆 1 条；新增主题节点 1 条"


def test_extract_memories_promotes_explicit_preference_to_permanent(monkeypatch) -> None:
    import app.services.dashscope_client as dashscope_client_module
    import app.services.embedding as embedding_service

    client = TestClient(main_module.app)
    user_info = register_user(client, "memory-preference-promote@example.com", "Memory Promote")
    workspace_id = user_info["workspace"]["id"]
    project = create_project(client, "Memory Promote Project")
    conversation_id = create_conversation_record(
        workspace_id,
        project["id"],
        user_info["user"]["id"],
        "Memory Promote Conversation",
    )

    with SessionLocal() as db:
        assistant_message = Message(
            conversation_id=conversation_id,
            role="assistant",
            content="这条消息稍后会展示记忆变更。",
            metadata_json={},
        )
        db.add(assistant_message)
        db.commit()
        assistant_message_id = assistant_message.id

    async def fake_extract_completion(*args, **kwargs):
        del args, kwargs
        return json.dumps(
            [
                {
                    "fact": "用户喜欢冷萃咖啡",
                    "category": "饮食.偏好.咖啡",
                    "importance": 0.8,
                }
            ],
            ensure_ascii=False,
        )

    async def fake_find_duplicate(*args, **kwargs):
        del args, kwargs
        return None, [0.11, 0.22, 0.33]

    async def fake_find_related(*args, **kwargs):
        del args, kwargs
        return []

    async def fake_embed_and_store(*args, **kwargs):
        del args, kwargs
        return None

    async def fake_plan_concept_parent(*args, **kwargs):
        del args, kwargs
        return {
            "topic": "咖啡",
            "parent_text": "用户对咖啡感兴趣",
            "parent_category": "饮食.偏好.咖啡",
            "reason": "冷萃咖啡属于咖啡偏好。",
        }

    monkeypatch.setattr(dashscope_client_module, "chat_completion", fake_extract_completion)
    monkeypatch.setattr(embedding_service, "find_duplicate_memory_with_vector", fake_find_duplicate)
    monkeypatch.setattr(embedding_service, "find_related_memories", fake_find_related)
    monkeypatch.setattr(embedding_service, "embed_and_store", fake_embed_and_store)
    monkeypatch.setattr(worker_tasks, "_plan_concept_parent", fake_plan_concept_parent)
    monkeypatch.setattr(worker_tasks, "compact_project_memories_task", lambda *args, **kwargs: None)

    worker_tasks.extract_memories(
        workspace_id,
        project["id"],
        conversation_id,
        "我喜欢冷萃咖啡。",
        "已记住。",
        assistant_message_id,
    )

    with SessionLocal() as db:
        concept_memory = (
            db.query(Memory)
            .filter(
                Memory.project_id == project["id"],
                Memory.content == "用户对咖啡感兴趣",
            )
            .first()
        )
        child_memory = (
            db.query(Memory)
            .filter(
                Memory.project_id == project["id"],
                Memory.parent_memory_id == concept_memory.id,
                Memory.id != concept_memory.id,
            )
            .first()
        )
        assistant_message = db.get(Message, assistant_message_id)
        assert concept_memory is not None
        assert child_memory is not None
        assert child_memory.type == "permanent"
        assert child_memory.parent_memory_id == concept_memory.id
        metadata = assistant_message.metadata_json or {}
        extracted_facts = metadata.get("extracted_facts")
        assert isinstance(extracted_facts, list)
        assert extracted_facts[0]["status"] == "permanent"
        assert metadata["memories_extracted"] == "新增永久记忆 1 条；新增主题节点 1 条"


def test_extract_memories_writes_profile_fact_as_permanent_below_high_threshold(monkeypatch) -> None:
    import app.services.dashscope_client as dashscope_client_module
    import app.services.embedding as embedding_service

    client = TestClient(main_module.app)
    user_info = register_user(client, "memory-profile-promote@example.com", "Memory Profile Promote")
    workspace_id = user_info["workspace"]["id"]
    project = create_project(client, "Memory Profile Promote Project")
    conversation_id = create_conversation_record(
        workspace_id,
        project["id"],
        user_info["user"]["id"],
        "Memory Profile Promote Conversation",
    )

    with SessionLocal() as db:
        assistant_message = Message(
            conversation_id=conversation_id,
            role="assistant",
            content="我会记住这条背景信息。",
            metadata_json={},
        )
        db.add(assistant_message)
        db.commit()
        assistant_message_id = assistant_message.id

    async def fake_extract_completion(*args, **kwargs):
        del args, kwargs
        return json.dumps(
            [
                {
                    "fact": "用户目前是产品经理",
                    "category": "背景.职业",
                    "importance": 0.72,
                }
            ],
            ensure_ascii=False,
        )

    async def fake_find_duplicate(*args, **kwargs):
        del args, kwargs
        return None, [0.14, 0.22, 0.31]

    async def fake_find_related(*args, **kwargs):
        del args, kwargs
        return []

    async def fake_embed_and_store(*args, **kwargs):
        del args, kwargs
        return None

    async def fake_resolve_concept_parent(*args, **kwargs):
        del args, kwargs
        return None, False, None

    monkeypatch.setattr(dashscope_client_module, "chat_completion", fake_extract_completion)
    monkeypatch.setattr(embedding_service, "find_duplicate_memory_with_vector", fake_find_duplicate)
    monkeypatch.setattr(embedding_service, "find_related_memories", fake_find_related)
    monkeypatch.setattr(embedding_service, "embed_and_store", fake_embed_and_store)
    monkeypatch.setattr(worker_tasks, "_resolve_concept_parent", fake_resolve_concept_parent)
    monkeypatch.setattr(worker_tasks, "compact_project_memories_task", lambda *args, **kwargs: None)
    monkeypatch.setattr(worker_tasks, "repair_project_memory_graph_task", lambda *args, **kwargs: None)

    worker_tasks.extract_memories(
        workspace_id,
        project["id"],
        conversation_id,
        "我目前是产品经理，主要做 AI 产品。",
        "我会记住这条背景信息。",
        assistant_message_id,
    )

    with SessionLocal() as db:
        profile_memory = (
            db.query(Memory)
            .filter(
                Memory.project_id == project["id"],
                Memory.category == "背景.职业",
            )
            .first()
        )
        assistant_message = db.get(Message, assistant_message_id)
        assert profile_memory is not None
        assert profile_memory.type == "permanent"
        assert (profile_memory.metadata_json or {}).get("memory_kind") == "profile"
        metadata = assistant_message.metadata_json or {}
        extracted_facts = metadata.get("extracted_facts")
        assert isinstance(extracted_facts, list)
        assert extracted_facts[0]["status"] == "permanent"
        assert metadata["memories_extracted"] == "新增永久记忆 1 条"


def test_extract_memories_promotes_first_person_preference_to_permanent(monkeypatch) -> None:
    import app.services.dashscope_client as dashscope_client_module
    import app.services.embedding as embedding_service

    client = TestClient(main_module.app)
    user_info = register_user(client, "memory-first-person-promote@example.com", "Memory First Person")
    workspace_id = user_info["workspace"]["id"]
    project = create_project(client, "Memory First Person Project")
    conversation_id = create_conversation_record(
        workspace_id,
        project["id"],
        user_info["user"]["id"],
        "Memory First Person Conversation",
    )

    with SessionLocal() as db:
        assistant_message = Message(
            conversation_id=conversation_id,
            role="assistant",
            content="这条消息稍后会展示记忆变更。",
            metadata_json={},
        )
        db.add(assistant_message)
        db.commit()
        assistant_message_id = assistant_message.id

    async def fake_extract_completion(*args, **kwargs):
        del args, kwargs
        return json.dumps(
            [
                {
                    "fact": "我也很喜欢冷萃咖啡",
                    "category": "饮食.偏好.咖啡",
                    "importance": 0.8,
                }
            ],
            ensure_ascii=False,
        )

    async def fake_find_duplicate(*args, **kwargs):
        del args, kwargs
        return None, [0.11, 0.22, 0.33]

    async def fake_find_related(*args, **kwargs):
        del args, kwargs
        return []

    async def fake_embed_and_store(*args, **kwargs):
        del args, kwargs
        return None

    async def fake_plan_concept_parent(*args, **kwargs):
        del args, kwargs
        return {
            "topic": "咖啡",
            "parent_text": "用户对咖啡感兴趣",
            "parent_category": "饮食.偏好.咖啡",
            "reason": "冷萃咖啡属于咖啡偏好。",
        }

    monkeypatch.setattr(dashscope_client_module, "chat_completion", fake_extract_completion)
    monkeypatch.setattr(embedding_service, "find_duplicate_memory_with_vector", fake_find_duplicate)
    monkeypatch.setattr(embedding_service, "find_related_memories", fake_find_related)
    monkeypatch.setattr(embedding_service, "embed_and_store", fake_embed_and_store)
    monkeypatch.setattr(worker_tasks, "_plan_concept_parent", fake_plan_concept_parent)
    monkeypatch.setattr(worker_tasks, "compact_project_memories_task", lambda *args, **kwargs: None)

    worker_tasks.extract_memories(
        workspace_id,
        project["id"],
        conversation_id,
        "我也很喜欢冷萃咖啡。",
        "已记住。",
        assistant_message_id,
    )

    with SessionLocal() as db:
        child_memory = (
            db.query(Memory)
            .filter(
                Memory.project_id == project["id"],
                Memory.category == "饮食.偏好.咖啡",
                Memory.content == "用户也很喜欢冷萃咖啡",
            )
            .first()
        )
        assistant_message = db.get(Message, assistant_message_id)
        assert child_memory is not None
        assert child_memory.type == "permanent"
        metadata = assistant_message.metadata_json or {}
        extracted_facts = metadata.get("extracted_facts")
        assert isinstance(extracted_facts, list)
        assert extracted_facts[0]["fact"] == "用户也很喜欢冷萃咖啡"
        assert extracted_facts[0]["status"] == "permanent"
        assert metadata["memories_extracted"] == "新增永久记忆 1 条；新增主题节点 1 条"


def test_refresh_subject_playbook_view_accumulates_success_count() -> None:
    client = TestClient(main_module.app)
    user_info = register_user(client, "memory-playbook-stats@example.com", "Memory Playbook Stats")
    workspace_id = user_info["workspace"]["id"]
    project = create_project(client, "Memory Playbook Stats Project")

    with SessionLocal() as db:
        project_record = db.get(Project, project["id"])
        assert project_record is not None
        ensure_project_assistant_root(db, project_record, reparent_orphans=False)
        subject_memory, _ = ensure_project_user_subject(
            db,
            project_record,
            owner_user_id=user_info["user"]["id"],
        )
        first_memory = Memory(
            workspace_id=workspace_id,
            project_id=project["id"],
            content="排查路由器时先检查电源，再确认指示灯，最后重启设备。",
            category="方法.网络",
            type="permanent",
            parent_memory_id=subject_memory.id,
            subject_memory_id=subject_memory.id,
            metadata_json={"memory_kind": "fact"},
        )
        second_memory = Memory(
            workspace_id=workspace_id,
            project_id=project["id"],
            content="排查路由器时先检查电源，再确认指示灯，最后重启设备。",
            category="方法.网络",
            type="permanent",
            parent_memory_id=subject_memory.id,
            subject_memory_id=subject_memory.id,
            metadata_json={"memory_kind": "fact"},
        )
        db.add_all([first_memory, second_memory])
        db.flush()

        first_view = memory_v2_service.refresh_subject_playbook_view(
            db,
            subject_memory=subject_memory,
            source_memory_ids=[first_memory.id],
            source_text=first_memory.content,
        )
        second_view = memory_v2_service.refresh_subject_playbook_view(
            db,
            subject_memory=subject_memory,
            source_memory_ids=[second_memory.id],
            source_text=second_memory.content,
        )
        first_memory_id = first_memory.id
        second_memory_id = second_memory.id
        first_view_id = first_view.id if first_view is not None else None
        second_view_id = second_view.id if second_view is not None else None
        db.commit()
        assert first_view is not None
        assert second_view is not None
        db.refresh(second_view)
        metadata = second_view.metadata_json or {}

    assert first_view_id == second_view_id
    assert metadata["success_count"] == 2
    assert metadata["failure_count"] == 0
    assert set(metadata["source_memory_ids"]) == {first_memory_id, second_memory_id}


def test_learning_runs_routes_hide_private_memory_runs_from_viewer() -> None:
    owner = TestClient(main_module.app)
    owner_info = register_user(owner, "memory-learning-owner@example.com", "Memory Learning Owner")
    workspace_id = owner_info["workspace"]["id"]
    owner_user_id = owner_info["user"]["id"]
    project = create_project(owner, "Memory Learning Privacy Project")
    conversation_id = create_conversation_record(
        workspace_id,
        project["id"],
        owner_user_id,
        "Owner Learning Thread",
    )

    temp_memory = owner.post(
        "/api/v1/memory",
        json={
            "project_id": project["id"],
            "content": "只有 owner 能看到的学习记忆",
            "category": "测试.学习",
            "type": "temporary",
            "source_conversation_id": conversation_id,
        },
        headers=csrf_headers(owner),
    )
    assert temp_memory.status_code == 200
    temp_memory_id = temp_memory.json()["id"]

    with SessionLocal() as db:
        learning_run = memory_v2_service.create_memory_learning_run(
            db,
            workspace_id=workspace_id,
            project_id=project["id"],
            conversation_id=conversation_id,
            trigger="post_turn",
            stages=["observe"],
            metadata_json={"source": "test"},
        )
        memory_v2_service.finalize_memory_learning_run(
            learning_run,
            status="completed",
            stages=["observe", "extract"],
            used_memory_ids=[temp_memory_id],
            metadata_json={"source": "test"},
        )
        db.commit()
        learning_run_id = learning_run.id

    owner_runs = owner.get(f"/api/v1/memory/learning-runs?project_id={project['id']}")
    assert owner_runs.status_code == 200
    assert [item["id"] for item in owner_runs.json()] == [learning_run_id]

    owner_run_detail = owner.get(f"/api/v1/memory/learning-runs/{learning_run_id}")
    assert owner_run_detail.status_code == 200
    assert owner_run_detail.json()["used_memory_ids"] == [temp_memory_id]

    viewer = TestClient(main_module.app)
    register_user(viewer, "memory-learning-viewer@example.com", "Memory Learning Viewer")
    add_workspace_membership(workspace_id, "memory-learning-viewer@example.com", "viewer")

    viewer_runs = viewer.get(
        f"/api/v1/memory/learning-runs?project_id={project['id']}",
        headers={"x-workspace-id": workspace_id},
    )
    assert viewer_runs.status_code == 200
    assert viewer_runs.json() == []

    viewer_run_detail = viewer.get(
        f"/api/v1/memory/learning-runs/{learning_run_id}",
        headers={"x-workspace-id": workspace_id},
    )
    assert viewer_run_detail.status_code == 404


def test_playbook_feedback_route_rejects_private_playbook_for_viewer() -> None:
    owner = TestClient(main_module.app)
    owner_info = register_user(owner, "memory-playbook-owner@example.com", "Memory Playbook Owner")
    workspace_id = owner_info["workspace"]["id"]
    project = create_project(owner, "Memory Private Playbook Project")

    with SessionLocal() as db:
        project_record = db.get(Project, project["id"])
        assert project_record is not None
        ensure_project_assistant_root(db, project_record, reparent_orphans=False)
        subject_memory, _ = ensure_project_user_subject(
            db,
            project_record,
            owner_user_id=owner_info["user"]["id"],
        )
        playbook_memory = Memory(
            workspace_id=workspace_id,
            project_id=project["id"],
            content="排查代理异常时先核对配置，再验证密钥，最后重试请求。",
            category="方法.代理",
            type="permanent",
            parent_memory_id=subject_memory.id,
            subject_memory_id=subject_memory.id,
            metadata_json={"memory_kind": "fact"},
        )
        db.add(playbook_memory)
        db.flush()
        playbook_view = memory_v2_service.refresh_subject_playbook_view(
            db,
            subject_memory=subject_memory,
            source_memory_ids=[playbook_memory.id],
            source_text=playbook_memory.content,
        )
        db.commit()
        assert playbook_view is not None
        playbook_view_id = playbook_view.id

    owner_feedback = owner.post(
        f"/api/v1/memory/playbooks/{playbook_view_id}/feedback",
        json={
            "project_id": project["id"],
            "status": "success",
            "memory_ids": [],
        },
        headers=csrf_headers(owner),
    )
    assert owner_feedback.status_code == 200

    viewer = TestClient(main_module.app)
    register_user(viewer, "memory-playbook-viewer@example.com", "Memory Playbook Viewer")
    add_workspace_membership(workspace_id, "memory-playbook-viewer@example.com", "editor")

    viewer_feedback = viewer.post(
        f"/api/v1/memory/playbooks/{playbook_view_id}/feedback",
        json={
            "project_id": project["id"],
            "status": "failure",
            "root_cause": "not_visible",
            "memory_ids": [],
        },
        headers=csrf_headers(viewer, workspace_id),
    )
    assert viewer_feedback.status_code == 404


def test_extract_memories_infers_interest_from_repeated_topic_questions(monkeypatch) -> None:
    import app.services.dashscope_client as dashscope_client_module
    import app.services.embedding as embedding_service

    client = TestClient(main_module.app)
    user_info = register_user(client, "memory-interest-topic@example.com", "Memory Topic Interest")
    workspace_id = user_info["workspace"]["id"]
    project = create_project(client, "Memory Topic Interest Project")
    conversation_id = create_conversation_record(
        workspace_id,
        project["id"],
        user_info["user"]["id"],
        "Memory Topic Interest Conversation",
    )

    def create_turn(user_content: str) -> str:
        with SessionLocal() as db:
            user_message = Message(
                conversation_id=conversation_id,
                role="user",
                content=user_content,
                metadata_json={},
            )
            assistant_message = Message(
                conversation_id=conversation_id,
                role="assistant",
                content="我来讲讲。",
                metadata_json={},
            )
            db.add_all([user_message, assistant_message])
            db.commit()
            return assistant_message.id

    async def fake_extract_completion(*args, **kwargs):
        del args, kwargs
        return "[]"

    async def fake_find_duplicate(db, *args, **kwargs):
        del args
        fact_text = str(kwargs.get("text") or "")
        existing = (
            db.query(Memory)
            .filter(
                Memory.project_id == project["id"],
                Memory.content == fact_text,
            )
            .order_by(Memory.created_at.asc())
            .first()
        )
        if existing is not None:
            return {"memory_id": existing.id}, [0.31, 0.52, 0.73]
        return None, [0.31, 0.52, 0.73]

    async def fake_find_related(*args, **kwargs):
        del args, kwargs
        return []

    async def fake_embed_and_store(*args, **kwargs):
        del args, kwargs
        return None

    async def fake_plan_concept_parent(*args, **kwargs):
        del args, kwargs
        return None

    monkeypatch.setattr(dashscope_client_module, "chat_completion", fake_extract_completion)
    monkeypatch.setattr(embedding_service, "find_duplicate_memory_with_vector", fake_find_duplicate)
    monkeypatch.setattr(embedding_service, "find_related_memories", fake_find_related)
    monkeypatch.setattr(embedding_service, "embed_and_store", fake_embed_and_store)
    monkeypatch.setattr(worker_tasks, "_plan_concept_parent", fake_plan_concept_parent)
    monkeypatch.setattr(worker_tasks, "compact_project_memories_task", lambda *args, **kwargs: None)
    monkeypatch.setattr(worker_tasks, "repair_project_memory_graph_task", lambda *args, **kwargs: None)

    first_assistant_id = create_turn("你能介绍一下比那名居天子这个角色吗？")
    worker_tasks.extract_memories(
        workspace_id,
        project["id"],
        conversation_id,
        "你能介绍一下比那名居天子这个角色吗？",
        "我来讲讲。",
        first_assistant_id,
    )

    with SessionLocal() as db:
        first_assistant = db.get(Message, first_assistant_id)
        assert first_assistant is not None
        assert (first_assistant.metadata_json or {}).get("extracted_facts") == []
        assert (
            db.query(Memory)
            .filter(
                Memory.project_id == project["id"],
                Memory.content == "用户对比那名居天子感兴趣。",
            )
            .first()
            is None
        )

    second_assistant_id = create_turn("比那名居天子的设定为什么这么特别？")
    worker_tasks.extract_memories(
        workspace_id,
        project["id"],
        conversation_id,
        "比那名居天子的设定为什么这么特别？",
        "我来讲讲。",
        second_assistant_id,
    )

    with SessionLocal() as db:
        subject_memory = (
            db.query(Memory)
            .filter(
                Memory.project_id == project["id"],
                Memory.node_type == "subject",
                Memory.content == "比那名居天子",
            )
            .first()
        )
        interest_memory = (
            db.query(Memory)
            .filter(
                Memory.project_id == project["id"],
                Memory.content == "用户对比那名居天子感兴趣。",
            )
            .first()
        )
        second_assistant = db.get(Message, second_assistant_id)
        assert subject_memory is not None
        assert interest_memory is not None
        assert interest_memory.type == "temporary"
        assert interest_memory.parent_memory_id == subject_memory.id
        metadata = second_assistant.metadata_json or {}
        extracted_facts = metadata.get("extracted_facts")
        assert isinstance(extracted_facts, list)
        assert extracted_facts[0]["fact"] == "用户对比那名居天子感兴趣。"
        assert extracted_facts[0]["status"] == "temporary"
        assert "连续 2 轮" in extracted_facts[0]["triage_reason"]
        temporary_interest_id = interest_memory.id

    third_assistant_id = create_turn("再讲讲比那名居天子的能力和背景。")
    worker_tasks.extract_memories(
        workspace_id,
        project["id"],
        conversation_id,
        "再讲讲比那名居天子的能力和背景。",
        "我来讲讲。",
        third_assistant_id,
    )

    with SessionLocal() as db:
        interest_memory = (
            db.query(Memory)
            .filter(
                Memory.project_id == project["id"],
                Memory.content == "用户对比那名居天子感兴趣。",
            )
            .first()
        )
        third_assistant = db.get(Message, third_assistant_id)
        assert interest_memory is not None
        assert interest_memory.id == temporary_interest_id
        assert interest_memory.type == "permanent"
        assert interest_memory.source_conversation_id is None
        assert (interest_memory.metadata_json or {}).get("source") == "behavioral_interest"
        metadata = third_assistant.metadata_json or {}
        extracted_facts = metadata.get("extracted_facts")
        assert isinstance(extracted_facts, list)
        assert extracted_facts[0]["status"] == "permanent"
        assert extracted_facts[0]["triage_action"] == "promote"
        assert "升级为永久记忆" in extracted_facts[0]["triage_reason"]


def test_extract_subject_hint_ignores_deictic_placeholder_subjects() -> None:
    subject_label, subject_kind = worker_tasks._extract_subject_hint(
        text="这个角色放在东方里是不是特别离谱？",
        category="偏好.关注",
    )

    assert subject_label is None
    assert subject_kind is None


def test_extract_subject_hint_ignores_pronoun_based_subject_labels() -> None:
    subject_label, subject_kind = worker_tasks._extract_subject_hint(
        text="她的天人设定很有辨识度。",
        category="人物.设定",
    )

    assert subject_label is None
    assert subject_kind is None


def test_extract_subject_hint_supports_background_queries_with_intermediate_tokens() -> None:
    subject_label, subject_kind = worker_tasks._extract_subject_hint(
        text="还有比那名居天子的绯想剑和天人背景，你觉得最有意思的是哪块？",
        category="偏好.关注",
    )

    assert subject_label == "比那名居天子"
    assert subject_kind == "custom"


def test_extract_subject_hint_supports_soft_leadin_topic_queries() -> None:
    subject_label, subject_kind = worker_tasks._extract_subject_hint(
        text="最近突然又想聊芙兰朵露，这个角色为什么这么适合二创？",
        category="偏好.关注",
    )

    assert subject_label == "芙兰朵露"
    assert subject_kind == "custom"


def test_deictic_subject_reference_recognizes_topic_attributes() -> None:
    assert worker_tasks._is_deictic_subject_reference("这个人设为什么总让人记住？") is True
    assert worker_tasks._is_deictic_subject_reference("这个设定放在东方里是不是特别离谱？") is True


def test_extract_memories_reuses_near_duplicate_concept_topics(monkeypatch) -> None:
    import app.services.dashscope_client as dashscope_client_module
    import app.services.embedding as embedding_service

    client = TestClient(main_module.app)
    user_info = register_user(client, "memory-concept-reuse@example.com", "Memory Concept Reuse")
    workspace_id = user_info["workspace"]["id"]
    project = create_project(client, "Memory Concept Reuse Project")
    conversation_id = create_conversation_record(
        workspace_id,
        project["id"],
        user_info["user"]["id"],
        "Memory Concept Reuse Conversation",
    )

    with SessionLocal() as db:
        assistant_message = Message(
            conversation_id=conversation_id,
            role="assistant",
            content="这条消息稍后会展示记忆变更。",
            metadata_json={},
        )
        db.add(assistant_message)
        db.commit()
        assistant_message_id = assistant_message.id

    async def fake_extract_completion(*args, **kwargs):
        del args, kwargs
        return json.dumps(
            [
                {
                    "fact": "用户喜欢冷萃咖啡",
                    "category": "饮食.偏好",
                    "importance": 0.8,
                },
                {
                    "fact": "用户喜欢冰美式",
                    "category": "饮食.偏好",
                    "importance": 0.8,
                },
            ],
            ensure_ascii=False,
        )

    async def fake_find_duplicate(*args, **kwargs):
        del args, kwargs
        return None, [0.11, 0.22, 0.33]

    async def fake_find_related(*args, **kwargs):
        del args, kwargs
        return []

    async def fake_embed_and_store(*args, **kwargs):
        del args, kwargs
        return None

    async def fake_plan_concept_parent(*args, **kwargs):
        fact_text = kwargs.get("fact_text", "")
        if "冷萃" in fact_text:
            return {
                "topic": "咖啡饮品",
                "parent_text": "用户对咖啡饮品感兴趣",
                "parent_category": "饮食.偏好.咖啡饮品",
                "reason": "冷萃咖啡属于咖啡饮品。",
            }
        return {
            "topic": "咖啡",
            "parent_text": "用户对咖啡感兴趣",
            "parent_category": "饮食.偏好.咖啡",
            "reason": "冰美式属于咖啡。",
        }

    monkeypatch.setattr(dashscope_client_module, "chat_completion", fake_extract_completion)
    monkeypatch.setattr(embedding_service, "find_duplicate_memory_with_vector", fake_find_duplicate)
    monkeypatch.setattr(embedding_service, "find_related_memories", fake_find_related)
    monkeypatch.setattr(embedding_service, "embed_and_store", fake_embed_and_store)
    monkeypatch.setattr(worker_tasks, "_plan_concept_parent", fake_plan_concept_parent)
    monkeypatch.setattr(worker_tasks, "compact_project_memories_task", lambda *args, **kwargs: None)

    worker_tasks.extract_memories(
        workspace_id,
        project["id"],
        conversation_id,
        "我喜欢冷萃咖啡，也喜欢冰美式。",
        "已记住。",
        assistant_message_id,
    )

    with SessionLocal() as db:
        concept_memories = (
            db.query(Memory)
            .filter(
                Memory.project_id == project["id"],
                Memory.type == "permanent",
            )
            .all()
        )
        concept_nodes = [memory for memory in concept_memories if (memory.metadata_json or {}).get("node_kind") == "concept"]
        child_nodes = (
            db.query(Memory)
            .filter(
                Memory.project_id == project["id"],
                Memory.parent_memory_id == concept_nodes[0].id,
            )
            .all()
            if concept_nodes
            else []
        )
        assert len(concept_nodes) == 1
        assert concept_nodes[0].content == "用户对咖啡感兴趣"
        assert len(child_nodes) == 2


def test_extract_memories_groups_non_user_fact_under_generated_concept(monkeypatch) -> None:
    import app.services.dashscope_client as dashscope_client_module
    import app.services.embedding as embedding_service

    client = TestClient(main_module.app)
    user_info = register_user(client, "memory-fact-concept@example.com", "Memory Fact Concept")
    workspace_id = user_info["workspace"]["id"]
    project = create_project(client, "Memory Fact Concept Project")
    conversation_id = create_conversation_record(
        workspace_id,
        project["id"],
        user_info["user"]["id"],
        "Memory Fact Concept Conversation",
    )

    with SessionLocal() as db:
        assistant_message = Message(
            conversation_id=conversation_id,
            role="assistant",
            content="这条消息稍后会展示记忆变更。",
            metadata_json={},
        )
        db.add(assistant_message)
        db.commit()
        assistant_message_id = assistant_message.id

    async def fake_extract_completion(*args, **kwargs):
        del args, kwargs
        return json.dumps(
            [
                {
                    "fact": "比那名居天子的天人设定很有辨识度。",
                    "category": "人物.设定",
                    "importance": 0.95,
                }
            ],
            ensure_ascii=False,
        )

    async def fake_find_duplicate(*args, **kwargs):
        del args, kwargs
        return None, [0.21, 0.43, 0.65]

    async def fake_find_related(*args, **kwargs):
        del args, kwargs
        return []

    async def fake_embed_and_store(*args, **kwargs):
        del args, kwargs
        return None

    monkeypatch.setattr(dashscope_client_module, "chat_completion", fake_extract_completion)
    monkeypatch.setattr(embedding_service, "find_duplicate_memory_with_vector", fake_find_duplicate)
    monkeypatch.setattr(embedding_service, "find_related_memories", fake_find_related)
    monkeypatch.setattr(embedding_service, "embed_and_store", fake_embed_and_store)
    monkeypatch.setattr(worker_tasks, "compact_project_memories_task", lambda *args, **kwargs: None)
    monkeypatch.setattr(worker_tasks, "repair_project_memory_graph_task", lambda *args, **kwargs: None)

    worker_tasks.extract_memories(
        workspace_id,
        project["id"],
        conversation_id,
        "比那名居天子的天人设定很有辨识度。",
        "已记住。",
        assistant_message_id,
    )

    with SessionLocal() as db:
        subject_memory = (
            db.query(Memory)
            .filter(
                Memory.project_id == project["id"],
                Memory.node_type == "subject",
                Memory.content == "比那名居天子",
            )
            .first()
        )
        concept_memory = (
            db.query(Memory)
            .filter(
                Memory.project_id == project["id"],
                Memory.content == "角色设定",
            )
            .first()
        )
        child_memory = (
            db.query(Memory)
            .filter(
                Memory.project_id == project["id"],
                Memory.content == "比那名居天子的天人设定很有辨识度。",
            )
            .first()
        )
        assistant_message = db.get(Message, assistant_message_id)

        assert subject_memory is not None
        assert concept_memory is not None
        assert child_memory is not None
        assert concept_memory.parent_memory_id == subject_memory.id
        assert child_memory.parent_memory_id == concept_memory.id
        assert (concept_memory.metadata_json or {}).get("node_kind") == "concept"
        assert (concept_memory.metadata_json or {}).get("memory_kind") == "fact"

        metadata = assistant_message.metadata_json or {}
        extracted_facts = metadata.get("extracted_facts")
        assert isinstance(extracted_facts, list)
        assert "角色设定" in extracted_facts[0]["triage_reason"]
        assert metadata["memories_extracted"] == "新增永久记忆 1 条；新增主题节点 1 条"


def test_extract_memories_groups_user_fact_under_structural_concept(monkeypatch) -> None:
    import app.services.dashscope_client as dashscope_client_module
    import app.services.embedding as embedding_service

    client = TestClient(main_module.app)
    user_info = register_user(client, "memory-user-fact-concept@example.com", "Memory User Fact Concept")
    workspace_id = user_info["workspace"]["id"]
    project = create_project(client, "Memory User Fact Concept Project")
    conversation_id = create_conversation_record(
        workspace_id,
        project["id"],
        user_info["user"]["id"],
        "Memory User Fact Concept Conversation",
    )

    with SessionLocal() as db:
        assistant_message = Message(
            conversation_id=conversation_id,
            role="assistant",
            content="这条消息稍后会展示记忆变更。",
            metadata_json={},
        )
        db.add(assistant_message)
        db.commit()
        assistant_message_id = assistant_message.id

    async def fake_extract_completion(*args, **kwargs):
        del args, kwargs
        return json.dumps(
            [
                {
                    "fact": "用户现在是大一学生。",
                    "category": "教育.学业阶段",
                    "importance": 0.95,
                }
            ],
            ensure_ascii=False,
        )

    async def fake_find_duplicate(*args, **kwargs):
        del args, kwargs
        return None, [0.21, 0.43, 0.65]

    async def fake_find_related(*args, **kwargs):
        del args, kwargs
        return []

    async def fake_embed_and_store(*args, **kwargs):
        del args, kwargs
        return None

    monkeypatch.setattr(dashscope_client_module, "chat_completion", fake_extract_completion)
    monkeypatch.setattr(embedding_service, "find_duplicate_memory_with_vector", fake_find_duplicate)
    monkeypatch.setattr(embedding_service, "find_related_memories", fake_find_related)
    monkeypatch.setattr(embedding_service, "embed_and_store", fake_embed_and_store)
    monkeypatch.setattr(worker_tasks, "compact_project_memories_task", lambda *args, **kwargs: None)
    monkeypatch.setattr(worker_tasks, "repair_project_memory_graph_task", lambda *args, **kwargs: None)

    worker_tasks.extract_memories(
        workspace_id,
        project["id"],
        conversation_id,
        "我现在是大一学生。",
        "已记住。",
        assistant_message_id,
    )

    with SessionLocal() as db:
        subject_memory = (
            db.query(Memory)
            .filter(
                Memory.project_id == project["id"],
                Memory.node_type == "subject",
                Memory.content == "用户",
            )
            .first()
        )
        concept_memory = (
            db.query(Memory)
            .filter(
                Memory.project_id == project["id"],
                Memory.content == "教育背景",
            )
            .first()
        )
        child_memory = (
            db.query(Memory)
            .filter(
                Memory.project_id == project["id"],
                Memory.content == "用户现在是大一学生。",
            )
            .first()
        )
        assistant_message = db.get(Message, assistant_message_id)

        assert subject_memory is not None
        assert concept_memory is not None
        assert child_memory is not None
        assert concept_memory.parent_memory_id == subject_memory.id
        assert child_memory.parent_memory_id == concept_memory.id
        assert (concept_memory.metadata_json or {}).get("node_kind") == "concept"
        assert (concept_memory.metadata_json or {}).get("memory_kind") == "fact"

        metadata = assistant_message.metadata_json or {}
        extracted_facts = metadata.get("extracted_facts")
        assert isinstance(extracted_facts, list)
        assert "教育背景" in extracted_facts[0]["triage_reason"]
        assert metadata["memories_extracted"] == "新增永久记忆 1 条；新增主题节点 1 条"


def test_extract_memories_reuses_existing_user_fact_concept(monkeypatch) -> None:
    import app.services.dashscope_client as dashscope_client_module
    import app.services.embedding as embedding_service

    client = TestClient(main_module.app)
    user_info = register_user(client, "memory-user-fact-concept-reuse@example.com", "Memory User Fact Concept Reuse")
    workspace_id = user_info["workspace"]["id"]
    project = create_project(client, "Memory User Fact Concept Reuse Project")
    conversation_id = create_conversation_record(
        workspace_id,
        project["id"],
        user_info["user"]["id"],
        "Memory User Fact Concept Reuse Conversation",
    )

    with SessionLocal() as db:
        project_row = db.get(Project, project["id"])
        assert project_row is not None
        subject, _ = ensure_project_user_subject(
            db,
            project_row,
            owner_user_id=user_info["user"]["id"],
        )
        concept_metadata = memory_metadata_service.normalize_memory_metadata(
            content="教育",
            category="教育",
            memory_type="permanent",
            metadata={
                "node_kind": "concept",
                "node_type": "concept",
                "node_status": "active",
                "subject_memory_id": subject.id,
                "concept_topic": "教育",
                "auto_generated": True,
                "source": "auto_concept_parent",
            },
        )
        concept = Memory(
            workspace_id=workspace_id,
            project_id=project["id"],
            content="教育",
            category="教育",
            type="permanent",
            node_type="concept",
            parent_memory_id=subject.id,
            subject_memory_id=subject.id,
            node_status="active",
            canonical_key=str(concept_metadata.get("canonical_key") or "").strip() or None,
            metadata_json=concept_metadata,
        )
        assistant_message = Message(
            conversation_id=conversation_id,
            role="assistant",
            content="这条消息稍后会展示记忆变更。",
            metadata_json={},
        )
        db.add_all([concept, assistant_message])
        db.commit()
        concept_id = concept.id
        assistant_message_id = assistant_message.id

    async def fake_extract_completion(*args, **kwargs):
        del args, kwargs
        return json.dumps(
            [
                {
                    "fact": "用户在英国的帝国理工学院学习物理",
                    "category": "教育.学校",
                    "importance": 0.9,
                }
            ],
            ensure_ascii=False,
        )

    async def fake_find_duplicate(*args, **kwargs):
        del args, kwargs
        return None, [0.21, 0.43, 0.65]

    async def fake_find_related(*args, **kwargs):
        del args, kwargs
        return []

    async def fake_embed_and_store(*args, **kwargs):
        del args, kwargs
        return None

    monkeypatch.setattr(dashscope_client_module, "chat_completion", fake_extract_completion)
    monkeypatch.setattr(embedding_service, "find_duplicate_memory_with_vector", fake_find_duplicate)
    monkeypatch.setattr(embedding_service, "find_related_memories", fake_find_related)
    monkeypatch.setattr(embedding_service, "embed_and_store", fake_embed_and_store)
    monkeypatch.setattr(worker_tasks, "compact_project_memories_task", lambda *args, **kwargs: None)
    monkeypatch.setattr(worker_tasks, "repair_project_memory_graph_task", lambda *args, **kwargs: None)

    worker_tasks.extract_memories(
        workspace_id,
        project["id"],
        conversation_id,
        "我在英国的帝国理工学院学习物理。",
        "已记住。",
        assistant_message_id,
    )

    with SessionLocal() as db:
        concept = db.get(Memory, concept_id)
        child_memory = (
            db.query(Memory)
            .filter(
                Memory.project_id == project["id"],
                Memory.content == "用户在英国的帝国理工学院学习物理",
            )
            .first()
        )
        concept_nodes = (
            db.query(Memory)
            .filter(
                Memory.project_id == project["id"],
                Memory.node_type == "concept",
                Memory.subject_memory_id == concept.subject_memory_id,
            )
            .all()
        )
        assistant_message = db.get(Message, assistant_message_id)
        assert concept is not None
        assert child_memory is not None
        assert child_memory.parent_memory_id == concept.id
        assert concept.parent_memory_id != concept.id
        assert len(concept_nodes) == 1
        assert concept.content == "教育背景"
        assert (concept.metadata_json or {}).get("concept_label") == "教育背景"
        metadata = assistant_message.metadata_json or {}
        extracted_facts = metadata.get("extracted_facts")
        assert isinstance(extracted_facts, list)
        assert extracted_facts[0]["parent_memory_id"] == concept.id
        assert extracted_facts[0]["parent_memory_content"] == "教育背景"
        assert metadata["memories_extracted"] == "新增永久记忆 1 条"


def test_extract_memories_reuses_fact_concept_for_pronoun_follow_up(monkeypatch) -> None:
    import app.services.dashscope_client as dashscope_client_module
    import app.services.embedding as embedding_service

    client = TestClient(main_module.app)
    user_info = register_user(client, "memory-fact-concept-followup@example.com", "Memory Fact Concept Followup")
    workspace_id = user_info["workspace"]["id"]
    project = create_project(client, "Memory Fact Concept Followup Project")
    conversation_id = create_conversation_record(
        workspace_id,
        project["id"],
        user_info["user"]["id"],
        "Memory Fact Concept Followup Conversation",
    )

    def create_turn(user_content: str, assistant_content: str) -> str:
        with SessionLocal() as db:
            user_message = Message(
                conversation_id=conversation_id,
                role="user",
                content=user_content,
                metadata_json={},
            )
            assistant_message = Message(
                conversation_id=conversation_id,
                role="assistant",
                content=assistant_content,
                metadata_json={},
            )
            db.add_all([user_message, assistant_message])
            db.commit()
            return assistant_message.id

    responses = {
        "比那名居天子的天人设定很有辨识度。": [
            {
                "fact": "比那名居天子的天人设定很有辨识度。",
                "category": "人物.设定",
                "importance": 0.95,
            }
        ],
        "她的战斗设定也很有辨识度。": [
            {
                "fact": "她的战斗设定也很有辨识度。",
                "category": "人物.设定",
                "importance": 0.95,
            }
        ],
    }

    async def fake_extract_completion(messages, *args, **kwargs):
        del args, kwargs
        prompt = messages[0]["content"]
        for user_message, payload in reversed(tuple(responses.items())):
            if user_message in prompt:
                return json.dumps(payload, ensure_ascii=False)
        return "[]"

    async def fake_find_duplicate(*args, **kwargs):
        del args, kwargs
        return None, [0.19, 0.27, 0.42]

    async def fake_find_related(*args, **kwargs):
        del args, kwargs
        return []

    async def fake_embed_and_store(*args, **kwargs):
        del args, kwargs
        return None

    monkeypatch.setattr(dashscope_client_module, "chat_completion", fake_extract_completion)
    monkeypatch.setattr(embedding_service, "find_duplicate_memory_with_vector", fake_find_duplicate)
    monkeypatch.setattr(embedding_service, "find_related_memories", fake_find_related)
    monkeypatch.setattr(embedding_service, "embed_and_store", fake_embed_and_store)
    monkeypatch.setattr(worker_tasks, "compact_project_memories_task", lambda *args, **kwargs: None)
    monkeypatch.setattr(worker_tasks, "repair_project_memory_graph_task", lambda *args, **kwargs: None)

    first_assistant_id = create_turn("比那名居天子的天人设定很有辨识度。", "这点确实很鲜明。")
    worker_tasks.extract_memories(
        workspace_id,
        project["id"],
        conversation_id,
        "比那名居天子的天人设定很有辨识度。",
        "这点确实很鲜明。",
        first_assistant_id,
    )

    with SessionLocal() as db:
        subject_memory = (
            db.query(Memory)
            .filter(
                Memory.project_id == project["id"],
                Memory.node_type == "subject",
                Memory.content == "比那名居天子",
            )
            .first()
        )
        conversation = db.get(Conversation, conversation_id)
        assert subject_memory is not None
        assert conversation is not None
        conversation.metadata_json = {
            **(conversation.metadata_json or {}),
            "primary_subject_id": subject_memory.id,
            "active_subject_ids": [subject_memory.id],
        }
        db.commit()

    second_assistant_id = create_turn("她的战斗设定也很有辨识度。", "这种风格也很强。")
    worker_tasks.extract_memories(
        workspace_id,
        project["id"],
        conversation_id,
        "她的战斗设定也很有辨识度。",
        "这种风格也很强。",
        second_assistant_id,
    )

    with SessionLocal() as db:
        subject_memory = (
            db.query(Memory)
            .filter(
                Memory.project_id == project["id"],
                Memory.node_type == "subject",
                Memory.content == "比那名居天子",
            )
            .first()
        )
        assert subject_memory is not None
        concept_memories = (
            db.query(Memory)
            .filter(
                Memory.project_id == project["id"],
                Memory.content == "角色设定",
            )
            .all()
        )
        fact_memories = (
            db.query(Memory)
            .filter(
                Memory.project_id == project["id"],
                Memory.node_type == "fact",
                Memory.subject_memory_id == subject_memory.id,
            )
            .order_by(Memory.created_at.asc())
            .all()
        )
        second_assistant = db.get(Message, second_assistant_id)

        assert len(concept_memories) == 1
        assert len(fact_memories) == 2
        assert all(memory.parent_memory_id == concept_memories[0].id for memory in fact_memories)
        assert fact_memories[1].content == "比那名居天子的战斗设定也很有辨识度。"

        metadata = second_assistant.metadata_json or {}
        extracted_facts = metadata.get("extracted_facts")
        assert isinstance(extracted_facts, list)
        assert extracted_facts[0]["fact"] == "比那名居天子的战斗设定也很有辨识度。"
        assert "归入主题「角色设定」" in extracted_facts[0]["triage_reason"]


def test_upsert_auto_memory_edge_deduplicates_pending_edges() -> None:
    client = TestClient(main_module.app)
    user_info = register_user(client, "memory-edge-dedupe@example.com", "Memory Edge Dedupe")
    workspace_id = user_info["workspace"]["id"]
    project = create_project(client, "Memory Edge Dedupe Project")

    with SessionLocal() as db:
        root = Memory(
            workspace_id=workspace_id,
            project_id=project["id"],
            content="root",
            category="assistant",
            type="permanent",
            metadata_json={"node_kind": "assistant-root"},
        )
        child = Memory(
            workspace_id=workspace_id,
            project_id=project["id"],
            content="child",
            category="偏好",
            type="permanent",
            metadata_json={"memory_kind": "preference"},
        )
        db.add_all([root, child])
        db.flush()

        worker_tasks._upsert_auto_memory_edge(
            db,
            source_memory_id=root.id,
            target_memory_id=child.id,
            strength=0.65,
        )
        worker_tasks._upsert_auto_memory_edge(
            db,
            source_memory_id=root.id,
            target_memory_id=child.id,
            strength=0.84,
        )
        db.flush()

        edges = (
            db.query(MemoryEdge)
            .filter(
                MemoryEdge.source_memory_id == root.id,
                MemoryEdge.target_memory_id == child.id,
            )
            .all()
        )
        assert len(edges) == 1
        assert float(edges[0].strength) == 0.84


def test_extract_memories_converts_append_siblings_into_shared_concept_parent(monkeypatch) -> None:
    import app.services.dashscope_client as dashscope_client_module
    import app.services.embedding as embedding_service

    client = TestClient(main_module.app)
    user_info = register_user(client, "memory-concept-siblings@example.com", "Memory Concept Siblings")
    workspace_id = user_info["workspace"]["id"]
    project = create_project(client, "Memory Concept Siblings Project")
    conversation_id = create_conversation_record(
        workspace_id,
        project["id"],
        user_info["user"]["id"],
        "Memory Concept Siblings Conversation",
    )

    with SessionLocal() as db:
        existing_memory = Memory(
            workspace_id=workspace_id,
            project_id=project["id"],
            content="用户喜欢喝冰美式。",
            category="饮食.偏好",
            type="permanent",
            metadata_json={"memory_kind": "preference"},
        )
        assistant_message = Message(
            conversation_id=conversation_id,
            role="assistant",
            content="这条消息稍后会展示记忆变更。",
            metadata_json={},
        )
        db.add(existing_memory)
        db.add(assistant_message)
        db.commit()
        existing_memory_id = existing_memory.id
        assistant_message_id = assistant_message.id

    async def fake_extract_completion(*args, **kwargs):
        del args, kwargs
        return json.dumps(
            [
                {
                    "fact": "用户喜欢手冲咖啡。",
                    "category": "饮食.偏好",
                    "importance": 0.95,
                }
            ],
            ensure_ascii=False,
        )

    async def fake_find_duplicate(*args, **kwargs):
        del args, kwargs
        return None, [0.31, 0.52, 0.73]

    async def fake_find_related(*args, **kwargs):
        del args, kwargs
        return [
            {
                "memory_id": existing_memory_id,
                "category": "饮食.偏好",
                "content": "用户喜欢喝冰美式。",
            }
        ]

    async def fake_triage(*args, **kwargs):
        del args, kwargs
        return {
            "action": "append",
            "target_memory_id": existing_memory_id,
            "merged_content": None,
            "reason": "同属咖啡偏好。",
        }

    async def fake_validate_append_parent(*args, **kwargs):
        del args, kwargs
        return {
            "relation": "sibling",
            "reason": "两条记忆是同一主题下的并列偏好，不应形成父子链。",
        }

    async def fake_plan_concept_parent(*args, **kwargs):
        del args, kwargs
        return {
            "topic": "咖啡",
            "parent_text": "用户对咖啡感兴趣",
            "parent_category": "饮食.偏好.咖啡",
            "reason": "两条偏好都稳定归属于咖啡主题。",
        }

    async def fake_embed_and_store(*args, **kwargs):
        del args, kwargs
        return None

    monkeypatch.setattr(dashscope_client_module, "chat_completion", fake_extract_completion)
    monkeypatch.setattr(embedding_service, "find_duplicate_memory_with_vector", fake_find_duplicate)
    monkeypatch.setattr(embedding_service, "find_related_memories", fake_find_related)
    monkeypatch.setattr(embedding_service, "embed_and_store", fake_embed_and_store)
    monkeypatch.setattr(worker_tasks, "triage_memory", fake_triage)
    monkeypatch.setattr(worker_tasks, "_validate_append_parent", fake_validate_append_parent)
    monkeypatch.setattr(worker_tasks, "_plan_concept_parent", fake_plan_concept_parent)
    monkeypatch.setattr(worker_tasks, "compact_project_memories_task", lambda *args, **kwargs: None)

    worker_tasks.extract_memories(
        workspace_id,
        project["id"],
        conversation_id,
        "请记住我喜欢手冲咖啡。",
        "已记住。",
        assistant_message_id,
    )

    with SessionLocal() as db:
        concept_memory = (
            db.query(Memory)
            .filter(
                Memory.project_id == project["id"],
                Memory.content == "用户对咖啡感兴趣",
            )
            .first()
        )
        existing_memory = db.get(Memory, existing_memory_id)
        new_memory = (
            db.query(Memory)
            .filter(
                Memory.project_id == project["id"],
                Memory.content == "用户喜欢手冲咖啡。",
            )
            .first()
        )
        assistant_message = db.get(Message, assistant_message_id)
        assert concept_memory is not None
        assert existing_memory is not None
        assert new_memory is not None
        assert existing_memory.parent_memory_id == concept_memory.id
        assert new_memory.parent_memory_id == concept_memory.id

        metadata = assistant_message.metadata_json or {}
        extracted_facts = metadata.get("extracted_facts")
        assert isinstance(extracted_facts, list)
        assert "并列偏好" in extracted_facts[0]["triage_reason"]
        assert "用户对咖啡感兴趣" in extracted_facts[0]["triage_reason"]


def test_repair_project_memory_graph_deletes_aggregate_nodes_and_repairs_auto_edges() -> None:
    client = TestClient(main_module.app)
    user_info = register_user(client, "memory-repair@example.com", "Memory Repair")
    workspace_id = user_info["workspace"]["id"]
    project = create_project(client, "Memory Repair Project")

    with SessionLocal() as db:
        project_row = db.get(Project, project["id"])
        assert project_row is not None
        root_memory, _ = ensure_project_assistant_root(db, project_row, reparent_orphans=False)
        concept_memory = Memory(
            workspace_id=workspace_id,
            project_id=project["id"],
            content="用户对咖啡感兴趣",
            category="饮食.偏好.咖啡",
            type="permanent",
            parent_memory_id=root_memory.id,
            metadata_json={"memory_kind": "preference", "node_kind": "concept", "auto_generated": True},
        )
        leaf_memory = Memory(
            workspace_id=workspace_id,
            project_id=project["id"],
            content="用户喜欢喝冰美式。",
            category="饮食.偏好",
            type="permanent",
            parent_memory_id=None,
            metadata_json={"memory_kind": "preference", "source": "auto_extraction"},
        )
        child_memory = Memory(
            workspace_id=workspace_id,
            project_id=project["id"],
            content="用户喜欢冷萃咖啡。",
            category="饮食.偏好",
            type="permanent",
            parent_memory_id=None,
            metadata_json={"memory_kind": "preference", "source": "auto_extraction"},
        )
        aggregate_memory = Memory(
            workspace_id=workspace_id,
            project_id=project["id"],
            content="用户偏好手冲咖啡、冰美式和冷萃咖啡。",
            category="饮食.饮品偏好",
            type="permanent",
            parent_memory_id=root_memory.id,
            metadata_json={"memory_kind": "preference", "source": "auto_extraction"},
        )
        db.add_all([concept_memory, leaf_memory, child_memory, aggregate_memory])
        db.flush()
        leaf_memory.parent_memory_id = concept_memory.id
        child_memory.parent_memory_id = leaf_memory.id
        db.add(
            MemoryEdge(
                source_memory_id=concept_memory.id,
                target_memory_id=leaf_memory.id,
                edge_type="auto",
                strength=0.8,
            )
        )
        db.add(
            MemoryEdge(
                source_memory_id=leaf_memory.id,
                target_memory_id=child_memory.id,
                edge_type="auto",
                strength=0.72,
            )
        )
        db.commit()
        child_memory_id = child_memory.id
        aggregate_memory_id = aggregate_memory.id
        concept_memory_id = concept_memory.id
        leaf_memory_id = leaf_memory.id

        summary = memory_graph_repair_service.repair_project_memory_graph(
            db,
            workspace_id=workspace_id,
            project_id=project["id"],
        )
        db.commit()

        repaired_child = db.get(Memory, child_memory_id)
        deleted_aggregate = db.get(Memory, aggregate_memory_id)
        assert repaired_child is not None
        assert repaired_child.parent_memory_id == concept_memory_id
        assert deleted_aggregate is None
        assert summary.deleted_aggregate_nodes == 1
        assert summary.reparented_nodes >= 1

        concept_child_edge = (
            db.query(MemoryEdge)
            .filter(
                MemoryEdge.source_memory_id == concept_memory_id,
                MemoryEdge.target_memory_id == child_memory_id,
                MemoryEdge.edge_type == "auto",
            )
            .first()
        )
        stale_leaf_edge = (
            db.query(MemoryEdge)
            .filter(
                MemoryEdge.source_memory_id == leaf_memory_id,
                MemoryEdge.target_memory_id == child_memory_id,
                MemoryEdge.edge_type == "auto",
            )
            .first()
        )
        assert concept_child_edge is not None
        assert stale_leaf_edge is None


def test_repair_project_memory_graph_deletes_legacy_primary_nodes() -> None:
    client = TestClient(main_module.app)
    user_info = register_user(client, "memory-legacy-repair@example.com", "Legacy Repair")
    workspace_id = user_info["workspace"]["id"]
    project = create_project(client, "Legacy Repair Project")

    with SessionLocal() as db:
        project_row = db.get(Project, project["id"])
        assert project_row is not None
        root_memory, _ = ensure_project_assistant_root(db, project_row, reparent_orphans=False)
        subject = Memory(
            workspace_id=workspace_id,
            project_id=project["id"],
            content="用户",
            category="user",
            type="permanent",
            node_type="subject",
            subject_kind="user",
            parent_memory_id=root_memory.id,
            metadata_json={"node_type": "subject", "node_kind": "subject", "subject_kind": "user"},
        )
        category_path = Memory(
            workspace_id=workspace_id,
            project_id=project["id"],
            content="旅行限制",
            category="出行.限制",
            type="permanent",
            parent_memory_id=root_memory.id,
            metadata_json={
                "node_type": "concept",
                "node_kind": "category-path",
                "concept_source": "category_path",
                "structural_only": True,
            },
        )
        summary_node = Memory(
            workspace_id=workspace_id,
            project_id=project["id"],
            content="用户近期旅行偏好摘要",
            category="出行.限制",
            type="permanent",
            parent_memory_id=root_memory.id,
            metadata_json={"memory_kind": "summary", "node_kind": "summary"},
        )
        db.add_all([subject, category_path, summary_node])
        db.flush()

        category_fact = Memory(
            workspace_id=workspace_id,
            project_id=project["id"],
            content="用户不喜欢红眼航班。",
            category="出行.限制",
            type="permanent",
            parent_memory_id=category_path.id,
            subject_memory_id=subject.id,
            metadata_json={"node_type": "fact", "subject_memory_id": subject.id, "source": "auto_extraction"},
        )
        summary_fact = Memory(
            workspace_id=workspace_id,
            project_id=project["id"],
            content="用户更偏好白天出发。",
            category="出行.限制",
            type="permanent",
            parent_memory_id=summary_node.id,
            subject_memory_id=subject.id,
            metadata_json={"node_type": "fact", "subject_memory_id": subject.id, "source": "auto_extraction"},
        )
        db.add_all([category_fact, summary_fact])
        db.flush()
        category_path_id = category_path.id
        summary_node_id = summary_node.id
        category_fact_id = category_fact.id
        summary_fact_id = summary_fact.id
        db.commit()

        summary = memory_graph_repair_service.repair_project_memory_graph(
            db,
            workspace_id=workspace_id,
            project_id=project["id"],
        )
        db.commit()

        assert db.get(Memory, category_path_id) is None
        assert db.get(Memory, summary_node_id) is None
        repaired_category_fact = db.get(Memory, category_fact_id)
        repaired_summary_fact = db.get(Memory, summary_fact_id)
        assert repaired_category_fact is not None
        assert repaired_summary_fact is not None
        assert repaired_category_fact.parent_memory_id == subject.id
        assert repaired_summary_fact.parent_memory_id == subject.id
        assert summary.deleted_legacy_nodes == 2


def test_repair_project_memory_graph_backfills_concepts_for_non_user_fact_leaves() -> None:
    client = TestClient(main_module.app)
    user_info = register_user(client, "memory-repair-concept-backfill@example.com", "Repair Concept Backfill")
    workspace_id = user_info["workspace"]["id"]
    project = create_project(client, "Repair Concept Backfill Project")

    with SessionLocal() as db:
        project_row = db.get(Project, project["id"])
        assert project_row is not None
        ensure_project_assistant_root(db, project_row, reparent_orphans=False)
        subject, _ = ensure_project_subject(
            db,
            project_row,
            subject_kind="person",
            label="比那名居天子",
            owner_user_id=user_info["user"]["id"],
        )

        def _fact(content: str, category: str) -> Memory:
            metadata = memory_metadata_service.normalize_memory_metadata(
                content=content,
                category=category,
                memory_type="permanent",
                metadata={
                    "node_type": "fact",
                    "node_status": "active",
                    "subject_memory_id": subject.id,
                    "source": "auto_extraction",
                },
            )
            return Memory(
                workspace_id=workspace_id,
                project_id=project["id"],
                content=content,
                category=category,
                type="permanent",
                node_type="fact",
                parent_memory_id=subject.id,
                subject_memory_id=subject.id,
                node_status="active",
                canonical_key=str(metadata.get("canonical_key") or "").strip() or None,
                metadata_json=metadata,
            )

        first_fact = _fact("比那名居天子的天人设定很有辨识度。", "人物.设定")
        second_fact = _fact("比那名居天子的战斗设定也很有辨识度。", "人物.设定")
        db.add_all([first_fact, second_fact])
        db.commit()
        first_fact_id = first_fact.id
        second_fact_id = second_fact.id
        subject_id = subject.id

        summary = memory_graph_repair_service.repair_project_memory_graph(
            db,
            workspace_id=workspace_id,
            project_id=project["id"],
        )
        db.commit()

        concept_nodes = (
            db.query(Memory)
            .filter(
                Memory.project_id == project["id"],
                Memory.node_type == "concept",
                Memory.subject_memory_id == subject_id,
            )
            .all()
        )
        repaired_first = db.get(Memory, first_fact_id)
        repaired_second = db.get(Memory, second_fact_id)
        assert len(concept_nodes) == 1
        assert concept_nodes[0].content == "角色设定"
        assert concept_nodes[0].parent_memory_id == subject_id
        assert (concept_nodes[0].metadata_json or {}).get("source") == "repair_concept_backfill"
        assert (concept_nodes[0].metadata_json or {}).get("concept_topic") == "设定"
        assert (concept_nodes[0].metadata_json or {}).get("concept_label") == "角色设定"
        assert repaired_first is not None
        assert repaired_second is not None
        assert repaired_first.parent_memory_id == concept_nodes[0].id
        assert repaired_second.parent_memory_id == concept_nodes[0].id
        assert summary.created_concept_nodes == 1
        assert summary.reparented_nodes == 2

        subject_edge = (
            db.query(MemoryEdge)
            .filter(
                MemoryEdge.source_memory_id == subject_id,
                MemoryEdge.target_memory_id == concept_nodes[0].id,
                MemoryEdge.edge_type == "auto",
            )
            .first()
        )
        first_edge = (
            db.query(MemoryEdge)
            .filter(
                MemoryEdge.source_memory_id == concept_nodes[0].id,
                MemoryEdge.target_memory_id == first_fact_id,
                MemoryEdge.edge_type == "auto",
            )
            .first()
        )
        second_edge = (
            db.query(MemoryEdge)
            .filter(
                MemoryEdge.source_memory_id == concept_nodes[0].id,
                MemoryEdge.target_memory_id == second_fact_id,
                MemoryEdge.edge_type == "auto",
            )
            .first()
        )
        assert subject_edge is not None
        assert first_edge is not None
        assert second_edge is not None


def test_repair_project_memory_graph_backfills_structural_concepts_for_user_facts() -> None:
    client = TestClient(main_module.app)
    user_info = register_user(client, "memory-repair-user-education@example.com", "Repair User Education")
    workspace_id = user_info["workspace"]["id"]
    project = create_project(client, "Repair User Education Project")

    with SessionLocal() as db:
        project_row = db.get(Project, project["id"])
        assert project_row is not None
        ensure_project_assistant_root(db, project_row, reparent_orphans=False)
        subject, _ = ensure_project_user_subject(
            db,
            project_row,
            owner_user_id=user_info["user"]["id"],
        )
        metadata = memory_metadata_service.normalize_memory_metadata(
            content="用户现在是大一学生。",
            category="教育.学业阶段",
            memory_type="permanent",
            metadata={
                "node_type": "fact",
                "node_status": "active",
                "subject_memory_id": subject.id,
                "source": "auto_extraction",
            },
        )
        fact = Memory(
            workspace_id=workspace_id,
            project_id=project["id"],
            content="用户现在是大一学生。",
            category="教育.学业阶段",
            type="permanent",
            node_type="fact",
            parent_memory_id=subject.id,
            subject_memory_id=subject.id,
            node_status="active",
            canonical_key=str(metadata.get("canonical_key") or "").strip() or None,
            metadata_json=metadata,
        )
        db.add(fact)
        db.commit()
        fact_id = fact.id
        subject_id = subject.id

        summary = memory_graph_repair_service.repair_project_memory_graph(
            db,
            workspace_id=workspace_id,
            project_id=project["id"],
        )
        db.commit()

        repaired_fact = db.get(Memory, fact_id)
        concept_node = (
            db.query(Memory)
            .filter(
                Memory.project_id == project["id"],
                Memory.node_type == "concept",
                Memory.subject_memory_id == subject_id,
                Memory.content == "教育背景",
            )
            .first()
        )
        assert repaired_fact is not None
        assert concept_node is not None
        assert concept_node.parent_memory_id == subject_id
        assert repaired_fact.parent_memory_id == concept_node.id
        assert (concept_node.metadata_json or {}).get("source") == "repair_concept_backfill"
        assert (concept_node.metadata_json or {}).get("concept_topic") == "教育"
        assert (concept_node.metadata_json or {}).get("concept_label") == "教育背景"
        assert summary.created_concept_nodes == 1
        assert summary.reparented_nodes == 1


def test_repair_project_memory_graph_reuses_existing_user_concept_without_self_parenting() -> None:
    client = TestClient(main_module.app)
    user_info = register_user(client, "memory-repair-user-concept-reuse@example.com", "Repair User Concept Reuse")
    workspace_id = user_info["workspace"]["id"]
    project = create_project(client, "Repair User Concept Reuse Project")

    with SessionLocal() as db:
        project_row = db.get(Project, project["id"])
        assert project_row is not None
        ensure_project_assistant_root(db, project_row, reparent_orphans=False)
        subject, _ = ensure_project_user_subject(
            db,
            project_row,
            owner_user_id=user_info["user"]["id"],
        )

        concept_metadata = memory_metadata_service.normalize_memory_metadata(
            content="教育",
            category="教育",
            memory_type="permanent",
            metadata={
                "node_kind": "concept",
                "node_type": "concept",
                "node_status": "active",
                "subject_memory_id": subject.id,
                "concept_topic": "教育",
                "auto_generated": True,
                "source": "repair_concept_backfill",
            },
        )
        concept = Memory(
            workspace_id=workspace_id,
            project_id=project["id"],
            content="教育",
            category="教育",
            type="permanent",
            node_type="concept",
            parent_memory_id=subject.id,
            subject_memory_id=subject.id,
            node_status="active",
            canonical_key=str(concept_metadata.get("canonical_key") or "").strip() or None,
            metadata_json=concept_metadata,
        )

        fact_metadata = memory_metadata_service.normalize_memory_metadata(
            content="用户在英国的帝国理工学院学习物理",
            category="教育.学校",
            memory_type="permanent",
            metadata={
                "node_type": "fact",
                "node_status": "active",
                "subject_memory_id": subject.id,
                "source": "auto_extraction",
            },
        )
        fact = Memory(
            workspace_id=workspace_id,
            project_id=project["id"],
            content="用户在英国的帝国理工学院学习物理",
            category="教育.学校",
            type="permanent",
            node_type="fact",
            parent_memory_id=subject.id,
            subject_memory_id=subject.id,
            node_status="active",
            canonical_key=str(fact_metadata.get("canonical_key") or "").strip() or None,
            metadata_json=fact_metadata,
        )

        db.add_all([concept, fact])
        db.commit()
        concept_id = concept.id
        fact_id = fact.id
        subject_id = subject.id

        summary = memory_graph_repair_service.repair_project_memory_graph(
            db,
            workspace_id=workspace_id,
            project_id=project["id"],
        )
        db.commit()

        repaired_concept = db.get(Memory, concept_id)
        repaired_fact = db.get(Memory, fact_id)
        assert repaired_concept is not None
        assert repaired_fact is not None
        assert repaired_concept.content == "教育背景"
        assert repaired_concept.parent_memory_id == subject_id
        assert repaired_fact.parent_memory_id == concept_id
        assert summary.created_concept_nodes == 0
        assert summary.reparented_nodes == 1


def test_repair_project_memory_graph_merges_duplicate_concepts_by_topic() -> None:
    client = TestClient(main_module.app)
    user_info = register_user(client, "memory-repair-concept-dedupe@example.com", "Repair Concept Dedupe")
    workspace_id = user_info["workspace"]["id"]
    project = create_project(client, "Repair Concept Dedupe Project")

    with SessionLocal() as db:
        project_row = db.get(Project, project["id"])
        assert project_row is not None
        ensure_project_assistant_root(db, project_row, reparent_orphans=False)
        subject, _ = ensure_project_user_subject(
            db,
            project_row,
            owner_user_id=user_info["user"]["id"],
        )

        concept_a_metadata = memory_metadata_service.normalize_memory_metadata(
            content="教育",
            category="教育",
            memory_type="permanent",
            metadata={
                "node_kind": "concept",
                "node_type": "concept",
                "node_status": "active",
                "subject_memory_id": subject.id,
                "concept_topic": "教育",
                "auto_generated": True,
                "source": "auto_concept_parent",
            },
        )
        concept_a = Memory(
            workspace_id=workspace_id,
            project_id=project["id"],
            content="教育",
            category="教育",
            type="permanent",
            node_type="concept",
            parent_memory_id=subject.id,
            subject_memory_id=subject.id,
            node_status="active",
            canonical_key=str(concept_a_metadata.get("canonical_key") or "").strip() or None,
            metadata_json=concept_a_metadata,
        )

        concept_b_metadata = memory_metadata_service.normalize_memory_metadata(
            content="教育背景",
            category="教育",
            memory_type="permanent",
            metadata={
                "node_kind": "concept",
                "node_type": "concept",
                "node_status": "active",
                "subject_memory_id": subject.id,
                "concept_topic": "教育",
                "concept_label": "教育背景",
                "auto_generated": True,
                "source": "repair_concept_backfill",
            },
        )
        concept_b = Memory(
            workspace_id=workspace_id,
            project_id=project["id"],
            content="教育背景",
            category="教育",
            type="permanent",
            node_type="concept",
            parent_memory_id=subject.id,
            subject_memory_id=subject.id,
            node_status="active",
            canonical_key=str(concept_b_metadata.get("canonical_key") or "").strip() or None,
            metadata_json=concept_b_metadata,
        )

        fact_a_metadata = memory_metadata_service.normalize_memory_metadata(
            content="用户现在是大一学生。",
            category="教育.学业阶段",
            memory_type="permanent",
            metadata={
                "node_type": "fact",
                "node_status": "active",
                "subject_memory_id": subject.id,
                "source": "auto_extraction",
            },
        )
        fact_a = Memory(
            workspace_id=workspace_id,
            project_id=project["id"],
            content="用户现在是大一学生。",
            category="教育.学业阶段",
            type="permanent",
            node_type="fact",
            parent_memory_id=None,
            subject_memory_id=subject.id,
            node_status="active",
            canonical_key=str(fact_a_metadata.get("canonical_key") or "").strip() or None,
            metadata_json=fact_a_metadata,
        )

        fact_b_metadata = memory_metadata_service.normalize_memory_metadata(
            content="用户在英国的帝国理工学院学习物理",
            category="教育.学校",
            memory_type="permanent",
            metadata={
                "node_type": "fact",
                "node_status": "active",
                "subject_memory_id": subject.id,
                "source": "auto_extraction",
            },
        )
        fact_b = Memory(
            workspace_id=workspace_id,
            project_id=project["id"],
            content="用户在英国的帝国理工学院学习物理",
            category="教育.学校",
            type="permanent",
            node_type="fact",
            parent_memory_id=None,
            subject_memory_id=subject.id,
            node_status="active",
            canonical_key=str(fact_b_metadata.get("canonical_key") or "").strip() or None,
            metadata_json=fact_b_metadata,
        )

        db.add_all([concept_a, concept_b])
        db.flush()
        fact_a.parent_memory_id = concept_a.id
        fact_b.parent_memory_id = concept_b.id
        db.add_all([fact_a, fact_b])
        db.commit()
        fact_a_id = fact_a.id
        fact_b_id = fact_b.id
        subject_id = subject.id

        summary = memory_graph_repair_service.repair_project_memory_graph(
            db,
            workspace_id=workspace_id,
            project_id=project["id"],
        )
        db.commit()

        concept_nodes = (
            db.query(Memory)
            .filter(
                Memory.project_id == project["id"],
                Memory.node_type == "concept",
                Memory.subject_memory_id == subject_id,
            )
            .all()
        )
        repaired_fact_a = db.get(Memory, fact_a_id)
        repaired_fact_b = db.get(Memory, fact_b_id)

        assert len(concept_nodes) == 1
        assert concept_nodes[0].content == "教育背景"
        assert (concept_nodes[0].metadata_json or {}).get("concept_topic") == "教育"
        assert repaired_fact_a is not None
        assert repaired_fact_b is not None
        assert repaired_fact_a.parent_memory_id == concept_nodes[0].id
        assert repaired_fact_b.parent_memory_id == concept_nodes[0].id
        assert summary.deleted_duplicate_concepts == 1
        assert summary.reparented_nodes >= 1


def test_repair_project_memory_graph_preserves_version_edges() -> None:
    client = TestClient(main_module.app)
    user_info = register_user(client, "memory-repair-version-edges@example.com", "Repair Version Edges")
    workspace_id = user_info["workspace"]["id"]
    project = create_project(client, "Repair Version Edge Project")

    with SessionLocal() as db:
        project_row = db.get(Project, project["id"])
        assert project_row is not None
        root_memory, _ = ensure_project_assistant_root(db, project_row, reparent_orphans=False)
        subject, _ = ensure_project_user_subject(
            db,
            project_row,
            owner_user_id=user_info["user"]["id"],
        )

        def _fact(content: str, *, node_status: str, lineage_key: str) -> Memory:
            metadata = memory_metadata_service.normalize_memory_metadata(
                content=content,
                category="项目.接口",
                memory_type="permanent",
                metadata={
                    "node_type": "fact",
                    "node_status": node_status,
                    "subject_memory_id": subject.id,
                    "lineage_key": lineage_key,
                    "source": "auto_extraction",
                },
            )
            return Memory(
                workspace_id=workspace_id,
                project_id=project["id"],
                content=content,
                category="项目.接口",
                type="permanent",
                node_type="fact",
                parent_memory_id=subject.id,
                subject_memory_id=subject.id,
                node_status=node_status,
                canonical_key=str(metadata.get("canonical_key") or "").strip() or None,
                lineage_key=lineage_key,
                metadata_json=metadata,
            )

        predecessor = _fact("项目曾经使用 REST API。", node_status="superseded", lineage_key="repair-lineage")
        successor = _fact("项目当前使用 GraphQL API。", node_status="active", lineage_key="repair-lineage")
        conflicting = _fact("项目当前使用 gRPC API。", node_status="active", lineage_key="repair-lineage")
        category_path = Memory(
            workspace_id=workspace_id,
            project_id=project["id"],
            content="接口路径",
            category="项目.接口",
            type="permanent",
            parent_memory_id=root_memory.id,
            metadata_json={
                "node_type": "concept",
                "node_kind": "category-path",
                "concept_source": "category_path",
                "structural_only": True,
            },
        )
        db.add_all([predecessor, successor, conflicting, category_path])
        db.flush()
        legacy_child = _fact("项目接口迁移信息。", node_status="active", lineage_key="repair-legacy-child")
        legacy_child.parent_memory_id = category_path.id
        db.add(legacy_child)
        db.flush()
        supersedes_edge = MemoryEdge(
            source_memory_id=successor.id,
            target_memory_id=predecessor.id,
            edge_type="supersedes",
            strength=0.99,
        )
        conflict_edge = MemoryEdge(
            source_memory_id=min(successor.id, conflicting.id),
            target_memory_id=max(successor.id, conflicting.id),
            edge_type="conflict",
            strength=0.88,
        )
        db.add_all([supersedes_edge, conflict_edge])
        db.commit()
        category_path_id = category_path.id
        legacy_child_id = legacy_child.id
        predecessor_id = predecessor.id
        successor_id = successor.id
        conflicting_id = conflicting.id

        summary = memory_graph_repair_service.repair_project_memory_graph(
            db,
            workspace_id=workspace_id,
            project_id=project["id"],
        )
        db.commit()

        assert db.get(Memory, category_path_id) is None
        repaired_child = db.get(Memory, legacy_child_id)
        assert repaired_child is not None
        repaired_parent = db.get(Memory, repaired_child.parent_memory_id)
        assert repaired_parent is not None
        assert repaired_parent.id == subject.id or (
            repaired_parent.node_type == "concept" and repaired_parent.parent_memory_id == subject.id
        )
        assert summary.deleted_legacy_nodes == 1

        preserved_supersedes = (
            db.query(MemoryEdge)
            .filter(
                MemoryEdge.source_memory_id == successor_id,
                MemoryEdge.target_memory_id == predecessor_id,
                MemoryEdge.edge_type == "supersedes",
            )
            .one_or_none()
        )
        preserved_conflict = (
            db.query(MemoryEdge)
            .filter(
                MemoryEdge.source_memory_id == min(successor_id, conflicting_id),
                MemoryEdge.target_memory_id == max(successor_id, conflicting_id),
                MemoryEdge.edge_type == "conflict",
            )
            .one_or_none()
        )
        assert preserved_supersedes is not None
        assert preserved_conflict is not None


def test_cleanup_pending_upload_session_skips_completed_items_when_task_replays(monkeypatch) -> None:
    client = TestClient(main_module.app)
    register_user(client, "upload-replay@example.com", "Upload Replay")
    project = create_project(client, "Upload Replay Project")
    dataset = create_dataset(client, project["id"], "Upload Replay Dataset")

    payload_bytes, _ = upload_fixture("replay.jpg")
    presign = client.post(
        "/api/v1/uploads/presign",
        json={
            "dataset_id": dataset["id"],
            "filename": "replay.jpg",
            "media_type": "image/jpeg",
            "size_bytes": len(payload_bytes),
        },
        headers=csrf_headers(client),
    )
    assert presign.status_code == 200
    payload = presign.json()

    put_resp = client.put(
        payload["put_url"],
        content=payload_bytes,
        headers={**payload["headers"], **csrf_headers(client)},
    )
    assert put_resp.status_code == 200

    complete = client.post(
        "/api/v1/uploads/complete",
        json={"upload_id": payload["upload_id"], "data_item_id": payload["data_item_id"]},
        headers=csrf_headers(client),
    )
    assert complete.status_code == 200

    with SessionLocal() as db:
        item = db.get(DataItem, payload["data_item_id"])
        assert item is not None
        object_key = item.object_key

    deleted: list[tuple[str, str]] = []

    def fake_delete_object(*, bucket_name: str, object_key: str) -> None:
        deleted.append((bucket_name, object_key))

    monkeypatch.setattr(worker_tasks, "delete_object", fake_delete_object)

    worker_tasks.cleanup_pending_upload_session(payload["upload_id"], object_key, payload["data_item_id"])

    assert deleted == []


def test_cleanup_deleted_dataset_marks_failed_when_object_delete_fails(monkeypatch) -> None:
    client = TestClient(main_module.app)
    register_user(client, "cleanup-fail@example.com", "Cleanup Fail User")
    project = create_project(client, "Cleanup Fail Project")
    dataset = create_dataset(client, project["id"], "Cleanup Fail Dataset")
    data_item_id = upload_item(client, dataset["id"], "cleanup-fail.jpg")

    def fake_delete_object(*, bucket_name: str, object_key: str) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(worker_tasks, "delete_object", fake_delete_object)

    worker_tasks.cleanup_deleted_dataset(dataset["id"])

    with SessionLocal() as db:
        dataset_row = db.get(Dataset, dataset["id"])
        data_item = db.get(DataItem, data_item_id)
        assert dataset_row is not None
        assert dataset_row.cleanup_status == "failed"
        assert data_item is not None
        assert data_item.deleted_at is not None


def test_pipeline_get_backfills_missing_defaults_and_migrates_legacy_realtime_llm() -> None:
    client = TestClient(main_module.app)
    register_user(client, "pipeline-get@example.com", "Pipeline Get")
    project = create_project(client, "Pipeline Get Project")

    with SessionLocal() as db:
        vision = (
            db.query(PipelineConfig)
            .filter(PipelineConfig.project_id == project["id"], PipelineConfig.model_type == "vision")
            .first()
        )
        assert vision is not None
        db.delete(vision)
        llm = (
            db.query(PipelineConfig)
            .filter(PipelineConfig.project_id == project["id"], PipelineConfig.model_type == "llm")
            .first()
        )
        assert llm is not None
        llm.model_id = "qwen3-omni-flash-realtime"
        realtime = (
            db.query(PipelineConfig)
            .filter(PipelineConfig.project_id == project["id"], PipelineConfig.model_type == "realtime")
            .first()
        )
        assert realtime is not None
        db.delete(realtime)
        realtime_asr = (
            db.query(PipelineConfig)
            .filter(PipelineConfig.project_id == project["id"], PipelineConfig.model_type == "realtime_asr")
            .first()
        )
        assert realtime_asr is not None
        db.delete(realtime_asr)
        realtime_tts = (
            db.query(PipelineConfig)
            .filter(PipelineConfig.project_id == project["id"], PipelineConfig.model_type == "realtime_tts")
            .first()
        )
        assert realtime_tts is not None
        db.delete(realtime_tts)
        db.commit()
        assert db.query(PipelineConfig).filter(PipelineConfig.project_id == project["id"]).count() == 3

    current = client.get(f"/api/v1/pipeline?project_id={project['id']}")
    assert current.status_code == 200
    items = {item["model_type"]: item["model_id"] for item in current.json()["items"]}
    assert len(items) == 7
    assert items["llm"] == "qwen3.5-plus"
    assert items["vision"] == "qwen-vl-plus"
    assert items["realtime"] == "qwen3-omni-flash-realtime"
    assert items["realtime_asr"] == "qwen3-asr-flash-realtime"
    assert items["realtime_tts"] == "qwen3-tts-flash-realtime"

    with SessionLocal() as db:
        assert db.query(PipelineConfig).filter(PipelineConfig.project_id == project["id"]).count() == 7


def test_deleted_project_invalidates_conversation_and_memory_handles() -> None:
    client = TestClient(main_module.app)
    register_user(client, "deleted-project@example.com", "Deleted Project")
    project = create_project(client, "Deleted Project")

    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Deleted Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200
    conversation_id = conversation.json()["id"]

    memory = client.post(
        "/api/v1/memory",
        json={"project_id": project["id"], "content": "用户喜欢乌龙茶", "category": "偏好", "type": "permanent"},
        headers=csrf_headers(client),
    )
    assert memory.status_code == 200
    memory_id = memory.json()["id"]

    deleted = client.delete(
        f"/api/v1/projects/{project['id']}",
        headers=csrf_headers(client),
    )
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "deleted"

    assert client.get(f"/api/v1/chat/conversations/{conversation_id}/messages").status_code == 404
    assert (
        client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"content": "should fail"},
            headers=csrf_headers(client),
        ).status_code
        == 404
    )
    assert client.get(f"/api/v1/memory/{memory_id}").status_code == 404
    assert client.get(f"/api/v1/memory/{project['id']}/stream").status_code == 404
    assert client.get(f"/api/v1/chat/conversations/{conversation_id}/memory-stream").status_code == 404
    with SessionLocal() as db:
        assert db.get(Project, project["id"]) is None
        assert db.get(Conversation, conversation_id) is None
        assert db.get(Memory, memory_id) is None


def test_promoted_private_memory_stays_hidden_from_other_members() -> None:
    owner = TestClient(main_module.app)
    owner_info = register_user(owner, "promote-owner@example.com", "Promote Owner")
    owner_workspace_id = owner_info["workspace"]["id"]
    project = create_project(owner, "Promote Project")

    conversation = owner.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Promote Thread"},
        headers=csrf_headers(owner),
    )
    assert conversation.status_code == 200
    conversation_id = conversation.json()["id"]

    temp_memory = owner.post(
        "/api/v1/memory",
        json={
            "project_id": project["id"],
            "content": "用户下周去东京出差",
            "category": "工作.计划",
            "type": "temporary",
            "source_conversation_id": conversation_id,
        },
        headers=csrf_headers(owner),
    )
    assert temp_memory.status_code == 200

    promoted = owner.post(
        f"/api/v1/memory/{temp_memory.json()['id']}/promote",
        headers=csrf_headers(owner),
    )
    assert promoted.status_code == 200
    promoted_id = promoted.json()["id"]

    viewer = TestClient(main_module.app)
    register_user(viewer, "promote-viewer@example.com", "Promote Viewer")
    add_workspace_membership(owner_workspace_id, "promote-viewer@example.com", "viewer")

    viewer_detail = viewer.get(
        f"/api/v1/memory/{promoted_id}",
        headers={"x-workspace-id": owner_workspace_id},
    )
    assert viewer_detail.status_code == 404

    viewer_graph = viewer.get(
        f"/api/v1/memory?project_id={project['id']}",
        headers={"x-workspace-id": owner_workspace_id},
    )
    assert viewer_graph.status_code == 200
    assert all(node["id"] != promoted_id for node in viewer_graph.json()["nodes"])

    owner_search = owner.post(
        "/api/v1/memory/search",
        json={"project_id": project["id"], "query": "东京"},
        headers={"x-workspace-id": owner_workspace_id},
    )
    assert owner_search.status_code == 200
    assert [item["memory"]["id"] for item in owner_search.json()] == [promoted_id]

    viewer_search = viewer.post(
        "/api/v1/memory/search",
        json={"project_id": project["id"], "query": "东京"},
        headers={"x-workspace-id": owner_workspace_id},
    )
    assert viewer_search.status_code == 200
    assert viewer_search.json() == []


def test_memory_detail_hides_deleted_dataset_files() -> None:
    client = TestClient(main_module.app)
    register_user(client, "memory-deleted-files@example.com", "Memory Deleted Files")
    project = create_project(client, "Memory Deleted Files Project")
    dataset = create_dataset(client, project["id"], "Memory Deleted Files Dataset")
    data_item_id = upload_item(client, dataset["id"], "hidden.jpg")

    memory = client.post(
        "/api/v1/memory",
        json={"project_id": project["id"], "content": "知识文件", "category": "资料", "type": "permanent"},
        headers=csrf_headers(client),
    )
    assert memory.status_code == 200
    memory_id = memory.json()["id"]

    attached = client.post(
        f"/api/v1/memory/{memory_id}/files",
        json={"data_item_id": data_item_id},
        headers=csrf_headers(client),
    )
    assert attached.status_code == 200

    deleted = client.delete(
        f"/api/v1/datasets/{dataset['id']}",
        headers=csrf_headers(client),
    )
    assert deleted.status_code == 200

    detail = client.get(f"/api/v1/memory/{memory_id}")
    assert detail.status_code == 200
    assert detail.json()["files"] == []

    graph = client.get(f"/api/v1/memory?project_id={project['id']}")
    assert graph.status_code == 200
    assert all(node.get("metadata_json", {}).get("node_kind") != "file" for node in graph.json()["nodes"])


def test_reset_password_for_missing_user_is_generic_after_valid_code() -> None:
    client = TestClient(main_module.app)
    code = issue_verification_code(client, "missing-reset@example.com", "reset")

    resp = client.post(
        "/api/v1/auth/reset-password",
        json={"email": "missing-reset@example.com", "password": "newpass1234pass", "code": code},
        headers=public_headers(),
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_orchestrator_filters_private_memory_embeddings_from_prompt(monkeypatch) -> None:
    owner = TestClient(main_module.app)
    owner_info = register_user(owner, "rag-owner@example.com", "Rag Owner")
    workspace_id = owner_info["workspace"]["id"]
    project = create_project(owner, "Rag Project")

    owner_conversation = owner.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Owner Thread"},
        headers=csrf_headers(owner),
    )
    assert owner_conversation.status_code == 200

    temp_memory = owner.post(
        "/api/v1/memory",
        json={
            "project_id": project["id"],
            "content": "私有事实-不要进入别人的prompt",
            "category": "测试",
            "type": "temporary",
            "source_conversation_id": owner_conversation.json()["id"],
        },
        headers=csrf_headers(owner),
    )
    assert temp_memory.status_code == 200

    promoted = owner.post(
        f"/api/v1/memory/{temp_memory.json()['id']}/promote",
        headers=csrf_headers(owner),
    )
    assert promoted.status_code == 200
    private_memory_id = promoted.json()["id"]

    viewer = TestClient(main_module.app)
    register_user(viewer, "rag-viewer@example.com", "Rag Viewer")
    add_workspace_membership(workspace_id, "rag-viewer@example.com", "editor")

    viewer_conversation = viewer.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Viewer Thread"},
        headers=csrf_headers(viewer, workspace_id),
    )
    assert viewer_conversation.status_code == 200

    captured: dict[str, str] = {}

    async def fake_search_similar(*args, **kwargs) -> list[dict]:
        return [
            {
                "id": "embedding-1",
                "chunk_text": "私有事实-不要进入别人的prompt",
                "memory_id": private_memory_id,
                "data_item_id": None,
                "score": 0.99,
            }
        ]

    async def fake_responses_completion_detailed(
        input_items,
        *,
        model=None,
        enable_thinking=None,
        tools=None,
        tool_choice="auto",
        image_bytes=None,
        image_mime_type="image/jpeg",
    ):
        del model, enable_thinking, tools, tool_choice, image_bytes, image_mime_type
        messages = input_items
        captured["system_prompt"] = messages[0]["content"]
        return SimpleNamespace(content="ok", reasoning_content=None, search_sources=[], tool_calls=[])

    monkeypatch.setattr(orchestrator_service, "search_similar", fake_search_similar)
    monkeypatch.setattr(
        orchestrator_service,
        "responses_completion_detailed",
        fake_responses_completion_detailed,
    )

    with SessionLocal() as db:
        result = asyncio.run(
            orchestrator_service.orchestrate_inference(
                db,
                workspace_id=workspace_id,
                project_id=project["id"],
                conversation_id=viewer_conversation.json()["id"],
                user_message="你记得什么",
                recent_messages=[],
            )
        )

    assert result["content"] == "ok"
    assert "私有事实-不要进入别人的prompt" not in captured["system_prompt"]


def test_orchestrator_skips_retrieval_for_self_intro_requests(monkeypatch) -> None:
    client = TestClient(main_module.app)
    owner_info = register_user(client, "context-none@example.com", "Context None")
    workspace_id = owner_info["workspace"]["id"]
    project = create_project(client, "Context None Project")

    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Context None Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200

    search_calls = {"count": 0}
    captured: dict[str, str] = {}

    async def fake_search_similar(*args, **kwargs) -> list[dict]:
        search_calls["count"] += 1
        return []

    async def fake_responses_completion_detailed(
        input_items,
        *,
        model=None,
        enable_thinking=None,
        tools=None,
        tool_choice="auto",
        image_bytes=None,
        image_mime_type="image/jpeg",
    ):
        del model, enable_thinking, tools, tool_choice, image_bytes, image_mime_type
        captured["system_prompt"] = input_items[0]["content"]
        return SimpleNamespace(content="ok", reasoning_content=None, search_sources=[], tool_calls=[])

    monkeypatch.setattr(orchestrator_service, "search_similar", fake_search_similar)
    monkeypatch.setattr(
        orchestrator_service,
        "responses_completion_detailed",
        fake_responses_completion_detailed,
    )

    with SessionLocal() as db:
        result = asyncio.run(
            orchestrator_service.orchestrate_inference(
                db,
                workspace_id=workspace_id,
                project_id=project["id"],
                conversation_id=conversation.json()["id"],
                user_message="介绍一下你自己",
                recent_messages=[],
            )
        )

    assert result["content"] == "ok"
    assert search_calls["count"] == 0
    assert result["retrieval_trace"]["context_level"] == "none"
    assert result["retrieval_trace"]["decision_source"] == "rules"
    assert isinstance(result["retrieval_trace"]["decision_confidence"], float)
    assert result["retrieval_trace"]["knowledge_chunks"] == []
    assert result["retrieval_trace"]["linked_file_chunks"] == []
    assert "相关知识参考" not in captured["system_prompt"]
    assert "与当前主体直接关联的资料摘录" not in captured["system_prompt"]


def test_orchestrator_memory_only_context_excludes_knowledge_and_linked_files(monkeypatch) -> None:
    client = TestClient(main_module.app)
    owner_info = register_user(client, "context-memory-only@example.com", "Context Memory Only")
    workspace_id = owner_info["workspace"]["id"]
    project = create_project(client, "Context Memory Only Project")

    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Context Memory Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200

    memory = client.post(
        "/api/v1/memory",
        json={
            "project_id": project["id"],
            "content": "用户上次说想要分步骤复盘。",
            "category": "偏好",
        },
        headers=csrf_headers(client),
    )
    assert memory.status_code == 200

    linked_loader_calls = {"count": 0}
    captured: dict[str, str] = {}

    async def fake_search_similar(*args, **kwargs) -> list[dict]:
        return [
            {
                "id": "embedding-memory-1",
                "chunk_text": "用户上次说想要分步骤复盘。",
                "memory_id": memory.json()["id"],
                "data_item_id": None,
                "score": 0.96,
            },
            {
                "id": "embedding-knowledge-1",
                "chunk_text": "这段知识库内容不应该出现在 memory_only 中。",
                "memory_id": None,
                "data_item_id": "data-item-knowledge-1",
                "score": 0.91,
            },
        ]

    async def fake_load_linked_file_chunks_for_memories(*args, **kwargs) -> list[dict]:
        linked_loader_calls["count"] += 1
        return [
            {
                "id": "chunk-1",
                "chunk_text": "这段关联文件也不应该出现在 memory_only 中。",
                "data_item_id": "data-item-linked-1",
                "filename": "linked.pdf",
                "score": 0.88,
            }
        ]

    async def fake_responses_completion_detailed(
        input_items,
        *,
        model=None,
        enable_thinking=None,
        tools=None,
        tool_choice="auto",
        image_bytes=None,
        image_mime_type="image/jpeg",
    ):
        del model, enable_thinking, tools, tool_choice, image_bytes, image_mime_type
        captured["system_prompt"] = input_items[0]["content"]
        return SimpleNamespace(content="ok", reasoning_content=None, search_sources=[], tool_calls=[])

    monkeypatch.setattr(orchestrator_service, "search_similar", fake_search_similar)
    monkeypatch.setattr(
        orchestrator_service,
        "load_linked_file_chunks_for_memories",
        fake_load_linked_file_chunks_for_memories,
    )
    monkeypatch.setattr(
        orchestrator_service,
        "responses_completion_detailed",
        fake_responses_completion_detailed,
    )

    with SessionLocal() as db:
        result = asyncio.run(
            orchestrator_service.orchestrate_inference(
                db,
                workspace_id=workspace_id,
                project_id=project["id"],
                conversation_id=conversation.json()["id"],
                user_message="你记得我上次说过什么吗？",
                recent_messages=[],
            )
        )

    assert result["content"] == "ok"
    assert result["retrieval_trace"]["context_level"] == "memory_only"
    assert result["retrieval_trace"]["decision_source"] == "rules"
    assert result["retrieval_trace"]["knowledge_chunks"] == []
    assert result["retrieval_trace"]["linked_file_chunks"] == []
    assert linked_loader_calls["count"] == 0
    assert "用户上次说想要分步骤复盘" in captured["system_prompt"]
    assert "这段知识库内容不应该出现在 memory_only 中" not in captured["system_prompt"]
    assert "这段关联文件也不应该出现在 memory_only 中" not in captured["system_prompt"]


def test_orchestrator_memory_only_context_excludes_unrelated_static_preferences(monkeypatch) -> None:
    client = TestClient(main_module.app)
    owner_info = register_user(client, "context-strict-related@example.com", "Context Strict Related")
    workspace_id = owner_info["workspace"]["id"]
    project = create_project(client, "Context Strict Related Project")

    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Strict Related Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200

    travel_memory = client.post(
        "/api/v1/memory",
        json={
            "project_id": project["id"],
            "content": "用户计划于2026年去东京旅行。",
            "category": "旅行.计划",
        },
        headers=csrf_headers(client),
    )
    assert travel_memory.status_code == 200

    tea_memory = client.post(
        "/api/v1/memory",
        json={
            "project_id": project["id"],
            "content": "用户喜欢乌龙茶。",
            "category": "饮食.偏好",
        },
        headers=csrf_headers(client),
    )
    assert tea_memory.status_code == 200

    captured: dict[str, str] = {}

    async def fake_search_similar(*args, **kwargs) -> list[dict]:
        del args, kwargs
        return [
            {
                "id": "embedding-travel-1",
                "chunk_text": "用户计划于2026年去东京旅行。",
                "memory_id": travel_memory.json()["id"],
                "data_item_id": None,
                "score": 0.91,
            },
            {
                "id": "embedding-tea-1",
                "chunk_text": "用户喜欢乌龙茶。",
                "memory_id": tea_memory.json()["id"],
                "data_item_id": None,
                "score": 0.49,
            },
        ]

    async def fake_responses_completion_detailed(
        input_items,
        *,
        model=None,
        enable_thinking=None,
        tools=None,
        tool_choice="auto",
        image_bytes=None,
        image_mime_type="image/jpeg",
    ):
        del model, enable_thinking, tools, tool_choice, image_bytes, image_mime_type
        captured["system_prompt"] = input_items[0]["content"]
        return SimpleNamespace(content="ok", reasoning_content=None, search_sources=[], tool_calls=[])

    monkeypatch.setattr(orchestrator_service, "search_similar", fake_search_similar)
    monkeypatch.setattr(
        orchestrator_service,
        "responses_completion_detailed",
        fake_responses_completion_detailed,
    )

    with SessionLocal() as db:
        result = asyncio.run(
            orchestrator_service.orchestrate_inference(
                db,
                workspace_id=workspace_id,
                project_id=project["id"],
                conversation_id=conversation.json()["id"],
                user_message="你记得我的东京旅行计划吗？",
                recent_messages=[],
            )
        )

    assert result["content"] == "ok"
    assert result["retrieval_trace"]["context_level"] == "memory_only"
    assert result["retrieval_trace"]["memory_counts"]["static"] == 0
    assert "用户计划于2026年去东京旅行。" in captured["system_prompt"]
    assert "用户喜欢乌龙茶。" not in captured["system_prompt"]


def test_orchestrator_memory_only_graph_expansion_keeps_parent_but_not_sibling(monkeypatch) -> None:
    client = TestClient(main_module.app)
    owner_info = register_user(client, "context-graph-parent@example.com", "Context Graph Parent")
    workspace_id = owner_info["workspace"]["id"]
    project = create_project(client, "Context Graph Parent Project")

    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Graph Parent Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200

    with SessionLocal() as db:
        project_row = db.get(Project, project["id"])
        assert project_row is not None
        root_memory, _ = ensure_project_assistant_root(db, project_row, reparent_orphans=False)
        tea_concept = Memory(
            workspace_id=workspace_id,
            project_id=project["id"],
            content="用户对茶感兴趣",
            category="饮食.偏好.茶",
            type="permanent",
            parent_memory_id=root_memory.id,
            metadata_json={"memory_kind": "preference", "node_kind": "concept", "auto_generated": True},
        )
        jasmine = Memory(
            workspace_id=workspace_id,
            project_id=project["id"],
            content="用户喜欢茉莉花茶。",
            category="饮食.偏好",
            type="permanent",
            parent_memory_id=None,
            metadata_json={"memory_kind": "preference"},
        )
        oolong = Memory(
            workspace_id=workspace_id,
            project_id=project["id"],
            content="用户喜欢乌龙茶。",
            category="饮食.偏好",
            type="permanent",
            parent_memory_id=None,
            metadata_json={"memory_kind": "preference"},
        )
        db.add_all([tea_concept, jasmine, oolong])
        db.flush()
        jasmine.parent_memory_id = tea_concept.id
        oolong.parent_memory_id = tea_concept.id
        db.commit()
        jasmine_id = jasmine.id

    captured: dict[str, str] = {}

    async def fake_search_similar(*args, **kwargs) -> list[dict]:
        del args, kwargs
        return [
            {
                "id": "embedding-jasmine-1",
                "chunk_text": "用户喜欢茉莉花茶。",
                "memory_id": jasmine_id,
                "data_item_id": None,
                "score": 0.92,
            }
        ]

    async def fake_responses_completion_detailed(
        input_items,
        *,
        model=None,
        enable_thinking=None,
        tools=None,
        tool_choice="auto",
        image_bytes=None,
        image_mime_type="image/jpeg",
    ):
        del model, enable_thinking, tools, tool_choice, image_bytes, image_mime_type
        captured["system_prompt"] = input_items[0]["content"]
        return SimpleNamespace(content="ok", reasoning_content=None, search_sources=[], tool_calls=[])

    monkeypatch.setattr(orchestrator_service, "search_similar", fake_search_similar)
    monkeypatch.setattr(
        orchestrator_service,
        "responses_completion_detailed",
        fake_responses_completion_detailed,
    )

    with SessionLocal() as db:
        result = asyncio.run(
            orchestrator_service.orchestrate_inference(
                db,
                workspace_id=workspace_id,
                project_id=project["id"],
                conversation_id=conversation.json()["id"],
                user_message="你记得我喜欢茉莉花茶吗？",
                recent_messages=[],
            )
        )

    assert result["content"] == "ok"
    assert "用户对茶感兴趣" in captured["system_prompt"]
    assert "用户喜欢茉莉花茶。" in captured["system_prompt"]
    assert "用户喜欢乌龙茶。" not in captured["system_prompt"]


def test_orchestrator_includes_chunks_from_memory_linked_files(monkeypatch) -> None:
    client = TestClient(main_module.app)
    owner_info = register_user(client, "linked-rag@example.com", "Linked Rag")
    workspace_id = owner_info["workspace"]["id"]
    project = create_project(client, "Linked Rag Project")

    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Linked Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200

    memory = client.post(
        "/api/v1/memory",
        json={"project_id": project["id"], "content": "心理学"},
        headers=csrf_headers(client),
    )
    assert memory.status_code == 200

    captured: dict[str, str] = {}

    async def fake_search_similar(*args, **kwargs) -> list[dict]:
        return [
            {
                "id": "embedding-memory-1",
                "chunk_text": "心理学",
                "memory_id": memory.json()["id"],
                "data_item_id": None,
                "score": 0.98,
            }
        ]

    async def fake_load_linked_file_chunks_for_memories(*args, **kwargs) -> list[dict]:
        return [
            {
                "id": "chunk-1",
                "chunk_text": "文件里提到：认知行为疗法适用于焦虑干预。",
                "data_item_id": "data-item-1",
                "filename": "心理学手册.pdf",
                "score": 0.91,
                "memory_ids": [memory.json()["id"]],
            }
        ]

    async def fake_responses_completion_detailed(
        input_items,
        *,
        model=None,
        enable_thinking=None,
        tools=None,
        tool_choice="auto",
        image_bytes=None,
        image_mime_type="image/jpeg",
    ):
        del model, enable_thinking, tools, tool_choice, image_bytes, image_mime_type
        messages = input_items
        captured["system_prompt"] = messages[0]["content"]
        return SimpleNamespace(content="ok", reasoning_content=None, search_sources=[], tool_calls=[])

    monkeypatch.setattr(orchestrator_service, "search_similar", fake_search_similar)
    monkeypatch.setattr(
        orchestrator_service,
        "load_linked_file_chunks_for_memories",
        fake_load_linked_file_chunks_for_memories,
    )
    monkeypatch.setattr(
        orchestrator_service,
        "responses_completion_detailed",
        fake_responses_completion_detailed,
    )

    with SessionLocal() as db:
        result = asyncio.run(
            orchestrator_service.orchestrate_inference(
                db,
                workspace_id=workspace_id,
                project_id=project["id"],
                conversation_id=conversation.json()["id"],
                user_message="请结合心理学资料回答",
                recent_messages=[],
            )
        )

    assert result["content"] == "ok"
    assert result["retrieval_trace"]["context_level"] == "full_rag"
    assert result["retrieval_trace"]["decision_source"] == "rules"
    assert "与当前主体直接关联的资料摘录" in captured["system_prompt"]
    assert "心理学手册.pdf" in captured["system_prompt"]
    assert "认知行为疗法适用于焦虑干预" in captured["system_prompt"]


def test_orchestrator_layered_memory_context_prefers_static_and_relevant_memories(monkeypatch) -> None:
    client = TestClient(main_module.app)
    owner_info = register_user(client, "layered-memory@example.com", "Layered Memory")
    workspace_id = owner_info["workspace"]["id"]
    project = create_project(client, "Layered Memory Project")

    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Layered Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200

    pinned = client.post(
        "/api/v1/memory",
        json={
            "project_id": project["id"],
            "content": "用户叫阿铭，长期喜欢数学和结构化推理。",
            "category": "用户画像",
            "metadata_json": {"pinned": True, "memory_kind": "profile"},
        },
        headers=csrf_headers(client),
    )
    assert pinned.status_code == 200

    unrelated = client.post(
        "/api/v1/memory",
        json={
            "project_id": project["id"],
            "content": "用户上周随手看了一部电影。",
            "category": "娱乐",
        },
        headers=csrf_headers(client),
    )
    assert unrelated.status_code == 200

    temporary = client.post(
        "/api/v1/memory",
        json={
            "project_id": project["id"],
            "content": "这次对话里用户正在准备数学竞赛。",
            "category": "目标.竞赛",
            "type": "temporary",
            "source_conversation_id": conversation.json()["id"],
        },
        headers=csrf_headers(client),
    )
    assert temporary.status_code == 200

    captured: dict[str, object] = {}

    async def fake_search_similar(*args, **kwargs) -> list[dict]:
        return [
            {
                "id": "embedding-temp-1",
                "chunk_text": "这次对话里用户正在准备数学竞赛。",
                "memory_id": temporary.json()["id"],
                "data_item_id": None,
                "score": 0.97,
            }
        ]

    async def fake_responses_completion_detailed(
        input_items,
        *,
        model=None,
        enable_thinking=None,
        tools=None,
        tool_choice="auto",
        image_bytes=None,
        image_mime_type="image/jpeg",
    ):
        del model, enable_thinking, tools, tool_choice, image_bytes, image_mime_type
        captured["system_prompt"] = input_items[0]["content"]
        return SimpleNamespace(content="ok", reasoning_content=None, search_sources=[], tool_calls=[])

    monkeypatch.setattr(orchestrator_service, "search_similar", fake_search_similar)
    monkeypatch.setattr(
        orchestrator_service,
        "responses_completion_detailed",
        fake_responses_completion_detailed,
    )

    with SessionLocal() as db:
        result = asyncio.run(
            orchestrator_service.orchestrate_inference(
                db,
                workspace_id=workspace_id,
                project_id=project["id"],
                conversation_id=conversation.json()["id"],
                user_message="请结合我准备数学竞赛这件事回答",
                recent_messages=[],
            )
        )

    assert result["content"] == "ok"
    assert result["retrieval_trace"]["strategy"] == "layered_memory_v2"
    assert "长期喜欢数学和结构化推理" in str(captured["system_prompt"])
    assert "正在准备数学竞赛" in str(captured["system_prompt"])
    assert "上周随手看了一部电影" not in str(captured["system_prompt"])


def test_context_route_classifier_can_keep_light_context_when_thinking_is_enabled(monkeypatch) -> None:
    async def fake_chat_completion_detailed(
        messages,
        *,
        model=None,
        temperature=0.0,
        max_tokens=180,
        enable_thinking=False,
        enable_search=False,
    ):
        del messages, model, temperature, max_tokens, enable_thinking, enable_search
        return SimpleNamespace(
            content=json.dumps(
                {
                    "route": "profile_only",
                    "confidence": 0.92,
                    "reason": "question only needs the stable profile layer",
                },
                ensure_ascii=False,
            )
        )

    monkeypatch.setattr(
        orchestrator_service,
        "chat_completion_detailed",
        fake_chat_completion_detailed,
    )

    with SessionLocal() as db:
        decision = asyncio.run(
            orchestrator_service.resolve_context_route(
                db,
                project_id="project-test",
                user_message="请认真分析一下我的学习方式是否适合结构化训练",
                recent_messages=[],
                enable_thinking=True,
                llm_model_id="qwen-plus",
            )
        )

    assert decision.route == "profile_only"
    assert decision.source == "classifier"
    assert decision.confidence == pytest.approx(0.92)


def test_chat_message_persists_retrieval_trace_and_touches_memory_usage(monkeypatch) -> None:
    client = TestClient(main_module.app)
    monkeypatch.setattr(auth_router.settings, "verification_rate_limit_max", 999)
    monkeypatch.setattr(auth_router.settings, "auth_rate_limit_ip_max", 999)
    monkeypatch.setattr(auth_router.settings, "auth_rate_limit_email_ip_max", 999)
    owner_info = register_user(
        client,
        f"retrieval-trace-{os.urandom(4).hex()}@example.com",
        "Trace User",
    )
    workspace_id = owner_info["workspace"]["id"]
    project = create_project(client, "Trace Project")
    monkeypatch.setattr(chat_router.settings, "dashscope_api_key", "test-key")

    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Trace Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200

    memory = client.post(
        "/api/v1/memory",
        json={
            "project_id": project["id"],
            "content": "用户偏好一步一步的解释。",
            "category": "偏好",
        },
        headers=csrf_headers(client),
    )
    assert memory.status_code == 200

    async def fake_orchestrate_inference(*args, **kwargs):
        return {
            "content": "好的，我会分步骤说明。",
            "reasoning_content": None,
            "sources": [],
            "retrieval_trace": {
                "strategy": "subject_graph_v1",
                "memories": [
                    {
                        "id": memory.json()["id"],
                        "source": "semantic",
                        "score": 0.94,
                    }
                ],
                "knowledge_chunks": [],
                "linked_file_chunks": [],
            },
        }

    monkeypatch.setattr(chat_router, "orchestrate_inference", fake_orchestrate_inference)

    resp = client.post(
        f"/api/v1/chat/conversations/{conversation.json()['id']}/messages",
        json={"content": "请回答"},
        headers=csrf_headers(client, workspace_id),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["metadata_json"]["retrieval_trace"]["strategy"] == "subject_graph_v1"

    with SessionLocal() as db:
        refreshed = db.get(Memory, memory.json()["id"])
        assert refreshed is not None
        assert refreshed.metadata_json["retrieval_count"] >= 1
        assert refreshed.metadata_json["last_used_source"] == "semantic"
        assert isinstance(refreshed.metadata_json["last_used_at"], str)


def test_chat_message_updates_conversation_focus_from_retrieval_trace(monkeypatch) -> None:
    client = TestClient(main_module.app)
    monkeypatch.setattr(auth_router.settings, "verification_rate_limit_max", 999)
    monkeypatch.setattr(auth_router.settings, "auth_rate_limit_ip_max", 999)
    monkeypatch.setattr(auth_router.settings, "auth_rate_limit_email_ip_max", 999)
    owner_info = register_user(
        client,
        f"focus-trace-{os.urandom(4).hex()}@example.com",
        "Focus Trace User",
    )
    workspace_id = owner_info["workspace"]["id"]
    project = create_project(client, "Focus Trace Project")
    monkeypatch.setattr(chat_router.settings, "dashscope_api_key", "test-key")

    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Focus Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200

    subject = client.post(
        "/api/v1/memory",
        json={
            "project_id": project["id"],
            "content": "线性代数",
            "category": "course",
            "node_type": "subject",
            "subject_kind": "course",
        },
        headers=csrf_headers(client, workspace_id),
    )
    assert subject.status_code == 200

    concept = client.post(
        "/api/v1/memory",
        json={
            "project_id": project["id"],
            "content": "矩阵分解",
            "category": "course.matrix",
            "node_type": "concept",
            "parent_memory_id": subject.json()["id"],
        },
        headers=csrf_headers(client, workspace_id),
    )
    assert concept.status_code == 200

    async def fake_orchestrate_inference(*args, **kwargs):
        return {
            "content": "我们继续看矩阵分解。",
            "reasoning_content": None,
            "sources": [],
            "retrieval_trace": {
                "strategy": "subject_graph_v1",
                "primary_subject_id": subject.json()["id"],
                "active_subject_ids": [subject.json()["id"]],
                "active_concept_ids": [concept.json()["id"]],
                "memories": [],
                "knowledge_chunks": [],
                "linked_file_chunks": [],
            },
        }

    monkeypatch.setattr(chat_router, "orchestrate_inference", fake_orchestrate_inference)

    response = client.post(
        f"/api/v1/chat/conversations/{conversation.json()['id']}/messages",
        json={"content": "继续讲矩阵分解"},
        headers=csrf_headers(client, workspace_id),
    )
    assert response.status_code == 200

    with SessionLocal() as db:
        refreshed = db.get(Conversation, conversation.json()["id"])
        assert refreshed is not None
        assert refreshed.metadata_json["primary_subject_id"] == subject.json()["id"]
        assert refreshed.metadata_json["active_subject_ids"] == [subject.json()["id"]]
        assert refreshed.metadata_json["active_concept_ids"] == [concept.json()["id"]]
        assert refreshed.metadata_json["focus_strategy"] == "subject_graph_v1"
        assert refreshed.metadata_json["active_route"] == "subject_graph_v1"
        assert refreshed.metadata_json["interaction_mode"] == "subject_graph"
        assert refreshed.metadata_json["last_graph_focus"]["primary_subject_id"] == subject.json()["id"]
        assert refreshed.metadata_json["last_graph_focus"]["active_concept_ids"] == [concept.json()["id"]]
        assert isinstance(refreshed.metadata_json["focus_updated_at"], str)


def test_subject_routes_resolve_overview_and_subgraph() -> None:
    client = TestClient(main_module.app)
    owner_info = register_user(
        client,
        f"subject-routes-{os.urandom(4).hex()}@example.com",
        "Subject Routes User",
    )
    workspace_id = owner_info["workspace"]["id"]
    project = create_project(client, "Subject Routes Project")

    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"project_id": project["id"], "title": "Subject Thread"},
        headers=csrf_headers(client),
    )
    assert conversation.status_code == 200

    subject = client.post(
        "/api/v1/memory",
        json={
            "project_id": project["id"],
            "content": "线性代数",
            "category": "course",
            "node_type": "subject",
            "subject_kind": "course",
        },
        headers=csrf_headers(client, workspace_id),
    )
    assert subject.status_code == 200

    concept = client.post(
        "/api/v1/memory",
        json={
            "project_id": project["id"],
            "content": "矩阵分解",
            "category": "course.matrix",
            "node_type": "concept",
            "parent_memory_id": subject.json()["id"],
        },
        headers=csrf_headers(client, workspace_id),
    )
    assert concept.status_code == 200

    fact = client.post(
        "/api/v1/memory",
        json={
            "project_id": project["id"],
            "content": "奇异值分解可以用于降维。",
            "category": "course.matrix.svd",
            "parent_memory_id": concept.json()["id"],
        },
        headers=csrf_headers(client, workspace_id),
    )
    assert fact.status_code == 200

    resolve_response = client.post(
        "/api/v1/memory/subjects/resolve",
        json={
            "project_id": project["id"],
            "conversation_id": conversation.json()["id"],
            "query": "线性代数里的矩阵分解",
        },
        headers=csrf_headers(client, workspace_id),
    )
    assert resolve_response.status_code == 200
    assert resolve_response.json()["primary_subject_id"] == subject.json()["id"]

    overview_response = client.get(
        f"/api/v1/memory/subjects/{subject.json()['id']}/overview",
        params={"conversation_id": conversation.json()["id"]},
        headers=csrf_headers(client, workspace_id),
    )
    assert overview_response.status_code == 200
    overview_body = overview_response.json()
    assert overview_body["subject"]["id"] == subject.json()["id"]
    assert any(node["id"] == concept.json()["id"] for node in overview_body["concepts"])
    assert any(node["id"] == fact.json()["id"] for node in overview_body["facts"])

    subgraph_response = client.post(
        f"/api/v1/memory/subjects/{subject.json()['id']}/subgraph?conversation_id={conversation.json()['id']}",
        json={"query": "奇异值分解", "depth": 2},
        headers=csrf_headers(client, workspace_id),
    )
    assert subgraph_response.status_code == 200
    subgraph_body = subgraph_response.json()
    node_ids = {node["id"] for node in subgraph_body["nodes"]}
    assert {subject.json()["id"], concept.json()["id"], fact.json()["id"]}.issubset(node_ids)
    assert any(edge["edge_type"] == "parent" for edge in subgraph_body["edges"])


def test_memory_sleep_cycle_task_backfills_reflection_and_health(monkeypatch) -> None:
    client = TestClient(main_module.app)
    owner_info = register_user(client, "memory-sleep-cycle@example.com", "Memory Sleep Cycle")
    workspace_id = owner_info["workspace"]["id"]
    project = create_project(client, "Memory Sleep Cycle Project")

    async def fake_chat_completion(*args, **kwargs):
        del args, kwargs
        return json.dumps({"skip": True}, ensure_ascii=False)

    monkeypatch.setattr(memory_compaction_service, "chat_completion", fake_chat_completion)

    with SessionLocal() as db:
        project_record = db.get(Project, project["id"])
        assert project_record is not None
        ensure_project_assistant_root(db, project_record, reparent_orphans=False)
        subject_memory, _ = ensure_project_user_subject(
            db,
            project_record,
            owner_user_id=owner_info["user"]["id"],
        )
        reconfirm_memory = Memory(
            workspace_id=workspace_id,
            project_id=project["id"],
            content="用户喜欢晚间复盘后再发日报。",
            category="偏好.复盘",
            type="permanent",
            parent_memory_id=subject_memory.id,
            subject_memory_id=subject_memory.id,
            metadata_json={
                "memory_kind": "preference",
                "single_source_explicit": True,
                "reconfirm_after": "2025-01-01T00:00:00+00:00",
            },
        )
        playbook_memory = Memory(
            workspace_id=workspace_id,
            project_id=project["id"],
            content="1. 先整理当天任务\n2. 再检查失败项\n3. 最后补一段复盘摘要",
            category="方法.复盘",
            type="permanent",
            parent_memory_id=subject_memory.id,
            subject_memory_id=subject_memory.id,
            metadata_json={"memory_kind": "fact"},
        )
        db.add_all([reconfirm_memory, playbook_memory])
        db.flush()
        learning_run = memory_v2_service.create_memory_learning_run(
            db,
            workspace_id=workspace_id,
            project_id=project["id"],
            trigger="post_turn",
            message_id="msg-memory-sleep-cycle",
            stages=["observe", "extract", "consolidate", "graphify"],
            metadata_json={"source": "test"},
        )
        memory_v2_service.finalize_memory_learning_run(
            learning_run,
            status="completed",
            stages=["observe", "extract", "consolidate", "graphify"],
            used_memory_ids=[reconfirm_memory.id],
        )
        outcome = memory_v2_service.create_memory_outcome(
            db,
            workspace_id=workspace_id,
            project_id=project["id"],
            message_id="msg-memory-sleep-cycle",
            status="success",
            feedback_source="system",
            summary="nightly reflection matched the remembered preference",
        )
        db.commit()
        learning_run_id = learning_run.id
        reconfirm_memory_id = reconfirm_memory.id
        assert outcome.id is not None

    summary = worker_tasks.run_project_memory_sleep_cycle_task(workspace_id, project["id"])
    assert summary["reflection_backfilled"] >= 1
    assert summary["health"]["reconfirm_count"] >= 1
    assert summary["subject_views"]["subjects_refreshed"] >= 1

    with SessionLocal() as db:
        refreshed_run = memory_v2_service.get_memory_learning_run(
            db,
            workspace_id=workspace_id,
            learning_run_id=learning_run_id,
        )
        refreshed_memory = db.get(Memory, reconfirm_memory_id)
        playbooks = memory_v2_service.list_project_playbook_views(
            db,
            workspace_id=workspace_id,
            project_id=project["id"],
        )
        assert refreshed_run is not None
        assert refreshed_memory is not None
        assert "reflect" in (refreshed_run.stages or [])
        assert "reuse" in (refreshed_run.stages or [])
        assert refreshed_run.outcome_id is not None
        health_flags = (refreshed_memory.metadata_json or {}).get("health_flags") or []
        assert "needs_reconfirm" in health_flags
        assert any(view.view_type == "playbook" for view in playbooks)


def test_memory_compaction_task_creates_summary_memory_and_edges(monkeypatch) -> None:
    client = TestClient(main_module.app)
    owner_info = register_user(client, "summary-memory@example.com", "Summary User")
    workspace_id = owner_info["workspace"]["id"]
    project = create_project(client, "Summary Project")

    async def fake_chat_completion(*args, **kwargs):
        return json.dumps(
            {
                "skip": False,
                "summary": "用户稳定关注数学学习，并且持续进行结构化训练。",
                "category": "学习.数学",
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr("app.services.memory_compaction.chat_completion", fake_chat_completion)

    source_ids: list[str] = []
    for content in (
        "用户正在系统学习数学分析。",
        "用户最近坚持做代数题训练。",
        "用户希望通过结构化方法提升数学竞赛能力。",
    ):
        response = client.post(
            "/api/v1/memory",
            json={
                "project_id": project["id"],
                "content": content,
                "category": "学习.数学",
            },
            headers=csrf_headers(client),
        )
        assert response.status_code == 200
        source_ids.append(response.json()["id"])

    worker_tasks.compact_project_memories_task(workspace_id, project["id"])

    with SessionLocal() as db:
        summaries = (
            db.query(MemoryView)
            .filter(
                MemoryView.project_id == project["id"],
                MemoryView.workspace_id == workspace_id,
                MemoryView.view_type == "summary",
            )
            .all()
        )
        summary = next(
            view for view in summaries if (view.metadata_json or {}).get("summary_group_key")
        )
        assert "稳定关注数学学习" in summary.content
        assert summary.metadata_json["source_count"] >= 3
        assert set(summary.metadata_json["source_memory_ids"]) >= set(source_ids)


def test_memory_compaction_removes_stale_summary_when_group_shrinks(monkeypatch) -> None:
    client = TestClient(main_module.app)
    owner_info = register_user(client, "summary-cleanup@example.com", "Summary Cleanup")
    workspace_id = owner_info["workspace"]["id"]
    project = create_project(client, "Summary Cleanup Project")

    async def fake_chat_completion(*args, **kwargs):
        return json.dumps(
            {
                "skip": False,
                "summary": "用户持续推进旅行规划，并记录了多个稳定目标。",
                "category": "生活.计划.旅行计划",
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr("app.services.memory_compaction.chat_completion", fake_chat_completion)

    memory_ids: list[str] = []
    for content in (
        "用户计划今年秋天去上海。",
        "用户准备为旅行制定预算。",
        "用户正在整理旅行行程清单。",
    ):
        response = client.post(
            "/api/v1/memory",
            json={
                "project_id": project["id"],
                "content": content,
                "category": "生活.计划.旅行计划",
            },
            headers=csrf_headers(client),
        )
        assert response.status_code == 200
        memory_ids.append(response.json()["id"])

    worker_tasks.compact_project_memories_task(workspace_id, project["id"])

    with SessionLocal() as db:
        summary = next(
            (
                view
                for view in db.query(MemoryView)
                .filter(
                    MemoryView.project_id == project["id"],
                    MemoryView.workspace_id == workspace_id,
                    MemoryView.view_type == "summary",
                )
                .all()
                if (view.metadata_json or {}).get("summary_group_key")
            ),
            None,
        )
        assert summary is not None
        summary_id = summary.id

    delete_resp = client.delete(
        f"/api/v1/memory/{memory_ids[0]}",
        headers=csrf_headers(client),
    )
    assert delete_resp.status_code == 204

    with SessionLocal() as db:
        assert db.get(MemoryView, summary_id) is None


def test_memory_compaction_uses_only_primary_active_fact_per_lineage(monkeypatch) -> None:
    client = TestClient(main_module.app)
    owner_info = register_user(client, "summary-lineage@example.com", "Summary Lineage")
    workspace_id = owner_info["workspace"]["id"]
    project = create_project(client, "Summary Lineage Project")

    async def fake_chat_completion(*args, **kwargs):
        return json.dumps(
            {
                "skip": False,
                "summary": "项目接口和部署信息已经稳定。",
                "category": "项目.接口",
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr("app.services.memory_compaction.chat_completion", fake_chat_completion)

    with SessionLocal() as db:
        project_row = db.get(Project, project["id"])
        assert project_row is not None
        ensure_project_assistant_root(db, project_row, reparent_orphans=False)
        subject, _ = ensure_project_user_subject(
            db,
            project_row,
            owner_user_id=owner_info["user"]["id"],
        )

        def _create_fact(
            content: str,
            *,
            lineage_key: str,
            salience: float,
        ) -> str:
            metadata = memory_metadata_service.normalize_memory_metadata(
                content=content,
                category="项目.接口",
                memory_type="permanent",
                metadata={
                    "node_type": "fact",
                    "node_status": "active",
                    "subject_memory_id": subject.id,
                    "lineage_key": lineage_key,
                    "salience": salience,
                },
            )
            memory = Memory(
                workspace_id=workspace_id,
                project_id=project["id"],
                content=content,
                category="项目.接口",
                type="permanent",
                node_type="fact",
                parent_memory_id=subject.id,
                subject_memory_id=subject.id,
                node_status="active",
                canonical_key=str(metadata.get("canonical_key") or "").strip() or None,
                lineage_key=lineage_key,
                metadata_json=metadata,
            )
            db.add(memory)
            db.flush()
            return memory.id

        primary_conflict_id = _create_fact(
            "项目当前使用 GraphQL API。",
            lineage_key="compaction-lineage-api",
            salience=0.95,
        )
        dropped_conflict_id = _create_fact(
            "项目当前使用 REST API。",
            lineage_key="compaction-lineage-api",
            salience=0.25,
        )
        deployment_id = _create_fact(
            "项目部署在欧洲区域。",
            lineage_key="compaction-lineage-region",
            salience=0.72,
        )
        auth_id = _create_fact(
            "项目接口要求 Bearer Token。",
            lineage_key="compaction-lineage-auth",
            salience=0.68,
        )
        db.add(
            MemoryEdge(
                source_memory_id=min(primary_conflict_id, dropped_conflict_id),
                target_memory_id=max(primary_conflict_id, dropped_conflict_id),
                edge_type="conflict",
                strength=0.83,
            )
        )
        db.commit()

    worker_tasks.compact_project_memories_task(workspace_id, project["id"])

    with SessionLocal() as db:
        summary = next(
            view for view in db.query(MemoryView)
            .filter(
                MemoryView.project_id == project["id"],
                MemoryView.workspace_id == workspace_id,
                MemoryView.view_type == "summary",
            )
            .all()
            if (view.metadata_json or {}).get("summary_group_key")
        )
        source_memory_ids = summary.metadata_json["source_memory_ids"]
        assert primary_conflict_id in source_memory_ids
        assert dropped_conflict_id not in source_memory_ids
        assert deployment_id in source_memory_ids
        assert auth_id in source_memory_ids
        assert summary.metadata_json["source_count"] == 3


def test_memory_graph_revision_increments_on_structure_mutations() -> None:
    client = TestClient(main_module.app)
    owner_info = register_user(client, "graph-revision@example.com", "Graph Revision")
    workspace_id = owner_info["workspace"]["id"]
    project = create_project(client, "Graph Revision Project")

    start_revision = memory_graph_events_service.get_project_memory_graph_revision(
        workspace_id=workspace_id,
        project_id=project["id"],
    )

    first = client.post(
        "/api/v1/memory",
        json={
            "project_id": project["id"],
            "content": "用户来自中国。",
            "category": "身份.国籍",
        },
        headers=csrf_headers(client),
    )
    assert first.status_code == 200
    after_first = memory_graph_events_service.get_project_memory_graph_revision(
        workspace_id=workspace_id,
        project_id=project["id"],
    )
    assert after_first > start_revision

    second = client.post(
        "/api/v1/memory",
        json={
            "project_id": project["id"],
            "content": "用户计划去上海。",
            "category": "生活.计划.旅行计划",
        },
        headers=csrf_headers(client),
    )
    assert second.status_code == 200
    after_second = memory_graph_events_service.get_project_memory_graph_revision(
        workspace_id=workspace_id,
        project_id=project["id"],
    )
    assert after_second > after_first

    edge = client.post(
        "/api/v1/memory/edges",
        json={
            "source_memory_id": first.json()["id"],
            "target_memory_id": second.json()["id"],
            "strength": 0.9,
        },
        headers=csrf_headers(client),
    )
    assert edge.status_code == 200
    after_edge_create = memory_graph_events_service.get_project_memory_graph_revision(
        workspace_id=workspace_id,
        project_id=project["id"],
    )
    assert after_edge_create > after_second

    remove_edge = client.delete(
        f"/api/v1/memory/edges/{edge.json()['id']}",
        headers=csrf_headers(client),
    )
    assert remove_edge.status_code == 204
    after_edge_delete = memory_graph_events_service.get_project_memory_graph_revision(
        workspace_id=workspace_id,
        project_id=project["id"],
    )
    assert after_edge_delete > after_edge_create

    delete_memory = client.delete(
        f"/api/v1/memory/{second.json()['id']}",
        headers=csrf_headers(client),
    )
    assert delete_memory.status_code == 204
    after_memory_delete = memory_graph_events_service.get_project_memory_graph_revision(
        workspace_id=workspace_id,
        project_id=project["id"],
    )
    assert after_memory_delete > after_edge_delete
