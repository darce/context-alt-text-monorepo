"""R1 recovery worker tests: C0 leases, orphan pages, ambiguous checkouts, retry."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import scripts.billing_reconcile as billing_reconcile

from recognition.domain.portal_contracts import (
    RECONCILIATION_MAX_PAGES_PER_RUN,
    RECONCILIATION_PAGE_LIMIT,
    RECONCILIATION_PROVIDER_TIMEOUT_SECONDS,
    BillingState,
    BillingSubscriptionStatus,
    EnumerationObservation,
    EnumerationObservationReason,
    EnumerationPage,
    QuarantineStatus,
    ReconciliationCursorKey,
    ReconciliationKind,
    ReconciliationLease,
    ReconciliationLeaseConflictError,
)
from recognition.tests.unit.test_app1_billing_reconcile import (
    _EntitlementService,
    _Provider,
    _Repository,
    _config,
    _no_sleep,
)
from scripts.billing_reconcile import ReconcileConfig, reconcile

_TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")
_NOW = datetime(2026, 9, 22, 18, 0, tzinfo=UTC)
_SELLER = "org_sandbox"
_POSITION = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)


def _state(
    tenant_id: UUID,
    *,
    customer_id: str = "cus-1",
    subscription_id: str = "sub-1",
    status: BillingSubscriptionStatus = BillingSubscriptionStatus.ACTIVE,
    position: datetime = _POSITION,
) -> BillingState:
    return BillingState(
        tenant_id=tenant_id,
        status=status,
        provider_customer_id=customer_id,
        current_period_end=position + timedelta(days=30),
        past_due_since=None,
        provider_subscription_id=subscription_id,
        event_position=position,
    )


def _page(
    items: tuple[BillingState, ...] = (),
    *,
    next_cursor: str | None = None,
    exhausted: bool = True,
    observations: tuple[EnumerationObservation, ...] = (),
) -> EnumerationPage:
    return EnumerationPage(items, next_cursor, exhausted, observations)


class _Clock:
    def __init__(self, value: datetime = _NOW) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


class _Session:
    def __init__(self) -> None:
        self.in_txn = False
        self.commits = 0
        self.rollbacks = 0

    def mark_write(self) -> None:
        self.in_txn = True

    def in_transaction(self) -> bool:
        return self.in_txn

    async def execute(self, *_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(scalar_one_or_none=lambda: None, scalars=lambda: SimpleNamespace(all=lambda: []))

    async def commit(self) -> None:
        self.commits += 1
        self.in_txn = False

    async def rollback(self) -> None:
        self.rollbacks += 1
        self.in_txn = False


class _Recovery:
    def __init__(self, *, session: _Session | None = None) -> None:
        self.session = session or _Session()
        self.key: ReconciliationCursorKey | None = None
        self.owner = "worker-a"
        self.fence = 0
        self.cursor: str | None = None
        self.exhausted = False
        self.lease_until = _NOW + timedelta(seconds=30)
        self.last_progress_at: datetime | None = None
        self.progress: dict[str, str] = {}
        self.quarantine: dict[str, SimpleNamespace] = {}
        self.acquires: list[object] = []
        self.heartbeats: list[object] = []
        self.completes: list[str] = []
        self.quarantines: list[str] = []
        self.advances: list[dict[str, object]] = []
        self.page_failures: list[str] = []
        self.retries: list[dict[str, str]] = []
        self.durable = False
        self.block_acquire = False
        self.steal_on_heartbeat = False

    def _lease(self) -> ReconciliationLease:
        assert self.key is not None
        return ReconciliationLease(
            key=self.key,
            owner=self.owner,
            fence=self.fence,
            lease_until=self.lease_until,
            cursor=None if self.exhausted else self.cursor,
            last_progress_at=self.last_progress_at,
            exhausted=self.exhausted,
        )

    async def acquire_lease(self, key, *, owner: str, lease_ttl: timedelta, now: datetime):
        self.acquires.append(key)
        if self.block_acquire:
            return None
        self.key = key
        self.owner = owner
        self.fence += 1
        self.lease_until = now + lease_ttl
        self.durable = False
        self.session.mark_write()
        return self._lease()

    async def heartbeat(self, lease, *, now: datetime, lease_ttl: timedelta):
        self.heartbeats.append(lease.fence)
        if self.steal_on_heartbeat or lease.fence != self.fence or now >= self.lease_until:
            raise ReconciliationLeaseConflictError("stale")
        self.lease_until = now + lease_ttl
        self.session.mark_write()
        return self._lease()

    async def complete_item(self, lease, *, remote_id: str, now: datetime) -> None:
        if lease.fence != self.fence or now >= self.lease_until:
            raise ReconciliationLeaseConflictError("stale")
        self.progress[remote_id] = "completed"
        self.completes.append(remote_id)
        self.last_progress_at = now
        self.session.mark_write()

    async def quarantine_item(self, lease, *, observation, now: datetime):
        if lease.fence != self.fence or now >= self.lease_until:
            raise ReconciliationLeaseConflictError("stale")
        record = SimpleNamespace(
            remote_id=observation.remote_id,
            reason=observation.reason,
            status=QuarantineStatus.OPEN,
            operator_identity=None,
            operator_reason=None,
            attempt_count=1,
        )
        self.quarantine[observation.remote_id] = record
        self.progress[observation.remote_id] = "quarantined"
        self.quarantines.append(observation.remote_id)
        self.last_progress_at = now
        self.session.mark_write()
        return record

    async def advance_cursor(
        self,
        lease,
        *,
        next_cursor: str | None,
        exhausted: bool,
        page_remote_ids: tuple[str, ...],
        now: datetime,
    ):
        missing = [item for item in page_remote_ids if item not in self.progress]
        if missing:
            raise RuntimeError(f"unprocessed {missing}")
        self.cursor = next_cursor
        self.exhausted = exhausted
        self.last_progress_at = now
        self.advances.append(
            {"next_cursor": next_cursor, "exhausted": exhausted, "ids": page_remote_ids}
        )
        self.session.mark_write()
        return self._lease()

    async def record_page_failure(self, lease, *, failure_class: str, now: datetime):
        self.page_failures.append(failure_class)
        self.session.mark_write()
        return self._lease()

    async def audited_retry(
        self,
        lease,
        *,
        remote_id: str,
        operator_identity: str,
        operator_reason: str,
        now: datetime,
    ):
        record = self.quarantine[remote_id]
        record.status = QuarantineStatus.RETRY_PENDING
        record.operator_identity = operator_identity
        record.operator_reason = operator_reason
        record.attempt_count += 1
        self.retries.append(
            {
                "remote_id": remote_id,
                "operator_identity": operator_identity,
                "operator_reason": operator_reason,
            }
        )
        self.session.mark_write()
        return record

    async def get_quarantine(self, key, remote_id: str):
        return self.quarantine.get(remote_id)


class _EnumProvider:
    def __init__(self, pages: dict[str | None, EnumerationPage]) -> None:
        self.pages = pages
        self.environment = "sandbox"
        self.seller_account = _SELLER
        self.session: _Session | None = None
        self.enumerate_calls: list[dict[str, object]] = []
        self.retrieve_calls: list[dict[str, object]] = []
        self.checkout_calls: list[dict[str, object]] = []
        self.create_calls: list[dict[str, object]] = []
        self.timeouts = 0

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
                "txn_open": bool(getattr(self.session, "in_txn", False)),
            }
        )
        tenant_id = _TENANT_ID
        return _state(
            tenant_id,
            customer_id=provider_customer_id,
            subscription_id=provider_subscription_id or "sub-1",
        )

    async def retrieve_checkout(self, *, provider_checkout_id: str, request_timeout: float):
        self.checkout_calls.append(
            {
                "id": provider_checkout_id,
                "timeout": request_timeout,
                "txn_open": bool(getattr(self.session, "in_txn", False)),
            }
        )
        return {"id": provider_checkout_id, "status": "open", "url": "https://pay.example/return"}

    async def enumerate_subscriptions(self, *, cursor: str | None, limit: int, request_timeout: float):
        self.enumerate_calls.append(
            {
                "cursor": cursor,
                "limit": limit,
                "timeout": request_timeout,
                "txn_open": bool(getattr(self.session, "in_txn", False)),
            }
        )
        if self.timeouts > 0:
            self.timeouts -= 1
            raise TimeoutError("simulated enumeration timeout")
        return self.pages[cursor]

    async def create_checkout_session(self, **kwargs: object) -> object:
        self.create_calls.append(dict(kwargs))
        raise AssertionError("reconcile must not POST a new checkout")


def _billing_repo(*, tenants: set[UUID] | None = None) -> _Repository:
    repository = _Repository([])
    repository.tenants = tenants or {_TENANT_ID}
    return repository


async def _run_orphans(
    provider: _EnumProvider,
    recovery: _Recovery,
    repository: _Repository,
    **kwargs: object,
):
    provider.session = recovery.session
    repository.session = recovery.session
    return await reconcile(
        repository,
        provider,
        entitlement_service=repository.entitlement_service,
        recovery_repository=recovery,
        config=_config(provider_timeout_s=RECONCILIATION_PROVIDER_TIMEOUT_SECONDS, stall_limit=1),
        clock=_Clock(),
        sleeper=_no_sleep,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_orphan_page_bound_is_50_and_stops_at_20_pages() -> None:
    pages: dict[str | None, EnumerationPage] = {}
    cursor: str | None = None
    for index in range(RECONCILIATION_MAX_PAGES_PER_RUN + 2):
        next_cursor = str(index + 2)
        tenant = _TENANT_ID
        pages[cursor] = _page(
            (_state(tenant, subscription_id=f"sub-{index}", position=_POSITION + timedelta(seconds=index)),),
            next_cursor=next_cursor,
            exhausted=False,
        )
        cursor = next_cursor
    provider = _EnumProvider(pages)
    recovery = _Recovery()
    repository = _billing_repo()

    report = await _run_orphans(provider, recovery, repository)

    assert len(provider.enumerate_calls) == RECONCILIATION_MAX_PAGES_PER_RUN
    assert all(call["limit"] == RECONCILIATION_PAGE_LIMIT for call in provider.enumerate_calls)
    assert recovery.cursor == str(RECONCILIATION_MAX_PAGES_PER_RUN + 1)
    assert recovery.exhausted is False
    assert report.exit_code == 0


@pytest.mark.asyncio
async def test_cursor_resumes_on_the_next_bounded_run() -> None:
    pages: dict[str | None, EnumerationPage] = {}
    cursor: str | None = None
    for index in range(RECONCILIATION_MAX_PAGES_PER_RUN + 1):
        next_cursor = str(index + 2)
        pages[cursor] = _page(
            (_state(_TENANT_ID, subscription_id=f"sub-{index}", position=_POSITION + timedelta(seconds=index)),),
            next_cursor=next_cursor,
            exhausted=index == RECONCILIATION_MAX_PAGES_PER_RUN,
        )
        cursor = next_cursor
    provider = _EnumProvider(pages)
    recovery = _Recovery()
    repository = _billing_repo()

    first = await _run_orphans(provider, recovery, repository)
    assert first.exit_code == 0
    assert len(provider.enumerate_calls) == RECONCILIATION_MAX_PAGES_PER_RUN
    persisted = recovery.cursor
    assert persisted == str(RECONCILIATION_MAX_PAGES_PER_RUN + 1)

    second = await _run_orphans(provider, recovery, repository)
    assert second.exit_code == 0
    assert provider.enumerate_calls[RECONCILIATION_MAX_PAGES_PER_RUN]["cursor"] == persisted


@pytest.mark.asyncio
async def test_orphan_failure_after_an_item_commits_is_unresolved() -> None:
    first = _state(_TENANT_ID, subscription_id="sub-first")
    second = _state(
        _TENANT_ID,
        subscription_id="sub-second",
        position=_POSITION + timedelta(seconds=1),
    )
    provider = _EnumProvider({None: _page((first, second))})
    recovery = _Recovery()
    repository = _billing_repo()
    original_upsert = repository.upsert_projection
    write_count = 0

    async def fail_second_projection_write(**kwargs: object) -> bool:
        nonlocal write_count
        write_count += 1
        if write_count == 2:
            raise RuntimeError("simulated second projection write failure")
        return await original_upsert(**kwargs)

    repository.upsert_projection = fail_second_projection_write

    report = await _run_orphans(provider, recovery, repository)

    assert recovery.completes == ["sub-first"]
    assert report.unresolved_failures > 0
    assert report.exit_code == 1


@pytest.mark.asyncio
async def test_known_projection_scan_rotates_between_bounded_runs(monkeypatch) -> None:
    projection_count = RECONCILIATION_PAGE_LIMIT * RECONCILIATION_MAX_PAGES_PER_RUN + 205
    tenant_ids = [UUID(int=index) for index in range(1, projection_count + 1)]
    repository = _billing_repo(tenants=set(tenant_ids))
    repository.known = [
        SimpleNamespace(
            tenant_id=tenant_id,
            provider="fake",
            provider_customer_id=f"cus-{index}",
            provider_subscription_id=f"sub-{index}",
            status=BillingSubscriptionStatus.ACTIVE.value,
            current_period_end=_POSITION + timedelta(days=30),
            past_due_since=None,
            last_event_id=f"event-{index}",
            updated_at=_POSITION - timedelta(days=1),
            environment="sandbox",
            seller_account=_SELLER,
        )
        for index, tenant_id in enumerate(tenant_ids, start=1)
    ]

    class _ProjectionProvider:
        environment = "sandbox"
        seller_account = _SELLER

        async def retrieve_state(
            self,
            *,
            provider_customer_id: str,
            provider_subscription_id: str | None,
            request_timeout: float,
        ) -> dict[str, object]:
            return {
                "provider_customer_id": provider_customer_id,
                "provider_subscription_id": provider_subscription_id,
                "status": BillingSubscriptionStatus.ACTIVE.value,
                "current_period_end": _POSITION + timedelta(days=30),
                "past_due_since": None,
                "event_position": _POSITION,
            }

    pivots = iter((100, 1000))
    monkeypatch.setattr(billing_reconcile.random, "getrandbits", lambda _bits: next(pivots))
    provider = _ProjectionProvider()

    await reconcile(
        repository,
        provider,
        entitlement_service=repository.entitlement_service,
        config=_config(),
        clock=_Clock(),
        sleeper=_no_sleep,
    )
    first_run = {
        str(claim["remote_id"])
        for claim in repository.claims
        if claim["kind"] == "projection"
    }
    first_run_claim_count = len(repository.claims)

    await reconcile(
        repository,
        provider,
        entitlement_service=repository.entitlement_service,
        config=_config(),
        clock=_Clock(),
        sleeper=_no_sleep,
    )
    second_run = {
        str(claim["remote_id"])
        for claim in repository.claims[first_run_claim_count:]
        if claim["kind"] == "projection"
    }

    assert len(first_run) == RECONCILIATION_PAGE_LIMIT * RECONCILIATION_MAX_PAGES_PER_RUN
    assert second_run != first_run
    assert second_run - first_run


@pytest.mark.asyncio
async def test_next_scan_after_exhaustion_restarts_at_first_page() -> None:
    page = _page((_state(_TENANT_ID, subscription_id="sub-cycle"),), exhausted=True)
    provider = _EnumProvider({None: page})
    recovery = _Recovery()
    recovery.exhausted = True
    recovery.cursor = "99"
    repository = _billing_repo()

    report = await _run_orphans(provider, recovery, repository)

    assert report.exit_code == 0
    assert provider.enumerate_calls[0]["cursor"] is None
    assert recovery.completes == ["sub-cycle"]


@pytest.mark.asyncio
async def test_bad_observation_is_quarantined_without_aborting_good_item() -> None:
    good = _state(_TENANT_ID, subscription_id="sub-good")
    bad = EnumerationObservation(
        reason=EnumerationObservationReason.EMAIL_IDENTITY_REJECTED,
        remote_id="digest:abc",
        details={"identity": "email_identity_rejected"},
    )
    provider = _EnumProvider({None: _page((good,), observations=(bad,))})
    recovery = _Recovery()
    repository = _billing_repo()

    report = await _run_orphans(provider, recovery, repository)

    assert report.exit_code == 0
    assert "sub-good" in recovery.completes
    assert "digest:abc" in recovery.quarantines
    assert repository.upserts
    assert repository.entitlement_service.states


@pytest.mark.asyncio
async def test_orphan_without_local_tenant_mapping_is_quarantined() -> None:
    unknown = uuid4()
    provider = _EnumProvider({None: _page((_state(unknown, subscription_id="sub-unknown"),))})
    recovery = _Recovery()
    repository = _billing_repo(tenants={_TENANT_ID})

    report = await _run_orphans(provider, recovery, repository)

    assert "sub-unknown" in recovery.quarantines
    assert repository.upserts == []
    assert repository.entitlement_service.states == []
    assert report.exit_code == 0


@pytest.mark.asyncio
async def test_null_legacy_projection_is_not_current_namespace_authority() -> None:
    repository = _billing_repo()
    repository.projections[_TENANT_ID] = SimpleNamespace(
        provider="fake",
        provider_customer_id="cus-1",
        provider_subscription_id="sub-legacy",
        status=BillingSubscriptionStatus.ACTIVE.value,
        current_period_end=None,
        past_due_since=None,
        last_event_id="evt-old",
        updated_at=_POSITION,
        environment=None,
        seller_account=None,
        tenant_id=_TENANT_ID,
    )
    provider = _EnumProvider({None: _page((_state(_TENANT_ID, customer_id="cus-other", subscription_id="sub-new"),))})
    recovery = _Recovery()

    await _run_orphans(provider, recovery, repository)

    assert repository.upserts == []
    assert "sub-new" in recovery.quarantines


@pytest.mark.asyncio
async def test_stale_lease_cannot_apply_paid_or_quarantine() -> None:
    provider = _EnumProvider({None: _page((_state(_TENANT_ID, subscription_id="sub-stolen"),))})
    recovery = _Recovery()
    recovery.steal_on_heartbeat = True
    repository = _billing_repo()

    report = await _run_orphans(provider, recovery, repository)

    assert report.exit_code == 1
    assert repository.upserts == []
    assert repository.entitlement_service.states == []
    assert recovery.quarantines == []
    assert recovery.completes == []


@pytest.mark.asyncio
async def test_enumerate_does_not_hold_a_db_transaction() -> None:
    provider = _EnumProvider({None: _page((_state(_TENANT_ID, subscription_id="sub-io"),))})
    recovery = _Recovery()
    repository = _billing_repo()

    await _run_orphans(provider, recovery, repository)

    assert provider.enumerate_calls[0]["txn_open"] is False
    assert recovery.session.commits >= 1
    assert recovery.durable is False or recovery.session.in_txn is False


@pytest.mark.asyncio
async def test_ambiguous_checkout_retrieves_and_never_posts() -> None:
    attempt = SimpleNamespace(
        id=uuid4(),
        tenant_id=_TENANT_ID,
        provider="fake",
        environment="sandbox",
        seller_account=_SELLER,
        status="ambiguous",
        provider_checkout_id="chk-1",
        updated_at=_NOW - timedelta(seconds=30),
    )
    provider = _EnumProvider({None: _page(exhausted=True)})
    recovery = _Recovery()
    repository = _billing_repo()
    transitions: list[str] = []

    class _Attempts:
        async def mark_terminal(self, tenant_id, attempt_id, *, status, last_error_class=None):
            transitions.append(str(status))
            return attempt

        async def mark_ambiguous(self, tenant_id, attempt_id):
            transitions.append("ambiguous")
            return attempt

    report = await reconcile(
        repository,
        provider,
        entitlement_service=repository.entitlement_service,
        recovery_repository=recovery,
        checkout_repository=_Attempts(),
        stale_checkout_attempts=[attempt],
        config=_config(provider_timeout_s=8.0),
        clock=_Clock(),
        sleeper=_no_sleep,
    )

    assert provider.create_calls == []
    assert [call["id"] for call in provider.checkout_calls] == ["chk-1"]
    assert provider.checkout_calls[0]["txn_open"] is False
    assert "succeeded" not in "".join(transitions).lower()
    assert report.exit_code == 0


@pytest.mark.asyncio
async def test_ambiguous_missing_checkout_id_quarantines_without_new_checkout() -> None:
    attempt = SimpleNamespace(
        id=uuid4(),
        tenant_id=_TENANT_ID,
        provider="fake",
        environment="sandbox",
        seller_account=_SELLER,
        status="provider_requested",
        provider_checkout_id=None,
        updated_at=_NOW - timedelta(seconds=30),
    )
    provider = _EnumProvider({None: _page(exhausted=True)})
    recovery = _Recovery()
    repository = _billing_repo()

    await reconcile(
        repository,
        provider,
        recovery_repository=recovery,
        stale_checkout_attempts=[attempt],
        config=_config(),
        clock=_Clock(),
        sleeper=_no_sleep,
    )

    assert provider.create_calls == []
    assert provider.checkout_calls == []
    assert recovery.quarantines


@pytest.mark.asyncio
async def test_redirect_url_is_not_treated_as_paid() -> None:
    attempt = SimpleNamespace(
        id=uuid4(),
        tenant_id=_TENANT_ID,
        provider="fake",
        environment="sandbox",
        seller_account=_SELLER,
        status="ambiguous",
        provider_checkout_id="chk-redirect",
        updated_at=_NOW - timedelta(seconds=30),
    )

    class _RedirectProvider(_EnumProvider):
        async def retrieve_checkout(self, *, provider_checkout_id: str, request_timeout: float):
            await super().retrieve_checkout(
                provider_checkout_id=provider_checkout_id,
                request_timeout=request_timeout,
            )
            return {
                "id": provider_checkout_id,
                "status": "open",
                "success_url": "https://app.example/success",
                "url": "https://pay.example/return",
            }

    provider = _RedirectProvider({None: _page(exhausted=True)})
    recovery = _Recovery()
    repository = _billing_repo()

    await reconcile(
        repository,
        provider,
        entitlement_service=repository.entitlement_service,
        recovery_repository=recovery,
        stale_checkout_attempts=[attempt],
        config=_config(),
        clock=_Clock(),
        sleeper=_no_sleep,
    )

    assert repository.entitlement_service.states == []
    assert repository.upserts == []


@pytest.mark.asyncio
async def test_timeout_with_zero_verified_page_progress_fails_once() -> None:
    provider = _EnumProvider({None: _page(exhausted=True)})
    provider.timeouts = 3
    recovery = _Recovery()
    repository = _billing_repo()

    report = await _run_orphans(provider, recovery, repository)

    assert report.exit_code == 1
    assert recovery.page_failures
    assert recovery.advances == []
    assert recovery.last_progress_at is None


@pytest.mark.asyncio
async def test_exhausted_empty_verified_page_is_healthy() -> None:
    provider = _EnumProvider({None: _page(exhausted=True)})
    recovery = _Recovery()
    repository = _billing_repo()

    report = await _run_orphans(provider, recovery, repository)

    assert report.exit_code == 0
    assert recovery.advances
    assert recovery.advances[0]["exhausted"] is True
    assert recovery.advances[0]["ids"] == ()


@pytest.mark.asyncio
async def test_acquiring_lease_alone_is_not_progress() -> None:
    provider = _EnumProvider({None: _page(exhausted=True)})
    recovery = _Recovery()
    recovery.block_acquire = True
    repository = _billing_repo()

    report = await _run_orphans(provider, recovery, repository)

    assert report.exit_code == 1
    assert provider.enumerate_calls == []
    assert recovery.last_progress_at is None


@pytest.mark.asyncio
async def test_repeated_page_applies_new_event_position_for_renewal() -> None:
    first = _state(_TENANT_ID, subscription_id="sub-renew", position=_POSITION)
    renewed = _state(_TENANT_ID, subscription_id="sub-renew", position=_POSITION + timedelta(days=30))
    provider = _EnumProvider({None: _page((first,), exhausted=True)})
    recovery = _Recovery()
    repository = _billing_repo()

    await _run_orphans(provider, recovery, repository)
    provider.pages[None] = _page((renewed,), exhausted=True)
    recovery.exhausted = True
    await _run_orphans(provider, recovery, repository)

    positions = [upsert["event_position"] for upsert in repository.upserts]
    assert _POSITION in positions
    assert _POSITION + timedelta(days=30) in positions
    event_ids = [upsert["provider_event_id"] for upsert in repository.upserts]
    assert event_ids[0] != event_ids[-1] or positions[0] != positions[-1]


@pytest.mark.asyncio
async def test_audited_retry_records_operator_and_cannot_grant_paid() -> None:
    from scripts.billing_reconcile import audited_retry_quarantine

    recovery = _Recovery()
    recovery.quarantine["sub-q"] = SimpleNamespace(
        remote_id="sub-q",
        status=QuarantineStatus.OPEN,
        operator_identity=None,
        operator_reason=None,
        attempt_count=1,
    )
    entitlement = _EntitlementService()
    report = await audited_retry_quarantine(
        recovery,
        remote_id="sub-q",
        operator_identity="ops@example.test",
        operator_reason="mapped seller confirmed",
        environment="sandbox",
        seller_account=_SELLER,
        dry_run=False,
        clock=_Clock(),
        entitlement_service=entitlement,
    )

    assert recovery.retries[0]["operator_identity"] == "ops@example.test"
    assert recovery.retries[0]["operator_reason"] == "mapped seller confirmed"
    assert entitlement.states == []
    assert report.exit_code == 0


@pytest.mark.asyncio
async def test_audited_retry_defaults_to_dry_run() -> None:
    from scripts.billing_reconcile import audited_retry_quarantine

    recovery = _Recovery()
    recovery.quarantine["sub-q"] = SimpleNamespace(
        remote_id="sub-q",
        status=QuarantineStatus.OPEN,
        attempt_count=1,
        operator_identity=None,
        operator_reason=None,
    )
    report = await audited_retry_quarantine(
        recovery,
        remote_id="sub-q",
        operator_identity="ops@example.test",
        operator_reason="retry",
        environment="sandbox",
        seller_account=_SELLER,
        clock=_Clock(),
    )

    assert recovery.retries == []
    assert report.would_change == 1


def test_retry_cli_requires_operator_identity_reason_and_prints_no_secrets() -> None:
    from scripts import billing_reconcile_retry as retry_cli

    class _Capture:
        def __init__(self) -> None:
            self.err: list[str] = []

        def write(self, text: str) -> int:
            self.err.append(text)
            return len(text)

        def flush(self) -> None:
            return None

    captured = _Capture()
    code = retry_cli.main(
        ["--remote-id", "sub-q", "--environment", "sandbox", "--seller-account", _SELLER],
        stderr=captured,
    )
    joined = "".join(captured.err)
    assert code == 2
    assert "operator" in joined.lower()
    assert "whsec_" not in joined
    assert "polar_access" not in joined.lower()
