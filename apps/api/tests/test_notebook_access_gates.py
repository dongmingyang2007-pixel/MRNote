# ruff: noqa: E402
"""Regression tests for A2 (cross-workspace IDOR via notebook-ai / study-ai / decks).

Before the A2 fix, `notebook_ai._get_page_or_404`, `study_ai._load_source_text`,
`study_decks._get_notebook_or_404 / _get_deck_or_404` and the `ask` endpoint's
`notebook_id` branch only enforced `Notebook.workspace_id == workspace_id`. Any
editor/viewer in the same workspace could feed another member's private
notebook / page / chunk / deck / asset id into these endpoints and have its
contents reflected back as AI output (summary, flashcards, quiz, RAG reply) or
deck/card listings.

This file covers the shared visibility gate (`core/notebook_access.py`):
- `visibility="private"` notebooks are only readable by their creator or a
  workspace-privileged role (owner/admin).
- Non-private (shared/public) notebooks remain visible to all members.
- Violations return 404 `not_found`, not 403, so the endpoint doesn't leak
  existence of resources the caller can't touch.
"""
import atexit
import hashlib
import importlib
import os
import shutil
import tempfile
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-a2-idor-"))
atexit.register(lambda: shutil.rmtree(TEST_TEMP_DIR, ignore_errors=True))
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_TEMP_DIR / 'test.db'}"
os.environ["ENV"] = "test"
os.environ["COOKIE_DOMAIN"] = ""
os.environ["DEMO_MODE"] = "true"
os.environ["STRIPE_API_KEY"] = "sk_test_dummy"

import app.core.config as config_module
config_module.get_settings.cache_clear()
config_module.settings = config_module.get_settings()

import app.db.session as session_module
importlib.reload(session_module)

import app.main as main_module
importlib.reload(main_module)

from fastapi.testclient import TestClient

import app.db.session as _s
import app.routers.notebook_ai as notebook_ai_router
import app.routers.study_ai as study_ai_router
import app.routers.study_decks as study_decks_router
from app.db.base import Base
from app.models import (
    Membership,
    Notebook,
    NotebookPage,
    Project,
    StudyAsset,
    StudyCard,
    StudyChunk,
    StudyDeck,
)
from app.services.runtime_state import runtime_state


def setup_function() -> None:
    # Other test files may have reloaded app.db.session after import time,
    # rebinding engine/SessionLocal. Look them up dynamically via `_s.` so
    # setup and the FastAPI app see the same DB.
    Base.metadata.drop_all(bind=_s.engine)
    Base.metadata.create_all(bind=_s.engine)
    runtime_state._memory = runtime_state._memory.__class__()
    # Routers captured `from app.db.session import SessionLocal` at their own
    # import time; reload so every test sees the current SessionLocal.
    importlib.reload(notebook_ai_router)
    importlib.reload(study_ai_router)
    importlib.reload(study_decks_router)
    importlib.reload(main_module)


def _public() -> dict[str, str]:
    return {"origin": "http://localhost:3000"}


def _register(email: str) -> tuple[TestClient, dict[str, str]]:
    client = TestClient(main_module.app)
    client.post(
        "/api/v1/auth/send-code",
        json={"email": email, "purpose": "register"},
        headers=_public(),
    )
    code_key = hashlib.sha256(f"{email.lower().strip()}:register".encode()).hexdigest()
    code = str(runtime_state.get_json("verify_code", code_key)["code"])
    info = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "pass1234pass",
            "display_name": "Test",
            "code": code,
        },
        headers=_public(),
    ).json()
    csrf = client.get("/api/v1/auth/csrf", headers=_public()).json()["csrf_token"]
    client.headers.update({
        "origin": "http://localhost:3000",
        "x-csrf-token": csrf,
        "x-workspace-id": info["workspace"]["id"],
    })
    return client, {"ws_id": info["workspace"]["id"], "user_id": info["user"]["id"]}


