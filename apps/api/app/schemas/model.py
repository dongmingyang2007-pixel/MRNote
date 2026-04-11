from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ModelCreate(BaseModel):
    project_id: str
    name: str
    task_type: str = "general"


class ModelOut(BaseModel):
    id: str
    project_id: str
    name: str
    task_type: str
    created_at: datetime
    updated_at: datetime


class ModelVersionCreate(BaseModel):
    run_id: str | None = None
    artifact_upload_id: str | None = None
    metrics_json: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = None


class ModelVersionOut(BaseModel):
    id: str
    model_id: str
    version: int
    run_id: str | None
    metrics_json: dict[str, Any]
    notes: str | None
    artifact_download_url: str | None = None
    artifact_filename: str | None = None
    created_at: datetime


class AliasUpdateRequest(BaseModel):
    alias: Literal["prod", "staging", "dev"]
    model_version_id: str


class RollbackRequest(BaseModel):
    alias: Literal["prod", "staging", "dev"]
    to_model_version_id: str


class ArtifactUploadPresignRequest(BaseModel):
    filename: str
    media_type: str
    size_bytes: int


class ArtifactUploadPresignResponse(BaseModel):
    artifact_upload_id: str
    put_url: str
    headers: dict[str, str]
    fields: dict[str, str] = Field(default_factory=dict)
    upload_method: Literal["PUT", "POST"] = "PUT"
