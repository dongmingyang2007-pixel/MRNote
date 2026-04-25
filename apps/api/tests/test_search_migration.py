# ruff: noqa: E402
import atexit, importlib, os, shutil, tempfile
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="mrnote-s7-mig-"))
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
from app.models import NotebookPage, Notebook, User, Workspace


def setup_function() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def test_notebook_page_has_embedding_id_column() -> None:
    with SessionLocal() as db:
        ws = Workspace(name="W"); user = User(email="u@x.co", password_hash="x")
        db.add(ws); db.add(user); db.commit(); db.refresh(ws); db.refresh(user)
        nb = Notebook(workspace_id=ws.id, created_by=user.id, title="NB", slug="nb")
        db.add(nb); db.commit(); db.refresh(nb)
        page = NotebookPage(
            notebook_id=nb.id, created_by=user.id,
            title="T", slug="t", plain_text="hello",
            embedding_id="emb-123",
        )
        db.add(page); db.commit(); db.refresh(page)
    assert page.embedding_id == "emb-123"


def test_notebook_page_embedding_id_defaults_null() -> None:
    with SessionLocal() as db:
        ws = Workspace(name="W"); user = User(email="u2@x.co", password_hash="x")
        db.add(ws); db.add(user); db.commit(); db.refresh(ws); db.refresh(user)
        nb = Notebook(workspace_id=ws.id, created_by=user.id, title="NB", slug="nb")
        db.add(nb); db.commit(); db.refresh(nb)
        page = NotebookPage(
            notebook_id=nb.id, created_by=user.id,
            title="T", slug="t", plain_text="x",
        )
        db.add(page); db.commit(); db.refresh(page)
    assert page.embedding_id is None
