"""WBUX-4 INT-02: startup reclaim of interrupted runs.

The bulk worker runs in-process (FastAPI background task) and does not survive
a service restart. Any run left PENDING/RUNNING at startup is orphaned — no
worker will ever finish it, so `_recompute_run_totals` never reaches terminal
and the frontend would poll it indefinitely. Startup reclaim marks such runs
terminal (FAILED) so they stop being polled and are reported honestly.
"""

from __future__ import annotations

import asyncio
import uuid

from scene.application.describe_run_repository import (
    DescribeRunRepository,
    run_startup_reclaim,
)
from scene.domain.describe_run import DescribeItemStatus, DescribeRunStatus
from scene.tests.test_describe_run_repository import _sessionmaker


def test_reclaim_marks_orphaned_nonterminal_runs_failed_and_preserves_completed_items():
    async def body():
        engine, sf = await _sessionmaker()
        tenant = uuid.uuid4()
        async with sf() as s:
            repo = DescribeRunRepository(s, max_items=3)
            run_id = await repo.create_run(tenant_id=tenant, media_ids=[101, 102])
            # 101 finished before the crash; 102 was still queued.
            await repo.record_item_result(
                tenant_id=tenant,
                run_id=run_id,
                media_id=101,
                alt_text_draft="done",
                caption="c",
                provenance={"adapter": "florence"},
            )
            await repo.mark_item(
                tenant_id=tenant, run_id=run_id, media_id=101, status=DescribeItemStatus.COMPLETED
            )
            # Run left non-terminal (RUNNING) as if the process died mid-run.
            run = await repo.get_run(tenant_id=tenant, run_id=run_id)
            run.status = DescribeRunStatus.RUNNING
            await s.commit()

        reclaimed = await run_startup_reclaim(sf)
        assert reclaimed == 1

        async with sf() as s:
            repo = DescribeRunRepository(s, max_items=3)
            run = await repo.get_run(tenant_id=tenant, run_id=run_id)
            items = {i.media_id: i for i in await repo.list_run_items(tenant_id=tenant, run_id=run_id)}

        assert run.status == DescribeRunStatus.FAILED
        assert run.completed_at is not None
        assert run.error_message
        # completed item kept its draft; queued item failed; bytes cleared.
        assert items[101].status == DescribeItemStatus.COMPLETED
        assert items[101].alt_text_draft == "done"
        assert items[102].status == DescribeItemStatus.FAILED
        assert items[101].image_bytes is None and items[102].image_bytes is None
        # counters honest after reclaim.
        assert run.completed_items == 1
        assert run.failed_items == 1

        await engine.dispose()

    asyncio.run(body())


def test_reclaim_leaves_terminal_runs_untouched():
    async def body():
        engine, sf = await _sessionmaker()
        tenant = uuid.uuid4()
        async with sf() as s:
            repo = DescribeRunRepository(s, max_items=1)
            run_id = await repo.create_run(tenant_id=tenant, media_ids=[201])
            await repo.mark_item(
                tenant_id=tenant, run_id=run_id, media_id=201, status=DescribeItemStatus.COMPLETED
            )
            await s.commit()

        reclaimed = await run_startup_reclaim(sf)
        assert reclaimed == 0

        async with sf() as s:
            run = await DescribeRunRepository(s).get_run(tenant_id=tenant, run_id=run_id)
        assert run.status != DescribeRunStatus.FAILED
        await engine.dispose()

    asyncio.run(body())
