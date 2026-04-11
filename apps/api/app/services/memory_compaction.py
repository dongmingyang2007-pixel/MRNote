from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import re

from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Memory, MemoryFile, MemoryView, Project
from app.services.dashscope_client import chat_completion
from app.services.memory_metadata import (
    MEMORY_KIND_EPISODIC,
    MEMORY_KIND_PREFERENCE,
    MEMORY_KIND_PROFILE,
    build_summary_group_key,
    get_lineage_key,
    get_memory_kind,
    get_memory_metadata,
    get_memory_salience,
    is_active_memory,
    is_category_path_memory,
    is_concept_memory,
    is_pinned_memory,
    is_subject_memory,
    is_summary_memory,
    normalize_category_path,
    shorten_text,
)
from app.services.memory_roots import is_assistant_root_memory
from app.services.memory_visibility import build_private_memory_metadata, get_memory_owner_user_id, is_private_memory

SUMMARY_MIN_GROUP_SIZE = 3
SUMMARY_MAX_SOURCE_MEMORIES = 8
SUMMARY_MIN_TOTAL_CHARS = 36
SUMMARY_EDGE_STRENGTH = 0.92

SUMMARY_PROMPT = """你是记忆压缩器。请把同一主题的多条记忆压缩成一条高信息密度摘要记忆。

要求：
- 保留稳定事实、长期偏好、持续目标
- 删除重复和一次性措辞
- 不要编造新事实
- 输出一句到三句话，适合作为长期上下文
- 如果这些记忆只是零散片段，不值得形成摘要，返回 {{"skip": true}}

主题：{category}

记忆列表：
{memory_lines}

输出 JSON：
{{"skip": false, "summary": "...", "category": "{category}"}}"""


@dataclass(slots=True)
class MemoryCompactionSummary:
    created_summaries: int = 0
    updated_summaries: int = 0
    deleted_summaries: int = 0
    updated_summary_ids: list[str] | None = None

    def as_dict(self) -> dict[str, int | list[str]]:
        return asdict(self)


def _summary_category(memory: Memory, memories_by_id: dict[str, Memory]) -> str:
    parent = memories_by_id.get(memory.parent_memory_id or "")
    if parent is not None and is_concept_memory(parent):
        category = normalize_category_path(parent.category)
        if category:
            return category
    category = normalize_category_path(memory.category)
    return category or "uncategorized"


def _eligible_for_compaction(memory: Memory) -> bool:
    if memory.type != "permanent":
        return False
    if not is_active_memory(memory):
        return False
    if (
        is_assistant_root_memory(memory)
        or is_summary_memory(memory)
        or is_subject_memory(memory)
        or is_concept_memory(memory)
        or is_category_path_memory(memory)
        or is_pinned_memory(memory)
    ):
        return False
    if get_memory_kind(memory) == MEMORY_KIND_EPISODIC:
        return False
    return bool(memory.content.strip())


def _select_primary_active_facts(memories: list[Memory]) -> list[Memory]:
    def _sort_key(memory: Memory) -> tuple[float, object, object]:
        return (
            get_memory_salience(memory),
            memory.updated_at or memory.created_at,
            memory.created_at,
        )

    selected: dict[str, Memory] = {}
    for memory in memories:
        if not _eligible_for_compaction(memory):
            continue
        lineage_key = get_lineage_key(memory) or memory.id
        existing = selected.get(lineage_key)
        if existing is None:
            selected[lineage_key] = memory
            continue
        existing_key = _sort_key(existing)
        candidate_key = _sort_key(memory)
        if candidate_key > existing_key:
            selected[lineage_key] = memory
    return list(selected.values())


def _group_memories(memories: list[Memory]) -> dict[str, list[Memory]]:
    groups: dict[str, list[Memory]] = {}
    memories_by_id = {memory.id: memory for memory in memories}
    for memory in memories:
        if not _eligible_for_compaction(memory):
            continue
        owner_user_id = get_memory_owner_user_id(memory) if is_private_memory(memory) else None
        memory_kind = get_memory_kind(memory)
        if memory_kind in {MEMORY_KIND_PROFILE, MEMORY_KIND_PREFERENCE}:
            summary_family = memory_kind
        else:
            summary_family = "topic"
        group_key = build_summary_group_key(
            owner_user_id=owner_user_id,
            parent_memory_id=memory.parent_memory_id,
            category=_summary_category(memory, memories_by_id),
            memory_kind=summary_family,
        )
        groups.setdefault(group_key, []).append(memory)
    return groups


def _fallback_summary_text(memories: list[Memory]) -> str:
    statements: list[str] = []
    for memory in memories:
        normalized = shorten_text(memory.content, limit=140)
        if normalized and normalized not in statements:
            statements.append(normalized)
        if len(statements) >= 4:
            break
    if not statements:
        return ""
    if len(statements) == 1:
        return statements[0]
    return "；".join(statements)


