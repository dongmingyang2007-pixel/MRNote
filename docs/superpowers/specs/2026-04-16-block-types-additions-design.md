# S2 — Block Types Additions (Design)

Date: 2026-04-16
Status: Approved for implementation
Scope: Sub-project S2 of the MRAI notebook upgrade (see
`MRAI_notebook_ai_os_build_spec.md` §5.1.3).

## 1. Purpose

Spec §5.1.3 enumerates 17 block types the notebook must support. The
current editor has 14 of them (StarterKit + TaskList/TaskItem + Image
+ Link + HorizontalRule + CodeBlockLowlight + MathBlock + InlineMath
+ CalloutBlock + WhiteboardBlock). S2 fills the remaining five:

| block_type | §5.1.3 definition |
|---|---|
| `file` | 文件嵌入/预览 |
| `ai_output` | AI 生成内容，带 source 引用 |
| `reference` | 引用另一个页面/记忆/文档 chunk |
| `task` | 任务项，可标记完成状态，可触发 outcome 记录 |
| `flashcard` | 学习卡片，可嵌入页面内 |

After S2 the slash menu shows 19 options (14 existing + 5 new), and
notebook pages can mix all of the block types the spec promises
without regressing existing content.

## 2. Scope

### In scope

- 5 new TipTap custom Node extensions, each a single `.tsx` file
  under `apps/web/components/console/editor/extensions/` with its
  NodeView inline.
- Slash menu entries for all five, wired into the existing
  `SlashCommandMenu.tsx` COMMANDS array.
- CSS in `apps/web/styles/note-editor.css` for block visuals.
- Three new backend endpoints, all already covered by the S1
  `action_log_context` for audit trails:
  - `POST /api/v1/pages/{page_id}/attachments/upload` — uploads a
    file, creates a `NotebookAttachment` row, returns its metadata.
  - `GET  /api/v1/attachments/{attachment_id}/url` — returns a
    fresh presigned URL for rendering.
  - `POST /api/v1/pages/{page_id}/tasks/{block_id}/complete` — logs
    task completion/reopen via `AIActionLog`.
- One new config setting and MinIO bucket for attachments.
- Unit tests for each block's JSON (de)serialization; API tests for
  the three new endpoints; one Playwright smoke covering flashcard
  flip + task complete.

### Out of scope (explicit)

- `StudyCard` persistence — flashcards are pure-frontend for S2;
  S4's Deck migration will later batch-import flashcards from pages.
- `MemoryOutcome` writes from `task.complete` — S2 only lands an
  `AIActionLog`; S5's proactive-services sub-project consumes it.
- AI-driven auto-insertion of `ai_output` blocks — always user-
  initiated via "Insert as AI block" in AI Panel / FloatingToolbar.
- Reference-target semantic search — title `ILIKE` is enough for S2.
- Attachment delete / replace endpoints — only upload + URL fetch.
- Mobile layout adaptation.

## 3. Architecture

```
User types "/" in editor
      │
      ▼
SlashCommandMenu (existing; adds 5 new entries)
      │
      ▼
TipTap Node extension (new; one .tsx per block)
      │
      ├─ attrs: content_json shape (see §4)
      └─ NodeView (inline in same .tsx) → React UI
              │
              ├─ file:       uploads → /attachments/upload + /attachments/{id}/url
              ├─ ai_output:  inserted via AIPanel / FloatingToolbar "insert" button
              ├─ reference:  pick-dialog → openWindow on click
              ├─ task:       checkbox → /tasks/{block_id}/complete
              └─ flashcard:  local flip state, pure frontend
```

Each block serializes to `content_json` within the page's TipTap
document and round-trips through `PATCH /pages/{id}`; the existing
autosave path is untouched.

## 4. Block Schemas (content_json)

### 4.1 `file`

```json
{
  "attachment_id": "att_…",
  "filename": "chapter1.pdf",
  "mime_type": "application/pdf",
  "size_bytes": 1234567
}
```

The URL is not persisted. On render the NodeView calls `GET
/api/v1/attachments/{attachment_id}/url` to obtain a fresh presigned
URL (15-minute TTL). This avoids stale URLs in saved documents.

Rendering by `mime_type`:
- `image/*` → inline `<img>` with the fetched URL; click opens a
  `file` window (`openWindow({type:"file",meta:{url,mimeType,
  filename}})`).
