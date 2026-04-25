# ruff: noqa: E402
import atexit, importlib, os, shutil, tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="mrnote-s5-gentask-"))
atexit.register(lambda: shutil.rmtree(TEST_TEMP_DIR, ignore_errors=True))
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_TEMP_DIR / 'test.db'}"
os.environ["ENV"] = "test"

import app.core.config as config_module
config_module.get_settings.cache_clear()
config_module.settings = config_module.get_settings()
import app.db.session as session_module
importlib.reload(session_module)

from unittest.mock import patch, AsyncMock

from app.db.base import Base
import app.db.session as _s
from app.models import (
    AIActionLog, Membership, Memory, Notebook, NotebookPage, ProactiveDigest,
    Project, User, Workspace,
)


def setup_function() -> None:
    global engine, SessionLocal
    engine = _s.engine
    SessionLocal = _s.SessionLocal
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    # Re-bind worker_tasks.SessionLocal like S4 did.
    import app.tasks.worker_tasks as _wt
    _wt.SessionLocal = _s.SessionLocal


engine = _s.engine
SessionLocal = _s.SessionLocal


def _seed_daily() -> tuple[str, str, str]:
    """Returns (workspace_id, project_id, notebook_id)."""
    with SessionLocal() as db:
        ws = Workspace(name="W"); user = User(email="u@x.co", password_hash="x")
        db.add(ws); db.add(user); db.commit(); db.refresh(ws); db.refresh(user)
        db.add(Membership(workspace_id=ws.id, user_id=user.id, role="owner"))
        db.commit()
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
        ))
        db.commit()
        return ws.id, pr.id, nb.id


def test_task_creates_one_daily_digest_row() -> None:
    ws_id, project_id, _ = _seed_daily()
    now = datetime.now(timezone.utc)
    period_start = (now - timedelta(hours=24)).isoformat()
    period_end = now.isoformat()

    fake_llm = AsyncMock(return_value='{"summary_md":"hi","next_actions":[]}')
    with patch(
        "app.services.proactive_generator._run_llm_json", fake_llm,
    ):
        from app.tasks.worker_tasks import generate_proactive_digest_task
        result = generate_proactive_digest_task.run(
            project_id, "daily_digest", period_start, period_end,
        )
    assert result is not None
    with SessionLocal() as db:
        rows = db.query(ProactiveDigest).all()
    assert len(rows) == 1
    assert rows[0].kind == "daily_digest"
    assert rows[0].status == "unread"
    assert rows[0].content_json["summary_md"] == "hi"
    assert rows[0].action_log_id  # S1 action_log linked


def test_task_idempotent_on_second_call() -> None:
    ws_id, project_id, _ = _seed_daily()
    now = datetime.now(timezone.utc)
    ps = (now - timedelta(hours=24)).isoformat()
    pe = now.isoformat()

    fake_llm = AsyncMock(return_value='{"summary_md":"hi","next_actions":[]}')
    with patch(
        "app.services.proactive_generator._run_llm_json", fake_llm,
    ):
        from app.tasks.worker_tasks import generate_proactive_digest_task
        generate_proactive_digest_task.run(project_id, "daily_digest", ps, pe)
        result2 = generate_proactive_digest_task.run(
            project_id, "daily_digest", ps, pe,
        )
    assert result2 is None
    with SessionLocal() as db:
        count = db.query(ProactiveDigest).count()
    assert count == 1


def test_task_empty_activity_returns_none() -> None:
    """If no activity in window, skip row creation."""
    with SessionLocal() as db:
        ws = Workspace(name="W"); user = User(email="u@x.co", password_hash="x")
        db.add(ws); db.add(user); db.commit(); db.refresh(ws); db.refresh(user)
        db.add(Membership(workspace_id=ws.id, user_id=user.id, role="owner"))
        db.commit()
        pr = Project(workspace_id=ws.id, name="P")
        db.add(pr); db.commit(); db.refresh(pr)
        # No notebook, no activity
        project_id = pr.id

    now = datetime.now(timezone.utc)
    ps = (now - timedelta(hours=24)).isoformat()
    pe = now.isoformat()

    from app.tasks.worker_tasks import generate_proactive_digest_task
    result = generate_proactive_digest_task.run(
        project_id, "daily_digest", ps, pe,
    )
    assert result is None
    with SessionLocal() as db:
        assert db.query(ProactiveDigest).count() == 0


def _seed_goal_project() -> tuple[str, str, list[str]]:
    """Return (workspace_id, project_id, [goal_memory_ids])."""
    with SessionLocal() as db:
        ws = Workspace(name="W"); user = User(email="gu@x.co", password_hash="x")
        db.add(ws); db.add(user); db.commit(); db.refresh(ws); db.refresh(user)
        db.add(Membership(workspace_id=ws.id, user_id=user.id, role="owner"))
        db.commit()
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
        ))
        g1 = Memory(workspace_id=ws.id, project_id=pr.id, content="goal 1",
                    node_type="fact", node_status="active",
                    metadata_json={"memory_kind": "goal"})
        g2 = Memory(workspace_id=ws.id, project_id=pr.id, content="goal 2",
                    node_type="fact", node_status="active",
                    metadata_json={"memory_kind": "goal"})
        db.add(g1); db.add(g2); db.commit(); db.refresh(g1); db.refresh(g2)
        return ws.id, pr.id, [g1.id, g2.id]


def test_deviation_partial_retry_backfills_remaining() -> None:
    ws_id, project_id, goal_ids = _seed_goal_project()
    g1_id, g2_id = goal_ids
    now = datetime.now(timezone.utc)
    ps = (now - timedelta(days=7)).isoformat()
    pe = now.isoformat()

    import json
    from app.tasks.worker_tasks import generate_proactive_digest_task

    first_payload = json.dumps({"drifts": [
        {"goal_memory_id": g1_id, "drift_reason_md": "r1", "confidence": 0.7},
    ]})
    with patch(
        "app.services.proactive_generator._run_llm_json",
        AsyncMock(return_value=first_payload),
    ):
        generate_proactive_digest_task.run(
            project_id, "deviation_reminder", ps, pe,
        )
    with SessionLocal() as db:
        rows = db.query(ProactiveDigest).filter_by(kind="deviation_reminder").all()
    assert len(rows) == 1
    assert rows[0].series_key == g1_id

    second_payload = json.dumps({"drifts": [
        {"goal_memory_id": g1_id, "drift_reason_md": "r1", "confidence": 0.7},
        {"goal_memory_id": g2_id, "drift_reason_md": "r2", "confidence": 0.6},
    ]})
    with patch(
        "app.services.proactive_generator._run_llm_json",
        AsyncMock(return_value=second_payload),
    ):
        generate_proactive_digest_task.run(
            project_id, "deviation_reminder", ps, pe,
        )
    with SessionLocal() as db:
        rows = db.query(ProactiveDigest).filter_by(kind="deviation_reminder").all()
    series_keys = sorted(r.series_key for r in rows)
    assert len(rows) == 2
    assert series_keys == sorted([g1_id, g2_id])
