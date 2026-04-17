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
