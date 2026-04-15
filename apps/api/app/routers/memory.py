import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import (
    can_access_workspace_conversation,
    enforce_rate_limit,
    get_current_user,
    get_current_workspace_id,
    get_current_workspace_role,
    get_db_session,
    require_csrf_protection,
    require_workspace_write_access,
)
from app.core.errors import ApiError
from app.models import (
    Conversation,
    DataItem,
    Dataset,
    Memory,
    MemoryEdge,
    MemoryEpisode,
    MemoryEvidence,
    MemoryFile,
    MemoryLearningRun,
    MemoryOutcome,
    MemoryView,
    MemoryWriteItem,
    Project,
    User,
)
from app.routers.utils import get_data_item_in_workspace, get_project_in_workspace_or_404
from app.schemas.memory import (
    MemoryBackfillOut,
    MemoryBackfillRequest,
    MemoryBackfillSummaryOut,
    MemoryCreate,
    MemoryDetailOut,
    MemoryExplainOut,
    MemoryExplainRequest,
    MemoryEdgeCreate,
    MemoryFileAttachRequest,
    MemoryFileCandidateOut,
    MemoryEdgeOut,
    MemoryEpisodeOut,
    MemoryEvidenceOut,
    MemoryFileOut,
    MemoryGraphOut,
    MemoryHealthEntryOut,
    MemoryHealthOut,
    MemoryLearningRunOut,
    MemoryOut,
    MemoryOutcomeCreate,
    MemoryOutcomeOut,
    MemorySearchRequest,
    MemorySearchHit,
    MemorySearchResult,
    MessageMemoryLearningOut,
    PlaybookFeedbackRequest,
    SubjectOverviewOut,
    SubjectResolveCandidate,
    SubjectResolveRequest,
    SubjectResolveResult,
    SubgraphOut,
    SubgraphRequest,
    MemorySupersedeRequest,
    MemoryViewOut,
    MemoryUpdate,
    MemoryWriteItemOut,
)
from app.services.embedding import embed_and_store, search_similar
from app.services.audit import write_audit_log
from app.services.memory_context import (
    explain_project_memory_hits_v2,
    expand_subject_subgraph,
    get_subject_overview,
    resolve_active_subjects,
    search_project_memory_hits_v2,
)
from app.services.memory_graph_events import bump_project_memory_graph_revision
from app.services.memory_metadata import (
    ACTIVE_NODE_STATUS,
    FACT_NODE_TYPE,
    add_related_edge_exclusion,
    get_lineage_key,
    is_active_memory,
    is_fact_memory,
    normalize_node_status,
    normalize_node_type,
    has_manual_parent_binding,
    is_concept_memory,
    is_category_path_memory,
    is_subject_memory,
    is_structural_only_memory,
    is_summary_memory,
    normalize_memory_metadata,
    remove_related_edge_exclusion,
    set_manual_parent_binding,
)
from app.services.memory_related_edges import (
    RELATED_EDGE_TYPE,
    ensure_project_prerequisite_edges,
    ensure_project_related_edges,
)
from app.services.memory_file_context import sync_data_item_links_for_memory
from app.services.memory_roots import ensure_project_assistant_root, is_assistant_root_memory
from app.services.memory_versioning import (
    CONFLICT_EDGE_TYPE,
    SUPERSEDES_EDGE_TYPE,
    VERSION_EDGE_TYPES,
    create_fact_successor,
    ensure_fact_lineage,
)
from app.services.memory_visibility import (
    build_private_memory_metadata,
    is_private_memory,
    memory_visible_to_user,
)
from app.services.memory_v2 import (
    apply_temporal_defaults,
    apply_memory_outcome,
    create_memory_outcome,
    get_memory_learning_run,
    get_message_memory_learning,
    ensure_memory_file_evidence,
    merge_learning_stages,
    list_memory_evidences,
    list_memory_episodes,
    list_memory_outcomes_for_learning_run,
    list_learning_runs_for_memory,
    list_memory_timeline_events,
    list_memory_views_for_memory,
    list_memory_write_history,
    list_project_learning_runs,
    list_project_playbook_views,
    refresh_memory_health_signals,
    summarize_memory_health,
)

router = APIRouter(prefix="/api/v1/memory", tags=["memory"])
ORDINARY_PARENT_FORBIDDEN_MESSAGE = (
    "Ordinary memories must stay as leaf nodes. Use the project root, a subject, or a concept as the primary parent instead."
)


def _is_completed_data_item(item: DataItem) -> bool:
    status = (item.meta_json or {}).get("upload_status")
    return status in {None, "completed", "index_failed"}


def _conversation_visible_to_user(
    conversation: Conversation,
    *,
    current_user_id: str,
    workspace_role: str,
) -> bool:
    return can_access_workspace_conversation(
        current_user_id=current_user_id,
        workspace_role=workspace_role,
        conversation_created_by=conversation.created_by,
    )


def _verify_conversation_ownership(
    db: Session,
    *,
    conversation_id: str,
    project_id: str,
    workspace_id: str,
    current_user_id: str,
    workspace_role: str,
) -> Conversation:
    conversation = (
        db.query(Conversation)
        .join(Project, Project.id == Conversation.project_id)
        .filter(
            Conversation.id == conversation_id,
            Conversation.project_id == project_id,
            Conversation.workspace_id == workspace_id,
            Project.workspace_id == workspace_id,
            Project.deleted_at.is_(None),
        )
        .first()
    )
    if not conversation or not _conversation_visible_to_user(
        conversation,
        current_user_id=current_user_id,
        workspace_role=workspace_role,
    ):
        raise ApiError("not_found", "Conversation not found", status_code=404)
    return conversation


def _verify_parent_memory(
    db: Session,
    *,
    parent_memory_id: str,
    project_id: str,
    workspace_id: str,
    current_user_id: str,
    workspace_role: str,
) -> Memory:
    parent = _get_accessible_memory_or_404(
        db,
        memory_id=parent_memory_id,
        workspace_id=workspace_id,
        current_user_id=current_user_id,
        workspace_role=workspace_role,
    )
    if parent.project_id != project_id:
        raise ApiError("not_found", "Parent memory not found", status_code=404)
    return parent


def _resolve_optional_conversation_context(
    db: Session,
    *,
    project_id: str,
    workspace_id: str,
    current_user_id: str,
    workspace_role: str,
    conversation_id: str | None,
) -> tuple[str, str | None]:
    if conversation_id:
        conversation = _verify_conversation_ownership(
            db,
            conversation_id=conversation_id,
            project_id=project_id,
            workspace_id=workspace_id,
            current_user_id=current_user_id,
            workspace_role=workspace_role,
        )
        return conversation.id, conversation.created_by
    return "", current_user_id


def _can_hold_primary_children(parent: Memory) -> bool:
    return (
        is_assistant_root_memory(parent)
        or is_subject_memory(parent)
        or is_concept_memory(parent)
    )


def _assert_supported_primary_parent(parent: Memory) -> None:
    if _can_hold_primary_children(parent):
        return
    raise ApiError(
        "bad_request",
        ORDINARY_PARENT_FORBIDDEN_MESSAGE,
        status_code=400,
    )


def _strip_parent_binding_fields(metadata: dict[str, object] | None) -> dict[str, object]:
    payload = dict(metadata or {})
    payload.pop("parent_binding", None)
    payload.pop("manual_parent_id", None)
    return payload


def _parse_optional_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _assert_primary_graph_metadata_allowed(metadata: dict[str, object]) -> None:
    if is_category_path_memory(metadata):
        raise ApiError(
            "bad_request",
            "Category-path nodes are a legacy derived view and cannot be created in the primary graph",
            status_code=400,
        )
    if is_summary_memory(metadata):
        raise ApiError(
            "bad_request",
            "Summary nodes are derived views and cannot be created in the primary graph",
            status_code=400,
        )


def _resolve_subject_memory_id(
    *,
    requested_subject_memory_id: str | None,
    parent: Memory | None,
    existing_subject_memory_id: str | None = None,
    node_type: str,
) -> str | None:
    if node_type == "subject":
        return None
    if isinstance(requested_subject_memory_id, str) and requested_subject_memory_id.strip():
        return requested_subject_memory_id.strip()
    if parent is not None:
        if is_subject_memory(parent):
            return parent.id
        if parent.subject_memory_id:
            return parent.subject_memory_id
    if isinstance(existing_subject_memory_id, str) and existing_subject_memory_id.strip():
        return existing_subject_memory_id.strip()
    return None


def _graph_parent_memory_id(memory: Memory, memories_by_id: dict[str, Memory], visible_ids: set[str]) -> str | None:
    current_id = memory.parent_memory_id
    visited: set[str] = set()
    while current_id:
        if current_id in visible_ids:
            return current_id
        if current_id in visited:
            return None
        visited.add(current_id)
        parent = memories_by_id.get(current_id)
        if parent is None:
            return None
        current_id = parent.parent_memory_id
    return None


def _memory_to_graph_out(
    memory: Memory,
    *,
    graph_parent_memory_id: str | None = None,
) -> MemoryOut:
    payload = MemoryOut.model_validate(memory, from_attributes=True)
    metadata = dict(payload.metadata_json or {})
    payload.suppression_reason = str(metadata.get("suppression_reason") or "").strip() or None
    payload.reconfirm_after = _parse_optional_datetime(metadata.get("reconfirm_after"))
    payload.last_used_at = _parse_optional_datetime(metadata.get("last_used_at"))
    reuse_success_rate = metadata.get("reuse_success_rate")
    payload.reuse_success_rate = float(reuse_success_rate) if isinstance(reuse_success_rate, (int, float)) else None
    if graph_parent_memory_id and graph_parent_memory_id != payload.parent_memory_id:
        metadata["graph_parent_memory_id"] = graph_parent_memory_id
    else:
        metadata.pop("graph_parent_memory_id", None)
    payload.metadata_json = metadata
    return payload


def _serialize_memory_out(memory: Memory) -> MemoryOut:
    return _memory_to_graph_out(memory)


def _serialize_edge_out(edge: MemoryEdge) -> MemoryEdgeOut:
    return MemoryEdgeOut.model_validate(edge, from_attributes=True)


def _serialize_evidence_out(evidence: MemoryEvidence) -> MemoryEvidenceOut:
    return MemoryEvidenceOut.model_validate(evidence, from_attributes=True)


def _serialize_episode_out(episode: MemoryEpisode) -> MemoryEpisodeOut:
    return MemoryEpisodeOut.model_validate(episode, from_attributes=True)


def _serialize_view_out(view: MemoryView) -> MemoryViewOut:
    return MemoryViewOut.model_validate(view, from_attributes=True)


def _serialize_learning_run_out(run: MemoryLearningRun) -> MemoryLearningRunOut:
    return MemoryLearningRunOut.model_validate(run, from_attributes=True)


def _serialize_outcome_out(outcome: MemoryOutcome) -> MemoryOutcomeOut:
    return MemoryOutcomeOut.model_validate(outcome, from_attributes=True)


def _serialize_write_item_out(item: MemoryWriteItem) -> MemoryWriteItemOut:
    return MemoryWriteItemOut.model_validate(item, from_attributes=True)


def _view_visible_to_user(
    view: MemoryView,
    *,
    visible_memory_ids: set[str],
    current_user_id: str,
) -> bool:
    if view.source_subject_id and view.source_subject_id not in visible_memory_ids:
        return False
    metadata = view.metadata_json if isinstance(view.metadata_json, dict) else {}
    owner_user_id = str(metadata.get("owner_user_id") or "").strip() or None
    if owner_user_id and owner_user_id != current_user_id:
        return False
    return True


def _assert_valid_parent_assignment(
    db: Session,
    *,
    memory_id: str,
    candidate_parent_id: str,
    workspace_id: str,
) -> None:
    current_id = candidate_parent_id
    visited: set[str] = set()
    while current_id:
        if current_id == memory_id:
            raise ApiError(
                "bad_request",
                "A memory cannot be reparented beneath one of its descendants",
                status_code=400,
            )
        if current_id in visited:
            raise ApiError("bad_request", "Memory hierarchy contains a cycle", status_code=400)
        visited.add(current_id)
        parent = (
            db.query(Memory.parent_memory_id)
            .filter(Memory.id == current_id, Memory.workspace_id == workspace_id)
            .first()
        )
        if parent is None:
            return
        current_id = parent[0] or ""


