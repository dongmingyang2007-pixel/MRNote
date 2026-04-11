from __future__ import annotations

from dataclasses import asdict, dataclass
import re

from sqlalchemy import or_, text as sql_text
from sqlalchemy.orm import Session

from app.models import Memory, MemoryEdge, MemoryFile, Project
from app.services.memory_metadata import (
    ACTIVE_NODE_STATUS,
    CONCEPT_NODE_KIND,
    MEMORY_KIND_FACT,
    MEMORY_KIND_GOAL,
    MEMORY_KIND_PREFERENCE,
    clear_manual_parent_binding,
    get_memory_kind,
    get_memory_metadata,
    get_subject_kind,
    has_manual_parent_binding,
    is_category_path_memory,
    is_concept_memory,
    is_fact_memory,
    is_pinned_memory,
    is_subject_memory,
    is_summary_memory,
    normalize_memory_metadata,
)
from app.services.memory_roots import ensure_project_assistant_root, is_assistant_root_memory
from app.services.memory_visibility import build_private_memory_metadata, get_memory_owner_user_id, is_private_memory
from app.services.memory_versioning import VERSION_EDGE_TYPES

AUTO_EDGE_TYPE = "auto"
REPAIR_MUTABLE_EDGE_TYPES = frozenset({AUTO_EDGE_TYPE})
PROTECTED_VERSION_EDGE_TYPES = frozenset(VERSION_EDGE_TYPES)


@dataclass(slots=True)
class MemoryGraphRepairSummary:
    deleted_aggregate_nodes: int = 0
    deleted_legacy_nodes: int = 0
    created_concept_nodes: int = 0
    deleted_duplicate_concepts: int = 0
    reparented_nodes: int = 0
    deleted_auto_edges: int = 0
    created_auto_edges: int = 0
    skipped_nodes: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


def _normalize_text_key(value: str) -> str:
    normalized = re.sub(r"\s+", "", str(value or "").strip().lower())
    return re.sub(r"[，。、“”‘’\"'`()（）,.!?！？:：;；\-_/\\]+", "", normalized)


def _normalize_category_segments(category: str) -> list[str]:
    return [
        segment.strip().lower()
        for segment in str(category or "").split(".")
        if segment.strip()
    ]


def _shared_category_prefix_length(left: str, right: str) -> int:
    shared = 0
    for left_segment, right_segment in zip(
        _normalize_category_segments(left),
        _normalize_category_segments(right),
        strict=False,
    ):
        if left_segment != right_segment:
            break
        shared += 1
    return shared


def _is_structural_parent_memory(memory: Memory | None) -> bool:
    return memory is not None and (
        is_assistant_root_memory(memory)
        or is_subject_memory(memory)
        or is_concept_memory(memory)
    )


def _is_auto_managed_memory(memory: Memory) -> bool:
    metadata = get_memory_metadata(memory)
    return bool(
        metadata.get("auto_generated")
        or metadata.get("source") == "auto_extraction"
        or metadata.get("promoted_by")
    )


def _is_aggregate_leaf_memory(memory: Memory) -> bool:
    if is_assistant_root_memory(memory) or is_subject_memory(memory) or is_concept_memory(memory) or is_summary_memory(memory):
        return False
    normalized = re.sub(r"\s+", "", memory.content.strip())
    if not normalized:
        return False
    memory_kind = get_memory_kind(memory)
    if memory_kind not in {MEMORY_KIND_PREFERENCE, MEMORY_KIND_GOAL} and "偏好" not in memory.category:
        return False
    if not any(separator in normalized for separator in ("、", "和", "以及", "及", "，", ",")):
        return False
    return bool(
        re.match(
            r"^用户(?:偏好|喜欢|喜爱|爱喝|爱吃|热爱|计划|打算|准备|想要)[^。！？!?]*[、和及以及，,][^。！？!?]*[。！？!?]?$",
            normalized,
        )
    )


