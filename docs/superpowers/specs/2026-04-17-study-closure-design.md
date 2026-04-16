# S4 — Study Closure (Deck / Card / Quiz / Review) — Design

Date: 2026-04-17
Status: Approved for implementation
Scope: Sub-project S4 of the MRAI notebook upgrade (see
`MRAI_notebook_ai_os_build_spec.md` §10).

## 1. Purpose

Spec §10 promised a full study workflow: upload → chunk → auto-pages
(already done in P2), then **AI-generated flashcards, quizzes,
spaced-repetition review, and confusion-aware memory writes**. P2 only
shipped the ingest side. S4 closes the loop.

S4 delivers:

1. `StudyDeck` + `StudyCard` persistence with FSRS scheduling state.
2. AI endpoints to generate flashcards (from a page or a chunk) and
   MCQ quizzes.
3. A `study` ask endpoint scoped to a single `StudyAsset`.
4. Deck/Card CRUD + a review loop (show due card → 4-grade rating →
   FSRS update).
5. Confusion signals — automatic after 3 consecutive failures, or
   explicit via a "Mark as confused" button — written to memory as
   `source_type="study_confusion"` evidence through the
   UnifiedMemoryPipeline.
6. Manual "Add to Deck" button on the page-embedded `flashcard`
   TipTap block (from S2) so the two surfaces stay clearly separated
   but can cross over when the user explicitly opts in.

Concept-map visualization (spec §10 "知识地图") is explicitly split
into sub-project **S4.5** because it is a different type of work
(graph extraction + Cytoscape rendering + probably a dedicated window
type) and doing it together with S4 would double the size.

## 2. Scope

### In scope

- 2 new models, one Alembic migration.
- 1 new simplified FSRS scheduler service (~80 LOC + unit tests, no
  third-party dep).
- Deck/Card CRUD router: `list` / `create` / `patch` / `delete`
  endpoints under `/api/v1/notebooks/{nb_id}/decks` and
  `/api/v1/decks/{id}`.
- Review endpoints: `POST /decks/{id}/review/next`,
  `POST /cards/{id}/review`.
- 3 AI endpoints: `/ai/study/flashcards`, `/ai/study/quiz`,
  `/ai/study/ask`.
- `study_confusion` `source_type` added to the UnifiedMemoryPipeline
  validation set.
- New Celery task `process_study_confusion`.
- StudyWindow extended with two new tabs (Decks, Review) next to the
  existing Assets tab.
- 4 new React components: `DecksPanel`, `CardsPanel`, `ReviewSession`,
  `GenerateFlashcardsModal`, `QuizModal`.
- `FlashcardBlock` (S2) gains an "Add to Deck" button + `card_id`
  attribute + "In deck X" badge.
- Tests: ≥80% coverage on new/changed modules; one Playwright smoke
  for create-deck → card → review-rate.

### Out of scope (explicit)

- Concept map / knowledge graph visualization — deferred to S4.5.
- FSRS parameter personalization (uses hard-coded defaults).
- Multi-user shared decks (everything is workspace-scoped + per-user
  review state for the user who reviewed; see §6.2 on this decision).
- Card tags / filtering (beyond `source_type`).
- Anki `.apkg` import/export.
- Mobile layout.

## 3. Architecture

```
User (Review tab)
      │
      ▼
ReviewSession  ─ POST /decks/{id}/review/next ─▶  fetch due card
      ▲                                                 │
      │                                                 ▼
      │◀─ render {front, back (hidden)} ──────────── StudyCard row
      │
      ├─ click "Good" (rating=3)
      │     │
      │     ▼
      │  POST /cards/{id}/review {rating:3}
      │     │
      │     ├─ FSRS.schedule_next(D, S, rating, days_since_last)
      │     ├─ UPDATE StudyCard (difficulty, stability, next_review_at, …)
      │     ├─ action_log_context("study.review_card") writes audit log
      │     └─ if rating==1: consecutive_failures++; if ≥3 → Celery
      │                    process_study_confusion(card_id)
      │
      ▼
Next call to /review/next returns next due card.

Celery  process_study_confusion(card_id)
     │
     ▼
UnifiedMemoryPipeline.run_pipeline(
     source_type="study_confusion",
     source_text="<front>/<back>/trigger",
     source_ref=card_id,
)
     │
     ▼
Memory node with evidence (visible in the Memory window + Trace tab).
```

