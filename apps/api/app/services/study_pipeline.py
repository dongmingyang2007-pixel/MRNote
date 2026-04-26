"""Study asset ingestion pipeline.

Full pipeline: parse source file -> chunk text -> embed chunks -> auto-create
notebook overview page -> extract memories from first N chunks.
"""
from __future__ import annotations

import logging
import math
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Notebook, StudyAsset, StudyChunk
from app.models.entities import NotebookPage
from app.services.document_indexer import build_file_fallback_text, chunk_text, extract_text_from_content
from app.services.embedding import embed_and_store
from app.routers.utils import get_data_item_in_workspace
from app.services.storage import get_s3_client

logger = logging.getLogger(__name__)

# Maximum number of leading chunks to run through the memory pipeline.
_MEMORY_EXTRACT_LIMIT = 5

# Hard cap on bytes the study pipeline will buffer from S3 before giving
# up. Audit V9: even if the upload side is capped at 50MB, MinIO objects
# could be put out-of-band (admin, bucket pollution) and a zip bomb
# attack through a 500MB-declared object would still expand inside
# document_indexer. Enforcing 128MB here gives the V3 per-member /
# per-archive caps a sane outer bound. The +1 lets us detect overflow
# via range semantics.
_STUDY_PIPELINE_MAX_S3_OBJECT_BYTES = 128 * 1024 * 1024


def _build_doc(title: str, paragraphs: list[str]) -> dict[str, object]:
    content: list[dict[str, object]] = [
        {
            "type": "heading",
            "attrs": {"level": 2},
            "content": [{"type": "text", "text": title}],
        }
    ]
    for paragraph in paragraphs:
        if not paragraph.strip():
            continue
        content.append(
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": paragraph}],
            }
        )
    return {"type": "doc", "content": content}


