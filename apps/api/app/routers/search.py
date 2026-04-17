"""S7 Search API: global / notebook / related endpoints."""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import (
    get_current_user, get_current_workspace_id, get_db_session,
)
from app.core.errors import ApiError
from app.models import Notebook, NotebookPage, User
from app.schemas.search import RelatedResponse, SearchResponse, SearchResults
from app.services.related_pages import get_related
from app.services.search_dispatcher import SCOPES, search_workspace

router = APIRouter(tags=["search"])


def _parse_scopes(raw: str | None) -> set[str]:
    if not raw:
        return set(SCOPES)
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    bad = [p for p in parts if p not in SCOPES]
    if bad:
        raise ApiError(
            "invalid_input", f"Unknown scope(s): {', '.join(bad)}",
            status_code=400,
        )
    return set(parts)


@router.get("/api/v1/search/global", response_model=SearchResponse)
def global_search(
    q: str,
    scope: str | None = None,
    project_id: str | None = None,
    limit: int = 8,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),  # noqa: ARG001
    workspace_id: str = Depends(get_current_workspace_id),
) -> SearchResponse:
    effective_scopes = _parse_scopes(scope)
    limit = max(1, min(limit, 20))
    started = time.monotonic()
    results_dict = asyncio.run(search_workspace(
        db, workspace_id=workspace_id, query=q,
        scopes=effective_scopes, project_id=project_id, limit=limit,
    ))
    duration_ms = int((time.monotonic() - started) * 1000)
    return SearchResponse(
        query=q, duration_ms=duration_ms,
        results=SearchResults(**results_dict),
    )


@router.get(
    "/api/v1/notebooks/{notebook_id}/search", response_model=SearchResponse,
)
def notebook_search(
    notebook_id: str,
    q: str,
    scope: str | None = None,
    limit: int = 8,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),  # noqa: ARG001
    workspace_id: str = Depends(get_current_workspace_id),
) -> SearchResponse:
    nb = db.query(Notebook).filter_by(id=notebook_id).first()
    if nb is None or nb.workspace_id != workspace_id:
        raise ApiError("not_found", "Notebook not found", status_code=404)
    effective_scopes = _parse_scopes(scope)
    limit = max(1, min(limit, 20))
    started = time.monotonic()
    results_dict = asyncio.run(search_workspace(
        db, workspace_id=workspace_id, query=q,
        scopes=effective_scopes, notebook_id=notebook_id, limit=limit,
    ))
    duration_ms = int((time.monotonic() - started) * 1000)
    return SearchResponse(
        query=q, duration_ms=duration_ms,
        results=SearchResults(**results_dict),
    )


@router.get("/api/v1/pages/{page_id}/related", response_model=RelatedResponse)
def page_related(
    page_id: str,
    limit: int = 5,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),  # noqa: ARG001
    workspace_id: str = Depends(get_current_workspace_id),
) -> RelatedResponse:
    page = db.query(NotebookPage).filter_by(id=page_id).first()
    if page is None:
        raise ApiError("not_found", "Page not found", status_code=404)
    nb = db.query(Notebook).filter_by(id=page.notebook_id).first()
    if nb is None or nb.workspace_id != workspace_id:
        raise ApiError("not_found", "Page not found", status_code=404)
    limit = max(1, min(limit, 20))
    out = get_related(
        db, page_id=page_id, workspace_id=workspace_id, limit=limit,
    )
    return RelatedResponse(pages=out["pages"], memory=out["memory"])
