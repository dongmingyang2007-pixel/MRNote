"""User.onboarding_completed_at column

Revision ID: 202604230001
Revises: 202604220002
Create Date: 2026-04-23
"""

from alembic import op


revision = "202604230001"
down_revision = "202604220002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE users
            ADD COLUMN IF NOT EXISTS onboarding_completed_at TIMESTAMPTZ;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE users
            DROP COLUMN IF EXISTS onboarding_completed_at;
        """
    )
