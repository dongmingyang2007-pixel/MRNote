"""Start memory graph phase 1 upgrade

Revision ID: 202603310001
Revises: 202603290001
Create Date: 2026-03-31
"""

from alembic import op

revision = "202603310001"
down_revision = "202603290001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE conversations
        ADD COLUMN IF NOT EXISTS metadata_json JSON NOT NULL DEFAULT '{}'::json;

        ALTER TABLE memories
        ADD COLUMN IF NOT EXISTS node_type VARCHAR(20) NOT NULL DEFAULT 'fact';

        ALTER TABLE memories
        ADD COLUMN IF NOT EXISTS subject_kind VARCHAR(40);

        ALTER TABLE memories
        ADD COLUMN IF NOT EXISTS subject_memory_id VARCHAR(36);

        ALTER TABLE memories
        ADD COLUMN IF NOT EXISTS node_status VARCHAR(20) NOT NULL DEFAULT 'active';

        ALTER TABLE memories
        ADD COLUMN IF NOT EXISTS canonical_key VARCHAR(255);

        CREATE INDEX IF NOT EXISTS idx_memories_project_node_type
          ON memories (project_id, node_type);

        CREATE INDEX IF NOT EXISTS idx_memories_project_subject
          ON memories (project_id, subject_memory_id);

        CREATE INDEX IF NOT EXISTS idx_memories_project_canonical
          ON memories (project_id, subject_memory_id, canonical_key);

        CREATE TABLE IF NOT EXISTS memory_views (
          id VARCHAR(36) PRIMARY KEY,
          workspace_id VARCHAR(36) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
          project_id VARCHAR(36) NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          source_subject_id VARCHAR(36) REFERENCES memories(id) ON DELETE SET NULL,
          view_type VARCHAR(40) NOT NULL,
          content TEXT NOT NULL,
          metadata_json JSON NOT NULL DEFAULT '{}'::json,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE INDEX IF NOT EXISTS idx_memory_views_project_type
          ON memory_views (project_id, view_type);

        UPDATE memories
        SET node_type = 'root',
            node_status = 'active',
            canonical_key = COALESCE(canonical_key, 'root')
        WHERE COALESCE(metadata_json ->> 'node_kind', '') = 'assistant-root';

        UPDATE memories
        SET node_type = 'concept'
        WHERE COALESCE(metadata_json ->> 'node_kind', '') = 'concept';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS idx_memory_views_project_type;
        DROP TABLE IF EXISTS memory_views;
        DROP INDEX IF EXISTS idx_memories_project_canonical;
        DROP INDEX IF EXISTS idx_memories_project_subject;
        DROP INDEX IF EXISTS idx_memories_project_node_type;
        ALTER TABLE memories DROP COLUMN IF EXISTS canonical_key;
        ALTER TABLE memories DROP COLUMN IF EXISTS node_status;
        ALTER TABLE memories DROP COLUMN IF EXISTS subject_memory_id;
        ALTER TABLE memories DROP COLUMN IF EXISTS subject_kind;
        ALTER TABLE memories DROP COLUMN IF EXISTS node_type;
        ALTER TABLE conversations DROP COLUMN IF EXISTS metadata_json;
        """
    )
