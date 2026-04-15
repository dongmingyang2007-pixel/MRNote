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
    get_db_session,
    require_csrf_protection,
    require_workspace_write_access,
)
from app.core.errors import ApiError
from app.models import Notebook, NotebookPage, User
from app.services.dashscope_stream import chat_completion_stream

router = APIRouter(prefix="/api/v1/ai/notebook", tags=["notebook-ai"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _get_page_or_404(db: Session, page_id: str, workspace_id: str) -> NotebookPage:
    """Load a page and verify it belongs to the workspace via its notebook."""
    page = db.query(NotebookPage).filter(NotebookPage.id == page_id).first()
    if not page:
        raise ApiError("not_found", "Page not found", status_code=404)
    # Verify workspace ownership through notebook
    notebook = db.query(Notebook).filter(
        Notebook.id == page.notebook_id,
        Notebook.workspace_id == workspace_id,
    ).first()
    if not notebook:
        raise ApiError("not_found", "Page not found", status_code=404)
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
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf: None = Depends(require_csrf_protection),
) -> StreamingResponse:
    page_id = payload.get("page_id", "")
    selected_text = payload.get("selected_text", "")
    action_type = payload.get("action_type", "rewrite")

    if not selected_text.strip():
        raise ApiError("invalid_input", "No text selected", status_code=400)

    page = _get_page_or_404(db, page_id, workspace_id)

    prompt_template = SELECTION_ACTION_PROMPTS.get(action_type)
    if not prompt_template:
        raise ApiError("invalid_input", f"Unknown action: {action_type}", status_code=400)

    user_prompt = prompt_template.format(text=selected_text)
    messages = [
        {"role": "system", "content": "你是一个AI写作助手，嵌入在用户的笔记编辑器中。请直接输出结果，不要添加多余的开场白或解释。"},
        {"role": "user", "content": user_prompt},
    ]

    async def _generate():
        full_content = ""
        try:
            yield _sse("message_start", {"role": "assistant"})
            async for chunk in chat_completion_stream(messages, temperature=0.7, max_tokens=4096):
                if chunk.content:
                    full_content += chunk.content
                    yield _sse("token", {"content": chunk.content, "snapshot": full_content})
            yield _sse("message_done", {"content": full_content, "action_type": action_type})
        except Exception as exc:
            yield _sse("error", {"message": str(exc)})

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
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf: None = Depends(require_csrf_protection),
) -> StreamingResponse:
    page_id = payload.get("page_id", "")
    action_type = payload.get("action_type", "summarize")

    page = _get_page_or_404(db, page_id, workspace_id)
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
        full_content = ""
        try:
            yield _sse("message_start", {"role": "assistant"})
            async for chunk in chat_completion_stream(messages, temperature=0.7, max_tokens=4096):
                if chunk.content:
                    full_content += chunk.content
                    yield _sse("token", {"content": chunk.content, "snapshot": full_content})
            yield _sse("message_done", {"content": full_content, "action_type": action_type})
        except Exception as exc:
            yield _sse("error", {"message": str(exc)})

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
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf: None = Depends(require_csrf_protection),
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

    if not user_message.strip():
        raise ApiError("invalid_input", "Message cannot be empty", status_code=400)

    page: NotebookPage | None = None
    page_text = ""
    notebook: Notebook | None = None

    if page_id:
        page = _get_page_or_404(db, page_id, workspace_id)
        page_text = page.plain_text or ""
        notebook = db.query(Notebook).filter(Notebook.id == page.notebook_id).first()
    elif notebook_id:
        notebook = (
            db.query(Notebook)
            .filter(Notebook.id == notebook_id, Notebook.workspace_id == workspace_id)
            .first()
        )
        if notebook is None:
            raise ApiError("not_found", "Notebook not found", status_code=404)
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

    async def _generate():
        full_content = ""
        try:
            yield _sse("message_start", {
                "role": "assistant",
                "sources": retrieval_sources,
            })
            async for chunk in chat_completion_stream(messages, temperature=0.7, max_tokens=4096):
                if chunk.content:
                    full_content += chunk.content
                    yield _sse("token", {"content": chunk.content, "snapshot": full_content})
            yield _sse("message_done", {
                "content": full_content,
                "sources": retrieval_sources,
            })
        except Exception as exc:
            yield _sse("error", {"message": str(exc)})

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


# ---------------------------------------------------------------------------
# 4. Whiteboard Summarize + Memory Extraction
# ---------------------------------------------------------------------------

@router.post("/whiteboard-summarize")
async def whiteboard_summarize(
    payload: dict[str, Any],
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf: None = Depends(require_csrf_protection),
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
    from app.services.whiteboard_service import extract_whiteboard_memories

    page_id = payload.get("page_id", "")
    elements = payload.get("elements", [])

    if not page_id:
        raise ApiError("invalid_input", "page_id is required", status_code=400)
    if not isinstance(elements, list):
        raise ApiError("invalid_input", "elements must be a list", status_code=400)

    # Verify page ownership through notebook -> workspace.
    page = _get_page_or_404(db, page_id, workspace_id)

    # Resolve project_id from the notebook.
    notebook = db.query(Notebook).filter(Notebook.id == page.notebook_id).first()
    if not notebook or not notebook.project_id:
        raise ApiError("invalid_input", "Page must belong to a project notebook", status_code=400)

    project_id = str(notebook.project_id)

    result = await extract_whiteboard_memories(
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
    memory_count = pipeline_result.item_count if pipeline_result else 0

    return {"summary": summary, "memory_count": memory_count}
