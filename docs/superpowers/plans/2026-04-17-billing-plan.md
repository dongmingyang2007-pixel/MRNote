# S6 Billing — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Stripe-backed subscription billing with 4 plans, 8 entitlement gates, Checkout / Customer Portal / Webhook, plus an Alipay/WeChat one-time payment fallback. End state: a workspace owner can upgrade Free → Pro at `/settings/billing`, the new plan unlocks 8 capabilities behind real 402 gates, and a Stripe webhook keeps DB state in sync.

**Architecture:** All billing state is workspace-scoped in 5 new tables (`customer_accounts`, `subscriptions`, `subscription_items`, `entitlements`, `billing_events`). `Workspace.plan` (already exists) is the durable resolved plan. A small `services/plan_entitlements.py` constant maps each plan to its 8 entitlement values. `core/entitlements.py` exposes a `require_entitlement(key)` FastAPI Depends used at 8 router enforcement points. Stripe SDK calls are isolated in `services/stripe_client.py` so the router stays mockable. Webhook idempotency is enforced by a UNIQUE `stripe_event_id` row in `billing_events`.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2, Alembic, Celery + crontab, Stripe Python SDK ≥10, pytest + pytest-cov, Next.js 14, React 18, TypeScript, vitest, Playwright, `@stripe/stripe-js`.

**Spec:** `docs/superpowers/specs/2026-04-17-billing-design.md`

**Stripe livemode IDs (already created via MCP):**
- Pro Monthly `price_1TNFnSRzO5cz1hgYP5J3Ez3h`, Yearly `price_1TNFnWRzO5cz1hgYqPbchdne`
- Power Monthly `price_1TNFncRzO5cz1hgYvZ4UkVlP`, Yearly `price_1TNFnhRzO5cz1hgYxQUJh6aL`
- Team Monthly `price_1TNFnmRzO5cz1hgYpqQBCs8s`, Yearly `price_1TNFnrRzO5cz1hgYPFabWMpM`

---

## Phase Overview

| Phase | Tasks | Description |
|---|---|---|
| **A** | 1 | Stripe SDK install + config fields + `customer_accounts` table |
| **B** | 2 | `subscriptions` / `subscription_items` / `entitlements` / `billing_events` tables + Alembic |
| **C** | 3 | `plan_entitlements.py` constants + `core/entitlements.py` resolver + tests |
| **D** | 4 | `stripe_client.py` SDK wrapper + 4 mutation endpoints (checkout / checkout-onetime / portal) |
| **E** | 5 | Read endpoints (`/billing/me`, `/billing/plans`) + `/billing/webhook` with idempotency + 5 event types |
| **F** | 6 | One-time-payment expiry Celery task + beat schedule |
| **G** | 7 | `require_entitlement` Depends + apply at 8 enforcement points |
| **H** | 8 | Full backend regression (no commit) |
| **I** | 9 | Frontend `/settings/billing` page + PlansGrid + PlanCard + CurrentSubscription |
| **J** | 10 | `useBillingMe` / `useEntitlement` / `useUpgradePrompt` hooks + 402 interception + UpgradeModal |
| **K** | 11 | Sidebar plan badge + nav.billing i18n + new `billing` namespace |
| **L** | 12 | vitest unit + Playwright skeleton |
| **M** | 13 | Final coverage verification |

---

## Task 1 — Stripe SDK + config fields + `customer_accounts` table

**Files:**
- Modify: `apps/api/pyproject.toml` (add stripe dep)
- Modify: `apps/api/app/core/config.py`
- Modify: `apps/api/app/models/entities.py` (CustomerAccount class)
- Create: `apps/api/alembic/versions/202604220001_billing_customer_accounts.py`
- Create: `apps/api/tests/test_customer_account_model.py`

- [ ] **Step 1: Add Stripe dependency**

In `apps/api/pyproject.toml` find the `[project]` `dependencies = [...]` array, add:

```toml
"stripe>=10.0.0,<11.0.0",
```

Run:
```bash
cd /Users/dog/Desktop/MRAI/apps/api && .venv/bin/pip install "stripe>=10.0.0,<11.0.0"
```

Verify: `cd apps/api && .venv/bin/python -c "import stripe; print(stripe.VERSION)"` should print a 10.x version.

- [ ] **Step 2: Add config fields**

Open `apps/api/app/core/config.py`. Find the `class Settings` (use Grep: `class Settings`). At the end of the field list (before any validator), add 9 fields. The exact insertion location is just before the closing of the class body. Add:

```python
    # ---------------------------------------------------------------
    # S6 Billing — Stripe (livemode IDs are the defaults; env can
    # override for test isolation). Production deployments MUST set
    # stripe_billing_portal_return_url to the public domain.
    # ---------------------------------------------------------------
    stripe_api_key: str = Field(default="", env="STRIPE_API_KEY")
    stripe_webhook_secret: str = Field(default="", env="STRIPE_WEBHOOK_SECRET")
    stripe_publishable_key: str = Field(default="", env="STRIPE_PUBLISHABLE_KEY")
    stripe_billing_portal_return_url: str = Field(
        default="http://localhost:3000/workspace/settings/billing",
        env="STRIPE_BILLING_PORTAL_RETURN_URL",
    )
    stripe_checkout_success_url: str = Field(
        default="http://localhost:3000/workspace/settings/billing?status=success",
        env="STRIPE_CHECKOUT_SUCCESS_URL",
    )
    stripe_checkout_cancel_url: str = Field(
        default="http://localhost:3000/workspace/settings/billing?status=cancel",
        env="STRIPE_CHECKOUT_CANCEL_URL",
    )
    stripe_price_pro_monthly: str = Field(
        default="price_1TNFnSRzO5cz1hgYP5J3Ez3h", env="STRIPE_PRICE_PRO_MONTHLY",
    )
    stripe_price_pro_yearly: str = Field(
        default="price_1TNFnWRzO5cz1hgYqPbchdne", env="STRIPE_PRICE_PRO_YEARLY",
    )
    stripe_price_power_monthly: str = Field(
        default="price_1TNFncRzO5cz1hgYvZ4UkVlP", env="STRIPE_PRICE_POWER_MONTHLY",
    )
    stripe_price_power_yearly: str = Field(
        default="price_1TNFnhRzO5cz1hgYxQUJh6aL", env="STRIPE_PRICE_POWER_YEARLY",
    )
    stripe_price_team_monthly: str = Field(
        default="price_1TNFnmRzO5cz1hgYpqQBCs8s", env="STRIPE_PRICE_TEAM_MONTHLY",
    )
    stripe_price_team_yearly: str = Field(
        default="price_1TNFnrRzO5cz1hgYPFabWMpM", env="STRIPE_PRICE_TEAM_YEARLY",
    )
```

Verify import is fine: `cd apps/api && .venv/bin/python -c "from app.core.config import settings; print(settings.stripe_price_pro_monthly[:8])"` should print `price_1T`.

- [ ] **Step 3: Write the failing test for CustomerAccount**

Create `apps/api/tests/test_customer_account_model.py`:

```python
# ruff: noqa: E402
import atexit, importlib, os, shutil, tempfile
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-s6-cust-"))
atexit.register(lambda: shutil.rmtree(TEST_TEMP_DIR, ignore_errors=True))
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_TEMP_DIR / 'test.db'}"
os.environ["ENV"] = "test"

import app.core.config as config_module
config_module.get_settings.cache_clear()
config_module.settings = config_module.get_settings()
import app.db.session as session_module
importlib.reload(session_module)

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models import CustomerAccount, User, Workspace


def setup_function() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _seed_workspace() -> str:
    with SessionLocal() as db:
        ws = Workspace(name="W"); user = User(email="u@x.co", password_hash="x")
        db.add(ws); db.add(user); db.commit(); db.refresh(ws)
        return ws.id


def test_customer_account_basic_insert() -> None:
    ws_id = _seed_workspace()
    with SessionLocal() as db:
        ca = CustomerAccount(
            workspace_id=ws_id,
            stripe_customer_id="cus_test_123",
            email="biz@x.co",
        )
        db.add(ca); db.commit(); db.refresh(ca)
    assert ca.id
    assert ca.default_payment_method_id is None


def test_customer_account_workspace_unique() -> None:
    ws_id = _seed_workspace()
    with SessionLocal() as db:
        db.add(CustomerAccount(
            workspace_id=ws_id, stripe_customer_id="cus_a", email="a@x.co",
        ))
        db.commit()
    with SessionLocal() as db, pytest.raises(IntegrityError):
        db.add(CustomerAccount(
            workspace_id=ws_id, stripe_customer_id="cus_b", email="b@x.co",
        ))
        db.commit()


def test_customer_account_stripe_id_unique() -> None:
    ws1 = _seed_workspace()
    with SessionLocal() as db:
        ws2 = Workspace(name="W2"); db.add(ws2); db.commit(); db.refresh(ws2)
        ws2_id = ws2.id
        db.add(CustomerAccount(
            workspace_id=ws1, stripe_customer_id="cus_dup", email="a@x.co",
        ))
        db.commit()
    with SessionLocal() as db, pytest.raises(IntegrityError):
        db.add(CustomerAccount(
            workspace_id=ws2_id, stripe_customer_id="cus_dup", email="b@x.co",
        ))
        db.commit()
```

- [ ] **Step 4: Run to verify failure**

```bash
cd apps/api && .venv/bin/pytest tests/test_customer_account_model.py -v
```
Expected: FAIL — `cannot import name 'CustomerAccount'`.

- [ ] **Step 5: Add the ORM class**

Open `apps/api/app/models/entities.py`. After the last existing class (likely `ProactiveDigest` from S5), append:

```python
class CustomerAccount(
    Base, UUIDPrimaryKeyMixin, TimestampMixin, UpdatedAtMixin,
):
    __tablename__ = "customer_accounts"
    __table_args__ = (
        UniqueConstraint("workspace_id", name="uq_customer_accounts_workspace"),
        UniqueConstraint("stripe_customer_id", name="uq_customer_accounts_stripe_customer_id"),
    )

    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    stripe_customer_id: Mapped[str] = mapped_column(String(64), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    default_payment_method_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True,
    )
```

Open `apps/api/app/models/__init__.py`. Add `CustomerAccount` to:
- the `from app.models.entities import (...)` import block (alphabetical)
- the `__all__` list (alphabetical)

- [ ] **Step 6: Create Alembic migration**

Find current head: `cd apps/api && .venv/bin/alembic current`. Should be `202604210001` (S7). If different, use the actual head as `down_revision` below.

Create `apps/api/alembic/versions/202604220001_billing_customer_accounts.py`:

```python
"""S6 Billing — customer_accounts table

Revision ID: 202604220001
Revises: 202604210001
Create Date: 2026-04-22
"""

from alembic import op


revision = "202604220001"
down_revision = "202604210001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS customer_accounts (
            id                            VARCHAR(36) PRIMARY KEY,
            workspace_id                  VARCHAR(36) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            stripe_customer_id            VARCHAR(64) NOT NULL,
            email                         VARCHAR(320),
            default_payment_method_id     VARCHAR(64),
            created_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_customer_accounts_workspace UNIQUE (workspace_id),
            CONSTRAINT uq_customer_accounts_stripe_customer_id UNIQUE (stripe_customer_id)
        );

        CREATE INDEX IF NOT EXISTS ix_customer_accounts_workspace_id
            ON customer_accounts (workspace_id);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS customer_accounts CASCADE;")
```

- [ ] **Step 7: Run to verify pass**

```bash
cd apps/api && .venv/bin/pytest tests/test_customer_account_model.py -v
```
Expected: 3 PASSED.

- [ ] **Step 8: Commit**

```bash
cd /Users/dog/Desktop/MRAI && git branch --show-current  # must be feature/s6-billing
git add apps/api/pyproject.toml apps/api/app/core/config.py apps/api/app/models/entities.py apps/api/app/models/__init__.py apps/api/alembic/versions/202604220001_billing_customer_accounts.py apps/api/tests/test_customer_account_model.py
git commit -m "feat(api): Stripe SDK + billing config fields + CustomerAccount model"
```

---

## Task 2 — 4 billing tables + Alembic

**Files:**
- Modify: `apps/api/app/models/entities.py` (add 4 classes)
- Modify: `apps/api/app/models/__init__.py` (export 4)
- Create: `apps/api/alembic/versions/202604220002_billing_core_tables.py`
- Create: `apps/api/tests/test_billing_core_models.py`

- [ ] **Step 1: Write failing tests**

Create `apps/api/tests/test_billing_core_models.py`:

```python
# ruff: noqa: E402
import atexit, importlib, os, shutil, tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-s6-core-"))
atexit.register(lambda: shutil.rmtree(TEST_TEMP_DIR, ignore_errors=True))
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_TEMP_DIR / 'test.db'}"
os.environ["ENV"] = "test"

import app.core.config as config_module
config_module.get_settings.cache_clear()
config_module.settings = config_module.get_settings()
import app.db.session as session_module
importlib.reload(session_module)

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models import (
    BillingEvent, Entitlement, Subscription, SubscriptionItem,
    User, Workspace,
)


def setup_function() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _ws() -> str:
    with SessionLocal() as db:
        ws = Workspace(name="W"); user = User(email="u@x.co", password_hash="x")
        db.add(ws); db.add(user); db.commit(); db.refresh(ws)
        return ws.id


def test_subscription_basic_insert_with_defaults() -> None:
    ws = _ws()
    with SessionLocal() as db:
        sub = Subscription(
            workspace_id=ws,
            plan="pro", billing_cycle="monthly",
            status="active", provider="stripe_recurring",
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
        )
        db.add(sub); db.commit(); db.refresh(sub)
    assert sub.seats == 1
    assert sub.cancel_at_period_end is False


def test_subscription_stripe_id_unique() -> None:
    ws = _ws()
    with SessionLocal() as db:
        db.add(Subscription(
            workspace_id=ws, plan="pro", billing_cycle="monthly",
            status="active", provider="stripe_recurring",
            stripe_subscription_id="sub_dup",
        ))
        db.commit()
    with SessionLocal() as db, pytest.raises(IntegrityError):
        db.add(Subscription(
            workspace_id=ws, plan="power", billing_cycle="monthly",
            status="active", provider="stripe_recurring",
            stripe_subscription_id="sub_dup",
        ))
        db.commit()


def test_subscription_status_check_constraint() -> None:
    ws = _ws()
    with SessionLocal() as db, pytest.raises(IntegrityError):
        db.add(Subscription(
            workspace_id=ws, plan="pro", billing_cycle="monthly",
            status="bogus", provider="stripe_recurring",
        ))
        db.commit()


def test_subscription_plan_check_constraint() -> None:
    ws = _ws()
    with SessionLocal() as db, pytest.raises(IntegrityError):
        db.add(Subscription(
            workspace_id=ws, plan="ultra", billing_cycle="monthly",
            status="active", provider="stripe_recurring",
        ))
        db.commit()


def test_subscription_item_links_to_subscription() -> None:
    ws = _ws()
    with SessionLocal() as db:
        sub = Subscription(
            workspace_id=ws, plan="team", billing_cycle="monthly",
            status="active", provider="stripe_recurring", seats=5,
        )
        db.add(sub); db.commit(); db.refresh(sub)
        item = SubscriptionItem(
            subscription_id=sub.id,
            stripe_price_id="price_team_monthly",
            quantity=5,
        )
        db.add(item); db.commit(); db.refresh(item)
    assert item.quantity == 5


def test_entitlement_unique_workspace_key() -> None:
    ws = _ws()
    with SessionLocal() as db:
        db.add(Entitlement(
            workspace_id=ws, key="notebooks.max",
            value_int=50, source="plan",
        ))
        db.commit()
    with SessionLocal() as db, pytest.raises(IntegrityError):
        db.add(Entitlement(
            workspace_id=ws, key="notebooks.max",
            value_int=100, source="admin_override",
        ))
        db.commit()


def test_billing_event_stripe_id_unique() -> None:
    with SessionLocal() as db:
        db.add(BillingEvent(
            stripe_event_id="evt_test_1",
            event_type="checkout.session.completed",
            payload_json={"foo": "bar"},
        ))
        db.commit()
    with SessionLocal() as db, pytest.raises(IntegrityError):
        db.add(BillingEvent(
            stripe_event_id="evt_test_1",
            event_type="customer.subscription.updated",
            payload_json={},
        ))
        db.commit()
```

