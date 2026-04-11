from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import AliasChoices, BaseModel, Field, field_validator


class MemoryCreate(BaseModel):
    project_id: str
    content: str
    category: str = ""
    type: str = "permanent"
    node_type: str | None = None
    subject_kind: str | None = None
    subject_memory_id: str | None = None
    node_status: str | None = None
    canonical_key: str | None = None
    source_conversation_id: str | None = None
    parent_memory_id: str | None = None
    position_x: float | None = None
    position_y: float | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class MemoryUpdate(BaseModel):
    content: str | None = None
    category: str | None = None
    node_type: str | None = None
    subject_kind: str | None = None
    subject_memory_id: str | None = None
    node_status: str | None = None
    canonical_key: str | None = None
    parent_memory_id: str | None = None
    position_x: float | None = None
    position_y: float | None = None
    metadata_json: dict[str, Any] | None = None


class MemoryOut(BaseModel):
    id: str
    workspace_id: str
    project_id: str
    content: str
    category: str
    type: str
    node_type: str | None = None
    subject_kind: str | None = None
    subject_memory_id: str | None = None
    node_status: str | None = None
    canonical_key: str | None = None
    lineage_key: str | None = None
    confidence: float = 0.7
    observed_at: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    last_confirmed_at: datetime | None = None
    suppression_reason: str | None = None
    reconfirm_after: datetime | None = None
    last_used_at: datetime | None = None
    reuse_success_rate: float | None = None
    source_conversation_id: str | None
    parent_memory_id: str | None
    position_x: float | None
    position_y: float | None
    metadata_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class MemoryEdgeCreate(BaseModel):
    source_memory_id: str
    target_memory_id: str
    edge_type: str = "manual"
    strength: float = 0.5


class MemoryEdgeOut(BaseModel):
    id: str
    source_memory_id: str
    target_memory_id: str
    edge_type: str
    strength: float
    confidence: float = 0.5
    observed_at: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class MemoryFileOut(BaseModel):
    id: str
    memory_id: str
    data_item_id: str
    filename: str | None = None
    media_type: str | None = None
    created_at: datetime


class MemoryEvidenceOut(BaseModel):
    id: str
    memory_id: str
    source_type: str
    conversation_id: str | None = None
    message_id: str | None = None
    message_role: str | None = None
    data_item_id: str | None = None
    episode_id: str | None = None
    quote_text: str
    start_offset: int | None = None
    end_offset: int | None = None
    chunk_id: str | None = None
    confidence: float = 0.7
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class MemoryEpisodeOut(BaseModel):
    id: str
    workspace_id: str
    project_id: str
    conversation_id: str | None = None
    message_id: str | None = None
    source_type: str
    source_id: str | None = None
    chunk_text: str
    owner_user_id: str | None = None
    visibility: str
    started_at: datetime | None = None
    ended_at: datetime | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class MemoryOutcomeCreate(BaseModel):
    project_id: str
    task_id: str | None = None
    status: str
    feedback_source: str = "system"
    summary: str | None = None
    root_cause: str | None = None
    tags: list[str] = Field(default_factory=list)
    conversation_id: str | None = None
    message_id: str | None = None
    memory_ids: list[str] = Field(default_factory=list)
    playbook_view_id: str | None = None
    learning_run_id: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class MemoryOutcomeOut(BaseModel):
    id: str
    workspace_id: str
    project_id: str
    conversation_id: str | None = None
    message_id: str | None = None
    task_id: str | None = None
    status: str
    feedback_source: str
    summary: str | None = None
    root_cause: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class MemoryLearningRunOut(BaseModel):
    id: str
    workspace_id: str
    project_id: str
    conversation_id: str | None = None
    message_id: str | None = None
    task_id: str | None = None
    trigger: str
    status: str
    stages: list[str] = Field(default_factory=list)
    used_memory_ids: list[str] = Field(default_factory=list)
    promoted_memory_ids: list[str] = Field(default_factory=list)
    degraded_memory_ids: list[str] = Field(default_factory=list)
    outcome_id: str | None = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class MessageMemoryLearningOut(BaseModel):
    runs: list["MemoryLearningRunOut"] = Field(default_factory=list)
    outcomes: list["MemoryOutcomeOut"] = Field(default_factory=list)


class PlaybookFeedbackRequest(BaseModel):
    status: str
    root_cause: str | None = None
    task_id: str | None = None
    project_id: str
    conversation_id: str | None = None
    message_id: str | None = None
    memory_ids: list[str] = Field(default_factory=list)
    learning_run_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class MemoryHealthEntryOut(BaseModel):
    kind: str
    memory: MemoryOut | None = None
    view: MemoryViewOut | None = None
    reason: str


class MemoryHealthOut(BaseModel):
    counts: dict[str, int] = Field(default_factory=dict)
    entries: list["MemoryHealthEntryOut"] = Field(default_factory=list)


class MemoryFileAttachRequest(BaseModel):
    data_item_id: str


class MemoryFileCandidateOut(BaseModel):
    id: str
    dataset_id: str
    filename: str
    media_type: str
    created_at: datetime


