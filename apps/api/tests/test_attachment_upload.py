# ruff: noqa: E402
import atexit, importlib, os, shutil, tempfile
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-s2-upload-"))
atexit.register(lambda: shutil.rmtree(TEST_TEMP_DIR, ignore_errors=True))
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_TEMP_DIR / 'test.db'}"
os.environ["ENV"] = "test"
os.environ["COOKIE_DOMAIN"] = ""
os.environ["DEMO_MODE"] = "true"

import app.core.config as config_module
config_module.get_settings.cache_clear()
config_module.settings = config_module.get_settings()
import app.db.session as session_module
importlib.reload(session_module)
import app.main as main_module
importlib.reload(main_module)

import io
from fastapi.testclient import TestClient

from app.db.base import Base
import app.db.session as _s
from app.models import (
    Notebook, NotebookAttachment, NotebookPage, Project, User, Workspace,
)
import app.services.storage as storage_service
from tests.fixtures.fake_s3 import FakeS3Client


def setup_function() -> None:
    global engine, SessionLocal
    engine = _s.engine
    SessionLocal = _s.SessionLocal
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    from app.services.runtime_state import runtime_state
    runtime_state._memory = runtime_state._memory.__class__()
    # Install a fake S3 and pre-create the bucket.
    fake = FakeS3Client()
    fake.create_bucket(Bucket="notebook-attachments")
    cache_clear = getattr(storage_service.get_s3_client, "cache_clear", None)
    if cache_clear:
        cache_clear()
    storage_service.get_s3_client = lambda: fake  # type: ignore[assignment]
    presign_cache_clear = getattr(storage_service.get_s3_presign_client, "cache_clear", None)
    if presign_cache_clear:
        presign_cache_clear()
    storage_service.get_s3_presign_client = lambda: fake  # type: ignore[assignment]


engine = _s.engine
SessionLocal = _s.SessionLocal


def _public_headers() -> dict[str, str]:
    return {"origin": "http://localhost:3000"}


def _verification_code_key(email: str, purpose: str) -> str:
    import hashlib
    raw = f"{email.lower().strip()}:{purpose}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _register_client(email: str = "u@x.co") -> tuple[TestClient, dict]:
    from app.services.runtime_state import runtime_state
    client = TestClient(main_module.app)
    client.post(
        "/api/v1/auth/send-code",
        json={"email": email, "purpose": "register"},
        headers=_public_headers(),
    )
    entry = runtime_state.get_json("verify_code", _verification_code_key(email, "register"))
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "pass1234pass",
              "display_name": "Test", "code": str(entry["code"])},
        headers=_public_headers(),
    )
    assert resp.status_code == 200, resp.text
    info = resp.json()
    csrf = client.get("/api/v1/auth/csrf", headers=_public_headers()).json()["csrf_token"]
    client.headers.update({
        "origin": "http://localhost:3000",
        "x-csrf-token": csrf,
        "x-workspace-id": info["workspace"]["id"],
    })
    return client, {"ws_id": info["workspace"]["id"], "user_id": info["user"]["id"]}


def _seed_page(ws_id: str, user_id: str) -> str:
    with SessionLocal() as db:
        pr = Project(workspace_id=ws_id, name="P"); db.add(pr); db.commit(); db.refresh(pr)
        nb = Notebook(workspace_id=ws_id, project_id=pr.id, created_by=user_id,
                      title="NB", slug="nb")
        db.add(nb); db.commit(); db.refresh(nb)
        pg = NotebookPage(notebook_id=nb.id, created_by=user_id, title="T",
                          slug="t", plain_text="x")
        db.add(pg); db.commit(); db.refresh(pg)
        return pg.id


