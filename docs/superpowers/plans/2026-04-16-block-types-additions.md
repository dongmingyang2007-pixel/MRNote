# S2 — 块类型补全 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 TipTap 编辑器里补齐 spec §5.1.3 剩余的 5 个块类型（file / ai_output / reference / task / flashcard），为 file/task 提供支撑的 3 个后端端点与一次 `NotebookAttachment.meta_json` 迁移，不动既有 14 个块。

**Architecture:**
- 前端：5 个 TipTap Node 扩展，每个 `.tsx` 一个文件（NodeView 内联）。Slash 菜单追加 5 条。`NoteEditor` 接收新的 `notebookId` prop 并把它作为扩展选项传给 `ReferenceBlock`。
- 后端：新建 `routers/attachments.py`（顶层 `/api/v1/attachments`）放单个 `GET /{id}/url`；上传和任务完成两个 POST 挂在已有的 `pages_router`（`/api/v1/pages`）。所有 3 个写端点复用 S1 的 `action_log_context`。
- 存储：新 MinIO bucket `notebook-attachments`，在 `main.py` 的 lifespan 用已有的 HEAD-then-CREATE 模式预建；附件的 `object_key` 存进 `NotebookAttachment.meta_json`（新列，Alembic 迁移加）。

**Tech Stack:** FastAPI · SQLAlchemy · Alembic · MinIO/boto3 · TipTap (React) · lucide-react · Vitest · Pytest · Playwright.

---

## 规范修正（仅此一处重要偏差）

Spec §4.3 Reference 块引用了三条前端搜索端点，实际代码路径与之不完全一致。下表是 plan 采用的真实路径，不要按 spec 的字面照抄。

| 用途 | Spec 写法 | 实际路径 | 调用方式 |
|---|---|---|---|
| 页面标题搜索 | `GET /api/v1/pages/search?q=&notebook_id=` | **一致** | `GET`，query string |
| Memory 搜索 | `GET /api/v1/memory/search?q=&project_id=&limit=` | `POST /api/v1/memory/search` | **POST**，body `{project_id, query, top_k}` |
| Notebook 下的学习资产列表 | `GET /api/v1/notebooks/{id}/study-assets` | `GET /api/v1/notebooks/{id}/study` | query 无需额外参数 |
| 资产分块浏览 | `GET /api/v1/study-assets/{id}/chunks?q=` | `GET /api/v1/notebooks/{nb}/study/{asset}/chunks` | query string |
| Notebook 详情（为取 project_id） | `GET /api/v1/notebooks/{id}` | **一致** | 返回 `NotebookOut`，含 `project_id` |

`ReferencePickerDialog` 需要同时接 `notebookId` 与通过 `GET /api/v1/notebooks/{id}` 解析出的 `project_id`。S2 继续采用 spec 推荐的"每次模态挂载解析一次"策略，不缓存。

---

## 文件结构

### 新建文件

| 路径 | 责任 |
|---|---|
| `apps/api/app/routers/attachments.py` | 单端点路由：`GET /api/v1/attachments/{id}/url` |
| `apps/api/alembic/versions/202604170001_notebook_attachment_meta.py` | 给 `notebook_attachments` 加 `meta_json` 列 |
| `apps/api/tests/test_attachment_upload.py` | 上传 + URL 端点 API 测试 |
| `apps/api/tests/test_task_complete.py` | 任务完成端点 API 测试 |
| `apps/web/components/console/editor/ai-output-types.ts` | 共享类型 `AIOutputInsertPayload`（NoteEditor + AIPanel 都用） |
| `apps/web/components/console/editor/active-editor-registry.ts` | 模块级 active-editor store（跨窗口调用用） |
| `apps/web/components/console/editor/extensions/FileBlock.tsx` | `file` 块 |
| `apps/web/components/console/editor/extensions/AIOutputBlock.tsx` | `ai_output` 块 |
| `apps/web/components/console/editor/extensions/ReferenceBlock.tsx` | `reference` 块 + 内部 `ReferencePickerDialog` 组件 |
| `apps/web/components/console/editor/extensions/TaskBlock.tsx` | `task` 块 |
| `apps/web/components/console/editor/extensions/FlashcardBlock.tsx` | `flashcard` 块 |
| `apps/web/tests/unit/block-schemas.test.ts` | 5 个块的序列化 round-trip 测试（10 cases） |
| `apps/web/tests/s2-blocks.spec.ts` | Playwright 冒烟：flashcard 翻转 + task 勾选 |

### 修改文件

| 路径 | 修改内容 |
|---|---|
| `apps/api/app/models/entities.py` | `NotebookAttachment` 加 `meta_json` 列 |
| `apps/api/app/routers/notebooks.py` | 追加 `upload_page_attachment` 与 `complete_task` 两个端点 |
| `apps/api/app/main.py` | 挂 `attachments.router` + lifespan 预建新 bucket |
| `apps/api/app/core/config.py` | 加 `s3_notebook_attachments_bucket` 与 `notebook_attachment_max_bytes` |
| `apps/web/components/console/editor/extensions/index.ts` | 追加 5 个 re-export |
| `apps/web/components/console/editor/NoteEditor.tsx` | 引入新扩展 + 新增 `notebookId` prop + 向 active-editor registry 注册 |
| `apps/web/components/console/editor/SlashCommandMenu.tsx` | `COMMANDS` 追加 5 条 + 新图标 import |
| `apps/web/components/console/editor/AIPanel.tsx` | 加 "Insert as AI block" 按钮，按钮调用 registry lookup（无 prop drilling） |
| `apps/web/styles/note-editor.css` | 新增五段样式 |
| `apps/web/messages/en/console-notebooks.json` + `zh/console-notebooks.json` | Slash 菜单/按钮文案 |

---

## Phase A — 后端配置与迁移

### Task 1: 配置两项 settings

**Files:**
- Modify: `apps/api/app/core/config.py`

- [ ] **Step 1: 把两项新字段加到 `Settings` 里**

紧挨着现有 `s3_ai_action_payloads_bucket` 那一行之后插入：

```python
    s3_notebook_attachments_bucket: str = "notebook-attachments"
    notebook_attachment_max_bytes: int = 50 * 1024 * 1024
```

（`Settings` 读 env 走 pydantic-settings 自动机制，无需额外代码。）

- [ ] **Step 2: 跑一次 `Settings()` 确认可实例化**

运行：

```bash
cd /Users/dog/Desktop/MRAI/apps/api
uv run python -c "from app.core.config import settings; print(settings.s3_notebook_attachments_bucket, settings.notebook_attachment_max_bytes)"
```

Expected: 输出 `notebook-attachments 52428800`

- [ ] **Step 3: Commit**

```bash
git add apps/api/app/core/config.py
git commit -m "feat(api): add notebook attachment settings (S2)"
```

---

### Task 2: 给 `NotebookAttachment` 加 `meta_json` ORM 字段

**Files:**
- Modify: `apps/api/app/models/entities.py`

- [ ] **Step 1: 定位到 `NotebookAttachment` 类**

用 grep 找行号：

```bash
grep -n "class NotebookAttachment" apps/api/app/models/entities.py
```

- [ ] **Step 2: 在 `title` 列下面追加 `meta_json` 列**

最终类体：

```python
class NotebookAttachment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "notebook_attachments"

    page_id: Mapped[str] = mapped_column(ForeignKey("notebook_pages.id", ondelete="CASCADE"), index=True)
    data_item_id: Mapped[str | None] = mapped_column(ForeignKey("data_items.id", ondelete="SET NULL"), nullable=True)
    attachment_type: Mapped[str] = mapped_column(String(20), default="other", nullable=False)
    title: Mapped[str] = mapped_column(Text, default="", nullable=False)
    meta_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
```

确认文件顶部已 import：
- `from typing import Any`
- `from sqlalchemy import JSON`（或 `from sqlalchemy.types import JSON`，按现有文件风格保持一致）

若这些导入不存在就补上。

- [ ] **Step 3: 语法验证**

```bash
cd /Users/dog/Desktop/MRAI/apps/api
uv run python -c "from app.models.entities import NotebookAttachment; print(NotebookAttachment.__table__.columns.keys())"
```

Expected: 输出里含 `meta_json`

- [ ] **Step 4: Commit**

```bash
git add apps/api/app/models/entities.py
git commit -m "feat(api): add meta_json to NotebookAttachment ORM (S2)"
```

---

### Task 3: Alembic 迁移：`notebook_attachments.meta_json`

**Files:**
- Create: `apps/api/alembic/versions/202604170001_notebook_attachment_meta.py`

- [ ] **Step 1: 确认最新 head 是 `202604160001`**

```bash
cd /Users/dog/Desktop/MRAI/apps/api
ls apps/api/alembic/versions | sort | tail -3
```

Expected: 见到 `202604160001_ai_action_log.py` 在最后。

- [ ] **Step 2: 写迁移文件**

```python
"""notebook_attachment_meta_json

Revision ID: 202604170001
Revises: 202604160001
Create Date: 2026-04-16
"""

from __future__ import annotations

from alembic import op


revision = "202604170001"
down_revision = "202604160001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE notebook_attachments
          ADD COLUMN IF NOT EXISTS meta_json JSONB NOT NULL DEFAULT '{}'::jsonb;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE notebook_attachments
          DROP COLUMN IF EXISTS meta_json;
        """
    )
```

说明：SQLite 测试路径不跑 Alembic，它是 `Base.metadata.create_all`，ORM 改动已让 SQLite 自动建列。

- [ ] **Step 3: （可选）在 Postgres 环境里过一次 upgrade/downgrade**

若本地装了 Postgres dev DB，运行：

```bash
cd /Users/dog/Desktop/MRAI/apps/api
uv run alembic upgrade head
uv run alembic downgrade -1
uv run alembic upgrade head
```

Expected: 三条命令都没报错。没本地 Postgres 就跳过，CI 会覆盖。

