"""Add default chat mode to projects

Revision ID: 202603200001
Revises: 202603180001
"""

from alembic import op

revision = "202603200001"
down_revision = "202603180001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE projects
        ADD COLUMN IF NOT EXISTS default_chat_mode TEXT NOT NULL DEFAULT 'standard'
        """
    )


def downgrade() -> None:
    # SQLite does not support dropping columns in-place; keep the column on downgrade.
    pass
