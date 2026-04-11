from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from time import perf_counter
from typing import Any, Awaitable, Callable, Literal

from sqlalchemy.orm import Session

from app.models import Conversation, Memory, MemoryEdge, MemoryEvidence, MemoryView, Project
from app.services.context_loader import filter_knowledge_chunks, load_conversation_context
from app.services.memory_file_context import load_linked_file_chunks_for_memories
from app.services.memory_metadata import (
    MEMORY_KIND_EPISODIC,
    MEMORY_KIND_GOAL,
    MEMORY_KIND_PREFERENCE,
    MEMORY_KIND_PROFILE,
    MEMORY_KIND_SUMMARY,
    get_lineage_key,
    get_memory_kind,
    get_memory_metadata,
    get_memory_salience,
    is_active_memory,
    get_subject_kind,
    get_subject_memory_id,
    is_category_path_memory,
    is_concept_memory,
    is_fact_memory,
    is_pinned_memory,
    is_subject_memory,
    is_structural_only_memory,
    is_summary_memory,
    shorten_text,
    stamp_memory_usage_metadata,
)
from app.services.memory_related_edges import RELATED_EDGE_TYPE
from app.services.memory_roots import ensure_project_user_subject, is_assistant_root_memory
from app.services.memory_v2 import (
    PLAYBOOK_VIEW_TYPE,
    PROFILE_VIEW_TYPE,
    SUMMARY_VIEW_TYPE,
    TIMELINE_VIEW_TYPE,
    RerankDocument,
    is_playbook_formalized,
    list_memory_evidences,
    rerank_documents,
    search_memories_lexical,
    search_memory_evidences_lexical,
    search_memory_views_lexical,
)
from app.services.memory_visibility import get_memory_owner_user_id, is_private_memory
from app.services.embedding import search_similar

SemanticSearchFn = Callable[..., Awaitable[list[dict[str, Any]]]]
LinkedFileLoaderFn = Callable[..., Awaitable[list[dict[str, Any]]]]
ContextLevel = Literal["none", "profile_only", "memory_only", "full_rag"]

STATIC_MEMORY_LIMIT = 6
RELEVANT_MEMORY_LIMIT = 10
GRAPH_MEMORY_LIMIT = 4
GRAPH_TRAVERSAL_DEPTH = 3
TEMPORARY_MEMORY_LIMIT = 8
KNOWLEDGE_CHUNK_LIMIT = 6
LINKED_FILE_CHUNK_LIMIT = 4
SEMANTIC_SEARCH_LIMIT = 18
SEMANTIC_MEMORY_MIN_SCORE = 0.55
LAYERED_RERANK_LIMIT = 40
LAYERED_MEMORY_LIMIT = 12
LAYERED_VIEW_LIMIT = 8
LAYERED_EVIDENCE_LIMIT = 6

_STATIC_KINDS = {
    MEMORY_KIND_PROFILE,
}
_QUERY_TOKEN_PATTERN = re.compile(r"[\w\u4e00-\u9fff]{2,}")


@dataclass(slots=True)
class MemoryCandidate:
    memory: Memory
    source: str
    score: float
    semantic_score: float | None = None

    @property
    def id(self) -> str:
        return self.memory.id


@dataclass(slots=True)
class MemoryContextResult:
    project: Project
    conversation: Conversation
    selected_memories: list[MemoryCandidate]
    knowledge_chunks: list[dict[str, Any]]
    linked_file_chunks: list[dict[str, Any]]
    system_prompt: str
    retrieval_trace: dict[str, Any]


@dataclass(slots=True)
class GraphPreflightResult:
    active_subjects: list[MemoryCandidate]
    primary_subject: Memory | None
    active_concepts: list[MemoryCandidate]
    active_facts: list[MemoryCandidate]
    static_memories: list[MemoryCandidate]
    graph_memories: list[MemoryCandidate]
    temporary_memories: list[MemoryCandidate]
    knowledge_chunks: list[dict[str, Any]]
    linked_file_chunks: list[dict[str, Any]]
    explanation_path: dict[str, Any] | None
    evidence_query_set: list[str]
    primary_fact_ids_by_lineage: dict[str, str]
    has_conflict: bool
    conflict_memory_ids: list[str]
    preflight_steps: list[str]
    selected_edge_types: list[str]


def _memory_visible_to_conversation(memory: Memory, *, conversation_id: str, conversation_created_by: str | None) -> bool:
    if memory.type == "temporary":
        return memory.source_conversation_id == conversation_id
    if not is_private_memory(memory):
        return True
    return get_memory_owner_user_id(memory) == conversation_created_by


def _load_visible_memories(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    conversation_id: str,
    conversation_created_by: str | None,
    include_inactive: bool = False,
) -> tuple[list[Memory], list[Memory]]:
    memories = (
        db.query(Memory)
        .filter(
            Memory.workspace_id == workspace_id,
            Memory.project_id == project_id,
        )
        .all()
    )
    visible_permanent: list[Memory] = []
    visible_temporary: list[Memory] = []
    for memory in memories:
        if is_assistant_root_memory(memory):
            continue
        if not _memory_visible_to_conversation(
            memory,
            conversation_id=conversation_id,
            conversation_created_by=conversation_created_by,
        ):
            continue
        if not include_inactive and not is_active_memory(memory):
            continue
        if memory.type == "temporary":
            visible_temporary.append(memory)
        else:
            visible_permanent.append(memory)
    return visible_permanent, visible_temporary


def _normalize_query_tokens(query: str) -> list[str]:
    return [token.casefold() for token in _QUERY_TOKEN_PATTERN.findall(query or "")]


def _memory_matches_query(memory: Memory, query_tokens: list[str]) -> bool:
    query_text = " ".join(query_tokens).casefold().strip()
    haystack_parts = [
        memory.content.casefold(),
        memory.category.casefold(),
    ]
    if query_text:
        if any(query_text in part for part in haystack_parts):
            return True
        if any(part and part in query_text for part in haystack_parts):
            return True
    if not query_tokens:
        return False
    haystack = "\n".join(haystack_parts)
    return any(token in haystack for token in query_tokens)


def _coerce_utc(timestamp: datetime | None) -> datetime | None:
    if timestamp is None:
        return None
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


def _recency_bonus(memory: Memory) -> float:
    updated_at = _coerce_utc(memory.updated_at)
    if updated_at is None:
        return 0.0
    age_days = max((datetime.now(timezone.utc) - updated_at).days, 0)
    if age_days <= 3:
        return 0.08
    if age_days <= 14:
        return 0.04
    if age_days <= 45:
        return 0.02
    return 0.0


def _candidate_score(memory: Memory, *, source: str, semantic_score: float | None = None) -> float:
    score = semantic_score or 0.0
    score += get_memory_salience(memory) * 0.45
    if is_pinned_memory(memory):
        score += 0.3
    if get_memory_kind(memory) in {MEMORY_KIND_PROFILE, MEMORY_KIND_PREFERENCE, MEMORY_KIND_GOAL}:
        score += 0.08
    score += _recency_bonus(memory)
    score += (_memory_outcome_weight(memory) - 1.0) * 0.12
    source_bonus = {
        "static": 0.15,
        "semantic": 0.28,
        "lexical": 0.16,
        "graph_parent": 0.12,
        "graph_child": 0.10,
        "graph_edge": 0.08,
        "graph_related": 0.09,
        "recent_temporary": 0.06,
    }.get(source, 0.0)
    return round(score + source_bonus, 4)


def _memory_outcome_weight(memory: Memory) -> float:
    metadata = get_memory_metadata(memory)
    success_count = int(metadata.get("success_feedback_count") or 0)
    failure_count = int(metadata.get("failure_feedback_count") or 0)
    reuse_success_rate = metadata.get("reuse_success_rate")
    try:
        success_rate = float(reuse_success_rate)
    except (TypeError, ValueError):
        total = success_count + failure_count
        success_rate = (success_count / total) if total > 0 else 0.5
    baseline = 1.0 + ((success_rate - 0.5) * 0.4)
    return round(max(0.75, min(1.25, baseline)), 4)


def _suppression_reason_for_memory(memory: Memory, *, as_of: datetime | None = None) -> str | None:
    metadata = get_memory_metadata(memory)
    reason = str(metadata.get("suppression_reason") or "").strip() or None
    if reason:
        return reason
    now = as_of or datetime.now(timezone.utc)
    if memory.valid_to is not None and _coerce_utc(memory.valid_to) and _coerce_utc(memory.valid_to) < now:
        return "memory_stale"
    if memory.node_status in {"superseded", "conflict"}:
        return f"memory_{memory.node_status}"
    return None


def _is_structural_graph_memory(memory: Memory) -> bool:
    return (
        is_subject_memory(memory)
        or is_concept_memory(memory)
    )


def _select_best_candidates(candidates: list[MemoryCandidate], *, limit: int) -> list[MemoryCandidate]:
    deduped: dict[str, MemoryCandidate] = {}
    for candidate in sorted(candidates, key=lambda item: item.score, reverse=True):
        current = deduped.get(candidate.id)
        if current is None or candidate.score > current.score:
            deduped[candidate.id] = candidate
    return list(sorted(deduped.values(), key=lambda item: item.score, reverse=True)[:limit])


def _lineage_bucket_id(memory: Memory) -> str:
    return get_lineage_key(memory) or memory.id


def _query_requests_conflict_expansion(query: str) -> bool:
    lowered = query.casefold()
    return any(
        token in lowered
        for token in (
            "矛盾",
            "冲突",
            "变化",
            "前后不一致",
            "有没有变",
            "是否变了",
            "conflict",
            "contradict",
            "changed",
            "difference",
        )
    )


def _query_requests_timeline(query: str) -> bool:
    lowered = query.casefold()
    return _query_requests_conflict_expansion(query) or any(
        token in lowered
        for token in (
            "时间线",
            "历史",
            "之前",
            "后来",
            "早先",
            "timeline",
            "history",
            "before",
            "after",
            "earlier",
            "previously",
        )
    )


def _query_prefers_profile_views(query: str) -> bool:
    lowered = query.casefold()
    return any(
        token in lowered
        for token in (
            "我",
            "我的",
            "我自己",
            "偏好",
            "习惯",
            "背景",
            "档案",
            "profile",
            "about me",
            "preference",
            "goal",
        )
    )


def _query_prefers_playbook_views(query: str) -> bool:
    lowered = query.casefold()
    return any(
        token in lowered
        for token in (
            "怎么",
            "如何",
            "步骤",
            "流程",
            "方法",
            "排查",
            "修复",
            "解决",
            "复盘",
            "how",
            "steps",
            "workflow",
            "procedure",
            "debug",
            "fix",
        )
    )


def _query_requests_evidence(query: str) -> bool:
    lowered = query.casefold()
    return any(
        token in lowered
        for token in (
            "证据",
            "原话",
            "出处",
            "依据",
            "evidence",
            "quote",
            "source",
            "citation",
        )
    )


def _query_requests_explanation(query: str) -> bool:
    lowered = query.casefold()
    return any(
        token in lowered
        for token in (
            "为什么",
            "依据什么",
            "怎么选的",
            "explain",
            "why",
            "how selected",
        )
    )


def _plan_query_intent(query: str) -> str:
    if _query_requests_conflict_expansion(query):
        return "conflict"
    if _query_requests_timeline(query):
        return "timeline"
    if _query_requests_evidence(query):
        return "evidence"
    if _query_requests_explanation(query):
        return "why"
    if _query_prefers_playbook_views(query):
        return "procedure"
    if _query_prefers_profile_views(query):
        return "profile"
    return "durable_fact"


def _fact_source_confidence(memory: Memory) -> float:
    metadata = get_memory_metadata(memory)
    raw_confidence = metadata.get("source_confidence")
    try:
        confidence = float(raw_confidence)
    except (TypeError, ValueError):
        confidence = 0.0
    source = str(metadata.get("source") or "").strip().lower()
    if source in {"manual", "user_edit", "manual_supersede"}:
        confidence += 1.0
    return confidence


def _candidate_updated_at(memory: Memory) -> datetime:
    return (
        _coerce_utc(memory.updated_at)
        or _coerce_utc(memory.created_at)
        or datetime.min.replace(tzinfo=timezone.utc)
    )


def _memory_is_currently_valid(memory: Memory, *, as_of: datetime | None = None) -> bool:
    now = as_of or datetime.now(timezone.utc)
    valid_from = _coerce_utc(memory.valid_from)
    valid_to = _coerce_utc(memory.valid_to)
    if valid_from is not None and valid_from > now:
        return False
    if valid_to is not None and valid_to < now:
        return False
    return True


def _view_visible_to_conversation(view: MemoryView, *, conversation_created_by: str | None) -> bool:
    metadata = view.metadata_json if isinstance(view.metadata_json, dict) else {}
    owner_user_id = str(metadata.get("owner_user_id") or "").strip() or None
    if owner_user_id:
        return owner_user_id == conversation_created_by
    return True


def _select_primary_lineage_candidates(
    candidates: list[MemoryCandidate],
    *,
    limit: int,
    allow_conflicts: bool = False,
) -> list[MemoryCandidate]:
    if allow_conflicts:
        return _select_best_candidates(candidates, limit=limit)

    selected: dict[str, MemoryCandidate] = {}
    for candidate in sorted(
        candidates,
        key=lambda item: (
            item.semantic_score if item.semantic_score is not None else item.score,
            _fact_source_confidence(item.memory),
            _candidate_updated_at(item.memory),
            item.score,
        ),
        reverse=True,
    ):
        memory = candidate.memory
        if not is_fact_memory(memory):
            key = memory.id
        else:
            key = _lineage_bucket_id(memory)
        current = selected.get(key)
        if current is None:
            selected[key] = candidate
            continue
        current_key = (
            current.semantic_score if current.semantic_score is not None else current.score,
            _fact_source_confidence(current.memory),
            _candidate_updated_at(current.memory),
            current.score,
        )
        next_key = (
            candidate.semantic_score if candidate.semantic_score is not None else candidate.score,
            _fact_source_confidence(candidate.memory),
            _candidate_updated_at(candidate.memory),
            candidate.score,
        )
        if next_key > current_key:
            selected[key] = candidate
    return list(sorted(selected.values(), key=lambda item: item.score, reverse=True)[:limit])


def _collect_conflict_memory_ids(memories: list[Memory]) -> list[str]:
    grouped: dict[str, list[str]] = {}
    for memory in memories:
        if not is_fact_memory(memory) or not is_active_memory(memory):
            continue
        grouped.setdefault(_lineage_bucket_id(memory), []).append(memory.id)
    ids: list[str] = []
    for group_ids in grouped.values():
        if len(group_ids) <= 1:
            continue
        ids.extend(sorted(group_ids))
    return ids


