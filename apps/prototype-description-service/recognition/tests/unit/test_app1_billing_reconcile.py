"""APP-1 billing reconciliation worker tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest

from recognition.domain.portal_contracts import BillingState, BillingSubscriptionStatus, WebhookInboxStatus
from scripts.billing_reconcile import (
    MAX_BATCH_SIZE,
    ReconcileConfig,
    reconcile,
    validate_batch_size,
)

_TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")
_BASE_POSITION = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def _row(
    event_id: str,
    *,
    row_id: str | None = None,
    tenant_id: UUID = _TENANT_ID,
    customer_id: str | None = None,
    status: WebhookInboxStatus = WebhookInboxStatus.RECEIVED,
) -> SimpleNamespace:
    customer = customer_id or f"cus-{event_id}"
    return SimpleNamespace(
        id=row_id or f"row-{event_id}",
        provider="polar",
        provider_event_id=event_id,
        event_type="subscription.active",
        payload={
            "type": "subscription.active",
            "data": {
                "tenant_id": str(tenant_id),
                "customer_id": customer,
                "subscription_id": f"sub-{event_id}",
            },
        },
        status=status.value,
    )


class _Repository:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self.rows = rows
        self.projections: dict[UUID, SimpleNamespace] = {}
        self.list_limits: list[int] = []
        self.upserts: list[dict[str, object]] = []
        self.marks: list[dict[str, object]] = []

    async def list_pending_webhooks(self, *, limit: int) -> list[SimpleNamespace]:
        self.list_limits.append(limit)
        pending = {
            WebhookInboxStatus.RECEIVED.value,
            WebhookInboxStatus.FAILED.value,
        }
        return [row for row in self.rows if row.status in pending][:limit]

    async def get_projection(self, tenant_id: UUID, *, provider: str | None = None) -> SimpleNamespace | None:
        projection = self.projections.get(tenant_id)
        if projection is not None and provider is not None and projection.provider != provider:
            return projection
        return projection

    async def upsert_projection(self, **kwargs: object) -> bool:
        self.upserts.append(kwargs)
        tenant_id = kwargs["tenant_id"]
        assert isinstance(tenant_id, UUID)
        existing = self.projections.get(tenant_id)
        position = kwargs["event_position"]
        assert isinstance(position, datetime)
        if existing is not None and (
            existing.last_event_id == kwargs["provider_event_id"] or position <= existing.updated_at
        ):
            return False
        status = kwargs["status"]
        assert isinstance(status, BillingSubscriptionStatus)
        self.projections[tenant_id] = SimpleNamespace(
            provider=kwargs["provider"],
            provider_customer_id=kwargs["provider_customer_id"],
            provider_subscription_id=kwargs["provider_subscription_id"],
            status=status.value,
            current_period_end=kwargs["current_period_end"],
            past_due_since=kwargs["past_due_since"],
            last_event_id=kwargs["provider_event_id"],
            updated_at=position,
        )
        return True

    async def mark_webhook_processed(
        self,
        *,
        provider: str,
        provider_event_id: str,
        status: WebhookInboxStatus,
        processed_at: datetime | None = None,
    ) -> bool:
        self.marks.append(
            {
                "provider": provider,
                "provider_event_id": provider_event_id,
                "status": status,
                "processed_at": processed_at,
            }
        )
        for row in self.rows:
            if row.provider == provider and row.provider_event_id == provider_event_id:
                row.status = status.value
                return True
        return False


class _Provider:
    def __init__(self, *, positions: dict[str, datetime] | None = None) -> None:
        self.positions = positions or {}
        self.calls: list[dict[str, object]] = []

    async def retrieve_state(
        self,
        *,
        provider_customer_id: str,
        provider_subscription_id: str | None,
        request_timeout: float,
    ) -> dict[str, object]:
        self.calls.append(
            {
                "customer_id": provider_customer_id,
                "subscription_id": provider_subscription_id,
                "timeout": request_timeout,
            }
        )
        position = self.positions.get(
            provider_subscription_id or "",
            self.positions.get(provider_customer_id, _BASE_POSITION),
        )
        return {
            "tenant_id": str(_TENANT_ID),
            "provider_customer_id": provider_customer_id,
            "provider_subscription_id": provider_subscription_id,
            "status": BillingSubscriptionStatus.ACTIVE.value,
            "current_period_end": "2026-10-20T12:00:00Z",
            "past_due_since": None,
            "event_position": position,
        }


class _PoisonProvider(_Provider):
    def __init__(self, *, timeout_error: bool = False) -> None:
        super().__init__()
        self.timeout_error = timeout_error

    async def retrieve_state(
        self,
        *,
        provider_customer_id: str,
        provider_subscription_id: str | None,
        request_timeout: float,
    ) -> dict[str, object]:
        self.calls.append({"customer_id": provider_customer_id, "timeout": request_timeout})
        if self.timeout_error:
            raise TimeoutError("simulated provider timeout")
        if provider_customer_id == "cus-poison":
            raise RuntimeError("simulated outage")
        return await super().retrieve_state(
            provider_customer_id=provider_customer_id,
            provider_subscription_id=provider_subscription_id,
            request_timeout=request_timeout,
        )


class _EntitlementService:
    def __init__(self) -> None:
        self.states: list[BillingState] = []

    async def apply_billing_state(self, tenant_id: UUID, state: BillingState) -> None:
        assert tenant_id == state.tenant_id
        self.states.append(state)


def _config(**updates: object) -> ReconcileConfig:
    values: dict[str, object] = {
        "provider_timeout_s": 0.1,
        "retry_attempts": 1,
        "retry_initial_delay_s": 0,
        "retry_max_delay_s": 0.1,
        "retry_jitter_s": 0,
        "stall_limit": 2,
        "poll_interval_s": 0,
    }
    values.update(updates)
    return ReconcileConfig(**values)


async def _no_sleep(_delay: float) -> None:
    return None


@pytest.mark.asyncio
async def test_clean_batch_processes_every_row_and_exits_zero() -> None:
    repository = _Repository(
        [
            _row("evt-1", customer_id="cus-shared"),
            _row("evt-2", customer_id="cus-shared"),
            _row("evt-3", customer_id="cus-shared"),
        ]
    )
    provider = _Provider(
        positions={
            "sub-evt-1": _BASE_POSITION,
            "sub-evt-2": _BASE_POSITION + timedelta(minutes=1),
            "sub-evt-3": _BASE_POSITION + timedelta(minutes=2),
        }
    )

    report = await reconcile(
        repository,
        provider,
        config=_config(),
        batch_size=100,
        sleeper=_no_sleep,
    )

    assert report.exit_code == 0
    assert report.processed == 3
    assert report.changed == 3
    assert len(repository.upserts) == 3
    assert repository.list_limits == [100]
    assert all(row.status == WebhookInboxStatus.PROCESSED.value for row in repository.rows)
    assert all(call["timeout"] == 0.1 for call in provider.calls)


@pytest.mark.asyncio
async def test_h1_success_applies_billing_state_before_acknowledging_event() -> None:
    repository = _Repository([_row("evt-apply")])
    provider = _Provider()
    entitlement_service = _EntitlementService()

    report = await reconcile(
        repository,
        provider,
        entitlement_service=entitlement_service,
        config=_config(),
        sleeper=_no_sleep,
    )

    assert report.exit_code == 0
    assert len(entitlement_service.states) == 1
    assert entitlement_service.states[0].status is BillingSubscriptionStatus.ACTIVE
    assert repository.marks[-1]["status"] is WebhookInboxStatus.PROCESSED


@pytest.mark.asyncio
async def test_h1_dry_run_does_not_apply_billing_state() -> None:
    repository = _Repository([_row("evt-apply-dry")])
    entitlement_service = _EntitlementService()

    report = await reconcile(
        repository,
        _Provider(),
        entitlement_service=entitlement_service,
        config=_config(),
        dry_run=True,
        sleeper=_no_sleep,
    )

    assert report.exit_code == 0
    assert entitlement_service.states == []
    assert repository.upserts == []
    assert repository.marks == []


@pytest.mark.asyncio
async def test_h9_projection_customer_mismatch_fails_closed_before_provider_call() -> None:
    row = _row("evt-customer-mismatch", customer_id="cus-stale")
    repository = _Repository([row])
    repository.projections[_TENANT_ID] = SimpleNamespace(
        provider="polar",
        provider_customer_id="cus-current",
        provider_subscription_id="sub-current",
        status=BillingSubscriptionStatus.ACTIVE.value,
        current_period_end=None,
        past_due_since=None,
        last_event_id="evt-current",
        updated_at=_BASE_POSITION,
    )
    provider = _Provider()

    report = await reconcile(repository, provider, config=_config(), sleeper=_no_sleep)

    assert report.exit_code == 1
    assert report.failed == 1
    assert provider.calls == []
    assert repository.upserts == []
    assert repository.rows[0].status == WebhookInboxStatus.FAILED.value


@pytest.mark.asyncio
async def test_h9_provider_customer_mismatch_fails_closed_before_projection_write() -> None:
    class _MismatchedProvider(_Provider):
        async def retrieve_state(
            self,
            *,
            provider_customer_id: str,
            provider_subscription_id: str | None,
            request_timeout: float,
        ) -> dict[str, object]:
            state = await super().retrieve_state(
                provider_customer_id=provider_customer_id,
                provider_subscription_id=provider_subscription_id,
                request_timeout=request_timeout,
            )
            state["provider_customer_id"] = "cus-other"
            return state

    repository = _Repository([_row("evt-provider-customer")])
    provider = _MismatchedProvider()

    report = await reconcile(repository, provider, config=_config(), sleeper=_no_sleep)

    assert report.exit_code == 1
    assert report.failed == 1
    assert repository.upserts == []
    assert repository.rows[0].status == WebhookInboxStatus.FAILED.value


@pytest.mark.asyncio
async def test_poison_row_does_not_prevent_other_rows_in_same_cycle() -> None:
    repository = _Repository([_row("evt-poison", customer_id="cus-poison"), _row("evt-good")])
    provider = _PoisonProvider()

    report = await reconcile(
        repository,
        provider,
        config=_config(),
        sleeper=_no_sleep,
    )

    assert report.exit_code == 1
    assert report.failed == 1
    assert report.changed == 1
    assert repository.rows[0].status == WebhookInboxStatus.FAILED.value
    assert repository.rows[1].status == WebhookInboxStatus.PROCESSED.value
    assert len(repository.upserts) == 1


@pytest.mark.asyncio
async def test_repeated_no_progress_trips_stall_threshold() -> None:
    repository = _Repository([_row("evt-poison", customer_id="cus-poison")])
    provider = _PoisonProvider()
    sleeps: list[float] = []

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    report = await reconcile(
        repository,
        provider,
        config=_config(stall_limit=2),
        loop=True,
        max_cycles=10,
        sleeper=record_sleep,
    )

    assert report.exit_code == 1
    assert report.stalled is True
    assert report.cycles == 2
    assert len(sleeps) == 1
    assert len(provider.calls) == 2


@pytest.mark.asyncio
async def test_provider_timeout_leaves_row_pending_without_projection_write() -> None:
    repository = _Repository([_row("evt-timeout")])
    provider = _PoisonProvider(timeout_error=True)

    report = await reconcile(
        repository,
        provider,
        config=_config(retry_attempts=2),
        sleeper=_no_sleep,
    )

    assert report.exit_code == 1
    assert report.failed == 1
    assert repository.rows[0].status == WebhookInboxStatus.FAILED.value
    assert repository.upserts == []
    assert [mark["status"] for mark in repository.marks] == [WebhookInboxStatus.FAILED]
    assert len(provider.calls) == 2


@pytest.mark.asyncio
async def test_m15_dry_run_provider_failure_does_not_update_retry_state() -> None:
    repository = _Repository([_row("evt-dry-failure")])
    provider = _PoisonProvider(timeout_error=True)

    report = await reconcile(
        repository,
        provider,
        config=_config(retry_attempts=2),
        dry_run=True,
        sleeper=_no_sleep,
    )

    assert report.exit_code == 1
    assert report.failed == 1
    assert [change.action for change in report.changes] == ["would_fail"]
    assert repository.marks == []
    assert repository.rows[0].status == WebhookInboxStatus.RECEIVED.value


@pytest.mark.asyncio
async def test_m16_recheck_skips_write_when_another_worker_changes_attempts() -> None:
    repository = _Repository([_row("evt-attempt-race")])

    class _RecheckRepository(_Repository):
        async def get_webhook(self, *, provider: str, provider_event_id: str) -> SimpleNamespace | None:
            return next(
                (
                    candidate
                    for candidate in self.rows
                    if candidate.provider == provider and candidate.provider_event_id == provider_event_id
                ),
                None,
            )

    repository = _RecheckRepository(repository.rows)

    class _AttemptChangingProvider(_Provider):
        async def retrieve_state(
            self,
            *,
            provider_customer_id: str,
            provider_subscription_id: str | None,
            request_timeout: float,
        ) -> dict[str, object]:
            repository.rows[0].attempts = 1
            return await super().retrieve_state(
                provider_customer_id=provider_customer_id,
                provider_subscription_id=provider_subscription_id,
                request_timeout=request_timeout,
            )

    report = await reconcile(repository, _AttemptChangingProvider(), config=_config(), sleeper=_no_sleep)

    assert report.exit_code == 0
    assert report.processed == 0
    assert repository.upserts == []
    assert repository.marks == []


@pytest.mark.asyncio
async def test_same_row_processed_twice_has_one_projection_transition() -> None:
    row = _row("evt-repeat")
    repository = _Repository([row])
    provider = _Provider()

    first = await reconcile(repository, provider, config=_config(), sleeper=_no_sleep)
    row.status = WebhookInboxStatus.RECEIVED.value
    second = await reconcile(repository, provider, config=_config(), sleeper=_no_sleep)

    assert first.exit_code == 0
    assert second.exit_code == 0
    assert len(repository.upserts) == 1
    assert second.duplicates == 1
    assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_older_provider_state_does_not_regress_projection() -> None:
    row = _row("evt-old", customer_id="cus-old")
    repository = _Repository([row])
    repository.projections[_TENANT_ID] = SimpleNamespace(
        provider="polar",
        provider_customer_id="cus-old",
        provider_subscription_id="sub-new",
        status=BillingSubscriptionStatus.ACTIVE.value,
        current_period_end=None,
        past_due_since=None,
        last_event_id="evt-new",
        updated_at=_BASE_POSITION + timedelta(hours=1),
    )
    provider = _Provider(positions={"cus-old": _BASE_POSITION})

    report = await reconcile(repository, provider, config=_config(), sleeper=_no_sleep)

    projection = repository.projections[_TENANT_ID]
    assert report.exit_code == 0
    assert report.stale == 1
    assert projection.last_event_id == "evt-new"
    assert projection.updated_at == _BASE_POSITION + timedelta(hours=1)
    assert repository.upserts == []


@pytest.mark.asyncio
async def test_dry_run_reports_change_and_writes_nothing() -> None:
    repository = _Repository([_row("evt-dry")])
    provider = _Provider()

    report = await reconcile(
        repository,
        provider,
        config=_config(),
        dry_run=True,
        sleeper=_no_sleep,
    )

    assert report.exit_code == 0
    assert report.would_change == 1
    assert [change.action for change in report.changes] == ["create_projection"]
    assert repository.upserts == []
    assert repository.marks == []
    assert repository.rows[0].status == WebhookInboxStatus.RECEIVED.value


def test_batch_size_cap_is_enforced() -> None:
    with pytest.raises(ValueError, match="between 1 and"):
        validate_batch_size(MAX_BATCH_SIZE + 1)


def test_required_config_and_malformed_config_fail_fast() -> None:
    with pytest.raises(ValueError, match="missing required"):
        ReconcileConfig.from_env({})
    with pytest.raises(ValueError, match="finite number"):
        ReconcileConfig.from_env({"BILLING_RECONCILE_PROVIDER_TIMEOUT_SECONDS": "not-a-number"})


@pytest.mark.asyncio
async def test_retry_sleeper_is_injected_without_real_sleep() -> None:
    repository = _Repository([_row("evt-retry")])

    class _RetryProvider(_Provider):
        def __init__(self) -> None:
            super().__init__()
            self.attempt = 0

        async def retrieve_state(
            self,
            *,
            provider_customer_id: str,
            provider_subscription_id: str | None,
            request_timeout: float,
        ) -> dict[str, object]:
            self.attempt += 1
            if self.attempt == 1:
                raise TimeoutError
            return await super().retrieve_state(
                provider_customer_id=provider_customer_id,
                provider_subscription_id=provider_subscription_id,
                    request_timeout=request_timeout,
            )

    provider = _RetryProvider()
    delays: list[float] = []

    async def collect_delay(delay: float) -> None:
        delays.append(delay)

    report = await reconcile(
        repository,
        provider,
        config=_config(retry_attempts=2, retry_initial_delay_s=0.25, retry_max_delay_s=0.5, retry_jitter_s=0),
        sleeper=collect_delay,
    )

    assert report.exit_code == 0
    assert len(delays) == 1
    assert delays[0] == 0.25


@pytest.mark.asyncio
async def test_timeout_does_not_use_unbounded_provider_call() -> None:
    repository = _Repository([_row("evt-never")])

    class _NeverProvider:
        async def retrieve_state(
            self,
            *,
            provider_customer_id: str,
            provider_subscription_id: str | None,
            request_timeout: float,
        ) -> dict[str, object]:
            await asyncio.Future()
            raise AssertionError("unreachable")

    report = await reconcile(
        repository,
        _NeverProvider(),
        config=_config(provider_timeout_s=0.001),
        sleeper=_no_sleep,
    )

    assert report.exit_code == 1
    assert repository.upserts == []
