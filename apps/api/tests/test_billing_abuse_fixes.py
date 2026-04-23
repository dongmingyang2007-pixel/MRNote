# ruff: noqa: E402
"""Wave 1 A4 regression tests — billing/entitlement abuse fixes.

Covers HIGH-4 / HIGH-5 / HIGH-8 / HIGH-9 / HIGH-10 plus the associated
MEDIUM/LOW items from tmp/bug_audit/03_billing_abuse.md. Each failure
mode has at least one negative test here so the gate cannot silently
regress.
"""

import asyncio
import atexit
import hashlib
import importlib
import io
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-a4-abuse-"))
atexit.register(lambda: shutil.rmtree(TEST_TEMP_DIR, ignore_errors=True))
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_TEMP_DIR / 'test.db'}"
os.environ["ENV"] = "test"
os.environ["COOKIE_DOMAIN"] = ""
os.environ["DEMO_MODE"] = "true"
os.environ["STRIPE_API_KEY"] = "sk_test_dummy"
os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_dummy"
os.environ["SITE_URL"] = "https://mrai.test"

import app.core.config as config_module
config_module.get_settings.cache_clear()
config_module.settings = config_module.get_settings()
import app.db.session as session_module
importlib.reload(session_module)
import app.main as main_module
importlib.reload(main_module)

from fastapi.testclient import TestClient

import app.db.session as _s
import app.routers.billing as billing_router
import app.routers.uploads as uploads_router
import app.services.billing_webhook as billing_webhook_module
import app.services.stripe_client as stripe_client_module
from app.db.base import Base
from app.models import (
    AIActionLog,
    AIUsageEvent,
    BillingEvent,
    CustomerAccount,
    Entitlement,
    Subscription,
    User,
    Workspace,
)
from app.services.ai_action_logger import action_log_context
from app.services.runtime_state import runtime_state


def setup_function() -> None:
    Base.metadata.drop_all(bind=_s.engine)
    Base.metadata.create_all(bind=_s.engine)
    runtime_state._memory = runtime_state._memory.__class__()
    # Routers captured SessionLocal at import time; rebind so they see
    # the freshly-reset engine.
    importlib.reload(billing_router)
    importlib.reload(uploads_router)
    importlib.reload(main_module)


def _public() -> dict[str, str]:
    return {"origin": "http://localhost:3000"}


def _register(email: str = "u@x.co") -> tuple[TestClient, str, str]:
    """Register a fresh workspace owner. Returns (client, ws_id, user_id)."""
    client = TestClient(main_module.app)
    client.post(
        "/api/v1/auth/send-code",
        json={"email": email, "purpose": "register"},
        headers=_public(),
    )
    code_key = hashlib.sha256(f"{email.lower().strip()}:register".encode()).hexdigest()
    code = str(runtime_state.get_json("verify_code", code_key)["code"])
    info = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "pass1234pass",
            "display_name": "Test",
            "code": code,
        },
        headers=_public(),
    ).json()
    csrf = client.get("/api/v1/auth/csrf", headers=_public()).json()["csrf_token"]
    ws_id = info["workspace"]["id"]
    user_id = info["user"]["id"]
    client.headers.update({
        "origin": "http://localhost:3000",
        "x-csrf-token": csrf,
        "x-workspace-id": ws_id,
    })
    return client, ws_id, user_id


def _seed_workspace_with_customer(stripe_customer_id: str = "cus_t") -> str:
    with _s.SessionLocal() as db:
        ws = Workspace(name="W")
        user = User(email="u@x.co", password_hash="x")
        db.add(ws); db.add(user); db.commit(); db.refresh(ws)
        db.add(CustomerAccount(
            workspace_id=ws.id,
            stripe_customer_id=stripe_customer_id,
            email="u@x.co",
        ))
        db.commit()
        return ws.id


