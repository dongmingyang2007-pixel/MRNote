"""drop duplicate ORM-created indexes

Revision ID: 202603120001
Revises: 202602150003
Create Date: 2026-03-12
"""

from alembic import op

revision = "202603120001"
down_revision = "202602150003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        create index if not exists idx_data_items_sha on data_items(sha256);

        drop index if exists ix_data_items_dataset_id;
        drop index if exists ix_data_items_sha256;
        drop index if exists ix_annotations_data_item_id;
        drop index if exists ix_dataset_versions_dataset_id;
        drop index if exists ix_training_jobs_project_id;
        drop index if exists ix_training_runs_training_job_id;
        drop index if exists ix_metrics_run_id;
        drop index if exists ix_artifacts_run_id;
        drop index if exists ix_models_project_id;
        drop index if exists ix_model_versions_model_id;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        create index if not exists ix_data_items_dataset_id on data_items(dataset_id);
        create index if not exists ix_data_items_sha256 on data_items(sha256);
        create index if not exists ix_annotations_data_item_id on annotations(data_item_id);
        create index if not exists ix_dataset_versions_dataset_id on dataset_versions(dataset_id);
        create index if not exists ix_training_jobs_project_id on training_jobs(project_id);
        create index if not exists ix_training_runs_training_job_id on training_runs(training_job_id);
        create index if not exists ix_metrics_run_id on metrics(run_id);
        create index if not exists ix_artifacts_run_id on artifacts(run_id);
        create index if not exists ix_models_project_id on models(project_id);
        create index if not exists ix_model_versions_model_id on model_versions(model_id);
        """
    )
