# ruff: noqa: E402
"""Regression tests for Wave 2 A5 — backend spec alignment.

Covers spec §5 / §8 / §9 / §11 / §13.3 / §13.4 / §13.5 gaps closed in this
change:

- ``NotebookBlock`` CRUD (create / patch / delete / reorder)
- Page duplicate / move / soft-delete
- Archived-notebook write rejection (HIGH-7)
- DELETE ``/api/v1/pages/{id}/attachments/{att_id}``
- ``notebook/brainstorm`` + ``notebook/generate-page`` standalone endpoints
- ``study-assets/{id}/generate-deck`` stub endpoint
- Retrieval orchestration new layers (memory/search/explain + page history)
- AI ``ask`` endpoint accepts scope parameter
- ``memory/confirm`` writes a ``NotebookSelectionMemoryLink`` row
- ``memory/reject`` downranks fingerprint-matching pending candidates

Test setup mirrors ``test_chat_quota_gates.py``: importlib reload + tempdir
per-file + ``setup_function`` DB reset + ``runtime_state._memory`` reset so
multi-file ``pytest`` runs don't share bleeding state.
"""

import atexit
import hashlib
import importlib
import io
import os
import shutil
import tempfile
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-a5-spec-"))
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
import app.routers.blocks as blocks_router
import app.routers.notebook_ai as notebook_ai_router
import app.routers.notebooks as notebooks_router
import app.routers.study_ai as study_ai_router
from app.db.base import Base
from app.models import (
    Memory,
    MemoryEvidence,
    MemoryWriteItem,
    MemoryWriteRun,
    Notebook,
    NotebookAttachment,
    NotebookPage,
    NotebookPageVersion,
    NotebookSelectionMemoryLink,
    Project,
    StudyAsset,
    StudyChunk,
    StudyDeck,
    Subscription,
)
from app.services.runtime_state import runtime_state


def setup_function() -> None:
    Base.metadata.drop_all(bind=_s.engine)
    Base.metadata.create_all(bind=_s.engine)
    runtime_state._memory = runtime_state._memory.__class__()
    importlib.reload(blocks_router)
    importlib.reload(notebooks_router)
    importlib.reload(notebook_ai_router)
    importlib.reload(study_ai_router)
    importlib.reload(main_module)


def _public() -> dict[str, str]:
    return {"origin": "http://localhost:3000"}


def _register(email: str = "u@x.co") -> tuple[TestClient, str, str]:
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
    ws_id = info["workspace"]["id"]
    user_id = info["user"]["id"]
    client.headers.update({
        "origin": "http://localhost:3000",
        "x-csrf-token": csrf,
        "x-workspace-id": ws_id,
    })
    return client, ws_id, user_id


def _upgrade(workspace_id: str, plan: str = "pro") -> None:
    from app.core.entitlements import refresh_workspace_entitlements
    with _s.SessionLocal() as db:
        db.add(Subscription(
            workspace_id=workspace_id,
            plan=plan, status="active",
            provider="free", billing_cycle="monthly",
        ))
        db.commit()
        refresh_workspace_entitlements(db, workspace_id=workspace_id)


def _seed_notebook(ws_id: str, user_id: str, *, visibility: str = "workspace") -> tuple[str, str, str]:
    """Create a project + notebook + seed page. Returns (project_id, notebook_id, page_id)."""
    with _s.SessionLocal() as db:
        project = Project(workspace_id=ws_id, name="P")
        db.add(project); db.commit(); db.refresh(project)
        nb = Notebook(
            workspace_id=ws_id,
            project_id=project.id,
            created_by=user_id,
            title="NB",
            slug="nb",
            visibility=visibility,
        )
        db.add(nb); db.commit(); db.refresh(nb)
        page = NotebookPage(
            notebook_id=nb.id,
            created_by=user_id,
            title="Seed",
            slug="seed",
            plain_text="seed content",
            content_json={
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "attrs": {"block_id": "seed-block-1"},
                        "content": [{"type": "text", "text": "seed content"}],
                    }
                ],
            },
        )
        db.add(page); db.commit(); db.refresh(page)
        return project.id, nb.id, page.id


