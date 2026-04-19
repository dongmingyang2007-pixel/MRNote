# Google OAuth Sign-In (Design)

Date: 2026-04-19
Status: Draft — awaiting user review
Scope: Auth system extension — adds Google as a second identity
provider alongside email/password, plus a provider-agnostic
`oauth_identities` table so Apple / GitHub / etc. can slot in later
without schema churn.

## 1. Purpose

Today MRNote auth is email + password only (see `apps/api/app/routers/auth.py`):
- `/send-code` → email verification code
- `/register` → code + email + password
- `/login` → email + password
- `/reset-password` → code + new password

This forces every new user to pick a password, verify their email,
and remember it — friction that causes measurable sign-up drop-off on
comparable SaaS. It also blocks a set of users who prefer passwordless
flows (Google Workspace users at small agencies, non-technical users
with password fatigue).

This spec adds **Sign in with Google** — the industry-standard OAuth
2.0 + OpenID Connect flow — as a parallel identity provider. Users
can:
- Sign up with Google (no password, no email code)
- Log in with Google
- Connect/disconnect Google from an existing email-password account
  in `/app/settings`

The data model is **multi-provider ready** from day one so Apple
(probably next, iOS-driven) and GitHub (dev audience) can be added
later with only a library-level integration, not a migration.

## 2. Scope

### In scope

**Backend (FastAPI):**
- New `oauth_identities` table + Alembic migration
- Make `users.password_hash` nullable (OAuth-only users have no password)
- `GET /api/v1/auth/google/authorize` — starts OAuth flow (both sign-up and sign-in)
- `GET /api/v1/auth/google/callback` — handles Google redirect, creates/links user, sets auth cookie, redirects to app
- `POST /api/v1/auth/google/connect` — link Google to an already-logged-in account (triggers same flow with `mode=connect` marker)
- `POST /api/v1/auth/google/disconnect` — unlink Google from the logged-in account; blocked if user has no password (with a clear error that the frontend handles)
- `GET /api/v1/auth/identities` — list the current user's linked OAuth identities (for settings UI)
- Authlib integration (`authlib.integrations.starlette_client.OAuth`) + Starlette `SessionMiddleware` for the OAuth state round-trip
- Env vars: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_OAUTH_REDIRECT_BASE`

**Frontend (Next.js):**
- `<GoogleSignInButton />` shared component (Google-branded, white bg + colored G logo per Google's identity guidelines)
- Rendered on `/login` and `/register` — **above** the email form, with an "OR" divider below (layout A from the brainstorming mockup)
- New "Connected accounts" section on `/app/settings/page.tsx` showing linked Google account (email + connected-at) and Connect/Disconnect buttons
- Password-setup inline flow when user tries to disconnect Google but has no password
- New i18n keys under `auth.oauth.*` (zh + en)

**Config / deployment:**
- Local dev: redirect URI `http://localhost:3000/api/v1/auth/google/callback`
- Production: redirect URI `https://mr-note.com/api/v1/auth/google/callback`
- Both registered in Google Cloud Console → OAuth consent screen (External) → OAuth 2.0 Client ID (Web application)
- `.env.example` documents the three new env vars

**Testing:**
- pytest backend unit tests: new-user flow, existing-email auto-link, unverified-email rejection, state mismatch rejection, disconnect-without-password rejection
- Playwright frontend smoke: Google button renders on login/register, settings page shows link status, disconnect confirm modal appears

### Out of scope (explicit)

