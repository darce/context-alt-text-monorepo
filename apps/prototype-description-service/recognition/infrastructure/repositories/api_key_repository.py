"""Repository for API key records."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ApiKey


class SqlAlchemyApiKeyRepository:
    """API key persistence helpers."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_hash(self, api_key_hash: str) -> ApiKey | None:
        """Return API key record matching the provided hash."""
        result = await self._session.execute(select(ApiKey).where(ApiKey.api_key_hash == api_key_hash))
        return result.scalar_one_or_none()

    async def touch(self, api_key: ApiKey) -> None:
        """Update last_used_at for bookkeeping."""
        api_key.last_used_at = datetime.now(tz=UTC)
        await self._session.flush()


__all__ = ["SqlAlchemyApiKeyRepository"]