def _score_concept_parent(candidate: Memory, memory: Memory) -> float:
    if memory.subject_memory_id and candidate.subject_memory_id != memory.subject_memory_id:
        return 0.0
    score = 0.0
    shared_prefix = _shared_category_prefix_length(candidate.category, memory.category)
    score += shared_prefix * 0.35
    candidate_topic = _get_concept_topic_for_matching(candidate)
    if candidate_topic:
        topic_key = _normalize_text_key(candidate_topic)
        if topic_key and topic_key in _normalize_text_key(memory.content + memory.category):
            score += 0.45
    if get_memory_kind(candidate) == get_memory_kind(memory):
        score += 0.12
    if candidate.parent_memory_id:
        score += 0.03
    return score


_FACT_CONCEPT_TOPIC_HINTS: tuple[tuple[str, str], ...] = (
    ("人设", "设定"),
    ("设定", "设定"),
    ("世界观", "设定"),
    ("定位", "设定"),
    ("背景", "背景"),
    ("来历", "背景"),
    ("出身", "背景"),
    ("历史", "背景"),
    ("经历", "经历"),
    ("剧情", "经历"),
    ("故事", "经历"),
    ("事件", "经历"),
    ("过去", "经历"),
    ("能力", "能力"),
    ("技能", "能力"),
    ("招式", "能力"),
    ("术式", "能力"),
    ("武器", "能力"),
    ("关系", "关系"),
    ("互动", "关系"),
    ("对手", "关系"),
    ("朋友", "关系"),
    ("搭档", "关系"),
    ("身份", "身份"),
    ("种族", "身份"),
    ("职业", "身份"),
    ("头衔", "身份"),
    ("称号", "身份"),
    ("职位", "身份"),
    ("性格", "特征"),
    ("特点", "特征"),
    ("辨识度", "特征"),
    ("风格", "特征"),
    ("外观", "特征"),
    ("形象", "特征"),
    ("气质", "特征"),
    ("特征", "特征"),
)

_USER_FACT_CONCEPT_TOPIC_HINTS: tuple[tuple[str, str], ...] = (
    ("education", "教育"),
    ("study", "教育"),
    ("school", "教育"),
    ("学业", "教育"),
    ("教育", "教育"),
    ("identity", "身份"),
    ("身份", "身份"),
    ("profile", "个人"),
    ("personal", "个人"),
    ("个人", "个人"),
    ("work", "工作"),
    ("job", "工作"),
    ("career", "工作"),
    ("profession", "工作"),
    ("职业", "工作"),
    ("工作", "工作"),
    ("travel", "旅行"),
    ("trip", "旅行"),
    ("旅行", "旅行"),
    ("location", "地点"),
    ("place", "地点"),
    ("residence", "地点"),
    ("居住", "地点"),
    ("地点", "地点"),
    ("relationship", "关系"),
    ("关系", "关系"),
    ("food", "饮食"),
    ("drink", "饮食"),
    ("diet", "饮食"),
    ("饮食", "饮食"),
    ("学习", "学习"),
    ("learning", "学习"),
    ("health", "健康"),
    ("健康", "健康"),
)

_USER_FACT_CONCEPT_TOPIC_SKIP_KEYS = {
    "user",
    "custom",
    "fact",
    "事实",
    "记忆",
    "memory",
}

_USER_FACT_CONCEPT_LABELS: dict[str, str] = {
    "教育": "教育背景",
    "身份": "身份信息",
    "个人": "个人信息",
    "工作": "工作经历",
    "地点": "地点经历",
    "关系": "关系网络",
    "饮食": "饮食习惯",
    "学习": "学习轨迹",
    "健康": "健康情况",
    "旅行": "旅行经历",
}

_PERSON_FACT_CONCEPT_LABELS: dict[str, str] = {
    "设定": "角色设定",
    "背景": "角色背景",
    "经历": "经历事件",
    "能力": "能力体系",
    "关系": "关系网络",
    "身份": "身份定位",
    "特征": "形象特征",
}

_GENERIC_FACT_CONCEPT_LABELS: dict[str, str] = {
    "设定": "核心设定",
    "背景": "背景信息",
    "经历": "相关经历",
    "能力": "能力体系",
    "关系": "关联关系",
    "身份": "身份定位",
    "特征": "关键特征",
}

_PERSON_LIKE_CATEGORY_HINTS = {
    "人物",
    "角色",
    "角色设定",
    "人物设定",
}


