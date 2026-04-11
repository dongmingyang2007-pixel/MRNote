from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import re
from typing import Any, AsyncIterator, Literal

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.entities import Conversation, Memory, ModelCatalog, PipelineConfig, Project
from app.services.assistant_markdown import normalize_assistant_markdown
from app.services.ai_gateway_tool_selection import (
    ToolSelectionCandidate,
    select_tools_with_ai_gateway_prefilter,
)
from app.services.context_loader import (
    extract_personality,
    filter_knowledge_chunks,
    load_conversation_context,
    load_permanent_memories,
    load_recent_messages,
)
from app.services.dashscope_client import (
    ChatCompletionResult,
    SearchSource,
    ToolCall,
    chat_completion_detailed,
    chat_completion_multimodal_detailed,
    merge_search_sources,
    omni_completion,
    serialize_search_sources,
)
from app.services.dashscope_responses import (
    ResponsesStreamChunk,
    responses_completion_detailed,
    responses_completion_stream,
)
from app.services.dashscope_stream import chat_completion_stream
from app.services.embedding import search_similar
from app.services.llm_tools import (
    execute_function_tool_call,
    get_function_tools,
    get_response_function_tools,
)
from app.services.memory_context import build_memory_context
from app.services.memory_file_context import load_linked_file_chunks_for_memories
from app.services.memory_visibility import get_memory_owner_user_id, is_private_memory
from app.services.pipeline_models import resolve_pipeline_model_id
from app.services.qwen_capabilities import (
    model_supports_deep_thinking,
    model_supports_image_input,
    model_supports_native_responses_tool,
    model_supports_native_web_search,
    model_supports_responses_api,
    model_supported_native_responses_tools,
)
from app.services.qwen_official_catalog import find_model
from app.services.responses_native_tools import (
    build_native_tool_definition,
    native_tool_requires_config,
    native_tool_requires_thinking,
    normalize_native_tool_name,
)
from app.services.voice_response_limits import (
    apply_voice_response_guidance,
    clamp_voice_response_text,
)

logger = logging.getLogger(__name__)

_OPENAI_COMPATIBLE_ASR_PREFIXES = ("qwen3-asr-",)
_OPENAI_COMPATIBLE_TTS_PREFIXES = ("qwen3-tts-",)
_WEB_SEARCH_HINTS = (
    "最新",
    "最近",
    "今天",
    "今日",
    "刚刚",
    "实时",
    "新闻",
    "天气",
    "股价",
    "汇率",
    "比分",
    "热搜",
    "time now",
    "today",
    "latest",
    "recent",
    "current",
    "news",
    "weather",
    "price",
    "stock",
    "exchange rate",
    "score",
)
_PROJECT_CONTEXT_HINTS = (
    "知识库",
    "资料里",
    "文档里",
    "上传的资料",
    "上传的文档",
    "根据文档",
    "根据资料",
    "我之前说过",
    "你记得",
    "之前那次对话",
    "knowledge base",
    "uploaded document",
    "uploaded file",
    "project context",
    "previous conversation",
    "remember what i said",
)
_LOCAL_ONLY_HINTS = (
    "现在几点",
    "几点了",
    "今天几号",
    "当前时间",
    "time now",
    "what time is it",
    "what's the time",
    "what is the date",
    "what's the date",
    "current time",
)
_THINKING_SOCIAL_MESSAGES = {
    "hi",
    "hello",
    "hey",
    "yo",
    "ok",
    "okay",
    "thanks",
    "thankyou",
    "test",
    "你好",
    "您好",
    "嗨",
    "哈喽",
    "早上好",
    "中午好",
    "下午好",
    "晚上好",
    "在吗",
    "谢谢",
    "收到",
    "好的",
    "测试",
}
_THINKING_SOCIAL_HINTS = ("你好", "您好", "嗨", "哈喽", "在吗", "谢谢", "收到", "好的")
_THINKING_HINTS = (
    "分析",
    "解释",
    "原因",
    "为什么",
    "如何",
    "怎么",
    "步骤",
    "方案",
    "计划",
    "设计",
    "比较",
    "对比",
    "优缺点",
    "排查",
    "调试",
    "修复",
    "推导",
    "总结",
    "归纳",
    "复盘",
    "评估",
    "评审",
    "取舍",
    "权衡",
    "架构",
    "优化",
    "reason",
    "analy",
    "debug",
    "compare",
    "tradeoff",
    "plan",
    "strategy",
    "explain",
)
_CONTEXT_ROUTE_HINTS_MEMORY = (
    "你记得我",
    "你还记得",
    "你记不记得",
    "我上次说过",
    "我之前说过",
    "我前面说过",
    "我刚才说过",
    "之前提到",
    "前面提到",
    "刚才提到",
    "earlier conversation",
    "previous conversation",
    "remember what i said",
    "what did i say",
    "what do you remember about me",
    "did i mention before",
)
_CONTEXT_ROUTE_HINTS_RAG = (
    "知识库",
    "资料里",
    "文档里",
    "文件里",
    "上传的资料",
    "上传的文档",
    "上传的文件",
    "根据文档",
    "根据资料",
    "结合文档",
    "结合资料",
    "结合我上传",
    "根据我上传",
    "project knowledge",
    "knowledge base",
    "uploaded document",
    "uploaded file",
    "uploaded files",
    "uploaded materials",
    "based on the document",
    "based on the file",
)
_CONTEXT_ROUTE_HINTS_NONE = (
    "介绍一下你自己",
    "介绍你自己",
    "自我介绍",
    "你是谁",
    "who are you",
    "introduce yourself",
    "tell me about yourself",
    "夸夸你",
    "你很棒",
    "你真棒",
    "你很不错",
    "辛苦了",
)
_CONTEXT_ROUTE_HINTS_PERSONAL = (
    "结合我",
    "根据我",
    "基于我",
    "按我的",
    "围绕我",
    "about me",
    "based on me",
    "using my",
    "my earlier",
    "my previous",
)
_CONTEXT_ROUTE_VALUES = {"none", "profile_only", "memory_only", "full_rag"}
_MARKDOWN_FORMAT_INSTRUCTION = (
    "【Markdown格式】回复中每个换行符都很重要，请确保：标题独占一行、每个列表项独占一行、"
    "代码块中每条语句独占一行、表格每行独占一行且不要在表格行内写标题。"
)
_GRAPH_TOOL_INSTRUCTION = (
    "如果需要调用项目图谱工具，默认顺序是：先 resolve_active_subjects，"
    "再 get_subject_overview 或 expand_subject_subgraph，随后按需调用 "
    "search_subject_documents、search_subject_facts、get_concept_neighbors、get_explanation_path。"
    "只有在主体图谱不足时，才回退到 search_project_memories 或 search_project_knowledge。"
)
_WEB_EXTRACTOR_HINTS = (
    "网页",
    "网址",
    "链接",
    "页面",
    "官网",
    "文章",
    "博客",
    "提取正文",
    "抓取网页",
    "读取网页",
    "网页摘要",
    "extract webpage",
    "read this page",
    "summarize this page",
    "web extractor",
)
_WEB_IMAGE_SEARCH_HINTS = (
    "找图",
    "搜图",
    "配图",
    "背景图",
    "封面图",
    "插图",
    "配一张图",
    "图片参考",
    "参考图",
    "视觉参考",
    "文搜图",
    "search image",
    "search images",
    "find image",
    "find images",
    "background image",
    "cover image",
    "illustration",
    "reference image",
    "web_search_image",
    "t2i_search",
)
_IMAGE_SEARCH_HINTS = (
    "以图搜图",
    "相似图",
    "类似图片",
    "找来源",
    "找出处",
    "图片来源",
    "图源",
    "同款",
    "similar image",
    "reverse image",
    "image source",
    "find similar",
    "image_search",
    "i2i_search",
)
_CODE_INTERPRETER_HINTS = (
    "代码解释器",
    "运行代码",
    "python",
    "脚本",
    "dataframe",
    "csv",
    "excel",
    "表格",
    "图表",
    "绘图",
    "可视化",
    "统计",
    "回归",
    "拟合",
    "simulation",
    "simulate",
    "plot",
    "chart",
    "compute",
    "calculation",
    "code interpreter",
)


def _normalize_assistant_fields(
    content: str | None,
    reasoning_content: str | None,
) -> tuple[str, str | None]:
    normalized_content = normalize_assistant_markdown(content)
    normalized_reasoning = (
        normalize_assistant_markdown(reasoning_content)
        if reasoning_content and reasoning_content.strip()
        else None
    )
    return normalized_content, normalized_reasoning
_URL_PATTERN = re.compile(r"https?://[^\s]+", re.IGNORECASE)
_FUNCTION_TOOL_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "get_subject_overview": ("resolve_active_subjects",),
    "expand_subject_subgraph": ("resolve_active_subjects",),
    "search_subject_documents": ("resolve_active_subjects",),
    "search_subject_facts": ("resolve_active_subjects",),
    "get_concept_neighbors": ("resolve_active_subjects",),
    "get_explanation_path": ("resolve_active_subjects",),
}
_NATIVE_TOOL_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "web_extractor": ("web_search",),
}
_NATIVE_TOOL_ORDER = (
    "web_search",
    "web_extractor",
    "web_search_image",
    "image_search",
    "code_interpreter",
    "file_search",
    "mcp",
)
_NATIVE_TOOL_SELECTION_DESCRIPTIONS: dict[str, str] = {
    "web_search": (
        "Search the public web for current information, recent events, webpages, live facts, and citations."
    ),
    "web_extractor": (
        "Open and extract the main content from a webpage or URL for summarization and reading. "
        "Best for explicit links or requests to read a page."
    ),
    "web_search_image": (
        "Search the web for images from a text description, concept keywords, background-image need, "
        "cover image need, or illustration request."
    ),
    "image_search": (
        "Use an uploaded image for reverse-image search, similar-image discovery, or source lookup."
    ),
    "code_interpreter": (
        "Run Python for calculations, tables, CSV or spreadsheet analysis, charts, plots, simulations, "
        "and file-backed computation."
    ),
    "file_search": (
        "Search configured vector stores and indexed files when the answer should come from attached or project files."
    ),
    "mcp": (
        "Call configured MCP server tools for external system actions or retrieval beyond the built-in tools."
    ),
}

