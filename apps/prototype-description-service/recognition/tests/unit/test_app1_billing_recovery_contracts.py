"""C0 billing recovery contract tests: signatures, page observations, fencing shape."""

from __future__ import annotations

import inspect
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import Table, UniqueConstraint, create_engine, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from db.base import Base
from db.models.portal_billing import (
    BillingCheckoutAttempt,
    BillingReconciliationCursor,
    BillingReconciliationItemProgress,
    BillingReconciliationQuarantine,
    BillingSubscriptionProjection,
    BillingWebhookInbox,
)
from recognition.domain.portal_contracts import (
    RECONCILIATION_DEFAULT_LEASE_SECONDS,
    RECONCILIATION_PAGE_LIMIT,
    BillingProvider,
    BillingReconciliationRepository,
    EnumerationObservation,
    EnumerationObservationReason,
    EnumerationPage,
    QuarantineStatus,
    ReconciliationCursorAdvanceError,
    ReconciliationCursorKey,
    ReconciliationKind,
    ReconciliationLease,
    ReconciliationLeaseConflictError,
    ReconciliationQuarantineConflictError,
)
from recognition.infrastructure.billing.polar_provider import PolarEnumerationError
from recognition.infrastructure.repositories.billing_reconciliation_repository import (
    BillingReconciliationRepository as ReconciliationRepositoryImpl,
)
from recognition.tests.unit.test_app1_billing_provider import (
    _SELLER_ACCOUNT,
    FakeHttpClient,
    FakeResponse,
    _provider,
)


class _AsyncTransactionFacade:
    def __init__(self, transaction: object) -> None:
        self._transaction = transaction

    async def __aenter__(self) -> _AsyncTransactionFacade:
        self._transaction.__enter__()  # type: ignore[attr-defined]
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        return bool(self._transaction.__exit__(exc_type, exc, traceback))  # type: ignore[attr-defined]


class _AsyncSessionFacade:
    def __init__(self, session: Session) -> None:
        self._session = session

    @property
    def bind(self) -> object:
        return self._session.bind

    def add(self, instance: object) -> None:
        self._session.add(instance)

    async def flush(self) -> None:
        self._session.flush()

    async def execute(self, statement: object) -> object:
        return self._session.execute(statement)

    def begin_nested(self) -> _AsyncTransactionFacade:
        return _AsyncTransactionFacade(self._session.begin_nested())

    async def commit(self) -> None:
        self._session.commit()

    async def rollback(self) -> None:
        self._session.rollback()

    async def close(self) -> None:
        self._session.close()


@pytest_asyncio.fixture
async def recovery_session() -> AsyncGenerator[_AsyncSessionFacade, None]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        tables: list[Table] = [
            BillingReconciliationCursor.__table__,
            BillingReconciliationQuarantine.__table__,
            BillingReconciliationItemProgress.__table__,
        ]
        Base.metadata.create_all(connection, tables=tables)
    session = _AsyncSessionFacade(Session(engine, expire_on_commit=False))
    try:
        yield session
    finally:
        await session.close()
        engine.dispose()


def _key(**overrides: object) -> ReconciliationCursorKey:
    payload: dict[str, object] = {
        "provider": "fake",
        "environment": "sandbox",
        "seller_account": "org_sandbox",
        "kind": ReconciliationKind.SUBSCRIPTIONS,
    }
    payload.update(overrides)
    return ReconciliationCursorKey(**payload)  # type: ignore[arg-type]


def test_billing_provider_checkout_and_enumeration_signatures_are_unchanged() -> None:
    checkout = inspect.signature(BillingProvider.create_checkout_session)
    enumerate_page = inspect.signature(BillingProvider.enumerate_subscriptions)
    retrieve_state = inspect.signature(BillingProvider.retrieve_state)
    retrieve_checkout = inspect.signature(BillingProvider.retrieve_checkout)
    assert list(checkout.parameters) == [
        "self",
        "tenant_id",
        "plan_code",
        "success_url",
        "cancel_url",
        "idempotency_key",
        "attempt_id",
    ]
    assert checkout.parameters["idempotency_key"].kind is inspect.Parameter.KEYWORD_ONLY
    assert list(enumerate_page.parameters) == ["self", "cursor", "limit", "request_timeout"]
    assert list(retrieve_state.parameters) == [
        "self",
        "provider_customer_id",
        "provider_subscription_id",
        "request_timeout",
    ]
    assert list(retrieve_checkout.parameters) == ["self", "provider_checkout_id", "request_timeout"]


