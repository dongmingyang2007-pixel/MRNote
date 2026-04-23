"""S7 Search API: global / notebook / related endpoints."""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, Depends
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.deps import (
    get_current_user, get_current_workspace_id, get_current_workspace_role, get_db_session,
    is_workspace_privileged_role,
)
from app.core.errors import ApiError
from app.core.notebook_access import assert_notebook_readable
from app.models import Notebook, NotebookPage, User
from app.schemas.search import RelatedResponse, SearchResponse, SearchResults
from app.services.related_pages import get_related
from app.services.search_dispatcher import SCOPES, search_workspace

router = APIRouter(tags=["search"])


def _get_readable_notebook_or_404(
    db: Session,
    *,
    notebook_id: str,
    workspace_id: str,
    current_user_id: str,
    workspace_role: str,
) -> Notebook:
    notebook = db.query(Notebook).filter(Notebook.id == notebook_id).first()
    assert_notebook_readable(
        notebook,
        workspace_id=workspace_id,
        current_user_id=current_user_id,
        workspace_role=workspace_role,
        not_found_message="Notebook not found",
    )
    return notebook


def _get_readable_page_or_404(
    db: Session,
    *,
    page_id: str,
    workspace_id: str,
    current_user_id: str,
    workspace_role: str,
) -> NotebookPage:
    page = db.query(NotebookPage).filter_by(id=page_id).first()
    if page is None:
        raise ApiError("not_found", "Page not found", status_code=404)
    notebook = db.query(Notebook).filter(Notebook.id == page.notebook_id).first()
    assert_notebook_readable(
        notebook,
        workspace_id=workspace_id,
        current_user_id=current_user_id,
        workspace_role=workspace_role,
        not_found_message="Page not found",
    )
    return page


def _filter_related_pages_for_viewer(
    pages: list[dict[str, object]],
    *,
    db: Session,
    workspace_id: str,
    current_user_id: str,
    workspace_role: str,
) -> list[dict[str, object]]:
    if is_workspace_privileged_role(workspace_role):
        return pages
    readable_notebook_ids = {
        notebook.id
        for notebook in (
            db.query(Notebook)
            .filter(Notebook.workspace_id == workspace_id)
            .filter(
                or_(
                    Notebook.visibility != "private",
                    Notebook.created_by == current_user_id,
                )
            )
            .all()
        )
    }
    return [
        page for page in pages
        if str(page.get("notebook_id") or "") in readable_notebook_ids
    ]


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
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    workspace_role: str = Depends(get_current_workspace_role),
) -> SearchResponse:
    effective_scopes = _parse_scopes(scope)
    limit = max(1, min(limit, 20))
    started = time.monotonic()
    results_dict = asyncio.run(search_workspace(
        db, workspace_id=workspace_id, query=q,
        scopes=effective_scopes, project_id=project_id, limit=limit,
        current_user_id=str(current_user.id),
        workspace_role=workspace_role,
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
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    workspace_role: str = Depends(get_current_workspace_role),
) -> SearchResponse:
    _get_readable_notebook_or_404(
        db,
        notebook_id=notebook_id,
        workspace_id=workspace_id,
        current_user_id=str(current_user.id),
        workspace_role=workspace_role,
    )
    effective_scopes = _parse_scopes(scope)
    limit = max(1, min(limit, 20))
    started = time.monotonic()
    results_dict = asyncio.run(search_workspace(
        db, workspace_id=workspace_id, query=q,
        scopes=effective_scopes, notebook_id=notebook_id, limit=limit,
        current_user_id=str(current_user.id),
        workspace_role=workspace_role,
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
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    workspace_role: str = Depends(get_current_workspace_role),
) -> RelatedResponse:
    _get_readable_page_or_404(
        db,
        page_id=page_id,
        workspace_id=workspace_id,
        current_user_id=str(current_user.id),
        workspace_role=workspace_role,
    )
    limit = max(1, min(limit, 20))
    out = get_related(
        db, page_id=page_id, workspace_id=workspace_id, limit=limit,
    )
    return RelatedResponse(
        pages=_filter_related_pages_for_viewer(
            out["pages"],
            db=db,
            workspace_id=workspace_id,
            current_user_id=str(current_user.id),
            workspace_role=workspace_role,
        ),
        memory=out["memory"],
    )
