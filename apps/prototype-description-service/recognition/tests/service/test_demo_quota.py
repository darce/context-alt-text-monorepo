"""Demo recognition quota enforcement (DS3-BR-02 / DS-2)."""

from __future__ import annotations

import asyncio
import hashlib

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.models import DemoInstance
from recognition.application.services.demo_provisioning_service import (
    DemoQuotaExceededError,
    provision_demo,
    try_consume_demo_quota,
)


@pytest.mark.asyncio
async def test_demo_quota_consume_increments_used(db_session: AsyncSession) -> None:
    result = await provision_demo(db_session, label="Q", seed="default", recognition_quota=5)
    await db_session.commit()

    ok = await try_consume_demo_quota(db_session, api_key_hash=result.instance.api_key_ref)
    await db_session.commit()
    assert ok is True

    loaded = await db_session.get(DemoInstance, result.instance.slug)
    assert loaded is not None
    assert loaded.recognition_used == 1


@pytest.mark.asyncio
async def test_demo_quota_non_demo_key_is_noop(db_session: AsyncSession) -> None:
    fake_hash = hashlib.sha256(b"not-a-demo-key").hexdigest()
    ok = await try_consume_demo_quota(db_session, api_key_hash=fake_hash)
    assert ok is False


@pytest.mark.asyncio
async def test_demo_quota_rejects_at_cap(db_session: AsyncSession) -> None:
    result = await provision_demo(db_session, label="Cap", seed="default", recognition_quota=2)
    await db_session.commit()

    assert await try_consume_demo_quota(db_session, api_key_hash=result.instance.api_key_ref)
    assert await try_consume_demo_quota(db_session, api_key_hash=result.instance.api_key_ref)
    await db_session.commit()

    with pytest.raises(DemoQuotaExceededError):
        await try_consume_demo_quota(db_session, api_key_hash=result.instance.api_key_ref)

    loaded = await db_session.get(DemoInstance, result.instance.slug)
    assert loaded is not None
    assert loaded.recognition_used == 2


@pytest.mark.asyncio
async def test_demo_quota_no_lost_update_under_concurrency(db_session: AsyncSession) -> None:
    """Concurrent consumes must not overshoot quota (atomic UPDATE, not RMW)."""
    result = await provision_demo(db_session, label="Race", seed="default", recognition_quota=10)
    await db_session.commit()
    key_hash = result.instance.api_key_ref
    slug = result.instance.slug

    # Bind new short-lived sessions off the same engine (StaticPool shared DB).
    engine = db_session.bind
    assert engine is not None
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    async def _attempt() -> str:
        async with factory() as session:
            try:
                await try_consume_demo_quota(session, api_key_hash=key_hash)
                await session.commit()
                return "ok"
            except DemoQuotaExceededError:
                await session.rollback()
                return "quota"

    outcomes = await asyncio.gather(*[_attempt() for _ in range(20)])
    assert outcomes.count("ok") == 10
    assert outcomes.count("quota") == 10

    async with factory() as session:
        loaded = await session.get(DemoInstance, slug)
        assert loaded is not None
        assert loaded.recognition_used == 10
