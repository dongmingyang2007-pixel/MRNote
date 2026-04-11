from __future__ import annotations

import base64
from dataclasses import dataclass, field
import json
from typing import Any, AsyncIterator
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.services.dashscope_client import (
    ChatCompletionResult,
    InferenceTimeoutError,
    SearchSource,
    ToolCall,
    UpstreamServiceError,
    _coerce_nonempty_text,
    merge_search_sources,
    raise_upstream_error,
)
from app.services.dashscope_http import DASHSCOPE_RESPONSES_BASE_URL, dashscope_headers, get_client


_RESPONSES_SOURCE_TOOL_TYPES = {
    "web_search_call": "web_search",
    "web_search_image_call": "web_search_image",
    "image_search_call": "image_search",
    "web_extractor_call": "web_extractor",
    "file_search_call": "file_search",
    "file_search_results": "file_search",
    "code_interpreter_call": "code_interpreter",
    "code_interpreter_output": "code_interpreter",
    "mcp_call": "mcp",
}


@dataclass(slots=True)
class ResponsesStreamChunk:
    content: str = ""
    reasoning_content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    search_sources: list[SearchSource] = field(default_factory=list)
    finish_reason: str | None = None


def _build_responses_payload(
    *,
    input_items: list[dict[str, Any]],
    model: str | None,
    enable_thinking: bool | None,
    tools: list[dict[str, Any]] | None,
    tool_choice: str | dict[str, Any] | None,
    stream: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model or settings.dashscope_model,
        "input": input_items,
    }
    if enable_thinking is not None:
        payload["enable_thinking"] = enable_thinking
    if tools:
        payload["tools"] = tools
    if tools and tool_choice is not None:
        payload["tool_choice"] = tool_choice
    if stream:
        payload["stream"] = True
    return payload


def _normalize_response_message_content(content: Any) -> Any:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return content

    normalized_parts: list[dict[str, Any]] = []
    for item in content:
        if isinstance(item, str):
            text_value = item.strip()
            if text_value:
                normalized_parts.append({"type": "text", "text": text_value})
            continue
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "").lower()
        if item_type == "text":
            text_value = (
                _coerce_nonempty_text(item.get("text"))
                or _coerce_nonempty_text(item.get("content"))
                or _coerce_nonempty_text(item.get("value"))
            )
            if text_value:
                normalized_parts.append({"type": "text", "text": text_value})
            continue
        if item_type == "image_url":
            image_value = item.get("image_url")
            if isinstance(image_value, dict):
                image_value = image_value.get("url")
            image_url = _coerce_nonempty_text(image_value)
            if image_url:
                normalized_parts.append({"type": "image_url", "image_url": image_url})
    return normalized_parts or content


def build_responses_input_items(
    messages: list[dict[str, Any]],
    *,
    image_bytes: bytes | None = None,
    image_mime_type: str = "image/jpeg",
) -> list[dict[str, Any]]:
    input_items: list[dict[str, Any]] = []
    image_url: str | None = None
    if image_bytes:
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        image_url = f"data:{image_mime_type};base64,{image_b64}"

    last_user_index = -1
    if image_url:
        for index, message in enumerate(messages):
            if str(message.get("role") or "").lower() == "user":
                last_user_index = index

    for index, message in enumerate(messages):
        normalized = dict(message)
        if "role" in normalized:
            content = normalized.get("content")
            if image_url and index == last_user_index:
                parts: list[dict[str, Any]] = []
                text_value = _extract_message_text(content)
                if text_value:
                    parts.append({"type": "text", "text": text_value})
                parts.append({"type": "image_url", "image_url": image_url})
                normalized["content"] = parts
            else:
                normalized["content"] = _normalize_response_message_content(content)
        input_items.append(normalized)
    return input_items


def _extract_message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            normalized = item.strip()
            if normalized:
                parts.append(normalized)
            continue
        if not isinstance(item, dict):
            continue
        text_value = (
            _coerce_nonempty_text(item.get("text"))
            or _coerce_nonempty_text(item.get("content"))
            or _coerce_nonempty_text(item.get("value"))
        )
        if text_value:
            parts.append(text_value)
    return "\n".join(parts)


def _extract_reasoning_text(item: dict[str, Any]) -> str:
    summary = item.get("summary")
    if isinstance(summary, list):
        parts: list[str] = []
        for entry in summary:
            if not isinstance(entry, dict):
                continue
            text_value = (
                _coerce_nonempty_text(entry.get("text"))
                or _coerce_nonempty_text(entry.get("summary_text"))
                or _coerce_nonempty_text(entry.get("content"))
            )
            if text_value:
                parts.append(text_value)
        if parts:
            return "\n".join(parts)
    return (
        _coerce_nonempty_text(item.get("summary_text"))
        or _coerce_nonempty_text(item.get("text"))
        or _extract_message_text(item.get("content"))
        or ""
    )


