"""Real PostgreSQL claim locks and failure fencing across rollback (RES-10)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.models import IdentityScanJobItem, Tenant
from recognition.infrastructure.repositories.scan_queue_repository import SqlAlchemyScanQueueRepository
from recognition.worker.handlers import scan as scan_handler_module
from recognition.worker.handlers.scan import ScanItemHandler

pytestmark = pytest.mark.pg


@pytest.mark.asyncio
@pytest.mark.parametrize("newer_status", ["processing", "completed"])
async def test_postgres_stale_failure_preserves_reclaimed_attempt(
    pg_migrated_engine, monkeypatch: pytest.MonkeyPatch, newer_status: str
) -> None:
    url = (
        pg_migrated_engine.url.render_as_string(hide_password=False)
        .replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
        .replace("postgresql://", "postgresql+asyncpg://", 1)
    )
    engine = create_async_engine(url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as setup:
            tenant = Tenant(site_url=f"http://scan-claim-{uuid.uuid4()}.test")
            setup.add(tenant)
            await setup.flush()
            tenant_id = tenant.id

            async def _tenant_context(session: AsyncSession) -> None:
                await session.execute(
                    text("SELECT set_config('app.current_tenant', :tenant_id, true)"),
                    {"tenant_id": str(tenant_id)},
                )

            await _tenant_context(setup)
            repo = SqlAlchemyScanQueueRepository(setup)
            now = datetime.now(tz=UTC)
            job_id = await repo.create_job(tenant_id=tenant_id, media_ids=[1])
            await repo.enqueue_items(
                job_id=job_id, tenant_id=tenant_id, items=[(1, "http://example.test/1.jpg")]
            )
            await repo.mark_job_running(job_id=job_id, started_at=now)
            claimed = await repo.claim_pending_items_any(limit=1, now=now - timedelta(minutes=5))
            assert len(claimed) == 1
            item = claimed[0]
            await setup.commit()

        async with factory() as competitor:
            reclaimed_after_rollback = False

            class _RollbackRaceSession(AsyncSession):
                async def rollback(self) -> None:
                    nonlocal reclaimed_after_rollback
                    await super().rollback()
                    if reclaimed_after_rollback:
                        return
                    # Force the competing claim into the exact lock-release gap.
                    await _tenant_context(competitor)
                    other_repo = SqlAlchemyScanQueueRepository(competitor)
                    assert await other_repo.reclaim_stale_items(
                        stale_after_seconds=60, max_attempts=3, now=now
                    ) == 1
                    newer = await other_repo.claim_pending_items_any(limit=1, now=now)
                    assert len(newer) == 1
                    assert newer[0].id == item.id
                    assert newer[0].attempts == item.attempts + 1
                    if newer_status == "completed":
                        await other_repo.mark_item_completed(
                            item_id=item.id, completed_at=now, identities_detected=7
                        )
                    await competitor.commit()
                    reclaimed_after_rollback = True

            class _FailingService:
                async def process_media_item(self, **_kwargs: object) -> int:
                    await _tenant_context(competitor)
                    # The original handler's item lock really blocks PostgreSQL writes.
                    with pytest.raises(DBAPIError) as conflict:
                        await competitor.execute(
                            select(IdentityScanJobItem.id)
                            .where(IdentityScanJobItem.id == item.id)
                            .with_for_update(nowait=True)
                        )
                    assert conflict.value.orig.sqlstate == "55P03"
                    await competitor.rollback()
                    raise RuntimeError("slow attempt failed")

            handler = ScanItemHandler(
                session_factory=async_sessionmaker(engine, class_=_RollbackRaceSession),
                detector=object(),
                generator=object(),
                max_attempts=1,
                max_concurrency=1,
            )
            monkeypatch.setattr(scan_handler_module, "enable_rls_bypass", _tenant_context)
            monkeypatch.setattr(handler, "_build_scan_service", lambda _session: _FailingService())

            async def _no_refresh(_job_ids: set[uuid.UUID]) -> None:
                return None

            monkeypatch.setattr(handler, "_refresh_job_progress", _no_refresh)
            await handler.process_items(claimed=[item])

            assert reclaimed_after_rollback
            await _tenant_context(competitor)
            row = (
                await competitor.execute(
                    select(IdentityScanJobItem).where(IdentityScanJobItem.id == item.id)
                )
            ).scalar_one()
            assert row.attempts == item.attempts + 1
            assert row.status == newer_status
            assert row.last_error is None
            assert row.identities_detected == (7 if newer_status == "completed" else 0)
    finally:
        await engine.dispose()