def _get_memory_or_404(db: Session, *, memory_id: str, workspace_id: str) -> Memory:
    memory = (
        db.query(Memory)
        .join(Project, Project.id == Memory.project_id)
        .filter(
            Memory.id == memory_id,
            Memory.workspace_id == workspace_id,
            Project.workspace_id == workspace_id,
            Project.deleted_at.is_(None),
        )
        .first()
    )
    if not memory:
        raise ApiError("not_found", "Memory not found", status_code=404)
    return memory


def _get_accessible_memory_or_404(
    db: Session,
    *,
    memory_id: str,
    workspace_id: str,
    current_user_id: str,
    workspace_role: str,
) -> Memory:
    memory = _get_memory_or_404(db, memory_id=memory_id, workspace_id=workspace_id)
    if memory.type == "temporary":
        if not memory.source_conversation_id:
            raise ApiError("not_found", "Memory not found", status_code=404)
        conversation = _verify_conversation_ownership(
            db,
            conversation_id=memory.source_conversation_id,
            project_id=memory.project_id,
            workspace_id=workspace_id,
            current_user_id=current_user_id,
            workspace_role=workspace_role,
        )
        if not memory_visible_to_user(
            memory,
            current_user_id=current_user_id,
            workspace_role=workspace_role,
            conversation_created_by=conversation.created_by,
        ):
            raise ApiError("not_found", "Memory not found", status_code=404)
        return memory
    if not memory_visible_to_user(
        memory,
        current_user_id=current_user_id,
        workspace_role=workspace_role,
    ):
        raise ApiError("not_found", "Memory not found", status_code=404)
    return memory


def _filter_accessible_memories(
    db: Session,
    memories: list[Memory],
    *,
    project_id: str,
    workspace_id: str,
    current_user_id: str,
    workspace_role: str,
) -> list[Memory]:
    temp_source_ids = {
        memory.source_conversation_id
        for memory in memories
        if memory.type == "temporary" and memory.source_conversation_id
    }
    conversations_by_id: dict[str, Conversation] = {}
    conversations = (
        db.query(Conversation)
        .join(Project, Project.id == Conversation.project_id)
        .filter(
            Conversation.id.in_(temp_source_ids),
            Conversation.project_id == project_id,
            Conversation.workspace_id == workspace_id,
            Project.workspace_id == workspace_id,
            Project.deleted_at.is_(None),
        )
        .all()
    ) if temp_source_ids else []
    conversations_by_id = {conversation.id: conversation for conversation in conversations}

    filtered: list[Memory] = []
    for memory in memories:
        conversation_created_by = None
        if memory.type == "temporary":
            if not memory.source_conversation_id:
                continue
            conversation = conversations_by_id.get(memory.source_conversation_id)
            if not conversation:
                continue
            conversation_created_by = conversation.created_by
        if memory_visible_to_user(
            memory,
            current_user_id=current_user_id,
            workspace_role=workspace_role,
            conversation_created_by=conversation_created_by,
        ):
            filtered.append(memory)
    return filtered


def _learning_run_memory_ids(run: MemoryLearningRun) -> set[str]:
    return {
        *(
            str(memory_id).strip()
            for memory_id in (run.used_memory_ids or [])
            if isinstance(memory_id, str) and str(memory_id).strip()
        ),
        *(
            str(memory_id).strip()
            for memory_id in (run.promoted_memory_ids or [])
            if isinstance(memory_id, str) and str(memory_id).strip()
        ),
        *(
            str(memory_id).strip()
            for memory_id in (run.degraded_memory_ids or [])
            if isinstance(memory_id, str) and str(memory_id).strip()
        ),
    }


def _filter_visible_learning_runs(
    db: Session,
    runs: list[MemoryLearningRun],
    *,
    project_id: str,
    workspace_id: str,
    current_user_id: str,
    workspace_role: str,
) -> list[MemoryLearningRun]:
    referenced_memory_ids = list(
        dict.fromkeys(
            memory_id
            for run in runs
            for memory_id in _learning_run_memory_ids(run)
        )
    )
    accessible_memory_ids = {
        memory.id
        for memory in _filter_accessible_memories(
            db,
            db.query(Memory)
            .filter(Memory.workspace_id == workspace_id, Memory.id.in_(referenced_memory_ids))
            .all()
            if referenced_memory_ids
            else [],
            project_id=project_id,
            workspace_id=workspace_id,
            current_user_id=current_user_id,
            workspace_role=workspace_role,
        )
    }
    conversation_ids = list(
        dict.fromkeys(
            str(run.conversation_id).strip()
            for run in runs
            if isinstance(run.conversation_id, str) and str(run.conversation_id).strip()
        )
    )
    conversations = (
        db.query(Conversation)
        .join(Project, Project.id == Conversation.project_id)
        .filter(
            Conversation.id.in_(conversation_ids),
            Conversation.project_id == project_id,
            Conversation.workspace_id == workspace_id,
            Project.workspace_id == workspace_id,
            Project.deleted_at.is_(None),
        )
        .all()
        if conversation_ids
        else []
    )
    visible_conversation_ids = {
        conversation.id
        for conversation in conversations
        if _conversation_visible_to_user(
            conversation,
            current_user_id=current_user_id,
            workspace_role=workspace_role,
        )
    }

    filtered: list[MemoryLearningRun] = []
    for run in runs:
        run_memory_ids = _learning_run_memory_ids(run)
        if run_memory_ids:
            if not run_memory_ids.isdisjoint(accessible_memory_ids):
                filtered.append(run)
                continue
            if run.conversation_id and run.conversation_id in visible_conversation_ids:
                filtered.append(run)
            continue
        if run.conversation_id:
            if run.conversation_id in visible_conversation_ids:
                filtered.append(run)
            continue
        filtered.append(run)
    return filtered


def _enforce_memory_read_rate_limit(request: Request, *, current_user_id: str) -> None:
    enforce_rate_limit(
        request,
        scope="memory-read",
        identifier=current_user_id,
        limit=settings.memory_read_rate_limit_max,
        window_seconds=settings.memory_read_rate_limit_window_seconds,
    )


def _enforce_memory_write_rate_limit(request: Request, *, current_user_id: str) -> None:
    enforce_rate_limit(
        request,
        scope="memory-write",
        identifier=current_user_id,
        limit=settings.memory_write_rate_limit_max,
        window_seconds=settings.memory_write_rate_limit_window_seconds,
    )


def _resolve_latest_visible_project_conversation(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    current_user_id: str,
    workspace_role: str,
) -> Conversation | None:
    project_conversations = (
        db.query(Conversation)
        .filter(
            Conversation.workspace_id == workspace_id,
            Conversation.project_id == project_id,
        )
        .order_by(Conversation.updated_at.desc())
        .all()
    )
    return next(
        (
            conversation
            for conversation in project_conversations
            if _conversation_visible_to_user(
                conversation,
                current_user_id=current_user_id,
                workspace_role=workspace_role,
            )
        ),
        None,
    )


def _load_memory_subgraph(
    db: Session,
    *,
    memory: Memory,
    depth: int,
    edge_types: list[str] | None,
    current_user_id: str,
    workspace_role: str,
    workspace_id: str,
) -> SubgraphOut:
    allowed_edge_types = set(
        edge_types
        or [
            "parent",
            "related",
            "manual",
            "prerequisite",
            "evidence",
            "supersedes",
            "conflict",
            "failed_under",
            "applies_to",
            "used_tool",
            "caused_by",
            "contradicts",
        ]
    )
    nodes_by_id: dict[str, Memory] = {memory.id: memory}
    visible_node_ids: set[str] = {memory.id}
    visited_node_ids: set[str] = {memory.id}
    edge_payloads: list[MemoryEdgeOut] = []
    seen_edge_keys: set[str] = set()
    frontier_ids: set[str] = {memory.id}

    for _ in range(max(1, depth)):
        if not frontier_ids:
            break
        frontier_list = list(frontier_ids)
        next_frontier: set[str] = set()

        graph_edges = (
            db.query(MemoryEdge)
            .filter(
                ((MemoryEdge.source_memory_id.in_(frontier_list)) | (MemoryEdge.target_memory_id.in_(frontier_list))),
                MemoryEdge.edge_type.in_([edge_type for edge_type in allowed_edge_types if edge_type != "parent"]),
            )
            .all()
        )
        candidate_ids = {
            edge.source_memory_id
            for edge in graph_edges
        } | {
            edge.target_memory_id
            for edge in graph_edges
        }

        parent_rows = (
            db.query(Memory)
            .filter(
                Memory.workspace_id == workspace_id,
                Memory.project_id == memory.project_id,
                (Memory.id.in_(frontier_list)) | (Memory.parent_memory_id.in_(frontier_list)),
            )
            .all()
        ) if "parent" in allowed_edge_types else []
        candidate_ids.update(item.id for item in parent_rows)
        candidate_ids.update(
            item.parent_memory_id
            for item in parent_rows
            if isinstance(item.parent_memory_id, str) and item.parent_memory_id
        )

        candidate_memories = (
            db.query(Memory)
            .filter(
                Memory.workspace_id == workspace_id,
                Memory.project_id == memory.project_id,
                Memory.id.in_(list(candidate_ids)),
            )
            .all()
            if candidate_ids
            else []
        )
        accessible_candidates = _filter_accessible_memories(
            db,
            candidate_memories,
            project_id=memory.project_id,
            workspace_id=workspace_id,
            current_user_id=current_user_id,
            workspace_role=workspace_role,
        )
        accessible_by_id = {item.id: item for item in accessible_candidates}
        nodes_by_id.update(accessible_by_id)
        visible_node_ids.update(accessible_by_id)

        for edge in graph_edges:
            if edge.source_memory_id not in visible_node_ids or edge.target_memory_id not in visible_node_ids:
                continue
            edge_key = edge.id or f"{edge.edge_type}:{edge.source_memory_id}:{edge.target_memory_id}"
            if edge_key in seen_edge_keys:
                continue
            seen_edge_keys.add(edge_key)
            edge_payloads.append(_serialize_edge_out(edge))
            if edge.source_memory_id in frontier_ids and edge.target_memory_id in visible_node_ids:
                next_frontier.add(edge.target_memory_id)
            if edge.target_memory_id in frontier_ids and edge.source_memory_id in visible_node_ids:
                next_frontier.add(edge.source_memory_id)

        if "parent" in allowed_edge_types:
            for item in parent_rows:
                if item.id not in visible_node_ids:
                    continue
                parent_id = item.parent_memory_id
                if not parent_id or parent_id not in visible_node_ids:
                    continue
                edge_key = f"parent:{parent_id}:{item.id}"
                if edge_key in seen_edge_keys:
                    continue
                seen_edge_keys.add(edge_key)
                edge_payloads.append(
                    MemoryEdgeOut(
                        id=edge_key,
                        source_memory_id=parent_id,
                        target_memory_id=item.id,
                        edge_type="parent",
                        strength=1.0,
                        confidence=1.0,
                        created_at=item.updated_at or item.created_at,
                    )
                )
                if item.id in frontier_ids:
                    next_frontier.add(parent_id)
                if parent_id in frontier_ids:
                    next_frontier.add(item.id)

        frontier_ids = next_frontier - visited_node_ids
        visited_node_ids.update(frontier_ids)

    return SubgraphOut(
        nodes=[_serialize_memory_out(item) for item in nodes_by_id.values() if item.id in visible_node_ids],
        edges=edge_payloads,
    )


def _delete_memory_embeddings(db: Session, memory_id: str) -> None:
    db.execute(
        sql_text("DELETE FROM embeddings WHERE memory_id = :memory_id"),
        {"memory_id": memory_id},
    )


