from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from datetime import datetime, timedelta, timezone

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
from app.services import dashscope_client
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
from app.services.embedding import embed_and_store
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
                media_type=item.media_type,
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
    _canonicalize_fact_text_for_storage as _canonicalize_fact_text_for_storage_impl,
    _extract_facts_heuristically,
    _extract_subject_hint,
    _is_deictic_subject_reference,
    _plan_concept_parent,
    _resolve_concept_parent,
    _upsert_auto_memory_edge,
    _validate_append_parent,
    triage_memory,
)


def _canonicalize_fact_text_for_storage(
    *,
    fact_text: str,
    user_message: str | None = None,
    source_text: str | None = None,
    subject_memory: Memory | None,
    subject_resolution: str,
) -> str:
    return _canonicalize_fact_text_for_storage_impl(
        fact_text=fact_text,
        source_text=source_text if source_text is not None else str(user_message or ""),
        subject_memory=subject_memory,
        subject_resolution=subject_resolution,
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
        unified_memory_pipeline._plan_concept_parent = _plan_concept_parent
        unified_memory_pipeline._validate_append_parent = _validate_append_parent
        unified_memory_pipeline._upsert_auto_memory_edge = _upsert_auto_memory_edge
        unified_memory_pipeline._extract_subject_hint = _extract_subject_hint
        unified_memory_pipeline._is_deictic_subject_reference = _is_deictic_subject_reference
        unified_memory_pipeline._canonicalize_fact_text_for_storage = _canonicalize_fact_text_for_storage

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


# ---------------------------------------------------------------------------
# S5 proactive services: per-project digest generator
# ---------------------------------------------------------------------------


def _materials_empty(kind: str, materials: dict) -> bool:
    """Heuristic: skip row creation when there's nothing to digest."""
    if kind == "daily_digest":
        return (
            not materials.get("action_counts")
            and not materials.get("page_edits")
            and not materials.get("reconfirm_items")
        )
    if kind == "weekly_reflection":
        return (
            not materials.get("action_counts")
            and not materials.get("page_edits")
            and materials.get("study_stats", {}).get("cards_reviewed", 0) == 0
        )
    if kind == "deviation_reminder":
        return not materials.get("goals")
    return False  # relationship_reminder handled via separate fan-out


@celery_app.task(name="app.tasks.worker_tasks.generate_proactive_digest")
def generate_proactive_digest_task(
    project_id: str,
    kind: str,
    period_start_iso: str,
    period_end_iso: str,
) -> str | None:
    """Generate one (or zero, or many for *_reminder) ProactiveDigest rows.

    Idempotent via the unique constraint (project_id, kind, period_start).
    """
    import asyncio as _asyncio
    from datetime import datetime as _dt
    from sqlalchemy.exc import IntegrityError
    from app.models import Membership, ProactiveDigest, Project, Workspace
    from app.services.ai_action_logger import action_log_context
    from app.services.proactive_generator import generate_digest_content
    from app.services.proactive_materials import (
        collect_daily_materials, collect_goal_materials,
        collect_relationship_materials, collect_weekly_materials,
    )

    period_start = _dt.fromisoformat(period_start_iso.replace("Z", "+00:00"))
    period_end = _dt.fromisoformat(period_end_iso.replace("Z", "+00:00"))

    db = SessionLocal()
    try:
        project = db.get(Project, project_id)
        if not project:
            logger.warning(
                "proactive_digest: project not found",
                extra={"project_id": project_id, "kind": kind},
            )
            return None
        workspace = db.get(Workspace, project.workspace_id)
        if not workspace:
            logger.warning(
                "proactive_digest: workspace not found",
                extra={"project_id": project_id, "workspace_id": project.workspace_id, "kind": kind},
            )
            return None
        member = (
            db.query(Membership)
            .filter(Membership.workspace_id == workspace.id)
            .first()
        )
        user_id = member.user_id if member else None
        if not user_id:
            logger.warning(
                "proactive_digest: workspace has no membership",
                extra={"project_id": project_id, "workspace_id": workspace.id, "kind": kind},
            )
            return None

        # Collect materials per-kind
        if kind == "daily_digest":
            materials = collect_daily_materials(
                db, project_id=project_id,
                period_start=period_start, period_end=period_end,
            )
        elif kind == "weekly_reflection":
            materials = collect_weekly_materials(
                db, project_id=project_id,
                period_start=period_start, period_end=period_end,
            )
        elif kind == "deviation_reminder":
            materials = collect_goal_materials(
                db, project_id=project_id,
                period_start=period_start, period_end=period_end,
            )
        elif kind == "relationship_reminder":
            rel_items = collect_relationship_materials(
                db, project_id=project_id, now=period_end,
            )
            materials = {"items": rel_items}
        else:
            return None

        # Skip when nothing to report (daily/weekly/deviation only)
        if kind in ("daily_digest", "weekly_reflection", "deviation_reminder") and _materials_empty(kind, materials):
            return None
        if kind == "relationship_reminder" and not materials["items"]:
            return None

        # Use the action logger for traceability (reuses async context manager)
        async def _async_work() -> list[str]:
            async with action_log_context(
                db,
                workspace_id=str(workspace.id),
                user_id=str(user_id),
                action_type=f"proactive.{kind}",
                scope="project",
                notebook_id=None,
                page_id=None,
                block_id=project_id,
            ) as log:
                log.set_input({"kind": kind,
                               "period_start": period_start_iso,
                               "period_end": period_end_iso})
                inserted_ids: list[str] = []
                if kind in ("daily_digest", "weekly_reflection"):
                    content = await generate_digest_content(
                        kind=kind, materials=materials,
                        project_name=project.name,
                    )
                    row = ProactiveDigest(
                        workspace_id=str(workspace.id),
                        project_id=project_id,
                        user_id=str(user_id),
                        kind=kind,
                        period_start=period_start,
                        period_end=period_end,
                        title=(
                            f"每日摘要 · {period_end.date().isoformat()}"
                            if kind == "daily_digest"
                            else f"每周反思 · {period_end.date().isoformat()}"
                        ),
                        content_markdown=content.get("summary_md", ""),
                        content_json=content,
                        action_log_id=log.log_id,
                    )
                    try:
                        db.add(row); db.commit(); db.refresh(row)
                        inserted_ids.append(row.id)
                    except IntegrityError:
                        db.rollback()
                        logger.info(
                            "proactive_digest: dup (%s, %s, %s) — skipping",
                            project_id, kind, period_start.isoformat(),
                        )
                elif kind == "deviation_reminder":
                    content = await generate_digest_content(
                        kind=kind, materials=materials,
                        project_name=project.name,
                    )
                    for drift in content.get("drifts", []):
                        goal_mid = str(drift.get("goal_memory_id") or "")[:64]
                        row = ProactiveDigest(
                            workspace_id=str(workspace.id),
                            project_id=project_id,
                            user_id=str(user_id),
                            kind=kind,
                            period_start=period_start,
                            period_end=period_end,
                            series_key=goal_mid,
                            title=f"目标偏离：{goal_mid[:20]}",
                            content_markdown=drift.get("drift_reason_md", ""),
                            content_json=drift,
                            action_log_id=log.log_id,
                        )
                        try:
                            db.add(row); db.commit(); db.refresh(row)
                            inserted_ids.append(row.id)
                        except IntegrityError:
                            db.rollback()
                            logger.info(
                                "proactive_digest: dup deviation %s/%s skipped",
                                project_id, goal_mid,
                            )
                elif kind == "relationship_reminder":
                    for item in materials["items"]:
                        series_key = str(item.get("memory_id") or "")[:64]
                        row = ProactiveDigest(
                            workspace_id=str(workspace.id),
                            project_id=project_id,
                            user_id=str(user_id),
                            kind=kind,
                            period_start=period_start,
                            period_end=period_end,
                            series_key=series_key,
                            title=f"久未联系：{item['person_label']}",
                            content_markdown=(
                                f"已有 {item['days_since']} 天未提及。"
                                if item.get("days_since") is not None
                                else "暂无相关记录。"
                            ),
                            content_json=item,
                            action_log_id=log.log_id,
                        )
                        try:
                            db.add(row); db.commit(); db.refresh(row)
                            inserted_ids.append(row.id)
                        except IntegrityError:
                            db.rollback()
                            logger.info(
                                "proactive_digest: dup relationship %s/%s skipped",
                                project_id, series_key,
                            )
                log.set_output({"inserted_ids": inserted_ids, "count": len(inserted_ids)})
            return inserted_ids

        inserted = _asyncio.run(_async_work())
        return inserted[0] if inserted else None
    except Exception:
        logger.exception("generate_proactive_digest_task failed")
        return None
    finally:
        db.close()


# ---------------------------------------------------------------------------
# S5 proactive services: fan-out tasks (daily / weekly / deviation / relationship)
# ---------------------------------------------------------------------------


def _active_project_ids(window_hours: int) -> list[str]:
    """Return project IDs that had any AIActionLog OR NotebookPage edit
    in the last ``window_hours`` hours."""
    from app.models import AIActionLog, Notebook, NotebookPage
    db = SessionLocal()
    try:
        threshold = datetime.now(timezone.utc) - timedelta(hours=window_hours)
        subq_action = (
            db.query(Notebook.project_id)
            .join(AIActionLog, AIActionLog.notebook_id == Notebook.id)
            .filter(AIActionLog.created_at >= threshold)
            .distinct()
        )
        subq_page = (
            db.query(Notebook.project_id)
            .join(NotebookPage, NotebookPage.notebook_id == Notebook.id)
            .filter(NotebookPage.last_edited_at >= threshold)
            .distinct()
        )
        ids: set[str] = set()
        for row in subq_action.all():
            if row[0]:
                ids.add(row[0])
        for row in subq_page.all():
            if row[0]:
                ids.add(row[0])
        return sorted(ids)
    finally:
        db.close()


@celery_app.task(name="app.tasks.worker_tasks.generate_daily_digests")
def generate_daily_digests_task() -> dict[str, int]:
    """Daily fan-out: enqueue per-project daily digest jobs."""
    now = datetime.now(timezone.utc)
    period_start = now - timedelta(hours=24)
    project_ids = _active_project_ids(window_hours=24)
    for pid in project_ids:
        generate_proactive_digest_task.delay(
            pid, "daily_digest",
            period_start.isoformat(), now.isoformat(),
        )
    return {"dispatched": len(project_ids)}


@celery_app.task(name="app.tasks.worker_tasks.generate_weekly_reflections")
def generate_weekly_reflections_task() -> dict[str, int]:
    """Weekly fan-out: enqueue per-project weekly reflection jobs."""
    now = datetime.now(timezone.utc)
    period_start = now - timedelta(days=7)
    project_ids = _active_project_ids(window_hours=24 * 7)
    for pid in project_ids:
        generate_proactive_digest_task.delay(
            pid, "weekly_reflection",
            period_start.isoformat(), now.isoformat(),
        )
    return {"dispatched": len(project_ids)}


def _projects_with_memory_matching(predicate) -> list[str]:
    """Return project IDs where at least one active memory satisfies predicate."""
    from app.models import Memory
    db = SessionLocal()
    try:
        memories = (
            db.query(Memory)
            .filter(Memory.node_status == "active")
            .all()
        )
        ids: set[str] = set()
        for m in memories:
            if predicate(m) and m.project_id:
                ids.add(m.project_id)
        return sorted(ids)
    finally:
        db.close()


@celery_app.task(name="app.tasks.worker_tasks.generate_deviation_reminders")
def generate_deviation_reminders_task() -> dict[str, int]:
    """Deviation reminders: fan-out to projects that have a 'goal' memory
    AND had recent activity (otherwise there's nothing to compare against)."""
    from app.services.memory_metadata import get_memory_kind
    now = datetime.now(timezone.utc)
    period_start = now - timedelta(days=7)
    project_ids = _projects_with_memory_matching(
        lambda m: get_memory_kind(m) == "goal",
    )
    # Also require recent activity — goals alone aren't enough.
    active = set(_active_project_ids(window_hours=24 * 7))
    targets = [pid for pid in project_ids if pid in active]
    for pid in targets:
        generate_proactive_digest_task.delay(
            pid, "deviation_reminder",
            period_start.isoformat(), now.isoformat(),
        )
    return {"dispatched": len(targets)}


@celery_app.task(name="app.tasks.worker_tasks.generate_relationship_reminders")
def generate_relationship_reminders_task() -> dict[str, int]:
    """Relationship reminders: fan-out to projects that have at least one
    person-subject memory."""
    from app.services.memory_metadata import get_subject_kind
    now = datetime.now(timezone.utc)
    period_start = now - timedelta(days=30)
    project_ids = _projects_with_memory_matching(
        lambda m: get_subject_kind(m) == "person",
    )
    for pid in project_ids:
        generate_proactive_digest_task.delay(
            pid, "relationship_reminder",
            period_start.isoformat(), now.isoformat(),
        )
    return {"dispatched": len(project_ids)}


# ---------------------------------------------------------------------------
# S7 Search: NotebookPage embedding maintenance
# ---------------------------------------------------------------------------


MIN_PAGE_TEXT_LEN_FOR_EMBEDDING = 20


@celery_app.task(name="app.tasks.worker_tasks.backfill_notebook_page_embeddings")
def backfill_notebook_page_embeddings_task(
    workspace_id: str | None = None,
    batch_size: int = 50,
) -> dict[str, int]:
    """Embed all NotebookPage rows whose embedding_id IS NULL and whose
    plain_text is long enough. Idempotent."""
    import asyncio as _asyncio
    from app.models import Notebook, NotebookPage

    db = SessionLocal()
    try:
        q = (
            db.query(NotebookPage)
            .join(Notebook, Notebook.id == NotebookPage.notebook_id)
            .filter(NotebookPage.embedding_id.is_(None))
            .filter(NotebookPage.plain_text.isnot(None))
        )
        if workspace_id:
            q = q.filter(Notebook.workspace_id == workspace_id)
        pages = q.limit(batch_size * 10).all()

        total = 0
        succeeded = 0
        failed = 0
        for page in pages:
            text = (page.plain_text or "").strip()
            if len(text) < MIN_PAGE_TEXT_LEN_FOR_EMBEDDING:
                continue
            total += 1
            nb = db.get(Notebook, page.notebook_id)
            if nb is None:
                failed += 1
                continue
            try:
                emb_id = _asyncio.run(embed_and_store(
                    db,
                    workspace_id=str(nb.workspace_id),
                    project_id=str(nb.project_id or ""),
                    chunk_text=text[:4000],
                    auto_commit=False,
                ))
                page.embedding_id = emb_id
                db.add(page)
                db.commit()
                succeeded += 1
            except Exception:
                logger.warning(
                    "backfill_notebook_page_embedding failed for %s",
                    page.id, exc_info=False,
                )
                db.rollback()
                failed += 1
        return {
            "total_processed": total,
            "succeeded": succeeded,
            "failed": failed,
        }
    finally:
        db.close()


@celery_app.task(name="app.tasks.worker_tasks.regenerate_notebook_page_embedding")
def regenerate_notebook_page_embedding_task(page_id: str) -> str | None:
    """Regenerate embedding for one page (called on plain_text change)."""
    import asyncio as _asyncio
    from app.models import Notebook, NotebookPage

    db = SessionLocal()
    try:
        page = db.get(NotebookPage, page_id)
        if page is None:
            return None
        text = (page.plain_text or "").strip()
        if len(text) < MIN_PAGE_TEXT_LEN_FOR_EMBEDDING:
            return None
        nb = db.get(Notebook, page.notebook_id)
        if nb is None:
            return None
        try:
            emb_id = _asyncio.run(embed_and_store(
                db,
                workspace_id=str(nb.workspace_id),
                project_id=str(nb.project_id or ""),
                chunk_text=text[:4000],
                auto_commit=False,
            ))
            page.embedding_id = emb_id
            db.add(page)
            db.commit()
            return emb_id
        except Exception:
            logger.warning(
                "regenerate_notebook_page_embedding failed for %s",
                page_id, exc_info=False,
            )
            db.rollback()
            return None
    finally:
        db.close()


# ---------------------------------------------------------------------------
# S6 Billing — One-time subscription expiry
# ---------------------------------------------------------------------------


@celery_app.task(name="app.tasks.worker_tasks.expire_one_time_subscriptions")
def expire_one_time_subscriptions_task() -> dict[str, int]:
    """Find expired one-time subscriptions, mark canceled, downgrade
    the workspace to free plan, and refresh entitlements. Idempotent."""
    from app.core.entitlements import refresh_workspace_entitlements
    from app.models import Subscription, Workspace

    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        all_rows = (
            db.query(Subscription)
            .filter(Subscription.provider == "stripe_one_time")
            .filter(Subscription.status == "manual")
            .all()
        )
        rows = []
        for sub in all_rows:
            end = sub.current_period_end
            if end is None:
                continue
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)
            if end < now:
                rows.append(sub)
        n = 0
        for sub in rows:
            sub.status = "canceled"
            db.add(sub)
            ws = db.get(Workspace, sub.workspace_id)
            if ws is not None:
                ws.plan = "free"
                db.add(ws)
            db.commit()
            try:
                refresh_workspace_entitlements(db, workspace_id=sub.workspace_id)
            except Exception:
                logger.warning("expire: refresh entitlements failed for %s",
                               sub.workspace_id, exc_info=False)
            n += 1
        return {"expired": n}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Wave 2 A8 — Spec §14 worker task alignment
