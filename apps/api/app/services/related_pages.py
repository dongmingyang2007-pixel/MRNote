"""S7 Search — related-pages service.

Combines embedding k-NN (when page has an embedding_id) with shared
memory-subject overlap. Shared-subject works on SQLite; semantic
requires pgvector.

Page → memory linking flows through MemoryEpisode:
    notebook_pages.id
        ← memory_episodes.source_id (with source_type='notebook_page')
        ← memory_evidences.episode_id
        → memory_evidences.memory_id (the shared subject)
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text

logger = logging.getLogger(__name__)


def get_related(
    db: Session,
    *,
    page_id: str,
    workspace_id: str,
    limit: int = 5,
) -> dict[str, list[dict[str, Any]]]:
    """Return related pages + memories for the given page."""
    target = db.execute(
        sql_text("""
            SELECT p.id, p.embedding_id, n.workspace_id
            FROM notebook_pages p
            JOIN notebooks n ON n.id = p.notebook_id
            WHERE p.id = :page_id AND n.workspace_id = :workspace_id
            LIMIT 1
        """),
        {"page_id": page_id, "workspace_id": workspace_id},
    ).fetchone()
    if target is None:
        return {"pages": [], "memory": []}

    embedding_id = target[1]

    # Step 1: find memories linked to THIS page via episodes.
    subject_rows = db.execute(
        sql_text("""
            SELECT DISTINCT ev.memory_id
            FROM memory_evidences ev
            JOIN memory_episodes ep ON ep.id = ev.episode_id
            WHERE ep.source_type = 'notebook_page'
              AND ep.source_id = :page_id
        """),
        {"page_id": page_id},
    ).fetchall()
    memory_ids = [r[0] for r in subject_rows if r[0]]

    shared_pages: list[dict[str, Any]] = []
    related_memories: list[dict[str, Any]] = []
    if memory_ids:
        ids_sql = "(" + ",".join(f"'{mid}'" for mid in memory_ids) + ")"

        # Step 2: find OTHER pages whose episodes carry any of these memories.
        other_page_rows = db.execute(
            sql_text(f"""
                SELECT DISTINCT p.id, p.notebook_id, p.title
                FROM memory_evidences ev
                JOIN memory_episodes ep ON ep.id = ev.episode_id
                JOIN notebook_pages p ON p.id = ep.source_id
                JOIN notebooks n ON n.id = p.notebook_id
                WHERE ep.source_type = 'notebook_page'
                  AND ev.memory_id IN {ids_sql}
                  AND p.id != :page_id
                  AND n.workspace_id = :workspace_id
                LIMIT :limit
            """),
            {"page_id": page_id, "workspace_id": workspace_id, "limit": limit * 2},
        ).fetchall()
        shared_pages = [
            {
                "id": r[0], "notebook_id": r[1], "title": r[2] or "",
                "score": 0.5, "reason": "shared_subject",
            }
            for r in other_page_rows
        ]

        # Connected memories for the "memory" bucket.
        mem_rows = db.execute(
            sql_text(f"""
                SELECT m.id, m.content, m.confidence
                FROM memories m
                WHERE m.id IN {ids_sql}
                  AND m.workspace_id = :workspace_id
                  AND m.node_status = 'active'
                ORDER BY m.confidence DESC
                LIMIT :limit
            """),
            {"workspace_id": workspace_id, "limit": limit},
        ).fetchall()
        related_memories = [
            {"id": r[0], "content": (r[1] or "")[:200],
             "score": float(r[2] or 0.0), "reason": "shared_subject"}
            for r in mem_rows
        ]

    # Semantic branch (pgvector; best-effort, skipped on SQLite)
    semantic_pages: list[dict[str, Any]] = []
    if embedding_id:
        try:
            sem_rows = db.execute(
                sql_text("""
                    SELECT p2.id, p2.notebook_id, p2.title,
                           1 - (e2.vector <=> e1.vector) AS score
                    FROM embeddings e1
                    JOIN embeddings e2 ON e2.id != e1.id
                    JOIN notebook_pages p2 ON p2.embedding_id = e2.id
                    JOIN notebooks n2 ON n2.id = p2.notebook_id
                    WHERE e1.id = :emb_id
                      AND n2.workspace_id = :workspace_id
                      AND p2.id != :page_id
                    ORDER BY e2.vector <=> e1.vector
                    LIMIT :limit
                """),
                {"emb_id": embedding_id, "page_id": page_id,
                 "workspace_id": workspace_id, "limit": limit * 2},
            ).fetchall()
            semantic_pages = [
                {"id": r[0], "notebook_id": r[1], "title": r[2] or "",
                 "score": float(r[3] or 0.0), "reason": "semantic"}
                for r in sem_rows
            ]
        except Exception:
            logger.warning("related_pages semantic failed", exc_info=False)

    # Merge: semantic wins the "reason" tag when a page appears in both.
    seen: dict[str, dict[str, Any]] = {}
    for p in semantic_pages:
        seen[p["id"]] = p
    for p in shared_pages:
        if p["id"] not in seen:
            seen[p["id"]] = p
    merged_pages = sorted(
        seen.values(), key=lambda h: h["score"], reverse=True,
    )[:limit]
    return {"pages": merged_pages, "memory": related_memories}
