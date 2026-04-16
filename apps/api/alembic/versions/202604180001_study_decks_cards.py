"""study_decks and study_cards (S4)

Revision ID: 202604180001
Revises: 202604170001
Create Date: 2026-04-18
"""

from alembic import op


revision = "202604180001"
down_revision = "202604170001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS study_decks (
            id             VARCHAR(36) PRIMARY KEY,
            notebook_id    VARCHAR(36) NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
            name           VARCHAR(120) NOT NULL,
            description    TEXT NOT NULL DEFAULT '',
            card_count     INTEGER NOT NULL DEFAULT 0,
            created_by     VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            archived_at    TIMESTAMPTZ,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE INDEX IF NOT EXISTS ix_study_decks_notebook_id
            ON study_decks(notebook_id);

        CREATE TABLE IF NOT EXISTS study_cards (
            id                          VARCHAR(36) PRIMARY KEY,
            deck_id                     VARCHAR(36) NOT NULL REFERENCES study_decks(id) ON DELETE CASCADE,
            front                       TEXT NOT NULL,
            back                        TEXT NOT NULL,
            source_type                 VARCHAR(20) NOT NULL DEFAULT 'manual',
            source_ref                  VARCHAR(64),
            difficulty                  DOUBLE PRECISION NOT NULL DEFAULT 5.0,
            stability                   DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            last_review_at              TIMESTAMPTZ,
            next_review_at              TIMESTAMPTZ,
            review_count                INTEGER NOT NULL DEFAULT 0,
            lapse_count                 INTEGER NOT NULL DEFAULT 0,
            consecutive_failures        INTEGER NOT NULL DEFAULT 0,
            confusion_memory_written_at TIMESTAMPTZ,
            created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE INDEX IF NOT EXISTS ix_study_cards_deck_id
            ON study_cards(deck_id);
        CREATE INDEX IF NOT EXISTS ix_study_cards_deck_due
            ON study_cards(deck_id, next_review_at ASC);
        CREATE INDEX IF NOT EXISTS ix_study_cards_deck_created
            ON study_cards(deck_id, created_at DESC);
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS study_cards CASCADE;
        DROP TABLE IF EXISTS study_decks CASCADE;
    """)
