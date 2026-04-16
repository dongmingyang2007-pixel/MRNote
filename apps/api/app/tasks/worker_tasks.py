from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from datetime import datetime, timezone

from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import (
    Conversation,
    DataItem,
    Dataset,
    Memory,
    MemoryLearningRun,
    MemoryOutcome,
    MemoryWriteRun,
    Message,
    ModelVersion,
    Project,
)
from app.services.audit import write_audit_log
from app.services.memory_graph_events import (
    bump_project_memory_graph_revision,
    session_has_pending_graph_mutations,
)
from app.services.memory_metadata import (
    ACTIVE_NODE_STATUS,
    FACT_NODE_TYPE,
    is_active_memory,
    normalize_memory_metadata,
)
from app.services.memory_related_edges import ensure_project_prerequisite_edges, ensure_project_related_edges
from app.services.memory_roots import (
    ensure_project_user_subject,
)
from app.services.memory_visibility import (
    build_private_memory_metadata,
)
from app.services.memory_versioning import ensure_fact_lineage
from app.services.memory_v2 import (
    PLAYBOOK_TRIGGER_PATTERN,
    apply_temporal_defaults,
    finalize_memory_learning_run,
    finalize_memory_write_run,
    merge_learning_stages,
    refresh_memory_health_signals,
    refresh_subject_views,
)
from app.services import project_cleanup as project_cleanup_service
from app.services.project_cleanup import ProjectDeletionError, delete_project_permanently
from app.services.runtime_state import runtime_state
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


MEMORY_EXTRACTION_STATUS_PENDING = "pending"
MEMORY_EXTRACTION_STATUS_COMPLETED = "completed"
MEMORY_EXTRACTION_STATUS_FAILED = "failed"
MEMORY_EXTRACTION_FAILURE_SUMMARY = "本轮记忆处理失败，请稍后重试"
MEMORY_EXTRACTION_MAX_ATTEMPTS = 3
_MEMORY_EXTRACTION_UNSET = object()


def _is_completed_upload_status(status: object) -> bool:
    return status in {None, "completed", "index_failed"}


def delete_object(*, bucket_name: str, object_key: str) -> None:
    project_cleanup_service.delete_object(bucket_name=bucket_name, object_key=object_key)


@celery_app.task(name="app.tasks.worker_tasks.process_data_item")
def process_data_item(data_item_id: str) -> None:
    db = SessionLocal()
    write_run = None
    try:
        item = db.get(DataItem, data_item_id)
        if not item or item.deleted_at is not None:
            return

        # v0.1 keeps dataset processing mock-only until object content inspection is wired up.
        pseudo = f"{item.dataset_id}:{item.filename}:{item.size_bytes}".encode()
        item.sha256 = hashlib.sha256(pseudo).hexdigest()

        if item.media_type.startswith("image/"):
            item.width = item.width or 1024
            item.height = item.height or 768

        item.meta_json = {**(item.meta_json or {}), "processed": True, "mock": True}

        write_audit_log(
            db,
            workspace_id=None,
            actor_user_id=None,
            action="data_item.processed",
            target_type="data_item",
            target_id=item.id,
            meta_json={"dataset_id": item.dataset_id},
        )
        db.commit()
    finally:
        db.close()


def _delete_object_keys(object_keys: set[str]) -> bool:
    success = True
    for object_key in sorted(object_keys):
        if not object_key:
            continue
        try:
            delete_object(bucket_name=settings.s3_private_bucket, object_key=object_key)
        except Exception:  # noqa: BLE001
            success = False
    return success


def _delete_object_if_present(*, bucket_name: str, object_key: str | None) -> bool:
    if not object_key:
        return True
    try:
        delete_object(bucket_name=bucket_name, object_key=object_key)
    except Exception:  # noqa: BLE001
        return False
    return True


@celery_app.task(name="app.tasks.worker_tasks.cleanup_pending_upload_session")
def cleanup_pending_upload_session(
    upload_id: str,
    object_key: str | None = None,
    data_item_id: str | None = None,
) -> None:
    session = runtime_state.get_json(f"upload:{upload_id}", "session")
    clear_session = True
    db = SessionLocal()
    try:
        resolved_data_item_id = data_item_id
        resolved_object_key = object_key
        if session:
            session_data_item_id = session.get("data_item_id")
            if isinstance(session_data_item_id, str) and session_data_item_id:
                resolved_data_item_id = session_data_item_id
            session_object_key = session.get("object_key")
            if isinstance(session_object_key, str) and session_object_key:
                resolved_object_key = session_object_key

        item = None
        if isinstance(resolved_data_item_id, str) and resolved_data_item_id:
            item = db.get(DataItem, resolved_data_item_id)
            if item and not _is_completed_upload_status((item.meta_json or {}).get("upload_status")):
                if item.deleted_at is None:
                    item.deleted_at = datetime.now(timezone.utc)
                item.meta_json = {
                    **(item.meta_json or {}),
                    "cleanup_marked": True,
                    "upload_status": "abandoned",
                }
                db.commit()
        if item and _is_completed_upload_status((item.meta_json or {}).get("upload_status")) and item.deleted_at is None:
            return
        deleted = _delete_object_if_present(bucket_name=settings.s3_private_bucket, object_key=resolved_object_key)
        if not deleted and resolved_object_key:
            clear_session = False
            try:
                cleanup_pending_upload_session.apply_async(
                    args=[upload_id, resolved_object_key, resolved_data_item_id],
                    countdown=60,
                )
            except Exception:  # noqa: BLE001
                pass
    finally:
        db.close()
        if clear_session:
            runtime_state.delete(f"upload:{upload_id}", "session")


