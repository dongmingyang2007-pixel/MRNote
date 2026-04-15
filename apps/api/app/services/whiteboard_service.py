"""Whiteboard content summarization and memory extraction.

Converts Excalidraw whiteboard elements to a text description via LLM,
then feeds the description through UnifiedMemoryPipeline for memory
extraction and promotion.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.services import dashscope_client
from app.services.unified_memory_pipeline import (
    PipelineInput,
    PipelineResult,
    SourceContext,
    run_pipeline,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# Excalidraw element types that carry user-visible text.
_TEXT_ELEMENT_TYPE = "text"

# Minimum total text length required to justify an LLM summarization call.
_MIN_TEXT_LENGTH_FOR_LLM = 20

# Minimum summary length to proceed with memory extraction.
_MIN_SUMMARY_LENGTH = 10


def _extract_elements_description(elements: list[dict[str, Any]]) -> str:
    """Build a structured plaintext description from Excalidraw elements.

    Extracts text content and shape types so the LLM has a concise
    representation of what the whiteboard contains.
    """
    text_items: list[str] = []
    shape_items: list[str] = []

    for el in elements:
        if not isinstance(el, dict):
            continue
        # Skip deleted elements.
        if el.get("isDeleted"):
            continue

        el_type = el.get("type", "")

        if el_type == _TEXT_ELEMENT_TYPE:
            text = (el.get("text") or "").strip()
            if text:
                text_items.append(text)
        else:
            # Record non-text shapes with their labels (if any).
            label = (el.get("text") or "").strip()
            if label:
                shape_items.append(f"{el_type}[{label}]")
            else:
                shape_items.append(el_type)

    parts: list[str] = []
    if text_items:
        parts.append("文字内容:\n" + "\n".join(f"- {t}" for t in text_items))
    if shape_items:
        parts.append("图形元素:\n" + "\n".join(f"- {s}" for s in shape_items))

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_SUMMARIZE_PROMPT_TEMPLATE = """\
你是白板内容描述器。根据以下白板元素，用一段简洁的文字描述白板上画了什么。

白板元素：
{elements_description}

请用中文描述白板内容，包括：
- 主要概念和关键词
- 元素之间的关系（箭头连接等）
- 文字内容

如果白板是空的或内容极少，返回"空白板"。\
"""


async def summarize_whiteboard(elements_json: list[dict[str, Any]]) -> str:
    """Convert Excalidraw elements to a text description via LLM.

    Takes the Excalidraw elements array (contains shapes, text, arrows,
    etc.) and asks the LLM to describe what the whiteboard depicts.

    Parameters
    ----------
    elements_json:
        The ``elements`` array from an Excalidraw scene.

    Returns
    -------
    str
        A natural-language description of the whiteboard content.
    """
    if not elements_json:
        return ""

    elements_description = _extract_elements_description(elements_json)
    if not elements_description.strip():
        return ""

    # Fast path: if there is not enough text content, just return the raw
    # structural description without calling the LLM.
    total_text = "".join(
        (el.get("text") or "")
        for el in elements_json
        if isinstance(el, dict) and not el.get("isDeleted")
    )
    if len(total_text.strip()) < _MIN_TEXT_LENGTH_FOR_LLM:
        return elements_description

    prompt = _SUMMARIZE_PROMPT_TEMPLATE.format(
        elements_description=elements_description,
    )

    try:
        summary = await dashscope_client.chat_completion(
            [{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=512,
        )
        return summary.strip()
    except Exception:
        logger.exception("LLM whiteboard summarization failed; falling back to raw description")
        return elements_description


async def extract_whiteboard_memories(
    db: Session,
    *,
    page_id: str,
    workspace_id: str,
    project_id: str,
    user_id: str,
    elements_json: list[dict[str, Any]],
) -> dict[str, Any]:
    """Summarize a whiteboard and extract memories via the unified pipeline.

    Parameters
    ----------
    db:
        Active SQLAlchemy session.
    page_id:
        The notebook page ID that holds the whiteboard.
    workspace_id, project_id, user_id:
        Ownership context for the memory pipeline.
    elements_json:
        The Excalidraw ``elements`` array.

    Returns
    -------
    dict
        ``{"summary": str, "pipeline_result": PipelineResult | None}``
    """
    description = await summarize_whiteboard(elements_json)

    if len(description.strip()) < _MIN_SUMMARY_LENGTH:
        return {"summary": description, "pipeline_result": None}

    pipeline_input = PipelineInput(
        source_type="whiteboard",
        source_text=description[:6000],
        source_ref=str(page_id),
        workspace_id=str(workspace_id),
        project_id=str(project_id),
        user_id=str(user_id),
        context=SourceContext(owner_user_id=str(user_id)),
        context_text="whiteboard",
    )

    try:
        result: PipelineResult = await run_pipeline(db, pipeline_input)
    except Exception:
        logger.exception("Unified pipeline failed for whiteboard page %s", page_id)
        return {"summary": description, "pipeline_result": None}

    return {"summary": description, "pipeline_result": result}
