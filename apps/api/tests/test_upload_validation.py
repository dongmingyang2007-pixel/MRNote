import asyncio

from app.services.upload_validation import (
    UPLOAD_SPOOL_MAX_MEMORY_BYTES,
    buffer_upload_body,
)


class DummyStreamingRequest:
    def __init__(self, payload: bytes) -> None:
        self.headers = {"content-length": str(len(payload))}
        self._payload = payload

    async def stream(self):
        midpoint = len(self._payload) // 2
        yield self._payload[:midpoint]
        yield self._payload[midpoint:]


def test_buffer_upload_body_spools_large_payloads_to_disk() -> None:
    payload = b"a" * (UPLOAD_SPOOL_MAX_MEMORY_BYTES + 1)

    buffered = asyncio.run(
        buffer_upload_body(
            DummyStreamingRequest(payload),
            expected_size=len(payload),
            max_bytes=len(payload) + 1024,
        )
    )
    try:
        assert getattr(buffered.file, "_rolled", False) is True
        assert buffered.peek_prefix(4) == b"aaaa"
    finally:
        buffered.close()
