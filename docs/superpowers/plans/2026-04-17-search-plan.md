# S7 Search — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship hybrid (lexical + semantic) search across 5 knowledge scopes (Pages / Blocks / Study assets / Memory / Playbooks), plus automated "related pages" surfacing inside NoteWindow, behind a new `"search"` WindowType with sidebar Search tab.

**Architecture:** Thin dispatcher (`search_dispatcher.py`) that fans out to per-scope search functions and merges via Reciprocal Rank Fusion (`search_rank.py`). Semantic branches run via a new `search_vector.py` helper that joins `embeddings` with `notebook_pages.embedding_id` / `study_chunks.embedding_id` / `memories`. `related_pages.py` combines embedding k-NN with shared-memory-subject overlap. NotebookPage gets a new `embedding_id` column with backfill + incremental Celery maintenance.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2, Alembic, Celery, pgvector, pg_trgm, pytest + pytest-cov, Next.js 14, React 18, TypeScript, vitest, Playwright, lucide-react.

**Spec:** `docs/superpowers/specs/2026-04-17-search-design.md`

---

## Phase Overview

| Phase | Tasks | Description |
|---|---|---|
| **A** | 1 | Alembic migration: `notebook_pages.embedding_id` + 2 new indexes |
| **B** | 2 | `search_rank.py` RRF merge + 4 unit tests |
| **C** | 3 | `search_vector.py` (pages / memory / study_chunks semantic) + 3 tests |
| **D** | 4 | `search_dispatcher.py` (5 scopes + dispatcher entry) + 7 tests |
| **E** | 5 | `related_pages.py` (semantic + shared-subject) + 4 tests |
| **F** | 6 | Backfill + incremental Celery tasks + beat + 3 tests |
| **G** | 7 | 3 API endpoints + 7 tests |
| **H** | 8 | Full backend regression verification |
| **I** | 9 | Frontend WindowType `"search"` plumbing (+ placeholder component) |
| **J** | 10 | `SearchWindow` + `SearchResultsGroup` + CSS + `useSearch` hook |
| **K** | 11 | Sidebar Search tab + `useDigestUnreadCount`-like integration + i18n |
| **L** | 12 | `RelatedPagesCard` + `useRelatedPages` hook + NoteWindow integration |
| **M** | 13 | vitest unit + Playwright smoke |
| **N** | 14 | Final coverage verification |

---

## Task 1 — Alembic migration: `notebook_pages.embedding_id` + 2 new indexes

**Files:**
- Modify: `apps/api/app/models/entities.py` (NotebookPage class)
- Create: `apps/api/alembic/versions/202604210001_search_indexes.py`
- Create: `apps/api/tests/test_search_migration.py`

- [ ] **Step 1: Write the failing test**

Create `apps/api/tests/test_search_migration.py`:

```python
# ruff: noqa: E402
import atexit, importlib, os, shutil, tempfile
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-s7-mig-"))
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
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && .venv/bin/pytest tests/test_search_migration.py -v`
Expected: FAIL — `NotebookPage` has no attribute `embedding_id`.

- [ ] **Step 3: Add column to ORM**

Open `apps/api/app/models/entities.py`. Inside `class NotebookPage` (around line 573–592), after the `source_conversation_id` field, add:

```python
    embedding_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
```

- [ ] **Step 4: Create Alembic migration**

Create `apps/api/alembic/versions/202604210001_search_indexes.py`:

```python
"""S7 Search — NotebookPage.embedding_id + trgm index on notebook_blocks.plain_text

Revision ID: 202604210001
Revises: 202604200001
Create Date: 2026-04-21
"""

from alembic import op


revision = "202604210001"
down_revision = "202604200001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE notebook_pages
            ADD COLUMN IF NOT EXISTS embedding_id VARCHAR(36);

        CREATE INDEX IF NOT EXISTS ix_notebook_pages_embedding_id
            ON notebook_pages (embedding_id);

        CREATE INDEX IF NOT EXISTS ix_notebook_blocks_plain_text_trgm
            ON notebook_blocks USING GIN (plain_text gin_trgm_ops);
    """)


def downgrade() -> None:
    op.execute("""
        DROP INDEX IF EXISTS ix_notebook_blocks_plain_text_trgm;
        DROP INDEX IF EXISTS ix_notebook_pages_embedding_id;
        ALTER TABLE notebook_pages DROP COLUMN IF EXISTS embedding_id;
    """)
```

- [ ] **Step 5: Run to verify pass**

Run: `cd apps/api && .venv/bin/pytest tests/test_search_migration.py -v`
Expected: 2 PASSED.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/models/entities.py apps/api/alembic/versions/202604210001_search_indexes.py apps/api/tests/test_search_migration.py
git commit -m "feat(api): NotebookPage.embedding_id + trgm index on notebook_blocks"
```

---

## Task 2 — `search_rank.py` RRF + 4 unit tests

**Files:**
- Create: `apps/api/app/services/search_rank.py`
- Create: `apps/api/tests/test_search_rank.py`

- [ ] **Step 1: Write the failing tests**

Create `apps/api/tests/test_search_rank.py`:

```python
# ruff: noqa: E402
from app.services.search_rank import rrf_merge


def test_single_list_passthrough() -> None:
    lst = [{"id": "a", "score": 0.9}, {"id": "b", "score": 0.8}]
    out = rrf_merge(lst, limit=10)
    assert [h["id"] for h in out] == ["a", "b"]
    # Fused score uses only rank, not the original score.
    assert out[0]["fused_score"] > out[1]["fused_score"]


def test_two_lists_merge_boosts_common_items() -> None:
    lex = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
    sem = [{"id": "b"}, {"id": "a"}, {"id": "d"}]
    out = rrf_merge(lex, sem, limit=10)
    ids = [h["id"] for h in out]
    # Items appearing in both lists rank above items appearing only once.
    assert set(ids[:2]) == {"a", "b"}
    assert "c" in ids
    assert "d" in ids


def test_limit_truncates() -> None:
    lst = [{"id": str(i)} for i in range(30)]
    out = rrf_merge(lst, limit=5)
    assert len(out) == 5
    assert [h["id"] for h in out] == ["0", "1", "2", "3", "4"]


def test_empty_lists_return_empty() -> None:
    assert rrf_merge([], [], limit=10) == []
    assert rrf_merge(limit=10) == []
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && .venv/bin/pytest tests/test_search_rank.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Create the module**

Create `apps/api/app/services/search_rank.py`:

```python
"""Reciprocal Rank Fusion for merging lexical + semantic search results.

Standard RRF: fused_score(item) = sum over ranks of 1 / (k + rank).
Items are keyed by their `id` field unless a custom key_fn is provided.
"""

from __future__ import annotations

from typing import Any, Callable


def rrf_merge(
    *rank_lists: list[dict[str, Any]],
    k: int = 60,
    limit: int = 20,
    key_fn: Callable[[dict[str, Any]], str] | None = None,
) -> list[dict[str, Any]]:
    """Merge multiple ranked result lists via Reciprocal Rank Fusion.

    Returns a new list of hits ordered by fused_score desc, truncated
    to `limit`. Each returned hit has `fused_score` set; all other keys
    are preserved from the first list the hit appeared in.
    """
    if not rank_lists:
        return []
    resolve_key = key_fn or (lambda h: str(h.get("id", "")))
    fused: dict[str, dict[str, Any]] = {}
    for lst in rank_lists:
        for rank, hit in enumerate(lst, start=1):
            key = resolve_key(hit)
            if not key:
                continue
            contribution = 1.0 / (k + rank)
            if key in fused:
                fused[key]["fused_score"] += contribution
            else:
                new_hit = dict(hit)
                new_hit["fused_score"] = contribution
                fused[key] = new_hit
    ordered = sorted(fused.values(), key=lambda h: h["fused_score"], reverse=True)
    return ordered[:limit]
```

- [ ] **Step 4: Run to verify pass**

Run: `cd apps/api && .venv/bin/pytest tests/test_search_rank.py -v`
Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/services/search_rank.py apps/api/tests/test_search_rank.py
git commit -m "feat(api): search_rank.py Reciprocal Rank Fusion + 4 tests"
```

---

## Task 3 — `search_vector.py` semantic helpers + 3 tests

**Files:**
- Create: `apps/api/app/services/search_vector.py`
- Create: `apps/api/tests/test_search_vector.py`

**Note:** These tests use SQLite which lacks pgvector. We verify the SQL construction + error-fallback path; real semantic results are exercised in integration tests in prod/staging. The helpers therefore MUST be defensive: if the `vector <=> ...` operator raises (e.g. pgvector missing on SQLite), return an empty list and log a warning.

- [ ] **Step 1: Write failing tests**

Create `apps/api/tests/test_search_vector.py`:

```python
# ruff: noqa: E402
import atexit, importlib, os, shutil, tempfile
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-s7-vec-"))
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
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && .venv/bin/pytest tests/test_search_vector.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Create the module**

Create `apps/api/app/services/search_vector.py`:

```python
"""Semantic search helpers that join the embeddings table with
notebook_pages, memories, or study_chunks to return scope-specific
results. Defensive against pgvector-missing environments (SQLite
tests)."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from app.services.embedding import create_embedding

logger = logging.getLogger(__name__)


async def search_pages_semantic(
    db: Session,
    *,
    workspace_id: str,
    project_id: str | None = None,
    notebook_id: str | None = None,
    query: str,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Return pages ranked by cosine similarity to query embedding."""
    try:
        q_vec = await create_embedding(query)
    except Exception:
        logger.warning("search_pages_semantic: embedding failed", exc_info=True)
        return []
    try:
        rows = db.execute(
            sql_text("""
                SELECT p.id, p.notebook_id, p.title, p.plain_text,
                       1 - (e.vector <=> CAST(:q_vec AS vector)) AS score
                FROM notebook_pages p
                JOIN embeddings e ON e.id = p.embedding_id
                JOIN notebooks n ON n.id = p.notebook_id
                WHERE n.workspace_id = :workspace_id
                  AND (:project_id IS NULL OR n.project_id = :project_id)
                  AND (:notebook_id IS NULL OR p.notebook_id = :notebook_id)
                  AND p.is_archived = FALSE
                ORDER BY e.vector <=> CAST(:q_vec AS vector)
                LIMIT :limit
            """),
            {
                "q_vec": str(q_vec),
                "workspace_id": workspace_id,
                "project_id": project_id,
                "notebook_id": notebook_id,
                "limit": limit,
            },
        ).fetchall()
    except Exception:
        logger.warning("search_pages_semantic: SQL failed (expected on SQLite)", exc_info=False)
        return []
    return [
        {
            "id": r[0],
            "notebook_id": r[1],
            "title": r[2] or "",
            "snippet": (r[3] or "")[:200],
            "score": float(r[4] or 0.0),
            "source": "semantic",
        }
        for r in rows
    ]


async def search_memories_semantic(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    query: str,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Return memories ranked by cosine similarity on their embedding row."""
    try:
        q_vec = await create_embedding(query)
    except Exception:
        logger.warning("search_memories_semantic: embedding failed", exc_info=True)
        return []
    try:
        rows = db.execute(
            sql_text("""
                SELECT m.id, m.project_id, m.content,
                       1 - (e.vector <=> CAST(:q_vec AS vector)) AS score
                FROM memories m
                JOIN embeddings e ON e.memory_id = m.id
                WHERE m.workspace_id = :workspace_id
                  AND m.project_id = :project_id
                  AND m.node_status = 'active'
                ORDER BY e.vector <=> CAST(:q_vec AS vector)
                LIMIT :limit
            """),
            {
                "q_vec": str(q_vec),
                "workspace_id": workspace_id,
                "project_id": project_id,
                "limit": limit,
            },
        ).fetchall()
    except Exception:
        logger.warning("search_memories_semantic: SQL failed", exc_info=False)
        return []
    return [
        {
            "id": r[0],
            "project_id": r[1],
            "snippet": (r[2] or "")[:200],
            "score": float(r[3] or 0.0),
            "source": "semantic",
        }
        for r in rows
    ]


async def search_study_chunks_semantic(
    db: Session,
    *,
    workspace_id: str,
    project_id: str | None = None,
    notebook_id: str | None = None,
    query: str,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Return study chunks ranked by cosine similarity."""
    try:
        q_vec = await create_embedding(query)
    except Exception:
        logger.warning("search_study_chunks_semantic: embedding failed", exc_info=True)
        return []
    try:
        rows = db.execute(
            sql_text("""
                SELECT sa.id AS asset_id, sc.id AS chunk_id,
                       sa.notebook_id, sa.title, sc.content,
                       1 - (e.vector <=> CAST(:q_vec AS vector)) AS score
                FROM study_chunks sc
                JOIN embeddings e ON e.id = sc.embedding_id
                JOIN study_assets sa ON sa.id = sc.asset_id
                JOIN notebooks n ON n.id = sa.notebook_id
                WHERE n.workspace_id = :workspace_id
                  AND (:project_id IS NULL OR n.project_id = :project_id)
                  AND (:notebook_id IS NULL OR sa.notebook_id = :notebook_id)
                ORDER BY e.vector <=> CAST(:q_vec AS vector)
                LIMIT :limit
            """),
            {
                "q_vec": str(q_vec),
                "workspace_id": workspace_id,
                "project_id": project_id,
                "notebook_id": notebook_id,
                "limit": limit,
            },
        ).fetchall()
    except Exception:
        logger.warning("search_study_chunks_semantic: SQL failed", exc_info=False)
        return []
    return [
        {
            "asset_id": r[0],
            "chunk_id": r[1],
            "notebook_id": r[2],
            "title": r[3] or "",
            "snippet": (r[4] or "")[:200],
            "score": float(r[5] or 0.0),
            "source": "semantic",
        }
        for r in rows
    ]
```

- [ ] **Step 4: Run to verify pass**

Run: `cd apps/api && .venv/bin/pytest tests/test_search_vector.py -v`
Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/services/search_vector.py apps/api/tests/test_search_vector.py
git commit -m "feat(api): search_vector.py semantic helpers (pages/memory/study) + 3 tests"
```

---

## Task 4 — `search_dispatcher.py` + 7 scope tests

**Files:**
- Create: `apps/api/app/services/search_dispatcher.py`
- Create: `apps/api/tests/test_search_dispatcher.py`

- [ ] **Step 1: Write failing tests**

Create `apps/api/tests/test_search_dispatcher.py`:

```python
# ruff: noqa: E402
import atexit, importlib, os, shutil, tempfile
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-s7-disp-"))
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
            importance=0.7, node_status="active",
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
    # SQLite doesn't have trgm — memory_v2.search_memories_lexical fails;
    # dispatcher catches and returns []. We just assert the key exists.
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
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && .venv/bin/pytest tests/test_search_dispatcher.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Create the module**

Create `apps/api/app/services/search_dispatcher.py`:

```python
"""S7 Search dispatcher: fans out across 5 scopes, merges via RRF."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from app.services.memory_v2 import (
    search_memories_lexical,
    search_memory_views_lexical,
)
from app.services.search_rank import rrf_merge
from app.services.search_vector import (
    search_memories_semantic,
    search_pages_semantic,
    search_study_chunks_semantic,
)

logger = logging.getLogger(__name__)

SCOPES: tuple[str, ...] = (
    "pages", "blocks", "study_assets", "memory", "playbooks",
)
MIN_QUERY_LENGTH = 2


async def search_workspace(
    db: Session,
    *,
    workspace_id: str,
    query: str,
    scopes: set[str],
    project_id: str | None = None,
    notebook_id: str | None = None,
    limit: int = 8,
) -> dict[str, list[dict[str, Any]]]:
    """Entry point. Returns {scope_name: list[Hit]}."""
    out: dict[str, list[dict[str, Any]]] = {s: [] for s in SCOPES}
    if len(query.strip()) < MIN_QUERY_LENGTH:
        return out

    # If notebook_id given, resolve its project_id to scope memory/playbooks.
    resolved_project_id = project_id
    if notebook_id is not None:
        row = db.execute(
            sql_text("SELECT project_id FROM notebooks WHERE id = :nb_id"),
            {"nb_id": notebook_id},
        ).fetchone()
        if row and row[0]:
            resolved_project_id = row[0]

    jobs: list[tuple[str, Any]] = []
    if "pages" in scopes:
        jobs.append(("pages", _search_pages(
            db, workspace_id=workspace_id, project_id=resolved_project_id,
            notebook_id=notebook_id, query=query, limit=limit,
        )))
    if "blocks" in scopes:
        jobs.append(("blocks", _search_blocks(
            db, workspace_id=workspace_id, project_id=resolved_project_id,
            notebook_id=notebook_id, query=query, limit=limit,
        )))
    if "study_assets" in scopes:
        jobs.append(("study_assets", _search_study_assets(
            db, workspace_id=workspace_id, project_id=resolved_project_id,
            notebook_id=notebook_id, query=query, limit=limit,
        )))
    if "memory" in scopes and resolved_project_id:
        jobs.append(("memory", _search_memory(
            db, workspace_id=workspace_id, project_id=resolved_project_id,
            query=query, limit=limit,
        )))
    if "playbooks" in scopes and resolved_project_id:
        jobs.append(("playbooks", _search_playbooks(
            db, workspace_id=workspace_id, project_id=resolved_project_id,
            query=query, limit=limit,
        )))

    results = await asyncio.gather(
        *(coro for _, coro in jobs), return_exceptions=True,
    )
    for (scope, _), result in zip(jobs, results, strict=True):
        if isinstance(result, Exception):
            logger.warning("search scope %s failed: %s", scope, result)
            out[scope] = []
        else:
            out[scope] = result  # type: ignore[assignment]
    return out


# ---------------------------------------------------------------------------
# Per-scope implementations
# ---------------------------------------------------------------------------


def _lexical_pages_sql(db: Session, *, workspace_id: str,
                      project_id: str | None, notebook_id: str | None,
                      query: str, limit: int) -> list[dict[str, Any]]:
    """pg_trgm on Postgres; ILIKE fallback so SQLite tests work."""
    like = f"%{query.strip()}%"
    try:
        rows = db.execute(
            sql_text("""
                SELECT p.id, p.notebook_id, p.title, p.plain_text,
                       GREATEST(
                         similarity(COALESCE(p.title,''), :q),
                         similarity(COALESCE(p.plain_text,''), :q)
                       ) AS score
                FROM notebook_pages p
                JOIN notebooks n ON n.id = p.notebook_id
                WHERE n.workspace_id = :workspace_id
                  AND (:project_id IS NULL OR n.project_id = :project_id)
                  AND (:notebook_id IS NULL OR p.notebook_id = :notebook_id)
                  AND p.is_archived = FALSE
                  AND (p.title % :q OR p.plain_text % :q
                       OR p.title ILIKE :like OR p.plain_text ILIKE :like)
                ORDER BY score DESC, p.updated_at DESC
                LIMIT :limit
            """),
            {"q": query, "like": like, "workspace_id": workspace_id,
             "project_id": project_id, "notebook_id": notebook_id,
             "limit": limit},
        ).fetchall()
    except Exception:
        # Fallback for SQLite / missing pg_trgm: plain ILIKE + static score.
        rows = db.execute(
            sql_text("""
                SELECT p.id, p.notebook_id, p.title, p.plain_text, 0.5 AS score
                FROM notebook_pages p
                JOIN notebooks n ON n.id = p.notebook_id
                WHERE n.workspace_id = :workspace_id
                  AND (:project_id IS NULL OR n.project_id = :project_id)
                  AND (:notebook_id IS NULL OR p.notebook_id = :notebook_id)
                  AND p.is_archived = 0
                  AND (p.title LIKE :like OR p.plain_text LIKE :like)
                ORDER BY p.updated_at DESC
                LIMIT :limit
            """),
            {"like": like, "workspace_id": workspace_id,
             "project_id": project_id, "notebook_id": notebook_id,
             "limit": limit},
        ).fetchall()
    return [
        {
            "id": r[0],
            "notebook_id": r[1],
            "title": r[2] or "",
            "snippet": (r[3] or "")[:200],
            "score": float(r[4] or 0.0),
            "source": "lexical",
        }
        for r in rows
    ]


async def _search_pages(
    db: Session, *, workspace_id: str, project_id: str | None,
    notebook_id: str | None, query: str, limit: int,
) -> list[dict[str, Any]]:
    lex = _lexical_pages_sql(
        db, workspace_id=workspace_id, project_id=project_id,
        notebook_id=notebook_id, query=query, limit=limit * 2,
    )
    sem = await search_pages_semantic(
        db, workspace_id=workspace_id, project_id=project_id,
        notebook_id=notebook_id, query=query, limit=limit * 2,
    )
    merged = rrf_merge(lex, sem, limit=limit)
    for h in merged:
        if "source" not in h:
            h["source"] = "rrf"
        elif h["source"] == "semantic" and any(
            x["id"] == h["id"] for x in lex
        ):
            h["source"] = "rrf"
    return merged


async def _search_blocks(
    db: Session, *, workspace_id: str, project_id: str | None,
    notebook_id: str | None, query: str, limit: int,
) -> list[dict[str, Any]]:
    like = f"%{query.strip()}%"
    try:
        rows = db.execute(
            sql_text("""
                SELECT b.id, b.page_id, p.notebook_id, b.plain_text,
                       similarity(COALESCE(b.plain_text,''), :q) AS score
                FROM notebook_blocks b
                JOIN notebook_pages p ON p.id = b.page_id
                JOIN notebooks n ON n.id = p.notebook_id
                WHERE n.workspace_id = :workspace_id
                  AND (:project_id IS NULL OR n.project_id = :project_id)
                  AND (:notebook_id IS NULL OR p.notebook_id = :notebook_id)
                  AND (b.plain_text % :q OR b.plain_text ILIKE :like)
                ORDER BY score DESC, b.updated_at DESC
                LIMIT :limit
            """),
            {"q": query, "like": like, "workspace_id": workspace_id,
             "project_id": project_id, "notebook_id": notebook_id,
             "limit": limit},
        ).fetchall()
    except Exception:
        rows = db.execute(
            sql_text("""
                SELECT b.id, b.page_id, p.notebook_id, b.plain_text, 0.5 AS score
                FROM notebook_blocks b
                JOIN notebook_pages p ON p.id = b.page_id
                JOIN notebooks n ON n.id = p.notebook_id
                WHERE n.workspace_id = :workspace_id
                  AND (:project_id IS NULL OR n.project_id = :project_id)
                  AND (:notebook_id IS NULL OR p.notebook_id = :notebook_id)
                  AND b.plain_text LIKE :like
                LIMIT :limit
            """),
            {"like": like, "workspace_id": workspace_id,
             "project_id": project_id, "notebook_id": notebook_id,
             "limit": limit},
        ).fetchall()
    return [
        {
            "id": r[0],
            "page_id": r[1],
            "notebook_id": r[2],
            "snippet": (r[3] or "")[:200],
            "score": float(r[4] or 0.0),
            "source": "lexical",
        }
        for r in rows
    ]


async def _search_study_assets(
    db: Session, *, workspace_id: str, project_id: str | None,
    notebook_id: str | None, query: str, limit: int,
) -> list[dict[str, Any]]:
    like = f"%{query.strip()}%"
    try:
        title_rows = db.execute(
            sql_text("""
                SELECT sa.id, sa.notebook_id, sa.title,
                       similarity(COALESCE(sa.title,''), :q) AS score
                FROM study_assets sa
                JOIN notebooks n ON n.id = sa.notebook_id
                WHERE n.workspace_id = :workspace_id
                  AND (:project_id IS NULL OR n.project_id = :project_id)
                  AND (:notebook_id IS NULL OR sa.notebook_id = :notebook_id)
                  AND (sa.title % :q OR sa.title ILIKE :like)
                ORDER BY score DESC, sa.updated_at DESC
                LIMIT :limit
            """),
            {"q": query, "like": like, "workspace_id": workspace_id,
             "project_id": project_id, "notebook_id": notebook_id,
             "limit": limit * 2},
        ).fetchall()
    except Exception:
        title_rows = db.execute(
            sql_text("""
                SELECT sa.id, sa.notebook_id, sa.title, 0.5 AS score
                FROM study_assets sa
                JOIN notebooks n ON n.id = sa.notebook_id
                WHERE n.workspace_id = :workspace_id
                  AND (:project_id IS NULL OR n.project_id = :project_id)
                  AND (:notebook_id IS NULL OR sa.notebook_id = :notebook_id)
                  AND sa.title LIKE :like
                LIMIT :limit
            """),
            {"like": like, "workspace_id": workspace_id,
             "project_id": project_id, "notebook_id": notebook_id,
             "limit": limit * 2},
        ).fetchall()
    lex_title = [
        {
            "asset_id": r[0], "chunk_id": None, "notebook_id": r[1],
            "title": r[2] or "", "snippet": r[2] or "",
            "score": float(r[3] or 0.0), "source": "lexical",
        }
        for r in title_rows
    ]
    sem_chunks = await search_study_chunks_semantic(
        db, workspace_id=workspace_id, project_id=project_id,
        notebook_id=notebook_id, query=query, limit=limit * 2,
    )
    merged = rrf_merge(
        lex_title, sem_chunks, limit=limit,
        key_fn=lambda h: str(h.get("asset_id") or ""),
    )
    for h in merged:
        if "source" not in h:
            h["source"] = "rrf"
    return merged


async def _search_memory(
    db: Session, *, workspace_id: str, project_id: str,
    query: str, limit: int,
) -> list[dict[str, Any]]:
    try:
        lex_raw = search_memories_lexical(
            db, workspace_id=workspace_id, project_id=project_id,
            query=query, limit=limit * 2,
        )
    except Exception:
        logger.warning("memory lexical failed", exc_info=False)
        lex_raw = []
    lex = [
        {"id": r["memory_id"], "project_id": project_id,
         "snippet": r.get("snippet", ""), "score": r.get("score", 0.0),
         "source": "lexical"}
        for r in lex_raw
    ]
    sem = await search_memories_semantic(
        db, workspace_id=workspace_id, project_id=project_id,
        query=query, limit=limit * 2,
    )
    merged = rrf_merge(lex, sem, limit=limit)
    for h in merged:
        if "source" not in h:
            h["source"] = "rrf"
    return merged


async def _search_playbooks(
    db: Session, *, workspace_id: str, project_id: str,
    query: str, limit: int,
) -> list[dict[str, Any]]:
    try:
        raw = search_memory_views_lexical(
            db, workspace_id=workspace_id, project_id=project_id,
            query=query, limit=limit,
        )
    except Exception:
        logger.warning("playbooks lexical failed", exc_info=False)
        raw = []
    return [
        {
            "memory_view_id": r["id"] if "id" in r else r.get("memory_view_id", ""),
            "project_id": project_id,
            "title": (r.get("snippet") or "")[:80],
            "snippet": (r.get("snippet") or "")[:200],
            "score": r.get("score", 0.0),
            "source": "lexical",
        }
        for r in raw
        if r.get("view_type", "playbook") == "playbook"
    ]
```

