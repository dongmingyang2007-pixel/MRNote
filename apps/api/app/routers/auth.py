from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from starlette.responses import RedirectResponse

from app.core.deps import (
    clear_auth_cookie,
    clear_csrf_cookie,
    enforce_rate_limit,
    get_active_csrf_token,
    get_client_ip,
    get_current_user,
    get_current_user_optional,
    get_db_session,
    is_safe_redirect_path,
    issue_csrf_token,
    revoke_user_tokens,
    require_allowed_origin,
    require_csrf_protection,
    set_auth_cookie,
)
from app.core.errors import ApiError
from app.core.oauth import oauth
from app.core.security import (
    create_access_token,
    hash_password,
    verify_password,
    verify_password_or_dummy,
)
from app.core.config import settings
from app.models import Membership, OAuthIdentity, User, Workspace
from app.schemas.auth import (
    AuthResponse,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
    SendCodeRequest,
    UserOut,
    WorkspaceOut,
)
from app.schemas.oauth import (
    OAuthDisconnectResponse,
    OAuthIdentityOut,
    SetPasswordRequest,
    SetPasswordResponse,
)
from app.services.audit import write_audit_log
from app.services.email import send_verification_email, store_verification_code, verify_code


router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/send-code")
def send_code(
    payload: SendCodeRequest,
    request: Request,
) -> dict[str, bool]:
    """Send a verification code to the given email address."""
    require_allowed_origin(request)
    client_ip = get_client_ip(request)
    enforce_rate_limit(
        request,
        scope="auth:send_code:ip",
        identifier=client_ip,
        limit=settings.verification_rate_limit_max,
        window_seconds=settings.verification_rate_limit_window_seconds,
    )
    enforce_rate_limit(
        request,
        scope="auth:send_code:email",
        identifier=payload.email,
        limit=settings.verification_rate_limit_max,
        window_seconds=settings.verification_rate_limit_window_seconds,
    )

    code = store_verification_code(payload.email, payload.purpose)
    send_verification_email(payload.email, code, payload.purpose)
    return {"ok": True}


@router.post("/register", response_model=AuthResponse)
def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db_session),
) -> AuthResponse:
    require_allowed_origin(request)
    client_ip = get_client_ip(request)
    enforce_rate_limit(
        request,
        scope="auth:register:ip",
        identifier=client_ip,
        limit=settings.auth_rate_limit_ip_max,
        window_seconds=settings.auth_rate_limit_window_seconds,
    )
    enforce_rate_limit(
        request,
        scope="auth:register:email_ip",
        identifier=f"{payload.email}:{client_ip}",
        limit=settings.auth_rate_limit_email_ip_max,
        window_seconds=settings.auth_rate_limit_window_seconds,
    )

    # Verify the email code
    if not verify_code(payload.email, "register", payload.code):
        raise ApiError("invalid_code", "验证码无效或已过期", status_code=400)

    exists = db.query(User).filter(User.email == payload.email).first()
    if exists:
        raise ApiError("email_exists", "Email already registered", status_code=409)

    user = User(email=payload.email, password_hash=hash_password(payload.password), display_name=payload.display_name)
    workspace = Workspace(name=f"{payload.display_name or payload.email.split('@')[0]} Workspace", plan="free")
    db.add(user)
    db.add(workspace)
    db.flush()

    membership = Membership(workspace_id=workspace.id, user_id=user.id, role="owner")
    db.add(membership)
    write_audit_log(
        db,
        workspace_id=workspace.id,
        actor_user_id=user.id,
        action="auth.register",
        target_type="user",
        target_id=user.id,
        meta_json={"email": user.email},
    )
    db.commit()

    token = create_access_token(user.id)
    set_auth_cookie(response, token)
    issue_csrf_token(response, token, user.id)

    return AuthResponse(
        user=UserOut.model_validate(user, from_attributes=True),
        workspace=WorkspaceOut.model_validate(workspace, from_attributes=True),
        access_token_expires_in_seconds=settings.jwt_expire_minutes * 60,
    )


