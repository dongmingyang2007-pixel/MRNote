import base64
import json

import websockets
from app.core.config import settings
from app.services.dashscope_client import raise_upstream_error
from app.services.dashscope_http import DASHSCOPE_NATIVE_URL, DASHSCOPE_WS_URL, dashscope_headers, get_client


async def synthesize_speech(
    text: str,
    model: str | None = None,
    voice: str = "Cherry",
) -> bytes:
    """Synthesize speech from text using Qwen3-TTS-Flash (DashScope native API).

    Uses the non-streaming multimodal generation endpoint.

    Args:
        text: Text to convert to speech (max ~2000 chars recommended)
        model: TTS model ID (default: qwen3-tts-flash)
        voice: Voice name (Cherry, Serena, Ethan, Chelsie, etc.)

    Returns:
        Audio bytes
    """
    model = model or "qwen3-tts-flash"

    try:
        client = get_client()
        response = await client.post(
            DASHSCOPE_NATIVE_URL,
            headers=dashscope_headers(),
            json={
                "model": model,
                "input": {
                    "text": text,
                    "voice": voice,
                },
            },
        )
        response.raise_for_status()
        data = response.json()

        # Response contains audio URL or base64 data
        output = data.get("output", {})
        audio_info = output.get("audio", {})

        # If URL is returned, download the audio
        audio_url = audio_info.get("url")
        if audio_url:
            audio_resp = await client.get(audio_url)
            audio_resp.raise_for_status()
            return audio_resp.content

        # If base64 data is returned directly
        audio_data = audio_info.get("data")
        if audio_data:
            return base64.b64decode(audio_data)

        raise ValueError("No audio data in TTS response")
    except Exception as exc:  # noqa: BLE001
        raise_upstream_error(exc)


async def synthesize_speech_realtime(
    text: str,
    model: str | None = None,
    voice: str = "Cherry",
    sample_rate: int = 24000,
) -> bytes:
    """Realtime: WebSocket, streams text in, collects audio chunks.

    Returns complete audio bytes (PCM format).
    Even though this is "realtime", we collect all audio before returning
    since our HTTP API needs to send a complete response.
    The benefit is faster processing due to streaming pipeline.
    """
    model = model or "qwen3-tts-flash-realtime"
    ws_url = f"{DASHSCOPE_WS_URL}?model={model}"

    headers = {
        "Authorization": f"Bearer {settings.dashscope_api_key}",
    }

    audio_chunks: list[bytes] = []

    try:
        async with websockets.connect(ws_url, additional_headers=headers) as ws:
            # 1. Configure session
            await ws.send(json.dumps({
                "type": "session.update",
                "session": {
                    "voice": voice,
                    "response_format": "mp3",
                    "sample_rate": sample_rate,
                    "mode": "server_commit",
                },
            }))

            # Wait for session.updated
            await ws.recv()

            # 2. Send text (can send in chunks for long text)
            chunk_size = 500
            for i in range(0, len(text), chunk_size):
                chunk = text[i : i + chunk_size]
                await ws.send(json.dumps({
                    "type": "input_text_buffer.append",
                    "text": chunk,
                }))

            # 3. Signal finish
            await ws.send(json.dumps({"type": "session.finish"}))

            # 4. Collect audio
            async for message in ws:
                event = json.loads(message)
                event_type = event.get("type", "")

                if event_type == "response.audio.delta":
                    audio_data = base64.b64decode(event.get("delta", ""))
                    audio_chunks.append(audio_data)
                elif event_type == "session.finished":
                    break
                elif event_type == "error":
                    raise RuntimeError(f"TTS WebSocket error: {event}")
    except Exception as exc:  # noqa: BLE001
        raise_upstream_error(exc)

    return b"".join(audio_chunks)
