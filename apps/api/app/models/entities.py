from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
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


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)


class Workspace(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "workspaces"

    name: Mapped[str] = mapped_column(Text, nullable=False)
    plan: Mapped[str] = mapped_column(Text, default="free", nullable=False)


class Membership(Base, TimestampMixin):
    __tablename__ = "memberships"

    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str] = mapped_column(Text, default="owner", nullable=False)


class Project(Base, UUIDPrimaryKeyMixin, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "projects"

    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_chat_mode: Mapped[str] = mapped_column(Text, default="standard", nullable=False)
    assistant_root_memory_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cleanup_status: Mapped[str] = mapped_column(Text, default="none", nullable=False)


class Dataset(Base, UUIDPrimaryKeyMixin, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "datasets"

    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(Text, default="images", nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cleanup_status: Mapped[str] = mapped_column(Text, default="none", nullable=False)


class DataItem(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "data_items"

    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"))
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    media_type: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(nullable=False, default=0)
    sha256: Mapped[str | None] = mapped_column(Text, nullable=True)
    width: Mapped[int | None] = mapped_column(nullable=True)
    height: Mapped[int | None] = mapped_column(nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(nullable=True)
    meta_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Annotation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "annotations"

    data_item_id: Mapped[str] = mapped_column(ForeignKey("data_items.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class DatasetVersion(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "dataset_versions"
    __table_args__ = (UniqueConstraint("dataset_id", "version", name="uq_dataset_versions_dataset_version"),)

    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(nullable=False)
    commit_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    item_count: Mapped[int] = mapped_column(default=0, nullable=False)
    frozen_item_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class TrainingJob(Base, UUIDPrimaryKeyMixin, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "training_jobs"

    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    dataset_version_id: Mapped[str] = mapped_column(
        ForeignKey("dataset_versions.id", ondelete="RESTRICT"), nullable=False
    )
    recipe: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, default="pending", nullable=False)
    params_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class TrainingRun(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "training_runs"

    training_job_id: Mapped[str] = mapped_column(ForeignKey("training_jobs.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(Text, default="running", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    logs_object_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class Metric(Base):
    __tablename__ = "metrics"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("training_runs.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    step: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Artifact(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "artifacts"

    run_id: Mapped[str] = mapped_column(ForeignKey("training_runs.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    meta_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class Model(Base, UUIDPrimaryKeyMixin, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "models"

    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    task_type: Mapped[str] = mapped_column(Text, default="general", nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ModelVersion(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "model_versions"
    __table_args__ = (UniqueConstraint("model_id", "version", name="uq_model_versions_model_version"),)

    model_id: Mapped[str] = mapped_column(ForeignKey("models.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(nullable=False)
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("training_runs.id", ondelete="SET NULL"), nullable=True
    )
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    artifact_object_key: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ModelAlias(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "model_aliases"
    __table_args__ = (UniqueConstraint("model_id", "alias", name="uq_model_aliases_model_alias"),)

    model_id: Mapped[str] = mapped_column(ForeignKey("models.id", ondelete="CASCADE"), nullable=False)
    alias: Mapped[str] = mapped_column(Text, nullable=False)
    model_version_id: Mapped[str] = mapped_column(
        ForeignKey("model_versions.id", ondelete="RESTRICT"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ApiKey(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "api_keys"

    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    key_hash: Mapped[str] = mapped_column(Text, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    workspace_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True, index=True
    )
    actor_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(Text, nullable=False)
    target_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    meta_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


Index("idx_data_items_dataset", DataItem.dataset_id)
Index("idx_data_items_sha", DataItem.sha256)
Index("idx_annotations_item", Annotation.data_item_id)
Index("idx_dsv_dataset", DatasetVersion.dataset_id)
Index("idx_jobs_project", TrainingJob.project_id)
Index("idx_runs_job", TrainingRun.training_job_id)
Index("idx_metrics_run", Metric.run_id)
Index("idx_artifacts_run", Artifact.run_id)
Index("idx_models_project", Model.project_id)
Index("idx_model_versions_model", ModelVersion.model_id)


class Conversation(Base, UUIDPrimaryKeyMixin, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "conversations"

    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class Message(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "messages"

    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    reasoning_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class Memory(Base, UUIDPrimaryKeyMixin, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "memories"

    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
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
    last_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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

    source_memory_id: Mapped[str] = mapped_column(ForeignKey("memories.id", ondelete="CASCADE"), nullable=False)
    target_memory_id: Mapped[str] = mapped_column(ForeignKey("memories.id", ondelete="CASCADE"), nullable=False)
    edge_type: Mapped[str] = mapped_column(String(20), default="auto", nullable=False)
    strength: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class Embedding(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "embeddings"

    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    memory_id: Mapped[str | None] = mapped_column(ForeignKey("memories.id", ondelete="CASCADE"), nullable=True)
    data_item_id: Mapped[str | None] = mapped_column(ForeignKey("data_items.id", ondelete="CASCADE"), nullable=True)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    # vector column (vector(1024)) is managed via raw SQL; not mapped in ORM


class MemoryFile(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "memory_files"

    memory_id: Mapped[str] = mapped_column(ForeignKey("memories.id", ondelete="CASCADE"), nullable=False)
    data_item_id: Mapped[str] = mapped_column(ForeignKey("data_items.id", ondelete="CASCADE"), nullable=False)


class MemoryEvidence(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "memory_evidences"

    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    memory_id: Mapped[str] = mapped_column(ForeignKey("memories.id", ondelete="CASCADE"), nullable=False)
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

    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
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

    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
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

    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
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

    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
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

    run_id: Mapped[str] = mapped_column(ForeignKey("memory_write_runs.id", ondelete="CASCADE"), nullable=False)
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

    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    source_subject_id: Mapped[str | None] = mapped_column(
        ForeignKey("memories.id", ondelete="SET NULL"), nullable=True
    )
    view_type: Mapped[str] = mapped_column(String(40), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


Index("idx_conversations_ws_project", Conversation.workspace_id, Conversation.project_id)
Index("idx_messages_conv_created", Message.conversation_id, Message.created_at)
Index("idx_memories_ws_project", Memory.workspace_id, Memory.project_id)
Index("idx_memories_project_type", Memory.project_id, Memory.type)
Index("idx_memories_project_node_type", Memory.project_id, Memory.node_type)
Index("idx_memories_project_subject", Memory.project_id, Memory.subject_memory_id)
Index("idx_memories_project_canonical", Memory.project_id, Memory.subject_memory_id, Memory.canonical_key)
Index("idx_memories_project_validity", Memory.project_id, Memory.valid_from, Memory.valid_to)
Index(
    "idx_memories_project_subject_status_type",
    Memory.project_id,
    Memory.subject_memory_id,
    Memory.node_status,
    Memory.node_type,
)
Index("idx_memories_project_lineage_status", Memory.project_id, Memory.lineage_key, Memory.node_status)
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
Index("idx_memory_learning_runs_project_status", MemoryLearningRun.project_id, MemoryLearningRun.status)
Index("idx_memory_learning_runs_message", MemoryLearningRun.message_id)
Index("idx_memory_write_runs_message", MemoryWriteRun.message_id)
Index("idx_memory_write_runs_project_status", MemoryWriteRun.project_id, MemoryWriteRun.status)
Index("idx_memory_write_items_run", MemoryWriteItem.run_id, MemoryWriteItem.created_at)
Index("idx_memory_write_items_target", MemoryWriteItem.target_memory_id)
Index("idx_memory_views_project_type", MemoryView.project_id, MemoryView.view_type)


class ModelCatalog(Base, UUIDPrimaryKeyMixin, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "model_catalog"

    model_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    capabilities: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    context_window: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_output: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    input_price: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    output_price: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class PipelineConfig(Base, UUIDPrimaryKeyMixin, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "pipeline_configs"
    __table_args__ = (UniqueConstraint("project_id", "model_type", name="uq_pipeline_configs_project_type"),)

    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    model_type: Mapped[str] = mapped_column(String(20), nullable=False)
    model_id: Mapped[str] = mapped_column(String(100), nullable=False)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


# ---------------------------------------------------------------------------
# Notebook system
# ---------------------------------------------------------------------------


class Notebook(Base, UUIDPrimaryKeyMixin, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "notebooks"

    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(Text, default="", nullable=False)
    slug: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    icon: Mapped[str | None] = mapped_column(String(100), nullable=True)
    cover_image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    notebook_type: Mapped[str] = mapped_column(String(20), default="personal", nullable=False)
    visibility: Mapped[str] = mapped_column(String(20), default="private", nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class NotebookPage(Base, UUIDPrimaryKeyMixin, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "notebook_pages"

    notebook_id: Mapped[str] = mapped_column(ForeignKey("notebooks.id", ondelete="CASCADE"), index=True)
    parent_page_id: Mapped[str | None] = mapped_column(ForeignKey("notebook_pages.id", ondelete="SET NULL"), nullable=True, index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(Text, default="", nullable=False)
    slug: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    page_type: Mapped[str] = mapped_column(String(20), default="document", nullable=False)
    content_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    plain_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    summary_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    ai_keywords_json: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    ai_status_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_conversation_id: Mapped[str | None] = mapped_column(ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True)


class NotebookBlock(Base, UUIDPrimaryKeyMixin, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "notebook_blocks"

    page_id: Mapped[str] = mapped_column(ForeignKey("notebook_pages.id", ondelete="CASCADE"), index=True)
    block_type: Mapped[str] = mapped_column(String(30), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    content_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    plain_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class NotebookPageVersion(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "notebook_page_versions"
    __table_args__ = (UniqueConstraint("page_id", "version_no", name="uq_page_versions_page_version"),)

    page_id: Mapped[str] = mapped_column(ForeignKey("notebook_pages.id", ondelete="CASCADE"), index=True)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    snapshot_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    source: Mapped[str] = mapped_column(String(20), default="autosave", nullable=False)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class NotebookAttachment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "notebook_attachments"

    page_id: Mapped[str] = mapped_column(ForeignKey("notebook_pages.id", ondelete="CASCADE"), index=True)
    data_item_id: Mapped[str | None] = mapped_column(ForeignKey("data_items.id", ondelete="SET NULL"), nullable=True)
    attachment_type: Mapped[str] = mapped_column(String(20), default="other", nullable=False)
    title: Mapped[str] = mapped_column(Text, default="", nullable=False)
    meta_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class StudyAsset(Base, UUIDPrimaryKeyMixin, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "study_assets"

    notebook_id: Mapped[str] = mapped_column(ForeignKey("notebooks.id", ondelete="CASCADE"), index=True)
    data_item_id: Mapped[str | None] = mapped_column(ForeignKey("data_items.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(Text, default="", nullable=False)
    asset_type: Mapped[str] = mapped_column(String(20), default="pdf", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    total_chunks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))


class StudyChunk(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "study_chunks"

    asset_id: Mapped[str] = mapped_column(ForeignKey("study_assets.id", ondelete="CASCADE"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    heading: Mapped[str] = mapped_column(Text, default="", nullable=False)
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class StudyDeck(Base, UUIDPrimaryKeyMixin, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "study_decks"

    notebook_id: Mapped[str] = mapped_column(
        ForeignKey("notebooks.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    card_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_by: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class StudyCard(Base, UUIDPrimaryKeyMixin, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "study_cards"

    deck_id: Mapped[str] = mapped_column(
        ForeignKey("study_decks.id", ondelete="CASCADE"), index=True
    )
    front: Mapped[str] = mapped_column(Text, nullable=False)
    back: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(
        String(20), default="manual", nullable=False
    )
    source_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    difficulty: Mapped[float] = mapped_column(Float, default=5.0, nullable=False)
    stability: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    last_review_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_review_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    review_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    lapse_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    confusion_memory_written_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AIActionLog(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "ai_action_logs"

    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    notebook_id: Mapped[str | None] = mapped_column(
        ForeignKey("notebooks.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    page_id: Mapped[str | None] = mapped_column(
        ForeignKey("notebook_pages.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    block_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    action_type: Mapped[str] = mapped_column(String(60), nullable=False)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="running", nullable=False)
    model_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    input_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    output_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    output_summary: Mapped[str] = mapped_column(Text, default="", nullable=False)

    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    trace_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class AIUsageEvent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "ai_usage_events"

    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    action_log_id: Mapped[str] = mapped_column(
        ForeignKey("ai_action_logs.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    model_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    audio_seconds: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    file_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    count_source: Mapped[str] = mapped_column(String(10), default="exact", nullable=False)
    meta_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class ProactiveDigest(
    Base, UUIDPrimaryKeyMixin, TimestampMixin, UpdatedAtMixin,
):
    __tablename__ = "proactive_digests"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "kind", "period_start", "series_key",
            name="uq_proactive_digests_project_kind_period_series",
        ),
        CheckConstraint(
            "status IN ('unread','read','dismissed')",
            name="ck_proactive_digests_status",
        ),
    )

    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )

    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    period_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    series_key: Mapped[str] = mapped_column(
        String(64), default="", nullable=False
    )

    title: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    content_markdown: Mapped[str] = mapped_column(Text, default="", nullable=False)
    content_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )

    status: Mapped[str] = mapped_column(
        String(20), default="unread", nullable=False
    )
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    dismissed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    model_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    action_log_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


Index(
    "ix_ai_action_logs_workspace_created",
    AIActionLog.workspace_id,
    AIActionLog.created_at.desc(),
)
Index(
    "ix_ai_action_logs_page_created",
    AIActionLog.page_id,
    AIActionLog.created_at.desc(),
)
Index(
    "ix_ai_action_logs_user_created",
    AIActionLog.user_id,
    AIActionLog.created_at.desc(),
)
Index(
    "ix_ai_usage_events_workspace_created",
    AIUsageEvent.workspace_id,
    AIUsageEvent.created_at.desc(),
)
Index("idx_model_catalog_category", ModelCatalog.category)
Index("idx_model_catalog_provider", ModelCatalog.provider)
Index(
    "ix_study_cards_deck_due",
    StudyCard.deck_id,
    StudyCard.next_review_at.asc(),
)
Index(
    "ix_study_cards_deck_created",
    StudyCard.deck_id,
    StudyCard.created_at.desc(),
)
Index("idx_pipeline_configs_project", PipelineConfig.project_id)
Index(
    "ix_proactive_digests_user_status_created",
    ProactiveDigest.user_id,
    ProactiveDigest.status,
    ProactiveDigest.created_at.desc(),
)
Index(
    "ix_proactive_digests_project_kind_period",
    ProactiveDigest.project_id,
    ProactiveDigest.kind,
    ProactiveDigest.period_start.desc(),
)
