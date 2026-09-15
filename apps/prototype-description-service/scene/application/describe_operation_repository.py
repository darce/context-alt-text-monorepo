"""Durable operation correlation and demand leases; caller owns the transaction.

Callers must commit expired/rejected transitions even when mapping a typed error.
Lease deployment bounds are validated by the demand service before construction.
"""

from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, update
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
    async_job_retention_hours,
    elapsed_ms,
    utc_observation,
    validate_duration_ms,
)


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
        return lease

    async def accept(
        self, *, tenant_id: uuid.UUID, request_digest: str, operation_id: str | None = None, now: datetime | None = None
    ) -> DescribeOperation:
        now = utc_observation(now or datetime.now(UTC))
        if len(request_digest) != 64:
            raise ValueError("request_digest must be a SHA-256 digest")
        if operation_id is None:
            op = DescribeOperation(
                tenant_id=tenant_id,
                operation_id=uuid.uuid4().hex,
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
        if not isinstance(operation_id, str) or not 1 <= len(operation_id) <= 128:
            raise OperationMismatchError("invalid operation id")
        op = await self.get(tenant_id=tenant_id, operation_id=operation_id)
        if op is None or op.request_digest != request_digest:
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
        if not 1 <= len(startup_id) <= 128:
            raise ValueError("invalid startup id")
        op, lease = await self._active(tenant_id, operation_id, utc_observation(now or datetime.now(UTC)))
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
        now = utc_observation(now or datetime.now(UTC))
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
        now = utc_observation(now or datetime.now(UTC))
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
        self, *, now: datetime | None = None, stop_requested: bool = False, max_lease_reached: bool = False
    ) -> int:
        await DescribeRunRepository(self._session)._require_rls_bypass()
        now = utc_observation(now or datetime.now(UTC))
        await self._session.execute(
            update(DescribeDemandLease)
            .where(
                DescribeDemandLease.state == State.ACTIVE,
                DescribeDemandLease.expires_at <= now,
            )
            .values(state=State.EXPIRED)
        )
        if stop_requested or max_lease_reached:
            return 0
        return int(
            await self._session.scalar(
                select(func.count())
                .select_from(DescribeDemandLease)
                .where(
                    DescribeDemandLease.state == State.ACTIVE,
                    DescribeDemandLease.expires_at > now,
                )
            )
            or 0
        )

    async def purge_expired(self, *, now: datetime | None = None) -> int:
        await DescribeRunRepository(self._session)._require_rls_bypass()
        now = utc_observation(now or datetime.now(UTC))
        await self._session.execute(delete(DescribeDemandLease).where(DescribeDemandLease.retain_until <= now))
        result = await self._session.execute(delete(DescribeOperation).where(DescribeOperation.retain_until <= now))
        await self._session.execute(
            delete(DescribeStartup).where(
                DescribeStartup.retain_until <= now,
                ~select(DescribeOperation.operation_id)
                .where(DescribeOperation.startup_id == DescribeStartup.startup_id)
                .exists(),
            )
        )
        await self._session.flush()
        return result.rowcount
