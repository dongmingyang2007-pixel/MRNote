from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db_session
from app.core.errors import ApiError
from app.models import ModelCatalog, User
from app.schemas.model_catalog import (
    ModelCatalogDetailOut,
    ModelCatalogDiscoverItemOut,
    ModelCatalogDiscoverOut,
    ModelCatalogOut,
)
from app.services.pipeline_models import list_catalog_models_for_slot
from app.services.qwen_official_catalog import find_model, list_discover_models, list_taxonomy

router = APIRouter(prefix="/api/v1/models/catalog", tags=["model-catalog"])

PROVIDER_DISPLAY_NAMES = {
    "qwen": "千问 · 阿里云",
    "alibaba": "千问 · 阿里云",
    "deepseek": "DeepSeek",
}

LEGACY_MODEL_ID_ALIASES: dict[str, tuple[str, ...]] = {
    "qwen3-plus": ("qwen3.5-plus",),
}

LEGACY_DETAIL_OVERRIDES: dict[str, dict[str, object]] = {
    "deepseek-v3.2": {
        "supported_tools": ["function_calling", "web_search"],
        "supported_features": ["streaming", "structured_output", "cache"],
        "price_unit": "tokens",
    },
    "deepseek-r1": {
        "supported_tools": [],
        "supported_features": ["deep_thinking"],
        "price_unit": "tokens",
    },
    "sensevoice-v1": {
        "price_unit": "audio",
        "price_note": "免费额度",
    },
    "cosyvoice-v1": {
        "price_unit": "characters",
        "price_note": "按字符计费",
    },
    "sambert-v1": {
        "price_unit": "characters",
        "price_note": "按字符计费",
    },
}

PIPELINE_CATEGORY_VALUES = {"llm", "asr", "tts", "vision", "realtime", "realtime_asr", "realtime_tts"}


def _provider_display_name(provider: str) -> str:
    key = (provider or "").lower()
    for prefix, label in PROVIDER_DISPLAY_NAMES.items():
        if key.startswith(prefix) or prefix in key:
            return label
    return provider


def _synthetic_timestamp() -> datetime:
    return datetime.now(timezone.utc)


def _official_item_to_discover(item: dict[str, Any]) -> ModelCatalogDiscoverItemOut:
    return ModelCatalogDiscoverItemOut(
        canonical_model_id=item["canonical_model_id"],
        model_id=item.get("model_id", item["canonical_model_id"]),
        display_name=item["display_name"],
        provider=item.get("provider", "qwen"),
        provider_display=item["provider_display"],
        official_group_key=item.get("official_group_key"),
        official_group=item.get("official_group"),
        official_category_key=item.get("official_category_key"),
        official_category=item.get("official_category"),
        official_order=item.get("official_order"),
        description=item.get("description", ""),
        input_modalities=list(item.get("input_modalities", [])),
        output_modalities=list(item.get("output_modalities", [])),
        supported_tools=list(item.get("supported_tools", [])),
        supported_features=list(item.get("supported_features", [])),
        official_url=item.get("official_url"),
        aliases=list(item.get("aliases", [])),
        pipeline_slot=item.get("pipeline_slot"),
        is_selectable_in_console=item.get("is_selectable_in_console"),
    )