@celery_app.task(name="app.tasks.worker_tasks.cleanup_pending_model_artifact_upload")
def cleanup_pending_model_artifact_upload(
    artifact_upload_id: str,
    object_key: str | None = None,
) -> None:
    session = runtime_state.get_json(f"model-artifact:{artifact_upload_id}", "session")
    resolved_object_key = object_key
    clear_session = True
    if session:
        session_object_key = session.get("object_key")
        if isinstance(session_object_key, str) and session_object_key:
            resolved_object_key = session_object_key

    if resolved_object_key:
        db = SessionLocal()
        try:
            live_reference = (
                db.query(ModelVersion.id)
                .filter(
                    ModelVersion.artifact_object_key == resolved_object_key,
                    ModelVersion.deleted_at.is_(None),
                )
                .first()
            )
            if not live_reference:
                deleted = _delete_object_if_present(
                    bucket_name=settings.s3_private_bucket,
                    object_key=resolved_object_key,
                )
                if not deleted:
                    clear_session = False
                    try:
                        cleanup_pending_model_artifact_upload.apply_async(
                            args=[artifact_upload_id, resolved_object_key],
                            countdown=60,
                        )
                    except Exception:  # noqa: BLE001
                        pass
        finally:
            db.close()
    if clear_session:
        runtime_state.delete(f"model-artifact:{artifact_upload_id}", "session")


@celery_app.task(name="app.tasks.worker_tasks.cleanup_deleted_dataset")
def cleanup_deleted_dataset(dataset_id: str) -> None:
    db = SessionLocal()
    try:
        dataset = db.get(Dataset, dataset_id)
        if not dataset:
            return
        dataset.cleanup_status = "running"
        db.flush()

        items = db.query(DataItem).filter(DataItem.dataset_id == dataset_id).all()
        object_keys = {item.object_key for item in items}
        for item in items:
            if item.deleted_at is None:
                item.deleted_at = datetime.now(timezone.utc)
            item.meta_json = {**(item.meta_json or {}), "cleanup_marked": True}

        dataset.cleanup_status = "done" if _delete_object_keys(object_keys) else "failed"
        db.commit()
    finally:
        db.close()


@celery_app.task(name="app.tasks.worker_tasks.cleanup_deleted_project")
def cleanup_deleted_project(project_id: str) -> None:
    db = SessionLocal()
    try:
        project = db.get(Project, project_id)
        if not project:
            return
        try:
            delete_project_permanently(db, project=project)
            db.commit()
        except ProjectDeletionError:
            db.rollback()
            project = db.get(Project, project_id)
            if project:
                project.cleanup_status = "failed"
                db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Periodic housekeeping
# ---------------------------------------------------------------------------

_AUDIT_LOG_RETENTION_DAYS = 90
_SOFT_DELETE_RETENTION_DAYS = 7


@celery_app.task(name="app.tasks.worker_tasks.purge_stale_records")
def purge_stale_records() -> None:
    """Periodic task: remove stale audit logs and hard-delete soft-deleted rows.

    Scheduled via Celery Beat (daily at 03:00).
    """
    db = SessionLocal()
    try:
        # 1. Purge old audit logs
        cutoff_audit = sql_text(
            "DELETE FROM audit_logs WHERE ts < NOW() - INTERVAL ':days days'"
        ).bindparams(days=_AUDIT_LOG_RETENTION_DAYS)
        result = db.execute(
            sql_text("DELETE FROM audit_logs WHERE ts < NOW() - make_interval(days => :days)"),
            {"days": _AUDIT_LOG_RETENTION_DAYS},
        )
        audit_deleted = result.rowcount
        logger.info("purge_stale_records: deleted %d audit_logs older than %d days", audit_deleted, _AUDIT_LOG_RETENTION_DAYS)

        # 2. Hard-delete data_items whose parent dataset is soft-deleted and cleaned
        result = db.execute(
            sql_text(
                "DELETE FROM data_items di "
                "USING datasets ds "
                "WHERE di.dataset_id = ds.id "
                "  AND ds.deleted_at IS NOT NULL "
                "  AND ds.cleanup_status = 'done' "
                "  AND ds.deleted_at < NOW() - make_interval(days => :days)"
            ),
            {"days": _SOFT_DELETE_RETENTION_DAYS},
        )
        items_deleted = result.rowcount
        logger.info("purge_stale_records: hard-deleted %d stale data_items", items_deleted)

        # 3. Hard-delete datasets that are soft-deleted and fully cleaned
        result = db.execute(
            sql_text(
                "DELETE FROM datasets "
                "WHERE deleted_at IS NOT NULL "
                "  AND cleanup_status = 'done' "
                "  AND deleted_at < NOW() - make_interval(days => :days)"
            ),
            {"days": _SOFT_DELETE_RETENTION_DAYS},
        )
        datasets_deleted = result.rowcount
        logger.info("purge_stale_records: hard-deleted %d stale datasets", datasets_deleted)

        db.commit()

        # 4. VACUUM to reclaim space (must run outside transaction)
        if audit_deleted or items_deleted or datasets_deleted:
            conn = db.get_bind().connect()
            try:
                conn = conn.execution_options(isolation_level="AUTOCOMMIT")
                conn.execute(sql_text("VACUUM ANALYZE audit_logs"))
                conn.execute(sql_text("VACUUM ANALYZE data_items"))
                conn.execute(sql_text("VACUUM ANALYZE datasets"))
                logger.info("purge_stale_records: VACUUM ANALYZE completed")
            finally:
                conn.close()
    except Exception:
        db.rollback()
        logger.exception("purge_stale_records failed")
        raise
    finally:
        db.close()


