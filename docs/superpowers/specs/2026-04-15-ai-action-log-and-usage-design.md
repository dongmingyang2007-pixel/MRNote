# S1 — AI Action Log + Usage Event Foundation (Design)

Date: 2026-04-15
Status: Approved for implementation
Scope: Sub-project S1 of the MRAI notebook upgrade (see
`MRAI_notebook_ai_os_build_spec.md` §5.1.8, §15.7, §26).

## 1. Purpose

Add a durable audit and usage-metering layer beneath every notebook AI
operation so that:

- Every call to the `/api/v1/ai/notebook/*` endpoints produces a single
  trace record (`AIActionLog`) describing what the user asked, what the
  model returned, how long it took, and whether it succeeded.
- Each action can emit one or more atomic billable measurements
  (`AIUsageEvent`) suitable for a future monthly rollup and Stripe
  metering.
- Users can inspect the AI history of any page via a new page-level
  endpoint.

This lays the foundation that S4 (study), S5 (proactive services), and
S6 (billing) all depend on. Spec §26 makes action logging a hard
engineering constraint.

## 2. Scope

### In scope

- 4 notebook AI endpoints:
  - `POST /api/v1/ai/notebook/selection-action`
  - `POST /api/v1/ai/notebook/page-action`
  - `POST /api/v1/ai/notebook/ask`
  - `POST /api/v1/ai/notebook/whiteboard-summarize`
- New tables `ai_action_logs` and `ai_usage_events` with Alembic
  migration.
- `action_log_context` async context manager for endpoint integration.
- MinIO overflow bucket for large input/output payloads.
- Page-level retrieval endpoint `GET /pages/{id}/ai-actions` plus a
  single-action detail endpoint.
- Automated test coverage ≥80% on the new code (unit, API, Playwright
  smoke).

### Out of scope (explicit)

- Chat path (`/api/v1/chat/*`).
- Celery AI tasks (unified memory pipeline, study ingest,
  whiteboard Celery extraction).
- Non-AI usage events (file parsing, embedding batches, ASR).
- Global "My AI history" UI — deferred until S2/S3.
- `usage_rollup_task` — deferred to S5.
- Feature flag — audit logs are unconditional.

## 3. Data Model

### 3.1 `ai_action_logs`

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
    # TipTap blocks are not DB rows; keep as free string.
    block_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    action_type: Mapped[str] = mapped_column(String(60), nullable=False)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="running", nullable=False
    )
    model_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    input_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    output_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    output_summary: Mapped[str] = mapped_column(Text, default="", nullable=False)

    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    trace_metadata: Mapped[dict] = mapped_column(
        JSON, default=dict, nullable=False
    )
```

Indexes:
- `ix_ai_action_logs_workspace_created` on `(workspace_id, created_at DESC)`
- `ix_ai_action_logs_page_created` on `(page_id, created_at DESC)`
- `ix_ai_action_logs_user_created` on `(user_id, created_at DESC)`

`action_type` values follow the pattern `<surface>.<verb>`:
- `selection.rewrite`, `selection.summarize`, `selection.translate_en`, …
- `page.summarize`, `page.outline`, `page.find_todos`, `page.tag`,
  `page.brainstorm`
- `ask`
- `whiteboard.summarize`

`scope` values: `selection | page | notebook | project | user_memory |
study_asset | web` (matches spec §8.1).

### 3.2 `ai_usage_events`

```python
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
    audio_seconds: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    file_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    count_source: Mapped[str] = mapped_column(
        String(10), default="exact", nullable=False
    )
    meta_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
```

`event_type`: `llm_completion | embedding | asr | tts | file_ingest`.
For S1 only `llm_completion` is produced (embedding / ASR are emitted by
out-of-scope paths today).

`count_source`: `exact` when Dashscope returned a `usage` object;
`estimated` when char-count fallback was used.

Indexes:
- `ix_ai_usage_events_workspace_created` on
  `(workspace_id, created_at DESC)`
- `ix_ai_usage_events_action` on `(action_log_id)`

Note: `total_tokens` is stored rather than computed in SQL to keep
SQLite-compatibility (the project supports SQLite for tests).

## 4. Service API

New file: `apps/api/app/services/ai_action_logger.py`.

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
) -> AsyncIterator["ActionLogHandle"]:
    ...
```

`ActionLogHandle` public methods:

| Method | Effect |
|---|---|
| `set_input(payload: dict)` | Serializes, truncates to 10 KB, offloads overflow to MinIO. Stores `{"_overflow_ref": key, "_preview": "..."}` in `input_json` when overflowed. |
| `set_output(content: str \| dict)` | Same truncation policy; additionally fills `output_summary` with the first 200 chars (stripping markdown/whitespace). |
| `record_usage(event_type, model_id=None, prompt_tokens=0, completion_tokens=0, audio_seconds=0, file_count=0, count_source="exact", meta=None)` | Appends a `UsageEventBuffer` entry. Multiple calls allowed. |
| `set_trace_metadata(data: dict)` | Shallow-merges into `trace_metadata` (last-write-wins per key). |

Public attributes:
- `log_id: str` — primary-key of the created row (empty string on
  `NullActionLogHandle`).
- `is_null: bool` — `True` on the null handle, for callers that want to
  skip work.

### 4.1 Lifecycle

1. **Enter** — INSERT one row into `ai_action_logs` with
   `status="running"`, `input_json={}`, and commit. The handle carries
   the `log_id`, the start timestamp, and an empty usage buffer.
2. **Body** — caller populates input, streams LLM response, records
   usage. Nothing is written to the DB mid-stream.
3. **Exit (normal)** — UPDATE the log row (`status="completed"`,
   `duration_ms`, `output_json`, `output_summary`, `model_id`,
   `trace_metadata`), INSERT buffered usage rows, COMMIT.
4. **Exit (exception)** — UPDATE with `status="failed"`,
   `error_code`, `error_message`, commit; **then re-raise** so the
   endpoint's own error handler still runs.
5. **Exit (DB failure during flush)** — swallow, log at ERROR, bump a
   `runtime_state` counter `ai_action_log.flush_failures`. Never
   propagate.
6. **Enter failure (DB down)** — return a `NullActionLogHandle` whose
   methods are no-ops. The SSE response proceeds normally.

### 4.2 MinIO overflow

- Bucket name: `ai-action-payloads`. Added as a new setting
  `settings.s3_ai_action_payloads_bucket` defaulting to that string.
- Uses the existing `get_s3_client()` from
  `app/services/storage.py` directly (`put_object`, `get_object`,
  `head_bucket`, `create_bucket`). No new service module.
- Bucket is ensured on first write via `_ensure_bucket()` (HEAD then
  CREATE on `404`/`NoSuchBucket`). The lifespan hook also attempts a
  best-effort create so the bucket is ready before requests arrive.
- Key format: `{workspace_id}/{YYYY-MM-DD}/{log_id}-{field}.json` where
  `field ∈ {input, output}`.
- Threshold: `len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))`
  > 10 KB.
- Stored value in the DB column:
  `{"_overflow_ref": "<object_key>", "_preview": "<first-500-chars>"}`.
- Upload uses `put_object(Body=..., ContentType="application/json")`.
- Deletion: piggyback on the existing `cleanup_deleted_project` /
  workspace cleanup by adding `ai-action-payloads` to its bucket list
  (updated in this same PR series; the cleanup function already
  iterates bucket names).

## 5. Endpoint Integration

Each of the 4 endpoints in `apps/api/app/routers/notebook_ai.py` is
wrapped so the entire SSE generator runs inside `action_log_context`:

```python
@router.post("/selection-action")
async def selection_action(...):
    ...
    async def _generate():
        async with action_log_context(
            db,
            workspace_id=workspace_id,
            user_id=current_user.id,
            action_type=f"selection.{action_type}",
            scope="selection",
            notebook_id=notebook.id if notebook else None,
            page_id=page.id,
            block_id=payload.get("block_id"),
        ) as log:
            log.set_input({"selected_text": selected_text, "action_type": action_type})
            full_content = ""
            last_usage: dict | None = None
            try:
                yield _sse("message_start", {"action_log_id": log.log_id})
                async for chunk in chat_completion_stream(messages, ...):
                    if chunk.content:
                        full_content += chunk.content
                        yield _sse("token", {...})
                    if chunk.usage:
                        last_usage = chunk.usage
                log.set_output(full_content)
                log.record_usage(
                    event_type="llm_completion",
                    model_id=chunk.model_id,
                    prompt_tokens=(last_usage or {}).get("prompt_tokens")
                        or _estimate_tokens(prompt),
                    completion_tokens=(last_usage or {}).get("completion_tokens")
                        or _estimate_tokens(full_content),
                    count_source="exact" if last_usage else "estimated",
                )
                yield _sse("message_done", {...})
            except Exception as exc:
                yield _sse("error", {"message": str(exc)})
                raise
    return StreamingResponse(_generate(), ...)
```

### 5.1 Action-type mapping