def _seed_owner_private_notebook(owner_ws: str, owner_uid: str) -> dict[str, str]:
    """Create a private notebook owned by `owner_uid` with a page, chunk asset
    and deck/card. Returns all ids so tests can probe them from other users.
    """
    with _s.SessionLocal() as db:
        project = Project(workspace_id=owner_ws, name="P")
        db.add(project); db.commit(); db.refresh(project)

        nb = Notebook(
            workspace_id=owner_ws,
            project_id=project.id,
            created_by=owner_uid,
            title="Owner private NB",
            slug="owner-private-nb",
            visibility="private",
        )
        db.add(nb); db.commit(); db.refresh(nb)

        page = NotebookPage(
            notebook_id=nb.id,
            created_by=owner_uid,
            title="Secret page",
            slug="secret-page",
            plain_text="highly sensitive payload that must never leak",
        )
        db.add(page); db.commit(); db.refresh(page)

        asset = StudyAsset(
            notebook_id=nb.id,
            title="Secret study asset",
            asset_type="pdf",
            status="ready",
            total_chunks=1,
            created_by=owner_uid,
        )
        db.add(asset); db.commit(); db.refresh(asset)

        chunk = StudyChunk(
            asset_id=asset.id,
            chunk_index=0,
            heading="",
            content="chunk-level private content",
        )
        db.add(chunk); db.commit(); db.refresh(chunk)

        deck = StudyDeck(
            notebook_id=nb.id,
            name="Owner private deck",
            description="",
            created_by=owner_uid,
            card_count=1,
        )
        db.add(deck); db.commit(); db.refresh(deck)

        card = StudyCard(
            deck_id=deck.id,
            front="Q",
            back="A",
            source_type="manual",
            source_ref=None,
        )
        db.add(card); db.commit(); db.refresh(card)

        return {
            "project_id": project.id,
            "notebook_id": nb.id,
            "page_id": page.id,
            "asset_id": asset.id,
            "chunk_id": chunk.id,
            "deck_id": deck.id,
            "card_id": card.id,
        }


def _seed_owner_shared_notebook(owner_ws: str, owner_uid: str) -> dict[str, str]:
    """Create a shared (visibility=workspace) notebook for positive tests."""
    with _s.SessionLocal() as db:
        project = Project(workspace_id=owner_ws, name="Shared P")
        db.add(project); db.commit(); db.refresh(project)

        nb = Notebook(
            workspace_id=owner_ws,
            project_id=project.id,
            created_by=owner_uid,
            title="Owner shared NB",
            slug="owner-shared-nb",
            visibility="workspace",
        )
        db.add(nb); db.commit(); db.refresh(nb)

        page = NotebookPage(
            notebook_id=nb.id,
            created_by=owner_uid,
            title="Shared page",
            slug="shared-page",
            plain_text="shared text that editors may read",
        )
        db.add(page); db.commit(); db.refresh(page)

        return {
            "project_id": project.id,
            "notebook_id": nb.id,
            "page_id": page.id,
        }


def _join_workspace(target_ws: str, joiner_uid: str, role: str = "editor") -> None:
    """Give `joiner_uid` a Membership in `target_ws` with the given role."""
    with _s.SessionLocal() as db:
        db.add(Membership(
            workspace_id=target_ws, user_id=joiner_uid, role=role,
        ))
        db.commit()


def _stub_llm(monkeypatch) -> None:
    """Block tests from making real dashscope calls even on the happy path."""
    async def _fake_chat_completion(messages, *args, **kwargs):
        return '{"cards":[{"front":"Q","back":"A"}]}'
    monkeypatch.setattr(study_ai_router, "_run_llm_json", _fake_chat_completion)

    async def _fake_stream(messages, *args, **kwargs):
        from app.services.dashscope_stream import StreamChunk
        yield StreamChunk(content="ok", usage=None, model_id=None)
    monkeypatch.setattr(
        "app.services.dashscope_stream.chat_completion_stream",
        _fake_stream,
    )


# ---------------------------------------------------------------------------
# notebook_ai — page_id + notebook_id paths
# ---------------------------------------------------------------------------


def test_editor_cannot_page_action_on_owners_private_page(monkeypatch) -> None:
    """An editor in the owner's workspace must get 404 when feeding a private
    page id to /ai/notebook/page-action — the endpoint must not summarize
    someone else's notebook body back to them."""
    _stub_llm(monkeypatch)

    _owner_client, owner = _register("a2-owner-1@x.co")
    editor_client, editor = _register("a2-editor-1@x.co")
    ids = _seed_owner_private_notebook(owner["ws_id"], owner["user_id"])
    _join_workspace(owner["ws_id"], editor["user_id"], role="editor")
    editor_client.headers["x-workspace-id"] = owner["ws_id"]

    resp = editor_client.post(
        "/api/v1/ai/notebook/page-action",
        json={"page_id": ids["page_id"], "action_type": "summarize"},
    )
    assert resp.status_code == 404, resp.text
    assert resp.json().get("error", {}).get("code") == "not_found"