#
# These wrappers exist so every task the spec names has a concrete
# ``@celery_app.task`` name the platform can reference. Several of them
# delegate to the same service functions used elsewhere in this file
# (UnifiedMemoryPipeline, study_pipeline, related_pages, etc.) and a few
# are still intentionally minimal stubs — they log + return a summary
# dict rather than raise, so callers can schedule them without blowing
# up the worker.
# ---------------------------------------------------------------------------


@celery_app.task(name="app.tasks.worker_tasks.notebook_page_plaintext_task")
def notebook_page_plaintext_task(page_id: str) -> dict[str, object]:
    """Rebuild ``plain_text`` from ``content_json`` for one NotebookPage.

    Spec §14.2 pairs this with the page-edit pipeline; the live code path
    runs the same extraction inline inside ``PATCH /pages/{id}``. Having
    this as its own task lets ops backfill or replay without going
    through the router.
    """
    from app.models import NotebookPage
    from app.routers.notebooks import extract_plain_text

    db = SessionLocal()
    try:
        page = db.get(NotebookPage, page_id)
        if page is None:
            return {"status": "missing", "page_id": page_id}
        page.plain_text = extract_plain_text(page.content_json or {})
        db.add(page)
        db.commit()
        return {"status": "ok", "page_id": page_id, "chars": len(page.plain_text or "")}
    except Exception:
        logger.exception("notebook_page_plaintext_task failed for %s", page_id)
        db.rollback()
        return {"status": "failed", "page_id": page_id}
    finally:
        db.close()


