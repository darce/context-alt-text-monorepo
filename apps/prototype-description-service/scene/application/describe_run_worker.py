"""Tracked worker execution for scene describe runs."""

from __future__ import annotations

import asyncio
import enum
import inspect
import json
import logging
import os
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final, Literal, NamedTuple, Protocol, runtime_checkable

import httpx
from sqlalchemy import select
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.models.scene import DescribeOperation, DescribeStartup
from db.tenant_context import get_tenant_record, set_tenant_context
from scene.application.describe_load import load_snapshot, resolve_load_path, write_load_snapshot
from scene.application.describe_run_repository import DescribeRunRepository
from scene.application.identity_merge import NamingRealizer, NamingStatus
from scene.application.naming_preview_service import (
    faces_for_naming_preview,
    load_fusion_naming_inputs,
    naming_preview,
)
from scene.application.settings.vlm import VlmSettings
from scene.config.settings import DEFAULT_GPU_WARMUP_TIMEOUT_SECONDS, DescriptionSettings
from scene.domain.describe_run import (
    TERMINAL_ITEM_STATUSES,
    DescribeItemStatus,
    DescribeRunPhase,
    DescribeRunStatus,
    elapsed_ms,
)
from scene.domain.description import DescriptionAdapterKind, DescriptionResultTier
from scene.infrastructure.vlm.unavailable_adapter import UnavailableDescriptionAdapter

if TYPE_CHECKING:
    from scene.application.identity_merge.policy import NamingPolicy

logger = logging.getLogger(__name__)

_DEFAULT_GPU_WARMUP_TIMEOUT_SECONDS = DEFAULT_GPU_WARMUP_TIMEOUT_SECONDS
_GPU_HEALTH_POLL_INTERVAL_SECONDS = 2.0
_GPU_HEALTH_REQUEST_TIMEOUT_SECONDS = 5.0
_GPU_ITEM_MAX_ATTEMPTS = 3
_GPU_ITEM_RETRY_BASE_DELAY_SECONDS = 1.0
_RETRYABLE_HTTP_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})
# Inner lookup/preview cap. The enforced per-item bound is item_envelope_seconds
# (this budget + describe timeout); Stage-3 preview uses the remaining envelope.
NAMING_BUDGET_SECONDS = float(os.environ.get("ACX_NAMING_BUDGET_SECONDS", "10.0"))
# rg-007: consecutive items that never reach a terminal mark abort the cycle.
_ITEM_NO_PROGRESS_LIMIT = 3


class FusionNamingInputs(NamedTuple):
    """Confirmed faces + naming policy loaded once per bulk item (DATA-19)."""

    confirmed_faces: list
    naming_policy: NamingPolicy | None = None


EMPTY_NAMING_INPUTS = FusionNamingInputs(confirmed_faces=[], naming_policy=None)


class _NamingBudget(enum.Enum):
    EXCEEDED = enum.auto()


_NAMING_BUDGET_EXCEEDED: Final = _NamingBudget.EXCEEDED


class MissingNamingSnapshotError(RuntimeError):
    """Recognition-enabled describe_one was called without a preloaded snapshot."""


def item_envelope_seconds(describe_timeout_seconds: float) -> float:
    """Wall-clock bound for one bulk item: naming lookup, describe, and Stage-3 preview.

    PERF-10 traded for DATA-19 (WBUX-6 S9-F1): serial single load instead of
    gathering lookup with describe, so the envelope is the sum of
    ``NAMING_BUDGET_SECONDS`` and the describe timeout, not the max.

    Stage-3 naming preview runs inside this envelope: its wait_for budget is
    ``min(NAMING_BUDGET_SECONDS, remaining)`` so a hung preview cannot add a
    second full naming budget (S9R2-F1 / RES-03).
    """
    return NAMING_BUDGET_SECONDS + describe_timeout_seconds


@dataclass(frozen=True)
class DescribeItemOutcome:
    """Result the describe adapter yields per item; persisted by the worker."""

    alt_text_draft: str | None = None
    caption: str | None = None
    provenance: dict = field(default_factory=dict)
    phrase_boxes: tuple = ()
    attachments: tuple = ()
    tier: DescriptionResultTier | str | None = None
    processing_ms: float | None = None


@dataclass(frozen=True)
class GpuRunPolicy:
    """GPU-only execution settings resolved with the actual run adapter."""

    endpoint_url: str
    api_key: str | None
    warmup_timeout_seconds: float


class DescribeRunTerminalCode(enum.StrEnum):
    """Typed terminal codes persisted on a FAILED describe run (C2)."""

    GPU_WARMUP_TIMEOUT = "gpu_warmup_timeout"


