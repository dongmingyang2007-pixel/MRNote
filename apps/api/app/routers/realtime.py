"""WebSocket endpoint for real-time full-duplex voice conversation."""
from __future__ import annotations

import asyncio
import json
import logging
import secrets
import threading
from contextlib import suppress
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import (
    authenticate_access_token,
    can_access_workspace_conversation,
    get_current_user,
    is_token_revoked_for_user,
    require_allowed_origin,
)
from app.core.errors import ApiError
from app.db.session import SessionLocal
from app.models import Conversation, Membership, Message, ModelCatalog, Project, User
from app.schemas.conversation import MessageOut
from app.services.context_loader import (
    extract_personality,
    load_recent_messages,
)
from app.services.composed_realtime import ComposedRealtimeSession, decode_pending_media
from app.services.asr_client import RealtimeTranscriptionBridge
from app.services.memory_context import (
    build_conversation_focus_metadata,
    build_memory_context,
    touch_memories_from_trace,
)
from app.services.realtime_bridge import (
    RealtimeSession,
    register_session,
    unregister_session,
)
from app.services.dashscope_client import UpstreamServiceError
from app.services.pipeline_models import DEFAULT_PIPELINE_MODELS, resolve_pipeline_model_id
from app.services.qwen_official_catalog import find_model
from app.services.runtime_state import runtime_state
from app.services.voice_response_limits import append_voice_response_instruction
from app.tasks.worker_tasks import execute_memory_extraction_job, extract_memories

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/realtime", tags=["realtime"])
SESSION_MONITOR_INTERVAL_SECONDS = 5.0
UPSTREAM_CONNECT_TIMEOUT_SECONDS = 10.0
UPSTREAM_SESSION_UPDATE_TIMEOUT_SECONDS = 10.0
COMPOSED_TRAILING_AUDIO_GRACE_SECONDS = 0.75
COMPOSED_AUTO_START_DEBOUNCE_SECONDS = 0.55
COMPOSED_TRANSCRIPT_FINAL_TIMEOUT_SECONDS = 1.25
REALTIME_TRANSCRIPT_SETTLE_SECONDS = 0.25
REALTIME_CAMERA_FRAME_MAX_BYTES = 500 * 1024
REALTIME_WS_TICKET_SCOPE = "realtime_ws_ticket"
REALTIME_WS_TICKET_TTL_SECONDS = 60
MODEL_API_UNCONFIGURED_MESSAGE = (
    "AI service is not configured. Set DASHSCOPE_API_KEY and restart the API service."
)


def _serialize_message_payload(message: Message) -> dict[str, object]:
    return MessageOut.model_validate(message, from_attributes=True).model_dump(mode="json")


async def _authenticate_websocket(ws: WebSocket) -> tuple[User, dict[str, object]]:
    """Validate same-site cookie auth for the realtime websocket."""
    origin = ws.headers.get("origin")
    if not origin or not settings.is_origin_allowed(settings.normalize_origin(origin)):
        raise ApiError("forbidden_origin", "Origin not allowed", status_code=403)

    access_token = ws.cookies.get(settings.access_cookie_name)
    if not access_token:
        ticket = str(ws.query_params.get("ticket") or "").strip()
        if ticket:
            ticket_state = runtime_state.pop_json(REALTIME_WS_TICKET_SCOPE, ticket)
            ticket_access_token = ticket_state.get("access_token") if ticket_state else None
            if isinstance(ticket_access_token, str) and ticket_access_token:
                access_token = ticket_access_token
    if not access_token:
        raise ApiError("unauthorized", "Authentication required", status_code=401)

    db: Session = SessionLocal()
    try:
        return authenticate_access_token(db=db, access_token=access_token)
    finally:
        db.close()


@router.get("/ws-ticket")
def create_realtime_ws_ticket(
    request: Request,
    current_user: User = Depends(get_current_user),
    _: None = Depends(require_allowed_origin),
) -> dict[str, object]:
    access_token = getattr(request.state, "access_token", None)
    if not isinstance(access_token, str) or not access_token:
        raise ApiError("unauthorized", "Authentication required", status_code=401)

    ticket = secrets.token_urlsafe(32)
    runtime_state.set_json(
        REALTIME_WS_TICKET_SCOPE,
        ticket,
        {
            "access_token": access_token,
            "user_id": current_user.id,
        },
        ttl_seconds=REALTIME_WS_TICKET_TTL_SECONDS,
    )
    return {
        "ticket": ticket,
        "expires_in_seconds": REALTIME_WS_TICKET_TTL_SECONDS,
    }


def _load_authorized_conversation(
    db: Session,
    *,
    current_user_id: str,
    project_id: str,
    conversation_id: str,
) -> tuple[Conversation, Membership]:
    row = (
        db.query(Conversation, Membership)
        .join(Project, Project.id == Conversation.project_id)
        .join(Membership, Membership.workspace_id == Project.workspace_id)
        .filter(
            Conversation.id == conversation_id,
            Conversation.project_id == project_id,
            Project.id == project_id,
            Project.deleted_at.is_(None),
            Conversation.workspace_id == Project.workspace_id,
            Membership.user_id == current_user_id,
        )
        .first()
    )
    if not row:
        raise ApiError("forbidden", "Realtime session access denied", status_code=403)

    conversation, membership = row
    if not can_access_workspace_conversation(
        current_user_id=current_user_id,
        workspace_role=membership.role or "owner",
        conversation_created_by=conversation.created_by,
    ):
        raise ApiError("forbidden", "Realtime session access denied", status_code=403)
    return conversation, membership


def _resolve_realtime_model_id(db: Session, project_id: str) -> str:
    model_id = resolve_pipeline_model_id(db, project_id=project_id, model_type="realtime")
    return model_id or DEFAULT_PIPELINE_MODELS["realtime"]


def _resolve_realtime_asr_model_id(db: Session, project_id: str) -> str:
    model_id = resolve_pipeline_model_id(db, project_id=project_id, model_type="realtime_asr")
    return model_id or DEFAULT_PIPELINE_MODELS["realtime_asr"]


async def _send_session_end(
    ws: WebSocket,
    *,
    reason: str,
    close_code: int = 1000,
) -> None:
    try:
        await ws.send_json({"type": "session.end", "reason": reason})
    except Exception:
        pass
    try:
        await ws.close(code=close_code, reason=reason)
    except Exception:
        pass