def test_reconciliation_repository_protocol_owns_short_transactions() -> None:
    acquire = inspect.signature(BillingReconciliationRepository.acquire_lease)
    advance = inspect.signature(BillingReconciliationRepository.advance_cursor)
    retry = inspect.signature(BillingReconciliationRepository.audited_retry)
    assert acquire.parameters["lease_ttl"].kind is inspect.Parameter.KEYWORD_ONLY
    assert "page_remote_ids" in advance.parameters
    assert "operator_identity" in retry.parameters
    assert "operator_reason" in retry.parameters
    assert RECONCILIATION_PAGE_LIMIT == 50
    assert RECONCILIATION_DEFAULT_LEASE_SECONDS == 30


def test_cursor_kind_excludes_known_inbox_and_is_not_a_tenant() -> None:
    assert {member.value for member in ReconciliationKind} == {"subscriptions", "ambiguous_checkouts"}
    key = _key()
    assert not hasattr(key, "tenant_id")
    with pytest.raises(ValueError, match="kind"):
        ReconciliationCursorKey(
            provider="fake",
            environment="sandbox",
            seller_account="org",
            kind="inbox",  # type: ignore[arg-type]
        )


def test_enumeration_page_construction_compat_defaults_empty_observations() -> None:
    page = EnumerationPage(items=(), next_cursor="2", exhausted=False)
    assert page.observations == ()
    observation = EnumerationObservation(
        reason=EnumerationObservationReason.SELLER_MISMATCH,
        remote_id="sub-foreign",
        details={"organization_id": "org-other"},
    )
    observed = EnumerationPage(items=(), next_cursor=None, exhausted=True, observations=(observation,))
    assert observed.observations[0].remote_id == "sub-foreign"
    with pytest.raises(ValueError, match="payload|details|length"):
        EnumerationObservation(
            reason=EnumerationObservationReason.MALFORMED_ITEM,
            remote_id="x",
            details={"body": "secret-payload-copy-that-is-far-too-long-" + ("x" * 200)},
        )


def test_namespace_columns_are_nullable_and_non_authoritative_on_legacy_tables() -> None:
    inbox_env = BillingWebhookInbox.__table__.c.environment
    inbox_seller = BillingWebhookInbox.__table__.c.seller_account
    projection_env = BillingSubscriptionProjection.__table__.c.environment
    projection_seller = BillingSubscriptionProjection.__table__.c.seller_account
    assert inbox_env.nullable is True
    assert inbox_seller.nullable is True
    assert projection_env.nullable is True
    assert projection_seller.nullable is True
    inbox_uniques = [
        tuple(column.name for column in constraint.columns)
        for constraint in BillingWebhookInbox.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    ]
    projection_uniques = [
        tuple(column.name for column in constraint.columns)
        for constraint in BillingSubscriptionProjection.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    ]
    assert ("provider", "environment", "seller_account", "provider_event_id") in inbox_uniques
    assert ("provider", "environment", "seller_account", "provider_customer_id") in projection_uniques


def test_recovery_tables_use_seller_wide_keys_not_tenant_id() -> None:
    cursor_pk = tuple(column.name for column in BillingReconciliationCursor.__table__.primary_key.columns)
    assert cursor_pk == ("provider", "environment", "seller_account", "kind")
    assert "tenant_id" not in BillingReconciliationCursor.__table__.c
    assert "tenant_id" not in BillingReconciliationQuarantine.__table__.c
    quarantine_uniques = [
        tuple(column.name for column in constraint.columns)
        for constraint in BillingReconciliationQuarantine.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    ]
    assert (
        "provider",
        "environment",
        "seller_account",
        "kind",
        "remote_id",
    ) in quarantine_uniques


def test_migration_lists_recovery_tables_and_preserves_usage_drain_helpers() -> None:
    import importlib

    migration = importlib.import_module("db.migrations.versions.001_identity_schema")
    for table in (
        "billing_reconciliation_cursor",
        "billing_reconciliation_quarantine",
        "billing_reconciliation_item_progress",
    ):
        assert table in migration.EXPECTED_SCHEMA_TABLES
        assert table in migration.DOWNGRADE_TABLE_ORDER
        assert table not in migration.TENANT_TABLES
        assert table in migration.OPERATOR_SCOPE_TABLES
    assert migration.USAGE_SCHEMA_WRITERS_DRAINED_ENV == "ACX_USAGE_SCHEMA_WRITERS_DRAINED"
    assert callable(migration._heal_portal_tenant_invitation_tenant_nullable)
    assert callable(migration._refuse_undrained_existing_usage_upgrade)


