# S7 Search — Design Spec

**Date:** 2026-04-17
**Status:** approved
**Depends on:** S5 (feature/s5-proactive-services merged, commit `6638976`)

## 1. Goal

Add notebook-level, page-relative, and global search across the MRAI knowledge base, plus automated "related content" surfacing inside the NoteWindow. Deliver hybrid (lexical + semantic) retrieval for the five scopes spec'd in `MRAI_notebook_ai_os_build_spec.md §12.1`:

- **Pages** — notebook page titles and bodies
- **Blocks** — individual TipTap block plain text
- **Study assets** — uploaded PDFs / files + their extracted chunks
- **Memory** — the long-term memory graph (lexical + semantic, already wired)
- **Playbooks** — `memory_views` rows where `view_type == "playbook"`

Out of S7 scope (deferred to follow-up): **AI actions** search, **"问一句"** (that is reusable via existing `POST /api/v1/ai/notebook/ask`).

## 2. Endpoints

Three endpoints, same response shape except for `/related` which returns page-centered suggestions:

```
GET /api/v1/search/global
    ?q=<string, required, >=2 chars>
    &scope=<csv of "pages,blocks,study_assets,memory,playbooks", default=all>
    &project_id=<uuid, optional filter within current workspace>
    &limit=<int 1..20, default 8, per-scope>

GET /api/v1/notebooks/{notebook_id}/search
    ?q=... &scope=... &limit=...
    # Pages / Blocks / Study assets limited to the given notebook.
    # Memory / Playbooks limited to the notebook's parent project.

GET /api/v1/pages/{page_id}/related
    ?limit=<int 1..20, default 5>
    # Returns pages similar to this page + memory nodes sharing subjects.
```

### Response shape (search endpoints)

```json
{
  "query": "login flow",
  "duration_ms": 142,
  "results": {
    "pages": [
      { "id": "…", "notebook_id": "…", "title": "…",
        "snippet": "…", "score": 0.81, "source": "rrf" }
    ],
    "blocks": [
      { "id": "…", "page_id": "…", "notebook_id": "…",
        "snippet": "…", "score": 0.67, "source": "lexical" }
    ],
    "study_assets": [
      { "asset_id": "…", "chunk_id": "…|null", "notebook_id": "…",
        "title": "…", "snippet": "…", "score": 0.74, "source": "rrf" }
    ],
    "memory": [
      { "id": "…", "project_id": "…", "content": "…",
        "score": 0.79, "source": "rrf" }
    ],
    "playbooks": [
      { "memory_view_id": "…", "project_id": "…", "title": "…",
        "snippet": "…", "score": 0.62, "source": "lexical" }
    ]
  }
}
```

### Response shape (/related)

```json
{
  "pages": [
    { "id": "…", "notebook_id": "…", "title": "…",
      "score": 0.88, "reason": "semantic" },
    { "id": "…", "notebook_id": "…", "title": "…",
      "score": 0.71, "reason": "shared_subject" }
  ],
  "memory": [
    { "id": "…", "content": "…", "score": 0.66, "reason": "shared_subject" }
  ]
}
```

### Authz

- All three endpoints: `get_current_user` + `get_current_workspace_id` required (standard pattern).
- Cross-workspace access returns `404 not_found` (not 403 — avoid existence leak).
- No write scope; all endpoints are GET, CSRF not required.

## 3. Data model changes

| Table | Change |
|---|---|
| `notebook_pages` | `ADD COLUMN embedding_id VARCHAR(36) NULL` |
| new index | `CREATE INDEX ix_notebook_pages_embedding_id ON notebook_pages (embedding_id)` |
| new index | `CREATE INDEX ix_notebook_blocks_plain_text_trgm ON notebook_blocks USING GIN (plain_text gin_trgm_ops)` |

Alembic migration chained after current head (`202604200001`). Revision ID `202604210001`.

No new tables. No constraint changes.

## 4. Services

```
apps/api/app/services/
  search_dispatcher.py   ← orchestrates per-scope search, parallel
  search_rank.py         ← RRF (Reciprocal Rank Fusion) merge
  related_pages.py       ← page → related pages/memory
```

