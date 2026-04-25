# ruff: noqa: E402
import atexit, importlib, os, shutil, tempfile
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="mrnote-s7-vec-"))
atexit.register(lambda: shutil.rmtree(TEST_TEMP_DIR, ignore_errors=True))
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_TEMP_DIR / 'test.db'}"
os.environ["ENV"] = "test"

import app.core.config as config_module
config_module.get_settings.cache_clear()
config_module.settings = config_module.get_settings()
import app.db.session as session_module
importlib.reload(session_module)

import asyncio
from unittest.mock import patch, AsyncMock

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.services.search_vector import (
    search_pages_semantic,
    search_memories_semantic,
    search_study_chunks_semantic,
)


def setup_function() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def test_pages_semantic_returns_empty_on_sqlite() -> None:
    """pgvector operators raise on SQLite; function returns []."""
    with patch("app.services.search_vector.create_embedding",
               new=AsyncMock(return_value=[0.1] * 1024)):
        with SessionLocal() as db:
            out = asyncio.run(search_pages_semantic(
                db, workspace_id="w1", query="hi", limit=5,
            ))
    assert out == []


def test_memories_semantic_returns_empty_on_sqlite() -> None:
    with patch("app.services.search_vector.create_embedding",
               new=AsyncMock(return_value=[0.1] * 1024)):
        with SessionLocal() as db:
            out = asyncio.run(search_memories_semantic(
                db, workspace_id="w1", project_id="p1", query="hi", limit=5,
            ))
    assert out == []


def test_study_chunks_semantic_returns_empty_on_sqlite() -> None:
    with patch("app.services.search_vector.create_embedding",
               new=AsyncMock(return_value=[0.1] * 1024)):
        with SessionLocal() as db:
            out = asyncio.run(search_study_chunks_semantic(
                db, workspace_id="w1", query="hi", limit=5,
            ))
    assert out == []
