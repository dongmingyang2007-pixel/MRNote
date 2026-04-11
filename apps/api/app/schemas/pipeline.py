from datetime import datetime
from typing import Literal
from typing import Any

from pydantic import BaseModel


class PipelineConfigOut(BaseModel):
    id: str
    project_id: str
    model_type: Literal["llm", "asr", "tts", "vision", "realtime", "realtime_asr", "realtime_tts"]
    model_id: str
    config_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class PipelineConfigUpdate(BaseModel):
    project_id: str
    model_type: Literal["llm", "asr", "tts", "vision", "realtime", "realtime_asr", "realtime_tts"]
    model_id: str
    config_json: dict[str, Any] = {}


class PipelineOut(BaseModel):
    items: list[PipelineConfigOut]