ContextRoute = Literal["none", "profile_only", "memory_only", "full_rag"]

WebSearchRoute = Literal["local_only", "web_only", "local_then_web", "no_search"]


@dataclass(slots=True)
class WebSearchDecision:
    enable_search: bool
    search_options: dict[str, bool] | None
    route: WebSearchRoute
    source: str
    confidence: float | None = None
    reason: str | None = None


@dataclass(slots=True)
class ThinkingDecision:
    enable_thinking: bool
    source: str
    confidence: float | None = None
    reason: str | None = None


@dataclass(slots=True)
class ThinkingClassification:
    enable_thinking: bool
    confidence: float
    reason: str | None = None


@dataclass(slots=True)
class ContextRouteDecision:
    route: ContextRoute
    source: str
    confidence: float | None = None
    reason: str | None = None


@dataclass(slots=True)
class ContextRouteClassification:
    route: ContextRoute
    confidence: float
    reason: str | None = None


# ---------------------------------------------------------------------------
# Shared helper: build system prompt + call LLM
# ---------------------------------------------------------------------------


def _load_active_conversation_context(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    conversation_id: str,
) -> tuple[Project, Conversation]:
    return load_conversation_context(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_id=conversation_id,
    )


def _filter_knowledge_chunks_for_prompt(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    results: list[dict],
) -> list[dict]:
    # Filter out memory-sourced results first (handled separately),
    # then delegate dataset visibility check to shared context_loader.
    non_memory_results = [r for r in results if r.get("memory_id") is None]
    return filter_knowledge_chunks(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        results=non_memory_results,
    )


def _load_visible_permanent_memories(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    conversation_created_by: str | None,
) -> list[Memory]:
    return load_permanent_memories(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_created_by=conversation_created_by,
    )


def _filter_relevant_memory_ids_for_prompt(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    conversation_id: str,
    conversation_created_by: str | None,
    results: list[dict],
) -> list[str]:
    memory_ids = [result["memory_id"] for result in results if result.get("memory_id")]
    if not memory_ids:
        return []

    memories = (
        db.query(Memory)
        .filter(
            Memory.id.in_(memory_ids),
            Memory.workspace_id == workspace_id,
            Memory.project_id == project_id,
        )
        .all()
    )

    visible_memory_ids: list[str] = []
    for memory in memories:
        if memory.type == "temporary":
            if memory.source_conversation_id != conversation_id:
                continue
            visible_memory_ids.append(memory.id)
            continue
        if not is_private_memory(memory) or get_memory_owner_user_id(memory) == conversation_created_by:
            visible_memory_ids.append(memory.id)
    return visible_memory_ids


def _memory_matches_query(memory: Memory, query: str) -> bool:
    normalized_query = query.strip().lower()
    normalized_memory = memory.content.strip().lower()
    if not normalized_query or not normalized_memory:
        return False
    if normalized_memory in normalized_query:
        return True

    tokens = re.findall(r"[\w\u4e00-\u9fff]{2,}", normalized_memory)
    return any(token in normalized_query for token in tokens[:6])


def _load_model_capabilities(
    db: Session,
    *,
    model_id: str,
) -> set[str]:
    model_info = db.query(ModelCatalog).filter(ModelCatalog.model_id == model_id).first()
    capabilities = {
        str(value).lower()
        for value in (model_info.capabilities or [])
    } if model_info else set()
    official = find_model(model_id)
    if official:
        capabilities.update(str(value).lower() for value in official.get("input_modalities", []))
        capabilities.update(str(value).lower() for value in official.get("output_modalities", []))
        capabilities.update(str(value).lower() for value in official.get("supported_tools", []))
        capabilities.update(str(value).lower() for value in official.get("supported_features", []))
        if official.get("official_category_key") == "deep_thinking":
            capabilities.update({"thinking", "deep_thinking"})
    if model_supports_deep_thinking(model_id):
        capabilities.update({"thinking", "deep_thinking"})
    if model_supports_image_input(model_id):
        capabilities.update({"vision", "image"})
    if model_supports_responses_api(model_id):
        capabilities.add("responses_api")
    if model_supports_native_web_search(model_id):
        capabilities.add("native_web_search")
    capabilities.update(model_supported_native_responses_tools(model_id))
    return capabilities


def _load_llm_config_json(
    db: Session,
    *,
    project_id: str,
) -> dict[str, object]:
    if db is None or not hasattr(db, "query"):
        return {}
    config = (
        db.query(PipelineConfig)
        .filter(
            PipelineConfig.project_id == project_id,
            PipelineConfig.model_type == "llm",
        )
        .first()
    )
    if config is None or not isinstance(config.config_json, dict):
        return {}
    return dict(config.config_json)


def _has_url_signal(text: str) -> bool:
    return bool(_URL_PATTERN.search(text))


def _should_offer_web_extractor(user_message: str) -> bool:
    lowered = user_message.casefold()
    return _has_url_signal(lowered) or any(hint in lowered for hint in _WEB_EXTRACTOR_HINTS)


def _should_offer_web_search_image(user_message: str) -> bool:
    lowered = user_message.casefold()
    return any(hint in lowered for hint in _WEB_IMAGE_SEARCH_HINTS)


def _should_offer_image_search(
    *,
    user_message: str,
    image_bytes: bytes | None,
) -> bool:
    if not image_bytes:
        return False
    lowered = user_message.casefold()
    return any(hint in lowered for hint in _IMAGE_SEARCH_HINTS)


def _should_offer_code_interpreter(user_message: str) -> bool:
    lowered = user_message.casefold()
    if any(hint in lowered for hint in _CODE_INTERPRETER_HINTS):
        return True
    math_like = re.search(r"\b\d+\s*[\+\-\*/]\s*\d+\b", lowered)
    return bool(math_like)


def _normalize_native_tool_config_entries(
    *,
    config_json: dict[str, object],
    tool_name: str,
) -> list[dict[str, object]]:
    normalized_tool = normalize_native_tool_name(tool_name)
    roots: list[object] = []
    for key in ("responses_native_tools", "native_tools", "responses_tools"):
        value = config_json.get(key)
        if isinstance(value, dict):
            roots.append(value)

    collected: list[dict[str, object]] = []
    candidate_keys = {
        normalized_tool,
        tool_name,
    }
    if normalized_tool == "web_search_image":
        candidate_keys.add("t2i_search")
    if normalized_tool == "image_search":
        candidate_keys.add("i2i_search")

    for root in roots:
        if not isinstance(root, dict):
            continue
        raw_entry = None
        for candidate_key in candidate_keys:
            if candidate_key in root:
                raw_entry = root.get(candidate_key)
                break
        if raw_entry is None:
            continue
        if isinstance(raw_entry, dict):
            collected.append({str(key): value for key, value in raw_entry.items()})
            continue
        if isinstance(raw_entry, list):
            for item in raw_entry:
                if isinstance(item, dict):
                    collected.append({str(key): value for key, value in item.items()})
    return collected


def _configured_native_tool_definitions(
    *,
    tool_name: str,
    llm_config_json: dict[str, object],
) -> list[dict[str, object]]:
    definitions: list[dict[str, object]] = []
    for config_entry in _normalize_native_tool_config_entries(
        config_json=llm_config_json,
        tool_name=tool_name,
    ):
        normalized_tool = normalize_native_tool_name(tool_name)
        if normalized_tool == "file_search":
            vector_store_ids = config_entry.get("vector_store_ids")
            if not isinstance(vector_store_ids, list) or not any(isinstance(value, str) for value in vector_store_ids):
                continue
        if normalized_tool == "mcp":
            server_label = config_entry.get("server_label")
            server_url = config_entry.get("server_url")
            if not isinstance(server_label, str) or not server_label.strip():
                continue
            if not isinstance(server_url, str) or not server_url.strip():
                continue
        definitions.append(build_native_tool_definition(normalized_tool, config_entry))
    return definitions


async def _resolve_search_options(
    db: Session,
    *,
    llm_model_id: str,
    llm_capabilities: set[str],
    user_message: str,
    recent_messages: list[dict[str, str]],
    preference: bool | None,
) -> WebSearchDecision:
    if "web_search" not in llm_capabilities:
        return WebSearchDecision(
            enable_search=False,
            search_options=None,
            route="no_search",
            source="unsupported",
            reason="llm model does not support web_search",
        )
    if preference is True:
        return WebSearchDecision(
            enable_search=True,
            search_options={"forced_search": True},
            route="web_only",
            source="user_preference",
            confidence=1.0,
            reason="user explicitly enabled web search",
        )
    if preference is False:
        return WebSearchDecision(
            enable_search=False,
            search_options=None,
            route="no_search",
            source="user_preference",
            confidence=1.0,
            reason="user explicitly disabled web search",
        )

    rule_decision = _resolve_rule_search_decision(user_message=user_message)
    if rule_decision is not None:
        return rule_decision

    del db, llm_model_id, recent_messages

    return WebSearchDecision(
        enable_search=False,
        search_options=None,
        route="no_search",
        source="fallback",
        reason="no explicit web-search rule matched, so stay offline by default",
    )


def _resolve_rule_thinking_decision(
    *,
    user_message: str,
) -> ThinkingDecision | None:
    stripped = user_message.strip()
    if not stripped:
        return ThinkingDecision(
            enable_thinking=False,
            source="rules",
            confidence=1.0,
            reason="empty user message does not require deep thinking",
        )

    lowered = stripped.casefold()
    normalized = re.sub(r"[\W_]+", "", lowered)
    if normalized in _THINKING_SOCIAL_MESSAGES:
        return ThinkingDecision(
            enable_thinking=False,
            source="rules",
            confidence=1.0,
            reason="social or acknowledgement message does not require deep thinking",
        )
    if len(stripped) <= 12 and any(hint in stripped for hint in _THINKING_SOCIAL_HINTS):
        return ThinkingDecision(
            enable_thinking=False,
            source="rules",
            confidence=0.98,
            reason="brief greeting does not require deep thinking",
        )
    if len(stripped) <= 24 and not any(hint in lowered for hint in _THINKING_HINTS):
        return ThinkingDecision(
            enable_thinking=False,
            source="rules",
            confidence=0.9,
            reason="short straightforward message does not require deep thinking",
        )
    if any(hint in lowered for hint in _THINKING_HINTS):
        return ThinkingDecision(
            enable_thinking=True,
            source="rules",
            confidence=0.92,
            reason="message contains explicit analysis or reasoning cues",
        )
    if "\n" in stripped or len(stripped) >= 80:
        return ThinkingDecision(
            enable_thinking=True,
            source="rules",
            confidence=0.88,
            reason="long or structured input benefits from deeper reasoning",
        )
    return None


