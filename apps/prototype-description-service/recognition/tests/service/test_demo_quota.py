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
async def test_demo_quota_http_consume_is_durable_against_later_rollback(
    db_session: AsyncSession,
) -> None:
    """consume_demo_quota_units commits immediately so a later rollback cannot refund."""
    from recognition.interface_adapters.http.deps.demo_quota import consume_demo_quota_units

    result = await provision_demo(db_session, label="Durable", seed="default", recognition_quota=5)
    await db_session.commit()

    consumed = await consume_demo_quota_units(
        db_session, api_key_hash=result.instance.api_key_ref, units=1, durable=True
    )
    assert consumed is True
    # Simulate a later request failure that rolls back the request session.
    await db_session.rollback()

    loaded = await db_session.get(DemoInstance, result.instance.slug)
    assert loaded is not None
    assert loaded.recognition_used == 1


@pytest.mark.asyncio
async def test_demo_quota_consume_returns_false_for_non_demo_key(
    db_session: AsyncSession,
) -> None:
    """HTTP helper returns False when hash is not a demo registry key (DS2B-PM-S1-04)."""
    from recognition.interface_adapters.http.deps.demo_quota import consume_demo_quota_units

    fake_hash = hashlib.sha256(b"not-demo-return-bool").hexdigest()
    consumed = await consume_demo_quota_units(
        db_session, api_key_hash=fake_hash, units=1, durable=True
    )
    assert consumed is False


@pytest.mark.asyncio
async def test_maybe_consume_fail_closed_when_session_unavailable() -> None:
    """Authenticated request with session=None must 503, not skip metering (DS2B-PM-S2-02)."""
    from fastapi import HTTPException

    from recognition.interface_adapters.http.deps.auth import AuthContext
    from recognition.interface_adapters.http.deps.demo_quota import maybe_consume_demo_quota

    auth = AuthContext(
        token="demo-or-unknown-key",
        tenant_claim=str(hashlib.sha256(b"t").hexdigest()[:32]),
        api_key_id=None,
        is_admin=False,
        enabled=True,
    )
    with pytest.raises(HTTPException) as exc_info:
        await maybe_consume_demo_quota(auth, None, units=1)
    assert exc_info.value.status_code == 503
    assert "database session unavailable" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_maybe_consume_skips_when_auth_disabled() -> None:
    from recognition.interface_adapters.http.deps.auth import AuthContext
    from recognition.interface_adapters.http.deps.demo_quota import maybe_consume_demo_quota

    auth = AuthContext(
        token="ignored",
        tenant_claim=None,
        api_key_id=None,
        is_admin=False,
        enabled=False,
    )
    assert await maybe_consume_demo_quota(auth, None, units=1) is False


@pytest.mark.asyncio
async def test_consume_demo_quota_units_rejects_over_ceiling(
    db_session: AsyncSession,
) -> None:
    """HTTP boundary maps out-of-range units to 422 (DS2B-PM-S1-03)."""
    from fastapi import HTTPException

    from recognition.interface_adapters.http.deps.demo_quota import consume_demo_quota_units

    result = await provision_demo(db_session, label="Ceil", seed="default", recognition_quota=5)
    await db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        await consume_demo_quota_units(
            db_session, api_key_hash=result.instance.api_key_ref, units=501
        )
    assert exc_info.value.status_code == 422
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert detail["code"] == "invalid_demo_quota_units"


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
async def test_demo_quota_non_demo_key_units_gt_one_is_noop(db_session: AsyncSession) -> None:
    fake_hash = hashlib.sha256(b"not-a-demo-key-multi").hexdigest()
    ok = await try_consume_demo_quota(db_session, api_key_hash=fake_hash, units=3)
    assert ok is False


@pytest.mark.asyncio
async def test_demo_quota_revoked_instance_reports_zero_remaining(db_session: AsyncSession) -> None:
    """Revoked demo key must not report a positive remaining budget (DS2B-PM-S1-01)."""
    from recognition.application.services.demo_provisioning_service import expire_demo

    result = await provision_demo(db_session, label="Revoked", seed="default", recognition_quota=5)
    await db_session.commit()
    key_hash = result.instance.api_key_ref
    await expire_demo(db_session, slug=result.instance.slug)
    await db_session.commit()

    with pytest.raises(DemoQuotaExceededError) as exc_info:
        await try_consume_demo_quota(db_session, api_key_hash=key_hash)
    assert exc_info.value.remaining == 0

    loaded = await db_session.get(DemoInstance, result.instance.slug)
    assert loaded is not None
    assert loaded.recognition_used == 0


