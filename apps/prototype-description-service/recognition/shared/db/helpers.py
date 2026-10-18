"""Helper utilities for typed database interactions."""

from __future__ import annotations

from typing import Any

from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession


def get_rowcount(result: CursorResult[Any]) -> int:
    """Return a safe integer rowcount for DML statements."""
    rowcount = getattr(result, "rowcount", 0) or 0
    return int(rowcount)


async def execute_dml(
    session: AsyncSession,
    stmt,
    params: dict[str, Any] | None = None,
) -> CursorResult[Any]:
    """Execute a DML statement and return a typed CursorResult."""
    if params is None:
        result = await session.execute(stmt)
    else:
        result = await session.execute(stmt, params)
    return result  # type: ignore[return-value]