def _resolve_rule_search_decision(
    *,
    user_message: str,
) -> WebSearchDecision | None:
    normalized = user_message.strip().lower()
    if not normalized:
        return None

    if any(hint in normalized for hint in _LOCAL_ONLY_HINTS):
        return WebSearchDecision(
            enable_search=False,
            search_options=None,
            route="local_only",
            source="rules",
            confidence=1.0,
            reason="question is answerable from local runtime information",
        )

    has_project_context_hint = any(hint in normalized for hint in _PROJECT_CONTEXT_HINTS)
    has_freshness_hint = any(hint in normalized for hint in _WEB_SEARCH_HINTS)

    if has_project_context_hint and has_freshness_hint:
        return WebSearchDecision(
            enable_search=True,
            search_options=None,
            route="local_then_web",
            source="rules",
            confidence=0.9,
            reason="question references both project context and fresh external facts",
        )
    if has_project_context_hint:
        return WebSearchDecision(
            enable_search=False,
            search_options=None,
            route="local_only",
            source="rules",
            confidence=0.9,
            reason="question references uploaded knowledge, memories, or earlier conversation",
        )
    if has_freshness_hint:
        return WebSearchDecision(
            enable_search=True,
            search_options=None,
            route="web_only",
            source="rules",
            confidence=0.85,
            reason="question contains freshness or live-data hints",
        )
    return None


def _resolve_rule_context_route(
    *,
    user_message: str,
) -> ContextRouteDecision | None:
    stripped = user_message.strip()
    if not stripped:
        return ContextRouteDecision(
            route="none",
            source="rules",
            confidence=1.0,
            reason="empty user message does not require project context",
        )

    lowered = stripped.casefold()
    normalized = re.sub(r"[\W_]+", "", lowered)
    if normalized in _THINKING_SOCIAL_MESSAGES:
        return ContextRouteDecision(
            route="none",
            source="rules",
            confidence=1.0,
            reason="social or acknowledgement turn does not require project context",
        )
    if any(hint in lowered for hint in _CONTEXT_ROUTE_HINTS_NONE):
        return ContextRouteDecision(
            route="none",
            source="rules",
            confidence=0.98,
            reason="self-intro, praise, or chit-chat turn does not require project retrieval",
        )
    if _has_rag_context_signal(lowered):
        return ContextRouteDecision(
            route="full_rag",
            source="rules",
            confidence=0.95,
            reason="user explicitly asked for uploaded files, docs, or project knowledge",
        )
    if _has_memory_context_signal(lowered):
        return ContextRouteDecision(
            route="memory_only",
            source="rules",
            confidence=0.93,
            reason="user explicitly asked about prior facts or remembered conversation state",
        )
    return None