class DescribeRunTerminalReason(enum.StrEnum):
    """Per-item/run reason stamps for a warmup-timeout continuation (C2)."""

    GPU_WARMUP_TIMEOUT = "gpu_warmup_timeout"


class DescriptionFallbackTier(enum.StrEnum):
    """Wire tier for CPU continuation after GPU warmup expiry (C2).

    ``DescriptionResultTier`` in ``scene/domain/description.py`` does not yet
    include this member; persist the C2 token and coerce through
    ``PROVISIONAL_CPU`` at the repository boundary.
    """

    CPU_FALLBACK = "cpu_fallback"


class _RunCancelledError(RuntimeError):
    """Internal control-flow signal; cancellation is not a run failure."""

    def __init__(self, message: str = "describe run cancelled", *, processing_ms: float | None = None):
        super().__init__(message)
        self.processing_ms = processing_ms


class _GpuCircuitOpenError(RuntimeError):
    """The run-local GPU breaker is open after an exhausted transient fault."""


# The describe boundary: given the item's media_id + loaded image bytes, return
# the outcome to persist (or None). Kept as an injectable callable so tests can
# supply a fast deterministic fake while production supplies the real
# VisualFactsService-backed adapter. naming_inputs is keyword-only so a wrapper
# cannot silently drop the DATA-19 snapshot.
@runtime_checkable
class DescribeOne(Protocol):
    def __call__(
        self,
        media_id: int,
        image_bytes: bytes | None,
        content_type: str | None,
        *,
        naming_inputs: FusionNamingInputs | None = None,
    ) -> Awaitable[DescribeItemOutcome | None] | DescribeItemOutcome | None: ...


async def _call_describe_one(
    describe_one: DescribeOne,
    media_id: int,
    image_bytes: bytes | None,
    content_type: str | None,
    naming_inputs: FusionNamingInputs | None = None,
) -> DescribeItemOutcome | None:
    result = describe_one(media_id, image_bytes, content_type, naming_inputs=naming_inputs)
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


def _usable_cpu_describe_one(
    cpu_describe_one: DescribeOne | UnavailableDescriptionAdapter | None,
) -> DescribeOne | None:
    """Return the CPU callable only when it is configured and not Unavailable."""

    if cpu_describe_one is None or isinstance(cpu_describe_one, UnavailableDescriptionAdapter):
        return None
    return cpu_describe_one


def _gpu_warmup_timeout_detail(*, timeout_seconds: float, error: BaseException) -> str:
    """C2 FAILED terminal payload; probe text stays visible (OBS-08)."""

    return json.dumps(
        {
            "code": DescribeRunTerminalCode.GPU_WARMUP_TIMEOUT,
            "retryable": True,
            "startup_budget_seconds": int(timeout_seconds),
            "message": str(error),
        }
    )


def _cpu_fallback_run_stamp() -> str:
    return json.dumps(
        {
            "tier": DescriptionFallbackTier.CPU_FALLBACK,
            "reason": DescribeRunTerminalReason.GPU_WARMUP_TIMEOUT,
        }
    )


def _persistable_item_tier(
    tier: DescriptionResultTier | str | None,
) -> DescriptionResultTier | str | None:
    """Repository coerces through DescriptionResultTier; cpu_fallback is not a member yet."""

    if tier is None:
        return None
    try:
        return DescriptionResultTier(tier)
    except ValueError:
        return DescriptionResultTier.PROVISIONAL_CPU


async def _fail_run_on_gpu_warmup_timeout(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_id: uuid.UUID,
    run_id: uuid.UUID,
    timeout_seconds: float,
    error: BaseException,
) -> None:
    logger.warning(
        "GPU warmup timed out run_id=%s budget_seconds=%s; no CPU adapter, ending retryable",
        run_id,
        timeout_seconds,
    )
    async with session_factory() as session:
        await set_tenant_context(session, tenant_id)
        await DescribeRunRepository(session).mark_run_failed(
            tenant_id=tenant_id,
            run_id=run_id,
            error_message=_gpu_warmup_timeout_detail(timeout_seconds=timeout_seconds, error=error),
        )
        await session.commit()