@celery_app.task(name="app.tasks.worker_tasks.index_data_item")
def index_data_item(
    workspace_id: str,
    project_id: str,
    data_item_id: str,
    object_key: str,
    filename: str,
) -> None:
    """Download file from S3, extract text, chunk, and vectorize for RAG."""
    import asyncio

    from app.services.document_indexer import index_document
    from app.services.embedding import delete_embeddings_for_data_item
    from app.services.memory_file_context import sync_memory_links_for_data_item
    from app.services.storage import get_s3_client

    logger.info("index_data_item started: item_id=%s, filename=%s", data_item_id, filename)

    db = SessionLocal()
    try:
        item = db.get(DataItem, data_item_id)
        if not item or item.deleted_at is not None:
            return

        if settings.env == "test":
            item.meta_json = {**(item.meta_json or {}), "index_status": "skipped"}
            db.commit()
            return

        if not settings.dashscope_api_key:
            logger.warning("index_data_item skipped: no dashscope_api_key configured (item_id=%s)", data_item_id)
            item.meta_json = {**(item.meta_json or {}), "index_status": "skipped"}
            db.commit()
            return

        s3 = get_s3_client()
        response = s3.get_object(
            Bucket=settings.s3_private_bucket,
            Key=object_key,
        )
        content = response["Body"].read()

        delete_embeddings_for_data_item(db, data_item_id)
        asyncio.run(
            index_document(
                db,
                workspace_id=workspace_id,
                project_id=project_id,
                data_item_id=data_item_id,
                content=content,
                filename=filename,
            ),
        )
        sync_memory_links_for_data_item(
            db,
            workspace_id=workspace_id,
            project_id=project_id,
            data_item_id=data_item_id,
        )
    except Exception:  # noqa: BLE001
        logger.exception("index_data_item failed for item %s", data_item_id)
        db.rollback()
        try:
            item = db.get(DataItem, data_item_id)
            if item:
                item.meta_json = {
                    **(item.meta_json or {}),
                    "index_status": "failed",
                    "index_error": "index_data_item_failed",
                }
                db.commit()
        except Exception:  # noqa: BLE001
            logger.exception("index_data_item could not persist failure state for item %s", data_item_id)
            db.rollback()
    finally:
        db.close()


# Import from unified pipeline to avoid duplication and keep legacy monkeypatch
# hooks in tests wired into the new pipeline implementation.
import app.services.unified_memory_pipeline as unified_memory_pipeline

from app.services.unified_memory_pipeline import (
    _build_memory_extraction_summary,
    _build_memory_write_preview,
    _extract_facts_heuristically,
    _resolve_concept_parent,
    triage_memory,
)


def _merge_memory_extraction_metadata(
    metadata: dict[str, object] | None,
    *,
    processed_facts: list[dict[str, object]] | object = _MEMORY_EXTRACTION_UNSET,
    empty_summary: str | None = None,
    status: str | None = None,
    attempts: int | None = None,
    error: str | None = None,
    run_id: str | None = None,
    learning_run_id: str | None = None,
) -> dict[str, object]:
    existing_meta = dict(metadata or {})

    if processed_facts is not _MEMORY_EXTRACTION_UNSET:
        facts = list(processed_facts or [])
        existing_meta["extracted_facts"] = facts

        summary = _build_memory_extraction_summary(facts) or empty_summary
        preview = _build_memory_write_preview(facts, summary=summary)
        if summary:
            existing_meta["memories_extracted"] = summary
        else:
            existing_meta.pop("memories_extracted", None)
        if preview:
            existing_meta["memory_write_preview"] = preview
        else:
            existing_meta.pop("memory_write_preview", None)

    if status:
        existing_meta["memory_extraction_status"] = status
    if attempts is not None:
        existing_meta["memory_extraction_attempts"] = attempts
    if isinstance(run_id, str) and run_id.strip():
        existing_meta["memory_write_run_id"] = run_id.strip()
    if isinstance(learning_run_id, str) and learning_run_id.strip():
        existing_meta["memory_learning_run_id"] = learning_run_id.strip()
    if isinstance(error, str) and error.strip():
        existing_meta["memory_extraction_error"] = error.strip()
    elif error is not None:
        existing_meta.pop("memory_extraction_error", None)

    if (
        processed_facts is not _MEMORY_EXTRACTION_UNSET
        or status is not None
        or attempts is not None
        or error is not None
    ):
        existing_meta["memory_extraction_updated_at"] = datetime.now(timezone.utc).isoformat()

    return existing_meta


def _set_memory_extraction_state(
    ai_msg: Message | None,
    *,
    processed_facts: list[dict[str, object]] | object = _MEMORY_EXTRACTION_UNSET,
    empty_summary: str | None = None,
    status: str | None = None,
    attempts: int | None = None,
    error: str | None = None,
    run_id: str | None = None,
    learning_run_id: str | None = None,
) -> None:
    if ai_msg is None:
        return
    ai_msg.metadata_json = _merge_memory_extraction_metadata(
        ai_msg.metadata_json if isinstance(ai_msg.metadata_json, dict) else {},
        processed_facts=processed_facts,
        empty_summary=empty_summary,
        status=status,
        attempts=attempts,
        error=error,
        run_id=run_id,
        learning_run_id=learning_run_id,
    )


