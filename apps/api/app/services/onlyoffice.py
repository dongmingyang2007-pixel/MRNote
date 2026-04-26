"""ONLYOFFICE Document Server integration.

Two distinct JWTs flow through this module:

1. The "config token" that wraps the editor config and is validated by
   ONLYOFFICE itself (HS256, signed with `onlyoffice_jwt_secret` shared
   between this backend and the Document Server container).
2. Short-lived "scoped tokens" we put in URL query strings so the Document
   Server can call back into our API without a session cookie. Each
   scoped token is bound to (data_item_id, action, user_id) so a leaked
   download URL can't be replayed against the callback endpoint.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from jose import JWTError, jwt

from app.core.config import settings
from app.models import DataItem, User


_JWT_ALGORITHM = "HS256"

# (Document Server's) supported documentType values
_DOC_TYPE_BY_EXT: dict[str, Literal["word", "cell", "slide"]] = {
    "docx": "word",
    "txt": "word",
    "xlsx": "cell",
    "csv": "cell",
    "pptx": "slide",
}
_MEDIA_TYPES_BY_EXT: dict[str, set[str]] = {
    "docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    },
    "xlsx": {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    },
    "pptx": {
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    },
    "txt": {"text/plain"},
    "csv": {"text/csv", "text/plain"},
}


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def is_onlyoffice_eligible(filename: str, media_type: str | None = None) -> bool:
    """Return True if the file extension is a format ONLYOFFICE can edit."""
    ext = _extension_for(filename)
    if ext not in _DOC_TYPE_BY_EXT:
        return False
    if media_type is None:
        return True
    normalized_media_type = media_type.split(";", 1)[0].strip().lower()
    return normalized_media_type in _MEDIA_TYPES_BY_EXT.get(ext, set())


def _extension_for(filename: str) -> str:
    if not filename or "." not in filename:
        return ""
    return filename.rsplit(".", 1)[-1].lower()


def _document_type(filename: str) -> Literal["word", "cell", "slide"]:
    ext = _extension_for(filename)
    return _DOC_TYPE_BY_EXT.get(ext, "word")


def _require_secret() -> str:
    if not settings.onlyoffice_jwt_secret:
        raise RuntimeError("ONLYOFFICE_JWT_SECRET is not configured")
    return settings.onlyoffice_jwt_secret


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------


def sign_onlyoffice_payload(payload: dict[str, Any]) -> str:
    """Sign the editor config so ONLYOFFICE accepts it (JWT_ENABLED=true)."""
    return jwt.encode(payload, _require_secret(), algorithm=_JWT_ALGORITHM)


def verify_onlyoffice_payload(token: str) -> dict[str, Any]:
    """Verify a JWT (config or callback). Raises on invalid token."""
    return jwt.decode(token, _require_secret(), algorithms=[_JWT_ALGORITHM])


def issue_scoped_token(
    *,
    data_item_id: str,
    user_id: str,
    action: Literal["download", "callback"],
    ttl_seconds: int | None = None,
) -> str:
    """Issue a short-lived token bound to one document and one action."""
    now = datetime.now(timezone.utc)
    ttl = ttl_seconds or settings.onlyoffice_token_ttl_seconds
    payload = {
        "sub": data_item_id,
        "act": action,
        "uid": user_id,
        "iat": now,
        "exp": now + timedelta(seconds=ttl),
        "jti": secrets.token_urlsafe(8),
    }
    return jwt.encode(payload, _require_secret(), algorithm=_JWT_ALGORITHM)


def verify_scoped_token(
    token: str,
    *,
    expected_action: Literal["download", "callback"],
    expected_data_item_id: str,
) -> dict[str, Any]:
    """Verify a scoped token. Raises if the token is invalid, expired, or
    bound to a different document/action."""
    try:
        payload = jwt.decode(token, _require_secret(), algorithms=[_JWT_ALGORITHM])
    except JWTError as exc:
        raise ValueError("Invalid ONLYOFFICE token") from exc
    if payload.get("act") != expected_action:
        raise ValueError("Token action mismatch")
    if payload.get("sub") != expected_data_item_id:
        raise ValueError("Token subject mismatch")
    return payload


# ---------------------------------------------------------------------------
# Editor config builder
# ---------------------------------------------------------------------------


def document_key(item: DataItem) -> str:
    """ONLYOFFICE caches by document key. We tie it to size+sha256 so the
    cache invalidates after any in-place save. Falls back to created_at if
    sha256 isn't computed yet (shouldn't happen post-upload)."""
    parts = [str(item.id)]
    if item.sha256:
        parts.append(item.sha256[:12])
    else:
        parts.append(str(int(item.size_bytes or 0)))
        if item.created_at:
            parts.append(str(int(item.created_at.timestamp())))
    raw = "-".join(parts)
    # ONLYOFFICE keys must be ≤128 chars, alphanum + . _ -; hash to be safe.
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def build_editor_config(
    item: DataItem,
    user: User,
    *,
    can_edit: bool,
    locale: str = "zh-CN",
) -> dict[str, Any]:
    """Build the editor config the frontend hands to DocsAPI.DocEditor.

    Contains a config-level JWT in `token` so ONLYOFFICE Server validates
    it. The `document.url` and `editorConfig.callbackUrl` carry their own
    short-lived scoped tokens so ONLYOFFICE Server can call back without
    a session cookie.
    """
    callback_origin = settings.onlyoffice_callback_origin
    download_token = issue_scoped_token(
        data_item_id=str(item.id),
        user_id=str(user.id),
        action="download",
    )

    document_url = (
        f"{callback_origin}/api/v1/onlyoffice/documents/{item.id}/content"
        f"?token={download_token}"
    )

    file_type = _extension_for(item.filename) or "docx"
    document_type = _document_type(item.filename)

    config: dict[str, Any] = {
        "document": {
            "fileType": file_type,
            "key": document_key(item),
            "title": item.filename,
            "url": document_url,
            "permissions": {
                "edit": can_edit,
                "download": True,
                "print": True,
                "comment": can_edit,
                "review": can_edit,
            },
        },
        "documentType": document_type,
        "editorConfig": {
            "lang": locale,
            "mode": "edit" if can_edit else "view",
            "user": {
                "id": str(user.id),
                "name": _display_name(user),
            },
            "customization": {
                "autosave": True,
                "forcesave": True,
                "compactHeader": False,
            },
        },
        # The Document Server checks `token` against the same secret; when
        # JWT_ENABLED is true on the server side, omitting this rejects the
        # editor config outright.
        "type": "desktop",
    }
    if can_edit:
        callback_token = issue_scoped_token(
            data_item_id=str(item.id),
            user_id=str(user.id),
            action="callback",
        )
        callback_url = (
            f"{callback_origin}/api/v1/onlyoffice/documents/{item.id}/callback"
            f"?token={callback_token}"
        )
        config["editorConfig"]["callbackUrl"] = callback_url
    config["token"] = sign_onlyoffice_payload(
        {
            "document": config["document"],
            "documentType": config["documentType"],
            "editorConfig": config["editorConfig"],
        }
    )
    config["docServerUrl"] = settings.onlyoffice_doc_server_url
    return config


def _display_name(user: User) -> str:
    candidates: list[Any] = []
    for attr in ("full_name", "display_name", "name", "email"):
        value = getattr(user, attr, None)
        if value:
            candidates.append(value)
    return str(candidates[0]) if candidates else "Editor"
