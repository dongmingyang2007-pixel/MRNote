import asyncio
import base64
from datetime import datetime, timezone
import json
import logging
import threading

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile, status
from sqlalchemy.orm import Session
from starlette.responses import StreamingResponse

from app.core.config import settings
from app.core.deps import (
    can_access_workspace_conversation,
    enforce_rate_limit,
    get_current_user,
    get_current_workspace_id,
    get_current_workspace_role,
    get_db_session,
    is_workspace_privileged_role,
    require_workspace_write_access,
    require_csrf_protection,
)
from app.core.errors import ApiError
from app.models import Conversation, Memory, Message, Project, User
from app.schemas.conversation import ConversationCreate, ConversationOut, MessageCreate, MessageOut
from app.schemas.memory import (
    MessageMemoryLearningOut,
    MessageMemoryWriteOut,
    MemoryLearningRunOut,
    MemoryOutcomeOut,
    MemoryWriteItemOut,
    MemoryWriteRunOut,
)
from app.services.dashscope_client import InferenceTimeoutError, UpstreamServiceError
from app.services.assistant_markdown import normalize_assistant_markdown
from app.services.orchestrator import (
    orchestrate_inference,
    orchestrate_inference_stream,
    orchestrate_voice_inference,
    synthesize_speech_for_project,
    transcribe_audio_input_for_project,
)
from app.services.memory_context import build_conversation_focus_metadata, touch_memories_from_trace
from app.services.memory_v2 import get_message_memory_learning, get_message_memory_write
from app.services.voice_response_limits import clamp_voice_response_text
from app.routers.utils import get_project_in_workspace_or_404
from app.services.upload_validation import (
    UPLOAD_SIGNATURE_READ_BYTES,
    validate_workspace_upload_signature,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])

_ALLOWED_AUDIO_MEDIA_TYPES = {
    "audio/wav",
    "audio/x-wav",
    "audio/wave",
    "audio/mpeg",
    "audio/mp3",
    "audio/webm",
    "audio/ogg",
    "audio/mp4",
    "audio/x-m4a",
    "audio/m4a",
}

_MODEL_API_UNCONFIGURED_MESSAGE = (
    "AI service is not configured. Set DASHSCOPE_API_KEY and restart the API service."
)

_MEMORY_EXTRACTION_STATUS_PENDING = "pending"


def _normalize_inference_result(result: str | dict) -> tuple[str, str | None, dict[str, object]]:
    if isinstance(result, str):
        return normalize_assistant_markdown(result), None, {}

    raw_sources = result.get("sources")
    sources = [
        source
        for source in raw_sources
        if isinstance(source, dict)
    ] if isinstance(raw_sources, list) else []

    metadata_json: dict[str, object] = {}
    if sources:
        metadata_json["sources"] = sources
    retrieval_trace = result.get("retrieval_trace")
    if isinstance(retrieval_trace, dict) and retrieval_trace:
        metadata_json["retrieval_trace"] = retrieval_trace

    # Content is already normalised by the orchestrator; avoid double-normalisation.
    content = result.get("content", "") or ""
    reasoning_content = result.get("reasoning_content")
    normalized_reasoning = (
        reasoning_content
        if isinstance(reasoning_content, str) and reasoning_content.strip()
        else None
    )

    return content, normalized_reasoning, metadata_json


