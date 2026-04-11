import base64
from dataclasses import asdict, dataclass, field
import re
from typing import Any, NoReturn
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.services.dashscope_http import DASHSCOPE_BASE_URL, dashscope_headers, get_client


class UpstreamServiceError(Exception):
    """Third-party model provider failed or returned an invalid response."""


class InferenceTimeoutError(UpstreamServiceError):
    """Third-party model provider timed out."""


@dataclass(slots=True)
class ChatCompletionResult:
    content: str
    reasoning_content: str | None = None
    tool_calls: list["ToolCall"] = field(default_factory=list)
    finish_reason: str | None = None
    search_sources: list["SearchSource"] = field(default_factory=list)


@dataclass(slots=True)
class ToolCall:
    id: str
    name: str
    arguments: str
    type: str = "function"


@dataclass(slots=True)
class SearchSource:
    index: int
    title: str
    url: str
    domain: str
    site_name: str | None = None
    summary: str | None = None
    icon: str | None = None
    tool_type: str | None = None
    image_url: str | None = None
    thumbnail_url: str | None = None


def raise_upstream_error(exc: Exception) -> NoReturn:
    if isinstance(exc, InferenceTimeoutError | UpstreamServiceError):
        raise exc
    if isinstance(exc, httpx.TimeoutException):
        raise InferenceTimeoutError("Inference timeout") from exc
    if isinstance(exc, httpx.HTTPError):
        raise UpstreamServiceError("Model API unavailable") from exc
    raise UpstreamServiceError(f"Unexpected model API error: {exc}") from exc


def _build_multimodal_messages(
    messages: list[dict],
    *,
    audio_bytes: bytes | None = None,
    audio_mime_type: str = "audio/wav",
    image_bytes: bytes | None = None,
    image_mime_type: str = "image/jpeg",
    video_bytes: bytes | None = None,
    video_mime_type: str = "video/mp4",
    video_frame_data_urls: list[str] | None = None,
    video_fps: float = 1.0,
) -> list[dict]:
    formatted_messages: list[dict] = []
    for msg in messages:
        if msg["role"] == "user" and msg is messages[-1]:
            content_parts: list[dict] = []

            if audio_bytes:
                audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
                content_parts.append({
                    "type": "input_audio",
                    "input_audio": {
                        "data": f"data:{audio_mime_type};base64,{audio_b64}",
                    },
                })

            if image_bytes:
                image_b64 = base64.b64encode(image_bytes).decode("utf-8")
                content_parts.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{image_mime_type};base64,{image_b64}",
                    },
                })

            if video_frame_data_urls:
                content_parts.append({
                    "type": "video",
                    "video": list(video_frame_data_urls),
                    "fps": video_fps,
                })
            elif video_bytes:
                video_b64 = base64.b64encode(video_bytes).decode("utf-8")
                content_parts.append({
                    "type": "video_url",
                    "video_url": {
                        "url": f"data:{video_mime_type};base64,{video_b64}",
                    },
                })

            text_content = msg.get("content", "")
            if text_content:
                content_parts.append({"type": "text", "text": text_content})

            formatted_messages.append({"role": "user", "content": content_parts})
        else:
            formatted_messages.append(msg)
    return formatted_messages


def _flatten_message_field(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict):
                if isinstance(item.get("text"), str):
                    parts.append(item["text"])
                    continue
                if item.get("type") == "text" and isinstance(item.get("content"), str):
                    parts.append(item["content"])
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(part.strip() for part in parts if part and part.strip())
    return ""


def _parse_tool_calls(value: Any) -> list[ToolCall]:
    if not isinstance(value, list):
        return []

    tool_calls: list[ToolCall] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        function_payload = item.get("function")
        if not isinstance(function_payload, dict):
            continue
        name = function_payload.get("name")
        arguments = function_payload.get("arguments")
        if not isinstance(name, str):
            continue
        tool_calls.append(
            ToolCall(
                id=str(item.get("id") or ""),
                name=name,
                arguments=arguments if isinstance(arguments, str) else "",
                type=str(item.get("type") or "function"),
            )
        )
    return tool_calls


def _coerce_nonempty_text(value: Any) -> str | None:
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    flattened = _flatten_message_field(value).strip()
    return flattened or None


