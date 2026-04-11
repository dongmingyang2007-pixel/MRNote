from __future__ import annotations

from dataclasses import asdict, dataclass

from sqlalchemy.orm import Session

from app.models import Memory, Project
from app.services.memory_metadata import (
    clear_manual_parent_binding,
    has_manual_parent_binding,
    is_concept_memory,
    is_subject_memory,
    normalize_memory_metadata,
)
from app.services.memory_roots import ensure_project_assistant_root, is_assistant_root_memory
from app.services.memory_visibility import (
    get_memory_owner_user_id,
    is_private_memory,
)


@dataclass(slots=True)
class CategoryTreeSyncSummary:
    created_path_nodes: int = 0
    normalized_path_nodes: int = 0
    reparented_nodes: int = 0
    deleted_empty_path_nodes: int = 0
    created_auto_edges: int = 0
    deleted_auto_edges: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


def _same_visibility(left: Memory, right: Memory) -> bool:
    if is_private_memory(left) != is_private_memory(right):
        return False
    if not is_private_memory(left):
        return True
    return get_memory_owner_user_id(left) == get_memory_owner_user_id(right)


def _preferred_parent_for_memory(
    *,
    memory: Memory,
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


def _is_preservable_parent(candidate: Memory | None, child: Memory) -> bool:
    if candidate is None or is_assistant_root_memory(candidate):
        return False
    if not _same_visibility(candidate, child):
        return False
    if is_subject_memory(candidate):
        return True
    if not is_concept_memory(candidate):
        return False
    child_subject_memory_id = child.subject_memory_id
    candidate_subject_memory_id = candidate.subject_memory_id
    if child_subject_memory_id and candidate_subject_memory_id != child_subject_memory_id:
        return False
    return True


def ensure_project_category_tree(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
) -> CategoryTreeSyncSummary:
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
        return CategoryTreeSyncSummary()

    summary = CategoryTreeSyncSummary()
    root_memory, _changed = ensure_project_assistant_root(db, project, reparent_orphans=False)
    memories = (
        db.query(Memory)
        .filter(
            Memory.project_id == project_id,
            Memory.workspace_id == workspace_id,
        )
        .all()
    )
    memories_by_id = {memory.id: memory for memory in memories}

    for memory in memories:
        if memory.id == root_memory.id:
            continue
        current_parent = memories_by_id.get(memory.parent_memory_id or "")
        if _is_preservable_parent(current_parent, memory):
            continue
        desired_parent = _preferred_parent_for_memory(
            memory=memory,
            root_memory=root_memory,
            memories_by_id=memories_by_id,
        )
        if memory.parent_memory_id != desired_parent.id:
            memory.parent_memory_id = desired_parent.id
            summary.reparented_nodes += 1
        if has_manual_parent_binding(memory):
            memory.metadata_json = normalize_memory_metadata(
                content=memory.content,
                category=memory.category,
                memory_type=memory.type,
                metadata=clear_manual_parent_binding(dict(memory.metadata_json or {})),
            )

    return summary