@pytest.mark.asyncio
async def test_enumerate_page_exposes_quarantine_observations_without_email_tenant() -> None:
    tenant_id = uuid4()
    client = FakeHttpClient(
        FakeResponse({"url": "unused"}),
        get_response=FakeResponse(
            {
                "items": [
                    {
                        "id": "sub-ok",
                        "customer_id": "cus-ok",
                        "status": "active",
                        "current_period_end": "2026-10-20T12:00:00Z",
                        "modified_at": "2026-09-20T12:00:00Z",
                        "customer": {
                            "id": "cus-ok",
                            "external_id": f"sandbox:{tenant_id}",
                            "email": "ignored@example.test",
                            "organization_id": _SELLER_ACCOUNT,
                        },
                    },
                    {
                        "id": "sub-foreign-org",
                        "customer_id": "cus-foreign",
                        "status": "active",
                        "current_period_end": "2026-10-20T12:00:00Z",
                        "modified_at": "2026-09-20T12:00:00Z",
                        "customer": {
                            "id": "cus-foreign",
                            "external_id": f"sandbox:{uuid4()}",
                            "email": "attacker@example.test",
                            "organization_id": "org-other-seller",
                        },
                    },
                    {
                        "id": "sub-email-only",
                        "customer_id": "cus-email",
                        "status": "active",
                        "current_period_end": "2026-10-20T12:00:00Z",
                        "modified_at": "2026-09-20T12:00:00Z",
                        "customer": {
                            "id": "cus-email",
                            "email": str(tenant_id) + "@example.test",
                            "organization_id": _SELLER_ACCOUNT,
                        },
                    },
                    "not-an-object",
                    {
                        "customer_id": "cus-no-id",
                        "status": "active",
                        "current_period_end": "2026-10-20T12:00:00Z",
                        "modified_at": "2026-09-20T12:00:00Z",
                        "customer": {
                            "external_id": f"sandbox:{uuid4()}",
                            "organization_id": _SELLER_ACCOUNT,
                        },
                    },
                ],
                "pagination": {"total_count": 5, "max_page": 1},
            }
        ),
    )
    provider = _provider(client)

    page = await provider.enumerate_subscriptions(cursor=None, limit=50, request_timeout=2.0)

    assert isinstance(page, EnumerationPage)
    assert len(page.items) == 1
    assert page.items[0].tenant_id == tenant_id
    assert page.exhausted is True
    reasons = {observation.reason: observation for observation in page.observations}
    assert EnumerationObservationReason.SELLER_MISMATCH in reasons
    assert EnumerationObservationReason.EMAIL_IDENTITY_REJECTED in reasons
    assert EnumerationObservationReason.MALFORMED_ITEM in reasons
    assert EnumerationObservationReason.MISSING_REMOTE_ID in reasons
    digest = reasons[EnumerationObservationReason.MISSING_REMOTE_ID].remote_id
    assert digest.startswith("digest:")
    assert "attacker@example.test" not in str(page.observations)
    assert "ignored@example.test" not in str(page.observations)
    assert not any("@" in observation.remote_id for observation in page.observations)


@pytest.mark.asyncio
async def test_enumerate_oversized_or_malformed_page_fails_closed() -> None:
    oversized = FakeHttpClient(
        FakeResponse({"url": "unused"}),
        get_response=FakeResponse(
            {
                "items": [
                    {
                        "id": f"sub-{index}",
                        "customer_id": f"cus-{index}",
                        "status": "active",
                        "current_period_end": "2026-10-20T12:00:00Z",
                        "modified_at": "2026-09-20T12:00:00Z",
                        "customer": {
                            "id": f"cus-{index}",
                            "external_id": f"sandbox:{uuid4()}",
                            "organization_id": _SELLER_ACCOUNT,
                        },
                    }
                    for index in range(3)
                ],
                "pagination": {"total_count": 3, "max_page": 1},
            }
        ),
    )
    provider = _provider(oversized)
    with pytest.raises(PolarEnumerationError):
        await provider.enumerate_subscriptions(cursor="1", limit=2, request_timeout=1.0)


