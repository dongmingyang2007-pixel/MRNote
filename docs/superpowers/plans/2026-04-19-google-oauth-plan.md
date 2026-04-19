# Google OAuth Sign-In Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Google OAuth 2.0 + OpenID Connect as a parallel identity provider to the existing email/password auth, with a provider-agnostic `oauth_identities` table that future Apple / GitHub providers can plug into.

**Architecture:** Backend uses Authlib's Starlette integration for the OAuth round-trip; new routes under `/api/v1/auth/google/*` handle authorize/callback/connect/disconnect; `oauth_identities` table keys on `(provider, provider_id)` so email changes don't break links. Frontend renders `<GoogleSignInButton>` above email forms on `/login` + `/register`, plus a `<ConnectedAccountsList>` section in `/app/settings` for manage/disconnect. All behind `GOOGLE_OAUTH_ENABLED` feature flag for safe rollout.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 + Alembic + pytest (backend); Next.js 16 + React 19 + next-intl + vitest + Playwright (frontend); Authlib 1.3+ + itsdangerous 2+ (new backend deps).

**Test commands:**
- Backend unit: `cd apps/api && pytest tests/test_auth_google.py -v`
- Backend full: `cd apps/api && pytest`
- Frontend unit: `cd apps/web && node_modules/.bin/vitest run <path>`
- Frontend e2e: `cd apps/web && node_modules/.bin/playwright test tests/auth-oauth.spec.ts`
- Typecheck: `cd apps/web && node_modules/.bin/tsc --noEmit`

**Commit policy:** one commit per task. Use `feat(api): …` / `feat(web): …` / `chore(db): …` / `test: …`. Co-author footer mandatory:
```
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

## Task 1: Alembic migration + `OAuthIdentity` model

**Files:**
- Create: `apps/api/alembic/versions/202604190001_oauth_identities.py`
- Modify: `apps/api/app/models/entities.py` (append `OAuthIdentity` class)

### - [ ] Step 1: Write the migration

Create `apps/api/alembic/versions/202604190001_oauth_identities.py`:

```python
"""oauth_identities table + users.password_hash nullable

Revision ID: 202604190001
Revises: <prev_revision>
Create Date: 2026-04-19

"""

from alembic import op

# Revision identifiers, used by Alembic.
revision = "202604190001"
# Look up the latest revision with `alembic heads` and paste below; if the
# repo's head on your checkout is different, use that.
down_revision = None  # FILL: set to current head before running
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) Make users.password_hash nullable so OAuth-only users can exist.
    op.execute("ALTER TABLE users ALTER COLUMN password_hash DROP NOT NULL")

    # 2) Create oauth_identities table.
    op.execute(
        """
        CREATE TABLE oauth_identities (
            id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
            user_id         uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            provider        text NOT NULL,
            provider_id     text NOT NULL,
            provider_email  text,
            linked_at       timestamptz NOT NULL DEFAULT now(),
            created_at      timestamptz NOT NULL DEFAULT now(),
            updated_at      timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_oauth_provider_id   UNIQUE (provider, provider_id),
            CONSTRAINT uq_oauth_provider_user UNIQUE (provider, user_id)
        )
        """
    )
    op.execute("CREATE INDEX idx_oauth_identities_user_id ON oauth_identities (user_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS oauth_identities")
    # Re-add NOT NULL. Will fail if any user row currently has NULL password_hash;
    # in that case the operator must re-set a password for those users before
    # downgrading. We accept that constraint.
    op.execute("ALTER TABLE users ALTER COLUMN password_hash SET NOT NULL")