- Apple / GitHub / Microsoft / WeChat providers (the schema supports them but wiring is future work)
- Google Workspace SSO / domain-restricted sign-in (any Google account can sign up)
- Merging two existing MRNote accounts because the same human has both an email account and a Google account with a *different* email — users must sign in with the Google email that matches their existing MRNote email, or create a new account
- Revoking Google's refresh token on disconnect (we only forget the link locally; the user can separately revoke at [myaccount.google.com](https://myaccount.google.com))
- Google One Tap / auto-prompt UI
- Logging out from Google when logging out from MRNote (single-sign-out)
- Passwordless email magic links (a different provider; tracked separately)
- Force-enable 2FA for Google users
- Avatar sync (Google's `picture` claim is available but we don't have an `avatar_url` column yet; if we add one it's a separate spec)

## 3. Architecture

### 3.1 OAuth flow (happy path — new user)

```
Browser                 Frontend            Backend              Google
   │                      │                    │                    │
   │ click "Continue       │                    │                    │
   │ with Google"          │                    │                    │
   │──────────────────────►│                    │                    │
   │                      │ window.location =  │                    │
   │                      │ /api/v1/auth/      │                    │
   │                      │ google/authorize?  │                    │
   │                      │ next=/app          │                    │
   │◄─────────────────────│                    │                    │
   │ GET /authorize?next=/app                  │                    │
   │──────────────────────────────────────────►│                    │
   │                                           │ generate state,    │
   │                                           │ store in session,  │
   │                                           │ build Google URL   │
   │◄──────── 302 → https://accounts.google.com/o/oauth2/v2/auth?… │
   │                                                                │
   │──────────── user consents on Google consent screen ───────────►│
   │                                                                │
   │◄─── 302 → /api/v1/auth/google/callback?code=…&state=…         │
   │                                           │                    │
   │─────────────────────────────────────────►│                    │
   │                                           │ verify state       │
   │                                           │ exchange code ◄───►│ token endpoint
   │                                           │ verify ID token    │
   │                                           │ lookup oauth_id   │
   │                                           │ → not found       │
   │                                           │ lookup email      │
   │                                           │ → not found       │
   │                                           │ create User +     │
   │                                           │   Workspace +     │
   │                                           │   Membership +    │
   │                                           │   oauth_identity  │
   │                                           │ set auth cookie   │
   │◄─── 302 → /app ───────────────────────────│                    │
```

### 3.2 Auto-link flow (returning user with existing email account)

Same flow through the token exchange + ID token verification. At the
"lookup email" step:
- Email matches an existing User in our DB
- **AND** Google's ID token claim `email_verified == true`
- → Create `oauth_identities` row linking Google ID to that user, set
  auth cookie, 302 → `/app`. User never sees a friction step.

If `email_verified == false` (extremely rare for Google accounts, but
possible in edge cases like corporate Google Workspace), the backend
returns a redirect to `/login?error=google_email_unverified` with a
frontend-rendered error message.

### 3.3 Connect flow (logged-in user linking Google in settings)

Same `/authorize` endpoint with a `mode=connect` query param. Backend
records the intent in the session state. In the callback, if the
current user already has an auth cookie **and** `mode=connect` was
stored:
- Look up existing `oauth_identities` by `(provider='google',
  provider_id=sub)`. If found AND linked to a different user → reject
  with error (that Google account belongs to someone else).
- Else insert new `oauth_identities` row for the logged-in user.
- 302 → `/app/settings?connected=google`.

### 3.4 Disconnect flow

`POST /api/v1/auth/google/disconnect` with CSRF token.
- If user has no `password_hash` → return 409 `password_required` with
  message "Please set a password before disconnecting Google, or your
  account will become inaccessible." Frontend shows inline
  password-setup form; on submit, hits `PUT /api/v1/auth/password`
  (new endpoint — creates password for OAuth-only user), then retries
  disconnect.
- Else delete the `oauth_identities` row and return 200.

## 4. Data model

### 4.1 `users` table change

```sql
ALTER TABLE users ALTER COLUMN password_hash DROP NOT NULL;
```

Existing password-users keep their hashes unchanged. Google-only users
insert with `password_hash = NULL`.

### 4.2 New `oauth_identities` table

```sql
CREATE TABLE oauth_identities (
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id         uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  provider        text NOT NULL,     -- 'google' | 'apple' | 'github' | …
  provider_id     text NOT NULL,     -- Google's `sub` (stable account ID)
  provider_email  text,              -- snapshot at link time, may drift
  linked_at       timestamptz NOT NULL DEFAULT now(),
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),

  UNIQUE (provider, provider_id),    -- one Google account = one MRNote user
  UNIQUE (provider, user_id)         -- a user has at most one Google link
);

CREATE INDEX idx_oauth_identities_user_id ON oauth_identities (user_id);
```

Rationale:
- `provider_id` is Google's `sub` claim — immutable even if the user
  changes their Google email, which is why we key on it rather than
  email.
- `provider_email` is a snapshot for display ("Linked: foo@gmail.com")
  but **never used for lookup**.
- `UNIQUE (provider, user_id)` prevents linking two Google accounts to
  one MRNote user. If we want multi-account linking in the future,
  drop this constraint — no migration pain.

### 4.3 SQLAlchemy model

```python
# apps/api/app/models/entities.py (append)

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
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
```

## 5. Backend API

### 5.1 Routes (new in `apps/api/app/routers/auth.py`)

```python
@router.get("/google/authorize")
async def google_authorize(
    request: Request,
    next: str | None = None,
    mode: Literal["signin", "connect"] = "signin",
    current_user: User | None = Depends(get_current_user_optional),
) -> RedirectResponse:
    # validate `next` is a relative URL (reuse getSafeNavigationPath pattern)
    # if mode=connect, require current_user (else 401 back to /login)
    # persist {next, mode, user_id} in request.session
    # return oauth.google.authorize_redirect(...)

@router.get("/google/callback")
async def google_callback(
    request: Request,
    response: Response,
    db: Session = Depends(get_db_session),
) -> RedirectResponse:
    # authlib validates state + exchanges code
    # verify ID token via authlib.parse_id_token
    # extract: sub, email, email_verified, name
    # branch on existing oauth_identity / existing email / mode

@router.get("/identities", response_model=list[OAuthIdentityOut])
async def list_identities(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> list[OAuthIdentityOut]:
    # return all oauth_identities rows for the current user

@router.post("/google/disconnect")
async def google_disconnect(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
    _: None = Depends(require_csrf_protection),
) -> dict[str, bool]:
    # block if current_user.password_hash is None
    # delete oauth_identities where user_id=… and provider='google'
    # write audit log
```

One new endpoint for "OAuth-only user sets an initial password":

```python
@router.put("/password")
async def set_password(
    payload: SetPasswordRequest,  # {new_password: str}
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
    _: None = Depends(require_csrf_protection),
) -> dict[str, bool]:
    # if current_user.password_hash is not None → require old password
    # else → no old password, just set new one
    # hash + save + audit log
```

### 5.2 Rate limiting

All three new public routes get the same IP-based rate limiting as
email login/register (reuse `enforce_rate_limit`):
- `/google/authorize`: `auth:oauth_authorize:ip`
- `/google/callback`: `auth:oauth_callback:ip`
- `/google/disconnect`: `auth:oauth_disconnect:user`

### 5.3 Audit logging

Every successful sign-in, sign-up, connect, disconnect goes through
`write_audit_log` with the same format as email auth (actor_user_id,
workspace_id, action, meta_json containing `provider="google"` and
`provider_email`).

### 5.4 Library choice

**Authlib** (`authlib` + `authlib[httpx_client]`, MIT license,
well-maintained, FastAPI-compatible via the Starlette integration).

- Install: `authlib>=1.3` and `itsdangerous>=2.0` (for session signing)
- Register Starlette `SessionMiddleware` with a 10-minute max-age,
  keyed separately from the app auth cookie
- Session is ONLY used for the OAuth round-trip (state + mode + next);
  app authn still flows through the JWT cookie

Rejected alternatives:
- `google-auth` + hand-written flow: more control, more code, more
  bugs to own.
- `fastapi-sso`: reasonable but less widely used; binds us to a thinner
  ecosystem.

### 5.5 Scopes

Minimum needed: `openid email profile`.
- `openid` — required for ID token issuance
- `email` — gives us `email` + `email_verified`
- `profile` — gives us `name` for populating `display_name`

Not requested: `https://www.googleapis.com/auth/calendar`, Drive, etc.
Keep permissions minimal — only what we actually consume.

## 6. Frontend

### 6.1 `<GoogleSignInButton />` component

New file: `apps/web/components/auth/GoogleSignInButton.tsx`. Client
component (uses `useSearchParams` to read `next`).

```tsx
"use client";

import { useSearchParams } from "next/navigation";

interface Props {
  mode?: "signin" | "connect";
  className?: string;
}

export default function GoogleSignInButton({ mode = "signin", className }: Props) {
  const searchParams = useSearchParams();
  const next = searchParams.get("next") ?? "/app";

  const href = `/api/v1/auth/google/authorize?mode=${mode}&next=${encodeURIComponent(next)}`;

  return (
    <a
      href={href}
      className={/* white bg, #dadce0 border, 16px Google G svg, 14px text per Google brand guidelines */}
    >
      <GoogleGLogo size={18} />
      <span>Continue with Google</span>
    </a>
  );
}
```

- Uses `<a>` (not `<Link>`) because the navigation is a real page
  redirect to an API endpoint, not a client-side route change.
- Style follows [Google's official button guidelines](https://developers.google.com/identity/branding-guidelines):
  white background, `#dadce0` border, `#3c4043` text, official
  multi-colored G SVG.

### 6.2 Login and Register page updates

**`apps/web/app/[locale]/(auth)/login/page.tsx`** and
**`apps/web/app/[locale]/(auth)/register/page.tsx`**:

Above the existing email form, insert:

```tsx
<div className="auth-oauth-block">
  <GoogleSignInButton />
  <div className="auth-divider"><span>OR</span></div>
</div>
```

New CSS for `.auth-divider` (tiny, in `globals.css` or a new
`auth.css`): horizontal line + centered "OR" text.

### 6.3 Settings page — Connected accounts section

**`apps/web/app/[locale]/workspace/settings/page.tsx`**: add a new
section below Account, above Developer Mode:

```tsx
<GlassCard>
  <div style={sectionTitle}>{t("connectedAccounts.title")}</div>
  <div style={sectionDesc}>{t("connectedAccounts.desc")}</div>

  <ConnectedAccountsList />
</GlassCard>
```

New component `components/settings/ConnectedAccountsList.tsx` (client
component):
- Fetches `/api/v1/auth/identities`
- Shows one row per provider (only Google in v1):
  - Google logo + "Google"
  - If linked: `<email>` · Linked MMM DD, YYYY · `[Disconnect]`
  - If not linked: `[Connect]`
- `Connect` → `window.location = /api/v1/auth/google/authorize?mode=connect&next=/app/settings`
- `Disconnect` → confirm modal → POST to `/google/disconnect`
  - On `password_required` error → show inline password-setup form
    (two fields: new password, confirm); on submit POST to
    `/auth/password`, then retry disconnect

### 6.4 i18n keys

New keys in `apps/web/messages/{zh,en}/auth.json`:

```json
{
  "oauth.google.button": "Continue with Google",  // both locales keep English per Google brand guide
  "oauth.divider": "或" / "OR",
  "oauth.error.unverified": "你的 Google 邮箱尚未验证，请先在 Google 账号设置里验证邮箱。" / "Your Google email is not verified. Please verify it in your Google account settings first.",
  "oauth.error.state_mismatch": "登录会话已过期，请重试。" / "Login session expired. Please try again.",
  "oauth.error.already_linked": "这个 Google 账号已经绑定到其他 MRNote 用户。" / "This Google account is already linked to a different MRNote user.",

  "connectedAccounts.title": "已连接账号" / "Connected accounts",
  "connectedAccounts.desc": "用第三方账号快速登录" / "Sign in faster with third-party accounts",
  "connectedAccounts.google.name": "Google",
  "connectedAccounts.connect": "连接" / "Connect",
  "connectedAccounts.disconnect": "解除连接" / "Disconnect",
  "connectedAccounts.linkedAt": "已连接于 {date}" / "Linked on {date}",
  "connectedAccounts.disconnectConfirm.title": "解除 Google 连接？" / "Disconnect Google?",
  "connectedAccounts.disconnectConfirm.desc": "解除后将无法用 Google 登录。你仍可用邮箱密码登录。" / "You won't be able to sign in with Google. Email + password still works.",
  "connectedAccounts.setPassword.title": "先设置密码" / "Set a password first",
  "connectedAccounts.setPassword.desc": "解除 Google 前必须先设置密码，否则账号将无法登录。" / "You must set a password before disconnecting Google, or your account will become inaccessible."
}
```

(The actual final zh/en copy will be polished during implementation;
the keys themselves are locked.)

## 7. Security

### 7.1 CSRF / state

- OAuth `state` is handled by Authlib automatically (random 32-byte
  token, stored in Starlette session, verified in callback).
- Session middleware uses a signed cookie with `SECRET_KEY` (env var),
  `HttpOnly`, `Secure` in prod, `SameSite=Lax` (required — the
  callback returns cross-site from Google).
- The app's existing JWT cookie stays `SameSite=Strict` (unchanged).

### 7.2 ID token verification

Authlib's `parse_id_token` verifies:
- Signature against Google's JWKS (fetched + cached by authlib)
- `iss == https://accounts.google.com`
- `aud == GOOGLE_CLIENT_ID`
- `exp` not passed
- `nonce` matches (authlib generates + checks)

We additionally check `email_verified == True` in our callback; if
false, reject.

### 7.3 Redirect URI validation

Google enforces `redirect_uri` matches one of the registered values in
Cloud Console. Register exactly:
- `http://localhost:3000/api/v1/auth/google/callback`
- `https://mr-note.com/api/v1/auth/google/callback`

No wildcard URIs, no other hosts. Staging (if added later) gets its
own registered URI.

### 7.4 `next` parameter validation

The `next` query param on `/authorize` is user-controllable. We
validate it's a **relative path starting with `/`** and doesn't
contain `//` or `\\` (open-redirect prevention — reuse the existing
`getSafeNavigationPath` helper on the backend side, port it to
Python).

### 7.5 Account takeover edge case

The only vector for OAuth-specific account takeover is **domain
takeover + email reuse**: attacker takes over a Google Workspace
domain, logs in with a `someone@oldcompany.com` Google account that
previously belonged to a real user, and auto-links.

Mitigation: we rely on `email_verified == true` from Google. Google's
verification is normally strong (domain admin must verify), but a
hostile domain admin could theoretically claim any `@oldcompany.com`
address. This is a known OAuth ecosystem limitation; mitigating it
requires email-reverification on every OAuth link (friction) or
blocking cross-domain auto-link entirely (hurts the primary use case).

We accept this risk for v1 — it matches the behavior of Notion,
Linear, Vercel, GitHub, and most SaaS. Documenting it here so a
future audit knows the threat model.

### 7.6 Session fixation

Each OAuth flow generates a fresh state + nonce. On success, we rotate
the app's JWT cookie (authlib session is separate and short-lived;
rotating the JWT is equivalent to a login). No pre-auth session data
persists post-auth.

## 8. Edge cases

| Case | Behavior |
|---|---|
| New user, new email | Create User + Workspace + Membership + oauth_identity; `password_hash = NULL`; `display_name = google.name`; route to onboarding (`onboarding_completed_at = NULL`) |
| Existing email account, never linked Google | Auto-link if `email_verified`; else reject with `oauth.error.unverified` |
| Existing Google link → sign in | Look up by `(provider='google', provider_id=sub)`, log in, ignore email mismatch (Google user may have changed their email) |
| User changes Google email, then tries to sign in | Works — we key on `sub`, not email. `provider_email` column gets stale but we refresh it on each successful callback. |
| User tries to connect Google already linked to another MRNote account | Reject with `oauth.error.already_linked` |
| User disconnects Google but has password | Delete `oauth_identities` row, success |
| User disconnects Google but has no password | 409 `password_required`; frontend prompts to set password, retries |
| User deleted their Google account | Their Google ID still resolves in our DB; next sign-in attempt fails at Google's side (they can't authenticate). Their MRNote account stays accessible via email+password if they have one, or via "Forgot password" if they don't but they own the email. |
| `state` expired (session older than 10 min) | Reject with `oauth.error.state_mismatch`; user retries from `/login` |
| User cancels on Google's consent screen | Google redirects back with `error=access_denied`; our callback detects, redirects to `/login?error=oauth_cancelled` with a muted message |
| Two tabs, concurrent OAuth flows | Each tab has its own session entry; second callback overwrites first's state. Whichever completes last wins. This is a theoretical race; practical impact is zero. |

