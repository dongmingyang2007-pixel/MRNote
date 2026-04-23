"""HTML digest email rendering + dispatch.

Spec: DIGEST upgrade — every daily digest / weekly reflection that lands
in ``digest_daily`` / ``digest_weekly`` can also be mailed to the user's
inbox. Opt-out via ``users.digest_email_enabled``.

Design notes
------------
* Inline CSS only. Gmail / Outlook strip <style> blocks and external
  stylesheets; keeping everything in ``style=""`` attributes is the
  pragmatic path to a readable card in both web and mobile clients.
* Palette matches the homepage cards (teal ``#0D9488`` primary, orange
  ``#F59E0B`` accent, slate ``#0F172A`` body text) so the mail feels
  like a native extension of the app.
* Every link back into the app is built from ``settings.site_url`` —
  we never trust the incoming Host header for mail templates.
* Payload shape mirrors ``services.digest_generation.generate_*_payload``;
  unexpected / missing keys degrade silently to empty blocks so the mail
  never errors out on a schema drift.
"""

from __future__ import annotations

import html
import logging
from typing import Any

from app.core.config import settings
from app.models import User
from app.services.email import send_html_email

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Palette — keep in one place so restyles don't hunt across the template
# ---------------------------------------------------------------------------


_TEAL = "#0D9488"
_ORANGE = "#F59E0B"
_SLATE_900 = "#0F172A"
_SLATE_700 = "#334155"
_SLATE_500 = "#64748B"
_SLATE_200 = "#E2E8F0"
_SLATE_50 = "#F8FAFC"
_WHITE = "#FFFFFF"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _esc(value: Any) -> str:
    """Shorthand HTML-escape that coerces to str first."""
    return html.escape(str(value) if value is not None else "")


def _settings_url() -> str:
    base = settings.site_url.rstrip("/") if settings.site_url else "http://localhost:3000"
    return f"{base}/app/settings"


def _footer_html() -> str:
    return (
        f'<tr><td style="padding:24px 32px 32px 32px;border-top:1px solid {_SLATE_200};'
        f'color:{_SLATE_500};font-size:12px;line-height:1.6;">'
        f'<p style="margin:0 0 8px 0;">如果你没有要求这些邮件，可以随时在设置里关闭。</p>'
        f'<p style="margin:0;">'
        f'<a href="{_esc(_settings_url())}" style="color:{_TEAL};text-decoration:none;">'
        f'在设置里关闭邮件</a>'
        f'</p>'
        f'</td></tr>'
    )


def _header_html(subtitle: str) -> str:
    return (
        f'<tr><td style="padding:32px 32px 16px 32px;">'
        f'<div style="font-size:12px;letter-spacing:2px;text-transform:uppercase;'
        f'color:{_TEAL};font-weight:600;">MRNOTE</div>'
        f'<div style="margin-top:6px;font-size:14px;color:{_SLATE_500};">'
        f'{_esc(subtitle)}'
        f'</div>'
        f'</td></tr>'
    )


def _items_html(items: list[dict[str, Any]]) -> str:
    if not items:
        return (
            f'<div style="color:{_SLATE_500};font-size:14px;font-style:italic;">'
            f'(这里还空着)'
            f'</div>'
        )
    rows = []
    for item in items:
        label = _esc(item.get("label") or "")
        tag = _esc(item.get("tag") or "")
        rows.append(
            f'<div style="display:block;padding:10px 14px;margin-bottom:6px;'
            f'background:{_SLATE_50};border-radius:8px;color:{_SLATE_700};'
            f'font-size:14px;line-height:1.5;">'
            f'<span style="display:inline-block;font-size:11px;'
            f'color:{_ORANGE};font-weight:600;text-transform:uppercase;'
            f'letter-spacing:1px;margin-right:8px;">{tag}</span>'
            f'{label}'
            f'</div>'
        )
    return "".join(rows)


def _block_html(title: str, inner_html: str) -> str:
    return (
        f'<tr><td style="padding:8px 32px 16px 32px;">'
        f'<h2 style="margin:0 0 10px 0;font-size:16px;color:{_SLATE_900};'
        f'font-weight:600;">{_esc(title)}</h2>'
        f'{inner_html}'
        f'</td></tr>'
    )


# ---------------------------------------------------------------------------
# Daily HTML
# ---------------------------------------------------------------------------


def render_daily_digest_html(user: User, payload: dict[str, Any]) -> str:
    """Render the daily-digest payload into an inline-styled HTML body."""
    date_str = _esc(payload.get("date") or "")
    greeting = _esc(
        payload.get("greeting")
        or f"早安，{user.display_name or (user.email or '').split('@')[0]}"
    )
    blocks = payload.get("blocks") or []

    content_rows: list[str] = [
        _header_html(f"Morning digest · {date_str}"),
        (
            f'<tr><td style="padding:0 32px 20px 32px;">'
            f'<h1 style="margin:0;font-size:22px;color:{_SLATE_900};'
            f'font-weight:700;">{greeting}</h1>'
            f'</td></tr>'
        ),
    ]

    for block in blocks:
        if not isinstance(block, dict):
            continue
        kind = block.get("kind")
        title = block.get("title") or ""
        if kind == "insight":
            body = _esc(block.get("body") or "")
            content_rows.append(
                f'<tr><td style="padding:8px 32px 24px 32px;">'
                f'<div style="padding:18px 20px;border-left:4px solid {_TEAL};'
                f'background:{_SLATE_50};border-radius:8px;">'
                f'<div style="font-size:12px;letter-spacing:1px;'
                f'text-transform:uppercase;color:{_TEAL};font-weight:600;">'
                f'{_esc(title)}'
                f'</div>'
                f'<div style="margin-top:8px;color:{_SLATE_900};font-size:15px;'
                f'line-height:1.6;">{body}</div>'
                f'</td></tr>'
            )
        else:
            items = block.get("items") or []
            content_rows.append(_block_html(title, _items_html(items)))

    content_rows.append(_footer_html())

    return _wrap_card("".join(content_rows))


