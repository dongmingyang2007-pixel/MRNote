# ruff: noqa: E402
import atexit, importlib, os, shutil, tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-s5-fanout-"))
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
    AIActionLog, Memory, MemoryEvidence, Notebook, Project, User, Workspace,
)


def setup_function() -> None:
    global engine, SessionLocal
    engine = _s.engine
    SessionLocal = _s.SessionLocal
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    import app.tasks.worker_tasks as _wt
    _wt.SessionLocal = _s.SessionLocal


engine = _s.engine
SessionLocal = _s.SessionLocal


def _seed_project_with_recent_activity() -> str:
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        ws = Workspace(name="W"); user = User(email="u@x.co", password_hash="x")
        db.add(ws); db.add(user); db.commit(); db.refresh(ws); db.refresh(user)
        pr = Project(workspace_id=ws.id, name="P")
        db.add(pr); db.commit(); db.refresh(pr)
        nb = Notebook(workspace_id=ws.id, project_id=pr.id, created_by=user.id,
                      title="NB", slug="nb")
        db.add(nb); db.commit(); db.refresh(nb)
        db.add(AIActionLog(
            workspace_id=ws.id, user_id=user.id, notebook_id=nb.id,
            action_type="selection.rewrite", scope="selection",
            status="completed", output_summary="out",
            trace_metadata={},
            created_at=now - timedelta(hours=2),
        ))
        db.commit()
        return pr.id


def test_daily_fanout_enqueues_one_per_active_project() -> None:
    p1 = _seed_project_with_recent_activity()

    from app.tasks.worker_tasks import generate_daily_digests_task
    with patch(
        "app.tasks.worker_tasks.generate_proactive_digest_task.delay",
    ) as delay_mock:
        result = generate_daily_digests_task.run()
    assert delay_mock.call_count == 1
    args = delay_mock.call_args[0]
    assert args[0] == p1
    assert args[1] == "daily_digest"
    assert result["dispatched"] == 1


def test_weekly_fanout_skips_projects_with_no_activity() -> None:
    with SessionLocal() as db:
        ws = Workspace(name="W"); db.add(ws); db.commit(); db.refresh(ws)
        user = User(email="u@x.co", password_hash="x")
        db.add(user); db.commit(); db.refresh(user)
        pr = Project(workspace_id=ws.id, name="idle")
        db.add(pr); db.commit(); db.refresh(pr)
        # no notebook, no activity

    from app.tasks.worker_tasks import generate_weekly_reflections_task
    with patch(
        "app.tasks.worker_tasks.generate_proactive_digest_task.delay",
    ) as delay_mock:
        result = generate_weekly_reflections_task.run()
    assert delay_mock.call_count == 0
    assert result["dispatched"] == 0


def test_deviation_fanout_filters_to_goal_projects() -> None:
    p1 = _seed_project_with_recent_activity()
    with SessionLocal() as db:
        # NB: Memory has `confidence` (not `importance`) and requires `workspace_id`.
        # Match this pattern to what the project's other S5 tests do.
        pr = db.query(Project).filter_by(id=p1).first()
        db.add(Memory(
            workspace_id=pr.workspace_id,
            project_id=p1, content="Goal",
            confidence=0.8, node_status="active",
            metadata_json={"memory_kind": "goal"},
        ))
        db.commit()

    from app.tasks.worker_tasks import generate_deviation_reminders_task
    with patch(
        "app.tasks.worker_tasks.generate_proactive_digest_task.delay",
    ) as delay_mock:
        generate_deviation_reminders_task.run()
    assert delay_mock.call_count == 1
    assert delay_mock.call_args[0][1] == "deviation_reminder"


def test_deviation_fanout_skips_projects_without_goals() -> None:
    _seed_project_with_recent_activity()  # no goal memory

    from app.tasks.worker_tasks import generate_deviation_reminders_task
    with patch(
        "app.tasks.worker_tasks.generate_proactive_digest_task.delay",
    ) as delay_mock:
        generate_deviation_reminders_task.run()
    assert delay_mock.call_count == 0


def test_relationship_fanout_filters_to_person_projects() -> None:
    p1 = _seed_project_with_recent_activity()
    with SessionLocal() as db:
        pr = db.query(Project).filter_by(id=p1).first()
        db.add(Memory(
            workspace_id=pr.workspace_id,
            project_id=p1, content="张三",
            confidence=0.6, node_status="active",
            subject_kind="person",
            metadata_json={"subject_kind": "person"},
        ))
        db.commit()

    from app.tasks.worker_tasks import generate_relationship_reminders_task
    with patch(
        "app.tasks.worker_tasks.generate_proactive_digest_task.delay",
    ) as delay_mock:
        generate_relationship_reminders_task.run()
    assert delay_mock.call_count == 1
    assert delay_mock.call_args[0][1] == "relationship_reminder"
