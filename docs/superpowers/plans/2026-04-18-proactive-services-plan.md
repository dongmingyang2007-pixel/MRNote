# S5 — Proactive Services — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship 4 kinds of proactive digests (`daily_digest`,
`weekly_reflection`, `deviation_reminder`, `relationship_reminder`)
behind two Celery beat entries that fan-out per active project, with
a new `digest` WindowType and sidebar Bell-with-badge UI for reading
them.

**Architecture:** Single `proactive_digests` table with a `kind`
discriminator. Per-period idempotency via
`UNIQUE(project_id, kind, period_start)`. Pure-function collectors
(`services/proactive_materials.py`) gather source material from S1
AIActionLog / NotebookPage / S4 StudyCard / Memory V3. The generator
(`services/proactive_generator.py`) turns materials into LLM prompts
and parses the returned JSON into `content_json`. A per-project
generator task (`generate_proactive_digest_task`) wraps the work in
S1 `action_log_context("proactive.{kind}")`.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2, Alembic, Celery,
pytest + pytest-cov, Next.js 14, React 18, TypeScript, vitest,
Playwright.

**Spec:** `docs/superpowers/specs/2026-04-18-proactive-services-design.md`

---

## Phase Overview

| Phase | Tasks | Description |
|---|---|---|
| **A** | 1 | `ProactiveDigest` model + Pydantic schemas + Alembic + ORM smoke |
| **B** | 2 | `find_reconfirm_candidates` extraction + regression |
| **C** | 3 | `proactive_materials.py` collectors + 8 unit tests |
| **D** | 4 | `proactive_generator.py` prompts/dispatch + 4 unit tests |
| **E** | 5 | Per-project generator Celery task + 3 tests |
| **F** | 6 | 4 fan-out Celery tasks + beat schedule + 5 tests |
| **G** | 7 | 6 API endpoints + 7 tests + router registration |
| **H** | 8 | Final backend regression verification |
| **I** | 9 | WindowType `digest` plumbing (WindowManager / Window / MinimizedTray / WindowCanvas) |
| **J** | 10–11 | `DigestWindow` + `DigestList` + `DigestDetail` components + CSS |
| **K** | 12 | Sidebar Bell tab + `useDigestUnreadCount` hook |
| **L** | 13 | Playwright smoke + vitest unit |
| **M** | 14 | Final coverage verification |

---

### Task 1: `ProactiveDigest` model + Pydantic schemas + migration

**Files:**
- Modify: `apps/api/app/models/entities.py`
- Modify: `apps/api/app/models/__init__.py`
- Create: `apps/api/alembic/versions/202604190001_proactive_digests.py`
- Create: `apps/api/app/schemas/proactive.py`
- Create: `apps/api/tests/test_proactive_models.py`

- [ ] **Step 1: Write the failing test**

Create `apps/api/tests/test_proactive_models.py`:

```python
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


def test_unique_constraint_project_kind_period_start() -> None:
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
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && .venv/bin/pytest tests/test_proactive_models.py -v`
Expected: FAIL — `ImportError: cannot import name 'ProactiveDigest'`.

- [ ] **Step 3: Add the ORM class**

Open `apps/api/app/models/entities.py`. After the last existing
class (`StudyCard` from S4 — should be near the bottom), append:

```python
class ProactiveDigest(
    Base, UUIDPrimaryKeyMixin, TimestampMixin, UpdatedAtMixin,
):
    __tablename__ = "proactive_digests"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "kind", "period_start",
            name="uq_proactive_digests_project_kind_period_start",
        ),
    )

    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )

    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    period_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    title: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    content_markdown: Mapped[str] = mapped_column(Text, default="", nullable=False)
    content_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )

    status: Mapped[str] = mapped_column(
        String(20), default="unread", nullable=False
    )
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    dismissed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    model_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    action_log_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
```

If the top-of-file imports don't already include `UniqueConstraint`,
add it to the `from sqlalchemy import (...)` block. Verify the
existing imports cover `DateTime`, `ForeignKey`, `Integer`, `JSON`,
`String`, `Text`, `Index`, `Mapped`, `mapped_column`.

At the bottom of the file, alongside the other `Index(...)` calls,
add:

```python
Index(
    "ix_proactive_digests_user_status_created",
    ProactiveDigest.user_id,
    ProactiveDigest.status,
    ProactiveDigest.created_at.desc(),
)
Index(
    "ix_proactive_digests_project_kind_period",
    ProactiveDigest.project_id,
    ProactiveDigest.kind,
    ProactiveDigest.period_start.desc(),
)
```

- [ ] **Step 4: Export from `app.models`**

Open `apps/api/app/models/__init__.py`. Add `ProactiveDigest` to
both the `from app.models.entities import (...)` block (alphabetical,
before `Project`) and the `__all__` list.

- [ ] **Step 5: Create the Alembic migration**

Create `apps/api/alembic/versions/202604190001_proactive_digests.py`:

```python
"""proactive_digests table (S5)

Revision ID: 202604190001
Revises: 202604180001
Create Date: 2026-04-19
"""

from alembic import op


revision = "202604190001"
down_revision = "202604180001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS proactive_digests (
            id                VARCHAR(36) PRIMARY KEY,
            workspace_id      VARCHAR(36) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            project_id        VARCHAR(36) NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            user_id           VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            kind              VARCHAR(32) NOT NULL,
            period_start      TIMESTAMPTZ NOT NULL,
            period_end        TIMESTAMPTZ NOT NULL,
            title             VARCHAR(200) NOT NULL DEFAULT '',
            content_markdown  TEXT NOT NULL DEFAULT '',
            content_json      JSONB NOT NULL DEFAULT '{}'::jsonb,
            status            VARCHAR(20) NOT NULL DEFAULT 'unread',
            read_at           TIMESTAMPTZ,
            dismissed_at      TIMESTAMPTZ,
            model_id          VARCHAR(100),
            action_log_id     VARCHAR(36),
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_proactive_digests_project_kind_period_start
                UNIQUE (project_id, kind, period_start)
        );

        CREATE INDEX IF NOT EXISTS ix_proactive_digests_workspace_id
            ON proactive_digests(workspace_id);
        CREATE INDEX IF NOT EXISTS ix_proactive_digests_project_id
            ON proactive_digests(project_id);
        CREATE INDEX IF NOT EXISTS ix_proactive_digests_user_status_created
            ON proactive_digests(user_id, status, created_at DESC);
        CREATE INDEX IF NOT EXISTS ix_proactive_digests_project_kind_period
            ON proactive_digests(project_id, kind, period_start DESC);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS proactive_digests CASCADE;")
```

- [ ] **Step 6: Create Pydantic schemas**

Create `apps/api/app/schemas/proactive.py`:

```python
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class DigestListItem(BaseModel):
    id: str
    kind: str
    title: str
    period_start: datetime
    period_end: datetime
    status: str
    created_at: datetime


class PaginatedDigests(BaseModel):
    items: list[DigestListItem]
    next_cursor: str | None
    unread_count: int


class DigestDetail(BaseModel):
    id: str
    workspace_id: str
    project_id: str
    user_id: str
    kind: str
    title: str
    period_start: datetime
    period_end: datetime
    content_markdown: str
    content_json: dict[str, Any]
    status: str
    read_at: datetime | None
    dismissed_at: datetime | None
    model_id: str | None
    action_log_id: str | None
    created_at: datetime
    updated_at: datetime


class GenerateNowRequest(BaseModel):
    kind: str = Field(..., pattern=r"^(daily_digest|weekly_reflection|deviation_reminder|relationship_reminder)$")
    project_id: str


class AckResponse(BaseModel):
    ok: bool = True
```

- [ ] **Step 7: Run to verify pass**

Run: `cd apps/api && .venv/bin/pytest tests/test_proactive_models.py -v`
Expected: 2 PASSED.

- [ ] **Step 8: Commit**

```bash
git add apps/api/app/models/entities.py apps/api/app/models/__init__.py apps/api/alembic/versions/202604190001_proactive_digests.py apps/api/app/schemas/proactive.py apps/api/tests/test_proactive_models.py
git commit -m "feat(api): ProactiveDigest model + schemas + migration for S5"
```

---

### Task 2: Extract `find_reconfirm_candidates` from `memory_v2.py`

**Files:**
- Modify: `apps/api/app/services/memory_v2.py`
- Create: `apps/api/tests/test_reconfirm_candidates.py`

- [ ] **Step 1: Write the failing test**

Create `apps/api/tests/test_reconfirm_candidates.py`:

```python
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


def _seed_project() -> str:
    with SessionLocal() as db:
        ws = Workspace(name="W"); user = User(email="u@x.co", password_hash="x")
        db.add(ws); db.add(user); db.commit(); db.refresh(ws); db.refresh(user)
        pr = Project(workspace_id=ws.id, name="P")
        db.add(pr); db.commit(); db.refresh(pr)
        return pr.id


def test_returns_memories_with_past_reconfirm_after() -> None:
    project_id = _seed_project()
    now = datetime.now(timezone.utc)
    past = (now - timedelta(days=5)).isoformat()
    with SessionLocal() as db:
        m = Memory(
            project_id=project_id,
            content="old fact",
            importance=0.5,
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
    project_id = _seed_project()
    now = datetime.now(timezone.utc)
    past = (now - timedelta(days=5)).isoformat()
    with SessionLocal() as db:
        m = Memory(
            project_id=project_id,
            content="old fact",
            importance=0.5,
            node_status="active",
            metadata_json={"reconfirm_after": past},
        )
        db.add(m); db.commit()

        candidates = find_reconfirm_candidates(db, project_id=project_id, now=now)
    assert candidates == []


def test_respects_limit() -> None:
    project_id = _seed_project()
    now = datetime.now(timezone.utc)
    past = (now - timedelta(days=5)).isoformat()
    with SessionLocal() as db:
        for i in range(7):
            db.add(Memory(
                project_id=project_id,
                content=f"old fact {i}",
                importance=0.5,
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
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && .venv/bin/pytest tests/test_reconfirm_candidates.py -v`
Expected: FAIL — `ImportError: cannot import name 'find_reconfirm_candidates'`.

- [ ] **Step 3: Add the helper to `memory_v2.py`**

Open `apps/api/app/services/memory_v2.py`. Near the top of the file,
after the existing imports and constants, add:

```python
def find_reconfirm_candidates(
    db: Session,
    *,
    project_id: str,
    limit: int = 5,
    now: datetime | None = None,
) -> list[Memory]:
    """Return the oldest memories that currently need reconfirmation.

    A memory needs reconfirmation when its metadata has
    ``single_source_explicit == True`` and its ``reconfirm_after``
    timestamp is in the past (or absent). Callers pass ``now`` so
    the result is deterministic in tests.
    """
    resolved_now = now or datetime.now(timezone.utc)
    rows = (
        db.query(Memory)
        .filter(Memory.project_id == project_id)
        .filter(Memory.node_status == "active")
        .order_by(Memory.created_at.asc())
        .all()
    )
    out: list[Memory] = []
    for memory in rows:
        metadata = memory.metadata_json or {}
        if not bool(metadata.get("single_source_explicit")):
            continue
        reconfirm_after_raw = str(metadata.get("reconfirm_after") or "").strip()
        if reconfirm_after_raw:
            try:
                when = datetime.fromisoformat(
                    reconfirm_after_raw.replace("Z", "+00:00")
                )
            except ValueError:
                when = resolved_now  # treat bad data as due
            if when > resolved_now:
                continue
        out.append(memory)
        if len(out) >= limit:
            break
    return out
```

Ensure `datetime`, `timezone`, and `Session` are already imported
at the top of the file; if any are missing, add them (this file
already uses `datetime`).

- [ ] **Step 4: Run to verify pass**

Run: `cd apps/api && .venv/bin/pytest tests/test_reconfirm_candidates.py -v`
Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/services/memory_v2.py apps/api/tests/test_reconfirm_candidates.py
git commit -m "feat(api): find_reconfirm_candidates helper (extracted from memory_v2)"
```

---

### Task 3: `proactive_materials.py` with 4 collectors + 8 tests

**Files:**
- Create: `apps/api/app/services/proactive_materials.py`
- Create: `apps/api/tests/test_proactive_materials.py`

- [ ] **Step 1: Write failing tests**

Create `apps/api/tests/test_proactive_materials.py`:

```python
# ruff: noqa: E402
import atexit, importlib, os, shutil, tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-s5-materials-"))
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
    AIActionLog, Memory, MemoryEvidence, Notebook, NotebookPage, Project,
    StudyCard, StudyDeck, User, Workspace,
)
from app.services.proactive_materials import (
    collect_daily_materials,
    collect_goal_materials,
    collect_relationship_materials,
    collect_weekly_materials,
)


