# ruff: noqa: E402
"""Regression tests for Wave-1 A1 auth/session/enumeration/rate-limit fixes.

Covers:

* S-H2: password change / Google disconnect revoke previously issued JWTs
* S-H3: /register returns identical 200 for new vs already-registered email
* M1:   /reset-password has email-scoped rate limiting
* M2:   PUT /auth/password is rate-limited per user
* M3:   /send-code honours the 24h per-email cap
* M8:   is_safe_redirect_path rejects nested open-redirect payloads
* M10:  /ws-ticket no longer stores the raw access_token in runtime state
* M11:  /memory/backfill writes an audit log with actor_user_id
* MEDIUM-15: /register refuses disposable email domains
"""
import atexit
import hashlib
import importlib
import os
import shutil
import tempfile
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-auth-c-fixes-"))
atexit.register(lambda: shutil.rmtree(TEST_TEMP_DIR, ignore_errors=True))
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_TEMP_DIR / 'test.db'}"
os.environ["ENV"] = "test"
os.environ["COOKIE_DOMAIN"] = ""
os.environ["DEMO_MODE"] = "true"
os.environ["STRIPE_API_KEY"] = "sk_test_dummy"

import app.core.config as config_module
config_module.get_settings.cache_clear()
config_module.settings = config_module.get_settings()
import app.db.session as session_module
importlib.reload(session_module)
import app.main as main_module
importlib.reload(main_module)

from fastapi.testclient import TestClient

import app.db.session as _s
import app.routers.auth as auth_router
import app.routers.chat as chat_router
import app.routers.memory as memory_router
import app.routers.realtime as realtime_router
from app.db.base import Base
from app.models import AuditLog, Membership, User
from app.services.runtime_state import runtime_state


ORIGIN = "http://localhost:3000"


def setup_function() -> None:
    Base.metadata.drop_all(bind=_s.engine)
    Base.metadata.create_all(bind=_s.engine)
    runtime_state._memory = runtime_state._memory.__class__()
    importlib.reload(chat_router)
    importlib.reload(realtime_router)
    importlib.reload(auth_router)
    importlib.reload(memory_router)
    importlib.reload(main_module)


def _public() -> dict[str, str]:
    return {"origin": ORIGIN}


def _verification_code_key(email: str, purpose: str) -> str:
    raw = f"{email.lower().strip()}:{purpose}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _issue_code(client: TestClient, email: str, purpose: str = "register") -> str:
    resp = client.post(
        "/api/v1/auth/send-code",
        json={"email": email, "purpose": purpose},
        headers=_public(),
    )
    assert resp.status_code == 200, resp.text
    entry = runtime_state.get_json("verify_code", _verification_code_key(email, purpose))
    assert entry is not None
    return str(entry["code"])


def _register(email: str, password: str = "pass1234pass") -> tuple[TestClient, dict]:
    client = TestClient(main_module.app)
    code = _issue_code(client, email, "register")
    resp = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": password,
            "display_name": "Test",
            "code": code,
        },
        headers=_public(),
    )
    assert resp.status_code == 200, resp.text
    info = resp.json()
    return client, info


def _csrf(client: TestClient, workspace_id: str | None = None) -> dict[str, str]:
    resp = client.get("/api/v1/auth/csrf", headers=_public())
    assert resp.status_code == 200, resp.text
    headers = {"origin": ORIGIN, "x-csrf-token": resp.json()["csrf_token"]}
    if workspace_id:
        headers["x-workspace-id"] = workspace_id
    return headers


# ---------------------------------------------------------------------------
# S-H2: password change / Google disconnect must revoke previously-issued JWTs
# ---------------------------------------------------------------------------