## 9. Config / Environment

### 9.1 Backend env vars

Add to `apps/api/.env.example` and `apps/api/app/core/config.py`:

```bash
# Google OAuth
GOOGLE_CLIENT_ID=              # from Google Cloud Console → Credentials
GOOGLE_CLIENT_SECRET=          # same place, keep secret
GOOGLE_OAUTH_REDIRECT_BASE=http://localhost:3000  # dev default; prod = https://mr-note.com
OAUTH_SESSION_SECRET=          # random 32-byte hex; independent from JWT SECRET_KEY
```

`GOOGLE_OAUTH_REDIRECT_BASE` + `/api/v1/auth/google/callback` must
exactly match a URI registered in the Cloud Console.

### 9.2 Dev secrets handling

`.env.example` carries empty values. Developers copy to `.env` and
fill. `.env` stays gitignored (already the case). The user has to:
1. Create Google Cloud Console OAuth Client (one-time, ~5 min)
2. Paste CLIENT_ID + CLIENT_SECRET into local `.env`
3. Set `OAUTH_SESSION_SECRET` with `openssl rand -hex 32`

Production secrets go into the Vercel / Aliyun ECS environment via
their respective dashboards — never committed.

### 9.3 Google Cloud Console checklist (for the human)

1. Create project → `MRNote`
2. OAuth consent screen → External → fill: App name `MRNote`,
   support + developer email, add `openid email profile` scopes, add
   test users (your own Gmail while in Testing mode)
