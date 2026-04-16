"""Assemble a context payload for /ai/study/ask.

Returns (context_dict, sources_list) where:
  context_dict = {
      "system_prompt": str with chunks + notes stitched in,
  }
  sources_list = [{"type": "chunk", "id": "...", "title": "..."}]
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import StudyAsset, StudyChunk


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
        {"type": "chunk", "id": c.id, "title": c.heading or f"Chunk {c.chunk_index}"}
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
