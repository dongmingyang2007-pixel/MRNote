# ruff: noqa: E402
import atexit, importlib, os, shutil, tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="mrnote-s5-api-"))
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
import app.db.session as _s
from app.models import ProactiveDigest


def setup_function() -> None:
    global engine, SessionLocal
    engine = _s.engine
    SessionLocal = _s.SessionLocal
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    from app.services.runtime_state import runtime_state
    runtime_state._memory = runtime_state._memory.__class__()
    import app.tasks.worker_tasks as _wt
    _wt.SessionLocal = _s.SessionLocal


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


def _seed_digest(ws_id: str, user_id: str, **kwargs) -> str:
    from app.models import Project
    with SessionLocal() as db:
        pr = Project(workspace_id=ws_id, name="P")
        db.add(pr); db.commit(); db.refresh(pr)
        d = ProactiveDigest(
            workspace_id=ws_id, project_id=pr.id, user_id=user_id,
            kind=kwargs.get("kind", "daily_digest"),
            period_start=datetime.now(timezone.utc) - timedelta(hours=24),
            period_end=datetime.now(timezone.utc),
            title=kwargs.get("title", "Daily"),
            content_markdown=kwargs.get("content_markdown", "hi"),
            content_json={"summary_md": "hi"},
            status=kwargs.get("status", "unread"),
        )
        db.add(d); db.commit(); db.refresh(d)
        return d.id


def test_list_returns_unread_first() -> None:
    client, auth = _register_client("u1@x.co")
    d_id = _seed_digest(auth["ws_id"], auth["user_id"])
    resp = client.get("/api/v1/digests?status=unread")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["id"] == d_id
    assert body["unread_count"] == 1


def test_detail_returns_full_row() -> None:
    client, auth = _register_client("u2@x.co")
    d_id = _seed_digest(auth["ws_id"], auth["user_id"])
    resp = client.get(f"/api/v1/digests/{d_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["content_markdown"] == "hi"


def test_read_marks_row_read() -> None:
    client, auth = _register_client("u3@x.co")
    d_id = _seed_digest(auth["ws_id"], auth["user_id"])
    resp = client.post(f"/api/v1/digests/{d_id}/read")
    assert resp.status_code == 200
    detail = client.get(f"/api/v1/digests/{d_id}").json()
    assert detail["status"] == "read"
    assert detail["read_at"] is not None


def test_dismiss_marks_row_dismissed() -> None:
    client, auth = _register_client("u4@x.co")
    d_id = _seed_digest(auth["ws_id"], auth["user_id"])
    client.post(f"/api/v1/digests/{d_id}/dismiss")
    detail = client.get(f"/api/v1/digests/{d_id}").json()
    assert detail["status"] == "dismissed"


def test_unread_count_endpoint() -> None:
    client, auth = _register_client("u5@x.co")
    _seed_digest(auth["ws_id"], auth["user_id"], kind="daily_digest")
    _seed_digest(auth["ws_id"], auth["user_id"], kind="weekly_reflection")
    resp = client.get("/api/v1/digests/unread-count")
    assert resp.status_code == 200
    assert resp.json()["unread_count"] == 2


def test_cross_workspace_returns_404() -> None:
    _client_a, auth_a = _register_client("a@x.co")
    d_id = _seed_digest(auth_a["ws_id"], auth_a["user_id"])
    client_b, _ = _register_client("b@x.co")
    resp = client_b.get(f"/api/v1/digests/{d_id}")
    assert resp.status_code == 404


def test_cross_workspace_read_returns_404() -> None:
    _client_a, auth_a = _register_client("rwa@x.co")
    d_id = _seed_digest(auth_a["ws_id"], auth_a["user_id"])
    client_b, _ = _register_client("rwb@x.co")
    resp = client_b.post(f"/api/v1/digests/{d_id}/read")
    assert resp.status_code == 404


def test_cross_workspace_dismiss_returns_404() -> None:
    _client_a, auth_a = _register_client("rda@x.co")
    d_id = _seed_digest(auth_a["ws_id"], auth_a["user_id"])
    client_b, _ = _register_client("rdb@x.co")
    resp = client_b.post(f"/api/v1/digests/{d_id}/dismiss")
    assert resp.status_code == 404


def test_unread_count_is_workspace_scoped() -> None:
    _client_a, auth_a = _register_client("uca@x.co")
    _seed_digest(auth_a["ws_id"], auth_a["user_id"], status="unread")
    _seed_digest(auth_a["ws_id"], auth_a["user_id"], status="unread")

    client_b, _ = _register_client("ucb@x.co")
    resp = client_b.get("/api/v1/digests/unread-count")
    assert resp.status_code == 200
    assert resp.json()["unread_count"] == 0


def test_digest_visible_to_other_workspace_member() -> None:
    _client_a, auth_a = _register_client("vwa@x.co")
    d_id = _seed_digest(auth_a["ws_id"], auth_a["user_id"])
    client_b, auth_b = _register_client("vwb@x.co")

    from app.models import Membership
    with SessionLocal() as db:
        db.add(Membership(
            workspace_id=auth_a["ws_id"],
            user_id=auth_b["user_id"],
            role="editor",
        ))
        db.commit()

    client_b.headers.update({"x-workspace-id": auth_a["ws_id"]})
    resp = client_b.get(f"/api/v1/digests/{d_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == d_id


def test_unread_count_visible_to_other_workspace_member() -> None:
    _client_a, auth_a = _register_client("uwa@x.co")
    _seed_digest(auth_a["ws_id"], auth_a["user_id"], status="unread")
    _seed_digest(auth_a["ws_id"], auth_a["user_id"], status="unread")
    client_b, auth_b = _register_client("uwb@x.co")

    from app.models import Membership
    with SessionLocal() as db:
        db.add(Membership(
            workspace_id=auth_a["ws_id"],
            user_id=auth_b["user_id"],
            role="editor",
        ))
        db.commit()

    client_b.headers.update({"x-workspace-id": auth_a["ws_id"]})
    resp = client_b.get("/api/v1/digests/unread-count")
    assert resp.status_code == 200
    assert resp.json()["unread_count"] == 2


def test_generate_now_enqueues_task() -> None:
    client, auth = _register_client("u7@x.co")
    from app.models import Project, Subscription
    from app.core.entitlements import refresh_workspace_entitlements
    with SessionLocal() as db:
        pr = Project(workspace_id=auth["ws_id"], name="P")
        db.add(pr); db.commit(); db.refresh(pr)
        project_id = pr.id
        # Upgrade to pro so daily_digest.enabled = True passes the gate.
        sub = Subscription(
            workspace_id=auth["ws_id"],
            plan="pro",
            status="active",
            provider="free",
            billing_cycle="monthly",
        )
        db.add(sub); db.commit()
        refresh_workspace_entitlements(db, workspace_id=auth["ws_id"])

    with patch(
        "app.tasks.worker_tasks.generate_proactive_digest_task.delay",
    ) as delay_mock:
        resp = client.post(
            "/api/v1/digests/generate-now",
            json={"kind": "daily_digest", "project_id": project_id},
        )
    assert resp.status_code == 200
    assert delay_mock.call_count == 1
    args = delay_mock.call_args[0]
    assert args[0] == project_id
    assert args[1] == "daily_digest"
