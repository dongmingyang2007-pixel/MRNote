"""S5 proactive services: LLM prompts + content_json assembly."""

from __future__ import annotations

import json
from typing import Any

from app.core.errors import ApiError
from app.services.dashscope_client import chat_completion


_DAILY_SYSTEM = (
    "你是一个每日摘要生成助手。请用 3-5 句话总结用户过去 24 小时的活动，"
    "然后给出若干具体的下一步动作建议（每个建议指向一个已有的页面）。"
    '必须返回严格的 JSON: {"summary_md":"...", '
    '"next_actions":[{"page_id":"...","title":"...","hint":"..."}]}。'
    "只返回 JSON，不要返回其他内容。"
)

_WEEKLY_SYSTEM = (
    "你是一个每周反思生成助手。请基于用户过去 7 天的活动，产出一段 5-8 句话的总结、"
    "一段学习回顾、以及一段对阻塞点的复盘。"
    '必须返回严格的 JSON: {"summary_md":"...","learning_recap_md":"...","blockers_md":"..."}。'
    "只返回 JSON，不要返回其他内容。"
)

_DEVIATION_SYSTEM = (
    "你负责判断用户当前的行动是否偏离了其明确表达过的目标。"
    "给定目标列表和最近的活动概况，输出 0-3 条偏离报告；如果没有偏离，返回空列表也是合法的。"
    '必须返回严格的 JSON: {"drifts":[{"goal_memory_id":"...","drift_reason_md":"...","confidence":0.0-1.0}]}。'
    "confidence 取值范围 0.0-1.0。只返回 JSON，不要返回其他内容。"
)


async def _run_llm_json(system: str, user_prompt: str) -> str:
    """Seam the tests monkey-patch. Calls the non-streaming LLM and
    returns the raw text (expected to be JSON)."""
    return await chat_completion(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
        max_tokens=2048,
    )


def _build_daily_user_prompt(materials: dict[str, Any], project_name: str) -> str:
    return (
        f"Project: {project_name}\n\n"
        f"Action counts (last 24h): {json.dumps(materials.get('action_counts', {}), ensure_ascii=False)}\n"
        f"Action samples: {json.dumps(materials.get('action_samples', [])[:5], ensure_ascii=False)}\n"
        f"Pages edited: {json.dumps(materials.get('page_edits', []), ensure_ascii=False)}\n"
    )


def _build_weekly_user_prompt(materials: dict[str, Any], project_name: str) -> str:
    return (
        f"Project: {project_name}\n\n"
        f"Action counts (last 7d): {json.dumps(materials.get('action_counts', {}), ensure_ascii=False)}\n"
        f"Action samples: {json.dumps(materials.get('action_samples', [])[:10], ensure_ascii=False)}\n"
        f"Pages edited: {json.dumps(materials.get('page_edits', []), ensure_ascii=False)}\n"
        f"Study stats: {json.dumps(materials.get('study_stats', {}), ensure_ascii=False)}\n"
        f"Blocker tasks: {json.dumps(materials.get('blocker_tasks', []), ensure_ascii=False)}\n"
    )


def _build_deviation_user_prompt(materials: dict[str, Any], project_name: str) -> str:
    return (
        f"Project: {project_name}\n\n"
        f"Goals:\n{json.dumps(materials.get('goals', []), ensure_ascii=False)}\n\n"
        f"Recent activity summary:\n{materials.get('activity_summary', '')}\n"
    )


async def generate_digest_content(
    *,
    kind: str,
    materials: dict[str, Any],
    project_name: str,
) -> dict[str, Any]:
    """Dispatch to the right prompt + LLM call, return content_json.

    Raises ApiError("llm_bad_output") on parse failure or missing
    required fields.
    """
    if kind == "daily_digest":
        system, user = _DAILY_SYSTEM, _build_daily_user_prompt(materials, project_name)
    elif kind == "weekly_reflection":
        system, user = _WEEKLY_SYSTEM, _build_weekly_user_prompt(materials, project_name)
    elif kind == "deviation_reminder":
        system, user = _DEVIATION_SYSTEM, _build_deviation_user_prompt(materials, project_name)
    else:
        raise ApiError("invalid_input", f"Unknown kind {kind}", status_code=400)

    raw = await _run_llm_json(system, user)
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("top-level must be object")
    except (json.JSONDecodeError, ValueError, TypeError):
        raise ApiError("llm_bad_output", "LLM returned invalid JSON", status_code=422)

    if kind == "daily_digest":
        if not isinstance(parsed.get("summary_md"), str):
            raise ApiError("llm_bad_output", "summary_md missing", status_code=422)
        parsed.setdefault("next_actions", [])
        # Pass through rule-based reconfirm items + sources (not LLM).
        parsed["reconfirm_items"] = materials.get("reconfirm_items", [])
        parsed["sources"] = {
            "action_log_ids": [s.get("action_log_id") for s in materials.get("action_samples", [])],
            "page_ids": [p.get("page_id") for p in materials.get("page_edits", [])],
        }
    elif kind == "weekly_reflection":
        for key in ("summary_md", "learning_recap_md", "blockers_md"):
            if not isinstance(parsed.get(key), str):
                raise ApiError("llm_bad_output", f"{key} missing", status_code=422)
        parsed["stats"] = materials.get("study_stats", {}) | {
            "action_count": sum(materials.get("action_counts", {}).values()),
            "pages_edited": len(materials.get("page_edits", [])),
        }
        parsed["sources"] = {
            "action_log_ids": [s.get("action_log_id") for s in materials.get("action_samples", [])],
            "page_ids": [p.get("page_id") for p in materials.get("page_edits", [])],
        }
    elif kind == "deviation_reminder":
        drifts = parsed.get("drifts")
        if not isinstance(drifts, list):
            raise ApiError("llm_bad_output", "drifts must be list", status_code=422)
        parsed["drifts"] = drifts[:3]

    return parsed