async def _wait_for_gpu_ready(
    *,
    endpoint_url: str,
    api_key: str | None,
    timeout_seconds: float,
    cancel_requested: Callable[[], Awaitable[bool]] | None = None,
) -> bool:
    """Poll the burst endpoint until it reports healthy or warmup expires.

    Returns True when the first probe already succeeded (warm; no cold ramp-up).
    """

    health_url = f"{endpoint_url}/health"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max(0.0, timeout_seconds)
    last_error = "no health response"
    timeout = httpx.Timeout(_GPU_HEALTH_REQUEST_TIMEOUT_SECONDS)
    immediately_ready = True

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
                    return immediately_ready
                last_error = f"HTTP {response.status_code}"
            except (TimeoutError, httpx.HTTPError) as exc:
                # Connection refusal and 503 are normal while cloud-init/model
                # loading is still in progress. Keep the log quiet until the
                # bounded warmup window is actually exhausted.
                last_error = f"{type(exc).__name__}: {exc}"
            immediately_ready = False

            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TimeoutError(f"GPU endpoint did not become ready within {timeout_seconds:g}s ({last_error})")
            await asyncio.sleep(min(_GPU_HEALTH_POLL_INTERVAL_SECONDS, remaining))


async def _persist_run_phase(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_id: uuid.UUID,
    run_id: uuid.UUID,
    phase: DescribeRunPhase,
) -> None:
    """Short-lived session so status polls can see warming/describing mid-gate."""
    async with session_factory() as session:
        await set_tenant_context(session, tenant_id)
        run = await DescribeRunRepository(session).get_run(tenant_id=tenant_id, run_id=run_id)
        if run is None:
            return
        run.phase = phase
        if phase is DescribeRunPhase.WARMING:
            run.status = DescribeRunStatus.RUNNING
        await session.commit()


async def publish_demand_snapshot(session_factory) -> None:
    """Commit ``load_snapshot`` then publish the file; never pass STOP flags."""
    from db.tenant_context import enable_rls_bypass

    if session_factory is None:
        return
    try:
        async with session_factory() as session:
            await enable_rls_bypass(session)
            payload = await load_snapshot(session)
        write_load_snapshot(payload, resolve_load_path())
    except Exception:  # noqa: BLE001 - reaper snapshot is best-effort
        logger.debug("describe load snapshot write failed", exc_info=True)


async def _record_run_pickup(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_id: uuid.UUID,
    run_id: uuid.UUID,
) -> None:
    async with session_factory() as session:
        await set_tenant_context(session, tenant_id)
        await DescribeRunRepository(session).record_pickup(tenant_id=tenant_id, run_id=run_id)
        await session.commit()


def _terminal_transition(previous: DescribeItemStatus, marked: bool) -> bool:
    """Progress is a real non-terminal → terminal mark, not a same-status no-op."""
    return bool(marked) and previous not in TERMINAL_ITEM_STATUSES


def _session_supports_row_lock(session: AsyncSession) -> bool:
    bind = session.get_bind()
    name = getattr(getattr(bind, "dialect", None), "name", "") or ""
    return bool(name) and name != "sqlite"


