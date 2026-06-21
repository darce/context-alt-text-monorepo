"""Shared async key-minting helper for admin surfaces (CLI + /admin router).

Mints a raw API key, hashes it with the configured algorithm, persists the
record via `SqlAlchemyApiKeyRepository`, and returns `(record, raw)`. The raw
key is only available here at mint time; it is unrecoverable from the stored
hash. Callers own the transaction — this helper never commits.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ApiKey
from recognition.config.security import RateLimitTier, get_security_settings
from recognition.infrastructure.repositories.api_key_repository import SqlAlchemyApiKeyRepository

_MIN_EXPIRES_IN_DAYS = 1
_MAX_EXPIRES_IN_DAYS = 36500  # ~100 years; bounds the timedelta so it cannot OverflowError


async def mint_api_key(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    tier: RateLimitTier,
    expires_in_days: int | None = None,
) -> tuple[ApiKey, str]:
    """Mint and persist an API key, returning the row and the one-time raw key.

    Does NOT commit; the caller owns the transaction.
    """
    raw = secrets.token_urlsafe(32)
    digest = hashlib.new(get_security_settings().api_key_hash_algorithm)
    digest.update(raw.encode("utf-8"))
    hashed = digest.hexdigest()

    expires_at: datetime | None = None
    if expires_in_days is not None:
        if not (_MIN_EXPIRES_IN_DAYS <= expires_in_days <= _MAX_EXPIRES_IN_DAYS):
            raise ValueError(
                f"expires_in_days must be between {_MIN_EXPIRES_IN_DAYS} and {_MAX_EXPIRES_IN_DAYS}"
            )
        expires_at = datetime.now(tz=UTC) + timedelta(days=int(expires_in_days))

    record = await SqlAlchemyApiKeyRepository(session).create(
        tenant_id=tenant_id,
        hashed_key=hashed,
        rate_limit_tier=tier,
        expires_at=expires_at,
    )
    return record, raw


__all__ = ["mint_api_key"]
