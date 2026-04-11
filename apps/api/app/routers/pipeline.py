from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import (
    get_current_user,
    get_current_workspace_id,
    get_db_session,
    require_csrf_protection,
    require_workspace_write_access,
)
from app.core.errors import ApiError
from app.models import ModelCatalog, PipelineConfig, Project, User
from app.routers.utils import get_project_in_workspace_or_404
from app.schemas.pipeline import PipelineConfigOut, PipelineConfigUpdate, PipelineOut
from app.services.pipeline_models import (
    DEFAULT_PIPELINE_MODELS,
    PIPELINE_SLOT_ORDER,
    ensure_project_pipeline_defaults,
    is_valid_catalog_model_for_slot,
)

router = APIRouter(prefix="/api/v1/pipeline", tags=["pipeline"])


def _ensure_pipeline_defaults(db: Session, project_id: str) -> bool:
    return ensure_project_pipeline_defaults(db, project_id)


def _build_pipeline_items(
    *,
    project: Project,
    configs: list[PipelineConfig],
) -> list[PipelineConfigOut]:
    now = datetime.now(timezone.utc)
    configs_by_type = {config.model_type: config for config in configs}
    items: list[PipelineConfigOut] = []
    for model_type in PIPELINE_SLOT_ORDER:
        config = configs_by_type.get(model_type)
        if config:
            items.append(PipelineConfigOut.model_validate(config, from_attributes=True))
            continue
        items.append(
            PipelineConfigOut(
                id=f"default:{project.id}:{model_type}",
                project_id=project.id,
                model_type=model_type,
                model_id=DEFAULT_PIPELINE_MODELS[model_type],
                config_json={},
                created_at=project.created_at or now,
                updated_at=project.updated_at or project.created_at or now,
            )
        )
    return items


@router.get("", response_model=PipelineOut)
def get_pipeline(
    project_id: str = Query(...),
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
) -> PipelineOut:
    _ = current_user
    project = get_project_in_workspace_or_404(db, project_id, workspace_id)

    changed = _ensure_pipeline_defaults(db, project_id)
    configs = db.query(PipelineConfig).filter(PipelineConfig.project_id == project_id).all()
    if changed:
        db.commit()
    return PipelineOut(items=_build_pipeline_items(project=project, configs=configs))


@router.patch("", response_model=PipelineConfigOut)
@router.put("", response_model=PipelineConfigOut)
def upsert_pipeline_config(
    payload: PipelineConfigUpdate,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _: None = Depends(require_csrf_protection),
) -> PipelineConfigOut:
    project = get_project_in_workspace_or_404(db, payload.project_id, workspace_id)
    _ensure_pipeline_defaults(db, payload.project_id)

    # Validate that the model_id exists in the catalog
    catalog_entry = (
        db.query(ModelCatalog)
        .filter(ModelCatalog.model_id == payload.model_id, ModelCatalog.is_active.is_(True))
        .first()
    )
    if not catalog_entry:
        raise ApiError("invalid_model", "Model not found in active catalog", status_code=400)
    if not is_valid_catalog_model_for_slot(payload.model_type, catalog_entry):
        if payload.model_type == "realtime":
            raise ApiError(
                "invalid_model_type",
                "Realtime slot requires a full-duplex realtime model",
                status_code=400,
            )
        if payload.model_type == "realtime_asr":
            raise ApiError(
                "invalid_model_type",
                "Realtime ASR slot requires a realtime speech recognition model",
                status_code=400,
            )
        if payload.model_type == "realtime_tts":
            raise ApiError(
                "invalid_model_type",
                "Realtime TTS slot requires a realtime speech synthesis model",
                status_code=400,
            )
        if payload.model_type == "llm":
            raise ApiError(
                "invalid_model_type",
                "Chat slot only accepts non-realtime LLM models",
                status_code=400,
            )
        if payload.model_type == "asr":
            raise ApiError(
                "invalid_model_type",
                "Standard ASR slot only accepts non-realtime speech recognition models",
                status_code=400,
            )
        if payload.model_type == "tts":
            raise ApiError(
                "invalid_model_type",
                "Standard TTS slot only accepts non-realtime speech synthesis models",
                status_code=400,
            )
        raise ApiError("invalid_model_type", "Model category does not match pipeline slot", status_code=400)

    now = datetime.now(timezone.utc)
    config = (
        db.query(PipelineConfig)
        .filter(
            PipelineConfig.project_id == payload.project_id,
            PipelineConfig.model_type == payload.model_type,
        )
        .first()
    )
    if config is None:
        config = PipelineConfig(
            project_id=payload.project_id,
            model_type=payload.model_type,
            model_id=payload.model_id,
            config_json=payload.config_json or {},
        )
        config.created_at = now
        db.add(config)
    else:
        config.model_id = payload.model_id
        config.config_json = payload.config_json or {}
    config.updated_at = now

    if (
        payload.model_type == "llm"
        and project.default_chat_mode == "synthetic_realtime"
        and "vision" not in [cap.lower() for cap in (catalog_entry.capabilities or [])]
    ):
        project.default_chat_mode = "standard"
        project.updated_at = now

    db.commit()
    db.refresh(config)
    return PipelineConfigOut.model_validate(config, from_attributes=True)
