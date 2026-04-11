from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
import math
from typing import Any, Literal

from app.core.config import settings
from app.services.dashscope_client import ChatCompletionResult, UpstreamServiceError, chat_completion_detailed
from app.services.dashscope_http import DASHSCOPE_RERANK_URL, dashscope_headers, get_client

logger = logging.getLogger(__name__)

ToolCategory = Literal["function", "native"]
FailureMode = Literal["bypass", "error"]

_REWRITE_SYSTEM_PROMPT = (
    "You rewrite the user's latest request into a short standalone query for tool selection. "
    "Preserve the real intent and make implicit tool needs explicit, such as latest/current "
    "information, webpage extraction, text-to-image search, reverse image search, code execution, "
    "project memory lookup, or document/file lookup. Return compact JSON only: "
    '{"query":"..."}'
)


@dataclass(slots=True)
class ToolSelectionCandidate:
    key: str
    tool_name: str
    category: ToolCategory
    description: str
    definition: dict[str, Any]
    dependencies: tuple[str, ...] = ()


@dataclass(slots=True)
class ToolSelectionConfig:
    enabled: bool = settings.ai_gateway_tool_selection_enabled
    trigger_tool_count: int = settings.ai_gateway_tool_selection_trigger_tool_count
    top_n: int = settings.ai_gateway_tool_selection_top_n
    top_k_percent: int = settings.ai_gateway_tool_selection_top_k_percent
    score_threshold: float = settings.ai_gateway_tool_selection_score_threshold
    failure_mode: FailureMode = "bypass"
    query_rewrite_enabled: bool = settings.ai_gateway_tool_selection_query_rewrite_enabled
    query_rewrite_turn_threshold: int = settings.ai_gateway_tool_selection_query_rewrite_turn_threshold
    query_rewrite_model: str = settings.ai_gateway_tool_selection_query_rewrite_model
    rerank_model: str = settings.dashscope_rerank_model


@dataclass(slots=True)
class ToolSelectionTrace:
    source: str
    candidate_count: int
    selected_keys: list[str]
    selected_tool_names: list[str]
    applied: bool
    query: str
    rewritten_query: str | None = None
    used_query_rewrite: bool = False
    rerank_model: str | None = None
    top_n: int | None = None
    top_k_percent: int | None = None
    score_threshold: float | None = None
    required_tool_names: list[str] = field(default_factory=list)
    selected_scores: list[dict[str, Any]] = field(default_factory=list)
    failure_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "source": self.source,
            "candidate_count": self.candidate_count,
            "selected_keys": list(self.selected_keys),
            "selected_tool_names": list(self.selected_tool_names),
            "applied": self.applied,
            "query": self.query,
            "used_query_rewrite": self.used_query_rewrite,
            "required_tool_names": list(self.required_tool_names),
            "selected_scores": list(self.selected_scores),
        }
        if self.rewritten_query:
            payload["rewritten_query"] = self.rewritten_query
        if self.rerank_model:
            payload["rerank_model"] = self.rerank_model
        if self.top_n is not None:
            payload["top_n"] = self.top_n
        if self.top_k_percent is not None:
            payload["top_k_percent"] = self.top_k_percent
        if self.score_threshold is not None:
            payload["score_threshold"] = self.score_threshold
        if self.failure_reason:
            payload["failure_reason"] = self.failure_reason
        return payload


@dataclass(slots=True)
class ToolSelectionResult:
    candidates: list[ToolSelectionCandidate]
    trace: ToolSelectionTrace


@dataclass(slots=True)
class _CandidateScore:
    key: str
    score: float


def load_tool_selection_config(llm_config_json: dict[str, object]) -> ToolSelectionConfig:
    raw = llm_config_json.get("ai_gateway_tool_selection")
    if not isinstance(raw, dict):
        raw = llm_config_json.get("tool_selection")
    payload = raw if isinstance(raw, dict) else {}

    failure_mode = str(payload.get("failure_mode") or settings.ai_gateway_tool_selection_failure_mode).strip().lower()
    if failure_mode not in {"bypass", "error"}:
        failure_mode = "bypass"

    def _bool(name: str, default: bool) -> bool:
        value = payload.get(name, default)
        return value if isinstance(value, bool) else default

    def _int(name: str, default: int) -> int:
        value = payload.get(name, default)
        return value if isinstance(value, int) else default

    def _float(name: str, default: float) -> float:
        value = payload.get(name, default)
        if isinstance(value, (int, float)):
            return float(value)
        return default

    def _str(name: str, default: str) -> str:
        value = payload.get(name, default)
        return value.strip() if isinstance(value, str) and value.strip() else default

    return ToolSelectionConfig(
        enabled=_bool("enabled", settings.ai_gateway_tool_selection_enabled),
        trigger_tool_count=max(1, _int("trigger_tool_count", settings.ai_gateway_tool_selection_trigger_tool_count)),
        top_n=max(1, _int("top_n", settings.ai_gateway_tool_selection_top_n)),
        top_k_percent=max(1, min(100, _int("top_k_percent", settings.ai_gateway_tool_selection_top_k_percent))),
        score_threshold=max(0.0, _float("score_threshold", settings.ai_gateway_tool_selection_score_threshold)),
        failure_mode=failure_mode,
        query_rewrite_enabled=_bool(
            "query_rewrite_enabled",
            settings.ai_gateway_tool_selection_query_rewrite_enabled,
        ),
        query_rewrite_turn_threshold=max(
            1,
            _int(
                "query_rewrite_turn_threshold",
                settings.ai_gateway_tool_selection_query_rewrite_turn_threshold,
            ),
        ),
        query_rewrite_model=_str(
            "query_rewrite_model",
            settings.ai_gateway_tool_selection_query_rewrite_model,
        ),
        rerank_model=_str("rerank_model", settings.dashscope_rerank_model),
    )


