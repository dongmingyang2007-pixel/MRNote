from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import (
    AuditLog,
    Conversation,
    DataItem,
    Dataset,
    Memory,
    MemoryEdge,
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
    CONCEPT_NODE_KIND,
    FACT_NODE_TYPE,
    MEMORY_KIND_EPISODIC,
    MEMORY_KIND_FACT,
    MEMORY_KIND_GOAL,
    MEMORY_KIND_PREFERENCE,
    MEMORY_KIND_PROFILE,
    get_memory_kind,
    get_subject_kind,
    get_subject_memory_id,
    is_active_memory,
    is_concept_memory,
    is_fact_memory,
    is_pinned_memory,
    is_subject_memory,
    normalize_memory_metadata,
    set_manual_parent_binding,
    split_category_segments,
)
from app.services.memory_related_edges import ensure_project_prerequisite_edges, ensure_project_related_edges
from app.services.memory_roots import (
    ensure_project_subject,
    ensure_project_user_subject,
    is_assistant_root_memory,
)
from app.services.memory_visibility import (
    build_private_memory_metadata,
    get_memory_owner_user_id,
    is_private_memory,
)
from app.services.memory_versioning import create_conflicting_fact, create_fact_successor, ensure_fact_lineage
from app.services.memory_v2 import (
    PLAYBOOK_TRIGGER_PATTERN,
    apply_temporal_defaults,
    create_memory_episode,
    create_memory_learning_run,
    create_memory_write_item,
    create_memory_write_run,
    finalize_memory_learning_run,
    finalize_memory_write_run,
    merge_learning_stages,
    record_memory_evidence,
    refresh_memory_health_signals,
    refresh_subject_views,
    update_memory_write_item,
)
from app.services import project_cleanup as project_cleanup_service
from app.services.project_cleanup import ProjectDeletionError, delete_project_permanently
from app.services.runtime_state import runtime_state
from app.services import dashscope_client
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


MEMORY_EXTRACTION_STATUS_PENDING = "pending"
MEMORY_EXTRACTION_STATUS_COMPLETED = "completed"
MEMORY_EXTRACTION_STATUS_FAILED = "failed"
MEMORY_EXTRACTION_FAILURE_SUMMARY = "本轮记忆处理失败，请稍后重试"
MEMORY_EXTRACTION_MAX_ATTEMPTS = 3
_MEMORY_EXTRACTION_UNSET = object()


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
            if item and (item.meta_json or {}).get("upload_status") != "completed":
                if item.deleted_at is None:
                    item.deleted_at = datetime.now(timezone.utc)
                item.meta_json = {
                    **(item.meta_json or {}),
                    "cleanup_marked": True,
                    "upload_status": "abandoned",
                }
                db.commit()
        if item and (item.meta_json or {}).get("upload_status") == "completed" and item.deleted_at is None:
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

    if not settings.dashscope_api_key:
        logger.warning("index_data_item skipped: no dashscope_api_key configured (item_id=%s)", data_item_id)
        return

    db = SessionLocal()
    try:
        item = db.get(DataItem, data_item_id)
        if not item or item.deleted_at is not None:
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
                item.meta_json = {**(item.meta_json or {}), "upload_status": "index_failed"}
                db.commit()
        except Exception:  # noqa: BLE001
            logger.exception("index_data_item could not update status to index_failed for item %s", data_item_id)
            db.rollback()
    finally:
        db.close()


TRIAGE_PROMPT = """你是记忆管理器。判断一条新事实与已有记忆的关系。

新事实：{fact}

已有记忆：
{candidates_formatted}

请选择一个操作：
- create: 新事实是全新话题，与已有记忆无关，应独立创建
- append: 新事实是对某条已有记忆的补充/细节，应挂载为其子记忆
- merge: 新事实和某条已有记忆说的是同一件事，应创建一个更完整的新版本，并把旧事实标记为 superseded
- replace: 新事实表明情况已变化（如搬家、换工作），应创建一个新版本替代旧事实，并把旧事实标记为 superseded
- conflict: 新事实与某条已有记忆存在明显冲突，但两者都应保留为 active 事实
- discard: 新事实和某条已有记忆实质重复，无需保存

输出 JSON：
{{"action": "...", "target_memory_id": "...", "merged_content": "合并/替换后的完整内容", "reason": "一句话解释"}}

规则：
- target_memory_id：create 和 discard 时为 null，其他操作必须指定
- merged_content：仅 merge 和 replace 时需要，其他为 null
- merge 时写出合并后的完整内容，不要丢失原有信息
- replace 时写出替换后的内容，旧信息不再保留
- conflict 时 merged_content 必须为 null"""

_CONCEPT_PARENT_SUPPORTED_KINDS = {
    MEMORY_KIND_FACT,
    MEMORY_KIND_PREFERENCE,
    MEMORY_KIND_GOAL,
}

CONCEPT_TOPIC_PROMPT = """你是记忆结构规划器。给定一条事实及其所属主体，判断是否值得抽出一个更泛化的父级主题节点。

主体：{subject_label}
主体类型：{subject_kind}

事实：{fact}
分类：{category}
记忆类型：{memory_kind}

输出 JSON：
{{"topic": "用于去重的稳定主题词", "label": "展示给用户看的概念名", "confidence": 0.0, "reason": "一句话说明"}}

规则：
- 只有在父级主题和原事实具有明确归属关系时才输出 topic，否则返回 null
- topic 必须稳定、短、可复用，用来避免同主题反复创建多个 concept
- label 用于显示，可以比 topic 更自然一点，但仍需简短，不要整句
- topic 必须比原事实更泛化，但不能跨话题
- 如果只是同义改写、无法安全泛化、或父子关系会显得牵强，返回 {{"topic": null, "label": null, "confidence": 0.0, "reason": "..."}}"""

APPEND_PARENT_VALIDATION_PROMPT = """你是记忆层级校验器。判断“候选记忆”能不能作为“新事实”的父节点。

候选记忆：{candidate}
候选分类：{candidate_category}
新事实：{fact}
新事实分类：{fact_category}
记忆类型：{memory_kind}

输出 JSON：
{{"relation": "parent|sibling|duplicate|unrelated", "reason": "一句话说明"}}

规则：
- 只有候选记忆明显比新事实更泛化、且新事实天然归属于它时，relation 才能是 parent
- 如果两者是同一主题下的并列细项，返回 sibling
- 如果两者本质是同一事实，只是表述不同，返回 duplicate
- 如果话题并不构成稳定父子关系，返回 unrelated"""


async def triage_memory(
    fact: str,
    candidates: list[dict],
) -> dict:
    """Call lightweight LLM to decide how to file a new fact against existing memories.

    Returns {"action": "create|append|merge|replace|conflict|discard",
             "target_memory_id": str | None,
             "merged_content": str | None,
             "reason": str | None}
    """
    from app.core.config import settings

    candidates_formatted = "\n".join(
        f"- ID: {c['memory_id']} | 分类: {c['category']} | 内容: {c['content']}"
        for c in candidates
    )

    prompt = TRIAGE_PROMPT.format(
        fact=fact,
        candidates_formatted=candidates_formatted,
    )

    fallback = {"action": "create", "target_memory_id": None, "merged_content": None, "reason": None}

    try:
        raw = await dashscope_client.chat_completion(
            [{"role": "user", "content": prompt}],
            model=settings.memory_triage_model,
            temperature=0.1,
            max_tokens=256,
        )
    except Exception:  # noqa: BLE001
        return fallback

    # Parse JSON (handle markdown code blocks)
    json_match = re.search(r"\{.*\}", raw.strip(), re.DOTALL)
    if not json_match:
        return fallback

    try:
        decision = json.loads(json_match.group(0))
    except (json.JSONDecodeError, ValueError):
        return fallback

    if decision.get("action") not in ("create", "append", "merge", "replace", "conflict", "discard"):
        return fallback

    return decision


def _normalize_category_segments(category: str) -> list[str]:
    return [
        segment.strip().lower()
        for segment in str(category or "").split(".")
        if segment and segment.strip()
    ]


def _shared_category_prefix_length(left: str, right: str) -> int:
    left_segments = _normalize_category_segments(left)
    right_segments = _normalize_category_segments(right)
    shared = 0
    for left_segment, right_segment in zip(left_segments, right_segments, strict=False):
        if left_segment != right_segment:
            break
        shared += 1
    return shared


def _normalize_text_key(value: str) -> str:
    normalized = re.sub(r"\s+", "", str(value or "").strip().lower())
    return re.sub(r"[，。、“”‘’\"'`()（）,.!?！？:：;；\-_/\\]+", "", normalized)


def _rebind_memory_under_parent(memory: Memory, parent: Memory) -> None:
    parent_memory_id = parent.id
    memory.parent_memory_id = parent_memory_id
    if is_subject_memory(parent):
        memory.subject_memory_id = parent.id
    elif parent.subject_memory_id:
        memory.subject_memory_id = parent.subject_memory_id
    metadata = dict(memory.metadata_json or {})
    if is_private_memory(parent):
        metadata = build_private_memory_metadata(
            metadata,
            owner_user_id=get_memory_owner_user_id(parent),
        )
    memory.metadata_json = normalize_memory_metadata(
        content=memory.content,
        category=memory.category,
        memory_type=memory.type,
        metadata=set_manual_parent_binding(
            metadata,
            parent_memory_id=parent_memory_id,
        ),
    )


def _is_structural_parent_memory(memory: Memory | dict[str, object] | None) -> bool:
    return (
        is_assistant_root_memory(memory)
        or is_subject_memory(memory)
        or is_concept_memory(memory)
    )


_FACT_LEADING_MODIFIER_PATTERN = r"(?:也|很|还|都|最|特别|真的|平时|一直|常常|经常|通常|比较|更|挺|蛮|还挺)*"
_FIRST_PERSON_FACT_PREFIX_PATTERN = re.compile(
    rf"^(?:我|本人)(?={_FACT_LEADING_MODIFIER_PATTERN}(?:喜欢|偏好|热爱|爱喝|常喝|爱吃|常吃|计划|打算|准备|希望|想要|是|在|有))"
)
_STABLE_PREFERENCE_FACT_PATTERN = re.compile(
    rf"^(?:用户|我|本人){_FACT_LEADING_MODIFIER_PATTERN}(?:喜欢|偏好|热爱|爱喝|常喝|爱吃|常吃)"
)
_STABLE_GOAL_FACT_PATTERN = re.compile(
    rf"^(?:用户|我|本人){_FACT_LEADING_MODIFIER_PATTERN}(?:计划|打算|准备|希望|想要)"
)
_QUOTED_SUBJECT_PATTERN = re.compile(r"[《“\"]([^》”\"]{2,48})[》”\"]")
_SUBJECT_REFERENCE_HINTS = (
    "这个角色",
    "这个人物",
    "这位人物",
    "这个人",
    "这个人设",
    "这个设定",
    "这个背景",
    "这本书",
    "这门课",
    "这个课程",
    "这个项目",
    "这个理论",
    "这个模型",
    "这个框架",
    "这篇论文",
    "这个设备",
    "这套系统",
    "this book",
    "this course",
    "this project",
    "this theory",
    "this model",
    "this paper",
)
_SUBJECT_KIND_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("book", ("这本书", "书里", "书中", "章节", "作者", "book", "chapter")),
    ("course", ("这门课", "课程", "讲义", "作业", "课堂", "course", "lesson")),
    ("project", ("项目", "工程", "系统", "平台", "仓库", "repo", "app", "应用", "产品")),
    ("theory", ("理论", "模型", "框架", "定律", "定理", "算法", "theory", "model", "framework")),
    ("paper", ("论文", "paper", "arxiv", "preprint")),
    ("device", ("设备", "仪器", "手机", "电脑", "相机", "机器人", "device", "hardware")),
    ("person", ("老师", "教授", "作者", "人物", "传记", "professor", "author")),
    ("domain", ("学科", "领域", "数学", "物理", "化学", "生物", "历史", "哲学", "拓扑", "代数")),
)
_CATEGORY_SUBJECT_KIND_HINTS: tuple[tuple[str, str], ...] = (
    ("书", "book"),
    ("课程", "course"),
    ("课", "course"),
    ("项目", "project"),
    ("工程", "project"),
    ("论文", "paper"),
    ("理论", "theory"),
    ("模型", "theory"),
    ("框架", "theory"),
    ("设备", "device"),
    ("硬件", "device"),
    ("学科", "domain"),
    ("领域", "domain"),
)
_GENERIC_SUBJECT_LABELS = {
    "这个",
    "这位",
    "那个",
    "那位",
    "这个角色",
    "这个人物",
    "这个人",
    "这本书",
    "这个项目",
    "这个理论",
    "这门课",
    "课程",
    "项目",
    "理论",
    "模型",
    "框架",
    "论文",
    "设备",
    "系统",
}
_GENERIC_SUBJECT_QUERY_PATTERNS: tuple[tuple[re.Pattern[str], str | None], ...] = (
    (
        re.compile(
            r"^(?:(?:最近|今天|突然|忽然|刚刚|现在|一直|我|又|还|再)\s*){0,4}(?:想聊|又想聊|还想聊|想再聊聊)\s*([A-Za-z0-9\u4e00-\u9fff·._\-]{2,48})"
        ),
        None,
    ),
    (
        re.compile(
            r"^(?:再)?(?:关于|聊聊|说说|讲讲|介绍(?:一下)?|科普(?:一下)?|分析(?:一下)?|讨论(?:一下)?|看看|想了解|想知道|研究(?:一下)?)\s*([A-Za-z0-9\u4e00-\u9fff·._\-]{2,48})"
        ),
        None,
    ),
    (
        re.compile(
            r"([A-Za-z0-9\u4e00-\u9fff·._\-]{2,48})的(?:[^，。！？,.!?]{0,24})?(?:设定|剧情|背景|技能|能力)"
        ),
        None,
    ),
    (
        re.compile(
            r"([A-Za-z0-9\u4e00-\u9fff·._\-]{2,48})(?:为什么|怎么样|是谁|是什么|如何)"
        ),
        None,
    ),
    (
        re.compile(
            r"([A-Za-z0-9\u4e00-\u9fff·._\-]{2,48})(?:这个|这位)?(角色|人物|人|作品|游戏|动漫)"
        ),
        None,
    ),
)
_SUBJECT_SUFFIX_KIND_HINTS: dict[str, str] = {
    "角色": "person",
    "人物": "person",
    "人": "person",
    "作品": "custom",
    "游戏": "project",
    "动漫": "custom",
}
_BEHAVIORAL_INTEREST_QUERY_HINTS = (
    "?",
    "？",
    "关于",
    "聊聊",
    "说说",
    "讲讲",
    "介绍",
    "科普",
    "分析",
    "讨论",
    "想了解",
    "想知道",
    "为什么",
    "如何",
    "怎么",
    "设定",
    "剧情",
    "背景",
    "技能",
    "能力",
    "是谁",
    "是什么",
)
_BEHAVIORAL_INTEREST_CATEGORY_BY_KIND: dict[str, str] = {
    "book": "偏好.关注.书籍",
    "course": "偏好.关注.课程",
    "project": "偏好.关注.项目",
    "theory": "偏好.关注.理论",
    "paper": "偏好.关注.论文",
    "device": "偏好.关注.设备",
    "person": "偏好.关注.人物",
    "domain": "偏好.关注.领域",
}
_NON_USER_FACT_PREDICATE_PREFIXES = (
    "是",
    "有",
    "在",
    "很",
    "比较",
    "更",
    "最",
    "并",
    "会",
    "能",
    "可",
    "让人",
    "令人",
    "显得",
    "看起来",
    "属于",
    "来自",
    "位于",
    "放在",
    "拥有",
    "带有",
    "不是",
    "并不",
)


