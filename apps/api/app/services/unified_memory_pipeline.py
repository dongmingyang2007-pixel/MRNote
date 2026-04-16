"""Unified Memory Pipeline — shared extraction/promotion service.

This module extracts the full 12-stage memory processing pipeline from
``worker_tasks.py`` into a reusable service that supports multiple source
types (chat messages, notebook pages, uploaded documents, whiteboards,
book chapters).

The pipeline stages are:

1.  Extract — LLM-based fact extraction with fallback heuristics
2.  Filter — importance threshold + aggregate-fact detection
3.  Subject Resolution — find or create the subject Memory node
4.  Dedup — vector similarity check against existing memories
5.  Triage — LLM decision (create / append / merge / replace / conflict / discard)
6.  Validate Append — LLM confirmation of parent relationship
7.  Promote / Supersede / Conflict — versioning operations
8.  Concept Parent — automatic topic hierarchy
9.  Memory Creation — entity + metadata + lineage
10. Evidence Recording — link memory to its source
11. Embedding — vectorise for retrieval
12. Edge + View Refresh — graph edges and subject views

Usage::

    from app.services.unified_memory_pipeline import run_pipeline, PipelineInput, SourceContext

    result = await run_pipeline(db, PipelineInput(
        source_type="notebook_page",
        source_text=page.plain_text,
        source_ref=str(page.id),
        workspace_id=str(workspace_id),
        project_id=str(project_id),
        user_id=str(user_id),
        context=SourceContext(owner_user_id=str(user_id)),
        context_text=page.title or "",
    ))
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    Conversation,
    Memory,
    MemoryEdge,
    MemoryEpisode,
    MemoryLearningRun,
    MemoryWriteItem,
    MemoryWriteRun,
    Message,
    Project,
)
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
from app.services.memory_related_edges import (
    ensure_project_prerequisite_edges,
    ensure_project_related_edges,
)
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
from app.services.memory_versioning import (
    create_conflicting_fact,
    create_fact_successor,
    ensure_fact_lineage,
)
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
from app.services import dashscope_client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Source types
# ---------------------------------------------------------------------------

SourceType = Literal[
    "chat_message",
    "notebook_page",
    "uploaded_document",
    "whiteboard",
    "book_chapter",
    # S4: user kept getting a card wrong, or explicitly marked it confusing.
    "study_confusion",
]


# ---------------------------------------------------------------------------
# Pipeline input / output data classes
# ---------------------------------------------------------------------------


@dataclass
class SourceContext:
    """Abstracts the source-specific context away from the pipeline logic.

    For chat messages, this carries conversation/message IDs.
    For notebook pages, these fields are typically None.
    """

    owner_user_id: str | None = None
    conversation_id: str | None = None
    message_id: str | None = None
    source_conversation_id: str | None = None
    primary_subject_id: str | None = None  # chat: from conversation.metadata_json


@dataclass
class PipelineInput:
    """Everything the pipeline needs to process content from any source."""

    source_type: SourceType
    source_text: str
    source_ref: str  # page_id, message_id, chunk_id, etc.
    workspace_id: str
    project_id: str
    user_id: str
    context: SourceContext = field(default_factory=SourceContext)
    context_text: str = ""  # additional context (page title, chapter heading, etc.)
    max_text_length: int = 6000


@dataclass
class PipelineResult:
    """Summary returned after the pipeline completes."""

    write_run_id: str | None = None
    learning_run_id: str | None = None
    episode_id: str | None = None
    processed_facts: list[dict[str, Any]] = field(default_factory=list)
    item_count: int = 0
    status: str = "empty"  # "completed" | "failed" | "empty"
    summary: str | None = None
    graph_changed: bool = False  # True if Memory/MemoryEdge was created/modified


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

EXTRACTION_PROMPT_CHAT = """你是一个严格的 JSON 记忆提取器。只根据用户原话，提取用户明确表达的可记忆原子事实。

用户原话：
{user_message}

要求：
- 只提取用户**明确表达**的事实
- 每条事实必须是**原子化**的（一条只说一件事）
- category 使用**点分层级**格式（如 "饮食.偏好"、"工作.计划"）
- importance 取值 high/medium/low
- 如果没有可提取的事实，返回空数组 []

输出严格 JSON 数组：
[{{"fact": "...", "category": "...", "importance": "high|medium|low"}}]"""

EXTRACTION_PROMPT_NOTEBOOK = """你是一个严格的 JSON 记忆提取器。根据用户写的笔记内容，提取可记忆的原子事实。

笔记标题：{context_text}

笔记内容：
{user_message}

要求：
- 只提取用户**明确表达**的事实、偏好、目标、计划
- 每条事实必须是**原子化**的（一条只说一件事）
- category 使用**点分层级**格式（如 "饮食.偏好"、"工作.计划"、"学习.笔记"）
- importance 取值 high/medium/low
- 如果没有可提取的事实，返回空数组 []

输出严格 JSON 数组：
[{{"fact": "...", "category": "...", "importance": "high|medium|low"}}]"""

FALLBACK_EXTRACTION_PROMPT = """你是一个严格的 JSON 记忆提取器。只根据用户原话，提取用户明确表达的可记忆原子事实。

用户原话：
{user_message}

请仔细再看一遍。如果确实有可提取的事实，输出 JSON 数组。如果没有，返回 []。

输出严格 JSON 数组：
[{{"fact": "...", "category": "...", "importance": "high|medium|low"}}]"""

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

APPEND_PARENT_VALIDATION_PROMPT = """你是记忆层级校验器。判断"候选记忆"能不能作为"新事实"的父节点。

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

_CONCEPT_PARENT_SUPPORTED_KINDS = {
    MEMORY_KIND_FACT,
    MEMORY_KIND_PREFERENCE,
    MEMORY_KIND_GOAL,
}

_IMPORTANCE_MAP = {"high": 0.9, "medium": 0.5, "low": 0.2}