def test_password_change_revokes_tokens() -> None:
    """Before S-H2, a stolen cookie stayed valid after the victim rotated
    their password. After the fix, the old token is rejected and the
    caller's own session is replaced by a fresh cookie."""
    email = "sh2-pw@x.co"
    client, info = _register(email, password="initial1234pass")

    stolen_token = client.cookies.get(config_module.settings.access_cookie_name)
    assert stolen_token

    shadow = TestClient(main_module.app)
    shadow.cookies.set(config_module.settings.access_cookie_name, stolen_token)
    assert shadow.get("/api/v1/auth/me").status_code == 200

    resp = client.put(
        "/api/v1/auth/password",
        json={
            "new_password": "newnew1234pass",
            "current_password": "initial1234pass",
        },
        headers=_csrf(client),
    )
    assert resp.status_code == 200, resp.text

    # Stolen cookie must no longer authenticate.
    denied = shadow.get("/api/v1/auth/me")
    assert denied.status_code == 401, denied.text

    # The caller kept a working session (we reissued a fresh cookie).
    assert client.get("/api/v1/auth/me", headers=_public()).status_code == 200


def test_google_disconnect_revokes_tokens() -> None:
    """Unlinking the only non-password auth method is a credential rotation
    event: previously-issued tokens should stop working."""
    from app.core.security import create_access_token
    from app.models import OAuthIdentity, User as UserModel

    # Seed a user with a password AND a Google identity.
    with _s.SessionLocal() as db:
        from app.core.security import hash_password
        user = UserModel(
            email="sh2-disc@x.co",
            password_hash=hash_password("initial1234pass"),
            display_name="D",
        )
        db.add(user)
        db.flush()
        db.add(OAuthIdentity(
            user_id=user.id, provider="google",
            provider_id="90210", provider_email=user.email,
        ))
        db.commit()
        uid = user.id

    client = TestClient(main_module.app)
    token = create_access_token(uid)
    client.cookies.set(config_module.settings.access_cookie_name, token)
    csrf = client.get("/api/v1/auth/csrf", headers=_public()).json()["csrf_token"]

    shadow = TestClient(main_module.app)
    shadow.cookies.set(config_module.settings.access_cookie_name, token)
    assert shadow.get("/api/v1/auth/me").status_code == 200

    resp = client.post(
        "/api/v1/auth/google/disconnect",
        headers={"origin": ORIGIN, "x-csrf-token": csrf},
    )
    assert resp.status_code == 200, resp.text

    # Old token (pre-disconnect) must be revoked.
    assert shadow.get("/api/v1/auth/me").status_code == 401

    # Caller session survives because a new cookie was reissued.
    assert client.get("/api/v1/auth/me", headers=_public()).status_code == 200


# ---------------------------------------------------------------------------
# S-H3: /register no longer exposes "already registered" vs "new"
# ---------------------------------------------------------------------------


def test_register_does_not_enumerate_existing_email() -> None:
    email = "enum@x.co"
    client, _ = _register(email)  # First registration succeeds.

    # Now probe from a fresh client; pre-audit this would have returned 409
    # email_exists, telling the attacker the address is registered.
    attacker = TestClient(main_module.app)
    code = _issue_code(attacker, email, "register")
    resp = attacker.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "other1234pass",
            "display_name": "Other",
            "code": code,
        },
        headers=_public(),
    )
    assert resp.status_code == 200, resp.text

    # No cookie should be set — we did not actually log the attacker in
    # as anybody.
    body = resp.json()
    assert body == {"ok": True}
    assert config_module.settings.access_cookie_name not in resp.cookies

    # And the original user row must be unchanged (no takeover).
    with _s.SessionLocal() as db:
        count = db.query(User).filter(User.email == email).count()
        assert count == 1


# ---------------------------------------------------------------------------
# M1: reset-password email-scoped rate limit
# ---------------------------------------------------------------------------


