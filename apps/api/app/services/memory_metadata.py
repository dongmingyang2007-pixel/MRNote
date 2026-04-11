from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

from app.models import Memory

MEMORY_KIND_PROFILE = "profile"
MEMORY_KIND_PREFERENCE = "preference"
MEMORY_KIND_GOAL = "goal"
MEMORY_KIND_EPISODIC = "episodic"
MEMORY_KIND_FACT = "fact"
MEMORY_KIND_SUMMARY = "summary"
ROOT_NODE_TYPE = "root"
SUBJECT_NODE_TYPE = "subject"
FACT_NODE_TYPE = "fact"
ACTIVE_NODE_STATUS = "active"
SUPERSEDED_NODE_STATUS = "superseded"
ARCHIVED_NODE_STATUS = "archived"
SUBJECT_NODE_KIND = "subject"
CONCEPT_NODE_KIND = "concept"
CATEGORY_PATH_NODE_KIND = "category-path"
SUMMARY_NODE_KIND = "summary"
CATEGORY_PATH_CONCEPT_SOURCE = "category_path"
PARENT_BINDING_AUTO = "auto"
PARENT_BINDING_MANUAL = "manual"
RELATED_EDGE_EXCLUSIONS_KEY = "related_edge_exclusions"

VALID_NODE_TYPES = {
    ROOT_NODE_TYPE,
    SUBJECT_NODE_TYPE,
    CONCEPT_NODE_KIND,
    FACT_NODE_TYPE,
}
VALID_NODE_STATUSES = {
    ACTIVE_NODE_STATUS,
    SUPERSEDED_NODE_STATUS,
    ARCHIVED_NODE_STATUS,
}

_VALID_MEMORY_KINDS = {
    MEMORY_KIND_PROFILE,
    MEMORY_KIND_PREFERENCE,
    MEMORY_KIND_GOAL,
    MEMORY_KIND_EPISODIC,
    MEMORY_KIND_FACT,
    MEMORY_KIND_SUMMARY,
}

_PROFILE_HINTS = (
    "我是",
    "我叫",
    "名字",
    "住在",
    "来自",
    "工作",
    "职业",
    "专业",
    "年龄",
    "身份",
    "i am",
    "my name",
    "i live",
    "i work",
)
_PREFERENCE_HINTS = (
    "喜欢",
    "偏好",
    "爱吃",
    "爱看",
    "热爱",
    "讨厌",
    "不喜欢",
    "prefer",
    "favorite",
    "like ",
    "dislike",
)
_GOAL_HINTS = (
    "计划",
    "打算",
    "准备",
    "目标",
    "想要",
    "正在学",
    "希望",
    "will ",
    "plan ",
    "goal",
    "trying to",
)
_EPISODIC_HINTS = (
    "今天",
    "昨天",
    "刚刚",
    "这次",
    "本次",
    "today",
    "yesterday",
    "just now",
    "this conversation",
)


def get_memory_metadata(memory: Memory | dict[str, Any] | None) -> dict[str, Any]:
    if memory is None:
        return {}
    if isinstance(memory, dict):
        return memory if isinstance(memory, dict) else {}
    metadata = memory.metadata_json or {}
    return metadata if isinstance(metadata, dict) else {}


def coerce_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def coerce_float(value: Any, default: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, numeric))


def is_summary_memory(memory: Memory | dict[str, Any] | None) -> bool:
    metadata = get_memory_metadata(memory)
    return metadata.get("node_kind") == SUMMARY_NODE_KIND or metadata.get("memory_kind") == MEMORY_KIND_SUMMARY


def is_concept_memory(memory: Memory | dict[str, Any] | None) -> bool:
    metadata = get_memory_metadata(memory)
    node_type = getattr(memory, "node_type", None) if memory is not None and not isinstance(memory, dict) else None
    return node_type == CONCEPT_NODE_KIND or metadata.get("node_kind") == CONCEPT_NODE_KIND


def is_subject_memory(memory: Memory | dict[str, Any] | None) -> bool:
    metadata = get_memory_metadata(memory)
    node_type = getattr(memory, "node_type", None) if memory is not None and not isinstance(memory, dict) else None
    return node_type == SUBJECT_NODE_TYPE or metadata.get("node_kind") == SUBJECT_NODE_KIND


