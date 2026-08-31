"""Tracked worker execution for scene describe runs."""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.tenant_context import set_tenant_context
from scene.application.describe_load import dump_load_snapshot
from scene.application.describe_run_repository import DescribeRunRepository
from scene.application.settings.vlm import VlmSettings
from scene.config.profiles import get_profile_spec
from scene.config.settings import DescriptionSettings
from scene.domain.describe_run import DescribeItemStatus
from scene.domain.description import DescriptionAdapterKind

logger = logging.getLogger(__name__)

_DEFAULT_GPU_WARMUP_TIMEOUT_SECONDS = 480.0
_GPU_HEALTH_POLL_INTERVAL_SECONDS = 2.0
_GPU_HEALTH_REQUEST_TIMEOUT_SECONDS = 5.0
_GPU_ITEM_MAX_ATTEMPTS = 3
_GPU_ITEM_RETRY_BASE_DELAY_SECONDS = 1.0
_RETRYABLE_HTTP_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})


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


def _gpu_warmup_target() -> tuple[str, str | None, float] | None:
    """Return the selected GPU endpoint's health target, if this is a GPU run.

    An endpoint may be present in a shared deployment environment while the
    active description profile is seeded or CPU-backed. Profile-gating here is
    deliberate: those paths must never acquire a dependency on burst-GPU
    availability.
    """

    settings = DescriptionSettings()
    profile = get_profile_spec(settings.profile)
    if profile.adapter_kind is not DescriptionAdapterKind.GPU or not settings.gpu_endpoint_url:
        return None
    timeout_seconds = float(os.environ.get("ACX_GPU_WARMUP_TIMEOUT_SECONDS", str(_DEFAULT_GPU_WARMUP_TIMEOUT_SECONDS)))
    return settings.gpu_endpoint_url.rstrip("/"), settings.gpu_endpoint_api_key, max(0.0, timeout_seconds)


async def _wait_for_gpu_ready(*, endpoint_url: str, api_key: str | None, timeout_seconds: float) -> None:
    """Poll the burst endpoint until it reports healthy or warmup expires."""

    health_url = f"{endpoint_url}/health"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    last_error = "no health response"
    timeout = httpx.Timeout(_GPU_HEALTH_REQUEST_TIMEOUT_SECONDS)

    async with httpx.AsyncClient(timeout=timeout) as client:
        while True:
            try:
                response = await client.get(health_url, headers=headers)
                if 200 <= response.status_code < 300:
                    return
                last_error = f"HTTP {response.status_code}"
            except httpx.HTTPError as exc:
                # Connection refusal and 503 are normal while cloud-init/model
                # loading is still in progress. Keep the log quiet until the
                # bounded warmup window is actually exhausted.
                last_error = f"{type(exc).__name__}: {exc}"

            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TimeoutError(f"GPU endpoint did not become ready within {timeout_seconds:g}s ({last_error})")
            await asyncio.sleep(min(_GPU_HEALTH_POLL_INTERVAL_SECONDS, remaining))


def _is_transient_describe_error(exc: BaseException) -> bool:
    """Classify endpoint faults, including those wrapped by the GPU adapter."""

    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (TimeoutError, httpx.TransportError)):
            return True
        if isinstance(current, httpx.HTTPStatusError):
            return current.response.status_code in _RETRYABLE_HTTP_STATUS_CODES
        current = current.__cause__ or current.__context__
    return False


async def _describe_with_transient_retry(
    *,
    describe_one: DescribeOne,
    media_id: int,
    image_bytes: bytes | None,
    content_type: str | None,
    timeout_seconds: float,
    retry_transient: bool,
) -> DescribeItemOutcome | None:
    max_attempts = _GPU_ITEM_MAX_ATTEMPTS if retry_transient else 1
    for attempt in range(1, max_attempts + 1):
        try:
            return await asyncio.wait_for(
                _call_describe_one(describe_one, media_id, image_bytes, content_type), timeout_seconds
            )
        except Exception as exc:  # noqa: BLE001 - classify before retrying
            if attempt >= max_attempts or not _is_transient_describe_error(exc):
                raise
            delay = _GPU_ITEM_RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1))
            logger.info(
                "retrying transient describe failure media_id=%s attempt=%s/%s delay_seconds=%s",
                media_id,
                attempt + 1,
                max_attempts,
                delay,
            )
            await asyncio.sleep(delay)
    raise RuntimeError("unreachable")  # pragma: no cover


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
        gpu_target = _gpu_warmup_target()
        if gpu_target is not None:
            endpoint_url, api_key, warmup_timeout = gpu_target
            await _wait_for_gpu_ready(
                endpoint_url=endpoint_url,
                api_key=api_key,
                timeout_seconds=warmup_timeout,
            )
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
                    outcome = await _describe_with_transient_retry(
                        describe_one=describe_one,
                        media_id=item.media_id,
                        image_bytes=image_bytes,
                        content_type=content_type,
                        timeout_seconds=timeout,
                        retry_transient=gpu_target is not None,
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