def _sanitize_concept_topic(topic: str) -> str:
    cleaned = re.sub(r"\s+", "", str(topic or "").strip())
    cleaned = cleaned.strip("，。、“”‘’\"'`()（）[]【】<>《》:：;；,.!?！？")
    if not cleaned or len(cleaned) > 18:
        return ""
    if any(token in cleaned for token in ("用户", "事实", "记忆", "主题", "偏好", "目标")):
        return ""
    return cleaned


def _normalize_fact_concept_topic(topic: str) -> str:
    cleaned = _sanitize_concept_topic(topic)
    if not cleaned:
        return ""
    normalized_key = _normalize_text_key(cleaned)
    for hint, canonical in _FACT_CONCEPT_TOPIC_HINTS:
        if _normalize_text_key(hint) in normalized_key:
            return canonical
    return cleaned


def _normalize_user_fact_concept_topic(topic: str) -> str:
    cleaned = _sanitize_concept_topic(topic)
    if not cleaned:
        return ""
    normalized_key = _normalize_text_key(cleaned)
    if normalized_key in _USER_FACT_CONCEPT_TOPIC_SKIP_KEYS:
        return ""
    for hint, canonical in _USER_FACT_CONCEPT_TOPIC_HINTS:
        hint_key = _normalize_text_key(hint)
        if hint_key and (hint_key == normalized_key or hint_key in normalized_key):
            return canonical
    return cleaned


def _normalize_concept_label(label: str) -> str:
    cleaned = _sanitize_concept_topic(label)
    if not cleaned:
        return ""
    if len(cleaned) > 24:
        return ""
    return cleaned


def _is_person_like_fact_subject(*, subject: Memory, fact_category: str) -> bool:
    subject_kind = get_subject_kind(subject)
    if subject_kind == "person":
        return True
    segments = [segment.strip() for segment in str(fact_category or "").split(".") if segment.strip()]
    if segments and segments[0] in _PERSON_LIKE_CATEGORY_HINTS:
        return True
    return False


def _build_fact_concept_label(
    *,
    subject: Memory,
    topic: str,
    fact_category: str,
) -> str:
    canonical_topic = _normalize_fact_concept_topic(topic) or _normalize_user_fact_concept_topic(topic) or topic
    subject_kind = get_subject_kind(subject)
    if subject_kind == "user":
        return _USER_FACT_CONCEPT_LABELS.get(canonical_topic, f"{canonical_topic}信息")
    if _is_person_like_fact_subject(subject=subject, fact_category=fact_category):
        return _PERSON_FACT_CONCEPT_LABELS.get(canonical_topic, f"{canonical_topic}信息")
    return _GENERIC_FACT_CONCEPT_LABELS.get(canonical_topic, canonical_topic)


def _is_auto_generated_concept(memory: Memory | None) -> bool:
    if memory is None or not is_concept_memory(memory):
        return False
    metadata = get_memory_metadata(memory)
    return bool(
        metadata.get("auto_generated")
        or metadata.get("source") in {"auto_concept_parent", "repair_concept_backfill"}
    )


def _get_concept_topic_for_matching(memory: Memory | None) -> str:
    if memory is None or not is_concept_memory(memory):
        return ""
    metadata = get_memory_metadata(memory)
    explicit_topic = str(metadata.get("concept_topic") or "").strip()
    if explicit_topic:
        normalized_explicit = (
            _normalize_fact_concept_topic(explicit_topic)
            or _normalize_user_fact_concept_topic(explicit_topic)
            or _sanitize_concept_topic(explicit_topic)
        )
        if normalized_explicit:
            return normalized_explicit

    for segment in [segment.strip() for segment in str(memory.category or "").split(".") if segment.strip()]:
        normalized_segment = (
            _normalize_user_fact_concept_topic(segment)
            or _normalize_fact_concept_topic(segment)
        )
        if normalized_segment:
            return normalized_segment

    return (
        _normalize_user_fact_concept_topic(memory.content)
        or _normalize_fact_concept_topic(memory.content)
        or _sanitize_concept_topic(memory.content)
    )


