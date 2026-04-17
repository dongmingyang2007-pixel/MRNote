# ruff: noqa: E402
import atexit, importlib, os, shutil, tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-s5-reconfirm-"))
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
from app.models import Memory, Project, User, Workspace
from app.services.memory_v2 import find_reconfirm_candidates


def setup_function() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _seed_project() -> tuple[str, str]:
    with SessionLocal() as db:
        ws = Workspace(name="W"); user = User(email="u@x.co", password_hash="x")
        db.add(ws); db.add(user); db.commit(); db.refresh(ws); db.refresh(user)
        pr = Project(workspace_id=ws.id, name="P")
        db.add(pr); db.commit(); db.refresh(pr)
        return ws.id, pr.id


def test_returns_memories_with_past_reconfirm_after() -> None:
    workspace_id, project_id = _seed_project()
    now = datetime.now(timezone.utc)
    past = (now - timedelta(days=5)).isoformat()
    with SessionLocal() as db:
        m = Memory(
            workspace_id=workspace_id,
            project_id=project_id,
            content="old fact",
            node_status="active",
            metadata_json={
                "reconfirm_after": past,
                "single_source_explicit": True,
            },
        )
        db.add(m); db.commit(); db.refresh(m)

        candidates = find_reconfirm_candidates(db, project_id=project_id, now=now)
    assert len(candidates) == 1
    assert candidates[0].id == m.id


def test_skips_memories_without_single_source_flag() -> None:
    workspace_id, project_id = _seed_project()
    now = datetime.now(timezone.utc)
    past = (now - timedelta(days=5)).isoformat()
    with SessionLocal() as db:
        m = Memory(
            workspace_id=workspace_id,
            project_id=project_id,
            content="old fact",
            node_status="active",
            metadata_json={"reconfirm_after": past},
        )
        db.add(m); db.commit()

        candidates = find_reconfirm_candidates(db, project_id=project_id, now=now)
    assert candidates == []


def test_respects_limit() -> None:
    workspace_id, project_id = _seed_project()
    now = datetime.now(timezone.utc)
    past = (now - timedelta(days=5)).isoformat()
    with SessionLocal() as db:
        for i in range(7):
            db.add(Memory(
                workspace_id=workspace_id,
                project_id=project_id,
                content=f"old fact {i}",
                node_status="active",
                metadata_json={
                    "reconfirm_after": past,
                    "single_source_explicit": True,
                },
            ))
        db.commit()

        candidates = find_reconfirm_candidates(
            db, project_id=project_id, limit=3, now=now,
        )
    assert len(candidates) == 3
