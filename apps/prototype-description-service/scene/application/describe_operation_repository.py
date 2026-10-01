"""Durable operation correlation and demand leases; caller owns the transaction.

Callers must commit expired/rejected transitions even when mapping a typed error.
Lease deployment bounds are validated by the demand service before construction.
"""

from __future__ import annotations

import math
import re
import sqlite3
import uuid
from collections.abc import Collection
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, tuple_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.scene import DescribeDemandLease, DescribeOperation, DescribeStartup
from recognition.shared.db.dialect import is_sqlite
from scene.application.describe_run_repository import DescribeRunRepository
from scene.domain.describe_run import (
    DemandLeaseState as State,
)
from scene.domain.describe_run import (
    OperationExpiredError,
    OperationMismatchError,
    as_utc,
    async_job_retention_hours,
    elapsed_ms,
    utc_observation,
    validate_duration_ms,
)

_PURGE_BATCH_SIZE = 400


def _is_describe_operation_primary_key_conflict(error: IntegrityError) -> bool:
    """Return whether ``error`` is the composite operation identity conflict.

    PostgreSQL exposes its constraint name through either asyncpg's
    ``constraint_name`` or psycopg's diagnostic record. SQLite does not expose
    named constraints, so accept only its exact composite-primary-key error.
    """
    original = error.orig
    diagnostic = getattr(original, "diag", None)
    constraint_name = getattr(original, "constraint_name", None) or getattr(diagnostic, "constraint_name", None)
    if constraint_name == "describe_operations_pkey":
        return True
    if getattr(original, "sqlite_errorcode", None) == sqlite3.SQLITE_CONSTRAINT_PRIMARYKEY:
        return str(original) == (
            "UNIQUE constraint failed: describe_operations.tenant_id, describe_operations.operation_id"
        )
    return False


