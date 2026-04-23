"""Payload generators for the homepage daily/weekly digest.

Spec: ``升级说明-Persona与Digest.md`` §2.4. The base scaffold is the same
as before (catch / today / insight blocks for daily; stats / moves /
options / sparkline for weekly) — the upgrade path drops in a real LLM
hop for the ``insight`` body (daily) and ``headline`` (weekly) and keeps
the ``Pending`` fallback string when DashScope errors out so the beat
schedule never fails closed.

Activity snapshot the LLM sees (all computed locally, no cross-tenant
reads):

* Daily — yesterday's ``AIActionLog`` count grouped by ``action_type``,
  ``NotebookPage`` created/updated counts, recent 7-day trend line,
  today candidates (pages stale in last 2 days, failed AI actions).
* Weekly — 7-day ``NotebookPage`` / ``AIActionLog`` / ``Memory`` totals
  plus a "real moves" list synthesized from completed AI actions.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    AIActionLog,
    Membership,
    Memory,
    NotebookPage,
    User,
)
from app.services import dashscope_client

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


# Fallback string the frontend already knows how to display when LLM work
# fails — keep the handshake stable so the UI doesn't have to branch.
_PENDING_TITLE = "Pending"
_PENDING_BODY = "Will be generated on next LLM-enabled run."
_PENDING_HEADLINE = "Pending"
_LLM_TIMEOUT_SECONDS = 8.0


# ---------------------------------------------------------------------------
# Helpers — window bounds, persona label, membership lookups
# ---------------------------------------------------------------------------


def _window_bounds_for_day(target_day: date) -> tuple[datetime, datetime]:
    """Return the [start, end) UTC datetime range for ``target_day``."""
    start = datetime.combine(target_day, datetime.min.time(), tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return start, end


def _workspace_ids_for_user(db: Session, user_id: str) -> list[str]:
    rows = (
        db.query(Membership.workspace_id)
        .filter(Membership.user_id == user_id)
        .all()
    )
    return [row[0] for row in rows if row[0]]


def _iso_week_to_window(iso_week: str) -> tuple[datetime, datetime]:
    """Convert e.g. ``"2026-W17"`` to [Monday 00:00 UTC, next Monday)."""
    try:
        year_str, week_str = iso_week.split("-W")
        year = int(year_str)
        week = int(week_str)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"bad iso_week: {iso_week!r}") from exc
    try:
        start_date = datetime.fromisocalendar(year, week, 1)  # Monday
    except ValueError as exc:
        raise ValueError(f"bad iso_week: {iso_week!r}") from exc
    start = start_date.replace(tzinfo=timezone.utc)
    return start, start + timedelta(days=7)


def iso_week_for_date(target_day: date) -> str:
    year, week, _ = target_day.isocalendar()
    return f"{year:04d}-W{week:02d}"


def iso_week_range_label(iso_week: str) -> str:
    start, end = _iso_week_to_window(iso_week)
    end_inclusive = end - timedelta(days=1)
    return f"{start.strftime('%b %-d')} - {end_inclusive.strftime('%b %-d')}"


_PERSONA_LABEL = {
    "student": "学生",
    "researcher": "研究者",
    "pm": "产品/项目",
}


def _persona_label(persona: str | None) -> str:
    if not persona:
        return "通用"
    return _PERSONA_LABEL.get(persona, persona)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_DAILY_INSIGHT_PROMPT = (
    "你是 MRNote 的写作伙伴，为用户写每日 digest 的 insight 段。\n"
    "\n"
    "身份 persona：{persona_label}\n"
    "昨日轨迹（结构化事实）：\n"
    "{yesterday_stats_json}\n"
    "最近 7 天节奏：\n"
    "{trend_summary}\n"
    "今日候选：\n"
    "{today_candidates}\n"
    "\n"
    "请输出一条「观察 + 一个轻建议」，不超过 50 字。"
    "严禁套话（如\"今天加油\"/\"祝好运\"）。必须具体，带清晰观察。\n"
    "只返回 JSON（不要代码围栏、不要额外说明）：{{\"title\": \"...\", \"body\": \"...\"}}"
)

_WEEKLY_HEADLINE_PROMPT = (
    "你是 MRNote 的写作伙伴，为每周反思写 headline。\n"
    "\n"
    "身份 persona：{persona_label}\n"
    "本周硬事实（7 天统计）：\n"
    "{weekly_stats_json}\n"
    "真正推进的事：\n"
    "{moves_list}\n"
    "\n"
    "请输出一条 headline，25 字以内。不要套话。像朋友对你说的那句话。\n"
    "只返回 JSON（不要代码围栏、不要额外说明）：{{\"headline\": \"...\"}}"
)


# ---------------------------------------------------------------------------
# LLM call helpers
# ---------------------------------------------------------------------------


def _extract_json_object(raw: str) -> dict[str, Any] | None:
    """Pull the first JSON object out of a possibly fenced / noisy reply.

    The LLM is asked for pure JSON, but models occasionally wrap in
    ```json``` fences or preface with prose. We try the raw string
    first, then fall back to the substring between the first `{` and
    the last `}` so fenced output still parses.
    """
    text = (raw or "").strip()
    if not text:
        return None
    # Strip common markdown fences.
    if text.startswith("```"):
        # drop first fence line and trailing fence
        parts = text.split("```")
        if len(parts) >= 3:
            text = parts[1]
            if text.startswith("json\n"):
                text = text[5:]
            elif text.startswith("json"):
                text = text[4:]
            text = text.strip()
    candidates = [text]
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        candidates.append(text[start : end + 1])
    for cand in candidates:
        try:
            parsed = json.loads(cand)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


async def _run_chat_with_timeout(prompt: str) -> str | None:
    """Run a one-shot chat completion, bounded by ``_LLM_TIMEOUT_SECONDS``."""
    try:
        return await asyncio.wait_for(
            dashscope_client.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.4,
                max_tokens=256,
            ),
            timeout=_LLM_TIMEOUT_SECONDS,
        )
    except Exception:  # noqa: BLE001 — timeout / upstream / config
        logger.exception("digest LLM call failed")
        return None


def _call_llm_sync(prompt: str) -> dict[str, Any] | None:
    """Run the LLM call from a sync context (Celery worker).

    Returns the parsed JSON dict, or ``None`` on any failure. We never
    raise — the caller falls back to the ``Pending`` placeholder so the
    digest still generates.
    """
    if not settings.dashscope_api_key:
        logger.info("digest LLM skipped — dashscope_api_key empty")
        return None
    try:
        raw = asyncio.run(_run_chat_with_timeout(prompt))
    except RuntimeError:
        # If an event loop is already running (pytest-asyncio etc.) fall
        # back to creating a fresh loop manually.
        loop = asyncio.new_event_loop()
        try:
            raw = loop.run_until_complete(_run_chat_with_timeout(prompt))
        finally:
            loop.close()
    if not raw:
        return None
    return _extract_json_object(raw)


# ---------------------------------------------------------------------------
# Activity collection — pure SQL counts, no LLM
# ---------------------------------------------------------------------------


def _collect_daily_activity(
    db: Session,
    user: User,
    *,
    target_day: date,
    workspace_ids: list[str],
) -> dict[str, Any]:
    """Gather the structured facts the daily prompt and payload both need."""
    yesterday = target_day - timedelta(days=1)
    y_start, y_end = _window_bounds_for_day(yesterday)

    pages_yesterday = 0
    ai_actions_yesterday = 0
    memories_yesterday = 0
    action_type_counts: dict[str, int] = {}
    failed_action_types: list[str] = []
    if workspace_ids:
        pages_yesterday = int(
            db.query(func.count(NotebookPage.id))
            .filter(
                NotebookPage.created_by == user.id,
                NotebookPage.created_at >= y_start,
                NotebookPage.created_at < y_end,
            )
            .scalar()
            or 0
        )
        ai_action_rows = (
            db.query(AIActionLog.action_type, AIActionLog.status)
            .filter(
                AIActionLog.user_id == user.id,
                AIActionLog.created_at >= y_start,
                AIActionLog.created_at < y_end,
            )
            .all()
        )
        ai_actions_yesterday = len(ai_action_rows)
        counter: Counter[str] = Counter()
        for action_type, status in ai_action_rows:
            counter[action_type] += 1
            if status == "failed":
                failed_action_types.append(action_type)
        action_type_counts = dict(counter.most_common())
        memories_yesterday = int(
            db.query(func.count(Memory.id))
            .filter(
                Memory.workspace_id.in_(workspace_ids),
                Memory.created_at >= y_start,
                Memory.created_at < y_end,
            )
            .scalar()
            or 0
        )

    # 7-day trend — total actions per day, oldest→newest.
    trend: list[dict[str, Any]] = []
    for offset in range(7, 0, -1):
        day = target_day - timedelta(days=offset)
        d_start, d_end = _window_bounds_for_day(day)
        if workspace_ids:
            count = int(
                db.query(func.count(AIActionLog.id))
                .filter(
                    AIActionLog.user_id == user.id,
                    AIActionLog.created_at >= d_start,
                    AIActionLog.created_at < d_end,
                )
                .scalar()
                or 0
            )
        else:
            count = 0
        trend.append({"date": day.isoformat(), "actions": count})

    # Today candidates — notebook pages touched in the last 2 days with no
    # activity today + failed action types that look like open loops.
    candidate_pages: list[dict[str, Any]] = []
    if workspace_ids:
        two_days_ago_start = _window_bounds_for_day(target_day - timedelta(days=2))[0]
        today_start = _window_bounds_for_day(target_day)[0]
        rows = (
            db.query(NotebookPage.id, NotebookPage.title, NotebookPage.updated_at)
            .filter(
                NotebookPage.created_by == user.id,
                NotebookPage.updated_at >= two_days_ago_start,
                NotebookPage.updated_at < today_start,
            )
            .order_by(NotebookPage.updated_at.desc())
            .limit(5)
            .all()
        )
        for row in rows:
            candidate_pages.append({
                "title": (row.title or "")[:60],
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            })

    return {
        "pages_yesterday": pages_yesterday,
        "ai_actions_yesterday": ai_actions_yesterday,
        "memories_yesterday": memories_yesterday,
        "action_type_counts": action_type_counts,
        "failed_action_types": failed_action_types,
        "trend": trend,
        "candidate_pages": candidate_pages,
    }


def _collect_weekly_activity(
    db: Session,
    user: User,
    *,
    iso_week: str,
    workspace_ids: list[str],
) -> dict[str, Any]:
    start, end = _iso_week_to_window(iso_week)

    pages_count = 0
    ai_actions_count = 0
    memories_count = 0
    moves: list[str] = []
    sparkline: list[dict[str, Any]] = []

    if workspace_ids:
        pages_count = int(
            db.query(func.count(NotebookPage.id))
            .filter(
                NotebookPage.created_by == user.id,
                NotebookPage.created_at >= start,
                NotebookPage.created_at < end,
            )
            .scalar()
            or 0
        )
        ai_actions_count = int(
            db.query(func.count(AIActionLog.id))
            .filter(
                AIActionLog.user_id == user.id,
                AIActionLog.created_at >= start,
                AIActionLog.created_at < end,
            )
            .scalar()
            or 0
        )
        memories_count = int(
            db.query(func.count(Memory.id))
            .filter(
                Memory.workspace_id.in_(workspace_ids),
                Memory.created_at >= start,
                Memory.created_at < end,
            )
            .scalar()
            or 0
        )
        # "Real moves" — completed action types with a short output summary.
        move_rows = (
            db.query(AIActionLog.action_type, AIActionLog.output_summary)
            .filter(
                AIActionLog.user_id == user.id,
                AIActionLog.status == "completed",
                AIActionLog.created_at >= start,
                AIActionLog.created_at < end,
            )
            .order_by(AIActionLog.created_at.desc())
            .limit(5)
            .all()
        )
        for action_type, summary in move_rows:
            s = (summary or "").strip()
            if s:
                moves.append(f"{action_type}: {s[:80]}")
            else:
                moves.append(action_type)

    for day_offset in range(7):
        day_start = start + timedelta(days=day_offset)
        day_end = day_start + timedelta(days=1)
        if workspace_ids:
            day_actions = int(
                db.query(func.count(AIActionLog.id))
                .filter(
                    AIActionLog.user_id == user.id,
                    AIActionLog.created_at >= day_start,
                    AIActionLog.created_at < day_end,
                )
                .scalar()
                or 0
            )
            day_pages = int(
                db.query(func.count(NotebookPage.id))
                .filter(
                    NotebookPage.created_by == user.id,
                    NotebookPage.created_at >= day_start,
                    NotebookPage.created_at < day_end,
                )
                .scalar()
                or 0
            )
        else:
            day_actions = 0
            day_pages = 0
        sparkline.append({
            "day": day_start.strftime("%a"),
            "value": int(day_actions + day_pages),
        })

    return {
        "pages_count": pages_count,
        "ai_actions_count": ai_actions_count,
        "memories_count": memories_count,
        "moves": moves,
        "sparkline": sparkline,
        "window": {"start": start.isoformat(), "end": end.isoformat()},
    }


# ---------------------------------------------------------------------------
# LLM callers — isolate so tests can monkeypatch
# ---------------------------------------------------------------------------


def _build_daily_insight(
    *,
    persona: str | None,
    activity: dict[str, Any],
) -> dict[str, str]:
    """Return ``{"title", "body"}``. Falls back to the Pending handshake."""
    trend_summary = ", ".join(
        f"{t['date']}:{t['actions']}" for t in activity["trend"]
    )
    candidates = activity["candidate_pages"] or []
    candidate_lines = [
        f"- {c['title']}" for c in candidates if c.get("title")
    ]
    if activity["failed_action_types"]:
        candidate_lines.append(
            "- 昨日失败动作：" + ", ".join(activity["failed_action_types"][:3])
        )
    today_candidates = "\n".join(candidate_lines) or "(none)"

    yesterday_stats = {
        "pages_yesterday": activity["pages_yesterday"],
        "ai_actions_yesterday": activity["ai_actions_yesterday"],
        "memories_yesterday": activity["memories_yesterday"],
        "action_type_counts": activity["action_type_counts"],
    }

    prompt = _DAILY_INSIGHT_PROMPT.format(
        persona_label=_persona_label(persona),
        yesterday_stats_json=json.dumps(yesterday_stats, ensure_ascii=False),
        trend_summary=trend_summary or "(no activity)",
        today_candidates=today_candidates,
    )
    parsed = _call_llm_sync(prompt)
    if parsed is None:
        return {"title": _PENDING_TITLE, "body": _PENDING_BODY}
    title = str(parsed.get("title") or "").strip() or "今日观察"
    body = str(parsed.get("body") or "").strip()
    if not body:
        return {"title": _PENDING_TITLE, "body": _PENDING_BODY}
    # Hard-cap to 120 chars so a chatty model can't blow up the card.
    return {"title": title[:40], "body": body[:120]}


def _build_weekly_headline(
    *,
    persona: str | None,
    activity: dict[str, Any],
) -> str:
    """Return the headline string (or ``Pending`` on failure)."""
    weekly_stats = {
        "pages_count": activity["pages_count"],
        "ai_actions_count": activity["ai_actions_count"],
        "memories_count": activity["memories_count"],
        "window": activity["window"],
    }
    moves = activity["moves"] or []
    moves_text = "\n".join(f"- {m}" for m in moves) or "(no completed moves)"

    prompt = _WEEKLY_HEADLINE_PROMPT.format(
        persona_label=_persona_label(persona),
        weekly_stats_json=json.dumps(weekly_stats, ensure_ascii=False),
        moves_list=moves_text,
    )
    parsed = _call_llm_sync(prompt)
    if parsed is None:
        return _PENDING_HEADLINE
    headline = str(parsed.get("headline") or "").strip()
    if not headline:
        return _PENDING_HEADLINE
    return headline[:60]


# ---------------------------------------------------------------------------
# Public: daily payload
# ---------------------------------------------------------------------------


def generate_daily_digest_payload(
    db: Session,
    user: User,
    *,
    target_day: date | None = None,
) -> dict[str, Any]:
    """Produce the JSON blob stored in ``digest_daily.payload``."""
    if target_day is None:
        target_day = datetime.now(timezone.utc).date()

    workspace_ids = _workspace_ids_for_user(db, user.id)
    activity = _collect_daily_activity(
        db, user, target_day=target_day, workspace_ids=workspace_ids,
    )

    catch_items: list[dict[str, Any]] = []
    if activity["pages_yesterday"]:
        catch_items.append({
            "icon": "note",
            "label": f"{activity['pages_yesterday']} page(s) touched yesterday",
            "tag": "notebook",
        })
    if activity["ai_actions_yesterday"]:
        catch_items.append({
            "icon": "sparkles",
            "label": f"{activity['ai_actions_yesterday']} AI action(s) ran",
            "tag": "ai",
        })

    today_items: list[dict[str, Any]] = []
    if activity["memories_yesterday"]:
        today_items.append({
            "icon": "graph",
            "label": f"{activity['memories_yesterday']} new memory node(s) to review",
            "tag": "memory",
        })
    # Surface stale pages as today candidates.
    for cand in activity["candidate_pages"][:3]:
        title = cand.get("title") or "Untitled"
        today_items.append({
            "icon": "note",
            "label": f"pending: {title}",
            "tag": "notebook",
        })

    insight = _build_daily_insight(persona=user.persona, activity=activity)

    greeting = f"早安，{user.display_name or user.email.split('@')[0]}"
    y_start, y_end = _window_bounds_for_day(target_day - timedelta(days=1))
    return {
        "date": target_day.isoformat(),
        "greeting": greeting,
        "blocks": [
            {
                "kind": "catch",
                "title": "昨日尾巴",
                "items": catch_items,
            },
            {
                "kind": "today",
                "title": "今日值得做的",
                "items": today_items,
            },
            {
                "kind": "insight",
                "title": insight["title"],
                "body": insight["body"],
            },
        ],
        "_meta": {
            "generator": "llm" if insight["body"] != _PENDING_BODY else "fallback",
            "persona": user.persona,
            "window": {
                "start": y_start.isoformat(),
                "end": y_end.isoformat(),
            },
        },
    }


# ---------------------------------------------------------------------------
# Public: weekly payload
# ---------------------------------------------------------------------------


def generate_weekly_reflection_payload(
    db: Session,
    user: User,
    *,
    iso_week: str | None = None,
) -> dict[str, Any]:
    """Produce the JSON blob stored in ``digest_weekly.payload``."""
    if iso_week is None:
        iso_week = iso_week_for_date(datetime.now(timezone.utc).date())
    workspace_ids = _workspace_ids_for_user(db, user.id)
    activity = _collect_weekly_activity(
        db, user, iso_week=iso_week, workspace_ids=workspace_ids,
    )

    headline = _build_weekly_headline(persona=user.persona, activity=activity)

    return {
        "range": iso_week_range_label(iso_week),
        "iso_week": iso_week,
        "headline": headline,
        "stats": [
            {"k": "pages", "v": str(activity["pages_count"])},
            {"k": "ai_actions", "v": str(activity["ai_actions_count"])},
            {"k": "memories", "v": str(activity["memories_count"])},
            {"k": "window", "v": "7d"},
        ],
        "moves": activity["moves"],
        "ask": "下周想回到哪一块？",
        "options": [],
        "sparkline": activity["sparkline"],
        "_meta": {
            "generator": "llm" if headline != _PENDING_HEADLINE else "fallback",
            "persona": user.persona,
            "window": activity["window"],
        },
    }


# ---------------------------------------------------------------------------
# Markdown rendering for "Save as page"
# ---------------------------------------------------------------------------


def render_weekly_reflection_markdown(
    payload: dict[str, Any],
    *,
    pick_option: str | None = None,
) -> str:
    """Render the weekly payload to a plain-text Markdown snapshot."""
    parts: list[str] = []
    range_label = payload.get("range") or payload.get("iso_week") or ""
    parts.append(f"# 本周反思 · {range_label}")
    parts.append("")
    headline = payload.get("headline")
    if headline and headline != _PENDING_HEADLINE:
        parts.append(f"> {headline}")
        parts.append("")
    if pick_option:
        parts.append(f"**下周主线**：{pick_option}")
        parts.append("")
    stats = payload.get("stats") or []
    if stats:
        parts.append("## 指标")
        for stat in stats:
            k = stat.get("k")
            v = stat.get("v")
            trend = stat.get("trend")
            line = f"- {k}: {v}"
            if trend:
                line += f" ({trend})"
            parts.append(line)
        parts.append("")
    moves = payload.get("moves") or []
    if moves:
        parts.append("## 真正推进的")
        for move in moves:
            parts.append(f"- {move}")
        parts.append("")
    options = payload.get("options") or []
    if options:
        parts.append("## 下周候选")
        for opt in options:
            parts.append(f"- {opt}")
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def render_weekly_reflection_tiptap(
    payload: dict[str, Any],
    *,
    pick_option: str | None = None,
) -> dict[str, Any]:
    """Build a minimal TipTap-compatible JSON doc for the same content."""
    markdown = render_weekly_reflection_markdown(payload, pick_option=pick_option)
    paragraphs: list[dict[str, Any]] = []
    for line in markdown.splitlines():
        line = line.rstrip()
        if not line:
            paragraphs.append({"type": "paragraph"})
            continue
        paragraphs.append({
            "type": "paragraph",
            "content": [{"type": "text", "text": line}],
        })
    if not paragraphs:
        paragraphs.append({"type": "paragraph"})
    return {
        "type": "doc",
        "content": paragraphs,
    }