def _build_concept_category(*, fact_category: str, topic: str) -> str:
    segments = [segment.strip() for segment in str(fact_category or "").split(".") if segment.strip()]
    if not topic:
        return ".".join(segments)
    if not segments:
        return topic
    topic_key = _normalize_text_key(topic)
    for index, segment in enumerate(segments):
        if _normalize_text_key(segment) == topic_key:
            return ".".join(segments[: index + 1])
    return ".".join([*segments, topic])


def _infer_backfill_concept_topic(memory: Memory, *, subject: Memory) -> str | None:
    if get_subject_kind(subject) == "user":
        raw_segments = [
            segment.strip()
            for segment in str(memory.category or "").split(".")
            if segment and segment.strip()
        ]
        for segment in raw_segments:
            topic = _normalize_user_fact_concept_topic(segment)
            if topic:
                return topic
        normalized_content = re.sub(r"\s+", "", memory.content.strip())
        if not normalized_content:
            return None
        for hint, canonical in _USER_FACT_CONCEPT_TOPIC_HINTS:
            if hint in normalized_content:
                return canonical
        return None
    for segment in reversed(_normalize_category_segments(memory.category)):
        topic = _normalize_fact_concept_topic(segment)
        if topic:
            return topic
    normalized_content = re.sub(r"\s+", "", memory.content.strip())
    if not normalized_content:
        return None
    for hint, canonical in _FACT_CONCEPT_TOPIC_HINTS:
        if hint in normalized_content:
            return canonical
    return None


def _find_existing_backfill_concept(
    *,
    memories_by_id: dict[str, Memory],
    subject_id: str,
    excluded_memory_id: str | None,
    topic: str,
    label: str,
    parent_category: str,
    fact_memory_kind: str,
) -> Memory | None:
    topic_key = _normalize_text_key(topic)
    if not topic_key:
        return None
    label_key = _normalize_text_key(label)
    best_match: Memory | None = None
    best_score = -1
    for candidate in memories_by_id.values():
        if excluded_memory_id and candidate.id == excluded_memory_id:
            continue
        if not is_concept_memory(candidate):
            continue
        if candidate.subject_memory_id != subject_id:
            continue
        if get_memory_kind(candidate) != fact_memory_kind:
            continue
        score = 0
        if label_key and _normalize_text_key(candidate.content) == label_key:
            score += 3
        if _normalize_text_key(candidate.content) == topic_key:
            score += 1
        existing_topic = _normalize_text_key(_get_concept_topic_for_matching(candidate))
        if existing_topic == topic_key:
            score += 4
        if _shared_category_prefix_length(candidate.category, parent_category) >= 1:
            score += 1
        if score > best_score:
            best_match = candidate
            best_score = score
    return best_match if best_score >= 4 else None


def _refresh_backfill_concept_parent(
    existing: Memory,
    *,
    subject: Memory,
    topic: str,
    label: str,
    parent_category: str,
) -> None:
    if not _is_auto_generated_concept(existing) or is_pinned_memory(existing):
        return

    normalized_label = _normalize_concept_label(label)
    if not normalized_label:
        return

    current_topic = _get_concept_topic_for_matching(existing)
    should_relabel = (
        _normalize_text_key(existing.content) in {
            _normalize_text_key(topic),
            _normalize_text_key(current_topic),
        }
        and _normalize_text_key(existing.content) != _normalize_text_key(normalized_label)
    )
    next_content = normalized_label if should_relabel else existing.content
    metadata: dict[str, object] = {
        **(existing.metadata_json or {}),
        "node_kind": CONCEPT_NODE_KIND,
        "node_type": CONCEPT_NODE_KIND,
        "node_status": ACTIVE_NODE_STATUS,
        "subject_kind": None,
        "subject_memory_id": subject.id,
        "concept_topic": topic,
        "concept_label": normalized_label,
        "auto_generated": True,
        "source": str((existing.metadata_json or {}).get("source") or "repair_concept_backfill"),
        "salience": float((existing.metadata_json or {}).get("salience") or 0.72),
    }
    owner_user_id = get_memory_owner_user_id(subject) or get_memory_owner_user_id(existing)
    if owner_user_id or is_private_memory(subject) or is_private_memory(existing):
        metadata = build_private_memory_metadata(metadata, owner_user_id=owner_user_id)
    metadata = normalize_memory_metadata(
        content=next_content,
        category=parent_category,
        memory_type=existing.type,
        metadata=metadata,
    )
    existing.content = next_content
    existing.category = parent_category
    existing.subject_memory_id = subject.id
    existing.parent_memory_id = subject.id
    existing.metadata_json = metadata
    existing.canonical_key = str(metadata.get("canonical_key") or "").strip() or existing.canonical_key


