"""proactive_digests table (S5)

Revision ID: 202604190001
Revises: 202604180001
Create Date: 2026-04-19
"""

from alembic import op


revision = "202604190001"
down_revision = "202604180001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS proactive_digests (
            id                VARCHAR(36) PRIMARY KEY,
            workspace_id      VARCHAR(36) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            project_id        VARCHAR(36) NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            user_id           VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            kind              VARCHAR(32) NOT NULL,
            period_start      TIMESTAMPTZ NOT NULL,
            period_end        TIMESTAMPTZ NOT NULL,
            title             VARCHAR(200) NOT NULL DEFAULT '',
            content_markdown  TEXT NOT NULL DEFAULT '',
            content_json      JSONB NOT NULL DEFAULT '{}'::jsonb,
            status            VARCHAR(20) NOT NULL DEFAULT 'unread',
            read_at           TIMESTAMPTZ,
            dismissed_at      TIMESTAMPTZ,
            model_id          VARCHAR(100),
            action_log_id     VARCHAR(36),
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_proactive_digests_project_kind_period_start
                UNIQUE (project_id, kind, period_start)
        );

        CREATE INDEX IF NOT EXISTS ix_proactive_digests_workspace_id
            ON proactive_digests(workspace_id);
        CREATE INDEX IF NOT EXISTS ix_proactive_digests_project_id
            ON proactive_digests(project_id);
        CREATE INDEX IF NOT EXISTS ix_proactive_digests_user_status_created
            ON proactive_digests(user_id, status, created_at DESC);
        CREATE INDEX IF NOT EXISTS ix_proactive_digests_project_kind_period
            ON proactive_digests(project_id, kind, period_start DESC);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS proactive_digests CASCADE;")