def setup_function() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _seed_base() -> tuple[str, str, str, str]:
    """Returns (workspace_id, user_id, project_id, notebook_id)."""
    with SessionLocal() as db:
        ws = Workspace(name="W"); user = User(email="u@x.co", password_hash="x")
        db.add(ws); db.add(user); db.commit(); db.refresh(ws); db.refresh(user)
        pr = Project(workspace_id=ws.id, name="P")
        db.add(pr); db.commit(); db.refresh(pr)
        nb = Notebook(workspace_id=ws.id, project_id=pr.id,
                      created_by=user.id, title="NB", slug="nb")
        db.add(nb); db.commit(); db.refresh(nb)
        return ws.id, user.id, pr.id, nb.id


def test_collect_daily_materials_with_activity() -> None:
    ws_id, user_id, project_id, notebook_id = _seed_base()
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        for i in range(3):
            db.add(AIActionLog(
                workspace_id=ws_id, user_id=user_id, notebook_id=notebook_id,
                action_type="selection.rewrite", scope="selection",
                status="completed", output_summary=f"out {i}",
                trace_metadata={},
                created_at=now - timedelta(hours=i),
            ))
        page = NotebookPage(notebook_id=notebook_id, created_by=user_id,
                            title="T", slug="t", plain_text="x",
                            last_edited_at=now - timedelta(hours=2))
        db.add(page); db.commit()

        mats = collect_daily_materials(
            db,
            project_id=project_id,
            period_start=now - timedelta(hours=24),
            period_end=now,
        )
    assert mats["action_counts"]["selection.rewrite"] == 3
    assert len(mats["action_samples"]) == 3
    assert len(mats["page_edits"]) == 1


def test_collect_daily_materials_empty_project_returns_empty() -> None:
    ws_id, user_id, project_id, notebook_id = _seed_base()
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        mats = collect_daily_materials(
            db, project_id=project_id,
            period_start=now - timedelta(hours=24), period_end=now,
        )
    assert mats["action_counts"] == {}
    assert mats["action_samples"] == []
    assert mats["page_edits"] == []


def test_collect_weekly_materials_includes_study_stats() -> None:
    ws_id, user_id, project_id, notebook_id = _seed_base()
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        deck = StudyDeck(notebook_id=notebook_id, name="D", created_by=user_id)
        db.add(deck); db.commit(); db.refresh(deck)
        for i in range(4):
            db.add(StudyCard(
                deck_id=deck.id, front=f"Q{i}", back=f"A{i}",
                review_count=i + 1,
                lapse_count=1 if i == 0 else 0,
            ))
        db.commit()

        mats = collect_weekly_materials(
            db, project_id=project_id,
            period_start=now - timedelta(days=7), period_end=now,
        )
    assert mats["study_stats"]["cards_reviewed"] >= 4 * (4 + 1) // 2  # sum of review_count 1..4 = 10
    assert mats["study_stats"]["lapse_count"] == 1


def test_collect_weekly_materials_blocker_tasks_empty_when_no_reopen() -> None:
    ws_id, user_id, project_id, notebook_id = _seed_base()
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        mats = collect_weekly_materials(
            db, project_id=project_id,
            period_start=now - timedelta(days=7), period_end=now,
        )
    assert mats["blocker_tasks"] == []


def test_collect_goal_materials_finds_goal_kind_memory() -> None:
    ws_id, user_id, project_id, notebook_id = _seed_base()
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        g = Memory(
            project_id=project_id,
            content="Ship MVP by end of month",
            importance=0.8,
            node_status="active",
            metadata_json={"memory_kind": "goal"},
        )
        db.add(g); db.commit()

        mats = collect_goal_materials(
            db, project_id=project_id,
            period_start=now - timedelta(days=7), period_end=now,
        )
    assert len(mats["goals"]) == 1
    assert mats["goals"][0]["content"].startswith("Ship MVP")


def test_collect_goal_materials_caps_at_ten() -> None:
    ws_id, user_id, project_id, notebook_id = _seed_base()
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        for i in range(15):
            db.add(Memory(
                project_id=project_id,
                content=f"goal {i}",
                importance=0.5,
                node_status="active",
                metadata_json={"memory_kind": "goal"},
            ))
        db.commit()

        mats = collect_goal_materials(
            db, project_id=project_id,
            period_start=now - timedelta(days=7), period_end=now,
        )
    assert len(mats["goals"]) == 10


def test_collect_relationship_materials_flags_stale_person() -> None:
    ws_id, user_id, project_id, notebook_id = _seed_base()
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=45)
    with SessionLocal() as db:
        m = Memory(
            project_id=project_id,
            content="张三",
            importance=0.6,
            node_status="active",
            metadata_json={"subject_kind": "person"},
        )
        db.add(m); db.commit(); db.refresh(m)
        db.add(MemoryEvidence(
            memory_id=m.id, kind="fact", strength=0.5, content="mentioned",
            created_at=old,
        ))
        db.commit()

        items = collect_relationship_materials(db, project_id=project_id, now=now)
    assert len(items) == 1
    assert items[0]["memory_id"] == m.id
    assert items[0]["days_since"] >= 44


def test_collect_relationship_materials_skips_fresh_person() -> None:
    ws_id, user_id, project_id, notebook_id = _seed_base()
    now = datetime.now(timezone.utc)
    fresh = now - timedelta(days=5)
    with SessionLocal() as db:
        m = Memory(
            project_id=project_id,
            content="张三",
            importance=0.6,
            node_status="active",
            metadata_json={"subject_kind": "person"},
        )
        db.add(m); db.commit(); db.refresh(m)
        db.add(MemoryEvidence(
            memory_id=m.id, kind="fact", strength=0.5, content="recent",
            created_at=fresh,
        ))
        db.commit()

        items = collect_relationship_materials(db, project_id=project_id, now=now)
    assert items == []
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && .venv/bin/pytest tests/test_proactive_materials.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Create the module**

Create `apps/api/app/services/proactive_materials.py`:

```python
"""S5 proactive services: pure source-material collectors.

None of these functions call an LLM — they only aggregate SQL data
into dicts that the prompt-builder / rule engine downstream can
consume. Keeping them pure makes the 8 unit tests trivial.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    AIActionLog, Memory, MemoryEvidence, Notebook, NotebookPage,
    StudyCard, StudyDeck,
)
from app.services.memory_metadata import get_memory_kind, get_subject_kind
from app.services.memory_v2 import find_reconfirm_candidates


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _project_notebook_ids(db: Session, project_id: str) -> list[str]:
    rows = db.query(Notebook.id).filter(Notebook.project_id == project_id).all()
    return [r[0] for r in rows]


def _summarize_action_logs(
    db: Session, *, notebook_ids: list[str],
    period_start: datetime, period_end: datetime, sample_limit: int = 5,
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    if not notebook_ids:
        return {}, []
    counts_rows = (
        db.query(AIActionLog.action_type, func.count(AIActionLog.id))
        .filter(AIActionLog.notebook_id.in_(notebook_ids))
        .filter(AIActionLog.created_at >= period_start)
        .filter(AIActionLog.created_at <= period_end)
        .group_by(AIActionLog.action_type)
        .all()
    )
    counts = {action_type: int(n) for action_type, n in counts_rows}

    sample_rows = (
        db.query(AIActionLog)
        .filter(AIActionLog.notebook_id.in_(notebook_ids))
        .filter(AIActionLog.created_at >= period_start)
        .filter(AIActionLog.created_at <= period_end)
        .order_by(AIActionLog.created_at.desc())
        .limit(sample_limit)
        .all()
    )
    samples = [
        {
            "action_log_id": r.id,
            "action_type": r.action_type,
            "output_summary": (r.output_summary or "")[:200],
            "created_at": r.created_at.isoformat(),
        }
        for r in sample_rows
    ]
    return counts, samples


def _page_edits(
    db: Session, *, notebook_ids: list[str],
    period_start: datetime, period_end: datetime, limit: int = 10,
) -> list[dict[str, Any]]:
    if not notebook_ids:
        return []
    rows = (
        db.query(NotebookPage)
        .filter(NotebookPage.notebook_id.in_(notebook_ids))
        .filter(NotebookPage.last_edited_at >= period_start)
        .filter(NotebookPage.last_edited_at <= period_end)
        .order_by(NotebookPage.last_edited_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "page_id": p.id,
            "title": p.title or "(untitled)",
            "last_edited_at": p.last_edited_at.isoformat() if p.last_edited_at else None,
        }
        for p in rows
    ]


# ---------------------------------------------------------------------------
# Collectors
# ---------------------------------------------------------------------------


def collect_daily_materials(
    db: Session,
    *,
    project_id: str,
    period_start: datetime,
    period_end: datetime,
) -> dict[str, Any]:
    notebook_ids = _project_notebook_ids(db, project_id)
    action_counts, action_samples = _summarize_action_logs(
        db, notebook_ids=notebook_ids,
        period_start=period_start, period_end=period_end,
    )
    page_edits = _page_edits(
        db, notebook_ids=notebook_ids,
        period_start=period_start, period_end=period_end,
    )
    reconfirm_memories = find_reconfirm_candidates(
        db, project_id=project_id, limit=5, now=period_end,
    )
    reconfirm_items = [
        {
            "memory_id": m.id,
            "fact": m.content[:200],
            "age_days": max(0, (period_end - m.created_at).days),
            "reason": "stale",
        }
        for m in reconfirm_memories
    ]
    return {
        "action_counts": action_counts,
        "action_samples": action_samples,
        "page_edits": page_edits,
        "reconfirm_items": reconfirm_items,
    }


def collect_weekly_materials(
    db: Session,
    *,
    project_id: str,
    period_start: datetime,
    period_end: datetime,
) -> dict[str, Any]:
    notebook_ids = _project_notebook_ids(db, project_id)
    action_counts, action_samples = _summarize_action_logs(
        db, notebook_ids=notebook_ids,
        period_start=period_start, period_end=period_end,
        sample_limit=10,
    )
    page_edits = _page_edits(
        db, notebook_ids=notebook_ids,
        period_start=period_start, period_end=period_end,
        limit=20,
    )

    # StudyCard aggregates over decks whose notebook is in the project
    deck_ids = [d[0] for d in (
        db.query(StudyDeck.id)
        .filter(StudyDeck.notebook_id.in_(notebook_ids) if notebook_ids else False)
        .all()
    )]
    if deck_ids:
        cards = (
            db.query(StudyCard)
            .filter(StudyCard.deck_id.in_(deck_ids))
            .all()
        )
        cards_reviewed = sum(c.review_count for c in cards)
        lapse_count = sum(c.lapse_count for c in cards)
        confusions_logged = sum(
            1 for c in cards if c.confusion_memory_written_at is not None
        )
    else:
        cards_reviewed = 0
        lapse_count = 0
        confusions_logged = 0

    # Blocker tasks: action_type=="task.reopen" in window
    blocker_rows = []
    if notebook_ids:
        blocker_rows = (
            db.query(AIActionLog)
            .filter(AIActionLog.notebook_id.in_(notebook_ids))
            .filter(AIActionLog.action_type == "task.reopen")
            .filter(AIActionLog.created_at >= period_start)
            .filter(AIActionLog.created_at <= period_end)
            .order_by(AIActionLog.created_at.desc())
            .limit(10)
            .all()
        )
    blocker_tasks = [
        {"action_log_id": r.id, "block_id": r.block_id,
         "created_at": r.created_at.isoformat()}
        for r in blocker_rows
    ]

    return {
        "action_counts": action_counts,
        "action_samples": action_samples,
        "page_edits": page_edits,
        "study_stats": {
            "cards_reviewed": cards_reviewed,
            "lapse_count": lapse_count,
            "confusions_logged": confusions_logged,
        },
        "blocker_tasks": blocker_tasks,
    }


def collect_goal_materials(
    db: Session,
    *,
    project_id: str,
    period_start: datetime,
    period_end: datetime,
) -> dict[str, Any]:
    memories = (
        db.query(Memory)
        .filter(Memory.project_id == project_id)
        .filter(Memory.node_status == "active")
        .all()
    )
    goals = [m for m in memories if get_memory_kind(m) == "goal"][:10]
    goal_payload = [
        {
            "memory_id": g.id,
            "content": g.content,
            "importance": float(g.importance or 0.0),
        }
        for g in goals
    ]

    notebook_ids = _project_notebook_ids(db, project_id)
    _, action_samples = _summarize_action_logs(
        db, notebook_ids=notebook_ids,
        period_start=period_start, period_end=period_end,
        sample_limit=15,
    )
    page_edits = _page_edits(
        db, notebook_ids=notebook_ids,
        period_start=period_start, period_end=period_end,
        limit=10,
    )
    activity_blurbs = [
        s["output_summary"] for s in action_samples if s["output_summary"]
    ]
    activity_blurbs += [p["title"] for p in page_edits]
    activity_summary = " · ".join(activity_blurbs)[:500]

    return {
        "goals": goal_payload,
        "activity_summary": activity_summary,
    }


def collect_relationship_materials(
    db: Session,
    *,
    project_id: str,
    now: datetime | None = None,
    stale_days: int = 30,
) -> list[dict[str, Any]]:
    resolved_now = now or datetime.now(timezone.utc)
    memories = (
        db.query(Memory)
        .filter(Memory.project_id == project_id)
        .filter(Memory.node_status == "active")
        .all()
    )
    out: list[dict[str, Any]] = []
    for memory in memories:
        if get_subject_kind(memory) != "person":
            continue
        last_evidence = (
            db.query(MemoryEvidence)
            .filter(MemoryEvidence.memory_id == memory.id)
            .order_by(MemoryEvidence.created_at.desc())
            .first()
        )
        if last_evidence is None:
            out.append({
                "memory_id": memory.id,
                "person_label": memory.content[:120],
                "last_mention_at": None,
                "days_since": None,
            })
            continue
        days = (resolved_now - last_evidence.created_at).days
        if days <= stale_days:
            continue
        out.append({
            "memory_id": memory.id,
            "person_label": memory.content[:120],
            "last_mention_at": last_evidence.created_at.isoformat(),
            "days_since": days,
        })
    return out
```

