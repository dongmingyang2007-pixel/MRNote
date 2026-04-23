"""Notebook AI action endpoints – selection actions, page actions, and in-editor chat."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from starlette.responses import StreamingResponse

from app.core.config import settings
from app.core.deps import (
    get_current_user,
    get_current_workspace_id,
    get_current_workspace_role,
    get_db_session,
    require_csrf_protection,
    require_workspace_write_access,
)
from app.core.entitlements import require_entitlement
from app.core.errors import ApiError
from app.core.notebook_access import assert_notebook_readable
from app.models import Notebook, NotebookPage, User
from app.services.quota_counters import count_ai_actions_this_month
from app.services.ai_action_logger import action_log_context
from app.services.dashscope_stream import chat_completion_stream

router = APIRouter(prefix="/api/v1/ai/notebook", tags=["notebook-ai"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _get_page_or_404(
    db: Session,
    page_id: str,
    workspace_id: str,
    *,
    current_user_id: str,
    workspace_role: str,
) -> NotebookPage:
    """Load a page and verify the caller may read its notebook.

    The workspace check alone is not enough: same-workspace editors/viewers
    must not bypass a private notebook's `visibility="private" + created_by`
    gate. Use the shared `assert_notebook_readable` so this contract is
    identical to `routers/notebooks.py`.
    """
    page = db.query(NotebookPage).filter(NotebookPage.id == page_id).first()
    if not page:
        raise ApiError("not_found", "Page not found", status_code=404)
    notebook = db.query(Notebook).filter(Notebook.id == page.notebook_id).first()
    assert_notebook_readable(
        notebook,
        workspace_id=workspace_id,
        current_user_id=current_user_id,
        workspace_role=workspace_role,
        not_found_message="Page not found",
    )
    return page


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

SELECTION_ACTION_PROMPTS: dict[str, str] = {
    "rewrite": "请改写以下文本，使其更加清晰流畅。保持原意不变，直接输出改写后的文本，不要添加解释：\n\n{text}",
    "summarize": "请总结以下内容的要点，使用简洁的条目形式：\n\n{text}",
    "expand": "请扩展以下内容，添加更多细节和论述：\n\n{text}",
    "translate_en": "请将以下内容翻译成英文，保持原文的语气和风格：\n\n{text}",
    "translate_zh": "请将以下内容翻译成中文，保持原文的语气和风格：\n\n{text}",
    "explain": "请用通俗易懂的语言解释以下内容：\n\n{text}",
    "fix_grammar": "请修正以下文本中的语法和拼写错误，直接输出修正后的文本：\n\n{text}",
    "to_list": "请将以下内容转换成清晰的列表格式：\n\n{text}",
    "continue": "请基于以下内容继续写作，保持一致的风格和主题：\n\n{text}",
    "explain_code": "请解释以下代码的功能和工作原理：\n\n```\n{text}\n```",
    "explain_formula": "请解释以下数学公式/LaTeX表达式的含义：\n\n{text}",
}

PAGE_ACTION_PROMPTS: dict[str, str] = {
    "summarize": "请总结以下页面内容的要点：\n\n{text}",
    "outline": "请为以下页面内容生成一个结构化大纲：\n\n{text}",
    "find_todos": "请从以下内容中找出所有待办事项和未完成的任务：\n\n{text}",
    "tag": "请为以下内容生成 3-5 个关键标签（以 JSON 数组返回）：\n\n{text}",
    "brainstorm": "请基于以下内容进行头脑风暴，给出 5-8 个相关的想法或方向：\n\n{text}",
}


# ---------------------------------------------------------------------------
# 1. Selection Action (streaming)
# ---------------------------------------------------------------------------

@router.post("/selection-action")
async def selection_action(
    payload: dict[str, Any],
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    workspace_role: str = Depends(get_current_workspace_role),
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf: None = Depends(require_csrf_protection),
    _ai_quota: None = Depends(require_entitlement("ai.actions.monthly", counter=count_ai_actions_this_month)),
) -> StreamingResponse:
    page_id = payload.get("page_id", "")
    selected_text = payload.get("selected_text", "")
    action_type = payload.get("action_type", "rewrite")

    if not selected_text.strip():
        raise ApiError("invalid_input", "No text selected", status_code=400)

    page = _get_page_or_404(
        db,
        page_id,
        workspace_id,
        current_user_id=str(current_user.id),
        workspace_role=workspace_role,
    )

    prompt_template = SELECTION_ACTION_PROMPTS.get(action_type)
    if not prompt_template:
        raise ApiError("invalid_input", f"Unknown action: {action_type}", status_code=400)

    user_prompt = prompt_template.format(text=selected_text)
    messages = [
        {"role": "system", "content": "你是一个AI写作助手，嵌入在用户的笔记编辑器中。请直接输出结果，不要添加多余的开场白或解释。"},
        {"role": "user", "content": user_prompt},
    ]

    async def _generate():
        async with action_log_context(
            db,
            workspace_id=str(workspace_id),
            user_id=str(current_user.id),
            action_type=f"selection.{action_type}",
            scope="selection",
            notebook_id=str(page.notebook_id) if page else None,
            page_id=str(page.id) if page else None,
            block_id=payload.get("block_id"),
        ) as log:
            log.set_input({"selected_text": selected_text[:5000], "action_type": action_type})
            full_content = ""
            last_usage: dict[str, Any] | None = None
            last_model_id: str | None = None
            try:
                yield _sse("message_start", {"role": "assistant", "action_log_id": log.log_id})
                async for chunk in chat_completion_stream(messages, temperature=0.7, max_tokens=4096):
                    if chunk.usage:
                        last_usage = chunk.usage
                    if chunk.model_id:
                        last_model_id = chunk.model_id
                    if chunk.content:
                        full_content += chunk.content
                        yield _sse("token", {"content": chunk.content, "snapshot": full_content})
                yield _sse("message_done", {"content": full_content, "action_type": action_type})
                log.set_output(full_content)
                log.record_usage(
                    event_type="llm_completion",
                    model_id=last_model_id,
                    prompt_tokens=(last_usage or {}).get("prompt_tokens") or _estimate_tokens(user_prompt),
                    completion_tokens=(last_usage or {}).get("completion_tokens") or _estimate_tokens(full_content),
                    count_source="exact" if last_usage else "estimated",
                )
            except Exception as exc:
                yield _sse("error", {"message": str(exc)})
                raise

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# 2. Page Action (streaming)
# ---------------------------------------------------------------------------

@router.post("/page-action")
async def page_action(
    payload: dict[str, Any],
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    workspace_role: str = Depends(get_current_workspace_role),
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf: None = Depends(require_csrf_protection),
    _ai_quota: None = Depends(require_entitlement("ai.actions.monthly", counter=count_ai_actions_this_month)),
) -> StreamingResponse:
    page_id = payload.get("page_id", "")
    action_type = payload.get("action_type", "summarize")

    page = _get_page_or_404(
        db,
        page_id,
        workspace_id,
        current_user_id=str(current_user.id),
        workspace_role=workspace_role,
    )
    page_text = page.plain_text or ""
    if not page_text.strip():
        raise ApiError("invalid_input", "Page has no content", status_code=400)

    prompt_template = PAGE_ACTION_PROMPTS.get(action_type)
    if not prompt_template:
        raise ApiError("invalid_input", f"Unknown action: {action_type}", status_code=400)

    user_prompt = prompt_template.format(text=page_text[:8000])
    messages = [
        {"role": "system", "content": "你是一个AI助手，正在帮助用户处理他们笔记页面中的内容。请直接、高效地回应。"},
        {"role": "user", "content": user_prompt},
    ]

    async def _generate():
        async with action_log_context(
            db,
            workspace_id=str(workspace_id),
            user_id=str(current_user.id),
            action_type=f"page.{action_type}",
            scope="page",
            notebook_id=str(page.notebook_id),
            page_id=str(page.id),
        ) as log:
            log.set_input({"action_type": action_type, "page_text_sha": str(len(page_text))})
            full_content = ""
            last_usage: dict[str, Any] | None = None
            last_model_id: str | None = None
            try:
                yield _sse("message_start", {"role": "assistant", "action_log_id": log.log_id})
                async for chunk in chat_completion_stream(messages, temperature=0.7, max_tokens=4096):
                    if chunk.usage:
                        last_usage = chunk.usage
                    if chunk.model_id:
                        last_model_id = chunk.model_id
                    if chunk.content:
                        full_content += chunk.content
                        yield _sse("token", {"content": chunk.content, "snapshot": full_content})
                yield _sse("message_done", {"content": full_content, "action_type": action_type})
                log.set_output(full_content)
                log.record_usage(
                    event_type="llm_completion",
                    model_id=last_model_id,
                    prompt_tokens=(last_usage or {}).get("prompt_tokens") or _estimate_tokens(user_prompt),
                    completion_tokens=(last_usage or {}).get("completion_tokens") or _estimate_tokens(full_content),
                    count_source="exact" if last_usage else "estimated",
                )
            except Exception as exc:
                yield _sse("error", {"message": str(exc)})
                raise

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# 3. In-Editor AI Chat (streaming)
# ---------------------------------------------------------------------------

@router.post("/ask")
async def ask(
    payload: dict[str, Any],
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    workspace_role: str = Depends(get_current_workspace_role),
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf: None = Depends(require_csrf_protection),
    _ai_quota: None = Depends(require_entitlement("ai.actions.monthly", counter=count_ai_actions_this_month)),
) -> StreamingResponse:
    """In-editor AI chat with multi-layer retrieval orchestration.

    Unlike the previous version that only used page text, this endpoint
    assembles context from:
    1. Current page text + selected text
    2. Long-term memory search (semantic similarity)
    3. Related pages in the same notebook
    4. Document chunks from uploaded study assets
    """
    page_id = str(payload.get("page_id", "") or "").strip()
    notebook_id = str(payload.get("notebook_id", "") or "").strip()
    user_message = payload.get("message", "")
    context_text = payload.get("context", "")
    history = payload.get("history", [])

    # Spec §8.1: caller chooses which layers the retriever may consult.
    # Defaults below match spec §8.2: selection present → selection+page,
    # else page+notebook when a page/notebook is in play.
    raw_scope = payload.get("scope")
    allowed_scope = {
        "selection", "page", "notebook", "project",
        "user_memory", "study_asset", "web",
    }
    scope: list[str] | None
    if isinstance(raw_scope, list):
        scope = [s for s in raw_scope if isinstance(s, str) and s in allowed_scope]
        if not scope:
            scope = None
    else:
        scope = None
    if scope is None:
        if context_text.strip():
            scope = ["selection", "page"]
        elif page_id or notebook_id:
            scope = ["page", "notebook"]
        else:
            scope = ["user_memory"]

    if not user_message.strip():
        raise ApiError("invalid_input", "Message cannot be empty", status_code=400)

    page: NotebookPage | None = None
    page_text = ""
    notebook: Notebook | None = None

    if page_id:
        page = _get_page_or_404(
            db,
            page_id,
            workspace_id,
            current_user_id=str(current_user.id),
            workspace_role=workspace_role,
        )
        page_text = page.plain_text or ""
        notebook = db.query(Notebook).filter(Notebook.id == page.notebook_id).first()
    elif notebook_id:
        notebook = (
            db.query(Notebook)
            .filter(Notebook.id == notebook_id, Notebook.workspace_id == workspace_id)
            .first()
        )
        # Extra visibility gate: same-workspace editors/viewers must not
        # reach private notebooks they didn't create. `assert_notebook_readable`
        # raises 404 (not 403) so the endpoint never leaks existence.
        assert_notebook_readable(
            notebook,
            workspace_id=workspace_id,
            current_user_id=str(current_user.id),
            workspace_role=workspace_role,
            not_found_message="Notebook not found",
        )
    else:
        raise ApiError("invalid_input", "page_id or notebook_id is required", status_code=400)

    resolved_notebook_id = str(notebook.id) if notebook else None
    project_id = str(notebook.project_id) if notebook and notebook.project_id else None

    # --- Retrieval Orchestration ---
    retrieval_sources = []
    if project_id:
        try:
            from app.services.retrieval_orchestration import assemble_context

            retrieval_ctx = await assemble_context(
                db,
                workspace_id=str(workspace_id),
                project_id=project_id,
                user_id=str(current_user.id),
                query=user_message,
                page_text=page_text[:6000],
                selected_text=context_text[:2000],
                notebook_id=resolved_notebook_id,
                page_id=str(page.id) if page is not None else None,
                scope=scope,
            )
            system_prompt = retrieval_ctx.system_prompt
            retrieval_sources = [
                {"type": s.source_type, "id": s.source_id, "title": s.title}
                for s in retrieval_ctx.sources
            ]
        except Exception:
            # Fallback to simple context if retrieval fails
            system_prompt = _build_simple_system_prompt(page_text, context_text)
    else:
        system_prompt = _build_simple_system_prompt(page_text, context_text)

    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt},
    ]
    # Add conversation history (last 10 turns)
    for msg in (history or [])[-10:]:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role in ("user", "assistant") and content.strip():
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_message})

    def _scope_from_sources(sources: list[dict]) -> str:
        types = {s.get("type") for s in sources}
        if {"related_page", "document_chunk"} & types:
            return "notebook"
        return "page"

    async def _generate():
        async with action_log_context(
            db,
            workspace_id=str(workspace_id),
            user_id=str(current_user.id),
            action_type="ask",
            scope=_scope_from_sources(retrieval_sources),
            notebook_id=resolved_notebook_id,
            page_id=str(page.id) if page is not None else None,
        ) as log:
            log.set_input({"message": user_message[:4000], "history_turns": len(history or [])})
            log.set_trace_metadata({"retrieval_sources": retrieval_sources})
            full_content = ""
            last_usage: dict[str, Any] | None = None
            last_model_id: str | None = None
            try:
                yield _sse("message_start", {
                    "role": "assistant",
                    "sources": retrieval_sources,
                    "action_log_id": log.log_id,
                })
                async for chunk in chat_completion_stream(messages, temperature=0.7, max_tokens=4096):
                    if chunk.usage:
                        last_usage = chunk.usage
                    if chunk.model_id:
                        last_model_id = chunk.model_id
                    if chunk.content:
                        full_content += chunk.content
                        yield _sse("token", {"content": chunk.content, "snapshot": full_content})
                yield _sse("message_done", {
                    "content": full_content,
                    "sources": retrieval_sources,
                })
                log.set_output(full_content)
                log.record_usage(
                    event_type="llm_completion",
                    model_id=last_model_id,
                    prompt_tokens=(last_usage or {}).get("prompt_tokens") or _estimate_tokens(user_message),
                    completion_tokens=(last_usage or {}).get("completion_tokens") or _estimate_tokens(full_content),
                    count_source="exact" if last_usage else "estimated",
                )
            except Exception as exc:
                yield _sse("error", {"message": str(exc)})
                raise

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _build_simple_system_prompt(page_text: str, context_text: str) -> str:
    """Fallback system prompt when retrieval orchestration is unavailable."""
    parts = [
        "你是用户笔记编辑器中的AI助手。用户正在编辑一个页面，你可以帮助他们写作、编程、解释概念、头脑风暴等。",
        "请根据页面内容和用户的问题给出有帮助的回答。如果用户让你写代码或文章，请直接输出内容。",
    ]
    if page_text.strip():
        parts.append(f"\n\n--- 当前页面内容 ---\n{page_text[:6000]}")
    if context_text.strip():
        parts.append(f"\n\n--- 用户选中的内容 ---\n{context_text[:2000]}")
    return "\n".join(parts)


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


# ---------------------------------------------------------------------------
# 4. Whiteboard Summarize + Memory Extraction
# ---------------------------------------------------------------------------

@router.post("/whiteboard-summarize")
async def whiteboard_summarize(
    payload: dict[str, Any],
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    workspace_role: str = Depends(get_current_workspace_role),
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf: None = Depends(require_csrf_protection),
    _ai_quota: None = Depends(require_entitlement("ai.actions.monthly", counter=count_ai_actions_this_month)),
) -> dict[str, Any]:
    """Summarize whiteboard content and extract memories.

    Payload::

        {
            "page_id": "<uuid>",
            "elements": [<Excalidraw elements array>]
        }

    Returns::

        {
            "summary": "...",
            "memory_count": 3
        }
    """
    from app.services import whiteboard_service

    page_id = payload.get("page_id", "")
    elements = payload.get("elements", [])

    if not page_id:
        raise ApiError("invalid_input", "page_id is required", status_code=400)
    if not isinstance(elements, list):
        raise ApiError("invalid_input", "elements must be a list", status_code=400)

    # Verify page ownership through notebook -> workspace (visibility-aware).
    page = _get_page_or_404(
        db,
        page_id,
        workspace_id,
        current_user_id=str(current_user.id),
        workspace_role=workspace_role,
    )

    # Resolve project_id from the notebook.
    notebook = db.query(Notebook).filter(Notebook.id == page.notebook_id).first()
    if not notebook or not notebook.project_id:
        raise ApiError("invalid_input", "Page must belong to a project notebook", status_code=400)

    project_id = str(notebook.project_id)

    async with action_log_context(
        db,
        workspace_id=str(workspace_id),
        user_id=str(current_user.id),
        action_type="whiteboard.summarize",
        scope="selection",
        notebook_id=str(page.notebook_id),
        page_id=str(page.id),
    ) as log:
        log.set_input({"elements_count": len(elements)})

        result = await whiteboard_service.extract_whiteboard_memories(
            db,
            page_id=str(page_id),
            workspace_id=str(workspace_id),
            project_id=project_id,
            user_id=str(current_user.id),
            elements_json=elements,
        )

        db.commit()

        summary = result.get("summary", "")
        pipeline_result = result.get("pipeline_result")
        if "memory_count" in result:
            memory_count = int(result.get("memory_count") or 0)
        else:
            memory_count = pipeline_result.item_count if pipeline_result else 0

        log.set_output({"summary": summary, "memory_count": memory_count})
        # whiteboard_service.extract_whiteboard_memories does not currently
        # surface the underlying LLM usage. Estimate from the summarized
        # description (description ≈ prompt input) and the produced summary.
        # TODO(s4/s5): plumb the actual `usage` block out of summarize_whiteboard.
        log.record_usage(
            event_type="llm_completion",
            prompt_tokens=_estimate_tokens(str(elements)),
            completion_tokens=_estimate_tokens(summary),
            count_source="estimated",
        )

        return {"summary": summary, "memory_count": memory_count}


# ---------------------------------------------------------------------------
# 5. Brainstorm (standalone endpoint — spec §13.5)
# ---------------------------------------------------------------------------

_BRAINSTORM_SYSTEM = (
    "You are a brainstorming partner embedded in the user's notebook. "
    "Generate fresh, actionable ideas on the given topic. Output a Markdown "
    "bulleted list; each bullet is one complete idea, concrete and varied."
)


@router.post("/brainstorm")
async def brainstorm(
    payload: dict[str, Any],
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    workspace_role: str = Depends(get_current_workspace_role),
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf: None = Depends(require_csrf_protection),
    _ai_quota: None = Depends(
        require_entitlement("ai.actions.monthly", counter=count_ai_actions_this_month),
    ),
) -> dict[str, Any]:
    """Dedicated brainstorm endpoint.

    Spec §13.5 listed `notebook/brainstorm` as a first-class route. It used
    to be subsumed by `page-action` with `action_type=brainstorm`; keeping
    both surface so legacy callers don't break, but spec compliance now
    exposes it directly.
    """
    topic = str(payload.get("topic") or "").strip()
    if not topic:
        raise ApiError("invalid_input", "topic is required", status_code=400)
    count = int(payload.get("count") or 5)
    if count < 1 or count > 20:
        raise ApiError("invalid_input", "count must be 1-20", status_code=400)
    page_id = str(payload.get("page_id") or "").strip()
    notebook_id = str(payload.get("notebook_id") or "").strip()

    notebook_resolved: Notebook | None = None
    page_resolved: NotebookPage | None = None
    if page_id:
        page_resolved = _get_page_or_404(
            db,
            page_id,
            workspace_id,
            current_user_id=str(current_user.id),
            workspace_role=workspace_role,
        )
        notebook_resolved = db.query(Notebook).filter(Notebook.id == page_resolved.notebook_id).first()
    elif notebook_id:
        notebook_resolved = (
            db.query(Notebook)
            .filter(Notebook.id == notebook_id, Notebook.workspace_id == workspace_id)
            .first()
        )
        assert_notebook_readable(
            notebook_resolved,
            workspace_id=workspace_id,
            current_user_id=str(current_user.id),
            workspace_role=workspace_role,
            not_found_message="Notebook not found",
        )

    user_prompt = (
        f"Brainstorm exactly {count} ideas around the following topic. "
        f"Return only a Markdown bulleted list.\n\nTopic: {topic}"
    )
    messages = [
        {"role": "system", "content": _BRAINSTORM_SYSTEM},
        {"role": "user", "content": user_prompt},
    ]

    async with action_log_context(
        db,
        workspace_id=str(workspace_id),
        user_id=str(current_user.id),
        action_type="notebook.brainstorm",
        scope="notebook" if notebook_resolved else "project",
        notebook_id=str(notebook_resolved.id) if notebook_resolved else None,
        page_id=str(page_resolved.id) if page_resolved else None,
    ) as log:
        log.set_input({"topic": topic[:500], "count": count})
        buffer = ""
        last_usage: dict[str, Any] | None = None
        last_model_id: str | None = None
        async for chunk in chat_completion_stream(messages, temperature=0.8, max_tokens=1024):
            if chunk.usage:
                last_usage = chunk.usage
            if chunk.model_id:
                last_model_id = chunk.model_id
            if chunk.content:
                buffer += chunk.content
        log.set_output(buffer)
        log.record_usage(
            event_type="llm_completion",
            model_id=last_model_id,
            prompt_tokens=(last_usage or {}).get("prompt_tokens") or _estimate_tokens(user_prompt),
            completion_tokens=(last_usage or {}).get("completion_tokens") or _estimate_tokens(buffer),
            count_source="exact" if last_usage else "estimated",
        )
        return {"markdown": buffer, "topic": topic, "count": count}


# ---------------------------------------------------------------------------
# 6. generate-page — idea → new page (spec §11 idea-to-build)
# ---------------------------------------------------------------------------

_GENERATE_PAGE_SYSTEM = (
    "You are an expert product/tech planner. The user gives you a raw idea "
    "and a target output type (prd, mvp, tech_spec, functional_tree). "
    "You produce a complete, well-structured document in Markdown. "
    "Use clear headings, tables where useful, and concrete next steps."
)

_GENERATE_PAGE_OUTPUT_PROMPTS: dict[str, str] = {
    "prd": (
        "Produce a Product Requirements Document with sections: "
        "Problem Statement / Target Users / Goals & Non-Goals / "
        "Key Features / User Stories / Success Metrics / Risks."
    ),
    "mvp": (
        "Produce an MVP build plan with: Scope Cuts / Must-Have Features / "
        "Out of Scope / 2-Week Milestones / Open Questions."
    ),
    "tech_spec": (
        "Produce a Technical Design Document with: Architecture Overview / "
        "Data Model / API Surface / Sequence Diagrams (ASCII ok) / "
        "Error Handling / Migration Plan."
    ),
    "functional_tree": (
        "Produce a functional decomposition tree (Markdown nested lists), "
        "where each leaf is a concrete work unit the engineer can pick up."
    ),
}


@router.post("/generate-page")
async def generate_page(
    payload: dict[str, Any],
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    workspace_role: str = Depends(get_current_workspace_role),
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf: None = Depends(require_csrf_protection),
    _ai_quota: None = Depends(
        require_entitlement("ai.actions.monthly", counter=count_ai_actions_this_month),
    ),
) -> dict[str, Any]:
    """Idea-to-build: turn a free-form idea into a fresh page (spec §11)."""
    idea = str(payload.get("idea") or "").strip()
    notebook_id = str(payload.get("notebook_id") or "").strip()
    output_type = str(payload.get("output_type") or "prd").strip().lower()
    if not idea:
        raise ApiError("invalid_input", "idea is required", status_code=400)
    if not notebook_id:
        raise ApiError("invalid_input", "notebook_id is required", status_code=400)
    if output_type not in _GENERATE_PAGE_OUTPUT_PROMPTS:
        raise ApiError(
            "invalid_input",
            f"output_type must be one of {list(_GENERATE_PAGE_OUTPUT_PROMPTS)}",
            status_code=400,
        )

    notebook = (
        db.query(Notebook)
        .filter(Notebook.id == notebook_id, Notebook.workspace_id == workspace_id)
        .first()
    )
    assert_notebook_readable(
        notebook,
        workspace_id=workspace_id,
        current_user_id=str(current_user.id),
        workspace_role=workspace_role,
        not_found_message="Notebook not found",
    )
    if notebook and notebook.archived_at is not None:
        raise ApiError("not_found", "Notebook not found", status_code=404)

    instructions = _GENERATE_PAGE_OUTPUT_PROMPTS[output_type]
    user_prompt = f"{instructions}\n\n--- Idea ---\n{idea}"
    messages = [
        {"role": "system", "content": _GENERATE_PAGE_SYSTEM},
        {"role": "user", "content": user_prompt},
    ]

    async with action_log_context(
        db,
        workspace_id=str(workspace_id),
        user_id=str(current_user.id),
        action_type=f"notebook.generate_page.{output_type}",
        scope="notebook",
        notebook_id=str(notebook.id),
    ) as log:
        log.set_input({"idea": idea[:2000], "output_type": output_type})
        buffer = ""
        last_usage: dict[str, Any] | None = None
        last_model_id: str | None = None
        async for chunk in chat_completion_stream(messages, temperature=0.7, max_tokens=4096):
            if chunk.usage:
                last_usage = chunk.usage
            if chunk.model_id:
                last_model_id = chunk.model_id
            if chunk.content:
                buffer += chunk.content

        # Persist the generated Markdown as a new NotebookPage.
        from uuid import uuid4 as _uuid4
        title_candidate = idea.splitlines()[0].strip()[:120] or f"{output_type.upper()} — Draft"
        # Wrap Markdown into a TipTap doc of one paragraph node so search
        # still indexes it; full Markdown rendering is a frontend concern.
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "attrs": {"block_id": str(_uuid4())},
                    "content": [{"type": "text", "text": buffer}],
                }
            ],
        }
        new_page = NotebookPage(
            notebook_id=notebook.id,
            created_by=current_user.id,
            title=title_candidate,
            slug=title_candidate.lower().replace(" ", "-")[:200],
            page_type="document",
            content_json=doc,
            plain_text=buffer,
        )
        db.add(new_page)
        db.flush()

        log.set_output({"page_id": new_page.id, "length": len(buffer)})
        log.record_usage(
            event_type="llm_completion",
            model_id=last_model_id,
            prompt_tokens=(last_usage or {}).get("prompt_tokens") or _estimate_tokens(user_prompt),
            completion_tokens=(last_usage or {}).get("completion_tokens") or _estimate_tokens(buffer),
            count_source="exact" if last_usage else "estimated",
        )
        db.commit()
        return {
            "page_id": new_page.id,
            "title": new_page.title,
            "output_type": output_type,
            "markdown": buffer,
        }
