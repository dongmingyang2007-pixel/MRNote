# ruff: noqa: E402
import atexit, importlib, os, shutil, tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="mrnote-s6-core-"))
atexit.register(lambda: shutil.rmtree(TEST_TEMP_DIR, ignore_errors=True))
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_TEMP_DIR / 'test.db'}"
os.environ["ENV"] = "test"

import app.core.config as config_module
config_module.get_settings.cache_clear()
config_module.settings = config_module.get_settings()
import app.db.session as session_module
importlib.reload(session_module)

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models import (
    BillingEvent, Entitlement, Subscription, SubscriptionItem,
    User, Workspace,
)


def setup_function() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _ws() -> str:
    with SessionLocal() as db:
        ws = Workspace(name="W"); user = User(email="u@x.co", password_hash="x")
        db.add(ws); db.add(user); db.commit(); db.refresh(ws)
        return ws.id


def test_subscription_basic_insert_with_defaults() -> None:
    ws = _ws()
    with SessionLocal() as db:
        sub = Subscription(
            workspace_id=ws,
            plan="pro", billing_cycle="monthly",
            status="active", provider="stripe_recurring",
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
        )
        db.add(sub); db.commit(); db.refresh(sub)
    assert sub.seats == 1
    assert sub.cancel_at_period_end is False


def test_subscription_stripe_id_unique() -> None:
    ws = _ws()
    with SessionLocal() as db:
        db.add(Subscription(
            workspace_id=ws, plan="pro", billing_cycle="monthly",
            status="active", provider="stripe_recurring",
            stripe_subscription_id="sub_dup",
        ))
        db.commit()
    with SessionLocal() as db, pytest.raises(IntegrityError):
        db.add(Subscription(
            workspace_id=ws, plan="power", billing_cycle="monthly",
            status="active", provider="stripe_recurring",
            stripe_subscription_id="sub_dup",
        ))
        db.commit()


def test_subscription_status_check_constraint() -> None:
    ws = _ws()
    with SessionLocal() as db, pytest.raises(IntegrityError):
        db.add(Subscription(
            workspace_id=ws, plan="pro", billing_cycle="monthly",
            status="bogus", provider="stripe_recurring",
        ))
        db.commit()


def test_subscription_plan_check_constraint() -> None:
    ws = _ws()
    with SessionLocal() as db, pytest.raises(IntegrityError):
        db.add(Subscription(
            workspace_id=ws, plan="ultra", billing_cycle="monthly",
            status="active", provider="stripe_recurring",
        ))
        db.commit()


def test_subscription_item_links_to_subscription() -> None:
    ws = _ws()
    with SessionLocal() as db:
        sub = Subscription(
            workspace_id=ws, plan="team", billing_cycle="monthly",
            status="active", provider="stripe_recurring", seats=5,
        )
        db.add(sub); db.commit(); db.refresh(sub)
        item = SubscriptionItem(
            subscription_id=sub.id,
            stripe_price_id="price_team_monthly",
            quantity=5,
        )
        db.add(item); db.commit(); db.refresh(item)
    assert item.quantity == 5


def test_entitlement_unique_workspace_key() -> None:
    ws = _ws()
    with SessionLocal() as db:
        db.add(Entitlement(
            workspace_id=ws, key="notebooks.max",
            value_int=50, source="plan",
        ))
        db.commit()
    with SessionLocal() as db, pytest.raises(IntegrityError):
        db.add(Entitlement(
            workspace_id=ws, key="notebooks.max",
            value_int=100, source="admin_override",
        ))
        db.commit()


def test_billing_event_stripe_id_unique() -> None:
    with SessionLocal() as db:
        db.add(BillingEvent(
            stripe_event_id="evt_test_1",
            event_type="checkout.session.completed",
            payload_json={"foo": "bar"},
        ))
        db.commit()
    with SessionLocal() as db, pytest.raises(IntegrityError):
        db.add(BillingEvent(
            stripe_event_id="evt_test_1",
            event_type="customer.subscription.updated",
            payload_json={},
        ))
        db.commit()
