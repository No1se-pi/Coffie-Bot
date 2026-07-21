"""Reusable portable SQLAlchemy column types."""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy import Enum as SAEnum


def enum_type[EnumT: StrEnum](enum_class: type[EnumT], *, name: str, length: int) -> SAEnum:
    """Persist enum values as constrained strings instead of DB-native enum types."""

    return SAEnum(
        enum_class,
        name=name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        values_callable=lambda members: [member.value for member in members],
        length=length,
    )
