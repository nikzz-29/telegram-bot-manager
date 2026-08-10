"""Custom SQLAlchemy column types.

DECISION: enums are stored as plain short strings rather than native PostgreSQL
enums, so adding a variant ships without a migration. But a bare `String` column
hands back a raw `str` on read, which makes every `Mapped[Plan]` annotation a
lie — `chat.plan.value` then raises `AttributeError` at runtime while mypy stays
happy. `StrEnumType` closes that gap: it writes the string and reads back the
enum member, so the annotation and the runtime type agree everywhere.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from sqlalchemy import Dialect, String, TypeDecorator


class StrEnumType(TypeDecorator[Any]):
    """A `VARCHAR` column that round-trips a `StrEnum` member.

    Unknown values coming back from the database (a variant removed in code but
    still present in old rows) fall back to the raw string rather than raising,
    so a stale row can still be read and repaired instead of breaking the query.
    """

    impl = String
    cache_ok = True

    def __init__(self, enum_class: type[StrEnum], length: int = 32) -> None:
        self.enum_class = enum_class
        self.length = length
        super().__init__(length=length)

    def process_bind_param(self, value: Any, dialect: Dialect) -> str | None:
        if value is None:
            return None
        if isinstance(value, StrEnum):
            return value.value
        return str(value)

    def process_result_value(self, value: Any, dialect: Dialect) -> Any:
        if value is None:
            return None
        try:
            return self.enum_class(value)
        except ValueError:
            return value

    def copy(self, **kwargs: Any) -> StrEnumType:
        return StrEnumType(self.enum_class, length=self.length)


__all__ = ["StrEnumType"]