@celery_app.task(name="app.tasks.worker_tasks.notebook_page_summary_task")
def notebook_page_summary_task(page_id: str) -> dict[str, object]:
    """Generate ``summary_text`` + ``ai_keywords_json`` for a page.

    Stub — delegates to whatever summary-generation logic already ships
    under ``app.services`` if it exists, otherwise falls back to a
    truncated plaintext preview so the column is never empty.
    Idempotent.
    """
    from app.models import NotebookPage

    db = SessionLocal()
    try:
        page = db.get(NotebookPage, page_id)
        if page is None:
            return {"status": "missing", "page_id": page_id}
        text = (page.plain_text or "").strip()
        if not text:
            return {"status": "empty", "page_id": page_id}
        # TODO: hook LLM summarizer. For now derive a short heuristic summary.
        first_para = text.split("\n", 1)[0].strip()
        summary = first_para[:240]
        page.summary_text = summary
        # Keywords: naive top-5 words >=4 chars. Cheap placeholder; the
        # real keyword pipeline lives inside notebook_ai_service.
        import re as _re
        from collections import Counter
        words = [w.lower() for w in _re.findall(r"[A-Za-z\u4e00-\u9fa5]{4,}", text)]
        if words:
            top = [w for w, _c in Counter(words).most_common(5)]
            page.ai_keywords_json = top
        db.add(page)
        db.commit()
        return {
            "status": "ok",
            "page_id": page_id,
            "summary_len": len(page.summary_text or ""),
            "keyword_count": len(page.ai_keywords_json or []),
        }
    except Exception:
        logger.exception("notebook_page_summary_task failed for %s", page_id)
        db.rollback()
        return {"status": "failed", "page_id": page_id}
    finally:
        db.close()


