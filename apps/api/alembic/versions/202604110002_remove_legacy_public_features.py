"""Remove legacy public-site waitlist schema

Revision ID: 202604110002
Revises: 202604110001
Create Date: 2026-04-11
"""

from alembic import op

revision = "202604110002"
down_revision = "202604110001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS idx_waitlist_created_at;
        DROP TABLE IF EXISTS waitlist;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS waitlist (
          id VARCHAR(36) PRIMARY KEY,
          email TEXT NOT NULL UNIQUE,
          source TEXT,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_waitlist_created_at
          ON waitlist (created_at DESC);
        """
    )
