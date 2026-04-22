"""S7 Search dispatcher: fans out across 5 scopes, merges via RRF."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy import or_
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from app.core.deps import is_workspace_privileged_role
from app.models import AIActionLog, DataItem, Notebook, NotebookAttachment, NotebookPage, StudyAsset
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
    "pages", "blocks", "study_assets", "files", "memory", "playbooks", "ai_actions",
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
    current_user_id: str | None = None,
    workspace_role: str = "owner",
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

    readable_notebook_ids: set[str] | None = None
    if current_user_id and not is_workspace_privileged_role(workspace_role):
        readable_notebook_ids = {
            notebook_id
            for (notebook_id,) in (
                db.query(Notebook.id)
                .filter(Notebook.workspace_id == workspace_id)
                .filter(
                    or_(
                        Notebook.visibility != "private",
                        Notebook.created_by == current_user_id,
                    )
                )
                .all()
            )
        }

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
    if "files" in scopes:
        jobs.append(("files", _search_files(
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
    if "ai_actions" in scopes:
        jobs.append(("ai_actions", _search_ai_actions(
            db, workspace_id=workspace_id, notebook_id=notebook_id,
            query=query, limit=limit,
            current_user_id=current_user_id,
            workspace_role=workspace_role,
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
            if readable_notebook_ids is not None and scope in {
                "pages", "blocks", "study_assets", "files", "ai_actions",
            }:
                out[scope] = [
                    hit
                    for hit in out[scope]
                    if _hit_is_visible_to_viewer(
                        hit,
                        scope=scope,
                        readable_notebook_ids=readable_notebook_ids,
                    )
                ]
    return out


def _hit_is_visible_to_viewer(
    hit: dict[str, Any],
    *,
    scope: str,
    readable_notebook_ids: set[str],
) -> bool:
    notebook_id = hit.get("notebook_id")
    if notebook_id is None:
        return scope == "ai_actions"
    return str(notebook_id) in readable_notebook_ids


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
                  AND (CAST(:project_id AS TEXT) IS NULL OR n.project_id = :project_id)
                  AND (CAST(:notebook_id AS TEXT) IS NULL OR p.notebook_id = :notebook_id)
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
        try: db.rollback()
        except Exception: pass
        # Fallback for SQLite / missing pg_trgm: plain LIKE + static score.
        rows = db.execute(
            sql_text("""
                SELECT p.id, p.notebook_id, p.title, p.plain_text, 0.5 AS score
                FROM notebook_pages p
                JOIN notebooks n ON n.id = p.notebook_id
                WHERE n.workspace_id = :workspace_id
                  AND (CAST(:project_id AS TEXT) IS NULL OR n.project_id = :project_id)
                  AND (CAST(:notebook_id AS TEXT) IS NULL OR p.notebook_id = :notebook_id)
                  AND p.is_archived = FALSE
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
                  AND (CAST(:project_id AS TEXT) IS NULL OR n.project_id = :project_id)
                  AND (CAST(:notebook_id AS TEXT) IS NULL OR p.notebook_id = :notebook_id)
                  AND (b.plain_text % :q OR b.plain_text ILIKE :like)
                ORDER BY score DESC, b.updated_at DESC
                LIMIT :limit
            """),
            {"q": query, "like": like, "workspace_id": workspace_id,
             "project_id": project_id, "notebook_id": notebook_id,
             "limit": limit},
        ).fetchall()
    except Exception:
        try: db.rollback()
        except Exception: pass
        rows = db.execute(
            sql_text("""
                SELECT b.id, b.page_id, p.notebook_id, b.plain_text, 0.5 AS score
                FROM notebook_blocks b
                JOIN notebook_pages p ON p.id = b.page_id
                JOIN notebooks n ON n.id = p.notebook_id
                WHERE n.workspace_id = :workspace_id
                  AND (CAST(:project_id AS TEXT) IS NULL OR n.project_id = :project_id)
                  AND (CAST(:notebook_id AS TEXT) IS NULL OR p.notebook_id = :notebook_id)
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
                  AND (CAST(:project_id AS TEXT) IS NULL OR n.project_id = :project_id)
                  AND (CAST(:notebook_id AS TEXT) IS NULL OR sa.notebook_id = :notebook_id)
                  AND sa.status != 'deleted'
                  AND (sa.title % :q OR sa.title ILIKE :like)
                ORDER BY score DESC, sa.updated_at DESC
                LIMIT :limit
            """),
            {"q": query, "like": like, "workspace_id": workspace_id,
             "project_id": project_id, "notebook_id": notebook_id,
             "limit": limit * 2},
        ).fetchall()
    except Exception:
        try: db.rollback()
        except Exception: pass
        title_rows = db.execute(
            sql_text("""
                SELECT sa.id, sa.notebook_id, sa.title, 0.5 AS score
                FROM study_assets sa
                JOIN notebooks n ON n.id = sa.notebook_id
                WHERE n.workspace_id = :workspace_id
                  AND (CAST(:project_id AS TEXT) IS NULL OR n.project_id = :project_id)
                  AND (CAST(:notebook_id AS TEXT) IS NULL OR sa.notebook_id = :notebook_id)
                  AND sa.status != 'deleted'
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