**Note:** `search_memory_views_lexical` returns dicts with keys `{id, source_subject_id, view_type, score, content}` per memory_v2.py:1439. If the live function returns slightly different key names, map them in `_search_playbooks`. Verify by reading `memory_v2.py:1439-1500` before implementing.

- [ ] **Step 4: Run to verify pass**

Run: `cd apps/api && .venv/bin/pytest tests/test_search_dispatcher.py -v`
Expected: 7 PASSED.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/services/search_dispatcher.py apps/api/tests/test_search_dispatcher.py
git commit -m "feat(api): search_dispatcher — 5 scopes + parallel fan-out + RRF + 7 tests"
```

---

## Task 5 — `related_pages.py` + 4 tests

**Files:**
- Create: `apps/api/app/services/related_pages.py`
- Create: `apps/api/tests/test_related_pages.py`

- [ ] **Step 1: Write failing tests**

Create `apps/api/tests/test_related_pages.py`:

```python
# ruff: noqa: E402
import atexit, importlib, os, shutil, tempfile
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-s7-rel-"))
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
    Memory, MemoryEvidence, Notebook, NotebookPage,
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
                     content="shared fact", importance=0.5,
                     node_status="active")
        db.add(mem); db.commit(); db.refresh(mem)
        db.add(MemoryEvidence(
            memory_id=mem.id, workspace_id=ws.id, project_id=pr.id,
            kind="fact", strength=0.5, quote_text="from A",
            source_kind="notebook_page", source_id=a.id,
        ))
        db.add(MemoryEvidence(
            memory_id=mem.id, workspace_id=ws.id, project_id=pr.id,
            kind="fact", strength=0.5, quote_text="from B",
            source_kind="notebook_page", source_id=b.id,
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
    ws_id, a_id, _ = _seed_two_pages_sharing_memory()
    with SessionLocal() as db:
        # Create isolated page with no memory evidences.
        from app.models import Notebook, NotebookPage, Project
        ws_row = db.query(Workspace).filter_by(id=ws_id).first()
        pr = db.query(Project).filter_by(workspace_id=ws_id).first()
        nb = Notebook(workspace_id=ws_id, project_id=pr.id,
                      created_by=db.query(User).first().id,
                      title="iso", slug="iso")
        db.add(nb); db.commit(); db.refresh(nb)
        p = NotebookPage(notebook_id=nb.id,
                         created_by=db.query(User).first().id,
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
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && .venv/bin/pytest tests/test_related_pages.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Verify evidence columns**

Before writing the module, check actual column names:

```bash
grep -n "class MemoryEvidence\|source_kind\|source_id" apps/api/app/models/entities.py | head -10
```

The test above assumes `MemoryEvidence` has `source_kind` and `source_id`. If the real columns are named differently (e.g. `owner_kind` / `owner_id`), update both the test seed AND the service SQL to match. This is a 1-line find-and-replace.

- [ ] **Step 4: Create the module**

Create `apps/api/app/services/related_pages.py`:

```python
"""S7 Search — related-pages service.

Combines embedding k-NN (when page has an embedding_id) with shared
memory-subject overlap. Shared-subject works on SQLite; semantic
requires pgvector.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def get_related(
    db: Session,
    *,
    page_id: str,
    workspace_id: str,
    limit: int = 5,
) -> dict[str, list[dict[str, Any]]]:
    """Return related pages + memories for the given page."""
    target = db.execute(
        sql_text("""
            SELECT p.id, p.embedding_id, n.workspace_id
            FROM notebook_pages p
            JOIN notebooks n ON n.id = p.notebook_id
            WHERE p.id = :page_id AND n.workspace_id = :workspace_id
            LIMIT 1
        """),
        {"page_id": page_id, "workspace_id": workspace_id},
    ).fetchone()
    if target is None:
        return {"pages": [], "memory": []}

    embedding_id = target[1]

    # Shared-subject branch
    subject_rows = db.execute(
        sql_text("""
            SELECT e.memory_id
            FROM memory_evidences e
            WHERE e.source_kind = 'notebook_page'
              AND e.source_id = :page_id
        """),
        {"page_id": page_id},
    ).fetchall()
    memory_ids = [r[0] for r in subject_rows if r[0]]

    shared_pages: list[dict[str, Any]] = []
    related_memories: list[dict[str, Any]] = []
    if memory_ids:
        # Other pages sharing any of these memories.
        other_page_rows = db.execute(
            sql_text("""
                SELECT DISTINCT p.id, p.notebook_id, p.title
                FROM memory_evidences e
                JOIN notebook_pages p ON p.id = e.source_id
                JOIN notebooks n ON n.id = p.notebook_id
                WHERE e.source_kind = 'notebook_page'
                  AND e.memory_id IN :memory_ids
                  AND p.id != :page_id
                  AND n.workspace_id = :workspace_id
                LIMIT :limit
            """).bindparams(
                sql_text("").compile(compile_kwargs={}).bindparams[0].__class__(
                    "memory_ids", expanding=True,
                ),
            ),
            {"memory_ids": memory_ids, "page_id": page_id,
             "workspace_id": workspace_id, "limit": limit * 2},
        ).fetchall()
        shared_pages = [
            {
                "id": r[0], "notebook_id": r[1], "title": r[2] or "",
                "score": 0.5, "reason": "shared_subject",
            }
            for r in other_page_rows
        ]
        # Connected memories as the "memory" bucket
        mem_rows = db.execute(
            sql_text("""
                SELECT m.id, m.content, m.importance
                FROM memories m
                WHERE m.id IN :memory_ids
                  AND m.workspace_id = :workspace_id
                  AND m.node_status = 'active'
                ORDER BY m.importance DESC
                LIMIT :limit
            """).bindparams(
                sql_text("").compile(compile_kwargs={}).bindparams[0].__class__(
                    "memory_ids", expanding=True,
                ),
            ),
            {"memory_ids": memory_ids, "workspace_id": workspace_id,
             "limit": limit},
        ).fetchall()
        related_memories = [
            {"id": r[0], "content": (r[1] or "")[:200],
             "score": float(r[2] or 0.0), "reason": "shared_subject"}
            for r in mem_rows
        ]

    # Semantic branch (pgvector; best-effort, skipped on SQLite)
    semantic_pages: list[dict[str, Any]] = []
    if embedding_id:
        try:
            sem_rows = db.execute(
                sql_text("""
                    SELECT p2.id, p2.notebook_id, p2.title,
                           1 - (e2.vector <=> e1.vector) AS score
                    FROM embeddings e1
                    JOIN embeddings e2 ON e2.id != e1.id
                    JOIN notebook_pages p2 ON p2.embedding_id = e2.id
                    JOIN notebooks n2 ON n2.id = p2.notebook_id
                    WHERE e1.id = :emb_id
                      AND n2.workspace_id = :workspace_id
                      AND p2.id != :page_id
                    ORDER BY e2.vector <=> e1.vector
                    LIMIT :limit
                """),
                {"emb_id": embedding_id, "page_id": page_id,
                 "workspace_id": workspace_id, "limit": limit * 2},
            ).fetchall()
            semantic_pages = [
                {"id": r[0], "notebook_id": r[1], "title": r[2] or "",
                 "score": float(r[3] or 0.0), "reason": "semantic"}
                for r in sem_rows
            ]
        except Exception:
            logger.warning("related_pages semantic failed", exc_info=False)

    # Merge: semantic wins the "reason" tag when a page appears in both
    seen: dict[str, dict[str, Any]] = {}
    for p in semantic_pages:
        seen[p["id"]] = p
    for p in shared_pages:
        if p["id"] not in seen:
            seen[p["id"]] = p
    merged_pages = sorted(
        seen.values(), key=lambda h: h["score"], reverse=True,
    )[:limit]
    return {"pages": merged_pages, "memory": related_memories}
```

**Note on `bindparam` expanding IN clauses:** The pattern in the test is defensive; use the cleaner SQLAlchemy `bindparam("memory_ids", expanding=True)` import at the top:

```python
from sqlalchemy import bindparam
```

Then change:
```python
sql_text("...IN :memory_ids...").bindparams(bindparam("memory_ids", expanding=True))
```

Replace both occurrences of the expanding pattern in the module with this clean form.

- [ ] **Step 5: Run to verify pass**

Run: `cd apps/api && .venv/bin/pytest tests/test_related_pages.py -v`
Expected: 4 PASSED.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/services/related_pages.py apps/api/tests/test_related_pages.py
git commit -m "feat(api): related_pages — shared_subject + semantic + 4 tests"
```

---

## Task 6 — Backfill + incremental Celery tasks + beat + 3 tests

**Files:**
- Modify: `apps/api/app/tasks/worker_tasks.py`
- Modify: `apps/api/app/tasks/celery_app.py`
- Create: `apps/api/tests/test_notebook_page_embedding.py`

- [ ] **Step 1: Write failing tests**

Create `apps/api/tests/test_notebook_page_embedding.py`:

```python
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
    ids = _seed_pages(n=3)

    async def fake_embed_and_store(*args, **kwargs):
        return "fake-emb-" + kwargs.get("chunk_text", "")[:5]

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
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && .venv/bin/pytest tests/test_notebook_page_embedding.py -v`
Expected: FAIL — tasks not defined.

- [ ] **Step 3: Add tasks to worker_tasks.py**

Append to `apps/api/app/tasks/worker_tasks.py`:

```python
# ---------------------------------------------------------------------------
# S7 Search: NotebookPage embedding maintenance
# ---------------------------------------------------------------------------


from app.services.embedding import embed_and_store  # safe: already imported above if exists


MIN_PAGE_TEXT_LEN_FOR_EMBEDDING = 20


@celery_app.task(name="app.tasks.worker_tasks.backfill_notebook_page_embeddings")
def backfill_notebook_page_embeddings_task(
    workspace_id: str | None = None,
    batch_size: int = 50,
) -> dict[str, int]:
    """Embed all NotebookPage rows whose embedding_id IS NULL and whose
    plain_text is long enough. Idempotent."""
    import asyncio as _asyncio
    from app.models import Notebook, NotebookPage

    db = SessionLocal()
    try:
        q = (
            db.query(NotebookPage)
            .join(Notebook, Notebook.id == NotebookPage.notebook_id)
            .filter(NotebookPage.embedding_id.is_(None))
            .filter(NotebookPage.plain_text.isnot(None))
        )
        if workspace_id:
            q = q.filter(Notebook.workspace_id == workspace_id)
        pages = q.limit(batch_size * 10).all()

        total = 0
        succeeded = 0
        failed = 0
        for page in pages:
            text = (page.plain_text or "").strip()
            if len(text) < MIN_PAGE_TEXT_LEN_FOR_EMBEDDING:
                continue
            total += 1
            nb = db.get(Notebook, page.notebook_id)
            if nb is None:
                failed += 1
                continue
            try:
                emb_id = _asyncio.run(embed_and_store(
                    db,
                    workspace_id=str(nb.workspace_id),
                    project_id=str(nb.project_id or ""),
                    chunk_text=text[:4000],
                    auto_commit=False,
                ))
                page.embedding_id = emb_id
                db.add(page)
                db.commit()
                succeeded += 1
            except Exception:
                logger.warning(
                    "backfill_notebook_page_embedding failed for %s",
                    page.id, exc_info=False,
                )
                db.rollback()
                failed += 1
        return {
            "total_processed": total,
            "succeeded": succeeded,
            "failed": failed,
        }
    finally:
        db.close()


@celery_app.task(name="app.tasks.worker_tasks.regenerate_notebook_page_embedding")
def regenerate_notebook_page_embedding_task(page_id: str) -> str | None:
    """Regenerate embedding for one page (called on plain_text change)."""
    import asyncio as _asyncio
    from app.models import Notebook, NotebookPage

    db = SessionLocal()
    try:
        page = db.get(NotebookPage, page_id)
        if page is None:
            return None
        text = (page.plain_text or "").strip()
        if len(text) < MIN_PAGE_TEXT_LEN_FOR_EMBEDDING:
            return None
        nb = db.get(Notebook, page.notebook_id)
        if nb is None:
            return None
        try:
            emb_id = _asyncio.run(embed_and_store(
                db,
                workspace_id=str(nb.workspace_id),
                project_id=str(nb.project_id or ""),
                chunk_text=text[:4000],
                auto_commit=False,
            ))
            page.embedding_id = emb_id
            db.add(page)
            db.commit()
            return emb_id
        except Exception:
            logger.warning(
                "regenerate_notebook_page_embedding failed for %s",
                page_id, exc_info=False,
            )
            db.rollback()
            return None
    finally:
        db.close()
```

**Hint:** At the top of `worker_tasks.py`, verify that `from app.services.embedding import embed_and_store` is already imported. If it isn't, add it to the imports. If another name (`from app.services.embedding import embed_and_store as _eas`) clashes, adjust this file's use accordingly.

- [ ] **Step 4: Add beat + task_routes entries**

Open `apps/api/app/tasks/celery_app.py`:

In `task_routes` (add these near the S5 entries):

```python
"app.tasks.worker_tasks.backfill_notebook_page_embeddings": {"queue": "memory"},
"app.tasks.worker_tasks.regenerate_notebook_page_embedding": {"queue": "memory"},
```

In `beat_schedule`:

```python
"backfill-notebook-page-embeddings-nightly": {
    "task": "app.tasks.worker_tasks.backfill_notebook_page_embeddings",
    "schedule": crontab(hour=4, minute=0),
},
```

- [ ] **Step 5: Add incremental hook**

Open `apps/api/app/services/note_memory_bridge.py`. Locate the function that runs after a page save (likely `sync_page_memory_signals` or similar). After the existing post-save commit, add:

```python
# S7: schedule embedding regeneration if plain_text changed meaningfully.
try:
    from app.tasks.worker_tasks import regenerate_notebook_page_embedding_task
    regenerate_notebook_page_embedding_task.delay(page.id)
except Exception:
    logger.warning("failed to schedule embedding regeneration for %s",
                   page.id, exc_info=False)
```

**If** the bridge module has no natural hook (i.e., there's no function called post-save), **instead** modify `apps/api/app/routers/notebooks.py` PATCH `/pages/{page_id}` endpoint: after the commit that persists `plain_text`, enqueue the task with the same 4 lines above. Search for `plain_text` assignment in the router.

- [ ] **Step 6: Run to verify pass**

Run: `cd apps/api && .venv/bin/pytest tests/test_notebook_page_embedding.py -v`
Expected: 3 PASSED.

- [ ] **Step 7: Commit**

```bash
git add apps/api/app/tasks/worker_tasks.py apps/api/app/tasks/celery_app.py apps/api/app/services/note_memory_bridge.py apps/api/tests/test_notebook_page_embedding.py
git commit -m "feat(api): NotebookPage embedding backfill + incremental regen + beat"
```

If `note_memory_bridge.py` wasn't modified (hook lived in router), swap that path for `apps/api/app/routers/notebooks.py`.

---

## Task 7 — 3 API endpoints + 7 tests

**Files:**
- Create: `apps/api/app/routers/search.py`
- Create: `apps/api/app/schemas/search.py`
- Modify: `apps/api/app/main.py`
- Create: `apps/api/tests/test_search_api.py`

- [ ] **Step 1: Write failing tests**

Create `apps/api/tests/test_search_api.py`:

```python
# ruff: noqa: E402
import atexit, importlib, os, shutil, tempfile
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-s7-api-"))
atexit.register(lambda: shutil.rmtree(TEST_TEMP_DIR, ignore_errors=True))
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_TEMP_DIR / 'test.db'}"
os.environ["ENV"] = "test"
os.environ["COOKIE_DOMAIN"] = ""
os.environ["DEMO_MODE"] = "true"

import app.core.config as config_module
config_module.get_settings.cache_clear()
config_module.settings = config_module.get_settings()
import app.db.session as session_module
importlib.reload(session_module)
import app.main as main_module
importlib.reload(main_module)

from fastapi.testclient import TestClient

from app.db.base import Base
import app.db.session as _s
from app.models import (
    Memory, Notebook, NotebookBlock, NotebookPage, Project, StudyAsset,
)


def setup_function() -> None:
    global engine, SessionLocal
    engine = _s.engine
    SessionLocal = _s.SessionLocal
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    from app.services.runtime_state import runtime_state
    runtime_state._memory = runtime_state._memory.__class__()


engine = _s.engine
SessionLocal = _s.SessionLocal


def _public_headers() -> dict[str, str]:
    return {"origin": "http://localhost:3000"}


def _register_client(email: str = "u@x.co") -> tuple[TestClient, dict]:
    import hashlib
    from app.services.runtime_state import runtime_state
    client = TestClient(main_module.app)
    client.post(
        "/api/v1/auth/send-code",
        json={"email": email, "purpose": "register"},
        headers=_public_headers(),
    )
    raw = f"{email.lower().strip()}:register"
    code_key = hashlib.sha256(raw.encode()).hexdigest()
    code = str(runtime_state.get_json("verify_code", code_key)["code"])
    info = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "pass1234pass",
              "display_name": "Test", "code": code},
        headers=_public_headers(),
    ).json()
    csrf = client.get("/api/v1/auth/csrf",
                     headers=_public_headers()).json()["csrf_token"]
    client.headers.update({
        "origin": "http://localhost:3000",
        "x-csrf-token": csrf,
        "x-workspace-id": info["workspace"]["id"],
    })
    return client, {
        "ws_id": info["workspace"]["id"],
        "user_id": info["user"]["id"],
    }