def _normalize_extracted_fact_text(value: str) -> str:
    normalized = re.sub(r"^[\-\*\u2022]+\s*", "", str(value or "").strip())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    normalized = _FIRST_PERSON_FACT_PREFIX_PATTERN.sub("用户", normalized)
    return normalized


def _looks_like_predicate_only_fact(value: str) -> bool:
    normalized = str(value or "").strip()
    if not normalized:
        return False
    return normalized.startswith(_NON_USER_FACT_PREDICATE_PREFIXES)


def _canonicalize_fact_text_for_storage(
    *,
    fact_text: str,
    user_message: str,
    subject_memory: Memory | None,
    subject_resolution: str,
) -> str:
    normalized = _normalize_extracted_fact_text(fact_text)
    if not normalized or _looks_like_user_fact(normalized) or subject_memory is None:
        return normalized

    subject_label = _normalize_subject_label(subject_memory.content)
    subject_kind = get_subject_kind(subject_memory)
    if not subject_label or subject_kind == "user" or subject_label in normalized:
        return normalized

    rewritten = normalized
    prefix_replacements = (
        ("她的", f"{subject_label}的"),
        ("他的", f"{subject_label}的"),
        ("它的", f"{subject_label}的"),
        ("TA的", f"{subject_label}的"),
        ("ta的", f"{subject_label}的"),
        ("这个角色的", f"{subject_label}的"),
        ("这个人物的", f"{subject_label}的"),
        ("这个人的", f"{subject_label}的"),
        ("这位人物的", f"{subject_label}的"),
        ("这位的", f"{subject_label}的"),
        ("该角色的", f"{subject_label}的"),
        ("该人物的", f"{subject_label}的"),
        ("该人的", f"{subject_label}的"),
        ("这个人设", f"{subject_label}的人设"),
        ("这个设定", f"{subject_label}的设定"),
        ("这个背景", f"{subject_label}的背景"),
        ("她", subject_label),
        ("他", subject_label),
        ("它", subject_label),
        ("TA", subject_label),
        ("ta", subject_label),
        ("这个角色", subject_label),
        ("这个人物", subject_label),
        ("这个人", subject_label),
        ("这位人物", subject_label),
        ("这位", subject_label),
        ("该角色", subject_label),
        ("该人物", subject_label),
        ("该人", subject_label),
    )
    for source, target in prefix_replacements:
        if rewritten.startswith(source):
            rewritten = f"{target}{rewritten[len(source):]}"
            break

    if rewritten == normalized:
        inline_replacements = (
            ("她的", f"{subject_label}的"),
            ("他的", f"{subject_label}的"),
            ("它的", f"{subject_label}的"),
            ("TA的", f"{subject_label}的"),
            ("ta的", f"{subject_label}的"),
            ("这个角色的", f"{subject_label}的"),
            ("这个人物的", f"{subject_label}的"),
            ("这个人的", f"{subject_label}的"),
            ("这位人物的", f"{subject_label}的"),
            ("该角色的", f"{subject_label}的"),
            ("该人物的", f"{subject_label}的"),
            ("该人的", f"{subject_label}的"),
        )
        for source, target in inline_replacements:
            rewritten = rewritten.replace(source, target)

    if (
        subject_label not in rewritten
        and (
            _is_deictic_subject_reference(user_message)
            or subject_resolution in {"conversation_focus_subject", "non_user_focus_fallback"}
        )
        and _looks_like_predicate_only_fact(rewritten)
    ):
        rewritten = f"{subject_label}{rewritten}"

    return _normalize_extracted_fact_text(rewritten)


def _normalize_subject_label(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(value or "").strip())
    cleaned = cleaned.strip("，。、“”‘’\"'`()（）[]【】<>《》:：;；,.!?！？")
    if not cleaned or cleaned in _GENERIC_SUBJECT_LABELS:
        return ""
    if re.match(r"^(?:她|他|它|TA|ta)(?:$|的)", cleaned):
        return ""
    if re.match(r"^(?:这个|这位|该)(?:$|角色|人物|人|人设|设定|背景)", cleaned):
        return ""
    if len(cleaned) > 48:
        return ""
    return cleaned


def _trim_generic_subject_candidate(value: str) -> str:
    cleaned = str(value or "").strip()
    cleaned = re.sub(r"^(?:还有|另外|顺便|以及|再(?:聊聊|讲讲|说说)?)", "", cleaned).strip()
    cleaned = re.sub(
        r"的(?:设定|剧情|背景|技能|能力)(?:和(?:设定|剧情|背景|技能|能力))*$",
        "",
        cleaned,
    )
    cleaned = re.sub(
        r"(?:这个|这位)?(?:角色|人物|人|作品|游戏|动漫)(?:的?(?:设定|剧情|背景|技能|能力))?$",
        "",
        cleaned,
    )
    cleaned = re.sub(r"(?:是谁|是什么|怎么样|如何|为什么|吗|呢|啊|呀|吧)$", "", cleaned)
    cleaned = re.sub(r"(?:的设定|的剧情|的背景|的技能|的能力)$", "", cleaned)
    return _normalize_subject_label(cleaned)


def _looks_like_user_fact(fact_text: str) -> bool:
    normalized = str(fact_text or "").strip()
    return bool(
        normalized
        and (
            normalized.startswith("用户")
            or normalized.startswith("我")
            or normalized.startswith("本人")
        )
    )


def _is_deictic_subject_reference(text: str) -> bool:
    haystack = str(text or "").strip().lower()
    return any(hint in haystack for hint in _SUBJECT_REFERENCE_HINTS)


def _infer_subject_kind(*values: str) -> str | None:
    haystack = "\n".join(str(value or "").strip().lower() for value in values if str(value or "").strip())
    if not haystack:
        return None
    for token, kind in _CATEGORY_SUBJECT_KIND_HINTS:
        if token in haystack:
            return kind
    for kind, hints in _SUBJECT_KIND_KEYWORDS:
        if any(hint in haystack for hint in hints):
            return kind
    return None


def _extract_subject_hint(*, text: str, category: str) -> tuple[str | None, str | None]:
    raw_text = str(text or "").strip()
    if not raw_text:
        return None, None

    for match in _QUOTED_SUBJECT_PATTERN.finditer(raw_text):
        label = _normalize_subject_label(match.group(1))
        if not label:
            continue
        kind = _infer_subject_kind(raw_text, category) or "custom"
        return label, kind

    named_patterns: tuple[tuple[re.Pattern[str], str], ...] = (
        (
            re.compile(r"(?:项目|工程|系统|平台|应用|工具|产品)[：:\s]*([A-Za-z0-9\u4e00-\u9fff._\-]{2,40})"),
            "project",
        ),
        (
            re.compile(r"(?:课程|这门课|课题|讲义)[：:\s]*([A-Za-z0-9\u4e00-\u9fff._\-]{2,40})"),
            "course",
        ),
        (
            re.compile(r"(?:理论|模型|框架|定律|定理)[：:\s]*([A-Za-z0-9\u4e00-\u9fff._\-]{2,40})"),
            "theory",
        ),
        (
            re.compile(r"(?:论文|paper)[：:\s]*([A-Za-z0-9\u4e00-\u9fff._\-]{2,40})"),
            "paper",
        ),
        (
            re.compile(r"(?:设备|仪器|机器人)[：:\s]*([A-Za-z0-9\u4e00-\u9fff._\-]{2,40})"),
            "device",
        ),
    )
    for pattern, default_kind in named_patterns:
        match = pattern.search(raw_text)
        if not match:
            continue
        label = _normalize_subject_label(match.group(1))
        if not label:
            continue
        kind = _infer_subject_kind(raw_text, category) or default_kind
        return label, kind

    for pattern, default_kind in _GENERIC_SUBJECT_QUERY_PATTERNS:
        match = pattern.search(raw_text)
        if not match:
            continue
        label = _trim_generic_subject_candidate(match.group(1))
        if not label:
            continue
        suffix = match.group(2) if match.lastindex and match.lastindex >= 2 else None
        kind = (
            _infer_subject_kind(raw_text, category)
            or _SUBJECT_SUFFIX_KIND_HINTS.get(str(suffix or "").strip(), "")
            or default_kind
            or "custom"
        )
        return label, kind

    return None, None


def _subject_visible_to_owner(subject: Memory, *, owner_user_id: str | None) -> bool:
    if not is_private_memory(subject):
        return True
    return get_memory_owner_user_id(subject) == owner_user_id


def _score_subject_match(subject: Memory, *, text_key: str, subject_kind: str | None) -> int:
    label_key = _normalize_text_key(subject.content)
    if not label_key or not text_key:
        return 0
    score = 0
    if label_key in text_key:
        score += min(12, len(label_key))
    canonical_key = _normalize_text_key(subject.canonical_key or "")
    if canonical_key and canonical_key in text_key:
        score += 4
    existing_kind = get_subject_kind(subject)
    if subject_kind and existing_kind == subject_kind:
        score += 3
    return score


def _resolve_subject_memory_for_fact(
    db,
    *,
    project: Project,
    conversation: Conversation,
    user_message: str,
    fact_text: str,
    fact_category: str,
) -> tuple[Memory, bool, str]:
    user_subject, user_subject_changed = ensure_project_user_subject(
        db,
        project,
        owner_user_id=conversation.created_by,
    )
    subject_memories = [
        memory
        for memory in (
            db.query(Memory)
            .filter(
                Memory.workspace_id == project.workspace_id,
                Memory.project_id == project.id,
                Memory.node_type == "subject",
            )
            .all()
        )
        if _subject_visible_to_owner(memory, owner_user_id=conversation.created_by)
    ]
    subjects_by_id = {memory.id: memory for memory in subject_memories}
    combined_text = "\n".join(
        value for value in [user_message, fact_text, fact_category] if str(value or "").strip()
    )
    combined_key = _normalize_text_key(combined_text)
    subject_label, subject_kind = _extract_subject_hint(text=combined_text, category=fact_category)

    best_subject: Memory | None = None
    best_score = 0
    for subject in subject_memories:
        score = _score_subject_match(subject, text_key=combined_key, subject_kind=subject_kind)
        if score > best_score:
            best_subject = subject
            best_score = score
    if best_subject is not None and best_score >= 5:
        return best_subject, user_subject_changed, "lexical_subject_match"

    conversation_meta = conversation.metadata_json if isinstance(conversation.metadata_json, dict) else {}
    primary_subject_id = str(conversation_meta.get("primary_subject_id") or "").strip()
    primary_subject = subjects_by_id.get(primary_subject_id) if primary_subject_id else None
    if (
        primary_subject is not None
        and get_subject_kind(primary_subject) != "user"
        and not _looks_like_user_fact(fact_text)
        and (_is_deictic_subject_reference(user_message) or not subject_label)
    ):
        return primary_subject, user_subject_changed, "conversation_focus_subject"

    if subject_label and not _looks_like_user_fact(fact_text):
        subject_kind = subject_kind or _infer_subject_kind(user_message, fact_text, fact_category) or "custom"
        subject_memory, subject_changed = ensure_project_subject(
            db,
            project,
            subject_kind=subject_kind,
            label=subject_label,
            owner_user_id=conversation.created_by,
        )
        return subject_memory, user_subject_changed or subject_changed, "created_or_reused_subject"

    if primary_subject is not None and get_subject_kind(primary_subject) != "user" and not _looks_like_user_fact(fact_text):
        return primary_subject, user_subject_changed, "non_user_focus_fallback"

    return user_subject, user_subject_changed, "user_subject_fallback"


