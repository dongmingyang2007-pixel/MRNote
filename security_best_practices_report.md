# MRAI Security And Bug Review Report

Date: 2026-04-26

## Executive Summary

Six parallel review agents audited the repository across backend auth, upload/file handling, billing, AI/RAG isolation, frontend security, and database/worker consistency. The highest-risk findings are concentrated in:

- Cross-user / cross-workspace data leakage through search, notebook AI retrieval, and trusted worker task parameters.
- ONLYOFFICE callback and upload handling, including SSRF, quota bypass, and parser exposure.
- Billing and quota enforcement races that can grant or overuse paid entitlements.
- Background cleanup and versioning paths that rely on caller/task parameters without enough defensive validation.

No business-code changes were made in this review. This report consolidates and deduplicates the findings.

## Critical Findings

### C1. Worker `index_data_item` Trusts Caller-Supplied Object And Workspace Parameters

- Severity: Critical
- Location: `/Users/dog/Desktop/MRAI/apps/api/app/tasks/worker_tasks.py:348`
- Evidence: `index_data_item(workspace_id, project_id, data_item_id, object_key, filename)` loads only `DataItem` by ID, then downloads `object_key` and indexes it under the supplied `workspace_id/project_id`.
- Impact: A forged, replayed, or buggy internal task can index arbitrary object storage content into the wrong workspace/project, causing data pollution or leakage.
- Fix: Pass only `data_item_id`; inside the worker join `DataItem -> Dataset -> Project`, derive `workspace_id`, `project_id`, `object_key`, and `filename`, and fail if any expected values do not match.
- False positive notes: Exploitability depends on who can enqueue Celery tasks or reach code paths that enqueue attacker-controlled parameters.

### C2. Document Memory Extraction Trusts Caller-Supplied Workspace/Project

- Severity: Critical
- Location: `/Users/dog/Desktop/MRAI/apps/api/app/tasks/worker_tasks.py:2339`, `/Users/dog/Desktop/MRAI/apps/api/app/services/unified_memory_pipeline.py:2252`
- Evidence: `document_memory_extract_task` loads `StudyChunk` by `chunk_id`, then runs the memory pipeline using caller-supplied `workspace_id/project_id/user_id`; `run_pipeline` uses `db.get(Project, inp.project_id)` without checking `Project.workspace_id`.
- Impact: A forged or mistaken task can turn another workspace's document chunk into memories in the wrong project, creating cross-workspace leakage and inconsistent graph data.
- Fix: Resolve `chunk -> StudyAsset -> Notebook -> Project` in the task and require it to match the supplied workspace/project, or derive those values entirely. In `run_pipeline`, query project by both `id` and `workspace_id`.

## High Findings

### H1. ONLYOFFICE Callback Enables SSRF And Arbitrary Document Overwrite

- Severity: High
- Location: `/Users/dog/Desktop/MRAI/apps/api/app/routers/onlyoffice.py:168`, `/Users/dog/Desktop/MRAI/apps/api/app/services/onlyoffice.py:185`
- Evidence: The callback URL token is exposed in editor config. `receive_callback` treats body JWT as optional and directly fetches `payload["url"]` with `httpx.Client().stream("GET", download_url)`.
- Impact: A user with the callback token can make the API fetch internal or attacker-controlled URLs and overwrite the document with the response.
- Fix: Require and verify the ONLYOFFICE body JWT, validate document key/status, allowlist the expected Document Server origin, block private/loopback/link-local IPs, and disable or revalidate redirects.

### H2. ONLYOFFICE Callback Bypasses Storage Quota And Token Replay Controls

- Severity: High
- Location: `/Users/dog/Desktop/MRAI/apps/api/app/routers/onlyoffice.py:193`
- Evidence: Each save callback can pull up to `max(upload_max_mb, 64MB)`, write the live object, and create a `DocumentVersion` snapshot without `assert_can_store`, callback rate limiting, or scoped token single-use protection.
- Impact: Repeated callbacks can grow version snapshots beyond workspace quota.
- Fix: Gate save bytes and snapshot bytes against quota before writing, add per-document rate limits, shorten callback token TTL, and mark scoped `jti` values as one-time use.

### H3. Office Upload Validation Lets Non-Office Bytes Reach Office Parsers

