from app.services.plan_entitlements import (
    PLAN_ENTITLEMENTS,
    ENTITLEMENT_KEYS,
    get_plan_entitlements,
)


def test_all_four_plans_present() -> None:
    assert set(PLAN_ENTITLEMENTS.keys()) == {"free", "pro", "power", "team"}


def test_each_plan_has_all_8_keys() -> None:
    expected_keys = {
        "notebooks.max", "pages.max", "study_assets.max",
        "ai.actions.monthly", "book_upload.enabled",
        "daily_digest.enabled", "voice.enabled",
        "advanced_memory_insights.enabled",
    }
    for plan, ents in PLAN_ENTITLEMENTS.items():
        assert set(ents.keys()) == expected_keys, f"plan {plan} missing keys"


def test_entitlement_keys_match() -> None:
    assert isinstance(ENTITLEMENT_KEYS, frozenset)
    assert len(ENTITLEMENT_KEYS) == 8


def test_free_plan_disables_premium_features() -> None:
    free = PLAN_ENTITLEMENTS["free"]
    assert free["voice.enabled"] is False
    assert free["daily_digest.enabled"] is False
    assert free["book_upload.enabled"] is False
    assert free["advanced_memory_insights.enabled"] is False


def test_power_unlimited_caps() -> None:
    power = PLAN_ENTITLEMENTS["power"]
    assert power["notebooks.max"] == -1
    assert power["pages.max"] == -1
    assert power["study_assets.max"] == -1


def test_get_plan_entitlements_returns_copy() -> None:
    ents = get_plan_entitlements("pro")
    ents["notebooks.max"] = 999
    assert PLAN_ENTITLEMENTS["pro"]["notebooks.max"] != 999


def test_get_plan_entitlements_unknown_plan_returns_free() -> None:
    ents = get_plan_entitlements("nonexistent")
    assert ents == PLAN_ENTITLEMENTS["free"]
