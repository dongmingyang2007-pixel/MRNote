"""Retrieval Orchestration — multi-layer context assembly for AI requests.

When a user asks a question in the notebook AI, the system should not only
look at the current page text.  It should assemble context from multiple
layers (spec §8.3 — 6 layers):

1. **Page current text / Selected context** — the literal editor viewport
2. **memory/search hits** — semantically relevant long-term memories
3. **memory/search/explain** — reasoning-layer hits (playbooks, evidence
   trails, layered retrieval trace) via ``memory_context.explain_project_memory_hits_v2``
4. **Related pages** — other pages in the same notebook that may be relevant
5. **Document chunks** — chunks from uploaded study assets / files
6. **Page history** — recent ``NotebookPageVersion`` snapshots on the current
   page (so the assistant has a sense of what changed)

Each layer is retrieved independently, scored, and assembled into a
structured system prompt with clear section delimiters.  A token budget
controls the total context size. Callers can pass a ``scope`` to restrict
which layers the retriever consults; the defaults are the spec §8.2 rules.

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
        scope=["page", "notebook", "user_memory"],
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
MEMORY_EXPLAIN_LIMIT = 5
RELATED_PAGES_LIMIT = 3
DOCUMENT_CHUNKS_LIMIT = 5
PAGE_HISTORY_LIMIT = 3


# ---------------------------------------------------------------------------
# Output types
# ---------------------------------------------------------------------------


@dataclass
class RetrievalSource:
    """A single referenced source for citation in the AI response."""

    source_type: str  # "memory" | "memory_explain" | "page" | "document_chunk" | "page_history"
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
    memory_explain_hits: list[dict[str, Any]] = field(default_factory=list)
    related_pages: list[dict[str, Any]] = field(default_factory=list)
    document_chunks: list[dict[str, Any]] = field(default_factory=list)
    page_history: list[dict[str, Any]] = field(default_factory=list)
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
# Layer 2 (new): memory/search/explain — reasoning-layer hits
# ---------------------------------------------------------------------------


async def _retrieve_memory_explain(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    user_id: str,
    query: str,
    limit: int = MEMORY_EXPLAIN_LIMIT,
) -> list[dict[str, Any]]:
    """Retrieve explain-layer reasoning hits (playbooks, views, evidence trails).

    Wraps ``memory_context.explain_project_memory_hits_v2`` with a read-only
    call path — we don't build any full context here, just fetch the hits
    list that feeds into the assembled prompt.
    """
    try:
        from app.services.memory_context import explain_project_memory_hits_v2
        explained = await explain_project_memory_hits_v2(
            db,
            workspace_id=workspace_id,
            project_id=project_id,
            conversation_id=None,
            conversation_created_by=user_id,
            query=query,
            top_k=limit,
        )
        hits = explained.get("hits") if isinstance(explained, dict) else []
        if not isinstance(hits, list):
            return []
        return hits[:limit]
    except Exception:
        logger.debug("memory/search/explain retrieval failed", exc_info=True)
        return []


# ---------------------------------------------------------------------------
# Layer 3: Related pages in the same notebook
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
# Layer 4: Document chunks (study assets)
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
# Layer 5 (new): Page history — recent snapshots on the current page
# ---------------------------------------------------------------------------


async def _retrieve_page_history(
    db: Session,
    *,
    page_id: str | None,
    limit: int = PAGE_HISTORY_LIMIT,
) -> list[dict[str, Any]]:
    """Return the N most recent ``NotebookPageVersion`` snapshots.

    We intentionally pick from the tail so the assistant sees the user's
    short-term trajectory rather than getting flooded with old autosaves.
    """
    if not page_id:
        return []
    try:
        from app.models import NotebookPageVersion
        versions = (
            db.query(NotebookPageVersion)
            .filter(NotebookPageVersion.page_id == page_id)
            .order_by(NotebookPageVersion.version_no.desc())
            .limit(limit)
            .all()
        )
        out: list[dict[str, Any]] = []
        for v in versions:
            summary = (v.snapshot_text or "")[:400]
            if not summary.strip():
                continue
            out.append({
                "version_id": str(v.id),
                "version_no": int(v.version_no),
                "source": v.source,
                "summary": summary,
                "created_at": v.created_at.isoformat() if v.created_at else None,
            })
        return out
    except Exception:
        logger.debug("Page history retrieval failed", exc_info=True)
        return []


# ---------------------------------------------------------------------------
# Context assembly
# ---------------------------------------------------------------------------


def _build_system_prompt(
    *,
    page_text: str,
    selected_text: str,
    memory_hits: list[dict[str, Any]],
    memory_explain_hits: list[dict[str, Any]],
    related_pages: list[dict[str, Any]],
    document_chunks: list[dict[str, Any]],
    page_history: list[dict[str, Any]],
    token_budget: int = DEFAULT_TOKEN_BUDGET,
) -> tuple[str, list[RetrievalSource]]:
    """Assemble a structured system prompt from all retrieval layers.

    Budget allocation (matches the spec-ish §8.3 priorities):
      selection + current page → shares the remainder (highest priority)
      memory search hits       → 30% of budget
      memory explain hits      → 15%
      document chunks          → 25%
      related pages            → 15%
      page history             → 10%

    Any layer that comes in under its allocation returns leftover to the
    selection+page block.
    """
    sources: list[RetrievalSource] = []
    parts: list[str] = []

    # Base instruction (unmetered — tiny).
    base = (
        "你是用户笔记编辑器中的AI助手。你可以帮助用户写作、编程、解释概念、头脑风暴等。\n"
        "你能访问用户的长期记忆、相关页面和上传的资料。请根据这些上下文给出有帮助的回答。\n"
        "如果你使用了记忆或资料中的信息，请在回答中简要标注来源。"
    )
    parts.append(base)
    allocated = max(0, token_budget - len(base))

    memory_budget = int(allocated * 0.30)
    explain_budget = int(allocated * 0.15)
    chunks_budget = int(allocated * 0.25)
    related_budget = int(allocated * 0.15)
    history_budget = int(allocated * 0.10)

    # Layer 1: Current page (soaks up whatever remains after fixed shares)
    primary_budget = allocated - (
        memory_budget + explain_budget + chunks_budget + related_budget + history_budget
    )
    primary_budget = max(primary_budget, 500)

    if page_text.strip():
        truncated_page = page_text[:min(len(page_text), primary_budget // 2)]
        section = f"\n\n[当前页面内容]\n{truncated_page}"
        parts.append(section)
        primary_budget -= len(section)

    # Layer 1b: Selected text
    if selected_text.strip() and primary_budget > 100:
        truncated_selection = selected_text[:min(2000, max(100, primary_budget - 50))]
        section = f"\n\n[用户选中的内容]\n{truncated_selection}"
        parts.append(section)

    # Layer 2: Memory search hits
    if memory_hits and memory_budget > 200:
        memory_lines = []
        remaining = memory_budget
        for hit in memory_hits:
            content = str(hit.get("content") or hit.get("chunk_text") or "").strip()
            category = str(hit.get("category") or "").strip()
            if not content:
                continue
            line = f"- [{category}] {content}" if category else f"- {content}"
            if len(line) > remaining:
                break
            memory_lines.append(line)
            remaining -= len(line)
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

    # Layer 3 (new): memory/explain hits — reasoning-layer evidence
    if memory_explain_hits and explain_budget > 200:
        explain_lines = []
        remaining = explain_budget
        for hit in memory_explain_hits:
            content = str(
                hit.get("content")
                or hit.get("excerpt")
                or hit.get("chunk_text")
                or hit.get("quote_text")
                or ""
            ).strip()
            if not content:
                continue
            result_type = str(hit.get("result_type") or "memory")
            prefix = {
                "memory": "记忆",
                "view": "操作手册",
                "evidence": "证据",
            }.get(result_type, "推理")
            line = f"- [{prefix}] {content[:300]}"
            if len(line) > remaining:
                break
            explain_lines.append(line)
            remaining -= len(line)
            hit_id = (
                hit.get("memory_id")
                or hit.get("view_id")
                or hit.get("evidence_id")
                or hit.get("id")
                or ""
            )
            sources.append(RetrievalSource(
                source_type="memory_explain",
                source_id=str(hit_id),
                title=prefix,
                snippet=content[:100],
                score=float(hit.get("score") or 0),
            ))
        if explain_lines:
            section = "\n\n[记忆推理层]\n以下是与用户问题相关的推理/证据轨迹：\n" + "\n".join(explain_lines)
            parts.append(section)

    # Layer 4: Related pages
    if related_pages and related_budget > 200:
        page_lines = []
        remaining = related_budget
        for p in related_pages:
            title = p.get("title", "Untitled")
            snippet = str(p.get("snippet") or "").strip()[:200]
            if not snippet:
                continue
            line = f"- 《{title}》: {snippet}"
            if len(line) > remaining:
                break
            page_lines.append(line)
            remaining -= len(line)
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

    # Layer 5: Document chunks
    if document_chunks and chunks_budget > 200:
        chunk_lines = []
        remaining = chunks_budget
        for chunk in document_chunks:
            text = str(chunk.get("chunk_text") or "").strip()[:300]
            if not text:
                continue
            line = f"- {text}"
            if len(line) > remaining:
                break
            chunk_lines.append(line)
            remaining -= len(line)
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

    # Layer 6 (new): Page history — short-term trajectory on this page
    if page_history and history_budget > 100:
        history_lines = []
        remaining = history_budget
        for h in page_history:
            summary = str(h.get("summary") or "").strip()[:240]
            if not summary:
                continue
            version_no = h.get("version_no")
            line = f"- v{version_no}: {summary}"
            if len(line) > remaining:
                break
            history_lines.append(line)
            remaining -= len(line)
            sources.append(RetrievalSource(
                source_type="page_history",
                source_id=str(h.get("version_id") or ""),
                title=f"v{version_no}",
                snippet=summary[:100],
                score=0.0,
            ))
        if history_lines:
            section = "\n\n[该页面的最近快照]\n以下是该页面最近的若干修改快照：\n" + "\n".join(history_lines)
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
    scope: list[str] | None = None,
) -> RetrievalContext:
    """Assemble multi-layer retrieval context for a notebook AI request.

    Retrieves from (spec §8.3):
    1. Current page text (passed in directly)
    2. Memory search hits (semantic similarity against knowledge graph)
    3. Memory/search/explain (reasoning-layer hits)
    4. Related pages in the same notebook (keyword overlap)
    5. Document chunks from uploaded study assets (semantic similarity)
    6. Recent NotebookPageVersion snapshots for this page

    ``scope`` gates which layers are even consulted. When not provided,
    every layer runs (the legacy behaviour). Known scope values per spec
    §8.1: ``selection / page / notebook / project / user_memory /
    study_asset / web``. Mapping used here:

    - ``user_memory`` present → memory + memory_explain layers
    - ``notebook`` or ``project`` present → related pages
    - ``study_asset`` present → document chunks
    - ``page`` present → page history
    - ``web`` present → TODO, currently no-op
    """
    run_memory = scope is None or "user_memory" in scope
    run_explain = run_memory
    run_related = scope is None or any(s in scope for s in ("notebook", "project"))
    run_chunks = scope is None or "study_asset" in scope
    run_history = scope is None or "page" in scope or "selection" in scope

    if run_memory:
        memory_hits = await _retrieve_memory_hits(
            db,
            workspace_id=workspace_id,
            project_id=project_id,
            user_id=user_id,
            query=query,
        )
    else:
        memory_hits = []

    if run_explain:
        memory_explain_hits = await _retrieve_memory_explain(
            db,
            workspace_id=workspace_id,
            project_id=project_id,
            user_id=user_id,
            query=query,
        )
    else:
        memory_explain_hits = []

    if run_related:
        related_pages = await _retrieve_related_pages(
            db,
            workspace_id=workspace_id,
            project_id=project_id,
            notebook_id=notebook_id,
            query=query,
            current_page_id=page_id,
        )
    else:
        related_pages = []

    if run_chunks:
        document_chunks = await _retrieve_document_chunks(
            db,
            workspace_id=workspace_id,
            project_id=project_id,
            query=query,
        )
    else:
        document_chunks = []

    if run_history:
        page_history = await _retrieve_page_history(
            db,
            page_id=page_id,
        )
    else:
        page_history = []

    system_prompt, sources = _build_system_prompt(
        page_text=page_text,
        selected_text=selected_text,
        memory_hits=memory_hits,
        memory_explain_hits=memory_explain_hits,
        related_pages=related_pages,
        document_chunks=document_chunks,
        page_history=page_history,
        token_budget=token_budget,
    )

    return RetrievalContext(
        system_prompt=system_prompt,
        sources=sources,
        memory_hits=memory_hits,
        memory_explain_hits=memory_explain_hits,
        related_pages=related_pages,
        document_chunks=document_chunks,
        page_history=page_history,
        token_estimate=len(system_prompt),
    )
