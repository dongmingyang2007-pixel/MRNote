# S6 Billing — Design Spec

**Date:** 2026-04-17
**Status:** approved
**Depends on:** S5 (commit `6638976`), S7 (commit `d985427`), main `945d0c1`

## 1. Goal

Ship Stripe-backed subscription billing for MRAI: 4 plans (Free / Pro / Power / Team), 8 entitlement keys gating real product capabilities, Stripe Checkout / Customer Portal / Webhook integration, and a one-time payment fallback for Alipay / WeChat (until Stripe approves recurring for those payment methods).

## 2. Plans, prices, and Stripe IDs

All prices are **livemode** (Stripe account `acct_1TFnGoRzO5cz1hgY` "铭润科技"), USD, billed per-license except Team which is per-seat.

| Plan | Monthly Price | Yearly Price | Stripe Product | Stripe Price (monthly) | Stripe Price (yearly) |
|---|---|---|---|---|---|
| Free | — | — | — | — | — |
| Pro | $10 | $102 | `prod_ULxidFvV2ivzrz` | `price_1TNFnSRzO5cz1hgYP5J3Ez3h` | `price_1TNFnWRzO5cz1hgYqPbchdne` |
| Power | $25 | $255 | `prod_ULxiNIox1PRZaw` | `price_1TNFncRzO5cz1hgYvZ4UkVlP` | `price_1TNFnhRzO5cz1hgYxQUJh6aL` |
| Team | $15/seat | $153/seat/year | `prod_ULxi7uvs66Dup5` | `price_1TNFnmRzO5cz1hgYpqQBCs8s` | `price_1TNFnrRzO5cz1hgYPFabWMpM` |

Yearly applies a 15% discount vs paying monthly.

Free is the default — no Stripe customer created until first paid checkout.

## 3. Plan ↔ entitlement mapping

`apps/api/app/services/plan_entitlements.py` (constants, NOT in DB so the same source of truth in code and runtime cache):

```python
PLAN_ENTITLEMENTS: dict[str, dict[str, int | bool]] = {
    "free": {
        "notebooks.max": 1,
        "pages.max": 50,
        "study_assets.max": 1,
        "ai.actions.monthly": 50,
        "book_upload.enabled": False,
        "daily_digest.enabled": False,
        "voice.enabled": False,
        "advanced_memory_insights.enabled": False,
    },
    "pro": {
        "notebooks.max": -1,        # -1 means unlimited
        "pages.max": 500,
        "study_assets.max": 20,
        "ai.actions.monthly": 1000,
        "book_upload.enabled": True,
        "daily_digest.enabled": True,
        "voice.enabled": True,
        "advanced_memory_insights.enabled": False,
    },
    "power": {
        "notebooks.max": -1,
        "pages.max": -1,
        "study_assets.max": -1,
        "ai.actions.monthly": 10000,
        "book_upload.enabled": True,
        "daily_digest.enabled": True,
        "voice.enabled": True,
        "advanced_memory_insights.enabled": True,
    },
    "team": {
        # Same caps as Power, plus per-seat licensing handled at the
        # subscriptions table level (not as an entitlement key).
        "notebooks.max": -1,
        "pages.max": -1,
        "study_assets.max": -1,
        "ai.actions.monthly": 10000,
        "book_upload.enabled": True,
        "daily_digest.enabled": True,
        "voice.enabled": True,
        "advanced_memory_insights.enabled": True,
    },
}
```

## 4. Subscription scoping

**All plans are workspace-scoped.** `Workspace.plan` field already exists (string default `"free"`); this design upgrades the field to be the durable resolved plan after webhook events apply.

`Membership.role == "owner"` (and `"admin"` if the role exists in code) is required to call mutation billing endpoints (checkout, portal, cancel). Read endpoints (`/billing/me`, `/billing/plans`) require any active workspace member.

## 5. Data model (5 new tables, 0 new columns on existing)

Reuses: `AIUsageEvent` (S1) as the source of `ai.actions.monthly` counts. `Workspace.plan` keeps existing column.

### 5.1 `customer_accounts`

One Stripe customer per workspace (only created at first paid checkout):

```
id                   VARCHAR(36) PK
workspace_id         FK workspaces ON DELETE CASCADE — UNIQUE
stripe_customer_id   VARCHAR(64) UNIQUE
email                VARCHAR(320)
default_payment_method_id  VARCHAR(64) NULL
created_at, updated_at     TIMESTAMPTZ
```