def _sync_memory_embedding(memory: Memory, db: Session) -> None:
    if (
        is_assistant_root_memory(memory)
        or is_structural_only_memory(memory)
        or not settings.dashscope_api_key
        or not memory.content.strip()
    ):
        return
    try:
        _delete_memory_embeddings(db, memory.id)
        db.commit()
        asyncio.run(
            embed_and_store(
                db,
                workspace_id=memory.workspace_id,
                project_id=memory.project_id,
                memory_id=memory.id,
                chunk_text=memory.content,
            )
        )
        if memory.type == "permanent" and not is_private_memory(memory):
            sync_data_item_links_for_memory(db, memory=memory)
    except Exception:  # noqa: BLE001
        db.rollback()


def _trigger_memory_compaction(workspace_id: str, project_id: str) -> None:
    try:
        from app.tasks.worker_tasks import compact_project_memories_task

        if settings.env == "test":
            compact_project_memories_task(workspace_id, project_id)
        else:
            compact_project_memories_task.delay(workspace_id, project_id)
    except Exception:  # noqa: BLE001
        pass


def _trigger_memory_v2_backfill(
    *,
    workspace_id: str,
    project_id: str,
    limit: int | None,
) -> tuple[str, str | None, dict[str, int] | None]:
    from app.tasks.worker_tasks import backfill_project_memory_v2_task

    if settings.env == "test":
        summary = backfill_project_memory_v2_task(workspace_id, project_id, limit)
        return "completed", None, summary
    task = backfill_project_memory_v2_task.delay(workspace_id, project_id, limit)
    return "queued", task.id, None


def _sync_project_related_edges(db: Session, *, workspace_id: str, project_id: str) -> bool:
    summary = ensure_project_related_edges(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
    )
    prerequisite_summary = ensure_project_prerequisite_edges(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
    )
    return any(summary.as_dict().values()) or any(prerequisite_summary.as_dict().values())


def _materialize_memory_search_hits(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    results: list[dict[str, object]],
    category: str | None,
    memory_type: str | None,
    root_memory_id: str,
    current_user_id: str,
    workspace_role: str,
) -> list[MemorySearchHit]:
    memory_ids = [result["memory_id"] for result in results if result.get("memory_id")]
    subject_ids = [
        result["source_subject_id"]
        for result in results
        if result.get("result_type") == "view" and result.get("source_subject_id")
    ] + [
        result["supporting_memory_id"]
        for result in results
        if result.get("supporting_memory_id")
    ] + [
        result["memory_id"]
        for result in results
        if result.get("result_type") == "evidence" and result.get("memory_id")
    ]
    supporting_memory_ids = [
        result["supporting_memory_id"]
        for result in results
        if result.get("supporting_memory_id")
    ]
    lookup_memory_ids = list(dict.fromkeys([*memory_ids, *subject_ids, *supporting_memory_ids]))
    memories_by_id = {
        memory.id: memory
        for memory in (
            db.query(Memory)
            .filter(Memory.workspace_id == workspace_id, Memory.id.in_(lookup_memory_ids))
            .all()
            if lookup_memory_ids
            else []
        )
    }
    accessible_memories = _filter_accessible_memories(
        db,
        list(memories_by_id.values()),
        project_id=project_id,
        workspace_id=workspace_id,
        current_user_id=current_user_id,
        workspace_role=workspace_role,
    )
    accessible_memory_ids = {memory.id for memory in accessible_memories}

    view_ids = [
        result["view_id"]
        for result in results
        if result.get("result_type") == "view" and result.get("view_id")
    ]
    evidence_ids = [
        result["evidence_id"]
        for result in results
        if result.get("result_type") == "evidence" and result.get("evidence_id")
    ]
    views_by_id = {
        view.id: view
        for view in (
            db.query(MemoryView)
            .filter(MemoryView.workspace_id == workspace_id, MemoryView.id.in_(view_ids))
            .all()
            if view_ids
            else []
        )
    }
    evidences_by_id = {
        evidence.id: evidence
        for evidence in (
            db.query(MemoryEvidence)
            .filter(MemoryEvidence.id.in_(evidence_ids))
            .all()
            if evidence_ids
            else []
        )
    }

    output: list[MemorySearchHit] = []
    seen: set[str] = set()
    for result in results:
        result_type = str(result.get("result_type") or "").strip()
        if result_type == "memory":
            memory_id = result.get("memory_id")
            if not isinstance(memory_id, str):
                continue
            memory = memories_by_id.get(memory_id)
            if memory is None or memory.id not in accessible_memory_ids:
                continue
            if is_structural_only_memory(memory) or not is_active_memory(memory) or memory.id == root_memory_id:
                continue
            if category and memory.category != category:
                continue
            if memory_type and memory.type != memory_type:
                continue
            dedupe_key = f"memory:{memory.id}"
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            output.append(
                MemorySearchHit(
                    result_type="memory",
                    score=float(result.get("score") or 0.0),
                    snippet=str(result.get("snippet") or result.get("content") or memory.content),
                    memory=_serialize_memory_out(memory),
                    supporting_memory_id=memory.id,
                    selection_reason=str(result.get("selection_reason") or "").strip() or None,
                    suppression_reason=str(result.get("suppression_reason") or "").strip() or None,
                    outcome_weight=float(result.get("outcome_weight") or 1.0),
                    episode_id=str(result.get("episode_id") or "").strip() or None,
                )
            )
            continue

        if result_type == "evidence":
            evidence_id = result.get("evidence_id")
            memory_id = result.get("memory_id")
            if not isinstance(evidence_id, str) or not isinstance(memory_id, str):
                continue
            memory = memories_by_id.get(memory_id)
            evidence = evidences_by_id.get(evidence_id)
            if memory is None or evidence is None or memory.id not in accessible_memory_ids:
                continue
            if is_structural_only_memory(memory) or not is_active_memory(memory) or memory.id == root_memory_id:
                continue
            if category and memory.category != category:
                continue
            if memory_type and memory.type != memory_type:
                continue
            dedupe_key = f"evidence:{evidence.id}"
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            output.append(
                MemorySearchHit(
                    result_type="evidence",
                    score=float(result.get("score") or 0.0),
                    snippet=str(result.get("snippet") or evidence.quote_text),
                    memory=_serialize_memory_out(memory),
                    evidence=_serialize_evidence_out(evidence),
                    supporting_memory_id=memory.id,
                    selection_reason=str(result.get("selection_reason") or "").strip() or None,
                    outcome_weight=float(result.get("outcome_weight") or 1.0),
                    episode_id=str(result.get("episode_id") or evidence.episode_id or "").strip() or None,
                )
            )
            continue

        if result_type != "view":
            continue
        view_id = result.get("view_id")
        if not isinstance(view_id, str):
            continue
        view = views_by_id.get(view_id)
        if view is None:
            continue
        if not _view_visible_to_user(
            view,
            visible_memory_ids=accessible_memory_ids,
            current_user_id=current_user_id,
        ):
            continue
        source_memory = memories_by_id.get(view.source_subject_id or "")
        supporting_memory = memories_by_id.get(str(result.get("supporting_memory_id") or ""))
        if category or memory_type:
            memory_for_filter = supporting_memory or source_memory
            if memory_for_filter is None:
                continue
            if category and memory_for_filter.category != category:
                continue
            if memory_type and memory_for_filter.type != memory_type:
                continue
        dedupe_key = f"view:{view.id}"
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        output.append(
            MemorySearchHit(
                result_type="view",
                score=float(result.get("score") or 0.0),
                snippet=str(result.get("snippet") or view.content),
                memory=_serialize_memory_out(source_memory) if source_memory is not None else None,
                view=_serialize_view_out(view),
                supporting_memory_id=(
                    supporting_memory.id
                    if supporting_memory is not None
                    else source_memory.id if source_memory is not None else None
                ),
                selection_reason=str(result.get("selection_reason") or "").strip() or None,
                suppression_reason=str(result.get("suppression_reason") or "").strip() or None,
                outcome_weight=float(result.get("outcome_weight") or 1.0),
                episode_id=str(result.get("episode_id") or "").strip() or None,
            )
        )

    output.sort(key=lambda item: item.score, reverse=True)
    return output


def _bump_graph_revision(*, workspace_id: str, project_id: str) -> None:
    bump_project_memory_graph_revision(workspace_id=workspace_id, project_id=project_id)


def _normalize_lineage_metadata(memory: Memory) -> None:
    lineage_key = ensure_fact_lineage(memory)
    if lineage_key and memory.canonical_key is None:
        memory.canonical_key = str((memory.metadata_json or {}).get("canonical_key") or "").strip() or None


@router.get("", response_model=MemoryGraphOut)
def get_memory_graph(
    project_id: str = Query(...),
    conversation_id: str | None = Query(default=None),
    include_temporary: bool = Query(default=False),
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_role: str = Depends(get_current_workspace_role),
    workspace_id: str = Depends(get_current_workspace_id),
) -> MemoryGraphOut:
    project = get_project_in_workspace_or_404(db, project_id, workspace_id)
    if conversation_id:
        _verify_conversation_ownership(
            db,
            conversation_id=conversation_id,
            project_id=project_id,
            workspace_id=workspace_id,
            current_user_id=current_user.id,
            workspace_role=workspace_role,
        )
    _, changed = ensure_project_assistant_root(db, project)
    if changed:
        db.commit()
        _bump_graph_revision(workspace_id=workspace_id, project_id=project_id)

    # All permanent nodes for this project
    permanent = (
        db.query(Memory)
        .filter(Memory.project_id == project_id, Memory.workspace_id == workspace_id, Memory.type == "permanent")
        .all()
    )
    permanent = _filter_accessible_memories(
        db,
        permanent,
        project_id=project_id,
        workspace_id=workspace_id,
        current_user_id=current_user.id,
        workspace_role=workspace_role,
    )
    permanent = [memory for memory in permanent if is_active_memory(memory)]

    # Temporary nodes for given conversation (if provided)
    temporary: list[Memory] = []
    if conversation_id:
        temporary = (
            db.query(Memory)
            .filter(
                Memory.project_id == project_id,
                Memory.workspace_id == workspace_id,
                Memory.type == "temporary",
                Memory.source_conversation_id == conversation_id,
            )
            .all()
        )
    elif include_temporary:
        temporary = (
            db.query(Memory)
            .filter(
                Memory.project_id == project_id,
                Memory.workspace_id == workspace_id,
                Memory.type == "temporary",
            )
            .all()
        )

    if temporary:
        temporary = _filter_accessible_memories(
            db,
            temporary,
            project_id=project_id,
            workspace_id=workspace_id,
            current_user_id=current_user.id,
            workspace_role=workspace_role,
        )
        temporary = [memory for memory in temporary if is_active_memory(memory)]

    all_memories = permanent + temporary
    memories_by_id = {memory.id: memory for memory in all_memories}
    visible_memories = [
        memory
        for memory in all_memories
        if not is_category_path_memory(memory) and not is_summary_memory(memory)
    ]
    visible_ids = {memory.id for memory in visible_memories}
    memory_ids = [m.id for m in visible_memories]

    # All edges between the collected memory nodes
    edges: list[MemoryEdge] = []
    if memory_ids:
        edges = (
            db.query(MemoryEdge)
            .filter(MemoryEdge.source_memory_id.in_(memory_ids), MemoryEdge.target_memory_id.in_(memory_ids))
            .all()
        )

    file_nodes: list[MemoryOut] = []
    file_edges: list[MemoryEdgeOut] = []
    if memory_ids:
        memory_files = (
            db.query(MemoryFile, DataItem)
            .join(DataItem, DataItem.id == MemoryFile.data_item_id)
            .join(Dataset, Dataset.id == DataItem.dataset_id)
            .join(Project, Project.id == Dataset.project_id)
            .filter(
                MemoryFile.memory_id.in_(memory_ids),
                DataItem.deleted_at.is_(None),
                Dataset.deleted_at.is_(None),
                Project.deleted_at.is_(None),
                Project.workspace_id == workspace_id,
            )
            .all()
        )
        for memory_file, data_item in memory_files:
            if not _is_completed_data_item(data_item):
                continue
            parent_memory = memories_by_id.get(memory_file.memory_id)
            if not parent_memory:
                continue
            file_node_id = f"file:{memory_file.id}"
            filename = data_item.filename or data_item.object_key or data_item.id
            file_nodes.append(
                MemoryOut(
                    id=file_node_id,
                    workspace_id=parent_memory.workspace_id,
                    project_id=parent_memory.project_id,
                    content=filename,
                    category="file",
                    type="permanent",
                    source_conversation_id=None,
                    parent_memory_id=memory_file.memory_id,
                    position_x=None,
                    position_y=None,
                    metadata_json={
                        "node_kind": "file",
                        "memory_file_id": memory_file.id,
                        "memory_id": memory_file.memory_id,
                        "data_item_id": data_item.id,
                        "filename": filename,
                        "media_type": data_item.media_type,
                    },
                    created_at=memory_file.created_at,
                    updated_at=memory_file.created_at,
                )
            )
            file_edges.append(
                MemoryEdgeOut(
                    id=f"file-edge:{memory_file.id}",
                    source_memory_id=memory_file.memory_id,
                    target_memory_id=file_node_id,
                    edge_type="file",
                    strength=0.2,
                    created_at=memory_file.created_at,
                )
            )

    return MemoryGraphOut(
        nodes=[
            _memory_to_graph_out(
                memory,
                graph_parent_memory_id=_graph_parent_memory_id(
                    memory,
                    memories_by_id=memories_by_id,
                    visible_ids=visible_ids,
                ),
            )
            for memory in visible_memories
        ] + file_nodes,
        edges=[MemoryEdgeOut.model_validate(e, from_attributes=True) for e in edges] + file_edges,
    )