def _persist_memory_extraction_failure(
    assistant_message_id: str | None,
    *,
    attempts: int,
    error_message: str = MEMORY_EXTRACTION_FAILURE_SUMMARY,
    run_id: str | None = None,
    learning_run_id: str | None = None,
) -> None:
    if not assistant_message_id and not run_id:
        return

    db = SessionLocal()
    try:
        if run_id:
            run = db.get(MemoryWriteRun, run_id)
            if run is not None:
                finalize_memory_write_run(
                    run,
                    status="failed",
                    error=error_message,
                )
        if learning_run_id:
            learning_run = db.get(MemoryLearningRun, learning_run_id)
            if learning_run is not None:
                finalize_memory_learning_run(
                    learning_run,
                    status="failed",
                    stages=merge_learning_stages(
                        learning_run.stages,
                        ["observe", "extract", "consolidate"],
                    ),
                    error=error_message,
                )
        ai_msg = (
            db.query(Message)
            .filter(
                Message.id == assistant_message_id,
                Message.role == "assistant",
            )
            .first()
        )
        if ai_msg is None:
            return
        _set_memory_extraction_state(
            ai_msg,
            processed_facts=[],
            empty_summary=error_message,
            status=MEMORY_EXTRACTION_STATUS_FAILED,
            attempts=attempts,
            error=error_message,
            run_id=run_id,
            learning_run_id=learning_run_id,
        )
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
    finally:
        db.close()


def _persist_memory_extraction_metadata(
    ai_msg: Message | None,
    *,
    processed_facts: list[dict[str, object]] | None,
    empty_summary: str | None = None,
    attempts: int | None = None,
    run_id: str | None = None,
    learning_run_id: str | None = None,
) -> None:
    if ai_msg is None:
        return

    _set_memory_extraction_state(
        ai_msg,
        processed_facts=list(processed_facts or []),
        empty_summary=empty_summary,
        status=MEMORY_EXTRACTION_STATUS_COMPLETED,
        attempts=attempts,
        error="",
        run_id=run_id,
        learning_run_id=learning_run_id,
    )


def _normalize_empty_memory_summary(summary: str | None) -> str:
    normalized = str(summary or "").strip()
    if not normalized or normalized == "no_extractable_facts":
        return "本轮未提取到可保存记忆"
    return normalized



def execute_memory_extraction_job(
    workspace_id: str,
    project_id: str,
    conversation_id: str,
    user_message: str,
    ai_response: str,
    assistant_message_id: str | None = None,
    *,
    max_attempts: int = MEMORY_EXTRACTION_MAX_ATTEMPTS,
) -> bool:
    for attempt_index in range(1, max_attempts + 1):
        succeeded = run_memory_extraction(
            workspace_id,
            project_id,
            conversation_id,
            user_message,
            ai_response,
            assistant_message_id,
            attempt_index=attempt_index,
        )
        if succeeded:
            return True
        if attempt_index < max_attempts:
            time.sleep(min(1.5 * attempt_index, 3.0))

    _persist_memory_extraction_failure(
        assistant_message_id,
        attempts=max_attempts,
        error_message=MEMORY_EXTRACTION_FAILURE_SUMMARY,
    )
    return False


