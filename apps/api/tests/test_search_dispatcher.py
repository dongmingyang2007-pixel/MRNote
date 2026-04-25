# ruff: noqa: E402
import atexit, importlib, os, shutil, tempfile
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="mrnote-s7-disp-"))
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
from app.models import (
    Memory, MemoryView, Notebook, NotebookBlock, NotebookPage,
    Project, StudyAsset, User, Workspace,
)
from app.services.search_dispatcher import search_workspace, SCOPES


def setup_function() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _seed() -> tuple[str, str, str, str]:
    """Returns (workspace_id, project_id, notebook_id, page_id)."""
    with SessionLocal() as db:
        ws = Workspace(name="W"); user = User(email="u@x.co", password_hash="x")
        db.add(ws); db.add(user); db.commit(); db.refresh(ws); db.refresh(user)
        pr = Project(workspace_id=ws.id, name="P")
        db.add(pr); db.commit(); db.refresh(pr)
        nb = Notebook(workspace_id=ws.id, project_id=pr.id,
                      created_by=user.id, title="NB", slug="nb")
        db.add(nb); db.commit(); db.refresh(nb)
        page = NotebookPage(
            notebook_id=nb.id, created_by=user.id,
            title="Login flow", slug="login-flow",
            plain_text="The login flow uses email + code verification.",
        )
        db.add(page); db.commit(); db.refresh(page)
        block = NotebookBlock(
            page_id=page.id, block_type="paragraph", sort_order=0,
            plain_text="Send verification code to the user's email inbox.",
            created_by=user.id,
        )
        db.add(block); db.commit()
        asset = StudyAsset(
            notebook_id=nb.id, created_by=user.id,
            title="Auth handbook", asset_type="pdf", status="ready",
        )
        db.add(asset); db.commit()
        mem = Memory(
            workspace_id=ws.id, project_id=pr.id,
            content="Email verification is the primary auth factor.",
            confidence=0.7, node_status="active",
        )
        db.add(mem); db.commit()
        view = MemoryView(
            workspace_id=ws.id, project_id=pr.id,
            source_subject_id=mem.id, view_type="playbook",
            content="Playbook: recover account via email OTP.",
        )
        db.add(view); db.commit()
        return ws.id, pr.id, nb.id, page.id


def test_short_query_returns_empty_dict_without_db_calls() -> None:
    ws_id, _, _, _ = _seed()
    with SessionLocal() as db:
        out = asyncio.run(search_workspace(
            db, workspace_id=ws_id, query="x",
            scopes=set(SCOPES), limit=5,
        ))
    assert all(out[s] == [] for s in SCOPES)


def test_pages_lexical_returns_matching_page() -> None:
    """On SQLite, trgm similarity/% operators don't exist — fallback to ILIKE."""
    ws_id, _, _, _ = _seed()
    with SessionLocal() as db:
        out = asyncio.run(search_workspace(
            db, workspace_id=ws_id, query="login",
            scopes={"pages"}, limit=5,
        ))
    assert len(out["pages"]) >= 1
    assert "login" in out["pages"][0]["snippet"].lower()


def test_blocks_lexical_returns_matching_block() -> None:
    ws_id, _, _, _ = _seed()
    with SessionLocal() as db:
        out = asyncio.run(search_workspace(
            db, workspace_id=ws_id, query="verification",
            scopes={"blocks"}, limit=5,
        ))
    assert len(out["blocks"]) >= 1


def test_study_assets_lexical_matches_title() -> None:
    ws_id, _, _, _ = _seed()
    with SessionLocal() as db:
        out = asyncio.run(search_workspace(
            db, workspace_id=ws_id, query="handbook",
            scopes={"study_assets"}, limit=5,
        ))
    assert any("handbook" in h["title"].lower() for h in out["study_assets"])


def test_memory_lexical_returns_hits() -> None:
    ws_id, _, _, _ = _seed()
    with SessionLocal() as db:
        out = asyncio.run(search_workspace(
            db, workspace_id=ws_id, query="email",
            scopes={"memory"}, limit=5,
        ))
    assert "memory" in out


def test_playbooks_lexical_filters_by_view_type() -> None:
    ws_id, _, _, _ = _seed()
    with SessionLocal() as db:
        out = asyncio.run(search_workspace(
            db, workspace_id=ws_id, query="playbook",
            scopes={"playbooks"}, limit=5,
        ))
    assert "playbooks" in out


def test_one_scope_failure_does_not_break_others() -> None:
    """Force memory scope to raise; pages should still return."""
    ws_id, _, _, _ = _seed()
    with patch(
        "app.services.search_dispatcher._search_memory",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        with SessionLocal() as db:
            out = asyncio.run(search_workspace(
                db, workspace_id=ws_id, query="login",
                scopes={"pages", "memory"}, limit=5,
            ))
    assert len(out["pages"]) >= 1
    assert out["memory"] == []