@router.post("/subjects/resolve", response_model=SubjectResolveResult)
async def resolve_subjects(
    payload: SubjectResolveRequest,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_role: str = Depends(get_current_workspace_role),
    workspace_id: str = Depends(get_current_workspace_id),
) -> SubjectResolveResult:
    get_project_in_workspace_or_404(db, payload.project_id, workspace_id)
    conversation_id, conversation_created_by = _resolve_optional_conversation_context(
        db,
        project_id=payload.project_id,
        workspace_id=workspace_id,
        current_user_id=current_user.id,
        workspace_role=workspace_role,
        conversation_id=payload.conversation_id,
    )
    result = await resolve_active_subjects(
        db,
        workspace_id=workspace_id,
        project_id=payload.project_id,
        conversation_id=conversation_id,
        conversation_created_by=conversation_created_by,
        query=payload.query,
        semantic_search_fn=search_similar,
    )
    subjects = result.get("subjects", [])
    primary_subject = result.get("primary_subject")
    return SubjectResolveResult(
        primary_subject_id=primary_subject.id if primary_subject is not None else None,
        subjects=[
            SubjectResolveCandidate(
                subject_id=candidate.memory.id,
                confidence=candidate.semantic_score if candidate.semantic_score is not None else candidate.score,
                label=candidate.memory.content,
                subject_kind=candidate.memory.subject_kind,
                canonical_key=candidate.memory.canonical_key,
            )
            for candidate in subjects
        ],
    )


@router.get("/subjects/{subject_id}/overview", response_model=SubjectOverviewOut)
def get_subject_overview_route(
    subject_id: str,
    conversation_id: str | None = Query(default=None),
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_role: str = Depends(get_current_workspace_role),
    workspace_id: str = Depends(get_current_workspace_id),
) -> SubjectOverviewOut:
    subject = _get_accessible_memory_or_404(
        db,
        memory_id=subject_id,
        workspace_id=workspace_id,
        current_user_id=current_user.id,
        workspace_role=workspace_role,
    )
    conversation_id, conversation_created_by = _resolve_optional_conversation_context(
        db,
        project_id=subject.project_id,
        workspace_id=workspace_id,
        current_user_id=current_user.id,
        workspace_role=workspace_role,
        conversation_id=conversation_id,
    )
    overview = get_subject_overview(
        db,
        workspace_id=workspace_id,
        project_id=subject.project_id,
        conversation_id=conversation_id,
        conversation_created_by=conversation_created_by,
        subject_id=subject_id,
    )
    if overview is None:
        raise ApiError("not_found", "Subject not found", status_code=404)
    return SubjectOverviewOut(
        subject=MemoryOut.model_validate(overview["subject"], from_attributes=True),
        concepts=[
            MemoryOut.model_validate(memory, from_attributes=True)
            for memory in overview.get("concepts", [])
        ],
        facts=[
            MemoryOut.model_validate(memory, from_attributes=True)
            for memory in overview.get("facts", [])
        ],
        suggested_paths=[
            path
            for path in overview.get("suggested_paths", [])
            if isinstance(path, str) and path.strip()
        ],
    )


@router.post("/subjects/{subject_id}/subgraph", response_model=SubgraphOut)
async def get_subject_subgraph_route(
    subject_id: str,
    payload: SubgraphRequest,
    conversation_id: str | None = Query(default=None),
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_role: str = Depends(get_current_workspace_role),
    workspace_id: str = Depends(get_current_workspace_id),
) -> SubgraphOut:
    subject = _get_accessible_memory_or_404(
        db,
        memory_id=subject_id,
        workspace_id=workspace_id,
        current_user_id=current_user.id,
        workspace_role=workspace_role,
    )
    conversation_id, conversation_created_by = _resolve_optional_conversation_context(
        db,
        project_id=subject.project_id,
        workspace_id=workspace_id,
        current_user_id=current_user.id,
        workspace_role=workspace_role,
        conversation_id=conversation_id,
    )
    subgraph = await expand_subject_subgraph(
        db,
        workspace_id=workspace_id,
        project_id=subject.project_id,
        conversation_id=conversation_id,
        conversation_created_by=conversation_created_by,
        subject_id=subject_id,
        query=payload.query,
        depth=payload.depth,
        edge_types=payload.edge_types,
        semantic_search_fn=search_similar,
    )
    if subgraph is None:
        raise ApiError("not_found", "Subject not found", status_code=404)
    return SubgraphOut(
        nodes=[
            MemoryOut.model_validate(memory, from_attributes=True)
            for memory in subgraph.get("nodes", [])
        ],
        edges=[
            MemoryEdgeOut.model_validate(edge)
            for edge in subgraph.get("edges", [])
        ],
    )


@router.get("/views", response_model=list[MemoryViewOut])
def list_memory_views_route(
    project_id: str = Query(...),
    subject_id: str | None = Query(default=None),
    view_type: str | None = Query(default=None),
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_role: str = Depends(get_current_workspace_role),
    workspace_id: str = Depends(get_current_workspace_id),
) -> list[MemoryViewOut]:
    get_project_in_workspace_or_404(db, project_id, workspace_id)
    query = (
        db.query(MemoryView)
        .filter(
            MemoryView.workspace_id == workspace_id,
            MemoryView.project_id == project_id,
        )
        .order_by(MemoryView.updated_at.desc())
    )
    if subject_id:
        query = query.filter(MemoryView.source_subject_id == subject_id)
    if view_type:
        query = query.filter(MemoryView.view_type == view_type)
    views = query.all()
    source_subject_ids = [view.source_subject_id for view in views if view.source_subject_id]
    visible_subject_ids = {
        memory.id
        for memory in _filter_accessible_memories(
            db,
            db.query(Memory)
            .filter(Memory.workspace_id == workspace_id, Memory.id.in_(source_subject_ids))
            .all() if source_subject_ids else [],
            project_id=project_id,
            workspace_id=workspace_id,
            current_user_id=current_user.id,
            workspace_role=workspace_role,
        )
    }
    return [
        _serialize_view_out(view)
        for view in views
        if _view_visible_to_user(
            view,
            visible_memory_ids=visible_subject_ids,
            current_user_id=current_user.id,
        )
    ]


@router.get("/evidences", response_model=list[MemoryEvidenceOut])
def list_project_memory_evidences_route(
    project_id: str = Query(...),
    memory_id: str | None = Query(default=None),
    source_type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_role: str = Depends(get_current_workspace_role),
    workspace_id: str = Depends(get_current_workspace_id),
) -> list[MemoryEvidenceOut]:
    get_project_in_workspace_or_404(db, project_id, workspace_id)

    if memory_id:
        memory = _get_accessible_memory_or_404(
            db,
            memory_id=memory_id,
            workspace_id=workspace_id,
            current_user_id=current_user.id,
            workspace_role=workspace_role,
        )
        if memory.project_id != project_id:
            raise ApiError("not_found", "Memory not found", status_code=404)
        query = (
            db.query(MemoryEvidence)
            .filter(
                MemoryEvidence.workspace_id == workspace_id,
                MemoryEvidence.project_id == project_id,
                MemoryEvidence.memory_id == memory.id,
            )
            .order_by(MemoryEvidence.created_at.desc())
        )
        if source_type:
            query = query.filter(MemoryEvidence.source_type == source_type)
        query = query.limit(limit)
        return [_serialize_evidence_out(evidence) for evidence in query.all()]

    query = (
        db.query(MemoryEvidence)
        .filter(
            MemoryEvidence.workspace_id == workspace_id,
            MemoryEvidence.project_id == project_id,
        )
        .order_by(MemoryEvidence.created_at.desc())
    )
    if source_type:
        query = query.filter(MemoryEvidence.source_type == source_type)
    query = query.limit(limit)
    evidences = query.all()
    memory_ids = list({evidence.memory_id for evidence in evidences if evidence.memory_id})
    accessible_ids = {
        memory.id
        for memory in _filter_accessible_memories(
            db,
            db.query(Memory)
            .filter(Memory.workspace_id == workspace_id, Memory.id.in_(memory_ids))
            .all()
            if memory_ids
            else [],
            project_id=project_id,
            workspace_id=workspace_id,
            current_user_id=current_user.id,
            workspace_role=workspace_role,
        )
    }
    return [
        _serialize_evidence_out(evidence)
        for evidence in evidences
        if evidence.memory_id in accessible_ids
    ]


@router.get("/playbooks", response_model=list[MemoryViewOut])
def list_playbooks_route(
    project_id: str = Query(...),
    subject_id: str | None = Query(default=None),
    query: str | None = Query(default=None),
    health: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_role: str = Depends(get_current_workspace_role),
    workspace_id: str = Depends(get_current_workspace_id),
) -> list[MemoryViewOut]:
    get_project_in_workspace_or_404(db, project_id, workspace_id)
    views = list_project_playbook_views(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        subject_id=subject_id,
        query=query,
        health=health,
        limit=limit,
    )
    source_subject_ids = [view.source_subject_id for view in views if view.source_subject_id]
    visible_subject_ids = {
        memory.id
        for memory in _filter_accessible_memories(
            db,
            db.query(Memory)
            .filter(Memory.workspace_id == workspace_id, Memory.id.in_(source_subject_ids))
            .all() if source_subject_ids else [],
            project_id=project_id,
            workspace_id=workspace_id,
            current_user_id=current_user.id,
            workspace_role=workspace_role,
        )
    }
    return [
        _serialize_view_out(view)
        for view in views
        if _view_visible_to_user(
            view,
            visible_memory_ids=visible_subject_ids,
            current_user_id=current_user.id,
        )
    ]


@router.get("/health", response_model=MemoryHealthOut)
def get_memory_health_route(
    request: Request,
    project_id: str = Query(...),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_role: str = Depends(get_current_workspace_role),
    workspace_id: str = Depends(get_current_workspace_id),
) -> MemoryHealthOut:
    _enforce_memory_read_rate_limit(request, current_user_id=current_user.id)
    get_project_in_workspace_or_404(db, project_id, workspace_id)
    summary = summarize_memory_health(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        limit=limit,
    )
    visible_entries: list[MemoryHealthEntryOut] = []
    memory_entries = [item["memory"] for item in summary["entries"] if isinstance(item.get("memory"), Memory)]
    visible_memory_ids = {
        memory.id
        for memory in _filter_accessible_memories(
            db,
            memory_entries,
            project_id=project_id,
            workspace_id=workspace_id,
            current_user_id=current_user.id,
            workspace_role=workspace_role,
        )
    }
    subject_ids = [
        item["view"].source_subject_id
        for item in summary["entries"]
        if isinstance(item.get("view"), MemoryView) and item["view"].source_subject_id
    ]
    visible_subject_ids = {
        memory.id
        for memory in _filter_accessible_memories(
            db,
            db.query(Memory)
            .filter(Memory.workspace_id == workspace_id, Memory.id.in_(subject_ids))
            .all() if subject_ids else [],
            project_id=project_id,
            workspace_id=workspace_id,
            current_user_id=current_user.id,
            workspace_role=workspace_role,
        )
    }
    for item in summary["entries"]:
        memory = item.get("memory")
        view = item.get("view")
        if isinstance(memory, Memory):
            if memory.id not in visible_memory_ids:
                continue
            visible_entries.append(
                MemoryHealthEntryOut(
                    kind=str(item["kind"]),
                    memory=_serialize_memory_out(memory),
                    reason=str(item["reason"]),
                )
            )
            continue
        if isinstance(view, MemoryView):
            if not _view_visible_to_user(
                view,
                visible_memory_ids=visible_subject_ids,
                current_user_id=current_user.id,
            ):
                continue
            visible_entries.append(
                MemoryHealthEntryOut(
                    kind=str(item["kind"]),
                    view=_serialize_view_out(view),
                    reason=str(item["reason"]),
                )
            )
    return MemoryHealthOut(counts=summary["counts"], entries=visible_entries[:limit])


