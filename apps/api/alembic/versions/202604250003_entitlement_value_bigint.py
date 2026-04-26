"""Promote entitlements.value_int from INTEGER to BIGINT.

Until now `value_int` was a 4-byte signed integer (max ~2.1 GB), which
worked fine for counts of pages/notebooks/AI actions but blew up the
moment we added a `storage.bytes.max` entitlement that can hit hundreds
of GB to terabytes. BIGINT (8 bytes, ~9 EB ceiling) gives plenty of
headroom for any practical quota value.

Revision ID: 202604250003
Revises: 202604250002
Create Date: 2026-04-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "202604250003"
down_revision = "202604250002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        # SQLite stores INTEGER as 1-8 bytes dynamically, so the column
        # already accepts BIGINT-sized values without a schema change.
        return
    op.alter_column(
        "entitlements",
        "value_int",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=True,
        postgresql_using="value_int::bigint",
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return
    op.alter_column(
        "entitlements",
        "value_int",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=True,
        postgresql_using="value_int::integer",
    )
