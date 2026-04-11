from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.sanitize import sanitize_audit_meta
from app.models import AuditLog


def write_audit_log(
    db: Session,
    *,
    workspace_id: str | None,
    actor_user_id: str | None,
    action: str,
    target_type: str,
    target_id: str | None,
    meta_json: dict[str, Any] | None = None,
) -> None:
    log = AuditLog(
        workspace_id=workspace_id,
        actor_user_id=actor_user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        meta_json=sanitize_audit_meta(meta_json or {}),
        ts=datetime.now(timezone.utc),
    )
    db.add(log)
