"""Real PostgreSQL row-lock proofs for the inline persistence fence."""

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import numpy as np
import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.models import IdentityScanJob, MediaIdentity, Tenant
from db.models.base_imports import _DB_SETTINGS
from db.tenant_context import set_tenant_context
from recognition.application.embedding.detector import FaceDetection
from recognition.application.scan import service as scan_service_module
from recognition.application.scan.service import ScanService
from recognition.domain.job import JobStatus
from recognition.interface_adapters.http.routers import analyze

pytestmark = pytest.mark.pg
OWNER = "inline:postgres-fence"


@pytest_asyncio.fixture
async def migrated_session_factory(pg_migrated_engine):
    url = (
        pg_migrated_engine.url.render_as_string(hide_password=False)
        .replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
        .replace("postgresql://", "postgresql+asyncpg://", 1)
    )
    engine = create_async_engine(url, pool_size=4, max_overflow=0)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    finally:
        await engine.dispose()


async def _seed_job(factory):
    async with factory() as session:
        tenant = Tenant(site_url=f"https://inline-fence-{uuid4()}.example.test")
        session.add(tenant)
        await session.flush()
        await set_tenant_context(session, tenant.id)
        job = IdentityScanJob(
            tenant_id=tenant.id,
            status=JobStatus.RUNNING,
            media_ids=[1],
            total_media=1,
            processed_media=0,
            identities_detected=0,
            started_at=datetime.now(tz=UTC),
            error_message=OWNER,
        )
        session.add(job)
        await session.commit()
        return tenant.id, job.id


async def _save(service, tenant_id, job_id):
    embedding = np.zeros(_DB_SETTINGS.pgvector_dimension, dtype=np.float32)
    embedding[0] = 1
    token = scan_service_module.inline_processing_owner.set((job_id, OWNER))
    try:
        return await service.save_job_results(
            job_id=job_id,
            tenant_id=str(tenant_id),
            media_ids=["1"],
            media_sources=None,
            detections=[
                FaceDetection(
                    media_id="1",
                    bbox=(0, 0, 20, 20),
                    confidence=0.99,
                    embedding=embedding,
                    model_id="postgres-fence-test",
                )
            ],
        )
    finally:
        scan_service_module.inline_processing_owner.reset(token)


async def _assert_blocked(task):
    # Shield preserves the contender while a bounded wait proves it cannot finish.
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(asyncio.shield(task), timeout=0.2)
    assert not task.done()


async def _verify(factory, tenant_id, job_id, *, status, count):
    async with factory() as session:
        await set_tenant_context(session, tenant_id)
        job = await session.get(IdentityScanJob, job_id)
        assert job.status == status
        assert job.processed_media == count
        assert job.identities_detected == count
        assert (job.completed_at is not None) == (status == JobStatus.COMPLETED)
        assert (
            await session.scalar(
                select(func.count()).select_from(MediaIdentity).where(MediaIdentity.tenant_id == tenant_id)
            )
            == count
        )
        return job


@pytest.mark.asyncio
async def test_sweeper_failure_wins_while_persistence_waits_on_job_lock(migrated_session_factory, monkeypatch):
    factory = migrated_session_factory
    tenant_id, job_id = await _seed_job(factory)
    async with factory() as sweeper, factory() as persistence:
        await set_tenant_context(sweeper, tenant_id)
        await set_tenant_context(persistence, tenant_id)
        job = await sweeper.scalar(select(IdentityScanJob).where(IdentityScanJob.id == job_id).with_for_update())
        job.status = JobStatus.FAILED
        job.error_message = "stalled job"
        await sweeper.flush()
        selecting = asyncio.Event()
        original_scalar = persistence.scalar

        async def signal_select(*args, **kwargs):
            selecting.set()
            return await original_scalar(*args, **kwargs)

        monkeypatch.setattr(persistence, "scalar", signal_select)
        service = ScanService(session=persistence)
        persist_calls = []
        original_persist = service._persist_identities

        async def record_persist(**kwargs):
            persist_calls.append(kwargs)
            return await original_persist(**kwargs)

        monkeypatch.setattr(service, "_persist_identities", record_persist)
        task = asyncio.create_task(_save(service, tenant_id, job_id))
        try:
            await asyncio.wait_for(selecting.wait(), timeout=5)
            await _assert_blocked(task)
            await asyncio.wait_for(sweeper.commit(), timeout=5)
            result = await asyncio.wait_for(task, timeout=5)
            assert result.status == JobStatus.FAILED
            assert persist_calls == []
        finally:
            await sweeper.rollback()
            if not task.done():
                task.cancel()
            await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=5)

    job = await _verify(factory, tenant_id, job_id, status=JobStatus.FAILED, count=0)
    assert job.error_message == "stalled job"


@pytest.mark.asyncio
async def test_heartbeat_waits_for_persistence_then_observes_one_completion(migrated_session_factory, monkeypatch):
    factory = migrated_session_factory
    tenant_id, job_id = await _seed_job(factory)
    holding_lock = asyncio.Event()
    resume_persistence = asyncio.Event()
    renewing = asyncio.Event()
    events = []
    monkeypatch.setattr(scan_service_module, "_emit_scan_media_reconciled", lambda **kwargs: events.append(kwargs))

    # Signal after tenant setup, immediately before renewal's real locking SELECT.
    class RenewalSession(AsyncSession):
        async def scalar(self, *args, **kwargs):
            renewing.set()
            return await super().scalar(*args, **kwargs)

    renewal_factory = async_sessionmaker(factory.kw["bind"], class_=RenewalSession, expire_on_commit=False)
    async with factory() as persistence:
        await set_tenant_context(persistence, tenant_id)
        service = ScanService(session=persistence)
        original_persist = service._persist_identities
        persist_calls = []

        async def paused_persist(**kwargs):
            persist_calls.append(kwargs)
            holding_lock.set()
            await asyncio.wait_for(resume_persistence.wait(), timeout=5)
            return await original_persist(**kwargs)

        monkeypatch.setattr(service, "_persist_identities", paused_persist)
        saving = asyncio.create_task(_save(service, tenant_id, job_id))
        renewal = None
        try:
            await asyncio.wait_for(holding_lock.wait(), timeout=5)
            renewal = asyncio.create_task(
                analyze._renew_inline_processing_lease(
                    session_factory=renewal_factory,
                    tenant_id=tenant_id,
                    job_id=job_id,
                    owner_token=OWNER,
                )
            )
            await asyncio.wait_for(renewing.wait(), timeout=5)
            await _assert_blocked(renewal)
            resume_persistence.set()
            result = await asyncio.wait_for(saving, timeout=5)
            assert result.status == JobStatus.COMPLETED
            assert await asyncio.wait_for(renewal, timeout=5) is None
            assert len(persist_calls) == 1
            assert len(events) == 1
            assert events[0]["job_id"] == str(job_id)
        finally:
            resume_persistence.set()
            tasks = [task for task in (saving, renewal) if task is not None]
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=5)

    await _verify(factory, tenant_id, job_id, status=JobStatus.COMPLETED, count=1)
