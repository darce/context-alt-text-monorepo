"""E15-27 Slice 3: per-item tenant isolation in concurrent scan batches."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.models import IdentityScanJobItem, Tenant
from recognition.application.scan.queue_repository import ScanQueueItem
from recognition.domain.job import ScanItemStatus
from recognition.infrastructure.repositories.scan_queue_repository import SqlAlchemyScanQueueRepository
from recognition.worker.handlers.scan import ScanItemHandler


def _claimed_item(
    *,
    item_id: uuid.UUID,
    job_id: uuid.UUID,
    tenant_id: uuid.UUID,
    media_id: int,
) -> ScanQueueItem:
    now = datetime.now(tz=UTC)
    return ScanQueueItem(
        id=item_id,
        job_id=job_id,
        tenant_id=tenant_id,
        media_id=media_id,
        media_url=f"http://example.test/{media_id}.jpg",
        status=ScanItemStatus.PROCESSING.value,
        attempts=1,
        identities_detected=0,
        last_error=None,
        created_at=now,
        started_at=now,
    )


@pytest.mark.asyncio
async def test_process_items_isolates_poisoned_tenant_among_three(
    db_session: AsyncSession,
) -> None:
    """One tenant's exception must not abort sibling tenants in the same batch."""
    tenants = [Tenant(site_url=f"http://tenant-{index}.test") for index in range(3)]
    db_session.add_all(tenants)
    await db_session.commit()
    for tenant in tenants:
        await db_session.refresh(tenant)

    poison_tenant_id = tenants[1].id
    repo = SqlAlchemyScanQueueRepository(db_session)
    job_ids: list[uuid.UUID] = []
    claimed: list[ScanQueueItem] = []
    for index, tenant in enumerate(tenants):
        job_id = await repo.create_job(tenant_id=tenant.id, media_ids=[index + 1])
        job_ids.append(job_id)
        await repo.enqueue_items(
            job_id=job_id,
            tenant_id=tenant.id,
            items=[(index + 1, f"http://example.test/{index + 1}.jpg")],
        )
        item_row = (
            await db_session.execute(select(IdentityScanJobItem).where(IdentityScanJobItem.job_id == job_id))
        ).scalar_one()
        claimed.append(
            _claimed_item(
                item_id=item_row.id,
                job_id=job_id,
                tenant_id=tenant.id,
                media_id=index + 1,
            )
        )
    await db_session.commit()

    session_factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)

    async def _process_media_item(*, tenant_id: str, media_id: int, media_url: str) -> int:
        if uuid.UUID(tenant_id) == poison_tenant_id:
            raise RuntimeError("poisoned tenant")
        return 1

    handler = ScanItemHandler(
        session_factory=session_factory,
        detector=AsyncMock(),
        generator=AsyncMock(),
        max_attempts=3,
        max_concurrency=3,
    )

    with (
        patch.object(handler, "_build_scan_service") as build_svc,
        patch.object(handler, "_refresh_job_progress", new=AsyncMock()),
    ):
        svc = AsyncMock()
        svc.process_media_item = _process_media_item
        build_svc.return_value = svc
        await handler.process_items(claimed=claimed)

    result = await db_session.execute(
        select(IdentityScanJobItem.job_id, IdentityScanJobItem.status, IdentityScanJobItem.last_error)
    )
    rows = {(job_id, status, last_error) for job_id, status, last_error in result.all()}

    healthy_job_ids = {job_ids[0], job_ids[2]}
    poison_job_id = job_ids[1]
    assert any(job_id in healthy_job_ids and status == ScanItemStatus.COMPLETED.value for job_id, status, _ in rows)
    assert any(
        job_id == poison_job_id and status == ScanItemStatus.PENDING.value and last_error == "poisoned tenant"
        for job_id, status, last_error in rows
    )
