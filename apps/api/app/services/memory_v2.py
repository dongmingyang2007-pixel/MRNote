from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
from typing import Any
from uuid import uuid4

from sqlalchemy import bindparam, text as sql_text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    DataItem,
    Memory,
    MemoryEpisode,
    MemoryEvidence,
    MemoryLearningRun,
    MemoryOutcome,
    MemoryView,
    MemoryWriteItem,
    MemoryWriteRun,
)
from app.services.dashscope_client import UpstreamServiceError
from app.services.dashscope_http import DASHSCOPE_RERANK_URL, dashscope_headers, get_client
from app.services.memory_metadata import (
    MEMORY_KIND_EPISODIC,
    MEMORY_KIND_GOAL,
    MEMORY_KIND_PREFERENCE,
    MEMORY_KIND_PROFILE,
    get_memory_kind,
    get_memory_metadata,
    get_subject_memory_id,
    is_active_memory,
)
from app.services.memory_visibility import get_memory_owner_user_id, is_private_memory

PROFILE_VIEW_TYPE = "profile"
TIMELINE_VIEW_TYPE = "timeline"
PLAYBOOK_VIEW_TYPE = "playbook"
SUMMARY_VIEW_TYPE = "summary"
MEMORY_LEARNING_STAGE_ORDER = (
    "observe",
    "extract",
    "consolidate",
    "graphify",
    "reflect",
    "reuse",
)
FORMAL_PLAYBOOK_SUCCESS_THRESHOLD = 2

PLAYBOOK_TRIGGER_PATTERN = re.compile(r"(步骤|流程|方法|先.+再.+|如何|怎么做|解决|排查|复盘)")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def find_reconfirm_candidates(
    db: Session,
    *,
    project_id: str,
    limit: int = 5,
    now: datetime | None = None,
) -> list[Memory]:
    """Return the oldest memories that currently need reconfirmation.

    A memory needs reconfirmation when its metadata has
    ``single_source_explicit == True`` and its ``reconfirm_after``
    timestamp is in the past (or absent). Callers pass ``now`` so
    the result is deterministic in tests.
    """
    resolved_now = now or datetime.now(timezone.utc)
    rows = (
        db.query(Memory)
        .filter(Memory.project_id == project_id)
        .filter(Memory.node_status == "active")
        .order_by(Memory.created_at.asc())
        .all()
    )
    out: list[Memory] = []
    for memory in rows:
        metadata = memory.metadata_json or {}
        if not bool(metadata.get("single_source_explicit")):
            continue
        reconfirm_after_raw = str(metadata.get("reconfirm_after") or "").strip()
        if reconfirm_after_raw:
            try:
                when = datetime.fromisoformat(
                    reconfirm_after_raw.replace("Z", "+00:00")
                )
            except ValueError:
                when = resolved_now  # treat bad data as due
            if when > resolved_now:
                continue
        out.append(memory)
        if len(out) >= limit:
            break
    return out


