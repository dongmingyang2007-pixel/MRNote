from __future__ import annotations

from typing import Any


RESPONSES_NATIVE_TOOL_ALIASES: dict[str, str] = {
    "t2i_search": "web_search_image",
    "i2i_search": "image_search",
}

RESPONSES_NATIVE_TOOL_FAMILY_OVERRIDES: dict[str, set[str]] = {
    # Verified against Alibaba Cloud Model Studio Responses API docs on 2026-04-01:
    # - web_search_image
    # - image_search
    # - web_extractor
    # - qwen-code-interpreter
    # - qwen-api-via-openai-responses (file_search / mcp)
    "qwen3.5-flash": {
        "code_interpreter",
        "file_search",
        "function_calling",
        "image_search",
        "mcp",
        "web_extractor",
        "web_search",
        "web_search_image",
    },
    "qwen3.5-plus": {
        "code_interpreter",
        "file_search",
        "function_calling",
        "image_search",
        "mcp",
        "web_extractor",
        "web_search",
        "web_search_image",
    },
    "qwen3-max": {
        "code_interpreter",
        "function_calling",
        "web_extractor",
        "web_search",
    },
}

RESPONSES_NATIVE_TOOL_MODEL_FAMILY: dict[str, str] = {
    "qwen3.5-flash": "qwen3.5-flash",
    "qwen3.5-flash-2026-02-23": "qwen3.5-flash",
    "qwen3.5-plus": "qwen3.5-plus",
    "qwen3.5-plus-2026-02-15": "qwen3.5-plus",
    "qwen3-max": "qwen3-max",
    "qwen3-max-preview": "qwen3-max",
    "qwen3-max-2026-01-23": "qwen3-max",
}

CONFIG_REQUIRED_NATIVE_TOOLS = {"file_search", "mcp"}
THINKING_REQUIRED_NATIVE_TOOLS_BY_FAMILY: dict[str, set[str]] = {
    "qwen3.5-flash": {"code_interpreter", "web_extractor"},
    "qwen3.5-plus": {"code_interpreter", "web_extractor"},
    "qwen3-max": {"code_interpreter", "web_extractor"},
}


def normalize_native_tool_name(name: str) -> str:
    normalized = name.strip().lower()
    return RESPONSES_NATIVE_TOOL_ALIASES.get(normalized, normalized)


def native_tool_family_for_model(model_id: str) -> str | None:
    normalized = model_id.strip().lower()
    if not normalized:
        return None
    return RESPONSES_NATIVE_TOOL_MODEL_FAMILY.get(normalized, normalized)


def native_tool_overrides_for_model(model_id: str) -> set[str]:
    family = native_tool_family_for_model(model_id)
    if not family:
        return set()
    return {
        normalize_native_tool_name(tool_name)
        for tool_name in RESPONSES_NATIVE_TOOL_FAMILY_OVERRIDES.get(family, set())
    }


def merge_native_tool_names(model_id: str, existing: list[str] | set[str] | tuple[str, ...]) -> list[str]:
    merged = {
        normalize_native_tool_name(str(tool_name))
        for tool_name in existing
        if isinstance(tool_name, str) and tool_name.strip()
    }
    merged.update(native_tool_overrides_for_model(model_id))
    return sorted(merged)


def native_tool_requires_config(tool_name: str) -> bool:
    return normalize_native_tool_name(tool_name) in CONFIG_REQUIRED_NATIVE_TOOLS


def native_tool_requires_thinking(tool_name: str, model_id: str) -> bool:
    normalized_tool = normalize_native_tool_name(tool_name)
    family = native_tool_family_for_model(model_id)
    if not family:
        return False
    return normalized_tool in THINKING_REQUIRED_NATIVE_TOOLS_BY_FAMILY.get(family, set())


def build_native_tool_definition(
    tool_name: str,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_tool = normalize_native_tool_name(tool_name)
    payload = dict(config or {})
    payload["type"] = normalized_tool
    return payload
