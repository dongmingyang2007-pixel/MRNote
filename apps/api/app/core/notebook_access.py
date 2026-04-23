"""Shared notebook visibility + workspace ownership gate.

Factored out of routers/notebooks.py so every router that reaches Notebook /
NotebookPage / StudyDeck / StudyAsset / StudyChunk by id uses the same
`visibility="private" + created_by` rule, not just "same workspace".

A Notebook is readable when BOTH:
  - It belongs to the requested workspace, AND
  - Its visibility is not "private", OR
  - The caller created it, OR
  - The caller holds a workspace-privileged role (owner/admin).

Anything else must 404 (not 403) so the endpoint doesn't leak existence.
"""

from __future__ import annotations

from app.core.deps import is_workspace_privileged_role
from app.core.errors import ApiError


def can_read_notebook(
    notebook,
    *,
    workspace_id: str,
    current_user_id: str,
    workspace_role: str,
) -> bool:
    """Return True iff the current user can read this notebook."""
    if notebook is None:
        return False
    if str(notebook.workspace_id) != str(workspace_id):
        return False
    if (notebook.visibility or "private") != "private":
        return True
    return (
        is_workspace_privileged_role(workspace_role)
        or str(notebook.created_by) == str(current_user_id)
    )


def assert_notebook_readable(
    notebook,
    *,
    workspace_id: str,
    current_user_id: str,
    workspace_role: str,
    not_found_message: str = "Notebook not found",
) -> None:
    """Raise ApiError('not_found', 404) when the notebook is not readable."""
    if not can_read_notebook(
        notebook,
        workspace_id=workspace_id,
        current_user_id=current_user_id,
        workspace_role=workspace_role,
    ):
        raise ApiError("not_found", not_found_message, status_code=404)