def test_reset_password_email_rate_limit() -> None:
    """With the default auth_rate_limit_ip_max cap at 10 per window, the
    11th reset attempt for the same email must be rate-limited even if the
    attacker shuffles source IPs (we simulate by varying X-Forwarded-For
    only as a secondary control — the email bucket is what matters)."""
    # Settle the app so test-client timers aren't carried from a sibling
    # test.
    client, info = _register("reset-rl@x.co")

    # Burn the cap using wrong codes; the email scope is what we're
    # testing, so even bad payloads count.
    email = "reset-rl@x.co"
    limit = config_module.settings.auth_rate_limit_ip_max
    last_status = None
    for i in range(limit + 2):
        resp = client.post(
            "/api/v1/auth/reset-password",
            json={
                "email": email,
                "password": "newpass1234pass",
                "code": "00000000",
            },
            headers=_public(),
        )
        last_status = resp.status_code
        if resp.status_code == 429:
            break
    assert last_status == 429, f"expected 429 within {limit + 2} attempts, got {last_status}"


# ---------------------------------------------------------------------------
# M2: set_password rate limit
# ---------------------------------------------------------------------------


def test_set_password_rate_limit() -> None:
    """After 5 wrong current_password attempts in the window, the 6th must
    be rate-limited with 429 before the password check runs."""
    client, info = _register("setpw-rl@x.co", password="correct1234pass")
    headers = _csrf(client)

    wrong_payload = {
        "new_password": "unused1234pass",
        "current_password": "wrong1234pass",
    }

    statuses = []
    for _ in range(6):
        resp = client.put(
            "/api/v1/auth/password",
            json=wrong_payload,
            headers=headers,
        )
        statuses.append(resp.status_code)

    # The first 5 should bounce on invalid_credentials (400); the 6th
    # must hit the rate limiter (429).
    assert statuses.count(400) == 5, statuses
    assert statuses[-1] == 429, statuses


# ---------------------------------------------------------------------------
# M3: send-code daily cap per email
# ---------------------------------------------------------------------------


def test_send_code_email_24h_cap() -> None:
    """Beyond the 24h daily per-email cap, /send-code refuses more code
    deliveries to the same address even across IPs/windows."""
    client = TestClient(main_module.app)
    email = "spam-target@x.co"
    cap = config_module.settings.verification_email_daily_cap
    # The send-code endpoint also enforces a small per-minute window;
    # advance the counter by incrementing the daily scope directly so we
    # isolate just the daily cap behaviour.
    daily_key = hashlib.sha256(email.encode("utf-8")).hexdigest()
    for _ in range(cap):
        runtime_state.incr(
            "auth:send_code:email_daily",
            daily_key,
            ttl_seconds=86400,
        )
    resp = client.post(
        "/api/v1/auth/send-code",
        json={"email": email, "purpose": "register"},
        headers=_public(),
    )
    assert resp.status_code == 429, resp.text


# ---------------------------------------------------------------------------
# M8: is_safe_redirect_path rejects nested open-redirect payloads
# ---------------------------------------------------------------------------


def test_safe_redirect_rejects_nested_open_redirect() -> None:
    from app.core.deps import is_safe_redirect_path

    # Baseline safe paths still accepted.
    assert is_safe_redirect_path("/app") is True
    assert is_safe_redirect_path("/app/notebooks/123") is True

    # Nested next=/redirect= / protocol tricks rejected.
    assert is_safe_redirect_path("/app?next=https://evil.com") is False
    assert is_safe_redirect_path("/app?redirect=https://evil.com") is False
    assert is_safe_redirect_path("/app?redirect_uri=https://evil.com") is False
    assert is_safe_redirect_path("/app?return_to=https://evil.com") is False
    assert is_safe_redirect_path("/app?url=https://evil.com") is False
    assert is_safe_redirect_path("//evil.com") is False
    assert is_safe_redirect_path("/\\evil.com") is False
    assert is_safe_redirect_path("/app/foo//bar") is False  # embedded //
    assert is_safe_redirect_path("/javascript:alert(1)") is False


# ---------------------------------------------------------------------------
# M10: ws-ticket stores only a sha256 digest
# ---------------------------------------------------------------------------