### 4.1 `search_dispatcher.py`

Single entry point:

```python
async def search_workspace(
    db: Session,
    *,
    workspace_id: str,
    query: str,
    scopes: set[str],
    project_id: str | None = None,
    notebook_id: str | None = None,
    limit: int = 8,
) -> dict[str, list[Hit]]
```

- Query shorter than 2 chars → return all-empty dict, skip DB.
- Dispatches to 5 scope-specific coroutines, `asyncio.gather(..., return_exceptions=True)`.
- Each scope's coroutine failure logs a warning and yields an empty list; the whole response is not failed by one scope.
- `notebook_id` given: Pages/Blocks/Study-assets limited to that notebook, Memory/Playbooks limited to the notebook's parent project.
- `project_id` given (without notebook_id): all scopes limited to that project.
- Neither given: workspace-wide.

### 4.2 Per-scope search functions

| Scope | Lexical | Semantic | Merge |
|---|---|---|---|
| Pages | `notebook_pages.plain_text` via `similarity(plain_text, q) >= 0.2` (pg_trgm) + ILIKE fallback | `vector_store.search_similar(query_embedding, owner_kind="notebook_page")` | RRF k=60 |
| Blocks | `notebook_blocks.plain_text` trgm similarity | — | lexical only |
| Study assets | `study_assets.title / summary_text` ILIKE + `study_chunks.plain_text` trgm | `vector_store.search_similar(..., owner_kind="study_chunk")` | RRF k=60 |
| Memory | `services.memory_v2.search_memories_lexical` (already exists) | `services.embedding.search_similar(..., owner_kind="memory")` (already exists) | RRF k=60 |
| Playbooks | `services.memory_v2.search_memory_views_lexical(view_type="playbook")` | — | lexical only |

All search functions return `list[Hit]` where `Hit` is a TypedDict containing at minimum `{id, score, snippet, source, ...per-scope fields}`. Limit is respected per-scope.

### 4.3 `search_rank.py`

```python
def rrf_merge(
    *rank_lists: list[Hit],
    k: int = 60,
    limit: int = 20,
) -> list[Hit]
```

Standard RRF: for each hit `h`, `fused_score(h) = Σ_i 1 / (k + rank_i(h))` where `rank_i(h)` is its 1-based rank in list `i` (absent = no contribution). Sort desc by fused score, truncate to `limit`. Hits are identified by `(scope, id)` tuple.

### 4.4 `related_pages.py`

```python
def get_related(
    db: Session,
    *,
    page_id: str,
    workspace_id: str,
    limit: int = 5,
) -> dict[str, list[Hit]]
```

- Load target page + its `embedding_id`. If no embedding, fall back to shared-subject only.
- **Semantic branch:** query pgvector for k-NN against the target page's embedding, filter to same workspace, exclude self.
- **Shared-subject branch:** look up memories linked to the page via the `MemoryEpisode` chain — `notebook_pages.id` ← `memory_episodes.source_id` (where `memory_episodes.source_type = 'notebook_page'`) ← `memory_evidences.episode_id` → `memory_evidences.memory_id` (the shared subject). For each shared memory, find other pages whose episodes also carry that memory. Score = number of shared subjects / max observed.
- Merge: pages appearing in both get `reason: "semantic"` (stronger signal wins). Pages only in shared-subject get `reason: "shared_subject"`.
- Memory branch: memories directly connected to the page (1-hop evidence), sorted by `Memory.confidence` desc.

## 5. Page embedding maintenance

### 5.1 Backfill task

```python
# apps/api/app/tasks/worker_tasks.py
@celery_app.task(name="app.tasks.worker_tasks.backfill_notebook_page_embeddings")
def backfill_notebook_page_embeddings_task(
    workspace_id: str | None = None,
    batch_size: int = 50,
) -> dict[str, int]
```

