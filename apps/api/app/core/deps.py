import hashlib
import secrets
from collections.abc import Generator
from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi import Cookie, Depends, Request, Response
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import ApiError
from app.core.security import decode_token
from app.db.session import get_db
from app.models import Membership, User
from app.services.runtime_state import runtime_state

_AUTH_TOKEN_STATE_SCOPE = "auth_token_state"
_WORKSPACE_WRITE_ROLES = {"owner", "admin", "editor"}
_WORKSPACE_PRIVILEGED_ROLES = {"owner", "admin"}
_WORKSPACE_COOKIE_NAMES = ("mingrun_workspace_id", "qihang_workspace_id")


def get_db_session() -> Generator[Session, None, None]:
    yield from get_db()


def authenticate_access_token(
    *,
    db: Session,
    access_token: str,
) -> tuple[User, dict[str, object]]:
    try:
        payload = decode_token(access_token)
    except ValueError as exc:
        raise ApiError("unauthorized", "Invalid token", status_code=401) from exc
    user_id = payload.get("sub")
    if not isinstance(user_id, str) or not user_id:
        raise ApiError("unauthorized", "Invalid token", status_code=401)
    if is_token_revoked_for_user(user_id, payload):
        raise ApiError("unauthorized", "Invalid token", status_code=401)
    user = db.get(User, user_id)
    if not user:
        raise ApiError("unauthorized", "User not found", status_code=401)
    return user, payload


def get_current_user(
    request: Request,
    db: Session = Depends(get_db_session),
    access_token: str | None = Cookie(default=None, alias=settings.access_cookie_name),
) -> User:
    if not access_token:
        raise ApiError("unauthorized", "Authentication required", status_code=401)
    user, payload = authenticate_access_token(db=db, access_token=access_token)
    request.state.access_token = access_token
    request.state.access_token_payload = payload
    request.state.current_user_id = user.id
    return user


