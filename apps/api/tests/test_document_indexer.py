import io
import zipfile

from app.services.document_indexer import build_file_fallback_text, extract_text_from_content


def _build_minimal_pptx(slides: list[str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        for index, slide_text in enumerate(slides, start=1):
            z.writestr(
                f"ppt/slides/slide{index}.xml",
                (
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    "<p:sld>"
                    "<a:t>"
                    f"{slide_text}"
                    "</a:t>"
                    "</p:sld>"
                ),
            )
    return buffer.getvalue()


def test_extract_text_from_pptx_content_reads_slide_text() -> None:
    payload = _build_minimal_pptx(["Intro slide", "Second slide"])

    text = extract_text_from_content(payload, "deck.pptx")

    assert "Intro slide" in text
    assert "Second slide" in text


def test_extract_text_from_python_source_reads_plain_text() -> None:
    payload = b"def greet(name):\n    return f'hello {name}'\n"

    text = extract_text_from_content(payload, "greet.py")

    assert "def greet(name)" in text
    assert "return f'hello {name}'" in text


def test_extract_text_from_ipynb_reads_cell_sources() -> None:
    payload = (
        b'{"cells":[{"cell_type":"markdown","source":["# Intro\\n","Notebook note"]},'
        b'{"cell_type":"code","source":["print(1)\\n"]}]}'
    )

    text = extract_text_from_content(payload, "lesson.ipynb")

    assert "markdown" in text
    assert "Notebook note" in text
    assert "print(1)" in text


def test_extract_text_from_unknown_binary_returns_empty_string() -> None:
    payload = b"\x00\x01\x02\x03binary-model-weights"

    text = extract_text_from_content(payload, "weights.gguf")

    assert text == ""


def test_build_file_fallback_text_includes_archive_members_for_unknown_binary() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("README.md", "# Hello")
        archive.writestr("src/main.py", "print('ok')\n")

    summary = build_file_fallback_text(
        buffer.getvalue(),
        "bundle.custompkg",
        "application/octet-stream",
    )

    assert "Uploaded file summary" in summary
    assert "bundle.custompkg" in summary
    assert "README.md" in summary
    assert "src/main.py" in summary