@celery_app.task(name="app.tasks.worker_tasks.unified_memory_extract_task")
def unified_memory_extract_task(
    source_type: str,
    source_ref: str,
    source_text: str,
    workspace_id: str,
    project_id: str,
    user_id: str,
    context_text: str = "",
    owner_user_id: str | None = None,
) -> dict[str, object]:
    """Unified entrypoint that funnels arbitrary source content through
    :func:`unified_memory_pipeline.run_pipeline`.

    This wrapper exists so everything the spec calls
    ``unified_memory_extract_task`` has a single Celery task name, even
    though the different per-source taskers (chat, page, whiteboard,
    study-confusion) all live in their own wrappers.
    """
    import asyncio as _asyncio
    from app.services.unified_memory_pipeline import (
        PipelineInput, SourceContext, run_pipeline,
    )

    db = SessionLocal()
    try:
        pipeline_input = PipelineInput(
            source_type=source_type,  # type: ignore[arg-type]
            source_text=(source_text or "")[:6000],
            source_ref=str(source_ref),
            workspace_id=str(workspace_id),
            project_id=str(project_id),
            user_id=str(user_id),
            context=SourceContext(owner_user_id=owner_user_id or str(user_id)),
            context_text=context_text,
        )
        result = _asyncio.run(run_pipeline(db, pipeline_input))
        db.commit()
        if result.graph_changed:
            bump_project_memory_graph_revision(
                workspace_id=workspace_id, project_id=project_id,
            )
        return {
            "status": result.status,
            "item_count": result.item_count,
            "graph_changed": result.graph_changed,
        }
    except Exception:
        logger.exception(
            "unified_memory_extract_task failed for %s/%s",
            source_type, source_ref,
        )
        db.rollback()
        return {"status": "failed", "source_type": source_type, "source_ref": source_ref}
    finally:
        db.close()


