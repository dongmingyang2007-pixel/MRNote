"""Add memory v3 learning loop schema

Revision ID: 202604110001
Revises: 202604100001
Create Date: 2026-04-11
"""

from alembic import op

revision = "202604110001"
down_revision = "202604100001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_episodes (
          id VARCHAR(36) PRIMARY KEY,
          workspace_id VARCHAR(36) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
          project_id VARCHAR(36) NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          conversation_id VARCHAR(36) REFERENCES conversations(id) ON DELETE SET NULL,
          message_id VARCHAR(36) REFERENCES messages(id) ON DELETE SET NULL,
          source_type VARCHAR(40) NOT NULL,
          source_id VARCHAR(64),
          chunk_text TEXT NOT NULL,
          owner_user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
          visibility VARCHAR(20) NOT NULL DEFAULT 'private',
          started_at TIMESTAMPTZ,
          ended_at TIMESTAMPTZ,
          metadata_json JSON NOT NULL DEFAULT '{}'::json,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS memory_outcomes (
          id VARCHAR(36) PRIMARY KEY,
          workspace_id VARCHAR(36) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
          project_id VARCHAR(36) NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          conversation_id VARCHAR(36) REFERENCES conversations(id) ON DELETE SET NULL,
          message_id VARCHAR(36) REFERENCES messages(id) ON DELETE SET NULL,
          task_id VARCHAR(64),
          status VARCHAR(20) NOT NULL,
          feedback_source VARCHAR(20) NOT NULL DEFAULT 'system',
          summary TEXT,
          root_cause TEXT,
          tags JSON NOT NULL DEFAULT '[]'::json,
          metadata_json JSON NOT NULL DEFAULT '{}'::json,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS memory_learning_runs (
          id VARCHAR(36) PRIMARY KEY,
          workspace_id VARCHAR(36) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
          project_id VARCHAR(36) NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          conversation_id VARCHAR(36) REFERENCES conversations(id) ON DELETE SET NULL,
          message_id VARCHAR(36) REFERENCES messages(id) ON DELETE SET NULL,
          task_id VARCHAR(64),
          trigger VARCHAR(40) NOT NULL DEFAULT 'post_turn',
          status VARCHAR(20) NOT NULL DEFAULT 'pending',
          stages JSON NOT NULL DEFAULT '[]'::json,
          used_memory_ids JSON NOT NULL DEFAULT '[]'::json,
          promoted_memory_ids JSON NOT NULL DEFAULT '[]'::json,
          degraded_memory_ids JSON NOT NULL DEFAULT '[]'::json,
          outcome_id VARCHAR(36) REFERENCES memory_outcomes(id) ON DELETE SET NULL,
          error TEXT,
          started_at TIMESTAMPTZ,
          completed_at TIMESTAMPTZ,
          metadata_json JSON NOT NULL DEFAULT '{}'::json,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        ALTER TABLE memory_evidences
        ADD COLUMN IF NOT EXISTS episode_id VARCHAR(36) REFERENCES memory_episodes(id) ON DELETE SET NULL;

        CREATE INDEX IF NOT EXISTS idx_memory_episodes_project_source
          ON memory_episodes (project_id, source_type);
        CREATE INDEX IF NOT EXISTS idx_memory_episodes_message
          ON memory_episodes (message_id);
        CREATE INDEX IF NOT EXISTS idx_memory_outcomes_project_status
          ON memory_outcomes (project_id, status);
        CREATE INDEX IF NOT EXISTS idx_memory_outcomes_message
          ON memory_outcomes (message_id);
        CREATE INDEX IF NOT EXISTS idx_memory_learning_runs_project_status
          ON memory_learning_runs (project_id, status);
        CREATE INDEX IF NOT EXISTS idx_memory_learning_runs_message
          ON memory_learning_runs (message_id);
        CREATE INDEX IF NOT EXISTS idx_memory_evidences_episode
          ON memory_evidences (episode_id);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS idx_memory_evidences_episode;
        DROP INDEX IF EXISTS idx_memory_learning_runs_message;
        DROP INDEX IF EXISTS idx_memory_learning_runs_project_status;
        DROP INDEX IF EXISTS idx_memory_outcomes_message;
        DROP INDEX IF EXISTS idx_memory_outcomes_project_status;
        DROP INDEX IF EXISTS idx_memory_episodes_message;
        DROP INDEX IF EXISTS idx_memory_episodes_project_source;

        ALTER TABLE memory_evidences DROP COLUMN IF EXISTS episode_id;

        DROP TABLE IF EXISTS memory_learning_runs;
        DROP TABLE IF EXISTS memory_outcomes;
        DROP TABLE IF EXISTS memory_episodes;
        """
    )
