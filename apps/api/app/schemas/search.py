from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class SearchResults(BaseModel):
    pages: list[dict[str, Any]] = []
    blocks: list[dict[str, Any]] = []
    study_assets: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    memory: list[dict[str, Any]] = []
    playbooks: list[dict[str, Any]] = []
    ai_actions: list[dict[str, Any]] = []


class SearchResponse(BaseModel):
    query: str
    duration_ms: int
    results: SearchResults


class RelatedResponse(BaseModel):
    pages: list[dict[str, Any]] = []
    memory: list[dict[str, Any]] = []
