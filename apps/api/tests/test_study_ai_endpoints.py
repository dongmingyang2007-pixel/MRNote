# ruff: noqa: E402
import atexit, importlib, os, shutil, tempfile
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-s4-study-ai-"))
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
from unittest.mock import AsyncMock, patch

from app.db.base import Base
import app.db.session as _s
from app.models import (
    AIActionLog, Notebook, NotebookPage, Project, StudyAsset, StudyCard, StudyDeck, User, Workspace,
)


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


def _seed_page(ws_id: str, user_id: str, text: str = "some page text") -> tuple[str, str]:
    with SessionLocal() as db:
        pr = Project(workspace_id=ws_id, name="P"); db.add(pr); db.commit(); db.refresh(pr)
        nb = Notebook(workspace_id=ws_id, project_id=pr.id, created_by=user_id,
                      title="NB", slug="nb"); db.add(nb); db.commit(); db.refresh(nb)
        pg = NotebookPage(notebook_id=nb.id, created_by=user_id, title="T",
                          slug="t", plain_text=text); db.add(pg); db.commit(); db.refresh(pg)
        return nb.id, pg.id


FAKE_FLASHCARDS_JSON = """
{"cards": [
  {"front": "What is X?", "back": "X is a concept."},
  {"front": "Why X?",     "back": "Because."}
]}
""".strip()


def test_flashcards_preview_returns_cards_without_persisting() -> None:
    client, auth = _register_client("u1@x.co")
    _, page_id = _seed_page(auth["ws_id"], auth["user_id"], "foundational text")

    fake = AsyncMock(return_value=FAKE_FLASHCARDS_JSON)
    with patch("app.routers.study_ai._run_llm_json", fake):
        resp = client.post(
            "/api/v1/ai/study/flashcards",
            json={"source_type": "page", "source_id": page_id, "count": 2},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["cards"]) == 2
    assert body["card_ids"] is None

    with SessionLocal() as db:
        # No cards inserted.
        assert db.query(StudyCard).count() == 0
        # Action log present.
        log = db.query(AIActionLog).filter_by(action_type="study.flashcards").one()
        assert log.page_id == page_id


def test_flashcards_with_deck_id_persists_cards() -> None:
    client, auth = _register_client("u2@x.co")
    nb_id, page_id = _seed_page(auth["ws_id"], auth["user_id"], "text")
    deck = client.post(
        f"/api/v1/notebooks/{nb_id}/decks",
        json={"name": "D"},
    ).json()

    fake = AsyncMock(return_value=FAKE_FLASHCARDS_JSON)
    with patch("app.routers.study_ai._run_llm_json", fake):
        resp = client.post(
            "/api/v1/ai/study/flashcards",
            json={"source_type": "page", "source_id": page_id, "count": 2,
                  "deck_id": deck["id"]},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["card_ids"]) == 2

    with SessionLocal() as db:
        cards = db.query(StudyCard).all()
        assert len(cards) == 2
        assert all(c.source_type == "page_ai" and c.source_ref == page_id for c in cards)
        deck_row = db.query(StudyDeck).filter_by(id=deck["id"]).one()
        assert deck_row.card_count == 2


def test_flashcards_bad_llm_output_returns_422() -> None:
    client, auth = _register_client("u3@x.co")
    _, page_id = _seed_page(auth["ws_id"], auth["user_id"])
    fake = AsyncMock(return_value="not json at all")
    with patch("app.routers.study_ai._run_llm_json", fake):
        resp = client.post(
            "/api/v1/ai/study/flashcards",
            json={"source_type": "page", "source_id": page_id},
        )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "llm_bad_output"


FAKE_QUIZ_JSON = """
{"questions": [
  {
    "question": "What is X?",
    "options": ["a","b","c","d"],
    "correct_index": 2,
    "explanation": "because…"
  }
]}
""".strip()


def test_quiz_returns_valid_mcq_schema() -> None:
    client, auth = _register_client("u_quiz@x.co")
    _, page_id = _seed_page(auth["ws_id"], auth["user_id"], "text")

    fake = AsyncMock(return_value=FAKE_QUIZ_JSON)
    with patch("app.routers.study_ai._run_llm_json", fake):
        resp = client.post(
            "/api/v1/ai/study/quiz",
            json={"source_type": "page", "source_id": page_id, "count": 1},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["questions"]) == 1
    q = body["questions"][0]
    assert len(q["options"]) == 4
    assert 0 <= q["correct_index"] < 4

    with SessionLocal() as db:
        assert db.query(AIActionLog).filter_by(action_type="study.quiz").count() == 1


def test_quiz_bad_shape_returns_422() -> None:
    client, auth = _register_client("u_quiz2@x.co")
    _, page_id = _seed_page(auth["ws_id"], auth["user_id"], "text")

    bad = '{"questions": [{"question": "Q", "options": ["a","b"], "correct_index": 0, "explanation": ""}]}'
    fake = AsyncMock(return_value=bad)
    with patch("app.routers.study_ai._run_llm_json", fake):
        resp = client.post(
            "/api/v1/ai/study/quiz",
            json={"source_type": "page", "source_id": page_id, "count": 1},
        )
    assert resp.status_code == 422


async def _fake_ask_stream(*_a, **_kw):
    from app.services.dashscope_stream import StreamChunk
    yield StreamChunk(content="answer text", finish_reason=None)
    yield StreamChunk(
        content="", finish_reason="stop",
        usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        model_id="qwen-plus",
    )


def test_ask_streaming_produces_action_log_with_sources() -> None:
    client, auth = _register_client("u_ask@x.co")

    # Seed a notebook + study asset to scope the ask.
    with SessionLocal() as db:
        pr = Project(workspace_id=auth["ws_id"], name="P"); db.add(pr); db.commit(); db.refresh(pr)
        nb = Notebook(workspace_id=auth["ws_id"], project_id=pr.id, created_by=auth["user_id"],
                      title="NB", slug="nb"); db.add(nb); db.commit(); db.refresh(nb)
        asset = StudyAsset(
            notebook_id=nb.id, title="Book",
            created_by=auth["user_id"],
        )
        db.add(asset); db.commit(); db.refresh(asset)
        asset_id = asset.id

    with patch(
        "app.routers.study_ai.chat_completion_stream",
        side_effect=lambda *a, **kw: _fake_ask_stream(),
    ), patch(
        "app.routers.study_ai.assemble_study_context",
        return_value=({"system_prompt": "SYS"}, [{"type": "chunk", "id": "c1", "title": "Chapter 1"}]),
    ):
        resp = client.post(
            "/api/v1/ai/study/ask",
            json={"asset_id": asset_id, "message": "what about X?"},
        )
        _ = resp.text  # drain SSE

    assert resp.status_code == 200
    with SessionLocal() as db:
        log = db.query(AIActionLog).filter_by(action_type="study.ask").one()
        assert log.trace_metadata.get("retrieval_sources")