def _pick_thinking_classifier_model(
    db: Session,
    *,
    llm_model_id: str,
) -> str:
    candidates = [
        settings.thinking_classifier_model,
        "qwen3.5-flash",
        llm_model_id,
        settings.dashscope_model,
    ]
    seen: set[str] = set()
    for candidate in candidates:
        normalized = (candidate or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        model_info = (
            db.query(ModelCatalog)
            .filter(ModelCatalog.model_id == normalized, ModelCatalog.is_active.is_(True))
            .first()
        )
        if model_info is not None or normalized in {settings.dashscope_model, llm_model_id}:
            return normalized
    return llm_model_id


def _fallback_context_route(
    *,
    user_message: str,
) -> ContextRouteDecision:
    lowered = user_message.strip().casefold()
    if _has_rag_context_signal(lowered):
        return ContextRouteDecision(
            route="full_rag",
            source="fallback",
            confidence=0.8,
            reason="document or uploaded-file hints require the full project context budget",
        )
    if _has_memory_context_signal(lowered):
        return ContextRouteDecision(
            route="memory_only",
            source="fallback",
            confidence=0.78,
            reason="memory-like hints require stored conversation context",
        )
    return ContextRouteDecision(
        route="none",
        source="fallback",
        confidence=0.72,
        reason="message can be answered directly without retrieval by default",
    )


def _has_rag_context_signal(lowered: str) -> bool:
    if any(hint in lowered for hint in _CONTEXT_ROUTE_HINTS_RAG):
        return True
    doc_terms = (
        "资料",
        "文档",
        "文件",
        "知识库",
        "上传",
        "document",
        "documents",
        "file",
        "files",
        "knowledge base",
        "uploaded",
    )
    verbs = ("根据", "结合", "参考", "基于", "based on", "according to", "using")
    return any(verb in lowered for verb in verbs) and any(term in lowered for term in doc_terms)


def _has_memory_context_signal(lowered: str) -> bool:
    return any(hint in lowered for hint in _CONTEXT_ROUTE_HINTS_MEMORY) or any(
        hint in lowered for hint in _CONTEXT_ROUTE_HINTS_PERSONAL
    )


def _extract_json_object(raw: str) -> dict[str, object] | None:
    text = raw.strip()
    if not text:
        return None

    candidates = [text]
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        candidates.append(text[start:end + 1])

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _parse_thinking_classifier_result(raw: str) -> ThinkingClassification | None:
    payload = _extract_json_object(raw)
    if not payload:
        return None

    enable_value = payload.get("enable_thinking")
    if isinstance(enable_value, bool):
        enable_thinking = enable_value
    elif isinstance(enable_value, str):
        normalized = enable_value.strip().lower()
        if normalized in {"true", "on", "yes", "think", "deep"}:
            enable_thinking = True
        elif normalized in {"false", "off", "no", "direct", "simple"}:
            enable_thinking = False
        else:
            return None
    else:
        return None

    confidence_value = payload.get("confidence", 0.0)
    try:
        confidence = max(0.0, min(1.0, float(confidence_value)))
    except (TypeError, ValueError):
        confidence = 0.0

    return ThinkingClassification(
        enable_thinking=enable_thinking,
        confidence=confidence,
        reason=str(payload.get("reason") or "").strip() or None,
    )


def _parse_context_classifier_result(raw: str) -> ContextRouteClassification | None:
    payload = _extract_json_object(raw)
    if not payload:
        return None

    route_value = str(payload.get("route") or "").strip().lower()
    if route_value not in _CONTEXT_ROUTE_VALUES:
        return None

    confidence_value = payload.get("confidence", 0.0)
    try:
        confidence = max(0.0, min(1.0, float(confidence_value)))
    except (TypeError, ValueError):
        confidence = 0.0

    return ContextRouteClassification(
        route=route_value,
        confidence=confidence,
        reason=str(payload.get("reason") or "").strip() or None,
    )


async def _classify_thinking_need(
    db: Session,
    *,
    llm_model_id: str,
    user_message: str,
    recent_messages: list[dict[str, str]],
) -> ThinkingClassification | None:
    classifier_model_id = _pick_thinking_classifier_model(db, llm_model_id=llm_model_id)
    recent_excerpt = "\n".join(
        f"{message.get('role', 'user')}: {message.get('content', '').strip()}"
        for message in recent_messages[-4:]
        if (message.get("content") or "").strip()
    )
    classifier_messages = [
        {
            "role": "system",
            "content": (
                "You decide whether the assistant should enable deep thinking for the latest user turn. "
                "Enable deep thinking for requests that likely need multi-step reasoning, planning, comparison, "
                "debugging, tradeoff analysis, careful synthesis, or non-trivial interpretation. "
                "Disable deep thinking for greetings, chit-chat, simple acknowledgements, direct factual answers, "
                "brief straightforward requests, or lightweight descriptions. "
                "Return JSON only with keys enable_thinking, confidence, reason."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Recent conversation:\n{recent_excerpt or '(none)'}\n\n"
                f"Latest user turn:\n{user_message.strip()}\n\n"
                "If the task can be answered directly without substantial internal reasoning, set enable_thinking to false. "
                "If the task benefits from deliberate decomposition or careful reasoning, set enable_thinking to true."
            ),
        },
    ]

    try:
        result = await chat_completion_detailed(
            classifier_messages,
            model=classifier_model_id,
            temperature=0.0,
            max_tokens=180,
            enable_thinking=False,
            enable_search=False,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Thinking classifier failed")
        return None

    classification = _parse_thinking_classifier_result(result.content)
    if classification is None:
        logger.warning("Thinking classifier returned unparsable content: %s", result.content)
    return classification


async def _classify_context_route(
    db: Session,
    *,
    llm_model_id: str,
    user_message: str,
    recent_messages: list[dict[str, str]],
    enable_thinking: bool,
) -> ContextRouteClassification | None:
    classifier_model_id = _pick_thinking_classifier_model(db, llm_model_id=llm_model_id)
    recent_excerpt = "\n".join(
        f"{message.get('role', 'user')}: {message.get('content', '').strip()}"
        for message in recent_messages[-4:]
        if (message.get("content") or "").strip()
    )
    classifier_messages = [
        {
            "role": "system",
            "content": (
                "You route how much project context the assistant should retrieve for the latest user turn. "
                "Return JSON only with keys route, confidence, reason. "
                "Valid route values: none, profile_only, memory_only, full_rag. "
                "Use none for greetings, thanks, praise, small talk, or self-introduction requests. "
                "Use profile_only for lightweight personalization that only needs stable profile, pinned memories, or assistant persona. "
                "Use memory_only for prior user facts, goals, preferences, or earlier conversation recall. "
                "Use full_rag when uploaded documents, files, project knowledge, or memory-linked files are likely needed. "
                "Deep thinking is only a hint toward a larger context budget, not a forced switch."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Recent conversation:\n{recent_excerpt or '(none)'}\n\n"
                f"Latest user turn:\n{user_message.strip()}\n\n"
                f"Deep thinking currently enabled: {'yes' if enable_thinking else 'no'}\n\n"
                "Choose the smallest sufficient context route."
            ),
        },
    ]

    try:
        result = await chat_completion_detailed(
            classifier_messages,
            model=classifier_model_id,
            temperature=0.0,
            max_tokens=180,
            enable_thinking=False,
            enable_search=False,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Context route classifier failed")
        return None

    classification = _parse_context_classifier_result(result.content)
    if classification is None:
        logger.warning("Context route classifier returned unparsable content: %s", result.content)
    return classification


async def resolve_enable_thinking(
    db: Session,
    *,
    project_id: str,
    user_message: str,
    recent_messages: list[dict[str, str]],
    preference: bool | None,
    llm_model_id: str | None = None,
) -> ThinkingDecision:
    if preference is True:
        return ThinkingDecision(
            enable_thinking=True,
            source="user_preference",
            confidence=1.0,
            reason="user explicitly enabled deep thinking",
        )
    if preference is False:
        return ThinkingDecision(
            enable_thinking=False,
            source="user_preference",
            confidence=1.0,
            reason="user explicitly disabled deep thinking",
        )

    rule_decision = _resolve_rule_thinking_decision(user_message=user_message)
    if rule_decision is not None:
        return rule_decision

    effective_model_id = llm_model_id or resolve_pipeline_model_id(
        db,
        project_id=project_id,
        model_type="llm",
    )
    classification = await _classify_thinking_need(
        db,
        llm_model_id=effective_model_id,
        user_message=user_message,
        recent_messages=recent_messages,
    )
    if classification and classification.confidence >= settings.thinking_classifier_min_confidence:
        return ThinkingDecision(
            enable_thinking=classification.enable_thinking,
            source="classifier",
            confidence=classification.confidence,
            reason=classification.reason,
        )

    return ThinkingDecision(
        enable_thinking=False,
        source="fallback",
        reason="rules and classifier did not require deep thinking",
    )


async def resolve_context_route(
    db: Session,
    *,
    project_id: str,
    user_message: str,
    recent_messages: list[dict[str, str]],
    enable_thinking: bool,
    llm_model_id: str | None = None,
) -> ContextRouteDecision:
    rule_decision = _resolve_rule_context_route(user_message=user_message)
    if rule_decision is not None:
        return rule_decision

    effective_model_id = llm_model_id or resolve_pipeline_model_id(
        db,
        project_id=project_id,
        model_type="llm",
    )
    classification = await _classify_context_route(
        db,
        llm_model_id=effective_model_id,
        user_message=user_message,
        recent_messages=recent_messages,
        enable_thinking=enable_thinking,
    )
    if classification and classification.confidence >= settings.thinking_classifier_min_confidence:
        return ContextRouteDecision(
            route=classification.route,
            source="classifier",
            confidence=classification.confidence,
            reason=classification.reason,
        )

    return _fallback_context_route(user_message=user_message)

def _should_use_responses_auto_tools(
    *,
    llm_model_id: str,
    llm_capabilities: set[str],
    tool_definitions: list[dict[str, object]] | None = None,
    image_bytes: bytes | None = None,
    video_bytes: bytes | None = None,
    video_frame_data_urls: list[str] | None = None,
) -> bool:
    if video_bytes or video_frame_data_urls:
        return False
    if image_bytes and not model_supports_image_input(llm_model_id):
        return False
    if "responses_api" not in llm_capabilities or not model_supports_responses_api(llm_model_id):
        return False
    if tool_definitions is not None:
        return bool(tool_definitions)
    if "function_calling" in llm_capabilities:
        return True
    return False


def _build_chat_function_tool_definitions(
    *,
    llm_capabilities: set[str],
) -> list[dict[str, object]]:
    if "function_calling" not in llm_capabilities:
        return []
    return [dict(tool) for tool in get_function_tools()]


def _function_tool_name(tool: dict[str, object]) -> str:
    function_payload = tool.get("function") if isinstance(tool.get("function"), dict) else tool
    name = function_payload.get("name")
    return str(name).strip() if isinstance(name, str) else ""


def _function_tool_description(tool: dict[str, object]) -> str:
    function_payload = tool.get("function") if isinstance(tool.get("function"), dict) else tool
    description = str(function_payload.get("description") or "").strip()
    parameters = function_payload.get("parameters")
    if not isinstance(parameters, dict):
        return description
    properties = parameters.get("properties")
    if not isinstance(properties, dict) or not properties:
        return description
    parameter_names = [
        str(key).strip()
        for key in properties.keys()
        if isinstance(key, str) and key.strip()
    ]
    if not parameter_names:
        return description
    suffix = " Parameters: " + ", ".join(parameter_names[:8])
    return f"{description}{suffix}".strip()


def _native_tool_candidate_description(
    *,
    tool_name: str,
    definition: dict[str, object],
) -> str:
    base = _NATIVE_TOOL_SELECTION_DESCRIPTIONS.get(tool_name, tool_name.replace("_", " "))
    extras: list[str] = []
    if tool_name == "file_search":
        vector_store_ids = definition.get("vector_store_ids")
        if isinstance(vector_store_ids, list) and vector_store_ids:
            extras.append(f"vector stores: {', '.join(str(item) for item in vector_store_ids[:3])}")
    if tool_name == "mcp":
        server_label = definition.get("server_label")
        if isinstance(server_label, str) and server_label.strip():
            extras.append(f"server: {server_label.strip()}")
    if not extras:
        return base
    return f"{base} {'; '.join(extras)}"


def _build_response_tool_candidates(
    *,
    llm_model_id: str,
    llm_capabilities: set[str],
    image_bytes: bytes | None,
    llm_config_json: dict[str, object],
) -> list[ToolSelectionCandidate]:
    candidates: list[ToolSelectionCandidate] = []
    seen_keys: set[str] = set()

    def _append_candidate(candidate: ToolSelectionCandidate) -> None:
        if candidate.key in seen_keys:
            return
        seen_keys.add(candidate.key)
        candidates.append(candidate)

    if "function_calling" in llm_capabilities:
        for tool in get_response_function_tools():
            name = _function_tool_name(tool)
            if not name:
                continue
            _append_candidate(
                ToolSelectionCandidate(
                    key=f"function:{name}",
                    tool_name=name,
                    category="function",
                    description=_function_tool_description(tool),
                    definition=dict(tool),
                    dependencies=_FUNCTION_TOOL_DEPENDENCIES.get(name, ()),
                )
            )

    for tool_name in _NATIVE_TOOL_ORDER:
        if not model_supports_native_responses_tool(llm_model_id, tool_name):
            continue
        if tool_name == "image_search" and not image_bytes:
            continue
        if native_tool_requires_config(tool_name):
            configured_definitions = _configured_native_tool_definitions(
                tool_name=tool_name,
                llm_config_json=llm_config_json,
            )
            for index, definition in enumerate(configured_definitions):
                key_suffix = str(definition.get("server_label") or definition.get("vector_store_ids") or index)
                _append_candidate(
                    ToolSelectionCandidate(
                        key=f"native:{tool_name}:{key_suffix}",
                        tool_name=tool_name,
                        category="native",
                        description=_native_tool_candidate_description(
                            tool_name=tool_name,
                            definition=definition,
                        ),
                        definition=dict(definition),
                        dependencies=_NATIVE_TOOL_DEPENDENCIES.get(tool_name, ()),
                    )
                )
            continue
        definition = build_native_tool_definition(tool_name)
        _append_candidate(
            ToolSelectionCandidate(
                key=f"native:{tool_name}",
                tool_name=tool_name,
                category="native",
                description=_native_tool_candidate_description(
                    tool_name=tool_name,
                    definition=definition,
                ),
                definition=definition,
                dependencies=_NATIVE_TOOL_DEPENDENCIES.get(tool_name, ()),
            )
        )

    return candidates


def _build_chat_function_tool_candidates(
    *,
    llm_capabilities: set[str],
) -> list[ToolSelectionCandidate]:
    if "function_calling" not in llm_capabilities:
        return []

    candidates: list[ToolSelectionCandidate] = []
    for tool in get_function_tools():
        name = _function_tool_name(tool)
        if not name:
            continue
        candidates.append(
            ToolSelectionCandidate(
                key=f"function:{name}",
                tool_name=name,
                category="function",
                description=_function_tool_description(tool),
                definition=dict(tool),
                dependencies=_FUNCTION_TOOL_DEPENDENCIES.get(name, ()),
            )
        )
    return candidates


def _build_response_tool_definitions(
    *,
    llm_model_id: str,
    llm_capabilities: set[str],
    enable_search: bool,
    user_message: str,
    image_bytes: bytes | None,
    llm_config_json: dict[str, object],
) -> list[dict[str, object]]:
    tools: list[dict[str, object]] = []

    def _append_native_tool(tool_name: str) -> None:
        tools.append(build_native_tool_definition(tool_name))

    if "function_calling" in llm_capabilities:
        tools.extend(get_response_function_tools())
    if enable_search and model_supports_native_responses_tool(llm_model_id, "web_search"):
        _append_native_tool("web_search")
    if _should_offer_web_extractor(user_message) and model_supports_native_responses_tool(
        llm_model_id,
        "web_extractor",
    ):
        if model_supports_native_responses_tool(llm_model_id, "web_search"):
            _append_native_tool("web_search")
        _append_native_tool("web_extractor")
    if _should_offer_web_search_image(user_message) and model_supports_native_responses_tool(
        llm_model_id,
        "web_search_image",
    ):
        _append_native_tool("web_search_image")
    if _should_offer_image_search(user_message=user_message, image_bytes=image_bytes) and model_supports_native_responses_tool(
        llm_model_id,
        "image_search",
    ):
        _append_native_tool("image_search")
    if _should_offer_code_interpreter(user_message) and model_supports_native_responses_tool(
        llm_model_id,
        "code_interpreter",
    ):
        _append_native_tool("code_interpreter")
    for configurable_tool in ("file_search", "mcp"):
        if not model_supports_native_responses_tool(llm_model_id, configurable_tool):
            continue
        if not native_tool_requires_config(configurable_tool):
            continue
        tools.extend(
            _configured_native_tool_definitions(
                tool_name=configurable_tool,
                llm_config_json=llm_config_json,
            )
        )
    deduped: dict[str, dict[str, object]] = {}
    for tool in tools:
        deduped[json.dumps(tool, sort_keys=True, ensure_ascii=False)] = tool
    tools = list(deduped.values())
    return tools


def _response_enable_thinking_value(
    *,
    llm_model_id: str,
    enable_thinking: bool | None,
    tool_definitions: list[dict[str, object]] | None = None,
) -> bool | None:
    if tool_definitions:
        native_tool_names = {
            normalize_native_tool_name(str(tool.get("type") or ""))
            for tool in tool_definitions
            if isinstance(tool, dict) and isinstance(tool.get("type"), str)
        }
        if any(native_tool_requires_thinking(tool_name, llm_model_id) for tool_name in native_tool_names):
            return True
    if enable_thinking is None:
        return None
    if model_supports_deep_thinking(llm_model_id):
        return enable_thinking
    return None


async def _select_response_tool_definitions(
    *,
    llm_model_id: str,
    llm_capabilities: set[str],
    user_message: str,
    recent_messages: list[dict[str, str]],
    image_bytes: bytes | None,
    llm_config_json: dict[str, object],
    search_enabled: bool,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    def _heuristic_fallback(trace_source: str, failure_reason: str | None = None) -> tuple[list[dict[str, object]], dict[str, object]]:
        fallback_tools = _build_response_tool_definitions(
            llm_model_id=llm_model_id,
            llm_capabilities=llm_capabilities,
            enable_search=search_enabled,
            user_message=user_message,
            image_bytes=image_bytes,
            llm_config_json=llm_config_json,
        )
        trace: dict[str, object] = {
            "source": trace_source,
            "candidate_count": len(fallback_tools),
            "selected_tool_names": [str(tool.get("type") or tool.get("name") or "") for tool in fallback_tools],
            "applied": False,
            "query": user_message.strip(),
            "fallback_mode": "heuristic_rules",
        }
        if failure_reason:
            trace["failure_reason"] = failure_reason
        return fallback_tools, trace

    if not settings.dashscope_api_key.strip():
        return _heuristic_fallback("ai_gateway_missing_api_key")

    candidates = _build_response_tool_candidates(
        llm_model_id=llm_model_id,
        llm_capabilities=llm_capabilities,
        image_bytes=image_bytes,
        llm_config_json=llm_config_json,
    )
    if not candidates:
        return [], {
            "source": "ai_gateway_no_candidates",
            "candidate_count": 0,
            "selected_tool_names": [],
            "applied": False,
            "query": user_message.strip(),
        }

    required_tool_names: set[str] = set()
    if search_enabled and model_supports_native_responses_tool(llm_model_id, "web_search"):
        required_tool_names.add("web_search")

    selection = await select_tools_with_ai_gateway_prefilter(
        user_message=user_message,
        recent_messages=recent_messages,
        candidates=candidates,
        llm_config_json=llm_config_json,
        required_tool_names=required_tool_names,
    )
    if selection.trace.source in {"ai_gateway_disabled", "ai_gateway_bypass"}:
        return _heuristic_fallback(
            selection.trace.source,
            selection.trace.failure_reason,
        )
    return [dict(candidate.definition) for candidate in selection.candidates], selection.trace.as_dict()


async def _select_chat_function_tool_definitions(
    *,
    llm_capabilities: set[str],
    user_message: str,
    recent_messages: list[dict[str, str]],
    llm_config_json: dict[str, object],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    def _heuristic_fallback(trace_source: str, failure_reason: str | None = None) -> tuple[list[dict[str, object]], dict[str, object]]:
        fallback_tools = _build_chat_function_tool_definitions(
            llm_capabilities=llm_capabilities,
        )
        trace: dict[str, object] = {
            "source": trace_source,
            "candidate_count": len(fallback_tools),
            "selected_tool_names": [_function_tool_name(tool) for tool in fallback_tools],
            "applied": False,
            "query": user_message.strip(),
            "fallback_mode": "heuristic_rules",
        }
        if failure_reason:
            trace["failure_reason"] = failure_reason
        return fallback_tools, trace

    if not settings.dashscope_api_key.strip():
        return _heuristic_fallback("ai_gateway_missing_api_key")

    candidates = _build_chat_function_tool_candidates(
        llm_capabilities=llm_capabilities,
    )
    if not candidates:
        return [], {
            "source": "ai_gateway_no_candidates",
            "candidate_count": 0,
            "selected_tool_names": [],
            "applied": False,
            "query": user_message.strip(),
        }

    selection = await select_tools_with_ai_gateway_prefilter(
        user_message=user_message,
        recent_messages=recent_messages,
        candidates=candidates,
        llm_config_json=llm_config_json,
    )
    if selection.trace.source in {"ai_gateway_disabled", "ai_gateway_bypass"}:
        return _heuristic_fallback(
            selection.trace.source,
            selection.trace.failure_reason,
        )
    return [dict(candidate.definition) for candidate in selection.candidates], selection.trace.as_dict()


async def _call_llm_with_auto_tools(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    conversation_id: str,
    messages: list[dict[str, str]],
    llm_model_id: str,
    tool_definitions: list[dict[str, object]],
    response_enable_thinking: bool | None,
    image_bytes: bytes | None = None,
    image_mime_type: str = "image/jpeg",
) -> ChatCompletionResult:
    _, conversation = _load_active_conversation_context(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_id=conversation_id,
    )
    tool_messages: list[dict[str, object]] = [dict(message) for message in messages]
    last_result = ChatCompletionResult(content="")
    collected_sources: list[SearchSource] = []

    for _ in range(4):
        last_result = await responses_completion_detailed(
            tool_messages,
            model=llm_model_id,
            enable_thinking=response_enable_thinking,
            tools=tool_definitions,
            tool_choice="auto",
            image_bytes=image_bytes,
            image_mime_type=image_mime_type,
        )
        collected_sources = merge_search_sources(collected_sources, last_result.search_sources)
        if not last_result.tool_calls:
            last_result.search_sources = merge_search_sources(collected_sources)
            return last_result

        for tool_call in last_result.tool_calls:
            tool_messages.append(
                {
                    "type": "function_call",
                    "call_id": tool_call.id,
                    "name": tool_call.name,
                    "arguments": tool_call.arguments,
                }
            )
            tool_result = await execute_function_tool_call(
                db,
                workspace_id=workspace_id,
                project_id=project_id,
                conversation_id=conversation_id,
                conversation_created_by=conversation.created_by,
                name=tool_call.name,
                arguments_json=tool_call.arguments,
            )
            tool_messages.append(
                {
                    "type": "function_call_output",
                    "call_id": tool_call.id,
                    "output": json.dumps(tool_result, ensure_ascii=False),
                }
            )

    last_result.search_sources = merge_search_sources(collected_sources)
    return last_result


async def _stream_llm_with_auto_tools(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    conversation_id: str,
    messages: list[dict[str, str]],
    llm_model_id: str,
    tool_definitions: list[dict[str, object]],
    response_enable_thinking: bool | None,
    image_bytes: bytes | None = None,
    image_mime_type: str = "image/jpeg",
) -> AsyncIterator[ResponsesStreamChunk]:
    _, conversation = _load_active_conversation_context(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_id=conversation_id,
    )
    tool_messages: list[dict[str, object]] = [dict(message) for message in messages]

    for _ in range(4):
        tool_calls: list[ToolCall] = []
        async for chunk in responses_completion_stream(
            tool_messages,
            model=llm_model_id,
            enable_thinking=response_enable_thinking,
            tools=tool_definitions,
            tool_choice="auto",
            image_bytes=image_bytes,
            image_mime_type=image_mime_type,
        ):
            if chunk.tool_calls:
                tool_calls.extend(chunk.tool_calls)
            if chunk.content or chunk.reasoning_content or chunk.search_sources or chunk.finish_reason:
                yield chunk

        if not tool_calls:
            return

        for tool_call in tool_calls:
            tool_messages.append(
                {
                    "type": "function_call",
                    "call_id": tool_call.id,
                    "name": tool_call.name,
                    "arguments": tool_call.arguments,
                }
            )
            tool_result = await execute_function_tool_call(
                db,
                workspace_id=workspace_id,
                project_id=project_id,
                conversation_id=conversation_id,
                conversation_created_by=conversation.created_by,
                name=tool_call.name,
                arguments_json=tool_call.arguments,
            )
            tool_messages.append(
                {
                    "type": "function_call_output",
                    "call_id": tool_call.id,
                    "output": json.dumps(tool_result, ensure_ascii=False),
                }
            )


async def _call_llm_with_chat_api_function_tools(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    conversation_id: str,
    messages: list[dict[str, str]],
    llm_model_id: str,
    tool_definitions: list[dict[str, object]],
    enable_thinking: bool | None,
    enable_search: bool,
    search_options: dict[str, Any] | None,
    image_bytes: bytes | None = None,
    image_mime_type: str = "image/jpeg",
    video_bytes: bytes | None = None,
    video_mime_type: str = "video/mp4",
    video_frame_data_urls: list[str] | None = None,
    video_fps: float = 1.0,
) -> ChatCompletionResult:
    _, conversation = _load_active_conversation_context(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_id=conversation_id,
    )
    tool_messages: list[dict[str, object]] = [dict(message) for message in messages]
    last_result = ChatCompletionResult(content="")
    collected_sources: list[SearchSource] = []

    for _ in range(4):
        if image_bytes or video_bytes or video_frame_data_urls:
            last_result = await chat_completion_multimodal_detailed(
                tool_messages,
                model=llm_model_id,
                image_bytes=image_bytes,
                image_mime_type=image_mime_type,
                video_bytes=video_bytes,
                video_mime_type=video_mime_type,
                video_frame_data_urls=video_frame_data_urls,
                video_fps=video_fps,
                enable_thinking=enable_thinking,
                enable_search=enable_search,
                search_options=search_options,
                tools=tool_definitions,
                tool_choice="auto",
                parallel_tool_calls=True,
            )
        else:
            last_result = await chat_completion_detailed(
                tool_messages,
                model=llm_model_id,
                enable_thinking=enable_thinking,
                enable_search=enable_search,
                search_options=search_options,
                tools=tool_definitions,
                tool_choice="auto",
                parallel_tool_calls=True,
            )
        collected_sources = merge_search_sources(collected_sources, last_result.search_sources)
        if not last_result.tool_calls:
            last_result.search_sources = merge_search_sources(collected_sources)
            return last_result

        tool_messages.append(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": tool_call.id,
                        "type": tool_call.type or "function",
                        "function": {
                            "name": tool_call.name,
                            "arguments": tool_call.arguments,
                        },
                    }
                    for tool_call in last_result.tool_calls
                ],
            }
        )
        for tool_call in last_result.tool_calls:
            tool_result = await execute_function_tool_call(
                db,
                workspace_id=workspace_id,
                project_id=project_id,
                conversation_id=conversation_id,
                conversation_created_by=conversation.created_by,
                name=tool_call.name,
                arguments_json=tool_call.arguments,
            )
            tool_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(tool_result, ensure_ascii=False),
                }
            )

    last_result.search_sources = merge_search_sources(collected_sources)
    return last_result


