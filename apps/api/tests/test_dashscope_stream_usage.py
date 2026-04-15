# ruff: noqa: E402
import asyncio
import json
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ["ENV"] = "test"

import pytest
from unittest.mock import patch

from app.services.dashscope_stream import StreamChunk, chat_completion_stream


class _FakeResponse:
    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    def raise_for_status(self) -> None:
        return None

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _FakeCtx:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    async def __aenter__(self) -> _FakeResponse:
        return self._response

    async def __aexit__(self, *a) -> None:
        return None


class _FakeClient:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    def stream(self, *a, **kw) -> _FakeCtx:
        return _FakeCtx(self._response)


def _drain(gen) -> list[StreamChunk]:
    async def go() -> list[StreamChunk]:
        return [chunk async for chunk in gen]
    return asyncio.run(go())


def test_final_chunk_carries_usage_and_model_id() -> None:
    lines = [
        "data: " + json.dumps({
            "model": "qwen-plus",
            "choices": [{"delta": {"content": "hello"}, "finish_reason": None}],
        }),
        "data: " + json.dumps({
            "model": "qwen-plus",
            "choices": [],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        }),
        "data: [DONE]",
    ]
    fake_client = _FakeClient(_FakeResponse(lines))
    with patch("app.services.dashscope_stream.get_client", return_value=fake_client):
        chunks = _drain(chat_completion_stream([{"role": "user", "content": "hi"}]))

    assert any(c.content == "hello" for c in chunks)
    final = chunks[-1]
    assert final.content == ""
    assert final.usage == {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}
    assert final.model_id == "qwen-plus"
    assert final.finish_reason == "stop"


def test_final_chunk_without_usage_still_yielded() -> None:
    lines = [
        "data: " + json.dumps({
            "model": "qwen-plus",
            "choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}],
        }),
        "data: [DONE]",
    ]
    fake_client = _FakeClient(_FakeResponse(lines))
    with patch("app.services.dashscope_stream.get_client", return_value=fake_client):
        chunks = _drain(chat_completion_stream([{"role": "user", "content": "hi"}]))

    final = chunks[-1]
    assert final.usage is None
    assert final.model_id == "qwen-plus"


def test_httpx_timeout_raises_inference_timeout() -> None:
    """Cover the httpx.TimeoutException → InferenceTimeoutError mapping."""
    import httpx
    from app.services.dashscope_client import InferenceTimeoutError

    class _ExplodingCtx:
        async def __aenter__(self):
            raise httpx.TimeoutException("upstream slow")

        async def __aexit__(self, *a):
            return None

    class _ExplodingClient:
        def stream(self, *a, **kw):
            return _ExplodingCtx()

    with patch(
        "app.services.dashscope_stream.get_client",
        return_value=_ExplodingClient(),
    ):
        with pytest.raises(InferenceTimeoutError):
            _drain(chat_completion_stream([{"role": "user", "content": "hi"}]))


def test_httpx_http_error_raises_upstream_service_error() -> None:
    """Cover the httpx.HTTPError → UpstreamServiceError mapping."""
    import httpx
    from app.services.dashscope_client import UpstreamServiceError

    class _ExplodingCtx:
        async def __aenter__(self):
            raise httpx.HTTPError("502")

        async def __aexit__(self, *a):
            return None

    class _ExplodingClient:
        def stream(self, *a, **kw):
            return _ExplodingCtx()

    with patch(
        "app.services.dashscope_stream.get_client",
        return_value=_ExplodingClient(),
    ):
        with pytest.raises(UpstreamServiceError):
            _drain(chat_completion_stream([{"role": "user", "content": "hi"}]))


def test_search_options_payload_path_does_not_break_stream() -> None:
    """Cover the enable_search / search_options payload branch."""
    lines = [
        "data: " + json.dumps({
            "model": "qwen-plus",
            "choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}],
        }),
        "data: [DONE]",
    ]
    fake_client = _FakeClient(_FakeResponse(lines))
    with patch("app.services.dashscope_stream.get_client", return_value=fake_client):
        chunks = _drain(chat_completion_stream(
            [{"role": "user", "content": "hi"}],
            enable_search=True,
            enable_thinking=True,
            search_options={"forced_search": True},
        ))

    assert chunks[-1].finish_reason == "stop"