### 5.2 `subscriptions`

```
id                          VARCHAR(36) PK
workspace_id                FK workspaces ON DELETE CASCADE
stripe_subscription_id      VARCHAR(64) UNIQUE NULL  -- NULL when provider != stripe_recurring
plan                        VARCHAR(20)  CHECK plan IN ('free','pro','power','team')
billing_cycle               VARCHAR(10)  CHECK IN ('monthly','yearly','none')
status                      VARCHAR(20)  CHECK IN ('active','past_due','canceled','trialing','manual','incomplete')
provider                    VARCHAR(20)  CHECK IN ('stripe_recurring','stripe_one_time','free')
current_period_start        TIMESTAMPTZ NULL
current_period_end          TIMESTAMPTZ NULL  -- end of paid period; nightly task downgrades to free after this
seats                       INT  DEFAULT 1  -- only meaningful for plan=team
cancel_at_period_end        BOOLEAN  DEFAULT FALSE
created_at, updated_at      TIMESTAMPTZ
```

Indexes: `(workspace_id)`, `(stripe_subscription_id)`, `(current_period_end)` for the nightly downgrade scan.

A workspace may have multiple historical rows; the **active** subscription is the one with `status IN ('active','past_due','trialing','manual')` ordered by `created_at DESC`. Free plan is implicit when no active row exists.

### 5.3 `subscription_items`

```
id                            VARCHAR(36) PK
subscription_id               FK subscriptions ON DELETE CASCADE
stripe_subscription_item_id   VARCHAR(64) UNIQUE NULL  -- NULL for one_time
stripe_price_id               VARCHAR(64) NOT NULL
quantity                      INT  DEFAULT 1
created_at                    TIMESTAMPTZ
```

For Team plans, `quantity` = seat count.

### 5.4 `entitlements`

Cache of resolved entitlements per workspace (refreshed on plan change). Allows admin overrides + fast lookup.

```
id            VARCHAR(36) PK
workspace_id  FK workspaces ON DELETE CASCADE
key           VARCHAR(80) NOT NULL
value_int     INT NULL    -- e.g. notebooks.max=50, -1=unlimited
value_bool    BOOLEAN NULL  -- e.g. voice.enabled=true
expires_at    TIMESTAMPTZ NULL  -- for time-limited grants
source        VARCHAR(20)  CHECK IN ('plan','admin_override','trial')
created_at, updated_at  TIMESTAMPTZ
UNIQUE (workspace_id, key)
```

### 5.5 `billing_events`

Webhook idempotency.

```
id                VARCHAR(36) PK
stripe_event_id   VARCHAR(64) UNIQUE NOT NULL
event_type        VARCHAR(80) NOT NULL
payload_json      JSON NOT NULL
processed_at      TIMESTAMPTZ NULL  -- NULL while in flight
error             TEXT NULL
created_at        TIMESTAMPTZ
```

Insert with `INSERT ... ON CONFLICT DO NOTHING` to short-circuit duplicate webhook deliveries.

## 6. API endpoints

All under `/api/v1/billing`. All require auth (`get_current_user` + `get_current_workspace_id`) except the webhook.

### 6.1 `POST /api/v1/billing/checkout`

Body: `{ plan: "pro"|"power"|"team", cycle: "monthly"|"yearly", seats?: int }` (`seats` only valid for `team`, default 1, min 1, max 100).

Auth: `require_workspace_admin` (member with role `owner` or `admin`).

Flow:
1. Lookup or create `customer_accounts` row + Stripe customer.
2. `stripe.checkout.Session.create(mode="subscription", line_items=[{price: <mapped>, quantity: seats}], success_url, cancel_url, customer=<id>)`.
3. Return `{ checkout_url: session.url }`.

CSRF required.

### 6.2 `POST /api/v1/billing/checkout-onetime`

Body: `{ plan: "pro"|"power"|"team", cycle: "monthly"|"yearly", payment_method: "alipay"|"wechat_pay", seats?: int }`.

Same auth as 6.1.

