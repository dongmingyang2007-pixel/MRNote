from __future__ import annotations

from dataclasses import dataclass
from io import BufferedIOBase
from tempfile import SpooledTemporaryFile

from fastapi import Request

from app.core.errors import ApiError
from app.services.storage import (
    delete_object,
    get_object_metadata,
    normalize_media_type,
    read_object_prefix,
    uploaded_object_matches,
)


UPLOAD_SIGNATURE_READ_BYTES = 8192
UPLOAD_SPOOL_MAX_MEMORY_BYTES = 1024 * 1024
_DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_TEXTUAL_MEDIA_TYPES = {"text/plain", "text/markdown"}
_PREVIEWABLE_IMAGE_MEDIA_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
    "image/bmp",
    "image/tiff",
}
_WORKSPACE_UPLOAD_MEDIA_TYPES_BY_EXTENSION: dict[str, set[str]] = {
    ".jpg": {"image/jpeg", "application/octet-stream"},
    ".jpeg": {"image/jpeg", "application/octet-stream"},
    ".png": {"image/png", "application/octet-stream"},
    ".webp": {"image/webp", "application/octet-stream"},
    ".gif": {"image/gif", "application/octet-stream"},
    ".bmp": {"image/bmp", "application/octet-stream"},
    ".tif": {"image/tiff", "application/octet-stream"},
    ".tiff": {"image/tiff", "application/octet-stream"},
    ".pdf": {"application/pdf", "application/octet-stream"},
    ".txt": {"text/plain", "application/octet-stream"},
    ".md": {"text/markdown", "text/plain", "application/octet-stream"},
    ".docx": {_DOCX_MEDIA_TYPE, "application/octet-stream"},
}
_CANONICAL_MEDIA_TYPE_BY_EXTENSION = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".docx": _DOCX_MEDIA_TYPE,
}


@dataclass
class BufferedUpload:
    file: BufferedIOBase
    size_bytes: int

    def peek_prefix(self, max_bytes: int = UPLOAD_SIGNATURE_READ_BYTES) -> bytes:
        self.file.seek(0)
        prefix = self.file.read(max_bytes)
        self.file.seek(0)
        return prefix

    def close(self) -> None:
        self.file.close()


def _normalized_extension(filename: str) -> str:
    if "." not in filename:
        return ""
    return f".{filename.rsplit('.', 1)[-1].lower()}"


def is_safe_preview_media_type(media_type: str) -> bool:
    return normalize_media_type(media_type) in _PREVIEWABLE_IMAGE_MEDIA_TYPES


def validate_workspace_upload_declaration(filename: str, media_type: str) -> str:
    extension = _normalized_extension(filename)
    allowed_media_types = _WORKSPACE_UPLOAD_MEDIA_TYPES_BY_EXTENSION.get(extension)
    if not allowed_media_types:
        raise ApiError("unsupported_media_type", "Unsupported upload file type", status_code=415)

    normalized_media_type = normalize_media_type(media_type or "application/octet-stream")
    if normalized_media_type not in allowed_media_types:
        raise ApiError("unsupported_media_type", "Unsupported upload file type", status_code=415)

    if normalized_media_type == "application/octet-stream":
        return _CANONICAL_MEDIA_TYPE_BY_EXTENSION[extension]
    return normalized_media_type


def _prefix_matches_declared_media_type(prefix: bytes, media_type: str) -> bool:
    if media_type == "image/jpeg":
        return prefix.startswith(b"\xff\xd8\xff")
    if media_type == "image/png":
        return prefix.startswith(b"\x89PNG\r\n\x1a\n")
    if media_type == "image/webp":
        return len(prefix) >= 12 and prefix.startswith(b"RIFF") and prefix[8:12] == b"WEBP"
    if media_type == "image/gif":
        return prefix.startswith((b"GIF87a", b"GIF89a"))
    if media_type == "image/bmp":
        return prefix.startswith(b"BM")
    if media_type == "image/tiff":
        return prefix.startswith((b"II*\x00", b"MM\x00*"))
    if media_type == "application/pdf":
        return prefix.startswith(b"%PDF-")
    if media_type == _DOCX_MEDIA_TYPE:
        return prefix.startswith(b"PK\x03\x04")
    if media_type == "video/mp4":
        return len(prefix) >= 12 and prefix[4:8] == b"ftyp"
    if media_type == "video/quicktime":
        return len(prefix) >= 12 and prefix[4:8] == b"ftyp"
    if media_type == "video/webm":
        return prefix.startswith(b"\x1a\x45\xdf\xa3")
    if media_type in _TEXTUAL_MEDIA_TYPES:
        return b"\x00" not in prefix
    return True