def run_memory_extraction(
    workspace_id: str,
    project_id: str,
    conversation_id: str,
    user_message: str,
    ai_response: str,
    assistant_message_id: str | None = None,
    *,
    attempt_index: int = 1,
) -> bool:
    """Extract factual memories from a conversation turn.
    Called asynchronously after each message exchange."""
    import asyncio

    from app.services.unified_memory_pipeline import (
        PipelineInput,
        PipelineResult,
        SourceContext,
        _load_subject_memory,
        run_pipeline,
    )

    write_run_id: str | None = None
    learning_run_id: str | None = None
    db = SessionLocal()
    try:
        project = (
            db.query(Project)
            .filter(
                Project.id == project_id,
                Project.workspace_id == workspace_id,
                Project.deleted_at.is_(None),
            )
            .first()
        )
        if not project:
            logger.info(
                "memory extraction skipped: project not found",
                extra={"workspace_id": workspace_id, "project_id": project_id},
            )
            return False
        conversation = (
            db.query(Conversation)
            .filter(
                Conversation.id == conversation_id,
                Conversation.project_id == project_id,
                Conversation.workspace_id == workspace_id,
            )
            .first()
        )
        if not conversation and assistant_message_id:
            assistant_message = (
                db.query(Message)
                .filter(
                    Message.id == assistant_message_id,
                    Message.role == "assistant",
                )
                .first()
            )
            if assistant_message:
                conversation = (
                    db.query(Conversation)
                    .filter(
                        Conversation.id == assistant_message.conversation_id,
                        Conversation.project_id == project_id,
                        Conversation.workspace_id == workspace_id,
                    )
                    .first()
                )
                if conversation:
                    conversation_id = conversation.id
        if not conversation:
            logger.info(
                "memory extraction skipped: conversation not found",
                extra={
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "conversation_id": conversation_id,
                    "assistant_message_id": assistant_message_id,
                },
            )
            return False

        ai_msg = None
        source_user_msg = None
        write_run = None
        learning_run = None
        try:
            if assistant_message_id:
                ai_msg = (
                    db.query(Message)
                    .filter(
                        Message.id == assistant_message_id,
                        Message.conversation_id == conversation_id,
                        Message.role == "assistant",
                    )
                    .first()
                )
            else:
                ai_msg = (
                    db.query(Message)
                    .filter(
                        Message.conversation_id == conversation_id,
                        Message.role == "assistant",
                    )
                    .order_by(Message.created_at.desc())
                    .first()
                )
            source_user_query = (
                db.query(Message)
                .filter(
                    Message.conversation_id == conversation_id,
                    Message.role == "user",
                )
                .order_by(Message.created_at.desc())
            )
            if ai_msg is not None:
                source_user_query = source_user_query.filter(Message.created_at <= ai_msg.created_at)
            source_user_msg = source_user_query.first()

            # Stamp ai_msg with pending status
            _set_memory_extraction_state(
                ai_msg,
                status=MEMORY_EXTRACTION_STATUS_PENDING,
                attempts=attempt_index,
                error="",
            )
            db.commit()
        except Exception:  # noqa: BLE001
            ai_msg = None
            source_user_msg = None

        # ── Delegate to unified pipeline ──
        unified_memory_pipeline.triage_memory = triage_memory
        unified_memory_pipeline._resolve_concept_parent = _resolve_concept_parent
        unified_memory_pipeline._extract_facts_heuristically = _extract_facts_heuristically

        conversation_meta = conversation.metadata_json if isinstance(conversation.metadata_json, dict) else {}
        pipeline_input = PipelineInput(
            source_type="chat_message",
            source_text=user_message[:6000],
            source_ref=str(assistant_message_id or conversation_id),
            workspace_id=str(workspace_id),
            project_id=str(project_id),
            user_id=str(conversation.created_by or ""),
            context=SourceContext(
                owner_user_id=str(conversation.created_by or ""),
                conversation_id=str(conversation_id),
                message_id=str(source_user_msg.id) if source_user_msg else None,
                source_conversation_id=str(conversation_id),
                primary_subject_id=str(conversation_meta.get("primary_subject_id") or "").strip() or None,
            ),
            context_text="",
        )

        result = asyncio.run(run_pipeline(db, pipeline_input))

        write_run_id = result.write_run_id
        learning_run_id = result.learning_run_id

        # Stamp results back onto ai_msg for the chat UI
        _persist_memory_extraction_metadata(
            ai_msg,
            processed_facts=result.processed_facts,
            empty_summary=_normalize_empty_memory_summary(result.summary) if not result.processed_facts else None,
            attempts=attempt_index,
            run_id=write_run_id,
            learning_run_id=learning_run_id,
        )
        db.flush()

        # ── Auto-promotion: temporary -> permanent when same fact appears in 2+ conversations ──
        temp_memories = db.query(Memory).filter(
            Memory.project_id == project_id,
            Memory.type == "temporary",
        ).all()

        for mem in temp_memories:
            try:
                similar = db.execute(
                    sql_text("""
                        SELECT COUNT(DISTINCT m.source_conversation_id)
                        FROM memories m
                        JOIN embeddings e ON e.memory_id = m.id
                        WHERE m.project_id = :project_id
                          AND m.id != :memory_id
                          AND m.source_conversation_id != :conv_id
                          AND e.vector IS NOT NULL
                          AND EXISTS (
                              SELECT 1 FROM embeddings e2
                              WHERE e2.memory_id = :memory_id
                                AND e2.vector IS NOT NULL
                                AND 1 - (e.vector <=> e2.vector) > 0.85
                          )
                    """),
                    {
                        "project_id": project_id,
                        "memory_id": mem.id,
                        "conv_id": conversation_id,
                    },
                ).scalar()
            except Exception:  # noqa: BLE001
                continue

            if similar and similar >= 1:
                owner_user_id = None
                if mem.source_conversation_id:
                    source_conversation = (
                        db.query(Conversation.created_by)
                        .filter(
                            Conversation.id == mem.source_conversation_id,
                            Conversation.project_id == project_id,
                            Conversation.workspace_id == workspace_id,
                        )
                        .first()
                    )
                    owner_user_id = source_conversation[0] if source_conversation else None
                if not owner_user_id:
                    continue
                try:
                    subject_memory = _load_subject_memory(
                        db,
                        workspace_id=workspace_id,
                        project_id=project_id,
                        owner_user_id=owner_user_id,
                        subject_id=mem.subject_memory_id,
                    )
                    if subject_memory is None and mem.source_conversation_id:
                        source_conversation = (
                            db.query(Conversation)
                            .filter(
                                Conversation.id == mem.source_conversation_id,
                                Conversation.project_id == project_id,
                                Conversation.workspace_id == workspace_id,
                            )
                            .first()
                        )
                        conversation_meta = (
                            source_conversation.metadata_json
                            if source_conversation and isinstance(source_conversation.metadata_json, dict)
                            else {}
                        )
                        focused_subject_id = str(conversation_meta.get("primary_subject_id") or "").strip() or None
                        subject_memory = _load_subject_memory(
                            db,
                            workspace_id=workspace_id,
                            project_id=project_id,
                            owner_user_id=owner_user_id,
                            subject_id=focused_subject_id,
                        )
                    if subject_memory is None:
                        subject_memory, _ = ensure_project_user_subject(
                            db,
                            project,
                            owner_user_id=owner_user_id,
                        )
                    mem.type = "permanent"
                    mem.node_type = mem.node_type or FACT_NODE_TYPE
                    mem.subject_memory_id = mem.subject_memory_id or subject_memory.id
                    mem.node_status = ACTIVE_NODE_STATUS
                    mem.canonical_key = mem.canonical_key or None
                    mem.source_conversation_id = None
                    mem.metadata_json = normalize_memory_metadata(
                        content=mem.content,
                        category=mem.category,
                        memory_type="permanent",
                        metadata=build_private_memory_metadata(
                            {
                                **(mem.metadata_json or {}),
                                "promoted_by": "auto_repeat",
                                "node_type": mem.node_type or FACT_NODE_TYPE,
                                "node_status": ACTIVE_NODE_STATUS,
                                "subject_memory_id": mem.subject_memory_id or subject_memory.id,
                            },
                            owner_user_id=owner_user_id,
                        ),
                    )
                    mem.canonical_key = str((mem.metadata_json or {}).get("canonical_key") or "").strip() or mem.canonical_key
                    ensure_fact_lineage(mem)
                    apply_temporal_defaults(mem)
                    mem.last_confirmed_at = datetime.now(timezone.utc)
                    refresh_subject_views(
                        db,
                        subject_memory=subject_memory,
                        playbook_source_text=mem.content,
                        playbook_source_memory_ids=[mem.id],
                    )
                except Exception:  # noqa: BLE001
                    continue

        # Edge maintenance already done inside run_pipeline().
        # Check if auto-promotion loop above dirtied any graph objects.
        auto_promo_changed = session_has_pending_graph_mutations(db)
        db.commit()
        # Bump for pipeline changes + any auto-promotion changes
        if result.graph_changed or auto_promo_changed:
            bump_project_memory_graph_revision(workspace_id=workspace_id, project_id=project_id)
        try:
            if settings.env == "test":
                compact_project_memories_task(workspace_id, project_id)
                repair_project_memory_graph_task(workspace_id, project_id)
            else:
                compact_project_memories_task.delay(workspace_id, project_id)
                repair_project_memory_graph_task.delay(workspace_id, project_id)
        except Exception:  # noqa: BLE001
            pass
        return True
    except Exception:  # noqa: BLE001
        logger.exception(
            "memory extraction failed",
            extra={
                "workspace_id": workspace_id,
                "project_id": project_id,
                "conversation_id": conversation_id,
                "assistant_message_id": assistant_message_id,
            },
        )
        db.rollback()
        _persist_memory_extraction_failure(
            assistant_message_id,
            attempts=attempt_index,
            run_id=write_run_id,
            learning_run_id=learning_run_id,
        )
        return False
    finally:
        db.close()



