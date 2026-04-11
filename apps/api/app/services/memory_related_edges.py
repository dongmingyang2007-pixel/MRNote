from __future__ import annotations

from dataclasses import asdict, dataclass
import re

from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from app.models import Memory, MemoryEdge
from app.services.memory_metadata import (
    get_memory_category_segments,
    get_related_edge_exclusions,
    is_active_memory,
    is_concept_memory,
    is_subject_memory,
    is_structural_only_memory,
    is_summary_memory,
)
from app.services.memory_roots import is_assistant_root_memory
from app.services.memory_visibility import get_memory_owner_user_id, is_private_memory

RELATED_EDGE_TYPE = "related"
RELATED_EDGE_MIN_SCORE = 0.72
RELATED_EDGE_MAX_SCORE = 0.97
RELATED_EDGE_QUERY_LIMIT = 6
RELATED_EDGE_LIMIT_PER_MEMORY = 2
_TOKEN_PATTERN = re.compile(r"[\w\u4e00-\u9fff]{2,}")
PREREQUISITE_EDGE_TYPE = "prerequisite"


@dataclass(slots=True)
class RelatedEdgeSyncSummary:
    created_related_edges: int = 0
    updated_related_edges: int = 0
    deleted_related_edges: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(slots=True)
class PrerequisiteEdgeSyncSummary:
    created_prerequisite_edges: int = 0
    updated_prerequisite_edges: int = 0
    deleted_prerequisite_edges: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


def _pair_key(left_id: str, right_id: str) -> tuple[str, str]:
    return (left_id, right_id) if left_id <= right_id else (right_id, left_id)


def _directed_pair_key(source_id: str, target_id: str) -> tuple[str, str]:
    return (source_id, target_id)


def _visibility_key(memory: Memory) -> str:
    if is_private_memory(memory):
        owner_user_id = get_memory_owner_user_id(memory)
        if owner_user_id:
            return f"private:{owner_user_id}"
    return "public"


def _memory_tokens(memory: Memory) -> set[str]:
    haystack = f"{memory.category}\n{memory.content}".casefold()
    return {token for token in _TOKEN_PATTERN.findall(haystack)}


def _shared_prefix_depth(left: Memory, right: Memory) -> int:
    left_segments = get_memory_category_segments(left)
    right_segments = get_memory_category_segments(right)
    depth = 0
    for left_segment, right_segment in zip(left_segments, right_segments, strict=False):
        if left_segment != right_segment:
            break
        depth += 1
    return depth


def _is_ancestor(
    *,
    candidate_ancestor_id: str,
    memory: Memory,
    memories_by_id: dict[str, Memory],
) -> bool:
    current_id = memory.parent_memory_id or ""
    visited: set[str] = set()
    while current_id:
        if current_id == candidate_ancestor_id:
            return True
        if current_id in visited:
            return False
        visited.add(current_id)
        current = memories_by_id.get(current_id)
        if current is None or is_assistant_root_memory(current):
            return False
        current_id = current.parent_memory_id or ""
    return False


def _should_skip_pair(
    *,
    left: Memory,
    right: Memory,
    memories_by_id: dict[str, Memory],
) -> bool:
    if left.id == right.id:
        return True
    if _visibility_key(left) != _visibility_key(right):
        return True
    if _is_ancestor(candidate_ancestor_id=left.id, memory=right, memories_by_id=memories_by_id):
        return True
    if _is_ancestor(candidate_ancestor_id=right.id, memory=left, memories_by_id=memories_by_id):
        return True
    return False


def _adjust_related_score(left: Memory, right: Memory, base_score: float) -> float:
    score = base_score
    shared_prefix_depth = _shared_prefix_depth(left, right)
    if shared_prefix_depth > 0:
        score -= min(0.06, shared_prefix_depth * 0.018)

    left_segments = get_memory_category_segments(left)
    right_segments = get_memory_category_segments(right)
    if (
        left_segments
        and right_segments
        and left_segments[-1] == right_segments[-1]
        and shared_prefix_depth == 0
    ):
        score += 0.03

    token_overlap = len(_memory_tokens(left) & _memory_tokens(right))
    if token_overlap >= 2:
        score += min(0.05, token_overlap * 0.012)

    return max(0.0, min(0.99, round(score, 4)))


