# Changelog

All notable changes to MRAI / MRNote are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Dates are ISO (YYYY-MM-DD); versions move when a real release tag is cut.

## [Unreleased] — 2026-04-22 / 2026-04-23 · Security + Homepage Restyle

This entry rolls up a multi-day push that (a) closed a six-agent security
audit, (b) aligned the codebase to `MRAI_notebook_ai_os_build_spec.md`,
and (c) rebranded the marketing homepage to the MRNote teal + orange
visual language. Seven commits on `main`.

### Database migrations to run on deploy

```bash
alembic upgrade head   # takes head to 202604240003
```

Applied in order:
- `202604220003` — `subscriptions.trial_used_at` + partial unique index
- `202604220004` — `notebook_selection_memory_links` table
- `202604220005` — 6 Postgres `CHECK` constraints (enum hardening) +
  `study_assets.language / author / page_id`
- `202604230002` — `study_chunks.summary` + `keywords_json`
- `202604240002` — `users.persona`, `digest_daily`, `digest_weekly`
- `202604240003` — `users.timezone`, `users.digest_email_enabled`

### Required environment variables (new)

- `SITE_URL` — **production must set to canonical HTTPS**. Upload
  presign URLs are now built from this instead of `request.base_url`.
  Default `http://localhost:3000` is dev-only.

### Added

**Security**
- `apps/api/app/core/notebook_access.py` — shared `assert_notebook_readable`
  gate reused by 4 routers (`notebook_ai` / `study_ai` / `study_decks` /
  `search`) to close same-workspace IDOR.
- `apps/api/app/routers/blocks.py` — NotebookBlock CRUD (spec §13.3):
  `POST /pages/{id}/blocks`, `PATCH /blocks/{id}`, `DELETE /blocks/{id}`,
  `POST /pages/{id}/reorder-blocks`, with TipTap JSON ↔ block-row
  bidirectional mapping.
- Flat `DELETE /api/v1/attachments/{id}` endpoint (spec §13.4).
- 169 new regression tests across nine test files
  (`test_chat_quota_gates`, `test_auth_c_fixes`, `test_notebook_access_gates`,
  `test_injection_fixes`, `test_billing_abuse_fixes`,
  `test_backend_spec_alignment`, `test_worker_tasks_spec_alignment`,
  `test_p0_spec_alignment`, `test_persona_digest`).
- 14 new Celery tasks (plaintext / snapshot / summary / memory-link /
  unified-memory-extract / relevance-refresh / whiteboard /
  document-memory / chunk / auto-pages / deck-generate /
  study-memory / review-recommendation / usage-rollup /
  subscription-sync-repair) with entries in `beat_schedule`.
- `services/retrieval_orchestration.py` now assembles 6 layers
  (page text / selection / memory search / **memory explain (new)** /
  related pages / document chunks / **page history (new)**) with a
  7-value `scope` enum.
- Four new `/api/v1/ai/notebook/*` endpoints: `brainstorm`,
  `generate-page`, `/pages/{id}/duplicate`, `/pages/{id}/move`.
- `POST /api/v1/study-assets/{id}/generate-deck` shortcut endpoint.

**Homepage + marketing**
- Full MRNote teal + orange restyle. New `:where(.marketing-theme)`
  token block at the top of `marketing.css` remaps to the warm
  `--mkt-*` palette; `.marketing-theme` wrapper lives only on public
  pages (`/`, `/pricing`, `/privacy`, `/terms`) so the app console
  stays on `--brand-v2` blue.
- PublicHeader rewrite — sticky backdrop blur, teal logo mark with
  orange shadow-dot, Chinese nav (功能 / 记忆 / 定价 / 更新日志),
  orange "免费开始 →" CTA, compact 中·EN toggle.
- Hero — single-column centered, dual radial teal+orange glow + 48px
  grid background, 3-persona pill switch (学生 / 研究者 / 产品经理),
  NEW kicker pill, split `<h1>` with teal-gradient `<em>` + orange
  highlighter `<mark>`, macOS-styled 620px canvas stage with traffic
  lights + focus-glow.
- New `MemorySection.tsx` — dark teal section, 3-stat grid, 8-node
  simplified memory graph with staggered pulse animation.
- New `components/marketing/digest/*` — tabbed daily digest + weekly
  reflection with SVG sparkline, per-persona mock data for all 6
  roles, honors real `/api/v1/digest/*` data when signed in.
