"""Study asset ingestion pipeline.

Full pipeline: parse source file -> chunk text -> embed chunks -> auto-create
notebook overview page -> extract memories from first N chunks.
"""
from __future__ import annotations

import logging
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import DataItem, Notebook, StudyAsset, StudyChunk
from app.models.entities import NotebookPage
from app.services.document_indexer import chunk_text, extract_text_from_content
from app.services.embedding import embed_and_store
from app.services.storage import get_s3_client

logger = logging.getLogger(__name__)

# Maximum number of leading chunks to run through the memory pipeline.
_MEMORY_EXTRACT_LIMIT = 5


def _detect_heading(text: str) -> str:
    """Extract the first line as a heading if it looks like one."""
    first_line = text.strip().split("\n", 1)[0].strip()
    if len(first_line) < 120:
        return first_line
    return ""


async def ingest_study_asset(
    db: Session,
    *,
    asset_id: str,
    workspace_id: str,
    user_id: str,
) -> None:
    """Full pipeline: parse -> chunk -> embed -> auto-create pages -> memory extract."""

    asset = db.get(StudyAsset, asset_id)
    if not asset:
        logger.warning("StudyAsset %s not found, skipping ingestion", asset_id)
        return

    notebook = db.get(Notebook, asset.notebook_id)
    if not notebook:
        logger.warning("Notebook %s not found for asset %s", asset.notebook_id, asset_id)
        return

    project_id = str(notebook.project_id) if notebook.project_id else None

    # ------------------------------------------------------------------
    # 1. Parse: download file content from MinIO via DataItem
    # ------------------------------------------------------------------
    asset.status = "parsing"
    db.flush()

    full_text = ""
    filename = "untitled.txt"

    if asset.data_item_id:
        data_item = db.get(DataItem, asset.data_item_id)
        if data_item and data_item.object_key:
            filename = data_item.filename or filename
            try:
                s3 = get_s3_client()
                response = s3.get_object(
                    Bucket=settings.s3_private_bucket,
                    Key=data_item.object_key,
                )
                content_bytes: bytes = response["Body"].read()
                full_text = extract_text_from_content(content_bytes, filename)
            except Exception:
                logger.exception("Failed to download/parse file for asset %s", asset_id)
                asset.status = "failed"
                db.flush()
                return
        else:
            logger.warning("DataItem %s missing or has no object_key", asset.data_item_id)

    if not full_text.strip():
        logger.info("No text extracted for asset %s, marking failed", asset_id)
        asset.status = "failed"
        db.flush()
        return

    # ------------------------------------------------------------------
    # 2. Chunk
    # ------------------------------------------------------------------
    asset.status = "chunked"
    db.flush()

    chunks = chunk_text(full_text, chunk_size=800, overlap=100)
    if not chunks:
        asset.status = "failed"
        db.flush()
        return

    # ------------------------------------------------------------------
    # 3. Create StudyChunk rows (delete old ones first for re-ingest)
    # ------------------------------------------------------------------
    db.query(StudyChunk).filter(StudyChunk.asset_id == asset_id).delete()
    db.flush()

    chunk_rows: list[StudyChunk] = []
    for idx, chunk_content in enumerate(chunks):
        row = StudyChunk(
            id=str(uuid4()),
            asset_id=asset_id,
            chunk_index=idx,
            heading=_detect_heading(chunk_content),
            content=chunk_content,
        )
        db.add(row)
        chunk_rows.append(row)
    db.flush()

    # ------------------------------------------------------------------
    # 4. Embed each chunk
    # ------------------------------------------------------------------
    if project_id and settings.dashscope_api_key:
        for row in chunk_rows:
            try:
                embedding_id = await embed_and_store(
                    db,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    data_item_id=asset.data_item_id,
                    chunk_text=row.content,
                    auto_commit=False,
                )
                row.embedding_id = embedding_id
            except Exception:
                logger.warning("Embedding failed for chunk %s of asset %s", row.chunk_index, asset_id)
        db.flush()

    # ------------------------------------------------------------------
    # 5. Auto-create notebook overview page
    # ------------------------------------------------------------------
    summary_lines = [
        f"Asset: {asset.title}",
        f"Type: {asset.asset_type}",
        f"Total chunks: {len(chunks)}",
        f"Characters: {len(full_text)}",
    ]
    overview_text = "\n".join(summary_lines)

    overview_content = {
        "type": "doc",
        "content": [
            {
                "type": "heading",
                "attrs": {"level": 2},
                "content": [{"type": "text", "text": f"{asset.title} - Overview"}],
            },
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": overview_text}],
            },
        ],
    }

    overview_page = NotebookPage(
        id=str(uuid4()),
        notebook_id=asset.notebook_id,
        title=f"{asset.title} - Overview",
        slug=f"study-overview-{str(uuid4())[:8]}",
        page_type="document",
        content_json=overview_content,
        plain_text=overview_text,
        created_by=user_id,
    )
    db.add(overview_page)
    db.flush()

    # ------------------------------------------------------------------
    # 6. Memory extraction for leading chunks
    # ------------------------------------------------------------------
    if project_id:
        try:
            from app.services.unified_memory_pipeline import (
                PipelineInput,
                SourceContext,
                run_pipeline,
            )

            for row in chunk_rows[:_MEMORY_EXTRACT_LIMIT]:
                await run_pipeline(
                    db,
                    PipelineInput(
                        source_type="book_chapter",
                        source_text=row.content,
                        source_ref=str(row.id),
                        workspace_id=workspace_id,
                        project_id=project_id,
                        user_id=user_id,
                        context=SourceContext(owner_user_id=user_id),
                        context_text=f"Book: {asset.title}, Chunk {row.chunk_index}",
                    ),
                )
        except Exception:
            logger.exception("Memory extraction failed for asset %s (non-fatal)", asset_id)

    # ------------------------------------------------------------------
    # 7. Finalize
    # ------------------------------------------------------------------
    asset.status = "indexed"
    asset.total_chunks = len(chunks)
    db.flush()
    logger.info("Study asset %s ingested: %d chunks", asset_id, len(chunks))