@pytest.mark.asyncio
async def test_sqlite_repository_fences_progress_and_refuses_stale_generation(
    recovery_session: _AsyncSessionFacade,
) -> None:
    repo = ReconciliationRepositoryImpl(recovery_session)
    assert isinstance(repo, BillingReconciliationRepository)
    now = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)
    key = _key()
    first = await repo.acquire_lease(key, owner="worker-a", lease_ttl=timedelta(seconds=30), now=now)
    await recovery_session.commit()
    assert first is not None
    assert first.fence == 1
    assert first.owner == "worker-a"

    held = await repo.acquire_lease(key, owner="worker-b", lease_ttl=timedelta(seconds=30), now=now)
    assert held is None

    stolen = await repo.acquire_lease(
        key,
        owner="worker-b",
        lease_ttl=timedelta(seconds=30),
        now=now + timedelta(seconds=31),
    )
    await recovery_session.commit()
    assert stolen is not None
    assert stolen.fence == 2
    assert stolen.owner == "worker-b"

    stale = ReconciliationLease(
        key=first.key,
        owner=first.owner,
        fence=first.fence,
        lease_until=first.lease_until,
        cursor=first.cursor,
        last_progress_at=first.last_progress_at,
        exhausted=first.exhausted,
    )
    with pytest.raises(ReconciliationLeaseConflictError):
        await repo.heartbeat(stale, now=now + timedelta(seconds=32), lease_ttl=timedelta(seconds=30))
    with pytest.raises(ReconciliationLeaseConflictError):
        await repo.complete_item(stale, remote_id="sub-1", now=now + timedelta(seconds=32))

    observation = EnumerationObservation(
        reason=EnumerationObservationReason.SELLER_MISMATCH,
        remote_id="sub-foreign",
        details={"organization_id": "org-other"},
    )
    quarantined = await repo.quarantine_item(stolen, observation=observation, now=now + timedelta(seconds=32))
    await repo.complete_item(stolen, remote_id="sub-ok", now=now + timedelta(seconds=32))
    advanced = await repo.advance_cursor(
        stolen,
        next_cursor="2",
        exhausted=False,
        page_remote_ids=("sub-ok", "sub-foreign"),
        now=now + timedelta(seconds=32),
    )
    await recovery_session.commit()
    assert quarantined.status is QuarantineStatus.OPEN
    assert advanced.cursor == "2"
    assert advanced.last_progress_at is not None

    with pytest.raises(ReconciliationCursorAdvanceError):
        await repo.advance_cursor(
            stolen,
            next_cursor="3",
            exhausted=False,
            page_remote_ids=("sub-ok", "sub-unprocessed"),
            now=now + timedelta(seconds=33),
        )

    await repo.complete_item(stolen, remote_id="sub-ok", now=now + timedelta(seconds=33))
    retry = await repo.audited_retry(
        stolen,
        remote_id="sub-foreign",
        operator_identity="operator@example.test",
        operator_reason="verified seller mapping",
        now=now + timedelta(seconds=33),
    )
    loaded = await repo.get_quarantine(key, "sub-foreign")
    await recovery_session.commit()
    assert retry.status is QuarantineStatus.RETRY_PENDING
    assert loaded is not None
    assert loaded.operator_identity == "operator@example.test"
    assert loaded.attempt_count == 2
    assert getattr(loaded, "mapped_tenant_id", None) is None
    assert getattr(retry, "tenant_id", None) is None


@pytest.mark.asyncio
async def test_acquire_rollback_does_not_leave_a_lease(recovery_session: _AsyncSessionFacade) -> None:
    repo = ReconciliationRepositoryImpl(recovery_session)
    now = datetime(2026, 9, 22, 13, 0, tzinfo=UTC)
    key = _key(kind=ReconciliationKind.AMBIGUOUS_CHECKOUTS)
    first = await repo.acquire_lease(key, owner="worker-a", lease_ttl=timedelta(seconds=30), now=now)
    assert first is not None
    await recovery_session.rollback()
    second = await repo.acquire_lease(key, owner="worker-b", lease_ttl=timedelta(seconds=30), now=now)
    await recovery_session.commit()
    assert second is not None
    assert second.owner == "worker-b"
    assert second.fence == 1


def test_sqlite_schema_creates_recovery_uniques(recovery_session: _AsyncSessionFacade) -> None:
    inspector = sa_inspect(recovery_session.bind)
    cursor_pk = inspector.get_pk_constraint("billing_reconciliation_cursor")
    assert cursor_pk["constrained_columns"] == ["provider", "environment", "seller_account", "kind"]


async def _progress_row(session: _AsyncSessionFacade, remote_id: str) -> BillingReconciliationItemProgress:
    result = await session.execute(
        select(BillingReconciliationItemProgress).where(BillingReconciliationItemProgress.remote_id == remote_id)
    )
    row = result.scalar_one_or_none()
    assert row is not None
    return row


