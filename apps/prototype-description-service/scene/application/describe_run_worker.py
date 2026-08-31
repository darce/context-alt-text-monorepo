"""Tracked worker execution for scene describe runs."""

from __future__ import annotations

import asyncio
import inspect
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.tenant_context import set_tenant_context
from scene.application.describe_load import dump_load_snapshot
from scene.application.describe_run_repository import DescribeRunRepository
from scene.application.settings.vlm import VlmSettings
from scene.domain.describe_run import DescribeItemStatus

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DescribeItemOutcome:
    """Result the describe adapter yields per item; persisted by the worker."""

    alt_text_draft: str | None = None
    caption: str | None = None
    provenance: dict = field(default_factory=dict)


# The describe boundary: given the item's media_id + loaded image bytes, return
# the outcome to persist (or None). Kept as an injectable callable so tests can
# supply a fast deterministic fake while production supplies the real
# VisualFactsService-backed adapter.
DescribeOne = Callable[
    [int, bytes | None, str | None],
    Awaitable[DescribeItemOutcome | None] | DescribeItemOutcome | None,
]


async def _call_describe_one(
    describe_one: DescribeOne, media_id: int, image_bytes: bytes | None, content_type: str | None
) -> DescribeItemOutcome | None:
    result = describe_one(media_id, image_bytes, content_type)
    if inspect.isawaitable(result):
        result = await result
    return result


async def run_describe_job(
    *,
    tenant_id: uuid.UUID,
    run_id: uuid.UUID,
    session_factory: async_sessionmaker[AsyncSession],
    describe_one: DescribeOne,
    timeout_seconds: float | None = None,
) -> None:
    """Process a describe run item-by-item.

    Per item: load its image bytes, run ``describe_one``, persist the draft /
    caption / provenance, clear the stored bytes, and mark it COMPLETED. Per-item
    failures are isolated (item -> FAILED, run continues); an unexpected fatal
    error around the whole loop forces the run terminal-FAILED. (S2-01, S2-02, HARM-01)
    """

    timeout = timeout_seconds if timeout_seconds is not None else VlmSettings().inference_timeout_seconds
    try:
        async with session_factory() as session:
            # RLS: every session touching the tenant-scoped run/item tables must
            # set app.current_tenant, else FORCE RLS on Postgres returns zero rows.
            await set_tenant_context(session, tenant_id)
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

                image_bytes = item.image_bytes
                content_type = item.image_content_type
                await repo.mark_item(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    media_id=item.media_id,
                    status=DescribeItemStatus.RUNNING,
                )
                try:
                    outcome = await asyncio.wait_for(
                        _call_describe_one(describe_one, item.media_id, image_bytes, content_type), timeout
                    )
                except Exception as exc:  # noqa: BLE001 - per-item failure must not abort the run
                    logger.warning(
                        "describe run item failed run_id=%s media_id=%s", run_id, item.media_id, exc_info=True
                    )
                    await repo.record_item_result(
                        tenant_id=tenant_id,
                        run_id=run_id,
                        media_id=item.media_id,
                        alt_text_draft=None,
                        caption=None,
                        provenance=None,
                    )
                    await repo.mark_item(
                        tenant_id=tenant_id,
                        run_id=run_id,
                        media_id=item.media_id,
                        status=DescribeItemStatus.FAILED,
                        error_message=str(exc),
                    )
                else:
                    outcome = outcome or DescribeItemOutcome()
                    await repo.record_item_result(
                        tenant_id=tenant_id,
                        run_id=run_id,
                        media_id=item.media_id,
                        alt_text_draft=outcome.alt_text_draft,
                        caption=outcome.caption,
                        provenance=outcome.provenance or None,
                    )
                    await repo.mark_item(
                        tenant_id=tenant_id,
                        run_id=run_id,
                        media_id=item.media_id,
                        status=DescribeItemStatus.COMPLETED,
                    )
                await session.commit()
    except Exception as fatal:  # noqa: BLE001 - fatal loop error must surface as a FAILED run
        logger.exception("describe run fatal error run_id=%s", run_id)
        try:
            async with session_factory() as session:
                await set_tenant_context(session, tenant_id)
                await DescribeRunRepository(session).mark_run_failed(
                    tenant_id=tenant_id, run_id=run_id, error_message=str(fatal)
                )
                await session.commit()
        except Exception:  # noqa: BLE001 - best-effort terminal write
            logger.exception("failed to mark run FAILED run_id=%s", run_id)
    finally:
        # GPUW-1: refresh the burst-GPU load dump on completion, failure AND
        # cancellation. A release that only fires on the happy path is a
        # reclaimer that eventually does not fire [RES-07] -- and here the cost
        # of not firing is an A10 held open at ~$2/hr.
        await dump_load_snapshot(session_factory)