def _extract_rewritten_query(content: str) -> str | None:
    normalized = content.strip()
    if not normalized:
        return None
    try:
        payload = json.loads(normalized)
    except json.JSONDecodeError:
        start = normalized.find("{")
        end = normalized.rfind("}")
        if start == -1 or end <= start:
            return normalized
        try:
            payload = json.loads(normalized[start : end + 1])
        except json.JSONDecodeError:
            return normalized
    if isinstance(payload, dict):
        query = payload.get("query")
        if isinstance(query, str) and query.strip():
            return query.strip()
    return normalized


async def _rewrite_query_for_tool_selection(
    *,
    user_message: str,
    recent_messages: list[dict[str, str]],
    config: ToolSelectionConfig,
) -> str | None:
    recent_user_turns = sum(1 for message in recent_messages if str(message.get("role") or "").lower() == "user")
    if recent_user_turns < config.query_rewrite_turn_threshold:
        return None

    rewrite_messages: list[dict[str, str]] = [{"role": "system", "content": _REWRITE_SYSTEM_PROMPT}]
    context_slice = recent_messages[-6:]
    for message in context_slice:
        role = str(message.get("role") or "").lower()
        content = str(message.get("content") or "").strip()
        if role not in {"user", "assistant"} or not content:
            continue
        rewrite_messages.append({"role": role, "content": content})
    rewrite_messages.append(
        {
            "role": "user",
            "content": f"Latest user request:\n{user_message.strip()}\n\nReturn JSON only.",
        }
    )

    result: ChatCompletionResult = await chat_completion_detailed(
        rewrite_messages,
        model=config.query_rewrite_model,
        temperature=0.0,
        max_tokens=160,
        enable_thinking=False,
        enable_search=False,
    )
    rewritten = _extract_rewritten_query(result.content)
    if not rewritten or rewritten == user_message.strip():
        return None
    return rewritten


async def _rerank_candidate_scores(
    *,
    query: str,
    candidates: list[ToolSelectionCandidate],
    config: ToolSelectionConfig,
) -> list[_CandidateScore]:
    client = get_client()
    payload = {
        "model": config.rerank_model,
        "input": {
            "query": query,
            "documents": [candidate.description for candidate in candidates],
        },
        "parameters": {
            "return_documents": False,
            "top_n": len(candidates),
        },
    }
    response = await client.post(
        DASHSCOPE_RERANK_URL,
        headers=dashscope_headers(),
        json=payload,
    )
    try:
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        message = response.text
        try:
            payload_json = response.json()
            if isinstance(payload_json, dict):
                message = str(payload_json.get("message") or payload_json.get("error") or message)
        except ValueError:
            pass
        raise UpstreamServiceError(f"AI Gateway tool-selection rerank failed: {message}") from exc

    payload_json = response.json()
    raw_results = None
    if isinstance(payload_json, dict):
        output = payload_json.get("output")
        if isinstance(output, dict):
            raw_results = output.get("results")
        if raw_results is None:
            raw_results = payload_json.get("results")
    if not isinstance(raw_results, list):
        return []

    scores_by_index: dict[int, float] = {}
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        index = item.get("index")
        score = item.get("relevance_score")
        if isinstance(index, int) and isinstance(score, (int, float)):
            scores_by_index[index] = float(score)

    scored: list[_CandidateScore] = []
    for index, candidate in enumerate(candidates):
        scored.append(_CandidateScore(key=candidate.key, score=scores_by_index.get(index, 0.0)))
    scored.sort(key=lambda item: item.score, reverse=True)
    return scored


def _selection_limit(candidate_count: int, config: ToolSelectionConfig) -> int:
    limits: list[int] = []
    if config.top_n > 0:
        limits.append(min(candidate_count, config.top_n))
    if config.top_k_percent > 0:
        limits.append(max(1, math.ceil(candidate_count * config.top_k_percent / 100)))
    if not limits:
        return candidate_count
    return max(1, min(limits))


