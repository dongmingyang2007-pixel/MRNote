"""Add metadata_json to messages

Revision ID: 202603220001
Revises: 202603200001
"""

from alembic import op

revision = "202603220001"
down_revision = "202603200001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE messages
        ADD COLUMN IF NOT EXISTS metadata_json JSON NOT NULL DEFAULT '{}'
        """
    )


def downgrade() -> None:
    # SQLite does not support dropping columns in-place; keep the column on downgrade.
    pass