# ---------------------------------------------------------------------------
# Regex patterns & lookup tables (from worker_tasks.py)
# ---------------------------------------------------------------------------

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
_QUOTED_SUBJECT_PATTERN = re.compile(r"[《\u201c\"]([^》\u201d\"]{2,48})[》\u201d\"]")
_SUBJECT_REFERENCE_HINTS = (
    "这个角色", "这个人物", "这位人物", "这个人", "这个人设", "这个设定", "这个背景",
    "这本书", "这门课", "这个课程", "这个项目", "这个理论", "这个模型", "这个框架",
    "这篇论文", "这个设备", "这套系统",
    "this book", "this course", "this project", "this theory", "this model", "this paper",
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
    ("书", "book"), ("课程", "course"), ("课", "course"), ("项目", "project"),
    ("工程", "project"), ("论文", "paper"), ("理论", "theory"), ("模型", "theory"),
    ("框架", "theory"), ("设备", "device"), ("硬件", "device"), ("学科", "domain"),
    ("领域", "domain"),
)
_GENERIC_SUBJECT_LABELS = {
    "这个", "这位", "那个", "那位", "这个角色", "这个人物", "这个人",
    "这本书", "这个项目", "这个理论", "这门课", "课程", "项目", "理论",
    "模型", "框架", "论文", "设备", "系统",
}
_GENERIC_SUBJECT_QUERY_PATTERNS: tuple[tuple[re.Pattern[str], str | None], ...] = (
    (re.compile(r"^(?:(?:最近|今天|突然|忽然|刚刚|现在|一直|我|又|还|再)\s*){0,4}(?:想聊|又想聊|还想聊|想再聊聊)\s*([A-Za-z0-9\u4e00-\u9fff·._\-]{2,48})"), None),
    (re.compile(r"^(?:再)?(?:关于|聊聊|说说|讲讲|介绍(?:一下)?|科普(?:一下)?|分析(?:一下)?|讨论(?:一下)?|看看|想了解|想知道|研究(?:一下)?)\s*([A-Za-z0-9\u4e00-\u9fff·._\-]{2,48})"), None),
    (re.compile(r"([A-Za-z0-9\u4e00-\u9fff·._\-]{2,48})的(?:[^，。！？,.!?]{0,24})?(?:设定|剧情|背景|技能|能力)"), None),
    (re.compile(r"([A-Za-z0-9\u4e00-\u9fff·._\-]{2,48})(?:为什么|怎么样|是谁|是什么|如何)"), None),
    (re.compile(r"([A-Za-z0-9\u4e00-\u9fff·._\-]{2,48})(?:这个|这位)?(角色|人物|人|作品|游戏|动漫)"), None),
)
_SUBJECT_SUFFIX_KIND_HINTS: dict[str, str] = {
    "角色": "person", "人物": "person", "人": "person",
    "作品": "custom", "游戏": "project", "动漫": "custom",
}
_BEHAVIORAL_INTEREST_QUERY_HINTS = (
    "?", "？", "关于", "聊聊", "说说", "讲讲", "介绍", "科普", "分析", "讨论",
    "想了解", "想知道", "为什么", "如何", "怎么", "设定", "剧情", "背景",
    "技能", "能力", "是谁", "是什么",
)
_BEHAVIORAL_INTEREST_CATEGORY_BY_KIND: dict[str, str] = {
    "book": "偏好.关注.书籍", "course": "偏好.关注.课程", "project": "偏好.关注.项目",
    "theory": "偏好.关注.理论", "paper": "偏好.关注.论文", "device": "偏好.关注.设备",
    "person": "偏好.关注.人物", "domain": "偏好.关注.领域",
}
_NON_USER_FACT_PREDICATE_PREFIXES = (
    "是", "有", "在", "很", "比较", "更", "最", "并", "会", "能", "可",
    "让人", "令人", "显得", "看起来", "属于", "来自", "位于", "放在",
    "拥有", "带有", "不是", "并不",
)
_FACT_CONCEPT_TOPIC_HINTS: tuple[tuple[str, str], ...] = (
    ("人设", "设定"), ("设定", "设定"), ("世界观", "设定"), ("定位", "设定"),
    ("背景", "背景"), ("来历", "背景"), ("出身", "背景"), ("历史", "背景"),
    ("经历", "经历"), ("剧情", "经历"), ("故事", "经历"), ("事件", "经历"), ("过去", "经历"),
    ("能力", "能力"), ("技能", "能力"), ("招式", "能力"), ("术式", "能力"), ("武器", "能力"),
    ("关系", "关系"), ("互动", "关系"), ("对手", "关系"), ("朋友", "关系"), ("搭档", "关系"),
    ("身份", "身份"), ("种族", "身份"), ("职业", "身份"), ("头衔", "身份"), ("称号", "身份"), ("职位", "身份"),
    ("性格", "特征"), ("特点", "特征"), ("辨识度", "特征"), ("风格", "特征"),
    ("外观", "特征"), ("形象", "特征"), ("气质", "特征"), ("特征", "特征"),
)
_USER_FACT_CONCEPT_TOPIC_HINTS: tuple[tuple[str, str], ...] = (
    ("education", "教育"), ("study", "教育"), ("school", "教育"), ("学业", "教育"), ("教育", "教育"),
    ("identity", "身份"), ("身份", "身份"), ("profile", "个人"), ("personal", "个人"), ("个人", "个人"),
    ("work", "工作"), ("job", "工作"), ("career", "工作"), ("profession", "工作"), ("职业", "工作"), ("工作", "工作"),
    ("travel", "旅行"), ("trip", "旅行"), ("旅行", "旅行"),
    ("location", "地点"), ("place", "地点"), ("residence", "地点"), ("居住", "地点"), ("地点", "地点"),
    ("relationship", "关系"), ("关系", "关系"),
    ("food", "饮食"), ("drink", "饮食"), ("diet", "饮食"), ("饮食", "饮食"),
    ("学习", "学习"), ("learning", "学习"), ("health", "健康"), ("健康", "健康"),
)
_USER_FACT_CONCEPT_TOPIC_SKIP_KEYS = {"user", "custom", "fact", "事实", "记忆", "memory"}
_USER_FACT_CONCEPT_LABELS: dict[str, str] = {
    "教育": "教育背景", "身份": "身份信息", "个人": "个人信息", "工作": "工作经历",
    "地点": "地点经历", "关系": "关系网络", "饮食": "饮食习惯", "学习": "学习轨迹",
    "健康": "健康情况", "旅行": "旅行经历",
}
_PERSON_FACT_CONCEPT_LABELS: dict[str, str] = {
    "设定": "角色设定", "背景": "角色背景", "经历": "经历事件", "能力": "能力体系",
    "关系": "关系网络", "身份": "身份定位", "特征": "形象特征",
}
_GENERIC_FACT_CONCEPT_LABELS: dict[str, str] = {
    "设定": "核心设定", "背景": "背景信息", "经历": "相关经历", "能力": "能力体系",
    "关系": "关联关系", "身份": "身份定位", "特征": "关键特征",
}
_PERSON_LIKE_CATEGORY_HINTS = {"人物", "角色", "角色设定", "人物设定"}


# ---------------------------------------------------------------------------
# Group A: Text normalization helpers
# ---------------------------------------------------------------------------


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
    return re.sub(r"[\uff0c\u3002\u3001\u201c\u201d\u2018\u2019\"'`()\uff08\uff09,.!?\uff01\uff1f\uff1a\uff1b:;\-_/\\]+", "", normalized)


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


# ---------------------------------------------------------------------------
# Group B: Triage async function
# ---------------------------------------------------------------------------


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
        f"- ID: {c['memory_id']} | \u5206\u7c7b: {c['category']} | \u5185\u5bb9: {c['content']}"
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


# ---------------------------------------------------------------------------
# Group C: Fact processing helpers
# ---------------------------------------------------------------------------


def _normalize_extracted_fact_text(value: str) -> str:
    normalized = re.sub(r"^[\-\*\u2022]+\s*", "", str(value or "").strip())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    normalized = _FIRST_PERSON_FACT_PREFIX_PATTERN.sub("\u7528\u6237", normalized)
    return normalized


def _looks_like_predicate_only_fact(value: str) -> bool:
    normalized = str(value or "").strip()
    if not normalized:
        return False
    return normalized.startswith(_NON_USER_FACT_PREDICATE_PREFIXES)


