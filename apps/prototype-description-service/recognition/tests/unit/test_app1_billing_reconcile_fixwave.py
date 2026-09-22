"""APP-1 R1 reconcile-fix-worker receipts for RV01-RV05, RV07, RV08."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from recognition.domain.portal_contracts import (
    BillingState,
    BillingSubscriptionStatus,
    EnumerationPage,
    ReconciliationKind,
)
from recognition.tests.unit.test_app1_billing_reconcile import (
    _config,
    _no_sleep,
    _Provider,
    _Repository,
    _row,
)
from recognition.tests.unit.test_app1_billing_reconcile_recovery import (
    _billing_repo,
    _Clock,
    _EnumProvider,
    _page,
    _Recovery,
    _run_orphans,
    _Session,
    _state,
)
from scripts import billing_reconcile as billing_reconcile_module
from scripts.billing_reconcile import reconcile

_TENANT_A = UUID("00000000-0000-0000-0000-000000000001")
_NOW = datetime(2026, 9, 22, 18, 0, tzinfo=UTC)
_POSITION = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)
_SELLER = "org_sandbox"


class _EchoProvider(_Provider):
    async def retrieve_state(
        self,
        *,
        provider_customer_id: str,
        provider_subscription_id: str | None,
        request_timeout: float,
    ) -> dict[str, object]:
        session = getattr(self, "session", None)
        self.calls.append(
            {
                "customer_id": provider_customer_id,
                "subscription_id": provider_subscription_id,
                "timeout": request_timeout,
                "txn_open": bool(
                    getattr(session, "in_txn", False) or getattr(session, "in_transaction", lambda: False)()
                ),
            }
        )
        return {
            "provider_customer_id": provider_customer_id,
            "provider_subscription_id": provider_subscription_id,
            "status": BillingSubscriptionStatus.ACTIVE.value,
            "current_period_end": "2026-10-20T12:00:00Z",
            "past_due_since": None,
            "event_position": _POSITION,
        }


class _MismatchCustomerProvider(_EchoProvider):
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


class _MismatchSubscriptionProvider(_EchoProvider):
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
        state["provider_subscription_id"] = "sub-other"
        return state


class _PoisonKnownProvider(_EchoProvider):
    async def retrieve_state(
        self,
        *,
        provider_customer_id: str,
        provider_subscription_id: str | None,
        request_timeout: float,
    ) -> dict[str, object]:
        if provider_customer_id == "cus-known":
            self.calls.append(
                {
                    "customer_id": provider_customer_id,
                    "subscription_id": provider_subscription_id,
                    "timeout": request_timeout,
                    "txn_open": False,
                }
            )
            raise RuntimeError("simulated known-projection outage")
        return await super().retrieve_state(
            provider_customer_id=provider_customer_id,
            provider_subscription_id=provider_subscription_id,
            request_timeout=request_timeout,
        )


class _KeyedRecovery(_Recovery):
    def __init__(self, *, session: _Session | None = None) -> None:
        super().__init__(session=session)
        self._by_kind: dict[ReconciliationKind, dict[str, object]] = {}

    def _persist(self) -> None:
        if self.key is None:
            return
        self._by_kind[self.key.kind] = {
            "cursor": self.cursor,
            "exhausted": self.exhausted,
            "fence": self.fence,
            "progress": dict(self.progress),
            "quarantine": dict(self.quarantine),
        }

    def _restore(self, key) -> None:
        stored = self._by_kind.get(key.kind)
        if stored is None:
            self.cursor = None
            self.exhausted = False
            self.progress = {}
            self.quarantine = {}
            self.fence = 0
            return
        self.cursor = stored["cursor"]
        self.exhausted = stored["exhausted"]
        self.progress = dict(stored["progress"])
        self.quarantine = dict(stored["quarantine"])
        self.fence = stored["fence"]

    async def acquire_lease(self, key, *, owner: str, lease_ttl: timedelta, now: datetime):
        if self.key is not None:
            self._persist()
        self._restore(key)
        lease = await super().acquire_lease(key, owner=owner, lease_ttl=lease_ttl, now=now)
        self._persist()
        return lease

    async def advance_cursor(self, lease, *, next_cursor, exhausted, page_remote_ids, now):
        result = await super().advance_cursor(
            lease,
            next_cursor=next_cursor,
            exhausted=exhausted,
            page_remote_ids=page_remote_ids,
            now=now,
        )
        self._persist()
        return result


class _TxnLookupRepository(_Repository):
    async def get_projection(self, tenant_id: UUID, *, provider: str | None = None) -> SimpleNamespace | None:
        mark_write = getattr(self.session, "mark_write", None)
        if callable(mark_write):
            mark_write()
        return await super().get_projection(tenant_id, provider=provider)


def _known_row(
    tenant_id: UUID,
    *,
    customer_id: str,
    subscription_id: str,
) -> SimpleNamespace:
    return SimpleNamespace(
        tenant_id=tenant_id,
        provider="fake",
        provider_customer_id=customer_id,
        provider_subscription_id=subscription_id,
        status=BillingSubscriptionStatus.ACTIVE.value,
        current_period_end=_POSITION + timedelta(days=30),
        past_due_since=None,
        last_event_id=f"evt-{subscription_id}",
        updated_at=_POSITION - timedelta(days=1),
        environment="sandbox",
        seller_account=_SELLER,
    )


def _attempt(
    *, checkout_id: str | None, attempt_id: UUID | None = None, updated_at: datetime | None = None
) -> SimpleNamespace:
    return SimpleNamespace(
        id=attempt_id or uuid4(),
        tenant_id=_TENANT_A,
        provider="fake",
        environment="sandbox",
        seller_account=_SELLER,
        status="ambiguous",
        provider_checkout_id=checkout_id,
        updated_at=updated_at or (_NOW - timedelta(seconds=30)),
    )


@pytest.mark.asyncio
async def test_rv01_known_projections_are_page_bounded_and_non_healthy_when_more_remain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(billing_reconcile_module, "RECONCILIATION_PAGE_LIMIT", 2)
    monkeypatch.setattr(billing_reconcile_module, "RECONCILIATION_MAX_PAGES_PER_RUN", 2)
    tenants = [UUID(int=index) for index in range(1, 6)]
    repository = _Repository([])
    repository.known = [
        _known_row(tenant, customer_id=f"cus-{index}", subscription_id=f"sub-{index}")
        for index, tenant in enumerate(tenants, start=1)
    ]
    for row in repository.known:
        repository.tenants.add(row.tenant_id)
        repository.projections[row.tenant_id] = row
    provider = _EchoProvider()

    report = await reconcile(repository, provider, config=_config(), sleeper=_no_sleep)

    assert len(provider.calls) == 4
    assert report.failed >= 1
    assert report.exit_code == 1
    assert len(repository.upserts) == 4


@pytest.mark.asyncio
async def test_rv02_malformed_orphan_is_quarantined_and_later_valid_item_applies() -> None:
    malformed = BillingState(
        tenant_id=_TENANT_A,
        status=BillingSubscriptionStatus.NONE,
        provider_customer_id=None,
        current_period_end=None,
        past_due_since=None,
        provider_subscription_id=None,
        event_position=_POSITION,
    )
    valid = _state(_TENANT_A, subscription_id="sub-good")
    provider = _EnumProvider({None: _page((malformed, valid), exhausted=True)})
    recovery = _Recovery()
    repository = _billing_repo()

    report = await _run_orphans(provider, recovery, repository)

    assert any(item.startswith("missing:") for item in recovery.quarantines)
    assert "sub-good" in recovery.completes
    assert repository.upserts
    assert repository.entitlement_service.states
    assert recovery.advances
    assert report.exit_code == 0


@pytest.mark.asyncio
async def test_rv03_known_projection_failure_is_unhealthy_even_when_inbox_advances() -> None:
    repository = _Repository([_row("evt-ok", customer_id="cus-evt-ok")])
    other = UUID("00000000-0000-0000-0000-000000000099")
    repository.known = [_known_row(other, customer_id="cus-known", subscription_id="sub-known")]
    repository.tenants.add(other)
    provider = _PoisonKnownProvider()

    report = await reconcile(repository, provider, config=_config(), sleeper=_no_sleep)

    assert report.failed >= 1
    assert report.exit_code == 1
    assert repository.rows[0].status == "processed"


@pytest.mark.asyncio
async def test_rv03_known_projection_failure_without_recovery_is_not_exit_zero() -> None:
    repository = _Repository([])
    repository.known = [_known_row(_TENANT_A, customer_id="cus-known", subscription_id="sub-known")]
    provider = _PoisonKnownProvider()

    report = await reconcile(repository, provider, config=_config(), sleeper=_no_sleep)

    assert report.failed >= 1
    assert report.exit_code == 1
    assert repository.upserts == []


@pytest.mark.asyncio
async def test_rv04_ambiguous_checkout_cursor_advances_past_first_bounded_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(billing_reconcile_module, "RECONCILIATION_PAGE_LIMIT", 2)
    attempts = [
        _attempt(checkout_id=f"chk-{index}", updated_at=_NOW - timedelta(seconds=40 - index)) for index in range(3)
    ]
    provider = _EnumProvider({None: EnumerationPage((), None, True)})

    async def _empty_page(*, cursor: str | None, limit: int, request_timeout: float):
        provider.enumerate_calls.append(
            {"cursor": cursor, "limit": limit, "timeout": request_timeout, "txn_open": False}
        )
        return EnumerationPage((), None, True)

    provider.enumerate_subscriptions = _empty_page  # type: ignore[method-assign]
    recovery = _KeyedRecovery()
    repository = _billing_repo()

    first = await reconcile(
        repository,
        provider,
        recovery_repository=recovery,
        stale_checkout_attempts=attempts,
        config=_config(provider_timeout_s=8.0),
        clock=_Clock(),
        sleeper=_no_sleep,
    )
    assert recovery.exhausted is False
    assert recovery.cursor is not None
    assert [call["id"] for call in provider.checkout_calls] == ["chk-0", "chk-1"]
    assert first.exit_code == 0

    second = await reconcile(
        repository,
        provider,
        recovery_repository=recovery,
        stale_checkout_attempts=attempts,
        config=_config(provider_timeout_s=8.0),
        clock=_Clock(),
        sleeper=_no_sleep,
    )
    assert [call["id"] for call in provider.checkout_calls] == ["chk-0", "chk-1", "chk-2"]
    assert recovery.exhausted is True
    assert second.exit_code == 0


@pytest.mark.asyncio
async def test_rv05_known_projection_rejects_returned_customer_mismatch() -> None:
    repository = _Repository([])
    repository.known = [_known_row(_TENANT_A, customer_id="cus-expected", subscription_id="sub-expected")]
    provider = _MismatchCustomerProvider()

    report = await reconcile(repository, provider, config=_config(), sleeper=_no_sleep)

    assert repository.upserts == []
    assert repository.entitlement_service.states == []
    assert report.failed >= 1
    assert report.exit_code == 1


@pytest.mark.asyncio
async def test_rv05_known_projection_rejects_returned_subscription_mismatch() -> None:
    repository = _Repository([])
    repository.known = [_known_row(_TENANT_A, customer_id="cus-expected", subscription_id="sub-expected")]
    provider = _MismatchSubscriptionProvider()

    report = await reconcile(repository, provider, config=_config(), sleeper=_no_sleep)

    assert repository.upserts == []
    assert repository.entitlement_service.states == []
    assert report.failed >= 1
    assert report.exit_code == 1


@pytest.mark.asyncio
async def test_rv07_checkout_customer_lookup_does_not_hold_transaction_during_provider_get() -> None:
    session = _Session()
    repository = _TxnLookupRepository([], session=session)
    repository.projections[_TENANT_A] = SimpleNamespace(
        provider="fake",
        provider_customer_id="cus-from-projection",
        provider_subscription_id="sub-paid",
        status=BillingSubscriptionStatus.ACTIVE.value,
        current_period_end=None,
        past_due_since=None,
        last_event_id="evt-seed",
        updated_at=_POSITION,
        environment="sandbox",
        seller_account=_SELLER,
        tenant_id=_TENANT_A,
    )
    attempt = _attempt(checkout_id="chk-paid")

    class _PaidCheckoutProvider(_EnumProvider):
        async def retrieve_checkout(self, *, provider_checkout_id: str, request_timeout: float):
            self.checkout_calls.append(
                {
                    "id": provider_checkout_id,
                    "timeout": request_timeout,
                    "txn_open": bool(self.session.in_txn if self.session is not None else False),
                }
            )
            return {
                "id": provider_checkout_id,
                "status": "succeeded",
                "subscription_id": "sub-paid",
            }

        async def retrieve_state(
            self,
            *,
            provider_customer_id: str,
            provider_subscription_id: str | None,
            request_timeout: float,
        ) -> BillingState:
            self.retrieve_calls.append(
                {
                    "customer_id": provider_customer_id,
                    "subscription_id": provider_subscription_id,
                    "timeout": request_timeout,
                    "txn_open": bool(self.session.in_txn if self.session is not None else False),
                }
            )
            return _state(
                _TENANT_A,
                customer_id=provider_customer_id,
                subscription_id=provider_subscription_id or "sub-paid",
            )

    recovery = _Recovery(session=session)
    provider = _PaidCheckoutProvider({None: _page(exhausted=True)})
    provider.session = session

    report = await reconcile(
        repository,
        provider,
        entitlement_service=repository.entitlement_service,
        recovery_repository=recovery,
        stale_checkout_attempts=[attempt],
        config=_config(provider_timeout_s=8.0),
        clock=_Clock(),
        sleeper=_no_sleep,
    )

    assert provider.retrieve_calls
    assert all(call["txn_open"] is False for call in provider.retrieve_calls)
    assert all(call["txn_open"] is False for call in provider.checkout_calls)
    assert report.exit_code == 0
    assert repository.upserts


@pytest.mark.asyncio
async def test_rv08_orphan_missing_event_position_is_quarantined_not_synthesized() -> None:
    missing = BillingState(
        tenant_id=_TENANT_A,
        status=BillingSubscriptionStatus.ACTIVE,
        provider_customer_id="cus-1",
        current_period_end=_POSITION + timedelta(days=30),
        past_due_since=None,
        provider_subscription_id="sub-no-pos",
        event_position=None,
    )
    provider = _EnumProvider({None: _page((missing,), exhausted=True)})
    recovery = _Recovery()
    repository = _billing_repo()

    first = await _run_orphans(provider, recovery, repository)
    second = await _run_orphans(provider, recovery, repository)

    assert "sub-no-pos" in recovery.quarantines
    assert repository.upserts == []
    assert repository.entitlement_service.states == []
    assert first.exit_code == 0
    assert second.exit_code == 0
    assert recovery.quarantines.count("sub-no-pos") >= 1