def _expand_dependencies(
    *,
    selected_keys: set[str],
    candidates: list[ToolSelectionCandidate],
    required_tool_names: set[str],
) -> set[str]:
    tool_name_to_keys: dict[str, list[str]] = {}
    dependencies_by_key: dict[str, tuple[str, ...]] = {}
    for candidate in candidates:
        tool_name_to_keys.setdefault(candidate.tool_name, []).append(candidate.key)
        dependencies_by_key[candidate.key] = candidate.dependencies

    for required_name in required_tool_names:
        for key in tool_name_to_keys.get(required_name, []):
            selected_keys.add(key)

    changed = True
    while changed:
        changed = False
        for key in list(selected_keys):
            for dependency_name in dependencies_by_key.get(key, ()):
                for dependency_key in tool_name_to_keys.get(dependency_name, []):
                    if dependency_key not in selected_keys:
                        selected_keys.add(dependency_key)
                        changed = True
    return selected_keys


async def select_tools_with_ai_gateway_prefilter(
    *,
    user_message: str,
    recent_messages: list[dict[str, str]],
    candidates: list[ToolSelectionCandidate],
    llm_config_json: dict[str, object],
    required_tool_names: set[str] | None = None,
) -> ToolSelectionResult:
    config = load_tool_selection_config(llm_config_json)
    selected_all = list(candidates)
    required = {name.strip() for name in (required_tool_names or set()) if isinstance(name, str) and name.strip()}

    if not config.enabled:
        return ToolSelectionResult(
            candidates=selected_all,
            trace=ToolSelectionTrace(
                source="ai_gateway_disabled",
                candidate_count=len(candidates),
                selected_keys=[candidate.key for candidate in selected_all],
                selected_tool_names=[candidate.tool_name for candidate in selected_all],
                applied=False,
                query=user_message.strip(),
                required_tool_names=sorted(required),
            ),
        )

    if len(candidates) < config.trigger_tool_count:
        return ToolSelectionResult(
            candidates=selected_all,
            trace=ToolSelectionTrace(
                source="ai_gateway_below_threshold",
                candidate_count=len(candidates),
                selected_keys=[candidate.key for candidate in selected_all],
                selected_tool_names=[candidate.tool_name for candidate in selected_all],
                applied=False,
                query=user_message.strip(),
                required_tool_names=sorted(required),
            ),
        )

    query = user_message.strip()
    rewritten_query: str | None = None
    try:
        if config.query_rewrite_enabled:
            rewritten_query = await _rewrite_query_for_tool_selection(
                user_message=user_message,
                recent_messages=recent_messages,
                config=config,
            )
        effective_query = rewritten_query or query
        scored = await _rerank_candidate_scores(
            query=effective_query,
            candidates=candidates,
            config=config,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("AI Gateway-style tool prefilter failed: %s", exc)
        if config.failure_mode == "error":
            raise
        return ToolSelectionResult(
            candidates=selected_all,
            trace=ToolSelectionTrace(
                source="ai_gateway_bypass",
                candidate_count=len(candidates),
                selected_keys=[candidate.key for candidate in selected_all],
                selected_tool_names=[candidate.tool_name for candidate in selected_all],
                applied=False,
                query=query,
                rewritten_query=rewritten_query,
                used_query_rewrite=rewritten_query is not None,
                rerank_model=config.rerank_model,
                top_n=config.top_n,
                top_k_percent=config.top_k_percent,
                score_threshold=config.score_threshold,
                required_tool_names=sorted(required),
                failure_reason=str(exc),
            ),
        )

    limit = _selection_limit(len(candidates), config)
    filtered_scores = [
        item
        for item in scored
        if item.score >= config.score_threshold
    ][:limit]
    selected_key_set = {item.key for item in filtered_scores}
    selected_key_set = _expand_dependencies(
        selected_keys=selected_key_set,
        candidates=candidates,
        required_tool_names=required,
    )

    ordered_selected = [
        candidate
        for candidate in candidates
        if candidate.key in selected_key_set
    ]
    selected_score_map = {item.key: item.score for item in scored}
    trace = ToolSelectionTrace(
        source="ai_gateway_prefilter",
        candidate_count=len(candidates),
        selected_keys=[candidate.key for candidate in ordered_selected],
        selected_tool_names=[candidate.tool_name for candidate in ordered_selected],
        applied=True,
        query=query,
        rewritten_query=rewritten_query,
        used_query_rewrite=rewritten_query is not None,
        rerank_model=config.rerank_model,
        top_n=config.top_n,
        top_k_percent=config.top_k_percent,
        score_threshold=config.score_threshold,
        required_tool_names=sorted(required),
        selected_scores=[
            {
                "key": candidate.key,
                "tool_name": candidate.tool_name,
                "score": round(float(selected_score_map.get(candidate.key, 0.0)), 4),
            }
            for candidate in ordered_selected[:8]
        ],
    )
    # Preserve empty selection if rerank truly rejected all tools and there were no required/dependency additions.
    if not ordered_selected:
        trace.source = "ai_gateway_prefilter_empty"
    return ToolSelectionResult(candidates=ordered_selected, trace=trace)
