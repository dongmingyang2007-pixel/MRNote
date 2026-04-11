from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from typing import Any

from redis import Redis
from redis.exceptions import RedisError

from app.core.config import settings


@dataclass
class _MemoryEntry:
    value: str
    expires_at: float | None


class _InMemoryBackend:
    def __init__(self) -> None:
        self._data: dict[str, _MemoryEntry] = {}
        self._lock = threading.Lock()

    def _purge_expired(self, key: str | None = None) -> None:
        now = time.time()
        if key is not None:
            entry = self._data.get(key)
            if entry and entry.expires_at is not None and entry.expires_at <= now:
                self._data.pop(key, None)
            return
        expired_keys = [
            item_key
            for item_key, entry in self._data.items()
            if entry.expires_at is not None and entry.expires_at <= now
        ]
        for item_key in expired_keys:
            self._data.pop(item_key, None)

    def get(self, key: str) -> str | None:
        with self._lock:
            self._purge_expired(key)
            entry = self._data.get(key)
            return entry.value if entry else None

    def setex(self, key: str, ttl_seconds: int, value: str) -> None:
        with self._lock:
            self._data[key] = _MemoryEntry(value=value, expires_at=time.time() + ttl_seconds)

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def incr(self, key: str, ttl_seconds: int) -> int:
        with self._lock:
            self._purge_expired(key)
            entry = self._data.get(key)
            current = int(entry.value) if entry else 0
            current += 1
            self._data[key] = _MemoryEntry(value=str(current), expires_at=time.time() + ttl_seconds)
            return current

    def pop(self, key: str) -> str | None:
        with self._lock:
            self._purge_expired(key)
            entry = self._data.pop(key, None)
            return entry.value if entry else None

    def decr(self, key: str) -> int:
        with self._lock:
            self._purge_expired(key)
            entry = self._data.get(key)
            if not entry:
                return 0
            current = int(entry.value) - 1
            if current <= 0:
                self._data.pop(key, None)
                return 0
            self._data[key] = _MemoryEntry(value=str(current), expires_at=entry.expires_at)
            return current


class RuntimeStateStore:
    def __init__(self) -> None:
        self._memory = _InMemoryBackend()
        self._redis: Redis | None = None

    def _namespaced(self, scope: str, key: str) -> str:
        return f"{settings.redis_namespace}:{scope}:{key}"

    def _get_redis_client(self) -> Redis | None:
        if settings.env == "test":
            return None
        if self._redis is None:
            self._redis = Redis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=settings.redis_connect_timeout_seconds,
                socket_timeout=settings.redis_connect_timeout_seconds,
            )
        return self._redis

    def _should_fallback_to_memory(self) -> bool:
        # Keep tests hermetic without requiring Redis, but never mask Redis
        # failures in local/prod-style environments.
        return settings.env == "test"

    def _run(self, redis_op, fallback_op):
        client = self._get_redis_client()
        if client is None:
            return fallback_op()
        try:
            return redis_op(client)
        except RedisError:
            if self._should_fallback_to_memory():
                return fallback_op()
            raise

    def ensure_available(self) -> None:
        client = self._get_redis_client()
        if client is None:
            return
        try:
            client.ping()
        except RedisError:
            if self._should_fallback_to_memory():
                return
            raise

    def set_json(self, scope: str, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        namespaced_key = self._namespaced(scope, key)
        payload = json.dumps(value, ensure_ascii=False)
        self._run(
            lambda client: client.setex(namespaced_key, ttl_seconds, payload),
            lambda: self._memory.setex(namespaced_key, ttl_seconds, payload),
        )

    def get_json(self, scope: str, key: str) -> dict[str, Any] | None:
        namespaced_key = self._namespaced(scope, key)
        payload = self._run(
            lambda client: client.get(namespaced_key),
            lambda: self._memory.get(namespaced_key),
        )
        if not payload:
            return None
        return json.loads(payload)

    def get_int(self, scope: str, key: str) -> int:
        namespaced_key = self._namespaced(scope, key)
        payload = self._run(
            lambda client: client.get(namespaced_key),
            lambda: self._memory.get(namespaced_key),
        )
        if payload is None:
            return 0
        try:
            return int(payload)
        except (TypeError, ValueError):
            return 0

    def pop_json(self, scope: str, key: str) -> dict[str, Any] | None:
        namespaced_key = self._namespaced(scope, key)

        def redis_op(client: Redis):
            with client.pipeline() as pipe:
                pipe.get(namespaced_key)
                pipe.delete(namespaced_key)
                payload, _ = pipe.execute()
            return payload

        payload = self._run(redis_op, lambda: self._memory.pop(namespaced_key))
        if not payload:
            return None
        return json.loads(payload)

    def delete(self, scope: str, key: str) -> None:
        namespaced_key = self._namespaced(scope, key)
        self._run(
            lambda client: client.delete(namespaced_key),
            lambda: self._memory.delete(namespaced_key),
        )

    def incr(self, scope: str, key: str, ttl_seconds: int) -> int:
        namespaced_key = self._namespaced(scope, key)

        def redis_op(client: Redis) -> int:
            current = client.incr(namespaced_key)
            if current == 1:
                client.expire(namespaced_key, ttl_seconds)
            return int(current)

        return int(
            self._run(
                redis_op,
                lambda: self._memory.incr(namespaced_key, ttl_seconds),
            )
        )

    def decr(self, scope: str, key: str) -> int:
        namespaced_key = self._namespaced(scope, key)

        def redis_op(client: Redis) -> int:
            current_value = client.get(namespaced_key)
            if current_value is None:
                return 0
            current = client.decr(namespaced_key)
            if current <= 0:
                client.delete(namespaced_key)
                return 0
            return int(current)

        return int(
            self._run(
                redis_op,
                lambda: self._memory.decr(namespaced_key),
            )
        )


runtime_state = RuntimeStateStore()
