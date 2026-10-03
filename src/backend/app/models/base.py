from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import DateTime, Enum as SAEnum, func
from sqlalchemy.orm import Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def enum_type(enum_cls: type[StrEnum]) -> SAEnum:
    return SAEnum(
        enum_cls,
        native_enum=False,
        length=32,
        values_callable=lambda members: [m.value for m in members],
        validate_strings=True,
        create_constraint=True,
        name=f"ck_{enum_cls.__name__.lower()}",
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
