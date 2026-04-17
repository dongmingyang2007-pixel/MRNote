"""S7 Search — NotebookPage.embedding_id + trgm index on notebook_blocks.plain_text

Revision ID: 202604210001
Revises: 202604200001
Create Date: 2026-04-21
"""

from alembic import op


revision = "202604210001"
down_revision = "202604200001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE notebook_pages
            ADD COLUMN IF NOT EXISTS embedding_id VARCHAR(36);

        CREATE INDEX IF NOT EXISTS ix_notebook_pages_embedding_id
            ON notebook_pages (embedding_id);

        CREATE INDEX IF NOT EXISTS ix_notebook_blocks_plain_text_trgm
            ON notebook_blocks USING GIN (plain_text gin_trgm_ops);
    """)


def downgrade() -> None:
    op.execute("""
        DROP INDEX IF EXISTS ix_notebook_blocks_plain_text_trgm;
        DROP INDEX IF EXISTS ix_notebook_pages_embedding_id;
        ALTER TABLE notebook_pages DROP COLUMN IF EXISTS embedding_id;
    """)