class DescribeOperationRepository:
    def __init__(self, session: AsyncSession, *, lease_seconds: float, retention_hours: float | None = None):
        hours = async_job_retention_hours() if retention_hours is None else retention_hours
        if not math.isfinite(lease_seconds) or lease_seconds <= 0:
            raise ValueError("lease_seconds must be finite and positive")
        if not math.isfinite(hours) or hours <= 0:
            raise ValueError("retention_hours must be finite and positive")
        self.unadmitted_events = 0
        self._session = session
        self._lease = timedelta(seconds=lease_seconds)
        self._retention = timedelta(hours=hours)

    async def get(self, *, tenant_id: uuid.UUID, operation_id: str) -> DescribeOperation | None:
        return await self._session.scalar(
            select(DescribeOperation)
            .where(
                DescribeOperation.tenant_id == tenant_id,
                DescribeOperation.operation_id == operation_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def _lease_for(self, op: DescribeOperation) -> DescribeDemandLease:
        lease = await self._session.get(
            DescribeDemandLease, (op.tenant_id, op.operation_id), populate_existing=True, with_for_update=True
        )
        if lease is None:
            raise RuntimeError("operation has no demand lease")
        if utc_observation(lease.retain_until) > utc_observation(op.retain_until):
            raise ValueError("lease retention exceeds operation retention")
        return lease

    async def _insert_new(
        self,
        *,
        tenant_id: uuid.UUID,
        request_digest: str,
        operation_id: str,
        now: datetime,
    ) -> DescribeOperation:
        op = DescribeOperation(
            tenant_id=tenant_id,
            operation_id=operation_id,
            request_digest=request_digest,
            accepted_at=now,
            retain_until=now + self._retention,
            expires_at=now + min(self._lease, self._retention),
        )
        self._session.add(op)
        await self._session.flush()
        self._session.add(
            DescribeDemandLease(
                tenant_id=tenant_id,
                operation_id=op.operation_id,
                state=State.ACTIVE,
                expires_at=op.expires_at,
                retain_until=op.retain_until,
            )
        )
        await self._session.flush()
        return op

    async def bind_usage_identity(self, *, tenant_id: uuid.UUID, operation_id: str) -> DescribeOperation:
        """Return the durable operation row used as the G2 usage binding.

        Persisted shape for G3: ``(tenant_id, operation_id, request_digest)``.
        ``reservation_id``, ``fence_token``, and ``job_id`` are not columns on
        ``DescribeOperation``; they remain on ``UsageTicket`` until G3 adds them.
        """
        op = await self.get(tenant_id=tenant_id, operation_id=operation_id)
        if op is None:
            raise OperationMismatchError("unknown operation")
        return op

    async def accept(
        self, *, tenant_id: uuid.UUID, request_digest: str, operation_id: str | None = None, now: datetime | None = None
    ) -> DescribeOperation:
        now = as_utc(now or datetime.now(UTC))
        if not isinstance(request_digest, str) or re.fullmatch(r"[0-9a-f]{64}", request_digest) is None:
            raise ValueError("request_digest must be a SHA-256 digest")
        if operation_id is None:
            return await self._insert_new(
                tenant_id=tenant_id,
                request_digest=request_digest,
                operation_id=uuid.uuid4().hex,
                now=now,
            )
        if not isinstance(operation_id, str) or not 1 <= len(operation_id) <= 128:
            raise OperationMismatchError("invalid operation id")
        op = await self.get(tenant_id=tenant_id, operation_id=operation_id)
        if op is None:
            try:
                async with self._session.begin_nested():
                    return await self._insert_new(
                        tenant_id=tenant_id,
                        request_digest=request_digest,
                        operation_id=operation_id,
                        now=now,
                    )
            except IntegrityError as exc:
                if not _is_describe_operation_primary_key_conflict(exc):
                    raise
                # A concurrent first request may have committed the same
                # tenant/key after our miss. Re-read it under the same tenant
                # scope, then apply the ordinary replay/mismatch rules below.
                op = await self.get(tenant_id=tenant_id, operation_id=operation_id)
                if op is None:
                    raise
        if op.request_digest != request_digest:
            raise OperationMismatchError("operation does not match this tenant and request")
        lease = await self._lease_for(op)
        if utc_observation(op.retain_until) <= now:
            if lease.state == State.ACTIVE:
                lease.state = State.EXPIRED
            await self._session.flush()
            raise OperationExpiredError("operation retention expired")
        if lease.state == State.COMPLETED:
            self.unadmitted_events += 1
            return op
        if lease.state == State.ACTIVE and utc_observation(lease.expires_at) <= now:
            lease.state = State.EXPIRED
        if lease.state in (State.EXPIRED, State.REJECTED):
            lease.state = State.REJECTED
            await self._session.flush()
            raise OperationExpiredError("operation expired; start a new operation")
        elapsed_ms(op.accepted_at, now)
        lease.retain_until = op.retain_until = utc_observation(op.retain_until)
        lease.expires_at = op.expires_at = min(now + self._lease, utc_observation(op.retain_until))
        await self._session.flush()
        return op

    async def _active(
        self, tenant_id: uuid.UUID, operation_id: str, now: datetime
    ) -> tuple[DescribeOperation, DescribeDemandLease]:
        op = await self.get(tenant_id=tenant_id, operation_id=operation_id)
        if op is None:
            raise OperationMismatchError("unknown operation")
        lease = await self._lease_for(op)
        if lease.state == State.ACTIVE and utc_observation(lease.expires_at) <= now:
            lease.state = State.EXPIRED
            await self._session.flush()
        return op, lease

    async def associate_startup(
        self,
        *,
        tenant_id: uuid.UUID,
        operation_id: str,
        startup_id: str,
        started_at: datetime | None = None,
        now: datetime | None = None,
    ) -> DescribeOperation:
        if started_at is not None:
            started_at = as_utc(started_at)
        if not 1 <= len(startup_id) <= 128:
            raise ValueError("invalid startup id")
        op, lease = await self._active(tenant_id, operation_id, as_utc(now or datetime.now(UTC)))
        if lease.state != State.ACTIVE or op.first_ready_at is not None:
            self.unadmitted_events += 1
            return op
        if op.startup_id is not None and op.startup_id != startup_id:
            raise ValueError("operation already associated with another startup")
        # Atomic upsert lets distinct operations join a startup concurrently.
        if is_sqlite(self._session):
            from sqlalchemy.dialects.sqlite import insert
        else:
            from sqlalchemy.dialects.postgresql import insert
        await self._session.execute(
            insert(DescribeStartup)
            .values(startup_id=startup_id, started_at=started_at, retain_until=op.retain_until)
            .on_conflict_do_nothing(index_elements=["startup_id"])
        )
        startup = await self._session.scalar(
            select(DescribeStartup)
            .where(DescribeStartup.startup_id == startup_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if started_at is not None and startup.started_at is None:
            if startup.first_ready_at is not None:
                elapsed_ms(started_at, startup.first_ready_at)
            startup.started_at = started_at
        startup.retain_until = max(utc_observation(startup.retain_until), utc_observation(op.retain_until))
        op.startup_id = startup_id
        await self._session.flush()
        return op

    async def observe_ready(
        self, *, tenant_id: uuid.UUID, operation_id: str, now: datetime | None = None
    ) -> DescribeOperation:
        now = as_utc(now or datetime.now(UTC))
        op, lease = await self._active(tenant_id, operation_id, now)
        if lease.state != State.ACTIVE or op.first_ready_at is not None:
            self.unadmitted_events += 1
            return op
        wait = elapsed_ms(op.accepted_at, now)
        startup_ms = None
        if op.startup_id is not None:
            startup = await self._session.scalar(
                select(DescribeStartup)
                .where(DescribeStartup.startup_id == op.startup_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            ready = startup.first_ready_at or now
            if startup.started_at is not None:
                startup_ms = elapsed_ms(startup.started_at, ready)
            startup.first_ready_at = ready
        op.first_ready_at = now
        op.ramp_up_ms = wait if op.startup_id is not None else 0
        op.startup_ms = startup_ms
        await self._session.flush()
        return op

    async def complete(
        self,
        *,
        tenant_id: uuid.UUID,
        operation_id: str,
        processing_ms: float | None = None,
        queue_ms: float | None = None,
        server_elapsed_ms: float | None = None,
        now: datetime | None = None,
    ) -> DescribeOperation:
        for value in (processing_ms, queue_ms, server_elapsed_ms):
            validate_duration_ms(value)
        now = as_utc(now or datetime.now(UTC))
        op, lease = await self._active(tenant_id, operation_id, now)
        if lease.state != State.ACTIVE:
            self.unadmitted_events += 1
            return op
        if op.first_ready_at is None:
            raise ValueError("completion requires readiness observation")
        elapsed_ms(op.first_ready_at, now)
        op.completed_at = now
        op.processing_ms, op.queue_ms, op.server_elapsed_ms = processing_ms, queue_ms, server_elapsed_ms
        # Completion retention does not extend the active lifecycle lease.
        op.retain_until = lease.retain_until = now + self._retention
        lease.state = State.COMPLETED
        await self._session.flush()
        return op

    async def active_demand_count(
        self,
        *,
        now: datetime | None = None,
        stop_requested: bool = False,
        max_lease_reached: bool = False,
        stop_held_leases: Collection[tuple[uuid.UUID, str]] = (),
    ) -> int:
        await DescribeRunRepository(self._session)._require_rls_bypass()
        now = as_utc(now or datetime.now(UTC))
        await self._session.execute(
            update(DescribeDemandLease)
            .where(
                DescribeDemandLease.state == State.ACTIVE,
                DescribeDemandLease.expires_at <= now,
            )
            .values(state=State.EXPIRED)
            .execution_options(synchronize_session="fetch")
        )
        if max_lease_reached:
            return 0
        held = tuple(stop_held_leases) if stop_requested else ()
        if stop_requested and not held:
            return 0
        query = (
            select(func.count())
            .select_from(DescribeDemandLease)
            .join(
                DescribeOperation,
                (DescribeDemandLease.tenant_id == DescribeOperation.tenant_id)
                & (DescribeDemandLease.operation_id == DescribeOperation.operation_id),
            )
            .where(
                DescribeDemandLease.state == State.ACTIVE,
                DescribeDemandLease.expires_at > now,
                DescribeDemandLease.retain_until > now,
                DescribeOperation.retain_until > now,
            )
        )
        if held:
            query = query.where(~tuple_(DescribeDemandLease.tenant_id, DescribeDemandLease.operation_id).in_(held))
        return int(await self._session.scalar(query) or 0)

    async def purge_expired(self, *, now: datetime | None = None) -> int:
        await DescribeRunRepository(self._session)._require_rls_bypass()
        now = as_utc(now or datetime.now(UTC))
        deleted = 0
        while True:
            # Match renewal lock order: parent operation before demand lease.
            candidates = (
                await self._session.execute(
                    select(DescribeOperation.tenant_id, DescribeOperation.operation_id)
                    .where(DescribeOperation.retain_until <= now)
                    .order_by(DescribeOperation.tenant_id, DescribeOperation.operation_id)
                    .limit(_PURGE_BATCH_SIZE)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            identities = [(row.tenant_id, row.operation_id) for row in candidates]
            if not identities:
                break
            # Evaluate expiry in SQL: SQLite-loaded identity-map timestamps are naive.
            await self._session.execute(
                delete(DescribeDemandLease)
                .where(tuple_(DescribeDemandLease.tenant_id, DescribeDemandLease.operation_id).in_(identities))
                .execution_options(synchronize_session="fetch")
            )
            result = await self._session.execute(
                delete(DescribeOperation)
                .where(tuple_(DescribeOperation.tenant_id, DescribeOperation.operation_id).in_(identities))
                .execution_options(synchronize_session="fetch")
            )
            deleted += int(result.rowcount or 0)
        await self._session.execute(
            delete(DescribeStartup)
            .where(
                DescribeStartup.retain_until <= now,
                ~select(DescribeOperation.operation_id)
                .where(DescribeOperation.startup_id == DescribeStartup.startup_id)
                .exists(),
            )
            .execution_options(synchronize_session="fetch")
        )
        await self._session.flush()
        return deleted
