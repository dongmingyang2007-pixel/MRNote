"""Transactional email sending via SMTP (Google Workspace / Gmail App Password)."""

from __future__ import annotations

import hashlib
import logging
import secrets
import smtplib
import string
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.core.config import settings
from app.services.runtime_state import runtime_state

logger = logging.getLogger(__name__)


# Curated list of widely-known disposable/throwaway mail domains. Not
# exhaustive — signup hardening, not a security boundary.
DISPOSABLE_EMAIL_DOMAINS: frozenset[str] = frozenset({
    "mailinator.com",
    "10minutemail.com",
    "10minutemail.net",
    "tempmail.com",
    "temp-mail.org",
    "tempmail.io",
    "guerrillamail.com",
    "guerrillamail.net",
    "guerrillamail.org",
    "sharklasers.com",
    "yopmail.com",
    "yopmail.net",
    "trashmail.com",
    "trashmail.net",
    "getnada.com",
    "maildrop.cc",
    "dispostable.com",
    "fakeinbox.com",
    "throwawaymail.com",
    "mohmal.com",
    "emailondeck.com",
    "tempail.com",
})


def is_disposable_email(email: str) -> bool:
    """Return True if the email's domain is a known disposable provider."""
    if not email or "@" not in email:
        return False
    domain = email.rsplit("@", 1)[-1].strip().lower()
    return domain in DISPOSABLE_EMAIL_DOMAINS


def _generate_code() -> str:
    """Generate a numeric verification code."""
    return "".join(secrets.choice(string.digits) for _ in range(settings.verification_code_length))


def _code_key(email: str, purpose: str) -> str:
    """Build a hashed Redis key for the verification code."""
    raw = f"{email.lower().strip()}:{purpose}"
    return hashlib.sha256(raw.encode()).hexdigest()


def store_verification_code(email: str, purpose: str) -> str:
    """Generate a code, persist it in Redis, and return it."""
    code = _generate_code()
    key = _code_key(email, purpose)
    runtime_state.set_json(
        "verify_code",
        key,
        {"code": code, "email": email.lower().strip()},
        ttl_seconds=settings.verification_code_ttl_seconds,
    )
    return code


def verify_code(email: str, purpose: str, code: str) -> bool:
    """Validate and consume a verification code (single-use).

    For ``purpose="reset"``, failed attempts are counted and the code is
    invalidated once ``settings.reset_code_max_attempts`` is reached to cap
    distributed brute-force search over the code's TTL window.
    """
    key = _code_key(email, purpose)
    entry = runtime_state.get_json("verify_code", key)
    if not entry:
        return False
    normalized_email = email.lower().strip()
    expected_code = str(entry.get("code") or "")
    expected_email = str(entry.get("email") or "")
    if not secrets.compare_digest(expected_email, normalized_email):
        return False
    if not secrets.compare_digest(expected_code, code.strip()):
        if purpose == "reset":
            attempts = runtime_state.incr(
                "verify_code_attempts",
                key,
                ttl_seconds=settings.verification_code_ttl_seconds,
            )
            if attempts >= settings.reset_code_max_attempts:
                runtime_state.delete("verify_code", key)
        return False
    runtime_state.delete("verify_code", key)
    runtime_state.delete("verify_code_attempts", key)
    return True


def _build_code_html(code: str, purpose: str) -> str:
    if purpose == "register":
        title = "注册验证码"
        heading = "欢迎注册铭润科技"
        instruction = "请在注册页面输入以下验证码完成注册："
    else:
        title = "密码重设验证码"
        heading = "重设您的密码"
        instruction = "请在重设密码页面输入以下验证码："

    ttl_minutes = settings.verification_code_ttl_seconds // 60
    return f"""\
<!DOCTYPE html>
<html lang="zh">
<head><meta charset="utf-8"><title>{title}</title></head>
<body style="margin:0;padding:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f5f5f7">
  <table width="100%" cellpadding="0" cellspacing="0" style="padding:40px 20px">
    <tr><td align="center">
      <table width="480" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:16px;padding:40px;box-shadow:0 2px 12px rgba(0,0,0,.06)">
        <tr><td style="text-align:center">
          <div style="font-size:14px;color:#86868b;letter-spacing:2px;text-transform:uppercase">铭润科技</div>
          <h1 style="margin:16px 0 8px;font-size:24px;color:#1d1d1f">{heading}</h1>
          <p style="color:#6e6e73;font-size:15px;margin:0 0 24px">{instruction}</p>
          <div style="background:#f5f5f7;border-radius:12px;padding:20px;font-size:36px;font-weight:700;letter-spacing:12px;color:#1d1d1f;font-family:monospace">{code}</div>
          <p style="color:#86868b;font-size:13px;margin:24px 0 0">验证码 {ttl_minutes} 分钟内有效，请勿泄露给他人。</p>
          <p style="color:#c53030;font-size:13px;margin:16px 0 0;font-weight:600">如果您没有请求此验证码，请忽略本邮件 — 您的账户安全未受影响。</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def send_verification_email(to_email: str, code: str, purpose: str) -> None:
    """Send a verification code email via SMTP."""
    if settings.env == "test":
        logger.info("Verification email skipped in test environment for %s", to_email)
        return

    if not settings.smtp_user or not settings.smtp_password:
        if settings.env in {"local", "test"}:
            logger.warning("SMTP not configured — verification email skipped for %s", to_email)
            return
        raise RuntimeError("SMTP not configured")

    msg = MIMEMultipart("alternative")
    msg["From"] = f"{settings.smtp_from_name} <{settings.smtp_from_address}>"
    msg["To"] = to_email
    msg["Subject"] = f"【铭润科技】验证码：{code}"

    plain = (
        f"您的验证码是：{code}\n\n"
        f"验证码 {settings.verification_code_ttl_seconds // 60} 分钟内有效。\n\n"
        "如果您没有请求此验证码，请忽略本邮件 — 您的账户安全未受影响。"
    )
    html = _build_code_html(code, purpose)

    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
        server.starttls()
        server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(msg)

    logger.info("Verification email sent to %s (purpose=%s)", to_email, purpose)


def send_verification_email_safe(to_email: str, code: str, purpose: str) -> None:
    """Best-effort wrapper for background dispatch.

    Verification-code issuance must stay responsive even when SMTP is slow or
    temporarily unavailable, so background workers should log and swallow
    delivery failures instead of aborting the original HTTP request.
    """

    try:
        send_verification_email(to_email, code, purpose)
    except Exception:  # noqa: BLE001
        logger.exception(
            "Verification email background dispatch failed for %s (purpose=%s)",
            to_email,
            purpose,
        )
