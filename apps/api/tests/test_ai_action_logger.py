# ruff: noqa: E402
import asyncio
import atexit
import os
import shutil
import tempfile
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-s1-logger-"))
atexit.register(lambda: shutil.rmtree(TEST_TEMP_DIR, ignore_errors=True))
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_TEMP_DIR / 'test.db'}"
os.environ["ENV"] = "test"

import importlib
import app.core.config as config_module
config_module.get_settings.cache_clear()
config_module.settings = config_module.get_settings()
import app.db.session as session_module
importlib.reload(session_module)

import pytest

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models import AIActionLog, AIUsageEvent, User, Workspace
from app.services.ai_action_logger import action_log_context


def setup_function() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _seed() -> tuple[str, str]:
    with SessionLocal() as db:
        ws = Workspace(name="WS")
        db.add(ws)
        user = User(email="a@b.co", password_hash="x")
        db.add(user)
        db.commit()
        db.refresh(ws)
        db.refresh(user)
        return ws.id, user.id


def test_happy_path_creates_running_row_then_completed() -> None:
    ws_id, user_id = _seed()

    async def go() -> str:
        with SessionLocal() as db:
            async with action_log_context(
                db,
                workspace_id=ws_id,
                user_id=user_id,
                action_type="selection.rewrite",
                scope="selection",
            ) as log:
                assert log.log_id
                assert not log.is_null
                mid = db.query(AIActionLog).filter_by(id=log.log_id).one()
                assert mid.status == "running"
                return log.log_id

    log_id = asyncio.run(go())

    with SessionLocal() as db:
        row = db.query(AIActionLog).filter_by(id=log_id).one()
        assert row.status == "completed"
        assert row.duration_ms is not None and row.duration_ms >= 0
        assert row.error_code is None