| Endpoint | `action_type` | `scope` |
|---|---|---|
| `/selection-action` | `selection.{rewrite\|summarize\|...}` (from payload) | `selection` |
| `/page-action` | `page.{summarize\|outline\|...}` | `page` |
| `/ask` | `ask` | `notebook` when `retrieval_ctx.sources` includes at least one `related_page` or `document_chunk` source, else `page`. `retrieval_sources` list is always written to `trace_metadata`. |
| `/whiteboard-summarize` | `whiteboard.summarize` | `selection` |

### 5.2 Stream event additions

SSE responses include the new `action_log_id` in `message_start` so the
frontend can correlate or open a trace view later. This is additive;
existing consumers ignore unknown keys.

### 5.3 Token estimation fallback

```python
def _estimate_tokens(text: str) -> int:
    # Conservative 4 chars ≈ 1 token heuristic; minimum 1 so empty
    # strings don't record 0.
    if not text:
        return 0
    return max(1, len(text) // 4)
```

### 5.4 Dashscope stream usage capture

`apps/api/app/services/dashscope_stream.py` currently discards
usage-only chunks (the branch commented "Could be a usage-only chunk;
skip silently"). That branch is changed to:

1. Read `data.get("usage")`. If present, stash it in a local variable.
2. Read `data.get("model")`. If present, stash model name.
3. Continue the loop (do not yield yet — usage chunks have empty
   choices).

After the stream loop ends normally, yield one final
`StreamChunk(content="", usage=<captured or None>, model_id=<captured or
None>, finish_reason="stop")`. This gives callers one deterministic
"closing" chunk carrying usage.

Dataclass additions:

```python
@dataclass
class StreamChunk:
    content: str = ""
    reasoning_content: str = ""
    finish_reason: str | None = None
    search_sources: list[SearchSource] = field(default_factory=list)
    usage: dict | None = None       # new
    model_id: str | None = None     # new
```

Existing callers that ignore the new fields continue to work unchanged.
All existing content chunks have `usage=None`, `model_id=None`; only the
final synthetic chunk may carry them.

## 6. Retrieval API

```
GET /api/v1/pages/{page_id}/ai-actions?limit=50&cursor=<iso8601>
```

Response:
```json
{
  "items": [
    {
      "id": "<log_id>",
      "action_type": "selection.rewrite",
      "scope": "selection",
      "status": "completed",
      "model_id": "qwen-plus",
      "duration_ms": 1240,
      "output_summary": "改写后的版本...",
      "created_at": "2026-04-15T09:12:11Z",
      "usage": { "total_tokens": 834 }
    }
  ],
  "next_cursor": "2026-04-15T09:10:00Z"
}
```

Paging: cursor = `created_at` of the oldest item; `WHERE created_at <
cursor` + `ORDER BY created_at DESC` + `LIMIT :limit+1`. `limit` capped
at 100.

```
GET /api/v1/ai-actions/{log_id}
```

Full detail including dereferenced MinIO overflow (backend fetches and
inlines into the response). Access rules: the caller must (a) belong to
the log's workspace via `Membership`, and (b) either be the log's
`user_id` or hold `role="owner"` on that workspace. Both the list
endpoint and the detail endpoint also go through the existing
`get_current_workspace_id` dependency so workspace switching works.

## 7. Error Handling & Monitoring

- All DB writes inside the context manager are wrapped in `try/except`
  with `logger.exception` plus a counter bump on
  `runtime_state.metrics["ai_action_log.flush_failures"]`.
- Overflow upload failures fall back to storing the truncated payload
  inline (never block the request).
- Dashscope stream errors are caught by the outer endpoint; the context
  manager records `status=failed` with `error_code="stream_error"` and
  a truncated `error_message`.

## 8. Migration

File: `apps/api/alembic/versions/202604160001_ai_action_log.py`

Creates both tables with all indexes. `downgrade` drops tables. The
test environment uses `Base.metadata.create_all` via the existing
direct-schema-bootstrap path and therefore does not need explicit
migration code.

## 9. Testing Strategy

Target: ≥80% line coverage on the four new/modified modules:
- `services/ai_action_logger.py`
- `routers/notebook_ai.py` (the logged branches)
- `routers/ai_actions.py` (new retrieval router)
- `services/dashscope_stream.py` (only the new usage/model fields)

### 9.1 Unit — `tests/test_ai_action_logger.py`

| # | Case | Asserts |
|---|---|---|
| 1 | Normal enter/exit → log row with `status=completed`, `duration_ms>0` | row exists, fields set |
| 2 | Exception inside body → `status=failed`, error fields set, raised | raised, fields set |
| 3 | `record_usage` once → 1 usage row with `count_source=exact` | 1 row, correct columns |
| 4 | `record_usage` twice → 2 usage rows | 2 rows |
| 5 | `record_usage` with no exact usage → `count_source=estimated` | estimated flag |
| 6 | `set_input` with >10 KB payload → MinIO object + `_overflow_ref` | object exists, column has ref |
| 7 | `set_output` with short string → `output_summary` truncated to 200 chars | summary length |
| 8 | DB down at enter → `NullActionLogHandle` (all no-ops) | no exception |
| 9 | DB down at flush → log error + counter bump, no exception | counter incremented |
| 10 | `set_trace_metadata` merges keys | merged dict |
| 11 | Concurrent `record_usage` from two tasks → both land | 2 rows |
| 12 | Token estimation on empty string | returns 0 |

### 9.2 API — `tests/test_notebook_ai_logging.py`

| # | Endpoint | Asserts |
|---|---|---|
| 1 | `/selection-action` | 1 action row with `action_type` prefix `selection.`, 1 usage row |
| 2 | `/page-action` | 1 action row `page.*`, 1 usage |
| 3 | `/ask` | trace_metadata has `retrieval_sources` when available |
| 4 | `/whiteboard-summarize` | 1 action row `whiteboard.summarize` |

Each test drives the endpoint via `TestClient` in non-stream collection
mode (drain SSE into text), then introspects `ai_action_logs` /
`ai_usage_events`.

### 9.3 API — `tests/test_ai_action_retrieval.py`

| # | Case | Asserts |
|---|---|---|
| 1 | list paged | returns 50, `next_cursor` non-null |
| 2 | list with cursor | second page does not overlap |
| 3 | list cross-workspace isolation | workspace B can't see workspace A logs |
| 4 | detail dereferences MinIO overflow | full payload returned |
| 5 | detail 404 on unknown id | 404 |
| 6 | detail 403 when accessed by non-creator non-owner | 403 |

### 9.4 Playwright — `apps/web/tests/notebook-ai-trace.spec.ts`

Single smoke test: open a page, run a selection rewrite, open the
(newly added) AI actions side panel, expect at least one entry with
the expected `action_type`.

### 9.5 Fixtures

Follow the existing pattern in
`apps/api/tests/test_api_integration.py`: a SQLite file DB is set up
via `DATABASE_URL` env override at import time, and
`Base.metadata.create_all(engine)` seeds the schema. The new test
modules add their own minimal setup (workspace, user, notebook, page)
via direct ORM inserts.

For MinIO we add a `FakeS3Client` class in
`apps/api/tests/fixtures/fake_s3.py` implementing exactly the boto3
methods the logger uses: `put_object`, `get_object`, `head_bucket`,
`create_bucket`. The fake is installed by monkey-patching
`app.services.storage.get_s3_client` (after clearing its
`lru_cache`). No new third-party dependency.

## 10. Frontend Surface (minimal for S1)

The Playwright test drives a minimal "AI actions" panel inside
`NoteEditor` — a list view backed by
`GET /pages/{id}/ai-actions`. Keep it behind an existing "Trace" tab
in the AI panel if the UI already has one; otherwise add a small list
element. No styling ambition; S3 will replace this with the
windowized AI panel.

## 11. Work Breakdown (for the implementation plan step)

Rough order, each item is independently testable:

1. Models + Alembic migration + ORM tests.
2. `_estimate_tokens` and the dashscope stream extension (usage +
   model_id).
3. `ai_action_logger.py` + unit tests (9.1).
4. MinIO fake fixture + overflow tests.
5. Router wiring in `notebook_ai.py` + API tests (9.2).
6. New `routers/ai_actions.py` for retrieval + tests (9.3).
7. `main.py` router registration + lifespan MinIO bucket init.
8. Minimal frontend panel + Playwright smoke.
9. Coverage check (`pytest --cov` against the four modules).

## 12. Acceptance Criteria

- `alembic upgrade head` creates `ai_action_logs` and `ai_usage_events`.
- All 4 notebook AI endpoints produce exactly one action log and at
  least one usage event per successful request.
- A stream error during `/ask` produces a log with `status=failed`
  and `error_code`.
- `GET /pages/{id}/ai-actions` returns only that page's logs,
  paginated.
- `pytest apps/api/tests/test_ai_action_*` passes with `pytest-cov`
  reporting ≥80% line coverage on the four modules (`ai_action_logger`,
  the logged branches of `notebook_ai`, the new `ai_actions` retrieval
  router, and the extended `dashscope_stream`). `pytest-cov>=6.0` is
  added to `apps/api/pyproject.toml` dev-dependencies.
- One Playwright smoke test passes.
- `scripts/dev.sh` still boots the full stack.

## 13. Non-goals Re-stated

Nothing in this spec establishes: a Stripe customer record, any pricing
math, chat-side logging, or a global UI surface for AI history. These
are later sub-projects.
