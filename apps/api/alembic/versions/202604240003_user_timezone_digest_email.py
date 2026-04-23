"""Add users.timezone + users.digest_email_enabled for per-user scheduling.

Spec: DIGEST upgrade — timezone-aware daily digest + opt-out digest email.

* ``users.timezone``            VARCHAR(64) NULL  — IANA zone ("Asia/Shanghai").
  NULL means the scheduler treats the user as UTC until they pick a zone.
* ``users.digest_email_enabled`` BOOLEAN NOT NULL DEFAULT TRUE — opt-out flag
  for SMTP-delivered digest mail. Default TRUE so existing users continue
  receiving mail once SMTP is live; they can flip off via PATCH /auth/me.

SQLite: same columns with JSON default mapping; BOOLEAN is stored as INTEGER.

Revision ID: 202604240003
Revises: 202604240002
Create Date: 2026-04-24
"""

from __future__ import annotations

from alembic import op


revision = "202604240003"
down_revision = "202604240002"
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

    # ------------------------------------------------------------------
    # users.timezone
    # ------------------------------------------------------------------
    if not _column_exists("users", "timezone"):
        op.execute("ALTER TABLE users ADD COLUMN timezone VARCHAR(64)")

    # ------------------------------------------------------------------
    # users.digest_email_enabled
    # ------------------------------------------------------------------
    if not _column_exists("users", "digest_email_enabled"):
        if dialect == "postgresql":
            op.execute(
                "ALTER TABLE users ADD COLUMN digest_email_enabled "
                "BOOLEAN NOT NULL DEFAULT TRUE"
            )
        else:
            # SQLite stores booleans as 0/1 under the hood; NOT NULL + DEFAULT 1
            # keeps old rows opted-in without a manual backfill.
            op.execute(
                "ALTER TABLE users ADD COLUMN digest_email_enabled "
                "BOOLEAN NOT NULL DEFAULT 1"
            )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        op.execute("ALTER TABLE users DROP COLUMN IF EXISTS digest_email_enabled")
        op.execute("ALTER TABLE users DROP COLUMN IF EXISTS timezone")
    # SQLite: leaving the columns in place is harmless; pre-3.35 can't
    # DROP COLUMN and batch_alter_table is heavier than warranted for a
    # dev-only rollback.