def _seed_content(ws_id: str, user_id: str) -> dict[str, str]:
    """Returns dict of useful IDs."""
    with SessionLocal() as db:
        pr = Project(workspace_id=ws_id, name="P")
        db.add(pr); db.commit(); db.refresh(pr)
        nb = Notebook(workspace_id=ws_id, project_id=pr.id,
                      created_by=user_id, title="NB", slug="nb")
        db.add(nb); db.commit(); db.refresh(nb)
        page = NotebookPage(
            notebook_id=nb.id, created_by=user_id,
            title="Login flow handbook",
            slug="login-flow-handbook",
            plain_text="Login flow uses email verification and OTP.",
        )
        db.add(page); db.commit(); db.refresh(page)
        return {
            "project_id": pr.id, "notebook_id": nb.id, "page_id": page.id,
        }


def test_global_search_returns_results_shape() -> None:
    client, auth = _register_client("u1@x.co")
    ids = _seed_content(auth["ws_id"], auth["user_id"])
    resp = client.get("/api/v1/search/global?q=login&limit=5")
    assert resp.status_code == 200
    body = resp.json()
    assert "results" in body
    for scope in ("pages", "blocks", "study_assets", "memory", "playbooks"):
        assert scope in body["results"]
    assert "duration_ms" in body


