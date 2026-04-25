from __future__ import annotations

from typing import Any

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base_class import Base, TimestampMixin, UUIDPrimaryKeyMixin, UpdatedAtMixin


class ModelCatalog(Base, UUIDPrimaryKeyMixin, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "model_catalog"

    model_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    capabilities: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    context_window: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_output: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    input_price: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    output_price: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class PipelineConfig(Base, UUIDPrimaryKeyMixin, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "pipeline_configs"
    __table_args__ = (
        UniqueConstraint("project_id", "model_type", name="uq_pipeline_configs_project_type"),
    )

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    model_type: Mapped[str] = mapped_column(String(20), nullable=False)
    model_id: Mapped[str] = mapped_column(String(100), nullable=False)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


Index("idx_model_catalog_category", ModelCatalog.category)

Index("idx_model_catalog_provider", ModelCatalog.provider)

Index("idx_pipeline_configs_project", PipelineConfig.project_id)


__all__ = [
    "ModelCatalog",
    "PipelineConfig",
]
