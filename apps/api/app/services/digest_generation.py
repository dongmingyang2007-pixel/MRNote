"""Stub payload generators for the homepage daily/weekly digest.

Spec: ``升级说明-Persona与Digest.md`` §2.4. The full design calls for an
LLM-authored ``insight`` block on daily and a full ``moves`` / ``options``
narrative on weekly. That LLM hop isn't wired yet, so this module
produces a structurally complete payload built entirely from hard facts
we can count locally (pages touched, AI actions run, memories created
in the window).

The layout matches the TypeScript ``DailyDigest`` / ``WeeklyReflection``
types the homepage imports from ``packages/home/digest-mock.ts`` — keep
them in sync when adding fields.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    AIActionLog,
    Membership,
    Memory,
    NotebookPage,
    User,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _window_bounds_for_day(target_day: date) -> tuple[datetime, datetime]:
    """Return the [start, end) UTC datetime range for ``target_day``.

    Uses UTC as the canonical day boundary. Per-user timezone support is
    called out as a follow-up in the task spec — the scheduler assumes
    UTC 08:30 for now so the payload matches that assumption.
    """
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
    """Convert e.g. ``"2026-W17"`` to [Monday 00:00 UTC, next Monday).

    We deliberately accept a small surface: if the input is malformed
    we raise ValueError so callers can surface a 400 instead of silently
    producing an empty payload.
    """
    try:
        year_str, week_str = iso_week.split("-W")
        year = int(year_str)
        week = int(week_str)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"bad iso_week: {iso_week!r}") from exc
    # ``datetime.fromisocalendar`` was added in 3.8 and handles the
    # "week 53" edge case for ISO-8601 properly.
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
    # end is exclusive — subtract one day for the display label
    end_inclusive = end - timedelta(days=1)
    return f"{start.strftime('%b %-d')} - {end_inclusive.strftime('%b %-d')}"


# ---------------------------------------------------------------------------
# Daily
# ---------------------------------------------------------------------------


def generate_daily_digest_payload(
    db: Session,
    user: User,
    *,
    target_day: date | None = None,
) -> dict[str, Any]:
    """Produce the JSON blob stored in ``digest_daily.payload``.

    Shape matches the ``DailyDigest`` TS type in the homepage bundle:
    ``{date, greeting, blocks: [{kind: "catch"|"today"|"insight", ...}]}``.

    The ``insight`` block is a deterministic placeholder until the LLM
    path is wired; see the ``Pending`` title handshake with the frontend.
    """
    if target_day is None:
        target_day = datetime.now(timezone.utc).date()

    start, end = _window_bounds_for_day(target_day - timedelta(days=1))
    workspace_ids = _workspace_ids_for_user(db, user.id)

    pages_yesterday = 0
    ai_actions_yesterday = 0
    memories_yesterday = 0
    if workspace_ids:
        pages_yesterday = (
            db.query(func.count(NotebookPage.id))
            .filter(
                NotebookPage.created_by == user.id,
                NotebookPage.created_at >= start,
                NotebookPage.created_at < end,
            )
            .scalar()
            or 0
        )
        ai_actions_yesterday = (
            db.query(func.count(AIActionLog.id))
            .filter(
                AIActionLog.user_id == user.id,
                AIActionLog.created_at >= start,
                AIActionLog.created_at < end,
            )
            .scalar()
            or 0
        )
        memories_yesterday = (
            db.query(func.count(Memory.id))
            .filter(
                Memory.workspace_id.in_(workspace_ids),
                Memory.created_at >= start,
                Memory.created_at < end,
            )
            .scalar()
            or 0
        )

    catch_items: list[dict[str, Any]] = []
    if pages_yesterday:
        catch_items.append({
            "icon": "note",
            "label": f"{pages_yesterday} page(s) touched yesterday",
            "tag": "notebook",
        })
    if ai_actions_yesterday:
        catch_items.append({
            "icon": "sparkles",
            "label": f"{ai_actions_yesterday} AI action(s) ran",
            "tag": "ai",
        })

    today_items: list[dict[str, Any]] = []
    if memories_yesterday:
        today_items.append({
            "icon": "graph",
            "label": f"{memories_yesterday} new memory node(s) to review",
            "tag": "memory",
        })

    greeting = f"早安，{user.display_name or user.email.split('@')[0]}"

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
                "title": "Pending",
                "body": "Will be generated on next LLM-enabled run.",
            },
        ],
        "_meta": {
            "generator": "stub",
            "persona": user.persona,
            "window": {
                "start": start.isoformat(),
                "end": end.isoformat(),
            },
        },
    }


# ---------------------------------------------------------------------------
# Weekly
# ---------------------------------------------------------------------------


def generate_weekly_reflection_payload(
    db: Session,
    user: User,
    *,
    iso_week: str | None = None,
) -> dict[str, Any]:
    """Produce the JSON blob stored in ``digest_weekly.payload``.

    Shape matches the ``WeeklyReflection`` TS type in the homepage
    bundle: ``{range, headline, stats, moves, ask, options, sparkline}``.
    """
    if iso_week is None:
        iso_week = iso_week_for_date(datetime.now(timezone.utc).date())
    start, end = _iso_week_to_window(iso_week)
    workspace_ids = _workspace_ids_for_user(db, user.id)

    pages_count = 0
    ai_actions_count = 0
    memories_count = 0
    if workspace_ids:
        pages_count = (
            db.query(func.count(NotebookPage.id))
            .filter(
                NotebookPage.created_by == user.id,
                NotebookPage.created_at >= start,
                NotebookPage.created_at < end,
            )
            .scalar()
            or 0
        )
        ai_actions_count = (
            db.query(func.count(AIActionLog.id))
            .filter(
                AIActionLog.user_id == user.id,
                AIActionLog.created_at >= start,
                AIActionLog.created_at < end,
            )
            .scalar()
            or 0
        )
        memories_count = (
            db.query(func.count(Memory.id))
            .filter(
                Memory.workspace_id.in_(workspace_ids),
                Memory.created_at >= start,
                Memory.created_at < end,
            )
            .scalar()
            or 0
        )

    sparkline: list[dict[str, Any]] = []
    for day_offset in range(7):
        day_start = start + timedelta(days=day_offset)
        day_end = day_start + timedelta(days=1)
        if workspace_ids:
            day_actions = (
                db.query(func.count(AIActionLog.id))
                .filter(
                    AIActionLog.user_id == user.id,
                    AIActionLog.created_at >= day_start,
                    AIActionLog.created_at < day_end,
                )
                .scalar()
                or 0
            )
            day_pages = (
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
        "range": iso_week_range_label(iso_week),
        "iso_week": iso_week,
        "headline": "Pending",  # LLM-authored in follow-up.
        "stats": [
            {"k": "pages", "v": str(pages_count)},
            {"k": "ai_actions", "v": str(ai_actions_count)},
            {"k": "memories", "v": str(memories_count)},
            {"k": "window", "v": "7d"},
        ],
        "moves": [],
        "ask": "下周想回到哪一块？",
        "options": [],
        "sparkline": sparkline,
        "_meta": {
            "generator": "stub",
            "persona": user.persona,
            "window": {
                "start": start.isoformat(),
                "end": end.isoformat(),
            },
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
    """Render the weekly payload to a plain-text Markdown snapshot.

    Used by ``POST /digest/weekly/save-as-page`` to produce a
    ``notebook_pages`` row the user can edit like any other page.
    """
    parts: list[str] = []
    range_label = payload.get("range") or payload.get("iso_week") or ""
    parts.append(f"# 本周反思 · {range_label}")
    parts.append("")
    headline = payload.get("headline")
    if headline and headline != "Pending":
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
    """Build a minimal TipTap-compatible JSON doc for the same content.

    NotebookPage stores rich content in ``content_json`` (TipTap format).
    We emit a simple paragraph-only doc here; the user can reshape it
    after the page is opened. Matching the minimal shape notebooks
    accept keeps the homepage path independent of TipTap schema churn.
    """
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