@celery_app.task(name="app.tasks.worker_tasks.notebook_page_memory_link_task")
def notebook_page_memory_link_task(page_id: str) -> dict[str, object]:
    """Refresh the NotebookSelectionMemoryLink bridge table for a page.

    A5 wires the bridge synchronously inside ``/pages/{id}/memory/confirm``,
    but this async task lets a maintenance job rebuild the links by
    scanning MemoryEvidence rows whose source episode type is
    ``notebook_page`` and whose ``source_id`` matches the page. Idempotent
    (each ``(page_id, memory_id)`` pair is only inserted once).
    """
    from sqlalchemy import text as _text
    from app.models import (
        MemoryEpisode,
        MemoryEvidence,
        NotebookPage,
        NotebookSelectionMemoryLink,
    )

    db = SessionLocal()
    try:
        page = db.get(NotebookPage, page_id)
        if page is None:
            return {"status": "missing", "page_id": page_id}
        rows = (
            db.query(MemoryEvidence.id, MemoryEvidence.memory_id)
            .join(MemoryEpisode, MemoryEpisode.id == MemoryEvidence.episode_id)
            .filter(MemoryEpisode.source_type == "notebook_page")
            .filter(MemoryEpisode.source_id == page_id)
            .all()
        )
        linked = 0
        for evidence_id, memory_id in rows:
            exists = db.execute(
                _text(
                    "SELECT 1 FROM notebook_selection_memory_links "
                    "WHERE page_id = :p AND memory_id = :m LIMIT 1"
                ),
                {"p": page_id, "m": memory_id},
            ).fetchone()
            if exists:
                continue
            link = NotebookSelectionMemoryLink(
                page_id=page_id,
                memory_id=memory_id,
                evidence_id=evidence_id,
            )
            db.add(link)
            linked += 1
        db.commit()
        return {"status": "ok", "page_id": page_id, "linked": linked}
    except Exception:
        logger.exception("notebook_page_memory_link_task failed for %s", page_id)
        db.rollback()
        return {"status": "failed", "page_id": page_id}
    finally:
        db.close()


