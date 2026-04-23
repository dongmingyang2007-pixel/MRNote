"""Wave 2 A5 – notebook_selection_memory_links

Adds the `NotebookSelectionMemoryLink` bridge table (spec §5.1 / §9.5) so the
UI can show "this page span has produced these memories" without scanning
MemoryEvidence. Populated on /api/v1/pages/{id}/memory/confirm after the
UnifiedMemoryPipeline promotes a candidate to a real Memory.

Portable across Postgres and SQLite; relies on IF NOT EXISTS semantics on
Postgres and safe CREATE TABLE IF NOT EXISTS on SQLite.

Revision ID: 202604220004
Revises: 202604220003
Create Date: 2026-04-22
"""

from alembic import op


revision = "202604220004"
down_revision = "202604220003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        op.execute(
            """
            CREATE TABLE IF NOT EXISTS notebook_selection_memory_links (
                id            varchar(36) primary key,
                page_id       varchar(36) not null references notebook_pages(id) on delete cascade,
                block_id      varchar(36) references notebook_blocks(id) on delete set null,
                start_offset  integer,
                end_offset    integer,
                memory_id     varchar(36) not null references memories(id) on delete cascade,
                evidence_id   varchar(36) references memory_evidences(id) on delete set null,
                created_at    timestamptz not null default now()
            );

            CREATE INDEX IF NOT EXISTS idx_nb_sel_mem_link_page_id
              ON notebook_selection_memory_links(page_id);
            CREATE INDEX IF NOT EXISTS idx_nb_sel_mem_link_block_id
              ON notebook_selection_memory_links(block_id)
              WHERE block_id IS NOT NULL;
            CREATE INDEX IF NOT EXISTS idx_nb_sel_mem_link_memory_id
              ON notebook_selection_memory_links(memory_id);
            CREATE INDEX IF NOT EXISTS idx_nb_sel_mem_link_evidence_id
              ON notebook_selection_memory_links(evidence_id)
              WHERE evidence_id IS NOT NULL;
            """
        )
    else:
        # SQLite (tests) — no timestamptz, no partial indexes.
        op.execute(
            """
            CREATE TABLE IF NOT EXISTS notebook_selection_memory_links (
                id            varchar(36) primary key,
                page_id       varchar(36) not null references notebook_pages(id) on delete cascade,
                block_id      varchar(36) references notebook_blocks(id) on delete set null,
                start_offset  integer,
                end_offset    integer,
                memory_id     varchar(36) not null references memories(id) on delete cascade,
                evidence_id   varchar(36) references memory_evidences(id) on delete set null,
                created_at    timestamp not null default CURRENT_TIMESTAMP
            )
            """
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS idx_nb_sel_mem_link_page_id "
            "ON notebook_selection_memory_links(page_id)"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS idx_nb_sel_mem_link_memory_id "
            "ON notebook_selection_memory_links(memory_id)"
        )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "postgresql":
        op.execute("DROP TABLE IF EXISTS notebook_selection_memory_links CASCADE")
    else:
        op.execute("DROP TABLE IF EXISTS notebook_selection_memory_links")
