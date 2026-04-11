from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from sqlalchemy.orm import Session

from app.models import Memory, MemoryEdge, MemoryFile
from app.services.embedding import embed_and_store
from app.services.memory_metadata import (
    ACTIVE_NODE_STATUS,
    FACT_NODE_TYPE,
    SUPERSEDED_NODE_STATUS,
    get_lineage_key,
    is_fact_memory,
    normalize_memory_metadata,
)
from app.services.memory_visibility import build_private_memory_metadata, get_memory_owner_user_id, is_private_memory
from app.services.memory_v2 import apply_temporal_defaults, copy_memory_evidences

SUPERSEDES_EDGE_TYPE = "supersedes"
CONFLICT_EDGE_TYPE = "conflict"
VERSION_EDGE_TYPES = {SUPERSEDES_EDGE_TYPE, CONFLICT_EDGE_TYPE}
_RUNTIME_METADATA_KEYS = {
    "last_used_at",
    "last_used_source",
    "last_retrieval_score",
    "retrieval_count",
    "superseded_by_memory_id",
    "predecessor_memory_id",
    "conflict_with_memory_id",
    "version_reason",
}
EmbedFn = Callable[..., Awaitable[str | None]]


def ensure_fact_lineage(memory: Memory) -> str | None:
    if not is_fact_memory(memory):
        if memory.lineage_key:
            memory.lineage_key = None
        metadata = dict(memory.metadata_json or {})
        if "lineage_key" in metadata:
            metadata.pop("lineage_key", None)
            memory.metadata_json = normalize_memory_metadata(
                content=memory.content,
                category=memory.category,
                memory_type=memory.type,
                metadata=metadata,
            )
        return None

    lineage_key = str(get_lineage_key(memory) or memory.id or "").strip() or None
    if lineage_key is None:
        return None
    if memory.lineage_key != lineage_key:
        memory.lineage_key = lineage_key
    metadata = dict(memory.metadata_json or {})
    if metadata.get("lineage_key") != lineage_key:
        metadata["lineage_key"] = lineage_key
        memory.metadata_json = normalize_memory_metadata(
            content=memory.content,
            category=memory.category,
            memory_type=memory.type,
            metadata=metadata,
        )
    return lineage_key


