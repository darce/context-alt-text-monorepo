"""SQLAlchemy persistence for verified billing events and their projection."""

from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import BillingSubscriptionProjection, BillingWebhookInbox
from db.models.portal_billing import BillingKnownItemLease
from db.tenant_context import (
    clear_tenant_context,
    disable_rls_bypass,
    enable_rls_bypass,
    set_tenant_context,
)
from recognition.application.scan.retry_backoff import compute_retry_backoff
from recognition.domain.billing_work_lease import (
    BillingNamespaceConflictError,
    BillingNamespaceRequiredError,
    BillingWorkKind,
    BillingWorkLease,
    BillingWorkLeaseConflictError,
)
from recognition.domain.portal_contracts import (
    RECONCILIATION_MAX_OWNER_LENGTH,
    RECONCILIATION_MAX_REMOTE_ID_LENGTH,
    BillingSubscriptionStatus,
    WebhookInboxStatus,
)
from recognition.shared.db.dialect import is_postgres, is_sqlite

logger = logging.getLogger(__name__)

DEFAULT_WEBHOOK_MAX_ATTEMPTS = 5
DEFAULT_WEBHOOK_RETRY_BACKOFF_BASE_SECONDS = 2.0
DEFAULT_WEBHOOK_RETRY_BACKOFF_MAX_SECONDS = 60.0


