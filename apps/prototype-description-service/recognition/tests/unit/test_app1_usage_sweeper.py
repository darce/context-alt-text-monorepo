"""APP-1 G3 sweeper: bounded scan, never release active work."""

from __future__ import annotations

import inspect
import os
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from sqlalchemy import Table, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db.models import UsageReservation
from db.models.base_imports import Base
from db.models.jobs import IdentityScanJob, IdentityScanJobItem
from db.models.portal_billing import GlobalUsageAdmissionState, TenantEntitlement
from db.models.scene import DescribeRun, DescribeRunItem
from db.models.tenant import Tenant
from recognition.application.services.usage_admission_service import UsageAdmissionService
from recognition.application.services.usage_settlement_service import (
    MISSING_GENERATION_FENCE_CONTRACT,
    SettlementOutcome,
    SettlementResult,
    UsageSettlementService,
    recover_usage_job,
    settle_usage_job,
    sweep_stale_reservations,
)
from recognition.domain.job import JobStatus
from recognition.domain.portal_contracts import (
    DEFAULT_GLOBAL_CONFIG_VERSION,
    DEFAULT_GLOBAL_DAILY_COST_LIMIT,
    DEFAULT_GLOBAL_FENCE_EPOCH,
    DEFAULT_GLOBAL_INFLIGHT_LIMIT,
    DEFAULT_GLOBAL_QUEUE_BYTE_LIMIT,
    DEFAULT_GLOBAL_QUEUE_LIMIT,
    GLOBAL_USAGE_ADMISSION_STATE_ID,
    EntitlementStatus,
    UsageReservationStatus,
)
from scene.domain.describe_run import DescribeRunPhase, DescribeRunStatus, RunKind


async def _ledger_sessionmaker():
    path = os.path.join(tempfile.gettempdir(), f"app1_usage_sweep_{uuid.uuid4().hex}.db")
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=cast(
                list[Table],
                [
                    Tenant.__table__,
                    TenantEntitlement.__table__,
                    UsageReservation.__table__,
                    GlobalUsageAdmissionState.__table__,
                    DescribeRun.__table__,
                    DescribeRunItem.__table__,
                    IdentityScanJob.__table__,
                    IdentityScanJobItem.__table__,
                ],
            ),
        )
    return engine, async_sessionmaker(engine, expire_on_commit=False), path


async def _seed_tenant(session, *, allowance: int = 20):
    tenant = Tenant(id=uuid.uuid4(), site_url=f"https://{uuid.uuid4().hex}.example.test")
    session.add(tenant)
    await session.flush()
    now = datetime.now(tz=UTC)
    period_start = now - timedelta(minutes=1)
    session.add(
        TenantEntitlement(
            tenant_id=tenant.id,
            plan_code="beta",
            allowance_version="sweep-v1",
            allowance_jobs=allowance,
            period_start=period_start,
            period_end=now + timedelta(hours=1),
            status=EntitlementStatus.BETA_ACTIVE,
            source="unit-test",
        )
    )
    session.add(
        GlobalUsageAdmissionState(
            id=GLOBAL_USAGE_ADMISSION_STATE_ID,
            period_start=datetime(now.year, now.month, now.day, tzinfo=UTC),
            period_end=datetime(now.year, now.month, now.day, tzinfo=UTC) + timedelta(days=1),
            daily_cost_limit=DEFAULT_GLOBAL_DAILY_COST_LIMIT,
            daily_cost_units=0,
            inflight_limit=DEFAULT_GLOBAL_INFLIGHT_LIMIT,
            inflight_units=0,
            queue_limit=DEFAULT_GLOBAL_QUEUE_LIMIT,
            queue_depth=0,
            queue_byte_limit=DEFAULT_GLOBAL_QUEUE_BYTE_LIMIT,
            queue_bytes=0,
            stop_requested=False,
            fence_epoch=DEFAULT_GLOBAL_FENCE_EPOCH,
            config_version=DEFAULT_GLOBAL_CONFIG_VERSION,
            updated_at=now,
        )
    )
    await session.flush()
    return tenant


