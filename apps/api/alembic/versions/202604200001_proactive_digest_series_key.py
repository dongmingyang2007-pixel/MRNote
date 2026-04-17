"""proactive_digests.series_key + unique rewrite (S5 follow-up)

Revision ID: 202604200001
Revises: 202604190001
Create Date: 2026-04-20
"""

from alembic import op


revision = "202604200001"
down_revision = "202604190001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE proactive_digests
            ADD COLUMN IF NOT EXISTS series_key VARCHAR(64) NOT NULL DEFAULT '';

        ALTER TABLE proactive_digests
            DROP CONSTRAINT IF EXISTS uq_proactive_digests_project_kind_period_start;

        ALTER TABLE proactive_digests
            ADD CONSTRAINT uq_proactive_digests_project_kind_period_series
                UNIQUE (project_id, kind, period_start, series_key);

        ALTER TABLE proactive_digests
            ADD CONSTRAINT ck_proactive_digests_status
                CHECK (status IN ('unread','read','dismissed'));
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE proactive_digests
            DROP CONSTRAINT IF EXISTS ck_proactive_digests_status;
        ALTER TABLE proactive_digests
            DROP CONSTRAINT IF EXISTS uq_proactive_digests_project_kind_period_series;
        ALTER TABLE proactive_digests
            ADD CONSTRAINT uq_proactive_digests_project_kind_period_start
                UNIQUE (project_id, kind, period_start);
        ALTER TABLE proactive_digests DROP COLUMN IF EXISTS series_key;
    """)