def _ensure_backfill_concept_parent(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    subject: Memory,
    memory: Memory,
    topic: str,
    memories_by_id: dict[str, Memory],
) -> tuple[Memory | None, bool]:
    fact_memory_kind = get_memory_kind(memory)
    label = _build_fact_concept_label(
        subject=subject,
        topic=topic,
        fact_category=memory.category,
    )
    parent_category = _build_concept_category(fact_category=memory.category, topic=topic)
    existing = _find_existing_backfill_concept(
        memories_by_id=memories_by_id,
        subject_id=subject.id,
        excluded_memory_id=memory.id,
        topic=topic,
        label=label,
        parent_category=parent_category,
        fact_memory_kind=fact_memory_kind,
    )
    if existing is not None:
        _refresh_backfill_concept_parent(
            existing,
            subject=subject,
            topic=topic,
            label=label,
            parent_category=parent_category,
        )
        return existing, False

    metadata: dict[str, object] = {
        "node_kind": CONCEPT_NODE_KIND,
        "node_type": CONCEPT_NODE_KIND,
        "node_status": ACTIVE_NODE_STATUS,
        "subject_kind": None,
        "subject_memory_id": subject.id,
        "concept_topic": topic,
        "concept_label": label,
        "auto_generated": True,
        "source": "repair_concept_backfill",
        "salience": 0.72,
    }
    owner_user_id = get_memory_owner_user_id(subject) or get_memory_owner_user_id(memory)
    if owner_user_id or is_private_memory(subject) or is_private_memory(memory):
        metadata = build_private_memory_metadata(metadata, owner_user_id=owner_user_id)
    metadata = normalize_memory_metadata(
        content=label,
        category=parent_category,
        memory_type="permanent",
        metadata=metadata,
    )

    concept_memory = Memory(
        workspace_id=workspace_id,
        project_id=project_id,
        content=label,
        category=parent_category,
        type="permanent",
        node_type=CONCEPT_NODE_KIND,
        subject_kind=None,
        source_conversation_id=None,
        parent_memory_id=subject.id,
        subject_memory_id=subject.id,
        node_status=ACTIVE_NODE_STATUS,
        canonical_key=str(metadata.get("canonical_key") or "").strip() or None,
        metadata_json=metadata,
    )
    db.add(concept_memory)
    db.flush()
    memories_by_id[concept_memory.id] = concept_memory
    return concept_memory, True


def _default_parent_for_memory(
    memory: Memory,
    *,
    root_memory: Memory,
    memories_by_id: dict[str, Memory],
) -> Memory:
    if is_subject_memory(memory):
        return root_memory
    subject_memory_id = memory.subject_memory_id
    if subject_memory_id:
        subject_memory = memories_by_id.get(subject_memory_id)
        if subject_memory is not None and is_subject_memory(subject_memory):
            return subject_memory
    return root_memory


def _find_repair_parent(
    memory: Memory,
    *,
    current_parent: Memory | None,
    root_memory: Memory,
    memories_by_id: dict[str, Memory],
) -> Memory:
    if (
        current_parent
        and current_parent.parent_memory_id
        and not is_category_path_memory(current_parent)
        and not is_summary_memory(current_parent)
    ):
        grandparent = memories_by_id.get(current_parent.parent_memory_id)
        if _is_structural_parent_memory(grandparent):
            return grandparent

    best_candidate: Memory | None = None
    best_score = 0.0
    for candidate in memories_by_id.values():
        if candidate.project_id != memory.project_id or candidate.id == memory.id:
            continue
        if not is_concept_memory(candidate):
            continue
        score = _score_concept_parent(candidate, memory)
        if score > best_score:
            best_candidate = candidate
            best_score = score
    if best_candidate and best_score >= 0.55:
        return best_candidate
    return _default_parent_for_memory(
        memory,
        root_memory=root_memory,
        memories_by_id=memories_by_id,
    )