@pytest.mark.asyncio
async def test_demo_quota_rejects_at_cap(db_session: AsyncSession) -> None:
    result = await provision_demo(db_session, label="Cap", seed="default", recognition_quota=2)
    await db_session.commit()

    assert await try_consume_demo_quota(db_session, api_key_hash=result.instance.api_key_ref)
    assert await try_consume_demo_quota(db_session, api_key_hash=result.instance.api_key_ref)
    await db_session.commit()

    with pytest.raises(DemoQuotaExceededError) as exc_info:
        await try_consume_demo_quota(db_session, api_key_hash=result.instance.api_key_ref)

    assert exc_info.value.remaining == 0

    loaded = await db_session.get(DemoInstance, result.instance.slug)
    assert loaded is not None
    assert loaded.recognition_used == 2


@pytest.mark.asyncio
async def test_demo_quota_units_validation_rejects_non_positive(
    db_session: AsyncSession,
) -> None:
    result = await provision_demo(db_session, label="Val", seed="default", recognition_quota=5)
    await db_session.commit()
    key_hash = result.instance.api_key_ref

    with pytest.raises(ValueError, match="units must be in 1"):
        await try_consume_demo_quota(db_session, api_key_hash=key_hash, units=0)
    with pytest.raises(ValueError, match="units must be in 1"):
        await try_consume_demo_quota(db_session, api_key_hash=key_hash, units=-1)
    with pytest.raises(ValueError, match="units must be in 1"):
        await try_consume_demo_quota(db_session, api_key_hash=key_hash, units=501)

    loaded = await db_session.get(DemoInstance, result.instance.slug)
    assert loaded is not None
    assert loaded.recognition_used == 0


@pytest.mark.asyncio
async def test_demo_quota_multi_unit_consume(db_session: AsyncSession) -> None:
    result = await provision_demo(db_session, label="Multi", seed="default", recognition_quota=5)
    await db_session.commit()

    ok = await try_consume_demo_quota(db_session, api_key_hash=result.instance.api_key_ref, units=3)
    await db_session.commit()
    assert ok is True

    loaded = await db_session.get(DemoInstance, result.instance.slug)
    assert loaded is not None
    assert loaded.recognition_used == 3


@pytest.mark.asyncio
async def test_demo_quota_all_or_nothing_boundary(db_session: AsyncSession) -> None:
    result = await provision_demo(db_session, label="AON", seed="default", recognition_quota=5)
    await db_session.commit()
    key_hash = result.instance.api_key_ref

    assert await try_consume_demo_quota(db_session, api_key_hash=key_hash, units=3)
    await db_session.commit()

    with pytest.raises(DemoQuotaExceededError) as exc_info:
        await try_consume_demo_quota(db_session, api_key_hash=key_hash, units=3)
    assert exc_info.value.remaining == 2

    loaded = await db_session.get(DemoInstance, result.instance.slug)
    assert loaded is not None
    assert loaded.recognition_used == 3


@pytest.mark.asyncio
async def test_demo_quota_exact_fit_then_zero_remaining(db_session: AsyncSession) -> None:
    result = await provision_demo(db_session, label="Exact", seed="default", recognition_quota=5)
    await db_session.commit()
    key_hash = result.instance.api_key_ref

    ok = await try_consume_demo_quota(db_session, api_key_hash=key_hash, units=5)
    await db_session.commit()
    assert ok is True

    loaded = await db_session.get(DemoInstance, result.instance.slug)
    assert loaded is not None
    assert loaded.recognition_used == 5

    with pytest.raises(DemoQuotaExceededError) as exc_info:
        await try_consume_demo_quota(db_session, api_key_hash=key_hash, units=1)
    assert exc_info.value.remaining == 0


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


@pytest.mark.asyncio
async def test_demo_quota_mixed_units_concurrency_near_cap(db_session: AsyncSession) -> None:
    """Mixed unit sizes near cap: never overshoot; success sum fits exactly."""
    quota = 10
    result = await provision_demo(db_session, label="MixedRace", seed="default", recognition_quota=quota)
    await db_session.commit()
    key_hash = result.instance.api_key_ref
    slug = result.instance.slug

    engine = db_session.bind
    assert engine is not None
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    # Mix of 1s, 2s, and 3s; total offered exceeds quota so some must fail.
    unit_sizes = [1, 2, 3, 1, 2, 3, 1, 2, 3, 1, 2, 3]

    async def _attempt(units: int) -> int:
        async with factory() as session:
            try:
                await try_consume_demo_quota(session, api_key_hash=key_hash, units=units)
                await session.commit()
                return units
            except DemoQuotaExceededError as exc:
                await session.rollback()
                assert exc.remaining >= 0
                return 0

    successes = await asyncio.gather(*[_attempt(u) for u in unit_sizes])
    successful_units = sum(successes)

    async with factory() as session:
        loaded = await session.get(DemoInstance, slug)
        assert loaded is not None
        assert loaded.recognition_used <= quota
        assert loaded.recognition_used == successful_units
        # Near-cap mixed sizes: at least some units consumed and remaining < largest attempt.
        assert successful_units > 0
        assert successful_units <= quota
        # Remaining cannot fit the largest unit size still offered after successes.
        remaining = quota - loaded.recognition_used
        assert remaining < 3 or successful_units == quota