async def _observed_startup(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    operation_id: str | None,
    for_update: bool = False,
) -> tuple[str | None, float | None]:
    """Reuse the startup bound to this run's operation; never pick a global row.

    ``startup_ms`` is defined only when both start and first-ready UTC
    observations exist. A missing table, missing association, or unobserved
    row stays untimed.
    """
    if not operation_id:
        return None, None
    stmt = select(DescribeOperation).where(
        DescribeOperation.tenant_id == tenant_id,
        DescribeOperation.operation_id == operation_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    try:
        operation = await session.scalar(stmt)
    except (OperationalError, ProgrammingError):
        return None, None
    if operation is None or not operation.startup_id:
        return None, None
    try:
        startup = await session.scalar(
            select(DescribeStartup).where(DescribeStartup.startup_id == operation.startup_id)
        )
    except (OperationalError, ProgrammingError):
        return None, None
    if startup is None:
        return None, None
    startup_ms = None
    if startup.started_at is not None and startup.first_ready_at is not None:
        startup_ms = elapsed_ms(startup.started_at, startup.first_ready_at)
    return startup.startup_id, startup_ms


def _measured_ramp_up_ms(run, *, cold: bool) -> float | None:
    if not cold:
        return 0.0
    if run is None or run.started_at is None or run.first_ready_at is None:
        return None
    return elapsed_ms(run.started_at, run.first_ready_at)


async def _record_run_readiness(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_id: uuid.UUID,
    run_id: uuid.UUID,
    cold: bool,
) -> None:
    async with session_factory() as session:
        await set_tenant_context(session, tenant_id)
        repo = DescribeRunRepository(session)
        run = await repo.get_run(tenant_id=tenant_id, run_id=run_id)
        first_ready_before = None if run is None else run.first_ready_at
        associated_operation_id = None if run is None else run.operation_id
        # Stale snapshot: association may land before the locked re-read below.
        await _observed_startup(session, tenant_id=tenant_id, operation_id=associated_operation_id)
        run = await repo.get_run(tenant_id=tenant_id, run_id=run_id)
        if run is not None:
            associated_operation_id = run.operation_id
            if first_ready_before is None:
                first_ready_before = run.first_ready_at
        observed_id, observed_ms = await _observed_startup(
            session,
            tenant_id=tenant_id,
            operation_id=associated_operation_id,
            for_update=_session_supports_row_lock(session),
        )
        operation_id = associated_operation_id or uuid.uuid4().hex
        startup_id = observed_id if cold else None
        startup_ms = observed_ms if cold else None
        kwargs: dict = {
            "tenant_id": tenant_id,
            "run_id": run_id,
            "operation_id": operation_id,
            "startup_id": startup_id,
            "startup_ms": startup_ms,
        }
        params = inspect.signature(repo.record_readiness).parameters
        if "cold" in params:
            kwargs["cold"] = cold
        if "ramp_up_ms" in params and run is not None and run.started_at is not None:
            now = datetime.now(UTC)
            kwargs["now"] = now
            kwargs["ramp_up_ms"] = elapsed_ms(run.started_at, now) if cold else 0.0
        await repo.record_readiness(**kwargs)
        run = await repo.get_run(tenant_id=tenant_id, run_id=run_id)
        if run is None:
            await session.commit()
            return
        newly_recorded = first_ready_before is None and run.first_ready_at is not None
        if newly_recorded:
            # Repository maps null startup_id → ramp_up_ms=0; restore the measured
            # wait only when this invocation newly recorded first readiness.
            ramp_up_ms = _measured_ramp_up_ms(run, cold=cold)
            if ramp_up_ms is not None:
                run.ramp_up_ms = ramp_up_ms
        if run.startup_id is None and observed_id is not None and (cold or first_ready_before is not None):
            run.startup_id = observed_id
            run.startup_ms = observed_ms
        await session.commit()


async def _record_item_processing_ms(
    *,
    repo: DescribeRunRepository,
    tenant_id: uuid.UUID,
    run_id: uuid.UUID,
    media_id: int,
    processing_ms: float | None,
) -> None:
    if processing_ms is None:
        return
    await repo.record_item_processing(
        tenant_id=tenant_id, run_id=run_id, media_id=media_id, processing_ms=processing_ms
    )


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
        if isinstance(
            current, (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError, httpx.ProxyError)
        ):
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


def _attempt_processing_ms(result: object) -> float | None:
    """Read adapter-dispatch timing; never invent zero for unobserved work."""
    if isinstance(result, DescribeItemOutcome):
        return result.processing_ms
    timing = getattr(result, "attempt_timing", None)
    if timing is not None and getattr(timing, "processing_ms", None) is not None:
        return float(timing.processing_ms)
    value = getattr(result, "processing_ms", None)
    return None if value is None else float(value)


def _adapter_was_dispatched(result: object) -> bool:
    timing = getattr(result, "attempt_timing", None)
    if timing is not None and bool(getattr(timing, "entered_adapter", False)):
        return True
    return bool(getattr(result, "entered_adapter", False))


def _sum_processing_ms(values: list[float | None]) -> float | None:
    measured = [value for value in values if value is not None]
    if not measured:
        return None
    return float(sum(measured))


async def _describe_with_transient_retry(
    *,
    describe_one: DescribeOne,
    media_id: int,
    image_bytes: bytes | None,
    content_type: str | None,
    timeout_seconds: float,
    retry_transient: bool,
    cancel_requested: Callable[[], Awaitable[bool]] | None = None,
    naming_inputs: FusionNamingInputs | None = None,
) -> DescribeItemOutcome | None:
    max_attempts = _GPU_ITEM_MAX_ATTEMPTS if retry_transient else 1
    measured: list[float | None] = []

    def _cancel_error(message: str) -> _RunCancelledError:
        return _RunCancelledError(message, processing_ms=_sum_processing_ms(measured))

    def _dispatch_elapsed_ms(started: float) -> float:
        return max(0.0, (time.monotonic() - started) * 1000.0)

    def _measured_attempt_ms(result: object, started: float) -> float | None:
        attempt_ms = _attempt_processing_ms(result)
        if attempt_ms is not None:
            return attempt_ms
        if _adapter_was_dispatched(result):
            return _dispatch_elapsed_ms(started)
        return None

    for attempt in range(1, max_attempts + 1):
        if cancel_requested is not None and await cancel_requested():
            raise _cancel_error("describe run cancelled before item retry")
        started = time.monotonic()
        try:
            outcome = await asyncio.wait_for(
                _call_describe_one(describe_one, media_id, image_bytes, content_type, naming_inputs=naming_inputs),
                timeout_seconds,
            )
            measured.append(_measured_attempt_ms(outcome, started))
            total = _sum_processing_ms(measured)
            if outcome is None:
                return None if total is None else DescribeItemOutcome(processing_ms=total)
            if total is not None and outcome.processing_ms != total:
                return replace(outcome, processing_ms=total)
            return outcome
        except _RunCancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - classify before retrying
            measured.append(_measured_attempt_ms(exc, started))
            total = _sum_processing_ms(measured)
            if total is not None:
                exc.processing_ms = total  # type: ignore[attr-defined]
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
                if cancel_requested is not None and await cancel_requested():
                    raise _cancel_error("describe run cancelled during item retry backoff")
    raise RuntimeError("unreachable")  # pragma: no cover


async def _naming_lookup_for_item(
    *,
    enabled: bool,
    session_factory: async_sessionmaker[AsyncSession],
    tenant,
    tenant_id: uuid.UUID,
    media_id: int,
    image_bytes: bytes | None,
) -> FusionNamingInputs | Literal[_NamingBudget.EXCEEDED] | None:
    """Load faces/policy independently of describe I/O; never raises to the run."""
    if not enabled or tenant is None or not image_bytes:
        return None
    try:
        async with session_factory() as naming_session:
            await set_tenant_context(naming_session, tenant_id)
            loaded = await asyncio.wait_for(
                load_fusion_naming_inputs(
                    session=naming_session,
                    tenant=tenant,
                    tenant_uuid=tenant_id,
                    media_id=media_id,
                    image_bytes=image_bytes,
                ),
                timeout=NAMING_BUDGET_SECONDS,
            )
            return FusionNamingInputs(*loaded)
    except TimeoutError:
        logger.warning("naming budget exceeded during lookup media_id=%s; continuing without names", media_id)
        return _NAMING_BUDGET_EXCEEDED
    except Exception:  # noqa: BLE001 - naming lookup must not fail the item
        logger.exception("naming lookup failed media_id=%s; describing without names", media_id)
        return None


def _naming_provenance_payload(
    provenance,
    *,
    status: NamingStatus | None = None,
    realizer: NamingRealizer | None = None,
    names_applied: list[str] | None = None,
) -> dict:
    """Return the additive C7 naming payload while retaining legacy fields."""
    dump = getattr(provenance, "model_dump", None)
    if callable(dump):
        payload = dump()
    elif isinstance(provenance, dict):
        payload = dict(provenance)
    else:
        payload = {}

    if not isinstance(payload, dict):
        payload = {}
    injected_names = payload.get("injected_names") or []
    if names_applied is None:
        names_applied = payload.get("names_applied")
    if names_applied is None:
        names_applied = [
            name for item in injected_names if isinstance(item, dict) and isinstance(name := item.get("name"), str)
        ]
    names_applied = list(names_applied)

    existing_status = payload.get("status")
    if status is None:
        status = existing_status or (NamingStatus.APPLIED if names_applied else NamingStatus.NO_FACES)
    status_value = getattr(status, "value", status)
    payload["status"] = status_value

    existing_realizer = payload.get("realizer")
    if realizer is None:
        realizer = existing_realizer
    if realizer is None:
        mode = payload.get("mode")
        if mode == "grounded":
            realizer = NamingRealizer.GROUNDED
        elif mode == "positional":
            realizer = NamingRealizer.POSITIONAL_FALLBACK
    payload["realizer"] = getattr(realizer, "value", realizer) if realizer is not None else None
    payload["names_applied"] = names_applied
    return payload


async def _apply_naming_preview(
    *,
    enabled: bool,
    session: AsyncSession,
    tenant,
    tenant_id: uuid.UUID,
    media_id: int,
    image_bytes: bytes | None,
    outcome: DescribeItemOutcome,
    naming_inputs: FusionNamingInputs | Literal[_NamingBudget.EXCEEDED] | None,
    item_started: float,
    item_envelope: float,
    naming_budget_exceeded: bool = False,
) -> DescribeItemOutcome:
    """Fuse names into alt_text_draft (the same generic_draft field the router uses).

    Preview wait_for is ``min(NAMING_BUDGET_SECONDS, remaining_envelope)``. Remaining
    <= 0 skips preview and keeps the generic draft (same path as a lookup timeout).
    """

    def with_naming_payload(payload: dict) -> DescribeItemOutcome:
        merged = dict(outcome.provenance or {})
        merged["naming"] = payload
        return replace(outcome, provenance=merged)

    if naming_budget_exceeded:
        logger.warning("naming budget exceeded media_id=%s; keeping generic draft", media_id)
        return with_naming_payload(_naming_provenance_payload(None, status=NamingStatus.SKIPPED_BUDGET))
    if not enabled:
        return with_naming_payload(_naming_provenance_payload(None, status=NamingStatus.DISABLED))
    if tenant is None or not image_bytes or naming_inputs is None or naming_inputs is _NAMING_BUDGET_EXCEEDED:
        return with_naming_payload(_naming_provenance_payload(None, status=NamingStatus.NO_FACES))
    faces, policy = naming_inputs
    if policy is None:
        return with_naming_payload(_naming_provenance_payload(None, status=NamingStatus.NO_FACES))
    remaining = item_envelope - (time.monotonic() - item_started)
    if remaining <= 0:
        logger.warning("naming budget exceeded before preview media_id=%s; keeping generic draft", media_id)
        return with_naming_payload(_naming_provenance_payload(None, status=NamingStatus.SKIPPED_BUDGET))
    preview_timeout = min(NAMING_BUDGET_SECONDS, remaining)
    try:
        phrase_boxes = outcome.phrase_boxes or ()
        preview_faces = faces_for_naming_preview(faces or [], outcome.attachments or (), phrase_boxes)
        named, provenance = await asyncio.wait_for(
            naming_preview(
                session=session,
                tenant=tenant,
                tenant_uuid=tenant_id,
                media_id=media_id,
                image_bytes=image_bytes,
                generic_draft=outcome.alt_text_draft or "",
                phrase_boxes=phrase_boxes,
                confirmed_faces=preview_faces if faces is not None else None,
                naming_policy=policy,
            ),
            timeout=preview_timeout,
        )
        payload = _naming_provenance_payload(provenance)
        return replace(
            outcome,
            alt_text_draft=named,
            provenance={**dict(outcome.provenance or {}), "naming": payload},
        )
    except TimeoutError:
        logger.warning("naming budget exceeded during preview media_id=%s; keeping generic draft", media_id)
        return with_naming_payload(_naming_provenance_payload(None, status=NamingStatus.SKIPPED_BUDGET))
    except Exception:  # noqa: BLE001 - a naming fault must not fail the described item
        logger.exception("naming preview failed media_id=%s; continuing without names", media_id)
        return with_naming_payload(_naming_provenance_payload(None, status=NamingStatus.NO_FACES))


async def run_describe_job(
    *,
    tenant_id: uuid.UUID,
    run_id: uuid.UUID,
    session_factory: async_sessionmaker[AsyncSession],
    describe_one: DescribeOne,
    timeout_seconds: float | None = None,
    gpu_policy: GpuRunPolicy | None = None,
    cpu_describe_one: DescribeOne | UnavailableDescriptionAdapter | None = None,
) -> None:
    """Process a describe run item-by-item.

    Per item: load its image bytes, load one naming snapshot (DATA-19), run
    ``describe_one``, persist the draft / caption / provenance, clear the stored
    bytes, and mark it COMPLETED. PERF-10 traded for DATA-19 (WBUX-6 S9-F1):
    the per-item envelope is ``item_envelope_seconds`` (naming budget + describe
    timeout, the sum not the max). Stage-3 preview runs inside that envelope
    (S9R2-F1): its wait_for is the remaining budget, not a second naming cap.
    Per-item failures are isolated (item -> FAILED, run continues); an unexpected
    fatal error around the whole loop forces the run terminal-FAILED.
    (S2-01, S2-02, HARM-01)

    A GPU warmup ``TimeoutError`` never fails the run silently: a usable CPU
    adapter continues the run with ``tier=cpu_fallback`` and
    ``reason=gpu_warmup_timeout``; otherwise the run ends FAILED with a typed
    retryable terminal detail (C2 / RES-13).
    """

    timeout = timeout_seconds if timeout_seconds is not None else VlmSettings().inference_timeout_seconds
    item_envelope = item_envelope_seconds(timeout)
    logger.debug(
        "describe run per-item envelope seconds=%s (PERF-10 traded for DATA-19 WBUX-6 S9-F1)",
        item_envelope,
    )

    async def cancel_requested() -> bool:
        # A fresh, short-lived session is intentional. The tracking session has
        # expire_on_commit=False and may otherwise keep an identity-mapped run
        # with cancel_requested=False after DELETE commits in another session.
        async with session_factory() as cancel_session:
            await set_tenant_context(cancel_session, tenant_id)
            run = await DescribeRunRepository(cancel_session).get_run(tenant_id=tenant_id, run_id=run_id)
            return run is None or bool(run.cancel_requested)

    warmup_fallback_tier: DescriptionFallbackTier | None = None
    warmup_fallback_reason: DescribeRunTerminalReason | None = None
    try:
        await _record_run_pickup(session_factory=session_factory, tenant_id=tenant_id, run_id=run_id)
        if gpu_policy is not None:
            await _persist_run_phase(
                session_factory=session_factory,
                tenant_id=tenant_id,
                run_id=run_id,
                phase=DescribeRunPhase.WARMING,
            )
            try:
                immediately_ready = await _wait_for_gpu_ready(
                    endpoint_url=gpu_policy.endpoint_url,
                    api_key=gpu_policy.api_key,
                    timeout_seconds=gpu_policy.warmup_timeout_seconds,
                    cancel_requested=cancel_requested,
                )
            except TimeoutError as warmup_timeout:
                cpu_one = _usable_cpu_describe_one(cpu_describe_one)
                if cpu_one is None:
                    await _fail_run_on_gpu_warmup_timeout(
                        session_factory=session_factory,
                        tenant_id=tenant_id,
                        run_id=run_id,
                        timeout_seconds=gpu_policy.warmup_timeout_seconds,
                        error=warmup_timeout,
                    )
                    return
                logger.warning(
                    "GPU warmup timed out run_id=%s budget_seconds=%s; continuing on CPU adapter",
                    run_id,
                    gpu_policy.warmup_timeout_seconds,
                )
                describe_one = cpu_one
                gpu_policy = None
                warmup_fallback_tier = DescriptionFallbackTier.CPU_FALLBACK
                warmup_fallback_reason = DescribeRunTerminalReason.GPU_WARMUP_TIMEOUT
                immediately_ready = False
            await _persist_run_phase(
                session_factory=session_factory,
                tenant_id=tenant_id,
                run_id=run_id,
                phase=DescribeRunPhase.DESCRIBING,
            )
            await _record_run_readiness(
                session_factory=session_factory,
                tenant_id=tenant_id,
                run_id=run_id,
                cold=not immediately_ready,
            )
        else:
            await _record_run_readiness(
                session_factory=session_factory,
                tenant_id=tenant_id,
                run_id=run_id,
                cold=False,
            )
        async with session_factory() as session:
            # RLS: every session touching the tenant-scoped run/item tables must
            # set app.current_tenant, else FORCE RLS on Postgres returns zero rows.
            await set_tenant_context(session, tenant_id)
            repo = DescribeRunRepository(session)
            tenant = await get_tenant_record(session, tenant_id)
            run = await repo.get_run(tenant_id=tenant_id, run_id=run_id)
            naming_enabled = bool(tenant and tenant.naming_agreement_enabled and run and run.recognition_enabled)
            items = await repo.list_run_items(tenant_id=tenant_id, run_id=run_id)
            gpu_breaker_error: str | None = None
            no_progress = 0
            for item in items:
                previous_status = DescribeItemStatus(item.status)
                progressed = False
                if await cancel_requested():
                    marked = await repo.mark_item(
                        tenant_id=tenant_id,
                        run_id=run_id,
                        media_id=item.media_id,
                        status=DescribeItemStatus.SKIPPED,
                    )
                    progressed = _terminal_transition(previous_status, marked)
                    await session.commit()
                else:
                    image_bytes = item.image_bytes
                    content_type = item.image_content_type
                    await repo.mark_item(
                        tenant_id=tenant_id,
                        run_id=run_id,
                        media_id=item.media_id,
                        status=DescribeItemStatus.RUNNING,
                    )
                    processing_ms: float | None = None
                    try:
                        if gpu_breaker_error is not None:
                            raise _GpuCircuitOpenError(gpu_breaker_error)
                        # HARM-F3 / DATA-19: one naming snapshot per item. Load first,
                        # then share with Stage-2 fusion and Stage-3 preview so a
                        # label/merge between two sessions cannot diverge the draft.
                        # PERF-10 traded for DATA-19 (WBUX-6 S9-F1): serial envelope
                        # is item_envelope_seconds(timeout), not max(naming, describe).
                        # S9R2-F1: Stage-3 preview is charged against remaining envelope.
                        item_started = time.monotonic()
                        naming_inputs = await _naming_lookup_for_item(
                            enabled=naming_enabled,
                            session_factory=session_factory,
                            tenant=tenant,
                            tenant_id=tenant_id,
                            media_id=item.media_id,
                            image_bytes=image_bytes,
                        )
                        naming_budget_exceeded = naming_inputs is _NAMING_BUDGET_EXCEEDED
                        if naming_inputs is not None and naming_inputs is not _NAMING_BUDGET_EXCEEDED:
                            describe_naming_inputs: FusionNamingInputs | None = naming_inputs
                        elif run is not None and run.recognition_enabled:
                            describe_naming_inputs = EMPTY_NAMING_INPUTS
                        else:
                            describe_naming_inputs = None
                        outcome = await _describe_with_transient_retry(
                            describe_one=describe_one,
                            media_id=item.media_id,
                            image_bytes=image_bytes,
                            content_type=content_type,
                            timeout_seconds=timeout,
                            retry_transient=gpu_policy is not None,
                            cancel_requested=cancel_requested,
                            naming_inputs=describe_naming_inputs,
                        )
                        processing_ms = None if outcome is None else outcome.processing_ms
                        outcome = await _apply_naming_preview(
                            enabled=naming_enabled,
                            session=session,
                            tenant=tenant,
                            tenant_id=tenant_id,
                            media_id=item.media_id,
                            image_bytes=image_bytes,
                            outcome=outcome or DescribeItemOutcome(),
                            naming_inputs=naming_inputs,
                            item_started=item_started,
                            item_envelope=item_envelope,
                            naming_budget_exceeded=naming_budget_exceeded,
                        )
                    except _RunCancelledError as exc:
                        processing_ms = getattr(exc, "processing_ms", processing_ms)
                        await _record_item_processing_ms(
                            repo=repo,
                            tenant_id=tenant_id,
                            run_id=run_id,
                            media_id=item.media_id,
                            processing_ms=processing_ms,
                        )
                        marked = await repo.mark_item(
                            tenant_id=tenant_id,
                            run_id=run_id,
                            media_id=item.media_id,
                            status=DescribeItemStatus.SKIPPED,
                        )
                        progressed = _terminal_transition(previous_status, marked)
                    except Exception as exc:  # noqa: BLE001 - per-item failure must not abort the run
                        logger.warning(
                            "describe run item failed run_id=%s media_id=%s", run_id, item.media_id, exc_info=True
                        )
                        processing_ms = getattr(exc, "processing_ms", processing_ms)
                        await _record_item_processing_ms(
                            repo=repo,
                            tenant_id=tenant_id,
                            run_id=run_id,
                            media_id=item.media_id,
                            processing_ms=processing_ms,
                        )
                        await repo.record_item_result(
                            tenant_id=tenant_id,
                            run_id=run_id,
                            media_id=item.media_id,
                            alt_text_draft=None,
                            caption=None,
                            provenance=None,
                        )
                        marked = await repo.mark_item(
                            tenant_id=tenant_id,
                            run_id=run_id,
                            media_id=item.media_id,
                            status=DescribeItemStatus.FAILED,
                            error_message=str(exc),
                        )
                        progressed = _terminal_transition(previous_status, marked)
                        if gpu_policy is not None and _is_transient_describe_error(exc):
                            gpu_breaker_error = (
                                f"GPU circuit open after transient retries were exhausted: {type(exc).__name__}: {exc}"
                            )
                    else:
                        outcome = outcome or DescribeItemOutcome()
                        if warmup_fallback_reason is not None:
                            outcome = replace(
                                outcome,
                                tier=warmup_fallback_tier,
                                provenance={
                                    **dict(outcome.provenance or {}),
                                    "tier": warmup_fallback_tier,
                                    "reason": warmup_fallback_reason,
                                },
                            )
                        await _record_item_processing_ms(
                            repo=repo,
                            tenant_id=tenant_id,
                            run_id=run_id,
                            media_id=item.media_id,
                            processing_ms=processing_ms if processing_ms is not None else outcome.processing_ms,
                        )
                        await repo.record_item_result(
                            tenant_id=tenant_id,
                            run_id=run_id,
                            media_id=item.media_id,
                            alt_text_draft=outcome.alt_text_draft,
                            caption=outcome.caption,
                            provenance=outcome.provenance or None,
                            tier=_persistable_item_tier(outcome.tier),
                        )
                        if warmup_fallback_tier is not None and item.tier != warmup_fallback_tier:
                            item.tier = warmup_fallback_tier
                        marked = await repo.mark_item(
                            tenant_id=tenant_id,
                            run_id=run_id,
                            media_id=item.media_id,
                            status=DescribeItemStatus.COMPLETED,
                        )
                        progressed = _terminal_transition(previous_status, marked)
                    await session.commit()
                if progressed:
                    no_progress = 0
                    continue
                no_progress += 1
                if no_progress >= _ITEM_NO_PROGRESS_LIMIT:
                    logger.error(
                        "describe run stalled run_id=%s after %s items without progress",
                        run_id,
                        no_progress,
                    )
                    await repo.mark_run_failed(
                        tenant_id=tenant_id,
                        run_id=run_id,
                        error_message="describe run stalled: no item progress",
                    )
                    await session.commit()
                    break
            if warmup_fallback_reason is not None:
                run = await repo.get_run(tenant_id=tenant_id, run_id=run_id)
                if run is not None and DescribeRunStatus(run.status) in {
                    DescribeRunStatus.COMPLETED,
                    DescribeRunStatus.COMPLETED_WITH_ERRORS,
                }:
                    run.error_message = _cpu_fallback_run_stamp()
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
        await publish_demand_snapshot(session_factory)