@celery_app.task(name="app.tasks.worker_tasks.extract_memories")
def extract_memories(
    workspace_id: str,
    project_id: str,
    conversation_id: str,
    user_message: str,
    ai_response: str,
    assistant_message_id: str | None = None,
) -> None:
    execute_memory_extraction_job(
        workspace_id,
        project_id,
        conversation_id,
        user_message,
        ai_response,
        assistant_message_id,
    )


@celery_app.task(name="app.tasks.worker_tasks.extract_notebook_page_memories")
def extract_notebook_page_memories(
    workspace_id: str,
    page_id: str,
    user_id: str,
) -> None:
    """Run the full UnifiedMemoryPipeline on a notebook page (async Celery task)."""
    from app.services.note_memory_bridge import extract_memory_candidates_sync

    db = SessionLocal()
    try:
        extraction = extract_memory_candidates_sync(
            db,
            page_id=page_id,
            workspace_id=workspace_id,
            user_id=user_id,
        )
        db.commit()
        if extraction.graph_changed:
            from app.services.memory_graph_events import bump_project_memory_graph_revision
            # Resolve project_id from the extraction's write run
            project_id = None
            if extraction.run and extraction.run.project_id:
                project_id = str(extraction.run.project_id)
            if project_id:
                bump_project_memory_graph_revision(workspace_id=workspace_id, project_id=project_id)
    except Exception:
        logger.exception("Notebook memory extraction failed for page %s", page_id)
        db.rollback()
    finally:
        db.close()


@celery_app.task(name="app.tasks.worker_tasks.ingest_study_asset")
def ingest_study_asset_task(asset_id: str, workspace_id: str, user_id: str) -> None:
    """Run the full study-asset ingestion pipeline (parse -> chunk -> embed -> pages -> memory)."""
    import asyncio

    from app.models import StudyAsset
    from app.services.study_pipeline import ingest_study_asset

    db = SessionLocal()
    try:
        asyncio.run(
            ingest_study_asset(db, asset_id=asset_id, workspace_id=workspace_id, user_id=user_id),
        )
        db.commit()
    except Exception:
        logger.exception("Study asset ingestion failed for %s", asset_id)
        db.rollback()
        asset = db.get(StudyAsset, asset_id)
        if asset:
            asset.status = "failed"
            db.commit()
    finally:
        db.close()


@celery_app.task(name="app.tasks.worker_tasks.repair_project_memory_graph")
def repair_project_memory_graph_task(
    workspace_id: str,
    project_id: str,
) -> None:
    from app.services.memory_graph_repair import repair_project_memory_graph

    db = SessionLocal()
    try:
        repair_summary = repair_project_memory_graph(
            db,
            workspace_id=workspace_id,
            project_id=project_id,
        )
        related_summary = ensure_project_related_edges(
            db,
            workspace_id=workspace_id,
            project_id=project_id,
        )
        prerequisite_summary = ensure_project_prerequisite_edges(
            db,
            workspace_id=workspace_id,
            project_id=project_id,
        )
        graph_changed = (
            any(repair_summary.as_dict().values())
            or any(related_summary.as_dict().values())
            or any(prerequisite_summary.as_dict().values())
        )
        db.commit()
        if graph_changed:
            bump_project_memory_graph_revision(workspace_id=workspace_id, project_id=project_id)
    except Exception:  # noqa: BLE001
        db.rollback()
    finally:
        db.close()


@celery_app.task(name="app.tasks.worker_tasks.compact_project_memories")
def compact_project_memories_task(
    workspace_id: str,
    project_id: str,
) -> None:
    from app.services.memory_compaction import compact_project_memories

    db = SessionLocal()
    try:
        compaction_summary = asyncio.run(
            compact_project_memories(
                db,
                workspace_id=workspace_id,
                project_id=project_id,
            )
        )
        related_summary = ensure_project_related_edges(
            db,
            workspace_id=workspace_id,
            project_id=project_id,
        )
        prerequisite_summary = ensure_project_prerequisite_edges(
            db,
            workspace_id=workspace_id,
            project_id=project_id,
        )
        graph_changed = any(
            (
                compaction_summary.created_summaries,
                compaction_summary.updated_summaries,
                compaction_summary.deleted_summaries,
            )
        ) or any(related_summary.as_dict().values()) or any(prerequisite_summary.as_dict().values())
        db.commit()
        if graph_changed:
            bump_project_memory_graph_revision(workspace_id=workspace_id, project_id=project_id)
    except Exception:  # noqa: BLE001
        db.rollback()
    finally:
        db.close()


