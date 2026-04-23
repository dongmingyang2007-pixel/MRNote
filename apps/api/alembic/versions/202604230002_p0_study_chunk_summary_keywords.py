"""P0 spec alignment — StudyChunk.summary + StudyChunk.keywords_json

Spec §5.1.7 lists both ``summary`` and ``keywords_json`` on StudyChunk.
Neither column existed in the initial schema, so this migration adds them.
The ORM default the new columns so historical rows stay valid:

* ``summary``       — empty string
* ``keywords_json`` — empty JSON array

Both columns are added nullable for Postgres + SQLite compatibility. The
ORM (see ``entities.StudyChunk``) treats them as required with defaults,
but letting the DB allow NULL avoids a rewrite-table backfill on legacy
rows and keeps SQLite (which cannot retroactively set NOT NULL on an
``ALTER ADD COLUMN``) happy.

Revision ID: 202604230002
Revises: 202604220005
Create Date: 2026-04-23
"""

from __future__ import annotations

from alembic import op


revision = "202604230002"
down_revision = "202604220005"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    try:
        from sqlalchemy import inspect as _inspect
        insp = _inspect(bind)
        return any(c.get("name") == column for c in insp.get_columns(table))
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if not _column_exists("study_chunks", "summary"):
        # TEXT default '' keeps existing rows valid without a rewrite.
        op.execute("ALTER TABLE study_chunks ADD COLUMN summary TEXT DEFAULT ''")

    if not _column_exists("study_chunks", "keywords_json"):
        # JSON default '[]' — Postgres: JSONB; SQLite stores as TEXT JSON.
        if dialect == "postgresql":
            op.execute(
                "ALTER TABLE study_chunks ADD COLUMN keywords_json JSONB DEFAULT '[]'::jsonb"
            )
        else:
            op.execute(
                "ALTER TABLE study_chunks ADD COLUMN keywords_json JSON DEFAULT '[]'"
            )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    # Postgres supports DROP COLUMN cleanly; SQLite pre-3.35 does not, and
    # even on newer SQLite versions Alembic's batch mode is required. We
    # leave the columns in place on SQLite — they default safely.
    if dialect == "postgresql":
        op.execute("ALTER TABLE study_chunks DROP COLUMN IF EXISTS keywords_json")
        op.execute("ALTER TABLE study_chunks DROP COLUMN IF EXISTS summary")
