"""Per-workspace storage usage + quota enforcement.

Used by the upload presign flow and the blank-document creation endpoint
so a single workspace can't fill the cluster's S3 with unbounded uploads
or with version snapshots from rapid-fire ONLYOFFICE saves.

Two interlocking optimizations vs the original implementation:

1. The two SUM aggregations (raw uploads + version snapshots) collapse
   into a single `UNION ALL` query so the DB does one round-trip instead
   of two. Both branches still benefit from existing indexes
   (`idx_data_items_dataset`, `idx_dv_item_version`) plus the
   `projects.workspace_id` btree.

2. The GET endpoint reads through a tiny Redis layer with a 60-second
   TTL — frontend usage badges don't need fresh-to-the-byte numbers and
   shaving the DB hit lets the badge poll on every page load without
   pressure. `assert_can_store` deliberately bypasses the cache so the
   quota gate never lets a stale value through.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.entitlements import resolve_entitlement
from app.core.errors import ApiError
from app.models import StorageReservation, Workspace
from app.services.runtime_state import runtime_state


logger = logging.getLogger(__name__)


# Cache lives in the existing Redis namespace; keys look like
# `<ns>:storage_usage:<workspace_id>`.
_USAGE_CACHE_SCOPE = "storage_usage"
_USAGE_CACHE_TTL_SECONDS = 60


@dataclass
class StorageUsage:
    workspace_id: str
    raw_bytes: int          # bytes used by live DataItem objects
    version_bytes: int      # bytes used by DocumentVersion snapshots
    reserved_bytes: int     # bytes reserved by pending DB upload sessions
    total_bytes: int        # raw + versions + pending reservations
    quota_bytes: int        # 0 = unlimited
    available_bytes: int    # max(0, quota - total); -1 if unlimited
    plan: str               # source plan name (e.g. "free", "pro")

    @property
    def is_unlimited(self) -> bool:
        return self.quota_bytes <= 0

    @property
    def is_over_quota(self) -> bool:
        return not self.is_unlimited and self.total_bytes >= self.quota_bytes

    def to_dict(self) -> dict[str, object]:
        return {
            "workspace_id": self.workspace_id,
            "raw_bytes": self.raw_bytes,
            "version_bytes": self.version_bytes,
            "reserved_bytes": self.reserved_bytes,
            "total_bytes": self.total_bytes,
            "quota_bytes": self.quota_bytes,
            "available_bytes": self.available_bytes,
            "is_unlimited": self.is_unlimited,
            "is_over_quota": self.is_over_quota,
            "plan": self.plan,
        }


def _resolve_quota_bytes(db: Session, *, workspace_id: str) -> tuple[int, str]:
    """Resolve `(quota_bytes, plan_code)` for a workspace.

    Reads the `storage.bytes.max` entitlement first — that's how plan tier
    lookups work elsewhere in the codebase. Falls back to the global
    `WORKSPACE_STORAGE_QUOTA_BYTES` env setting (handy for self-hosted
    deployments without billing). `-1` from either side means "unlimited"
    and is normalized to `0` (our internal "no limit" sentinel).
    """
    from app.core.entitlements import get_active_plan

    plan = get_active_plan(db, workspace_id=workspace_id)
    raw = resolve_entitlement(db, workspace_id=workspace_id, key="storage.bytes.max")
    if isinstance(raw, int):
        if raw <= 0:  # -1 or 0 → unlimited
            return 0, plan
        return raw, plan
    # No entitlement row and no plan default — fall back to settings.
    fallback = settings.workspace_storage_quota_bytes
    return (max(0, fallback), plan)


def _query_byte_totals(db: Session, *, workspace_id: str) -> tuple[int, int, int]:
    """One SQL round-trip that returns raw, version, and reserved bytes.

    The previous version issued two separate aggregate queries; this
    UNION ALL collapses them. Each branch reuses the same join chain
    (data_items -> datasets -> projects) to filter by workspace_id.
    Pending upload reservations are included so parallel presigns cannot
    each pass quota before any DataItem row exists.
    """
    # No `::text` casts: keep this query SQLite-compatible so unit tests
    # (which use a sqlite memory DB) still run. The literal strings are
    # already text in both dialects; the dual-aggregate trick still folds
    # the two SUMs into one round-trip.
    row = db.execute(
        sql_text(
            """
            SELECT
              COALESCE(SUM(CASE WHEN source = 'raw' THEN size ELSE 0 END), 0) AS raw_bytes,
              COALESCE(SUM(CASE WHEN source = 'version' THEN size ELSE 0 END), 0) AS version_bytes,
              COALESCE(SUM(CASE WHEN source = 'reserved' THEN size ELSE 0 END), 0) AS reserved_bytes
            FROM (
              SELECT 'raw' AS source, di.size_bytes AS size
              FROM data_items di
              JOIN datasets d ON d.id = di.dataset_id
              JOIN projects p ON p.id = d.project_id
              WHERE p.workspace_id = :workspace_id
                AND di.deleted_at IS NULL
                AND d.deleted_at IS NULL

              UNION ALL

              SELECT 'version' AS source, dv.size_bytes AS size
              FROM document_versions dv
              JOIN data_items di ON di.id = dv.data_item_id
              JOIN datasets d ON d.id = di.dataset_id
              JOIN projects p ON p.id = d.project_id
              WHERE p.workspace_id = :workspace_id
                AND di.deleted_at IS NULL
                AND d.deleted_at IS NULL

              UNION ALL

              SELECT 'reserved' AS source, sr.bytes_reserved AS size
              FROM storage_reservations sr
              WHERE sr.workspace_id = :workspace_id
                AND sr.status = 'pending'
                AND sr.expires_at > :now
            ) AS u
            """
        ),
        {
            "workspace_id": workspace_id,
            "now": datetime.now(timezone.utc),
        },
    ).fetchone()
    if row is None:
        return 0, 0, 0
    return int(row[0] or 0), int(row[1] or 0), int(row[2] or 0)


def _lock_workspace(db: Session, *, workspace_id: str) -> None:
    (
        db.query(Workspace)
        .filter(Workspace.id == workspace_id)
        .with_for_update()
        .first()
    )


def get_workspace_storage_usage(
    db: Session,
    *,
    workspace_id: str,
    use_cache: bool = True,
) -> StorageUsage:
    """Compute current S3 byte consumption for a workspace.

    `use_cache=True` (the default) returns a cached snapshot when one is
    fresh enough; the GET endpoint uses this. The quota gate calls with
    `use_cache=False` so it never serves a stale "you're under budget"
    answer to a request that's about to push the workspace over.
    """
    if use_cache:
        cached = runtime_state.get_json(_USAGE_CACHE_SCOPE, workspace_id)
        if cached:
            try:
                return StorageUsage(
                    workspace_id=str(cached["workspace_id"]),
                    raw_bytes=int(cached["raw_bytes"]),
                    version_bytes=int(cached["version_bytes"]),
                    reserved_bytes=int(cached.get("reserved_bytes") or 0),
                    total_bytes=int(cached["total_bytes"]),
                    quota_bytes=int(cached["quota_bytes"]),
                    available_bytes=int(cached["available_bytes"]),
                    plan=str(cached.get("plan") or "free"),
                )
            except (KeyError, TypeError, ValueError):
                # Schema drift between deploys — drop the bad row and
                # fall through to a fresh compute.
                runtime_state.delete(_USAGE_CACHE_SCOPE, workspace_id)

    raw_bytes, version_bytes, reserved_bytes = _query_byte_totals(
        db, workspace_id=workspace_id
    )
    quota, plan = _resolve_quota_bytes(db, workspace_id=workspace_id)
    total = raw_bytes + version_bytes + reserved_bytes
    available = -1 if quota <= 0 else max(0, quota - total)
    usage = StorageUsage(
        workspace_id=str(workspace_id),
        raw_bytes=raw_bytes,
        version_bytes=version_bytes,
        reserved_bytes=reserved_bytes,
        total_bytes=total,
        quota_bytes=quota,
        available_bytes=available,
        plan=plan,
    )

    try:
        runtime_state.set_json(
            _USAGE_CACHE_SCOPE,
            workspace_id,
            usage.to_dict(),
            ttl_seconds=_USAGE_CACHE_TTL_SECONDS,
        )
    except Exception:  # noqa: BLE001
        logger.debug("storage_quota: failed to cache usage row", exc_info=True)
    return usage


def invalidate_workspace_usage_cache(workspace_id: str) -> None:
    """Drop the cached usage row. Called from any path that adds or
    removes bytes (uploads complete, references create, version prune,
    workspace teardown) so the next read recomputes."""
    try:
        runtime_state.delete(_USAGE_CACHE_SCOPE, workspace_id)
    except Exception:  # noqa: BLE001
        logger.debug(
            "storage_quota: cache invalidation failed for ws %s", workspace_id,
            exc_info=True,
        )


def assert_can_store(
    db: Session,
    *,
    workspace_id: str,
    incoming_bytes: int,
    lock_workspace: bool = True,
) -> StorageUsage:
    """Raise 402 (plan upgrade required) if the upload would exceed quota.

    402 lets the frontend pop the same upgrade gate it already shows for
    AI quota / book uploads, instead of a generic 4xx. Returns the usage
    snapshot so callers can include it in trace metadata if useful.

    Always reads fresh: skips the Redis cache so a freshly-uploaded burst
    can't slip past the gate using a stale total.
    """
    if lock_workspace:
        _lock_workspace(db, workspace_id=workspace_id)
    usage = get_workspace_storage_usage(
        db, workspace_id=workspace_id, use_cache=False
    )
    if usage.is_unlimited:
        return usage
    if incoming_bytes <= 0:
        return usage
    projected = usage.total_bytes + int(incoming_bytes)
    if projected > usage.quota_bytes:
        raise ApiError(
            "storage_quota_exceeded",
            (
                "This upload would exceed the workspace storage quota "
                f"({usage.quota_bytes} bytes). "
                f"Currently using {usage.total_bytes} bytes; "
                f"need {incoming_bytes} more."
            ),
            status_code=402,
            details={
                "key": "storage.bytes.max",
                "plan": usage.plan,
                "quota_bytes": usage.quota_bytes,
                "used_bytes": usage.total_bytes,
                "incoming_bytes": int(incoming_bytes),
                "raw_bytes": usage.raw_bytes,
                "version_bytes": usage.version_bytes,
                "reserved_bytes": usage.reserved_bytes,
            },
        )
    return usage


def create_upload_reservation(
    db: Session,
    *,
    workspace_id: str,
    dataset_id: str,
    upload_id: str,
    data_item_id: str,
    object_key: str,
    bytes_reserved: int,
    expires_at: datetime,
) -> StorageReservation:
    """Atomically reserve storage bytes for a pending upload.

    The quota check and insert happen under the workspace row lock so a
    burst of presigned uploads cannot overbook the same remaining bytes.
    """
    assert_can_store(
        db,
        workspace_id=workspace_id,
        incoming_bytes=int(bytes_reserved),
        lock_workspace=True,
    )
    reservation = StorageReservation(
        workspace_id=workspace_id,
        dataset_id=dataset_id,
        upload_id=upload_id,
        data_item_id=data_item_id,
        object_key=object_key,
        bytes_reserved=int(bytes_reserved),
        status="pending",
        expires_at=expires_at,
    )
    db.add(reservation)
    db.flush()
    invalidate_workspace_usage_cache(workspace_id)
    return reservation


def consume_upload_reservation(
    db: Session,
    *,
    workspace_id: str,
    upload_id: str,
    data_item_id: str,
    final_size_bytes: int,
) -> StorageReservation | None:
    """Mark a pending reservation as consumed before DataItem commit.

    The pending reservation is counted in quota until this transaction
    commits the live DataItem row. If the final object is unexpectedly
    larger than reserved, only the delta is checked.
    """
    _lock_workspace(db, workspace_id=workspace_id)
    reservation = (
        db.query(StorageReservation)
        .filter(StorageReservation.upload_id == upload_id)
        .with_for_update()
        .first()
    )
    if reservation is None:
        assert_can_store(
            db,
            workspace_id=workspace_id,
            incoming_bytes=int(final_size_bytes),
            lock_workspace=False,
        )
        return None
    if (
        reservation.workspace_id != workspace_id
        or reservation.data_item_id != data_item_id
    ):
        raise ApiError("upload_reservation_mismatch", "Upload reservation mismatch", status_code=400)
    if reservation.status == "completed":
        return reservation
    if reservation.status != "pending":
        raise ApiError("upload_expired", "Upload reservation is no longer pending", status_code=404)
    expires_at = reservation.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        reservation.status = "released"
        reservation.released_at = datetime.now(timezone.utc)
        db.add(reservation)
        db.flush()
        raise ApiError("upload_expired", "Upload reservation expired", status_code=404)

    extra_bytes = max(0, int(final_size_bytes) - int(reservation.bytes_reserved or 0))
    if extra_bytes:
        assert_can_store(
            db,
            workspace_id=workspace_id,
            incoming_bytes=extra_bytes,
            lock_workspace=False,
        )
    reservation.status = "completed"
    reservation.completed_at = datetime.now(timezone.utc)
    db.add(reservation)
    db.flush()
    invalidate_workspace_usage_cache(workspace_id)
    return reservation


def release_upload_reservation(
    db: Session,
    *,
    upload_id: str,
    data_item_id: str | None = None,
) -> None:
    reservation = (
        db.query(StorageReservation)
        .filter(StorageReservation.upload_id == upload_id)
        .with_for_update()
        .first()
    )
    if reservation is None:
        return
    if data_item_id and reservation.data_item_id != data_item_id:
        return
    if reservation.status == "pending":
        reservation.status = "released"
        reservation.released_at = datetime.now(timezone.utc)
        db.add(reservation)
        db.flush()
        invalidate_workspace_usage_cache(str(reservation.workspace_id))
