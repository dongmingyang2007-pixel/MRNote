"""Shared DashScope HTTP constants and client."""

import asyncio
import httpx

from app.core.config import settings

DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DASHSCOPE_RESPONSES_BASE_URL = "https://dashscope.aliyuncs.com/api/v2/apps/protocols/compatible-mode/v1"
DASHSCOPE_NATIVE_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
DASHSCOPE_RERANK_URL = "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"
DASHSCOPE_WS_URL = "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"

_clients: dict[int, httpx.AsyncClient] = {}


def get_client() -> httpx.AsyncClient:
    """Return a loop-local shared httpx.AsyncClient, creating it lazily."""
    loop = asyncio.get_running_loop()
    key = id(loop)
    client = _clients.get(key)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(90.0, connect=10.0),
        )
        _clients[key] = client
    return client


async def close_current_client() -> None:
    """Close the shared client bound to the current event loop."""
    loop = asyncio.get_running_loop()
    key = id(loop)
    client = _clients.pop(key, None)
    if client is not None and not client.is_closed:
        await client.aclose()


async def close_client() -> None:
    """Close all shared clients (call during app shutdown)."""
    clients = list(_clients.values())
    _clients.clear()
    for client in clients:
        if not client.is_closed:
            await client.aclose()


def dashscope_headers() -> dict[str, str]:
    """Standard DashScope auth headers."""
    return {
        "Authorization": f"Bearer {settings.dashscope_api_key}",
        "Content-Type": "application/json",
    }
