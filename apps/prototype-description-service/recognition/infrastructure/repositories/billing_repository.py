"""SQLAlchemy persistence for verified billing events and their projection."""

from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import BillingSubscriptionProjection, BillingWebhookInbox
from db.tenant_context import (
    clear_tenant_context,
    disable_rls_bypass,
    enable_rls_bypass,
    set_tenant_context,
)
from recognition.application.scan.retry_backoff import compute_retry_backoff
from recognition.domain.portal_contracts import BillingSubscriptionStatus, WebhookInboxStatus
from recognition.shared.db.dialect import is_sqlite

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
        self._session = session
        self._max_attempts = max_attempts
        self._retry_backoff_base_s = retry_backoff_base_s
        self._retry_backoff_max_s = retry_backoff_max_s

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

        row = BillingWebhookInbox(
            provider=provider,
            provider_event_id=provider_event_id,
            event_type=event_type,
            signature_verified=True,
            payload=dict(payload),
            status=WebhookInboxStatus.RECEIVED.value,
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
        # WHY: the worker scan intentionally spans tenants because inbox rows
        # have no tenant key; use the approved maintenance bypass only around
        # this bounded read and always release it on success or failure.
        async with self._maintenance_rls_bypass():
            result = await self._session.execute(statement)
            return list(result.scalars().all())

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


__all__ = [
    "BillingRepository",
    "DEFAULT_WEBHOOK_MAX_ATTEMPTS",
    "DEFAULT_WEBHOOK_RETRY_BACKOFF_BASE_SECONDS",
    "DEFAULT_WEBHOOK_RETRY_BACKOFF_MAX_SECONDS",
    "SqlAlchemyBillingRepository",
]
