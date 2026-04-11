from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services import qwen_official_catalog as service


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "qwen_official_catalog"


def read_fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def build_snapshot() -> dict:
    return service.generate_snapshot(
        {
            "models": read_fixture("models.html"),
            "text_generation": read_fixture("text_generation.html"),
            "chat_api": read_fixture("chat_api.html"),
        }
    )


def test_generate_snapshot_from_fixtures_keeps_current_models_separate() -> None:
    snapshot = build_snapshot()
    by_id = {item["canonical_model_id"]: item for item in snapshot["items"]}

    assert "qwen3.5-plus" in by_id
    assert "qwen-plus" in by_id
    assert by_id["qwen3.5-plus"]["aliases"] == ["qwen3-plus", "qwen3.5-plus-2026-02-15"]

    assert by_id["qwen3-livetranslate-flash"]["official_category_key"] == "speech_recognition"
    assert by_id["qwen3-livetranslate-flash"]["output_modalities"] == ["text", "audio"]

    assert by_id["qwen3-asr-flash"]["display_name"] == "Qwen3-ASR-Flash"
    assert by_id["qwen3-asr-flash"]["official_category_key"] == "speech_recognition"

    assert by_id["qwen3-vl-plus"]["display_name"] == "Qwen3-VL-Plus"
    assert by_id["qwen3-vl-plus"]["official_category_key"] == "vision"

    assert by_id["qwen3-tts-flash-realtime"]["official_category_key"] == "realtime_tts"
    assert by_id["qwen3-tts-flash-realtime"]["pipeline_slot"] == "realtime_tts"


def test_generate_snapshot_only_adds_explicit_tools_and_features() -> None:
    snapshot = build_snapshot()
    by_id = {item["canonical_model_id"]: item for item in snapshot["items"]}

    plus = by_id["qwen3.5-plus"]
    assert plus["supported_tools"] == [
        "code_interpreter",
        "file_search",
        "function_calling",
        "image_search",
        "mcp",
        "web_extractor",
        "web_search",
        "web_search_image",
    ]
    assert plus["supported_features"] == ["streaming"]
    assert plus["input_modalities"] == ["text", "image", "video"]
    assert plus["output_modalities"] == ["text"]


def test_fetch_rejects_cross_host_redirect(monkeypatch) -> None:
    class FakeResponse:
        headers = {"Content-Type": "text/html; charset=utf-8"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def geturl(self) -> str:
            return "https://example.com/redirected"

        def read(self, _size: int) -> bytes:
            return b"<html></html>"

    monkeypatch.setattr(service, "urlopen", lambda request, timeout=0: FakeResponse())

    with pytest.raises(ValueError, match="redirected host"):
        service._fetch("https://help.aliyun.com/zh/model-studio/models")


def test_fetch_rejects_oversized_payload(monkeypatch) -> None:
    class FakeResponse:
        headers = {"Content-Type": "text/html; charset=utf-8"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def geturl(self) -> str:
            return "https://help.aliyun.com/zh/model-studio/models"

        def read(self, _size: int) -> bytes:
            return b"x" * (service.MAX_FETCH_BYTES + 1)

    monkeypatch.setattr(service, "urlopen", lambda request, timeout=0: FakeResponse())

    with pytest.raises(ValueError, match="size limit"):
        service._fetch("https://help.aliyun.com/zh/model-studio/models")


def test_load_snapshot_falls_back_to_last_good_file(tmp_path: Path, monkeypatch) -> None:
    snapshot = build_snapshot()
    primary = tmp_path / "qwen_official_catalog.json"
    fallback = tmp_path / "qwen_official_catalog.last_good.json"

    monkeypatch.setattr(service, "CATALOG_SNAPSHOT_PATH", primary)
    monkeypatch.setattr(service, "CATALOG_SNAPSHOT_FALLBACK_PATH", fallback)
    service.load_snapshot.cache_clear()

    service.write_snapshot(snapshot, output_path=primary)
    primary.write_text("{broken", encoding="utf-8")

    loaded = service.load_snapshot()
    assert loaded.by_id["qwen3.5-plus"]["canonical_model_id"] == "qwen3.5-plus"
    assert json.loads(fallback.read_text(encoding="utf-8"))["items"]
    service.load_snapshot.cache_clear()