async def _search_files(
    db: Session,
    *,
    workspace_id: str,
    project_id: str | None,
    notebook_id: str | None,
    query: str,
    limit: int,
) -> list[dict[str, Any]]:
    like = f"%{query.strip()}%"
    attachment_rows = (
        db.query(NotebookAttachment, NotebookPage.notebook_id)
        .join(NotebookPage, NotebookPage.id == NotebookAttachment.page_id)
        .join(Notebook, Notebook.id == NotebookPage.notebook_id)
        .filter(Notebook.workspace_id == workspace_id)
        .filter(NotebookAttachment.title.ilike(like))
        .filter(NotebookPage.is_archived.is_(False))
    )
    if project_id:
        attachment_rows = attachment_rows.filter(Notebook.project_id == project_id)
    if notebook_id:
        attachment_rows = attachment_rows.filter(NotebookPage.notebook_id == notebook_id)
    attachment_items = attachment_rows.order_by(NotebookAttachment.created_at.desc()).limit(limit * 2).all()

    study_rows = (
        db.query(StudyAsset, DataItem)
        .join(Notebook, Notebook.id == StudyAsset.notebook_id)
        .join(DataItem, DataItem.id == StudyAsset.data_item_id)
        .filter(Notebook.workspace_id == workspace_id)
        .filter(StudyAsset.status != "deleted")
        .filter(DataItem.deleted_at.is_(None))
        .filter(
            or_(
                StudyAsset.title.ilike(like),
                DataItem.filename.ilike(like),
            )
        )
    )
    if project_id:
        study_rows = study_rows.filter(Notebook.project_id == project_id)
    if notebook_id:
        study_rows = study_rows.filter(StudyAsset.notebook_id == notebook_id)
    study_items = study_rows.order_by(StudyAsset.created_at.desc()).limit(limit * 2).all()

    hits = [
        {
            "id": attachment.id,
            "attachment_id": attachment.id,
            "page_id": attachment.page_id,
            "notebook_id": page_notebook_id,
            "title": attachment.title or "Attachment",
            "snippet": attachment.title or "",
            "mime_type": str((attachment.meta_json or {}).get("mime_type") or ""),
            "score": 0.5,
            "source": "lexical",
            "_created_at": attachment.created_at,
        }
        for attachment, page_notebook_id in attachment_items
    ]
    hits.extend(
        {
            "id": asset.id,
            "asset_id": asset.id,
            "data_item_id": asset.data_item_id,
            "notebook_id": asset.notebook_id,
            "title": asset.title or data_item.filename or "Study document",
            "snippet": data_item.filename or asset.title or "",
            "mime_type": data_item.media_type or "",
            "score": 0.5,
            "source": "lexical",
            "_created_at": asset.created_at,
        }
        for asset, data_item in study_items
    )
    hits.sort(key=lambda hit: hit.get("_created_at"), reverse=True)
    return [
        {key: value for key, value in hit.items() if key != "_created_at"}
        for hit in hits[:limit]
    ]


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


async def _search_ai_actions(
    db: Session,
    *,
    workspace_id: str,
    notebook_id: str | None,
    query: str,
    limit: int,
    current_user_id: str | None = None,
    workspace_role: str = "owner",
) -> list[dict[str, Any]]:
    like = f"%{query.strip()}%"
    rows = (
        db.query(AIActionLog, NotebookPage.title, Notebook.title)
        .outerjoin(NotebookPage, NotebookPage.id == AIActionLog.page_id)
        .outerjoin(Notebook, Notebook.id == AIActionLog.notebook_id)
        .filter(AIActionLog.workspace_id == workspace_id)
        .filter(
            (AIActionLog.action_type.ilike(like))
            | (AIActionLog.output_summary.ilike(like))
        )
    )
    if current_user_id and not is_workspace_privileged_role(workspace_role):
        rows = rows.filter(AIActionLog.user_id == current_user_id)
    if notebook_id:
        rows = rows.filter(AIActionLog.notebook_id == notebook_id)
    items = rows.order_by(AIActionLog.created_at.desc()).limit(limit).all()
    return [
        {
            "id": action.id,
            "action_log_id": action.id,
            "page_id": action.page_id,
            "notebook_id": action.notebook_id,
            "title": page_title or action.action_type,
            "snippet": action.output_summary or action.action_type,
            "action_type": action.action_type,
            "notebook_title": notebook_title or "",
            "score": 0.5,
            "source": "lexical",
        }
        for action, page_title, notebook_title in items
    ]
