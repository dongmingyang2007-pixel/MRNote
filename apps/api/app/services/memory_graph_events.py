from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Memory, MemoryEdge, MemoryFile
from app.services.runtime_state import runtime_state

_GRAPH_REVISION_SCOPE = "memory_graph_revision"
_GRAPH_REVISION_TTL_SECONDS = 60 * 60 * 24 * 30
_GRAPH_MUTATION_TYPES = (Memory, MemoryEdge, MemoryFile)


def _project_graph_key(*, workspace_id: str, project_id: str) -> str:
    return f"{workspace_id}:{project_id}"


def get_project_memory_graph_revision(*, workspace_id: str, project_id: str) -> int:
    return runtime_state.get_int(_GRAPH_REVISION_SCOPE, _project_graph_key(workspace_id=workspace_id, project_id=project_id))


def bump_project_memory_graph_revision(*, workspace_id: str, project_id: str) -> int:
    return runtime_state.incr(
        _GRAPH_REVISION_SCOPE,
        _project_graph_key(workspace_id=workspace_id, project_id=project_id),
        ttl_seconds=_GRAPH_REVISION_TTL_SECONDS,
    )


def session_has_pending_graph_mutations(db: Session) -> bool:
    pending = tuple(db.new) + tuple(db.dirty) + tuple(db.deleted)
    return any(isinstance(item, _GRAPH_MUTATION_TYPES) for item in pending)
