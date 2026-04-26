"""document_versions table for per-document snapshot history.

Each ONLYOFFICE save (and manual restore-pre snapshot) writes one row
recording the S3 snapshot key + metadata. Restoring is server-side copy
from the snapshot key back into ``data_items.object_key``.

Revision ID: 202604250001
Revises: 202604240003
Create Date: 2026-04-25
"""

from alembic import op


revision = "202604250001"
down_revision = "202604240003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS document_versions (
            id            VARCHAR(36) PRIMARY KEY,
            data_item_id  VARCHAR(36) NOT NULL REFERENCES data_items(id) ON DELETE CASCADE,
            version       INTEGER NOT NULL,
            object_key    TEXT NOT NULL,
            size_bytes    BIGINT NOT NULL DEFAULT 0,
            sha256        TEXT,
            media_type    TEXT NOT NULL,
            saved_via     TEXT NOT NULL DEFAULT 'onlyoffice',
            saved_by      VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
            note          TEXT,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE INDEX IF NOT EXISTS idx_dv_item_version
            ON document_versions(data_item_id, version);
        CREATE INDEX IF NOT EXISTS ix_document_versions_data_item_id
            ON document_versions(data_item_id);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS ix_document_versions_data_item_id;
        DROP INDEX IF EXISTS idx_dv_item_version;
        DROP TABLE IF EXISTS document_versions CASCADE;
        """
    )
