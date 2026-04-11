from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import Memory, MemoryEdge, MemoryEvidence, Message
from app.services.memory_metadata import (
    get_memory_kind,
    get_memory_metadata,
    get_subject_memory_id,
    is_active_memory,
    is_structural_only_memory,
    is_subject_memory,
)
from app.services.memory_roots import is_assistant_root_memory
from app.services.memory_v2 import (
    PLAYBOOK_VIEW_TYPE,
    PROFILE_VIEW_TYPE,
    TIMELINE_VIEW_TYPE,
    apply_temporal_defaults,
    record_memory_evidence,
    refresh_subject_views,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_confidence(value: object, default: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, numeric))


def _explicit_memory_confidence(memory: Memory) -> float | None:
    metadata = get_memory_metadata(memory)
    for key in ("importance", "salience"):
        value = metadata.get(key)
        if isinstance(value, (int, float)):
            return _coerce_confidence(value, float(memory.confidence or 0.7))
    return None


def _backfill_memory_fields(memory: Memory) -> tuple[bool, bool]:
    temporal_changed = False
    confidence_changed = False

    before_temporal = (
        memory.observed_at,
        memory.valid_from,
        memory.valid_to,
        memory.last_confirmed_at,
    )
    apply_temporal_defaults(
        memory,
        memory_kind=get_memory_kind(memory),
        timestamp=memory.created_at or _utc_now(),
    )
    if not is_active_memory(memory) and memory.valid_to is None:
        memory.valid_to = memory.updated_at or memory.created_at or _utc_now()
    after_temporal = (
        memory.observed_at,
        memory.valid_from,
        memory.valid_to,
        memory.last_confirmed_at,
    )
    temporal_changed = before_temporal != after_temporal

    explicit_confidence = _explicit_memory_confidence(memory)
    if explicit_confidence is not None and abs(float(memory.confidence or 0.0) - explicit_confidence) > 1e-6:
        memory.confidence = explicit_confidence
        confidence_changed = True

    return temporal_changed, confidence_changed


def _backfill_edge_fields(edge: MemoryEdge) -> bool:
    changed = False
    derived_confidence = _coerce_confidence(edge.strength, float(edge.confidence or 0.5))
    if abs(float(edge.confidence or 0.0) - derived_confidence) > 1e-6:
        edge.confidence = derived_confidence
        changed = True
    if edge.metadata_json is None:
        edge.metadata_json = {}
        changed = True
    timestamp = edge.created_at or _utc_now()
    if edge.observed_at is None:
        edge.observed_at = timestamp
        changed = True
    if edge.valid_from is None:
        edge.valid_from = timestamp
        changed = True
    return changed


def _select_backfill_message(
    db: Session,
    *,
    conversation_id: str,
    memory_created_at: datetime | None,
) -> Message | None:
    base_query = db.query(Message).filter(Message.conversation_id == conversation_id)
    scoped_query = base_query
    if memory_created_at is not None:
        scoped_query = scoped_query.filter(Message.created_at <= memory_created_at)

    message = (
        scoped_query.filter(Message.role == "user")
        .order_by(Message.created_at.desc())
        .first()
    )
    if message is not None:
        return message

    message = scoped_query.order_by(Message.created_at.desc()).first()
    if message is not None:
        return message

    message = (
        base_query.filter(Message.role == "user")
        .order_by(Message.created_at.desc())
        .first()
    )
    if message is not None:
        return message
    return base_query.order_by(Message.created_at.desc()).first()


def _backfill_memory_evidence(db: Session, *, memory: Memory) -> str | None:
    if is_assistant_root_memory(memory) or is_structural_only_memory(memory):
        return None
    existing = (
        db.query(MemoryEvidence.id)
        .filter(MemoryEvidence.memory_id == memory.id)
        .first()
    )
    if existing is not None:
        return None

    metadata = {"source": "memory_v2_backfill", "legacy": True}
    if memory.source_conversation_id:
        source_message = _select_backfill_message(
            db,
            conversation_id=memory.source_conversation_id,
            memory_created_at=memory.created_at,
        )
        if source_message is not None:
            record_memory_evidence(
                db,
                memory=memory,
                source_type="message",
                conversation_id=memory.source_conversation_id,
                message_id=source_message.id,
                message_role=source_message.role,
                quote_text=source_message.content.strip() or memory.content,
                confidence=memory.confidence,
                metadata_json=metadata,
            )
            return "message"
        record_memory_evidence(
            db,
            memory=memory,
            source_type="conversation",
            conversation_id=memory.source_conversation_id,
            quote_text=memory.content,
            confidence=memory.confidence,
            metadata_json=metadata,
        )
        return "conversation"

    record_memory_evidence(
        db,
        memory=memory,
        source_type="manual",
        quote_text=memory.content,
        confidence=memory.confidence,
        metadata_json=metadata,
    )
    return "manual"


def _collect_subject_memory_ids(memories: list[Memory]) -> set[str]:
    subject_ids: set[str] = set()
    for memory in memories:
        if is_subject_memory(memory):
            subject_ids.add(memory.id)
        subject_id = get_subject_memory_id(memory)
        if subject_id:
            subject_ids.add(subject_id)
    return subject_ids


