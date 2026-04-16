# S2 — Block Types Additions — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the 5 remaining TipTap block types `file`, `ai_output`,
`reference`, `task`, `flashcard` along with their backing
endpoints, so users can insert them from the slash menu and the
editor round-trips all 19 block types the spec requires.

**Architecture:** Five TipTap custom-Node extensions (one `.tsx`
each, NodeView inline). Slash-menu entries drive insertion. Three
new backend endpoints wire `file` (upload + URL fetch) and `task`
(complete/reopen → `AIActionLog`). `NotebookAttachment` gains a
`meta_json` column so the upload can stash the MinIO object key.
`ai_output` is produced exclusively by the AI Panel "Insert as AI
block" button, which uses a new `onInsertAIOutput` prop threaded
from `AIPanel` down to `NoteEditor`.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2, Alembic, boto3,
pytest + pytest-cov, Node 20, Next.js 14, TipTap 3, lucide-react,
vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-04-16-block-types-additions-design.md`

---

## Phase Overview

| Phase | Scope |
|---|---|
| A | Backend foundation: `meta_json` migration, config, lifespan bucket init |
| B | `/attachments/upload` + `/attachments/{id}/url` endpoints + 4 API tests |
| C | `/tasks/{block_id}/complete` endpoint + 3 API tests |
| D | 5 TipTap extensions, each with its NodeView and vitest schema test |
| E | Wire: index / NoteEditor / SlashCommandMenu / AIPanel `onInsertAIOutput` / CSS |
| F | Playwright smoke (flashcard flip + task complete) |

---

### Task 1: Add `meta_json` to NotebookAttachment

**Files:**
- Modify: `apps/api/app/models/entities.py`
- Create: `apps/api/alembic/versions/202604170001_notebook_attachment_meta.py`
- Test: `apps/api/tests/test_notebook_attachment_meta.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/test_notebook_attachment_meta.py
# ruff: noqa: E402
import atexit, os, shutil, tempfile
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-s2-att-meta-"))
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
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && .venv/bin/pytest tests/test_notebook_attachment_meta.py -v`
Expected: FAIL — `TypeError: 'meta_json' is an invalid keyword argument for NotebookAttachment`.

- [ ] **Step 3: Add the column to the ORM model**

Open `apps/api/app/models/entities.py`. Locate the `NotebookAttachment`
class (starts around line 617). Current body:

```python
class NotebookAttachment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "notebook_attachments"

    page_id: Mapped[str] = mapped_column(ForeignKey("notebook_pages.id", ondelete="CASCADE"), index=True)
    data_item_id: Mapped[str | None] = mapped_column(ForeignKey("data_items.id", ondelete="SET NULL"), nullable=True)
    attachment_type: Mapped[str] = mapped_column(String(20), default="other", nullable=False)
    title: Mapped[str] = mapped_column(Text, default="", nullable=False)
```

Append one more line inside the class body (after `title`):

```python
    meta_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
```

- [ ] **Step 4: Write the Alembic migration**

Create `apps/api/alembic/versions/202604170001_notebook_attachment_meta.py`:

```python
"""notebook attachment meta_json column (S2)

Revision ID: 202604170001
Revises: 202604160001
Create Date: 2026-04-17
"""

from alembic import op


revision = "202604170001"
down_revision = "202604160001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE notebook_attachments
          ADD COLUMN IF NOT EXISTS meta_json JSONB NOT NULL DEFAULT '{}'::jsonb;
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE notebook_attachments DROP COLUMN IF EXISTS meta_json;")
```

- [ ] **Step 5: Run to verify pass**

Run: `cd apps/api && .venv/bin/pytest tests/test_notebook_attachment_meta.py -v`
Expected: 1 PASSED.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/models/entities.py apps/api/alembic/versions/202604170001_notebook_attachment_meta.py apps/api/tests/test_notebook_attachment_meta.py
git commit -m "feat(api): NotebookAttachment.meta_json column for S2 block storage"
```

---

### Task 2: Config values and lifespan bucket ensure

**Files:**
- Modify: `apps/api/app/core/config.py`
- Modify: `apps/api/app/main.py`

- [ ] **Step 1: Add two config keys**

Open `apps/api/app/core/config.py`. Find the block that defines
`s3_ai_action_payloads_bucket: str = "ai-action-payloads"` (added in
S1). Right below it, add:

```python
    s3_notebook_attachments_bucket: str = "notebook-attachments"
    notebook_attachment_max_bytes: int = 50 * 1024 * 1024
```

- [ ] **Step 2: Extend the lifespan bucket init**

Open `apps/api/app/main.py`. Find the S1 lifespan block that creates
`ai-action-payloads`. Add a parallel block for the new bucket,
immediately after:

```python
    # S2: ensure the attachments bucket exists.
    try:
        from app.services import storage as _storage_service
        from botocore.exceptions import ClientError as _ClientError

        _s3 = _storage_service.get_s3_client()
        try:
            _s3.head_bucket(Bucket=settings.s3_notebook_attachments_bucket)
        except _ClientError as _exc:
            _code = _exc.response.get("Error", {}).get("Code", "")
            if _code in ("404", "NoSuchBucket", "NotFound"):
                _s3.create_bucket(Bucket=settings.s3_notebook_attachments_bucket)
    except Exception:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception(
            "lifespan: notebook-attachments bucket init failed (non-fatal)"
        )
```

- [ ] **Step 3: Verify server still boots**

Run: `cd apps/api && .venv/bin/pytest tests/test_notebook_attachment_meta.py tests/test_ai_action_logger.py -v`
Expected: all green — lifespan code isn't touched by these, but we
confirm the config change didn't break import.

- [ ] **Step 4: Commit**

```bash
git add apps/api/app/core/config.py apps/api/app/main.py
git commit -m "feat(api): config + lifespan init for notebook-attachments bucket"
```

---

### Task 3: Upload endpoint POST /pages/{id}/attachments/upload

**Files:**
- Modify: `apps/api/app/routers/notebooks.py`
- Test: `apps/api/tests/test_attachment_upload.py` (new)

- [ ] **Step 1: Write the failing test**

Create `apps/api/tests/test_attachment_upload.py`:

```python
# ruff: noqa: E402
import atexit, importlib, os, shutil, tempfile
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-s2-upload-"))
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

import io
from fastapi.testclient import TestClient

from app.db.base import Base
import app.db.session as _s
from app.models import (
    Notebook, NotebookAttachment, NotebookPage, Project, User, Workspace,
)
import app.services.storage as storage_service
from tests.fixtures.fake_s3 import FakeS3Client


def setup_function() -> None:
    global engine, SessionLocal
    engine = _s.engine
    SessionLocal = _s.SessionLocal
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    from app.services.runtime_state import runtime_state
    runtime_state._memory = runtime_state._memory.__class__()
    # Install a fake S3 and pre-create the bucket.
    fake = FakeS3Client()
    fake.create_bucket(Bucket="notebook-attachments")
    cache_clear = getattr(storage_service.get_s3_client, "cache_clear", None)
    if cache_clear:
        cache_clear()
    storage_service.get_s3_client = lambda: fake  # type: ignore[assignment]


engine = _s.engine
SessionLocal = _s.SessionLocal


def _public_headers() -> dict[str, str]:
    return {"origin": "http://localhost:3000"}


def _verification_code_key(email: str, purpose: str) -> str:
    import hashlib
    raw = f"{email.lower().strip()}:{purpose}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _register_client(email: str = "u@x.co") -> tuple[TestClient, dict]:
    from app.services.runtime_state import runtime_state
    client = TestClient(main_module.app)
    client.post(
        "/api/v1/auth/send-code",
        json={"email": email, "purpose": "register"},
        headers=_public_headers(),
    )
    entry = runtime_state.get_json("verify_code", _verification_code_key(email, "register"))
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "pass1234pass",
              "display_name": "Test", "code": str(entry["code"])},
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


def _seed_page(ws_id: str, user_id: str) -> str:
    with SessionLocal() as db:
        pr = Project(workspace_id=ws_id, name="P"); db.add(pr); db.commit(); db.refresh(pr)
        nb = Notebook(workspace_id=ws_id, project_id=pr.id, created_by=user_id,
                      title="NB", slug="nb")
        db.add(nb); db.commit(); db.refresh(nb)
        pg = NotebookPage(notebook_id=nb.id, created_by=user_id, title="T",
                          slug="t", plain_text="x")
        db.add(pg); db.commit(); db.refresh(pg)
        return pg.id


def test_upload_small_png() -> None:
    client, auth = _register_client("u1@x.co")
    page_id = _seed_page(auth["ws_id"], auth["user_id"])
    files = {"file": ("x.png", io.BytesIO(b"fake png data"), "image/png")}

    resp = client.post(
        f"/api/v1/pages/{page_id}/attachments/upload",
        files=files,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["filename"] == "x.png"
    assert body["mime_type"] == "image/png"
    assert body["size_bytes"] == len(b"fake png data")
    assert body["attachment_id"]
    assert body["attachment_type"] == "image"

    with SessionLocal() as db:
        att = db.query(NotebookAttachment).filter_by(id=body["attachment_id"]).one()
    assert att.meta_json.get("object_key")
    assert att.meta_json["object_key"].endswith("x.png")


def test_upload_rejects_files_over_limit(monkeypatch) -> None:
    client, auth = _register_client("u2@x.co")
    page_id = _seed_page(auth["ws_id"], auth["user_id"])

    # Temporarily shrink the limit for deterministic assertion.
    monkeypatch.setattr(config_module.settings, "notebook_attachment_max_bytes", 10)
    files = {"file": ("big.txt", io.BytesIO(b"this-is-way-too-long"), "text/plain")}

    resp = client.post(
        f"/api/v1/pages/{page_id}/attachments/upload",
        files=files,
    )
    assert resp.status_code == 413
    body = resp.json()
    assert body["error"]["code"] == "file_too_large"


def test_upload_cross_workspace_404() -> None:
    # Owner of page A
    _client_a, auth_a = _register_client("a@x.co")
    page_id = _seed_page(auth_a["ws_id"], auth_a["user_id"])

    # Different workspace
    client_b, _ = _register_client("b@x.co")
    files = {"file": ("x.png", io.BytesIO(b"data"), "image/png")}
    resp = client_b.post(
        f"/api/v1/pages/{page_id}/attachments/upload",
        files=files,
    )
    assert resp.status_code == 404
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && .venv/bin/pytest tests/test_attachment_upload.py::test_upload_small_png -v`
Expected: FAIL — 404 (endpoint not registered).