async def _send_error_and_close(
    ws: WebSocket,
    *,
    code: str,
    message: str,
    close_code: int = 1011,
) -> None:
    try:
        await ws.send_json({"type": "error", "code": code, "message": message})
    except Exception:
        pass
    try:
        await ws.close(code=close_code, reason=message)
    except Exception:
        pass


async def _ensure_model_api_configured(ws: WebSocket) -> bool:
    if settings.dashscope_api_key:
        return True
    await _send_error_and_close(
        ws,
        code="model_api_unconfigured",
        message=MODEL_API_UNCONFIGURED_MESSAGE,
        close_code=1011,
    )
    return False


async def _build_realtime_context(
    db: Session,
    session: RealtimeSession,
    *,
    user_message: str,
    include_recent_history: bool,
) -> str:
    """Build layered prompt context for a realtime session."""
    recent_messages = load_recent_messages(
        db,
        conversation_id=session.conversation_id,
        limit=max(settings.realtime_context_history_turns * 2, 0),
    )
    project = (
        db.query(Project)
        .filter(
            Project.id == session.project_id,
            Project.workspace_id == session.workspace_id,
            Project.deleted_at.is_(None),
        )
        .first()
    )
    context = await build_memory_context(
        db,
        workspace_id=session.workspace_id,
        project_id=session.project_id,
        conversation_id=session.conversation_id,
        user_message=user_message,
        recent_messages=recent_messages,
        include_recent_history=include_recent_history,
        personality=extract_personality(project.description) if project else "",
    )
    session._active_turn_retrieval_trace = context.retrieval_trace
    return append_voice_response_instruction(context.system_prompt)


async def _load_initial_context(
    db: Session,
    session: RealtimeSession,
) -> str:
    """Load initial layered prompt context for realtime sessions."""
    return await _build_realtime_context(
        db,
        session,
        user_message="",
        include_recent_history=True,
    )


async def _refresh_realtime_context_and_request_response(
    session: RealtimeSession,
    *,
    user_text: str,
) -> None:
    """Refresh the native realtime prompt with the latest turn context, then respond."""
    system_prompt: str | None = None
    session._active_turn_retrieval_trace = None
    try:
        db: Session = SessionLocal()
        try:
            system_prompt = await _build_realtime_context(
                db,
                session,
                user_message=user_text,
                include_recent_history=True,
            )
        finally:
            db.close()
    except Exception:
        logger.exception("Failed to build realtime turn context; falling back to current instructions")

    try:
        if system_prompt:
            await session.send_session_update(system_prompt)
        await session.request_response()
    except Exception:
        logger.exception("Failed to update realtime session before response")


def _schedule_realtime_context_refresh(
    session: RealtimeSession,
    *,
    user_text: str,
) -> None:
    transcript = str(user_text or "").strip()
    if not transcript or not session._awaiting_transcript_response:
        return

    session._latest_transcript_completion = transcript
    existing = session._pending_response_refresh_task
    if existing is not None and not existing.done():
        existing.cancel()

    async def _runner(expected_text: str) -> None:
        try:
            await asyncio.sleep(REALTIME_TRANSCRIPT_SETTLE_SECONDS)
            if (
                session._latest_transcript_completion != expected_text
                or session._response_request_started_for_current_input
            ):
                return
            session._response_request_started_for_current_input = True
            session._awaiting_transcript_response = False
            await _refresh_realtime_context_and_request_response(
                session,
                user_text=expected_text,
            )
        except asyncio.CancelledError:
            return
        finally:
            if session._pending_response_refresh_task is asyncio.current_task():
                session._pending_response_refresh_task = None

    session._pending_response_refresh_task = asyncio.create_task(_runner(transcript))