def _normalize_response_source(item: Any, fallback_index: int) -> SearchSource | None:
    if not isinstance(item, dict):
        return None
    image_value = item.get("image_url")
    if isinstance(image_value, dict):
        image_value = image_value.get("url")
    thumbnail_value = item.get("thumbnail_url")
    if isinstance(thumbnail_value, dict):
        thumbnail_value = thumbnail_value.get("url")
    image_url = _coerce_nonempty_text(image_value)
    thumbnail_url = _coerce_nonempty_text(thumbnail_value)
    url = (
        _coerce_nonempty_text(item.get("url"))
        or _coerce_nonempty_text(item.get("source_url"))
        or _coerce_nonempty_text(item.get("page_url"))
        or _coerce_nonempty_text(item.get("link"))
        or image_url
        or thumbnail_url
    )
    if not url:
        return None
    hostname = urlparse(url).hostname or ""
    domain = hostname.lower()
    title = (
        _coerce_nonempty_text(item.get("title"))
        or _coerce_nonempty_text(item.get("name"))
        or _coerce_nonempty_text(item.get("label"))
        or domain
        or url
    )
    return SearchSource(
        index=fallback_index,
        title=title,
        url=url,
        domain=domain,
        site_name=_coerce_nonempty_text(item.get("site_name")) or domain or None,
        summary=(
            _coerce_nonempty_text(item.get("summary"))
            or _coerce_nonempty_text(item.get("snippet"))
            or _coerce_nonempty_text(item.get("description"))
            or _coerce_nonempty_text(item.get("caption"))
            or _coerce_nonempty_text(item.get("text"))
        ),
        icon=_coerce_nonempty_text(item.get("icon")),
        tool_type=_coerce_nonempty_text(item.get("tool_type")),
        image_url=image_url,
        thumbnail_url=thumbnail_url,
    )


def _extract_response_search_sources(item: dict[str, Any]) -> list[SearchSource]:
    sources: list[SearchSource] = []
    item_type = str(item.get("type") or "").lower()
    tool_type = _RESPONSES_SOURCE_TOOL_TYPES.get(item_type)
    candidate_groups: list[list[Any]] = []

    def _append_candidates(value: Any) -> None:
        if isinstance(value, list):
            candidate_groups.append(value)
        elif isinstance(value, dict):
            candidate_groups.append([value])

    for key in ("sources", "results", "search_results"):
        _append_candidates(item.get(key))
    action = item.get("action")
    if isinstance(action, dict):
        for key in ("sources", "results", "search_results"):
            _append_candidates(action.get(key))
        if tool_type == "web_extractor":
            _append_candidates(action)
    if tool_type and not candidate_groups:
        _append_candidates(item)
    for candidates in candidate_groups:
        for index, source in enumerate(candidates, start=1):
            if isinstance(source, dict) and tool_type and "tool_type" not in source:
                source = {
                    **source,
                    "tool_type": tool_type,
                }
            normalized = _normalize_response_source(source, index)
            if normalized:
                sources.append(normalized)
    return merge_search_sources(sources)


def _parse_response_tool_call(item: dict[str, Any]) -> ToolCall | None:
    name = _coerce_nonempty_text(item.get("name"))
    if not name:
        return None
    arguments = item.get("arguments")
    if isinstance(arguments, (dict, list)):
        arguments_text = json.dumps(arguments, ensure_ascii=False)
    elif isinstance(arguments, str):
        arguments_text = arguments
    else:
        arguments_text = ""
    call_id = (
        _coerce_nonempty_text(item.get("call_id"))
        or _coerce_nonempty_text(item.get("id"))
        or name
    )
    return ToolCall(
        id=call_id,
        name=name,
        arguments=arguments_text,
    )


def _extract_responses_error_message(data: dict[str, Any]) -> str | None:
    error = data.get("error")
    if isinstance(error, dict):
        code = _coerce_nonempty_text(error.get("code"))
        message = _coerce_nonempty_text(error.get("message"))
        if code and message:
            return f"{code}: {message}"
        if message:
            return message
        if code:
            return code
    status = _coerce_nonempty_text(data.get("status"))
    if status == "failed":
        return "Responses API request failed"
    return None


