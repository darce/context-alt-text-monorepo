"""Tests for the shared key-minting helper (E15-31 Slice 1).

`mint_api_key` is the single async key-minting seam used by both the operator
CLI and the future /admin router. These tests pin its persistence behaviour
(hash round-trips through the repository), its transaction contract (the caller
owns the commit), and its expiry conversion.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Tenant
from recognition.application.services.api_key_admin_service import mint_api_key
from recognition.config.security import RateLimitTier
from recognition.infrastructure.repositories import SqlAlchemyApiKeyRepository


@pytest.mark.asyncio
async def test_mint_api_key_hash_round_trips_through_repository(db_session: AsyncSession, tenant: Tenant) -> None:
    record, raw = await mint_api_key(
        db_session,
        tenant_id=tenant.id,
        tier=RateLimitTier.STANDARD,
    )

    hashed = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    repo = SqlAlchemyApiKeyRepository(db_session)
    found = await repo.get_by_hash(hashed)

    assert found is not None
    assert found.id == record.id
    assert str(found.tenant_id) == str(tenant.id)
    assert str(record.tenant_id) == str(tenant.id)


@pytest.mark.asyncio
async def test_mint_api_key_does_not_commit(db_session: AsyncSession, tenant: Tenant, monkeypatch) -> None:
    # The caller owns the transaction. Spy on commit to prove mint_api_key
    # never invokes it; the row must still be visible in-session via flush.
    commits = 0
    original_commit = db_session.commit

    async def _counting_commit() -> None:
        nonlocal commits
        commits += 1
        await original_commit()

    monkeypatch.setattr(db_session, "commit", _counting_commit)

    record, raw = await mint_api_key(
        db_session,
        tenant_id=tenant.id,
        tier=RateLimitTier.STANDARD,
    )

    assert commits == 0

    # Visible in-session before any commit (repository flushed the insert).
    hashed = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    found = await SqlAlchemyApiKeyRepository(db_session).get_by_hash(hashed)
    assert found is not None
    assert found.id == record.id


@pytest.mark.asyncio
async def test_mint_api_key_expiry_conversion(db_session: AsyncSession, tenant: Tenant) -> None:
    # None -> no expiry.
    record_none, _ = await mint_api_key(
        db_session,
        tenant_id=tenant.id,
        tier=RateLimitTier.STANDARD,
        expires_in_days=None,
    )
    assert record_none.expires_at is None

    # 7 days -> expires_at roughly 7 days out.
    before = datetime.now(tz=UTC)
    record_7, _ = await mint_api_key(
        db_session,
        tenant_id=tenant.id,
        tier=RateLimitTier.STANDARD,
        expires_in_days=7,
    )
    after = datetime.now(tz=UTC)

    assert record_7.expires_at is not None
    expires_at = record_7.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)

    assert before + timedelta(days=7) - timedelta(seconds=5) <= expires_at
    assert expires_at <= after + timedelta(days=7) + timedelta(seconds=5)