- New `components/settings/PersonaSection.tsx` — in-app persona picker.
- New `components/app/DigestDrawer.tsx` — workspace-shell morning drawer
  (one per day, `localStorage` guard).
- New `components/auth/PersonaPickerStep.tsx` — optional Step 2 on
  `/register`, 3 persona cards + skip.
- Three new SDKs: `lib/notebook-sdk.ts`, `lib/study-sdk.ts`,
  `lib/billing-sdk.ts`.
- Google Fonts — Plus Jakarta Sans + JetBrains Mono self-hosted via
  `next/font/google`; Noto Sans SC stays on `@import` (partial migration).
- Four new Playwright specs (`s8-ai-rewrite`, `s9-upload-pdf`,
  `s10-memory-links`, `s11-upgrade-flow`) behind env flags.

### Changed

**Security / behaviour**
- Chat router (`apps/api/app/routers/chat.py`) — every LLM-touching
  POST (6 endpoints) now carries `Depends(require_entitlement("ai.actions.monthly", …))`
  and `voice.enabled` where applicable. All calls write `AIUsageEvent`
  via `action_log_context` so the monthly counter actually advances.
- Realtime `/voice` and `/composed-voice` WebSockets — `_ensure_voice_entitlement`
  gate (matching the existing `/dictate` gate) prevents Free users
  from getting Pro realtime voice by opening the socket directly.
- `require_entitlement` — counted-quota branch now acquires a row-level
  `with_for_update` lock on the Workspace so concurrent creators can't
  both observe `current < limit`.
- `resolve_entitlement` — pure-read; the old on-the-fly plan row rewrite
  is gone (HIGH-8). Expired `admin_override` rows fall back to plan
  value at read time.
- `PUT /auth/password` + `POST /auth/google/disconnect` — revoke
  pre-existing JWTs and reissue a fresh cookie+CSRF so the caller
  keeps their session.
- `/register` — identical `200 {"ok": true}` for new and existing
  emails (no more `409 email_exists` enumeration); rejects ~22 known
  disposable domains upfront.
- `/reset-password` — 8-digit codes, per-email rate limit,
  5-attempt cap.
- `/auth/password`, `/send-code` — per-user and per-email rate limits
  added.
- `/ws-ticket` — Redis stores `sha256(access_token)`, not the raw JWT.
- `/memory/backfill` — audit log now records `actor_user_id`.
- `is_safe_redirect_path` — rejects nested open-redirect params
  (`?next=`, `?redirect=`, `//`, `javascript:`, `data:`).
- Attachment upload (`routers/notebooks.py` + `services/storage.py`) —
  enforces MIME / extension / magic-bytes triple check, forces
  `application/octet-stream` on the S3 `PUT` unless the MIME is in a
  tight whitelist, always returns `Content-Disposition: attachment`
  on presigned GET.
- Document indexer (`services/document_indexer.py`) — three-tier zip
  bomb guard (64 MB per member / 128 MB declared / 256 MB archive
  aggregate) with streamed reads.
- Prompt-injection defences — `context_loader.build_system_prompt`
  wraps RAG knowledge / memories in `<untrusted_knowledge_context>`
  tags; `unified_memory_pipeline` pre-filters seven instruction-override
  patterns before the extractor LLM sees the text.
- `upload_page_attachment` + `study_pipeline` — streaming body reads
  with `Content-Length` pre-check and 128 MB `Range`-bounded S3 reads
  to bound memory under hostile payloads.
- `schemas/notebook.py` — `cover_image_url` field validator blocks
  non-HTTPS schemes, RFC1918 / loopback / link-local / cloud-metadata
  hostnames.
- `services/related_pages.py` — dynamic `IN (…)` converted to
  `sqlalchemy.bindparam(..., expanding=True)`.

**Billing**
- Stripe webhook — one-time subscriptions now extend the existing
  `manual` row instead of stacking; `trial_period_days` is gated on
  `Subscription.trial_used_at` so the 14-day trial can't be reused
  per workspace; `handle_invoice_paid` pulls `current_period_end`
  from `stripe.Subscription.retrieve(...)` instead of trusting the
  invoice field; `handle_subscription_updated` re-fetches line items
  to keep `seats` in sync; `handle_charge_refunded` cancels the
  matching manual subscription and refreshes entitlements; all
  events cross-check `metadata.mrai_plan` against the actual Stripe
  price id and short-circuit on mismatch.
