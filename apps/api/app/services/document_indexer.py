from __future__ import annotations

import io
import json
import logging
import re
import zipfile

from sqlalchemy.orm import Session

from app.services.embedding import embed_and_store

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "bmp", "webp", "tiff", "tif"}
MARKUP_EXTENSIONS = {"html", "htm", "xml"}
FALLBACK_PREVIEW_SAMPLE_BYTES = 4096
FALLBACK_PREVIEW_MAX_CHARS = 1200
FALLBACK_ARCHIVE_MEMBER_LIMIT = 20


def _decode_text(content: bytes) -> str:
    return content.decode("utf-8", errors="ignore").replace("\ufeff", "")


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """Split text into overlapping chunks."""
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk.strip())
        start = end - overlap
    return chunks


async def _ocr_image(content: bytes) -> str:
    """Use Qwen-VL-OCR to extract text from an image."""
    from app.core.config import settings

    if not settings.dashscope_api_key:
        return ""

    try:
        from app.services.vision_client import describe_image

        return await describe_image(
            content,
            prompt="请识别并提取这张图片中的所有文字内容。如果图片没有文字，请简要描述图片内容。",
            model="qwen-vl-ocr",
        )
    except Exception:  # noqa: BLE001
        # Fallback to qwen-vl-plus if qwen-vl-ocr is unavailable
        try:
            from app.services.vision_client import describe_image

            return await describe_image(
                content,
                prompt="请识别并提取这张图片中的所有文字内容。如果图片没有文字，请简要描述图片内容。",
                model="qwen-vl-plus",
            )
        except Exception:  # noqa: BLE001
            logger.warning("Image OCR failed for both qwen-vl-ocr and qwen-vl-plus")
            return ""


def _extract_office_xml_text(content: bytes, member_names: list[str]) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            parts: list[str] = []
            for member_name in member_names:
                with z.open(member_name) as f:
                    xml_content = f.read().decode("utf-8", errors="ignore")
                    text = re.sub(r"<[^>]+>", " ", xml_content)
                    cleaned = re.sub(r"\s+", " ", text).strip()
                    if cleaned:
                        parts.append(cleaned)
            return "\n".join(parts)
    except Exception:  # noqa: BLE001
        return ""


def _extract_markup_text(content: bytes) -> str:
    raw = _decode_text(content)
    without_tags = re.sub(r"<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", without_tags).strip()


def _extract_notebook_text(content: bytes) -> str:
    try:
        payload = json.loads(_decode_text(content))
    except Exception:  # noqa: BLE001
        return _decode_text(content)

    cells = payload.get("cells")
    if not isinstance(cells, list):
        return _decode_text(content)

    parts: list[str] = []
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        cell_type = str(cell.get("cell_type") or "").strip()
        source = cell.get("source")
        if isinstance(source, list):
            text = "".join(str(item) for item in source)
        else:
            text = str(source or "")
        text = text.strip()
        if not text:
            continue
        parts.append(f"{cell_type}\n{text}" if cell_type else text)
    return "\n\n".join(parts)


def _looks_binary(content: bytes) -> bool:
    sample = content[:FALLBACK_PREVIEW_SAMPLE_BYTES]
    if not sample:
        return False
    if b"\x00" in sample:
        return True

    decoded = _decode_text(sample)
    if not decoded.strip():
        return True

    printable = sum(1 for ch in decoded if ch.isprintable() or ch in "\n\r\t")
    return printable / max(len(decoded), 1) < 0.85


def _extract_readable_preview(content: bytes) -> str:
    if _looks_binary(content):
        return ""

    preview = _decode_text(content[:FALLBACK_PREVIEW_SAMPLE_BYTES])
    preview = "".join(ch if ch.isprintable() or ch in "\n\r\t" else " " for ch in preview)
    preview = re.sub(r"\r\n?", "\n", preview)
    preview = re.sub(r"[ \t]+", " ", preview)
    preview = re.sub(r"\n{3,}", "\n\n", preview).strip()
    return preview[:FALLBACK_PREVIEW_MAX_CHARS].strip()