- Severity: High
- Location: `/Users/dog/Desktop/MRAI/apps/api/app/services/upload_validation.py:237`, `/Users/dog/Desktop/MRAI/apps/api/app/services/onlyoffice.py:57`
- Evidence: Unknown extensions can normalize to `application/octet-stream`; unknown media signatures return `True`; ONLYOFFICE eligibility is extension-only; OOXML validation only checks the ZIP `PK` prefix.
- Impact: Arbitrary binary, malformed Office files, or zip-bomb-like archives can be routed into ONLYOFFICE or indexing parsers.
- Fix: Use a strict Office allowlist; validate extension, MIME, magic, and OOXML package structure; enforce zip member and archive limits before opening in editors.

### H4. Production Allows Default OAuth Session Secret

- Severity: High
- Location: `/Users/dog/Desktop/MRAI/apps/api/app/core/config.py:177`, `/Users/dog/Desktop/MRAI/apps/api/app/main.py:126`
- Evidence: `oauth_session_secret` defaults to `change-me-in-prod-use-openssl-rand-hex-32`, but `validate_runtime_configuration()` does not reject it.
- Impact: Production OAuth session cookies can be forgeable if the env var is missed, affecting OAuth state and connect-mode user binding.
- Fix: Reject default or short `OAUTH_SESSION_SECRET` in production. For connect callbacks, also verify the current authenticated user matches the session `oauth_connect_user_id`.

### H5. Read-Only Members Can Receive Editable ONLYOFFICE Config

- Severity: High
- Location: `/Users/dog/Desktop/MRAI/apps/api/app/routers/onlyoffice.py:77`
- Evidence: `get_editor_config` requires membership but always returns `build_editor_config(..., can_edit=True)` and does not check `require_workspace_write_access`.
- Impact: Viewer/read-only members can receive edit/comment/review permissions and callback tokens for documents they can read.
- Fix: Add `workspace_role` and use `is_workspace_write_role()` to set `can_edit`; do not emit callback tokens for view-only config, or require write access for this route.

### H6. Conversation Export Bypasses Conversation Visibility

- Severity: High
- Location: `/Users/dog/Desktop/MRAI/apps/api/app/routers/notebooks.py:851`
- Evidence: `create_page_from_conversation` fetches `Conversation` by `id` and `workspace_id` only, then copies all messages. Chat routes use `can_access_workspace_conversation`.
- Impact: A workspace editor can export another non-admin user's conversation into a notebook page if they know or obtain the conversation ID.
- Fix: Reuse the chat conversation access check with `workspace_role` and `conversation.created_by` before reading messages.

### H7. Global Search Leaks Private Memories And Playbooks

- Severity: High
- Location: `/Users/dog/Desktop/MRAI/apps/api/app/services/search_dispatcher.py:126`
- Evidence: Non-privileged visibility filtering applies to `pages`, `blocks`, `study_assets`, `files`, and `ai_actions`, but not `memory` or `playbooks`.
- Impact: A regular workspace member can search snippets from another user's private memories or playbooks in the same project.
- Fix: Pass `current_user_id/workspace_role` into memory/playbook search and filter with the same private-memory visibility rules used elsewhere.

### H8. Notebook AI Can Put Other Users' Private Memories Into Prompts

- Severity: High
- Location: `/Users/dog/Desktop/MRAI/apps/api/app/services/retrieval_orchestration.py:97`
- Evidence: `_retrieve_memory_hits` calls `search_similar`, then materializes `Memory.content` by ID without owner/private/conversation filtering.
- Impact: Private memories can be sent to the LLM and echoed to an unauthorized user.
- Fix: Pass `workspace_role` and current user to `assemble_context`; filter memory hits before materialization with the existing memory visibility helper.

### H9. Notebook AI `study_asset` Scope Searches Project-Wide Documents

- Severity: High
- Location: `/Users/dog/Desktop/MRAI/apps/api/app/services/retrieval_orchestration.py:271`
- Evidence: `_retrieve_document_chunks` searches all embeddings for the project and does not constrain results to the current readable notebook or non-deleted visible assets.
- Impact: A user with access to one notebook in a shared project can cause chunks from other private notebooks/assets to enter the LLM prompt.
- Fix: Join chunks back to `StudyAsset`/`Notebook` or `DataItem`/`Dataset` and apply notebook readability and deletion filters before returning text.

### H10. One-Time Async Payments Grant Access Before Payment Is Paid

