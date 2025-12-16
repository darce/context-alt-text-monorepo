"""
Canonical report builder for the regression harness.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy.ext.asyncio import AsyncSession


async def generate_canonical_report(
    session: AsyncSession,
    *,
    tenant_id: str,
    run_id: str | None = None,
    media_ids: Iterable[int] | None = None,
    roster_id: str | None = None,
    dataset_name: str | None = None,
    dataset_notes: str | None = None,
) -> dict[str, object]:
    """Generate the canonical report JSON payload for a tenant/dataset.

    Args:
        session: Async SQLAlchemy session.
        tenant_id: Tenant UUID string.
        run_id: Optional recognition_run UUID string to attach as the baseline run.
        media_ids: Optional dataset filter (media IDs).
        roster_id: Optional dataset filter (roster UUID).
        dataset_name: Optional human-friendly dataset name.
        dataset_notes: Optional dataset notes.

    Returns:
        dict[str, object]: Canonical report payload (JSON-serializable).
    """
    raise NotImplementedError("TODO: implement generate_canonical_report")