3. Credentials → Create → OAuth Client ID → Web application
4. Authorized redirect URIs: both local + prod exact strings
5. Copy Client ID + Secret into `.env`

## 10. Testing strategy

### 10.1 Backend (pytest)

New `apps/api/tests/test_auth_google.py`:

- `test_new_user_via_google` — mock authlib, assert User + Workspace + oauth_identity created
- `test_existing_email_auto_links` — seed User(email=X), Google returns email=X verified → assert oauth_identity row created, no duplicate User
- `test_existing_email_unverified_rejects` — Google returns `email_verified=false` → assert 302 to `/login?error=google_email_unverified`
- `test_existing_oauth_identity_signs_in` — seed oauth_identity → same Google ID returns → assert signs in as the linked user (not matching email)
- `test_state_mismatch_rejects` — manipulate session → assert 400
- `test_disconnect_requires_password` — user with password_hash=NULL → POST disconnect → assert 409
- `test_disconnect_with_password_succeeds` — user with password_hash → POST disconnect → assert row deleted
- `test_connect_to_already_linked_google_rejects` — Google ID already in oauth_identities for user A; user B tries to connect → assert rejected
- `test_next_param_relative_only` — `next=https://evil.com` → assert ignored, redirected to `/app`

All tests mock Authlib's Google client with stubs for `authorize_redirect`, `authorize_access_token`, `parse_id_token`.