@router.post("/reset-password")
def reset_password(
    payload: ResetPasswordRequest,
    request: Request,
    db: Session = Depends(get_db_session),
) -> dict[str, bool]:
    """Verify code and set a new password."""
    require_allowed_origin(request)
    client_ip = get_client_ip(request)
    enforce_rate_limit(
        request,
        scope="auth:reset:ip",
        identifier=client_ip,
        limit=settings.auth_rate_limit_ip_max,
        window_seconds=settings.auth_rate_limit_window_seconds,
    )

    if not verify_code(payload.email, "reset", payload.code):
        raise ApiError("invalid_code", "验证码无效或已过期", status_code=400)

    user = db.query(User).filter(User.email == payload.email).first()
    if not user:
        return {"ok": True}

    user.password_hash = hash_password(payload.password)
    revoke_user_tokens(user.id)
    db.commit()
    return {"ok": True}


@router.post("/login", response_model=AuthResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db_session),
) -> AuthResponse:
    require_allowed_origin(request)
    client_ip = get_client_ip(request)
    enforce_rate_limit(
        request,
        scope="auth:login:ip",
        identifier=client_ip,
        limit=settings.auth_rate_limit_ip_max,
        window_seconds=settings.auth_rate_limit_window_seconds,
    )
    enforce_rate_limit(
        request,
        scope="auth:login:email_ip",
        identifier=f"{payload.email}:{client_ip}",
        limit=settings.auth_rate_limit_email_ip_max,
        window_seconds=settings.auth_rate_limit_window_seconds,
    )
    user = db.query(User).filter(User.email == payload.email).first()
    if not verify_password_or_dummy(payload.password, user.password_hash if user else None):
        raise ApiError("invalid_credentials", "Invalid email or password", status_code=401)

    workspace = (
        db.query(Workspace)
        .join(Membership, Membership.workspace_id == Workspace.id)
        .filter(Membership.user_id == user.id)
        .order_by(Workspace.created_at.asc())
        .first()
    )
    if not workspace:
        raise ApiError("workspace_not_found", "No workspace found", status_code=404)

    token = create_access_token(user.id)
    set_auth_cookie(response, token)
    issue_csrf_token(response, token, user.id)

    return AuthResponse(
        user=UserOut.model_validate(user, from_attributes=True),
        workspace=WorkspaceOut.model_validate(workspace, from_attributes=True),
        access_token_expires_in_seconds=settings.jwt_expire_minutes * 60,
    )


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    _: None = Depends(require_csrf_protection),
) -> dict[str, bool]:
    require_allowed_origin(request)
    revoke_user_tokens(current_user.id)
    clear_auth_cookie(response)
    clear_csrf_cookie(response)
    return {"ok": True}