def _official_item_to_detail(item: dict[str, Any]) -> ModelCatalogDetailOut:
    supported_tools = list(item.get("supported_tools", []))
    supported_features = list(item.get("supported_features", []))
    capabilities = sorted(set(
        list(item.get("input_modalities", []))
        + list(item.get("output_modalities", []))
        + supported_tools
        + supported_features
    ))
    timestamp = _synthetic_timestamp()
    return ModelCatalogDetailOut(
        id=item["canonical_model_id"],
        model_id=item.get("model_id", item["canonical_model_id"]),
        canonical_model_id=item["canonical_model_id"],
        display_name=item["display_name"],
        provider=item.get("provider", "qwen"),
        provider_display=item["provider_display"],
        category=item.get("pipeline_slot") or item["official_category"],
        description=item.get("description", ""),
        capabilities=capabilities,
        context_window=0,
        max_output=0,
        input_price=0.0,
        output_price=0.0,
        is_active=True,
        sort_order=item.get("official_order", 0),
        created_at=timestamp,
        updated_at=timestamp,
        official_group_key=item.get("official_group_key"),
        official_group=item.get("official_group"),
        official_category_key=item.get("official_category_key"),
        official_category=item.get("official_category"),
        official_order=item.get("official_order"),
        official_url=item.get("official_url"),
        aliases=list(item.get("aliases", [])),
        pipeline_slot=item.get("pipeline_slot"),
        is_selectable_in_console=bool(item.get("is_selectable_in_console")),
        input_modalities=list(item.get("input_modalities", [])),
        output_modalities=list(item.get("output_modalities", [])),
        supports_function_calling="function_calling" in supported_tools,
        supports_web_search="web_search" in supported_tools,
        supports_structured_output="structured_output" in supported_features,
        supports_cache="cache" in supported_features,
        supported_tools=supported_tools,
        supported_features=supported_features,
        batch_input_price=None,
        batch_output_price=None,
        cache_read_price=None,
        cache_write_price=None,
        price_unit="tokens",
        price_note=None,
    )


def _derive_legacy_modalities(item: ModelCatalog) -> tuple[list[str], list[str]]:
    capabilities = {str(value).lower() for value in item.capabilities or []}
    if item.category == "llm":
        inputs = ["text"]
        if "vision" in capabilities:
            inputs.append("image")
        if "video" in capabilities:
            inputs.append("video")
        if "audio_input" in capabilities:
            inputs.append("audio")
        outputs = ["text"]
        if "audio_output" in capabilities:
            outputs.append("audio")
        return inputs, outputs
    if item.category == "asr":
        return ["audio"], ["text"]
    if item.category == "tts":
        return ["text"], ["audio"]
    if item.category == "vision":
        inputs = ["image"]
        if "video" in capabilities:
            inputs.append("video")
        return inputs, ["text"]
    return ["text"], ["text"]


def _legacy_pipeline_slot(item: ModelCatalog) -> str | None:
    capabilities = {str(value).lower() for value in item.capabilities or []}
    if item.category == "llm" and {"realtime", "audio_input", "audio_output"}.issubset(capabilities):
        return "realtime"
    if item.category == "asr" and "realtime" in capabilities:
        return "realtime_asr"
    if item.category == "tts" and "realtime" in capabilities:
        return "realtime_tts"
    if item.category in {"llm", "asr", "tts", "vision"}:
        return item.category
    return None


def _build_catalog_summary(item: ModelCatalog, *, category_override: str | None = None) -> ModelCatalogOut:
    official = find_model(item.model_id)
    pipeline_slot = _legacy_pipeline_slot(item)
    base = ModelCatalogOut.model_validate(item, from_attributes=True)
    updates: dict[str, Any] = {
        "provider_display": _provider_display_name(item.provider),
        "pipeline_slot": pipeline_slot,
        "is_selectable_in_console": True,
    }
    if category_override:
        updates["category"] = category_override
        updates["pipeline_slot"] = category_override
    if official:
        official_capabilities = sorted(set(
            list(item.capabilities or [])
            + list(official.get("input_modalities", []))
            + list(official.get("output_modalities", []))
            + list(official.get("supported_tools", []))
            + list(official.get("supported_features", []))
        ))
        updates.update(
            canonical_model_id=official["canonical_model_id"],
            official_group_key=official.get("official_group_key"),
            official_group=official.get("official_group"),
            official_category_key=official.get("official_category_key"),
            official_category=official.get("official_category"),
            official_order=official.get("official_order"),
            official_url=official.get("official_url"),
            aliases=list(official.get("aliases", [])),
            capabilities=official_capabilities,
            pipeline_slot=official.get("pipeline_slot") or updates["pipeline_slot"],
            is_selectable_in_console=bool(official.get("is_selectable_in_console")),
        )
    return base.model_copy(update=updates)


