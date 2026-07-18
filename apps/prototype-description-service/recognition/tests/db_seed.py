"""Test-only seeding of ``MediaIdentity`` ancestor rows (INFRA-3).

Production repository write paths no longer fabricate placeholder
``MediaIdentity`` rows; the foreign key enforces identity integrity. Integration
tests that legitimately need an identity seed it explicitly with this helper,
which carries the fabrication logic formerly living in
``recognition.infrastructure.repositories._helpers.ensure_media_identity``.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from db.models import MediaIdentity
from db.settings import get_database_settings
from recognition.infrastructure.repositories._helpers import coerce_uuid

_DB_SETTINGS = get_database_settings()


async def ensure_media_identity(
    session: AsyncSession,
    tenant_id: uuid.UUID | str,
    identity_id: uuid.UUID | str | None,
) -> None:
    """Create a placeholder ``MediaIdentity`` so FK-bound writes can be exercised."""
    identity_uuid = coerce_uuid(identity_id)
    if identity_uuid is None:
        return

    if await session.get(MediaIdentity, identity_uuid):
        return

    media = MediaIdentity(
        id=identity_uuid,
        tenant_id=coerce_uuid(tenant_id),
        media_id=abs(identity_uuid.int) % 1_000_000,
        media_url="http://example.test/media.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=1,
        bbox_height=1,
        confidence=1.0,
        embedding=[0.0] * _DB_SETTINGS.pgvector_dimension,
        embedding_model="buffalo_l@insightface",
    )
    session.add(media)
    await session.flush()
    await session.refresh(media)
