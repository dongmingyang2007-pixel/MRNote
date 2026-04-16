# S4 — Study Closure — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the study loop — persistent `StudyDeck`/`StudyCard`
with FSRS scheduling, AI-generated flashcards and MCQ quizzes, a
study-scoped `ask` endpoint, review loop with 4-grade rating, and
confusion-signal memory writes via the UnifiedMemoryPipeline.

**Architecture:** Two new tables + a small FSRS scheduler in Python.
Deck/Card CRUD is a dedicated router. Review endpoint updates FSRS
state in-place and fires a Celery task that writes a
`study_confusion` memory evidence when the user keeps failing a card
(or explicitly marks it). Three AI endpoints (flashcards / quiz / ask)
follow the S1 `action_log_context` pattern. Frontend extends
`StudyWindow` into a tab shell hosting Assets / Decks / Review panels.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2, Alembic,
pytest-cov, Celery, Next.js 14, React 18, TypeScript, TipTap 3,
vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-04-17-study-closure-design.md`

---

## Phase Overview

| Phase | Tasks | Scope |
|---|---|---|
| **A** | 1 | FSRS service + unit tests |
| **B** | 2 | StudyDeck / StudyCard models + migration + Pydantic schemas + ORM smoke |
| **C** | 3–4 | Deck CRUD router + Card CRUD router + 5 API tests |
| **D** | 5–6 | `review/next` + `review` endpoints + FSRS wiring + 4 tests |
| **E** | 7–8 | `study_confusion` source_type + Celery task + 2 tests |
| **F** | 9–11 | 3 AI endpoints (`flashcards` / `quiz` / `ask`) + study_context helper + 4 tests |
| **G** | 12 | main.py router registration + final backend verification |
| **H** | 13–14 | StudyWindow tab shell + AssetsPanel lift |
| **I** | 15–17 | DecksPanel + CardsPanel + ReviewSession components |
| **J** | 18–19 | GenerateFlashcardsModal + QuizModal |
| **K** | 20 | FlashcardBlock "Add to Deck" wiring |
| **L** | 21 | i18n strings + CSS |
| **M** | 22 | Playwright smoke |
| **N** | 23 | Coverage verification |

---

### Task 1: FSRS scheduler service + unit tests

**Files:**
- Create: `apps/api/app/services/fsrs.py`
- Create: `apps/api/tests/test_fsrs.py`

- [ ] **Step 1: Write the failing tests**

Create `apps/api/tests/test_fsrs.py`:

```python
# ruff: noqa: E402
import math
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ["ENV"] = "test"

import pytest
from app.services.fsrs import FSRSUpdate, schedule_next


def test_new_card_rating_good_seeds_from_table() -> None:
    out = schedule_next(difficulty=0, stability=0, rating=3, days_since_last_review=0)
    assert isinstance(out, FSRSUpdate)
    assert out.difficulty == 5.0
    assert math.isclose(out.stability, 2.3, rel_tol=1e-6)
    assert out.next_interval_days == 2


def test_new_card_rating_again_seeds_short() -> None:
    out = schedule_next(difficulty=0, stability=0, rating=1, days_since_last_review=0)
    assert out.difficulty == 8.0
    assert math.isclose(out.stability, 0.4, rel_tol=1e-6)
    assert out.next_interval_days == 1


def test_existing_card_rating_good_grows_stability() -> None:
    out = schedule_next(
        difficulty=5.0, stability=2.3, rating=3, days_since_last_review=2.0,
    )
    assert out.stability > 2.3
    assert out.next_interval_days >= 3


def test_existing_card_rating_again_shrinks_stability() -> None:
    out = schedule_next(
        difficulty=5.0, stability=10.0, rating=1, days_since_last_review=10.0,
    )
    assert out.stability < 2.5
    assert out.difficulty > 5.0  # difficulty rises on lapse


def test_rating_out_of_range_raises() -> None:
    with pytest.raises(ValueError):
        schedule_next(difficulty=5, stability=5, rating=0, days_since_last_review=1)
    with pytest.raises(ValueError):
        schedule_next(difficulty=5, stability=5, rating=5, days_since_last_review=1)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && .venv/bin/pytest tests/test_fsrs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.fsrs'`.

- [ ] **Step 3: Create the service**

Create `apps/api/app/services/fsrs.py`:

```python
"""Simplified FSRS-4.5 spaced-repetition scheduler.

Public surface:
    schedule_next(difficulty, stability, rating, days_since_last_review)
        -> FSRSUpdate(difficulty, stability, next_interval_days)

Rating convention: 1=Again, 2=Hard, 3=Good, 4=Easy.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

_INITIAL_STABILITY = [0.4, 0.9, 2.3, 10.9]  # days, indexed by rating-1
_INITIAL_DIFFICULTY = [8.0, 6.0, 5.0, 3.0]

_RATING_FACTORS = {2: 0.5, 3: 1.0, 4: 1.3}  # for non-lapse ratings
_FACTOR_W = 3.0
_RETENTION_TARGET = 0.9

_MIN_STABILITY = 0.1  # days — avoid zero decay


@dataclass(frozen=True)
class FSRSUpdate:
    difficulty: float
    stability: float
    next_interval_days: int


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def schedule_next(
    *,
    difficulty: float,
    stability: float,
    rating: int,
    days_since_last_review: float,
) -> FSRSUpdate:
    """Advance a card's scheduling state after a review."""
    if rating < 1 or rating > 4:
        raise ValueError("rating must be 1-4")

    # New card — seed state from rating-indexed tables
    if stability <= 0.0:
        new_difficulty = _INITIAL_DIFFICULTY[rating - 1]
        new_stability = max(_MIN_STABILITY, _INITIAL_STABILITY[rating - 1])
        return FSRSUpdate(
            difficulty=new_difficulty,
            stability=new_stability,
            next_interval_days=max(1, round(new_stability)),
        )

    # Difficulty update
    difficulty_delta = (5 - rating) * 0.3
    new_difficulty = _clamp(difficulty + difficulty_delta, 1.0, 10.0)

    # Stability update
    if rating == 1:
        # Lapse — shrink stability aggressively
        new_stability = max(
            _MIN_STABILITY,
            stability * 0.2 * math.exp(-0.05 * new_difficulty),
        )
    else:
        retrievability = math.exp(
            math.log(_RETENTION_TARGET)
            * days_since_last_review
            / max(stability, _MIN_STABILITY)
        )
        factor = 1.0 + (
            math.exp(_FACTOR_W)
            * (11.0 - new_difficulty)
            * math.pow(stability, -0.3)
            * (math.exp((1.0 - retrievability) * 0.6) - 1.0)
            * _RATING_FACTORS[rating]
        )
        new_stability = max(_MIN_STABILITY, stability * factor)

    return FSRSUpdate(
        difficulty=new_difficulty,
        stability=new_stability,
        next_interval_days=max(1, round(new_stability)),
    )
```

- [ ] **Step 4: Run to verify pass**

Run: `cd apps/api && .venv/bin/pytest tests/test_fsrs.py -v`
Expected: 5 PASSED.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/services/fsrs.py apps/api/tests/test_fsrs.py
git commit -m "feat(api): FSRS-4.5 simplified scheduler for S4 study cards"
```

---

### Task 2: StudyDeck + StudyCard models + migration + schemas

**Files:**
- Modify: `apps/api/app/models/entities.py`
- Modify: `apps/api/app/models/__init__.py`
- Create: `apps/api/alembic/versions/202604180001_study_decks_cards.py`
- Create: `apps/api/app/schemas/study_decks.py`
- Create: `apps/api/tests/test_study_decks_models.py`

- [ ] **Step 1: Write the failing model smoke test**

Create `apps/api/tests/test_study_decks_models.py`:

```python
# ruff: noqa: E402
import atexit, os, shutil, tempfile
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-s4-models-"))
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
    Notebook, NotebookPage, Project, StudyCard, StudyDeck, User, Workspace,
)


def setup_function() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _seed() -> str:
    with SessionLocal() as db:
        ws = Workspace(name="W"); user = User(email="u@x.co", password_hash="x")
        db.add(ws); db.add(user); db.commit(); db.refresh(ws); db.refresh(user)
        pr = Project(workspace_id=ws.id, name="P"); db.add(pr); db.commit(); db.refresh(pr)
        nb = Notebook(workspace_id=ws.id, project_id=pr.id, created_by=user.id,
                      title="NB", slug="nb")
        db.add(nb); db.commit(); db.refresh(nb)
        return nb.id, user.id


