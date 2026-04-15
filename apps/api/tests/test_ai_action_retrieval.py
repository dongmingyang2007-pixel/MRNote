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
    # Reset runtime_state so rate-limit counters and verify_code entries
    # from a previous test do not leak into the next test.
    from app.services.runtime_state import runtime_state
    runtime_state._memory = runtime_state._memory.__class__()  # type: ignore[attr-defined]


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


def test_list_cross_workspace_isolation() -> None:
    """Workspace B cannot see workspace A's logs even with the same page-id-style request.

    Spec §9.3 case 3.
    """
    client_a, fx_a = _seed_n_logs(3, email="ws-a@x.co")
    client_b, fx_b = _seed_n_logs(2, email="ws-b@x.co")

    # Sanity: each workspace sees its own logs in isolation.
    a_only = client_a.get(f"/api/v1/pages/{fx_a['page_id']}/ai-actions").json()
    b_only = client_b.get(f"/api/v1/pages/{fx_b['page_id']}/ai-actions").json()
    assert len(a_only["items"]) == 3
    assert len(b_only["items"]) == 2

    # Cross-request: workspace B asks for workspace A's page → empty list,
    # not workspace A's data.
    cross = client_b.get(f"/api/v1/pages/{fx_a['page_id']}/ai-actions").json()
    assert cross["items"] == []
    assert cross["next_cursor"] is None


def test_detail_returns_full_payload() -> None:
    client, fx = _seed_n_logs(1, email="u3@x.co")
    list_resp = client.get(f"/api/v1/pages/{fx['page_id']}/ai-actions").json()
    log_id = list_resp["items"][0]["id"]

    resp = client.get(f"/api/v1/ai-actions/{log_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == log_id
    assert body["status"] == "completed"
    assert len(body["usage_events"]) == 1


def test_detail_404_when_unknown_id() -> None:
    client, _ = _register_client(email="u4@x.co")
    resp = client.get("/api/v1/ai-actions/does-not-exist")
    assert resp.status_code == 404


def test_detail_403_for_other_user_non_owner() -> None:
    """user_owner creates a log; user_member (same workspace but not owner)
    tries to read it -> 403."""
    owner_client, owner_auth = _register_client(email="owner@x.co")
    ws_id = owner_auth["ws_id"]
    owner_id = owner_auth["user_id"]
    with SessionLocal() as db:
        pr = Project(workspace_id=ws_id, name="P")
        db.add(pr); db.commit(); db.refresh(pr)
        nb = Notebook(workspace_id=ws_id, project_id=pr.id,
                      created_by=owner_id, title="NB", slug="nb")
        db.add(nb); db.commit(); db.refresh(nb)
        pg = NotebookPage(notebook_id=nb.id, created_by=owner_id,
                          title="T", slug="t", plain_text="x")
        db.add(pg); db.commit(); db.refresh(pg)
        log = AIActionLog(
            workspace_id=ws_id, user_id=owner_id,
            notebook_id=nb.id, page_id=pg.id,
            action_type="selection.rewrite", scope="selection",
            status="completed", trace_metadata={},
        )
        db.add(log); db.commit(); db.refresh(log)
        log_id = log.id

    member_client, member_auth = _register_client(email="member@x.co")
    member_id = member_auth["user_id"]
    with SessionLocal() as db:
        db.add(Membership(workspace_id=ws_id, user_id=member_id, role="member"))
        db.commit()
    member_client.headers["x-workspace-id"] = ws_id

    resp = member_client.get(f"/api/v1/ai-actions/{log_id}")
    assert resp.status_code == 403


def test_detail_dereferences_minio_overflow() -> None:
    import app.services.storage as storage_service
    from tests.fixtures.fake_s3 import FakeS3Client
    fake = FakeS3Client()
    fake.create_bucket(Bucket="ai-action-payloads")
    import json as _json
    big_payload = {"q": "x" * 20_000}
    fake.put_object(
        Bucket="ai-action-payloads",
        Key="some-key/input.json",
        Body=_json.dumps(big_payload).encode("utf-8"),
        ContentType="application/json",
    )
    cache_clear = getattr(storage_service.get_s3_client, "cache_clear", None)
    if cache_clear:
        cache_clear()
    storage_service.get_s3_client = lambda: fake  # type: ignore[assignment]

    client, auth = _register_client(email="u5@x.co")
    ws_id = auth["ws_id"]; user_id = auth["user_id"]
    with SessionLocal() as db:
        pr = Project(workspace_id=ws_id, name="P")
        db.add(pr); db.commit(); db.refresh(pr)
        nb = Notebook(workspace_id=ws_id, project_id=pr.id, created_by=user_id,
                      title="NB", slug="nb")
        db.add(nb); db.commit(); db.refresh(nb)
        pg = NotebookPage(notebook_id=nb.id, created_by=user_id, title="T",
                          slug="t", plain_text="x")
        db.add(pg); db.commit(); db.refresh(pg)
        log = AIActionLog(
            workspace_id=ws_id, user_id=user_id,
            notebook_id=nb.id, page_id=pg.id,
            action_type="ask", scope="page", status="completed",
            input_json={"_overflow_ref": "some-key/input.json", "_preview": "x" * 500},
            trace_metadata={},
        )
        db.add(log); db.commit(); db.refresh(log)
        log_id = log.id

    resp = client.get(f"/api/v1/ai-actions/{log_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["input_json"]["q"] == "x" * 20_000