def _age_reservation(reservation: UsageReservation, *, seconds: float) -> None:
    reservation.reserved_at = datetime.now(tz=UTC) - timedelta(seconds=seconds)


async def _advance_epoch(session, *, delta: int = 1) -> int:
    state = await session.get(GlobalUsageAdmissionState, GLOBAL_USAGE_ADMISSION_STATE_ID)
    assert state is not None
    state.fence_epoch = int(state.fence_epoch) + delta
    await session.flush()
    return int(state.fence_epoch)


def test_public_settle_and_sweep_signatures_are_frozen() -> None:
    settle = inspect.signature(settle_usage_job)
    assert list(settle.parameters) == [
        "session",
        "tenant_id",
        "job_id",
        "fence_token",
        "allow_missing_job_release",
    ]
    sweep = inspect.signature(sweep_stale_reservations)
    assert list(sweep.parameters) == [
        "session",
        "stale_after_seconds",
        "max_batches",
        "batch_size",
        "no_progress_limit",
    ]
    recover = inspect.signature(recover_usage_job)
    assert list(recover.parameters) == ["session", "tenant_id", "job_id", "allow_missing_job_release"]


@pytest.mark.asyncio
async def test_sweeper_does_not_release_active_describe_or_scan_work() -> None:
    engine, sf, path = await _ledger_sessionmaker()
    try:
        async with sf() as session:
            tenant = await _seed_tenant(session)
            service = UsageAdmissionService(session)
            running_job = uuid.uuid4()
            pending_scan = uuid.uuid4()
            running_ticket = await service.reserve(
                tenant.id,
                idempotency_key="op-running",
                job_id=str(running_job),
                cost_units=1,
                operation_id="op-running",
                request_fingerprint="fp-running",
            )
            scan_ticket = await service.reserve(
                tenant.id,
                idempotency_key="op-scan",
                job_id=str(pending_scan),
                cost_units=1,
                operation_id="op-scan",
                request_fingerprint="fp-scan",
            )
            session.add(
                DescribeRun(
                    id=running_job,
                    tenant_id=tenant.id,
                    run_kind=RunKind.BULK,
                    status=DescribeRunStatus.RUNNING,
                    phase=DescribeRunPhase.DESCRIBING,
                    media_ids=[1],
                    total_items=1,
                    started_at=datetime.now(tz=UTC),
                )
            )
            session.add(
                IdentityScanJob(
                    id=pending_scan,
                    tenant_id=tenant.id,
                    status=JobStatus.PENDING,
                    media_ids=[1],
                    total_media=1,
                )
            )
            await session.flush()
            _age_reservation(await session.get(UsageReservation, running_ticket.reservation_id), seconds=3600)
            _age_reservation(await session.get(UsageReservation, scan_ticket.reservation_id), seconds=3600)
            report = await sweep_stale_reservations(session, stale_after_seconds=60, max_batches=3, batch_size=10)
            await session.commit()

        async with sf() as session:
            running_row = await session.get(UsageReservation, running_ticket.reservation_id)
            scan_row = await session.get(UsageReservation, scan_ticket.reservation_id)
            assert running_row is not None and running_row.status == UsageReservationStatus.RESERVED
            assert scan_row is not None and scan_row.status == UsageReservationStatus.RESERVED
            assert report.skipped_active >= 2
            assert report.released == 0
            assert report.exit_code == 0
            assert MISSING_GENERATION_FENCE_CONTRACT in report.notes
    finally:
        await engine.dispose()
        os.unlink(path)


@pytest.mark.asyncio
async def test_sweeper_releases_stale_reservation_when_job_never_persisted() -> None:
    engine, sf, path = await _ledger_sessionmaker()
    try:
        async with sf() as session:
            tenant = await _seed_tenant(session)
            ticket = await UsageAdmissionService(session).reserve(
                tenant.id,
                idempotency_key="op-missing",
                job_id=str(uuid.uuid4()),
                cost_units=1,
                operation_id="op-missing",
                request_fingerprint="fp-missing",
            )
            _age_reservation(await session.get(UsageReservation, ticket.reservation_id), seconds=120)
            report = await sweep_stale_reservations(session, stale_after_seconds=30, max_batches=2, batch_size=5)
            await session.commit()
        async with sf() as session:
            row = await session.get(UsageReservation, ticket.reservation_id)
            assert row is not None and row.status == UsageReservationStatus.RELEASED
            assert report.released == 1
            assert report.exit_code == 0
    finally:
        await engine.dispose()
        os.unlink(path)


