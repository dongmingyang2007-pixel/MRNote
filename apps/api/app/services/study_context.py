"""Assemble a context payload for /ai/study/ask.

Returns (context_dict, sources_list) where:
  context_dict = {
      "system_prompt": str with chunks + notes stitched in,
  }
  sources_list = [{"type": "chunk", "id": "...", "title": "..."}]
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models import StudyAsset, StudyChunk


logger = logging.getLogger(__name__)


def assemble_study_context(
    db: Session,
    *,
    asset_id: str,
    workspace_id: str,
    project_id: str,
    user_id: str,
    query: str,
    max_chunks: int = 3,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """S4 minimum: pull the first N chunks of the asset by chunk_index.

    A richer embedding-similarity search is a reasonable follow-up but
    is explicitly outside S4's scope — see spec §6.3.3.
    """
    asset = db.query(StudyAsset).filter_by(id=asset_id).first()
    if not asset:
        return ({"system_prompt": ""}, [])

    chunks = (
        db.query(StudyChunk)
        .filter(StudyChunk.asset_id == asset.id)
        .order_by(StudyChunk.chunk_index.asc())
        .limit(max_chunks)
        .all()
    )

    sources = [
        {
            "type": "chunk",
            "id": c.id,
            "chunk_id": c.id,
            "asset_id": str(asset.id),
            "asset_title": asset.title or "Untitled",
            "data_item_id": str(asset.data_item_id) if asset.data_item_id else None,
            "title": c.heading or f"Chunk {c.chunk_index}",
            "heading": c.heading,
            "page_number": c.page_number,
        }
        for c in chunks
    ]
    chunks_text = "\n\n---\n\n".join(
        (c.heading + "\n" if c.heading else "") + (c.content or "")[:2000]
        for c in chunks
    )
    system = (
        "You are helping a user understand a study asset. "
        "Use the chunks below as authoritative context. Be concise.\n\n"
        f"CHUNKS:\n{chunks_text}\n\n"
        f"USER QUESTION: {query}"
    )
    return ({"system_prompt": system}, sources)


async def assemble_notebook_study_context(
    db: Session,
    *,
    notebook_id: str,
    workspace_id: str,
    project_id: str,
    user_id: str,
    query: str,
    max_chunks: int = 6,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Cross-asset retrieval: pull the most relevant chunks from any indexed
    study asset in the notebook.

    Uses embedding similarity (when available) to rank chunks across all
    documents in the notebook, then enriches each result with the matching
    `StudyChunk` (for `page_number` / `heading`) so the frontend can offer
    cross-asset page-jump.

    Falls back to "first N chunks of the most-recent indexed asset" when
    embeddings haven't been populated (e.g. local dev without a vector
    backend).
    """
    assets = (
        db.query(StudyAsset)
        .filter(
            StudyAsset.notebook_id == notebook_id,
            StudyAsset.status != "deleted",
        )
        .all()
    )
    if not assets:
        return ({"system_prompt": ""}, [])

    asset_by_data_item: dict[str, StudyAsset] = {}
    asset_by_id: dict[str, StudyAsset] = {}
    for asset in assets:
        asset_by_id[str(asset.id)] = asset
        if asset.data_item_id:
            asset_by_data_item[str(asset.data_item_id)] = asset

    sources: list[dict[str, Any]] = []
    chunk_blocks: list[str] = []
    used_chunk_ids: set[str] = set()

    if asset_by_data_item:
        try:
            from app.services.embedding import search_similar

            results = await search_similar(
                db,
                workspace_id=workspace_id,
                project_id=project_id,
                query=query,
                limit=max_chunks * 4,
            )
            for row in results:
                data_item_id = row.get("data_item_id")
                if not data_item_id or data_item_id not in asset_by_data_item:
                    continue
                score = float(row.get("score") or 0.0)
                if score < 0.3:
                    continue
                asset = asset_by_data_item[data_item_id]
                chunk_text = (row.get("chunk_text") or "")[:2000].strip()
                if not chunk_text:
                    continue
                # Best-effort: find the matching StudyChunk so we can return
                # `page_number` / `heading`. Match by data_item_id + content
                # prefix. Falls through to a synthetic source if no match.
                study_chunk = (
                    db.query(StudyChunk)
                    .filter(
                        StudyChunk.asset_id == asset.id,
                        StudyChunk.content.startswith(chunk_text[:64]),
                    )
                    .first()
                )
                source: dict[str, Any] = {
                    "type": "chunk",
                    "asset_id": str(asset.id),
                    "asset_title": asset.title or "Untitled",
                    "data_item_id": str(asset.data_item_id)
                    if asset.data_item_id
                    else None,
                    "score": score,
                }
                if study_chunk is not None:
                    if study_chunk.id in used_chunk_ids:
                        continue
                    used_chunk_ids.add(study_chunk.id)
                    source.update(
                        {
                            "id": study_chunk.id,
                            "chunk_id": study_chunk.id,
                            "title": study_chunk.heading
                            or f"Chunk {study_chunk.chunk_index}",
                            "heading": study_chunk.heading,
                            "page_number": study_chunk.page_number,
                        }
                    )
                else:
                    source.update(
                        {
                            "id": str(row.get("id") or ""),
                            "chunk_id": None,
                            "title": asset.title or "Untitled",
                            "heading": None,
                            "page_number": None,
                        }
                    )
                sources.append(source)
                heading_prefix = (
                    f"{source['asset_title']}"
                    + (
                        f" · p.{source['page_number']}"
                        if source.get("page_number")
                        else ""
                    )
                    + (
                        f" — {source['heading']}"
                        if source.get("heading")
                        else ""
                    )
                )
                chunk_blocks.append(f"[{heading_prefix}]\n{chunk_text}")
                if len(sources) >= max_chunks:
                    break
        except Exception:  # noqa: BLE001
            logger.debug(
                "Embedding search failed for notebook %s; falling back",
                notebook_id,
                exc_info=True,
            )

    if not sources:
        # Embedding fallback: take first chunks from each indexed asset.
        per_asset = max(1, max_chunks // max(1, len(assets)))
        for asset in assets:
            if asset.status != "indexed":
                continue
            chunks = (
                db.query(StudyChunk)
                .filter(StudyChunk.asset_id == asset.id)
                .order_by(StudyChunk.chunk_index.asc())
                .limit(per_asset)
                .all()
            )
            for chunk in chunks:
                if chunk.id in used_chunk_ids:
                    continue
                used_chunk_ids.add(chunk.id)
                sources.append(
                    {
                        "type": "chunk",
                        "id": chunk.id,
                        "chunk_id": chunk.id,
                        "asset_id": str(asset.id),
                        "asset_title": asset.title or "Untitled",
                        "data_item_id": str(asset.data_item_id)
                        if asset.data_item_id
                        else None,
                        "title": chunk.heading or f"Chunk {chunk.chunk_index}",
                        "heading": chunk.heading,
                        "page_number": chunk.page_number,
                    }
                )
                chunk_blocks.append(
                    f"[{asset.title or 'Untitled'}"
                    + (f" · p.{chunk.page_number}" if chunk.page_number else "")
                    + (f" — {chunk.heading}" if chunk.heading else "")
                    + f"]\n{(chunk.content or '')[:2000]}"
                )
                if len(sources) >= max_chunks:
                    break
            if len(sources) >= max_chunks:
                break

    chunks_text = "\n\n---\n\n".join(chunk_blocks)
    system = (
        "You are helping a user study the references in their notebook. "
        "Multiple documents are available below — cite the specific document "
        "and page when answering. Be concise.\n\n"
        f"CHUNKS:\n{chunks_text}\n\n"
        f"USER QUESTION: {query}"
    )
    return ({"system_prompt": system}, sources)