@router.get("/learning-runs", response_model=list[MemoryLearningRunOut])
def list_memory_learning_runs_route(
    request: Request,
    project_id: str = Query(...),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_role: str = Depends(get_current_workspace_role),
    workspace_id: str = Depends(get_current_workspace_id),
) -> list[MemoryLearningRunOut]:
    _enforce_memory_read_rate_limit(request, current_user_id=current_user.id)
    get_project_in_workspace_or_404(db, project_id, workspace_id)
    return [
        _serialize_learning_run_out(run)
        for run in _filter_visible_learning_runs(
            db,
            list_project_learning_runs(
                db,
                workspace_id=workspace_id,
                project_id=project_id,
                limit=limit,
            ),
            project_id=project_id,
            workspace_id=workspace_id,
            current_user_id=current_user.id,
            workspace_role=workspace_role,
        )
    ]


@router.get("/learning-runs/{learning_run_id}", response_model=MemoryLearningRunOut)
def get_memory_learning_run_route(
    learning_run_id: str,
    request: Request,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_role: str = Depends(get_current_workspace_role),
    workspace_id: str = Depends(get_current_workspace_id),
) -> MemoryLearningRunOut:
    _enforce_memory_read_rate_limit(request, current_user_id=current_user.id)
    run = get_memory_learning_run(
        db,
        workspace_id=workspace_id,
        learning_run_id=learning_run_id,
    )
    if run is None:
        raise ApiError("not_found", "Learning run not found", status_code=404)
    visible_runs = _filter_visible_learning_runs(
        db,
        [run],
        project_id=run.project_id,
        workspace_id=workspace_id,
        current_user_id=current_user.id,
        workspace_role=workspace_role,
    )
    if not visible_runs:
        raise ApiError("not_found", "Learning run not found", status_code=404)
    return _serialize_learning_run_out(run)


@router.post("/outcomes", response_model=MemoryOutcomeOut)
def create_memory_outcome_route(
    payload: MemoryOutcomeCreate,
    request: Request,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_role: str = Depends(get_current_workspace_role),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    __: None = Depends(require_csrf_protection),
) -> MemoryOutcomeOut:
    _enforce_memory_write_rate_limit(request, current_user_id=current_user.id)
    get_project_in_workspace_or_404(db, payload.project_id, workspace_id)
    if payload.conversation_id:
        _verify_conversation_ownership(
            db,
            conversation_id=payload.conversation_id,
            project_id=payload.project_id,
            workspace_id=workspace_id,
            current_user_id=current_user.id,
            workspace_role=workspace_role,
        )
    accessible_memories = _filter_accessible_memories(
        db,
        db.query(Memory)
        .filter(Memory.workspace_id == workspace_id, Memory.id.in_(payload.memory_ids))
        .all() if payload.memory_ids else [],
        project_id=payload.project_id,
        workspace_id=workspace_id,
        current_user_id=current_user.id,
        workspace_role=workspace_role,
    )
    playbook_view = None
    if payload.playbook_view_id:
        playbook_view = (
            db.query(MemoryView)
            .filter(
                MemoryView.workspace_id == workspace_id,
                MemoryView.project_id == payload.project_id,
                MemoryView.id == payload.playbook_view_id,
                MemoryView.view_type == "playbook",
            )
            .first()
        )
        if playbook_view is None:
            raise ApiError("not_found", "Playbook not found", status_code=404)
        source_subject_ids = [playbook_view.source_subject_id] if playbook_view.source_subject_id else []
        visible_subject_ids = {
            memory.id
            for memory in _filter_accessible_memories(
                db,
                db.query(Memory)
                .filter(Memory.workspace_id == workspace_id, Memory.id.in_(source_subject_ids))
                .all() if source_subject_ids else [],
                project_id=payload.project_id,
                workspace_id=workspace_id,
                current_user_id=current_user.id,
                workspace_role=workspace_role,
            )
        }
        if not _view_visible_to_user(
            playbook_view,
            visible_memory_ids=visible_subject_ids,
            current_user_id=current_user.id,
        ):
            raise ApiError("not_found", "Playbook not found", status_code=404)
    outcome = create_memory_outcome(
        db,
        workspace_id=workspace_id,
        project_id=payload.project_id,
        conversation_id=payload.conversation_id,
        message_id=payload.message_id,
        task_id=payload.task_id,
        status=payload.status,
        feedback_source=payload.feedback_source,
        summary=payload.summary,
        root_cause=payload.root_cause,
        tags=payload.tags,
        metadata_json={
            **payload.metadata_json,
            "memory_ids": [memory.id for memory in accessible_memories],
            "playbook_view_id": payload.playbook_view_id,
            "submitted_by": current_user.id,
        },
    )
    apply_memory_outcome(
        db,
        outcome=outcome,
        memory_ids=[memory.id for memory in accessible_memories],
        playbook_view=playbook_view,
    )
    if payload.learning_run_id:
        run = get_memory_learning_run(db, workspace_id=workspace_id, learning_run_id=payload.learning_run_id)
        if run is not None:
            run.outcome_id = outcome.id
            run.status = "completed"
            run.completed_at = datetime.now(timezone.utc)
            run.stages = merge_learning_stages(run.stages, ["reflect", "reuse"])
    refresh_memory_health_signals(
        db,
        workspace_id=workspace_id,
        project_id=payload.project_id,
    )
    write_audit_log(
        db,
        workspace_id=workspace_id,
        actor_user_id=current_user.id,
        action="memory.outcome_created",
        target_type="memory_outcome",
        target_id=outcome.id,
        meta_json={
            "project_id": payload.project_id,
            "status": payload.status,
            "feedback_source": payload.feedback_source,
            "memory_ids": [memory.id for memory in accessible_memories],
            "playbook_view_id": payload.playbook_view_id,
            "learning_run_id": payload.learning_run_id,
        },
    )
    db.commit()
    db.refresh(outcome)
    return _serialize_outcome_out(outcome)


@router.post("/playbooks/{view_id}/feedback", response_model=MemoryOutcomeOut)
def submit_playbook_feedback_route(
    view_id: str,
    payload: PlaybookFeedbackRequest,
    request: Request,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_role: str = Depends(get_current_workspace_role),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    __: None = Depends(require_csrf_protection),
) -> MemoryOutcomeOut:
    _enforce_memory_write_rate_limit(request, current_user_id=current_user.id)
    playbook_view = (
        db.query(MemoryView)
        .filter(
            MemoryView.workspace_id == workspace_id,
            MemoryView.project_id == payload.project_id,
            MemoryView.id == view_id,
            MemoryView.view_type == "playbook",
        )
        .first()
    )
    if playbook_view is None:
        raise ApiError("not_found", "Playbook not found", status_code=404)
    return create_memory_outcome_route(
        MemoryOutcomeCreate(
            project_id=payload.project_id,
            task_id=payload.task_id,
            status=payload.status,
            feedback_source="user",
            summary=f"Playbook feedback for {view_id}",
            root_cause=payload.root_cause,
            tags=payload.tags,
            conversation_id=payload.conversation_id,
            message_id=payload.message_id,
            memory_ids=payload.memory_ids,
            playbook_view_id=view_id,
            learning_run_id=payload.learning_run_id,
            metadata_json=payload.metadata_json,
        ),
        request=request,
        db=db,
        current_user=current_user,
        workspace_role=workspace_role,
        workspace_id=workspace_id,
        _write_guard=None,
        __=None,
    )


@router.post("/backfill", response_model=MemoryBackfillOut)
def backfill_memory_v2_route(
    payload: MemoryBackfillRequest,
    db: Session = Depends(get_db_session),
    _: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    __: None = Depends(require_csrf_protection),
) -> MemoryBackfillOut:
    get_project_in_workspace_or_404(db, payload.project_id, workspace_id)
    status_value, job_id, summary = _trigger_memory_v2_backfill(
        workspace_id=workspace_id,
        project_id=payload.project_id,
        limit=payload.limit,
    )
    return MemoryBackfillOut(
        status=status_value,
        job_id=job_id,
        summary=MemoryBackfillSummaryOut(**summary) if summary else None,
    )


@router.post("", response_model=MemoryOut)
def create_memory(
    payload: MemoryCreate,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_role: str = Depends(get_current_workspace_role),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _: None = Depends(require_csrf_protection),
) -> MemoryOut:
    project = get_project_in_workspace_or_404(db, payload.project_id, workspace_id)
    parent_field_present = "parent_memory_id" in payload.model_fields_set
    if payload.type not in {"permanent", "temporary"}:
        raise ApiError("bad_request", "Invalid memory type", status_code=400)
    if payload.type == "temporary" and not payload.source_conversation_id:
        raise ApiError(
            "bad_request",
            "Temporary memories must be linked to a conversation",
            status_code=400,
        )
    if payload.source_conversation_id:
        _verify_conversation_ownership(
            db,
            conversation_id=payload.source_conversation_id,
            project_id=payload.project_id,
            workspace_id=workspace_id,
            current_user_id=current_user.id,
            workspace_role=workspace_role,
        )
    root_memory, _ = ensure_project_assistant_root(db, project, reparent_orphans=True)
    requested_parent_id = payload.parent_memory_id
    requested_parent: Memory | None = None
    if requested_parent_id:
        requested_parent = _verify_parent_memory(
            db,
            parent_memory_id=requested_parent_id,
            project_id=payload.project_id,
            workspace_id=workspace_id,
            current_user_id=current_user.id,
            workspace_role=workspace_role,
        )
        _assert_supported_primary_parent(requested_parent)
    metadata_input = _strip_parent_binding_fields(payload.metadata_json)
    node_type = normalize_node_type(payload.node_type or metadata_input.get("node_type"), fallback=FACT_NODE_TYPE)
    if node_type == "root":
        raise ApiError("bad_request", "Root memory is system managed", status_code=400)
    if node_type == "subject" and requested_parent and not is_assistant_root_memory(requested_parent):
        raise ApiError("bad_request", "Subject nodes must be attached to the project root", status_code=400)
    resolved_parent_id = requested_parent_id or root_memory.id
    subject_kind = (
        str(payload.subject_kind or metadata_input.get("subject_kind") or "").strip().lower() or None
    )
    if node_type != "subject":
        subject_kind = None
    subject_memory_id = _resolve_subject_memory_id(
        requested_subject_memory_id=payload.subject_memory_id,
        parent=requested_parent,
        node_type=node_type,
    )
    node_status = normalize_node_status(payload.node_status or metadata_input.get("node_status"), fallback=ACTIVE_NODE_STATUS)
    metadata_input.update(
        {
            "node_type": node_type,
            "subject_kind": subject_kind,
            "subject_memory_id": subject_memory_id,
            "node_status": node_status,
        }
    )
    if payload.canonical_key:
        metadata_input["canonical_key"] = payload.canonical_key
    if parent_field_present:
        metadata_input = set_manual_parent_binding(
            metadata_input,
            parent_memory_id=(
                None if resolved_parent_id == root_memory.id else resolved_parent_id
            ),
        )
    normalized_metadata = normalize_memory_metadata(
        content=payload.content,
        category=payload.category,
        memory_type=payload.type,
        metadata=metadata_input,
    )
    _assert_primary_graph_metadata_allowed(normalized_metadata)

    memory = Memory(
        workspace_id=workspace_id,
        project_id=payload.project_id,
        content=payload.content,
        category=payload.category,
        type=payload.type,
        node_type=node_type,
        subject_kind=subject_kind,
        source_conversation_id=payload.source_conversation_id,
        parent_memory_id=resolved_parent_id,
        subject_memory_id=subject_memory_id,
        node_status=node_status,
        canonical_key=payload.canonical_key or str(normalized_metadata.get("canonical_key") or "").strip() or None,
        lineage_key=None,
        position_x=payload.position_x,
        position_y=payload.position_y,
        metadata_json=normalized_metadata,
    )
    apply_temporal_defaults(memory)
    db.add(memory)
    db.flush()
    _normalize_lineage_metadata(memory)
    db.commit()
    _bump_graph_revision(workspace_id=workspace_id, project_id=payload.project_id)
    db.refresh(memory)
    _sync_memory_embedding(memory, db)
    if memory.type == "permanent":
        if _sync_project_related_edges(db, workspace_id=workspace_id, project_id=memory.project_id):
            db.commit()
            _bump_graph_revision(workspace_id=workspace_id, project_id=memory.project_id)
    if memory.type == "permanent":
        _trigger_memory_compaction(workspace_id, memory.project_id)
    return MemoryOut.model_validate(memory, from_attributes=True)


