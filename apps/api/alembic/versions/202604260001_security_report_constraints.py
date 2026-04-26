"""Add uniqueness constraints for security report race fixes.

Revision ID: 202604260001
Revises: 202604250003
Create Date: 2026-04-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "202604260001"
down_revision = "202604250003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    op.create_table(
        "quota_counters",
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_count", sa.Integer(), nullable=False),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("used_count >= 0", name="ck_quota_counters_used_nonnegative"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "key",
            "period_start",
            name="uq_quota_counters_workspace_key_period",
        ),
    )
    op.create_index("ix_quota_counters_workspace_id", "quota_counters", ["workspace_id"])

    op.create_table(
        "storage_reservations",
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("dataset_id", sa.String(), nullable=False),
        sa.Column("upload_id", sa.String(length=80), nullable=False),
        sa.Column("data_item_id", sa.String(length=64), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("bytes_reserved", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending','completed','released')",
            name="ck_storage_reservations_status",
        ),
        sa.CheckConstraint(
            "bytes_reserved >= 0",
            name="ck_storage_reservations_bytes_nonnegative",
        ),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("upload_id", name="uq_storage_reservations_upload_id"),
        sa.UniqueConstraint("data_item_id", name="uq_storage_reservations_data_item_id"),
    )
    op.create_index("ix_storage_reservations_workspace_id", "storage_reservations", ["workspace_id"])
    op.create_index("ix_storage_reservations_dataset_id", "storage_reservations", ["dataset_id"])
    op.create_index("ix_storage_reservations_expires_at", "storage_reservations", ["expires_at"])

    if bind.dialect.name == "sqlite":
        return
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_document_versions_item_version'
            ) THEN
                ALTER TABLE document_versions
                ADD CONSTRAINT uq_document_versions_item_version
                UNIQUE (data_item_id, version);
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_study_chunks_asset_chunk_index'
            ) THEN
                ALTER TABLE study_chunks
                ADD CONSTRAINT uq_study_chunks_asset_chunk_index
                UNIQUE (asset_id, chunk_index);
            END IF;
        END $$;

        CREATE UNIQUE INDEX IF NOT EXISTS uq_notebook_selection_memory_link_business_key
        ON notebook_selection_memory_links (
            page_id,
            COALESCE(block_id, ''),
            COALESCE(start_offset, -1),
            COALESCE(end_offset, -1),
            memory_id
        );

        ALTER TABLE subscriptions
            DROP CONSTRAINT IF EXISTS ck_subscriptions_status;
        ALTER TABLE subscriptions
            ADD CONSTRAINT ck_subscriptions_status CHECK (
                status IN (
                    'active',
                    'past_due',
                    'canceled',
                    'trialing',
                    'manual',
                    'incomplete',
                    'incomplete_expired',
                    'unpaid',
                    'paused'
                )
            );
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        op.drop_index("ix_storage_reservations_expires_at", table_name="storage_reservations")
        op.drop_index("ix_storage_reservations_dataset_id", table_name="storage_reservations")
        op.drop_index("ix_storage_reservations_workspace_id", table_name="storage_reservations")
        op.drop_table("storage_reservations")
        op.drop_index("ix_quota_counters_workspace_id", table_name="quota_counters")
        op.drop_table("quota_counters")
        return
    op.execute(
        """
        DROP INDEX IF EXISTS uq_notebook_selection_memory_link_business_key;
        ALTER TABLE study_chunks
            DROP CONSTRAINT IF EXISTS uq_study_chunks_asset_chunk_index;
        ALTER TABLE document_versions
            DROP CONSTRAINT IF EXISTS uq_document_versions_item_version;
        ALTER TABLE subscriptions
            DROP CONSTRAINT IF EXISTS ck_subscriptions_status;
        ALTER TABLE subscriptions
            ADD CONSTRAINT ck_subscriptions_status CHECK (
                status IN (
                    'active',
                    'past_due',
                    'canceled',
                    'trialing',
                    'manual',
                    'incomplete'
                )
            );
        """
    )
    op.drop_index("ix_storage_reservations_expires_at", table_name="storage_reservations")
    op.drop_index("ix_storage_reservations_dataset_id", table_name="storage_reservations")
    op.drop_index("ix_storage_reservations_workspace_id", table_name="storage_reservations")
    op.drop_table("storage_reservations")
    op.drop_index("ix_quota_counters_workspace_id", table_name="quota_counters")
    op.drop_table("quota_counters")