- Severity: High
- Location: `/Users/dog/Desktop/MRAI/apps/api/app/services/billing_webhook.py:191`
- Evidence: The one-time payment branch opens or extends a manual subscription on `checkout.session.completed` without checking `payment_status == "paid"` and without handling `async_payment_succeeded/failed`.
- Impact: Async payment methods such as Alipay/WeChat can grant paid entitlements while payment is pending or failed.
- Fix: Activate one-time plans only when `payment_status` is paid or on `checkout.session.async_payment_succeeded`; clear pending state on async failure.

### H11. Stripe Webhook Processing Failures Are Acknowledged And Non-Retryable

- Severity: High
- Location: `/Users/dog/Desktop/MRAI/apps/api/app/routers/billing.py:352`
- Evidence: The webhook inserts `BillingEvent`, commits, catches all processing exceptions, records `error`, then still returns HTTP 200. Replays hit the unique event ID and are skipped.
- Impact: Temporary Stripe/API/DB failures can permanently prevent activation, cancellation, or refund handling.
- Fix: Return 5xx on processing failure; only set `processed_at` on success; allow retry for events with `processed_at IS NULL` or `error IS NOT NULL`.

### H12. Unknown Stripe Statuses Can Leave Stale Paid Access

- Severity: High
- Location: `/Users/dog/Desktop/MRAI/apps/api/app/models/billing.py:68`, `/Users/dog/Desktop/MRAI/apps/api/app/services/billing_webhook.py:230`
- Evidence: The status constraint omits Stripe statuses such as `unpaid`, `paused`, and `incomplete_expired`; webhook updates write raw Stripe status.
- Impact: DB constraint failures are swallowed by the webhook path, leaving old active/past_due rows and entitlements in place.
- Fix: Map Stripe's full status set into internal statuses; only grant entitlements for explicitly allowed states; combine with retryable webhook failures.

### H13. AI Quota Check Releases Its Lock Before Usage Is Counted

- Severity: High
- Location: `/Users/dog/Desktop/MRAI/apps/api/app/core/entitlements.py:181`
- Evidence: `require_entitlement` locks the workspace row and counts usage, but chat paths commit messages/action logs before `AIUsageEvent` is inserted.
- Impact: Concurrent requests can all pass the same old count and consume model calls past `ai.actions.monthly`.
- Fix: Add an atomic quota reservation/counter before model calls, e.g. `UPDATE quota SET used = used + 1 WHERE used < limit`, then settle or retain the reservation after completion.

### H14. Storage Quota Has No Reservation Or Complete-Time Recheck

- Severity: High
- Location: `/Users/dog/Desktop/MRAI/apps/api/app/services/storage_quota.py:230`, `/Users/dog/Desktop/MRAI/apps/api/app/routers/uploads.py:119`
- Evidence: Quota only sums committed objects; pending presigned uploads live in `runtime_state`; `complete_upload` inserts the `DataItem` without rechecking quota.
- Impact: Parallel presigns can each pass quota but collectively exceed `storage.bytes.max`.
- Fix: Store pending upload reservations in the DB, lock per workspace, include reservations in usage, and recheck at completion before committing the item.

### H15. Cleanup Tasks Can Delete Active Datasets Or Projects If Invoked With IDs

- Severity: High
- Location: `/Users/dog/Desktop/MRAI/apps/api/app/tasks/worker_tasks.py:229`, `/Users/dog/Desktop/MRAI/apps/api/app/tasks/worker_tasks.py:252`
- Evidence: `cleanup_deleted_dataset` and `cleanup_deleted_project` do not defensively require `deleted_at IS NOT NULL` before marking records and deleting objects.
- Impact: A wrong, replayed, or forged task can permanently delete active data.
- Fix: Require `deleted_at` and expected cleanup status in worker queries and in `delete_project_permanently` as a defense-in-depth assertion.

### H16. Document Version Writes Are Race-Prone

- Severity: High
- Location: `/Users/dog/Desktop/MRAI/apps/api/app/services/document_versions.py:29`
- Evidence: Version number is computed as `max(version) + 1`; there is no unique constraint on `(data_item_id, version)` in the model/migration.
- Impact: Concurrent saves can produce duplicate version numbers and collide on the same snapshot key, corrupting version history.
- Fix: Add `UNIQUE(data_item_id, version)`, lock the `DataItem` or use an advisory lock while assigning versions, and retry on `IntegrityError`.

## Medium Findings

### M1. Preview, Content, And Indexing Paths Full-Buffer Large Objects