- [ ] **Step 3: Implement the endpoint**

Open `apps/api/app/routers/notebooks.py`. At the top of the
`pages_router` endpoints section (after the imports), verify that
`File`, `Form`, and `UploadFile` are imported from `fastapi`. If
they are not, add:

```python
from fastapi import File, Form, UploadFile
```

Also ensure these are available at module top:

```python
from app.core.errors import ApiError
from uuid import uuid4
from app.services import storage as storage_service
```

Immediately before the existing `@pages_router.post("/{page_id}/snapshot", ...)`
endpoint, insert the upload endpoint:

```python
_ATTACHMENT_TYPE_MAP: dict[str, str] = {
    "application/pdf": "pdf",
    "image/png": "image",
    "image/jpeg": "image",
    "image/gif": "image",
    "image/webp": "image",
    "audio/mpeg": "audio",
    "audio/wav": "audio",
    "video/mp4": "video",
}


def _classify_attachment(mime: str | None) -> str:
    if not mime:
        return "other"
    if mime in _ATTACHMENT_TYPE_MAP:
        return _ATTACHMENT_TYPE_MAP[mime]
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("audio/"):
        return "audio"
    if mime.startswith("video/"):
        return "video"
    return "other"


@pages_router.post("/{page_id}/attachments/upload")
async def upload_page_attachment(
    page_id: str,
    file: UploadFile = File(...),
    title: str = Form(""),
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf: None = Depends(require_csrf_protection),
) -> dict[str, Any]:
    """Upload a file as an attachment of the page. Stores the binary in
    the S2 attachments bucket and returns the new NotebookAttachment row."""
    page = _get_page_or_404(db, page_id, workspace_id)

    body = await file.read()
    size = len(body)
    max_bytes = settings.notebook_attachment_max_bytes
    if size > max_bytes:
        raise ApiError(
            "file_too_large",
            f"Attachment exceeds {max_bytes} bytes",
            status_code=413,
        )

    safe_name = storage_service.sanitize_filename(file.filename or "file")
    object_key = f"{workspace_id}/{page.id}/{uuid4().hex}/{safe_name}"

    storage_service.get_s3_client().put_object(
        Bucket=settings.s3_notebook_attachments_bucket,
        Key=object_key,
        Body=body,
        ContentType=file.content_type or "application/octet-stream",
    )

    attachment = NotebookAttachment(
        page_id=page.id,
        data_item_id=None,
        attachment_type=_classify_attachment(file.content_type),
        title=title or safe_name,
        meta_json={
            "object_key": object_key,
            "mime_type": file.content_type or "application/octet-stream",
            "size_bytes": size,
        },
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)

    return {
        "attachment_id": attachment.id,
        "filename": safe_name,
        "mime_type": file.content_type or "application/octet-stream",
        "size_bytes": size,
        "attachment_type": attachment.attachment_type,
    }
```

Near the top of the file, ensure `settings` is imported:

```python
from app.core.config import settings
```

- [ ] **Step 4: Run to verify pass**

Run: `cd apps/api && .venv/bin/pytest tests/test_attachment_upload.py -v`
Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/routers/notebooks.py apps/api/tests/test_attachment_upload.py
git commit -m "feat(api): POST /pages/{id}/attachments/upload — stores in MinIO, inserts row"
```

---

### Task 4: Attachment URL endpoint GET /attachments/{id}/url

**Files:**
- Create: `apps/api/app/routers/attachments.py`
- Modify: `apps/api/app/main.py`
- Modify: `apps/api/tests/test_attachment_upload.py`

- [ ] **Step 1: Append a failing test**

Append to `apps/api/tests/test_attachment_upload.py`:

```python
def test_attachment_url_returns_presigned_url() -> None:
    client, auth = _register_client("u4@x.co")
    page_id = _seed_page(auth["ws_id"], auth["user_id"])
    import io as _io
    files = {"file": ("doc.pdf", _io.BytesIO(b"pdf-bytes"), "application/pdf")}
    upload = client.post(
        f"/api/v1/pages/{page_id}/attachments/upload",
        files=files,
    ).json()

    resp = client.get(f"/api/v1/attachments/{upload['attachment_id']}/url")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["url"].startswith("http")
    # The presigned URL should reference the stored object key.
    assert "doc.pdf" in body["url"] or upload["attachment_id"] in body["url"]
    assert body["expires_in_seconds"] == 900