- Iterates `notebook_pages WHERE embedding_id IS NULL AND plain_text IS NOT NULL AND length(plain_text) >= 20`.
- If `workspace_id` given, scope to that workspace (for manual re-runs).
- For each page: `embed_and_store(plain_text, owner_kind="notebook_page", owner_id=page.id)` → set `page.embedding_id` → commit.
- Idempotent (only touches NULL rows). Returns `{total_processed, succeeded, failed}`.

### 5.2 Incremental hook

Hook into the existing `note_memory_bridge.py` page-save pipeline. On page save where `plain_text` has changed and its length ≥ 20:
- Enqueue `regenerate_notebook_page_embedding.delay(page.id)`.
- Task re-runs `embed_and_store` and overwrites `page.embedding_id`. Previous embedding row is left in place (pgvector cleanup is out of scope — the embedding table has enough space for mild churn).

### 5.3 Beat schedule (optional safety net)

```python
"backfill-notebook-page-embeddings-nightly": {
    "task": "app.tasks.worker_tasks.backfill_notebook_page_embeddings",
    "schedule": crontab(hour=4, minute=0),
}
```

Catches any page that slipped through the incremental hook (e.g., Celery down at save time). Not the primary maintenance path.

## 6. Frontend

### 6.1 WindowType "search"

- New type in `WindowManager.tsx` `WindowType` union and `DEFAULT_SIZES` (`search: { width: 680, height: 720 }`, single-open).
- Icon `Search` from `lucide-react` in `Window.tsx` `WINDOW_ICONS` + `MinimizedTray.tsx` `TRAY_ICONS`.
- `WindowCanvas.tsx` switch dispatches `case "search"` → `<SearchWindow notebookId={…} projectId={…} />`.

### 6.2 Sidebar tab

