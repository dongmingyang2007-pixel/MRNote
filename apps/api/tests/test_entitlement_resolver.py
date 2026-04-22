# ruff: noqa: E402
import atexit, importlib, os, shutil, tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-s6-resolver-"))
atexit.register(lambda: shutil.rmtree(TEST_TEMP_DIR, ignore_errors=True))
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_TEMP_DIR / 'test.db'}"
os.environ["ENV"] = "test"

import app.core.config as config_module
config_module.get_settings.cache_clear()
config_module.settings = config_module.get_settings()
import app.db.session as session_module
importlib.reload(session_module)

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models import Entitlement, Subscription, User, Workspace
from app.core.entitlements import (
    resolve_entitlement, refresh_workspace_entitlements,
    get_active_plan,
)


def setup_function() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _ws() -> str:
    with SessionLocal() as db:
        ws = Workspace(name="W"); user = User(email="u@x.co", password_hash="x")
        db.add(ws); db.add(user); db.commit(); db.refresh(ws)
        return ws.id


def test_no_subscription_returns_free_plan() -> None:
    ws = _ws()
    with SessionLocal() as db:
        plan = get_active_plan(db, workspace_id=ws)
    assert plan == "free"


def test_active_subscription_returns_its_plan() -> None:
    ws = _ws()
    with SessionLocal() as db:
        db.add(Subscription(
            workspace_id=ws, plan="pro", billing_cycle="monthly",
            status="active", provider="stripe_recurring",
        ))
        db.commit()
        plan = get_active_plan(db, workspace_id=ws)
    assert plan == "pro"


def test_canceled_subscription_falls_back_to_free() -> None:
    ws = _ws()
    with SessionLocal() as db:
        db.add(Subscription(
            workspace_id=ws, plan="pro", billing_cycle="monthly",
            status="canceled", provider="stripe_recurring",
        ))
        db.commit()
        plan = get_active_plan(db, workspace_id=ws)
    assert plan == "free"


def test_refresh_writes_all_8_entitlements() -> None:
    ws = _ws()
    with SessionLocal() as db:
        db.add(Subscription(
            workspace_id=ws, plan="pro", billing_cycle="monthly",
            status="active", provider="stripe_recurring",
        ))
        db.commit()
        refresh_workspace_entitlements(db, workspace_id=ws)
        rows = db.query(Entitlement).filter(
            Entitlement.workspace_id == ws,
        ).all()
    assert len(rows) == 8
    by_key = {r.key: r for r in rows}
    assert by_key["notebooks.max"].value_int == -1
    assert by_key["voice.enabled"].value_bool is True


def test_refresh_is_idempotent() -> None:
    ws = _ws()
    with SessionLocal() as db:
        db.add(Subscription(
            workspace_id=ws, plan="pro", billing_cycle="monthly",
            status="active", provider="stripe_recurring",
        ))
        db.commit()
        refresh_workspace_entitlements(db, workspace_id=ws)
        refresh_workspace_entitlements(db, workspace_id=ws)
        count = db.query(Entitlement).filter(
            Entitlement.workspace_id == ws,
        ).count()
    assert count == 8


def test_resolve_returns_int_for_counted_entitlement() -> None:
    ws = _ws()
    with SessionLocal() as db:
        db.add(Subscription(
            workspace_id=ws, plan="free", billing_cycle="none",
            status="active", provider="free",
        ))
        db.commit()
        refresh_workspace_entitlements(db, workspace_id=ws)
        v = resolve_entitlement(db, workspace_id=ws, key="notebooks.max")
    assert v == 1


def test_resolve_returns_bool_for_flag_entitlement() -> None:
    ws = _ws()
    with SessionLocal() as db:
        db.add(Subscription(
            workspace_id=ws, plan="free", billing_cycle="none",
            status="active", provider="free",
        ))
        db.commit()
        refresh_workspace_entitlements(db, workspace_id=ws)
        v = resolve_entitlement(db, workspace_id=ws, key="voice.enabled")
    assert v is False


def test_admin_override_wins_over_plan() -> None:
    ws = _ws()
    with SessionLocal() as db:
        db.add(Subscription(
            workspace_id=ws, plan="free", billing_cycle="none",
            status="active", provider="free",
        ))
        db.commit()
        refresh_workspace_entitlements(db, workspace_id=ws)
        ent = db.query(Entitlement).filter_by(
            workspace_id=ws, key="notebooks.max",
        ).first()
        ent.value_int = 999
        ent.source = "admin_override"
        db.add(ent); db.commit()
        v = resolve_entitlement(db, workspace_id=ws, key="notebooks.max")
    assert v == 999


def test_expired_override_falls_back_to_plan_via_refresh() -> None:
    ws = _ws()
    with SessionLocal() as db:
        db.add(Subscription(
            workspace_id=ws, plan="free", billing_cycle="none",
            status="active", provider="free",
        ))
        db.commit()
        db.add(Entitlement(
            workspace_id=ws, key="voice.enabled", value_bool=True,
            source="admin_override",
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        ))
        db.commit()
        refresh_workspace_entitlements(db, workspace_id=ws)
        v = resolve_entitlement(db, workspace_id=ws, key="voice.enabled")
    assert v is False


def test_resolve_self_heals_stale_plan_row_from_current_mapping() -> None:
    ws = _ws()
    with SessionLocal() as db:
        db.add(Subscription(
            workspace_id=ws, plan="free", billing_cycle="none",
            status="active", provider="free",
        ))
        db.commit()
        db.add(Entitlement(
            workspace_id=ws,
            key="book_upload.enabled",
            value_bool=False,
            source="plan",
        ))
        db.commit()

        v = resolve_entitlement(db, workspace_id=ws, key="book_upload.enabled")
        refreshed = db.query(Entitlement).filter_by(
            workspace_id=ws, key="book_upload.enabled",
        ).first()

    assert v is True
    assert refreshed is not None
    assert refreshed.value_bool is True
