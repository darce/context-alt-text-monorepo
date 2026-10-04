"""ADVFIX-1: cancelling initial fence capture still settles the describe run."""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import pytest

from scene.application.describe_run_worker import run_describe_job
from scene.domain.describe_run import DescribeItemStatus, DescribeRunStatus


TENANT_ID = uuid.UUID("00000000-0000-0000-0000-0000000000ae")


def test_task_cancel_during_initial_fence_capture_terminalizes_and_settles(monkeypatch):
    import scene.application.describe_run_worker as worker

    run_id = uuid.uuid4()
    run = SimpleNamespace(status=DescribeRunStatus.PENDING, cancel_requested=False)
    item = SimpleNamespace(media_id=17, status=DescribeItemStatus.QUEUED, image_bytes=b"queued-image")
    settled_statuses: list[DescribeRunStatus] = []

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def commit(self):
            return None

    class _Repository:
        def __init__(self, _session):
            pass

        async def request_cancel(self, **_kwargs):
            run.cancel_requested = True

        async def list_run_items(self, **_kwargs):
            return [item]

        async def mark_item(self, *, status, **_kwargs):
            item.status = status
            item.image_bytes = None
            if run.cancel_requested and item.status == DescribeItemStatus.SKIPPED:
                run.status = DescribeRunStatus.CANCELLED

    async def _set_tenant_context(*_args, **_kwargs):
        return None

    async def _capture_fence(*_args, **_kwargs):
        capture_started.set()
        await asyncio.Event().wait()

    async def _settle(_session, *, tenant_id, job_id, fence_token):
        assert tenant_id == TENANT_ID
        assert job_id == str(run_id)
        assert fence_token is None
        settled_statuses.append(run.status)

    async def _publish_demand_snapshot(_session_factory):
        return None

    async def _describe_one(*_args, **_kwargs):
        raise AssertionError("description must not start before fence capture completes")

    session_factory = _Session
    capture_started = asyncio.Event()
    monkeypatch.setattr(worker, "DescribeRunRepository", _Repository)
    monkeypatch.setattr(worker, "set_tenant_context", _set_tenant_context)
    monkeypatch.setattr(worker, "capture_usage_fence", _capture_fence)
    monkeypatch.setattr(worker, "settle_usage_job", _settle)
    monkeypatch.setattr(worker, "publish_demand_snapshot", _publish_demand_snapshot)

    async def _exercise_cancellation():
        task = asyncio.create_task(
            run_describe_job(
                tenant_id=TENANT_ID,
                run_id=run_id,
                session_factory=session_factory,
                describe_one=_describe_one,
            )
        )
        await asyncio.wait_for(capture_started.wait(), timeout=5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(_exercise_cancellation())

    assert run.status == DescribeRunStatus.CANCELLED
    assert item.status == DescribeItemStatus.SKIPPED
    assert item.image_bytes is None
    assert settled_statuses == [DescribeRunStatus.CANCELLED]