`NotebookSidebar.tsx`:
- Extend `SideTab` union to include `"search"`.
- Add `{ id: "search" as const, Icon: Search, key: "nav.search" }` to `TABS` (inserted between `pages` and `ai_panel`, so it's visually prominent).
- `handleTabClick` new `"search"` branch: `openWindow({ type: "search", title: tn("search.windowTitle"), meta: { notebookId } })`.

### 6.3 SearchWindow

`apps/web/components/notebook/contents/SearchWindow.tsx`:
- Top: `<input>` with placeholder `tn("search.placeholder")`, autofocus on mount.
- Body: 5 `<SearchResultsGroup>` sections (Pages, Blocks, Study assets, Memory, Playbooks), each scrollable list.
- Empty query → show placeholder text.
- Loading state → `<p>Searching…</p>` below input.
- Click on a result:
  - Pages / Blocks → `openWindow({ type: "note", meta: { pageId, notebookId } })`
  - Study asset → `openWindow({ type: "study", meta: { notebookId } })` (user continues from there)
  - Memory / Playbook → `openWindow({ type: "memory", meta: { notebookId, memoryId } })`

### 6.4 RelatedPagesCard

`apps/web/components/notebook/contents/search/RelatedPagesCard.tsx`:
- Collapsed by default, renders under NoteWindow body.
- Fetches on page mount + on pageId change via `useRelatedPages(pageId)` hook.
- Empty state hidden (no card rendered if no results).
- Click item → `openWindow({ type: "note", meta: { pageId, notebookId } })`.

### 6.5 Hooks

```
apps/web/hooks/useSearch.ts          ← debounced (300ms) query fetch + abort-on-retype
apps/web/hooks/useRelatedPages.ts    ← simple fetch-once per page
```

### 6.6 i18n keys

- `apps/web/messages/en/console.json` + `zh/console.json`: add `nav.search`.
- `apps/web/messages/en/console-notebooks.json` + `zh/console-notebooks.json`:
  - `search.windowTitle`
  - `search.placeholder`
  - `search.emptyResults`
  - `search.groupPages`, `search.groupBlocks`, `search.groupStudyAssets`, `search.groupMemory`, `search.groupPlaybooks`
  - `search.relatedHeading`

## 7. Error handling

| Condition | Behavior |
|---|---|
| Query `< 2` characters | Return empty result set; skip all DB calls |
| One scope's search raises | Log warning, that scope returns `[]`, other scopes succeed |
| Embedding service unavailable (pgvector error) | Semantic branch silently skipped, lexical-only returned |
| User not member of workspace | 404 not_found |
| `/related` on a page without `plain_text` / embedding | Return only shared-subject results (possibly empty), 200 OK |
| Invalid `scope=` CSV value | Return 400 `invalid_input` with list of valid scope names |
| `limit` out of range | Clamp to [1, 20] silently (match spec pattern from S5) |

## 8. Tests

### 8.1 Backend

| File | Cases |
|---|---|
| `tests/test_search_dispatcher.py` | per-scope dispatch + scope filter + notebook_id vs project_id scoping + one scope fails others survive + query too short |
| `tests/test_search_rank.py` | RRF math: single-list passthrough, two-list merge, tie-breaking, limit truncation |
| `tests/test_related_pages.py` | semantic only, shared-subject only, both (semantic wins reason), page with no plain_text |
| `tests/test_search_api.py` | 3 endpoints: 200 happy path, scope csv filter, cross-workspace 404, q too short returns empty, invalid scope returns 400 |
| `tests/test_notebook_page_embedding_backfill.py` | idempotent re-run, batch_size respected, skip pages with short plain_text, workspace filter |

Target coverage ≥ 80% on `search_dispatcher.py`, `search_rank.py`, `related_pages.py`.

### 8.2 Frontend

| File | Cases |
|---|---|
| `tests/unit/search-window.test.tsx` | input renders, mocked API returns populate 5 groups, empty state, group click dispatches `openWindow` |
| `tests/unit/related-pages-card.test.tsx` | renders items + empty state collapses |
| `tests/unit/use-search.test.ts` | debounce, abort on re-type |
| `tests/s7-search.spec.ts` | Playwright smoke: sidebar Search icon → SearchWindow opens → type query → click result → note window open |

## 9. Scope boundaries

**Explicitly in S7:**
- 5 scopes (Pages / Blocks / Study assets / Memory / Playbooks)
- 3 endpoints (global + notebook + /related)
- SearchWindow + sidebar tab + RelatedPagesCard
- NotebookPage embedding column + backfill + incremental hook

**Explicitly out of S7** (follow-up):
- AI actions search (spec §12.1 mentions "recent AI actions" — not MVP-critical)
- "问一句" search as a distinct endpoint (user reuses existing `/ai/notebook/ask`)
- Cmd+K global palette (can layer on later — backend will already support it)
- Block-level embedding (blocks use lexical only; page-level embedding is enough to find the right page)
- Cross-workspace search (workspace is the hard privacy boundary)
- Advanced filters (date range, author, block type) — add when user demand signals it

## 10. Phasing outline (for plan)

| Phase | Focus |
|---|---|
| A | Alembic migration + new indexes |
| B | `search_rank.py` RRF + unit tests |
| C | 5 per-scope search functions in `search_dispatcher.py` |
| D | `related_pages.py` service |
| E | Backfill task + incremental hook + beat schedule |
| F | 3 API endpoints |
| G | Backend regression + coverage |
| H | WindowType "search" plumbing |
| I | SearchWindow + SearchResultsGroup |
| J | Sidebar Search tab + `nav.search` i18n |
| K | RelatedPagesCard + NoteWindow integration |
| L | Playwright smoke + vitest unit tests |
| M | Final coverage verification |

## 11. References

- Product spec: `MRAI_notebook_ai_os_build_spec.md` §12 (搜索系统), §13.6 (Search API)
- Predecessors (merged to `main`):
  - S1 AIActionLog + action_log_context (shared infra)
  - S2 Block extensions (provides NotebookBlock model)
  - S3 AI Panel tabs (WindowManagerProvider pattern)
  - S4 Study Closure (provides StudyAsset / StudyChunk models + embedding already wired)
  - S5 Proactive Services (merge commit `6638976`)
- Existing infra to reuse:
  - `app/services/embedding.py` — `embed_and_store`, pgvector store
  - `app/services/memory_v2.py` — `search_memories_lexical`, `search_memories_semantic`, `search_memory_views_lexical`
  - `app/services/retrieval_orchestration.py` — shares philosophy; S7 is a sibling service, not an extension