class MemoryDetailOut(MemoryOut):
    edges: list[MemoryEdgeOut] = []
    files: list[MemoryFileOut] = []
    lineage_nodes: list[MemoryOut] = []
    lineage_edges: list[MemoryEdgeOut] = []
    evidences: list[MemoryEvidenceOut] = []
    episodes: list["MemoryEpisodeOut"] = []
    views: list["MemoryViewOut"] = []
    timeline_events: list["MemoryOut"] = []
    write_history: list["MemoryWriteItemOut"] = []
    learning_history: list["MemoryLearningRunOut"] = []


class MemoryGraphOut(BaseModel):
    nodes: list[MemoryOut]
    edges: list[MemoryEdgeOut]


class MemorySearchRequest(BaseModel):
    project_id: str
    query: str
    top_k: int = Field(default=10, ge=1, le=20, validation_alias=AliasChoices("top_k", "limit"))
    category: str | None = None
    type: str | None = None

    @field_validator("query")
    @classmethod
    def _trim_query(cls, value: str) -> str:
        return value.strip()


class MemorySearchResult(BaseModel):
    memory: MemoryOut
    score: float
    chunk_text: str


class MemoryViewOut(BaseModel):
    id: str
    source_subject_id: str | None = None
    view_type: str
    content: str
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class MemoryWriteRunOut(BaseModel):
    id: str
    workspace_id: str
    project_id: str
    conversation_id: str | None = None
    message_id: str | None = None
    status: str
    extraction_model: str | None = None
    consolidation_model: str | None = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class MemoryWriteItemOut(BaseModel):
    id: str
    run_id: str
    subject_memory_id: str | None = None
    candidate_text: str
    category: str
    proposed_memory_kind: str | None = None
    importance: float = 0.0
    decision: str
    target_memory_id: str | None = None
    predecessor_memory_id: str | None = None
    reason: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class MessageMemoryWriteOut(BaseModel):
    run: MemoryWriteRunOut | None = None
    items: list[MemoryWriteItemOut] = Field(default_factory=list)


class MemorySearchHit(BaseModel):
    result_type: str
    score: float
    snippet: str
    memory: MemoryOut | None = None
    view: MemoryViewOut | None = None
    evidence: MemoryEvidenceOut | None = None
    supporting_memory_id: str | None = None
    selection_reason: str | None = None
    suppression_reason: str | None = None
    outcome_weight: float | None = None
    episode_id: str | None = None


class MemoryExplainRequest(BaseModel):
    project_id: str
    query: str
    top_k: int = Field(default=10, ge=1, le=20, validation_alias=AliasChoices("top_k", "limit"))
    conversation_id: str | None = None
    include_subgraph: bool = True

    @field_validator("query")
    @classmethod
    def _trim_explain_query(cls, value: str) -> str:
        return value.strip()


class MemoryExplainOut(BaseModel):
    hits: list[MemorySearchHit] = Field(default_factory=list)
    trace: dict[str, Any] = Field(default_factory=dict)
    suppressed_candidates: list[MemoryOut] = Field(default_factory=list)
    subgraph: "SubgraphOut | None" = None


class MemoryBackfillRequest(BaseModel):
    project_id: str
    limit: int | None = Field(default=None, ge=1, le=5000)


class MemoryBackfillSummaryOut(BaseModel):
    processed_memories: int = 0
    processed_edges: int = 0
    temporal_updated: int = 0
    confidence_updated: int = 0
    edge_fields_updated: int = 0
    evidences_created: int = 0
    message_evidences_created: int = 0
    conversation_evidences_created: int = 0
    manual_evidences_created: int = 0
    subjects_refreshed: int = 0
    profile_views_refreshed: int = 0
    timeline_views_refreshed: int = 0
    playbook_views_refreshed: int = 0
    skipped_structural_memories: int = 0


class MemoryBackfillOut(BaseModel):
    status: str
    job_id: str | None = None
    summary: MemoryBackfillSummaryOut | None = None


class SubjectResolveRequest(BaseModel):
    project_id: str
    query: str
    conversation_id: str | None = None


class SubjectResolveCandidate(BaseModel):
    subject_id: str
    confidence: float
    label: str
    subject_kind: str | None = None
    canonical_key: str | None = None


class SubjectResolveResult(BaseModel):
    primary_subject_id: str | None = None
    subjects: list[SubjectResolveCandidate] = Field(default_factory=list)


class SubjectOverviewOut(BaseModel):
    subject: MemoryOut
    concepts: list[MemoryOut] = Field(default_factory=list)
    facts: list[MemoryOut] = Field(default_factory=list)
    suggested_paths: list[str] = Field(default_factory=list)


class SubgraphRequest(BaseModel):
    query: str = ""
    depth: int = Field(default=2, ge=1, le=4)
    edge_types: list[str] = Field(default_factory=list)


class SubgraphOut(BaseModel):
    nodes: list[MemoryOut] = Field(default_factory=list)
    edges: list[MemoryEdgeOut] = Field(default_factory=list)


class MemorySupersedeRequest(BaseModel):
    content: str
    category: str | None = None
    reason: str | None = None


MemoryDetailOut.model_rebuild()
MessageMemoryLearningOut.model_rebuild()
MemoryHealthEntryOut.model_rebuild()
MemoryExplainOut.model_rebuild()
