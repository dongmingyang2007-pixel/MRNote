"""S5 proactive services: LLM prompts + content_json assembly."""

from __future__ import annotations

import json
from typing import Any

from app.core.errors import ApiError
from app.services.dashscope_client import chat_completion


_DAILY_SYSTEM = (
    "You are a daily digest generator. Summarize the user's last-24h "
    "activity in 3-5 sentences, then suggest concrete next actions "
    'pointing at existing pages. Return strict JSON: {"summary_md":"...", '
    '"next_actions":[{"page_id":"...","title":"...","hint":"..."}]}.'
)

_WEEKLY_SYSTEM = (
    "You are a weekly reflection generator. Produce a 5-8 sentence "
    "summary, a learning recap, and a blockers retrospective. Return "
    'strict JSON: {"summary_md":"...","learning_recap_md":"...","blockers_md":"..."}.'
)

_DEVIATION_SYSTEM = (
    "You judge whether stated goals are drifting. Given goals and recent "
    "activity, return 0-3 drift reports. Strict JSON: "
    '{"drifts":[{"goal_memory_id":"...","drift_reason_md":"...","confidence":0.0-1.0}]}. '
    "Empty drifts list is valid if nothing is drifting. Only return JSON."
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
    except Exception:
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
