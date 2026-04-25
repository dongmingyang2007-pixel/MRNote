# ruff: noqa: E402
import atexit, importlib, os, shutil, tempfile
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="mrnote-s4-cards-api-"))
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


def _seed_deck(client: TestClient, user_id: str, ws_id: str) -> tuple[str, str]:
    with SessionLocal() as db:
        pr = Project(workspace_id=ws_id, name="P"); db.add(pr); db.commit(); db.refresh(pr)
        nb = Notebook(workspace_id=ws_id, project_id=pr.id, created_by=user_id,
                      title="NB", slug="nb")
        db.add(nb); db.commit(); db.refresh(nb)
    deck = client.post(
        f"/api/v1/notebooks/{nb.id}/decks",
        json={"name": "D"},
    ).json()
    return nb.id, deck["id"]


def test_create_and_list_cards_updates_count() -> None:
    client, auth = _register_client("u1@x.co")
    _, deck_id = _seed_deck(client, auth["user_id"], auth["ws_id"])

    resp = client.post(
        f"/api/v1/decks/{deck_id}/cards",
        json={"front": "Q", "back": "A"},
    )
    assert resp.status_code == 200, resp.text
    card = resp.json()
    assert card["source_type"] == "manual"

    list_resp = client.get(f"/api/v1/decks/{deck_id}/cards").json()
    assert len(list_resp["items"]) == 1

    deck_resp = client.get(f"/api/v1/decks/{deck_id}").json()
    assert deck_resp["card_count"] == 1


def test_delete_card_decrements_deck_count() -> None:
    client, auth = _register_client("u2@x.co")
    _, deck_id = _seed_deck(client, auth["user_id"], auth["ws_id"])

    card = client.post(
        f"/api/v1/decks/{deck_id}/cards",
        json={"front": "Q", "back": "A"},
    ).json()
    client.delete(f"/api/v1/cards/{card['id']}")

    deck_resp = client.get(f"/api/v1/decks/{deck_id}").json()
    assert deck_resp["card_count"] == 0


def test_list_cards_due_only_filter() -> None:
    client, auth = _register_client("u3@x.co")
    _, deck_id = _seed_deck(client, auth["user_id"], auth["ws_id"])
    # Two cards: one new (next_review_at NULL), one already due in the future.
    card_a = client.post(
        f"/api/v1/decks/{deck_id}/cards",
        json={"front": "Q1", "back": "A1"},
    ).json()
    card_b = client.post(
        f"/api/v1/decks/{deck_id}/cards",
        json={"front": "Q2", "back": "A2"},
    ).json()
    # Push card_b into the future via a Good review.
    client.post(f"/api/v1/cards/{card_b['id']}/review", json={"rating": 3})

    due = client.get(f"/api/v1/decks/{deck_id}/cards?due_only=true").json()
    ids = {i["id"] for i in due["items"]}
    assert card_a["id"] in ids
    assert card_b["id"] not in ids
