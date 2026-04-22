# ruff: noqa: E402
import asyncio
import atexit, importlib, os, shutil, tempfile
import io
from datetime import datetime, timedelta, timezone
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
    AIActionLog, DataItem, Dataset, Notebook, NotebookPage, Project, StudyAsset, StudyCard, StudyChunk, StudyDeck, User, Workspace,
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


def test_global_study_asset_routes_match_build_spec() -> None:
    client, auth = _register_client("u_routes@x.co")

    with SessionLocal() as db:
        pr = Project(workspace_id=auth["ws_id"], name="P"); db.add(pr); db.commit(); db.refresh(pr)
        nb = Notebook(
            workspace_id=auth["ws_id"],
            project_id=pr.id,
            created_by=auth["user_id"],
            title="NB",
            slug="nb",
        )
        db.add(nb); db.commit(); db.refresh(nb)
        asset = StudyAsset(
            notebook_id=nb.id,
            title="Course Slides",
            created_by=auth["user_id"],
            status="indexed",
            total_chunks=2,
        )
        db.add(asset); db.commit(); db.refresh(asset)
        db.add_all([
            StudyChunk(asset_id=asset.id, chunk_index=0, heading="Intro", content="chunk 1"),
            StudyChunk(asset_id=asset.id, chunk_index=1, heading="Deep Dive", content="chunk 2"),
        ])
        db.commit()

        notebook_id = nb.id
        asset_id = asset.id

    detail = client.get(f"/api/v1/study-assets/{asset_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["id"] == asset_id

    aliased_list = client.get(f"/api/v1/notebooks/{notebook_id}/study-assets")
    assert aliased_list.status_code == 200, aliased_list.text
    assert [item["id"] for item in aliased_list.json()["items"]] == [asset_id]

    aliased_chunks = client.get(f"/api/v1/notebooks/{notebook_id}/study-assets/{asset_id}/chunks")
    assert aliased_chunks.status_code == 200, aliased_chunks.text
    assert [item["heading"] for item in aliased_chunks.json()["items"]] == ["Intro", "Deep Dive"]

    chunks = client.get(f"/api/v1/study-assets/{asset_id}/chunks")
    assert chunks.status_code == 200, chunks.text
    assert [item["heading"] for item in chunks.json()["items"]] == ["Intro", "Deep Dive"]

    with patch("app.tasks.worker_tasks.ingest_study_asset_task.delay") as delay:
        resp = client.post(f"/api/v1/study-assets/{asset_id}/ingest")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "queued"
    delay.assert_called_once()


def test_create_study_asset_rejects_foreign_workspace_data_item() -> None:
    client_a, auth_a = _register_client("study-owner-a@x.co")
    _client_b, auth_b = _register_client("study-owner-b@x.co")

    with SessionLocal() as db:
        project_a = Project(workspace_id=auth_a["ws_id"], name="P-A")
        db.add(project_a); db.commit(); db.refresh(project_a)
        notebook_a = Notebook(
            workspace_id=auth_a["ws_id"],
            project_id=project_a.id,
            created_by=auth_a["user_id"],
            title="Notebook A",
            slug="notebook-a",
        )
        db.add(notebook_a); db.commit(); db.refresh(notebook_a)

        project_b = Project(workspace_id=auth_b["ws_id"], name="P-B")
        db.add(project_b); db.commit(); db.refresh(project_b)
        dataset_b = Dataset(project_id=project_b.id, name="Docs", type="docs")
        db.add(dataset_b); db.commit(); db.refresh(dataset_b)
        foreign_item = DataItem(
            dataset_id=dataset_b.id,
            object_key="workspaces/foreign/doc.pdf",
            filename="doc.pdf",
            media_type="application/pdf",
            size_bytes=42,
        )
        db.add(foreign_item); db.commit(); db.refresh(foreign_item)
        notebook_a_id = notebook_a.id
        foreign_item_id = foreign_item.id

    resp = client_a.post(
        f"/api/v1/notebooks/{notebook_a_id}/study-assets",
        json={"title": "Foreign file", "data_item_id": foreign_item_id},
    )
    assert resp.status_code == 404, resp.text


def test_ingest_study_asset_fails_when_data_item_is_outside_workspace() -> None:
    client_a, auth_a = _register_client("study-pipeline-a@x.co")
    _client_b, auth_b = _register_client("study-pipeline-b@x.co")

    with SessionLocal() as db:
        project_a = Project(workspace_id=auth_a["ws_id"], name="P-A")
        db.add(project_a); db.commit(); db.refresh(project_a)
        notebook_a = Notebook(
            workspace_id=auth_a["ws_id"],
            project_id=project_a.id,
            created_by=auth_a["user_id"],
            title="Notebook A",
            slug="notebook-a",
        )
        db.add(notebook_a); db.commit(); db.refresh(notebook_a)

        project_b = Project(workspace_id=auth_b["ws_id"], name="P-B")
        db.add(project_b); db.commit(); db.refresh(project_b)
        dataset_b = Dataset(project_id=project_b.id, name="Docs", type="docs")
        db.add(dataset_b); db.commit(); db.refresh(dataset_b)
        foreign_item = DataItem(
            dataset_id=dataset_b.id,
            object_key="workspaces/foreign/doc.pdf",
            filename="doc.pdf",
            media_type="application/pdf",
            size_bytes=42,
        )
        db.add(foreign_item); db.commit(); db.refresh(foreign_item)

        asset = StudyAsset(
            notebook_id=notebook_a.id,
            data_item_id=foreign_item.id,
            title="Foreign file",
            created_by=auth_a["user_id"],
            status="pending",
        )
        db.add(asset); db.commit(); db.refresh(asset)
        asset_id = asset.id

        from app.services.study_pipeline import ingest_study_asset

        asyncio.run(
            ingest_study_asset(
                db,
                asset_id=asset_id,
                workspace_id=auth_a["ws_id"],
                user_id=auth_a["user_id"],
            )
        )
        db.refresh(asset)
        assert asset.status == "failed"
        assert db.query(StudyChunk).filter(StudyChunk.asset_id == asset_id).count() == 0


def test_ingest_study_asset_indexes_unknown_binary_file_with_fallback_summary() -> None:
    client, auth = _register_client("study-fallback@example.com")
    payload = b"\x00\x01weights\x02\x03model-data"

    with SessionLocal() as db:
        project = Project(workspace_id=auth["ws_id"], name="Docs Project")
        db.add(project)
        db.commit()
        db.refresh(project)

        dataset = Dataset(project_id=project.id, name="Docs", type="docs")
        db.add(dataset)
        db.commit()
        db.refresh(dataset)

        notebook = Notebook(
            workspace_id=auth["ws_id"],
            created_by=auth["user_id"],
            title="Fallback Notebook",
            slug="fallback-notebook",
        )
        db.add(notebook)
        db.commit()
        db.refresh(notebook)

        data_item = DataItem(
            dataset_id=dataset.id,
            object_key="workspaces/test/weights.gguf",
            filename="weights.gguf",
            media_type="application/octet-stream",
            size_bytes=len(payload),
        )
        db.add(data_item)
        db.commit()
        db.refresh(data_item)

        asset = StudyAsset(
            notebook_id=notebook.id,
            data_item_id=data_item.id,
            title="Weights file",
            asset_type="file",
            status="pending",
            created_by=auth["user_id"],
        )
        db.add(asset)
        db.commit()
        db.refresh(asset)
        asset_id = asset.id
        notebook_id = notebook.id

    class StubS3Client:
        def get_object(self, *, Bucket: str, Key: str, **_: object) -> dict[str, object]:
            assert Key == "workspaces/test/weights.gguf"
            return {"Body": io.BytesIO(payload)}

    with patch("app.services.study_pipeline.get_s3_client", return_value=StubS3Client()):
        from app.services.study_pipeline import ingest_study_asset

        with SessionLocal() as db:
            asyncio.run(
                ingest_study_asset(
                    db,
                    asset_id=asset_id,
                    workspace_id=auth["ws_id"],
                    user_id=auth["user_id"],
                )
            )

            asset = db.get(StudyAsset, asset_id)
            assert asset is not None
            assert asset.status == "indexed"
            assert asset.total_chunks == 1
            assert (asset.metadata_json or {}).get("ingest_mode") == "fallback"
            assert (asset.metadata_json or {}).get("source_filename") == "weights.gguf"

            chunk = db.query(StudyChunk).filter(StudyChunk.asset_id == asset_id).one()
            assert "Uploaded file summary" in chunk.content
            assert "weights.gguf" in chunk.content

            overview_page = (
                db.query(NotebookPage)
                .filter(
                    NotebookPage.notebook_id == notebook_id,
                    NotebookPage.slug == f"study-asset-{asset_id}-overview",
                )
                .one()
            )
            assert "fallback summary" in (overview_page.plain_text or "")


def test_study_insights_aggregates_progress_and_weekly_activity() -> None:
    client, auth = _register_client("study-insights@example.com")
    now = datetime.now(timezone.utc)

    with SessionLocal() as db:
        project = Project(workspace_id=auth["ws_id"], name="Study Project")
        db.add(project)
        db.commit()
        db.refresh(project)

        notebook = Notebook(
            workspace_id=auth["ws_id"],
            project_id=project.id,
            created_by=auth["user_id"],
            title="Distributed Systems",
            slug="distributed-systems",
        )
        db.add(notebook)
        db.commit()
        db.refresh(notebook)

        asset = StudyAsset(
            notebook_id=notebook.id,
            title="Distributed Systems Reader",
            asset_type="article",
            status="indexed",
            total_chunks=24,
            created_by=auth["user_id"],
        )
        db.add(asset)
        db.commit()
        db.refresh(asset)

        db.add_all(
            [
                NotebookPage(
                    notebook_id=notebook.id,
                    created_by=auth["user_id"],
                    title="Overview",
                    slug=f"study-asset-{asset.id}-overview",
                    plain_text="overview",
                ),
                NotebookPage(
                    notebook_id=notebook.id,
                    created_by=auth["user_id"],
                    title="Notes",
                    slug=f"study-asset-{asset.id}-notes",
                    plain_text="notes",
                ),
                NotebookPage(
                    notebook_id=notebook.id,
                    created_by=auth["user_id"],
                    title="Chapter 1",
                    slug=f"study-asset-{asset.id}-chapter-1",
                    plain_text="chapter",
                ),
            ]
        )

        deck = StudyDeck(
            notebook_id=notebook.id,
            name="Core ideas",
            description="",
            card_count=3,
            created_by=auth["user_id"],
        )
        archived_deck = StudyDeck(
            notebook_id=notebook.id,
            name="Archived",
            description="",
            card_count=1,
            created_by=auth["user_id"],
            archived_at=now - timedelta(days=1),
        )
        db.add_all([deck, archived_deck])
        db.commit()
        db.refresh(deck)
        db.refresh(archived_deck)

        db.add_all(
            [
                StudyCard(
                    deck_id=deck.id,
                    front="What is a quorum?",
                    back="Majority agreement",
                    review_count=0,
                    next_review_at=None,
                ),
                StudyCard(
                    deck_id=deck.id,
                    front="What is linearizability?",
                    back="A strong consistency model",
                    review_count=2,
                    last_review_at=now - timedelta(days=2),
                    next_review_at=now + timedelta(days=2),
                    lapse_count=1,
                    consecutive_failures=1,
                ),
                StudyCard(
                    deck_id=deck.id,
                    front="What is Raft leader election?",
                    back="A randomized timeout process",
                    review_count=4,
                    last_review_at=now - timedelta(days=1),
                    next_review_at=now - timedelta(hours=2),
                    lapse_count=2,
                    confusion_memory_written_at=now - timedelta(days=1),
                ),
                StudyCard(
                    deck_id=archived_deck.id,
                    front="Ignored archived card",
                    back="Ignored",
                    review_count=9,
                    next_review_at=now - timedelta(days=1),
                ),
            ]
        )

        db.add_all(
            [
                AIActionLog(
                    workspace_id=auth["ws_id"],
                    user_id=auth["user_id"],
                    notebook_id=notebook.id,
                    action_type="study.review_card",
                    scope="notebook",
                    status="completed",
                    block_id="card-1",
                    created_at=now - timedelta(days=1),
                    output_summary="Reviewed flashcard",
                ),
                AIActionLog(
                    workspace_id=auth["ws_id"],
                    user_id=auth["user_id"],
                    notebook_id=notebook.id,
                    action_type="study.review_card",
                    scope="notebook",
                    status="completed",
                    block_id="card-2",
                    created_at=now - timedelta(days=3),
                    output_summary="Reviewed second flashcard",
                ),
                AIActionLog(
                    workspace_id=auth["ws_id"],
                    user_id=auth["user_id"],
                    notebook_id=notebook.id,
                    action_type="study.ask",
                    scope="study_asset",
                    status="completed",
                    created_at=now - timedelta(days=2),
                    output_summary="Asked about consensus tradeoffs",
                ),
                AIActionLog(
                    workspace_id=auth["ws_id"],
                    user_id=auth["user_id"],
                    notebook_id=notebook.id,
                    action_type="study.quiz",
                    scope="study_asset",
                    status="completed",
                    created_at=now - timedelta(days=4),
                    output_summary="Generated a checkpoint quiz",
                ),
                AIActionLog(
                    workspace_id=auth["ws_id"],
                    user_id=auth["user_id"],
                    notebook_id=notebook.id,
                    action_type="study.flashcards",
                    scope="study_asset",
                    status="completed",
                    created_at=now - timedelta(days=10),
                    output_summary="Too old to count",
                ),
            ]
        )
        db.commit()

        notebook_id = notebook.id

    response = client.get(f"/api/v1/notebooks/{notebook_id}/study/insights")
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["totals"] == {
        "assets": 1,
        "indexed_assets": 1,
        "generated_pages": 3,
        "chunks": 24,
        "decks": 1,
        "cards": 3,
        "new_cards": 1,
        "due_cards": 2,
        "weak_cards": 2,
        "reviewed_this_week": 2,
        "ai_actions_this_week": 2,
        "confusions_logged": 1,
    }
    assert payload["active_days"] == 4
    assert payload["action_counts"] == [
        {"action_type": "study.ask", "count": 1},
        {"action_type": "study.flashcards", "count": 0},
        {"action_type": "study.quiz", "count": 1},
        {"action_type": "study.review_card", "count": 2},
    ]
    assert payload["deck_pressure"][0]["deck_name"] == "Core ideas"
    assert payload["deck_pressure"][0]["due_cards"] == 2
    assert [item["front"] for item in payload["weak_cards"]] == [
        "What is linearizability?",
        "What is Raft leader election?",
    ]
    assert payload["recent_actions"][0]["action_type"] == "study.review_card"
    assert len(payload["daily_activity"]) == 7
