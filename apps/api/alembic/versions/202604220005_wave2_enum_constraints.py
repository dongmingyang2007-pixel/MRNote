"""Wave 2 A8 – enum constraint + StudyAsset field alignment

Spec §5.1 says several columns are meant to be enums:

* ``notebook_pages.page_type`` ∈ {document, canvas, mixed, study}
* ``notebooks.notebook_type`` ∈ {personal, work, study, scratch}
* ``notebooks.visibility`` ∈ {private, workspace}
* ``study_assets.asset_type`` ∈ {book, pdf, article, slides, notes_bundle}
* ``ai_action_logs.scope`` ∈ {selection, page, notebook, project, user_memory, study_asset, web}
* ``memory_evidences.source_type`` ∈ {chat_message, notebook_page, uploaded_document, whiteboard, book_chapter, study_confusion}

The live models use ``String(20)`` / ``String(40)``; this migration adds
named CheckConstraints on Postgres so bad inserts are rejected at the
DB layer. SQLite (tests) is skipped because CHECK enforcement on ALTER
is flaky there and we don't want to block the test DB boot.

It also adds three spec-required columns to ``study_assets``:

* ``language``   — ISO 639 code
* ``author``     — free-form
* ``page_id``    — FK to ``notebook_pages`` (nullable)

These are additive, so SQLite is fine with them too.

Revision ID: 202604220005
Revises: 202604220004
Create Date: 2026-04-22
"""

from __future__ import annotations

from alembic import op


revision = "202604220005"
down_revision = "202604220004"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Spec §5.1 enum contracts.
# ---------------------------------------------------------------------------

_CHECKS: tuple[tuple[str, str, str], ...] = (
    (
        "notebook_pages",
        "ck_notebook_pages_page_type",
        "page_type IN ('document','canvas','mixed','study')",
    ),
    (
        "notebooks",
        "ck_notebooks_notebook_type",
        "notebook_type IN ('personal','work','study','scratch')",
    ),
    (
        "notebooks",
        "ck_notebooks_visibility",
        "visibility IN ('private','workspace')",
    ),
    (
        "study_assets",
        "ck_study_assets_asset_type",
        "asset_type IN ('book','pdf','article','slides','notes_bundle')",
    ),
    (
        "ai_action_logs",
        "ck_ai_action_logs_scope",
        "scope IN ('selection','page','notebook','project','user_memory','study_asset','web')",
    ),
    (
        "memory_evidences",
        "ck_memory_evidences_source_type",
        (
            "source_type IN ("
            "'chat_message','notebook_page','uploaded_document',"
            "'whiteboard','book_chapter','study_confusion')"
        ),
    ),
)


def _is_postgres() -> bool:
    bind = op.get_bind()
    return bind.dialect.name == "postgresql"


def upgrade() -> None:
    # -- StudyAsset field alignment (spec §5.1.6) --------------------------
    # These are additive columns so both Postgres and SQLite can run them.
    bind = op.get_bind()
    dialect = bind.dialect.name

    def _column_exists(table: str, column: str) -> bool:
        # Portable column probe that works on both Postgres and SQLite.
        try:
            from sqlalchemy import inspect as _inspect
            insp = _inspect(bind)
            return any(c.get("name") == column for c in insp.get_columns(table))
        except Exception:
            return False

    if not _column_exists("study_assets", "language"):
        op.execute("ALTER TABLE study_assets ADD COLUMN language varchar(16)")
    if not _column_exists("study_assets", "author"):
        op.execute("ALTER TABLE study_assets ADD COLUMN author varchar(200)")
    if not _column_exists("study_assets", "page_id"):
        op.execute("ALTER TABLE study_assets ADD COLUMN page_id varchar(36)")
        # FK only on Postgres — SQLite ALTER cannot add an FK after the
        # fact, and we don't rely on cascade here (nullable, best-effort).
        if dialect == "postgresql":
            op.execute(
                "ALTER TABLE study_assets "
                "ADD CONSTRAINT fk_study_assets_page_id "
                "FOREIGN KEY (page_id) REFERENCES notebook_pages(id) "
                "ON DELETE SET NULL"
            )

    # -- Check constraints (Postgres only) --------------------------------
    if not _is_postgres():
        return

    for table, name, condition in _CHECKS:
        # IF NOT EXISTS isn't valid inside ADD CONSTRAINT, so we
        # defensively DROP first.
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({condition})"
        )


def downgrade() -> None:
    if _is_postgres():
        for table, name, _condition in _CHECKS:
            op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
        op.execute(
            "ALTER TABLE study_assets DROP CONSTRAINT IF EXISTS fk_study_assets_page_id"
        )

    # Drop the additive columns — safe on both dialects.
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "postgresql":
        op.execute("ALTER TABLE study_assets DROP COLUMN IF EXISTS page_id")
        op.execute("ALTER TABLE study_assets DROP COLUMN IF EXISTS author")
        op.execute("ALTER TABLE study_assets DROP COLUMN IF EXISTS language")
    # SQLite's ALTER DROP COLUMN is pre-3.35; we leave the columns in
    # place on downgrade there — harmless, they default to NULL.
