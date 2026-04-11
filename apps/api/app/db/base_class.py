from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))


class UpdatedAtMixin:
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class UUIDPrimaryKeyMixin:
    id: Mapped[str] = mapped_column(primary_key=True, default=lambda: str(uuid4()))