async def _stream_llm_with_chat_api_function_tools(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    conversation_id: str,
    messages: list[dict[str, str]],
    llm_model_id: str,
    tool_definitions: list[dict[str, object]],
    enable_thinking: bool | None,
    enable_search: bool,
    search_options: dict[str, Any] | None,
    image_bytes: bytes | None = None,
    image_mime_type: str = "image/jpeg",
    video_bytes: bytes | None = None,
    video_mime_type: str = "video/mp4",
    video_frame_data_urls: list[str] | None = None,
    video_fps: float = 1.0,
) -> AsyncIterator[ResponsesStreamChunk]:
    result = await _call_llm_with_chat_api_function_tools(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_id=conversation_id,
        messages=messages,
        llm_model_id=llm_model_id,
        tool_definitions=tool_definitions,
        enable_thinking=enable_thinking,
        enable_search=enable_search,
        search_options=search_options,
        image_bytes=image_bytes,
        image_mime_type=image_mime_type,
        video_bytes=video_bytes,
        video_mime_type=video_mime_type,
        video_frame_data_urls=video_frame_data_urls,
        video_fps=video_fps,
    )
    if result.reasoning_content:
        yield ResponsesStreamChunk(reasoning_content=result.reasoning_content)
    if result.content:
        yield ResponsesStreamChunk(content=result.content)
    if result.search_sources:
        yield ResponsesStreamChunk(search_sources=result.search_sources)
    yield ResponsesStreamChunk(finish_reason=result.finish_reason or "completed")