@celery_app.task(name="app.tasks.worker_tasks.notebook_page_relevance_refresh_task")
def notebook_page_relevance_refresh_task(page_id: str) -> dict[str, object]:
    """Recompute related-pages ranking for a page.

    Today ``related_pages.get_related`` runs on-demand inside the API,
    so there's nothing to cache yet. This task calls through to the
    service so a scheduled rebuild still has a concrete task name — the
    return value doubles as a health signal.
    """
    from app.models import Notebook, NotebookPage
    from app.services.related_pages import get_related

    db = SessionLocal()
    try:
        page = db.get(NotebookPage, page_id)
        if page is None:
            return {"status": "missing", "page_id": page_id}
        nb = db.get(Notebook, page.notebook_id)
        if nb is None:
            return {"status": "orphan", "page_id": page_id}
        try:
            related = get_related(
                db,
                page_id=page_id,
                workspace_id=str(nb.workspace_id),
                limit=5,
            )
        except Exception:
            logger.warning(
                "notebook_page_relevance_refresh_task: get_related failed for %s",
                page_id, exc_info=False,
            )
            related = {"pages": [], "memory": []}
        return {
            "status": "ok",
            "page_id": page_id,
            "page_count": len(related.get("pages", [])),
            "memory_count": len(related.get("memory", [])),
        }
    finally:
        db.close()


@celery_app.task(name="app.tasks.worker_tasks.whiteboard_memory_extract_task")
def whiteboard_memory_extract_task(
    page_id: str,
    workspace_id: str,
    project_id: str,
    user_id: str,
    elements_json: list | None = None,
) -> dict[str, object]:
    """Thin spec-aligned alias around :func:`process_whiteboard_memories`.

    The underlying task name shipped as ``process_whiteboard_memories``;
    this wrapper just maps the spec-preferred name to it so schedulers
    and API code can use either name.
    """
    process_whiteboard_memories(
        page_id=page_id,
        workspace_id=workspace_id,
        project_id=project_id,
        user_id=user_id,
        elements_json=elements_json or [],
    )
    return {"status": "ok", "page_id": page_id}


@celery_app.task(name="app.tasks.worker_tasks.document_memory_extract_task")
def document_memory_extract_task(
    chunk_id: str,
    workspace_id: str,
    project_id: str,
    user_id: str,
) -> dict[str, object]:
    """Route a StudyChunk (or arbitrary document chunk) through the
    UnifiedMemoryPipeline with ``source_type='uploaded_document'``."""
    import asyncio as _asyncio
    from app.models import StudyAsset, StudyChunk
    from app.services.unified_memory_pipeline import (
        PipelineInput, SourceContext, run_pipeline,
    )

    db = SessionLocal()
    try:
        chunk = db.get(StudyChunk, chunk_id)
        if chunk is None:
            return {"status": "missing", "chunk_id": chunk_id}
        asset = db.get(StudyAsset, chunk.asset_id) if chunk.asset_id else None
        context_text = ""
        if asset is not None:
            context_text = f"Document: {asset.title}"
        pipeline_input = PipelineInput(
            source_type="uploaded_document",
            source_text=(chunk.content or "")[:6000],
            source_ref=str(chunk.id),
            workspace_id=str(workspace_id),
            project_id=str(project_id),
            user_id=str(user_id),
            context=SourceContext(owner_user_id=str(user_id)),
            context_text=context_text,
        )
        result = _asyncio.run(run_pipeline(db, pipeline_input))
        db.commit()
        if result.graph_changed:
            bump_project_memory_graph_revision(
                workspace_id=workspace_id, project_id=project_id,
            )
        return {
            "status": result.status,
            "chunk_id": chunk_id,
            "item_count": result.item_count,
        }
    except Exception:
        logger.exception("document_memory_extract_task failed for %s", chunk_id)
        db.rollback()
        return {"status": "failed", "chunk_id": chunk_id}
    finally:
        db.close()