def _parse_responses_result(data: dict[str, Any]) -> ChatCompletionResult:
    error_message = _extract_responses_error_message(data)
    if error_message:
        raise UpstreamServiceError(error_message)

    output_items = data.get("output")
    if not isinstance(output_items, list):
        output_items = []

    content = _coerce_nonempty_text(data.get("output_text")) or ""
    reasoning_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    search_sources: list[SearchSource] = []

    for item in output_items:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "").lower()
        if item_type == "message":
            if not content:
                content = _extract_message_text(item.get("content"))
            continue
        if item_type == "reasoning":
            reasoning = _extract_reasoning_text(item)
            if reasoning:
                reasoning_parts.append(reasoning)
            continue
        if item_type == "function_call":
            tool_call = _parse_response_tool_call(item)
            if tool_call:
                tool_calls.append(tool_call)
            continue
        if item_type in _RESPONSES_SOURCE_TOOL_TYPES:
            search_sources = merge_search_sources(search_sources, _extract_response_search_sources(item))
            continue

    finish_reason = _coerce_nonempty_text(data.get("status"))
    return ChatCompletionResult(
        content=content,
        reasoning_content="\n".join(part for part in reasoning_parts if part).strip() or None,
        tool_calls=tool_calls,
        finish_reason=finish_reason,
        search_sources=merge_search_sources(search_sources),
    )


async def responses_completion_detailed(
    input_items: list[dict[str, Any]],
    *,
    model: str | None = None,
    enable_thinking: bool | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = "auto",
    image_bytes: bytes | None = None,
    image_mime_type: str = "image/jpeg",
) -> ChatCompletionResult:
    payload = _build_responses_payload(
        input_items=build_responses_input_items(
            input_items,
            image_bytes=image_bytes,
            image_mime_type=image_mime_type,
        ),
        model=model,
        enable_thinking=enable_thinking,
        tools=tools,
        tool_choice=tool_choice,
        stream=False,
    )
    try:
        client = get_client()
        response = await client.post(
            f"{DASHSCOPE_RESPONSES_BASE_URL}/responses",
            headers=dashscope_headers(),
            json=payload,
        )
        response.raise_for_status()
        return _parse_responses_result(response.json())
    except Exception as exc:  # noqa: BLE001
        raise_upstream_error(exc)


def _parse_sse_event(raw_event: str | None, raw_data_lines: list[str]) -> tuple[str | None, dict[str, Any] | None]:
    if not raw_data_lines:
        return None, None
    raw_data = "\n".join(raw_data_lines).strip()
    if not raw_data or raw_data == "[DONE]":
        return raw_event, None
    try:
        payload = json.loads(raw_data)
    except json.JSONDecodeError:
        return raw_event, None
    event_type = raw_event or _coerce_nonempty_text(payload.get("type"))
    return event_type, payload