def _post_event(client: TestClient, event: dict) -> int:
    with patch(
        "app.routers.billing.stripe_client.verify_webhook",
        return_value=event,
    ):
        resp = client.post(
            "/api/v1/billing/webhook",
            data=json.dumps(event),
            headers={
                "stripe-signature": "test_sig",
                "content-type": "application/json",
            },
        )
    return resp.status_code


# ---------------------------------------------------------------------------
# HIGH-4 — one-time subscription extends instead of stacking
# ---------------------------------------------------------------------------

def test_onetime_subscription_extends_not_duplicates() -> None:
    """Buying the same one-time plan twice must extend current_period_end
    on the existing manual Subscription row, not create a second one."""
    ws = _seed_workspace_with_customer("cus_one_time")
    client = TestClient(main_module.app)
    event = {
        "id": "evt_onetime_1",
        "type": "checkout.session.completed",
        "data": {"object": {
            "mode": "payment",
            "customer": "cus_one_time",
            "metadata": {
                "mrai_workspace_id": ws,
                "mrai_plan": "pro",
                "mrai_cycle": "monthly",
                "mrai_one_time": "1",
            },
        }},
    }
    assert _post_event(client, event) == 200

    with _s.SessionLocal() as db:
        row1 = db.query(Subscription).filter_by(workspace_id=ws).one()
        first_end = row1.current_period_end
        assert row1.provider == "stripe_one_time"
        assert row1.status == "manual"

    # Second purchase of the same one-time plan.
    event2 = dict(event)
    event2["id"] = "evt_onetime_2"
    assert _post_event(client, event2) == 200

    with _s.SessionLocal() as db:
        rows = db.query(Subscription).filter_by(workspace_id=ws).all()
    # HIGH-4: exactly one row; the extant period is extended.
    assert len(rows) == 1, [
        (r.id, r.current_period_end, r.status) for r in rows
    ]

    def _aware(dt):
        if dt is None:
            return None
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
    assert _aware(rows[0].current_period_end) > _aware(first_end)


# ---------------------------------------------------------------------------
# HIGH-5 — trial can only be consumed once per workspace
# ---------------------------------------------------------------------------

def test_trial_period_not_granted_twice() -> None:
    """If the workspace already trialed (Subscription.trial_used_at set),
    a subsequent /checkout must NOT request trial_period_days."""
    client, ws_id, _ = _register("trial-reuse@x.co")

    # Stamp a past trial on the workspace.
    with _s.SessionLocal() as db:
        db.add(Subscription(
            workspace_id=ws_id, plan="pro", billing_cycle="monthly",
            status="canceled", provider="stripe_recurring",
            trial_used_at=datetime.now(timezone.utc) - timedelta(days=30),
        ))
        db.commit()

    captured: dict = {}

    def fake_session(**kwargs):
        captured.update(kwargs)
        return "https://checkout.stripe.com/pay/sess_notrial"

    with patch(
        "app.routers.billing.stripe_client.get_or_create_customer",
        return_value="cus_x",
    ), patch(
        "app.routers.billing.stripe_client.create_checkout_session_subscription",
        side_effect=fake_session,
    ):
        resp = client.post(
            "/api/v1/billing/checkout",
            json={"plan": "pro", "cycle": "monthly"},
        )
    assert resp.status_code == 200, resp.text
    assert captured["trial_period_days"] is None


def test_has_active_subscription_blocks_new_checkout() -> None:
    """If a workspace already has an active/past_due/manual sub, /checkout
    must return 409 subscription_exists instead of opening a parallel Pro."""
    client, ws_id, _ = _register("active-sub@x.co")
    with _s.SessionLocal() as db:
        db.add(Subscription(
            workspace_id=ws_id, plan="pro", billing_cycle="monthly",
            status="active", provider="stripe_recurring",
            stripe_subscription_id="sub_existing",
        ))
        db.commit()

    resp = client.post(
        "/api/v1/billing/checkout",
        json={"plan": "power", "cycle": "monthly"},
    )
    assert resp.status_code == 409, resp.text
    body = resp.json()
    code = body.get("error", {}).get("code") or body.get("code")
    assert code == "subscription_exists", body


