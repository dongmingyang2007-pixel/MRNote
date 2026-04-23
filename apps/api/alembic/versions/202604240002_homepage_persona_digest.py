"""Homepage persona + digest_daily/digest_weekly tables.

Spec: ``升级说明-Persona与Digest.md`` §1.7, §2.4. Adds the account-level
``users.persona`` selector plus the two per-user digest payload tables
the homepage consumes via ``/api/v1/digest/*``.

Design notes
------------
* ``users.persona`` is nullable — every existing row stays valid without
  a backfill. The CHECK constraint only runs on Postgres; SQLite's
  constraint checker is lenient enough that we'd just be stacking dead
  code, and the Pydantic MePatch model is the real enforcement point
  on the write path.
* The digest tables deliberately duplicate the ``(user_id, period)``
  key as a UNIQUE constraint so the daily / weekly Celery jobs can
  do an idempotent upsert keyed on ``(user_id, date)`` /
  ``(user_id, iso_week)``.
* ``saved_page_id`` is a nullable FK into ``notebook_pages`` with
  ``ON DELETE SET NULL`` — a user deleting a saved page should not
  orphan the digest row.

Revision ID: 202604240002
Revises: 202604230002
Create Date: 2026-04-24
"""

from __future__ import annotations

from alembic import op


revision = "202604240002"
down_revision = "202604230002"
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


def _table_exists(table: str) -> bool:
    bind = op.get_bind()
    try:
        from sqlalchemy import inspect as _inspect
        insp = _inspect(bind)
        return table in insp.get_table_names()
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    # ------------------------------------------------------------------
    # 1) users.persona column
    # ------------------------------------------------------------------
    if not _column_exists("users", "persona"):
        if dialect == "postgresql":
            op.execute("ALTER TABLE users ADD COLUMN persona VARCHAR(20)")
            # CHECK is Postgres-only. SQLite would silently ignore inserts
            # that violate it, so skipping there is actually more honest.
            op.execute(
                "ALTER TABLE users ADD CONSTRAINT ck_users_persona "
                "CHECK (persona IS NULL OR persona IN ('student','researcher','pm'))"
            )
            op.execute(
                "CREATE INDEX IF NOT EXISTS ix_users_persona ON users(persona) "
                "WHERE persona IS NOT NULL"
            )
        else:
            op.execute("ALTER TABLE users ADD COLUMN persona VARCHAR(20)")

    # ------------------------------------------------------------------
    # 2) digest_daily table
    # ------------------------------------------------------------------
    if not _table_exists("digest_daily"):
        if dialect == "postgresql":
            op.execute(
                """
                CREATE TABLE digest_daily (
                    id          VARCHAR(36) PRIMARY KEY,
                    user_id     VARCHAR(36) NOT NULL
                                REFERENCES users(id) ON DELETE CASCADE,
                    date        DATE NOT NULL,
                    payload     JSONB NOT NULL DEFAULT '{}'::jsonb,
                    read_at     TIMESTAMPTZ,
                    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
                    CONSTRAINT uq_digest_daily_user_date UNIQUE (user_id, date)
                )
                """
            )
            op.execute(
                "CREATE INDEX ix_digest_daily_user_id ON digest_daily(user_id)"
            )
            op.execute(
                "CREATE INDEX ix_digest_daily_user_date "
                "ON digest_daily(user_id, date DESC)"
            )
        else:
            # SQLite — NOW()/DEFAULT helpers differ and timestamptz maps to
            # TEXT under-the-hood, so emit a Portable create_table via op.
            op.execute(
                """
                CREATE TABLE digest_daily (
                    id          VARCHAR(36) PRIMARY KEY,
                    user_id     VARCHAR(36) NOT NULL
                                REFERENCES users(id) ON DELETE CASCADE,
                    date        DATE NOT NULL,
                    payload     JSON NOT NULL DEFAULT '{}',
                    read_at     TIMESTAMP,
                    created_at  TIMESTAMP NOT NULL,
                    updated_at  TIMESTAMP NOT NULL,
                    CONSTRAINT uq_digest_daily_user_date UNIQUE (user_id, date)
                )
                """
            )
            op.execute(
                "CREATE INDEX ix_digest_daily_user_id ON digest_daily(user_id)"
            )
            op.execute(
                "CREATE INDEX ix_digest_daily_user_date "
                "ON digest_daily(user_id, date DESC)"
            )

    # ------------------------------------------------------------------
    # 3) digest_weekly table
    # ------------------------------------------------------------------
    if not _table_exists("digest_weekly"):
        if dialect == "postgresql":
            op.execute(
                """
                CREATE TABLE digest_weekly (
                    id              VARCHAR(36) PRIMARY KEY,
                    user_id         VARCHAR(36) NOT NULL
                                    REFERENCES users(id) ON DELETE CASCADE,
                    iso_week        VARCHAR(12) NOT NULL,
                    payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
                    saved_page_id   VARCHAR(36)
                                    REFERENCES notebook_pages(id) ON DELETE SET NULL,
                    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
                    CONSTRAINT uq_digest_weekly_user_iso_week UNIQUE (user_id, iso_week)
                )
                """
            )
            op.execute(
                "CREATE INDEX ix_digest_weekly_user_id ON digest_weekly(user_id)"
            )
            op.execute(
                "CREATE INDEX ix_digest_weekly_user_iso_week "
                "ON digest_weekly(user_id, iso_week DESC)"
            )
        else:
            op.execute(
                """
                CREATE TABLE digest_weekly (
                    id              VARCHAR(36) PRIMARY KEY,
                    user_id         VARCHAR(36) NOT NULL
                                    REFERENCES users(id) ON DELETE CASCADE,
                    iso_week        VARCHAR(12) NOT NULL,
                    payload         JSON NOT NULL DEFAULT '{}',
                    saved_page_id   VARCHAR(36)
                                    REFERENCES notebook_pages(id) ON DELETE SET NULL,
                    created_at      TIMESTAMP NOT NULL,
                    updated_at      TIMESTAMP NOT NULL,
                    CONSTRAINT uq_digest_weekly_user_iso_week UNIQUE (user_id, iso_week)
                )
                """
            )
            op.execute(
                "CREATE INDEX ix_digest_weekly_user_id ON digest_weekly(user_id)"
            )
            op.execute(
                "CREATE INDEX ix_digest_weekly_user_iso_week "
                "ON digest_weekly(user_id, iso_week DESC)"
            )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    # Drop tables first (they reference users.id via FK).
    op.execute("DROP TABLE IF EXISTS digest_weekly")
    op.execute("DROP TABLE IF EXISTS digest_daily")

    if dialect == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_users_persona")
        op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_persona")
        op.execute("ALTER TABLE users DROP COLUMN IF EXISTS persona")
    # SQLite: leaving the persona column in place is harmless (default NULL);
    # pre-3.35 SQLite can't DROP COLUMN, and even newer versions require
    # batch_alter_table which is heavier than it's worth for a dev-only rollback.
