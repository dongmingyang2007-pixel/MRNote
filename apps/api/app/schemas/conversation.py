from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ConversationCreate(BaseModel):
    project_id: str
    title: str = ""


class ConversationOut(BaseModel):
    id: str
    workspace_id: str
    project_id: str
    title: str
    created_by: str | None
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class MessageCreate(BaseModel):
    content: str
    enable_thinking: bool | None = None
    enable_search: bool | None = None


class MessageOut(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    reasoning_content: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
