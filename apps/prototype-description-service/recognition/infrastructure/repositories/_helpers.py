"""Shared repository helper utilities."""

from __future__ import annotations

import uuid
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from db.models import MediaIdentity
from db.settings import get_database_settings

_DB_SETTINGS = get_database_settings()


def coerce_uuid(
    value: str | uuid.UUID | None,
    *,
    on_failure: Literal["deterministic", "none"] = "deterministic",
) -> uuid.UUID | None:
    """Convert a string/UUID to ``uuid.UUID`` with configurable failure behavior."""
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        if on_failure == "none":
            return None
        # Keep short legacy identifiers storable by deriving a deterministic UUID.
        return uuid.uuid5(uuid.NAMESPACE_URL, str(value))


async def ensure_media_identity(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    identity_id: uuid.UUID | None,
) -> None:
    """Create a placeholder ``MediaIdentity`` for repository write paths."""
    if identity_id is None:
        return

    existing = await session.get(MediaIdentity, identity_id)
    if existing:
        return

    media = MediaIdentity(
        id=identity_id,
        tenant_id=tenant_id,
        media_id=abs(identity_id.int) % 1_000_000,
        media_url="http://example.test/media.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=1,
        bbox_height=1,
        confidence=1.0,
        embedding=[0.0] * _DB_SETTINGS.pgvector_dimension,
    )
    session.add(media)
    await session.flush()
    await session.refresh(media)