def test_editor_cannot_selection_action_on_owners_private_page(monkeypatch) -> None:
    _stub_llm(monkeypatch)

    _owner_client, owner = _register("a2-owner-sel@x.co")
    editor_client, editor = _register("a2-editor-sel@x.co")
    ids = _seed_owner_private_notebook(owner["ws_id"], owner["user_id"])
    _join_workspace(owner["ws_id"], editor["user_id"], role="editor")
    editor_client.headers["x-workspace-id"] = owner["ws_id"]

    resp = editor_client.post(
        "/api/v1/ai/notebook/selection-action",
        json={
            "page_id": ids["page_id"],
            "selected_text": "probe",
            "action_type": "rewrite",
        },
    )
    assert resp.status_code == 404, resp.text
    assert resp.json().get("error", {}).get("code") == "not_found"


def test_editor_cannot_ask_notebook_id_visibility_gated(monkeypatch) -> None:
    """The `ask` endpoint's `notebook_id`-only branch (no page_id) used to skip
    the visibility check entirely. Must now 404 for non-owners."""
    _stub_llm(monkeypatch)

    _owner_client, owner = _register("a2-owner-ask@x.co")
    editor_client, editor = _register("a2-editor-ask@x.co")
    ids = _seed_owner_private_notebook(owner["ws_id"], owner["user_id"])
    _join_workspace(owner["ws_id"], editor["user_id"], role="editor")
    editor_client.headers["x-workspace-id"] = owner["ws_id"]

    resp = editor_client.post(
        "/api/v1/ai/notebook/ask",
        json={"notebook_id": ids["notebook_id"], "message": "reveal contents"},
    )
    assert resp.status_code == 404, resp.text
    assert resp.json().get("error", {}).get("code") == "not_found"


def test_editor_cannot_whiteboard_summarize_owners_private_page(monkeypatch) -> None:
    _stub_llm(monkeypatch)

    _owner_client, owner = _register("a2-owner-wb@x.co")
    editor_client, editor = _register("a2-editor-wb@x.co")
    ids = _seed_owner_private_notebook(owner["ws_id"], owner["user_id"])
    _join_workspace(owner["ws_id"], editor["user_id"], role="editor")
    editor_client.headers["x-workspace-id"] = owner["ws_id"]

    resp = editor_client.post(
        "/api/v1/ai/notebook/whiteboard-summarize",
        json={"page_id": ids["page_id"], "elements": []},
    )
    assert resp.status_code == 404, resp.text
    assert resp.json().get("error", {}).get("code") == "not_found"


# ---------------------------------------------------------------------------
# study_ai — page / chunk / asset paths
# ---------------------------------------------------------------------------


def test_editor_cannot_study_flashcards_from_owners_page(monkeypatch) -> None:
    _stub_llm(monkeypatch)

    _owner_client, owner = _register("a2-owner-fc@x.co")
    editor_client, editor = _register("a2-editor-fc@x.co")
    ids = _seed_owner_private_notebook(owner["ws_id"], owner["user_id"])
    _join_workspace(owner["ws_id"], editor["user_id"], role="editor")
    editor_client.headers["x-workspace-id"] = owner["ws_id"]

    resp = editor_client.post(
        "/api/v1/ai/study/flashcards",
        json={
            "source_type": "page",
            "source_id": ids["page_id"],
            "count": 3,
        },
    )
    assert resp.status_code == 404, resp.text
    assert resp.json().get("error", {}).get("code") == "not_found"


def test_editor_cannot_study_flashcards_from_owners_chunk(monkeypatch) -> None:
    _stub_llm(monkeypatch)

    _owner_client, owner = _register("a2-owner-fcch@x.co")
    editor_client, editor = _register("a2-editor-fcch@x.co")
    ids = _seed_owner_private_notebook(owner["ws_id"], owner["user_id"])
    _join_workspace(owner["ws_id"], editor["user_id"], role="editor")
    editor_client.headers["x-workspace-id"] = owner["ws_id"]

    resp = editor_client.post(
        "/api/v1/ai/study/flashcards",
        json={
            "source_type": "chunk",
            "source_id": ids["chunk_id"],
            "count": 3,
        },
    )
    assert resp.status_code == 404, resp.text
    assert resp.json().get("error", {}).get("code") == "not_found"


def test_editor_cannot_study_ask_from_owners_asset(monkeypatch) -> None:
    _stub_llm(monkeypatch)

    _owner_client, owner = _register("a2-owner-sa@x.co")
    editor_client, editor = _register("a2-editor-sa@x.co")
    ids = _seed_owner_private_notebook(owner["ws_id"], owner["user_id"])
    _join_workspace(owner["ws_id"], editor["user_id"], role="editor")
    editor_client.headers["x-workspace-id"] = owner["ws_id"]

    resp = editor_client.post(
        "/api/v1/ai/study/ask",
        json={"asset_id": ids["asset_id"], "message": "reveal"},
    )
    assert resp.status_code == 404, resp.text
    assert resp.json().get("error", {}).get("code") == "not_found"


