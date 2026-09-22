"""Operator-scope persistence for billing recovery cursors, leases, and quarantine.

Caller owns the transaction. Acquire must be committed before any vendor I/O.
This repository never holds a row lock across a network call.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import Select, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.portal_billing import (
    BillingReconciliationCursor,
    BillingReconciliationItemProgress,
    BillingReconciliationQuarantine,
)
from db.tenant_context import enable_rls_bypass
from recognition.domain.portal_contracts import (
    RECONCILIATION_MAX_CURSOR_LENGTH,
    RECONCILIATION_MAX_FAILURE_CLASS_LENGTH,
    RECONCILIATION_MAX_OPERATOR_REASON_LENGTH,
    RECONCILIATION_MAX_OWNER_LENGTH,
    RECONCILIATION_MAX_REMOTE_ID_LENGTH,
    EnumerationObservation,
    EnumerationObservationReason,
    QuarantineRecord,
    QuarantineStatus,
    ReconciliationCursorAdvanceError,
    ReconciliationCursorKey,
    ReconciliationKind,
    ReconciliationLease,
    ReconciliationLeaseConflictError,
    ReconciliationQuarantineConflictError,
)
from recognition.shared.db.dialect import is_postgres, is_sqlite

_CURSOR = BillingReconciliationCursor
_QUARANTINE = BillingReconciliationQuarantine
_PROGRESS = BillingReconciliationItemProgress
_ALLOWED_PROVIDERS = frozenset({"polar", "fake"})


class BillingReconciliationRepository:
    """Fenced cursor/quarantine store. Transaction-local app.bypass_rls only."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def acquire_lease(
        self,
        key: ReconciliationCursorKey,
        *,
        owner: str,
        lease_ttl: timedelta,
        now: datetime,
    ) -> ReconciliationLease | None:
        await self._operator_scope()
        key = _validate_key(key)
        owner = _bounded_text("owner", owner, RECONCILIATION_MAX_OWNER_LENGTH)
        now = _require_aware(now)
        until = now + _require_ttl(lease_ttl)
        await self._ensure_cursor_row(key, now)
        row = await self._claim_cursor(key, owner=owner, until=until, now=now)
        if row is None:
            return None
        return _lease_from_cursor(row)

    async def heartbeat(
        self,
        lease: ReconciliationLease,
        *,
        now: datetime,
        lease_ttl: timedelta,
    ) -> ReconciliationLease:
        await self._operator_scope()
        now = _require_aware(now)
        until = now + _require_ttl(lease_ttl)
        row = await self._require_live_cursor(lease, now, lease_until=until)
        return _lease_from_cursor(row)

    async def complete_item(
        self,
        lease: ReconciliationLease,
        *,
        remote_id: str,
        now: datetime,
    ) -> None:
        await self._operator_scope()
        now = _require_aware(now)
        remote_id = _validate_remote_id(remote_id)
        await self._require_live_cursor(lease, now, last_progress_at=now)
        await self._upsert_progress(lease, remote_id=remote_id, status="completed", now=now)

    async def quarantine_item(
        self,
        lease: ReconciliationLease,
        *,
        observation: EnumerationObservation,
        now: datetime,
    ) -> QuarantineRecord:
        await self._operator_scope()
        now = _require_aware(now)
        if not isinstance(observation, EnumerationObservation):
            raise ValueError("observation must be EnumerationObservation")
        remote_id = _validate_remote_id(observation.remote_id)
        await self._require_live_cursor(lease, now, last_progress_at=now)
        existing = await self._get_quarantine_row(lease.key, remote_id)
        if existing is None:
            row = _QUARANTINE(
                provider=lease.key.provider,
                environment=lease.key.environment,
                seller_account=lease.key.seller_account,
                kind=lease.key.kind.value,
                remote_id=remote_id,
                reason=observation.reason.value,
                status=QuarantineStatus.OPEN.value,
                attempt_count=1,
                fence=lease.fence,
                details=dict(observation.details),
                created_at=now,
                updated_at=now,
            )
            try:
                async with self._session.begin_nested():
                    self._session.add(row)
                    await self._session.flush()
                    existing = row
            except IntegrityError:
                existing = await self._get_quarantine_row(lease.key, remote_id)
                if existing is None:
                    raise
        await self._upsert_progress(lease, remote_id=remote_id, status="quarantined", now=now)
        return _quarantine_from_row(existing)

    async def advance_cursor(
        self,
        lease: ReconciliationLease,
        *,
        next_cursor: str | None,
        exhausted: bool,
        page_remote_ids: tuple[str, ...],
        now: datetime,
    ) -> ReconciliationLease:
        await self._operator_scope()
        now = _require_aware(now)
        if not isinstance(exhausted, bool):
            raise ValueError("exhausted must be a boolean")
        cursor_value = _validate_optional_cursor(next_cursor)
        unique_ids = tuple(dict.fromkeys(_validate_remote_id(item) for item in page_remote_ids))
        if unique_ids:
            progressed = await self._session.execute(
                select(func.count())
                .select_from(_PROGRESS)
                .where(*_progress_namespace(lease.key), _PROGRESS.remote_id.in_(unique_ids))
            )
            if int(progressed.scalar_one()) != len(unique_ids):
                raise ReconciliationCursorAdvanceError("cursor advance refused: page contains unprocessed remote ids")
        row = await self._require_live_cursor(
            lease,
            now,
            last_progress_at=now,
            cursor=cursor_value,
            exhausted=exhausted,
        )
        return _lease_from_cursor(row)

    async def record_page_failure(
        self,
        lease: ReconciliationLease,
        *,
        failure_class: str,
        now: datetime,
    ) -> ReconciliationLease:
        await self._operator_scope()
        now = _require_aware(now)
        failure_class = _bounded_text("failure_class", failure_class, RECONCILIATION_MAX_FAILURE_CLASS_LENGTH)
        row = await self._require_live_cursor(
            lease,
            now,
            failure_class=failure_class,
            failure_at=now,
        )
        return _lease_from_cursor(row)

    async def audited_retry(
        self,
        lease: ReconciliationLease,
        *,
        remote_id: str,
        operator_identity: str,
        operator_reason: str,
        now: datetime,
    ) -> QuarantineRecord:
        await self._operator_scope()
        now = _require_aware(now)
        remote_id = _validate_remote_id(remote_id)
        operator_identity = _bounded_text("operator_identity", operator_identity, RECONCILIATION_MAX_OWNER_LENGTH)
        operator_reason = _bounded_text("operator_reason", operator_reason, RECONCILIATION_MAX_OPERATOR_REASON_LENGTH)
        await self._require_live_cursor(lease, now)
        stmt = (
            update(_QUARANTINE)
            .where(*_quarantine_namespace(lease.key), _QUARANTINE.remote_id == remote_id)
            .values(
                status=QuarantineStatus.RETRY_PENDING.value,
                attempt_count=_QUARANTINE.attempt_count + 1,
                operator_identity=operator_identity,
                operator_reason=operator_reason,
                next_retry_at=now,
                fence=lease.fence,
                updated_at=now,
            )
            .returning(_QUARANTINE)
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            raise ReconciliationQuarantineConflictError("quarantine item was not found for audited retry")
        return _quarantine_from_row(row)

    async def get_quarantine(
        self,
        key: ReconciliationCursorKey,
        remote_id: str,
    ) -> QuarantineRecord | None:
        await self._operator_scope()
        row = await self._get_quarantine_row(_validate_key(key), _validate_remote_id(remote_id))
        return None if row is None else _quarantine_from_row(row)

    async def _operator_scope(self) -> None:
        await enable_rls_bypass(self._session)

    async def _ensure_cursor_row(self, key: ReconciliationCursorKey, now: datetime) -> None:
        inserter = pg_insert if is_postgres(self._session) else sqlite_insert
        stmt = inserter(_CURSOR).values(
            provider=key.provider,
            environment=key.environment,
            seller_account=key.seller_account,
            kind=key.kind.value,
            fence=0,
            exhausted=False,
            failure_count=0,
            updated_at=now,
        )
        stmt = stmt.on_conflict_do_nothing(index_elements=["provider", "environment", "seller_account", "kind"])
        await self._session.execute(stmt)

    async def _claim_cursor(
        self,
        key: ReconciliationCursorKey,
        *,
        owner: str,
        until: datetime,
        now: datetime,
    ) -> BillingReconciliationCursor | None:
        if is_postgres(self._session) and not is_sqlite(self._session):
            result = await self._session.execute(
                text(
                    """
                    WITH claimed AS (
                      SELECT provider, environment, seller_account, kind
                      FROM billing_reconciliation_cursor
                      WHERE provider = :provider
                        AND environment = :environment
                        AND seller_account = :seller_account
                        AND kind = :kind
                        AND (lease_owner IS NULL OR lease_until IS NULL OR lease_until <= :now)
                      FOR UPDATE SKIP LOCKED
                    )
                    UPDATE billing_reconciliation_cursor AS c
                    SET lease_owner = :owner,
                        lease_until = :until,
                        fence = c.fence + 1,
                        updated_at = :now
                    FROM claimed
                    WHERE c.provider = claimed.provider
                      AND c.environment = claimed.environment
                      AND c.seller_account = claimed.seller_account
                      AND c.kind = claimed.kind
                    RETURNING c.provider, c.environment, c.seller_account, c.kind, c.cursor,
                              c.lease_owner, c.lease_until, c.fence, c.last_progress_at, c.exhausted
                    """
                ),
                {
                    "provider": key.provider,
                    "environment": key.environment,
                    "seller_account": key.seller_account,
                    "kind": key.kind.value,
                    "owner": owner,
                    "until": until,
                    "now": now,
                },
            )
            mapping = result.mappings().first()
            if mapping is None:
                return None
            loaded = await self._session.execute(_cursor_select(key))
            return loaded.scalar_one_or_none()
        stmt = (
            update(_CURSOR)
            .where(
                *_cursor_namespace(key),
                or_(
                    _CURSOR.lease_owner.is_(None),
                    _CURSOR.lease_until.is_(None),
                    _CURSOR.lease_until <= now,
                ),
            )
            .values(
                lease_owner=owner,
                lease_until=until,
                fence=_CURSOR.fence + 1,
                updated_at=now,
            )
            .returning(_CURSOR)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def _require_live_cursor(
        self,
        lease: ReconciliationLease,
        now: datetime,
        *,
        last_progress_at: datetime | None = None,
        lease_until: datetime | None = None,
        cursor: str | None | object = ...,
        exhausted: bool | None = None,
        failure_class: str | None = None,
        failure_at: datetime | None = None,
    ) -> BillingReconciliationCursor:
        if not isinstance(lease, ReconciliationLease):
            raise ValueError("lease is required")
        values: dict[str, object] = {"updated_at": now}
        if last_progress_at is not None:
            values["last_progress_at"] = last_progress_at
        if lease_until is not None:
            values["lease_until"] = lease_until
        if cursor is not ...:
            values["cursor"] = cursor
        if exhausted is not None:
            values["exhausted"] = exhausted
        if failure_class is not None:
            values["last_failure_class"] = failure_class
            values["failure_count"] = _CURSOR.failure_count + 1
        if failure_at is not None:
            values["last_failure_at"] = failure_at
        stmt = (
            update(_CURSOR)
            .where(
                *_cursor_namespace(lease.key),
                _CURSOR.lease_owner == lease.owner,
                _CURSOR.fence == lease.fence,
                _CURSOR.lease_until.is_not(None),
                _CURSOR.lease_until > now,
            )
            .values(**values)
            .returning(_CURSOR)
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            raise ReconciliationLeaseConflictError("reconciliation lease is expired, stolen, or stale")
        return row

    async def _upsert_progress(
        self,
        lease: ReconciliationLease,
        *,
        remote_id: str,
        status: str,
        now: datetime,
    ) -> None:
        inserter = pg_insert if is_postgres(self._session) else sqlite_insert
        stmt = inserter(_PROGRESS).values(
            provider=lease.key.provider,
            environment=lease.key.environment,
            seller_account=lease.key.seller_account,
            kind=lease.key.kind.value,
            remote_id=remote_id,
            fence=lease.fence,
            status=status,
            processed_at=now,
        )
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["provider", "environment", "seller_account", "kind", "remote_id"]
        )
        await self._session.execute(stmt)

    async def _get_quarantine_row(
        self,
        key: ReconciliationCursorKey,
        remote_id: str,
    ) -> BillingReconciliationQuarantine | None:
        result = await self._session.execute(
            select(_QUARANTINE).where(*_quarantine_namespace(key), _QUARANTINE.remote_id == remote_id).limit(1)
        )
        return result.scalar_one_or_none()


def _cursor_select(key: ReconciliationCursorKey) -> Select[tuple[BillingReconciliationCursor]]:
    return select(_CURSOR).where(*_cursor_namespace(key)).limit(1)


def _cursor_namespace(key: ReconciliationCursorKey) -> tuple[object, object, object, object]:
    return (
        _CURSOR.provider == key.provider,
        _CURSOR.environment == key.environment,
        _CURSOR.seller_account == key.seller_account,
        _CURSOR.kind == key.kind.value,
    )


def _quarantine_namespace(key: ReconciliationCursorKey) -> tuple[object, object, object, object]:
    return (
        _QUARANTINE.provider == key.provider,
        _QUARANTINE.environment == key.environment,
        _QUARANTINE.seller_account == key.seller_account,
        _QUARANTINE.kind == key.kind.value,
    )


def _progress_namespace(key: ReconciliationCursorKey) -> tuple[object, object, object, object]:
    return (
        _PROGRESS.provider == key.provider,
        _PROGRESS.environment == key.environment,
        _PROGRESS.seller_account == key.seller_account,
        _PROGRESS.kind == key.kind.value,
    )


def _lease_from_cursor(row: BillingReconciliationCursor) -> ReconciliationLease:
    if row.lease_owner is None or row.lease_until is None:
        raise ReconciliationLeaseConflictError("reconciliation lease is missing owner or expiry")
    lease_until = _as_utc(row.lease_until)
    if lease_until is None:
        raise ReconciliationLeaseConflictError("reconciliation lease is missing owner or expiry")
    return ReconciliationLease(
        key=ReconciliationCursorKey(
            provider=row.provider,
            environment=row.environment,
            seller_account=row.seller_account,
            kind=ReconciliationKind(row.kind),
        ),
        owner=row.lease_owner,
        fence=int(row.fence),
        lease_until=lease_until,
        cursor=row.cursor,
        last_progress_at=_as_utc(row.last_progress_at),
        exhausted=bool(row.exhausted),
    )


def _quarantine_from_row(row: BillingReconciliationQuarantine) -> QuarantineRecord:
    return QuarantineRecord(
        key=ReconciliationCursorKey(
            provider=row.provider,
            environment=row.environment,
            seller_account=row.seller_account,
            kind=ReconciliationKind(row.kind),
        ),
        remote_id=row.remote_id,
        reason=EnumerationObservationReason(row.reason),
        status=QuarantineStatus(row.status),
        attempt_count=int(row.attempt_count),
        fence=int(row.fence),
        next_retry_at=_as_utc(row.next_retry_at),
        operator_identity=row.operator_identity,
        operator_reason=row.operator_reason,
    )


def _validate_key(key: ReconciliationCursorKey) -> ReconciliationCursorKey:
    if not isinstance(key, ReconciliationCursorKey):
        raise ValueError("cursor key is required")
    if key.provider not in _ALLOWED_PROVIDERS:
        raise ValueError("provider must be polar or fake")
    return key


def _validate_remote_id(remote_id: str) -> str:
    if not isinstance(remote_id, str) or not remote_id.strip():
        raise ValueError("remote_id is required")
    value = remote_id.strip()
    if len(value) > RECONCILIATION_MAX_REMOTE_ID_LENGTH:
        raise ValueError("remote_id exceeds the bounded identifier length")
    return value


def _validate_optional_cursor(cursor: str | None) -> str | None:
    if cursor is None:
        return None
    if not isinstance(cursor, str) or not cursor.strip():
        raise ValueError("cursor must be opaque text when present")
    value = cursor.strip()
    if len(value) > RECONCILIATION_MAX_CURSOR_LENGTH:
        raise ValueError("cursor exceeds the bounded length")
    return value


def _bounded_text(name: str, value: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    stripped = value.strip()
    if len(stripped) > limit:
        raise ValueError(f"{name} exceeds the bounded length")
    return stripped


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _require_aware(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("now must be a timezone-aware datetime")
    return value


def _require_ttl(value: timedelta) -> timedelta:
    if not isinstance(value, timedelta) or value <= timedelta(0):
        raise ValueError("lease_ttl must be a positive duration")
    return value


__all__ = ["BillingReconciliationRepository"]