@pytest.mark.asyncio
async def test_cancel_before_pickup_releases_and_stale_fence_is_rejected() -> None:
    engine, sf, path = await _ledger_sessionmaker()
    try:
        async with sf() as session:
            tenant = await _seed_tenant(session)
            job_id = uuid.uuid4()
            ticket = await UsageAdmissionService(session).reserve(
                tenant.id,
                idempotency_key="op-cancel",
                job_id=str(job_id),
                cost_units=1,
                operation_id="op-cancel",
                request_fingerprint="fp-cancel",
            )
            session.add(
                DescribeRun(
                    id=job_id,
                    tenant_id=tenant.id,
                    run_kind=RunKind.SINGLE,
                    status=DescribeRunStatus.CANCELLED,
                    phase=DescribeRunPhase.CANCELLED,
                    media_ids=[1],
                    total_items=1,
                )
            )
            await session.flush()
            settlement = UsageSettlementService(session)
            released = await settlement.settle_job(
                tenant_id=tenant.id, job_id=str(job_id), fence_token=ticket.fence_token
            )
            assert released.outcome is SettlementOutcome.RELEASED
            stale = await settlement.settle_ticket(ticket, action=SettlementOutcome.COMMITTED, fence_token="old-fence")
            assert stale.outcome is SettlementOutcome.REJECTED
            wrong_tenant = await settlement.settle_job(
                tenant_id=uuid.uuid4(),
                job_id=str(job_id),
                fence_token=ticket.fence_token,
            )
            assert wrong_tenant.outcome is SettlementOutcome.MISSING
            await session.commit()
        async with sf() as session:
            row = await session.get(UsageReservation, ticket.reservation_id)
            assert row is not None and row.status == UsageReservationStatus.RELEASED
    finally:
        await engine.dispose()
        os.unlink(path)


@pytest.mark.asyncio
async def test_after_pickup_failure_is_conservatively_charged() -> None:
    engine, sf, path = await _ledger_sessionmaker()
    try:
        async with sf() as session:
            tenant = await _seed_tenant(session)
            job_id = uuid.uuid4()
            ticket = await UsageAdmissionService(session).reserve(
                tenant.id,
                idempotency_key="op-fail",
                job_id=str(job_id),
                cost_units=1,
                operation_id="op-fail",
                request_fingerprint="fp-fail",
            )
            session.add(
                DescribeRun(
                    id=job_id,
                    tenant_id=tenant.id,
                    run_kind=RunKind.BULK,
                    status=DescribeRunStatus.FAILED,
                    phase=DescribeRunPhase.FAILED,
                    media_ids=[1],
                    total_items=1,
                    started_at=datetime.now(tz=UTC),
                    queue_ms=12.0,
                )
            )
            await session.flush()
            captured = ticket.fence_token
            result = await UsageSettlementService(session).settle_job(
                tenant_id=tenant.id,
                job_id=str(job_id),
                fence_token=captured,
            )
            again = await UsageSettlementService(session).settle_job(
                tenant_id=tenant.id,
                job_id=str(job_id),
                fence_token=captured,
            )
            await session.commit()
            assert result.outcome is SettlementOutcome.COMMITTED
            assert again.outcome is SettlementOutcome.ALREADY_SETTLED
        async with sf() as session:
            row = await session.get(UsageReservation, ticket.reservation_id)
            assert row is not None and row.status == UsageReservationStatus.COMMITTED
    finally:
        await engine.dispose()
        os.unlink(path)