def _build_graph_neighbors(
    *,
    seed_candidates: list[MemoryCandidate],
    visible_memories_by_id: dict[str, Memory],
    query_tokens: list[str],
    lateral_edges: list[MemoryEdge] | None = None,
) -> list[MemoryCandidate]:
    seed_ids = [candidate.id for candidate in seed_candidates if candidate.memory.type == "permanent"]
    if not seed_ids:
        return []

    candidates: list[MemoryCandidate] = []
    seed_semantic_by_id = {
        candidate.id: (
            candidate.semantic_score
            if candidate.semantic_score is not None
            else 0.55
        )
        for candidate in seed_candidates
    }

    structural_seed_ids = {
        candidate.id
        for candidate in seed_candidates
        if _is_structural_graph_memory(candidate.memory)
    }
    structural_parent_depths: dict[str, int] = {}
    for candidate in seed_candidates:
        current = candidate.memory
        depth = 0
        while current.parent_memory_id and depth < GRAPH_TRAVERSAL_DEPTH:
            parent_memory = visible_memories_by_id.get(current.parent_memory_id)
            if not parent_memory or not _is_structural_graph_memory(parent_memory):
                break
            depth += 1
            existing_depth = structural_parent_depths.get(parent_memory.id)
            if existing_depth is None or depth < existing_depth:
                structural_parent_depths[parent_memory.id] = depth
            current = parent_memory

    strongest_seed_score = max(
        (seed_semantic_by_id.get(seed_id, 0.0) for seed_id in seed_ids if visible_memories_by_id.get(seed_id)),
        default=0.0,
    )
    for parent_id, depth in structural_parent_depths.items():
        parent_memory = visible_memories_by_id.get(parent_id)
        if not parent_memory:
            continue
        score = _candidate_score(parent_memory, source="graph_parent", semantic_score=strongest_seed_score) - (
            (depth - 1) * 0.015
        )
        candidates.append(
            MemoryCandidate(
                memory=parent_memory,
                source="graph_parent",
                semantic_score=strongest_seed_score,
                score=round(score, 4),
            )
        )

    children_by_parent: dict[str, list[Memory]] = {}
    for memory in visible_memories_by_id.values():
        if memory.parent_memory_id:
            children_by_parent.setdefault(memory.parent_memory_id, []).append(memory)

    # Only expand downward from structure nodes that were directly selected as seeds.
    # Ancestors discovered while walking up from a leaf should contribute as parents,
    # but they should not re-expand sideways into sibling subtrees.
    branch_root_ids = set(structural_seed_ids)
    descendant_depths: dict[str, int] = {}
    traversal_queue = [(parent_id, 0) for parent_id in branch_root_ids]
    seen_structural_ids = set(branch_root_ids)

    while traversal_queue:
        parent_id, depth = traversal_queue.pop(0)
        if depth >= GRAPH_TRAVERSAL_DEPTH:
            continue
        for child_memory in children_by_parent.get(parent_id, []):
            if child_memory.id in seed_semantic_by_id:
                continue
            next_depth = depth + 1
            existing_depth = descendant_depths.get(child_memory.id)
            if existing_depth is None or next_depth < existing_depth:
                descendant_depths[child_memory.id] = next_depth
            if _is_structural_graph_memory(child_memory) and child_memory.id not in seen_structural_ids:
                seen_structural_ids.add(child_memory.id)
                traversal_queue.append((child_memory.id, next_depth))

    for child_id, depth in descendant_depths.items():
        child_memory = visible_memories_by_id.get(child_id)
        if not child_memory:
            continue
        semantic_score = strongest_seed_score
        score = _candidate_score(child_memory, source="graph_child", semantic_score=semantic_score) - (
            (depth - 1) * 0.015
        )
        candidates.append(
            MemoryCandidate(
                memory=child_memory,
                source="graph_child",
                semantic_score=semantic_score,
                score=round(score, 4),
            )
        )

    lateral_neighbors: dict[str, list[tuple[Memory, float, str]]] = {}
    for edge in lateral_edges or []:
        if edge.edge_type not in {"manual", RELATED_EDGE_TYPE}:
            continue
        source_memory = visible_memories_by_id.get(edge.source_memory_id)
        target_memory = visible_memories_by_id.get(edge.target_memory_id)
        if not source_memory or not target_memory:
            continue
        lateral_neighbors.setdefault(source_memory.id, []).append(
            (target_memory, float(edge.strength or 0.0), edge.edge_type)
        )
        lateral_neighbors.setdefault(target_memory.id, []).append(
            (source_memory, float(edge.strength or 0.0), edge.edge_type)
        )

    seen_related_ids: set[str] = set()
    for seed_id in seed_ids:
        for related_memory, relation_strength, edge_type in lateral_neighbors.get(seed_id, []):
            if related_memory.id in seed_semantic_by_id or related_memory.id in seen_related_ids:
                continue
            if _is_structural_graph_memory(related_memory):
                continue
            seen_related_ids.add(related_memory.id)
            semantic_score = max(strongest_seed_score, relation_strength)
            score = _candidate_score(
                related_memory,
                source="graph_related",
                semantic_score=semantic_score,
            ) + (0.02 if edge_type == "manual" else 0.0)
            candidates.append(
                MemoryCandidate(
                    memory=related_memory,
                    source="graph_related",
                    semantic_score=semantic_score,
                    score=round(score, 4),
                )
            )

    return _select_best_candidates(candidates, limit=GRAPH_MEMORY_LIMIT)


def _subject_label(subject: Memory) -> str:
    return subject.content.strip() or subject.category.strip() or subject.id


def _query_mentions_user(query: str) -> bool:
    lowered = query.casefold()
    return any(token in lowered for token in ("我", "我的", "我自己", "about me", "my ", "remember me"))


def _query_mentions_subject_kind(query: str, subject_kind: str | None) -> bool:
    if not subject_kind:
        return False
    lowered = query.casefold()
    hints = {
        "book": ("这本书", "书里", "book", "chapter"),
        "project": ("这个项目", "项目里", "project"),
        "theory": ("这个理论", "理论", "theory"),
        "domain": ("这个学科", "学科", "领域", "domain"),
        "person": ("这个人", "人物", "person"),
        "paper": ("这篇论文", "论文", "paper"),
        "course": ("这门课", "课程", "course"),
        "device": ("这个设备", "设备", "device"),
        "model": ("这个模型", "模型", "model"),
        "user": ("我", "我的", "我自己", "about me", "my "),
    }.get(subject_kind, ())
    return any(hint in lowered for hint in hints)


def _subject_matches_query(subject: Memory, query: str, query_tokens: list[str]) -> bool:
    if not query_tokens and not query.strip():
        return False
    fields = [
        subject.content,
        subject.category,
        str(subject.canonical_key or ""),
        str(get_subject_kind(subject) or ""),
    ]
    haystack = "\n".join(filter(None, fields)).casefold()
    normalized_query = query.casefold().strip()
    if normalized_query:
        if normalized_query in haystack:
            return True
        if any(field and str(field).casefold() in normalized_query for field in fields):
            return True
    return any(token in haystack for token in query_tokens)


def _sort_memories_by_activity(memories: list[Memory]) -> list[Memory]:
    return sorted(
        memories,
        key=lambda memory: (
            get_memory_salience(memory),
            _coerce_utc(memory.updated_at) or datetime.min.replace(tzinfo=timezone.utc),
            _coerce_utc(memory.created_at) or datetime.min.replace(tzinfo=timezone.utc),
        ),
        reverse=True,
    )


def _load_scope_edges(
    db: Session,
    *,
    memory_ids: list[str],
) -> list[MemoryEdge]:
    if not memory_ids:
        return []
    return (
        db.query(MemoryEdge)
        .filter(
            MemoryEdge.source_memory_id.in_(memory_ids),
            MemoryEdge.target_memory_id.in_(memory_ids),
        )
        .all()
    )


def _collect_subject_scope_memories(
    *,
    subject_ids: list[str],
    visible_permanent: list[Memory],
    visible_temporary: list[Memory],
    subjects_by_id: dict[str, Memory],
) -> tuple[list[Memory], list[Memory]]:
    selected_ids = {subject_id for subject_id in subject_ids if subject_id}
    if not selected_ids:
        return [], []

    include_legacy_user_scope = any(
        get_subject_kind(subjects_by_id.get(subject_id)) == "user"
        for subject_id in selected_ids
        if subjects_by_id.get(subject_id) is not None
    )

    def _belongs_to_scope(memory: Memory) -> bool:
        if memory.id in selected_ids:
            return True
        subject_memory_id = get_subject_memory_id(memory)
        if subject_memory_id and subject_memory_id in selected_ids:
            return True
        if include_legacy_user_scope and subject_memory_id is None:
            if is_subject_memory(memory) or is_category_path_memory(memory) or is_summary_memory(memory):
                return False
            return True
        return False

    permanent_scope = [memory for memory in visible_permanent if _belongs_to_scope(memory)]
    temporary_scope = [memory for memory in visible_temporary if _belongs_to_scope(memory)]
    return permanent_scope, temporary_scope


def _pick_active_concepts(
    *,
    subject_scope_memories: list[Memory],
    subject_ids: list[str],
    semantic_results: list[dict[str, Any]],
    query_tokens: list[str],
    active_concept_ids: list[str],
) -> list[MemoryCandidate]:
    scope_by_id = {memory.id: memory for memory in subject_scope_memories}
    candidates: list[MemoryCandidate] = []

    for rank, concept_id in enumerate(active_concept_ids):
        concept = scope_by_id.get(concept_id)
        if concept is None or not is_concept_memory(concept):
            continue
        score = _candidate_score(concept, source="graph_parent", semantic_score=0.82) - (rank * 0.02)
        candidates.append(
            MemoryCandidate(memory=concept, source="active_concept", semantic_score=0.82, score=round(score, 4))
        )

    for memory in subject_scope_memories:
        if not is_concept_memory(memory):
            continue
        if _memory_matches_query(memory, query_tokens):
            candidates.append(
                MemoryCandidate(
                    memory=memory,
                    source="lexical",
                    semantic_score=0.76,
                    score=_candidate_score(memory, source="lexical", semantic_score=0.76),
                )
            )

    for result in semantic_results:
        memory_id = result.get("memory_id")
        if not memory_id:
            continue
        memory = scope_by_id.get(memory_id)
        if memory is None or not is_concept_memory(memory):
            continue
        semantic_score = float(result.get("score") or 0.0)
        candidates.append(
            MemoryCandidate(
                memory=memory,
                source="semantic",
                semantic_score=semantic_score,
                score=_candidate_score(memory, source="semantic", semantic_score=semantic_score),
            )
        )

    selected = _select_best_candidates(candidates, limit=4)
    if selected:
        return selected

    fallback_concepts = [
        memory
        for memory in _sort_memories_by_activity(subject_scope_memories)
        if is_concept_memory(memory) and (memory.parent_memory_id in subject_ids or not memory.parent_memory_id)
    ][:3]
    return [
        MemoryCandidate(memory=memory, source="subject_overview", score=_candidate_score(memory, source="graph_parent"))
        for memory in fallback_concepts
    ]


def _pick_subject_facts(
    *,
    subject_scope_memories: list[Memory],
    subject_ids: list[str],
    semantic_results: list[dict[str, Any]],
    query_tokens: list[str],
    context_level: ContextLevel,
    allow_conflicts: bool = False,
) -> list[MemoryCandidate]:
    scope_by_id = {memory.id: memory for memory in subject_scope_memories}
    candidates: list[MemoryCandidate] = []

    for result in semantic_results:
        memory_id = result.get("memory_id")
        if not memory_id:
            continue
        memory = scope_by_id.get(memory_id)
        if memory is None or is_subject_memory(memory) or is_concept_memory(memory) or is_structural_only_memory(memory):
            continue
        semantic_score = float(result.get("score") or 0.0)
        if semantic_score < SEMANTIC_MEMORY_MIN_SCORE and not _memory_matches_query(memory, query_tokens):
            continue
        candidates.append(
            MemoryCandidate(
                memory=memory,
                source="semantic",
                semantic_score=semantic_score,
                score=_candidate_score(memory, source="semantic", semantic_score=semantic_score),
            )
        )

    for memory in subject_scope_memories:
        if is_subject_memory(memory) or is_concept_memory(memory) or is_structural_only_memory(memory):
            continue
        if _memory_matches_query(memory, query_tokens):
            candidates.append(
                MemoryCandidate(
                    memory=memory,
                    source="lexical",
                    semantic_score=0.7,
                    score=_candidate_score(memory, source="lexical", semantic_score=0.7),
                )
            )

    if context_level == "profile_only":
        for memory in subject_scope_memories:
            if is_subject_memory(memory) or is_concept_memory(memory) or is_structural_only_memory(memory):
                continue
            if is_pinned_memory(memory) or get_memory_kind(memory) in _STATIC_KINDS | {MEMORY_KIND_PREFERENCE, MEMORY_KIND_GOAL}:
                candidates.append(
                    MemoryCandidate(
                        memory=memory,
                        source="static",
                        score=_candidate_score(memory, source="static"),
                    )
                )

    selected = _select_primary_lineage_candidates(
        candidates,
        limit=RELEVANT_MEMORY_LIMIT,
        allow_conflicts=allow_conflicts,
    )
    if selected:
        return selected

    fallback_facts = [
        memory
        for memory in _sort_memories_by_activity(subject_scope_memories)
        if not is_subject_memory(memory) and not is_concept_memory(memory) and not is_structural_only_memory(memory)
    ][: max(2, min(4, RELEVANT_MEMORY_LIMIT))]
    return _select_primary_lineage_candidates([
        MemoryCandidate(memory=memory, source="fallback", score=_candidate_score(memory, source="lexical", semantic_score=0.58))
        for memory in fallback_facts
    ], limit=max(2, min(4, RELEVANT_MEMORY_LIMIT)), allow_conflicts=allow_conflicts)


def _serialize_view_hit(
    view: MemoryView,
    *,
    score: float,
    snippet: str | None = None,
    why_selected: str | None = None,
    supporting_memory_id: str | None = None,
    supporting_quote: str | None = None,
    outcome_weight: float | None = None,
) -> dict[str, Any]:
    metadata = view.metadata_json if isinstance(view.metadata_json, dict) else {}
    success_count = int(metadata.get("success_count") or 0)
    failure_count = int(metadata.get("failure_count") or 0)
    derived_weight = outcome_weight
    if derived_weight is None:
        total = success_count + failure_count
        derived_weight = 1.0 if total == 0 else max(0.75, min(1.25, 1.0 + ((success_count - failure_count) / max(total, 1)) * 0.1))
    return {
        "id": view.id,
        "view_type": view.view_type,
        "source_subject_id": view.source_subject_id,
        "score": round(float(score or 0.0), 4),
        "content": shorten_text(view.content, limit=220),
        "snippet": shorten_text(snippet or view.content, limit=220),
        "why_selected": shorten_text(why_selected, limit=160) if why_selected else None,
        "selection_reason": shorten_text(why_selected, limit=160) if why_selected else None,
        "suppression_reason": str(metadata.get("suppression_reason") or "").strip() or None,
        "outcome_weight": round(float(derived_weight or 1.0), 4),
        "supporting_memory_id": supporting_memory_id,
        "supporting_quote": shorten_text(supporting_quote, limit=220) if supporting_quote else None,
    }


def _playbook_view_recall_boost(view: MemoryView, *, requested: bool) -> float:
    if view.view_type != PLAYBOOK_VIEW_TYPE:
        return 0.0
    if is_playbook_formalized(view.metadata_json if isinstance(view.metadata_json, dict) else {}):
        return 0.34 if requested else 0.08
    return 0.08 if requested else -0.06


def _serialize_evidence_hit(
    evidence: MemoryEvidence,
    *,
    score: float,
    snippet: str | None = None,
    why_selected: str | None = None,
    supporting_memory_id: str | None = None,
) -> dict[str, Any]:
    return {
        "id": evidence.id,
        "memory_id": evidence.memory_id,
        "source_type": evidence.source_type,
        "conversation_id": evidence.conversation_id,
        "message_id": evidence.message_id,
        "episode_id": evidence.episode_id,
        "chunk_id": evidence.chunk_id,
        "confidence": round(float(evidence.confidence or 0.0), 4),
        "score": round(float(score or 0.0), 4),
        "quote_text": shorten_text(evidence.quote_text, limit=220),
        "snippet": shorten_text(snippet or evidence.quote_text, limit=220),
        "why_selected": shorten_text(why_selected, limit=160) if why_selected else None,
        "selection_reason": shorten_text(why_selected, limit=160) if why_selected else None,
        "supporting_memory_id": supporting_memory_id or evidence.memory_id,
    }