def _normalize_memory_write_preview(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None

    payload: dict[str, object] = {}
    summary = value.get("summary")
    if isinstance(summary, str) and summary.strip():
        payload["summary"] = summary.strip()

    for key in ("item_count", "written_count", "discarded_count"):
        raw_value = value.get(key)
        if isinstance(raw_value, int):
            payload[key] = raw_value

    raw_items = value.get("items")
    if isinstance(raw_items, list):
        items: list[dict[str, object]] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            fact_text = str(item.get("fact") or "").strip()
            if not fact_text:
                continue
            normalized_item: dict[str, object] = {
                "id": str(item.get("id") or "").strip() or fact_text[:32],
                "fact": fact_text,
                "category": str(item.get("category") or "").strip(),
                "importance": float(item.get("importance") or 0.0),
            }
            for field in (
                "triage_action",
                "triage_reason",
                "status",
                "target_memory_id",
                "memory_type",
            ):
                field_value = str(item.get(field) or "").strip()
                if field_value:
                    normalized_item[field] = field_value
            evidence_count = item.get("evidence_count")
            if isinstance(evidence_count, int):
                normalized_item["evidence_count"] = evidence_count
            items.append(normalized_item)
        if items:
            payload["items"] = items

    if not payload:
        return None
    return payload


def _sanitize_assistant_metadata(metadata_json: dict[str, object] | None) -> dict[str, object]:
    metadata = metadata_json if isinstance(metadata_json, dict) else {}
    payload: dict[str, object] = {}

    raw_sources = metadata.get("sources")
    if isinstance(raw_sources, list):
        sources = [source for source in raw_sources if isinstance(source, dict)]
        if sources:
            payload["sources"] = sources

    retrieval_trace = metadata.get("retrieval_trace")
    if isinstance(retrieval_trace, dict) and retrieval_trace:
        payload["retrieval_trace"] = retrieval_trace

    preview = _normalize_memory_write_preview(metadata.get("memory_write_preview"))
    if preview:
        payload["memory_write_preview"] = preview

    raw_memories_extracted = metadata.get("memories_extracted")
    if isinstance(raw_memories_extracted, str) and raw_memories_extracted.strip():
        payload["memories_extracted"] = raw_memories_extracted.strip()

    raw_memory_extraction_status = metadata.get("memory_extraction_status")
    if isinstance(raw_memory_extraction_status, str) and raw_memory_extraction_status.strip():
        payload["memory_extraction_status"] = raw_memory_extraction_status.strip()

    raw_memory_extraction_attempts = metadata.get("memory_extraction_attempts")
    if isinstance(raw_memory_extraction_attempts, int):
        payload["memory_extraction_attempts"] = raw_memory_extraction_attempts

    raw_memory_extraction_error = metadata.get("memory_extraction_error")
    if isinstance(raw_memory_extraction_error, str) and raw_memory_extraction_error.strip():
        payload["memory_extraction_error"] = raw_memory_extraction_error.strip()

    raw_memory_write_run_id = metadata.get("memory_write_run_id")
    if isinstance(raw_memory_write_run_id, str) and raw_memory_write_run_id.strip():
        payload["memory_write_run_id"] = raw_memory_write_run_id.strip()

    raw_memory_learning_run_id = metadata.get("memory_learning_run_id")
    if isinstance(raw_memory_learning_run_id, str) and raw_memory_learning_run_id.strip():
        payload["memory_learning_run_id"] = raw_memory_learning_run_id.strip()

    raw_memory_extraction_updated_at = metadata.get("memory_extraction_updated_at")
    if isinstance(raw_memory_extraction_updated_at, str) and raw_memory_extraction_updated_at.strip():
        payload["memory_extraction_updated_at"] = raw_memory_extraction_updated_at.strip()

    return payload


def _serialize_message(message: Message) -> MessageOut:
    content = message.content
    reasoning_content = message.reasoning_content
    metadata_json = message.metadata_json if isinstance(message.metadata_json, dict) else {}
    if message.role == "assistant":
        content = normalize_assistant_markdown(content)
        reasoning_content = (
            normalize_assistant_markdown(reasoning_content)
            if isinstance(reasoning_content, str) and reasoning_content.strip()
            else None
        )
        metadata_json = _sanitize_assistant_metadata(metadata_json)

    return MessageOut(
        id=message.id,
        conversation_id=message.conversation_id,
        role=message.role,
        content=content,
        reasoning_content=reasoning_content,
        metadata_json=metadata_json,
        created_at=message.created_at,
    )


def _apply_pending_memory_extraction_metadata(
    metadata_json: dict[str, object] | None,
) -> dict[str, object]:
    next_metadata = dict(metadata_json or {})
    next_metadata.pop("memory_write_preview", None)
    next_metadata["memory_extraction_status"] = _MEMORY_EXTRACTION_STATUS_PENDING
    next_metadata["memory_extraction_attempts"] = 0
    next_metadata.pop("memory_extraction_error", None)
    next_metadata["memory_extraction_updated_at"] = datetime.now(timezone.utc).isoformat()
    return next_metadata


def _apply_conversation_focus(
    conversation: Conversation,
    *,
    retrieval_trace: dict[str, object] | None,
    updated_at: datetime | None = None,
) -> None:
    conversation.metadata_json = build_conversation_focus_metadata(
        existing_metadata=conversation.metadata_json if isinstance(conversation.metadata_json, dict) else {},
        retrieval_trace=retrieval_trace,
        updated_at=updated_at,
    )


def _normalize_media_type(content_type: str | None) -> str:
    return (content_type or "").split(";", 1)[0].strip().lower()


async def _read_validated_upload(upload: UploadFile, *, kind: str) -> bytes:
    content_type = _normalize_media_type(upload.content_type)
    if kind == "image":
        if content_type not in settings.image_allowed_media_types:
            raise ApiError("unsupported_media_type", "Unsupported image upload type", status_code=415)
    elif kind == "audio":
        if content_type not in _ALLOWED_AUDIO_MEDIA_TYPES:
            raise ApiError("unsupported_media_type", "Unsupported audio upload type", status_code=415)
    else:
        raise ApiError("bad_request", "Unsupported upload kind", status_code=400)

    payload = await upload.read()
    if not payload:
        raise ApiError("empty_upload", f"{kind.capitalize()} upload is empty", status_code=400)

    max_bytes = settings.upload_max_mb * 1024 * 1024
    if len(payload) > max_bytes:
        raise ApiError(
            "payload_too_large",
            f"{kind.capitalize()} exceeds {settings.upload_max_mb}MB limit",
            status_code=413,
        )

    if kind == "image":
        validate_workspace_upload_signature(
            prefix=payload[:UPLOAD_SIGNATURE_READ_BYTES],
            media_type=content_type,
        )
    return payload


def _raise_inference_api_error(exc: Exception) -> None:
    if isinstance(exc, InferenceTimeoutError):
        raise ApiError("inference_timeout", "Inference timeout", status_code=503) from exc
    if isinstance(exc, UpstreamServiceError):
        raise ApiError(
            "model_api_unavailable",
            "Model API unavailable",
            status_code=502,
            details={"retry_after": 5},
        ) from exc
    raise exc


def _ensure_model_api_configured() -> None:
    if settings.dashscope_api_key:
        return
    raise ApiError(
        "model_api_unconfigured",
        _MODEL_API_UNCONFIGURED_MESSAGE,
        status_code=503,
    )


def _extract_live_message_metadata(message: Message) -> dict[str, object] | None:
    metadata = message.metadata_json if isinstance(message.metadata_json, dict) else {}
    payload: dict[str, object] = {}

    preview = _normalize_memory_write_preview(metadata.get("memory_write_preview"))
    if preview:
        payload["memory_write_preview"] = preview

    raw_memories_extracted = metadata.get("memories_extracted")
    if isinstance(raw_memories_extracted, str) and raw_memories_extracted.strip():
        payload["memories_extracted"] = raw_memories_extracted.strip()

    raw_memory_extraction_status = metadata.get("memory_extraction_status")
    if isinstance(raw_memory_extraction_status, str) and raw_memory_extraction_status.strip():
        payload["memory_extraction_status"] = raw_memory_extraction_status.strip()

    raw_memory_extraction_attempts = metadata.get("memory_extraction_attempts")
    if isinstance(raw_memory_extraction_attempts, int):
        payload["memory_extraction_attempts"] = raw_memory_extraction_attempts

    raw_memory_extraction_error = metadata.get("memory_extraction_error")
    if isinstance(raw_memory_extraction_error, str) and raw_memory_extraction_error.strip():
        payload["memory_extraction_error"] = raw_memory_extraction_error.strip()

    raw_memory_write_run_id = metadata.get("memory_write_run_id")
    if isinstance(raw_memory_write_run_id, str) and raw_memory_write_run_id.strip():
        payload["memory_write_run_id"] = raw_memory_write_run_id.strip()

    raw_memory_learning_run_id = metadata.get("memory_learning_run_id")
    if isinstance(raw_memory_learning_run_id, str) and raw_memory_learning_run_id.strip():
        payload["memory_learning_run_id"] = raw_memory_learning_run_id.strip()

    return payload or None


def _refresh_chat_sse_session(db: Session) -> None:
    """Reset ORM/session state before each SSE poll.

    The chat events stream stays open for a long time while background tasks
    continue to update message metadata. Rolling back any open transaction and
    expiring the identity map keeps each poll from reusing stale ORM state.
    """
    if db.in_transaction():
        db.rollback()
    db.expire_all()


@router.get("/conversations", response_model=list[ConversationOut])
def list_conversations(
    project_id: str = Query(...),
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_role: str = Depends(get_current_workspace_role),
    workspace_id: str = Depends(get_current_workspace_id),
) -> list[ConversationOut]:
    get_project_in_workspace_or_404(db, project_id, workspace_id)

    conversations_query = db.query(Conversation).filter(
        Conversation.project_id == project_id,
        Conversation.workspace_id == workspace_id,
    )
    if not is_workspace_privileged_role(workspace_role):
        conversations_query = conversations_query.filter(Conversation.created_by == current_user.id)

    conversations = conversations_query.order_by(Conversation.updated_at.desc()).all()
    return [ConversationOut.model_validate(c, from_attributes=True) for c in conversations]


@router.post("/conversations", response_model=ConversationOut)
def create_conversation(
    payload: ConversationCreate,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf_guard: None = Depends(require_csrf_protection),
) -> ConversationOut:
    get_project_in_workspace_or_404(db, payload.project_id, workspace_id)

    conversation = Conversation(
        workspace_id=workspace_id,
        project_id=payload.project_id,
        title=payload.title,
        created_by=current_user.id,
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return ConversationOut.model_validate(conversation, from_attributes=True)


@router.delete("/conversations/{conversation_id}")
def delete_conversation(
    conversation_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_role: str = Depends(get_current_workspace_role),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf_guard: None = Depends(require_csrf_protection),
) -> Response:
    conversation = _get_conversation_or_404(db, conversation_id, workspace_id, current_user.id, workspace_role)

    # Delete temporary memories linked to this conversation
    db.query(Memory).filter(
        Memory.source_conversation_id == conversation_id,
        Memory.type == "temporary",
        Memory.workspace_id == workspace_id,
    ).delete()

    # Delete the conversation (CASCADE handles messages)
    db.delete(conversation)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
def list_messages(
    conversation_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_role: str = Depends(get_current_workspace_role),
    workspace_id: str = Depends(get_current_workspace_id),
) -> list[MessageOut]:
    _get_conversation_or_404(db, conversation_id, workspace_id, current_user.id, workspace_role)

    messages = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
        .all()
    )
    return [_serialize_message(message) for message in messages]


@router.get("/messages/{message_id}/memory-write", response_model=MessageMemoryWriteOut)
def get_message_memory_write_route(
    message_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_role: str = Depends(get_current_workspace_role),
    workspace_id: str = Depends(get_current_workspace_id),
) -> MessageMemoryWriteOut:
    message = (
        db.query(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .join(Project, Project.id == Conversation.project_id)
        .filter(
            Message.id == message_id,
            Message.role == "assistant",
            Conversation.workspace_id == workspace_id,
            Project.workspace_id == workspace_id,
            Project.deleted_at.is_(None),
        )
        .first()
    )
    if message is None:
        raise ApiError("not_found", "Message not found", status_code=404)
    _get_conversation_or_404(
        db,
        message.conversation_id,
        workspace_id,
        current_user.id,
        workspace_role,
    )
    run, items = get_message_memory_write(db, message_id=message_id)
    return MessageMemoryWriteOut(
        run=MemoryWriteRunOut.model_validate(run, from_attributes=True) if run is not None else None,
        items=[
            MemoryWriteItemOut.model_validate(item, from_attributes=True)
            for item in items
        ],
    )


@router.get("/messages/{message_id}/memory-learning", response_model=MessageMemoryLearningOut)
def get_message_memory_learning_route(
    message_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_role: str = Depends(get_current_workspace_role),
    workspace_id: str = Depends(get_current_workspace_id),
) -> MessageMemoryLearningOut:
    message = (
        db.query(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .join(Project, Project.id == Conversation.project_id)
        .filter(
            Message.id == message_id,
            Message.role == "assistant",
            Conversation.workspace_id == workspace_id,
            Project.workspace_id == workspace_id,
            Project.deleted_at.is_(None),
        )
        .first()
    )
    if message is None:
        raise ApiError("not_found", "Message not found", status_code=404)
    _get_conversation_or_404(
        db,
        message.conversation_id,
        workspace_id,
        current_user.id,
        workspace_role,
    )
    runs, outcomes = get_message_memory_learning(db, message_id=message_id)
    return MessageMemoryLearningOut(
        runs=[MemoryLearningRunOut.model_validate(run, from_attributes=True) for run in runs],
        outcomes=[MemoryOutcomeOut.model_validate(outcome, from_attributes=True) for outcome in outcomes],
    )


@router.get("/conversations/{conversation_id}/events")
async def stream_conversation_events(
    conversation_id: str,
    request: Request,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_role: str = Depends(get_current_workspace_role),
    workspace_id: str = Depends(get_current_workspace_id),
) -> StreamingResponse:
    enforce_rate_limit(
        request,
        scope="chat-sse",
        identifier=current_user.id,
        limit=settings.sse_rate_limit_max,
        window_seconds=settings.sse_rate_limit_window_seconds,
    )
    _get_conversation_or_404(db, conversation_id, workspace_id, current_user.id, workspace_role)

    async def _event_generator():
        emitted_signatures: dict[str, str] = {}

        while True:
            if await request.is_disconnected():
                break

            _refresh_chat_sse_session(db)
            assistant_messages = (
                db.query(Message)
                .filter(
                    Message.conversation_id == conversation_id,
                    Message.role == "assistant",
                )
                .order_by(Message.created_at.asc())
                .all()
            )

            live_message_ids: set[str] = set()
            for message in assistant_messages:
                live_metadata = _extract_live_message_metadata(message)
                if not live_metadata:
                    continue

                live_message_ids.add(message.id)
                signature = json.dumps(live_metadata, ensure_ascii=False, sort_keys=True)
                if emitted_signatures.get(message.id) == signature:
                    continue

                emitted_signatures[message.id] = signature
                yield (
                    "event: assistant_message_metadata\n"
                    f"data: {json.dumps({'id': message.id, 'metadata_json': live_metadata}, ensure_ascii=False)}\n\n"
                )

            for message_id in list(emitted_signatures):
                if message_id not in live_message_ids:
                    emitted_signatures.pop(message_id, None)

            yield "event: ping\ndata: {}\n\n"
            db.expire_all()
            await asyncio.sleep(2)

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/conversations/{conversation_id}/messages", response_model=MessageOut)
async def send_message(
    conversation_id: str,
    payload: MessageCreate,
    request: Request,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_role: str = Depends(get_current_workspace_role),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf_guard: None = Depends(require_csrf_protection),
) -> MessageOut:
    enforce_rate_limit(
        request,
        scope="chat-send",
        identifier=current_user.id,
        limit=10,
        window_seconds=60,
    )
    conversation = _get_conversation_or_404(db, conversation_id, workspace_id, current_user.id, workspace_role)
    _ensure_model_api_configured()

    # Save user message
    user_message = Message(
        conversation_id=conversation_id,
        role="user",
        content=payload.content,
    )
    db.add(user_message)
    conversation.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user_message)

    # Load recent messages for context
    recent = (
        db.query(Message)
        .filter(
            Message.conversation_id == conversation_id,
            Message.id != user_message.id,
        )
        .order_by(Message.created_at.desc())
        .limit(20)
        .all()
    )
    recent_msgs = [{"role": m.role, "content": m.content} for m in reversed(recent)]
    # Real inference
    try:
        inference_result = await orchestrate_inference(
            db,
            workspace_id=workspace_id,
            project_id=conversation.project_id,
            conversation_id=conversation_id,
            user_message=payload.content,
            recent_messages=recent_msgs,
            enable_thinking=payload.enable_thinking,
            enable_search=payload.enable_search,
        )
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        _raise_inference_api_error(exc)
    ai_response_text, ai_reasoning_content, ai_metadata_json = _normalize_inference_result(inference_result)
    if settings.dashscope_api_key:
        ai_metadata_json = _apply_pending_memory_extraction_metadata(ai_metadata_json)

    # Save AI response
    ai_message = Message(
        conversation_id=conversation_id,
        role="assistant",
        content=ai_response_text,
        reasoning_content=ai_reasoning_content,
        metadata_json=ai_metadata_json,
    )
    db.add(ai_message)

    # Update conversation.updated_at
    conversation.updated_at = datetime.now(timezone.utc)
    touch_memories_from_trace(
        db,
        retrieval_trace=ai_metadata_json.get("retrieval_trace") if isinstance(ai_metadata_json, dict) else None,
    )
    _apply_conversation_focus(
        conversation,
        retrieval_trace=ai_metadata_json.get("retrieval_trace") if isinstance(ai_metadata_json, dict) else None,
    )

    db.commit()
    db.refresh(ai_message)

    # Trigger async memory extraction (non-fatal)
    _trigger_memory_extraction(
        workspace_id,
        conversation.project_id,
        conversation_id,
        payload.content,
        ai_response_text,
        assistant_message_id=ai_message.id,
    )

    return _serialize_message(ai_message)


# ---------------------------------------------------------------------------
# Streaming SSE endpoint
# ---------------------------------------------------------------------------


@router.post("/conversations/{conversation_id}/stream")
async def stream_message(
    conversation_id: str,
    payload: MessageCreate,
    request: Request,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_role: str = Depends(get_current_workspace_role),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf_guard: None = Depends(require_csrf_protection),
) -> StreamingResponse:
    """Stream the AI response as Server-Sent Events.

    The endpoint saves the user message immediately, streams tokens as they
    arrive from the model, then persists the complete assistant message and
    triggers async memory extraction when the stream finishes.
    """
    enforce_rate_limit(
        request,
        scope="chat-send",
        identifier=current_user.id,
        limit=10,
        window_seconds=60,
    )
    conversation = _get_conversation_or_404(db, conversation_id, workspace_id, current_user.id, workspace_role)
    _ensure_model_api_configured()

    # Save user message immediately
    user_message = Message(
        conversation_id=conversation_id,
        role="user",
        content=payload.content,
    )
    db.add(user_message)
    conversation.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user_message)

    # Load recent messages for context
    recent = (
        db.query(Message)
        .filter(
            Message.conversation_id == conversation_id,
            Message.id != user_message.id,
        )
        .order_by(Message.created_at.desc())
        .limit(20)
        .all()
    )
    recent_msgs = [{"role": m.role, "content": m.content} for m in reversed(recent)]
    async def _event_generator():
        """Yield SSE-formatted lines from the streaming orchestrator."""
        full_content = ""
        full_reasoning: str | None = None
        full_metadata_json: dict[str, object] = {}
        final_event_data: dict[str, object] | None = None

        try:
            async for event in orchestrate_inference_stream(
                db,
                workspace_id=workspace_id,
                project_id=conversation.project_id,
                conversation_id=conversation_id,
                user_message=payload.content,
                recent_messages=recent_msgs,
                enable_thinking=payload.enable_thinking,
                enable_search=payload.enable_search,
                user_id=current_user.id,
            ):
                event_type = event["event"]
                data = event["data"]

                # Track accumulated content from the final event
                if event_type == "message_done":
                    full_content = data.get("content", "")
                    full_reasoning = data.get("reasoning_content")
                    raw_sources = data.get("sources")
                    if isinstance(raw_sources, list):
                        sources = [source for source in raw_sources if isinstance(source, dict)]
                        full_metadata_json = {"sources": sources} if sources else {}
                    retrieval_trace = data.get("retrieval_trace")
                    if isinstance(retrieval_trace, dict) and retrieval_trace:
                        full_metadata_json["retrieval_trace"] = retrieval_trace
                    final_event_data = dict(data)
                    continue

                yield f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

        except Exception as exc:  # noqa: BLE001
            logger.exception("SSE stream error")
            error_data = json.dumps({"message": str(exc)}, ensure_ascii=False)
            yield f"event: error\ndata: {error_data}\n\n"
            return

        if final_event_data is None and not (full_content or full_reasoning or full_metadata_json):
            return

        persisted_message_id: str | None = None
        try:
            if settings.dashscope_api_key:
                full_metadata_json = _apply_pending_memory_extraction_metadata(full_metadata_json)
            ai_message = Message(
                conversation_id=conversation_id,
                role="assistant",
                content=full_content,
                reasoning_content=full_reasoning,
                metadata_json=full_metadata_json,
            )
            db.add(ai_message)
            conversation.updated_at = datetime.now(timezone.utc)
            touch_memories_from_trace(
                db,
                retrieval_trace=full_metadata_json.get("retrieval_trace") if isinstance(full_metadata_json, dict) else None,
            )
            _apply_conversation_focus(
                conversation,
                retrieval_trace=full_metadata_json.get("retrieval_trace") if isinstance(full_metadata_json, dict) else None,
            )
            db.commit()
            persisted_message_id = ai_message.id
        except Exception:  # noqa: BLE001
            logger.exception("Failed to persist streamed assistant message")
            db.rollback()

        completion_payload = dict(final_event_data or {})
        if "content" not in completion_payload:
            completion_payload["content"] = full_content
        if "reasoning_content" not in completion_payload:
            completion_payload["reasoning_content"] = full_reasoning
        if "sources" not in completion_payload and isinstance(full_metadata_json.get("sources"), list):
            completion_payload["sources"] = full_metadata_json["sources"]
        if "retrieval_trace" not in completion_payload and isinstance(full_metadata_json.get("retrieval_trace"), dict):
            completion_payload["retrieval_trace"] = full_metadata_json["retrieval_trace"]
        if "memory_extraction_status" not in completion_payload and isinstance(full_metadata_json.get("memory_extraction_status"), str):
            completion_payload["memory_extraction_status"] = full_metadata_json["memory_extraction_status"]
        if "memory_extraction_attempts" not in completion_payload and isinstance(full_metadata_json.get("memory_extraction_attempts"), int):
            completion_payload["memory_extraction_attempts"] = full_metadata_json["memory_extraction_attempts"]
        if "memory_extraction_error" not in completion_payload and isinstance(full_metadata_json.get("memory_extraction_error"), str):
            completion_payload["memory_extraction_error"] = full_metadata_json["memory_extraction_error"]
        if persisted_message_id:
            completion_payload["id"] = persisted_message_id

        yield f"event: message_done\ndata: {json.dumps(completion_payload, ensure_ascii=False)}\n\n"

        if persisted_message_id:
            _trigger_memory_extraction(
                workspace_id,
                conversation.project_id,
                conversation_id,
                payload.content,
                full_content,
                assistant_message_id=persisted_message_id,
            )

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Voice & Image endpoints (full pipeline: ASR → LLM → TTS)
# ---------------------------------------------------------------------------


def _get_conversation_or_404(
    db: Session,
    conversation_id: str,
    workspace_id: str,
    current_user_id: str,
    workspace_role: str,
) -> Conversation:
    """Shared lookup used by voice / image endpoints."""
    conversation = (
        db.query(Conversation)
        .join(Project, Project.id == Conversation.project_id)
        .filter(
            Conversation.id == conversation_id,
            Conversation.workspace_id == workspace_id,
            Project.workspace_id == workspace_id,
            Project.deleted_at.is_(None),
        )
        .first()
    )
    if not conversation or not can_access_workspace_conversation(
        current_user_id=current_user_id,
        workspace_role=workspace_role,
        conversation_created_by=conversation.created_by,
    ):
        raise ApiError("not_found", "Conversation not found", status_code=404)
    return conversation


def _trigger_memory_extraction(
    workspace_id: str,
    project_id: str,
    conversation_id: str,
    user_text: str,
    ai_text: str,
    *,
    assistant_message_id: str | None = None,
) -> None:
    """Fire-and-forget Celery task for memory extraction."""
    if not settings.dashscope_api_key:
        return
    try:
        from app.tasks.worker_tasks import execute_memory_extraction_job, extract_memories

        if settings.env == "local":
            args = (
                workspace_id,
                project_id,
                conversation_id,
                user_text,
                ai_text,
                assistant_message_id,
            )
            logger.info("Scheduling local memory extraction in dedicated background thread")
            threading.Thread(
                target=execute_memory_extraction_job,
                args=args,
                daemon=True,
            ).start()
            return

        extract_memories.delay(
            workspace_id,
            project_id,
            conversation_id,
            user_text,
            ai_text,
            assistant_message_id,
        )
    except Exception:  # noqa: BLE001
        pass  # Celery failure is non-fatal


def _save_pipeline_messages(
    db: Session,
    conversation: Conversation,
    result: dict,
) -> Message:
    """Persist user + assistant messages from a voice/image pipeline result.

    Returns the saved assistant Message (refreshed).
    """
    if result["text_input"]:
        user_msg = Message(
            conversation_id=conversation.id,
            role="user",
            content=result["text_input"],
        )
        db.add(user_msg)

    ai_msg = Message(
        conversation_id=conversation.id,
        role="assistant",
        content=result["text_response"],
        reasoning_content=result.get("reasoning_content"),
        metadata_json=(
            _apply_pending_memory_extraction_metadata(
                {
                    **(
                        {"sources": sources}
                        if isinstance((sources := result.get("sources")), list) and sources
                        else {}
                    ),
                    **(
                        {"retrieval_trace": trace}
                        if isinstance((trace := result.get("retrieval_trace")), dict) and trace
                        else {}
                    ),
                }
            )
            if settings.dashscope_api_key
            else {
                **(
                    {"sources": sources}
                    if isinstance((sources := result.get("sources")), list) and sources
                    else {}
                ),
                **(
                    {"retrieval_trace": trace}
                    if isinstance((trace := result.get("retrieval_trace")), dict) and trace
                    else {}
                ),
            }
        ),
    )
    db.add(ai_msg)
    conversation.updated_at = datetime.now(timezone.utc)
    touch_memories_from_trace(
        db,
        retrieval_trace=ai_msg.metadata_json.get("retrieval_trace") if isinstance(ai_msg.metadata_json, dict) else None,
    )
    _apply_conversation_focus(
        conversation,
        retrieval_trace=ai_msg.metadata_json.get("retrieval_trace") if isinstance(ai_msg.metadata_json, dict) else None,
    )
    db.commit()
    db.refresh(ai_msg)
    return ai_msg


def _build_pipeline_response(ai_msg: Message, result: dict) -> dict:
    """Format the JSON response shared by voice & image endpoints."""
    return {
        "message": _serialize_message(ai_msg).model_dump(),
        "text_input": result["text_input"],
        "audio_response": (
            base64.b64encode(result["audio_response"]).decode()
            if result["audio_response"]
            else None
        ),
    }


@router.post("/conversations/{conversation_id}/voice")
async def send_voice_message(
    conversation_id: str,
    request: Request,
    audio: UploadFile = File(...),
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_role: str = Depends(get_current_workspace_role),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf_guard: None = Depends(require_csrf_protection),
) -> dict:
    """Accept an audio file, run ASR → LLM (with memory/RAG) → TTS, return
    the AI text response plus optional base64-encoded audio."""
    enforce_rate_limit(
        request,
        scope="chat-send",
        identifier=current_user.id,
        limit=10,
        window_seconds=60,
    )
    conversation = _get_conversation_or_404(db, conversation_id, workspace_id, current_user.id, workspace_role)
    _ensure_model_api_configured()

    audio_bytes = await _read_validated_upload(audio, kind="audio")

    # Run full voice pipeline
    try:
        result = await orchestrate_voice_inference(
            db,
            workspace_id=workspace_id,
            project_id=conversation.project_id,
            conversation_id=conversation_id,
            audio_bytes=audio_bytes,
            audio_filename=audio.filename or "recording.webm",
        )
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        _raise_inference_api_error(exc)

    # Persist messages
    ai_msg = _save_pipeline_messages(db, conversation, result)

    # Async memory extraction
    _trigger_memory_extraction(
        workspace_id, conversation.project_id, conversation_id,
        result["text_input"], result["text_response"],
        assistant_message_id=ai_msg.id,
    )

    return _build_pipeline_response(ai_msg, result)


@router.post("/conversations/{conversation_id}/dictate")
async def dictate_voice_input(
    conversation_id: str,
    request: Request,
    audio: UploadFile = File(...),
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_role: str = Depends(get_current_workspace_role),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf_guard: None = Depends(require_csrf_protection),
) -> dict:
    """Transcribe a recorded utterance into text without sending it to the model."""
    enforce_rate_limit(
        request,
        scope="chat-dictate",
        identifier=current_user.id,
        limit=10,
        window_seconds=60,
    )
    conversation = _get_conversation_or_404(db, conversation_id, workspace_id, current_user.id, workspace_role)
    _ensure_model_api_configured()

    audio_bytes = await _read_validated_upload(audio, kind="audio")

    try:
        text_input = await transcribe_audio_input_for_project(
            db,
            project_id=conversation.project_id,
            audio_bytes=audio_bytes,
            filename=audio.filename or "recording.webm",
            content_type=_normalize_media_type(audio.content_type) or None,
        )
    except Exception as exc:  # noqa: BLE001
        _raise_inference_api_error(exc)

    return {"text_input": text_input.strip()}


@router.post("/conversations/{conversation_id}/speech")
async def synthesize_message_audio(
    conversation_id: str,
    payload: MessageCreate,
    request: Request,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_role: str = Depends(get_current_workspace_role),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf_guard: None = Depends(require_csrf_protection),
) -> dict:
    """Synthesize a text message into audio without creating new chat messages."""
    enforce_rate_limit(
        request,
        scope="chat-speech",
        identifier=current_user.id,
        limit=20,
        window_seconds=60,
    )
    conversation = _get_conversation_or_404(db, conversation_id, workspace_id, current_user.id, workspace_role)
    _ensure_model_api_configured()

    text = clamp_voice_response_text(payload.content or "")
    if not text:
        raise ApiError("bad_request", "Text is required", status_code=400)

    try:
        audio_response = await synthesize_speech_for_project(
            db,
            project_id=conversation.project_id,
            text=text,
        )
    except Exception as exc:  # noqa: BLE001
        _raise_inference_api_error(exc)

    return {
        "audio_response": base64.b64encode(audio_response).decode(),
    }


@router.post("/conversations/{conversation_id}/image")
async def send_image_message(
    conversation_id: str,
    request: Request,
    image: UploadFile = File(...),
    audio: UploadFile | None = File(None),
    prompt: str | None = Form(None),
    enable_thinking: bool | None = Form(None),
    enable_search: bool | None = Form(None),
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_role: str = Depends(get_current_workspace_role),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _csrf_guard: None = Depends(require_csrf_protection),
) -> dict:
    """Accept an image (+ optional audio), run the multimodal pipeline:
    (optional ASR) + Vision/LLM → TTS, return text + optional audio."""
    enforce_rate_limit(
        request,
        scope="chat-send",
        identifier=current_user.id,
        limit=10,
        window_seconds=60,
    )
    conversation = _get_conversation_or_404(db, conversation_id, workspace_id, current_user.id, workspace_role)
    _ensure_model_api_configured()

    image_bytes = await _read_validated_upload(image, kind="image")
    audio_bytes = await _read_validated_upload(audio, kind="audio") if audio else None
    prompt_text = (prompt or "").strip()
    effective_prompt = prompt_text if (prompt_text and not audio_bytes) else ("请描述这张图片" if not audio_bytes else None)

    # Run full pipeline with image (and optional voice input)
    try:
        result = await orchestrate_voice_inference(
            db,
            workspace_id=workspace_id,
            project_id=conversation.project_id,
            conversation_id=conversation_id,
            audio_bytes=audio_bytes,
            audio_filename=audio.filename if audio else None,
            image_bytes=image_bytes,
            image_mime_type=_normalize_media_type(image.content_type) or "image/jpeg",
            text_input=effective_prompt,
            enable_thinking=enable_thinking,
            enable_search=enable_search,
        )
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        _raise_inference_api_error(exc)

    # Persist messages
    ai_msg = _save_pipeline_messages(db, conversation, result)

    # Async memory extraction
    _trigger_memory_extraction(
        workspace_id, conversation.project_id, conversation_id,
        result["text_input"], result["text_response"],
        assistant_message_id=ai_msg.id,
    )

    return _build_pipeline_response(ai_msg, result)
