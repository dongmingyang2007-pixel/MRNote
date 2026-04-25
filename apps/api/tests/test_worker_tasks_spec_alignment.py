# ruff: noqa: E402
"""Wave 2 A8 — smoke tests for spec §14 worker-task alignment.

These cover the wrappers we added in ``worker_tasks.py``: they must be
importable, callable via ``.run(...)``, and they must not raise on
expected-missing / empty inputs. Heavy integration is covered elsewhere
(UnifiedMemoryPipeline, study_pipeline, etc.) — the goal here is just
that the new Celery task names behave.
"""
import atexit
import importlib
import os
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="mrnote-a8-spec-"))
atexit.register(lambda: shutil.rmtree(TEST_TEMP_DIR, ignore_errors=True))
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_TEMP_DIR / 'test.db'}"
os.environ["ENV"] = "test"

import app.core.config as config_module

config_module.get_settings.cache_clear()
config_module.settings = config_module.get_settings()
import app.db.session as session_module

importlib.reload(session_module)

from unittest.mock import patch

from app.db.base import Base
import app.db.session as _s
from app.models import (
    AIActionLog,
    AIUsageEvent,
    Notebook,
    NotebookPage,
    Project,
    StudyAsset,
    StudyCard,
    StudyChunk,
    StudyDeck,
    Subscription,
    User,
    Workspace,
)


def setup_function() -> None:
    global engine, SessionLocal
    engine = _s.engine
    SessionLocal = _s.SessionLocal
    # worker_tasks binds SessionLocal at import time — rebind.
    import app.tasks.worker_tasks as _wt

    _wt.SessionLocal = _s.SessionLocal
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


engine = _s.engine
SessionLocal = _s.SessionLocal


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _seed_minimal_page() -> tuple[str, str, str, str]:
    """Create a Workspace / Project / Notebook / Page and return their ids."""
    with SessionLocal() as db:
        ws = Workspace(name="W")
        user = User(email="u@x.co", password_hash="x")
        db.add_all([ws, user])
        db.commit()
        db.refresh(ws)
        db.refresh(user)
        pr = Project(workspace_id=ws.id, name="P")
        db.add(pr)
        db.commit()
        db.refresh(pr)
        nb = Notebook(
            workspace_id=ws.id,
            project_id=pr.id,
            created_by=user.id,
            title="NB",
            slug="nb",
        )
        db.add(nb)
        db.commit()
        db.refresh(nb)
        page = NotebookPage(
            notebook_id=nb.id,
            created_by=user.id,
            title="t",
            slug="t",
            plain_text="",
            content_json={
                "type": "doc",
                "content": [
                    {"type": "paragraph", "content": [
                        {"type": "text", "text": "Hello world learning memory"}
                    ]},
                    {"type": "paragraph", "content": [
                        {"type": "text", "text": "Another sentence about something"}
                    ]},
                ],
            },
        )
        db.add(page)
        db.commit()
        db.refresh(page)
        return ws.id, user.id, pr.id, page.id


# ---------------------------------------------------------------------------
# Task tests
# ---------------------------------------------------------------------------


def test_notebook_page_plaintext_rebuilds_text() -> None:
    _ws, _u, _p, page_id = _seed_minimal_page()

    from app.tasks.worker_tasks import notebook_page_plaintext_task

    out = notebook_page_plaintext_task.run(page_id)
    assert out["status"] == "ok"
    with SessionLocal() as db:
        page = db.get(NotebookPage, page_id)
    assert page is not None
    assert "Hello world" in page.plain_text
    assert "Another sentence" in page.plain_text


def test_notebook_page_plaintext_missing_page_is_noop() -> None:
    from app.tasks.worker_tasks import notebook_page_plaintext_task

    out = notebook_page_plaintext_task.run("does-not-exist")
    assert out["status"] == "missing"


def test_notebook_page_summary_fills_summary_and_keywords() -> None:
    _ws, _u, _p, page_id = _seed_minimal_page()
    # Populate plain_text so the task has something to summarize.
    with SessionLocal() as db:
        page = db.get(NotebookPage, page_id)
        page.plain_text = (
            "Learning about memory pipelines today.\n"
            "Memory retrieval is important for learning outcomes."
        )
        db.add(page)
        db.commit()

    from app.tasks.worker_tasks import notebook_page_summary_task

    out = notebook_page_summary_task.run(page_id)
    assert out["status"] == "ok"
    with SessionLocal() as db:
        page = db.get(NotebookPage, page_id)
    assert page is not None
    assert page.summary_text.startswith("Learning about memory")
    # keywords should at least contain one of the repeated words.
    assert any(
        kw in {"learning", "memory", "retrieval", "important", "pipelines", "outcomes"}
        for kw in (page.ai_keywords_json or [])
    )


def test_notebook_page_summary_empty_text_status_empty() -> None:
    _ws, _u, _p, page_id = _seed_minimal_page()
    with SessionLocal() as db:
        page = db.get(NotebookPage, page_id)
        page.plain_text = ""
        db.add(page)
        db.commit()

    from app.tasks.worker_tasks import notebook_page_summary_task

    out = notebook_page_summary_task.run(page_id)
    assert out["status"] == "empty"