def _refresh_project_subject_views(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
) -> dict[str, int]:
    subjects = (
        db.query(Memory)
        .filter(
            Memory.workspace_id == workspace_id,
            Memory.project_id == project_id,
            Memory.node_type == "subject",
        )
        .order_by(Memory.updated_at.desc())
        .all()
    )
    refreshed_subjects = 0
    refreshed_playbooks = 0
    for subject in subjects:
        refresh_subject_views(db, subject_memory=subject)
        refreshed_subjects += 1
        candidate_memories = (
            db.query(Memory)
            .filter(
                Memory.workspace_id == workspace_id,
                Memory.project_id == project_id,
                Memory.subject_memory_id == subject.id,
                Memory.type == "permanent",
            )
            .order_by(Memory.updated_at.desc(), Memory.created_at.desc())
            .all()
        )
        for candidate in candidate_memories[:8]:
            if not is_active_memory(candidate):
                continue
            if not str(candidate.content or "").strip():
                continue
            if not PLAYBOOK_TRIGGER_PATTERN.search(candidate.content):
                continue
            views = refresh_subject_views(
                db,
                subject_memory=subject,
                playbook_source_text=candidate.content,
                playbook_source_memory_ids=[candidate.id],
            )
            if any(view.view_type == "playbook" for view in views):
                refreshed_playbooks += 1
    return {
        "subjects_refreshed": refreshed_subjects,
        "playbooks_refreshed": refreshed_playbooks,
    }


def _backfill_learning_reflection_runs(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
) -> int:
    runs = (
        db.query(MemoryLearningRun)
        .filter(
            MemoryLearningRun.workspace_id == workspace_id,
            MemoryLearningRun.project_id == project_id,
            MemoryLearningRun.status == "completed",
        )
        .order_by(MemoryLearningRun.created_at.desc())
        .all()
    )
    outcomes = (
        db.query(MemoryOutcome)
        .filter(
            MemoryOutcome.workspace_id == workspace_id,
            MemoryOutcome.project_id == project_id,
        )
        .order_by(MemoryOutcome.created_at.desc())
        .all()
    )
    outcomes_by_task_id = {
        outcome.task_id: outcome
        for outcome in outcomes
        if isinstance(outcome.task_id, str) and outcome.task_id.strip()
    }
    outcomes_by_message_id = {
        outcome.message_id: outcome
        for outcome in outcomes
        if isinstance(outcome.message_id, str) and outcome.message_id.strip()
    }
    updated = 0
    for run in runs:
        linked_outcome = None
        if run.outcome_id:
            linked_outcome = db.get(MemoryOutcome, run.outcome_id)
        elif run.task_id:
            linked_outcome = outcomes_by_task_id.get(run.task_id)
        elif run.message_id:
            linked_outcome = outcomes_by_message_id.get(run.message_id)
        if linked_outcome is None:
            continue
        next_stages = merge_learning_stages(run.stages, ["reflect", "reuse"])
        if next_stages == (run.stages or []) and run.outcome_id == linked_outcome.id:
            continue
        run.stages = next_stages
        run.outcome_id = linked_outcome.id
        run.completed_at = run.completed_at or datetime.now(timezone.utc)
        updated += 1
    return updated


def _run_project_memory_sleep_cycle(
    *,
    workspace_id: str,
    project_id: str,
    reflection_backfill: bool = True,
) -> dict[str, object]:
    from app.services.memory_compaction import compact_project_memories
    from app.services.memory_graph_repair import repair_project_memory_graph

    db = SessionLocal()
    try:
        compaction_summary = asyncio.run(
            compact_project_memories(
                db,
                workspace_id=workspace_id,
                project_id=project_id,
            )
        )
        repair_summary = repair_project_memory_graph(
            db,
            workspace_id=workspace_id,
            project_id=project_id,
        )
        subject_summary = _refresh_project_subject_views(
            db,
            workspace_id=workspace_id,
            project_id=project_id,
        )
        reflection_backfilled = (
            _backfill_learning_reflection_runs(
                db,
                workspace_id=workspace_id,
                project_id=project_id,
            )
            if reflection_backfill
            else 0
        )
        related_summary = ensure_project_related_edges(
            db,
            workspace_id=workspace_id,
            project_id=project_id,
        )
        prerequisite_summary = ensure_project_prerequisite_edges(
            db,
            workspace_id=workspace_id,
            project_id=project_id,
        )
        health_summary = refresh_memory_health_signals(
            db,
            workspace_id=workspace_id,
            project_id=project_id,
        )
        graph_changed = any(
            (
                compaction_summary.created_summaries,
                compaction_summary.updated_summaries,
                compaction_summary.deleted_summaries,
                subject_summary["subjects_refreshed"],
                subject_summary["playbooks_refreshed"],
                reflection_backfilled,
                health_summary["updated_memories"],
                health_summary["updated_playbooks"],
            )
        ) or any(repair_summary.as_dict().values()) or any(
            related_summary.as_dict().values()
        ) or any(prerequisite_summary.as_dict().values())
        summary = {
            "workspace_id": workspace_id,
            "project_id": project_id,
            "compaction": {
                "created_summaries": compaction_summary.created_summaries,
                "updated_summaries": compaction_summary.updated_summaries,
                "deleted_summaries": compaction_summary.deleted_summaries,
            },
            "graph_repair": repair_summary.as_dict(),
            "related_edges": related_summary.as_dict(),
            "prerequisite_edges": prerequisite_summary.as_dict(),
            "subject_views": subject_summary,
            "health": health_summary,
            "reflection_backfilled": reflection_backfilled,
        }
        write_audit_log(
            db,
            workspace_id=workspace_id,
            actor_user_id=None,
            action="memory.sleep_cycle_ran",
            target_type="project",
            target_id=project_id,
            meta_json=summary,
        )
        db.commit()
        if graph_changed:
            bump_project_memory_graph_revision(workspace_id=workspace_id, project_id=project_id)
        return summary
    except Exception:
        db.rollback()
        logger.exception(
            "memory sleep cycle failed",
            extra={"workspace_id": workspace_id, "project_id": project_id},
        )
        raise
    finally:
        db.close()


