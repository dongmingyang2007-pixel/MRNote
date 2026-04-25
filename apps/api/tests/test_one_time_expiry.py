# ruff: noqa: E402
import atexit, importlib, os, shutil, tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="mrnote-s6-exp-"))
atexit.register(lambda: shutil.rmtree(TEST_TEMP_DIR, ignore_errors=True))
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_TEMP_DIR / 'test.db'}"
os.environ["ENV"] = "test"

import app.core.config as config_module
config_module.get_settings.cache_clear()
config_module.settings = config_module.get_settings()
import app.db.session as session_module
importlib.reload(session_module)

from app.db.base import Base
import app.db.session as _s
from app.models import Subscription, User, Workspace


def setup_function() -> None:
    global engine, SessionLocal
    engine = _s.engine
    SessionLocal = _s.SessionLocal
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    import app.tasks.worker_tasks as _wt
    _wt.SessionLocal = _s.SessionLocal


engine = _s.engine
SessionLocal = _s.SessionLocal


def _seed_one_time_sub(plan: str = "pro", expired: bool = True) -> tuple[str, str]:
    with SessionLocal() as db:
        ws = Workspace(name="W", plan=plan); user = User(email="u@x.co", password_hash="x")
        db.add(ws); db.add(user); db.commit(); db.refresh(ws)
        end = datetime.now(timezone.utc) - timedelta(days=1) if expired else datetime.now(timezone.utc) + timedelta(days=10)
        sub = Subscription(
            workspace_id=ws.id, plan=plan, billing_cycle="monthly",
            status="manual", provider="stripe_one_time",
            current_period_end=end,
        )
        db.add(sub); db.commit(); db.refresh(sub)
        return ws.id, sub.id


def test_expiry_task_downgrades_workspace() -> None:
    ws_id, sub_id = _seed_one_time_sub()
    from app.tasks.worker_tasks import expire_one_time_subscriptions_task
    result = expire_one_time_subscriptions_task.run()
    assert result["expired"] == 1
    with SessionLocal() as db:
        ws = db.get(Workspace, ws_id)
        sub = db.get(Subscription, sub_id)
    assert ws.plan == "free"
    assert sub.status == "canceled"


def test_expiry_task_skips_unexpired() -> None:
    ws_id, sub_id = _seed_one_time_sub(expired=False)
    from app.tasks.worker_tasks import expire_one_time_subscriptions_task
    result = expire_one_time_subscriptions_task.run()
    assert result["expired"] == 0
    with SessionLocal() as db:
        sub = db.get(Subscription, sub_id)
    assert sub.status == "manual"


def test_expiry_task_idempotent() -> None:
    ws_id, _ = _seed_one_time_sub()
    from app.tasks.worker_tasks import expire_one_time_subscriptions_task
    r1 = expire_one_time_subscriptions_task.run()
    r2 = expire_one_time_subscriptions_task.run()
    assert r1["expired"] == 1
    assert r2["expired"] == 0