@router.get("/{memory_id}", response_model=MemoryDetailOut)
def get_memory_detail(
    memory_id: str,
    request: Request,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_role: str = Depends(get_current_workspace_role),
    workspace_id: str = Depends(get_current_workspace_id),
) -> MemoryDetailOut:
    _enforce_memory_read_rate_limit(request, current_user_id=current_user.id)
    memory = _get_accessible_memory_or_404(
        db,
        memory_id=memory_id,
        workspace_id=workspace_id,
        current_user_id=current_user.id,
        workspace_role=workspace_role,
    )

    edges = (
        db.query(MemoryEdge)
        .filter(
            (MemoryEdge.source_memory_id == memory_id) | (MemoryEdge.target_memory_id == memory_id)
        )
        .all()
    )

    connected_memory_ids = {
        edge.source_memory_id for edge in edges
    } | {
        edge.target_memory_id for edge in edges
    }
    connected_memories = (
        db.query(Memory)
        .filter(Memory.workspace_id == workspace_id, Memory.id.in_(connected_memory_ids))
        .all()
        if connected_memory_ids
        else []
    )
    visible_connected_ids = {
        item.id
        for item in _filter_accessible_memories(
            db,
            connected_memories,
            project_id=memory.project_id,
            workspace_id=workspace_id,
            current_user_id=current_user.id,
            workspace_role=workspace_role,
        )
    }
    edges = [
        edge
        for edge in edges
        if edge.source_memory_id in visible_connected_ids and edge.target_memory_id in visible_connected_ids
    ]

    files = (
        db.query(MemoryFile, DataItem)
        .join(DataItem, DataItem.id == MemoryFile.data_item_id)
        .join(Dataset, Dataset.id == DataItem.dataset_id)
        .join(Project, Project.id == Dataset.project_id)
        .filter(
            MemoryFile.memory_id == memory_id,
            DataItem.deleted_at.is_(None),
            Dataset.deleted_at.is_(None),
            Project.deleted_at.is_(None),
            Project.workspace_id == workspace_id,
        )
        .all()
    )

    lineage_memories: list[Memory] = []
    lineage_edges: list[MemoryEdge] = []
    if is_fact_memory(memory) and get_lineage_key(memory):
        lineage_memories = (
            db.query(Memory)
            .filter(
                Memory.workspace_id == workspace_id,
                Memory.project_id == memory.project_id,
                Memory.lineage_key == get_lineage_key(memory),
            )
            .all()
        )
        lineage_memories = _filter_accessible_memories(
            db,
            lineage_memories,
            project_id=memory.project_id,
            workspace_id=workspace_id,
            current_user_id=current_user.id,
            workspace_role=workspace_role,
        )
        lineage_ids = [item.id for item in lineage_memories]
        if lineage_ids:
            lineage_edges = (
                db.query(MemoryEdge)
                .filter(
                    MemoryEdge.edge_type.in_([SUPERSEDES_EDGE_TYPE, CONFLICT_EDGE_TYPE]),
                    MemoryEdge.source_memory_id.in_(lineage_ids),
                    MemoryEdge.target_memory_id.in_(lineage_ids),
                )
                .all()
            )

    result = MemoryDetailOut.model_validate(memory, from_attributes=True)
    result.edges = [_serialize_edge_out(e) for e in edges]
    result.files = [
        MemoryFileOut(
            id=memory_file.id,
            memory_id=memory_file.memory_id,
            data_item_id=memory_file.data_item_id,
            filename=data_item.filename,
            media_type=data_item.media_type,
            created_at=memory_file.created_at,
        )
        for memory_file, data_item in files
        if _is_completed_data_item(data_item)
    ]
    result.lineage_nodes = [
        _serialize_memory_out(item)
        for item in lineage_memories
    ]
    result.lineage_edges = [_serialize_edge_out(edge) for edge in lineage_edges]
    result.evidences = [
        _serialize_evidence_out(evidence)
        for evidence in list_memory_evidences(db, memory_id=memory.id)
    ]
    result.episodes = [
        _serialize_episode_out(episode)
        for episode in list_memory_episodes(db, memory_id=memory.id)
    ]
    visible_ids = {
        item.id
        for item in _filter_accessible_memories(
            db,
            [memory, *lineage_memories],
            project_id=memory.project_id,
            workspace_id=workspace_id,
            current_user_id=current_user.id,
            workspace_role=workspace_role,
        )
    }
    result.views = [
        _serialize_view_out(view)
        for view in list_memory_views_for_memory(db, memory=memory)
        if _view_visible_to_user(view, visible_memory_ids=visible_ids, current_user_id=current_user.id)
    ]
    result.timeline_events = [
        _serialize_memory_out(item)
        for item in _filter_accessible_memories(
            db,
            list_memory_timeline_events(db, memory=memory),
            project_id=memory.project_id,
            workspace_id=workspace_id,
            current_user_id=current_user.id,
            workspace_role=workspace_role,
        )
    ]
    result.write_history = [
        _serialize_write_item_out(item)
        for item in list_memory_write_history(db, memory_id=memory.id)
    ]
    result.learning_history = [
        _serialize_learning_run_out(run)
        for run in list_learning_runs_for_memory(
            db,
            memory_id=memory.id,
            workspace_id=memory.workspace_id,
            project_id=memory.project_id,
        )
    ]
    return result


@router.get("/{memory_id}/evidences", response_model=list[MemoryEvidenceOut])
def get_memory_evidences_route(
    memory_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_role: str = Depends(get_current_workspace_role),
    workspace_id: str = Depends(get_current_workspace_id),
) -> list[MemoryEvidenceOut]:
    memory = _get_accessible_memory_or_404(
        db,
        memory_id=memory_id,
        workspace_id=workspace_id,
        current_user_id=current_user.id,
        workspace_role=workspace_role,
    )
    return [
        _serialize_evidence_out(evidence)
        for evidence in list_memory_evidences(db, memory_id=memory.id)
    ]


@router.post("/{memory_id}/subgraph", response_model=SubgraphOut)
def get_memory_subgraph_route(
    memory_id: str,
    payload: SubgraphRequest,
    request: Request,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_role: str = Depends(get_current_workspace_role),
    workspace_id: str = Depends(get_current_workspace_id),
) -> SubgraphOut:
    _enforce_memory_read_rate_limit(request, current_user_id=current_user.id)
    memory = _get_accessible_memory_or_404(
        db,
        memory_id=memory_id,
        workspace_id=workspace_id,
        current_user_id=current_user.id,
        workspace_role=workspace_role,
    )
    return _load_memory_subgraph(
        db,
        memory=memory,
        depth=payload.depth,
        edge_types=payload.edge_types,
        current_user_id=current_user.id,
        workspace_role=workspace_role,
        workspace_id=workspace_id,
    )




@router.get("/{memory_id}/available-files", response_model=list[MemoryFileCandidateOut])
def list_available_memory_files(
    memory_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_role: str = Depends(get_current_workspace_role),
    workspace_id: str = Depends(get_current_workspace_id),
) -> list[MemoryFileCandidateOut]:
    memory = _get_accessible_memory_or_404(
        db,
        memory_id=memory_id,
        workspace_id=workspace_id,
        current_user_id=current_user.id,
        workspace_role=workspace_role,
    )
    if is_assistant_root_memory(memory):
        raise ApiError("bad_request", "Assistant root memory cannot attach files", status_code=400)
    if is_category_path_memory(memory):
        raise ApiError("bad_request", "Category path nodes cannot attach files", status_code=400)

    attached_item_ids = {
        item_id
        for item_id, in db.query(MemoryFile.data_item_id).filter(MemoryFile.memory_id == memory.id).all()
    }

    items = (
        db.query(DataItem)
        .join(Dataset, Dataset.id == DataItem.dataset_id)
        .join(Project, Project.id == Dataset.project_id)
        .filter(
            Project.id == memory.project_id,
            Project.workspace_id == workspace_id,
            Project.deleted_at.is_(None),
            Dataset.deleted_at.is_(None),
            DataItem.deleted_at.is_(None),
        )
        .order_by(DataItem.created_at.desc())
        .all()
    )

    return [
        MemoryFileCandidateOut(
            id=item.id,
            dataset_id=item.dataset_id,
            filename=item.filename,
            media_type=item.media_type,
            created_at=item.created_at,
        )
        for item in items
        if item.id not in attached_item_ids and _is_completed_data_item(item)
    ][:100]


@router.post("/{memory_id}/files", response_model=MemoryFileOut)
def attach_memory_file(
    memory_id: str,
    payload: MemoryFileAttachRequest,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_role: str = Depends(get_current_workspace_role),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _: None = Depends(require_csrf_protection),
) -> MemoryFileOut:
    memory = _get_accessible_memory_or_404(
        db,
        memory_id=memory_id,
        workspace_id=workspace_id,
        current_user_id=current_user.id,
        workspace_role=workspace_role,
    )
    if is_assistant_root_memory(memory):
        raise ApiError("bad_request", "Assistant root memory cannot attach files", status_code=400)
    if is_category_path_memory(memory):
        raise ApiError("bad_request", "Category path nodes cannot attach files", status_code=400)
    data_item = get_data_item_in_workspace(db, data_item_id=payload.data_item_id, workspace_id=workspace_id)
    if not data_item or not _is_completed_data_item(data_item):
        raise ApiError("not_found", "Data item not found", status_code=404)

    dataset = (
        db.query(Dataset)
        .join(Project, Project.id == Dataset.project_id)
        .filter(
            Dataset.id == data_item.dataset_id,
            Project.workspace_id == workspace_id,
            Project.deleted_at.is_(None),
            Dataset.deleted_at.is_(None),
        )
        .first()
    )
    if not dataset or dataset.project_id != memory.project_id:
        raise ApiError("bad_request", "Cannot attach files across projects", status_code=400)

    existing = (
        db.query(MemoryFile)
        .filter(MemoryFile.memory_id == memory.id, MemoryFile.data_item_id == data_item.id)
        .first()
    )
    if existing:
        return MemoryFileOut(
            id=existing.id,
            memory_id=existing.memory_id,
            data_item_id=existing.data_item_id,
            filename=data_item.filename,
            media_type=data_item.media_type,
            created_at=existing.created_at,
        )

    memory_file = MemoryFile(memory_id=memory.id, data_item_id=data_item.id)
    db.add(memory_file)
    ensure_memory_file_evidence(
        db,
        memory=memory,
        data_item=data_item,
        metadata_json={"link_source": "manual_attach"},
    )
    db.commit()
    _bump_graph_revision(workspace_id=workspace_id, project_id=memory.project_id)
    db.refresh(memory_file)
    return MemoryFileOut(
        id=memory_file.id,
        memory_id=memory_file.memory_id,
        data_item_id=memory_file.data_item_id,
        filename=data_item.filename,
        media_type=data_item.media_type,
        created_at=memory_file.created_at,
    )