def is_fact_memory(memory: Memory | dict[str, Any] | None) -> bool:
    return get_node_type(memory) == FACT_NODE_TYPE


def is_category_path_memory(memory: Memory | dict[str, Any] | None) -> bool:
    metadata = get_memory_metadata(memory)
    return (
        metadata.get("node_kind") == CATEGORY_PATH_NODE_KIND
        or metadata.get("concept_source") == CATEGORY_PATH_CONCEPT_SOURCE
    )


def is_structural_only_memory(memory: Memory | dict[str, Any] | None) -> bool:
    metadata = get_memory_metadata(memory)
    return is_category_path_memory(memory) or coerce_bool(metadata.get("structural_only"), False)


def get_parent_binding_mode(memory: Memory | dict[str, Any] | None) -> str:
    metadata = get_memory_metadata(memory)
    raw = str(metadata.get("parent_binding") or "").strip().lower()
    if raw == PARENT_BINDING_MANUAL:
        return PARENT_BINDING_MANUAL
    return PARENT_BINDING_AUTO


def has_manual_parent_binding(memory: Memory | dict[str, Any] | None) -> bool:
    return get_parent_binding_mode(memory) == PARENT_BINDING_MANUAL


def get_manual_parent_id(memory: Memory | dict[str, Any] | None) -> str | None:
    if not has_manual_parent_binding(memory):
        return None
    metadata = get_memory_metadata(memory)
    value = metadata.get("manual_parent_id")
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def set_manual_parent_binding(
    metadata: dict[str, Any] | None,
    *,
    parent_memory_id: str | None,
) -> dict[str, Any]:
    payload = dict(metadata or {})
    payload["parent_binding"] = PARENT_BINDING_MANUAL
    payload["manual_parent_id"] = str(parent_memory_id).strip() if parent_memory_id else None
    return payload