Flow: `stripe.checkout.Session.create(mode="payment", line_items=[...], payment_method_types=[<pm>], ...)`. The line item amount is hardcoded server-side from `PLAN_ENTITLEMENTS` price table (since one-time mode can't reuse Stripe `recurring` Price IDs directly — we create a one-time `price_data` inline).

### 6.3 `POST /api/v1/billing/portal`

Auth: `require_workspace_admin`. Creates a Stripe Billing Portal session with `return_url` = `settings.stripe_billing_portal_return_url`. Returns `{ portal_url }`. CSRF required.

### 6.4 `POST /api/v1/billing/webhook`

No auth. Stripe-hosted POST.

Verifies `Stripe-Signature` header against `settings.stripe_webhook_secret`. Idempotency: insert `billing_events` row with `stripe_event_id` UNIQUE. On conflict, return 200 immediately.

Handles 5 events:

| Event | Action |
|---|---|
| `checkout.session.completed` (mode=subscription) | Create `subscriptions` row + items, set `Workspace.plan`, refresh `entitlements` |
| `checkout.session.completed` (mode=payment) | Create `subscriptions` row with `provider="stripe_one_time"`, `status="manual"`, `current_period_end=now+30d/365d`; same plan + entitlement update |
| `customer.subscription.updated` | Update plan / status / current_period_end / cancel_at_period_end on matching `subscriptions` row; refresh entitlements. `cancel_at_period_end=true` does NOT immediately downgrade — Workspace.plan stays current until `current_period_end` is reached and `customer.subscription.deleted` fires |
| `customer.subscription.deleted` | Mark `status="canceled"`, set `Workspace.plan="free"`, refresh entitlements |
| `invoice.paid` | Update `subscriptions.current_period_end` to renewal date |
| `invoice.payment_failed` | Mark `status="past_due"`, do NOT immediately downgrade (Stripe Smart Retries handles it) |

Returns 200 even on internal errors (Stripe retries 4xx/5xx — we want at-most-once via idempotency table not at-least-once).

### 6.5 `GET /api/v1/billing/me`

Auth: any active member.

Returns:
```json
{
  "plan": "pro",
  "status": "active",
  "billing_cycle": "monthly",
  "current_period_end": "2026-05-17T00:00:00Z",
  "seats": 1,
  "cancel_at_period_end": false,
  "provider": "stripe_recurring",
  "entitlements": {
    "notebooks.max": -1,
    "pages.max": 500,
    "study_assets.max": 20,
    "ai.actions.monthly": 1000,
    "book_upload.enabled": true,
    "daily_digest.enabled": true,
    "voice.enabled": true,
    "advanced_memory_insights.enabled": false
  },
  "usage_this_month": {
    "ai.actions": 437,
    "notebooks": 3,
    "pages": 87,
    "study_assets": 12
  }
}
```

### 6.6 `GET /api/v1/billing/plans`

No auth (public marketing data).

Returns the static plan descriptors (name, price, features, entitlements) so the frontend pricing page doesn't hardcode them. Source: `PLAN_ENTITLEMENTS` + Stripe Price IDs from `settings.stripe_price_ids`.

## 7. Entitlement gate mechanism

`apps/api/app/core/entitlements.py`:

```python
def require_entitlement(
    key: str,
    *,
    count_field: str | None = None,  # for cumulative caps like notebooks.max
) -> Callable
```

Returns a FastAPI Depends function. Two modes:

- **Boolean entitlement** (e.g. `voice.enabled`): if `value_bool is False`, raise `ApiError("plan_required", ..., status_code=402)`.
- **Counted entitlement** (e.g. `notebooks.max`): query current usage via `count_field` resolver (e.g. `notebooks_count(workspace_id)`); if `current >= value_int and value_int != -1`, raise `ApiError("plan_limit_reached", ..., status_code=402, details={"current": ..., "limit": ...})`.

`-1` means unlimited (skip cap check).

`ai.actions.monthly` uses a **rolling-month aggregator** over `AIUsageEvent` (S1's table), not stored counters, to avoid carrying a separate ledger.

### 7.1 Application points (8 entitlements)

| Entitlement | Router file | Endpoint(s) |
|---|---|---|
| `notebooks.max` | `routers/notebooks.py` | POST `/api/v1/notebooks` |
| `pages.max` | `routers/notebooks.py` | POST `/api/v1/notebooks/{id}/pages` |
| `study_assets.max` | `routers/study.py` | POST `/api/v1/notebooks/{id}/study-assets` |
| `ai.actions.monthly` | `routers/notebook_ai.py` and `routers/study_ai.py` | All POST endpoints (selection-action, page-action, brainstorm, ask, generate-page, study/ask, study/quiz, study/flashcards) |
| `book_upload.enabled` | `routers/study.py` | POST `/api/v1/notebooks/{id}/study-assets` (combined with `study_assets.max`) |
| `daily_digest.enabled` | `routers/proactive.py` | `POST /generate-now` and Celery task at fan-out time |
| `voice.enabled` | `routers/realtime.py` | WS connect handler |
| `advanced_memory_insights.enabled` | `routers/memory.py` | GET `/memory/{id}/explain`, GET `/memory/{id}/subgraph` |

When 402 raised, response body uses standard `{ error: { code, message, details } }` shape so the frontend can recognize and route to the upgrade modal.

## 8. One-time payment flow (Alipay / WeChat)

WeChat Pay does not support Stripe subscription mode. Alipay subscription is invite-only. Until Stripe approves recurring for this account, we offer a one-time variant:

```
User on /settings/billing picks "Pro Monthly via Alipay"
  ↓
Frontend calls POST /api/v1/billing/checkout-onetime
  { plan: "pro", cycle: "monthly", payment_method: "alipay" }
  ↓
Backend creates Stripe Checkout Session (mode=payment, payment_method_types=["alipay"])
  with line_items = [{ price_data: { unit_amount: 1000, currency: "usd",
                                     product: prod_ULxidFvV2ivzrz,
                                     recurring: None }, quantity: 1 }]
  ↓
Returns checkout_url; frontend redirects user.
  ↓
User scans Alipay QR → pays.
  ↓
Stripe webhook checkout.session.completed (mode=payment)
  ↓
Backend creates subscriptions row:
  provider="stripe_one_time"
  status="manual"
  plan="pro"
  current_period_end = now + (30d if monthly else 365d)
Workspace.plan = "pro"; entitlements refreshed.
```

### Expiry handling

New Celery beat task `expire_one_time_subscriptions` (daily at 02:15):

```
SELECT * FROM subscriptions
  WHERE provider='stripe_one_time'
    AND status='manual'
    AND current_period_end < now()

→ For each: set status='canceled',
            Workspace.plan='free' (only if this was the workspace's active sub),
            refresh entitlements,
            optionally enqueue email reminder
```

Pre-expiry reminder (T-7 days, T-1 day) is **out of scope** for S6 — leaves an in-app banner + entry in the proactive digest as the only nudge.

## 9. Frontend

### 9.1 New pages / components

```
apps/web/app/[locale]/workspace/settings/billing/page.tsx
  → top of page: <CurrentSubscription /> (plan + status + manage button)
  → middle: <UsageMeter /> (monthly AI actions used / cap, page count / cap)
  → bottom: <PlansGrid /> (4 PlanCards: Free / Pro / Power / Team, with month/year toggle)

apps/web/components/billing/
  ├── PlanCard.tsx          ← single plan card with feature checklist + upgrade button
  ├── PlansGrid.tsx         ← grid of 4 PlanCards + cycle toggle
  ├── CurrentSubscription.tsx  ← current plan summary + portal button
  ├── UsageMeter.tsx        ← progress bars for counted entitlements
  ├── UpgradeModal.tsx      ← global modal that shows when a 402 is intercepted; sends user to checkout
  └── PaymentMethodPicker.tsx  ← choose Card / Alipay / WeChat (only Card if subscription, all 3 if one-time)
```

### 9.2 Hooks

```
apps/web/hooks/
  ├── useBillingMe.ts         ← fetches /billing/me (also exposes resolved entitlements)
  ├── useEntitlement.ts       ← useEntitlement("voice.enabled") -> { allowed, limit?, current? }
  └── useUpgradePrompt.ts     ← global event-bus hook: on 402, fire and UpgradeModal listens
```

### 9.3 Sidebar plan badge

`NotebookSidebar.tsx` settings tab gets a small badge showing current plan (Free / Pro / Power / Team). Click → goes to `/settings/billing`.

### 9.4 402 interception

`apps/web/lib/api.ts` `apiRequest` already handles 401 → re-auth. Add 402 → emit `mrai:plan-required` custom event with `{ code, message, details }`. `UpgradeModal` listens and shows.

### 9.5 i18n

- `apps/web/messages/en/console.json` + `zh/console.json`: `nav.billing`, plan labels.
- `apps/web/messages/en/billing.json` + `zh/billing.json` (new namespace): plan names, feature labels, upgrade copy, cycle labels, payment method labels.

## 10. Stripe SDK + config

### 10.1 Backend deps

`apps/api/pyproject.toml` add:
```toml
stripe = "^10.0.0"
```

### 10.2 `apps/api/app/core/config.py` new fields

```python
stripe_api_key: str = Field(default="", env="STRIPE_API_KEY")
stripe_webhook_secret: str = Field(default="", env="STRIPE_WEBHOOK_SECRET")
stripe_publishable_key: str = Field(default="", env="STRIPE_PUBLISHABLE_KEY")
stripe_billing_portal_return_url: str = Field(
    default="http://localhost:3000/workspace/settings/billing",
    env="STRIPE_BILLING_PORTAL_RETURN_URL",
)
# NOTE: production deployments MUST override stripe_billing_portal_return_url
# via env var to point to the public domain; the localhost default is for dev only.
# Hardcoded Price IDs (live mode); env override for test isolation
stripe_price_pro_monthly: str = Field(default="price_1TNFnSRzO5cz1hgYP5J3Ez3h", env="STRIPE_PRICE_PRO_MONTHLY")
stripe_price_pro_yearly: str = Field(default="price_1TNFnWRzO5cz1hgYqPbchdne", env="STRIPE_PRICE_PRO_YEARLY")
stripe_price_power_monthly: str = Field(default="price_1TNFncRzO5cz1hgYvZ4UkVlP", env="STRIPE_PRICE_POWER_MONTHLY")
stripe_price_power_yearly: str = Field(default="price_1TNFnhRzO5cz1hgYxQUJh6aL", env="STRIPE_PRICE_POWER_YEARLY")
stripe_price_team_monthly: str = Field(default="price_1TNFnmRzO5cz1hgYpqQBCs8s", env="STRIPE_PRICE_TEAM_MONTHLY")
stripe_price_team_yearly: str = Field(default="price_1TNFnrRzO5cz1hgYPFabWMpM", env="STRIPE_PRICE_TEAM_YEARLY")
```

### 10.3 Frontend deps

`apps/web/package.json` add:
```json
"@stripe/stripe-js": "^4.0.0"
```

(`@stripe/react-stripe-js` is not strictly required since we use redirect-to-checkout, not Elements.)

### 10.4 `apps/api/app/services/stripe_client.py`

Initializes the SDK from settings, exposes thin wrappers used by the router:
- `create_checkout_session_subscription(...)`
- `create_checkout_session_one_time(...)`
- `create_billing_portal_session(...)`
- `verify_webhook(payload_bytes, sig_header)`

Wrapping keeps the router stateless and the Stripe API calls easy to mock in tests.

## 11. Error handling

| Condition | Behavior |
|---|---|
| User's plan doesn't include feature | 402 `plan_required` with `details: {key}` |
| Counted limit reached | 402 `plan_limit_reached` with `details: {key, current, limit}` |
| Webhook signature invalid | 400 `webhook_invalid_signature` (Stripe retries) |
| Webhook duplicate | 200 (idempotent skip) |
| Stripe API failure during checkout creation | 502 `stripe_unavailable` with `retry_after: 30` |
| User without owner/admin role calls mutation endpoint | 403 `forbidden` |
| Non-member calls any billing endpoint | 404 `not_found` (avoid existence leak) |
| `seats` out of range for non-team plan | 400 `invalid_input` |
| Webhook handler internal error | 200 with `error` recorded in `billing_events.error` (Stripe doesn't retry; admin can replay manually) |

## 12. Tests

### 12.1 Backend (~30 tests)

| File | Cases |
|---|---|
| `tests/test_billing_models.py` | 5 tables instantiate, UNIQUE constraints, defaults |
| `tests/test_plan_entitlements.py` | All 4 plans have all 8 keys; -1 means unlimited; PLAN_ENTITLEMENTS is the single source of truth |
| `tests/test_entitlement_gate.py` | require_entitlement: count cap triggers 402, bool cap triggers 402, -1 skips, admin override wins, expired override falls back to plan |
| `tests/test_billing_checkout.py` | POST /checkout creates Stripe customer + session (Stripe API mocked), missing role → 403, invalid plan → 400, seats default 1, team seats 5 → quantity=5 |
| `tests/test_billing_checkout_onetime.py` | Alipay / WeChat path uses payment mode, line_items.price_data correct, recurring=None, success creates manual subscription with current_period_end=now+30d/365d |
| `tests/test_billing_webhook.py` | Signature verify success / fail; idempotency (same event twice → no double-write); 5 event types each create/update correctly |
| `tests/test_billing_portal.py` | POST /portal returns Stripe portal URL; non-admin → 403 |
| `tests/test_billing_me.py` | Returns plan + entitlements + usage_this_month; cross-workspace 404 |
| `tests/test_billing_plans.py` | GET /plans returns 4 entries with prices and entitlements; matches PLAN_ENTITLEMENTS constants |
| `tests/test_quota_enforcement.py` | Each of 8 entitlements actually fires the gate on its endpoint |
| `tests/test_one_time_expiry_task.py` | Nightly task expires `current_period_end < now`, downgrades workspace plan, idempotent on rerun |

Coverage target ≥ 80% on `services/plan_entitlements.py`, `services/stripe_client.py`, `core/entitlements.py`, `routers/billing.py`.

### 12.2 Frontend (~5 tests)

| File | Cases |
|---|---|
| `tests/unit/billing-page.test.tsx` | Renders 4 plan cards, current plan highlighted |
| `tests/unit/plan-card.test.tsx` | Free has no upgrade button; paid plans have it; click → fires checkout |
| `tests/unit/use-entitlement.test.ts` | bool entitlement returns allowed; counted with current<limit allowed; with current>=limit denied |
| `tests/unit/upgrade-modal.test.tsx` | Listens for `mrai:plan-required` event and renders |
| `tests/s6-billing.spec.ts` | Playwright skeleton: navigate to /settings/billing, see plans, click Pro upgrade → asserts redirect call (don't actually go to Stripe) |

## 13. Scope boundaries (explicitly out of S6)

- **Pre-expiry email reminders** for one-time subscriptions (in-app banner only)
- **Trials** (no free trial flow; immediate paid)
- **Proration UI** (Stripe handles it server-side; we don't surface preview math)
- **Multi-currency** (USD only; CNY display via Stripe's customer-side conversion only)
- **Refund self-serve** (must email support; admin issues via Stripe dashboard)
- **Coupons / promo codes** (can add via Stripe Checkout `allow_promotion_codes=true` later)
- **Usage-based / metered billing** (UsageEvent table is recorded but not billed)
- **Team seat invite flow** (Team plan unblocks the entitlements; existing Membership invite path is separate)
- **Tax handling** (Stripe Tax integration left as follow-up)
- **Failed-payment dunning** (rely on Stripe Smart Retries default)
- **Plan downgrade proration** (default Stripe behavior)
- **Soft-delete vs hard-delete on workspace** (existing `cleanup_deleted_project` task handles fan-out)

## 14. Phasing outline (refined in plan)

| Phase | Focus |
|---|---|
| A | Stripe SDK install + config + customer_accounts table |
| B | subscriptions / subscription_items / entitlements / billing_events tables + Alembic migration |
| C | plan_entitlements.py constants + entitlement resolver + 4 unit tests |
| D | stripe_client.py wrapper + 4 billing API endpoints (checkout, checkout-onetime, portal, me, plans) |
| E | webhook handler + 5 event types + idempotency + 6 tests |
| F | One-time expiry Celery task + beat schedule |
| G | require_entitlement Depends + apply at all 8 enforcement points + per-gate tests |
| H | Backend regression |
| I | Frontend settings/billing page + PlansGrid + PlanCard + UpgradeModal |
| J | useBillingMe / useEntitlement / useUpgradePrompt hooks + 402 interception in api.ts |
| K | Sidebar plan badge + i18n (console + new billing namespace) |
| L | vitest + Playwright skeleton |
| M | Final coverage + smoke |

## 15. References

- Product spec: `MRAI_notebook_ai_os_build_spec.md` §15 (计费与收费)
- Stripe account: `acct_1TFnGoRzO5cz1hgY` (铭润科技)
- Stripe Dashboard: https://dashboard.stripe.com/acct_1TFnGoRzO5cz1hgY
- Predecessors merged to main:
  - S1 `AIActionLog` + `AIUsageEvent` (usage ledger reused)
  - S5 Proactive Services (`daily_digest.enabled` gate point)
  - S7 Search (no direct dependency)
- Reuses: `AIUsageEvent` (S1) for ai.actions counter; `Workspace.plan` field; `Membership.role` for billing permission.