def _load_subject_memory(
    db,
    *,
    workspace_id: str,
    project_id: str,
    owner_user_id: str | None,
    subject_id: str | None,
) -> Memory | None:
    if not subject_id:
        return None
    subject = (
        db.query(Memory)
        .filter(
            Memory.id == subject_id,
            Memory.workspace_id == workspace_id,
            Memory.project_id == project_id,
        )
        .first()
    )
    if subject is None or not is_subject_memory(subject):
        return None
    if not _subject_visible_to_owner(subject, owner_user_id=owner_user_id):
        return None
    return subject


def _query_signals_topic_interest(text: str) -> bool:
    haystack = str(text or "").strip().lower()
    if not haystack:
        return False
    return any(token in haystack for token in _BEHAVIORAL_INTEREST_QUERY_HINTS)


def _message_mentions_subject_label(text: str, *, label_key: str) -> bool:
    if not label_key:
        return False
    return label_key in _normalize_text_key(text)


def _count_subject_mentions_by_conversation(
    db,
    *,
    workspace_id: str,
    project_id: str,
    owner_user_id: str | None,
    label_key: str,
    limit: int = 120,
) -> dict[str, int]:
    if not owner_user_id or not label_key:
        return {}

    rows = (
        db.query(Message.content, Message.conversation_id)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .filter(
            Conversation.workspace_id == workspace_id,
            Conversation.project_id == project_id,
            Conversation.created_by == owner_user_id,
            Message.role == "user",
        )
        .order_by(Message.created_at.desc())
        .limit(limit)
        .all()
    )

    counts: dict[str, int] = {}
    for content, message_conversation_id in rows:
        if not _message_mentions_subject_label(content, label_key=label_key):
            continue
        counts[message_conversation_id] = counts.get(message_conversation_id, 0) + 1
    return counts


def _facts_already_capture_subject_interest(
    facts: list[dict[str, object]],
    *,
    label_key: str,
) -> bool:
    if not label_key:
        return False
    for fact in facts:
        fact_text = _normalize_text_key(str(fact.get("fact") or ""))
        if not fact_text or label_key not in fact_text:
            continue
        category = str(fact.get("category") or "")
        if any(token in fact_text for token in ("喜欢", "偏好", "热爱", "感兴趣")) or "偏好" in category:
            return True
    return False


def _build_behavioral_interest_fact_text(subject_label: str) -> str:
    normalized_label = _normalize_subject_label(subject_label)
    if not normalized_label:
        return ""
    return f"用户对{normalized_label}感兴趣。"


def _build_behavioral_interest_category(subject_kind: str | None) -> str:
    normalized_kind = str(subject_kind or "").strip().lower()
    return _BEHAVIORAL_INTEREST_CATEGORY_BY_KIND.get(normalized_kind, "偏好.关注")


def _build_behavioral_interest_reason(
    *,
    subject_label: str,
    same_conversation_turns: int,
    distinct_conversations: int,
) -> str:
    if distinct_conversations >= 2:
        return (
            f"基于用户在 {distinct_conversations} 个对话里反复围绕「{subject_label}」提问，"
            "推断这是稳定关注主题。"
        )
    return f"基于用户在当前对话中连续 {same_conversation_turns} 轮围绕「{subject_label}」提问，推断这是持续关注主题。"


def _infer_behavioral_interest_fact(
    db,
    *,
    project: Project,
    conversation: Conversation,
    workspace_id: str,
    project_id: str,
    user_message: str,
    extracted_facts: list[dict[str, object]],
) -> tuple[dict[str, object] | None, bool]:
    if not _query_signals_topic_interest(user_message):
        return None, False

    conversation_meta = conversation.metadata_json if isinstance(conversation.metadata_json, dict) else {}
    primary_subject_id = str(conversation_meta.get("primary_subject_id") or "").strip() or None
    primary_subject = _load_subject_memory(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        owner_user_id=conversation.created_by,
        subject_id=primary_subject_id,
    )
    if primary_subject is not None and get_subject_kind(primary_subject) == "user":
        primary_subject = None

    subject = None
    subject_label = ""
    subject_kind: str | None = None
    current_message_is_lexical_hit = False

    if primary_subject is not None:
        subject = primary_subject
        subject_label = primary_subject.content.strip()
        subject_kind = get_subject_kind(primary_subject)
        label_key = _normalize_text_key(subject_label)
        current_message_is_lexical_hit = _message_mentions_subject_label(user_message, label_key=label_key)
        if not current_message_is_lexical_hit and not _is_deictic_subject_reference(user_message):
            subject = None
            subject_label = ""
            subject_kind = None

    if subject is None:
        subject_label, subject_kind = _extract_subject_hint(text=user_message, category="偏好.关注")
        if not subject_label:
            return None, False

    label_key = _normalize_text_key(subject_label)
    if not label_key or _facts_already_capture_subject_interest(extracted_facts, label_key=label_key):
        return None, False

    mention_counts = _count_subject_mentions_by_conversation(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        owner_user_id=conversation.created_by,
        label_key=label_key,
    )
    same_conversation_turns = mention_counts.get(conversation.id, 0)
    distinct_conversations = len(mention_counts)
    if subject is not None and not current_message_is_lexical_hit and _is_deictic_subject_reference(user_message):
        same_conversation_turns += 1
        if conversation.id not in mention_counts:
            distinct_conversations += 1

    if distinct_conversations >= 2 or same_conversation_turns >= 3:
        importance = 0.92
    elif same_conversation_turns >= 2:
        importance = 0.82
    else:
        return None, False

    subject_changed = False
    if subject is None:
        subject, subject_changed = ensure_project_subject(
            db,
            project,
            subject_kind=subject_kind or _infer_subject_kind(user_message, subject_label, "偏好.关注") or "custom",
            label=subject_label,
            owner_user_id=conversation.created_by,
        )
        subject_label = subject.content.strip()
        subject_kind = get_subject_kind(subject)

    fact_text = _build_behavioral_interest_fact_text(subject_label)
    if not fact_text:
        return None, subject_changed

    return (
        {
            "fact": fact_text,
            "category": _build_behavioral_interest_category(subject_kind),
            "importance": importance,
            "source": "behavioral_interest",
            "triage_reason": _build_behavioral_interest_reason(
                subject_label=subject_label,
                same_conversation_turns=same_conversation_turns,
                distinct_conversations=distinct_conversations,
            ),
        },
        subject_changed,
    )


def _promote_temporary_duplicate_to_permanent(
    duplicate_memory: Memory,
    *,
    fact_text: str,
    fact_category: str,
    importance: float,
    fact_source: str,
    conversation: Conversation,
    subject_memory: Memory,
) -> None:
    reconfirm_after = datetime.now(timezone.utc).replace(microsecond=0)
    metadata = build_private_memory_metadata(
        {
            **(duplicate_memory.metadata_json or {}),
            "importance": importance,
            "source": fact_source,
            "node_type": FACT_NODE_TYPE,
            "node_status": ACTIVE_NODE_STATUS,
            "subject_memory_id": subject_memory.id,
            "single_source_explicit": True,
            "reconfirm_after": (reconfirm_after.replace(day=reconfirm_after.day) + timedelta(days=30)).isoformat(),
        },
        owner_user_id=conversation.created_by,
    )
    duplicate_memory.content = fact_text
    duplicate_memory.category = fact_category
    duplicate_memory.type = "permanent"
    duplicate_memory.node_type = duplicate_memory.node_type or FACT_NODE_TYPE
    duplicate_memory.subject_memory_id = subject_memory.id
    duplicate_memory.parent_memory_id = duplicate_memory.parent_memory_id or subject_memory.id
    duplicate_memory.node_status = ACTIVE_NODE_STATUS
    duplicate_memory.source_conversation_id = None
    duplicate_memory.confidence = max(float(duplicate_memory.confidence or 0.0), float(importance or 0.0))
    duplicate_memory.metadata_json = normalize_memory_metadata(
        content=fact_text,
        category=fact_category,
        memory_type="permanent",
        metadata=metadata,
    )
    duplicate_memory.canonical_key = (
        str((duplicate_memory.metadata_json or {}).get("canonical_key") or "").strip() or duplicate_memory.canonical_key
    )
    ensure_fact_lineage(duplicate_memory)
    apply_temporal_defaults(duplicate_memory)


def _record_source_message_evidence(
    db,
    *,
    memory: Memory,
    conversation: Conversation,
    source_message: Message | None,
    quote_text: str,
    confidence: float,
    source: str,
    episode_id: str | None = None,
) -> list[str]:
    normalized_quote = str(quote_text or "").strip()
    if not normalized_quote:
        return []
    evidence = record_memory_evidence(
        db,
        memory=memory,
        source_type="message",
        conversation_id=conversation.id,
        message_id=source_message.id if source_message is not None else None,
        message_role=source_message.role if source_message is not None else "user",
        episode_id=episode_id,
        quote_text=normalized_quote,
        confidence=confidence,
        metadata_json={"source": source},
    )
    return [evidence.id]


def _looks_like_aggregate_fact(
    fact_text: str,
    *,
    fact_category: str,
    fact_memory_kind: str,
) -> bool:
    normalized = re.sub(r"\s+", "", str(fact_text or "").strip())
    if not normalized:
        return False
    if fact_memory_kind not in {MEMORY_KIND_PREFERENCE, MEMORY_KIND_GOAL} and "偏好" not in str(fact_category or ""):
        return False
    if not any(separator in normalized for separator in ("、", "和", "以及", "及", "，", ",")):
        return False
    return bool(
        re.match(
            r"^用户(?:偏好|喜欢|喜爱|爱喝|爱吃|热爱|计划|打算|准备|想要)[^。！？!?]*[、和及以及，,][^。！？!?]*[。！？!?]?$",
            normalized,
        )
    )


def _sanitize_concept_topic(topic: str) -> str:
    cleaned = re.sub(r"\s+", "", str(topic or "").strip())
    cleaned = cleaned.strip("，。、“”‘’\"'`()（）[]【】<>《》:：;；,.!?！？")
    for suffix in ("饮品", "饮料", "食品", "食物", "类别", "类型"):
        if cleaned.endswith(suffix) and len(cleaned) > len(suffix):
            cleaned = cleaned[: -len(suffix)]
            break
    if not cleaned:
        return ""
    if len(cleaned) > 18:
        return ""
    if any(token in cleaned for token in ("用户", "事实", "记忆", "主题", "偏好", "目标")):
        return ""
    return cleaned


_FACT_CONCEPT_TOPIC_HINTS: tuple[tuple[str, str], ...] = (
    ("人设", "设定"),
    ("设定", "设定"),
    ("世界观", "设定"),
    ("定位", "设定"),
    ("背景", "背景"),
    ("来历", "背景"),
    ("出身", "背景"),
    ("历史", "背景"),
    ("经历", "经历"),
    ("剧情", "经历"),
    ("故事", "经历"),
    ("事件", "经历"),
    ("过去", "经历"),
    ("能力", "能力"),
    ("技能", "能力"),
    ("招式", "能力"),
    ("术式", "能力"),
    ("武器", "能力"),
    ("关系", "关系"),
    ("互动", "关系"),
    ("对手", "关系"),
    ("朋友", "关系"),
    ("搭档", "关系"),
    ("身份", "身份"),
    ("种族", "身份"),
    ("职业", "身份"),
    ("头衔", "身份"),
    ("称号", "身份"),
    ("职位", "身份"),
    ("性格", "特征"),
    ("特点", "特征"),
    ("辨识度", "特征"),
    ("风格", "特征"),
    ("外观", "特征"),
    ("形象", "特征"),
    ("气质", "特征"),
    ("特征", "特征"),
)

_USER_FACT_CONCEPT_TOPIC_HINTS: tuple[tuple[str, str], ...] = (
    ("education", "教育"),
    ("study", "教育"),
    ("school", "教育"),
    ("学业", "教育"),
    ("教育", "教育"),
    ("identity", "身份"),
    ("身份", "身份"),
    ("profile", "个人"),
    ("personal", "个人"),
    ("个人", "个人"),
    ("work", "工作"),
    ("job", "工作"),
    ("career", "工作"),
    ("profession", "工作"),
    ("职业", "工作"),
    ("工作", "工作"),
    ("travel", "旅行"),
    ("trip", "旅行"),
    ("旅行", "旅行"),
    ("location", "地点"),
    ("place", "地点"),
    ("residence", "地点"),
    ("居住", "地点"),
    ("地点", "地点"),
    ("relationship", "关系"),
    ("关系", "关系"),
    ("food", "饮食"),
    ("drink", "饮食"),
    ("diet", "饮食"),
    ("饮食", "饮食"),
    ("学习", "学习"),
    ("learning", "学习"),
    ("health", "健康"),
    ("健康", "健康"),
)

_USER_FACT_CONCEPT_TOPIC_SKIP_KEYS = {
    "user",
    "custom",
    "fact",
    "事实",
    "记忆",
    "memory",
}

_USER_FACT_CONCEPT_LABELS: dict[str, str] = {
    "教育": "教育背景",
    "身份": "身份信息",
    "个人": "个人信息",
    "工作": "工作经历",
    "地点": "地点经历",
    "关系": "关系网络",
    "饮食": "饮食习惯",
    "学习": "学习轨迹",
    "健康": "健康情况",
    "旅行": "旅行经历",
}

_PERSON_FACT_CONCEPT_LABELS: dict[str, str] = {
    "设定": "角色设定",
    "背景": "角色背景",
    "经历": "经历事件",
    "能力": "能力体系",
    "关系": "关系网络",
    "身份": "身份定位",
    "特征": "形象特征",
}

_GENERIC_FACT_CONCEPT_LABELS: dict[str, str] = {
    "设定": "核心设定",
    "背景": "背景信息",
    "经历": "相关经历",
    "能力": "能力体系",
    "关系": "关联关系",
    "身份": "身份定位",
    "特征": "关键特征",
}