async def _assemble_prompt_context(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    conversation_id: str,
    user_message: str,
    recent_messages: list[dict[str, str]],
    llm_model_id: str,
    enable_thinking: bool,
) -> tuple[list[dict[str, str]], dict[str, object]]:
    project, _conversation = _load_active_conversation_context(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_id=conversation_id,
    )
    context_route = await resolve_context_route(
        db,
        project_id=project_id,
        user_message=user_message,
        recent_messages=recent_messages,
        enable_thinking=enable_thinking,
        llm_model_id=llm_model_id,
    )
    context = await build_memory_context(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_id=conversation_id,
        user_message=user_message,
        recent_messages=recent_messages,
        personality=extract_personality(project.description) if project else "",
        context_level=context_route.route,
        semantic_search_fn=search_similar,
        linked_file_loader_fn=load_linked_file_chunks_for_memories,
    )
    retrieval_trace = dict(context.retrieval_trace)
    retrieval_trace.update(
        {
            "context_level": context_route.route,
            "decision_source": context_route.source,
            "decision_reason": context_route.reason,
            "decision_confidence": context_route.confidence,
        }
    )
    system_prompt = f"{context.system_prompt}\n\n{_GRAPH_TOOL_INSTRUCTION}\n\n{_MARKDOWN_FORMAT_INSTRUCTION}".strip()
    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    messages.extend(recent_messages[-20:])  # Last 20 messages for context
    messages.append({"role": "user", "content": user_message})
    return messages, retrieval_trace


async def _assemble_llm_context(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    conversation_id: str,
    user_message: str,
    recent_messages: list[dict[str, str]],
    llm_model_id: str,
    enable_thinking: bool,
) -> list[dict[str, str]]:
    messages, _retrieval_trace = await _assemble_prompt_context(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_id=conversation_id,
        user_message=user_message,
        recent_messages=recent_messages,
        llm_model_id=llm_model_id,
        enable_thinking=enable_thinking,
    )
    return messages


async def _build_and_call_llm(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    conversation_id: str,
    user_message: str,
    recent_messages: list[dict[str, str]],
    llm_model_id: str,
    image_bytes: bytes | None = None,
    image_mime_type: str = "image/jpeg",
    video_bytes: bytes | None = None,
    video_mime_type: str = "video/mp4",
    video_frame_data_urls: list[str] | None = None,
    video_fps: float = 1.0,
    enable_thinking: bool | None = None,
    enable_search: bool | None = None,
    voice_response_mode: bool = False,
) -> dict[str, object]:
    """Shared logic used by both text and voice pipelines.

    1. Retrieve RAG knowledge (semantic search)
    2. Load relevant memories (permanent + conversation temporary)
    3. Load project personality
    4. Assemble system prompt
    5. Call model API (text-only or multimodal if *image_bytes* provided)
    """
    thinking_decision = await resolve_enable_thinking(
        db,
        project_id=project_id,
        user_message=user_message,
        recent_messages=recent_messages,
        preference=enable_thinking,
        llm_model_id=llm_model_id,
    )
    resolved_enable_thinking = thinking_decision.enable_thinking
    messages, retrieval_trace = await _assemble_prompt_context(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_id=conversation_id,
        user_message=user_message,
        recent_messages=recent_messages,
        llm_model_id=llm_model_id,
        enable_thinking=resolved_enable_thinking,
    )
    if voice_response_mode:
        messages = apply_voice_response_guidance(messages)
    llm_capabilities = _load_model_capabilities(db, model_id=llm_model_id)
    search_decision = await _resolve_search_options(
        db,
        llm_model_id=llm_model_id,
        llm_capabilities=llm_capabilities,
        user_message=user_message,
        recent_messages=recent_messages,
        preference=enable_search,
    )
    search_enabled = search_decision.enable_search
    search_options = search_decision.search_options
    llm_config_json = _load_llm_config_json(db, project_id=project_id)
    response_tool_definitions, response_tool_trace = await _select_response_tool_definitions(
        llm_model_id=llm_model_id,
        llm_capabilities=llm_capabilities,
        user_message=user_message,
        recent_messages=recent_messages,
        image_bytes=image_bytes,
        llm_config_json=llm_config_json,
        search_enabled=search_enabled,
    )
    if model_supports_responses_api(llm_model_id):
        chat_function_tool_definitions = []
        chat_tool_trace = {
            "source": "responses_model_uses_responses_tooling",
            "candidate_count": 0,
            "selected_tool_names": [],
            "applied": False,
            "query": user_message.strip(),
        }
    else:
        chat_function_tool_definitions, chat_tool_trace = await _select_chat_function_tool_definitions(
            llm_capabilities=llm_capabilities,
            user_message=user_message,
            recent_messages=recent_messages,
            llm_config_json=llm_config_json,
        )
    retrieval_trace["tool_selection"] = (
        response_tool_trace
        if response_tool_definitions or "responses_api" in llm_capabilities
        else chat_tool_trace
    )
    response_enable_thinking = _response_enable_thinking_value(
        llm_model_id=llm_model_id,
        enable_thinking=resolved_enable_thinking,
        tool_definitions=response_tool_definitions,
    )
    should_use_responses_auto_tools = _should_use_responses_auto_tools(
        llm_model_id=llm_model_id,
        llm_capabilities=llm_capabilities,
        tool_definitions=response_tool_definitions,
        image_bytes=image_bytes,
        video_bytes=video_bytes,
        video_frame_data_urls=video_frame_data_urls,
    )

    if should_use_responses_auto_tools:
        result = await _call_llm_with_auto_tools(
            db,
            workspace_id=workspace_id,
            project_id=project_id,
            conversation_id=conversation_id,
            messages=messages,
            llm_model_id=llm_model_id,
            tool_definitions=response_tool_definitions,
            response_enable_thinking=response_enable_thinking,
            image_bytes=image_bytes,
            image_mime_type=image_mime_type,
        )
    elif chat_function_tool_definitions:
        result = await _call_llm_with_chat_api_function_tools(
            db,
            workspace_id=workspace_id,
            project_id=project_id,
            conversation_id=conversation_id,
            messages=messages,
            llm_model_id=llm_model_id,
            tool_definitions=chat_function_tool_definitions,
            enable_thinking=resolved_enable_thinking,
            enable_search=search_enabled,
            search_options=search_options,
            image_bytes=image_bytes,
            image_mime_type=image_mime_type,
            video_bytes=video_bytes,
            video_mime_type=video_mime_type,
            video_frame_data_urls=video_frame_data_urls,
            video_fps=video_fps,
        )
    elif image_bytes or video_bytes or video_frame_data_urls:
        result = await chat_completion_multimodal_detailed(
            messages,
            model=llm_model_id,
            image_bytes=image_bytes,
            image_mime_type=image_mime_type,
            video_bytes=video_bytes,
            video_mime_type=video_mime_type,
            video_frame_data_urls=video_frame_data_urls,
            video_fps=video_fps,
            enable_thinking=resolved_enable_thinking,
            enable_search=search_enabled,
            search_options=search_options,
        )
    else:
        result = await chat_completion_detailed(
            messages,
            model=llm_model_id,
            enable_thinking=resolved_enable_thinking,
            enable_search=search_enabled,
            search_options=search_options,
        )
    normalized_content, normalized_reasoning_content = _normalize_assistant_fields(
        result.content,
        result.reasoning_content if resolved_enable_thinking else None,
    )
    return {
        "content": normalized_content,
        "reasoning_content": normalized_reasoning_content,
        "sources": serialize_search_sources(result.search_sources),
        "retrieval_trace": retrieval_trace,
    }


# ---------------------------------------------------------------------------
# Public API: text-only inference (original interface, now delegates)
# ---------------------------------------------------------------------------


async def orchestrate_inference(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    conversation_id: str,
    user_message: str,
    recent_messages: list[dict[str, str]],
    enable_thinking: bool | None = None,
    enable_search: bool | None = None,
) -> dict[str, object]:
    """Orchestrate a full inference call (text → text).

    This is the original entry-point used by the chat endpoint.
    """
    # Resolve per-project LLM model
    llm_model_id = resolve_pipeline_model_id(db, project_id=project_id, model_type="llm")

    return await _build_and_call_llm(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_id=conversation_id,
        user_message=user_message,
        recent_messages=recent_messages,
        llm_model_id=llm_model_id,
        enable_thinking=enable_thinking,
        enable_search=enable_search,
    )