- `application/pdf` → PDF icon + filename + "Open" button that
  opens a `file` window.
- other → generic file icon + filename + download link.

### 4.2 `ai_output`

```json
{
  "content_markdown": "…",
  "action_type": "selection.rewrite",
  "action_log_id": "log_…",
  "model_id": "qwen-plus",
  "sources": [
    { "type": "memory", "id": "…", "title": "…" }
  ]
}
```

NodeView layout:
- Header row: small badge with `action_type`, `model_id`, and a
  "View trace" button that opens the notebook's AI Panel on the
  Trace tab scoped to this page. For S2 the button calls
  `window.dispatchEvent(new CustomEvent("mrai:open-trace", {detail:
  { action_log_id }}))`. Actual cross-window focus is deferred
  (graceful: if no listener, the button becomes a no-op + console
  hint).
- Body: `react-markdown` (already a dep) rendering
  `content_markdown`.
- Footer: sources list (`type · title`), each a link that calls
  `openWindow` for the corresponding target type when clickable.

Regeneration is not supported — spec §1 mandated "view source only".

### 4.3 `reference`

```json
{
  "target_type": "page" | "memory" | "study_chunk",
  "target_id": "…",
  "title": "…",
  "snippet": "…up to 240 chars…"
}
```

Insertion flow:
1. Slash menu item → opens a modal (new `ReferencePickerDialog`
   component co-located with `ReferenceBlock.tsx`).
2. Dialog has three tabs: Pages / Memory / Study Chunks. Each tab
   issues a search request with a 250 ms debounced input. Scope of
   each search is the **current notebook** (derived from the note's
   `notebookId` meta passed through the editor).
   - Pages: reuse existing `GET /api/v1/pages/search?q=...&notebook_id={notebookId}`.
   - Memory: reuse existing `GET /api/v1/memory/search?q=...&project_id={notebook.project_id}&limit=10`
     — the notebook's project id is fetched once per picker mount
     from `GET /api/v1/notebooks/{notebookId}`.
   - Study Chunks: `GET /api/v1/notebooks/{notebookId}/study-assets`
     returns the list; picking an asset reveals its chunks via
     `GET /api/v1/study-assets/{id}/chunks?q=...`. For S2 search is
     title-only; body search is deferred.
3. User picks one → dialog returns the payload → TipTap inserts the
   block with the picked attrs.

Click behavior on the rendered block:
- `page` → `openWindow({type:"note", meta:{pageId, notebookId}})`
- `memory` → `openWindow({type:"memory", meta:{notebookId, initialPageId: <host page id>}})`
- `study_chunk` → `openWindow({type:"file", meta:{…}})` using the
  chunk's `data_item_id` to resolve URL via the same
  `/attachments/{id}/url` endpoint if applicable; otherwise the
  reference renders as read-only with a copy-id button.

### 4.4 `task`

```json
{
  "block_id": "<uuid, generated at insert>",
  "title": "…",
  "description": null,
  "due_date": "2026-05-01" | null,
  "completed": false,
  "completed_at": null
}
```

`block_id` is a stable UUID generated by `crypto.randomUUID()` on
insert. TipTap node identity is not stable across moves; `block_id`
gives the backend a join key for audit logs.

NodeView:
- A single row: checkbox + editable title + optional due-date
  badge.
- Clicking the checkbox flips local state **and** posts
  `POST /api/v1/pages/{page_id}/tasks/{block_id}/complete` with
  `{completed: true, completed_at: new Date().toISOString()}`.
  Failure rolls back the local flip and shows a tiny red indicator.
- `description` and `due_date` are exposed through an expandable
  "⋮" menu to keep the default footprint small.

### 4.5 `flashcard`

```json
{
  "front": "What is X?",
  "back": "X is …",
  "flipped": false
}
```

NodeView toggles between edit mode (two textareas: Front / Back) and
preview mode (a single card that flips on click). `flipped` is
persisted so that the card resumes on the user's chosen side after
reload.

A small `aria-label` tells screen readers "Flashcard, front side" /
"back side".

## 5. Backend

### 5.1 Attachments

New endpoints in `apps/api/app/routers/notebooks.py` (under the
existing `pages_router`):