- [ ] **Step 4: Commit**

```bash
git add apps/api/alembic/versions/202604170001_notebook_attachment_meta.py
git commit -m "feat(api): migrate notebook_attachments.meta_json (S2)"
```

---

### Task 4: Lifespan 预建附件 bucket

**Files:**
- Modify: `apps/api/app/main.py`

- [ ] **Step 1: 找到现有 `ai-action-payloads` bucket 预建代码**

```bash
grep -n "s3_ai_action_payloads_bucket" apps/api/app/main.py
```

定位到 lifespan 块里 HEAD-then-CREATE 的那一段。

- [ ] **Step 2: 紧跟其后加一段同构代码，换成新 bucket**

最终 lifespan 片段（紧接现有 `ai-action-payloads` 那个 try 块之后）：

```python
    # S2: Ensure notebook-attachments bucket exists
    try:
        from app.services import storage as _storage_service  # noqa: F401,E501 (already imported above)
        from botocore.exceptions import ClientError as _ClientError  # noqa: F401

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

如果 `_storage_service` / `_ClientError` 在上一段已经局部导入且仍在作用域内，可以直接复用，不必重复 import。务必和现有风格一致。

- [ ] **Step 3: 冒烟：启动 API，确认 lifespan 不报错**

```bash
cd /Users/dog/Desktop/MRAI/apps/api
uv run python -c "from app.main import app; print('ok')"
```

Expected: 打印 `ok`，没有异常。真实 bucket 创建要到服务启动时才会触发，这里只是确保 import 路径正确。

- [ ] **Step 4: Commit**

```bash
git add apps/api/app/main.py
git commit -m "feat(api): ensure notebook-attachments bucket on startup (S2)"
```

---

## Phase B — 后端三个端点（TDD）

### Task 5: `POST /pages/{page_id}/attachments/upload` 端点

**Files:**
- Create: `apps/api/tests/test_attachment_upload.py`
- Modify: `apps/api/app/routers/notebooks.py`

- [ ] **Step 1: 写 4 个失败的 API 测试**

新建 `apps/api/tests/test_attachment_upload.py`。参照 `apps/api/tests/test_notebook_ai_logging.py` 的 bootstrap 模式（自包含 SQLite、`_register_user`、`_finalize_client_auth`、inline 装饰一个 `TestClient`）。若测试环境已用 MinIO，走真实路径；若无，就用 `unittest.mock.patch` 把 `storage.get_s3_client()` 和 `get_s3_presign_client()` 都替掉。

完整测试文件（可直接写入）：

```python
"""API tests: POST /api/v1/pages/{page_id}/attachments/upload (S2)."""

from __future__ import annotations

import io
import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# Reuse bootstrap helpers from notebook_ai_logging tests. This project has no
# conftest; each test file wires its own client.
from tests.test_notebook_ai_logging import (  # type: ignore
    _register_user,
    _finalize_client_auth,
    _public_headers,
    _seed_fixture,
)
from app.main import app
from app.models import NotebookAttachment
from app.core.deps import get_db_session


def _client() -> TestClient:
    return TestClient(app)


class _FakeS3:
    def __init__(self) -> None:
        self.puts: list[dict] = []

    def put_object(self, **kwargs):
        self.puts.append(kwargs)
        return {"ETag": "fake"}

    def head_bucket(self, **_):
        return {}

    def create_bucket(self, **_):
        return {}


class _FakePresign:
    def generate_presigned_url(self, op_name, Params, ExpiresIn):  # noqa: N803
        return f"https://fake/{Params['Bucket']}/{Params['Key']}?expires={ExpiresIn}"


@pytest.fixture
def s3_stubs():
    fake_s3 = _FakeS3()
    fake_presign = _FakePresign()
    with patch("app.services.storage.get_s3_client", return_value=fake_s3), \
         patch("app.services.storage.get_s3_presign_client", return_value=fake_presign):
        yield fake_s3, fake_presign


