from __future__ import annotations

from typing import Any

from app.core.deps import can_access_workspace_conversation, is_workspace_privileged_role
from app.models import Memory

PRIVATE_MEMORY_VISIBILITY = "private"


def get_memory_metadata(memory: Memory | None) -> dict[str, Any]:
    if memory is None:
        return {}
    metadata = memory.metadata_json or {}
    return metadata if isinstance(metadata, dict) else {}


def get_memory_owner_user_id(memory: Memory | None) -> str | None:
    owner_user_id = get_memory_metadata(memory).get("owner_user_id")
    return owner_user_id if isinstance(owner_user_id, str) and owner_user_id else None


def is_private_memory(memory: Memory | None) -> bool:
    metadata = get_memory_metadata(memory)
    return metadata.get("visibility") == PRIVATE_MEMORY_VISIBILITY and get_memory_owner_user_id(memory) is not None


def build_private_memory_metadata(
    metadata: dict[str, Any] | None,
    *,
    owner_user_id: str | None,
) -> dict[str, Any]:
    payload = dict(metadata or {})
    if owner_user_id:
        payload["visibility"] = PRIVATE_MEMORY_VISIBILITY
        payload["owner_user_id"] = owner_user_id
    return payload


def memory_visible_to_user(
    memory: Memory,
    *,
    current_user_id: str,
    workspace_role: str,
    conversation_created_by: str | None = None,
) -> bool:
    if memory.type == "temporary":
        return can_access_workspace_conversation(
            current_user_id=current_user_id,
            workspace_role=workspace_role,
            conversation_created_by=conversation_created_by,
        )
    if not is_private_memory(memory):
        return True
    return is_workspace_privileged_role(workspace_role) or get_memory_owner_user_id(memory) == current_user_id
