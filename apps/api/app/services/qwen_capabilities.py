from __future__ import annotations

from app.services.qwen_official_catalog import find_model
from app.services.responses_native_tools import merge_native_tool_names, normalize_native_tool_name


# Verified against Alibaba Cloud Model Studio docs on 2026-03-23:
# - Responses API supported models:
#   https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-responses
# - Deep thinking supported models:
#   https://help.aliyun.com/zh/model-studio/user-guide/qwq
_RESPONSES_API_SUPPORTED_MODELS = {
    "qwen-max",
    "qwen-plus",
    "qwen-flash",
    "qwen-turbo",
    "qwen-long",
    "qwen3-max",
    "qwen3-max-preview",
    "qwen3-max-2026-01-23",
    "qwen3.5-plus",
    "qwen3.5-plus-2026-02-15",
    "qwen3.5-flash",
    "qwen3.5-flash-2026-02-23",
    "qwen-vl-max-latest",
    "qwen-vl-plus-latest",
    "qwen3-coder-plus",
    "qwen3-coder-plus-latest",
    "qwen3-coder-flash",
    "qwen3-coder-flash-latest",
    "qwen-omni-turbo",
}

_DEEP_THINKING_SUPPORTED_MODELS = {
    "qwen-plus",
    "qwen-flash",
    "qwen3.5-flash",
    "qwen3.5-flash-2026-02-23",
    "qwen3.5-plus",
    "qwen3.5-plus-2026-02-15",
    "qwen3-max-preview",
    "qwen3-max-2026-01-23",
    "qwq-plus",
    "qwq-plus-latest",
    "qvq-max",
    "qvq-max-latest",
    "qvq-plus",
    "qvq-plus-latest",
}

# Verified against Alibaba Cloud Model Studio docs on 2026-03-23:
# - Newly-released models page:
#   https://help.aliyun.com/zh/model-studio/newly-released-models
# - Responses API currently supports text + image input, but not video/audio input:
#   https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-responses
_IMAGE_INPUT_SUPPORTED_MODELS = {
    "qwen3.5-flash",
    "qwen3.5-flash-2026-02-23",
    "qwen3.5-plus",
    "qwen3.5-plus-2026-02-15",
}


def _normalized_model_tokens(model_id: str) -> set[str]:
    normalized = model_id.strip().lower()
    if not normalized:
        return set()

    tokens = {normalized}
    official = find_model(normalized)
    if not official:
        return tokens

    for key in ("model_id", "canonical_model_id"):
        value = official.get(key)
        if isinstance(value, str) and value.strip():
            tokens.add(value.strip().lower())
    for alias in official.get("aliases", []):
        if isinstance(alias, str) and alias.strip():
            tokens.add(alias.strip().lower())
    return tokens


def model_supports_responses_api(model_id: str) -> bool:
    return bool(_normalized_model_tokens(model_id) & _RESPONSES_API_SUPPORTED_MODELS)


def model_supports_deep_thinking(model_id: str) -> bool:
    official = find_model(model_id.strip().lower())
    if official:
        category = str(official.get("official_category_key") or "").lower()
        supported_features = {
            str(value).lower()
            for value in official.get("supported_features", [])
        }
        if category == "deep_thinking" or "deep_thinking" in supported_features:
            return True
    return bool(_normalized_model_tokens(model_id) & _DEEP_THINKING_SUPPORTED_MODELS)


def model_supports_native_web_search(model_id: str) -> bool:
    return model_supports_native_responses_tool(model_id, "web_search")


def model_supported_native_responses_tools(model_id: str) -> set[str]:
    if not model_supports_responses_api(model_id):
        return set()
    official = find_model(model_id.strip().lower())
    if not official:
        return set()
    return {
        str(value).lower()
        for value in merge_native_tool_names(
            model_id.strip().lower(),
            official.get("supported_tools", []),
        )
    }


def model_supports_native_responses_tool(model_id: str, tool_name: str) -> bool:
    normalized_tool = normalize_native_tool_name(tool_name)
    return normalized_tool in model_supported_native_responses_tools(model_id)


def model_supports_image_input(model_id: str) -> bool:
    official = find_model(model_id.strip().lower())
    if official:
        input_modalities = {
            str(value).lower()
            for value in official.get("input_modalities", [])
        }
        if "image" in input_modalities:
            return True
    return bool(_normalized_model_tokens(model_id) & _IMAGE_INPUT_SUPPORTED_MODELS)