def _delete_memory(db: Session, memory_id: str) -> None:
    db.query(MemoryEdge).filter(
        or_(
            MemoryEdge.source_memory_id == memory_id,
            MemoryEdge.target_memory_id == memory_id,
        )
    ).delete(synchronize_session=False)
    db.query(MemoryFile).filter(MemoryFile.memory_id == memory_id).delete(synchronize_session=False)
    db.execute(sql_text("DELETE FROM embeddings WHERE memory_id = :memory_id"), {"memory_id": memory_id})
    db.query(Memory).filter(Memory.id == memory_id).delete(synchronize_session=False)


def _concept_merge_priority(
    memory: Memory,
    *,
    child_count: int,
) -> tuple[int, int, int, int, str]:
    metadata = get_memory_metadata(memory)
    topic_key = _normalize_text_key(_get_concept_topic_for_matching(memory))
    label_key = _normalize_text_key(str(metadata.get("concept_label") or memory.content or ""))
    content_key = _normalize_text_key(memory.content)
    return (
        1 if is_pinned_memory(memory) else 0,
        0 if _is_auto_generated_concept(memory) else 1,
        1 if content_key and content_key == label_key and content_key != topic_key else 0,
        child_count,
        memory.id,
    )


def _merge_duplicate_concepts(
    db: Session,
    *,
    memories_by_id: dict[str, Memory],
    summary: MemoryGraphRepairSummary,
) -> None:
    child_counts: dict[str, int] = {}
    for memory in memories_by_id.values():
        parent_id = str(memory.parent_memory_id or "").strip()
        if parent_id:
            child_counts[parent_id] = child_counts.get(parent_id, 0) + 1

    grouped: dict[tuple[str, str, str], list[Memory]] = {}
    for memory in memories_by_id.values():
        if not is_concept_memory(memory):
            continue
        topic = _get_concept_topic_for_matching(memory)
        topic_key = _normalize_text_key(topic)
        if not topic_key:
            continue
        group_key = (
            str(memory.subject_memory_id or "").strip(),
            str(get_memory_kind(memory) or "").strip(),
            topic_key,
        )
        grouped.setdefault(group_key, []).append(memory)

    for group in grouped.values():
        if len(group) < 2:
            continue

        protected = [memory for memory in group if is_pinned_memory(memory) or not _is_auto_generated_concept(memory)]
        if len(protected) > 1:
            summary.skipped_nodes += len(group)
            continue

        winner = max(group, key=lambda item: _concept_merge_priority(item, child_count=child_counts.get(item.id, 0)))
        winner_topic = _get_concept_topic_for_matching(winner)
        winner_subject = memories_by_id.get(winner.subject_memory_id or "")
        if winner_subject is not None:
            winner_label = _build_fact_concept_label(
                subject=winner_subject,
                topic=winner_topic,
                fact_category=winner.category,
            )
            parent_category = _build_concept_category(fact_category=winner.category, topic=winner_topic)
            _refresh_backfill_concept_parent(
                winner,
                subject=winner_subject,
                topic=winner_topic,
                label=winner_label,
                parent_category=parent_category,
            )

        for duplicate in group:
            if duplicate.id == winner.id:
                continue
            if is_pinned_memory(duplicate) or not _is_auto_generated_concept(duplicate):
                summary.skipped_nodes += 1
                continue

            children = [
                child
                for child in memories_by_id.values()
                if child.parent_memory_id == duplicate.id and child.id != winner.id
            ]
            for child in children:
                if child.parent_memory_id != winner.id:
                    child.parent_memory_id = winner.id
                    if child.subject_memory_id != winner.subject_memory_id:
                        child.subject_memory_id = winner.subject_memory_id
                    summary.reparented_nodes += 1

            deleted_id = duplicate.id
            memories_by_id.pop(deleted_id, None)
            _delete_memory(db, deleted_id)
            summary.deleted_duplicate_concepts += 1

        child_counts[winner.id] = sum(1 for memory in memories_by_id.values() if memory.parent_memory_id == winner.id)


