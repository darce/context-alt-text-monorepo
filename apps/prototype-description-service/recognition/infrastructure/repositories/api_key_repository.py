"""Repository for API key records."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ApiKey

ClassifyResult = Literal["active", "expired", "revoked", "unknown"]


def _as_utc(value: datetime) -> datetime:
    """Coerce a naive timestamp (SQLite returns these) to UTC for safe comparison."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


class SqlAlchemyApiKeyRepository:
    """API key persistence helpers."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_hash(self, api_key_hash: str) -> ApiKey | None:
        """Return active API key record matching the provided hash.

        Expired (`expires_at < now()`) and revoked (`revoked_at IS NOT NULL`)
        keys are filtered out so callers never mistake them for valid auth.
        """
        stmt = select(ApiKey).where(
            and_(
                ApiKey.api_key_hash == api_key_hash,
                ApiKey.revoked_at.is_(None),
            )
        )
        result = await self._session.execute(stmt)
        record = result.scalar_one_or_none()
        if record is None:
            return None
        expires_at = getattr(record, "expires_at", None)
        if expires_at is not None and _as_utc(expires_at) <= datetime.now(tz=UTC):
            return None
        return record

    async def classify_by_hash(self, api_key_hash: str) -> ClassifyResult:
        """Classify a hash as active/expired/revoked/unknown without hiding it.

        Used by the auth boundary to emit a descriptive 401 reason when a key
        is present in the store but no longer valid.
        """
        result = await self._session.execute(select(ApiKey).where(ApiKey.api_key_hash == api_key_hash))
        record = result.scalar_one_or_none()
        if record is None:
            return "unknown"
        if record.revoked_at is not None:
            return "revoked"
        if record.expires_at is not None and _as_utc(record.expires_at) <= datetime.now(tz=UTC):
            return "expired"
        return "active"

    async def create(
        self,
        *,
        tenant_id: uuid.UUID | str,
        hashed_key: str,
        rate_limit_tier: object | None = None,
        expires_at: datetime | None = None,
    ) -> ApiKey:
        """Insert a new API key and return the persisted row."""
        tier_value: str | None
        if rate_limit_tier is None:
            tier_value = None
        elif hasattr(rate_limit_tier, "value"):
            tier_value = str(rate_limit_tier.value)
        else:
            tier_value = str(rate_limit_tier)

        tid = tenant_id if isinstance(tenant_id, uuid.UUID) else uuid.UUID(str(tenant_id))
        record = ApiKey(
            tenant_id=tid,
            api_key_hash=hashed_key,
            rate_limit_tier=tier_value,
            expires_at=expires_at,
        )
        self._session.add(record)
        await self._session.flush()
        await self._session.refresh(record)
        return record

    async def list_for_tenant(self, tenant_id: uuid.UUID | str, *, include_revoked: bool = False) -> list[ApiKey]:
        """Return API keys for a tenant, optionally including revoked rows."""
        tid = tenant_id if isinstance(tenant_id, uuid.UUID) else uuid.UUID(str(tenant_id))
        stmt = select(ApiKey).where(ApiKey.tenant_id == tid).order_by(ApiKey.created_at)
        if not include_revoked:
            stmt = stmt.where(ApiKey.revoked_at.is_(None))
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def revoke(self, api_key_id: uuid.UUID | str, *, now: datetime | None = None) -> ApiKey:
        """Soft-revoke a key by setting `revoked_at`. Raises LookupError if absent."""
        kid = api_key_id if isinstance(api_key_id, uuid.UUID) else uuid.UUID(str(api_key_id))
        record = await self._session.get(ApiKey, kid)
        if record is None:
            raise LookupError(f"api key not found: {api_key_id}")
        record.revoked_at = now or datetime.now(tz=UTC)
        await self._session.flush()
        await self._session.refresh(record)
        return record

    async def touch(self, api_key: ApiKey) -> None:
        """Update last_used_at for bookkeeping."""
        api_key.last_used_at = datetime.now(tz=UTC)
        await self._session.flush()

    async def touch_by_id(self, api_key_id: str) -> None:
        """Update last_used_at for a record identified by id."""
        await self._session.execute(
            update(ApiKey).where(ApiKey.id == uuid.UUID(str(api_key_id))).values(last_used_at=datetime.now(tz=UTC))
        )


__all__ = ["SqlAlchemyApiKeyRepository"]