def _build_catalog_detail(item: ModelCatalog) -> ModelCatalogDetailOut:
    official = find_model(item.model_id)
    if official:
        detail = _official_item_to_detail(official)
        return detail.model_copy(
            update={
                "id": item.id,
                "model_id": item.model_id,
                "category": item.category,
                "display_name": official.get("display_name", item.display_name),
                "description": official.get("description", item.description),
                "provider": item.provider,
                "provider_display": _provider_display_name(item.provider),
                "context_window": item.context_window,
                "max_output": item.max_output,
                "input_price": item.input_price,
                "output_price": item.output_price,
                "sort_order": item.sort_order,
                "created_at": item.created_at,
                "updated_at": item.updated_at,
                "is_active": item.is_active,
            }
        )

    overrides = LEGACY_DETAIL_OVERRIDES.get(item.model_id, {})
    input_modalities, output_modalities = _derive_legacy_modalities(item)
    supported_tools = list(overrides.get("supported_tools", []))
    supported_features = list(overrides.get("supported_features", []))

    return ModelCatalogDetailOut(
        **_build_catalog_summary(item).model_dump(),
        input_modalities=input_modalities,
        output_modalities=output_modalities,
        supports_function_calling="function_calling" in supported_tools,
        supports_web_search="web_search" in supported_tools,
        supports_structured_output="structured_output" in supported_features,
        supports_cache="cache" in supported_features,
        supported_tools=supported_tools,
        supported_features=supported_features,
        batch_input_price=None,
        batch_output_price=None,
        cache_read_price=None,
        cache_write_price=None,
        price_unit=str(overrides.get("price_unit", "tokens")),
        price_note=overrides.get("price_note"),
    )


@router.get("", response_model=ModelCatalogDiscoverOut | list[ModelCatalogOut])
def list_catalog(
    category: str | None = Query(default=None),
    view: str | None = Query(default=None),
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> ModelCatalogDiscoverOut | list[ModelCatalogOut]:
    _ = current_user
    normalized_view = (view or "").lower() or None
    normalized_category = (category or "").lower() or None

    if normalized_view == "discover":
        items = [_official_item_to_discover(item) for item in list_discover_models()]
        return ModelCatalogDiscoverOut(taxonomy=list_taxonomy(), items=items)

    if normalized_category in PIPELINE_CATEGORY_VALUES:
        items = list_catalog_models_for_slot(db, model_type=normalized_category)
        category_override = normalized_category
        return [_build_catalog_summary(item, category_override=category_override) for item in items]
    if normalized_category is not None:
        return []

    items = db.query(ModelCatalog).filter(ModelCatalog.is_active.is_(True)).order_by(ModelCatalog.sort_order).all()
    return [_build_catalog_summary(item) for item in items]


@router.get("/{model_id}", response_model=ModelCatalogDetailOut)
def get_catalog_item(
    model_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> ModelCatalogDetailOut:
    _ = current_user

    item = (
        db.query(ModelCatalog)
        .filter(ModelCatalog.id == model_id, ModelCatalog.is_active.is_(True))
        .first()
    )
    if item:
        return _build_catalog_detail(item)

    candidate_ids = [model_id, *LEGACY_MODEL_ID_ALIASES.get(model_id, ())]
    items = (
        db.query(ModelCatalog)
        .filter(
            ModelCatalog.model_id.in_(candidate_ids),
            ModelCatalog.is_active.is_(True),
        )
        .all()
    )
    item_by_model_id = {item.model_id: item for item in items}
    item = next((item_by_model_id[candidate] for candidate in candidate_ids if candidate in item_by_model_id), None)
    if item:
        return _build_catalog_detail(item)

    official = find_model(model_id)
    if official:
        return _official_item_to_detail(official)

    raise ApiError("not_found", "Model not found in catalog", status_code=404)
