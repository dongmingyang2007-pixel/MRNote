"""ai action log – add ai_action_logs and ai_usage_events for S1

Revision ID: 202604160001
Revises: 202604150001
Create Date: 2026-04-16
"""

from alembic import op


revision = "202604160001"
down_revision = "202604150001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS ai_action_logs (
            id              VARCHAR(36) PRIMARY KEY,
            workspace_id    VARCHAR(36) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            user_id         VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            notebook_id     VARCHAR(36) REFERENCES notebooks(id) ON DELETE SET NULL,
            page_id         VARCHAR(36) REFERENCES notebook_pages(id) ON DELETE SET NULL,
            block_id        VARCHAR(64),
            action_type     VARCHAR(60) NOT NULL,
            scope           VARCHAR(20) NOT NULL,
            status          VARCHAR(20) NOT NULL DEFAULT 'running',
            model_id        VARCHAR(100),
            duration_ms     INTEGER,
            input_json      JSONB NOT NULL DEFAULT '{}'::jsonb,
            output_json     JSONB NOT NULL DEFAULT '{}'::jsonb,
            output_summary  TEXT NOT NULL DEFAULT '',
            error_code      VARCHAR(50),
            error_message   TEXT,
            trace_metadata  JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE INDEX IF NOT EXISTS ix_ai_action_logs_workspace_id
            ON ai_action_logs(workspace_id);
        CREATE INDEX IF NOT EXISTS ix_ai_action_logs_notebook_id
            ON ai_action_logs(notebook_id);
        CREATE INDEX IF NOT EXISTS ix_ai_action_logs_page_id
            ON ai_action_logs(page_id);
        CREATE INDEX IF NOT EXISTS ix_ai_action_logs_workspace_created
            ON ai_action_logs(workspace_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS ix_ai_action_logs_page_created
            ON ai_action_logs(page_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS ix_ai_action_logs_user_created
            ON ai_action_logs(user_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS ai_usage_events (
            id                 VARCHAR(36) PRIMARY KEY,
            workspace_id       VARCHAR(36) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            user_id            VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            action_log_id      VARCHAR(36) NOT NULL REFERENCES ai_action_logs(id) ON DELETE CASCADE,
            event_type         VARCHAR(30) NOT NULL,
            model_id           VARCHAR(100),
            prompt_tokens      INTEGER NOT NULL DEFAULT 0,
            completion_tokens  INTEGER NOT NULL DEFAULT 0,
            total_tokens       INTEGER NOT NULL DEFAULT 0,
            audio_seconds      DOUBLE PRECISION NOT NULL DEFAULT 0,
            file_count         INTEGER NOT NULL DEFAULT 0,
            count_source       VARCHAR(10) NOT NULL DEFAULT 'exact',
            meta_json          JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE INDEX IF NOT EXISTS ix_ai_usage_events_workspace_id
            ON ai_usage_events(workspace_id);
        CREATE INDEX IF NOT EXISTS ix_ai_usage_events_action
            ON ai_usage_events(action_log_id);
        CREATE INDEX IF NOT EXISTS ix_ai_usage_events_workspace_created
            ON ai_usage_events(workspace_id, created_at DESC);
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS ai_usage_events CASCADE;
        DROP TABLE IF EXISTS ai_action_logs CASCADE;
    """)
