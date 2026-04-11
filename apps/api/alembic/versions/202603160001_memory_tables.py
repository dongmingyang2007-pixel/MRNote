"""memory system tables (conversations, messages, memories, memory_edges, embeddings, memory_files)

Revision ID: 202603160001
Revises: 202603120001
Create Date: 2026-03-16
"""

from alembic import op

revision = "202603160001"
down_revision = "202603120001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        create extension if not exists vector;

        create table if not exists conversations (
          id varchar(36) primary key,
          workspace_id uuid not null references workspaces(id) on delete cascade,
          project_id uuid not null references projects(id) on delete cascade,
          title varchar(255) not null default '',
          created_by uuid references users(id) on delete set null,
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now()
        );
        create index if not exists idx_conversations_ws_project
          on conversations(workspace_id, project_id);

        create table if not exists messages (
          id varchar(36) primary key,
          conversation_id varchar(36) not null references conversations(id) on delete cascade,
          role varchar(20) not null,
          content text not null,
          created_at timestamptz not null default now()
        );
        create index if not exists idx_messages_conv_created
          on messages(conversation_id, created_at);

        create table if not exists memories (
          id varchar(36) primary key,
          workspace_id uuid not null references workspaces(id) on delete cascade,
          project_id uuid not null references projects(id) on delete cascade,
          content text not null,
          category varchar(255) not null default '',
          type varchar(20) not null default 'permanent',
          source_conversation_id varchar(36) references conversations(id) on delete set null,
          parent_memory_id varchar(36) references memories(id) on delete set null,
          position_x double precision,
          position_y double precision,
          metadata_json jsonb not null default '{}'::jsonb,
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now()
        );
        create index if not exists idx_memories_ws_project
          on memories(workspace_id, project_id);
        create index if not exists idx_memories_project_type
          on memories(project_id, type);
        create index if not exists idx_memories_source_conv
          on memories(source_conversation_id);

        create table if not exists memory_edges (
          id varchar(36) primary key,
          source_memory_id varchar(36) not null references memories(id) on delete cascade,
          target_memory_id varchar(36) not null references memories(id) on delete cascade,
          edge_type varchar(20) not null default 'auto',
          strength double precision not null default 0.5,
          created_at timestamptz not null default now(),
          unique (source_memory_id, target_memory_id)
        );

        create table if not exists embeddings (
          id varchar(36) primary key,
          workspace_id uuid not null references workspaces(id) on delete cascade,
          project_id uuid not null references projects(id) on delete cascade,
          memory_id varchar(36) references memories(id) on delete cascade,
          data_item_id uuid references data_items(id) on delete cascade,
          chunk_text text not null,
          vector vector(1024),
          created_at timestamptz not null default now(),
          check (memory_id is not null or data_item_id is not null)
        );
        create index if not exists idx_embeddings_ws_project
          on embeddings(workspace_id, project_id);

        create table if not exists memory_files (
          id varchar(36) primary key,
          memory_id varchar(36) not null references memories(id) on delete cascade,
          data_item_id uuid not null references data_items(id) on delete cascade,
          created_at timestamptz not null default now()
        );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        drop table if exists memory_files;
        drop table if exists embeddings;
        drop table if exists memory_edges;
        drop table if exists memories;
        drop table if exists messages;
        drop table if exists conversations;
        drop extension if exists vector;
        """
    )
