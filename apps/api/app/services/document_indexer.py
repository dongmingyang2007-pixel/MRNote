from __future__ import annotations

import io
import logging
import re
import zipfile

from sqlalchemy.orm import Session

from app.services.embedding import embed_and_store

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "bmp", "webp", "tiff", "tif"}


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


def extract_text_from_content(content: bytes, filename: str) -> str:
    """Extract plain text from file content based on extension.

    For image files, returns empty string — use extract_text_async instead.
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext in IMAGE_EXTENSIONS:
        return ""  # Images require async OCR, handled in index_document

    if ext in ("txt", "md"):
        return content.decode("utf-8", errors="ignore")

    if ext == "pdf":
        try:
            import pdfplumber  # noqa: WPS433

            with pdfplumber.open(io.BytesIO(content)) as pdf:
                return "\n".join(page.extract_text() or "" for page in pdf.pages)
        except Exception:  # noqa: BLE001
            return ""

    if ext == "docx":
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                with z.open("word/document.xml") as f:
                    xml_content = f.read().decode("utf-8")
                    text = re.sub(r"<[^>]+>", " ", xml_content)
                    return re.sub(r"\s+", " ", text).strip()
        except Exception:  # noqa: BLE001
            return ""

    # Fallback: try as plain text
    return content.decode("utf-8", errors="ignore")


async def index_document(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    data_item_id: str,
    content: bytes,
    filename: str,
) -> int:
    """Index a document: extract text, chunk, embed, store.

    Supports text files (txt, md, pdf, docx) and image files (via OCR).
    Returns the number of chunks created.
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext in IMAGE_EXTENSIONS:
        text = await _ocr_image(content)
    else:
        text = extract_text_from_content(content, filename)

    if not text.strip():
        return 0

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