def _query_related_candidates(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    memory_id: str,
    limit: int,
) -> list[tuple[str, float]]:
    bind = db.get_bind()
    if bind is None or bind.dialect.name != "postgresql":
        return []
    rows = db.execute(
        sql_text(
            """
            SELECT related.memory_id, MAX(1 - (source.vector <=> related.vector)) AS score
            FROM embeddings AS source
            JOIN embeddings AS related
              ON related.workspace_id = source.workspace_id
             AND related.project_id = source.project_id
             AND related.memory_id IS NOT NULL
             AND related.memory_id != source.memory_id
            JOIN memories AS target_memory
              ON target_memory.id = related.memory_id
            WHERE source.workspace_id = :workspace_id
              AND source.project_id = :project_id
              AND source.memory_id = :memory_id
              AND source.vector IS NOT NULL
              AND target_memory.type = 'permanent'
            GROUP BY related.memory_id
            ORDER BY score DESC
            LIMIT :limit
            """
        ),
        {
            "workspace_id": workspace_id,
            "project_id": project_id,
            "memory_id": memory_id,
            "limit": limit,
        },
    ).fetchall()
    return [
        (str(row[0]), float(row[1]) if row[1] is not None else 0.0)
        for row in rows
        if row[0]
    ]


def ensure_project_related_edges(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
) -> RelatedEdgeSyncSummary:
    summary = RelatedEdgeSyncSummary()
    candidate_memories = [
        memory
        for memory in (
            db.query(Memory)
            .filter(
                Memory.workspace_id == workspace_id,
                Memory.project_id == project_id,
                Memory.type == "permanent",
            )
            .all()
        )
        if not is_assistant_root_memory(memory)
        and is_active_memory(memory)
        and not is_subject_memory(memory)
        and not is_concept_memory(memory)
        and not is_structural_only_memory(memory)
        and not is_summary_memory(memory)
        and memory.content.strip()
    ]
    memories_by_id = {memory.id: memory for memory in candidate_memories}
    if len(memories_by_id) < 2:
        existing_related_edges = (
            db.query(MemoryEdge)
            .filter(
                MemoryEdge.edge_type == RELATED_EDGE_TYPE,
                MemoryEdge.source_memory_id.in_(list(memories_by_id) or [""]),
                MemoryEdge.target_memory_id.in_(list(memories_by_id) or [""]),
            )
            .all()
        )
        for edge in existing_related_edges:
            db.delete(edge)
            summary.deleted_related_edges += 1
        return summary

    candidate_ids = list(memories_by_id)
    existing_edges = (
        db.query(MemoryEdge)
        .filter(
            MemoryEdge.source_memory_id.in_(candidate_ids),
            MemoryEdge.target_memory_id.in_(candidate_ids),
            MemoryEdge.edge_type.in_(["manual", RELATED_EDGE_TYPE]),
        )
        .all()
    )
    manual_pairs = {
        _pair_key(edge.source_memory_id, edge.target_memory_id)
        for edge in existing_edges
        if edge.edge_type == "manual"
    }
    existing_related_by_pair = {
        _pair_key(edge.source_memory_id, edge.target_memory_id): edge
        for edge in existing_edges
        if edge.edge_type == RELATED_EDGE_TYPE
    }

    exclusions_by_memory = {
        memory.id: set(get_related_edge_exclusions(memory))
        for memory in candidate_memories
    }
    desired_pairs: dict[tuple[str, str], float] = {}

    for memory in candidate_memories:
        accepted = 0
        for other_id, base_score in _query_related_candidates(
            db,
            workspace_id=workspace_id,
            project_id=project_id,
            memory_id=memory.id,
            limit=RELATED_EDGE_QUERY_LIMIT,
        ):
            if accepted >= RELATED_EDGE_LIMIT_PER_MEMORY:
                break
            other = memories_by_id.get(other_id)
            if other is None:
                continue
            if other_id in exclusions_by_memory.get(memory.id, set()):
                continue
            if memory.id in exclusions_by_memory.get(other_id, set()):
                continue
            if _should_skip_pair(left=memory, right=other, memories_by_id=memories_by_id):
                continue

            pair = _pair_key(memory.id, other.id)
            if pair in manual_pairs:
                continue

            score = _adjust_related_score(memory, other, base_score)
            if score < RELATED_EDGE_MIN_SCORE or score >= RELATED_EDGE_MAX_SCORE:
                continue
            previous_score = desired_pairs.get(pair)
            if previous_score is None or score > previous_score:
                desired_pairs[pair] = score
            accepted += 1

    for pair, strength in desired_pairs.items():
        source_id, target_id = pair
        existing = existing_related_by_pair.get(pair)
        if existing is None:
            db.add(
                MemoryEdge(
                    source_memory_id=source_id,
                    target_memory_id=target_id,
                    edge_type=RELATED_EDGE_TYPE,
                    strength=strength,
                )
            )
            summary.created_related_edges += 1
            continue
        changed = False
        if existing.source_memory_id != source_id:
            existing.source_memory_id = source_id
            changed = True
        if existing.target_memory_id != target_id:
            existing.target_memory_id = target_id
            changed = True
        if abs(float(existing.strength or 0.0) - strength) >= 0.02:
            existing.strength = strength
            changed = True
        if changed:
            summary.updated_related_edges += 1

    for pair, edge in existing_related_by_pair.items():
        if pair in desired_pairs or pair in manual_pairs:
            continue
        db.delete(edge)
        summary.deleted_related_edges += 1

    return summary


