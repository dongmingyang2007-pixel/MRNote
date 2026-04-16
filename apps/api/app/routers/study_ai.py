"""Study-scope AI endpoints: flashcards / quiz / ask (S4)."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from starlette.responses import StreamingResponse

from app.core.deps import (
    get_current_user,
    get_current_workspace_id,
    get_db_session,
    require_csrf_protection,
    require_workspace_write_access,
)
from app.core.errors import ApiError
from app.models import (
    Notebook, NotebookPage, StudyAsset, StudyCard, StudyChunk, StudyDeck, User,
)
from app.services.ai_action_logger import action_log_context
from app.services.dashscope_client import chat_completion
from app.services.dashscope_stream import chat_completion_stream
from app.services.study_context import assemble_study_context

router = APIRouter(prefix="/api/v1/ai/study", tags=["study-ai"])


_FLASHCARDS_SYSTEM = (
    "You produce study flashcards as strict JSON. No prose. "
    'Format: {"cards":[{"front":"...","back":"..."}]}. '
    "Each question tests a distinct concept; answers concise."
)


async def _run_llm_json(system: str, user_prompt: str) -> str:
    """Seam the tests monkey-patch. Calls the non-streaming LLM and
    returns the raw text (expected to be JSON)."""
    return await chat_completion(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
        max_tokens=2048,
    )


def _load_source_text(
    db: Session, *, source_type: str, source_id: str, workspace_id: str,
) -> tuple[str, str | None, str | None]:
    """Return (text, page_id_or_None, notebook_id)."""
    if source_type == "page":
        page = db.query(NotebookPage).filter_by(id=source_id).first()
        if not page:
            raise ApiError("not_found", "Page not found", status_code=404)
        nb = (
            db.query(Notebook)
            .filter(Notebook.id == page.notebook_id, Notebook.workspace_id == workspace_id)
            .first()
        )
        if not nb:
            raise ApiError("not_found", "Page not found", status_code=404)
        return (page.plain_text or "")[:8000], page.id, nb.id
    if source_type == "chunk":
        chunk = db.query(StudyChunk).filter_by(id=source_id).first()
        if not chunk:
            raise ApiError("not_found", "Chunk not found", status_code=404)
        asset = db.query(StudyAsset).filter_by(id=chunk.asset_id).first()
        if not asset:
            raise ApiError("not_found", "Chunk not found", status_code=404)
        nb = (
            db.query(Notebook)
            .filter(Notebook.id == asset.notebook_id, Notebook.workspace_id == workspace_id)
            .first()
        )
        if not nb:
            raise ApiError("not_found", "Chunk not found", status_code=404)
        return (chunk.content or "")[:8000], None, nb.id
    raise ApiError("invalid_input", f"Unknown source_type {source_type}", status_code=400)


@router.post("/flashcards")
async def generate_flashcards(
    payload: dict[str, Any],
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf: None = Depends(require_csrf_protection),
) -> dict[str, Any]:
    source_type = str(payload.get("source_type", ""))
    source_id = str(payload.get("source_id", ""))
    count = int(payload.get("count", 10))
    deck_id = payload.get("deck_id")
    if count < 1 or count > 50:
        raise ApiError("invalid_input", "count must be 1-50", status_code=400)

    text, page_id, notebook_id = _load_source_text(
        db, source_type=source_type, source_id=source_id,
        workspace_id=workspace_id,
    )

    prompt = (
        f"Produce exactly {count} flashcards from the following text.\n\n{text}"
    )

    async with action_log_context(
        db,
        workspace_id=str(workspace_id),
        user_id=str(current_user.id),
        action_type="study.flashcards",
        scope="study_asset" if source_type == "chunk" else "page",
        notebook_id=str(notebook_id) if notebook_id else None,
        page_id=str(page_id) if page_id else None,
    ) as log:
        log.set_input({"source_type": source_type, "source_id": source_id, "count": count})

        raw = await _run_llm_json(_FLASHCARDS_SYSTEM, prompt)
        try:
            parsed = json.loads(raw)
            cards = parsed["cards"]
            if not isinstance(cards, list) or not cards:
                raise ValueError("cards missing")
            for c in cards:
                if not isinstance(c.get("front"), str) or not isinstance(c.get("back"), str):
                    raise ValueError("bad card shape")
        except Exception as exc:
            log.set_output({"error": str(exc), "raw_length": len(raw)})
            raise ApiError("llm_bad_output", "LLM returned invalid JSON", status_code=422)

        log.set_output({"card_count": len(cards)})
        log.record_usage(
            event_type="llm_completion",
            prompt_tokens=max(1, len(prompt) // 4),
            completion_tokens=max(1, len(raw) // 4),
            count_source="estimated",
        )

        card_ids: list[str] | None = None
        if deck_id:
            deck = db.query(StudyDeck).filter_by(id=deck_id).first()
            if not deck:
                raise ApiError("not_found", "Deck not found", status_code=404)
            nb = (
                db.query(Notebook)
                .filter(Notebook.id == deck.notebook_id, Notebook.workspace_id == workspace_id)
                .first()
            )
            if not nb:
                raise ApiError("not_found", "Deck not found", status_code=404)
            src_type = "page_ai" if source_type == "page" else "chunk_ai"
            card_rows: list[StudyCard] = []
            for c in cards:
                card_rows.append(StudyCard(
                    deck_id=deck.id,
                    front=c["front"],
                    back=c["back"],
                    source_type=src_type,
                    source_ref=source_id,
                ))
            db.add_all(card_rows)
            deck.card_count = (deck.card_count or 0) + len(card_rows)
            db.add(deck)
            db.commit()
            for row in card_rows:
                db.refresh(row)
            card_ids = [r.id for r in card_rows]

    return {"cards": cards, "card_ids": card_ids}


_QUIZ_SYSTEM = (
    "You produce multiple-choice quizzes as strict JSON. No prose. "
    'Format: {"questions":[{"question":"...","options":["a","b","c","d"],'
    '"correct_index":0,"explanation":"..."}]}. Exactly 4 options each, '
    "correct_index in 0..3."
)


@router.post("/quiz")
async def generate_quiz(
    payload: dict[str, Any],
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf: None = Depends(require_csrf_protection),
) -> dict[str, Any]:
    source_type = str(payload.get("source_type", ""))
    source_id = str(payload.get("source_id", ""))
    count = int(payload.get("count", 5))
    if count < 1 or count > 20:
        raise ApiError("invalid_input", "count must be 1-20", status_code=400)

    text, page_id, notebook_id = _load_source_text(
        db, source_type=source_type, source_id=source_id,
        workspace_id=workspace_id,
    )

    prompt = (
        f"Produce exactly {count} MCQs from the following text.\n\n{text}"
    )

    async with action_log_context(
        db,
        workspace_id=str(workspace_id),
        user_id=str(current_user.id),
        action_type="study.quiz",
        scope="study_asset" if source_type == "chunk" else "page",
        notebook_id=str(notebook_id) if notebook_id else None,
        page_id=str(page_id) if page_id else None,
    ) as log:
        log.set_input({"source_type": source_type, "source_id": source_id, "count": count})

        raw = await _run_llm_json(_QUIZ_SYSTEM, prompt)
        try:
            parsed = json.loads(raw)
            questions = parsed["questions"]
            if not isinstance(questions, list) or not questions:
                raise ValueError("questions missing")
            for q in questions:
                options = q.get("options")
                if not isinstance(options, list) or len(options) != 4:
                    raise ValueError("options must be length 4")
                if not all(isinstance(o, str) and o.strip() for o in options):
                    raise ValueError("options must be non-empty strings")
                ci = q.get("correct_index")
                if not isinstance(ci, int) or not 0 <= ci < 4:
                    raise ValueError("correct_index out of range")
                if not isinstance(q.get("question"), str):
                    raise ValueError("question must be str")
        except Exception as exc:
            log.set_output({"error": str(exc), "raw_length": len(raw)})
            raise ApiError("llm_bad_output", "LLM returned invalid MCQ JSON", status_code=422)

        log.set_output({"question_count": len(questions)})
        log.record_usage(
            event_type="llm_completion",
            prompt_tokens=max(1, len(prompt) // 4),
            completion_tokens=max(1, len(raw) // 4),
            count_source="estimated",
        )

    return {"questions": questions}


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/ask")
async def study_ask(
    payload: dict[str, Any],
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf: None = Depends(require_csrf_protection),
) -> StreamingResponse:
    asset_id = str(payload.get("asset_id", ""))
    message = str(payload.get("message", "")).strip()
    history = payload.get("history") or []
    if not asset_id or not message:
        raise ApiError("invalid_input", "asset_id and message are required", status_code=400)

    asset = db.query(StudyAsset).filter_by(id=asset_id).first()
    if not asset:
        raise ApiError("not_found", "Asset not found", status_code=404)
    nb = (
        db.query(Notebook)
        .filter(Notebook.id == asset.notebook_id, Notebook.workspace_id == workspace_id)
        .first()
    )
    if not nb:
        raise ApiError("not_found", "Asset not found", status_code=404)

    ctx, sources = assemble_study_context(
        db,
        asset_id=asset_id,
        workspace_id=str(workspace_id),
        project_id=str(nb.project_id) if nb.project_id else "",
        user_id=str(current_user.id),
        query=message,
    )

    messages: list[dict[str, str]] = [
        {"role": "system", "content": ctx["system_prompt"]}
    ]
    for m in (history or [])[-10:]:
        role = m.get("role"); content = m.get("content")
        if role in ("user", "assistant") and isinstance(content, str) and content.strip():
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": message})

    async def _generate():
        async with action_log_context(
            db,
            workspace_id=str(workspace_id),
            user_id=str(current_user.id),
            action_type="study.ask",
            scope="study_asset",
            notebook_id=str(nb.id),
            page_id=None,
        ) as log:
            log.set_input({"asset_id": asset_id, "message": message[:4000]})
            log.set_trace_metadata({"retrieval_sources": sources})
            full = ""
            last_usage: dict | None = None
            last_model_id: str | None = None
            try:
                yield _sse("message_start", {
                    "role": "assistant",
                    "sources": sources,
                    "action_log_id": log.log_id,
                })
                async for chunk in chat_completion_stream(messages, temperature=0.7, max_tokens=4096):
                    if chunk.content:
                        full += chunk.content
                        yield _sse("token", {"content": chunk.content, "snapshot": full})
                    if chunk.usage:
                        last_usage = chunk.usage
                    if chunk.model_id:
                        last_model_id = chunk.model_id
                log.set_output(full)
                log.record_usage(
                    event_type="llm_completion",
                    model_id=last_model_id,
                    prompt_tokens=(last_usage or {}).get("prompt_tokens") or max(1, len(message) // 4),
                    completion_tokens=(last_usage or {}).get("completion_tokens") or max(1, len(full) // 4),
                    count_source="exact" if last_usage else "estimated",
                )
                yield _sse("message_done", {"content": full, "sources": sources, "action_log_id": log.log_id})
            except Exception as exc:
                yield _sse("error", {"message": str(exc)})
                raise

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
