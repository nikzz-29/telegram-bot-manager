"""Shared helper for DML statements that report affected-row counts.

`AsyncSession.execute` is typed as returning `Result`, which has no `rowcount`.
Only `CursorResult` does, and that is always what an UPDATE/DELETE returns — so
the cast is narrowed here once instead of at every call site.
"""

from __future__ import annotations

from typing import cast

from sqlalchemy import CursorResult, Delete, Update
from sqlalchemy.ext.asyncio import AsyncSession


async def execute_dml(session: AsyncSession, statement: Update | Delete) -> int:
    """Run an UPDATE/DELETE and return the number of affected rows."""
    result = cast(CursorResult[None], await session.execute(statement))
    return int(result.rowcount or 0)


__all__ = ["execute_dml"]