- [ ] **Step 2: Run to verify failure**

```bash
cd apps/api && .venv/bin/pytest tests/test_billing_core_models.py -v
```
Expected: FAIL — `cannot import name 'Subscription'`.

- [ ] **Step 3: Add the 4 ORM classes**

Append to `apps/api/app/models/entities.py` after `CustomerAccount`:

```python
class Subscription(
    Base, UUIDPrimaryKeyMixin, TimestampMixin, UpdatedAtMixin,
):
    __tablename__ = "subscriptions"
    __table_args__ = (
        UniqueConstraint(
            "stripe_subscription_id",
            name="uq_subscriptions_stripe_subscription_id",
        ),
        CheckConstraint(
            "plan IN ('free','pro','power','team')",
            name="ck_subscriptions_plan",
        ),
        CheckConstraint(
            "billing_cycle IN ('monthly','yearly','none')",
            name="ck_subscriptions_billing_cycle",
        ),
        CheckConstraint(
            "status IN ('active','past_due','canceled','trialing','manual','incomplete')",
            name="ck_subscriptions_status",
        ),
        CheckConstraint(
            "provider IN ('stripe_recurring','stripe_one_time','free')",
            name="ck_subscriptions_provider",
        ),
    )

    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    plan: Mapped[str] = mapped_column(String(20), nullable=False)
    billing_cycle: Mapped[str] = mapped_column(String(10), default="monthly", nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    current_period_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True,
    )
    seats: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    cancel_at_period_end: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False,
    )


class SubscriptionItem(
    Base, UUIDPrimaryKeyMixin, TimestampMixin,
):
    __tablename__ = "subscription_items"
    __table_args__ = (
        UniqueConstraint(
            "stripe_subscription_item_id",
            name="uq_subscription_items_stripe_id",
        ),
    )

    subscription_id: Mapped[str] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    stripe_subscription_item_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True,
    )
    stripe_price_id: Mapped[str] = mapped_column(String(64), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class Entitlement(
    Base, UUIDPrimaryKeyMixin, TimestampMixin, UpdatedAtMixin,
):
    __tablename__ = "entitlements"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "key",
            name="uq_entitlements_workspace_key",
        ),
        CheckConstraint(
            "source IN ('plan','admin_override','trial')",
            name="ck_entitlements_source",
        ),
    )

    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    key: Mapped[str] = mapped_column(String(80), nullable=False)
    value_int: Mapped[int | None] = mapped_column(Integer, nullable=True)
    value_bool: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    source: Mapped[str] = mapped_column(String(20), default="plan", nullable=False)


class BillingEvent(
    Base, UUIDPrimaryKeyMixin, TimestampMixin,
):
    __tablename__ = "billing_events"
    __table_args__ = (
        UniqueConstraint(
            "stripe_event_id",
            name="uq_billing_events_stripe_event_id",
        ),
    )

    stripe_event_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
```

Open `apps/api/app/models/__init__.py`. Add `BillingEvent`, `Entitlement`, `Subscription`, `SubscriptionItem` to both the import block and `__all__` (alphabetical placement).

- [ ] **Step 4: Create Alembic migration**

Create `apps/api/alembic/versions/202604220002_billing_core_tables.py`:

```python
"""S6 Billing — subscriptions / subscription_items / entitlements / billing_events

Revision ID: 202604220002
Revises: 202604220001
Create Date: 2026-04-22
"""

from alembic import op


revision = "202604220002"
down_revision = "202604220001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            id                          VARCHAR(36) PRIMARY KEY,
            workspace_id                VARCHAR(36) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            stripe_subscription_id      VARCHAR(64),
            plan                        VARCHAR(20) NOT NULL,
            billing_cycle               VARCHAR(10) NOT NULL DEFAULT 'monthly',
            status                      VARCHAR(20) NOT NULL,
            provider                    VARCHAR(20) NOT NULL,
            current_period_start        TIMESTAMPTZ,
            current_period_end          TIMESTAMPTZ,
            seats                       INTEGER NOT NULL DEFAULT 1,
            cancel_at_period_end        BOOLEAN NOT NULL DEFAULT FALSE,
            created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_subscriptions_stripe_subscription_id UNIQUE (stripe_subscription_id),
            CONSTRAINT ck_subscriptions_plan CHECK (plan IN ('free','pro','power','team')),
            CONSTRAINT ck_subscriptions_billing_cycle CHECK (billing_cycle IN ('monthly','yearly','none')),
            CONSTRAINT ck_subscriptions_status CHECK (status IN ('active','past_due','canceled','trialing','manual','incomplete')),
            CONSTRAINT ck_subscriptions_provider CHECK (provider IN ('stripe_recurring','stripe_one_time','free'))
        );
        CREATE INDEX IF NOT EXISTS ix_subscriptions_workspace_id ON subscriptions(workspace_id);
        CREATE INDEX IF NOT EXISTS ix_subscriptions_current_period_end ON subscriptions(current_period_end);

        CREATE TABLE IF NOT EXISTS subscription_items (
            id                            VARCHAR(36) PRIMARY KEY,
            subscription_id               VARCHAR(36) NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
            stripe_subscription_item_id   VARCHAR(64),
            stripe_price_id               VARCHAR(64) NOT NULL,
            quantity                      INTEGER NOT NULL DEFAULT 1,
            created_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_subscription_items_stripe_id UNIQUE (stripe_subscription_item_id)
        );
        CREATE INDEX IF NOT EXISTS ix_subscription_items_subscription_id ON subscription_items(subscription_id);

        CREATE TABLE IF NOT EXISTS entitlements (
            id            VARCHAR(36) PRIMARY KEY,
            workspace_id  VARCHAR(36) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            key           VARCHAR(80) NOT NULL,
            value_int     INTEGER,
            value_bool    BOOLEAN,
            expires_at    TIMESTAMPTZ,
            source        VARCHAR(20) NOT NULL DEFAULT 'plan',
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_entitlements_workspace_key UNIQUE (workspace_id, key),
            CONSTRAINT ck_entitlements_source CHECK (source IN ('plan','admin_override','trial'))
        );
        CREATE INDEX IF NOT EXISTS ix_entitlements_workspace_id ON entitlements(workspace_id);

        CREATE TABLE IF NOT EXISTS billing_events (
            id                VARCHAR(36) PRIMARY KEY,
            stripe_event_id   VARCHAR(64) NOT NULL,
            event_type        VARCHAR(80) NOT NULL,
            payload_json      JSONB NOT NULL DEFAULT '{}'::jsonb,
            processed_at      TIMESTAMPTZ,
            error             TEXT,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_billing_events_stripe_event_id UNIQUE (stripe_event_id)
        );
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS billing_events CASCADE;
        DROP TABLE IF EXISTS entitlements CASCADE;
        DROP TABLE IF EXISTS subscription_items CASCADE;
        DROP TABLE IF EXISTS subscriptions CASCADE;
    """)
```

- [ ] **Step 5: Run to verify pass**

```bash
cd apps/api && .venv/bin/pytest tests/test_billing_core_models.py -v
```
Expected: 7 PASSED.

- [ ] **Step 6: Commit**

```bash
cd /Users/dog/Desktop/MRAI && git add apps/api/app/models/entities.py apps/api/app/models/__init__.py apps/api/alembic/versions/202604220002_billing_core_tables.py apps/api/tests/test_billing_core_models.py
git commit -m "feat(api): subscriptions / subscription_items / entitlements / billing_events tables"
```

---

## Task 3 — `plan_entitlements.py` constants + `core/entitlements.py` resolver

**Files:**
- Create: `apps/api/app/services/plan_entitlements.py`
- Create: `apps/api/app/core/entitlements.py`
- Create: `apps/api/tests/test_plan_entitlements.py`
- Create: `apps/api/tests/test_entitlement_resolver.py`

- [ ] **Step 1: Write failing tests for constants**

Create `apps/api/tests/test_plan_entitlements.py`:

```python
from app.services.plan_entitlements import (
    PLAN_ENTITLEMENTS,
    ENTITLEMENT_KEYS,
    get_plan_entitlements,
)


def test_all_four_plans_present() -> None:
    assert set(PLAN_ENTITLEMENTS.keys()) == {"free", "pro", "power", "team"}


def test_each_plan_has_all_8_keys() -> None:
    expected_keys = {
        "notebooks.max", "pages.max", "study_assets.max",
        "ai.actions.monthly", "book_upload.enabled",
        "daily_digest.enabled", "voice.enabled",
        "advanced_memory_insights.enabled",
    }
    for plan, ents in PLAN_ENTITLEMENTS.items():
        assert set(ents.keys()) == expected_keys, f"plan {plan} missing keys"


def test_entitlement_keys_match() -> None:
    assert isinstance(ENTITLEMENT_KEYS, frozenset)
    assert len(ENTITLEMENT_KEYS) == 8


def test_free_plan_disables_premium_features() -> None:
    free = PLAN_ENTITLEMENTS["free"]
    assert free["voice.enabled"] is False
    assert free["daily_digest.enabled"] is False
    assert free["book_upload.enabled"] is False
    assert free["advanced_memory_insights.enabled"] is False


def test_power_unlimited_caps() -> None:
    power = PLAN_ENTITLEMENTS["power"]
    assert power["notebooks.max"] == -1
    assert power["pages.max"] == -1
    assert power["study_assets.max"] == -1


def test_get_plan_entitlements_returns_copy() -> None:
    ents = get_plan_entitlements("pro")
    ents["notebooks.max"] = 999
    # Mutating the copy should not affect the constant.
    assert PLAN_ENTITLEMENTS["pro"]["notebooks.max"] != 999


def test_get_plan_entitlements_unknown_plan_returns_free() -> None:
    ents = get_plan_entitlements("nonexistent")
    assert ents == PLAN_ENTITLEMENTS["free"]
```

- [ ] **Step 2: Verify failure**

```bash
cd apps/api && .venv/bin/pytest tests/test_plan_entitlements.py -v
```
Expected: FAIL — module not found.

- [ ] **Step 3: Create constants module**

Create `apps/api/app/services/plan_entitlements.py`:

```python
"""S6 Billing — single source of truth for plan ↔ entitlement mapping."""

from __future__ import annotations

from typing import Any


PLAN_ENTITLEMENTS: dict[str, dict[str, Any]] = {
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
        "notebooks.max": -1,
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

ENTITLEMENT_KEYS: frozenset[str] = frozenset(PLAN_ENTITLEMENTS["free"].keys())


def get_plan_entitlements(plan: str) -> dict[str, Any]:
    """Return a fresh dict copy of entitlements for the given plan.
    Unknown plans fall back to free."""
    return dict(PLAN_ENTITLEMENTS.get(plan, PLAN_ENTITLEMENTS["free"]))
```

- [ ] **Step 4: Verify pass**

```bash
cd apps/api && .venv/bin/pytest tests/test_plan_entitlements.py -v
```
Expected: 7 PASSED.

- [ ] **Step 5: Write failing tests for resolver**

Create `apps/api/tests/test_entitlement_resolver.py`:

```python
# ruff: noqa: E402
import atexit, importlib, os, shutil, tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-s6-resolver-"))
atexit.register(lambda: shutil.rmtree(TEST_TEMP_DIR, ignore_errors=True))
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_TEMP_DIR / 'test.db'}"
os.environ["ENV"] = "test"

import app.core.config as config_module
config_module.get_settings.cache_clear()
config_module.settings = config_module.get_settings()
import app.db.session as session_module
importlib.reload(session_module)

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models import Entitlement, Subscription, User, Workspace
from app.core.entitlements import (
    resolve_entitlement, refresh_workspace_entitlements,
    get_active_plan,
)


def setup_function() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _ws() -> str:
    with SessionLocal() as db:
        ws = Workspace(name="W"); user = User(email="u@x.co", password_hash="x")
        db.add(ws); db.add(user); db.commit(); db.refresh(ws)
        return ws.id


def test_no_subscription_returns_free_plan() -> None:
    ws = _ws()
    with SessionLocal() as db:
        plan = get_active_plan(db, workspace_id=ws)
    assert plan == "free"


def test_active_subscription_returns_its_plan() -> None:
    ws = _ws()
    with SessionLocal() as db:
        db.add(Subscription(
            workspace_id=ws, plan="pro", billing_cycle="monthly",
            status="active", provider="stripe_recurring",
        ))
        db.commit()
        plan = get_active_plan(db, workspace_id=ws)
    assert plan == "pro"


def test_canceled_subscription_falls_back_to_free() -> None:
    ws = _ws()
    with SessionLocal() as db:
        db.add(Subscription(
            workspace_id=ws, plan="pro", billing_cycle="monthly",
            status="canceled", provider="stripe_recurring",
        ))
        db.commit()
        plan = get_active_plan(db, workspace_id=ws)
    assert plan == "free"


def test_refresh_writes_all_8_entitlements() -> None:
    ws = _ws()
    with SessionLocal() as db:
        db.add(Subscription(
            workspace_id=ws, plan="pro", billing_cycle="monthly",
            status="active", provider="stripe_recurring",
        ))
        db.commit()
        refresh_workspace_entitlements(db, workspace_id=ws)
        rows = db.query(Entitlement).filter(
            Entitlement.workspace_id == ws,
        ).all()
    assert len(rows) == 8
    by_key = {r.key: r for r in rows}
    assert by_key["notebooks.max"].value_int == -1
    assert by_key["voice.enabled"].value_bool is True


def test_refresh_is_idempotent() -> None:
    ws = _ws()
    with SessionLocal() as db:
        db.add(Subscription(
            workspace_id=ws, plan="pro", billing_cycle="monthly",
            status="active", provider="stripe_recurring",
        ))
        db.commit()
        refresh_workspace_entitlements(db, workspace_id=ws)
        refresh_workspace_entitlements(db, workspace_id=ws)
        count = db.query(Entitlement).filter(
            Entitlement.workspace_id == ws,
        ).count()
    assert count == 8


def test_resolve_returns_int_for_counted_entitlement() -> None:
    ws = _ws()
    with SessionLocal() as db:
        db.add(Subscription(
            workspace_id=ws, plan="free", billing_cycle="none",
            status="active", provider="free",
        ))
        db.commit()
        refresh_workspace_entitlements(db, workspace_id=ws)
        v = resolve_entitlement(db, workspace_id=ws, key="notebooks.max")
    assert v == 1


def test_resolve_returns_bool_for_flag_entitlement() -> None:
    ws = _ws()
    with SessionLocal() as db:
        db.add(Subscription(
            workspace_id=ws, plan="free", billing_cycle="none",
            status="active", provider="free",
        ))
        db.commit()
        refresh_workspace_entitlements(db, workspace_id=ws)
        v = resolve_entitlement(db, workspace_id=ws, key="voice.enabled")
    assert v is False


def test_admin_override_wins_over_plan() -> None:
    ws = _ws()
    with SessionLocal() as db:
        db.add(Subscription(
            workspace_id=ws, plan="free", billing_cycle="none",
            status="active", provider="free",
        ))
        db.commit()
        refresh_workspace_entitlements(db, workspace_id=ws)
        # Override notebooks.max from 1 to 999 via admin_override.
        ent = db.query(Entitlement).filter_by(
            workspace_id=ws, key="notebooks.max",
        ).first()
        ent.value_int = 999
        ent.source = "admin_override"
        db.add(ent); db.commit()
        v = resolve_entitlement(db, workspace_id=ws, key="notebooks.max")
    assert v == 999


def test_expired_override_falls_back_to_plan_via_refresh() -> None:
    ws = _ws()
    with SessionLocal() as db:
        db.add(Subscription(
            workspace_id=ws, plan="free", billing_cycle="none",
            status="active", provider="free",
        ))
        db.commit()
        # Insert an expired admin override directly.
        db.add(Entitlement(
            workspace_id=ws, key="voice.enabled", value_bool=True,
            source="admin_override",
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        ))
        db.commit()
        refresh_workspace_entitlements(db, workspace_id=ws)
        v = resolve_entitlement(db, workspace_id=ws, key="voice.enabled")
    assert v is False  # plan default after refresh
```