@router.get("/csrf")
def refresh_csrf(
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    require_allowed_origin(request)
    access_token = getattr(request.state, "access_token", None)
    if not access_token:
        raise ApiError("unauthorized", "Authentication required", status_code=401)
    existing_csrf = get_active_csrf_token(
        access_token=access_token,
        csrf_cookie=request.cookies.get(settings.csrf_cookie_name),
        user_id=current_user.id,
    )
    if existing_csrf:
        return {"csrf_token": existing_csrf}
    csrf_token = issue_csrf_token(response, access_token, current_user.id)
    return {"csrf_token": csrf_token}


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(current_user, from_attributes=True)


@router.post("/onboarding/complete")
def complete_onboarding(
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    _: None = Depends(require_csrf_protection),
) -> dict[str, Any]:
    """Mark onboarding as completed for the current user.

    Idempotent: if already completed, the existing timestamp is preserved.
    """
    if current_user.onboarding_completed_at is None:
        current_user.onboarding_completed_at = datetime.now(timezone.utc)
        db.add(current_user)
        db.commit()
        db.refresh(current_user)
    return {
        "ok": True,
        "onboarding_completed_at": current_user.onboarding_completed_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# Google OAuth
# ---------------------------------------------------------------------------


def _create_user_with_workspace_for_oauth(
    db: Session, email: str, display_name: str,
) -> User:
    """Mirror ``/register`` but with password_hash=None and no verification code.

    Google's ``email_verified=true`` plays the role of our verification step.
    """
    user = User(
        email=email,
        password_hash=None,
        display_name=display_name or email.split("@")[0],
    )
    workspace = Workspace(
        name=f"{display_name or email.split('@')[0]} Workspace",
        plan="free",
    )
    db.add(user)
    db.add(workspace)
    db.flush()
    db.add(Membership(workspace_id=workspace.id, user_id=user.id, role="owner"))
    write_audit_log(
        db,
        workspace_id=workspace.id,
        actor_user_id=user.id,
        action="auth.register.oauth",
        target_type="user",
        target_id=user.id,
        meta_json={"email": user.email, "provider": "google"},
    )
    db.commit()
    return user


@router.get("/google/authorize")
async def google_authorize(
    request: Request,
    next: str | None = None,
    mode: Literal["signin", "connect"] = "signin",
    current_user: User | None = Depends(get_current_user_optional),
):
    """Start the Google OAuth round-trip.

    ``mode="signin"`` handles sign-in + sign-up (new users auto-provision).
    ``mode="connect"`` is used by signed-in users to link an additional
    Google identity from the Settings page.
    """
    if not settings.google_oauth_enabled:
        raise ApiError("not_found", "OAuth is disabled", status_code=404)

    client_ip = get_client_ip(request)
    enforce_rate_limit(
        request,
        scope="auth:oauth_authorize:ip",
        identifier=client_ip,
        limit=settings.auth_rate_limit_ip_max,
        window_seconds=settings.auth_rate_limit_window_seconds,
    )

    safe_next = next if is_safe_redirect_path(next) else "/app"

    if mode == "connect":
        if current_user is None:
            return RedirectResponse(
                url="/login?error=auth_required", status_code=302
            )
        request.session["oauth_mode"] = "connect"
        request.session["oauth_connect_user_id"] = current_user.id
    else:
        request.session["oauth_mode"] = "signin"
        request.session["oauth_connect_user_id"] = None

    request.session["oauth_next"] = safe_next

    redirect_uri = settings.google_oauth_redirect_uri
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/google/callback")
async def google_callback(
    request: Request,
    response: Response,
    db: Session = Depends(get_db_session),
):
    """Finish the Google OAuth round-trip.

    Three branches:
    1. ``existing_identity`` found → sign the mapped user in.
    2. New provider_id + ``email`` matches an existing user → auto-link.
    3. Brand-new → create User + Workspace + Membership + OAuthIdentity.

    ``mode == "connect"`` is a separate branch that links an additional
    Google identity to the currently-signed-in user and sends them back
    to the Settings page.
    """
    if not settings.google_oauth_enabled:
        raise ApiError("not_found", "OAuth is disabled", status_code=404)

    enforce_rate_limit(
        request,
        scope="auth:oauth_callback:ip",
        identifier=get_client_ip(request),
        limit=settings.auth_rate_limit_ip_max,
        window_seconds=settings.auth_rate_limit_window_seconds,
    )

    if request.query_params.get("error") == "access_denied":
        return RedirectResponse(url="/login?error=oauth_cancelled", status_code=302)

    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception:  # noqa: BLE001 — Authlib raises a variety of errors on state/code mismatch
        return RedirectResponse(url="/login?error=oauth_state_mismatch", status_code=302)

    try:
        id_claims = await oauth.google.parse_id_token(request, token)
    except Exception:  # noqa: BLE001
        return RedirectResponse(url="/login?error=oauth_invalid_id_token", status_code=302)

    sub = id_claims.get("sub") if id_claims else None
    email = id_claims.get("email") if id_claims else None
    email_verified = bool(id_claims.get("email_verified")) if id_claims else False
    display_name = (id_claims.get("name") if id_claims else "") or ""

    if not sub or not email:
        return RedirectResponse(url="/login?error=oauth_invalid_id_token", status_code=302)

    mode = request.session.get("oauth_mode", "signin")
    next_path = request.session.get("oauth_next") or "/app"
    connect_user_id = request.session.get("oauth_connect_user_id")

    # Clean up session state once consumed so a replay doesn't land in the
    # wrong branch.
    request.session.pop("oauth_mode", None)
    request.session.pop("oauth_next", None)
    request.session.pop("oauth_connect_user_id", None)

    existing_identity = db.execute(
        select(OAuthIdentity).where(
            OAuthIdentity.provider == "google",
            OAuthIdentity.provider_id == sub,
        )
    ).scalar_one_or_none()

    # ---- Connect mode ----
    if mode == "connect":
        if connect_user_id is None:
            return RedirectResponse(url="/login?error=auth_required", status_code=302)
        if existing_identity is not None and existing_identity.user_id != connect_user_id:
            return RedirectResponse(
                url="/app/settings?error=already_linked", status_code=302
            )
        if existing_identity is None:
            db.add(OAuthIdentity(
                user_id=connect_user_id, provider="google",
                provider_id=sub, provider_email=email,
            ))
            db.commit()
        write_audit_log(
            db,
            workspace_id=None,
            actor_user_id=connect_user_id,
            action="auth.oauth.google.connect",
            target_type="user",
            target_id=connect_user_id,
            meta_json={"provider": "google", "provider_email": email},
        )
        db.commit()
        separator = "&" if "?" in next_path else "?"
        return RedirectResponse(
            url=f"{next_path}{separator}connected=google", status_code=302
        )

    # ---- Sign-in mode ----
    if existing_identity is not None:
        if existing_identity.provider_email != email:
            existing_identity.provider_email = email
            db.commit()
        user = db.get(User, existing_identity.user_id)
        if user is None:
            # Shouldn't happen (FK would prevent orphan), but fail closed.
            return RedirectResponse(url="/login?error=oauth_state_mismatch", status_code=302)
    else:
        user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if not email_verified:
            return RedirectResponse(
                url="/login?error=google_email_unverified", status_code=302
            )
        if user is not None:
            db.add(OAuthIdentity(
                user_id=user.id, provider="google",
                provider_id=sub, provider_email=email,
            ))
            db.commit()
        else:
            user = _create_user_with_workspace_for_oauth(
                db=db, email=email, display_name=display_name,
            )
            db.add(OAuthIdentity(
                user_id=user.id, provider="google",
                provider_id=sub, provider_email=email,
            ))
            db.commit()

    token_str = create_access_token(user.id)
    set_auth_cookie(response, token_str)
    issue_csrf_token(response, token_str, user.id)
    write_audit_log(
        db,
        workspace_id=None,
        actor_user_id=user.id,
        action="auth.oauth.google.signin",
        target_type="user",
        target_id=user.id,
        meta_json={"provider": "google", "provider_email": email},
    )
    db.commit()

    redir = RedirectResponse(url=next_path, status_code=302)
    # Carry the Set-Cookie headers written onto ``response`` by set_auth_cookie
    # + issue_csrf_token through to the actual redirect response we return.
    for cookie_header in response.headers.getlist("set-cookie"):
        redir.headers.append("set-cookie", cookie_header)
    return redir


@router.get("/identities", response_model=list[OAuthIdentityOut])
def list_identities(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> list[OAuthIdentityOut]:
    """Return the current user's linked external identities."""
    rows = db.execute(
        select(OAuthIdentity)
        .where(OAuthIdentity.user_id == current_user.id)
        .order_by(OAuthIdentity.linked_at.desc())
    ).scalars().all()
    return [OAuthIdentityOut.model_validate(r) for r in rows]


@router.post("/google/disconnect", response_model=OAuthDisconnectResponse)
def google_disconnect(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
    _csrf: None = Depends(require_csrf_protection),
) -> OAuthDisconnectResponse:
    """Unlink Google from the current user.

    Blocks with 409 ``password_required`` when the user has no password
    (removing the link would lock them out of every sign-in method).
    """
    enforce_rate_limit(
        request,
        scope="auth:oauth_disconnect:user",
        identifier=current_user.id,
        limit=10,
        window_seconds=3600,
    )
    if current_user.password_hash is None:
        raise ApiError(
            "password_required",
            "Please set a password before disconnecting Google.",
            status_code=409,
        )
    db.execute(
        delete(OAuthIdentity).where(
            OAuthIdentity.user_id == current_user.id,
            OAuthIdentity.provider == "google",
        )
    )
    write_audit_log(
        db,
        workspace_id=None,
        actor_user_id=current_user.id,
        action="auth.oauth.google.disconnect",
        target_type="user",
        target_id=current_user.id,
        meta_json={"provider": "google"},
    )
    db.commit()
    return OAuthDisconnectResponse(success=True)


@router.put("/password", response_model=SetPasswordResponse)
def set_password(
    payload: SetPasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
    _csrf: None = Depends(require_csrf_protection),
) -> SetPasswordResponse:
    """Set or change the current user's password.

    Users who signed up via Google have ``password_hash=None``; they can
    simply ``PUT {new_password}``. Users who already have a password must
    include ``current_password`` to rotate.
    """
    if current_user.password_hash is not None:
        if not payload.current_password:
            raise ApiError(
                "invalid_request", "current_password required", status_code=400
            )
        if not verify_password(payload.current_password, current_user.password_hash):
            raise ApiError(
                "invalid_credentials", "Wrong current password", status_code=400
            )
    current_user.password_hash = hash_password(payload.new_password)
    write_audit_log(
        db,
        workspace_id=None,
        actor_user_id=current_user.id,
        action="auth.password.set",
        target_type="user",
        target_id=current_user.id,
        meta_json={},
    )
    db.commit()
    return SetPasswordResponse(success=True)