def _normalize_source_index(value: Any, fallback: int) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        match = re.search(r"(\d+)", value)
        if match:
            return int(match.group(1))
    return fallback


def _coerce_url_field(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("url", "href", "link"):
            normalized = _coerce_nonempty_text(value.get(key))
            if normalized:
                return normalized
        return None
    return _coerce_nonempty_text(value)


def _normalize_search_source(item: dict[str, Any], fallback_index: int) -> SearchSource | None:
    url = (
        _coerce_url_field(item.get("url"))
        or _coerce_url_field(item.get("source_url"))
        or _coerce_url_field(item.get("page_url"))
        or _coerce_url_field(item.get("link"))
    )
    image_url = (
        _coerce_url_field(item.get("image_url"))
        or _coerce_url_field(item.get("image"))
    )
    thumbnail_url = (
        _coerce_url_field(item.get("thumbnail_url"))
        or _coerce_url_field(item.get("thumbnail"))
    )
    effective_url = url or image_url or thumbnail_url
    if not effective_url:
        return None
    title = (
        _coerce_nonempty_text(item.get("title"))
        or _coerce_nonempty_text(item.get("name"))
        or _coerce_nonempty_text(item.get("label"))
    )

    hostname = urlparse(effective_url).hostname or ""
    domain = hostname.lower()
    summary = (
        _coerce_nonempty_text(item.get("summary"))
        or _coerce_nonempty_text(item.get("snippet"))
        or _coerce_nonempty_text(item.get("excerpt"))
        or _coerce_nonempty_text(item.get("description"))
        or _coerce_nonempty_text(item.get("text"))
        or _coerce_nonempty_text(item.get("content"))
    )
    if not title:
        title = domain or effective_url
    return SearchSource(
        index=_normalize_source_index(item.get("index"), fallback_index),
        title=title,
        url=effective_url,
        domain=domain,
        site_name=_coerce_nonempty_text(item.get("site_name")) or domain or None,
        summary=summary,
        icon=_coerce_nonempty_text(item.get("icon")),
        tool_type=_coerce_nonempty_text(item.get("tool_type")),
        image_url=image_url,
        thumbnail_url=thumbnail_url,
    )


def extract_search_sources(*payloads: Any) -> list[SearchSource]:
    parsed_sources: list[SearchSource] = []
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        search_info = payload.get("search_info")
        if isinstance(search_info, dict):
            search_results = search_info.get("search_results")
            if isinstance(search_results, list):
                for index, item in enumerate(search_results, start=1):
                    if isinstance(item, dict):
                        normalized = _normalize_search_source(item, index)
                        if normalized:
                            parsed_sources.append(normalized)
        direct_results = payload.get("search_results")
        if isinstance(direct_results, list):
            for index, item in enumerate(direct_results, start=1):
                if isinstance(item, dict):
                    normalized = _normalize_search_source(item, index)
                    if normalized:
                        parsed_sources.append(normalized)
    return merge_search_sources(parsed_sources)


def merge_search_sources(*groups: list[SearchSource]) -> list[SearchSource]:
    merged: dict[str, SearchSource] = {}
    for group in groups:
        for source in group:
            key = source.image_url or source.url or f"ref:{source.index}"
            current = merged.get(key)
            if current is None:
                merged[key] = SearchSource(**asdict(source))
                continue
            if source.index > 0 and (current.index <= 0 or source.index < current.index):
                current.index = source.index
            if not current.title and source.title:
                current.title = source.title
            if not current.domain and source.domain:
                current.domain = source.domain
            if not current.site_name and source.site_name:
                current.site_name = source.site_name
            if not current.summary and source.summary:
                current.summary = source.summary
            if not current.icon and source.icon:
                current.icon = source.icon
            if not current.tool_type and source.tool_type:
                current.tool_type = source.tool_type
            if not current.image_url and source.image_url:
                current.image_url = source.image_url
            if not current.thumbnail_url and source.thumbnail_url:
                current.thumbnail_url = source.thumbnail_url
    return sorted(
        merged.values(),
        key=lambda source: (
            source.index if source.index > 0 else 10_000,
            source.domain,
            source.url,
        ),
    )


def serialize_search_sources(sources: list[SearchSource]) -> list[dict[str, Any]]:
    return [asdict(source) for source in merge_search_sources(sources)]


def _build_effective_search_options(
    *,
    enable_search: bool | None,
    search_options: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if enable_search is not True:
        return search_options
    merged = {
        "enable_source": True,
        "enable_citation": True,
        "citation_format": "[ref_<number>]",
    }
    if search_options:
        merged.update(search_options)
    return merged


def _parse_chat_completion_result(data: dict[str, Any]) -> ChatCompletionResult:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise UpstreamServiceError("Model API returned no choices")

    choice = choices[0]
    message = choice.get("message")
    if not isinstance(message, dict):
        raise UpstreamServiceError("Model API returned an invalid message payload")

    content = _flatten_message_field(message.get("content"))
    reasoning_content = _flatten_message_field(message.get("reasoning_content")) or None
    tool_calls = _parse_tool_calls(message.get("tool_calls"))
    search_sources = extract_search_sources(data, choice, message)
    finish_reason = choice.get("finish_reason")
    return ChatCompletionResult(
        content=content,
        reasoning_content=reasoning_content,
        tool_calls=tool_calls,
        finish_reason=finish_reason if isinstance(finish_reason, str) else None,
        search_sources=search_sources,
    )


async def chat_completion_detailed(
    messages: list[dict[str, Any]],
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 2048,
    enable_thinking: bool | None = None,
    enable_search: bool | None = None,
    search_options: dict[str, Any] | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = None,
    parallel_tool_calls: bool | None = None,
) -> ChatCompletionResult:
    """Call DashScope chat completion API and return answer + reasoning."""
    model = model or settings.dashscope_model

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
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
    if tools:
        payload["tools"] = tools
    if tool_choice is not None:
        payload["tool_choice"] = tool_choice
    if parallel_tool_calls is not None:
        payload["parallel_tool_calls"] = parallel_tool_calls

    try:
        client = get_client()
        response = await client.post(
            f"{DASHSCOPE_BASE_URL}/chat/completions",
            headers=dashscope_headers(),
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
        return _parse_chat_completion_result(data)
    except Exception as exc:  # noqa: BLE001
        raise_upstream_error(exc)


async def chat_completion(
    messages: list[dict[str, Any]],
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 2048,
    enable_thinking: bool | None = None,
    enable_search: bool | None = None,
    search_options: dict[str, Any] | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = None,
    parallel_tool_calls: bool | None = None,
) -> str:
    """Call DashScope chat completion API (OpenAI-compatible).
    Returns the assistant's response text."""
    result = await chat_completion_detailed(
        messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        enable_thinking=enable_thinking,
        enable_search=enable_search,
        search_options=search_options,
        tools=tools,
        tool_choice=tool_choice,
        parallel_tool_calls=parallel_tool_calls,
    )
    return result.content


async def chat_completion_multimodal_detailed(
    messages: list[dict[str, Any]],
    *,
    model: str | None = None,
    audio_bytes: bytes | None = None,
    audio_mime_type: str = "audio/wav",
    image_bytes: bytes | None = None,
    image_mime_type: str = "image/jpeg",
    video_bytes: bytes | None = None,
    video_mime_type: str = "video/mp4",
    video_frame_data_urls: list[str] | None = None,
    video_fps: float = 1.0,
    temperature: float = 0.7,
    max_tokens: int = 2048,
    enable_thinking: bool | None = None,
    enable_search: bool | None = None,
    search_options: dict[str, Any] | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = None,
    parallel_tool_calls: bool | None = None,
) -> ChatCompletionResult:
    model = model or settings.dashscope_model
    formatted_messages = _build_multimodal_messages(
        messages,
        audio_bytes=audio_bytes,
        audio_mime_type=audio_mime_type,
        image_bytes=image_bytes,
        image_mime_type=image_mime_type,
        video_bytes=video_bytes,
        video_mime_type=video_mime_type,
        video_frame_data_urls=video_frame_data_urls,
        video_fps=video_fps,
    )

    payload: dict[str, Any] = {
        "model": model,
        "messages": formatted_messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
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
    if tools:
        payload["tools"] = tools
    if tool_choice is not None:
        payload["tool_choice"] = tool_choice
    if parallel_tool_calls is not None:
        payload["parallel_tool_calls"] = parallel_tool_calls

    try:
        client = get_client()
        response = await client.post(
            f"{DASHSCOPE_BASE_URL}/chat/completions",
            headers=dashscope_headers(),
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
        return _parse_chat_completion_result(data)
    except Exception as exc:  # noqa: BLE001
        raise_upstream_error(exc)


async def chat_completion_multimodal(
    messages: list[dict[str, Any]],
    *,
    model: str | None = None,
    audio_bytes: bytes | None = None,
    audio_mime_type: str = "audio/wav",
    image_bytes: bytes | None = None,
    image_mime_type: str = "image/jpeg",
    video_bytes: bytes | None = None,
    video_mime_type: str = "video/mp4",
    video_frame_data_urls: list[str] | None = None,
    video_fps: float = 1.0,
    temperature: float = 0.7,
    max_tokens: int = 2048,
    enable_thinking: bool | None = None,
    enable_search: bool | None = None,
    search_options: dict[str, Any] | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = None,
    parallel_tool_calls: bool | None = None,
) -> str:
    result = await chat_completion_multimodal_detailed(
        messages,
        model=model,
        audio_bytes=audio_bytes,
        audio_mime_type=audio_mime_type,
        image_bytes=image_bytes,
        image_mime_type=image_mime_type,
        video_bytes=video_bytes,
        video_mime_type=video_mime_type,
        video_frame_data_urls=video_frame_data_urls,
        video_fps=video_fps,
        temperature=temperature,
        max_tokens=max_tokens,
        enable_thinking=enable_thinking,
        enable_search=enable_search,
        search_options=search_options,
        tools=tools,
        tool_choice=tool_choice,
        parallel_tool_calls=parallel_tool_calls,
    )
    return result.content


async def create_embedding(
    text: str,
    model: str | None = None,
) -> list[float]:
    """Create a text embedding vector using DashScope embedding API.
    Returns a list of floats (1024 dimensions for text-embedding-v3)."""
    model = model or settings.dashscope_embedding_model

    try:
        client = get_client()
        response = await client.post(
            f"{DASHSCOPE_BASE_URL}/embeddings",
            headers=dashscope_headers(),
            json={
                "model": model,
                "input": text,
            },
        )
        response.raise_for_status()
        data = response.json()
        return data["data"][0]["embedding"]
    except Exception as exc:  # noqa: BLE001
        raise_upstream_error(exc)


async def create_embeddings_batch(
    texts: list[str],
    model: str | None = None,
) -> list[list[float]]:
    """Batch embed multiple texts. Returns list of vectors."""
    model = model or settings.dashscope_embedding_model

    try:
        client = get_client()
        response = await client.post(
            f"{DASHSCOPE_BASE_URL}/embeddings",
            headers=dashscope_headers(),
            json={
                "model": model,
                "input": texts,
            },
        )
        response.raise_for_status()
        data = response.json()
        return [item["embedding"] for item in data["data"]]
    except Exception as exc:  # noqa: BLE001
        raise_upstream_error(exc)


async def omni_completion(
    messages: list[dict[str, Any]],
    audio_bytes: bytes | None = None,
    image_bytes: bytes | None = None,
    image_mime_type: str = "image/jpeg",
    model: str = "qwen3-omni-flash-realtime",
    temperature: float = 0.7,
    max_tokens: int = 2048,
    enable_thinking: bool | None = None,
    enable_search: bool | None = None,
    search_options: dict[str, Any] | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = None,
    parallel_tool_calls: bool | None = None,
) -> dict:
    """Call an omni model with multimodal input (audio and/or image).

    The omni model understands audio and images directly via the same
    chat/completions endpoint, using multimodal content blocks.

    Returns ``{"text": "...", "audio": None}`` -- audio output requires
    WebSocket streaming which will be added in a future phase.
    """
    result = await chat_completion_multimodal_detailed(
        messages,
        model=model,
        audio_bytes=audio_bytes,
        image_bytes=image_bytes,
        image_mime_type=image_mime_type,
        temperature=temperature,
        max_tokens=max_tokens,
        enable_thinking=enable_thinking,
        enable_search=enable_search,
        search_options=search_options,
        tools=tools,
        tool_choice=tool_choice,
        parallel_tool_calls=parallel_tool_calls,
    )

    return {
        "text": result.content,
        "audio": None,
        "reasoning_content": result.reasoning_content,
        "sources": serialize_search_sources(result.search_sources),
    }
