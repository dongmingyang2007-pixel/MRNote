# ruff: noqa: E402
"""Regression tests for the three P0 spec-alignment gaps.

Gap 1 — StudyAsset ORM missing ``language``, ``author``, ``page_id`` fields
        (columns existed on-disk from migration 202604220005 but were not
        bound to the SQLAlchemy model so reads/writes silently dropped
        them).
Gap 2 — StudyChunk missing ``summary`` + ``keywords_json`` (Spec §5.1.7).
        Columns added by migration 202604230002; this test verifies the
        ORM can roundtrip them and that the default values work.
Gap 3 — DELETE /api/v1/attachments/{id} flat path (Spec §13.4). The
        nested page-scoped delete already existed; this exercises the
        flat route, its cross-workspace 404, and the CSRF guard.
"""

import atexit
import hashlib
import importlib
import io
import os
import shutil
import tempfile
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="mrnote-p0-"))
atexit.register(lambda: shutil.rmtree(TEST_TEMP_DIR, ignore_errors=True))
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_TEMP_DIR / 'test.db'}"
os.environ["ENV"] = "test"
os.environ["COOKIE_DOMAIN"] = ""
os.environ["DEMO_MODE"] = "true"
os.environ["STRIPE_API_KEY"] = "sk_test_dummy"
os.environ["SITE_URL"] = "http://testserver"

import app.core.config as config_module

config_module.get_settings.cache_clear()
config_module.settings = config_module.get_settings()
import app.db.session as session_module

importlib.reload(session_module)
import app.main as main_module

importlib.reload(main_module)

from fastapi.testclient import TestClient

import app.db.session as _s
import app.services.storage as storage_service
from app.db.base import Base
from app.models import (
    Notebook,
    NotebookAttachment,
    NotebookPage,
    Project,
    StudyAsset,
    StudyChunk,
    User,
)
from app.services.runtime_state import runtime_state
from tests.fixtures.fake_s3 import FakeS3Client


def setup_function() -> None:
    Base.metadata.drop_all(bind=_s.engine)
    Base.metadata.create_all(bind=_s.engine)
    runtime_state._memory = runtime_state._memory.__class__()
    # Swap in a fake S3 so delete_object calls don't hit the network.
    fake = FakeS3Client()
    fake.create_bucket(Bucket="notebook-attachments")
    cache_clear = getattr(storage_service.get_s3_client, "cache_clear", None)
    if cache_clear:
        cache_clear()
    storage_service.get_s3_client = lambda: fake  # type: ignore[assignment]


def _public() -> dict[str, str]:
    return {"origin": "http://localhost:3000"}


def _register(email: str = "u@x.co") -> tuple[TestClient, dict]:
    """Register a workspace+user and return a preconfigured TestClient."""
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
    client.headers.update(
        {
            "origin": "http://localhost:3000",
            "x-csrf-token": csrf,
            "x-workspace-id": ws_id,
        }
    )
    return client, {"ws_id": ws_id, "user_id": info["user"]["id"]}


def _seed_notebook_page(ws_id: str, user_id: str) -> tuple[str, str]:
    """Seed a (notebook_id, page_id) pair for the given workspace."""
    with _s.SessionLocal() as db:
        pr = Project(workspace_id=ws_id, name="P")
        db.add(pr)
        db.commit()
        db.refresh(pr)
        nb = Notebook(
            workspace_id=ws_id,
            project_id=pr.id,
            created_by=user_id,
            title="NB",
            slug="nb",
        )
        db.add(nb)
        db.commit()
        db.refresh(nb)
        pg = NotebookPage(
            notebook_id=nb.id, created_by=user_id, title="T", slug="t", plain_text="x"
        )
        db.add(pg)
        db.commit()
        db.refresh(pg)
        return nb.id, pg.id


def _seed_attachment(page_id: str, *, object_key: str = "att/xyz/x.pdf") -> str:
    """Insert a NotebookAttachment row and return its id."""
    with _s.SessionLocal() as db:
        att = NotebookAttachment(
            page_id=page_id,
            attachment_type="file",
            title="x.pdf",
            meta_json={"object_key": object_key, "filename": "x.pdf"},
        )
        db.add(att)
        db.commit()
        db.refresh(att)
        return att.id


# ---------------------------------------------------------------------------
# Gap 1 — StudyAsset ORM field alignment
# ---------------------------------------------------------------------------


def test_studyasset_orm_writes_and_reads_language_author_page_id() -> None:
    """Round-trip language/author/page_id through the ORM.

    Pre-fix: SQLAlchemy dropped these columns on insert/update because they
    had no Mapped[] binding, so querying back returned None even after a
    raw SQL insert with values set.
    """
    _client, auth = _register("sa-orm@x.co")
    _nb_id, page_id = _seed_notebook_page(auth["ws_id"], auth["user_id"])

    with _s.SessionLocal() as db:
        notebook_id = db.query(Notebook.id).first()[0]
        user_id = db.query(User.id).first()[0]
        asset = StudyAsset(
            notebook_id=notebook_id,
            created_by=user_id,
            title="Calculus Book",
            asset_type="book",
            language="en-US",
            author="Spivak",
            page_id=page_id,
        )
        db.add(asset)
        db.commit()
        db.refresh(asset)
        asset_id = asset.id

    # Re-query in a fresh session to make sure values actually hit disk and
    # the ORM re-hydrates them on the way back (not just held in identity
    # map memory).
    with _s.SessionLocal() as db:
        got = db.query(StudyAsset).filter_by(id=asset_id).first()
        assert got is not None
        assert got.language == "en-US"
        assert got.author == "Spivak"
        assert got.page_id == page_id


