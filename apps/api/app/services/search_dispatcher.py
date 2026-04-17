"""S7 Search dispatcher: fans out across 5 scopes, merges via RRF."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from app.services.memory_v2 import (
    search_memories_lexical,
    search_memory_views_lexical,
)
from app.services.search_rank import rrf_merge
from app.services.search_vector import (
    search_memories_semantic,
    search_pages_semantic,
    search_study_chunks_semantic,
)

logger = logging.getLogger(__name__)

SCOPES: tuple[str, ...] = (
    "pages", "blocks", "study_assets", "memory", "playbooks",
)
MIN_QUERY_LENGTH = 2


async def search_workspace(
    db: Session,
    *,
    workspace_id: str,
    query: str,
    scopes: set[str],
    project_id: str | None = None,
    notebook_id: str | None = None,
    limit: int = 8,
) -> dict[str, list[dict[str, Any]]]:
    """Entry point. Returns {scope_name: list[Hit]}."""
    out: dict[str, list[dict[str, Any]]] = {s: [] for s in SCOPES}
    if len(query.strip()) < MIN_QUERY_LENGTH:
        return out

    # If notebook_id given, resolve its project_id to scope memory/playbooks.
    resolved_project_id = project_id
    if notebook_id is not None:
        row = db.execute(
            sql_text("SELECT project_id FROM notebooks WHERE id = :nb_id"),
            {"nb_id": notebook_id},
        ).fetchone()
        if row and row[0]:
            resolved_project_id = row[0]

    jobs: list[tuple[str, Any]] = []
    if "pages" in scopes:
        jobs.append(("pages", _search_pages(
            db, workspace_id=workspace_id, project_id=resolved_project_id,
            notebook_id=notebook_id, query=query, limit=limit,
        )))
    if "blocks" in scopes:
        jobs.append(("blocks", _search_blocks(
            db, workspace_id=workspace_id, project_id=resolved_project_id,
            notebook_id=notebook_id, query=query, limit=limit,
        )))
    if "study_assets" in scopes:
        jobs.append(("study_assets", _search_study_assets(
            db, workspace_id=workspace_id, project_id=resolved_project_id,
            notebook_id=notebook_id, query=query, limit=limit,
        )))
    if "memory" in scopes and resolved_project_id:
        jobs.append(("memory", _search_memory(
            db, workspace_id=workspace_id, project_id=resolved_project_id,
            query=query, limit=limit,
        )))
    if "playbooks" in scopes and resolved_project_id:
        jobs.append(("playbooks", _search_playbooks(
            db, workspace_id=workspace_id, project_id=resolved_project_id,
            query=query, limit=limit,
        )))

    results = await asyncio.gather(
        *(coro for _, coro in jobs), return_exceptions=True,
    )
    for (scope, _), result in zip(jobs, results, strict=True):
        if isinstance(result, Exception):
            logger.warning("search scope %s failed: %s", scope, result)
            out[scope] = []
        else:
            out[scope] = result  # type: ignore[assignment]
    return out


def _lexical_pages_sql(db: Session, *, workspace_id: str,
                      project_id: str | None, notebook_id: str | None,
                      query: str, limit: int) -> list[dict[str, Any]]:
    """pg_trgm on Postgres; ILIKE fallback so SQLite tests work."""
    like = f"%{query.strip()}%"
    try:
        rows = db.execute(
            sql_text("""
                SELECT p.id, p.notebook_id, p.title, p.plain_text,
                       GREATEST(
                         similarity(COALESCE(p.title,''), :q),
                         similarity(COALESCE(p.plain_text,''), :q)
                       ) AS score
                FROM notebook_pages p
                JOIN notebooks n ON n.id = p.notebook_id
                WHERE n.workspace_id = :workspace_id
                  AND (:project_id IS NULL OR n.project_id = :project_id)
                  AND (:notebook_id IS NULL OR p.notebook_id = :notebook_id)
                  AND p.is_archived = FALSE
                  AND (p.title % :q OR p.plain_text % :q
                       OR p.title ILIKE :like OR p.plain_text ILIKE :like)
                ORDER BY score DESC, p.updated_at DESC
                LIMIT :limit
            """),
            {"q": query, "like": like, "workspace_id": workspace_id,
             "project_id": project_id, "notebook_id": notebook_id,
             "limit": limit},
        ).fetchall()
    except Exception:
        # Fallback for SQLite / missing pg_trgm: plain LIKE + static score.
        rows = db.execute(
            sql_text("""
                SELECT p.id, p.notebook_id, p.title, p.plain_text, 0.5 AS score
                FROM notebook_pages p
                JOIN notebooks n ON n.id = p.notebook_id
                WHERE n.workspace_id = :workspace_id
                  AND (:project_id IS NULL OR n.project_id = :project_id)
                  AND (:notebook_id IS NULL OR p.notebook_id = :notebook_id)
                  AND p.is_archived = 0
                  AND (p.title LIKE :like OR p.plain_text LIKE :like)
                ORDER BY p.updated_at DESC
                LIMIT :limit
            """),
            {"like": like, "workspace_id": workspace_id,
             "project_id": project_id, "notebook_id": notebook_id,
             "limit": limit},
        ).fetchall()
    return [
        {
            "id": r[0],
            "notebook_id": r[1],
            "title": r[2] or "",
            "snippet": (r[3] or "")[:200],
            "score": float(r[4] or 0.0),
            "source": "lexical",
        }
        for r in rows
    ]


async def _search_pages(
    db: Session, *, workspace_id: str, project_id: str | None,
    notebook_id: str | None, query: str, limit: int,
) -> list[dict[str, Any]]:
    lex = _lexical_pages_sql(
        db, workspace_id=workspace_id, project_id=project_id,
        notebook_id=notebook_id, query=query, limit=limit * 2,
    )
    sem = await search_pages_semantic(
        db, workspace_id=workspace_id, project_id=project_id,
        notebook_id=notebook_id, query=query, limit=limit * 2,
    )
    merged = rrf_merge(lex, sem, limit=limit)
    for h in merged:
        if "source" not in h:
            h["source"] = "rrf"
        elif h["source"] == "semantic" and any(
            x["id"] == h["id"] for x in lex
        ):
            h["source"] = "rrf"
    return merged


async def _search_blocks(
    db: Session, *, workspace_id: str, project_id: str | None,
    notebook_id: str | None, query: str, limit: int,
) -> list[dict[str, Any]]:
    like = f"%{query.strip()}%"
    try:
        rows = db.execute(
            sql_text("""
                SELECT b.id, b.page_id, p.notebook_id, b.plain_text,
                       similarity(COALESCE(b.plain_text,''), :q) AS score
                FROM notebook_blocks b
                JOIN notebook_pages p ON p.id = b.page_id
                JOIN notebooks n ON n.id = p.notebook_id
                WHERE n.workspace_id = :workspace_id
                  AND (:project_id IS NULL OR n.project_id = :project_id)
                  AND (:notebook_id IS NULL OR p.notebook_id = :notebook_id)
                  AND (b.plain_text % :q OR b.plain_text ILIKE :like)
                ORDER BY score DESC, b.updated_at DESC
                LIMIT :limit
            """),
            {"q": query, "like": like, "workspace_id": workspace_id,
             "project_id": project_id, "notebook_id": notebook_id,
             "limit": limit},
        ).fetchall()
    except Exception:
        rows = db.execute(
            sql_text("""
                SELECT b.id, b.page_id, p.notebook_id, b.plain_text, 0.5 AS score
                FROM notebook_blocks b
                JOIN notebook_pages p ON p.id = b.page_id
                JOIN notebooks n ON n.id = p.notebook_id
                WHERE n.workspace_id = :workspace_id
                  AND (:project_id IS NULL OR n.project_id = :project_id)
                  AND (:notebook_id IS NULL OR p.notebook_id = :notebook_id)
                  AND b.plain_text LIKE :like
                LIMIT :limit
            """),
            {"like": like, "workspace_id": workspace_id,
             "project_id": project_id, "notebook_id": notebook_id,
             "limit": limit},
        ).fetchall()
    return [
        {
            "id": r[0],
            "page_id": r[1],
            "notebook_id": r[2],
            "snippet": (r[3] or "")[:200],
            "score": float(r[4] or 0.0),
            "source": "lexical",
        }
        for r in rows
    ]


async def _search_study_assets(
    db: Session, *, workspace_id: str, project_id: str | None,
    notebook_id: str | None, query: str, limit: int,
) -> list[dict[str, Any]]:
    like = f"%{query.strip()}%"
    try:
        title_rows = db.execute(
            sql_text("""
                SELECT sa.id, sa.notebook_id, sa.title,
                       similarity(COALESCE(sa.title,''), :q) AS score
                FROM study_assets sa
                JOIN notebooks n ON n.id = sa.notebook_id
                WHERE n.workspace_id = :workspace_id
                  AND (:project_id IS NULL OR n.project_id = :project_id)
                  AND (:notebook_id IS NULL OR sa.notebook_id = :notebook_id)
                  AND (sa.title % :q OR sa.title ILIKE :like)
                ORDER BY score DESC, sa.updated_at DESC
                LIMIT :limit
            """),
            {"q": query, "like": like, "workspace_id": workspace_id,
             "project_id": project_id, "notebook_id": notebook_id,
             "limit": limit * 2},
        ).fetchall()
    except Exception:
        title_rows = db.execute(
            sql_text("""
                SELECT sa.id, sa.notebook_id, sa.title, 0.5 AS score
                FROM study_assets sa
                JOIN notebooks n ON n.id = sa.notebook_id
                WHERE n.workspace_id = :workspace_id
                  AND (:project_id IS NULL OR n.project_id = :project_id)
                  AND (:notebook_id IS NULL OR sa.notebook_id = :notebook_id)
                  AND sa.title LIKE :like
                LIMIT :limit
            """),
            {"like": like, "workspace_id": workspace_id,
             "project_id": project_id, "notebook_id": notebook_id,
             "limit": limit * 2},
        ).fetchall()
    lex_title = [
        {
            "asset_id": r[0], "chunk_id": None, "notebook_id": r[1],
            "title": r[2] or "", "snippet": r[2] or "",
            "score": float(r[3] or 0.0), "source": "lexical",
        }
        for r in title_rows
    ]
    sem_chunks = await search_study_chunks_semantic(
        db, workspace_id=workspace_id, project_id=project_id,
        notebook_id=notebook_id, query=query, limit=limit * 2,
    )
    merged = rrf_merge(
        lex_title, sem_chunks, limit=limit,
        key_fn=lambda h: str(h.get("asset_id") or ""),
    )
    for h in merged:
        if "source" not in h:
            h["source"] = "rrf"
    return merged


async def _search_memory(
    db: Session, *, workspace_id: str, project_id: str,
    query: str, limit: int,
) -> list[dict[str, Any]]:
    try:
        lex_raw = search_memories_lexical(
            db, workspace_id=workspace_id, project_id=project_id,
            query=query, limit=limit * 2,
        )
    except Exception:
        logger.warning("memory lexical failed", exc_info=False)
        lex_raw = []
    lex = [
        {"id": r["memory_id"], "project_id": project_id,
         "snippet": r.get("snippet", ""), "score": r.get("score", 0.0),
         "source": "lexical"}
        for r in lex_raw
    ]
    sem = await search_memories_semantic(
        db, workspace_id=workspace_id, project_id=project_id,
        query=query, limit=limit * 2,
    )
    merged = rrf_merge(lex, sem, limit=limit)
    for h in merged:
        if "source" not in h:
            h["source"] = "rrf"
    return merged


async def _search_playbooks(
    db: Session, *, workspace_id: str, project_id: str,
    query: str, limit: int,
) -> list[dict[str, Any]]:
    try:
        raw = search_memory_views_lexical(
            db, workspace_id=workspace_id, project_id=project_id,
            query=query, limit=limit,
        )
    except Exception:
        logger.warning("playbooks lexical failed", exc_info=False)
        raw = []
    # search_memory_views_lexical returns dicts with keys:
    # {view_id, source_subject_id, view_type, score, snippet}
    return [
        {
            "memory_view_id": r.get("view_id", ""),
            "project_id": project_id,
            "title": (r.get("snippet") or "")[:80],
            "snippet": (r.get("snippet") or "")[:200],
            "score": r.get("score", 0.0),
            "source": "lexical",
        }
        for r in raw
        if r.get("view_type") == "playbook"
    ]
