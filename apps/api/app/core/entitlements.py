"""S6 Billing — entitlement resolver and FastAPI gate Depends."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_workspace_id, get_db_session
from app.core.errors import ApiError
from app.models import Entitlement, Subscription, Workspace
from app.services.plan_entitlements import (
    ENTITLEMENT_KEYS, get_plan_entitlements,
)


_ACTIVE_STATUSES = {"active", "past_due", "trialing", "manual"}


def _coerce_entitlement_value(value: Any) -> tuple[int | None, bool | None]:
    if isinstance(value, bool):
        return None, value
    if isinstance(value, int):
        return value, None
    return None, None


def _humanize_entitlement_key(key: str) -> str:
    labels = {
        "notebooks.max": "notebooks",
        "pages.max": "pages",
        "study_assets.max": "study materials",
        "ai.actions.monthly": "monthly AI actions",
        "book_upload.enabled": "study uploads",
        "daily_digest.enabled": "daily digests",
        "voice.enabled": "voice capture",
        "advanced_memory_insights.enabled": "advanced memory insights",
    }
    return labels.get(key, key.replace(".", " "))


def get_active_plan(db: Session, *, workspace_id: str) -> str:
    """Return the plan code of the workspace's active subscription, or 'free'."""
    sub = (
        db.query(Subscription)
        .filter(Subscription.workspace_id == workspace_id)
        .filter(Subscription.status.in_(_ACTIVE_STATUSES))
        .order_by(Subscription.created_at.desc())
        .first()
    )
    return sub.plan if sub else "free"


def refresh_workspace_entitlements(db: Session, *, workspace_id: str) -> None:
    """Recompute entitlements for the workspace from its active plan.

    Removes expired admin_override rows; upserts plan-source rows;
    keeps unexpired admin_override rows untouched.
    """
    plan = get_active_plan(db, workspace_id=workspace_id)
    plan_ents = get_plan_entitlements(plan)
    now = datetime.now(timezone.utc)

    existing = (
        db.query(Entitlement)
        .filter(Entitlement.workspace_id == workspace_id)
        .all()
    )
    by_key = {e.key: e for e in existing}

    # Drop expired overrides so plan defaults take over.
    for e in existing:
        exp = e.expires_at
        if exp is not None and exp.tzinfo is None:
            # SQLite returns naive datetimes; treat as UTC for comparison.
            exp = exp.replace(tzinfo=timezone.utc)
        if e.source == "admin_override" and exp and exp < now:
            db.delete(e)
            del by_key[e.key]

    # Flush deletes before inserting new rows to avoid UNIQUE constraint violation.
    db.flush()

    for key in ENTITLEMENT_KEYS:
        plan_value = plan_ents[key]
        ent = by_key.get(key)
        if ent is None:
            new = Entitlement(
                workspace_id=workspace_id, key=key, source="plan",
                value_int=plan_value if isinstance(plan_value, int) and not isinstance(plan_value, bool) else None,
                value_bool=plan_value if isinstance(plan_value, bool) else None,
            )
            db.add(new)
            continue
        if ent.source != "admin_override":
            ent.value_int = plan_value if isinstance(plan_value, int) and not isinstance(plan_value, bool) else None
            ent.value_bool = plan_value if isinstance(plan_value, bool) else None
            ent.source = "plan"
            db.add(ent)
    db.commit()


def resolve_entitlement(
    db: Session, *, workspace_id: str, key: str,
) -> int | bool | None:
    """Return the resolved entitlement value, or None if missing."""
    plan = get_active_plan(db, workspace_id=workspace_id)
    plan_value = get_plan_entitlements(plan).get(key)
    ent = (
        db.query(Entitlement)
        .filter(Entitlement.workspace_id == workspace_id)
        .filter(Entitlement.key == key)
        .first()
    )
    if ent is None:
        # Lazy fallback: read plan default without writing to DB.
        return plan_value
    if ent.source != "admin_override":
        expected_int, expected_bool = _coerce_entitlement_value(plan_value)
        if (
            ent.source != "plan"
            or ent.value_int != expected_int
            or ent.value_bool != expected_bool
        ):
            ent.source = "plan"
            ent.value_int = expected_int
            ent.value_bool = expected_bool
            db.add(ent)
            db.commit()
        return plan_value
    if ent.value_int is not None:
        return ent.value_int
    return ent.value_bool


def require_entitlement(
    key: str,
    *,
    counter: Callable[[Session, str], int] | None = None,
) -> Callable:
    """Returns a FastAPI Depends that enforces entitlement on the
    current workspace. Boolean entitlements raise 402 plan_required
    when False. Counted entitlements (non-bool, non -1) raise 402
    plan_limit_reached when current >= limit. counter signature:
    (db, workspace_id) -> int."""

    def _check(
        workspace_id: str = Depends(get_current_workspace_id),
        db: Session = Depends(get_db_session),
    ) -> None:
        value = resolve_entitlement(db, workspace_id=workspace_id, key=key)
        if isinstance(value, bool):
            if value is False:
                feature = _humanize_entitlement_key(key)
                raise ApiError(
                    "plan_required",
                    f"Your plan doesn't include {feature}",
                    status_code=402,
                    details={"key": key},
                )
            return
        if isinstance(value, int):
            if value == -1:
                return
            if counter is None:
                return
            # Serialize concurrent counted-quota checks for this workspace
            # by acquiring a row-level lock on the Workspace row. The lock
            # is held by the request's transaction until its eventual
            # commit (after the resource insert), so competing creators
            # block here and re-read the counter after the winner commits.
            # On SQLite with_for_update is a no-op, but SQLite's global
            # write lock already serializes writers.
            (
                db.query(Workspace)
                .filter(Workspace.id == workspace_id)
                .with_for_update()
                .first()
            )
            current = counter(db, workspace_id)
            if current >= value:
                feature = _humanize_entitlement_key(key)
                feature_title = feature[:1].upper() + feature[1:]
                raise ApiError(
                    "plan_limit_reached",
                    f"{feature_title} limit reached ({current}/{value})",
                    status_code=402,
                    details={"key": key, "current": current, "limit": value},
                )

    return _check