- [ ] **Step 4: Run to verify pass**

Run: `cd apps/api && .venv/bin/pytest tests/test_proactive_materials.py -v`
Expected: 8 PASSED.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/services/proactive_materials.py apps/api/tests/test_proactive_materials.py
git commit -m "feat(api): proactive_materials with 4 collectors + 8 tests"
```

---

### Task 4: `proactive_generator.py` — prompts + LLM dispatch + 4 tests

**Files:**
- Create: `apps/api/app/services/proactive_generator.py`
- Create: `apps/api/tests/test_proactive_generator.py`

- [ ] **Step 1: Write failing tests**

Create `apps/api/tests/test_proactive_generator.py`:

```python
# ruff: noqa: E402
import asyncio
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ["ENV"] = "test"

import pytest
from unittest.mock import AsyncMock, patch

from app.services.proactive_generator import generate_digest_content


FAKE_DAILY = """
{"summary_md": "hi", "next_actions": [{"page_id":"p1","title":"T","hint":"do it"}]}
""".strip()

FAKE_WEEKLY = """
{"summary_md":"week","learning_recap_md":"lr","blockers_md":"bl"}
""".strip()

FAKE_DEVIATION_ONE = """
{"drifts":[{"goal_memory_id":"g1","drift_reason_md":"…","confidence":0.7}]}
""".strip()

FAKE_DEVIATION_EMPTY = """
{"drifts":[]}
""".strip()


def test_daily_generator_parses_content() -> None:
    mats = {
        "action_counts": {"selection.rewrite": 3},
        "action_samples": [{"output_summary": "..."}],
        "page_edits": [],
        "reconfirm_items": [],
    }
    with patch(
        "app.services.proactive_generator._run_llm_json",
        new=AsyncMock(return_value=FAKE_DAILY),
    ):
        content = asyncio.run(generate_digest_content(
            kind="daily_digest", materials=mats, project_name="P"
        ))
    assert content["summary_md"] == "hi"
    assert content["next_actions"][0]["page_id"] == "p1"
    # reconfirm_items preserved from materials (rule-based, not LLM)
    assert content["reconfirm_items"] == []


def test_weekly_generator_parses_content() -> None:
    mats = {
        "action_counts": {},
        "action_samples": [],
        "page_edits": [],
        "study_stats": {"cards_reviewed": 10, "lapse_count": 1, "confusions_logged": 0},
        "blocker_tasks": [],
    }
    with patch(
        "app.services.proactive_generator._run_llm_json",
        new=AsyncMock(return_value=FAKE_WEEKLY),
    ):
        content = asyncio.run(generate_digest_content(
            kind="weekly_reflection", materials=mats, project_name="P"
        ))
    assert content["summary_md"] == "week"
    assert content["stats"]["cards_reviewed"] == 10


def test_deviation_generator_returns_list_of_drifts() -> None:
    mats = {
        "goals": [{"memory_id": "g1", "content": "ship MVP", "importance": 0.8}],
        "activity_summary": "unrelated stuff",
    }
    with patch(
        "app.services.proactive_generator._run_llm_json",
        new=AsyncMock(return_value=FAKE_DEVIATION_ONE),
    ):
        content = asyncio.run(generate_digest_content(
            kind="deviation_reminder", materials=mats, project_name="P"
        ))
    assert content["drifts"][0]["goal_memory_id"] == "g1"


def test_bad_llm_output_raises() -> None:
    from app.core.errors import ApiError
    mats = {"goals": [], "activity_summary": ""}
    with patch(
        "app.services.proactive_generator._run_llm_json",
        new=AsyncMock(return_value="not json"),
    ):
        with pytest.raises(ApiError) as exc:
            asyncio.run(generate_digest_content(
                kind="daily_digest", materials={"action_counts":{},"action_samples":[],"page_edits":[],"reconfirm_items":[]},
                project_name="P",
            ))
    assert exc.value.code == "llm_bad_output"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && .venv/bin/pytest tests/test_proactive_generator.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Create the module**

Create `apps/api/app/services/proactive_generator.py`:

```python
"""S5 proactive services: LLM prompts + content_json assembly."""

from __future__ import annotations

import json
from typing import Any

from app.core.errors import ApiError
from app.services.dashscope_client import chat_completion


_DAILY_SYSTEM = (
    "You are a daily digest generator. Summarize the user's last-24h "
    "activity in 3-5 sentences, then suggest concrete next actions "
    'pointing at existing pages. Return strict JSON: {"summary_md":"...", '
    '"next_actions":[{"page_id":"...","title":"...","hint":"..."}]}.'
)

_WEEKLY_SYSTEM = (
    "You are a weekly reflection generator. Produce a 5-8 sentence "
    "summary, a learning recap, and a blockers retrospective. Return "
    'strict JSON: {"summary_md":"...","learning_recap_md":"...","blockers_md":"..."}.'
)

_DEVIATION_SYSTEM = (
    "You judge whether stated goals are drifting. Given goals and recent "
    "activity, return 0-3 drift reports. Strict JSON: "
    '{"drifts":[{"goal_memory_id":"...","drift_reason_md":"...","confidence":0.0-1.0}]}. '
    "Empty drifts list is valid if nothing is drifting. Only return JSON."
)


async def _run_llm_json(system: str, user_prompt: str) -> str:
    """Seam the tests monkey-patch. Calls the non-streaming LLM and
    returns the raw text (expected to be JSON)."""
    return await chat_completion(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
        max_tokens=2048,
    )


def _build_daily_user_prompt(materials: dict[str, Any], project_name: str) -> str:
    return (
        f"Project: {project_name}\n\n"
        f"Action counts (last 24h): {json.dumps(materials.get('action_counts', {}), ensure_ascii=False)}\n"
        f"Action samples: {json.dumps(materials.get('action_samples', [])[:5], ensure_ascii=False)}\n"
        f"Pages edited: {json.dumps(materials.get('page_edits', []), ensure_ascii=False)}\n"
    )


def _build_weekly_user_prompt(materials: dict[str, Any], project_name: str) -> str:
    return (
        f"Project: {project_name}\n\n"
        f"Action counts (last 7d): {json.dumps(materials.get('action_counts', {}), ensure_ascii=False)}\n"
        f"Action samples: {json.dumps(materials.get('action_samples', [])[:10], ensure_ascii=False)}\n"
        f"Pages edited: {json.dumps(materials.get('page_edits', []), ensure_ascii=False)}\n"
        f"Study stats: {json.dumps(materials.get('study_stats', {}), ensure_ascii=False)}\n"
        f"Blocker tasks: {json.dumps(materials.get('blocker_tasks', []), ensure_ascii=False)}\n"
    )


def _build_deviation_user_prompt(materials: dict[str, Any], project_name: str) -> str:
    return (
        f"Project: {project_name}\n\n"
        f"Goals:\n{json.dumps(materials.get('goals', []), ensure_ascii=False)}\n\n"
        f"Recent activity summary:\n{materials.get('activity_summary', '')}\n"
    )


async def generate_digest_content(
    *,
    kind: str,
    materials: dict[str, Any],
    project_name: str,
) -> dict[str, Any]:
    """Dispatch to the right prompt + LLM call, return content_json.

    Raises ApiError("llm_bad_output") on parse failure or missing
    required fields.
    """
    if kind == "daily_digest":
        system, user = _DAILY_SYSTEM, _build_daily_user_prompt(materials, project_name)
    elif kind == "weekly_reflection":
        system, user = _WEEKLY_SYSTEM, _build_weekly_user_prompt(materials, project_name)
    elif kind == "deviation_reminder":
        system, user = _DEVIATION_SYSTEM, _build_deviation_user_prompt(materials, project_name)
    else:
        raise ApiError("invalid_input", f"Unknown kind {kind}", status_code=400)

    raw = await _run_llm_json(system, user)
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("top-level must be object")
    except Exception:
        raise ApiError("llm_bad_output", "LLM returned invalid JSON", status_code=422)

    if kind == "daily_digest":
        if not isinstance(parsed.get("summary_md"), str):
            raise ApiError("llm_bad_output", "summary_md missing", status_code=422)
        parsed.setdefault("next_actions", [])
        # Pass through rule-based reconfirm items + sources (not LLM).
        parsed["reconfirm_items"] = materials.get("reconfirm_items", [])
        parsed["sources"] = {
            "action_log_ids": [s.get("action_log_id") for s in materials.get("action_samples", [])],
            "page_ids": [p.get("page_id") for p in materials.get("page_edits", [])],
        }
    elif kind == "weekly_reflection":
        for key in ("summary_md", "learning_recap_md", "blockers_md"):
            if not isinstance(parsed.get(key), str):
                raise ApiError("llm_bad_output", f"{key} missing", status_code=422)
        parsed["stats"] = materials.get("study_stats", {}) | {
            "action_count": sum(materials.get("action_counts", {}).values()),
            "pages_edited": len(materials.get("page_edits", [])),
        }
        parsed["sources"] = {
            "action_log_ids": [s.get("action_log_id") for s in materials.get("action_samples", [])],
            "page_ids": [p.get("page_id") for p in materials.get("page_edits", [])],
        }
    elif kind == "deviation_reminder":
        drifts = parsed.get("drifts")
        if not isinstance(drifts, list):
            raise ApiError("llm_bad_output", "drifts must be list", status_code=422)
        parsed["drifts"] = drifts[:3]

    return parsed
```

- [ ] **Step 4: Run to verify pass**

Run: `cd apps/api && .venv/bin/pytest tests/test_proactive_generator.py -v`
Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/services/proactive_generator.py apps/api/tests/test_proactive_generator.py
git commit -m "feat(api): proactive_generator with per-kind prompts + 4 tests"
```

---

### Task 5: Per-project generator Celery task

**Files:**
- Modify: `apps/api/app/tasks/worker_tasks.py`
- Create: `apps/api/tests/test_proactive_generator_task.py`

- [ ] **Step 1: Write failing tests**

Create `apps/api/tests/test_proactive_generator_task.py`:

```python
# ruff: noqa: E402
import atexit, importlib, os, shutil, tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-s5-gentask-"))
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
from app.models import (
    AIActionLog, Memory, Notebook, NotebookPage, ProactiveDigest,
    Project, User, Workspace,
)


def setup_function() -> None:
    global engine, SessionLocal
    engine = _s.engine
    SessionLocal = _s.SessionLocal
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    # Re-bind worker_tasks.SessionLocal like S4 did.
    import app.tasks.worker_tasks as _wt
    _wt.SessionLocal = _s.SessionLocal