@celery_app.task(name="app.tasks.worker_tasks.run_project_memory_sleep_cycle")
def run_project_memory_sleep_cycle_task(
    workspace_id: str,
    project_id: str,
    reflection_backfill: bool = True,
) -> dict[str, object]:
    return _run_project_memory_sleep_cycle(
        workspace_id=workspace_id,
        project_id=project_id,
        reflection_backfill=reflection_backfill,
    )


@celery_app.task(name="app.tasks.worker_tasks.run_nightly_memory_sleep_cycle")
def run_nightly_memory_sleep_cycle_task() -> dict[str, int]:
    db = SessionLocal()
    try:
        projects = (
            db.query(Project.workspace_id, Project.id)
            .filter(Project.deleted_at.is_(None))
            .order_by(Project.updated_at.desc())
            .all()
        )
    finally:
        db.close()

    processed = 0
    failed = 0
    for workspace_id, project_id in projects:
        try:
            _run_project_memory_sleep_cycle(
                workspace_id=workspace_id,
                project_id=project_id,
                reflection_backfill=True,
            )
            processed += 1
        except Exception:
            failed += 1
    return {"processed_projects": processed, "failed_projects": failed}


@celery_app.task(name="app.tasks.worker_tasks.backfill_project_memory_v2")
def backfill_project_memory_v2_task(
    workspace_id: str,
    project_id: str,
    limit: int | None = None,
) -> dict[str, int]:
    from app.services.memory_backfill import backfill_project_memory_v2

    db = SessionLocal()
    try:
        summary = backfill_project_memory_v2(
            db,
            workspace_id=workspace_id,
            project_id=project_id,
            limit=limit,
        )
        related_summary = ensure_project_related_edges(
            db,
            workspace_id=workspace_id,
            project_id=project_id,
        )
        prerequisite_summary = ensure_project_prerequisite_edges(
            db,
            workspace_id=workspace_id,
            project_id=project_id,
        )
        graph_changed = summary.has_changes() or any(related_summary.as_dict().values()) or any(
            prerequisite_summary.as_dict().values()
        )
        db.commit()
        if graph_changed:
            bump_project_memory_graph_revision(workspace_id=workspace_id, project_id=project_id)
        return summary.as_dict()
    except Exception:  # noqa: BLE001
        db.rollback()
        raise
    finally:
        db.close()


@celery_app.task(name="app.tasks.worker_tasks.process_whiteboard_memories")
def process_whiteboard_memories(
    page_id: str,
    workspace_id: str,
    project_id: str,
    user_id: str,
    elements_json: list,
) -> None:
    """Async Celery task: summarize whiteboard and extract memories."""
    import asyncio

    from app.services.whiteboard_service import extract_whiteboard_memories

    db = SessionLocal()
    try:
        result = asyncio.run(
            extract_whiteboard_memories(
                db,
                page_id=page_id,
                workspace_id=workspace_id,
                project_id=project_id,
                user_id=user_id,
                elements_json=elements_json,
            )
        )
        db.commit()
        pipeline_result = result.get("pipeline_result")
        if pipeline_result and pipeline_result.graph_changed:
            bump_project_memory_graph_revision(
                workspace_id=workspace_id, project_id=project_id,
            )
    except Exception:
        logger.exception("Whiteboard memory extraction failed for page %s", page_id)
        db.rollback()
    finally:
        db.close()


def _run_study_confusion_pipeline(db, pipeline_input) -> None:
    """Isolated sync wrapper so the task can be patched in tests without
    also patching the async pipeline internals."""
    import asyncio
    from app.services.unified_memory_pipeline import run_pipeline
    asyncio.run(run_pipeline(db, pipeline_input))


@celery_app.task(name="app.tasks.worker_tasks.process_study_confusion")
def process_study_confusion_task(
    card_id: str,
    user_id: str,
    workspace_id: str,
    trigger: str,  # "consecutive_failures" | "manual"
) -> None:
    """Write a confusion-memory evidence for a StudyCard the user keeps
    getting wrong. Idempotent: returns early if the card is gone."""
    from app.models import Notebook, StudyCard, StudyDeck
    from app.services.unified_memory_pipeline import (
        PipelineInput,
        SourceContext,
    )

    db = SessionLocal()
    try:
        card = db.get(StudyCard, card_id)
        if not card:
            return
        deck = db.get(StudyDeck, card.deck_id)
        if not deck:
            return
        notebook = db.get(Notebook, deck.notebook_id)
        if not notebook or not notebook.project_id:
            return

        source_text = (
            f"User is confused about this study card (trigger: {trigger}).\n"
            f"Question: {card.front}\n"
            f"Answer: {card.back}\n"
            f"Lapses: {card.lapse_count}, consecutive failures: {card.consecutive_failures}."
        )
        pipeline_input = PipelineInput(
            source_type="study_confusion",
            source_text=source_text[:6000],
            source_ref=str(card.id),
            workspace_id=str(workspace_id),
            project_id=str(notebook.project_id),
            user_id=str(user_id),
            context=SourceContext(owner_user_id=str(user_id)),
            context_text=f"Study confusion ({trigger})",
        )
        _run_study_confusion_pipeline(db, pipeline_input)
    except Exception:
        logger.exception("process_study_confusion_task failed for card %s", card_id)
    finally:
        db.close()
