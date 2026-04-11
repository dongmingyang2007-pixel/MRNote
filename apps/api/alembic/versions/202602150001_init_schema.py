"""init schema from QIHANG spec

Revision ID: 202602150001
Revises: 
Create Date: 2026-02-15
"""

from alembic import op

revision = "202602150001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        create extension if not exists "uuid-ossp";

        create table if not exists users (
          id uuid primary key default uuid_generate_v4(),
          email text not null unique,
          password_hash text not null,
          display_name text,
          created_at timestamptz not null default now()
        );

        create table if not exists workspaces (
          id uuid primary key default uuid_generate_v4(),
          name text not null,
          plan text not null default 'free',
          created_at timestamptz not null default now()
        );

        create table if not exists memberships (
          workspace_id uuid not null references workspaces(id) on delete cascade,
          user_id uuid not null references users(id) on delete cascade,
          role text not null default 'owner',
          created_at timestamptz not null default now(),
          primary key (workspace_id, user_id)
        );

        create table if not exists projects (
          id uuid primary key default uuid_generate_v4(),
          workspace_id uuid not null references workspaces(id) on delete cascade,
          name text not null,
          description text,
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now()
        );
        create index if not exists idx_projects_workspace on projects(workspace_id);

        create table if not exists datasets (
          id uuid primary key default uuid_generate_v4(),
          project_id uuid not null references projects(id) on delete cascade,
          name text not null,
          type text not null default 'images',
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now()
        );
        create index if not exists idx_datasets_project on datasets(project_id);

        create table if not exists data_items (
          id uuid primary key default uuid_generate_v4(),
          dataset_id uuid not null references datasets(id) on delete cascade,
          object_key text not null,
          filename text not null,
          media_type text not null,
          size_bytes bigint not null default 0,
          sha256 text,
          width int,
          height int,
          duration_ms int,
          meta_json jsonb not null default '{}'::jsonb,
          created_at timestamptz not null default now()
        );
        create index if not exists idx_data_items_dataset on data_items(dataset_id);
        create index if not exists idx_data_items_sha on data_items(sha256);

        create table if not exists annotations (
          id uuid primary key default uuid_generate_v4(),
          data_item_id uuid not null references data_items(id) on delete cascade,
          type text not null,
          payload_json jsonb not null,
          created_by uuid references users(id) on delete set null,
          created_at timestamptz not null default now()
        );
        create index if not exists idx_annotations_item on annotations(data_item_id);

        create table if not exists dataset_versions (
          id uuid primary key default uuid_generate_v4(),
          dataset_id uuid not null references datasets(id) on delete cascade,
          version int not null,
          commit_message text,
          item_count int not null default 0,
          frozen_item_ids uuid[] not null default '{}'::uuid[],
          created_by uuid references users(id) on delete set null,
          created_at timestamptz not null default now(),
          unique (dataset_id, version)
        );
        create index if not exists idx_dsv_dataset on dataset_versions(dataset_id);

        create table if not exists training_jobs (
          id uuid primary key default uuid_generate_v4(),
          project_id uuid not null references projects(id) on delete cascade,
          dataset_version_id uuid not null references dataset_versions(id) on delete restrict,
          recipe text not null,
          status text not null default 'pending',
          params_json jsonb not null default '{}'::jsonb,
          created_by uuid references users(id) on delete set null,
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now()
        );
        create index if not exists idx_jobs_project on training_jobs(project_id);

        create table if not exists training_runs (
          id uuid primary key default uuid_generate_v4(),
          training_job_id uuid not null references training_jobs(id) on delete cascade,
          status text not null default 'running',
          started_at timestamptz,
          finished_at timestamptz,
          logs_object_key text,
          summary_json jsonb not null default '{}'::jsonb,
          created_at timestamptz not null default now()
        );
        create index if not exists idx_runs_job on training_runs(training_job_id);

        create table if not exists metrics (
          id bigserial primary key,
          run_id uuid not null references training_runs(id) on delete cascade,
          key text not null,
          value double precision not null,
          step int not null default 0,
          ts timestamptz not null default now()
        );
        create index if not exists idx_metrics_run on metrics(run_id);

        create table if not exists artifacts (
          id uuid primary key default uuid_generate_v4(),
          run_id uuid not null references training_runs(id) on delete cascade,
          name text not null,
          object_key text not null,
          meta_json jsonb not null default '{}'::jsonb,
          created_at timestamptz not null default now()
        );
        create index if not exists idx_artifacts_run on artifacts(run_id);

        create table if not exists models (
          id uuid primary key default uuid_generate_v4(),
          project_id uuid not null references projects(id) on delete cascade,
          name text not null,
          task_type text not null default 'general',
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now()
        );
        create index if not exists idx_models_project on models(project_id);

        create table if not exists model_versions (
          id uuid primary key default uuid_generate_v4(),
          model_id uuid not null references models(id) on delete cascade,
          version int not null,
          run_id uuid references training_runs(id) on delete set null,
          metrics_json jsonb not null default '{}'::jsonb,
          artifact_object_key text not null,
          notes text,
          created_at timestamptz not null default now(),
          unique (model_id, version)
        );
        create index if not exists idx_model_versions_model on model_versions(model_id);

        create table if not exists model_aliases (
          id uuid primary key default uuid_generate_v4(),
          model_id uuid not null references models(id) on delete cascade,
          alias text not null,
          model_version_id uuid not null references model_versions(id) on delete restrict,
          updated_at timestamptz not null default now(),
          unique (model_id, alias)
        );

        create table if not exists api_keys (
          id uuid primary key default uuid_generate_v4(),
          workspace_id uuid not null references workspaces(id) on delete cascade,
          name text not null,
          key_hash text not null,
          revoked_at timestamptz,
          created_at timestamptz not null default now()
        );

        create table if not exists waitlist (
          id uuid primary key default uuid_generate_v4(),
          email text not null unique,
          source text,
          created_at timestamptz not null default now()
        );

        create table if not exists audit_logs (
          id bigserial primary key,
          workspace_id uuid references workspaces(id) on delete set null,
          actor_user_id uuid references users(id) on delete set null,
          action text not null,
          target_type text not null,
          target_id uuid,
          meta_json jsonb not null default '{}'::jsonb,
          ts timestamptz not null default now()
        );
        create index if not exists idx_audit_workspace on audit_logs(workspace_id);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        drop table if exists audit_logs;
        drop table if exists waitlist;
        drop table if exists api_keys;
        drop table if exists model_aliases;
        drop table if exists model_versions;
        drop table if exists models;
        drop table if exists artifacts;
        drop table if exists metrics;
        drop table if exists training_runs;
        drop table if exists training_jobs;
        drop table if exists dataset_versions;
        drop table if exists annotations;
        drop table if exists data_items;
        drop table if exists datasets;
        drop table if exists projects;
        drop table if exists memberships;
        drop table if exists workspaces;
        drop table if exists users;
        """
    )
