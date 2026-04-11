from sqlalchemy import bindparam, text as sql_text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from uuid import uuid4

from app.services.dashscope_client import create_embedding
from app.services.schema_helpers import ensure_column


def ensure_embedding_schema(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(sql_text("CREATE EXTENSION IF NOT EXISTS vector"))

    ensure_column(engine, "embeddings", "vector", "vector(1024)")

    with engine.begin() as connection:
        connection.execute(
            sql_text(
                "CREATE INDEX IF NOT EXISTS idx_embeddings_ws_project "
                "ON embeddings (workspace_id, project_id)"
            )
        )
        connection.execute(
            sql_text(
                "CREATE INDEX IF NOT EXISTS idx_embeddings_vector_hnsw "
                "ON embeddings USING hnsw (vector vector_cosine_ops) "
                "WITH (m = 16, ef_construction = 200)"
            )
        )


async def embed_and_store(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    memory_id: str | None = None,
    data_item_id: str | None = None,
    chunk_text: str,
    vector: list[float] | None = None,
    auto_commit: bool = True,
) -> str:
    """Embed text and store the vector in the embeddings table.
    Returns the embedding ID.
    If vector is provided, skip the embedding API call and use it directly.
    If auto_commit is False, the caller is responsible for committing."""
    if vector is None:
        vector = await create_embedding(chunk_text)

    embedding_id = str(uuid4())
    db.execute(
        sql_text("""
            INSERT INTO embeddings (id, workspace_id, project_id, memory_id, data_item_id, chunk_text, vector, created_at)
            VALUES (:id, :workspace_id, :project_id, :memory_id, :data_item_id, :chunk_text, CAST(:vector AS vector), now())
        """),
        {
            "id": embedding_id,
            "workspace_id": workspace_id,
            "project_id": project_id,
            "memory_id": memory_id,
            "data_item_id": data_item_id,
            "chunk_text": chunk_text,
            "vector": str(vector),
        },
    )
    if auto_commit:
        db.commit()
    return embedding_id


async def search_similar(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    query: str,
    limit: int = 5,
) -> list[dict]:
    """Semantic search: find most similar embeddings by cosine distance.
    Returns list of {chunk_text, memory_id, data_item_id, score}."""
    query_vector = await create_embedding(query)

    results = db.execute(
        sql_text("""
            SELECT id, chunk_text, memory_id, data_item_id,
                   1 - (vector <=> CAST(:query_vector AS vector)) AS score
            FROM embeddings
            WHERE workspace_id = :workspace_id
              AND project_id = :project_id
              AND vector IS NOT NULL
            ORDER BY vector <=> CAST(:query_vector AS vector)
            LIMIT :limit
        """),
        {
            "workspace_id": workspace_id,
            "project_id": project_id,
            "query_vector": str(query_vector),
            "limit": limit,
        },
    ).fetchall()

    return [
        {
            "id": row[0],
            "chunk_text": row[1],
            "memory_id": row[2],
            "data_item_id": row[3],
            "score": float(row[4]) if row[4] else 0.0,
        }
        for row in results
    ]


async def find_duplicate_memory_with_vector(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    text: str,
    threshold: float = 0.90,
) -> tuple[dict | None, list[float]]:
    """Check if a highly similar memory already exists.

    Returns (best_match_or_None, query_vector).
    The query_vector is always returned for reuse by downstream functions.
    """
    query_vector = await create_embedding(text)

    row = db.execute(
        sql_text("""
            SELECT e.memory_id, m.content,
                   1 - (e.vector <=> CAST(:query_vector AS vector)) AS score
            FROM embeddings e
            JOIN memories m ON m.id = e.memory_id
            WHERE e.workspace_id = :workspace_id
              AND e.project_id = :project_id
              AND e.memory_id IS NOT NULL
              AND e.vector IS NOT NULL
              AND m.type = 'permanent'
              AND COALESCE(m.node_type, 'fact') = 'fact'
              AND COALESCE(m.node_status, 'active') = 'active'
              AND 1 - (e.vector <=> CAST(:query_vector AS vector)) >= :threshold
            ORDER BY e.vector <=> CAST(:query_vector AS vector)
            LIMIT 1
        """),
        {
            "workspace_id": workspace_id,
            "project_id": project_id,
            "query_vector": str(query_vector),
            "threshold": threshold,
        },
    ).fetchone()

    if not row:
        return None, query_vector

    return {
        "memory_id": row[0],
        "content": row[1],
        "score": float(row[2]) if row[2] else 0.0,
    }, query_vector


async def find_duplicate_memory(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    text: str,
    threshold: float = 0.90,
) -> dict | None:
    """Check if a highly similar memory already exists.

    Returns the best match {memory_id, content, score} if similarity >= threshold,
    or None if no duplicate found.
    """
    result, _ = await find_duplicate_memory_with_vector(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        text=text,
        threshold=threshold,
    )
    return result


async def find_related_memories(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    query_vector: list[float],
    low: float = 0.70,
    high: float = 0.90,
    limit: int = 3,
) -> list[dict]:
    """Find memories with similarity in [low, high) range.
    Returns list of {memory_id, content, category, score}, ordered by descending similarity."""
    rows = db.execute(
        sql_text("""
            SELECT e.memory_id, m.content, m.category,
                   1 - (e.vector <=> CAST(:query_vector AS vector)) AS score
            FROM embeddings e
            JOIN memories m ON m.id = e.memory_id
            WHERE e.workspace_id = :workspace_id
              AND e.project_id = :project_id
              AND e.memory_id IS NOT NULL
              AND e.vector IS NOT NULL
              AND m.type = 'permanent'
              AND COALESCE(m.node_type, 'fact') = 'fact'
              AND COALESCE(m.node_status, 'active') = 'active'
              AND 1 - (e.vector <=> CAST(:query_vector AS vector)) >= :low
              AND 1 - (e.vector <=> CAST(:query_vector AS vector)) < :high
            ORDER BY e.vector <=> CAST(:query_vector AS vector)
            LIMIT :limit
        """),
        {
            "workspace_id": workspace_id,
            "project_id": project_id,
            "query_vector": str(query_vector),
            "low": low,
            "high": high,
            "limit": limit,
        },
    ).fetchall()

    return [
        {
            "memory_id": row[0],
            "content": row[1],
            "category": row[2],
            "score": float(row[3]) if row[3] else 0.0,
        }
        for row in rows
    ]


def delete_embeddings_for_memory(db: Session, memory_id: str) -> None:
    """Delete all embeddings associated with a memory."""
    db.execute(
        sql_text("DELETE FROM embeddings WHERE memory_id = :memory_id"),
        {"memory_id": memory_id},
    )
    db.commit()


def delete_embeddings_for_data_item(db: Session, data_item_id: str) -> None:
    """Delete all embeddings associated with a data item."""
    db.execute(
        sql_text("DELETE FROM embeddings WHERE data_item_id = :data_item_id"),
        {"data_item_id": data_item_id},
    )
    db.commit()


def find_related_memories_for_data_item(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    data_item_id: str,
    limit: int = 5,
    min_score: float = 0.55,
) -> list[dict]:
    """Find permanent public memories that are semantically close to a data item."""
    try:
        rows = db.execute(
            sql_text("""
                SELECT related.memory_id, MAX(1 - (related.vector <=> target.vector)) AS score
                FROM embeddings AS target
                JOIN embeddings AS related
                  ON related.workspace_id = target.workspace_id
                 AND related.project_id = target.project_id
                 AND related.memory_id IS NOT NULL
                JOIN memories ON memories.id = related.memory_id
                WHERE target.workspace_id = :workspace_id
                  AND target.project_id = :project_id
                  AND target.data_item_id = :data_item_id
                  AND memories.workspace_id = :workspace_id
                  AND memories.project_id = :project_id
                  AND memories.type = 'permanent'
                  AND COALESCE(memories.metadata_json ->> 'visibility', '') != 'private'
                GROUP BY related.memory_id
                HAVING MAX(1 - (related.vector <=> target.vector)) >= :min_score
                ORDER BY score DESC
                LIMIT :limit
            """),
            {
                "workspace_id": workspace_id,
                "project_id": project_id,
                "data_item_id": data_item_id,
                "min_score": min_score,
                "limit": limit,
            },
        ).fetchall()
    except Exception:  # noqa: BLE001
        return []

    return [
        {
            "memory_id": row[0],
            "score": float(row[1]) if row[1] is not None else 0.0,
        }
        for row in rows
        if row[0]
    ]


def find_related_data_items_for_memory(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    memory_id: str,
    limit: int = 5,
    min_score: float = 0.55,
) -> list[dict]:
    """Find completed data items that are semantically close to a memory."""
    try:
        rows = db.execute(
            sql_text("""
                SELECT related.data_item_id, MAX(1 - (source.vector <=> related.vector)) AS score
                FROM embeddings AS source
                JOIN embeddings AS related
                  ON related.workspace_id = source.workspace_id
                 AND related.project_id = source.project_id
                 AND related.data_item_id IS NOT NULL
                JOIN data_items ON data_items.id = related.data_item_id
                JOIN datasets ON datasets.id = data_items.dataset_id
                JOIN projects ON projects.id = datasets.project_id
                WHERE source.workspace_id = :workspace_id
                  AND source.project_id = :project_id
                  AND source.memory_id = :memory_id
                  AND data_items.deleted_at IS NULL
                  AND datasets.deleted_at IS NULL
                  AND projects.deleted_at IS NULL
                  AND projects.workspace_id = :workspace_id
                  AND COALESCE(data_items.meta_json ->> 'upload_status', 'completed') = 'completed'
                GROUP BY related.data_item_id
                HAVING MAX(1 - (source.vector <=> related.vector)) >= :min_score
                ORDER BY score DESC
                LIMIT :limit
            """),
            {
                "workspace_id": workspace_id,
                "project_id": project_id,
                "memory_id": memory_id,
                "min_score": min_score,
                "limit": limit,
            },
        ).fetchall()
    except Exception:  # noqa: BLE001
        return []

    return [
        {
            "data_item_id": row[0],
            "score": float(row[1]) if row[1] is not None else 0.0,
        }
        for row in rows
        if row[0]
    ]


async def search_data_item_chunks(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    query: str,
    data_item_ids: list[str],
    limit: int = 5,
) -> list[dict]:
    """Search only within the specified data items and return the best matching chunks."""
    if not data_item_ids:
        return []

    query_vector = await create_embedding(query)
    statement = sql_text("""
        SELECT embeddings.id, embeddings.chunk_text, embeddings.data_item_id, data_items.filename,
               1 - (embeddings.vector <=> CAST(:query_vector AS vector)) AS score
        FROM embeddings
        JOIN data_items ON data_items.id = embeddings.data_item_id
        JOIN datasets ON datasets.id = data_items.dataset_id
        JOIN projects ON projects.id = datasets.project_id
        WHERE embeddings.workspace_id = :workspace_id
          AND embeddings.project_id = :project_id
          AND embeddings.data_item_id IN :data_item_ids
          AND data_items.deleted_at IS NULL
          AND datasets.deleted_at IS NULL
          AND projects.deleted_at IS NULL
          AND projects.workspace_id = :workspace_id
          AND COALESCE(data_items.meta_json ->> 'upload_status', 'completed') = 'completed'
        ORDER BY embeddings.vector <=> CAST(:query_vector AS vector)
        LIMIT :limit
    """).bindparams(bindparam("data_item_ids", expanding=True))

    try:
        rows = db.execute(
            statement,
            {
                "workspace_id": workspace_id,
                "project_id": project_id,
                "query_vector": str(query_vector),
                "data_item_ids": data_item_ids,
                "limit": limit,
            },
        ).fetchall()
    except Exception:  # noqa: BLE001
        return []

    return [
        {
            "id": row[0],
            "chunk_text": row[1],
            "data_item_id": row[2],
            "filename": row[3],
            "score": float(row[4]) if row[4] is not None else 0.0,
        }
        for row in rows
    ]