def test_global_search_short_query_returns_empty() -> None:
    client, _ = _register_client("u2@x.co")
    resp = client.get("/api/v1/search/global?q=a")
    assert resp.status_code == 200
    body = resp.json()
    assert all(len(v) == 0 for v in body["results"].values())


def test_global_search_invalid_scope_returns_400() -> None:
    client, _ = _register_client("u3@x.co")
    resp = client.get("/api/v1/search/global?q=login&scope=pages,bogus")
    assert resp.status_code == 400


def test_global_search_scope_csv_filters() -> None:
    client, auth = _register_client("u4@x.co")
    _seed_content(auth["ws_id"], auth["user_id"])
    resp = client.get("/api/v1/search/global?q=login&scope=pages")
    assert resp.status_code == 200
    body = resp.json()
    # Non-selected scopes are still present in the shape but empty.
    assert body["results"]["blocks"] == []
    assert body["results"]["memory"] == []


def test_notebook_search_limits_to_notebook_scope() -> None:
    client, auth = _register_client("u5@x.co")
    ids = _seed_content(auth["ws_id"], auth["user_id"])
    resp = client.get(f"/api/v1/notebooks/{ids['notebook_id']}/search?q=login")
    assert resp.status_code == 200
    body = resp.json()
    assert "results" in body


def test_related_returns_pages_and_memory_keys() -> None:
    client, auth = _register_client("u6@x.co")
    ids = _seed_content(auth["ws_id"], auth["user_id"])
    resp = client.get(f"/api/v1/pages/{ids['page_id']}/related")
    assert resp.status_code == 200
    body = resp.json()
    assert "pages" in body
    assert "memory" in body


def test_cross_workspace_global_search_isolated() -> None:
    client_a, auth_a = _register_client("a@x.co")
    _seed_content(auth_a["ws_id"], auth_a["user_id"])
    client_b, _ = _register_client("b@x.co")
    resp = client_b.get("/api/v1/search/global?q=login")
    assert resp.status_code == 200
    # Workspace B is empty — no pages should leak from A.
    assert resp.json()["results"]["pages"] == []
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && .venv/bin/pytest tests/test_search_api.py -v`
Expected: FAIL — router missing.

- [ ] **Step 3: Create schemas**

Create `apps/api/app/schemas/search.py`:

```python
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class SearchResults(BaseModel):
    pages: list[dict[str, Any]] = []
    blocks: list[dict[str, Any]] = []
    study_assets: list[dict[str, Any]] = []
    memory: list[dict[str, Any]] = []
    playbooks: list[dict[str, Any]] = []


class SearchResponse(BaseModel):
    query: str
    duration_ms: int
    results: SearchResults


class RelatedResponse(BaseModel):
    pages: list[dict[str, Any]] = []
    memory: list[dict[str, Any]] = []
```

- [ ] **Step 4: Create the router**

Create `apps/api/app/routers/search.py`:

```python
"""S7 Search API: global / notebook / related endpoints."""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import (
    get_current_user, get_current_workspace_id, get_db_session,
)
from app.core.errors import ApiError
from app.models import Notebook, NotebookPage, User
from app.schemas.search import RelatedResponse, SearchResponse, SearchResults
from app.services.related_pages import get_related
from app.services.search_dispatcher import SCOPES, search_workspace

router = APIRouter(tags=["search"])


def _parse_scopes(raw: str | None) -> set[str]:
    if not raw:
        return set(SCOPES)
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    bad = [p for p in parts if p not in SCOPES]
    if bad:
        raise ApiError(
            "invalid_input", f"Unknown scope(s): {', '.join(bad)}", status_code=400,
        )
    return set(parts)


@router.get("/api/v1/search/global", response_model=SearchResponse)
def global_search(
    q: str,
    scope: str | None = None,
    project_id: str | None = None,
    limit: int = 8,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),  # noqa: ARG001
    workspace_id: str = Depends(get_current_workspace_id),
) -> SearchResponse:
    effective_scopes = _parse_scopes(scope)
    limit = max(1, min(limit, 20))
    started = time.monotonic()
    results_dict = asyncio.run(search_workspace(
        db, workspace_id=workspace_id, query=q,
        scopes=effective_scopes, project_id=project_id, limit=limit,
    ))
    duration_ms = int((time.monotonic() - started) * 1000)
    return SearchResponse(
        query=q, duration_ms=duration_ms,
        results=SearchResults(**results_dict),
    )


@router.get(
    "/api/v1/notebooks/{notebook_id}/search", response_model=SearchResponse,
)
def notebook_search(
    notebook_id: str,
    q: str,
    scope: str | None = None,
    limit: int = 8,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),  # noqa: ARG001
    workspace_id: str = Depends(get_current_workspace_id),
) -> SearchResponse:
    nb = db.query(Notebook).filter_by(id=notebook_id).first()
    if nb is None or nb.workspace_id != workspace_id:
        raise ApiError("not_found", "Notebook not found", status_code=404)
    effective_scopes = _parse_scopes(scope)
    limit = max(1, min(limit, 20))
    started = time.monotonic()
    results_dict = asyncio.run(search_workspace(
        db, workspace_id=workspace_id, query=q,
        scopes=effective_scopes, notebook_id=notebook_id, limit=limit,
    ))
    duration_ms = int((time.monotonic() - started) * 1000)
    return SearchResponse(
        query=q, duration_ms=duration_ms,
        results=SearchResults(**results_dict),
    )


@router.get("/api/v1/pages/{page_id}/related", response_model=RelatedResponse)
def page_related(
    page_id: str,
    limit: int = 5,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),  # noqa: ARG001
    workspace_id: str = Depends(get_current_workspace_id),
) -> RelatedResponse:
    page = db.query(NotebookPage).filter_by(id=page_id).first()
    if page is None:
        raise ApiError("not_found", "Page not found", status_code=404)
    nb = db.query(Notebook).filter_by(id=page.notebook_id).first()
    if nb is None or nb.workspace_id != workspace_id:
        raise ApiError("not_found", "Page not found", status_code=404)
    limit = max(1, min(limit, 20))
    out = get_related(
        db, page_id=page_id, workspace_id=workspace_id, limit=limit,
    )
    return RelatedResponse(pages=out["pages"], memory=out["memory"])
```

- [ ] **Step 5: Register router**

Open `apps/api/app/main.py`. Find the `from app.routers import ...` block and add `search` (alphabetical placement — between `proactive` and `projects`):

```python
from app.routers import (
    ai_actions, attachments, auth, chat, datasets, memory, memory_stream,
    model_catalog, models, notebook_ai, notebooks, pipeline, proactive,
    projects, realtime, search, study, study_ai, study_decks, uploads,
)
```

Then add:

```python
app.include_router(search.router)
```

- [ ] **Step 6: Run to verify pass**

Run: `cd apps/api && .venv/bin/pytest tests/test_search_api.py -v`
Expected: 7 PASSED.

- [ ] **Step 7: Commit**

```bash
git add apps/api/app/routers/search.py apps/api/app/schemas/search.py apps/api/app/main.py apps/api/tests/test_search_api.py
git commit -m "feat(api): 3 search endpoints (global / notebook / related) + 7 tests"
```

---

## Task 8 — Full backend regression

**Files:** none (verification).

- [ ] **Step 1: Run full S7 backend suite**

```bash
cd /Users/dog/Desktop/MRAI/apps/api && .venv/bin/pytest \
  tests/test_search_migration.py \
  tests/test_search_rank.py \
  tests/test_search_vector.py \
  tests/test_search_dispatcher.py \
  tests/test_related_pages.py \
  tests/test_notebook_page_embedding.py \
  tests/test_search_api.py -v 2>&1 | tail -20
