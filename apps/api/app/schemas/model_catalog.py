from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ModelCatalogOut(BaseModel):
    id: str
    model_id: str
    display_name: str
    provider: str
    category: str
    description: str
    capabilities: list[Any]
    context_window: int
    max_output: int
    input_price: float
    output_price: float
    is_active: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime
    canonical_model_id: str | None = None
    provider_display: str | None = None
    official_group_key: str | None = None
    official_group: str | None = None
    official_category_key: str | None = None
    official_category: str | None = None
    official_order: int | None = None
    official_url: str | None = None
    aliases: list[str] = []
    pipeline_slot: str | None = None
    is_selectable_in_console: bool | None = None


class ModelCatalogDetailOut(ModelCatalogOut):
    input_modalities: list[str]
    output_modalities: list[str]
    supports_function_calling: bool
    supports_web_search: bool
    supports_structured_output: bool
    supports_cache: bool
    supported_tools: list[str] = []
    supported_features: list[str] = []
    batch_input_price: float | None = None
    batch_output_price: float | None = None
    cache_read_price: float | None = None
    cache_write_price: float | None = None
    price_unit: str
    price_note: str | None = None


class ModelCatalogTaxonomyOut(BaseModel):
    key: str
    label: str
    group_key: str | None = None
    group_label: str | None = None
    group: str | None = None
    order: int
    count: int


class ModelCatalogDiscoverItemOut(BaseModel):
    canonical_model_id: str
    model_id: str
    display_name: str
    provider: str
    provider_display: str
    official_group_key: str | None = None
    official_group: str | None = None
    official_category_key: str | None = None
    official_category: str | None = None
    official_order: int | None = None
    description: str
    input_modalities: list[str] = []
    output_modalities: list[str] = []
    supported_tools: list[str] = []
    supported_features: list[str] = []
    official_url: str | None = None
    aliases: list[str] = []
    pipeline_slot: str | None = None
    is_selectable_in_console: bool | None = None


class ModelCatalogDiscoverOut(BaseModel):
    taxonomy: list[ModelCatalogTaxonomyOut]
    items: list[ModelCatalogDiscoverItemOut]
