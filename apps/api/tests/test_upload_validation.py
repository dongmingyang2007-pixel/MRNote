import asyncio

from app.core.errors import ApiError
from app.services.upload_validation import (
    UPLOAD_SPOOL_MAX_MEMORY_BYTES,
    buffer_upload_body,
    validate_workspace_upload_declaration,
    validate_workspace_upload_signature,
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


def test_validate_workspace_upload_declaration_accepts_pptx_octet_stream() -> None:
    media_type = validate_workspace_upload_declaration(
        "deck.pptx",
        "application/octet-stream",
    )
    assert media_type == "application/vnd.openxmlformats-officedocument.presentationml.presentation"


def test_validate_workspace_upload_signature_accepts_pptx_zip_prefix() -> None:
    validate_workspace_upload_signature(
        prefix=b"PK\x03\x04pptx",
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )


def test_validate_workspace_upload_declaration_accepts_python_source_octet_stream() -> None:
    media_type = validate_workspace_upload_declaration(
        "agent.py",
        "application/octet-stream",
    )
    assert media_type == "text/plain"


def test_validate_workspace_upload_declaration_accepts_unknown_binary_file() -> None:
    media_type = validate_workspace_upload_declaration(
        "weights.gguf",
        "application/octet-stream",
    )
    assert media_type == "application/octet-stream"


def test_validate_workspace_upload_declaration_rejects_svg_even_when_declared_octet_stream() -> None:
    try:
        validate_workspace_upload_declaration(
            "payload.svg",
            "application/octet-stream",
        )
    except ApiError as exc:
        assert exc.code == "unsupported_media_type"
    else:
        raise AssertionError("expected unsupported_media_type")


def test_validate_workspace_upload_signature_rejects_binary_payload_for_text_media_type() -> None:
    try:
        validate_workspace_upload_signature(
            prefix=b"\x00\x01\x02binary",
            media_type="text/plain",
        )
    except ApiError as exc:
        assert exc.code == "upload_mismatch"
    else:
        raise AssertionError("expected upload mismatch")
