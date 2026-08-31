"""Tracked worker execution for scene describe runs."""

from __future__ import annotations

import asyncio
import inspect
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.tenant_context import set_tenant_context
from scene.application.describe_load import dump_load_snapshot
from scene.application.describe_run_repository import DescribeRunRepository
from scene.application.settings.vlm import VlmSettings
from scene.config.settings import DEFAULT_GPU_WARMUP_TIMEOUT_SECONDS, DescriptionSettings
from scene.domain.describe_run import DescribeItemStatus
from scene.domain.description import DescriptionAdapterKind

logger = logging.getLogger(__name__)

_DEFAULT_GPU_WARMUP_TIMEOUT_SECONDS = DEFAULT_GPU_WARMUP_TIMEOUT_SECONDS
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


@dataclass(frozen=True)
class GpuRunPolicy:
    """GPU-only execution settings resolved with the actual run adapter."""

    endpoint_url: str
    api_key: str | None
    warmup_timeout_seconds: float


class _RunCancelledError(RuntimeError):
    """Internal control-flow signal; cancellation is not a run failure."""


class _GpuCircuitOpenError(RuntimeError):
    """The run-local GPU breaker is open after an exhausted transient fault."""


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


def gpu_run_policy(*, adapter_kind: DescriptionAdapterKind, settings: DescriptionSettings) -> GpuRunPolicy | None:
    """Build a policy only when the adapter captured for this run is GPU-backed.

    The worker accepts this policy explicitly instead of re-reading the process
    profile. That keeps injected/seeded workers isolated from a concurrently
    changed GPU environment and makes retry eligibility a property of the
    adapter actually captured by the route.
    """

    if adapter_kind is not DescriptionAdapterKind.GPU or not settings.gpu_endpoint_url:
        return None
    return GpuRunPolicy(
        endpoint_url=settings.gpu_endpoint_url.rstrip("/"),
        api_key=settings.gpu_endpoint_api_key,
        warmup_timeout_seconds=settings.gpu_warmup_timeout_seconds,
    )


async def _wait_for_gpu_ready(
    *,
    endpoint_url: str,
    api_key: str | None,
    timeout_seconds: float,
    cancel_requested: Callable[[], Awaitable[bool]] | None = None,
) -> None:
    """Poll the burst endpoint until it reports healthy or warmup expires."""

    health_url = f"{endpoint_url}/health"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max(0.0, timeout_seconds)
    last_error = "no health response"
    timeout = httpx.Timeout(_GPU_HEALTH_REQUEST_TIMEOUT_SECONDS)

    async with httpx.AsyncClient(timeout=timeout) as client:
        while True:
            if cancel_requested is not None and await cancel_requested():
                raise _RunCancelledError("describe run cancelled while waiting for GPU readiness")
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TimeoutError(f"GPU endpoint did not become ready within {timeout_seconds:g}s ({last_error})")
            try:
                # The httpx timeout bounds transport phases individually. The
                # outer wait_for also caps the whole request to the remaining
                # warmup budget, so one hung health request cannot overrun the
                # run-level deadline.
                response = await asyncio.wait_for(
                    client.get(health_url, headers=headers),
                    timeout=min(_GPU_HEALTH_REQUEST_TIMEOUT_SECONDS, remaining),
                )
                if 200 <= response.status_code < 300:
                    return
                last_error = f"HTTP {response.status_code}"
            except (TimeoutError, httpx.HTTPError) as exc:
                # Connection refusal and 503 are normal while cloud-init/model
                # loading is still in progress. Keep the log quiet until the
                # bounded warmup window is actually exhausted.
                last_error = f"{type(exc).__name__}: {exc}"

            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TimeoutError(f"GPU endpoint did not become ready within {timeout_seconds:g}s ({last_error})")
            await asyncio.sleep(min(_GPU_HEALTH_POLL_INTERVAL_SECONDS, remaining))


def _is_transient_describe_error(exc: BaseException) -> bool:
    """Classify endpoint faults, including those wrapped by the GPU adapter.

    A bare ``TimeoutError`` with no httpx fault anywhere in its cause chain is
    the worker's OWN ``asyncio.wait_for`` budget expiring, not an endpoint
    fault. The underlying to_thread request keeps running when the wait is
    cancelled, so retrying stacks a new concurrent generation on a busy
    endpoint; local expiries are therefore deliberately non-transient.
    Endpoint-originated faults surface as httpx exceptions or carry one as
    their cause and stay retryable.
    """

    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError, httpx.ProxyError)):
            return True
        if isinstance(current, httpx.HTTPStatusError):
            return current.response.status_code in _RETRYABLE_HTTP_STATUS_CODES
        if current.__cause__ is not None:
            current = current.__cause__
        elif current.__suppress_context__:
            # `raise ... from None` deliberately severed the chain; walking into
            # the suppressed context would resurrect a transient signal the
            # raiser explicitly discarded.
            break
        else:
            current = current.__context__
    return False