def clear_manual_parent_binding(metadata: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(metadata or {})
    payload["parent_binding"] = PARENT_BINDING_AUTO
    payload.pop("manual_parent_id", None)
    return payload


def get_related_edge_exclusions(memory: Memory | dict[str, Any] | None) -> list[str]:
    metadata = get_memory_metadata(memory)
    raw = metadata.get(RELATED_EDGE_EXCLUSIONS_KEY)
    if not isinstance(raw, list):
        return []
    seen: set[str] = set()
    ordered: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        value = item.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def add_related_edge_exclusion(
    metadata: dict[str, Any] | None,
    *,
    memory_id: str,
) -> dict[str, Any]:
    value = str(memory_id or "").strip()
    if not value:
        return dict(metadata or {})
    payload = dict(metadata or {})
    exclusions = get_related_edge_exclusions(payload)
    if value not in exclusions:
        exclusions.append(value)
    payload[RELATED_EDGE_EXCLUSIONS_KEY] = exclusions
    return payload


def remove_related_edge_exclusion(
    metadata: dict[str, Any] | None,
    *,
    memory_id: str,
) -> dict[str, Any]:
    value = str(memory_id or "").strip()
    payload = dict(metadata or {})
    exclusions = [item for item in get_related_edge_exclusions(payload) if item != value]
    if exclusions:
        payload[RELATED_EDGE_EXCLUSIONS_KEY] = exclusions
    else:
        payload.pop(RELATED_EDGE_EXCLUSIONS_KEY, None)
    return payload


def split_category_segments(category: str) -> list[str]:
    return [
        segment.strip()
        for segment in str(category or "").split(".")
        if segment.strip()
    ]


def normalize_category_path(category: str) -> str:
    return ".".join(split_category_segments(category))


def get_category_path_prefixes(category: str) -> list[str]:
    prefixes: list[str] = []
    parts: list[str] = []
    for segment in split_category_segments(category):
        parts.append(segment)
        prefixes.append(".".join(parts))
    return prefixes


def get_memory_category_segments(memory: Memory | dict[str, Any] | None) -> list[str]:
    metadata = get_memory_metadata(memory)
    raw_segments = metadata.get("category_segments")
    if isinstance(raw_segments, list):
        segments = [str(segment).strip() for segment in raw_segments if str(segment).strip()]
        if segments:
            return segments
    if isinstance(memory, Memory):
        return split_category_segments(memory.category)
    if isinstance(memory, dict):
        return split_category_segments(str(memory.get("category") or ""))
    return []


def get_memory_category_label(memory: Memory | dict[str, Any] | None) -> str:
    metadata = get_memory_metadata(memory)
    label = str(metadata.get("category_label") or "").strip()
    if label:
        return label
    segments = get_memory_category_segments(memory)
    return segments[-1] if segments else ""


def get_memory_category_path(memory: Memory | dict[str, Any] | None) -> str:
    metadata = get_memory_metadata(memory)
    path = str(metadata.get("category_path") or "").strip()
    if path:
        return path
    if isinstance(memory, Memory):
        return normalize_category_path(memory.category)
    if isinstance(memory, dict):
        return normalize_category_path(str(memory.get("category") or ""))
    return ""


def normalize_node_type(value: Any, *, fallback: str = FACT_NODE_TYPE) -> str:
    raw = str(value or "").strip().lower()
    if raw in VALID_NODE_TYPES:
        return raw
    if raw == CATEGORY_PATH_NODE_KIND:
        return CONCEPT_NODE_KIND
    if raw == SUMMARY_NODE_KIND:
        return FACT_NODE_TYPE
    if raw == "assistant-root":
        return ROOT_NODE_TYPE
    return fallback


def normalize_node_status(value: Any, *, fallback: str = ACTIVE_NODE_STATUS) -> str:
    raw = str(value or "").strip().lower()
    if raw in VALID_NODE_STATUSES:
        return raw
    return fallback


def get_node_type(memory: Memory | dict[str, Any] | None) -> str:
    if isinstance(memory, Memory):
        direct = str(getattr(memory, "node_type", "") or "").strip().lower()
        if direct in VALID_NODE_TYPES:
            return direct
    metadata = get_memory_metadata(memory)
    node_kind = str(metadata.get("node_kind") or "").strip().lower()
    if node_kind == "assistant-root":
        return ROOT_NODE_TYPE
    return normalize_node_type(metadata.get("node_type") or node_kind, fallback=FACT_NODE_TYPE)


def get_node_status(memory: Memory | dict[str, Any] | None) -> str:
    if isinstance(memory, Memory):
        direct = str(getattr(memory, "node_status", "") or "").strip().lower()
        if direct in VALID_NODE_STATUSES:
            return direct
    metadata = get_memory_metadata(memory)
    return normalize_node_status(metadata.get("node_status"), fallback=ACTIVE_NODE_STATUS)


def is_active_memory(memory: Memory | dict[str, Any] | None) -> bool:
    return get_node_status(memory) == ACTIVE_NODE_STATUS


def get_subject_kind(memory: Memory | dict[str, Any] | None) -> str | None:
    if isinstance(memory, Memory):
        direct = str(getattr(memory, "subject_kind", "") or "").strip().lower()
        if direct:
            return direct
    metadata = get_memory_metadata(memory)
    raw = str(metadata.get("subject_kind") or "").strip().lower()
    return raw or None


def get_subject_memory_id(memory: Memory | dict[str, Any] | None) -> str | None:
    if isinstance(memory, Memory):
        direct = getattr(memory, "subject_memory_id", None)
        if isinstance(direct, str) and direct.strip():
            return direct.strip()
    metadata = get_memory_metadata(memory)
    value = metadata.get("subject_memory_id")
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return None


def get_lineage_key(memory: Memory | dict[str, Any] | None) -> str | None:
    if isinstance(memory, Memory):
        direct = getattr(memory, "lineage_key", None)
        if isinstance(direct, str) and direct.strip():
            return direct.strip()
    metadata = get_memory_metadata(memory)
    raw = metadata.get("lineage_key")
    if isinstance(raw, str):
        value = raw.strip()
        return value or None
    return None


def build_canonical_key(
    *,
    content: str,
    category: str = "",
    node_type: str,
    subject_kind: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str | None:
    payload = dict(metadata or {})
    explicit = str(payload.get("canonical_key") or "").strip().lower()
    if explicit:
        return explicit

    normalized_type = normalize_node_type(node_type)
    normalized_content = shorten_text(content, limit=240).strip().lower()
    normalized_content = re.sub(r"\s+", " ", normalized_content)
    normalized_content = re.sub(r"[，。、“”‘’\"'`()（）,.!?！？:：;；\-_/\\]+", " ", normalized_content)
    normalized_content = re.sub(r"\s+", "-", normalized_content).strip("-")
    normalized_category = normalize_category_path(category).strip().lower().replace(".", "/")
    if normalized_type == ROOT_NODE_TYPE:
        return "root"
    if normalized_type == SUBJECT_NODE_TYPE:
        kind = str(subject_kind or payload.get("subject_kind") or "custom").strip().lower() or "custom"
        owner_key = str(payload.get("owner_user_id") or "").strip().lower()
        label = normalized_content or normalized_category or "subject"
        scope = f":{owner_key}" if owner_key else ":public"
        return f"subject:{kind}{scope}:{label}"
    if normalized_type == CONCEPT_NODE_KIND:
        topic = str(payload.get("concept_topic") or "").strip().lower()
        topic = re.sub(r"\s+", "-", topic)
        label = topic or normalized_content or normalized_category or "concept"
        return f"concept:{label}"
    if normalized_type == FACT_NODE_TYPE:
        label = normalized_content or normalized_category
        return f"fact:{label}" if label else None
    return None


def derive_memory_kind(
    *,
    content: str,
    category: str = "",
    memory_type: str = "permanent",
    metadata: dict[str, Any] | None = None,
) -> str:
    existing = str((metadata or {}).get("memory_kind") or "").strip().lower()
    if existing in _VALID_MEMORY_KINDS:
        return existing
    if is_summary_memory(metadata):
        return MEMORY_KIND_SUMMARY

    haystack = f"{category}\n{content}".strip().lower()
    if any(hint in haystack for hint in _PROFILE_HINTS):
        return MEMORY_KIND_PROFILE
    if any(hint in haystack for hint in _PREFERENCE_HINTS):
        return MEMORY_KIND_PREFERENCE
    if any(hint in haystack for hint in _GOAL_HINTS):
        return MEMORY_KIND_GOAL
    if any(hint in haystack for hint in _EPISODIC_HINTS):
        return MEMORY_KIND_EPISODIC
    return MEMORY_KIND_FACT


def get_memory_kind(memory: Memory | dict[str, Any] | None) -> str:
    metadata = get_memory_metadata(memory)
    kind = str(metadata.get("memory_kind") or "").strip().lower()
    if kind in _VALID_MEMORY_KINDS:
        return kind
    if isinstance(memory, Memory):
        return derive_memory_kind(
            content=memory.content,
            category=memory.category,
            memory_type=memory.type,
            metadata=metadata,
        )
    return MEMORY_KIND_FACT


def get_memory_salience(memory: Memory | dict[str, Any] | None) -> float:
    metadata = get_memory_metadata(memory)
    default = 0.55
    if is_summary_memory(memory):
        default = 0.82
    elif isinstance(memory, Memory) and memory.type == "temporary":
        default = 0.45
    return coerce_float(metadata.get("salience", metadata.get("importance")), default)


def is_pinned_memory(memory: Memory | dict[str, Any] | None) -> bool:
    metadata = get_memory_metadata(memory)
    if is_summary_memory(memory):
        return coerce_bool(metadata.get("pinned"), False)
    return coerce_bool(metadata.get("pinned"), False)


def get_summary_source_memory_ids(memory: Memory | dict[str, Any] | None) -> list[str]:
    metadata = get_memory_metadata(memory)
    source_ids = metadata.get("source_memory_ids")
    if not isinstance(source_ids, list):
        return []
    return [item for item in source_ids if isinstance(item, str) and item]


def build_summary_group_key(
    *,
    owner_user_id: str | None,
    parent_memory_id: str | None,
    category: str,
    memory_kind: str,
) -> str:
    normalized_category = ".".join(
        segment.strip().lower()
        for segment in str(category or "").split(".")
        if segment.strip()
    ) or "uncategorized"
    owner_key = owner_user_id or "public"
    parent_key = parent_memory_id or "root"
    return f"{owner_key}|{parent_key}|{memory_kind}|{normalized_category}"


def normalize_memory_metadata(
    *,
    content: str,
    category: str,
    memory_type: str,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    payload = dict(metadata or {})
    if get_parent_binding_mode(payload) == PARENT_BINDING_MANUAL:
        payload["parent_binding"] = PARENT_BINDING_MANUAL
        payload["manual_parent_id"] = get_manual_parent_id(payload)
    else:
        payload = clear_manual_parent_binding(payload)
    normalized_category = normalize_category_path(category)
    category_segments = split_category_segments(normalized_category)
    payload["category_path"] = normalized_category
    payload["category_segments"] = category_segments
    payload["category_label"] = category_segments[-1] if category_segments else ""
    payload["category_prefixes"] = get_category_path_prefixes(normalized_category)
    payload["node_type"] = normalize_node_type(
        payload.get("node_type") or payload.get("node_kind"),
        fallback=FACT_NODE_TYPE,
    )
    payload["node_status"] = normalize_node_status(payload.get("node_status"), fallback=ACTIVE_NODE_STATUS)
    lineage_key = str(payload.get("lineage_key") or "").strip() or None
    if payload["node_type"] != FACT_NODE_TYPE:
        lineage_key = None
    if lineage_key:
        payload["lineage_key"] = lineage_key
    else:
        payload.pop("lineage_key", None)
    payload["memory_kind"] = derive_memory_kind(
        content=content,
        category=category,
        memory_type=memory_type,
        metadata=payload,
    )
    payload["salience"] = get_memory_salience(payload)
    payload["pinned"] = is_pinned_memory(payload)
    if is_category_path_memory(payload):
        payload["node_kind"] = CATEGORY_PATH_NODE_KIND
        payload["concept_source"] = CATEGORY_PATH_CONCEPT_SOURCE
        payload["structural_only"] = True
        payload["node_type"] = CONCEPT_NODE_KIND
        payload = clear_manual_parent_binding(payload)
    if payload["memory_kind"] == MEMORY_KIND_SUMMARY:
        payload["node_kind"] = SUMMARY_NODE_KIND
    elif payload["node_type"] == CONCEPT_NODE_KIND:
        payload["node_kind"] = CONCEPT_NODE_KIND
    elif payload["node_type"] == SUBJECT_NODE_TYPE and payload.get("node_kind") not in {"assistant-root", "file"}:
        payload["node_kind"] = SUBJECT_NODE_KIND
    payload["canonical_key"] = build_canonical_key(
        content=content,
        category=category,
        node_type=payload["node_type"],
        subject_kind=str(payload.get("subject_kind") or "").strip() or None,
        metadata=payload,
    )
    if "last_used_at" in payload and not isinstance(payload.get("last_used_at"), str):
        payload.pop("last_used_at", None)
    return payload


def stamp_memory_usage_metadata(
    metadata: dict[str, Any] | None,
    *,
    source: str,
    score: float | None,
    used_at: datetime | None = None,
) -> dict[str, Any]:
    payload = dict(metadata or {})
    timestamp = (used_at or datetime.now(timezone.utc)).isoformat()
    payload["last_used_at"] = timestamp
    payload["last_used_source"] = source
    payload["retrieval_count"] = int(payload.get("retrieval_count") or 0) + 1
    if score is not None:
        payload["last_retrieval_score"] = round(float(score), 4)
    return payload


def build_summary_memory_metadata(
    *,
    content: str,
    category: str,
    source_memory_ids: list[str],
    summary_group_key: str,
    salience: float,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(metadata or {})
    payload.update(
        {
            "memory_kind": MEMORY_KIND_SUMMARY,
            "node_kind": SUMMARY_NODE_KIND,
            "source_memory_ids": list(dict.fromkeys(source_memory_ids)),
            "source_count": len(list(dict.fromkeys(source_memory_ids))),
            "summary_group_key": summary_group_key,
            "salience": coerce_float(salience, 0.85),
            "auto_generated": True,
            "summarized_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    return normalize_memory_metadata(
        content=content,
        category=category,
        memory_type="permanent",
        metadata=payload,
    )


def shorten_text(value: str, limit: int = 180) -> str:
    normalized = re.sub(r"\s+", " ", value).strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"
