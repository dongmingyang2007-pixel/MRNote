from contextlib import asynccontextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import settings
from app.core.errors import (
    ApiError,
    api_error_handler,
    http_exception_handler,
    unhandled_error_handler,
    validation_exception_handler,
)
from app.core.http_security import SecurityHeadersMiddleware
from app.core.request_id import RequestIDMiddleware
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.routers import (
    ai_actions, attachments, auth, chat, datasets, memory, memory_stream,
    model_catalog, models, notebook_ai, notebooks, pipeline, proactive,
    projects, realtime, search, study, study_ai, study_decks, uploads,
)
from app.services.chat_modes import ensure_project_chat_mode_schema
from app.services.embedding import ensure_embedding_schema
from app.services.model_catalog_seed import seed_model_catalog
from app.services.memory_roots import ensure_project_memory_root_schema
from app.services.schema_helpers import ensure_column
from app.services.dashscope_http import close_client
from app.services.runtime_state import runtime_state


def _should_use_direct_schema_bootstrap() -> bool:
    return settings.env == "test" or engine.dialect.name == "sqlite"


def _run_direct_schema_bootstrap() -> None:
    Base.metadata.create_all(bind=engine)
    ensure_project_chat_mode_schema(engine)
    ensure_embedding_schema(engine)
    ensure_column(engine, "messages", "reasoning_content", "TEXT")
    ensure_column(engine, "messages", "metadata_json", "JSON", nullable=False, default="'{}'")
    ensure_project_memory_root_schema(engine)


def _run_alembic_upgrades() -> None:
    alembic_config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    alembic_config.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(alembic_config, "head")


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.validate_runtime_configuration()
    runtime_state.ensure_available()
    if _should_use_direct_schema_bootstrap():
        _run_direct_schema_bootstrap()
    else:
        _run_alembic_upgrades()
    db = SessionLocal()
    try:
        seed_model_catalog(db)
    finally:
        db.close()
    # S1: best-effort init of the AI action-log overflow bucket so requests
    # that need it don't pay the bucket-create cost on the hot path.
    try:
        from app.services import storage as _storage_service
        from botocore.exceptions import ClientError as _ClientError

        _s3 = _storage_service.get_s3_client()
        try:
            _s3.head_bucket(Bucket=settings.s3_ai_action_payloads_bucket)
        except _ClientError as _exc:
            _code = _exc.response.get("Error", {}).get("Code", "")
            if _code in ("404", "NoSuchBucket", "NotFound"):
                _s3.create_bucket(Bucket=settings.s3_ai_action_payloads_bucket)
    except Exception:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception(
            "lifespan: ai-action-payloads bucket init failed (non-fatal)"
        )
    # S2: ensure the attachments bucket exists.
    try:
        from app.services import storage as _storage_service
        from botocore.exceptions import ClientError as _ClientError

        _s3 = _storage_service.get_s3_client()
        try:
            _s3.head_bucket(Bucket=settings.s3_notebook_attachments_bucket)
        except _ClientError as _exc:
            _code = _exc.response.get("Error", {}).get("Code", "")
            if _code in ("404", "NoSuchBucket", "NotFound"):
                _s3.create_bucket(Bucket=settings.s3_notebook_attachments_bucket)
    except Exception:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception(
            "lifespan: notebook-attachments bucket init failed (non-fatal)"
        )
    yield
    await close_client()


app = FastAPI(
    title="QIHANG API",
    version="0.1.0",
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
    openapi_url=None if settings.is_production else "/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(RequestIDMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
if settings.allowed_hosts:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=settings.cors_origin_regex,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Workspace-ID", "X-CSRF-Token"],
)

app.add_exception_handler(ApiError, api_error_handler)
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, unhandled_error_handler)


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "api"}


app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(notebooks.router)
app.include_router(notebooks.pages_router)
app.include_router(notebook_ai.router)
app.include_router(datasets.router)
app.include_router(uploads.router)
app.include_router(model_catalog.router)
app.include_router(models.router)
app.include_router(pipeline.router)
app.include_router(proactive.router)
app.include_router(search.router)
app.include_router(memory_stream.router)
app.include_router(memory.router)
app.include_router(chat.router)
app.include_router(study.router)
app.include_router(realtime.router)
app.include_router(ai_actions.pages_router)
app.include_router(ai_actions.detail_router)
app.include_router(attachments.router)
app.include_router(study_decks.notebooks_decks_router)
app.include_router(study_decks.decks_router)
app.include_router(study_decks.cards_router)
app.include_router(study_ai.router)