@celery_app.task(name="app.tasks.worker_tasks.study_asset_chunk_task")
def study_asset_chunk_task(asset_id: str) -> dict[str, object]:
    """Stand-alone chunk task (spec §14.3).

    The monolithic :func:`ingest_study_asset_task` already chunks +
    embeds inline. This wrapper exists so a retry / manual operator can
    rerun just the chunking stage without re-parsing the PDF.
    TODO: split ``study_pipeline.ingest_study_asset`` into independent
    stages so each can be called in isolation.
    """
    logger.info("study_asset_chunk_task(%s) — TODO split stage", asset_id)
    return {"status": "noop", "asset_id": asset_id, "reason": "merged into ingest_study_asset"}


@celery_app.task(name="app.tasks.worker_tasks.study_asset_auto_pages_task")
def study_asset_auto_pages_task(asset_id: str) -> dict[str, object]:
    """Stand-alone auto-pages task (spec §14.3).

    Same story as :func:`study_asset_chunk_task`: auto-page generation
    currently runs inside ``ingest_study_asset``. This stub lets the
    caller ask for a re-run; it returns a no-op marker today.
    """
    logger.info("study_asset_auto_pages_task(%s) — TODO split stage", asset_id)
    return {"status": "noop", "asset_id": asset_id, "reason": "merged into ingest_study_asset"}


@celery_app.task(name="app.tasks.worker_tasks.study_asset_deck_generate_task")
def study_asset_deck_generate_task(
    asset_id: str,
    workspace_id: str,
    user_id: str,
    deck_name: str | None = None,
    max_cards: int = 20,
) -> dict[str, object]:
    """Generate a StudyDeck+StudyCards from a study asset's chunks.

    Stub — the richer generator is currently reachable only through the
    synchronous ``/api/v1/ai/study/flashcards`` endpoint. The async
    version builds a minimal deck of placeholder cards so the workflow
    isn't blocking on the AI call; the deck is marked with
    ``metadata_json["generated_from_asset_id"]`` for traceability.
    """
    import uuid
    from app.models import Notebook, StudyAsset, StudyCard, StudyChunk, StudyDeck

    db = SessionLocal()
    try:
        asset = db.get(StudyAsset, asset_id)
        if asset is None:
            return {"status": "missing", "asset_id": asset_id}
        notebook = db.get(Notebook, asset.notebook_id) if asset.notebook_id else None
        if notebook is None:
            return {"status": "orphan", "asset_id": asset_id}
        deck = StudyDeck(
            id=str(uuid.uuid4()),
            notebook_id=notebook.id,
            name=deck_name or f"{asset.title or 'Asset'} — generated",
            description="Auto-generated deck stub (TODO: hook real LLM flashcard generator).",
            created_by=user_id,
        )
        db.add(deck)
        db.flush()
        chunks = (
            db.query(StudyChunk)
            .filter(StudyChunk.asset_id == asset_id)
            .order_by(StudyChunk.chunk_index.asc())
            .limit(max_cards)
            .all()
        )
        created = 0
        for chunk in chunks:
            snippet = (chunk.content or "").strip()
            if not snippet:
                continue
            front = (chunk.heading or snippet[:80]).strip() or "Question"
            back = snippet[:600]
            card = StudyCard(
                id=str(uuid.uuid4()),
                deck_id=deck.id,
                front=front,
                back=back,
                source_type="asset",
                source_ref=str(chunk.id),
            )
            db.add(card)
            created += 1
        deck.card_count = created
        db.add(deck)
        db.commit()
        return {
            "status": "ok",
            "asset_id": asset_id,
            "deck_id": deck.id,
            "card_count": created,
        }
    except Exception:
        logger.exception("study_asset_deck_generate_task failed for %s", asset_id)
        db.rollback()
        return {"status": "failed", "asset_id": asset_id}
    finally:
        db.close()


