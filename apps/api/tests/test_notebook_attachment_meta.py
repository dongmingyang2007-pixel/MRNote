# ruff: noqa: E402
import atexit, os, shutil, tempfile
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="mrnote-s2-att-meta-"))
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
from app.models import (
    Notebook, NotebookAttachment, NotebookPage, Project, User, Workspace,
)


def setup_function() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def test_attachment_meta_json_roundtrip() -> None:
    with SessionLocal() as db:
        ws = Workspace(name="W"); user = User(email="u@x.co", password_hash="x")
        db.add(ws); db.add(user); db.commit(); db.refresh(ws); db.refresh(user)
        pr = Project(workspace_id=ws.id, name="P"); db.add(pr); db.commit(); db.refresh(pr)
        nb = Notebook(workspace_id=ws.id, project_id=pr.id, created_by=user.id,
                      title="NB", slug="nb")
        db.add(nb); db.commit(); db.refresh(nb)
        pg = NotebookPage(notebook_id=nb.id, created_by=user.id,
                          title="T", slug="t", plain_text="x")
        db.add(pg); db.commit(); db.refresh(pg)

        att = NotebookAttachment(
            page_id=pg.id,
            attachment_type="pdf",
            title="chapter1.pdf",
            meta_json={"object_key": "w/p/abc/chapter1.pdf"},
        )
        db.add(att); db.commit(); db.refresh(att)

        reloaded = db.query(NotebookAttachment).filter_by(id=att.id).one()
    assert reloaded.meta_json == {"object_key": "w/p/abc/chapter1.pdf"}