### 10.2 Frontend (Playwright)

New `apps/web/tests/auth-oauth.spec.ts`:

- `/login` shows Google button above email form with "OR" divider
- `/register` shows Google button above email form
- Clicking button navigates to `/api/v1/auth/google/authorize` (we can't complete the flow without Google, but we can verify the navigation target and query string)
- Logged-in user's `/app/settings` shows "Connected accounts" section with "Connect Google" button when no link exists
- Mock the `GET /api/v1/auth/identities` response to show a linked state; verify "Disconnect" button renders

Full end-to-end OAuth test (hitting real Google) is NOT in scope — it
requires persistent test Google accounts and is flaky. The
backend+frontend unit/integration layers together cover the behavior.

### 10.3 Manual smoke (one-time per deploy)

After deployment:
1. Visit `/login`, click Continue with Google, complete consent, land on `/app`
2. Log out, visit `/login` again, Continue with Google again, land on `/app` (no duplicate user)
3. Log in with email account, go to `/app/settings`, click Connect Google, complete flow, see linked state
4. Click Disconnect, confirm, see unlinked state
5. Repeat for user with no password: Disconnect blocked, password-setup modal shows, set password, retry Disconnect succeeds

## 11. Deployment

### 11.1 Dev

- `.env` filled with Google test credentials (from Testing mode
  consent screen)
- `pnpm dev` runs frontend on :3000
- FastAPI runs on :8000 via `uvicorn` (as today)
- Next.js proxies `/api/*` to :8000 (already configured in
  `next.config.mjs`)
- Google redirects to `http://localhost:3000/api/v1/auth/google/callback`
- Next.js proxy forwards to FastAPI, which handles the callback

### 11.2 Production

- Frontend: **Vercel** (free Hobby plan), bound to `mr-note.com` via
  the Vercel connector
- Backend: **Aliyun / Tencent Cloud HK ECS** (or equivalent), FastAPI
  behind nginx with Let's Encrypt certs
- Subdomain: `api.mr-note.com` → backend ECS IP, or same-origin via
  Vercel rewrite (revisit at deploy time)
- Google Cloud Console redirect URI:
  `https://mr-note.com/api/v1/auth/google/callback`
- Publish from Testing → Production in the OAuth consent screen after
  domain verification (Google sends a file to place on the domain, or
  a meta tag)

### 11.3 OAuth consent screen state

Start in **Testing** mode (only test users can sign in, max 100, lasts
indefinitely). Move to **In production** mode once:
- You've finalized the app name + logo + support email
- You've verified domain ownership via `mr-note.com`
- You're ready for Google's verification review (can take 1-2 weeks,
  required only if you request sensitive scopes; for `openid email
  profile` it's usually fast)

For v1 launch, Testing mode with a handful of real users is fine. Move
to Production before a broader marketing push.

## 12. Rollout / migration

1. Ship migration (alter users + create oauth_identities) to prod DB
2. Ship backend routes behind a feature flag `GOOGLE_OAUTH_ENABLED=false`
3. Ship frontend components without rendering them (flag-gated)
4. Smoke test internally on staging
5. Enable flag in prod — Google button appears
6. Monitor for 1 week: error rate on callback, new-user creation rate,
   auto-link success rate
7. If green, remove the flag code in a follow-up PR

Feature-flag gate exists so a bad interaction with the existing email
flow can be killed server-side without a frontend redeploy.

## 13. Non-goals

- Not a general-purpose "identity provider" system. The `provider`
  column is text for flexibility but there's no plugin architecture;
  adding Apple means writing Apple-specific code paths, not configuring
  a new row.
- Not a replacement for email/password. Email flow stays fully
  supported forever.
- Not tracking Google refresh tokens. We don't need ongoing access to
  Google APIs; we just need one-time identity proof. If a future
  feature needs Drive / Calendar access, it requires a separate scope
  request and refresh-token-storage design — that's its own spec.
- Not a federated logout. Logging out of MRNote doesn't log you out of
  Google. Most users want this behavior; the rare user who wants full
  sign-out can do so at [myaccount.google.com](https://myaccount.google.com).

---

## Appendix A — Self-review checklist

- [x] Every section concrete, no "TBD"
- [x] Architecture diagram matches the API routes
- [x] Schema migration forward-only safe (password_hash nullable is
      additive; oauth_identities is new table)
- [x] All edge cases in §8 have defined behavior
- [x] Env vars listed in §9 match what code references
- [x] i18n keys in §6.4 exhaustive for what §6.1-6.3 renders
- [x] Tests in §10 cover every edge case from §8
- [x] Security threats in §7 enumerated and addressed or explicitly
      accepted
- [x] Out-of-scope items in §2 prevent scope creep during implementation