def test_deck_and_card_roundtrip() -> None:
    nb_id, user_id = _seed()
    with SessionLocal() as db:
        deck = StudyDeck(notebook_id=nb_id, name="My deck", created_by=user_id)
        db.add(deck); db.commit(); db.refresh(deck)

        card = StudyCard(
            deck_id=deck.id, front="Q", back="A",
            source_type="manual",
        )
        db.add(card); db.commit(); db.refresh(card)

        # Defaults
        assert card.difficulty == 5.0
        assert card.stability == 0.0
        assert card.review_count == 0
        assert card.consecutive_failures == 0
        assert card.confusion_memory_written_at is None
        assert card.next_review_at is None
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && .venv/bin/pytest tests/test_study_decks_models.py -v`
Expected: FAIL — `ImportError: cannot import name 'StudyDeck' from 'app.models'`.

- [ ] **Step 3: Add the ORM classes**

Open `apps/api/app/models/entities.py`. After the existing `StudyChunk`
class (around line 649), append two new classes before the trailing
`Index(...)` block:

```python
class StudyDeck(Base, UUIDPrimaryKeyMixin, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "study_decks"

    notebook_id: Mapped[str] = mapped_column(
        ForeignKey("notebooks.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    card_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_by: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class StudyCard(Base, UUIDPrimaryKeyMixin, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "study_cards"

    deck_id: Mapped[str] = mapped_column(
        ForeignKey("study_decks.id", ondelete="CASCADE"), index=True
    )
    front: Mapped[str] = mapped_column(Text, nullable=False)
    back: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(
        String(20), default="manual", nullable=False
    )
    source_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    difficulty: Mapped[float] = mapped_column(Float, default=5.0, nullable=False)
    stability: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    last_review_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_review_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    review_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    lapse_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    confusion_memory_written_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
```

Also add the composite indexes alongside the other `Index(...)` calls
at the bottom of the file:

```python
Index(
    "ix_study_cards_deck_due",
    StudyCard.deck_id,
    StudyCard.next_review_at.asc(),
)
Index(
    "ix_study_cards_deck_created",
    StudyCard.deck_id,
    StudyCard.created_at.desc(),
)
```

- [ ] **Step 4: Export from `app.models`**

Open `apps/api/app/models/__init__.py`. Add `StudyCard` and `StudyDeck`
to both the `from app.models.entities import (...)` block (alphabetical,
between `StudyAsset` and `StudyChunk`) and the `__all__` list.

- [ ] **Step 5: Create the Alembic migration**

Create `apps/api/alembic/versions/202604180001_study_decks_cards.py`:

```python
"""study_decks and study_cards (S4)

Revision ID: 202604180001
Revises: 202604170001
Create Date: 2026-04-18
"""

from alembic import op


revision = "202604180001"
down_revision = "202604170001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS study_decks (
            id             VARCHAR(36) PRIMARY KEY,
            notebook_id    VARCHAR(36) NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
            name           VARCHAR(120) NOT NULL,
            description    TEXT NOT NULL DEFAULT '',
            card_count     INTEGER NOT NULL DEFAULT 0,
            created_by     VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            archived_at    TIMESTAMPTZ,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE INDEX IF NOT EXISTS ix_study_decks_notebook_id
            ON study_decks(notebook_id);

        CREATE TABLE IF NOT EXISTS study_cards (
            id                          VARCHAR(36) PRIMARY KEY,
            deck_id                     VARCHAR(36) NOT NULL REFERENCES study_decks(id) ON DELETE CASCADE,
            front                       TEXT NOT NULL,
            back                        TEXT NOT NULL,
            source_type                 VARCHAR(20) NOT NULL DEFAULT 'manual',
            source_ref                  VARCHAR(64),
            difficulty                  DOUBLE PRECISION NOT NULL DEFAULT 5.0,
            stability                   DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            last_review_at              TIMESTAMPTZ,
            next_review_at              TIMESTAMPTZ,
            review_count                INTEGER NOT NULL DEFAULT 0,
            lapse_count                 INTEGER NOT NULL DEFAULT 0,
            consecutive_failures        INTEGER NOT NULL DEFAULT 0,
            confusion_memory_written_at TIMESTAMPTZ,
            created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE INDEX IF NOT EXISTS ix_study_cards_deck_id
            ON study_cards(deck_id);
        CREATE INDEX IF NOT EXISTS ix_study_cards_deck_due
            ON study_cards(deck_id, next_review_at ASC);
        CREATE INDEX IF NOT EXISTS ix_study_cards_deck_created
            ON study_cards(deck_id, created_at DESC);
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS study_cards CASCADE;
        DROP TABLE IF EXISTS study_decks CASCADE;
    """)
```

- [ ] **Step 6: Add Pydantic schemas**

Create `apps/api/app/schemas/study_decks.py`:

```python
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class DeckCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str = ""


class DeckPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    archived: bool | None = None


class DeckOut(BaseModel):
    id: str
    notebook_id: str
    name: str
    description: str
    card_count: int
    created_by: str
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PaginatedDecks(BaseModel):
    items: list[DeckOut]
    total: int


class CardCreate(BaseModel):
    front: str = Field(..., min_length=1)
    back: str = Field(..., min_length=1)
    source_type: str = "manual"
    source_ref: str | None = None


class CardPatch(BaseModel):
    front: str | None = Field(default=None, min_length=1)
    back: str | None = Field(default=None, min_length=1)


class CardOut(BaseModel):
    id: str
    deck_id: str
    front: str
    back: str
    source_type: str
    source_ref: str | None
    difficulty: float
    stability: float
    last_review_at: datetime | None
    next_review_at: datetime | None
    review_count: int
    lapse_count: int
    consecutive_failures: int
    created_at: datetime
    updated_at: datetime


class ReviewRequest(BaseModel):
    rating: int = Field(..., ge=1, le=4)
    marked_confused: bool = False


class ReviewResponse(BaseModel):
    ok: bool = True
    next_review_at: datetime | None
    consecutive_failures: int
```

- [ ] **Step 7: Run to verify pass**

Run: `cd apps/api && .venv/bin/pytest tests/test_study_decks_models.py -v`
Expected: 1 PASSED.

- [ ] **Step 8: Commit**

```bash
git add apps/api/app/models/entities.py apps/api/app/models/__init__.py apps/api/alembic/versions/202604180001_study_decks_cards.py apps/api/app/schemas/study_decks.py apps/api/tests/test_study_decks_models.py
git commit -m "feat(api): StudyDeck + StudyCard models, migration, and Pydantic schemas"
```

---

### Task 3: Deck CRUD router + 3 API tests

**Files:**
- Create: `apps/api/app/routers/study_decks.py`
- Create: `apps/api/tests/test_study_decks_api.py`
- Modify: `apps/api/app/main.py` (include router — done here inline)

- [ ] **Step 1: Write failing tests**

Create `apps/api/tests/test_study_decks_api.py`:

```python
# ruff: noqa: E402
import atexit, importlib, os, shutil, tempfile
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-s4-decks-api-"))
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
from app.models import Notebook, Project, StudyDeck, User, Workspace


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
    csrf = client.get("/api/v1/auth/csrf", headers=_public_headers()).json()["csrf_token"]
    client.headers.update({
        "origin": "http://localhost:3000",
        "x-csrf-token": csrf,
        "x-workspace-id": info["workspace"]["id"],
    })
    return client, {"ws_id": info["workspace"]["id"], "user_id": info["user"]["id"]}


def _seed_notebook(ws_id: str, user_id: str) -> str:
    with SessionLocal() as db:
        pr = Project(workspace_id=ws_id, name="P"); db.add(pr); db.commit(); db.refresh(pr)
        nb = Notebook(workspace_id=ws_id, project_id=pr.id, created_by=user_id,
                      title="NB", slug="nb")
        db.add(nb); db.commit(); db.refresh(nb)
        return nb.id


def test_create_and_list_decks() -> None:
    client, auth = _register_client("u1@x.co")
    nb_id = _seed_notebook(auth["ws_id"], auth["user_id"])

    resp = client.post(
        f"/api/v1/notebooks/{nb_id}/decks",
        json={"name": "My deck", "description": "test"},
    )
    assert resp.status_code == 200, resp.text
    created = resp.json()
    assert created["name"] == "My deck"
    assert created["card_count"] == 0

    list_resp = client.get(f"/api/v1/notebooks/{nb_id}/decks")
    assert list_resp.status_code == 200
    body = list_resp.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == created["id"]


def test_patch_deck_rename_and_archive() -> None:
    client, auth = _register_client("u2@x.co")
    nb_id = _seed_notebook(auth["ws_id"], auth["user_id"])
    deck = client.post(
        f"/api/v1/notebooks/{nb_id}/decks",
        json={"name": "before", "description": ""},
    ).json()

    patched = client.patch(
        f"/api/v1/decks/{deck['id']}",
        json={"name": "after", "archived": True},
    ).json()
    assert patched["name"] == "after"
    assert patched["archived_at"] is not None


def test_cross_workspace_deck_access_404() -> None:
    # Owner creates a deck.
    _client_a, auth_a = _register_client("a@x.co")
    nb_id = _seed_notebook(auth_a["ws_id"], auth_a["user_id"])
    # Use _client_a directly so we need to make it again to POST
    client_a, _auth2 = _register_client("a@x.co") if False else (_client_a, auth_a)
    deck = client_a.post(
        f"/api/v1/notebooks/{nb_id}/decks",
        json={"name": "secret"},
    ).json()

    # Second workspace tries to see it.
    client_b, _ = _register_client("b@x.co")
    resp = client_b.get(f"/api/v1/decks/{deck['id']}")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && .venv/bin/pytest tests/test_study_decks_api.py -v`
Expected: FAIL — 404 on POST (endpoint not registered).

- [ ] **Step 3: Create the router**

Create `apps/api/app/routers/study_decks.py`:

```python
"""StudyDeck + StudyCard CRUD and review endpoints (S4)."""

from __future__ import annotations

from datetime import datetime, timezone
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
from app.models import Notebook, StudyCard, StudyDeck, User
from app.schemas.study_decks import (
    CardCreate,
    CardOut,
    CardPatch,
    DeckCreate,
    DeckOut,
    DeckPatch,
    PaginatedDecks,
)

notebooks_decks_router = APIRouter(
    prefix="/api/v1/notebooks", tags=["study-decks"]
)
decks_router = APIRouter(prefix="/api/v1/decks", tags=["study-decks"])
cards_router = APIRouter(prefix="/api/v1/cards", tags=["study-decks"])


def _get_notebook_or_404(db: Session, notebook_id: str, workspace_id: str) -> Notebook:
    nb = (
        db.query(Notebook)
        .filter(Notebook.id == notebook_id, Notebook.workspace_id == workspace_id)
        .first()
    )
    if nb is None:
        raise ApiError("not_found", "Notebook not found", status_code=404)
    return nb


def _get_deck_or_404(db: Session, deck_id: str, workspace_id: str) -> StudyDeck:
    deck = db.query(StudyDeck).filter(StudyDeck.id == deck_id).first()
    if deck is None:
        raise ApiError("not_found", "Deck not found", status_code=404)
    nb = (
        db.query(Notebook)
        .filter(Notebook.id == deck.notebook_id, Notebook.workspace_id == workspace_id)
        .first()
    )
    if nb is None:
        raise ApiError("not_found", "Deck not found", status_code=404)
    return deck


def _get_card_or_404(db: Session, card_id: str, workspace_id: str) -> StudyCard:
    card = db.query(StudyCard).filter(StudyCard.id == card_id).first()
    if card is None:
        raise ApiError("not_found", "Card not found", status_code=404)
    # Verify workspace through deck → notebook
    _get_deck_or_404(db, card.deck_id, workspace_id)
    return card


# ---------------------------------------------------------------------------
# Deck endpoints
# ---------------------------------------------------------------------------


@notebooks_decks_router.get("/{notebook_id}/decks", response_model=PaginatedDecks)
def list_decks(
    notebook_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
) -> PaginatedDecks:
    _ = current_user
    _get_notebook_or_404(db, notebook_id, workspace_id)
    rows = (
        db.query(StudyDeck)
        .filter(StudyDeck.notebook_id == notebook_id)
        .order_by(StudyDeck.created_at.desc())
        .all()
    )
    return PaginatedDecks(
        items=[DeckOut.model_validate(r, from_attributes=True) for r in rows],
        total=len(rows),
    )


@notebooks_decks_router.post("/{notebook_id}/decks", response_model=DeckOut)
def create_deck(
    notebook_id: str,
    payload: DeckCreate,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf: None = Depends(require_csrf_protection),
) -> DeckOut:
    _get_notebook_or_404(db, notebook_id, workspace_id)
    deck = StudyDeck(
        notebook_id=notebook_id,
        name=payload.name,
        description=payload.description,
        created_by=str(current_user.id),
    )
    db.add(deck); db.commit(); db.refresh(deck)
    return DeckOut.model_validate(deck, from_attributes=True)


@decks_router.get("/{deck_id}", response_model=DeckOut)
def get_deck(
    deck_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
) -> DeckOut:
    _ = current_user
    deck = _get_deck_or_404(db, deck_id, workspace_id)
    return DeckOut.model_validate(deck, from_attributes=True)


@decks_router.patch("/{deck_id}", response_model=DeckOut)
def patch_deck(
    deck_id: str,
    payload: DeckPatch,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf: None = Depends(require_csrf_protection),
) -> DeckOut:
    _ = current_user
    deck = _get_deck_or_404(db, deck_id, workspace_id)
    if payload.name is not None:
        deck.name = payload.name
    if payload.description is not None:
        deck.description = payload.description
    if payload.archived is True:
        deck.archived_at = datetime.now(timezone.utc)
    elif payload.archived is False:
        deck.archived_at = None
    db.add(deck); db.commit(); db.refresh(deck)
    return DeckOut.model_validate(deck, from_attributes=True)


@decks_router.delete("/{deck_id}")
def delete_deck(
    deck_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf: None = Depends(require_csrf_protection),
) -> dict[str, Any]:
    _ = current_user
    deck = _get_deck_or_404(db, deck_id, workspace_id)
    db.delete(deck); db.commit()
    return {"ok": True}
```

- [ ] **Step 4: Register routers in main.py**

Open `apps/api/app/main.py`. Update the `from app.routers import (...)`
line to include `study_decks`:

```python
from app.routers import (
    ai_actions, attachments, auth, chat, datasets, memory, memory_stream,
    model_catalog, models, notebook_ai, notebooks, pipeline, projects,
    realtime, study, study_decks, uploads,
)
```

Then add three `include_router` calls alongside the other ones:

```python
app.include_router(study_decks.notebooks_decks_router)
app.include_router(study_decks.decks_router)
app.include_router(study_decks.cards_router)
```

- [ ] **Step 5: Run to verify pass**

Run: `cd apps/api && .venv/bin/pytest tests/test_study_decks_api.py -v`
Expected: 3 PASSED.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/routers/study_decks.py apps/api/app/main.py apps/api/tests/test_study_decks_api.py
git commit -m "feat(api): StudyDeck CRUD endpoints"
```

---

### Task 4: Card CRUD endpoints + 2 API tests

**Files:**
- Modify: `apps/api/app/routers/study_decks.py`
- Create: `apps/api/tests/test_study_cards_api.py`

- [ ] **Step 1: Write failing tests**

Create `apps/api/tests/test_study_cards_api.py`. Reuse the same
bootstrap / `_register_client` / `_seed_notebook` helpers from
`test_study_decks_api.py` (inline-copy them into the new file; each
test file is self-contained).

```python
# ruff: noqa: E402
import atexit, importlib, os, shutil, tempfile
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-s4-cards-api-"))
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
from app.models import Notebook, Project, StudyDeck, User, Workspace


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
    csrf = client.get("/api/v1/auth/csrf", headers=_public_headers()).json()["csrf_token"]
    client.headers.update({
        "origin": "http://localhost:3000",
        "x-csrf-token": csrf,
        "x-workspace-id": info["workspace"]["id"],
    })
    return client, {"ws_id": info["workspace"]["id"], "user_id": info["user"]["id"]}


def _seed_deck(client: TestClient, user_id: str, ws_id: str) -> tuple[str, str]:
    with SessionLocal() as db:
        pr = Project(workspace_id=ws_id, name="P"); db.add(pr); db.commit(); db.refresh(pr)
        nb = Notebook(workspace_id=ws_id, project_id=pr.id, created_by=user_id,
                      title="NB", slug="nb")
        db.add(nb); db.commit(); db.refresh(nb)
    deck = client.post(
        f"/api/v1/notebooks/{nb.id}/decks",
        json={"name": "D"},
    ).json()
    return nb.id, deck["id"]


def test_create_and_list_cards_updates_count() -> None:
    client, auth = _register_client("u1@x.co")
    _, deck_id = _seed_deck(client, auth["user_id"], auth["ws_id"])

    resp = client.post(
        f"/api/v1/decks/{deck_id}/cards",
        json={"front": "Q", "back": "A"},
    )
    assert resp.status_code == 200, resp.text
    card = resp.json()
    assert card["source_type"] == "manual"

    list_resp = client.get(f"/api/v1/decks/{deck_id}/cards").json()
    assert len(list_resp["items"]) == 1

    deck_resp = client.get(f"/api/v1/decks/{deck_id}").json()
    assert deck_resp["card_count"] == 1


def test_delete_card_decrements_deck_count() -> None:
    client, auth = _register_client("u2@x.co")
    _, deck_id = _seed_deck(client, auth["user_id"], auth["ws_id"])

    card = client.post(
        f"/api/v1/decks/{deck_id}/cards",
        json={"front": "Q", "back": "A"},
    ).json()
    client.delete(f"/api/v1/cards/{card['id']}")

    deck_resp = client.get(f"/api/v1/decks/{deck_id}").json()
    assert deck_resp["card_count"] == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && .venv/bin/pytest tests/test_study_cards_api.py -v`
Expected: FAIL — 404 (card endpoints missing).

- [ ] **Step 3: Append card endpoints**

Open `apps/api/app/routers/study_decks.py`. Also add a `CardOut` output
import at the top if not already imported, then add at the end of the
file:

```python
from app.schemas.study_decks import CardOut  # noqa: E402 — keep grouped


@decks_router.get("/{deck_id}/cards")
def list_cards(
    deck_id: str,
    due_only: bool = False,
    limit: int = 50,
    cursor: str | None = None,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
) -> dict[str, Any]:
    _ = current_user
    _get_deck_or_404(db, deck_id, workspace_id)

    q = db.query(StudyCard).filter(StudyCard.deck_id == deck_id)
    if due_only:
        now = datetime.now(timezone.utc)
        q = q.filter(
            (StudyCard.next_review_at.is_(None)) | (StudyCard.next_review_at <= now)
        )
    if cursor:
        try:
            cursor_dt = datetime.fromisoformat(cursor.replace("Z", "+00:00"))
        except ValueError:
            raise ApiError("invalid_input", "Bad cursor", status_code=400)
        q = q.filter(StudyCard.created_at < cursor_dt)
    rows = q.order_by(StudyCard.created_at.desc()).limit(max(1, min(limit, 100)) + 1).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = rows[-1].created_at.isoformat() if rows and has_more else None
    return {
        "items": [CardOut.model_validate(r, from_attributes=True).model_dump(mode="json") for r in rows],
        "next_cursor": next_cursor,
    }


@decks_router.post("/{deck_id}/cards", response_model=CardOut)
def create_card(
    deck_id: str,
    payload: CardCreate,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf: None = Depends(require_csrf_protection),
) -> CardOut:
    _ = current_user
    deck = _get_deck_or_404(db, deck_id, workspace_id)
    card = StudyCard(
        deck_id=deck.id,
        front=payload.front,
        back=payload.back,
        source_type=payload.source_type,
        source_ref=payload.source_ref,
    )
    db.add(card)
    deck.card_count = (deck.card_count or 0) + 1
    db.add(deck)
    db.commit(); db.refresh(card)
    return CardOut.model_validate(card, from_attributes=True)


@cards_router.patch("/{card_id}", response_model=CardOut)
def patch_card(
    card_id: str,
    payload: CardPatch,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf: None = Depends(require_csrf_protection),
) -> CardOut:
    _ = current_user
    card = _get_card_or_404(db, card_id, workspace_id)
    if payload.front is not None:
        card.front = payload.front
    if payload.back is not None:
        card.back = payload.back
    db.add(card); db.commit(); db.refresh(card)
    return CardOut.model_validate(card, from_attributes=True)


@cards_router.delete("/{card_id}")
def delete_card(
    card_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf: None = Depends(require_csrf_protection),
) -> dict[str, Any]:
    _ = current_user
    card = _get_card_or_404(db, card_id, workspace_id)
    deck = db.query(StudyDeck).filter(StudyDeck.id == card.deck_id).first()
    if deck and deck.card_count > 0:
        deck.card_count -= 1
        db.add(deck)
    db.delete(card); db.commit()
    return {"ok": True}
```

- [ ] **Step 4: Run to verify pass**

Run: `cd apps/api && .venv/bin/pytest tests/test_study_cards_api.py tests/test_study_decks_api.py -v`
Expected: 5 PASSED.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/routers/study_decks.py apps/api/tests/test_study_cards_api.py
git commit -m "feat(api): StudyCard CRUD endpoints under decks router"
```

---

### Task 5: Review endpoints (`review/next` + `review`) with FSRS

**Files:**
- Modify: `apps/api/app/routers/study_decks.py`
- Create: `apps/api/tests/test_study_review.py`

- [ ] **Step 1: Write failing tests**

Create `apps/api/tests/test_study_review.py`:

```python
# ruff: noqa: E402
import atexit, importlib, os, shutil, tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-s4-review-"))
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
from app.models import AIActionLog, Notebook, Project, StudyCard, StudyDeck, User, Workspace


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
    csrf = client.get("/api/v1/auth/csrf", headers=_public_headers()).json()["csrf_token"]
    client.headers.update({
        "origin": "http://localhost:3000",
        "x-csrf-token": csrf,
        "x-workspace-id": info["workspace"]["id"],
    })
    return client, {"ws_id": info["workspace"]["id"], "user_id": info["user"]["id"]}


def _make_deck_with_cards(client: TestClient, user_id: str, ws_id: str, n_cards: int = 1) -> tuple[str, list[str]]:
    with SessionLocal() as db:
        pr = Project(workspace_id=ws_id, name="P"); db.add(pr); db.commit(); db.refresh(pr)
        nb = Notebook(workspace_id=ws_id, project_id=pr.id, created_by=user_id,
                      title="NB", slug="nb")
        db.add(nb); db.commit(); db.refresh(nb)
    deck = client.post(
        f"/api/v1/notebooks/{nb.id}/decks",
        json={"name": "D"},
    ).json()
    card_ids: list[str] = []
    for i in range(n_cards):
        c = client.post(
            f"/api/v1/decks/{deck['id']}/cards",
            json={"front": f"Q{i}", "back": f"A{i}"},
        ).json()
        card_ids.append(c["id"])
    return deck["id"], card_ids


def test_review_next_returns_card_or_empty() -> None:
    client, auth = _register_client("r1@x.co")
    deck_id, cards = _make_deck_with_cards(client, auth["user_id"], auth["ws_id"], n_cards=1)

    resp = client.post(f"/api/v1/decks/{deck_id}/review/next")
    assert resp.status_code == 200
    body = resp.json()
    assert body["card"] is not None
    assert body["card"]["id"] == cards[0]

    # Mark it as reviewed, then expect queue empty (next_review_at in future).
    client.post(f"/api/v1/cards/{cards[0]}/review", json={"rating": 3})
    resp2 = client.post(f"/api/v1/decks/{deck_id}/review/next").json()
    assert resp2["card"] is None
    assert resp2["queue_empty"] is True


def test_review_good_updates_fsrs_and_logs() -> None:
    client, auth = _register_client("r2@x.co")
    deck_id, cards = _make_deck_with_cards(client, auth["user_id"], auth["ws_id"], n_cards=1)
    card_id = cards[0]

    resp = client.post(f"/api/v1/cards/{card_id}/review", json={"rating": 3})
    assert resp.status_code == 200, resp.text

    with SessionLocal() as db:
        card = db.query(StudyCard).filter_by(id=card_id).one()
        assert card.review_count == 1
        assert card.stability > 0
        assert card.next_review_at is not None
        assert card.last_review_at is not None
        assert card.consecutive_failures == 0

        log = (
            db.query(AIActionLog)
            .filter(AIActionLog.action_type == "study.review_card")
            .one()
        )
        assert log.block_id == card_id


def test_review_again_bumps_consecutive_failures_and_schedules_confusion_task() -> None:
    client, auth = _register_client("r3@x.co")
    deck_id, cards = _make_deck_with_cards(client, auth["user_id"], auth["ws_id"], n_cards=1)
    card_id = cards[0]

    # Three consecutive Again calls. Patch the Celery .delay() to observe.
    with patch(
        "app.tasks.worker_tasks.process_study_confusion_task.delay",
    ) as delay_mock:
        for _ in range(3):
            client.post(f"/api/v1/cards/{card_id}/review", json={"rating": 1})

    assert delay_mock.call_count == 1
    args, kwargs = delay_mock.call_args
    assert args[0] == card_id
    assert args[3] == "consecutive_failures"

    with SessionLocal() as db:
        card = db.query(StudyCard).filter_by(id=card_id).one()
        assert card.lapse_count == 3
        assert card.confusion_memory_written_at is not None


def test_review_marked_confused_flag_fires_task_once() -> None:
    client, auth = _register_client("r4@x.co")
    deck_id, cards = _make_deck_with_cards(client, auth["user_id"], auth["ws_id"], n_cards=1)
    card_id = cards[0]

    with patch(
        "app.tasks.worker_tasks.process_study_confusion_task.delay",
    ) as delay_mock:
        client.post(
            f"/api/v1/cards/{card_id}/review",
            json={"rating": 3, "marked_confused": True},
        )
        # Second mark on the same card should NOT fire again — memory_written_at is set.
        client.post(
            f"/api/v1/cards/{card_id}/review",
            json={"rating": 3, "marked_confused": True},
        )

    assert delay_mock.call_count == 1
    args, kwargs = delay_mock.call_args
    assert args[3] == "manual"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && .venv/bin/pytest tests/test_study_review.py -v`
Expected: FAIL — `process_study_confusion_task.delay` not found or
endpoint missing.

- [ ] **Step 3: Add review endpoints + stub the Celery task**

Append to `apps/api/app/routers/study_decks.py`:

```python
from app.schemas.study_decks import ReviewRequest, ReviewResponse  # noqa: E402
from app.services.ai_action_logger import action_log_context
from app.services.fsrs import schedule_next


@decks_router.post("/{deck_id}/review/next")
async def review_next(
    deck_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf: None = Depends(require_csrf_protection),
) -> dict[str, Any]:
    """Return the next due card for this deck, or `{card: null, queue_empty: true}`."""
    _ = current_user
    deck = _get_deck_or_404(db, deck_id, workspace_id)

    now = datetime.now(timezone.utc)
    q = (
        db.query(StudyCard)
        .filter(StudyCard.deck_id == deck.id)
        .filter(
            (StudyCard.next_review_at.is_(None)) | (StudyCard.next_review_at <= now)
        )
        .order_by(StudyCard.next_review_at.asc().nullsfirst())
        .limit(1)
    )
    card = q.first()
    if card is None:
        return {"card": None, "queue_empty": True}

    days_since = 0.0
    if card.last_review_at:
        delta = (now - card.last_review_at).total_seconds()
        days_since = max(0.0, delta / 86400.0)

    return {
        "card": {
            "id": card.id,
            "front": card.front,
            "back": card.back,
            "review_count": card.review_count,
            "days_since_last": round(days_since, 3),
        },
        "queue_empty": False,
    }


@cards_router.post("/{card_id}/review", response_model=ReviewResponse)
async def review_card(
    card_id: str,
    payload: ReviewRequest,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf: None = Depends(require_csrf_protection),
) -> ReviewResponse:
    card = _get_card_or_404(db, card_id, workspace_id)
    deck = db.query(StudyDeck).filter(StudyDeck.id == card.deck_id).first()
    notebook_id = deck.notebook_id if deck else None
    now = datetime.now(timezone.utc)

    days_since = 0.0
    if card.last_review_at:
        days_since = max(0.0, (now - card.last_review_at).total_seconds() / 86400.0)

    update = schedule_next(
        difficulty=card.difficulty,
        stability=card.stability,
        rating=payload.rating,
        days_since_last_review=days_since,
    )

    async with action_log_context(
        db,
        workspace_id=str(workspace_id),
        user_id=str(current_user.id),
        action_type="study.review_card",
        scope="notebook",
        notebook_id=str(notebook_id) if notebook_id else None,
        page_id=None,
        block_id=str(card.id),
    ) as log:
        log.set_input({
            "rating": payload.rating,
            "days_since_last": round(days_since, 3),
            "marked_confused": payload.marked_confused,
        })

        card.difficulty = update.difficulty
        card.stability = update.stability
        card.last_review_at = now
        card.next_review_at = now + timedelta(days=update.next_interval_days)
        card.review_count += 1
        if payload.rating == 1:
            card.lapse_count += 1
            card.consecutive_failures += 1
        else:
            card.consecutive_failures = 0

        fire_confusion = False
        if card.confusion_memory_written_at is None and (
            card.consecutive_failures >= 3 or payload.marked_confused
        ):
            fire_confusion = True
            card.confusion_memory_written_at = now

        db.add(card); db.commit(); db.refresh(card)

        log.set_output({
            "next_review_at": card.next_review_at.isoformat(),
            "difficulty": card.difficulty,
            "stability": card.stability,
            "consecutive_failures": card.consecutive_failures,
            "fired_confusion_task": fire_confusion,
        })

    if fire_confusion:
        trigger = "manual" if payload.marked_confused else "consecutive_failures"
        from app.tasks.worker_tasks import process_study_confusion_task
        process_study_confusion_task.delay(
            str(card.id),
            str(current_user.id),
            str(workspace_id),
            trigger,
        )

    return ReviewResponse(
        ok=True,
        next_review_at=card.next_review_at,
        consecutive_failures=card.consecutive_failures,
    )
```

You also need to add the `from datetime import timedelta` to the
module-level imports if it isn't already there (it's needed for
`now + timedelta(days=...)`).

- [ ] **Step 4: Stub the Celery task in worker_tasks.py so the tests pass**

Open `apps/api/app/tasks/worker_tasks.py`. At the bottom, add a stub
that will be fleshed out in Task 7:

```python
@celery_app.task(name="app.tasks.worker_tasks.process_study_confusion")
def process_study_confusion_task(
    card_id: str,
    user_id: str,
    workspace_id: str,
    trigger: str,
) -> None:
    """Stub — full implementation in S4 Task 7."""
    logger.info(
        "process_study_confusion_task stub: card=%s user=%s trigger=%s",
        card_id, user_id, trigger,
    )
```

- [ ] **Step 5: Run to verify pass**

Run: `cd apps/api && .venv/bin/pytest tests/test_study_review.py tests/test_study_cards_api.py tests/test_study_decks_api.py -v`
Expected: 9 PASSED.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/routers/study_decks.py apps/api/app/tasks/worker_tasks.py apps/api/tests/test_study_review.py
git commit -m "feat(api): review/next + review endpoints with FSRS state update"
```

---

### Task 6: Card list endpoint `due_only` behavior test (regression guard)

**Files:**
- Modify: `apps/api/tests/test_study_cards_api.py`

- [ ] **Step 1: Append a test**

Append to `apps/api/tests/test_study_cards_api.py`:

```python
def test_list_cards_due_only_filter() -> None:
    client, auth = _register_client("u3@x.co")
    _, deck_id = _seed_deck(client, auth["user_id"], auth["ws_id"])
    # Two cards: one new (next_review_at NULL), one already due in the future.
    card_a = client.post(
        f"/api/v1/decks/{deck_id}/cards",
        json={"front": "Q1", "back": "A1"},
    ).json()
    card_b = client.post(
        f"/api/v1/decks/{deck_id}/cards",
        json={"front": "Q2", "back": "A2"},
    ).json()
    # Push card_b into the future via a Good review.
    client.post(f"/api/v1/cards/{card_b['id']}/review", json={"rating": 3})

    due = client.get(f"/api/v1/decks/{deck_id}/cards?due_only=true").json()
    ids = {i["id"] for i in due["items"]}
    assert card_a["id"] in ids
    assert card_b["id"] not in ids
```

- [ ] **Step 2: Run**

Run: `cd apps/api && .venv/bin/pytest tests/test_study_cards_api.py -v`
Expected: 4 PASSED.

- [ ] **Step 3: Commit**

```bash
git add apps/api/tests/test_study_cards_api.py
git commit -m "test(api): regression guard for study-cards due_only filter"
```

---

### Task 7: `study_confusion` source_type in UnifiedMemoryPipeline

**Files:**
- Modify: `apps/api/app/services/unified_memory_pipeline.py`
- Create: `apps/api/tests/test_unified_pipeline_study_confusion.py`

- [ ] **Step 1: Write the failing test**

Create `apps/api/tests/test_unified_pipeline_study_confusion.py`:

```python
# ruff: noqa: E402
import atexit, asyncio, os, shutil, tempfile
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-s4-conf-pipeline-"))
atexit.register(lambda: shutil.rmtree(TEST_TEMP_DIR, ignore_errors=True))
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_TEMP_DIR / 'test.db'}"
os.environ["ENV"] = "test"

import importlib
import app.core.config as config_module
config_module.get_settings.cache_clear()
config_module.settings = config_module.get_settings()
import app.db.session as session_module
importlib.reload(session_module)

from app.services.unified_memory_pipeline import SourceType


def test_source_type_includes_study_confusion() -> None:
    # The Literal must accept "study_confusion" — if it doesn't, this
    # import would be fine but the pipeline branch logic rejects it.
    # We verify via a runtime check against the module's get_args.
    from typing import get_args
    assert "study_confusion" in get_args(SourceType)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && .venv/bin/pytest tests/test_unified_pipeline_study_confusion.py -v`
Expected: FAIL — `"study_confusion" not in SourceType args`.

- [ ] **Step 3: Add the source_type**

Open `apps/api/app/services/unified_memory_pipeline.py`. Find the
`SourceType = Literal[...]` block (around line 130):

```python
SourceType = Literal[
    "chat_message",
    "notebook_page",
    "uploaded_document",
    "whiteboard",
    "book_chapter",
]
```

Replace with:

```python
SourceType = Literal[
    "chat_message",
    "notebook_page",
    "uploaded_document",
    "whiteboard",
    "book_chapter",
    "study_confusion",
]
```

If anywhere in the same file there is a triage helper that looks at
`source_type` to compute an initial `importance` (search for
`source_type == "chat_message"` or similar), add a branch so that
`study_confusion` seeds `importance = max(importance, 0.5)`. If no
such branch exists (the file's triage is source-agnostic), no further
change is required — the `study_confusion` evidence will be triaged
like any other candidate. Leave a short comment above the new arm of
the Literal:

```python
SourceType = Literal[
    "chat_message",
    "notebook_page",
    "uploaded_document",
    "whiteboard",
    "book_chapter",
    # S4: user kept getting a card wrong, or explicitly marked it confusing.
    "study_confusion",
]
```

- [ ] **Step 4: Run to verify pass**

Run: `cd apps/api && .venv/bin/pytest tests/test_unified_pipeline_study_confusion.py -v`
Expected: PASSED.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/services/unified_memory_pipeline.py apps/api/tests/test_unified_pipeline_study_confusion.py
git commit -m "feat(api): accept study_confusion source_type in UnifiedMemoryPipeline"
```

---

### Task 8: Fill in `process_study_confusion_task`

**Files:**
- Modify: `apps/api/app/tasks/worker_tasks.py`
- Create: `apps/api/tests/test_study_confusion_task.py`

- [ ] **Step 1: Write failing test**

Create `apps/api/tests/test_study_confusion_task.py`:

```python
# ruff: noqa: E402
import atexit, importlib, os, shutil, tempfile
from datetime import datetime, timezone
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-s4-conf-task-"))
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
    Notebook, Project, StudyCard, StudyDeck, User, Workspace,
)


def setup_function() -> None:
    global engine, SessionLocal
    engine = _s.engine
    SessionLocal = _s.SessionLocal
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


engine = _s.engine
SessionLocal = _s.SessionLocal


def _seed_card() -> tuple[str, str, str]:
    with SessionLocal() as db:
        ws = Workspace(name="W"); user = User(email="u@x.co", password_hash="x")
        db.add(ws); db.add(user); db.commit(); db.refresh(ws); db.refresh(user)
        pr = Project(workspace_id=ws.id, name="P"); db.add(pr); db.commit(); db.refresh(pr)
        nb = Notebook(workspace_id=ws.id, project_id=pr.id, created_by=user.id,
                      title="NB", slug="nb"); db.add(nb); db.commit(); db.refresh(nb)
        deck = StudyDeck(notebook_id=nb.id, name="D", created_by=user.id)
        db.add(deck); db.commit(); db.refresh(deck)
        card = StudyCard(
            deck_id=deck.id, front="Q", back="A",
            consecutive_failures=3,
        )
        db.add(card); db.commit(); db.refresh(card)
        return ws.id, user.id, card.id


def test_task_runs_pipeline_for_confusion_card() -> None:
    ws_id, user_id, card_id = _seed_card()

    from app.tasks.worker_tasks import process_study_confusion_task

    with patch("app.tasks.worker_tasks._run_study_confusion_pipeline") as runner:
        process_study_confusion_task.run(
            card_id, user_id, ws_id, "consecutive_failures",
        )
    assert runner.call_count == 1
    args, _ = runner.call_args
    # args: (db, PipelineInput)
    pipeline_input = args[1]
    assert pipeline_input.source_type == "study_confusion"
    assert pipeline_input.source_ref == card_id


def test_task_noop_when_card_missing() -> None:
    from app.tasks.worker_tasks import process_study_confusion_task

    with patch("app.tasks.worker_tasks._run_study_confusion_pipeline") as runner:
        process_study_confusion_task.run(
            "does-not-exist", "user", "ws", "manual",
        )
    assert runner.call_count == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && .venv/bin/pytest tests/test_study_confusion_task.py -v`
Expected: FAIL — `_run_study_confusion_pipeline` doesn't exist.

- [ ] **Step 3: Replace the stub with the real task**

In `apps/api/app/tasks/worker_tasks.py`, replace the stub version of
`process_study_confusion_task` with:

```python
def _run_study_confusion_pipeline(db, pipeline_input) -> None:
    """Isolated sync wrapper so the task can be patched in tests without
    also patching the async pipeline internals."""
    import asyncio
    from app.services.unified_memory_pipeline import run_pipeline
    asyncio.run(run_pipeline(db, pipeline_input))


@celery_app.task(name="app.tasks.worker_tasks.process_study_confusion")
def process_study_confusion_task(
    card_id: str,
    user_id: str,
    workspace_id: str,
    trigger: str,  # "consecutive_failures" | "manual"
) -> None:
    """Write a confusion-memory evidence for a StudyCard the user keeps
    getting wrong. Idempotent: returns early if the card is gone."""
    from app.models import Notebook, StudyCard, StudyDeck
    from app.services.unified_memory_pipeline import (
        PipelineInput,
        SourceContext,
    )

    db = SessionLocal()
    try:
        card = db.get(StudyCard, card_id)
        if not card:
            return
        deck = db.get(StudyDeck, card.deck_id)
        if not deck:
            return
        notebook = db.get(Notebook, deck.notebook_id)
        if not notebook or not notebook.project_id:
            return

        source_text = (
            f"User is confused about this study card (trigger: {trigger}).\n"
            f"Question: {card.front}\n"
            f"Answer: {card.back}\n"
            f"Lapses: {card.lapse_count}, consecutive failures: {card.consecutive_failures}."
        )
        pipeline_input = PipelineInput(
            source_type="study_confusion",
            source_text=source_text[:6000],
            source_ref=str(card.id),
            workspace_id=str(workspace_id),
            project_id=str(notebook.project_id),
            user_id=str(user_id),
            context=SourceContext(owner_user_id=str(user_id)),
            context_text=f"Study confusion ({trigger})",
        )
        _run_study_confusion_pipeline(db, pipeline_input)
    except Exception:
        logger.exception("process_study_confusion_task failed for card %s", card_id)
    finally:
        db.close()
```

- [ ] **Step 4: Run to verify pass**

Run: `cd apps/api && .venv/bin/pytest tests/test_study_confusion_task.py -v`
Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/tasks/worker_tasks.py apps/api/tests/test_study_confusion_task.py
git commit -m "feat(api): process_study_confusion Celery task writes study_confusion evidence"
```

---

### Task 9: `POST /ai/study/flashcards` endpoint

**Files:**
- Create: `apps/api/app/routers/study_ai.py`
- Create: `apps/api/tests/test_study_ai_endpoints.py`
- Modify: `apps/api/app/main.py`

- [ ] **Step 1: Write failing test**

Create `apps/api/tests/test_study_ai_endpoints.py`:

```python
# ruff: noqa: E402
import atexit, importlib, os, shutil, tempfile
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-s4-study-ai-"))
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
from unittest.mock import AsyncMock, patch

from app.db.base import Base
import app.db.session as _s
from app.models import (
    AIActionLog, Notebook, NotebookPage, Project, StudyCard, StudyDeck, User, Workspace,
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
    csrf = client.get("/api/v1/auth/csrf", headers=_public_headers()).json()["csrf_token"]
    client.headers.update({
        "origin": "http://localhost:3000",
        "x-csrf-token": csrf,
        "x-workspace-id": info["workspace"]["id"],
    })
    return client, {"ws_id": info["workspace"]["id"], "user_id": info["user"]["id"]}


def _seed_page(ws_id: str, user_id: str, text: str = "some page text") -> tuple[str, str]:
    with SessionLocal() as db:
        pr = Project(workspace_id=ws_id, name="P"); db.add(pr); db.commit(); db.refresh(pr)
        nb = Notebook(workspace_id=ws_id, project_id=pr.id, created_by=user_id,
                      title="NB", slug="nb"); db.add(nb); db.commit(); db.refresh(nb)
        pg = NotebookPage(notebook_id=nb.id, created_by=user_id, title="T",
                          slug="t", plain_text=text); db.add(pg); db.commit(); db.refresh(pg)
        return nb.id, pg.id


FAKE_FLASHCARDS_JSON = """
{"cards": [
  {"front": "What is X?", "back": "X is a concept."},
  {"front": "Why X?",     "back": "Because."}
]}
""".strip()


def test_flashcards_preview_returns_cards_without_persisting() -> None:
    client, auth = _register_client("u1@x.co")
    _, page_id = _seed_page(auth["ws_id"], auth["user_id"], "foundational text")

    fake = AsyncMock(return_value=FAKE_FLASHCARDS_JSON)
    with patch("app.routers.study_ai._run_llm_json", fake):
        resp = client.post(
            "/api/v1/ai/study/flashcards",
            json={"source_type": "page", "source_id": page_id, "count": 2},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["cards"]) == 2
    assert body["card_ids"] is None

    with SessionLocal() as db:
        # No cards inserted.
        assert db.query(StudyCard).count() == 0
        # Action log present.
        log = db.query(AIActionLog).filter_by(action_type="study.flashcards").one()
        assert log.page_id == page_id


def test_flashcards_with_deck_id_persists_cards() -> None:
    client, auth = _register_client("u2@x.co")
    nb_id, page_id = _seed_page(auth["ws_id"], auth["user_id"], "text")
    deck = client.post(
        f"/api/v1/notebooks/{nb_id}/decks",
        json={"name": "D"},
    ).json()

    fake = AsyncMock(return_value=FAKE_FLASHCARDS_JSON)
    with patch("app.routers.study_ai._run_llm_json", fake):
        resp = client.post(
            "/api/v1/ai/study/flashcards",
            json={"source_type": "page", "source_id": page_id, "count": 2,
                  "deck_id": deck["id"]},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["card_ids"]) == 2

    with SessionLocal() as db:
        cards = db.query(StudyCard).all()
        assert len(cards) == 2
        assert all(c.source_type == "page_ai" and c.source_ref == page_id for c in cards)
        deck_row = db.query(StudyDeck).filter_by(id=deck["id"]).one()
        assert deck_row.card_count == 2


def test_flashcards_bad_llm_output_returns_422() -> None:
    client, auth = _register_client("u3@x.co")
    _, page_id = _seed_page(auth["ws_id"], auth["user_id"])
    fake = AsyncMock(return_value="not json at all")
    with patch("app.routers.study_ai._run_llm_json", fake):
        resp = client.post(
            "/api/v1/ai/study/flashcards",
            json={"source_type": "page", "source_id": page_id},
        )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "llm_bad_output"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && .venv/bin/pytest tests/test_study_ai_endpoints.py::test_flashcards_preview_returns_cards_without_persisting -v`
Expected: FAIL — 404 (router missing).

- [ ] **Step 3: Create the study_ai router**

Create `apps/api/app/routers/study_ai.py`:

```python
"""Study-scope AI endpoints: flashcards / quiz / ask (S4)."""

from __future__ import annotations

import json
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
from app.models import (
    Notebook, NotebookPage, StudyAsset, StudyCard, StudyChunk, StudyDeck, User,
)
from app.services.ai_action_logger import action_log_context
from app.services.dashscope_client import chat_completion

router = APIRouter(prefix="/api/v1/ai/study", tags=["study-ai"])


_FLASHCARDS_SYSTEM = (
    "You produce study flashcards as strict JSON. No prose. "
    'Format: {"cards":[{"front":"...","back":"..."}]}. '
    "Each question tests a distinct concept; answers concise."
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


def _load_source_text(
    db: Session, *, source_type: str, source_id: str, workspace_id: str,
) -> tuple[str, str | None, str | None]:
    """Return (text, page_id_or_None, notebook_id)."""
    if source_type == "page":
        page = db.query(NotebookPage).filter_by(id=source_id).first()
        if not page:
            raise ApiError("not_found", "Page not found", status_code=404)
        nb = (
            db.query(Notebook)
            .filter(Notebook.id == page.notebook_id, Notebook.workspace_id == workspace_id)
            .first()
        )
        if not nb:
            raise ApiError("not_found", "Page not found", status_code=404)
        return (page.plain_text or "")[:8000], page.id, nb.id
    if source_type == "chunk":
        chunk = db.query(StudyChunk).filter_by(id=source_id).first()
        if not chunk:
            raise ApiError("not_found", "Chunk not found", status_code=404)
        asset = db.query(StudyAsset).filter_by(id=chunk.asset_id).first()
        if not asset:
            raise ApiError("not_found", "Chunk not found", status_code=404)
        nb = (
            db.query(Notebook)
            .filter(Notebook.id == asset.notebook_id, Notebook.workspace_id == workspace_id)
            .first()
        )
        if not nb:
            raise ApiError("not_found", "Chunk not found", status_code=404)
        return (chunk.content or "")[:8000], None, nb.id
    raise ApiError("invalid_input", f"Unknown source_type {source_type}", status_code=400)


@router.post("/flashcards")
async def generate_flashcards(
    payload: dict[str, Any],
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf: None = Depends(require_csrf_protection),
) -> dict[str, Any]:
    source_type = str(payload.get("source_type", ""))
    source_id = str(payload.get("source_id", ""))
    count = int(payload.get("count", 10))
    deck_id = payload.get("deck_id")
    if count < 1 or count > 50:
        raise ApiError("invalid_input", "count must be 1-50", status_code=400)

    text, page_id, notebook_id = _load_source_text(
        db, source_type=source_type, source_id=source_id,
        workspace_id=workspace_id,
    )

    prompt = (
        f"Produce exactly {count} flashcards from the following text.\n\n{text}"
    )

    async with action_log_context(
        db,
        workspace_id=str(workspace_id),
        user_id=str(current_user.id),
        action_type="study.flashcards",
        scope="study_asset" if source_type == "chunk" else "page",
        notebook_id=str(notebook_id) if notebook_id else None,
        page_id=str(page_id) if page_id else None,
    ) as log:
        log.set_input({"source_type": source_type, "source_id": source_id, "count": count})

        raw = await _run_llm_json(_FLASHCARDS_SYSTEM, prompt)
        try:
            parsed = json.loads(raw)
            cards = parsed["cards"]
            if not isinstance(cards, list) or not cards:
                raise ValueError("cards missing")
            for c in cards:
                if not isinstance(c.get("front"), str) or not isinstance(c.get("back"), str):
                    raise ValueError("bad card shape")
        except Exception as exc:
            log.set_output({"error": str(exc), "raw_length": len(raw)})
            raise ApiError("llm_bad_output", "LLM returned invalid JSON", status_code=422)

        log.set_output({"card_count": len(cards)})
        log.record_usage(
            event_type="llm_completion",
            prompt_tokens=max(1, len(prompt) // 4),
            completion_tokens=max(1, len(raw) // 4),
            count_source="estimated",
        )

        card_ids: list[str] | None = None
        if deck_id:
            deck = db.query(StudyDeck).filter_by(id=deck_id).first()
            if not deck:
                raise ApiError("not_found", "Deck not found", status_code=404)
            nb = (
                db.query(Notebook)
                .filter(Notebook.id == deck.notebook_id, Notebook.workspace_id == workspace_id)
                .first()
            )
            if not nb:
                raise ApiError("not_found", "Deck not found", status_code=404)
            src_type = "page_ai" if source_type == "page" else "chunk_ai"
            card_rows: list[StudyCard] = []
            for c in cards:
                card_rows.append(StudyCard(
                    deck_id=deck.id,
                    front=c["front"],
                    back=c["back"],
                    source_type=src_type,
                    source_ref=source_id,
                ))
            db.add_all(card_rows)
            deck.card_count = (deck.card_count or 0) + len(card_rows)
            db.add(deck)
            db.commit()
            for row in card_rows:
                db.refresh(row)
            card_ids = [r.id for r in card_rows]

    return {"cards": cards, "card_ids": card_ids}
```

- [ ] **Step 4: Register the router**

Open `apps/api/app/main.py`. Add `study_ai` to the routers import and
include the router:

```python
from app.routers import (
    ai_actions, attachments, auth, chat, datasets, memory, memory_stream,
    model_catalog, models, notebook_ai, notebooks, pipeline, projects,
    realtime, study, study_ai, study_decks, uploads,
)
```

```python
app.include_router(study_ai.router)
```

- [ ] **Step 5: Run to verify pass**

Run: `cd apps/api && .venv/bin/pytest tests/test_study_ai_endpoints.py -v`
Expected: 3 PASSED.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/routers/study_ai.py apps/api/app/main.py apps/api/tests/test_study_ai_endpoints.py
git commit -m "feat(api): POST /ai/study/flashcards endpoint with deck persistence"
```

---

### Task 10: `POST /ai/study/quiz` endpoint

**Files:**
- Modify: `apps/api/app/routers/study_ai.py`
- Modify: `apps/api/tests/test_study_ai_endpoints.py`

- [ ] **Step 1: Append failing test**

Append to `apps/api/tests/test_study_ai_endpoints.py`:

```python
FAKE_QUIZ_JSON = """
{"questions": [
  {
    "question": "What is X?",
    "options": ["a","b","c","d"],
    "correct_index": 2,
    "explanation": "because…"
  }
]}
""".strip()


def test_quiz_returns_valid_mcq_schema() -> None:
    client, auth = _register_client("u_quiz@x.co")
    _, page_id = _seed_page(auth["ws_id"], auth["user_id"], "text")

    fake = AsyncMock(return_value=FAKE_QUIZ_JSON)
    with patch("app.routers.study_ai._run_llm_json", fake):
        resp = client.post(
            "/api/v1/ai/study/quiz",
            json={"source_type": "page", "source_id": page_id, "count": 1},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["questions"]) == 1
    q = body["questions"][0]
    assert len(q["options"]) == 4
    assert 0 <= q["correct_index"] < 4

    with SessionLocal() as db:
        assert db.query(AIActionLog).filter_by(action_type="study.quiz").count() == 1


def test_quiz_bad_shape_returns_422() -> None:
    client, auth = _register_client("u_quiz2@x.co")
    _, page_id = _seed_page(auth["ws_id"], auth["user_id"], "text")

    bad = '{"questions": [{"question": "Q", "options": ["a","b"], "correct_index": 0, "explanation": ""}]}'
    fake = AsyncMock(return_value=bad)
    with patch("app.routers.study_ai._run_llm_json", fake):
        resp = client.post(
            "/api/v1/ai/study/quiz",
            json={"source_type": "page", "source_id": page_id, "count": 1},
        )
    assert resp.status_code == 422
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && .venv/bin/pytest tests/test_study_ai_endpoints.py::test_quiz_returns_valid_mcq_schema -v`
Expected: FAIL — 404.

- [ ] **Step 3: Add the endpoint**

In `apps/api/app/routers/study_ai.py`, below `generate_flashcards`,
add:

```python
_QUIZ_SYSTEM = (
    "You produce multiple-choice quizzes as strict JSON. No prose. "
    'Format: {"questions":[{"question":"...","options":["a","b","c","d"],'
    '"correct_index":0,"explanation":"..."}]}. Exactly 4 options each, '
    "correct_index in 0..3."
)


@router.post("/quiz")
async def generate_quiz(
    payload: dict[str, Any],
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf: None = Depends(require_csrf_protection),
) -> dict[str, Any]:
    source_type = str(payload.get("source_type", ""))
    source_id = str(payload.get("source_id", ""))
    count = int(payload.get("count", 5))
    if count < 1 or count > 20:
        raise ApiError("invalid_input", "count must be 1-20", status_code=400)

    text, page_id, notebook_id = _load_source_text(
        db, source_type=source_type, source_id=source_id,
        workspace_id=workspace_id,
    )

    prompt = (
        f"Produce exactly {count} MCQs from the following text.\n\n{text}"
    )

    async with action_log_context(
        db,
        workspace_id=str(workspace_id),
        user_id=str(current_user.id),
        action_type="study.quiz",
        scope="study_asset" if source_type == "chunk" else "page",
        notebook_id=str(notebook_id) if notebook_id else None,
        page_id=str(page_id) if page_id else None,
    ) as log:
        log.set_input({"source_type": source_type, "source_id": source_id, "count": count})

        raw = await _run_llm_json(_QUIZ_SYSTEM, prompt)
        try:
            parsed = json.loads(raw)
            questions = parsed["questions"]
            if not isinstance(questions, list) or not questions:
                raise ValueError("questions missing")
            for q in questions:
                options = q.get("options")
                if not isinstance(options, list) or len(options) != 4:
                    raise ValueError("options must be length 4")
                if not all(isinstance(o, str) and o.strip() for o in options):
                    raise ValueError("options must be non-empty strings")
                ci = q.get("correct_index")
                if not isinstance(ci, int) or not 0 <= ci < 4:
                    raise ValueError("correct_index out of range")
                if not isinstance(q.get("question"), str):
                    raise ValueError("question must be str")
        except Exception as exc:
            log.set_output({"error": str(exc), "raw_length": len(raw)})
            raise ApiError("llm_bad_output", "LLM returned invalid MCQ JSON", status_code=422)

        log.set_output({"question_count": len(questions)})
        log.record_usage(
            event_type="llm_completion",
            prompt_tokens=max(1, len(prompt) // 4),
            completion_tokens=max(1, len(raw) // 4),
            count_source="estimated",
        )

    return {"questions": questions}
```

- [ ] **Step 4: Run to verify pass**

Run: `cd apps/api && .venv/bin/pytest tests/test_study_ai_endpoints.py -v`
Expected: 5 PASSED.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/routers/study_ai.py apps/api/tests/test_study_ai_endpoints.py
git commit -m "feat(api): POST /ai/study/quiz endpoint with MCQ schema validation"
```

---

### Task 11: `study_context` helper + `POST /ai/study/ask` SSE endpoint

**Files:**
- Create: `apps/api/app/services/study_context.py`
- Modify: `apps/api/app/routers/study_ai.py`
- Modify: `apps/api/tests/test_study_ai_endpoints.py`

- [ ] **Step 1: Append failing test**

Append to `apps/api/tests/test_study_ai_endpoints.py`:

```python
async def _fake_ask_stream(*_a, **_kw):
    from app.services.dashscope_stream import StreamChunk
    yield StreamChunk(content="answer text", finish_reason=None)
    yield StreamChunk(
        content="", finish_reason="stop",
        usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        model_id="qwen-plus",
    )


def test_ask_streaming_produces_action_log_with_sources() -> None:
    client, auth = _register_client("u_ask@x.co")

    # Seed a notebook + study asset to scope the ask.
    with SessionLocal() as db:
        pr = Project(workspace_id=auth["ws_id"], name="P"); db.add(pr); db.commit(); db.refresh(pr)
        nb = Notebook(workspace_id=auth["ws_id"], project_id=pr.id, created_by=auth["user_id"],
                      title="NB", slug="nb"); db.add(nb); db.commit(); db.refresh(nb)
        asset = StudyAsset(
            notebook_id=nb.id, title="Book",
            created_by=auth["user_id"],
        )
        db.add(asset); db.commit(); db.refresh(asset)
        asset_id = asset.id

    with patch(
        "app.routers.study_ai.chat_completion_stream",
        side_effect=lambda *a, **kw: _fake_ask_stream(),
    ), patch(
        "app.routers.study_ai.assemble_study_context",
        return_value=({"system_prompt": "SYS"}, [{"type": "chunk", "id": "c1", "title": "Chapter 1"}]),
    ):
        resp = client.post(
            "/api/v1/ai/study/ask",
            json={"asset_id": asset_id, "message": "what about X?"},
        )
        _ = resp.text  # drain SSE

    assert resp.status_code == 200
    with SessionLocal() as db:
        log = db.query(AIActionLog).filter_by(action_type="study.ask").one()
        assert log.trace_metadata.get("retrieval_sources")
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && .venv/bin/pytest tests/test_study_ai_endpoints.py::test_ask_streaming_produces_action_log_with_sources -v`
Expected: FAIL — 404.

- [ ] **Step 3: Create the study_context helper**

Create `apps/api/app/services/study_context.py`:

```python
"""Assemble a context payload for /ai/study/ask.

Returns (context_dict, sources_list) where:
  context_dict = {
      "system_prompt": str with chunks + notes stitched in,
  }
  sources_list = [{"type": "chunk", "id": "...", "title": "..."}]
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import StudyAsset, StudyChunk


def assemble_study_context(
    db: Session,
    *,
    asset_id: str,
    workspace_id: str,
    project_id: str,
    user_id: str,
    query: str,
    max_chunks: int = 3,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """S4 minimum: pull the first N chunks of the asset by chunk_index.

    A richer embedding-similarity search is a reasonable follow-up but
    is explicitly outside S4's scope — see spec §6.3.3.
    """
    asset = db.query(StudyAsset).filter_by(id=asset_id).first()
    if not asset:
        return ({"system_prompt": ""}, [])

    chunks = (
        db.query(StudyChunk)
        .filter(StudyChunk.asset_id == asset.id)
        .order_by(StudyChunk.chunk_index.asc())
        .limit(max_chunks)
        .all()
    )

    sources = [
        {"type": "chunk", "id": c.id, "title": c.heading or f"Chunk {c.chunk_index}"}
        for c in chunks
    ]
    chunks_text = "\n\n---\n\n".join(
        (c.heading + "\n" if c.heading else "") + (c.content or "")[:2000]
        for c in chunks
    )
    system = (
        "You are helping a user understand a study asset. "
        "Use the chunks below as authoritative context. Be concise.\n\n"
        f"CHUNKS:\n{chunks_text}\n\n"
        f"USER QUESTION: {query}"
    )
    return ({"system_prompt": system}, sources)
```

- [ ] **Step 4: Add the ask endpoint**

In `apps/api/app/routers/study_ai.py`, at the top, add:

```python
from starlette.responses import StreamingResponse

from app.services.dashscope_stream import chat_completion_stream
from app.services.study_context import assemble_study_context
```

Append at the bottom of the file:

```python
def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/ask")
async def study_ask(
    payload: dict[str, Any],
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf: None = Depends(require_csrf_protection),
) -> StreamingResponse:
    asset_id = str(payload.get("asset_id", ""))
    message = str(payload.get("message", "")).strip()
    history = payload.get("history") or []
    if not asset_id or not message:
        raise ApiError("invalid_input", "asset_id and message are required", status_code=400)

    asset = db.query(StudyAsset).filter_by(id=asset_id).first()
    if not asset:
        raise ApiError("not_found", "Asset not found", status_code=404)
    nb = (
        db.query(Notebook)
        .filter(Notebook.id == asset.notebook_id, Notebook.workspace_id == workspace_id)
        .first()
    )
    if not nb:
        raise ApiError("not_found", "Asset not found", status_code=404)

    ctx, sources = assemble_study_context(
        db,
        asset_id=asset_id,
        workspace_id=str(workspace_id),
        project_id=str(nb.project_id) if nb.project_id else "",
        user_id=str(current_user.id),
        query=message,
    )

    messages: list[dict[str, str]] = [
        {"role": "system", "content": ctx["system_prompt"]}
    ]
    for m in (history or [])[-10:]:
        role = m.get("role"); content = m.get("content")
        if role in ("user", "assistant") and isinstance(content, str) and content.strip():
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": message})

    async def _generate():
        async with action_log_context(
            db,
            workspace_id=str(workspace_id),
            user_id=str(current_user.id),
            action_type="study.ask",
            scope="study_asset",
            notebook_id=str(nb.id),
            page_id=None,
        ) as log:
            log.set_input({"asset_id": asset_id, "message": message[:4000]})
            log.set_trace_metadata({"retrieval_sources": sources})
            full = ""
            last_usage: dict | None = None
            last_model_id: str | None = None
            try:
                yield _sse("message_start", {
                    "role": "assistant",
                    "sources": sources,
                    "action_log_id": log.log_id,
                })
                async for chunk in chat_completion_stream(messages, temperature=0.7, max_tokens=4096):
                    if chunk.content:
                        full += chunk.content
                        yield _sse("token", {"content": chunk.content, "snapshot": full})
                    if chunk.usage:
                        last_usage = chunk.usage
                    if chunk.model_id:
                        last_model_id = chunk.model_id
                log.set_output(full)
                log.record_usage(
                    event_type="llm_completion",
                    model_id=last_model_id,
                    prompt_tokens=(last_usage or {}).get("prompt_tokens") or max(1, len(message) // 4),
                    completion_tokens=(last_usage or {}).get("completion_tokens") or max(1, len(full) // 4),
                    count_source="exact" if last_usage else "estimated",
                )
                yield _sse("message_done", {"content": full, "sources": sources, "action_log_id": log.log_id})
            except Exception as exc:
                yield _sse("error", {"message": str(exc)})
                raise

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

- [ ] **Step 5: Run to verify pass**

Run: `cd apps/api && .venv/bin/pytest tests/test_study_ai_endpoints.py -v`
Expected: 6 PASSED.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/services/study_context.py apps/api/app/routers/study_ai.py apps/api/tests/test_study_ai_endpoints.py
git commit -m "feat(api): POST /ai/study/ask SSE with asset-scoped context"
```

---

### Task 12: Full backend regression run

**Files:** none (verification)

- [ ] **Step 1: Run the full S4 backend suite**

```bash
cd apps/api && .venv/bin/pytest \
  tests/test_fsrs.py \
  tests/test_study_decks_models.py \
  tests/test_study_decks_api.py \
  tests/test_study_cards_api.py \
  tests/test_study_review.py \
  tests/test_unified_pipeline_study_confusion.py \
  tests/test_study_confusion_task.py \
  tests/test_study_ai_endpoints.py -v
```
Expected: all passed (roughly 25 tests).

- [ ] **Step 2: Commit nothing**

No artifacts.

---

### Task 13: Frontend — StudyWindow tab shell refactor

**Files:**
- Modify: `apps/web/components/notebook/contents/StudyWindow.tsx`
- Create: `apps/web/components/notebook/contents/study/AssetsPanel.tsx`
- Create: `apps/web/styles/study-window.css`
- Modify: `apps/web/app/[locale]/workspace/notebooks/[notebookId]/layout.tsx`

- [ ] **Step 1: Move existing StudyWindow body into AssetsPanel.tsx**

Read the current `apps/web/components/notebook/contents/StudyWindow.tsx`
(small, ~70 lines based on earlier snapshot). Create
`apps/web/components/notebook/contents/study/AssetsPanel.tsx` with the
**entire existing body** of StudyWindow — same imports, same state,
same effects, same JSX. Update the default export name to
`AssetsPanel` and the props interface name to `AssetsPanelProps`. The
component still takes `notebookId: string`.

Do not modify the component's behavior — this is a pure move.

- [ ] **Step 2: Replace StudyWindow.tsx with a tab shell**

Overwrite `apps/web/components/notebook/contents/StudyWindow.tsx`
with:

```tsx
"use client";

import { useState } from "react";
import AssetsPanel from "./study/AssetsPanel";
import DecksPanel from "./study/DecksPanel";
import ReviewSession from "./study/ReviewSession";

type StudyTab = "assets" | "decks" | "review";

interface StudyWindowProps {
  notebookId: string;
}

export default function StudyWindow({ notebookId }: StudyWindowProps) {
  const [tab, setTab] = useState<StudyTab>("assets");
  const [reviewingDeckId, setReviewingDeckId] = useState<string | null>(null);

  const handleStartReview = (deckId: string) => {
    setReviewingDeckId(deckId);
    setTab("review");
  };

  return (
    <div className="study-window" data-testid="study-window">
      <div className="study-window__tabs" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={tab === "assets"}
          data-testid="study-tab-assets"
          onClick={() => setTab("assets")}
        >
          Assets
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "decks"}
          data-testid="study-tab-decks"
          onClick={() => setTab("decks")}
        >
          Decks
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "review"}
          data-testid="study-tab-review"
          onClick={() => setTab("review")}
          disabled={!reviewingDeckId}
          title={reviewingDeckId ? "" : "Start a review from the Decks tab first"}
        >
          Review
        </button>
      </div>
      <div className="study-window__body">
        {tab === "assets" && <AssetsPanel notebookId={notebookId} />}
        {tab === "decks" && (
          <DecksPanel notebookId={notebookId} onStartReview={handleStartReview} />
        )}
        {tab === "review" && reviewingDeckId && (
          <ReviewSession
            deckId={reviewingDeckId}
            onExit={() => setTab("decks")}
          />
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Create `study-window.css`**

Create `apps/web/styles/study-window.css`:

```css
.study-window {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #ffffff;
}

.study-window__tabs {
  display: flex;
  gap: 2px;
  padding: 6px 8px 0;
  border-bottom: 1px solid #e5e7eb;
  flex-shrink: 0;
}

.study-window__tabs button {
  padding: 6px 12px;
  font-size: 12px;
  font-weight: 500;
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  cursor: pointer;
  color: #6b7280;
}

.study-window__tabs button[aria-selected="true"] {
  color: #111827;
  border-bottom-color: #2563eb;
  font-weight: 600;
}

.study-window__tabs button[disabled] {
  cursor: not-allowed;
  opacity: 0.5;
}

.study-window__body {
  flex: 1;
  overflow: auto;
  min-height: 0;
}
```

- [ ] **Step 4: Import the CSS in the notebook layout**

Open `apps/web/app/[locale]/workspace/notebooks/[notebookId]/layout.tsx`.
Add alongside the other CSS imports at the top:

```tsx
import "@/styles/study-window.css";
```

- [ ] **Step 5: Commit** (DecksPanel and ReviewSession do not exist
  yet; frontend will not render until later tasks. That is expected —
  we ship the tab shell first.)

Note: `DecksPanel` and `ReviewSession` are referenced but haven't
been created yet, so the app will fail to compile until Tasks 15 and
17 land. To avoid a broken commit, create **empty placeholder files**
now:

Create `apps/web/components/notebook/contents/study/DecksPanel.tsx`:

```tsx
"use client";
interface Props { notebookId: string; onStartReview: (deckId: string) => void; }
export default function DecksPanel(_: Props) { return <div>DecksPanel (TODO)</div>; }
```

Create `apps/web/components/notebook/contents/study/ReviewSession.tsx`:

```tsx
"use client";
interface Props { deckId: string; onExit: () => void; }
export default function ReviewSession(_: Props) { return <div>ReviewSession (TODO)</div>; }
```

These placeholders let the build succeed. Tasks 15 and 17 overwrite
them with the real implementations.

```bash
git add apps/web/components/notebook/contents/StudyWindow.tsx apps/web/components/notebook/contents/study/AssetsPanel.tsx apps/web/components/notebook/contents/study/DecksPanel.tsx apps/web/components/notebook/contents/study/ReviewSession.tsx apps/web/styles/study-window.css apps/web/app/[locale]/workspace/notebooks/[notebookId]/layout.tsx
git commit -m "refactor(web): StudyWindow becomes a tab shell; Assets body lifted out"
```

---

### Task 14: DeckPickerDialog component (shared helper)

**Files:**
- Create: `apps/web/components/notebook/contents/study/DeckPickerDialog.tsx`

- [ ] **Step 1: Create the dialog**

```tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost } from "@/lib/api";

interface Deck {
  id: string;
  name: string;
  card_count: number;
}

interface Props {
  notebookId: string;
  onPick: (deck: Deck) => void;
  onCancel: () => void;
}

export default function DeckPickerDialog({ notebookId, onPick, onCancel }: Props) {
  const [decks, setDecks] = useState<Deck[]>([]);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");

  useEffect(() => {
    void apiGet<{ items: Deck[] }>(`/api/v1/notebooks/${notebookId}/decks`)
      .then((r) => setDecks(r.items || []))
      .catch(() => setDecks([]));
  }, [notebookId]);

  const handleCreate = useCallback(async () => {
    if (!newName.trim()) return;
    setCreating(true);
    try {
      const created = await apiPost<Deck>(
        `/api/v1/notebooks/${notebookId}/decks`,
        { name: newName.trim(), description: "" },
      );
      onPick(created);
    } catch {
      setCreating(false);
    }
  }, [newName, notebookId, onPick]);

  return (
    <div className="deck-picker" role="dialog" data-testid="deck-picker">
      <div className="deck-picker__header">
        <strong>Pick a deck</strong>
        <button type="button" onClick={onCancel} className="deck-picker__close">×</button>
      </div>
      <ul className="deck-picker__list">
        {decks.map((d) => (
          <li key={d.id}>
            <button
              type="button"
              className="deck-picker__item"
              data-testid="deck-picker-item"
              onClick={() => onPick(d)}
            >
              {d.name} <span className="deck-picker__count">({d.card_count})</span>
            </button>
          </li>
        ))}
        {decks.length === 0 && <li className="deck-picker__empty">No decks yet</li>}
      </ul>
      <div className="deck-picker__create">
        <input
          type="text"
          placeholder="New deck name"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
        />
        <button
          type="button"
          onClick={handleCreate}
          disabled={creating || !newName.trim()}
          data-testid="deck-picker-create"
        >
          + Create
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add apps/web/components/notebook/contents/study/DeckPickerDialog.tsx
git commit -m "feat(web): DeckPickerDialog — used by FlashcardBlock and CardsPanel"
```

---

### Task 15: DecksPanel component

**Files:**
- Overwrite: `apps/web/components/notebook/contents/study/DecksPanel.tsx`
- Create: `apps/web/components/notebook/contents/study/CardsPanel.tsx` (placeholder; Task 16 overwrites)

- [ ] **Step 1: Overwrite DecksPanel.tsx**

```tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import { Plus, Archive, Play } from "lucide-react";
import { apiGet, apiPatch, apiPost } from "@/lib/api";
import CardsPanel from "./CardsPanel";

interface Deck {
  id: string;
  name: string;
  description: string;
  card_count: number;
  archived_at: string | null;
  created_at: string;
}

interface Props {
  notebookId: string;
  onStartReview: (deckId: string) => void;
}

export default function DecksPanel({ notebookId, onStartReview }: Props) {
  const [decks, setDecks] = useState<Deck[]>([]);
  const [activeDeckId, setActiveDeckId] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await apiGet<{ items: Deck[]; total: number }>(
        `/api/v1/notebooks/${notebookId}/decks`,
      );
      setDecks(data.items || []);
    } catch {
      setDecks([]);
    }
  }, [notebookId]);

  useEffect(() => { void load(); }, [load]);

  const handleCreate = useCallback(async () => {
    if (!newName.trim() || creating) return;
    setCreating(true);
    try {
      await apiPost<Deck>(`/api/v1/notebooks/${notebookId}/decks`, {
        name: newName.trim(),
        description: "",
      });
      setNewName("");
      await load();
    } finally {
      setCreating(false);
    }
  }, [newName, creating, notebookId, load]);

  const handleArchive = useCallback(
    async (deckId: string) => {
      await apiPatch(`/api/v1/decks/${deckId}`, { archived: true });
      await load();
    },
    [load],
  );

  if (activeDeckId) {
    return (
      <CardsPanel
        deckId={activeDeckId}
        notebookId={notebookId}
        onBack={() => setActiveDeckId(null)}
        onStartReview={onStartReview}
      />
    );
  }

  return (
    <div className="decks-panel" data-testid="decks-panel" style={{ padding: 12 }}>
      <div style={{ display: "flex", gap: 6, marginBottom: 12 }}>
        <input
          type="text"
          placeholder="New deck name"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          style={{ flex: 1, padding: "6px 10px", border: "1px solid #e5e7eb", borderRadius: 6 }}
        />
        <button
          type="button"
          onClick={handleCreate}
          disabled={creating || !newName.trim()}
          data-testid="decks-panel-create"
          style={{ padding: "6px 12px", borderRadius: 6, border: "1px solid #e5e7eb", background: "#fff", cursor: "pointer" }}
        >
          <Plus size={14} /> Create
        </button>
      </div>

      {decks.length === 0 ? (
        <p style={{ color: "#888", fontSize: 12 }}>No decks yet. Create one above.</p>
      ) : (
        <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {decks.map((d) => (
            <li
              key={d.id}
              data-testid="deck-row"
              style={{
                padding: 10,
                borderBottom: "1px solid #eee",
                display: "flex",
                alignItems: "center",
                gap: 8,
              }}
            >
              <button
                type="button"
                onClick={() => setActiveDeckId(d.id)}
                style={{ flex: 1, textAlign: "left", border: "none", background: "transparent", cursor: "pointer", fontSize: 13 }}
              >
                <div style={{ fontWeight: 600 }}>{d.name}</div>
                <div style={{ color: "#666", fontSize: 11 }}>{d.card_count} cards</div>
              </button>
              <button
                type="button"
                onClick={() => onStartReview(d.id)}
                title="Start Review"
                data-testid="deck-start-review"
                style={{ padding: 4, border: "none", background: "transparent", cursor: "pointer", color: "#2563eb" }}
              >
                <Play size={16} />
              </button>
              <button
                type="button"
                onClick={() => void handleArchive(d.id)}
                title="Archive"
                style={{ padding: 4, border: "none", background: "transparent", cursor: "pointer", color: "#9ca3af" }}
              >
                <Archive size={16} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Create CardsPanel placeholder (Task 16 overwrites)**

Create `apps/web/components/notebook/contents/study/CardsPanel.tsx`:

```tsx
"use client";
interface Props {
  deckId: string;
  notebookId: string;
  onBack: () => void;
  onStartReview: (deckId: string) => void;
}
export default function CardsPanel(_: Props) { return <div>CardsPanel (TODO)</div>; }
```

- [ ] **Step 3: Commit**

```bash
git add apps/web/components/notebook/contents/study/DecksPanel.tsx apps/web/components/notebook/contents/study/CardsPanel.tsx
git commit -m "feat(web): DecksPanel — list, create, archive, drill-in to cards"
```

---

### Task 16: CardsPanel component

**Files:**
- Overwrite: `apps/web/components/notebook/contents/study/CardsPanel.tsx`

- [ ] **Step 1: Overwrite CardsPanel.tsx**

```tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import { ArrowLeft, Plus, Play, Trash2, Sparkles, ClipboardList } from "lucide-react";
import { apiDelete, apiGet, apiPost } from "@/lib/api";
import GenerateFlashcardsModal from "./GenerateFlashcardsModal";
import QuizModal from "./QuizModal";

interface Card {
  id: string;
  front: string;
  back: string;
  source_type: string;
  review_count: number;
  next_review_at: string | null;
}

interface Props {
  deckId: string;
  notebookId: string;
  onBack: () => void;
  onStartReview: (deckId: string) => void;
}

export default function CardsPanel({ deckId, notebookId, onBack, onStartReview }: Props) {
  const [cards, setCards] = useState<Card[]>([]);
  const [newFront, setNewFront] = useState("");
  const [newBack, setNewBack] = useState("");
  const [showGen, setShowGen] = useState(false);
  const [showQuiz, setShowQuiz] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await apiGet<{ items: Card[]; next_cursor: string | null }>(
        `/api/v1/decks/${deckId}/cards`,
      );
      setCards(r.items || []);
    } catch {
      setCards([]);
    }
  }, [deckId]);

  useEffect(() => { void load(); }, [load]);

  const handleCreate = useCallback(async () => {
    if (!newFront.trim() || !newBack.trim()) return;
    await apiPost(`/api/v1/decks/${deckId}/cards`, {
      front: newFront.trim(),
      back: newBack.trim(),
    });
    setNewFront(""); setNewBack("");
    await load();
  }, [newFront, newBack, deckId, load]);

  const handleDelete = useCallback(async (cardId: string) => {
    await apiDelete(`/api/v1/cards/${cardId}`);
    await load();
  }, [load]);

  return (
    <div className="cards-panel" data-testid="cards-panel" style={{ padding: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 12 }}>
        <button
          type="button"
          onClick={onBack}
          style={{ padding: 4, border: "none", background: "transparent", cursor: "pointer" }}
        >
          <ArrowLeft size={16} />
        </button>
        <strong style={{ flex: 1 }}>Cards ({cards.length})</strong>
        <button
          type="button"
          onClick={() => onStartReview(deckId)}
          title="Start Review"
          data-testid="cards-panel-review"
          style={{ padding: 6, border: "1px solid #e5e7eb", borderRadius: 6, background: "#fff", cursor: "pointer" }}
        >
          <Play size={14} /> Review
        </button>
        <button
          type="button"
          onClick={() => setShowGen(true)}
          title="Generate Flashcards"
          data-testid="cards-panel-generate"
          style={{ padding: 6, border: "1px solid #e5e7eb", borderRadius: 6, background: "#fff", cursor: "pointer" }}
        >
          <Sparkles size={14} /> Generate
        </button>
        <button
          type="button"
          onClick={() => setShowQuiz(true)}
          title="Quiz"
          data-testid="cards-panel-quiz"
          style={{ padding: 6, border: "1px solid #e5e7eb", borderRadius: 6, background: "#fff", cursor: "pointer" }}
        >
          <ClipboardList size={14} /> Quiz
        </button>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr auto", gap: 6, marginBottom: 12 }}>
        <input
          type="text"
          placeholder="Front"
          value={newFront}
          onChange={(e) => setNewFront(e.target.value)}
          style={{ padding: "6px 10px", border: "1px solid #e5e7eb", borderRadius: 6 }}
        />
        <input
          type="text"
          placeholder="Back"
          value={newBack}
          onChange={(e) => setNewBack(e.target.value)}
          style={{ padding: "6px 10px", border: "1px solid #e5e7eb", borderRadius: 6 }}
        />
        <button
          type="button"
          onClick={handleCreate}
          disabled={!newFront.trim() || !newBack.trim()}
          data-testid="cards-panel-create"
          style={{ padding: "6px 12px", borderRadius: 6, border: "1px solid #e5e7eb", background: "#fff", cursor: "pointer" }}
        >
          <Plus size={14} />
        </button>
      </div>

      {cards.length === 0 ? (
        <p style={{ color: "#888", fontSize: 12 }}>No cards yet.</p>
      ) : (
        <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {cards.map((c) => (
            <li
              key={c.id}
              data-testid="card-row"
              style={{
                padding: 8,
                borderBottom: "1px solid #eee",
                display: "flex",
                alignItems: "flex-start",
                gap: 8,
              }}
            >
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 600, fontSize: 12 }}>{c.front}</div>
                <div style={{ color: "#666", fontSize: 12 }}>{c.back}</div>
                <div style={{ color: "#9ca3af", fontSize: 10, marginTop: 2 }}>
                  {c.source_type} · {c.review_count} reviews
                </div>
              </div>
              <button
                type="button"
                onClick={() => void handleDelete(c.id)}
                style={{ padding: 2, border: "none", background: "transparent", cursor: "pointer", color: "#9ca3af" }}
              >
                <Trash2 size={14} />
              </button>
            </li>
          ))}
        </ul>
      )}

      {showGen && (
        <GenerateFlashcardsModal
          notebookId={notebookId}
          deckId={deckId}
          onClose={() => { setShowGen(false); void load(); }}
        />
      )}
      {showQuiz && (
        <QuizModal
          notebookId={notebookId}
          onClose={() => setShowQuiz(false)}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

GenerateFlashcardsModal and QuizModal haven't been created yet. Create
minimal placeholders first so this commit builds:

Create `apps/web/components/notebook/contents/study/GenerateFlashcardsModal.tsx`:

```tsx
"use client";
interface Props { notebookId: string; deckId: string; onClose: () => void; }
export default function GenerateFlashcardsModal(_: Props) { return null; }
```

Create `apps/web/components/notebook/contents/study/QuizModal.tsx`:

```tsx
"use client";
interface Props { notebookId: string; onClose: () => void; }
export default function QuizModal(_: Props) { return null; }
```

Tasks 18 and 19 overwrite these.

```bash
git add apps/web/components/notebook/contents/study/CardsPanel.tsx apps/web/components/notebook/contents/study/GenerateFlashcardsModal.tsx apps/web/components/notebook/contents/study/QuizModal.tsx
git commit -m "feat(web): CardsPanel — manual add, list, delete, entry points for gen/quiz/review"
```

---

### Task 17: ReviewSession component

**Files:**
- Overwrite: `apps/web/components/notebook/contents/study/ReviewSession.tsx`

- [ ] **Step 1: Overwrite**

```tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import { Eye, Flag } from "lucide-react";
import { apiPost } from "@/lib/api";

interface Card {
  id: string;
  front: string;
  back: string;
  review_count: number;
  days_since_last: number;
}

interface Props {
  deckId: string;
  onExit: () => void;
}

const RATINGS: { label: string; value: 1 | 2 | 3 | 4 }[] = [
  { label: "Again", value: 1 },
  { label: "Hard", value: 2 },
  { label: "Good", value: 3 },
  { label: "Easy", value: 4 },
];

export default function ReviewSession({ deckId, onExit }: Props) {
  const [card, setCard] = useState<Card | null>(null);
  const [revealed, setRevealed] = useState(false);
  const [empty, setEmpty] = useState(false);
  const [reviewed, setReviewed] = useState(0);

  const fetchNext = useCallback(async () => {
    setRevealed(false);
    try {
      const r = await apiPost<{ card: Card | null; queue_empty?: boolean }>(
        `/api/v1/decks/${deckId}/review/next`,
        {},
      );
      if (r.card) {
        setCard(r.card);
        setEmpty(false);
      } else {
        setCard(null);
        setEmpty(true);
      }
    } catch {
      setCard(null);
      setEmpty(true);
    }
  }, [deckId]);

  useEffect(() => { void fetchNext(); }, [fetchNext]);

  const handleRate = useCallback(
    async (rating: 1 | 2 | 3 | 4) => {
      if (!card) return;
      await apiPost(`/api/v1/cards/${card.id}/review`, { rating });
      setReviewed((n) => n + 1);
      await fetchNext();
    },
    [card, fetchNext],
  );

  const handleMarkConfused = useCallback(async () => {
    if (!card) return;
    await apiPost(`/api/v1/cards/${card.id}/review`, {
      rating: 1,
      marked_confused: true,
    });
    setReviewed((n) => n + 1);
    await fetchNext();
  }, [card, fetchNext]);

  if (empty) {
    return (
      <div data-testid="review-empty" style={{ padding: 32, textAlign: "center" }}>
        <div style={{ fontSize: 18, fontWeight: 600, marginBottom: 8 }}>
          Queue empty
        </div>
        <div style={{ color: "#888", fontSize: 13, marginBottom: 16 }}>
          Reviewed {reviewed} card(s).
        </div>
        <button
          type="button"
          onClick={onExit}
          style={{ padding: "6px 16px", border: "1px solid #e5e7eb", borderRadius: 6, background: "#fff", cursor: "pointer" }}
        >
          Back to decks
        </button>
      </div>
    );
  }

  if (!card) {
    return <div style={{ padding: 16, color: "#888" }}>Loading…</div>;
  }

  return (
    <div className="review-session" data-testid="review-session" style={{ padding: 16 }}>
      <div
        style={{
          minHeight: 120,
          padding: 20,
          border: "1px solid #e5e7eb",
          borderRadius: 10,
          background: "#fafbfd",
          marginBottom: 16,
        }}
      >
        <div style={{ fontSize: 11, color: "#9ca3af", marginBottom: 6 }}>
          Question · reviewed {card.review_count} time(s)
        </div>
        <div data-testid="review-front" style={{ fontSize: 15, lineHeight: 1.55 }}>
          {card.front}
        </div>
      </div>

      {revealed ? (
        <div
          style={{
            minHeight: 120,
            padding: 20,
            border: "1px solid #2563eb33",
            background: "rgba(37,99,235,0.04)",
            borderRadius: 10,
            marginBottom: 16,
          }}
        >
          <div style={{ fontSize: 11, color: "#9ca3af", marginBottom: 6 }}>Answer</div>
          <div data-testid="review-back" style={{ fontSize: 15, lineHeight: 1.55 }}>
            {card.back}
          </div>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setRevealed(true)}
          data-testid="review-reveal"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            padding: "10px 16px",
            margin: "0 auto 16px",
            border: "1px solid #e5e7eb",
            borderRadius: 8,
            background: "#fff",
            cursor: "pointer",
          }}
        >
          <Eye size={14} /> Reveal answer
        </button>
      )}

      {revealed && (
        <>
          <div style={{ display: "flex", gap: 6, justifyContent: "center", marginBottom: 12 }}>
            {RATINGS.map((r) => (
              <button
                key={r.value}
                type="button"
                data-testid={`review-rate-${r.value}`}
                onClick={() => void handleRate(r.value)}
                style={{
                  padding: "8px 14px",
                  border: "1px solid #e5e7eb",
                  borderRadius: 6,
                  background: r.value === 1 ? "#fee2e2" : r.value === 4 ? "#d1fae5" : "#fff",
                  cursor: "pointer",
                  fontSize: 12,
                  fontWeight: 600,
                }}
              >
                {r.label}
              </button>
            ))}
          </div>
          <div style={{ textAlign: "center" }}>
            <button
              type="button"
              onClick={() => void handleMarkConfused()}
              data-testid="review-mark-confused"
              style={{
                padding: "4px 10px",
                border: "none",
                background: "transparent",
                cursor: "pointer",
                color: "#b91c1c",
                fontSize: 11,
              }}
            >
              <Flag size={12} /> Mark as confused
            </button>
          </div>
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add apps/web/components/notebook/contents/study/ReviewSession.tsx
git commit -m "feat(web): ReviewSession — reveal/rate/mark-confused loop"
```

---

### Task 18: GenerateFlashcardsModal

**Files:**
- Overwrite: `apps/web/components/notebook/contents/study/GenerateFlashcardsModal.tsx`

- [ ] **Step 1: Overwrite**

```tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost } from "@/lib/api";

interface Props {
  notebookId: string;
  deckId: string;
  onClose: () => void;
}

type SourceType = "page" | "chunk";

interface Page { id: string; title: string; }
interface Asset { id: string; title: string; }
interface Chunk { id: string; heading: string; }

interface GeneratedCard { front: string; back: string; }

export default function GenerateFlashcardsModal({ notebookId, deckId, onClose }: Props) {
  const [sourceType, setSourceType] = useState<SourceType>("page");
  const [pages, setPages] = useState<Page[]>([]);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [chunks, setChunks] = useState<Chunk[]>([]);
  const [selectedPage, setSelectedPage] = useState("");
  const [selectedAsset, setSelectedAsset] = useState("");
  const [selectedChunk, setSelectedChunk] = useState("");
  const [count, setCount] = useState(10);
  const [generated, setGenerated] = useState<GeneratedCard[] | null>(null);
  const [saving, setSaving] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void apiGet<{ items: Page[] }>(`/api/v1/notebooks/${notebookId}/pages`)
      .then((r) => setPages(r.items || []))
      .catch(() => setPages([]));
    void apiGet<{ items: Asset[] }>(`/api/v1/notebooks/${notebookId}/study-assets`)
      .then((r) => setAssets(r.items || []))
      .catch(() => setAssets([]));
  }, [notebookId]);

  useEffect(() => {
    if (!selectedAsset) {
      setChunks([]);
      return;
    }
    void apiGet<{ items: Chunk[] }>(`/api/v1/study-assets/${selectedAsset}/chunks`)
      .then((r) => setChunks(r.items || []))
      .catch(() => setChunks([]));
  }, [selectedAsset]);

  const handleGenerate = useCallback(async () => {
    setGenerating(true);
    setError(null);
    try {
      const sourceId = sourceType === "page" ? selectedPage : selectedChunk;
      if (!sourceId) {
        setError("Pick a source");
        return;
      }
      const r = await apiPost<{ cards: GeneratedCard[] }>(
        "/api/v1/ai/study/flashcards",
        { source_type: sourceType, source_id: sourceId, count },
      );
      setGenerated(r.cards || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Generation failed");
    } finally {
      setGenerating(false);
    }
  }, [sourceType, selectedPage, selectedChunk, count]);

  const handleSave = useCallback(async () => {
    if (!generated) return;
    setSaving(true);
    try {
      await Promise.all(
        generated.map((c) =>
          apiPost(`/api/v1/decks/${deckId}/cards`, {
            front: c.front,
            back: c.back,
            source_type: sourceType === "page" ? "page_ai" : "chunk_ai",
            source_ref: sourceType === "page" ? selectedPage : selectedChunk,
          }),
        ),
      );
      onClose();
    } finally {
      setSaving(false);
    }
  }, [generated, deckId, sourceType, selectedPage, selectedChunk, onClose]);

  return (
    <div
      role="dialog"
      data-testid="generate-flashcards-modal"
      style={{
        position: "fixed",
        top: 0, left: 0, right: 0, bottom: 0,
        background: "rgba(17,24,39,0.35)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
      }}
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "#fff",
          borderRadius: 10,
          padding: 18,
          minWidth: 420,
          maxWidth: 560,
          maxHeight: "80vh",
          overflow: "auto",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <strong>Generate flashcards</strong>
          <button type="button" onClick={onClose} style={{ border: "none", background: "none", fontSize: 18, cursor: "pointer" }}>×</button>
        </div>

        <div style={{ display: "flex", gap: 6, marginBottom: 10 }}>
          <button
            type="button"
            onClick={() => setSourceType("page")}
            data-testid="gen-source-page"
            style={{ padding: "4px 10px", borderRadius: 4, border: "1px solid", borderColor: sourceType === "page" ? "#2563eb" : "#e5e7eb", background: sourceType === "page" ? "rgba(37,99,235,0.06)" : "#fff", cursor: "pointer", fontSize: 12 }}
          >
            From page
          </button>
          <button
            type="button"
            onClick={() => setSourceType("chunk")}
            data-testid="gen-source-chunk"
            style={{ padding: "4px 10px", borderRadius: 4, border: "1px solid", borderColor: sourceType === "chunk" ? "#2563eb" : "#e5e7eb", background: sourceType === "chunk" ? "rgba(37,99,235,0.06)" : "#fff", cursor: "pointer", fontSize: 12 }}
          >
            From chapter
          </button>
        </div>

        {sourceType === "page" ? (
          <select
            value={selectedPage}
            onChange={(e) => setSelectedPage(e.target.value)}
            data-testid="gen-select-page"
            style={{ width: "100%", padding: 6, marginBottom: 10 }}
          >
            <option value="">Pick a page</option>
            {pages.map((p) => (
              <option key={p.id} value={p.id}>{p.title || "(untitled)"}</option>
            ))}
          </select>
        ) : (
          <>
            <select
              value={selectedAsset}
              onChange={(e) => { setSelectedAsset(e.target.value); setSelectedChunk(""); }}
              data-testid="gen-select-asset"
              style={{ width: "100%", padding: 6, marginBottom: 6 }}
            >
              <option value="">Pick a study asset</option>
              {assets.map((a) => (
                <option key={a.id} value={a.id}>{a.title}</option>
              ))}
            </select>
            <select
              value={selectedChunk}
              onChange={(e) => setSelectedChunk(e.target.value)}
              data-testid="gen-select-chunk"
              style={{ width: "100%", padding: 6, marginBottom: 10 }}
              disabled={!selectedAsset}
            >
              <option value="">Pick a chapter / chunk</option>
              {chunks.map((c) => (
                <option key={c.id} value={c.id}>{c.heading || "(chunk)"}</option>
              ))}
            </select>
          </>
        )}

        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
          <span style={{ fontSize: 12 }}>Count:</span>
          <input
            type="number"
            min={1}
            max={20}
            value={count}
            onChange={(e) => setCount(Math.max(1, Math.min(20, Number(e.target.value) || 10)))}
            style={{ width: 60, padding: 6 }}
          />
          <button
            type="button"
            onClick={handleGenerate}
            disabled={generating}
            data-testid="gen-submit"
            style={{ padding: "6px 12px", borderRadius: 6, border: "1px solid #e5e7eb", background: "#fff", cursor: "pointer" }}
          >
            {generating ? "Generating…" : "Generate"}
          </button>
        </div>

        {error && <p style={{ color: "#b91c1c", fontSize: 12 }}>{error}</p>}

        {generated && (
          <>
            <ul style={{ listStyle: "none", padding: 0, margin: 0, maxHeight: 260, overflow: "auto" }}>
              {generated.map((c, i) => (
                <li
                  key={i}
                  data-testid="gen-preview-card"
                  style={{ padding: 8, borderBottom: "1px solid #eee", fontSize: 12 }}
                >
                  <div style={{ fontWeight: 600 }}>{c.front}</div>
                  <div style={{ color: "#555" }}>{c.back}</div>
                </li>
              ))}
            </ul>
            <button
              type="button"
              onClick={handleSave}
              disabled={saving || generated.length === 0}
              data-testid="gen-save"
              style={{
                marginTop: 10,
                padding: "8px 16px",
                borderRadius: 6,
                border: "1px solid #e5e7eb",
                background: "#2563eb",
                color: "#fff",
                cursor: "pointer",
              }}
            >
              {saving ? "Saving…" : `Save ${generated.length} to deck`}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add apps/web/components/notebook/contents/study/GenerateFlashcardsModal.tsx
git commit -m "feat(web): GenerateFlashcardsModal — pick source, preview, bulk-save"
```

---

### Task 19: QuizModal

**Files:**
- Overwrite: `apps/web/components/notebook/contents/study/QuizModal.tsx`

- [ ] **Step 1: Overwrite**

```tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost } from "@/lib/api";

interface Props {
  notebookId: string;
  onClose: () => void;
}

type SourceType = "page" | "chunk";

interface Page { id: string; title: string; }
interface Asset { id: string; title: string; }
interface Chunk { id: string; heading: string; }

interface QuizQuestion {
  question: string;
  options: string[];
  correct_index: number;
  explanation: string;
}

export default function QuizModal({ notebookId, onClose }: Props) {
  const [sourceType, setSourceType] = useState<SourceType>("page");
  const [pages, setPages] = useState<Page[]>([]);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [chunks, setChunks] = useState<Chunk[]>([]);
  const [selectedPage, setSelectedPage] = useState("");
  const [selectedAsset, setSelectedAsset] = useState("");
  const [selectedChunk, setSelectedChunk] = useState("");
  const [questions, setQuestions] = useState<QuizQuestion[] | null>(null);
  const [index, setIndex] = useState(0);
  const [answered, setAnswered] = useState<number[]>([]); // picked option per question
  const [submitted, setSubmitted] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void apiGet<{ items: Page[] }>(`/api/v1/notebooks/${notebookId}/pages`)
      .then((r) => setPages(r.items || []))
      .catch(() => setPages([]));
    void apiGet<{ items: Asset[] }>(`/api/v1/notebooks/${notebookId}/study-assets`)
      .then((r) => setAssets(r.items || []))
      .catch(() => setAssets([]));
  }, [notebookId]);

  useEffect(() => {
    if (!selectedAsset) { setChunks([]); return; }
    void apiGet<{ items: Chunk[] }>(`/api/v1/study-assets/${selectedAsset}/chunks`)
      .then((r) => setChunks(r.items || []))
      .catch(() => setChunks([]));
  }, [selectedAsset]);

  const handleGenerate = useCallback(async () => {
    const sourceId = sourceType === "page" ? selectedPage : selectedChunk;
    if (!sourceId) { setError("Pick a source"); return; }
    setGenerating(true); setError(null);
    try {
      const r = await apiPost<{ questions: QuizQuestion[] }>(
        "/api/v1/ai/study/quiz",
        { source_type: sourceType, source_id: sourceId, count: 5 },
      );
      setQuestions(r.questions || []);
      setIndex(0); setAnswered([]); setSubmitted(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Generation failed");
    } finally {
      setGenerating(false);
    }
  }, [sourceType, selectedPage, selectedChunk]);

  const handlePick = useCallback((optIdx: number) => {
    setAnswered((prev) => {
      const next = [...prev];
      next[index] = optIdx;
      return next;
    });
  }, [index]);

  const handleNext = useCallback(() => {
    if (questions && index < questions.length - 1) {
      setIndex((i) => i + 1);
    } else {
      setSubmitted(true);
    }
  }, [questions, index]);

  if (submitted && questions) {
    const correct = answered.reduce(
      (n, pick, i) => n + (pick === questions[i].correct_index ? 1 : 0),
      0,
    );
    return (
      <div role="dialog" data-testid="quiz-modal" style={modalOverlay} onClick={onClose}>
        <div onClick={(e) => e.stopPropagation()} style={modalBody}>
          <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 12 }}>
            Score: {correct} / {questions.length}
          </div>
          <ul style={{ listStyle: "none", padding: 0, margin: 0, maxHeight: 300, overflow: "auto" }}>
            {questions.map((q, i) => {
              const pick = answered[i];
              const correctPick = pick === q.correct_index;
              return (
                <li
                  key={i}
                  data-testid="quiz-result-row"
                  style={{
                    padding: 8,
                    borderBottom: "1px solid #eee",
                    fontSize: 12,
                    background: correctPick ? "rgba(16,185,129,0.06)" : "rgba(239,68,68,0.06)",
                  }}
                >
                  <div style={{ fontWeight: 600 }}>{q.question}</div>
                  <div style={{ color: "#555" }}>
                    Your answer: {q.options[pick] ?? "(none)"} {correctPick ? "✓" : `✗ (correct: ${q.options[q.correct_index]})`}
                  </div>
                  <div style={{ color: "#6b7280", marginTop: 2 }}>{q.explanation}</div>
                </li>
              );
            })}
          </ul>
          <button
            type="button"
            onClick={onClose}
            style={{ marginTop: 10, padding: "6px 16px", border: "1px solid #e5e7eb", borderRadius: 6, background: "#fff", cursor: "pointer" }}
          >
            Close
          </button>
        </div>
      </div>
    );
  }

  if (!questions) {
    return (
      <div role="dialog" data-testid="quiz-modal" style={modalOverlay} onClick={onClose}>
        <div onClick={(e) => e.stopPropagation()} style={modalBody}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 10 }}>
            <strong>Quiz</strong>
            <button type="button" onClick={onClose} style={{ border: "none", background: "none", fontSize: 18, cursor: "pointer" }}>×</button>
          </div>
          <div style={{ display: "flex", gap: 6, marginBottom: 10 }}>
            <button
              type="button"
              onClick={() => setSourceType("page")}
              data-testid="quiz-source-page"
              style={sourceBtn(sourceType === "page")}
            >
              From page
            </button>
            <button
              type="button"
              onClick={() => setSourceType("chunk")}
              data-testid="quiz-source-chunk"
              style={sourceBtn(sourceType === "chunk")}
            >
              From chapter
            </button>
          </div>
          {sourceType === "page" ? (
            <select
              value={selectedPage}
              onChange={(e) => setSelectedPage(e.target.value)}
              data-testid="quiz-select-page"
              style={{ width: "100%", padding: 6, marginBottom: 10 }}
            >
              <option value="">Pick a page</option>
              {pages.map((p) => (
                <option key={p.id} value={p.id}>{p.title || "(untitled)"}</option>
              ))}
            </select>
          ) : (
            <>
              <select
                value={selectedAsset}
                onChange={(e) => { setSelectedAsset(e.target.value); setSelectedChunk(""); }}
                data-testid="quiz-select-asset"
                style={{ width: "100%", padding: 6, marginBottom: 6 }}
              >
                <option value="">Pick a study asset</option>
                {assets.map((a) => (
                  <option key={a.id} value={a.id}>{a.title}</option>
                ))}
              </select>
              <select
                value={selectedChunk}
                onChange={(e) => setSelectedChunk(e.target.value)}
                data-testid="quiz-select-chunk"
                style={{ width: "100%", padding: 6, marginBottom: 10 }}
                disabled={!selectedAsset}
              >
                <option value="">Pick a chapter / chunk</option>
                {chunks.map((c) => (
                  <option key={c.id} value={c.id}>{c.heading || "(chunk)"}</option>
                ))}
              </select>
            </>
          )}
          {error && <p style={{ color: "#b91c1c", fontSize: 12 }}>{error}</p>}
          <button
            type="button"
            onClick={handleGenerate}
            disabled={generating}
            data-testid="quiz-start"
            style={{ padding: "8px 14px", border: "1px solid #e5e7eb", borderRadius: 6, background: "#2563eb", color: "#fff", cursor: "pointer" }}
          >
            {generating ? "Generating…" : "Start"}
          </button>
        </div>
      </div>
    );
  }

  const q = questions[index];
  const pick = answered[index];
  return (
    <div role="dialog" data-testid="quiz-modal" style={modalOverlay} onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()} style={modalBody}>
        <div style={{ fontSize: 11, color: "#9ca3af", marginBottom: 4 }}>
          Question {index + 1} / {questions.length}
        </div>
        <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 10 }}>{q.question}</div>
        <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {q.options.map((opt, i) => (
            <li key={i} style={{ marginBottom: 4 }}>
              <button
                type="button"
                data-testid={`quiz-opt-${i}`}
                onClick={() => handlePick(i)}
                disabled={pick !== undefined}
                style={{
                  width: "100%",
                  textAlign: "left",
                  padding: "8px 10px",
                  border: "1px solid",
                  borderColor: pick === undefined
                    ? "#e5e7eb"
                    : i === q.correct_index
                      ? "#10b981"
                      : i === pick
                        ? "#ef4444"
                        : "#e5e7eb",
                  borderRadius: 6,
                  background: pick === undefined
                    ? "#fff"
                    : i === q.correct_index
                      ? "rgba(16,185,129,0.08)"
                      : i === pick
                        ? "rgba(239,68,68,0.08)"
                        : "#fff",
                  cursor: pick === undefined ? "pointer" : "default",
                }}
              >
                {opt}
              </button>
            </li>
          ))}
        </ul>
        {pick !== undefined && (
          <>
            <p style={{ color: "#555", fontSize: 12, marginTop: 8 }}>{q.explanation}</p>
            <button
              type="button"
              onClick={handleNext}
              data-testid="quiz-next"
              style={{ marginTop: 8, padding: "6px 14px", border: "1px solid #e5e7eb", borderRadius: 6, background: "#fff", cursor: "pointer" }}
            >
              {index === questions.length - 1 ? "See results" : "Next →"}
            </button>
          </>
        )}
      </div>
    </div>
  );
}

const modalOverlay: React.CSSProperties = {
  position: "fixed", top: 0, left: 0, right: 0, bottom: 0,
  background: "rgba(17,24,39,0.35)",
  display: "flex", alignItems: "center", justifyContent: "center",
  zIndex: 1000,
};
const modalBody: React.CSSProperties = {
  background: "#fff",
  borderRadius: 10,
  padding: 18,
  minWidth: 420,
  maxWidth: 560,
  maxHeight: "80vh",
  overflow: "auto",
};
function sourceBtn(active: boolean): React.CSSProperties {
  return {
    padding: "4px 10px",
    borderRadius: 4,
    border: `1px solid ${active ? "#2563eb" : "#e5e7eb"}`,
    background: active ? "rgba(37,99,235,0.06)" : "#fff",
    cursor: "pointer",
    fontSize: 12,
  };
}
```

- [ ] **Step 2: Commit**

```bash
git add apps/web/components/notebook/contents/study/QuizModal.tsx
git commit -m "feat(web): QuizModal — generate MCQs, answer, score, review answers"
```

---

### Task 20: FlashcardBlock "Add to Deck" wiring

**Files:**
- Modify: `apps/web/components/console/editor/extensions/FlashcardBlock.tsx`

- [ ] **Step 1: Extend attrs + render button**

Open `apps/web/components/console/editor/extensions/FlashcardBlock.tsx`.
At the top of the file, in the `FlashcardAttrs` interface, add a
`card_id` field:

```tsx
interface FlashcardAttrs {
  front: string;
  back: string;
  flipped: boolean;
  card_id: string | null;
}
```

In the `addAttributes()` object, add:

```ts
      card_id: { default: null as string | null },
```

At the top of `FlashcardBlockView`, add imports and helpers:

```tsx
import { useCurrentPageId } from "@/components/console/editor/PageIdContext";
import DeckPickerDialog from "@/components/notebook/contents/study/DeckPickerDialog";
import { apiPost } from "@/lib/api";

function extractNotebookId(): string | null {
  if (typeof window === "undefined") return null;
  const m = window.location.pathname.match(/\/notebooks\/([^/?#]+)/);
  return m ? m[1] : null;
}
```

In the component body, after the existing `useState` hooks, add:

```tsx
  const [picking, setPicking] = useState(false);
  const [adding, setAdding] = useState(false);
  const notebookId = extractNotebookId();

  const handleAddToDeck = useCallback(
    async (deck: { id: string; name: string }) => {
      if (!attrs.front.trim() || !attrs.back.trim()) {
        setPicking(false);
        return;
      }
      setAdding(true);
      try {
        const card = await apiPost<{ id: string }>(
          `/api/v1/decks/${deck.id}/cards`,
          {
            front: attrs.front,
            back: attrs.back,
            source_type: "block",
          },
        );
        props.updateAttributes({ card_id: card.id });
      } finally {
        setAdding(false);
        setPicking(false);
      }
    },
    [attrs, props],
  );
```

In the toolbar JSX (the `.flashcard-block__toolbar` div), add a third
button after the Preview button:

```tsx
        {!attrs.card_id && (
          <button
            type="button"
            className="flashcard-block__mode"
            onClick={() => setPicking(true)}
            disabled={adding}
            data-testid="flashcard-add-to-deck"
          >
            {adding ? "Adding…" : "Add to Deck"}
          </button>
        )}
        {attrs.card_id && (
          <span
            className="flashcard-block__in-deck"
            data-testid="flashcard-in-deck"
            style={{ fontSize: 10, color: "#2563eb", marginLeft: 6 }}
          >
            In deck ✓
          </span>
        )}
```

At the bottom of the NodeView return, just before the closing
`</NodeViewWrapper>`, render the picker:

```tsx
      {picking && notebookId && (
        <DeckPickerDialog
          notebookId={notebookId}
          onPick={(d) => void handleAddToDeck(d)}
          onCancel={() => setPicking(false)}
        />
      )}
```

- [ ] **Step 2: Typecheck**

Run: `cd apps/web && ./node_modules/.bin/tsc --noEmit 2>&1 | grep -i "FlashcardBlock" | head -10`
Expected: no new errors in this file.

- [ ] **Step 3: Commit**

```bash
git add apps/web/components/console/editor/extensions/FlashcardBlock.tsx
git commit -m "feat(web): FlashcardBlock — Add to Deck button + card_id attr + badge"
```

---

### Task 21: i18n strings + decks picker CSS

**Files:**
- Modify: `apps/web/messages/en/console-notebooks.json`
- Modify: `apps/web/messages/zh/console-notebooks.json`
- Modify: `apps/web/styles/study-window.css`

- [ ] **Step 1: Append en strings**

Open `apps/web/messages/en/console-notebooks.json`. Add the following
keys at the bottom of the outer object (before the final `}`):

```json
  "study.tabs.assets": "Assets",
  "study.tabs.decks": "Decks",
  "study.tabs.review": "Review",
  "study.decks.create": "Create deck",
  "study.decks.empty": "No decks yet.",
  "study.cards.create": "Create card",
  "study.cards.generate": "Generate",
  "study.cards.quiz": "Quiz",
  "study.cards.review": "Review",
  "study.review.reveal": "Reveal answer",
  "study.review.rate.again": "Again",
  "study.review.rate.hard": "Hard",
  "study.review.rate.good": "Good",
  "study.review.rate.easy": "Easy",
  "study.review.mark_confused": "Mark as confused",
  "study.review.queue_empty": "Queue empty",
  "study.quiz.start": "Start",
  "study.quiz.submit": "Submit",
  "study.flashcard.add_to_deck": "Add to Deck",
  "study.flashcard.in_deck": "In deck"
```

- [ ] **Step 2: Append zh strings**

Open `apps/web/messages/zh/console-notebooks.json`. Add equivalent
Chinese translations with the same keys. For example:

```json
  "study.tabs.assets": "资料",
  "study.tabs.decks": "卡组",
  "study.tabs.review": "复习",
  "study.decks.create": "新建卡组",
  "study.decks.empty": "还没有卡组。",
  "study.cards.create": "新建卡片",
  "study.cards.generate": "生成",
  "study.cards.quiz": "测验",
  "study.cards.review": "复习",
  "study.review.reveal": "查看答案",
  "study.review.rate.again": "再来",
  "study.review.rate.hard": "困难",
  "study.review.rate.good": "良好",
  "study.review.rate.easy": "轻松",
  "study.review.mark_confused": "标记为不懂",
  "study.review.queue_empty": "当前无可复习卡片",
  "study.quiz.start": "开始",
  "study.quiz.submit": "提交",
  "study.flashcard.add_to_deck": "加入卡组",
  "study.flashcard.in_deck": "已在卡组中"
```

- [ ] **Step 3: Append deck-picker CSS**

Append to `apps/web/styles/study-window.css`:

```css
.deck-picker {
  position: absolute;
  z-index: 10;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.1);
  padding: 10px;
  min-width: 240px;
  max-width: 320px;
}
.deck-picker__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
  font-size: 12px;
}
.deck-picker__close {
  background: none;
  border: none;
  cursor: pointer;
  font-size: 14px;
  color: #6b7280;
}
.deck-picker__list {
  list-style: none;
  padding: 0;
  margin: 0;
  max-height: 200px;
  overflow: auto;
}
.deck-picker__item {
  display: block;
  width: 100%;
  text-align: left;
  padding: 6px 8px;
  border: none;
  background: transparent;
  cursor: pointer;
  font-size: 12px;
  border-radius: 4px;
}
.deck-picker__item:hover {
  background: rgba(37, 99, 235, 0.06);
}
.deck-picker__count {
  color: #9ca3af;
  font-size: 10px;
}
.deck-picker__empty {
  padding: 6px 8px;
  font-size: 12px;
  color: #9ca3af;
  text-align: center;
}
.deck-picker__create {
  display: flex;
  gap: 4px;
  margin-top: 8px;
}
.deck-picker__create input {
  flex: 1;
  padding: 4px 6px;
  border: 1px solid #e5e7eb;
  border-radius: 4px;
  font-size: 12px;
}
```

- [ ] **Step 4: Commit**

```bash
git add apps/web/messages/en/console-notebooks.json apps/web/messages/zh/console-notebooks.json apps/web/styles/study-window.css
git commit -m "feat(web): i18n strings for S4 study UI + deck picker CSS"
```

---

### Task 22: Playwright smoke — study loop

**Files:**
- Create: `apps/web/tests/s4-study.spec.ts`

- [ ] **Step 1: Write the test**

```ts
import { test, expect } from "@playwright/test";

async function openNotebookWithStudyWindow(page: import("@playwright/test").Page) {
  await page.goto("/workspace/notebooks");
  await page.getByRole("button", { name: /create/i }).first().click();
  await page.waitForURL(/\/workspace\/notebooks\/[^/]+$/);
  // Open a page so the canvas has something; then click the sidebar "learn" icon
  // to open the Study window. The sidebar testid pattern is sidebar-tab-<id>.
  await page.getByRole("button", { name: /create/i }).first().click();
  await page.getByTestId("sidebar-tab-learn").click();
  await expect(page.getByTestId("study-window")).toBeVisible();
}

test.describe("S4 study loop", () => {
  test("create deck, add card, review Good, queue empty", async ({ page }) => {
    await openNotebookWithStudyWindow(page);
    await page.getByTestId("study-tab-decks").click();

    await page.locator('input[placeholder="New deck name"]').fill("Smoke deck");
    await page.getByTestId("decks-panel-create").click();
    await expect(page.getByTestId("deck-row")).toBeVisible();
    await page.getByTestId("deck-row").click();

    // CardsPanel — manual add.
    await page.locator('input[placeholder="Front"]').fill("Front Q");
    await page.locator('input[placeholder="Back"]').fill("Back A");
    await page.getByTestId("cards-panel-create").click();
    await expect(page.getByTestId("card-row")).toBeVisible();

    // Start review.
    await page.getByTestId("cards-panel-review").click();
    await expect(page.getByTestId("review-session")).toBeVisible();
    await expect(page.getByTestId("review-front")).toContainText("Front Q");

    // Reveal + Good.
    await page.getByTestId("review-reveal").click();
    await expect(page.getByTestId("review-back")).toContainText("Back A");
    await page.getByTestId("review-rate-3").click();

    // Queue empty state.
    await expect(page.getByTestId("review-empty")).toBeVisible({ timeout: 10_000 });
  });
});
```

- [ ] **Step 2: Commit**

```bash
git add apps/web/tests/s4-study.spec.ts
git commit -m "test(web): S4 Playwright smoke for full study loop"
```

---

### Task 23: Final verification

- [ ] **Step 1: Backend full S4 sweep**

```bash
cd apps/api && .venv/bin/pytest \
  tests/test_fsrs.py \
  tests/test_study_decks_models.py \
  tests/test_study_decks_api.py \
  tests/test_study_cards_api.py \
  tests/test_study_review.py \
  tests/test_unified_pipeline_study_confusion.py \
  tests/test_study_confusion_task.py \
  tests/test_study_ai_endpoints.py \
  --cov=app.services.fsrs \
  --cov=app.routers.study_decks \
  --cov=app.routers.study_ai \
  --cov=app.services.study_context \
  --cov-report=term 2>&1 | tail -15
```
Expected: all green; each of the four covered modules ≥80%.

- [ ] **Step 2: Frontend vitest (pre-existing only)**

```bash
cd apps/web && ./node_modules/.bin/vitest run 2>&1 | tail -10
```
Expected: all pre-existing tests still pass (S4 added no vitest).

- [ ] **Step 3: Typecheck**

```bash
cd apps/web && ./node_modules/.bin/tsc --noEmit 2>&1 | tail -15
```
Expected: no **new** type errors from S4 files.

- [ ] **Step 4: Report**

Produce a summary — 23 task commits, backend coverage numbers, any
pre-existing errors. No commit.

---

## Final Acceptance Checklist

- [ ] `alembic upgrade head` lands the `study_decks` + `study_cards`
  tables with indexes.
- [ ] All 25 backend tests pass (FSRS + models + deck CRUD + card CRUD
  + review + pipeline + task + AI endpoints).
- [ ] Coverage on `services/fsrs`, `routers/study_decks`,
  `routers/study_ai`, `services/study_context` ≥ 80 %.
- [ ] Three S4 AI endpoints produce the expected `AIActionLog` rows.
- [ ] Three consecutive Again ratings enqueue a confusion task that
  writes `study_confusion` memory evidence.
- [ ] FlashcardBlock shows "Add to Deck" → picker → adds card → badge
  switches to "In deck ✓".
- [ ] Playwright `s4-study.spec.ts` drives the full happy path.

## Cross-references

- Spec: `docs/superpowers/specs/2026-04-17-study-closure-design.md`
- Product spec: `MRAI_notebook_ai_os_build_spec.md` §10
