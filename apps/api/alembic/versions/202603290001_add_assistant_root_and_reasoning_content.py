"""Add assistant_root_memory_id and reasoning_content columns

Revision ID: 202603290001
Revises: 202603220001
Create Date: 2026-03-29
"""

from alembic import op

revision = "202603290001"
down_revision = "202603220001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE projects
        ADD COLUMN IF NOT EXISTS assistant_root_memory_id VARCHAR(36);

        CREATE INDEX IF NOT EXISTS idx_projects_assistant_root_memory
          ON projects (assistant_root_memory_id);

        ALTER TABLE messages
        ADD COLUMN IF NOT EXISTS reasoning_content TEXT;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS idx_projects_assistant_root_memory;
        ALTER TABLE messages DROP COLUMN IF EXISTS reasoning_content;
        ALTER TABLE projects DROP COLUMN IF EXISTS assistant_root_memory_id;
        """
    )
