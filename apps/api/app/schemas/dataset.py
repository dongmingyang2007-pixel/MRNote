from datetime import datetime
from typing import Any
from typing import Literal

from pydantic import BaseModel, Field


class DatasetCreate(BaseModel):
    project_id: str
    name: str
    type: str = "images"


class DatasetOut(BaseModel):
    id: str
    project_id: str
    name: str
    type: str
    cleanup_status: str
    created_at: datetime
    updated_at: datetime


class UploadPresignRequest(BaseModel):
    dataset_id: str
    filename: str
    media_type: str
    size_bytes: int


class UploadPresignResponse(BaseModel):
    upload_id: str
    put_url: str
    headers: dict[str, str]
    fields: dict[str, str] = Field(default_factory=dict)
    upload_method: Literal["PUT", "POST"] = "PUT"
    data_item_id: str


class UploadCompleteRequest(BaseModel):
    upload_id: str
    data_item_id: str


class AnnotationCreateRequest(BaseModel):
    type: str
    payload_json: dict[str, Any]


class AnnotationOut(BaseModel):
    id: str
    type: str
    payload_json: dict[str, Any]
    created_at: datetime


class DataItemOut(BaseModel):
    id: str
    dataset_id: str
    filename: str
    media_type: str
    size_bytes: int
    sha256: str | None
    width: int | None
    height: int | None
    meta_json: dict[str, Any]
    preview_url: str | None = None
    download_url: str | None = None
    created_at: datetime
    annotations: list[AnnotationOut] = Field(default_factory=list)


class DatasetCommitRequest(BaseModel):
    commit_message: str | None = None
    freeze_filter: dict[str, Any] | None = None


class DatasetVersionOut(BaseModel):
    id: str
    dataset_id: str
    version: int
    commit_message: str | None
    item_count: int
    frozen_item_ids: list[str]
    created_at: datetime