def _trigger_realtime_memory_extraction(
    workspace_id: str,
    project_id: str,
    conversation_id: str,
    user_text: str,
    ai_text: str,
    *,
    assistant_message_id: str | None = None,
) -> None:
    if not settings.dashscope_api_key:
        return
    try:
        if settings.env == "local":
            threading.Thread(
                target=execute_memory_extraction_job,
                args=(
                    workspace_id,
                    project_id,
                    conversation_id,
                    user_text,
                    ai_text,
                    assistant_message_id,
                ),
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
        logger.debug("Failed to dispatch realtime memory extraction", exc_info=True)


async def _post_turn_tasks(
    ws: WebSocket,
    session: RealtimeSession,
    user_text: str,
    ai_text: str,
    *,
    assistant_metadata_json: dict[str, object] | None = None,
) -> None:
    """Save messages to DB and run async tasks after a conversation turn."""
    if not user_text or not ai_text:
        return

    # Persist messages to database
    db_save: Session = SessionLocal()
    assistant_payload: dict[str, object] | None = None
    user_payload: dict[str, object] | None = None
    try:
        now = datetime.now(timezone.utc)
        user_message = Message(
            conversation_id=session.conversation_id,
            role="user",
            content=user_text,
            created_at=now,
        )
        assistant_metadata_json = dict(assistant_metadata_json or {})
        assistant_message = Message(
            conversation_id=session.conversation_id,
            role="assistant",
            content=ai_text,
            created_at=now,
            metadata_json=assistant_metadata_json,
        )
        db_save.add(user_message)
        db_save.add(assistant_message)
        conversation = db_save.get(Conversation, session.conversation_id)
        if conversation is not None:
            conversation.updated_at = now
            conversation.metadata_json = build_conversation_focus_metadata(
                existing_metadata=conversation.metadata_json if isinstance(conversation.metadata_json, dict) else {},
                retrieval_trace=assistant_metadata_json.get("retrieval_trace"),
                updated_at=now,
            )
        touch_memories_from_trace(
            db_save,
            retrieval_trace=assistant_metadata_json.get("retrieval_trace"),
            used_at=now,
        )
        db_save.commit()
        db_save.refresh(user_message)
        db_save.refresh(assistant_message)
        user_payload = _serialize_message_payload(user_message)
        assistant_payload = _serialize_message_payload(assistant_message)
    except Exception:
        db_save.rollback()
        logger.exception("Failed to save voice turn messages")
    finally:
        db_save.close()

    if user_payload and assistant_payload:
        try:
            await ws.send_json(
                {
                    "type": "turn.persisted",
                    "user_message": user_payload,
                    "assistant_message": assistant_payload,
                }
            )
        except Exception:
            logger.debug("Failed to send realtime persistence notice", exc_info=True)

    _trigger_realtime_memory_extraction(
        session.workspace_id,
        session.project_id,
        session.conversation_id,
        user_text,
        ai_text,
        assistant_message_id=assistant_payload["id"] if assistant_payload else None,
    )

    # Refresh layered context after a few turns so the next turn sees the latest
    # memories, summaries, and relevant linked documents.
    if session.turn_count % settings.realtime_rag_refresh_turns == 0:
        try:
            db: Session = SessionLocal()
            try:
                system_prompt = await _build_realtime_context(
                    db,
                    session,
                    user_message=user_text,
                    include_recent_history=True,
                )
                await session.send_session_update(system_prompt)
            finally:
                db.close()
        except Exception:
            logger.exception("Failed to refresh RAG context")


def _load_llm_capabilities(db: Session, project_id: str) -> tuple[str, set[str]]:
    llm_model_id = resolve_pipeline_model_id(db, project_id=project_id, model_type="llm")
    llm_entry = (
        db.query(ModelCatalog)
        .filter(ModelCatalog.model_id == llm_model_id, ModelCatalog.is_active.is_(True))
        .first()
    )
    capabilities = {str(value).lower() for value in (llm_entry.capabilities or [])} if llm_entry else set()
    official = find_model(llm_model_id)
    if official:
        capabilities.update(str(value).lower() for value in official.get("input_modalities", []))
        capabilities.update(str(value).lower() for value in official.get("output_modalities", []))
        capabilities.update(str(value).lower() for value in official.get("supported_tools", []))
        capabilities.update(str(value).lower() for value in official.get("supported_features", []))
    return llm_model_id, capabilities


async def _persist_composed_turn(
    ws: WebSocket,
    session: ComposedRealtimeSession,
    user_text: str,
    ai_text: str,
    *,
    assistant_reasoning_content: str | None = None,
    assistant_metadata_json: dict[str, object] | None = None,
) -> None:
    if not user_text or not ai_text:
        return

    db: Session = SessionLocal()
    user_payload: dict[str, object] | None = None
    assistant_payload: dict[str, object] | None = None
    try:
        now = datetime.now(timezone.utc)
        user_message = Message(
            conversation_id=session.conversation_id,
            role="user",
            content=user_text,
            created_at=now,
        )
        assistant_message = Message(
            conversation_id=session.conversation_id,
            role="assistant",
            content=ai_text,
            reasoning_content=assistant_reasoning_content,
            metadata_json=assistant_metadata_json or {},
            created_at=now,
        )
        db.add(user_message)
        db.add(assistant_message)
        conversation = db.get(Conversation, session.conversation_id)
        if conversation is not None:
            conversation.updated_at = now
            conversation.metadata_json = build_conversation_focus_metadata(
                existing_metadata=conversation.metadata_json if isinstance(conversation.metadata_json, dict) else {},
                retrieval_trace=(assistant_metadata_json or {}).get("retrieval_trace"),
                updated_at=now,
            )
        touch_memories_from_trace(
            db,
            retrieval_trace=(assistant_metadata_json or {}).get("retrieval_trace"),
            used_at=now,
        )
        db.commit()
        db.refresh(user_message)
        db.refresh(assistant_message)
        user_payload = _serialize_message_payload(user_message)
        assistant_payload = _serialize_message_payload(assistant_message)
    except Exception:
        db.rollback()
        logger.exception("Failed to save composed realtime turn")
    finally:
        db.close()

    if user_payload and assistant_payload:
        try:
            await ws.send_json(
                {
                    "type": "turn.persisted",
                    "user_message": user_payload,
                    "assistant_message": assistant_payload,
                }
            )
        except Exception:
            logger.debug("Failed to send composed realtime persistence notice", exc_info=True)

    _trigger_realtime_memory_extraction(
        session.workspace_id,
        session.project_id,
        session.conversation_id,
        user_text,
        ai_text,
        assistant_message_id=assistant_payload["id"] if assistant_payload else None,
    )


async def _composed_idle_monitor(
    ws: WebSocket,
    session: ComposedRealtimeSession,
    auth_payload: dict[str, object],
) -> str | None:
    start_time = asyncio.get_event_loop().time()
    idle_warned = False
    while True:
        await asyncio.sleep(SESSION_MONITOR_INTERVAL_SECONDS)
        if is_token_revoked_for_user(session.user_id, auth_payload):
            return "auth_revoked"
        if session.idle_seconds >= settings.realtime_close_timeout_seconds:
            return "timeout"
        if not idle_warned and session.idle_seconds >= settings.realtime_idle_timeout_seconds:
            idle_warned = True
            try:
                await ws.send_json({"type": "session.idle"})
            except Exception:
                pass
        elif session.idle_seconds < settings.realtime_idle_timeout_seconds:
            idle_warned = False
        elapsed = asyncio.get_event_loop().time() - start_time
        if elapsed >= settings.realtime_max_session_seconds:
            return "max_duration"


async def _upstream_listener(
    ws: WebSocket,
    session: RealtimeSession,
) -> dict[str, str] | None:
    """Listen for DashScope upstream events and relay to client."""
    try:
        async for raw_msg in session._upstream_ws:
            if isinstance(raw_msg, bytes):
                continue
            event = json.loads(raw_msg)
            outgoing = await session.handle_upstream_event(event)
            for item in outgoing:
                if isinstance(item, bytes):
                    await ws.send_bytes(item)
                else:
                    await ws.send_json(item)

            if event.get("type") == "conversation.item.input_audio_transcription.completed":
                transcript = str(event.get("transcript") or "").strip()
                if transcript:
                    _schedule_realtime_context_refresh(
                        session,
                        user_text=transcript,
                    )

            if event.get("type") == "response.done" and session.consume_response_done_finalization():
                user_text, ai_text = session.get_turn_texts()
                assistant_metadata_json = {}
                retrieval_trace = getattr(session, "_active_turn_retrieval_trace", None)
                if isinstance(retrieval_trace, dict) and retrieval_trace:
                    assistant_metadata_json["retrieval_trace"] = retrieval_trace
                asyncio.create_task(
                    _post_turn_tasks(
                        ws,
                        session,
                        user_text,
                        ai_text,
                        assistant_metadata_json=assistant_metadata_json,
                    )
                )
        if session.state not in (session.state.CLOSING, session.state.CLOSED):
            return {
                "code": "upstream_disconnected",
                "message": "AI 暂时无响应",
            }
        return None
    except Exception as exc:
        logger.warning("Upstream listener error: %s", exc)
        return {
            "code": "upstream_disconnected",
            "message": "AI 暂时无响应",
        }


async def _idle_monitor(
    ws: WebSocket,
    session: RealtimeSession,
    auth_payload: dict[str, object],
) -> str | None:
    """Monitor for idle timeout and max session duration."""
    start_time = asyncio.get_event_loop().time()
    idle_warned = False
    while session.state not in (session.state.CLOSING, session.state.CLOSED):
        await asyncio.sleep(SESSION_MONITOR_INTERVAL_SECONDS)
        if is_token_revoked_for_user(session.user_id, auth_payload):
            return "auth_revoked"
        if session.idle_seconds >= settings.realtime_close_timeout_seconds:
            return "timeout"
        if not idle_warned and session.idle_seconds >= settings.realtime_idle_timeout_seconds:
            idle_warned = True
            try:
                await ws.send_json({"type": "session.idle"})
            except Exception:
                pass
        elif session.idle_seconds < settings.realtime_idle_timeout_seconds:
            idle_warned = False
        elapsed = asyncio.get_event_loop().time() - start_time
        if elapsed >= settings.realtime_max_session_seconds:
            return "max_duration"
    return None


@router.websocket("/dictate")
async def realtime_dictate(ws: WebSocket) -> None:
    """Realtime dictation endpoint for the standard chat input mic."""
    user: User | None = None
    auth_payload: dict[str, object] | None = None
    receive_task: asyncio.Task | None = None
    transcription_task: asyncio.Task[dict[str, str]] | None = None
    transcription_bridge: RealtimeTranscriptionBridge | None = None

    try:
        try:
            user, auth_payload = await _authenticate_websocket(ws)
        except ApiError as exc:
            await ws.accept()
            await ws.send_json({"type": "error", "code": exc.code, "message": exc.message})
            await ws.close(code=4001 if exc.status_code == 401 else 4003, reason=exc.message)
            return

        await ws.accept()
        if not await _ensure_model_api_configured(ws):
            return

        init_raw = await asyncio.wait_for(ws.receive_json(), timeout=10)
        if init_raw.get("type") != "session.start":
            await ws.send_json({"type": "error", "code": "bad_request", "message": "Expected session.start"})
            await ws.close()
            return

        conversation_id = init_raw.get("conversation_id")
        project_id = init_raw.get("project_id")
        if not conversation_id or not project_id:
            await ws.send_json({"type": "error", "code": "bad_request", "message": "Missing conversation_id or project_id"})
            await ws.close()
            return

        db: Session = SessionLocal()
        try:
            _load_authorized_conversation(
                db,
                current_user_id=user.id,
                project_id=project_id,
                conversation_id=conversation_id,
            )
            realtime_asr_model_id = _resolve_realtime_asr_model_id(db, project_id)
        except ApiError as exc:
            await ws.send_json({"type": "error", "code": exc.code, "message": exc.message})
            await ws.close(code=4003, reason=exc.message)
            return
        finally:
            db.close()

        await ws.send_json({"type": "session.ready"})
        receive_task = asyncio.create_task(ws.receive())

        while True:
            wait_set: set[asyncio.Task] = {receive_task}
            if transcription_task is not None:
                wait_set.add(transcription_task)

            done, _pending = await asyncio.wait(wait_set, return_when=asyncio.FIRST_COMPLETED)

            if transcription_task is not None and transcription_task in done:
                event = transcription_task.result()
                event_type = event.get("type", "")

                if event_type == "transcript.partial":
                    await ws.send_json({"type": "transcript.partial", "text": event.get("text", "")})
                elif event_type == "transcript.final":
                    await ws.send_json({"type": "transcript.final", "text": event.get("text", "")})
                    await transcription_bridge.close()
                    transcription_bridge = None
                elif event_type == "transcript.empty":
                    await ws.send_json({
                        "type": "turn.notice",
                        "code": "empty_transcription",
                        "message": "未识别到语音，请重试。",
                    })
                    await transcription_bridge.close()
                    transcription_bridge = None
                elif event_type == "error":
                    await _send_error_and_close(
                        ws,
                        code="upstream_unavailable",
                        message="AI 暂时无响应，请重试",
                    )
                    break
                elif event_type == "session.closed":
                    transcription_bridge = None

                transcription_task = (
                    asyncio.create_task(transcription_bridge.next_event())
                    if transcription_bridge is not None
                    else None
                )

            if receive_task in done:
                try:
                    message = receive_task.result()
                except WebSocketDisconnect:
                    break

                if message["type"] == "websocket.disconnect":
                    break

                if "bytes" in message and message["bytes"]:
                    if transcription_bridge is None:
                        transcription_bridge = RealtimeTranscriptionBridge(model=realtime_asr_model_id)
                        try:
                            await asyncio.wait_for(
                                transcription_bridge.connect(),
                                timeout=UPSTREAM_CONNECT_TIMEOUT_SECONDS,
                            )
                        except TimeoutError:
                            await _send_error_and_close(
                                ws,
                                code="upstream_timeout",
                                message="AI 暂时无响应，请重试",
                                close_code=1013,
                            )
                            break
                        except UpstreamServiceError:
                            await _send_error_and_close(
                                ws,
                                code="upstream_unavailable",
                                message="AI 暂时无响应，请重试",
                            )
                            break
                        transcription_task = asyncio.create_task(transcription_bridge.next_event())
                    try:
                        await transcription_bridge.send_audio_chunk(message["bytes"])
                    except UpstreamServiceError:
                        await _send_error_and_close(
                            ws,
                            code="upstream_unavailable",
                            message="AI 暂时无响应，请重试",
                        )
                        break

                elif "text" in message and message["text"]:
                    data = json.loads(message["text"])
                    msg_type = data.get("type")
                    if msg_type == "session.end":
                        break
                    if msg_type == "audio.stop":
                        if transcription_bridge is None:
                            await ws.send_json({
                                "type": "turn.notice",
                                "code": "no_audio_input",
                                "message": "未检测到音频，请检查麦克风。",
                            })
                        else:
                            try:
                                await transcription_bridge.commit()
                            except UpstreamServiceError:
                                await _send_error_and_close(
                                    ws,
                                    code="upstream_unavailable",
                                    message="AI 暂时无响应，请重试",
                                )
                                break

                receive_task = asyncio.create_task(ws.receive())
    except Exception as exc:
        logger.exception("Realtime dictate error: %s", exc)
        try:
            await ws.send_json({"type": "error", "code": "internal", "message": "Internal server error"})
        except Exception:
            pass
    finally:
        if receive_task is not None and not receive_task.done():
            receive_task.cancel()
        if transcription_task is not None and not transcription_task.done():
            transcription_task.cancel()
        if transcription_bridge is not None:
            await transcription_bridge.close()
        if user is not None and auth_payload is not None and is_token_revoked_for_user(user.id, auth_payload):
            with suppress(Exception):
                await ws.close(code=4001, reason="auth_revoked")
            return
        with suppress(Exception):
            await ws.close()


@router.websocket("/voice")
async def realtime_voice(ws: WebSocket) -> None:
    """Full-duplex voice conversation WebSocket endpoint."""
    user: User | None = None
    auth_payload: dict[str, object] | None = None

    try:
        user, auth_payload = await _authenticate_websocket(ws)
    except ApiError as exc:
        await ws.accept()
        await ws.send_json({"type": "error", "code": exc.code, "message": exc.message})
        await ws.close(code=4001 if exc.status_code == 401 else 4003, reason=exc.message)
        return

    await ws.accept()
    if not await _ensure_model_api_configured(ws):
        return

    session: RealtimeSession | None = None

    try:
        init_raw = await asyncio.wait_for(ws.receive_json(), timeout=10)
        if init_raw.get("type") != "session.start":
            await ws.send_json({"type": "error", "code": "bad_request", "message": "Expected session.start"})
            await ws.close()
            return

        conversation_id = init_raw.get("conversation_id")
        project_id = init_raw.get("project_id")

        if not conversation_id or not project_id:
            await ws.send_json({"type": "error", "code": "bad_request", "message": "Missing conversation_id or project_id"})
            await ws.close()
            return

        db: Session = SessionLocal()
        try:
            conversation, membership = _load_authorized_conversation(
                db,
                current_user_id=user.id,
                project_id=project_id,
                conversation_id=conversation_id,
            )
            session = RealtimeSession(
                workspace_id=conversation.workspace_id,
                project_id=conversation.project_id,
                conversation_id=conversation.id,
                user_id=user.id,
                upstream_model=_resolve_realtime_model_id(db, conversation.project_id),
                input_transcription_model=_resolve_realtime_asr_model_id(db, conversation.project_id),
            )

            if not await register_session(user.id, session):
                await ws.send_json({"type": "error", "code": "concurrent_limit", "message": "您已有一个进行中的对话"})
                await ws.close()
                return

            _ = membership
            system_prompt = await _load_initial_context(db, session)
        except ApiError as exc:
            await ws.send_json({"type": "error", "code": exc.code, "message": exc.message})
            await ws.close(code=4003, reason=exc.message)
            return
        finally:
            db.close()

        try:
            await asyncio.wait_for(
                session.connect_upstream(),
                timeout=UPSTREAM_CONNECT_TIMEOUT_SECONDS,
            )
            await asyncio.wait_for(
                session.send_initial_session_update(system_prompt),
                timeout=UPSTREAM_SESSION_UPDATE_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            await _send_error_and_close(
                ws,
                code="upstream_timeout",
                message="AI 暂时无响应",
                close_code=1013,
            )
            return
        except UpstreamServiceError as exc:
            logger.warning("Realtime upstream setup failed: %s", exc)
            await _send_error_and_close(
                ws,
                code="upstream_unavailable",
                message="AI 暂时无响应",
            )
            return
        except Exception as exc:
            logger.warning("Realtime upstream connection error: %s", exc)
            await _send_error_and_close(
                ws,
                code="upstream_unavailable",
                message="AI 暂时无响应",
            )
            return

        await ws.send_json({"type": "session.ready"})

        upstream_task = asyncio.create_task(_upstream_listener(ws, session))
        idle_task = asyncio.create_task(_idle_monitor(ws, session, auth_payload or {}))
        receive_task = asyncio.create_task(ws.receive())

        try:
            while True:
                done, _pending = await asyncio.wait(
                    {receive_task, upstream_task, idle_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )

                if upstream_task in done:
                    upstream_error = upstream_task.result()
                    if upstream_error:
                        await _send_error_and_close(
                            ws,
                            code=upstream_error["code"],
                            message=upstream_error["message"],
                        )
                    break

                if idle_task in done:
                    end_reason = idle_task.result()
                    if end_reason:
                        await _send_session_end(
                            ws,
                            reason=end_reason,
                            close_code=4001 if end_reason == "auth_revoked" else 1000,
                        )
                    break

                if receive_task in done:
                    try:
                        message = receive_task.result()
                    except WebSocketDisconnect:
                        break

                    if message["type"] == "websocket.disconnect":
                        break

                    if "bytes" in message and message["bytes"]:
                        await session.relay_audio_to_upstream(message["bytes"])

                    elif "text" in message and message["text"]:
                        data = json.loads(message["text"])
                        msg_type = data.get("type")

                        if msg_type == "session.end":
                            break
                        elif msg_type == "audio.stop" and session._upstream_ws:
                            session._awaiting_transcript_response = True
                            session._response_request_started_for_current_input = False
                            session._latest_transcript_completion = ""
                            if (
                                session._pending_response_refresh_task is not None
                                and not session._pending_response_refresh_task.done()
                            ):
                                session._pending_response_refresh_task.cancel()
                                session._pending_response_refresh_task = None
                            await session._upstream_ws.send(
                                json.dumps({"type": "input_audio_buffer.commit"})
                            )
                        elif msg_type == "input.interrupt":
                            replies = await session.handle_client_message(msg_type, data)
                            for reply in replies:
                                await ws.send_json(reply)
                        elif msg_type == "input.image.append":
                            data_url = str(data.get("data_url") or "")
                            if not data_url:
                                await ws.send_json({
                                    "type": "error",
                                    "code": "bad_request",
                                    "message": "Missing image payload",
                                })
                            else:
                                try:
                                    pending_media = decode_pending_media(
                                        data_url=data_url,
                                        filename="camera-frame.jpg",
                                        max_bytes=REALTIME_CAMERA_FRAME_MAX_BYTES,
                                    )
                                    if (
                                        pending_media.kind != "image"
                                        or pending_media.mime_type != "image/jpeg"
                                    ):
                                        raise ApiError(
                                            "unsupported_media_type",
                                            "Realtime camera frames must be JPEG images",
                                            status_code=415,
                                        )
                                    await session.relay_image_to_upstream(pending_media.data)
                                except ApiError as exc:
                                    await ws.send_json({
                                        "type": "error",
                                        "code": exc.code,
                                        "message": exc.message,
                                    })

                    receive_task = asyncio.create_task(ws.receive())
        except WebSocketDisconnect:
            pass
        finally:
            if not receive_task.done():
                receive_task.cancel()
            upstream_task.cancel()
            idle_task.cancel()

    except Exception as exc:
        logger.exception("Realtime voice error: %s", exc)
        try:
            await ws.send_json({"type": "error", "code": "internal", "message": "Internal server error"})
        except Exception:
            pass
    finally:
        if session:
            await session.close()
            await unregister_session(user.id if user else "")
        try:
            await ws.close()
        except Exception:
            pass


@router.websocket("/composed-voice")
async def composed_realtime_voice(ws: WebSocket) -> None:
    user: User | None = None
    auth_payload: dict[str, object] | None = None

    try:
        user, auth_payload = await _authenticate_websocket(ws)
    except ApiError as exc:
        await ws.accept()
        await ws.send_json({"type": "error", "code": exc.code, "message": exc.message})
        await ws.close(code=4001 if exc.status_code == 401 else 4003, reason=exc.message)
        return

    await ws.accept()
    if not await _ensure_model_api_configured(ws):
        return

    session: ComposedRealtimeSession | None = None
    llm_capabilities: set[str] = set()
    receive_task: asyncio.Task | None = None
    turn_task: asyncio.Task[dict[str, str] | None] | None = None
    transcription_task: asyncio.Task[dict[str, str]] | None = None
    transcription_bridge: RealtimeTranscriptionBridge | None = None
    auto_start_task: asyncio.Task[None] | None = None
    transcript_final_timeout_task: asyncio.Task[None] | None = None
    idle_task: asyncio.Task[str | None] | None = None
    awaiting_transcript_final = False
    ignore_trailing_audio_until = 0.0
    realtime_asr_model_id = DEFAULT_PIPELINE_MODELS["realtime_asr"]

    def cancel_auto_start_task() -> None:
        nonlocal auto_start_task
        if auto_start_task is not None and not auto_start_task.done():
            auto_start_task.cancel()
        auto_start_task = None

    def cancel_transcript_final_timeout_task() -> None:
        nonlocal transcript_final_timeout_task
        if (
            transcript_final_timeout_task is not None
            and not transcript_final_timeout_task.done()
        ):
            transcript_final_timeout_task.cancel()
        transcript_final_timeout_task = None

    def arm_transcript_final_timeout_task() -> None:
        nonlocal transcript_final_timeout_task
        cancel_transcript_final_timeout_task()
        transcript_final_timeout_task = asyncio.create_task(
            asyncio.sleep(COMPOSED_TRANSCRIPT_FINAL_TIMEOUT_SECONDS)
        )

    async def close_transcription_bridge() -> None:
        nonlocal transcription_bridge, transcription_task
        cancel_transcript_final_timeout_task()
        if transcription_task is not None and not transcription_task.done():
            transcription_task.cancel()
            with suppress(asyncio.CancelledError):
                await transcription_task
        transcription_task = None
        if transcription_bridge is not None:
            await transcription_bridge.close()
            transcription_bridge = None

    async def start_turn_from_buffered_transcript(
        *,
        close_bridge_after_start: bool,
        trailing_audio_grace_seconds: float = 0.0,
    ) -> None:
        nonlocal turn_task, ignore_trailing_audio_until, awaiting_transcript_final
        maybe_task, consumed_media = await session.start_turn(ws)
        if consumed_media:
            await ws.send_json({"type": "media.cleared"})
        if maybe_task is not None:
            turn_task = maybe_task
            ignore_trailing_audio_until = (
                asyncio.get_running_loop().time() + trailing_audio_grace_seconds
                if trailing_audio_grace_seconds > 0
                else 0.0
            )
        else:
            ignore_trailing_audio_until = 0.0
        awaiting_transcript_final = False
        if close_bridge_after_start:
            await close_transcription_bridge()

    async def commit_transcription_turn() -> None:
        nonlocal awaiting_transcript_final
        if transcription_bridge is None or awaiting_transcript_final:
            return
        awaiting_transcript_final = True
        try:
            await transcription_bridge.commit()
        except UpstreamServiceError:
            logger.warning(
                "Composed realtime ASR commit failed",
                exc_info=True,
            )
            await ws.send_json({
                "type": "turn.error",
                "code": "upstream_unavailable",
                "message": "AI 暂时无响应，请重试",
            })
            awaiting_transcript_final = False
            session.clear_live_transcript()
            session.clear_buffered_audio()
            await close_transcription_bridge()
        else:
            arm_transcript_final_timeout_task()

    try:
        init_raw = await asyncio.wait_for(ws.receive_json(), timeout=10)
        if init_raw.get("type") != "session.start":
            await ws.send_json({"type": "error", "code": "bad_request", "message": "Expected session.start"})
            await ws.close()
            return

        conversation_id = init_raw.get("conversation_id")
        project_id = init_raw.get("project_id")
        if not conversation_id or not project_id:
            await ws.send_json({"type": "error", "code": "bad_request", "message": "Missing conversation_id or project_id"})
            await ws.close()
            return

        db: Session = SessionLocal()
        try:
            conversation, membership = _load_authorized_conversation(
                db,
                current_user_id=user.id,
                project_id=project_id,
                conversation_id=conversation_id,
            )
            llm_model_id, llm_capabilities = _load_llm_capabilities(db, conversation.project_id)
            realtime_asr_model_id = _resolve_realtime_asr_model_id(db, conversation.project_id)
            if "vision" not in llm_capabilities and "image" not in llm_capabilities:
                await _send_error_and_close(
                    ws,
                    code="unsupported_model",
                    message="Synthetic realtime requires a vision-capable chat model",
                )
                return

            session = ComposedRealtimeSession(
                workspace_id=conversation.workspace_id,
                project_id=conversation.project_id,
                conversation_id=conversation.id,
                user_id=user.id,
            )
            if not await register_session(user.id, session):  # type: ignore[arg-type]
                await ws.send_json({"type": "error", "code": "concurrent_limit", "message": "您已有一个进行中的对话"})
                await ws.close()
                return
            _ = membership
        except ApiError as exc:
            await ws.send_json({"type": "error", "code": exc.code, "message": exc.message})
            await ws.close(code=4003, reason=exc.message)
            return
        finally:
            db.close()

        await ws.send_json({"type": "session.ready"})

        idle_task = asyncio.create_task(_composed_idle_monitor(ws, session, auth_payload or {}))
        receive_task = asyncio.create_task(ws.receive())

        while True:
            wait_set: set[asyncio.Task] = {receive_task, idle_task}
            if turn_task is not None:
                wait_set.add(turn_task)
            if transcription_task is not None:
                wait_set.add(transcription_task)
            if auto_start_task is not None:
                wait_set.add(auto_start_task)
            if transcript_final_timeout_task is not None:
                wait_set.add(transcript_final_timeout_task)

            done, _pending = await asyncio.wait(wait_set, return_when=asyncio.FIRST_COMPLETED)

            if idle_task in done:
                end_reason = idle_task.result()
                if end_reason:
                    await _send_session_end(
                        ws,
                        reason=end_reason,
                        close_code=4001 if end_reason == "auth_revoked" else 1000,
                    )
                break

            if turn_task is not None and turn_task in done:
                try:
                    turn_result = turn_task.result()
                except asyncio.CancelledError:
                    turn_result = None
                except UpstreamServiceError:
                    logger.warning("Composed realtime turn failed due to upstream error", exc_info=True)
                    await ws.send_json({
                        "type": "turn.error",
                        "code": "upstream_unavailable",
                        "message": "AI 暂时无响应，请重试",
                    })
                    session.touch_activity()
                    turn_result = None
                except Exception:
                    logger.exception("Composed realtime turn failed")
                    await ws.send_json({
                        "type": "turn.error",
                        "code": "turn_failed",
                        "message": "本轮处理失败，请重试",
                    })
                    session.touch_activity()
                    turn_result = None

                if turn_result:
                    asyncio.create_task(
                        _persist_composed_turn(
                            ws,
                            session,
                            turn_result.get("user_text", "").strip(),
                            turn_result.get("assistant_text", "").strip(),
                            assistant_reasoning_content=turn_result.get("reasoning_content"),
                            assistant_metadata_json=turn_result.get("assistant_metadata_json"),
                        )
                    )
                turn_task = None

            if auto_start_task is not None and auto_start_task in done:
                try:
                    auto_start_task.result()
                except asyncio.CancelledError:
                    pass
                else:
                    if (
                        not awaiting_transcript_final
                        and session.has_buffered_audio
                        and not session.is_processing
                        and session.live_transcript.strip()
                    ):
                        await start_turn_from_buffered_transcript(
                            close_bridge_after_start=True,
                            trailing_audio_grace_seconds=COMPOSED_TRAILING_AUDIO_GRACE_SECONDS,
                        )
                finally:
                    auto_start_task = None

            if (
                transcript_final_timeout_task is not None
                and transcript_final_timeout_task in done
            ):
                try:
                    transcript_final_timeout_task.result()
                except asyncio.CancelledError:
                    pass
                else:
                    if awaiting_transcript_final and transcription_bridge is not None:
                        logger.warning(
                            "Composed realtime ASR finalization timed out; starting turn with current transcript"
                        )
                        await start_turn_from_buffered_transcript(
                            close_bridge_after_start=True,
                        )
                finally:
                    transcript_final_timeout_task = None

            if receive_task in done:
                try:
                    message = receive_task.result()
                except WebSocketDisconnect:
                    break

                if message["type"] == "websocket.disconnect":
                    break

                if "bytes" in message and message["bytes"]:
                    now = asyncio.get_running_loop().time()
                    if (
                        ignore_trailing_audio_until
                        and now < ignore_trailing_audio_until
                        and not session.is_processing
                    ):
                        session.touch_activity()
                        receive_task = asyncio.create_task(ws.receive())
                        continue
                    ignore_trailing_audio_until = 0.0
                    cancel_auto_start_task()
                    cancel_transcript_final_timeout_task()
                    is_new_utterance = not session.has_buffered_audio
                    audio_chunk_forwarded = False
                    if is_new_utterance and session.is_processing:
                        interrupted = await session.interrupt()
                        if interrupted:
                            await ws.send_json({"type": "interrupt.ack"})
                            turn_task = None
                    if is_new_utterance:
                        session.clear_live_transcript()
                        awaiting_transcript_final = False
                    if transcription_bridge is None:
                        transcription_bridge = RealtimeTranscriptionBridge(model=realtime_asr_model_id)
                        try:
                            await asyncio.wait_for(
                                transcription_bridge.connect(),
                                timeout=UPSTREAM_CONNECT_TIMEOUT_SECONDS,
                            )
                        except TimeoutError:
                            logger.warning("Composed realtime ASR setup timed out")
                            await ws.send_json({
                                "type": "turn.error",
                                "code": "upstream_timeout",
                                "message": "AI 暂时无响应，请重试",
                            })
                            awaiting_transcript_final = False
                            session.clear_live_transcript()
                            session.clear_buffered_audio()
                            await close_transcription_bridge()
                        except UpstreamServiceError:
                            logger.warning("Composed realtime ASR setup failed", exc_info=True)
                            await ws.send_json({
                                "type": "turn.error",
                                "code": "upstream_unavailable",
                                "message": "AI 暂时无响应，请重试",
                            })
                            awaiting_transcript_final = False
                            session.clear_live_transcript()
                            session.clear_buffered_audio()
                            await close_transcription_bridge()
                        else:
                            transcription_task = asyncio.create_task(transcription_bridge.next_event())
                    if transcription_bridge is not None:
                        await transcription_bridge.send_audio_chunk(message["bytes"])
                        audio_chunk_forwarded = True
                    if audio_chunk_forwarded:
                        session.append_audio_chunk(message["bytes"])

                elif "text" in message and message["text"]:
                    data = json.loads(message["text"])
                    msg_type = data.get("type")

                    if msg_type == "session.end":
                        cancel_auto_start_task()
                        cancel_transcript_final_timeout_task()
                        await ws.close(code=1000)
                        break
                    if msg_type == "input.interrupt":
                        cancel_auto_start_task()
                        cancel_transcript_final_timeout_task()
                        ignore_trailing_audio_until = 0.0
                        interrupted = await session.interrupt()
                        if interrupted:
                            await ws.send_json({"type": "interrupt.ack"})
                            turn_task = None
                    if msg_type == "audio.stop":
                        cancel_auto_start_task()
                        cancel_transcript_final_timeout_task()
                        ignore_trailing_audio_until = 0.0
                        if transcription_bridge is None:
                            if not session.has_buffered_audio:
                                session.touch_activity()
                                receive_task = asyncio.create_task(ws.receive())
                                continue
                            await start_turn_from_buffered_transcript(
                                close_bridge_after_start=False,
                            )
                        else:
                            await commit_transcription_turn()
                    elif msg_type == "media.set":
                        data_url = str(data.get("data_url") or "")
                        filename = str(data.get("filename") or "")
                        if not data_url:
                            await ws.send_json({"type": "error", "code": "bad_request", "message": "Missing media payload"})
                        else:
                            try:
                                pending_media = decode_pending_media(data_url=data_url, filename=filename)
                                if pending_media.kind == "video" and "video" not in llm_capabilities:
                                    await ws.send_json({
                                        "type": "error",
                                        "code": "unsupported_video",
                                        "message": "Current chat model does not support video input",
                                    })
                                else:
                                    await ws.send_json(session.replace_pending_media(pending_media))
                            except ApiError as exc:
                                await ws.send_json({"type": "error", "code": exc.code, "message": exc.message})
                            except ValueError as exc:
                                await ws.send_json({"type": "error", "code": "bad_media", "message": str(exc)})
                    elif msg_type == "media.frame.append":
                        data_url = str(data.get("data_url") or "")
                        if not data_url:
                            await ws.send_json({
                                "type": "error",
                                "code": "bad_request",
                                "message": "Missing media frame payload",
                            })
                        else:
                            try:
                                pending_frame = decode_pending_media(data_url=data_url, filename="frame.jpg")
                                if pending_frame.kind != "image":
                                    await ws.send_json({
                                        "type": "error",
                                        "code": "unsupported_media_type",
                                        "message": "Synthetic camera frames must be images",
                                    })
                                else:
                                    session.append_pending_video_frame(
                                        frame_data_url=data_url,
                                        frame_bytes=len(pending_frame.data or b""),
                                        fps=data.get("fps"),
                                    )
                            except ApiError as exc:
                                await ws.send_json({
                                    "type": "error",
                                    "code": exc.code,
                                    "message": exc.message,
                                })
                            except ValueError as exc:
                                await ws.send_json({
                                    "type": "error",
                                    "code": "bad_media",
                                    "message": str(exc),
                                })
                    elif msg_type == "media.clear":
                        await ws.send_json(session.clear_pending_media())

                receive_task = asyncio.create_task(ws.receive())

            if transcription_task is not None and transcription_task in done:
                event = transcription_task.result()
                event_type = event.get("type", "")

                if event_type == "transcript.partial":
                    cancel_auto_start_task()
                    if awaiting_transcript_final:
                        arm_transcript_final_timeout_task()
                    partial_text = event.get("text", "")
                    session.set_live_transcript(partial_text, final=False)
                    await ws.send_json({"type": "transcript.partial", "text": session.turn_input_text})
                elif event_type == "speech_stopped":
                    cancel_auto_start_task()
                    cancel_transcript_final_timeout_task()
                    if session.has_buffered_audio and not session.is_processing:
                        await commit_transcription_turn()
                elif event_type == "transcript.final":
                    cancel_transcript_final_timeout_task()
                    final_text = event.get("text", "")
                    session.set_live_transcript(final_text, final=True)
                    await ws.send_json({"type": "transcript.final", "text": session.turn_input_text})
                    if awaiting_transcript_final:
                        await start_turn_from_buffered_transcript(
                            close_bridge_after_start=True,
                        )
                    elif (
                        session.has_buffered_audio
                        and not session.is_processing
                        and session.turn_input_text.strip()
                    ):
                        cancel_auto_start_task()
                        auto_start_task = asyncio.create_task(
                            asyncio.sleep(COMPOSED_AUTO_START_DEBOUNCE_SECONDS)
                        )
                elif event_type == "transcript.empty":
                    cancel_auto_start_task()
                    cancel_transcript_final_timeout_task()
                    buffered_transcript = session.turn_input_text.strip()
                    if awaiting_transcript_final and buffered_transcript:
                        logger.warning(
                            "Composed realtime ASR returned empty finalization; falling back to buffered transcript"
                        )
                        await start_turn_from_buffered_transcript(
                            close_bridge_after_start=True,
                        )
                    else:
                        session.clear_live_transcript()
                    if awaiting_transcript_final and not buffered_transcript:
                        await start_turn_from_buffered_transcript(
                            close_bridge_after_start=True,
                        )
                elif event_type == "error":
                    logger.warning("Composed realtime transcription bridge failed: %s", event.get("message", ""))
                    await ws.send_json({
                        "type": "turn.error",
                        "code": "upstream_unavailable",
                        "message": "AI 暂时无响应，请重试",
                    })
                    cancel_auto_start_task()
                    awaiting_transcript_final = False
                    session.clear_live_transcript()
                    session.clear_buffered_audio()
                    await close_transcription_bridge()
                elif event_type == "session.closed":
                    cancel_auto_start_task()
                    cancel_transcript_final_timeout_task()
                    transcription_bridge = None

                transcription_task = (
                    asyncio.create_task(transcription_bridge.next_event())
                    if transcription_bridge is not None
                    else None
                )

    except Exception as exc:
        logger.exception("Composed realtime voice error: %s", exc)
        try:
            await ws.send_json({"type": "error", "code": "internal", "message": "Internal server error"})
        except Exception:
            pass
    finally:
        if receive_task is not None and not receive_task.done():
            receive_task.cancel()
        if transcription_task is not None and not transcription_task.done():
            transcription_task.cancel()
        if auto_start_task is not None and not auto_start_task.done():
            auto_start_task.cancel()
        if (
            transcript_final_timeout_task is not None
            and not transcript_final_timeout_task.done()
        ):
            transcript_final_timeout_task.cancel()
        if idle_task is not None:
            idle_task.cancel()
        if transcription_bridge is not None:
            await transcription_bridge.close()
        if session is not None:
            await session.close()
            await unregister_session(user.id if user else "")
        try:
            await ws.close()
        except Exception:
            pass
