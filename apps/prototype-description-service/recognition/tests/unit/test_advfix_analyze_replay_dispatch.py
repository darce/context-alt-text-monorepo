"""Regression tests for failed analyze dispatch registration on replays."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from recognition.application.scan.scan_queue_service import ScanQueueService
from recognition.interface_adapters.http.routers.analyze import _schedule_analysis


class _FailingBackgroundTasks:
    def add_task(self, *_args, **_kwargs) -> None:
        raise RuntimeError("background task registration failed")


def _scan_queue() -> ScanQueueService:
    return object.__new__(ScanQueueService)


async def _schedule(*, scan_queue: ScanQueueService, job_id: uuid.UUID, existing_job: bool) -> None:
    await _schedule_analysis(
        background_tasks=_FailingBackgroundTasks(),  # type: ignore[arg-type]
        session=None,
        scan_queue=scan_queue,
        tenant_uuid=uuid.uuid4(),
        media_items=[(42, "https://example.test/42.jpg")],
        media_ids=["42"],
        media_sources=["https://example.test/42.jpg"],
        inline_processing=False,
        auth=None,
        job_id=job_id if existing_job else None,
        existing_job=existing_job,
    )


@pytest.mark.asyncio
async def test_dispatch_registration_failure_does_not_cancel_replayed_job() -> None:
    scan_queue = _scan_queue()
    scan_queue.cancel_scan_job = AsyncMock()  # type: ignore[method-assign]
    replayed_job_id = uuid.uuid4()

    with pytest.raises(HTTPException) as exc_info:
        await _schedule(scan_queue=scan_queue, job_id=replayed_job_id, existing_job=True)

    assert exc_info.value.status_code == 503
    scan_queue.cancel_scan_job.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_registration_failure_cancels_job_created_by_request() -> None:
    scan_queue = _scan_queue()
    created_job_id = uuid.uuid4()
    scan_queue.create_scan_job_record = AsyncMock(return_value=created_job_id)  # type: ignore[method-assign]
    scan_queue.cancel_scan_job = AsyncMock()  # type: ignore[method-assign]

    with pytest.raises(HTTPException) as exc_info:
        await _schedule(scan_queue=scan_queue, job_id=created_job_id, existing_job=False)

    assert exc_info.value.status_code == 503
    scan_queue.cancel_scan_job.assert_awaited_once_with(job_id=created_job_id)
