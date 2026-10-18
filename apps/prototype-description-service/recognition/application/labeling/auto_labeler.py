"""Auto-labeling helpers for high-confidence clusters."""

from __future__ import annotations

import uuid

from sqlalchemy import update
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Tenant
from recognition.application.settings.clustering import AutoLabelSettings


async def allocate_person_label(
    tenant_id: str,
    session: AsyncSession,
    prefix: str = "Person",
) -> str:
    """Atomically allocate next "Person N" label for tenant.

    Uses UPDATE...RETURNING for concurrency safety.

    Args:
        tenant_id: Tenant UUID string.
        session: Active database session.
        prefix: Label prefix (default "Person").

    Returns:
        Label string like "Person 1", "Person 2", etc.

    Raises:
        ValueError: If tenant_id is not a valid UUID string.
        NoResultFound: If tenant doesn't exist.
    """
    try:
        tenant_uuid = uuid.UUID(tenant_id)
    except ValueError as exc:
        raise ValueError("tenant_id must be a valid UUID string") from exc

    stmt = (
        update(Tenant)
        .where(Tenant.id == tenant_uuid)
        .values(next_person_number=Tenant.next_person_number + 1)
        .returning(Tenant.next_person_number)
    )
    result = await session.execute(stmt)
    try:
        next_number = result.scalar_one()
    except NoResultFound as exc:
        raise NoResultFound(f"Tenant not found for id={tenant_id}") from exc
    return f"{prefix} {next_number - 1}"


def should_auto_label(
    *,
    member_count: int,
    similarities: list[float],
    algorithm: str,
    settings: AutoLabelSettings,
) -> bool:
    """Determine if a new cluster should be auto-labeled."""
    if not settings.enabled:
        return False

    if algorithm == "manual":
        return False

    if member_count < settings.min_members:
        return False

    if not similarities:
        return False

    avg_similarity = sum(similarities) / len(similarities)
    return avg_similarity >= settings.similarity_floor
