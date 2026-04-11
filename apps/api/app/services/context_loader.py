"""Shared context-assembly logic for both HTTP and WebSocket inference paths.

Extracts personality, loads memories, builds system prompts.
Used by orchestrator.py (HTTP) and realtime_bridge.py (WebSocket).
"""
from __future__ import annotations

import re

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.models import (
    Conversation,
    DataItem,
    Dataset,
    Memory,
    Message,
    Project,
)
from app.services.embedding import search_similar


def extract_personality(description: str | None) -> str:
    """Extract personality from project description.

    Looks for [personality:...] block (multiline).
    Falls back to raw description if no tag found.
    """
    if not description:
        return ""
    match = re.search(r"\[personality:(.*?)\]", description, re.DOTALL)
    return match.group(1).strip() if match else description.strip()


def load_conversation_context(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    conversation_id: str,
) -> tuple[Project, Conversation]:
    """Load and validate project + conversation.

    Raises RuntimeError if not found.
    """
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
        raise RuntimeError("project_not_found")

    conversation = (
        db.query(Conversation)
        .filter(
            Conversation.id == conversation_id,
            Conversation.project_id == project_id,
            Conversation.workspace_id == workspace_id,
        )
        .first()
    )
    if not conversation:
        raise RuntimeError("conversation_not_found")

    return project, conversation


def load_permanent_memories(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    conversation_created_by: str | None,
    limit: int = 20,
) -> list[Memory]:
    """Load visible permanent memories for a conversation context."""
    query = (
        db.query(Memory)
        .filter(
            Memory.workspace_id == workspace_id,
            Memory.project_id == project_id,
            Memory.type == "permanent",
        )
        .order_by(desc(Memory.updated_at))
    )

    project_root_id = (
        db.query(Project.assistant_root_memory_id)
        .filter(
            Project.id == project_id,
            Project.workspace_id == workspace_id,
            Project.deleted_at.is_(None),
        )
        .scalar()
    )
    if project_root_id:
        query = query.filter(Memory.id != project_root_id)

    memories = query.limit(limit).all()

    visible = []
    for m in memories:
        meta = m.metadata_json or {}
        if meta.get("visibility") == "private":
            if conversation_created_by and meta.get("owner_user_id") == conversation_created_by:
                visible.append(m)
        else:
            visible.append(m)

    return visible


def load_recent_messages(
    db: Session,
    *,
    conversation_id: str,
    limit: int = 20,
) -> list[dict[str, str]]:
    """Load recent conversation messages as {role, content} dicts."""
    rows = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(desc(Message.created_at))
        .limit(limit)
        .all()
    )
    rows.reverse()
    return [{"role": m.role, "content": m.content} for m in rows]


async def search_rag_knowledge(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    query: str,
    limit: int = 12,
) -> list[dict]:
    """Run RAG semantic search and return matching chunks."""
    results = await search_similar(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        query=query,
        limit=limit,
    )
    return results


def filter_knowledge_chunks(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    results: list[dict],
) -> list[dict]:
    """Keep only chunks from visible, non-deleted datasets."""
    if not results:
        return []

    data_item_ids = [r["data_item_id"] for r in results if r.get("data_item_id")]
    if not data_item_ids:
        return results

    rows = (
        db.query(DataItem.id)
        .join(Dataset, Dataset.id == DataItem.dataset_id)
        .join(Project, Project.id == Dataset.project_id)
        .filter(
            DataItem.id.in_(data_item_ids),
            DataItem.deleted_at.is_(None),
            Dataset.deleted_at.is_(None),
            Project.deleted_at.is_(None),
            Project.workspace_id == workspace_id,
        )
        .all()
    )
    visible_ids = {r[0] for r in rows}

    return [
        r for r in results
        if not r.get("data_item_id") or r["data_item_id"] in visible_ids
    ]


def build_system_prompt(
    *,
    personality: str,
    memories: list[str],
    knowledge_chunks: list[str],
    recent_messages: list[dict[str, str]] | None = None,
) -> str:
    """Assemble the system prompt from personality, memories, and knowledge."""
    parts = []

    if personality:
        parts.append(personality)

    if memories:
        memory_block = "\n".join(f"- {m}" for m in memories)
        parts.append(f"\n你对这位用户的了解：\n{memory_block}")

    if knowledge_chunks:
        knowledge_block = "\n---\n".join(knowledge_chunks)
        parts.append(f"\n相关知识：\n{knowledge_block}")

    if recent_messages:
        history_lines = []
        for message in recent_messages:
            role = "用户" if message.get("role") == "user" else "助手"
            content = str(message.get("content") or "").strip()
            if content:
                history_lines.append(f"{role}: {content}")
        if history_lines:
            parts.append(f"\n最近对话历史：\n" + "\n".join(history_lines))

    return "\n\n".join(parts)
