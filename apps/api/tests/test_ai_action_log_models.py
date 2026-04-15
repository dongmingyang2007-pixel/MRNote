# ruff: noqa: E402
import atexit
import os
import shutil
import tempfile
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-s1-models-"))
atexit.register(lambda: shutil.rmtree(TEST_TEMP_DIR, ignore_errors=True))
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_TEMP_DIR / 'test.db'}"
os.environ["ENV"] = "test"

import importlib
import app.core.config as config_module
config_module.get_settings.cache_clear()
config_module.settings = config_module.get_settings()
import app.db.session as session_module
importlib.reload(session_module)

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models import AIActionLog, AIUsageEvent, User, Workspace


def setup_function() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _seed_user_and_workspace(db) -> tuple[str, str]:
    ws = Workspace(name="WS")
    db.add(ws)
    user = User(email="a@b.co", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(ws)
    db.refresh(user)
    return ws.id, user.id


def test_insert_action_log_with_usage_events() -> None:
    with SessionLocal() as db:
        ws_id, user_id = _seed_user_and_workspace(db)
        log = AIActionLog(
            workspace_id=ws_id,
            user_id=user_id,
            action_type="selection.rewrite",
            scope="selection",
            status="completed",
            duration_ms=1200,
            input_json={"text": "hi"},
            output_json={"text": "hello"},
            output_summary="hello",
            trace_metadata={},
        )
        db.add(log)
        db.commit()
        db.refresh(log)

        usage = AIUsageEvent(
            workspace_id=ws_id,
            user_id=user_id,
            action_log_id=log.id,
            event_type="llm_completion",
            model_id="qwen-plus",
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            count_source="exact",
            meta_json={},
        )
        db.add(usage)
        db.commit()

        rows = db.query(AIActionLog).all()
        usages = db.query(AIUsageEvent).all()

    assert len(rows) == 1
    assert rows[0].status == "completed"
    assert rows[0].action_type == "selection.rewrite"
    assert len(usages) == 1
    assert usages[0].action_log_id == log.id
    assert usages[0].total_tokens == 15