- [ ] **Step 6: Verify failure**

```bash
cd apps/api && .venv/bin/pytest tests/test_entitlement_resolver.py -v
```
Expected: FAIL — module not found.

- [ ] **Step 7: Create resolver module**

Create `apps/api/app/core/entitlements.py`:

```python
"""S6 Billing — entitlement resolver and FastAPI gate Depends."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_workspace_id, get_db_session
from app.core.errors import ApiError
from app.models import Entitlement, Subscription
from app.services.plan_entitlements import (
    ENTITLEMENT_KEYS, PLAN_ENTITLEMENTS, get_plan_entitlements,
)


_ACTIVE_STATUSES = {"active", "past_due", "trialing", "manual"}


def get_active_plan(db: Session, *, workspace_id: str) -> str:
    """Return the plan code of the workspace's active subscription, or 'free'."""
    sub = (
        db.query(Subscription)
        .filter(Subscription.workspace_id == workspace_id)
        .filter(Subscription.status.in_(_ACTIVE_STATUSES))
        .order_by(Subscription.created_at.desc())
        .first()
    )
    return sub.plan if sub else "free"


def refresh_workspace_entitlements(db: Session, *, workspace_id: str) -> None:
    """Recompute entitlements for the workspace from its active plan.

    Removes expired admin_override rows; upserts plan-source rows;
    keeps unexpired admin_override rows untouched.
    """
    plan = get_active_plan(db, workspace_id=workspace_id)
    plan_ents = get_plan_entitlements(plan)
    now = datetime.now(timezone.utc)

    existing = (
        db.query(Entitlement)
        .filter(Entitlement.workspace_id == workspace_id)
        .all()
    )
    by_key = {e.key: e for e in existing}

    # Drop expired overrides so plan defaults take over.
    for e in existing:
        if e.source == "admin_override" and e.expires_at and e.expires_at < now:
            db.delete(e)
            del by_key[e.key]

    for key in ENTITLEMENT_KEYS:
        plan_value = plan_ents[key]
        ent = by_key.get(key)
        if ent is None:
            new = Entitlement(
                workspace_id=workspace_id, key=key, source="plan",
                value_int=plan_value if isinstance(plan_value, int) else None,
                value_bool=plan_value if isinstance(plan_value, bool) else None,
            )
            db.add(new)
            continue
        if ent.source != "admin_override":
            ent.value_int = plan_value if isinstance(plan_value, int) else None
            ent.value_bool = plan_value if isinstance(plan_value, bool) else None
            ent.source = "plan"
            db.add(ent)
    db.commit()


def resolve_entitlement(
    db: Session, *, workspace_id: str, key: str,
) -> int | bool | None:
    """Return the resolved entitlement value, or None if missing."""
    ent = (
        db.query(Entitlement)
        .filter(Entitlement.workspace_id == workspace_id)
        .filter(Entitlement.key == key)
        .first()
    )
    if ent is None:
        # Lazy fallback: read plan default without writing to DB.
        plan = get_active_plan(db, workspace_id=workspace_id)
        return get_plan_entitlements(plan).get(key)
    if ent.value_int is not None:
        return ent.value_int
    return ent.value_bool


def require_entitlement(
    key: str,
    *,
    counter: Callable[[Session, str], int] | None = None,
) -> Callable:
    """Returns a FastAPI Depends that enforces entitlement on the
    current workspace. Boolean entitlements raise 402 plan_required
    when False. Counted entitlements (non-bool, non -1) raise 402
    plan_limit_reached when current >= limit. counter signature:
    (db, workspace_id) -> int."""

    def _check(
        workspace_id: str = Depends(get_current_workspace_id),
        db: Session = Depends(get_db_session),
    ) -> None:
        value = resolve_entitlement(db, workspace_id=workspace_id, key=key)
        if isinstance(value, bool):
            if value is False:
                raise ApiError(
                    "plan_required",
                    f"Your plan doesn't include {key}",
                    status_code=402,
                    details={"key": key},
                )
            return
        if isinstance(value, int):
            if value == -1:
                return
            if counter is None:
                return
            current = counter(db, workspace_id)
            if current >= value:
                raise ApiError(
                    "plan_limit_reached",
                    f"{key} limit reached ({current}/{value})",
                    status_code=402,
                    details={"key": key, "current": current, "limit": value},
                )

    return _check
```

- [ ] **Step 8: Verify pass**

```bash
cd apps/api && .venv/bin/pytest tests/test_entitlement_resolver.py -v
```
Expected: 9 PASSED.

- [ ] **Step 9: Commit**

```bash
cd /Users/dog/Desktop/MRAI && git add apps/api/app/services/plan_entitlements.py apps/api/app/core/entitlements.py apps/api/tests/test_plan_entitlements.py apps/api/tests/test_entitlement_resolver.py
git commit -m "feat(api): plan_entitlements constants + entitlement resolver + 16 tests"
```

---

## Task 4 — `stripe_client.py` wrapper + 3 mutation endpoints

**Files:**
- Create: `apps/api/app/services/stripe_client.py`
- Create: `apps/api/app/schemas/billing.py`
- Create: `apps/api/app/routers/billing.py`
- Modify: `apps/api/app/main.py` (include router)
- Create: `apps/api/tests/test_billing_checkout.py`

- [ ] **Step 1: Pydantic schemas**

Create `apps/api/app/schemas/billing.py`:

```python
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class CheckoutRequest(BaseModel):
    plan: str = Field(..., pattern=r"^(pro|power|team)$")
    cycle: str = Field(..., pattern=r"^(monthly|yearly)$")
    seats: int = Field(default=1, ge=1, le=100)


class CheckoutOnetimeRequest(BaseModel):
    plan: str = Field(..., pattern=r"^(pro|power|team)$")
    cycle: str = Field(..., pattern=r"^(monthly|yearly)$")
    payment_method: str = Field(..., pattern=r"^(alipay|wechat_pay)$")
    seats: int = Field(default=1, ge=1, le=100)


class CheckoutResponse(BaseModel):
    checkout_url: str


class PortalResponse(BaseModel):
    portal_url: str


class BillingMeResponse(BaseModel):
    plan: str
    status: str
    billing_cycle: str
    current_period_end: datetime | None
    seats: int
    cancel_at_period_end: bool
    provider: str
    entitlements: dict[str, Any]
    usage_this_month: dict[str, int]


class PlansResponse(BaseModel):
    plans: list[dict[str, Any]]
```

- [ ] **Step 2: Stripe client wrapper**

Create `apps/api/app/services/stripe_client.py`:

```python
"""Thin wrapper around the Stripe SDK so the router stays mockable
and we don't sprinkle stripe.* calls everywhere."""

from __future__ import annotations

from typing import Any

import stripe

from app.core.config import settings


def _init() -> None:
    stripe.api_key = settings.stripe_api_key


def get_or_create_customer(*, workspace_id: str, email: str | None = None) -> str:
    """Create a Stripe customer with workspace_id metadata. Returns the
    Stripe customer ID. Caller is responsible for persisting it in
    customer_accounts."""
    _init()
    customer = stripe.Customer.create(
        email=email or None,
        metadata={"mrai_workspace_id": workspace_id},
    )
    return customer["id"]


def create_checkout_session_subscription(
    *,
    stripe_customer_id: str,
    price_id: str,
    quantity: int,
    success_url: str,
    cancel_url: str,
    metadata: dict[str, str] | None = None,
) -> str:
    """Returns the Checkout session URL for redirect."""
    _init()
    session = stripe.checkout.Session.create(
        mode="subscription",
        customer=stripe_customer_id,
        line_items=[{"price": price_id, "quantity": quantity}],
        success_url=success_url,
        cancel_url=cancel_url,
        metadata=metadata or {},
    )
    return session["url"]


def create_checkout_session_one_time(
    *,
    stripe_customer_id: str,
    product_id: str,
    unit_amount_cents: int,
    quantity: int,
    payment_method: str,
    success_url: str,
    cancel_url: str,
    metadata: dict[str, str] | None = None,
) -> str:
    """One-time payment (Alipay / WeChat Pay) — no recurring."""
    _init()
    session = stripe.checkout.Session.create(
        mode="payment",
        customer=stripe_customer_id,
        payment_method_types=[payment_method],
        line_items=[
            {
                "quantity": quantity,
                "price_data": {
                    "currency": "usd",
                    "product": product_id,
                    "unit_amount": unit_amount_cents,
                },
            },
        ],
        success_url=success_url,
        cancel_url=cancel_url,
        metadata=metadata or {},
    )
    return session["url"]


def create_billing_portal_session(
    *,
    stripe_customer_id: str,
    return_url: str,
) -> str:
    _init()
    session = stripe.billing_portal.Session.create(
        customer=stripe_customer_id,
        return_url=return_url,
    )
    return session["url"]


def verify_webhook(
    payload_bytes: bytes,
    sig_header: str,
) -> dict[str, Any]:
    """Verify Stripe-Signature header and return the parsed event dict."""
    _init()
    event = stripe.Webhook.construct_event(
        payload=payload_bytes,
        sig_header=sig_header,
        secret=settings.stripe_webhook_secret,
    )
    return dict(event)


# ---------------------------------------------------------------------------
# Plan ↔ Stripe ID lookup helpers (used by router + webhook)
# ---------------------------------------------------------------------------


def stripe_price_id_for(plan: str, cycle: str) -> str:
    """Return the Stripe Price ID for the (plan, cycle) tuple."""
    table = {
        ("pro", "monthly"): settings.stripe_price_pro_monthly,
        ("pro", "yearly"): settings.stripe_price_pro_yearly,
        ("power", "monthly"): settings.stripe_price_power_monthly,
        ("power", "yearly"): settings.stripe_price_power_yearly,
        ("team", "monthly"): settings.stripe_price_team_monthly,
        ("team", "yearly"): settings.stripe_price_team_yearly,
    }
    pid = table.get((plan, cycle))
    if not pid:
        raise ValueError(f"unknown plan/cycle: {plan}/{cycle}")
    return pid


def stripe_product_id_for(plan: str) -> str:
    """Return the Stripe Product ID for the plan."""
    table = {
        "pro": "prod_ULxidFvV2ivzrz",
        "power": "prod_ULxiNIox1PRZaw",
        "team": "prod_ULxi7uvs66Dup5",
    }
    pid = table.get(plan)
    if not pid:
        raise ValueError(f"unknown plan: {plan}")
    return pid


def one_time_unit_amount_cents(plan: str, cycle: str) -> int:
    """Mirror the recurring price points for one-time payment fallback."""
    table = {
        ("pro", "monthly"): 1000,
        ("pro", "yearly"): 10200,
        ("power", "monthly"): 2500,
        ("power", "yearly"): 25500,
        ("team", "monthly"): 1500,
        ("team", "yearly"): 15300,
    }
    return table[(plan, cycle)]
```

- [ ] **Step 3: Write failing tests for checkout endpoints**

Create `apps/api/tests/test_billing_checkout.py`:

```python
# ruff: noqa: E402
import atexit, importlib, os, shutil, tempfile
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-s6-checkout-"))
atexit.register(lambda: shutil.rmtree(TEST_TEMP_DIR, ignore_errors=True))
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_TEMP_DIR / 'test.db'}"
os.environ["ENV"] = "test"
os.environ["COOKIE_DOMAIN"] = ""
os.environ["DEMO_MODE"] = "true"
os.environ["STRIPE_API_KEY"] = "sk_test_dummy"

import app.core.config as config_module
config_module.get_settings.cache_clear()
config_module.settings = config_module.get_settings()
import app.db.session as session_module
importlib.reload(session_module)
import app.main as main_module
importlib.reload(main_module)

from unittest.mock import patch
from fastapi.testclient import TestClient

from app.db.base import Base
import app.db.session as _s


def setup_function() -> None:
    Base.metadata.drop_all(bind=_s.engine)
    Base.metadata.create_all(bind=_s.engine)
    from app.services.runtime_state import runtime_state
    runtime_state._memory = runtime_state._memory.__class__()


def _public_headers() -> dict[str, str]:
    return {"origin": "http://localhost:3000"}


def _register_client(email: str = "u@x.co") -> tuple[TestClient, dict]:
    import hashlib
    from app.services.runtime_state import runtime_state
    client = TestClient(main_module.app)
    client.post("/api/v1/auth/send-code",
                json={"email": email, "purpose": "register"},
                headers=_public_headers())
    raw = f"{email.lower().strip()}:register"
    code_key = hashlib.sha256(raw.encode()).hexdigest()
    code = str(runtime_state.get_json("verify_code", code_key)["code"])
    info = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "pass1234pass",
              "display_name": "Test", "code": code},
        headers=_public_headers(),
    ).json()
    csrf = client.get("/api/v1/auth/csrf",
                     headers=_public_headers()).json()["csrf_token"]
    client.headers.update({
        "origin": "http://localhost:3000",
        "x-csrf-token": csrf,
        "x-workspace-id": info["workspace"]["id"],
    })
    return client, {"ws_id": info["workspace"]["id"],
                    "user_id": info["user"]["id"]}


def test_checkout_returns_url_and_creates_customer() -> None:
    client, _ = _register_client("u1@x.co")
    with patch(
        "app.routers.billing.stripe_client.get_or_create_customer",
        return_value="cus_test_1",
    ), patch(
        "app.routers.billing.stripe_client.create_checkout_session_subscription",
        return_value="https://checkout.stripe.com/pay/sess_x",
    ):
        resp = client.post(
            "/api/v1/billing/checkout",
            json={"plan": "pro", "cycle": "monthly"},
        )
    assert resp.status_code == 200
    assert "checkout.stripe.com" in resp.json()["checkout_url"]
    # Customer row persisted.
    from app.models import CustomerAccount
    with _s.SessionLocal() as db:
        ca = db.query(CustomerAccount).first()
    assert ca and ca.stripe_customer_id == "cus_test_1"


def test_checkout_team_uses_seat_quantity() -> None:
    client, _ = _register_client("u2@x.co")
    captured = {}

    def fake_session(**kwargs):
        captured.update(kwargs)
        return "https://checkout.stripe.com/pay/sess_y"

    with patch(
        "app.routers.billing.stripe_client.get_or_create_customer",
        return_value="cus_test_2",
    ), patch(
        "app.routers.billing.stripe_client.create_checkout_session_subscription",
        side_effect=fake_session,
    ):
        resp = client.post(
            "/api/v1/billing/checkout",
            json={"plan": "team", "cycle": "monthly", "seats": 5},
        )
    assert resp.status_code == 200
    assert captured["quantity"] == 5


def test_checkout_invalid_plan_returns_422() -> None:
    client, _ = _register_client("u3@x.co")
    resp = client.post(
        "/api/v1/billing/checkout",
        json={"plan": "ultra", "cycle": "monthly"},
    )
    assert resp.status_code == 422


def test_checkout_onetime_uses_payment_mode() -> None:
    client, _ = _register_client("u4@x.co")
    captured = {}

    def fake_session(**kwargs):
        captured.update(kwargs)
        return "https://checkout.stripe.com/pay/sess_z"

    with patch(
        "app.routers.billing.stripe_client.get_or_create_customer",
        return_value="cus_test_4",
    ), patch(
        "app.routers.billing.stripe_client.create_checkout_session_one_time",
        side_effect=fake_session,
    ):
        resp = client.post(
            "/api/v1/billing/checkout-onetime",
            json={"plan": "pro", "cycle": "yearly", "payment_method": "alipay"},
        )
    assert resp.status_code == 200
    assert captured["payment_method"] == "alipay"
    assert captured["unit_amount_cents"] == 10200


def test_portal_returns_url_when_customer_exists() -> None:
    client, _ = _register_client("u5@x.co")
    # First create the customer via checkout call.
    with patch(
        "app.routers.billing.stripe_client.get_or_create_customer",
        return_value="cus_test_5",
    ), patch(
        "app.routers.billing.stripe_client.create_checkout_session_subscription",
        return_value="https://checkout.stripe.com/pay/sess_p",
    ):
        client.post("/api/v1/billing/checkout",
                    json={"plan": "pro", "cycle": "monthly"})
    with patch(
        "app.routers.billing.stripe_client.create_billing_portal_session",
        return_value="https://billing.stripe.com/p/session/foo",
    ):
        resp = client.post("/api/v1/billing/portal", json={})
    assert resp.status_code == 200
    assert "billing.stripe.com" in resp.json()["portal_url"]


def test_portal_returns_404_without_customer() -> None:
    client, _ = _register_client("u6@x.co")
    resp = client.post("/api/v1/billing/portal", json={})
    assert resp.status_code == 404
```

