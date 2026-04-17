# ruff: noqa: E402
import atexit, importlib, json, os, shutil, tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-s6-wh-"))
atexit.register(lambda: shutil.rmtree(TEST_TEMP_DIR, ignore_errors=True))
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_TEMP_DIR / 'test.db'}"
os.environ["ENV"] = "test"
os.environ["COOKIE_DOMAIN"] = ""
os.environ["DEMO_MODE"] = "true"
os.environ["STRIPE_API_KEY"] = "sk_test_dummy"
os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_dummy"

import app.core.config as config_module
config_module.get_settings.cache_clear()
config_module.settings = config_module.get_settings()
import app.db.session as session_module
importlib.reload(session_module)
import app.main as main_module
importlib.reload(main_module)

from unittest.mock import patch
from fastapi.testclient import TestClient

from app.db.base import Base
import app.db.session as _s
from app.models import (
    BillingEvent, CustomerAccount, Subscription, User, Workspace,
)


def setup_function() -> None:
    Base.metadata.drop_all(bind=_s.engine)
    Base.metadata.create_all(bind=_s.engine)


def _seed_workspace_with_customer(stripe_customer_id: str = "cus_t") -> str:
    with _s.SessionLocal() as db:
        ws = Workspace(name="W"); user = User(email="u@x.co", password_hash="x")
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
            headers={"stripe-signature": "test_sig",
                     "content-type": "application/json"},
        )
    return resp.status_code


def test_checkout_session_completed_subscription_creates_row() -> None:
    ws = _seed_workspace_with_customer("cus_a")
    client = TestClient(main_module.app)
    period_end = int((datetime.now(timezone.utc) + timedelta(days=30)).timestamp())
    event = {
        "id": "evt_1",
        "type": "checkout.session.completed",
        "data": {"object": {
            "mode": "subscription",
            "customer": "cus_a",
            "subscription": "sub_1",
            "metadata": {"mrai_workspace_id": ws,
                         "mrai_plan": "pro", "mrai_cycle": "monthly"},
        }},
    }
    with patch(
        "app.services.billing_webhook.stripe.Subscription.retrieve",
        return_value={"id": "sub_1", "status": "active",
                      "current_period_start": int(datetime.now(timezone.utc).timestamp()),
                      "current_period_end": period_end,
                      "cancel_at_period_end": False,
                      "items": {"data": []}},
    ):
        code = _post_event(client, event)
    assert code == 200
    with _s.SessionLocal() as db:
        sub = db.query(Subscription).filter_by(workspace_id=ws).first()
    assert sub and sub.plan == "pro" and sub.status == "active"


def test_checkout_session_completed_payment_creates_one_time() -> None:
    ws = _seed_workspace_with_customer("cus_b")
    client = TestClient(main_module.app)
    event = {
        "id": "evt_2",
        "type": "checkout.session.completed",
        "data": {"object": {
            "mode": "payment",
            "customer": "cus_b",
            "metadata": {"mrai_workspace_id": ws,
                         "mrai_plan": "pro", "mrai_cycle": "yearly",
                         "mrai_one_time": "1"},
        }},
    }
    code = _post_event(client, event)
    assert code == 200
    with _s.SessionLocal() as db:
        sub = db.query(Subscription).filter_by(workspace_id=ws).first()
    assert sub.provider == "stripe_one_time"
    assert sub.status == "manual"
    assert sub.current_period_end is not None
    # SQLite returns naive datetime; coerce both sides for comparison.
    end = sub.current_period_end
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    delta = end - datetime.now(timezone.utc)
    assert 363 <= delta.days <= 366


def test_subscription_deleted_downgrades_to_free() -> None:
    ws = _seed_workspace_with_customer("cus_c")
    with _s.SessionLocal() as db:
        db.add(Subscription(
            workspace_id=ws, plan="pro", billing_cycle="monthly",
            status="active", provider="stripe_recurring",
            stripe_subscription_id="sub_c",
        ))
        db.commit()
    client = TestClient(main_module.app)
    event = {
        "id": "evt_3",
        "type": "customer.subscription.deleted",
        "data": {"object": {"id": "sub_c", "status": "canceled"}},
    }
    code = _post_event(client, event)
    assert code == 200
    with _s.SessionLocal() as db:
        sub = db.query(Subscription).filter_by(stripe_subscription_id="sub_c").first()
    assert sub.status == "canceled"


def test_invoice_payment_failed_marks_past_due() -> None:
    ws = _seed_workspace_with_customer("cus_d")
    with _s.SessionLocal() as db:
        db.add(Subscription(
            workspace_id=ws, plan="pro", billing_cycle="monthly",
            status="active", provider="stripe_recurring",
            stripe_subscription_id="sub_d",
        ))
        db.commit()
    client = TestClient(main_module.app)
    event = {
        "id": "evt_4",
        "type": "invoice.payment_failed",
        "data": {"object": {"subscription": "sub_d"}},
    }
    _post_event(client, event)
    with _s.SessionLocal() as db:
        sub = db.query(Subscription).filter_by(stripe_subscription_id="sub_d").first()
    assert sub.status == "past_due"


def test_webhook_idempotency_same_event_twice() -> None:
    _seed_workspace_with_customer("cus_e")
    client = TestClient(main_module.app)
    event = {
        "id": "evt_5",
        "type": "customer.subscription.updated",
        "data": {"object": {"id": "sub_e", "status": "active",
                            "cancel_at_period_end": False,
                            "current_period_end": int(datetime.now(timezone.utc).timestamp()),
                            "current_period_start": int(datetime.now(timezone.utc).timestamp())}},
    }
    code1 = _post_event(client, event)
    code2 = _post_event(client, event)
    assert code1 == 200 and code2 == 200
    with _s.SessionLocal() as db:
        n_events = db.query(BillingEvent).filter_by(stripe_event_id="evt_5").count()
    assert n_events == 1


def test_webhook_invalid_signature_returns_400() -> None:
    client = TestClient(main_module.app)
    with patch(
        "app.routers.billing.stripe_client.verify_webhook",
        side_effect=ValueError("bad sig"),
    ):
        resp = client.post(
            "/api/v1/billing/webhook",
            data="{}", headers={"stripe-signature": "bad",
                                "content-type": "application/json"},
        )
    assert resp.status_code == 400
