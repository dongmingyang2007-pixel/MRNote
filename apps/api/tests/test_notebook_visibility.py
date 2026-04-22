# ruff: noqa: E402
import atexit
import importlib
import os
import shutil
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-notebook-visibility-"))
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

from app.db.base import Base
import app.db.session as _s
from app.models import AIActionLog, Membership, Notebook, NotebookPage, Project


def setup_function() -> None:
    Base.metadata.drop_all(bind=_s.engine)
    Base.metadata.create_all(bind=_s.engine)
    from app.services.runtime_state import runtime_state
    runtime_state._memory = runtime_state._memory.__class__()


def _public_headers() -> dict[str, str]:
    return {"origin": "http://localhost:3000"}


def _register_client(email: str) -> tuple[TestClient, dict[str, str]]:
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
    resp = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "pass1234pass",
            "display_name": "Test",
            "code": code,
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


def test_private_notebook_is_hidden_from_workspace_members() -> None:
    _owner_client, owner_auth = _register_client("notebook-owner@x.co")
    member_client, member_auth = _register_client("notebook-member@x.co")

    with _s.SessionLocal() as db:
        project = Project(workspace_id=owner_auth["ws_id"], name="P")
        db.add(project); db.commit(); db.refresh(project)

        private_nb = Notebook(
            workspace_id=owner_auth["ws_id"],
            project_id=project.id,
            created_by=owner_auth["user_id"],
            title="Private NB",
            slug="private-nb",
            visibility="private",
        )
        public_nb = Notebook(
            workspace_id=owner_auth["ws_id"],
            project_id=project.id,
            created_by=owner_auth["user_id"],
            title="Public NB",
            slug="public-nb",
            visibility="public",
        )
        db.add(private_nb)
        db.add(public_nb)
        db.commit()
        db.refresh(private_nb)
        db.refresh(public_nb)

        private_page = NotebookPage(
            notebook_id=private_nb.id,
            created_by=owner_auth["user_id"],
            title="Secret page",
            slug="secret-page",
            plain_text="secret text",
        )
        public_page = NotebookPage(
            notebook_id=public_nb.id,
            created_by=owner_auth["user_id"],
            title="Shared page",
            slug="shared-page",
            plain_text="shared text",
        )
        db.add(private_page)
        db.add(public_page)
        db.add(Membership(
            workspace_id=owner_auth["ws_id"],
            user_id=member_auth["user_id"],
            role="member",
        ))
        db.add(AIActionLog(
            workspace_id=owner_auth["ws_id"],
            user_id=owner_auth["user_id"],
            notebook_id=private_nb.id,
            page_id=private_page.id,
            action_type="selection.rewrite",
            scope="selection",
            status="completed",
            output_summary="secret output",
            trace_metadata={},
        ))
        db.commit()
        private_nb_id = private_nb.id
        public_nb_id = public_nb.id
        private_page_id = private_page.id
        public_page_id = public_page.id

    member_client.headers["x-workspace-id"] = owner_auth["ws_id"]

    notebooks = member_client.get("/api/v1/notebooks")
    assert notebooks.status_code == 200, notebooks.text
    notebook_ids = {item["id"] for item in notebooks.json()["items"]}
    assert public_nb_id in notebook_ids
    assert private_nb_id not in notebook_ids

    assert member_client.get(f"/api/v1/notebooks/{private_nb_id}").status_code == 404
    assert member_client.get(f"/api/v1/notebooks/{private_nb_id}/pages").status_code == 404
    assert member_client.get(f"/api/v1/pages/{private_page_id}").status_code == 404

    home = member_client.get("/api/v1/notebooks/home")
    assert home.status_code == 200, home.text
    body = home.json()
    home_notebook_ids = {item["id"] for item in body["notebooks"]}
    assert public_nb_id in home_notebook_ids
    assert private_nb_id not in home_notebook_ids
    assert any(item["id"] == public_page_id for item in body["recent_pages"])
    assert all(item["id"] != private_page_id for item in body["recent_pages"])
    assert body["ai_today"]["recent_actions"] == []
