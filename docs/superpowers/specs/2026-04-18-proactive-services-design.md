# S5 — Proactive Services (Digests / Reflections / Reminders) — Design

Date: 2026-04-18
Status: Approved for implementation
Scope: Sub-project S5 of the MRAI notebook upgrade (see
`MRAI_notebook_ai_os_build_spec.md` §3.5, §14.4).

## 1. Purpose

Spec §3.5 promised seven proactive services:

1. 今日摘要 (today's summary)
2. 今日可推进的 next action
3. 本周重点 (this week's focus)
4. 卡点与复盘 (blockers + retrospective)
5. 学习回顾 (learning recap)
6. 关系提醒 / 目标偏航提醒 (relationship + goal-drift reminders)
7. 需要 reconfirm 的旧记忆提醒

Spec §14.4 explicitly requires two Celery tasks (`daily_notebook_digest_task`,
`weekly_notebook_reflection_task`) but leaves the rest implicit.

S5 ships the full list as **four `kind` rows under a single
`ProactiveDigest` table**, driven by two Celery beat entries (daily +
weekly) that fan-out per project. Users see results through a new
`digest` window type opened from a sidebar bell icon.

## 2. Scope

### In scope

- One new table `proactive_digests` with `kind` discriminator.
- Four `kind` values, two generation pipelines:
  - **Daily** cron → `daily_digest` rows (one per active project).
    Each row bundles today's summary + next actions + reconfirm items.
  - **Weekly** cron → `weekly_reflection` row per active project +
    0..N `deviation_reminder` rows (LLM-as-judge) + 0..N
    `relationship_reminder` rows (rule-based).
- Five Celery tasks (4 fan-outs + 1 per-project generator).
- `services/proactive_materials.py` collecting source material
  (AIActionLog / NotebookPage edits / Memory nodes / StudyCard
  review data from S4).
- `services/proactive_generator.py` containing per-kind LLM prompts
  and content_json assembly.
- 6 API endpoints (list / detail / read / dismiss / unread-count /
  generate-now).
- New `digest` WindowType + DigestWindow + DigestList + DigestDetail
  React components.
- Bell icon in notebook sidebar with unread-count badge.
- Tests: ≥80% coverage target on new Python modules, vitest +
  Playwright smoke for frontend.

### Out of scope (explicit)

- Email / push notifications (deferred to S5.1).
- Per-user timezone (digests run on a single UTC cron; the clock
  question comes up post-launch).
- Admin-scoped digests (workspace-level or org-level aggregation).
- Retroactive backfill of past periods (`generate-now` targets the
  current period only).
- Voice / TTS morning briefings.
- i18n — UI chrome uses English strings today; the LLM-generated
  body text naturally uses whatever language the input is in.
- Markdown-embedded interactive buttons — `next_actions` is rendered
  as a clickable list of links, not a "one-click complete".

## 3. Architecture

```
┌─ Celery Beat (07:03 daily, 08:07/12/17 weekly Mon) ──┐
│                                                       │
│  generate_daily_digests          ← 07:03              │
│  generate_weekly_reflections     ← Mon 08:07          │
│  generate_deviation_reminders    ← Mon 08:12          │
│  generate_relationship_reminders ← Mon 08:17          │
│                                                       │
└─── each one is a fan-out task ───┐                   │
                                   │                   │
                                   ▼                   │
                       for project in active_projects:│
                         enqueue                      │
                         generate_proactive_digest_task│
                         (project_id, kind, ...)      │
                                   │                  │
                                   ▼                  │
                         ┌─ collect_{kind}_materials ─┤
                         │                            │
                         ▼                            │
                    ┌─ build_prompt(materials)        │
                    │  + LLM call                    │
                    │  + parse content_json          │
                    │                                │
                    └─ INSERT ProactiveDigest row    │
                       (status="unread",             │
                        action_log_id=...)           │
                                                    ┘
┌─ User opens sidebar Bell icon ───┐
│                                  │
│  WindowManager.openWindow(       │
│    type="digest",                │
│    meta={ notebookId })           │
│                                  │
│  DigestWindow renders 3 tabs:    │
│    Today | Week | All            │
│                                  │
│  GET /api/v1/digests?...         │
│  POST /api/v1/digests/{id}/read  │
│                                  │
└──────────────────────────────────┘
```

## 4. Data Model

### 4.1 `proactive_digests`

```python
class ProactiveDigest(
    Base, UUIDPrimaryKeyMixin, TimestampMixin, UpdatedAtMixin,
):
    __tablename__ = "proactive_digests"

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
    # "daily_digest" | "weekly_reflection" | "deviation_reminder" |
    # "relationship_reminder"

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
    )  # "unread" | "read" | "dismissed"
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    dismissed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    model_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    action_log_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )  # → AIActionLog from S1
```

### 4.2 Indexes

- `ix_proactive_digests_user_status_created`
  `(user_id, status, created_at DESC)` — powers the sidebar unread
  count and the user's list view.
- `ix_proactive_digests_project_kind_period`
  `(project_id, kind, period_start DESC)` — makes the per-period
  idempotency check fast.
- Unique constraint:
  `uq_proactive_digests_project_kind_period_start`
  on `(project_id, kind, period_start)` — enforces idempotency at
  the DB layer so Celery retries cannot double-insert.

### 4.3 Alembic migration

`apps/api/alembic/versions/202604190001_proactive_digests.py`:

```sql
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

CREATE INDEX IF NOT EXISTS ix_proactive_digests_user_status_created
    ON proactive_digests(user_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_proactive_digests_project_kind_period
    ON proactive_digests(project_id, kind, period_start DESC);
```

Chain: `down_revision = "202604180001"` (S4).

## 5. content_json schemas

### 5.1 `daily_digest`

```json
{
  "summary_md": "3-5 sentence LLM recap of the last 24h",
  "next_actions": [
    {
      "page_id": "…",
      "title": "Page title",
      "hint": "One-line suggestion of what to do next"
    }
  ],
  "reconfirm_items": [
    {
      "memory_id": "…",
      "fact": "fact text",
      "age_days": 94,
      "reason": "stale"
    }
  ],
  "sources": {
    "action_log_ids": ["…"],
    "page_ids": ["…"]
  }
}
```

### 5.2 `weekly_reflection`

```json
{
  "summary_md": "…",
  "learning_recap_md": "…",
  "blockers_md": "…",
  "stats": {
    "action_count": 123,
    "cards_reviewed": 20,
    "pages_edited": 5,
    "confusions_logged": 2
  },
  "sources": { "action_log_ids": ["…"], "page_ids": ["…"] }
}
```

### 5.3 `deviation_reminder`

```json
{
  "goal_memory_id": "…",
  "goal_text": "build MVP by end of month",
  "drift_reason_md": "LLM judgment: …",
  "confidence": 0.7
}
```

One row per drifting goal. The LLM judge may return 0 items (no row
created) through 3 items (3 rows) per project.

### 5.4 `relationship_reminder`

```json
{
  "relationship_memory_id": "…",
  "person_label": "张三",
  "last_mention_at": "2026-03-01T…",
  "days_since": 47
}
```

One row per stale relationship (>30 days since last evidence).

## 6. Celery tasks

All live in `apps/api/app/tasks/worker_tasks.py`, routed to the
existing `memory` queue (via `celery_app.conf.task_routes`).

### 6.1 Fan-out tasks (called by beat)

```python
@celery_app.task(name="app.tasks.worker_tasks.generate_daily_digests")
def generate_daily_digests_task() -> dict[str, int]:
    """Iterate active projects, enqueue per-project daily digest jobs."""


@celery_app.task(name="app.tasks.worker_tasks.generate_weekly_reflections")
def generate_weekly_reflections_task() -> dict[str, int]: ...


@celery_app.task(name="app.tasks.worker_tasks.generate_deviation_reminders")
def generate_deviation_reminders_task() -> dict[str, int]: ...


@celery_app.task(name="app.tasks.worker_tasks.generate_relationship_reminders")
def generate_relationship_reminders_task() -> dict[str, int]: ...
```

**Active project** = a `Project` that had any `AIActionLog` or
`NotebookPage.updated_at` in the last 24 hours (daily) or last 7
days (weekly). Implementation is a single SQL query per fan-out.

Deviation and relationship tasks additionally filter to projects that
have at least one `Memory` row with matching `memory_kind` value in
their metadata — `memory_kind="goal"` for deviation,
`memory_kind="relationship"` for relationship.

### 6.2 Per-project generator

```python
@celery_app.task(name="app.tasks.worker_tasks.generate_proactive_digest")
def generate_proactive_digest_task(
    project_id: str,
    kind: str,
    period_start_iso: str,
    period_end_iso: str,
) -> str | None:
    """Generate one (or zero) ProactiveDigest row for this project+kind.

    For `deviation_reminder` and `relationship_reminder`, this task
    may insert multiple rows — one per detected item.

    Returns the digest id (or None if nothing was generated).
    """
```

Implementation outline:

1. Check idempotency: query
   `(project_id, kind, period_start)` → if exists, return early.
2. Load `project`, `workspace`, `creator_user`.
3. Call `collect_{kind}_materials(db, project_id, period_start,
   period_end)` → returns a dict.
4. If `materials` is empty (no activity), return None (no row).
5. Open `action_log_context("proactive.{kind}", scope="project")`.
6. Call `build_{kind}_prompt(materials)` → str prompt.
7. Call `chat_completion(prompt, ...)` (non-streaming; small JSON
   output).
8. Parse output; on JSON parse failure, log + record in
   `action_log.output_json.error`, return None.
9. For `deviation_reminder` / `relationship_reminder`, iterate items
   and insert one row each. Otherwise, insert a single row.
10. Each insert sets `action_log_id = log.log_id` for traceability.

### 6.3 Beat schedule additions

In `apps/api/app/tasks/celery_app.py`:

```python
celery_app.conf.beat_schedule = {
    # existing entries kept unchanged
    "purge-stale-records-daily": {...},
    "memory-sleep-cycle-nightly": {...},
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

Also add task routes:

```python
celery_app.conf.task_routes.update({
    "app.tasks.worker_tasks.generate_daily_digests": {"queue": "memory"},
    "app.tasks.worker_tasks.generate_weekly_reflections": {"queue": "memory"},
    "app.tasks.worker_tasks.generate_deviation_reminders": {"queue": "memory"},
    "app.tasks.worker_tasks.generate_relationship_reminders": {"queue": "memory"},
    "app.tasks.worker_tasks.generate_proactive_digest": {"queue": "memory"},
})
```

## 7. Source collection (`services/proactive_materials.py`)

New file. Four pure helpers that return structured dicts (no LLM
calls here — this is strictly data assembly for the prompt).

```python
def collect_daily_materials(
    db: Session, *, project_id: str, period_start: datetime, period_end: datetime,
) -> dict[str, Any]:
    """Return {action_counts, action_samples, page_edits, reconfirm_items}."""
    ...


def collect_weekly_materials(
    db: Session, *, project_id: str, period_start: datetime, period_end: datetime,
) -> dict[str, Any]:
    """Return {action_counts, action_samples, page_edits, study_stats, blocker_tasks}."""
    ...


def collect_goal_materials(
    db: Session, *, project_id: str, period_start: datetime, period_end: datetime,
) -> dict[str, Any]:
    """Return {goals: [...], activity_summary}."""
    ...


def collect_relationship_materials(
    db: Session, *, project_id: str,
) -> list[dict[str, Any]]:
    """Return a list of {relationship_memory, last_mention_at, days_since}
    for any relationship memory older than 30 days since its most
    recent evidence."""
    ...
```

### 7.1 Daily detail

- `action_counts`: SQL aggregate
  `SELECT action_type, COUNT(*) FROM ai_action_logs WHERE
  notebook_id IN (project's notebooks) AND created_at BETWEEN
  period_start AND period_end GROUP BY action_type`.
- `action_samples`: top 5 latest AIActionLog rows with
  `output_summary` (truncated to 200 chars).
- `page_edits`: `NotebookPage` rows with `updated_at` in window,
  limited to 10 most recent.
- `reconfirm_items`: reuse `memory_v2`'s existing "needs_reconfirm"
  logic. Currently that logic lives inline in the nightly sleep
  cycle (`memory_v2.py:894-920`) — it reads `reconfirm_after` and
  flags from each memory's `metadata_json` dict (no dedicated
  column). S5 **extracts** a reusable pure-function helper
  `find_reconfirm_candidates(db, project_id, *, limit=5, now=None)
  -> list[Memory]` at the top of `memory_v2.py` that returns at
  most `limit` memories matching either:
  - `metadata_json.get("reconfirm_after")` parses as ISO8601 and
    `<= now`, OR
  - `metadata_json.get("last_used_at")` is older than 90 days (or
    missing AND `created_at` older than 90 days).

  The sleep-cycle existing code then calls this helper; its
  behaviour must stay identical (covered by the existing
  `test_api_integration.py` regression tests — no new assertions
  needed, just the refactor).

### 7.2 Weekly detail

Same as daily but 7-day window, plus:
- `study_stats`: `StudyCard.review_count` sum + `lapse_count` sum +
  `confusion_memory_written_at IS NOT NULL` count across the
  project's notebooks' decks.
- `blocker_tasks`: AIActionLog rows with `action_type="task.reopen"`
  in the window, plus any `task.complete` that fired after 5+ days
  gap from the preceding `task.create` (heuristic — surface via
  block_id).

### 7.3 Goal detail

- `goals`: all `Memory` rows in the project filtered to
  `memory_kind == "goal"`. Use the existing `get_memory_kind(memory)`
  helper from `memory_v2` on Python side after loading (project
  memory counts are small enough to filter in-process; SQL-side
  filtering via `Memory.metadata_json["memory_kind"].as_string() ==
  "goal"` is the DB-agnostic alternative and works across Postgres
  and SQLite). Cap at 10 per project.
- `activity_summary`: compact 500-char text description of the
  week's activity (reuse daily `action_samples` idea with more
  entries).

### 7.4 Relationship detail

- Load project memories, filter to `memory_kind == "relationship"`
  via the `get_memory_kind(memory)` helper.
- For each, query `MemoryEvidence` ordered by `created_at DESC`
  limited to 1 (most recent).
- If `now - last_evidence.created_at > timedelta(days=30)`, include
  the item with `days_since` computed. If the memory has zero
  evidence, count it as stale with `days_since = None` and
  `last_mention_at = null` — the row still gets emitted.
- No LLM call; pure SQL + datetime math.

## 8. Prompt builders (`services/proactive_generator.py`)

One file. Four builder functions:

```python
def build_daily_prompt(materials: dict, project_name: str) -> tuple[str, str]:
    """Returns (system_prompt, user_prompt)."""


def build_weekly_prompt(materials: dict, project_name: str) -> tuple[str, str]: ...


def build_deviation_prompt(materials: dict, project_name: str) -> tuple[str, str]:
    """LLM returns strict JSON: {"drifts": [{"goal_memory_id","drift_reason_md","confidence"}, ...]}
    May return empty drifts list. System prompt explicitly instructs
    JSON-only output."""
```

(No prompt builder for relationship — that's pure rule-based.)

A single dispatch helper:

```python
async def generate_digest_content(
    *, kind: str, materials: dict, project_name: str,
) -> dict[str, Any]:
    """Call the right prompt + LLM, return the content_json dict.
    Raises ApiError("llm_bad_output") on parse failure."""
```

System prompts insist on JSON-only output for deviation (just like
S4 quiz / flashcards). For daily / weekly the LLM returns
markdown prose in a structured JSON wrapper.

## 9. API endpoints

New router `apps/api/app/routers/proactive.py` (prefix `/api/v1/digests`).

### 9.1 `GET /api/v1/digests`

Query params: `kind?`, `status?`, `limit=20`, `cursor?` (ISO8601).

Response:
```json
{
  "items": [
    {
      "id": "…",
      "kind": "daily_digest",
      "title": "Daily digest · 2026-04-18",
      "period_start": "2026-04-17T00:00:00Z",
      "period_end": "2026-04-18T00:00:00Z",
      "status": "unread",
      "created_at": "…"
    }
  ],
  "next_cursor": "…" | null,
  "unread_count": 3
}
```

Scoped to the caller's workspace via `get_current_workspace_id`.
`user_id` filter is implicit: only the caller's own digests.

### 9.2 `GET /api/v1/digests/{id}`

Full row including `content_markdown` and `content_json`. 404 on
cross-workspace access.

### 9.3 `POST /api/v1/digests/{id}/read`

Sets `status="read"`, `read_at=now()`. Idempotent: no-op if already
read.

### 9.4 `POST /api/v1/digests/{id}/dismiss`

Sets `status="dismissed"`, `dismissed_at=now()`. Idempotent.

### 9.5 `GET /api/v1/digests/unread-count`

```json
{ "unread_count": 3 }
```

Cheap — indexed query on `(user_id, status)`.

### 9.6 `POST /api/v1/digests/generate-now`

Body: `{ "kind": "daily_digest", "project_id": "…" }`. Immediately
enqueues `generate_proactive_digest_task.delay(project_id, kind,
…)` with the current period. Returns `{ "task_id": "…" }`. Used
by developers and admin tooling; gated behind
`require_workspace_write_access` + CSRF.

## 10. Frontend

### 10.1 WindowType extension

`components/notebook/WindowManager.tsx`:

```ts
export type WindowType =
  "note" | "ai_panel" | "file" | "memory" | "study" | "digest";
```

`DEFAULT_SIZES["digest"] = { width: 520, height: 620 }`.
`supportsMultiOpen` stays `["note", "file", "ai_panel"]` — one
digest window per notebook is enough.

`Window.tsx` and `MinimizedTray.tsx` icon maps gain
`digest: Bell`.

`WindowCanvas.tsx` adds a dispatch case that renders
`<DigestWindow notebookId={windowState.meta.notebookId ?? ""} />`.

### 10.2 `DigestWindow.tsx`

Three-tab shell (matches AI Panel / Study Window patterns):

```
┌─ Digest ────────────────────┐
│ Today | This week | All      │
├──────────────────────────────┤
│ <DigestList status=unread>    │
│   one card per digest         │
│   click → DigestDetail        │
└──────────────────────────────┘
```

Tabs filter by `kind` / `status`:

- **Today**: `kind=daily_digest`, sorted by `created_at DESC`, last
  7 days.
- **This week**: `kind=weekly_reflection`, latest only.
- **All**: everything in workspace, mixed. `deviation_reminder` and
  `relationship_reminder` only surface here (they're too small to
  justify own tabs).

### 10.3 `DigestList.tsx`

A list component keyed by digest id. Each row shows:
- Bell / Flag / Users icon (by kind)
- Title + relative time
- Two-line truncated `content_markdown.slice(0,140)`
- Bullet if `status=unread`
- Row click opens `DigestDetail` overlay

### 10.4 `DigestDetail.tsx`

Markdown render of `content_markdown`. For structured fields:
- `daily_digest.next_actions` → clickable list; each item opens the
  page in a note window (reuse `useWindowManager`).
- `daily_digest.reconfirm_items` → link to the memory window
  anchored at that memory id.
- `deviation_reminder` / `relationship_reminder` → link to the
  referenced memory.

Clicking anywhere in the detail auto-sets `status=read` via
`POST /{id}/read` (debounced 500ms to avoid flicker).

"Dismiss" button on the detail header calls
`POST /{id}/dismiss` and closes the overlay.

### 10.5 Sidebar Bell

`components/console/NotebookSidebar.tsx`:

Extend the `type SideTab` union (line 19) and the `TABS` array
(line 25). Current shape:

```ts
type SideTab = "pages" | "ai_panel" | "memory" | "learn" | null;

const TABS = [
  { id: "pages" as const, Icon: FileText, key: "nav.pages" },
  { id: "ai_panel" as const, Icon: Sparkles, key: "nav.aiPanel" },
  { id: "memory" as const, Icon: Brain, key: "nav.memory" },
  { id: "learn" as const, Icon: BookOpen, key: "nav.learn" },
] as const;
```

Change to:

```ts
type SideTab = "pages" | "ai_panel" | "memory" | "learn" | "digest" | null;

const TABS = [
  { id: "pages" as const, Icon: FileText, key: "nav.pages" },
  { id: "ai_panel" as const, Icon: Sparkles, key: "nav.aiPanel" },
  { id: "memory" as const, Icon: Brain, key: "nav.memory" },
  { id: "learn" as const, Icon: BookOpen, key: "nav.learn" },
  { id: "digest" as const, Icon: Bell, key: "nav.digest" },
] as const;
```

Add the `Bell` import from `lucide-react`. Extend `handleTabClick`
with a `"digest"` branch:

```ts
if (tabId === "digest") {
  openWindow({
    type: "digest",
    title: tn("digest.windowTitle"),
    meta: { notebookId },
  });
  return;
}
```

Add a new i18n key `"nav.digest": "Digest"` (en) /
`"nav.digest": "摘要"` (zh) to the relevant messages file — same
one where `nav.aiPanel` lives today (`console-notebooks.json`
from memory).

The bell icon renders an unread-count badge (small red circle with
number). The count is managed by a new hook
`useDigestUnreadCount()`:

```ts
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
      } catch { /* swallow */ }
    }
    void tick();
    const h = setInterval(tick, 30_000);
    return () => { cancelled = true; clearInterval(h); };
  }, []);
  return count;
}
```

30-second polling. No websocket needed for MVP.

## 11. Error handling

- **LLM parse failure** — `generate_proactive_digest_task` logs the
  error to the enclosing `action_log_context` (status=failed,
  error_code="llm_bad_output"), does **not** insert a row. Cron
  will re-attempt next period.
- **Empty materials** — skip with a noted "no_activity" outcome in
  the action log's `output_json`. Row not inserted.
- **Unique constraint violation** — rare but possible under Celery
  retries. Catch `IntegrityError`, log, return early. The existing
  row stays authoritative.
- **Celery worker crash mid-task** — next beat iteration re-enqueues.
  No partial writes because the row is inserted only at the end of
  the pipeline.
- **User deleted while digest exists** — FK cascade deletes the row.
- **Project deleted** — same. `cleanup_deleted_project` doesn't need
  a new case because the cascade covers it.

## 12. Testing strategy

Target ≥80% line coverage on new Python modules:
`models.entities.ProactiveDigest`, `routers.proactive`,
`services.proactive_materials`, `services.proactive_generator`,
the 5 new tasks in `tasks.worker_tasks`.

### 12.1 Backend unit + API tests

- `tests/test_proactive_models.py` (1 test) — ORM roundtrip +
  unique constraint.
- `tests/test_proactive_materials.py` (8 tests, 2 per collector) —
  with data / empty project / cross-window filtering / memory_kind
  filter.
- `tests/test_proactive_generator.py` (4 tests) — per kind, with
  mocked LLM returning canned JSON, assert content_json shape.
- `tests/test_proactive_celery.py` (5 tests) — fan-out tasks
  enqueue the expected number of per-project jobs; idempotency on
  second call produces no duplicates; deviation returns 0 drifts →
  0 rows; relationship stale-detection cases.
- `tests/test_proactive_api.py` (7 tests) — list / detail / read /
  dismiss / unread-count / cross-workspace 404 / generate-now.

### 12.2 Frontend unit

- `tests/unit/digest-list.test.tsx` (vitest) — renders N items,
  shows unread dot, formats relative time.

### 12.3 Playwright smoke

`tests/s5-digest.spec.ts` (1 test) — seed one `ProactiveDigest`
row via a direct API `POST /digests/generate-now`, open sidebar
Bell, see badge, click, see detail, click Dismiss, expect badge
zero.

## 13. File plan

### New files

- `apps/api/app/models/entities.py` (append `ProactiveDigest`)
- `apps/api/app/models/__init__.py` (export)
- `apps/api/alembic/versions/202604190001_proactive_digests.py`
- `apps/api/app/schemas/proactive.py`
- `apps/api/app/services/proactive_materials.py`
- `apps/api/app/services/proactive_generator.py`
- `apps/api/app/routers/proactive.py`
- `apps/api/tests/test_proactive_models.py`
- `apps/api/tests/test_proactive_materials.py`
- `apps/api/tests/test_proactive_generator.py`
- `apps/api/tests/test_proactive_celery.py`
- `apps/api/tests/test_proactive_api.py`
- `apps/web/components/notebook/contents/DigestWindow.tsx`
- `apps/web/components/notebook/contents/digest/DigestList.tsx`
- `apps/web/components/notebook/contents/digest/DigestDetail.tsx`
- `apps/web/hooks/useDigestUnreadCount.ts`
- `apps/web/styles/digest-window.css`
- `apps/web/tests/unit/digest-list.test.tsx`
- `apps/web/tests/s5-digest.spec.ts`

### Modified files

- `apps/api/app/tasks/celery_app.py` (beat_schedule + task_routes)
- `apps/api/app/tasks/worker_tasks.py` (5 new tasks)
- `apps/api/app/main.py` (register proactive router)
- `apps/api/app/services/memory_v2.py` (extract
  `find_reconfirm_candidates` helper — lightweight refactor of
  existing logic)
- `apps/web/components/notebook/WindowManager.tsx` (WindowType +
  DEFAULT_SIZES)
- `apps/web/components/notebook/Window.tsx` (icon map)
- `apps/web/components/notebook/MinimizedTray.tsx` (icon map)
- `apps/web/components/notebook/WindowCanvas.tsx` (DigestWindow
  dispatch)
- `apps/web/components/console/NotebookSidebar.tsx` (Bell tab +
  unread badge)
- `apps/web/app/[locale]/workspace/notebooks/[notebookId]/layout.tsx`
  (import digest-window.css)

## 14. Phase layout (for `writing-plans`)

| Phase | Tasks | Description |
|---|---|---|
| **A** | T1 | `ProactiveDigest` model + migration + Pydantic schemas + ORM smoke |
| **B** | T2–T3 | `proactive_materials` (4 collectors + `find_reconfirm_candidates` extract) + 8 tests |
| **C** | T4 | `proactive_generator` (4 prompts + dispatch) + 4 tests |
| **D** | T5–T6 | 5 Celery tasks + beat schedule + 5 tests |
| **E** | T7 | 6 API endpoints + 7 tests |
| **F** | T8 | Register router in main.py + final backend verification run |
| **G** | T9 | WindowType extension + WindowManager / Window / MinimizedTray / WindowCanvas plumbing |
| **H** | T10–T11 | DigestWindow + DigestList + DigestDetail components |
| **I** | T12 | Sidebar Bell + `useDigestUnreadCount` hook + badge |
| **J** | T13 | i18n strings (minimal — nav.digest label; rest deliberately English) + CSS |
| **K** | T14 | Playwright smoke + vitest unit + final coverage verification |

Approximately 14 atomic commits.

## 15. Acceptance criteria

- `alembic upgrade head` creates `proactive_digests` with unique
  constraint and two indexes.
- `POST /api/v1/digests/generate-now` with `kind="daily_digest"` and
  a project_id that had a recent AIActionLog produces one row
  immediately.
- Running `generate_daily_digests_task` manually (via
  `celery call …`) fans out to all active projects; running again
  in the same hour produces **zero additional rows** (idempotency).
- Running `generate_weekly_reflections_task` on a project with
  study_cards reviewed produces a `weekly_reflection` row whose
  `content_json.stats.cards_reviewed > 0`.
- Running `generate_deviation_reminders_task` on a project with
  at least one goal memory and a canned LLM response of
  `{"drifts":[{"goal_memory_id":"…","drift_reason_md":"…",
  "confidence":0.7}]}` produces one `deviation_reminder` row.
- Running `generate_relationship_reminders_task` on a project with
  a relationship memory whose latest evidence is 40 days old
  produces one `relationship_reminder` row.
- Sidebar Bell icon shows unread count; clicking opens
  `DigestWindow`; opening a digest sets status=read; dismiss
  works.
- All `proactive.*` AIActionLog entries visible in the S1 Trace
  tab.
- `pytest apps/api/tests/test_proactive*` passes with `pytest-cov`
  reporting ≥80% on the four new modules.
- `vitest run tests/unit/digest-list.test.tsx` passes; Playwright
  `s5-digest.spec.ts` passes against a running stack.
- No regression to any S1/S2/S3/S4 test.

## 16. Non-goals re-stated

S5 ships the *minimum thing that proactively notifies the user that
the system is tracking their work*. Advanced features — email,
per-user timezone, historical backfill, voice, personal cadence —
are separate sub-projects. Concept-map and S4.1 improvements are
unrelated and remain on their own tracks.