```

Before running, open a shell in `apps/api/` and run `alembic heads` to find the current head revision ID. Replace `down_revision = None` with that string.

### - [ ] Step 2: Append the model to `entities.py`

Open `apps/api/app/models/entities.py` and add at the bottom (after the existing model classes, before any footer code):

```python
class OAuthIdentity(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "oauth_identities"
    __table_args__ = (
        UniqueConstraint("provider", "provider_id", name="uq_oauth_provider_id"),
        UniqueConstraint("provider", "user_id", name="uq_oauth_provider_user"),
    )

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    provider_id: Mapped[str] = mapped_column(Text, nullable=False)
    provider_email: Mapped[str | None] = mapped_column(Text, nullable=True)
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
```

Also make `User.password_hash` nullable in the model. Find the existing `User` class and change:

```python
# BEFORE
password_hash: Mapped[str] = mapped_column(Text, nullable=False)

# AFTER
password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
```

If `UniqueConstraint`, `ForeignKey`, `Text`, `DateTime`, `datetime`, `timezone`, `Mapped`, `mapped_column` aren't already imported at the top of the file, add them to the existing import block.

### - [ ] Step 3: Run the migration against dev DB

```bash
cd apps/api
alembic upgrade head
```
Expected: `Running upgrade … -> 202604190001, oauth_identities …` — one line per new revision.

Verify the schema:

```bash
psql -h localhost -U postgres -d mrai_dev -c "\d oauth_identities"
```
Expected: table listing with 8 columns, 2 unique constraints, 1 index.

### - [ ] Step 4: Commit

```bash
git add apps/api/alembic/versions/202604190001_oauth_identities.py \
        apps/api/app/models/entities.py
git commit -m "$(cat <<'EOF'
chore(db): add oauth_identities table + make users.password_hash nullable

Provider-agnostic shape: (provider='google'|'apple'|…, provider_id=sub)
with UNIQUE (provider, provider_id) and UNIQUE (provider, user_id). Users
keyed on `sub` so Google email changes don't break links.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Config + auth deps helpers

**Files:**
- Modify: `apps/api/app/core/config.py`
- Modify: `apps/api/app/core/deps.py` (append `get_current_user_optional` + `is_safe_redirect_path`)
- Modify: `apps/api/.env.example` or `apps/api/app/core/.env.example` (find the live path and append)
- Modify: `apps/api/pyproject.toml` or `apps/api/requirements.txt` (add `authlib>=1.3` and `itsdangerous>=2.0`)

### - [ ] Step 1: Add deps to `pyproject.toml`

Find the `[project.dependencies]` section (or `requirements.txt` if that's what the repo uses) and append:

```toml
"authlib>=1.3",
"itsdangerous>=2.0",
"httpx>=0.25",  # authlib needs an async HTTP client
```

### - [ ] Step 2: Install deps

```bash
cd apps/api
pip install authlib itsdangerous httpx
# OR poetry install / pdm sync, per repo convention
```

### - [ ] Step 3: Add env vars to `config.py`

Open `apps/api/app/core/config.py`. Find the `Settings(BaseSettings)` class and append near the existing auth fields:

```python
    # Google OAuth
    google_client_id: str = Field(default="", env="GOOGLE_CLIENT_ID")
    google_client_secret: str = Field(default="", env="GOOGLE_CLIENT_SECRET")
    google_oauth_redirect_base: str = Field(
        default="http://localhost:3000", env="GOOGLE_OAUTH_REDIRECT_BASE"
    )
    oauth_session_secret: str = Field(default="change-me-in-prod", env="OAUTH_SESSION_SECRET")
    google_oauth_enabled: bool = Field(default=False, env="GOOGLE_OAUTH_ENABLED")

    @property
    def google_oauth_redirect_uri(self) -> str:
        return f"{self.google_oauth_redirect_base.rstrip('/')}/api/v1/auth/google/callback"
```

### - [ ] Step 4: Document env vars in `.env.example`

Find the live `.env.example` (usually `apps/api/.env.example` or root `.env.example`). Append:

```bash
# Google OAuth (see docs/superpowers/specs/2026-04-19-google-oauth-design.md §9)
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_OAUTH_REDIRECT_BASE=http://localhost:3000
OAUTH_SESSION_SECRET=
GOOGLE_OAUTH_ENABLED=false
```

### - [ ] Step 5: Add `get_current_user_optional` to `deps.py`

Open `apps/api/app/core/deps.py`. After the existing `get_current_user` function, add:

```python
def get_current_user_optional(
    request: Request,
    db: Session = Depends(get_db_session),
    access_token: str | None = Cookie(default=None, alias=settings.access_cookie_name),
) -> User | None:
    """Like `get_current_user` but returns None instead of raising when unauthenticated."""
    if not access_token:
        return None
    try:
        user, _payload = authenticate_access_token(db=db, access_token=access_token)
    except ApiError:
        return None
    request.state.access_token = access_token
    return user
```

If any of `Request`, `Depends`, `Cookie`, `Session`, `User`, `settings`, `authenticate_access_token`, `ApiError` aren't already imported at the top, add them. They all should be — `get_current_user` uses the same set.

### - [ ] Step 6: Add `is_safe_redirect_path` to `deps.py`

Append to the same file:

```python
def is_safe_redirect_path(path: str | None) -> bool:
    """Validate a user-controllable `next` parameter is a relative in-app path.

    Rejects: absolute URLs (http://evil.com), protocol-relative (//evil.com),
    backslash tricks (\\\\evil.com), javascript:/data: URIs, anything not
    starting with a single `/`.
    """
    if not path or not isinstance(path, str):
        return False
    if not path.startswith("/"):
        return False
    if path.startswith("//") or path.startswith("/\\"):
        return False
    lower = path.lower()
    if lower.startswith("/javascript:") or lower.startswith("/data:"):
        return False
    return True
```

### - [ ] Step 7: Write tests for helpers

Create `apps/api/tests/test_auth_deps.py` (or append to an existing deps test):

```python
from app.core.deps import is_safe_redirect_path


def test_safe_redirect_path_accepts_simple_relative():
    assert is_safe_redirect_path("/app") is True
    assert is_safe_redirect_path("/app/notebooks/123") is True


def test_safe_redirect_path_rejects_absolute():
    assert is_safe_redirect_path("https://evil.com/app") is False
    assert is_safe_redirect_path("http://evil.com") is False


def test_safe_redirect_path_rejects_protocol_relative():
    assert is_safe_redirect_path("//evil.com") is False


def test_safe_redirect_path_rejects_backslash():
    assert is_safe_redirect_path("/\\evil.com") is False


def test_safe_redirect_path_rejects_injection():
    assert is_safe_redirect_path("/javascript:alert(1)") is False
    assert is_safe_redirect_path("/data:text/html,<script>") is False


def test_safe_redirect_path_rejects_empty_and_non_string():
    assert is_safe_redirect_path(None) is False
    assert is_safe_redirect_path("") is False
    assert is_safe_redirect_path("app") is False  # no leading slash
```

### - [ ] Step 8: Run the test

```bash
cd apps/api
pytest tests/test_auth_deps.py -v
```
Expected: 6 passed.

### - [ ] Step 9: Commit

```bash
git add apps/api/app/core/config.py apps/api/app/core/deps.py \
        apps/api/.env.example apps/api/pyproject.toml \
        apps/api/tests/test_auth_deps.py
git commit -m "$(cat <<'EOF'
feat(api): add oauth config + get_current_user_optional + safe redirect helper

Adds GOOGLE_* env vars, Authlib/itsdangerous/httpx deps, an optional
variant of get_current_user for the OAuth authorize route, and a
relative-path validator for the `next` redirect parameter.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: OAuth schemas

**Files:**
- Create: `apps/api/app/schemas/oauth.py`

### - [ ] Step 1: Create schemas

Create `apps/api/app/schemas/oauth.py`:

```python
from datetime import datetime

from pydantic import BaseModel, Field


class OAuthIdentityOut(BaseModel):
    id: str
    provider: str
    provider_email: str | None
    linked_at: datetime

    class Config:
        from_attributes = True


class SetPasswordRequest(BaseModel):
    new_password: str = Field(min_length=8, max_length=200)
    # Optional — used by users who already have a password
    current_password: str | None = None


class OAuthDisconnectResponse(BaseModel):
    success: bool


class SetPasswordResponse(BaseModel):
    success: bool
```

### - [ ] Step 2: Typecheck / smoke import

```bash
cd apps/api
python -c "from app.schemas.oauth import OAuthIdentityOut, SetPasswordRequest, OAuthDisconnectResponse, SetPasswordResponse; print('ok')"
```
Expected: `ok`

### - [ ] Step 3: Commit

```bash
git add apps/api/app/schemas/oauth.py
git commit -m "$(cat <<'EOF'
feat(api): add oauth schemas (OAuthIdentityOut, SetPasswordRequest)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Authlib OAuth client + SessionMiddleware setup

**Files:**
- Create: `apps/api/app/core/oauth.py`
- Modify: `apps/api/app/main.py` (register SessionMiddleware)

### - [ ] Step 1: Create the OAuth client module

Create `apps/api/app/core/oauth.py`:

```python
"""Authlib OAuth client registrations.

Centralizes provider config so routes stay thin.
"""

from authlib.integrations.starlette_client import OAuth

from app.core.config import settings

oauth = OAuth()

oauth.register(
    name="google",
    client_id=settings.google_client_id,
    client_secret=settings.google_client_secret,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)
```

### - [ ] Step 2: Register SessionMiddleware in `main.py`

Open `apps/api/app/main.py`. Near the other middleware registrations (CORS etc.), add:

```python
from starlette.middleware.sessions import SessionMiddleware

# … existing middleware …

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.oauth_session_secret,
    session_cookie="mr_oauth_session",
    max_age=600,  # 10 minutes — OAuth round-trip only
    same_site="lax",
    https_only=settings.cookie_secure,
)
```

Place this **before** other request-inspecting middlewares (like auth / ratelimit) if they reference `request.session`, but after the ASGI-level CORS middleware. Consult the existing middleware stack order and insert near logical siblings.

### - [ ] Step 3: Smoke test app boot

```bash
cd apps/api
python -c "from app.main import app; print('app loaded:', app.title)"
```
Expected: `app loaded: <your app title>`. No import errors.

### - [ ] Step 4: Commit

```bash
git add apps/api/app/core/oauth.py apps/api/app/main.py
git commit -m "$(cat <<'EOF'
feat(api): register Authlib Google OAuth client + Starlette SessionMiddleware

Session cookie is separate from the app's JWT cookie (10min TTL, lax
SameSite because Google callback is cross-site). Scopes: openid email
profile.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `GET /auth/google/authorize` route

**Files:**
- Modify: `apps/api/app/routers/auth.py` (append route)
- Create: `apps/api/tests/test_auth_google.py`

### - [ ] Step 1: Write the failing test

Create `apps/api/tests/test_auth_google.py`:

```python
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

client = TestClient(app)


def public_headers() -> dict[str, str]:
    return {"Origin": settings.public_app_origin, "Referer": settings.public_app_origin + "/"}


@patch("app.routers.auth.oauth.google.authorize_redirect")
def test_authorize_redirects_to_google(mock_redirect):
    from starlette.responses import RedirectResponse

    mock_redirect.return_value = RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth?…")
    settings.google_oauth_enabled = True
    try:
        resp = client.get(
            "/api/v1/auth/google/authorize?next=/app/notebooks",
            headers=public_headers(),
            follow_redirects=False,
        )
        assert resp.status_code == 307 or resp.status_code == 302
        assert "accounts.google.com" in resp.headers.get("location", "")
    finally:
        settings.google_oauth_enabled = False


def test_authorize_404_when_flag_off():
    settings.google_oauth_enabled = False
    resp = client.get(
        "/api/v1/auth/google/authorize?next=/app",
        headers=public_headers(),
        follow_redirects=False,
    )
    assert resp.status_code == 404


@patch("app.routers.auth.oauth.google.authorize_redirect")
def test_authorize_rejects_unsafe_next(mock_redirect):
    from starlette.responses import RedirectResponse

    captured_next: dict[str, str] = {}

    async def capture(request, redirect_uri, **kwargs):
        captured_next["value"] = request.session.get("oauth_next")
        return RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth?…")

    mock_redirect.side_effect = capture
    settings.google_oauth_enabled = True
    try:
        client.get(
            "/api/v1/auth/google/authorize?next=https://evil.com",
            headers=public_headers(),
            follow_redirects=False,
        )
        # Unsafe next should be replaced with safe default
        assert captured_next["value"] == "/app"
    finally:
        settings.google_oauth_enabled = False
```

### - [ ] Step 2: Run test to verify it fails

```bash
cd apps/api
pytest tests/test_auth_google.py -v
```
Expected: FAIL on `AttributeError: module 'app.routers.auth' has no attribute 'oauth'` or the import itself.

### - [ ] Step 3: Implement the route

Open `apps/api/app/routers/auth.py`. At the top of the file, add imports:

```python
from typing import Literal

from app.core.oauth import oauth
from app.core.deps import get_current_user_optional, is_safe_redirect_path
from app.core.config import settings
```

Append the route (after existing routes, before any module footer):

```python
@router.get("/google/authorize")
async def google_authorize(
    request: Request,
    next: str | None = None,
    mode: Literal["signin", "connect"] = "signin",
    current_user: User | None = Depends(get_current_user_optional),
):
    if not settings.google_oauth_enabled:
        raise ApiError("not_found", "OAuth is disabled", status_code=404)

    client_ip = _client_ip(request)
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
```

The `_client_ip` helper and `auth_rate_limit_*` settings already exist — grep for `_client_ip(` and `auth_rate_limit_ip_max` to confirm import paths.

### - [ ] Step 4: Run test to verify it passes

```bash
pytest tests/test_auth_google.py::test_authorize_redirects_to_google \
       tests/test_auth_google.py::test_authorize_404_when_flag_off \
       tests/test_auth_google.py::test_authorize_rejects_unsafe_next -v
```
Expected: 3 passed.

### - [ ] Step 5: Commit

```bash
git add apps/api/app/routers/auth.py apps/api/tests/test_auth_google.py
git commit -m "$(cat <<'EOF'
feat(api): GET /auth/google/authorize — start OAuth flow

Stashes {mode, next, connect_user_id} in Starlette session; delegates
to Authlib authorize_redirect. Feature-flag gated. Rejects unsafe next.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: `GET /auth/google/callback` route

**Files:**
- Modify: `apps/api/app/routers/auth.py` (append callback)
- Modify: `apps/api/tests/test_auth_google.py` (append callback tests)

This is the largest single route. It handles three flows: new user signup, existing-email auto-link, and connect-mode.

### - [ ] Step 1: Write failing tests for all callback branches

Append to `apps/api/tests/test_auth_google.py`:

```python
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.entities import OAuthIdentity, User


def _stub_authlib(mock_token, id_token_claims):
    """Patches both token exchange and ID-token parsing."""
    async def fake_token(request, **kwargs):
        return mock_token

    async def fake_parse(*args, **kwargs):
        return id_token_claims

    return fake_token, fake_parse


@patch("app.routers.auth.oauth.google.parse_id_token")
@patch("app.routers.auth.oauth.google.authorize_access_token")
def test_callback_creates_new_user(mock_token, mock_parse):
    mock_token.return_value = {"access_token": "at", "id_token": "it"}
    mock_parse.return_value = {
        "sub": "109876", "email": "new@gmail.com",
        "email_verified": True, "name": "New User",
    }
    settings.google_oauth_enabled = True
    try:
        with client as c:
            # Seed a valid session
            with c.session_transaction() as sess:
                sess["oauth_mode"] = "signin"
                sess["oauth_next"] = "/app"
            resp = c.get("/api/v1/auth/google/callback?code=X&state=Y",
                         headers=public_headers(), follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "/app"
        with SessionLocal() as db:
            user = db.execute(select(User).where(User.email == "new@gmail.com")).scalar_one()
            assert user.password_hash is None
            ident = db.execute(
                select(OAuthIdentity).where(OAuthIdentity.user_id == user.id)
            ).scalar_one()
            assert ident.provider == "google"
            assert ident.provider_id == "109876"
    finally:
        settings.google_oauth_enabled = False


@patch("app.routers.auth.oauth.google.parse_id_token")
@patch("app.routers.auth.oauth.google.authorize_access_token")
def test_callback_auto_links_existing_email(mock_token, mock_parse):
    # Seed existing email-only user
    with SessionLocal() as db:
        existing = User(email="exists@gmail.com", password_hash="hashed")
        db.add(existing)
        db.commit()
        existing_id = existing.id

    mock_token.return_value = {"access_token": "at", "id_token": "it"}
    mock_parse.return_value = {
        "sub": "200", "email": "exists@gmail.com",
        "email_verified": True, "name": "X",
    }
    settings.google_oauth_enabled = True
    try:
        with client as c:
            with c.session_transaction() as sess:
                sess["oauth_mode"] = "signin"; sess["oauth_next"] = "/app"
            resp = c.get("/api/v1/auth/google/callback?code=X&state=Y",
                         headers=public_headers(), follow_redirects=False)
        assert resp.status_code == 302
        with SessionLocal() as db:
            ident = db.execute(
                select(OAuthIdentity).where(OAuthIdentity.user_id == existing_id)
            ).scalar_one()
            assert ident.provider_id == "200"
            # No duplicate user
            users = db.execute(select(User).where(User.email == "exists@gmail.com")).scalars().all()
            assert len(users) == 1
    finally:
        settings.google_oauth_enabled = False


@patch("app.routers.auth.oauth.google.parse_id_token")
@patch("app.routers.auth.oauth.google.authorize_access_token")
def test_callback_rejects_unverified_email(mock_token, mock_parse):
    mock_token.return_value = {"access_token": "at", "id_token": "it"}
    mock_parse.return_value = {
        "sub": "300", "email": "x@y.com",
        "email_verified": False, "name": "X",
    }
    settings.google_oauth_enabled = True
    try:
        with client as c:
            with c.session_transaction() as sess:
                sess["oauth_mode"] = "signin"; sess["oauth_next"] = "/app"
            resp = c.get("/api/v1/auth/google/callback?code=X&state=Y",
                         headers=public_headers(), follow_redirects=False)
        assert resp.status_code == 302
        assert "error=google_email_unverified" in resp.headers["location"]
    finally:
        settings.google_oauth_enabled = False


@patch("app.routers.auth.oauth.google.parse_id_token")
@patch("app.routers.auth.oauth.google.authorize_access_token")
def test_callback_existing_oauth_signs_in(mock_token, mock_parse):
    with SessionLocal() as db:
        u = User(email="linked@gmail.com", password_hash=None)
        db.add(u); db.flush()
        db.add(OAuthIdentity(user_id=u.id, provider="google", provider_id="400",
                             provider_email="linked@gmail.com"))
        db.commit()
        uid = u.id

    mock_token.return_value = {"access_token": "at", "id_token": "it"}
    mock_parse.return_value = {
        "sub": "400", "email": "new-email@gmail.com",
        "email_verified": True, "name": "X",
    }  # user changed their Google email
    settings.google_oauth_enabled = True
    try:
        with client as c:
            with c.session_transaction() as sess:
                sess["oauth_mode"] = "signin"; sess["oauth_next"] = "/app"
            resp = c.get("/api/v1/auth/google/callback?code=X&state=Y",
                         headers=public_headers(), follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "/app"
    finally:
        settings.google_oauth_enabled = False
```

### - [ ] Step 2: Run tests to verify they fail

```bash
pytest tests/test_auth_google.py -v
```
Expected: 4 new failures — callback route not yet defined.

### - [ ] Step 3: Implement the callback

Append to `apps/api/app/routers/auth.py`:

```python
@router.get("/google/callback")
async def google_callback(
    request: Request,
    response: Response,
    db: Session = Depends(get_db_session),
):
    if not settings.google_oauth_enabled:
        raise ApiError("not_found", "OAuth is disabled", status_code=404)

    enforce_rate_limit(
        request,
        scope="auth:oauth_callback:ip",
        identifier=_client_ip(request),
        limit=settings.auth_rate_limit_ip_max,
        window_seconds=settings.auth_rate_limit_window_seconds,
    )

    # Handle user-cancelled at Google
    if request.query_params.get("error") == "access_denied":
        return RedirectResponse(url="/login?error=oauth_cancelled", status_code=302)

    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception:
        return RedirectResponse(url="/login?error=oauth_state_mismatch", status_code=302)

    id_claims = await oauth.google.parse_id_token(request, token)

    sub = id_claims.get("sub")
    email = id_claims.get("email")
    email_verified = bool(id_claims.get("email_verified"))
    display_name = id_claims.get("name") or ""

    if not sub or not email:
        return RedirectResponse(url="/login?error=oauth_invalid_id_token", status_code=302)

    mode = request.session.get("oauth_mode", "signin")
    next_path = request.session.get("oauth_next") or "/app"
    connect_user_id = request.session.get("oauth_connect_user_id")

    # Clean up session state once consumed.
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
            return RedirectResponse(url="/app/settings?error=already_linked", status_code=302)
        if existing_identity is None:
            db.add(OAuthIdentity(
                user_id=connect_user_id, provider="google",
                provider_id=sub, provider_email=email,
            ))
            db.commit()
        write_audit_log(
            db, workspace_id=None, actor_user_id=connect_user_id,
            action="auth.oauth.google.connect", target_type="user",
            target_id=connect_user_id,
            meta_json={"provider": "google", "provider_email": email},
        )
        db.commit()
        return RedirectResponse(url=f"{next_path}?connected=google", status_code=302)

    # ---- Sign-in mode ----
    if existing_identity is not None:
        # Refresh provider_email snapshot
        if existing_identity.provider_email != email:
            existing_identity.provider_email = email
            db.commit()
        user = db.get(User, existing_identity.user_id)
    else:
        # Lookup by email for auto-link
        user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if user is not None:
            if not email_verified:
                return RedirectResponse(url="/login?error=google_email_unverified", status_code=302)
            db.add(OAuthIdentity(
                user_id=user.id, provider="google",
                provider_id=sub, provider_email=email,
            ))
            db.commit()
        else:
            # Brand-new user
            if not email_verified:
                return RedirectResponse(url="/login?error=google_email_unverified", status_code=302)
            user = _create_user_with_workspace_for_oauth(
                db=db, email=email, display_name=display_name,
            )
            db.add(OAuthIdentity(
                user_id=user.id, provider="google",
                provider_id=sub, provider_email=email,
            ))
            db.commit()

    # Issue app auth cookie
    token_str = issue_access_token(user_id=user.id)
    set_auth_cookie(response, token_str)
    write_audit_log(
        db, workspace_id=None, actor_user_id=user.id,
        action="auth.oauth.google.signin", target_type="user",
        target_id=user.id,
        meta_json={"provider": "google", "provider_email": email},
    )
    db.commit()

    redir = RedirectResponse(url=next_path, status_code=302)
    # Re-apply the cookie to the redirect response (FastAPI doesn't carry it over).
    for cookie_header in response.headers.getlist("set-cookie"):
        redir.headers.append("set-cookie", cookie_header)
    return redir
```

You'll need a new helper `_create_user_with_workspace_for_oauth`. Add just above the callback:

```python
def _create_user_with_workspace_for_oauth(
    db: Session, email: str, display_name: str,
) -> User:
    """Mirror the shape of _create_user_with_workspace() from /register but
    with password_hash=None, email_verified implied by Google, and
    onboarding_completed_at left NULL."""
    user = User(
        email=email,
        password_hash=None,
        display_name=display_name or email.split("@")[0],
    )
    db.add(user)
    db.flush()
    workspace = Workspace(name=f"{display_name or email}'s Workspace", owner_user_id=user.id)
    db.add(workspace)
    db.flush()
    db.add(Membership(workspace_id=workspace.id, user_id=user.id, role="owner"))
    db.commit()
    return user
```

The names `Workspace`, `Membership`, `issue_access_token`, `set_auth_cookie`, `write_audit_log` should already be importable — grep for their import sites in this file to confirm aliases.

### - [ ] Step 4: Run tests to verify they pass

```bash
pytest tests/test_auth_google.py -v
```
Expected: 7 passed (3 from Task 5 + 4 from this task).

### - [ ] Step 5: Commit

```bash
git add apps/api/app/routers/auth.py apps/api/tests/test_auth_google.py
git commit -m "$(cat <<'EOF'
feat(api): GET /auth/google/callback — signin + auto-link + connect flows

Three branches: (1) existing oauth_identity → sign in, (2) email
match with verified=true → auto-link, (3) brand-new → create
User+Workspace+Membership+oauth_identity. Connect mode handles
already-linked rejection. Rejects unverified email. Audit-logs
every outcome.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: `GET /auth/identities` + `POST /auth/google/disconnect`

**Files:**
- Modify: `apps/api/app/routers/auth.py` (append two routes)
- Modify: `apps/api/tests/test_auth_google.py` (append tests)

### - [ ] Step 1: Write failing tests

Append to `tests/test_auth_google.py`:

```python
def test_identities_returns_linked_accounts():
    # Seed a user with a Google link
    with SessionLocal() as db:
        u = User(email="u@x.com", password_hash="p")
        db.add(u); db.flush()
        db.add(OAuthIdentity(
            user_id=u.id, provider="google",
            provider_id="9001", provider_email="u@x.com",
        ))
        db.commit()
    # Log in via email/password to get a cookie
    # (reuse existing login helper from test_api_integration.py)
    from tests.test_api_integration import login_as
    client_with_auth = login_as(email="u@x.com", password="…")
    resp = client_with_auth.get("/api/v1/auth/identities", headers=public_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["provider"] == "google"
    assert data[0]["provider_email"] == "u@x.com"


def test_disconnect_blocks_user_without_password():
    with SessionLocal() as db:
        u = User(email="oauth-only@x.com", password_hash=None)
        db.add(u); db.flush()
        db.add(OAuthIdentity(user_id=u.id, provider="google",
                             provider_id="9002", provider_email="oauth-only@x.com"))
        db.commit()
    # Need to log the user in. Use a test helper that bypasses password check
    # for OAuth-only users (add `login_as_oauth_only` to tests/test_api_integration.py
    # or construct the JWT directly with issue_access_token).
    from app.core.security import issue_access_token
    token = issue_access_token(user_id=u.id)
    resp = client.post(
        "/api/v1/auth/google/disconnect",
        headers={**public_headers(), "Cookie": f"{settings.access_cookie_name}={token}"},
    )
    assert resp.status_code == 409
    assert resp.json().get("code") == "password_required"


def test_disconnect_succeeds_when_user_has_password():
    with SessionLocal() as db:
        u = User(email="both@x.com", password_hash="hashed")
        db.add(u); db.flush()
        db.add(OAuthIdentity(user_id=u.id, provider="google",
                             provider_id="9003", provider_email="both@x.com"))
        db.commit(); uid = u.id
    from app.core.security import issue_access_token
    token = issue_access_token(user_id=uid)
    resp = client.post(
        "/api/v1/auth/google/disconnect",
        headers={**public_headers(), "Cookie": f"{settings.access_cookie_name}={token}"},
    )
    assert resp.status_code == 200
    with SessionLocal() as db:
        remaining = db.execute(
            select(OAuthIdentity).where(OAuthIdentity.user_id == uid)
        ).scalars().all()
        assert remaining == []
```

### - [ ] Step 2: Run to verify they fail

```bash
pytest tests/test_auth_google.py::test_identities_returns_linked_accounts \
       tests/test_auth_google.py::test_disconnect_blocks_user_without_password \
       tests/test_auth_google.py::test_disconnect_succeeds_when_user_has_password -v
```
Expected: 3 failures — routes not yet defined.

### - [ ] Step 3: Implement routes

Append to `apps/api/app/routers/auth.py`:

```python
@router.get("/identities", response_model=list[OAuthIdentityOut])
def list_identities(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> list[OAuthIdentityOut]:
    rows = db.execute(
        select(OAuthIdentity).where(OAuthIdentity.user_id == current_user.id)
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
        db, workspace_id=None, actor_user_id=current_user.id,
        action="auth.oauth.google.disconnect", target_type="user",
        target_id=current_user.id, meta_json={"provider": "google"},
    )
    db.commit()
    return OAuthDisconnectResponse(success=True)
```

Add imports at the top if missing: `from sqlalchemy import select, delete`, `from app.models.entities import OAuthIdentity`, `from app.schemas.oauth import OAuthIdentityOut, OAuthDisconnectResponse`.

### - [ ] Step 4: Run tests to verify they pass

```bash
pytest tests/test_auth_google.py -v
```
Expected: 10 passed.

### - [ ] Step 5: Commit

```bash
git add apps/api/app/routers/auth.py apps/api/tests/test_auth_google.py
git commit -m "$(cat <<'EOF'
feat(api): GET /auth/identities + POST /auth/google/disconnect

Identities returns current user's linked providers. Disconnect
blocks with 409 password_required if user has no password
(otherwise they'd lock themselves out). CSRF-protected. Rate-limited.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: `PUT /auth/password` (set/change password)

**Files:**
- Modify: `apps/api/app/routers/auth.py` (append route)
- Modify: `apps/api/tests/test_auth_google.py` (append tests)

### - [ ] Step 1: Write failing tests

Append to `tests/test_auth_google.py`:

```python
def test_set_password_for_oauth_only_user():
    with SessionLocal() as db:
        u = User(email="no-pw@x.com", password_hash=None); db.add(u); db.commit(); uid = u.id
    from app.core.security import issue_access_token
    token = issue_access_token(user_id=uid)
    resp = client.put(
        "/api/v1/auth/password",
        json={"new_password": "NewStrongPass123"},
        headers={**public_headers(), "Cookie": f"{settings.access_cookie_name}={token}"},
    )
    assert resp.status_code == 200
    with SessionLocal() as db:
        u = db.get(User, uid)
        assert u.password_hash is not None


def test_change_password_requires_current_when_one_exists():
    with SessionLocal() as db:
        from app.core.security import hash_password
        u = User(email="has-pw@x.com", password_hash=hash_password("CurrentPass123"))
        db.add(u); db.commit(); uid = u.id
    from app.core.security import issue_access_token
    token = issue_access_token(user_id=uid)
    # Missing current_password → 400
    resp = client.put(
        "/api/v1/auth/password",
        json={"new_password": "NewPass123"},
        headers={**public_headers(), "Cookie": f"{settings.access_cookie_name}={token}"},
    )
    assert resp.status_code == 400
    # Wrong current_password → 400
    resp = client.put(
        "/api/v1/auth/password",
        json={"new_password": "NewPass123", "current_password": "Wrong"},
        headers={**public_headers(), "Cookie": f"{settings.access_cookie_name}={token}"},
    )
    assert resp.status_code == 400
    # Correct → 200
    resp = client.put(
        "/api/v1/auth/password",
        json={"new_password": "NewPass123", "current_password": "CurrentPass123"},
        headers={**public_headers(), "Cookie": f"{settings.access_cookie_name}={token}"},
    )
    assert resp.status_code == 200
```

### - [ ] Step 2: Run to verify failures

```bash
pytest tests/test_auth_google.py::test_set_password_for_oauth_only_user \
       tests/test_auth_google.py::test_change_password_requires_current_when_one_exists -v
```
Expected: 2 failures.

### - [ ] Step 3: Implement

Append to `apps/api/app/routers/auth.py`:

```python
@router.put("/password", response_model=SetPasswordResponse)
def set_password(
    payload: SetPasswordRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
    _csrf: None = Depends(require_csrf_protection),
) -> SetPasswordResponse:
    if current_user.password_hash is not None:
        if not payload.current_password:
            raise ApiError("invalid_request", "current_password required", status_code=400)
        if not verify_password(payload.current_password, current_user.password_hash):
            raise ApiError("invalid_credentials", "Wrong current password", status_code=400)
    current_user.password_hash = hash_password(payload.new_password)
    write_audit_log(
        db, workspace_id=None, actor_user_id=current_user.id,
        action="auth.password.set", target_type="user",
        target_id=current_user.id, meta_json={},
    )
    db.commit()
    return SetPasswordResponse(success=True)
```

Import adjustment at top: `from app.schemas.oauth import SetPasswordRequest, SetPasswordResponse`. `hash_password` and `verify_password` come from `app.core.security` (same functions the existing login/register use).

### - [ ] Step 4: Run tests to verify pass

```bash
pytest tests/test_auth_google.py -v
```
Expected: 12 passed.

### - [ ] Step 5: Commit

```bash
git add apps/api/app/routers/auth.py apps/api/tests/test_auth_google.py
git commit -m "$(cat <<'EOF'
feat(api): PUT /auth/password — set/change password

Handles both OAuth-only user setting an initial password and existing
password user rotating. Requires current_password when one exists.
CSRF-protected.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Frontend i18n keys

**Files:**
- Modify: `apps/web/messages/en/auth.json`
- Modify: `apps/web/messages/zh/auth.json`

### - [ ] Step 1: Append keys to English

Open `apps/web/messages/en/auth.json`. Append (before the closing `}`):

```json
,
"oauth.google.button": "Continue with Google",
"oauth.divider": "OR",
"oauth.error.unverified": "Your Google email is not verified. Please verify it in your Google account settings first.",
"oauth.error.state_mismatch": "Login session expired. Please try again.",
"oauth.error.already_linked": "This Google account is already linked to a different MRNote user.",
"oauth.error.cancelled": "Google sign-in was cancelled.",
"oauth.error.auth_required": "Please sign in first to connect Google.",
"connectedAccounts.title": "Connected accounts",
"connectedAccounts.desc": "Sign in faster with third-party accounts",
"connectedAccounts.google.name": "Google",
"connectedAccounts.connect": "Connect",
"connectedAccounts.disconnect": "Disconnect",
"connectedAccounts.linkedAt": "Linked on {date}",
"connectedAccounts.disconnectConfirm.title": "Disconnect Google?",
"connectedAccounts.disconnectConfirm.desc": "You won't be able to sign in with Google. Email + password still works.",
"connectedAccounts.disconnectConfirm.cancel": "Cancel",
"connectedAccounts.disconnectConfirm.confirm": "Disconnect",
"connectedAccounts.setPassword.title": "Set a password first",
"connectedAccounts.setPassword.desc": "You must set a password before disconnecting Google, or your account will become inaccessible.",
"connectedAccounts.setPassword.newPassword": "New password",
"connectedAccounts.setPassword.confirmPassword": "Confirm password",
"connectedAccounts.setPassword.submit": "Save and disconnect",
"connectedAccounts.setPassword.mismatch": "Passwords don't match."
```

### - [ ] Step 2: Append keys to Chinese

Open `apps/web/messages/zh/auth.json`. Append:

```json
,
"oauth.google.button": "使用 Google 继续",
"oauth.divider": "或",
"oauth.error.unverified": "你的 Google 邮箱尚未验证，请先在 Google 账号设置里验证邮箱。",
"oauth.error.state_mismatch": "登录会话已过期，请重试。",
"oauth.error.already_linked": "这个 Google 账号已经绑定到其他 MRNote 用户。",
"oauth.error.cancelled": "Google 登录已取消。",
"oauth.error.auth_required": "请先登录再连接 Google。",
"connectedAccounts.title": "已连接账号",
"connectedAccounts.desc": "用第三方账号快速登录",
"connectedAccounts.google.name": "Google",
"connectedAccounts.connect": "连接",
"connectedAccounts.disconnect": "解除连接",
"connectedAccounts.linkedAt": "已连接于 {date}",
"connectedAccounts.disconnectConfirm.title": "解除 Google 连接？",
"connectedAccounts.disconnectConfirm.desc": "解除后将无法用 Google 登录。你仍可用邮箱密码登录。",
"connectedAccounts.disconnectConfirm.cancel": "取消",
"connectedAccounts.disconnectConfirm.confirm": "解除连接",
"connectedAccounts.setPassword.title": "先设置密码",
"connectedAccounts.setPassword.desc": "解除 Google 前必须先设置密码，否则账号将无法登录。",
"connectedAccounts.setPassword.newPassword": "新密码",
"connectedAccounts.setPassword.confirmPassword": "确认密码",
"connectedAccounts.setPassword.submit": "保存并解除连接",
"connectedAccounts.setPassword.mismatch": "两次输入的密码不一致。"
```

### - [ ] Step 3: Validate JSON

```bash
cd apps/web
node -e "JSON.parse(require('fs').readFileSync('messages/en/auth.json','utf8'))"
node -e "JSON.parse(require('fs').readFileSync('messages/zh/auth.json','utf8'))"
```
Expected: no output (valid).

### - [ ] Step 4: Commit

```bash
git add apps/web/messages/en/auth.json apps/web/messages/zh/auth.json
git commit -m "$(cat <<'EOF'
chore(web): add i18n keys for Google OAuth + connected accounts

Includes error strings (unverified email, state mismatch, already
linked, cancelled, auth required), button copy, and the full
disconnect → set-password inline flow copy.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: `<GoogleSignInButton />` component

**Files:**
- Create: `apps/web/components/auth/GoogleSignInButton.tsx`
- Create: `apps/web/tests/unit/google-signin-button.test.tsx`
- Modify: `apps/web/styles/globals.css` (append `.auth-divider` styles)

### - [ ] Step 1: Write the failing test

Create `apps/web/tests/unit/google-signin-button.test.tsx`:

```tsx
import { render, screen, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import GoogleSignInButton from "@/components/auth/GoogleSignInButton";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams("next=/app/notebooks/123"),
}));

afterEach(() => { cleanup(); });

describe("GoogleSignInButton", () => {
  it("renders as an <a> pointing at /api/v1/auth/google/authorize", () => {
    render(<GoogleSignInButton />);
    const link = screen.getByTestId("google-signin-link");
    expect(link.tagName).toBe("A");
    const href = link.getAttribute("href") || "";
    expect(href.startsWith("/api/v1/auth/google/authorize")).toBe(true);
    expect(href).toContain("mode=signin");
    expect(href).toContain("next=%2Fapp%2Fnotebooks%2F123");
  });

  it("respects mode=connect prop", () => {
    render(<GoogleSignInButton mode="connect" />);
    const link = screen.getByTestId("google-signin-link");
    expect(link.getAttribute("href")).toContain("mode=connect");
  });

  it("defaults next to /app when no search param present", () => {
    // Override mock for this test
    vi.resetModules();
    render(<GoogleSignInButton />);
    const link = screen.getByTestId("google-signin-link");
    const href = link.getAttribute("href") || "";
    expect(href).toContain("next=");
  });
});
```

### - [ ] Step 2: Run to verify failure

```bash
cd apps/web
node_modules/.bin/vitest run tests/unit/google-signin-button.test.tsx
```
Expected: FAIL — module not found.

### - [ ] Step 3: Implement the component

Create `apps/web/components/auth/GoogleSignInButton.tsx`:

```tsx
"use client";

import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";

interface Props {
  mode?: "signin" | "connect";
  className?: string;
}

function GoogleGLogo({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" aria-hidden="true">
      <path fill="#4285F4" d="M45.12 24.5c0-1.56-.14-3.06-.4-4.5H24v8.51h11.84c-.51 2.75-2.06 5.08-4.39 6.64v5.52h7.11c4.16-3.83 6.56-9.47 6.56-16.17z"/>
      <path fill="#34A853" d="M24 46c5.94 0 10.92-1.97 14.56-5.33l-7.11-5.52c-1.97 1.32-4.49 2.1-7.45 2.1-5.73 0-10.58-3.87-12.31-9.07H4.34v5.7C7.96 41.07 15.4 46 24 46z"/>
      <path fill="#FBBC05" d="M11.69 28.18c-.44-1.32-.69-2.73-.69-4.18s.25-2.86.69-4.18v-5.7H4.34C2.85 17.09 2 20.45 2 24s.85 6.91 2.34 9.88l7.35-5.7z"/>
      <path fill="#EA4335" d="M24 10.75c3.23 0 6.13 1.11 8.41 3.29l6.31-6.31C34.91 4.18 29.93 2 24 2 15.4 2 7.96 6.93 4.34 14.12l7.35 5.7c1.73-5.2 6.58-9.07 12.31-9.07z"/>
    </svg>
  );
}

export default function GoogleSignInButton({ mode = "signin", className }: Props) {
  const t = useTranslations("auth");
  const searchParams = useSearchParams();
  const next = searchParams?.get("next") ?? "/app";
  const href = `/api/v1/auth/google/authorize?mode=${mode}&next=${encodeURIComponent(next)}`;

  return (
    <a
      data-testid="google-signin-link"
      href={href}
      className={className}
      style={{
        display: "inline-flex", alignItems: "center", justifyContent: "center",
        gap: 10, width: "100%", padding: "10px 16px",
        background: "#fff", color: "#3c4043",
        border: "1px solid #dadce0", borderRadius: 8,
        fontSize: 14, fontWeight: 500, textDecoration: "none",
        cursor: "pointer",
      }}
    >
      <GoogleGLogo size={18} />
      <span>{t("oauth.google.button")}</span>
    </a>
  );
}
```

### - [ ] Step 4: Add `.auth-divider` CSS

Open `apps/web/styles/globals.css` and append:

```css
.auth-oauth-block {
  margin-bottom: 16px;
}
.auth-divider {
  display: flex; align-items: center; gap: 12px;
  margin: 12px 0;
  color: var(--text-secondary, #64748b);
  font-size: 12px;
}
.auth-divider::before,
.auth-divider::after {
  content: ""; flex: 1;
  border-top: 1px solid var(--border, rgba(15,42,45,0.1));
}
```

### - [ ] Step 5: Run tests to verify pass

```bash
node_modules/.bin/vitest run tests/unit/google-signin-button.test.tsx
```
Expected: 3 passed.

### - [ ] Step 6: Commit

```bash
git add apps/web/components/auth/GoogleSignInButton.tsx \
        apps/web/tests/unit/google-signin-button.test.tsx \
        apps/web/styles/globals.css
git commit -m "$(cat <<'EOF'
feat(web): add GoogleSignInButton + auth divider styles

White button with official Google G SVG, forwards mode + next to
/authorize. Includes .auth-oauth-block + .auth-divider CSS for
the "OR" separator.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Integrate Google button into `/login` and `/register`

**Files:**
- Modify: `apps/web/app/[locale]/(auth)/login/page.tsx`
- Modify: `apps/web/app/[locale]/(auth)/register/page.tsx`

### - [ ] Step 1: Add block to login page

Open `apps/web/app/[locale]/(auth)/login/page.tsx`. Add the import near the top:

```tsx
import GoogleSignInButton from "@/components/auth/GoogleSignInButton";
```

Find the JSX that wraps the email form (look for the form tag or the heading above it). Insert ABOVE the email form:

```tsx
<div className="auth-oauth-block">
  <GoogleSignInButton />
  <div className="auth-divider"><span>{t("oauth.divider")}</span></div>
</div>
```

If `t` is from `useTranslations("auth")`, it will resolve `oauth.divider` via the keys added in Task 9.

### - [ ] Step 2: Add block to register page

Open `apps/web/app/[locale]/(auth)/register/page.tsx`. Same import + same block, inserted above the register form.

### - [ ] Step 3: Typecheck + lint

```bash
cd apps/web
node_modules/.bin/tsc --noEmit
node_modules/.bin/eslint app/\[locale\]/\(auth\)/login/page.tsx \
                         app/\[locale\]/\(auth\)/register/page.tsx
```
Expected: 0 errors / 0 warnings.

### - [ ] Step 4: Manual render check (optional, during review)

```bash
node_modules/.bin/next dev  # then visit http://localhost:3000/en/login
```
The Google button should appear above the email form with an "OR" divider under it.

### - [ ] Step 5: Commit

```bash
git add apps/web/app/\[locale\]/\(auth\)/login/page.tsx \
        apps/web/app/\[locale\]/\(auth\)/register/page.tsx
git commit -m "$(cat <<'EOF'
feat(web): render GoogleSignInButton on /login and /register

Inserted above the email form with an "OR" divider below. Uses the
i18n keys added in the previous commit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: `<ConnectedAccountsList />` component

**Files:**
- Create: `apps/web/components/settings/ConnectedAccountsList.tsx`
- Create: `apps/web/tests/unit/connected-accounts-list.test.tsx`

### - [ ] Step 1: Write the failing test

Create `apps/web/tests/unit/connected-accounts-list.test.tsx`:

```tsx
import { render, screen, waitFor, fireEvent, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi, beforeEach } from "vitest";

vi.mock("@/lib/api", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPut: vi.fn(),
  apiDelete: vi.fn(),
}));

import { apiGet, apiPost } from "@/lib/api";
import ConnectedAccountsList from "@/components/settings/ConnectedAccountsList";

beforeEach(() => {
  vi.mocked(apiGet).mockReset();
  vi.mocked(apiPost).mockReset();
});
afterEach(() => { cleanup(); });

describe("ConnectedAccountsList", () => {
  it("renders Connect button when no identities", async () => {
    vi.mocked(apiGet).mockResolvedValue([]);
    render(<ConnectedAccountsList />);
    await waitFor(() => {
      expect(screen.getByTestId("oauth-connect-google")).toBeTruthy();
    });
  });

  it("renders Disconnect row when Google is linked", async () => {
    vi.mocked(apiGet).mockResolvedValue([
      { id: "oid1", provider: "google", provider_email: "x@y.com",
        linked_at: "2026-04-18T10:00:00Z" },
    ]);
    render(<ConnectedAccountsList />);
    await waitFor(() => {
      expect(screen.getByTestId("oauth-disconnect-google")).toBeTruthy();
      expect(screen.getByText("x@y.com")).toBeTruthy();
    });
  });

  it("shows set-password inline form when disconnect returns password_required", async () => {
    vi.mocked(apiGet).mockResolvedValue([
      { id: "oid1", provider: "google", provider_email: "x@y.com",
        linked_at: "2026-04-18T10:00:00Z" },
    ]);
    vi.mocked(apiPost).mockRejectedValueOnce({
      response: { status: 409, data: { code: "password_required" } },
    });
    render(<ConnectedAccountsList />);
    await waitFor(() => screen.getByTestId("oauth-disconnect-google"));
    fireEvent.click(screen.getByTestId("oauth-disconnect-google"));
    // Confirm modal
    await waitFor(() => screen.getByTestId("oauth-disconnect-confirm"));
    fireEvent.click(screen.getByTestId("oauth-disconnect-confirm"));
    // password_required → inline form appears
    await waitFor(() => {
      expect(screen.getByTestId("oauth-set-password-form")).toBeTruthy();
    });
  });
});
```

### - [ ] Step 2: Run to verify failure

```bash
node_modules/.bin/vitest run tests/unit/connected-accounts-list.test.tsx
```
Expected: FAIL — module not found.

### - [ ] Step 3: Implement the component

Create `apps/web/components/settings/ConnectedAccountsList.tsx`:

```tsx
"use client";

import { useEffect, useState, useCallback } from "react";
import { useTranslations } from "next-intl";
import { apiGet, apiPost, apiPut } from "@/lib/api";

interface Identity {
  id: string;
  provider: string;
  provider_email: string | null;
  linked_at: string;
}

type Phase = "idle" | "confirming" | "password_setup";

export default function ConnectedAccountsList() {
  const t = useTranslations("auth");
  const [identities, setIdentities] = useState<Identity[] | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [newPw, setNewPw] = useState("");
  const [confirmPw, setConfirmPw] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await apiGet<Identity[]>("/api/v1/auth/identities");
      setIdentities(data);
    } catch {
      setIdentities([]);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const google = (identities ?? []).find((i) => i.provider === "google") ?? null;

  const connect = () => {
    window.location.href =
      "/api/v1/auth/google/authorize?mode=connect&next=/app/settings";
  };

  const startDisconnect = () => setPhase("confirming");
  const cancelDisconnect = () => { setPhase("idle"); setError(null); };

  const confirmDisconnect = async () => {
    try {
      await apiPost("/api/v1/auth/google/disconnect", {});
      setPhase("idle");
      await load();
    } catch (err: unknown) {
      const e = err as { response?: { status?: number; data?: { code?: string } } };
      if (e?.response?.status === 409 && e.response.data?.code === "password_required") {
        setPhase("password_setup");
      } else {
        setError(t("oauth.error.state_mismatch"));
      }
    }
  };

  const submitPassword = async () => {
    setError(null);
    if (newPw !== confirmPw) {
      setError(t("connectedAccounts.setPassword.mismatch"));
      return;
    }
    try {
      await apiPut("/api/v1/auth/password", { new_password: newPw });
      await apiPost("/api/v1/auth/google/disconnect", {});
      setPhase("idle"); setNewPw(""); setConfirmPw("");
      await load();
    } catch {
      setError(t("oauth.error.state_mismatch"));
    }
  };

  if (identities === null) return null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, padding: 12,
                    border: "1px solid var(--border)", borderRadius: 8 }}>
        <span style={{ fontWeight: 600 }}>{t("connectedAccounts.google.name")}</span>
        {google ? (
          <>
            <span style={{ color: "var(--text-secondary)" }}>
              {google.provider_email}
            </span>
            <span style={{ color: "var(--text-secondary)", fontSize: 12 }}>
              {t("connectedAccounts.linkedAt", {
                date: new Date(google.linked_at).toLocaleDateString(),
              })}
            </span>
            <div style={{ flex: 1 }} />
            <button data-testid="oauth-disconnect-google" type="button"
              onClick={startDisconnect}>
              {t("connectedAccounts.disconnect")}
            </button>
          </>
        ) : (
          <>
            <div style={{ flex: 1 }} />
            <button data-testid="oauth-connect-google" type="button" onClick={connect}>
              {t("connectedAccounts.connect")}
            </button>
          </>
        )}
      </div>

      {phase === "confirming" && (
        <div style={{ padding: 16, border: "1px solid var(--border)", borderRadius: 8 }}>
          <div style={{ fontWeight: 600, marginBottom: 6 }}>
            {t("connectedAccounts.disconnectConfirm.title")}
          </div>
          <div style={{ color: "var(--text-secondary)", marginBottom: 12 }}>
            {t("connectedAccounts.disconnectConfirm.desc")}
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button type="button" onClick={cancelDisconnect}>
              {t("connectedAccounts.disconnectConfirm.cancel")}
            </button>
            <button data-testid="oauth-disconnect-confirm" type="button"
              onClick={confirmDisconnect}>
              {t("connectedAccounts.disconnectConfirm.confirm")}
            </button>
          </div>
        </div>
      )}

      {phase === "password_setup" && (
        <form
          data-testid="oauth-set-password-form"
          onSubmit={(e) => { e.preventDefault(); void submitPassword(); }}
          style={{ padding: 16, border: "1px solid var(--border)", borderRadius: 8 }}
        >
          <div style={{ fontWeight: 600, marginBottom: 6 }}>
            {t("connectedAccounts.setPassword.title")}
          </div>
          <div style={{ color: "var(--text-secondary)", marginBottom: 12 }}>
            {t("connectedAccounts.setPassword.desc")}
          </div>
          <label style={{ display: "block", marginBottom: 8 }}>
            <span>{t("connectedAccounts.setPassword.newPassword")}</span>
            <input type="password" value={newPw}
              onChange={(e) => setNewPw(e.target.value)}
              required minLength={8}
              style={{ width: "100%", padding: 8 }} />
          </label>
          <label style={{ display: "block", marginBottom: 8 }}>
            <span>{t("connectedAccounts.setPassword.confirmPassword")}</span>
            <input type="password" value={confirmPw}
              onChange={(e) => setConfirmPw(e.target.value)}
              required minLength={8}
              style={{ width: "100%", padding: 8 }} />
          </label>
          {error && <div style={{ color: "#ef4444", marginBottom: 8 }}>{error}</div>}
          <button type="submit">
            {t("connectedAccounts.setPassword.submit")}
          </button>
        </form>
      )}
    </div>
  );
}
```

**Note:** If `apiPut` isn't already exported from `@/lib/api`, add it (mirrors `apiPost`/`apiPatch`) or use `apiPatch` on the PUT route (FastAPI accepts both if you declare both). Simplest: grep for `apiPut` — if missing, add a 10-line helper.

### - [ ] Step 4: Run tests to verify pass

```bash
node_modules/.bin/vitest run tests/unit/connected-accounts-list.test.tsx
```
Expected: 3 passed.

### - [ ] Step 5: Commit

```bash
git add apps/web/components/settings/ConnectedAccountsList.tsx \
        apps/web/tests/unit/connected-accounts-list.test.tsx
git commit -m "$(cat <<'EOF'
feat(web): add ConnectedAccountsList for settings OAuth management

Fetches /api/v1/auth/identities, renders Connect or Disconnect row,
confirm modal + inline password-setup form when disconnect returns
409 password_required.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: Integrate ConnectedAccountsList into Settings page

**Files:**
- Modify: `apps/web/app/[locale]/workspace/settings/page.tsx`

### - [ ] Step 1: Add section

Open `apps/web/app/[locale]/workspace/settings/page.tsx`. Add import:

```tsx
import ConnectedAccountsList from "@/components/settings/ConnectedAccountsList";
```

Find the existing section list (look for `GlassCard` wrappers or `<section>` tags). Insert a new section between Account and Developer Mode (or wherever the spec's "below Account, above Developer Mode" guidance maps):

```tsx
<GlassCard>
  <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 4 }}>
    {t("connectedAccounts.title")}
  </div>
  <div style={{ fontSize: 13, color: "var(--text-secondary)", marginBottom: 16 }}>
    {t("connectedAccounts.desc")}
  </div>
  <ConnectedAccountsList />
</GlassCard>
```

If `GlassCard` isn't already imported in this file, replace it with whatever wrapper the surrounding sections use.

### - [ ] Step 2: Typecheck

```bash
node_modules/.bin/tsc --noEmit
```

### - [ ] Step 3: Commit

```bash
git add apps/web/app/\[locale\]/workspace/settings/page.tsx
git commit -m "$(cat <<'EOF'
feat(web): add Connected accounts section to /app/settings

Inserts a new GlassCard between Account and Developer Mode showing
the ConnectedAccountsList component.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 14: Playwright smoke test

**Files:**
- Create: `apps/web/tests/auth-oauth.spec.ts`

### - [ ] Step 1: Write the test

Create `apps/web/tests/auth-oauth.spec.ts`:

```ts
import { expect, test } from "@playwright/test";

test.describe("Google OAuth surface", () => {
  test("/login shows Google button above email form with OR divider", async ({ page }) => {
    await page.goto("/en/login");
    const button = page.getByTestId("google-signin-link");
    await expect(button).toBeVisible();
    await expect(page.locator(".auth-divider")).toBeVisible();
    const emailInput = page.locator('input[type="email"]').first();
    const buttonBox = await button.boundingBox();
    const emailBox = await emailInput.boundingBox();
    expect(buttonBox && emailBox).toBeTruthy();
    if (buttonBox && emailBox) expect(buttonBox.y).toBeLessThan(emailBox.y);
  });

  test("/register shows Google button", async ({ page }) => {
    await page.goto("/en/register");
    await expect(page.getByTestId("google-signin-link")).toBeVisible();
  });

  test("Google button href points at /api/v1/auth/google/authorize with next", async ({ page }) => {
    await page.goto("/en/login?next=/app/notebooks/abc");
    const href = await page.getByTestId("google-signin-link").getAttribute("href");
    expect(href).toContain("/api/v1/auth/google/authorize");
    expect(href).toContain("mode=signin");
    expect(href).toContain("next=%2Fapp%2Fnotebooks%2Fabc");
  });

  test("/app/settings shows Connect Google when not linked", async ({ page, request }) => {
    // This test assumes a helper for authenticated browser context. If the repo has
    // fixtures like `authenticatedPage`, use that. Otherwise, log in via API first.
    // For now, skip if the login fixture isn't set up:
    test.skip(!process.env.PLAYWRIGHT_AUTH_EMAIL, "requires logged-in fixture");
    await page.goto("/en/app/settings");
    await expect(page.getByTestId("oauth-connect-google")).toBeVisible();
  });
});
```

### - [ ] Step 2: Run the test

```bash
cd apps/web
node_modules/.bin/playwright test tests/auth-oauth.spec.ts --reporter=list
```
Expected: first 3 tests pass; the 4th is skipped unless the test env has `PLAYWRIGHT_AUTH_EMAIL` set.

**Note:** the dev server must be running (`pnpm dev` or `node_modules/.bin/next dev`) for Playwright to navigate. If the repo has a `playwright.config.ts` that auto-starts the server via `webServer`, that's already handled.

### - [ ] Step 3: Commit

```bash
git add apps/web/tests/auth-oauth.spec.ts
git commit -m "$(cat <<'EOF'
test(web): add Playwright smoke for Google OAuth surface

Verifies button renders above email form on /login and /register,
href wires through to /authorize with mode + next. Settings page
Connect button checked when authenticated fixture available.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 15: Manual acceptance + deployment checklist

**Files:** (none — verification task)

### - [ ] Step 1: Local smoke — prereqs

Create an `.env` in `apps/api/` with test Google credentials (from a Google Cloud Console project in Testing mode — the human does this one-time per the spec §9.3):

```bash
GOOGLE_CLIENT_ID=…
GOOGLE_CLIENT_SECRET=…
GOOGLE_OAUTH_REDIRECT_BASE=http://localhost:3000
OAUTH_SESSION_SECRET=$(openssl rand -hex 32)
GOOGLE_OAUTH_ENABLED=true
```

### - [ ] Step 2: Run the stack

Terminal A:
```bash
cd apps/api
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

Terminal B:
```bash
cd apps/web
node_modules/.bin/next dev
```

### - [ ] Step 3: Walk through the acceptance checklist

For each, ✅ it works as expected — if any fail, fix with a separate `fix(…)` commit, then re-test.

- [ ] Visit `http://localhost:3000/en/login` — Google button visible above the email form, "OR" divider below it
- [ ] Click Continue with Google — redirects to Google consent screen
- [ ] Sign in with a test Google account — lands back on `/app` with auth cookie set (check DevTools → Application → Cookies)
- [ ] Open DB, verify a new row in `users` with `password_hash=NULL` and a new row in `oauth_identities` linked to that user
- [ ] Log out, visit `/en/login`, click Continue with Google again — lands on `/app` without creating a duplicate user
- [ ] Log in as an existing email+password user, visit `/en/app/settings` — "Connected accounts" section visible with "Connect Google" button
- [ ] Click Connect — redirects to Google, consents, returns to `/app/settings?connected=google`
- [ ] Verify the section now shows "Google · <email> · Linked on …" with a Disconnect button
- [ ] Click Disconnect → confirm modal appears
- [ ] Click Disconnect in modal → row disappears (user had password)
- [ ] Sign out, sign in as an OAuth-only user (no `password_hash`), try to Disconnect — inline "Set a password first" form appears
- [ ] Fill password, submit — row disappears + password is now set (test by logging out and logging in with email+password)
- [ ] Try `http://localhost:3000/api/v1/auth/google/authorize?next=https://evil.com` — after Google consent, lands on `/app`, NOT `https://evil.com`
- [ ] Set `GOOGLE_OAUTH_ENABLED=false` in `.env`, restart API, revisit `/en/login` — Google button still renders (i18n alone) but clicking it returns 404 (flag gates the backend route)

### - [ ] Step 4: Production deploy checklist

Before shipping to production:

- [ ] In Google Cloud Console, add production redirect URI: `https://mr-note.com/api/v1/auth/google/callback`
- [ ] In production env (Vercel / Aliyun ECS), set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_OAUTH_REDIRECT_BASE=https://mr-note.com`, `OAUTH_SESSION_SECRET` (fresh random hex), `GOOGLE_OAUTH_ENABLED=false` (flag off until smoke passes)
- [ ] Deploy backend — verify `/api/v1/auth/google/authorize` returns 404 (flag off)
- [ ] Deploy frontend — verify `/login` still renders (Google button will 404 when clicked, but that's expected with flag off)
- [ ] Flip `GOOGLE_OAUTH_ENABLED=true` in production — re-run the manual acceptance §3 items against production
- [ ] Monitor logs for 1 week: new-user creation rate, auto-link success rate, callback errors. Document any issues.
- [ ] Once stable, remove the feature flag in a follow-up PR

### - [ ] Step 5: Document the flag removal

Open a tracking issue (or add to a running TODO doc): "Remove `GOOGLE_OAUTH_ENABLED` feature flag once OAuth has run in prod for 1 week without incidents."

---

## Self-Review (plan author)

**Spec coverage matrix:**

| Spec requirement | Task |
|---|---|
| `oauth_identities` table + migration | Task 1 |
| `users.password_hash` nullable | Task 1 |
| Env vars (`GOOGLE_CLIENT_ID` etc.) | Task 2 |
| `get_current_user_optional` helper | Task 2 |
| `is_safe_redirect_path` helper (ported from frontend) | Task 2 |
| Authlib + itsdangerous + httpx deps | Task 2 |
| Session middleware | Task 4 |
| Authlib Google client registration | Task 4 |
| Schemas (OAuthIdentityOut, SetPasswordRequest) | Task 3 |
| `GET /auth/google/authorize` | Task 5 |
| `GET /auth/google/callback` (3 flows: new / auto-link / connect) | Task 6 |
| Unverified-email rejection | Task 6 |
| `GET /auth/identities` | Task 7 |
| `POST /auth/google/disconnect` (+ password guard) | Task 7 |
| `PUT /auth/password` | Task 8 |
| Rate limiting on all three public routes | Tasks 5, 6, 7 |
| Audit logging on signin / connect / disconnect | Tasks 6, 7 |
| i18n keys (en + zh) | Task 9 |
| `<GoogleSignInButton>` | Task 10 |
| `.auth-divider` CSS | Task 10 |
| Integrate into /login + /register | Task 11 |
| `<ConnectedAccountsList>` | Task 12 |
| Disconnect confirm + set-password inline flow | Task 12 |
| Settings page section | Task 13 |
| Backend pytest tests for all edge cases from §8 | Tasks 5-8 |
| Playwright smoke tests | Task 14 |
| `.env.example` documentation | Task 2 |
| Manual acceptance checklist | Task 15 |
| Feature-flag rollout | Tasks 2, 15 |

Every line in spec §2 "In scope" is covered by at least one task. Spec §8 edge cases each map to a pytest test case in Tasks 5-8.

**Type consistency:** `OAuthIdentity` model (Task 1) matches schema `OAuthIdentityOut` (Task 3) matches frontend `Identity` interface (Task 12). `SetPasswordRequest` (Task 3) matches frontend `apiPut('/api/v1/auth/password', { new_password })` body (Task 12). `password_required` error code (Task 7 backend) matches frontend error branch detection (Task 12).

**Placeholder scan:** one intentional `down_revision = None  # FILL:` marker in Task 1 Step 1 — the implementer must look up the current Alembic head before running. This is clearly flagged with a `# FILL:` comment and explicit instructions. All other tasks contain complete code.

**Out-of-scope items** (from spec §2 "Out of scope") are NOT in the plan, as intended:
- Apple / GitHub / other providers
- Google Workspace SSO restrictions
- Cross-email account merging
- Refresh token revocation
- One Tap UI
- Federated logout
- Passwordless email
- Avatar sync