# ---------------------------------------------------------------------------
# Public API: streaming text inference (SSE)
# ---------------------------------------------------------------------------


async def orchestrate_inference_stream(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    conversation_id: str,
    user_message: str,
    recent_messages: list[dict[str, str]],
    enable_thinking: bool | None = None,
    enable_search: bool | None = None,
    user_id: str | None = None,
) -> AsyncIterator[dict]:
    """Streaming variant of :func:`orchestrate_inference`.

    Yields SSE-style event dicts as tokens arrive from the model:

    * ``{"event": "message_start", "data": {"role": "assistant"}}``
    * ``{"event": "token", "data": {"content": "..."}}``
    * ``{"event": "reasoning", "data": {"content": "..."}}``
    * ``{"event": "message_done", "data": {"content": ..., "reasoning_content": ...}}``

    On error an ``{"event": "error", "data": {"message": ...}}`` is emitted.
    """
    # Push an immediate SSE frame so the client can keep the turn alive while
    # planning, retrieval, and model-selection work is still in progress.
    yield {"event": "message_start", "data": {"role": "assistant"}}

    llm_model_id = resolve_pipeline_model_id(db, project_id=project_id, model_type="llm")
    thinking_decision = await resolve_enable_thinking(
        db,
        project_id=project_id,
        user_message=user_message,
        recent_messages=recent_messages,
        preference=enable_thinking,
        llm_model_id=llm_model_id,
    )
    resolved_enable_thinking = thinking_decision.enable_thinking
    llm_capabilities = _load_model_capabilities(db, model_id=llm_model_id)
    search_decision = await _resolve_search_options(
        db,
        llm_model_id=llm_model_id,
        llm_capabilities=llm_capabilities,
        user_message=user_message,
        recent_messages=recent_messages,
        preference=enable_search,
    )
    search_enabled = search_decision.enable_search
    search_options = search_decision.search_options
    llm_config_json = _load_llm_config_json(db, project_id=project_id)
    response_tool_definitions, response_tool_trace = await _select_response_tool_definitions(
        llm_model_id=llm_model_id,
        llm_capabilities=llm_capabilities,
        user_message=user_message,
        recent_messages=recent_messages,
        image_bytes=None,
        llm_config_json=llm_config_json,
        search_enabled=search_enabled,
    )
    if model_supports_responses_api(llm_model_id):
        chat_function_tool_definitions = []
        chat_tool_trace = {
            "source": "responses_model_uses_responses_tooling",
            "candidate_count": 0,
            "selected_tool_names": [],
            "applied": False,
            "query": user_message.strip(),
        }
    else:
        chat_function_tool_definitions, chat_tool_trace = await _select_chat_function_tool_definitions(
            llm_capabilities=llm_capabilities,
            user_message=user_message,
            recent_messages=recent_messages,
            llm_config_json=llm_config_json,
        )
    response_enable_thinking = _response_enable_thinking_value(
        llm_model_id=llm_model_id,
        enable_thinking=resolved_enable_thinking,
        tool_definitions=response_tool_definitions,
    )

    messages, retrieval_trace = await _assemble_prompt_context(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_id=conversation_id,
        user_message=user_message,
        recent_messages=recent_messages,
        llm_model_id=llm_model_id,
        enable_thinking=resolved_enable_thinking,
    )
    retrieval_trace["tool_selection"] = (
        response_tool_trace
        if response_tool_definitions or "responses_api" in llm_capabilities
        else chat_tool_trace
    )

    full_content = ""
    full_reasoning = ""
    full_sources: list[SearchSource] = []
    should_emit_reasoning = resolved_enable_thinking

    if _should_use_responses_auto_tools(
        llm_model_id=llm_model_id,
        llm_capabilities=llm_capabilities,
        tool_definitions=response_tool_definitions,
    ):
        try:
            async for chunk in _stream_llm_with_auto_tools(
                db,
                workspace_id=workspace_id,
                project_id=project_id,
                conversation_id=conversation_id,
                messages=messages,
                llm_model_id=llm_model_id,
                tool_definitions=response_tool_definitions,
                response_enable_thinking=response_enable_thinking,
            ):
                if chunk.search_sources:
                    full_sources = merge_search_sources(full_sources, chunk.search_sources)
                if should_emit_reasoning and chunk.reasoning_content:
                    full_reasoning += chunk.reasoning_content
                    yield {
                        "event": "reasoning",
                        "data": {
                            "content": chunk.reasoning_content,
                            "snapshot": normalize_assistant_markdown(full_reasoning),
                        },
                    }
                if chunk.content:
                    full_content += chunk.content
                    yield {
                        "event": "token",
                        "data": {
                            "content": chunk.content,
                            "snapshot": normalize_assistant_markdown(full_content),
                        },
                    }
        except Exception as exc:  # noqa: BLE001
            logger.exception("Auto-tool inference error")
            yield {"event": "error", "data": {"message": str(exc)}}
            return

        normalized_full_content, normalized_full_reasoning = _normalize_assistant_fields(
            full_content,
            full_reasoning if should_emit_reasoning else None,
        )
        yield {
            "event": "message_done",
            "data": {
                "content": normalized_full_content,
                "reasoning_content": normalized_full_reasoning,
                "sources": serialize_search_sources(full_sources),
                "retrieval_trace": retrieval_trace,
            },
        }
        return

    if chat_function_tool_definitions:
        try:
            async for chunk in _stream_llm_with_chat_api_function_tools(
                db,
                workspace_id=workspace_id,
                project_id=project_id,
                conversation_id=conversation_id,
                messages=messages,
                llm_model_id=llm_model_id,
                tool_definitions=chat_function_tool_definitions,
                enable_thinking=resolved_enable_thinking,
                enable_search=search_enabled,
                search_options=search_options,
            ):
                if chunk.search_sources:
                    full_sources = merge_search_sources(full_sources, chunk.search_sources)
                if should_emit_reasoning and chunk.reasoning_content:
                    full_reasoning += chunk.reasoning_content
                    yield {
                        "event": "reasoning",
                        "data": {
                            "content": chunk.reasoning_content,
                            "snapshot": normalize_assistant_markdown(full_reasoning),
                        },
                    }
                if chunk.content:
                    full_content += chunk.content
                    yield {
                        "event": "token",
                        "data": {
                            "content": chunk.content,
                            "snapshot": normalize_assistant_markdown(full_content),
                        },
                    }
        except Exception as exc:  # noqa: BLE001
            logger.exception("Chat-completions function-tool inference error")
            yield {"event": "error", "data": {"message": str(exc)}}
            return

        normalized_full_content, normalized_full_reasoning = _normalize_assistant_fields(
            full_content,
            full_reasoning if should_emit_reasoning else None,
        )
        yield {
            "event": "message_done",
            "data": {
                "content": normalized_full_content,
                "reasoning_content": normalized_full_reasoning,
                "sources": serialize_search_sources(full_sources),
                "retrieval_trace": retrieval_trace,
            },
        }
        return

    try:
        async for chunk in chat_completion_stream(
            messages,
            model=llm_model_id,
            enable_thinking=resolved_enable_thinking,
            enable_search=search_enabled,
            search_options=search_options,
        ):
            if chunk.search_sources:
                full_sources = merge_search_sources(full_sources, chunk.search_sources)
            if should_emit_reasoning and chunk.reasoning_content:
                full_reasoning += chunk.reasoning_content
                yield {
                    "event": "reasoning",
                    "data": {
                        "content": chunk.reasoning_content,
                        "snapshot": normalize_assistant_markdown(full_reasoning),
                    },
                }
            if chunk.content:
                full_content += chunk.content
                yield {
                    "event": "token",
                    "data": {
                        "content": chunk.content,
                        "snapshot": normalize_assistant_markdown(full_content),
                    },
                }
    except Exception as exc:  # noqa: BLE001
        logger.exception("Streaming inference error")
        yield {"event": "error", "data": {"message": str(exc)}}
        return

    normalized_full_content, normalized_full_reasoning = _normalize_assistant_fields(
        full_content,
        full_reasoning if should_emit_reasoning else None,
    )
    yield {
        "event": "message_done",
        "data": {
            "content": normalized_full_content,
            "reasoning_content": normalized_full_reasoning,
            "sources": serialize_search_sources(full_sources),
            "retrieval_trace": retrieval_trace,
        },
    }


async def transcribe_audio_input_for_project(
    db: Session,
    *,
    project_id: str,
    audio_bytes: bytes,
    filename: str = "audio.wav",
    content_type: str | None = None,
) -> str:
    from app.services.asr_client import transcribe_audio, transcribe_audio_realtime

    asr_model_id = resolve_pipeline_model_id(db, project_id=project_id, model_type="asr")
    asr_model_info = (
        db.query(ModelCatalog).filter(ModelCatalog.model_id == asr_model_id).first()
    )
    asr_is_realtime = asr_model_info is not None and "realtime" in (asr_model_info.capabilities or [])
    runtime_model_id = (
        asr_model_id
        if asr_model_id.startswith(_OPENAI_COMPATIBLE_ASR_PREFIXES)
        else "qwen3-asr-flash"
    )

    if asr_is_realtime:
        return await transcribe_audio_realtime(audio_bytes, model=asr_model_id)
    return await transcribe_audio(audio_bytes, filename=filename, model=runtime_model_id, content_type=content_type)


async def synthesize_speech_for_project(
    db: Session,
    *,
    project_id: str,
    text: str,
) -> bytes:
    from app.services.tts_client import synthesize_speech, synthesize_speech_realtime

    tts_model_id = resolve_pipeline_model_id(db, project_id=project_id, model_type="tts")
    tts_model_info = (
        db.query(ModelCatalog).filter(ModelCatalog.model_id == tts_model_id).first()
    )
    tts_is_realtime = tts_model_info is not None and "realtime" in (tts_model_info.capabilities or [])
    runtime_model_id = (
        tts_model_id
        if tts_model_id.startswith(_OPENAI_COMPATIBLE_TTS_PREFIXES)
        else "qwen3-tts-flash"
    )

    if tts_is_realtime:
        return await synthesize_speech_realtime(text, model=tts_model_id)
    return await synthesize_speech(text, model=runtime_model_id)