def _parse_summary_payload(raw: str, *, fallback_category: str) -> tuple[str, str] | None:
    if not raw.strip():
        return None
    match = re.search(r"\{.*\}", raw.strip(), re.DOTALL)
    if match:
        try:
            payload = json.loads(match.group(0))
        except (json.JSONDecodeError, ValueError):
            payload = None
        if isinstance(payload, dict):
            if payload.get("skip") is True:
                return None
            summary = str(payload.get("summary") or "").strip()
            category = str(payload.get("category") or fallback_category).strip() or fallback_category
            if summary:
                return summary, category
    summary = raw.strip()
    return (summary, fallback_category) if summary else None


async def _generate_summary_for_group(
    *,
    memories: list[Memory],
    category: str,
) -> tuple[str, str] | None:
    memory_lines = "\n".join(
        f"- ({memory.id}) {shorten_text(memory.content, limit=220)}"
        for memory in memories
    )
    try:
        raw = await chat_completion(
            [{"role": "user", "content": SUMMARY_PROMPT.format(category=category, memory_lines=memory_lines)}],
            model=settings.memory_triage_model,
            temperature=0.1,
            max_tokens=256,
        )
    except Exception:
        raw = ""
    parsed = _parse_summary_payload(raw, fallback_category=category)
    if parsed is not None:
        return parsed
    fallback = _fallback_summary_text(memories)
    return (fallback, category) if fallback else None


async def compact_project_memories(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
) -> MemoryCompactionSummary:
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
        return MemoryCompactionSummary(updated_summary_ids=[])

    memories = (
        db.query(Memory)
        .filter(
            Memory.workspace_id == workspace_id,
            Memory.project_id == project_id,
            Memory.type == "permanent",
        )
        .all()
    )
    grouped = _group_memories(_select_primary_active_facts(memories))
    summary_views = (
        db.query(MemoryView)
        .filter(
            MemoryView.workspace_id == workspace_id,
            MemoryView.project_id == project_id,
            MemoryView.view_type == "summary",
        )
        .all()
    )
    summaries_by_group = {
        str((view.metadata_json or {}).get("summary_group_key") or ""): view
        for view in summary_views
        if str((view.metadata_json or {}).get("summary_group_key") or "")
    }
    active_group_keys: set[str] = set()

    summary = MemoryCompactionSummary(updated_summary_ids=[])
    for group_key, group_memories in grouped.items():
        if len(group_memories) < SUMMARY_MIN_GROUP_SIZE:
            continue
        ordered_group = sorted(
            group_memories,
            key=lambda memory: (get_memory_salience(memory), memory.updated_at),
            reverse=True,
        )[:SUMMARY_MAX_SOURCE_MEMORIES]
        total_chars = sum(len(memory.content.strip()) for memory in ordered_group)
        min_chars = max(SUMMARY_MIN_TOTAL_CHARS, len(ordered_group) * 10)
        if total_chars < min_chars:
            continue

        sample = ordered_group[0]
        summary_category = _summary_category(sample, {memory.id: memory for memory in memories})
        summary_payload = await _generate_summary_for_group(
            memories=ordered_group,
            category=summary_category,
        )
        if summary_payload is None:
            continue
        summary_content, summary_category = summary_payload
        active_group_keys.add(group_key)
        owner_user_id = get_memory_owner_user_id(sample) if is_private_memory(sample) else None
        source_memory_ids = [memory.id for memory in ordered_group]
        summary_metadata: dict[str, object] = {
            "summary_group_key": group_key,
            "source_memory_ids": list(dict.fromkeys(source_memory_ids)),
            "source_count": len(list(dict.fromkeys(source_memory_ids))),
            "category": summary_category,
            "salience": max(0.82, max(get_memory_salience(memory) for memory in ordered_group)),
            "auto_generated": True,
            "view_kind": "summary",
        }
        if owner_user_id:
            summary_metadata = build_private_memory_metadata(summary_metadata, owner_user_id=owner_user_id)

        summary_view = summaries_by_group.get(group_key)
        source_subject_id = sample.subject_memory_id

        if summary_view is None:
            summary_view = MemoryView(
                workspace_id=workspace_id,
                project_id=project_id,
                source_subject_id=source_subject_id,
                view_type="summary",
                content=summary_content,
                metadata_json=summary_metadata,
            )
            db.add(summary_view)
            db.flush()
            summaries_by_group[group_key] = summary_view
            summary.created_summaries += 1
        else:
            summary_view.content = summary_content
            summary_view.source_subject_id = source_subject_id
            summary_view.metadata_json = summary_metadata
            summary.updated_summaries += 1

        summary.updated_summary_ids.append(summary_view.id)

    stale_group_keys = sorted(set(summaries_by_group) - active_group_keys)
    for group_key in stale_group_keys:
        summary_view = summaries_by_group[group_key]
        db.delete(summary_view)
        summary.deleted_summaries += 1

    legacy_summary_memories = [memory for memory in memories if is_summary_memory(memory)]
    for summary_memory in legacy_summary_memories:
        db.query(MemoryFile).filter(MemoryFile.memory_id == summary_memory.id).delete(synchronize_session=False)
        db.execute(
            sql_text("DELETE FROM embeddings WHERE memory_id = :memory_id"),
            {"memory_id": summary_memory.id},
        )
        db.query(Memory).filter(Memory.id == summary_memory.id).delete(synchronize_session=False)
        summary.deleted_summaries += 1

    return summary
