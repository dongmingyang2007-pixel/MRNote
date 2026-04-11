"""add soft delete columns

Revision ID: 202602150002
Revises: 202602150001
Create Date: 2026-02-15
"""

from alembic import op

revision = "202602150002"
down_revision = "202602150001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        alter table projects add column if not exists deleted_at timestamptz;
        alter table projects add column if not exists cleanup_status text default 'none';

        alter table datasets add column if not exists deleted_at timestamptz;
        alter table datasets add column if not exists cleanup_status text default 'none';

        alter table data_items add column if not exists deleted_at timestamptz;
        alter table models add column if not exists deleted_at timestamptz;
        alter table model_versions add column if not exists deleted_at timestamptz;

        create index if not exists idx_projects_deleted_at on projects(deleted_at);
        create index if not exists idx_datasets_deleted_at on datasets(deleted_at);
        create index if not exists idx_data_items_deleted_at on data_items(deleted_at);
        create index if not exists idx_models_deleted_at on models(deleted_at);
        create index if not exists idx_model_versions_deleted_at on model_versions(deleted_at);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        drop index if exists idx_model_versions_deleted_at;
        drop index if exists idx_models_deleted_at;
        drop index if exists idx_data_items_deleted_at;
        drop index if exists idx_datasets_deleted_at;
        drop index if exists idx_projects_deleted_at;

        alter table model_versions drop column if exists deleted_at;
        alter table models drop column if exists deleted_at;
        alter table data_items drop column if exists deleted_at;

        alter table datasets drop column if exists cleanup_status;
        alter table datasets drop column if exists deleted_at;

        alter table projects drop column if exists cleanup_status;
        alter table projects drop column if exists deleted_at;
        """
    )
