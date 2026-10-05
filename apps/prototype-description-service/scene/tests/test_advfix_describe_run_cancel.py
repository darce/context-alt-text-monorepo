"""ADVFIX-1: task cancellation must terminalize the describe run before settlement."""

from __future__ import annotations

import asyncio
import uuid
from typing import cast

import pytest
from sqlalchemy import Table
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db.models.base_imports import Base
from db.models.scene import DescribeRun, DescribeRunItem
from db.models.tenant import Tenant
from db.tenant_context import set_tenant_context
from scene.application.describe_run_repository import DescribeRunRepository
from scene.application.describe_run_worker import GpuRunPolicy, run_describe_job
from scene.domain.describe_run import DescribeItemStatus, DescribeRunStatus


TENANT_ID = uuid.UUID("00000000-0000-0000-0000-0000000000ad")


def test_task_cancel_terminalizes_run_before_usage_settlement(tmp_path, monkeypatch):
    import scene.application.describe_run_worker as worker

    run_id = uuid.uuid4()
    url = f"sqlite+aiosqlite:///{tmp_path / 'cancelled-describe-run.db'}"
    settled_statuses: list[DescribeRunStatus] = []
    gpu_ready = asyncio.Event()
    describe_started = asyncio.Event()

    async def _capture_fence(*_, **__):
        return "test-fence"

    async def _settle(session, *, tenant_id, job_id, fence_token):
        del fence_token
        run = await DescribeRunRepository(session).get_run(tenant_id=tenant_id, run_id=uuid.UUID(job_id))
        assert run is not None
        settled_statuses.append(DescribeRunStatus(run.status))

    async def _publish_demand_snapshot(_session_factory):
        return None

    async def _wait_for_gpu_ready(**_kwargs):
        gpu_ready.set()
        return True

    async def _describe_one(*_args, **_kwargs):
        assert gpu_ready.is_set()
        describe_started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(worker, "capture_usage_fence", _capture_fence)
    monkeypatch.setattr(worker, "settle_usage_job", _settle)
    monkeypatch.setattr(worker, "publish_demand_snapshot", _publish_demand_snapshot)
    monkeypatch.setattr(worker, "_wait_for_gpu_ready", _wait_for_gpu_ready)

    async def _exercise_cancellation():
        engine = create_async_engine(url)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(
                    Base.metadata.create_all,
                    tables=cast(list[Table], [Tenant.__table__, DescribeRun.__table__, DescribeRunItem.__table__]),
                )
            session_factory = async_sessionmaker(engine, expire_on_commit=False)
            async with session_factory() as session:
                session.add(Tenant(id=TENANT_ID, site_url="http://test.local"))
                await session.flush()
                await set_tenant_context(session, TENANT_ID)
                run_id_created = await DescribeRunRepository(session).create_run(
                    tenant_id=TENANT_ID,
                    media_ids=[17],
                    images={17: (b"image-bytes", "image/png")},
                    run_id=run_id,
                )
                await session.commit()
            assert run_id_created == run_id

            task = asyncio.create_task(
                run_describe_job(
                    tenant_id=TENANT_ID,
                    run_id=run_id,
                    session_factory=session_factory,
                    describe_one=_describe_one,
                    timeout_seconds=60,
                    gpu_policy=GpuRunPolicy(
                        endpoint_url="http://gpu.test",
                        api_key=None,
                        warmup_timeout_seconds=60,
                    ),
                )
            )
            await asyncio.wait_for(describe_started.wait(), timeout=5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

            async with session_factory() as session:
                repo = DescribeRunRepository(session)
                run = await repo.get_run(tenant_id=TENANT_ID, run_id=run_id)
                items = await repo.list_run_items(tenant_id=TENANT_ID, run_id=run_id)
            assert run is not None
            assert run.status == DescribeRunStatus.CANCELLED
            assert items[0].status == DescribeItemStatus.SKIPPED
            assert items[0].image_bytes is None
            assert settled_statuses == [DescribeRunStatus.CANCELLED]
        finally:
            await engine.dispose()

    asyncio.run(_exercise_cancellation())