def _canonicalize_fact_text_for_storage(
    *,
    fact_text: str,
    source_text: str,
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
        ("\u5979\u7684", f"{subject_label}\u7684"),
        ("\u4ed6\u7684", f"{subject_label}\u7684"),
        ("\u5b83\u7684", f"{subject_label}\u7684"),
        ("TA\u7684", f"{subject_label}\u7684"),
        ("ta\u7684", f"{subject_label}\u7684"),
        ("\u8fd9\u4e2a\u89d2\u8272\u7684", f"{subject_label}\u7684"),
        ("\u8fd9\u4e2a\u4eba\u7269\u7684", f"{subject_label}\u7684"),
        ("\u8fd9\u4e2a\u4eba\u7684", f"{subject_label}\u7684"),
        ("\u8fd9\u4f4d\u4eba\u7269\u7684", f"{subject_label}\u7684"),
        ("\u8fd9\u4f4d\u7684", f"{subject_label}\u7684"),
        ("\u8be5\u89d2\u8272\u7684", f"{subject_label}\u7684"),
        ("\u8be5\u4eba\u7269\u7684", f"{subject_label}\u7684"),
        ("\u8be5\u4eba\u7684", f"{subject_label}\u7684"),
        ("\u8fd9\u4e2a\u4eba\u8bbe", f"{subject_label}\u7684\u4eba\u8bbe"),
        ("\u8fd9\u4e2a\u8bbe\u5b9a", f"{subject_label}\u7684\u8bbe\u5b9a"),
        ("\u8fd9\u4e2a\u80cc\u666f", f"{subject_label}\u7684\u80cc\u666f"),
        ("\u5979", subject_label),
        ("\u4ed6", subject_label),
        ("\u5b83", subject_label),
        ("TA", subject_label),
        ("ta", subject_label),
        ("\u8fd9\u4e2a\u89d2\u8272", subject_label),
        ("\u8fd9\u4e2a\u4eba\u7269", subject_label),
        ("\u8fd9\u4e2a\u4eba", subject_label),
        ("\u8fd9\u4f4d\u4eba\u7269", subject_label),
        ("\u8fd9\u4f4d", subject_label),
        ("\u8be5\u89d2\u8272", subject_label),
        ("\u8be5\u4eba\u7269", subject_label),
        ("\u8be5\u4eba", subject_label),
    )
    for source, target in prefix_replacements:
        if rewritten.startswith(source):
            rewritten = f"{target}{rewritten[len(source):]}"
            break

    if rewritten == normalized:
        inline_replacements = (
            ("\u5979\u7684", f"{subject_label}\u7684"),
            ("\u4ed6\u7684", f"{subject_label}\u7684"),
            ("\u5b83\u7684", f"{subject_label}\u7684"),
            ("TA\u7684", f"{subject_label}\u7684"),
            ("ta\u7684", f"{subject_label}\u7684"),
            ("\u8fd9\u4e2a\u89d2\u8272\u7684", f"{subject_label}\u7684"),
            ("\u8fd9\u4e2a\u4eba\u7269\u7684", f"{subject_label}\u7684"),
            ("\u8fd9\u4e2a\u4eba\u7684", f"{subject_label}\u7684"),
            ("\u8fd9\u4f4d\u4eba\u7269\u7684", f"{subject_label}\u7684"),
            ("\u8be5\u89d2\u8272\u7684", f"{subject_label}\u7684"),
            ("\u8be5\u4eba\u7269\u7684", f"{subject_label}\u7684"),
            ("\u8be5\u4eba\u7684", f"{subject_label}\u7684"),
        )
        for source, target in inline_replacements:
            rewritten = rewritten.replace(source, target)

    if (
        subject_label not in rewritten
        and (
            _is_deictic_subject_reference(source_text)
            or subject_resolution in {"conversation_focus_subject", "non_user_focus_fallback"}
        )
        and _looks_like_predicate_only_fact(rewritten)
    ):
        rewritten = f"{subject_label}{rewritten}"

    return _normalize_extracted_fact_text(rewritten)


def _normalize_subject_label(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(value or "").strip())
    cleaned = cleaned.strip("\uff0c\u3002\u3001\u201c\u201d\u2018\u2019\"'`()\uff08\uff09[]\u3010\u3011<>\u300a\u300b\uff1a\uff1b:;,.!?\uff01\uff1f")
    if not cleaned or cleaned in _GENERIC_SUBJECT_LABELS:
        return ""
    if re.match(r"^(?:\u5979|\u4ed6|\u5b83|TA|ta)(?:$|\u7684)", cleaned):
        return ""
    if re.match(r"^(?:\u8fd9\u4e2a|\u8fd9\u4f4d|\u8be5)(?:$|\u89d2\u8272|\u4eba\u7269|\u4eba|\u4eba\u8bbe|\u8bbe\u5b9a|\u80cc\u666f)", cleaned):
        return ""
    if len(cleaned) > 48:
        return ""
    return cleaned


def _trim_generic_subject_candidate(value: str) -> str:
    cleaned = str(value or "").strip()
    cleaned = re.sub(r"^(?:\u8fd8\u6709|\u53e6\u5916|\u987a\u4fbf|\u4ee5\u53ca|\u518d(?:\u804a\u804a|\u8bb2\u8bb2|\u8bf4\u8bf4)?)", "", cleaned).strip()
    cleaned = re.sub(
        r"\u7684(?:\u8bbe\u5b9a|\u5267\u60c5|\u80cc\u666f|\u6280\u80fd|\u80fd\u529b)(?:\u548c(?:\u8bbe\u5b9a|\u5267\u60c5|\u80cc\u666f|\u6280\u80fd|\u80fd\u529b))*$",
        "",
        cleaned,
    )
    cleaned = re.sub(
        r"(?:\u8fd9\u4e2a|\u8fd9\u4f4d)?(?:\u89d2\u8272|\u4eba\u7269|\u4eba|\u4f5c\u54c1|\u6e38\u620f|\u52a8\u6f2b)(?:\u7684?(?:\u8bbe\u5b9a|\u5267\u60c5|\u80cc\u666f|\u6280\u80fd|\u80fd\u529b))?$",
        "",
        cleaned,
    )
    cleaned = re.sub(r"(?:\u662f\u8c01|\u662f\u4ec0\u4e48|\u600e\u4e48\u6837|\u5982\u4f55|\u4e3a\u4ec0\u4e48|\u5417|\u5462|\u554a|\u5440|\u5427)$", "", cleaned)
    cleaned = re.sub(r"(?:\u7684\u8bbe\u5b9a|\u7684\u5267\u60c5|\u7684\u80cc\u666f|\u7684\u6280\u80fd|\u7684\u80fd\u529b)$", "", cleaned)
    return _normalize_subject_label(cleaned)


# ---------------------------------------------------------------------------
# Group D: Subject resolution helpers
# ---------------------------------------------------------------------------