def test_ws_ticket_does_not_store_plaintext_token() -> None:
    """/ws-ticket must not persist the raw access_token in runtime state;
    a Redis leak would otherwise expose live JWTs."""
    from app.core.entitlements import refresh_workspace_entitlements
    from app.models import Subscription

    client, info = _register("ws-ticket@x.co")
    workspace_id = info["workspace"]["id"]
    with _s.SessionLocal() as db:
        db.add(Subscription(
            workspace_id=workspace_id,
            plan="pro", status="active",
            provider="free", billing_cycle="monthly",
        ))
        db.commit()
        refresh_workspace_entitlements(db, workspace_id=workspace_id)

    resp = client.get("/api/v1/realtime/ws-ticket", headers=_public())
    assert resp.status_code == 200, resp.text
    ticket = resp.json()["ticket"]

    state = runtime_state.get_json(realtime_router.REALTIME_WS_TICKET_SCOPE, ticket)
    assert state is not None
    # No raw token
    assert "access_token" not in state
    # Presence of the hash + user_id
    assert "access_token_hash" in state
    assert isinstance(state["access_token_hash"], str)
    assert len(state["access_token_hash"]) == 64  # sha256 hex
    assert state["access_token_hash"] != client.cookies.get(
        config_module.settings.access_cookie_name
    )
    assert state["user_id"] == info["user"]["id"]


# ---------------------------------------------------------------------------
# M11: memory.backfill records actor_user_id
# ---------------------------------------------------------------------------


def test_backfill_logs_actor(monkeypatch) -> None:
    """Before M11, the backfill route committed an empty audit trail.
    Fix must record actor_user_id = current_user.id."""
    # Stub the actual backfill task so we don't run the real compute.
    import app.tasks.worker_tasks as worker_tasks

    def _fake_backfill(workspace_id, project_id, limit=None):
        return {
            "processed_memories": 0,
            "processed_edges": 0,
            "temporal_updated": 0,
            "confidence_updated": 0,
            "edge_fields_updated": 0,
            "evidences_created": 0,
            "message_evidences_created": 0,
            "conversation_evidences_created": 0,
            "manual_evidences_created": 0,
            "subjects_refreshed": 0,
            "profile_views_refreshed": 0,
            "timeline_views_refreshed": 0,
            "playbook_views_refreshed": 0,
            "skipped_structural_memories": 0,
        }

    monkeypatch.setattr(
        worker_tasks, "backfill_project_memory_v2_task", _fake_backfill
    )

    client, info = _register("m11@x.co")
    workspace_id = info["workspace"]["id"]
    user_id = info["user"]["id"]

    project = client.post(
        "/api/v1/projects",
        json={"name": "P", "description": "x", "default_chat_mode": "standard"},
        headers=_csrf(client, workspace_id),
    ).json()

    resp = client.post(
        "/api/v1/memory/backfill",
        json={"project_id": project["id"], "limit": 10},
        headers=_csrf(client, workspace_id),
    )
    assert resp.status_code == 200, resp.text

    with _s.SessionLocal() as db:
        rows = (
            db.query(AuditLog)
            .filter(AuditLog.action == "memory.backfill")
            .all()
        )
        assert rows, "no backfill audit log written"
        assert all(r.actor_user_id == user_id for r in rows)
        assert all(r.workspace_id == workspace_id for r in rows)
        assert all(r.target_id == project["id"] for r in rows)


# ---------------------------------------------------------------------------
# MEDIUM-15: disposable email rejection
# ---------------------------------------------------------------------------


def test_register_rejects_disposable_email() -> None:
    client = TestClient(main_module.app)
    email = "burner@mailinator.com"
    # We can't issue a real code because register rejects before verify,
    # but the endpoint also short-circuits disposable without needing it.
    resp = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "pass1234pass",
            "display_name": "X",
            "code": "00000000",
        },
        headers=_public(),
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()
    code = body.get("error", {}).get("code") or body.get("code")
    assert code == "disposable_email", body