def test_unified_memory_extract_delegates_to_pipeline() -> None:
    from app.tasks import worker_tasks as wt

    seen: dict = {}

    async def fake_run_pipeline(db, pipeline_input):
        seen["input"] = pipeline_input
        from app.services.unified_memory_pipeline import PipelineResult

        return PipelineResult(status="completed", item_count=1, graph_changed=False)

    with patch(
        "app.services.unified_memory_pipeline.run_pipeline",
        new=fake_run_pipeline,
    ):
        out = wt.unified_memory_extract_task.run(
            source_type="chat_message",
            source_ref="msg-1",
            source_text="hello",
            workspace_id="ws-1",
            project_id="pr-1",
            user_id="u-1",
            context_text="ctx",
        )
    assert out["status"] == "completed"
    assert out["item_count"] == 1
    assert seen["input"].source_type == "chat_message"
    assert seen["input"].source_ref == "msg-1"


def test_notebook_page_memory_link_links_new_evidence() -> None:
    from app.models import Memory, MemoryEpisode, MemoryEvidence

    _ws, _u, _p, page_id = _seed_minimal_page()
    # Seed a memory + evidence + episode so the task has something to link.
    with SessionLocal() as db:
        mem = Memory(
            workspace_id=_ws,
            project_id=_p,
            content="fact body",
        )
        db.add(mem)
        db.commit()
        db.refresh(mem)
        episode = MemoryEpisode(
            workspace_id=_ws,
            project_id=_p,
            source_type="notebook_page",
            source_id=page_id,
            chunk_text="chunk body",
        )
        db.add(episode)
        db.commit()
        db.refresh(episode)
        evidence = MemoryEvidence(
            workspace_id=_ws,
            project_id=_p,
            memory_id=mem.id,
            source_type="notebook_page",
            episode_id=episode.id,
            quote_text="quote",
            confidence=0.9,
        )
        db.add(evidence)
        db.commit()

    from app.tasks.worker_tasks import notebook_page_memory_link_task

    out = notebook_page_memory_link_task.run(page_id)
    assert out["status"] == "ok"
    assert out["linked"] == 1

    # idempotent — second run links 0 new rows.
    out2 = notebook_page_memory_link_task.run(page_id)
    assert out2["linked"] == 0


def test_notebook_page_relevance_refresh_returns_counts() -> None:
    _ws, _u, _p, page_id = _seed_minimal_page()

    from app.tasks.worker_tasks import notebook_page_relevance_refresh_task

    out = notebook_page_relevance_refresh_task.run(page_id)
    assert out["status"] == "ok"
    # Counts may be zero — the task should still return them.
    assert "page_count" in out
    assert "memory_count" in out


def test_whiteboard_memory_extract_is_alias() -> None:
    from app.tasks import worker_tasks as wt

    with patch.object(wt, "process_whiteboard_memories") as spy:
        out = wt.whiteboard_memory_extract_task.run(
            page_id="p-1",
            workspace_id="ws-1",
            project_id="pr-1",
            user_id="u-1",
            elements_json=[{"k": "v"}],
        )
    assert out["status"] == "ok"
    spy.assert_called_once()


def test_document_memory_extract_missing_chunk_returns_missing() -> None:
    from app.tasks.worker_tasks import document_memory_extract_task

    out = document_memory_extract_task.run(
        chunk_id="nope",
        workspace_id="ws",
        project_id="pr",
        user_id="u",
    )
    assert out["status"] == "missing"


def test_study_asset_chunk_and_auto_pages_are_noops() -> None:
    from app.tasks.worker_tasks import (
        study_asset_auto_pages_task,
        study_asset_chunk_task,
    )

    out1 = study_asset_chunk_task.run("asset-x")
    out2 = study_asset_auto_pages_task.run("asset-x")
    assert out1["status"] == "noop"
    assert out2["status"] == "noop"


def test_study_asset_deck_generate_creates_deck_with_chunks() -> None:
    _ws, user_id, _p, _page_id = _seed_minimal_page()
    with SessionLocal() as db:
        nb = db.query(Notebook).first()
        asset = StudyAsset(
            notebook_id=nb.id,
            title="Sample book",
            asset_type="pdf",
            status="completed",
            created_by=user_id,
        )
        db.add(asset)
        db.commit()
        db.refresh(asset)
        for i in range(3):
            db.add(
                StudyChunk(
                    asset_id=asset.id,
                    chunk_index=i,
                    heading=f"Chapter {i}",
                    content=f"Content body {i} " * 10,
                )
            )
        db.commit()
        asset_id = asset.id

    from app.tasks.worker_tasks import study_asset_deck_generate_task

    out = study_asset_deck_generate_task.run(
        asset_id=asset_id,
        workspace_id=_ws,
        user_id=user_id,
        deck_name="Generated",
    )
    assert out["status"] == "ok"
    assert out["card_count"] == 3

    with SessionLocal() as db:
        deck = db.get(StudyDeck, out["deck_id"])
        assert deck is not None
        cards = (
            db.query(StudyCard)
            .filter(StudyCard.deck_id == deck.id)
            .all()
        )
    assert len(cards) == 3


