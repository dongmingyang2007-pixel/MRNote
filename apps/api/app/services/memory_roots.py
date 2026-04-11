from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text as sql_text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.services.memory_metadata import (
    ACTIVE_NODE_STATUS,
    ROOT_NODE_TYPE,
    SUBJECT_NODE_TYPE,
    build_canonical_key,
    normalize_memory_metadata,
)
from app.services.schema_helpers import ensure_column

from app.models import Memory, Project
from app.services.memory_visibility import build_private_memory_metadata, get_memory_owner_user_id, is_private_memory

ASSISTANT_ROOT_NODE_KIND = "assistant-root"
ASSISTANT_ROOT_CATEGORY = "assistant"
USER_SUBJECT_KIND = "user"
USER_SUBJECT_LABEL = "用户"


def is_assistant_root_memory(memory: Memory | dict[str, Any] | None) -> bool:
    if memory is None:
        return False
    metadata = memory if isinstance(memory, dict) else (memory.metadata_json or {})
    return metadata.get("node_kind") == ASSISTANT_ROOT_NODE_KIND


def build_assistant_root_metadata(
    *,
    project_name: str,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = dict(existing or {})
    metadata["node_kind"] = ASSISTANT_ROOT_NODE_KIND
    metadata["node_type"] = ROOT_NODE_TYPE
    metadata["node_status"] = ACTIVE_NODE_STATUS
    metadata["canonical_key"] = "root"
    metadata["assistant_name"] = project_name
    metadata["system_managed"] = True
    return metadata


def _build_subject_metadata(
    *,
    label: str,
    subject_kind: str,
    owner_user_id: str | None = None,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        **(existing or {}),
        "node_kind": SUBJECT_NODE_TYPE,
        "node_type": SUBJECT_NODE_TYPE,
        "node_status": ACTIVE_NODE_STATUS,
        "subject_kind": subject_kind,
        "system_managed": True,
        "auto_generated": True,
        "canonical_key": build_canonical_key(
            content=label,
            category=subject_kind,
            node_type=SUBJECT_NODE_TYPE,
            subject_kind=subject_kind,
            metadata={"owner_user_id": owner_user_id} if owner_user_id else {},
        ),
    }
    if owner_user_id:
        metadata = build_private_memory_metadata(metadata, owner_user_id=owner_user_id)
    return normalize_memory_metadata(
        content=label,
        category=subject_kind,
        memory_type="permanent",
        metadata=metadata,
    )


def ensure_project_subject(
    db: Session,
    project: Project,
    *,
    subject_kind: str,
    label: str,
    owner_user_id: str | None = None,
) -> tuple[Memory, bool]:
    normalized_kind = str(subject_kind or "").strip().lower() or "custom"
    normalized_label = str(label or "").strip() or "未命名主体"
    root_memory, root_changed = ensure_project_assistant_root(db, project, reparent_orphans=False)
    candidates = (
        db.query(Memory)
        .filter(
            Memory.project_id == project.id,
            Memory.workspace_id == project.workspace_id,
            Memory.node_type == SUBJECT_NODE_TYPE,
            Memory.subject_kind == normalized_kind,
        )
        .all()
    )
    subject: Memory | None = None
    metadata = _build_subject_metadata(
        label=normalized_label,
        subject_kind=normalized_kind,
        owner_user_id=owner_user_id,
    )
    canonical_key = str(metadata.get("canonical_key") or "").strip() or None
    for candidate in candidates:
        candidate_owner = get_memory_owner_user_id(candidate) if is_private_memory(candidate) else None
        if candidate_owner != owner_user_id:
            continue
        if canonical_key and candidate.canonical_key == canonical_key:
            subject = candidate
            break
        if candidate.content.strip() == normalized_label:
            subject = candidate
            break

    changed = root_changed
    desired_parent_id = root_memory.id

    if subject is None:
        subject = Memory(
            workspace_id=project.workspace_id,
            project_id=project.id,
            content=normalized_label,
            category=normalized_kind,
            type="permanent",
            node_type=SUBJECT_NODE_TYPE,
            subject_kind=normalized_kind,
            source_conversation_id=None,
            parent_memory_id=desired_parent_id,
            subject_memory_id=None,
            node_status=ACTIVE_NODE_STATUS,
            canonical_key=canonical_key,
            position_x=None,
            position_y=None,
            metadata_json=metadata,
        )
        db.add(subject)
        db.flush()
        return subject, True

    if subject.content != normalized_label:
        subject.content = normalized_label
        changed = True
    if subject.category != normalized_kind:
        subject.category = normalized_kind
        changed = True
    if subject.type != "permanent":
        subject.type = "permanent"
        changed = True
    if subject.node_type != SUBJECT_NODE_TYPE:
        subject.node_type = SUBJECT_NODE_TYPE
        changed = True
    if subject.subject_kind != normalized_kind:
        subject.subject_kind = normalized_kind
        changed = True
    if subject.source_conversation_id is not None:
        subject.source_conversation_id = None
        changed = True
    if subject.parent_memory_id != desired_parent_id:
        subject.parent_memory_id = desired_parent_id
        changed = True
    if subject.subject_memory_id is not None:
        subject.subject_memory_id = None
        changed = True
    if subject.node_status != ACTIVE_NODE_STATUS:
        subject.node_status = ACTIVE_NODE_STATUS
        changed = True
    if subject.canonical_key != canonical_key:
        subject.canonical_key = canonical_key
        changed = True
    if subject.metadata_json != metadata:
        subject.metadata_json = metadata
        changed = True
    if changed:
        subject.updated_at = datetime.now(timezone.utc)
    return subject, changed


def get_project_assistant_root(db: Session, project: Project) -> Memory | None:
    if project.assistant_root_memory_id:
        root = (
            db.query(Memory)
            .filter(
                Memory.id == project.assistant_root_memory_id,
                Memory.project_id == project.id,
                Memory.workspace_id == project.workspace_id,
            )
            .first()
        )
        if root and is_assistant_root_memory(root):
            return root

    candidates = (
        db.query(Memory)
        .filter(
            Memory.project_id == project.id,
            Memory.workspace_id == project.workspace_id,
            Memory.type == "permanent",
        )
        .order_by(Memory.created_at.asc())
        .all()
    )
    root = next((candidate for candidate in candidates if is_assistant_root_memory(candidate)), None)
    if root and project.assistant_root_memory_id != root.id:
        project.assistant_root_memory_id = root.id
    return root


def ensure_project_assistant_root(
    db: Session,
    project: Project,
    *,
    reparent_orphans: bool = True,
) -> tuple[Memory, bool]:
    root = get_project_assistant_root(db, project)
    changed = False
    now = datetime.now(timezone.utc)
    desired_name = (project.name or "").strip() or "Assistant"

    if root is None:
        root = Memory(
            workspace_id=project.workspace_id,
            project_id=project.id,
            content=desired_name,
            category=ASSISTANT_ROOT_CATEGORY,
            type="permanent",
            node_type=ROOT_NODE_TYPE,
            subject_kind=None,
            source_conversation_id=None,
            parent_memory_id=None,
            subject_memory_id=None,
            node_status=ACTIVE_NODE_STATUS,
            canonical_key="root",
            position_x=0,
            position_y=0,
            metadata_json=build_assistant_root_metadata(project_name=desired_name),
        )
        db.add(root)
        db.flush()
        changed = True

    if project.assistant_root_memory_id != root.id:
        project.assistant_root_memory_id = root.id
        changed = True

    next_metadata = build_assistant_root_metadata(
        project_name=desired_name,
        existing=root.metadata_json,
    )
    if root.content != desired_name:
        root.content = desired_name
        changed = True
    if root.category != ASSISTANT_ROOT_CATEGORY:
        root.category = ASSISTANT_ROOT_CATEGORY
        changed = True
    if root.type != "permanent":
        root.type = "permanent"
        changed = True
    if root.node_type != ROOT_NODE_TYPE:
        root.node_type = ROOT_NODE_TYPE
        changed = True
    if root.subject_kind is not None:
        root.subject_kind = None
        changed = True
    if root.source_conversation_id is not None:
        root.source_conversation_id = None
        changed = True
    if root.parent_memory_id is not None:
        root.parent_memory_id = None
        changed = True
    if root.subject_memory_id is not None:
        root.subject_memory_id = None
        changed = True
    if root.node_status != ACTIVE_NODE_STATUS:
        root.node_status = ACTIVE_NODE_STATUS
        changed = True
    if root.canonical_key != "root":
        root.canonical_key = "root"
        changed = True
    if root.metadata_json != next_metadata:
        root.metadata_json = next_metadata
        changed = True
    if changed:
        root.updated_at = now

    if reparent_orphans:
        orphan_memories = (
            db.query(Memory)
            .filter(
                Memory.project_id == project.id,
                Memory.workspace_id == project.workspace_id,
                Memory.id != root.id,
                Memory.parent_memory_id.is_(None),
            )
            .all()
        )
        for memory in orphan_memories:
            memory.parent_memory_id = root.id
            memory.updated_at = now
            changed = True

    return root, changed


def ensure_project_user_subject(
    db: Session,
    project: Project,
    *,
    owner_user_id: str | None = None,
    label: str = USER_SUBJECT_LABEL,
) -> tuple[Memory, bool]:
    return ensure_project_subject(
        db,
        project,
        subject_kind=USER_SUBJECT_KIND,
        label=label,
        owner_user_id=owner_user_id,
    )


def ensure_project_memory_root_schema(engine: Engine) -> None:
    ensure_column(engine, "conversations", "metadata_json", "JSON", nullable=False, default="'{}'")
    ensure_column(engine, "memories", "node_type", "TEXT", nullable=False, default="'fact'")
    ensure_column(engine, "memories", "subject_kind", "TEXT")
    ensure_column(engine, "memories", "subject_memory_id", "TEXT")
    ensure_column(engine, "memories", "node_status", "TEXT", nullable=False, default="'active'")
    ensure_column(engine, "memories", "canonical_key", "TEXT")
    ensure_column(engine, "projects", "assistant_root_memory_id", "TEXT")

    with engine.begin() as connection:
        connection.execute(
            sql_text(
                "CREATE INDEX IF NOT EXISTS idx_projects_assistant_root_memory "
                "ON projects (assistant_root_memory_id)"
            )
        )
        connection.execute(
            sql_text(
                "CREATE INDEX IF NOT EXISTS idx_memories_project_node_type "
                "ON memories (project_id, node_type)"
            )
        )
        connection.execute(
            sql_text(
                "CREATE INDEX IF NOT EXISTS idx_memories_project_subject "
                "ON memories (project_id, subject_memory_id)"
            )
        )
        connection.execute(
            sql_text(
                "CREATE INDEX IF NOT EXISTS idx_memories_project_canonical "
                "ON memories (project_id, subject_memory_id, canonical_key)"
            )
        )