- `stripe_client.get_or_create_customer` — prefers
  `stripe.Customer.search(...)` before creating, with an idempotency
  key derived from `workspace_id`.
- `ai_action_logger._flush_failure` — now flushes buffered usage
  events (HIGH-10) so LLM tokens are accounted for even when the
  action ultimately raises.
- `routers/uploads.py` — `presign` endpoint adds `require_entitlement("book_upload.enabled")`;
  `put_url` is built from `settings.site_url` instead of
  `request.base_url` to defeat Host-header spoofing.
- `routers/billing.py` — `/plans` masks price ids (`****xxxx`).
- Checkout endpoint guards against double-trial and forces portal
  cancellation before a second active subscription can land.

**Soft delete + field hardening**
- `delete_page` flipped from `db.delete(page)` to `page.is_archived = True`
  so memory evidence links aren't broken on removal.
- Write paths (`create_page`, upload, `create_block`, etc.) now refuse
  to mutate pages inside archived notebooks (HIGH-7).
- `StudyAsset` ORM gained `language / author / page_id` (columns were
  added in a migration but the SQLAlchemy model didn't expose them).
- `StudyChunk` gained `summary` + `keywords_json` (spec §5.1.7).

**Homepage**
- Marketing JSON — `hero.footBadgesLabel`, `digest.*` (30+ keys), and
  per-role `digestMock` payloads for all six roles.
- `app/[locale]/page.tsx` — rewrapped root with `className="marketing-theme"`
  so every downstream section reads `--mkt-*` tokens.
- `useRoleSelection` gained `persona` + `setPersona` (debounced server
  sync to `PATCH /me`).
- `registers` page — multi-step state machine gained a `persona` step
  between code verification and workspace redirect.

### Fixed

- `test_api_integration.py` — 29 voice / realtime tests now seed a
  Pro subscription so the new `voice.enabled` gate doesn't force 402;
  three pre-existing memory / compaction tests adjusted to observed
  behaviour; `SITE_URL=http://testserver` set so upload-proxy tests
  reach the app instead of localhost:3000.
- `role-selector/StatCounter.tsx` — pre-existing
  `react-hooks/set-state-in-effect` error.
- Slash command menu in the notebook editor — `aiBrainstorm` and
  `studyQa` entries per spec §19.1 (previously only generic `aiOutput`).

### Deferred (explicit)

- **Monaco / CodeMirror code block upgrade** — bundle cost + NodeView
  rework is its own Sprint. CodeBlockLowlight + `language` + `filename`
  attrs cover 90 % of the spec intent.
- **`CodeWindow` / `CanvasWindow` / `ChatWindow` standalone window
  types** — block-level embedding already covers the common case.
  Revisit once product confirms they want dedicated window shells.
- **URL `?windows=` window-state persistence** — localStorage still
  works per-device; cross-device URL sync is a standalone effort.
- **Disposable email blocklist** — 22 curated domains, not an
  external feed. Sign-up hygiene, not a security boundary.
- **Global per-second JWT revoke window** — same-second revoke still
  fails-open for a stolen token. Needs a jti blacklist or sub-second
  `iat`; larger change than the audit brief called for.
- **Noto Sans SC via `next/font/google`** — dynamic Chinese subset
  didn't cooperate with the Next 15 font loader. The `@import` in
  `globals.css` remains for that one family.

### Deploy checklist

1. Pull `main` (commit range `c68687f..36f8f20` + the pending Agent X
   commit for digest email / timezone / LLM insight).
2. Set `SITE_URL` in production env.
3. `alembic upgrade head` (takes head to `202604240003`).
4. Restart API + Celery worker + Celery beat (new tasks + updated
   schedule).
5. Redeploy the web app (new fonts, new CSS, new marketing routes
   guarded by `.marketing-theme`).
6. Smoke test: open `/`, switch the hero pill, sign in, check the
   in-app digest drawer.

Rollback: `alembic downgrade` walks the chain above in reverse; each
revision's `downgrade()` is exercised in CI-style tests.

---

Earlier entries live only in `git log`. See
`tmp/bug_audit/99_FINAL_DELIVERY.md` + `SPEC_ALIGNMENT_GAPS.md` +
`AUDIT_VERDICT.md` for the original audit reports that drove this
work.