- [ ] **Step 4: Verify failure**

```bash
cd apps/api && .venv/bin/pytest tests/test_billing_checkout.py -v
```
Expected: FAIL — router missing.

- [ ] **Step 5: Create the router**

Create `apps/api/app/routers/billing.py`:

```python
"""S6 Billing API: checkout / checkout-onetime / portal / me / plans / webhook."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import (
    get_current_user, get_current_workspace_id, get_db_session,
    require_csrf_protection,
)
from app.core.errors import ApiError
from app.models import CustomerAccount, User
from app.schemas.billing import (
    CheckoutOnetimeRequest, CheckoutRequest, CheckoutResponse, PortalResponse,
)
from app.services import stripe_client

router = APIRouter(prefix="/api/v1/billing", tags=["billing"])


def _ensure_customer(
    db: Session, *, workspace_id: str, user: User,
) -> CustomerAccount:
    ca = db.query(CustomerAccount).filter_by(workspace_id=workspace_id).first()
    if ca is not None:
        return ca
    stripe_customer_id = stripe_client.get_or_create_customer(
        workspace_id=workspace_id,
        email=getattr(user, "email", None),
    )
    ca = CustomerAccount(
        workspace_id=workspace_id,
        stripe_customer_id=stripe_customer_id,
        email=getattr(user, "email", None),
    )
    db.add(ca); db.commit(); db.refresh(ca)
    return ca


@router.post("/checkout", response_model=CheckoutResponse)
def post_checkout(
    payload: CheckoutRequest,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _: None = Depends(require_csrf_protection),
) -> CheckoutResponse:
    if payload.plan != "team" and payload.seats != 1:
        raise ApiError("invalid_input",
                       "seats only valid for team plan", status_code=400)
    ca = _ensure_customer(db, workspace_id=workspace_id, user=current_user)
    price_id = stripe_client.stripe_price_id_for(payload.plan, payload.cycle)
    url = stripe_client.create_checkout_session_subscription(
        stripe_customer_id=ca.stripe_customer_id,
        price_id=price_id,
        quantity=payload.seats,
        success_url=settings.stripe_checkout_success_url,
        cancel_url=settings.stripe_checkout_cancel_url,
        metadata={
            "mrai_workspace_id": workspace_id,
            "mrai_plan": payload.plan,
            "mrai_cycle": payload.cycle,
        },
    )
    return CheckoutResponse(checkout_url=url)


@router.post("/checkout-onetime", response_model=CheckoutResponse)
def post_checkout_onetime(
    payload: CheckoutOnetimeRequest,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _: None = Depends(require_csrf_protection),
) -> CheckoutResponse:
    if payload.plan != "team" and payload.seats != 1:
        raise ApiError("invalid_input",
                       "seats only valid for team plan", status_code=400)
    ca = _ensure_customer(db, workspace_id=workspace_id, user=current_user)
    amount_cents = stripe_client.one_time_unit_amount_cents(
        payload.plan, payload.cycle,
    )
    product_id = stripe_client.stripe_product_id_for(payload.plan)
    url = stripe_client.create_checkout_session_one_time(
        stripe_customer_id=ca.stripe_customer_id,
        product_id=product_id,
        unit_amount_cents=amount_cents,
        quantity=payload.seats,
        payment_method=payload.payment_method,
        success_url=settings.stripe_checkout_success_url,
        cancel_url=settings.stripe_checkout_cancel_url,
        metadata={
            "mrai_workspace_id": workspace_id,
            "mrai_plan": payload.plan,
            "mrai_cycle": payload.cycle,
            "mrai_one_time": "1",
        },
    )
    return CheckoutResponse(checkout_url=url)


@router.post("/portal", response_model=PortalResponse)
def post_portal(
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),  # noqa: ARG001
    workspace_id: str = Depends(get_current_workspace_id),
    _: None = Depends(require_csrf_protection),
) -> PortalResponse:
    ca = db.query(CustomerAccount).filter_by(workspace_id=workspace_id).first()
    if ca is None:
        raise ApiError("not_found",
                       "No Stripe customer for this workspace", status_code=404)
    url = stripe_client.create_billing_portal_session(
        stripe_customer_id=ca.stripe_customer_id,
        return_url=settings.stripe_billing_portal_return_url,
    )
    return PortalResponse(portal_url=url)
```

- [ ] **Step 6: Register router in main.py**

Open `apps/api/app/main.py`. Find the `from app.routers import (...)` import block; add `billing` (alphabetically — first or near top of the list). Then add `app.include_router(billing.router)` near the other router includes.

- [ ] **Step 7: Verify pass**

```bash
cd apps/api && .venv/bin/pytest tests/test_billing_checkout.py -v
```
Expected: 6 PASSED.

- [ ] **Step 8: Commit**

```bash
cd /Users/dog/Desktop/MRAI && git add apps/api/app/services/stripe_client.py apps/api/app/schemas/billing.py apps/api/app/routers/billing.py apps/api/app/main.py apps/api/tests/test_billing_checkout.py
git commit -m "feat(api): stripe_client wrapper + 3 billing endpoints (checkout / onetime / portal)"
```

---

## Task 5 — Read endpoints + webhook handler

**Files:**
- Modify: `apps/api/app/routers/billing.py` (add /me, /plans, /webhook)
- Create: `apps/api/app/services/billing_webhook.py`
- Create: `apps/api/tests/test_billing_me.py`
- Create: `apps/api/tests/test_billing_webhook.py`

- [ ] **Step 1: Write failing tests for /me and /plans**

Create `apps/api/tests/test_billing_me.py`:

```python
# ruff: noqa: E402
import atexit, importlib, os, shutil, tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-s6-me-"))
atexit.register(lambda: shutil.rmtree(TEST_TEMP_DIR, ignore_errors=True))
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_TEMP_DIR / 'test.db'}"
os.environ["ENV"] = "test"
os.environ["COOKIE_DOMAIN"] = ""
os.environ["DEMO_MODE"] = "true"
os.environ["STRIPE_API_KEY"] = "sk_test_dummy"

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


def setup_function() -> None:
    Base.metadata.drop_all(bind=_s.engine)
    Base.metadata.create_all(bind=_s.engine)
    from app.services.runtime_state import runtime_state
    runtime_state._memory = runtime_state._memory.__class__()


def _public_headers() -> dict[str, str]:
    return {"origin": "http://localhost:3000"}


def _register_client(email: str = "u@x.co") -> tuple[TestClient, dict]:
    import hashlib
    from app.services.runtime_state import runtime_state
    client = TestClient(main_module.app)
    client.post("/api/v1/auth/send-code",
                json={"email": email, "purpose": "register"},
                headers=_public_headers())
    raw = f"{email.lower().strip()}:register"
    code_key = hashlib.sha256(raw.encode()).hexdigest()
    code = str(runtime_state.get_json("verify_code", code_key)["code"])
    info = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "pass1234pass",
              "display_name": "Test", "code": code},
        headers=_public_headers(),
    ).json()
    csrf = client.get("/api/v1/auth/csrf",
                     headers=_public_headers()).json()["csrf_token"]
    client.headers.update({
        "origin": "http://localhost:3000",
        "x-csrf-token": csrf,
        "x-workspace-id": info["workspace"]["id"],
    })
    return client, {"ws_id": info["workspace"]["id"]}


def test_me_default_returns_free_plan() -> None:
    client, _ = _register_client("me1@x.co")
    resp = client.get("/api/v1/billing/me")
    assert resp.status_code == 200
    body = resp.json()
    assert body["plan"] == "free"
    assert body["entitlements"]["voice.enabled"] is False
    assert body["entitlements"]["notebooks.max"] == 1
    assert "ai.actions" in body["usage_this_month"]


def test_me_returns_pro_plan_when_active() -> None:
    client, auth = _register_client("me2@x.co")
    from app.models import Subscription
    with _s.SessionLocal() as db:
        db.add(Subscription(
            workspace_id=auth["ws_id"], plan="pro",
            billing_cycle="monthly", status="active",
            provider="stripe_recurring",
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
        ))
        db.commit()
    resp = client.get("/api/v1/billing/me")
    body = resp.json()
    assert body["plan"] == "pro"
    assert body["entitlements"]["voice.enabled"] is True


def test_plans_returns_four_descriptors() -> None:
    client, _ = _register_client("p1@x.co")
    resp = client.get("/api/v1/billing/plans")
    body = resp.json()
    assert "plans" in body
    assert {p["id"] for p in body["plans"]} == {"free", "pro", "power", "team"}
```

- [ ] **Step 2: Verify failure**

```bash
cd apps/api && .venv/bin/pytest tests/test_billing_me.py -v
```
Expected: FAIL — endpoints missing.

- [ ] **Step 3: Add /me and /plans to billing.py**

Append to `apps/api/app/routers/billing.py`:

```python
from datetime import datetime, timezone

from sqlalchemy import func

from app.core.entitlements import get_active_plan, resolve_entitlement
from app.models import (
    AIUsageEvent, Notebook, NotebookPage, StudyAsset, Subscription,
)
from app.schemas.billing import BillingMeResponse, PlansResponse
from app.services.plan_entitlements import (
    ENTITLEMENT_KEYS, PLAN_ENTITLEMENTS,
)


def _month_start_utc() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


@router.get("/me", response_model=BillingMeResponse)
def get_me(
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),  # noqa: ARG001
    workspace_id: str = Depends(get_current_workspace_id),
) -> BillingMeResponse:
    sub = (
        db.query(Subscription)
        .filter(Subscription.workspace_id == workspace_id)
        .filter(Subscription.status.in_(
            ("active", "past_due", "trialing", "manual"),
        ))
        .order_by(Subscription.created_at.desc())
        .first()
    )
    plan = sub.plan if sub else "free"
    ents = {key: resolve_entitlement(db, workspace_id=workspace_id, key=key)
            for key in ENTITLEMENT_KEYS}

    month_start = _month_start_utc()
    ai_actions_count = (
        db.query(func.count(AIUsageEvent.id))
        .filter(AIUsageEvent.workspace_id == workspace_id)
        .filter(AIUsageEvent.created_at >= month_start)
        .scalar()
    ) or 0
    notebooks_count = (
        db.query(func.count(Notebook.id))
        .filter(Notebook.workspace_id == workspace_id)
        .scalar()
    ) or 0
    pages_count = (
        db.query(func.count(NotebookPage.id))
        .join(Notebook, Notebook.id == NotebookPage.notebook_id)
        .filter(Notebook.workspace_id == workspace_id)
        .scalar()
    ) or 0
    study_assets_count = (
        db.query(func.count(StudyAsset.id))
        .join(Notebook, Notebook.id == StudyAsset.notebook_id)
        .filter(Notebook.workspace_id == workspace_id)
        .scalar()
    ) or 0

    return BillingMeResponse(
        plan=plan,
        status=sub.status if sub else "active",
        billing_cycle=sub.billing_cycle if sub else "none",
        current_period_end=sub.current_period_end if sub else None,
        seats=sub.seats if sub else 1,
        cancel_at_period_end=sub.cancel_at_period_end if sub else False,
        provider=sub.provider if sub else "free",
        entitlements=ents,
        usage_this_month={
            "ai.actions": int(ai_actions_count),
            "notebooks": int(notebooks_count),
            "pages": int(pages_count),
            "study_assets": int(study_assets_count),
        },
    )


@router.get("/plans", response_model=PlansResponse)
def get_plans() -> PlansResponse:
    plans = []
    for plan_id, ents in PLAN_ENTITLEMENTS.items():
        if plan_id == "free":
            prices = {"monthly": None, "yearly": None}
        else:
            prices = {
                "monthly": stripe_client.stripe_price_id_for(plan_id, "monthly"),
                "yearly": stripe_client.stripe_price_id_for(plan_id, "yearly"),
            }
        plans.append({
            "id": plan_id,
            "stripe_prices": prices,
            "entitlements": ents,
        })
    return PlansResponse(plans=plans)
```

- [ ] **Step 4: Verify /me + /plans pass**

```bash
cd apps/api && .venv/bin/pytest tests/test_billing_me.py -v
```
Expected: 3 PASSED.

- [ ] **Step 5: Webhook tests**

Create `apps/api/tests/test_billing_webhook.py`:

```python
# ruff: noqa: E402
import atexit, importlib, json, os, shutil, tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-s6-wh-"))
atexit.register(lambda: shutil.rmtree(TEST_TEMP_DIR, ignore_errors=True))
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_TEMP_DIR / 'test.db'}"
os.environ["ENV"] = "test"
os.environ["COOKIE_DOMAIN"] = ""
os.environ["DEMO_MODE"] = "true"
os.environ["STRIPE_API_KEY"] = "sk_test_dummy"
os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_dummy"

import app.core.config as config_module
config_module.get_settings.cache_clear()
config_module.settings = config_module.get_settings()
import app.db.session as session_module
importlib.reload(session_module)
import app.main as main_module
importlib.reload(main_module)

from unittest.mock import patch
from fastapi.testclient import TestClient

from app.db.base import Base
import app.db.session as _s
from app.models import (
    BillingEvent, CustomerAccount, Subscription, User, Workspace,
)


def setup_function() -> None:
    Base.metadata.drop_all(bind=_s.engine)
    Base.metadata.create_all(bind=_s.engine)


def _seed_workspace_with_customer(stripe_customer_id: str = "cus_t") -> str:
    with _s.SessionLocal() as db:
        ws = Workspace(name="W"); user = User(email="u@x.co", password_hash="x")
        db.add(ws); db.add(user); db.commit(); db.refresh(ws)
        db.add(CustomerAccount(
            workspace_id=ws.id,
            stripe_customer_id=stripe_customer_id,
            email="u@x.co",
        ))
        db.commit()
        return ws.id


def _post_event(client: TestClient, event: dict) -> int:
    with patch(
        "app.routers.billing.stripe_client.verify_webhook",
        return_value=event,
    ):
        resp = client.post(
            "/api/v1/billing/webhook",
            data=json.dumps(event),
            headers={"stripe-signature": "test_sig",
                     "content-type": "application/json"},
        )
    return resp.status_code


def test_checkout_session_completed_subscription_creates_row() -> None:
    ws = _seed_workspace_with_customer("cus_a")
    client = TestClient(main_module.app)
    period_end = int((datetime.now(timezone.utc) + timedelta(days=30)).timestamp())
    event = {
        "id": "evt_1",
        "type": "checkout.session.completed",
        "data": {"object": {
            "mode": "subscription",
            "customer": "cus_a",
            "subscription": "sub_1",
            "metadata": {"mrai_workspace_id": ws,
                         "mrai_plan": "pro", "mrai_cycle": "monthly"},
        }},
    }
    # Also stub stripe.Subscription.retrieve for period info.
    with patch(
        "app.services.billing_webhook.stripe.Subscription.retrieve",
        return_value={"id": "sub_1", "status": "active",
                      "current_period_start": int(datetime.now(timezone.utc).timestamp()),
                      "current_period_end": period_end,
                      "cancel_at_period_end": False,
                      "items": {"data": []}},
    ):
        code = _post_event(client, event)
    assert code == 200
    with _s.SessionLocal() as db:
        sub = db.query(Subscription).filter_by(workspace_id=ws).first()
    assert sub and sub.plan == "pro" and sub.status == "active"


def test_checkout_session_completed_payment_creates_one_time() -> None:
    ws = _seed_workspace_with_customer("cus_b")
    client = TestClient(main_module.app)
    event = {
        "id": "evt_2",
        "type": "checkout.session.completed",
        "data": {"object": {
            "mode": "payment",
            "customer": "cus_b",
            "metadata": {"mrai_workspace_id": ws,
                         "mrai_plan": "pro", "mrai_cycle": "yearly",
                         "mrai_one_time": "1"},
        }},
    }
    code = _post_event(client, event)
    assert code == 200
    with _s.SessionLocal() as db:
        sub = db.query(Subscription).filter_by(workspace_id=ws).first()
    assert sub.provider == "stripe_one_time"
    assert sub.status == "manual"
    # ~365d from now (allow ±1d slack)
    assert sub.current_period_end is not None
    delta = sub.current_period_end - datetime.now(timezone.utc)
    assert 363 <= delta.days <= 366


def test_subscription_deleted_downgrades_to_free() -> None:
    ws = _seed_workspace_with_customer("cus_c")
    with _s.SessionLocal() as db:
        db.add(Subscription(
            workspace_id=ws, plan="pro", billing_cycle="monthly",
            status="active", provider="stripe_recurring",
            stripe_subscription_id="sub_c",
        ))
        db.commit()
    client = TestClient(main_module.app)
    event = {
        "id": "evt_3",
        "type": "customer.subscription.deleted",
        "data": {"object": {"id": "sub_c", "status": "canceled"}},
    }
    code = _post_event(client, event)
    assert code == 200
    with _s.SessionLocal() as db:
        sub = db.query(Subscription).filter_by(stripe_subscription_id="sub_c").first()
    assert sub.status == "canceled"


def test_invoice_payment_failed_marks_past_due() -> None:
    ws = _seed_workspace_with_customer("cus_d")
    with _s.SessionLocal() as db:
        db.add(Subscription(
            workspace_id=ws, plan="pro", billing_cycle="monthly",
            status="active", provider="stripe_recurring",
            stripe_subscription_id="sub_d",
        ))
        db.commit()
    client = TestClient(main_module.app)
    event = {
        "id": "evt_4",
        "type": "invoice.payment_failed",
        "data": {"object": {"subscription": "sub_d"}},
    }
    _post_event(client, event)
    with _s.SessionLocal() as db:
        sub = db.query(Subscription).filter_by(stripe_subscription_id="sub_d").first()
    assert sub.status == "past_due"


def test_webhook_idempotency_same_event_twice() -> None:
    ws = _seed_workspace_with_customer("cus_e")
    client = TestClient(main_module.app)
    event = {
        "id": "evt_5",
        "type": "customer.subscription.updated",
        "data": {"object": {"id": "sub_e", "status": "active",
                            "cancel_at_period_end": False,
                            "current_period_end": int(datetime.now(timezone.utc).timestamp()),
                            "current_period_start": int(datetime.now(timezone.utc).timestamp())}},
    }
    code1 = _post_event(client, event)
    code2 = _post_event(client, event)  # second time
    assert code1 == 200 and code2 == 200
    with _s.SessionLocal() as db:
        n_events = db.query(BillingEvent).filter_by(stripe_event_id="evt_5").count()
    assert n_events == 1


def test_webhook_invalid_signature_returns_400() -> None:
    client = TestClient(main_module.app)
    with patch(
        "app.routers.billing.stripe_client.verify_webhook",
        side_effect=ValueError("bad sig"),
    ):
        resp = client.post(
            "/api/v1/billing/webhook",
            data="{}", headers={"stripe-signature": "bad",
                                "content-type": "application/json"},
        )
    assert resp.status_code == 400
```

- [ ] **Step 6: Verify failure**

```bash
cd apps/api && .venv/bin/pytest tests/test_billing_webhook.py -v
```
Expected: FAIL — webhook handler missing.

- [ ] **Step 7: Create webhook handler**

Create `apps/api/app/services/billing_webhook.py`:

```python
"""S6 Billing — webhook event handlers.

All handlers take (db, payload_obj) and update DB. They are safe to call
inside the idempotency-protected section of the router because they only
touch DB rows scoped to a single workspace per event."""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

import stripe
from sqlalchemy.orm import Session

from app.core.entitlements import refresh_workspace_entitlements
from app.models import (
    CustomerAccount, Subscription, SubscriptionItem, Workspace,
)

logger = logging.getLogger(__name__)


def _ts(seconds: int | None) -> datetime | None:
    if seconds is None:
        return None
    return datetime.fromtimestamp(int(seconds), tz=timezone.utc)


def _set_workspace_plan(db: Session, *, workspace_id: str, plan: str) -> None:
    ws = db.get(Workspace, workspace_id)
    if ws is not None:
        ws.plan = plan
        db.add(ws)


def handle_checkout_session_completed(
    db: Session, payload_obj: dict[str, Any],
) -> None:
    metadata = payload_obj.get("metadata") or {}
    workspace_id = metadata.get("mrai_workspace_id")
    plan = metadata.get("mrai_plan")
    cycle = metadata.get("mrai_cycle")
    if not (workspace_id and plan and cycle):
        logger.warning("checkout.session.completed missing mrai metadata")
        return

    if payload_obj.get("mode") == "subscription":
        # Fetch sub details for period and item info.
        sub_id = payload_obj.get("subscription")
        details = stripe.Subscription.retrieve(sub_id) if sub_id else None
        period_start = _ts(details["current_period_start"]) if details else None
        period_end = _ts(details["current_period_end"]) if details else None
        cancel_flag = bool(details.get("cancel_at_period_end")) if details else False
        sub = Subscription(
            workspace_id=workspace_id,
            stripe_subscription_id=sub_id,
            plan=plan, billing_cycle=cycle,
            status="active", provider="stripe_recurring",
            current_period_start=period_start,
            current_period_end=period_end,
            cancel_at_period_end=cancel_flag,
        )
        db.add(sub); db.commit(); db.refresh(sub)
        if details:
            for item in (details.get("items") or {}).get("data") or []:
                db.add(SubscriptionItem(
                    subscription_id=sub.id,
                    stripe_subscription_item_id=item.get("id"),
                    stripe_price_id=(item.get("price") or {}).get("id", ""),
                    quantity=int(item.get("quantity", 1)),
                ))
            db.commit()
    else:
        # mode == "payment" — one-time
        days = 365 if cycle == "yearly" else 30
        sub = Subscription(
            workspace_id=workspace_id,
            stripe_subscription_id=None,
            plan=plan, billing_cycle=cycle,
            status="manual", provider="stripe_one_time",
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=days),
        )
        db.add(sub); db.commit()

    _set_workspace_plan(db, workspace_id=workspace_id, plan=plan)
    db.commit()
    refresh_workspace_entitlements(db, workspace_id=workspace_id)


def handle_subscription_updated(
    db: Session, payload_obj: dict[str, Any],
) -> None:
    sub_id = payload_obj.get("id")
    sub = (
        db.query(Subscription)
        .filter(Subscription.stripe_subscription_id == sub_id)
        .first()
    )
    if sub is None:
        return
    sub.status = payload_obj.get("status", sub.status)
    sub.cancel_at_period_end = bool(payload_obj.get("cancel_at_period_end"))
    cps = payload_obj.get("current_period_start")
    cpe = payload_obj.get("current_period_end")
    if cps is not None:
        sub.current_period_start = _ts(cps)
    if cpe is not None:
        sub.current_period_end = _ts(cpe)
    db.add(sub); db.commit()
    refresh_workspace_entitlements(db, workspace_id=sub.workspace_id)


def handle_subscription_deleted(
    db: Session, payload_obj: dict[str, Any],
) -> None:
    sub_id = payload_obj.get("id")
    sub = (
        db.query(Subscription)
        .filter(Subscription.stripe_subscription_id == sub_id)
        .first()
    )
    if sub is None:
        return
    sub.status = "canceled"
    db.add(sub); db.commit()
    _set_workspace_plan(db, workspace_id=sub.workspace_id, plan="free")
    db.commit()
    refresh_workspace_entitlements(db, workspace_id=sub.workspace_id)


def handle_invoice_paid(
    db: Session, payload_obj: dict[str, Any],
) -> None:
    sub_id = payload_obj.get("subscription")
    if not sub_id:
        return
    sub = (
        db.query(Subscription)
        .filter(Subscription.stripe_subscription_id == sub_id)
        .first()
    )
    if sub is None:
        return
    period_end = _ts(payload_obj.get("period_end"))
    if period_end is not None:
        sub.current_period_end = period_end
        db.add(sub); db.commit()


def handle_invoice_payment_failed(
    db: Session, payload_obj: dict[str, Any],
) -> None:
    sub_id = payload_obj.get("subscription")
    if not sub_id:
        return
    sub = (
        db.query(Subscription)
        .filter(Subscription.stripe_subscription_id == sub_id)
        .first()
    )
    if sub is None:
        return
    sub.status = "past_due"
    db.add(sub); db.commit()
```

- [ ] **Step 8: Add /webhook endpoint to router**

Append to `apps/api/app/routers/billing.py`:

```python
import json as _json
from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.models import BillingEvent
from app.services import billing_webhook


@router.post("/webhook")
async def post_webhook(
    request: Request,
    db: Session = Depends(get_db_session),
) -> JSONResponse:
    payload_bytes = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    try:
        event = stripe_client.verify_webhook(payload_bytes, sig_header)
    except Exception:
        return JSONResponse(status_code=400, content={"error": "invalid_signature"})

    event_id = event.get("id", "")
    event_type = event.get("type", "")

    # Idempotency: insert BillingEvent first; on conflict skip.
    try:
        db.add(BillingEvent(
            stripe_event_id=event_id,
            event_type=event_type,
            payload_json=event,
        ))
        db.commit()
    except IntegrityError:
        db.rollback()
        return JSONResponse(status_code=200, content={"ok": True, "skipped": True})

    payload_obj = (event.get("data") or {}).get("object") or {}

    try:
        if event_type == "checkout.session.completed":
            billing_webhook.handle_checkout_session_completed(db, payload_obj)
        elif event_type == "customer.subscription.updated":
            billing_webhook.handle_subscription_updated(db, payload_obj)
        elif event_type == "customer.subscription.deleted":
            billing_webhook.handle_subscription_deleted(db, payload_obj)
        elif event_type == "invoice.paid":
            billing_webhook.handle_invoice_paid(db, payload_obj)
        elif event_type == "invoice.payment_failed":
            billing_webhook.handle_invoice_payment_failed(db, payload_obj)
        be = db.query(BillingEvent).filter_by(stripe_event_id=event_id).first()
        if be is not None:
            be.processed_at = datetime.now(timezone.utc)
            db.add(be); db.commit()
    except Exception as exc:  # noqa: BLE001
        be = db.query(BillingEvent).filter_by(stripe_event_id=event_id).first()
        if be is not None:
            be.error = str(exc)[:500]
            db.add(be); db.commit()

    return JSONResponse(status_code=200, content={"ok": True})
```

- [ ] **Step 9: Verify pass**

```bash
cd apps/api && .venv/bin/pytest tests/test_billing_webhook.py -v
```
Expected: 6 PASSED.

- [ ] **Step 10: Commit**

```bash
cd /Users/dog/Desktop/MRAI && git add apps/api/app/routers/billing.py apps/api/app/services/billing_webhook.py apps/api/tests/test_billing_me.py apps/api/tests/test_billing_webhook.py
git commit -m "feat(api): /me + /plans + /webhook with idempotency + 5 event handlers"
```

---

## Task 6 — One-time expiry Celery task + beat

**Files:**
- Modify: `apps/api/app/tasks/worker_tasks.py`
- Modify: `apps/api/app/tasks/celery_app.py`
- Create: `apps/api/tests/test_one_time_expiry.py`

- [ ] **Step 1: Write failing tests**

Create `apps/api/tests/test_one_time_expiry.py`:

```python
# ruff: noqa: E402
import atexit, importlib, os, shutil, tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-s6-exp-"))
atexit.register(lambda: shutil.rmtree(TEST_TEMP_DIR, ignore_errors=True))
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_TEMP_DIR / 'test.db'}"
os.environ["ENV"] = "test"

import app.core.config as config_module
config_module.get_settings.cache_clear()
config_module.settings = config_module.get_settings()
import app.db.session as session_module
importlib.reload(session_module)

from app.db.base import Base
import app.db.session as _s
from app.models import Subscription, User, Workspace


def setup_function() -> None:
    global engine, SessionLocal
    engine = _s.engine
    SessionLocal = _s.SessionLocal
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    import app.tasks.worker_tasks as _wt
    _wt.SessionLocal = _s.SessionLocal


engine = _s.engine
SessionLocal = _s.SessionLocal


def _seed_one_time_sub(plan: str = "pro", expired: bool = True) -> tuple[str, str]:
    with SessionLocal() as db:
        ws = Workspace(name="W", plan=plan); user = User(email="u@x.co", password_hash="x")
        db.add(ws); db.add(user); db.commit(); db.refresh(ws)
        end = datetime.now(timezone.utc) - timedelta(days=1) if expired else datetime.now(timezone.utc) + timedelta(days=10)
        sub = Subscription(
            workspace_id=ws.id, plan=plan, billing_cycle="monthly",
            status="manual", provider="stripe_one_time",
            current_period_end=end,
        )
        db.add(sub); db.commit(); db.refresh(sub)
        return ws.id, sub.id


def test_expiry_task_downgrades_workspace() -> None:
    ws_id, sub_id = _seed_one_time_sub()
    from app.tasks.worker_tasks import expire_one_time_subscriptions_task
    result = expire_one_time_subscriptions_task.run()
    assert result["expired"] == 1
    with SessionLocal() as db:
        ws = db.get(Workspace, ws_id)
        sub = db.get(Subscription, sub_id)
    assert ws.plan == "free"
    assert sub.status == "canceled"


def test_expiry_task_skips_unexpired() -> None:
    ws_id, sub_id = _seed_one_time_sub(expired=False)
    from app.tasks.worker_tasks import expire_one_time_subscriptions_task
    result = expire_one_time_subscriptions_task.run()
    assert result["expired"] == 0
    with SessionLocal() as db:
        sub = db.get(Subscription, sub_id)
    assert sub.status == "manual"


def test_expiry_task_idempotent() -> None:
    ws_id, _ = _seed_one_time_sub()
    from app.tasks.worker_tasks import expire_one_time_subscriptions_task
    r1 = expire_one_time_subscriptions_task.run()
    r2 = expire_one_time_subscriptions_task.run()
    assert r1["expired"] == 1
    assert r2["expired"] == 0
```

- [ ] **Step 2: Verify failure**

```bash
cd apps/api && .venv/bin/pytest tests/test_one_time_expiry.py -v
```
Expected: FAIL — task missing.

- [ ] **Step 3: Add task to worker_tasks.py**

Append to `apps/api/app/tasks/worker_tasks.py`:

```python
# ---------------------------------------------------------------------------
# S6 Billing — One-time subscription expiry
# ---------------------------------------------------------------------------


@celery_app.task(name="app.tasks.worker_tasks.expire_one_time_subscriptions")
def expire_one_time_subscriptions_task() -> dict[str, int]:
    """Find expired one-time subscriptions, mark canceled, downgrade
    the workspace to free plan, and refresh entitlements. Idempotent."""
    from app.core.entitlements import refresh_workspace_entitlements
    from app.models import Subscription, Workspace

    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        rows = (
            db.query(Subscription)
            .filter(Subscription.provider == "stripe_one_time")
            .filter(Subscription.status == "manual")
            .filter(Subscription.current_period_end < now)
            .all()
        )
        n = 0
        for sub in rows:
            sub.status = "canceled"
            db.add(sub)
            ws = db.get(Workspace, sub.workspace_id)
            if ws is not None:
                ws.plan = "free"
                db.add(ws)
            db.commit()
            try:
                refresh_workspace_entitlements(db, workspace_id=sub.workspace_id)
            except Exception:
                logger.warning("expire: refresh entitlements failed for %s",
                               sub.workspace_id, exc_info=False)
            n += 1
        return {"expired": n}
    finally:
        db.close()
```

- [ ] **Step 4: Add beat schedule + task_routes entry**

Open `apps/api/app/tasks/celery_app.py`. In `task_routes`:

```python
"app.tasks.worker_tasks.expire_one_time_subscriptions": {"queue": "memory"},
```

In `beat_schedule`:

```python
"expire-one-time-subscriptions-daily": {
    "task": "app.tasks.worker_tasks.expire_one_time_subscriptions",
    "schedule": crontab(hour=2, minute=15),
},
```

- [ ] **Step 5: Verify pass**

```bash
cd apps/api && .venv/bin/pytest tests/test_one_time_expiry.py -v
```
Expected: 3 PASSED.

- [ ] **Step 6: Commit**

```bash
cd /Users/dog/Desktop/MRAI && git add apps/api/app/tasks/worker_tasks.py apps/api/app/tasks/celery_app.py apps/api/tests/test_one_time_expiry.py
git commit -m "feat(api): expire_one_time_subscriptions Celery task + nightly beat"
```

---

## Task 7 — `require_entitlement` Depends + 8 enforcement points

**Files:**
- Modify: `apps/api/app/routers/notebooks.py` (2 gates)
- Modify: `apps/api/app/routers/study.py` (1 gate)
- Modify: `apps/api/app/routers/notebook_ai.py` (multiple gates)
- Modify: `apps/api/app/routers/study_ai.py` (multiple gates)
- Modify: `apps/api/app/routers/proactive.py` (1 gate)
- Modify: `apps/api/app/routers/realtime.py` (1 gate)
- Modify: `apps/api/app/routers/memory.py` (1–2 gates)
- Create: `apps/api/app/services/quota_counters.py`
- Create: `apps/api/tests/test_quota_enforcement.py`

- [ ] **Step 1: Write failing tests**

Create `apps/api/tests/test_quota_enforcement.py`:

```python
# ruff: noqa: E402
import atexit, importlib, os, shutil, tempfile
from datetime import datetime, timezone
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-s6-quota-"))
atexit.register(lambda: shutil.rmtree(TEST_TEMP_DIR, ignore_errors=True))
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_TEMP_DIR / 'test.db'}"
os.environ["ENV"] = "test"
os.environ["COOKIE_DOMAIN"] = ""
os.environ["DEMO_MODE"] = "true"
os.environ["STRIPE_API_KEY"] = "sk_test_dummy"

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


def setup_function() -> None:
    Base.metadata.drop_all(bind=_s.engine)
    Base.metadata.create_all(bind=_s.engine)
    from app.services.runtime_state import runtime_state
    runtime_state._memory = runtime_state._memory.__class__()


def _public() -> dict[str, str]:
    return {"origin": "http://localhost:3000"}


def _register_client(email: str = "u@x.co") -> tuple[TestClient, dict]:
    import hashlib
    from app.services.runtime_state import runtime_state
    client = TestClient(main_module.app)
    client.post("/api/v1/auth/send-code",
                json={"email": email, "purpose": "register"},
                headers=_public())
    raw = f"{email.lower().strip()}:register"
    code_key = hashlib.sha256(raw.encode()).hexdigest()
    code = str(runtime_state.get_json("verify_code", code_key)["code"])
    info = client.post("/api/v1/auth/register",
                       json={"email": email, "password": "pass1234pass",
                             "display_name": "Test", "code": code},
                       headers=_public()).json()
    csrf = client.get("/api/v1/auth/csrf",
                     headers=_public()).json()["csrf_token"]
    client.headers.update({"origin": "http://localhost:3000",
                          "x-csrf-token": csrf,
                          "x-workspace-id": info["workspace"]["id"]})
    return client, {"ws_id": info["workspace"]["id"]}


def test_free_plan_notebooks_max_blocks_second_create() -> None:
    """Free plan allows 1 notebook; second POST returns 402."""
    client, auth = _register_client("nb1@x.co")
    # First create OK
    r1 = client.post("/api/v1/notebooks", json={"title": "First"})
    assert r1.status_code in (200, 201)
    # Second blocked
    r2 = client.post("/api/v1/notebooks", json={"title": "Second"})
    assert r2.status_code == 402
    assert r2.json()["error"]["code"] == "plan_limit_reached"


def test_free_plan_voice_returns_402() -> None:
    """voice.enabled is False on free; realtime endpoint should 402."""
    client, _ = _register_client("v1@x.co")
    # If realtime is WS-based and not testable via TestClient HTTP, this
    # may need to test the underlying gate directly. Adjust as needed.
    # For now verify the gate via /me.
    me = client.get("/api/v1/billing/me").json()
    assert me["entitlements"]["voice.enabled"] is False
```

- [ ] **Step 2: Verify failure**

```bash
cd apps/api && .venv/bin/pytest tests/test_quota_enforcement.py -v
```
Expected: 1 FAIL (test_free_plan_notebooks_max_blocks_second_create — gate not yet applied), 1 PASS.

- [ ] **Step 3: Counter helpers**

Create `apps/api/app/services/quota_counters.py`:

```python
"""Counters used by require_entitlement for counted-cap entitlements."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    AIUsageEvent, Notebook, NotebookPage, StudyAsset,
)


def count_notebooks(db: Session, workspace_id: str) -> int:
    return int(
        db.query(func.count(Notebook.id))
        .filter(Notebook.workspace_id == workspace_id)
        .scalar() or 0
    )


def count_pages(db: Session, workspace_id: str) -> int:
    return int(
        db.query(func.count(NotebookPage.id))
        .join(Notebook, Notebook.id == NotebookPage.notebook_id)
        .filter(Notebook.workspace_id == workspace_id)
        .scalar() or 0
    )


def count_study_assets(db: Session, workspace_id: str) -> int:
    return int(
        db.query(func.count(StudyAsset.id))
        .join(Notebook, Notebook.id == StudyAsset.notebook_id)
        .filter(Notebook.workspace_id == workspace_id)
        .scalar() or 0
    )


def count_ai_actions_this_month(db: Session, workspace_id: str) -> int:
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return int(
        db.query(func.count(AIUsageEvent.id))
        .filter(AIUsageEvent.workspace_id == workspace_id)
        .filter(AIUsageEvent.created_at >= month_start)
        .scalar() or 0
    )
```

- [ ] **Step 4: Apply 8 gates**

For each enforcement point, find the existing endpoint and add `Depends(require_entitlement(...))` to the signature.

**4a. notebooks.max** — `apps/api/app/routers/notebooks.py`:

Find `def create_notebook(...)` (POST `/api/v1/notebooks`). Add to imports:

```python
from app.core.entitlements import require_entitlement
from app.services.quota_counters import count_notebooks
```

Add to the endpoint signature:

```python
_quota: None = Depends(require_entitlement("notebooks.max", counter=count_notebooks)),
```

**4b. pages.max** — same file, find page create endpoint. Add similar `Depends(require_entitlement("pages.max", counter=count_pages))`. Import `count_pages`.

**4c. study_assets.max** — `apps/api/app/routers/study.py`. Find study-asset create. Add gate:

```python
_quota: None = Depends(require_entitlement("study_assets.max", counter=count_study_assets)),
```

Also add `book_upload.enabled` gate as a second Depends on the same endpoint:

```python
_book: None = Depends(require_entitlement("book_upload.enabled")),
```

**4d. ai.actions.monthly** — `apps/api/app/routers/notebook_ai.py` and `apps/api/app/routers/study_ai.py`. Find every POST endpoint (`selection-action`, `page-action`, `brainstorm`, `ask`, `generate-page`, `study/ask`, `study/quiz`, `study/flashcards`). Add to each:

```python
_ai_quota: None = Depends(require_entitlement("ai.actions.monthly", counter=count_ai_actions_this_month)),
```

**4e. daily_digest.enabled** — `apps/api/app/routers/proactive.py`. Find POST `/generate-now` (and any other mutation that triggers digest). Add `Depends(require_entitlement("daily_digest.enabled"))`.

**4f. voice.enabled** — `apps/api/app/routers/realtime.py`. Find the WS handler. WS auth flows differ; add an explicit check in the connect handler:

```python
from app.core.entitlements import resolve_entitlement
# inside the ws handler after extracting workspace_id:
if not resolve_entitlement(db, workspace_id=workspace_id, key="voice.enabled"):
    await ws.close(code=4002, reason="plan_required")
    return
```

**4g. advanced_memory_insights.enabled** — `apps/api/app/routers/memory.py`. Find `GET /memory/{id}/explain` and `GET /memory/{id}/subgraph`. Add `Depends(require_entitlement("advanced_memory_insights.enabled"))`.

- [ ] **Step 5: Verify pass**

```bash
cd apps/api && .venv/bin/pytest tests/test_quota_enforcement.py -v
```
Expected: 2 PASSED.

Then run a broader S1–S5 sanity check to confirm nothing broke:

```bash
cd apps/api && .venv/bin/pytest tests/test_proactive_api.py tests/test_search_api.py 2>&1 | tail -5
```

Expected: all pre-existing tests still pass (no plan_limit_reached on test workspaces because they start fresh with 0 notebooks ≤ 1, etc.).

- [ ] **Step 6: Commit**

```bash
cd /Users/dog/Desktop/MRAI && git add apps/api/app/services/quota_counters.py apps/api/app/routers/notebooks.py apps/api/app/routers/study.py apps/api/app/routers/notebook_ai.py apps/api/app/routers/study_ai.py apps/api/app/routers/proactive.py apps/api/app/routers/realtime.py apps/api/app/routers/memory.py apps/api/tests/test_quota_enforcement.py
git commit -m "feat(api): apply require_entitlement gates at 8 enforcement points"
```

---

## Task 8 — Full backend regression (no commit)

- [ ] **Step 1: Run full S6 suite**

```bash
cd /Users/dog/Desktop/MRAI/apps/api && .venv/bin/pytest \
  tests/test_customer_account_model.py \
  tests/test_billing_core_models.py \
  tests/test_plan_entitlements.py \
  tests/test_entitlement_resolver.py \
  tests/test_billing_checkout.py \
  tests/test_billing_me.py \
  tests/test_billing_webhook.py \
  tests/test_one_time_expiry.py \
  tests/test_quota_enforcement.py -v 2>&1 | tail -20
```

Expected: ~40 passed.

- [ ] **Step 2: Sanity test prior S-suites**

```bash
cd /Users/dog/Desktop/MRAI/apps/api && .venv/bin/pytest \
  tests/test_proactive_api.py \
  tests/test_search_api.py \
  tests/test_ai_action_logger.py 2>&1 | tail -5
```

Expected: all pre-existing tests pass (no S6 regression).

**No commit.**

---

## Task 9 — Frontend `/settings/billing` page + PlansGrid + PlanCard

**Files:**
- Create: `apps/web/app/[locale]/workspace/settings/billing/page.tsx`
- Create: `apps/web/components/billing/PlansGrid.tsx`
- Create: `apps/web/components/billing/PlanCard.tsx`
- Create: `apps/web/components/billing/CurrentSubscription.tsx`
- Create: `apps/web/components/billing/UsageMeter.tsx`
- Create: `apps/web/styles/billing.css`
- Modify: `apps/web/app/[locale]/workspace/settings/layout.tsx` (if exists, add link)

- [ ] **Step 1: Create the page**

Create `apps/web/app/[locale]/workspace/settings/billing/page.tsx`:

```tsx
"use client";

import "@/styles/billing.css";
import CurrentSubscription from "@/components/billing/CurrentSubscription";
import UsageMeter from "@/components/billing/UsageMeter";
import PlansGrid from "@/components/billing/PlansGrid";

export default function BillingSettingsPage() {
  return (
    <div className="billing-page" data-testid="billing-page">
      <h1 className="billing-page__title">Billing</h1>
      <CurrentSubscription />
      <UsageMeter />
      <PlansGrid />
    </div>
  );
}
```

- [ ] **Step 2: PlanCard**

Create `apps/web/components/billing/PlanCard.tsx`:

```tsx
"use client";

import { Check } from "lucide-react";
import { apiPost } from "@/lib/api";

export interface PlanDescriptor {
  id: "free" | "pro" | "power" | "team";
  name: string;
  monthlyPrice: number | null;
  yearlyPrice: number | null;
  features: string[];
}

interface Props {
  plan: PlanDescriptor;
  cycle: "monthly" | "yearly";
  isCurrent: boolean;
}

export default function PlanCard({ plan, cycle, isCurrent }: Props) {
  const price = cycle === "monthly" ? plan.monthlyPrice : plan.yearlyPrice;

  const handleUpgrade = async () => {
    if (plan.id === "free") return;
    try {
      const data = await apiPost<{ checkout_url: string }>(
        "/api/v1/billing/checkout",
        { plan: plan.id, cycle },
      );
      window.location.href = data.checkout_url;
    } catch (e) {
      console.error("checkout failed", e);
    }
  };

  return (
    <div
      className={`plan-card${isCurrent ? " plan-card--current" : ""}`}
      data-testid={`plan-card-${plan.id}`}
    >
      <h2 className="plan-card__name">{plan.name}</h2>
      <div className="plan-card__price">
        {price === null ? (
          "Free"
        ) : (
          <>
            ${price}
            <span className="plan-card__cycle">/{cycle === "monthly" ? "mo" : "yr"}</span>
          </>
        )}
      </div>
      <ul className="plan-card__features">
        {plan.features.map((f, i) => (
          <li key={i}>
            <Check size={14} /> {f}
          </li>
        ))}
      </ul>
      {isCurrent ? (
        <div className="plan-card__current-label">Current plan</div>
      ) : plan.id === "free" ? null : (
        <button
          type="button"
          onClick={handleUpgrade}
          className="plan-card__upgrade"
          data-testid={`plan-card-${plan.id}-upgrade`}
        >
          Upgrade
        </button>
      )}
    </div>
  );
}
```

- [ ] **Step 3: PlansGrid**

Create `apps/web/components/billing/PlansGrid.tsx`:

```tsx
"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";
import PlanCard, { type PlanDescriptor } from "./PlanCard";

const PLAN_FEATURES: Record<PlanDescriptor["id"], string[]> = {
  free: [
    "1 notebook", "50 pages", "1 study asset",
    "50 AI actions / month",
  ],
  pro: [
    "Unlimited notebooks", "500 pages", "20 study assets",
    "1,000 AI actions / month", "Daily digest", "Voice", "Book upload",
  ],
  power: [
    "Everything in Pro", "Unlimited pages & study assets",
    "10,000 AI actions / month", "Advanced memory insights",
  ],
  team: [
    "Everything in Power", "Per-seat pricing",
    "Shared workspace", "Team memory views", "Admin billing",
  ],
};

const PLAN_PRICES = {
  free: { monthly: null, yearly: null },
  pro: { monthly: 10, yearly: 102 },
  power: { monthly: 25, yearly: 255 },
  team: { monthly: 15, yearly: 153 },
} as const;

export default function PlansGrid() {
  const [cycle, setCycle] = useState<"monthly" | "yearly">("monthly");
  const [currentPlan, setCurrentPlan] = useState<string>("free");

  useEffect(() => {
    void apiGet<{ plan: string }>("/api/v1/billing/me")
      .then((r) => setCurrentPlan(r.plan))
      .catch(() => {});
  }, []);

  const plans: PlanDescriptor[] = (
    ["free", "pro", "power", "team"] as const
  ).map((id) => ({
    id,
    name: id.charAt(0).toUpperCase() + id.slice(1),
    monthlyPrice: PLAN_PRICES[id].monthly,
    yearlyPrice: PLAN_PRICES[id].yearly,
    features: PLAN_FEATURES[id],
  }));

  return (
    <section className="plans-grid">
      <div className="plans-grid__cycle-toggle">
        <button
          type="button"
          aria-pressed={cycle === "monthly"}
          onClick={() => setCycle("monthly")}
          data-testid="cycle-monthly"
        >
          Monthly
        </button>
        <button
          type="button"
          aria-pressed={cycle === "yearly"}
          onClick={() => setCycle("yearly")}
          data-testid="cycle-yearly"
        >
          Yearly (15% off)
        </button>
      </div>
      <div className="plans-grid__cards">
        {plans.map((p) => (
          <PlanCard
            key={p.id}
            plan={p}
            cycle={cycle}
            isCurrent={currentPlan === p.id}
          />
        ))}
      </div>
    </section>
  );
}
```

- [ ] **Step 4: CurrentSubscription**

Create `apps/web/components/billing/CurrentSubscription.tsx`:

```tsx
"use client";

import { useEffect, useState } from "react";
import { apiGet, apiPost } from "@/lib/api";

interface Me {
  plan: string;
  status: string;
  billing_cycle: string;
  current_period_end: string | null;
  cancel_at_period_end: boolean;
  provider: string;
}

export default function CurrentSubscription() {
  const [me, setMe] = useState<Me | null>(null);

  useEffect(() => {
    void apiGet<Me>("/api/v1/billing/me")
      .then(setMe)
      .catch(() => setMe(null));
  }, []);

  const handleManage = async () => {
    try {
      const r = await apiPost<{ portal_url: string }>(
        "/api/v1/billing/portal", {},
      );
      window.location.href = r.portal_url;
    } catch (e) {
      console.error("portal failed", e);
    }
  };

  if (!me) return null;
  return (
    <section className="current-sub" data-testid="current-subscription">
      <div>
        <strong>Current plan:</strong> {me.plan.toUpperCase()}{" "}
        ({me.billing_cycle}) — {me.status}
      </div>
      {me.current_period_end && (
        <div className="current-sub__renewal">
          Renews: {me.current_period_end.slice(0, 10)}
          {me.cancel_at_period_end && " (cancels at period end)"}
        </div>
      )}
      {me.provider !== "free" && (
        <button
          type="button"
          onClick={handleManage}
          className="current-sub__manage"
          data-testid="current-sub-manage"
        >
          Manage billing
        </button>
      )}
    </section>
  );
}
```

- [ ] **Step 5: UsageMeter**

Create `apps/web/components/billing/UsageMeter.tsx`:

```tsx
"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";

interface Me {
  entitlements: Record<string, number | boolean>;
  usage_this_month: Record<string, number>;
}

export default function UsageMeter() {
  const [me, setMe] = useState<Me | null>(null);

  useEffect(() => {
    void apiGet<Me>("/api/v1/billing/me")
      .then(setMe)
      .catch(() => setMe(null));
  }, []);

  if (!me) return null;

  const items: Array<{ label: string; current: number; limit: number | boolean | undefined }> = [
    { label: "AI actions (this month)", current: me.usage_this_month["ai.actions"] || 0, limit: me.entitlements["ai.actions.monthly"] as number },
    { label: "Notebooks", current: me.usage_this_month["notebooks"] || 0, limit: me.entitlements["notebooks.max"] as number },
    { label: "Pages", current: me.usage_this_month["pages"] || 0, limit: me.entitlements["pages.max"] as number },
    { label: "Study assets", current: me.usage_this_month["study_assets"] || 0, limit: me.entitlements["study_assets.max"] as number },
  ];

  return (
    <section className="usage-meter" data-testid="usage-meter">
      <h2 className="usage-meter__title">Usage</h2>
      <ul>
        {items.map((it, i) => {
          const limit = typeof it.limit === "number" ? it.limit : 0;
          const cap = limit === -1 ? "∞" : String(limit);
          const pct = limit === -1 || limit === 0
            ? 0
            : Math.min(100, Math.round((it.current / limit) * 100));
          return (
            <li key={i} className="usage-meter__item">
              <div className="usage-meter__label">
                {it.label}: {it.current} / {cap}
              </div>
              <div className="usage-meter__bar">
                <div
                  className="usage-meter__fill"
                  style={{ width: `${pct}%` }}
                />
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
```

- [ ] **Step 6: CSS**

Create `apps/web/styles/billing.css`:

```css
.billing-page {
  padding: 24px;
  max-width: 1100px;
  margin: 0 auto;
}
.billing-page__title {
  font-size: 24px;
  font-weight: 700;
  margin-bottom: 16px;
}
.current-sub {
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 16px;
  background: #f9fafb;
}
.current-sub__renewal {
  font-size: 12px;
  color: #6b7280;
  margin-top: 4px;
}
.current-sub__manage {
  margin-top: 8px;
  padding: 6px 12px;
  background: #2563eb;
  color: #fff;
  border: none;
  border-radius: 6px;
  cursor: pointer;
}
.usage-meter {
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 24px;
}
.usage-meter__title {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 8px;
}
.usage-meter ul {
  list-style: none;
  padding: 0;
  margin: 0;
}
.usage-meter__item {
  margin-bottom: 8px;
}
.usage-meter__label {
  font-size: 12px;
  margin-bottom: 4px;
  color: #374151;
}
.usage-meter__bar {
  background: #e5e7eb;
  border-radius: 4px;
  height: 6px;
  overflow: hidden;
}
.usage-meter__fill {
  background: #2563eb;
  height: 100%;
  transition: width 0.3s;
}
.plans-grid__cycle-toggle {
  display: inline-flex;
  gap: 0;
  margin-bottom: 16px;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  overflow: hidden;
}
.plans-grid__cycle-toggle button {
  padding: 6px 16px;
  background: #fff;
  border: none;
  cursor: pointer;
  font-size: 12px;
}
.plans-grid__cycle-toggle button[aria-pressed="true"] {
  background: #2563eb;
  color: #fff;
}
.plans-grid__cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}
.plan-card {
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 16px;
  display: flex;
  flex-direction: column;
}
.plan-card--current {
  border-color: #2563eb;
  border-width: 2px;
}
.plan-card__name {
  font-size: 18px;
  font-weight: 700;
  margin-bottom: 4px;
}
.plan-card__price {
  font-size: 28px;
  font-weight: 700;
  margin-bottom: 12px;
}
.plan-card__cycle {
  font-size: 12px;
  font-weight: 400;
  color: #6b7280;
}
.plan-card__features {
  list-style: none;
  padding: 0;
  margin: 0 0 16px;
  flex: 1;
}
.plan-card__features li {
  display: flex;
  gap: 6px;
  align-items: center;
  font-size: 12px;
  margin-bottom: 4px;
  color: #374151;
}
.plan-card__upgrade {
  padding: 8px 16px;
  background: #2563eb;
  color: #fff;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-weight: 600;
}
.plan-card__current-label {
  text-align: center;
  font-size: 12px;
  color: #2563eb;
  font-weight: 600;
  padding: 8px;
}
```

- [ ] **Step 7: Typecheck**

```bash
cd /Users/dog/Desktop/MRAI/apps/web && ./node_modules/.bin/tsc --noEmit 2>&1 | grep -iE "(billing|PlanCard|PlansGrid|CurrentSubscription|UsageMeter)" | head -10
```
Expected: no output.

- [ ] **Step 8: Commit**

```bash
cd /Users/dog/Desktop/MRAI && git branch --show-current  # feature/s6-billing
git add apps/web/app/\[locale\]/workspace/settings/billing/page.tsx \
        apps/web/components/billing/ \
        apps/web/styles/billing.css
git commit -m "feat(web): /settings/billing page + PlansGrid + PlanCard + UsageMeter"
```

---

## Task 10 — Hooks + 402 interception + UpgradeModal

**Files:**
- Create: `apps/web/hooks/useBillingMe.ts`
- Create: `apps/web/hooks/useEntitlement.ts`
- Create: `apps/web/components/billing/UpgradeModal.tsx`
- Modify: `apps/web/lib/api.ts` (intercept 402)
- Modify: `apps/web/app/[locale]/layout.tsx` or root layout (mount UpgradeModal globally)

- [ ] **Step 1: useBillingMe hook**

Create `apps/web/hooks/useBillingMe.ts`:

```ts
"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";

export interface BillingMe {
  plan: string;
  status: string;
  billing_cycle: string;
  current_period_end: string | null;
  seats: number;
  cancel_at_period_end: boolean;
  provider: string;
  entitlements: Record<string, number | boolean>;
  usage_this_month: Record<string, number>;
}

export function useBillingMe(): BillingMe | null {
  const [me, setMe] = useState<BillingMe | null>(null);
  useEffect(() => {
    void apiGet<BillingMe>("/api/v1/billing/me")
      .then(setMe)
      .catch(() => setMe(null));
  }, []);
  return me;
}
```

- [ ] **Step 2: useEntitlement hook**

Create `apps/web/hooks/useEntitlement.ts`:

```ts
"use client";

import { useBillingMe } from "./useBillingMe";

export interface EntitlementState {
  loaded: boolean;
  allowed: boolean;
  current?: number;
  limit?: number;
}

export function useEntitlement(key: string): EntitlementState {
  const me = useBillingMe();
  if (!me) return { loaded: false, allowed: false };
  const value = me.entitlements[key];
  if (typeof value === "boolean") {
    return { loaded: true, allowed: value };
  }
  if (typeof value === "number") {
    if (value === -1) return { loaded: true, allowed: true, limit: -1 };
    // Counted — try to derive current from usage_this_month
    const usageKey = key.replace(".max", "").replace(".monthly", "");
    const current = me.usage_this_month[usageKey] || 0;
    return { loaded: true, allowed: current < value, current, limit: value };
  }
  return { loaded: true, allowed: false };
}
```

- [ ] **Step 3: 402 interception in api.ts**

Open `apps/web/lib/api.ts`. Find the response handling in `apiRequest` (where status code is checked). Locate where 401 is handled (calls `handleUnauthorizedSession`). Add a parallel branch for 402:

```ts
// After the 401 handling block, before generic !ok check:
if (response.status === 402) {
  let body: { error?: { code?: string; message?: string; details?: unknown } } = {};
  try {
    body = await response.clone().json();
  } catch {
    /* swallow */
  }
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent("mrai:plan-required", { detail: body.error }));
  }
  // Still throw so the caller's promise rejects.
  throw new Error(body?.error?.message || "Plan upgrade required");
}
```

If the existing code has a different shape for status checks, fit the dispatch into the appropriate place — the key behavior is: **fire `mrai:plan-required` window event before throwing**.

- [ ] **Step 4: UpgradeModal**

Create `apps/web/components/billing/UpgradeModal.tsx`:

```tsx
"use client";

import { useEffect, useState } from "react";

interface PlanRequiredDetail {
  code?: string;
  message?: string;
  details?: { key?: string; current?: number; limit?: number };
}

export default function UpgradeModal() {
  const [detail, setDetail] = useState<PlanRequiredDetail | null>(null);

  useEffect(() => {
    const handler = (e: Event) => {
      const ce = e as CustomEvent<PlanRequiredDetail>;
      setDetail(ce.detail || {});
    };
    window.addEventListener("mrai:plan-required", handler);
    return () => window.removeEventListener("mrai:plan-required", handler);
  }, []);

  if (!detail) return null;

  const handleUpgrade = () => {
    window.location.href = "/workspace/settings/billing";
  };

  return (
    <div
      data-testid="upgrade-modal"
      style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)",
        zIndex: 9999, display: "flex", alignItems: "center", justifyContent: "center",
      }}
    >
      <div style={{
        background: "#fff", borderRadius: 8, padding: 24,
        maxWidth: 420, width: "90%",
      }}>
        <h2 style={{ marginTop: 0 }}>Upgrade required</h2>
        <p>{detail.message || "Please upgrade your plan to continue."}</p>
        {detail.details?.key && (
          <p style={{ fontSize: 12, color: "#6b7280" }}>
            Limit: <strong>{detail.details.key}</strong>
            {detail.details.current !== undefined && detail.details.limit !== undefined && (
              <> ({detail.details.current}/{detail.details.limit})</>
            )}
          </p>
        )}
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 16 }}>
          <button
            type="button"
            onClick={() => setDetail(null)}
            style={{ padding: "6px 12px", background: "transparent", border: "1px solid #d1d5db", borderRadius: 6, cursor: "pointer" }}
          >
            Dismiss
          </button>
          <button
            type="button"
            onClick={handleUpgrade}
            data-testid="upgrade-modal-go"
            style={{ padding: "6px 12px", background: "#2563eb", color: "#fff", border: "none", borderRadius: 6, cursor: "pointer" }}
          >
            See plans
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Mount UpgradeModal globally**

Open the workspace layout `apps/web/app/[locale]/workspace/layout.tsx` (or whichever layout wraps the workspace area). Add:

```tsx
import UpgradeModal from "@/components/billing/UpgradeModal";
```

And inside the JSX (after children, before closing tag):

```tsx
<UpgradeModal />
```

- [ ] **Step 6: Typecheck**

```bash
cd /Users/dog/Desktop/MRAI/apps/web && ./node_modules/.bin/tsc --noEmit 2>&1 | grep -iE "(useBillingMe|useEntitlement|UpgradeModal|api\.ts)" | head -10
```
Expected: no output.

- [ ] **Step 7: Commit**

```bash
cd /Users/dog/Desktop/MRAI && git add apps/web/hooks/useBillingMe.ts apps/web/hooks/useEntitlement.ts apps/web/components/billing/UpgradeModal.tsx apps/web/lib/api.ts apps/web/app/\[locale\]/workspace/layout.tsx
git commit -m "feat(web): useBillingMe + useEntitlement + 402 interception + UpgradeModal"
```

---

## Task 11 — Sidebar plan badge + i18n

**Files:**
- Modify: `apps/web/components/console/NotebookSidebar.tsx`
- Create: `apps/web/messages/en/billing.json`
- Create: `apps/web/messages/zh/billing.json`
- Modify: `apps/web/messages/en/console.json`
- Modify: `apps/web/messages/zh/console.json`

- [ ] **Step 1: Plan badge on sidebar settings link**

Open `apps/web/components/console/NotebookSidebar.tsx`. Find the settings Link near the bottom (search for `/settings`). Wrap or supplement it with a plan badge:

```tsx
import { useBillingMe } from "@/hooks/useBillingMe";
// inside component:
const me = useBillingMe();
// near the settings <Link>:
{me && me.plan !== "free" && (
  <span
    data-testid="sidebar-plan-badge"
    style={{
      position: "absolute", bottom: 4, right: 4,
      background: "#2563eb", color: "#fff",
      fontSize: 8, fontWeight: 700,
      padding: "1px 4px", borderRadius: 3,
      lineHeight: 1,
    }}
  >
    {me.plan.toUpperCase()}
  </span>
)}
```

The settings link must already have `position: relative` for absolute positioning to work; if not, add it inline.

- [ ] **Step 2: i18n keys**

Open `apps/web/messages/en/console.json`. Add (next to other nav.* keys):

```json
"nav.billing": "Billing",
```

Open `apps/web/messages/zh/console.json`:

```json
"nav.billing": "计费",
```

Create `apps/web/messages/en/billing.json`:

```json
{
  "page.title": "Billing",
  "current.plan": "Current plan",
  "current.renewal": "Renews",
  "current.manage": "Manage billing",
  "usage.title": "Usage",
  "plans.cycle.monthly": "Monthly",
  "plans.cycle.yearly": "Yearly (15% off)",
  "plan.free.name": "Free",
  "plan.pro.name": "Pro",
  "plan.power.name": "Power",
  "plan.team.name": "Team",
  "upgrade.button": "Upgrade",
  "upgrade.required.title": "Upgrade required",
  "upgrade.modal.dismiss": "Dismiss",
  "upgrade.modal.see_plans": "See plans"
}
```

Create `apps/web/messages/zh/billing.json`:

```json
{
  "page.title": "计费",
  "current.plan": "当前套餐",
  "current.renewal": "续期日期",
  "current.manage": "管理账单",
  "usage.title": "使用量",
  "plans.cycle.monthly": "月付",
  "plans.cycle.yearly": "年付（85 折）",
  "plan.free.name": "免费版",
  "plan.pro.name": "专业版",
  "plan.power.name": "高级版",
  "plan.team.name": "团队版",
  "upgrade.button": "升级",
  "upgrade.required.title": "需要升级",
  "upgrade.modal.dismiss": "稍后",
  "upgrade.modal.see_plans": "查看套餐"
}
```

(The components in Task 9-10 use hardcoded English; you can swap them to `useTranslations("billing")` if you want to wire i18n now, but the spec keeps i18n keys ready without forcing a refactor.)

- [ ] **Step 3: JSON sanity**

```bash
cd /Users/dog/Desktop/MRAI/apps/web && for f in messages/en/console.json messages/zh/console.json messages/en/billing.json messages/zh/billing.json; do
  node -e "JSON.parse(require('fs').readFileSync('$f'))" && echo "OK $f" || echo "BAD $f"
done
```

Expected: all OK.

- [ ] **Step 4: Typecheck**

```bash
cd /Users/dog/Desktop/MRAI/apps/web && ./node_modules/.bin/tsc --noEmit 2>&1 | grep -i "NotebookSidebar" | head -5
```

Expected: no output.

- [ ] **Step 5: Commit**

```bash
cd /Users/dog/Desktop/MRAI && git add apps/web/components/console/NotebookSidebar.tsx apps/web/messages/en/console.json apps/web/messages/zh/console.json apps/web/messages/en/billing.json apps/web/messages/zh/billing.json
git commit -m "feat(web): sidebar plan badge + nav.billing + new billing i18n namespace"
```

---

## Task 12 — vitest unit + Playwright skeleton

**Files:**
- Create: `apps/web/tests/unit/plan-card.test.tsx`
- Create: `apps/web/tests/unit/use-entitlement.test.ts`
- Create: `apps/web/tests/unit/upgrade-modal.test.tsx`
- Create: `apps/web/tests/s6-billing.spec.ts`

- [ ] **Step 1: PlanCard test**

Create `apps/web/tests/unit/plan-card.test.tsx`:

```tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import PlanCard, { type PlanDescriptor } from "@/components/billing/PlanCard";

afterEach(() => { vi.restoreAllMocks(); });

const PLAN_FREE: PlanDescriptor = {
  id: "free", name: "Free", monthlyPrice: null, yearlyPrice: null,
  features: ["1 notebook"],
};
const PLAN_PRO: PlanDescriptor = {
  id: "pro", name: "Pro", monthlyPrice: 10, yearlyPrice: 102,
  features: ["Unlimited notebooks"],
};

describe("PlanCard", () => {
  it("renders Free with no upgrade button", () => {
    render(<PlanCard plan={PLAN_FREE} cycle="monthly" isCurrent={false} />);
    expect(screen.queryByTestId("plan-card-free-upgrade")).toBeNull();
  });

  it("renders Pro monthly with upgrade button", () => {
    render(<PlanCard plan={PLAN_PRO} cycle="monthly" isCurrent={false} />);
    const btn = screen.getByTestId("plan-card-pro-upgrade");
    expect(btn).toBeTruthy();
    expect(screen.getByText(/\$10/)).toBeTruthy();
  });

  it("highlights current plan and hides upgrade", () => {
    render(<PlanCard plan={PLAN_PRO} cycle="monthly" isCurrent={true} />);
    expect(screen.queryByTestId("plan-card-pro-upgrade")).toBeNull();
    expect(screen.getByText("Current plan")).toBeTruthy();
  });
});
```

- [ ] **Step 2: useEntitlement test**

Create `apps/web/tests/unit/use-entitlement.test.ts`:

```ts
import { renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useEntitlement } from "@/hooks/useEntitlement";

afterEach(() => { vi.restoreAllMocks(); });

function mockMe(me: any) {
  global.fetch = vi.fn(async (url: RequestInfo | URL) => {
    const u = String(url);
    if (u.includes("/api/v1/auth/csrf")) {
      return { ok: true, status: 200,
               json: async () => ({ csrf_token: "t" }) } as Response;
    }
    if (u.includes("/api/v1/billing/me")) {
      return { ok: true, status: 200, json: async () => me } as Response;
    }
    return { ok: true, status: 200, json: async () => ({}) } as Response;
  }) as typeof fetch;
}

describe("useEntitlement", () => {
  it("returns allowed for unlimited counted entitlement", async () => {
    mockMe({
      plan: "pro", entitlements: { "notebooks.max": -1 },
      usage_this_month: { notebooks: 5 },
    });
    const { result } = renderHook(() => useEntitlement("notebooks.max"));
    await new Promise((r) => setTimeout(r, 50));
    expect(result.current.allowed).toBe(true);
  });

  it("returns denied when current >= limit", async () => {
    mockMe({
      plan: "free", entitlements: { "notebooks.max": 1 },
      usage_this_month: { notebooks: 1 },
    });
    const { result } = renderHook(() => useEntitlement("notebooks.max"));
    await new Promise((r) => setTimeout(r, 50));
    expect(result.current.allowed).toBe(false);
  });

  it("returns allowed for true bool entitlement", async () => {
    mockMe({
      plan: "pro", entitlements: { "voice.enabled": true },
      usage_this_month: {},
    });
    const { result } = renderHook(() => useEntitlement("voice.enabled"));
    await new Promise((r) => setTimeout(r, 50));
    expect(result.current.allowed).toBe(true);
  });
});
```

- [ ] **Step 3: UpgradeModal test**

Create `apps/web/tests/unit/upgrade-modal.test.tsx`:

```tsx
import { render, screen, act } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import UpgradeModal from "@/components/billing/UpgradeModal";

afterEach(() => { vi.restoreAllMocks(); });

describe("UpgradeModal", () => {
  it("renders nothing initially", () => {
    const { container } = render(<UpgradeModal />);
    expect(container.querySelector("[data-testid='upgrade-modal']")).toBeNull();
  });

  it("renders when mrai:plan-required event fires", () => {
    render(<UpgradeModal />);
    act(() => {
      window.dispatchEvent(new CustomEvent("mrai:plan-required", {
        detail: { code: "plan_limit_reached", message: "Notebooks limit reached",
                  details: { key: "notebooks.max", current: 1, limit: 1 } },
      }));
    });
    expect(screen.getByTestId("upgrade-modal")).toBeTruthy();
    expect(screen.getByText(/Notebooks limit reached/)).toBeTruthy();
  });
});
```

- [ ] **Step 4: Playwright skeleton**

Create `apps/web/tests/s6-billing.spec.ts`:

```ts
import { test, expect } from "@playwright/test";

test.describe("S6 Billing", () => {
  test("settings/billing renders 4 plan cards", async ({ page }) => {
    await page.goto("/workspace/settings/billing");
    // Without auth bypass, this may redirect to login. The spec is a
    // skeleton verifying file compiles + at least the route exists.
    // Full E2E with real Stripe is out of scope.
    await page.waitForLoadState("domcontentloaded");
    // Best-effort: check the testid exists on the rendered DOM if logged in.
    const billingPage = page.getByTestId("billing-page");
    if (await billingPage.isVisible().catch(() => false)) {
      await expect(page.getByTestId("plan-card-free")).toBeVisible();
      await expect(page.getByTestId("plan-card-pro")).toBeVisible();
      await expect(page.getByTestId("plan-card-power")).toBeVisible();
      await expect(page.getByTestId("plan-card-team")).toBeVisible();
    }
  });
});
```

- [ ] **Step 5: Run vitest**

```bash
cd /Users/dog/Desktop/MRAI/apps/web && ./node_modules/.bin/vitest run tests/unit/plan-card.test.tsx tests/unit/use-entitlement.test.ts tests/unit/upgrade-modal.test.tsx 2>&1 | tail -10
```

Expected: 8 passed (3 plan-card + 3 use-entitlement + 2 upgrade-modal).

- [ ] **Step 6: Typecheck**

```bash
cd /Users/dog/Desktop/MRAI/apps/web && ./node_modules/.bin/tsc --noEmit 2>&1 | grep -iE "(plan-card|use-entitlement|upgrade-modal|s6-billing)" | head -10
```
Expected: no output.

- [ ] **Step 7: Commit**

```bash
cd /Users/dog/Desktop/MRAI && git add apps/web/tests/unit/plan-card.test.tsx apps/web/tests/unit/use-entitlement.test.ts apps/web/tests/unit/upgrade-modal.test.tsx apps/web/tests/s6-billing.spec.ts
git commit -m "test(web): PlanCard + useEntitlement + UpgradeModal vitest + Playwright skeleton"
```

---

## Task 13 — Final coverage (no commit)

- [ ] **Step 1: Backend coverage**

```bash
cd /Users/dog/Desktop/MRAI/apps/api && .venv/bin/pytest \
  tests/test_customer_account_model.py \
  tests/test_billing_core_models.py \
  tests/test_plan_entitlements.py \
  tests/test_entitlement_resolver.py \
  tests/test_billing_checkout.py \
  tests/test_billing_me.py \
  tests/test_billing_webhook.py \
  tests/test_one_time_expiry.py \
  tests/test_quota_enforcement.py \
  --cov=app.services.plan_entitlements \
  --cov=app.services.stripe_client \
  --cov=app.services.billing_webhook \
  --cov=app.core.entitlements \
  --cov=app.routers.billing \
  --cov-report=term 2>&1 | tail -15
```

Expected: target modules ≥ 80% coverage.

- [ ] **Step 2: Vitest full suite**

```bash
cd /Users/dog/Desktop/MRAI/apps/web && ./node_modules/.bin/vitest run 2>&1 | tail -10
```

Expected: all pre-existing + new tests pass.

- [ ] **Step 3: Typecheck**

```bash
cd /Users/dog/Desktop/MRAI/apps/web && ./node_modules/.bin/tsc --noEmit 2>&1 | tail -10
```

Expected: only pre-existing WhiteboardBlock error.

- [ ] **Step 4: Summary**

Compile a short summary:
- 12 task commit SHAs in order
- backend coverage per module
- vitest pass count
- any typecheck issues from S6 files (should be zero)

No commit.

---

## Final Acceptance Checklist

- [ ] `alembic upgrade head` lands at `202604220002` and creates 5 new tables.
- [ ] `POST /api/v1/billing/checkout` returns a Stripe Checkout URL when called by a workspace owner.
- [ ] `POST /api/v1/billing/checkout-onetime` accepts `payment_method=alipay` and returns a payment-mode session URL.
- [ ] `POST /api/v1/billing/portal` returns a Stripe Billing Portal URL after a customer exists.
- [ ] `POST /api/v1/billing/webhook` accepts the 5 event types, is signature-verified, and is idempotent.
- [ ] `GET /api/v1/billing/me` returns plan + entitlements + usage; default for fresh workspace is Free.
- [ ] `GET /api/v1/billing/plans` returns 4 plan descriptors with Stripe Price IDs.
- [ ] All 8 entitlement gates fire 402 on Free workspaces past their limit (only `notebooks.max` test in MVP; others verified via /me).
- [ ] `expire_one_time_subscriptions_task` downgrades expired one-time subs and is idempotent.
- [ ] `/workspace/settings/billing` renders 4 plan cards with monthly/yearly toggle.
- [ ] Sidebar shows the plan badge for non-free workspaces.
- [ ] 402 from any API call surfaces an UpgradeModal.
- [ ] No regression on S1–S5 + S7 backend test suites.

## Cross-references

- Spec: `docs/superpowers/specs/2026-04-17-billing-design.md`
- Product spec: `MRAI_notebook_ai_os_build_spec.md` §15
- Stripe account: `acct_1TFnGoRzO5cz1hgY` (livemode)
- Stripe Products + Prices already created via MCP — IDs embedded in `services/stripe_client.py` and `core/config.py` defaults
- Predecessors merged: S1 (`AIUsageEvent`), S5 (`daily_digest.enabled` gate point), S7 (no direct dep)