# ---------------------------------------------------------------------------
# HIGH-8 — resolve_entitlement is pure-read + expired override fallback
# ---------------------------------------------------------------------------

def test_resolve_entitlement_is_read_only() -> None:
    """resolve_entitlement must not emit writes/commits. We count the
    number of UPDATE/INSERT statements during the call."""
    from app.core.entitlements import refresh_workspace_entitlements, resolve_entitlement

    with _s.SessionLocal() as db:
        ws = Workspace(name="W"); db.add(ws); db.commit(); db.refresh(ws)
        db.add(Subscription(
            workspace_id=ws.id, plan="free", billing_cycle="none",
            status="active", provider="free",
        ))
        db.commit()
        refresh_workspace_entitlements(db, workspace_id=ws.id)
        # Now corrupt a plan row so the old code would've self-healed.
        ent = db.query(Entitlement).filter_by(
            workspace_id=ws.id, key="notebooks.max",
        ).first()
        ent.value_int = 999
        db.add(ent); db.commit()
        ws_id = ws.id

    writes: list[str] = []
    from sqlalchemy import event as sa_event

    def _capture(conn, cursor, statement, parameters, context, executemany):
        head = statement.split(None, 1)[0].lower() if statement else ""
        if head in {"update", "insert", "delete"}:
            writes.append(head)

    sa_event.listen(_s.engine, "before_cursor_execute", _capture)
    try:
        with _s.SessionLocal() as db:
            value = resolve_entitlement(
                db, workspace_id=ws_id, key="notebooks.max",
            )
    finally:
        sa_event.remove(_s.engine, "before_cursor_execute", _capture)

    # Free plan notebooks.max is 1. The stored row still says 999 but
    # the resolver returns the plan mapping.
    assert value == 1
    assert writes == [], f"resolve_entitlement emitted writes: {writes}"


def test_expired_admin_override_falls_back_to_plan() -> None:
    """An expired admin_override Entitlement must NOT leak through —
    resolve_entitlement should return the plan default."""
    from app.core.entitlements import resolve_entitlement

    with _s.SessionLocal() as db:
        ws = Workspace(name="W"); db.add(ws); db.commit(); db.refresh(ws)
        db.add(Subscription(
            workspace_id=ws.id, plan="free", billing_cycle="none",
            status="active", provider="free",
        ))
        db.commit()
        db.add(Entitlement(
            workspace_id=ws.id, key="voice.enabled", value_bool=True,
            source="admin_override",
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        ))
        db.commit()
        ws_id = ws.id

    with _s.SessionLocal() as db:
        value = resolve_entitlement(db, workspace_id=ws_id, key="voice.enabled")
    # Free plan voice.enabled is False — override expired, so we fall back.
    assert value is False


# ---------------------------------------------------------------------------
# HIGH-9 — uploads.presign is gated on book_upload.enabled and URL source
# ---------------------------------------------------------------------------

def test_uploads_presign_requires_book_upload_entitlement(monkeypatch) -> None:
    """When book_upload.enabled is False for the workspace's plan the
    /uploads/presign gate must 402 before touching any uploader logic."""
    from app.services.plan_entitlements import PLAN_ENTITLEMENTS

    # Flip the default so Free now has book_upload.enabled=False. We
    # restore it after the test.
    original = PLAN_ENTITLEMENTS["free"]["book_upload.enabled"]
    monkeypatch.setitem(PLAN_ENTITLEMENTS["free"], "book_upload.enabled", False)
    try:
        client, _, _ = _register("upload-gate@x.co")
        # Seed a project + dataset so the request gets past pre-gate
        # validation (but it shouldn't — the entitlement gate fires first).
        project = client.post(
            "/api/v1/projects",
            json={"name": "P", "description": "x", "default_chat_mode": "standard"},
        ).json()
        dataset = client.post(
            "/api/v1/datasets",
            json={"project_id": project["id"], "name": "D", "type": "images"},
        ).json()
        resp = client.post(
            "/api/v1/uploads/presign",
            json={
                "dataset_id": dataset["id"],
                "filename": "book.pdf",
                "media_type": "application/pdf",
                "size_bytes": 1024,
            },
        )
        assert resp.status_code == 402, resp.text
        body = resp.json()
        assert (body.get("error", {}).get("code")
                or body.get("code")) == "plan_required"
    finally:
        PLAN_ENTITLEMENTS["free"]["book_upload.enabled"] = original