_PERSON_LIKE_CATEGORY_HINTS = {
    "人物",
    "角色",
    "角色设定",
    "人物设定",
}


def _normalize_fact_concept_topic(topic: str) -> str:
    cleaned = _sanitize_concept_topic(topic)
    if not cleaned:
        return ""
    normalized_key = _normalize_text_key(cleaned)
    for hint, canonical in _FACT_CONCEPT_TOPIC_HINTS:
        if _normalize_text_key(hint) in normalized_key:
            return canonical
    return cleaned


def _normalize_user_fact_concept_topic(topic: str) -> str:
    cleaned = _sanitize_concept_topic(topic)
    if not cleaned:
        return ""
    normalized_key = _normalize_text_key(cleaned)
    if normalized_key in _USER_FACT_CONCEPT_TOPIC_SKIP_KEYS:
        return ""
    for hint, canonical in _USER_FACT_CONCEPT_TOPIC_HINTS:
        hint_key = _normalize_text_key(hint)
        if hint_key and (hint_key == normalized_key or hint_key in normalized_key):
            return canonical
    return cleaned


def _normalize_concept_label(label: str) -> str:
    cleaned = _sanitize_concept_topic(label)
    if not cleaned:
        return ""
    if len(cleaned) > 24:
        return ""
    return cleaned


def _is_person_like_fact_subject(*, subject_memory: Memory, fact_category: str) -> bool:
    subject_kind = get_subject_kind(subject_memory)
    if subject_kind == "person":
        return True
    segments = split_category_segments(fact_category)
    if segments and segments[0] in _PERSON_LIKE_CATEGORY_HINTS:
        return True
    return False


def _build_fact_concept_label(
    *,
    subject_memory: Memory,
    topic: str,
    fact_category: str,
) -> str:
    canonical_topic = _normalize_fact_concept_topic(topic) or _normalize_user_fact_concept_topic(topic) or topic
    subject_kind = get_subject_kind(subject_memory)
    if subject_kind == "user":
        return _USER_FACT_CONCEPT_LABELS.get(canonical_topic, f"{canonical_topic}信息")
    if _is_person_like_fact_subject(subject_memory=subject_memory, fact_category=fact_category):
        return _PERSON_FACT_CONCEPT_LABELS.get(canonical_topic, f"{canonical_topic}信息")
    return _GENERIC_FACT_CONCEPT_LABELS.get(canonical_topic, canonical_topic)


def _is_auto_generated_concept(memory: Memory | None) -> bool:
    if memory is None or not is_concept_memory(memory):
        return False
    metadata = memory.metadata_json or {}
    return bool(
        metadata.get("auto_generated")
        or metadata.get("source") in {"auto_concept_parent", "repair_concept_backfill"}
    )


def _get_concept_topic_for_matching(memory: Memory | None) -> str:
    if memory is None or not is_concept_memory(memory):
        return ""
    metadata = memory.metadata_json or {}
    explicit_topic = str(metadata.get("concept_topic") or "").strip()
    if explicit_topic:
        normalized_explicit = (
            _normalize_fact_concept_topic(explicit_topic)
            or _normalize_user_fact_concept_topic(explicit_topic)
            or _sanitize_concept_topic(explicit_topic)
        )
        if normalized_explicit:
            return normalized_explicit

    for segment in split_category_segments(memory.category):
        normalized_segment = (
            _normalize_user_fact_concept_topic(segment)
            or _normalize_fact_concept_topic(segment)
        )
        if normalized_segment:
            return normalized_segment

    return (
        _normalize_user_fact_concept_topic(memory.content)
        or _normalize_fact_concept_topic(memory.content)
        or _sanitize_concept_topic(memory.content)
    )


def _infer_user_fact_concept_topic(*, fact_category: str, fact_text: str) -> str | None:
    raw_segments = [
        segment.strip()
        for segment in str(fact_category or "").split(".")
        if segment and segment.strip()
    ]
    for segment in raw_segments:
        topic = _normalize_user_fact_concept_topic(segment)
        if topic:
            return topic

    normalized_fact = re.sub(r"\s+", "", str(fact_text or "").strip())
    if not normalized_fact:
        return None
    for hint, canonical in _USER_FACT_CONCEPT_TOPIC_HINTS:
        if hint in normalized_fact:
            return canonical
    return None


def _infer_fact_concept_topic(
    *,
    subject_memory: Memory,
    fact_text: str,
    fact_category: str,
) -> str | None:
    if get_subject_kind(subject_memory) == "user":
        return _infer_user_fact_concept_topic(
            fact_category=fact_category,
            fact_text=fact_text,
        )

    for segment in reversed(_normalize_category_segments(fact_category)):
        topic = _normalize_fact_concept_topic(segment)
        if topic:
            return topic

    normalized_fact = re.sub(r"\s+", "", str(fact_text or "").strip())
    if not normalized_fact:
        return None

    for hint, canonical in _FACT_CONCEPT_TOPIC_HINTS:
        if hint in normalized_fact:
            return canonical
    return None


def _build_concept_parent_text(
    *,
    topic: str,
    memory_kind: str,
    subject_memory: Memory | None = None,
) -> str | None:
    if not topic:
        return None
    if memory_kind == MEMORY_KIND_PREFERENCE:
        return f"用户对{topic}感兴趣"
    if memory_kind == MEMORY_KIND_GOAL:
        return f"用户有{topic}相关目标"
    if memory_kind == MEMORY_KIND_FACT and subject_memory is not None:
        return topic
    return None


def _build_concept_category(*, fact_category: str, topic: str) -> str:
    segments = [segment.strip() for segment in str(fact_category or "").split(".") if segment.strip()]
    if not topic:
        return ".".join(segments)
    if not segments:
        return topic
    topic_key = _normalize_text_key(topic)
    for index, segment in enumerate(segments):
        if _normalize_text_key(segment) == topic_key:
            return ".".join(segments[: index + 1])
    return ".".join([*segments, topic])


