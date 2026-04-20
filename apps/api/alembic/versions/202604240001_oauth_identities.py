"""oauth_identities table + users.password_hash nullable

Revision ID: 202604200001
Revises: 202604230001
Create Date: 2026-04-20
"""

from alembic import op


revision = "202604240001"
down_revision = "202604230001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) Make users.password_hash nullable so OAuth-only users can exist.
    op.execute("ALTER TABLE users ALTER COLUMN password_hash DROP NOT NULL")

    # 2) Create oauth_identities table.
    op.execute(
        """
        CREATE TABLE oauth_identities (
            id              varchar(36) PRIMARY KEY,
            user_id         varchar(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            provider        text NOT NULL,
            provider_id     text NOT NULL,
            provider_email  text,
            linked_at       timestamptz NOT NULL DEFAULT now(),
            created_at      timestamptz NOT NULL DEFAULT now(),
            updated_at      timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_oauth_provider_id   UNIQUE (provider, provider_id),
            CONSTRAINT uq_oauth_provider_user UNIQUE (provider, user_id)
        )
        """
    )
    op.execute("CREATE INDEX idx_oauth_identities_user_id ON oauth_identities (user_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS oauth_identities")
    op.execute("ALTER TABLE users ALTER COLUMN password_hash SET NOT NULL")
