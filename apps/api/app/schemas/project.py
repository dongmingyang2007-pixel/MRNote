from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class ProjectCreate(BaseModel):
    name: str
    description: str | None = None
    default_chat_mode: Literal["standard", "omni_realtime", "synthetic_realtime"] = "standard"


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    default_chat_mode: Literal["standard", "omni_realtime", "synthetic_realtime"] | None = None


class ProjectOut(BaseModel):
    id: str
    workspace_id: str
    name: str
    description: str | None
    default_chat_mode: Literal["standard", "omni_realtime", "synthetic_realtime"]
    assistant_root_memory_id: str | None
    cleanup_status: str
    created_at: datetime
    updated_at: datetime


class PaginatedProjects(BaseModel):
    items: list[ProjectOut]
    total: int
