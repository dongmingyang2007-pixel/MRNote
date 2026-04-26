"""S6 Billing — single source of truth for plan ↔ entitlement mapping."""

from __future__ import annotations

from typing import Any


_GB = 1024 * 1024 * 1024

PLAN_ENTITLEMENTS: dict[str, dict[str, Any]] = {
    "free": {
        "notebooks.max": 1,
        "pages.max": 50,
        "study_assets.max": 1,
        "ai.actions.monthly": 50,
        "book_upload.enabled": True,
        "daily_digest.enabled": False,
        "voice.enabled": False,
        "advanced_memory_insights.enabled": False,
        # Storage quota for raw uploads + DocumentVersion snapshots.
        # `-1` means unlimited; the `storage_quota` service treats -1 the
        # same as "no limit" and skips enforcement.
        "storage.bytes.max": 1 * _GB,
    },
    "pro": {
        "notebooks.max": -1,
        "pages.max": 500,
        "study_assets.max": 20,
        "ai.actions.monthly": 1000,
        "book_upload.enabled": True,
        "daily_digest.enabled": True,
        "voice.enabled": True,
        "advanced_memory_insights.enabled": False,
        "storage.bytes.max": 50 * _GB,
    },
    "power": {
        "notebooks.max": -1,
        "pages.max": -1,
        "study_assets.max": -1,
        "ai.actions.monthly": 10000,
        "book_upload.enabled": True,
        "daily_digest.enabled": True,
        "voice.enabled": True,
        "advanced_memory_insights.enabled": True,
        "storage.bytes.max": 500 * _GB,
    },
    "team": {
        "notebooks.max": -1,
        "pages.max": -1,
        "study_assets.max": -1,
        "ai.actions.monthly": 10000,
        "book_upload.enabled": True,
        "daily_digest.enabled": True,
        "voice.enabled": True,
        "advanced_memory_insights.enabled": True,
        # Team gets bigger storage to accommodate shared workspaces.
        "storage.bytes.max": 2 * 1024 * _GB,  # 2 TB
    },
}

ENTITLEMENT_KEYS: frozenset[str] = frozenset(PLAN_ENTITLEMENTS["free"].keys())


def get_plan_entitlements(plan: str) -> dict[str, Any]:
    """Return a fresh dict copy of entitlements for the given plan.
    Unknown plans fall back to free."""
    return dict(PLAN_ENTITLEMENTS.get(plan, PLAN_ENTITLEMENTS["free"]))