@pytest.mark.asyncio
async def test_completed_with_errors_without_start_releases_and_started_commits() -> None:
    engine, sf, path = await _ledger_sessionmaker()
    try:
        async with sf() as session:
            tenant = await _seed_tenant(session)
            never_id = uuid.uuid4()
            started_id = uuid.uuid4()
            never_ticket = await UsageAdmissionService(session).reserve(
                tenant.id,
                idempotency_key="op-cwe-never",
                job_id=str(never_id),
                cost_units=1,
                operation_id="op-cwe-never",
                request_fingerprint="fp-cwe-never",
            )
            started_ticket = await UsageAdmissionService(session).reserve(
                tenant.id,
                idempotency_key="op-cwe-started",
                job_id=str(started_id),
                cost_units=1,
                operation_id="op-cwe-started",
                request_fingerprint="fp-cwe-started",
            )
            session.add(
                DescribeRun(
                    id=never_id,
                    tenant_id=tenant.id,
                    run_kind=RunKind.BULK,
                    status=DescribeRunStatus.COMPLETED_WITH_ERRORS,
                    phase=DescribeRunPhase.COMPLETE,
                    media_ids=[1],
                    total_items=1,
                )
            )
            session.add(
                DescribeRun(
                    id=started_id,
                    tenant_id=tenant.id,
                    run_kind=RunKind.BULK,
                    status=DescribeRunStatus.COMPLETED_WITH_ERRORS,
                    phase=DescribeRunPhase.COMPLETE,
                    media_ids=[2],
                    total_items=1,
                    started_at=datetime.now(tz=UTC),
                    queue_ms=8.0,
                )
            )
            await session.flush()
            settlement = UsageSettlementService(session)
            never = await settlement.settle_job(
                tenant_id=tenant.id,
                job_id=str(never_id),
                fence_token=never_ticket.fence_token,
            )
            started = await settlement.settle_job(
                tenant_id=tenant.id,
                job_id=str(started_id),
                fence_token=started_ticket.fence_token,
            )
            ambiguous_id = uuid.uuid4()
            ambiguous_ticket = await UsageAdmissionService(session).reserve(
                tenant.id,
                idempotency_key="op-completed-nostart",
                job_id=str(ambiguous_id),
                cost_units=1,
                operation_id="op-completed-nostart",
                request_fingerprint="fp-completed-nostart",
            )
            session.add(
                DescribeRun(
                    id=ambiguous_id,
                    tenant_id=tenant.id,
                    run_kind=RunKind.SINGLE,
                    status=DescribeRunStatus.COMPLETED,
                    phase=DescribeRunPhase.COMPLETE,
                    media_ids=[3],
                    total_items=1,
                )
            )
            await session.flush()
            ambiguous = await settlement.settle_job(
                tenant_id=tenant.id,
                job_id=str(ambiguous_id),
                fence_token=ambiguous_ticket.fence_token,
            )
            await session.commit()
            assert never.outcome is SettlementOutcome.RELEASED
            assert started.outcome is SettlementOutcome.COMMITTED
            assert ambiguous.outcome is SettlementOutcome.FAIL_CLOSED
        async with sf() as session:
            never_row = await session.get(UsageReservation, never_ticket.reservation_id)
            started_row = await session.get(UsageReservation, started_ticket.reservation_id)
            ambiguous_row = await session.get(UsageReservation, ambiguous_ticket.reservation_id)
            assert never_row is not None and never_row.status == UsageReservationStatus.RELEASED
            assert started_row is not None and started_row.status == UsageReservationStatus.COMMITTED
            assert ambiguous_row is not None and ambiguous_row.status == UsageReservationStatus.RESERVED
    finally:
        await engine.dispose()
        os.unlink(path)