engine = _s.engine
SessionLocal = _s.SessionLocal


def _seed_daily() -> tuple[str, str, str]:
    """Returns (workspace_id, project_id, notebook_id)."""
    with SessionLocal() as db:
        ws = Workspace(name="W"); user = User(email="u@x.co", password_hash="x")
        db.add(ws); db.add(user); db.commit(); db.refresh(ws); db.refresh(user)
        pr = Project(workspace_id=ws.id, name="P")
        db.add(pr); db.commit(); db.refresh(pr)
        nb = Notebook(workspace_id=ws.id, project_id=pr.id, created_by=user.id,
                      title="NB", slug="nb")
        db.add(nb); db.commit(); db.refresh(nb)
        db.add(AIActionLog(
            workspace_id=ws.id, user_id=user.id, notebook_id=nb.id,
            action_type="selection.rewrite", scope="selection",
            status="completed", output_summary="out",
            trace_metadata={},
        ))
        db.commit()
        return ws.id, pr.id, nb.id


def test_task_creates_one_daily_digest_row() -> None:
    ws_id, project_id, _ = _seed_daily()
    now = datetime.now(timezone.utc)
    period_start = (now - timedelta(hours=24)).isoformat()
    period_end = now.isoformat()

    fake_llm = AsyncMock(return_value='{"summary_md":"hi","next_actions":[]}')
    with patch(
        "app.services.proactive_generator._run_llm_json", fake_llm,
    ):
        from app.tasks.worker_tasks import generate_proactive_digest_task
        result = generate_proactive_digest_task.run(
            project_id, "daily_digest", period_start, period_end,
        )
    assert result is not None
    with SessionLocal() as db:
        rows = db.query(ProactiveDigest).all()
    assert len(rows) == 1
    assert rows[0].kind == "daily_digest"
    assert rows[0].status == "unread"
    assert rows[0].content_json["summary_md"] == "hi"
    assert rows[0].action_log_id  # S1 action_log linked


def test_task_idempotent_on_second_call() -> None:
    ws_id, project_id, _ = _seed_daily()
    now = datetime.now(timezone.utc)
    ps = (now - timedelta(hours=24)).isoformat()
    pe = now.isoformat()

    fake_llm = AsyncMock(return_value='{"summary_md":"hi","next_actions":[]}')
    with patch(
        "app.services.proactive_generator._run_llm_json", fake_llm,
    ):
        from app.tasks.worker_tasks import generate_proactive_digest_task
        generate_proactive_digest_task.run(project_id, "daily_digest", ps, pe)
        result2 = generate_proactive_digest_task.run(
            project_id, "daily_digest", ps, pe,
        )
    assert result2 is None
    with SessionLocal() as db:
        count = db.query(ProactiveDigest).count()
    assert count == 1


def test_task_empty_activity_returns_none() -> None:
    """If no activity in window, skip row creation."""
    with SessionLocal() as db:
        ws = Workspace(name="W"); user = User(email="u@x.co", password_hash="x")
        db.add(ws); db.add(user); db.commit(); db.refresh(ws); db.refresh(user)
        pr = Project(workspace_id=ws.id, name="P")
        db.add(pr); db.commit(); db.refresh(pr)
        # No notebook, no activity
        project_id = pr.id

    now = datetime.now(timezone.utc)
    ps = (now - timedelta(hours=24)).isoformat()
    pe = now.isoformat()

    from app.tasks.worker_tasks import generate_proactive_digest_task
    result = generate_proactive_digest_task.run(
        project_id, "daily_digest", ps, pe,
    )
    assert result is None
    with SessionLocal() as db:
        assert db.query(ProactiveDigest).count() == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && .venv/bin/pytest tests/test_proactive_generator_task.py -v`
Expected: FAIL — task not defined.

- [ ] **Step 3: Add the task to worker_tasks.py**

Append to `apps/api/app/tasks/worker_tasks.py`:

```python
# ---------------------------------------------------------------------------
# S5 proactive services: per-project digest generator
# ---------------------------------------------------------------------------


def _materials_empty(kind: str, materials: dict) -> bool:
    """Heuristic: skip row creation when there's nothing to digest."""
    if kind == "daily_digest":
        return (
            not materials.get("action_counts")
            and not materials.get("page_edits")
            and not materials.get("reconfirm_items")
        )
    if kind == "weekly_reflection":
        return (
            not materials.get("action_counts")
            and not materials.get("page_edits")
            and materials.get("study_stats", {}).get("cards_reviewed", 0) == 0
        )
    if kind == "deviation_reminder":
        return not materials.get("goals")
    return False  # relationship_reminder handled via separate fan-out


@celery_app.task(name="app.tasks.worker_tasks.generate_proactive_digest")
def generate_proactive_digest_task(
    project_id: str,
    kind: str,
    period_start_iso: str,
    period_end_iso: str,
) -> str | None:
    """Generate one (or zero, or many for *_reminder) ProactiveDigest rows.

    Idempotent via the unique constraint (project_id, kind, period_start).
    """
    import asyncio as _asyncio
    from datetime import datetime as _dt
    from sqlalchemy.exc import IntegrityError
    from app.models import Notebook, Project, ProactiveDigest, Workspace
    from app.services.ai_action_logger import action_log_context
    from app.services.proactive_generator import generate_digest_content
    from app.services.proactive_materials import (
        collect_daily_materials, collect_goal_materials,
        collect_relationship_materials, collect_weekly_materials,
    )

    period_start = _dt.fromisoformat(period_start_iso.replace("Z", "+00:00"))
    period_end = _dt.fromisoformat(period_end_iso.replace("Z", "+00:00"))

    db = SessionLocal()
    try:
        project = db.get(Project, project_id)
        if not project:
            return None
        workspace = db.get(Workspace, project.workspace_id)
        if not workspace:
            return None
        # Creator defaults to workspace owner — first workspace membership.
        from app.models import Membership
        owner = (
            db.query(Membership)
            .filter(Membership.workspace_id == workspace.id, Membership.role == "owner")
            .first()
        )
        user_id = owner.user_id if owner else None
        if not user_id:
            return None

        # Idempotency guard (pre-check + unique constraint backup)
        existing = (
            db.query(ProactiveDigest)
            .filter(
                ProactiveDigest.project_id == project_id,
                ProactiveDigest.kind == kind,
                ProactiveDigest.period_start == period_start,
            )
            .first()
        )
        if existing is not None:
            return None

        # Collect materials per-kind
        if kind == "daily_digest":
            materials = collect_daily_materials(
                db, project_id=project_id,
                period_start=period_start, period_end=period_end,
            )
        elif kind == "weekly_reflection":
            materials = collect_weekly_materials(
                db, project_id=project_id,
                period_start=period_start, period_end=period_end,
            )
        elif kind == "deviation_reminder":
            materials = collect_goal_materials(
                db, project_id=project_id,
                period_start=period_start, period_end=period_end,
            )
        elif kind == "relationship_reminder":
            rel_items = collect_relationship_materials(
                db, project_id=project_id, now=period_end,
            )
            materials = {"items": rel_items}
        else:
            return None

        # Skip when nothing to report (daily/weekly/deviation only)
        if kind in ("daily_digest", "weekly_reflection", "deviation_reminder") and _materials_empty(kind, materials):
            return None
        if kind == "relationship_reminder" and not materials["items"]:
            return None

        # Use the action logger for traceability (reuses async context manager)
        async def _async_work() -> list[str]:
            async with action_log_context(
                db,
                workspace_id=str(workspace.id),
                user_id=str(user_id),
                action_type=f"proactive.{kind}",
                scope="project",
                notebook_id=None,
                page_id=None,
                block_id=project_id,
            ) as log:
                log.set_input({"kind": kind,
                               "period_start": period_start_iso,
                               "period_end": period_end_iso})
                inserted_ids: list[str] = []
                try:
                    if kind in ("daily_digest", "weekly_reflection"):
                        content = await generate_digest_content(
                            kind=kind, materials=materials,
                            project_name=project.name,
                        )
                        row = ProactiveDigest(
                            workspace_id=str(workspace.id),
                            project_id=project_id,
                            user_id=str(user_id),
                            kind=kind,
                            period_start=period_start,
                            period_end=period_end,
                            title=(
                                f"Daily digest · {period_end.date().isoformat()}"
                                if kind == "daily_digest"
                                else f"Weekly reflection · {period_end.date().isoformat()}"
                            ),
                            content_markdown=content.get("summary_md", ""),
                            content_json=content,
                            action_log_id=log.log_id,
                        )
                        db.add(row); db.commit(); db.refresh(row)
                        inserted_ids.append(row.id)
                    elif kind == "deviation_reminder":
                        content = await generate_digest_content(
                            kind=kind, materials=materials,
                            project_name=project.name,
                        )
                        for drift in content.get("drifts", []):
                            row = ProactiveDigest(
                                workspace_id=str(workspace.id),
                                project_id=project_id,
                                user_id=str(user_id),
                                kind=kind,
                                period_start=period_start + timedelta(seconds=len(inserted_ids)),
                                period_end=period_end,
                                title=f"Goal drift: {drift.get('goal_memory_id','')[:20]}",
                                content_markdown=drift.get("drift_reason_md", ""),
                                content_json=drift,
                                action_log_id=log.log_id,
                            )
                            db.add(row); db.commit(); db.refresh(row)
                            inserted_ids.append(row.id)
                    elif kind == "relationship_reminder":
                        for idx, item in enumerate(materials["items"]):
                            row = ProactiveDigest(
                                workspace_id=str(workspace.id),
                                project_id=project_id,
                                user_id=str(user_id),
                                kind=kind,
                                period_start=period_start + timedelta(seconds=idx),
                                period_end=period_end,
                                title=f"Stale contact: {item['person_label']}",
                                content_markdown=(
                                    f"No mention in {item['days_since']} day(s)."
                                    if item.get("days_since") is not None
                                    else "No evidence recorded yet."
                                ),
                                content_json=item,
                                action_log_id=log.log_id,
                            )
                            db.add(row); db.commit(); db.refresh(row)
                            inserted_ids.append(row.id)
                except IntegrityError:
                    db.rollback()
                    logger.info(
                        "proactive_digest: unique constraint hit for %s/%s — skipping",
                        project_id, kind,
                    )
                log.set_output({"inserted_ids": inserted_ids, "count": len(inserted_ids)})
            return inserted_ids

        inserted = _asyncio.run(_async_work())
        return inserted[0] if inserted else None
    except Exception:
        logger.exception("generate_proactive_digest_task failed")
        return None
    finally:
        db.close()
```

Add the `timedelta` import near the top of `worker_tasks.py` if
it isn't already there (the file likely already imports
`datetime, timedelta`).

- [ ] **Step 4: Run to verify pass**

Run: `cd apps/api && .venv/bin/pytest tests/test_proactive_generator_task.py -v`
Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/tasks/worker_tasks.py apps/api/tests/test_proactive_generator_task.py
git commit -m "feat(api): generate_proactive_digest_task — per-project digest generator"
```

---

### Task 6: 4 fan-out Celery tasks + beat schedule + 5 tests

**Files:**
- Modify: `apps/api/app/tasks/worker_tasks.py`
- Modify: `apps/api/app/tasks/celery_app.py`
- Create: `apps/api/tests/test_proactive_fanout_tasks.py`

- [ ] **Step 1: Write failing tests**

Create `apps/api/tests/test_proactive_fanout_tasks.py`:

