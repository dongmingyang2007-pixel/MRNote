# ruff: noqa: E402
import atexit, importlib, os, shutil, tempfile
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-s6-checkout-"))
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

from unittest.mock import patch
from fastapi.testclient import TestClient

from app.db.base import Base
import app.db.session as _s


def setup_function() -> None:
    Base.metadata.drop_all(bind=_s.engine)
    Base.metadata.create_all(bind=_s.engine)
    from app.services.runtime_state import runtime_state
    runtime_state._memory = runtime_state._memory.__class__()


def _public_headers() -> dict[str, str]:
    return {"origin": "http://localhost:3000"}


def _register_client(email: str = "u@x.co") -> tuple[TestClient, dict]:
    import hashlib
    from app.services.runtime_state import runtime_state
    client = TestClient(main_module.app)
    client.post("/api/v1/auth/send-code",
                json={"email": email, "purpose": "register"},
                headers=_public_headers())
    raw = f"{email.lower().strip()}:register"
    code_key = hashlib.sha256(raw.encode()).hexdigest()
    code = str(runtime_state.get_json("verify_code", code_key)["code"])
    info = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "pass1234pass",
              "display_name": "Test", "code": code},
        headers=_public_headers(),
    ).json()
    csrf = client.get("/api/v1/auth/csrf",
                     headers=_public_headers()).json()["csrf_token"]
    client.headers.update({
        "origin": "http://localhost:3000",
        "x-csrf-token": csrf,
        "x-workspace-id": info["workspace"]["id"],
    })
    return client, {"ws_id": info["workspace"]["id"],
                    "user_id": info["user"]["id"]}


def test_checkout_returns_url_and_creates_customer() -> None:
    client, _ = _register_client("u1@x.co")
    with patch(
        "app.routers.billing.stripe_client.get_or_create_customer",
        return_value="cus_test_1",
    ), patch(
        "app.routers.billing.stripe_client.create_checkout_session_subscription",
        return_value="https://checkout.stripe.com/pay/sess_x",
    ):
        resp = client.post(
            "/api/v1/billing/checkout",
            json={"plan": "pro", "cycle": "monthly"},
        )
    assert resp.status_code == 200, resp.text
    assert "checkout.stripe.com" in resp.json()["checkout_url"]
    from app.models import CustomerAccount
    with _s.SessionLocal() as db:
        ca = db.query(CustomerAccount).first()
    assert ca and ca.stripe_customer_id == "cus_test_1"


def test_checkout_team_uses_seat_quantity() -> None:
    client, _ = _register_client("u2@x.co")
    captured = {}

    def fake_session(**kwargs):
        captured.update(kwargs)
        return "https://checkout.stripe.com/pay/sess_y"

    with patch(
        "app.routers.billing.stripe_client.get_or_create_customer",
        return_value="cus_test_2",
    ), patch(
        "app.routers.billing.stripe_client.create_checkout_session_subscription",
        side_effect=fake_session,
    ):
        resp = client.post(
            "/api/v1/billing/checkout",
            json={"plan": "team", "cycle": "monthly", "seats": 5},
        )
    assert resp.status_code == 200, resp.text
    assert captured["quantity"] == 5


def test_checkout_invalid_plan_returns_422() -> None:
    client, _ = _register_client("u3@x.co")
    resp = client.post(
        "/api/v1/billing/checkout",
        json={"plan": "ultra", "cycle": "monthly"},
    )
    assert resp.status_code == 422


def test_checkout_onetime_uses_payment_mode() -> None:
    client, _ = _register_client("u4@x.co")
    captured = {}

    def fake_session(**kwargs):
        captured.update(kwargs)
        return "https://checkout.stripe.com/pay/sess_z"

    with patch(
        "app.routers.billing.stripe_client.get_or_create_customer",
        return_value="cus_test_4",
    ), patch(
        "app.routers.billing.stripe_client.create_checkout_session_one_time",
        side_effect=fake_session,
    ):
        resp = client.post(
            "/api/v1/billing/checkout-onetime",
            json={"plan": "pro", "cycle": "yearly", "payment_method": "alipay"},
        )
    assert resp.status_code == 200, resp.text
    assert captured["payment_method"] == "alipay"
    assert captured["unit_amount_cents"] == 10200


def test_portal_returns_url_when_customer_exists() -> None:
    client, _ = _register_client("u5@x.co")
    with patch(
        "app.routers.billing.stripe_client.get_or_create_customer",
        return_value="cus_test_5",
    ), patch(
        "app.routers.billing.stripe_client.create_checkout_session_subscription",
        return_value="https://checkout.stripe.com/pay/sess_p",
    ):
        client.post("/api/v1/billing/checkout",
                    json={"plan": "pro", "cycle": "monthly"})
    with patch(
        "app.routers.billing.stripe_client.create_billing_portal_session",
        return_value="https://billing.stripe.com/p/session/foo",
    ):
        resp = client.post("/api/v1/billing/portal", json={})
    assert resp.status_code == 200, resp.text
    assert "billing.stripe.com" in resp.json()["portal_url"]


def test_portal_returns_404_without_customer() -> None:
    client, _ = _register_client("u6@x.co")
    resp = client.post("/api/v1/billing/portal", json={})
    assert resp.status_code == 404


def test_checkout_pro_triggers_14_day_trial() -> None:
    client, _ = _register_client("trial@x.co")
    captured: dict = {}

    def fake_session(**kwargs):
        captured.update(kwargs)
        return "https://checkout.stripe.com/pay/sess_trial"

    with patch(
        "app.routers.billing.stripe_client.get_or_create_customer",
        return_value="cus_trial",
    ), patch(
        "app.routers.billing.stripe_client.create_checkout_session_subscription",
        side_effect=fake_session,
    ):
        resp = client.post(
            "/api/v1/billing/checkout",
            json={"plan": "pro", "cycle": "monthly"},
        )
    assert resp.status_code == 200, resp.text
    assert captured["trial_period_days"] == 14


def test_checkout_power_triggers_14_day_trial() -> None:
    client, _ = _register_client("trialpower@x.co")
    captured: dict = {}

    def fake_session(**kwargs):
        captured.update(kwargs)
        return "https://checkout.stripe.com/pay/sess_trial_power"

    with patch(
        "app.routers.billing.stripe_client.get_or_create_customer",
        return_value="cus_trial_power",
    ), patch(
        "app.routers.billing.stripe_client.create_checkout_session_subscription",
        side_effect=fake_session,
    ):
        resp = client.post(
            "/api/v1/billing/checkout",
            json={"plan": "power", "cycle": "yearly"},
        )
    assert resp.status_code == 200, resp.text
    assert captured["trial_period_days"] == 14


def test_checkout_team_skips_trial() -> None:
    client, _ = _register_client("notrial@x.co")
    captured: dict = {}

    def fake_session(**kwargs):
        captured.update(kwargs)
        return "https://checkout.stripe.com/pay/sess_notrial"

    with patch(
        "app.routers.billing.stripe_client.get_or_create_customer",
        return_value="cus_notrial",
    ), patch(
        "app.routers.billing.stripe_client.create_checkout_session_subscription",
        side_effect=fake_session,
    ):
        resp = client.post(
            "/api/v1/billing/checkout",
            json={"plan": "team", "cycle": "monthly", "seats": 3},
        )
    assert resp.status_code == 200, resp.text
    assert captured["trial_period_days"] is None