```python
@pages_router.post("/{page_id}/attachments/upload")
async def upload_page_attachment(
    page_id: str,
    file: UploadFile = File(...),
    title: str = Form(""),
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _: None = Depends(require_workspace_write_access),
    __: None = Depends(require_csrf_protection),
) -> dict[str, Any]:
    ...
```

Implementation:
1. `_get_page_or_404(db, page_id, workspace_id)`.
2. Read `file.file.read()`; reject if size > 50 MiB
   (`raise ApiError("file_too_large", ..., 413)`). The size limit
   lives in `settings.notebook_attachment_max_bytes`, default 50
   MiB.
3. `key = f"{workspace_id}/{page_id}/{uuid4().hex}/{safe_filename}"`
   (reuse `sanitize_filename` from `services/storage.py`).
4. `storage.get_s3_client().put_object(Bucket=settings.
   s3_notebook_attachments_bucket, Key=key, Body=..., ContentType=
   file.content_type or "application/octet-stream")`.
   The bucket is ensured once at lifespan startup (§5.3); the
   endpoint itself does not retry bucket creation.
5. Insert `NotebookAttachment(page_id=page_id, data_item_id=None,
   attachment_type=_classify(file.content_type), title=title or
   file.filename, meta_json={"object_key": key})`. `data_item_id`
   stays null — S2 attachments live under their own bucket, not the
   MinIO "data item" pipeline, so cross-referencing is optional.
6. (The `meta_json` column is added in §5.4's migration; this
   endpoint assumes the column exists.)
7. Return:
   ```json
   {
     "attachment_id": "<uuid>",
     "filename": "…",
     "mime_type": "…",
     "size_bytes": 123,
     "attachment_type": "pdf|image|…"
   }
   ```

```python
@router.get("/attachments/{attachment_id}/url")
def get_attachment_url(
    attachment_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
) -> dict[str, Any]:
    ...
```

(`router` here is a new `APIRouter(prefix="/api/v1/attachments",
tags=["attachments"])` registered from `main.py`. The POST lives on
`pages_router` because it's page-scoped; GET lives on a top-level
attachments router because the client knows only the id.)

Implementation:
1. Look up `NotebookAttachment` → associated `NotebookPage` →
   `Notebook` → verify workspace match. 404 otherwise.
2. `object_key = attachment.meta_json.get("object_key")`; 404 if
   missing.
3. Call `get_s3_presign_client().generate_presigned_url("get_object",
   Params={"Bucket": settings.s3_notebook_attachments_bucket, "Key":
   object_key}, ExpiresIn=settings.s3_presign_expire_seconds)`.
4. Return `{ "url": "…", "expires_in_seconds": 900 }`.

### 5.2 Task completion

New endpoint in `apps/api/app/routers/notebooks.py`:

```python
@pages_router.post("/{page_id}/tasks/{block_id}/complete")
async def complete_task(
    page_id: str,
    block_id: str,
    payload: dict[str, Any],
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _: None = Depends(require_workspace_write_access),
    __: None = Depends(require_csrf_protection),
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

No LLM call → no `record_usage`. The action log itself is the
signal. S5 can query
`AIActionLog.filter(action_type="task.complete").group_by(user_id)`
for daily digests.

### 5.3 Config + lifespan

Add to `apps/api/app/core/config.py`:

```python
s3_notebook_attachments_bucket: str = "notebook-attachments"
notebook_attachment_max_bytes: int = 50 * 1024 * 1024
```

Extend the lifespan block in `apps/api/app/main.py` to also ensure
the new bucket exists, using the same HEAD-then-CREATE pattern as
the S1 `ai-action-payloads` block.

### 5.4 NotebookAttachment meta_json column (required migration)

Current model (`models/entities.py`) has **no** `meta_json` column.
S2 adds it as a NOT NULL JSON column with a `{}` default so old
rows stay valid.

ORM change:

```python
class NotebookAttachment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "notebook_attachments"
    page_id: Mapped[str] = mapped_column(ForeignKey("notebook_pages.id", ondelete="CASCADE"), index=True)
    data_item_id: Mapped[str | None] = mapped_column(ForeignKey("data_items.id", ondelete="SET NULL"), nullable=True)
    attachment_type: Mapped[str] = mapped_column(String(20), default="other", nullable=False)
    title: Mapped[str] = mapped_column(Text, default="", nullable=False)
    meta_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)  # NEW
