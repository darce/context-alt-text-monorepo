"""Postgres CTE claim path: not-before (started_at) must block re-claim.

R2-02 / TEST-15: production workers use claim_pending_items_any → raw SQL CTE.
SQLite generic-path coverage alone cannot catch deletion of the hand-mirrored
predicate. This pg-marked test exercises the real Postgres path.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.models import IdentityScanJobItem, Tenant
from recognition.application.scan.retry_backoff import compute_retry_backoff
from recognition.infrastructure.repositories.scan_queue_repository import SqlAlchemyScanQueueRepository

pytestmark = pytest.mark.pg


def _async_url(pg_migrated_engine) -> str:
    return (
        pg_migrated_engine.url.render_as_string(hide_password=False)
        .replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
        .replace("postgresql://", "postgresql+asyncpg://", 1)
    )


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


@pytest.mark.asyncio
async def test_postgres_claim_any_respects_started_at_not_before(pg_migrated_engine) -> None:
    engine = create_async_engine(_async_url(pg_migrated_engine), pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with session_factory() as session:
            tenant = Tenant(site_url="http://fir4-e2e10-backoff-pg.test")
            session.add(tenant)
            await session.flush()
            # Satisfy the forced-RLS tenant policies for the rest of the transaction.
            await session.execute(
                text("SELECT set_config('app.current_tenant', :tenant_id, true)"),
                {"tenant_id": str(tenant.id)},
            )

            repo = SqlAlchemyScanQueueRepository(session)
            now = datetime.now(tz=UTC)
            job_id = await repo.create_job(tenant_id=tenant.id, media_ids=[1])
            await repo.enqueue_items(
                job_id=job_id,
                tenant_id=tenant.id,
                items=[(1, "http://example.test/1.jpg")],
            )
            claimed = await repo.claim_pending_items_any(limit=1, now=now)
            assert len(claimed) == 1
            item = claimed[0]
            assert item.attempts == 1

            assert await repo.release_item_for_retry(
                item_id=item.id,
                error_message="transient",
                attempts=item.attempts,
                now=now,
            )
            await session.commit()
            # set_config(..., true) is transaction-local; re-arm RLS for the new transaction.
            await session.execute(
                text("SELECT set_config('app.current_tenant', :tenant_id, true)"),
                {"tenant_id": str(tenant.id)},
            )

            # Inside backoff: Postgres CTE must not re-claim.
            during = await repo.claim_pending_items_any(
                limit=1, now=now + timedelta(milliseconds=100)
            )
            assert during == []

            row = (
                await session.execute(
                    select(IdentityScanJobItem).where(IdentityScanJobItem.id == item.id)
                )
            ).scalar_one()
            assert row.status == "pending"
            expected = now + compute_retry_backoff(item.attempts)
            assert abs((_as_utc(row.started_at) - expected).total_seconds()) < 0.05

            # After not-before: claimable again via the same Postgres path.
            after = now + compute_retry_backoff(item.attempts) + timedelta(milliseconds=5)
            reclaimed = await repo.claim_pending_items_any(limit=1, now=after)
            assert len(reclaimed) == 1
            assert reclaimed[0].id == item.id
            assert reclaimed[0].attempts == 2
            await session.commit()
    finally:
        await engine.dispose()