```

The `FakeS3Client` used in tests does not implement `generate_presigned_url`,
so the new router will use a small helper that falls back to a deterministic
`s3://` URL when the client is a fake. The assertion `"doc.pdf" in url or
attachment_id in url` tolerates either form.

Extend `tests/fixtures/fake_s3.py` to add a stub for
`generate_presigned_url`. Edit
`apps/api/tests/fixtures/fake_s3.py` and append a new method inside
`FakeS3Client`:

```python
    def generate_presigned_url(
        self, operation: str = "get_object", *, Params: dict[str, Any] | None = None,
        ExpiresIn: int = 900, **_: Any,
    ) -> str:
        params = Params or {}
        bucket = params.get("Bucket", "")
        key = params.get("Key", "")
        return f"http://fake-s3/{bucket}/{key}?sig=stub&expires={ExpiresIn}"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && .venv/bin/pytest tests/test_attachment_upload.py::test_attachment_url_returns_presigned_url -v`
Expected: FAIL — 404 (router not registered).

- [ ] **Step 3: Create the attachments router**

Create `apps/api/app/routers/attachments.py`:

```python
"""Attachment URL fetch API (S2)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import (
    get_current_user,
    get_current_workspace_id,
    get_db_session,
)
from app.core.errors import ApiError
from app.models import Notebook, NotebookAttachment, NotebookPage, User
from app.services import storage as storage_service

router = APIRouter(prefix="/api/v1/attachments", tags=["attachments"])


@router.get("/{attachment_id}/url")
def get_attachment_url(
    attachment_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
) -> dict[str, Any]:
    _ = current_user

    att = db.query(NotebookAttachment).filter_by(id=attachment_id).first()
    if att is None:
        raise ApiError("not_found", "Attachment not found", status_code=404)

    # Verify workspace ownership through page → notebook.
    page = db.query(NotebookPage).filter_by(id=att.page_id).first()
    if page is None:
        raise ApiError("not_found", "Attachment page missing", status_code=404)
    nb = (
        db.query(Notebook)
        .filter(Notebook.id == page.notebook_id, Notebook.workspace_id == workspace_id)
        .first()
    )
    if nb is None:
        raise ApiError("not_found", "Attachment not found", status_code=404)

    object_key = (att.meta_json or {}).get("object_key")
    if not object_key:
        raise ApiError("not_found", "Attachment object key missing", status_code=404)

    presign_client = storage_service.get_s3_client()
    # Prefer the dedicated presign client if the app exposes one; otherwise
    # the normal client. Both support generate_presigned_url under boto3.
    try:
        presign_client = storage_service.get_s3_presign_client()
    except Exception:  # noqa: BLE001
        pass

    expires_in = settings.s3_presign_expire_seconds
    url = presign_client.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": settings.s3_notebook_attachments_bucket,
            "Key": object_key,
        },
        ExpiresIn=expires_in,
    )
    return {"url": url, "expires_in_seconds": expires_in}
```

- [ ] **Step 4: Register the router in main.py**

Open `apps/api/app/main.py`. Update the existing `from app.routers
import ...` line to add `attachments`:

```python
from app.routers import (
    ai_actions, attachments, auth, chat, datasets, memory, memory_stream,
    model_catalog, models, notebook_ai, notebooks, pipeline, projects,
    realtime, study, uploads,
)
```

Then add the include near the other `app.include_router(...)` calls:

```python
app.include_router(attachments.router)
```

- [ ] **Step 5: Run to verify pass**

Run: `cd apps/api && .venv/bin/pytest tests/test_attachment_upload.py -v`
Expected: 4 PASSED.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/routers/attachments.py apps/api/app/main.py apps/api/tests/test_attachment_upload.py apps/api/tests/fixtures/fake_s3.py
git commit -m "feat(api): GET /attachments/{id}/url — presigned URL for page attachments"
```

---

### Task 5: Task complete endpoint POST /pages/{id}/tasks/{block_id}/complete

**Files:**
- Modify: `apps/api/app/routers/notebooks.py`
- Test: `apps/api/tests/test_task_complete.py` (new)

- [ ] **Step 1: Write the failing test**

Create `apps/api/tests/test_task_complete.py`:

```python
# ruff: noqa: E402
import atexit, importlib, os, shutil, tempfile
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-s2-task-"))
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
    AIActionLog, Notebook, NotebookPage, Project, User, Workspace,
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


def _seed_page(ws_id: str, user_id: str) -> str:
    with SessionLocal() as db:
        pr = Project(workspace_id=ws_id, name="P"); db.add(pr); db.commit(); db.refresh(pr)
        nb = Notebook(workspace_id=ws_id, project_id=pr.id, created_by=user_id,
                      title="NB", slug="nb")
        db.add(nb); db.commit(); db.refresh(nb)
        pg = NotebookPage(notebook_id=nb.id, created_by=user_id, title="T",
                          slug="t", plain_text="x")
        db.add(pg); db.commit(); db.refresh(pg)
        return pg.id


def test_task_complete_creates_action_log() -> None:
    client, auth = _register_client("t1@x.co")
    page_id = _seed_page(auth["ws_id"], auth["user_id"])
    block_id = "11111111-2222-3333-4444-555555555555"

    resp = client.post(
        f"/api/v1/pages/{page_id}/tasks/{block_id}/complete",
        json={"completed": True, "completed_at": "2026-04-16T12:00:00+00:00"},
    )
    assert resp.status_code == 200

    with SessionLocal() as db:
        log = db.query(AIActionLog).one()
    assert log.action_type == "task.complete"
    assert log.block_id == block_id
    assert log.page_id == page_id
    assert log.input_json["completed"] is True


def test_task_reopen_uses_reopen_action_type() -> None:
    client, auth = _register_client("t2@x.co")
    page_id = _seed_page(auth["ws_id"], auth["user_id"])
    block_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    resp = client.post(
        f"/api/v1/pages/{page_id}/tasks/{block_id}/complete",
        json={"completed": False, "completed_at": None},
    )
    assert resp.status_code == 200

    with SessionLocal() as db:
        log = db.query(AIActionLog).one()
    assert log.action_type == "task.reopen"
    assert log.input_json["completed"] is False


def test_task_cross_workspace_404() -> None:
    _client_a, auth_a = _register_client("a@x.co")
    page_id = _seed_page(auth_a["ws_id"], auth_a["user_id"])

    client_b, _ = _register_client("b@x.co")
    resp = client_b.post(
        f"/api/v1/pages/{page_id}/tasks/xxx/complete",
        json={"completed": True},
    )
    assert resp.status_code == 404
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && .venv/bin/pytest tests/test_task_complete.py::test_task_complete_creates_action_log -v`
Expected: FAIL — 404.

- [ ] **Step 3: Implement the endpoint**

In `apps/api/app/routers/notebooks.py`, ensure `action_log_context` is
imported:

```python
from app.services.ai_action_logger import action_log_context
```

Append a new endpoint at the bottom of the file (after the last
`@pages_router.post(...)`):

```python
@pages_router.post("/{page_id}/tasks/{block_id}/complete")
async def complete_task_block(
    page_id: str,
    block_id: str,
    payload: dict[str, Any],
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf: None = Depends(require_csrf_protection),
) -> dict[str, Any]:
    """Record a task-block completion toggle as an AIActionLog.

    No LLM usage is involved — this is a pure audit entry so later
    subsystems (S5 proactive services) can mine it.
    """
    page = _get_page_or_404(db, page_id, workspace_id)
    completed = bool(payload.get("completed", True))
    completed_at = payload.get("completed_at")

    async with action_log_context(
        db,
        workspace_id=str(workspace_id),
        user_id=str(current_user.id),
        action_type="task.complete" if completed else "task.reopen",
        scope="page",
        notebook_id=str(page.notebook_id),
        page_id=str(page.id),
        block_id=block_id,
    ) as log:
        log.set_input({
            "block_id": block_id,
            "completed": completed,
            "completed_at": completed_at,
        })
        log.set_output({"ok": True})

    return {"ok": True}
```

- [ ] **Step 4: Run to verify pass**

Run: `cd apps/api && .venv/bin/pytest tests/test_task_complete.py -v`
Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/routers/notebooks.py apps/api/tests/test_task_complete.py
git commit -m "feat(api): POST /pages/{id}/tasks/{block_id}/complete — task toggle audit log"
```

---

### Task 6: TipTap `file` block extension

**Files:**
- Create: `apps/web/components/console/editor/extensions/FileBlock.tsx`
- Test: `apps/web/tests/unit/block-schemas.test.ts`

- [ ] **Step 1: Write the failing vitest**

Create `apps/web/tests/unit/block-schemas.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { Editor } from "@tiptap/core";
import Document from "@tiptap/extension-document";
import Text from "@tiptap/extension-text";
import Paragraph from "@tiptap/extension-paragraph";
import FileBlock from "@/components/console/editor/extensions/FileBlock";

function buildEditor(extensions: unknown[]) {
  return new Editor({
    extensions: [Document, Text, Paragraph, ...(extensions as never[])],
    content: "",
  });
}

describe("FileBlock schema", () => {
  it("inserts with expected default attrs", () => {
    const editor = buildEditor([FileBlock]);
    editor
      .chain()
      .focus()
      .insertContent({
        type: "file",
        attrs: {
          attachment_id: "att_1",
          filename: "a.pdf",
          mime_type: "application/pdf",
          size_bytes: 42,
        },
      })
      .run();
    const json = editor.getJSON();
    const fileNode = (json.content ?? []).find((n) => n.type === "file");
    expect(fileNode?.attrs?.attachment_id).toBe("att_1");
    expect(fileNode?.attrs?.filename).toBe("a.pdf");
    expect(fileNode?.attrs?.mime_type).toBe("application/pdf");
    expect(fileNode?.attrs?.size_bytes).toBe(42);
  });

  it("round-trips JSON through setContent", () => {
    const editor = buildEditor([FileBlock]);
    const original = {
      type: "doc",
      content: [
        {
          type: "file",
          attrs: {
            attachment_id: "att_2",
            filename: "x.png",
            mime_type: "image/png",
            size_bytes: 7,
          },
        },
      ],
    };
    editor.commands.setContent(original);
    const roundtripped = editor.getJSON();
    expect(roundtripped.content?.[0].type).toBe("file");
    expect(roundtripped.content?.[0].attrs?.filename).toBe("x.png");
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/web && pnpm test:unit tests/unit/block-schemas.test.ts`
Expected: FAIL — cannot resolve `@/.../FileBlock`.

- [ ] **Step 3: Create the extension**

Create `apps/web/components/console/editor/extensions/FileBlock.tsx`:

```tsx
import { Node, mergeAttributes } from "@tiptap/core";
import type { NodeViewProps } from "@tiptap/react";
import { NodeViewWrapper, ReactNodeViewRenderer } from "@tiptap/react";
import { useCallback, useEffect, useRef, useState } from "react";
import { FileUp, Loader2, Download, ExternalLink } from "lucide-react";
import { apiGet, apiPostFormData } from "@/lib/api";

interface FileBlockAttrs {
  attachment_id: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
}

function humanSize(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function extractPageId(): string | null {
  if (typeof window === "undefined") return null;
  const m = window.location.pathname.match(/\/notebooks\/[^/]+\/?.*?(?:pages\/([^/?#]+))?/);
  // pageId is not reliably in the URL for all layouts; fall back to a
  // window-scoped global the NoteEditor sets.
  const fromWindow = (window as unknown as { __MRAI_CURRENT_PAGE_ID?: string })
    .__MRAI_CURRENT_PAGE_ID;
  return fromWindow || (m && m[1]) || null;
}

function FileBlockView(props: NodeViewProps) {
  const attrs = props.node.attrs as FileBlockAttrs;
  const hasAttachment = Boolean(attrs.attachment_id);

  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [url, setUrl] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!attrs.attachment_id) return;
    let cancelled = false;
    void apiGet<{ url: string }>(`/api/v1/attachments/${attrs.attachment_id}/url`)
      .then((r) => {
        if (!cancelled) setUrl(r.url);
      })
      .catch(() => {
        if (!cancelled) setUrl(null);
      });
    return () => {
      cancelled = true;
    };
  }, [attrs.attachment_id]);

  const handlePick = useCallback(() => inputRef.current?.click(), []);

  const handleFile = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file) return;
      const pageId = extractPageId();
      if (!pageId) {
        setError("Page not ready yet, try again.");
        return;
      }
      setUploading(true);
      setError(null);
      try {
        const fd = new FormData();
        fd.append("file", file);
        const resp = await apiPostFormData<{
          attachment_id: string;
          filename: string;
          mime_type: string;
          size_bytes: number;
        }>(`/api/v1/pages/${pageId}/attachments/upload`, fd);
        props.updateAttributes({
          attachment_id: resp.attachment_id,
          filename: resp.filename,
          mime_type: resp.mime_type,
          size_bytes: resp.size_bytes,
        });
      } catch (err) {
        setError(err instanceof Error ? err.message : "Upload failed");
      } finally {
        setUploading(false);
      }
    },
    [props],
  );

  return (
    <NodeViewWrapper className="file-block" data-testid="file-block">
      {!hasAttachment && (
        <button
          type="button"
          onClick={handlePick}
          disabled={uploading}
          data-testid="file-block-upload"
          className="file-block__picker"
        >
          {uploading ? <Loader2 size={14} className="animate-spin" /> : <FileUp size={14} />}
          {uploading ? "Uploading…" : "Upload file"}
        </button>
      )}
      {hasAttachment && (
        <div className="file-block__meta">
          <FileUp size={16} />
          <span className="file-block__name">{attrs.filename}</span>
          <span className="file-block__size">{humanSize(attrs.size_bytes)}</span>
          {url && attrs.mime_type.startsWith("image/") && (
            <img src={url} alt={attrs.filename} className="file-block__preview" />
          )}
          {url && !attrs.mime_type.startsWith("image/") && (
            <a
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              className="file-block__open"
            >
              <ExternalLink size={14} /> Open
            </a>
          )}
          {url && (
            <a
              href={url}
              download={attrs.filename}
              className="file-block__download"
              title="Download"
            >
              <Download size={14} />
            </a>
          )}
        </div>
      )}
      {error && <p className="file-block__error">{error}</p>}
      <input
        ref={inputRef}
        type="file"
        style={{ display: "none" }}
        onChange={handleFile}
      />
    </NodeViewWrapper>
  );
}

const FileBlock = Node.create({
  name: "file",
  group: "block",
  atom: true,
  draggable: true,

  addAttributes() {
    return {
      attachment_id: { default: "" },
      filename: { default: "" },
      mime_type: { default: "" },
      size_bytes: { default: 0 },
    };
  },

  parseHTML() {
    return [{ tag: 'div[data-type="file"]' }];
  },

  renderHTML({ HTMLAttributes }) {
    return ["div", mergeAttributes(HTMLAttributes, { "data-type": "file" })];
  },

  addNodeView() {
    return ReactNodeViewRenderer(FileBlockView);
  },
});

export default FileBlock;
```

- [ ] **Step 4: Run to verify pass**

Run: `cd apps/web && pnpm test:unit tests/unit/block-schemas.test.ts`
Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add apps/web/components/console/editor/extensions/FileBlock.tsx apps/web/tests/unit/block-schemas.test.ts
git commit -m "feat(web): TipTap FileBlock with upload + presigned URL render"
```

---

### Task 7: TipTap `ai_output` block extension

**Files:**
- Create: `apps/web/components/console/editor/extensions/AIOutputBlock.tsx`
- Modify: `apps/web/tests/unit/block-schemas.test.ts`

- [ ] **Step 1: Append the failing test**

Append to `apps/web/tests/unit/block-schemas.test.ts`:

```ts
import AIOutputBlock from "@/components/console/editor/extensions/AIOutputBlock";

describe("AIOutputBlock schema", () => {
  it("inserts with expected default attrs", () => {
    const editor = buildEditor([AIOutputBlock]);
    editor
      .chain()
      .focus()
      .insertContent({
        type: "ai_output",
        attrs: {
          content_markdown: "hello world",
          action_type: "selection.rewrite",
          action_log_id: "log_1",
          model_id: "qwen-plus",
          sources: [{ type: "memory", id: "m1", title: "M" }],
        },
      })
      .run();
    const json = editor.getJSON();
    const node = json.content?.find((n) => n.type === "ai_output");
    expect(node?.attrs?.content_markdown).toBe("hello world");
    expect(node?.attrs?.model_id).toBe("qwen-plus");
    expect((node?.attrs?.sources as { id: string }[] | undefined)?.[0]?.id).toBe("m1");
  });

  it("round-trips JSON through setContent", () => {
    const editor = buildEditor([AIOutputBlock]);
    const original = {
      type: "doc",
      content: [
        {
          type: "ai_output",
          attrs: {
            content_markdown: "rt",
            action_type: "ask",
            action_log_id: "log_2",
            model_id: null,
            sources: [],
          },
        },
      ],
    };
    editor.commands.setContent(original);
    const node = editor.getJSON().content?.[0];
    expect(node?.type).toBe("ai_output");
    expect(node?.attrs?.content_markdown).toBe("rt");
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/web && pnpm test:unit tests/unit/block-schemas.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Create the extension**

Create `apps/web/components/console/editor/extensions/AIOutputBlock.tsx`:

```tsx
import { Node, mergeAttributes } from "@tiptap/core";
import type { NodeViewProps } from "@tiptap/react";
import { NodeViewWrapper, ReactNodeViewRenderer } from "@tiptap/react";
import { Sparkles, Link2 } from "lucide-react";
import ReactMarkdown from "react-markdown";

interface AIOutputAttrs {
  content_markdown: string;
  action_type: string;
  action_log_id: string;
  model_id: string | null;
  sources: Array<{ type: string; id: string; title: string }>;
}

function AIOutputBlockView(props: NodeViewProps) {
  const attrs = props.node.attrs as AIOutputAttrs;

  const handleViewTrace = () => {
    if (!attrs.action_log_id) return;
    // Dispatch a custom event so the AI Panel (Trace tab) can subscribe.
    window.dispatchEvent(
      new CustomEvent("mrai:open-trace", {
        detail: { action_log_id: attrs.action_log_id },
      }),
    );
  };

  return (
    <NodeViewWrapper className="ai-output-block" data-testid="ai-output-block">
      <div className="ai-output-block__header">
        <Sparkles size={14} />
        <span className="ai-output-block__badge">
          AI
          {attrs.action_type ? ` · ${attrs.action_type}` : ""}
          {attrs.model_id ? ` · ${attrs.model_id}` : ""}
        </span>
        {attrs.action_log_id && (
          <button
            type="button"
            className="ai-output-block__trace-btn"
            onClick={handleViewTrace}
            data-testid="ai-output-view-trace"
          >
            View trace
          </button>
        )}
      </div>
      <div className="ai-output-block__body">
        {attrs.content_markdown ? (
          <ReactMarkdown>{attrs.content_markdown}</ReactMarkdown>
        ) : (
          <p className="ai-output-block__empty">(empty AI block — use AI Panel to fill)</p>
        )}
      </div>
      {Array.isArray(attrs.sources) && attrs.sources.length > 0 && (
        <div className="ai-output-block__sources">
          {attrs.sources.map((s, idx) => (
            <span key={`${s.type}-${s.id}-${idx}`} className="ai-output-block__source">
              <Link2 size={12} /> {s.type} · {s.title}
            </span>
          ))}
        </div>
      )}
    </NodeViewWrapper>
  );
}

const AIOutputBlock = Node.create({
  name: "ai_output",
  group: "block",
  atom: true,
  draggable: true,

  addAttributes() {
    return {
      content_markdown: { default: "" },
      action_type: { default: "" },
      action_log_id: { default: "" },
      model_id: { default: null as string | null },
      sources: { default: [] as Array<{ type: string; id: string; title: string }> },
    };
  },

  parseHTML() {
    return [{ tag: 'div[data-type="ai_output"]' }];
  },

  renderHTML({ HTMLAttributes }) {
    return ["div", mergeAttributes(HTMLAttributes, { "data-type": "ai_output" })];
  },

  addNodeView() {
    return ReactNodeViewRenderer(AIOutputBlockView);
  },
});

export default AIOutputBlock;
```

- [ ] **Step 4: Run to verify pass**

Run: `cd apps/web && pnpm test:unit tests/unit/block-schemas.test.ts`
Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```bash
git add apps/web/components/console/editor/extensions/AIOutputBlock.tsx apps/web/tests/unit/block-schemas.test.ts
git commit -m "feat(web): TipTap AIOutputBlock with markdown body and trace link"
```

---

### Task 8: TipTap `reference` block extension

**Files:**
- Create: `apps/web/components/console/editor/extensions/ReferenceBlock.tsx`
- Modify: `apps/web/tests/unit/block-schemas.test.ts`

- [ ] **Step 1: Append the failing test**

```ts
import ReferenceBlock from "@/components/console/editor/extensions/ReferenceBlock";

describe("ReferenceBlock schema", () => {
  it("inserts with expected default attrs", () => {
    const editor = buildEditor([ReferenceBlock]);
    editor
      .chain()
      .focus()
      .insertContent({
        type: "reference",
        attrs: {
          target_type: "page",
          target_id: "p1",
          title: "Intro page",
          snippet: "short snippet",
        },
      })
      .run();
    const node = editor.getJSON().content?.find((n) => n.type === "reference");
    expect(node?.attrs?.target_type).toBe("page");
    expect(node?.attrs?.target_id).toBe("p1");
  });

  it("round-trips JSON through setContent", () => {
    const editor = buildEditor([ReferenceBlock]);
    editor.commands.setContent({
      type: "doc",
      content: [
        {
          type: "reference",
          attrs: {
            target_type: "memory",
            target_id: "m1",
            title: "Memory A",
            snippet: "",
          },
        },
      ],
    });
    const node = editor.getJSON().content?.[0];
    expect(node?.type).toBe("reference");
    expect(node?.attrs?.target_type).toBe("memory");
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/web && pnpm test:unit tests/unit/block-schemas.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Create the extension**

Create `apps/web/components/console/editor/extensions/ReferenceBlock.tsx`:

```tsx
import { Node, mergeAttributes } from "@tiptap/core";
import type { NodeViewProps } from "@tiptap/react";
import { NodeViewWrapper, ReactNodeViewRenderer } from "@tiptap/react";
import { useCallback, useEffect, useState } from "react";
import { FileText, Brain, BookOpen, Link2 } from "lucide-react";
import { apiGet } from "@/lib/api";

type TargetType = "page" | "memory" | "study_chunk";

interface ReferenceAttrs {
  target_type: TargetType | "";
  target_id: string;
  title: string;
  snippet: string;
}

interface PageHit {
  id: string;
  title: string;
  plain_text?: string;
}

interface MemoryHit {
  id: string;
  title?: string;
  content?: string;
}

interface ChunkHit {
  id: string;
  heading?: string;
  content?: string;
}

function iconFor(target: TargetType | "") {
  if (target === "memory") return <Brain size={14} />;
  if (target === "study_chunk") return <BookOpen size={14} />;
  return <FileText size={14} />;
}

function extractNotebookId(): string | null {
  if (typeof window === "undefined") return null;
  const m = window.location.pathname.match(/\/notebooks\/([^/?#]+)/);
  return m ? m[1] : null;
}

function ReferencePickerDialog({
  notebookId,
  onPick,
  onClose,
}: {
  notebookId: string;
  onPick: (attrs: ReferenceAttrs) => void;
  onClose: () => void;
}) {
  const [tab, setTab] = useState<TargetType>("page");
  const [q, setQ] = useState("");
  const [results, setResults] = useState<Array<{ id: string; title: string; snippet: string }>>([]);
  const [projectId, setProjectId] = useState<string | null>(null);

  useEffect(() => {
    void apiGet<{ project_id: string | null }>(`/api/v1/notebooks/${notebookId}`)
      .then((nb) => setProjectId(nb.project_id))
      .catch(() => setProjectId(null));
  }, [notebookId]);

  useEffect(() => {
    const handle = setTimeout(() => {
      if (tab === "page") {
        void apiGet<{ items: PageHit[] }>(
          `/api/v1/pages/search?q=${encodeURIComponent(q)}&notebook_id=${notebookId}`,
        )
          .then((r) =>
            setResults(
              r.items.map((p) => ({
                id: p.id,
                title: p.title || "(untitled)",
                snippet: (p.plain_text || "").slice(0, 240),
              })),
            ),
          )
          .catch(() => setResults([]));
      } else if (tab === "memory" && projectId) {
        void apiGet<{ items: MemoryHit[] }>(
          `/api/v1/memory/search?q=${encodeURIComponent(q)}&project_id=${projectId}&limit=10`,
        )
          .then((r) =>
            setResults(
              r.items.map((m) => ({
                id: m.id,
                title: m.title || m.content?.slice(0, 80) || "(memory)",
                snippet: (m.content || "").slice(0, 240),
              })),
            ),
          )
          .catch(() => setResults([]));
      } else if (tab === "study_chunk") {
        void apiGet<{ items: Array<{ id: string; title: string }> }>(
          `/api/v1/notebooks/${notebookId}/study-assets`,
        )
          .then(async (r) => {
            const first = r.items[0];
            if (!first) {
              setResults([]);
              return;
            }
            const chunks = await apiGet<{ items: ChunkHit[] }>(
              `/api/v1/study-assets/${first.id}/chunks`,
            );
            setResults(
              chunks.items
                .filter((c) => !q || (c.heading || "").toLowerCase().includes(q.toLowerCase()))
                .map((c) => ({
                  id: c.id,
                  title: c.heading || "(chunk)",
                  snippet: (c.content || "").slice(0, 240),
                })),
            );
          })
          .catch(() => setResults([]));
      }
    }, 250);
    return () => clearTimeout(handle);
  }, [tab, q, notebookId, projectId]);

  return (
    <div className="reference-picker" role="dialog" data-testid="reference-picker">
      <div className="reference-picker__tabs">
        {(["page", "memory", "study_chunk"] as const).map((k) => (
          <button
            key={k}
            type="button"
            onClick={() => setTab(k)}
            className={tab === k ? "is-active" : ""}
            data-testid={`reference-picker-tab-${k}`}
          >
            {k === "page" ? "Pages" : k === "memory" ? "Memory" : "Chunks"}
          </button>
        ))}
        <button type="button" onClick={onClose} className="reference-picker__close">
          ×
        </button>
      </div>
      <input
        type="text"
        placeholder="Search…"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        className="reference-picker__search"
        data-testid="reference-picker-search"
      />
      <ul className="reference-picker__results">
        {results.map((item) => (
          <li key={item.id}>
            <button
              type="button"
              onClick={() =>
                onPick({
                  target_type: tab,
                  target_id: item.id,
                  title: item.title,
                  snippet: item.snippet,
                })
              }
              data-testid="reference-picker-item"
            >
              <div className="reference-picker__item-title">{item.title}</div>
              {item.snippet && (
                <div className="reference-picker__item-snippet">{item.snippet}</div>
              )}
            </button>
          </li>
        ))}
        {results.length === 0 && <li className="reference-picker__empty">No results</li>}
      </ul>
    </div>
  );
}

function ReferenceBlockView(props: NodeViewProps) {
  const attrs = props.node.attrs as ReferenceAttrs;
  const [picking, setPicking] = useState(!attrs.target_id);

  const handlePick = useCallback(
    (next: ReferenceAttrs) => {
      props.updateAttributes(next);
      setPicking(false);
    },
    [props],
  );

  const handleOpen = useCallback(() => {
    // Note: full openWindow wiring happens in NoteEditor context; here we
    // dispatch a DOM event the editor layer subscribes to.
    window.dispatchEvent(
      new CustomEvent("mrai:open-reference", { detail: attrs }),
    );
  }, [attrs]);

  const notebookId = extractNotebookId();

  return (
    <NodeViewWrapper
      className="reference-block"
      data-testid="reference-block"
      contentEditable={false}
    >
      {picking && notebookId ? (
        <ReferencePickerDialog
          notebookId={notebookId}
          onPick={handlePick}
          onClose={() => setPicking(false)}
        />
      ) : (
        <button
          type="button"
          onClick={handleOpen}
          className="reference-block__card"
          data-testid="reference-block-open"
        >
          {iconFor(attrs.target_type)}
          <div className="reference-block__content">
            <div className="reference-block__title">{attrs.title || "(unnamed)"}</div>
            {attrs.snippet && (
              <div className="reference-block__snippet">{attrs.snippet}</div>
            )}
          </div>
          <Link2 size={12} />
        </button>
      )}
    </NodeViewWrapper>
  );
}

const ReferenceBlock = Node.create({
  name: "reference",
  group: "block",
  atom: true,
  draggable: true,

  addAttributes() {
    return {
      target_type: { default: "" },
      target_id: { default: "" },
      title: { default: "" },
      snippet: { default: "" },
    };
  },

  parseHTML() {
    return [{ tag: 'div[data-type="reference"]' }];
  },

  renderHTML({ HTMLAttributes }) {
    return ["div", mergeAttributes(HTMLAttributes, { "data-type": "reference" })];
  },

  addNodeView() {
    return ReactNodeViewRenderer(ReferenceBlockView);
  },
});

export default ReferenceBlock;
```

- [ ] **Step 4: Run to verify pass**

Run: `cd apps/web && pnpm test:unit tests/unit/block-schemas.test.ts`
Expected: 6 PASSED.

- [ ] **Step 5: Commit**

```bash
git add apps/web/components/console/editor/extensions/ReferenceBlock.tsx apps/web/tests/unit/block-schemas.test.ts
git commit -m "feat(web): TipTap ReferenceBlock with page/memory/chunk picker"
```

---

### Task 9: TipTap `task` block extension

**Files:**
- Create: `apps/web/components/console/editor/extensions/TaskBlock.tsx`
- Modify: `apps/web/tests/unit/block-schemas.test.ts`

- [ ] **Step 1: Append the failing test**

```ts
import TaskBlock from "@/components/console/editor/extensions/TaskBlock";

describe("TaskBlock schema", () => {
  it("inserts with expected default attrs", () => {
    const editor = buildEditor([TaskBlock]);
    editor
      .chain()
      .focus()
      .insertContent({
        type: "task",
        attrs: {
          block_id: "b1",
          title: "do X",
          description: null,
          due_date: null,
          completed: false,
          completed_at: null,
        },
      })
      .run();
    const node = editor.getJSON().content?.find((n) => n.type === "task");
    expect(node?.attrs?.block_id).toBe("b1");
    expect(node?.attrs?.completed).toBe(false);
  });

  it("round-trips JSON through setContent", () => {
    const editor = buildEditor([TaskBlock]);
    editor.commands.setContent({
      type: "doc",
      content: [
        {
          type: "task",
          attrs: {
            block_id: "b2",
            title: "rt",
            description: "desc",
            due_date: "2026-05-01",
            completed: true,
            completed_at: "2026-04-16T00:00:00Z",
          },
        },
      ],
    });
    const node = editor.getJSON().content?.[0];
    expect(node?.type).toBe("task");
    expect(node?.attrs?.completed).toBe(true);
    expect(node?.attrs?.due_date).toBe("2026-05-01");
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/web && pnpm test:unit tests/unit/block-schemas.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Create the extension**

Create `apps/web/components/console/editor/extensions/TaskBlock.tsx`:

```tsx
import { Node, mergeAttributes } from "@tiptap/core";
import type { NodeViewProps } from "@tiptap/react";
import { NodeViewWrapper, ReactNodeViewRenderer } from "@tiptap/react";
import { useCallback, useState } from "react";
import { CalendarDays, MoreVertical } from "lucide-react";
import { apiPost } from "@/lib/api";

interface TaskAttrs {
  block_id: string;
  title: string;
  description: string | null;
  due_date: string | null;
  completed: boolean;
  completed_at: string | null;
}

function extractPageId(): string | null {
  if (typeof window === "undefined") return null;
  const fromWindow = (window as unknown as { __MRAI_CURRENT_PAGE_ID?: string })
    .__MRAI_CURRENT_PAGE_ID;
  return fromWindow || null;
}

function TaskBlockView(props: NodeViewProps) {
  const attrs = props.node.attrs as TaskAttrs;
  const [expanded, setExpanded] = useState(false);
  const [failed, setFailed] = useState(false);

  const handleToggle = useCallback(async () => {
    const pageId = extractPageId();
    const nextCompleted = !attrs.completed;
    const nextCompletedAt = nextCompleted ? new Date().toISOString() : null;
    // Optimistic flip.
    props.updateAttributes({ completed: nextCompleted, completed_at: nextCompletedAt });
    setFailed(false);

    if (!pageId || !attrs.block_id) return;
    try {
      await apiPost(
        `/api/v1/pages/${pageId}/tasks/${attrs.block_id}/complete`,
        { completed: nextCompleted, completed_at: nextCompletedAt },
      );
    } catch {
      // Roll back.
      props.updateAttributes({ completed: attrs.completed, completed_at: attrs.completed_at });
      setFailed(true);
    }
  }, [attrs, props]);

  return (
    <NodeViewWrapper className="task-block" data-testid="task-block">
      <div className="task-block__row">
        <input
          type="checkbox"
          checked={attrs.completed}
          onChange={handleToggle}
          data-testid="task-block-checkbox"
        />
        <input
          type="text"
          className="task-block__title"
          value={attrs.title}
          placeholder="Task title"
          onChange={(e) => props.updateAttributes({ title: e.target.value })}
        />
        {attrs.due_date && (
          <span className="task-block__due">
            <CalendarDays size={12} /> {attrs.due_date}
          </span>
        )}
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="task-block__menu"
          title="Details"
        >
          <MoreVertical size={14} />
        </button>
      </div>
      {expanded && (
        <div className="task-block__expanded">
          <textarea
            placeholder="Description"
            value={attrs.description ?? ""}
            onChange={(e) =>
              props.updateAttributes({ description: e.target.value || null })
            }
          />
          <input
            type="date"
            value={attrs.due_date ?? ""}
            onChange={(e) =>
              props.updateAttributes({ due_date: e.target.value || null })
            }
          />
        </div>
      )}
      {failed && <p className="task-block__error">Couldn't save; try again.</p>}
    </NodeViewWrapper>
  );
}

const TaskBlock = Node.create({
  name: "task",
  group: "block",
  atom: true,
  draggable: true,

  addAttributes() {
    return {
      block_id: { default: "" },
      title: { default: "" },
      description: { default: null as string | null },
      due_date: { default: null as string | null },
      completed: { default: false },
      completed_at: { default: null as string | null },
    };
  },

  parseHTML() {
    return [{ tag: 'div[data-type="task"]' }];
  },

  renderHTML({ HTMLAttributes }) {
    return ["div", mergeAttributes(HTMLAttributes, { "data-type": "task" })];
  },

  addNodeView() {
    return ReactNodeViewRenderer(TaskBlockView);
  },
});

export default TaskBlock;
```

- [ ] **Step 4: Run to verify pass**

Run: `cd apps/web && pnpm test:unit tests/unit/block-schemas.test.ts`
Expected: 8 PASSED.

- [ ] **Step 5: Commit**

```bash
git add apps/web/components/console/editor/extensions/TaskBlock.tsx apps/web/tests/unit/block-schemas.test.ts
git commit -m "feat(web): TipTap TaskBlock with optimistic toggle + audit post"
```

---

### Task 10: TipTap `flashcard` block extension

**Files:**
- Create: `apps/web/components/console/editor/extensions/FlashcardBlock.tsx`
- Modify: `apps/web/tests/unit/block-schemas.test.ts`

- [ ] **Step 1: Append the failing test**

```ts
import FlashcardBlock from "@/components/console/editor/extensions/FlashcardBlock";

describe("FlashcardBlock schema", () => {
  it("inserts with expected default attrs", () => {
    const editor = buildEditor([FlashcardBlock]);
    editor
      .chain()
      .focus()
      .insertContent({
        type: "flashcard",
        attrs: { front: "Q", back: "A", flipped: false },
      })
      .run();
    const node = editor.getJSON().content?.find((n) => n.type === "flashcard");
    expect(node?.attrs?.front).toBe("Q");
    expect(node?.attrs?.back).toBe("A");
    expect(node?.attrs?.flipped).toBe(false);
  });

  it("round-trips JSON through setContent", () => {
    const editor = buildEditor([FlashcardBlock]);
    editor.commands.setContent({
      type: "doc",
      content: [
        {
          type: "flashcard",
          attrs: { front: "rt-q", back: "rt-a", flipped: true },
        },
      ],
    });
    const node = editor.getJSON().content?.[0];
    expect(node?.type).toBe("flashcard");
    expect(node?.attrs?.flipped).toBe(true);
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/web && pnpm test:unit tests/unit/block-schemas.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Create the extension**

Create `apps/web/components/console/editor/extensions/FlashcardBlock.tsx`:

```tsx
import { Node, mergeAttributes } from "@tiptap/core";
import type { NodeViewProps } from "@tiptap/react";
import { NodeViewWrapper, ReactNodeViewRenderer } from "@tiptap/react";
import { useCallback, useState } from "react";
import { Layers, Pencil, Eye } from "lucide-react";

interface FlashcardAttrs {
  front: string;
  back: string;
  flipped: boolean;
}

function FlashcardBlockView(props: NodeViewProps) {
  const attrs = props.node.attrs as FlashcardAttrs;
  const [mode, setMode] = useState<"edit" | "preview">(
    attrs.front || attrs.back ? "preview" : "edit",
  );

  const handleFlip = useCallback(() => {
    props.updateAttributes({ flipped: !attrs.flipped });
  }, [attrs.flipped, props]);

  const isBack = attrs.flipped;

  return (
    <NodeViewWrapper className="flashcard-block" data-testid="flashcard-block">
      <div className="flashcard-block__toolbar">
        <Layers size={14} />
        <button
          type="button"
          className={`flashcard-block__mode${mode === "edit" ? " is-active" : ""}`}
          onClick={() => setMode("edit")}
          data-testid="flashcard-mode-edit"
        >
          <Pencil size={12} /> Edit
        </button>
        <button
          type="button"
          className={`flashcard-block__mode${mode === "preview" ? " is-active" : ""}`}
          onClick={() => setMode("preview")}
          data-testid="flashcard-mode-preview"
        >
          <Eye size={12} /> Preview
        </button>
      </div>
      {mode === "edit" ? (
        <div className="flashcard-block__editor">
          <textarea
            placeholder="Front (question)"
            value={attrs.front}
            onChange={(e) => props.updateAttributes({ front: e.target.value })}
            data-testid="flashcard-front"
          />
          <textarea
            placeholder="Back (answer)"
            value={attrs.back}
            onChange={(e) => props.updateAttributes({ back: e.target.value })}
            data-testid="flashcard-back"
          />
        </div>
      ) : (
        <button
          type="button"
          onClick={handleFlip}
          className={`flashcard-block__card${isBack ? " is-flipped" : ""}`}
          aria-label={
            isBack ? "Flashcard, back side" : "Flashcard, front side"
          }
          data-testid="flashcard-card"
        >
          <span className="flashcard-block__hint">
            {isBack ? "Answer" : "Question"} · click to flip
          </span>
          <div className="flashcard-block__body">
            {isBack ? attrs.back || "(empty)" : attrs.front || "(empty)"}
          </div>
        </button>
      )}
    </NodeViewWrapper>
  );
}

const FlashcardBlock = Node.create({
  name: "flashcard",
  group: "block",
  atom: true,
  draggable: true,

  addAttributes() {
    return {
      front: { default: "" },
      back: { default: "" },
      flipped: { default: false },
    };
  },

  parseHTML() {
    return [{ tag: 'div[data-type="flashcard"]' }];
  },

  renderHTML({ HTMLAttributes }) {
    return ["div", mergeAttributes(HTMLAttributes, { "data-type": "flashcard" })];
  },

  addNodeView() {
    return ReactNodeViewRenderer(FlashcardBlockView);
  },
});

export default FlashcardBlock;
```

- [ ] **Step 4: Run to verify pass**

Run: `cd apps/web && pnpm test:unit tests/unit/block-schemas.test.ts`
Expected: 10 PASSED.

- [ ] **Step 5: Commit**

```bash
git add apps/web/components/console/editor/extensions/FlashcardBlock.tsx apps/web/tests/unit/block-schemas.test.ts
git commit -m "feat(web): TipTap FlashcardBlock with edit/preview + flip"
```

---

### Task 11: Wire extensions into editor + slash menu

**Files:**
- Modify: `apps/web/components/console/editor/extensions/index.ts`
- Modify: `apps/web/components/console/editor/NoteEditor.tsx`
- Modify: `apps/web/components/console/editor/SlashCommandMenu.tsx`

- [ ] **Step 1: Extend the extensions barrel**

Replace `apps/web/components/console/editor/extensions/index.ts` with:

```ts
export { default as MathBlock } from "./MathBlock";
export { default as InlineMath } from "./InlineMath";
export { default as CalloutBlock } from "./CalloutBlock";
export { default as WhiteboardBlock } from "./WhiteboardBlock";
export { default as FileBlock } from "./FileBlock";
export { default as AIOutputBlock } from "./AIOutputBlock";
export { default as ReferenceBlock } from "./ReferenceBlock";
export { default as TaskBlock } from "./TaskBlock";
export { default as FlashcardBlock } from "./FlashcardBlock";
```

- [ ] **Step 2: Import and register in NoteEditor**

Open `apps/web/components/console/editor/NoteEditor.tsx`. Locate:

```tsx
import { MathBlock, InlineMath, CalloutBlock, WhiteboardBlock } from "./extensions";
```

Replace with:

```tsx
import {
  MathBlock,
  InlineMath,
  CalloutBlock,
  WhiteboardBlock,
  FileBlock,
  AIOutputBlock,
  ReferenceBlock,
  TaskBlock,
  FlashcardBlock,
} from "./extensions";
```

In the same file, find the `extensions: [...]` array inside
`useEditor({...})`. Insert the five new names right after
`WhiteboardBlock,`:

```tsx
      WhiteboardBlock,
      FileBlock,
      AIOutputBlock,
      ReferenceBlock,
      TaskBlock,
      FlashcardBlock,
      SlashCommand,
```

Also — so that the new blocks can learn the current `pageId` without
prop drilling — add a useEffect that pins it to `window`:

```tsx
  useEffect(() => {
    if (typeof window === "undefined") return;
    (window as unknown as { __MRAI_CURRENT_PAGE_ID?: string }).__MRAI_CURRENT_PAGE_ID = pageId;
    return () => {
      if (typeof window === "undefined") return;
      (window as unknown as { __MRAI_CURRENT_PAGE_ID?: string }).__MRAI_CURRENT_PAGE_ID = undefined;
    };
  }, [pageId]);
```

Put this `useEffect` with the other hooks at the top of the component
body (after the existing `useEffect` that loads the page).

- [ ] **Step 3: Add slash menu entries**

Open `apps/web/components/console/editor/SlashCommandMenu.tsx`. Update
the `lucide-react` import to include the new icons — change:

```tsx
import {
  Heading1,
  Heading2,
  Heading3,
  List,
  ListOrdered,
  CheckSquare,
  Code,
  Quote,
  Minus,
  ImageIcon,
  Sigma,
  AlertCircle,
  Type,
  PenTool,
} from "lucide-react";
```

to:

```tsx
import {
  Heading1,
  Heading2,
  Heading3,
  List,
  ListOrdered,
  CheckSquare,
  Code,
  Quote,
  Minus,
  ImageIcon,
  Sigma,
  AlertCircle,
  Type,
  PenTool,
  FileUp,
  Sparkles,
  Link2,
  CheckCircle2,
  Layers,
} from "lucide-react";
```

At the end of the `COMMANDS` array (just before the closing `]`), add
the five new entries:

```ts
  {
    title: "File",
    description: "Upload and embed a file",
    icon: FileUp,
    command: (editor) =>
      editor.chain().focus().insertContent({ type: "file" }).run(),
  },
  {
    title: "AI Output",
    description: "Placeholder AI block (use AI Panel to fill)",
    icon: Sparkles,
    command: (editor) =>
      editor
        .chain()
        .focus()
        .insertContent({
          type: "ai_output",
          attrs: { content_markdown: "", action_type: "", action_log_id: "" },
        })
        .run(),
  },
  {
    title: "Reference",
    description: "Link to a page, memory, or chapter",
    icon: Link2,
    command: (editor) =>
      editor.chain().focus().insertContent({ type: "reference" }).run(),
  },
  {
    title: "Task",
    description: "Standalone task with completion tracking",
    icon: CheckCircle2,
    command: (editor) =>
      editor
        .chain()
        .focus()
        .insertContent({
          type: "task",
          attrs: {
            block_id: crypto.randomUUID(),
            title: "",
            description: null,
            due_date: null,
            completed: false,
            completed_at: null,
          },
        })
        .run(),
  },
  {
    title: "Flashcard",
    description: "Q/A card that flips on click",
    icon: Layers,
    command: (editor) =>
      editor
        .chain()
        .focus()
        .insertContent({
          type: "flashcard",
          attrs: { front: "", back: "", flipped: false },
        })
        .run(),
  },
```

- [ ] **Step 4: Typecheck**

Run: `cd apps/web && pnpm tsc --noEmit 2>&1 | grep -iE "(NoteEditor|SlashCommand|extensions/index)" | head -20`
Expected: no errors from these files.

- [ ] **Step 5: Commit**

```bash
git add apps/web/components/console/editor/extensions/index.ts apps/web/components/console/editor/NoteEditor.tsx apps/web/components/console/editor/SlashCommandMenu.tsx
git commit -m "feat(web): register 5 new TipTap blocks + slash menu entries"
```

---

### Task 12: AI Panel "Insert as AI block" wiring

**Files:**
- Modify: `apps/web/components/console/editor/AIPanel.tsx`
- Modify: `apps/web/components/notebook/contents/ai-panel-tabs/AskTab.tsx`

- [ ] **Step 1: Extend AIPanel types + capture metadata**

Open `apps/web/components/console/editor/AIPanel.tsx`. Near the top
`interface AIPanelProps`:

```tsx
interface AIPanelProps {
  notebookId?: string;
  pageId?: string;
  selectedText?: string;
  onInsertToEditor?: (text: string) => void;
  onClose: () => void;
}
```

Replace with:

```tsx
interface AIOutputInsertPayload {
  content_markdown: string;
  action_type: string;
  action_log_id: string;
  model_id: string | null;
  sources: Array<{ type: string; id: string; title: string }>;
}

interface AIPanelProps {
  notebookId?: string;
  pageId?: string;
  selectedText?: string;
  onInsertToEditor?: (text: string) => void;
  onInsertAIOutput?: (payload: AIOutputInsertPayload) => void;
  onClose: () => void;
}
```

Extend the local `ChatMessage` interface:

```tsx
interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  sources?: ChatSource[];
  action_log_id?: string;
  model_id?: string | null;
  action_type?: string;
}
```

In the `handleSend` body, alongside `fullSources`, track:

```tsx
    let fullContent = "";
    let fullSources: ChatSource[] = [];
    let fullActionLogId = "";
    let fullModelId: string | null = null;
    let fullActionType = "ask";
```

Inside the event loop, extract from `message_start` and `message_done`:

```tsx
        if (event === "message_start") {
          fullSources = normalizeSources(data.sources);
          setStreamSources(fullSources);
          if (typeof data.action_log_id === "string") {
            fullActionLogId = data.action_log_id;
          }
        } else if (event === "token" && data.content) {
          fullContent += data.content as string;
          setStreamContent(fullContent);
        } else if (event === "message_done") {
          fullContent = (data.content as string) || fullContent;
          const doneSources = normalizeSources(data.sources);
          if (doneSources.length > 0) {
            fullSources = doneSources;
            setStreamSources(doneSources);
          }
          if (typeof data.action_log_id === "string") {
            fullActionLogId = data.action_log_id;
          }
          if (typeof data.model_id === "string") {
            fullModelId = data.model_id;
          }
        } else if (event === "error") {
          fullContent = `Error: ${data.message || "Unknown error"}`;
        }
```

The `setMessages` call after the loop becomes:

```tsx
    setMessages((prev) => [
      ...prev,
      {
        role: "assistant",
        content: fullContent,
        sources: fullSources,
        action_log_id: fullActionLogId,
        model_id: fullModelId,
        action_type: fullActionType,
      },
    ]);
```

- [ ] **Step 2: Pull onInsertAIOutput from props and render button**

In the props destructuring, add `onInsertAIOutput`:

```tsx
export default function AIPanel({
  notebookId,
  pageId,
  selectedText,
  onInsertToEditor,
  onInsertAIOutput,
  onClose,
}: AIPanelProps) {
```

Find the assistant-message render block that currently shows the
"Insert to editor" button (it calls `onInsertToEditor(msg.content)`).
Immediately after that button, render another button:

```tsx
            {msg.role === "assistant" && onInsertAIOutput && msg.content && (
              <button
                type="button"
                data-testid="ai-panel-insert-ai-block"
                className="ai-panel-insert-btn ai-panel-insert-btn--block"
                onClick={() =>
                  onInsertAIOutput({
                    content_markdown: msg.content,
                    action_type: msg.action_type || "ask",
                    action_log_id: msg.action_log_id || "",
                    model_id: msg.model_id ?? null,
                    sources: (msg.sources || []).map((s) => ({
                      type: s.type,
                      id: s.id,
                      title: s.title,
                    })),
                  })
                }
              >
                Insert as AI block
              </button>
            )}
```

- [ ] **Step 3: Pass the prop through AskTab**

Open `apps/web/components/notebook/contents/ai-panel-tabs/AskTab.tsx`.
Current body:

```tsx
export default function AskTab({ notebookId, pageId }: AskTabProps) {
  const noop = useCallback(() => {}, []);

  return (
    <div style={{ height: "100%", overflow: "auto" }}>
      <AIPanel
        notebookId={notebookId}
        pageId={pageId}
        onClose={noop}
      />
    </div>
  );
}
```

Replace with:

```tsx
export default function AskTab({ notebookId, pageId }: AskTabProps) {
  const noop = useCallback(() => {}, []);

  const handleInsertAIBlock = useCallback(
    (payload: {
      content_markdown: string;
      action_type: string;
      action_log_id: string;
      model_id: string | null;
      sources: Array<{ type: string; id: string; title: string }>;
    }) => {
      if (typeof window === "undefined") return;
      window.dispatchEvent(
        new CustomEvent("mrai:insert-ai-output", { detail: payload }),
      );
    },
    [],
  );

  return (
    <div style={{ height: "100%", overflow: "auto" }}>
      <AIPanel
        notebookId={notebookId}
        pageId={pageId}
        onInsertAIOutput={handleInsertAIBlock}
        onClose={noop}
      />
    </div>
  );
}
```

- [ ] **Step 4: Subscribe to the event in NoteEditor**

Open `apps/web/components/console/editor/NoteEditor.tsx`. Add a new
`useEffect` alongside the other effects:

```tsx
  useEffect(() => {
    if (!editor) return;
    function handler(e: Event) {
      const payload = (e as CustomEvent).detail as {
        content_markdown: string;
        action_type: string;
        action_log_id: string;
        model_id: string | null;
        sources: Array<{ type: string; id: string; title: string }>;
      } | null;
      if (!payload || !editor) return;
      editor
        .chain()
        .focus()
        .insertContent({ type: "ai_output", attrs: payload })
        .run();
    }
    window.addEventListener("mrai:insert-ai-output", handler);
    return () => window.removeEventListener("mrai:insert-ai-output", handler);
  }, [editor]);
```

- [ ] **Step 5: Typecheck**

Run: `cd apps/web && pnpm tsc --noEmit 2>&1 | grep -iE "(AIPanel|AskTab|NoteEditor)" | head -20`
Expected: no errors from these files.

- [ ] **Step 6: Commit**

```bash
git add apps/web/components/console/editor/AIPanel.tsx apps/web/components/notebook/contents/ai-panel-tabs/AskTab.tsx apps/web/components/console/editor/NoteEditor.tsx
git commit -m "feat(web): AI Panel 'Insert as AI block' → ai_output TipTap node"
```

---

### Task 13: Block CSS

**Files:**
- Modify: `apps/web/styles/note-editor.css`

- [ ] **Step 1: Append block styles**

Open `apps/web/styles/note-editor.css` and append:

```css
/* S2 new blocks ----------------------------------------------------------- */

.file-block,
.ai-output-block,
.reference-block,
.task-block,
.flashcard-block {
  border: 1px solid rgba(15, 23, 42, 0.1);
  border-radius: 8px;
  padding: 10px 12px;
  margin: 8px 0;
  background: rgba(249, 250, 251, 0.6);
}

.file-block__picker,
.file-block__open,
.file-block__download {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 6px;
  border: 1px solid rgba(15, 23, 42, 0.12);
  background: #fff;
  color: #1a1a2e;
  font-size: 12px;
  cursor: pointer;
}
.file-block__meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}
.file-block__size {
  color: #6b7280;
  font-size: 11px;
}
.file-block__preview {
  max-width: 100%;
  margin-top: 8px;
  border-radius: 6px;
}
.file-block__error {
  color: #b91c1c;
  font-size: 12px;
  margin-top: 6px;
}

.ai-output-block__header {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: #6b7280;
  margin-bottom: 6px;
}
.ai-output-block__badge {
  font-weight: 600;
}
.ai-output-block__trace-btn {
  margin-left: auto;
  background: none;
  border: 1px solid rgba(15, 23, 42, 0.12);
  border-radius: 4px;
  padding: 2px 8px;
  font-size: 11px;
  cursor: pointer;
  color: #2563eb;
}
.ai-output-block__body p {
  margin: 0 0 6px;
  font-size: 13px;
  line-height: 1.55;
}
.ai-output-block__empty {
  color: #9ca3af;
  font-style: italic;
}
.ai-output-block__sources {
  margin-top: 8px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.ai-output-block__source {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  background: rgba(37, 99, 235, 0.08);
  color: #2563eb;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.reference-block {
  padding: 0;
}
.reference-block__card {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  text-align: left;
  padding: 10px 12px;
  background: transparent;
  border: none;
  cursor: pointer;
  color: inherit;
}
.reference-block__content {
  flex: 1;
}
.reference-block__title {
  font-weight: 600;
  font-size: 13px;
}
.reference-block__snippet {
  font-size: 12px;
  color: #6b7280;
  margin-top: 2px;
}

.reference-picker {
  padding: 8px;
}
.reference-picker__tabs {
  display: flex;
  gap: 4px;
  border-bottom: 1px solid #e5e7eb;
  padding-bottom: 6px;
  margin-bottom: 6px;
}
.reference-picker__tabs button {
  padding: 4px 10px;
  font-size: 12px;
  border: none;
  background: transparent;
  color: #6b7280;
  cursor: pointer;
  border-radius: 4px;
}
.reference-picker__tabs button.is-active {
  background: rgba(37, 99, 235, 0.08);
  color: #2563eb;
  font-weight: 600;
}
.reference-picker__close {
  margin-left: auto;
  font-size: 14px;
  color: #6b7280;
  background: none;
  border: none;
  cursor: pointer;
}
.reference-picker__search {
  width: 100%;
  padding: 6px 10px;
  border: 1px solid #e5e7eb;
  border-radius: 4px;
  font-size: 12px;
  margin-bottom: 6px;
}
.reference-picker__results {
  list-style: none;
  padding: 0;
  margin: 0;
  max-height: 200px;
  overflow-y: auto;
}
.reference-picker__results li {
  border-radius: 4px;
}
.reference-picker__results button {
  display: block;
  width: 100%;
  text-align: left;
  padding: 6px 8px;
  border: none;
  background: transparent;
  cursor: pointer;
}
.reference-picker__results button:hover {
  background: rgba(37, 99, 235, 0.06);
}
.reference-picker__item-title {
  font-size: 12px;
  font-weight: 600;
  color: #111827;
}
.reference-picker__item-snippet {
  font-size: 11px;
  color: #6b7280;
  margin-top: 2px;
}
.reference-picker__empty {
  padding: 10px;
  text-align: center;
  font-size: 12px;
  color: #9ca3af;
}

.task-block__row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.task-block__title {
  flex: 1;
  border: none;
  background: transparent;
  font-size: 13px;
  outline: none;
}
.task-block__due {
  font-size: 11px;
  color: #6b7280;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.task-block__menu {
  background: none;
  border: none;
  color: #6b7280;
  cursor: pointer;
}
.task-block__expanded {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.task-block__expanded textarea,
.task-block__expanded input[type="date"] {
  padding: 6px 8px;
  border: 1px solid #e5e7eb;
  border-radius: 4px;
  font-size: 12px;
}
.task-block__error {
  color: #b91c1c;
  font-size: 11px;
  margin-top: 4px;
}

.flashcard-block__toolbar {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}
.flashcard-block__mode {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 4px;
  font-size: 11px;
  cursor: pointer;
  color: #6b7280;
}
.flashcard-block__mode.is-active {
  background: rgba(37, 99, 235, 0.08);
  border-color: rgba(37, 99, 235, 0.2);
  color: #2563eb;
  font-weight: 600;
}
.flashcard-block__editor {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.flashcard-block__editor textarea {
  padding: 8px;
  border: 1px solid #e5e7eb;
  border-radius: 4px;
  font-size: 13px;
  min-height: 60px;
}
.flashcard-block__card {
  width: 100%;
  min-height: 120px;
  padding: 16px;
  border-radius: 8px;
  background: linear-gradient(135deg, #fff 0%, #f9fafb 100%);
  border: 1px solid rgba(37, 99, 235, 0.15);
  cursor: pointer;
  text-align: left;
  transition: transform 150ms ease;
}
.flashcard-block__card:hover {
  transform: translateY(-1px);
}
.flashcard-block__card.is-flipped {
  background: linear-gradient(135deg, rgba(37, 99, 235, 0.04) 0%, rgba(37, 99, 235, 0.08) 100%);
}
.flashcard-block__hint {
  font-size: 10px;
  color: #9ca3af;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.flashcard-block__body {
  margin-top: 8px;
  font-size: 15px;
  line-height: 1.55;
}
```

- [ ] **Step 2: Commit**

```bash
git add apps/web/styles/note-editor.css
git commit -m "feat(web): CSS for the five new block types"
```

---

### Task 14: Playwright smoke for flashcard + task

**Files:**
- Create: `apps/web/tests/s2-blocks.spec.ts`

- [ ] **Step 1: Write the test**

Create `apps/web/tests/s2-blocks.spec.ts`:

```ts
import { test, expect } from "@playwright/test";

async function openNewPage(page: import("@playwright/test").Page) {
  await page.goto("/workspace/notebooks");
  await page.getByRole("button", { name: /create/i }).first().click();
  await page.waitForURL(/\/workspace\/notebooks\/[^/]+$/);
  await page.getByRole("button", { name: /create/i }).first().click();
  await expect(page.locator(".ProseMirror").first()).toBeVisible();
}

test.describe("S2 block types", () => {
  test("flashcard block flips on click", async ({ page }) => {
    await openNewPage(page);
    const editor = page.locator(".ProseMirror").first();
    await editor.click();
    await editor.type("/flashcard");
    await page.keyboard.press("Enter");

    await expect(page.getByTestId("flashcard-block")).toBeVisible();

    await page.getByTestId("flashcard-front").fill("What is X?");
    await page.getByTestId("flashcard-back").fill("X is an answer.");
    await page.getByTestId("flashcard-mode-preview").click();

    const card = page.getByTestId("flashcard-card");
    await expect(card).toContainText(/What is X/);
    await card.click();
    await expect(card).toContainText(/X is an answer/);
  });

  test("task block toggle persists across reload", async ({ page }) => {
    await openNewPage(page);
    const editor = page.locator(".ProseMirror").first();
    await editor.click();
    await editor.type("/task");
    await page.keyboard.press("Enter");

    await expect(page.getByTestId("task-block")).toBeVisible();
    // Set title via the embedded input.
    await page.locator(".task-block__title").fill("Ship S2");

    const checkbox = page.getByTestId("task-block-checkbox");
    await checkbox.check();
    await expect(checkbox).toBeChecked();

    // Trigger autosave by blurring (simulate short wait).
    await page.waitForTimeout(1500);
    await page.reload();
    await expect(page.getByTestId("task-block")).toBeVisible();
    await expect(page.getByTestId("task-block-checkbox")).toBeChecked();
  });
});
```

- [ ] **Step 2: Typecheck**

Run: `cd apps/web && pnpm tsc --noEmit tests/s2-blocks.spec.ts 2>&1 | tail -5`
Expected: no errors in this file (pre-existing errors elsewhere OK).

- [ ] **Step 3: Commit**

```bash
git add apps/web/tests/s2-blocks.spec.ts
git commit -m "test(web): Playwright smoke for flashcard flip + task persist"
```

---

### Task 15: Final verification

- [ ] **Step 1: Run unit + backend tests**

```bash
cd apps/api && .venv/bin/pytest \
  tests/test_notebook_attachment_meta.py \
  tests/test_attachment_upload.py \
  tests/test_task_complete.py -v
```
Expected: 8 passed (1 meta + 4 upload/url + 3 task).

```bash
cd apps/web && pnpm test:unit
```
Expected: 18 passed (8 window + 10 block-schemas).

- [ ] **Step 2: Typecheck full project**

```bash
cd apps/web && pnpm tsc --noEmit 2>&1 | tail -10
```
Expected: no new errors from S2 files.

- [ ] **Step 3: Report summary**

No commit here — just produce a short report listing:
- all task commits (15 of them)
- backend + unit + typecheck results
- anything unexpected

---

## Final Acceptance Checklist

- [ ] `NotebookAttachment.meta_json` column exists; migration chain is
  clean (`202604160001 → 202604170001`).
- [ ] `POST /pages/{id}/attachments/upload` stores binary, inserts
  row with `meta_json.object_key`.
- [ ] `GET /attachments/{id}/url` returns a presigned URL.
- [ ] `POST /pages/{id}/tasks/{block_id}/complete` creates an
  `AIActionLog` with `action_type="task.complete"` (or `.reopen`).
- [ ] Slash menu shows `File`, `AI Output`, `Reference`, `Task`,
  `Flashcard` entries.
- [ ] Inserting each block and saving preserves `content_json`
  round-trip.
- [ ] AI Panel's "Insert as AI block" appends an `ai_output` TipTap
  node to the currently-focused editor.
- [ ] `pnpm test:unit` passes 18 tests (8 existing + 10 new).
- [ ] Playwright `tests/s2-blocks.spec.ts` passes against a real
  stack (flashcard flip + task reload).

## Cross-references

- Spec: `docs/superpowers/specs/2026-04-16-block-types-additions-design.md`
- Original product spec: `MRAI_notebook_ai_os_build_spec.md` §5.1.3