# ---------------------------------------------------------------------------
# study_decks — deck / cards / create_card
# ---------------------------------------------------------------------------


def test_editor_cannot_read_owners_deck() -> None:
    _owner_client, owner = _register("a2-owner-gd@x.co")
    editor_client, editor = _register("a2-editor-gd@x.co")
    ids = _seed_owner_private_notebook(owner["ws_id"], owner["user_id"])
    _join_workspace(owner["ws_id"], editor["user_id"], role="editor")
    editor_client.headers["x-workspace-id"] = owner["ws_id"]

    resp = editor_client.get(f"/api/v1/decks/{ids['deck_id']}")
    assert resp.status_code == 404, resp.text
    assert resp.json().get("error", {}).get("code") == "not_found"


def test_editor_cannot_read_owners_deck_cards() -> None:
    _owner_client, owner = _register("a2-owner-dc@x.co")
    editor_client, editor = _register("a2-editor-dc@x.co")
    ids = _seed_owner_private_notebook(owner["ws_id"], owner["user_id"])
    _join_workspace(owner["ws_id"], editor["user_id"], role="editor")
    editor_client.headers["x-workspace-id"] = owner["ws_id"]

    resp = editor_client.get(f"/api/v1/decks/{ids['deck_id']}/cards")
    assert resp.status_code == 404, resp.text
    assert resp.json().get("error", {}).get("code") == "not_found"


def test_editor_cannot_create_card_in_owners_deck() -> None:
    _owner_client, owner = _register("a2-owner-cc@x.co")
    editor_client, editor = _register("a2-editor-cc@x.co")
    ids = _seed_owner_private_notebook(owner["ws_id"], owner["user_id"])
    _join_workspace(owner["ws_id"], editor["user_id"], role="editor")
    editor_client.headers["x-workspace-id"] = owner["ws_id"]

    resp = editor_client.post(
        f"/api/v1/decks/{ids['deck_id']}/cards",
        json={"front": "F", "back": "B", "source_type": "manual"},
    )
    assert resp.status_code == 404, resp.text
    assert resp.json().get("error", {}).get("code") == "not_found"


def test_editor_cannot_list_decks_in_owners_private_notebook() -> None:
    _owner_client, owner = _register("a2-owner-ld@x.co")
    editor_client, editor = _register("a2-editor-ld@x.co")
    ids = _seed_owner_private_notebook(owner["ws_id"], owner["user_id"])
    _join_workspace(owner["ws_id"], editor["user_id"], role="editor")
    editor_client.headers["x-workspace-id"] = owner["ws_id"]

    resp = editor_client.get(f"/api/v1/notebooks/{ids['notebook_id']}/decks")
    assert resp.status_code == 404, resp.text
    assert resp.json().get("error", {}).get("code") == "not_found"


# ---------------------------------------------------------------------------
# Positive: owner on own resource, editor on shared resource
# ---------------------------------------------------------------------------


def test_owner_can_access_own_private_page(monkeypatch) -> None:
    _stub_llm(monkeypatch)

    owner_client, owner = _register("a2-owner-ok@x.co")
    ids = _seed_owner_private_notebook(owner["ws_id"], owner["user_id"])
    owner_client.headers["x-workspace-id"] = owner["ws_id"]

    # Flashcards is non-streaming and cleanly returns 200 when LLM is stubbed.
    resp = owner_client.post(
        "/api/v1/ai/study/flashcards",
        json={
            "source_type": "page",
            "source_id": ids["page_id"],
            "count": 1,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "cards" in body and body["cards"]


def test_editor_can_access_workspace_visible_notebook(monkeypatch) -> None:
    """Positive regression: when the owner sets visibility != private, the
    editor is allowed. Confirms the gate blocks only the private case."""
    _stub_llm(monkeypatch)

    _owner_client, owner = _register("a2-owner-vis@x.co")
    editor_client, editor = _register("a2-editor-vis@x.co")
    ids = _seed_owner_shared_notebook(owner["ws_id"], owner["user_id"])
    _join_workspace(owner["ws_id"], editor["user_id"], role="editor")
    editor_client.headers["x-workspace-id"] = owner["ws_id"]

    resp = editor_client.post(
        "/api/v1/ai/study/flashcards",
        json={
            "source_type": "page",
            "source_id": ids["page_id"],
            "count": 1,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "cards" in body and body["cards"]