def test_study_asset_review_recommendation_returns_due_cards() -> None:
    _ws, user_id, _p, _page_id = _seed_minimal_page()
    with SessionLocal() as db:
        nb = db.query(Notebook).first()
        deck = StudyDeck(notebook_id=nb.id, name="d", created_by=user_id)
        db.add(deck)
        db.commit()
        db.refresh(deck)
        # Due card (no next_review_at)
        db.add(StudyCard(deck_id=deck.id, front="Q1", back="A1"))
        # Due card (past)
        db.add(
            StudyCard(
                deck_id=deck.id,
                front="Q2",
                back="A2",
                next_review_at=datetime.now(timezone.utc) - timedelta(hours=1),
            )
        )
        # Not due (far future)
        db.add(
            StudyCard(
                deck_id=deck.id,
                front="Q3",
                back="A3",
                next_review_at=datetime.now(timezone.utc) + timedelta(days=30),
            )
        )
        db.commit()

    from app.tasks.worker_tasks import study_asset_review_recommendation_task

    out = study_asset_review_recommendation_task.run(
        user_id=user_id,
        workspace_id=_ws,
    )
    assert out["status"] == "ok"
    assert out["due_card_count"] == 2


def test_usage_rollup_aggregates_events() -> None:
    _ws, user_id, _p, _page_id = _seed_minimal_page()
    with SessionLocal() as db:
        # Seed an AIActionLog + 2 AIUsageEvents.
        log = AIActionLog(
            workspace_id=_ws,
            user_id=user_id,
            action_type="ai.ask",
            scope="page",
            status="completed",
        )
        db.add(log)
        db.commit()
        db.refresh(log)
        for tokens in (100, 200):
            db.add(
                AIUsageEvent(
                    workspace_id=_ws,
                    user_id=user_id,
                    action_log_id=log.id,
                    event_type="text",
                    total_tokens=tokens,
                )
            )
        db.commit()

    from app.tasks.worker_tasks import usage_rollup_task

    out = usage_rollup_task.run()
    assert out["status"] == "ok"
    assert out["workspace_count"] >= 1
    assert out["total_events"] >= 2
    assert out["total_tokens"] >= 300


def test_subscription_sync_repair_flags_stale_rows() -> None:
    _ws, _u, _p, _page_id = _seed_minimal_page()
    with SessionLocal() as db:
        # Active sub in the past -> stale.
        db.add(
            Subscription(
                workspace_id=_ws,
                plan="pro",
                billing_cycle="monthly",
                status="active",
                provider="stripe_recurring",
                current_period_end=datetime.now(timezone.utc) - timedelta(days=1),
            )
        )
        # Active sub in the future -> healthy.
        db.add(
            Subscription(
                workspace_id=_ws,
                plan="pro",
                billing_cycle="monthly",
                status="active",
                provider="stripe_recurring",
                current_period_end=datetime.now(timezone.utc) + timedelta(days=10),
            )
        )
        db.commit()

    from app.tasks.worker_tasks import subscription_sync_repair_task

    out = subscription_sync_repair_task.run()
    assert out["status"] == "ok"
    assert out["stale_count"] == 1


def test_beat_schedule_includes_new_tasks() -> None:
    from app.tasks.celery_app import celery_app

    schedule = celery_app.conf.beat_schedule
    assert "usage-rollup-daily" in schedule
    assert "subscription-sync-repair-6h" in schedule
    assert (
        schedule["usage-rollup-daily"]["task"]
        == "app.tasks.worker_tasks.usage_rollup_task"
    )
    assert (
        schedule["subscription-sync-repair-6h"]["task"]
        == "app.tasks.worker_tasks.subscription_sync_repair_task"
    )


def test_new_task_routes_registered() -> None:
    from app.tasks.celery_app import celery_app

    routes = celery_app.conf.task_routes
    for task_name in (
        "app.tasks.worker_tasks.notebook_page_plaintext_task",
        "app.tasks.worker_tasks.notebook_page_summary_task",
        "app.tasks.worker_tasks.unified_memory_extract_task",
        "app.tasks.worker_tasks.notebook_page_memory_link_task",
        "app.tasks.worker_tasks.notebook_page_relevance_refresh_task",
        "app.tasks.worker_tasks.whiteboard_memory_extract_task",
        "app.tasks.worker_tasks.document_memory_extract_task",
        "app.tasks.worker_tasks.study_asset_chunk_task",
        "app.tasks.worker_tasks.study_asset_auto_pages_task",
        "app.tasks.worker_tasks.study_asset_deck_generate_task",
        "app.tasks.worker_tasks.study_asset_memory_extract_task",
        "app.tasks.worker_tasks.study_asset_review_recommendation_task",
        "app.tasks.worker_tasks.usage_rollup_task",
        "app.tasks.worker_tasks.subscription_sync_repair_task",
    ):
        assert task_name in routes, f"{task_name} missing from task_routes"