def _looks_like_user_fact(fact_text: str) -> bool:
    normalized = str(fact_text or "").strip()
    return bool(
        normalized
        and (
            normalized.startswith("\u7528\u6237")
            or normalized.startswith("\u6211")
            or normalized.startswith("\u672c\u4eba")
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
            re.compile(r"(?:\u9879\u76ee|\u5de5\u7a0b|\u7cfb\u7edf|\u5e73\u53f0|\u5e94\u7528|\u5de5\u5177|\u4ea7\u54c1)[\uff1a:\s]*([A-Za-z0-9\u4e00-\u9fff._\-]{2,40})"),
            "project",
        ),
        (
            re.compile(r"(?:\u8bfe\u7a0b|\u8fd9\u95e8\u8bfe|\u8bfe\u9898|\u8bb2\u4e49)[\uff1a:\s]*([A-Za-z0-9\u4e00-\u9fff._\-]{2,40})"),
            "course",
        ),
        (
            re.compile(r"(?:\u7406\u8bba|\u6a21\u578b|\u6846\u67b6|\u5b9a\u5f8b|\u5b9a\u7406)[\uff1a:\s]*([A-Za-z0-9\u4e00-\u9fff._\-]{2,40})"),
            "theory",
        ),
        (
            re.compile(r"(?:\u8bba\u6587|paper)[\uff1a:\s]*([A-Za-z0-9\u4e00-\u9fff._\-]{2,40})"),
            "paper",
        ),
        (
            re.compile(r"(?:\u8bbe\u5907|\u4eea\u5668|\u673a\u5668\u4eba)[\uff1a:\s]*([A-Za-z0-9\u4e00-\u9fff._\-]{2,40})"),
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
    context: SourceContext,
    source_text: str,
    fact_text: str,
    fact_category: str,
) -> tuple[Memory, bool, str]:
    user_subject, user_subject_changed = ensure_project_user_subject(
        db,
        project,
        owner_user_id=context.owner_user_id,
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
        if _subject_visible_to_owner(memory, owner_user_id=context.owner_user_id)
    ]
    subjects_by_id = {memory.id: memory for memory in subject_memories}
    combined_text = "\n".join(
        value for value in [source_text, fact_text, fact_category] if str(value or "").strip()
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

    primary_subject_id = str(context.primary_subject_id or "").strip()
    primary_subject = subjects_by_id.get(primary_subject_id) if primary_subject_id else None
    if (
        primary_subject is not None
        and get_subject_kind(primary_subject) != "user"
        and not _looks_like_user_fact(fact_text)
        and (_is_deictic_subject_reference(source_text) or not subject_label)
    ):
        return primary_subject, user_subject_changed, "conversation_focus_subject"

    if subject_label and not _looks_like_user_fact(fact_text):
        subject_kind = subject_kind or _infer_subject_kind(source_text, fact_text, fact_category) or "custom"
        subject_memory, subject_changed = ensure_project_subject(
            db,
            project,
            subject_kind=subject_kind,
            label=subject_label,
            owner_user_id=context.owner_user_id,
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


# ---------------------------------------------------------------------------
# Group E: Behavioral interest helpers
# ---------------------------------------------------------------------------


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
        if any(token in fact_text for token in ("\u559c\u6b22", "\u504f\u597d", "\u70ed\u7231", "\u611f\u5174\u8da3")) or "\u504f\u597d" in category:
            return True
    return False


def _build_behavioral_interest_fact_text(subject_label: str) -> str:
    normalized_label = _normalize_subject_label(subject_label)
    if not normalized_label:
        return ""
    return f"\u7528\u6237\u5bf9{normalized_label}\u611f\u5174\u8da3\u3002"


def _build_behavioral_interest_category(subject_kind: str | None) -> str:
    normalized_kind = str(subject_kind or "").strip().lower()
    return _BEHAVIORAL_INTEREST_CATEGORY_BY_KIND.get(normalized_kind, "\u504f\u597d.\u5173\u6ce8")


def _build_behavioral_interest_reason(
    *,
    subject_label: str,
    same_conversation_turns: int,
    distinct_conversations: int,
) -> str:
    if distinct_conversations >= 2:
        return (
            f"\u57fa\u4e8e\u7528\u6237\u5728 {distinct_conversations} \u4e2a\u5bf9\u8bdd\u91cc\u53cd\u590d\u56f4\u7ed5\u300c{subject_label}\u300d\u63d0\u95ee\uff0c"
            "\u63a8\u65ad\u8fd9\u662f\u7a33\u5b9a\u5173\u6ce8\u4e3b\u9898\u3002"
        )
    return f"\u57fa\u4e8e\u7528\u6237\u5728\u5f53\u524d\u5bf9\u8bdd\u4e2d\u8fde\u7eed {same_conversation_turns} \u8f6e\u56f4\u7ed5\u300c{subject_label}\u300d\u63d0\u95ee\uff0c\u63a8\u65ad\u8fd9\u662f\u6301\u7eed\u5173\u6ce8\u4e3b\u9898\u3002"


def _infer_behavioral_interest_fact(
    db,
    *,
    project: Project,
    context: SourceContext,
    workspace_id: str,
    project_id: str,
    user_message: str,
    extracted_facts: list[dict[str, object]],
) -> tuple[dict[str, object] | None, bool]:
    if not _query_signals_topic_interest(user_message):
        return None, False

    primary_subject_id = str(context.primary_subject_id or "").strip() or None
    primary_subject = _load_subject_memory(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        owner_user_id=context.owner_user_id,
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
        subject_label, subject_kind = _extract_subject_hint(text=user_message, category="\u504f\u597d.\u5173\u6ce8")
        if not subject_label:
            return None, False

    label_key = _normalize_text_key(subject_label)
    if not label_key or _facts_already_capture_subject_interest(extracted_facts, label_key=label_key):
        return None, False

    mention_counts = _count_subject_mentions_by_conversation(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        owner_user_id=context.owner_user_id,
        label_key=label_key,
    )
    conversation_id = context.conversation_id or ""
    same_conversation_turns = mention_counts.get(conversation_id, 0)
    distinct_conversations = len(mention_counts)
    if subject is not None and not current_message_is_lexical_hit and _is_deictic_subject_reference(user_message):
        same_conversation_turns += 1
        if conversation_id not in mention_counts:
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
            subject_kind=subject_kind or _infer_subject_kind(user_message, subject_label, "\u504f\u597d.\u5173\u6ce8") or "custom",
            label=subject_label,
            owner_user_id=context.owner_user_id,
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


# ---------------------------------------------------------------------------
# Group F: Dedup/promote helpers
# ---------------------------------------------------------------------------


def _promote_temporary_duplicate_to_permanent(
    duplicate_memory: Memory,
    *,
    fact_text: str,
    fact_category: str,
    importance: float,
    fact_source: str,
    owner_user_id: str | None,
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
        owner_user_id=owner_user_id,
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


def _looks_like_aggregate_fact(
    fact_text: str,
    *,
    fact_category: str,
    fact_memory_kind: str,
) -> bool:
    normalized = re.sub(r"\s+", "", str(fact_text or "").strip())
    if not normalized:
        return False
    if fact_memory_kind not in {MEMORY_KIND_PREFERENCE, MEMORY_KIND_GOAL} and "\u504f\u597d" not in str(fact_category or ""):
        return False
    if not any(separator in normalized for separator in ("\u3001", "\u548c", "\u4ee5\u53ca", "\u53ca", "\uff0c", ",")):
        return False
    return bool(
        re.match(
            r"^\u7528\u6237(?:\u504f\u597d|\u559c\u6b22|\u559c\u7231|\u7231\u559d|\u7231\u5403|\u70ed\u7231|\u8ba1\u5212|\u6253\u7b97|\u51c6\u5907|\u60f3\u8981)[^\u3002\uff01\uff1f!?]*[\u3001\u548c\u53ca\u4ee5\u53ca\uff0c,][^\u3002\uff01\uff1f!?]*[\u3002\uff01\uff1f!?]?$",
            normalized,
        )
    )


# ---------------------------------------------------------------------------
# Group G: Generalized evidence recording
# ---------------------------------------------------------------------------


def _record_source_evidence(
    db,
    *,
    memory: Memory,
    source_type: str,
    source_ref: str | None = None,
    conversation_id: str | None = None,
    message_id: str | None = None,
    message_role: str = "user",
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
        source_type=source_type,
        conversation_id=conversation_id,
        message_id=message_id,
        message_role=message_role,
        episode_id=episode_id,
        quote_text=normalized_quote,
        confidence=confidence,
        metadata_json={"source": source, "source_ref": source_ref},
    )
    return [evidence.id]


# ---------------------------------------------------------------------------
# Group H: Concept parent helpers
# ---------------------------------------------------------------------------


def _sanitize_concept_topic(topic: str) -> str:
    cleaned = re.sub(r"\s+", "", str(topic or "").strip())
    cleaned = cleaned.strip("\uff0c\u3002\u3001\u201c\u201d\u2018\u2019\"'`()\uff08\uff09[]\u3010\u3011<>\u300a\u300b\uff1a\uff1b:;,.!?\uff01\uff1f")
    for suffix in ("\u996e\u54c1", "\u996e\u6599", "\u98df\u54c1", "\u98df\u7269", "\u7c7b\u522b", "\u7c7b\u578b"):
        if cleaned.endswith(suffix) and len(cleaned) > len(suffix):
            cleaned = cleaned[: -len(suffix)]
            break
    if not cleaned:
        return ""
    if len(cleaned) > 18:
        return ""
    if any(token in cleaned for token in ("\u7528\u6237", "\u4e8b\u5b9e", "\u8bb0\u5fc6", "\u4e3b\u9898", "\u504f\u597d", "\u76ee\u6807")):
        return ""
    return cleaned


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
        return _USER_FACT_CONCEPT_LABELS.get(canonical_topic, f"{canonical_topic}\u4fe1\u606f")
    if _is_person_like_fact_subject(subject_memory=subject_memory, fact_category=fact_category):
        return _PERSON_FACT_CONCEPT_LABELS.get(canonical_topic, f"{canonical_topic}\u4fe1\u606f")
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
        return f"\u7528\u6237\u5bf9{topic}\u611f\u5174\u8da3"
    if memory_kind == MEMORY_KIND_GOAL:
        return f"\u7528\u6237\u6709{topic}\u76f8\u5173\u76ee\u6807"
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
                "reason": f"\u6839\u636e\u5206\u7c7b\u548c\u4e8b\u5b9e\u5185\u5bb9\u5f52\u5165\u300c{concept_label}\u300d\u4e3b\u9898\u3002",
            }

    prompt = CONCEPT_TOPIC_PROMPT.format(
        subject_label=subject_memory.content.strip() or "\u672a\u547d\u540d\u4e3b\u4f53",
        subject_kind=get_subject_kind(subject_memory) or "custom",
        fact=fact_text,
        category=fact_category or "\u672a\u5206\u7c7b",
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
            semantic_reason = f"{semantic_reason}\uff1b\u590d\u7528\u8bed\u4e49\u76f8\u8fd1\u7684\u65e2\u6709\u4e3b\u9898\u8282\u70b9\u3002"
        else:
            semantic_reason = "\u590d\u7528\u8bed\u4e49\u76f8\u8fd1\u7684\u65e2\u6709\u4e3b\u9898\u8282\u70b9\u3002"
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
        return {"relation": "parent", "reason": "\u5019\u9009\u8bb0\u5fc6\u662f\u4e3b\u9898\u8282\u70b9\uff0c\u53ef\u4f5c\u4e3a\u7a33\u5b9a\u7236\u8282\u70b9\u3002"}

    prompt = APPEND_PARENT_VALIDATION_PROMPT.format(
        candidate=candidate_memory.content,
        candidate_category=candidate_memory.category or "\u672a\u5206\u7c7b",
        fact=fact_text,
        fact_category=fact_category or "\u672a\u5206\u7c7b",
        memory_kind=fact_memory_kind or "fact",
    )

    fallback = {"relation": "unrelated", "reason": "\u5019\u9009\u8bb0\u5fc6\u4e0d\u662f\u7a33\u5b9a\u7684\u7236\u8282\u70b9\uff0c\u56de\u9000\u5230\u72ec\u7acb\u5efa\u6a21\u3002"}
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
                "reason": "\u666e\u901a\u4e8b\u5b9e\u8282\u70b9\u4e0d\u80fd\u4f5c\u4e3a\u81ea\u52a8\u7236\u8282\u70b9\uff0c\u6539\u4e3a\u540c\u4e3b\u9898\u5e76\u5217\u9879\u5e76\u5f52\u5165\u4e3b\u9898\u8282\u70b9\u3002",
            }
        return {
            "relation": "unrelated",
            "reason": "\u666e\u901a\u4e8b\u5b9e\u8282\u70b9\u4e0d\u80fd\u4f5c\u4e3a\u81ea\u52a8\u7236\u8282\u70b9\uff0c\u56de\u9000\u5230\u72ec\u7acb\u5efa\u6a21\u3002",
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


# ---------------------------------------------------------------------------
# Group I: Edge / summary / heuristic helpers
# ---------------------------------------------------------------------------


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
        ("permanent", "\u65b0\u589e\u6c38\u4e45\u8bb0\u5fc6"),
        ("temporary", "\u65b0\u589e\u4e34\u65f6\u8bb0\u5fc6"),
        ("appended", "\u6302\u63a5\u5230\u5df2\u6709\u8bb0\u5fc6"),
        ("superseded", "\u521b\u5efa\u65b0\u7248\u5e76\u66ff\u4ee3\u65e7\u4e8b\u5b9e"),
        ("conflicted", "\u521b\u5efa\u51b2\u7a81\u4e8b\u5b9e"),
        ("duplicate", "\u91cd\u590d\u8df3\u8fc7"),
        ("discarded", "\u88ab triage \u4e22\u5f03"),
        ("ignored", "\u91cd\u8981\u5ea6\u4e0d\u8db3\u88ab\u5ffd\u7565"),
    ]
    parts = [f"{label} {counts[key]} \u6761" for key, label in ordered_labels if counts.get(key)]
    if concept_parent_created:
        parts.append(f"\u65b0\u589e\u4e3b\u9898\u8282\u70b9 {concept_parent_created} \u6761")
    if not parts:
        return None
    return "\uff1b".join(parts)


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


def _guess_heuristic_memory_category(item: str, clause: str, action: str) -> str:
    text = f"{clause} {item}".strip()
    if re.search(r"(\u65c5\u884c|\u51fa\u884c|\u4e1c\u4eac|\u673a\u7968|\u9152\u5e97)", text):
        return "\u65c5\u884c.\u8ba1\u5212"
    if re.search(r"(\u8336|\u5496\u5561|\u7f8e\u5f0f|\u62ff\u94c1|\u51b7\u8403|\u996e\u6599|\u996e\u54c1|\u679c\u6c41|\u5976\u8336|\u53ef\u4e50|\u725b\u5976|\u4e4c\u9f99|\u8309\u8389)", text):
        return "\u996e\u98df.\u504f\u597d"
    if re.search(r"(\u5403|\u996d|\u83dc|\u706b\u9505|\u9762|\u7c73\u996d|\u5bff\u53f8|\u62c9\u9762)", text):
        return "\u996e\u98df.\u504f\u597d"
    if action == "goal":
        return "\u8ba1\u5212"
    return "\u504f\u597d"


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
    normalized_item = item.strip(" \uff0c,\u3002\uff01\uff1f!\uff1b;\u3001")
    if not normalized_item:
        return ""
    if action == "drink_preference":
        return f"\u7528\u6237\u559c\u6b22{normalized_item}\u3002"
    if action == "preference":
        return f"\u7528\u6237\u559c\u6b22{normalized_item}\u3002"
    if action == "goal":
        clause = original_clause.strip()
        if clause and not re.search(r"[\u3002\uff01\uff1f!?]$", clause):
            clause = f"{clause}\u3002"
        return clause
    return ""


def _extract_facts_heuristically(user_message: str) -> list[dict[str, object]]:
    text = str(user_message or "").strip()
    if not text:
        return []

    clauses = [segment.strip() for segment in re.split(r"[\u3002\uff01\uff1f!?\uff1b;\uff0c,]", text) if segment.strip()]
    results: list[dict[str, object]] = []
    seen: set[str] = set()

    speaker_prefix = r"(?:(?:\u6211|\u672c\u4eba)(?:\u4e5f|\u5f88|\u8fd8|\u90fd|\u6700|\u7279\u522b|\u771f\u7684|\u5e73\u65f6|\u4e00\u76f4|\u5e38\u5e38|\u7ecf\u5e38|\u901a\u5e38|\u6bd4\u8f83|\u66f4|\u631a|\u86ee|\u8fd8\u631a)*|(?:\u4e5f|\u5f88|\u8fd8|\u5e73\u65f6|\u4e00\u76f4|\u5e38\u5e38|\u7ecf\u5e38|\u901a\u5e38|\u6bd4\u8f83|\u66f4|\u631a|\u86ee|\u8fd8\u631a)+)"
    preference_patterns = [
        (rf"^{speaker_prefix}\u559c\u6b22\u559d(?P<item>.+)$", "drink_preference"),
        (rf"^{speaker_prefix}(?:\u7231\u559d|\u5e38\u559d)(?P<item>.+)$", "drink_preference"),
        (rf"^{speaker_prefix}\u559c\u6b22(?P<item>.+)$", "preference"),
        (rf"^{speaker_prefix}(?:\u7231\u5403|\u5e38\u5403)(?P<item>.+)$", "preference"),
    ]
    goal_patterns = [
        r"^(?:(?:\u6211|\u672c\u4eba)|(?:\u4eca\u5e74|\u660e\u5e74|\u6700\u8fd1|\u4e4b\u540e)).*(?:\u6253\u7b97|\u8ba1\u5212|\u51c6\u5907).+$",
    ]

    for clause in clauses:
        matched = False
        for pattern, action in preference_patterns:
            match = re.search(pattern, clause)
            if not match:
                continue
            item = match.group("item").strip()
            item = re.sub(r"^(?:\u4e5f|\u5f88|\u8fd8|\u90fd|\u6700|\u7279\u522b|\u771f\u7684|\u5e73\u65f6|\u4e00\u76f4|\u5e38\u5e38|\u7ecf\u5e38|\u901a\u5e38|\u6bd4\u8f83|\u66f4|\u631a|\u86ee|\u8fd8\u631a)+", "", item).strip()
            item = re.sub(r"(?:\u5462|\u554a|\u5440|\u5566|\u54e6|\u5427)$", "", item).strip()
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


# ---------------------------------------------------------------------------
# Main pipeline entry-point
# ---------------------------------------------------------------------------


async def run_pipeline(db: Session, inp: PipelineInput) -> PipelineResult:
    """Execute the full memory extraction/promotion pipeline for any source.

    This replicates the logic from ``_extract_and_store_facts()`` in
    ``worker_tasks.py`` (lines 2954-3840), generalised so it works for
    chat messages, notebook pages, uploaded documents, whiteboards, and
    book chapters.

    Parameters
    ----------
    db : Session
        Active SQLAlchemy database session.
    inp : PipelineInput
        Source-agnostic extraction input (text, refs, IDs).

    Returns
    -------
    PipelineResult
        Summary of what was extracted, created, merged, etc.
    """
    from app.services.embedding import (
        embed_and_store,
        find_duplicate_memory_with_vector,
        find_related_memories,
    )

    result = PipelineResult()

    # ------------------------------------------------------------------
    # 1. Load Project
    # ------------------------------------------------------------------
    project = db.get(Project, inp.project_id)
    if project is None:
        result.status = "failed"
        result.summary = "project_not_found"
        return result

    workspace_id = inp.workspace_id
    project_id = inp.project_id
    owner_user_id = inp.context.owner_user_id
    conversation_id = inp.context.conversation_id or ""
    source_conversation_id = inp.context.source_conversation_id

    # Truncate source text to configured max length
    user_message = (inp.source_text or "").strip()
    if inp.max_text_length and len(user_message) > inp.max_text_length:
        user_message = user_message[: inp.max_text_length]
    if not user_message:
        result.status = "empty"
        result.summary = "empty_source_text"
        return result

    # ------------------------------------------------------------------
    # 2. Create tracking records (episode, learning_run, write_run)
    # ------------------------------------------------------------------
    source_episode = create_memory_episode(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_id=inp.context.conversation_id,
        message_id=inp.context.message_id,
        source_type=inp.source_type,
        source_id=inp.source_ref,
        chunk_text=user_message,
        owner_user_id=owner_user_id,
        visibility="private" if owner_user_id else "public",
        started_at=datetime.now(timezone.utc),
        metadata_json={
            "source_type": inp.source_type,
            "source_ref": inp.source_ref,
        },
    )
    learning_run = create_memory_learning_run(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_id=inp.context.conversation_id,
        message_id=inp.context.message_id,
        trigger="pipeline",
        stages=["observe"],
        metadata_json={
            "episode_id": source_episode.id,
            "source_type": inp.source_type,
        },
    )
    write_run = create_memory_write_run(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_id=inp.context.conversation_id,
        message_id=inp.context.message_id,
        extraction_model=settings.memory_triage_model,
        consolidation_model=settings.dashscope_rerank_model,
        metadata_json={
            "user_message_preview": user_message[:500],
            "episode_id": source_episode.id,
            "learning_run_id": learning_run.id,
            "source_type": inp.source_type,
            "source_id": inp.source_ref,
            "source_ref": inp.source_ref,
        },
    )
    result.write_run_id = write_run.id
    result.learning_run_id = learning_run.id
    result.episode_id = source_episode.id
    db.flush()

    # ------------------------------------------------------------------
    # 3. Build extraction prompt based on source_type
    # ------------------------------------------------------------------
    if inp.source_type == "notebook_page":
        prompt = EXTRACTION_PROMPT_NOTEBOOK.format(
            user_message=user_message,
            context_text=inp.context_text or "",
        )
    else:
        prompt = EXTRACTION_PROMPT_CHAT.format(user_message=user_message)

    # ------------------------------------------------------------------
    # 4. LLM extraction (primary -> fallback -> heuristic)
    # ------------------------------------------------------------------
    async def _extract_facts_once(prompt_text: str) -> list[dict[str, object]]:
        raw_response = await dashscope_client.chat_completion(
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

    # ------------------------------------------------------------------
    # 5. Behavioral interest inference (chat only)
    # ------------------------------------------------------------------
    if inp.source_type == "chat_message":
        inferred_interest_fact, inferred_subject_changed = _infer_behavioral_interest_fact(
            db,
            project=project,
            context=inp.context,
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
                _normalize_text_key(str(item.get("fact") or "")) != inferred_key
                for item in (facts or [])
            ):
                facts = [*(facts or []), inferred_interest_fact]

    # ------------------------------------------------------------------
    # Early return when nothing was extracted
    # ------------------------------------------------------------------
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
        db.flush()
        result.status = "empty"
        result.summary = "no_extractable_facts"
        return result

    # ------------------------------------------------------------------
    # 6. Per-fact processing loop
    # ------------------------------------------------------------------
    processed_facts: list[dict[str, object]] = []
    graph_changed = False  # Track whether Memory/MemoryEdge was created/modified
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
        # ── 6a. Normalize, resolve subject, canonicalize ──
        fact_text = _normalize_extracted_fact_text(fact.get("fact", ""))
        category = str(fact.get("category", "")).strip()
        fact_source = str(fact.get("source") or "auto_extraction").strip() or "auto_extraction"
        initial_triage_reason = str(fact.get("triage_reason") or "").strip() or None
        if not fact_text:
            continue

        subject_memory, subject_changed, subject_resolution = _resolve_subject_memory_for_fact(
            db,
            project=project,
            context=inp.context,
            source_text=user_message,
            fact_text=fact_text,
            fact_category=category,
        )
        if subject_changed:
            db.flush()

        fact_text = _canonicalize_fact_text_for_storage(
            fact_text=fact_text,
            source_text=user_message,
            subject_memory=subject_memory,
            subject_resolution=subject_resolution,
        )
        if not fact_text:
            continue

        # ── 6b. Compute importance + memory_kind ──
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

        # Map string importance ("high"/"medium"/"low") to float, then
        # apply the stable-pattern boost via _normalize_explicit_fact_importance.
        raw_importance = fact.get("importance", 0)
        if isinstance(raw_importance, str):
            raw_importance = _IMPORTANCE_MAP.get(raw_importance.strip().lower(), 0.0)
        importance = _normalize_explicit_fact_importance(
            raw_importance,
            fact_text=fact_text,
            memory_kind=memory_kind,
        )

        # S4: confusion evidence must survive triage — the downstream
        # proactive-services subsystem depends on it staying visible.
        if inp.source_type == "study_confusion":
            importance = max(importance, 0.5)

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

        # ── 6c. Create write_item ──
        write_item = create_memory_write_item(
            db,
            run_id=write_run.id,
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
        )

        # ── 6d. Importance threshold ──
        if importance < 0.7:
            update_memory_write_item(
                write_item,
                decision="discard",
                reason="importance_below_threshold",
            )
            fact_display["status"] = "ignored"
            processed_facts.append(fact_display)
            continue

        # Determine memory_type: permanent vs temporary
        durable_memory_kind = memory_kind in {
            MEMORY_KIND_PROFILE,
            MEMORY_KIND_PREFERENCE,
            MEMORY_KIND_GOAL,
        }
        memory_type = (
            "permanent"
            if owner_user_id and (importance >= 0.9 or durable_memory_kind)
            else "temporary"
        )
        triage_reason = initial_triage_reason

        # Aggregate fact filter
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

        # ── 6e. Dedup check ──
        query_vector: list[float] | None = None
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
                # Promote temporary duplicate to permanent when applicable
                if (
                    duplicate_memory is not None
                    and duplicate_memory.type == "temporary"
                    and memory_type == "permanent"
                    and owner_user_id
                ):
                    _promote_temporary_duplicate_to_permanent(
                        duplicate_memory,
                        fact_text=fact_text,
                        fact_category=category,
                        importance=importance,
                        fact_source=fact_source,
                        owner_user_id=owner_user_id,
                        subject_memory=subject_memory,
                    )
                    duplicate_memory.last_confirmed_at = datetime.now(timezone.utc)
                    graph_changed = True
                    evidence_ids = _record_source_evidence(
                        db,
                        memory=duplicate_memory,
                        source_type=inp.source_type,
                        source_ref=inp.source_ref,
                        conversation_id=inp.context.conversation_id,
                        message_id=inp.context.message_id,
                        quote_text=user_message,
                        confidence=importance,
                        source=fact_source,
                        episode_id=source_episode.id,
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

                # Duplicate exists, just bump confidence and record evidence
                if duplicate_memory is not None:
                    duplicate_memory.confidence = max(
                        float(duplicate_memory.confidence or 0.0),
                        float(importance or 0.0),
                    )
                    duplicate_memory.last_confirmed_at = datetime.now(timezone.utc)
                    apply_temporal_defaults(duplicate_memory)
                    graph_changed = True
                    evidence_ids = _record_source_evidence(
                        db,
                        memory=duplicate_memory,
                        source_type=inp.source_type,
                        source_ref=inp.source_ref,
                        conversation_id=inp.context.conversation_id,
                        message_id=inp.context.message_id,
                        quote_text=user_message,
                        confidence=importance,
                        source=fact_source,
                        episode_id=source_episode.id,
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

        # ── 6f. Triage: check for related (but not duplicate) memories ──
        parent_memory_id: str | None = None
        parent_memory: Memory | None = None
        anchor_strength = 0.0
        append_candidate_memory: Memory | None = None
        triage_action = "create"
        triage_reason = initial_triage_reason
        triage_target_memory_id: str | None = None

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

                # ── 6g. Handle triage decisions ──

                # --- discard ---
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

                # --- append ---
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
                            evidence_ids = _record_source_evidence(
                                db,
                                memory=target,
                                source_type=inp.source_type,
                                source_ref=inp.source_ref,
                                conversation_id=inp.context.conversation_id,
                                message_id=inp.context.message_id,
                                quote_text=user_message,
                                confidence=importance,
                                source=fact_source,
                                episode_id=source_episode.id,
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

                # --- merge / replace ---
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
                        graph_changed = True
                        evidence_ids = _record_source_evidence(
                            db,
                            memory=successor,
                            source_type=inp.source_type,
                            source_ref=inp.source_ref,
                            conversation_id=inp.context.conversation_id,
                            message_id=inp.context.message_id,
                            quote_text=user_message,
                            confidence=importance,
                            source=fact_source,
                            episode_id=source_episode.id,
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
                        continue
                    triage_action = "create"
                    triage_target_memory_id = None

                # --- conflict ---
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
                        graph_changed = True
                        evidence_ids = _record_source_evidence(
                            db,
                            memory=conflict_memory,
                            source_type=inp.source_type,
                            source_ref=inp.source_ref,
                            conversation_id=inp.context.conversation_id,
                            message_id=inp.context.message_id,
                            quote_text=user_message,
                            confidence=importance,
                            source=fact_source,
                            episode_id=source_episode.id,
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

        # ── 6h. Subject alignment from parent ──
        if parent_memory and not is_assistant_root_memory(parent_memory):
            parent_subject_id = (
                parent_memory.id if is_subject_memory(parent_memory) else get_subject_memory_id(parent_memory)
            )
            parent_subject = _load_subject_memory(
                db,
                workspace_id=workspace_id,
                project_id=project_id,
                owner_user_id=owner_user_id,
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

        # Build metadata for the new memory
        metadata: dict[str, object] = {
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
            metadata = build_private_memory_metadata(metadata, owner_user_id=owner_user_id)
        metadata = normalize_memory_metadata(
            content=fact_text,
            category=fact.get("category", ""),
            memory_type=memory_type,
            metadata=metadata,
        )
        memory_kind = str(metadata.get("memory_kind") or "").strip().lower()

        # ── 6h (cont). Concept parent resolution ──
        concept_parent_created = False
        if parent_memory_id is None and memory_type == "permanent":
            concept_parent, concept_created, concept_reason = await _resolve_concept_parent(
                db,
                workspace_id=workspace_id,
                project_id=project_id,
                conversation_id=inp.context.conversation_id or "",
                owner_user_id=owner_user_id,
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

        # Default parent to subject when nothing else was found
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

        # ── 6i. Create Memory entity ──
        memory = Memory(
            workspace_id=workspace_id,
            project_id=project_id,
            content=fact_text,
            category=fact.get("category", ""),
            type=memory_type,
            node_type=FACT_NODE_TYPE,
            subject_kind=None,
            source_conversation_id=source_conversation_id if memory_type == "temporary" else None,
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
        graph_changed = True

        # ── 6j. Embed ──
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

        # ── 6k. Create edge ──
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

        # ── 6l. Record evidence ──
        evidence_ids = _record_source_evidence(
            db,
            memory=memory,
            source_type=inp.source_type,
            source_ref=inp.source_ref,
            conversation_id=inp.context.conversation_id,
            message_id=inp.context.message_id,
            quote_text=user_message,
            confidence=importance,
            source=fact_source,
            episode_id=source_episode.id,
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

        # ── 6m. Collect view refresh ──
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

    # ------------------------------------------------------------------
    # 7. Refresh subject views
    # ------------------------------------------------------------------
    for payload in subject_view_inputs.values():
        sv_memory = payload.get("subject_memory")
        if not isinstance(sv_memory, Memory):
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
                subject_memory=sv_memory,
                playbook_source_text=playbook_text or None,
                playbook_source_memory_ids=source_memory_ids,
            )
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # 8. Finalize write_run and learning_run
    # ------------------------------------------------------------------
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
            "write_run_id": write_run.id,
            "episode_id": source_episode.id,
            "item_count": len(processed_facts),
        },
    )
    db.flush()

    # ------------------------------------------------------------------
    # 8b. Related/prerequisite edges
    # ------------------------------------------------------------------
    try:
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
    except Exception:  # noqa: BLE001
        logger.debug("Edge maintenance failed, non-fatal")

    # ------------------------------------------------------------------
    # 9. Return PipelineResult
    # ------------------------------------------------------------------
    result.processed_facts = processed_facts
    result.item_count = len(processed_facts)
    result.status = "completed"
    result.summary = _build_memory_extraction_summary(processed_facts)
    # Signal to caller that graph changed (caller should bump AFTER db.commit)
    result.graph_changed = graph_changed
    return result


# ---------------------------------------------------------------------------
# promote_write_item — used by memory/confirm endpoint
# ---------------------------------------------------------------------------


async def promote_write_item(
    db: Session,
    *,
    item: MemoryWriteItem,
    workspace_id: str,
    project_id: str,
    user_id: str,
) -> Memory | None:
    """Promote a pending MemoryWriteItem into a real Memory node.

    This runs dedup, creates the Memory entity, embeds it, records evidence,
    and updates the item's decision and target_memory_id.  Called when a user
    confirms a candidate from the notebook memory UI.
    """
    from app.services.embedding import embed_and_store, find_duplicate_memory_with_vector

    candidate_text = str(item.candidate_text or "").strip()
    if not candidate_text:
        return None

    category = str(item.category or "").strip()
    importance = float(item.importance or 0.5)
    run = db.get(MemoryWriteRun, item.run_id) if item.run_id else None
    run_meta = run.metadata_json if run and isinstance(run.metadata_json, dict) else {}
    source_ref = str(run_meta.get("source_id") or run_meta.get("source_ref") or "")
    source_type = str(run_meta.get("source_type") or "notebook_page")

    def _record_confirm_evidence(memory: Memory) -> None:
        _record_source_evidence(
            db,
            memory=memory,
            source_type=source_type,
            source_ref=source_ref,
            conversation_id=run.conversation_id if run is not None else None,
            message_id=run.message_id if run is not None else None,
            quote_text=candidate_text[:500],
            confidence=importance,
            source="user_confirmed",
        )

    # --- Resolve subject (prefer extracted subject, fallback to user) -----
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.workspace_id == workspace_id,
    ).first()
    if not project:
        return None

    subject_memory = None
    if item.subject_memory_id:
        candidate_subject = db.get(Memory, item.subject_memory_id)
        if (
            candidate_subject is not None
            and candidate_subject.workspace_id == workspace_id
            and candidate_subject.project_id == project_id
            and candidate_subject.node_status == ACTIVE_NODE_STATUS
        ):
            subject_memory = candidate_subject
    if subject_memory is None:
        subject_memory, _ = ensure_project_user_subject(db, project, owner_user_id=user_id)
        db.flush()

    if item.target_memory_id:
        existing_target = db.get(Memory, item.target_memory_id)
        if (
            existing_target is not None
            and existing_target.workspace_id == workspace_id
            and existing_target.project_id == project_id
            and existing_target.node_status == ACTIVE_NODE_STATUS
        ):
            existing_target.confidence = max(float(existing_target.confidence or 0), importance)
            existing_target.last_confirmed_at = datetime.now(timezone.utc)
            apply_temporal_defaults(existing_target)
            item.decision = "confirmed"
            item.target_memory_id = existing_target.id
            db.flush()
            return existing_target

    # --- Dedup check ------------------------------------------------------
    query_vector: list[float] | None = None
    try:
        dup_match, dup_vector = await find_duplicate_memory_with_vector(
            db,
            workspace_id=workspace_id,
            project_id=project_id,
            text=candidate_text,
            threshold=settings.memory_triage_similarity_high,
        )
        query_vector = dup_vector
        if dup_match:
            dup_memory_id = dup_match.get("memory_id")
            dup_score = float(dup_match.get("score") or 0)
            if dup_memory_id and dup_score >= settings.memory_triage_similarity_high:
                existing = db.get(Memory, dup_memory_id)
                if existing and existing.node_status == ACTIVE_NODE_STATUS:
                    # Already exists — bump confidence, mark confirmed
                    existing.confidence = max(float(existing.confidence or 0), importance)
                    existing.last_confirmed_at = datetime.now(timezone.utc)
                    apply_temporal_defaults(existing)
                    _record_confirm_evidence(existing)
                    item.decision = "confirmed"
                    item.target_memory_id = existing.id
                    db.flush()
                    return existing
    except Exception:  # noqa: BLE001
        logger.debug("Dedup check failed during promote, proceeding with creation")

    # --- Build metadata ---------------------------------------------------
    metadata: dict[str, object] = {
        "source": "user_confirmed",
        "node_type": FACT_NODE_TYPE,
        "node_status": ACTIVE_NODE_STATUS,
        "subject_memory_id": subject_memory.id,
        "importance": importance,
    }
    metadata = build_private_memory_metadata(metadata, owner_user_id=user_id)
    metadata = normalize_memory_metadata(
        content=candidate_text,
        category=category,
        memory_type="permanent",
        metadata=metadata,
    )

    # --- Create Memory entity ---------------------------------------------
    memory = Memory(
        workspace_id=workspace_id,
        project_id=project_id,
        content=candidate_text,
        category=category,
        type="permanent",
        node_type=FACT_NODE_TYPE,
        node_status=ACTIVE_NODE_STATUS,
        confidence=importance,
        source_conversation_id=None,
        parent_memory_id=subject_memory.id,
        subject_memory_id=subject_memory.id,
        canonical_key=str(metadata.get("canonical_key") or "").strip() or None,
        metadata_json=metadata,
    )
    db.add(memory)
    db.flush()
    ensure_fact_lineage(memory)
    apply_temporal_defaults(memory)

    # --- Embed ------------------------------------------------------------
    try:
        await embed_and_store(
            db,
            workspace_id=workspace_id,
            project_id=project_id,
            memory_id=memory.id,
            chunk_text=candidate_text,
            vector=query_vector,
            auto_commit=False,
        )
    except Exception:  # noqa: BLE001
        logger.debug("Embedding failed during promote for memory %s", memory.id)

    # --- Edge -------------------------------------------------------------
    _upsert_auto_memory_edge(
        db,
        source_memory_id=subject_memory.id,
        target_memory_id=memory.id,
        strength=0.65,
    )

    # --- Evidence ---------------------------------------------------------
    _record_confirm_evidence(memory)

    # --- Update item ------------------------------------------------------
    item.decision = "confirmed"
    item.target_memory_id = memory.id
    db.flush()

    return memory
