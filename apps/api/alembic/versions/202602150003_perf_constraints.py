"""extra constraints and perf indexes

Revision ID: 202602150003
Revises: 202602150002
Create Date: 2026-02-15
"""

from alembic import op

revision = "202602150003"
down_revision = "202602150002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        alter table training_jobs add column if not exists summary_json jsonb not null default '{}'::jsonb;

        create index if not exists idx_training_jobs_status on training_jobs(status);
        create index if not exists idx_training_jobs_created_at on training_jobs(created_at desc);
        create index if not exists idx_training_runs_status on training_runs(status);
        create index if not exists idx_metrics_key_step on metrics(key, step);
        create index if not exists idx_artifacts_name on artifacts(name);
        create index if not exists idx_model_aliases_alias on model_aliases(alias);
        create index if not exists idx_waitlist_created_at on waitlist(created_at desc);
        create index if not exists idx_audit_logs_ts on audit_logs(ts desc);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        drop index if exists idx_audit_logs_ts;
        drop index if exists idx_waitlist_created_at;
        drop index if exists idx_model_aliases_alias;
        drop index if exists idx_artifacts_name;
        drop index if exists idx_metrics_key_step;
        drop index if exists idx_training_runs_status;
        drop index if exists idx_training_jobs_created_at;
        drop index if exists idx_training_jobs_status;

        alter table training_jobs drop column if exists summary_json;
        """
    )
