from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Mapping
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup, Tag

from app.services.responses_native_tools import merge_native_tool_names

CATALOG_SNAPSHOT_PATH = Path(__file__).resolve().parent.parent / "data" / "qwen_official_catalog.json"
CATALOG_SNAPSHOT_FALLBACK_PATH = CATALOG_SNAPSHOT_PATH.with_name("qwen_official_catalog.last_good.json")

SOURCE_URLS = {
    "models": "https://help.aliyun.com/zh/model-studio/models",
    "text_generation": "https://help.aliyun.com/zh/model-studio/text-generation",
    "chat_api": "https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions",
}

ALLOWED_FETCH_HOSTS = {"help.aliyun.com"}
FETCH_TIMEOUT_SECONDS = 20
MAX_FETCH_BYTES = 8_000_000

MODEL_TOKEN_PATTERN = re.compile(
    r"(qwen[0-9A-Za-z._-]+|qwq[0-9A-Za-z._-]+|qvq[0-9A-Za-z._-]+|"
    r"cosyvoice-[0-9A-Za-z._-]+|paraformer-[0-9A-Za-z._-]+|"
    r"sensevoice-[0-9A-Za-z._-]+|sambert-[0-9A-Za-z._-]+|"
    r"fun-asr[0-9A-Za-z._-]*|text-embedding-v[0-9]+|multimodal-embedding-v[0-9]+)"
)

BLOCKED_EXACT_IDS = {
    "qwen.ai",
    "qwenlm.github.io",
    "qwen-api-reference",
    "qwen-asr-api-reference",
    "qwen-asr-realtime-api",
    "qwen-by-calling-api",
    "qwen-deep-research-api",
    "qwen-image-api",
    "qwen-image-edit-api",
    "qwen-image-edit-guide",
    "qwen-mt-image-api",
    "qwen-real-time-speech-recognition",
    "qwen-speech-recognition",
    "qwen-tts-api",
    "qwen-tts-realtime-api-reference",
    "qwen-vl-ocr-api-reference",
    "fun-asr-real-time-speech-recognition-api-reference",
    "fun-asr-recorded-speech-recognition-api-reference",
    "paraformer-real-time-speech-recognition-api-reference",
    "paraformer-recorded-speech-recognition-api-reference",
    "qwen3-livetranslate-flash-api",
}

NOISE_ALIASES = {"currenttab", "modelid"}
REGION_HEADINGS = {"中国内地", "全球", "国际", "美国", "金融云"}
IGNORED_TOP_LEVEL_HEADINGS = {
    "旗舰模型",
    "模型总览",
    "文本生成-第三方模型",
    "图像生成-第三方模型",
    "视频生成-第三方模型",
    "已下线模型",
}

OFFICIAL_TAXONOMY = [
    {
        "key": "omni",
        "label": "全模态",
        "group_key": "multimodal",
        "group_label": "多模态",
        "order": 10,
    },
    {
        "key": "deep_thinking",
        "label": "深度思考",
        "group_key": "text",
        "group_label": "文本",
        "order": 20,
    },
    {
        "key": "text_generation",
        "label": "文本生成",
        "group_key": "text",
        "group_label": "文本",
        "order": 30,
    },
    {
        "key": "vision",
        "label": "视觉理解",
        "group_key": "vision",
        "group_label": "视觉",
        "order": 40,
    },
    {
        "key": "image_generation",
        "label": "图片生成",
        "group_key": "vision",
        "group_label": "视觉",
        "order": 50,
    },
    {
        "key": "video_generation",
        "label": "视频生成",
        "group_key": "vision",
        "group_label": "视觉",
        "order": 60,
    },
    {
        "key": "speech_recognition",
        "label": "语音识别",
        "group_key": "speech",
        "group_label": "语音",
        "order": 70,
    },
    {
        "key": "speech_synthesis",
        "label": "语音合成",
        "group_key": "speech",
        "group_label": "语音",
        "order": 80,
    },
    {
        "key": "multimodal_embedding",
        "label": "多模态向量",
        "group_key": "embedding",
        "group_label": "向量",
        "order": 90,
    },
    {
        "key": "text_embedding",
        "label": "文本向量",
        "group_key": "embedding",
        "group_label": "向量",
        "order": 100,
    },
    {
        "key": "realtime_omni",
        "label": "实时全模态",
        "group_key": "realtime",
        "group_label": "Realtime",
        "order": 110,
    },
    {
        "key": "realtime_tts",
        "label": "实时语音合成",
        "group_key": "realtime",
        "group_label": "Realtime",
        "order": 120,
    },
    {
        "key": "realtime_asr",
        "label": "实时语音识别",
        "group_key": "realtime",
        "group_label": "Realtime",
        "order": 130,
    },
    {
        "key": "realtime_translate",
        "label": "实时语音翻译",
        "group_key": "realtime",
        "group_label": "Realtime",
        "order": 140,
    },
    {
        "key": "rerank",
        "label": "重排序",
        "group_key": "text",
        "group_label": "文本",
        "order": 150,
    },
]
TAXONOMY_BY_KEY = {item["key"]: item for item in OFFICIAL_TAXONOMY}