def _upsert_generated_page(
    db: Session,
    *,
    notebook_id: str,
    slug: str,
    title: str,
    content_json: dict[str, object],
    plain_text: str,
    created_by: str,
    parent_page_id: str | None = None,
    preserve_existing_content: bool = False,
) -> NotebookPage:
    page = (
        db.query(NotebookPage)
        .filter(
            NotebookPage.notebook_id == notebook_id,
            NotebookPage.slug == slug,
        )
        .first()
    )
    if page is None:
        page = NotebookPage(
            id=str(uuid4()),
            notebook_id=notebook_id,
            title=title,
            slug=slug,
            page_type="document",
            content_json=content_json,
            plain_text=plain_text,
            parent_page_id=parent_page_id,
            created_by=created_by,
        )
        db.add(page)
        db.flush()
        return page

    page.title = title
    page.parent_page_id = parent_page_id
    if not preserve_existing_content:
        page.content_json = content_json
        page.plain_text = plain_text
    return page


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

    asset = (
        db.query(StudyAsset)
        .filter(StudyAsset.id == asset_id)
        .with_for_update()
        .first()
    )
    if not asset:
        logger.warning("StudyAsset %s not found, skipping ingestion", asset_id)
        return

    notebook = db.get(Notebook, asset.notebook_id)
    if not notebook:
        logger.warning("Notebook %s not found for asset %s", asset.notebook_id, asset_id)
        return
    if str(notebook.workspace_id) != str(workspace_id):
        logger.warning(
            "StudyAsset %s notebook %s is outside workspace %s",
            asset_id,
            asset.notebook_id,
            workspace_id,
        )
        asset.status = "failed"
        db.flush()
        return

    project_id = str(notebook.project_id) if notebook.project_id else None

    # ------------------------------------------------------------------
    # 1. Parse: download file content from MinIO via DataItem
    # ------------------------------------------------------------------
    asset.status = "parsing"
    db.flush()

    full_text = ""
    filename = "untitled.txt"
    source_media_type = "application/octet-stream"
    source_size_bytes = 0
    ingest_mode = "parsed"

    if asset.data_item_id:
        data_item = get_data_item_in_workspace(
            db,
            data_item_id=asset.data_item_id,
            workspace_id=workspace_id,
        )
        if data_item and data_item.object_key:
            filename = data_item.filename or filename
            source_media_type = data_item.media_type or source_media_type
            source_size_bytes = int(data_item.size_bytes or 0)
            try:
                s3 = get_s3_client()
                # V9: request only the first N bytes so an oversized
                # (or malicious) S3 object cannot force the worker to
                # load gigabytes into memory. If the object is larger
                # than the cap, we reject the asset and mark it failed
                # rather than silently truncating.
                get_kwargs: dict[str, object] = {
                    "Bucket": settings.s3_private_bucket,
                    "Key": data_item.object_key,
                    "Range": f"bytes=0-{_STUDY_PIPELINE_MAX_S3_OBJECT_BYTES}",
                }
                response = s3.get_object(**get_kwargs)
                content_bytes: bytes = response["Body"].read(_STUDY_PIPELINE_MAX_S3_OBJECT_BYTES + 1)
                if len(content_bytes) > _STUDY_PIPELINE_MAX_S3_OBJECT_BYTES:
                    logger.warning(
                        "StudyAsset %s object %s exceeds size cap %d",
                        asset_id,
                        data_item.object_key,
                        _STUDY_PIPELINE_MAX_S3_OBJECT_BYTES,
                    )
                    asset.status = "failed"
                    db.flush()
                    return
                full_text = extract_text_from_content(content_bytes, filename)
                if not full_text.strip():
                    full_text = build_file_fallback_text(
                        content_bytes,
                        filename,
                        source_media_type,
                    )
                    ingest_mode = "fallback"
            except Exception:
                logger.exception("Failed to download/parse file for asset %s", asset_id)
                asset.status = "failed"
                db.flush()
                return
        else:
            logger.warning(
                "DataItem %s is unavailable in workspace %s or has no object_key",
                asset.data_item_id,
                workspace_id,
            )
            asset.status = "failed"
            db.flush()
            return

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
    # 5. Auto-create notebook pages (overview / chapter pages / notes page)
    # ------------------------------------------------------------------
    summary_lines = [
        f"Asset: {asset.title}",
        f"Type: {asset.asset_type}",
        f"Source media type: {source_media_type}",
        f"Parse mode: {'fallback summary' if ingest_mode == 'fallback' else 'text extraction'}",
        f"Total chunks: {len(chunks)}",
        f"Characters: {len(full_text)}",
    ]
    if source_size_bytes > 0:
        summary_lines.append(f"Size: {source_size_bytes} bytes")
    target_chapter_pages = min(8, max(1, len(chunk_rows)))
    group_size = max(1, math.ceil(len(chunk_rows) / target_chapter_pages))
    chapter_specs: list[tuple[int, str, str]] = []
    for start in range(0, len(chunk_rows), group_size):
        group = chunk_rows[start:start + group_size]
        chapter_number = len(chapter_specs) + 1
        heading = next((row.heading.strip() for row in group if row.heading.strip()), "")
        chapter_title = (
            f"Chapter {chapter_number}: {heading[:80]}"
            if heading
            else f"Chapter {chapter_number}"
        )
        chapter_text = "\n\n".join(row.content for row in group).strip()
        chapter_specs.append((chapter_number, chapter_title, chapter_text))

    overview_paragraphs = summary_lines + [
        f"Generated chapter pages: {len(chapter_specs)}",
    ]
    overview_paragraphs.extend(
        f"{chapter_number}. {chapter_title}"
        for chapter_number, chapter_title, _ in chapter_specs
    )
    overview_text = "\n".join(overview_paragraphs)
    overview_title = f"{asset.title} - Overview"
    overview_page = _upsert_generated_page(
        db,
        notebook_id=asset.notebook_id,
        slug=f"study-asset-{asset_id}-overview",
        title=overview_title,
        content_json=_build_doc(overview_title, overview_paragraphs),
        plain_text=overview_text,
        created_by=user_id,
    )

    chapter_page_ids: list[str] = []
    expected_chapter_slugs: set[str] = set()
    for chapter_number, chapter_title, chapter_text in chapter_specs:
        chapter_slug = f"study-asset-{asset_id}-chapter-{chapter_number}"
        expected_chapter_slugs.add(chapter_slug)
        chapter_page = _upsert_generated_page(
            db,
            notebook_id=asset.notebook_id,
            slug=chapter_slug,
            title=f"{asset.title} - {chapter_title}",
            content_json=_build_doc(
                f"{asset.title} - {chapter_title}",
                [chapter_text],
            ),
            plain_text=chapter_text,
            created_by=user_id,
            parent_page_id=overview_page.id,
        )
        chapter_page_ids.append(str(chapter_page.id))

    stale_chapter_pages = (
        db.query(NotebookPage)
        .filter(
            NotebookPage.notebook_id == asset.notebook_id,
            NotebookPage.slug.like(f"study-asset-{asset_id}-chapter-%"),
        )
        .all()
    )
    for stale_page in stale_chapter_pages:
        if stale_page.slug not in expected_chapter_slugs:
            db.delete(stale_page)

    notes_title = f"{asset.title} - Notes"
    notes_seed = "\n".join(
        [
            "What stands out?",
            "Questions to ask the AI:",
            "Connections to long-term memory:",
        ]
    )
    notes_page = _upsert_generated_page(
        db,
        notebook_id=asset.notebook_id,
        slug=f"study-asset-{asset_id}-notes",
        title=notes_title,
        content_json=_build_doc(notes_title, notes_seed.split("\n")),
        plain_text=notes_seed,
        created_by=user_id,
        parent_page_id=overview_page.id,
        preserve_existing_content=True,
    )
    asset.metadata_json = {
        **(asset.metadata_json or {}),
        "overview_page_id": str(overview_page.id),
        "notes_page_id": str(notes_page.id),
        "chapter_page_ids": chapter_page_ids,
        "ingest_mode": ingest_mode,
        "source_filename": filename,
        "source_media_type": source_media_type,
        "source_size_bytes": source_size_bytes,
    }
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
