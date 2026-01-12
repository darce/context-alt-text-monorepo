"""Shared helpers for worker handlers."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from db.models import IdentityClusteringJob
from db.tenant_context import enable_rls_bypass, set_tenant_context


def compute_progress(completed: int, total: int) -> float:
    """Return normalized progress within [0, 1]."""
    if total <= 0:
        return 0.0
    return min(1.0, completed / total)


def coerce_str_list(value: object) -> list[str]:
    """Convert list-like payloads to string lists."""
    if not isinstance(value, list):
        return []
    results: list[str] = []
    for item in value:
        if isinstance(item, str):
            results.append(item)
        elif isinstance(item, uuid.UUID):
            results.append(str(item))
    return results


def coerce_optional_str(value: object) -> str | None:
    """Return string or None from payload values."""
    if value is None:
        return None
    return str(value)


def coerce_int(value: object, *, default: int) -> int:
    """Return int from payload values with a default fallback."""
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, (str, bytes, bytearray)):
        try:
            return int(value)
        except ValueError:
            return default
    return default


async def ensure_job_context(*, session: AsyncSession, job: IdentityClusteringJob) -> None:
    """Reassert tenant context before updating clustering job rows."""
    await set_tenant_context(session, job.tenant_id)
    await enable_rls_bypass(session)