def _best_evidence_quote_for_memory(
    memory_id: str,
    *,
    evidence_by_memory_id: dict[str, MemoryEvidence],
) -> str:
    evidence = evidence_by_memory_id.get(memory_id)
    if evidence is None:
        return ""
    return str(evidence.quote_text or "").strip()


def _memory_selection_reason(candidate: MemoryCandidate) -> str:
    memory = candidate.memory
    if is_pinned_memory(memory):
        return "置顶长期记忆，按优先级保留。"

    source_reason_map = {
        "static": "来自稳定画像层，适合作为长期背景。",
        "semantic": "与当前问题语义最接近。",
        "lexical": "与当前问题关键词直接匹配。",
        "fallback": "作为兜底事实补足上下文。",
        "recent_temporary": "近期情节与当前问题相关。",
        "graph_parent": "由当前主题骨架向上追溯得到。",
        "graph_child": "由当前主题骨架向下展开得到。",
        "graph_related": "由图谱关联边扩展得到。",
        "active_concept": "命中当前激活概念骨架。",
        "conversation_focus": "沿用当前对话聚焦主体。",
        "subject_overview": "作为主体概览保留。",
        "user_default": "作为默认用户主体保留。",
    }
    if candidate.source in source_reason_map:
        return source_reason_map[candidate.source]

    kind = get_memory_kind(memory)
    if kind in {MEMORY_KIND_PROFILE, MEMORY_KIND_PREFERENCE, MEMORY_KIND_GOAL}:
        return "属于稳定画像层，适合作为回答约束。"
    if memory.type == "temporary" or kind == MEMORY_KIND_EPISODIC:
        return "属于近期情节层，用于补充时间敏感上下文。"
    return "命中当前问题的相关记忆。"


def _view_selection_reason(view: MemoryView) -> str:
    if view.view_type == PROFILE_VIEW_TYPE:
        return "画像视图概括了稳定背景。"
    if view.view_type == PLAYBOOK_VIEW_TYPE:
        return "行动经验被整理为可直接复用的步骤。"
    if view.view_type == TIMELINE_VIEW_TYPE:
        return "时间线视图补充了近期事件顺序。"
    if view.view_type == SUMMARY_VIEW_TYPE:
        return "摘要视图压缩了同主题下的关键信息。"
    return "视图内容与当前问题直接相关。"


def _evidence_selection_reason(evidence: MemoryEvidence) -> str:
    if evidence.source_type == "file":
        return "原始文件证据与当前问题直接匹配。"
    if evidence.source_type == "message":
        return "原始对话证据与当前问题直接匹配。"
    return "原始证据支撑了当前检索结果。"


def _linked_file_selection_reason(chunk: dict[str, Any]) -> str:
    filename = str(chunk.get("filename") or "").strip()
    if filename:
        return f"关联文件《{filename}》中的片段与当前问题直接匹配。"
    return "关联文件片段与当前问题直接匹配。"


def _best_file_excerpt_for_memory(memory_id: str, *, linked_file_chunks: list[dict[str, Any]]) -> str:
    for chunk in linked_file_chunks:
        memory_ids = chunk.get("memory_ids")
        if not isinstance(memory_ids, list) or memory_id not in memory_ids:
            continue
        filename = str(chunk.get("filename") or "").strip()
        chunk_text = str(chunk.get("chunk_text") or "").strip()
        if not chunk_text:
            continue
        prefix = f"[{filename}] " if filename else ""
        return shorten_text(f"{prefix}{chunk_text}", limit=220)
    return ""


def _build_graph_guided_system_prompt(
    *,
    personality: str,
    active_subjects: list[MemoryCandidate],
    active_concepts: list[MemoryCandidate],
    relevant_memories: list[MemoryCandidate],
    temporary_memories: list[MemoryCandidate],
    profile_views: list[dict[str, Any]] | None = None,
    playbook_views: list[dict[str, Any]] | None = None,
    timeline_views: list[dict[str, Any]] | None = None,
    raw_evidences: list[dict[str, Any]] | None = None,
    knowledge_chunks: list[dict[str, Any]],
    linked_file_chunks: list[dict[str, Any]],
    recent_messages: list[dict[str, str]] | None = None,
) -> str:
    parts: list[str] = []
    if personality:
        parts.append(f"你的人格设定：\n{personality}")

    if active_subjects:
        lines = [
            f"- [{get_subject_kind(candidate.memory) or 'subject'}] {candidate.memory.content}"
            for candidate in active_subjects
        ]
        parts.append("当前激活主体：\n" + "\n".join(lines))

    if active_concepts:
        lines = [f"- {candidate.memory.content}" for candidate in active_concepts]
        parts.append("当前概念骨架：\n" + "\n".join(lines))

    if profile_views:
        lines = [f"- {item['content']}" for item in profile_views if item.get("content")]
        if lines:
            parts.append("Profile：\n" + "\n".join(lines))

    if relevant_memories:
        lines = [
            f"- [{candidate.source}] {candidate.memory.content}"
            for candidate in relevant_memories
            if not is_subject_memory(candidate.memory)
        ]
        if lines:
            parts.append("Durable Facts：\n" + "\n".join(lines))

    if playbook_views:
        lines = [f"- {item['content']}" for item in playbook_views if item.get("content")]
        if lines:
            parts.append("Playbooks：\n" + "\n".join(lines))

    timeline_lines = [
        f"- {candidate.memory.content}"
        for candidate in temporary_memories
    ]
    if timeline_views:
        timeline_lines.extend(
            f"- {item['content']}"
            for item in timeline_views
            if item.get("content")
        )
    if timeline_lines:
        parts.append("Episodic Timeline：\n" + "\n".join(timeline_lines))

    if raw_evidences:
        lines = [f"- {item['quote_text']}" for item in raw_evidences if item.get("quote_text")]
        if lines:
            parts.append("Raw Evidence：\n" + "\n".join(lines))

    if knowledge_chunks:
        parts.append(
            "相关知识参考：\n"
            + "\n---\n".join(chunk["chunk_text"] for chunk in knowledge_chunks if chunk.get("chunk_text"))
        )

    if linked_file_chunks:
        linked_text = "\n---\n".join(
            f"[{chunk.get('filename') or '未命名资料'}]\n{chunk['chunk_text']}"
            for chunk in linked_file_chunks
            if chunk.get("chunk_text")
        )
        if linked_text:
            parts.append(f"与当前主体直接关联的资料摘录：\n{linked_text}")

    if recent_messages:
        history_lines: list[str] = []
        for message in recent_messages:
            role = "用户" if message.get("role") == "user" else "助手"
            content = str(message.get("content") or "").strip()
            if content:
                history_lines.append(f"{role}: {content}")
        if history_lines:
            parts.append("最近对话历史：\n" + "\n".join(history_lines))

    return "\n\n".join(parts) if parts else "你是一个有帮助的 AI 助手。"