async def responses_completion_stream(
    input_items: list[dict[str, Any]],
    *,
    model: str | None = None,
    enable_thinking: bool | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = "auto",
    timeout: float = 120.0,
    image_bytes: bytes | None = None,
    image_mime_type: str = "image/jpeg",
) -> AsyncIterator[ResponsesStreamChunk]:
    payload = _build_responses_payload(
        input_items=build_responses_input_items(
            input_items,
            image_bytes=image_bytes,
            image_mime_type=image_mime_type,
        ),
        model=model,
        enable_thinking=enable_thinking,
        tools=tools,
        tool_choice=tool_choice,
        stream=True,
    )
    try:
        client = get_client()
        async with client.stream(
            "POST",
            f"{DASHSCOPE_RESPONSES_BASE_URL}/responses",
            headers=dashscope_headers(),
            json=payload,
            timeout=timeout,
        ) as response:
            response.raise_for_status()

            event_name: str | None = None
            data_lines: list[str] = []
            emitted_content = ""
            emitted_reasoning = ""
            seen_tool_call_ids: set[str] = set()

            def _emit_missing_text(
                *,
                current: str,
                candidate: str,
            ) -> str:
                if not candidate:
                    return ""
                if not current:
                    return candidate
                if candidate.startswith(current):
                    return candidate[len(current):]
                return ""

            async for line in response.aiter_lines():
                if line == "":
                    parsed_event, payload_data = _parse_sse_event(event_name, data_lines)
                    event_name = None
                    data_lines = []
                    if not payload_data:
                        continue

                    if parsed_event == "response.output_text.delta":
                        delta = _coerce_nonempty_text(payload_data.get("delta")) or ""
                        if delta:
                            emitted_content += delta
                            yield ResponsesStreamChunk(content=delta)
                        continue
                    if parsed_event == "response.reasoning_summary_text.delta":
                        delta = _coerce_nonempty_text(payload_data.get("delta")) or ""
                        if delta:
                            emitted_reasoning += delta
                            yield ResponsesStreamChunk(reasoning_content=delta)
                        continue
                    if parsed_event == "response.output_item.done":
                        item = payload_data.get("item")
                        if not isinstance(item, dict):
                            continue
                        item_type = str(item.get("type") or "").lower()
                        if item_type == "function_call":
                            tool_call = _parse_response_tool_call(item)
                            if tool_call and tool_call.id not in seen_tool_call_ids:
                                seen_tool_call_ids.add(tool_call.id)
                                yield ResponsesStreamChunk(tool_calls=[tool_call])
                        elif item_type in _RESPONSES_SOURCE_TOOL_TYPES:
                            sources = _extract_response_search_sources(item)
                            if sources:
                                yield ResponsesStreamChunk(search_sources=sources)
                        elif item_type == "message":
                            delta = _emit_missing_text(
                                current=emitted_content,
                                candidate=_extract_message_text(item.get("content")),
                            )
                            if delta:
                                emitted_content += delta
                                yield ResponsesStreamChunk(content=delta)
                        elif item_type == "reasoning":
                            delta = _emit_missing_text(
                                current=emitted_reasoning,
                                candidate=_extract_reasoning_text(item),
                            )
                            if delta:
                                emitted_reasoning += delta
                                yield ResponsesStreamChunk(reasoning_content=delta)
                        continue
                    if parsed_event == "response.completed":
                        result = _parse_responses_result(payload_data)
                        content_delta = _emit_missing_text(
                            current=emitted_content,
                            candidate=result.content,
                        )
                        if content_delta:
                            emitted_content += content_delta
                            yield ResponsesStreamChunk(content=content_delta)
                        reasoning_delta = _emit_missing_text(
                            current=emitted_reasoning,
                            candidate=result.reasoning_content or "",
                        )
                        if reasoning_delta:
                            emitted_reasoning += reasoning_delta
                            yield ResponsesStreamChunk(reasoning_content=reasoning_delta)
                        unseen_tool_calls = [
                            tool_call
                            for tool_call in result.tool_calls
                            if tool_call.id not in seen_tool_call_ids
                        ]
                        if unseen_tool_calls:
                            seen_tool_call_ids.update(tool_call.id for tool_call in unseen_tool_calls)
                            yield ResponsesStreamChunk(tool_calls=unseen_tool_calls)
                        if result.search_sources:
                            yield ResponsesStreamChunk(search_sources=result.search_sources)
                        yield ResponsesStreamChunk(finish_reason="completed")
                        continue
                    if parsed_event == "response.failed":
                        raise UpstreamServiceError(
                            _extract_responses_error_message(payload_data) or "Responses API stream failed",
                        )
                    continue

                if line.startswith("event:"):
                    event_name = line[len("event:"):].strip()
                    continue
                if line.startswith("data:"):
                    data_lines.append(line[len("data:"):].strip())

            parsed_event, payload_data = _parse_sse_event(event_name, data_lines)
            if parsed_event == "response.completed" and payload_data is not None:
                result = _parse_responses_result(payload_data)
                content_delta = _emit_missing_text(
                    current=emitted_content,
                    candidate=result.content,
                )
                if content_delta:
                    emitted_content += content_delta
                    yield ResponsesStreamChunk(content=content_delta)
                reasoning_delta = _emit_missing_text(
                    current=emitted_reasoning,
                    candidate=result.reasoning_content or "",
                )
                if reasoning_delta:
                    emitted_reasoning += reasoning_delta
                    yield ResponsesStreamChunk(reasoning_content=reasoning_delta)
                unseen_tool_calls = [
                    tool_call
                    for tool_call in result.tool_calls
                    if tool_call.id not in seen_tool_call_ids
                ]
                if unseen_tool_calls:
                    seen_tool_call_ids.update(tool_call.id for tool_call in unseen_tool_calls)
                    yield ResponsesStreamChunk(tool_calls=unseen_tool_calls)
                if result.search_sources:
                    yield ResponsesStreamChunk(search_sources=result.search_sources)
                yield ResponsesStreamChunk(finish_reason="completed")
    except (InferenceTimeoutError, UpstreamServiceError):
        raise
    except httpx.TimeoutException as exc:
        raise InferenceTimeoutError("Inference timeout") from exc
    except httpx.HTTPError as exc:
        raise UpstreamServiceError("Model API unavailable") from exc
    except Exception as exc:  # noqa: BLE001
        raise UpstreamServiceError(f"Unexpected model API error: {exc}") from exc