async def transcribe_realtime_audio_input_for_project(
    db: Session,
    *,
    project_id: str,
    audio_bytes: bytes,
) -> str:
    from app.services.asr_client import transcribe_audio_realtime

    asr_model_id = resolve_pipeline_model_id(db, project_id=project_id, model_type="realtime_asr")
    return await transcribe_audio_realtime(audio_bytes, model=asr_model_id)


async def synthesize_realtime_speech_for_project(
    db: Session,
    *,
    project_id: str,
    text: str,
) -> bytes:
    from app.services.tts_client import synthesize_speech_realtime

    tts_model_id = resolve_pipeline_model_id(db, project_id=project_id, model_type="realtime_tts")
    return await synthesize_speech_realtime(text, model=tts_model_id)


async def orchestrate_synthetic_realtime_turn(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    conversation_id: str,
    audio_bytes: bytes,
    image_bytes: bytes | None = None,
    image_mime_type: str = "image/jpeg",
    video_bytes: bytes | None = None,
    video_mime_type: str = "video/mp4",
    video_frame_data_urls: list[str] | None = None,
    video_fps: float = 1.0,
    enable_thinking: bool | None = None,
    enable_search: bool | None = None,
) -> dict[str, object]:
    user_text = await transcribe_realtime_audio_input_for_project(
        db,
        project_id=project_id,
        audio_bytes=audio_bytes,
    )
    return await orchestrate_synthetic_realtime_turn_from_text(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_id=conversation_id,
        user_text=user_text,
        image_bytes=image_bytes,
        image_mime_type=image_mime_type,
        video_bytes=video_bytes,
        video_mime_type=video_mime_type,
        video_frame_data_urls=video_frame_data_urls,
        video_fps=video_fps,
        enable_thinking=enable_thinking,
        enable_search=enable_search,
    )


async def orchestrate_synthetic_realtime_turn_from_text(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    conversation_id: str,
    user_text: str,
    image_bytes: bytes | None = None,
    image_mime_type: str = "image/jpeg",
    video_bytes: bytes | None = None,
    video_mime_type: str = "video/mp4",
    video_frame_data_urls: list[str] | None = None,
    video_fps: float = 1.0,
    enable_thinking: bool | None = None,
    enable_search: bool | None = None,
) -> dict[str, object]:
    normalized_user_text = user_text.strip()
    if not normalized_user_text:
        return {"text_input": "", "text_response": "", "sources": []}

    llm_model_id = resolve_pipeline_model_id(db, project_id=project_id, model_type="llm")
    recent_msgs = load_recent_messages(db, conversation_id=conversation_id, limit=20)
    llm_result = await _build_and_call_llm(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_id=conversation_id,
        user_message=normalized_user_text,
        recent_messages=recent_msgs,
        llm_model_id=llm_model_id,
        image_bytes=image_bytes,
        image_mime_type=image_mime_type,
        video_bytes=video_bytes,
        video_mime_type=video_mime_type,
        video_frame_data_urls=video_frame_data_urls,
        video_fps=video_fps,
        enable_thinking=enable_thinking,
        enable_search=enable_search,
        voice_response_mode=True,
    )
    return {
        "text_input": normalized_user_text,
        "text_response": clamp_voice_response_text(llm_result["content"] or ""),
        "reasoning_content": llm_result["reasoning_content"],
        "sources": llm_result.get("sources") or [],
        "retrieval_trace": llm_result.get("retrieval_trace") or {},
    }


# ---------------------------------------------------------------------------
# Public API: full voice pipeline (ASR → LLM → TTS)
# ---------------------------------------------------------------------------


async def orchestrate_voice_inference(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    conversation_id: str,
    audio_bytes: bytes | None = None,
    audio_filename: str | None = None,
    image_bytes: bytes | None = None,
    image_mime_type: str = "image/jpeg",
    text_input: str | None = None,
    return_audio: bool = True,
    enable_thinking: bool | None = None,
    enable_search: bool | None = None,
) -> dict:
    """Full voice pipeline orchestration.

    Returns:
        {
            "text_input": str,          # What the user said (after ASR)
            "text_response": str,       # AI's text response
            "audio_response": bytes | None,  # AI's voice (after TTS)
            "reasoning_content": str | None,
            "sources": list[dict],
        }
    """
    from app.services.vision_client import describe_image

    # ⓪ Check for omni model (handles audio in/out directly)  -------------
    llm_model_id = resolve_pipeline_model_id(db, project_id=project_id, model_type="llm")

    model_info = (
        db.query(ModelCatalog)
        .filter(ModelCatalog.model_id == llm_model_id)
        .first()
    )
    capabilities = model_info.capabilities if model_info else []
    is_omni = "audio_input" in capabilities and "audio_output" in capabilities
    llm_capabilities = {str(value).lower() for value in capabilities or []}
    recent_msgs = load_recent_messages(db, conversation_id=conversation_id, limit=20)
    search_decision = await _resolve_search_options(
        db,
        llm_model_id=llm_model_id,
        llm_capabilities=llm_capabilities,
        user_message=text_input or "",
        recent_messages=recent_msgs,
        preference=enable_search,
    )
    search_enabled = search_decision.enable_search
    search_options = search_decision.search_options

    if is_omni and (audio_bytes or image_bytes):
        thinking_decision = await resolve_enable_thinking(
            db,
            project_id=project_id,
            user_message=text_input or "(audio input)",
            recent_messages=recent_msgs,
            preference=enable_thinking,
            llm_model_id=llm_model_id,
        )
        resolved_enable_thinking = thinking_decision.enable_thinking
        # Omni mode: skip ASR (model understands audio directly)
        # Build context from recent messages
        user_text = text_input or "(audio input)"

        messages, retrieval_trace = await _assemble_prompt_context(
            db,
            workspace_id=workspace_id,
            project_id=project_id,
            conversation_id=conversation_id,
            user_message=user_text,
            recent_messages=recent_msgs,
            llm_model_id=llm_model_id,
            enable_thinking=resolved_enable_thinking,
        )
        if return_audio:
            messages = apply_voice_response_guidance(messages)

        omni_result = await omni_completion(
            messages,
            audio_bytes=audio_bytes,
            image_bytes=image_bytes,
            image_mime_type=image_mime_type,
            model=llm_model_id,
            enable_thinking=resolved_enable_thinking,
            enable_search=search_enabled,
            search_options=search_options,
        )
        text_response, normalized_omni_reasoning = _normalize_assistant_fields(
            omni_result["text"],
            omni_result.get("reasoning_content") if resolved_enable_thinking else None,
        )
        if return_audio:
            text_response = clamp_voice_response_text(text_response)

        # TTS: still separate for now (omni audio output requires WebSocket streaming)
        audio_response: bytes | None = None
        if return_audio and text_response:
            try:
                with db.begin_nested():
                    audio_response = await synthesize_speech_for_project(
                        db,
                        project_id=project_id,
                        text=text_response,
                    )
            except Exception:  # noqa: BLE001
                logger.warning("Realtime TTS failed in omni pipeline", exc_info=True)

        return {
            "text_input": user_text,
            "text_response": text_response,
            "audio_response": audio_response,
            "reasoning_content": normalized_omni_reasoning,
            "sources": omni_result.get("sources") or [],
            "retrieval_trace": retrieval_trace,
        }

    # ① ASR: audio → text  ------------------------------------------------
    user_text = text_input or ""
    if audio_bytes and not text_input:
        user_text = await transcribe_audio_input_for_project(
            db,
            project_id=project_id,
            audio_bytes=audio_bytes,
            filename=audio_filename or "audio.wav",
        )

    if not user_text.strip():
        return {"text_input": "", "text_response": "未检测到语音内容", "audio_response": None, "sources": []}

    # ② Get LLM config and capabilities  ----------------------------------
    llm_model_id = resolve_pipeline_model_id(db, project_id=project_id, model_type="llm")

    model_info = (
        db.query(ModelCatalog)
        .filter(ModelCatalog.model_id == llm_model_id)
        .first()
    )
    llm_capabilities = _load_model_capabilities(db, model_id=llm_model_id)
    llm_supports_vision = model_supports_image_input(llm_model_id) or "vision" in llm_capabilities

    # ③ Handle image input  ------------------------------------------------
    image_description: str | None = None
    use_multimodal_llm = False

    if image_bytes:
        if llm_supports_vision:
            use_multimodal_llm = True  # Pass image directly to LLM
        else:
            # Use separate Vision model
            vision_config = (
                db.query(PipelineConfig)
                .filter(
                    PipelineConfig.project_id == project_id,
                    PipelineConfig.model_type == "vision",
                )
                .first()
            )
            vision_model = vision_config.model_id if vision_config else "qwen-vl-plus"
            image_description = await describe_image(image_bytes, model=vision_model)

    # ④ Build context  -----------------------------------------------------
    # Get recent messages for conversation history
    # If we have an image description from a separate Vision model, prepend
    enriched_text = user_text
    if image_description:
        enriched_text = f"[用户发送了一张图片，内容是：{image_description}]\n{user_text}"

    # ⑤ Call LLM (reuses shared helper)  -----------------------------------
    llm_result = await _build_and_call_llm(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_id=conversation_id,
        user_message=enriched_text,
        recent_messages=recent_msgs,
        llm_model_id=llm_model_id,
        image_bytes=image_bytes if use_multimodal_llm else None,
        image_mime_type=image_mime_type,
        enable_thinking=enable_thinking,
        enable_search=enable_search,
        voice_response_mode=return_audio,
    )
    text_response = llm_result["content"] or ""
    if return_audio:
        text_response = clamp_voice_response_text(text_response)

    # ⑥ TTS: text → audio  ------------------------------------------------
    audio_response: bytes | None = None
    if return_audio and text_response:
        try:
            with db.begin_nested():
                audio_response = await synthesize_speech_for_project(
                    db,
                    project_id=project_id,
                    text=text_response,
                )
        except Exception:  # noqa: BLE001
            logger.warning("TTS failed in voice pipeline", exc_info=True)

    return {
        "text_input": user_text,
        "text_response": text_response,
        "audio_response": audio_response,
        "reasoning_content": llm_result["reasoning_content"],
        "sources": llm_result.get("sources") or [],
        "retrieval_trace": llm_result.get("retrieval_trace") or {},
    }