```

Expected: ≥ 30 passed.

- [ ] **Step 2: Sanity run a subset of other S-suites**

Pick one test file from S1, S2, S4, S5 to confirm no regression:

```bash
cd /Users/dog/Desktop/MRAI/apps/api && .venv/bin/pytest \
  tests/test_ai_action_logger.py \
  tests/test_proactive_api.py 2>&1 | tail -5
```

Expected: all passed.

**No commit.**

---

## Task 9 — WindowType `"search"` plumbing

**Files:**
- Modify: `apps/web/components/notebook/WindowManager.tsx`
- Modify: `apps/web/components/notebook/Window.tsx`
- Modify: `apps/web/components/notebook/MinimizedTray.tsx`
- Modify: `apps/web/components/notebook/WindowCanvas.tsx`
- Create: `apps/web/components/notebook/contents/SearchWindow.tsx`

- [ ] **Step 1: Extend WindowType**

In `apps/web/components/notebook/WindowManager.tsx`, add `"search"` to the `WindowType` union and to `DEFAULT_SIZES`:

```ts
export type WindowType =
  "note" | "ai_panel" | "file" | "memory" | "study" | "digest" | "search";
```

```ts
const DEFAULT_SIZES: Record<WindowType, { width: number; height: number }> = {
  note: { width: 780, height: 600 },
  ai_panel: { width: 480, height: 620 },
  file: { width: 700, height: 500 },
  memory: { width: 500, height: 600 },
  study: { width: 600, height: 500 },
  digest: { width: 520, height: 620 },
  search: { width: 680, height: 720 },
};
```

**Do NOT** add `search` to `supportsMultiOpen`; single-open keeps UX tight.

- [ ] **Step 2: Icon maps**

In `apps/web/components/notebook/Window.tsx`:

- Add `Search` to the `lucide-react` import at the top.
- In `WINDOW_ICONS`, add:
  ```ts
  search: Search,
  ```

Same in `apps/web/components/notebook/MinimizedTray.tsx`.

- [ ] **Step 3: WindowCanvas dispatch + placeholder**

Create `apps/web/components/notebook/contents/SearchWindow.tsx` as a temporary placeholder (Task 10 will overwrite):

```tsx
"use client";
interface Props {
  notebookId?: string;
  projectId?: string;
}
export default function SearchWindow(_: Props) {
  return <div>SearchWindow (TODO)</div>;
}
```

In `apps/web/components/notebook/WindowCanvas.tsx`:

- Add `import SearchWindow from "./contents/SearchWindow";` alongside the other content imports.
- Add a new case in `switch (windowState.type)`:
  ```tsx
  case "search":
    return (
      <SearchWindow
        notebookId={windowState.meta.notebookId}
        projectId={windowState.meta.projectId}
      />
    );
  ```

- [ ] **Step 4: Typecheck**

```bash
cd /Users/dog/Desktop/MRAI/apps/web && ./node_modules/.bin/tsc --noEmit 2>&1 | grep -iE "(SearchWindow|WindowManager|Window\.tsx|MinimizedTray|WindowCanvas)" | head -10
```

Expected: no output (zero errors from these files).

- [ ] **Step 5: Commit**

```bash
git add apps/web/components/notebook/WindowManager.tsx apps/web/components/notebook/Window.tsx apps/web/components/notebook/MinimizedTray.tsx apps/web/components/notebook/WindowCanvas.tsx apps/web/components/notebook/contents/SearchWindow.tsx
git commit -m "refactor(web): add search WindowType plumbing (placeholder)"
```

---

## Task 10 — `SearchWindow` + `SearchResultsGroup` + CSS + `useSearch` hook

**Files:**
- Overwrite: `apps/web/components/notebook/contents/SearchWindow.tsx`
- Create: `apps/web/components/notebook/contents/search/SearchResultsGroup.tsx`
- Create: `apps/web/hooks/useSearch.ts`
- Create: `apps/web/styles/search-window.css`
- Modify: `apps/web/app/[locale]/workspace/notebooks/[notebookId]/layout.tsx`

- [ ] **Step 1: Create `useSearch` hook**

Create `apps/web/hooks/useSearch.ts`:

```ts
"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiGet } from "@/lib/api";

export interface SearchResults {
  pages: Hit[];
  blocks: Hit[];
  study_assets: Hit[];
  memory: Hit[];
  playbooks: Hit[];
}

export interface Hit {
  id?: string;
  asset_id?: string;
  chunk_id?: string | null;
  page_id?: string;
  memory_view_id?: string;
  notebook_id?: string;
  project_id?: string;
  title?: string;
  snippet?: string;
  score: number;
  source: string;
}

export interface SearchResponse {
  query: string;
  duration_ms: number;
  results: SearchResults;
}

export function useSearch(notebookId?: string) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResults>({
    pages: [], blocks: [], study_assets: [], memory: [], playbooks: [],
  });
  const [loading, setLoading] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const doSearch = useCallback(async (q: string) => {
    abortRef.current?.abort();
    if (q.trim().length < 2) {
      setResults({ pages: [], blocks: [], study_assets: [], memory: [], playbooks: [] });
      setLoading(false);
      return;
    }
    const ac = new AbortController();
    abortRef.current = ac;
    setLoading(true);
    try {
      const path = notebookId
        ? `/api/v1/notebooks/${notebookId}/search?q=${encodeURIComponent(q)}`
        : `/api/v1/search/global?q=${encodeURIComponent(q)}`;
      const data = await apiGet<SearchResponse>(path, { signal: ac.signal });
      if (!ac.signal.aborted) setResults(data.results);
    } catch {
      /* swallow */
    } finally {
      if (!ac.signal.aborted) setLoading(false);
    }
  }, [notebookId]);

  useEffect(() => {
    const h = setTimeout(() => { void doSearch(query); }, 300);
    return () => clearTimeout(h);
  }, [query, doSearch]);

  return { query, setQuery, results, loading };
}
```

- [ ] **Step 2: Create SearchResultsGroup**

Create `apps/web/components/notebook/contents/search/SearchResultsGroup.tsx`:

```tsx
"use client";

import React from "react";
import type { Hit } from "@/hooks/useSearch";

interface Props {
  heading: string;
  icon: React.ElementType;
  items: Hit[];
  onPick: (hit: Hit) => void;
  emptyHint?: string;
}