def test_upload_small_image_returns_attachment(s3_stubs):
    client = _client()
    ctx = _seed_fixture(client)
    _finalize_client_auth(client, ctx["ws_id"])

    page_id = ctx["page_id"]
    payload = b"\x89PNG\r\n\x1a\nfake-image-bytes"
    resp = client.post(
        f"/api/v1/pages/{page_id}/attachments/upload",
        files={"file": ("cover.png", io.BytesIO(payload), "image/png")},
        data={"title": "Cover"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["filename"] == "cover.png"
    assert body["mime_type"] == "image/png"
    assert body["size_bytes"] == len(payload)
    assert body["attachment_type"] == "image"
    attachment_id = body["attachment_id"]

    gen = get_db_session()
    db = next(gen)
    try:
        row = db.query(NotebookAttachment).filter_by(id=attachment_id).one()
        assert "object_key" in row.meta_json
        assert row.meta_json["object_key"].endswith("cover.png")
    finally:
        try:
            next(gen)
        except StopIteration:
            pass


def test_upload_exceeds_size_limit(s3_stubs, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.notebook_attachment_max_bytes", 16
    )
    client = _client()
    ctx = _seed_fixture(client, email="u2@x.co")
    _finalize_client_auth(client, ctx["ws_id"])
    page_id = ctx["page_id"]

    big = b"a" * 32
    resp = client.post(
        f"/api/v1/pages/{page_id}/attachments/upload",
        files={"file": ("big.bin", io.BytesIO(big), "application/octet-stream")},
    )
    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == "file_too_large"


def test_upload_cross_workspace_returns_404(s3_stubs):
    client = _client()
    ctx_a = _seed_fixture(client, email="a@x.co")
    ctx_b = _seed_fixture(client, email="b@x.co")
    _finalize_client_auth(client, ctx_b["ws_id"])  # auth as B

    resp = client.post(
        f"/api/v1/pages/{ctx_a['page_id']}/attachments/upload",
        files={"file": ("x.txt", io.BytesIO(b"hi"), "text/plain")},
    )
    assert resp.status_code == 404


def test_get_attachment_url_returns_presigned(s3_stubs):
    client = _client()
    ctx = _seed_fixture(client, email="c@x.co")
    _finalize_client_auth(client, ctx["ws_id"])

    upload = client.post(
        f"/api/v1/pages/{ctx['page_id']}/attachments/upload",
        files={"file": ("doc.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
    )
    assert upload.status_code == 200
    att_id = upload.json()["attachment_id"]

    resp = client.get(f"/api/v1/attachments/{att_id}/url")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["expires_in_seconds"] == 900
    assert "notebook-attachments" in body["url"]
```

说明：`_seed_fixture` 与 `_finalize_client_auth` 已在 `test_notebook_ai_logging.py` 里定义——若从那里直接 import 不通（比如没有 `__init__.py`），把那两函数复制到本文件顶部即可；保持内容一致。

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /Users/dog/Desktop/MRAI/apps/api
uv run pytest tests/test_attachment_upload.py -v
```

Expected: 4 个测试全部失败（路由未注册，404/405 之类）。

- [ ] **Step 3: 在 `routers/notebooks.py` 添加 `_classify` 辅助 + upload 端点**

先在文件顶部 import 区（靠近现有 `from fastapi import ...`）确认含：

```python
from fastapi import APIRouter, Depends, File, Form, UploadFile
```

然后在合适位置（`pages_router` 的其它端点附近，`update_page` 下面即可）插入：

```python
def _classify_attachment(content_type: str | None) -> str:
    if not content_type:
        return "other"
    if content_type.startswith("image/"):
        return "image"
    if content_type == "application/pdf":
        return "pdf"
    if content_type.startswith("audio/"):
        return "audio"
    if content_type.startswith("video/"):
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
    page = _get_page_or_404(db, page_id, workspace_id)
    data = await file.read()
    if len(data) > settings.notebook_attachment_max_bytes:
        raise ApiError(
            "file_too_large",
            f"File exceeds {settings.notebook_attachment_max_bytes} bytes",
            status_code=413,
        )

    from uuid import uuid4
    from app.services.storage import (
        get_s3_client,
        sanitize_filename,
    )

    safe_name = sanitize_filename(file.filename or "file")
    object_key = f"{workspace_id}/{page.id}/{uuid4().hex}/{safe_name}"
    content_type = file.content_type or "application/octet-stream"

    get_s3_client().put_object(
        Bucket=settings.s3_notebook_attachments_bucket,
        Key=object_key,
        Body=data,
        ContentType=content_type,
    )

    attachment = NotebookAttachment(
        page_id=page.id,
        data_item_id=None,
        attachment_type=_classify_attachment(content_type),
        title=title or (file.filename or ""),
        meta_json={"object_key": object_key},
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)

    # S1 audit log — no LLM usage to record.
    async with action_log_context(
        db,
        workspace_id=str(workspace_id),
        user_id=str(current_user.id),
        action_type="attachment.upload",
        scope="page",
        notebook_id=str(page.notebook_id),
        page_id=str(page.id),
    ) as log:
        log.set_input({"filename": safe_name, "mime_type": content_type, "size_bytes": len(data)})
        log.set_output({"attachment_id": attachment.id})

    return {
        "attachment_id": attachment.id,
        "filename": file.filename or safe_name,
        "mime_type": content_type,
        "size_bytes": len(data),
        "attachment_type": attachment.attachment_type,
    }
```

确认文件顶部已 import：`NotebookAttachment`（来自 `app.models`）、`action_log_context`（来自 `app.services.ai_action_logger`）、`settings`（`app.core.config`）、`ApiError`（`app.core.errors`）。这些大概率都已经在用，以 grep 核查。

- [ ] **Step 4: 跑测试确认前 3 个 case 过，第 4 个（GET url）仍挂**

```bash
uv run pytest tests/test_attachment_upload.py -v
```

Expected: 前 3 个 PASS，第 4 个 FAIL（`/api/v1/attachments/{id}/url` 未注册）。

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/routers/notebooks.py apps/api/tests/test_attachment_upload.py
git commit -m "feat(api): POST /pages/{id}/attachments/upload (S2)"
```

---

### Task 6: `GET /attachments/{id}/url` 端点 + 新路由文件

**Files:**
- Create: `apps/api/app/routers/attachments.py`
- Modify: `apps/api/app/main.py`

- [ ] **Step 1: 新建 `attachments.py` 路由**

内容：

```python
"""Top-level attachment URL resolver (S2).

Upload lives on pages_router because it's page-scoped; this GET lives here
because clients only know the attachment id.
"""

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
from app.services.storage import get_s3_presign_client


router = APIRouter(prefix="/api/v1/attachments", tags=["attachments"])


@router.get("/{attachment_id}/url")
def get_attachment_url(
    attachment_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
) -> dict[str, Any]:
    _ = current_user
    attachment = (
        db.query(NotebookAttachment).filter_by(id=attachment_id).first()
    )
    if not attachment:
        raise ApiError("not_found", "Attachment not found", status_code=404)
    page = db.query(NotebookPage).filter_by(id=attachment.page_id).first()
    if not page:
        raise ApiError("not_found", "Attachment not found", status_code=404)
    notebook = (
        db.query(Notebook)
        .filter(Notebook.id == page.notebook_id, Notebook.workspace_id == workspace_id)
        .first()
    )
    if not notebook:
        raise ApiError("not_found", "Attachment not found", status_code=404)

    object_key = (attachment.meta_json or {}).get("object_key")
    if not object_key:
        raise ApiError("not_found", "Attachment object_key missing", status_code=404)

    url = get_s3_presign_client().generate_presigned_url(
        "get_object",
        Params={
            "Bucket": settings.s3_notebook_attachments_bucket,
            "Key": object_key,
        },
        ExpiresIn=settings.s3_presign_expire_seconds,
    )
    return {
        "url": url,
        "expires_in_seconds": settings.s3_presign_expire_seconds,
    }
```

- [ ] **Step 2: 在 `main.py` 里挂路由**

找到既有 `app.include_router(notebooks.pages_router)`，在其后追加：

```python
from app.routers import attachments  # at top with other router imports
...
app.include_router(attachments.router)
```

确认 top-of-file 的路由 import 行已经包含 `attachments` 模块（和其他路由并列写）。

- [ ] **Step 3: 跑测试确认 4 个全过**

```bash
cd /Users/dog/Desktop/MRAI/apps/api
uv run pytest tests/test_attachment_upload.py -v
```

Expected: 4 PASS。

- [ ] **Step 4: Commit**

```bash
git add apps/api/app/routers/attachments.py apps/api/app/main.py
git commit -m "feat(api): GET /attachments/{id}/url (S2)"
```

---

### Task 7: `POST /pages/{page_id}/tasks/{block_id}/complete` 端点

**Files:**
- Create: `apps/api/tests/test_task_complete.py`
- Modify: `apps/api/app/routers/notebooks.py`

- [ ] **Step 1: 写 3 个失败 API 测试**

新建 `apps/api/tests/test_task_complete.py`：

```python
"""API tests: POST /api/v1/pages/{page_id}/tasks/{block_id}/complete (S2)."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from tests.test_notebook_ai_logging import (  # type: ignore
    _register_user,
    _finalize_client_auth,
    _seed_fixture,
)
from app.main import app
from app.models import AIActionLog
from app.core.deps import get_db_session


def _client() -> TestClient:
    return TestClient(app)


def _action_logs_for(page_id: str) -> list[AIActionLog]:
    gen = get_db_session()
    db = next(gen)
    try:
        return db.query(AIActionLog).filter_by(page_id=page_id).all()
    finally:
        try:
            next(gen)
        except StopIteration:
            pass


def test_task_complete_writes_action_log():
    client = _client()
    ctx = _seed_fixture(client, email="t1@x.co")
    _finalize_client_auth(client, ctx["ws_id"])

    block_id = str(uuid.uuid4())
    resp = client.post(
        f"/api/v1/pages/{ctx['page_id']}/tasks/{block_id}/complete",
        json={"completed": True, "completed_at": "2026-04-16T12:00:00Z"},
    )
    assert resp.status_code == 200, resp.text
    logs = [l for l in _action_logs_for(ctx["page_id"]) if l.action_type == "task.complete"]
    assert len(logs) == 1
    assert logs[0].block_id == block_id


def test_task_reopen_uses_different_action_type():
    client = _client()
    ctx = _seed_fixture(client, email="t2@x.co")
    _finalize_client_auth(client, ctx["ws_id"])

    block_id = str(uuid.uuid4())
    resp = client.post(
        f"/api/v1/pages/{ctx['page_id']}/tasks/{block_id}/complete",
        json={"completed": False},
    )
    assert resp.status_code == 200
    logs = [l for l in _action_logs_for(ctx["page_id"]) if l.action_type == "task.reopen"]
    assert len(logs) == 1


def test_task_complete_cross_workspace_returns_404():
    client = _client()
    ctx_a = _seed_fixture(client, email="a@x.co")
    ctx_b = _seed_fixture(client, email="b@x.co")
    _finalize_client_auth(client, ctx_b["ws_id"])

    block_id = str(uuid.uuid4())
    resp = client.post(
        f"/api/v1/pages/{ctx_a['page_id']}/tasks/{block_id}/complete",
        json={"completed": True},
    )
    assert resp.status_code == 404
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /Users/dog/Desktop/MRAI/apps/api
uv run pytest tests/test_task_complete.py -v
```

Expected: 3 FAIL（404/405/实现不存在）。

- [ ] **Step 3: 在 `routers/notebooks.py` 添加 `complete_task` 端点**

插入位置：紧跟 Task 5 写好的 `upload_page_attachment` 之后。

```python
@pages_router.post("/{page_id}/tasks/{block_id}/complete")
async def complete_task(
    page_id: str,
    block_id: str,
    payload: dict[str, Any],
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf: None = Depends(require_csrf_protection),
) -> dict[str, Any]:
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

- [ ] **Step 4: 跑测试确认过**

```bash
uv run pytest tests/test_task_complete.py -v
```

Expected: 3 PASS。

- [ ] **Step 5: 跑整个 S2 后端 suite 保通**

```bash
uv run pytest tests/test_attachment_upload.py tests/test_task_complete.py tests/test_notebook_ai_logging.py -v
```

Expected: 全 PASS。

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/routers/notebooks.py apps/api/tests/test_task_complete.py
git commit -m "feat(api): POST /pages/{id}/tasks/{block}/complete (S2)"
```

---

## Phase C — 前端 TipTap 扩展（纯前端块在先）

所有扩展都遵循同一模板：

- 顶部 imports：
  ```ts
  import { Node, mergeAttributes } from "@tiptap/core";
  import { NodeViewWrapper, ReactNodeViewRenderer, type NodeViewProps } from "@tiptap/react";
  import React from "react";
  ```
- `Node.create({ name, group: "block", atom/selectable/draggable 按需, addAttributes, parseHTML, renderHTML, addNodeView })`。
- `parseHTML` 通过 `tag: 'div[data-type="<name>"]'` 匹配；`renderHTML` 用 `mergeAttributes(HTMLAttributes, { "data-type": "<name>" })` 并在需要时加 `class`。
- NodeView 函数接 `{ node, updateAttributes, selected, extension }: NodeViewProps`，从 `node.attrs` 读数据。

测试集中在 `apps/web/tests/unit/block-schemas.test.ts`。所有 5 个扩展共用同一测试文件，每个扩展 2 个 case：
1. `editor.chain().insertContent({ type: "<name>", attrs: ... }).run()` 后 `editor.getJSON()` 含期望 attrs。
2. 取第一步得到的 JSON，用另一个 editor 实例 `setContent(json)`，再 `getJSON()`，attrs 仍一致。

测试文件骨架（先写好可被 skip 的壳，后续每个 Task 开掉对应 skip）：

```ts
import { describe, expect, it, beforeAll } from "vitest";
import { Editor } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";

import FileBlock from "../../components/console/editor/extensions/FileBlock";
import AIOutputBlock from "../../components/console/editor/extensions/AIOutputBlock";
import ReferenceBlock from "../../components/console/editor/extensions/ReferenceBlock";
import TaskBlock from "../../components/console/editor/extensions/TaskBlock";
import FlashcardBlock from "../../components/console/editor/extensions/FlashcardBlock";

function makeEditor(extensions: any[]) {
  return new Editor({
    extensions: [StarterKit, ...extensions],
    content: "",
  });
}

function roundTrip(extensions: any[], payload: any) {
  const a = makeEditor(extensions);
  a.chain().focus().insertContent(payload).run();
  const json = a.getJSON();
  const b = makeEditor(extensions);
  b.commands.setContent(json);
  return b.getJSON();
}
// per-block describe blocks populated in Tasks 8-12 below.
```

---

### Task 8: FlashcardBlock（最独立：无后端、无模态）

**Files:**
- Create: `apps/web/components/console/editor/extensions/FlashcardBlock.tsx`
- Modify: `apps/web/tests/unit/block-schemas.test.ts`

- [ ] **Step 1: 追加失败测试到 `block-schemas.test.ts`**

（若该文件不存在，先写入上面 Phase C 里的骨架）：

```ts
describe("FlashcardBlock", () => {
  it("default insertion carries front/back/flipped attrs", () => {
    const e = makeEditor([FlashcardBlock]);
    e.chain().focus().insertContent({
      type: "flashcard",
      attrs: { front: "Q?", back: "A.", flipped: false },
    }).run();
    const doc = e.getJSON();
    const node = doc.content?.find((n: any) => n.type === "flashcard");
    expect(node?.attrs).toEqual({ front: "Q?", back: "A.", flipped: false });
  });

  it("round-trips front/back/flipped through setContent", () => {
    const json = roundTrip([FlashcardBlock], {
      type: "flashcard",
      attrs: { front: "Q?", back: "A.", flipped: true },
    });
    const node = json.content?.find((n: any) => n.type === "flashcard");
    expect(node?.attrs).toEqual({ front: "Q?", back: "A.", flipped: true });
  });
});
```

- [ ] **Step 2: 跑 vitest 确认失败**

```bash
cd /Users/dog/Desktop/MRAI/apps/web
npm run test:unit -- block-schemas
```

Expected: FAIL（FlashcardBlock 未定义）。

- [ ] **Step 3: 实现 FlashcardBlock.tsx**

```tsx
import { Node, mergeAttributes } from "@tiptap/core";
import { NodeViewWrapper, ReactNodeViewRenderer, type NodeViewProps } from "@tiptap/react";
import React, { useCallback, useState } from "react";

const FlashcardBlock = Node.create({
  name: "flashcard",
  group: "block",
  atom: true,
  selectable: true,
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
    return [
      "div",
      mergeAttributes(HTMLAttributes, {
        "data-type": "flashcard",
        class: "flashcard-block",
      }),
    ];
  },

  addNodeView() {
    return ReactNodeViewRenderer(FlashcardBlockView);
  },
});

function FlashcardBlockView({ node, updateAttributes, selected }: NodeViewProps) {
  const [editing, setEditing] = useState<boolean>(!node.attrs.front && !node.attrs.back);

  const toggleFlip = useCallback(() => {
    if (editing) return;
    updateAttributes({ flipped: !node.attrs.flipped });
  }, [editing, node.attrs.flipped, updateAttributes]);

  return (
    <NodeViewWrapper
      data-type="flashcard"
      data-selected={selected ? "true" : undefined}
      className="flashcard-block"
    >
      {editing ? (
        <div className="flashcard-edit">
          <textarea
            value={node.attrs.front}
            onChange={(e) => updateAttributes({ front: e.target.value })}
            placeholder="Front"
            aria-label="Flashcard front"
          />
          <textarea
            value={node.attrs.back}
            onChange={(e) => updateAttributes({ back: e.target.value })}
            placeholder="Back"
            aria-label="Flashcard back"
          />
          <button type="button" onClick={() => setEditing(false)}>Preview</button>
        </div>
      ) : (
        <button
          type="button"
          className="flashcard-preview"
          onClick={toggleFlip}
          onDoubleClick={() => setEditing(true)}
          aria-label={node.attrs.flipped ? "Flashcard, back side" : "Flashcard, front side"}
        >
          {node.attrs.flipped ? node.attrs.back || "(back)" : node.attrs.front || "(front)"}
        </button>
      )}
    </NodeViewWrapper>
  );
}

export default FlashcardBlock;
```

- [ ] **Step 4: 跑 vitest 确认过**

```bash
npm run test:unit -- block-schemas
```

Expected: FlashcardBlock 两个 case PASS。

- [ ] **Step 5: Commit**

```bash
git add apps/web/components/console/editor/extensions/FlashcardBlock.tsx apps/web/tests/unit/block-schemas.test.ts
git commit -m "feat(web): FlashcardBlock TipTap extension (S2)"
```

---

### Task 9: AIOutputBlock（纯前端渲染 + 事件派发）

**Files:**
- Create: `apps/web/components/console/editor/extensions/AIOutputBlock.tsx`
- Modify: `apps/web/tests/unit/block-schemas.test.ts`

- [ ] **Step 1: 追加失败测试**

```ts
describe("AIOutputBlock", () => {
  const attrs = {
    content_markdown: "# Hello",
    action_type: "selection.rewrite",
    action_log_id: "log_123",
    model_id: "qwen-plus",
    sources: [{ type: "memory", id: "m1", title: "Note" }],
  };

  it("default insertion preserves all AI attrs", () => {
    const e = makeEditor([AIOutputBlock]);
    e.chain().focus().insertContent({ type: "ai_output", attrs }).run();
    const node = e.getJSON().content?.find((n: any) => n.type === "ai_output");
    expect(node?.attrs).toEqual(attrs);
  });

  it("round-trips sources[] through setContent", () => {
    const json = roundTrip([AIOutputBlock], { type: "ai_output", attrs });
    const node = json.content?.find((n: any) => n.type === "ai_output");
    expect(node?.attrs.sources).toEqual(attrs.sources);
    expect(node?.attrs.action_log_id).toBe("log_123");
  });
});
```

```bash
npm run test:unit -- block-schemas
```

Expected: 新增 2 FAIL。

- [ ] **Step 2: 实现 `AIOutputBlock.tsx`**

```tsx
import { Node, mergeAttributes } from "@tiptap/core";
import { NodeViewWrapper, ReactNodeViewRenderer, type NodeViewProps } from "@tiptap/react";
import React from "react";
import ReactMarkdown from "react-markdown";

type Source = { type: string; id: string; title: string };

const AIOutputBlock = Node.create({
  name: "ai_output",
  group: "block",
  atom: true,
  selectable: true,
  draggable: true,

  addAttributes() {
    return {
      content_markdown: { default: "" },
      action_type: { default: "" },
      action_log_id: { default: "" },
      model_id: { default: null },
      sources: { default: [] as Source[] },
    };
  },

  parseHTML() {
    return [{ tag: 'div[data-type="ai_output"]' }];
  },

  renderHTML({ HTMLAttributes }) {
    return [
      "div",
      mergeAttributes(HTMLAttributes, {
        "data-type": "ai_output",
        class: "ai-output-block",
      }),
    ];
  },

  addNodeView() {
    return ReactNodeViewRenderer(AIOutputBlockView);
  },
});

function AIOutputBlockView({ node, selected }: NodeViewProps) {
  const attrs = node.attrs as {
    content_markdown: string;
    action_type: string;
    action_log_id: string;
    model_id: string | null;
    sources: Source[];
  };

  const onViewTrace = () => {
    if (!attrs.action_log_id) return;
    window.dispatchEvent(
      new CustomEvent("mrai:open-trace", { detail: { action_log_id: attrs.action_log_id } }),
    );
  };

  return (
    <NodeViewWrapper
      data-type="ai_output"
      data-selected={selected ? "true" : undefined}
      className="ai-output-block"
    >
      <div className="ai-output-header">
        {attrs.action_type && <span className="ai-output-badge">{attrs.action_type}</span>}
        {attrs.model_id && <span className="ai-output-model">{attrs.model_id}</span>}
        {attrs.action_log_id && (
          <button type="button" className="ai-output-trace" onClick={onViewTrace}>
            View trace
          </button>
        )}
      </div>
      <div className="ai-output-body">
        <ReactMarkdown>{attrs.content_markdown}</ReactMarkdown>
      </div>
      {attrs.sources?.length > 0 && (
        <ul className="ai-output-sources">
          {attrs.sources.map((s) => (
            <li key={`${s.type}:${s.id}`}>
              <span className="ai-output-source-type">{s.type}</span>
              <span className="ai-output-source-title">{s.title}</span>
            </li>
          ))}
        </ul>
      )}
    </NodeViewWrapper>
  );
}

export default AIOutputBlock;
```

说明：`react-markdown` 已是 web 包的依赖（spec §4.2 明确），无需再装。若 `import` 报错，就按 `AIPanel.tsx` 已有的用法写。

- [ ] **Step 3: 跑测试确认过**

```bash
npm run test:unit -- block-schemas
```

Expected: AIOutputBlock 两个 case PASS。

- [ ] **Step 4: Commit**

```bash
git add apps/web/components/console/editor/extensions/AIOutputBlock.tsx apps/web/tests/unit/block-schemas.test.ts
git commit -m "feat(web): AIOutputBlock TipTap extension (S2)"
```

---

### Task 10: TaskBlock（需要命中后端 complete 端点）

**Files:**
- Create: `apps/web/components/console/editor/extensions/TaskBlock.tsx`
- Modify: `apps/web/tests/unit/block-schemas.test.ts`

- [ ] **Step 1: 追加失败测试**

```ts
describe("TaskBlock", () => {
  const attrs = {
    block_id: "bk-1111",
    title: "Write plan",
    description: null,
    due_date: null,
    completed: false,
    completed_at: null,
  };

  it("default insertion preserves task attrs", () => {
    const e = makeEditor([TaskBlock]);
    e.chain().focus().insertContent({ type: "task", attrs }).run();
    const node = e.getJSON().content?.find((n: any) => n.type === "task");
    expect(node?.attrs.block_id).toBe("bk-1111");
    expect(node?.attrs.completed).toBe(false);
  });

  it("round-trips completed/completed_at through setContent", () => {
    const json = roundTrip([TaskBlock], {
      type: "task",
      attrs: { ...attrs, completed: true, completed_at: "2026-04-16T12:00:00Z" },
    });
    const node = json.content?.find((n: any) => n.type === "task");
    expect(node?.attrs.completed).toBe(true);
    expect(node?.attrs.completed_at).toBe("2026-04-16T12:00:00Z");
  });
});
```

```bash
npm run test:unit -- block-schemas
```

Expected: 2 FAIL。

- [ ] **Step 2: 实现 `TaskBlock.tsx`**

`pageId` 通过扩展 options 由 NoteEditor 注入（Task 15 里 wire 进来；暂时让 NodeView 从 `extension.options.pageId` 读，缺时按 null 处理并把失败以 toast 形式吞掉）。

```tsx
import { Node, mergeAttributes } from "@tiptap/core";
import { NodeViewWrapper, ReactNodeViewRenderer, type NodeViewProps } from "@tiptap/react";
import React, { useCallback, useState } from "react";

interface TaskBlockOptions {
  pageId: string;
}

const TaskBlock = Node.create<TaskBlockOptions>({
  name: "task",
  group: "block",
  atom: true,
  selectable: true,
  draggable: true,

  addOptions() {
    return { pageId: "" };
  },

  addAttributes() {
    return {
      block_id: { default: "" },
      title: { default: "" },
      description: { default: null },
      due_date: { default: null },
      completed: { default: false },
      completed_at: { default: null },
    };
  },

  parseHTML() {
    return [{ tag: 'div[data-type="task"]' }];
  },

  renderHTML({ HTMLAttributes }) {
    return [
      "div",
      mergeAttributes(HTMLAttributes, {
        "data-type": "task",
        class: "task-block",
      }),
    ];
  },

  addNodeView() {
    return ReactNodeViewRenderer(TaskBlockView);
  },
});

function TaskBlockView({ node, updateAttributes, selected, extension }: NodeViewProps) {
  const [error, setError] = useState<string | null>(null);
  const pageId = (extension.options as TaskBlockOptions).pageId;

  const toggle = useCallback(async () => {
    const next = !node.attrs.completed;
    const prev = node.attrs.completed;
    updateAttributes({
      completed: next,
      completed_at: next ? new Date().toISOString() : null,
    });
    setError(null);
    if (!pageId || !node.attrs.block_id) return;
    try {
      const resp = await fetch(
        `/api/v1/pages/${pageId}/tasks/${node.attrs.block_id}/complete`,
        {
          method: "POST",
          credentials: "include",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            completed: next,
            completed_at: next ? new Date().toISOString() : null,
          }),
        },
      );
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    } catch (err) {
      updateAttributes({ completed: prev, completed_at: null });
      setError("Couldn't save task state");
    }
  }, [node.attrs.completed, node.attrs.block_id, pageId, updateAttributes]);

  return (
    <NodeViewWrapper
      data-type="task"
      data-selected={selected ? "true" : undefined}
      className="task-block"
    >
      <label className="task-block-row">
        <input type="checkbox" checked={!!node.attrs.completed} onChange={toggle} />
        <input
          type="text"
          className="task-block-title"
          value={node.attrs.title}
          onChange={(e) => updateAttributes({ title: e.target.value })}
          placeholder="Task title"
        />
        {node.attrs.due_date && (
          <span className="task-block-due">{node.attrs.due_date}</span>
        )}
      </label>
      {error && <div className="task-block-error" role="alert">{error}</div>}
    </NodeViewWrapper>
  );
}

export default TaskBlock;
```

- [ ] **Step 3: 跑测试确认过**

```bash
npm run test:unit -- block-schemas
```

Expected: TaskBlock 2 PASS。

- [ ] **Step 4: Commit**

```bash
git add apps/web/components/console/editor/extensions/TaskBlock.tsx apps/web/tests/unit/block-schemas.test.ts
git commit -m "feat(web): TaskBlock TipTap extension (S2)"
```

---

### Task 11: FileBlock（上传 + 重新签 URL 渲染）

**Files:**
- Create: `apps/web/components/console/editor/extensions/FileBlock.tsx`
- Modify: `apps/web/tests/unit/block-schemas.test.ts`

- [ ] **Step 1: 追加失败测试（只测 schema，不测网络）**

```ts
describe("FileBlock", () => {
  const attrs = {
    attachment_id: "att_123",
    filename: "chapter1.pdf",
    mime_type: "application/pdf",
    size_bytes: 1234567,
  };

  it("default insertion carries attachment metadata", () => {
    const e = makeEditor([FileBlock]);
    e.chain().focus().insertContent({ type: "file", attrs }).run();
    const node = e.getJSON().content?.find((n: any) => n.type === "file");
    expect(node?.attrs).toEqual(attrs);
  });

  it("round-trips attachment metadata through setContent", () => {
    const json = roundTrip([FileBlock], { type: "file", attrs });
    const node = json.content?.find((n: any) => n.type === "file");
    expect(node?.attrs).toEqual(attrs);
  });
});
```

- [ ] **Step 2: 实现 `FileBlock.tsx`**

`pageId` 同 `TaskBlock`，靠扩展 options 传入：

```tsx
import { Node, mergeAttributes } from "@tiptap/core";
import { NodeViewWrapper, ReactNodeViewRenderer, type NodeViewProps } from "@tiptap/react";
import React, { useCallback, useEffect, useState } from "react";

interface FileBlockOptions {
  pageId: string;
  openWindow?: (args: { type: string; meta: Record<string, unknown> }) => void;
}

const FileBlock = Node.create<FileBlockOptions>({
  name: "file",
  group: "block",
  atom: true,
  selectable: true,
  draggable: true,

  addOptions() {
    return { pageId: "", openWindow: undefined };
  },

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
    return [
      "div",
      mergeAttributes(HTMLAttributes, {
        "data-type": "file",
        class: "file-block",
      }),
    ];
  },

  addNodeView() {
    return ReactNodeViewRenderer(FileBlockView);
  },
});

async function fetchPresignedUrl(attachmentId: string): Promise<string> {
  const resp = await fetch(`/api/v1/attachments/${attachmentId}/url`, {
    credentials: "include",
  });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  const body = await resp.json();
  return body.url as string;
}

async function uploadFile(pageId: string, file: File): Promise<{
  attachment_id: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
}> {
  const form = new FormData();
  form.append("file", file);
  form.append("title", file.name);
  const resp = await fetch(`/api/v1/pages/${pageId}/attachments/upload`, {
    method: "POST",
    credentials: "include",
    body: form,
  });
  if (!resp.ok) throw new Error(`Upload failed: HTTP ${resp.status}`);
  return resp.json();
}

function FileBlockView({ node, updateAttributes, selected, extension }: NodeViewProps) {
  const [url, setUrl] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { pageId, openWindow } = extension.options as FileBlockOptions;

  const attachmentId = node.attrs.attachment_id as string;

  useEffect(() => {
    let cancelled = false;
    if (!attachmentId) return;
    fetchPresignedUrl(attachmentId)
      .then((u) => { if (!cancelled) setUrl(u); })
      .catch((err) => { if (!cancelled) setError(String(err)); });
    return () => { cancelled = true; };
  }, [attachmentId]);

  const onFileChosen = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !pageId) return;
    setUploading(true);
    setError(null);
    try {
      const res = await uploadFile(pageId, file);
      updateAttributes({
        attachment_id: res.attachment_id,
        filename: res.filename,
        mime_type: res.mime_type,
        size_bytes: res.size_bytes,
      });
    } catch (err) {
      setError(String(err));
    } finally {
      setUploading(false);
    }
  }, [pageId, updateAttributes]);

  if (!attachmentId) {
    return (
      <NodeViewWrapper data-type="file" className="file-block file-block-empty">
        <input type="file" onChange={onFileChosen} disabled={uploading} />
        {uploading && <span>Uploading…</span>}
        {error && <span className="file-block-error">{error}</span>}
      </NodeViewWrapper>
    );
  }

  const mime = node.attrs.mime_type as string;
  const filename = node.attrs.filename as string;

  const openInWindow = () => {
    if (!openWindow || !url) return;
    openWindow({ type: "file", meta: { url, mimeType: mime, filename } });
  };

  return (
    <NodeViewWrapper
      data-type="file"
      data-selected={selected ? "true" : undefined}
      className="file-block"
    >
      {mime.startsWith("image/") && url && (
        <img src={url} alt={filename} onClick={openInWindow} onError={async () => {
          try { setUrl(await fetchPresignedUrl(attachmentId)); } catch { /* ignore */ }
        }} />
      )}
      {mime === "application/pdf" && (
        <div className="file-block-row">
          <span className="file-block-icon">📄</span>
          <span className="file-block-name">{filename}</span>
          <button type="button" onClick={openInWindow} disabled={!url}>Open</button>
        </div>
      )}
      {!mime.startsWith("image/") && mime !== "application/pdf" && (
        <div className="file-block-row">
          <span className="file-block-icon">📎</span>
          <a href={url || undefined} target="_blank" rel="noreferrer">{filename}</a>
        </div>
      )}
      {error && <div className="file-block-error">{error}</div>}
    </NodeViewWrapper>
  );
}

export default FileBlock;
```

- [ ] **Step 3: 跑测试确认过**

```bash
npm run test:unit -- block-schemas
```

Expected: FileBlock 2 PASS。

- [ ] **Step 4: Commit**

```bash
git add apps/web/components/console/editor/extensions/FileBlock.tsx apps/web/tests/unit/block-schemas.test.ts
git commit -m "feat(web): FileBlock TipTap extension (S2)"
```

---

### Task 12: ReferenceBlock（含 `ReferencePickerDialog`）

**Files:**
- Create: `apps/web/components/console/editor/extensions/ReferenceBlock.tsx`
- Modify: `apps/web/tests/unit/block-schemas.test.ts`

- [ ] **Step 1: 追加失败测试**

```ts
describe("ReferenceBlock", () => {
  const attrs = {
    target_type: "page",
    target_id: "pg_1",
    title: "Chapter 1",
    snippet: "Lorem ipsum dolor sit amet...",
  };

  it("default insertion carries reference attrs", () => {
    const e = makeEditor([ReferenceBlock]);
    e.chain().focus().insertContent({ type: "reference", attrs }).run();
    const node = e.getJSON().content?.find((n: any) => n.type === "reference");
    expect(node?.attrs).toEqual(attrs);
  });

  it("round-trips reference attrs through setContent", () => {
    const json = roundTrip([ReferenceBlock], { type: "reference", attrs });
    const node = json.content?.find((n: any) => n.type === "reference");
    expect(node?.attrs).toEqual(attrs);
  });
});
```

- [ ] **Step 2: 实现 `ReferenceBlock.tsx` + `ReferencePickerDialog`**

把 Dialog 组件放在同一文件内部（不导出），Node view 里触发：

```tsx
import { Node, mergeAttributes } from "@tiptap/core";
import { NodeViewWrapper, ReactNodeViewRenderer, type NodeViewProps } from "@tiptap/react";
import React, { useCallback, useEffect, useRef, useState } from "react";

type TargetType = "page" | "memory" | "study_chunk";
type ReferenceAttrs = {
  target_type: TargetType;
  target_id: string;
  title: string;
  snippet: string;
};

interface ReferenceBlockOptions {
  notebookId: string;
  openWindow?: (args: { type: string; meta: Record<string, unknown> }) => void;
}

const ReferenceBlock = Node.create<ReferenceBlockOptions>({
  name: "reference",
  group: "block",
  atom: true,
  selectable: true,
  draggable: true,

  addOptions() {
    return { notebookId: "", openWindow: undefined };
  },

  addAttributes() {
    return {
      target_type: { default: "page" },
      target_id: { default: "" },
      title: { default: "" },
      snippet: { default: "" },
    };
  },

  parseHTML() {
    return [{ tag: 'div[data-type="reference"]' }];
  },

  renderHTML({ HTMLAttributes }) {
    return [
      "div",
      mergeAttributes(HTMLAttributes, {
        "data-type": "reference",
        class: "reference-block",
      }),
    ];
  },

  addNodeView() {
    return ReactNodeViewRenderer(ReferenceBlockView);
  },
});

function ReferenceBlockView({ node, updateAttributes, selected, extension }: NodeViewProps) {
  const attrs = node.attrs as ReferenceAttrs;
  const { notebookId, openWindow } = extension.options as ReferenceBlockOptions;
  const [pickerOpen, setPickerOpen] = useState<boolean>(!attrs.target_id);

  const onClick = useCallback(() => {
    if (!openWindow) return;
    if (attrs.target_type === "page") {
      openWindow({ type: "note", meta: { pageId: attrs.target_id, notebookId } });
    } else if (attrs.target_type === "memory") {
      openWindow({ type: "memory", meta: { notebookId } });
    } else if (attrs.target_type === "study_chunk") {
      openWindow({ type: "file", meta: { target_id: attrs.target_id } });
    }
  }, [attrs, notebookId, openWindow]);

  return (
    <NodeViewWrapper
      data-type="reference"
      data-selected={selected ? "true" : undefined}
      className="reference-block"
    >
      {attrs.target_id ? (
        <button type="button" className="reference-card" onClick={onClick}>
          <div className="reference-type">{attrs.target_type}</div>
          <div className="reference-title">{attrs.title}</div>
          <div className="reference-snippet">{attrs.snippet}</div>
        </button>
      ) : (
        <button type="button" onClick={() => setPickerOpen(true)}>Pick a reference…</button>
      )}
      {pickerOpen && (
        <ReferencePickerDialog
          notebookId={notebookId}
          onClose={() => setPickerOpen(false)}
          onPick={(payload) => {
            updateAttributes(payload);
            setPickerOpen(false);
          }}
        />
      )}
    </NodeViewWrapper>
  );
}

interface ReferencePickerDialogProps {
  notebookId: string;
  onClose: () => void;
  onPick: (attrs: ReferenceAttrs) => void;
}

function useDebounced<T>(value: T, ms = 250): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

function ReferencePickerDialog({ notebookId, onClose, onPick }: ReferencePickerDialogProps) {
  const [tab, setTab] = useState<TargetType>("page");
  const [query, setQuery] = useState("");
  const [projectId, setProjectId] = useState<string | null>(null);
  const [results, setResults] = useState<ReferenceAttrs[]>([]);
  const debouncedQuery = useDebounced(query);

  // Fetch notebook → project_id once per mount.
  useEffect(() => {
    if (!notebookId) return;
    fetch(`/api/v1/notebooks/${notebookId}`, { credentials: "include" })
      .then((r) => r.json())
      .then((nb) => setProjectId(nb.project_id ?? null))
      .catch(() => setProjectId(null));
  }, [notebookId]);

  useEffect(() => {
    let cancelled = false;

    async function run() {
      if (tab === "page") {
        const url = `/api/v1/pages/search?q=${encodeURIComponent(debouncedQuery)}&notebook_id=${encodeURIComponent(notebookId)}`;
        const r = await fetch(url, { credentials: "include" });
        const body = await r.json();
        if (cancelled) return;
        setResults(
          (body.items || []).map((p: any) => ({
            target_type: "page" as const,
            target_id: p.id,
            title: p.title || "(untitled)",
            snippet: (p.plain_text || "").slice(0, 240),
          })),
        );
      } else if (tab === "memory") {
        if (!projectId) { setResults([]); return; }
        const r = await fetch(`/api/v1/memory/search`, {
          method: "POST",
          credentials: "include",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            project_id: projectId,
            query: debouncedQuery || " ",
            top_k: 10,
          }),
        });
        const body = await r.json();
        if (cancelled) return;
        setResults(
          (Array.isArray(body) ? body : []).map((m: any) => ({
            target_type: "memory" as const,
            target_id: m.memory?.id ?? m.id,
            title: (m.memory?.title || m.title || "").slice(0, 240) || "(memory)",
            snippet: (m.memory?.content || m.content || "").slice(0, 240),
          })),
        );
      } else {
        const r = await fetch(
          `/api/v1/notebooks/${encodeURIComponent(notebookId)}/study`,
          { credentials: "include" },
        );
        const body = await r.json();
        if (cancelled) return;
        const items = (body.items || []).filter((a: any) =>
          !debouncedQuery || (a.title || "").toLowerCase().includes(debouncedQuery.toLowerCase()),
        );
        setResults(
          items.map((a: any) => ({
            target_type: "study_chunk" as const,
            target_id: a.id,
            title: a.title || "(asset)",
            snippet: a.asset_type || "",
          })),
        );
      }
    }
    run().catch(() => setResults([]));
    return () => { cancelled = true; };
  }, [tab, debouncedQuery, notebookId, projectId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="ref-picker-backdrop" onClick={onClose}>
      <div className="ref-picker" onClick={(e) => e.stopPropagation()}>
        <div className="ref-picker-tabs">
          {(["page", "memory", "study_chunk"] as TargetType[]).map((t) => (
            <button
              key={t}
              type="button"
              className={t === tab ? "active" : ""}
              onClick={() => setTab(t)}
            >
              {t}
            </button>
          ))}
        </div>
        <input
          type="text"
          autoFocus
          placeholder="Search…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <ul className="ref-picker-results">
          {results.map((r) => (
            <li key={`${r.target_type}:${r.target_id}`}>
              <button type="button" onClick={() => onPick(r)}>
                <span className="title">{r.title}</span>
                <span className="snippet">{r.snippet}</span>
              </button>
            </li>
          ))}
          {results.length === 0 && <li className="empty">No results</li>}
        </ul>
      </div>
    </div>
  );
}

export default ReferenceBlock;
```

- [ ] **Step 3: 跑测试确认过**

```bash
cd /Users/dog/Desktop/MRAI/apps/web
npm run test:unit -- block-schemas
```

Expected: ReferenceBlock 2 PASS，全部 10 case 绿。

- [ ] **Step 4: Commit**

```bash
git add apps/web/components/console/editor/extensions/ReferenceBlock.tsx apps/web/tests/unit/block-schemas.test.ts
git commit -m "feat(web): ReferenceBlock + picker dialog (S2)"
```

---

## Phase D — 编辑器集成与 UI 串线

### Task 13: 扩展 barrel export

**Files:**
- Modify: `apps/web/components/console/editor/extensions/index.ts`

- [ ] **Step 1: 追加 5 条 re-export**

最终文件：

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

- [ ] **Step 2: TypeScript 编译确认**

```bash
cd /Users/dog/Desktop/MRAI/apps/web
npm run typecheck
```

Expected: 无错误。

- [ ] **Step 3: Commit**

```bash
git add apps/web/components/console/editor/extensions/index.ts
git commit -m "feat(web): export 5 new block extensions (S2)"
```

---

### Task 14: 共享类型文件 + active-editor registry

S3 已经把 AI Panel 抽成独立窗口（`AIPanelWindow.tsx`），AI Panel 和 NoteEditor 不在同一组件树，无法 prop drilling。Spec §7 明确方案：`NoteEditor.tsx` 维护一个 module-level store；AIPanel 通过查询 store 取"最近活跃" editor 的 handle；查不到就 toast。

**Files:**
- Create: `apps/web/components/console/editor/ai-output-types.ts`
- Create: `apps/web/components/console/editor/active-editor-registry.ts`

- [ ] **Step 1: 新建共享类型文件**

```ts
// apps/web/components/console/editor/ai-output-types.ts
export interface AIOutputInsertPayload {
  content_markdown: string;
  action_type: string;
  action_log_id: string;
  model_id: string | null;
  sources: Array<{ type: string; id: string; title: string }>;
}

export interface NoteEditorHandle {
  pageId: string;
  insertAIOutput: (payload: AIOutputInsertPayload) => void;
  focus: () => void;
}
```

- [ ] **Step 2: 新建 active-editor registry**

```ts
// apps/web/components/console/editor/active-editor-registry.ts
import type { NoteEditorHandle } from "./ai-output-types";

const editors: Map<string, NoteEditorHandle> = new Map();
let lastActivePageId: string | null = null;

export function registerActiveEditor(handle: NoteEditorHandle): () => void {
  editors.set(handle.pageId, handle);
  lastActivePageId = handle.pageId;
  return () => {
    editors.delete(handle.pageId);
    if (lastActivePageId === handle.pageId) {
      const remaining = Array.from(editors.keys());
      lastActivePageId = remaining[remaining.length - 1] ?? null;
    }
  };
}

export function markEditorActive(pageId: string): void {
  if (editors.has(pageId)) lastActivePageId = pageId;
}

export function getActiveEditor(pageId?: string): NoteEditorHandle | null {
  if (pageId && editors.has(pageId)) return editors.get(pageId) ?? null;
  if (lastActivePageId && editors.has(lastActivePageId)) return editors.get(lastActivePageId) ?? null;
  return null;
}
```

- [ ] **Step 3: Typecheck**

```bash
cd /Users/dog/Desktop/MRAI/apps/web
npm run typecheck
```

Expected: 无错误（两个文件都是孤立模块）。

- [ ] **Step 4: Commit**

```bash
git add apps/web/components/console/editor/ai-output-types.ts apps/web/components/console/editor/active-editor-registry.ts
git commit -m "feat(web): shared AI output types + active-editor registry (S2)"
```

---

### Task 15: `NoteEditor` 注册新扩展 + 接入 registry

**Files:**
- Modify: `apps/web/components/console/editor/NoteEditor.tsx`

- [ ] **Step 1: 加 `notebookId` 到 Props + import 新扩展与 registry**

找到 NoteEditor 的 props 接口（在 `NoteEditor.tsx` 顶部）。加 `notebookId?: string` 字段。

更新 import：

```ts
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
import { registerActiveEditor, markEditorActive } from "./active-editor-registry";
import type { NoteEditorHandle } from "./ai-output-types";
```

- [ ] **Step 2: 把扩展加到 `extensions: [...]` 并注入选项**

在 `useEditor({ extensions: [...] })` 里追加（建议放在 `WhiteboardBlock` 后面）：

```ts
    FileBlock.configure({ pageId }),
    AIOutputBlock,
    ReferenceBlock.configure({ notebookId: notebookId ?? "" }),
    TaskBlock.configure({ pageId }),
    FlashcardBlock,
```

`pageId` 是现有 prop、`notebookId` 是 Step 1 新加的 prop。`openWindow` 暂不接，缺席时点击行为降级为不做事（符合 spec §4.2 "graceful no-op" 精神）。

- [ ] **Step 3: 把 editor handle 注册到 registry**

在 `useEditor(...)` 返回之后加一个 `useEffect`：

```tsx
useEffect(() => {
  if (!editor) return;
  const handle: NoteEditorHandle = {
    pageId,
    insertAIOutput: (payload) => {
      editor.chain().focus().insertContent({ type: "ai_output", attrs: payload }).run();
    },
    focus: () => editor.commands.focus(),
  };
  return registerActiveEditor(handle);
}, [editor, pageId]);
```

并在 editor 的 `onFocus` 回调里（若已有 `editorProps` 或 `onFocus`）调用 `markEditorActive(pageId)`。若现有 NoteEditor 没有 focus 钩子，最简洁方式是在 outer div 上加 `onFocusCapture={() => markEditorActive(pageId)}`。

- [ ] **Step 4: Typecheck + 冒烟**

```bash
npm run typecheck
```

Expected: 无错误。

- [ ] **Step 5: Commit**

```bash
git add apps/web/components/console/editor/NoteEditor.tsx
git commit -m "feat(web): register 5 new extensions + active-editor registry (S2)"
```

---

### Task 16: SlashCommandMenu 追加 5 条命令

**Files:**
- Modify: `apps/web/components/console/editor/SlashCommandMenu.tsx`

- [ ] **Step 1: 更新图标 import**

顶部的 `from "lucide-react"` 那一行里追加 `FileUp`、`Sparkles`、`Link2`、`CheckCircle2`、`Layers`。

- [ ] **Step 2: 在 `COMMANDS` 末尾追加 5 条**

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
      editor.chain().focus().insertContent({
        type: "ai_output",
        attrs: { content_markdown: "", action_type: "", action_log_id: "", model_id: null, sources: [] },
      }).run(),
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
      editor.chain().focus().insertContent({
        type: "task",
        attrs: {
          block_id: crypto.randomUUID(),
          title: "",
          description: null,
          due_date: null,
          completed: false,
          completed_at: null,
        },
      }).run(),
  },
  {
    title: "Flashcard",
    description: "Q/A card that flips on click",
    icon: Layers,
    command: (editor) =>
      editor.chain().focus().insertContent({
        type: "flashcard",
        attrs: { front: "", back: "", flipped: false },
      }).run(),
  },
```

- [ ] **Step 3: Typecheck 并冒烟菜单可见**

```bash
npm run typecheck
```

Expected: 无错误。

- [ ] **Step 4: Commit**

```bash
git add apps/web/components/console/editor/SlashCommandMenu.tsx
git commit -m "feat(web): slash menu +5 commands (file/ai_output/reference/task/flashcard) (S2)"
```

---

### Task 17: AIPanel 新增 "Insert as AI block" 按钮（调 registry）

**Files:**
- Modify: `apps/web/components/console/editor/AIPanel.tsx`

AIPanel 目前在 S3 窗口化之后处于自己的窗口，跟 NoteEditor 不在同一组件树。按 spec §7 的"module-level store"建议，按钮直接调 `getActiveEditor(pageId)?.insertAIOutput(payload)`，查不到就 toast。

- [ ] **Step 1: 每条消息的本地 state 补四个字段**

AIPanel 在处理 SSE 流时已拿到 `sources`（`message_start` 或 `message_done` 里都存了）。`model_id` 在 `message_done` 里；`action_log_id` 与 `action_type` 是 S1 加在 SSE payload 里的字段。用 grep 核实 key 名：

```bash
grep -n "action_log_id\|action_type" apps/api/app/routers/notebook_ai.py | head -20
```

确认 key 名后（一般是 snake_case 原样），在 AIPanel 消息的本地 shape 上扩展：

```ts
interface AssistantMsg {
  role: "assistant";
  content: string;
  action_type?: string;
  action_log_id?: string;
  model_id?: string | null;
  sources?: Array<{ type: string; id: string; title: string }>;
}
```

在已处理 `message_start`（赋 sources）与 `message_done` 的地方，同步记录 `action_log_id`、`action_type`、`model_id`。

- [ ] **Step 2: 在 "Insert to editor" 按钮旁加第二个按钮，查 registry 执行**

顶部 import：

```ts
import { getActiveEditor } from "./active-editor-registry";
import type { AIOutputInsertPayload } from "./ai-output-types";
```

按钮渲染（紧贴已有 `onInsertToEditor` 按钮）：

```tsx
{msg.role === "assistant" && msg.action_log_id && (
  <button
    type="button"
    className="ai-panel-insert-ai-block"
    onClick={() => {
      const payload: AIOutputInsertPayload = {
        content_markdown: msg.content,
        action_type: msg.action_type ?? "",
        action_log_id: msg.action_log_id ?? "",
        model_id: msg.model_id ?? null,
        sources: msg.sources ?? [],
      };
      const handle = getActiveEditor(pageId);
      if (!handle) {
        console.warn("[AIPanel] no active editor to insert into");
        // Use existing toast system; if none, a simple alert() is acceptable for S2.
        if (typeof window !== "undefined" && window.dispatchEvent) {
          window.dispatchEvent(new CustomEvent("mrai:toast", {
            detail: { level: "warn", message: "Open the note editor to insert AI block" }
          }));
        }
        return;
      }
      handle.insertAIOutput(payload);
    }}
  >
    {t("ai.insertAsAIBlock")}
  </button>
)}
```

`pageId` 是 AIPanel 现有 prop（`AIPanelProps.pageId?: string`）。若调用时 `pageId` 不存在，`getActiveEditor(undefined)` 会回退到 "最近活跃" editor（见 Task 14 registry 逻辑）。

- [ ] **Step 3: Typecheck**

```bash
cd /Users/dog/Desktop/MRAI/apps/web
npm run typecheck
```

Expected: 无错误。若 `t("ai.insertAsAIBlock")` 报未定义 key，占位先用英文字符串并在 Task 19 里补 i18n。

- [ ] **Step 4: Commit**

```bash
git add apps/web/components/console/editor/AIPanel.tsx
git commit -m "feat(web): AIPanel 'Insert as AI block' via registry (S2)"
```

---

### Task 18: CSS（`note-editor.css`）加 5 段样式

**Files:**
- Modify: `apps/web/styles/note-editor.css`

- [ ] **Step 1: 在文件末尾追加五段**

选择器完全按 spec §6.5 的命名：`.file-block`、`.ai-output-block`、`.reference-block`、`.task-block`、`.flashcard-block`。目标是最小能看——outline / padding / hover / `[data-selected="true"]` 描边，不做设计 polish。

```css
/* ---------- S2 block visuals ---------- */

.file-block,
.ai-output-block,
.reference-block,
.task-block,
.flashcard-block {
  padding: 8px 12px;
  margin: 8px 0;
  border-radius: 6px;
  border: 1px solid var(--border, #e5e7eb);
  background: var(--bg-subtle, #fafafa);
  transition: border-color 150ms ease;
}

.file-block[data-selected="true"],
.ai-output-block[data-selected="true"],
.reference-block[data-selected="true"],
.task-block[data-selected="true"],
.flashcard-block[data-selected="true"] {
  border-color: var(--primary, #2563eb);
}

.file-block-empty input[type="file"] { display: block; }
.file-block img { max-width: 100%; height: auto; border-radius: 4px; cursor: zoom-in; }
.file-block-row { display: flex; gap: 8px; align-items: center; }
.file-block-error { color: var(--danger, #dc2626); font-size: 12px; }

.ai-output-header { display: flex; gap: 8px; font-size: 12px; color: var(--fg-subtle, #6b7280); }
.ai-output-badge { padding: 2px 6px; border-radius: 4px; background: var(--primary-subtle, #eef2ff); }
.ai-output-trace { margin-left: auto; font-size: 12px; text-decoration: underline; background: none; border: none; cursor: pointer; }
.ai-output-sources { list-style: none; padding: 0; margin: 8px 0 0; font-size: 12px; }
.ai-output-sources li { display: flex; gap: 6px; }

.reference-card { width: 100%; text-align: left; padding: 6px 8px; background: transparent; border: none; cursor: pointer; }
.reference-type { font-size: 10px; text-transform: uppercase; color: var(--fg-subtle); }
.reference-title { font-weight: 600; }
.reference-snippet { font-size: 12px; color: var(--fg-subtle); }

.ref-picker-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,.35); z-index: 1000; display: flex; align-items: center; justify-content: center; }
.ref-picker { background: white; border-radius: 8px; padding: 16px; width: 480px; max-height: 70vh; display: flex; flex-direction: column; }
.ref-picker-tabs { display: flex; gap: 4px; margin-bottom: 8px; }
.ref-picker-tabs button { padding: 4px 8px; border: 1px solid var(--border); background: white; cursor: pointer; }
.ref-picker-tabs button.active { background: var(--primary-subtle, #eef2ff); }
.ref-picker input[type="text"] { padding: 6px 8px; border: 1px solid var(--border); border-radius: 4px; margin-bottom: 8px; }
.ref-picker-results { list-style: none; padding: 0; margin: 0; overflow-y: auto; flex: 1; }
.ref-picker-results li button { width: 100%; text-align: left; background: none; border: none; padding: 6px 8px; cursor: pointer; }
.ref-picker-results li button:hover { background: var(--bg-subtle); }
.ref-picker-results .empty { padding: 8px; color: var(--fg-subtle); }

.task-block-row { display: flex; gap: 8px; align-items: center; }
.task-block-title { flex: 1; border: none; background: transparent; outline: none; }
.task-block-due { font-size: 11px; color: var(--fg-subtle); }
.task-block-error { color: var(--danger, #dc2626); font-size: 12px; }

.flashcard-block { text-align: center; min-height: 64px; }
.flashcard-edit { display: flex; flex-direction: column; gap: 6px; }
.flashcard-edit textarea { min-height: 48px; padding: 4px; }
.flashcard-preview { cursor: pointer; min-width: 200px; padding: 16px; background: transparent; border: none; width: 100%; font-size: 16px; }
```

- [ ] **Step 2: 冒烟（启动 dev server，手动看五个块渲染成功）**

此 step 可视为人工 QA：`npm run dev`，然后打开任意 notebook 页面，`/` 唤出菜单，五个新项都能插入并显示基本框。无回归则通过。

- [ ] **Step 3: Commit**

```bash
git add apps/web/styles/note-editor.css
git commit -m "feat(web): S2 block visuals (file/ai_output/reference/task/flashcard)"
```

---

### Task 19: i18n 文案

**Files:**
- Modify: `apps/web/messages/en/console-notebooks.json`
- Modify: `apps/web/messages/zh/console-notebooks.json`

- [ ] **Step 1: 确定现有 i18n 结构**

```bash
grep -n "insertToEditor" apps/web/messages/en/console-notebooks.json
```

定位到 AI panel 的 namespace。

- [ ] **Step 2: 在同一 `ai` 子对象里追加**

EN：

```json
"ai": {
  "insertToEditor": "Insert to editor",
  "insertAsAIBlock": "Insert as AI block"
}
```

ZH：

```json
"ai": {
  "insertToEditor": "插入到编辑器",
  "insertAsAIBlock": "插入为 AI 块"
}
```

若 slash 菜单的 title/description 来自 i18n，照同样模式追加 5 条，key 名例如 `slash.file.title / slash.file.desc` 等（实际按现有命名风格）。若 slash 菜单现有代码是写死英文字符串，保持写死，不在本 Task 做 i18n 重构。

- [ ] **Step 3: 冒烟**

```bash
npm run typecheck
```

Expected: 无错误。

- [ ] **Step 4: Commit**

```bash
git add apps/web/messages/en/console-notebooks.json apps/web/messages/zh/console-notebooks.json
git commit -m "feat(web): i18n for S2 blocks (S2)"
```

---

## Phase E — 端到端冒烟测试

### Task 20: Playwright `s2-blocks.spec.ts`

**Files:**
- Create: `apps/web/tests/s2-blocks.spec.ts`

- [ ] **Step 1: 写两个测试**

```ts
import { test, expect } from "@playwright/test";

test.describe("S2 new block types", () => {
  test("flashcard flip toggles front/back", async ({ page }) => {
    await page.goto("/workspace/notebooks");
    await page.getByRole("button", { name: /create/i }).first().click();
    await page.waitForURL(/\/workspace\/notebooks\/[^/]+$/);
    await page.getByRole("button", { name: /create/i }).first().click();

    const editor = page.locator(".ProseMirror").first();
    await editor.click();
    await editor.type("/flashcard");
    await page.keyboard.press("Enter");

    const card = page.locator(".flashcard-block").first();
    await expect(card).toBeVisible({ timeout: 5_000 });

    const front = card.locator("textarea[aria-label='Flashcard front']");
    const back = card.locator("textarea[aria-label='Flashcard back']");
    await front.fill("Q?");
    await back.fill("A!");
    await card.getByRole("button", { name: /preview/i }).click();

    const preview = card.locator(".flashcard-preview");
    await expect(preview).toContainText("Q?");
    await preview.click();
    await expect(preview).toContainText("A!");
  });

  test("task checkbox toggle persists across reload", async ({ page }) => {
    await page.goto("/workspace/notebooks");
    await page.getByRole("button", { name: /create/i }).first().click();
    await page.waitForURL(/\/workspace\/notebooks\/[^/]+$/);
    await page.getByRole("button", { name: /create/i }).first().click();

    const editor = page.locator(".ProseMirror").first();
    await editor.click();
    await editor.type("/task");
    await page.keyboard.press("Enter");

    const task = page.locator(".task-block").first();
    await expect(task).toBeVisible({ timeout: 5_000 });
    await task.locator("input.task-block-title").fill("Write E2E test");
    const checkbox = task.locator("input[type='checkbox']");
    await checkbox.check();

    await page.waitForTimeout(500);
    await page.reload();

    const taskAfter = page.locator(".task-block").first();
    const cbAfter = taskAfter.locator("input[type='checkbox']");
    await expect(cbAfter).toBeChecked();

    // Assert an ai-action-log entry via the S1 Trace tab
    await page.getByTestId("note-open-ai-panel").first().click();
    await page.getByTestId("ai-panel-tab-trace").click();
    const items = page.getByTestId("ai-action-item");
    await expect(items.first()).toContainText(/task\.complete/, { timeout: 10_000 });
  });
});
```

- [ ] **Step 2: 跑 Playwright**

```bash
cd /Users/dog/Desktop/MRAI/apps/web
npm run test:e2e -- s2-blocks.spec
```

Expected: 两个测试都 PASS（需要本地 dev stack 或 playwright 的预配置；失败多半是 dev stack 未起或 auth 未 seed——按项目现有 Playwright 配置流程补救）。

- [ ] **Step 3: Commit**

```bash
git add apps/web/tests/s2-blocks.spec.ts
git commit -m "test(web): S2 blocks Playwright smoke (flashcard + task) (S2)"
```

---

## Phase F — 收尾校验

### Task 21: 全量回归

- [ ] **Step 1: 后端 pytest**

```bash
cd /Users/dog/Desktop/MRAI/apps/api
uv run pytest tests -v
```

Expected: 全部 PASS（含既有 + 新增）。

- [ ] **Step 2: 前端单测**

```bash
cd /Users/dog/Desktop/MRAI/apps/web
npm run test:unit
```

Expected: 全部 PASS（含 10 新 case）。

- [ ] **Step 3: Typecheck + build**

```bash
cd /Users/dog/Desktop/MRAI/apps/web
npm run typecheck
npm run build
```

Expected: 无错误。

- [ ] **Step 4: 人工 QA 对照 spec §10 的 Acceptance Criteria**

- [ ] Slash 菜单看到 19 条（其中 5 条新）
- [ ] File 块能上传一个 PDF 或 PNG，刷新后 presigned URL 重新渲染
- [ ] AIPanel 把一个流式回复插成 `ai_output` 块并显示 `action_type` badge 与 "View trace"
- [ ] Reference picker 的 Pages / Memory / Study Chunks 三 tab 都可搜并插入
- [ ] Task 勾选产生 `AIActionLog(action_type=task.complete)`（可在 Trace tab 看到）
- [ ] Flashcard 默认编辑态、preview 后点击可翻转
- [ ] 已有 14 个块类型回归无异常

- [ ] **Step 5: Final commit（如果 QA 发现小修）**

修完后：

```bash
git add -p  # 精准 stage
git commit -m "chore(s2): QA adjustments"
```

---

## 附录 A: 决策备忘

- **`scope="page"` vs `"selection"`：** S2 的三个端点都不涉及选区，一律 `scope="page"`（`action_log_context` 里 scope 是自由字符串）。
- **没有 LLM → 不调 `record_usage`：** 附件上传与任务完成都是纯 CRUD，不记 usage。Spec §5.2 也明确说明。
- **`data_item_id=None`：** S2 附件走独立 bucket，不挂 data item 管线；S4/S7 有需要再回补。
- **`meta_json` 当前唯一用途是 `{"object_key": "..."}`：** 保留为 JSON 方便将来扩展（缩略图、EXIF、page range 等）。
- **前端把 `pageId`/`notebookId` 用 `addOptions` 而非 attribute：** attribute 会序列化到 content_json；这些是运行时上下文，不应持久化。
- **"View trace" 用 `CustomEvent` 而非直连 WindowManager：** Spec §4.2 明确：S2 不假设 WindowManager 可用，留事件钩子给后续 sub-project 捡。

## 附录 B: 与其他 sub-project 的边界

| 子项目 | S2 埋下的接口 | 它们接手要做的 |
|---|---|---|
| S4 (学习系统) | flashcard 的 content_json shape | 批量把页面内 flashcard 挪到 `StudyCard` 表 |
| S5 (主动服务) | `AIActionLog(action_type="task.complete")` | 按 `user_id` group 做 daily digest |
| S3 (窗口化) 未来完整版 | `mrai:open-trace` CustomEvent、`openWindow` option | Listener 真正把 Trace tab 聚焦到指定 log |
