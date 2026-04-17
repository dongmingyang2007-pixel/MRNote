# ruff: noqa: E402
import asyncio
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ["ENV"] = "test"

import pytest
from unittest.mock import AsyncMock, patch

from app.services.proactive_generator import generate_digest_content


FAKE_DAILY = """
{"summary_md": "hi", "next_actions": [{"page_id":"p1","title":"T","hint":"do it"}]}
""".strip()

FAKE_WEEKLY = """
{"summary_md":"week","learning_recap_md":"lr","blockers_md":"bl"}
""".strip()

FAKE_DEVIATION_ONE = """
{"drifts":[{"goal_memory_id":"g1","drift_reason_md":"…","confidence":0.7}]}
""".strip()

FAKE_DEVIATION_EMPTY = """
{"drifts":[]}
""".strip()


def test_daily_generator_parses_content() -> None:
    mats = {
        "action_counts": {"selection.rewrite": 3},
        "action_samples": [{"output_summary": "..."}],
        "page_edits": [],
        "reconfirm_items": [],
    }
    with patch(
        "app.services.proactive_generator._run_llm_json",
        new=AsyncMock(return_value=FAKE_DAILY),
    ):
        content = asyncio.run(generate_digest_content(
            kind="daily_digest", materials=mats, project_name="P"
        ))
    assert content["summary_md"] == "hi"
    assert content["next_actions"][0]["page_id"] == "p1"
    # reconfirm_items preserved from materials (rule-based, not LLM)
    assert content["reconfirm_items"] == []


def test_weekly_generator_parses_content() -> None:
    mats = {
        "action_counts": {},
        "action_samples": [],
        "page_edits": [],
        "study_stats": {"cards_reviewed": 10, "lapse_count": 1, "confusions_logged": 0},
        "blocker_tasks": [],
    }
    with patch(
        "app.services.proactive_generator._run_llm_json",
        new=AsyncMock(return_value=FAKE_WEEKLY),
    ):
        content = asyncio.run(generate_digest_content(
            kind="weekly_reflection", materials=mats, project_name="P"
        ))
    assert content["summary_md"] == "week"
    assert content["stats"]["cards_reviewed"] == 10


def test_deviation_generator_returns_list_of_drifts() -> None:
    mats = {
        "goals": [{"memory_id": "g1", "content": "ship MVP", "importance": 0.8}],
        "activity_summary": "unrelated stuff",
    }
    with patch(
        "app.services.proactive_generator._run_llm_json",
        new=AsyncMock(return_value=FAKE_DEVIATION_ONE),
    ):
        content = asyncio.run(generate_digest_content(
            kind="deviation_reminder", materials=mats, project_name="P"
        ))
    assert content["drifts"][0]["goal_memory_id"] == "g1"


def test_bad_llm_output_raises() -> None:
    from app.core.errors import ApiError
    mats = {"goals": [], "activity_summary": ""}
    with patch(
        "app.services.proactive_generator._run_llm_json",
        new=AsyncMock(return_value="not json"),
    ):
        with pytest.raises(ApiError) as exc:
            asyncio.run(generate_digest_content(
                kind="daily_digest", materials={"action_counts":{},"action_samples":[],"page_edits":[],"reconfirm_items":[]},
                project_name="P",
            ))
    assert exc.value.code == "llm_bad_output"


def test_deviation_empty_drifts_is_valid() -> None:
    """LLM returning zero drifts is a valid outcome (nothing is drifting)."""
    mats = {
        "goals": [{"memory_id": "g1", "content": "ship MVP", "importance": 0.8}],
        "activity_summary": "on track",
    }
    with patch(
        "app.services.proactive_generator._run_llm_json",
        new=AsyncMock(return_value=FAKE_DEVIATION_EMPTY),
    ):
        content = asyncio.run(generate_digest_content(
            kind="deviation_reminder", materials=mats, project_name="P"
        ))
    assert content["drifts"] == []
