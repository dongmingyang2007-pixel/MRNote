from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from app.models.entities import DataItem
from app.services.context_loader import filter_knowledge_chunks
from app.services.embedding import search_similar
from app.services.memory_context import (
    expand_subject_subgraph,
    get_concept_neighbors,
    get_explanation_path,
    get_subject_overview,
    resolve_active_subjects,
    search_project_memories_for_tool,
    search_subject_documents,
    search_subject_facts,
)


FUNCTION_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_project_knowledge",
            "description": "Fallback search across the current project's uploaded knowledge base for relevant excerpts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query to run."},
                    "top_k": {
                        "type": "integer",
                        "description": "Maximum number of excerpts to return.",
                        "minimum": 1,
                        "maximum": 8,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_project_memories",
            "description": "Fallback search across remembered facts and conversation memory for the current project.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query to run."},
                    "top_k": {
                        "type": "integer",
                        "description": "Maximum number of memories to return.",
                        "minimum": 1,
                        "maximum": 8,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resolve_active_subjects",
            "description": "Resolve which subject or entity is most relevant for the current turn in the project memory graph.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The user query or subject hint."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_subject_overview",
            "description": "Get a compact overview of a subject node, including top concepts and representative facts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "subject_id": {"type": "string", "description": "The subject memory id."},
                },
                "required": ["subject_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "expand_subject_subgraph",
            "description": "Expand the local concept and fact neighborhood around a subject.",
            "parameters": {
                "type": "object",
                "properties": {
                    "subject_id": {"type": "string", "description": "The subject memory id."},
                    "query": {"type": "string", "description": "Optional query to bias the expansion."},
                    "depth": {
                        "type": "integer",
                        "description": "Traversal depth.",
                        "minimum": 1,
                        "maximum": 4,
                    },
                    "edge_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional edge types to include.",
                    },
                },
                "required": ["subject_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_subject_facts",
            "description": "Search facts within one subject scope.",
            "parameters": {
                "type": "object",
                "properties": {
                    "subject_id": {"type": "string", "description": "The subject memory id."},
                    "query": {"type": "string", "description": "The search query."},
                    "top_k": {
                        "type": "integer",
                        "description": "Maximum number of facts to return.",
                        "minimum": 1,
                        "maximum": 8,
                    },
                },
                "required": ["subject_id", "query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_subject_documents",
            "description": "Search linked documents and evidence connected to one subject scope.",
            "parameters": {
                "type": "object",
                "properties": {
                    "subject_id": {"type": "string", "description": "The subject memory id."},
                    "query": {"type": "string", "description": "The evidence search query."},
                    "top_k": {
                        "type": "integer",
                        "description": "Maximum number of document excerpts to return.",
                        "minimum": 1,
                        "maximum": 8,
                    },
                },
                "required": ["subject_id", "query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_concept_neighbors",
            "description": "Inspect a concept node with its parent, children, and lateral neighbors.",
            "parameters": {
                "type": "object",
                "properties": {
                    "concept_id": {"type": "string", "description": "The concept memory id."},
                },
                "required": ["concept_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_explanation_path",
            "description": "Get a suggested explanation order from subject and concept context.",
            "parameters": {
                "type": "object",
                "properties": {
                    "subject_id": {"type": "string", "description": "The subject memory id."},
                    "concept_id": {"type": "string", "description": "The concept memory id."},
                    "target_style": {
                        "type": "string",
                        "description": "Optional explanation style hint.",
                    },
                },
                "required": ["subject_id", "concept_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_datetime",
            "description": "Get the current server time, optionally in a supplied IANA timezone name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "timezone": {
                        "type": "string",
                        "description": "Optional IANA timezone, for example Asia/Shanghai or Europe/London.",
                    }
                },
            },
        },
    },
]

_FUNCTION_TOOL_NAMES = {
    tool["function"]["name"]
    for tool in FUNCTION_TOOLS
    if isinstance(tool.get("function"), dict) and isinstance(tool["function"].get("name"), str)
}
_FUNCTION_TOOL_PRIORITY = {
    "resolve_active_subjects": 0,
    "get_subject_overview": 1,
    "expand_subject_subgraph": 2,
    "get_concept_neighbors": 3,
    "get_explanation_path": 4,
    "search_subject_documents": 5,
    "search_subject_facts": 6,
    "search_project_memories": 7,
    "search_project_knowledge": 8,
    "get_current_datetime": 9,
}


def _tool_priority(tool: dict[str, Any]) -> int:
    function_payload = tool.get("function") if isinstance(tool.get("function"), dict) else tool
    name = function_payload.get("name")
    if not isinstance(name, str):
        return 999
    return _FUNCTION_TOOL_PRIORITY.get(name, 999)


def get_function_tools() -> list[dict[str, Any]]:
    return sorted(
        [json.loads(json.dumps(tool)) for tool in FUNCTION_TOOLS],
        key=_tool_priority,
    )


def _normalize_response_tool_parameters_schema(schema: dict[str, Any]) -> dict[str, Any]:
    normalized = json.loads(json.dumps(schema))
    if normalized.get("type") == "object":
        properties = normalized.get("properties")
        if not isinstance(properties, dict):
            normalized["properties"] = {}
        if "required" not in normalized or not isinstance(normalized.get("required"), list):
            normalized["required"] = []
        normalized.setdefault("additionalProperties", False)
    return normalized


def get_response_function_tools() -> list[dict[str, Any]]:
    response_tools: list[dict[str, Any]] = []
    for tool in FUNCTION_TOOLS:
        function_payload = tool.get("function")
        if not isinstance(function_payload, dict):
            continue
        name = function_payload.get("name")
        if not isinstance(name, str) or not name:
            continue
        response_tool = {
            "type": "function",
            "name": name,
        }
        description = function_payload.get("description")
        if isinstance(description, str) and description:
            response_tool["description"] = description
        parameters = function_payload.get("parameters")
        if isinstance(parameters, dict):
            response_tool["parameters"] = _normalize_response_tool_parameters_schema(parameters)
        response_tools.append(response_tool)
    return sorted(
        response_tools,
        key=lambda tool: _FUNCTION_TOOL_PRIORITY.get(str(tool.get("name") or ""), 999),
    )


def _clamp_top_k(value: Any, default: int = 4) -> int:
    if not isinstance(value, int):
        return default
    return max(1, min(value, 8))


def _shorten_excerpt(text: str, limit: int = 600) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


def _serialize_memory_brief(memory: Any) -> dict[str, Any]:
    return {
        "id": getattr(memory, "id", None),
        "content": _shorten_excerpt(str(getattr(memory, "content", "") or ""), limit=240),
        "category": getattr(memory, "category", ""),
        "type": getattr(memory, "type", ""),
        "node_type": getattr(memory, "node_type", None),
        "subject_kind": getattr(memory, "subject_kind", None),
        "subject_memory_id": getattr(memory, "subject_memory_id", None),
        "canonical_key": getattr(memory, "canonical_key", None),
    }


async def _search_project_knowledge(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    query: str,
    top_k: int,
) -> dict[str, Any]:
    semantic_results = await search_similar(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        query=query,
        limit=max(12, top_k * 3),
    )
    knowledge_results = [
        result
        for result in filter_knowledge_chunks(
            db,
            workspace_id=workspace_id,
            project_id=project_id,
            results=semantic_results,
        )
        if not result.get("memory_id")
    ][:top_k]

    data_item_ids = [result["data_item_id"] for result in knowledge_results if result.get("data_item_id")]
    filenames = {
        item.id: item.filename
        for item in db.query(DataItem)
        .filter(DataItem.id.in_(data_item_ids))
        .all()
    } if data_item_ids else {}

    return {
        "query": query,
        "results": [
            {
                "filename": filenames.get(result.get("data_item_id"), "未命名资料"),
                "score": result.get("score"),
                "excerpt": _shorten_excerpt(result.get("chunk_text") or ""),
            }
            for result in knowledge_results
        ],
    }


async def _search_project_memories(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    conversation_id: str,
    conversation_created_by: str | None,
    query: str,
    top_k: int,
) -> dict[str, Any]:
    visible_results = await search_project_memories_for_tool(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_id=conversation_id,
        conversation_created_by=conversation_created_by,
        query=query,
        top_k=top_k,
        semantic_search_fn=search_similar,
    )
    return {
        "query": query,
        "results": [
            {
                **result,
                "content": _shorten_excerpt(str(result.get("content") or "")),
            }
            for result in visible_results
        ],
    }


async def _resolve_active_subjects(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    conversation_id: str,
    conversation_created_by: str | None,
    query: str,
) -> dict[str, Any]:
    resolved = await resolve_active_subjects(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_id=conversation_id,
        conversation_created_by=conversation_created_by,
        query=query,
        semantic_search_fn=search_similar,
    )
    subjects = resolved.get("subjects", [])
    primary_subject = resolved.get("primary_subject")
    return {
        "query": query,
        "primary_subject_id": primary_subject.id if primary_subject is not None else None,
        "subjects": [
            {
                "subject_id": candidate.memory.id,
                "label": candidate.memory.content,
                "confidence": candidate.semantic_score if candidate.semantic_score is not None else candidate.score,
                "subject_kind": candidate.memory.subject_kind,
                "canonical_key": candidate.memory.canonical_key,
            }
            for candidate in subjects
        ],
    }


def _get_current_datetime(*, timezone_name: str | None = None) -> dict[str, Any]:
    resolved_timezone = "UTC"
    tzinfo = timezone.utc
    if timezone_name:
        try:
            tzinfo = ZoneInfo(timezone_name)
            resolved_timezone = timezone_name
        except ZoneInfoNotFoundError:
            resolved_timezone = "UTC"
            tzinfo = timezone.utc

    now = datetime.now(tzinfo)
    return {
        "timezone": resolved_timezone,
        "current_time": now.isoformat(),
        "date": now.date().isoformat(),
        "weekday": now.strftime("%A"),
        "unix_seconds": int(now.timestamp()),
    }


async def execute_function_tool_call(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    conversation_id: str,
    conversation_created_by: str | None,
    name: str,
    arguments_json: str,
) -> dict[str, Any]:
    if name not in _FUNCTION_TOOL_NAMES:
        return {"ok": False, "error": f"unknown_tool:{name}"}

    try:
        raw_arguments = json.loads(arguments_json or "{}")
    except json.JSONDecodeError:
        return {"ok": False, "error": "invalid_json_arguments"}

    if not isinstance(raw_arguments, dict):
        return {"ok": False, "error": "invalid_tool_arguments"}

    try:
        if name == "search_project_knowledge":
            query = str(raw_arguments.get("query") or "").strip()
            if not query:
                return {"ok": False, "error": "missing_query"}
            return {
                "ok": True,
                **await _search_project_knowledge(
                    db,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    query=query,
                    top_k=_clamp_top_k(raw_arguments.get("top_k")),
                ),
            }
        if name == "search_project_memories":
            query = str(raw_arguments.get("query") or "").strip()
            if not query:
                return {"ok": False, "error": "missing_query"}
            return {
                "ok": True,
                **await _search_project_memories(
                    db,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    conversation_id=conversation_id,
                    conversation_created_by=conversation_created_by,
                    query=query,
                    top_k=_clamp_top_k(raw_arguments.get("top_k")),
                ),
            }
        if name == "resolve_active_subjects":
            query = str(raw_arguments.get("query") or "").strip()
            if not query:
                return {"ok": False, "error": "missing_query"}
            return {
                "ok": True,
                **await _resolve_active_subjects(
                    db,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    conversation_id=conversation_id,
                    conversation_created_by=conversation_created_by,
                    query=query,
                ),
            }
        if name == "get_subject_overview":
            subject_id = str(raw_arguments.get("subject_id") or "").strip()
            if not subject_id:
                return {"ok": False, "error": "missing_subject_id"}
            overview = get_subject_overview(
                db,
                workspace_id=workspace_id,
                project_id=project_id,
                conversation_id=conversation_id,
                conversation_created_by=conversation_created_by,
                subject_id=subject_id,
            )
            if overview is None:
                return {"ok": True, "result": {}}
            return {
                "ok": True,
                "result": {
                    "subject": _serialize_memory_brief(overview.get("subject")),
                    "concepts": [
                        _serialize_memory_brief(memory)
                        for memory in overview.get("concepts", [])
                    ],
                    "facts": [
                        _serialize_memory_brief(memory)
                        for memory in overview.get("facts", [])
                    ],
                    "suggested_paths": overview.get("suggested_paths", []),
                },
            }
        if name == "expand_subject_subgraph":
            subject_id = str(raw_arguments.get("subject_id") or "").strip()
            if not subject_id:
                return {"ok": False, "error": "missing_subject_id"}
            result = await expand_subject_subgraph(
                db,
                workspace_id=workspace_id,
                project_id=project_id,
                conversation_id=conversation_id,
                conversation_created_by=conversation_created_by,
                subject_id=subject_id,
                query=str(raw_arguments.get("query") or "").strip(),
                depth=max(1, min(4, int(raw_arguments.get("depth") or 2))),
                edge_types=[
                    value
                    for value in (raw_arguments.get("edge_types") or [])
                    if isinstance(value, str) and value.strip()
                ] or None,
                semantic_search_fn=search_similar,
            )
            if result is None:
                return {"ok": True, "result": {}}
            return {
                "ok": True,
                "result": {
                    "subject": _serialize_memory_brief(result.get("subject")),
                    "nodes": [
                        _serialize_memory_brief(memory)
                        for memory in result.get("nodes", [])
                    ],
                    "edges": result.get("edges", []),
                },
            }
        if name == "search_subject_facts":
            subject_id = str(raw_arguments.get("subject_id") or "").strip()
            query = str(raw_arguments.get("query") or "").strip()
            if not subject_id:
                return {"ok": False, "error": "missing_subject_id"}
            if not query:
                return {"ok": False, "error": "missing_query"}
            return {
                "ok": True,
                "query": query,
                "subject_id": subject_id,
                "results": await search_subject_facts(
                    db,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    conversation_id=conversation_id,
                    conversation_created_by=conversation_created_by,
                    subject_id=subject_id,
                    query=query,
                    top_k=_clamp_top_k(raw_arguments.get("top_k")),
                    semantic_search_fn=search_similar,
                ),
            }
        if name == "search_subject_documents":
            subject_id = str(raw_arguments.get("subject_id") or "").strip()
            query = str(raw_arguments.get("query") or "").strip()
            if not subject_id:
                return {"ok": False, "error": "missing_subject_id"}
            if not query:
                return {"ok": False, "error": "missing_query"}
            return {
                "ok": True,
                "query": query,
                "subject_id": subject_id,
                "results": await search_subject_documents(
                    db,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    conversation_id=conversation_id,
                    conversation_created_by=conversation_created_by,
                    subject_id=subject_id,
                    query=query,
                    top_k=_clamp_top_k(raw_arguments.get("top_k")),
                ),
            }
        if name == "get_concept_neighbors":
            concept_id = str(raw_arguments.get("concept_id") or "").strip()
            if not concept_id:
                return {"ok": False, "error": "missing_concept_id"}
            result = get_concept_neighbors(
                db,
                workspace_id=workspace_id,
                project_id=project_id,
                conversation_id=conversation_id,
                conversation_created_by=conversation_created_by,
                concept_id=concept_id,
            )
            if result is None:
                return {"ok": True, "result": {}}
            return {
                "ok": True,
                "result": {
                    "concept": _serialize_memory_brief(result.get("concept")),
                    "parent": _serialize_memory_brief(result.get("parent")) if result.get("parent") is not None else None,
                    "children": [
                        _serialize_memory_brief(memory)
                        for memory in result.get("children", [])
                    ],
                    "neighbors": result.get("neighbors", []),
                    "recent_facts": [
                        _serialize_memory_brief(memory)
                        for memory in result.get("recent_facts", [])
                    ],
                },
            }
        if name == "get_explanation_path":
            subject_id = str(raw_arguments.get("subject_id") or "").strip()
            concept_id = str(raw_arguments.get("concept_id") or "").strip()
            if not subject_id:
                return {"ok": False, "error": "missing_subject_id"}
            if not concept_id:
                return {"ok": False, "error": "missing_concept_id"}
            result = get_explanation_path(
                db,
                workspace_id=workspace_id,
                project_id=project_id,
                conversation_id=conversation_id,
                conversation_created_by=conversation_created_by,
                subject_id=subject_id,
                concept_id=concept_id,
                target_style=str(raw_arguments.get("target_style") or "").strip() or None,
            )
            return {"ok": True, "result": result or {}}
        return {
            "ok": True,
            **_get_current_datetime(timezone_name=str(raw_arguments.get("timezone") or "").strip() or None),
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"tool_execution_failed:{exc}"}
