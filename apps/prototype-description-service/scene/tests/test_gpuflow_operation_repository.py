"""Durable retry correlation and finite demand leases with UTC fake clocks."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db.models.base_imports import Base
from db.models.scene import DescribeDemandLease, DescribeOperation, DescribeStartup
from scene.application.describe_operation_repository import DescribeOperationRepository
from scene.domain.describe_run import OperationExpiredError, OperationMismatchError


def test_retry_restart_shared_startup_and_retained_timing():
    async def body():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(
                Base.metadata.create_all,
                tables=[
                    DescribeStartup.__table__,
                    DescribeOperation.__table__,
                    DescribeDemandLease.__table__,
                ],
            )
        sf = async_sessionmaker(engine, expire_on_commit=False)
        tenant = uuid.uuid4()
        start = datetime(2026, 1, 1, tzinfo=UTC)
        async with sf() as session:
            repo = DescribeOperationRepository(session, lease_seconds=60)
            first = await repo.accept(tenant_id=tenant, request_digest="a" * 64, now=start)
            token = first.operation_id
            await repo.associate_startup(
                tenant_id=tenant, operation_id=token, startup_id="boot", started_at=start, now=start
            )
            second = await repo.accept(tenant_id=tenant, request_digest="b" * 64, now=start + timedelta(seconds=10))
            await repo.associate_startup(
                tenant_id=tenant, operation_id=second.operation_id, startup_id="boot", now=start + timedelta(seconds=10)
            )
            await session.commit()
        async with sf() as session:
            repo = DescribeOperationRepository(session, lease_seconds=60)
            first = await repo.accept(
                tenant_id=tenant, request_digest="a" * 64, operation_id=token, now=start + timedelta(seconds=20)
            )
            await repo.observe_ready(tenant_id=tenant, operation_id=token, now=start + timedelta(seconds=30))
            await repo.observe_ready(
                tenant_id=tenant, operation_id=second.operation_id, now=start + timedelta(seconds=35)
            )
            await repo.observe_ready(tenant_id=tenant, operation_id=token, now=start + timedelta(seconds=40))
            assert first.ramp_up_ms == 30000
            other = await repo.get(tenant_id=tenant, operation_id=second.operation_id)
            assert other.ramp_up_ms == 25000
            assert other.startup_ms == first.startup_ms == 30000
            await repo.complete(
                tenant_id=tenant,
                operation_id=token,
                processing_ms=12,
                server_elapsed_ms=15,
                now=start + timedelta(seconds=45),
            )
            await session.commit()
        async with sf() as session:
            repo = DescribeOperationRepository(session, lease_seconds=60)
            replay = await repo.accept(
                tenant_id=tenant, request_digest="a" * 64, operation_id=token, now=start + timedelta(seconds=90)
            )
            assert replay.processing_ms == 12
            assert replay.server_elapsed_ms == 15
            with pytest.raises(OperationMismatchError):
                await repo.accept(tenant_id=tenant, request_digest="c" * 64, operation_id=token, now=start)
            with pytest.raises(OperationMismatchError):
                await repo.accept(tenant_id=uuid.uuid4(), request_digest="a" * 64, operation_id=token, now=start)
            with pytest.raises(OperationExpiredError):
                await repo.accept(
                    tenant_id=tenant,
                    request_digest="b" * 64,
                    operation_id=second.operation_id,
                    now=start + timedelta(seconds=90),
                )
            await session.commit()
        await engine.dispose()

    asyncio.run(body())


def test_warm_cache_expiry_and_retention_bound():
    async def body():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(
                Base.metadata.create_all,
                tables=[
                    DescribeStartup.__table__,
                    DescribeOperation.__table__,
                    DescribeDemandLease.__table__,
                ],
            )
        sf = async_sessionmaker(engine, expire_on_commit=False)
        start = datetime(2026, 1, 1, tzinfo=UTC)
        tenant = uuid.uuid4()
        async with sf() as session:
            repo = DescribeOperationRepository(session, lease_seconds=60, retention_hours=1)
            op = await repo.accept(tenant_id=tenant, request_digest="a" * 64, now=start)
            await repo.observe_ready(tenant_id=tenant, operation_id=op.operation_id, now=start + timedelta(seconds=2))
            assert op.ramp_up_ms == 0
            assert op.startup_id is None
            assert op.startup_ms is None
            await repo.complete(
                tenant_id=tenant,
                operation_id=op.operation_id,
                processing_ms=0,
                server_elapsed_ms=2,
                now=start + timedelta(seconds=3),
            )
            assert op.processing_ms == 0
            expiring = await repo.accept(tenant_id=tenant, request_digest="b" * 64, now=start)
            # Retain the SQLite-loaded lease so bulk expiry must synchronize it.
            lease = await session.get(DescribeDemandLease, (tenant, expiring.operation_id))
            assert lease.expires_at.tzinfo is None
            assert await repo.active_demand_count(now=start, stop_requested=True) == 0
            assert await repo.active_demand_count(now=start) == 1
            assert await repo.active_demand_count(now=start + timedelta(seconds=60)) == 0
            assert lease.state == "expired"
            with pytest.raises(OperationExpiredError):
                await repo.accept(
                    tenant_id=tenant,
                    request_digest="b" * 64,
                    operation_id=expiring.operation_id,
                    now=start + timedelta(seconds=61),
                )
            lease = await session.get(DescribeDemandLease, (tenant, expiring.operation_id))
            assert lease.state == "rejected"
            bounded = await repo.accept(tenant_id=tenant, request_digest="c" * 64, now=start)
            for seconds in range(50, 3600, 50):
                bounded = await repo.accept(
                    tenant_id=tenant,
                    request_digest="c" * 64,
                    operation_id=bounded.operation_id,
                    now=start + timedelta(seconds=seconds),
                )
            from scene.domain.describe_run import utc_observation

            assert utc_observation(bounded.expires_at) == start + timedelta(hours=1)
            assert utc_observation(bounded.retain_until) == start + timedelta(hours=1)
            assert await repo.purge_expired(now=start + timedelta(hours=1, seconds=4)) == 3
            assert lease not in session
            assert all(operation not in session for operation in (op, expiring, bounded))
            with pytest.raises(ValueError):
                await repo.complete(
                    tenant_id=tenant, operation_id=op.operation_id, processing_ms=float("nan"), now=start
                )
        await engine.dispose()

    asyncio.run(body())


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), -float("inf")])
def test_duration_rejects_invalid_measurements(value):
    from scene.domain.describe_run import validate_duration_ms

    with pytest.raises(ValueError, match="finite and nonnegative"):
        validate_duration_ms(value)


def test_utc_observations_validate_clock_order_without_fabricated_zero():
    from scene.domain.describe_run import elapsed_ms, validate_duration_ms

    start = datetime(2026, 1, 1, tzinfo=UTC)
    assert elapsed_ms(start.replace(tzinfo=None), start + timedelta(milliseconds=12)) == 12
    assert validate_duration_ms(None) is None
    assert validate_duration_ms(0) == 0
    with pytest.raises(ValueError):
        elapsed_ms(start, start - timedelta(milliseconds=1))
