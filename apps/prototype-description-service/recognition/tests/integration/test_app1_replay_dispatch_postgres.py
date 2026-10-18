"""PostgreSQL proof for replay-safe scan population and inline processing."""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.models import IdentityScanJob, IdentityScanJobItem, Tenant
from db.tenant_context import set_tenant_context
from recognition.application.scan.scan_queue_service import ScanQueueService
from recognition.application.settings.scan import ScanSettings
from recognition.domain.job import JobStatus
from recognition.infrastructure.repositories.scan_queue_repository import SqlAlchemyScanQueueRepository
from recognition.interface_adapters.http.routers import analyze

pytestmark = pytest.mark.pg


def _async_url(engine) -> str:
    return (
        engine.url.render_as_string(hide_password=False)
        .replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
        .replace("postgresql://", "postgresql+asyncpg://", 1)
    )


async def _seed_pending_job(
    session_factory: async_sessionmaker[AsyncSession], *, total: int
) -> tuple[UUID, UUID]:
    async with session_factory() as session:
        tenant = Tenant(site_url=f"https://app1-replay-{uuid4()}.example.test")
        session.add(tenant)
        await session.flush()
        await set_tenant_context(session, tenant.id)
        job = IdentityScanJob(
            tenant_id=tenant.id,
            status=JobStatus.PENDING,
            media_ids=[],
            total_media=total,
            processed_media=0,
            identities_detected=0,
        )
        session.add(job)
        await session.commit()
        return tenant.id, job.id


def _dispatch_kwargs(session_factory, tenant_id, job_id, media_items):
    media_ids = [f"media-{media_id}" for media_id, _ in media_items]
    return {
        "tenant_id": str(tenant_id),
        "job_id": str(job_id),
        "media_items": media_items,
        "media_ids": media_ids,
        "media_sources": [url for _, url in media_items],
        "session_factory": session_factory,
        "inline_processing": True,
        "adapter_provider": None,
    }


@pytest_asyncio.fixture
async def migrated_session_factory(pg_migrated_engine):
    engine = create_async_engine(_async_url(pg_migrated_engine), pool_size=4, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_original_and_replay_populate_and_process_once(migrated_session_factory, monkeypatch):
    tenant_id, job_id = await _seed_pending_job(migrated_session_factory, total=3)
    media_items = [
        (101, "https://media.example.test/101"),
        (102, "https://media.example.test/102"),
        (103, "https://media.example.test/103"),
    ]
    processor_calls = []

    async def counting_processor(**kwargs):
        processor_calls.append(kwargs)

    monkeypatch.setattr(analyze, "process_scan_job_inline", counting_processor)
    dispatch = _dispatch_kwargs(migrated_session_factory, tenant_id, job_id, media_items)

    original_dispatch = analyze._dispatch_persisted_analysis(**dispatch)
    replay_dispatch = analyze._dispatch_persisted_analysis(**dispatch)
    await asyncio.gather(original_dispatch, replay_dispatch)

    async with migrated_session_factory() as session:
        await set_tenant_context(session, tenant_id)
        rows = (
            await session.execute(
                select(IdentityScanJobItem.media_id, IdentityScanJobItem.media_url)
                .where(IdentityScanJobItem.job_id == job_id)
                .order_by(IdentityScanJobItem.media_id)
            )
        ).all()
        job = await session.get(IdentityScanJob, job_id)

    assert rows == media_items
    assert job is not None and job.status == JobStatus.RUNNING
    assert len(processor_calls) == 1
    assert processor_calls[0]["job_id"] == str(job_id)


@pytest.mark.asyncio
async def test_population_failure_in_second_chunk_rolls_back_first_chunk(
    migrated_session_factory, monkeypatch
):
    tenant_id, job_id = await _seed_pending_job(migrated_session_factory, total=3)
    media_items = [
        (201, "https://media.example.test/201"),
        (202, "https://media.example.test/202"),
        (203, "https://media.example.test/203"),
    ]
    attempts = 0
    original_enqueue_items = SqlAlchemyScanQueueRepository.enqueue_items

    class OneItemChunkScanQueue(ScanQueueService):
        def __init__(self, repository):
            super().__init__(repository, settings=ScanSettings(enqueue_chunk_size=1))

    async def fail_second_chunk(repository, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 2:
            raise RuntimeError("injected failure on second population chunk")
        return await original_enqueue_items(repository, **kwargs)

    monkeypatch.setattr(analyze, "ScanQueueService", OneItemChunkScanQueue)
    monkeypatch.setattr(SqlAlchemyScanQueueRepository, "enqueue_items", fail_second_chunk)
    dispatch = _dispatch_kwargs(migrated_session_factory, tenant_id, job_id, media_items)

    with pytest.raises(RuntimeError, match="second population chunk"):
        await analyze._dispatch_persisted_analysis(**dispatch)

    assert attempts == 2
    async with migrated_session_factory() as session:
        await set_tenant_context(session, tenant_id)
        item_count = await session.scalar(
            select(func.count()).select_from(IdentityScanJobItem).where(IdentityScanJobItem.job_id == job_id)
        )
        job = await session.get(IdentityScanJob, job_id)

    assert item_count == 0
    assert job is not None and job.status == JobStatus.PENDING