```

Alembic migration `202604170001_notebook_attachment_meta.py`:

```sql
ALTER TABLE notebook_attachments
  ADD COLUMN IF NOT EXISTS meta_json JSONB NOT NULL DEFAULT '{}'::jsonb;
```

Test environments use `Base.metadata.create_all` so the column is
picked up automatically.

## 6. Frontend Wiring

### 6.1 Extensions index

`apps/web/components/console/editor/extensions/index.ts` re-exports
all nine extensions (4 existing + 5 new):

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

### 6.2 NoteEditor

Add the five new names to the `import { … } from "./extensions"`
line and append them to the `extensions: [ … ]` array. No other
NoteEditor changes.

### 6.3 SlashCommandMenu

Append five entries to `COMMANDS` in `SlashCommandMenu.tsx`:

```ts
  {
    title: "File",
    description: "Upload and embed a file",
    icon: FileUp,
    command: (editor) =>
      editor
        .chain()
        .focus()
        .insertContent({ type: "file" })
        .run(),
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
      editor
        .chain()
        .focus()
        .insertContent({ type: "reference" })
        .run(),
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
        .insertContent({ type: "flashcard", attrs: { front: "", back: "", flipped: false } })
        .run(),
  },
```

Icons reuse existing `lucide-react` imports; add `Link2`,
`CheckCircle2`, `Layers` to the top-of-file import.

### 6.4 AI Panel "Insert as AI block" action

`AIPanel.tsx` today already shows an "Insert to editor" text button
next to each completed assistant turn, driven by an `onInsertToEditor`
prop. S2 adds a parallel button "Insert as AI block" driven by a
new prop:

```ts
interface AIOutputInsertPayload {
  content_markdown: string;
  action_type: string;
  action_log_id: string;
  model_id: string | null;
  sources: Array<{ type: string; id: string; title: string }>;
}

