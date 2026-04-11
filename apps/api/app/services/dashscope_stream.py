"""Streaming variant of DashScope chat completion API."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import httpx

from app.core.config import settings
from app.services.dashscope_client import (
    InferenceTimeoutError,
    SearchSource,
    UpstreamServiceError,
    _build_effective_search_options,
    extract_search_sources,
)
from app.services.dashscope_http import DASHSCOPE_BASE_URL, dashscope_headers, get_client

logger = logging.getLogger(__name__)


@dataclass
class StreamChunk:
    content: str = ""
    reasoning_content: str = ""
    finish_reason: str | None = None
    search_sources: list[SearchSource] = field(default_factory=list)


async def chat_completion_stream(
    messages: list[dict],
    model: str | None = None,
    *,
    temperature: float = 0.7,
    max_tokens: int = 2048,
    enable_thinking: bool | None = None,
    enable_search: bool | None = None,
    search_options: dict[str, Any] | None = None,
    timeout: float = 120.0,
) -> AsyncIterator[StreamChunk]:
    """Stream chat completion tokens from DashScope OpenAI-compatible API.

    Yields StreamChunk objects as they arrive from the API.
    The caller is responsible for accumulating content.
    """
    model = model or settings.dashscope_model

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    effective_search_options = _build_effective_search_options(
        enable_search=enable_search,
        search_options=search_options,
    )
    if enable_thinking is not None:
        payload["enable_thinking"] = enable_thinking
    if enable_search is not None:
        payload["enable_search"] = enable_search
    if effective_search_options:
        payload["search_options"] = effective_search_options

    try:
        client = get_client()
        async with client.stream(
            "POST",
            f"{DASHSCOPE_BASE_URL}/chat/completions",
            headers=dashscope_headers(),
            json=payload,
            timeout=timeout,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                raw = line[len("data:"):].strip()
                if raw == "[DONE]":
                    break
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning("dashscope_stream: failed to parse SSE line: %r", raw)
                    continue

                choices = data.get("choices")
                if not choices:
                    # Could be a usage-only chunk; skip silently
                    continue

                delta = choices[0].get("delta", {})
                finish_reason = choices[0].get("finish_reason")

                content = delta.get("content") or ""
                reasoning_content = delta.get("reasoning_content") or ""
                search_sources = extract_search_sources(data, choices[0], delta)

                if content or reasoning_content or finish_reason or search_sources:
                    yield StreamChunk(
                        content=content,
                        reasoning_content=reasoning_content,
                        finish_reason=finish_reason,
                        search_sources=search_sources,
                    )
    except (InferenceTimeoutError, UpstreamServiceError):
        raise
    except httpx.TimeoutException as exc:
        raise InferenceTimeoutError("Inference timeout") from exc
    except httpx.HTTPError as exc:
        raise UpstreamServiceError("Model API unavailable") from exc
    except Exception as exc:  # noqa: BLE001
        raise UpstreamServiceError(f"Unexpected model API error: {exc}") from exc