- Severity: Medium
- Location: `/Users/dog/Desktop/MRAI/apps/api/app/routers/datasets.py:127`, `/Users/dog/Desktop/MRAI/apps/api/app/routers/onlyoffice.py:123`, `/Users/dog/Desktop/MRAI/apps/api/app/tasks/worker_tasks.py:383`
- Evidence: S3 objects are read fully into memory for previews, ONLYOFFICE content, and document indexing.
- Impact: Concurrent previews or indexing of large files can create API/worker memory pressure.
- Fix: Stream S3 bodies, support Range where appropriate, and add preview/index size and concurrency limits.

### M2. PDF Annotation Payload Is Unbounded

- Severity: Medium
- Location: `/Users/dog/Desktop/MRAI/apps/api/app/routers/datasets.py:476`, `/Users/dog/Desktop/MRAI/apps/web/components/notebook/contents/PDFViewer.tsx:492`
- Evidence: `payload_json` is an arbitrary dict and frontend renders rects/colors from stored annotation payloads.
- Impact: Huge rect arrays can cause browser DoS; arbitrary color strings can create CSS-based external beacons depending on browser behavior.
- Fix: Use a strict schema for PDF highlights, cap rect/link/text lengths, numeric ranges, and allowlist colors.

### M3. Notebook/Study RAG Context Lacks Untrusted-Context Boundaries

- Severity: Medium
- Location: `/Users/dog/Desktop/MRAI/apps/api/app/services/retrieval_orchestration.py:391`, `/Users/dog/Desktop/MRAI/apps/api/app/services/study_context.py:68`
- Evidence: Page text, selected text, memories, related pages, chunks, and user questions are concatenated into system prompts without the untrusted delimiters present in `context_loader.build_system_prompt`.
- Impact: Uploaded documents or notes can inject instructions into higher-priority prompt context.
- Fix: Wrap user-origin content in explicit untrusted context tags and keep user questions in user-role messages rather than system prompt text.

### M4. Native `web_extractor` Enables Arbitrary URL Fetch Surface

- Severity: Medium
- Location: `/Users/dog/Desktop/MRAI/apps/api/app/services/orchestrator.py:604`
- Evidence: Any `http(s)` URL in user text can trigger provider-native `web_extractor` without app-side URL/IP policy.
- Impact: SSRF radius depends on the provider tool, but the app currently has no local denial of localhost/private/link-local/metadata addresses.
- Fix: Parse candidate URLs, deny private and local ranges and unusual schemes, and require explicit user intent before enabling extraction.

### M5. Discover Disabled Redirect Accepts Protocol-Relative URLs

- Severity: Medium
- Location: `/Users/dog/Desktop/MRAI/apps/web/lib/feature-flags.ts:9`, `/Users/dog/Desktop/MRAI/apps/web/proxy.ts:164`
- Evidence: `from=//attacker.example` passes `from.startsWith("/")`; `new URL(redirectTarget, request.url)` resolves it as an external URL.
- Impact: A first-party URL can trigger an external 307 redirect for phishing.
- Fix: Reject `//`, backslashes, absolute URLs, and non-console paths; normalize with `new URL` and require same origin.

### M6. CSP Nonce Is Not Available During Next.js SSR

- Severity: Medium
- Location: `/Users/dog/Desktop/MRAI/apps/web/proxy.ts:198`
- Evidence: The proxy generates a nonce after `NextResponse.next()` and writes only the response CSP; request headers used by SSR do not receive `x-nonce` or the CSP.
- Impact: Production non-local pages may fail to hydrate under CSP, or operators may weaken CSP to recover functionality.
- Fix: Build CSP before `NextResponse.next()`, set `x-nonce` and CSP on request headers, and also set CSP on the response.

### M7. Trial Checkout Can Be Raced Before Webhook Stamps Trial Use

- Severity: Medium
- Location: `/Users/dog/Desktop/MRAI/apps/api/app/routers/billing.py:124`
- Evidence: Active-subscription guard excludes `trialing`; `trial_used_at` is only written after a webhook.
- Impact: Multiple checkout sessions can receive 14-day trials before the first webhook updates local state.
- Fix: Reserve trial use atomically before creating checkout, include `trialing` in active-subscription blocking, and use workspace/customer idempotency keys.

### M8. Checkout Webhook Does Not Verify Customer Matches Metadata Workspace