```python
# ruff: noqa: E402
import atexit, importlib, os, shutil, tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-s5-fanout-"))
atexit.register(lambda: shutil.rmtree(TEST_TEMP_DIR, ignore_errors=True))
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_TEMP_DIR / 'test.db'}"
os.environ["ENV"] = "test"

import app.core.config as config_module
config_module.get_settings.cache_clear()
config_module.settings = config_module.get_settings()
import app.db.session as session_module
importlib.reload(session_module)

from unittest.mock import patch

from app.db.base import Base
import app.db.session as _s
from app.models import (
    AIActionLog, Memory, MemoryEvidence, Notebook, Project, User, Workspace,
)


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


def _seed_project_with_recent_activity() -> str:
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        ws = Workspace(name="W"); user = User(email="u@x.co", password_hash="x")
        db.add(ws); db.add(user); db.commit(); db.refresh(ws); db.refresh(user)
        pr = Project(workspace_id=ws.id, name="P")
        db.add(pr); db.commit(); db.refresh(pr)
        nb = Notebook(workspace_id=ws.id, project_id=pr.id, created_by=user.id,
                      title="NB", slug="nb")
        db.add(nb); db.commit(); db.refresh(nb)
        db.add(AIActionLog(
            workspace_id=ws.id, user_id=user.id, notebook_id=nb.id,
            action_type="selection.rewrite", scope="selection",
            status="completed", output_summary="out",
            trace_metadata={},
            created_at=now - timedelta(hours=2),
        ))
        db.commit()
        return pr.id


def test_daily_fanout_enqueues_one_per_active_project() -> None:
    p1 = _seed_project_with_recent_activity()

    from app.tasks.worker_tasks import generate_daily_digests_task
    with patch(
        "app.tasks.worker_tasks.generate_proactive_digest_task.delay",
    ) as delay_mock:
        result = generate_daily_digests_task.run()
    assert delay_mock.call_count == 1
    args = delay_mock.call_args[0]
    assert args[0] == p1
    assert args[1] == "daily_digest"
    assert result["dispatched"] == 1


def test_weekly_fanout_skips_projects_with_no_activity() -> None:
    with SessionLocal() as db:
        ws = Workspace(name="W"); db.add(ws); db.commit(); db.refresh(ws)
        user = User(email="u@x.co", password_hash="x")
        db.add(user); db.commit(); db.refresh(user)
        pr = Project(workspace_id=ws.id, name="idle")
        db.add(pr); db.commit(); db.refresh(pr)
        # no notebook, no activity

    from app.tasks.worker_tasks import generate_weekly_reflections_task
    with patch(
        "app.tasks.worker_tasks.generate_proactive_digest_task.delay",
    ) as delay_mock:
        result = generate_weekly_reflections_task.run()
    assert delay_mock.call_count == 0
    assert result["dispatched"] == 0


def test_deviation_fanout_filters_to_goal_projects() -> None:
    p1 = _seed_project_with_recent_activity()
    with SessionLocal() as db:
        db.add(Memory(
            project_id=p1, content="Goal",
            importance=0.8, node_status="active",
            metadata_json={"memory_kind": "goal"},
        ))
        db.commit()

    from app.tasks.worker_tasks import generate_deviation_reminders_task
    with patch(
        "app.tasks.worker_tasks.generate_proactive_digest_task.delay",
    ) as delay_mock:
        generate_deviation_reminders_task.run()
    assert delay_mock.call_count == 1
    assert delay_mock.call_args[0][1] == "deviation_reminder"


def test_deviation_fanout_skips_projects_without_goals() -> None:
    _seed_project_with_recent_activity()  # no goal memory

    from app.tasks.worker_tasks import generate_deviation_reminders_task
    with patch(
        "app.tasks.worker_tasks.generate_proactive_digest_task.delay",
    ) as delay_mock:
        generate_deviation_reminders_task.run()
    assert delay_mock.call_count == 0


def test_relationship_fanout_filters_to_person_projects() -> None:
    p1 = _seed_project_with_recent_activity()
    with SessionLocal() as db:
        db.add(Memory(
            project_id=p1, content="张三",
            importance=0.6, node_status="active",
            metadata_json={"subject_kind": "person"},
        ))
        db.commit()

    from app.tasks.worker_tasks import generate_relationship_reminders_task
    with patch(
        "app.tasks.worker_tasks.generate_proactive_digest_task.delay",
    ) as delay_mock:
        generate_relationship_reminders_task.run()
    assert delay_mock.call_count == 1
    assert delay_mock.call_args[0][1] == "relationship_reminder"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && .venv/bin/pytest tests/test_proactive_fanout_tasks.py -v`
Expected: FAIL — tasks not defined.

- [ ] **Step 3: Add fan-out tasks to worker_tasks.py**

Append to `apps/api/app/tasks/worker_tasks.py`:

```python
def _active_project_ids(window_hours: int) -> list[str]:
    """Return project IDs that had any AIActionLog OR NotebookPage edit
    in the last `window_hours` hours."""
    from app.models import AIActionLog, Notebook, NotebookPage, Project
    db = SessionLocal()
    try:
        threshold = datetime.now(timezone.utc) - timedelta(hours=window_hours)
        subq_action = (
            db.query(Notebook.project_id)
            .join(AIActionLog, AIActionLog.notebook_id == Notebook.id)
            .filter(AIActionLog.created_at >= threshold)
            .distinct()
        )
        subq_page = (
            db.query(Notebook.project_id)
            .join(NotebookPage, NotebookPage.notebook_id == Notebook.id)
            .filter(NotebookPage.last_edited_at >= threshold)
            .distinct()
        )
        ids: set[str] = set()
        for row in subq_action.all():
            ids.add(row[0])
        for row in subq_page.all():
            ids.add(row[0])
        return sorted(ids)
    finally:
        db.close()


@celery_app.task(name="app.tasks.worker_tasks.generate_daily_digests")
def generate_daily_digests_task() -> dict[str, int]:
    """Daily fan-out: enqueue per-project daily digest jobs."""
    now = datetime.now(timezone.utc)
    period_start = now - timedelta(hours=24)
    project_ids = _active_project_ids(window_hours=24)
    for pid in project_ids:
        generate_proactive_digest_task.delay(
            pid, "daily_digest",
            period_start.isoformat(), now.isoformat(),
        )
    return {"dispatched": len(project_ids)}


@celery_app.task(name="app.tasks.worker_tasks.generate_weekly_reflections")
def generate_weekly_reflections_task() -> dict[str, int]:
    now = datetime.now(timezone.utc)
    period_start = now - timedelta(days=7)
    project_ids = _active_project_ids(window_hours=24 * 7)
    for pid in project_ids:
        generate_proactive_digest_task.delay(
            pid, "weekly_reflection",
            period_start.isoformat(), now.isoformat(),
        )
    return {"dispatched": len(project_ids)}


def _projects_with_memory_matching(predicate) -> list[str]:
    """Return project IDs where at least one active memory satisfies predicate."""
    from app.models import Memory
    db = SessionLocal()
    try:
        memories = (
            db.query(Memory)
            .filter(Memory.node_status == "active")
            .all()
        )
        ids: set[str] = set()
        for m in memories:
            if predicate(m):
                ids.add(m.project_id)
        return sorted(ids)
    finally:
        db.close()


@celery_app.task(name="app.tasks.worker_tasks.generate_deviation_reminders")
def generate_deviation_reminders_task() -> dict[str, int]:
    from app.services.memory_metadata import get_memory_kind
    now = datetime.now(timezone.utc)
    period_start = now - timedelta(days=7)
    project_ids = _projects_with_memory_matching(
        lambda m: get_memory_kind(m) == "goal",
    )
    # Also require recent activity (goals alone aren't enough — nothing to compare)
    active = set(_active_project_ids(window_hours=24 * 7))
    targets = [pid for pid in project_ids if pid in active]
    for pid in targets:
        generate_proactive_digest_task.delay(
            pid, "deviation_reminder",
            period_start.isoformat(), now.isoformat(),
        )
    return {"dispatched": len(targets)}


@celery_app.task(name="app.tasks.worker_tasks.generate_relationship_reminders")
def generate_relationship_reminders_task() -> dict[str, int]:
    from app.services.memory_metadata import get_subject_kind
    now = datetime.now(timezone.utc)
    period_start = now - timedelta(days=30)
    project_ids = _projects_with_memory_matching(
        lambda m: get_subject_kind(m) == "person",
    )
    for pid in project_ids:
        generate_proactive_digest_task.delay(
            pid, "relationship_reminder",
            period_start.isoformat(), now.isoformat(),
        )
    return {"dispatched": len(project_ids)}
```

Ensure `datetime, timedelta, timezone` are imported at module top
(the file likely already has them).

- [ ] **Step 4: Add beat schedule + task routes**

Open `apps/api/app/tasks/celery_app.py`. Extend the
`task_routes` dict and `beat_schedule` dict:

```python
celery_app.conf.task_routes = {
    # existing entries unchanged ...
    "app.tasks.worker_tasks.process_data_item": {"queue": "data"},
    "app.tasks.worker_tasks.cleanup_deleted_dataset": {"queue": "cleanup"},
    "app.tasks.worker_tasks.cleanup_deleted_project": {"queue": "cleanup"},
    "app.tasks.worker_tasks.cleanup_pending_upload_session": {"queue": "cleanup"},
    "app.tasks.worker_tasks.cleanup_pending_model_artifact_upload": {"queue": "cleanup"},
    "app.tasks.worker_tasks.purge_stale_records": {"queue": "cleanup"},
    "app.tasks.worker_tasks.index_data_item": {"queue": "data"},
    "app.tasks.worker_tasks.extract_memories": {"queue": "inference"},
    "app.tasks.worker_tasks.compact_project_memories": {"queue": "memory"},
    "app.tasks.worker_tasks.repair_project_memory_graph": {"queue": "memory"},
    "app.tasks.worker_tasks.backfill_project_memory_v2": {"queue": "memory"},
    "app.tasks.worker_tasks.run_project_memory_sleep_cycle": {"queue": "memory"},
    "app.tasks.worker_tasks.run_nightly_memory_sleep_cycle": {"queue": "memory"},
    # S5 additions
    "app.tasks.worker_tasks.generate_daily_digests": {"queue": "memory"},
    "app.tasks.worker_tasks.generate_weekly_reflections": {"queue": "memory"},
    "app.tasks.worker_tasks.generate_deviation_reminders": {"queue": "memory"},
    "app.tasks.worker_tasks.generate_relationship_reminders": {"queue": "memory"},
    "app.tasks.worker_tasks.generate_proactive_digest": {"queue": "memory"},
}
```

And the beat schedule:

```python
celery_app.conf.beat_schedule = {
    "purge-stale-records-daily": {
        "task": "app.tasks.worker_tasks.purge_stale_records",
        "schedule": crontab(hour=3, minute=0),
    },
    "memory-sleep-cycle-nightly": {
        "task": "app.tasks.worker_tasks.run_nightly_memory_sleep_cycle",
        "schedule": crontab(hour=2, minute=30),
    },
    # S5 additions
    "generate-daily-digests": {
        "task": "app.tasks.worker_tasks.generate_daily_digests",
        "schedule": crontab(hour=7, minute=3),
    },
    "generate-weekly-reflections": {
        "task": "app.tasks.worker_tasks.generate_weekly_reflections",
        "schedule": crontab(hour=8, minute=7, day_of_week=1),
    },
    "generate-deviation-reminders": {
        "task": "app.tasks.worker_tasks.generate_deviation_reminders",
        "schedule": crontab(hour=8, minute=12, day_of_week=1),
    },
    "generate-relationship-reminders": {
        "task": "app.tasks.worker_tasks.generate_relationship_reminders",
        "schedule": crontab(hour=8, minute=17, day_of_week=1),
    },
}
```

- [ ] **Step 5: Run to verify pass**

Run: `cd apps/api && .venv/bin/pytest tests/test_proactive_fanout_tasks.py -v`
Expected: 5 PASSED.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/tasks/worker_tasks.py apps/api/app/tasks/celery_app.py apps/api/tests/test_proactive_fanout_tasks.py
git commit -m "feat(api): 4 fan-out Celery tasks + beat schedule + task_routes for S5"
```

---

### Task 7: 6 API endpoints + 7 tests

**Files:**
- Create: `apps/api/app/routers/proactive.py`
- Modify: `apps/api/app/main.py`
- Create: `apps/api/tests/test_proactive_api.py`

- [ ] **Step 1: Write failing tests**

Create `apps/api/tests/test_proactive_api.py`:

```python
# ruff: noqa: E402
import atexit, importlib, os, shutil, tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-s5-api-"))
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
from unittest.mock import patch

from app.db.base import Base
import app.db.session as _s
from app.models import ProactiveDigest


def setup_function() -> None:
    global engine, SessionLocal
    engine = _s.engine
    SessionLocal = _s.SessionLocal
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    from app.services.runtime_state import runtime_state
    runtime_state._memory = runtime_state._memory.__class__()
    import app.tasks.worker_tasks as _wt
    _wt.SessionLocal = _s.SessionLocal


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
    csrf = client.get("/api/v1/auth/csrf", headers=_public_headers()).json()["csrf_token"]
    client.headers.update({
        "origin": "http://localhost:3000",
        "x-csrf-token": csrf,
        "x-workspace-id": info["workspace"]["id"],
    })
    return client, {"ws_id": info["workspace"]["id"], "user_id": info["user"]["id"]}


