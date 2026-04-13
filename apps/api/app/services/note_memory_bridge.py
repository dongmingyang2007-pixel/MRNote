"""Bridge between notebook pages and the Memory V3 system.

Extracts facts/preferences/goals from page content and creates
MemoryWriteRun + MemoryWriteItem records, following the same
pattern as chat message memory extraction.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    Memory,
    MemoryEvidence,
    MemoryWriteItem,
    MemoryWriteRun,
    Notebook,
    NotebookPage,
)
from app.services.dashscope_client import chat_completion

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """\
你是一个记忆抽取引擎。请从以下笔记内容中提取用户的关键信息。

提取规则：
1. 只提取明确的事实、偏好、目标、观点，不要猜测
2. 每条记忆必须是独立的、可理解的
3. 标注类别和重要程度

请以 JSON 数组返回，每项格式：
{{"fact": "...", "category": "fact|preference|goal|project|concept|relationship|procedure|insight", "importance": "high|medium|low"}}

如果没有可提取的内容，返回空数组 []。

--- 笔记标题 ---
{title}

--- 笔记内容 ---
{content}
"""

# Map importance labels from LLM to numeric values for the float column.
_IMPORTANCE_MAP: dict[str, float] = {
    "high": 0.9,
    "medium": 0.5,
    "low": 0.2,
}


async def extract_memory_candidates(
    db: Session,
    *,
    page_id: str,
    workspace_id: str,
    user_id: str,
) -> tuple[MemoryWriteRun | None, list[MemoryWriteItem]]:
    """Extract memory candidates from a notebook page.

    Returns the write run and list of extracted items.
    """
    page = db.query(NotebookPage).filter(NotebookPage.id == page_id).first()
    if not page or not page.plain_text.strip():
        return None, []

    notebook = db.query(Notebook).filter(
        Notebook.id == page.notebook_id,
        Notebook.workspace_id == workspace_id,
    ).first()
    if not notebook:
        return None, []

    project_id = notebook.project_id
    if not project_id:
        return None, []

    # Create a write run record.
    # MemoryWriteRun has conversation_id / message_id for chat-originated runs;
    # for notebook-originated runs we leave those NULL and store source info in
    # metadata_json instead.
    run = MemoryWriteRun(
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_id=None,
        message_id=None,
        status="running",
        extraction_model=settings.memory_triage_model or settings.dashscope_model,
        started_at=datetime.now(timezone.utc),
        metadata_json={
            "source_type": "notebook_page",
            "source_id": page_id,
            "page_title": page.title or "Untitled",
        },
    )
    db.add(run)
    db.flush()

    try:
        prompt = EXTRACTION_PROMPT.format(
            title=page.title or "Untitled",
            content=page.plain_text[:6000],
        )

        raw = await chat_completion(
            messages=[{"role": "user", "content": prompt}],
            model=settings.memory_triage_model or settings.dashscope_model,
            temperature=0.3,
            max_tokens=2048,
        )

        # Parse JSON from response
        candidates = _parse_candidates(raw)

        items: list[MemoryWriteItem] = []
        for candidate in candidates:
            importance_label = candidate.get("importance", "medium")
            importance_value = _IMPORTANCE_MAP.get(importance_label, 0.5)

            item = MemoryWriteItem(
                run_id=run.id,
                candidate_text=candidate.get("fact", ""),
                category=candidate.get("category", "fact"),
                importance=importance_value,
                decision="pending",
                metadata_json={
                    "source_type": "notebook_page",
                    "source_id": page_id,
                    "importance_label": importance_label,
                },
            )
            db.add(item)
            items.append(item)

        run.status = "completed"
        run.completed_at = datetime.now(timezone.utc)
        db.commit()
        return run, items

    except Exception as exc:
        logger.exception("Memory extraction failed for page %s: %s", page_id, exc)
        run.status = "failed"
        run.error = str(exc)[:500]
        db.commit()
        return run, []


def _parse_candidates(raw: str) -> list[dict[str, str]]:
    """Best-effort parse of JSON array from LLM response."""
    text = raw.strip()
    # Find JSON array in response
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1:
        return []
    try:
        arr = json.loads(text[start : end + 1])
        if isinstance(arr, list):
            return [
                item
                for item in arr
                if isinstance(item, dict) and item.get("fact")
            ]
    except json.JSONDecodeError:
        pass
    return []
