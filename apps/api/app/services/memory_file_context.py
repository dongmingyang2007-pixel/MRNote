from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import DataItem, Dataset, Memory, MemoryFile, Project
from app.services.embedding import (
    find_related_data_items_for_memory,
    find_related_memories_for_data_item,
    search_data_item_chunks,
)
from app.services.memory_v2 import ensure_memory_file_evidence
from app.services.memory_visibility import is_private_memory


AUTO_LINK_LIMIT = 5
AUTO_LINK_MIN_SCORE = 0.55


def _is_completed_data_item(item: DataItem) -> bool:
    status = (item.meta_json or {}).get("upload_status")
    return status in {None, "completed", "index_failed"}


def sync_memory_links_for_data_item(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    data_item_id: str,
    limit: int = AUTO_LINK_LIMIT,
    min_score: float = AUTO_LINK_MIN_SCORE,
) -> list[str]:
    """Attach a newly indexed data item to the most relevant permanent memories."""
    data_item = db.get(DataItem, data_item_id)
    if data_item is None:
        return []

    candidates = find_related_memories_for_data_item(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        data_item_id=data_item_id,
        limit=limit,
        min_score=min_score,
    )
    memory_ids = [candidate["memory_id"] for candidate in candidates if candidate.get("memory_id")]
    if not memory_ids:
        return []

    existing_memory_ids = {
        memory_id
        for memory_id, in db.query(MemoryFile.memory_id)
        .filter(MemoryFile.data_item_id == data_item_id, MemoryFile.memory_id.in_(memory_ids))
        .all()
    }

    created_memory_ids: list[str] = []
    for memory_id in memory_ids:
        if memory_id in existing_memory_ids:
            continue
        db.add(MemoryFile(memory_id=memory_id, data_item_id=data_item_id))
        memory = db.get(Memory, memory_id)
        if memory is not None:
            ensure_memory_file_evidence(
                db,
                memory=memory,
                data_item=data_item,
                metadata_json={"link_source": "data_item_auto_link"},
            )
        created_memory_ids.append(memory_id)

    if created_memory_ids:
        db.commit()
    return created_memory_ids


def sync_data_item_links_for_memory(
    db: Session,
    *,
    memory: Memory,
    limit: int = AUTO_LINK_LIMIT,
    min_score: float = AUTO_LINK_MIN_SCORE,
) -> list[str]:
    """Attach the most relevant indexed data items to a permanent public memory."""
    if memory.type != "permanent" or is_private_memory(memory):
        return []

    candidates = find_related_data_items_for_memory(
        db,
        workspace_id=memory.workspace_id,
        project_id=memory.project_id,
        memory_id=memory.id,
        limit=limit,
        min_score=min_score,
    )
    data_item_ids = [candidate["data_item_id"] for candidate in candidates if candidate.get("data_item_id")]
    if not data_item_ids:
        return []

    existing_data_item_ids = {
        data_item_id
        for data_item_id, in db.query(MemoryFile.data_item_id)
        .filter(MemoryFile.memory_id == memory.id, MemoryFile.data_item_id.in_(data_item_ids))
        .all()
    }

    created_data_item_ids: list[str] = []
    data_items_by_id = {
        item.id: item
        for item in (
            db.query(DataItem)
            .filter(DataItem.id.in_(data_item_ids))
            .all()
            if data_item_ids
            else []
        )
    }
    for data_item_id in data_item_ids:
        if data_item_id in existing_data_item_ids:
            continue
        db.add(MemoryFile(memory_id=memory.id, data_item_id=data_item_id))
        data_item = data_items_by_id.get(data_item_id)
        if data_item is not None:
            ensure_memory_file_evidence(
                db,
                memory=memory,
                data_item=data_item,
                metadata_json={"link_source": "memory_auto_link"},
            )
        created_data_item_ids.append(data_item_id)

    if created_data_item_ids:
        db.commit()
    return created_data_item_ids


async def load_linked_file_chunks_for_memories(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    memory_ids: list[str],
    query: str,
    limit: int = 4,
) -> list[dict]:
    """Retrieve the best matching chunks from files attached to the selected memories."""
    unique_memory_ids = list(dict.fromkeys(memory_ids))
    if not unique_memory_ids:
        return []

    rows = (
        db.query(MemoryFile, DataItem)
        .join(DataItem, DataItem.id == MemoryFile.data_item_id)
        .join(Dataset, Dataset.id == DataItem.dataset_id)
        .join(Project, Project.id == Dataset.project_id)
        .filter(
            MemoryFile.memory_id.in_(unique_memory_ids),
            DataItem.deleted_at.is_(None),
            Dataset.deleted_at.is_(None),
            Project.id == project_id,
            Project.workspace_id == workspace_id,
            Project.deleted_at.is_(None),
        )
        .all()
    )

    data_item_to_memory_ids: dict[str, list[str]] = {}
    filenames_by_data_item: dict[str, str] = {}
    ordered_data_item_ids: list[str] = []
    for memory_file, data_item in rows:
        if not _is_completed_data_item(data_item):
            continue
        if data_item.id not in data_item_to_memory_ids:
            data_item_to_memory_ids[data_item.id] = []
            ordered_data_item_ids.append(data_item.id)
        data_item_to_memory_ids[data_item.id].append(memory_file.memory_id)
        filenames_by_data_item[data_item.id] = data_item.filename

    if not ordered_data_item_ids:
        return []

    chunk_hits = await search_data_item_chunks(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        query=query,
        data_item_ids=ordered_data_item_ids,
        limit=limit,
    )

    results: list[dict] = []
    for hit in chunk_hits:
        data_item_id = hit.get("data_item_id")
        if not isinstance(data_item_id, str) or data_item_id not in data_item_to_memory_ids:
            continue
        results.append(
            {
                **hit,
                "filename": filenames_by_data_item.get(data_item_id, hit.get("filename") or ""),
                "memory_ids": list(dict.fromkeys(data_item_to_memory_ids[data_item_id])),
            }
        )
    return results
