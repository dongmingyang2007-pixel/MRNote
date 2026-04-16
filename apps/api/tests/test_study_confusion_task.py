# ruff: noqa: E402
import atexit, importlib, os, shutil, tempfile
from datetime import datetime, timezone
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-s4-conf-task-"))
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
    Notebook, Project, StudyCard, StudyDeck, User, Workspace,
)


def setup_function() -> None:
    global engine, SessionLocal
    engine = _s.engine
    SessionLocal = _s.SessionLocal
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


engine = _s.engine
SessionLocal = _s.SessionLocal


def _seed_card() -> tuple[str, str, str]:
    with SessionLocal() as db:
        ws = Workspace(name="W"); user = User(email="u@x.co", password_hash="x")
        db.add(ws); db.add(user); db.commit(); db.refresh(ws); db.refresh(user)
        pr = Project(workspace_id=ws.id, name="P"); db.add(pr); db.commit(); db.refresh(pr)
        nb = Notebook(workspace_id=ws.id, project_id=pr.id, created_by=user.id,
                      title="NB", slug="nb"); db.add(nb); db.commit(); db.refresh(nb)
        deck = StudyDeck(notebook_id=nb.id, name="D", created_by=user.id)
        db.add(deck); db.commit(); db.refresh(deck)
        card = StudyCard(
            deck_id=deck.id, front="Q", back="A",
            consecutive_failures=3,
        )
        db.add(card); db.commit(); db.refresh(card)
        return ws.id, user.id, card.id


def test_task_runs_pipeline_for_confusion_card() -> None:
    ws_id, user_id, card_id = _seed_card()

    from app.tasks.worker_tasks import process_study_confusion_task

    with patch("app.tasks.worker_tasks._run_study_confusion_pipeline") as runner:
        process_study_confusion_task.run(
            card_id, user_id, ws_id, "consecutive_failures",
        )
    assert runner.call_count == 1
    args, _ = runner.call_args
    # args: (db, PipelineInput)
    pipeline_input = args[1]
    assert pipeline_input.source_type == "study_confusion"
    assert pipeline_input.source_ref == card_id


def test_task_noop_when_card_missing() -> None:
    from app.tasks.worker_tasks import process_study_confusion_task

    with patch("app.tasks.worker_tasks._run_study_confusion_pipeline") as runner:
        process_study_confusion_task.run(
            "does-not-exist", "user", "ws", "manual",
        )
    assert runner.call_count == 0