def _normalize_string_list(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    return [
        str(value).strip()
        for value in values
        if isinstance(value, str) and str(value).strip()
    ]


def normalize_learning_stages(values: object) -> list[str]:
    normalized = _normalize_string_list(values)
    if not normalized:
        return []
    ordered: list[str] = []
    extras: list[str] = []
    seen: set[str] = set()
    for stage in normalized:
        if stage in seen:
            continue
        seen.add(stage)
        if stage in MEMORY_LEARNING_STAGE_ORDER:
            ordered.append(stage)
        else:
            extras.append(stage)
    ordered.sort(
        key=lambda item: MEMORY_LEARNING_STAGE_ORDER.index(item)
        if item in MEMORY_LEARNING_STAGE_ORDER
        else len(MEMORY_LEARNING_STAGE_ORDER),
    )
    return [*ordered, *extras]


def merge_learning_stages(*values: object) -> list[str]:
    merged: list[str] = []
    for value in values:
        merged.extend(_normalize_string_list(value))
    return normalize_learning_stages(merged)


def is_playbook_formalized(metadata: dict[str, Any] | None) -> bool:
    payload = dict(metadata or {})
    if bool(payload.get("explicit_saved")):
        return True
    return _non_negative_int(payload.get("success_count"), default=0) >= FORMAL_PLAYBOOK_SUCCESS_THRESHOLD


def apply_playbook_policy(metadata: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(metadata or {})
    success_count = _non_negative_int(payload.get("success_count"), default=0)
    failure_count = _non_negative_int(payload.get("failure_count"), default=0)
    formalized = is_playbook_formalized(payload)
    health_flags = _normalize_string_list(payload.get("health_flags"))
    next_flags = [flag for flag in health_flags if flag != "high_risk_playbook"]
    if failure_count > success_count:
        next_flags.append("high_risk_playbook")
    payload["success_count"] = success_count
    payload["failure_count"] = failure_count
    payload["is_formalized"] = formalized
    payload["recall_tier"] = "formalized" if formalized else "candidate"
    payload["health_flags"] = list(dict.fromkeys(next_flags))
    return payload


def _json_contains_id(values: object, needle: str) -> bool:
    if not needle:
        return False
    return needle in _normalize_string_list(values)


def create_memory_episode(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    source_type: str,
    chunk_text: str,
    conversation_id: str | None = None,
    message_id: str | None = None,
    source_id: str | None = None,
    owner_user_id: str | None = None,
    visibility: str = "private",
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> MemoryEpisode:
    episode = MemoryEpisode(
        id=str(uuid4()),
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_id=conversation_id,
        message_id=message_id,
        source_type=source_type,
        source_id=source_id,
        chunk_text=chunk_text.strip(),
        owner_user_id=owner_user_id,
        visibility=visibility,
        started_at=started_at or utc_now(),
        ended_at=ended_at,
        metadata_json=dict(metadata_json or {}),
    )
    db.add(episode)
    db.flush()
    return episode


def create_memory_learning_run(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    trigger: str,
    conversation_id: str | None = None,
    message_id: str | None = None,
    task_id: str | None = None,
    stages: list[str] | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> MemoryLearningRun:
    run = MemoryLearningRun(
        id=str(uuid4()),
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_id=conversation_id,
        message_id=message_id,
        task_id=task_id,
        trigger=trigger,
        status="pending",
        stages=normalize_learning_stages(stages),
        used_memory_ids=[],
        promoted_memory_ids=[],
        degraded_memory_ids=[],
        started_at=utc_now(),
        metadata_json=dict(metadata_json or {}),
    )
    db.add(run)
    db.flush()
    return run


def finalize_memory_learning_run(
    run: MemoryLearningRun | None,
    *,
    status: str,
    stages: list[str] | None = None,
    used_memory_ids: list[str] | None = None,
    promoted_memory_ids: list[str] | None = None,
    degraded_memory_ids: list[str] | None = None,
    outcome_id: str | None = None,
    error: str | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> None:
    if run is None:
        return
    run.status = status
    if stages is not None:
        run.stages = normalize_learning_stages(stages)
    if used_memory_ids is not None:
        run.used_memory_ids = _normalize_string_list(used_memory_ids)
    if promoted_memory_ids is not None:
        run.promoted_memory_ids = _normalize_string_list(promoted_memory_ids)
    if degraded_memory_ids is not None:
        run.degraded_memory_ids = _normalize_string_list(degraded_memory_ids)
    if outcome_id is not None:
        run.outcome_id = outcome_id
    run.error = error
    run.completed_at = utc_now()
    if metadata_json:
        run.metadata_json = {
            **(run.metadata_json or {}),
            **metadata_json,
        }


def create_memory_outcome(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    status: str,
    feedback_source: str,
    conversation_id: str | None = None,
    message_id: str | None = None,
    task_id: str | None = None,
    summary: str | None = None,
    root_cause: str | None = None,
    tags: list[str] | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> MemoryOutcome:
    outcome = MemoryOutcome(
        id=str(uuid4()),
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_id=conversation_id,
        message_id=message_id,
        task_id=task_id,
        status=status,
        feedback_source=feedback_source,
        summary=summary,
        root_cause=root_cause,
        tags=_normalize_string_list(tags),
        metadata_json=dict(metadata_json or {}),
    )
    db.add(outcome)
    db.flush()
    return outcome


def list_memory_episodes(db: Session, *, memory_id: str) -> list[MemoryEpisode]:
    evidences = list_memory_evidences(db, memory_id=memory_id)
    episode_ids = list(
        dict.fromkeys(
            evidence.episode_id
            for evidence in evidences
            if isinstance(evidence.episode_id, str) and evidence.episode_id.strip()
        )
    )
    if not episode_ids:
        return []
    return (
        db.query(MemoryEpisode)
        .filter(MemoryEpisode.id.in_(episode_ids))
        .order_by(MemoryEpisode.created_at.desc())
        .all()
    )


def list_project_learning_runs(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    limit: int = 100,
) -> list[MemoryLearningRun]:
    return (
        db.query(MemoryLearningRun)
        .filter(
            MemoryLearningRun.workspace_id == workspace_id,
            MemoryLearningRun.project_id == project_id,
        )
        .order_by(MemoryLearningRun.created_at.desc())
        .limit(limit)
        .all()
    )


def get_memory_learning_run(
    db: Session,
    *,
    workspace_id: str,
    learning_run_id: str,
) -> MemoryLearningRun | None:
    return (
        db.query(MemoryLearningRun)
        .filter(
            MemoryLearningRun.workspace_id == workspace_id,
            MemoryLearningRun.id == learning_run_id,
        )
        .first()
    )


def list_learning_runs_for_memory(
    db: Session,
    *,
    memory_id: str,
    workspace_id: str | None = None,
    project_id: str | None = None,
    limit: int = 20,
) -> list[MemoryLearningRun]:
    query = db.query(MemoryLearningRun)
    if workspace_id:
        query = query.filter(MemoryLearningRun.workspace_id == workspace_id)
    if project_id:
        query = query.filter(MemoryLearningRun.project_id == project_id)
    runs = (
        query.order_by(MemoryLearningRun.created_at.desc())
        .limit(max(limit * 4, 50))
        .all()
    )
    return [
        run
        for run in runs
        if _json_contains_id(run.used_memory_ids, memory_id)
        or _json_contains_id(run.promoted_memory_ids, memory_id)
        or _json_contains_id(run.degraded_memory_ids, memory_id)
    ][:limit]


def get_message_memory_learning(
    db: Session,
    *,
    message_id: str,
) -> tuple[list[MemoryLearningRun], list[MemoryOutcome]]:
    runs = (
        db.query(MemoryLearningRun)
        .filter(MemoryLearningRun.message_id == message_id)
        .order_by(MemoryLearningRun.created_at.desc())
        .all()
    )
    outcomes = (
        db.query(MemoryOutcome)
        .filter(MemoryOutcome.message_id == message_id)
        .order_by(MemoryOutcome.created_at.desc())
        .all()
    )
    outcome_ids = [run.outcome_id for run in runs if run.outcome_id]
    if outcome_ids:
        linked = (
            db.query(MemoryOutcome)
            .filter(MemoryOutcome.id.in_(outcome_ids))
            .order_by(MemoryOutcome.created_at.desc())
            .all()
        )
        seen = {outcome.id for outcome in outcomes}
        outcomes.extend(outcome for outcome in linked if outcome.id not in seen)
    return runs, outcomes


def _update_memory_feedback_stats(memory: Memory, *, succeeded: bool, reason: str | None = None) -> None:
    metadata = dict(memory.metadata_json or {})
    success_count = int(metadata.get("success_feedback_count") or 0)
    failure_count = int(metadata.get("failure_feedback_count") or 0)
    if succeeded:
        success_count += 1
        metadata["last_outcome_status"] = "success"
        metadata["suppression_reason"] = None
    else:
        failure_count += 1
        metadata["last_outcome_status"] = "failure"
        metadata["suppression_reason"] = reason or "failure_feedback"
    total = max(success_count + failure_count, 1)
    metadata["success_feedback_count"] = success_count
    metadata["failure_feedback_count"] = failure_count
    metadata["reuse_success_rate"] = round(success_count / total, 4)
    metadata["last_used_at"] = utc_now().isoformat()
    memory.metadata_json = metadata
    if succeeded:
        memory.last_confirmed_at = utc_now()
        memory.confidence = min(1.0, max(float(memory.confidence or 0.0), 0.55) + 0.05)
    else:
        memory.confidence = max(0.1, float(memory.confidence or 0.0) - 0.08)
        if memory.valid_to is None and float(memory.confidence or 0.0) < 0.35:
            memory.valid_to = utc_now()


def apply_memory_outcome(
    db: Session,
    *,
    outcome: MemoryOutcome,
    memory_ids: list[str] | None = None,
    playbook_view: MemoryView | None = None,
) -> None:
    metadata = outcome.metadata_json if isinstance(outcome.metadata_json, dict) else {}
    normalized_ids = _normalize_string_list(memory_ids)
    if normalized_ids:
        memories = db.query(Memory).filter(Memory.id.in_(normalized_ids)).all()
        for memory in memories:
            _update_memory_feedback_stats(
                memory,
                succeeded=outcome.status == "success",
                reason=outcome.root_cause,
            )
    if playbook_view is not None and isinstance(playbook_view.metadata_json, dict):
        view_meta = dict(playbook_view.metadata_json or {})
        if outcome.status == "success":
            view_meta["success_count"] = int(view_meta.get("success_count") or 0) + 1
            view_meta["last_success_at"] = utc_now().isoformat()
        else:
            view_meta["failure_count"] = int(view_meta.get("failure_count") or 0) + 1
            view_meta["last_failure_at"] = utc_now().isoformat()
            reasons = _normalize_string_list(view_meta.get("common_failure_reasons"))
            if outcome.root_cause:
                reasons.insert(0, outcome.root_cause.strip())
            view_meta["common_failure_reasons"] = list(dict.fromkeys(reasons))[:5]
        playbook_view.metadata_json = apply_playbook_policy(view_meta)


def list_memory_outcomes_for_learning_run(
    db: Session,
    *,
    learning_run: MemoryLearningRun,
) -> list[MemoryOutcome]:
    if learning_run.outcome_id:
        outcome = db.get(MemoryOutcome, learning_run.outcome_id)
        return [outcome] if outcome is not None else []
    return []


def list_memory_outcomes(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    limit: int = 100,
) -> list[MemoryOutcome]:
    return (
        db.query(MemoryOutcome)
        .filter(
            MemoryOutcome.workspace_id == workspace_id,
            MemoryOutcome.project_id == project_id,
        )
        .order_by(MemoryOutcome.created_at.desc())
        .limit(limit)
        .all()
    )


def temporal_defaults(*, memory_kind: str, timestamp: datetime | None = None) -> dict[str, datetime | None]:
    effective = timestamp or utc_now()
    if memory_kind == MEMORY_KIND_EPISODIC:
        return {
            "observed_at": effective,
            "valid_from": effective,
            "valid_to": None,
            "last_confirmed_at": effective,
        }
    return {
        "observed_at": effective,
        "valid_from": effective,
        "valid_to": None,
        "last_confirmed_at": effective,
    }


def apply_temporal_defaults(memory: Memory, *, memory_kind: str | None = None, timestamp: datetime | None = None) -> None:
    kind = memory_kind or get_memory_kind(memory)
    defaults = temporal_defaults(memory_kind=kind, timestamp=timestamp)
    if memory.observed_at is None:
        memory.observed_at = defaults["observed_at"]
    if memory.valid_from is None:
        memory.valid_from = defaults["valid_from"]
    if memory.last_confirmed_at is None:
        memory.last_confirmed_at = defaults["last_confirmed_at"]


def create_memory_write_run(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    conversation_id: str | None,
    message_id: str | None,
    extraction_model: str | None,
    consolidation_model: str | None,
    metadata_json: dict[str, Any] | None = None,
) -> MemoryWriteRun:
    run = MemoryWriteRun(
        id=str(uuid4()),
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_id=conversation_id,
        message_id=message_id,
        status="pending",
        extraction_model=extraction_model,
        consolidation_model=consolidation_model,
        started_at=utc_now(),
        metadata_json=dict(metadata_json or {}),
    )
    db.add(run)
    db.flush()
    return run


def finalize_memory_write_run(
    run: MemoryWriteRun | None,
    *,
    status: str,
    error: str | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> None:
    if run is None:
        return
    run.status = status
    run.error = error
    run.completed_at = utc_now()
    if metadata_json:
        run.metadata_json = {
            **(run.metadata_json or {}),
            **metadata_json,
        }


def create_memory_write_item(
    db: Session,
    *,
    run_id: str,
    subject_memory_id: str | None,
    candidate_text: str,
    category: str,
    proposed_memory_kind: str | None,
    importance: float,
    decision: str = "create",
    reason: str | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> MemoryWriteItem:
    item = MemoryWriteItem(
        id=str(uuid4()),
        run_id=run_id,
        subject_memory_id=subject_memory_id,
        candidate_text=candidate_text,
        category=category,
        proposed_memory_kind=proposed_memory_kind,
        importance=float(importance or 0.0),
        decision=decision,
        reason=reason,
        metadata_json=dict(metadata_json or {}),
    )
    db.add(item)
    db.flush()
    return item


def update_memory_write_item(
    item: MemoryWriteItem | None,
    *,
    decision: str | None = None,
    target_memory_id: str | None = None,
    predecessor_memory_id: str | None = None,
    reason: str | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> None:
    if item is None:
        return
    if decision:
        item.decision = decision
    if target_memory_id is not None:
        item.target_memory_id = target_memory_id
    if predecessor_memory_id is not None:
        item.predecessor_memory_id = predecessor_memory_id
    if reason is not None:
        item.reason = reason
    if metadata_json:
        item.metadata_json = {
            **(item.metadata_json or {}),
            **metadata_json,
        }


def record_memory_evidence(
    db: Session,
    *,
    memory: Memory,
    source_type: str,
    quote_text: str,
    conversation_id: str | None = None,
    message_id: str | None = None,
    message_role: str | None = None,
    data_item_id: str | None = None,
    episode_id: str | None = None,
    start_offset: int | None = None,
    end_offset: int | None = None,
    chunk_id: str | None = None,
    confidence: float | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> MemoryEvidence:
    evidence = MemoryEvidence(
        id=str(uuid4()),
        workspace_id=memory.workspace_id,
        project_id=memory.project_id,
        memory_id=memory.id,
        source_type=source_type,
        conversation_id=conversation_id,
        message_id=message_id,
        message_role=message_role,
        data_item_id=data_item_id,
        episode_id=episode_id,
        quote_text=quote_text.strip(),
        start_offset=start_offset,
        end_offset=end_offset,
        chunk_id=chunk_id,
        confidence=float(confidence if confidence is not None else memory.confidence or 0.7),
        metadata_json=dict(metadata_json or {}),
    )
    db.add(evidence)
    db.flush()
    return evidence


def ensure_memory_file_evidence(
    db: Session,
    *,
    memory: Memory,
    data_item: DataItem,
    quote_text: str | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> MemoryEvidence | None:
    normalized_quote = str(quote_text or "").strip() or f"关联文件：{data_item.filename}"
    existing = (
        db.query(MemoryEvidence)
        .filter(
            MemoryEvidence.memory_id == memory.id,
            MemoryEvidence.source_type == "file",
            MemoryEvidence.data_item_id == data_item.id,
            MemoryEvidence.chunk_id.is_(None),
        )
        .order_by(MemoryEvidence.created_at.asc())
        .first()
    )
    if existing is not None:
        return existing

    return record_memory_evidence(
        db,
        memory=memory,
        source_type="file",
        data_item_id=data_item.id,
        episode_id=None,
        quote_text=normalized_quote,
        confidence=float(memory.confidence or 0.7),
        metadata_json={
            "filename": data_item.filename,
            "media_type": data_item.media_type,
            **dict(metadata_json or {}),
        },
    )


def copy_memory_evidences(
    db: Session,
    *,
    source_memory_id: str,
    target_memory_id: str,
) -> list[MemoryEvidence]:
    evidences = (
        db.query(MemoryEvidence)
        .filter(MemoryEvidence.memory_id == source_memory_id)
        .order_by(MemoryEvidence.created_at.asc())
        .all()
    )
    created: list[MemoryEvidence] = []
    for evidence in evidences:
        duplicate = (
            db.query(MemoryEvidence.id)
            .filter(
                MemoryEvidence.memory_id == target_memory_id,
                MemoryEvidence.source_type == evidence.source_type,
                MemoryEvidence.message_id == evidence.message_id,
                MemoryEvidence.data_item_id == evidence.data_item_id,
                MemoryEvidence.quote_text == evidence.quote_text,
            )
            .first()
        )
        if duplicate is not None:
            continue
        created.append(
            MemoryEvidence(
                id=str(uuid4()),
                workspace_id=evidence.workspace_id,
                project_id=evidence.project_id,
                memory_id=target_memory_id,
                source_type=evidence.source_type,
                conversation_id=evidence.conversation_id,
                message_id=evidence.message_id,
                message_role=evidence.message_role,
                data_item_id=evidence.data_item_id,
                episode_id=evidence.episode_id,
                quote_text=evidence.quote_text,
                start_offset=evidence.start_offset,
                end_offset=evidence.end_offset,
                chunk_id=evidence.chunk_id,
                confidence=evidence.confidence,
                metadata_json=dict(evidence.metadata_json or {}),
            )
        )
    if created:
        db.add_all(created)
        db.flush()
    return created


def list_memory_evidences(db: Session, *, memory_id: str) -> list[MemoryEvidence]:
    return (
        db.query(MemoryEvidence)
        .filter(MemoryEvidence.memory_id == memory_id)
        .order_by(MemoryEvidence.created_at.desc())
        .all()
    )


def list_memory_views_for_memory(db: Session, *, memory: Memory) -> list[MemoryView]:
    subject_id = get_subject_memory_id(memory) or (memory.id if memory.node_type == "subject" else None)
    views = (
        db.query(MemoryView)
        .filter(
            MemoryView.project_id == memory.project_id,
            (MemoryView.source_subject_id == subject_id) if subject_id else sql_text("1 = 0"),
        )
        .order_by(MemoryView.updated_at.desc())
        .all()
    ) if subject_id else []
    direct = []
    if memory.id:
        for view in (
            db.query(MemoryView)
            .filter(MemoryView.project_id == memory.project_id)
            .order_by(MemoryView.updated_at.desc())
            .all()
        ):
            source_ids = (view.metadata_json or {}).get("source_memory_ids")
            if isinstance(source_ids, list) and memory.id in source_ids:
                direct.append(view)
    deduped: dict[str, MemoryView] = {}
    for view in [*views, *direct]:
        deduped[view.id] = view
    return list(deduped.values())


def list_memory_write_history(db: Session, *, memory_id: str) -> list[MemoryWriteItem]:
    return (
        db.query(MemoryWriteItem)
        .filter(
            (MemoryWriteItem.target_memory_id == memory_id)
            | (MemoryWriteItem.predecessor_memory_id == memory_id)
        )
        .order_by(MemoryWriteItem.created_at.desc())
        .all()
    )


def list_memory_timeline_events(db: Session, *, memory: Memory) -> list[Memory]:
    subject_id = get_subject_memory_id(memory) or (memory.id if memory.node_type == "subject" else None)
    if not subject_id:
        return []
    memories = (
        db.query(Memory)
        .filter(
            Memory.project_id == memory.project_id,
            Memory.subject_memory_id == subject_id,
        )
        .order_by(Memory.observed_at.desc().nullslast(), Memory.updated_at.desc())
        .all()
    )
    selected = [
        item
        for item in memories
        if get_memory_kind(item) == MEMORY_KIND_EPISODIC
        or item.node_status != "active"
        or (memory.lineage_key and item.lineage_key == memory.lineage_key)
    ]
    return selected[:20]


def get_message_memory_write(db: Session, *, message_id: str) -> tuple[MemoryWriteRun | None, list[MemoryWriteItem]]:
    run = (
        db.query(MemoryWriteRun)
        .filter(MemoryWriteRun.message_id == message_id)
        .order_by(MemoryWriteRun.created_at.desc())
        .first()
    )
    if run is None:
        return None, []
    items = (
        db.query(MemoryWriteItem)
        .filter(MemoryWriteItem.run_id == run.id)
        .order_by(MemoryWriteItem.created_at.asc())
        .all()
    )
    return run, items


def list_project_playbook_views(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    subject_id: str | None = None,
    query: str | None = None,
    health: str | None = None,
    limit: int = 100,
) -> list[MemoryView]:
    views = (
        db.query(MemoryView)
        .filter(
            MemoryView.workspace_id == workspace_id,
            MemoryView.project_id == project_id,
            MemoryView.view_type == PLAYBOOK_VIEW_TYPE,
        )
        .order_by(MemoryView.updated_at.desc())
        .limit(limit * 3)
        .all()
    )
    normalized_query = str(query or "").strip().casefold()
    filtered: list[MemoryView] = []
    for view in views:
        if subject_id and view.source_subject_id != subject_id:
            continue
        metadata = view.metadata_json if isinstance(view.metadata_json, dict) else {}
        if normalized_query and normalized_query not in view.content.casefold():
            trigger_text = " ".join(_normalize_string_list(metadata.get("trigger_phrases"))).casefold()
            if normalized_query not in trigger_text:
                continue
        success_count = int(metadata.get("success_count") or 0)
        failure_count = int(metadata.get("failure_count") or 0)
        if health == "high-risk" and failure_count <= success_count:
            continue
        if health == "healthy" and success_count <= failure_count:
            continue
        filtered.append(view)
    filtered.sort(
        key=lambda item: (
            1 if is_playbook_formalized(item.metadata_json if isinstance(item.metadata_json, dict) else {}) else 0,
            _non_negative_int((item.metadata_json or {}).get("success_count"), default=0)
            - _non_negative_int((item.metadata_json or {}).get("failure_count"), default=0),
            item.updated_at,
        ),
        reverse=True,
    )
    return filtered[:limit]


def refresh_memory_health_signals(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
) -> dict[str, int]:
    now = utc_now()
    memories = (
        db.query(Memory)
        .filter(
            Memory.workspace_id == workspace_id,
            Memory.project_id == project_id,
            Memory.node_type == "fact",
        )
        .all()
    )
    playbooks = list_project_playbook_views(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        limit=500,
    )
    updated_memories = 0
    updated_playbooks = 0
    stale_count = 0
    reconfirm_count = 0
    high_risk_playbooks = 0

    for memory in memories:
        metadata = dict(memory.metadata_json or {})
        next_flags: list[str] = []
        if memory.valid_to is not None and memory.valid_to < now:
            stale_count += 1
            next_flags.append("stale")
        if memory.node_status == "conflict":
            next_flags.append("conflict")
        reconfirm_after = str(metadata.get("reconfirm_after") or "").strip()
        if bool(metadata.get("single_source_explicit")):
            needs_reconfirm = True
            if reconfirm_after:
                try:
                    needs_reconfirm = datetime.fromisoformat(reconfirm_after.replace("Z", "+00:00")) <= now
                except ValueError:
                    needs_reconfirm = True
            if needs_reconfirm:
                reconfirm_count += 1
                next_flags.append("needs_reconfirm")

        next_suppression_reason = str(metadata.get("suppression_reason") or "").strip() or None
        if "stale" in next_flags:
            next_suppression_reason = "stale"
        elif next_suppression_reason == "stale":
            next_suppression_reason = None

        prior_flags = _normalize_string_list(metadata.get("health_flags"))
        if list(dict.fromkeys(next_flags)) != prior_flags or (
            next_suppression_reason != (str(metadata.get("suppression_reason") or "").strip() or None)
        ):
            metadata["health_flags"] = list(dict.fromkeys(next_flags))
            if next_suppression_reason:
                metadata["suppression_reason"] = next_suppression_reason
            else:
                metadata.pop("suppression_reason", None)
            memory.metadata_json = metadata
            updated_memories += 1

    for view in playbooks:
        original = dict(view.metadata_json or {})
        updated = apply_playbook_policy(original)
        if "high_risk_playbook" in updated.get("health_flags", []):
            high_risk_playbooks += 1
        if updated != original:
            view.metadata_json = updated
            updated_playbooks += 1

    return {
        "updated_memories": updated_memories,
        "updated_playbooks": updated_playbooks,
        "stale_count": stale_count,
        "reconfirm_count": reconfirm_count,
        "high_risk_playbooks": high_risk_playbooks,
    }


def summarize_memory_health(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    limit: int = 100,
) -> dict[str, Any]:
    memories = (
        db.query(Memory)
        .filter(
            Memory.workspace_id == workspace_id,
            Memory.project_id == project_id,
            Memory.node_type == "fact",
        )
        .order_by(Memory.updated_at.desc())
        .all()
    )
    playbooks = list_project_playbook_views(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        limit=max(limit, 100),
    )
    now = utc_now()
    entries: list[dict[str, Any]] = []
    counts = {"stale": 0, "conflict": 0, "needs_reconfirm": 0, "high_risk_playbook": 0}
    for memory in memories:
        metadata = dict(memory.metadata_json or {})
        if memory.valid_to is not None and memory.valid_to < now:
            counts["stale"] += 1
            entries.append({"kind": "stale", "memory": memory, "reason": "记忆已过有效期。"})
        if memory.node_status == "conflict":
            counts["conflict"] += 1
            entries.append({"kind": "conflict", "memory": memory, "reason": "该记忆处于冲突状态。"})
        reconfirm_after = str(metadata.get("reconfirm_after") or "").strip()
        single_source = bool(metadata.get("single_source_explicit"))
        if single_source:
            should_reconfirm = True
            if reconfirm_after:
                try:
                    should_reconfirm = datetime.fromisoformat(reconfirm_after.replace("Z", "+00:00")) <= now
                except ValueError:
                    should_reconfirm = True
            if should_reconfirm:
                counts["needs_reconfirm"] += 1
                entries.append({"kind": "needs_reconfirm", "memory": memory, "reason": "该长期记忆仍需后续复确认。"})
    for view in playbooks:
        metadata = view.metadata_json if isinstance(view.metadata_json, dict) else {}
        success_count = int(metadata.get("success_count") or 0)
        failure_count = int(metadata.get("failure_count") or 0)
        if failure_count > success_count:
            counts["high_risk_playbook"] += 1
            entries.append({"kind": "high_risk_playbook", "view": view, "reason": "该 playbook 最近失败多于成功。"})
    entries.sort(
        key=lambda item: (
            0 if item["kind"] in {"conflict", "high_risk_playbook"} else 1,
            getattr(item.get("memory") or item.get("view"), "updated_at", None) or getattr(item.get("memory") or item.get("view"), "created_at", utc_now()),
        ),
        reverse=True,
    )
    return {
        "counts": counts,
        "entries": entries[:limit],
    }


def _upsert_memory_view(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    source_subject_id: str | None,
    view_type: str,
    content: str,
    metadata_json: dict[str, Any] | None = None,
) -> MemoryView:
    existing = (
        db.query(MemoryView)
        .filter(
            MemoryView.workspace_id == workspace_id,
            MemoryView.project_id == project_id,
            MemoryView.source_subject_id == source_subject_id,
            MemoryView.view_type == view_type,
        )
        .first()
    )
    if existing is None:
        existing = MemoryView(
            id=str(uuid4()),
            workspace_id=workspace_id,
            project_id=project_id,
            source_subject_id=source_subject_id,
            view_type=view_type,
            content=content,
            metadata_json=dict(metadata_json or {}),
        )
        db.add(existing)
        db.flush()
        return existing
    existing.content = content
    existing.metadata_json = dict(metadata_json or {})
    existing.updated_at = utc_now()
    db.flush()
    return existing


def refresh_subject_profile_view(db: Session, *, subject_memory: Memory) -> MemoryView | None:
    memories = (
        db.query(Memory)
        .filter(
            Memory.project_id == subject_memory.project_id,
            Memory.subject_memory_id == subject_memory.id,
            Memory.type == "permanent",
        )
        .order_by(Memory.updated_at.desc())
        .all()
    )
    selected = [
        memory
        for memory in memories
        if is_active_memory(memory)
        and get_memory_kind(memory) in {MEMORY_KIND_PROFILE, MEMORY_KIND_PREFERENCE, MEMORY_KIND_GOAL}
    ][:12]
    if not selected:
        return None
    lines = [f"- {memory.content}" for memory in selected]
    owner_user_id = get_memory_owner_user_id(subject_memory) if is_private_memory(subject_memory) else None
    return _upsert_memory_view(
        db,
        workspace_id=subject_memory.workspace_id,
        project_id=subject_memory.project_id,
        source_subject_id=subject_memory.id,
        view_type=PROFILE_VIEW_TYPE,
        content="\n".join(lines),
        metadata_json={
            "source_memory_ids": [memory.id for memory in selected],
            "memory_count": len(selected),
            "owner_user_id": owner_user_id,
        },
    )


def refresh_subject_timeline_view(db: Session, *, subject_memory: Memory) -> MemoryView | None:
    memories = (
        db.query(Memory)
        .filter(
            Memory.project_id == subject_memory.project_id,
            Memory.subject_memory_id == subject_memory.id,
        )
        .order_by(Memory.observed_at.desc().nullslast(), Memory.updated_at.desc())
        .all()
    )
    selected = [
        memory
        for memory in memories
        if get_memory_kind(memory) == MEMORY_KIND_EPISODIC or memory.node_status != "active"
    ][:16]
    if not selected:
        return None
    lines = []
    for memory in selected:
        timestamp = memory.observed_at or memory.updated_at or memory.created_at
        prefix = timestamp.date().isoformat() if timestamp else "unknown"
        lines.append(f"- [{prefix}] {memory.content}")
    owner_user_id = get_memory_owner_user_id(subject_memory) if is_private_memory(subject_memory) else None
    return _upsert_memory_view(
        db,
        workspace_id=subject_memory.workspace_id,
        project_id=subject_memory.project_id,
        source_subject_id=subject_memory.id,
        view_type=TIMELINE_VIEW_TYPE,
        content="\n".join(lines),
        metadata_json={
            "source_memory_ids": [memory.id for memory in selected],
            "memory_count": len(selected),
            "owner_user_id": owner_user_id,
        },
    )


def _extract_playbook_steps(text: str) -> list[str]:
    lines = [line.strip(" -\t") for line in str(text or "").splitlines() if line.strip()]
    numbered = [
        re.sub(r"^\d+[.)、]\s*", "", line).strip()
        for line in lines
        if re.match(r"^\d+[.)、]\s*", line)
    ]
    if numbered:
        return [step for step in numbered if step]
    if "先" in text and "再" in text:
        segments = re.split(r"(?:然后|再|最后)", text)
        steps = [segment.strip(" ，,。；;") for segment in segments if segment.strip(" ，,。；;")]
        return steps[:6]
    return []


def _non_negative_int(value: object, *, default: int = 0) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return default
    return max(normalized, 0)


def refresh_subject_playbook_view(
    db: Session,
    *,
    subject_memory: Memory,
    source_memory_ids: list[str],
    source_text: str,
) -> MemoryView | None:
    if not PLAYBOOK_TRIGGER_PATTERN.search(source_text or ""):
        return None
    steps = _extract_playbook_steps(source_text)
    if not steps:
        return None
    trigger_phrases = [
        phrase
        for phrase, count in Counter(re.findall(r"[\w\u4e00-\u9fff]{2,}", source_text)).most_common(6)
        if count > 0
    ]
    owner_user_id = get_memory_owner_user_id(subject_memory) if is_private_memory(subject_memory) else None
    content = "\n".join(f"{index + 1}. {step}" for index, step in enumerate(steps))
    existing = (
        db.query(MemoryView)
        .filter(
            MemoryView.workspace_id == subject_memory.workspace_id,
            MemoryView.project_id == subject_memory.project_id,
            MemoryView.source_subject_id == subject_memory.id,
            MemoryView.view_type == PLAYBOOK_VIEW_TYPE,
        )
        .first()
    )
    existing_metadata = (
        existing.metadata_json
        if existing is not None and isinstance(existing.metadata_json, dict)
        else {}
    )
    existing_steps = (
        existing_metadata.get("ordered_steps")
        if isinstance(existing_metadata.get("ordered_steps"), list)
        else []
    )
    existing_episode_ids = (
        existing_metadata.get("source_episode_ids")
        if isinstance(existing_metadata.get("source_episode_ids"), list)
        else []
    )
    derived_episode_ids = [
        episode_id
        for episode_id, in (
            db.query(MemoryEvidence.episode_id)
            .filter(
                MemoryEvidence.memory_id.in_(source_memory_ids or [""]),
                MemoryEvidence.episode_id.is_not(None),
            )
            .all()
            if source_memory_ids
            else []
        )
        if isinstance(episode_id, str) and episode_id.strip()
    ]
    previous_source_ids = (
        existing_metadata.get("source_memory_ids")
        if isinstance(existing_metadata.get("source_memory_ids"), list)
        else []
    )
    merged_source_memory_ids = list(
        dict.fromkeys(
            [
                str(item).strip()
                for item in [*previous_source_ids, *source_memory_ids]
                if isinstance(item, str) and str(item).strip()
            ]
        )
    )
    merged_source_episode_ids = list(
        dict.fromkeys(
            [
                str(item).strip()
                for item in [*existing_episode_ids, *derived_episode_ids]
                if isinstance(item, str) and str(item).strip()
            ]
        )
    )
    success_count = _non_negative_int(existing_metadata.get("success_count"), default=0)
    failure_count = _non_negative_int(existing_metadata.get("failure_count"), default=0)
    policy_metadata = apply_playbook_policy(
        {
            **existing_metadata,
            "source_memory_ids": merged_source_memory_ids,
            "source_episode_ids": merged_source_episode_ids,
            "ordered_steps": steps,
            "trigger_phrases": trigger_phrases,
            "prerequisites": _normalize_string_list(existing_metadata.get("prerequisites")),
            "applies_to": list(
                dict.fromkeys(
                    [
                        *(
                            _normalize_string_list(existing_metadata.get("applies_to"))
                            or [subject_memory.content]
                        ),
                        subject_memory.content,
                    ]
                )
            ),
            "success_count": success_count,
            "failure_count": failure_count,
            "last_success_at": existing_metadata.get("last_success_at") if success_count > 0 else None,
            "last_failure_at": existing_metadata.get("last_failure_at"),
            "common_failure_reasons": (
                existing_metadata.get("common_failure_reasons")
                if isinstance(existing_metadata.get("common_failure_reasons"), list)
                else []
            ),
            "owner_user_id": owner_user_id,
            "explicit_saved": bool(existing_metadata.get("explicit_saved")),
        }
    )
    return _upsert_memory_view(
        db,
        workspace_id=subject_memory.workspace_id,
        project_id=subject_memory.project_id,
        source_subject_id=subject_memory.id,
        view_type=PLAYBOOK_VIEW_TYPE,
        content=content,
        metadata_json=policy_metadata,
    )


def refresh_subject_views(
    db: Session,
    *,
    subject_memory: Memory,
    playbook_source_text: str | None = None,
    playbook_source_memory_ids: list[str] | None = None,
) -> list[MemoryView]:
    views: list[MemoryView] = []
    profile_view = refresh_subject_profile_view(db, subject_memory=subject_memory)
    if profile_view is not None:
        views.append(profile_view)
    timeline_view = refresh_subject_timeline_view(db, subject_memory=subject_memory)
    if timeline_view is not None:
        views.append(timeline_view)
    if playbook_source_text:
        playbook_view = refresh_subject_playbook_view(
            db,
            subject_memory=subject_memory,
            source_memory_ids=playbook_source_memory_ids or [],
            source_text=playbook_source_text,
        )
        if playbook_view is not None:
            views.append(playbook_view)
    return views


def search_memories_lexical(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    query: str,
    limit: int = 12,
) -> list[dict[str, Any]]:
    rows = db.execute(
        sql_text(
            """
            SELECT id,
                   GREATEST(similarity(content, :query), similarity(category, :query)) AS score,
                   content
            FROM memories
            WHERE workspace_id = :workspace_id
              AND project_id = :project_id
              AND (content % :query OR category % :query OR content ILIKE :query_like)
            ORDER BY score DESC, updated_at DESC
            LIMIT :limit
            """
        ),
        {
            "workspace_id": workspace_id,
            "project_id": project_id,
            "query": query,
            "query_like": f"%{query.strip()}%",
            "limit": limit,
        },
    ).fetchall()
    return [
        {
            "memory_id": row[0],
            "score": float(row[1] or 0.0),
            "snippet": str(row[2] or ""),
        }
        for row in rows
        if row[0]
    ]


def search_memory_evidences_lexical(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    query: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    rows = db.execute(
        sql_text(
            """
            SELECT id,
                   memory_id,
                   similarity(quote_text, :query) AS score,
                   quote_text
            FROM memory_evidences
            WHERE workspace_id = :workspace_id
              AND project_id = :project_id
              AND (quote_text % :query OR quote_text ILIKE :query_like)
            ORDER BY score DESC, created_at DESC
            LIMIT :limit
            """
        ),
        {
            "workspace_id": workspace_id,
            "project_id": project_id,
            "query": query,
            "query_like": f"%{query.strip()}%",
            "limit": limit,
        },
    ).fetchall()
    return [
        {
            "evidence_id": row[0],
            "memory_id": row[1],
            "score": float(row[2] or 0.0),
            "snippet": str(row[3] or ""),
        }
        for row in rows
        if row[0] and row[1]
    ]


def search_memory_views_lexical(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    query: str,
    limit: int = 8,
    subject_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    statement = sql_text(
        """
        SELECT id,
               source_subject_id,
               view_type,
               similarity(content, :query) AS score,
               content
        FROM memory_views
        WHERE workspace_id = :workspace_id
          AND project_id = :project_id
          AND (content % :query OR content ILIKE :query_like)
          AND (:subject_scope = FALSE OR source_subject_id IN :subject_ids)
        ORDER BY score DESC, updated_at DESC
        LIMIT :limit
        """
    ).bindparams(bindparam("subject_ids", expanding=True))
    rows = db.execute(
        statement,
        {
            "workspace_id": workspace_id,
            "project_id": project_id,
            "query": query,
            "query_like": f"%{query.strip()}%",
            "subject_scope": bool(subject_ids),
            "subject_ids": subject_ids or [""],
            "limit": limit,
        },
    ).fetchall()
    return [
        {
            "view_id": row[0],
            "source_subject_id": row[1],
            "view_type": row[2],
            "score": float(row[3] or 0.0),
            "snippet": str(row[4] or ""),
        }
        for row in rows
        if row[0]
    ]


@dataclass(slots=True)
class RerankDocument:
    key: str
    text: str
    score: float = 0.0


async def rerank_documents(query: str, documents: list[RerankDocument]) -> list[RerankDocument]:
    if not documents or not settings.dashscope_api_key.strip():
        return documents
    client = get_client()
    payload = {
        "model": settings.dashscope_rerank_model,
        "input": {
            "query": query,
            "documents": [document.text for document in documents],
        },
        "parameters": {
            "return_documents": False,
            "top_n": len(documents),
        },
    }
    response = await client.post(
        DASHSCOPE_RERANK_URL,
        headers=dashscope_headers(),
        json=payload,
    )
    try:
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        message = response.text
        raise UpstreamServiceError(f"Memory rerank failed: {message}") from exc
    payload_json = response.json()
    raw_results = None
    if isinstance(payload_json, dict):
        output = payload_json.get("output")
        if isinstance(output, dict):
            raw_results = output.get("results")
        if raw_results is None:
            raw_results = payload_json.get("results")
    if not isinstance(raw_results, list):
        return documents
    scores_by_index: dict[int, float] = {}
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        index = item.get("index")
        score = item.get("relevance_score")
        if isinstance(index, int) and isinstance(score, (int, float)):
            scores_by_index[index] = float(score)
    reranked = [
        RerankDocument(key=document.key, text=document.text, score=scores_by_index.get(index, document.score))
        for index, document in enumerate(documents)
    ]
    reranked.sort(key=lambda item: item.score, reverse=True)
    return reranked
