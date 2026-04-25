from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text as sql_text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base_class import Base, TimestampMixin, UUIDPrimaryKeyMixin, UpdatedAtMixin


class Memory(Base, UUIDPrimaryKeyMixin, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "memories"

    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    type: Mapped[str] = mapped_column(String(20), default="permanent", nullable=False)
    node_type: Mapped[str] = mapped_column(String(20), default="fact", nullable=False)
    subject_kind: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    parent_memory_id: Mapped[str | None] = mapped_column(
        ForeignKey("memories.id", ondelete="SET NULL"), nullable=True
    )
    subject_memory_id: Mapped[str | None] = mapped_column(
        ForeignKey("memories.id", ondelete="SET NULL"), nullable=True
    )
    node_status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    canonical_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lineage_key: Mapped[str | None] = mapped_column(String(36), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.7, nullable=False)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    position_x: Mapped[float | None] = mapped_column(Float, nullable=True)
    position_y: Mapped[float | None] = mapped_column(Float, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class MemoryEdge(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "memory_edges"
    __table_args__ = (
        UniqueConstraint(
            "source_memory_id",
            "target_memory_id",
            "edge_type",
            name="uq_memory_edges_src_tgt_type",
        ),
    )

    source_memory_id: Mapped[str] = mapped_column(
        ForeignKey("memories.id", ondelete="CASCADE"), nullable=False
    )
    target_memory_id: Mapped[str] = mapped_column(
        ForeignKey("memories.id", ondelete="CASCADE"), nullable=False
    )
    edge_type: Mapped[str] = mapped_column(String(20), default="auto", nullable=False)
    strength: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class Embedding(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "embeddings"

    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    memory_id: Mapped[str | None] = mapped_column(
        ForeignKey("memories.id", ondelete="CASCADE"), nullable=True
    )
    data_item_id: Mapped[str | None] = mapped_column(
        ForeignKey("data_items.id", ondelete="CASCADE"), nullable=True
    )
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)


class MemoryFile(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "memory_files"

    memory_id: Mapped[str] = mapped_column(
        ForeignKey("memories.id", ondelete="CASCADE"), nullable=False
    )
    data_item_id: Mapped[str] = mapped_column(
        ForeignKey("data_items.id", ondelete="CASCADE"), nullable=False
    )


class MemoryEvidence(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "memory_evidences"

    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    memory_id: Mapped[str] = mapped_column(
        ForeignKey("memories.id", ondelete="CASCADE"), nullable=False
    )
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    message_id: Mapped[str | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    message_role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    data_item_id: Mapped[str | None] = mapped_column(
        ForeignKey("data_items.id", ondelete="SET NULL"), nullable=True
    )
    episode_id: Mapped[str | None] = mapped_column(
        ForeignKey("memory_episodes.id", ondelete="SET NULL"), nullable=True
    )
    quote_text: Mapped[str] = mapped_column(Text, nullable=False)
    start_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.7, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class MemoryEpisode(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "memory_episodes"

    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    message_id: Mapped[str | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    owner_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    visibility: Mapped[str] = mapped_column(String(20), default="private", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class MemoryWriteRun(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "memory_write_runs"

    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    message_id: Mapped[str | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    extraction_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    consolidation_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class MemoryOutcome(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "memory_outcomes"

    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    message_id: Mapped[str | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    feedback_source: Mapped[str] = mapped_column(String(20), default="system", nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    root_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class MemoryLearningRun(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "memory_learning_runs"

    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    message_id: Mapped[str | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    trigger: Mapped[str] = mapped_column(String(40), default="post_turn", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    stages: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    used_memory_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    promoted_memory_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    degraded_memory_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    outcome_id: Mapped[str | None] = mapped_column(
        ForeignKey("memory_outcomes.id", ondelete="SET NULL"), nullable=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class MemoryWriteItem(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "memory_write_items"

    run_id: Mapped[str] = mapped_column(
        ForeignKey("memory_write_runs.id", ondelete="CASCADE"), nullable=False
    )
    subject_memory_id: Mapped[str | None] = mapped_column(
        ForeignKey("memories.id", ondelete="SET NULL"), nullable=True
    )
    candidate_text: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    proposed_memory_kind: Mapped[str | None] = mapped_column(String(40), nullable=True)
    importance: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    decision: Mapped[str] = mapped_column(String(20), default="create", nullable=False)
    target_memory_id: Mapped[str | None] = mapped_column(
        ForeignKey("memories.id", ondelete="SET NULL"), nullable=True
    )
    predecessor_memory_id: Mapped[str | None] = mapped_column(
        ForeignKey("memories.id", ondelete="SET NULL"), nullable=True
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class MemoryView(Base, UUIDPrimaryKeyMixin, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "memory_views"

    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    source_subject_id: Mapped[str | None] = mapped_column(
        ForeignKey("memories.id", ondelete="SET NULL"), nullable=True
    )
    view_type: Mapped[str] = mapped_column(String(40), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


Index("idx_memories_ws_project", Memory.workspace_id, Memory.project_id)

Index("idx_memories_project_type", Memory.project_id, Memory.type)

Index("idx_memories_project_node_type", Memory.project_id, Memory.node_type)

Index("idx_memories_project_subject", Memory.project_id, Memory.subject_memory_id)

Index(
    "idx_memories_project_canonical",
    Memory.project_id,
    Memory.subject_memory_id,
    Memory.canonical_key,
)

Index("idx_memories_project_validity", Memory.project_id, Memory.valid_from, Memory.valid_to)

Index(
    "idx_memories_project_subject_status_type",
    Memory.project_id,
    Memory.subject_memory_id,
    Memory.node_status,
    Memory.node_type,
)

Index(
    "idx_memories_project_lineage_status", Memory.project_id, Memory.lineage_key, Memory.node_status
)

Index(
    "idx_memories_active_fact_subject",
    Memory.project_id,
    Memory.subject_memory_id,
    postgresql_where=sql_text("node_type = 'fact' AND node_status = 'active'"),
)

Index(
    "idx_memories_active_fact_lineage",
    Memory.project_id,
    Memory.lineage_key,
    postgresql_where=sql_text("node_type = 'fact' AND node_status = 'active'"),
)

Index("idx_memories_source_conv", Memory.source_conversation_id)

Index("idx_embeddings_ws_project", Embedding.workspace_id, Embedding.project_id)

Index("idx_memory_episodes_project_source", MemoryEpisode.project_id, MemoryEpisode.source_type)

Index("idx_memory_episodes_message", MemoryEpisode.message_id)

Index("idx_memory_evidences_memory", MemoryEvidence.memory_id, MemoryEvidence.created_at)

Index("idx_memory_evidences_project_source", MemoryEvidence.project_id, MemoryEvidence.source_type)

Index("idx_memory_evidences_episode", MemoryEvidence.episode_id)

Index("idx_memory_outcomes_project_status", MemoryOutcome.project_id, MemoryOutcome.status)

Index("idx_memory_outcomes_message", MemoryOutcome.message_id)

Index(
    "idx_memory_learning_runs_project_status",
    MemoryLearningRun.project_id,
    MemoryLearningRun.status,
)

Index("idx_memory_learning_runs_message", MemoryLearningRun.message_id)

Index("idx_memory_write_runs_message", MemoryWriteRun.message_id)

Index("idx_memory_write_runs_project_status", MemoryWriteRun.project_id, MemoryWriteRun.status)

Index("idx_memory_write_items_run", MemoryWriteItem.run_id, MemoryWriteItem.created_at)

Index("idx_memory_write_items_target", MemoryWriteItem.target_memory_id)

Index("idx_memory_views_project_type", MemoryView.project_id, MemoryView.view_type)


__all__ = [
    "Memory",
    "MemoryEdge",
    "Embedding",
    "MemoryFile",
    "MemoryEvidence",
    "MemoryEpisode",
    "MemoryWriteRun",
    "MemoryOutcome",
    "MemoryLearningRun",
    "MemoryWriteItem",
    "MemoryView",
]
