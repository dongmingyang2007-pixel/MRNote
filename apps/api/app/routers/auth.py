from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.core.deps import (
    clear_auth_cookie,
    clear_csrf_cookie,
    enforce_rate_limit,
    get_active_csrf_token,
    get_client_ip,
    get_current_user,
    get_db_session,
    issue_csrf_token,
    revoke_user_tokens,
    require_allowed_origin,
    require_csrf_protection,
    set_auth_cookie,
)
from app.core.errors import ApiError
from app.core.security import create_access_token, hash_password, verify_password_or_dummy
from app.core.config import settings
from app.models import Membership, User, Workspace
from app.schemas.auth import (
    AuthResponse,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
    SendCodeRequest,
    UserOut,
    WorkspaceOut,
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
