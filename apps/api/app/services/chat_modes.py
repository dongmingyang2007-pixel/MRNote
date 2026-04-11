from __future__ import annotations

from typing import Literal, cast

from sqlalchemy import text as sql_text
from sqlalchemy.engine import Engine

from app.services.schema_helpers import ensure_column


ChatMode = Literal["standard", "omni_realtime", "synthetic_realtime"]

CHAT_MODES: tuple[ChatMode, ...] = ("standard", "omni_realtime", "synthetic_realtime")
DEFAULT_CHAT_MODE: ChatMode = "standard"


def normalize_chat_mode(value: str | None) -> ChatMode:
    if value in CHAT_MODES:
        return cast(ChatMode, value)
    return DEFAULT_CHAT_MODE


def ensure_project_chat_mode_schema(engine: Engine) -> None:
    ensure_column(
        engine, "projects", "default_chat_mode", "TEXT",
        nullable=False, default="'standard'",
    )
    with engine.begin() as connection:
        connection.execute(
            sql_text(
                "UPDATE projects "
                "SET default_chat_mode = 'standard' "
                "WHERE default_chat_mode IS NULL OR default_chat_mode = ''"
            )
        )