interface AIPanelProps {
  // …existing props…
  onInsertAIOutput?: (payload: AIOutputInsertPayload) => void;
}
```

Wiring:
- `AIPanel.tsx` collects `action_log_id`, `model_id`, and `sources`
  from the SSE event payloads already received (S1 wired these into
  `message_done`); it just needs to hold on to them per message.
- `AskTab.tsx` (the only current caller) forwards the prop
  unchanged.
- `NoteEditor.tsx` passes a concrete implementation that calls
  `editorRef.current?.chain().focus().insertContent({ type:
  "ai_output", attrs: payload }).run()`. If no editor is mounted
  when the user clicks, the button calls `console.warn` and toasts
  via the existing toast system (same pattern S3 §4.7 used for
  sidebar no-op).

This is the sole automatic cross-wire between AIPanel and the
editor. Everything else in AIPanel stays as-is.

### 6.5 Styles

Add to `apps/web/styles/note-editor.css` one focused section per
block with standard selectors:

```css
.file-block { … }
.ai-output-block { … }
.reference-block { … }
.task-block { … }
.flashcard-block { … }
```

CSS stays minimal — outlines, padding, hover, focus states. Design
polish is explicitly out of scope.

## 7. Error Handling

- **Attachment upload failure** (MinIO down / quota): backend returns
  500 with `ApiError("upload_failed", …)`. Frontend shows an inline
  error on the block and a retry button; block stays in "pending"
  state (no `attachment_id` set) and is not persisted to the document
  until retry succeeds.
- **Attachment URL expired mid-render**: the `<img>` / `<iframe>`
  `onError` handler re-fetches `/attachments/{id}/url` once before
  rendering a fallback icon.
- **Task toggle failure**: local flip rolls back, a transient toast
  shows the message ("Couldn't save task state; tap again to retry").
- **Reference target deleted**: on click, show "This reference target
  is no longer available." No automatic cleanup — manual delete.
- **AI Panel "Insert" when editor not focused**: dispatch to the
  most recently active editor (track a ref in a small module-level
  store in `NoteEditor.tsx`). If no editor is mounted, show a toast.

## 8. Testing Strategy

Target ≥80% line coverage on new/changed modules.

### 8.1 Backend unit + API tests

- `apps/api/tests/test_attachment_upload.py` (new) — 4 cases:
  1. Upload a small image → 200, row exists, meta_json has
     `object_key`.
  2. Upload exceeding size limit → 413 `file_too_large`.
  3. Upload to page in another workspace → 404.
  4. `GET /attachments/{id}/url` → 200 with URL containing the
     bucket name.
- `apps/api/tests/test_task_complete.py` (new) — 3 cases:
  1. Complete a task → AIActionLog with
     `action_type="task.complete"` and `block_id` set.
  2. Reopen a task → `action_type="task.reopen"`.
  3. Cross-workspace call → 404.

Both files follow the existing `test_notebook_ai_logging.py`
bootstrap pattern (self-contained SQLite, real `register_user`).

### 8.2 Frontend unit tests (vitest)

`apps/web/tests/unit/block-schemas.test.ts` — one describe block per
extension, each with 2 tests:

1. Default insertion produces the expected attrs.
2. `getJSON` → `setContent` round-trip preserves attrs.

Five blocks × 2 tests = 10 tests.

### 8.3 Playwright smoke

`apps/web/tests/s2-blocks.spec.ts` — two tests:

1. **Flashcard flip**: insert via slash menu → type front/back →
   click preview → card shows back text.
2. **Task complete**: insert task → set title → click checkbox →
   refresh page → task still shows completed. Server-side, assert a
   new AIActionLog row is present (via the S1 trace tab).

Attachment upload requires a real stack and is left as a manual QA
step.

## 9. File Plan

### New files

- `apps/web/components/console/editor/extensions/FileBlock.tsx`
- `apps/web/components/console/editor/extensions/AIOutputBlock.tsx`
- `apps/web/components/console/editor/extensions/ReferenceBlock.tsx`
- `apps/web/components/console/editor/extensions/TaskBlock.tsx`
- `apps/web/components/console/editor/extensions/FlashcardBlock.tsx`
- `apps/api/alembic/versions/202604170001_notebook_attachment_meta.py`
- `apps/api/app/routers/attachments.py`
- `apps/api/tests/test_attachment_upload.py`
- `apps/api/tests/test_task_complete.py`
- `apps/web/tests/unit/block-schemas.test.ts`
- `apps/web/tests/s2-blocks.spec.ts`

### Modified files

- `apps/api/app/models/entities.py` (add `meta_json` to
  `NotebookAttachment`)
- `apps/api/app/routers/notebooks.py` (add upload + task-complete
  endpoints)
- `apps/api/app/main.py` (include new attachments router + ensure
  new bucket)
- `apps/api/app/core/config.py` (two new settings)
- `apps/web/components/console/editor/extensions/index.ts`
- `apps/web/components/console/editor/NoteEditor.tsx`
- `apps/web/components/console/editor/SlashCommandMenu.tsx`
- `apps/web/components/console/editor/AIPanel.tsx` (new
  `onInsertAIOutput` prop + Insert button)
- `apps/web/components/notebook/contents/ai-panel-tabs/AskTab.tsx`
  (pass prop through)
- `apps/web/styles/note-editor.css`
- `apps/web/messages/en/console-notebooks.json` +
  `apps/web/messages/zh/console-notebooks.json` (editor labels)

## 10. Acceptance Criteria

- `/` menu shows 19 commands including File, AI Output, Reference,
  Task, Flashcard.
- A file block can upload a PDF or PNG; after reload the embed
  renders again via a fresh presigned URL.
- An AI Panel streamed reply can be inserted as an `ai_output`
  block; the block shows the `action_type` badge and a "View trace"
  link.
- A reference block can be inserted via the picker dialog with
  Pages / Memory / Study Chunk tabs, each searchable.
- A task block's checkbox toggle produces an
  `AIActionLog(action_type="task.complete")` entry and the toggle
  persists across reload.
- A flashcard block renders in edit mode by default, flips to the
  back on click in preview mode.
- `pytest apps/api/tests/test_attachment_upload.py
  tests/test_task_complete.py` passes with ≥80% coverage on
  `routers/attachments.py` and the modified sections of
  `routers/notebooks.py`.
- `npm run test:unit` passes 10 new block-schema tests.
- `tests/s2-blocks.spec.ts` Playwright flashcard + task tests pass
  against a running stack.

## 11. Non-goals Re-stated

No `StudyCard` table, no `MemoryOutcome` writes, no auto-insertion
of AI blocks, no attachment delete, no mobile layout. Every deferral
has a pointer to the sub-project that owns it (S4 for cards, S5 for
outcomes).