def ensure_project_prerequisite_edges(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
) -> PrerequisiteEdgeSyncSummary:
    summary = PrerequisiteEdgeSyncSummary()
    concept_memories = [
        memory
        for memory in (
            db.query(Memory)
            .filter(
                Memory.workspace_id == workspace_id,
                Memory.project_id == project_id,
                Memory.type == "permanent",
            )
            .all()
        )
        if not is_assistant_root_memory(memory)
        and is_active_memory(memory)
        and is_concept_memory(memory)
        and memory.content.strip()
    ]
    concept_ids = [memory.id for memory in concept_memories]
    concepts_by_id = {memory.id: memory for memory in concept_memories}
    existing_edges = (
        db.query(MemoryEdge)
        .filter(
            MemoryEdge.edge_type == PREREQUISITE_EDGE_TYPE,
            MemoryEdge.source_memory_id.in_(concept_ids or [""]),
            MemoryEdge.target_memory_id.in_(concept_ids or [""]),
        )
        .all()
    )
    existing_by_pair = {
        _directed_pair_key(edge.source_memory_id, edge.target_memory_id): edge
        for edge in existing_edges
    }

    desired_pairs: dict[tuple[str, str], float] = {}
    for concept in concept_memories:
        parent_id = concept.parent_memory_id or ""
        parent = concepts_by_id.get(parent_id)
        if parent is None:
            continue
        if parent.subject_memory_id and concept.subject_memory_id and parent.subject_memory_id != concept.subject_memory_id:
            continue
        desired_pairs[_directed_pair_key(parent.id, concept.id)] = 0.82

    for pair, strength in desired_pairs.items():
        source_id, target_id = pair
        existing = existing_by_pair.get(pair)
        if existing is None:
            db.add(
                MemoryEdge(
                    source_memory_id=source_id,
                    target_memory_id=target_id,
                    edge_type=PREREQUISITE_EDGE_TYPE,
                    strength=strength,
                )
            )
            summary.created_prerequisite_edges += 1
            continue
        if abs(float(existing.strength or 0.0) - strength) >= 0.02:
            existing.strength = strength
            summary.updated_prerequisite_edges += 1

    for pair, edge in existing_by_pair.items():
        if pair in desired_pairs:
            continue
        db.delete(edge)
        summary.deleted_prerequisite_edges += 1

    return summary