def repair_project_memory_graph(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
) -> MemoryGraphRepairSummary:
    project = (
        db.query(Project)
        .filter(
            Project.id == project_id,
            Project.workspace_id == workspace_id,
            Project.deleted_at.is_(None),
        )
        .first()
    )
    if project is None:
        return MemoryGraphRepairSummary()

    root_memory, _ = ensure_project_assistant_root(db, project, reparent_orphans=False)
    summary = MemoryGraphRepairSummary()

    memories = (
        db.query(Memory)
        .filter(
            Memory.workspace_id == workspace_id,
            Memory.project_id == project_id,
        )
        .all()
    )
    memories_by_id = {memory.id: memory for memory in memories}

    deleted_memory_ids: set[str] = set()

    legacy_nodes = [
        memory
        for memory in memories
        if memory.id != root_memory.id and (is_category_path_memory(memory) or is_summary_memory(memory))
    ]
    for memory in legacy_nodes:
        if memory.id in deleted_memory_ids:
            continue

        children = [
            child
            for child in memories
            if child.parent_memory_id == memory.id and child.id not in deleted_memory_ids
        ]
        for child in children:
            replacement_parent = _find_repair_parent(
                child,
                current_parent=memory,
                root_memory=root_memory,
                memories_by_id=memories_by_id,
            )
            if child.parent_memory_id != replacement_parent.id:
                child.parent_memory_id = replacement_parent.id
                summary.reparented_nodes += 1
            if has_manual_parent_binding(child):
                child.metadata_json = normalize_memory_metadata(
                    content=child.content,
                    category=child.category,
                    memory_type=child.type,
                    metadata=clear_manual_parent_binding(dict(child.metadata_json or {})),
                )

        deleted_memory_ids.add(memory.id)
        memories_by_id.pop(memory.id, None)
        _delete_memory(db, memory.id)
        summary.deleted_legacy_nodes += 1

    for memory in memories:
        if memory.id == root_memory.id:
            continue
        if memory.id in deleted_memory_ids:
            continue
        if is_pinned_memory(memory) or not _is_auto_managed_memory(memory):
            continue
        if not _is_aggregate_leaf_memory(memory):
            continue

        for child in memories:
            if child.parent_memory_id != memory.id or child.id in deleted_memory_ids:
                continue
            if is_pinned_memory(child) or not _is_auto_managed_memory(child):
                summary.skipped_nodes += 1
                continue
            replacement_parent = _find_repair_parent(
                child,
                current_parent=memory,
                root_memory=root_memory,
                memories_by_id=memories_by_id,
            )
            if child.parent_memory_id != replacement_parent.id:
                child.parent_memory_id = replacement_parent.id
                summary.reparented_nodes += 1

        deleted_memory_ids.add(memory.id)
        memories_by_id.pop(memory.id, None)
        _delete_memory(db, memory.id)
        summary.deleted_aggregate_nodes += 1

    remaining_memories = (
        db.query(Memory)
        .filter(
            Memory.workspace_id == workspace_id,
            Memory.project_id == project_id,
        )
        .all()
    )
    memories_by_id = {memory.id: memory for memory in remaining_memories}

    for memory in list(remaining_memories):
        if memory.id == root_memory.id or memory.id in deleted_memory_ids:
            continue
        if memory.type != "permanent" or memory.node_status != ACTIVE_NODE_STATUS:
            continue
        if get_memory_kind(memory) != MEMORY_KIND_FACT:
            continue
        if not is_fact_memory(memory):
            continue
        if is_pinned_memory(memory) or has_manual_parent_binding(memory) or not _is_auto_managed_memory(memory):
            continue

        current_parent = memories_by_id.get(memory.parent_memory_id or "")
        if current_parent is None or not is_subject_memory(current_parent):
            continue

        topic = _infer_backfill_concept_topic(memory, subject=current_parent)
        if not topic:
            continue

        concept_parent, concept_created = _ensure_backfill_concept_parent(
            db,
            workspace_id=workspace_id,
            project_id=project_id,
            subject=current_parent,
            memory=memory,
            topic=topic,
            memories_by_id=memories_by_id,
        )
        if concept_parent is None:
            continue
        if concept_created:
            summary.created_concept_nodes += 1
        if memory.parent_memory_id != concept_parent.id:
            memory.parent_memory_id = concept_parent.id
            summary.reparented_nodes += 1

    remaining_memories = (
        db.query(Memory)
        .filter(
            Memory.workspace_id == workspace_id,
            Memory.project_id == project_id,
        )
        .all()
    )
    memories_by_id = {memory.id: memory for memory in remaining_memories}
    _merge_duplicate_concepts(
        db,
        memories_by_id=memories_by_id,
        summary=summary,
    )

    remaining_memories = (
        db.query(Memory)
        .filter(
            Memory.workspace_id == workspace_id,
            Memory.project_id == project_id,
        )
        .all()
    )
    memories_by_id = {memory.id: memory for memory in remaining_memories}

    for memory in remaining_memories:
        if memory.id == root_memory.id or memory.id in deleted_memory_ids:
            continue
        parent = memories_by_id.get(memory.parent_memory_id or "")
        if parent is not None and parent.id == memory.id:
            if is_pinned_memory(memory) or not _is_auto_managed_memory(memory):
                summary.skipped_nodes += 1
                continue
            replacement_parent = _default_parent_for_memory(
                memory,
                root_memory=root_memory,
                memories_by_id=memories_by_id,
            )
            if memory.parent_memory_id != replacement_parent.id:
                memory.parent_memory_id = replacement_parent.id
                summary.reparented_nodes += 1
            parent = replacement_parent
        if parent is None:
            if is_pinned_memory(memory) or not _is_auto_managed_memory(memory):
                summary.skipped_nodes += 1
                continue
            if memory.parent_memory_id != root_memory.id:
                memory.parent_memory_id = root_memory.id
                summary.reparented_nodes += 1
            continue
        if _is_structural_parent_memory(parent):
            continue
        if is_pinned_memory(memory) or not _is_auto_managed_memory(memory):
            summary.skipped_nodes += 1
            continue

        replacement_parent = _find_repair_parent(
            memory,
            current_parent=parent,
            root_memory=root_memory,
            memories_by_id=memories_by_id,
        )
        if memory.parent_memory_id != replacement_parent.id:
            memory.parent_memory_id = replacement_parent.id
            summary.reparented_nodes += 1

    valid_auto_edges = {
        (memory.parent_memory_id, memory.id)
        for memory in remaining_memories
        if memory.parent_memory_id
        and memory.parent_memory_id in memories_by_id
        and not is_assistant_root_memory(memories_by_id[memory.parent_memory_id])
        and _is_structural_parent_memory(memories_by_id[memory.parent_memory_id])
    }

    auto_edges = (
        db.query(MemoryEdge)
        .filter(
            MemoryEdge.edge_type.in_(list(REPAIR_MUTABLE_EDGE_TYPES)),
            MemoryEdge.source_memory_id.in_(list(memories_by_id)),
            MemoryEdge.target_memory_id.in_(list(memories_by_id)),
        )
        .all()
    )
    existing_auto_pairs = {(edge.source_memory_id, edge.target_memory_id): edge for edge in auto_edges}

    for edge in auto_edges:
        # Repair only mutates legacy auto-structure edges. Version edges
        # (`supersedes` / `conflict`) are intentionally outside its authority.
        if edge.edge_type in PROTECTED_VERSION_EDGE_TYPES or edge.edge_type not in REPAIR_MUTABLE_EDGE_TYPES:
            continue
        pair = (edge.source_memory_id, edge.target_memory_id)
        source = memories_by_id.get(edge.source_memory_id)
        if pair not in valid_auto_edges or not _is_structural_parent_memory(source):
            db.delete(edge)
            summary.deleted_auto_edges += 1

    for source_memory_id, target_memory_id in sorted(valid_auto_edges):
        if (source_memory_id, target_memory_id) in existing_auto_pairs:
            continue
        db.add(
            MemoryEdge(
                source_memory_id=source_memory_id,
                target_memory_id=target_memory_id,
                edge_type=AUTO_EDGE_TYPE,
                strength=0.76,
            )
        )
        summary.created_auto_edges += 1
    db.flush()
    return summary