def test_upload_proxy_url_uses_site_url_not_base_url(monkeypatch) -> None:
    """presign_upload must build put_url from settings.site_url, not from
    request.base_url (HIGH-9 V8). Verify by sending a bogus Host header
    and confirming the URL remains rooted at the configured site_url."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "site_url", "https://canonical.mrai.test")
    # Force the proxy-upload branch on regardless of env defaults.
    monkeypatch.setattr(settings, "upload_put_proxy", True)

    client, _, _ = _register("upload-host@x.co")
    project = client.post(
        "/api/v1/projects",
        json={"name": "P", "description": "x", "default_chat_mode": "standard"},
    ).json()
    dataset = client.post(
        "/api/v1/datasets",
        json={"project_id": project["id"], "name": "D", "type": "images"},
    ).json()
    # Don't use a forged Host header here — TrustedHostMiddleware rejects
    # those at 400, which would short-circuit before presign runs. Instead
    # rely on TestClient's default base_url of http://testserver and
    # confirm put_url comes from the server-owned site_url, not from
    # request.base_url.
    resp = client.post(
        "/api/v1/uploads/presign",
        json={
            "dataset_id": dataset["id"],
            "filename": "book.pdf",
            "media_type": "application/pdf",
            "size_bytes": 16,
        },
    )
    assert resp.status_code == 200, resp.text
    put_url = resp.json()["put_url"]
    assert put_url.startswith("https://canonical.mrai.test/"), put_url
    assert "testserver" not in put_url


# ---------------------------------------------------------------------------
# HIGH-10 — failed AI actions also flush buffered usage events
# ---------------------------------------------------------------------------

def test_flush_failure_also_flushes_usage_events() -> None:
    """Even when the wrapped body raises after record_usage() fires, the
    AIUsageEvent rows must land so the quota counter advances (tokens
    were spent). Previously _flush_failure silently dropped them."""
    with _s.SessionLocal() as db:
        ws = Workspace(name="W")
        user = User(email="u@x.co", password_hash="x")
        db.add(ws); db.add(user); db.commit(); db.refresh(ws); db.refresh(user)
        ws_id, user_id = ws.id, user.id

    async def go() -> str:
        with _s.SessionLocal() as db:
            try:
                async with action_log_context(
                    db, workspace_id=ws_id, user_id=user_id,
                    action_type="selection.rewrite", scope="selection",
                ) as log:
                    log.record_usage(
                        event_type="llm_completion",
                        model_id="qwen-plus",
                        prompt_tokens=1000,
                        completion_tokens=500,
                        count_source="exact",
                    )
                    captured = log.log_id
                    raise RuntimeError("post-usage boom")
            except RuntimeError:
                return captured
        return ""

    log_id = asyncio.run(go())
    assert log_id

    with _s.SessionLocal() as db:
        row = db.query(AIActionLog).filter_by(id=log_id).one()
        events = db.query(AIUsageEvent).filter_by(action_log_id=log_id).all()
    assert row.status == "failed"
    assert len(events) == 1, [
        (e.event_type, e.prompt_tokens) for e in events
    ]
    assert events[0].prompt_tokens == 1000
    assert events[0].total_tokens == 1500


# ---------------------------------------------------------------------------
# MEDIUM-11 — invoice.paid reads authoritative period_end from Stripe
# ---------------------------------------------------------------------------

def test_invoice_paid_reads_authoritative_period_end_from_stripe() -> None:
    ws = _seed_workspace_with_customer("cus_invoice")
    with _s.SessionLocal() as db:
        db.add(Subscription(
            workspace_id=ws, plan="pro", billing_cycle="monthly",
            status="active", provider="stripe_recurring",
            stripe_subscription_id="sub_invoice",
            current_period_end=datetime.now(timezone.utc),
        ))
        db.commit()

    # Invoice carries a period_end that is *narrower* than the
    # subscription's; we must trust the Subscription retrieve() instead.
    authoritative_end = int(
        (datetime.now(timezone.utc) + timedelta(days=60)).timestamp()
    )
    narrower_invoice_end = int(
        (datetime.now(timezone.utc) + timedelta(days=3)).timestamp()
    )

    client = TestClient(main_module.app)
    event = {
        "id": "evt_invoice_paid_1",
        "type": "invoice.paid",
        "data": {"object": {
            "subscription": "sub_invoice",
            "period_end": narrower_invoice_end,
        }},
    }
    with patch(
        "app.services.billing_webhook.stripe.Subscription.retrieve",
        return_value={
            "id": "sub_invoice",
            "status": "active",
            "current_period_end": authoritative_end,
            "current_period_start": int(datetime.now(timezone.utc).timestamp()),
            "cancel_at_period_end": False,
            "items": {"data": []},
        },
    ) as mock_retrieve:
        assert _post_event(client, event) == 200
    mock_retrieve.assert_called_once_with("sub_invoice")

    with _s.SessionLocal() as db:
        sub = db.query(Subscription).filter_by(
            stripe_subscription_id="sub_invoice",
        ).one()
    end = sub.current_period_end
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    # Authoritative Stripe period_end (~60 days), not the invoice's 3.
    delta = end - datetime.now(timezone.utc)
    assert delta.days > 30, f"delta.days={delta.days}"


# ---------------------------------------------------------------------------
# MEDIUM-12 — get_or_create_customer reuses via Stripe search
# ---------------------------------------------------------------------------

def test_get_or_create_customer_reuses_via_search() -> None:
    """If Stripe already has a Customer tagged with this workspace's
    metadata, get_or_create_customer must reuse it instead of creating
    another orphan."""
    search_result = {"data": [{"id": "cus_existing"}]}

    with patch(
        "app.services.stripe_client.stripe.Customer.search",
        return_value=search_result,
    ) as mock_search, patch(
        "app.services.stripe_client.stripe.Customer.create",
    ) as mock_create:
        cid = stripe_client_module.get_or_create_customer(
            workspace_id="ws_abc", email="u@x.co",
        )
    assert cid == "cus_existing"
    mock_search.assert_called_once()
    mock_create.assert_not_called()


# ---------------------------------------------------------------------------
# MEDIUM-16 — /billing/plans no longer leaks raw price_id
# ---------------------------------------------------------------------------

def test_plans_endpoint_does_not_leak_stripe_price_id() -> None:
    client, _, _ = _register("plans-leak@x.co")
    resp = client.get("/api/v1/billing/plans")
    assert resp.status_code == 200, resp.text
    for plan in resp.json()["plans"]:
        if plan["id"] == "free":
            continue
        for cycle, pid in plan["stripe_prices"].items():
            assert pid is None or not pid.startswith("price_"), (
                f"{plan['id']} {cycle} leaks raw price_id: {pid}"
            )


# ---------------------------------------------------------------------------
# LOW-18 — charge.refunded cancels the manual subscription
# ---------------------------------------------------------------------------

def test_charge_refunded_cancels_manual_subscription() -> None:
    ws = _seed_workspace_with_customer("cus_refund")
    with _s.SessionLocal() as db:
        db.add(Subscription(
            workspace_id=ws, plan="pro", billing_cycle="monthly",
            status="manual", provider="stripe_one_time",
            current_period_end=datetime.now(timezone.utc) + timedelta(days=20),
        ))
        db.commit()

    client = TestClient(main_module.app)
    event = {
        "id": "evt_refund_1",
        "type": "charge.refunded",
        "data": {"object": {
            "customer": "cus_refund",
            "metadata": {"mrai_workspace_id": ws},
        }},
    }
    assert _post_event(client, event) == 200

    with _s.SessionLocal() as db:
        sub = db.query(Subscription).filter_by(workspace_id=ws).one()
        ws_row = db.get(Workspace, ws)
    assert sub.status == "canceled"
    assert ws_row.plan == "free"


# ---------------------------------------------------------------------------
# LOW-20 — subscription.updated refreshes seats from items
# ---------------------------------------------------------------------------

def test_subscription_updated_refreshes_seats_from_items() -> None:
    ws = _seed_workspace_with_customer("cus_seats")
    with _s.SessionLocal() as db:
        db.add(Subscription(
            workspace_id=ws, plan="team", billing_cycle="monthly",
            status="active", provider="stripe_recurring",
            stripe_subscription_id="sub_seats",
            seats=1,
        ))
        db.commit()

    client = TestClient(main_module.app)
    now = int(datetime.now(timezone.utc).timestamp())
    event = {
        "id": "evt_seat_update",
        "type": "customer.subscription.updated",
        "data": {"object": {
            "id": "sub_seats",
            "status": "active",
            "cancel_at_period_end": False,
            "current_period_start": now,
            "current_period_end": now + 86_400 * 30,
            "items": {"data": [{
                "id": "si_1",
                "price": {"id": "price_team_monthly"},
                "quantity": 7,
            }]},
        }},
    }
    assert _post_event(client, event) == 200

    with _s.SessionLocal() as db:
        sub = db.query(Subscription).filter_by(
            stripe_subscription_id="sub_seats",
        ).one()
    assert sub.seats == 7


# ---------------------------------------------------------------------------
# LOW-21 — webhook cross-validates metadata plan against subscription price
# ---------------------------------------------------------------------------

def test_checkout_metadata_cross_validated_with_price() -> None:
    """If the client-supplied mrai_plan claims 'power' but the Stripe
    subscription is actually on the Pro price, the webhook must refuse
    to apply the mismatched plan upgrade."""
    ws = _seed_workspace_with_customer("cus_spoof")
    pro_monthly_price = config_module.settings.stripe_price_pro_monthly

    client = TestClient(main_module.app)
    event = {
        "id": "evt_mismatch",
        "type": "checkout.session.completed",
        "data": {"object": {
            "mode": "subscription",
            "customer": "cus_spoof",
            "subscription": "sub_mismatch",
            "metadata": {
                "mrai_workspace_id": ws,
                # Client claims power, but Stripe paid for Pro below.
                "mrai_plan": "power",
                "mrai_cycle": "monthly",
            },
        }},
    }

    with patch(
        "app.services.billing_webhook.stripe.Subscription.retrieve",
        return_value={
            "id": "sub_mismatch",
            "status": "active",
            "current_period_start": int(datetime.now(timezone.utc).timestamp()),
            "current_period_end": int(
                (datetime.now(timezone.utc) + timedelta(days=30)).timestamp()
            ),
            "cancel_at_period_end": False,
            "items": {"data": [{
                "id": "si_spoof",
                "price": {"id": pro_monthly_price},
                "quantity": 1,
            }]},
        },
    ):
        assert _post_event(client, event) == 200

    with _s.SessionLocal() as db:
        rows = db.query(Subscription).filter_by(workspace_id=ws).all()
    # No Subscription was written because metadata.plan != stripe price.
    assert rows == []
