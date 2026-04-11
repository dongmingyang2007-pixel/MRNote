"""Add layered memory v2 schema

Revision ID: 202604100001
Revises: 202604010001
Create Date: 2026-04-10
"""

from alembic import op

revision = "202604100001"
down_revision = "202604010001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE EXTENSION IF NOT EXISTS pg_trgm;

        ALTER TABLE memories
        ADD COLUMN IF NOT EXISTS confidence DOUBLE PRECISION NOT NULL DEFAULT 0.7;
        ALTER TABLE memories
        ADD COLUMN IF NOT EXISTS observed_at TIMESTAMPTZ;
        ALTER TABLE memories
        ADD COLUMN IF NOT EXISTS valid_from TIMESTAMPTZ;
        ALTER TABLE memories
        ADD COLUMN IF NOT EXISTS valid_to TIMESTAMPTZ;
        ALTER TABLE memories
        ADD COLUMN IF NOT EXISTS last_confirmed_at TIMESTAMPTZ;

        UPDATE memories
        SET observed_at = COALESCE(observed_at, created_at),
            valid_from = COALESCE(valid_from, created_at),
            last_confirmed_at = COALESCE(last_confirmed_at, updated_at, created_at)
        WHERE COALESCE(node_type, 'fact') = 'fact';

        ALTER TABLE memory_edges
        ADD COLUMN IF NOT EXISTS confidence DOUBLE PRECISION NOT NULL DEFAULT 0.5;
        ALTER TABLE memory_edges
        ADD COLUMN IF NOT EXISTS observed_at TIMESTAMPTZ;
        ALTER TABLE memory_edges
        ADD COLUMN IF NOT EXISTS valid_from TIMESTAMPTZ;
        ALTER TABLE memory_edges
        ADD COLUMN IF NOT EXISTS valid_to TIMESTAMPTZ;
        ALTER TABLE memory_edges
        ADD COLUMN IF NOT EXISTS metadata_json JSON NOT NULL DEFAULT '{}'::json;

        CREATE TABLE IF NOT EXISTS memory_evidences (
          id VARCHAR(36) PRIMARY KEY,
          workspace_id VARCHAR(36) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
          project_id VARCHAR(36) NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          memory_id VARCHAR(36) NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
          source_type VARCHAR(20) NOT NULL,
          conversation_id VARCHAR(36) REFERENCES conversations(id) ON DELETE SET NULL,
          message_id VARCHAR(36) REFERENCES messages(id) ON DELETE SET NULL,
          message_role VARCHAR(20),
          data_item_id VARCHAR(36) REFERENCES data_items(id) ON DELETE SET NULL,
          quote_text TEXT NOT NULL,
          start_offset INTEGER,
          end_offset INTEGER,
          chunk_id VARCHAR(64),
          confidence DOUBLE PRECISION NOT NULL DEFAULT 0.7,
          metadata_json JSON NOT NULL DEFAULT '{}'::json,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS memory_write_runs (
          id VARCHAR(36) PRIMARY KEY,
          workspace_id VARCHAR(36) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
          project_id VARCHAR(36) NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          conversation_id VARCHAR(36) REFERENCES conversations(id) ON DELETE SET NULL,
          message_id VARCHAR(36) REFERENCES messages(id) ON DELETE SET NULL,
          status VARCHAR(20) NOT NULL DEFAULT 'pending',
          extraction_model VARCHAR(100),
          consolidation_model VARCHAR(100),
          error TEXT,
          started_at TIMESTAMPTZ,
          completed_at TIMESTAMPTZ,
          metadata_json JSON NOT NULL DEFAULT '{}'::json,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS memory_write_items (
          id VARCHAR(36) PRIMARY KEY,
          run_id VARCHAR(36) NOT NULL REFERENCES memory_write_runs(id) ON DELETE CASCADE,
          subject_memory_id VARCHAR(36) REFERENCES memories(id) ON DELETE SET NULL,
          candidate_text TEXT NOT NULL,
          category VARCHAR(255) NOT NULL DEFAULT '',
          proposed_memory_kind VARCHAR(40),
          importance DOUBLE PRECISION NOT NULL DEFAULT 0.0,
          decision VARCHAR(20) NOT NULL DEFAULT 'create',
          target_memory_id VARCHAR(36) REFERENCES memories(id) ON DELETE SET NULL,
          predecessor_memory_id VARCHAR(36) REFERENCES memories(id) ON DELETE SET NULL,
          reason TEXT,
          metadata_json JSON NOT NULL DEFAULT '{}'::json,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE INDEX IF NOT EXISTS idx_memories_project_validity
          ON memories (project_id, valid_from, valid_to);
        CREATE INDEX IF NOT EXISTS idx_memory_evidences_memory
          ON memory_evidences (memory_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_memory_evidences_project_source
          ON memory_evidences (project_id, source_type);
        CREATE INDEX IF NOT EXISTS idx_memory_write_runs_message
          ON memory_write_runs (message_id);
        CREATE INDEX IF NOT EXISTS idx_memory_write_runs_project_status
          ON memory_write_runs (project_id, status);
        CREATE INDEX IF NOT EXISTS idx_memory_write_items_run
          ON memory_write_items (run_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_memory_write_items_target
          ON memory_write_items (target_memory_id);

        CREATE INDEX IF NOT EXISTS idx_memories_content_trgm
          ON memories USING gin (content gin_trgm_ops);
        CREATE INDEX IF NOT EXISTS idx_memories_category_trgm
          ON memories USING gin (category gin_trgm_ops);
        CREATE INDEX IF NOT EXISTS idx_memory_evidences_quote_trgm
          ON memory_evidences USING gin (quote_text gin_trgm_ops);
        CREATE INDEX IF NOT EXISTS idx_memory_views_content_trgm
          ON memory_views USING gin (content gin_trgm_ops);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS idx_memory_views_content_trgm;
        DROP INDEX IF EXISTS idx_memory_evidences_quote_trgm;
        DROP INDEX IF EXISTS idx_memories_category_trgm;
        DROP INDEX IF EXISTS idx_memories_content_trgm;
        DROP INDEX IF EXISTS idx_memory_write_items_target;
        DROP INDEX IF EXISTS idx_memory_write_items_run;
        DROP INDEX IF EXISTS idx_memory_write_runs_project_status;
        DROP INDEX IF EXISTS idx_memory_write_runs_message;
        DROP INDEX IF EXISTS idx_memory_evidences_project_source;
        DROP INDEX IF EXISTS idx_memory_evidences_memory;
        DROP INDEX IF EXISTS idx_memories_project_validity;

        DROP TABLE IF EXISTS memory_write_items;
        DROP TABLE IF EXISTS memory_write_runs;
        DROP TABLE IF EXISTS memory_evidences;

        ALTER TABLE memory_edges DROP COLUMN IF EXISTS metadata_json;
        ALTER TABLE memory_edges DROP COLUMN IF EXISTS valid_to;
        ALTER TABLE memory_edges DROP COLUMN IF EXISTS valid_from;
        ALTER TABLE memory_edges DROP COLUMN IF EXISTS observed_at;
        ALTER TABLE memory_edges DROP COLUMN IF EXISTS confidence;

        ALTER TABLE memories DROP COLUMN IF EXISTS last_confirmed_at;
        ALTER TABLE memories DROP COLUMN IF EXISTS valid_to;
        ALTER TABLE memories DROP COLUMN IF EXISTS valid_from;
        ALTER TABLE memories DROP COLUMN IF EXISTS observed_at;
        ALTER TABLE memories DROP COLUMN IF EXISTS confidence;
        """
    )
