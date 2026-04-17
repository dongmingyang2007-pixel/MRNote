"""Semantic search helpers that join the embeddings table with
notebook_pages, memories, or study_chunks to return scope-specific
results. Defensive against pgvector-missing environments (SQLite
tests)."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from app.services.embedding import create_embedding

logger = logging.getLogger(__name__)


async def search_pages_semantic(
    db: Session,
    *,
    workspace_id: str,
    project_id: str | None = None,
    notebook_id: str | None = None,
    query: str,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Return pages ranked by cosine similarity to query embedding."""
    try:
        q_vec = await create_embedding(query)
    except Exception:
        logger.warning("search_pages_semantic: embedding failed", exc_info=True)
        return []
    try:
        rows = db.execute(
            sql_text("""
                SELECT p.id, p.notebook_id, p.title, p.plain_text,
                       1 - (e.vector <=> CAST(:q_vec AS vector)) AS score
                FROM notebook_pages p
                JOIN embeddings e ON e.id = p.embedding_id
                JOIN notebooks n ON n.id = p.notebook_id
                WHERE n.workspace_id = :workspace_id
                  AND (CAST(:project_id AS TEXT) IS NULL OR n.project_id = :project_id)
                  AND (CAST(:notebook_id AS TEXT) IS NULL OR p.notebook_id = :notebook_id)
                  AND p.is_archived = FALSE
                ORDER BY e.vector <=> CAST(:q_vec AS vector)
                LIMIT :limit
            """),
            {
                "q_vec": str(q_vec),
                "workspace_id": workspace_id,
                "project_id": project_id,
                "notebook_id": notebook_id,
                "limit": limit,
            },
        ).fetchall()
    except Exception:
        try: db.rollback()
        except Exception: pass
        logger.warning("search_pages_semantic: SQL failed (expected on SQLite)", exc_info=False)
        return []
    return [
        {
            "id": r[0],
            "notebook_id": r[1],
            "title": r[2] or "",
            "snippet": (r[3] or "")[:200],
            "score": float(r[4] or 0.0),
            "source": "semantic",
        }
        for r in rows
    ]


async def search_memories_semantic(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    query: str,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Return memories ranked by cosine similarity on their embedding row."""
    try:
        q_vec = await create_embedding(query)
    except Exception:
        logger.warning("search_memories_semantic: embedding failed", exc_info=True)
        return []
    try:
        rows = db.execute(
            sql_text("""
                SELECT m.id, m.project_id, m.content,
                       1 - (e.vector <=> CAST(:q_vec AS vector)) AS score
                FROM memories m
                JOIN embeddings e ON e.memory_id = m.id
                WHERE m.workspace_id = :workspace_id
                  AND m.project_id = :project_id
                  AND m.node_status = 'active'
                ORDER BY e.vector <=> CAST(:q_vec AS vector)
                LIMIT :limit
            """),
            {
                "q_vec": str(q_vec),
                "workspace_id": workspace_id,
                "project_id": project_id,
                "limit": limit,
            },
        ).fetchall()
    except Exception:
        try: db.rollback()
        except Exception: pass
        logger.warning("search_memories_semantic: SQL failed", exc_info=False)
        return []
    return [
        {
            "id": r[0],
            "project_id": r[1],
            "snippet": (r[2] or "")[:200],
            "score": float(r[3] or 0.0),
            "source": "semantic",
        }
        for r in rows
    ]


async def search_study_chunks_semantic(
    db: Session,
    *,
    workspace_id: str,
    project_id: str | None = None,
    notebook_id: str | None = None,
    query: str,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Return study chunks ranked by cosine similarity."""
    try:
        q_vec = await create_embedding(query)
    except Exception:
        logger.warning("search_study_chunks_semantic: embedding failed", exc_info=True)
        return []
    try:
        rows = db.execute(
            sql_text("""
                SELECT sa.id AS asset_id, sc.id AS chunk_id,
                       sa.notebook_id, sa.title, sc.content,
                       1 - (e.vector <=> CAST(:q_vec AS vector)) AS score
                FROM study_chunks sc
                JOIN embeddings e ON e.id = sc.embedding_id
                JOIN study_assets sa ON sa.id = sc.asset_id
                JOIN notebooks n ON n.id = sa.notebook_id
                WHERE n.workspace_id = :workspace_id
                  AND (CAST(:project_id AS TEXT) IS NULL OR n.project_id = :project_id)
                  AND (CAST(:notebook_id AS TEXT) IS NULL OR sa.notebook_id = :notebook_id)
                ORDER BY e.vector <=> CAST(:q_vec AS vector)
                LIMIT :limit
            """),
            {
                "q_vec": str(q_vec),
                "workspace_id": workspace_id,
                "project_id": project_id,
                "notebook_id": notebook_id,
                "limit": limit,
            },
        ).fetchall()
    except Exception:
        try: db.rollback()
        except Exception: pass
        logger.warning("search_study_chunks_semantic: SQL failed", exc_info=False)
        return []
    return [
        {
            "asset_id": r[0],
            "chunk_id": r[1],
            "notebook_id": r[2],
            "title": r[3] or "",
            "snippet": (r[4] or "")[:200],
            "score": float(r[5] or 0.0),
            "source": "semantic",
        }
        for r in rows
    ]