PIPELINE_SELECTABLE_IDS = {
    "qwen3.5-flash",
    "qwen3.5-plus",
    "qwen3-max",
    "qwen3-flash",
    "qwen2.5-72b-instruct",
    "qwen2.5-coder-32b",
    "qwen-vl-plus",
    "qwen-vl-max",
    "qwen-vl-ocr",
    "qwen3-vl-plus",
    "qwen3-omni-flash-realtime",
    "qwen3-asr-flash",
    "qwen3-asr-flash-realtime",
    "paraformer-v2",
    "paraformer-offline-v2",
    "sensevoice-v1",
    "fun-asr-realtime",
    "cosyvoice-v1",
    "cosyvoice-v2",
    "sambert-v1",
    "qwen3-tts-flash",
    "qwen3-tts-flash-realtime",
    "qwen-voice-enrollment",
}

LEGACY_CANONICAL_ALIASES: dict[str, tuple[str, ...]] = {
    "qwen3.5-plus": ("qwen3-plus",),
}

CHAT_API_TOOL_SECTION_MAP = {
    "工具调用": ("supported_tools", "function_calling"),
    "联网搜索": ("supported_tools", "web_search"),
    "流式输出": ("supported_features", "streaming"),
    "图像输入": ("input_modalities", "image"),
    "视频输入": ("input_modalities", "video"),
}


@dataclass(frozen=True)
class OfficialCatalogIndex:
    generated_at: datetime
    taxonomy: list[dict[str, Any]]
    items: list[dict[str, Any]]
    by_id: dict[str, dict[str, Any]]
    by_alias: dict[str, dict[str, Any]]


@dataclass
class RawOfficialModel:
    canonical_model_id: str
    major_heading: str
    family_heading: str
    sub_heading: str | None = None
    family_description: str | None = None
    row_descriptions: list[str] = field(default_factory=list)
    aliases: set[str] = field(default_factory=set)
    official_url: str | None = None
    source_order: int = 0
    input_modalities: set[str] = field(default_factory=set)
    output_modalities: set[str] = field(default_factory=set)
    supported_tools: set[str] = field(default_factory=set)
    supported_features: set[str] = field(default_factory=set)


