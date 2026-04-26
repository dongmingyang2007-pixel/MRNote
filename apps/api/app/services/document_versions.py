from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import DataItem, DocumentVersion
from app.services import storage as storage_service


logger = logging.getLogger(__name__)


def write_version_snapshot(
    db: Session,
    *,
    item: DataItem,
    saved_by: str | None,
    saved_via: str = "onlyoffice",
    note: str | None = None,
) -> DocumentVersion:
    """Copy the current S3 object to a versioned key and record a row.

    Object key convention: workspaces/.../items/<id>/versions/v<N>/<filename>.
    """
    db.query(DataItem.id).filter(DataItem.id == item.id).with_for_update().one_or_none()
    next_version = (
        db.query(func.coalesce(func.max(DocumentVersion.version), 0))
        .filter(DocumentVersion.data_item_id == item.id)
        .scalar()
    ) + 1

    base_key = item.object_key
    # Replace `/raw/` with `/versions/vN/` in the object key, falling back
    # to appending `/versions/vN/<filename>` if `/raw/` isn't present.
    if "/raw/" in base_key:
        snapshot_key = base_key.replace(
            "/raw/", f"/versions/v{next_version}/", 1
        )
    else:
        prefix = base_key.rsplit("/", 1)[0]
        safe_name = storage_service.sanitize_filename(item.filename or "doc")
        snapshot_key = f"{prefix}/versions/v{next_version}/{safe_name}"

    # S3 server-side copy (cheap, no bytes through API)
    client = storage_service.get_s3_client()
    client.copy_object(
        Bucket=settings.s3_private_bucket,
        Key=snapshot_key,
        CopySource={
            "Bucket": settings.s3_private_bucket,
            "Key": item.object_key,
        },
    )

    record = DocumentVersion(
        data_item_id=item.id,
        version=next_version,
        object_key=snapshot_key,
        size_bytes=item.size_bytes or 0,
        sha256=item.sha256,
        media_type=item.media_type or "application/octet-stream",
        saved_via=saved_via,
        saved_by=saved_by,
        note=note,
    )
    db.add(record)
    db.flush()
    return record


def restore_version(
    db: Session,
    *,
    item: DataItem,
    version: DocumentVersion,
) -> None:
    """Server-side copy version snapshot back to the live key."""
    client = storage_service.get_s3_client()
    client.copy_object(
        Bucket=settings.s3_private_bucket,
        Key=item.object_key,
        CopySource={
            "Bucket": settings.s3_private_bucket,
            "Key": version.object_key,
        },
    )
    item.size_bytes = version.size_bytes
    item.sha256 = version.sha256
    item.media_type = version.media_type
    item.meta_json = {
        **(item.meta_json or {}),
        "upload_status": "completed",
        "restored_from_version": version.version,
        "restored_at": datetime.now(timezone.utc).isoformat(),
    }


def prune_versions_for_item(
    db: Session,
    *,
    data_item_id: str,
    keep_recent: int,
    keep_within_days: int,
) -> int:
    """Delete old `DocumentVersion` rows + their S3 objects.

    Retention rule: keep the `keep_recent` most-recent rows OR anything
    saved within the last `keep_within_days` days, whichever is broader.
    Returns the count deleted. Does not commit; caller must.
    """
    if keep_recent <= 0 and keep_within_days <= 0:
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(days=max(0, keep_within_days))

    # Pull every version for this item, newest first.
    rows = (
        db.query(DocumentVersion)
        .filter(DocumentVersion.data_item_id == data_item_id)
        .order_by(DocumentVersion.version.desc())
        .all()
    )
    if not rows:
        return 0

    # Anything in the top-N or newer than cutoff is kept.
    to_delete: list[DocumentVersion] = []
    for idx, row in enumerate(rows):
        within_recency = idx < keep_recent
        within_window = (
            row.created_at is not None
            and row.created_at.replace(tzinfo=timezone.utc) >= cutoff
            if row.created_at and row.created_at.tzinfo is None
            else (row.created_at is not None and row.created_at >= cutoff)
        )
        if within_recency or within_window:
            continue
        to_delete.append(row)

    if not to_delete:
        return 0

    client = storage_service.get_s3_client()
    deleted = 0
    for row in to_delete:
        try:
            client.delete_object(
                Bucket=settings.s3_private_bucket,
                Key=row.object_key,
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "prune_versions_for_item: failed to delete S3 key %s",
                row.object_key,
                exc_info=True,
            )
            # Still drop the DB row even if S3 delete fails — at worst we
            # leak a few bytes; we'd rather not retain a dead reference.
        db.delete(row)
        deleted += 1
    return deleted


def prune_versions_for_all_items(
    db: Session,
    *,
    keep_recent: int | None = None,
    keep_within_days: int | None = None,
) -> dict[str, int]:
    """Sweep every data_item and prune. Used by the nightly celery task."""
    keep_recent = (
        keep_recent
        if keep_recent is not None
        else settings.document_version_keep_recent
    )
    keep_within_days = (
        keep_within_days
        if keep_within_days is not None
        else settings.document_version_keep_days
    )

    # Items that have any versions — sweep just those, not every data_item.
    item_ids = [
        row[0]
        for row in db.query(DocumentVersion.data_item_id).distinct().all()
    ]
    total = 0
    items_touched = 0
    for item_id in item_ids:
        deleted = prune_versions_for_item(
            db,
            data_item_id=str(item_id),
            keep_recent=keep_recent,
            keep_within_days=keep_within_days,
        )
        if deleted:
            items_touched += 1
            total += deleted
    db.commit()
    return {
        "items_touched": items_touched,
        "versions_deleted": total,
        "scanned": len(item_ids),
    }
