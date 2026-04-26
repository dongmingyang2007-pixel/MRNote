"""Add study_assets.tags JSON column for per-asset tag filtering.

Lets the notebook study list be filtered by tag and lets the new
``PATCH /study-assets/{id}/tags`` endpoint persist user-supplied tags.

* ``study_assets.tags`` JSON NOT NULL DEFAULT '[]' — empty array for legacy
  rows so the ORM mapping (Mapped[list[str]]) stays valid without a backfill.

Postgres stores JSONB; SQLite stores TEXT JSON. ``server_default='[]'``
keeps existing rows valid on both.

Revision ID: 202604250002
Revises: 202604250001
Create Date: 2026-04-25
"""

from __future__ import annotations

from alembic import op


revision = "202604250002"
down_revision = "202604250001"
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

    if not _column_exists("study_assets", "tags"):
        if dialect == "postgresql":
            op.execute(
                "ALTER TABLE study_assets ADD COLUMN tags JSONB NOT NULL DEFAULT '[]'::jsonb"
            )
        else:
            # SQLite: JSON stored as TEXT; NOT NULL + DEFAULT '[]' keeps old
            # rows happy without a manual backfill.
            op.execute(
                "ALTER TABLE study_assets ADD COLUMN tags JSON NOT NULL DEFAULT '[]'"
            )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    # Postgres supports DROP COLUMN cleanly; SQLite pre-3.35 does not, and
    # batch_alter_table is heavier than warranted for a dev-only rollback.
    if dialect == "postgresql":
        op.execute("ALTER TABLE study_assets DROP COLUMN IF EXISTS tags")