@router.delete("/files/{memory_file_id}")
def delete_memory_file(
    memory_file_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_role: str = Depends(get_current_workspace_role),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _: None = Depends(require_csrf_protection),
) -> Response:
    memory_file = (
        db.query(MemoryFile, Memory)
        .join(Memory, Memory.id == MemoryFile.memory_id)
        .filter(MemoryFile.id == memory_file_id, Memory.workspace_id == workspace_id)
        .first()
    )
    if not memory_file:
        raise ApiError("not_found", "Memory file not found", status_code=404)

    _, memory = memory_file
    _get_accessible_memory_or_404(
        db,
        memory_id=memory.id,
        workspace_id=workspace_id,
        current_user_id=current_user.id,
        workspace_role=workspace_role,
    )

    db.delete(memory_file[0])
    db.commit()
    _bump_graph_revision(workspace_id=workspace_id, project_id=memory.project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/{memory_id}", response_model=MemoryOut)
def update_memory(
    memory_id: str,
    payload: MemoryUpdate,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_role: str = Depends(get_current_workspace_role),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _: None = Depends(require_csrf_protection),
) -> MemoryOut:
    memory = _get_accessible_memory_or_404(
        db,
        memory_id=memory_id,
        workspace_id=workspace_id,
        current_user_id=current_user.id,
        workspace_role=workspace_role,
    )
    if is_assistant_root_memory(memory):
        raise ApiError("bad_request", "Assistant root memory is system managed", status_code=400)
    if is_category_path_memory(memory):
        raise ApiError("bad_request", "Category path nodes are system managed", status_code=400)
    if is_summary_memory(memory):
        raise ApiError("bad_request", "Summary nodes are derived views and cannot be edited directly", status_code=400)
    if (
        is_fact_memory(memory)
        and memory.type == "permanent"
        and is_active_memory(memory)
        and payload.model_fields_set.intersection({"content", "category"})
    ):
        raise ApiError(
            "bad_request",
            "Active permanent facts are versioned. Use /api/v1/memory/{id}/supersede to revise content or category.",
            status_code=400,
        )

    parent_field_present = "parent_memory_id" in payload.model_fields_set
    project = get_project_in_workspace_or_404(db, memory.project_id, workspace_id)
    root_memory, _ = ensure_project_assistant_root(db, project, reparent_orphans=False)
    current_parent = db.get(Memory, memory.parent_memory_id) if memory.parent_memory_id else None

    if payload.content is not None:
        memory.content = payload.content
    if payload.category is not None:
        memory.category = payload.category
    metadata = dict(memory.metadata_json or {})
    if payload.metadata_json is not None:
        metadata.update(_strip_parent_binding_fields(payload.metadata_json))
    node_type = normalize_node_type(payload.node_type or metadata.get("node_type") or memory.node_type, fallback=FACT_NODE_TYPE)
    if node_type == "root":
        raise ApiError("bad_request", "Root memory is system managed", status_code=400)
    subject_kind = (
        str(payload.subject_kind or metadata.get("subject_kind") or memory.subject_kind or "").strip().lower() or None
    )
    if node_type != "subject":
        subject_kind = None
    parent_memory = current_parent
    if parent_field_present:
        requested_parent_id = payload.parent_memory_id
        if requested_parent_id:
            if requested_parent_id == memory.id:
                raise ApiError("bad_request", "A memory cannot parent itself", status_code=400)
            parent_memory = _verify_parent_memory(
                db,
                parent_memory_id=requested_parent_id,
                project_id=memory.project_id,
                workspace_id=workspace_id,
                current_user_id=current_user.id,
                workspace_role=workspace_role,
            )
            _assert_supported_primary_parent(parent_memory)
            if node_type == "subject" and not is_assistant_root_memory(parent_memory):
                raise ApiError("bad_request", "Subject nodes must be attached to the project root", status_code=400)
            _assert_valid_parent_assignment(
                db,
                memory_id=memory.id,
                candidate_parent_id=parent_memory.id,
                workspace_id=workspace_id,
            )
            memory.parent_memory_id = parent_memory.id
            metadata = set_manual_parent_binding(metadata, parent_memory_id=parent_memory.id)
        else:
            memory.parent_memory_id = root_memory.id
            parent_memory = root_memory
            metadata = set_manual_parent_binding(metadata, parent_memory_id=None)
    elif node_type == "subject" and memory.parent_memory_id != root_memory.id:
        memory.parent_memory_id = root_memory.id
        parent_memory = root_memory
    subject_memory_id = _resolve_subject_memory_id(
        requested_subject_memory_id=payload.subject_memory_id,
        parent=parent_memory,
        existing_subject_memory_id=memory.subject_memory_id,
        node_type=node_type,
    )
    node_status = normalize_node_status(payload.node_status or metadata.get("node_status") or memory.node_status, fallback=ACTIVE_NODE_STATUS)
    if payload.position_x is not None:
        memory.position_x = payload.position_x
    if payload.position_y is not None:
        memory.position_y = payload.position_y
    memory.node_type = node_type
    memory.subject_kind = subject_kind
    memory.subject_memory_id = subject_memory_id
    memory.node_status = node_status
    if is_private_memory(memory):
        metadata = build_private_memory_metadata(
            metadata,
            owner_user_id=(memory.metadata_json or {}).get("owner_user_id"),
        )
    metadata.update(
        {
            "node_type": node_type,
            "subject_kind": subject_kind,
            "subject_memory_id": subject_memory_id,
            "node_status": node_status,
        }
    )
    if memory.lineage_key:
        metadata["lineage_key"] = memory.lineage_key
    if payload.canonical_key:
        metadata["canonical_key"] = payload.canonical_key
    memory.metadata_json = normalize_memory_metadata(
        content=memory.content,
        category=memory.category,
        memory_type=memory.type,
        metadata=metadata,
    )
    _assert_primary_graph_metadata_allowed(memory.metadata_json)
    memory.canonical_key = (
        payload.canonical_key
        or str(memory.metadata_json.get("canonical_key") or "").strip()
        or memory.canonical_key
    )
    _normalize_lineage_metadata(memory)
    memory.updated_at = datetime.now(timezone.utc)

    db.commit()
    _bump_graph_revision(workspace_id=workspace_id, project_id=memory.project_id)
    db.refresh(memory)
    _sync_memory_embedding(memory, db)
    if memory.type == "permanent":
        if _sync_project_related_edges(db, workspace_id=workspace_id, project_id=memory.project_id):
            db.commit()
            _bump_graph_revision(workspace_id=workspace_id, project_id=memory.project_id)
    if memory.type == "permanent":
        _trigger_memory_compaction(workspace_id, memory.project_id)
    return MemoryOut.model_validate(memory, from_attributes=True)


@router.post("/{memory_id}/supersede", response_model=MemoryOut)
def supersede_memory(
    memory_id: str,
    payload: MemorySupersedeRequest,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_role: str = Depends(get_current_workspace_role),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _: None = Depends(require_csrf_protection),
) -> MemoryOut:
    memory = _get_accessible_memory_or_404(
        db,
        memory_id=memory_id,
        workspace_id=workspace_id,
        current_user_id=current_user.id,
        workspace_role=workspace_role,
    )
    if not is_fact_memory(memory) or memory.type != "permanent":
        raise ApiError("bad_request", "Only permanent fact memories can be superseded", status_code=400)
    if not is_active_memory(memory):
        raise ApiError("bad_request", "Only active fact memories can be superseded", status_code=400)

    successor = asyncio.run(
        create_fact_successor(
            db,
            predecessor=memory,
            content=payload.content,
            category=payload.category,
            reason=payload.reason or "manual_supersede",
        )
    )
    db.commit()
    _bump_graph_revision(workspace_id=workspace_id, project_id=memory.project_id)
    db.refresh(successor)
    if _sync_project_related_edges(db, workspace_id=workspace_id, project_id=memory.project_id):
        db.commit()
        _bump_graph_revision(workspace_id=workspace_id, project_id=memory.project_id)
    _trigger_memory_compaction(workspace_id, memory.project_id)
    return MemoryOut.model_validate(successor, from_attributes=True)


@router.delete("/{memory_id}")
def delete_memory(
    memory_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_role: str = Depends(get_current_workspace_role),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _: None = Depends(require_csrf_protection),
) -> Response:
    memory = _get_accessible_memory_or_404(
        db,
        memory_id=memory_id,
        workspace_id=workspace_id,
        current_user_id=current_user.id,
        workspace_role=workspace_role,
    )
    if is_assistant_root_memory(memory):
        raise ApiError("bad_request", "Assistant root memory cannot be deleted", status_code=400)
    if is_category_path_memory(memory):
        raise ApiError("bad_request", "Category path nodes are system managed", status_code=400)

    project = get_project_in_workspace_or_404(db, memory.project_id, workspace_id)
    root_memory, _ = ensure_project_assistant_root(db, project, reparent_orphans=False)
    replacement_parent_id = memory.parent_memory_id or (root_memory.id if root_memory.id != memory.id else None)
    children = (
        db.query(Memory)
        .filter(
            Memory.project_id == memory.project_id,
            Memory.workspace_id == workspace_id,
            Memory.parent_memory_id == memory.id,
        )
        .all()
    )
    for child in children:
        child.parent_memory_id = replacement_parent_id
        if has_manual_parent_binding(child):
            child.metadata_json = normalize_memory_metadata(
                content=child.content,
                category=child.category,
                memory_type=child.type,
                metadata=set_manual_parent_binding(
                    dict(child.metadata_json or {}),
                    parent_memory_id=(
                        None
                        if not replacement_parent_id or replacement_parent_id == root_memory.id
                        else replacement_parent_id
                    ),
                ),
            )
        child.updated_at = datetime.now(timezone.utc)

    _delete_memory_embeddings(db, memory.id)
    db.delete(memory)
    db.flush()
    _sync_project_related_edges(db, workspace_id=workspace_id, project_id=memory.project_id)
    db.commit()
    _bump_graph_revision(workspace_id=workspace_id, project_id=memory.project_id)
    _trigger_memory_compaction(workspace_id, memory.project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{memory_id}/promote", response_model=MemoryOut)
def promote_memory(
    memory_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_role: str = Depends(get_current_workspace_role),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _: None = Depends(require_csrf_protection),
) -> MemoryOut:
    memory = _get_accessible_memory_or_404(
        db,
        memory_id=memory_id,
        workspace_id=workspace_id,
        current_user_id=current_user.id,
        workspace_role=workspace_role,
    )

    if memory.type != "temporary":
        raise ApiError("bad_request", "Only temporary memories can be promoted", status_code=400)

    owner_user_id: str | None = None
    if memory.source_conversation_id:
        conversation = _verify_conversation_ownership(
            db,
            conversation_id=memory.source_conversation_id,
            project_id=memory.project_id,
            workspace_id=workspace_id,
            current_user_id=current_user.id,
            workspace_role=workspace_role,
        )
        owner_user_id = conversation.created_by

    memory.type = "permanent"
    metadata = dict(memory.metadata_json or {})
    metadata["promoted_by"] = "user"
    memory.metadata_json = normalize_memory_metadata(
        content=memory.content,
        category=memory.category,
        memory_type="permanent",
        metadata=build_private_memory_metadata(metadata, owner_user_id=owner_user_id),
    )
    memory.source_conversation_id = None
    if memory.parent_memory_id is None:
        project = get_project_in_workspace_or_404(db, memory.project_id, workspace_id)
        root_memory, _ = ensure_project_assistant_root(db, project, reparent_orphans=False)
        memory.parent_memory_id = root_memory.id
    memory.updated_at = datetime.now(timezone.utc)
    _normalize_lineage_metadata(memory)
    db.commit()
    _bump_graph_revision(workspace_id=workspace_id, project_id=memory.project_id)
    db.refresh(memory)
    _sync_memory_embedding(memory, db)
    if _sync_project_related_edges(db, workspace_id=workspace_id, project_id=memory.project_id):
        db.commit()
        _bump_graph_revision(workspace_id=workspace_id, project_id=memory.project_id)
    _trigger_memory_compaction(workspace_id, memory.project_id)
    return MemoryOut.model_validate(memory, from_attributes=True)


@router.post("/search/explain", response_model=MemoryExplainOut)
async def explain_memory_search(
    payload: MemoryExplainRequest,
    request: Request,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_role: str = Depends(get_current_workspace_role),
    workspace_id: str = Depends(get_current_workspace_id),
) -> MemoryExplainOut:
    _enforce_memory_read_rate_limit(request, current_user_id=current_user.id)
    project = get_project_in_workspace_or_404(db, payload.project_id, workspace_id)
    root_memory, root_changed = ensure_project_assistant_root(db, project, reparent_orphans=False)
    if root_changed:
        db.commit()
        _bump_graph_revision(workspace_id=workspace_id, project_id=payload.project_id)

    project_conversation = None
    if payload.conversation_id:
        project_conversation = _verify_conversation_ownership(
            db,
            conversation_id=payload.conversation_id,
            project_id=payload.project_id,
            workspace_id=workspace_id,
            current_user_id=current_user.id,
            workspace_role=workspace_role,
        )
    else:
        project_conversation = _resolve_latest_visible_project_conversation(
            db,
            workspace_id=workspace_id,
            project_id=payload.project_id,
            current_user_id=current_user.id,
            workspace_role=workspace_role,
        )

    try:
        explained = await explain_project_memory_hits_v2(
            db,
            workspace_id=workspace_id,
            project_id=payload.project_id,
            conversation_id=project_conversation.id if project_conversation else None,
            conversation_created_by=(
                project_conversation.created_by if project_conversation else current_user.id
            ),
            query=payload.query,
            top_k=payload.top_k,
            semantic_search_fn=search_similar,
        )
    except Exception:  # noqa: BLE001
        explained = {"hits": [], "trace": {}}

    raw_hits = explained.get("hits") if isinstance(explained, dict) else []
    trace = explained.get("trace") if isinstance(explained, dict) else {}
    if not isinstance(raw_hits, list):
        raw_hits = []
    if not isinstance(trace, dict):
        trace = {}

    hits = _materialize_memory_search_hits(
        db,
        workspace_id=workspace_id,
        project_id=payload.project_id,
        results=raw_hits,
        category=None,
        memory_type=None,
        root_memory_id=root_memory.id,
        current_user_id=current_user.id,
        workspace_role=workspace_role,
    )[: payload.top_k]

    suppressed_ids = [
        str(memory_id).strip()
        for memory_id in trace.get("suppressed_memory_ids", [])
        if isinstance(memory_id, str) and str(memory_id).strip()
    ]
    suppressed_memories = _filter_accessible_memories(
        db,
        (
            db.query(Memory)
            .filter(Memory.workspace_id == workspace_id, Memory.id.in_(suppressed_ids))
            .all()
            if suppressed_ids
            else []
        ),
        project_id=payload.project_id,
        workspace_id=workspace_id,
        current_user_id=current_user.id,
        workspace_role=workspace_role,
    )
    subgraph = None
    primary_subject_id = str(trace.get("primary_subject_id") or "").strip()
    if payload.include_subgraph and primary_subject_id and project_conversation is not None:
        try:
            subject_subgraph = await expand_subject_subgraph(
                db,
                workspace_id=workspace_id,
                project_id=payload.project_id,
                conversation_id=project_conversation.id,
                conversation_created_by=project_conversation.created_by,
                subject_id=primary_subject_id,
                query=payload.query,
                depth=2,
                edge_types=["parent", "related", "manual", "prerequisite", "evidence"],
                semantic_search_fn=search_similar,
            )
            if subject_subgraph is not None:
                subgraph = SubgraphOut(
                    nodes=[_serialize_memory_out(memory) for memory in subject_subgraph.get("nodes", [])],
                    edges=[
                        MemoryEdgeOut.model_validate(edge)
                        if isinstance(edge, MemoryEdgeOut)
                        else MemoryEdgeOut(**edge)
                        for edge in subject_subgraph.get("edges", [])
                    ],
                )
        except Exception:  # noqa: BLE001
            subgraph = None
    if payload.include_subgraph and subgraph is None and hits:
        primary_memory = next((hit.memory for hit in hits if hit.memory is not None), None)
        if primary_memory is not None:
            try:
                memory_record = _get_accessible_memory_or_404(
                    db,
                    memory_id=primary_memory.id,
                    workspace_id=workspace_id,
                    current_user_id=current_user.id,
                    workspace_role=workspace_role,
                )
                subgraph = _load_memory_subgraph(
                    db,
                    memory=memory_record,
                    depth=2,
                    edge_types=["parent", "related", "manual", "prerequisite", "evidence"],
                    current_user_id=current_user.id,
                    workspace_role=workspace_role,
                    workspace_id=workspace_id,
                )
            except ApiError:
                subgraph = None

    return MemoryExplainOut(
        hits=hits,
        trace=trace,
        suppressed_candidates=[_serialize_memory_out(memory) for memory in suppressed_memories[: payload.top_k]],
        subgraph=subgraph,
    )


@router.post("/search", response_model=list[MemorySearchHit])
async def search_memory(
    payload: MemorySearchRequest,
    request: Request,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_role: str = Depends(get_current_workspace_role),
    workspace_id: str = Depends(get_current_workspace_id),
) -> list[MemorySearchHit]:
    _enforce_memory_read_rate_limit(request, current_user_id=current_user.id)
    project = get_project_in_workspace_or_404(db, payload.project_id, workspace_id)
    root_memory, root_changed = ensure_project_assistant_root(db, project, reparent_orphans=False)
    if root_changed:
        db.commit()
        _bump_graph_revision(workspace_id=workspace_id, project_id=payload.project_id)

    try:
        project_conversation = _resolve_latest_visible_project_conversation(
            db,
            workspace_id=workspace_id,
            project_id=payload.project_id,
            current_user_id=current_user.id,
            workspace_role=workspace_role,
        )
        results = await search_project_memory_hits_v2(
            db,
            workspace_id=workspace_id,
            project_id=payload.project_id,
            conversation_id=project_conversation.id if project_conversation else None,
            conversation_created_by=(
                project_conversation.created_by if project_conversation else current_user.id
            ),
            query=payload.query,
            top_k=payload.top_k,
            semantic_search_fn=search_similar,
        )
    except Exception:  # noqa: BLE001
        results = []
    output = _materialize_memory_search_hits(
        db,
        workspace_id=workspace_id,
        project_id=payload.project_id,
        results=results,
        category=payload.category,
        memory_type=payload.type,
        root_memory_id=root_memory.id,
        current_user_id=current_user.id,
        workspace_role=workspace_role,
    )
    return output[: payload.top_k]


@router.post("/edges", response_model=MemoryEdgeOut)
def create_edge(
    payload: MemoryEdgeCreate,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_role: str = Depends(get_current_workspace_role),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _: None = Depends(require_csrf_protection),
) -> MemoryEdgeOut:
    if payload.edge_type in VERSION_EDGE_TYPES:
        raise ApiError(
            "bad_request",
            "supersedes/conflict edges are system managed and cannot be created manually",
            status_code=400,
        )
    # Verify both memories belong to the same workspace
    source = _get_accessible_memory_or_404(
        db,
        memory_id=payload.source_memory_id,
        workspace_id=workspace_id,
        current_user_id=current_user.id,
        workspace_role=workspace_role,
    )
    target = _get_accessible_memory_or_404(
        db,
        memory_id=payload.target_memory_id,
        workspace_id=workspace_id,
        current_user_id=current_user.id,
        workspace_role=workspace_role,
    )
    if not source or not target:
        raise ApiError("not_found", "Source or target memory not found", status_code=404)
    if source.project_id != target.project_id:
        raise ApiError("bad_request", "Cannot connect memories across projects", status_code=400)
    if source.id == target.id:
        raise ApiError("bad_request", "Cannot connect a memory to itself", status_code=400)
    if is_assistant_root_memory(source) or is_assistant_root_memory(target):
        raise ApiError("bad_request", "Assistant root memory cannot create manual edges", status_code=400)

    # Check for duplicate
    existing = (
        db.query(MemoryEdge)
        .filter(
            MemoryEdge.edge_type.in_(["manual", RELATED_EDGE_TYPE]),
            (
                (MemoryEdge.source_memory_id == payload.source_memory_id)
                & (MemoryEdge.target_memory_id == payload.target_memory_id)
            )
            | (
                (MemoryEdge.source_memory_id == payload.target_memory_id)
                & (MemoryEdge.target_memory_id == payload.source_memory_id)
            )
        )
        .first()
    )
    if existing:
        if existing.edge_type == "manual":
            return MemoryEdgeOut.model_validate(existing, from_attributes=True)
        if existing.edge_type == RELATED_EDGE_TYPE:
            existing.edge_type = "manual"
            existing.strength = payload.strength
            source.metadata_json = normalize_memory_metadata(
                content=source.content,
                category=source.category,
                memory_type=source.type,
                metadata=remove_related_edge_exclusion(
                    dict(source.metadata_json or {}),
                    memory_id=target.id,
                ),
            )
            target.metadata_json = normalize_memory_metadata(
                content=target.content,
                category=target.category,
                memory_type=target.type,
                metadata=remove_related_edge_exclusion(
                    dict(target.metadata_json or {}),
                    memory_id=source.id,
                ),
            )
            db.commit()
            _bump_graph_revision(workspace_id=workspace_id, project_id=source.project_id)
            db.refresh(existing)
            return MemoryEdgeOut.model_validate(existing, from_attributes=True)
        raise ApiError("conflict", "Edge already exists between these memories", status_code=409)

    edge = MemoryEdge(
        source_memory_id=payload.source_memory_id,
        target_memory_id=payload.target_memory_id,
        edge_type="manual",
        strength=payload.strength,
    )
    source.metadata_json = normalize_memory_metadata(
        content=source.content,
        category=source.category,
        memory_type=source.type,
        metadata=remove_related_edge_exclusion(
            dict(source.metadata_json or {}),
            memory_id=target.id,
        ),
    )
    target.metadata_json = normalize_memory_metadata(
        content=target.content,
        category=target.category,
        memory_type=target.type,
        metadata=remove_related_edge_exclusion(
            dict(target.metadata_json or {}),
            memory_id=source.id,
        ),
    )
    db.add(edge)
    db.commit()
    _bump_graph_revision(workspace_id=workspace_id, project_id=source.project_id)
    db.refresh(edge)
    return MemoryEdgeOut.model_validate(edge, from_attributes=True)


@router.delete("/edges/{edge_id}")
def delete_edge(
    edge_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_role: str = Depends(get_current_workspace_role),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _: None = Depends(require_csrf_protection),
) -> Response:
    # Verify the edge belongs to a memory in the user's workspace
    edge = db.query(MemoryEdge).filter(MemoryEdge.id == edge_id).first()
    if not edge:
        raise ApiError("not_found", "Edge not found", status_code=404)

    if edge.edge_type not in {"manual", RELATED_EDGE_TYPE}:
        raise ApiError("bad_request", "Only lateral relations can be removed here", status_code=400)

    source = _get_accessible_memory_or_404(
        db,
        memory_id=edge.source_memory_id,
        workspace_id=workspace_id,
        current_user_id=current_user.id,
        workspace_role=workspace_role,
    )
    target = _get_accessible_memory_or_404(
        db,
        memory_id=edge.target_memory_id,
        workspace_id=workspace_id,
        current_user_id=current_user.id,
        workspace_role=workspace_role,
    )

    source.metadata_json = normalize_memory_metadata(
        content=source.content,
        category=source.category,
        memory_type=source.type,
        metadata=add_related_edge_exclusion(
            dict(source.metadata_json or {}),
            memory_id=target.id,
        ),
    )
    target.metadata_json = normalize_memory_metadata(
        content=target.content,
        category=target.category,
        memory_type=target.type,
        metadata=add_related_edge_exclusion(
            dict(target.metadata_json or {}),
            memory_id=source.id,
        ),
    )
    db.delete(edge)
    db.commit()
    _bump_graph_revision(workspace_id=workspace_id, project_id=source.project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
