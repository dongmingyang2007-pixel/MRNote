"""Dual WebSocket bridge for real-time full-duplex voice.

Manages the lifecycle of a voice session:
  Browser/Earphone <-> FastAPI <-> DashScope Omni Realtime

Handles:
  - Upstream DashScope WebSocket connection
  - Audio relay in both directions
  - Smart interruption (VAD-based with duration threshold)
  - Context injection (personality, memories, RAG)
  - Session state machine
"""
from __future__ import annotations

import asyncio
import base64
import enum
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

import websockets

from app.core.config import settings
from app.services.dashscope_client import UpstreamServiceError
from app.services.voice_response_limits import (
    clamp_voice_response_text,
    normalize_voice_response_text,
)

logger = logging.getLogger(__name__)

DASHSCOPE_REALTIME_URL = "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"
OMNI_MODEL = "qwen3-omni-flash-realtime"
INPUT_AUDIO_TRANSCRIPTION_MODEL = "gummy-realtime-v1"
DEFAULT_REALTIME_VOICE = "Cherry"


class SessionState(enum.Enum):
    CONNECTING = "connecting"
    READY = "ready"
    LISTENING = "listening"
    AI_SPEAKING = "ai_speaking"
    CLOSING = "closing"
    CLOSED = "closed"


@dataclass
class RealtimeSession:
    """Tracks state for one real-time voice session."""

    workspace_id: str
    project_id: str
    conversation_id: str
    user_id: str
    upstream_model: str = OMNI_MODEL
    input_transcription_model: str = INPUT_AUDIO_TRANSCRIPTION_MODEL

    state: SessionState = SessionState.CONNECTING
    turn_count: int = 0
    _ai_speaking: bool = False
    _personality: str = ""
    _memory_texts: list[str] = field(default_factory=list)
    _knowledge_chunks: list[str] = field(default_factory=list)
    _speech_start_time: float | None = None
    _partial_transcript: str = ""
    _current_transcript: str = ""
    _current_response_text: str = ""
    _text_response_text: str = ""
    _audio_response_text: str = ""
    _response_text_channel: str | None = None
    _response_outputs_blocked: bool = False
    _swallow_next_response_done: bool = False
    _response_done_should_finalize_turn: bool = False
    _upstream_ws: websockets.ClientConnection | None = None
    _last_activity: float = field(default_factory=time.time)
    _session_update_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _pending_session_update: asyncio.Future[None] | None = None
    _active_turn_retrieval_trace: dict[str, Any] | None = None
    _response_in_flight: bool = False
    _awaiting_transcript_response: bool = False
    _response_request_started_for_current_input: bool = False
    _latest_transcript_completion: str = ""
    _pending_response_refresh_task: asyncio.Task[None] | None = None
    _has_sent_input_audio: bool = False
    _pending_image_b64: str | None = None

    @property
    def is_ai_speaking(self) -> bool:
        return self._ai_speaking

    def should_interrupt(self, speech_duration_ms: int) -> bool:
        """Decide whether user speech should interrupt AI output."""
        if not (self._ai_speaking or self._response_in_flight):
            return False
        return speech_duration_ms >= settings.realtime_interrupt_threshold_ms

    def touch(self) -> None:
        """Update last activity timestamp."""
        self._last_activity = time.time()

    def _reset_response_text_tracking(self) -> None:
        self._current_response_text = ""
        self._text_response_text = ""
        self._audio_response_text = ""
        self._response_text_channel = None

    def _reset_response_output_block(self) -> None:
        self._response_outputs_blocked = False

    def consume_response_done_finalization(self) -> bool:
        should_finalize = self._response_done_should_finalize_turn
        self._response_done_should_finalize_turn = False
        return should_finalize

    def _clear_swallowed_done_guard_on_new_output(self) -> None:
        if self._swallow_next_response_done and not self._response_outputs_blocked:
            self._swallow_next_response_done = False

    @staticmethod
    def _merge_transcript_text(existing: str, incoming: str) -> str:
        left = str(existing or "").strip()
        right = str(incoming or "").strip()
        if not left:
            return right
        if not right:
            return left
        if right.startswith(left) or left in right:
            return right
        if left.startswith(right) or right in left:
            return left
        needs_space = bool(re.search(r"[A-Za-z0-9]$", left) and re.match(r"[A-Za-z0-9]", right))
        return f"{left}{' ' if needs_space else ''}{right}"

    def _reconcile_response_text(self, *, channel: str, candidate: str) -> tuple[str, bool]:
        """Merge one response-text channel into the visible assistant transcript.

        DashScope omni may stream both ``response.text.delta`` and
        ``response.audio_transcript.*`` for the same turn. We keep separate
        channel buffers and only emit the minimal suffix needed to advance the
        visible transcript, so the UI does not render duplicated assistant text.
        """
        if not candidate:
            return "", False

        current = self._current_response_text
        if not current:
            self._response_text_channel = channel
            self._current_response_text = candidate
            return candidate, False

        if candidate == current or current.startswith(candidate):
            return "", False

        if candidate.startswith(current):
            self._response_text_channel = channel
            delta = candidate[len(current):]
            self._current_response_text = candidate
            return delta, False

        common_prefix_len = 0
        for left, right in zip(current, candidate, strict=False):
            if left != right:
                break
            common_prefix_len += 1

        self._response_text_channel = channel
        self._current_response_text = candidate
        if common_prefix_len == 0:
            return candidate, True
        return candidate, True

    async def _emit_response_text_candidate(self, *, channel: str, candidate: str) -> list[dict]:
        normalized_candidate = normalize_voice_response_text(candidate)
        if not normalized_candidate:
            return []

        clamped_candidate = clamp_voice_response_text(normalized_candidate)
        outgoing: list[dict] = []

        if (
            clamped_candidate != normalized_candidate
            and self._current_response_text
            and self._current_response_text != clamped_candidate
            and self._current_response_text.startswith(clamped_candidate)
        ):
            self._response_text_channel = channel
            self._current_response_text = clamped_candidate
            outgoing.append({"type": "response.text", "text": clamped_candidate, "replace": True})
        else:
            visible_delta, replace = self._reconcile_response_text(
                channel=channel,
                candidate=clamped_candidate,
            )
            if visible_delta:
                payload = {"type": "response.text", "text": visible_delta}
                if replace:
                    payload["replace"] = True
                outgoing.append(payload)

        if clamped_candidate != normalized_candidate:
            await self.cancel_response(
                preserve_turn=True,
                suppress_response_done=False,
            )
        return outgoing

    @property
    def idle_seconds(self) -> float:
        return time.time() - self._last_activity

    async def connect_upstream(self) -> None:
        """Establish WebSocket to DashScope Omni Realtime."""
        url = f"{DASHSCOPE_REALTIME_URL}?model={self.upstream_model or OMNI_MODEL}"
        headers = {
            "Authorization": f"Bearer {settings.dashscope_api_key}",
            "OpenAI-Beta": "realtime=v1",
        }
        self._upstream_ws = await websockets.connect(
            url,
            additional_headers=headers,
            max_size=16 * 1024 * 1024,
        )

    def _build_session_update_payload(self, system_prompt: str) -> dict:
        return {
            "type": "session.update",
            "session": {
                "modalities": ["audio", "text"],
                "instructions": system_prompt,
                "voice": DEFAULT_REALTIME_VOICE,
                "input_audio_format": "pcm",
                "input_audio_transcription": {
                    "model": self.input_transcription_model or INPUT_AUDIO_TRANSCRIPTION_MODEL,
                },
                "output_audio_format": "pcm",
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.0,
                    "silence_duration_ms": 400,
                    # We refresh layered context after ASR finalization and then
                    # explicitly trigger the next response, so upstream should
                    # not auto-start generation with stale instructions.
                    "create_response": False,
                    "interrupt_response": True,
                },
            },
        }

    async def _send_session_update_locked(
        self,
        system_prompt: str,
        *,
        wait_via_listener: bool,
    ) -> None:
        if not self._upstream_ws:
            raise UpstreamServiceError("Upstream not connected")

        loop = asyncio.get_running_loop()
        pending = loop.create_future()
        self._pending_session_update = pending

        await self._upstream_ws.send(json.dumps(self._build_session_update_payload(system_prompt)))
        try:
            if wait_via_listener:
                await pending
            else:
                while not pending.done():
                    raw_msg = await self._upstream_ws.recv()
                    if isinstance(raw_msg, bytes):
                        continue
                    event = json.loads(raw_msg)
                    await self.handle_upstream_event(event)
                await pending
        except websockets.ConnectionClosed as exc:
            if not pending.done():
                pending.set_exception(
                    UpstreamServiceError("Upstream connection closed during session setup")
                )
            raise UpstreamServiceError("Upstream connection closed during session setup") from exc
        finally:
            if self._pending_session_update is pending:
                self._pending_session_update = None

        self.state = SessionState.READY

    async def send_session_update(self, system_prompt: str) -> None:
        """Update the active session after the upstream listener is already running."""
        async with self._session_update_lock:
            await self._send_session_update_locked(
                system_prompt,
                wait_via_listener=True,
            )

    async def send_initial_session_update(self, system_prompt: str) -> None:
        """Configure the initial session before the upstream listener starts."""
        async with self._session_update_lock:
            await self._send_session_update_locked(
                system_prompt,
                wait_via_listener=False,
            )

    async def relay_audio_to_upstream(self, audio_bytes: bytes) -> None:
        """Forward PCM audio chunk from client to DashScope."""
        if not self._upstream_ws:
            return
        self.touch()
        audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
        await self._upstream_ws.send(json.dumps({
            "type": "input_audio_buffer.append",
            "audio": audio_b64,
        }))
        if not self._has_sent_input_audio:
            self._has_sent_input_audio = True
            if self._pending_image_b64:
                pending_image_b64 = self._pending_image_b64
                self._pending_image_b64 = None
                await self._upstream_ws.send(json.dumps({
                    "type": "input_image_buffer.append",
                    "image": pending_image_b64,
                }))

    async def relay_image_to_upstream(self, image_bytes: bytes) -> None:
        """Forward one JPEG frame from the browser camera to DashScope."""
        if not self._upstream_ws or not image_bytes:
            return
        self.touch()
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        if not self._has_sent_input_audio:
            self._pending_image_b64 = image_b64
            return
        await self._upstream_ws.send(json.dumps({
            "type": "input_image_buffer.append",
            "image": image_b64,
        }))

    async def request_response(self) -> None:
        """Explicitly ask the realtime model to answer the latest committed turn."""
        if not self._upstream_ws:
            raise UpstreamServiceError("Upstream not connected")
        if self._response_in_flight:
            return
        self.touch()
        self._speech_start_time = None
        self._response_done_should_finalize_turn = False
        self._reset_response_output_block()
        self._response_in_flight = True
        try:
            await self._upstream_ws.send(json.dumps({"type": "response.create"}))
        except Exception:
            self._response_in_flight = False
            raise

    async def handle_upstream_event(self, event: dict) -> list[dict | bytes]:
        """Process a DashScope event and return messages to send to client."""
        event_type = event.get("type", "")
        outgoing: list[dict | bytes] = []
        if event_type != "response.done":
            self._response_done_should_finalize_turn = False

        if event_type == "conversation.item.input_audio_transcription.text":
            confirmed = str(event.get("text", ""))
            speculative = str(event.get("stash", ""))
            preview = f"{confirmed}{speculative}"
            if preview:
                self._partial_transcript = self._merge_transcript_text(self._current_transcript, preview)
            outgoing.append({"type": "transcript.partial", "text": self._partial_transcript})
            self.touch()

        elif event_type == "conversation.item.input_audio_transcription.delta":
            partial = event.get("delta", "")
            if partial:
                self._partial_transcript = f"{self._partial_transcript or self._current_transcript}{partial}"
            outgoing.append({"type": "transcript.partial", "text": self._partial_transcript})
            self.touch()

        elif event_type == "conversation.item.input_audio_transcription.completed":
            transcript = event.get("transcript", "")
            self._partial_transcript = ""
            self._current_transcript = self._merge_transcript_text(self._current_transcript, str(transcript or ""))
            outgoing.append({"type": "transcript.final", "text": self._current_transcript})
            self.state = SessionState.LISTENING
            self.touch()

        elif event_type == "conversation.item.input_audio_transcription.failed":
            self._partial_transcript = ""
            self.touch()

        elif event_type == "response.audio.delta":
            if self._response_outputs_blocked:
                self.touch()
                return outgoing
            self._clear_swallowed_done_guard_on_new_output()
            self._ai_speaking = True
            self.state = SessionState.AI_SPEAKING
            audio_b64 = event.get("delta", "")
            if audio_b64:
                outgoing.append(base64.b64decode(audio_b64))
            self.touch()

        elif event_type == "response.text.delta":
            if self._response_outputs_blocked:
                self.touch()
                return outgoing
            self._clear_swallowed_done_guard_on_new_output()
            self._ai_speaking = True
            self.state = SessionState.AI_SPEAKING
            delta = event.get("delta", "")
            self._text_response_text += delta
            outgoing.extend(
                await self._emit_response_text_candidate(
                    channel="text",
                    candidate=self._text_response_text,
                )
            )
            self.touch()

        elif event_type == "response.audio_transcript.delta":
            if self._response_outputs_blocked:
                self.touch()
                return outgoing
            self._clear_swallowed_done_guard_on_new_output()
            self._ai_speaking = True
            self.state = SessionState.AI_SPEAKING
            delta = event.get("delta", "")
            self._audio_response_text += delta
            outgoing.extend(
                await self._emit_response_text_candidate(
                    channel="audio",
                    candidate=self._audio_response_text,
                )
            )
            self.touch()

        elif event_type == "response.audio_transcript.done":
            if self._response_outputs_blocked:
                self.touch()
                return outgoing
            self._clear_swallowed_done_guard_on_new_output()
            self._ai_speaking = True
            self.state = SessionState.AI_SPEAKING
            transcript = event.get("transcript", "")
            if transcript:
                self._audio_response_text = transcript
                outgoing.extend(
                    await self._emit_response_text_candidate(
                        channel="audio",
                        candidate=self._audio_response_text,
                    )
                )
            self.touch()

        elif event_type == "response.done":
            self._ai_speaking = False
            self._response_in_flight = False
            self._reset_response_output_block()
            self.state = SessionState.LISTENING
            self.touch()
            if self._swallow_next_response_done:
                self._swallow_next_response_done = False
                return outgoing
            self.turn_count += 1
            self._response_done_should_finalize_turn = True
            outgoing.append({"type": "response.done"})

        elif event_type == "session.updated":
            if self._pending_session_update and not self._pending_session_update.done():
                self._pending_session_update.set_result(None)
            self.state = SessionState.READY
            self.touch()

        elif event_type == "input_audio_buffer.speech_started":
            self._partial_transcript = ""
            self._speech_start_time = time.time()
            self._awaiting_transcript_response = False
            self._response_request_started_for_current_input = False
            self._latest_transcript_completion = ""
            if (
                self._pending_response_refresh_task is not None
                and not self._pending_response_refresh_task.done()
            ):
                self._pending_response_refresh_task.cancel()
                self._pending_response_refresh_task = None
            self.touch()

        elif event_type == "input_audio_buffer.speech_stopped":
            self._speech_start_time = None
            self._awaiting_transcript_response = True
            self._response_request_started_for_current_input = False
            self._latest_transcript_completion = ""
            if (
                self._pending_response_refresh_task is not None
                and not self._pending_response_refresh_task.done()
            ):
                self._pending_response_refresh_task.cancel()
                self._pending_response_refresh_task = None
            self.touch()

        elif event_type == "error":
            if self._pending_session_update and not self._pending_session_update.done():
                self._pending_session_update.set_exception(
                    UpstreamServiceError(f"DashScope session error: {event}")
                )
                self._pending_session_update = None
            outgoing.append({
                "type": "error",
                "code": "upstream_error",
                "message": str(event.get("error", {}).get("message", "Unknown error")),
            })

        # Check if ongoing speech should trigger interruption
        if self._speech_start_time and (self._ai_speaking or self._response_in_flight):
            elapsed_ms = (time.time() - self._speech_start_time) * 1000
            if self.should_interrupt(speech_duration_ms=int(elapsed_ms)):
                await self.cancel_response()
                self._speech_start_time = None
                outgoing.append({"type": "interrupt.ack"})

        return outgoing

    async def handle_client_message(self, msg_type: str, data: dict) -> list[dict]:
        """Process a control message sent from the client and return reply messages."""
        outgoing: list[dict] = []
        if msg_type == "input.interrupt":
            if self._ai_speaking or self._response_in_flight:
                await self.cancel_response()
                outgoing.append({"type": "interrupt.ack"})
        return outgoing

    async def cancel_response(
        self,
        *,
        preserve_turn: bool = False,
        suppress_response_done: bool | None = None,
    ) -> None:
        """Tell DashScope to stop current generation."""
        if not self._upstream_ws:
            return
        if suppress_response_done is None:
            suppress_response_done = not preserve_turn
        if self._response_outputs_blocked:
            if suppress_response_done:
                self._swallow_next_response_done = True
            return
        self._response_outputs_blocked = True
        self._response_in_flight = False
        if suppress_response_done:
            self._swallow_next_response_done = True
        self._ai_speaking = False
        self._partial_transcript = ""
        if not preserve_turn:
            self._current_transcript = ""
            self._active_turn_retrieval_trace = None
            self._reset_response_text_tracking()
        await self._upstream_ws.send(json.dumps({"type": "response.cancel"}))

    async def close(self) -> None:
        """Gracefully close upstream connection."""
        self.state = SessionState.CLOSING
        if self._pending_response_refresh_task and not self._pending_response_refresh_task.done():
            self._pending_response_refresh_task.cancel()
            self._pending_response_refresh_task = None
        if self._pending_session_update and not self._pending_session_update.done():
            self._pending_session_update.set_exception(
                UpstreamServiceError("Upstream connection closed")
            )
            self._pending_session_update = None
        if self._upstream_ws:
            try:
                await self._upstream_ws.close()
            except Exception:
                pass
        self.state = SessionState.CLOSED

    def get_turn_texts(self) -> tuple[str, str]:
        """Return (user_text, ai_text) for the current turn and reset."""
        user = self._current_transcript
        ai = self._current_response_text
        self._current_transcript = ""
        self._reset_response_text_tracking()
        return user, ai


# -- Global session registry --

_active_sessions: dict[str, RealtimeSession] = {}
_sessions_lock = asyncio.Lock()


async def register_session(user_id: str, session: RealtimeSession) -> bool:
    """Register a session. Returns False if user already has an active session
    or global limit reached."""
    async with _sessions_lock:
        if user_id in _active_sessions:
            return False
        if len(_active_sessions) >= settings.realtime_max_concurrent_sessions:
            return False
        _active_sessions[user_id] = session
        return True


async def unregister_session(user_id: str) -> None:
    """Remove a session from the registry."""
    async with _sessions_lock:
        _active_sessions.pop(user_id, None)