@celery_app.task(name="app.tasks.worker_tasks.study_asset_memory_extract_task")
def study_asset_memory_extract_task(
    asset_id: str,
    workspace_id: str,
    project_id: str,
    user_id: str,
) -> dict[str, object]:
    """Fan out document-memory extraction over every chunk in an asset.

    Delegates per-chunk work to :func:`document_memory_extract_task` so
    the unified-pipeline call path stays shared.
    """
    from app.models import StudyChunk

    db = SessionLocal()
    try:
        chunk_ids = [
            row[0]
            for row in db.query(StudyChunk.id)
            .filter(StudyChunk.asset_id == asset_id)
            .all()
        ]
    finally:
        db.close()

    processed = 0
    for cid in chunk_ids:
        try:
            document_memory_extract_task(
                chunk_id=cid,
                workspace_id=workspace_id,
                project_id=project_id,
                user_id=user_id,
            )
            processed += 1
        except Exception:
            logger.warning(
                "study_asset_memory_extract_task: chunk %s failed",
                cid, exc_info=False,
            )
    return {"status": "ok", "asset_id": asset_id, "chunks": processed}


@celery_app.task(name="app.tasks.worker_tasks.study_asset_review_recommendation_task")
def study_asset_review_recommendation_task(
    user_id: str,
    workspace_id: str,
) -> dict[str, object]:
    """Return today's recommended review cards for a user.

    Uses ``StudyCard.next_review_at`` (FSRS-computed) to pick cards due
    in the next 24 h. Pure read; scheduler treats this as a ping.
    """
    from datetime import timedelta as _td

    from app.models import Notebook, StudyCard, StudyDeck

    db = SessionLocal()
    try:
        horizon = datetime.now(timezone.utc) + _td(hours=24)
        due = (
            db.query(StudyCard)
            .join(StudyDeck, StudyDeck.id == StudyCard.deck_id)
            .join(Notebook, Notebook.id == StudyDeck.notebook_id)
            .filter(Notebook.workspace_id == workspace_id)
            .filter(
                (StudyCard.next_review_at.is_(None))
                | (StudyCard.next_review_at <= horizon)
            )
            .limit(50)
            .all()
        )
        return {
            "status": "ok",
            "user_id": user_id,
            "workspace_id": workspace_id,
            "due_card_count": len(due),
            "card_ids": [c.id for c in due[:20]],
        }
    finally:
        db.close()


@celery_app.task(name="app.tasks.worker_tasks.usage_rollup_task")
def usage_rollup_task() -> dict[str, object]:
    """Aggregate AIUsageEvent rows into per-workspace / per-day totals.

    The spec envisions a UsageSummary table; until that lands this task
    just computes the aggregate and logs it. The return dict is enough
    for ops dashboards to scrape.
    """
    from sqlalchemy import func as _func

    from app.models import AIUsageEvent

    db = SessionLocal()
    try:
        # Simple monthly rollup — group by workspace_id.
        since = datetime.now(timezone.utc) - timedelta(days=30)
        rows = (
            db.query(
                AIUsageEvent.workspace_id,
                _func.count(AIUsageEvent.id),
                _func.sum(AIUsageEvent.total_tokens),
            )
            .filter(AIUsageEvent.created_at >= since)
            .group_by(AIUsageEvent.workspace_id)
            .all()
        )
        summary = {
            "workspace_count": len(rows),
            "total_events": sum(int(r[1] or 0) for r in rows),
            "total_tokens": sum(int(r[2] or 0) for r in rows),
        }
        logger.info("usage_rollup_task result: %s", summary)
        return {"status": "ok", **summary}
    finally:
        db.close()


@celery_app.task(name="app.tasks.worker_tasks.subscription_sync_repair_task")
def subscription_sync_repair_task() -> dict[str, object]:
    """Scan non-``free`` subscriptions and flag stale rows.

    Does not call Stripe directly (the webhook handler owns that path);
    instead this task surfaces rows whose ``current_period_end`` is in
    the past but still marked ``active`` / ``trialing``, so ops can fix
    them manually or rerun the webhook replay.
    """
    from app.models import Subscription

    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        rows = (
            db.query(Subscription)
            .filter(Subscription.status.in_(["active", "trialing"]))
            .all()
        )
        stale: list[str] = []
        for sub in rows:
            end = sub.current_period_end
            if end is None:
                continue
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)
            if end < now:
                stale.append(sub.id)
        logger.info("subscription_sync_repair_task flagged %d stale rows", len(stale))
        return {"status": "ok", "stale_count": len(stale), "stale_ids": stale[:20]}
    finally:
        db.close()
