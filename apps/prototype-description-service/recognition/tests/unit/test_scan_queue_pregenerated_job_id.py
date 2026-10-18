"""Tests for the pre-generated job_id flow on scan_queue (E15-11 Slice 1.4c).

The multipart route writes uploaded image bytes into the ObjectStore at
``<tenant>/<job_id>/<media_id>.bin`` BEFORE the scan job record exists in
the DB — the job_id has to be known at upload time so the blobs land
under the right per-job directory. To support that without a post-write
filesystem rename, scan_queue.create_scan_job_record now accepts an
optional pre-generated job_id which the repository persists verbatim.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from db.models import IdentityScanJob
from recognition.application.scan.scan_queue_service import ScanQueueService
from recognition.infrastructure.repositories.scan_queue_repository import (
    SqlAlchemyScanQueueRepository,
)


@pytest.mark.asyncio
async def test_create_scan_job_record_uses_provided_job_id(db_session, tenant) -> None:
    """When the caller pre-generates a UUID (the multipart route does this
    before calling ObjectStore.put), create_scan_job_record must persist
    that exact UUID rather than generating its own."""
    repo = SqlAlchemyScanQueueRepository(db_session)
    queue = ScanQueueService(repo)
    pre_generated = uuid.uuid4()

    returned = await queue.create_scan_job_record(tenant_id=tenant.id, total=2, job_id=pre_generated)

    assert returned == pre_generated
    job = (await db_session.execute(select(IdentityScanJob).where(IdentityScanJob.id == pre_generated))).scalar_one()
    assert job.id == pre_generated
    assert job.total_media == 2


@pytest.mark.asyncio
async def test_create_scan_job_record_generates_job_id_when_not_provided(db_session, tenant) -> None:
    """Default behaviour preserved: callers that don't pre-generate get a
    fresh UUID from the DB layer."""
    repo = SqlAlchemyScanQueueRepository(db_session)
    queue = ScanQueueService(repo)

    job_id = await queue.create_scan_job_record(tenant_id=tenant.id, total=1)

    assert isinstance(job_id, uuid.UUID)
    job = (await db_session.execute(select(IdentityScanJob).where(IdentityScanJob.id == job_id))).scalar_one()
    assert job.id == job_id


@pytest.mark.asyncio
async def test_create_scan_job_record_rejects_duplicate_pre_generated_id(db_session, tenant) -> None:
    """Calling twice with the same pre-generated UUID must fail at the DB
    layer. This protects against the multipart route accidentally reusing
    a stale job_id from an earlier failed request."""
    repo = SqlAlchemyScanQueueRepository(db_session)
    queue = ScanQueueService(repo)
    pre_generated = uuid.uuid4()

    await queue.create_scan_job_record(tenant_id=tenant.id, total=1, job_id=pre_generated)
    with pytest.raises(Exception):  # noqa: BLE001 - SQLAlchemy IntegrityError or similar
        await queue.create_scan_job_record(tenant_id=tenant.id, total=1, job_id=pre_generated)