def _setup_client() -> tuple[TestClient, str, str, str, str]:
    client, ws_id, user_id = _register(f"a5-{os.urandom(4).hex()}@x.co")
    _upgrade(ws_id, "pro")  # lift quota / entitlement ceilings
    project_id, nb_id, page_id = _seed_notebook(ws_id, user_id)
    return client, ws_id, user_id, nb_id, page_id


# ---------------------------------------------------------------------------
# NotebookBlock CRUD (spec §13.3)
# ---------------------------------------------------------------------------


def test_block_create_updates_page_content_json() -> None:
    client, _ws, _uid, _nb, page_id = _setup_client()

    resp = client.post(
        f"/api/v1/pages/{page_id}/blocks",
        json={
            "block_type": "paragraph",
            "content_json": {
                "type": "paragraph",
                "content": [{"type": "text", "text": "new block"}],
            },
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["page_id"] == page_id
    assert body["block_type"] == "paragraph"
    block_id = body["id"]

    # Page content_json should now have this block
    with _s.SessionLocal() as db:
        page = db.query(NotebookPage).filter(NotebookPage.id == page_id).first()
        content = (page.content_json or {}).get("content") or []
        block_ids = [(n.get("attrs") or {}).get("block_id") for n in content]
        assert block_id in block_ids


def test_block_patch_updates_block_and_page_plain_text() -> None:
    client, _ws, _uid, _nb, page_id = _setup_client()

    create = client.post(
        f"/api/v1/pages/{page_id}/blocks",
        json={
            "block_type": "paragraph",
            "content_json": {
                "type": "paragraph",
                "content": [{"type": "text", "text": "initial"}],
            },
        },
    ).json()
    block_id = create["id"]

    resp = client.patch(
        f"/api/v1/blocks/{block_id}",
        json={
            "content_json": {
                "type": "paragraph",
                "content": [{"type": "text", "text": "updated text"}],
            }
        },
    )
    assert resp.status_code == 200, resp.text
    assert "updated text" in resp.json()["plain_text"]

    with _s.SessionLocal() as db:
        page = db.query(NotebookPage).filter(NotebookPage.id == page_id).first()
        assert "updated text" in (page.plain_text or "")


def test_block_delete_removes_from_page() -> None:
    client, _ws, _uid, _nb, page_id = _setup_client()

    create = client.post(
        f"/api/v1/pages/{page_id}/blocks",
        json={
            "block_type": "paragraph",
            "content_json": {
                "type": "paragraph",
                "content": [{"type": "text", "text": "doomed"}],
            },
        },
    ).json()
    block_id = create["id"]

    resp = client.delete(f"/api/v1/blocks/{block_id}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "deleted"

    with _s.SessionLocal() as db:
        page = db.query(NotebookPage).filter(NotebookPage.id == page_id).first()
        ids = [
            (n.get("attrs") or {}).get("block_id")
            for n in (page.content_json or {}).get("content") or []
        ]
        assert block_id not in ids


def test_reorder_blocks_updates_sort_order() -> None:
    client, _ws, _uid, _nb, page_id = _setup_client()

    b1 = client.post(
        f"/api/v1/pages/{page_id}/blocks",
        json={
            "block_type": "paragraph",
            "content_json": {
                "type": "paragraph",
                "content": [{"type": "text", "text": "A"}],
            },
        },
    ).json()
    b2 = client.post(
        f"/api/v1/pages/{page_id}/blocks",
        json={
            "block_type": "paragraph",
            "content_json": {
                "type": "paragraph",
                "content": [{"type": "text", "text": "B"}],
            },
        },
    ).json()

    # Reverse them
    resp = client.post(
        f"/api/v1/pages/{page_id}/reorder-blocks",
        json={"block_ids": [b2["id"], b1["id"]]},
    )
    assert resp.status_code == 200, resp.text

    listing = client.get(f"/api/v1/pages/{page_id}/blocks")
    assert listing.status_code == 200
    # seed block + reordered two
    ids_in_order = [row["id"] for row in listing.json()]
    # b2 should appear before b1
    assert ids_in_order.index(b2["id"]) < ids_in_order.index(b1["id"])


# ---------------------------------------------------------------------------
# Page duplicate / move / soft-delete / archived guard
# ---------------------------------------------------------------------------


def test_page_duplicate_copies_blocks_and_attachments() -> None:
    client, ws_id, uid, nb_id, page_id = _setup_client()

    # Seed a NotebookBlock row via the API so there's something to clone
    client.post(
        f"/api/v1/pages/{page_id}/blocks",
        json={
            "block_type": "heading",
            "content_json": {
                "type": "heading",
                "attrs": {"level": 2},
                "content": [{"type": "text", "text": "Hello"}],
            },
        },
    )
    # Seed an attachment row directly (bypassing S3)
    with _s.SessionLocal() as db:
        att = NotebookAttachment(
            page_id=page_id,
            data_item_id=None,
            attachment_type="image",
            title="icon.png",
            meta_json={"object_key": f"{ws_id}/{page_id}/x/icon.png", "size_bytes": 10},
        )
        db.add(att); db.commit()

    resp = client.post(f"/api/v1/pages/{page_id}/duplicate", json={})
    assert resp.status_code == 200, resp.text
    new_id = resp.json()["id"]
    assert new_id != page_id
    assert resp.json()["title"].endswith("(copy)")

    with _s.SessionLocal() as db:
        # Attachments cloned
        clones = db.query(NotebookAttachment).filter(NotebookAttachment.page_id == new_id).all()
        assert len(clones) == 1
        # Blocks cloned with fresh block_ids
        new_page = db.query(NotebookPage).filter(NotebookPage.id == new_id).first()
        nb_ids = [
            (n.get("attrs") or {}).get("block_id")
            for n in (new_page.content_json or {}).get("content") or []
        ]
        orig_page = db.query(NotebookPage).filter(NotebookPage.id == page_id).first()
        orig_ids = [
            (n.get("attrs") or {}).get("block_id")
            for n in (orig_page.content_json or {}).get("content") or []
        ]
        # No id is shared between the source and the clone
        assert not (set(nb_ids) & set(orig_ids))


def test_page_move_to_another_notebook_same_workspace() -> None:
    client, ws_id, uid, nb_id, page_id = _setup_client()
    # Second notebook in same workspace
    with _s.SessionLocal() as db:
        project = db.query(Project).filter(Project.workspace_id == ws_id).first()
        nb2 = Notebook(
            workspace_id=ws_id,
            project_id=project.id,
            created_by=uid,
            title="NB2",
            slug="nb2",
            visibility="workspace",
        )
        db.add(nb2); db.commit(); db.refresh(nb2)
        target_id = nb2.id

    resp = client.post(
        f"/api/v1/pages/{page_id}/move",
        json={"notebook_id": target_id},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["notebook_id"] == target_id


def test_page_move_rejects_cross_workspace() -> None:
    client_a, ws_a, uid_a, nb_a, page_a = _setup_client()
    client_b, ws_b, uid_b = _register(f"a5-cross-{os.urandom(4).hex()}@x.co")
    _upgrade(ws_b, "pro")
    _, nb_b, _ = _seed_notebook(ws_b, uid_b, visibility="workspace")

    resp = client_a.post(
        f"/api/v1/pages/{page_a}/move",
        json={"notebook_id": nb_b},
    )
    # Target notebook in a different workspace → 404 not-leaked
    assert resp.status_code == 404, resp.text


def test_delete_page_is_soft_delete_preserves_evidence() -> None:
    client, _ws, _uid, _nb, page_id = _setup_client()

    resp = client.delete(f"/api/v1/pages/{page_id}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "archived"

    with _s.SessionLocal() as db:
        # Row still present, but is_archived=True
        page = db.query(NotebookPage).filter(NotebookPage.id == page_id).first()
        assert page is not None
        assert page.is_archived is True


def test_create_block_on_archived_notebook_page_404() -> None:
    client, _ws, _uid, nb_id, page_id = _setup_client()

    # Archive the notebook (soft-delete)
    with _s.SessionLocal() as db:
        from datetime import datetime, timezone
        nb = db.query(Notebook).filter(Notebook.id == nb_id).first()
        nb.archived_at = datetime.now(timezone.utc)
        db.commit()

    resp = client.post(
        f"/api/v1/pages/{page_id}/blocks",
        json={
            "block_type": "paragraph",
            "content_json": {"type": "paragraph"},
        },
    )
    assert resp.status_code == 404, resp.text


def test_delete_attachment_removes_row_and_s3_object(monkeypatch) -> None:
    client, ws_id, _uid, _nb, page_id = _setup_client()

    # Seed an attachment directly (avoids multipart upload path)
    with _s.SessionLocal() as db:
        att = NotebookAttachment(
            page_id=page_id,
            data_item_id=None,
            attachment_type="image",
            title="z.png",
            meta_json={
                "object_key": f"{ws_id}/{page_id}/x/z.png",
                "size_bytes": 8,
            },
        )
        db.add(att); db.commit(); db.refresh(att)
        att_id = att.id

    # Stub the S3 client so we don't hit MinIO
    calls: dict[str, str] = {}

    class _FakeS3:
        def delete_object(self, *, Bucket: str, Key: str) -> None:  # noqa: N803
            calls["Bucket"] = Bucket
            calls["Key"] = Key

    import app.services.storage as storage_module
    monkeypatch.setattr(storage_module, "get_s3_client", lambda: _FakeS3())

    resp = client.delete(f"/api/v1/pages/{page_id}/attachments/{att_id}")
    assert resp.status_code == 200, resp.text

    with _s.SessionLocal() as db:
        assert db.query(NotebookAttachment).filter(NotebookAttachment.id == att_id).first() is None
    assert calls.get("Key", "").endswith("z.png")


# ---------------------------------------------------------------------------
# Standalone notebook AI endpoints
# ---------------------------------------------------------------------------


def _stub_stream(monkeypatch, content: str = "- one\n- two\n- three") -> None:
    from app.services.dashscope_stream import StreamChunk

    async def _fake_stream(messages, *args, **kwargs):
        yield StreamChunk(
            content=content,
            usage={"prompt_tokens": 10, "completion_tokens": 20},
            model_id="test-model",
        )

    monkeypatch.setattr(notebook_ai_router, "chat_completion_stream", _fake_stream)


def test_notebook_brainstorm_endpoint_writes_action_log(monkeypatch) -> None:
    _stub_stream(monkeypatch, content="- idea 1\n- idea 2\n- idea 3")
    client, _ws, _uid, nb_id, _page = _setup_client()

    resp = client.post(
        "/api/v1/ai/notebook/brainstorm",
        json={"notebook_id": nb_id, "topic": "Launch ideas", "count": 3},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "markdown" in body
    assert "idea" in body["markdown"].lower()

    # AIActionLog row written
    from app.models import AIActionLog
    with _s.SessionLocal() as db:
        logs = db.query(AIActionLog).filter(
            AIActionLog.action_type == "notebook.brainstorm"
        ).all()
        assert len(logs) == 1


def test_generate_page_endpoint_creates_page_and_writes_log(monkeypatch) -> None:
    _stub_stream(
        monkeypatch,
        content="# PRD\n\n## Problem\nUsers need X.\n\n## Goals\n- Ship fast",
    )
    client, _ws, _uid, nb_id, _page = _setup_client()

    resp = client.post(
        "/api/v1/ai/notebook/generate-page",
        json={
            "notebook_id": nb_id,
            "idea": "A minimal SaaS that does X",
            "output_type": "prd",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["output_type"] == "prd"
    new_page_id = body["page_id"]

    with _s.SessionLocal() as db:
        page = db.query(NotebookPage).filter(NotebookPage.id == new_page_id).first()
        assert page is not None
        assert "Problem" in (page.plain_text or "")

    from app.models import AIActionLog
    with _s.SessionLocal() as db:
        logs = db.query(AIActionLog).filter(
            AIActionLog.action_type.like("notebook.generate_page%")
        ).all()
        assert len(logs) == 1


def test_generate_deck_endpoint_stub_returns_deck(monkeypatch) -> None:
    """generate-deck should produce a deck when chunk content is available.

    LLM returns JSON cards; we stub _run_llm_json to bypass the real API.
    """
    client, ws_id, uid, nb_id, _page = _setup_client()

    # Seed a study asset with chunks
    with _s.SessionLocal() as db:
        asset = StudyAsset(
            notebook_id=nb_id,
            title="Book",
            asset_type="pdf",
            status="ready",
            total_chunks=1,
            created_by=uid,
        )
        db.add(asset); db.commit(); db.refresh(asset)
        chunk = StudyChunk(asset_id=asset.id, chunk_index=0, heading="", content="Long study text"[:8000])
        db.add(chunk); db.commit()
        asset_id = asset.id

    # Stub the LLM helper
    async def _fake_json(system, user_prompt):
        return '{"cards":[{"front":"Q1","back":"A1"},{"front":"Q2","back":"A2"}]}'
    monkeypatch.setattr(study_ai_router, "_run_llm_json", _fake_json)

    resp = client.post(
        f"/api/v1/study-assets/{asset_id}/generate-deck",
        json={"count": 2},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["card_count"] == 2

    with _s.SessionLocal() as db:
        deck = db.query(StudyDeck).filter(StudyDeck.id == body["deck_id"]).first()
        assert deck is not None
        assert deck.card_count == 2


# ---------------------------------------------------------------------------
# Memory confirm/reject
# ---------------------------------------------------------------------------


def _seed_memory_write_item(ws_id: str, uid: str, page_id: str, nb_id: str, project_id: str) -> str:
    """Seed a pending memory candidate tied to this page. Returns item_id."""
    with _s.SessionLocal() as db:
        run = MemoryWriteRun(
            workspace_id=ws_id,
            project_id=project_id,
            status="completed",
            metadata_json={"source_type": "notebook_page", "source_id": page_id},
        )
        db.add(run); db.commit(); db.refresh(run)
        item = MemoryWriteItem(
            run_id=run.id,
            candidate_text="The user prefers dark mode in all their apps",
            category="preference",
            importance=0.7,
            decision="pending",
            metadata_json={"start_offset": 0, "end_offset": 45},
        )
        db.add(item); db.commit(); db.refresh(item)
        return item.id


def test_selection_memory_link_created_on_confirm(monkeypatch) -> None:
    client, ws_id, uid, nb_id, page_id = _setup_client()
    with _s.SessionLocal() as db:
        project_id = db.query(Project).filter(Project.workspace_id == ws_id).first().id
    item_id = _seed_memory_write_item(ws_id, uid, page_id, nb_id, project_id)

    # Stub the unified pipeline promote so the test is hermetic
    from app.services import unified_memory_pipeline as ump

    async def _fake_promote(db, *, item, workspace_id, project_id, user_id):
        mem = Memory(
            workspace_id=workspace_id,
            project_id=project_id,
            content=item.candidate_text,
            category=item.category,
            type="permanent",
            node_type="fact",
            node_status="active",
            confidence=0.7,
        )
        db.add(mem); db.flush()
        item.decision = "approved"
        item.target_memory_id = mem.id
        ev = MemoryEvidence(
            workspace_id=workspace_id,
            project_id=project_id,
            memory_id=mem.id,
            source_type="notebook_page",
            quote_text=item.candidate_text,
            start_offset=0,
            end_offset=len(item.candidate_text),
            metadata_json={"page_id": str(item.metadata_json.get("page_id") or "")},
        )
        db.add(ev); db.flush()
        return mem

    monkeypatch.setattr(ump, "promote_write_item", _fake_promote)

    resp = client.post(
        f"/api/v1/pages/{page_id}/memory/confirm",
        json={"item_id": item_id},
    )
    assert resp.status_code == 200, resp.text

    with _s.SessionLocal() as db:
        links = db.query(NotebookSelectionMemoryLink).all()
        assert len(links) == 1
        link = links[0]
        assert link.page_id == page_id
        assert link.start_offset == 0
        assert link.end_offset == 45
        assert link.memory_id is not None


def test_memory_reject_lowers_fingerprint_matching_candidates() -> None:
    client, ws_id, uid, nb_id, page_id = _setup_client()
    with _s.SessionLocal() as db:
        project_id = db.query(Project).filter(Project.workspace_id == ws_id).first().id

    # Seed the victim (to reject) + 2 pending look-alikes with matching prefix
    with _s.SessionLocal() as db:
        run = MemoryWriteRun(
            workspace_id=ws_id,
            project_id=project_id,
            status="completed",
            metadata_json={"source_type": "notebook_page", "source_id": page_id},
        )
        db.add(run); db.commit(); db.refresh(run)
        victim = MemoryWriteItem(
            run_id=run.id,
            candidate_text="The user really hates blue buttons everywhere they see them",
            category="preference",
            importance=0.6,
            decision="pending",
        )
        sib1 = MemoryWriteItem(
            run_id=run.id,
            candidate_text="The user really hates blue buttons and wishes they were green",
            category="preference",
            importance=0.6,
            decision="pending",
        )
        sib2 = MemoryWriteItem(
            run_id=run.id,
            candidate_text="Today's weather is lovely and sunny",
            category="observation",
            importance=0.5,
            decision="pending",
        )
        db.add_all([victim, sib1, sib2])
        db.commit()
        db.refresh(victim); db.refresh(sib1); db.refresh(sib2)
        victim_id, sib1_id, sib2_id = victim.id, sib1.id, sib2.id

    resp = client.post(
        f"/api/v1/pages/{page_id}/memory/reject",
        json={"item_id": victim_id, "reason": "not relevant"},
    )
    assert resp.status_code == 200, resp.text
    # The sibling with matching first-100 prefix was downranked, the other wasn't
    assert resp.json().get("downranked_count", 0) >= 1

    with _s.SessionLocal() as db:
        sib1_after = db.query(MemoryWriteItem).filter(MemoryWriteItem.id == sib1_id).first()
        sib2_after = db.query(MemoryWriteItem).filter(MemoryWriteItem.id == sib2_id).first()
        # sib1 shares prefix → importance halved
        assert sib1_after.importance < 0.6
        # sib2 doesn't share prefix → importance intact
        assert sib2_after.importance == 0.5


# ---------------------------------------------------------------------------
# Retrieval orchestration new layers + scope gate
# ---------------------------------------------------------------------------


def test_retrieval_orchestration_assembles_memory_explain_layer(monkeypatch) -> None:
    """``_retrieve_memory_explain`` should feed through ``assemble_context``
    and produce ``memory_explain_hits`` + a ``memory_explain`` source.
    """
    from app.services import retrieval_orchestration as ro

    async def _fake_explain(db, **kw):
        return {
            "hits": [
                {"memory_id": "m-1", "content": "explain hit one", "result_type": "memory", "score": 0.8},
                {"view_id": "v-1", "excerpt": "playbook says do X", "result_type": "view", "score": 0.7},
            ],
            "trace": {},
        }

    monkeypatch.setattr(
        "app.services.memory_context.explain_project_memory_hits_v2",
        _fake_explain,
    )
    # Make memory_hits come back empty so we know the explain section drives the prompt.
    async def _fake_hits(*a, **kw):
        return []
    monkeypatch.setattr(ro, "_retrieve_memory_hits", _fake_hits)
    async def _fake_chunks(*a, **kw):
        return []
    monkeypatch.setattr(ro, "_retrieve_document_chunks", _fake_chunks)
    async def _fake_related(*a, **kw):
        return []
    monkeypatch.setattr(ro, "_retrieve_related_pages", _fake_related)

    import asyncio
    with _s.SessionLocal() as db:
        ctx = asyncio.run(ro.assemble_context(
            db,
            workspace_id="ws",
            project_id="pj",
            user_id="uid",
            query="whatever",
            scope=["user_memory", "page"],
        ))
    assert any(h.get("result_type") in ("memory", "view") for h in ctx.memory_explain_hits)
    assert any(s.source_type == "memory_explain" for s in ctx.sources)
    assert "推理" in ctx.system_prompt


def test_retrieval_orchestration_assembles_page_history_layer() -> None:
    """``_retrieve_page_history`` should surface recent NotebookPageVersion rows."""
    client, ws_id, uid, _nb, page_id = _setup_client()

    with _s.SessionLocal() as db:
        for vn in range(1, 4):
            db.add(NotebookPageVersion(
                page_id=page_id,
                version_no=vn,
                snapshot_json={},
                snapshot_text=f"snapshot v{vn} — earlier draft",
                source="autosave",
                created_by=uid,
            ))
        db.commit()

    import asyncio
    from app.services import retrieval_orchestration as ro

    with _s.SessionLocal() as db:
        ctx = asyncio.run(ro._retrieve_page_history(db, page_id=page_id))
    assert len(ctx) == 3
    assert ctx[0]["version_no"] == 3  # most-recent first


def test_ask_endpoint_accepts_scope_parameter_and_filters_layers(monkeypatch) -> None:
    """Passing scope=['page'] should skip user_memory / study_asset / notebook layers."""
    client, ws_id, uid, nb_id, page_id = _setup_client()

    # Stub the streaming LLM so we don't hit dashscope
    from app.services.dashscope_stream import StreamChunk

    async def _fake_stream(messages, *args, **kwargs):
        yield StreamChunk(content="ok", usage=None, model_id=None)

    monkeypatch.setattr(notebook_ai_router, "chat_completion_stream", _fake_stream)

    # Observe which retrieval functions were called via a spy
    called: dict[str, bool] = {"memory": False, "explain": False, "chunks": False, "related": False}
    from app.services import retrieval_orchestration as ro

    async def _spy_memory(*a, **kw):
        called["memory"] = True
        return []
    async def _spy_explain(*a, **kw):
        called["explain"] = True
        return []
    async def _spy_chunks(*a, **kw):
        called["chunks"] = True
        return []
    async def _spy_related(*a, **kw):
        called["related"] = True
        return []
    monkeypatch.setattr(ro, "_retrieve_memory_hits", _spy_memory)
    monkeypatch.setattr(ro, "_retrieve_memory_explain", _spy_explain)
    monkeypatch.setattr(ro, "_retrieve_document_chunks", _spy_chunks)
    monkeypatch.setattr(ro, "_retrieve_related_pages", _spy_related)

    resp = client.post(
        "/api/v1/ai/notebook/ask",
        json={
            "page_id": page_id,
            "message": "what is on this page?",
            "scope": ["page"],
        },
    )
    # Stream response status is 200 as soon as headers flush
    assert resp.status_code == 200, resp.text
    # Drain the stream so the generator ran
    _ = resp.text

    # With scope=['page'], memory-related layers should be skipped.
    assert called["memory"] is False
    assert called["explain"] is False
    assert called["chunks"] is False
    assert called["related"] is False
