"""S1: AI Action Log + Usage Event context manager."""

from __future__ import annotations

import json
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from botocore.exceptions import ClientError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import AIActionLog, AIUsageEvent
from app.services import storage as storage_service

logger = logging.getLogger(__name__)


@dataclass
class _UsageBuffer:
    event_type: str
    model_id: str | None
    prompt_tokens: int
    completion_tokens: int
    audio_seconds: float
    file_count: int
    count_source: str
    meta: dict[str, Any]


OVERFLOW_THRESHOLD_BYTES = 10 * 1024
OVERFLOW_PREVIEW_CHARS = 500


def _json_size_bytes(payload: Any) -> int:
    return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def _ensure_bucket(bucket: str) -> None:
    client = storage_service.get_s3_client()
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("404", "NoSuchBucket", "NotFound"):
            client.create_bucket(Bucket=bucket)
        else:
            raise


def _overflow_key(workspace_id: str, log_id: str, field: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"{workspace_id}/{ts}/{log_id}-{field}.json"


def _maybe_overflow(
    payload: dict[str, Any],
    *,
    workspace_id: str,
    log_id: str,
    field: str,
) -> dict[str, Any]:
    if _json_size_bytes(payload) <= OVERFLOW_THRESHOLD_BYTES:
        return payload
    bucket = settings.s3_ai_action_payloads_bucket
    key = _overflow_key(workspace_id, log_id, field)
    try:
        _ensure_bucket(bucket)
        client = storage_service.get_s3_client()
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            ContentType="application/json",
        )
    except Exception:
        logger.exception("ai_action_logger: overflow upload failed; storing inline")
        return payload
    preview_src = json.dumps(payload, ensure_ascii=False)
    return {
        "_overflow_ref": key,
        "_preview": preview_src[:OVERFLOW_PREVIEW_CHARS],
    }


class ActionLogHandle:
    """Public handle for the in-progress action log."""

    def __init__(
        self,
        *,
        db: Session,
        log_id: str,
        workspace_id: str,
        start_monotonic: float,
    ) -> None:
        self._db = db
        self._log_id = log_id
        self._workspace_id = workspace_id
        self._start = start_monotonic
        self._input: dict[str, Any] | None = None
        self._output: dict[str, Any] | None = None
        self._output_summary: str = ""
        self._model_id: str | None = None
        self._trace: dict[str, Any] = {}
        self._usage: list[_UsageBuffer] = []

    @property
    def log_id(self) -> str:
        return self._log_id

    @property
    def is_null(self) -> bool:
        return False

    def set_input(self, payload: dict[str, Any]) -> None:
        self._input = dict(payload)

    def set_output(self, content: Any) -> None:
        if isinstance(content, str):
            self._output = {"content": content}
            self._output_summary = content[:200]
        else:
            self._output = dict(content) if isinstance(content, dict) else {"value": content}
            preview_src = self._output.get("content") or self._output.get("value") or ""
            self._output_summary = str(preview_src)[:200]

    def record_usage(
        self,
        *,
        event_type: str,
        model_id: str | None = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        audio_seconds: float = 0.0,
        file_count: int = 0,
        count_source: str = "exact",
        meta: dict[str, Any] | None = None,
    ) -> None:
        self._usage.append(_UsageBuffer(
            event_type=event_type,
            model_id=model_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            audio_seconds=audio_seconds,
            file_count=file_count,
            count_source=count_source,
            meta=dict(meta or {}),
        ))
        if model_id and not self._model_id:
            self._model_id = model_id

    def set_trace_metadata(self, data: dict[str, Any]) -> None:
        self._trace.update(data)

    def _duration_ms(self) -> int:
        return int((time.monotonic() - self._start) * 1000)

    def _flush_success(self) -> None:
        row = self._db.query(AIActionLog).filter_by(id=self._log_id).one()
        row.status = "completed"
        row.duration_ms = self._duration_ms()
        if self._input is not None:
            row.input_json = _maybe_overflow(
                self._input, workspace_id=self._workspace_id,
                log_id=self._log_id, field="input",
            )
        if self._output is not None:
            row.output_json = _maybe_overflow(
                self._output, workspace_id=self._workspace_id,
                log_id=self._log_id, field="output",
            )
        row.output_summary = self._output_summary
        row.model_id = self._model_id
        row.trace_metadata = dict(self._trace)
        self._db.add(row)
        for buf in self._usage:
            self._db.add(AIUsageEvent(
                workspace_id=row.workspace_id,
                user_id=row.user_id,
                action_log_id=row.id,
                event_type=buf.event_type,
                model_id=buf.model_id,
                prompt_tokens=buf.prompt_tokens,
                completion_tokens=buf.completion_tokens,
                total_tokens=buf.prompt_tokens + buf.completion_tokens,
                audio_seconds=buf.audio_seconds,
                file_count=buf.file_count,
                count_source=buf.count_source,
                meta_json=buf.meta,
            ))
        self._db.commit()

    def _flush_failure(self, exc: BaseException) -> None:
        row = self._db.query(AIActionLog).filter_by(id=self._log_id).one()
        row.status = "failed"
        row.duration_ms = self._duration_ms()
        row.error_code = type(exc).__name__[:50]
        row.error_message = str(exc)[:2000]
        if self._input is not None:
            row.input_json = _maybe_overflow(
                self._input, workspace_id=self._workspace_id,
                log_id=self._log_id, field="input",
            )
        if self._output is not None:
            row.output_json = _maybe_overflow(
                self._output, workspace_id=self._workspace_id,
                log_id=self._log_id, field="output",
            )
        row.output_summary = self._output_summary
        row.trace_metadata = dict(self._trace)
        self._db.add(row)
        self._db.commit()


class NullActionLogHandle:
    """Safe no-op handle returned when the DB cannot accept the log row."""

    @property
    def log_id(self) -> str:
        return ""

    @property
    def is_null(self) -> bool:
        return True

    def set_input(self, payload: dict[str, Any]) -> None:
        return None

    def set_output(self, content: Any) -> None:
        return None

    def record_usage(self, **_: Any) -> None:
        return None

    def set_trace_metadata(self, data: dict[str, Any]) -> None:
        return None


@asynccontextmanager
async def action_log_context(
    db: Session,
    *,
    workspace_id: str,
    user_id: str,
    action_type: str,
    scope: str,
    notebook_id: str | None = None,
    page_id: str | None = None,
    block_id: str | None = None,
) -> AsyncIterator["ActionLogHandle | NullActionLogHandle"]:
    start = time.monotonic()
    try:
        row = AIActionLog(
            workspace_id=workspace_id,
            user_id=user_id,
            notebook_id=notebook_id,
            page_id=page_id,
            block_id=block_id,
            action_type=action_type,
            scope=scope,
            status="running",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
    except Exception:
        logger.exception("ai_action_logger: enter failed, returning null handle")
        try:
            db.rollback()
        except Exception:  # pragma: no cover
            pass
        yield NullActionLogHandle()
        return

    handle = ActionLogHandle(
        db=db, log_id=row.id,
        workspace_id=workspace_id,
        start_monotonic=start,
    )
    try:
        yield handle
    except BaseException as exc:
        try:
            handle._flush_failure(exc)
        except Exception:  # pragma: no cover
            logger.exception("ai_action_logger: flush_failure failed")
        raise
    else:
        try:
            handle._flush_success()
        except Exception:
            logger.exception("ai_action_logger: flush_success failed")