# ---------------------------------------------------------------------------
# Weekly HTML
# ---------------------------------------------------------------------------


def render_weekly_reflection_html(user: User, payload: dict[str, Any]) -> str:
    """Render the weekly-reflection payload into an inline-styled HTML body."""
    range_label = _esc(payload.get("range") or payload.get("iso_week") or "")
    headline = _esc(payload.get("headline") or "")
    stats = payload.get("stats") or []
    moves = payload.get("moves") or []

    content_rows: list[str] = [
        _header_html(f"Weekly reflection · {range_label}"),
        (
            f'<tr><td style="padding:0 32px 20px 32px;">'
            f'<h1 style="margin:0;font-size:20px;color:{_SLATE_900};'
            f'font-weight:700;">{headline or "本周反思"}</h1>'
            f'</td></tr>'
        ),
    ]

    if stats:
        stat_cells = []
        for stat in stats:
            if not isinstance(stat, dict):
                continue
            k = _esc(stat.get("k") or "")
            v = _esc(stat.get("v") or "")
            stat_cells.append(
                f'<td style="padding:12px 16px;background:{_SLATE_50};'
                f'border-radius:8px;text-align:center;">'
                f'<div style="font-size:11px;color:{_SLATE_500};'
                f'text-transform:uppercase;letter-spacing:1px;">{k}</div>'
                f'<div style="margin-top:6px;font-size:20px;'
                f'color:{_SLATE_900};font-weight:700;">{v}</div>'
                f'</td>'
                f'<td style="width:8px;"></td>'
            )
        if stat_cells:
            content_rows.append(
                f'<tr><td style="padding:0 32px 16px 32px;">'
                f'<table role="presentation" cellpadding="0" cellspacing="0" '
                f'style="width:100%;border-collapse:separate;">'
                f'<tr>{"".join(stat_cells)}</tr></table>'
                f'</td></tr>'
            )

    if moves:
        move_items = "".join(
            f'<div style="padding:10px 14px;margin-bottom:6px;'
            f'background:{_SLATE_50};border-radius:8px;'
            f'color:{_SLATE_700};font-size:14px;line-height:1.5;">'
            f'{_esc(m)}</div>'
            for m in moves
        )
        content_rows.append(_block_html("真正推进的", move_items))

    content_rows.append(_footer_html())
    return _wrap_card("".join(content_rows))


# ---------------------------------------------------------------------------
# Wrapper / outer table
# ---------------------------------------------------------------------------


def _wrap_card(inner_rows_html: str) -> str:
    return (
        f'<!DOCTYPE html>'
        f'<html lang="zh"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>MRNote digest</title></head>'
        f'<body style="margin:0;padding:0;background:{_SLATE_50};'
        f'font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Roboto,'
        f'\'Helvetica Neue\',Arial,\'PingFang SC\',\'Hiragino Sans GB\','
        f'sans-serif;">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="background:{_SLATE_50};padding:32px 12px;">'
        f'<tr><td align="center">'
        f'<table role="presentation" width="560" cellpadding="0" cellspacing="0" '
        f'style="background:{_WHITE};border-radius:16px;'
        f'box-shadow:0 2px 14px rgba(15,23,42,0.06);max-width:560px;">'
        f'{inner_rows_html}'
        f'</table>'
        f'</td></tr></table>'
        f'</body></html>'
    )


# ---------------------------------------------------------------------------
# Dispatch helpers
# ---------------------------------------------------------------------------


def send_daily_digest_email(user: User, payload: dict[str, Any]) -> None:
    """Dispatch a daily digest to ``user.email``. No-op if email unset."""
    if not user or not user.email:
        return
    if not user.digest_email_enabled:
        return
    date_str = payload.get("date") or ""
    subject = f"MRNote morning digest · {date_str}"
    html_body = render_daily_digest_html(user, payload)
    try:
        send_html_email(
            to=user.email,
            subject=subject,
            html=html_body,
            text_fallback=f"MRNote daily digest for {date_str}.",
        )
    except Exception:  # noqa: BLE001 — mail failure never poisons the digest upsert
        logger.exception(
            "send_daily_digest_email failed for user=%s date=%s",
            user.id, date_str,
        )


def send_weekly_reflection_email(user: User, payload: dict[str, Any]) -> None:
    """Dispatch a weekly reflection to ``user.email``. No-op if email unset."""
    if not user or not user.email:
        return
    if not user.digest_email_enabled:
        return
    range_label = payload.get("range") or payload.get("iso_week") or ""
    subject = f"MRNote weekly reflection · {range_label}"
    html_body = render_weekly_reflection_html(user, payload)
    try:
        send_html_email(
            to=user.email,
            subject=subject,
            html=html_body,
            text_fallback=f"MRNote weekly reflection for {range_label}.",
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "send_weekly_reflection_email failed for user=%s range=%s",
            user.id, range_label,
        )