@pytest.mark.asyncio
async def test_epoch_advance_rejects_captured_worker_token_without_substitution() -> None:
    engine, sf, path = await _ledger_sessionmaker()
    try:
        async with sf() as session:
            tenant = await _seed_tenant(session)
            job_id = uuid.uuid4()
            ticket = await UsageAdmissionService(session).reserve(
                tenant.id,
                idempotency_key="op-stale-worker",
                job_id=str(job_id),
                cost_units=1,
                operation_id="op-stale-worker",
                request_fingerprint="fp-stale-worker",
            )
            captured = ticket.fence_token
            session.add(
                DescribeRun(
                    id=job_id,
                    tenant_id=tenant.id,
                    run_kind=RunKind.SINGLE,
                    status=DescribeRunStatus.CANCELLED,
                    phase=DescribeRunPhase.CANCELLED,
                    media_ids=[1],
                    total_items=1,
                )
            )
            await session.flush()
            await _advance_epoch(session)
            rejected = await UsageSettlementService(session).settle_job(
                tenant_id=tenant.id,
                job_id=str(job_id),
                fence_token=captured,
            )
            replay = await UsageAdmissionService(session).reserve(
                tenant.id,
                idempotency_key="op-stale-worker",
                job_id=str(uuid.uuid4()),
                cost_units=1,
                operation_id="op-stale-worker",
                request_fingerprint="fp-stale-worker",
            )
            await session.commit()
            assert rejected.outcome is SettlementOutcome.REJECTED
            assert replay.fence_token == captured
        async with sf() as session:
            row = await session.get(UsageReservation, ticket.reservation_id)
            assert row is not None and row.status == UsageReservationStatus.RESERVED
            assert row.fence_token == captured
    finally:
        await engine.dispose()
        os.unlink(path)


@pytest.mark.asyncio
async def test_trusted_recovery_settles_stale_terminal_exactly_once() -> None:
    engine, sf, path = await _ledger_sessionmaker()
    try:
        async with sf() as session:
            tenant = await _seed_tenant(session)
            job_id = uuid.uuid4()
            ticket = await UsageAdmissionService(session).reserve(
                tenant.id,
                idempotency_key="op-recover",
                job_id=str(job_id),
                cost_units=1,
                operation_id="op-recover",
                request_fingerprint="fp-recover",
            )
            captured = ticket.fence_token
            session.add(
                DescribeRun(
                    id=job_id,
                    tenant_id=tenant.id,
                    run_kind=RunKind.BULK,
                    status=DescribeRunStatus.COMPLETED_WITH_ERRORS,
                    phase=DescribeRunPhase.COMPLETE,
                    media_ids=[1],
                    total_items=1,
                )
            )
            await session.flush()
            new_epoch = await _advance_epoch(session)
            before = await session.get(GlobalUsageAdmissionState, GLOBAL_USAGE_ADMISSION_STATE_ID)
            assert before is not None
            inflight_before = int(before.inflight_units)
            daily_before = int(before.daily_cost_units)
            first = await recover_usage_job(session, tenant_id=tenant.id, job_id=str(job_id))
            second = await recover_usage_job(session, tenant_id=tenant.id, job_id=str(job_id))
            stale = await UsageSettlementService(session).settle_job(
                tenant_id=tenant.id,
                job_id=str(job_id),
                fence_token=captured,
            )
            mismatch = await UsageSettlementService(session).recover_job(
                tenant_id=tenant.id,
                job_id=str(job_id),
                operation_id="other-op",
            )
            await session.commit()
            assert first.outcome is SettlementOutcome.RELEASED
            assert second.outcome is SettlementOutcome.ALREADY_SETTLED
            assert stale.outcome is SettlementOutcome.REJECTED
            assert mismatch.outcome is SettlementOutcome.REJECTED
            after = await session.get(GlobalUsageAdmissionState, GLOBAL_USAGE_ADMISSION_STATE_ID)
            assert after is not None
            assert int(after.inflight_units) == inflight_before - 1
            assert int(after.daily_cost_units) == daily_before - 1
            assert int(after.fence_epoch) == new_epoch
        async with sf() as session:
            row = await session.get(UsageReservation, ticket.reservation_id)
            assert row is not None and row.status == UsageReservationStatus.RELEASED
            assert row.fence_token != captured
            epoch_text, _token = row.fence_token.split(":", 1)
            assert int(epoch_text) == new_epoch
    finally:
        await engine.dispose()
        os.unlink(path)