def test_studyasset_orm_allows_null_metadata() -> None:
    """language/author/page_id are all nullable per spec §5.1.6."""
    _client, auth = _register("sa-null@x.co")
    _seed_notebook_page(auth["ws_id"], auth["user_id"])
    with _s.SessionLocal() as db:
        notebook_id = db.query(Notebook.id).first()[0]
        user_id = db.query(User.id).first()[0]
        asset = StudyAsset(
            notebook_id=notebook_id,
            created_by=user_id,
            title="Untitled",
            asset_type="pdf",
        )
        db.add(asset)
        db.commit()
        db.refresh(asset)
        assert asset.language is None
        assert asset.author is None
        assert asset.page_id is None


# ---------------------------------------------------------------------------
# Gap 2 — StudyChunk summary + keywords_json
# ---------------------------------------------------------------------------


def test_studychunk_orm_writes_summary_and_keywords_json() -> None:
    _client, auth = _register("sc-write@x.co")
    _seed_notebook_page(auth["ws_id"], auth["user_id"])
    with _s.SessionLocal() as db:
        notebook_id = db.query(Notebook.id).first()[0]
        user_id = db.query(User.id).first()[0]
        asset = StudyAsset(
            notebook_id=notebook_id,
            created_by=user_id,
            title="Book",
            asset_type="book",
        )
        db.add(asset)
        db.commit()
        db.refresh(asset)

        chunk = StudyChunk(
            asset_id=asset.id,
            chunk_index=0,
            heading="Chapter 1",
            content="Once upon a time ...",
            summary="Fairy tale opening.",
            keywords_json=["fairy-tale", "opening", "narrative"],
        )
        db.add(chunk)
        db.commit()
        db.refresh(chunk)
        chunk_id = chunk.id

    with _s.SessionLocal() as db:
        got = db.query(StudyChunk).filter_by(id=chunk_id).first()
        assert got is not None
        assert got.summary == "Fairy tale opening."
        assert got.keywords_json == ["fairy-tale", "opening", "narrative"]


def test_studychunk_default_values_are_empty() -> None:
    """Callers that omit summary/keywords_json get the spec defaults.

    ORM default ``""`` for summary, ``[]`` for keywords_json — so legacy
    callers that only set (asset_id, chunk_index, content) keep working.
    """
    _client, auth = _register("sc-default@x.co")
    _seed_notebook_page(auth["ws_id"], auth["user_id"])
    with _s.SessionLocal() as db:
        notebook_id = db.query(Notebook.id).first()[0]
        user_id = db.query(User.id).first()[0]
        asset = StudyAsset(
            notebook_id=notebook_id,
            created_by=user_id,
            title="Book",
            asset_type="book",
        )
        db.add(asset)
        db.commit()
        db.refresh(asset)

        chunk = StudyChunk(
            asset_id=asset.id,
            chunk_index=0,
            content="body",
        )
        db.add(chunk)
        db.commit()
        db.refresh(chunk)
        assert chunk.summary == ""
        assert chunk.keywords_json == []


# ---------------------------------------------------------------------------
# Gap 3 — DELETE /api/v1/attachments/{id} flat path (spec §13.4)
# ---------------------------------------------------------------------------


def test_delete_attachment_flat_endpoint_removes_row() -> None:
    """DELETE /api/v1/attachments/{id} deletes the row and returns 204."""
    client, auth = _register("att-flat@x.co")
    _nb_id, page_id = _seed_notebook_page(auth["ws_id"], auth["user_id"])
    att_id = _seed_attachment(page_id)

    resp = client.delete(f"/api/v1/attachments/{att_id}")
    assert resp.status_code == 204, resp.text
    # 204 bodies should be empty.
    assert resp.content in (b"", b"null")

    with _s.SessionLocal() as db:
        assert db.query(NotebookAttachment).filter_by(id=att_id).first() is None


def test_delete_attachment_flat_checks_visibility_404_on_other_workspace() -> None:
    """Caller from workspace B cannot delete an attachment in workspace A."""
    _client_a, auth_a = _register("own-flat@x.co")
    _nb_id_a, page_id_a = _seed_notebook_page(auth_a["ws_id"], auth_a["user_id"])
    att_id = _seed_attachment(page_id_a)

    client_b, _auth_b = _register("other-flat@x.co")
    resp = client_b.delete(f"/api/v1/attachments/{att_id}")
    assert resp.status_code == 404, resp.text

    # Attachment still exists — cross-workspace delete was rejected.
    with _s.SessionLocal() as db:
        assert db.query(NotebookAttachment).filter_by(id=att_id).first() is not None


def test_delete_attachment_flat_requires_csrf() -> None:
    """Missing x-csrf-token must be rejected; the write guard is in play."""
    client, auth = _register("att-csrf@x.co")
    _nb_id, page_id = _seed_notebook_page(auth["ws_id"], auth["user_id"])
    att_id = _seed_attachment(page_id)

    # Strip CSRF header, keep workspace + origin so auth resolves but the
    # csrf dep trips.
    headers = {k: v for k, v in client.headers.items() if k.lower() != "x-csrf-token"}
    client.headers.clear()
    client.headers.update(headers)

    resp = client.delete(f"/api/v1/attachments/{att_id}")
    assert resp.status_code in (400, 401, 403), resp.text

    # Row must survive the rejected request.
    with _s.SessionLocal() as db:
        assert db.query(NotebookAttachment).filter_by(id=att_id).first() is not None


def test_delete_attachment_flat_404_when_missing() -> None:
    """Unknown attachment id → 404 (not 500)."""
    client, _auth = _register("att-miss@x.co")
    resp = client.delete("/api/v1/attachments/does-not-exist")
    assert resp.status_code == 404, resp.text
