"""Bridge between notebook pages and the Memory V3 system.

Uses the UnifiedMemoryPipeline to run the FULL 12-stage memory extraction
pipeline (extract -> dedup -> triage -> promote -> supersede -> concept-parent ->
evidence -> embedding -> view refresh) on notebook page content.

This replaces the previous weak extraction that only created pending
MemoryWriteItem candidates without triage, embedding, or evidence.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import (
    MemoryWriteItem,
    MemoryWriteRun,
    Notebook,
    NotebookPage,
)
from app.services.unified_memory_pipeline import (
    PipelineInput,
    PipelineResult,
    SourceContext,
    run_pipeline,
)

logger = logging.getLogger(__name__)


@dataclass
class ExtractionResult:
    """Result from notebook memory extraction."""

    run: MemoryWriteRun | None = None
    items: list[MemoryWriteItem] | None = None
    graph_changed: bool = False


async def extract_memory_candidates(
    db: Session,
    *,
    page_id: str,
    workspace_id: str,
    user_id: str,
) -> ExtractionResult:
    """Extract memory candidates from a notebook page.

    Now uses the full UnifiedMemoryPipeline instead of a weak LLM-only
    extraction.  Returns an ExtractionResult with write run, items, and
    graph_changed flag.
    """
    page = db.query(NotebookPage).filter(NotebookPage.id == page_id).first()
    if not page or not (page.plain_text or "").strip():
        return ExtractionResult()

    notebook = db.query(Notebook).filter(
        Notebook.id == page.notebook_id,
        Notebook.workspace_id == workspace_id,
    ).first()
    if not notebook:
        return ExtractionResult()

    project_id = notebook.project_id
    if not project_id:
        return ExtractionResult()

    pipeline_input = PipelineInput(
        source_type="notebook_page",
        source_text=(page.plain_text or "")[:6000],
        source_ref=str(page_id),
        workspace_id=str(workspace_id),
        project_id=str(project_id),
        user_id=str(user_id),
        context=SourceContext(owner_user_id=str(user_id)),
        context_text=page.title or "Untitled",
    )

    try:
        result: PipelineResult = await run_pipeline(db, pipeline_input)
    except Exception:
        logger.exception("Unified pipeline failed for page %s", page_id)
        return ExtractionResult()

    if not result.write_run_id:
        return ExtractionResult(graph_changed=result.graph_changed)

    run = db.get(MemoryWriteRun, result.write_run_id)
    items = (
        db.query(MemoryWriteItem)
        .filter(MemoryWriteItem.run_id == result.write_run_id)
        .all()
    )
    extraction_result = ExtractionResult(run=run, items=list(items), graph_changed=result.graph_changed)

    # S7: schedule embedding regeneration on page save
    try:
        from app.tasks.worker_tasks import regenerate_notebook_page_embedding_task
        regenerate_notebook_page_embedding_task.delay(str(page_id))
    except Exception:
        logger.warning("failed to schedule embedding regeneration for %s",
                       page_id, exc_info=False)

    return extraction_result


def extract_memory_candidates_sync(
    db: Session,
    *,
    page_id: str,
    workspace_id: str,
    user_id: str,
) -> ExtractionResult:
    """Synchronous wrapper for use in Celery tasks."""
    return asyncio.run(
        extract_memory_candidates(
            db,
            page_id=page_id,
            workspace_id=workspace_id,
            user_id=user_id,
        )
    )


async def extract_memory_from_text(
    db: Session,
    *,
    notebook_id: str,
    workspace_id: str,
    user_id: str,
    text: str,
    source_label: str = "",
    source_ref: str = "",
) -> ExtractionResult:
    """Run the memory pipeline against an ad-hoc text snippet.

    Used by PDF/Office reference selection: the user highlights a passage in
    a reference document and asks "extract memory from this". The text isn't
    tied to a notebook page, so we resolve project context from the notebook.
    """
    snippet = (text or "").strip()
    if not snippet:
        return ExtractionResult()

    notebook = db.query(Notebook).filter(
        Notebook.id == notebook_id,
        Notebook.workspace_id == workspace_id,
    ).first()
    if not notebook or not notebook.project_id:
        return ExtractionResult()

    pipeline_input = PipelineInput(
        source_type="notebook_selection",
        source_text=snippet[:6000],
        source_ref=source_ref or str(notebook.id),
        workspace_id=str(workspace_id),
        project_id=str(notebook.project_id),
        user_id=str(user_id),
        context=SourceContext(owner_user_id=str(user_id)),
        context_text=(source_label or notebook.title or "Reference selection")[:200],
    )

    try:
        result: PipelineResult = await run_pipeline(db, pipeline_input)
    except Exception:
        logger.exception(
            "Unified pipeline failed for selection text in notebook %s",
            notebook_id,
        )
        return ExtractionResult()

    if not result.write_run_id:
        return ExtractionResult(graph_changed=result.graph_changed)

    run = db.get(MemoryWriteRun, result.write_run_id)
    items = (
        db.query(MemoryWriteItem)
        .filter(MemoryWriteItem.run_id == result.write_run_id)
        .all()
    )
    return ExtractionResult(
        run=run, items=list(items), graph_changed=result.graph_changed
    )