def _seed_digest(ws_id: str, user_id: str, **kwargs) -> str:
    from app.models import Project
    with SessionLocal() as db:
        pr = Project(workspace_id=ws_id, name="P")
        db.add(pr); db.commit(); db.refresh(pr)
        d = ProactiveDigest(
            workspace_id=ws_id, project_id=pr.id, user_id=user_id,
            kind=kwargs.get("kind", "daily_digest"),
            period_start=datetime.now(timezone.utc) - timedelta(hours=24),
            period_end=datetime.now(timezone.utc),
            title=kwargs.get("title", "Daily"),
            content_markdown=kwargs.get("content_markdown", "hi"),
            content_json={"summary_md": "hi"},
            status=kwargs.get("status", "unread"),
        )
        db.add(d); db.commit(); db.refresh(d)
        return d.id


def test_list_returns_unread_first() -> None:
    client, auth = _register_client("u1@x.co")
    d_id = _seed_digest(auth["ws_id"], auth["user_id"])
    resp = client.get("/api/v1/digests?status=unread")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["id"] == d_id
    assert body["unread_count"] == 1


def test_detail_returns_full_row() -> None:
    client, auth = _register_client("u2@x.co")
    d_id = _seed_digest(auth["ws_id"], auth["user_id"])
    resp = client.get(f"/api/v1/digests/{d_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["content_markdown"] == "hi"


def test_read_marks_row_read() -> None:
    client, auth = _register_client("u3@x.co")
    d_id = _seed_digest(auth["ws_id"], auth["user_id"])
    resp = client.post(f"/api/v1/digests/{d_id}/read")
    assert resp.status_code == 200
    detail = client.get(f"/api/v1/digests/{d_id}").json()
    assert detail["status"] == "read"
    assert detail["read_at"] is not None


def test_dismiss_marks_row_dismissed() -> None:
    client, auth = _register_client("u4@x.co")
    d_id = _seed_digest(auth["ws_id"], auth["user_id"])
    client.post(f"/api/v1/digests/{d_id}/dismiss")
    detail = client.get(f"/api/v1/digests/{d_id}").json()
    assert detail["status"] == "dismissed"


def test_unread_count_endpoint() -> None:
    client, auth = _register_client("u5@x.co")
    _seed_digest(auth["ws_id"], auth["user_id"], kind="daily_digest")
    _seed_digest(auth["ws_id"], auth["user_id"], kind="weekly_reflection")
    resp = client.get("/api/v1/digests/unread-count")
    assert resp.status_code == 200
    assert resp.json()["unread_count"] == 2


def test_cross_workspace_returns_404() -> None:
    _client_a, auth_a = _register_client("a@x.co")
    d_id = _seed_digest(auth_a["ws_id"], auth_a["user_id"])
    client_b, _ = _register_client("b@x.co")
    resp = client_b.get(f"/api/v1/digests/{d_id}")
    assert resp.status_code == 404


def test_generate_now_enqueues_task() -> None:
    client, auth = _register_client("u7@x.co")
    from app.models import Project
    with SessionLocal() as db:
        pr = Project(workspace_id=auth["ws_id"], name="P")
        db.add(pr); db.commit(); db.refresh(pr)
        project_id = pr.id

    with patch(
        "app.tasks.worker_tasks.generate_proactive_digest_task.delay",
    ) as delay_mock:
        resp = client.post(
            "/api/v1/digests/generate-now",
            json={"kind": "daily_digest", "project_id": project_id},
        )
    assert resp.status_code == 200
    assert delay_mock.call_count == 1
    args = delay_mock.call_args[0]
    assert args[0] == project_id
    assert args[1] == "daily_digest"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && .venv/bin/pytest tests/test_proactive_api.py -v`
Expected: FAIL — router missing.

- [ ] **Step 3: Create the router**

Create `apps/api/app/routers/proactive.py`:

```python
"""S5 Proactive digests API."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import (
    get_current_user,
    get_current_workspace_id,
    get_db_session,
    require_csrf_protection,
    require_workspace_write_access,
)
from app.core.errors import ApiError
from app.models import Notebook, ProactiveDigest, Project, User
from app.schemas.proactive import (
    AckResponse,
    DigestDetail,
    DigestListItem,
    GenerateNowRequest,
    PaginatedDigests,
)

router = APIRouter(prefix="/api/v1/digests", tags=["proactive"])


def _parse_cursor(cursor: str | None) -> datetime | None:
    if not cursor:
        return None
    try:
        return datetime.fromisoformat(cursor.replace("Z", "+00:00"))
    except ValueError:
        raise ApiError("invalid_input", "Bad cursor", status_code=400)


def _verify_workspace(db: Session, digest: ProactiveDigest, workspace_id: str) -> None:
    if digest.workspace_id != workspace_id:
        raise ApiError("not_found", "Digest not found", status_code=404)


@router.get("/unread-count")
def unread_count(
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
) -> dict[str, int]:
    n = (
        db.query(ProactiveDigest)
        .filter(ProactiveDigest.user_id == str(current_user.id))
        .filter(ProactiveDigest.workspace_id == workspace_id)
        .filter(ProactiveDigest.status == "unread")
        .count()
    )
    return {"unread_count": int(n)}


@router.get("", response_model=PaginatedDigests)
def list_digests(
    kind: str | None = None,
    status: str | None = None,
    limit: int = 20,
    cursor: str | None = None,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
) -> PaginatedDigests:
    limit = max(1, min(limit, 100))
    q = (
        db.query(ProactiveDigest)
        .filter(ProactiveDigest.user_id == str(current_user.id))
        .filter(ProactiveDigest.workspace_id == workspace_id)
    )
    if kind:
        q = q.filter(ProactiveDigest.kind == kind)
    if status:
        q = q.filter(ProactiveDigest.status == status)
    cur = _parse_cursor(cursor)
    if cur:
        q = q.filter(ProactiveDigest.created_at < cur)
    rows = q.order_by(ProactiveDigest.created_at.desc()).limit(limit + 1).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = rows[-1].created_at.isoformat() if rows and has_more else None

    unread_total = (
        db.query(ProactiveDigest)
        .filter(ProactiveDigest.user_id == str(current_user.id))
        .filter(ProactiveDigest.workspace_id == workspace_id)
        .filter(ProactiveDigest.status == "unread")
        .count()
    )

    return PaginatedDigests(
        items=[DigestListItem.model_validate(r, from_attributes=True) for r in rows],
        next_cursor=next_cursor,
        unread_count=int(unread_total),
    )


@router.get("/{digest_id}", response_model=DigestDetail)
def get_digest(
    digest_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
) -> DigestDetail:
    d = db.query(ProactiveDigest).filter_by(id=digest_id).first()
    if d is None:
        raise ApiError("not_found", "Digest not found", status_code=404)
    _verify_workspace(db, d, workspace_id)
    if str(d.user_id) != str(current_user.id):
        raise ApiError("not_found", "Digest not found", status_code=404)
    return DigestDetail.model_validate(d, from_attributes=True)


@router.post("/{digest_id}/read", response_model=AckResponse)
def mark_read(
    digest_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _: None = Depends(require_workspace_write_access),
    __: None = Depends(require_csrf_protection),
) -> AckResponse:
    d = db.query(ProactiveDigest).filter_by(id=digest_id).first()
    if d is None or d.workspace_id != workspace_id or str(d.user_id) != str(current_user.id):
        raise ApiError("not_found", "Digest not found", status_code=404)
    if d.status != "read":
        d.status = "read"
        d.read_at = datetime.now(timezone.utc)
        db.add(d); db.commit()
    return AckResponse(ok=True)


@router.post("/{digest_id}/dismiss", response_model=AckResponse)
def mark_dismissed(
    digest_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _: None = Depends(require_workspace_write_access),
    __: None = Depends(require_csrf_protection),
) -> AckResponse:
    d = db.query(ProactiveDigest).filter_by(id=digest_id).first()
    if d is None or d.workspace_id != workspace_id or str(d.user_id) != str(current_user.id):
        raise ApiError("not_found", "Digest not found", status_code=404)
    if d.status != "dismissed":
        d.status = "dismissed"
        d.dismissed_at = datetime.now(timezone.utc)
        db.add(d); db.commit()
    return AckResponse(ok=True)


@router.post("/generate-now")
def generate_now(
    payload: GenerateNowRequest,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _: None = Depends(require_workspace_write_access),
    __: None = Depends(require_csrf_protection),
) -> dict[str, Any]:
    project = db.query(Project).filter_by(id=payload.project_id).first()
    if project is None or project.workspace_id != workspace_id:
        raise ApiError("not_found", "Project not found", status_code=404)

    now = datetime.now(timezone.utc)
    if payload.kind == "daily_digest":
        period_start = now - timedelta(hours=24)
    elif payload.kind == "weekly_reflection":
        period_start = now - timedelta(days=7)
    elif payload.kind == "deviation_reminder":
        period_start = now - timedelta(days=7)
    elif payload.kind == "relationship_reminder":
        period_start = now - timedelta(days=30)
    else:
        raise ApiError("invalid_input", "Bad kind", status_code=400)

    from app.tasks.worker_tasks import generate_proactive_digest_task
    task = generate_proactive_digest_task.delay(
        payload.project_id, payload.kind,
        period_start.isoformat(), now.isoformat(),
    )
    return {"ok": True, "task_id": task.id if hasattr(task, "id") else None}
```

- [ ] **Step 4: Register the router in main.py**

Open `apps/api/app/main.py`. Add `proactive` to the routers import
and include the router:

```python
from app.routers import (
    ai_actions, attachments, auth, chat, datasets, memory, memory_stream,
    model_catalog, models, notebook_ai, notebooks, pipeline, proactive,
    projects, realtime, study, study_ai, study_decks, uploads,
)
```

And:

```python
app.include_router(proactive.router)
```

- [ ] **Step 5: Run to verify pass**

Run: `cd apps/api && .venv/bin/pytest tests/test_proactive_api.py -v`
Expected: 7 PASSED.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/routers/proactive.py apps/api/app/main.py apps/api/tests/test_proactive_api.py
git commit -m "feat(api): 6 proactive digests API endpoints + 7 tests"
```

---

### Task 8: Full backend regression

**Files:** none (verification)

- [ ] **Step 1: Run the full S5 backend suite**

```bash
cd apps/api && .venv/bin/pytest \
  tests/test_proactive_models.py \
  tests/test_reconfirm_candidates.py \
  tests/test_proactive_materials.py \
  tests/test_proactive_generator.py \
  tests/test_proactive_generator_task.py \
  tests/test_proactive_fanout_tasks.py \
  tests/test_proactive_api.py -v
```

Expected: ≈32 tests, all passed.

No commit.

---

### Task 9: WindowType `digest` plumbing

**Files:**
- Modify: `apps/web/components/notebook/WindowManager.tsx`
- Modify: `apps/web/components/notebook/Window.tsx`
- Modify: `apps/web/components/notebook/MinimizedTray.tsx`
- Modify: `apps/web/components/notebook/WindowCanvas.tsx`

- [ ] **Step 1: Extend `WindowType` + DEFAULT_SIZES**

Open `apps/web/components/notebook/WindowManager.tsx`. Replace:

```ts
export type WindowType =
  "note" | "ai_panel" | "file" | "memory" | "study";
```

with:

```ts
export type WindowType =
  "note" | "ai_panel" | "file" | "memory" | "study" | "digest";
```

Add to `DEFAULT_SIZES`:

```ts
  digest: { width: 520, height: 620 },
```

Do not change `supportsMultiOpen` — one digest window per notebook
is enough (matches the `chat` → `ai_panel` refactor's precedent).

- [ ] **Step 2: Icon in Window.tsx**

Open `apps/web/components/notebook/Window.tsx`. At the top, add
`Bell` to the `lucide-react` import. In the `WINDOW_ICONS` map,
add:

```ts
  digest: Bell,
```

- [ ] **Step 3: Icon in MinimizedTray.tsx**

Open `apps/web/components/notebook/MinimizedTray.tsx`. Same: add
`Bell` import and add `digest: Bell` to `TRAY_ICONS`.

- [ ] **Step 4: Dispatch in WindowCanvas**

Open `apps/web/components/notebook/WindowCanvas.tsx`. Add to the
`switch (windowState.type)` block a new case:

```tsx
    case "digest":
      return (
        <DigestWindow
          notebookId={windowState.meta.notebookId || ""}
        />
      );
```

At the top of the file, add the import — placeholder until Task 10
creates the real component. Create a stub so the build compiles:

Create `apps/web/components/notebook/contents/DigestWindow.tsx`:

```tsx
"use client";
interface Props { notebookId: string; }
export default function DigestWindow(_: Props) { return <div>DigestWindow (TODO)</div>; }
```

Then add the import in `WindowCanvas.tsx`:

```tsx
import DigestWindow from "./contents/DigestWindow";
```

- [ ] **Step 5: Typecheck**

Run: `cd apps/web && ./node_modules/.bin/tsc --noEmit 2>&1 | grep -iE "(WindowManager|Window\.tsx|MinimizedTray|WindowCanvas|DigestWindow)" | head -20`
Expected: no errors from these files.

- [ ] **Step 6: Commit**

```bash
git add apps/web/components/notebook/WindowManager.tsx apps/web/components/notebook/Window.tsx apps/web/components/notebook/MinimizedTray.tsx apps/web/components/notebook/WindowCanvas.tsx apps/web/components/notebook/contents/DigestWindow.tsx
git commit -m "refactor(web): add digest WindowType plumbing (placeholder content)"
```

---

### Task 10: DigestWindow + DigestList components

**Files:**
- Overwrite: `apps/web/components/notebook/contents/DigestWindow.tsx`
- Create: `apps/web/components/notebook/contents/digest/DigestList.tsx`
- Create: `apps/web/styles/digest-window.css`
- Modify: `apps/web/app/[locale]/workspace/notebooks/[notebookId]/layout.tsx`

- [ ] **Step 1: Create the list component**

Create `apps/web/components/notebook/contents/digest/DigestList.tsx`:

```tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import { Bell, Calendar, Flag, Users } from "lucide-react";
import { apiGet } from "@/lib/api";

interface Digest {
  id: string;
  kind: string;
  title: string;
  period_start: string;
  period_end: string;
  status: string;
  created_at: string;
}

interface Props {
  kind?: string;
  status?: string;
  onPick: (digest: Digest) => void;
}

const KIND_ICON: Record<string, React.ElementType> = {
  daily_digest: Calendar,
  weekly_reflection: Bell,
  deviation_reminder: Flag,
  relationship_reminder: Users,
};

function relTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const days = Math.floor(diff / 86400000);
  if (days === 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 7) return `${days}d ago`;
  return `${Math.floor(days / 7)}w ago`;
}

export default function DigestList({ kind, status, onPick }: Props) {
  const [items, setItems] = useState<Digest[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (kind) params.set("kind", kind);
      if (status) params.set("status", status);
      params.set("limit", "50");
      const data = await apiGet<{ items: Digest[]; next_cursor: string | null }>(
        `/api/v1/digests?${params.toString()}`,
      );
      setItems(data.items || []);
    } catch {
      setItems([]);
    }
    setLoading(false);
  }, [kind, status]);

  useEffect(() => { void load(); }, [load]);

  if (loading) {
    return <p style={{ padding: 12, fontSize: 12, color: "#888" }}>Loading…</p>;
  }

  if (items.length === 0) {
    return (
      <p style={{ padding: 12, fontSize: 12, color: "#888" }}>
        Nothing here yet.
      </p>
    );
  }

  return (
    <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
      {items.map((it) => {
        const Icon = KIND_ICON[it.kind] ?? Bell;
        return (
          <li
            key={it.id}
            data-testid="digest-list-item"
            onClick={() => onPick(it)}
            style={{
              padding: 10,
              borderBottom: "1px solid #eee",
              cursor: "pointer",
              display: "flex",
              gap: 8,
              alignItems: "flex-start",
            }}
          >
            <Icon size={16} style={{ marginTop: 2, flexShrink: 0, color: "#6b7280" }} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 13, fontWeight: 600, display: "flex", alignItems: "center", gap: 6 }}>
                {it.status === "unread" && (
                  <span
                    data-testid="digest-unread-dot"
                    style={{ width: 8, height: 8, borderRadius: 999, background: "#2563eb" }}
                  />
                )}
                {it.title}
              </div>
              <div style={{ fontSize: 11, color: "#9ca3af" }}>
                {it.kind} · {relTime(it.created_at)}
              </div>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
```

- [ ] **Step 2: Overwrite DigestWindow.tsx**

Overwrite `apps/web/components/notebook/contents/DigestWindow.tsx`:

```tsx
"use client";

import { useState } from "react";
import DigestList from "./digest/DigestList";
import DigestDetail from "./digest/DigestDetail";

type DigestTab = "today" | "week" | "all";

interface Props {
  notebookId: string;
}

export default function DigestWindow({ notebookId }: Props) {
  const [tab, setTab] = useState<DigestTab>("today");
  const [activeDigestId, setActiveDigestId] = useState<string | null>(null);

  const filters = (
    tab === "today" ? { kind: "daily_digest" as const } :
    tab === "week" ? { kind: "weekly_reflection" as const } :
    {}
  );

  if (activeDigestId) {
    return (
      <div className="digest-window" data-testid="digest-window">
        <DigestDetail
          digestId={activeDigestId}
          notebookId={notebookId}
          onBack={() => setActiveDigestId(null)}
        />
      </div>
    );
  }

  return (
    <div className="digest-window" data-testid="digest-window">
      <div className="digest-window__tabs" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={tab === "today"}
          data-testid="digest-tab-today"
          onClick={() => setTab("today")}
        >
          Today
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "week"}
          data-testid="digest-tab-week"
          onClick={() => setTab("week")}
        >
          This week
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "all"}
          data-testid="digest-tab-all"
          onClick={() => setTab("all")}
        >
          All
        </button>
      </div>
      <div className="digest-window__body">
        <DigestList
          kind={filters.kind}
          onPick={(d) => setActiveDigestId(d.id)}
        />
      </div>
    </div>
  );
}
```

Note: `DigestDetail` doesn't exist yet — add a tiny placeholder so
this compiles. Create
`apps/web/components/notebook/contents/digest/DigestDetail.tsx`:

```tsx
"use client";
interface Props { digestId: string; notebookId: string; onBack: () => void; }
export default function DigestDetail(_: Props) { return <div>DigestDetail (TODO)</div>; }
```

Task 11 overwrites.

- [ ] **Step 3: Create CSS**

Create `apps/web/styles/digest-window.css`:

```css
.digest-window {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #ffffff;
}

.digest-window__tabs {
  display: flex;
  gap: 2px;
  padding: 6px 8px 0;
  border-bottom: 1px solid #e5e7eb;
  flex-shrink: 0;
}

.digest-window__tabs button {
  padding: 6px 12px;
  font-size: 12px;
  font-weight: 500;
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  cursor: pointer;
  color: #6b7280;
}

.digest-window__tabs button[aria-selected="true"] {
  color: #111827;
  border-bottom-color: #2563eb;
  font-weight: 600;
}

.digest-window__body {
  flex: 1;
  overflow: auto;
  min-height: 0;
}

.digest-detail {
  padding: 16px;
  overflow: auto;
  height: 100%;
}

.digest-detail__back {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: none;
  border: none;
  color: #6b7280;
  cursor: pointer;
  padding: 4px 0;
  font-size: 12px;
}

.digest-detail__title {
  font-size: 16px;
  font-weight: 700;
  margin: 8px 0 4px;
}

.digest-detail__meta {
  font-size: 11px;
  color: #9ca3af;
  margin-bottom: 12px;
}

.digest-detail__body p,
.digest-detail__body ul {
  font-size: 13px;
  line-height: 1.55;
}
```

- [ ] **Step 4: Import the CSS in the notebook layout**

Open `apps/web/app/[locale]/workspace/notebooks/[notebookId]/layout.tsx`.
Add alongside existing CSS imports:

```tsx
import "@/styles/digest-window.css";
```

- [ ] **Step 5: Commit**

```bash
git add apps/web/components/notebook/contents/DigestWindow.tsx apps/web/components/notebook/contents/digest/DigestList.tsx apps/web/components/notebook/contents/digest/DigestDetail.tsx apps/web/styles/digest-window.css apps/web/app/[locale]/workspace/notebooks/[notebookId]/layout.tsx
git commit -m "feat(web): DigestWindow tab shell + DigestList + CSS"
```

---

### Task 11: DigestDetail component

**Files:**
- Overwrite: `apps/web/components/notebook/contents/digest/DigestDetail.tsx`

- [ ] **Step 1: Overwrite**

```tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import { ArrowLeft, X } from "lucide-react";
import ReactMarkdown from "react-markdown";
import { apiGet, apiPost } from "@/lib/api";
import { useWindowManager } from "@/components/notebook/WindowManager";

interface Detail {
  id: string;
  kind: string;
  title: string;
  content_markdown: string;
  content_json: Record<string, unknown>;
  status: string;
  created_at: string;
  period_start: string;
  period_end: string;
}

interface Props {
  digestId: string;
  notebookId: string;
  onBack: () => void;
}

export default function DigestDetail({ digestId, notebookId, onBack }: Props) {
  const [detail, setDetail] = useState<Detail | null>(null);
  const { openWindow } = useWindowManager();

  useEffect(() => {
    void apiGet<Detail>(`/api/v1/digests/${digestId}`)
      .then((d) => {
        setDetail(d);
        if (d.status === "unread") {
          void apiPost(`/api/v1/digests/${d.id}/read`, {});
        }
      })
      .catch(() => setDetail(null));
  }, [digestId]);

  const handleDismiss = useCallback(async () => {
    if (!detail) return;
    await apiPost(`/api/v1/digests/${detail.id}/dismiss`, {});
    onBack();
  }, [detail, onBack]);

  const handleOpenPage = useCallback(
    (pageId: string) => {
      openWindow({
        type: "note",
        title: "Page",
        meta: { notebookId, pageId },
      });
    },
    [notebookId, openWindow],
  );

  if (!detail) {
    return <p style={{ padding: 16, fontSize: 12, color: "#888" }}>Loading…</p>;
  }

  const nextActions =
    (detail.content_json?.next_actions as Array<{
      page_id: string; title: string; hint: string;
    }> | undefined) ?? [];
  const reconfirmItems =
    (detail.content_json?.reconfirm_items as Array<{
      memory_id: string; fact: string; age_days: number;
    }> | undefined) ?? [];

  return (
    <div className="digest-detail" data-testid="digest-detail">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <button
          type="button"
          onClick={onBack}
          className="digest-detail__back"
          data-testid="digest-detail-back"
        >
          <ArrowLeft size={14} /> Back
        </button>
        <button
          type="button"
          onClick={() => void handleDismiss()}
          className="digest-detail__back"
          data-testid="digest-detail-dismiss"
        >
          <X size={14} /> Dismiss
        </button>
      </div>
      <h2 className="digest-detail__title">{detail.title}</h2>
      <p className="digest-detail__meta">
        {detail.kind} · {detail.created_at.slice(0, 10)}
      </p>
      <div className="digest-detail__body">
        <ReactMarkdown>{detail.content_markdown || "(empty)"}</ReactMarkdown>
      </div>

      {nextActions.length > 0 && (
        <>
          <h3 style={{ fontSize: 13, marginTop: 16 }}>Next actions</h3>
          <ul style={{ listStyle: "none", padding: 0 }}>
            {nextActions.map((a, i) => (
              <li key={i} style={{ padding: 6, borderBottom: "1px solid #eee" }}>
                <button
                  type="button"
                  onClick={() => handleOpenPage(a.page_id)}
                  data-testid="digest-next-action"
                  style={{
                    background: "none", border: "none",
                    cursor: "pointer", color: "#2563eb",
                    fontSize: 12, padding: 0, textAlign: "left",
                  }}
                >
                  {a.title}
                </button>
                <div style={{ fontSize: 11, color: "#6b7280" }}>{a.hint}</div>
              </li>
            ))}
          </ul>
        </>
      )}

      {reconfirmItems.length > 0 && (
        <>
          <h3 style={{ fontSize: 13, marginTop: 16 }}>Memories to reconfirm</h3>
          <ul style={{ listStyle: "none", padding: 0 }}>
            {reconfirmItems.map((m, i) => (
              <li key={i} style={{ padding: 6, borderBottom: "1px solid #eee", fontSize: 12 }}>
                <strong>{m.fact}</strong>
                <div style={{ color: "#6b7280", fontSize: 11 }}>
                  {m.age_days}d old · {m.memory_id.slice(0, 8)}
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Typecheck**

Run: `cd apps/web && ./node_modules/.bin/tsc --noEmit 2>&1 | grep -i "DigestDetail" | head -5`
Expected: no errors from this file.

- [ ] **Step 3: Commit**

```bash
git add apps/web/components/notebook/contents/digest/DigestDetail.tsx
git commit -m "feat(web): DigestDetail — markdown, next_actions, reconfirm list, auto-read"
```

---

### Task 12: Sidebar Bell + `useDigestUnreadCount` hook

**Files:**
- Create: `apps/web/hooks/useDigestUnreadCount.ts`
- Modify: `apps/web/components/console/NotebookSidebar.tsx`
- Modify: `apps/web/messages/en/console-notebooks.json` +
  `apps/web/messages/zh/console-notebooks.json`

- [ ] **Step 1: Create the hook**

Create `apps/web/hooks/useDigestUnreadCount.ts`:

```ts
"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";

export function useDigestUnreadCount(): number {
  const [count, setCount] = useState(0);

  useEffect(() => {
    let cancelled = false;
    async function tick() {
      try {
        const r = await apiGet<{ unread_count: number }>(
          "/api/v1/digests/unread-count",
        );
        if (!cancelled) setCount(r.unread_count);
      } catch {
        /* swallow */
      }
    }
    void tick();
    const handle = setInterval(tick, 30_000);
    return () => {
      cancelled = true;
      clearInterval(handle);
    };
  }, []);

  return count;
}
```

- [ ] **Step 2: Update NotebookSidebar.tsx**

Open `apps/web/components/console/NotebookSidebar.tsx`. Add `Bell`
to the `lucide-react` import. Extend the `SideTab` union (line ~19)
and the `TABS` array (line ~25):

```tsx
type SideTab = "pages" | "ai_panel" | "memory" | "learn" | "digest" | null;

const TABS = [
  { id: "pages" as const, Icon: FileText, key: "nav.pages" },
  { id: "ai_panel" as const, Icon: Sparkles, key: "nav.aiPanel" },
  { id: "memory" as const, Icon: Brain, key: "nav.memory" },
  { id: "learn" as const, Icon: BookOpen, key: "nav.learn" },
  { id: "digest" as const, Icon: Bell, key: "nav.digest" },
] as const;
```

Add the hook import:

```tsx
import { useDigestUnreadCount } from "@/hooks/useDigestUnreadCount";
```

Inside the component, call the hook:

```tsx
const unreadCount = useDigestUnreadCount();
```

Add a `"digest"` branch to the existing `handleTabClick`:

```tsx
} else if (tabId === "digest") {
  openWindow({
    type: "digest",
    title: tn("digest.windowTitle"),
    meta: { notebookId },
  });
}
```

Render the badge. Find where the TABS array is iterated (the nav
cluster). Replace the existing `<tab.Icon …/>` render with:

```tsx
{TABS.map((tab) => (
  <button
    key={tab.id}
    type="button"
    data-testid={`sidebar-tab-${tab.id}`}
    className={`glass-sidebar-nav-item${
      isRouteActive(tab.id) || activeTab === tab.id ? " is-active" : ""
    }`}
    title={t(tab.key)}
    aria-label={t(tab.key)}
    onClick={() => handleTabClick(tab.id)}
    style={{ position: "relative" }}
  >
    <tab.Icon size={20} strokeWidth={1.8} />
    {tab.id === "digest" && unreadCount > 0 && (
      <span
        data-testid="sidebar-digest-badge"
        style={{
          position: "absolute",
          top: 4,
          right: 4,
          minWidth: 14,
          height: 14,
          borderRadius: 999,
          background: "#ef4444",
          color: "#fff",
          fontSize: 9,
          lineHeight: "14px",
          textAlign: "center",
          padding: "0 3px",
          fontWeight: 700,
        }}
      >
        {unreadCount > 99 ? "99+" : unreadCount}
      </span>
    )}
  </button>
))}
```

- [ ] **Step 3: Add i18n keys**

Open `apps/web/messages/en/console-notebooks.json`. Find the
`settings.projectId` entry near the bottom; add before the closing `}`:

```json
  ,
  "nav.digest": "Digest",
  "digest.windowTitle": "Proactive digest"
```

Adjust the preceding line's comma accordingly (the current last line
is `"settings.projectId": "Project ID"` without a trailing comma —
add the comma and then the two new keys).

Apply the equivalent to `zh/console-notebooks.json`:

```json
  ,
  "nav.digest": "摘要",
  "digest.windowTitle": "主动摘要"
```

Also check whether a namespace `"console"` file in
`apps/web/messages/en/*.json` or `zh/*.json` is the one that
actually owns `nav.*` keys. If `nav.pages` lives in `console.json`
(not `console-notebooks.json`), add `nav.digest` to that file
instead. Inspect:

```bash
grep -l '"nav.memory"' apps/web/messages/en/*.json
```

Add the key to whichever file returned.

- [ ] **Step 4: Typecheck**

Run: `cd apps/web && ./node_modules/.bin/tsc --noEmit 2>&1 | grep -iE "(NotebookSidebar|useDigestUnreadCount)" | head -5`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add apps/web/hooks/useDigestUnreadCount.ts apps/web/components/console/NotebookSidebar.tsx apps/web/messages
git commit -m "feat(web): sidebar Bell + unread-count badge for digests"
```

---

### Task 13: Playwright smoke + vitest unit for DigestList

**Files:**
- Create: `apps/web/tests/unit/digest-list.test.tsx`
- Create: `apps/web/tests/s5-digest.spec.ts`

- [ ] **Step 1: vitest for DigestList**

Create `apps/web/tests/unit/digest-list.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import DigestList from "@/components/notebook/contents/digest/DigestList";

afterEach(() => {
  vi.restoreAllMocks();
});

const SAMPLE = [
  {
    id: "d1", kind: "daily_digest", title: "Daily",
    period_start: "2026-04-17T00:00:00Z", period_end: "2026-04-18T00:00:00Z",
    status: "unread",
    created_at: new Date(Date.now() - 1000).toISOString(),
  },
  {
    id: "d2", kind: "weekly_reflection", title: "Week",
    period_start: "2026-04-10T00:00:00Z", period_end: "2026-04-17T00:00:00Z",
    status: "read",
    created_at: new Date(Date.now() - 86400_000 * 2).toISOString(),
  },
];


function mockFetch(items: typeof SAMPLE) {
  global.fetch = vi.fn(async (url: string | URL) => {
    if (String(url).includes("/api/v1/digests")) {
      return {
        ok: true,
        status: 200,
        json: async () => ({ items, next_cursor: null, unread_count: items.filter(i=>i.status==="unread").length }),
      } as Response;
    }
    throw new Error("unexpected fetch " + url);
  }) as typeof fetch;
}


describe("DigestList", () => {
  it("renders each item and shows the unread dot for unread rows", async () => {
    mockFetch(SAMPLE);
    const onPick = vi.fn();
    render(<DigestList onPick={onPick} />);
    // wait for load
    await screen.findByText("Daily");
    expect(screen.getByText("Week")).toBeInTheDocument();
    const unreadDots = screen.getAllByTestId("digest-unread-dot");
    expect(unreadDots).toHaveLength(1);
  });

  it("renders empty state when api returns no items", async () => {
    mockFetch([]);
    const onPick = vi.fn();
    render(<DigestList onPick={onPick} />);
    await screen.findByText(/Nothing here/i);
  });
});
```

**Note**: `apiGet` internally calls `fetch`. If the codebase's
`apiGet` wraps the URL with a base or adds headers, the mock above
should still catch the call via URL substring match. If the test
setup needs adjustments (e.g., JSDOM's `fetch` not recognized),
refer to how `window-persistence.test.ts` handles global mocks and
adapt.

- [ ] **Step 2: Playwright spec**

Create `apps/web/tests/s5-digest.spec.ts`:

```ts
import { test, expect } from "@playwright/test";

test.describe("S5 Proactive digest", () => {
  test("sidebar Bell surfaces unread digest → open → dismiss", async ({ page, request }) => {
    // Log in by navigating through the app; adapt to the repo's
    // existing auth helper if present.
    await page.goto("/workspace/notebooks");
    await page.getByRole("button", { name: /create/i }).first().click();
    await page.waitForURL(/\/workspace\/notebooks\/[^/]+$/);
    // Ensure a note exists so the notebook has a page for the digest
    // background to reference. The smoke's goal is the UI chain; the
    // digest row is seeded via the API below.

    // Seed a digest via generate-now → the Celery task runs eagerly
    // under test mode (Celery eager configured globally).
    // In this repo Celery may not be eager; if the row doesn't appear
    // within 10s, mark the test as needing full-stack.
    // (Skeleton — real execution requires the dev stack.)
    await page.getByTestId("sidebar-tab-digest").click();
    await expect(page.getByTestId("digest-window")).toBeVisible();
  });
});
```

(The smoke is intentionally minimal — Playwright requires the full
stack and Celery eager mode to fully exercise; the test is a sanity
check that the window opens.)

- [ ] **Step 3: Typecheck**

Run: `cd apps/web && ./node_modules/.bin/tsc --noEmit 2>&1 | grep -iE "(digest-list|s5-digest)" | head -5`
Expected: no errors from new files.

- [ ] **Step 4: Run vitest**

Run: `cd apps/web && ./node_modules/.bin/vitest run tests/unit/digest-list.test.tsx -v`
Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add apps/web/tests/unit/digest-list.test.tsx apps/web/tests/s5-digest.spec.ts
git commit -m "test(web): vitest for DigestList + Playwright smoke skeleton"
```

---

### Task 14: Final coverage verification

No commit.

- [ ] **Step 1: Backend coverage**

```bash
cd apps/api && .venv/bin/pytest \
  tests/test_proactive_models.py \
  tests/test_reconfirm_candidates.py \
  tests/test_proactive_materials.py \
  tests/test_proactive_generator.py \
  tests/test_proactive_generator_task.py \
  tests/test_proactive_fanout_tasks.py \
  tests/test_proactive_api.py \
  --cov=app.services.proactive_materials \
  --cov=app.services.proactive_generator \
  --cov=app.routers.proactive \
  --cov-report=term 2>&1 | tail -15
```

Expected: ≥80% line coverage on the three modules.

- [ ] **Step 2: Vitest**

```bash
cd apps/web && ./node_modules/.bin/vitest run 2>&1 | tail -10
```

Expected: all pre-existing + 2 new tests pass.

- [ ] **Step 3: Typecheck**

```bash
cd apps/web && ./node_modules/.bin/tsc --noEmit 2>&1 | tail -10
```

Expected: only the pre-existing WhiteboardBlock error; no new
errors from any S5 file.

- [ ] **Step 4: Report summary**

Produce a short report listing:
- all 13 task commits
- backend coverage per module
- vitest pass count
- any typecheck issues from S5 code

No commit.

---

## Final Acceptance Checklist

- [ ] `alembic upgrade head` creates `proactive_digests` with the
  unique constraint and two composite indexes.
- [ ] `POST /api/v1/digests/generate-now` with a valid project_id
  enqueues a Celery task and returns 200.
- [ ] Running `generate_daily_digests_task.run()` manually fans out
  to all active projects; running again in the same hour produces
  zero new rows (idempotency).
- [ ] `generate_weekly_reflections_task` fills
  `content_json.stats.cards_reviewed` for projects with S4
  StudyCard reviews.
- [ ] `generate_deviation_reminders_task` with a canned LLM response
  `{"drifts":[{...}]}` inserts one `deviation_reminder` row per
  drift.
- [ ] `generate_relationship_reminders_task` on a project with a
  person-subject memory whose latest evidence is 40 days old
  inserts one `relationship_reminder` row.
- [ ] Sidebar Bell shows the unread badge; clicking opens the
  DigestWindow; opening a digest marks it read; dismiss works.
- [ ] `pytest tests/test_proactive*` + `test_reconfirm_candidates.py`
  passes with ≥80% coverage on the three target modules.
- [ ] `vitest run tests/unit/digest-list.test.tsx` passes.
- [ ] No regressions on S1–S4 test suites.

## Cross-references

- Spec: `docs/superpowers/specs/2026-04-18-proactive-services-design.md`
- Product spec: `MRAI_notebook_ai_os_build_spec.md` §3.5, §14.4