def _copy_fact_metadata(
    predecessor: Memory,
    *,
    content: str,
    category: str,
    lineage_key: str,
    reason: str | None,
    metadata_updates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = dict(predecessor.metadata_json or {})
    for key in _RUNTIME_METADATA_KEYS:
        metadata.pop(key, None)
    metadata.update(metadata_updates or {})
    metadata.update(
        {
            "node_type": FACT_NODE_TYPE,
            "node_status": ACTIVE_NODE_STATUS,
            "subject_memory_id": predecessor.subject_memory_id,
            "lineage_key": lineage_key,
        }
    )
    if reason:
        metadata["version_reason"] = reason
    if is_private_memory(predecessor):
        metadata = build_private_memory_metadata(
            metadata,
            owner_user_id=get_memory_owner_user_id(predecessor),
        )
    return normalize_memory_metadata(
        content=content,
        category=category,
        memory_type=predecessor.type,
        metadata=metadata,
    )


def _set_predecessor_status(
    predecessor: Memory,
    *,
    status: str,
    lineage_key: str,
    successor_id: str | None = None,
    reason: str | None = None,
) -> None:
    effective_now = datetime.now(timezone.utc)
    predecessor.node_status = status
    predecessor.lineage_key = lineage_key
    if status == SUPERSEDED_NODE_STATUS and predecessor.valid_to is None:
        predecessor.valid_to = effective_now
    metadata = dict(predecessor.metadata_json or {})
    metadata["node_status"] = status
    metadata["lineage_key"] = lineage_key
    if successor_id:
        metadata["superseded_by_memory_id"] = successor_id
    if reason:
        metadata["version_reason"] = reason
    predecessor.metadata_json = normalize_memory_metadata(
        content=predecessor.content,
        category=predecessor.category,
        memory_type=predecessor.type,
        metadata=metadata,
    )
    predecessor.updated_at = effective_now


def _upsert_version_edge(
    db: Session,
    *,
    source_memory_id: str,
    target_memory_id: str,
    edge_type: str,
    strength: float,
) -> MemoryEdge:
    if edge_type not in VERSION_EDGE_TYPES:
        raise ValueError(f"Unsupported version edge type: {edge_type}")
    if edge_type == CONFLICT_EDGE_TYPE and target_memory_id < source_memory_id:
        source_memory_id, target_memory_id = target_memory_id, source_memory_id
    existing = (
        db.query(MemoryEdge)
        .filter(
            MemoryEdge.source_memory_id == source_memory_id,
            MemoryEdge.target_memory_id == target_memory_id,
            MemoryEdge.edge_type == edge_type,
        )
        .first()
    )
    if existing is not None:
        existing.strength = max(float(existing.strength or 0.0), float(strength))
        return existing
    edge = MemoryEdge(
        source_memory_id=source_memory_id,
        target_memory_id=target_memory_id,
        edge_type=edge_type,
        strength=max(0.1, min(1.0, float(strength))),
    )
    db.add(edge)
    db.flush()
    return edge


def _copy_manual_edges(db: Session, *, predecessor: Memory, successor: Memory) -> None:
    manual_edges = (
        db.query(MemoryEdge)
        .filter(
            MemoryEdge.edge_type == "manual",
            (MemoryEdge.source_memory_id == predecessor.id) | (MemoryEdge.target_memory_id == predecessor.id),
        )
        .all()
    )
    for edge in manual_edges:
        source_memory_id = successor.id if edge.source_memory_id == predecessor.id else edge.source_memory_id
        target_memory_id = successor.id if edge.target_memory_id == predecessor.id else edge.target_memory_id
        if source_memory_id == target_memory_id:
            continue
        existing = (
            db.query(MemoryEdge)
            .filter(
                MemoryEdge.source_memory_id == source_memory_id,
                MemoryEdge.target_memory_id == target_memory_id,
                MemoryEdge.edge_type == "manual",
            )
            .first()
        )
        if existing is not None:
            existing.strength = max(float(existing.strength or 0.0), float(edge.strength or 0.0))
            continue
        db.add(
            MemoryEdge(
                source_memory_id=source_memory_id,
                target_memory_id=target_memory_id,
                edge_type="manual",
                strength=float(edge.strength or 0.5),
            )
        )


def _copy_memory_files(db: Session, *, predecessor: Memory, successor: Memory) -> None:
    attachments = db.query(MemoryFile).filter(MemoryFile.memory_id == predecessor.id).all()
    if not attachments:
        return
    existing_item_ids = {
        data_item_id
        for data_item_id, in db.query(MemoryFile.data_item_id).filter(MemoryFile.memory_id == successor.id).all()
    }
    for attachment in attachments:
        if attachment.data_item_id in existing_item_ids:
            continue
        db.add(
            MemoryFile(
                memory_id=successor.id,
                data_item_id=attachment.data_item_id,
            )
        )


async def create_fact_successor(
    db: Session,
    *,
    predecessor: Memory,
    content: str,
    category: str | None = None,
    reason: str | None = None,
    metadata_updates: dict[str, Any] | None = None,
    embed_fn: EmbedFn = embed_and_store,
    vector: list[float] | None = None,
) -> Memory:
    if predecessor.type != "permanent" or not is_fact_memory(predecessor):
        raise ValueError("Only permanent fact memories can be superseded")
    lineage_key = str(get_lineage_key(predecessor) or predecessor.id).strip()
    predecessor.lineage_key = lineage_key
    normalized_category = category if category is not None else predecessor.category
    successor_metadata = _copy_fact_metadata(
        predecessor,
        content=content,
        category=normalized_category,
        lineage_key=lineage_key,
        reason=reason,
        metadata_updates=metadata_updates,
    )
    successor = Memory(
        workspace_id=predecessor.workspace_id,
        project_id=predecessor.project_id,
        content=content,
        category=normalized_category,
        type=predecessor.type,
        node_type=FACT_NODE_TYPE,
        source_conversation_id=None,
        parent_memory_id=predecessor.parent_memory_id,
        subject_memory_id=predecessor.subject_memory_id,
        node_status=ACTIVE_NODE_STATUS,
        canonical_key=str(successor_metadata.get("canonical_key") or "").strip() or None,
        lineage_key=lineage_key,
        confidence=predecessor.confidence,
        observed_at=predecessor.observed_at,
        valid_from=predecessor.valid_from,
        valid_to=None,
        last_confirmed_at=datetime.now(timezone.utc),
        metadata_json=successor_metadata,
    )
    db.add(successor)
    db.flush()
    ensure_fact_lineage(successor)
    apply_temporal_defaults(successor)
    _set_predecessor_status(
        predecessor,
        status=SUPERSEDED_NODE_STATUS,
        lineage_key=lineage_key,
        successor_id=successor.id,
        reason=reason,
    )
    _copy_manual_edges(db, predecessor=predecessor, successor=successor)
    _copy_memory_files(db, predecessor=predecessor, successor=successor)
    copy_memory_evidences(db, source_memory_id=predecessor.id, target_memory_id=successor.id)
    _upsert_version_edge(
        db,
        source_memory_id=successor.id,
        target_memory_id=predecessor.id,
        edge_type=SUPERSEDES_EDGE_TYPE,
        strength=0.98,
    )
    try:
        await embed_fn(
            db,
            workspace_id=successor.workspace_id,
            project_id=successor.project_id,
            memory_id=successor.id,
            chunk_text=successor.content,
            vector=vector,
            auto_commit=False,
        )
    except Exception:  # noqa: BLE001
        pass
    return successor


async def create_conflicting_fact(
    db: Session,
    *,
    anchor: Memory,
    content: str,
    category: str | None = None,
    reason: str | None = None,
    metadata_updates: dict[str, Any] | None = None,
    embed_fn: EmbedFn = embed_and_store,
    vector: list[float] | None = None,
) -> Memory:
    if anchor.type != "permanent" or not is_fact_memory(anchor):
        raise ValueError("Only permanent fact memories can produce conflict versions")
    lineage_key = str(get_lineage_key(anchor) or anchor.id).strip()
    anchor.lineage_key = lineage_key
    normalized_category = category if category is not None else anchor.category
    conflict_metadata = _copy_fact_metadata(
        anchor,
        content=content,
        category=normalized_category,
        lineage_key=lineage_key,
        reason=reason,
        metadata_updates={
            **(metadata_updates or {}),
            "conflict_with_memory_id": anchor.id,
        },
    )
    conflict_memory = Memory(
        workspace_id=anchor.workspace_id,
        project_id=anchor.project_id,
        content=content,
        category=normalized_category,
        type=anchor.type,
        node_type=FACT_NODE_TYPE,
        source_conversation_id=None,
        parent_memory_id=anchor.parent_memory_id,
        subject_memory_id=anchor.subject_memory_id,
        node_status=ACTIVE_NODE_STATUS,
        canonical_key=str(conflict_metadata.get("canonical_key") or "").strip() or None,
        lineage_key=lineage_key,
        confidence=anchor.confidence,
        observed_at=anchor.observed_at,
        valid_from=anchor.valid_from,
        valid_to=None,
        last_confirmed_at=datetime.now(timezone.utc),
        metadata_json=conflict_metadata,
    )
    db.add(conflict_memory)
    db.flush()
    ensure_fact_lineage(conflict_memory)
    apply_temporal_defaults(conflict_memory)
    _copy_memory_files(db, predecessor=anchor, successor=conflict_memory)
    copy_memory_evidences(db, source_memory_id=anchor.id, target_memory_id=conflict_memory.id)
    _upsert_version_edge(
        db,
        source_memory_id=conflict_memory.id,
        target_memory_id=anchor.id,
        edge_type=CONFLICT_EDGE_TYPE,
        strength=0.92,
    )
    try:
        await embed_fn(
            db,
            workspace_id=conflict_memory.workspace_id,
            project_id=conflict_memory.project_id,
            memory_id=conflict_memory.id,
            chunk_text=conflict_memory.content,
            vector=vector,
            auto_commit=False,
        )
    except Exception:  # noqa: BLE001
        pass
    return conflict_memory