def test_upload_small_png() -> None:
    client, auth = _register_client("u1@x.co")
    page_id = _seed_page(auth["ws_id"], auth["user_id"])
    # Must start with real PNG magic bytes — post-audit, the upload
    # endpoint validates the file signature.
    png_body = b"\x89PNG\r\n\x1a\n" + b"fake png payload"
    files = {"file": ("x.png", io.BytesIO(png_body), "image/png")}

    resp = client.post(
        f"/api/v1/pages/{page_id}/attachments/upload",
        files=files,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["filename"] == "x.png"
    assert body["mime_type"] == "image/png"
    assert body["size_bytes"] == len(png_body)
    assert body["attachment_id"]
    assert body["attachment_type"] == "image"

    with SessionLocal() as db:
        att = db.query(NotebookAttachment).filter_by(id=body["attachment_id"]).one()
    assert att.meta_json.get("object_key")
    assert att.meta_json["object_key"].endswith("x.png")


def test_upload_rejects_files_over_limit(monkeypatch) -> None:
    client, auth = _register_client("u2@x.co")
    page_id = _seed_page(auth["ws_id"], auth["user_id"])

    # Patch both the test module's settings reference and the router's
    # live settings reference. When an earlier test module has already
    # loaded the router, the router's `settings` may be bound to an
    # earlier Settings instance that our top-level reassignment does not
    # reach.
    import app.routers.notebooks as _notebooks_router
    monkeypatch.setattr(config_module.settings, "notebook_attachment_max_bytes", 10)
    monkeypatch.setattr(_notebooks_router.settings, "notebook_attachment_max_bytes", 10)
    # Use plain ASCII text so the text/plain signature check passes and
    # we actually hit the size guard, not the MIME guard.
    files = {"file": ("big.txt", io.BytesIO(b"this-is-way-too-long"), "text/plain")}

    resp = client.post(
        f"/api/v1/pages/{page_id}/attachments/upload",
        files=files,
    )
    assert resp.status_code == 413
    body = resp.json()
    assert body["error"]["code"] == "file_too_large"


def test_upload_cross_workspace_404() -> None:
    _client_a, auth_a = _register_client("a@x.co")
    page_id = _seed_page(auth_a["ws_id"], auth_a["user_id"])

    client_b, _ = _register_client("b@x.co")
    # The page lookup happens before file parsing, so any plausible
    # payload is fine — cross-workspace should 404 regardless.
    png_body = b"\x89PNG\r\n\x1a\n" + b"data"
    files = {"file": ("x.png", io.BytesIO(png_body), "image/png")}
    resp = client_b.post(
        f"/api/v1/pages/{page_id}/attachments/upload",
        files=files,
    )
    assert resp.status_code == 404


def test_attachment_url_returns_presigned_url() -> None:
    client, auth = _register_client("u4@x.co")
    page_id = _seed_page(auth["ws_id"], auth["user_id"])
    import io as _io
    # Real PDF magic required post-audit.
    pdf_body = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\nfake pdf bytes"
    files = {"file": ("doc.pdf", _io.BytesIO(pdf_body), "application/pdf")}
    upload = client.post(
        f"/api/v1/pages/{page_id}/attachments/upload",
        files=files,
    ).json()

    resp = client.get(f"/api/v1/attachments/{upload['attachment_id']}/url")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["url"].startswith("http")
    assert "doc.pdf" in body["url"] or upload["attachment_id"] in body["url"]
    assert body["expires_in_seconds"] == 900


def test_attachment_url_forces_download_disposition() -> None:
    client, auth = _register_client("u5@x.co")
    page_id = _seed_page(auth["ws_id"], auth["user_id"])
    # SVG is now blocked by the upload endpoint (audit V1). Upload a
    # benign PDF and verify the presign call still forces the
    # attachment Content-Disposition on download.
    pdf_body = b"%PDF-1.4\nminimal"
    upload = client.post(
        f"/api/v1/pages/{page_id}/attachments/upload",
        files={"file": ("doc.pdf", io.BytesIO(pdf_body), "application/pdf")},
    ).json()

    captured: dict[str, dict] = {}

    class CapturePresignClient:
        def generate_presigned_url(self, operation: str = "get_object", *, Params=None, ExpiresIn=900, **_kwargs):
            captured["params"] = Params or {}
            captured["expires"] = {"value": ExpiresIn}
            return "http://fake-s3/download"

    storage_service.get_s3_presign_client = lambda: CapturePresignClient()  # type: ignore[assignment]

    resp = client.get(f"/api/v1/attachments/{upload['attachment_id']}/url")
    assert resp.status_code == 200, resp.text
    disposition = captured["params"]["ResponseContentDisposition"]
    assert disposition.startswith("attachment;")
    assert "doc.pdf" in disposition
