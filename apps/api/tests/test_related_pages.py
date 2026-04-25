# ruff: noqa: E402
import atexit, importlib, os, shutil, tempfile
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="mrnote-s7-rel-"))
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
from app.models import (
    Memory, MemoryEpisode, MemoryEvidence, Notebook, NotebookPage,
    Project, User, Workspace,
)
from app.services.related_pages import get_related


def setup_function() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _seed_two_pages_sharing_memory() -> tuple[str, str, str]:
    """Returns (workspace_id, page_a_id, page_b_id)."""
    with SessionLocal() as db:
        ws = Workspace(name="W"); user = User(email="u@x.co", password_hash="x")
        db.add(ws); db.add(user); db.commit(); db.refresh(ws); db.refresh(user)
        pr = Project(workspace_id=ws.id, name="P")
        db.add(pr); db.commit(); db.refresh(pr)
        nb = Notebook(workspace_id=ws.id, project_id=pr.id,
                      created_by=user.id, title="NB", slug="nb")
        db.add(nb); db.commit(); db.refresh(nb)
        a = NotebookPage(notebook_id=nb.id, created_by=user.id,
                         title="A", slug="a", plain_text="page A")
        b = NotebookPage(notebook_id=nb.id, created_by=user.id,
                         title="B", slug="b", plain_text="page B")
        db.add(a); db.add(b); db.commit(); db.refresh(a); db.refresh(b)
        mem = Memory(workspace_id=ws.id, project_id=pr.id,
                     content="shared fact", confidence=0.5,
                     node_status="active")
        db.add(mem); db.commit(); db.refresh(mem)
        ep_a = MemoryEpisode(
            workspace_id=ws.id, project_id=pr.id,
            source_type="notebook_page", source_id=a.id,
            chunk_text="from A",
        )
        ep_b = MemoryEpisode(
            workspace_id=ws.id, project_id=pr.id,
            source_type="notebook_page", source_id=b.id,
            chunk_text="from B",
        )
        db.add(ep_a); db.add(ep_b); db.commit()
        db.refresh(ep_a); db.refresh(ep_b)
        db.add(MemoryEvidence(
            workspace_id=ws.id, project_id=pr.id,
            memory_id=mem.id, source_type="notebook_page",
            episode_id=ep_a.id, quote_text="from A", confidence=0.5,
        ))
        db.add(MemoryEvidence(
            workspace_id=ws.id, project_id=pr.id,
            memory_id=mem.id, source_type="notebook_page",
            episode_id=ep_b.id, quote_text="from B", confidence=0.5,
        ))
        db.commit()
        return ws.id, a.id, b.id


def test_shared_subject_returns_other_page() -> None:
    ws_id, a_id, b_id = _seed_two_pages_sharing_memory()
    with SessionLocal() as db:
        out = get_related(db, page_id=a_id, workspace_id=ws_id, limit=5)
    page_ids = [p["id"] for p in out["pages"]]
    assert b_id in page_ids
    assert out["pages"][0]["reason"] == "shared_subject"


def test_returns_connected_memory_in_memory_bucket() -> None:
    ws_id, a_id, _ = _seed_two_pages_sharing_memory()
    with SessionLocal() as db:
        out = get_related(db, page_id=a_id, workspace_id=ws_id, limit=5)
    assert len(out["memory"]) >= 1
    assert out["memory"][0]["reason"] == "shared_subject"


def test_page_with_no_evidence_returns_empty() -> None:
    ws_id, _, _ = _seed_two_pages_sharing_memory()
    with SessionLocal() as db:
        pr = db.query(Project).filter_by(workspace_id=ws_id).first()
        user = db.query(User).first()
        nb = Notebook(workspace_id=ws_id, project_id=pr.id,
                      created_by=user.id, title="iso", slug="iso")
        db.add(nb); db.commit(); db.refresh(nb)
        p = NotebookPage(notebook_id=nb.id, created_by=user.id,
                         title="iso", slug="iso", plain_text="")
        db.add(p); db.commit(); db.refresh(p)
        out = get_related(db, page_id=p.id, workspace_id=ws_id, limit=5)
    assert out["pages"] == []
    assert out["memory"] == []


def test_returns_empty_for_unknown_page_id() -> None:
    ws_id, _, _ = _seed_two_pages_sharing_memory()
    with SessionLocal() as db:
        out = get_related(db, page_id="nonexistent", workspace_id=ws_id, limit=5)
    assert out == {"pages": [], "memory": []}
