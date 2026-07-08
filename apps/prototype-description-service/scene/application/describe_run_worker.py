"""Tracked worker execution for scene describe runs."""

from __future__ import annotations

import asyncio
import inspect
import logging
import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from scene.application.describe_run_repository import DescribeRunRepository
from scene.application.settings.vlm import VlmSettings
from scene.domain.describe_run import DescribeItemStatus

logger = logging.getLogger(__name__)

DescribeOne = Callable[[int], Awaitable[None] | None]

_RUN_TASKS: dict[uuid.UUID, asyncio.Task] = {}


async def _call_describe_one(describe_one: DescribeOne, media_id: int) -> None:
    result = describe_one(media_id)
    if inspect.isawaitable(result):
        await result


async def run_describe_job(
    *,
    tenant_id: uuid.UUID,
    run_id: uuid.UUID,
    session_factory: async_sessionmaker[AsyncSession],
    describe_one: DescribeOne,
    timeout_seconds: float | None = None,
) -> None:
    """Process a describe run item-by-item.

    The callable boundary is intentionally narrow for Slice 2: route submission
    and queue semantics are testable now; later slices provide the concrete image
    loading/VisualFacts adapter integration.
    """

    timeout = timeout_seconds if timeout_seconds is not None else VlmSettings().inference_timeout_seconds
    async with session_factory() as session:
        repo = DescribeRunRepository(session)
        items = await repo.list_run_items(tenant_id=tenant_id, run_id=run_id)
        for item in items:
            run = await repo.get_run(tenant_id=tenant_id, run_id=run_id)
            if run is None:
                return
            if run.cancel_requested:
                await repo.mark_item(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    media_id=item.media_id,
                    status=DescribeItemStatus.SKIPPED,
                )
                await session.commit()
                continue

            await repo.mark_item(
                tenant_id=tenant_id,
                run_id=run_id,
                media_id=item.media_id,
                status=DescribeItemStatus.RUNNING,
            )
            try:
                await asyncio.wait_for(_call_describe_one(describe_one, item.media_id), timeout)
            except Exception as exc:  # noqa: BLE001 - per-item failure must not abort the run
                logger.warning("describe run item failed run_id=%s media_id=%s", run_id, item.media_id, exc_info=True)
                await repo.mark_item(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    media_id=item.media_id,
                    status=DescribeItemStatus.FAILED,
                    error_message=str(exc),
                )
            else:
                await repo.mark_item(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    media_id=item.media_id,
                    status=DescribeItemStatus.COMPLETED,
                )
            await session.commit()


def track_describe_task(run_id: uuid.UUID, task: asyncio.Task) -> None:
    _RUN_TASKS[run_id] = task
    task.add_done_callback(lambda _: _RUN_TASKS.pop(run_id, None))


def get_tracked_describe_task(run_id: uuid.UUID) -> asyncio.Task | None:
    return _RUN_TASKS.get(run_id)