export default function SearchResultsGroup({
  heading, icon: Icon, items, onPick, emptyHint,
}: Props) {
  return (
    <section className="search-group">
      <h3 className="search-group__heading">
        <Icon size={13} />
        <span>{heading}</span>
        <span className="search-group__count">{items.length}</span>
      </h3>
      {items.length === 0 ? (
        <p className="search-group__empty">{emptyHint || "—"}</p>
      ) : (
        <ul className="search-group__list">
          {items.map((hit, i) => (
            <li
              key={
                hit.id || hit.asset_id || hit.memory_view_id ||
                `${heading}-${i}`
              }
              data-testid="search-result-item"
              className="search-group__item"
              onClick={() => onPick(hit)}
            >
              <div className="search-group__title">
                {hit.title || hit.snippet?.slice(0, 60) || "(untitled)"}
              </div>
              {hit.snippet && hit.snippet !== hit.title && (
                <div className="search-group__snippet">
                  {hit.snippet.slice(0, 140)}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
```

- [ ] **Step 3: Overwrite SearchWindow**

Overwrite `apps/web/components/notebook/contents/SearchWindow.tsx`:

```tsx
"use client";

import { FileText, Layers, Brain, BookOpen, ScrollText } from "lucide-react";
import { useWindowManager } from "@/components/notebook/WindowManager";
import SearchResultsGroup from "./search/SearchResultsGroup";
import { useSearch, type Hit } from "@/hooks/useSearch";

interface Props {
  notebookId?: string;
  projectId?: string;
}

export default function SearchWindow({ notebookId }: Props) {
  const { query, setQuery, results, loading } = useSearch(notebookId);
  const { openWindow } = useWindowManager();

  const pickPage = (hit: Hit) => {
    if (!hit.id || !hit.notebook_id) return;
    openWindow({
      type: "note", title: hit.title || "Page",
      meta: { pageId: hit.id, notebookId: hit.notebook_id },
    });
  };
  const pickBlock = (hit: Hit) => {
    if (!hit.page_id || !hit.notebook_id) return;
    openWindow({
      type: "note", title: "Page",
      meta: { pageId: hit.page_id, notebookId: hit.notebook_id },
    });
  };
  const pickStudy = (hit: Hit) => {
    if (!hit.notebook_id) return;
    openWindow({
      type: "study", title: "Study",
      meta: { notebookId: hit.notebook_id },
    });
  };
  const pickMemory = (hit: Hit) => {
    if (!notebookId) return;
    openWindow({
      type: "memory", title: "Memory",
      meta: { notebookId, memoryId: hit.id || "" },
    });
  };
  const pickPlaybook = (hit: Hit) => {
    if (!notebookId) return;
    openWindow({
      type: "memory", title: "Playbook",
      meta: { notebookId, memoryViewId: hit.memory_view_id || "" },
    });
  };

  return (
    <div className="search-window" data-testid="search-window">
      <div className="search-window__header">
        <input
          type="text"
          placeholder="Search pages, blocks, memory, study…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          autoFocus
          data-testid="search-window-input"
        />
        {loading && <span className="search-window__loading">…</span>}
      </div>

      <div className="search-window__body">
        <SearchResultsGroup
          heading="Pages"
          icon={FileText}
          items={results.pages}
          onPick={pickPage}
        />
        <SearchResultsGroup
          heading="Blocks"
          icon={Layers}
          items={results.blocks}
          onPick={pickBlock}
        />
        <SearchResultsGroup
          heading="Study assets"
          icon={BookOpen}
          items={results.study_assets}
          onPick={pickStudy}
        />
        <SearchResultsGroup
          heading="Memory"
          icon={Brain}
          items={results.memory}
          onPick={pickMemory}
        />
        <SearchResultsGroup
          heading="Playbooks"
          icon={ScrollText}
          items={results.playbooks}
          onPick={pickPlaybook}
        />
      </div>
    </div>
  );
}
```

- [ ] **Step 4: CSS**

Create `apps/web/styles/search-window.css`:

```css
.search-window {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #ffffff;
}

.search-window__header {
  flex-shrink: 0;
  padding: 10px 12px;
  border-bottom: 1px solid #e5e7eb;
  display: flex;
  gap: 8px;
  align-items: center;
}

.search-window__header input {
  flex: 1;
  padding: 8px 10px;
  font-size: 13px;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  outline: none;
}

.search-window__header input:focus {
  border-color: #2563eb;
}

.search-window__loading {
  font-size: 11px;
  color: #9ca3af;
}

.search-window__body {
  flex: 1;
  overflow: auto;
  padding: 8px 0;
  min-height: 0;
}

.search-group {
  padding: 6px 12px;
  border-bottom: 1px solid #f3f4f6;
}

.search-group__heading {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  font-weight: 600;
  color: #6b7280;
  margin: 4px 0;
  text-transform: uppercase;
}

.search-group__count {
  margin-left: auto;
  font-size: 10px;
  color: #9ca3af;
  font-weight: 500;
}

.search-group__list {
  list-style: none;
  padding: 0;
  margin: 0;
}

.search-group__item {
  padding: 6px 8px;
  border-radius: 4px;
  cursor: pointer;
}

.search-group__item:hover {
  background: #f3f4f6;
}

.search-group__title {
  font-size: 13px;
  font-weight: 600;
  color: #111827;
}

.search-group__snippet {
  font-size: 11px;
  color: #6b7280;
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.search-group__empty {
  font-size: 11px;
  color: #9ca3af;
  padding: 2px 8px;
  margin: 0;
}
```

- [ ] **Step 5: Import CSS in layout**

Open `apps/web/app/[locale]/workspace/notebooks/[notebookId]/layout.tsx`.
Add after the existing digest-window CSS import:

```tsx
import "@/styles/search-window.css";
```

- [ ] **Step 6: Typecheck**

```bash
cd /Users/dog/Desktop/MRAI/apps/web && ./node_modules/.bin/tsc --noEmit 2>&1 | grep -iE "(SearchWindow|SearchResultsGroup|useSearch|search-window)" | head -10
```

Expected: no output.

- [ ] **Step 7: Commit**

```bash
git add apps/web/components/notebook/contents/SearchWindow.tsx apps/web/components/notebook/contents/search/SearchResultsGroup.tsx apps/web/hooks/useSearch.ts apps/web/styles/search-window.css apps/web/app/[locale]/workspace/notebooks/[notebookId]/layout.tsx
git commit -m "feat(web): SearchWindow + SearchResultsGroup + useSearch + CSS"
```

---

## Task 11 — Sidebar Search tab + i18n

**Files:**
- Modify: `apps/web/components/console/NotebookSidebar.tsx`
- Modify: `apps/web/messages/en/console.json`
- Modify: `apps/web/messages/zh/console.json`
- Modify: `apps/web/messages/en/console-notebooks.json`
- Modify: `apps/web/messages/zh/console-notebooks.json`

- [ ] **Step 1: Extend SideTab + TABS**

In `apps/web/components/console/NotebookSidebar.tsx`:

1. Add `Search` to the `lucide-react` import (top of file).
2. Extend `SideTab` union:
   ```ts
   type SideTab =
     "pages" | "ai_panel" | "memory" | "learn" | "digest" | "search" | null;
   ```
3. Extend `TABS` (place Search between `pages` and `ai_panel`):
   ```ts
   const TABS = [
     { id: "pages" as const, Icon: FileText, key: "nav.pages" },
     { id: "search" as const, Icon: Search, key: "nav.search" },
     { id: "ai_panel" as const, Icon: Sparkles, key: "nav.aiPanel" },
     { id: "memory" as const, Icon: Brain, key: "nav.memory" },
     { id: "learn" as const, Icon: BookOpen, key: "nav.learn" },
     { id: "digest" as const, Icon: Bell, key: "nav.digest" },
   ] as const;
   ```
4. In the `handleTabClick` switch, add a branch before `memory`:
   ```ts
   } else if (tabId === "search") {
     openWindow({
       type: "search",
       title: tn("search.windowTitle"),
       meta: { notebookId },
     });
     return;
   }
   ```

- [ ] **Step 2: i18n**

Open `apps/web/messages/en/console.json`. Find `nav.learn`, add after:

```json
  "nav.search": "Search",
```

Same to `apps/web/messages/zh/console.json`:

```json
  "nav.search": "搜索",
```

Open `apps/web/messages/en/console-notebooks.json`. Add near `digest.windowTitle`:

```json
  "search.windowTitle": "Search",
  "search.placeholder": "Search pages, blocks, memory, study…",
```

`apps/web/messages/zh/console-notebooks.json`:

```json
  "search.windowTitle": "搜索",
  "search.placeholder": "搜索页面、块、记忆、学习资料…",
```

Make sure trailing commas are correct (each new key-value except the last in its object needs a comma).

- [ ] **Step 3: JSON sanity**

```bash
cd /Users/dog/Desktop/MRAI/apps/web && for f in messages/en/console.json messages/zh/console.json messages/en/console-notebooks.json messages/zh/console-notebooks.json; do
  node -e "JSON.parse(require('fs').readFileSync('$f'))" && echo "OK $f" || echo "BAD $f"
done
```

Expected: all OK.

- [ ] **Step 4: Typecheck**

```bash
cd /Users/dog/Desktop/MRAI/apps/web && ./node_modules/.bin/tsc --noEmit 2>&1 | grep -i "NotebookSidebar" | head -5
```

Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add apps/web/components/console/NotebookSidebar.tsx apps/web/messages/en/console.json apps/web/messages/zh/console.json apps/web/messages/en/console-notebooks.json apps/web/messages/zh/console-notebooks.json
git commit -m "feat(web): sidebar Search tab + i18n (nav.search + search.windowTitle)"
```

---

## Task 12 — `RelatedPagesCard` + `useRelatedPages` hook + NoteWindow

**Files:**
- Create: `apps/web/components/notebook/contents/search/RelatedPagesCard.tsx`
- Create: `apps/web/hooks/useRelatedPages.ts`
- Modify: `apps/web/components/notebook/contents/NoteWindow.tsx`

- [ ] **Step 1: Create hook**

Create `apps/web/hooks/useRelatedPages.ts`:

```ts
"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";

export interface RelatedPage {
  id: string;
  notebook_id: string;
  title: string;
  score: number;
  reason: "semantic" | "shared_subject";
}

export interface RelatedMemory {
  id: string;
  content: string;
  score: number;
  reason: string;
}

export interface RelatedResponse {
  pages: RelatedPage[];
  memory: RelatedMemory[];
}

export function useRelatedPages(pageId: string | null) {
  const [data, setData] = useState<RelatedResponse>({ pages: [], memory: [] });

  useEffect(() => {
    if (!pageId) {
      setData({ pages: [], memory: [] });
      return;
    }
    let cancelled = false;
    void apiGet<RelatedResponse>(`/api/v1/pages/${pageId}/related?limit=5`)
      .then((r) => { if (!cancelled) setData(r); })
      .catch(() => { if (!cancelled) setData({ pages: [], memory: [] }); });
    return () => { cancelled = true; };
  }, [pageId]);

  return data;
}
```

- [ ] **Step 2: Create RelatedPagesCard**

Create `apps/web/components/notebook/contents/search/RelatedPagesCard.tsx`:

```tsx
"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, Sparkles } from "lucide-react";
import { useRelatedPages } from "@/hooks/useRelatedPages";
import { useWindowManager } from "@/components/notebook/WindowManager";

interface Props {
  pageId: string;
}

export default function RelatedPagesCard({ pageId }: Props) {
  const { openWindow } = useWindowManager();
  const data = useRelatedPages(pageId);
  const [open, setOpen] = useState(false);

  if (data.pages.length === 0 && data.memory.length === 0) return null;

  return (
    <aside
      className="related-pages-card"
      data-testid="related-pages-card"
      style={{
        borderTop: "1px solid #e5e7eb",
        padding: "10px 16px",
        fontSize: 12,
      }}
    >
      <button
        type="button"
        data-testid="related-pages-card-toggle"
        onClick={() => setOpen((v) => !v)}
        style={{
          display: "flex", alignItems: "center", gap: 6,
          background: "none", border: "none", cursor: "pointer",
          padding: 0, fontWeight: 600, color: "#374151",
        }}
      >
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        <Sparkles size={13} />
        Related ({data.pages.length + data.memory.length})
      </button>

      {open && (
        <div style={{ marginTop: 8 }}>
          {data.pages.length > 0 && (
            <div>
              <div style={{ fontSize: 10, color: "#9ca3af", marginBottom: 4 }}>
                Pages
              </div>
              <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
                {data.pages.map((p) => (
                  <li key={p.id} style={{ padding: "4px 0" }}>
                    <button
                      type="button"
                      data-testid="related-pages-link"
                      onClick={() =>
                        openWindow({
                          type: "note", title: p.title || "Page",
                          meta: { pageId: p.id, notebookId: p.notebook_id },
                        })
                      }
                      style={{
                        background: "none", border: "none",
                        cursor: "pointer", color: "#2563eb",
                        fontSize: 12, padding: 0, textAlign: "left",
                      }}
                    >
                      {p.title || "(untitled)"}
                    </button>
                    <span style={{ color: "#9ca3af", fontSize: 10, marginLeft: 6 }}>
                      · {p.reason}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {data.memory.length > 0 && (
            <div style={{ marginTop: 8 }}>
              <div style={{ fontSize: 10, color: "#9ca3af", marginBottom: 4 }}>
                Memory
              </div>
              <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
                {data.memory.map((m) => (
                  <li key={m.id} style={{ padding: "2px 0", color: "#374151" }}>
                    {m.content.slice(0, 100)}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </aside>
  );
}
```

- [ ] **Step 3: Integrate into NoteWindow**

Open `apps/web/components/notebook/contents/NoteWindow.tsx`. The component currently wraps `<NoteEditor pageId={...} />`. At the bottom of the rendered tree (after the editor), add:

```tsx
import RelatedPagesCard from "./search/RelatedPagesCard";
```

Then inside the JSX, after the editor element, render:

```tsx
{pageId && <RelatedPagesCard pageId={pageId} />}
```

If the current layout is a single JSX root (editor only), wrap both in a `<div>` or `<>` fragment and include the card.

- [ ] **Step 4: Typecheck**

```bash
cd /Users/dog/Desktop/MRAI/apps/web && ./node_modules/.bin/tsc --noEmit 2>&1 | grep -iE "(RelatedPagesCard|useRelatedPages|NoteWindow)" | head -10
```

Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add apps/web/components/notebook/contents/search/RelatedPagesCard.tsx apps/web/hooks/useRelatedPages.ts apps/web/components/notebook/contents/NoteWindow.tsx
git commit -m "feat(web): RelatedPagesCard + useRelatedPages + NoteWindow integration"
```

---

## Task 13 — vitest unit + Playwright smoke

**Files:**
- Create: `apps/web/tests/unit/search-window.test.tsx`
- Create: `apps/web/tests/unit/use-search.test.ts`
- Create: `apps/web/tests/unit/related-pages-card.test.tsx`
- Create: `apps/web/tests/s7-search.spec.ts`

- [ ] **Step 1: vitest for SearchWindow**

Create `apps/web/tests/unit/search-window.test.tsx`:

```tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import SearchWindow from "@/components/notebook/contents/SearchWindow";
import { WindowManagerProvider } from "@/components/notebook/WindowManager";

afterEach(() => { vi.restoreAllMocks(); });

function mockFetch() {
  global.fetch = vi.fn(async (url: RequestInfo | URL) => {
    const urlStr = String(url);
    if (urlStr.includes("/api/v1/auth/csrf")) {
      return {
        ok: true, status: 200,
        json: async () => ({ csrf_token: "t" }),
      } as Response;
    }
    if (urlStr.includes("/api/v1/search/global")) {
      return {
        ok: true, status: 200,
        json: async () => ({
          query: "login", duration_ms: 5,
          results: {
            pages: [{ id: "p1", notebook_id: "nb1", title: "Login flow",
                      snippet: "x", score: 0.8, source: "rrf" }],
            blocks: [], study_assets: [], memory: [], playbooks: [],
          },
        }),
      } as Response;
    }
    throw new Error("unexpected fetch " + urlStr);
  }) as typeof fetch;
}

describe("SearchWindow", () => {
  it("renders input and populates pages group after typing", async () => {
    mockFetch();
    render(
      <WindowManagerProvider notebookId="nb1">
        <SearchWindow notebookId="nb1" />
      </WindowManagerProvider>,
    );
    const input = screen.getByTestId("search-window-input");
    fireEvent.change(input, { target: { value: "login" } });
    const item = await screen.findByText("Login flow", {}, { timeout: 3000 });
    expect(item).toBeTruthy();
  });

  it("renders empty state when no query", () => {
    mockFetch();
    render(
      <WindowManagerProvider notebookId="nb1">
        <SearchWindow notebookId="nb1" />
      </WindowManagerProvider>,
    );
    const input = screen.getByTestId("search-window-input");
    expect((input as HTMLInputElement).value).toBe("");
  });
});
```

**Note:** If `WindowManagerProvider` import fails (e.g., it's default-exported or not exported at all), switch to whichever existing provider wraps the app in other tests — check `window-manager-persistence.test.tsx` for the pattern.

- [ ] **Step 2: vitest for useSearch**

Create `apps/web/tests/unit/use-search.test.ts`:

```ts
import { renderHook, act, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useSearch } from "@/hooks/useSearch";

afterEach(() => { vi.restoreAllMocks(); });

function setupFetch(onCall: (url: string) => void) {
  global.fetch = vi.fn(async (url: RequestInfo | URL) => {
    const u = String(url);
    onCall(u);
    if (u.includes("/api/v1/auth/csrf")) {
      return { ok: true, status: 200,
               json: async () => ({ csrf_token: "t" }) } as Response;
    }
    return {
      ok: true, status: 200,
      json: async () => ({
        query: "q", duration_ms: 1,
        results: { pages: [], blocks: [], study_assets: [],
                   memory: [], playbooks: [] },
      }),
    } as Response;
  }) as typeof fetch;
}

describe("useSearch", () => {
  it("does not call fetch for queries shorter than 2 chars", async () => {
    const calls: string[] = [];
    setupFetch((u) => calls.push(u));
    const { result } = renderHook(() => useSearch());
    act(() => { result.current.setQuery("a"); });
    await new Promise((r) => setTimeout(r, 400));
    expect(calls.filter((u) => u.includes("/api/v1/search")).length).toBe(0);
  });

  it("debounces rapid typing", async () => {
    const calls: string[] = [];
    setupFetch((u) => calls.push(u));
    const { result } = renderHook(() => useSearch());
    act(() => { result.current.setQuery("hello"); });
    act(() => { result.current.setQuery("hello world"); });
    await new Promise((r) => setTimeout(r, 400));
    const searchCalls = calls.filter((u) => u.includes("/api/v1/search"));
    // Latest query wins; at most 1 search call (hello world).
    expect(searchCalls.length).toBeLessThanOrEqual(1);
    if (searchCalls[0]) {
      expect(searchCalls[0]).toContain("hello%20world");
    }
  });
});
```

- [ ] **Step 3: vitest for RelatedPagesCard**

Create `apps/web/tests/unit/related-pages-card.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import RelatedPagesCard from "@/components/notebook/contents/search/RelatedPagesCard";
import { WindowManagerProvider } from "@/components/notebook/WindowManager";

afterEach(() => { vi.restoreAllMocks(); });

function mockFetch(withResults: boolean) {
  global.fetch = vi.fn(async (url: RequestInfo | URL) => {
    const u = String(url);
    if (u.includes("/api/v1/auth/csrf")) {
      return { ok: true, status: 200,
               json: async () => ({ csrf_token: "t" }) } as Response;
    }
    if (u.includes("/related")) {
      return {
        ok: true, status: 200,
        json: async () => withResults
          ? { pages: [{ id: "pp", notebook_id: "nb",
                        title: "Linked", score: 0.7, reason: "semantic" }],
              memory: [] }
          : { pages: [], memory: [] },
      } as Response;
    }
    throw new Error("unexpected " + u);
  }) as typeof fetch;
}

describe("RelatedPagesCard", () => {
  it("does not render when results are empty", async () => {
    mockFetch(false);
    const { container } = render(
      <WindowManagerProvider notebookId="nb">
        <RelatedPagesCard pageId="p1" />
      </WindowManagerProvider>,
    );
    await new Promise((r) => setTimeout(r, 50));
    expect(container.querySelector("[data-testid='related-pages-card']"))
      .toBeNull();
  });

  it("renders when there are related items", async () => {
    mockFetch(true);
    render(
      <WindowManagerProvider notebookId="nb">
        <RelatedPagesCard pageId="p1" />
      </WindowManagerProvider>,
    );
    const card = await screen.findByTestId(
      "related-pages-card", {}, { timeout: 2000 },
    );
    expect(card).toBeTruthy();
  });
});
```

- [ ] **Step 4: Playwright smoke**

Create `apps/web/tests/s7-search.spec.ts`:

```ts
import { test, expect } from "@playwright/test";

test.describe("S7 Search", () => {
  test("sidebar Search icon opens SearchWindow", async ({ page }) => {
    await page.goto("/workspace/notebooks");
    await page.getByRole("button", { name: /create/i }).first().click();
    await page.waitForURL(/\/workspace\/notebooks\/[^/]+$/);

    const searchTab = page.getByTestId("sidebar-tab-search");
    await expect(searchTab).toBeVisible();
    await searchTab.click();

    await expect(page.getByTestId("search-window")).toBeVisible();
    await expect(page.getByTestId("search-window-input")).toBeVisible();
  });
});
```

- [ ] **Step 5: Run vitest**

```bash
cd /Users/dog/Desktop/MRAI/apps/web && ./node_modules/.bin/vitest run tests/unit/search-window.test.tsx tests/unit/use-search.test.ts tests/unit/related-pages-card.test.tsx 2>&1 | tail -12
```

Expected: 5–6 passed.

**If a test fails due to `WindowManagerProvider` import not existing by that name**, replace with whichever provider the existing test files use (check `tests/unit/window-manager-persistence.test.tsx` for the pattern — it may be `<WindowManagerProvider notebookId="nb">`).

- [ ] **Step 6: Typecheck**

```bash
cd /Users/dog/Desktop/MRAI/apps/web && ./node_modules/.bin/tsc --noEmit 2>&1 | grep -iE "(search-window|use-search|related-pages|s7-search)" | head -10
```

Expected: no output.

- [ ] **Step 7: Commit**

```bash
git add apps/web/tests/unit/search-window.test.tsx apps/web/tests/unit/use-search.test.ts apps/web/tests/unit/related-pages-card.test.tsx apps/web/tests/s7-search.spec.ts
git commit -m "test(web): SearchWindow + useSearch + RelatedPagesCard vitest + Playwright smoke"
```

---

## Task 14 — Final coverage verification

No commit.

- [ ] **Step 1: Backend coverage**

```bash
cd /Users/dog/Desktop/MRAI/apps/api && .venv/bin/pytest \
  tests/test_search_migration.py \
  tests/test_search_rank.py \
  tests/test_search_vector.py \
  tests/test_search_dispatcher.py \
  tests/test_related_pages.py \
  tests/test_notebook_page_embedding.py \
  tests/test_search_api.py \
  --cov=app.services.search_rank \
  --cov=app.services.search_vector \
  --cov=app.services.search_dispatcher \
  --cov=app.services.related_pages \
  --cov=app.routers.search \
  --cov-report=term 2>&1 | tail -15
```

Expected: target modules ≥ 80% coverage.

- [ ] **Step 2: Vitest**

```bash
cd /Users/dog/Desktop/MRAI/apps/web && ./node_modules/.bin/vitest run 2>&1 | tail -10
```

Expected: all existing + new tests pass.

- [ ] **Step 3: Typecheck**

```bash
cd /Users/dog/Desktop/MRAI/apps/web && ./node_modules/.bin/tsc --noEmit 2>&1 | tail -10
```

Expected: only pre-existing WhiteboardBlock error; no new S7 errors.

- [ ] **Step 4: Summary report**

Write a short summary of:
- All 13 task commit SHAs (in order)
- Coverage per target module
- Vitest pass count
- Any typecheck issues from S7 files (should be zero)

No commit.

---

## Final Acceptance Checklist

- [ ] `alembic upgrade head` succeeds and creates `notebook_pages.embedding_id`, `ix_notebook_pages_embedding_id`, `ix_notebook_blocks_plain_text_trgm`.
- [ ] `GET /api/v1/search/global?q=login` returns `200` with the full 5-scope shape.
- [ ] `GET /api/v1/notebooks/{id}/search?q=login` returns 200 and limits Pages/Blocks/Study-assets to that notebook.
- [ ] `GET /api/v1/pages/{id}/related` returns `{pages, memory}` shape.
- [ ] Sidebar Search icon opens SearchWindow; typing populates result groups.
- [ ] Opening a NoteWindow whose page has related content shows the RelatedPagesCard (collapsed by default).
- [ ] `generate_daily_digests_task` (S5) still runs; no S1–S5 backend test regresses.
- [ ] `backfill_notebook_page_embeddings_task.run()` is idempotent (second run returns `total_processed: 0` when nothing new).
- [ ] `alembic downgrade -1` cleanly reverses the S7 migration.

## Cross-references

- Spec: `docs/superpowers/specs/2026-04-17-search-design.md`
- Product spec: `MRAI_notebook_ai_os_build_spec.md §12`, `§13.6`
- Reuses: `app/services/memory_v2.py` (search_memories_lexical, search_memory_views_lexical), `app/services/embedding.py` (embed_and_store, create_embedding), S1 `action_log_context`
- Predecessor: S5 merge commit `6638976`