@pytest.mark.asyncio
async def test_audited_retry_rejects_resolved_and_repeated_retry(
    recovery_session: _AsyncSessionFacade,
) -> None:
    repo = ReconciliationRepositoryImpl(recovery_session)
    now = datetime(2026, 9, 22, 14, 0, tzinfo=UTC)
    key = _key(seller_account="org_retry")
    lease = await repo.acquire_lease(key, owner="worker-a", lease_ttl=timedelta(seconds=30), now=now)
    await recovery_session.commit()
    assert lease is not None
    observation = EnumerationObservation(
        reason=EnumerationObservationReason.SELLER_MISMATCH,
        remote_id="sub-retry",
        details={"organization_id": "org-other"},
    )
    await repo.quarantine_item(lease, observation=observation, now=now + timedelta(seconds=1))
    first = await repo.audited_retry(
        lease,
        remote_id="sub-retry",
        operator_identity="ops-1",
        operator_reason="retry once",
        now=now + timedelta(seconds=2),
    )
    await recovery_session.commit()
    assert first.status is QuarantineStatus.RETRY_PENDING
    assert first.attempt_count == 2

    with pytest.raises(ReconciliationQuarantineConflictError, match="retry"):
        await repo.audited_retry(
            lease,
            remote_id="sub-retry",
            operator_identity="ops-1",
            operator_reason="retry again",
            now=now + timedelta(seconds=3),
        )
    loaded = await repo.get_quarantine(key, "sub-retry")
    assert loaded is not None
    assert loaded.status is QuarantineStatus.RETRY_PENDING
    assert loaded.attempt_count == 2

    await repo.complete_item(lease, remote_id="sub-retry", now=now + timedelta(seconds=4))
    await recovery_session.commit()
    resolved = await repo.get_quarantine(key, "sub-retry")
    assert resolved is not None
    assert resolved.status is QuarantineStatus.RESOLVED
    assert resolved.attempt_count == 2
    assert (await _progress_row(recovery_session, "sub-retry")).status == "completed"

    with pytest.raises(ReconciliationQuarantineConflictError, match="retry"):
        await repo.audited_retry(
            lease,
            remote_id="sub-retry",
            operator_identity="ops-1",
            operator_reason="reopen resolved",
            now=now + timedelta(seconds=5),
        )
    still = await repo.get_quarantine(key, "sub-retry")
    assert still is not None
    assert still.status is QuarantineStatus.RESOLVED
    assert still.attempt_count == 2


@pytest.mark.asyncio
async def test_complete_item_after_retry_is_fenced_and_atomic(
    recovery_session: _AsyncSessionFacade,
) -> None:
    repo = ReconciliationRepositoryImpl(recovery_session)
    now = datetime(2026, 9, 22, 14, 30, tzinfo=UTC)
    key = _key(seller_account="org_complete")
    first = await repo.acquire_lease(key, owner="worker-a", lease_ttl=timedelta(seconds=30), now=now)
    await recovery_session.commit()
    assert first is not None
    await repo.quarantine_item(
        first,
        observation=EnumerationObservation(
            reason=EnumerationObservationReason.ENVIRONMENT_MISMATCH,
            remote_id="sub-fenced",
            details={"environment": "live"},
        ),
        now=now + timedelta(seconds=1),
    )
    await repo.audited_retry(
        first,
        remote_id="sub-fenced",
        operator_identity="ops-2",
        operator_reason="operator verified",
        now=now + timedelta(seconds=2),
    )
    await recovery_session.commit()
    assert (await _progress_row(recovery_session, "sub-fenced")).status == "quarantined"

    stolen = await repo.acquire_lease(
        key,
        owner="worker-b",
        lease_ttl=timedelta(seconds=30),
        now=now + timedelta(seconds=31),
    )
    await recovery_session.commit()
    assert stolen is not None
    assert stolen.fence == 2

    with pytest.raises(ReconciliationLeaseConflictError):
        await repo.complete_item(first, remote_id="sub-fenced", now=now + timedelta(seconds=32))
    stale = await repo.get_quarantine(key, "sub-fenced")
    assert stale is not None
    assert stale.status is QuarantineStatus.RETRY_PENDING
    assert (await _progress_row(recovery_session, "sub-fenced")).status == "quarantined"

    await repo.complete_item(stolen, remote_id="sub-fenced", now=now + timedelta(seconds=32))
    await repo.complete_item(stolen, remote_id="sub-fenced", now=now + timedelta(seconds=33))
    await recovery_session.commit()
    resolved = await repo.get_quarantine(key, "sub-fenced")
    assert resolved is not None
    assert resolved.status is QuarantineStatus.RESOLVED
    assert resolved.attempt_count == 2
    progress = await _progress_row(recovery_session, "sub-fenced")
    assert progress.status == "completed"
    assert progress.fence == stolen.fence
