"""study system – study assets and chunks for P2 Study System

Revision ID: 202604150001
Revises: 202604120001
Create Date: 2026-04-15
"""

from alembic import op

revision = "202604150001"
down_revision = "202604120001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        -- ---------------------------------------------------------------
        -- Study Assets
        -- ---------------------------------------------------------------
        CREATE TABLE IF NOT EXISTS study_assets (
            id          VARCHAR(36) PRIMARY KEY,
            notebook_id VARCHAR(36) NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
            data_item_id VARCHAR(36) REFERENCES data_items(id) ON DELETE SET NULL,
            title       TEXT NOT NULL DEFAULT '',
            asset_type  VARCHAR(20) NOT NULL DEFAULT 'pdf',
            status      VARCHAR(20) NOT NULL DEFAULT 'pending',
            total_chunks INTEGER NOT NULL DEFAULT 0,
            metadata_json JSONB,
            created_by  VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE INDEX IF NOT EXISTS idx_study_assets_notebook
            ON study_assets(notebook_id);
        CREATE INDEX IF NOT EXISTS idx_study_assets_status
            ON study_assets(status);

        -- ---------------------------------------------------------------
        -- Study Chunks
        -- ---------------------------------------------------------------
        CREATE TABLE IF NOT EXISTS study_chunks (
            id          VARCHAR(36) PRIMARY KEY,
            asset_id    VARCHAR(36) NOT NULL REFERENCES study_assets(id) ON DELETE CASCADE,
            chunk_index INTEGER NOT NULL DEFAULT 0,
            heading     TEXT NOT NULL DEFAULT '',
            content     TEXT NOT NULL DEFAULT '',
            page_number INTEGER,
            embedding_id VARCHAR(36),
            metadata_json JSONB,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE INDEX IF NOT EXISTS idx_study_chunks_asset
            ON study_chunks(asset_id, chunk_index);
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS study_chunks CASCADE;
        DROP TABLE IF EXISTS study_assets CASCADE;
    """)
