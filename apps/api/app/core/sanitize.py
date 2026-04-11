from __future__ import annotations

from typing import Any


_OBJECT_KEY_MARKERS = ("object_key",)
_AUDIT_REDACT_MARKERS = ("object_key", "password", "secret", "token", "cookie", "csrf")


def _should_strip_object_key(key: str) -> bool:
    lower = key.lower()
    return any(marker in lower for marker in _OBJECT_KEY_MARKERS)


def _should_redact_audit_key(key: str) -> bool:
    lower = key.lower()
    return any(marker in lower for marker in _AUDIT_REDACT_MARKERS)


def mask_email(value: str) -> str:
    if "@" not in value:
        return "[redacted]"
    local, domain = value.split("@", 1)
    if len(local) <= 1:
        masked_local = "*"
    elif len(local) == 2:
        masked_local = f"{local[0]}*"
    else:
        masked_local = f"{local[0]}***{local[-1]}"
    return f"{masked_local}@{domain}"


def strip_object_key_fields(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if _should_strip_object_key(key):
                continue
            cleaned[key] = strip_object_key_fields(item)
        return cleaned
    if isinstance(value, list):
        return [strip_object_key_fields(item) for item in value]
    return value


def sanitize_audit_meta(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if _should_redact_audit_key(key):
                cleaned[key] = "[redacted]"
                continue
            if key.lower() == "email" and isinstance(item, str):
                cleaned[key] = mask_email(item)
                continue
            cleaned[key] = sanitize_audit_meta(item)
        return cleaned
    if isinstance(value, list):
        return [sanitize_audit_meta(item) for item in value]
    if isinstance(value, str) and len(value) > 512:
        return value[:509] + "..."
    return value
