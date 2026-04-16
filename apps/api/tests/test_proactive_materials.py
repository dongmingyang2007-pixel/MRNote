# ruff: noqa: E402
import atexit, importlib, os, shutil, tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-s5-materials-"))
atexit.register(lambda: shutil.rmtree(TEST_TEMP_DIR, ignore_errors=True))
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_TEMP_DIR / 'test.db'}"
os.environ["ENV"] = "test"

import app.core.config as config_module
config_module.get_settings.cache_clear()
config_module.settings = config_module.get_settings()
import app.db.session as session_module
importlib.reload(session_module)

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models import (
    AIActionLog, Memory, MemoryEvidence, Notebook, NotebookPage, Project,
    StudyCard, StudyDeck, User, Workspace,
)
from app.services.proactive_materials import (
    collect_daily_materials,
    collect_goal_materials,
    collect_relationship_materials,
    collect_weekly_materials,
)


def setup_function() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _seed_base() -> tuple[str, str, str, str]:
    """Returns (workspace_id, user_id, project_id, notebook_id)."""
    with SessionLocal() as db:
        ws = Workspace(name="W"); user = User(email="u@x.co", password_hash="x")
        db.add(ws); db.add(user); db.commit(); db.refresh(ws); db.refresh(user)
        pr = Project(workspace_id=ws.id, name="P")
        db.add(pr); db.commit(); db.refresh(pr)
        nb = Notebook(workspace_id=ws.id, project_id=pr.id,
                      created_by=user.id, title="NB", slug="nb")
        db.add(nb); db.commit(); db.refresh(nb)
        return ws.id, user.id, pr.id, nb.id


def test_collect_daily_materials_with_activity() -> None:
    ws_id, user_id, project_id, notebook_id = _seed_base()
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        for i in range(3):
            db.add(AIActionLog(
                workspace_id=ws_id, user_id=user_id, notebook_id=notebook_id,
                action_type="selection.rewrite", scope="selection",
                status="completed", output_summary=f"out {i}",
                trace_metadata={},
                created_at=now - timedelta(hours=i),
            ))
        page = NotebookPage(notebook_id=notebook_id, created_by=user_id,
                            title="T", slug="t", plain_text="x",
                            last_edited_at=now - timedelta(hours=2))
        db.add(page); db.commit()

        mats = collect_daily_materials(
            db,
            project_id=project_id,
            period_start=now - timedelta(hours=24),
            period_end=now,
        )
    assert mats["action_counts"]["selection.rewrite"] == 3
    assert len(mats["action_samples"]) == 3
    assert len(mats["page_edits"]) == 1


def test_collect_daily_materials_empty_project_returns_empty() -> None:
    ws_id, user_id, project_id, notebook_id = _seed_base()
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        mats = collect_daily_materials(
            db, project_id=project_id,
            period_start=now - timedelta(hours=24), period_end=now,
        )
    assert mats["action_counts"] == {}
    assert mats["action_samples"] == []
    assert mats["page_edits"] == []


def test_collect_weekly_materials_includes_study_stats() -> None:
    ws_id, user_id, project_id, notebook_id = _seed_base()
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        deck = StudyDeck(notebook_id=notebook_id, name="D", created_by=user_id)
        db.add(deck); db.commit(); db.refresh(deck)
        for i in range(4):
            db.add(StudyCard(
                deck_id=deck.id, front=f"Q{i}", back=f"A{i}",
                review_count=i + 1,
                lapse_count=1 if i == 0 else 0,
            ))
        db.commit()

        mats = collect_weekly_materials(
            db, project_id=project_id,
            period_start=now - timedelta(days=7), period_end=now,
        )
    assert mats["study_stats"]["cards_reviewed"] >= 4 * (4 + 1) // 2  # sum of review_count 1..4 = 10
    assert mats["study_stats"]["lapse_count"] == 1


def test_collect_weekly_materials_blocker_tasks_empty_when_no_reopen() -> None:
    ws_id, user_id, project_id, notebook_id = _seed_base()
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        mats = collect_weekly_materials(
            db, project_id=project_id,
            period_start=now - timedelta(days=7), period_end=now,
        )
    assert mats["blocker_tasks"] == []


def test_collect_goal_materials_finds_goal_kind_memory() -> None:
    ws_id, user_id, project_id, notebook_id = _seed_base()
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        g = Memory(
            workspace_id=ws_id,
            project_id=project_id,
            content="Ship MVP by end of month",
            confidence=0.8,
            node_status="active",
            metadata_json={"memory_kind": "goal"},
        )
        db.add(g); db.commit()

        mats = collect_goal_materials(
            db, project_id=project_id,
            period_start=now - timedelta(days=7), period_end=now,
        )
    assert len(mats["goals"]) == 1
    assert mats["goals"][0]["content"].startswith("Ship MVP")


def test_collect_goal_materials_caps_at_ten() -> None:
    ws_id, user_id, project_id, notebook_id = _seed_base()
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        for i in range(15):
            db.add(Memory(
                workspace_id=ws_id,
                project_id=project_id,
                content=f"goal {i}",
                confidence=0.5,
                node_status="active",
                metadata_json={"memory_kind": "goal"},
            ))
        db.commit()

        mats = collect_goal_materials(
            db, project_id=project_id,
            period_start=now - timedelta(days=7), period_end=now,
        )
    assert len(mats["goals"]) == 10


def test_collect_relationship_materials_flags_stale_person() -> None:
    ws_id, user_id, project_id, notebook_id = _seed_base()
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=45)
    with SessionLocal() as db:
        m = Memory(
            workspace_id=ws_id,
            project_id=project_id,
            content="张三",
            confidence=0.6,
            node_status="active",
            subject_kind="person",
            metadata_json={"subject_kind": "person"},
        )
        db.add(m); db.commit(); db.refresh(m)
        db.add(MemoryEvidence(
            workspace_id=ws_id,
            project_id=project_id,
            memory_id=m.id,
            source_type="chat",
            confidence=0.5,
            quote_text="mentioned",
            created_at=old,
        ))
        db.commit()

        items = collect_relationship_materials(db, project_id=project_id, now=now)
    assert len(items) == 1
    assert items[0]["memory_id"] == m.id
    assert items[0]["days_since"] >= 44


def test_collect_relationship_materials_skips_fresh_person() -> None:
    ws_id, user_id, project_id, notebook_id = _seed_base()
    now = datetime.now(timezone.utc)
    fresh = now - timedelta(days=5)
    with SessionLocal() as db:
        m = Memory(
            workspace_id=ws_id,
            project_id=project_id,
            content="张三",
            confidence=0.6,
            node_status="active",
            subject_kind="person",
            metadata_json={"subject_kind": "person"},
        )
        db.add(m); db.commit(); db.refresh(m)
        db.add(MemoryEvidence(
            workspace_id=ws_id,
            project_id=project_id,
            memory_id=m.id,
            source_type="chat",
            confidence=0.5,
            quote_text="recent",
            created_at=fresh,
        ))
        db.commit()

        items = collect_relationship_materials(db, project_id=project_id, now=now)
    assert items == []