@dataclass(slots=True)
class MemoryBackfillSummary:
    processed_memories: int = 0
    processed_edges: int = 0
    temporal_updated: int = 0
    confidence_updated: int = 0
    edge_fields_updated: int = 0
    evidences_created: int = 0
    message_evidences_created: int = 0
    conversation_evidences_created: int = 0
    manual_evidences_created: int = 0
    subjects_refreshed: int = 0
    profile_views_refreshed: int = 0
    timeline_views_refreshed: int = 0
    playbook_views_refreshed: int = 0
    skipped_structural_memories: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "processed_memories": self.processed_memories,
            "processed_edges": self.processed_edges,
            "temporal_updated": self.temporal_updated,
            "confidence_updated": self.confidence_updated,
            "edge_fields_updated": self.edge_fields_updated,
            "evidences_created": self.evidences_created,
            "message_evidences_created": self.message_evidences_created,
            "conversation_evidences_created": self.conversation_evidences_created,
            "manual_evidences_created": self.manual_evidences_created,
            "subjects_refreshed": self.subjects_refreshed,
            "profile_views_refreshed": self.profile_views_refreshed,
            "timeline_views_refreshed": self.timeline_views_refreshed,
            "playbook_views_refreshed": self.playbook_views_refreshed,
            "skipped_structural_memories": self.skipped_structural_memories,
        }

    def has_changes(self) -> bool:
        return any(
            value > 0
            for key, value in self.as_dict().items()
            if key not in {"processed_memories", "processed_edges"}
        )


def backfill_project_memory_v2(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    limit: int | None = None,
) -> MemoryBackfillSummary:
    summary = MemoryBackfillSummary()

    memory_query = (
        db.query(Memory)
        .filter(
            Memory.workspace_id == workspace_id,
            Memory.project_id == project_id,
        )
        .order_by(Memory.created_at.asc(), Memory.id.asc())
    )
    if limit is not None:
        memory_query = memory_query.limit(limit)
    memories = memory_query.all()

    for memory in memories:
        summary.processed_memories += 1
        if is_assistant_root_memory(memory) or is_structural_only_memory(memory):
            summary.skipped_structural_memories += 1
        temporal_changed, confidence_changed = _backfill_memory_fields(memory)
        if temporal_changed:
            summary.temporal_updated += 1
        if confidence_changed:
            summary.confidence_updated += 1
        evidence_source = _backfill_memory_evidence(db, memory=memory)
        if evidence_source:
            summary.evidences_created += 1
            if evidence_source == "message":
                summary.message_evidences_created += 1
            elif evidence_source == "conversation":
                summary.conversation_evidences_created += 1
            else:
                summary.manual_evidences_created += 1

    project_memory_ids = [
        memory_id
        for memory_id, in db.query(Memory.id)
        .filter(
            Memory.workspace_id == workspace_id,
            Memory.project_id == project_id,
        )
        .all()
    ]
    edges = (
        db.query(MemoryEdge)
        .filter(
            MemoryEdge.source_memory_id.in_(project_memory_ids),
            MemoryEdge.target_memory_id.in_(project_memory_ids),
        )
        .order_by(MemoryEdge.created_at.asc(), MemoryEdge.id.asc())
        .all()
        if project_memory_ids
        else []
    )
    for edge in edges:
        summary.processed_edges += 1
        if _backfill_edge_fields(edge):
            summary.edge_fields_updated += 1

    subject_ids = _collect_subject_memory_ids(memories)
    if subject_ids:
        subject_memories = (
            db.query(Memory)
            .filter(
                Memory.workspace_id == workspace_id,
                Memory.project_id == project_id,
                Memory.id.in_(sorted(subject_ids)),
            )
            .all()
        )
        for subject_memory in subject_memories:
            source_memories = (
                db.query(Memory)
                .filter(
                    Memory.workspace_id == workspace_id,
                    Memory.project_id == project_id,
                    Memory.subject_memory_id == subject_memory.id,
                )
                .order_by(Memory.updated_at.desc(), Memory.created_at.desc())
                .all()
            )
            source_memories = [
                memory
                for memory in source_memories
                if not is_structural_only_memory(memory) and memory.id != subject_memory.id
            ]
            views = refresh_subject_views(
                db,
                subject_memory=subject_memory,
                playbook_source_text="\n".join(
                    memory.content.strip()
                    for memory in source_memories[:32]
                    if memory.content.strip()
                )
                or None,
                playbook_source_memory_ids=[
                    memory.id
                    for memory in source_memories
                    if is_active_memory(memory)
                ],
            )
            if views:
                summary.subjects_refreshed += 1
            for view in views:
                if view.view_type == PROFILE_VIEW_TYPE:
                    summary.profile_views_refreshed += 1
                elif view.view_type == TIMELINE_VIEW_TYPE:
                    summary.timeline_views_refreshed += 1
                elif view.view_type == PLAYBOOK_VIEW_TYPE:
                    summary.playbook_views_refreshed += 1

    db.flush()
    return summary
