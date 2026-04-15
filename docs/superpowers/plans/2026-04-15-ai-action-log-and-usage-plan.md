# S1 — AI Action Log + Usage Event Foundation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a durable audit and usage-metering layer beneath every
`/api/v1/ai/notebook/*` endpoint, enabling trace retrieval and a future
billing rollup.

**Architecture:** A two-table schema (`ai_action_logs` ⟵ 1:N —
`ai_usage_events`) written via an `async with action_log_context(...)`
wrapper around each endpoint's SSE generator. Large input/output
payloads spill over to a MinIO bucket. The Dashscope stream yields one
final synthetic chunk carrying `usage` and `model_id` so the wrapper
can record exact token counts, falling back to character-based
estimation if the upstream omits usage.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0, Alembic, boto3
(MinIO), pytest + pytest-asyncio + pytest-cov, httpx mocking,
Playwright (Node).

**Spec:** `docs/superpowers/specs/2026-04-15-ai-action-log-and-usage-design.md`

---

### Task 1: Add pytest-cov dev dependency

**Files:**
- Modify: `apps/api/pyproject.toml`

- [ ] **Step 1: Add pytest-cov to the dev extras list**

Edit `apps/api/pyproject.toml`. Find the `[project.optional-dependencies]` section:

```toml
[project.optional-dependencies]
dev = [
  "pytest>=8.3.4",
  "pytest-asyncio>=0.25.2",
  "ruff>=0.8.6",
]
```

Replace with:

```toml
[project.optional-dependencies]
dev = [
  "pytest>=8.3.4",
  "pytest-asyncio>=0.25.2",
  "pytest-cov>=6.0",
  "ruff>=0.8.6",
]
```

- [ ] **Step 2: Install the new dev dep**

Run: `cd apps/api && pip install -e ".[dev]"`
Expected: `Successfully installed ... pytest-cov-...`

- [ ] **Step 3: Commit**

```bash
git add apps/api/pyproject.toml
git commit -m "chore(api): add pytest-cov dev dependency for S1 coverage gate"
```

---

### Task 2: Add AIActionLog + AIUsageEvent SQLAlchemy models

**Files:**
- Modify: `apps/api/app/models/entities.py` (append before final `Index(...)` lines at the bottom)
- Modify: `apps/api/app/models/__init__.py`
- Test: `apps/api/tests/test_ai_action_log_models.py` (new)

- [ ] **Step 1: Write the failing model smoke test**

Create `apps/api/tests/test_ai_action_log_models.py` with the
self-contained test-DB pattern used by `test_api_integration.py`:

```python
# ruff: noqa: E402
import atexit
import os
import shutil
import tempfile
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-s1-models-"))
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
from app.models import AIActionLog, AIUsageEvent, User, Workspace


def setup_function() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _seed_user_and_workspace(db) -> tuple[str, str]:
    ws = Workspace(name="WS")
    db.add(ws)
    user = User(email="a@b.co", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(ws)
    db.refresh(user)
    return ws.id, user.id


def test_insert_action_log_with_usage_events() -> None:
    with SessionLocal() as db:
        ws_id, user_id = _seed_user_and_workspace(db)
        log = AIActionLog(
            workspace_id=ws_id,
            user_id=user_id,
            action_type="selection.rewrite",
            scope="selection",
            status="completed",
            duration_ms=1200,
            input_json={"text": "hi"},
            output_json={"text": "hello"},
            output_summary="hello",
            trace_metadata={},
        )
        db.add(log)
        db.commit()
        db.refresh(log)

        usage = AIUsageEvent(
            workspace_id=ws_id,
            user_id=user_id,
            action_log_id=log.id,
            event_type="llm_completion",
            model_id="qwen-plus",
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            count_source="exact",
            meta_json={},
        )
        db.add(usage)
        db.commit()

        rows = db.query(AIActionLog).all()
        usages = db.query(AIUsageEvent).all()

    assert len(rows) == 1
    assert rows[0].status == "completed"
    assert rows[0].action_type == "selection.rewrite"
    assert len(usages) == 1
    assert usages[0].action_log_id == log.id
    assert usages[0].total_tokens == 15
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/api && pytest tests/test_ai_action_log_models.py -v`
Expected: FAIL with `ImportError: cannot import name 'AIActionLog' from 'app.models'`

- [ ] **Step 3: Add the two ORM classes**

Open `apps/api/app/models/entities.py`. Find the very last class
(`StudyChunk`) — append these two classes **before** the trailing
`Index("idx_model_catalog_category", ...)` lines:

```python
class AIActionLog(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "ai_action_logs"

    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    notebook_id: Mapped[str | None] = mapped_column(
        ForeignKey("notebooks.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    page_id: Mapped[str | None] = mapped_column(
        ForeignKey("notebook_pages.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    block_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    action_type: Mapped[str] = mapped_column(String(60), nullable=False)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="running", nullable=False)
    model_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    input_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    output_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    output_summary: Mapped[str] = mapped_column(Text, default="", nullable=False)

    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    trace_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class AIUsageEvent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "ai_usage_events"

    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    action_log_id: Mapped[str] = mapped_column(
        ForeignKey("ai_action_logs.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    model_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    audio_seconds: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    file_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    count_source: Mapped[str] = mapped_column(String(10), default="exact", nullable=False)
    meta_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
```

Right below the new classes (before the trailing `Index(...)` lines for
ModelCatalog/PipelineConfig), add the composite indexes:

```python
Index(
    "ix_ai_action_logs_workspace_created",
    AIActionLog.workspace_id,
    AIActionLog.created_at.desc(),
)
Index(
    "ix_ai_action_logs_page_created",
    AIActionLog.page_id,
    AIActionLog.created_at.desc(),
)
Index(
    "ix_ai_action_logs_user_created",
    AIActionLog.user_id,
    AIActionLog.created_at.desc(),
)
Index(
    "ix_ai_usage_events_workspace_created",
    AIUsageEvent.workspace_id,
    AIUsageEvent.created_at.desc(),
)
```

- [ ] **Step 4: Export the new models**

Open `apps/api/app/models/__init__.py`. Add `AIActionLog` and
`AIUsageEvent` to **both** the `from app.models.entities import (...)`
block (alphabetical) and the `__all__` list:

```python
from app.models.entities import (
    AIActionLog,      # NEW
    AIUsageEvent,     # NEW
    Annotation,
    ApiKey,
    # ... rest unchanged
)

__all__ = [
    "AIActionLog",    # NEW
    "AIUsageEvent",   # NEW
    "Annotation",
    # ... rest unchanged
]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd apps/api && pytest tests/test_ai_action_log_models.py -v`
Expected: `PASSED` — one test.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/models/entities.py apps/api/app/models/__init__.py apps/api/tests/test_ai_action_log_models.py
git commit -m "feat(api): add AIActionLog and AIUsageEvent ORM models"
```

---

### Task 3: Add Alembic migration for the two tables

**Files:**
- Create: `apps/api/alembic/versions/202604160001_ai_action_log.py`

- [ ] **Step 1: Write the migration**

Create `apps/api/alembic/versions/202604160001_ai_action_log.py`:

```python
"""ai action log – add ai_action_logs and ai_usage_events for S1

Revision ID: 202604160001
Revises: 202604150001
Create Date: 2026-04-16
"""

from alembic import op


