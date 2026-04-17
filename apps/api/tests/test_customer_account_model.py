# ruff: noqa: E402
import atexit, importlib, os, shutil, tempfile
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-s6-cust-"))
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
from app.models import CustomerAccount, User, Workspace


def setup_function() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _seed_workspace() -> str:
    with SessionLocal() as db:
        ws = Workspace(name="W"); user = User(email="u@x.co", password_hash="x")
        db.add(ws); db.add(user); db.commit(); db.refresh(ws)
        return ws.id


def test_customer_account_basic_insert() -> None:
    ws_id = _seed_workspace()
    with SessionLocal() as db:
        ca = CustomerAccount(
            workspace_id=ws_id,
            stripe_customer_id="cus_test_123",
            email="biz@x.co",
        )
        db.add(ca); db.commit(); db.refresh(ca)
    assert ca.id
    assert ca.default_payment_method_id is None


def test_customer_account_workspace_unique() -> None:
    ws_id = _seed_workspace()
    with SessionLocal() as db:
        db.add(CustomerAccount(
            workspace_id=ws_id, stripe_customer_id="cus_a", email="a@x.co",
        ))
        db.commit()
    with SessionLocal() as db, pytest.raises(IntegrityError):
        db.add(CustomerAccount(
            workspace_id=ws_id, stripe_customer_id="cus_b", email="b@x.co",
        ))
        db.commit()


def test_customer_account_stripe_id_unique() -> None:
    ws1 = _seed_workspace()
    with SessionLocal() as db:
        ws2 = Workspace(name="W2"); db.add(ws2); db.commit(); db.refresh(ws2)
        ws2_id = ws2.id
        db.add(CustomerAccount(
            workspace_id=ws1, stripe_customer_id="cus_dup", email="a@x.co",
        ))
        db.commit()
    with SessionLocal() as db, pytest.raises(IntegrityError):
        db.add(CustomerAccount(
            workspace_id=ws2_id, stripe_customer_id="cus_dup", email="b@x.co",
        ))
        db.commit()
