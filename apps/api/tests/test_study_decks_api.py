# ruff: noqa: E402
import atexit, importlib, os, shutil, tempfile
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-s4-decks-api-"))
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
from app.models import Notebook, Project, StudyDeck, User, Workspace


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


def _seed_notebook(ws_id: str, user_id: str) -> str:
    with SessionLocal() as db:
        pr = Project(workspace_id=ws_id, name="P"); db.add(pr); db.commit(); db.refresh(pr)
        nb = Notebook(workspace_id=ws_id, project_id=pr.id, created_by=user_id,
                      title="NB", slug="nb")
        db.add(nb); db.commit(); db.refresh(nb)
        return nb.id


def test_create_and_list_decks() -> None:
    client, auth = _register_client("u1@x.co")
    nb_id = _seed_notebook(auth["ws_id"], auth["user_id"])

    resp = client.post(
        f"/api/v1/notebooks/{nb_id}/decks",
        json={"name": "My deck", "description": "test"},
    )
    assert resp.status_code == 200, resp.text
    created = resp.json()
    assert created["name"] == "My deck"
    assert created["card_count"] == 0

    list_resp = client.get(f"/api/v1/notebooks/{nb_id}/decks")
    assert list_resp.status_code == 200
    body = list_resp.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == created["id"]


def test_patch_deck_rename_and_archive() -> None:
    client, auth = _register_client("u2@x.co")
    nb_id = _seed_notebook(auth["ws_id"], auth["user_id"])
    deck = client.post(
        f"/api/v1/notebooks/{nb_id}/decks",
        json={"name": "before", "description": ""},
    ).json()

    patched = client.patch(
        f"/api/v1/decks/{deck['id']}",
        json={"name": "after", "archived": True},
    ).json()
    assert patched["name"] == "after"
    assert patched["archived_at"] is not None


def test_cross_workspace_deck_access_404() -> None:
    # Owner creates a deck.
    _client_a, auth_a = _register_client("a@x.co")
    nb_id = _seed_notebook(auth_a["ws_id"], auth_a["user_id"])
    # Use _client_a directly so we need to make it again to POST
    client_a, _auth2 = _register_client("a@x.co") if False else (_client_a, auth_a)
    deck = client_a.post(
        f"/api/v1/notebooks/{nb_id}/decks",
        json={"name": "secret"},
    ).json()

    # Second workspace tries to see it.
    client_b, _ = _register_client("b@x.co")
    resp = client_b.get(f"/api/v1/decks/{deck['id']}")
    assert resp.status_code == 404