def _clean_text(value: str) -> str:
    text = value.replace("\xa0", " ").replace("\u2009", " ").replace("\u202f", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _normalize_model_token(raw: str) -> str | None:
    token = raw.strip().lower().strip(" ,.;:()[]{}<>\"'`")
    if not token or token in BLOCKED_EXACT_IDS or token in NOISE_ALIASES:
        return None
    if "reference" in token or "guide" in token or "github" in token:
        return None
    if token.endswith(("-api", "-reference", "-guide")):
        return None
    return token


def _extract_model_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    seen: set[str] = set()
    for raw in MODEL_TOKEN_PATTERN.findall(text):
        normalized = _normalize_model_token(raw)
        if normalized and normalized not in seen:
            tokens.append(normalized)
            seen.add(normalized)
    return tokens


def _is_snapshot_or_latest(token: str) -> bool:
    return bool(
        token.endswith("-latest")
        or re.search(r"-(20\d{2}-\d{2}-\d{2})$", token)
        or re.search(r"-(\d{4})$", token)
        or token.endswith(("-us", "-cn-bj"))
    )


def _alias_base(token: str) -> str:
    value = re.sub(r"-latest$", "", token)
    value = re.sub(r"-(?:20\d{2}-\d{2}-\d{2})$", "", value)
    value = re.sub(r"-(?:\d{4})$", "", value)
    value = re.sub(r"-(?:us|cn-bj)$", "", value)
    return value


def _is_current_model_token(token: str) -> bool:
    return not _is_snapshot_or_latest(token)


def _belongs_to_model(token: str, model_id: str) -> bool:
    return token == model_id or _alias_base(token) == model_id


def _relevant_help_url(section: Tag) -> str | None:
    for anchor in section.find_all("a", href=True):
        href = anchor["href"].strip()
        parsed = urlparse(href)
        if parsed.scheme != "https" or parsed.netloc != "help.aliyun.com":
            continue
        if "/regions/" in parsed.path:
            continue
        return href
    return None


def _top_level_heading_for(tag: Tag) -> str:
    current = tag.find_previous("h2")
    while current is not None:
        text = _clean_text(current.get_text(" ", strip=True))
        if text and text not in REGION_HEADINGS and text not in IGNORED_TOP_LEVEL_HEADINGS:
            if not re.match(r"^20\d{2} 年", text):
                return text
        current = current.find_previous("h2")
    return "模型列表"


def _extract_family_description(section: Tag) -> str | None:
    snippets: list[str] = []
    for node in section.descendants:
        if isinstance(node, Tag):
            if node.name == "table":
                break
            if node.name not in {"p", "blockquote"}:
                continue
            text = _clean_text(node.get_text(" ", strip=True))
            if not text:
                continue
            if text.startswith("在 中国内地部署模式") or text.startswith("在 全球部署模式") or text.startswith("在 国际部署模式"):
                continue
            snippets.append(text)
    if not snippets:
        return None
    return snippets[0]


def _extract_row_description(cell_text: str, model_id: str) -> str | None:
    text = _clean_text(cell_text)
    if not text:
        return None
    text = re.sub(rf"^{re.escape(model_id)}\b", "", text).strip()
    text = re.sub(r"^(当前与|当前等同|当前能力等同于|当前能力等同|能力始终等同)\s+[0-9A-Za-z._-]+\s*(能力相同|相同)?", "", text)
    text = re.sub(r"^始终与最新版能力相同", "", text)
    text = re.sub(r"^又称\s+[0-9A-Za-z._-]+", "", text)
    text = re.sub(r"\b(Batch 调用 半价|稳定版|最新版|快照版|默认开启思考模式)\b", "", text)
    text = _clean_text(text)
    if not text:
        return None
    if text in {"思考", "非思考"}:
        return None
    return text


def _titleize_model_id(model_id: str) -> str:
    def normalize_segment(segment: str) -> str:
        lowered = segment.lower()
        if lowered.startswith("qwen"):
            suffix = segment[4:]
            return f"Qwen{suffix}"
        if lowered.startswith("qwq"):
            suffix = segment[3:]
            return f"QwQ{suffix}"
        if lowered.startswith("qvq"):
            suffix = segment[3:]
            return f"QVQ{suffix}"
        if lowered == "asr":
            return "ASR"
        if lowered == "tts":
            return "TTS"
        if lowered == "vl":
            return "VL"
        if lowered == "ocr":
            return "OCR"
        if lowered == "mt":
            return "MT"
        if lowered == "vc":
            return "VC"
        if lowered == "vd":
            return "VD"
        if lowered.startswith("v") and lowered[1:].isdigit():
            return lowered.upper()
        word_map = {
            "omni": "Omni",
            "flash": "Flash",
            "plus": "Plus",
            "max": "Max",
            "turbo": "Turbo",
            "long": "Long",
            "coder": "Coder",
            "image": "Image",
            "audio": "Audio",
            "math": "Math",
            "realtime": "Realtime",
            "livetranslate": "LiveTranslate",
            "captioner": "Captioner",
            "thinking": "Thinking",
            "instruct": "Instruct",
            "filetrans": "Filetrans",
        }
        if lowered in word_map:
            return word_map[lowered]
        if lowered.startswith("cosyvoice"):
            suffix = segment[9:]
            return f"CosyVoice{suffix}"
        if lowered.startswith("paraformer"):
            suffix = segment[10:]
            return f"Paraformer{suffix}"
        if lowered.startswith("sensevoice"):
            suffix = segment[10:]
            return f"SenseVoice{suffix}"
        if lowered.startswith("sambert"):
            suffix = segment[7:]
            return f"Sambert{suffix}"
        if lowered.startswith("fun"):
            return "Fun"
        if lowered == "asr":
            return "ASR"
        return segment[:1].upper() + segment[1:]

    return "-".join(normalize_segment(segment) for segment in model_id.split("-"))


def _classify_category_key(raw: RawOfficialModel) -> str:
    top_level = raw.major_heading
    family = raw.family_heading
    model_id = raw.canonical_model_id

    if top_level == "图像生成":
        return "image_generation"
    if top_level == "视频生成-万相与视频编辑":
        return "video_generation"
    if top_level == "文本向量":
        return "text_embedding"
    if top_level == "多模态向量":
        return "multimodal_embedding"
    if top_level == "文本分类、抽取、排序":
        return "rerank"
    if top_level == "语音合成（文本转语音）":
        return "realtime_tts" if "realtime" in model_id else "speech_synthesis"
    if top_level == "语音识别（语音转文本）与翻译（语音转成指定语种的文本）":
        if "livetranslate" in model_id and "realtime" in model_id:
            return "realtime_translate"
        if "realtime" in model_id:
            return "realtime_asr"
        return "speech_recognition"
    if "omni-realtime" in family.lower() or ("omni" in model_id and "realtime" in model_id):
        return "realtime_omni"
    if "omni" in family.lower() or (model_id.startswith(("qwen-omni", "qwen2.5-omni", "qwen3-omni")) and "realtime" not in model_id):
        return "omni"
    if any(keyword in family.lower() for keyword in {"qwq", "qvq", "深入研究"}) or model_id.startswith(("qwq", "qvq")):
        return "deep_thinking"
    if any(keyword in family for keyword in {"VL", "OCR"}) or any(keyword in model_id for keyword in {"-vl-", "-vl", "ocr"}):
        return "vision"
    return "text_generation"


def _pipeline_slot_for_category(category_key: str) -> str | None:
    if category_key in {"omni", "deep_thinking", "text_generation"}:
        return "llm"
    if category_key == "vision":
        return "vision"
    if category_key == "speech_recognition":
        return "asr"
    if category_key == "speech_synthesis":
        return "tts"
    if category_key == "realtime_omni":
        return "realtime"
    if category_key == "realtime_asr":
        return "realtime_asr"
    if category_key == "realtime_tts":
        return "realtime_tts"
    return None


def _derive_modalities(raw: RawOfficialModel, category_key: str) -> tuple[list[str], list[str]]:
    input_modalities = set(raw.input_modalities)
    output_modalities = set(raw.output_modalities)

    combined_text = " ".join(
        part for part in [raw.family_description or "", *raw.row_descriptions] if part
    )

    if "支持文本、图像和视频输入" in combined_text:
        input_modalities.update({"text", "image", "video"})
    if "支持文本、图像和音频输入" in combined_text:
        input_modalities.update({"text", "image", "audio"})
    if "支持文本输入" in combined_text:
        input_modalities.add("text")
    if "支持图片" in combined_text or "视觉（图像）理解" in combined_text:
        input_modalities.add("image")
    if "支持视频" in combined_text or "音视频" in combined_text:
        input_modalities.add("video")
    if category_key in {"speech_recognition", "realtime_asr", "realtime_translate"}:
        input_modalities.add("audio")
    if "音频输入" in combined_text or "语音输入" in combined_text:
        input_modalities.add("audio")
    if "输出文本与语音" in combined_text or "输出文本+音频" in combined_text:
        output_modalities.update({"text", "audio"})
    if "流式输出音频" in combined_text or category_key in {"speech_synthesis", "realtime_tts"}:
        output_modalities.add("audio")

    if category_key in {"deep_thinking", "text_generation"}:
        input_modalities.add("text")
        output_modalities.add("text")
    elif category_key == "omni":
        input_modalities.update({"text", "image", "audio", "video"})
        output_modalities.update({"text", "audio"})
    elif category_key == "vision":
        input_modalities.update({"text", "image"})
        output_modalities.add("text")
    elif category_key == "image_generation":
        input_modalities.add("text")
        if "edit" in raw.canonical_model_id:
            input_modalities.add("image")
        output_modalities.add("image")
    elif category_key == "video_generation":
        input_modalities.add("text")
        output_modalities.add("video")
    elif category_key in {"speech_recognition", "realtime_asr"}:
        input_modalities.add("audio")
        output_modalities.add("text")
    elif category_key in {"speech_synthesis", "realtime_tts"}:
        input_modalities.add("text")
        output_modalities.add("audio")
    elif category_key == "realtime_translate":
        input_modalities.update({"audio", "image"})
        output_modalities.update({"text", "audio"})
    elif category_key == "realtime_omni":
        input_modalities.update({"text", "image", "audio"})
        output_modalities.update({"text", "audio"})
    elif category_key in {"text_embedding", "multimodal_embedding", "rerank"}:
        input_modalities.add("text")
        if category_key == "multimodal_embedding":
            input_modalities.add("image")
        output_modalities.add("text")

    ordered_modalities = ["text", "image", "audio", "video"]
    return (
        [value for value in ordered_modalities if value in input_modalities],
        [value for value in ordered_modalities if value in output_modalities],
    )


def _select_description(raw: RawOfficialModel, display_name: str) -> str:
    candidates = [entry for entry in raw.row_descriptions if entry]
    for candidate in candidates:
        if len(candidate) >= 10:
            return _sanitize_description(candidate)
    if raw.family_description:
        family_text = raw.family_description
        model_tokens = _extract_model_tokens(family_text)
        if not model_tokens:
            return _sanitize_description(family_text)
        if raw.canonical_model_id in model_tokens or display_name in family_text:
            return _sanitize_description(family_text)
        if len({raw.canonical_model_id, *raw.aliases} & set(model_tokens)) > 0:
            return _sanitize_description(family_text)
    return _sanitize_description(raw.family_description or "")


def _sanitize_description(text: str) -> str:
    cleaned = _clean_text(text)
    cleaned = re.sub(
        r"(?:\s*[｜|]\s*|\s+)(?:使用方法|思考模式|API\s*参考|在线体验)(?:(?:\s*[｜|]\s*|\s+)(?:使用方法|思考模式|API\s*参考|在线体验))*\s*$",
        "",
        cleaned,
    )
    return _clean_text(cleaned)


def _official_url_for_model(raw: RawOfficialModel, category_key: str) -> str:
    if raw.official_url:
        return raw.official_url
    if category_key in {"deep_thinking", "text_generation", "omni", "vision"}:
        return SOURCE_URLS["text_generation"]
    return SOURCE_URLS["models"]


def _ensure_iterable_text(tag: Tag) -> str:
    return _clean_text(tag.get_text(" ", strip=True))


def _parse_models_page(html: str) -> dict[str, RawOfficialModel]:
    soup = BeautifulSoup(html, "lxml")
    main = soup.find(id="aliyun-docs-view") or soup.find("main")
    if not isinstance(main, Tag):
        raise ValueError("Unable to locate official documentation content in models page")

    models: dict[str, RawOfficialModel] = {}
    source_order = 0

    for heading in main.find_all("h3"):
        family_heading = _ensure_iterable_text(heading)
        section = heading.find_next_sibling("section")
        if not isinstance(section, Tag):
            continue

        top_level_heading = _top_level_heading_for(heading)
        family_description = _extract_family_description(section)
        official_url = _relevant_help_url(section)
        current_subheading: str | None = None
        current_model_id: str | None = None

        for node in section.descendants:
            if not isinstance(node, Tag):
                continue

            if node.name == "h5":
                current_subheading = _ensure_iterable_text(node)
                current_model_id = None
                continue

            if node.name != "table":
                continue

            for row in node.find_all("tr"):
                cells = row.find_all(["td", "th"])
                if not cells:
                    continue
                first_cell_text = _ensure_iterable_text(cells[0])
                tokens = _extract_model_tokens(first_cell_text)
                if not tokens:
                    continue

                primary_token = tokens[0]
                if _is_current_model_token(primary_token):
                    current_model_id = primary_token
                    source_order += 1
                    entry = models.get(current_model_id)
                    if entry is None:
                        entry = RawOfficialModel(
                            canonical_model_id=current_model_id,
                            major_heading=top_level_heading,
                            family_heading=family_heading,
                            sub_heading=current_subheading,
                            family_description=family_description,
                            official_url=official_url,
                            source_order=source_order,
                        )
                        models[current_model_id] = entry
                    else:
                        entry.major_heading = top_level_heading
                        entry.family_heading = family_heading
                        entry.sub_heading = current_subheading or entry.sub_heading
                        entry.family_description = entry.family_description or family_description
                        entry.official_url = entry.official_url or official_url
                        entry.source_order = min(entry.source_order, source_order)
                    description = _extract_row_description(first_cell_text, current_model_id)
                    if description:
                        entry.row_descriptions.append(description)
                    for token in tokens[1:]:
                        if _belongs_to_model(token, current_model_id):
                            entry.aliases.add(token)
                    continue

                if current_model_id is None or not _belongs_to_model(primary_token, current_model_id):
                    continue

                entry = models[current_model_id]
                entry.aliases.add(primary_token)
                for token in tokens[1:]:
                    if _belongs_to_model(token, current_model_id):
                        entry.aliases.add(token)
                alias_description = _extract_row_description(first_cell_text, primary_token)
                if alias_description:
                    entry.row_descriptions.append(alias_description)

    for model_id, extra_aliases in LEGACY_CANONICAL_ALIASES.items():
        entry = models.get(model_id)
        if entry:
            entry.aliases.update(extra_aliases)

    return models


def _augment_from_chat_api(html: str, models: dict[str, RawOfficialModel]) -> None:
    soup = BeautifulSoup(html, "lxml")
    main = soup.find(id="aliyun-docs-view") or soup.find("main")
    if not isinstance(main, Tag):
        return

    for heading in main.find_all("h2"):
        section_title = _ensure_iterable_text(heading)
        mapping = CHAT_API_TOOL_SECTION_MAP.get(section_title)
        if mapping is None:
            continue
        field_name, value = mapping
        content_parts: list[str] = []
        for sibling in heading.find_next_siblings():
            if isinstance(sibling, Tag) and sibling.name == "h2":
                break
            if isinstance(sibling, Tag):
                content_parts.append(_ensure_iterable_text(sibling))
        section_text = " ".join(content_parts)
        for token in _extract_model_tokens(section_text):
            model_id = token if token in models else _alias_base(token)
            raw = models.get(model_id)
            if raw is None:
                continue
            getattr(raw, field_name).add(value)

    lowered = html.lower()
    for model_id in ("qwen3.5-plus", "qwen3.5-flash", "qwen3-max"):
        if model_id in lowered and "enable_search" in lowered:
            if re.search(rf"(agent|max).*{re.escape(model_id)}|{re.escape(model_id)}.*(agent|max)", lowered):
                raw = models.get(model_id)
                if raw is not None:
                    raw.supported_tools.add("web_search")


def _augment_from_text_generation(html: str, models: dict[str, RawOfficialModel]) -> None:
    soup = BeautifulSoup(html, "lxml")
    main = soup.find(id="aliyun-docs-view") or soup.find("main")
    if not isinstance(main, Tag):
        return

    text = _ensure_iterable_text(main)

    plus = models.get("qwen3.5-plus")
    if plus is not None:
        if re.search(r"Qwen3\.5-Plus\s*系列", text) and "同时支持视觉与文本输入" in text:
            plus.input_modalities.update({"text", "image", "video"})
            plus.output_modalities.add("text")
            plus.row_descriptions.append(
                "Qwen3.5-Plus系列同时支持视觉与文本输入，在语言理解、逻辑推理、代码生成、智能体任务、图像理解、视频理解、图形用户界面（GUI）等多种任务中展现出卓越性能。"
            )
        if re.search(r"Qwen3\.5-Plus\s*系列.{0,120}支持内置\s*工具调用", text):
            plus.supported_tools.add("function_calling")
        if "Qwen3.5 系列默认开启" in text:
            plus.supported_features.add("deep_thinking")


def _validate_snapshot(snapshot: Mapping[str, Any]) -> None:
    items = snapshot.get("items", [])
    if not isinstance(items, list) or not items:
        raise ValueError("Generated Qwen official catalog snapshot is empty")
    required_fields = {
        "canonical_model_id",
        "display_name",
        "official_group",
        "official_group_key",
        "official_category",
        "official_category_key",
        "description",
        "input_modalities",
        "output_modalities",
        "official_url",
    }
    for item in items:
        missing = [field for field in required_fields if field not in item]
        if missing:
            raise ValueError(f"Snapshot item missing fields: {missing}")


def _fetch(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc not in ALLOWED_FETCH_HOSTS:
        raise ValueError(f"Refusing to fetch non-official host: {url}")

    request = Request(
        url,
        headers={
            "User-Agent": "Mingrun-QwenCatalogSync/1.0",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    with urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
        final_url = response.geturl()
        final_parsed = urlparse(final_url)
        if final_parsed.scheme != "https" or final_parsed.netloc != parsed.netloc:
            raise ValueError(f"Refusing redirected host for {url}: {final_url}")
        content_type = response.headers.get("Content-Type", "")
        if "html" not in content_type:
            raise ValueError(f"Unexpected content type for {url}: {content_type}")
        payload = response.read(MAX_FETCH_BYTES + 1)
        if len(payload) > MAX_FETCH_BYTES:
            raise ValueError(f"Response exceeds size limit for {url}")
    return payload.decode("utf-8", "ignore")


def generate_snapshot(source_payloads: Mapping[str, str] | None = None) -> dict[str, Any]:
    payloads = {key: value for key, value in (source_payloads or {}).items()}
    for key, url in SOURCE_URLS.items():
        payloads.setdefault(key, _fetch(url))

    raw_models = _parse_models_page(payloads["models"])
    _augment_from_chat_api(payloads["chat_api"], raw_models)
    _augment_from_text_generation(payloads["text_generation"], raw_models)

    items: list[dict[str, Any]] = []
    for raw in sorted(raw_models.values(), key=lambda item: item.source_order):
        category_key = _classify_category_key(raw)
        taxonomy_entry = TAXONOMY_BY_KEY[category_key]
        display_name = _titleize_model_id(raw.canonical_model_id)
        input_modalities, output_modalities = _derive_modalities(raw, category_key)
        supported_tools = merge_native_tool_names(raw.canonical_model_id, raw.supported_tools)
        supported_features = sorted(raw.supported_features)
        pipeline_slot = _pipeline_slot_for_category(category_key)
        aliases = sorted(alias for alias in raw.aliases if alias != raw.canonical_model_id)
        is_selectable = raw.canonical_model_id in PIPELINE_SELECTABLE_IDS or any(
            alias in PIPELINE_SELECTABLE_IDS for alias in aliases
        )

        items.append(
            {
                "canonical_model_id": raw.canonical_model_id,
                "model_id": raw.canonical_model_id,
                "display_name": display_name,
                "provider": "qwen",
                "provider_display": "千问 · 阿里云",
                "official_group_key": taxonomy_entry["group_key"],
                "official_group": taxonomy_entry["group_label"],
                "official_category_key": taxonomy_entry["key"],
                "official_category": taxonomy_entry["label"],
                "official_order": taxonomy_entry["order"] * 1000 + raw.source_order,
                "description": _select_description(raw, display_name),
                "input_modalities": input_modalities,
                "output_modalities": output_modalities,
                "supported_tools": supported_tools,
                "supported_features": supported_features,
                "official_url": _official_url_for_model(raw, category_key),
                "aliases": aliases,
                "pipeline_slot": pipeline_slot,
                "is_selectable_in_console": is_selectable,
            }
        )

    counts = defaultdict(int)
    for item in items:
        counts[item["official_category_key"]] += 1

    taxonomy = [
        {
            "key": entry["key"],
            "label": entry["label"],
            "group_key": entry["group_key"],
            "group_label": entry["group_label"],
            "group": entry["group_label"],
            "order": entry["order"],
            "count": counts.get(entry["key"], 0),
        }
        for entry in OFFICIAL_TAXONOMY
    ]

    snapshot = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": SOURCE_URLS,
        "taxonomy": taxonomy,
        "items": items,
    }
    _validate_snapshot(snapshot)
    return snapshot


def _atomic_write_json(output_path: Path, payload: Mapping[str, Any]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=output_path.parent, delete=False) as temp_file:
        temp_file.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        temp_path = Path(temp_file.name)
    temp_path.replace(output_path)


def _fallback_path_for(output_path: Path) -> Path:
    if output_path == CATALOG_SNAPSHOT_PATH:
        return CATALOG_SNAPSHOT_FALLBACK_PATH
    return output_path.with_name(f"{output_path.stem}.last_good{output_path.suffix}")


def write_snapshot(snapshot: dict[str, Any], output_path: Path = CATALOG_SNAPSHOT_PATH) -> Path:
    _validate_snapshot(snapshot)
    _atomic_write_json(output_path, snapshot)
    _atomic_write_json(_fallback_path_for(output_path), snapshot)
    if output_path == CATALOG_SNAPSHOT_PATH:
        reload_snapshot()
    return output_path


def _read_snapshot_payload(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_snapshot() -> OfficialCatalogIndex:
    payload: dict[str, Any] | None = None
    for path in (CATALOG_SNAPSHOT_PATH, CATALOG_SNAPSHOT_FALLBACK_PATH):
        if not path.exists():
            continue
        try:
            payload = _read_snapshot_payload(path)
            break
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    if payload is None:
        raise FileNotFoundError("Qwen official catalog snapshot is missing or invalid")

    generated_at = datetime.fromisoformat(payload["generated_at"])
    raw_items = payload.get("items", [])
    items: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    by_alias: dict[str, dict[str, Any]] = {}

    for item in raw_items:
        normalized = dict(item)
        normalized.setdefault("model_id", normalized["canonical_model_id"])
        normalized.setdefault("provider", "qwen")
        normalized.setdefault("provider_display", "千问 · 阿里云")
        normalized.setdefault("official_group_key", "")
        normalized.setdefault("official_category_key", "")
        normalized["supported_tools"] = merge_native_tool_names(
            str(normalized["canonical_model_id"]),
            normalized.get("supported_tools", []),
        )
        normalized.setdefault("supported_features", [])
        normalized.setdefault("aliases", [])
        normalized.setdefault("pipeline_slot", None)
        normalized.setdefault("is_selectable_in_console", False)
        items.append(normalized)
        by_id[normalized["canonical_model_id"]] = normalized
        by_alias[normalized["canonical_model_id"]] = normalized
        by_alias[normalized["model_id"]] = normalized
        for alias in normalized.get("aliases", []):
            by_alias[alias] = normalized

    return OfficialCatalogIndex(
        generated_at=generated_at,
        taxonomy=payload.get("taxonomy", []),
        items=items,
        by_id=by_id,
        by_alias=by_alias,
    )


def reload_snapshot() -> OfficialCatalogIndex:
    load_snapshot.cache_clear()
    return load_snapshot()


def list_discover_models() -> list[dict[str, Any]]:
    return load_snapshot().items


def list_taxonomy() -> list[dict[str, Any]]:
    return load_snapshot().taxonomy


def find_model(model_id: str) -> dict[str, Any] | None:
    return load_snapshot().by_alias.get(model_id.lower())
