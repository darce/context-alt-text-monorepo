"""Local SSE boundary tests; repositories never open database connections."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from recognition.domain.job import Job, JobStatus, JobType
from recognition.interface_adapters.http.routers import analyze

JOB_ID = "33333333-3333-4333-8333-333333333333"
TENANT_A = "11111111-1111-4111-8111-111111111111"
TENANT_B = "22222222-2222-4222-8222-222222222222"


@pytest.fixture(autouse=True)
def reset_limiter():
    analyze._reset_job_stream_limiter_for_tests()
    yield
    assert analyze._job_stream_total == 0
    assert analyze._job_stream_counts == {}
    analyze._reset_job_stream_limiter_for_tests()


def job(tenant=TENANT_A, status=JobStatus.RUNNING):
    return Job(id=JOB_ID, tenant_id=tenant, type=JobType.ANALYZE,
               status=status, progress_completed=0, progress_total=1)


async def stream(repo, tenant=TENANT_A, auth=None):
    if auth is None:
        auth = SimpleNamespace(enabled=True, tenant_claim=tenant, is_admin=False)
    response = await analyze.stream_job_progress(
        JOB_ID, tenant_id=tenant, auth=auth, job_repo=repo,
        scan_repo=SimpleNamespace(
            get_job_item_status_counts=AsyncMock(return_value={}),
            get_job_item_identities_detected=AsyncMock(return_value=0),
        ),
    )
    return response.body_iterator


@pytest.mark.asyncio
async def test_foreign_job_is_not_found():
    iterator = await stream(SimpleNamespace(get=AsyncMock(return_value=job(TENANT_B))))
    assert [event async for event in iterator] == [{"event": "error", "data": "Job not found"}]


@pytest.mark.asyncio
async def test_own_job_progress_then_done():
    repo = SimpleNamespace(get=AsyncMock(side_effect=[job(), job(status=JobStatus.COMPLETED)]))
    events = [event async for event in await stream(repo)]
    assert [event["event"] for event in events] == ["progress", "progress", "done"]
    assert json.loads(events[-1]["data"])["status"] == "completed"


@pytest.mark.asyncio
async def test_deadline(monkeypatch):
    clock = [0.0]

    async def sleep(seconds):
        clock[0] += seconds

    monkeypatch.setattr(analyze, "JOB_STREAM_MAX_SECONDS", 0.05)
    monkeypatch.setattr(analyze, "_time", SimpleNamespace(monotonic=lambda: clock[0], time=lambda: clock[0]))
    monkeypatch.setattr(asyncio, "sleep", sleep)
    events = [event async for event in await stream(SimpleNamespace(get=AsyncMock(return_value=job())))]
    assert events[-1] == {"event": "timeout", "data": json.dumps({"job_id": JOB_ID, "reconnect": True})}
    assert sum(event["event"] == "timeout" for event in events) == 1


@pytest.mark.asyncio
async def test_per_tenant_cap_and_cancel_cleanup():
    repo = SimpleNamespace(get=AsyncMock(return_value=job()))
    streams = [await stream(repo) for _ in range(4)]
    for iterator in streams:
        assert (await anext(iterator))["event"] == "progress"
    refused = await stream(repo)
    assert [event async for event in refused] == [{"event": "error", "data": "too_many_streams"}]
    pending = asyncio.create_task(anext(streams[0]))
    await asyncio.sleep(0)
    pending.cancel()
    with pytest.raises(StopAsyncIteration):
        await pending
    for iterator in streams:
        await iterator.aclose()


@pytest.mark.asyncio
async def test_total_cap_and_unstarted_generator():
    repo = SimpleNamespace(get=AsyncMock(return_value=job()))
    unused = await stream(repo)
    assert analyze._job_stream_total == 0
    streams = []
    # Auth disabled: limiter falls back to the normalized header tenant.
    for index in range(3):
        for _ in range(4):
            iterator = await stream(repo, tenant=f"tenant-{index}", auth=SimpleNamespace(enabled=False))
            streams.append(iterator)
            await anext(iterator)
    refused = await stream(repo, tenant="other", auth=SimpleNamespace(enabled=False))
    assert [event async for event in refused] == [{"event": "error", "data": "too_many_streams"}]
    for iterator in streams + [unused]:
        await iterator.aclose()


@pytest.mark.asyncio
async def test_internal_error_is_sanitized():
    repo = SimpleNamespace(get=AsyncMock(side_effect=RuntimeError("private diagnostic")))
    assert [event async for event in await stream(repo)] == [
        {"event": "error", "data": analyze.INTERNAL_ERROR_DETAIL},
    ]


@pytest.mark.asyncio
async def test_enabled_auth_without_authority_is_forbidden():
    repo = SimpleNamespace(get=AsyncMock())
    with pytest.raises(HTTPException) as exc:
        await stream(repo, auth=SimpleNamespace(enabled=True, is_admin=False))
    assert exc.value.status_code == 403
    repo.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_deadline_cancels_stuck_repository(monkeypatch):
    monkeypatch.setattr(analyze, "JOB_STREAM_MAX_SECONDS", 0.01)
    cancelled = asyncio.Event()

    async def get(_job_id):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    events = [event async for event in await stream(SimpleNamespace(get=get))]
    assert events == [{"event": "timeout", "data": json.dumps({"job_id": JOB_ID, "reconnect": True})}]
    assert cancelled.is_set()
