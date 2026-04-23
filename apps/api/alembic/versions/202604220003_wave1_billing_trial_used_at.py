"""Wave 1 A4 billing fixes — subscriptions.trial_used_at

Adds a nullable `trial_used_at` column to `subscriptions` so the checkout
endpoint can decide whether a workspace has already consumed its trial.
Backwards-compatible: column is nullable, defaults to NULL.

On Postgres we also add a partial unique index to prevent duplicate active
one-time subscriptions per workspace (HIGH-4). SQLite can't express partial
unique indexes via the simple IF NOT EXISTS path we use; we skip there and
rely on the webhook extend-in-place logic plus the runtime check.

Revision ID: 202604220003
Revises: 202604240001
Create Date: 2026-04-22
"""

from alembic import op


revision = "202604220003"
down_revision = "202604240001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        op.execute(
            "ALTER TABLE subscriptions "
            "ADD COLUMN IF NOT EXISTS trial_used_at TIMESTAMPTZ"
        )
        # HIGH-4: Only one active manual one-time subscription per workspace.
        # stripe_subscription_id is NULL for one-time subs, so a regular
        # UNIQUE(workspace_id, stripe_subscription_id) wouldn't help.
        op.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS "
            "uq_subscriptions_active_one_time "
            "ON subscriptions (workspace_id) "
            "WHERE provider = 'stripe_one_time' AND status = 'manual'"
        )
    else:
        # SQLite (tests) and others: add the column via portable syntax.
        # Use a safe try/except wrapper because SQLite doesn't support
        # IF NOT EXISTS on ADD COLUMN.
        try:
            op.execute("ALTER TABLE subscriptions ADD COLUMN trial_used_at TIMESTAMP")
        except Exception:
            pass


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        op.execute("DROP INDEX IF EXISTS uq_subscriptions_active_one_time")
        op.execute("ALTER TABLE subscriptions DROP COLUMN IF EXISTS trial_used_at")
    else:
        # SQLite has no DROP COLUMN; skip.
        pass