AI flashcard generation flow:

```
GenerateFlashcardsModal  ─ POST /ai/study/flashcards
     │
     ├─ body = {source_type:"page"|"chunk", source_id, deck_id?, count?}
     ▼
Router handler
     │
     ├─ load page.plain_text OR chunk.content as source_text
     ├─ async with action_log_context("study.flashcards") as log:
     │       log.set_input({...})
     │       full = await chat_completion_stream(system_prompt + source) collected
     │       parse JSON {cards:[...]}
     │       if deck_id: bulk-insert StudyCard rows (source_type, source_ref set)
     │       log.set_output({card_count, cards preview})
     │       log.record_usage(llm_completion, ...)
     ▼
Return {cards: [...], card_ids?: [...]}
```

## 4. Data Model

### 4.1 `study_decks`

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
```

`card_count` is a denormalized counter updated atomically on card
insert/delete. Avoids a COUNT(*) on every list query.

### 4.2 `study_cards`

```python
class StudyCard(Base, UUIDPrimaryKeyMixin, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "study_cards"

    deck_id: Mapped[str] = mapped_column(
        ForeignKey("study_decks.id", ondelete="CASCADE"), index=True
    )

    # Content
    front: Mapped[str] = mapped_column(Text, nullable=False)
    back: Mapped[str] = mapped_column(Text, nullable=False)

    # Source traceability — helps find "where did this card come from?"
    source_type: Mapped[str] = mapped_column(
        String(20), default="manual", nullable=False
    )   # "manual" | "block" | "page_ai" | "chunk_ai"
    source_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # FSRS state
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

    # Confusion signal
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    confusion_memory_written_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
```

Indexes:
- `ix_study_cards_deck_due` on `(deck_id, next_review_at ASC)` — used
  by the review queue query. NULL `next_review_at` sorts first so new
  cards surface.
- `ix_study_cards_deck_created` on `(deck_id, created_at DESC)` — for
  the manage view.

All review state lives on the card itself. We deliberately do **not**
add a per-user card state table: the notebook is already scoped to a
workspace + creator, and S4 explicitly out-of-scopes multi-user shared
decks. When that need appears, split it into a `StudyCardReview`
child table — the cost of that migration is small.

### 4.3 Alembic migration

File: `apps/api/alembic/versions/202604180001_study_decks_cards.py`.
Chain: `down_revision = "202604170001"` (from S2).

```sql
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

CREATE INDEX IF NOT EXISTS ix_study_cards_deck_due
    ON study_cards(deck_id, next_review_at ASC);
CREATE INDEX IF NOT EXISTS ix_study_cards_deck_created
    ON study_cards(deck_id, created_at DESC);
```

Downgrade drops both tables.

## 5. FSRS Scheduler

New file: `apps/api/app/services/fsrs.py` (~80 LOC).

```python
"""Simplified FSRS-4.5 spaced-repetition scheduler.

Public surface:
    schedule_next(difficulty, stability, rating, days_since_last_review)
        -> FSRSUpdate(difficulty, stability, next_interval_days)

Rating convention: 1=Again, 2=Hard, 3=Good, 4=Easy.

This is a reference implementation, not a training/optimization rig —
parameters are fixed. Full FSRS parameter search belongs to a separate
product decision and is deliberately out of scope for S4.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

_INITIAL_STABILITY = [0.4, 0.9, 2.3, 10.9]  # days, indexed by rating-1
_INITIAL_DIFFICULTY = [8.0, 6.0, 5.0, 3.0]

_RATING_FACTORS = {2: 0.5, 3: 1.0, 4: 1.3}  # for non-lapse ratings
_FACTOR_W = 3.0  # weight constant
_RETENTION_TARGET = 0.9  # FSRS's implied retention target

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
    """Advance a card's scheduling state after a review.

    New cards (stability == 0) seed difficulty and stability from
    rating-indexed tables. Existing cards update via FSRS formulas.
    """
    if rating < 1 or rating > 4:
        raise ValueError("rating must be 1-4")

    # New card — seed state
    if stability <= 0.0:
        new_difficulty = _INITIAL_DIFFICULTY[rating - 1]
        new_stability = max(_MIN_STABILITY, _INITIAL_STABILITY[rating - 1])
        return FSRSUpdate(
            difficulty=new_difficulty,
            stability=new_stability,
            next_interval_days=max(1, round(new_stability)),
        )

    # Update difficulty
    difficulty_delta = (5 - rating) * 0.3
    new_difficulty = _clamp(difficulty + difficulty_delta, 1.0, 10.0)

    # Update stability
    if rating == 1:
        # Lapse — shrink stability aggressively
        new_stability = max(
            _MIN_STABILITY,
            stability * 0.2 * math.exp(-0.05 * new_difficulty),
        )
    else:
        retrievability = math.exp(
            math.log(_RETENTION_TARGET) * days_since_last_review / max(stability, _MIN_STABILITY)
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

Unit tests in `tests/test_fsrs.py` cover:
1. New card, rating Good → difficulty=5.0, stability≈2.3, interval≈2.
2. New card, rating Again → difficulty=8.0, stability≈0.4, interval≈1.
3. Existing card (D=5, S=2.3), rating Good 2 days later → stability
   increases, interval ≥ 3.
4. Existing card (D=5, S=10), rating Again 10 days later →
   stability < 2.5 (drastic shrink), difficulty rises to ~6.2.

## 6. Endpoints

### 6.1 Deck / Card CRUD

All endpoints follow the S1/S2 patterns: workspace-scoped via
`get_current_workspace_id` dep, CSRF required on mutations,
`action_log_context` wrapping the mutation endpoints that actually
touch an AI path (for `review` and generation). CRUD endpoints do
**not** write action logs — they're straightforward data ops.

```
GET    /api/v1/notebooks/{nb_id}/decks
POST   /api/v1/notebooks/{nb_id}/decks            {name, description}
GET    /api/v1/decks/{deck_id}
PATCH  /api/v1/decks/{deck_id}                    {name?, description?, archived?}
DELETE /api/v1/decks/{deck_id}

GET    /api/v1/decks/{deck_id}/cards?due_only=false&limit=50&cursor=<ts>
POST   /api/v1/decks/{deck_id}/cards              {front, back, source_type?, source_ref?}
PATCH  /api/v1/cards/{card_id}                    {front?, back?}
DELETE /api/v1/cards/{card_id}
```

Card list pagination mirrors the S1 ai-action-list pattern: cursor is
`created_at` ISO8601. `due_only=true` filters to
`next_review_at IS NULL OR next_review_at <= now()`.

All routes live in a new router file `apps/api/app/routers/study_decks.py`
(the existing `routers/study.py` stays focused on assets/chunks).

### 6.2 Review endpoints

```
POST /api/v1/decks/{deck_id}/review/next
```

Response (200):
```json
{
  "card": {
    "id": "...",
    "front": "…",
    "back": "…",
    "review_count": 3,
    "days_since_last": 2.4
  }
}
```

Or when queue is empty:
```json
{"card": null, "queue_empty": true}
```

Query: pull up to 1 card from the deck matching:
- `next_review_at IS NULL` (new cards, up to 10 per session tracked
  client-side), OR
- `next_review_at <= now()` (due cards).

Ordering: `next_review_at NULLS FIRST, next_review_at ASC`. Oldest
due cards first; new cards interspersed.

```
POST /api/v1/cards/{card_id}/review
```

Body:
```json
{
  "rating": 1|2|3|4,
  "marked_confused": false
}
```

Server side:
1. Load card → deck → notebook → workspace check.
2. Compute `days_since_last = (now - last_review_at).total_seconds() / 86400` (0 if
   `last_review_at` is null).
3. Call `schedule_next(...)` → update difficulty, stability,
   last_review_at=now, next_review_at = now + update.next_interval_days,
   review_count += 1.
4. If rating == 1:
   - `lapse_count += 1`
   - `consecutive_failures += 1`
5. Else:
   - `consecutive_failures = 0`
6. Wrap in `action_log_context("study.review_card", scope="notebook",
   block_id=None)`, set_input/set_output minimal.
7. If `(consecutive_failures >= 3 OR marked_confused) AND
   confusion_memory_written_at IS NULL`:
   - Enqueue Celery task `process_study_confusion.delay(card.id,
     current_user.id, workspace_id, trigger="consecutive_failures" or
     "manual")`.
   - Set `confusion_memory_written_at = now()` eagerly in the DB so
     we don't enqueue twice if the task succeeds. On Celery failure we
     let it retry from the pending state on the next trigger — slight
     over-write is acceptable for confusion evidence.

Response: `{ok: true, next_review_at: "..."}`.

### 6.3 AI endpoints

New router `apps/api/app/routers/study_ai.py`
(prefix `/api/v1/ai/study`).

All three wrap the work in `action_log_context` (S1 pattern) with
specific `action_type` and `scope` values:

| Endpoint | action_type | scope |
|---|---|---|
| `POST /flashcards` | `study.flashcards` | `study_asset` if chunk, `page` if page |
| `POST /quiz` | `study.quiz` | `study_asset` if chunk, `page` if page |
| `POST /ask` | `study.ask` | `study_asset` |

#### 6.3.1 `POST /ai/study/flashcards`

Body:
```json
{
  "source_type": "page" | "chunk",
  "source_id": "<uuid>",
  "count": 10,
  "deck_id": null | "<uuid>"
}
```

- Resolve source text:
  - `page` → load `NotebookPage.plain_text[:8000]`.
  - `chunk` → load `StudyChunk.content[:8000]`.
- Prompt:
  ```
  You are generating study flashcards from the following text.
  Produce exactly <count> question/answer pairs in JSON.
  Each question should test a distinct concept. Answers concise.
  Output format: {"cards": [{"front": "...", "back": "..."}, ...]}.
  Only JSON, no commentary.

  Text:
  <source>
  ```
- Use the non-streaming `chat_completion` (not `chat_completion_stream`)
  helper — the output is small JSON, streaming just complicates
  parsing. If the existing service only exposes streaming, collect the
  tokens and parse at end.
- Parse JSON with a single `json.loads` inside try/except. On parse
  failure, return 422 with `ApiError("llm_bad_output", "...")` — do
  **not** save partial cards.
- If `deck_id` is provided, validate it belongs to the same workspace,
  then bulk-insert `StudyCard` rows with
  `source_type="page_ai"` or `"chunk_ai"`, `source_ref=source_id`.
  Increment `deck.card_count` by the number inserted.
- Response:
  ```json
  {
    "cards": [{"front": "...", "back": "..."}, ...],
    "card_ids": null | ["...", ...]
  }
  ```
- `record_usage` with `event_type="llm_completion"` using the exact
  `usage` block from the model (or estimate fallback per S1 pattern).

#### 6.3.2 `POST /ai/study/quiz`

Body:
```json
{
  "source_type": "page" | "chunk",
  "source_id": "<uuid>",
  "count": 5
}
```

Prompt produces:
```json
{
  "questions": [
    {
      "question": "...",
      "options": ["A", "B", "C", "D"],
      "correct_index": 2,
      "explanation": "..."
    }
  ]
}
```

Server validates:
- `options.length == 4`.
- `0 <= correct_index < 4`.
- Each option non-empty.

On validation failure: log + raise 422. No silent fix-up.

**Quiz state is entirely client-side for S4.** The generated
questions are not persisted. The user's answers, score, and wrong-
answer list live only in `QuizModal`'s local component state and
disappear when the modal closes. Wrong answers do **not** trigger
`/cards/{id}/review` — quiz MCQs are not cards, they have no
`card_id`. The UI may show a "Mark these wrong answers as confusing"
button at the end of the quiz, but that just keeps a local note. A
dedicated `/ai/study/quiz/record-wrong` endpoint that would feed the
confusion memory path is explicitly a follow-up sub-project.

#### 6.3.3 `POST /ai/study/ask`

Body:
```json
{
  "asset_id": "<uuid>",
  "message": "…",
  "history": [{"role": "user"|"assistant", "content": "..."}]
}
```

SSE response, mirror of `/ai/notebook/ask` from S1. Context
assembly:
- Load last 5 chunks the user has referenced (via searching
  `NotebookPage.content_json` for `reference` blocks with
  `target_type == "study_chunk"` and `target_id IN asset's chunks`).
- Load top 3 chunks by embedding similarity to the question (reuse
  `retrieval_orchestration` helper, passing a synthesized asset scope).
- Assemble: prompt preamble + chunks + user notes + memory hits.

`services/retrieval_orchestration.py` already accepts a `query` and
internally calls embedding search. For S4 we add a new thin helper in a
new file `services/study_context.py` exporting
`assemble_study_context(db, *, asset_id, query, workspace_id,
project_id, user_id)` that:

1. Loads the top 3 `StudyChunk` rows of `asset_id` by embedding
   similarity to `query` (reusing `embedding.search_similar` with a
   chunk-scoped filter).
2. Loads the last 5 `reference` blocks across the notebook's pages
   whose `target_type == "study_chunk"` and `target_id` is in the
   asset's chunks (one SQL pass over page content_json).
3. Calls `retrieval_orchestration.assemble_context` with the
   chunk/page snippets stitched into `page_text`.

`retrieval_orchestration.assemble_context` itself is **not changed**.
This keeps S1's retrieval layer stable.

Pass the `sources` list this helper returns into
`action_log_context` via
`set_trace_metadata({"retrieval_sources": sources})`.

### 6.4 Endpoint registration

`apps/api/app/main.py` gains one new `include_router(study_decks.router)`
call and one new `include_router(study_ai.router)` call. Both are
under `/api/v1`.

## 7. Confusion Celery Task

New task in `apps/api/app/tasks/worker_tasks.py`:

```python
@celery_app.task(name="app.tasks.worker_tasks.process_study_confusion")
def process_study_confusion_task(
    card_id: str,
    user_id: str,
    workspace_id: str,
    trigger: str,  # "consecutive_failures" | "manual"
) -> None:
    """Write a confusion-memory evidence for a StudyCard the user keeps
    getting wrong.

    Idempotent: if `StudyCard.confusion_memory_written_at` is already
    set when the task runs, it returns early. The request handler also
    eagerly sets that field before enqueueing, so at most one memory
    per card ever gets written in the common case.
    """
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
            return  # can't attach memory without a project

        source_text = (
            f"User is confused about this study card (trigger: {trigger}).\n"
            f"Question: {card.front}\n"
            f"Answer: {card.back}\n"
            f"Lapses: {card.lapse_count}, consecutive failures: {card.consecutive_failures}."
        )
        asyncio.run(
            run_pipeline(
                db,
                PipelineInput(
                    source_type="study_confusion",
                    source_text=source_text[:6000],
                    source_ref=str(card.id),
                    workspace_id=str(workspace_id),
                    project_id=str(notebook.project_id),
                    user_id=str(user_id),
                    context=SourceContext(owner_user_id=str(user_id)),
                    context_text=f"Study confusion ({trigger})",
                ),
            )
        )
    finally:
        db.close()
```

`apps/api/app/services/unified_memory_pipeline.py` gains
`"study_confusion"` to its `_VALID_SOURCE_TYPES` set. The triage
branch treats `study_confusion` like `chat_message` for classification
but bumps the initial `importance` floor to 0.5 so confusion
evidence is not triaged away immediately.

## 8. Frontend

### 8.1 StudyWindow tab structure

Replace the current flat `StudyWindow.tsx` with a tabbed shell:

```
┌─ StudyWindow ───────────────────┐
│ [Assets] [Decks] [Review]       │ ← new tab bar
├─────────────────────────────────┤
│ <tab content>                    │
└─────────────────────────────────┘
```

Tab content components:
- **AssetsPanel** — lift the existing StudyWindow body into a new file
  `components/notebook/contents/study/AssetsPanel.tsx`.
- **DecksPanel** — lists decks; buttons to Create / Open / Archive.
  Clicking Open shows the CardsPanel for that deck.
- **CardsPanel** — list cards, edit inline, delete. Buttons: "Start
  Review", "Generate from page…", "Generate from chunk…".
- **ReviewSession** — when activated for a deck, polls
  `/decks/{id}/review/next`. Renders one card at a time: front visible,
  back revealed on click, then 4 rating buttons + "Mark confused".
  POST rating → next card. When `queue_empty`, show a summary.

### 8.2 GenerateFlashcardsModal

A dialog opened from CardsPanel:
1. Pick source: radio buttons for "From this page" (requires an open
   Note window; uses its `pageId`) or "From a chapter" (dropdown
   populated from `GET /notebooks/{nb_id}/study-assets/{asset}/chunks`).
2. Pick count (5–20).
3. Preview button → calls `/ai/study/flashcards` with `deck_id=null`
   and renders the returned `cards` as an editable list.
4. "Save to this deck" → re-calls `/ai/study/flashcards` with
   `deck_id=<current>` and `cards` in the body? — **No**: simpler to
   reuse the preview payload client-side and POST
   `POST /decks/{id}/cards` in a `Promise.all` for each card. That
   avoids having to teach the AI endpoint to accept pre-generated
   cards.

### 8.3 QuizModal

Opened from CardsPanel with "Start Quiz (5 questions)":
1. Pick source: same as above.
2. POST `/ai/study/quiz` → receives `{questions}`.
3. Render one question at a time with 4 options.
4. Submit → show green/red + explanation.
5. At end, render score + wrong-answer list.
6. If user clicks "Mark confused" on a wrong answer **and the
   question came from a page or chunk that has an associated card in
   some deck**, post `/cards/{id}/review` with `rating=1,
   marked_confused=true`. If no card exists, the wrong answer stays
   local — S4 does not auto-create cards from quiz wrongs.

### 8.4 FlashcardBlock "Add to Deck"

Update `apps/web/components/console/editor/extensions/FlashcardBlock.tsx`:
- Add `card_id: string | null` to the attrs (default null).
- When `card_id` is null, render an "Add to Deck" button alongside
  the Edit/Preview tabs.
- Click button → open a compact deck picker (same notebook's decks
  via `/notebooks/{nb_id}/decks` + "+ New deck" option).
- On pick → `POST /decks/{deck_id}/cards` with
  `{front, back, source_type:"block", source_ref: "<block tiptap uuid>"}`
  and set the returned `card_id` on the block's attrs via
  `props.updateAttributes({card_id})`.
- When `card_id` is not null, render a small "In deck ✓" pill.
  Clicking the pill opens the deck's CardsPanel scrolled to that
  card (deferred nice-to-have; S4 just shows the pill).

### 8.5 i18n

Update `apps/web/messages/en/console-notebooks.json` +
`apps/web/messages/zh/console-notebooks.json` with the new strings:
`study.tabs.assets`, `study.tabs.decks`, `study.tabs.review`,
`study.decks.create`, `study.cards.generate`, `study.cards.start_review`,
`study.review.rate.again`, `study.review.rate.hard`, `study.review.rate.good`,
`study.review.rate.easy`, `study.review.mark_confused`,
`study.review.queue_empty`, `study.quiz.start`, `study.quiz.submit`,
`study.flashcard.add_to_deck`, `study.flashcard.in_deck`.

## 9. Error Handling

- **LLM returns non-JSON**: `ApiError("llm_bad_output", ..., 422)`. No
  partial writes. UI shows a red toast and keeps the preview empty.
- **Deck deleted while review running**: `/decks/{id}/review/next`
  returns 404. UI closes the session gracefully.
- **Cross-workspace access on any endpoint**: 404, not 403 (consistent
  with S1/S2).
- **Celery task fails**: the `confusion_memory_written_at` was set
  eagerly — task failure means that one confusion event is silently
  dropped. Acceptable: next failure or next explicit mark fires a new
  attempt. Counter + error log in `runtime_state.metrics`
  (`study_confusion.task_failures`) for monitoring.
- **FSRS produces zero/NaN**: `schedule_next` clamps with
  `_MIN_STABILITY=0.1`. Unit tests verify.

## 10. Testing Strategy

Target ≥80% line coverage on new modules.

### 10.1 Backend unit

- `tests/test_fsrs.py` — 4 cases (§5 list).
- `tests/test_study_decks.py` — 5 cases: create, list, patch (rename
  + archive), delete cascade, cross-workspace 404.
- `tests/test_study_cards.py` — 4 cases: create, list+due_only filter,
  patch, delete decrements deck.card_count.
- `tests/test_study_review.py` — 5 cases: new-card review seeds state,
  review updates next_review_at, lapse bumps consecutive_failures,
  three consecutive failures enqueues confusion task, manual mark
  enqueues confusion task.
- `tests/test_study_ai_endpoints.py` — 3 cases:
  flashcards happy path with deck_id=None, flashcards with deck_id
  bulk-inserts cards, quiz returns valid MCQ schema. All use
  `monkeypatch` on the LLM client to return canned JSON.
- `tests/test_study_ask.py` — 1 case: streaming ask echoes fake tokens,
  AIActionLog `study.ask` row exists with `retrieval_sources` in
  trace_metadata.
- `tests/test_study_confusion_task.py` — 2 cases: task runs once and
  sets `confusion_memory_written_at`; task is a no-op when the flag
  is already set.

### 10.2 Frontend unit (vitest)

- `tests/unit/fsrs-parity.test.ts` — if we port FSRS to the client, 4
  parity tests against a pinned backend output. If we don't port (all
  FSRS lives server-side), skip this.

### 10.3 Playwright smoke

`tests/s4-study.spec.ts`: one test driving the full loop —
1. Create deck.
2. Add card manually via CardsPanel.
3. Start review.
4. Click reveal, click Good.
5. Expect "queue empty" state.

Stack-run only, mark skipped if no dev server.

## 11. File Plan

### New files

- `apps/api/app/services/fsrs.py`
- `apps/api/app/services/study_context.py`
- `apps/api/app/routers/study_decks.py`
- `apps/api/app/routers/study_ai.py`
- `apps/api/alembic/versions/202604180001_study_decks_cards.py`
- `apps/api/app/schemas/study_decks.py` (Pydantic request/response
  shapes for Deck/Card CRUD and review endpoints — mirrors
  `schemas/study.py` pattern from P2)
- `apps/api/tests/test_fsrs.py`
- `apps/api/tests/test_study_decks.py`
- `apps/api/tests/test_study_cards.py`
- `apps/api/tests/test_study_review.py`
- `apps/api/tests/test_study_ai_endpoints.py`
- `apps/api/tests/test_study_ask.py`
- `apps/api/tests/test_study_confusion_task.py`
- `apps/web/components/notebook/contents/study/AssetsPanel.tsx` (lifted from StudyWindow)
- `apps/web/components/notebook/contents/study/DecksPanel.tsx`
- `apps/web/components/notebook/contents/study/CardsPanel.tsx`
- `apps/web/components/notebook/contents/study/ReviewSession.tsx`
- `apps/web/components/notebook/contents/study/GenerateFlashcardsModal.tsx`
- `apps/web/components/notebook/contents/study/QuizModal.tsx`
- `apps/web/components/notebook/contents/study/DeckPickerDialog.tsx`
- `apps/web/styles/study-window.css`
- `apps/web/tests/s4-study.spec.ts`

### Modified files

- `apps/api/app/models/entities.py` (add 2 classes)
- `apps/api/app/models/__init__.py` (export 2 names)
- `apps/api/app/services/unified_memory_pipeline.py` (accept
  `study_confusion` source_type, bump importance floor)
- `apps/api/app/tasks/worker_tasks.py` (add `process_study_confusion_task`)
- `apps/api/app/main.py` (register 2 new routers)
- `apps/web/components/notebook/contents/StudyWindow.tsx` (tab shell)
- `apps/web/components/console/editor/extensions/FlashcardBlock.tsx`
  (Add to Deck button + card_id attr + In-deck pill)
- `apps/web/messages/en/console-notebooks.json`
- `apps/web/messages/zh/console-notebooks.json`

## 12. Phase Layout (for the plan)

| Phase | Tasks | Description |
|---|---|---|
| **A** | T1–T2 | FSRS service + unit tests |
| **B** | T3–T4 | StudyDeck / StudyCard models + Alembic migration + ORM smoke test |
| **C** | T5–T9 | Deck/Card CRUD endpoints + 5 API tests |
| **D** | T10–T11 | Review endpoints (`review/next` + `review`) + 5 API tests |
| **E** | T12–T13 | `study_confusion` source_type in UnifiedMemoryPipeline + Celery task + 2 tests |
| **F** | T14–T16 | 3 AI endpoints + 4 API tests |
| **G** | T17 | `StudyWindow` tab shell refactor + AssetsPanel lift |
| **H** | T18–T20 | `DecksPanel` + `CardsPanel` + `ReviewSession` |
| **I** | T21–T22 | `GenerateFlashcardsModal` + `QuizModal` |
| **J** | T23 | `FlashcardBlock` Add-to-Deck wiring |
| **K** | T24 | Playwright smoke |
| **L** | T25 | Final coverage verification |

25 tasks. Roughly the same cardinality as S2.

## 13. Acceptance Criteria

1. `alembic upgrade head` creates `study_decks` and `study_cards`
   tables with their indexes.
2. Creating a deck → creating a card (manual) → starting review → rating
   Good updates `next_review_at` per FSRS.
3. Rating Again three times in a row enqueues a Celery task that writes
   a `study_confusion` memory evidence, and sets
   `confusion_memory_written_at`.
4. Manually clicking "Mark confused" once enqueues the same task
   regardless of failure count.
5. `POST /ai/study/flashcards` returns 10 valid Q/A pairs for a page
   of plain_text. With `deck_id` set, cards persist to the deck.
6. `POST /ai/study/quiz` returns 5 valid MCQs with exactly 4 options
   each and `correct_index` in [0,3].
7. `POST /ai/study/ask` streams an SSE response with `sources`
   populated from the asset's chunks.
8. Each AI endpoint produces an `AIActionLog` row with the expected
   `action_type` prefix (`study.flashcards` / `study.quiz` / `study.ask`).
9. A page `flashcard` block's "Add to Deck" button inserts a new card
   into the picked deck and the block's `card_id` attr is populated.
10. `pytest apps/api/tests/test_study*` passes with `pytest-cov`
    reporting ≥80% line coverage on `services/fsrs.py`,
    `routers/study_decks.py`, `routers/study_ai.py`,
    `tasks/worker_tasks.py::process_study_confusion_task`.
11. `pnpm test:unit` + the one new Playwright smoke pass.

## 14. Non-goals Re-stated

Concept map, FSRS parameter optimization, multi-user decks, tags,
Anki import, and mobile layout are all explicitly deferred. The
product shape S4 ships is *the minimum thing the user can practice
against without falling back to external tools like Anki*. Advanced
features are sub-projects in their own right.
