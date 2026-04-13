"""notebook system – notebooks, pages, blocks, versions, attachments

Revision ID: 202604120001
Revises: 202604110002
Create Date: 2026-04-12
"""

from alembic import op

revision = "202604120001"
down_revision = "202604110002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        -- ---------------------------------------------------------------
        -- Notebooks
        -- ---------------------------------------------------------------
        create table if not exists notebooks (
          id           varchar(36) primary key,
          workspace_id varchar(36) not null references workspaces(id) on delete cascade,
          project_id   varchar(36) references projects(id) on delete set null,
          created_by   varchar(36) not null references users(id) on delete cascade,
          title        text not null default '',
          slug         varchar(255) not null default '',
          description  text not null default '',
          icon         varchar(100),
          cover_image_url text,
          notebook_type varchar(20) not null default 'personal',
          visibility    varchar(20) not null default 'private',
          archived_at   timestamptz,
          created_at    timestamptz not null default now(),
          updated_at    timestamptz not null default now()
        );

        create index if not exists idx_notebooks_workspace
          on notebooks(workspace_id);
        create index if not exists idx_notebooks_project
          on notebooks(project_id) where project_id is not null;

        -- ---------------------------------------------------------------
        -- Notebook Pages
        -- ---------------------------------------------------------------
        create table if not exists notebook_pages (
          id             varchar(36) primary key,
          notebook_id    varchar(36) not null references notebooks(id) on delete cascade,
          parent_page_id varchar(36) references notebook_pages(id) on delete set null,
          created_by     varchar(36) not null references users(id) on delete cascade,
          title          text not null default '',
          slug           varchar(255) not null default '',
          page_type      varchar(20) not null default 'document',
          content_json   jsonb not null default '{}'::jsonb,
          plain_text     text not null default '',
          summary_text   text not null default '',
          ai_keywords_json jsonb not null default '[]'::jsonb,
          ai_status_json   jsonb not null default '{}'::jsonb,
          sort_order     integer not null default 0,
          is_pinned      boolean not null default false,
          is_archived    boolean not null default false,
          last_edited_at timestamptz,
          source_conversation_id varchar(36) references conversations(id) on delete set null,
          created_at     timestamptz not null default now(),
          updated_at     timestamptz not null default now()
        );

        create index if not exists idx_notebook_pages_notebook
          on notebook_pages(notebook_id);
        create index if not exists idx_notebook_pages_parent
          on notebook_pages(parent_page_id) where parent_page_id is not null;

        -- ---------------------------------------------------------------
        -- Notebook Blocks  (search / AI index; content lives in page JSON)
        -- ---------------------------------------------------------------
        create table if not exists notebook_blocks (
          id            varchar(36) primary key,
          page_id       varchar(36) not null references notebook_pages(id) on delete cascade,
          block_type    varchar(30) not null,
          sort_order    integer not null default 0,
          content_json  jsonb not null default '{}'::jsonb,
          plain_text    text not null default '',
          created_by    varchar(36) references users(id) on delete set null,
          metadata_json jsonb not null default '{}'::jsonb,
          created_at    timestamptz not null default now(),
          updated_at    timestamptz not null default now()
        );

        create index if not exists idx_notebook_blocks_page
          on notebook_blocks(page_id);

        -- ---------------------------------------------------------------
        -- Notebook Page Versions  (snapshots for undo / learning)
        -- ---------------------------------------------------------------
        create table if not exists notebook_page_versions (
          id            varchar(36) primary key,
          page_id       varchar(36) not null references notebook_pages(id) on delete cascade,
          version_no    integer not null,
          snapshot_json jsonb not null default '{}'::jsonb,
          snapshot_text text not null default '',
          source        varchar(20) not null default 'autosave',
          created_by    varchar(36) references users(id) on delete set null,
          created_at    timestamptz not null default now()
        );

        create index if not exists idx_notebook_page_versions_page
          on notebook_page_versions(page_id);
        create unique index if not exists uq_page_versions_page_version
          on notebook_page_versions(page_id, version_no);

        -- ---------------------------------------------------------------
        -- Notebook Attachments  (reuses data_items via FK)
        -- ---------------------------------------------------------------
        create table if not exists notebook_attachments (
          id              varchar(36) primary key,
          page_id         varchar(36) not null references notebook_pages(id) on delete cascade,
          data_item_id    varchar(36) references data_items(id) on delete set null,
          attachment_type varchar(20) not null default 'other',
          title           text not null default '',
          created_at      timestamptz not null default now()
        );

        create index if not exists idx_notebook_attachments_page
          on notebook_attachments(page_id);

        -- ---------------------------------------------------------------
        -- Full-text search on pages (trigram)
        -- ---------------------------------------------------------------
        create index if not exists idx_notebook_pages_plain_text_trgm
          on notebook_pages using gin (plain_text gin_trgm_ops);
    """)


def downgrade() -> None:
    op.execute("""
        drop table if exists notebook_attachments cascade;
        drop table if exists notebook_page_versions cascade;
        drop table if exists notebook_blocks cascade;
        drop table if exists notebook_pages cascade;
        drop table if exists notebooks cascade;
    """)
