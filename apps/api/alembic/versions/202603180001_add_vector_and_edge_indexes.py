"""Add HNSW vector index on embeddings and source/target indexes on memory_edges

Revision ID: 202603180001
Revises: 202603160003
Create Date: 2026-03-18
"""

from alembic import op

revision = "202603180001"
down_revision = "202603160003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        -- HNSW vector index for cosine similarity search on embeddings.
        -- This dramatically speeds up semantic search at scale (100+ rows).
        CREATE INDEX IF NOT EXISTS idx_embeddings_vector_hnsw
          ON embeddings USING hnsw (vector vector_cosine_ops)
          WITH (m = 16, ef_construction = 200);

        -- Source and target indexes on memory_edges for fast graph traversal.
        CREATE INDEX IF NOT EXISTS idx_memory_edges_source
          ON memory_edges (source_memory_id);
        CREATE INDEX IF NOT EXISTS idx_memory_edges_target
          ON memory_edges (target_memory_id);

        -- Index on memory_files.memory_id for fast file lookup per memory.
        CREATE INDEX IF NOT EXISTS idx_memory_files_memory_id
          ON memory_files (memory_id);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS idx_memory_files_memory_id;
        DROP INDEX IF EXISTS idx_memory_edges_target;
        DROP INDEX IF EXISTS idx_memory_edges_source;
        DROP INDEX IF EXISTS idx_embeddings_vector_hnsw;
        """
    )
