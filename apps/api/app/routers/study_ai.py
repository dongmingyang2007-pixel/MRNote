"""Study-scope AI endpoints: flashcards / quiz / ask (S4)."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

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
