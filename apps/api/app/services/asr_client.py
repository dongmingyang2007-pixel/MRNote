import asyncio
import base64
import json
from collections.abc import Iterator
from contextlib import suppress

import websockets
from app.core.config import settings
from app.services.dashscope_client import UpstreamServiceError, raise_upstream_error
from app.services.dashscope_http import DASHSCOPE_BASE_URL, DASHSCOPE_WS_URL, dashscope_headers, get_client


def _iter_encoded_audio_chunks(audio_bytes: bytes, *, raw_chunk_size: int = 8192) -> Iterator[str]:
    """Yield base64-encoded audio chunks without splitting inside base64 groups."""
    for i in range(0, len(audio_bytes), raw_chunk_size):
        raw_chunk = audio_bytes[i : i + raw_chunk_size]
        if raw_chunk:
            yield base64.b64encode(raw_chunk).decode("utf-8")


def _is_empty_audio_stream_error(event: dict[str, object]) -> bool:
    """Treat empty/invalid committed audio buffers as no-speech instead of provider outage."""
    error = event.get("error")
    if not isinstance(error, dict):
        return False
    message = str(error.get("message", "")).lower()
    return (
        "error committing input audio buffer" in message
        or "invalid audio stream" in message
        or "no audio stream" in message
    )


def _build_realtime_asr_session_update_payload(sample_rate: int) -> dict[str, object]:
    return {
        "type": "session.update",
        "session": {
            "modalities": ["text"],
            "input_audio_format": "pcm",
            "sample_rate": sample_rate,
            "input_audio_transcription": {"language": "zh"},
            "turn_detection": {
                "type": "server_vad",
                "threshold": 0.0,
                "silence_duration_ms": 400,
            },
        },
    }


class RealtimeTranscriptionBridge:
    """Reusable realtime ASR bridge that emits normalized partial/final events."""

    def __init__(
        self,
        *,
        model: str | None = None,
        sample_rate: int = 16000,
    ) -> None:
        self.model = model or "qwen3-asr-flash-realtime"
        self.sample_rate = sample_rate
        self._ws: websockets.ClientConnection | None = None
        self._listener_task: asyncio.Task[None] | None = None
        self._events: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        self._partial_transcript = ""

    async def connect(self) -> None:
        ws_url = f"{DASHSCOPE_WS_URL}?model={self.model}"
        headers = {
            "Authorization": f"Bearer {settings.dashscope_api_key}",
            "OpenAI-Beta": "realtime=v1",
        }
        self._ws = await websockets.connect(
            ws_url,
            additional_headers=headers,
            max_size=16 * 1024 * 1024,
        )
        await self._ws.send(json.dumps(_build_realtime_asr_session_update_payload(self.sample_rate)))

        while True:
            raw_event = await self._ws.recv()
            if isinstance(raw_event, bytes):
                continue
            event = json.loads(raw_event)
            event_type = event.get("type", "")
            if event_type == "session.updated":
                break
            if event_type == "error":
                if _is_empty_audio_stream_error(event):
                    break
                raise UpstreamServiceError(f"ASR WebSocket error: {event}")

        self._listener_task = asyncio.create_task(self._listen())

    async def send_audio_chunk(self, audio_bytes: bytes) -> None:
        if not self._ws:
            raise UpstreamServiceError("ASR upstream not connected")
        for chunk in _iter_encoded_audio_chunks(audio_bytes):
            await self._ws.send(json.dumps({
                "type": "input_audio_buffer.append",
                "audio": chunk,
            }))

    async def commit(self) -> None:
        if not self._ws:
            raise UpstreamServiceError("ASR upstream not connected")
        await self._ws.send(json.dumps({"type": "input_audio_buffer.commit"}))

    async def next_event(self) -> dict[str, str]:
        return await self._events.get()

    async def close(self) -> None:
        listener = self._listener_task
        self._listener_task = None
        ws = self._ws
        self._ws = None

        if listener is not None:
            listener.cancel()
            with suppress(asyncio.CancelledError):
                await listener

        if ws is not None:
            with suppress(Exception):
                await ws.send(json.dumps({"type": "session.finish"}))
            with suppress(Exception):
                await ws.close()

    async def _listen(self) -> None:
        try:
            assert self._ws is not None
            async for message in self._ws:
                if isinstance(message, bytes):
                    continue
                event = json.loads(message)
                event_type = event.get("type", "")

                if event_type == "input_audio_buffer.speech_started":
                    self._partial_transcript = ""
                elif event_type == "input_audio_buffer.speech_stopped":
                    await self._events.put({"type": "speech_stopped", "text": ""})
                elif event_type == "conversation.item.input_audio_transcription.text":
                    confirmed = str(event.get("text", ""))
                    speculative = str(event.get("stash", ""))
                    preview = f"{confirmed}{speculative}"
                    if preview:
                        self._partial_transcript = preview
                        await self._events.put({"type": "transcript.partial", "text": preview})
                elif event_type == "conversation.item.input_audio_transcription.delta":
                    delta = str(event.get("delta", ""))
                    if delta:
                        self._partial_transcript += delta
                        await self._events.put({"type": "transcript.partial", "text": self._partial_transcript})
                elif event_type == "conversation.item.input_audio_transcription.completed":
                    transcript = str(event.get("transcript", "")).strip()
                    self._partial_transcript = ""
                    await self._events.put({"type": "transcript.final", "text": transcript})
                elif event_type == "conversation.item.input_audio_transcription.failed":
                    self._partial_transcript = ""
                    await self._events.put({"type": "transcript.empty", "text": ""})
                elif event_type == "error":
                    self._partial_transcript = ""
                    if _is_empty_audio_stream_error(event):
                        await self._events.put({"type": "transcript.empty", "text": ""})
                    else:
                        await self._events.put({"type": "error", "message": f"ASR WebSocket error: {event}"})
                elif event_type == "session.finished":
                    await self._events.put({"type": "session.closed", "text": ""})
                    break
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            await self._events.put({"type": "error", "message": str(exc)})