async def _plan_concept_parent(
    *,
    subject_memory: Memory,
    fact_text: str,
    fact_category: str,
    fact_memory_kind: str,
) -> dict[str, str] | None:
    if fact_memory_kind not in _CONCEPT_PARENT_SUPPORTED_KINDS:
        return None

    if fact_memory_kind == MEMORY_KIND_FACT:
        heuristic_topic = _infer_fact_concept_topic(
            subject_memory=subject_memory,
            fact_text=fact_text,
            fact_category=fact_category,
        )
        if heuristic_topic:
            concept_label = _build_fact_concept_label(
                subject_memory=subject_memory,
                topic=heuristic_topic,
                fact_category=fact_category,
            )
            return {
                "topic": heuristic_topic,
                "parent_text": concept_label,
                "parent_category": _build_concept_category(fact_category=fact_category, topic=heuristic_topic),
                "reason": f"根据分类和事实内容归入「{concept_label}」主题。",
            }

    prompt = CONCEPT_TOPIC_PROMPT.format(
        subject_label=subject_memory.content.strip() or "未命名主体",
        subject_kind=get_subject_kind(subject_memory) or "custom",
        fact=fact_text,
        category=fact_category or "未分类",
        memory_kind=fact_memory_kind,
    )

    try:
        raw = await dashscope_client.chat_completion(
            [{"role": "user", "content": prompt}],
            model=settings.memory_triage_model,
            temperature=0.1,
            max_tokens=128,
        )
    except Exception:  # noqa: BLE001
        return None

    json_match = re.search(r"\{.*\}", raw.strip(), re.DOTALL)
    if not json_match:
        return None

    try:
        payload = json.loads(json_match.group(0))
    except (json.JSONDecodeError, ValueError):
        return None

    topic = str(payload.get("topic") or "")
    label = str(payload.get("label") or "")
    if fact_memory_kind == MEMORY_KIND_FACT:
        topic = _normalize_fact_concept_topic(topic)
        label = _normalize_concept_label(label) or _build_fact_concept_label(
            subject_memory=subject_memory,
            topic=topic,
            fact_category=fact_category,
        )
    else:
        topic = _sanitize_concept_topic(topic)
        label = _normalize_concept_label(label)
    confidence = 0.0
    try:
        confidence = float(payload.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    if not topic or confidence < 0.78:
        return None

    parent_text = _build_concept_parent_text(
        topic=label or topic,
        memory_kind=fact_memory_kind,
        subject_memory=subject_memory,
    )
    if not parent_text:
        return None
    if _normalize_text_key(parent_text) == _normalize_text_key(fact_text):
        return None
    if _normalize_text_key(parent_text) == _normalize_text_key(subject_memory.content):
        return None

    return {
        "topic": topic,
        "parent_text": parent_text,
        "parent_category": _build_concept_category(fact_category=fact_category, topic=topic),
        "reason": str(payload.get("reason") or "").strip(),
    }


def _find_existing_concept_parent(
    db,
    *,
    workspace_id: str,
    project_id: str,
    conversation_id: str,
    subject_memory_id: str,
    parent_text: str,
    topic: str,
    parent_category: str,
    fact_memory_kind: str,
) -> Memory | None:
    target_key = _normalize_text_key(parent_text)
    if not target_key:
        return None
    topic_key = _normalize_text_key(topic)

    concept_memories = (
        db.query(Memory)
        .filter(
            Memory.workspace_id == workspace_id,
            Memory.project_id == project_id,
            Memory.subject_memory_id == subject_memory_id,
        )
        .all()
    )

    best_match: Memory | None = None
    best_score = -1
    for memory in concept_memories:
        if is_assistant_root_memory(memory) or not is_concept_memory(memory):
            continue
        if memory.type == "temporary" and memory.source_conversation_id != conversation_id:
            continue
        if get_memory_kind(memory) != fact_memory_kind:
            continue

        score = 0
        if _normalize_text_key(memory.content) == target_key:
            score += 3
        existing_topic = _normalize_text_key(_get_concept_topic_for_matching(memory))
        if topic_key and existing_topic == topic_key:
            score += 4
        elif topic_key and existing_topic and (topic_key in existing_topic or existing_topic in topic_key):
            if _shared_category_prefix_length(parent_category, memory.category) >= 1:
                score += 2
        if score > best_score:
            best_match = memory
            best_score = score

    return best_match if best_score >= 4 else None


async def _refresh_existing_concept_parent(
    db,
    existing: Memory,
    *,
    workspace_id: str,
    project_id: str,
    owner_user_id: str | None,
    subject_memory: Memory,
    topic: str,
    label: str,
    parent_category: str,
) -> None:
    if not _is_auto_generated_concept(existing) or is_pinned_memory(existing):
        return

    normalized_label = _normalize_concept_label(label)
    if not normalized_label:
        return

    current_topic = _get_concept_topic_for_matching(existing)
    should_relabel = (
        _normalize_text_key(existing.content) in {
            _normalize_text_key(topic),
            _normalize_text_key(current_topic),
        }
        and _normalize_text_key(existing.content) != _normalize_text_key(normalized_label)
    )

    next_content = normalized_label if should_relabel else existing.content
    if (
        _normalize_text_key(next_content) == _normalize_text_key(existing.content)
        and _normalize_text_key(existing.category) == _normalize_text_key(parent_category)
        and _normalize_text_key(str((existing.metadata_json or {}).get("concept_topic") or "")) == _normalize_text_key(topic)
        and _normalize_text_key(str((existing.metadata_json or {}).get("concept_label") or "")) == _normalize_text_key(normalized_label)
    ):
        return

    metadata: dict[str, object] = {
        **(existing.metadata_json or {}),
        "node_kind": CONCEPT_NODE_KIND,
        "node_type": CONCEPT_NODE_KIND,
        "node_status": ACTIVE_NODE_STATUS,
        "subject_kind": None,
        "subject_memory_id": subject_memory.id,
        "concept_topic": topic,
        "concept_label": normalized_label,
        "auto_generated": True,
        "source": str((existing.metadata_json or {}).get("source") or "auto_concept_parent"),
        "salience": float((existing.metadata_json or {}).get("salience") or 0.72),
    }
    if owner_user_id:
        metadata = build_private_memory_metadata(metadata, owner_user_id=owner_user_id)
    metadata = normalize_memory_metadata(
        content=next_content,
        category=parent_category,
        memory_type=existing.type,
        metadata=metadata,
    )
    existing.content = next_content
    existing.category = parent_category
    existing.subject_memory_id = subject_memory.id
    existing.parent_memory_id = subject_memory.id
    existing.metadata_json = metadata
    existing.canonical_key = str(metadata.get("canonical_key") or "").strip() or existing.canonical_key

    if should_relabel:
        try:
            from app.services.embedding import embed_and_store

            await embed_and_store(
                db,
                workspace_id=workspace_id,
                project_id=project_id,
                memory_id=existing.id,
                chunk_text=existing.content,
                auto_commit=False,
            )
        except Exception:  # noqa: BLE001
            pass


async def _resolve_concept_parent(
    db,
    *,
    workspace_id: str,
    project_id: str,
    conversation_id: str,
    owner_user_id: str | None,
    subject_memory: Memory,
    fact_text: str,
    fact_category: str,
    fact_memory_kind: str,
    query_vector: list[float] | None = None,
) -> tuple[Memory | None, bool, str | None]:
    plan = await _plan_concept_parent(
        subject_memory=subject_memory,
        fact_text=fact_text,
        fact_category=fact_category,
        fact_memory_kind=fact_memory_kind,
    )
    if not plan:
        return None, False, None

    normalized_topic = _sanitize_concept_topic(plan.get("topic", ""))
    if normalized_topic and normalized_topic != plan["topic"]:
        normalized_parent_text = _build_concept_parent_text(
            topic=normalized_topic,
            memory_kind=fact_memory_kind,
            subject_memory=subject_memory,
        )
        if normalized_parent_text:
            plan = {
                **plan,
                "topic": normalized_topic,
                "parent_text": normalized_parent_text,
                "parent_category": _build_concept_category(
                    fact_category=fact_category,
                    topic=normalized_topic,
                ),
            }

    existing = _find_existing_concept_parent(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_id=conversation_id,
        subject_memory_id=subject_memory.id,
        parent_text=plan["parent_text"],
        topic=plan["topic"],
        parent_category=plan["parent_category"],
        fact_memory_kind=fact_memory_kind,
    )
    if existing:
        await _refresh_existing_concept_parent(
            db,
            existing,
            workspace_id=workspace_id,
            project_id=project_id,
            owner_user_id=owner_user_id,
            subject_memory=subject_memory,
            topic=plan["topic"],
            label=plan["parent_text"],
            parent_category=plan["parent_category"],
        )
        return existing, False, plan.get("reason") or None

    semantic_existing: Memory | None = None
    semantic_score = 0.0
    if query_vector:
        semantic_existing, semantic_score = await _select_parent_memory_anchor(
            db,
            workspace_id=workspace_id,
            project_id=project_id,
            conversation_id=conversation_id,
            query_vector=query_vector,
            fact_category=plan["parent_category"],
            fact_memory_kind=fact_memory_kind,
        )
    if semantic_existing is not None and semantic_existing.subject_memory_id == subject_memory.id and semantic_score >= 0.78:
        await _refresh_existing_concept_parent(
            db,
            semantic_existing,
            workspace_id=workspace_id,
            project_id=project_id,
            owner_user_id=owner_user_id,
            subject_memory=subject_memory,
            topic=plan["topic"],
            label=plan["parent_text"],
            parent_category=plan["parent_category"],
        )
        semantic_reason = plan.get("reason") or None
        if semantic_reason:
            semantic_reason = f"{semantic_reason}；复用语义相近的既有主题节点。"
        else:
            semantic_reason = "复用语义相近的既有主题节点。"
        return semantic_existing, False, semantic_reason

    metadata: dict[str, object] = {
        "node_kind": CONCEPT_NODE_KIND,
        "node_type": CONCEPT_NODE_KIND,
        "node_status": ACTIVE_NODE_STATUS,
        "subject_kind": None,
        "subject_memory_id": subject_memory.id,
        "concept_topic": plan["topic"],
        "concept_label": plan["parent_text"],
        "auto_generated": True,
        "source": "auto_concept_parent",
        "salience": 0.72,
    }
    if owner_user_id:
        metadata = build_private_memory_metadata(metadata, owner_user_id=owner_user_id)
    metadata = normalize_memory_metadata(
        content=plan["parent_text"],
        category=plan["parent_category"],
        memory_type="permanent",
        metadata=metadata,
    )

    concept_memory = Memory(
        workspace_id=workspace_id,
        project_id=project_id,
        content=plan["parent_text"],
        category=plan["parent_category"],
        type="permanent",
        node_type=CONCEPT_NODE_KIND,
        subject_kind=None,
        source_conversation_id=None,
        parent_memory_id=subject_memory.id,
        subject_memory_id=subject_memory.id,
        node_status=ACTIVE_NODE_STATUS,
        canonical_key=str(metadata.get("canonical_key") or "").strip() or None,
        metadata_json=metadata,
    )
    db.add(concept_memory)
    db.flush()

    try:
        from app.services.embedding import embed_and_store

        await embed_and_store(
            db,
            workspace_id=workspace_id,
            project_id=project_id,
            memory_id=concept_memory.id,
            chunk_text=concept_memory.content,
            auto_commit=False,
        )
    except Exception:  # noqa: BLE001
        pass

    return concept_memory, True, plan.get("reason") or None


async def _validate_append_parent(
    *,
    fact_text: str,
    fact_category: str,
    fact_memory_kind: str,
    candidate_memory: Memory,
) -> dict[str, str]:
    if _is_structural_parent_memory(candidate_memory):
        return {"relation": "parent", "reason": "候选记忆是主题节点，可作为稳定父节点。"}

    prompt = APPEND_PARENT_VALIDATION_PROMPT.format(
        candidate=candidate_memory.content,
        candidate_category=candidate_memory.category or "未分类",
        fact=fact_text,
        fact_category=fact_category or "未分类",
        memory_kind=fact_memory_kind or "fact",
    )

    fallback = {"relation": "unrelated", "reason": "候选记忆不是稳定的父节点，回退到独立建模。"}
    try:
        raw = await dashscope_client.chat_completion(
            [{"role": "user", "content": prompt}],
            model=settings.memory_triage_model,
            temperature=0.1,
            max_tokens=128,
        )
    except Exception:  # noqa: BLE001
        return fallback

    json_match = re.search(r"\{.*\}", raw.strip(), re.DOTALL)
    if not json_match:
        return fallback
    try:
        payload = json.loads(json_match.group(0))
    except (json.JSONDecodeError, ValueError):
        return fallback

    relation = str(payload.get("relation") or "").strip().lower()
    if relation not in {"parent", "sibling", "duplicate", "unrelated"}:
        return fallback
    reason = str(payload.get("reason") or "").strip()
    if relation == "parent" and not _is_structural_parent_memory(candidate_memory):
        shared_prefix = _shared_category_prefix_length(fact_category, candidate_memory.category)
        candidate_kind = get_memory_kind(candidate_memory)
        if shared_prefix >= 1 or (fact_memory_kind and candidate_kind == fact_memory_kind):
            return {
                "relation": "sibling",
                "reason": "普通事实节点不能作为自动父节点，改为同主题并列项并归入主题节点。",
            }
        return {
            "relation": "unrelated",
            "reason": "普通事实节点不能作为自动父节点，回退到独立建模。",
        }
    return {
        "relation": relation,
        "reason": reason or fallback["reason"],
    }


async def _select_parent_memory_anchor(
    db,
    *,
    workspace_id: str,
    project_id: str,
    conversation_id: str,
    query_vector: list[float] | None,
    fact_category: str,
    fact_memory_kind: str,
    excluded_memory_ids: set[str] | None = None,
) -> tuple[Memory | None, float]:
    if not query_vector:
        return None, 0.0

    from app.services.embedding import find_related_memories

    excluded_ids = {item for item in (excluded_memory_ids or set()) if item}
    anchor_low = max(0.55, settings.memory_triage_similarity_low - 0.12)
    try:
        candidate_rows = await find_related_memories(
            db,
            workspace_id=workspace_id,
            project_id=project_id,
            query_vector=query_vector,
            low=anchor_low,
            high=0.999,
            limit=6,
        )
    except Exception:  # noqa: BLE001
        return None, 0.0

    candidate_ids = [
        str(row.get("memory_id") or "").strip()
        for row in candidate_rows
        if str(row.get("memory_id") or "").strip() and str(row.get("memory_id") or "").strip() not in excluded_ids
    ]
    if not candidate_ids:
        return None, 0.0

    memories = (
        db.query(Memory)
        .filter(
            Memory.project_id == project_id,
            Memory.workspace_id == workspace_id,
            Memory.id.in_(candidate_ids),
        )
        .all()
    )
    memories_by_id = {memory.id: memory for memory in memories}

    best_memory: Memory | None = None
    best_score = 0.0
    for row in candidate_rows:
        memory_id = str(row.get("memory_id") or "").strip()
        if not memory_id or memory_id in excluded_ids:
            continue
        memory = memories_by_id.get(memory_id)
        if not memory or is_assistant_root_memory(memory) or not is_concept_memory(memory):
            continue
        if memory.type == "temporary" and memory.source_conversation_id != conversation_id:
            continue

        semantic_score = float(row.get("score") or 0.0)
        combined_score = semantic_score

        shared_prefix = _shared_category_prefix_length(fact_category, memory.category)
        if shared_prefix >= 2:
            combined_score += 0.18
        elif shared_prefix == 1:
            combined_score += 0.10

        if fact_memory_kind and get_memory_kind(memory) == fact_memory_kind:
            combined_score += 0.08
        if memory.type == "permanent":
            combined_score += 0.04

        if combined_score > best_score:
            best_memory = memory
            best_score = combined_score

    if best_memory is None:
        return None, 0.0

    fact_has_category = bool(_normalize_category_segments(fact_category))
    if best_score < 0.68 and not fact_has_category:
        return None, 0.0

    return best_memory, best_score


def _upsert_auto_memory_edge(
    db,
    *,
    source_memory_id: str,
    target_memory_id: str,
    strength: float = 0.65,
) -> None:
    if not source_memory_id or not target_memory_id or source_memory_id == target_memory_id:
        return

    for pending in db.new:
        if not isinstance(pending, MemoryEdge):
            continue
        if pending.source_memory_id != source_memory_id or pending.target_memory_id != target_memory_id:
            continue
        pending.strength = max(float(pending.strength or 0.0), float(strength))
        return

    existing = (
        db.query(MemoryEdge)
        .filter(
            MemoryEdge.source_memory_id == source_memory_id,
            MemoryEdge.target_memory_id == target_memory_id,
        )
        .first()
    )
    if existing:
        existing.strength = max(float(existing.strength or 0.0), float(strength))
        return

    db.add(
        MemoryEdge(
            source_memory_id=source_memory_id,
            target_memory_id=target_memory_id,
            edge_type="auto",
            strength=max(0.1, min(1.0, float(strength))),
        )
    )


def _build_memory_extraction_summary(processed_facts: list[dict[str, object]]) -> str | None:
    counts: dict[str, int] = {}
    concept_parent_created = 0
    for fact in processed_facts:
        status = str(fact.get("status") or "").strip()
        if not status:
            status = ""
        if status:
            counts[status] = counts.get(status, 0) + 1
        if str(fact.get("parent_memory_action") or "").strip() == "created":
            concept_parent_created += 1

    if not counts and concept_parent_created == 0:
        return None

    ordered_labels = [
        ("permanent", "新增永久记忆"),
        ("temporary", "新增临时记忆"),
        ("appended", "挂接到已有记忆"),
        ("superseded", "创建新版并替代旧事实"),
        ("conflicted", "创建冲突事实"),
        ("duplicate", "重复跳过"),
        ("discarded", "被 triage 丢弃"),
        ("ignored", "重要度不足被忽略"),
    ]
    parts = [f"{label} {counts[key]} 条" for key, label in ordered_labels if counts.get(key)]
    if concept_parent_created:
        parts.append(f"新增主题节点 {concept_parent_created} 条")
    if not parts:
        return None
    return "；".join(parts)


def _build_memory_write_preview(
    processed_facts: list[dict[str, object]],
    *,
    summary: str | None,
    limit: int = 3,
) -> dict[str, object] | None:
    facts = [
        item
        for item in list(processed_facts or [])
        if isinstance(item, dict) and str(item.get("fact") or "").strip()
    ]
    normalized_summary = str(summary or "").strip()
    if not facts and not normalized_summary:
        return None

    preview_items: list[dict[str, object]] = []
    written_count = 0
    discarded_count = 0

    for index, fact in enumerate(facts):
        triage_action = str(fact.get("triage_action") or "").strip() or None
        status = str(fact.get("status") or "").strip() or None
        target_memory_id = str(fact.get("target_memory_id") or "").strip() or None
        triage_reason = str(fact.get("triage_reason") or "").strip() or None
        evidence_ids = fact.get("evidence_ids")
        evidence_count = len(evidence_ids) if isinstance(evidence_ids, list) else 0

        if triage_action == "discard" or status in {"discarded", "ignored"}:
            discarded_count += 1
        else:
            written_count += 1

        memory_type: str | None = None
        if triage_action == "promote" or status == "permanent":
            memory_type = "permanent"
        elif status == "temporary":
            memory_type = "temporary"

        if len(preview_items) >= limit:
            continue

        preview_items.append(
            {
                "id": target_memory_id or f"preview-{index}",
                "fact": str(fact.get("fact") or "").strip(),
                "category": str(fact.get("category") or "").strip(),
                "importance": float(fact.get("importance") or 0.0),
                "triage_action": triage_action,
                "triage_reason": triage_reason,
                "status": status,
                "target_memory_id": target_memory_id,
                "memory_type": memory_type,
                "evidence_count": evidence_count,
            }
        )

    return {
        "summary": normalized_summary or None,
        "item_count": len(facts),
        "written_count": written_count,
        "discarded_count": discarded_count,
        "items": preview_items,
    }


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


def _guess_heuristic_memory_category(item: str, clause: str, action: str) -> str:
    text = f"{clause} {item}".strip()
    if re.search(r"(旅行|出行|东京|机票|酒店)", text):
        return "旅行.计划"
    if re.search(r"(茶|咖啡|美式|拿铁|冷萃|饮料|饮品|果汁|奶茶|可乐|牛奶|乌龙|茉莉)", text):
        return "饮食.偏好"
    if re.search(r"(吃|饭|菜|火锅|面|米饭|寿司|拉面)", text):
        return "饮食.偏好"
    if action == "goal":
        return "计划"
    return "偏好"


def _normalize_explicit_fact_importance(
    importance: object,
    *,
    fact_text: str,
    memory_kind: str | None,
) -> float:
    try:
        normalized = float(importance)
    except (TypeError, ValueError):
        normalized = 0.0

    text = str(fact_text or "").strip()
    kind = str(memory_kind or "").strip().lower()
    if kind == MEMORY_KIND_PREFERENCE and _STABLE_PREFERENCE_FACT_PATTERN.search(text):
        return max(normalized, 0.9)
    if kind == MEMORY_KIND_GOAL and _STABLE_GOAL_FACT_PATTERN.search(text):
        return max(normalized, 0.9)
    return normalized


def _build_heuristic_fact_text(item: str, action: str, original_clause: str) -> str:
    normalized_item = item.strip(" ，,。！？!；;、")
    if not normalized_item:
        return ""
    if action == "drink_preference":
        return f"用户喜欢{normalized_item}。"
    if action == "preference":
        return f"用户喜欢{normalized_item}。"
    if action == "goal":
        clause = original_clause.strip()
        if clause and not re.search(r"[。！？!?]$", clause):
            clause = f"{clause}。"
        return clause
    return ""


def _extract_facts_heuristically(user_message: str) -> list[dict[str, object]]:
    text = str(user_message or "").strip()
    if not text:
        return []

    clauses = [segment.strip() for segment in re.split(r"[。！？!?；;，,]", text) if segment.strip()]
    results: list[dict[str, object]] = []
    seen: set[str] = set()

    speaker_prefix = r"(?:(?:我|本人)(?:也|很|还|都|最|特别|真的|平时|一直|常常|经常|通常|比较|更|挺|蛮|还挺)*|(?:也|很|还|平时|一直|常常|经常|通常|比较|更|挺|蛮|还挺)+)"
    preference_patterns = [
        (rf"^{speaker_prefix}喜欢喝(?P<item>.+)$", "drink_preference"),
        (rf"^{speaker_prefix}(?:爱喝|常喝)(?P<item>.+)$", "drink_preference"),
        (rf"^{speaker_prefix}喜欢(?P<item>.+)$", "preference"),
        (rf"^{speaker_prefix}(?:爱吃|常吃)(?P<item>.+)$", "preference"),
    ]
    goal_patterns = [
        r"^(?:(?:我|本人)|(?:今年|明年|最近|之后)).*(?:打算|计划|准备).+$",
    ]

    for clause in clauses:
        matched = False
        for pattern, action in preference_patterns:
            match = re.search(pattern, clause)
            if not match:
                continue
            item = match.group("item").strip()
            item = re.sub(r"^(?:也|很|还|都|最|特别|真的|平时|一直|常常|经常|通常|比较|更|挺|蛮|还挺)+", "", item).strip()
            item = re.sub(r"(?:呢|啊|呀|啦|哦|吧)$", "", item).strip()
            fact_text = _build_heuristic_fact_text(item, action, clause)
            if not fact_text:
                continue
            fact_key = _normalize_text_key(fact_text)
            if fact_key in seen:
                continue
            seen.add(fact_key)
            results.append(
                {
                    "fact": fact_text,
                    "category": _guess_heuristic_memory_category(item, clause, action),
                    "importance": 0.8,
                    "source": "heuristic",
                }
            )
            matched = True
            break
        if matched:
            continue

        for pattern in goal_patterns:
            match = re.search(pattern, clause)
            if not match:
                continue
            fact_text = _build_heuristic_fact_text(clause, "goal", clause)
            fact_key = _normalize_text_key(fact_text)
            if fact_key in seen:
                continue
            seen.add(fact_key)
            results.append(
                {
                    "fact": fact_text,
                    "category": _guess_heuristic_memory_category(clause, clause, "goal"),
                    "importance": 0.9,
                    "source": "heuristic",
                }
            )
            break

    return results


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
    import json
    import re

    from app.models.entities import Memory
    from app.services.dashscope_client import chat_completion
    from app.services.dashscope_http import close_current_client
    from app.services.embedding import embed_and_store, find_duplicate_memory_with_vector, find_related_memories

    EXTRACTION_PROMPT = """你是一个严格的 JSON 记忆提取器。只根据用户原话，提取用户明确表达的可记忆原子事实。

规则：
- 只提取用户明确说出的事实，不做推测
- 事实既可以关于用户本人，也可以关于当前明确提到的主体，例如书、课程、项目、理论、论文、设备、人物
- 不提取 assistant 复述出的汇总句，不根据 assistant 回复新增事实
- 如果一句话里包含多个并列偏好或事实，必须拆成多条叶子事实
- 禁止输出“用户偏好A和B”这类聚合句
- 如果事实属于非用户主体，要在 fact 文本里保留主体名称，不要偷偷改写成“用户……”
- 如果用户对非用户主体使用“他/她/它/TA/这个角色/这个人/这位/这个设定”等指代，输出时要改写为明确主体名，不要把代词直接写进 fact
- 每个事实用一句话表达
- importance: 0-1，其中 >=0.7 创建为临时记忆，>=0.9 直接升级为永久记忆
- category: 用中文，层级用点分隔（如"工作.计划"、"健康.用药"）

用户原话：
{user_message}

输出 JSON 数组：
[{{"fact": "...", "category": "...", "importance": 0.0}}]

如果没有值得记忆的事实，输出空数组 []。"""

    FALLBACK_EXTRACTION_PROMPT = """你是一个严格的 JSON 记忆提取器。只根据用户原话，提取用户明确表达的可记忆原子事实。

规则：
- 只提取用户明确说出的事实，不做推测
- 优先提取：身份、偏好、计划、经历、关系、限制条件，以及当前明确谈论的书、课程、项目、理论等主体事实
- 如果一句话里包含多个并列偏好或事实，要拆成多条
- 对非用户主体的事实，保留主体名称
- 如果用户用“他/她/它/TA/这个角色/这个人/这位/这个设定”等指代非用户主体，输出时改写为明确主体名
- importance: 0-1，明确且稳定的偏好/身份/计划通常 >=0.9
- category: 用中文，层级用点分隔
- 输出必须是 JSON 数组，不要输出解释文字或 markdown

用户原话：
{user_message}

输出示例：
[{{"fact":"用户喜欢喝冰美式。","category":"饮食.偏好","importance":0.95}}]

如果没有值得记忆的事实，输出 []。"""

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
        source_episode = None
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
            source_episode = create_memory_episode(
                db,
                workspace_id=workspace_id,
                project_id=project_id,
                conversation_id=conversation_id,
                message_id=ai_msg.id if ai_msg is not None else assistant_message_id,
                source_type="conversation_turn",
                source_id=assistant_message_id or (ai_msg.id if ai_msg is not None else conversation_id),
                chunk_text=f"USER:\n{user_message.strip()}\n\nASSISTANT:\n{str(ai_response or '').strip()}",
                owner_user_id=conversation.created_by,
                visibility="private" if conversation.created_by else "public",
                started_at=source_user_msg.created_at if source_user_msg is not None else datetime.now(timezone.utc),
                ended_at=ai_msg.created_at if ai_msg is not None else datetime.now(timezone.utc),
                metadata_json={
                    "assistant_message_id": ai_msg.id if ai_msg is not None else assistant_message_id,
                    "conversation_id": conversation_id,
                },
            )
            learning_run = create_memory_learning_run(
                db,
                workspace_id=workspace_id,
                project_id=project_id,
                conversation_id=conversation_id,
                message_id=ai_msg.id if ai_msg is not None else assistant_message_id,
                trigger="post_turn",
                stages=["observe"],
                metadata_json={
                    "episode_id": source_episode.id,
                    "assistant_message_id": ai_msg.id if ai_msg is not None else assistant_message_id,
                },
            )
            write_run = create_memory_write_run(
                db,
                workspace_id=workspace_id,
                project_id=project_id,
                conversation_id=conversation_id,
                message_id=ai_msg.id if ai_msg is not None else assistant_message_id,
                extraction_model=settings.memory_triage_model,
                consolidation_model=settings.dashscope_rerank_model,
                metadata_json={
                    "user_message_preview": user_message[:500],
                    "assistant_message_id": ai_msg.id if ai_msg is not None else assistant_message_id,
                    "episode_id": source_episode.id if source_episode is not None else None,
                    "learning_run_id": learning_run.id if learning_run is not None else None,
                },
            )
            _set_memory_extraction_state(
                ai_msg,
                status=MEMORY_EXTRACTION_STATUS_PENDING,
                attempts=attempt_index,
                error="",
                run_id=write_run.id if write_run is not None else None,
                learning_run_id=learning_run.id if learning_run is not None else None,
            )
            db.commit()
        except Exception:  # noqa: BLE001
            ai_msg = None
            source_user_msg = None
            write_run = None
            learning_run = None
            source_episode = None

        prompt = EXTRACTION_PROMPT.format(user_message=user_message)

        # ── Async helper: extract, dedup, and embed in a single event loop ──
        async def _extract_and_store_facts() -> None:
            try:
                async def _extract_facts_once(prompt_text: str) -> list[dict[str, object]]:
                    raw_response = await chat_completion(
                        [{"role": "user", "content": prompt_text}],
                        temperature=0.1,
                        max_tokens=1024,
                    )

                    json_str = raw_response.strip()
                    json_match = re.search(r"\[.*\]", json_str, re.DOTALL)
                    if not json_match:
                        return []

                    try:
                        parsed = json.loads(json_match.group(0))
                    except json.JSONDecodeError:
                        return []
                    if not isinstance(parsed, list):
                        return []
                    return [item for item in parsed if isinstance(item, dict)]

                facts = await _extract_facts_once(prompt)
                if not facts:
                    fallback_prompt = FALLBACK_EXTRACTION_PROMPT.format(
                        user_message=user_message,
                    )
                    facts = await _extract_facts_once(fallback_prompt)

                if not facts:
                    facts = _extract_facts_heuristically(user_message)
                if facts:
                    facts = list(facts)
                inferred_interest_fact, inferred_subject_changed = _infer_behavioral_interest_fact(
                    db,
                    project=project,
                    conversation=conversation,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    user_message=user_message,
                    extracted_facts=facts or [],
                )
                if inferred_subject_changed:
                    db.flush()
                if inferred_interest_fact:
                    inferred_key = _normalize_text_key(str(inferred_interest_fact.get("fact") or ""))
                    if inferred_key and all(
                        _normalize_text_key(str(item.get("fact") or "")) != inferred_key for item in (facts or [])
                    ):
                        facts = [*(facts or []), inferred_interest_fact]
                if not facts:
                    finalize_memory_write_run(
                        write_run,
                        status="completed",
                        metadata_json={"item_count": 0},
                    )
                    finalize_memory_learning_run(
                        learning_run,
                        status="completed",
                        stages=merge_learning_stages(
                            learning_run.stages,
                            ["observe", "extract", "consolidate"],
                        ),
                        used_memory_ids=[],
                        promoted_memory_ids=[],
                        degraded_memory_ids=[],
                        metadata_json={"item_count": 0},
                    )
                    _persist_memory_extraction_metadata(
                        ai_msg,
                        processed_facts=[],
                        empty_summary="本轮未提取到可保存记忆",
                        attempts=attempt_index,
                        run_id=write_run.id if write_run is not None else None,
                        learning_run_id=learning_run.id if learning_run is not None else None,
                    )
                    db.flush()
                    return

                processed_facts: list[dict[str, object]] = []
                subject_view_inputs: dict[str, dict[str, object]] = {}

                def _collect_view_refresh(
                    subject: Memory | None,
                    *,
                    source_memory_id: str | None = None,
                    source_text: str | None = None,
                ) -> None:
                    if subject is None:
                        return
                    payload = subject_view_inputs.setdefault(
                        subject.id,
                        {
                            "subject_memory": subject,
                            "memory_ids": [],
                            "playbook_texts": [],
                        },
                    )
                    memory_ids = payload.get("memory_ids")
                    if isinstance(memory_ids, list) and source_memory_id and source_memory_id not in memory_ids:
                        memory_ids.append(source_memory_id)
                    playbook_texts = payload.get("playbook_texts")
                    normalized_text = str(source_text or "").strip()
                    if isinstance(playbook_texts, list) and normalized_text:
                        playbook_texts.append(normalized_text)

                for fact in facts:
                    fact_text = _normalize_extracted_fact_text(fact.get("fact", ""))
                    category = str(fact.get("category", "")).strip()
                    fact_source = str(fact.get("source") or "auto_extraction").strip() or "auto_extraction"
                    initial_triage_reason = str(fact.get("triage_reason") or "").strip() or None
                    if not fact_text:
                        continue

                    subject_memory, subject_changed, subject_resolution = _resolve_subject_memory_for_fact(
                        db,
                        project=project,
                        conversation=conversation,
                        user_message=user_message,
                        fact_text=fact_text,
                        fact_category=category,
                    )
                    if subject_changed:
                        db.flush()
                    fact_text = _canonicalize_fact_text_for_storage(
                        fact_text=fact_text,
                        user_message=user_message,
                        subject_memory=subject_memory,
                        subject_resolution=subject_resolution,
                    )
                    if not fact_text:
                        continue

                    preview_metadata = normalize_memory_metadata(
                        content=fact_text,
                        category=category,
                        memory_type="temporary",
                        metadata={
                            "source": fact_source,
                            "node_type": FACT_NODE_TYPE,
                            "node_status": ACTIVE_NODE_STATUS,
                            "subject_memory_id": subject_memory.id,
                        },
                    )
                    memory_kind = str(preview_metadata.get("memory_kind") or "").strip().lower()
                    importance = _normalize_explicit_fact_importance(
                        fact.get("importance", 0),
                        fact_text=fact_text,
                        memory_kind=memory_kind,
                    )
                    if importance < 0.9 and memory_kind not in {
                        MEMORY_KIND_PROFILE,
                        MEMORY_KIND_PREFERENCE,
                        MEMORY_KIND_GOAL,
                    }:
                        memory_kind = MEMORY_KIND_EPISODIC

                    fact_display: dict[str, object] = {
                        "fact": fact_text,
                        "category": category,
                        "importance": importance,
                        "subject_memory_id": subject_memory.id,
                        "subject_label": subject_memory.content,
                        "subject_kind": get_subject_kind(subject_memory),
                        "subject_resolution": subject_resolution,
                        "source": fact_source,
                    }
                    if initial_triage_reason:
                        fact_display["triage_reason"] = initial_triage_reason

                    write_item = create_memory_write_item(
                        db,
                        run_id=write_run.id if write_run is not None else "",
                        subject_memory_id=subject_memory.id,
                        candidate_text=fact_text,
                        category=category,
                        proposed_memory_kind=memory_kind,
                        importance=importance,
                        decision="create",
                        reason=initial_triage_reason,
                        metadata_json={
                            "policy_flags": [fact_source],
                            "quote_preview": user_message[:500],
                        },
                    ) if write_run is not None else None

                    if importance < 0.7:
                        update_memory_write_item(
                            write_item,
                            decision="discard",
                            reason="importance_below_threshold",
                        )
                        fact_display["status"] = "ignored"
                        processed_facts.append(fact_display)
                        continue

                    durable_memory_kind = memory_kind in {
                        MEMORY_KIND_PROFILE,
                        MEMORY_KIND_PREFERENCE,
                        MEMORY_KIND_GOAL,
                    }
                    memory_type = (
                        "permanent"
                        if conversation.created_by and (importance >= 0.9 or durable_memory_kind)
                        else "temporary"
                    )
                    triage_reason = initial_triage_reason

                    if _looks_like_aggregate_fact(
                        fact_text,
                        fact_category=category,
                        fact_memory_kind=memory_kind,
                    ):
                        update_memory_write_item(
                            write_item,
                            decision="discard",
                            reason="aggregate_fact",
                        )
                        fact_display["status"] = "discarded"
                        fact_display["triage_action"] = "discard"
                        fact_display["triage_reason"] = "聚合型事实应拆分为多个叶子记忆，已跳过该汇总句。"
                        processed_facts.append(fact_display)
                        continue

                    # Deduplication: skip if a highly similar memory already exists
                    try:
                        duplicate, query_vector = await find_duplicate_memory_with_vector(
                            db,
                            workspace_id=workspace_id,
                            project_id=project_id,
                            text=fact_text,
                            threshold=settings.memory_triage_similarity_high,
                        )
                        if duplicate:
                            duplicate_memory = db.get(Memory, duplicate["memory_id"])
                            if (
                                duplicate_memory is not None
                                and duplicate_memory.type == "temporary"
                                and memory_type == "permanent"
                                and conversation.created_by
                            ):
                                _promote_temporary_duplicate_to_permanent(
                                    duplicate_memory,
                                    fact_text=fact_text,
                                    fact_category=category,
                                    importance=importance,
                                    fact_source=fact_source,
                                    conversation=conversation,
                                    subject_memory=subject_memory,
                                )
                                duplicate_memory.last_confirmed_at = datetime.now(timezone.utc)
                                evidence_ids = _record_source_message_evidence(
                                    db,
                                    memory=duplicate_memory,
                                    conversation=conversation,
                                    source_message=source_user_msg,
                                    quote_text=user_message,
                                    confidence=importance,
                                    source=fact_source,
                                    episode_id=source_episode.id if source_episode is not None else None,
                                )
                                update_memory_write_item(
                                    write_item,
                                    decision="promote",
                                    target_memory_id=duplicate_memory.id,
                                    reason=initial_triage_reason or "temporary_duplicate_promoted",
                                    metadata_json={
                                        "evidence_ids": evidence_ids,
                                        "merged_content": duplicate_memory.content,
                                        "policy_flags": [fact_source],
                                        "result_memory_id": duplicate_memory.id,
                                    },
                                )
                                refresh_subject = (
                                    db.get(Memory, duplicate_memory.subject_memory_id)
                                    if duplicate_memory.subject_memory_id
                                    else subject_memory
                                )
                                _collect_view_refresh(
                                    refresh_subject if isinstance(refresh_subject, Memory) else subject_memory,
                                    source_memory_id=duplicate_memory.id,
                                    source_text=duplicate_memory.content,
                                )
                                fact_display["status"] = "permanent"
                                fact_display["target_memory_id"] = duplicate_memory.id
                                fact_display["triage_action"] = "promote"
                                fact_display["evidence_ids"] = evidence_ids
                                fact_display["triage_reason"] = (
                                    f"{initial_triage_reason}；已有临时记忆因更强信号升级为永久记忆。"
                                    if initial_triage_reason
                                    else "已有临时记忆因更强信号升级为永久记忆。"
                                )
                                processed_facts.append(fact_display)
                                continue
                            if duplicate_memory is not None:
                                duplicate_memory.confidence = max(
                                    float(duplicate_memory.confidence or 0.0),
                                    float(importance or 0.0),
                                )
                                duplicate_memory.last_confirmed_at = datetime.now(timezone.utc)
                                apply_temporal_defaults(duplicate_memory)
                                evidence_ids = _record_source_message_evidence(
                                    db,
                                    memory=duplicate_memory,
                                    conversation=conversation,
                                    source_message=source_user_msg,
                                    quote_text=user_message,
                                    confidence=importance,
                                    source=fact_source,
                                    episode_id=source_episode.id if source_episode is not None else None,
                                )
                                update_memory_write_item(
                                    write_item,
                                    decision="append",
                                    target_memory_id=duplicate_memory.id,
                                    reason=initial_triage_reason or "duplicate_existing_memory",
                                    metadata_json={
                                        "evidence_ids": evidence_ids,
                                        "merged_content": duplicate_memory.content,
                                        "policy_flags": [fact_source],
                                        "result_memory_id": duplicate_memory.id,
                                    },
                                )
                                refresh_subject = (
                                    db.get(Memory, duplicate_memory.subject_memory_id)
                                    if duplicate_memory.subject_memory_id
                                    else subject_memory
                                )
                                _collect_view_refresh(
                                    refresh_subject if isinstance(refresh_subject, Memory) else subject_memory,
                                    source_memory_id=duplicate_memory.id,
                                    source_text=duplicate_memory.content,
                                )
                                fact_display["status"] = "duplicate"
                                fact_display["target_memory_id"] = duplicate_memory.id
                                fact_display["triage_action"] = "append"
                                fact_display["evidence_ids"] = evidence_ids
                                processed_facts.append(fact_display)
                                continue
                    except Exception:  # noqa: BLE001
                        query_vector = None  # Dedup check failure is non-fatal

                    # ── Memory Triage: check for related (but not duplicate) memories ──
                    parent_memory_id = None
                    parent_memory: Memory | None = None
                    anchor_strength = 0.0
                    append_candidate_memory: Memory | None = None
                    triage_action = "create"
                    triage_reason = initial_triage_reason
                    triage_target_memory_id = None
                    if query_vector:
                        try:
                            candidates = await find_related_memories(
                                db,
                                workspace_id=workspace_id,
                                project_id=project_id,
                                query_vector=query_vector,
                                low=settings.memory_triage_similarity_low,
                                high=settings.memory_triage_similarity_high,
                            )
                        except Exception:  # noqa: BLE001
                            candidates = []

                        if candidates:
                            candidate_ids = {c["memory_id"] for c in candidates}
                            try:
                                decision = await triage_memory(fact_text, candidates)
                            except Exception:  # noqa: BLE001
                                decision = {"action": "create"}

                            action = decision.get("action", "create")
                            target_id = decision.get("target_memory_id")
                            merged = decision.get("merged_content")
                            triage_reason = decision.get("reason")

                            # Validate target_id comes from candidate list
                            if target_id and target_id not in candidate_ids:
                                action = "create"
                                target_id = None

                            triage_action = action
                            triage_target_memory_id = target_id

                            if action == "discard":
                                update_memory_write_item(
                                    write_item,
                                    decision="discard",
                                    reason=triage_reason or "triage_discard",
                                )
                                fact_display["status"] = "discarded"
                                fact_display["triage_action"] = "discard"
                                if isinstance(triage_reason, str) and triage_reason.strip():
                                    fact_display["triage_reason"] = triage_reason.strip()
                                processed_facts.append(fact_display)
                                continue

                            if action == "append" and target_id:
                                target = db.query(Memory).filter(
                                    Memory.id == target_id,
                                    Memory.project_id == project_id,
                                ).first()
                                if target:
                                    append_validation = await _validate_append_parent(
                                        fact_text=fact_text,
                                        fact_category=category,
                                        fact_memory_kind=memory_kind,
                                        candidate_memory=target,
                                    )
                                    validation_relation = append_validation.get("relation", "unrelated")
                                    validation_reason = append_validation.get("reason")
                                    if validation_relation == "parent":
                                        parent_memory_id = target_id
                                        parent_memory = target
                                        if validation_reason:
                                            triage_reason = validation_reason
                                    elif validation_relation == "duplicate":
                                        target.confidence = max(float(target.confidence or 0.0), float(importance or 0.0))
                                        target.last_confirmed_at = datetime.now(timezone.utc)
                                        apply_temporal_defaults(target)
                                        evidence_ids = _record_source_message_evidence(
                                            db,
                                            memory=target,
                                            conversation=conversation,
                                            source_message=source_user_msg,
                                            quote_text=user_message,
                                            confidence=importance,
                                            source=fact_source,
                                            episode_id=source_episode.id if source_episode is not None else None,
                                        )
                                        update_memory_write_item(
                                            write_item,
                                            decision="append",
                                            target_memory_id=target.id,
                                            reason=validation_reason or "duplicate_existing_memory",
                                            metadata_json={
                                                "evidence_ids": evidence_ids,
                                                "merged_content": target.content,
                                                "policy_flags": [fact_source],
                                                "result_memory_id": target.id,
                                            },
                                        )
                                        refresh_subject = (
                                            db.get(Memory, target.subject_memory_id)
                                            if target.subject_memory_id
                                            else subject_memory
                                        )
                                        _collect_view_refresh(
                                            refresh_subject if isinstance(refresh_subject, Memory) else subject_memory,
                                            source_memory_id=target.id,
                                            source_text=target.content,
                                        )
                                        fact_display["status"] = "duplicate"
                                        fact_display["triage_action"] = "discard"
                                        fact_display["target_memory_id"] = target_id
                                        fact_display["evidence_ids"] = evidence_ids
                                        if validation_reason:
                                            fact_display["triage_reason"] = validation_reason
                                        processed_facts.append(fact_display)
                                        continue
                                    else:
                                        append_candidate_memory = target if validation_relation == "sibling" else None
                                        triage_action = "create"
                                        triage_target_memory_id = None
                                        triage_reason = validation_reason
                                else:
                                    triage_action = "create"
                                    triage_target_memory_id = None
                                # else: fallthrough to create

                            elif action in ("merge", "replace") and target_id and merged:
                                target = db.query(Memory).filter(
                                    Memory.id == target_id,
                                    Memory.project_id == project_id,
                                ).first()
                                if target and target.type == "permanent" and is_fact_memory(target) and is_active_memory(target):
                                    successor = await create_fact_successor(
                                        db,
                                        predecessor=target,
                                        content=merged,
                                        category=fact.get("category", "") or target.category,
                                        reason=triage_reason or action,
                                        metadata_updates={"source": "auto_extraction", "version_action": action},
                                        vector=query_vector,
                                    )
                                    successor.confidence = max(float(successor.confidence or 0.0), float(importance or 0.0))
                                    successor.last_confirmed_at = datetime.now(timezone.utc)
                                    evidence_ids = _record_source_message_evidence(
                                        db,
                                        memory=successor,
                                        conversation=conversation,
                                        source_message=source_user_msg,
                                        quote_text=user_message,
                                        confidence=importance,
                                        source=fact_source,
                                        episode_id=source_episode.id if source_episode is not None else None,
                                    )
                                    update_memory_write_item(
                                        write_item,
                                        decision="supersede",
                                        target_memory_id=successor.id,
                                        predecessor_memory_id=target.id,
                                        reason=triage_reason or action,
                                        metadata_json={
                                            "evidence_ids": evidence_ids,
                                            "merged_content": merged,
                                            "policy_flags": [fact_source],
                                            "result_memory_id": successor.id,
                                        },
                                    )
                                    refresh_subject = (
                                        db.get(Memory, successor.subject_memory_id)
                                        if successor.subject_memory_id
                                        else subject_memory
                                    )
                                    _collect_view_refresh(
                                        refresh_subject if isinstance(refresh_subject, Memory) else subject_memory,
                                        source_memory_id=successor.id,
                                        source_text=successor.content,
                                    )
                                    fact_display["status"] = "superseded"
                                    fact_display["triage_action"] = action
                                    fact_display["target_memory_id"] = successor.id
                                    fact_display["supersedes_memory_id"] = target_id
                                    fact_display["lineage_key"] = successor.lineage_key
                                    fact_display["evidence_ids"] = evidence_ids
                                    if successor.parent_memory_id:
                                        fact_display["parent_memory_id"] = successor.parent_memory_id
                                    if isinstance(triage_reason, str) and triage_reason.strip():
                                        fact_display["triage_reason"] = triage_reason.strip()
                                    processed_facts.append(fact_display)
                                    continue  # Don't create a new memory
                                triage_action = "create"
                                triage_target_memory_id = None
                            elif action == "conflict" and target_id:
                                target = db.query(Memory).filter(
                                    Memory.id == target_id,
                                    Memory.project_id == project_id,
                                ).first()
                                if target and target.type == "permanent" and is_fact_memory(target) and is_active_memory(target):
                                    conflict_memory = await create_conflicting_fact(
                                        db,
                                        anchor=target,
                                        content=fact_text,
                                        category=fact.get("category", "") or target.category,
                                        reason=triage_reason or action,
                                        metadata_updates={"source": "auto_extraction", "version_action": action},
                                        vector=query_vector,
                                    )
                                    conflict_memory.confidence = max(
                                        float(conflict_memory.confidence or 0.0),
                                        float(importance or 0.0),
                                    )
                                    conflict_memory.last_confirmed_at = datetime.now(timezone.utc)
                                    evidence_ids = _record_source_message_evidence(
                                        db,
                                        memory=conflict_memory,
                                        conversation=conversation,
                                        source_message=source_user_msg,
                                        quote_text=user_message,
                                        confidence=importance,
                                        source=fact_source,
                                        episode_id=source_episode.id if source_episode is not None else None,
                                    )
                                    update_memory_write_item(
                                        write_item,
                                        decision="conflict",
                                        target_memory_id=conflict_memory.id,
                                        predecessor_memory_id=target.id,
                                        reason=triage_reason or action,
                                        metadata_json={
                                            "evidence_ids": evidence_ids,
                                            "merged_content": fact_text,
                                            "policy_flags": [fact_source],
                                            "result_memory_id": conflict_memory.id,
                                        },
                                    )
                                    refresh_subject = (
                                        db.get(Memory, conflict_memory.subject_memory_id)
                                        if conflict_memory.subject_memory_id
                                        else subject_memory
                                    )
                                    _collect_view_refresh(
                                        refresh_subject if isinstance(refresh_subject, Memory) else subject_memory,
                                        source_memory_id=conflict_memory.id,
                                        source_text=conflict_memory.content,
                                    )
                                    fact_display["status"] = "conflicted"
                                    fact_display["triage_action"] = "conflict"
                                    fact_display["target_memory_id"] = conflict_memory.id
                                    fact_display["conflict_with_memory_id"] = target_id
                                    fact_display["lineage_key"] = conflict_memory.lineage_key
                                    fact_display["evidence_ids"] = evidence_ids
                                    if conflict_memory.parent_memory_id:
                                        fact_display["parent_memory_id"] = conflict_memory.parent_memory_id
                                    if isinstance(triage_reason, str) and triage_reason.strip():
                                        fact_display["triage_reason"] = triage_reason.strip()
                                    processed_facts.append(fact_display)
                                    continue
                                triage_action = "create"
                                triage_target_memory_id = None

                    if parent_memory and not is_assistant_root_memory(parent_memory):
                        parent_subject_id = (
                            parent_memory.id if is_subject_memory(parent_memory) else get_subject_memory_id(parent_memory)
                        )
                        parent_subject = _load_subject_memory(
                            db,
                            workspace_id=workspace_id,
                            project_id=project_id,
                            owner_user_id=conversation.created_by,
                            subject_id=parent_subject_id,
                        )
                        if parent_subject is not None and parent_subject.id != subject_memory.id:
                            subject_memory = parent_subject
                            fact_display["subject_memory_id"] = subject_memory.id
                            fact_display["subject_label"] = subject_memory.content
                            fact_display["subject_kind"] = get_subject_kind(subject_memory)
                            if subject_resolution == "user_subject_fallback":
                                subject_resolution = "parent_subject_alignment"
                                fact_display["subject_resolution"] = subject_resolution

                    metadata = {
                        "importance": importance,
                        "source": fact_source,
                        "node_type": FACT_NODE_TYPE,
                        "node_status": ACTIVE_NODE_STATUS,
                        "subject_memory_id": subject_memory.id,
                    }
                    if memory_type == "temporary" and memory_kind not in {
                        MEMORY_KIND_PROFILE,
                        MEMORY_KIND_PREFERENCE,
                        MEMORY_KIND_GOAL,
                    }:
                        metadata["memory_kind"] = MEMORY_KIND_EPISODIC
                    if memory_type == "permanent":
                        if durable_memory_kind:
                            metadata["single_source_explicit"] = True
                            metadata["reconfirm_after"] = (
                                datetime.now(timezone.utc) + timedelta(days=30)
                            ).isoformat()
                        metadata = build_private_memory_metadata(metadata, owner_user_id=conversation.created_by)
                    metadata = normalize_memory_metadata(
                        content=fact_text,
                        category=fact.get("category", ""),
                        memory_type=memory_type,
                        metadata=metadata,
                    )
                    memory_kind = str(metadata.get("memory_kind") or "").strip().lower()

                    concept_parent_created = False
                    if parent_memory_id is None and memory_type == "permanent":
                        concept_parent, concept_created, concept_reason = await _resolve_concept_parent(
                            db,
                            workspace_id=workspace_id,
                            project_id=project_id,
                            conversation_id=conversation_id,
                            owner_user_id=conversation.created_by,
                            subject_memory=subject_memory,
                            fact_text=fact_text,
                            fact_category=category,
                            fact_memory_kind=memory_kind,
                            query_vector=query_vector,
                        )
                        if concept_parent:
                            concept_parent_created = concept_created
                            parent_memory_id = concept_parent.id
                            parent_memory = concept_parent
                            anchor_strength = 0.84 if concept_created else 0.8
                            if append_candidate_memory and append_candidate_memory.id != concept_parent.id:
                                _rebind_memory_under_parent(append_candidate_memory, concept_parent)
                                triage_action = "append"
                                triage_target_memory_id = append_candidate_memory.id
                                try:
                                    _upsert_auto_memory_edge(
                                        db,
                                        source_memory_id=concept_parent.id,
                                        target_memory_id=append_candidate_memory.id,
                                        strength=0.76,
                                    )
                                except Exception:  # noqa: BLE001
                                    pass
                            concept_label = concept_parent.content.strip()
                            relation_reason = (
                                f"新增主题节点「{concept_label}」并归入其下"
                                if concept_created
                                else f"归入主题「{concept_label}」"
                            )
                            if concept_reason:
                                relation_reason = f"{relation_reason}；{concept_reason}"
                            if triage_reason:
                                triage_reason = f"{triage_reason}；{relation_reason}"
                            else:
                                triage_reason = relation_reason
                        else:
                            anchor_strength = 0.0

                    if parent_memory_id is None:
                        parent_memory_id = subject_memory.id
                        parent_memory = subject_memory

                    if append_candidate_memory and parent_memory and not is_assistant_root_memory(parent_memory):
                        metadata = normalize_memory_metadata(
                            content=fact_text,
                            category=fact.get("category", ""),
                            memory_type=memory_type,
                            metadata=set_manual_parent_binding(
                                metadata,
                                parent_memory_id=parent_memory.id,
                            ),
                        )

                    memory = Memory(
                        workspace_id=workspace_id,
                        project_id=project_id,
                        content=fact_text,
                        category=fact.get("category", ""),
                        type=memory_type,
                        node_type=FACT_NODE_TYPE,
                        subject_kind=None,
                        source_conversation_id=conversation_id if memory_type == "temporary" else None,
                        parent_memory_id=parent_memory_id,
                        subject_memory_id=subject_memory.id,
                        node_status=ACTIVE_NODE_STATUS,
                        canonical_key=str(metadata.get("canonical_key") or "").strip() or None,
                        lineage_key=None,
                        confidence=importance,
                        observed_at=datetime.now(timezone.utc),
                        valid_from=datetime.now(timezone.utc),
                        valid_to=None,
                        last_confirmed_at=datetime.now(timezone.utc),
                        metadata_json=metadata,
                    )
                    apply_temporal_defaults(memory)
                    db.add(memory)
                    db.flush()
                    ensure_fact_lineage(memory)

                    # Embed the memory for future RAG retrieval
                    try:
                        await embed_and_store(
                            db,
                            workspace_id=workspace_id,
                            project_id=project_id,
                            memory_id=memory.id,
                            chunk_text=memory.content,
                            vector=query_vector,
                            auto_commit=False,
                        )
                    except Exception:  # noqa: BLE001
                        pass  # Embedding failure is non-fatal

                    if parent_memory and not is_assistant_root_memory(parent_memory):
                        try:
                            edge_strength = 0.72 if triage_action == "append" else anchor_strength or 0.65
                            _upsert_auto_memory_edge(
                                db,
                                source_memory_id=parent_memory.id,
                                target_memory_id=memory.id,
                                strength=edge_strength,
                            )
                        except Exception:  # noqa: BLE001
                            pass

                    evidence_ids = _record_source_message_evidence(
                        db,
                        memory=memory,
                        conversation=conversation,
                        source_message=source_user_msg,
                        quote_text=user_message,
                        confidence=importance,
                        source=fact_source,
                        episode_id=source_episode.id if source_episode is not None else None,
                    )
                    update_memory_write_item(
                        write_item,
                        decision="append" if triage_action == "append" else "create",
                        target_memory_id=triage_target_memory_id if triage_action == "append" else memory.id,
                        reason=triage_reason,
                        metadata_json={
                            "evidence_ids": evidence_ids,
                            "merged_content": memory.content,
                            "policy_flags": [fact_source],
                            "result_memory_id": memory.id,
                            "parent_memory_id": parent_memory.id if parent_memory is not None else None,
                        },
                    )
                    _collect_view_refresh(
                        subject_memory,
                        source_memory_id=memory.id,
                        source_text=memory.content,
                    )
                    fact_display["status"] = "appended" if parent_memory_id and triage_action == "append" else memory_type
                    fact_display["triage_action"] = triage_action
                    fact_display["target_memory_id"] = triage_target_memory_id or memory.id
                    fact_display["evidence_ids"] = evidence_ids
                    if parent_memory and not is_assistant_root_memory(parent_memory):
                        fact_display["parent_memory_id"] = parent_memory.id
                        fact_display["parent_memory_content"] = parent_memory.content
                        if concept_parent_created:
                            fact_display["parent_memory_action"] = "created"
                    if isinstance(triage_reason, str) and triage_reason.strip():
                        fact_display["triage_reason"] = triage_reason.strip()
                    processed_facts.append(fact_display)

                for payload in subject_view_inputs.values():
                    subject_memory = payload.get("subject_memory")
                    if not isinstance(subject_memory, Memory):
                        continue
                    source_memory_ids = [
                        str(item)
                        for item in payload.get("memory_ids", [])
                        if isinstance(item, str) and item.strip()
                    ]
                    playbook_text = "\n".join(
                        str(item).strip()
                        for item in payload.get("playbook_texts", [])
                        if str(item).strip()
                    )
                    try:
                        refresh_subject_views(
                            db,
                            subject_memory=subject_memory,
                            playbook_source_text=playbook_text or None,
                            playbook_source_memory_ids=source_memory_ids,
                        )
                    except Exception:  # noqa: BLE001
                        pass
                finalize_memory_write_run(
                    write_run,
                    status="completed",
                    metadata_json={
                        "item_count": len(processed_facts),
                        "subject_count": len(subject_view_inputs),
                    },
                )
                used_memory_ids = [
                    str(item.get("target_memory_id") or "").strip()
                    for item in processed_facts
                    if isinstance(item.get("target_memory_id"), str) and str(item.get("target_memory_id") or "").strip()
                ]
                promoted_memory_ids = [
                    str(item.get("target_memory_id") or "").strip()
                    for item in processed_facts
                    if str(item.get("triage_action") or "").strip() in {"promote"}
                    and isinstance(item.get("target_memory_id"), str)
                    and str(item.get("target_memory_id") or "").strip()
                ]
                degraded_memory_ids = [
                    str(item.get("supersedes_memory_id") or item.get("conflict_with_memory_id") or "").strip()
                    for item in processed_facts
                    if isinstance(item.get("supersedes_memory_id") or item.get("conflict_with_memory_id"), str)
                    and str(item.get("supersedes_memory_id") or item.get("conflict_with_memory_id") or "").strip()
                ]
                finalize_memory_learning_run(
                    learning_run,
                    status="completed",
                    stages=merge_learning_stages(
                        learning_run.stages,
                        ["observe", "extract", "consolidate", "graphify"],
                    ),
                    used_memory_ids=used_memory_ids,
                    promoted_memory_ids=promoted_memory_ids,
                    degraded_memory_ids=degraded_memory_ids,
                    metadata_json={
                        "write_run_id": write_run.id if write_run is not None else None,
                        "episode_id": source_episode.id if source_episode is not None else None,
                        "item_count": len(processed_facts),
                    },
                )
                if ai_msg:
                    try:
                        _persist_memory_extraction_metadata(
                            ai_msg,
                            processed_facts=processed_facts,
                            empty_summary="本轮未提取到可保存记忆",
                            attempts=attempt_index,
                            run_id=write_run.id if write_run is not None else None,
                            learning_run_id=learning_run.id if learning_run is not None else None,
                        )
                        db.flush()
                    except Exception:  # noqa: BLE001
                        pass  # Non-fatal: display data only
            finally:
                await close_current_client()

        # Run all async work in a single event loop
        asyncio.run(_extract_and_store_facts())

        # ── Auto-promotion: temporary → permanent when same fact appears in 2+ conversations ──
        # A temporary memory should auto-promote to permanent if:
        # 1. The same fact appears in 2+ different conversations (vector similarity > 0.85)
        # 2. The extraction marked it with importance >= 0.9 (already handled above)
        temp_memories = db.query(Memory).filter(
            Memory.project_id == project_id,
            Memory.type == "temporary",
        ).all()

        for mem in temp_memories:
            try:
                # Check if similar content exists in other conversations
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

            if similar and similar >= 1:  # Found in at least 1 other conversation
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
                    mem.source_conversation_id = None  # Detach from conversation
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

        ensure_project_related_edges(
            db,
            workspace_id=workspace_id,
            project_id=project_id,
        )
        ensure_project_prerequisite_edges(
            db,
            workspace_id=workspace_id,
            project_id=project_id,
        )
        graph_changed = session_has_pending_graph_mutations(db)
        db.commit()
        if graph_changed:
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
            run_id=write_run.id if write_run is not None else None,
            learning_run_id=learning_run.id if learning_run is not None else None,
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
