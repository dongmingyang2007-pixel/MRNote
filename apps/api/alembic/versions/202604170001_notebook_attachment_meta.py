"""notebook attachment meta_json column (S2)

Revision ID: 202604170001
Revises: 202604160001
Create Date: 2026-04-17
"""

from alembic import op


revision = "202604170001"
down_revision = "202604160001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE notebook_attachments
          ADD COLUMN IF NOT EXISTS meta_json JSONB NOT NULL DEFAULT '{}'::jsonb;
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE notebook_attachments DROP COLUMN IF EXISTS meta_json;")