def _list_archive_members(content: bytes) -> list[str]:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            return [
                name
                for name in archive.namelist()
                if name and not name.endswith("/")
            ][:FALLBACK_ARCHIVE_MEMBER_LIMIT]
    except Exception:  # noqa: BLE001
        return []


def build_file_fallback_text(
    content: bytes,
    filename: str,
    media_type: str = "application/octet-stream",
) -> str:
    normalized_media_type = (media_type or "application/octet-stream").split(";", 1)[0].strip().lower()
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    parts = [
        "Uploaded file summary",
        f"Filename: {filename}",
        f"Media type: {normalized_media_type or 'application/octet-stream'}",
        f"Size: {len(content)} bytes",
    ]
    if extension:
        parts.append(f"Extension: .{extension}")
    parts.append(
        "Automatic parsing could not extract enough plain text, so this file was indexed from safe metadata and any readable preview that could be recovered."
    )

    archive_members = _list_archive_members(content)
    if archive_members:
        archive_listing = "\n".join(f"- {member}" for member in archive_members)
        parts.append(f"Archive contents:\n{archive_listing}")

    readable_preview = _extract_readable_preview(content)
    if readable_preview:
        parts.append(f"Readable preview:\n{readable_preview}")
    else:
        parts.append("Readable preview: No inline text preview was available from the uploaded bytes.")

    parts.append(
        "You can still attach notes, ask the assistant about this file, and link your own understanding to long-term memory."
    )
    return "\n\n".join(parts)


def extract_text_from_content(content: bytes, filename: str) -> str:
    """Extract plain text from file content based on extension.

    For image files, returns empty string — use extract_text_async instead.
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext in IMAGE_EXTENSIONS:
        return ""  # Images require async OCR, handled in index_document

    if ext in (
        "txt", "md", "csv", "tsv", "json", "yaml", "yml", "toml", "ini", "cfg", "env", "log",
        "rst", "tex", "py", "js", "jsx", "ts", "tsx", "java", "c", "cc", "cpp", "cxx",
        "h", "hpp", "cs", "go", "rs", "rb", "php", "swift", "kt", "kts", "scala", "r",
        "sql", "sh", "bash", "zsh", "fish", "ps1", "vue", "svelte",
    ):
        return _decode_text(content)

    if ext == "ipynb":
        return _extract_notebook_text(content)

    if ext in MARKUP_EXTENSIONS:
        return _extract_markup_text(content)

    if ext == "pdf":
        try:
            import pdfplumber  # noqa: WPS433

            with pdfplumber.open(io.BytesIO(content)) as pdf:
                return "\n".join(page.extract_text() or "" for page in pdf.pages)
        except Exception:  # noqa: BLE001
            return ""

    if ext == "docx":
        return _extract_office_xml_text(content, ["word/document.xml"])

    if ext == "pptx":
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                slide_names = sorted(
                    name
                    for name in z.namelist()
                    if name.startswith("ppt/slides/slide") and name.endswith(".xml")
                )
        except Exception:  # noqa: BLE001
            return ""
        return _extract_office_xml_text(content, slide_names)

    # Fallback: try as plain text
    if _looks_binary(content):
        return ""
    return _decode_text(content)


async def index_document(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    data_item_id: str,
    content: bytes,
    filename: str,
    media_type: str = "application/octet-stream",
) -> int:
    """Index a document: extract text, chunk, embed, store.

    Supports text files (txt, md, pdf, docx, pptx) and image files (via OCR).
    Returns the number of chunks created.
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext in IMAGE_EXTENSIONS:
        text = await _ocr_image(content)
    else:
        text = extract_text_from_content(content, filename)

    if not text.strip():
        text = build_file_fallback_text(content, filename, media_type)

    chunks = chunk_text(text)
    count = 0
    for chunk in chunks:
        try:
            await embed_and_store(
                db,
                workspace_id=workspace_id,
                project_id=project_id,
                data_item_id=data_item_id,
                chunk_text=chunk,
            )
            count += 1
        except Exception:  # noqa: BLE001
            continue  # Skip failed chunks

    return count