async def _describe_with_transient_retry(
    *,
    describe_one: DescribeOne,
    media_id: int,
    image_bytes: bytes | None,
    content_type: str | None,
    timeout_seconds: float,
    retry_transient: bool,
    cancel_requested: Callable[[], Awaitable[bool]] | None = None,
) -> DescribeItemOutcome | None:
    max_attempts = _GPU_ITEM_MAX_ATTEMPTS if retry_transient else 1
    for attempt in range(1, max_attempts + 1):
        if cancel_requested is not None and await cancel_requested():
            raise _RunCancelledError("describe run cancelled before item retry")
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
            if delay:
                await asyncio.sleep(delay)
    raise RuntimeError("unreachable")  # pragma: no cover


async def run_describe_job(
    *,
    tenant_id: uuid.UUID,
    run_id: uuid.UUID,
    session_factory: async_sessionmaker[AsyncSession],
    describe_one: DescribeOne,
    timeout_seconds: float | None = None,
    gpu_policy: GpuRunPolicy | None = None,
) -> None:
    """Process a describe run item-by-item.

    Per item: load its image bytes, run ``describe_one``, persist the draft /
    caption / provenance, clear the stored bytes, and mark it COMPLETED. Per-item
    failures are isolated (item -> FAILED, run continues); an unexpected fatal
    error around the whole loop forces the run terminal-FAILED. (S2-01, S2-02, HARM-01)
    """

    timeout = timeout_seconds if timeout_seconds is not None else VlmSettings().inference_timeout_seconds

    async def cancel_requested() -> bool:
        # A fresh, short-lived session is intentional. The tracking session has
        # expire_on_commit=False and may otherwise keep an identity-mapped run
        # with cancel_requested=False after DELETE commits in another session.
        async with session_factory() as cancel_session:
            await set_tenant_context(cancel_session, tenant_id)
            run = await DescribeRunRepository(cancel_session).get_run(tenant_id=tenant_id, run_id=run_id)
            return run is None or bool(run.cancel_requested)

    try:
        if gpu_policy is not None:
            await _wait_for_gpu_ready(
                endpoint_url=gpu_policy.endpoint_url,
                api_key=gpu_policy.api_key,
                timeout_seconds=gpu_policy.warmup_timeout_seconds,
                cancel_requested=cancel_requested,
            )
        async with session_factory() as session:
            # RLS: every session touching the tenant-scoped run/item tables must
            # set app.current_tenant, else FORCE RLS on Postgres returns zero rows.
            await set_tenant_context(session, tenant_id)
            repo = DescribeRunRepository(session)
            items = await repo.list_run_items(tenant_id=tenant_id, run_id=run_id)
            gpu_breaker_error: str | None = None
            for item in items:
                if await cancel_requested():
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
                    if gpu_breaker_error is not None:
                        raise _GpuCircuitOpenError(gpu_breaker_error)
                    outcome = await _describe_with_transient_retry(
                        describe_one=describe_one,
                        media_id=item.media_id,
                        image_bytes=image_bytes,
                        content_type=content_type,
                        timeout_seconds=timeout,
                        retry_transient=gpu_policy is not None,
                        cancel_requested=cancel_requested,
                    )
                except _RunCancelledError:
                    await repo.mark_item(
                        tenant_id=tenant_id,
                        run_id=run_id,
                        media_id=item.media_id,
                        status=DescribeItemStatus.SKIPPED,
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
                    if gpu_policy is not None and _is_transient_describe_error(exc):
                        gpu_breaker_error = (
                            f"GPU circuit open after transient retries were exhausted: {type(exc).__name__}: {exc}"
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
    except _RunCancelledError:
        # Cancellation can land while the worker is still in its GPU warmup
        # gate, before the main tracking session exists. Drive every queued item
        # terminal so the run honestly projects CANCELLED and bytes are reclaimed.
        try:
            async with session_factory() as session:
                await set_tenant_context(session, tenant_id)
                repo = DescribeRunRepository(session)
                for item in await repo.list_run_items(tenant_id=tenant_id, run_id=run_id):
                    await repo.mark_item(
                        tenant_id=tenant_id,
                        run_id=run_id,
                        media_id=item.media_id,
                        status=DescribeItemStatus.SKIPPED,
                    )
                await session.commit()
        except Exception:  # noqa: BLE001 - an exception raised here would escape
            # run_describe_job entirely (the sibling fatal handler cannot catch
            # it), stranding the run non-terminal. Fall back to the terminal
            # writer, which preserves a derived CANCELLED.
            logger.exception("failed to finalize cancelled run run_id=%s", run_id)
            try:
                async with session_factory() as session:
                    await set_tenant_context(session, tenant_id)
                    await DescribeRunRepository(session).mark_run_failed(
                        tenant_id=tenant_id, run_id=run_id, error_message="cancel finalization failed"
                    )
                    await session.commit()
            except Exception:  # noqa: BLE001 - best-effort terminal write
                logger.exception("failed to mark cancelled run terminal run_id=%s", run_id)
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
