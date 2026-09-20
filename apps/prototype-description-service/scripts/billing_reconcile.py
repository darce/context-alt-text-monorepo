"""Bounded reconciliation of the verified billing webhook inbox.

The command is deliberately a composition seam: the database repository and
provider are injected by the caller.  This keeps vendor transport, credentials,
and application startup out of the worker while making the retry and timeout
policy testable without a network.

Usage:
    python -m scripts.billing_reconcile --once --batch-size 100
    python -m scripts.billing_reconcile --loop --max-cycles 2

The standalone command validates its numeric configuration and reports that an
injected repository/provider are required.  Runtime wiring belongs to the
application composition root in a later wave.
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import logging
import math
import os
import random
import sys
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, cast
from uuid import UUID

from sqlalchemy import select

from db.models import BillingWebhookInbox
from recognition.domain.portal_contracts import (
    BillingProvider,
    BillingSubscriptionStatus,
    WebhookInboxStatus,
)

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 100
MAX_BATCH_SIZE = 1000
DEFAULT_PROVIDER_TIMEOUT_SECONDS = 10.0
DEFAULT_RETRY_ATTEMPTS = 3
DEFAULT_RETRY_INITIAL_DELAY_SECONDS = 0.25
DEFAULT_RETRY_MAX_DELAY_SECONDS = 5.0
DEFAULT_RETRY_JITTER_SECONDS = 0.25
DEFAULT_STALL_LIMIT = 3
DEFAULT_POLL_INTERVAL_SECONDS = 900.0

_PENDING_STATUSES = frozenset(
    {
        WebhookInboxStatus.RECEIVED.value,
        WebhookInboxStatus.FAILED.value,
    }
)
_PROVIDER_METHOD_NAMES = (
    "retrieve_state",
    "retrieve_billing_state",
    "retrieve_customer_state",
    "retrieve_subscription_state",
    "get_authoritative_state",
    "get_billing_state",
    "get_customer_state",
    "get_subscription_state",
    "get_state",
    "fetch_billing_state",
    "fetch_state",
)
_CUSTOMER_PARAMETER_NAMES = (
    "provider_customer_id",
    "customer_id",
    "customer",
    "external_customer_id",
)
_SUBSCRIPTION_PARAMETER_NAMES = (
    "provider_subscription_id",
    "subscription_id",
)
_TIMEOUT_PARAMETER_NAMES = ("timeout", "request_timeout", "timeout_seconds", "timeout_s")


class ConfigurationError(ValueError):
    """Raised when worker configuration is missing or structurally invalid."""


class ReconciliationError(RuntimeError):
    """Raised when an inbox row cannot be reconciled safely."""


class ProviderUnavailableError(ReconciliationError):
    """Raised after the provider retry budget is exhausted."""


class UnsupportedWebhookError(ReconciliationError):
    """Raised for a valid inbox event with no safe reconciliation target."""


ProviderUnavailable = ProviderUnavailableError
UnsupportedWebhook = UnsupportedWebhookError


class BillingRepositoryLike(Protocol):
    async def list_pending_webhooks(self, *, limit: int) -> Sequence[object]:
        ...

    async def get_projection(self, tenant_id: UUID, *, provider: str | None = None) -> object | None:
        ...

    async def upsert_projection(self, **kwargs: object) -> bool:
        ...

    async def mark_webhook_processed(
        self,
        *,
        provider: str,
        provider_event_id: str,
        status: WebhookInboxStatus,
        processed_at: datetime | None = None,
    ) -> bool:
        ...


class ReconciliationProvider(BillingProvider, Protocol):
    """The injected provider seam used by the reconciliation worker.

    The canonical portal protocol intentionally remains small.  The provider
    supplied to this worker additionally exposes one of the retrieval method
    names in ``_PROVIDER_METHOD_NAMES``; each method receives an explicit
    timeout when its signature accepts one, and is also wrapped in
    ``asyncio.wait_for``.
    """

    async def retrieve_state(
        self,
        *,
        provider_customer_id: str,
        provider_subscription_id: str | None,
        request_timeout: float,
    ) -> object:
        ...


@dataclass(frozen=True, slots=True)
class ReconcileConfig:
    """Validated timeout, retry, polling, and stall policy."""

    provider_timeout_s: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS
    retry_attempts: int = DEFAULT_RETRY_ATTEMPTS
    retry_initial_delay_s: float = DEFAULT_RETRY_INITIAL_DELAY_SECONDS
    retry_max_delay_s: float = DEFAULT_RETRY_MAX_DELAY_SECONDS
    retry_jitter_s: float = DEFAULT_RETRY_JITTER_SECONDS
    stall_limit: int = DEFAULT_STALL_LIMIT
    poll_interval_s: float = DEFAULT_POLL_INTERVAL_SECONDS

    def __post_init__(self) -> None:
        _positive_finite("provider_timeout_s", self.provider_timeout_s)
        _bounded_int("retry_attempts", self.retry_attempts, minimum=1, maximum=10)
        _non_negative_finite("retry_initial_delay_s", self.retry_initial_delay_s)
        _positive_finite("retry_max_delay_s", self.retry_max_delay_s)
        if self.retry_initial_delay_s > self.retry_max_delay_s:
            raise ConfigurationError("retry_initial_delay_s must not exceed retry_max_delay_s")
        _non_negative_finite("retry_jitter_s", self.retry_jitter_s)
        _bounded_int("stall_limit", self.stall_limit, minimum=1, maximum=100)
        _non_negative_finite("poll_interval_s", self.poll_interval_s)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> ReconcileConfig:
        """Load numerically typed settings and fail closed on bad input.

        The provider timeout is required for a standalone deployment.  The
        remaining controls have explicit, bounded defaults rather than an empty
        or silently disabled value.
        """

        values = os.environ if environ is None else environ
        timeout_raw = values.get("BILLING_RECONCILE_PROVIDER_TIMEOUT_SECONDS")
        if timeout_raw is None or not timeout_raw.strip():
            raise ConfigurationError(
                "missing required configuration BILLING_RECONCILE_PROVIDER_TIMEOUT_SECONDS"
            )
        return cls(
            provider_timeout_s=_parse_float_env(
                "BILLING_RECONCILE_PROVIDER_TIMEOUT_SECONDS", timeout_raw
            ),
            retry_attempts=_parse_int_env(
                "BILLING_RECONCILE_RETRY_ATTEMPTS",
                values.get("BILLING_RECONCILE_RETRY_ATTEMPTS", str(DEFAULT_RETRY_ATTEMPTS)),
            ),
            retry_initial_delay_s=_parse_float_env(
                "BILLING_RECONCILE_RETRY_INITIAL_DELAY_SECONDS",
                values.get(
                    "BILLING_RECONCILE_RETRY_INITIAL_DELAY_SECONDS",
                    str(DEFAULT_RETRY_INITIAL_DELAY_SECONDS),
                ),
            ),
            retry_max_delay_s=_parse_float_env(
                "BILLING_RECONCILE_RETRY_MAX_DELAY_SECONDS",
                values.get("BILLING_RECONCILE_RETRY_MAX_DELAY_SECONDS", str(DEFAULT_RETRY_MAX_DELAY_SECONDS)),
            ),
            retry_jitter_s=_parse_float_env(
                "BILLING_RECONCILE_RETRY_JITTER_SECONDS",
                values.get("BILLING_RECONCILE_RETRY_JITTER_SECONDS", str(DEFAULT_RETRY_JITTER_SECONDS)),
            ),
            stall_limit=_parse_int_env(
                "BILLING_RECONCILE_STALL_LIMIT",
                values.get("BILLING_RECONCILE_STALL_LIMIT", str(DEFAULT_STALL_LIMIT)),
            ),
            poll_interval_s=_parse_float_env(
                "BILLING_RECONCILE_POLL_INTERVAL_SECONDS",
                values.get("BILLING_RECONCILE_POLL_INTERVAL_SECONDS", str(DEFAULT_POLL_INTERVAL_SECONDS)),
            ),
        )


@dataclass(frozen=True, slots=True)
class AuthoritativeBillingState:
    """Normalized provider state accepted by the projection repository."""

    tenant_id: UUID
    provider_customer_id: str
    provider_subscription_id: str | None
    status: BillingSubscriptionStatus
    current_period_end: datetime | None
    past_due_since: datetime | None
    event_position: datetime


@dataclass(frozen=True, slots=True)
class DryRunChange:
    """One read-only action reported by ``--dry-run``."""

    inbox_row_id: str
    provider_event_id: str
    tenant_id: str | None
    action: str


@dataclass(slots=True)
class ReconcileReport:
    """Counters and dry-run actions produced by one worker invocation."""

    cycles: int = 0
    processed: int = 0
    ignored: int = 0
    failed: int = 0
    changed: int = 0
    stale: int = 0
    duplicates: int = 0
    would_change: int = 0
    stalled: bool = False
    unresolved_failures: int = 0
    changes: list[DryRunChange] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        return 1 if self.stalled or self.unresolved_failures else 0


@dataclass(frozen=True, slots=True)
class _EventContext:
    tenant_id: UUID
    provider_customer_id: str
    provider_subscription_id: str | None


@dataclass(frozen=True, slots=True)
class _RowOutcome:
    progressed: bool = False
    failed: bool = False
    changed: bool = False
    ignored: bool = False
    stale: bool = False
    duplicate: bool = False
    dry_run_change: DryRunChange | None = None


class BillingReconciliationWorker:
    """Drain pending inbox rows with bounded provider work and isolated failures."""

    def __init__(
        self,
        repository: BillingRepositoryLike,
        provider: ReconciliationProvider,
        *,
        config: ReconcileConfig | None = None,
        clock: Callable[[], datetime] | None = None,
        sleeper: Callable[[float], Awaitable[object]] = asyncio.sleep,
        random_value: Callable[[], float] = random.random,
        log: logging.Logger | None = None,
    ) -> None:
        self._repository = repository
        self._provider = provider
        self._config = config or ReconcileConfig()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._sleeper = sleeper
        self._random_value = random_value
        self._logger = log or logger

    async def run(
        self,
        *,
        loop: bool = False,
        max_cycles: int | None = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
        dry_run: bool = False,
    ) -> ReconcileReport:
        """Run one cycle or a bounded/unbounded polling loop."""

        batch_size = validate_batch_size(batch_size)
        if isinstance(max_cycles, bool) or (
            max_cycles is not None and (not isinstance(max_cycles, int) or max_cycles <= 0)
        ):
            raise ValueError("max_cycles must be a positive integer when provided")
        if not loop and max_cycles not in (None, 1):
            raise ValueError("max_cycles is only valid with loop mode")

        report = ReconcileReport()
        no_progress: dict[str, int] = {}
        unresolved: set[str] = set()
        cycle_limit = max_cycles if loop else 1

        while cycle_limit is None or report.cycles < cycle_limit:
            report.cycles += 1
            try:
                rows = await _maybe_await(self._repository.list_pending_webhooks(limit=batch_size))
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                unresolved.add("list_pending_webhooks")
                report.failed += 1
                self._logger.error(
                    "billing_reconcile cycle_failed operation=list_pending_webhooks error_type=%s",
                    type(exc).__name__,
                )
                break

            bounded_rows = list(rows)[:batch_size]
            cycle_stalled = False
            for row in bounded_rows:
                row_key = _row_key(row)
                outcome = await self._process_row(row, dry_run=dry_run)
                if outcome.failed:
                    report.failed += 1
                    unresolved.add(row_key)
                    no_progress[row_key] = no_progress.get(row_key, 0) + 1
                    if no_progress[row_key] >= self._config.stall_limit:
                        cycle_stalled = True
                        self._logger.error(
                            "billing_reconcile row_stalled inbox_row_id=%s provider_event_id=%s threshold=%s",
                            _safe_log_id(row, "id"),
                            _safe_log_id(row, "provider_event_id"),
                            self._config.stall_limit,
                        )
                elif outcome.progressed:
                    no_progress.pop(row_key, None)
                    unresolved.discard(row_key)

                report.processed += int(outcome.progressed and not outcome.ignored and not dry_run)
                report.ignored += int(outcome.ignored and not dry_run)
                report.changed += int(outcome.changed)
                report.stale += int(outcome.stale)
                report.duplicates += int(outcome.duplicate)
                if outcome.dry_run_change is not None:
                    report.changes.append(outcome.dry_run_change)
                    report.would_change += int(outcome.dry_run_change.action in {"create_projection", "update_projection"})

            if cycle_stalled:
                report.stalled = True
                break
            if not loop or (cycle_limit is not None and report.cycles >= cycle_limit):
                break
            await _maybe_await(self._sleeper(self._config.poll_interval_s))

        report.unresolved_failures = len(unresolved)
        return report

    async def run_once(
        self,
        *,
        batch_size: int = DEFAULT_BATCH_SIZE,
        dry_run: bool = False,
    ) -> ReconcileReport:
        """Run one cycle without enabling loop-specific behavior."""

        return await self.run(batch_size=batch_size, dry_run=dry_run)

    async def _process_row(self, row: object, *, dry_run: bool) -> _RowOutcome:
        provider_name = _safe_log_id(row, "provider")
        provider_event_id = _safe_log_id(row, "provider_event_id")
        inbox_row_id = _safe_log_id(row, "id")
        try:
            claimed = await self._claim_row(row)
            if claimed is None:
                return _RowOutcome()
            row = claimed
            provider_name = _required_text(_row_value(row, "provider"), "provider")
            provider_event_id = _required_text(_row_value(row, "provider_event_id"), "provider_event_id")
            inbox_row_id = _safe_log_id(row, "id")

            payload = _row_value(row, "payload")
            event_type = _required_text(_row_value(row, "event_type"), "event_type")
            if not isinstance(payload, Mapping):
                raise ReconciliationError("inbox payload must be an object")

            context, projection = await self._context_and_projection(
                payload,
                provider=provider_name,
                event_type=event_type,
            )
            if projection is not None and _same_event(projection, provider_event_id):
                change = DryRunChange(
                    inbox_row_id=inbox_row_id,
                    provider_event_id=provider_event_id,
                    tenant_id=str(context.tenant_id),
                    action="skip_duplicate",
                )
                if dry_run:
                    self._log_row(row, "dry_run", action=change.action)
                    await self._rollback()
                    return _RowOutcome(progressed=True, duplicate=True, dry_run_change=change)
                await self._mark(row, status=WebhookInboxStatus.PROCESSED)
                self._log_row(row, "processed", action=change.action)
                return _RowOutcome(progressed=True, duplicate=True)

            state = await self._retrieve_state(context)
            if state.tenant_id != context.tenant_id:
                raise ReconciliationError("provider state tenant does not match inbox tenant")

            action = _projection_action(projection, state, provider_event_id, provider_name)
            change = DryRunChange(
                inbox_row_id=inbox_row_id,
                provider_event_id=provider_event_id,
                tenant_id=str(state.tenant_id),
                action=action,
            )
            if dry_run:
                self._log_row(row, "dry_run", action=action)
                await self._rollback()
                return _RowOutcome(
                    progressed=True,
                    changed=action in {"create_projection", "update_projection"},
                    stale=action == "skip_stale",
                    duplicate=action == "skip_duplicate",
                    dry_run_change=change,
                )

            if action == "skip_stale":
                await self._mark(row, status=WebhookInboxStatus.PROCESSED)
                self._log_row(row, "processed", action=action)
                return _RowOutcome(progressed=True, stale=True)

            changed = await _maybe_await(
                self._repository.upsert_projection(
                    tenant_id=state.tenant_id,
                    provider=provider_name,
                    provider_customer_id=state.provider_customer_id,
                    provider_subscription_id=state.provider_subscription_id,
                    status=state.status,
                    current_period_end=state.current_period_end,
                    past_due_since=state.past_due_since,
                    provider_event_id=provider_event_id,
                    event_position=state.event_position,
                )
            )
            await self._mark(row, status=WebhookInboxStatus.PROCESSED)
            self._log_row(row, "processed", action="update_projection" if changed else "skip_stale")
            return _RowOutcome(
                progressed=True,
                changed=bool(changed),
                stale=not changed,
            )
        except asyncio.CancelledError:
            raise
        except UnsupportedWebhook:
            if dry_run:
                change = DryRunChange(
                    inbox_row_id=inbox_row_id,
                    provider_event_id=provider_event_id,
                    tenant_id=None,
                    action="ignore_unknown",
                )
                await self._rollback()
                self._log_row(row, "dry_run", action=change.action)
                return _RowOutcome(progressed=True, ignored=True, dry_run_change=change)
            try:
                await self._mark(row, status=WebhookInboxStatus.DISCARDED)
            except Exception as exc:  # noqa: BLE001
                await self._rollback()
                self._log_failure(row, "discard_failed", exc)
                return _RowOutcome(failed=True)
            self._log_row(row, "discarded", action="ignore_unknown")
            return _RowOutcome(progressed=True, ignored=True)
        except ProviderUnavailable as exc:
            await self._mark_failure(row, exc)
            return _RowOutcome(failed=True)
        except Exception as exc:  # noqa: BLE001
            await self._mark_failure(row, exc)
            return _RowOutcome(failed=True)

    async def _context_and_projection(
        self,
        payload: Mapping[str, object],
        *,
        provider: str,
        event_type: str,
    ) -> tuple[_EventContext, object | None]:
        data_value = payload.get("data")
        data: Mapping[str, object]
        if isinstance(data_value, Mapping):
            data = data_value
        else:
            data = payload

        metadata_value = data.get("metadata")
        metadata = metadata_value if isinstance(metadata_value, Mapping) else {}
        tenant_value = _first_value(
            payload.get("tenant_id"),
            data.get("tenant_id"),
            metadata.get("tenant_id"),
        )
        if tenant_value is None:
            raise UnsupportedWebhook(f"event {event_type} has no tenant reference")
        tenant_id = _parse_uuid(tenant_value, "tenant_id")
        projection = await self._get_projection(tenant_id, provider)

        customer_value = _first_value(
            data.get("provider_customer_id"),
            data.get("customer_id"),
            data.get("external_customer_id"),
            _nested_value(data.get("customer"), "id"),
            metadata.get("provider_customer_id"),
            metadata.get("customer_id"),
            _projection_value(projection, "provider_customer_id"),
        )
        if not isinstance(customer_value, str) or not customer_value:
            raise UnsupportedWebhook(f"event {event_type} has no provider customer reference")

        subscription_value = _first_value(
            data.get("provider_subscription_id"),
            data.get("subscription_id"),
            data.get("id") if data.get("type") != "customer" else None,
            _nested_value(data.get("subscription"), "id"),
            _projection_value(projection, "provider_subscription_id"),
        )
        if subscription_value is not None and not isinstance(subscription_value, str):
            raise ReconciliationError("provider subscription id must be a string")
        return _EventContext(tenant_id, customer_value, subscription_value), projection

    async def _get_projection(self, tenant_id: UUID, provider: str) -> object | None:
        method = getattr(self._repository, "get_projection", None)
        if not callable(method):
            raise ReconciliationError("repository does not expose get_projection")
        method = cast(Callable[..., object], method)
        parameters = _callable_parameters(method)
        if "provider" in parameters or _accepts_var_kwargs(parameters):
            return cast(object | None, await _maybe_await(method(tenant_id, provider=provider)))
        return cast(object | None, await _maybe_await(method(tenant_id)))

    async def _retrieve_state(self, context: _EventContext) -> AuthoritativeBillingState:
        method = _provider_method(self._provider)

        async def call() -> object:
            kwargs = _provider_kwargs(
                method,
                tenant_id=context.tenant_id,
                provider_customer_id=context.provider_customer_id,
                provider_subscription_id=context.provider_subscription_id,
                timeout=self._config.provider_timeout_s,
            )
            result = method(**kwargs)
            if inspect.isawaitable(result):
                return await result
            return result

        raw_state = await _retry_provider_call(
            call,
            timeout_s=self._config.provider_timeout_s,
            attempts=self._config.retry_attempts,
            initial_delay_s=self._config.retry_initial_delay_s,
            max_delay_s=self._config.retry_max_delay_s,
            jitter_s=self._config.retry_jitter_s,
            sleeper=self._sleeper,
            random_value=self._random_value,
        )
        return _normalize_state(raw_state, context)

    async def _claim_row(self, row: object) -> object | None:
        status = _inbox_status(_row_value(row, "status", WebhookInboxStatus.RECEIVED.value))
        if status not in {WebhookInboxStatus.RECEIVED, WebhookInboxStatus.FAILED}:
            return None

        custom_claim = getattr(self._repository, "claim_webhook", None)
        if callable(custom_claim):
            result = await _maybe_await(
                custom_claim(
                    provider=_required_text(_row_value(row, "provider"), "provider"),
                    provider_event_id=_required_text(
                        _row_value(row, "provider_event_id"), "provider_event_id"
                    ),
                )
            )
            if isinstance(result, bool):
                return row if result else None
            return cast(object | None, result)

        session = getattr(self._repository, "session", None)
        row_id = _row_value(row, "id", None)
        execute = getattr(session, "execute", None)
        if session is None or row_id is None or not callable(execute):
            return row

        statement = (
            select(BillingWebhookInbox)
            .where(
                BillingWebhookInbox.id == row_id,
                BillingWebhookInbox.provider == _required_text(_row_value(row, "provider"), "provider"),
                BillingWebhookInbox.provider_event_id
                == _required_text(_row_value(row, "provider_event_id"), "provider_event_id"),
                BillingWebhookInbox.status.in_(tuple(_PENDING_STATUSES)),
            )
            .with_for_update()
            .limit(1)
        )
        result = await _maybe_await(execute(statement))
        scalar_one_or_none = getattr(result, "scalar_one_or_none", None)
        if callable(scalar_one_or_none):
            return cast(object | None, scalar_one_or_none())
        scalars = getattr(result, "scalars", None)
        if callable(scalars):
            first = getattr(scalars(), "first", None)
            if callable(first):
                return cast(object | None, first())
        raise ReconciliationError("repository row-lock result is not scalar")

    async def _mark(self, row: object, *, status: WebhookInboxStatus) -> None:
        await _maybe_await(
            self._repository.mark_webhook_processed(
                provider=_required_text(_row_value(row, "provider"), "provider"),
                provider_event_id=_required_text(
                    _row_value(row, "provider_event_id"), "provider_event_id"
                ),
                status=status,
                processed_at=self._clock() if status is WebhookInboxStatus.PROCESSED else None,
            )
        )
        await self._commit()

    async def _mark_failure(self, row: object, exc: BaseException) -> None:
        try:
            await _maybe_await(
                self._repository.mark_webhook_processed(
                    provider=_safe_log_id(row, "provider"),
                    provider_event_id=_safe_log_id(row, "provider_event_id"),
                    status=WebhookInboxStatus.FAILED,
                )
            )
            await self._commit()
        except Exception as mark_exc:  # noqa: BLE001
            await self._rollback()
            self._log_failure(row, "failure_record_failed", mark_exc)
        self._log_failure(row, "row_failed", exc)

    async def _commit(self) -> None:
        target = getattr(self._repository, "session", self._repository)
        commit = getattr(target, "commit", None)
        if callable(commit):
            await _maybe_await(commit())

    async def _rollback(self) -> None:
        target = getattr(self._repository, "session", self._repository)
        rollback = getattr(target, "rollback", None)
        if callable(rollback):
            try:
                await _maybe_await(rollback())
            except Exception as exc:  # noqa: BLE001
                self._logger.error(
                    "billing_reconcile rollback_failed error_type=%s",
                    type(exc).__name__,
                )

    def _log_row(self, row: object, outcome: str, *, action: str) -> None:
        self._logger.info(
            "billing_reconcile row_%s inbox_row_id=%s provider_event_id=%s action=%s",
            outcome,
            _safe_log_id(row, "id"),
            _safe_log_id(row, "provider_event_id"),
            action,
        )

    def _log_failure(self, row: object, code: str, exc: BaseException) -> None:
        self._logger.error(
            "billing_reconcile row_failed inbox_row_id=%s provider_event_id=%s error_code=%s error_type=%s",
            _safe_log_id(row, "id"),
            _safe_log_id(row, "provider_event_id"),
            code,
            type(exc).__name__,
        )


async def reconcile(
    repository: BillingRepositoryLike,
    provider: ReconciliationProvider,
    *,
    config: ReconcileConfig | None = None,
    loop: bool = False,
    max_cycles: int | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    dry_run: bool = False,
    clock: Callable[[], datetime] | None = None,
    sleeper: Callable[[float], Awaitable[object]] = asyncio.sleep,
    random_value: Callable[[], float] = random.random,
) -> ReconcileReport:
    """Functional entry point used by tests and application wiring."""

    return await BillingReconciliationWorker(
        repository,
        provider,
        config=config,
        clock=clock,
        sleeper=sleeper,
        random_value=random_value,
    ).run(
        loop=loop,
        max_cycles=max_cycles,
        batch_size=batch_size,
        dry_run=dry_run,
    )


async def reconcile_once(
    repository: BillingRepositoryLike,
    provider: ReconciliationProvider,
    *,
    config: ReconcileConfig | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    dry_run: bool = False,
    clock: Callable[[], datetime] | None = None,
    sleeper: Callable[[float], Awaitable[object]] = asyncio.sleep,
    random_value: Callable[[], float] = random.random,
) -> ReconcileReport:
    """Process one bounded batch through the same worker used by the CLI."""

    return await reconcile(
        repository,
        provider,
        config=config,
        batch_size=batch_size,
        dry_run=dry_run,
        clock=clock,
        sleeper=sleeper,
        random_value=random_value,
    )


def validate_batch_size(value: object) -> int:
    """Validate the repository result-set cap shared by CLI and worker APIs."""

    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= MAX_BATCH_SIZE:
        raise ValueError(f"batch_size must be between 1 and {MAX_BATCH_SIZE}")
    return value


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="billing_reconcile")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true", help="process one bounded batch and exit")
    mode.add_argument("--loop", action="store_true", help="poll bounded batches until stopped")
    parser.add_argument(
        "--batch-size",
        type=_batch_size_arg,
        default=DEFAULT_BATCH_SIZE,
        help=f"pending rows per cycle (1-{MAX_BATCH_SIZE}; default {DEFAULT_BATCH_SIZE})",
    )
    parser.add_argument(
        "--max-cycles",
        type=_positive_int_arg,
        default=None,
        help="maximum loop cycles; required for bounded operation",
    )
    parser.add_argument("--dry-run", action="store_true", help="read and report without any writes")
    return parser


async def run(
    argv: Sequence[str] | None = None,
    *,
    repository: BillingRepositoryLike | None = None,
    provider: ReconciliationProvider | None = None,
    config: ReconcileConfig | None = None,
    clock: Callable[[], datetime] | None = None,
    sleeper: Callable[[float], Awaitable[object]] = asyncio.sleep,
    random_value: Callable[[], float] = random.random,
) -> int:
    """CLI-compatible async entry point with dependency injection."""

    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.once and args.max_cycles not in (None, 1):
        parser.error("--max-cycles is only valid with --loop")

    if config is None:
        if repository is None or provider is None:
            try:
                config = ReconcileConfig.from_env()
            except ConfigurationError as exc:
                sys.stderr.write(f"error: {exc}\n")
                sys.stderr.flush()
                return 2
        else:
            config = ReconcileConfig()
    if repository is None or provider is None:
        sys.stderr.write("error: billing reconciliation requires injected repository and provider\n")
        sys.stderr.flush()
        return 2

    report = await reconcile(
        repository,
        provider,
        config=config,
        loop=args.loop,
        max_cycles=args.max_cycles,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
        clock=clock,
        sleeper=sleeper,
        random_value=random_value,
    )
    sys.stderr.write(
        f"billing_reconcile cycles={report.cycles} processed={report.processed} ignored={report.ignored} "
        f"failed={report.failed} changed={report.changed} stale={report.stale} duplicates={report.duplicates} "
        f"unresolved={report.unresolved_failures} stalled={report.stalled} dry_run={args.dry_run}\n"
    )
    for change in report.changes:
        sys.stderr.write(
            f"billing_reconcile dry_run_action inbox_row_id={change.inbox_row_id} "
            f"provider_event_id={change.provider_event_id} tenant_id={change.tenant_id or ''} "
            f"action={change.action}\n"
        )
    sys.stderr.flush()
    return report.exit_code


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(run(argv))


def _parse_float_env(name: str, raw: str) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"{name} must be a finite number") from exc


def _parse_int_env(name: str, raw: str) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc


def _positive_finite(name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or value <= 0:
        raise ConfigurationError(f"{name} must be a finite positive number")


def _non_negative_finite(name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or value < 0:
        raise ConfigurationError(f"{name} must be a finite non-negative number")


def _bounded_int(name: str, value: object, *, minimum: int, maximum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ConfigurationError(f"{name} must be an integer between {minimum} and {maximum}")


def _batch_size_arg(raw: str) -> int:
    try:
        return validate_batch_size(int(raw))
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _positive_int_arg(raw: str) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if value <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return value


async def _retry_provider_call(
    call: Callable[[], Awaitable[object]],
    *,
    timeout_s: float,
    attempts: int,
    initial_delay_s: float,
    max_delay_s: float,
    jitter_s: float,
    sleeper: Callable[[float], Awaitable[object]],
    random_value: Callable[[], float],
) -> object:
    last_error: BaseException | None = None
    for attempt in range(attempts):
        try:
            return await asyncio.wait_for(call(), timeout=timeout_s)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt + 1 >= attempts:
                break
            exponential = min(max_delay_s, initial_delay_s * (2**attempt))
            jitter = max(0.0, min(1.0, float(random_value()))) * jitter_s
            await _maybe_await(sleeper(exponential + jitter))
    raise ProviderUnavailableError("provider retry budget exhausted") from last_error


def _provider_method(provider: object) -> Callable[..., object]:
    for name in _PROVIDER_METHOD_NAMES:
        method = getattr(provider, name, None)
        if callable(method):
            return cast(Callable[..., object], method)
    raise ReconciliationError("provider does not expose an authoritative state retrieval method")


def _provider_kwargs(
    method: Callable[..., object],
    *,
    tenant_id: UUID,
    provider_customer_id: str,
    provider_subscription_id: str | None,
    timeout: float,
) -> dict[str, object]:
    parameters = _callable_parameters(method)
    accepts_kwargs = _accepts_var_kwargs(parameters)
    kwargs: dict[str, object] = {}
    if accepts_kwargs or "tenant_id" in parameters:
        kwargs["tenant_id"] = tenant_id
    if accepts_kwargs:
        kwargs["provider_customer_id"] = provider_customer_id
        kwargs["provider_subscription_id"] = provider_subscription_id
        kwargs["timeout"] = timeout
        return kwargs
    for name in _CUSTOMER_PARAMETER_NAMES:
        if name in parameters:
            kwargs[name] = provider_customer_id
            break
    for name in _SUBSCRIPTION_PARAMETER_NAMES:
        if name in parameters:
            kwargs[name] = provider_subscription_id
            break
    for name in _TIMEOUT_PARAMETER_NAMES:
        if name in parameters:
            kwargs[name] = timeout
            break
    return kwargs


def _callable_parameters(method: Callable[..., object]) -> dict[str, inspect.Parameter]:
    try:
        return dict(inspect.signature(method).parameters)
    except (TypeError, ValueError):
        return {}


def _accepts_var_kwargs(parameters: Mapping[str, inspect.Parameter]) -> bool:
    return any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters.values())


def _normalize_state(raw_state: object, context: _EventContext) -> AuthoritativeBillingState:
    if isinstance(raw_state, AuthoritativeBillingState):
        if raw_state.tenant_id != context.tenant_id:
            raise ReconciliationError("provider state tenant does not match inbox tenant")
        return AuthoritativeBillingState(
            tenant_id=raw_state.tenant_id,
            provider_customer_id=_required_text(raw_state.provider_customer_id, "provider customer id"),
            provider_subscription_id=raw_state.provider_subscription_id,
            status=raw_state.status,
            current_period_end=_optional_datetime(raw_state.current_period_end, "current_period_end"),
            past_due_since=_optional_datetime(raw_state.past_due_since, "past_due_since"),
            event_position=_parse_datetime(raw_state.event_position, "provider event position"),
        )

    if isinstance(raw_state, Mapping):
        candidate: object = raw_state.get("state", raw_state)
        if isinstance(candidate, Mapping) and isinstance(raw_state.get("data"), Mapping) and "status" not in candidate:
            candidate = raw_state["data"]
    else:
        candidate = raw_state

    state_tenant = _object_value(candidate, "tenant_id")
    tenant_id = context.tenant_id if state_tenant is None else _parse_uuid(state_tenant, "provider tenant_id")
    customer_value = _first_value(
        _object_value(candidate, "provider_customer_id"),
        _object_value(candidate, "customer_id"),
        context.provider_customer_id,
    )
    if not isinstance(customer_value, str) or not customer_value:
        raise ReconciliationError("provider state has no customer id")

    subscription_value = _first_value(
        _object_value(candidate, "provider_subscription_id"),
        _object_value(candidate, "subscription_id"),
        _nested_value(_object_value(candidate, "subscription"), "id"),
        context.provider_subscription_id,
    )
    if subscription_value is not None and not isinstance(subscription_value, str):
        raise ReconciliationError("provider state subscription id must be a string")

    status_value = _first_value(
        _object_value(candidate, "status"),
        _nested_value(_object_value(candidate, "subscription"), "status"),
    )
    try:
        status = (
            status_value
            if isinstance(status_value, BillingSubscriptionStatus)
            else BillingSubscriptionStatus(cast(str, status_value))
        )
    except (TypeError, ValueError) as exc:
        raise ReconciliationError("provider state has an unknown subscription status") from exc

    event_position_value = _first_value(
        _object_value(candidate, "event_position"),
        _object_value(candidate, "provider_event_position"),
        _object_value(candidate, "updated_at"),
        _object_value(candidate, "last_updated_at"),
        _object_value(candidate, "modified_at"),
    )
    event_position = _parse_datetime(event_position_value, "provider event position")
    period_end = _optional_datetime(
        _first_value(
            _object_value(candidate, "current_period_end"),
            _nested_value(_object_value(candidate, "subscription"), "current_period_end"),
        ),
        "current_period_end",
    )
    past_due_since = _optional_datetime(
        _first_value(
            _object_value(candidate, "past_due_since"),
            _nested_value(_object_value(candidate, "subscription"), "past_due_since"),
        ),
        "past_due_since",
    )
    return AuthoritativeBillingState(
        tenant_id=tenant_id,
        provider_customer_id=customer_value,
        provider_subscription_id=subscription_value,
        status=status,
        current_period_end=period_end,
        past_due_since=past_due_since,
        event_position=event_position,
    )


def _projection_action(
    projection: object | None,
    state: AuthoritativeBillingState,
    provider_event_id: str,
    provider: str,
) -> str:
    if projection is None:
        return "create_projection"
    stored_provider = _projection_value(projection, "provider")
    if stored_provider != provider:
        raise ReconciliationError("tenant projection is owned by another provider")
    if _same_event(projection, provider_event_id):
        return "skip_duplicate"
    stored_event_id = _projection_value(projection, "last_event_id")
    if stored_event_id is not None:
        stored_position = _parse_datetime(
            _projection_value(projection, "updated_at"),
            "projection event position",
        )
        if state.event_position <= stored_position:
            return "skip_stale"
    return "update_projection"


def _same_event(projection: object, provider_event_id: str) -> bool:
    return _projection_value(projection, "last_event_id") == provider_event_id


def _projection_value(projection: object | None, name: str) -> object | None:
    if projection is None:
        return None
    return _object_value(projection, name)


def _object_value(value: object, name: str, default: object | None = None) -> object | None:
    if isinstance(value, Mapping):
        return cast(object | None, value.get(name, default))
    return cast(object | None, getattr(value, name, default))


def _nested_value(value: object, name: str) -> object | None:
    return _object_value(value, name) if isinstance(value, Mapping) or value is not None else None


def _row_value(row: object, name: str, default: object = None) -> object:
    return _object_value(row, name, default)


def _first_value(*values: object | None) -> object | None:
    for value in values:
        if value is not None:
            return value
    return None


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ReconciliationError(f"{name} must be a non-empty string")
    return value


def _parse_uuid(value: object, name: str) -> UUID:
    if isinstance(value, UUID):
        return value
    if not isinstance(value, str) or not value:
        raise ReconciliationError(f"{name} must be a UUID")
    try:
        return UUID(value)
    except ValueError as exc:
        raise ReconciliationError(f"{name} must be a UUID") from exc


def _parse_datetime(value: object, name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ReconciliationError(f"{name} must be an ISO timestamp") from exc
    else:
        raise ReconciliationError(f"{name} must be an ISO timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _optional_datetime(value: object | None, name: str) -> datetime | None:
    if value is None:
        return None
    return _parse_datetime(value, name)


def _inbox_status(value: object) -> WebhookInboxStatus:
    if isinstance(value, WebhookInboxStatus):
        return value
    try:
        return WebhookInboxStatus(cast(str, value))
    except (TypeError, ValueError) as exc:
        raise ReconciliationError("inbox row has an unknown status") from exc


def _row_key(row: object) -> str:
    row_id = _row_value(row, "id", None)
    if row_id is not None:
        return f"row:{row_id}"
    return f"event:{_safe_log_id(row, 'provider')}:{_safe_log_id(row, 'provider_event_id')}"


def _safe_log_id(row: object, name: str) -> str:
    value = _row_value(row, name, "unknown")
    if value is None:
        return "unknown"
    return str(value)


async def _maybe_await(value: object) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


BillingReconcileWorker = BillingReconciliationWorker


__all__ = [
    "AuthoritativeBillingState",
    "BillingReconcileWorker",
    "BillingReconciliationWorker",
    "ConfigurationError",
    "DEFAULT_BATCH_SIZE",
    "MAX_BATCH_SIZE",
    "ProviderUnavailable",
    "ProviderUnavailableError",
    "ReconcileConfig",
    "ReconcileReport",
    "ReconciliationProvider",
    "UnsupportedWebhook",
    "UnsupportedWebhookError",
    "main",
    "reconcile",
    "reconcile_once",
    "run",
    "validate_batch_size",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
