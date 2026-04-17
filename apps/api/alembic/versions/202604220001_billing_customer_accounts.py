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