class BillingRepository:
    """Persist the durable webhook inbox and one subscription row per tenant.

    The repository does not commit.  Callers choose the transaction boundary;
    methods use savepoints around idempotent inserts so a duplicate delivery or
    a rejected projection cannot poison the caller's transaction.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        environment: str | None = None,
        seller_account: str | None = None,
        max_attempts: int = DEFAULT_WEBHOOK_MAX_ATTEMPTS,
        retry_backoff_base_s: float = DEFAULT_WEBHOOK_RETRY_BACKOFF_BASE_SECONDS,
        retry_backoff_max_s: float = DEFAULT_WEBHOOK_RETRY_BACKOFF_MAX_SECONDS,
    ) -> None:
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 1:
            raise ValueError("max_attempts must be a positive integer")
        if retry_backoff_base_s < 0 or retry_backoff_max_s < 0:
            raise ValueError("retry backoff values must be non-negative")
        if retry_backoff_base_s > retry_backoff_max_s:
            raise ValueError("retry_backoff_base_s must not exceed retry_backoff_max_s")
        if environment is not None:
            if not isinstance(environment, str) or environment.strip() not in {"sandbox", "live"}:
                raise ValueError("environment must be sandbox or live")
            environment = environment.strip()
        if seller_account is not None:
            if not isinstance(seller_account, str) or not seller_account.strip():
                raise ValueError("seller_account must be a non-empty string")
            seller_account = seller_account.strip()
        if (environment is None) ^ (seller_account is None):
            raise ValueError("environment and seller_account must both be configured")
        self._session = session
        self._environment = environment
        self._seller_account = seller_account
        self._max_attempts = max_attempts
        self._retry_backoff_base_s = retry_backoff_base_s
        self._retry_backoff_max_s = retry_backoff_max_s

    def _is_bound(self) -> bool:
        return self._environment is not None and self._seller_account is not None

    def _require_namespace(self) -> tuple[str, str]:
        if not self._is_bound() or self._environment is None or self._seller_account is None:
            raise BillingNamespaceRequiredError(
                "bound billing operations require explicit environment and seller_account"
            )
        return self._environment, self._seller_account

    @property
    def session(self) -> AsyncSession:
        return self._session

    async def get_projection(
        self,
        tenant_id: UUID,
        *,
        provider: str | None = None,
    ) -> BillingSubscriptionProjection | None:
        _validate_uuid("tenant_id", tenant_id)
        if provider is not None:
            _validate_non_empty("provider", provider)

        statement = select(BillingSubscriptionProjection).where(
            BillingSubscriptionProjection.tenant_id == tenant_id,
        )
        if provider is not None:
            statement = statement.where(BillingSubscriptionProjection.provider == provider)
        if self._is_bound():
            statement = statement.where(
                BillingSubscriptionProjection.environment == self._environment,
                BillingSubscriptionProjection.seller_account == self._seller_account,
            )
        # tenant_id is unique, but keep the result bounded for defense in depth.
        statement = statement.limit(1)
        # WHY: projection rows are tenant-scoped FORCE-RLS data, so every read
        # must establish the requested tenant context for this statement.
        async with self._tenant_context(tenant_id):
            result = await self._session.execute(statement)
            return result.scalar_one_or_none()

    async def get_webhook(
        self,
        *,
        provider: str,
        provider_event_id: str,
    ) -> BillingWebhookInbox | None:
        _validate_non_empty("provider", provider)
        _validate_non_empty("provider_event_id", provider_event_id)
        statement = (
            select(BillingWebhookInbox)
            .where(
                BillingWebhookInbox.provider == provider,
                BillingWebhookInbox.provider_event_id == provider_event_id,
            )
            .limit(1)
        )
        if self._is_bound():
            statement = statement.where(
                BillingWebhookInbox.environment == self._environment,
                BillingWebhookInbox.seller_account == self._seller_account,
            )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def record_webhook(
        self,
        *,
        provider: str,
        provider_event_id: str,
        event_type: str,
        signature_verified: bool,
        payload: Mapping[str, object],
    ) -> bool:
        """Insert one verified event and return ``False`` for redelivery.

        Signature verification is deliberately a precondition.  A webhook's
        arrival cannot authorize a tenant or enter the durable processing queue.
        """
        _validate_non_empty("provider", provider)
        _validate_non_empty("provider_event_id", provider_event_id)
        _validate_non_empty("event_type", event_type)
        if signature_verified is not True:
            raise PermissionError("only a verified webhook may enter the inbox")
        if not isinstance(payload, Mapping):
            raise ValueError("payload must be a mapping")
        environment, seller_account = self._require_namespace()

        existing = await self.get_webhook(provider=provider, provider_event_id=provider_event_id)
        if existing is not None:
            return False
        row = BillingWebhookInbox(
            provider=provider,
            provider_event_id=provider_event_id,
            event_type=event_type,
            signature_verified=True,
            payload=dict(payload),
            status=WebhookInboxStatus.RECEIVED.value,
            environment=environment,
            seller_account=seller_account,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(row)
                await self._session.flush()
        except IntegrityError:
            existing = await self.get_webhook(provider=provider, provider_event_id=provider_event_id)
            if existing is None:
                raise
            return False
        return True

    async def upsert_projection(
        self,
        *,
        tenant_id: UUID,
        provider: str,
        provider_customer_id: str,
        provider_subscription_id: str | None,
        status: BillingSubscriptionStatus | str,
        current_period_end: datetime | None,
        past_due_since: datetime | None,
        provider_event_id: str,
        event_position: datetime | str,
    ) -> bool:
        """Apply a newer event position and report whether it was applied."""
        _validate_uuid("tenant_id", tenant_id)
        _validate_non_empty("provider", provider)
        _validate_non_empty("provider_customer_id", provider_customer_id)
        if provider_subscription_id is not None:
            _validate_non_empty("provider_subscription_id", provider_subscription_id)
        _validate_non_empty("provider_event_id", provider_event_id)
        normalized_status = _coerce_subscription_status(status)
        normalized_position = _coerce_position(event_position, "event_position")
        normalized_period_end = _coerce_optional_datetime(current_period_end, "current_period_end")
        normalized_past_due_since = _coerce_optional_datetime(past_due_since, "past_due_since")
        self._require_namespace()

        # WHY: the projection has one row per tenant and is FORCE-RLS protected;
        # keep its read/compare/write sequence inside one tenant context.
        async with self._tenant_context(tenant_id):
            try:
                async with self._session.begin_nested():
                    return await self._upsert_projection(
                        tenant_id=tenant_id,
                        provider=provider,
                        provider_customer_id=provider_customer_id,
                        provider_subscription_id=provider_subscription_id,
                        status=normalized_status,
                        current_period_end=normalized_period_end,
                        past_due_since=normalized_past_due_since,
                        provider_event_id=provider_event_id,
                        event_position=normalized_position,
                    )
            except IntegrityError:
                if self._is_bound():
                    raise BillingNamespaceConflictError(
                        "projection customer is already bound in this billing namespace"
                    ) from None
                return False

    async def _upsert_projection(
        self,
        *,
        tenant_id: UUID,
        provider: str,
        provider_customer_id: str,
        provider_subscription_id: str | None,
        status: BillingSubscriptionStatus,
        current_period_end: datetime | None,
        past_due_since: datetime | None,
        provider_event_id: str,
        event_position: datetime,
    ) -> bool:
        # The projection has one row per tenant.  Lock the row where supported
        # (PostgreSQL) and retain the same compare-before-write behavior on SQLite.
        statement = (
            select(BillingSubscriptionProjection)
            .where(BillingSubscriptionProjection.tenant_id == tenant_id)
            .limit(1)
            .with_for_update()
        )
        result = await self._session.execute(statement)
        projection = result.scalar_one_or_none()

        if projection is not None:
            if projection.provider != provider:
                raise ValueError("tenant projection is owned by another provider")
            if self._is_bound():
                existing_env = projection.environment
                existing_seller = projection.seller_account
                if existing_env is None or existing_seller is None:
                    raise BillingNamespaceConflictError("tenant projection has unmapped legacy namespace")
                if existing_env != self._environment or existing_seller != self._seller_account:
                    raise BillingNamespaceConflictError("tenant projection is owned by another billing namespace")
            if projection.last_event_id == provider_event_id:
                return False
            stored_position = _coerce_position(projection.updated_at, "projection.updated_at")
            if projection.last_event_id is not None and event_position <= stored_position:
                return False

            projection.provider_customer_id = provider_customer_id
            projection.provider_subscription_id = provider_subscription_id
            projection.status = status.value
            projection.current_period_end = current_period_end
            projection.past_due_since = past_due_since
            projection.last_event_id = provider_event_id
            # ``updated_at`` is the model's stored event position.  It is set
            # explicitly because the foundation model has no separate cursor.
            projection.updated_at = event_position
            projection.environment = self._environment
            projection.seller_account = self._seller_account
            await self._session.flush()
            return True

        projection = BillingSubscriptionProjection(
            tenant_id=tenant_id,
            provider=provider,
            provider_customer_id=provider_customer_id,
            provider_subscription_id=provider_subscription_id,
            status=status.value,
            current_period_end=current_period_end,
            past_due_since=past_due_since,
            last_event_id=provider_event_id,
            updated_at=event_position,
            environment=self._environment,
            seller_account=self._seller_account,
        )
        self._session.add(projection)
        await self._session.flush()
        return True

    async def record_subscription_event(
        self,
        *,
        tenant_id: UUID,
        provider: str,
        provider_event_id: str,
        event_type: str,
        signature_verified: bool,
        payload: Mapping[str, object],
        provider_customer_id: str,
        provider_subscription_id: str | None,
        status: BillingSubscriptionStatus | str,
        current_period_end: datetime | None,
        past_due_since: datetime | None,
        event_position: datetime | str,
    ) -> bool:
        """Atomically record a verified event and apply its projection update."""
        async with self._session.begin_nested():
            inserted = await self.record_webhook(
                provider=provider,
                provider_event_id=provider_event_id,
                event_type=event_type,
                signature_verified=signature_verified,
                payload=payload,
            )
            if not inserted:
                return False
            return await self.upsert_projection(
                tenant_id=tenant_id,
                provider=provider,
                provider_customer_id=provider_customer_id,
                provider_subscription_id=provider_subscription_id,
                status=status,
                current_period_end=current_period_end,
                past_due_since=past_due_since,
                provider_event_id=provider_event_id,
                event_position=event_position,
            )

    async def mark_webhook_processed(
        self,
        *,
        provider: str,
        provider_event_id: str,
        status: WebhookInboxStatus | str = WebhookInboxStatus.PROCESSED,
        processed_at: datetime | None = None,
    ) -> bool:
        """Advance an inbox row using only the published status vocabulary."""
        _validate_non_empty("provider", provider)
        _validate_non_empty("provider_event_id", provider_event_id)
        self._require_namespace()
        normalized_status = _coerce_inbox_status(status)
        row = await self.get_webhook(provider=provider, provider_event_id=provider_event_id)
        if row is None:
            return False

        attempts = int(row.attempts or 0) + 1
        row.attempts = attempts
        if normalized_status is WebhookInboxStatus.PROCESSED:
            row.processed_at = _coerce_optional_datetime(processed_at, "processed_at") or datetime.now(UTC)
            row.status = normalized_status.value
            row.next_attempt_at = None
            row.quarantined_at = None
        elif normalized_status is WebhookInboxStatus.FAILED:
            failure_at = _coerce_optional_datetime(processed_at, "processed_at") or datetime.now(UTC)
            if attempts >= self._max_attempts:
                row.status = WebhookInboxStatus.DISCARDED.value
                row.next_attempt_at = None
                row.quarantined_at = failure_at
            else:
                row.status = normalized_status.value
                row.next_attempt_at = failure_at + compute_retry_backoff(
                    attempts,
                    base_seconds=self._retry_backoff_base_s,
                    max_seconds=self._retry_backoff_max_s,
                )
                row.quarantined_at = None
        elif normalized_status is WebhookInboxStatus.DISCARDED:
            row.status = normalized_status.value
            row.next_attempt_at = None
            row.quarantined_at = _coerce_optional_datetime(processed_at, "processed_at") or datetime.now(UTC)
        else:
            row.status = normalized_status.value
            row.next_attempt_at = None
            row.quarantined_at = None
        await self._session.flush()
        return True

    async def list_pending_webhooks(self, *, limit: int = 100) -> list[BillingWebhookInbox]:
        """Return a bounded batch for a later reconciliation worker."""
        if isinstance(limit, bool) or not isinstance(limit, int) or not 0 < limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        environment, seller_account = self._require_namespace()
        statement = (
            select(BillingWebhookInbox)
            .where(BillingWebhookInbox.status.in_([WebhookInboxStatus.RECEIVED.value, WebhookInboxStatus.FAILED.value]))
            .where(BillingWebhookInbox.attempts < self._max_attempts)
            .where(
                BillingWebhookInbox.next_attempt_at.is_(None)
                | (BillingWebhookInbox.next_attempt_at <= datetime.now(UTC))
            )
            .order_by(BillingWebhookInbox.received_at, BillingWebhookInbox.id)
            .limit(limit)
        )
        statement = statement.where(
            BillingWebhookInbox.environment == environment,
            BillingWebhookInbox.seller_account == seller_account,
        )
        # WHY: the worker scan intentionally spans tenants because inbox rows
        # have no tenant key; use the approved maintenance bypass only around
        # this bounded read and always release it on success or failure.
        async with self._maintenance_rls_bypass():
            result = await self._session.execute(statement)
            return list(result.scalars().all())

    async def list_known_projections(
        self,
        *,
        provider: str,
        limit: int,
        after_tenant_id: UUID | None = None,
    ) -> list[BillingSubscriptionProjection]:
        """Return a bounded, namespace-bound page of known projections in UUID order.

        NULL-legacy rows are not current authority and are never returned.
        """
        environment, seller_account = self._require_namespace()
        _validate_non_empty("provider", provider)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 0 < limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        if after_tenant_id is not None:
            _validate_uuid("after_tenant_id", after_tenant_id)
        statement = (
            select(BillingSubscriptionProjection)
            .where(
                BillingSubscriptionProjection.provider == provider,
                BillingSubscriptionProjection.environment == environment,
                BillingSubscriptionProjection.seller_account == seller_account,
            )
            .order_by(BillingSubscriptionProjection.tenant_id)
            .limit(limit)
        )
        if after_tenant_id is not None:
            statement = statement.where(BillingSubscriptionProjection.tenant_id > after_tenant_id)
        async with self._maintenance_rls_bypass():
            result = await self._session.execute(statement)
            return list(result.scalars().all())

    async def claim_reconcile_item(
        self,
        *,
        provider: str,
        kind: str,
        remote_id: str,
        owner: str,
        lease_ttl: timedelta,
        now: datetime,
    ) -> BillingWorkLease | None:
        """Acquire a fenced item lease. Caller must COMMIT before any provider GET."""
        environment, seller_account = self._require_namespace()
        _validate_non_empty("provider", provider)
        kind_value = _coerce_work_kind(kind)
        remote_id = _bounded_text("remote_id", remote_id, RECONCILIATION_MAX_REMOTE_ID_LENGTH)
        owner = _bounded_text("owner", owner, RECONCILIATION_MAX_OWNER_LENGTH)
        now = _require_aware(now)
        until = now + _require_ttl(lease_ttl)
        async with self._operator_scope():
            await self._ensure_known_item_row(
                provider=provider,
                environment=environment,
                seller_account=seller_account,
                kind=kind_value,
                remote_id=remote_id,
                now=now,
            )
            row = await self._claim_known_item_row(
                provider=provider,
                environment=environment,
                seller_account=seller_account,
                kind=kind_value,
                remote_id=remote_id,
                owner=owner,
                until=until,
                now=now,
            )
            if row is None:
                return None
            return _lease_from_row(row)

    async def lock_reconcile_item(self, lease: object, *, now: datetime) -> None:
        """Lock the leased row and reject stale/stolen/expired fences.

        The row lock is held through later projection/entitlement/inbox writes
        in the same database transaction. Does not mark the inbox processed.
        """
        async with self._operator_scope():
            now = _require_aware(now)
            bound = _coerce_lease(lease)
            environment, seller_account = self._require_namespace()
            if bound.environment != environment or bound.seller_account != seller_account:
                raise BillingWorkLeaseConflictError("lease namespace does not match the bound repository")
            statement = (
                select(BillingKnownItemLease)
                .where(*_lease_identity(bound))
                .where(
                    BillingKnownItemLease.lease_owner == bound.owner,
                    BillingKnownItemLease.fence == bound.fence,
                    BillingKnownItemLease.lease_until.is_not(None),
                    BillingKnownItemLease.lease_until > now,
                )
                .limit(1)
                .with_for_update()
            )
            result = await self._session.execute(statement)
            if result.scalar_one_or_none() is None:
                raise BillingWorkLeaseConflictError("billing work lease is expired, stolen, or stale")

    async def finish_reconcile_item(self, lease: object, *, now: datetime) -> None:
        """Release a live fenced lease. Never marks inbox processed."""
        async with self._operator_scope():
            now = _require_aware(now)
            bound = _coerce_lease(lease)
            environment, seller_account = self._require_namespace()
            if bound.environment != environment or bound.seller_account != seller_account:
                raise BillingWorkLeaseConflictError("lease namespace does not match the bound repository")
            stmt = (
                update(BillingKnownItemLease)
                .where(*_lease_identity(bound))
                .where(
                    BillingKnownItemLease.lease_owner == bound.owner,
                    BillingKnownItemLease.fence == bound.fence,
                    BillingKnownItemLease.lease_until.is_not(None),
                    BillingKnownItemLease.lease_until > now,
                )
                .values(lease_owner=None, lease_until=None, updated_at=now)
                .returning(BillingKnownItemLease)
            )
            result = await self._session.execute(stmt)
            if result.scalar_one_or_none() is None:
                raise BillingWorkLeaseConflictError("billing work lease is expired, stolen, or stale")

    @contextlib.asynccontextmanager
    async def _operator_scope(self) -> AsyncIterator[None]:
        # WHY: SET LOCAL bypass must not outlive this method or mix with tenant-bound work.
        # Nested savepoint keeps FOR UPDATE on the outer transaction after success.
        if _is_sqlite_session(self._session):
            yield
            return
        tenant = await _session_setting(self._session, "app.current_tenant")
        if tenant.strip():
            raise ValueError("billing repository operator scope cannot run on a tenant-bound session")
        previous = await _session_setting(self._session, "app.bypass_rls")
        await self._session.execute(text("SELECT set_config('app.bypass_rls', 'true', true)"))
        try:
            async with self._session.begin_nested():
                yield
        finally:
            await self._session.execute(
                text("SELECT set_config('app.bypass_rls', :value, true)"),
                {"value": previous},
            )

    async def _ensure_known_item_row(
        self,
        *,
        provider: str,
        environment: str,
        seller_account: str,
        kind: str,
        remote_id: str,
        now: datetime,
    ) -> None:
        inserter = pg_insert if is_postgres(self._session) else sqlite_insert
        stmt = inserter(BillingKnownItemLease).values(
            provider=provider,
            environment=environment,
            seller_account=seller_account,
            kind=kind,
            remote_id=remote_id,
            fence=0,
            updated_at=now,
        )
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["provider", "environment", "seller_account", "kind", "remote_id"]
        )
        await self._session.execute(stmt)

    async def _claim_known_item_row(
        self,
        *,
        provider: str,
        environment: str,
        seller_account: str,
        kind: str,
        remote_id: str,
        owner: str,
        until: datetime,
        now: datetime,
    ) -> BillingKnownItemLease | None:
        if is_postgres(self._session) and not is_sqlite(self._session):
            result = await self._session.execute(
                text(
                    """
                    WITH claimed AS (
                      SELECT provider, environment, seller_account, kind, remote_id
                      FROM billing_known_item_lease
                      WHERE provider = :provider
                        AND environment = :environment
                        AND seller_account = :seller_account
                        AND kind = :kind
                        AND remote_id = :remote_id
                        AND (lease_owner IS NULL OR lease_until IS NULL OR lease_until <= :now)
                      FOR UPDATE SKIP LOCKED
                    )
                    UPDATE billing_known_item_lease AS c
                    SET lease_owner = :owner,
                        lease_until = :until,
                        fence = c.fence + 1,
                        updated_at = :now
                    FROM claimed
                    WHERE c.provider = claimed.provider
                      AND c.environment = claimed.environment
                      AND c.seller_account = claimed.seller_account
                      AND c.kind = claimed.kind
                      AND c.remote_id = claimed.remote_id
                    RETURNING c.provider, c.environment, c.seller_account, c.kind, c.remote_id,
                              c.lease_owner, c.lease_until, c.fence
                    """
                ),
                {
                    "provider": provider,
                    "environment": environment,
                    "seller_account": seller_account,
                    "kind": kind,
                    "remote_id": remote_id,
                    "owner": owner,
                    "until": until,
                    "now": now,
                },
            )
            mapping = result.mappings().first()
            if mapping is None:
                return None
            loaded = await self._session.execute(
                select(BillingKnownItemLease)
                .where(
                    BillingKnownItemLease.provider == provider,
                    BillingKnownItemLease.environment == environment,
                    BillingKnownItemLease.seller_account == seller_account,
                    BillingKnownItemLease.kind == kind,
                    BillingKnownItemLease.remote_id == remote_id,
                )
                .limit(1)
                .execution_options(populate_existing=True)
            )
            row = loaded.scalar_one_or_none()
            if row is None:
                return None
            return _apply_lease_returning(row, mapping)
        stmt = (
            update(BillingKnownItemLease)
            .where(
                BillingKnownItemLease.provider == provider,
                BillingKnownItemLease.environment == environment,
                BillingKnownItemLease.seller_account == seller_account,
                BillingKnownItemLease.kind == kind,
                BillingKnownItemLease.remote_id == remote_id,
                or_(
                    BillingKnownItemLease.lease_owner.is_(None),
                    BillingKnownItemLease.lease_until.is_(None),
                    BillingKnownItemLease.lease_until <= now,
                ),
            )
            .values(
                lease_owner=owner,
                lease_until=until,
                fence=BillingKnownItemLease.fence + 1,
                updated_at=now,
            )
            .returning(BillingKnownItemLease)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    @contextlib.asynccontextmanager
    async def _tenant_context(self, tenant_id: UUID) -> AsyncIterator[None]:
        if _is_sqlite_session(self._session):
            yield
            return
        try:
            await set_tenant_context(self._session, tenant_id)
            yield
        finally:
            await clear_tenant_context(self._session)

    @contextlib.asynccontextmanager
    async def _maintenance_rls_bypass(self) -> AsyncIterator[None]:
        if _is_sqlite_session(self._session):
            yield
            return
        try:
            await enable_rls_bypass(self._session)
            yield
        except BaseException:
            try:
                await disable_rls_bypass(self._session)
            except Exception:  # noqa: BLE001 - preserve the original scan failure
                logger.warning("billing inbox RLS context reset failed")
            raise
        else:
            await disable_rls_bypass(self._session)

    # Small, explicit aliases keep the repository useful to the future worker
    # without introducing another persistence implementation.
    insert_webhook = record_webhook
    save_webhook = record_webhook
    get_subscription_projection = get_projection


SqlAlchemyBillingRepository = BillingRepository


def _validate_non_empty(name: str, value: object) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")


def _validate_uuid(name: str, value: object) -> None:
    if not isinstance(value, UUID):
        raise ValueError(f"{name} must be a UUID")


def _coerce_subscription_status(value: BillingSubscriptionStatus | str) -> BillingSubscriptionStatus:
    if isinstance(value, BillingSubscriptionStatus):
        return value
    try:
        return BillingSubscriptionStatus(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid billing subscription status") from exc


def _coerce_inbox_status(value: WebhookInboxStatus | str) -> WebhookInboxStatus:
    if isinstance(value, WebhookInboxStatus):
        return value
    try:
        return WebhookInboxStatus(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid webhook inbox status") from exc


def _coerce_position(value: datetime | str, name: str) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{name} must be an ISO timestamp") from exc
    if not isinstance(value, datetime):
        raise ValueError(f"{name} must be a datetime or ISO timestamp")
    if value.tzinfo is None or value.utcoffset() is None:
        # Database drivers may return a naive UTC value for a timezone column;
        # treating it as UTC preserves the stored ordering without guessing a
        # caller's local timezone.
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _coerce_optional_datetime(value: datetime | None, name: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise ValueError(f"{name} must be a datetime or None")
    return _coerce_position(value, name)


def _is_sqlite_session(session: AsyncSession) -> bool:
    if is_sqlite(session):
        return True
    wrapped = getattr(session, "_session", None)
    return wrapped is not None and is_sqlite(wrapped)


def _coerce_work_kind(value: str) -> str:
    if isinstance(value, BillingWorkKind):
        return value.value
    try:
        return BillingWorkKind(value).value
    except (TypeError, ValueError) as exc:
        raise ValueError("kind must be inbox or projection") from exc


def _bounded_text(name: str, value: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    stripped = value.strip()
    if len(stripped) > limit:
        raise ValueError(f"{name} exceeds the bounded length")
    return stripped


def _require_aware(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("now must be a timezone-aware datetime")
    return value.astimezone(UTC)


def _require_ttl(value: timedelta) -> timedelta:
    if not isinstance(value, timedelta) or value <= timedelta(0):
        raise ValueError("lease_ttl must be a positive duration")
    return value


def _coerce_lease(lease: object) -> BillingWorkLease:
    if isinstance(lease, BillingWorkLease):
        return lease
    try:
        return BillingWorkLease(
            provider=lease.provider,
            environment=lease.environment,
            seller_account=lease.seller_account,
            kind=lease.kind,
            remote_id=lease.remote_id,
            owner=lease.owner,
            fence=lease.fence,
            lease_until=lease.lease_until,
        )
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("lease is required") from exc


def _lease_identity(lease: BillingWorkLease) -> tuple[object, object, object, object, object]:
    return (
        BillingKnownItemLease.provider == lease.provider,
        BillingKnownItemLease.environment == lease.environment,
        BillingKnownItemLease.seller_account == lease.seller_account,
        BillingKnownItemLease.kind == lease.kind,
        BillingKnownItemLease.remote_id == lease.remote_id,
    )


def _apply_lease_returning(
    row: BillingKnownItemLease,
    mapping: Mapping[str, object],
) -> BillingKnownItemLease:
    # WHY: raw UPDATE RETURNING is the fresh owner/fence; identity-map rows can lag.
    row.lease_owner = mapping["lease_owner"]  # type: ignore[assignment]
    row.lease_until = mapping["lease_until"]  # type: ignore[assignment]
    row.fence = int(mapping["fence"])  # type: ignore[arg-type]
    return row


async def _session_setting(session: AsyncSession, name: str) -> str:
    result = await session.execute(text("SELECT current_setting(:name, true)"), {"name": name})
    value = result.scalar()
    return "" if value is None else str(value)


def _lease_from_row(row: BillingKnownItemLease) -> BillingWorkLease:
    if row.lease_owner is None or row.lease_until is None:
        raise BillingWorkLeaseConflictError("billing work lease is missing owner or expiry")
    lease_until = row.lease_until
    if lease_until.tzinfo is None:
        lease_until = lease_until.replace(tzinfo=UTC)
    else:
        lease_until = lease_until.astimezone(UTC)
    return BillingWorkLease(
        provider=row.provider,
        environment=row.environment,
        seller_account=row.seller_account,
        kind=row.kind,
        remote_id=row.remote_id,
        owner=row.lease_owner,
        fence=int(row.fence),
        lease_until=lease_until,
    )


__all__ = [
    "BillingRepository",
    "DEFAULT_WEBHOOK_MAX_ATTEMPTS",
    "DEFAULT_WEBHOOK_RETRY_BACKOFF_BASE_SECONDS",
    "DEFAULT_WEBHOOK_RETRY_BACKOFF_MAX_SECONDS",
    "SqlAlchemyBillingRepository",
]