def _detect_audio_mime(content_type: str | None, filename: str) -> str:
    """Detect audio MIME type, prioritizing content_type over filename extension."""
    if content_type and content_type.startswith("audio/"):
        return content_type
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "wav"
    return {"wav": "audio/wav", "mp3": "audio/mpeg", "webm": "audio/webm", "m4a": "audio/mp4", "ogg": "audio/ogg", "mp4": "audio/mp4"}.get(ext, "audio/wav")


async def transcribe_audio(
    audio_bytes: bytes,
    filename: str = "audio.wav",
    model: str | None = None,
    content_type: str | None = None,
) -> str:
    """Transcribe audio to text using Qwen3-ASR-Flash (OpenAI-compatible).

    Uses the chat/completions endpoint with input_audio content type.
    Supports Base64-encoded audio data for direct upload.

    Args:
        audio_bytes: Raw audio data (WAV, MP3, WebM, etc.)
        filename: Filename (used for MIME detection fallback)
        model: ASR model ID (default: qwen3-asr-flash)
        content_type: HTTP Content-Type from the upload (preferred over filename extension)

    Returns:
        Transcribed text string
    """
    model = model or "qwen3-asr-flash"

    # Encode audio as base64 data URL
    audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
    # Detect MIME type: prefer content_type, fall back to filename extension
    mime = _detect_audio_mime(content_type, filename)
    data_url = f"data:{mime};base64,{audio_b64}"

    try:
        client = get_client()
        response = await client.post(
            f"{DASHSCOPE_BASE_URL}/chat/completions",
            headers=dashscope_headers(),
            json={
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_audio",
                                "input_audio": {"data": data_url},
                            }
                        ],
                    }
                ],
            },
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]
    except Exception as exc:  # noqa: BLE001
        raise_upstream_error(exc)


async def transcribe_audio_realtime(
    audio_bytes: bytes,
    model: str | None = None,
    sample_rate: int = 16000,
) -> str:
    """Realtime: WebSocket, streams audio chunks, returns accumulated text.

    Despite being "realtime", we send the complete audio in chunks
    since we record first then send. Each chunk must be base64-encoded
    independently; slicing an already-encoded string corrupts the stream.
    """
    model = model or "qwen3-asr-flash-realtime"
    ws_url = f"{DASHSCOPE_WS_URL}?model={model}"

    headers = {
        "Authorization": f"Bearer {settings.dashscope_api_key}",
        "OpenAI-Beta": "realtime=v1",
    }

    transcript_parts: list[str] = []

    try:
        async with websockets.connect(
            ws_url,
            additional_headers=headers,
            max_size=16 * 1024 * 1024,
        ) as ws:
            # 1. Configure session
            await ws.send(json.dumps(_build_realtime_asr_session_update_payload(sample_rate)))

            # Wait for session.updated confirmation.
            while True:
                raw_event = await ws.recv()
                if isinstance(raw_event, bytes):
                    continue
                event = json.loads(raw_event)
                event_type = event.get("type", "")
                if event_type == "session.updated":
                    break
                if event_type == "error":
                    if _is_empty_audio_stream_error(event):
                        return ""
                    raise RuntimeError(f"ASR WebSocket error: {event}")

            # 2. Send audio in chunks. Encode each raw PCM chunk independently
            # so the provider receives valid base64 payloads for every append.
            for chunk in _iter_encoded_audio_chunks(audio_bytes):
                await ws.send(json.dumps({
                    "type": "input_audio_buffer.append",
                    "audio": chunk,
                }))

            # 3. Signal end
            await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
            await ws.send(json.dumps({"type": "session.finish"}))

            # 4. Collect transcription results
            async for message in ws:
                event = json.loads(message)
                event_type = event.get("type", "")

                if event_type == "conversation.item.input_audio_transcription.completed":
                    transcript_parts.append(event.get("transcript", ""))
                elif event_type == "session.finished":
                    break
                elif event_type == "error":
                    if _is_empty_audio_stream_error(event):
                        return ""
                    raise RuntimeError(f"ASR WebSocket error: {event}")
    except Exception as exc:  # noqa: BLE001
        raise_upstream_error(exc)

    return "".join(transcript_parts)
