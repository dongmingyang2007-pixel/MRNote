"""Retrieval Orchestration — multi-layer context assembly for AI requests.

When a user asks a question in the notebook AI, the system should not only
look at the current page text.  It should assemble context from multiple
layers:

1. **Page context** — current page full text + selected text
2. **Memory search** — semantically relevant memories from the user's
   long-term knowledge graph
3. **Related pages** — other pages in the same notebook that may be relevant
4. **Document chunks** — chunks from uploaded study assets / files

Each layer is retrieved independently, scored, and assembled into a
structured system prompt with clear section delimiters.  A token budget
controls the total context size.

Usage::

    context = await assemble_context(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        user_id=user_id,
        query=user_message,
        page_text=page.plain_text,
        selected_text=context_text,
        notebook_id=notebook_id,
    )
    # context.system_prompt contains the assembled context
    # context.sources lists all referenced sources for citation
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_TOKEN_BUDGET = 4000  # approximate char budget (~tokens * 2 for Chinese)
MEMORY_HITS_LIMIT = 8
RELATED_PAGES_LIMIT = 3
DOCUMENT_CHUNKS_LIMIT = 5


# ---------------------------------------------------------------------------
# Output types
# ---------------------------------------------------------------------------


@dataclass
class RetrievalSource:
    """A single referenced source for citation in the AI response."""

    source_type: str  # "memory" | "page" | "document_chunk"
    source_id: str
    title: str
    snippet: str
    score: float = 0.0


@dataclass
class RetrievalContext:
    """Assembled multi-layer context ready for the AI model."""

    system_prompt: str
    sources: list[RetrievalSource] = field(default_factory=list)
    memory_hits: list[dict[str, Any]] = field(default_factory=list)
    related_pages: list[dict[str, Any]] = field(default_factory=list)
    document_chunks: list[dict[str, Any]] = field(default_factory=list)
    token_estimate: int = 0


# ---------------------------------------------------------------------------
# Layer 1: Memory search
# ---------------------------------------------------------------------------


async def _retrieve_memory_hits(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    user_id: str,
    query: str,
    limit: int = MEMORY_HITS_LIMIT,
) -> list[dict[str, Any]]:
    """Retrieve semantically relevant memories from the knowledge graph."""
    try:
        from app.services.embedding import search_similar

        results = await search_similar(
            db,
            workspace_id=workspace_id,
            project_id=project_id,
            query=query,
            limit=limit * 2,  # fetch more, then filter
        )

        # Filter to only memories (not data items) with sufficient score
        memory_hits = []
        for result in results:
            if not result.get("memory_id"):
                continue
            score = float(result.get("score") or 0)
            if score < 0.3:
                continue
            memory_hits.append(result)
            if len(memory_hits) >= limit:
                break

        # Enrich with memory content from DB
        if memory_hits:
            from app.models import Memory

            memory_ids = [h["memory_id"] for h in memory_hits]
            memories = (
                db.query(Memory)
                .filter(Memory.id.in_(memory_ids))
                .all()
            )
            mem_map = {m.id: m for m in memories}
            for hit in memory_hits:
                mem = mem_map.get(hit["memory_id"])
                if mem:
                    hit["content"] = mem.content
                    hit["category"] = mem.category
                    hit["memory_type"] = mem.type

        return memory_hits
    except Exception:
        logger.debug("Memory search failed for retrieval orchestration", exc_info=True)
        return []


# ---------------------------------------------------------------------------
# Layer 2: Related pages in the same notebook
# ---------------------------------------------------------------------------


async def _retrieve_related_pages(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    notebook_id: str | None,
    query: str,
    current_page_id: str | None = None,
    limit: int = RELATED_PAGES_LIMIT,
) -> list[dict[str, Any]]:
    """Find other pages in the same notebook that are relevant to the query."""
    if not notebook_id:
        return []

    try:
        from app.models import NotebookPage

        # Simple approach: search pages by plain_text trigram similarity
        # TODO: upgrade to semantic search when page embeddings are available
        pages = (
            db.query(NotebookPage)
            .filter(
                NotebookPage.notebook_id == notebook_id,
                NotebookPage.is_archived == False,  # noqa: E712
            )
            .order_by(NotebookPage.last_edited_at.desc())
            .limit(20)
            .all()
        )

        # Score by keyword overlap
        query_lower = query.lower()
        scored_pages = []
        for page in pages:
            if current_page_id and str(page.id) == str(current_page_id):
                continue
            plain = (page.plain_text or "").lower()
            title = (page.title or "").lower()
            if not plain and not title:
                continue

            # Simple relevance score: keyword overlap
            score = 0.0
            query_words = set(query_lower.split())
            for word in query_words:
                if len(word) < 2:
                    continue
                if word in title:
                    score += 2.0
                if word in plain[:500]:
                    score += 1.0

            if score > 0:
                scored_pages.append({
                    "page_id": str(page.id),
                    "title": page.title or "Untitled",
                    "snippet": (page.plain_text or "")[:300],
                    "score": score,
                })

        scored_pages.sort(key=lambda p: p["score"], reverse=True)
        return scored_pages[:limit]
    except Exception:
        logger.debug("Related page search failed", exc_info=True)
        return []


# ---------------------------------------------------------------------------
# Layer 3: Document chunks (study assets)
# ---------------------------------------------------------------------------


async def _retrieve_document_chunks(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    query: str,
    limit: int = DOCUMENT_CHUNKS_LIMIT,
) -> list[dict[str, Any]]:
    """Retrieve relevant chunks from uploaded documents / study assets."""
    try:
        from app.services.embedding import search_similar

        results = await search_similar(
            db,
            workspace_id=workspace_id,
            project_id=project_id,
            query=query,
            limit=limit * 2,
        )

        # Filter to only data_item results (not memories)
        doc_chunks = []
        for result in results:
            if not result.get("data_item_id"):
                continue
            score = float(result.get("score") or 0)
            if score < 0.3:
                continue
            doc_chunks.append({
                "chunk_id": result.get("id"),
                "data_item_id": result["data_item_id"],
                "chunk_text": result.get("chunk_text", ""),
                "score": score,
            })
            if len(doc_chunks) >= limit:
                break

        return doc_chunks
    except Exception:
        logger.debug("Document chunk search failed", exc_info=True)
        return []


# ---------------------------------------------------------------------------
# Context assembly
# ---------------------------------------------------------------------------


def _build_system_prompt(
    *,
    page_text: str,
    selected_text: str,
    memory_hits: list[dict[str, Any]],
    related_pages: list[dict[str, Any]],
    document_chunks: list[dict[str, Any]],
    token_budget: int = DEFAULT_TOKEN_BUDGET,
) -> tuple[str, list[RetrievalSource]]:
    """Assemble a structured system prompt from all retrieval layers."""
    sources: list[RetrievalSource] = []
    parts: list[str] = []
    budget_remaining = token_budget

    # Base instruction
    base = (
        "你是用户笔记编辑器中的AI助手。你可以帮助用户写作、编程、解释概念、头脑风暴等。\n"
        "你能访问用户的长期记忆、相关页面和上传的资料。请根据这些上下文给出有帮助的回答。\n"
        "如果你使用了记忆或资料中的信息，请在回答中简要标注来源。"
    )
    parts.append(base)
    budget_remaining -= len(base)

    # Layer 1: Current page
    if page_text.strip():
        truncated_page = page_text[:min(len(page_text), budget_remaining // 2)]
        section = f"\n\n[当前页面内容]\n{truncated_page}"
        parts.append(section)
        budget_remaining -= len(section)

    # Layer 1b: Selected text
    if selected_text.strip() and budget_remaining > 100:
        truncated_selection = selected_text[:min(2000, max(100, budget_remaining - 50))]
        section = f"\n\n[用户选中的内容]\n{truncated_selection}"
        parts.append(section)
        budget_remaining -= len(section)

    # Layer 2: Memory hits
    if memory_hits and budget_remaining > 200:
        memory_lines = []
        for hit in memory_hits:
            content = str(hit.get("content") or hit.get("chunk_text") or "").strip()
            category = str(hit.get("category") or "").strip()
            if not content:
                continue
            line = f"- [{category}] {content}" if category else f"- {content}"
            if len(line) > budget_remaining:
                break
            memory_lines.append(line)
            budget_remaining -= len(line)
            sources.append(RetrievalSource(
                source_type="memory",
                source_id=str(hit.get("memory_id") or ""),
                title=category or "记忆",
                snippet=content[:100],
                score=float(hit.get("score") or 0),
            ))

        if memory_lines:
            section = "\n\n[用户的长期记忆]\n以下是与用户问题相关的长期记忆：\n" + "\n".join(memory_lines)
            parts.append(section)

    # Layer 3: Related pages
    if related_pages and budget_remaining > 200:
        page_lines = []
        for p in related_pages:
            title = p.get("title", "Untitled")
            snippet = str(p.get("snippet") or "").strip()[:200]
            if not snippet:
                continue
            line = f"- 《{title}》: {snippet}"
            if len(line) > budget_remaining:
                break
            page_lines.append(line)
            budget_remaining -= len(line)
            sources.append(RetrievalSource(
                source_type="page",
                source_id=str(p.get("page_id") or ""),
                title=title,
                snippet=snippet[:100],
                score=float(p.get("score") or 0),
            ))

        if page_lines:
            section = "\n\n[相关笔记页面]\n以下是同一笔记本中的相关页面：\n" + "\n".join(page_lines)
            parts.append(section)

    # Layer 4: Document chunks
    if document_chunks and budget_remaining > 200:
        chunk_lines = []
        for chunk in document_chunks:
            text = str(chunk.get("chunk_text") or "").strip()[:300]
            if not text:
                continue
            line = f"- {text}"
            if len(line) > budget_remaining:
                break
            chunk_lines.append(line)
            budget_remaining -= len(line)
            sources.append(RetrievalSource(
                source_type="document_chunk",
                source_id=str(chunk.get("data_item_id") or ""),
                title="上传资料",
                snippet=text[:100],
                score=float(chunk.get("score") or 0),
            ))

        if chunk_lines:
            section = "\n\n[上传的资料/文件]\n以下是用户上传的相关资料片段：\n" + "\n".join(chunk_lines)
            parts.append(section)

    system_prompt = "".join(parts)
    return system_prompt, sources


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def assemble_context(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    user_id: str,
    query: str,
    page_text: str = "",
    selected_text: str = "",
    notebook_id: str | None = None,
    page_id: str | None = None,
    token_budget: int = DEFAULT_TOKEN_BUDGET,
) -> RetrievalContext:
    """Assemble multi-layer retrieval context for a notebook AI request.

    Retrieves from:
    1. Current page text (passed in directly)
    2. Memory search hits (semantic similarity against knowledge graph)
    3. Related pages in the same notebook (keyword overlap)
    4. Document chunks from uploaded study assets (semantic similarity)

    Returns a ``RetrievalContext`` with a ready-to-use system prompt and
    source attribution list.
    """
    # Run retrievals in parallel-ish (sequential for now, can be made concurrent)
    memory_hits = await _retrieve_memory_hits(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        user_id=user_id,
        query=query,
    )

    related_pages = await _retrieve_related_pages(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        notebook_id=notebook_id,
        query=query,
        current_page_id=page_id,
    )

    document_chunks = await _retrieve_document_chunks(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        query=query,
    )

    system_prompt, sources = _build_system_prompt(
        page_text=page_text,
        selected_text=selected_text,
        memory_hits=memory_hits,
        related_pages=related_pages,
        document_chunks=document_chunks,
        token_budget=token_budget,
    )

    return RetrievalContext(
        system_prompt=system_prompt,
        sources=sources,
        memory_hits=memory_hits,
        related_pages=related_pages,
        document_chunks=document_chunks,
        token_estimate=len(system_prompt),
    )
