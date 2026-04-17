# ruff: noqa: E402
import atexit, importlib, os, shutil, tempfile
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-s7-emb-"))
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
from app.models import Notebook, NotebookPage, Project, User, Workspace


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


def _seed_pages(n: int = 3, min_len: int = 50) -> list[str]:
    ids = []
    with SessionLocal() as db:
        ws = Workspace(name="W"); user = User(email="u@x.co", password_hash="x")
        db.add(ws); db.add(user); db.commit(); db.refresh(ws); db.refresh(user)
        pr = Project(workspace_id=ws.id, name="P")
        db.add(pr); db.commit(); db.refresh(pr)
        nb = Notebook(workspace_id=ws.id, project_id=pr.id,
                      created_by=user.id, title="NB", slug="nb")
        db.add(nb); db.commit(); db.refresh(nb)
        for i in range(n):
            p = NotebookPage(
                notebook_id=nb.id, created_by=user.id,
                title=f"P{i}", slug=f"p{i}",
                plain_text="x" * min_len,
            )
            db.add(p); db.commit(); db.refresh(p)
            ids.append(p.id)
    return ids


def test_backfill_processes_pages_with_null_embedding() -> None:
    _seed_pages(n=3)

    async def fake_embed_and_store(*args, **kwargs):
        return "fake-emb-" + (kwargs.get("chunk_text", "")[:5] or "x")

    with patch(
        "app.tasks.worker_tasks.embed_and_store",
        new=AsyncMock(side_effect=fake_embed_and_store),
    ):
        from app.tasks.worker_tasks import backfill_notebook_page_embeddings_task
        result = backfill_notebook_page_embeddings_task.run()

    assert result["total_processed"] == 3
    assert result["succeeded"] == 3
    with SessionLocal() as db:
        pages = db.query(NotebookPage).all()
    assert all(p.embedding_id is not None for p in pages)


def test_backfill_skips_pages_with_short_text() -> None:
    _seed_pages(n=2, min_len=5)  # below threshold

    with patch(
        "app.tasks.worker_tasks.embed_and_store",
        new=AsyncMock(return_value="never-called"),
    ):
        from app.tasks.worker_tasks import backfill_notebook_page_embeddings_task
        result = backfill_notebook_page_embeddings_task.run()

    assert result["total_processed"] == 0


def test_backfill_idempotent_on_rerun() -> None:
    _seed_pages(n=2)

    async def fake_embed(*a, **k):
        return "fake-emb"

    with patch(
        "app.tasks.worker_tasks.embed_and_store",
        new=AsyncMock(side_effect=fake_embed),
    ):
        from app.tasks.worker_tasks import backfill_notebook_page_embeddings_task
        result1 = backfill_notebook_page_embeddings_task.run()
        result2 = backfill_notebook_page_embeddings_task.run()

    assert result1["total_processed"] == 2
    assert result2["total_processed"] == 0  # all have embedding_id