- Severity: Medium
- Location: `/Users/dog/Desktop/MRAI/apps/api/app/services/billing_webhook.py:145`
- Evidence: The handler trusts `metadata.mrai_workspace_id` and does not verify `payload_obj.customer` against `CustomerAccount`.
- Impact: A valid Stripe event with mismatched customer/workspace metadata can apply entitlements to the wrong workspace.
- Fix: Require a matching `CustomerAccount(workspace_id, stripe_customer_id)` before applying a subscription/payment.

### M9. Notebook Page Memory Links Lack A Unique Constraint

- Severity: Medium
- Location: `/Users/dog/Desktop/MRAI/apps/api/app/tasks/worker_tasks.py:2245`, `/Users/dog/Desktop/MRAI/apps/api/app/models/notebooks.py:127`
- Evidence: Task code does check-then-insert but the table has no uniqueness constraint for the business key.
- Impact: Concurrent rebuilds can create duplicate page-memory links and duplicate UI/statistics output.
- Fix: Add an appropriate unique constraint and use insert-on-conflict semantics.

### M10. Study Asset Ingest Can Race And Duplicate Or Lose Chunks

- Severity: Medium
- Location: `/Users/dog/Desktop/MRAI/apps/api/app/services/study_pipeline.py:230`, `/Users/dog/Desktop/MRAI/apps/api/app/models/study.py:53`
- Evidence: Ingest deletes chunks then recreates them without locking the `StudyAsset`; `study_chunks` has only a non-unique index on `(asset_id, chunk_index)`.
- Impact: Retry/concurrent ingest can interleave deletes and inserts, producing duplicate indexes or missing chunks.
- Fix: Lock the asset, add `UNIQUE(asset_id, chunk_index)`, and add an idempotent ingest run key.

### M11. Same-Origin Image Preview Iframe Needs Defense In Depth

- Severity: Medium
- Location: `/Users/dog/Desktop/MRAI/apps/web/components/notebook/contents/ReferenceDocumentWindow.tsx:389`
- Evidence: Image previews are rendered in an unsandboxed same-origin iframe.
- Impact: Current backend validation blocks SVG/HTML previews, but any legacy or misclassified active content served inline could run same-origin.
- Fix: Render images with `<img>`, or sandbox the iframe without `allow-scripts`/`allow-same-origin`; keep backend SVG/HTML preview rejection.

## Low Findings

### L1. Presigned Download Does Not Force Octet-Stream Despite Comment

- Severity: Low
- Location: `/Users/dog/Desktop/MRAI/apps/api/app/services/storage.py:191`
- Evidence: The comment says downloads force `ResponseContentType=application/octet-stream`, but generated params only set `ResponseContentDisposition`.
- Impact: If a legacy/miswritten HTML/SVG/XML object reaches the download path, stored `Content-Type` may remain visible to clients.
- Fix: Add `ResponseContentType="application/octet-stream"` for download presigned URLs.

### L2. Frontend Google OAuth Link Does Not Reuse Local `next` Sanitizer

- Severity: Low
- Location: `/Users/dog/Desktop/MRAI/apps/web/components/auth/GoogleSignInButton.tsx:47`
- Evidence: The button forwards raw `next` query text to backend authorize. The backend currently validates via `is_safe_redirect_path`, so this is defense-in-depth rather than an active open redirect.
- Impact: Future backend regression would expose OAuth redirect risk.
- Fix: Apply `getSafeNavigationPath(rawNext) ?? "/app"` in the frontend too.

## Verification Notes

- Billing sub-agent ran `uv run pytest -q tests/test_billing_webhook.py tests/test_billing_abuse_fixes.py`: 20 passing.
- Billing sub-agent ran `uv run pytest -q tests/test_chat_quota_gates.py tests/test_quota_enforcement.py`: 16 passing.
- `tests/test_plan_entitlements.py` currently has 2 stale test failures because it still expects 8 entitlement keys while code now includes `storage.bytes.max` as a ninth key.
- No full test suite was run for this review.

## Recommended Fix Order

1. Fix data-leak paths first: C1, C2, H7, H8, H9, H6.
2. Fix ONLYOFFICE SSRF/edit/quota issues: H1, H2, H5, H3.
3. Fix billing correctness: H10, H11, H12, M7, M8.
4. Add atomic quota reservations: H13 and H14.
5. Harden workers/cleanup/versioning: H15, H16, M9, M10.
6. Address prompt-injection and frontend defense-in-depth: M3, M4, M5, M6, M11, L1, L2.
