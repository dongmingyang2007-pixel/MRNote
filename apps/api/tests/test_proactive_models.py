# ruff: noqa: E402
import atexit, os, shutil, tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-s5-models-"))
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
from sqlalchemy.exc import IntegrityError

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models import ProactiveDigest, Project, User, Workspace


def setup_function() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _seed() -> tuple[str, str, str]:
    with SessionLocal() as db:
        ws = Workspace(name="W"); user = User(email="u@x.co", password_hash="x")
        db.add(ws); db.add(user); db.commit(); db.refresh(ws); db.refresh(user)
        pr = Project(workspace_id=ws.id, name="P")
        db.add(pr); db.commit(); db.refresh(pr)
        return ws.id, user.id, pr.id


def test_digest_insert_and_defaults() -> None:
    ws_id, user_id, project_id = _seed()
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        d = ProactiveDigest(
            workspace_id=ws_id,
            project_id=project_id,
            user_id=user_id,
            kind="daily_digest",
            period_start=now - timedelta(hours=24),
            period_end=now,
            title="Daily",
            content_markdown="hello",
            content_json={"summary_md": "hello"},
        )
        db.add(d); db.commit(); db.refresh(d)
    assert d.status == "unread"
    assert d.read_at is None
    assert d.dismissed_at is None


def test_unique_constraint_project_kind_period_series() -> None:
    ws_id, user_id, project_id = _seed()
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        d1 = ProactiveDigest(
            workspace_id=ws_id, project_id=project_id, user_id=user_id,
            kind="daily_digest", period_start=now, period_end=now,
            content_markdown="a", content_json={},
        )
        db.add(d1); db.commit()
    with SessionLocal() as db, pytest.raises(IntegrityError):
        d2 = ProactiveDigest(
            workspace_id=ws_id, project_id=project_id, user_id=user_id,
            kind="daily_digest", period_start=now, period_end=now,
            content_markdown="b", content_json={},
        )
        db.add(d2); db.commit()


def test_series_key_allows_multiple_rows_per_period() -> None:
    ws_id, user_id, project_id = _seed()
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        d1 = ProactiveDigest(
            workspace_id=ws_id, project_id=project_id, user_id=user_id,
            kind="deviation_reminder", period_start=now, period_end=now,
            series_key="g1",
            content_markdown="a", content_json={},
        )
        d2 = ProactiveDigest(
            workspace_id=ws_id, project_id=project_id, user_id=user_id,
            kind="deviation_reminder", period_start=now, period_end=now,
            series_key="g2",
            content_markdown="b", content_json={},
        )
        db.add(d1); db.add(d2); db.commit()
        count = db.query(ProactiveDigest).filter_by(
            kind="deviation_reminder", project_id=project_id,
        ).count()
    assert count == 2


def test_status_check_constraint() -> None:
    ws_id, user_id, project_id = _seed()
    now = datetime.now(timezone.utc)
    with SessionLocal() as db, pytest.raises(IntegrityError):
        d = ProactiveDigest(
            workspace_id=ws_id, project_id=project_id, user_id=user_id,
            kind="daily_digest", period_start=now, period_end=now,
            content_markdown="x", content_json={},
            status="garbage",
        )
        db.add(d); db.commit()