async def resolve_active_subjects(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    conversation_id: str,
    conversation_created_by: str | None,
    query: str,
    semantic_search_fn: SemanticSearchFn = search_similar,
    semantic_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    project = (
        db.query(Project)
        .filter(
            Project.id == project_id,
            Project.workspace_id == workspace_id,
            Project.deleted_at.is_(None),
        )
        .first()
    )
    if project is not None:
        _subject, changed = ensure_project_user_subject(
            db,
            project,
            owner_user_id=conversation_created_by,
        )
        if changed:
            db.flush()

    visible_permanent, visible_temporary = _load_visible_memories(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_id=conversation_id,
        conversation_created_by=conversation_created_by,
    )
    del visible_temporary
    subject_memories = [memory for memory in visible_permanent if is_subject_memory(memory)]
    subjects_by_id = {memory.id: memory for memory in subject_memories}
    query_tokens = _normalize_query_tokens(query)
    conversation = (
        db.query(Conversation)
        .filter(
            Conversation.id == conversation_id,
            Conversation.project_id == project_id,
            Conversation.workspace_id == workspace_id,
        )
        .first()
    )
    conversation_meta = conversation.metadata_json if conversation and isinstance(conversation.metadata_json, dict) else {}
    active_subject_ids = [
        subject_id
        for subject_id in conversation_meta.get("active_subject_ids", [])
        if isinstance(subject_id, str) and subject_id in subjects_by_id
    ]

    candidates: list[MemoryCandidate] = []
    for rank, subject_id in enumerate(active_subject_ids):
        subject = subjects_by_id.get(subject_id)
        if subject is None:
            continue
        score = 0.78 - (rank * 0.05)
        if _query_mentions_subject_kind(query, get_subject_kind(subject)):
            score += 0.08
        candidates.append(
            MemoryCandidate(memory=subject, source="conversation_focus", semantic_score=0.82, score=round(score, 4))
        )

    for subject in subject_memories:
        if _subject_matches_query(subject, query, query_tokens):
            score = 0.84
            if _query_mentions_subject_kind(query, get_subject_kind(subject)):
                score += 0.08
            candidates.append(
                MemoryCandidate(memory=subject, source="lexical", semantic_score=0.84, score=round(score, 4))
            )
        elif get_subject_kind(subject) == "user" and _query_mentions_user(query):
            candidates.append(
                MemoryCandidate(memory=subject, source="user_default", semantic_score=0.72, score=0.72)
            )

    local_semantic_results = semantic_results
    if local_semantic_results is None and query.strip():
        try:
            local_semantic_results = await semantic_search_fn(
                db,
                workspace_id=workspace_id,
                project_id=project_id,
                query=query,
                limit=SEMANTIC_SEARCH_LIMIT,
            )
        except Exception:
            local_semantic_results = []
    local_semantic_results = local_semantic_results or []

    for result in local_semantic_results:
        memory_id = result.get("memory_id")
        if not memory_id:
            continue
        subject = subjects_by_id.get(memory_id)
        if subject is None:
            continue
        semantic_score = float(result.get("score") or 0.0)
        candidates.append(
            MemoryCandidate(
                memory=subject,
                source="semantic",
                semantic_score=semantic_score,
                score=_candidate_score(subject, source="semantic", semantic_score=max(semantic_score, 0.7)),
            )
        )

    selected = _select_best_candidates(candidates, limit=3)
    if not selected:
        user_subject = next((subject for subject in subject_memories if get_subject_kind(subject) == "user"), None)
        fallback_subject = user_subject or (subject_memories[0] if subject_memories else None)
        if fallback_subject is not None:
            selected = [
                MemoryCandidate(
                    memory=fallback_subject,
                    source="fallback",
                    semantic_score=0.6,
                    score=0.6,
                )
            ]

    return {
        "subjects": selected,
        "primary_subject": selected[0].memory if selected else None,
        "semantic_results": local_semantic_results,
    }


def get_subject_overview(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    conversation_id: str,
    conversation_created_by: str | None,
    subject_id: str,
) -> dict[str, Any] | None:
    visible_permanent, visible_temporary = _load_visible_memories(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_id=conversation_id,
        conversation_created_by=conversation_created_by,
    )
    del visible_temporary
    subjects_by_id = {memory.id: memory for memory in visible_permanent if is_subject_memory(memory)}
    subject = subjects_by_id.get(subject_id)
    if subject is None:
        return None
    scope_memories, _temporary_scope = _collect_subject_scope_memories(
        subject_ids=[subject_id],
        visible_permanent=visible_permanent,
        visible_temporary=[],
        subjects_by_id=subjects_by_id,
    )
    concepts = [
        memory for memory in _sort_memories_by_activity(scope_memories)
        if is_concept_memory(memory)
    ][:6]
    fact_candidates = [
        MemoryCandidate(
            memory=memory,
            source="subject_overview",
            score=_candidate_score(memory, source="lexical", semantic_score=0.6),
        )
        for memory in _sort_memories_by_activity(scope_memories)
        if not is_subject_memory(memory) and not is_concept_memory(memory) and not is_structural_only_memory(memory)
    ]
    facts = [candidate.memory for candidate in _select_primary_lineage_candidates(fact_candidates, limit=8)]
    suggested_paths = [memory.content for memory in concepts[:4]]
    return {
        "subject": subject,
        "concepts": concepts,
        "facts": facts,
        "suggested_paths": suggested_paths,
    }


def _build_parent_edge(source_id: str, target_id: str, created_at: datetime) -> dict[str, Any]:
    return {
        "id": f"parent:{source_id}:{target_id}",
        "source_memory_id": source_id,
        "target_memory_id": target_id,
        "edge_type": "parent",
        "strength": 1.0,
        "created_at": created_at,
    }


async def expand_subject_subgraph(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    conversation_id: str,
    conversation_created_by: str | None,
    subject_id: str,
    query: str,
    depth: int = 2,
    edge_types: list[str] | None = None,
    semantic_search_fn: SemanticSearchFn = search_similar,
) -> dict[str, Any] | None:
    visible_permanent, visible_temporary = _load_visible_memories(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_id=conversation_id,
        conversation_created_by=conversation_created_by,
    )
    subjects_by_id = {memory.id: memory for memory in visible_permanent if is_subject_memory(memory)}
    subject = subjects_by_id.get(subject_id)
    if subject is None:
        return None

    scope_permanent, scope_temporary = _collect_subject_scope_memories(
        subject_ids=[subject_id],
        visible_permanent=visible_permanent,
        visible_temporary=visible_temporary,
        subjects_by_id=subjects_by_id,
    )
    scope_memories = [*scope_permanent, *scope_temporary]
    scope_by_id = {memory.id: memory for memory in scope_memories}
    query_tokens = _normalize_query_tokens(query)
    semantic_results: list[dict[str, Any]] = []
    if query.strip():
        try:
            semantic_results = await semantic_search_fn(
                db,
                workspace_id=workspace_id,
                project_id=project_id,
                query=query,
                limit=SEMANTIC_SEARCH_LIMIT,
            )
        except Exception:
            semantic_results = []

    seed_ids: set[str] = {subject_id}
    for memory in scope_memories:
        if _memory_matches_query(memory, query_tokens):
            seed_ids.add(memory.id)
    for result in semantic_results:
        memory_id = result.get("memory_id")
        if isinstance(memory_id, str) and memory_id in scope_by_id:
            seed_ids.add(memory_id)

    if len(seed_ids) == 1:
        seed_ids.update(memory.id for memory in _sort_memories_by_activity(scope_memories)[:4])

    allowed_edge_types = set(edge_types or ["parent", "related", "manual", "prerequisite", "evidence"])
    scope_edges = _load_scope_edges(db, memory_ids=list(scope_by_id))
    edge_results: list[dict[str, Any]] = []
    node_ids: set[str] = set(seed_ids)

    frontier = list(seed_ids)
    visited = set(seed_ids)
    for _level in range(max(1, depth)):
        next_frontier: list[str] = []
        for current_id in frontier:
            current = scope_by_id.get(current_id)
            if current is None:
                continue
            parent_id = current.parent_memory_id
            if parent_id and parent_id in scope_by_id and "parent" in allowed_edge_types:
                node_ids.add(parent_id)
                edge_results.append(_build_parent_edge(parent_id, current_id, current.updated_at or current.created_at))
                if parent_id not in visited:
                    visited.add(parent_id)
                    next_frontier.append(parent_id)
            for child in scope_memories:
                if child.parent_memory_id != current_id:
                    continue
                if "parent" in allowed_edge_types:
                    node_ids.add(child.id)
                    edge_results.append(_build_parent_edge(current_id, child.id, child.updated_at or child.created_at))
                if child.id not in visited:
                    visited.add(child.id)
                    next_frontier.append(child.id)
            for edge in scope_edges:
                if edge.edge_type not in allowed_edge_types:
                    continue
                if edge.source_memory_id == current_id:
                    other_id = edge.target_memory_id
                elif edge.target_memory_id == current_id:
                    other_id = edge.source_memory_id
                else:
                    continue
                if other_id not in scope_by_id:
                    continue
                node_ids.add(other_id)
                edge_results.append(
                    {
                        "id": edge.id,
                        "source_memory_id": edge.source_memory_id,
                        "target_memory_id": edge.target_memory_id,
                        "edge_type": edge.edge_type,
                        "strength": edge.strength,
                        "created_at": edge.created_at,
                    }
                )
                if other_id not in visited:
                    visited.add(other_id)
                    next_frontier.append(other_id)
        frontier = next_frontier
        if not frontier:
            break

    ordered_nodes = [scope_by_id[node_id] for node_id in node_ids if node_id in scope_by_id]
    return {
        "subject": subject,
        "nodes": ordered_nodes,
        "edges": edge_results,
    }


async def search_subject_facts(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    conversation_id: str,
    conversation_created_by: str | None,
    subject_id: str,
    query: str,
    top_k: int,
    semantic_search_fn: SemanticSearchFn = search_similar,
) -> list[dict[str, Any]]:
    visible_permanent, visible_temporary = _load_visible_memories(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_id=conversation_id,
        conversation_created_by=conversation_created_by,
    )
    subjects_by_id = {memory.id: memory for memory in visible_permanent if is_subject_memory(memory)}
    scope_permanent, scope_temporary = _collect_subject_scope_memories(
        subject_ids=[subject_id],
        visible_permanent=visible_permanent,
        visible_temporary=visible_temporary,
        subjects_by_id=subjects_by_id,
    )
    scope_memories = [*scope_permanent, *scope_temporary]
    semantic_results: list[dict[str, Any]] = []
    if query.strip():
        try:
            semantic_results = await semantic_search_fn(
                db,
                workspace_id=workspace_id,
                project_id=project_id,
                query=query,
                limit=max(12, top_k * 3),
            )
        except Exception:
            semantic_results = []
    selected = _pick_subject_facts(
        subject_scope_memories=scope_memories,
        subject_ids=[subject_id],
        semantic_results=semantic_results,
        query_tokens=_normalize_query_tokens(query),
        context_level="memory_only",
        allow_conflicts=_query_requests_conflict_expansion(query),
    )[:top_k]
    return [
        {
            "id": candidate.memory.id,
            "content": candidate.memory.content,
            "category": candidate.memory.category,
            "type": candidate.memory.type,
            "score": candidate.semantic_score if candidate.semantic_score is not None else candidate.score,
            "source": candidate.source,
        }
        for candidate in selected
    ]


async def search_subject_documents(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    conversation_id: str,
    conversation_created_by: str | None,
    subject_id: str,
    query: str,
    top_k: int,
    linked_file_loader_fn: LinkedFileLoaderFn = load_linked_file_chunks_for_memories,
) -> list[dict[str, Any]]:
    visible_permanent, visible_temporary = _load_visible_memories(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_id=conversation_id,
        conversation_created_by=conversation_created_by,
    )
    subjects_by_id = {memory.id: memory for memory in visible_permanent if is_subject_memory(memory)}
    scope_permanent, scope_temporary = _collect_subject_scope_memories(
        subject_ids=[subject_id],
        visible_permanent=visible_permanent,
        visible_temporary=visible_temporary,
        subjects_by_id=subjects_by_id,
    )
    memory_ids = [memory.id for memory in [*scope_permanent, *scope_temporary]]
    if not memory_ids or not query.strip():
        return []
    try:
        chunks = await linked_file_loader_fn(
            db,
            workspace_id=workspace_id,
            project_id=project_id,
            memory_ids=memory_ids,
            query=query,
            limit=top_k,
        )
    except Exception:
        chunks = []
    return [
        {
            "filename": chunk.get("filename") or "未命名资料",
            "score": chunk.get("score"),
            "excerpt": _shorten_text(str(chunk.get("chunk_text") or ""), limit=600),
            "memory_ids": chunk.get("memory_ids") or [],
        }
        for chunk in chunks[:top_k]
    ]


def get_concept_neighbors(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    conversation_id: str,
    conversation_created_by: str | None,
    concept_id: str,
) -> dict[str, Any] | None:
    visible_permanent, visible_temporary = _load_visible_memories(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_id=conversation_id,
        conversation_created_by=conversation_created_by,
    )
    del visible_temporary
    memories_by_id = {memory.id: memory for memory in visible_permanent}
    concept = memories_by_id.get(concept_id)
    if concept is None or not is_concept_memory(concept):
        return None
    subject_id = get_subject_memory_id(concept)
    related_edges = _load_scope_edges(db, memory_ids=list(memories_by_id))
    children = [
        memory for memory in visible_permanent
        if memory.parent_memory_id == concept.id and get_subject_memory_id(memory) == subject_id
    ]
    neighbors: list[dict[str, Any]] = []
    for edge in related_edges:
        if edge.source_memory_id == concept.id:
            other_id = edge.target_memory_id
        elif edge.target_memory_id == concept.id:
            other_id = edge.source_memory_id
        else:
            continue
        other = memories_by_id.get(other_id)
        if other is None:
            continue
        neighbors.append(
            {
                "id": other.id,
                "content": other.content,
                "edge_type": edge.edge_type,
            }
        )
    return {
        "concept": concept,
        "parent": memories_by_id.get(concept.parent_memory_id or ""),
        "children": children,
        "neighbors": neighbors,
        "recent_facts": [
            memory for memory in _sort_memories_by_activity(children)
            if not is_concept_memory(memory)
        ][:6],
    }


def get_explanation_path(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    conversation_id: str,
    conversation_created_by: str | None,
    subject_id: str,
    concept_id: str,
    target_style: str | None = None,
) -> dict[str, Any] | None:
    del target_style
    overview = get_concept_neighbors(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_id=conversation_id,
        conversation_created_by=conversation_created_by,
        concept_id=concept_id,
    )
    if overview is None:
        return None
    concept = overview["concept"]
    parent_chain: list[str] = []
    current = overview.get("parent")
    while isinstance(current, Memory):
        parent_chain.append(current.content)
        if current.parent_memory_id == subject_id:
            break
        current = (
            db.query(Memory)
            .filter(
                Memory.id == current.parent_memory_id,
                Memory.workspace_id == workspace_id,
                Memory.project_id == project_id,
            )
            .first()
        )
    return {
        "concept_id": concept.id,
        "concept": concept.content,
        "parent_chain": list(reversed(parent_chain)),
        "recommended_order": [
            *list(reversed(parent_chain)),
            concept.content,
            *[child.content for child in overview.get("children", [])[:3]],
        ],
        "related_concepts": [
            neighbor["content"]
            for neighbor in overview.get("neighbors", [])
            if neighbor.get("edge_type") in {"related", "prerequisite"}
        ][:4],
        "recent_facts": [memory.content for memory in overview.get("recent_facts", [])[:4]],
    }


def _build_system_prompt(
    *,
    personality: str,
    static_memories: list[MemoryCandidate],
    relevant_memories: list[MemoryCandidate],
    temporary_memories: list[MemoryCandidate],
    knowledge_chunks: list[dict[str, Any]],
    linked_file_chunks: list[dict[str, Any]],
    recent_messages: list[dict[str, str]] | None = None,
) -> str:
    static_memories = [candidate for candidate in static_memories if not is_structural_only_memory(candidate.memory)]
    relevant_memories = [candidate for candidate in relevant_memories if not is_structural_only_memory(candidate.memory)]
    temporary_memories = [candidate for candidate in temporary_memories if not is_structural_only_memory(candidate.memory)]
    parts: list[str] = []
    if personality:
        parts.append(f"你的人格设定：\n{personality}")

    if static_memories:
        lines = [
            f"- [{get_memory_kind(candidate.memory)}] {candidate.memory.content}"
            for candidate in static_memories
        ]
        parts.append("用户的长期画像与稳定偏好：\n" + "\n".join(lines))

    if relevant_memories:
        lines = [
            f"- [{candidate.source}] {candidate.memory.content}"
            for candidate in relevant_memories
        ]
        parts.append("与当前问题最相关的记忆：\n" + "\n".join(lines))

    if temporary_memories:
        lines = [f"- {candidate.memory.content}" for candidate in temporary_memories]
        parts.append("当前会话中刚形成或只在本次对话生效的记忆：\n" + "\n".join(lines))

    if knowledge_chunks:
        parts.append(
            "相关知识参考（来自用户上传的资料）：\n"
            + "\n---\n".join(chunk["chunk_text"] for chunk in knowledge_chunks if chunk.get("chunk_text"))
        )

    if linked_file_chunks:
        linked_text = "\n---\n".join(
            f"[{chunk.get('filename') or '未命名资料'}]\n{chunk['chunk_text']}"
            for chunk in linked_file_chunks
            if chunk.get("chunk_text")
        )
        if linked_text:
            parts.append(f"与当前主体直接关联的资料摘录：\n{linked_text}")

    if recent_messages:
        history_lines: list[str] = []
        for message in recent_messages:
            role = "用户" if message.get("role") == "user" else "助手"
            content = str(message.get("content") or "").strip()
            if content:
                history_lines.append(f"{role}: {content}")
        if history_lines:
            parts.append("最近对话历史：\n" + "\n".join(history_lines))

    return "\n\n".join(parts) if parts else "你是一个有帮助的 AI 助手。"


def _serialize_memory_candidate(
    candidate: MemoryCandidate,
    *,
    why_selected: str | None = None,
    supporting_quote: str | None = None,
    supporting_file_excerpt: str | None = None,
    supporting_memory_id: str | None = None,
    episode_ids: list[str] | None = None,
) -> dict[str, Any]:
    memory = candidate.memory
    return {
        "id": memory.id,
        "type": memory.type,
        "node_type": memory.node_type,
        "node_status": memory.node_status,
        "category": memory.category,
        "memory_kind": get_memory_kind(memory),
        "lineage_key": get_lineage_key(memory),
        "source": candidate.source,
        "score": round(candidate.score, 4),
        "semantic_score": round(candidate.semantic_score, 4) if candidate.semantic_score is not None else None,
        "pinned": is_pinned_memory(memory),
        "salience": round(get_memory_salience(memory), 4),
        "content": shorten_text(memory.content, limit=180),
        "why_selected": shorten_text(why_selected, limit=160) if why_selected else None,
        "selection_reason": shorten_text(why_selected, limit=160) if why_selected else None,
        "suppression_reason": _suppression_reason_for_memory(memory),
        "outcome_weight": _memory_outcome_weight(memory),
        "episode_ids": [
            episode_id
            for episode_id in (episode_ids or [])
            if isinstance(episode_id, str) and episode_id.strip()
        ],
        "supporting_quote": shorten_text(supporting_quote, limit=220) if supporting_quote else None,
        "supporting_file_excerpt": shorten_text(supporting_file_excerpt, limit=220) if supporting_file_excerpt else None,
        "supporting_memory_id": supporting_memory_id or memory.id,
    }


def _serialize_chunk(chunk: dict[str, Any], *, why_selected: str | None = None) -> dict[str, Any]:
    return {
        "id": chunk.get("id"),
        "data_item_id": chunk.get("data_item_id"),
        "filename": chunk.get("filename"),
        "memory_ids": [
            str(memory_id)
            for memory_id in chunk.get("memory_ids", [])
            if isinstance(memory_id, str) and str(memory_id).strip()
        ],
        "score": round(float(chunk.get("score") or 0.0), 4),
        "chunk_text": shorten_text(str(chunk.get("chunk_text") or ""), limit=220),
        "why_selected": shorten_text(why_selected, limit=160) if why_selected else None,
    }


def build_conversation_focus_metadata(
    *,
    existing_metadata: dict[str, Any] | None,
    retrieval_trace: dict[str, Any] | None,
    updated_at: datetime | None = None,
) -> dict[str, Any]:
    payload = dict(existing_metadata or {})
    if not isinstance(retrieval_trace, dict):
        return payload

    active_subject_ids = [
        subject_id
        for subject_id in retrieval_trace.get("active_subject_ids", [])
        if isinstance(subject_id, str) and subject_id.strip()
    ]
    active_concept_ids = [
        concept_id
        for concept_id in retrieval_trace.get("active_concept_ids", [])
        if isinstance(concept_id, str) and concept_id.strip()
    ]
    active_fact_ids = [
        fact_id
        for fact_id in retrieval_trace.get("active_fact_ids", [])
        if isinstance(fact_id, str) and fact_id.strip()
    ]
    primary_subject_id = retrieval_trace.get("primary_subject_id")
    if isinstance(primary_subject_id, str) and primary_subject_id.strip():
        payload["primary_subject_id"] = primary_subject_id.strip()
    if active_subject_ids:
        payload["active_subject_ids"] = active_subject_ids[:3]
    if active_concept_ids:
        payload["active_concept_ids"] = active_concept_ids[:6]
    if active_fact_ids:
        payload["active_fact_ids"] = active_fact_ids[:8]
    explanation_path = retrieval_trace.get("explanation_path")
    if isinstance(explanation_path, dict):
        payload["explanation_path"] = {
            "concept_ids": [
                concept_id
                for concept_id in explanation_path.get("concept_ids", [])
                if isinstance(concept_id, str) and concept_id.strip()
            ][:4],
            "labels": [
                label
                for label in explanation_path.get("labels", [])
                if isinstance(label, str) and label.strip()
            ][:6],
        }
    payload["graph_first"] = bool(retrieval_trace.get("graph_first"))
    payload["has_conflict"] = bool(retrieval_trace.get("has_conflict"))
    conflict_memory_ids = [
        memory_id
        for memory_id in retrieval_trace.get("conflict_memory_ids", [])
        if isinstance(memory_id, str) and memory_id.strip()
    ]
    if conflict_memory_ids:
        payload["conflict_memory_ids"] = conflict_memory_ids[:8]
    if active_subject_ids or active_concept_ids or payload.get("primary_subject_id"):
        payload["focus_strategy"] = str(retrieval_trace.get("strategy") or "layered_memory_v2")
        payload["focus_updated_at"] = (updated_at or datetime.now(timezone.utc)).isoformat()
        payload["active_route"] = str(
            retrieval_trace.get("active_route")
            or retrieval_trace.get("context_level")
            or payload.get("focus_strategy")
            or "layered_memory_v2"
        )
        payload["interaction_mode"] = str(
            retrieval_trace.get("interaction_mode")
            or ("subject_graph" if active_subject_ids or active_concept_ids else "direct")
        )
        payload["last_graph_focus"] = {
            "strategy": str(retrieval_trace.get("strategy") or "layered_memory_v2"),
            "primary_subject_id": payload.get("primary_subject_id"),
            "active_subject_ids": active_subject_ids[:3],
            "active_concept_ids": active_concept_ids[:6],
            "active_fact_ids": active_fact_ids[:8],
            "memory_ids": [
                memory_id
                for memory_id in (
                    active_fact_ids
                    or [
                        str(memory.get("id") or "").strip()
                        for memory in retrieval_trace.get("memories", [])
                        if isinstance(memory, dict)
                    ]
                )
                if memory_id
            ][:10],
            "explanation_path": payload.get("explanation_path"),
            "graph_first": payload.get("graph_first", False),
            "has_conflict": payload.get("has_conflict", False),
            "updated_at": payload["focus_updated_at"],
        }
    return payload


async def graph_preflight(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    conversation_id: str,
    user_message: str,
    context_level: ContextLevel,
    semantic_search_fn: SemanticSearchFn = search_similar,
    linked_file_loader_fn: LinkedFileLoaderFn = load_linked_file_chunks_for_memories,
) -> GraphPreflightResult:
    project, conversation = load_conversation_context(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_id=conversation_id,
    )

    if context_level == "none":
        return GraphPreflightResult(
            active_subjects=[],
            primary_subject=None,
            active_concepts=[],
            active_facts=[],
            static_memories=[],
            graph_memories=[],
            temporary_memories=[],
            knowledge_chunks=[],
            linked_file_chunks=[],
            explanation_path=None,
            evidence_query_set=[],
            primary_fact_ids_by_lineage={},
            has_conflict=False,
            conflict_memory_ids=[],
            preflight_steps=[],
            selected_edge_types=["parent", "related", "manual", "prerequisite", "evidence"],
        )

    _subject, changed = ensure_project_user_subject(
        db,
        project,
        owner_user_id=conversation.created_by,
    )
    if changed:
        db.flush()

    timeline_requested = _query_requests_timeline(user_message)
    permanent_memories, temporary_memories = _load_visible_memories(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_id=conversation_id,
        conversation_created_by=conversation.created_by,
        include_inactive=timeline_requested,
    )
    query_tokens = _normalize_query_tokens(user_message)
    semantic_results: list[dict[str, Any]] = []
    if user_message.strip() and context_level in {"profile_only", "memory_only", "full_rag"}:
        try:
            semantic_results = await semantic_search_fn(
                db,
                workspace_id=workspace_id,
                project_id=project_id,
                query=user_message,
                limit=SEMANTIC_SEARCH_LIMIT,
            )
        except Exception:
            semantic_results = []

    subject_resolution = await resolve_active_subjects(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_id=conversation_id,
        conversation_created_by=conversation.created_by,
        query=user_message,
        semantic_search_fn=semantic_search_fn,
        semantic_results=semantic_results,
    )
    active_subjects = subject_resolution.get("subjects", [])
    primary_subject = subject_resolution.get("primary_subject")
    subject_ids = [candidate.id for candidate in active_subjects]
    subjects_by_id = {memory.id: memory for memory in permanent_memories if is_subject_memory(memory)}
    scope_permanent, scope_temporary = _collect_subject_scope_memories(
        subject_ids=subject_ids,
        visible_permanent=permanent_memories,
        visible_temporary=temporary_memories,
        subjects_by_id=subjects_by_id,
    )
    scope_memories = [*scope_permanent, *scope_temporary]
    scope_by_id = {memory.id: memory for memory in scope_memories}
    selected_edge_types = ["parent", "related", "manual", "prerequisite", "evidence"]
    lateral_edges = (
        db.query(MemoryEdge)
        .filter(
            MemoryEdge.edge_type.in_(selected_edge_types),
            MemoryEdge.source_memory_id.in_(list(scope_by_id)),
            MemoryEdge.target_memory_id.in_(list(scope_by_id)),
        )
        .all()
        if scope_by_id
        else []
    )

    static_candidates = [
        MemoryCandidate(
            memory=memory,
            source="static",
            score=_candidate_score(memory, source="static"),
        )
        for memory in scope_permanent
        if not is_subject_memory(memory)
        and not is_concept_memory(memory)
        and not is_structural_only_memory(memory)
        and (is_pinned_memory(memory) or get_memory_kind(memory) in _STATIC_KINDS)
    ]
    static_selected = _select_best_candidates(static_candidates, limit=STATIC_MEMORY_LIMIT)

    allow_conflicts = timeline_requested
    active_concepts: list[MemoryCandidate] = []
    active_facts: list[MemoryCandidate] = []
    graph_selected: list[MemoryCandidate] = []
    temporary_selected: list[MemoryCandidate] = []
    knowledge_chunks: list[dict[str, Any]] = []
    linked_file_chunks: list[dict[str, Any]] = []
    explanation_path: dict[str, Any] | None = None
    preflight_steps = ["resolve_active_subjects"]

    if context_level in {"profile_only", "memory_only", "full_rag"} and scope_memories:
        active_concepts = _pick_active_concepts(
            subject_scope_memories=scope_memories,
            subject_ids=subject_ids,
            semantic_results=semantic_results,
            query_tokens=query_tokens,
            active_concept_ids=[
                concept_id
                for concept_id in ((conversation.metadata_json or {}).get("active_concept_ids") or [])
                if isinstance(concept_id, str)
            ],
        )
        active_facts = _pick_subject_facts(
            subject_scope_memories=scope_memories,
            subject_ids=subject_ids,
            semantic_results=semantic_results,
            query_tokens=query_tokens,
            context_level=context_level,
            allow_conflicts=allow_conflicts,
        )
        graph_selected = _build_graph_neighbors(
            seed_candidates=[*active_concepts, *active_facts],
            visible_memories_by_id=scope_by_id,
            query_tokens=query_tokens,
            lateral_edges=lateral_edges,
        )
        temporary_candidates = [
            candidate
            for candidate in [*active_facts, *graph_selected]
            if candidate.memory.type == "temporary"
        ]
        temporary_candidates.extend(
            MemoryCandidate(
                memory=memory,
                source="recent_temporary",
                score=_candidate_score(memory, source="recent_temporary"),
            )
            for memory in sorted(
                scope_temporary,
                key=lambda item: _candidate_updated_at(item),
                reverse=True,
            )[:TEMPORARY_MEMORY_LIMIT]
            if not is_subject_memory(memory) and not is_concept_memory(memory)
        )
        temporary_selected = _select_best_candidates(temporary_candidates, limit=TEMPORARY_MEMORY_LIMIT)
        preflight_steps.extend(["expand_subject_subgraph", "search_subject_facts"])

        if primary_subject and active_concepts:
            explanation_path = get_explanation_path(
                db,
                workspace_id=workspace_id,
                project_id=project_id,
                conversation_id=conversation_id,
                conversation_created_by=conversation.created_by,
                subject_id=primary_subject.id,
                concept_id=active_concepts[0].id,
            )
            if explanation_path:
                preflight_steps.append("get_explanation_path")

        if context_level == "full_rag" and semantic_results:
            knowledge_chunks = filter_knowledge_chunks(
                db,
                workspace_id=workspace_id,
                project_id=project_id,
                results=[result for result in semantic_results if result.get("memory_id") is None],
            )[:KNOWLEDGE_CHUNK_LIMIT]

        evidence_query_set = [
            value
            for value in [
                user_message.strip(),
                explanation_path.get("concept") if isinstance(explanation_path, dict) else None,
                primary_subject.content.strip() if primary_subject else None,
            ]
            if isinstance(value, str) and value.strip()
        ]
        selected_memory_ids = {
            candidate.id
            for candidate in [
                *active_subjects,
                *active_concepts,
                *static_selected,
                *active_facts,
                *graph_selected,
                *temporary_selected,
            ]
        }
        if context_level == "full_rag" and evidence_query_set and selected_memory_ids:
            try:
                linked_file_chunks = await linked_file_loader_fn(
                    db,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    memory_ids=list(selected_memory_ids),
                    query=evidence_query_set[0],
                    limit=LINKED_FILE_CHUNK_LIMIT,
                )
            except Exception:
                linked_file_chunks = []
            if linked_file_chunks:
                preflight_steps.append("search_subject_documents")
    else:
        evidence_query_set = [user_message.strip()] if user_message.strip() else []

    active_scope_conflicts = _collect_conflict_memory_ids(scope_memories)
    primary_fact_ids_by_lineage = {
        _lineage_bucket_id(candidate.memory): candidate.id
        for candidate in active_facts
        if is_fact_memory(candidate.memory)
    }

    return GraphPreflightResult(
        active_subjects=active_subjects,
        primary_subject=primary_subject,
        active_concepts=active_concepts,
        active_facts=active_facts,
        static_memories=static_selected,
        graph_memories=graph_selected,
        temporary_memories=temporary_selected,
        knowledge_chunks=knowledge_chunks,
        linked_file_chunks=linked_file_chunks,
        explanation_path=explanation_path,
        evidence_query_set=evidence_query_set,
        primary_fact_ids_by_lineage=primary_fact_ids_by_lineage,
        has_conflict=bool(active_scope_conflicts),
        conflict_memory_ids=active_scope_conflicts,
        preflight_steps=preflight_steps,
        selected_edge_types=selected_edge_types,
    )


async def build_memory_context(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    conversation_id: str,
    user_message: str,
    recent_messages: list[dict[str, str]],
    personality: str = "",
    context_level: ContextLevel = "full_rag",
    include_recent_history: bool = False,
    semantic_search_fn: SemanticSearchFn = search_similar,
    linked_file_loader_fn: LinkedFileLoaderFn = load_linked_file_chunks_for_memories,
) -> MemoryContextResult:
    project, conversation = load_conversation_context(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_id=conversation_id,
    )
    preflight = await graph_preflight(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_id=conversation_id,
        user_message=user_message,
        context_level=context_level,
        semantic_search_fn=semantic_search_fn,
        linked_file_loader_fn=linked_file_loader_fn,
    )
    active_subjects = preflight.active_subjects
    active_concepts = preflight.active_concepts
    static_selected = preflight.static_memories
    relevant_selected = preflight.active_facts
    graph_selected = preflight.graph_memories
    temporary_selected = preflight.temporary_memories
    knowledge_chunks = preflight.knowledge_chunks
    linked_file_chunks = preflight.linked_file_chunks
    primary_subject = preflight.primary_subject

    explanation_path_summary = None
    if isinstance(preflight.explanation_path, dict):
        explanation_path_summary = {
            "concept_ids": [
                concept_id
                for concept_id in [preflight.explanation_path.get("concept_id")]
                if isinstance(concept_id, str) and concept_id.strip()
            ],
            "labels": [
                label
                for label in [
                    *(
                        preflight.explanation_path.get("parent_chain")
                        if isinstance(preflight.explanation_path.get("parent_chain"), list)
                        else []
                    ),
                    preflight.explanation_path.get("concept"),
                ]
                if isinstance(label, str) and label.strip()
            ],
        }
    timeline_requested = _query_requests_timeline(user_message)
    allow_conflicts = timeline_requested
    profile_priority = _query_prefers_profile_views(user_message)
    playbook_priority = _query_prefers_playbook_views(user_message)
    policy_flags = [
        flag
        for flag, enabled in (
            ("profile_priority", profile_priority),
            ("playbook_priority", playbook_priority),
            ("timeline_expansion", timeline_requested),
            ("full_rag", context_level == "full_rag"),
        )
        if enabled
    ]

    visible_permanent, visible_temporary = _load_visible_memories(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_id=conversation_id,
        conversation_created_by=conversation.created_by,
        include_inactive=timeline_requested,
    )
    subjects_by_id = {
        memory.id: memory
        for memory in visible_permanent
        if is_subject_memory(memory)
    }
    scope_permanent, scope_temporary = _collect_subject_scope_memories(
        subject_ids=[candidate.id for candidate in active_subjects],
        visible_permanent=visible_permanent,
        visible_temporary=visible_temporary,
        subjects_by_id=subjects_by_id,
    )
    scope_memories = [*scope_permanent, *scope_temporary] or [*visible_permanent, *visible_temporary]
    scope_by_id = {memory.id: memory for memory in scope_memories}
    suppressed_memory_ids: list[str] = []

    memory_candidate_pool: dict[str, MemoryCandidate] = {}

    def _register_memory_candidate(candidate: MemoryCandidate) -> None:
        memory = candidate.memory
        if scope_by_id and memory.id not in scope_by_id:
            return
        if not timeline_requested and (not is_active_memory(memory) or not _memory_is_currently_valid(memory)):
            if memory.id not in suppressed_memory_ids:
                suppressed_memory_ids.append(memory.id)
            return
        current = memory_candidate_pool.get(candidate.id)
        if current is None or candidate.score > current.score:
            memory_candidate_pool[candidate.id] = candidate

    for candidate in _select_primary_lineage_candidates(
        [
            *active_subjects,
            *active_concepts,
            *static_selected,
            *relevant_selected,
            *graph_selected,
            *temporary_selected,
        ],
        limit=LAYERED_RERANK_LIMIT,
        allow_conflicts=allow_conflicts,
    ):
        _register_memory_candidate(candidate)

    try:
        lexical_memory_hits = search_memories_lexical(
            db,
            workspace_id=workspace_id,
            project_id=project_id,
            query=user_message,
            limit=12,
        )
    except Exception:
        lexical_memory_hits = []
    for hit in lexical_memory_hits:
        memory = scope_by_id.get(str(hit.get("memory_id") or ""))
        if memory is None:
            continue
        lexical_score = float(hit.get("score") or 0.0)
        _register_memory_candidate(
            MemoryCandidate(
                memory=memory,
                source="lexical",
                semantic_score=lexical_score,
                score=_candidate_score(memory, source="lexical", semantic_score=lexical_score),
            )
        )

    candidate_memory_ids = list(memory_candidate_pool)
    evidence_by_memory_id: dict[str, MemoryEvidence] = {}
    if candidate_memory_ids:
        for evidence in (
            db.query(MemoryEvidence)
            .filter(MemoryEvidence.memory_id.in_(candidate_memory_ids))
            .order_by(MemoryEvidence.created_at.desc())
            .all()
        ):
            if evidence.memory_id not in evidence_by_memory_id and str(evidence.quote_text or "").strip():
                evidence_by_memory_id[evidence.memory_id] = evidence

    view_pool: dict[str, dict[str, Any]] = {}

    def _register_view(view: MemoryView, *, score: float, snippet: str | None = None) -> None:
        if not _view_visible_to_conversation(view, conversation_created_by=conversation.created_by):
            return
        current = view_pool.get(view.id)
        if current is None or score > float(current["score"]):
            view_pool[view.id] = {
                "view": view,
                "score": float(score),
                "snippet": snippet or view.content,
            }

    view_query = db.query(MemoryView).filter(
        MemoryView.project_id == project_id,
        MemoryView.workspace_id == workspace_id,
    )
    active_subject_ids = [candidate.id for candidate in active_subjects]
    if active_subject_ids:
        view_query = view_query.filter(MemoryView.source_subject_id.in_(active_subject_ids))
    subject_views = view_query.order_by(MemoryView.updated_at.desc()).all()
    for view in subject_views:
        base_score = 0.46
        if view.view_type == PROFILE_VIEW_TYPE and profile_priority:
            base_score += 0.34
        elif view.view_type == PLAYBOOK_VIEW_TYPE:
            base_score += _playbook_view_recall_boost(view, requested=playbook_priority)
        elif view.view_type == TIMELINE_VIEW_TYPE and timeline_requested:
            base_score += 0.28
        elif view.view_type == SUMMARY_VIEW_TYPE:
            base_score += 0.08
        _register_view(view, score=base_score)

    try:
        lexical_view_hits = search_memory_views_lexical(
            db,
            workspace_id=workspace_id,
            project_id=project_id,
            query=user_message,
            limit=10,
            subject_ids=active_subject_ids or None,
        )
    except Exception:
        lexical_view_hits = []
    subject_views_by_id = {view.id: view for view in subject_views}
    for hit in lexical_view_hits:
        view = subject_views_by_id.get(str(hit.get("view_id") or ""))
        if view is None:
            fetched_view = db.get(MemoryView, str(hit.get("view_id") or ""))
            if fetched_view is None:
                continue
            view = fetched_view
        lexical_score = 0.52 + float(hit.get("score") or 0.0)
        if view.view_type == PROFILE_VIEW_TYPE and profile_priority:
            lexical_score += 0.16
        if view.view_type == PLAYBOOK_VIEW_TYPE:
            lexical_score += 0.16 if is_playbook_formalized(
                view.metadata_json if isinstance(view.metadata_json, dict) else {}
            ) and playbook_priority else (0.04 if playbook_priority else -0.04)
        if view.view_type == TIMELINE_VIEW_TYPE and timeline_requested:
            lexical_score += 0.12
        _register_view(view, score=lexical_score, snippet=str(hit.get("snippet") or view.content))

    evidence_pool: dict[str, dict[str, Any]] = {}
    try:
        lexical_evidence_hits = search_memory_evidences_lexical(
            db,
            workspace_id=workspace_id,
            project_id=project_id,
            query=user_message,
            limit=10,
        )
    except Exception:
        lexical_evidence_hits = []
    for hit in lexical_evidence_hits:
        memory = scope_by_id.get(str(hit.get("memory_id") or ""))
        if memory is None:
            continue
        if not timeline_requested and (not is_active_memory(memory) or not _memory_is_currently_valid(memory)):
            continue
        evidence = db.get(MemoryEvidence, str(hit.get("evidence_id") or ""))
        if evidence is None:
            continue
        base_score = 0.44 + float(hit.get("score") or 0.0)
        if timeline_requested and (
            memory.type == "temporary"
            or get_memory_kind(memory) == MEMORY_KIND_EPISODIC
            or memory.node_status != "active"
        ):
            base_score += 0.08
        current = evidence_pool.get(evidence.id)
        if current is None or base_score > float(current["score"]):
            evidence_pool[evidence.id] = {
                "evidence": evidence,
                "score": base_score,
                "snippet": str(hit.get("snippet") or evidence.quote_text),
            }

    candidate_registry: dict[str, dict[str, Any]] = {}

    def _register_candidate_doc(
        *,
        key: str,
        result_type: str,
        base_score: float,
        text: str,
        snippet: str,
        candidate: MemoryCandidate | None = None,
        view: MemoryView | None = None,
        evidence: MemoryEvidence | None = None,
        supporting_memory_id: str | None = None,
    ) -> None:
        current = candidate_registry.get(key)
        if current is None or base_score > float(current["base_score"]):
            candidate_registry[key] = {
                "key": key,
                "result_type": result_type,
                "base_score": float(base_score),
                "text": text,
                "snippet": snippet,
                "candidate": candidate,
                "view": view,
                "evidence": evidence,
                "supporting_memory_id": supporting_memory_id,
            }

    for candidate in memory_candidate_pool.values():
        memory = candidate.memory
        subject_memory = scope_by_id.get(get_subject_memory_id(memory) or "")
        evidence_quote = _best_evidence_quote_for_memory(
            memory.id,
            evidence_by_memory_id=evidence_by_memory_id,
        )
        kind = get_memory_kind(memory)
        layer_bias = 0.0
        if profile_priority and kind in {MEMORY_KIND_PROFILE, MEMORY_KIND_PREFERENCE, MEMORY_KIND_GOAL}:
            layer_bias += 0.16
        if timeline_requested and (
            memory.type == "temporary"
            or kind == MEMORY_KIND_EPISODIC
            or memory.node_status != "active"
        ):
            layer_bias += 0.12
        if not timeline_requested and memory.node_status != "active":
            layer_bias -= 0.3
        rerank_text = "\n".join(
            part
            for part in (
                f"Subject: {_subject_label(subject_memory)}" if subject_memory else "",
                f"Category: {memory.category}" if memory.category else "",
                f"Memory: {memory.content}",
                f"Evidence: {evidence_quote}" if evidence_quote else "",
            )
            if part
        )
        _register_candidate_doc(
            key=f"memory:{memory.id}",
            result_type="memory",
            base_score=float(candidate.score) + layer_bias,
            text=rerank_text,
            snippet=evidence_quote or memory.content,
            candidate=candidate,
            supporting_memory_id=memory.id,
        )

    for payload in view_pool.values():
        view = payload["view"]
        supporting_memory_id = None
        metadata = view.metadata_json if isinstance(view.metadata_json, dict) else {}
        source_memory_ids = metadata.get("source_memory_ids")
        if isinstance(source_memory_ids, list):
            supporting_memory_id = next(
                (str(item).strip() for item in source_memory_ids if isinstance(item, str) and str(item).strip()),
                None,
            )
        if supporting_memory_id is None:
            supporting_memory_id = str(view.source_subject_id or "").strip() or None
        evidence_quote = (
            _best_evidence_quote_for_memory(
                supporting_memory_id,
                evidence_by_memory_id=evidence_by_memory_id,
            )
            if supporting_memory_id
            else ""
        )
        subject_memory = scope_by_id.get(str(view.source_subject_id or ""))
        _register_candidate_doc(
            key=f"view:{view.id}",
            result_type="view",
            base_score=float(payload["score"]),
            text="\n".join(
                part
                for part in (
                    f"Subject: {_subject_label(subject_memory)}" if subject_memory else "",
                    f"View Type: {view.view_type}",
                    f"View: {view.content}",
                    f"Evidence: {evidence_quote}" if evidence_quote else "",
                )
                if part
            ),
            snippet=str(payload["snippet"] or view.content),
            view=view,
            supporting_memory_id=supporting_memory_id,
        )

    for payload in evidence_pool.values():
        evidence = payload["evidence"]
        memory = scope_by_id.get(evidence.memory_id)
        if memory is None:
            continue
        subject_memory = scope_by_id.get(get_subject_memory_id(memory) or "")
        _register_candidate_doc(
            key=f"evidence:{evidence.id}",
            result_type="evidence",
            base_score=float(payload["score"]),
            text="\n".join(
                part
                for part in (
                    f"Subject: {_subject_label(subject_memory)}" if subject_memory else "",
                    f"Category: {memory.category}" if memory.category else "",
                    f"Memory: {memory.content}",
                    f"Evidence: {evidence.quote_text}",
                )
                if part
            ),
            snippet=str(payload["snippet"] or evidence.quote_text),
            evidence=evidence,
            supporting_memory_id=evidence.memory_id,
        )

    rerank_latency_ms = 0.0
    reranked_items: list[dict[str, Any]] = []
    if candidate_registry:
        candidate_docs = sorted(
            candidate_registry.values(),
            key=lambda item: float(item["base_score"]),
            reverse=True,
        )[:LAYERED_RERANK_LIMIT]
        rerank_input = [
            RerankDocument(
                key=str(item["key"]),
                text=str(item["text"]),
                score=float(item["base_score"]),
            )
            for item in candidate_docs
        ]
        started_at = perf_counter()
        try:
            reranked_docs = await rerank_documents(user_message, rerank_input)
        except Exception:
            reranked_docs = rerank_input
        rerank_latency_ms = round((perf_counter() - started_at) * 1000, 2)
        for document in reranked_docs:
            item = candidate_registry.get(document.key)
            if item is None:
                continue
            reranked_items.append(
                {
                    **item,
                    "score": float(document.score),
                }
            )

    final_selected_memories: list[MemoryCandidate] = []
    selected_lineage_keys: set[str] = set()
    for item in reranked_items:
        if item.get("result_type") != "memory":
            continue
        candidate = item.get("candidate")
        if not isinstance(candidate, MemoryCandidate):
            continue
        memory = candidate.memory
        if not timeline_requested and (not is_active_memory(memory) or not _memory_is_currently_valid(memory)):
            if memory.id not in suppressed_memory_ids:
                suppressed_memory_ids.append(memory.id)
            continue
        if not allow_conflicts and is_fact_memory(memory):
            lineage_key = _lineage_bucket_id(memory)
            if lineage_key in selected_lineage_keys:
                if memory.id not in suppressed_memory_ids:
                    suppressed_memory_ids.append(memory.id)
                continue
            selected_lineage_keys.add(lineage_key)
        final_selected_memories.append(
            MemoryCandidate(
                memory=memory,
                source=candidate.source,
                semantic_score=candidate.semantic_score,
                score=round(float(item.get("score") or candidate.score), 4),
            )
        )
        if len(final_selected_memories) >= LAYERED_MEMORY_LIMIT:
            break

    if not final_selected_memories:
        final_selected_memories = _select_primary_lineage_candidates(
            [
                *active_subjects,
                *active_concepts,
                *static_selected,
                *relevant_selected,
                *graph_selected,
                *temporary_selected,
            ],
            limit=LAYERED_MEMORY_LIMIT,
            allow_conflicts=allow_conflicts,
        )

    ordered_view_hits: list[dict[str, Any]] = []
    ordered_evidence_hits: list[dict[str, Any]] = []
    for item in reranked_items:
        if (
            item.get("result_type") == "view"
            and item.get("view") is not None
            and len(ordered_view_hits) < LAYERED_VIEW_LIMIT
        ):
            ordered_view_hits.append(item)
        if (
            item.get("result_type") == "evidence"
            and item.get("evidence") is not None
            and len(ordered_evidence_hits) < LAYERED_EVIDENCE_LIMIT
        ):
            ordered_evidence_hits.append(item)

    evidence_hit_ids = {
        str(item["evidence"].id)
        for item in ordered_evidence_hits
        if isinstance(item.get("evidence"), MemoryEvidence)
    }
    for candidate in final_selected_memories:
        if len(ordered_evidence_hits) >= LAYERED_EVIDENCE_LIMIT:
            break
        for evidence in list_memory_evidences(db, memory_id=candidate.id)[:1]:
            if evidence.id in evidence_hit_ids:
                continue
            evidence_hit_ids.add(evidence.id)
            ordered_evidence_hits.append(
                {
                    "evidence": evidence,
                    "score": candidate.score,
                    "snippet": evidence.quote_text,
                }
            )
            break

    profile_view_hits = [
        item
        for item in ordered_view_hits
        if item["view"].view_type == PROFILE_VIEW_TYPE
    ][:3]
    playbook_view_hits = [
        item
        for item in ordered_view_hits
        if item["view"].view_type == PLAYBOOK_VIEW_TYPE
    ][:3]
    timeline_view_hits = [
        item
        for item in ordered_view_hits
        if item["view"].view_type == TIMELINE_VIEW_TYPE
    ][:3]
    summary_view_hits = [
        item
        for item in ordered_view_hits
        if item["view"].view_type == SUMMARY_VIEW_TYPE
    ][:2]

    durable_prompt_memories = [
        candidate
        for candidate in final_selected_memories
        if not is_subject_memory(candidate.memory)
        and not is_concept_memory(candidate.memory)
        and candidate.memory.type != "temporary"
        and get_memory_kind(candidate.memory) != MEMORY_KIND_EPISODIC
        and is_active_memory(candidate.memory)
        and _memory_is_currently_valid(candidate.memory)
    ]
    timeline_prompt_memories = [
        candidate
        for candidate in final_selected_memories
        if candidate.memory.type == "temporary"
        or get_memory_kind(candidate.memory) == MEMORY_KIND_EPISODIC
        or candidate.memory.node_status != "active"
        or not _memory_is_currently_valid(candidate.memory)
    ]
    evidence_quote_by_memory_id = {
        candidate.id: _best_evidence_quote_for_memory(
            candidate.id,
            evidence_by_memory_id=evidence_by_memory_id,
        )
        for candidate in final_selected_memories
    }
    episode_ids_by_memory_id: dict[str, list[str]] = {}
    for candidate in final_selected_memories:
        evidence_items = list_memory_evidences(db, memory_id=candidate.id)[:3]
        episode_ids_by_memory_id[candidate.id] = list(
            dict.fromkeys(
                evidence.episode_id
                for evidence in evidence_items
                if isinstance(evidence.episode_id, str) and evidence.episode_id.strip()
            )
        )
    file_excerpt_by_memory_id = {
        candidate.id: _best_file_excerpt_for_memory(
            candidate.id,
            linked_file_chunks=linked_file_chunks,
        )
        for candidate in final_selected_memories
    }
    query_intent = _plan_query_intent(user_message)

    serialized_profile_views = [
        _serialize_view_hit(item["view"], score=float(item.get("score") or 0.0), snippet=str(item.get("snippet") or ""))
        for item in (profile_view_hits or summary_view_hits[:1])
    ]
    serialized_playbook_views = [
        _serialize_view_hit(item["view"], score=float(item.get("score") or 0.0), snippet=str(item.get("snippet") or ""))
        for item in playbook_view_hits
    ]
    serialized_timeline_views = [
        _serialize_view_hit(item["view"], score=float(item.get("score") or 0.0), snippet=str(item.get("snippet") or ""))
        for item in timeline_view_hits
    ]
    serialized_evidence_hits = [
        _serialize_evidence_hit(
            item["evidence"],
            score=float(item.get("score") or 0.0),
            snippet=str(item.get("snippet") or ""),
            why_selected=_evidence_selection_reason(item["evidence"]),
            supporting_memory_id=str(item.get("supporting_memory_id") or item["evidence"].memory_id or "").strip() or None,
        )
        for item in ordered_evidence_hits[:LAYERED_EVIDENCE_LIMIT]
        if isinstance(item.get("evidence"), MemoryEvidence)
    ]
    prompt_concepts = _select_best_candidates(
        [
            *active_concepts,
            *[
                candidate
                for candidate in graph_selected
                if is_concept_memory(candidate.memory)
            ],
            *[
                candidate
                for candidate in final_selected_memories
                if is_concept_memory(candidate.memory)
            ],
        ],
        limit=4,
    )

    prompt = _build_graph_guided_system_prompt(
        personality=personality,
        active_subjects=active_subjects,
        active_concepts=prompt_concepts,
        relevant_memories=durable_prompt_memories[: RELEVANT_MEMORY_LIMIT + 4],
        temporary_memories=timeline_prompt_memories[:TEMPORARY_MEMORY_LIMIT],
        profile_views=serialized_profile_views,
        playbook_views=serialized_playbook_views,
        timeline_views=serialized_timeline_views,
        raw_evidences=serialized_evidence_hits,
        knowledge_chunks=knowledge_chunks,
        linked_file_chunks=linked_file_chunks,
        recent_messages=recent_messages if include_recent_history else None,
    )

    serialized_selected_memories = [
        _serialize_memory_candidate(
            candidate,
            why_selected=_memory_selection_reason(candidate),
            supporting_quote=evidence_quote_by_memory_id.get(candidate.id) or None,
            supporting_file_excerpt=file_excerpt_by_memory_id.get(candidate.id) or None,
            supporting_memory_id=candidate.id,
            episode_ids=episode_ids_by_memory_id.get(candidate.id, []),
        )
        for candidate in final_selected_memories
    ]
    serialized_view_hits = [
        _serialize_view_hit(
            item["view"],
            score=float(item.get("score") or 0.0),
            snippet=str(item.get("snippet") or ""),
            why_selected=_view_selection_reason(item["view"]),
            supporting_memory_id=str(item.get("supporting_memory_id") or "").strip() or None,
            supporting_quote=(
                _best_evidence_quote_for_memory(
                    str(item.get("supporting_memory_id") or "").strip(),
                    evidence_by_memory_id=evidence_by_memory_id,
                )
                if str(item.get("supporting_memory_id") or "").strip()
                else None
            ),
        )
        for item in ordered_view_hits[:LAYERED_VIEW_LIMIT]
        if isinstance(item.get("view"), MemoryView)
    ]
    retrieval_trace = {
        "strategy": "layered_memory_v2",
        "query_intent": query_intent,
        "graph_first": context_level in {"memory_only", "full_rag"},
        "preflight_steps": preflight.preflight_steps,
        "selected_edge_types": preflight.selected_edge_types,
        "active_route": context_level,
        "interaction_mode": "layered_memory" if (active_subjects or active_concepts or serialized_selected_memories or serialized_view_hits) else "direct",
        "context_level": context_level,
        "primary_subject_id": primary_subject.id if primary_subject else None,
        "primary_subject_kind": get_subject_kind(primary_subject) if primary_subject else None,
        "active_subject_ids": [candidate.id for candidate in active_subjects],
        "active_concept_ids": [candidate.id for candidate in active_concepts],
        "active_fact_ids": [candidate.id for candidate in relevant_selected if is_fact_memory(candidate.memory)],
        "primary_fact_ids_by_lineage": preflight.primary_fact_ids_by_lineage,
        "explanation_path": explanation_path_summary,
        "has_conflict": preflight.has_conflict,
        "conflict_memory_ids": preflight.conflict_memory_ids,
        "memory_counts": {
            "active_subjects": len(active_subjects),
            "active_concepts": len(active_concepts),
            "static": len(static_selected),
            "relevant": len(relevant_selected),
            "graph": len(graph_selected),
            "temporary": len(temporary_selected),
        },
        "layer_hits": {
            "profile": len(serialized_profile_views),
            "durable_facts": len(durable_prompt_memories),
            "playbooks": len(serialized_playbook_views),
            "episodic_timeline": len(timeline_prompt_memories) + len(serialized_timeline_views),
            "raw_evidence": len(serialized_evidence_hits),
        },
        "view_hits": serialized_view_hits,
        "evidence_hits": serialized_evidence_hits,
        "rerank_latency_ms": rerank_latency_ms,
        "policy_flags": policy_flags,
        "used_playbook_ids": [item["id"] for item in serialized_playbook_views],
        "conflicted_memory_ids": preflight.conflict_memory_ids,
        "episode_ids": list(
            dict.fromkeys(
                episode_id
                for item in serialized_evidence_hits
                for episode_id in [item.get("episode_id")]
                if isinstance(episode_id, str) and episode_id.strip()
            )
        ),
        "suppressed_memory_ids": suppressed_memory_ids,
        "selected_memories": serialized_selected_memories,
        "active_subjects": [
            {
                **_serialize_memory_candidate(
                    candidate,
                    why_selected=_memory_selection_reason(candidate),
                    supporting_quote=_best_evidence_quote_for_memory(
                        candidate.id,
                        evidence_by_memory_id=evidence_by_memory_id,
                    )
                    or None,
                    supporting_file_excerpt=_best_file_excerpt_for_memory(
                        candidate.id,
                        linked_file_chunks=linked_file_chunks,
                    )
                    or None,
                    supporting_memory_id=candidate.id,
                ),
                "subject_kind": get_subject_kind(candidate.memory),
                "label": _subject_label(candidate.memory),
            }
            for candidate in active_subjects
        ],
        "active_concepts": [
            _serialize_memory_candidate(
                candidate,
                why_selected=_memory_selection_reason(candidate),
                supporting_quote=_best_evidence_quote_for_memory(
                    candidate.id,
                    evidence_by_memory_id=evidence_by_memory_id,
                )
                or None,
                supporting_file_excerpt=_best_file_excerpt_for_memory(
                    candidate.id,
                    linked_file_chunks=linked_file_chunks,
                )
                or None,
                supporting_memory_id=candidate.id,
            )
            for candidate in active_concepts
        ],
        "memories": serialized_selected_memories,
        "knowledge_chunks": [_serialize_chunk(chunk) for chunk in knowledge_chunks],
        "linked_file_chunks": [
            _serialize_chunk(chunk, why_selected=_linked_file_selection_reason(chunk))
            for chunk in linked_file_chunks
        ],
    }

    return MemoryContextResult(
        project=project,
        conversation=conversation,
        selected_memories=final_selected_memories,
        knowledge_chunks=knowledge_chunks,
        linked_file_chunks=linked_file_chunks,
        system_prompt=prompt,
        retrieval_trace=retrieval_trace,
    )


def touch_retrieved_memories(
    db: Session,
    *,
    selected_memories: list[MemoryCandidate],
    used_at: datetime | None = None,
) -> None:
    timestamp = used_at or datetime.now(timezone.utc)
    seen: set[str] = set()
    for candidate in selected_memories:
        if (
            candidate.id in seen
            or is_assistant_root_memory(candidate.memory)
            or is_structural_only_memory(candidate.memory)
        ):
            continue
        seen.add(candidate.id)
        candidate.memory.metadata_json = stamp_memory_usage_metadata(
            get_memory_metadata(candidate.memory),
            source=candidate.source,
            score=candidate.semantic_score if candidate.semantic_score is not None else candidate.score,
            used_at=timestamp,
        )
        candidate.memory.updated_at = candidate.memory.updated_at or timestamp


def touch_memories_from_trace(
    db: Session,
    *,
    retrieval_trace: dict[str, Any] | None,
    used_at: datetime | None = None,
) -> None:
    if not isinstance(retrieval_trace, dict):
        return
    memory_entries = retrieval_trace.get("memories")
    if not isinstance(memory_entries, list):
        return

    entry_by_id: dict[str, dict[str, Any]] = {}
    for entry in memory_entries:
        if not isinstance(entry, dict):
            continue
        memory_id = entry.get("id")
        if isinstance(memory_id, str) and memory_id:
            entry_by_id[memory_id] = entry
    if not entry_by_id:
        return

    timestamp = used_at or datetime.now(timezone.utc)
    memories = db.query(Memory).filter(Memory.id.in_(list(entry_by_id))).all()
    for memory in memories:
        if is_structural_only_memory(memory):
            continue
        entry = entry_by_id.get(memory.id) or {}
        score = entry.get("semantic_score")
        if not isinstance(score, (int, float)):
            score = entry.get("score")
        memory.metadata_json = stamp_memory_usage_metadata(
            get_memory_metadata(memory),
            source=str(entry.get("source") or "context"),
            score=float(score) if isinstance(score, (int, float)) else None,
            used_at=timestamp,
        )


async def retrieve_memory_candidates_v2(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    conversation_id: str,
    conversation_created_by: str | None,
    query: str,
    top_k: int,
    semantic_search_fn: SemanticSearchFn = search_similar,
) -> list[MemoryCandidate]:
    permanent_memories, temporary_memories = _load_visible_memories(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_id=conversation_id,
        conversation_created_by=conversation_created_by,
    )
    visible_memories_by_id = {
        memory.id: memory for memory in [*permanent_memories, *temporary_memories]
    }
    query_tokens = _normalize_query_tokens(query)
    candidates: list[MemoryCandidate] = []
    try:
        results = await semantic_search_fn(
            db,
            workspace_id=workspace_id,
            project_id=project_id,
            query=query,
            limit=max(12, top_k * 3),
        )
    except Exception:
        results = []

    for result in results:
        memory_id = result.get("memory_id")
        if not memory_id:
            continue
        memory = visible_memories_by_id.get(memory_id)
        if not memory:
            continue
        if is_structural_only_memory(memory):
            continue
        semantic_score = float(result.get("score") or 0.0)
        candidates.append(
            MemoryCandidate(
                memory=memory,
                source="semantic",
                semantic_score=semantic_score,
                score=_candidate_score(memory, source="semantic", semantic_score=semantic_score),
            )
        )

    if not candidates:
        candidates = [
            MemoryCandidate(
                memory=memory,
                source="lexical",
                semantic_score=1.0,
                score=_candidate_score(memory, source="lexical", semantic_score=1.0),
            )
            for memory in [*permanent_memories, *temporary_memories]
            if not is_structural_only_memory(memory) and _memory_matches_query(memory, query_tokens)
        ]

    return _select_primary_lineage_candidates(
        candidates,
        limit=top_k,
        allow_conflicts=_query_requests_conflict_expansion(query),
    )


def _hits_from_retrieval_trace(trace: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(trace, dict):
        return []

    hits: list[dict[str, Any]] = []
    for entry in trace.get("selected_memories") or []:
        if not isinstance(entry, dict):
            continue
        memory_id = str(entry.get("id") or "").strip()
        if not memory_id:
            continue
        hits.append(
            {
                "result_type": "memory",
                "id": memory_id,
                "memory_id": memory_id,
                "type": entry.get("type"),
                "node_type": entry.get("node_type"),
                "category": entry.get("category"),
                "memory_kind": entry.get("memory_kind"),
                "source": entry.get("source"),
                "score": float(entry.get("score") or 0.0),
                "selection_reason": str(entry.get("selection_reason") or entry.get("why_selected") or "").strip() or None,
                "suppression_reason": str(entry.get("suppression_reason") or "").strip() or None,
                "outcome_weight": float(entry.get("outcome_weight") or 1.0),
                "episode_id": (
                    str((entry.get("episode_ids") or [None])[0] or "").strip() or None
                    if isinstance(entry.get("episode_ids"), list)
                    else None
                ),
                "snippet": str(
                    entry.get("supporting_quote")
                    or entry.get("supporting_file_excerpt")
                    or entry.get("content")
                    or ""
                ),
                "content": str(entry.get("content") or ""),
                "supporting_memory_id": str(entry.get("supporting_memory_id") or memory_id).strip() or memory_id,
            }
        )

    for entry in trace.get("view_hits") or []:
        if not isinstance(entry, dict):
            continue
        view_id = str(entry.get("id") or "").strip()
        if not view_id:
            continue
        supporting_memory_id = str(entry.get("supporting_memory_id") or "").strip() or None
        hits.append(
            {
                "result_type": "view",
                "view_id": view_id,
                "score": float(entry.get("score") or 0.0),
                "selection_reason": str(entry.get("selection_reason") or entry.get("why_selected") or "").strip() or None,
                "suppression_reason": str(entry.get("suppression_reason") or "").strip() or None,
                "outcome_weight": float(entry.get("outcome_weight") or 1.0),
                "snippet": str(entry.get("snippet") or entry.get("content") or ""),
                "source_subject_id": str(entry.get("source_subject_id") or "").strip() or None,
                "supporting_memory_id": supporting_memory_id,
            }
        )

    for entry in trace.get("evidence_hits") or []:
        if not isinstance(entry, dict):
            continue
        evidence_id = str(entry.get("id") or "").strip()
        if not evidence_id:
            continue
        memory_id = str(entry.get("memory_id") or "").strip() or None
        supporting_memory_id = str(entry.get("supporting_memory_id") or memory_id or "").strip() or None
        hits.append(
            {
                "result_type": "evidence",
                "evidence_id": evidence_id,
                "memory_id": memory_id,
                "score": float(entry.get("score") or 0.0),
                "selection_reason": str(entry.get("selection_reason") or entry.get("why_selected") or "").strip() or None,
                "outcome_weight": float(entry.get("outcome_weight") or 1.0),
                "episode_id": str(entry.get("episode_id") or "").strip() or None,
                "snippet": str(entry.get("snippet") or entry.get("quote_text") or ""),
                "supporting_memory_id": supporting_memory_id,
            }
        )

    hits.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
    return hits


async def _search_project_memory_hits_without_conversation(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    conversation_created_by: str | None,
    query: str,
    top_k: int,
    semantic_search_fn: SemanticSearchFn,
) -> list[dict[str, Any]]:
    allow_conflicts = _query_requests_conflict_expansion(query)
    profile_priority = _query_prefers_profile_views(query)
    playbook_priority = _query_prefers_playbook_views(query)
    timeline_requested = _query_requests_timeline(query)
    permanent_memories, temporary_memories = _load_visible_memories(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_id="",
        conversation_created_by=conversation_created_by,
        include_inactive=timeline_requested,
    )
    visible_memories_by_id = {
        memory.id: memory
        for memory in [*permanent_memories, *temporary_memories]
    }
    query_tokens = _normalize_query_tokens(query)
    memory_candidate_pool: dict[str, MemoryCandidate] = {}

    def _register_memory_candidate(candidate: MemoryCandidate) -> None:
        memory = candidate.memory
        if is_structural_only_memory(memory):
            return
        if not timeline_requested and (not is_active_memory(memory) or not _memory_is_currently_valid(memory)):
            return
        current = memory_candidate_pool.get(candidate.id)
        if current is None or candidate.score > current.score:
            memory_candidate_pool[candidate.id] = candidate

    try:
        semantic_results = await semantic_search_fn(
            db,
            workspace_id=workspace_id,
            project_id=project_id,
            query=query,
            limit=max(12, top_k * 4),
        )
    except Exception:
        semantic_results = []
    for result in semantic_results:
        memory_id = str(result.get("memory_id") or "").strip()
        if not memory_id:
            continue
        memory = visible_memories_by_id.get(memory_id)
        if memory is None:
            continue
        semantic_score = float(result.get("score") or 0.0)
        _register_memory_candidate(
            MemoryCandidate(
                memory=memory,
                source="semantic",
                semantic_score=semantic_score,
                score=_candidate_score(memory, source="semantic", semantic_score=semantic_score),
            )
        )

    try:
        lexical_memory_hits = search_memories_lexical(
            db,
            workspace_id=workspace_id,
            project_id=project_id,
            query=query,
            limit=max(top_k * 2, 10),
        )
    except Exception:
        lexical_memory_hits = []
    for hit in lexical_memory_hits:
        memory = visible_memories_by_id.get(str(hit.get("memory_id") or ""))
        if memory is None:
            continue
        lexical_score = float(hit.get("score") or 0.0)
        _register_memory_candidate(
            MemoryCandidate(
                memory=memory,
                source="lexical",
                semantic_score=lexical_score,
                score=_candidate_score(memory, source="lexical", semantic_score=lexical_score),
            )
        )

    if not memory_candidate_pool:
        for memory in visible_memories_by_id.values():
            if _memory_matches_query(memory, query_tokens):
                _register_memory_candidate(
                    MemoryCandidate(
                        memory=memory,
                        source="lexical",
                        semantic_score=0.58,
                        score=_candidate_score(memory, source="lexical", semantic_score=0.58),
                    )
                )

    seed_candidates = _select_primary_lineage_candidates(
        list(memory_candidate_pool.values()),
        limit=max(4, min(max(top_k, 4), 8)),
        allow_conflicts=allow_conflicts,
    )
    for candidate in _build_graph_neighbors(
        seed_candidates=seed_candidates,
        visible_memories_by_id=visible_memories_by_id,
        query_tokens=query_tokens,
        lateral_edges=None,
    ):
        _register_memory_candidate(candidate)

    candidate_memory_ids = list(memory_candidate_pool)
    evidence_by_memory_id: dict[str, MemoryEvidence] = {}
    if candidate_memory_ids:
        for evidence in (
            db.query(MemoryEvidence)
            .filter(MemoryEvidence.memory_id.in_(candidate_memory_ids))
            .order_by(MemoryEvidence.created_at.desc())
            .all()
        ):
            if evidence.memory_id not in evidence_by_memory_id and str(evidence.quote_text or "").strip():
                evidence_by_memory_id[evidence.memory_id] = evidence

    candidate_subject_ids = list(
        dict.fromkeys(
            [
                candidate.id
                for candidate in memory_candidate_pool.values()
                if is_subject_memory(candidate.memory)
            ]
            + [
                subject_id
                for subject_id in [
                    get_subject_memory_id(candidate.memory)
                    for candidate in memory_candidate_pool.values()
                ]
                if isinstance(subject_id, str) and subject_id.strip()
            ]
        )
    )
    view_pool: dict[str, dict[str, Any]] = {}

    def _register_view(view: MemoryView, *, score: float, snippet: str | None = None) -> None:
        if not _view_visible_to_conversation(view, conversation_created_by=conversation_created_by):
            return
        current = view_pool.get(view.id)
        if current is None or score > float(current["score"]):
            view_pool[view.id] = {
                "view": view,
                "score": float(score),
                "snippet": snippet or view.content,
            }

    view_query = db.query(MemoryView).filter(
        MemoryView.project_id == project_id,
        MemoryView.workspace_id == workspace_id,
    )
    if candidate_subject_ids:
        view_query = view_query.filter(MemoryView.source_subject_id.in_(candidate_subject_ids))
    subject_views = view_query.order_by(MemoryView.updated_at.desc()).all()
    for view in subject_views:
        base_score = 0.44
        if view.view_type == PROFILE_VIEW_TYPE and profile_priority:
            base_score += 0.28
        elif view.view_type == PLAYBOOK_VIEW_TYPE and playbook_priority:
            base_score += 0.28
        elif view.view_type == TIMELINE_VIEW_TYPE and timeline_requested:
            base_score += 0.22
        elif view.view_type == SUMMARY_VIEW_TYPE:
            base_score += 0.06
        _register_view(view, score=base_score)

    try:
        lexical_view_hits = search_memory_views_lexical(
            db,
            workspace_id=workspace_id,
            project_id=project_id,
            query=query,
            limit=max(top_k * 2, 10),
            subject_ids=candidate_subject_ids or None,
        )
    except Exception:
        lexical_view_hits = []
    subject_views_by_id = {view.id: view for view in subject_views}
    for hit in lexical_view_hits:
        view = subject_views_by_id.get(str(hit.get("view_id") or ""))
        if view is None:
            continue
        lexical_score = 0.5 + float(hit.get("score") or 0.0)
        if view.view_type == PROFILE_VIEW_TYPE and profile_priority:
            lexical_score += 0.12
        if view.view_type == PLAYBOOK_VIEW_TYPE and playbook_priority:
            lexical_score += 0.12
        if view.view_type == TIMELINE_VIEW_TYPE and timeline_requested:
            lexical_score += 0.08
        _register_view(view, score=lexical_score, snippet=str(hit.get("snippet") or view.content))

    evidence_pool: dict[str, dict[str, Any]] = {}
    try:
        lexical_evidence_hits = search_memory_evidences_lexical(
            db,
            workspace_id=workspace_id,
            project_id=project_id,
            query=query,
            limit=max(top_k * 2, 10),
        )
    except Exception:
        lexical_evidence_hits = []
    for hit in lexical_evidence_hits:
        memory = visible_memories_by_id.get(str(hit.get("memory_id") or ""))
        if memory is None:
            continue
        if not timeline_requested and (not is_active_memory(memory) or not _memory_is_currently_valid(memory)):
            continue
        evidence = db.get(MemoryEvidence, str(hit.get("evidence_id") or ""))
        if evidence is None:
            continue
        base_score = 0.42 + float(hit.get("score") or 0.0)
        current = evidence_pool.get(evidence.id)
        if current is None or base_score > float(current["score"]):
            evidence_pool[evidence.id] = {
                "evidence": evidence,
                "score": base_score,
                "snippet": str(hit.get("snippet") or evidence.quote_text),
            }

    candidate_registry: dict[str, dict[str, Any]] = {}

    def _register_candidate_doc(
        *,
        key: str,
        result_type: str,
        base_score: float,
        text: str,
        snippet: str,
        candidate: MemoryCandidate | None = None,
        view: MemoryView | None = None,
        evidence: MemoryEvidence | None = None,
        supporting_memory_id: str | None = None,
    ) -> None:
        current = candidate_registry.get(key)
        if current is None or base_score > float(current["base_score"]):
            candidate_registry[key] = {
                "key": key,
                "result_type": result_type,
                "base_score": float(base_score),
                "text": text,
                "snippet": snippet,
                "candidate": candidate,
                "view": view,
                "evidence": evidence,
                "supporting_memory_id": supporting_memory_id,
            }

    for candidate in memory_candidate_pool.values():
        memory = candidate.memory
        subject_memory = visible_memories_by_id.get(get_subject_memory_id(memory) or "")
        evidence_quote = _best_evidence_quote_for_memory(
            memory.id,
            evidence_by_memory_id=evidence_by_memory_id,
        )
        kind = get_memory_kind(memory)
        layer_bias = 0.0
        if profile_priority and kind in {MEMORY_KIND_PROFILE, MEMORY_KIND_PREFERENCE, MEMORY_KIND_GOAL}:
            layer_bias += 0.14
        if timeline_requested and (
            memory.type == "temporary"
            or kind == MEMORY_KIND_EPISODIC
            or memory.node_status != "active"
        ):
            layer_bias += 0.1
        _register_candidate_doc(
            key=f"memory:{memory.id}",
            result_type="memory",
            base_score=float(candidate.score) + layer_bias,
            text="\n".join(
                part
                for part in (
                    f"Subject: {_subject_label(subject_memory)}" if subject_memory else "",
                    f"Category: {memory.category}" if memory.category else "",
                    f"Memory: {memory.content}",
                    f"Evidence: {evidence_quote}" if evidence_quote else "",
                )
                if part
            ),
            snippet=evidence_quote or memory.content,
            candidate=candidate,
            supporting_memory_id=memory.id,
        )

    for payload in view_pool.values():
        view = payload["view"]
        supporting_memory_id = None
        metadata = view.metadata_json if isinstance(view.metadata_json, dict) else {}
        source_memory_ids = metadata.get("source_memory_ids")
        if isinstance(source_memory_ids, list):
            supporting_memory_id = next(
                (
                    str(item).strip()
                    for item in source_memory_ids
                    if isinstance(item, str) and str(item).strip()
                ),
                None,
            )
        if supporting_memory_id is None:
            supporting_memory_id = str(view.source_subject_id or "").strip() or None
        subject_memory = visible_memories_by_id.get(str(view.source_subject_id or ""))
        evidence_quote = (
            _best_evidence_quote_for_memory(
                supporting_memory_id,
                evidence_by_memory_id=evidence_by_memory_id,
            )
            if supporting_memory_id
            else ""
        )
        _register_candidate_doc(
            key=f"view:{view.id}",
            result_type="view",
            base_score=float(payload["score"]),
            text="\n".join(
                part
                for part in (
                    f"Subject: {_subject_label(subject_memory)}" if subject_memory else "",
                    f"View Type: {view.view_type}",
                    f"View: {view.content}",
                    f"Evidence: {evidence_quote}" if evidence_quote else "",
                )
                if part
            ),
            snippet=str(payload["snippet"] or view.content),
            view=view,
            supporting_memory_id=supporting_memory_id,
        )

    for payload in evidence_pool.values():
        evidence = payload["evidence"]
        memory = visible_memories_by_id.get(evidence.memory_id)
        if memory is None:
            continue
        subject_memory = visible_memories_by_id.get(get_subject_memory_id(memory) or "")
        _register_candidate_doc(
            key=f"evidence:{evidence.id}",
            result_type="evidence",
            base_score=float(payload["score"]),
            text="\n".join(
                part
                for part in (
                    f"Subject: {_subject_label(subject_memory)}" if subject_memory else "",
                    f"Category: {memory.category}" if memory.category else "",
                    f"Memory: {memory.content}",
                    f"Evidence: {evidence.quote_text}",
                )
                if part
            ),
            snippet=str(payload["snippet"] or evidence.quote_text),
            evidence=evidence,
            supporting_memory_id=evidence.memory_id,
        )

    if not candidate_registry:
        return []

    candidate_docs = sorted(
        candidate_registry.values(),
        key=lambda item: float(item["base_score"]),
        reverse=True,
    )[:LAYERED_RERANK_LIMIT]
    rerank_input = [
        RerankDocument(
            key=str(item["key"]),
            text=str(item["text"]),
            score=float(item["base_score"]),
        )
        for item in candidate_docs
    ]
    try:
        reranked_docs = await rerank_documents(query, rerank_input)
    except Exception:
        reranked_docs = rerank_input

    reranked_items: list[dict[str, Any]] = []
    for document in reranked_docs:
        item = candidate_registry.get(document.key)
        if item is None:
            continue
        reranked_items.append(
            {
                **item,
                "score": float(document.score),
            }
        )

    memory_hits: list[dict[str, Any]] = []
    selected_lineage_keys: set[str] = set()
    for item in reranked_items:
        if item.get("result_type") != "memory":
            continue
        candidate = item.get("candidate")
        if not isinstance(candidate, MemoryCandidate):
            continue
        memory = candidate.memory
        if not allow_conflicts and is_fact_memory(memory):
            lineage_key = _lineage_bucket_id(memory)
            if lineage_key in selected_lineage_keys:
                continue
            selected_lineage_keys.add(lineage_key)
        memory_hits.append(
            {
                "result_type": "memory",
                "id": memory.id,
                "memory_id": memory.id,
                "type": memory.type,
                "node_type": memory.node_type,
                "category": memory.category,
                "memory_kind": get_memory_kind(memory),
                "source": candidate.source,
                "score": round(float(item.get("score") or candidate.score), 4),
                "snippet": str(item.get("snippet") or memory.content),
                "content": shorten_text(memory.content, limit=600),
                "supporting_memory_id": memory.id,
            }
        )
        if len(memory_hits) >= max(top_k, LAYERED_MEMORY_LIMIT):
            break

    view_hits = [
        {
            "result_type": "view",
            "view_id": item["view"].id,
            "score": round(float(item.get("score") or 0.0), 4),
            "snippet": str(item.get("snippet") or item["view"].content),
            "source_subject_id": str(item["view"].source_subject_id or "").strip() or None,
            "supporting_memory_id": str(item.get("supporting_memory_id") or "").strip() or None,
        }
        for item in reranked_items
        if item.get("result_type") == "view" and isinstance(item.get("view"), MemoryView)
    ][:LAYERED_VIEW_LIMIT]
    evidence_hits = [
        {
            "result_type": "evidence",
            "evidence_id": item["evidence"].id,
            "memory_id": item["evidence"].memory_id,
            "score": round(float(item.get("score") or 0.0), 4),
            "snippet": str(item.get("snippet") or item["evidence"].quote_text),
            "supporting_memory_id": str(item.get("supporting_memory_id") or item["evidence"].memory_id or "").strip() or None,
        }
        for item in reranked_items
        if item.get("result_type") == "evidence" and isinstance(item.get("evidence"), MemoryEvidence)
    ][:LAYERED_EVIDENCE_LIMIT]

    hits = [*memory_hits, *view_hits, *evidence_hits]
    hits.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
    return hits[:top_k]


async def search_project_memory_hits_v2(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    conversation_id: str | None,
    conversation_created_by: str | None,
    query: str,
    top_k: int,
    semantic_search_fn: SemanticSearchFn = search_similar,
) -> list[dict[str, Any]]:
    normalized_conversation_id = str(conversation_id or "").strip()
    if normalized_conversation_id:
        try:
            context = await build_memory_context(
                db,
                workspace_id=workspace_id,
                project_id=project_id,
                conversation_id=normalized_conversation_id,
                user_message=query,
                recent_messages=[],
                personality="",
                context_level="memory_only",
                include_recent_history=False,
                semantic_search_fn=semantic_search_fn,
            )
            hits = _hits_from_retrieval_trace(context.retrieval_trace)
            if hits:
                return hits[:top_k]
        except Exception:
            pass
    return await _search_project_memory_hits_without_conversation(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_created_by=conversation_created_by,
        query=query,
        top_k=top_k,
        semantic_search_fn=semantic_search_fn,
    )


async def explain_project_memory_hits_v2(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    conversation_id: str | None,
    conversation_created_by: str | None,
    query: str,
    top_k: int,
    semantic_search_fn: SemanticSearchFn = search_similar,
) -> dict[str, Any]:
    normalized_conversation_id = str(conversation_id or "").strip()
    if normalized_conversation_id:
        try:
            context = await build_memory_context(
                db,
                workspace_id=workspace_id,
                project_id=project_id,
                conversation_id=normalized_conversation_id,
                user_message=query,
                recent_messages=[],
                personality="",
                context_level="memory_only",
                include_recent_history=False,
                semantic_search_fn=semantic_search_fn,
            )
            hits = _hits_from_retrieval_trace(context.retrieval_trace)
            return {
                "hits": hits[:top_k],
                "trace": context.retrieval_trace,
            }
        except Exception:
            pass

    hits = await _search_project_memory_hits_without_conversation(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_created_by=conversation_created_by,
        query=query,
        top_k=top_k,
        semantic_search_fn=semantic_search_fn,
    )
    result_hits = hits[:top_k]
    memory_count = len([item for item in result_hits if item.get("result_type") == "memory"])
    view_count = len([item for item in result_hits if item.get("result_type") == "view"])
    evidence_count = len([item for item in result_hits if item.get("result_type") == "evidence"])
    trace = {
        "strategy": "layered_memory_v2",
        "query_intent": _plan_query_intent(query),
        "context_level": "memory_only",
        "layer_hits": {
            "profile": 0,
            "durable_facts": memory_count,
            "playbooks": view_count,
            "episodic_timeline": 0,
            "raw_evidence": evidence_count,
        },
        "used_playbook_ids": [
            str(item.get("view_id") or "").strip()
            for item in result_hits
            if item.get("result_type") == "view" and str(item.get("view_id") or "").strip()
        ],
        "conflicted_memory_ids": [],
        "episode_ids": list(
            dict.fromkeys(
                str(item.get("episode_id") or "").strip()
                for item in result_hits
                if str(item.get("episode_id") or "").strip()
            )
        ),
        "suppressed_memory_ids": [],
        "selected_memories": [],
        "view_hits": [],
        "evidence_hits": [],
        "policy_flags": [],
    }
    return {
        "hits": result_hits,
        "trace": trace,
    }


async def search_project_memories_for_tool(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    conversation_id: str | None,
    conversation_created_by: str | None,
    query: str,
    top_k: int,
    semantic_search_fn: SemanticSearchFn = search_similar,
) -> list[dict[str, Any]]:
    selected = await search_project_memory_hits_v2(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_id=conversation_id,
        conversation_created_by=conversation_created_by,
        query=query,
        top_k=max(top_k * 3, 12),
        semantic_search_fn=semantic_search_fn,
    )
    return [
        {
            "id": result["memory_id"],
            "type": result.get("type"),
            "category": result.get("category"),
            "memory_kind": result.get("memory_kind"),
            "score": float(result.get("score") or 0.0),
            "source": result.get("source"),
            "content": str(result.get("content") or result.get("snippet") or ""),
        }
        for result in selected
        if (
            result.get("result_type") == "memory"
            and result.get("memory_id")
            and result.get("node_type") not in {"subject", "concept", "root"}
        )
    ][:top_k]