def validate_workspace_upload_signature(*, prefix: bytes, media_type: str) -> None:
    normalized_media_type = normalize_media_type(media_type)
    if _prefix_matches_declared_media_type(prefix, normalized_media_type):
        return
    raise ApiError("upload_mismatch", "Uploaded object contents do not match declared file type", status_code=400)


def ensure_uploaded_object_matches(
    *,
    bucket_name: str,
    object_key: str,
    expected_size_bytes: int,
    expected_media_type: str,
    missing_message: str,
    mismatch_message: str,
) -> None:
    metadata = get_object_metadata(bucket_name=bucket_name, object_key=object_key)
    if not metadata:
        raise ApiError("upload_incomplete", missing_message, status_code=400)
    if uploaded_object_matches(
        metadata,
        expected_size_bytes=expected_size_bytes,
        expected_media_type=expected_media_type,
    ):
        return
    delete_object(bucket_name=bucket_name, object_key=object_key)
    raise ApiError("upload_mismatch", mismatch_message, status_code=400)


def ensure_uploaded_object_signature_matches(
    *,
    bucket_name: str,
    object_key: str,
    media_type: str,
    mismatch_message: str,
) -> None:
    prefix = read_object_prefix(
        bucket_name=bucket_name,
        object_key=object_key,
        max_bytes=UPLOAD_SIGNATURE_READ_BYTES,
    )
    if prefix is None:
        raise ApiError("upload_incomplete", "Uploaded object not found", status_code=400)
    try:
        validate_workspace_upload_signature(prefix=prefix, media_type=media_type)
    except ApiError as exc:
        delete_object(bucket_name=bucket_name, object_key=object_key)
        raise ApiError("upload_mismatch", mismatch_message, status_code=400) from exc


async def buffer_upload_body(
    request: Request,
    *,
    expected_size: int,
    max_bytes: int,
) -> BufferedUpload:
    header_length = request.headers.get("content-length")
    if not header_length:
        raise ApiError("length_required", "Content-Length header is required", status_code=411)
    try:
        content_length = int(header_length)
    except ValueError as exc:
        raise ApiError("invalid_length", "Invalid Content-Length header", status_code=400) from exc
    if content_length <= 0:
        raise ApiError("empty_body", "Empty upload payload", status_code=400)
    if content_length != expected_size:
        raise ApiError("length_mismatch", "Content-Length does not match declared file size", status_code=400)
    if content_length > max_bytes:
        raise ApiError("payload_too_large", "Upload payload exceeds size limit", status_code=413)

    temp_file = SpooledTemporaryFile(max_size=min(max_bytes, UPLOAD_SPOOL_MAX_MEMORY_BYTES))
    total = 0
    try:
        async for chunk in request.stream():
            if not chunk:
                continue
            total += len(chunk)
            if total > max_bytes:
                raise ApiError("payload_too_large", "Upload payload exceeds size limit", status_code=413)
            temp_file.write(chunk)
        if total != expected_size:
            raise ApiError("length_mismatch", "Uploaded body size does not match declared file size", status_code=400)
        temp_file.seek(0)
        return BufferedUpload(file=temp_file, size_bytes=total)
    except Exception:
        temp_file.close()
        raise


async def read_upload_body(request: Request, *, expected_size: int, max_bytes: int) -> bytes:
    buffered_upload = await buffer_upload_body(
        request,
        expected_size=expected_size,
        max_bytes=max_bytes,
    )
    try:
        return buffered_upload.file.read()
    finally:
        buffered_upload.close()
