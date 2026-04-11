from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from sqlalchemy.orm import Session

from app.models import ModelCatalog, PipelineConfig


PipelineModelType = Literal["llm", "asr", "tts", "vision", "realtime", "realtime_asr", "realtime_tts"]

PIPELINE_SLOT_ORDER: tuple[PipelineModelType, ...] = (
    "llm",
    "asr",
    "tts",
    "vision",
    "realtime",
    "realtime_asr",
    "realtime_tts",
)
DEFAULT_PIPELINE_MODELS: dict[PipelineModelType, str] = {
    "llm": "qwen3.5-plus",
    "asr": "paraformer-v2",
    "tts": "cosyvoice-v1",
    "vision": "qwen-vl-plus",
    "realtime": "qwen3-omni-flash-realtime",
    "realtime_asr": "qwen3-asr-flash-realtime",
    "realtime_tts": "qwen3-tts-flash-realtime",
}
LEGACY_PIPELINE_MODEL_REPLACEMENTS: dict[str, str] = {
    "qwen3-flash": "qwen3.5-flash",
}


def supports_full_duplex_realtime(capabilities: list[str] | None) -> bool:
    capability_set = {cap.lower() for cap in capabilities or []}
    return {"realtime", "audio_input", "audio_output"}.issubset(capability_set)


def supports_realtime_asr(capabilities: list[str] | None) -> bool:
    capability_set = {cap.lower() for cap in capabilities or []}
    return "realtime" in capability_set


def supports_realtime_tts(capabilities: list[str] | None) -> bool:
    capability_set = {cap.lower() for cap in capabilities or []}
    return "realtime" in capability_set


def is_valid_catalog_model_for_slot(model_type: PipelineModelType, catalog_entry: ModelCatalog | None) -> bool:
    if catalog_entry is None:
        return False
    if model_type == "realtime":
        return catalog_entry.category == "llm" and supports_full_duplex_realtime(catalog_entry.capabilities)
    if model_type == "llm":
        return catalog_entry.category == "llm" and not supports_full_duplex_realtime(catalog_entry.capabilities)
    if model_type == "realtime_asr":
        return catalog_entry.category == "asr" and supports_realtime_asr(catalog_entry.capabilities)
    if model_type == "realtime_tts":
        return catalog_entry.category == "tts" and supports_realtime_tts(catalog_entry.capabilities)
    if model_type == "asr":
        return catalog_entry.category == "asr" and not supports_realtime_asr(catalog_entry.capabilities)
    if model_type == "tts":
        return catalog_entry.category == "tts" and not supports_realtime_tts(catalog_entry.capabilities)
    return catalog_entry.category == model_type


def list_catalog_models_for_slot(
    db: Session,
    *,
    model_type: PipelineModelType | None = None,
) -> list[ModelCatalog]:
    items = db.query(ModelCatalog).filter(ModelCatalog.is_active.is_(True)).order_by(ModelCatalog.sort_order).all()
    if model_type is None:
        return items
    return [item for item in items if is_valid_catalog_model_for_slot(model_type, item)]


def ensure_project_pipeline_defaults(db: Session, project_id: str) -> bool:
    existing = {
        config.model_type: config
        for config in db.query(PipelineConfig).filter(PipelineConfig.project_id == project_id).all()
    }
    now = datetime.now(timezone.utc)
    changed = False

    for config in existing.values():
        replacement_model_id = LEGACY_PIPELINE_MODEL_REPLACEMENTS.get(config.model_id)
        if not replacement_model_id:
            continue
        replacement_entry = (
            db.query(ModelCatalog)
            .filter(ModelCatalog.model_id == replacement_model_id, ModelCatalog.is_active.is_(True))
            .first()
        )
        if not is_valid_catalog_model_for_slot(config.model_type, replacement_entry):
            continue
        config.model_id = replacement_model_id
        config.updated_at = now
        changed = True

    for model_type in PIPELINE_SLOT_ORDER:
        if model_type in existing:
            continue
        config = PipelineConfig(
            project_id=project_id,
            model_type=model_type,
            model_id=DEFAULT_PIPELINE_MODELS[model_type],
            config_json={},
        )
        config.created_at = now
        config.updated_at = now
        db.add(config)
        existing[model_type] = config
        changed = True

    llm_config = existing.get("llm")
    realtime_config = existing.get("realtime")
    asr_config = existing.get("asr")
    realtime_asr_config = existing.get("realtime_asr")
    tts_config = existing.get("tts")
    realtime_tts_config = existing.get("realtime_tts")
    if llm_config is None:
        if changed:
            db.flush()
        return changed

    llm_catalog_entry = (
        db.query(ModelCatalog)
        .filter(ModelCatalog.model_id == llm_config.model_id, ModelCatalog.is_active.is_(True))
        .first()
    )
    if llm_catalog_entry and supports_full_duplex_realtime(llm_catalog_entry.capabilities):
        # Legacy compatibility: earlier UI allowed writing realtime-only models
        # into the generic llm slot, which breaks plain text chat. Move that
        # model into the dedicated realtime slot and reset llm to a safe default.
        if realtime_config is not None and realtime_config.model_id == DEFAULT_PIPELINE_MODELS["realtime"]:
            realtime_config.model_id = llm_config.model_id
            realtime_config.updated_at = now
            changed = True
        llm_config.model_id = DEFAULT_PIPELINE_MODELS["llm"]
        llm_config.updated_at = now
        changed = True

    if asr_config is not None:
        asr_catalog_entry = (
            db.query(ModelCatalog)
            .filter(ModelCatalog.model_id == asr_config.model_id, ModelCatalog.is_active.is_(True))
            .first()
        )
        if asr_catalog_entry and supports_realtime_asr(asr_catalog_entry.capabilities):
            if (
                realtime_asr_config is not None
                and realtime_asr_config.model_id == DEFAULT_PIPELINE_MODELS["realtime_asr"]
            ):
                realtime_asr_config.model_id = asr_config.model_id
                realtime_asr_config.updated_at = now
                changed = True
            asr_config.model_id = DEFAULT_PIPELINE_MODELS["asr"]
            asr_config.updated_at = now
            changed = True

    if tts_config is not None:
        tts_catalog_entry = (
            db.query(ModelCatalog)
            .filter(ModelCatalog.model_id == tts_config.model_id, ModelCatalog.is_active.is_(True))
            .first()
        )
        if tts_catalog_entry and supports_realtime_tts(tts_catalog_entry.capabilities):
            if (
                realtime_tts_config is not None
                and realtime_tts_config.model_id == DEFAULT_PIPELINE_MODELS["realtime_tts"]
            ):
                realtime_tts_config.model_id = tts_config.model_id
                realtime_tts_config.updated_at = now
                changed = True
            tts_config.model_id = DEFAULT_PIPELINE_MODELS["tts"]
            tts_config.updated_at = now
            changed = True

    if changed:
        db.flush()
    return changed


def resolve_pipeline_model_id(
    db: Session,
    *,
    project_id: str,
    model_type: PipelineModelType,
) -> str:
    config = (
        db.query(PipelineConfig)
        .filter(PipelineConfig.project_id == project_id, PipelineConfig.model_type == model_type)
        .first()
    )
    if not config:
        return DEFAULT_PIPELINE_MODELS[model_type]

    catalog_entry = (
        db.query(ModelCatalog)
        .filter(ModelCatalog.model_id == config.model_id, ModelCatalog.is_active.is_(True))
        .first()
    )
    if is_valid_catalog_model_for_slot(model_type, catalog_entry):
        return config.model_id

    return DEFAULT_PIPELINE_MODELS[model_type]