revision = "202604160001"
down_revision = "202604150001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS ai_action_logs (
            id              VARCHAR(36) PRIMARY KEY,
            workspace_id    VARCHAR(36) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            user_id         VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            notebook_id     VARCHAR(36) REFERENCES notebooks(id) ON DELETE SET NULL,
            page_id         VARCHAR(36) REFERENCES notebook_pages(id) ON DELETE SET NULL,
            block_id        VARCHAR(64),
            action_type     VARCHAR(60) NOT NULL,
            scope           VARCHAR(20) NOT NULL,
            status          VARCHAR(20) NOT NULL DEFAULT 'running',
            model_id        VARCHAR(100),
            duration_ms     INTEGER,
            input_json      JSONB NOT NULL DEFAULT '{}'::jsonb,
            output_json     JSONB NOT NULL DEFAULT '{}'::jsonb,
            output_summary  TEXT NOT NULL DEFAULT '',
            error_code      VARCHAR(50),
            error_message   TEXT,
            trace_metadata  JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE INDEX IF NOT EXISTS ix_ai_action_logs_workspace_id
            ON ai_action_logs(workspace_id);
        CREATE INDEX IF NOT EXISTS ix_ai_action_logs_notebook_id
            ON ai_action_logs(notebook_id);
        CREATE INDEX IF NOT EXISTS ix_ai_action_logs_page_id
            ON ai_action_logs(page_id);
        CREATE INDEX IF NOT EXISTS ix_ai_action_logs_workspace_created
            ON ai_action_logs(workspace_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS ix_ai_action_logs_page_created
            ON ai_action_logs(page_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS ix_ai_action_logs_user_created
            ON ai_action_logs(user_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS ai_usage_events (
            id                 VARCHAR(36) PRIMARY KEY,
            workspace_id       VARCHAR(36) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            user_id            VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            action_log_id      VARCHAR(36) NOT NULL REFERENCES ai_action_logs(id) ON DELETE CASCADE,
            event_type         VARCHAR(30) NOT NULL,
            model_id           VARCHAR(100),
            prompt_tokens      INTEGER NOT NULL DEFAULT 0,
            completion_tokens  INTEGER NOT NULL DEFAULT 0,
            total_tokens       INTEGER NOT NULL DEFAULT 0,
            audio_seconds      DOUBLE PRECISION NOT NULL DEFAULT 0,
            file_count         INTEGER NOT NULL DEFAULT 0,
            count_source       VARCHAR(10) NOT NULL DEFAULT 'exact',
            meta_json          JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE INDEX IF NOT EXISTS ix_ai_usage_events_workspace_id
            ON ai_usage_events(workspace_id);
        CREATE INDEX IF NOT EXISTS ix_ai_usage_events_action
            ON ai_usage_events(action_log_id);
        CREATE INDEX IF NOT EXISTS ix_ai_usage_events_workspace_created
            ON ai_usage_events(workspace_id, created_at DESC);
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS ai_usage_events CASCADE;
        DROP TABLE IF EXISTS ai_action_logs CASCADE;
    """)
```

- [ ] **Step 2: Verify model smoke test still passes (SQLite path uses Base.metadata.create_all, not Alembic)**

Run: `cd apps/api && pytest tests/test_ai_action_log_models.py -v`
Expected: `PASSED`.

- [ ] **Step 3: Commit**

```bash
git add apps/api/alembic/versions/202604160001_ai_action_log.py
git commit -m "feat(api): alembic migration for ai_action_logs and ai_usage_events"
```

---

### Task 4: Extend StreamChunk to carry usage + model_id

**Files:**
- Modify: `apps/api/app/services/dashscope_stream.py`
- Test: `apps/api/tests/test_dashscope_stream_usage.py` (new)

- [ ] **Step 1: Write the failing test**

Create `apps/api/tests/test_dashscope_stream_usage.py`:

```python
# ruff: noqa: E402
import asyncio
import json
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ["ENV"] = "test"

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.dashscope_stream import StreamChunk, chat_completion_stream


class _FakeResponse:
    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    def raise_for_status(self) -> None:
        return None

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _FakeCtx:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    async def __aenter__(self) -> _FakeResponse:
        return self._response

    async def __aexit__(self, *a) -> None:
        return None


class _FakeClient:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    def stream(self, *a, **kw) -> _FakeCtx:
        return _FakeCtx(self._response)


def _drain(gen) -> list[StreamChunk]:
    async def go() -> list[StreamChunk]:
        return [chunk async for chunk in gen]
    return asyncio.run(go())


def test_final_chunk_carries_usage_and_model_id() -> None:
    lines = [
        "data: " + json.dumps({
            "model": "qwen-plus",
            "choices": [{"delta": {"content": "hello"}, "finish_reason": None}],
        }),
        "data: " + json.dumps({
            "model": "qwen-plus",
            "choices": [],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        }),
        "data: [DONE]",
    ]
    fake_client = _FakeClient(_FakeResponse(lines))
    with patch("app.services.dashscope_stream.get_client", return_value=fake_client):
        chunks = _drain(chat_completion_stream([{"role": "user", "content": "hi"}]))

    assert any(c.content == "hello" for c in chunks)
    final = chunks[-1]
    assert final.content == ""
    assert final.usage == {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}
    assert final.model_id == "qwen-plus"
    assert final.finish_reason == "stop"


def test_final_chunk_without_usage_still_yielded() -> None:
    lines = [
        "data: " + json.dumps({
            "model": "qwen-plus",
            "choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}],
        }),
        "data: [DONE]",
    ]
    fake_client = _FakeClient(_FakeResponse(lines))
    with patch("app.services.dashscope_stream.get_client", return_value=fake_client):
        chunks = _drain(chat_completion_stream([{"role": "user", "content": "hi"}]))

    final = chunks[-1]
    assert final.usage is None
    # model_id captured from an earlier chunk even if last had it
    assert final.model_id == "qwen-plus"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && pytest tests/test_dashscope_stream_usage.py -v`
Expected: FAIL — `AttributeError: 'StreamChunk' object has no attribute 'usage'`

- [ ] **Step 3: Extend StreamChunk + stream loop**

Replace `apps/api/app/services/dashscope_stream.py` content from the
dataclass block through the end of the async function. The final file
should read:

```python
"""Streaming variant of DashScope chat completion API."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import httpx

from app.core.config import settings
from app.services.dashscope_client import (
    InferenceTimeoutError,
    SearchSource,
    UpstreamServiceError,
    _build_effective_search_options,
    extract_search_sources,
)
from app.services.dashscope_http import DASHSCOPE_BASE_URL, dashscope_headers, get_client

logger = logging.getLogger(__name__)


@dataclass
class StreamChunk:
    content: str = ""
    reasoning_content: str = ""
    finish_reason: str | None = None
    search_sources: list[SearchSource] = field(default_factory=list)
    usage: dict[str, Any] | None = None
    model_id: str | None = None


async def chat_completion_stream(
    messages: list[dict],
    model: str | None = None,
    *,
    temperature: float = 0.7,
    max_tokens: int = 2048,
    enable_thinking: bool | None = None,
    enable_search: bool | None = None,
    search_options: dict[str, Any] | None = None,
    timeout: float = 120.0,
) -> AsyncIterator[StreamChunk]:
    """Stream chat completion tokens from DashScope OpenAI-compatible API.

    Yields StreamChunk objects as they arrive; ends with one synthetic
    closing chunk carrying ``usage`` and ``model_id`` (either may be
    ``None`` if the upstream did not emit them).
    """
    model = model or settings.dashscope_model

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    effective_search_options = _build_effective_search_options(
        enable_search=enable_search,
        search_options=search_options,
    )
    if enable_thinking is not None:
        payload["enable_thinking"] = enable_thinking
    if enable_search is not None:
        payload["enable_search"] = enable_search
    if effective_search_options:
        payload["search_options"] = effective_search_options

    captured_usage: dict[str, Any] | None = None
    captured_model_id: str | None = None

    try:
        client = get_client()
        async with client.stream(
            "POST",
            f"{DASHSCOPE_BASE_URL}/chat/completions",
            headers=dashscope_headers(),
            json=payload,
            timeout=timeout,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                raw = line[len("data:"):].strip()
                if raw == "[DONE]":
                    break
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning("dashscope_stream: failed to parse SSE line: %r", raw)
                    continue

                # Capture model_id from any chunk that has it
                if data.get("model") and not captured_model_id:
                    captured_model_id = data["model"]
                # Capture usage from any chunk that has it
                usage_block = data.get("usage")
                if isinstance(usage_block, dict):
                    captured_usage = usage_block

                choices = data.get("choices")
                if not choices:
                    # usage-only chunk — already captured above
                    continue

                delta = choices[0].get("delta", {})
                finish_reason = choices[0].get("finish_reason")

                content = delta.get("content") or ""
                reasoning_content = delta.get("reasoning_content") or ""
                search_sources = extract_search_sources(data, choices[0], delta)

                if content or reasoning_content or finish_reason or search_sources:
                    yield StreamChunk(
                        content=content,
                        reasoning_content=reasoning_content,
                        finish_reason=finish_reason,
                        search_sources=search_sources,
                    )
        # Synthetic closing chunk — even if usage is None
        yield StreamChunk(
            content="",
            finish_reason="stop",
            usage=captured_usage,
            model_id=captured_model_id,
        )
    except (InferenceTimeoutError, UpstreamServiceError):
        raise
    except httpx.TimeoutException as exc:
        raise InferenceTimeoutError("Inference timeout") from exc
    except httpx.HTTPError as exc:
        raise UpstreamServiceError("Model API unavailable") from exc
    except Exception as exc:  # noqa: BLE001
        raise UpstreamServiceError(f"Unexpected model API error: {exc}") from exc
```

- [ ] **Step 4: Run to verify pass**

Run: `cd apps/api && pytest tests/test_dashscope_stream_usage.py -v`
Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/services/dashscope_stream.py apps/api/tests/test_dashscope_stream_usage.py
git commit -m "feat(api): StreamChunk carries usage and model_id via synthetic closing chunk"
```

---

### Task 5: Create FakeS3Client test fixture

**Files:**
- Create: `apps/api/tests/fixtures/__init__.py`
- Create: `apps/api/tests/fixtures/fake_s3.py`
- Test: `apps/api/tests/test_fake_s3.py` (new)

- [ ] **Step 1: Write the failing test**

Create `apps/api/tests/test_fake_s3.py`:

```python
from botocore.exceptions import ClientError
import pytest

from tests.fixtures.fake_s3 import FakeS3Client


def test_put_and_get_roundtrip() -> None:
    client = FakeS3Client()
    client.create_bucket(Bucket="b1")
    client.put_object(Bucket="b1", Key="k1", Body=b"hello", ContentType="application/json")

    resp = client.get_object(Bucket="b1", Key="k1")
    assert resp["Body"].read() == b"hello"
    assert resp["ContentType"] == "application/json"


def test_head_bucket_404_when_missing() -> None:
    client = FakeS3Client()
    with pytest.raises(ClientError) as exc:
        client.head_bucket(Bucket="nope")
    assert exc.value.response["Error"]["Code"] == "404"


def test_get_object_missing_key() -> None:
    client = FakeS3Client()
    client.create_bucket(Bucket="b1")
    with pytest.raises(ClientError) as exc:
        client.get_object(Bucket="b1", Key="absent")
    assert exc.value.response["Error"]["Code"] == "NoSuchKey"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && pytest tests/test_fake_s3.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tests.fixtures.fake_s3'`

- [ ] **Step 3: Create the fixture package**

Create `apps/api/tests/fixtures/__init__.py` as an empty file.

Create `apps/api/tests/fixtures/fake_s3.py`:

```python
"""A minimal boto3-compatible fake S3 client for tests.

Implements only the surface used by the ai_action_logger:
``head_bucket``, ``create_bucket``, ``put_object``, ``get_object``.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Any

from botocore.exceptions import ClientError


@dataclass
class _StoredObject:
    body: bytes
    content_type: str


def _client_error(code: str, message: str, op_name: str) -> ClientError:
    return ClientError(
        {"Error": {"Code": code, "Message": message}},
        op_name,
    )


@dataclass
class FakeS3Client:
    _store: dict[tuple[str, str], _StoredObject] = field(default_factory=dict)
    _buckets: set[str] = field(default_factory=set)

    def head_bucket(self, *, Bucket: str) -> dict[str, Any]:
        if Bucket not in self._buckets:
            raise _client_error("404", "Not Found", "HeadBucket")
        return {}

    def create_bucket(self, *, Bucket: str, **_: Any) -> dict[str, Any]:
        self._buckets.add(Bucket)
        return {"Location": f"/{Bucket}"}

    def put_object(
        self, *, Bucket: str, Key: str, Body: Any,
        ContentType: str = "application/octet-stream", **_: Any,
    ) -> dict[str, Any]:
        if Bucket not in self._buckets:
            raise _client_error("NoSuchBucket", f"bucket {Bucket} missing", "PutObject")
        if isinstance(Body, (bytes, bytearray)):
            data = bytes(Body)
        elif isinstance(Body, str):
            data = Body.encode("utf-8")
        else:
            data = Body.read()
        self._store[(Bucket, Key)] = _StoredObject(body=data, content_type=ContentType)
        return {"ETag": f'"{len(data)}"'}

    def get_object(self, *, Bucket: str, Key: str, **_: Any) -> dict[str, Any]:
        obj = self._store.get((Bucket, Key))
        if obj is None:
            raise _client_error("NoSuchKey", f"{Bucket}/{Key} missing", "GetObject")
        return {
            "Body": io.BytesIO(obj.body),
            "ContentType": obj.content_type,
            "ContentLength": len(obj.body),
        }
```

- [ ] **Step 4: Run to verify pass**

Run: `cd apps/api && pytest tests/test_fake_s3.py -v`
Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add apps/api/tests/fixtures/__init__.py apps/api/tests/fixtures/fake_s3.py apps/api/tests/test_fake_s3.py
git commit -m "test(api): add FakeS3Client for S1 storage tests"
```

---

### Task 6: ai_action_logger context manager — enter + exit happy path

**Files:**
- Create: `apps/api/app/services/ai_action_logger.py`
- Test: `apps/api/tests/test_ai_action_logger.py` (new)

- [ ] **Step 1: Write the failing test**

Create `apps/api/tests/test_ai_action_logger.py` with the self-contained
test-DB pattern:

```python
# ruff: noqa: E402
import asyncio
import atexit
import os
import shutil
import tempfile
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-s1-logger-"))
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

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models import AIActionLog, AIUsageEvent, User, Workspace
from app.services.ai_action_logger import action_log_context


def setup_function() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _seed() -> tuple[str, str]:
    with SessionLocal() as db:
        ws = Workspace(name="WS")
        db.add(ws)
        user = User(email="a@b.co", password_hash="x")
        db.add(user)
        db.commit()
        db.refresh(ws)
        db.refresh(user)
        return ws.id, user.id


def test_happy_path_creates_running_row_then_completed() -> None:
    ws_id, user_id = _seed()

    async def go() -> str:
        with SessionLocal() as db:
            async with action_log_context(
                db,
                workspace_id=ws_id,
                user_id=user_id,
                action_type="selection.rewrite",
                scope="selection",
            ) as log:
                assert log.log_id
                assert not log.is_null
                # mid-flight row exists with status=running
                mid = db.query(AIActionLog).filter_by(id=log.log_id).one()
                assert mid.status == "running"
                return log.log_id

    log_id = asyncio.run(go())

    with SessionLocal() as db:
        row = db.query(AIActionLog).filter_by(id=log_id).one()
        assert row.status == "completed"
        assert row.duration_ms is not None and row.duration_ms >= 0
        assert row.error_code is None
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && pytest tests/test_ai_action_logger.py::test_happy_path_creates_running_row_then_completed -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.ai_action_logger'`

- [ ] **Step 3: Create the skeleton service**

Create `apps/api/app/services/ai_action_logger.py`:

```python
"""S1: AI Action Log + Usage Event context manager.

Usage::

    async with action_log_context(
        db,
        workspace_id=ws_id, user_id=user_id,
        action_type="selection.rewrite", scope="selection",
        page_id=page_id,
    ) as log:
        log.set_input({"selected_text": "..."})
        async for chunk in stream(...):
            yield sse_event(chunk)
        log.set_output(full_content)
        log.record_usage(
            event_type="llm_completion",
            model_id="qwen-plus",
            prompt_tokens=10, completion_tokens=5,
            count_source="exact",
        )
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from sqlalchemy.orm import Session

from app.models import AIActionLog, AIUsageEvent

logger = logging.getLogger(__name__)


@dataclass
class _UsageBuffer:
    event_type: str
    model_id: str | None
    prompt_tokens: int
    completion_tokens: int
    audio_seconds: float
    file_count: int
    count_source: str
    meta: dict[str, Any]


class ActionLogHandle:
    """Public handle for the in-progress action log."""

    def __init__(
        self,
        *,
        db: Session,
        log_id: str,
        start_monotonic: float,
    ) -> None:
        self._db = db
        self._log_id = log_id
        self._start = start_monotonic
        self._input: dict[str, Any] | None = None
        self._output: dict[str, Any] | None = None
        self._output_summary: str = ""
        self._model_id: str | None = None
        self._trace: dict[str, Any] = {}
        self._usage: list[_UsageBuffer] = []

    # -- public attributes ------------------------------------------------
    @property
    def log_id(self) -> str:
        return self._log_id

    @property
    def is_null(self) -> bool:
        return False

    # -- public methods (filled in later tasks) ---------------------------
    def set_input(self, payload: dict[str, Any]) -> None:
        self._input = dict(payload)

    def set_output(self, content: Any) -> None:
        if isinstance(content, str):
            self._output = {"content": content}
            self._output_summary = content[:200]
        else:
            self._output = dict(content) if isinstance(content, dict) else {"value": content}
            preview_src = self._output.get("content") or self._output.get("value") or ""
            self._output_summary = str(preview_src)[:200]

    def record_usage(
        self,
        *,
        event_type: str,
        model_id: str | None = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        audio_seconds: float = 0.0,
        file_count: int = 0,
        count_source: str = "exact",
        meta: dict[str, Any] | None = None,
    ) -> None:
        self._usage.append(_UsageBuffer(
            event_type=event_type,
            model_id=model_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            audio_seconds=audio_seconds,
            file_count=file_count,
            count_source=count_source,
            meta=dict(meta or {}),
        ))
        if model_id and not self._model_id:
            self._model_id = model_id

    def set_trace_metadata(self, data: dict[str, Any]) -> None:
        self._trace.update(data)

    # -- internal --------------------------------------------------------
    def _duration_ms(self) -> int:
        return int((time.monotonic() - self._start) * 1000)

    def _flush_success(self) -> None:
        row = self._db.query(AIActionLog).filter_by(id=self._log_id).one()
        row.status = "completed"
        row.duration_ms = self._duration_ms()
        if self._input is not None:
            row.input_json = self._input
        if self._output is not None:
            row.output_json = self._output
        row.output_summary = self._output_summary
        row.model_id = self._model_id
        row.trace_metadata = dict(self._trace)
        self._db.add(row)
        for buf in self._usage:
            self._db.add(AIUsageEvent(
                workspace_id=row.workspace_id,
                user_id=row.user_id,
                action_log_id=row.id,
                event_type=buf.event_type,
                model_id=buf.model_id,
                prompt_tokens=buf.prompt_tokens,
                completion_tokens=buf.completion_tokens,
                total_tokens=buf.prompt_tokens + buf.completion_tokens,
                audio_seconds=buf.audio_seconds,
                file_count=buf.file_count,
                count_source=buf.count_source,
                meta_json=buf.meta,
            ))
        self._db.commit()

    def _flush_failure(self, exc: BaseException) -> None:
        row = self._db.query(AIActionLog).filter_by(id=self._log_id).one()
        row.status = "failed"
        row.duration_ms = self._duration_ms()
        row.error_code = type(exc).__name__[:50]
        row.error_message = str(exc)[:2000]
        if self._input is not None:
            row.input_json = self._input
        if self._output is not None:
            row.output_json = self._output
        row.output_summary = self._output_summary
        row.trace_metadata = dict(self._trace)
        self._db.add(row)
        self._db.commit()


@asynccontextmanager
async def action_log_context(
    db: Session,
    *,
    workspace_id: str,
    user_id: str,
    action_type: str,
    scope: str,
    notebook_id: str | None = None,
    page_id: str | None = None,
    block_id: str | None = None,
) -> AsyncIterator[ActionLogHandle]:
    start = time.monotonic()
    row = AIActionLog(
        workspace_id=workspace_id,
        user_id=user_id,
        notebook_id=notebook_id,
        page_id=page_id,
        block_id=block_id,
        action_type=action_type,
        scope=scope,
        status="running",
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    handle = ActionLogHandle(db=db, log_id=row.id, start_monotonic=start)
    try:
        yield handle
    except BaseException as exc:
        try:
            handle._flush_failure(exc)
        except Exception:  # pragma: no cover
            logger.exception("ai_action_logger: flush_failure failed")
        raise
    else:
        try:
            handle._flush_success()
        except Exception:
            logger.exception("ai_action_logger: flush_success failed")
```

- [ ] **Step 4: Run to verify pass**

Run: `cd apps/api && pytest tests/test_ai_action_logger.py::test_happy_path_creates_running_row_then_completed -v`
Expected: PASSED.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/services/ai_action_logger.py apps/api/tests/test_ai_action_logger.py
git commit -m "feat(api): ai_action_logger context manager (happy path)"
```

---

### Task 7: record_usage creates usage event rows

**Files:**
- Modify: `apps/api/tests/test_ai_action_logger.py`

- [ ] **Step 1: Append the test**

Append to `apps/api/tests/test_ai_action_logger.py`:

```python
def test_record_usage_single_event() -> None:
    ws_id, user_id = _seed()

    async def go() -> str:
        with SessionLocal() as db:
            async with action_log_context(
                db,
                workspace_id=ws_id,
                user_id=user_id,
                action_type="selection.rewrite",
                scope="selection",
            ) as log:
                log.record_usage(
                    event_type="llm_completion",
                    model_id="qwen-plus",
                    prompt_tokens=7,
                    completion_tokens=3,
                    count_source="exact",
                )
                return log.log_id

    log_id = asyncio.run(go())

    with SessionLocal() as db:
        rows = db.query(AIUsageEvent).filter_by(action_log_id=log_id).all()
    assert len(rows) == 1
    assert rows[0].event_type == "llm_completion"
    assert rows[0].model_id == "qwen-plus"
    assert rows[0].prompt_tokens == 7
    assert rows[0].total_tokens == 10
    assert rows[0].count_source == "exact"


def test_record_usage_multiple_events() -> None:
    ws_id, user_id = _seed()

    async def go() -> str:
        with SessionLocal() as db:
            async with action_log_context(
                db,
                workspace_id=ws_id,
                user_id=user_id,
                action_type="ask",
                scope="notebook",
            ) as log:
                log.record_usage(event_type="llm_completion", prompt_tokens=5)
                log.record_usage(event_type="embedding", file_count=2)
                return log.log_id

    log_id = asyncio.run(go())

    with SessionLocal() as db:
        rows = (
            db.query(AIUsageEvent)
            .filter_by(action_log_id=log_id)
            .order_by(AIUsageEvent.event_type.asc())
            .all()
        )
    assert len(rows) == 2
    assert rows[0].event_type == "embedding" and rows[0].file_count == 2
    assert rows[1].event_type == "llm_completion" and rows[1].prompt_tokens == 5


def test_record_usage_estimated_source() -> None:
    ws_id, user_id = _seed()

    async def go() -> str:
        with SessionLocal() as db:
            async with action_log_context(
                db,
                workspace_id=ws_id,
                user_id=user_id,
                action_type="page.summarize",
                scope="page",
            ) as log:
                log.record_usage(
                    event_type="llm_completion",
                    prompt_tokens=100,
                    completion_tokens=50,
                    count_source="estimated",
                )
                return log.log_id

    log_id = asyncio.run(go())

    with SessionLocal() as db:
        row = db.query(AIUsageEvent).filter_by(action_log_id=log_id).one()
    assert row.count_source == "estimated"
    assert row.total_tokens == 150
```

- [ ] **Step 2: Run**

Run: `cd apps/api && pytest tests/test_ai_action_logger.py -v`
Expected: 4 PASSED (including the earlier one).

- [ ] **Step 3: Commit**

```bash
git add apps/api/tests/test_ai_action_logger.py
git commit -m "test(api): cover record_usage flush behavior"
```

---

### Task 8: set_output populates output_summary

**Files:**
- Modify: `apps/api/tests/test_ai_action_logger.py`

- [ ] **Step 1: Append the test**

```python
def test_set_output_string_summary_truncates_to_200() -> None:
    ws_id, user_id = _seed()
    long_text = "x" * 500

    async def go() -> str:
        with SessionLocal() as db:
            async with action_log_context(
                db,
                workspace_id=ws_id, user_id=user_id,
                action_type="selection.rewrite", scope="selection",
            ) as log:
                log.set_output(long_text)
                return log.log_id

    log_id = asyncio.run(go())

    with SessionLocal() as db:
        row = db.query(AIActionLog).filter_by(id=log_id).one()
    assert len(row.output_summary) == 200
    assert row.output_summary == "x" * 200
    assert row.output_json == {"content": long_text}


def test_set_output_dict_uses_content_key_for_summary() -> None:
    ws_id, user_id = _seed()

    async def go() -> str:
        with SessionLocal() as db:
            async with action_log_context(
                db, workspace_id=ws_id, user_id=user_id,
                action_type="page.tag", scope="page",
            ) as log:
                log.set_output({"content": "short answer", "extra": 42})
                return log.log_id

    log_id = asyncio.run(go())
    with SessionLocal() as db:
        row = db.query(AIActionLog).filter_by(id=log_id).one()
    assert row.output_summary == "short answer"
    assert row.output_json["extra"] == 42
```

- [ ] **Step 2: Run**

Run: `cd apps/api && pytest tests/test_ai_action_logger.py -v`
Expected: 6 PASSED.

- [ ] **Step 3: Commit**

```bash
git add apps/api/tests/test_ai_action_logger.py
git commit -m "test(api): cover set_output summary extraction"
```

---

### Task 9: set_trace_metadata merges shallowly

**Files:**
- Modify: `apps/api/tests/test_ai_action_logger.py`

- [ ] **Step 1: Append test**

```python
def test_set_trace_metadata_merges_keys() -> None:
    ws_id, user_id = _seed()

    async def go() -> str:
        with SessionLocal() as db:
            async with action_log_context(
                db, workspace_id=ws_id, user_id=user_id,
                action_type="ask", scope="notebook",
            ) as log:
                log.set_trace_metadata({"retrieval_sources": [{"type": "memory"}]})
                log.set_trace_metadata({"token_budget": 4000})
                log.set_trace_metadata({"retrieval_sources": [{"type": "page"}]})
                return log.log_id

    log_id = asyncio.run(go())
    with SessionLocal() as db:
        row = db.query(AIActionLog).filter_by(id=log_id).one()
    assert row.trace_metadata["token_budget"] == 4000
    assert row.trace_metadata["retrieval_sources"] == [{"type": "page"}]
```

- [ ] **Step 2: Run**

Run: `cd apps/api && pytest tests/test_ai_action_logger.py -v`
Expected: 7 PASSED.

- [ ] **Step 3: Commit**

```bash
git add apps/api/tests/test_ai_action_logger.py
git commit -m "test(api): cover set_trace_metadata shallow merge"
```

---

### Task 10: Exception inside body marks status=failed and re-raises

**Files:**
- Modify: `apps/api/tests/test_ai_action_logger.py`

- [ ] **Step 1: Append test**

```python
def test_exception_inside_body_marks_failed_and_reraises() -> None:
    ws_id, user_id = _seed()

    async def go() -> str:
        with SessionLocal() as db:
            try:
                async with action_log_context(
                    db, workspace_id=ws_id, user_id=user_id,
                    action_type="ask", scope="page",
                ) as log:
                    log.set_input({"q": "a"})
                    log_id_local = log.log_id
                    raise RuntimeError("upstream boom")
            except RuntimeError:
                return log_id_local
            return ""

    log_id = asyncio.run(go())
    assert log_id
    with SessionLocal() as db:
        row = db.query(AIActionLog).filter_by(id=log_id).one()
    assert row.status == "failed"
    assert row.error_code == "RuntimeError"
    assert "upstream boom" in (row.error_message or "")
    assert row.input_json == {"q": "a"}
```

- [ ] **Step 2: Run to verify pass**

Run: `cd apps/api && pytest tests/test_ai_action_logger.py -v`
Expected: 8 PASSED (exception path already implemented in Task 6).

- [ ] **Step 3: Commit**

```bash
git add apps/api/tests/test_ai_action_logger.py
git commit -m "test(api): cover exception-in-body marks status=failed"
```

---

### Task 11: MinIO overflow for large input/output

**Files:**
- Modify: `apps/api/app/core/config.py` (one new setting)
- Modify: `apps/api/app/services/ai_action_logger.py`
- Modify: `apps/api/tests/test_ai_action_logger.py`

- [ ] **Step 1: Append the failing test**

Append to `apps/api/tests/test_ai_action_logger.py`:

```python
import app.services.storage as storage_service
from tests.fixtures.fake_s3 import FakeS3Client


def _install_fake_s3(fake: FakeS3Client) -> None:
    storage_service.get_s3_client.cache_clear()

    def _get() -> FakeS3Client:
        return fake

    # Replace the lru_cache'd factory with our fake for the test session.
    storage_service.get_s3_client = _get  # type: ignore[assignment]


def test_set_input_large_payload_overflows_to_minio() -> None:
    ws_id, user_id = _seed()
    fake = FakeS3Client()
    _install_fake_s3(fake)
    payload = {"text": "a" * 20_000}

    async def go() -> str:
        with SessionLocal() as db:
            async with action_log_context(
                db, workspace_id=ws_id, user_id=user_id,
                action_type="selection.rewrite", scope="selection",
            ) as log:
                log.set_input(payload)
                return log.log_id

    log_id = asyncio.run(go())
    with SessionLocal() as db:
        row = db.query(AIActionLog).filter_by(id=log_id).one()
    # DB column holds a pointer, not the full payload
    assert "_overflow_ref" in row.input_json
    assert row.input_json["_overflow_ref"].endswith(f"{log_id}-input.json")
    assert len(row.input_json["_preview"]) <= 500
    # MinIO has the full payload
    key = row.input_json["_overflow_ref"]
    stored = fake.get_object(Bucket="ai-action-payloads", Key=key)
    import json as _json
    assert _json.loads(stored["Body"].read().decode("utf-8")) == payload


def test_set_output_small_payload_stored_inline() -> None:
    ws_id, user_id = _seed()
    fake = FakeS3Client()
    _install_fake_s3(fake)

    async def go() -> str:
        with SessionLocal() as db:
            async with action_log_context(
                db, workspace_id=ws_id, user_id=user_id,
                action_type="page.summarize", scope="page",
            ) as log:
                log.set_output("small content")
                return log.log_id

    log_id = asyncio.run(go())
    with SessionLocal() as db:
        row = db.query(AIActionLog).filter_by(id=log_id).one()
    assert "_overflow_ref" not in row.output_json
    assert row.output_json == {"content": "small content"}
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && pytest tests/test_ai_action_logger.py::test_set_input_large_payload_overflows_to_minio -v`
Expected: FAIL — `_overflow_ref` not found.

- [ ] **Step 3: Add the config setting**

Open `apps/api/app/core/config.py`. Find the block with `s3_private_bucket: str = "qihang-private"` and add below it:

```python
    s3_ai_action_payloads_bucket: str = "ai-action-payloads"
```

- [ ] **Step 4: Extend the logger with overflow logic**

Open `apps/api/app/services/ai_action_logger.py`. Add the following
imports at the top (after existing imports):

```python
import json
from datetime import datetime, timezone

from botocore.exceptions import ClientError

from app.core.config import settings
from app.services import storage as storage_service
```

Add helper functions just above the `ActionLogHandle` class:

```python
OVERFLOW_THRESHOLD_BYTES = 10 * 1024
OVERFLOW_PREVIEW_CHARS = 500


def _json_size_bytes(payload: Any) -> int:
    return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def _ensure_bucket(bucket: str) -> None:
    client = storage_service.get_s3_client()
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("404", "NoSuchBucket", "NotFound"):
            client.create_bucket(Bucket=bucket)
        else:
            raise


def _overflow_key(workspace_id: str, log_id: str, field: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"{workspace_id}/{ts}/{log_id}-{field}.json"


def _maybe_overflow(
    payload: dict[str, Any],
    *,
    workspace_id: str,
    log_id: str,
    field: str,
) -> dict[str, Any]:
    if _json_size_bytes(payload) <= OVERFLOW_THRESHOLD_BYTES:
        return payload
    bucket = settings.s3_ai_action_payloads_bucket
    key = _overflow_key(workspace_id, log_id, field)
    try:
        _ensure_bucket(bucket)
        client = storage_service.get_s3_client()
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            ContentType="application/json",
        )
    except Exception:
        logger.exception("ai_action_logger: overflow upload failed; storing inline")
        return payload
    preview_src = json.dumps(payload, ensure_ascii=False)
    return {
        "_overflow_ref": key,
        "_preview": preview_src[:OVERFLOW_PREVIEW_CHARS],
    }
```

Modify `ActionLogHandle.__init__` to accept workspace_id and log_id:

```python
    def __init__(
        self,
        *,
        db: Session,
        log_id: str,
        workspace_id: str,
        start_monotonic: float,
    ) -> None:
        self._db = db
        self._log_id = log_id
        self._workspace_id = workspace_id
        self._start = start_monotonic
        self._input: dict[str, Any] | None = None
        self._output: dict[str, Any] | None = None
        self._output_summary: str = ""
        self._model_id: str | None = None
        self._trace: dict[str, Any] = {}
        self._usage: list[_UsageBuffer] = []
```

Update `_flush_success` to call `_maybe_overflow` before writing
input/output:

```python
    def _flush_success(self) -> None:
        row = self._db.query(AIActionLog).filter_by(id=self._log_id).one()
        row.status = "completed"
        row.duration_ms = self._duration_ms()
        if self._input is not None:
            row.input_json = _maybe_overflow(
                self._input, workspace_id=self._workspace_id,
                log_id=self._log_id, field="input",
            )
        if self._output is not None:
            row.output_json = _maybe_overflow(
                self._output, workspace_id=self._workspace_id,
                log_id=self._log_id, field="output",
            )
        row.output_summary = self._output_summary
        row.model_id = self._model_id
        row.trace_metadata = dict(self._trace)
        self._db.add(row)
        for buf in self._usage:
            self._db.add(AIUsageEvent(
                workspace_id=row.workspace_id,
                user_id=row.user_id,
                action_log_id=row.id,
                event_type=buf.event_type,
                model_id=buf.model_id,
                prompt_tokens=buf.prompt_tokens,
                completion_tokens=buf.completion_tokens,
                total_tokens=buf.prompt_tokens + buf.completion_tokens,
                audio_seconds=buf.audio_seconds,
                file_count=buf.file_count,
                count_source=buf.count_source,
                meta_json=buf.meta,
            ))
        self._db.commit()
```

Apply the same `_maybe_overflow` treatment inside `_flush_failure`.

Update the `action_log_context` to pass `workspace_id` into the handle:

```python
    handle = ActionLogHandle(
        db=db, log_id=row.id,
        workspace_id=workspace_id,
        start_monotonic=start,
    )
```

- [ ] **Step 5: Run to verify pass**

Run: `cd apps/api && pytest tests/test_ai_action_logger.py -v`
Expected: 10 PASSED.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/core/config.py apps/api/app/services/ai_action_logger.py apps/api/tests/test_ai_action_logger.py
git commit -m "feat(api): overflow large action-log payloads to MinIO"
```

---

### Task 12: NullActionLogHandle when DB enter fails

**Files:**
- Modify: `apps/api/app/services/ai_action_logger.py`
- Modify: `apps/api/tests/test_ai_action_logger.py`

- [ ] **Step 1: Append the failing test**

```python
from unittest.mock import patch


def test_enter_db_failure_returns_null_handle() -> None:
    ws_id, user_id = _seed()

    async def go() -> tuple[str, bool]:
        with SessionLocal() as db:
            # Force the initial commit to blow up
            with patch.object(db, "commit", side_effect=RuntimeError("db down")):
                async with action_log_context(
                    db, workspace_id=ws_id, user_id=user_id,
                    action_type="selection.rewrite", scope="selection",
                ) as log:
                    assert log.is_null is True
                    assert log.log_id == ""
                    # All methods should be safe no-ops
                    log.set_input({"x": 1})
                    log.set_output("nope")
                    log.record_usage(event_type="llm_completion")
                    log.set_trace_metadata({"k": "v"})
                    return log.log_id, log.is_null
        return "", False

    log_id, is_null = asyncio.run(go())
    assert log_id == ""
    assert is_null is True
    # Nothing was persisted
    with SessionLocal() as db:
        assert db.query(AIActionLog).count() == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && pytest tests/test_ai_action_logger.py::test_enter_db_failure_returns_null_handle -v`
Expected: FAIL — the RuntimeError propagates.

- [ ] **Step 3: Add NullActionLogHandle**

In `apps/api/app/services/ai_action_logger.py`, just below
`ActionLogHandle`, add:

```python
class NullActionLogHandle:
    """Safe no-op handle returned when the DB cannot accept the log row."""

    @property
    def log_id(self) -> str:
        return ""

    @property
    def is_null(self) -> bool:
        return True

    def set_input(self, payload: dict[str, Any]) -> None:
        return None

    def set_output(self, content: Any) -> None:
        return None

    def record_usage(self, **_: Any) -> None:
        return None

    def set_trace_metadata(self, data: dict[str, Any]) -> None:
        return None
```

Wrap the initial insert in `action_log_context` with a try/except:

```python
@asynccontextmanager
async def action_log_context(
    db: Session,
    *,
    workspace_id: str,
    user_id: str,
    action_type: str,
    scope: str,
    notebook_id: str | None = None,
    page_id: str | None = None,
    block_id: str | None = None,
) -> AsyncIterator["ActionLogHandle | NullActionLogHandle"]:
    start = time.monotonic()
    try:
        row = AIActionLog(
            workspace_id=workspace_id,
            user_id=user_id,
            notebook_id=notebook_id,
            page_id=page_id,
            block_id=block_id,
            action_type=action_type,
            scope=scope,
            status="running",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
    except Exception:
        logger.exception("ai_action_logger: enter failed, returning null handle")
        try:
            db.rollback()
        except Exception:  # pragma: no cover
            pass
        yield NullActionLogHandle()
        return

    handle = ActionLogHandle(
        db=db, log_id=row.id,
        workspace_id=workspace_id,
        start_monotonic=start,
    )
    try:
        yield handle
    except BaseException as exc:
        try:
            handle._flush_failure(exc)
        except Exception:  # pragma: no cover
            logger.exception("ai_action_logger: flush_failure failed")
        raise
    else:
        try:
            handle._flush_success()
        except Exception:
            logger.exception("ai_action_logger: flush_success failed")
```

- [ ] **Step 4: Run to verify pass**

Run: `cd apps/api && pytest tests/test_ai_action_logger.py -v`
Expected: 11 PASSED.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/services/ai_action_logger.py apps/api/tests/test_ai_action_logger.py
git commit -m "feat(api): NullActionLogHandle for DB-enter failure"
```

---

### Task 13: Flush failure is swallowed with counter bump

**Files:**
- Modify: `apps/api/app/services/ai_action_logger.py`
- Modify: `apps/api/tests/test_ai_action_logger.py`

- [ ] **Step 1: Append failing test**

```python
from app.services.runtime_state import runtime_state


def test_flush_failure_swallowed_and_counter_bumped() -> None:
    ws_id, user_id = _seed()

    async def go() -> None:
        with SessionLocal() as db:
            async with action_log_context(
                db, workspace_id=ws_id, user_id=user_id,
                action_type="selection.rewrite", scope="selection",
            ) as log:
                # Poison the *second* commit (success path) by monkeypatching
                # the handle's db session commit after we have yielded.
                original = db.commit

                def _boom() -> None:
                    db.commit = original  # type: ignore[method-assign]
                    raise RuntimeError("flush boom")

                db.commit = _boom  # type: ignore[method-assign]

    # Should NOT raise
    asyncio.run(go())
    metrics_key = "ai_action_log.flush_failures"
    counter_value = runtime_state.get_json("metrics", metrics_key) or 0
    assert counter_value >= 1
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && pytest tests/test_ai_action_logger.py::test_flush_failure_swallowed_and_counter_bumped -v`
Expected: FAIL — counter not incremented (we haven't added the bump yet).

- [ ] **Step 3: Add counter bump**

First, check the `runtime_state` module. Open
`apps/api/app/services/runtime_state.py` — it exposes
`get_json(namespace, key)` and `set_json(namespace, key, value)`. Add a
helper `increment_metric` at the bottom of that module if it does not
already exist. Specifically append:

```python
def increment_metric(key: str, delta: int = 1) -> int:
    """Thread-safe integer counter in the 'metrics' namespace."""
    with runtime_state._memory._lock:
        current = runtime_state._memory._data.setdefault("metrics", {}).get(key, 0)
        next_val = int(current) + delta
        runtime_state._memory._data["metrics"][key] = next_val
        return next_val
```

In `apps/api/app/services/ai_action_logger.py`, import it:

```python
from app.services.runtime_state import increment_metric
```

Replace both flush-failure swallow blocks to bump the counter:

```python
    try:
        yield handle
    except BaseException as exc:
        try:
            handle._flush_failure(exc)
        except Exception:
            logger.exception("ai_action_logger: flush_failure failed")
            increment_metric("ai_action_log.flush_failures")
        raise
    else:
        try:
            handle._flush_success()
        except Exception:
            logger.exception("ai_action_logger: flush_success failed")
            increment_metric("ai_action_log.flush_failures")
```

- [ ] **Step 4: Run to verify pass**

Run: `cd apps/api && pytest tests/test_ai_action_logger.py -v`
Expected: 12 PASSED.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/services/runtime_state.py apps/api/app/services/ai_action_logger.py apps/api/tests/test_ai_action_logger.py
git commit -m "feat(api): swallow flush failures with runtime_state counter"
```

---

### Task 14: Wire /selection-action endpoint

**Files:**
- Modify: `apps/api/app/routers/notebook_ai.py`
- Create: `apps/api/tests/test_notebook_ai_logging.py`

- [ ] **Step 1: Write failing integration test**

Create `apps/api/tests/test_notebook_ai_logging.py` — uses TestClient
against the full FastAPI app. Reuse the fixture pattern from
`test_api_integration.py` (copy the bootstrap chunk):

```python
# ruff: noqa: E402
import atexit
import importlib
import os
import shutil
import tempfile
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-s1-wiring-"))
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
from app.db.session import SessionLocal, engine
from app.models import (
    AIActionLog, AIUsageEvent,
    Membership, Notebook, NotebookPage, Project, User, Workspace,
)
from app.services.dashscope_stream import StreamChunk


def setup_function() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _public_headers() -> dict[str, str]:
    return {"origin": "http://localhost:3000"}


def _verification_code_key(email: str, purpose: str) -> str:
    import hashlib
    raw = f"{email.lower().strip()}:{purpose}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _issue_code(client: TestClient, email: str, purpose: str = "register") -> str:
    from app.services.runtime_state import runtime_state
    resp = client.post(
        "/api/v1/auth/send-code",
        json={"email": email, "purpose": purpose},
        headers=_public_headers(),
    )
    assert resp.status_code == 200
    entry = runtime_state.get_json("verify_code", _verification_code_key(email, purpose))
    assert entry is not None
    return str(entry["code"])


def _register_user(client: TestClient, email: str) -> dict:
    code = _issue_code(client, email, "register")
    resp = client.post(
        "/api/v1/auth/register",
        json={
            "email": email, "password": "pass1234pass",
            "display_name": "Test", "code": code,
        },
        headers=_public_headers(),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _seed_fixture(client: TestClient, email: str = "u@x.co") -> dict:
    """Register a new user (creates workspace) then ORM-seed project+notebook+page."""
    info = _register_user(client, email)
    ws_id = info["workspace"]["id"]
    user_id = info["user"]["id"]
    with SessionLocal() as db:
        project = Project(workspace_id=ws_id, name="P")
        db.add(project); db.commit(); db.refresh(project)
        notebook = Notebook(
            workspace_id=ws_id, project_id=project.id, created_by=user_id,
            title="NB", slug="nb",
        )
        db.add(notebook); db.commit(); db.refresh(notebook)
        page = NotebookPage(
            notebook_id=notebook.id, created_by=user_id, title="T", slug="t",
            plain_text="some page text here",
        )
        db.add(page); db.commit(); db.refresh(page)
        return {
            "ws_id": ws_id, "user_id": user_id, "user_email": email,
            "project_id": project.id,
            "notebook_id": notebook.id, "page_id": page.id,
        }


async def _fake_stream(*_a, **_kw):
    yield StreamChunk(content="改写后的文字", finish_reason=None)
    yield StreamChunk(
        content="", finish_reason="stop",
        usage={"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17},
        model_id="qwen-plus",
    )


def _finalize_client_auth(client: TestClient, ws_id: str) -> None:
    """Add CSRF and workspace header to an already-authenticated client."""
    csrf = client.get("/api/v1/auth/csrf", headers=_public_headers()).json()["csrf_token"]
    client.headers.update({
        "origin": "http://localhost:3000",
        "x-csrf-token": csrf,
        "x-workspace-id": ws_id,
    })


def test_selection_action_creates_log_and_usage() -> None:
    client = TestClient(main_module.app)
    fx = _seed_fixture(client, email="t1@x.co")
    _finalize_client_auth(client, fx["ws_id"])

    with patch(
        "app.routers.notebook_ai.chat_completion_stream",
        side_effect=lambda *a, **kw: _fake_stream(),
    ):
        resp = client.post(
            "/api/v1/ai/notebook/selection-action",
            json={
                "page_id": fx["page_id"],
                "selected_text": "原文",
                "action_type": "rewrite",
            },
        )
        # drain the SSE body
        _ = resp.text

    assert resp.status_code == 200

    with SessionLocal() as db:
        logs = db.query(AIActionLog).all()
        assert len(logs) == 1
        log = logs[0]
        assert log.action_type == "selection.rewrite"
        assert log.scope == "selection"
        assert log.status == "completed"
        assert log.page_id == fx["page_id"]

        usages = db.query(AIUsageEvent).filter_by(action_log_id=log.id).all()
        assert len(usages) == 1
        assert usages[0].event_type == "llm_completion"
        assert usages[0].prompt_tokens == 12
        assert usages[0].count_source == "exact"
```

Before running, verify the project actually uses an
`x-test-user-id`-style override. Grep for it first:

```bash
cd apps/api && grep -rn "x-test-user" app/ 2>&1 | head -3
```

If no such header exists in the codebase, use the normal register +
login flow from `test_api_integration.py` (`register_user`) instead —
copy that helper into the new test file. Do not introduce a new auth
bypass.

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && pytest tests/test_notebook_ai_logging.py::test_selection_action_creates_log_and_usage -v`
Expected: FAIL — 0 rows in `ai_action_logs` (wiring not done yet).

- [ ] **Step 3: Wire the endpoint**

Open `apps/api/app/routers/notebook_ai.py`. At the top, add the import:

```python
from app.services.ai_action_logger import action_log_context
```

Replace the `_generate()` body inside `selection_action` so the whole
generator runs under the context manager:

```python
    async def _generate():
        async with action_log_context(
            db,
            workspace_id=str(workspace_id),
            user_id=str(current_user.id),
            action_type=f"selection.{action_type}",
            scope="selection",
            notebook_id=str(page.notebook_id) if page else None,
            page_id=str(page.id) if page else None,
            block_id=payload.get("block_id"),
        ) as log:
            log.set_input({
                "selected_text": selected_text[:5000],
                "action_type": action_type,
            })
            full_content = ""
            last_usage: dict | None = None
            last_model_id: str | None = None
            try:
                yield _sse("message_start", {
                    "role": "assistant",
                    "action_log_id": log.log_id,
                })
                async for chunk in chat_completion_stream(messages, temperature=0.7, max_tokens=4096):
                    if chunk.content:
                        full_content += chunk.content
                        yield _sse("token", {"content": chunk.content, "snapshot": full_content})
                    if chunk.usage:
                        last_usage = chunk.usage
                    if chunk.model_id:
                        last_model_id = chunk.model_id
                log.set_output(full_content)
                log.record_usage(
                    event_type="llm_completion",
                    model_id=last_model_id,
                    prompt_tokens=(last_usage or {}).get("prompt_tokens")
                        or _estimate_tokens(user_prompt),
                    completion_tokens=(last_usage or {}).get("completion_tokens")
                        or _estimate_tokens(full_content),
                    count_source="exact" if last_usage else "estimated",
                )
                yield _sse("message_done", {
                    "content": full_content,
                    "action_type": action_type,
                    "action_log_id": log.log_id,
                })
            except Exception as exc:
                yield _sse("error", {"message": str(exc)})
                raise
```

Add the `_estimate_tokens` helper at the bottom of the same file
(below `_build_simple_system_prompt`):

```python
def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd apps/api && pytest tests/test_notebook_ai_logging.py::test_selection_action_creates_log_and_usage -v`
Expected: PASSED.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/routers/notebook_ai.py apps/api/tests/test_notebook_ai_logging.py
git commit -m "feat(api): instrument /selection-action with action_log_context"
```

---

### Task 15: Wire /page-action endpoint

**Files:**
- Modify: `apps/api/app/routers/notebook_ai.py`
- Modify: `apps/api/tests/test_notebook_ai_logging.py`

- [ ] **Step 1: Append the failing test**

```python
def test_page_action_creates_log_and_usage() -> None:
    client = TestClient(main_module.app)
    fx = _seed_fixture(client, email="t2@x.co")
    _finalize_client_auth(client, fx["ws_id"])

    with patch(
        "app.routers.notebook_ai.chat_completion_stream",
        side_effect=lambda *a, **kw: _fake_stream(),
    ):
        resp = client.post(
            "/api/v1/ai/notebook/page-action",
            json={"page_id": fx["page_id"], "action_type": "summarize"},
        )
        _ = resp.text

    assert resp.status_code == 200
    with SessionLocal() as db:
        logs = db.query(AIActionLog).all()
        assert len(logs) == 1
        assert logs[0].action_type == "page.summarize"
        assert logs[0].scope == "page"
        assert db.query(AIUsageEvent).count() == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && pytest tests/test_notebook_ai_logging.py::test_page_action_creates_log_and_usage -v`
Expected: FAIL.

- [ ] **Step 3: Wire /page-action identically to /selection-action**

In `apps/api/app/routers/notebook_ai.py`, in `page_action(...)`, replace
the `_generate()` body with:

```python
    async def _generate():
        async with action_log_context(
            db,
            workspace_id=str(workspace_id),
            user_id=str(current_user.id),
            action_type=f"page.{action_type}",
            scope="page",
            notebook_id=str(page.notebook_id),
            page_id=str(page.id),
        ) as log:
            log.set_input({"action_type": action_type, "page_text_sha": str(len(page_text))})
            full_content = ""
            last_usage: dict | None = None
            last_model_id: str | None = None
            try:
                yield _sse("message_start", {"role": "assistant", "action_log_id": log.log_id})
                async for chunk in chat_completion_stream(messages, temperature=0.7, max_tokens=4096):
                    if chunk.content:
                        full_content += chunk.content
                        yield _sse("token", {"content": chunk.content, "snapshot": full_content})
                    if chunk.usage:
                        last_usage = chunk.usage
                    if chunk.model_id:
                        last_model_id = chunk.model_id
                log.set_output(full_content)
                log.record_usage(
                    event_type="llm_completion",
                    model_id=last_model_id,
                    prompt_tokens=(last_usage or {}).get("prompt_tokens")
                        or _estimate_tokens(user_prompt),
                    completion_tokens=(last_usage or {}).get("completion_tokens")
                        or _estimate_tokens(full_content),
                    count_source="exact" if last_usage else "estimated",
                )
                yield _sse("message_done", {
                    "content": full_content,
                    "action_type": action_type,
                    "action_log_id": log.log_id,
                })
            except Exception as exc:
                yield _sse("error", {"message": str(exc)})
                raise
```

- [ ] **Step 4: Run to verify pass**

Run: `cd apps/api && pytest tests/test_notebook_ai_logging.py -v`
Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/routers/notebook_ai.py apps/api/tests/test_notebook_ai_logging.py
git commit -m "feat(api): instrument /page-action with action_log_context"
```

---

### Task 16: Wire /ask endpoint with retrieval source metadata

**Files:**
- Modify: `apps/api/app/routers/notebook_ai.py`
- Modify: `apps/api/tests/test_notebook_ai_logging.py`

- [ ] **Step 1: Append the failing test**

```python
async def _fake_assemble_context(*_a, **_kw):
    from app.services.retrieval_orchestration import RetrievalContext, RetrievalSource
    return RetrievalContext(
        system_prompt="SYS",
        sources=[
            RetrievalSource(source_type="memory", source_id="m1", title="M", snippet="s"),
            RetrievalSource(source_type="related_page", source_id="p1", title="P", snippet="s"),
        ],
    )


def test_ask_creates_log_with_retrieval_sources() -> None:
    client = TestClient(main_module.app)
    fx = _seed_fixture(client, email="t3@x.co")
    _finalize_client_auth(client, fx["ws_id"])

    with patch(
        "app.routers.notebook_ai.chat_completion_stream",
        side_effect=lambda *a, **kw: _fake_stream(),
    ), patch(
        "app.services.retrieval_orchestration.assemble_context",
        side_effect=_fake_assemble_context,
    ):
        resp = client.post(
            "/api/v1/ai/notebook/ask",
            json={"page_id": fx["page_id"], "message": "what is X?", "history": []},
        )
        _ = resp.text

    assert resp.status_code == 200
    with SessionLocal() as db:
        log = db.query(AIActionLog).one()
    assert log.action_type == "ask"
    assert log.scope == "notebook"    # related_page present → scope=notebook
    sources = log.trace_metadata.get("retrieval_sources") or []
    assert len(sources) == 2
    assert {s["type"] for s in sources} == {"memory", "related_page"}
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && pytest tests/test_notebook_ai_logging.py::test_ask_creates_log_with_retrieval_sources -v`
Expected: FAIL.

- [ ] **Step 3: Wire /ask**

In `apps/api/app/routers/notebook_ai.py`, in `ask(...)`, replace the
`_generate()` body with:

```python
    def _scope_from_sources(sources: list[dict]) -> str:
        types = {s.get("type") for s in sources}
        if {"related_page", "document_chunk"} & types:
            return "notebook"
        return "page"

    async def _generate():
        scope = _scope_from_sources(retrieval_sources)
        async with action_log_context(
            db,
            workspace_id=str(workspace_id),
            user_id=str(current_user.id),
            action_type="ask",
            scope=scope,
            notebook_id=resolved_notebook_id,
            page_id=str(page.id) if page is not None else None,
        ) as log:
            log.set_input({"message": user_message[:4000], "history_turns": len(history or [])})
            log.set_trace_metadata({"retrieval_sources": retrieval_sources})
            full_content = ""
            last_usage: dict | None = None
            last_model_id: str | None = None
            try:
                yield _sse("message_start", {
                    "role": "assistant",
                    "sources": retrieval_sources,
                    "action_log_id": log.log_id,
                })
                async for chunk in chat_completion_stream(messages, temperature=0.7, max_tokens=4096):
                    if chunk.content:
                        full_content += chunk.content
                        yield _sse("token", {"content": chunk.content, "snapshot": full_content})
                    if chunk.usage:
                        last_usage = chunk.usage
                    if chunk.model_id:
                        last_model_id = chunk.model_id
                log.set_output(full_content)
                log.record_usage(
                    event_type="llm_completion",
                    model_id=last_model_id,
                    prompt_tokens=(last_usage or {}).get("prompt_tokens")
                        or _estimate_tokens(user_message),
                    completion_tokens=(last_usage or {}).get("completion_tokens")
                        or _estimate_tokens(full_content),
                    count_source="exact" if last_usage else "estimated",
                )
                yield _sse("message_done", {
                    "content": full_content,
                    "sources": retrieval_sources,
                    "action_log_id": log.log_id,
                })
            except Exception as exc:
                yield _sse("error", {"message": str(exc)})
                raise
```

- [ ] **Step 4: Run to verify pass**

Run: `cd apps/api && pytest tests/test_notebook_ai_logging.py -v`
Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/routers/notebook_ai.py apps/api/tests/test_notebook_ai_logging.py
git commit -m "feat(api): instrument /ask with action_log_context + retrieval_sources"
```

---

### Task 17: Wire /whiteboard-summarize endpoint

**Files:**
- Modify: `apps/api/app/routers/notebook_ai.py`
- Modify: `apps/api/tests/test_notebook_ai_logging.py`

- [ ] **Step 1: Append failing test**

```python
async def _fake_whiteboard_summary(*_a, **_kw):
    return {"summary": "a sketch of X", "memory_count": 2, "tokens": 42}


def test_whiteboard_summarize_creates_log() -> None:
    client = TestClient(main_module.app)
    fx = _seed_fixture(client, email="t4@x.co")
    _finalize_client_auth(client, fx["ws_id"])

    with patch(
        "app.services.whiteboard_service.extract_whiteboard_memories",
        side_effect=_fake_whiteboard_summary,
    ):
        resp = client.post(
            "/api/v1/ai/notebook/whiteboard-summarize",
            json={"page_id": fx["page_id"], "elements": []},
        )

    assert resp.status_code == 200
    with SessionLocal() as db:
        log = db.query(AIActionLog).one()
    assert log.action_type == "whiteboard.summarize"
    assert log.scope == "selection"
    assert log.status == "completed"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && pytest tests/test_notebook_ai_logging.py::test_whiteboard_summarize_creates_log -v`
Expected: FAIL.

- [ ] **Step 3: Wire /whiteboard-summarize**

In `apps/api/app/routers/notebook_ai.py`, modify the
`whiteboard_summarize` function body so the entire work is wrapped in
`action_log_context`. Example target shape (adapt to the function's
existing structure — replace the body after the input-validation
block):

```python
    async with action_log_context(
        db,
        workspace_id=str(workspace_id),
        user_id=str(current_user.id),
        action_type="whiteboard.summarize",
        scope="selection",
        notebook_id=str(page.notebook_id),
        page_id=str(page.id),
    ) as log:
        log.set_input({"elements_count": len(elements)})
        from app.services.whiteboard_service import extract_whiteboard_memories
        result = await extract_whiteboard_memories(
            db,
            page_id=page_id,
            elements=elements,
            workspace_id=workspace_id,
            user_id=str(current_user.id),
        )
        log.set_output({"summary": result.get("summary", ""),
                        "memory_count": result.get("memory_count", 0)})
        # This endpoint does not call the dashscope stream directly, but the
        # underlying service does. We approximate usage via its reported
        # token count if available, else estimate.
        tok = result.get("tokens")
        log.record_usage(
            event_type="llm_completion",
            prompt_tokens=tok or _estimate_tokens(str(elements)),
            completion_tokens=_estimate_tokens(result.get("summary", "")),
            count_source="exact" if tok else "estimated",
        )
        return result
```

- [ ] **Step 4: Run to verify pass**

Run: `cd apps/api && pytest tests/test_notebook_ai_logging.py -v`
Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/routers/notebook_ai.py apps/api/tests/test_notebook_ai_logging.py
git commit -m "feat(api): instrument /whiteboard-summarize with action_log_context"
```

---

### Task 18: Create ai_actions retrieval router — list endpoint

**Files:**
- Create: `apps/api/app/routers/ai_actions.py`
- Create: `apps/api/tests/test_ai_action_retrieval.py`

- [ ] **Step 1: Write failing test**

Create `apps/api/tests/test_ai_action_retrieval.py`:

```python
# ruff: noqa: E402
import atexit
import importlib
import os
import shutil
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-s1-retrieval-"))
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
from app.db.session import SessionLocal, engine
from app.models import (
    AIActionLog, AIUsageEvent, Membership, Notebook, NotebookPage,
    Project, User, Workspace,
)


def setup_function() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _public_headers() -> dict[str, str]:
    return {"origin": "http://localhost:3000"}


def _verification_code_key(email: str, purpose: str) -> str:
    import hashlib
    raw = f"{email.lower().strip()}:{purpose}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _register_client(email: str = "u@x.co") -> tuple[TestClient, dict]:
    """Register a new user and return (client, {ws_id, user_id})."""
    from app.services.runtime_state import runtime_state
    client = TestClient(main_module.app)
    client.post(
        "/api/v1/auth/send-code",
        json={"email": email, "purpose": "register"},
        headers=_public_headers(),
    )
    entry = runtime_state.get_json("verify_code", _verification_code_key(email, "register"))
    code = str(entry["code"])
    resp = client.post(
        "/api/v1/auth/register",
        json={
            "email": email, "password": "pass1234pass",
            "display_name": "Test", "code": code,
        },
        headers=_public_headers(),
    )
    assert resp.status_code == 200, resp.text
    info = resp.json()
    csrf = client.get("/api/v1/auth/csrf", headers=_public_headers()).json()["csrf_token"]
    client.headers.update({
        "origin": "http://localhost:3000",
        "x-csrf-token": csrf,
        "x-workspace-id": info["workspace"]["id"],
    })
    return client, {"ws_id": info["workspace"]["id"], "user_id": info["user"]["id"]}


def _seed_n_logs(n: int, email: str = "u@x.co") -> tuple[TestClient, dict]:
    """Register a user, seed a notebook+page, and drop n AIActionLog rows."""
    client, auth = _register_client(email)
    ws_id, user_id = auth["ws_id"], auth["user_id"]
    with SessionLocal() as db:
        project = Project(workspace_id=ws_id, name="P")
        db.add(project); db.commit(); db.refresh(project)
        notebook = Notebook(workspace_id=ws_id, project_id=project.id,
                            created_by=user_id, title="NB", slug="nb")
        db.add(notebook); db.commit(); db.refresh(notebook)
        page = NotebookPage(notebook_id=notebook.id, created_by=user_id,
                            title="T", slug="t", plain_text="x")
        db.add(page); db.commit(); db.refresh(page)

        base = datetime.now(timezone.utc)
        for i in range(n):
            log = AIActionLog(
                workspace_id=ws_id, user_id=user_id,
                notebook_id=notebook.id, page_id=page.id,
                action_type="selection.rewrite", scope="selection",
                status="completed", duration_ms=100 + i,
                output_summary=f"out {i}", trace_metadata={},
                created_at=base - timedelta(seconds=i),
            )
            db.add(log); db.commit(); db.refresh(log)
            db.add(AIUsageEvent(
                workspace_id=ws_id, user_id=user_id, action_log_id=log.id,
                event_type="llm_completion", prompt_tokens=5, completion_tokens=5,
                total_tokens=10, count_source="exact", meta_json={},
            ))
        db.commit()
    return client, {"ws_id": ws_id, "user_id": user_id, "page_id": page.id}


def test_list_returns_page_logs_paginated() -> None:
    client, fx = _seed_n_logs(60)
    resp = client.get(f"/api/v1/pages/{fx['page_id']}/ai-actions?limit=50")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 50
    assert body["next_cursor"] is not None
    # total_tokens is rolled up into the item payload
    assert body["items"][0]["usage"]["total_tokens"] == 10


def test_list_second_page_does_not_overlap() -> None:
    client, fx = _seed_n_logs(60, email="u2@x.co")
    first = client.get(f"/api/v1/pages/{fx['page_id']}/ai-actions?limit=30").json()
    cursor = first["next_cursor"]
    second = client.get(
        f"/api/v1/pages/{fx['page_id']}/ai-actions?limit=30&cursor={cursor}"
    ).json()
    first_ids = {i["id"] for i in first["items"]}
    second_ids = {i["id"] for i in second["items"]}
    assert first_ids.isdisjoint(second_ids)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && pytest tests/test_ai_action_retrieval.py::test_list_returns_page_logs_paginated -v`
Expected: FAIL — 404 (endpoint not registered).

- [ ] **Step 3: Create the router file**

Create `apps/api/app/routers/ai_actions.py`:

```python
"""Retrieval API for AI action logs (S1)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import (
    get_current_user,
    get_current_workspace_id,
    get_db_session,
)
from app.core.errors import ApiError
from app.models import AIActionLog, AIUsageEvent, Membership, User

pages_router = APIRouter(prefix="/api/v1/pages", tags=["ai-actions"])
detail_router = APIRouter(prefix="/api/v1/ai-actions", tags=["ai-actions"])


def _parse_cursor(cursor: str | None) -> datetime | None:
    if not cursor:
        return None
    try:
        return datetime.fromisoformat(cursor.replace("Z", "+00:00"))
    except ValueError:
        raise ApiError("invalid_input", "Bad cursor", status_code=400)


def _serialize_log(log: AIActionLog, total_tokens: int) -> dict[str, Any]:
    return {
        "id": log.id,
        "action_type": log.action_type,
        "scope": log.scope,
        "status": log.status,
        "model_id": log.model_id,
        "duration_ms": log.duration_ms,
        "output_summary": log.output_summary,
        "created_at": log.created_at.isoformat(),
        "usage": {"total_tokens": total_tokens},
    }


@pages_router.get("/{page_id}/ai-actions")
def list_page_ai_actions(
    page_id: str,
    limit: int = 50,
    cursor: str | None = None,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
) -> dict[str, Any]:
    _ = current_user
    limit = max(1, min(limit, 100))
    q = (
        db.query(AIActionLog)
        .filter(AIActionLog.page_id == page_id)
        .filter(AIActionLog.workspace_id == workspace_id)
    )
    cur = _parse_cursor(cursor)
    if cur:
        q = q.filter(AIActionLog.created_at < cur)
    rows = q.order_by(AIActionLog.created_at.desc()).limit(limit + 1).all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    if not rows:
        return {"items": [], "next_cursor": None}

    # Roll up total_tokens per log in one query
    log_ids = [r.id for r in rows]
    totals = dict(
        db.query(AIUsageEvent.action_log_id,
                 AIUsageEvent.total_tokens).filter(
            AIUsageEvent.action_log_id.in_(log_ids)
        ).all()
    )

    items = [_serialize_log(r, totals.get(r.id, 0)) for r in rows]
    next_cursor = rows[-1].created_at.isoformat() if has_more else None
    return {"items": items, "next_cursor": next_cursor}
```

- [ ] **Step 4: Register the router in main.py**

Open `apps/api/app/main.py`. Update the imports:

```python
from app.routers import (
    ai_actions, auth, chat, datasets, memory, memory_stream, model_catalog,
    models, notebook_ai, notebooks, pipeline, projects, realtime, study, uploads,
)
```

Add the include lines near the other `include_router` calls:

```python
app.include_router(ai_actions.pages_router)
app.include_router(ai_actions.detail_router)
```

- [ ] **Step 5: Run to verify pass**

Run: `cd apps/api && pytest tests/test_ai_action_retrieval.py -v`
Expected: 2 PASSED.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/routers/ai_actions.py apps/api/app/main.py apps/api/tests/test_ai_action_retrieval.py
git commit -m "feat(api): GET /pages/{id}/ai-actions list endpoint with cursor paging"
```

---

### Task 19: Add detail endpoint with overflow dereference + access control

**Files:**
- Modify: `apps/api/app/routers/ai_actions.py`
- Modify: `apps/api/tests/test_ai_action_retrieval.py`

- [ ] **Step 1: Append failing tests**

```python
def test_detail_returns_full_payload() -> None:
    client, fx = _seed_n_logs(1, email="u3@x.co")
    list_resp = client.get(f"/api/v1/pages/{fx['page_id']}/ai-actions").json()
    log_id = list_resp["items"][0]["id"]

    resp = client.get(f"/api/v1/ai-actions/{log_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == log_id
    assert body["status"] == "completed"
    assert len(body["usage_events"]) == 1


def test_detail_404_when_unknown_id() -> None:
    client, _ = _register_client(email="u4@x.co")
    resp = client.get("/api/v1/ai-actions/does-not-exist")
    assert resp.status_code == 404


def test_detail_403_for_other_user_non_owner() -> None:
    """user_owner creates a log; user_member (same workspace but not owner)
    tries to read it → 403."""
    # owner creates workspace + log
    owner_client, owner_auth = _register_client(email="owner@x.co")
    ws_id = owner_auth["ws_id"]
    owner_id = owner_auth["user_id"]
    with SessionLocal() as db:
        pr = Project(workspace_id=ws_id, name="P")
        db.add(pr); db.commit(); db.refresh(pr)
        nb = Notebook(workspace_id=ws_id, project_id=pr.id,
                      created_by=owner_id, title="NB", slug="nb")
        db.add(nb); db.commit(); db.refresh(nb)
        pg = NotebookPage(notebook_id=nb.id, created_by=owner_id,
                          title="T", slug="t", plain_text="x")
        db.add(pg); db.commit(); db.refresh(pg)
        log = AIActionLog(
            workspace_id=ws_id, user_id=owner_id,
            notebook_id=nb.id, page_id=pg.id,
            action_type="selection.rewrite", scope="selection",
            status="completed", trace_metadata={},
        )
        db.add(log); db.commit(); db.refresh(log)
        log_id = log.id

    # add a member user and add them as member (role!=owner) to the workspace
    member_client, member_auth = _register_client(email="member@x.co")
    member_id = member_auth["user_id"]
    with SessionLocal() as db:
        # downgrade member's self-created workspace irrelevant; add them to owner's ws
        db.add(Membership(workspace_id=ws_id, user_id=member_id, role="member"))
        db.commit()
    member_client.headers["x-workspace-id"] = ws_id

    resp = member_client.get(f"/api/v1/ai-actions/{log_id}")
    assert resp.status_code == 403


def test_detail_dereferences_minio_overflow() -> None:
    import app.services.storage as storage_service
    from tests.fixtures.fake_s3 import FakeS3Client
    fake = FakeS3Client()
    fake.create_bucket(Bucket="ai-action-payloads")
    import json as _json
    big_payload = {"q": "x" * 20_000}
    fake.put_object(
        Bucket="ai-action-payloads",
        Key="some-key/input.json",
        Body=_json.dumps(big_payload).encode("utf-8"),
        ContentType="application/json",
    )
    storage_service.get_s3_client.cache_clear()
    storage_service.get_s3_client = lambda: fake  # type: ignore[assignment]

    client, auth = _register_client(email="u5@x.co")
    ws_id = auth["ws_id"]; user_id = auth["user_id"]
    with SessionLocal() as db:
        pr = Project(workspace_id=ws_id, name="P")
        db.add(pr); db.commit(); db.refresh(pr)
        nb = Notebook(workspace_id=ws_id, project_id=pr.id, created_by=user_id,
                      title="NB", slug="nb")
        db.add(nb); db.commit(); db.refresh(nb)
        pg = NotebookPage(notebook_id=nb.id, created_by=user_id, title="T",
                          slug="t", plain_text="x")
        db.add(pg); db.commit(); db.refresh(pg)
        log = AIActionLog(
            workspace_id=ws_id, user_id=user_id,
            notebook_id=nb.id, page_id=pg.id,
            action_type="ask", scope="page", status="completed",
            input_json={"_overflow_ref": "some-key/input.json", "_preview": "x" * 500},
            trace_metadata={},
        )
        db.add(log); db.commit(); db.refresh(log)
        log_id = log.id

    resp = client.get(f"/api/v1/ai-actions/{log_id}")
    assert resp.status_code == 200
    body = resp.json()
    # input_json has been dereferenced into the full payload
    assert body["input_json"]["q"] == "x" * 20_000
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && pytest tests/test_ai_action_retrieval.py::test_detail_returns_full_payload -v`
Expected: FAIL — 404 (endpoint absent).

- [ ] **Step 3: Implement detail endpoint**

Append to `apps/api/app/routers/ai_actions.py`:

```python
import json as _json
import logging

from botocore.exceptions import ClientError

from app.core.config import settings
from app.services import storage as storage_service

logger = logging.getLogger(__name__)


def _deref_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict) or "_overflow_ref" not in payload:
        return payload
    try:
        client = storage_service.get_s3_client()
        resp = client.get_object(
            Bucket=settings.s3_ai_action_payloads_bucket,
            Key=payload["_overflow_ref"],
        )
        return _json.loads(resp["Body"].read().decode("utf-8"))
    except (ClientError, Exception):  # noqa: BLE001
        logger.exception("ai-actions: overflow deref failed")
        return payload


@detail_router.get("/{log_id}")
def get_ai_action_detail(
    log_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
) -> dict[str, Any]:
    log = db.query(AIActionLog).filter(
        AIActionLog.id == log_id,
        AIActionLog.workspace_id == workspace_id,
    ).first()
    if log is None:
        raise ApiError("not_found", "Action log not found", status_code=404)

    if str(log.user_id) != str(current_user.id):
        # Must be workspace owner to see another user's log
        membership = db.query(Membership).filter(
            Membership.workspace_id == workspace_id,
            Membership.user_id == current_user.id,
        ).first()
        if not membership or membership.role != "owner":
            raise ApiError("forbidden", "Not allowed", status_code=403)

    usage_rows = (
        db.query(AIUsageEvent)
        .filter(AIUsageEvent.action_log_id == log.id)
        .order_by(AIUsageEvent.created_at.asc())
        .all()
    )

    return {
        "id": log.id,
        "workspace_id": log.workspace_id,
        "user_id": log.user_id,
        "notebook_id": log.notebook_id,
        "page_id": log.page_id,
        "block_id": log.block_id,
        "action_type": log.action_type,
        "scope": log.scope,
        "status": log.status,
        "model_id": log.model_id,
        "duration_ms": log.duration_ms,
        "input_json": _deref_payload(log.input_json),
        "output_json": _deref_payload(log.output_json),
        "output_summary": log.output_summary,
        "error_code": log.error_code,
        "error_message": log.error_message,
        "trace_metadata": log.trace_metadata,
        "created_at": log.created_at.isoformat(),
        "usage_events": [
            {
                "id": u.id,
                "event_type": u.event_type,
                "model_id": u.model_id,
                "prompt_tokens": u.prompt_tokens,
                "completion_tokens": u.completion_tokens,
                "total_tokens": u.total_tokens,
                "audio_seconds": u.audio_seconds,
                "file_count": u.file_count,
                "count_source": u.count_source,
                "meta_json": u.meta_json,
            }
            for u in usage_rows
        ],
    }
```

- [ ] **Step 4: Run to verify pass**

Run: `cd apps/api && pytest tests/test_ai_action_retrieval.py -v`
Expected: 6 PASSED.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/routers/ai_actions.py apps/api/tests/test_ai_action_retrieval.py
git commit -m "feat(api): GET /ai-actions/{id} detail with MinIO deref and access control"
```

---

### Task 20: Lifespan MinIO bucket init + cleanup hook

**Files:**
- Modify: `apps/api/app/main.py`

- [ ] **Step 1: Add lazy bucket creation in lifespan**

Open `apps/api/app/main.py`. In the `lifespan` function, after
`seed_model_catalog(db)`, add:

```python
    # S1: ensure the overflow bucket exists for the action-log pipeline.
    try:
        from app.services import storage as _storage_service
        from botocore.exceptions import ClientError as _ClientError

        _s3 = _storage_service.get_s3_client()
        try:
            _s3.head_bucket(Bucket=settings.s3_ai_action_payloads_bucket)
        except _ClientError as _exc:
            _code = _exc.response.get("Error", {}).get("Code", "")
            if _code in ("404", "NoSuchBucket", "NotFound"):
                _s3.create_bucket(Bucket=settings.s3_ai_action_payloads_bucket)
    except Exception:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception(
            "lifespan: ai-action-payloads bucket init failed (non-fatal)"
        )
```

- [ ] **Step 2: Verify all previous tests still pass**

Run: `cd apps/api && pytest tests/test_ai_action_log_models.py tests/test_dashscope_stream_usage.py tests/test_fake_s3.py tests/test_ai_action_logger.py tests/test_notebook_ai_logging.py tests/test_ai_action_retrieval.py -v`
Expected: all green.

- [ ] **Step 3: Commit**

```bash
git add apps/api/app/main.py
git commit -m "feat(api): lifespan creates ai-action-payloads bucket if missing"
```

---

### Task 21: Coverage check and gate

**Files:** none (verification step)

- [ ] **Step 1: Run the full S1 test set with coverage**

Run:

```bash
cd apps/api && pytest \
  tests/test_ai_action_log_models.py \
  tests/test_dashscope_stream_usage.py \
  tests/test_fake_s3.py \
  tests/test_ai_action_logger.py \
  tests/test_notebook_ai_logging.py \
  tests/test_ai_action_retrieval.py \
  --cov=app/services/ai_action_logger \
  --cov=app/routers/ai_actions \
  --cov=app/services/dashscope_stream \
  --cov-report=term-missing
```

Expected: line coverage ≥80% on all three modules, `notebook_ai.py`
covered by the wiring tests.

If any module is below 80%, add a targeted test for the uncovered
branch and re-run.

- [ ] **Step 2: Commit coverage artifacts if generated**

If the command produced a `.coverage` file, leave it untracked (should
already be in `.gitignore` as `.coverage`). No commit here.

---

### Task 22: Frontend — minimal AI actions list panel

**Files:**
- Create: `apps/web/components/notebook/AIActionsList.tsx`
- Modify: `apps/web/components/console/editor/NoteEditor.tsx` (add panel)

- [ ] **Step 1: Create the list component**

Create `apps/web/components/notebook/AIActionsList.tsx`:

```tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import { apiGet } from "@/lib/api";

interface AIActionItem {
  id: string;
  action_type: string;
  scope: string;
  status: string;
  model_id: string | null;
  duration_ms: number | null;
  output_summary: string;
  created_at: string;
  usage: { total_tokens: number };
}

interface Props {
  pageId: string;
}

export default function AIActionsList({ pageId }: Props) {
  const [items, setItems] = useState<AIActionItem[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiGet<{ items: AIActionItem[]; next_cursor: string | null }>(
        `/api/v1/pages/${pageId}/ai-actions?limit=50`,
      );
      setItems(data.items || []);
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [pageId]);

  useEffect(() => { void load(); }, [load]);

  return (
    <div data-testid="ai-actions-list" style={{ padding: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
        <h3 style={{ fontSize: 14, fontWeight: 600, margin: 0 }}>AI Actions</h3>
        <button onClick={() => void load()} style={{ fontSize: 12 }}>Refresh</button>
      </div>
      {loading && <p style={{ fontSize: 12, color: "#888" }}>Loading…</p>}
      {!loading && items.length === 0 && (
        <p style={{ fontSize: 12, color: "#888" }}>No AI actions yet.</p>
      )}
      {!loading && items.length > 0 && (
        <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {items.map((it) => (
            <li
              key={it.id}
              data-testid="ai-action-item"
              style={{ padding: 8, borderBottom: "1px solid #eee", fontSize: 12 }}
            >
              <div style={{ fontWeight: 600 }}>{it.action_type}</div>
              <div style={{ color: "#666" }}>
                {it.status} · {it.model_id ?? "—"} · {it.duration_ms ?? 0}ms · {it.usage.total_tokens} tok
              </div>
              <div style={{ color: "#444", marginTop: 2 }}>
                {it.output_summary || "(no output)"}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Add the panel toggle to the note editor**

Open `apps/web/components/console/editor/NoteEditor.tsx`. Find the
existing AI panel region (look for `AIPanel` import or usage). Wrap the
existing panel with a tab switch: one tab for the existing AI features
and a second "Trace" tab that renders `<AIActionsList pageId={pageId} />`.

Minimal, style-agnostic approach — add near the other state hooks at
the top of the component:

```tsx
import AIActionsList from "@/components/notebook/AIActionsList";
// ...
const [panelTab, setPanelTab] = useState<"ai" | "trace">("ai");
```

In the JSX where the AI panel currently renders, wrap:

```tsx
<div>
  <div style={{ display: "flex", gap: 4, padding: "6px 8px", borderBottom: "1px solid #eee" }}>
    <button
      type="button"
      onClick={() => setPanelTab("ai")}
      data-testid="panel-tab-ai"
      style={{ fontWeight: panelTab === "ai" ? 600 : 400 }}
    >
      AI
    </button>
    <button
      type="button"
      onClick={() => setPanelTab("trace")}
      data-testid="panel-tab-trace"
      style={{ fontWeight: panelTab === "trace" ? 600 : 400 }}
    >
      Trace
    </button>
  </div>
  {panelTab === "ai" ? (
    /* existing AIPanel usage — unchanged */
  ) : (
    <AIActionsList pageId={pageId} />
  )}
</div>
```

Do **not** remove any existing AI panel logic; only wrap it.

- [ ] **Step 3: Typecheck**

Run: `cd apps/web && pnpm typecheck` (or `npm run typecheck`).
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add apps/web/components/notebook/AIActionsList.tsx apps/web/components/console/editor/NoteEditor.tsx
git commit -m "feat(web): AIActionsList panel under a Trace tab"
```

---

### Task 23: Playwright smoke test

**Files:**
- Create: `apps/web/tests/notebook-ai-trace.spec.ts`

- [ ] **Step 1: Write the test**

Create `apps/web/tests/notebook-ai-trace.spec.ts`:

```ts
import { test, expect } from "@playwright/test";

test.describe("AI action trace panel", () => {
  test("shows an entry after a selection rewrite", async ({ page }) => {
    // These helpers should mirror existing login/fixture helpers in the repo.
    // If there's a helper file (e.g. `tests/helpers/auth.ts`) prefer it over
    // hand-rolled login.
    await page.goto("/workspace/notebooks");

    // Create a notebook
    await page.getByRole("button", { name: /create/i }).first().click();
    // Wait for redirect to [notebookId]
    await page.waitForURL(/\/workspace\/notebooks\/[^/]+$/);

    // Create a page
    await page.getByRole("button", { name: /create/i }).first().click();

    // Type into the editor, select text, run rewrite
    const editor = page.locator(".ProseMirror").first();
    await editor.click();
    await editor.type("Hello world, this is a sentence.");
    await editor.press("Meta+a");

    // Trigger rewrite via a floating toolbar button if present, OR call the API
    // directly via the page context. Prefer the UI path if the button is
    // accessible:
    const rewrite = page.getByRole("button", { name: /rewrite/i });
    if (await rewrite.isVisible().catch(() => false)) {
      await rewrite.click();
      // wait for stream to finish — look for a "done" marker
      await page.waitForTimeout(2000);
    }

    // Switch to trace tab
    await page.getByTestId("panel-tab-trace").click();

    // Expect at least one entry
    const items = page.getByTestId("ai-action-item");
    await expect(items.first()).toBeVisible({ timeout: 10_000 });
    await expect(items.first()).toContainText(/selection\.rewrite/);
  });
});
```

- [ ] **Step 2: Run**

Run: `cd apps/web && pnpm playwright test tests/notebook-ai-trace.spec.ts --reporter=list`
Expected: PASSED (requires the dev server + api worker running).

If the test environment cannot stand up a full stack, mark this task
complete once the test file itself typechecks via
`pnpm tsc --noEmit tests/notebook-ai-trace.spec.ts` and the test suite
accepts the new file without syntax errors. Reviewer may run
Playwright manually.

- [ ] **Step 3: Commit**

```bash
git add apps/web/tests/notebook-ai-trace.spec.ts
git commit -m "test(web): Playwright smoke for AI action trace panel"
```

---

## Final acceptance checklist

After all tasks land, verify:

- [ ] `pytest apps/api/tests/test_ai_action_*` → all green
- [ ] Coverage on `ai_action_logger`, `ai_actions`, `dashscope_stream` ≥ 80 %
- [ ] `pnpm playwright test tests/notebook-ai-trace.spec.ts` → passes
- [ ] `scripts/dev.sh` still boots the full stack without errors
- [ ] `git log --oneline` shows one commit per task (≤ 23 commits)
- [ ] All four `/ai/notebook/*` endpoints produce logs with the
  expected `action_type` prefixes
- [ ] A failed stream produces a log with `status=failed` and
  `error_code`

## Cross-references

- Spec: `docs/superpowers/specs/2026-04-15-ai-action-log-and-usage-design.md`
- Original product spec: `MRAI_notebook_ai_os_build_spec.md` §5.1.8,
  §14.5, §15.7, §26
