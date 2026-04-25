# ruff: noqa: E402
import atexit, importlib, os, shutil, tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="mrnote-s4-review-"))
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
from app.models import AIActionLog, Notebook, Project, StudyCard, StudyDeck, User, Workspace


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


def _make_deck_with_cards(client: TestClient, user_id: str, ws_id: str, n_cards: int = 1) -> tuple[str, list[str]]:
    with SessionLocal() as db:
        pr = Project(workspace_id=ws_id, name="P"); db.add(pr); db.commit(); db.refresh(pr)
        nb = Notebook(workspace_id=ws_id, project_id=pr.id, created_by=user_id,
                      title="NB", slug="nb")
        db.add(nb); db.commit(); db.refresh(nb)
    deck = client.post(
        f"/api/v1/notebooks/{nb.id}/decks",
        json={"name": "D"},
    ).json()
    card_ids: list[str] = []
    for i in range(n_cards):
        c = client.post(
            f"/api/v1/decks/{deck['id']}/cards",
            json={"front": f"Q{i}", "back": f"A{i}"},
        ).json()
        card_ids.append(c["id"])
    return deck["id"], card_ids


def test_review_next_returns_card_or_empty() -> None:
    client, auth = _register_client("r1@x.co")
    deck_id, cards = _make_deck_with_cards(client, auth["user_id"], auth["ws_id"], n_cards=1)

    resp = client.post(f"/api/v1/decks/{deck_id}/review/next")
    assert resp.status_code == 200
    body = resp.json()
    assert body["card"] is not None
    assert body["card"]["id"] == cards[0]

    # Mark it as reviewed, then expect queue empty (next_review_at in future).
    client.post(f"/api/v1/cards/{cards[0]}/review", json={"rating": 3})
    resp2 = client.post(f"/api/v1/decks/{deck_id}/review/next").json()
    assert resp2["card"] is None
    assert resp2["queue_empty"] is True


def test_review_good_updates_fsrs_and_logs() -> None:
    client, auth = _register_client("r2@x.co")
    deck_id, cards = _make_deck_with_cards(client, auth["user_id"], auth["ws_id"], n_cards=1)
    card_id = cards[0]

    resp = client.post(f"/api/v1/cards/{card_id}/review", json={"rating": 3})
    assert resp.status_code == 200, resp.text

    with SessionLocal() as db:
        card = db.query(StudyCard).filter_by(id=card_id).one()
        assert card.review_count == 1
        assert card.stability > 0
        assert card.next_review_at is not None
        assert card.last_review_at is not None
        assert card.consecutive_failures == 0

        log = (
            db.query(AIActionLog)
            .filter(AIActionLog.action_type == "study.review_card")
            .one()
        )
        assert log.block_id == card_id


def test_review_again_bumps_consecutive_failures_and_schedules_confusion_task() -> None:
    client, auth = _register_client("r3@x.co")
    deck_id, cards = _make_deck_with_cards(client, auth["user_id"], auth["ws_id"], n_cards=1)
    card_id = cards[0]

    # Three consecutive Again calls. Patch the Celery .delay() to observe.
    with patch(
        "app.tasks.worker_tasks.process_study_confusion_task.delay",
    ) as delay_mock:
        for _ in range(3):
            client.post(f"/api/v1/cards/{card_id}/review", json={"rating": 1})

    assert delay_mock.call_count == 1
    args, kwargs = delay_mock.call_args
    assert args[0] == card_id
    assert args[3] == "consecutive_failures"

    with SessionLocal() as db:
        card = db.query(StudyCard).filter_by(id=card_id).one()
        assert card.lapse_count == 3
        assert card.confusion_memory_written_at is not None


def test_review_marked_confused_flag_fires_task_once() -> None:
    client, auth = _register_client("r4@x.co")
    deck_id, cards = _make_deck_with_cards(client, auth["user_id"], auth["ws_id"], n_cards=1)
    card_id = cards[0]

    with patch(
        "app.tasks.worker_tasks.process_study_confusion_task.delay",
    ) as delay_mock:
        client.post(
            f"/api/v1/cards/{card_id}/review",
            json={"rating": 3, "marked_confused": True},
        )
        # Second mark on the same card should NOT fire again — memory_written_at is set.
        client.post(
            f"/api/v1/cards/{card_id}/review",
            json={"rating": 3, "marked_confused": True},
        )

    assert delay_mock.call_count == 1
    args, kwargs = delay_mock.call_args
    assert args[3] == "manual"
