"""Finalize memory graph versioning and graph-first indexes

Revision ID: 202604010001
Revises: 202603310001
Create Date: 2026-04-01
"""

from alembic import op

revision = "202604010001"
down_revision = "202603310001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE memories
        ADD COLUMN IF NOT EXISTS lineage_key VARCHAR(36);

        UPDATE memories
        SET lineage_key = id
        WHERE COALESCE(node_type, 'fact') = 'fact'
          AND COALESCE(lineage_key, '') = '';

        DELETE FROM memory_edges
        WHERE id IN (
          SELECT id
          FROM (
            SELECT id,
                   ROW_NUMBER() OVER (
                     PARTITION BY source_memory_id, target_memory_id, edge_type
                     ORDER BY created_at, id
                   ) AS row_num
            FROM memory_edges
          ) ranked
          WHERE ranked.row_num > 1
        );

        ALTER TABLE memory_edges
        DROP CONSTRAINT IF EXISTS uq_memory_edges_src_tgt;

        ALTER TABLE memory_edges
        ADD CONSTRAINT uq_memory_edges_src_tgt_type
        UNIQUE (source_memory_id, target_memory_id, edge_type);

        CREATE INDEX IF NOT EXISTS idx_memories_project_subject_status_type
          ON memories (project_id, subject_memory_id, node_status, node_type);

        CREATE INDEX IF NOT EXISTS idx_memories_project_lineage_status
          ON memories (project_id, lineage_key, node_status);

        CREATE INDEX IF NOT EXISTS idx_memories_active_fact_subject
          ON memories (project_id, subject_memory_id)
          WHERE node_type = 'fact' AND node_status = 'active';

        CREATE INDEX IF NOT EXISTS idx_memories_active_fact_lineage
          ON memories (project_id, lineage_key)
          WHERE node_type = 'fact' AND node_status = 'active';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS idx_memories_active_fact_lineage;
        DROP INDEX IF EXISTS idx_memories_active_fact_subject;
        DROP INDEX IF EXISTS idx_memories_project_lineage_status;
        DROP INDEX IF EXISTS idx_memories_project_subject_status_type;

        ALTER TABLE memory_edges
        DROP CONSTRAINT IF EXISTS uq_memory_edges_src_tgt_type;

        ALTER TABLE memory_edges
        ADD CONSTRAINT uq_memory_edges_src_tgt
        UNIQUE (source_memory_id, target_memory_id);

        ALTER TABLE memories DROP COLUMN IF EXISTS lineage_key;
        """
    )