def get_current_workspace_membership(
    request: Request,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> Membership:
    workspace_id = request.headers.get("x-workspace-id") or request.query_params.get("workspace_id")
    if not workspace_id:
        for cookie_name in _WORKSPACE_COOKIE_NAMES:
            cookie_value = request.cookies.get(cookie_name)
            if cookie_value:
                workspace_id = cookie_value
                break
    memberships = (
        db.query(Membership)
        .filter(Membership.user_id == current_user.id)
        .order_by(Membership.workspace_id.asc())
        .all()
    )
    if workspace_id:
        membership = next((item for item in memberships if item.workspace_id == workspace_id), None)
        if not membership:
            raise ApiError("forbidden", "Workspace access denied", status_code=403)
    else:
        if not memberships:
            raise ApiError("forbidden", "No workspace membership", status_code=403)
        if len(memberships) > 1:
            raise ApiError("workspace_required", "Workspace selection is required", status_code=409)
        membership = memberships[0]

    request.state.workspace_role = membership.role
    return membership


def get_current_workspace_id(
    membership: Membership = Depends(get_current_workspace_membership),
) -> str:
    return membership.workspace_id


def get_current_workspace_role(
    membership: Membership = Depends(get_current_workspace_membership),
) -> str:
    return membership.role or "owner"


def is_workspace_write_role(role: str) -> bool:
    return role in _WORKSPACE_WRITE_ROLES


def is_workspace_privileged_role(role: str) -> bool:
    return role in _WORKSPACE_PRIVILEGED_ROLES


def can_access_workspace_conversation(
    *,
    current_user_id: str,
    workspace_role: str,
    conversation_created_by: str | None,
) -> bool:
    return is_workspace_privileged_role(workspace_role) or conversation_created_by == current_user_id


def require_workspace_write_access(
    workspace_role: str = Depends(get_current_workspace_role),
) -> None:
    if is_workspace_write_role(workspace_role):
        return
    raise ApiError("forbidden", "Workspace role does not permit this action", status_code=403)


def get_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for")
    if settings.trust_forwarded_for and forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def require_allowed_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin:
        normalized_origin = settings.normalize_origin(origin)
    else:
        referer = request.headers.get("referer")
        if not referer:
            raise ApiError("origin_required", "Origin or Referer header is required", status_code=403)
        parsed = urlparse(referer)
        normalized_origin = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")

    if not settings.is_origin_allowed(normalized_origin):
        raise ApiError("forbidden_origin", "Origin not allowed", status_code=403)


def _build_access_token_hash(access_token: str) -> str:
    return hashlib.sha256(access_token.encode("utf-8")).hexdigest()


def _coerce_timestamp(value: object) -> float | None:
    if isinstance(value, datetime):
        return value.timestamp()
    if isinstance(value, (int, float)):
        return float(value)
    return None


def is_token_revoked_for_user(user_id: str, payload: dict[str, object]) -> bool:
    auth_state = runtime_state.get_json(_AUTH_TOKEN_STATE_SCOPE, user_id)
    if not auth_state:
        return False
    not_before = _coerce_timestamp(auth_state.get("not_before"))
    if not_before is None:
        return False
    issued_at = _coerce_timestamp(payload.get("iat"))
    if issued_at is None:
        return True
    return issued_at < not_before


def revoke_user_tokens(user_id: str) -> None:
    runtime_state.set_json(
        _AUTH_TOKEN_STATE_SCOPE,
        user_id,
        {"not_before": datetime.now(timezone.utc).timestamp()},
        ttl_seconds=max(settings.jwt_expire_minutes * 60, settings.csrf_ttl_seconds),
    )


def set_auth_cookie(response: Response, token: str) -> None:
    cookie_kwargs = {
        "key": settings.access_cookie_name,
        "value": token,
        "httponly": True,
        "secure": settings.cookie_secure,
        "samesite": settings.cookie_samesite,
        "max_age": settings.jwt_expire_minutes * 60,
        "path": "/",
    }
    if settings.cookie_domain and settings.cookie_domain not in {"localhost", "testserver"}:
        cookie_kwargs["domain"] = settings.cookie_domain
    response.set_cookie(**cookie_kwargs)


def set_csrf_cookie(response: Response, csrf_token: str) -> None:
    cookie_kwargs = {
        "key": settings.csrf_cookie_name,
        "value": csrf_token,
        "httponly": False,
        "secure": settings.cookie_secure,
        "samesite": settings.cookie_samesite,
        "max_age": settings.csrf_ttl_seconds,
        "path": "/",
    }
    if settings.cookie_domain and settings.cookie_domain not in {"localhost", "testserver"}:
        cookie_kwargs["domain"] = settings.cookie_domain
    response.set_cookie(**cookie_kwargs)


def clear_auth_cookie(response: Response) -> None:
    if settings.cookie_domain and settings.cookie_domain not in {"localhost", "testserver"}:
        response.delete_cookie(
            key=settings.access_cookie_name,
            domain=settings.cookie_domain,
            path="/",
        )
    else:
        response.delete_cookie(
            key=settings.access_cookie_name,
            path="/",
        )


def clear_csrf_cookie(response: Response) -> None:
    if settings.cookie_domain and settings.cookie_domain not in {"localhost", "testserver"}:
        response.delete_cookie(
            key=settings.csrf_cookie_name,
            domain=settings.cookie_domain,
            path="/",
        )
    else:
        response.delete_cookie(
            key=settings.csrf_cookie_name,
            path="/",
        )


def issue_csrf_token(response: Response, access_token: str, user_id: str) -> str:
    csrf_token = secrets.token_urlsafe(32)
    runtime_state.set_json(
        "csrf",
        _build_access_token_hash(access_token),
        {"token": csrf_token, "user_id": user_id},
        ttl_seconds=settings.csrf_ttl_seconds,
    )
    set_csrf_cookie(response, csrf_token)
    return csrf_token


def get_active_csrf_token(
    *,
    access_token: str | None,
    csrf_cookie: str | None,
    user_id: str,
) -> str | None:
    if not access_token or not csrf_cookie:
        return None
    csrf_state = runtime_state.get_json("csrf", _build_access_token_hash(access_token))
    if not csrf_state:
        return None
    if csrf_state.get("token") != csrf_cookie:
        return None
    if csrf_state.get("user_id") != user_id:
        return None
    return csrf_cookie


def require_csrf_protection(
    request: Request,
    current_user: User = Depends(get_current_user),
    access_token: str | None = Cookie(default=None, alias=settings.access_cookie_name),
    csrf_cookie: str | None = Cookie(default=None, alias=settings.csrf_cookie_name),
) -> None:
    _ = current_user
    require_allowed_origin(request)
    header_token = request.headers.get("x-csrf-token")
    if not access_token or not csrf_cookie or not header_token:
        raise ApiError("csrf_required", "CSRF token is required", status_code=403)
    if header_token != csrf_cookie:
        raise ApiError("csrf_mismatch", "CSRF token mismatch", status_code=403)
    active_token = get_active_csrf_token(
        access_token=access_token,
        csrf_cookie=csrf_cookie,
        user_id=current_user.id,
    )
    if active_token != header_token:
        raise ApiError("csrf_invalid", "CSRF token is invalid or expired", status_code=403)


def enforce_rate_limit(
    request: Request,
    *,
    scope: str,
    identifier: str,
    limit: int,
    window_seconds: int,
) -> None:
    hashed_identifier = hashlib.sha256(identifier.encode("utf-8")).hexdigest()
    current = runtime_state.incr(scope, hashed_identifier, ttl_seconds=window_seconds)
    if current > limit:
        raise ApiError("rate_limited", "Too many requests", status_code=429)