@pytest.mark.asyncio
async def test_sweep_recovers_never_picked_terminal_and_stalls_on_ambiguous() -> None:
    engine, sf, path = await _ledger_sessionmaker()
    try:
        async with sf() as session:
            tenant = await _seed_tenant(session)
            ambiguous_id = uuid.uuid4()
            terminal_id = uuid.uuid4()
            ambiguous_ticket = await UsageAdmissionService(session).reserve(
                tenant.id,
                idempotency_key="op-ambiguous-complete",
                job_id=str(ambiguous_id),
                cost_units=1,
                operation_id="op-ambiguous-complete",
                request_fingerprint="fp-ambiguous-complete",
            )
            terminal_ticket = await UsageAdmissionService(session).reserve(
                tenant.id,
                idempotency_key="op-sweep-cwe",
                job_id=str(terminal_id),
                cost_units=1,
                operation_id="op-sweep-cwe",
                request_fingerprint="fp-sweep-cwe",
            )
            session.add(
                DescribeRun(
                    id=ambiguous_id,
                    tenant_id=tenant.id,
                    run_kind=RunKind.SINGLE,
                    status=DescribeRunStatus.COMPLETED,
                    phase=DescribeRunPhase.COMPLETE,
                    media_ids=[1],
                    total_items=1,
                )
            )
            session.add(
                DescribeRun(
                    id=terminal_id,
                    tenant_id=tenant.id,
                    run_kind=RunKind.SINGLE,
                    status=DescribeRunStatus.COMPLETED_WITH_ERRORS,
                    phase=DescribeRunPhase.COMPLETE,
                    media_ids=[2],
                    total_items=1,
                )
            )
            await session.flush()
            _age_reservation(await session.get(UsageReservation, ambiguous_ticket.reservation_id), seconds=180)
            _age_reservation(await session.get(UsageReservation, terminal_ticket.reservation_id), seconds=180)
            await _advance_epoch(session)
            report = await sweep_stale_reservations(
                session,
                stale_after_seconds=30,
                max_batches=4,
                batch_size=10,
                no_progress_limit=2,
            )
            await session.commit()
            assert report.released == 1
            assert report.committed == 0
            assert report.fail_closed >= 1
            assert report.stalled is True
            assert report.exit_code == 1
        async with sf() as session:
            statuses = {row.job_id: row.status for row in (await session.execute(select(UsageReservation))).scalars()}
            assert statuses[str(terminal_id)] == UsageReservationStatus.RELEASED
            assert statuses[str(ambiguous_id)] == UsageReservationStatus.RESERVED
    finally:
        await engine.dispose()
        os.unlink(path)


@pytest.mark.asyncio
async def test_sweep_rejected_only_batch_stalls_nonzero() -> None:
    engine, sf, path = await _ledger_sessionmaker()
    try:
        async with sf() as session:
            tenant = await _seed_tenant(session)
            job_id = uuid.uuid4()
            ticket = await UsageAdmissionService(session).reserve(
                tenant.id,
                idempotency_key="op-only-reject",
                job_id=str(job_id),
                cost_units=1,
                operation_id="op-only-reject",
                request_fingerprint="fp-only-reject",
            )
            _age_reservation(await session.get(UsageReservation, ticket.reservation_id), seconds=240)

            async def _reject(self, **_kwargs):
                return SettlementResult(
                    SettlementOutcome.REJECTED,
                    reservation_id=ticket.reservation_id,
                    detail="forced reject",
                )

            original_settle = UsageSettlementService.settle_job
            original_recover = getattr(UsageSettlementService, "recover_job", None)
            UsageSettlementService.settle_job = _reject  # type: ignore[method-assign]
            UsageSettlementService.recover_job = _reject  # type: ignore[method-assign]
            try:
                report = await sweep_stale_reservations(
                    session,
                    stale_after_seconds=30,
                    max_batches=5,
                    batch_size=10,
                    no_progress_limit=2,
                )
            finally:
                UsageSettlementService.settle_job = original_settle  # type: ignore[method-assign]
                if original_recover is None:
                    delattr(UsageSettlementService, "recover_job")
                else:
                    UsageSettlementService.recover_job = original_recover  # type: ignore[method-assign]
            await session.commit()
            assert report.rejected >= 1
            assert report.released == 0
            assert report.committed == 0
            assert report.stalled is True
            assert report.exit_code == 1
            assert report.no_progress_cycles >= 2
        async with sf() as session:
            row = await session.get(UsageReservation, ticket.reservation_id)
            assert row is not None and row.status == UsageReservationStatus.RESERVED
    finally:
        await engine.dispose()
        os.unlink(path)
