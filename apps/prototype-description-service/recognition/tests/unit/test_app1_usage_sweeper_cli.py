"""CLI maintenance must settle through UsageSettlementService, never age-only release."""

from __future__ import annotations

import importlib.util
import io
import os
import sys
import tempfile
import uuid
from contextlib import redirect_stderr
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import Table
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import recognition.tests.conftest as _recognition_conftest
from db.models import UsageReservation
from db.models.base_imports import Base
from db.models.jobs import IdentityScanJob, IdentityScanJobItem
from db.models.portal_billing import GlobalUsageAdmissionState, TenantEntitlement
from db.models.scene import DescribeRun, DescribeRunItem
from db.models.tenant import Tenant
from recognition.application.services.usage_admission_service import UsageAdmissionService
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

_recognition_conftest.SQLITE_TEST_TABLE_EXCLUSIONS = _recognition_conftest.SQLITE_TEST_TABLE_EXCLUSIONS | {
    "billing_known_item_lease",
    "billing_reconciliation_cursor",
    "billing_reconciliation_item_progress",
    "billing_reconciliation_quarantine",
}

_SWEEPER_PATH = Path(__file__).resolve().parents[3] / "scripts" / "usage_reservation_sweeper.py"


def _load_sweeper():
    spec = importlib.util.spec_from_file_location("usage_reservation_sweeper", _SWEEPER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


async def _ledger_sessionmaker():
    path = os.path.join(tempfile.gettempdir(), f"app1_usage_sweep_cli_{uuid.uuid4().hex}.db")
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


async def _seed_tenant(session, *, allowance: int = 40):
    tenant = Tenant(id=uuid.uuid4(), site_url=f"https://{uuid.uuid4().hex}.example.test")
    session.add(tenant)
    await session.flush()
    now = datetime.now(tz=UTC)
    session.add(
        TenantEntitlement(
            tenant_id=tenant.id,
            plan_code="beta",
            allowance_version="cli-v1",
            allowance_jobs=allowance,
            period_start=now - timedelta(minutes=1),
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


@pytest.mark.asyncio
async def test_cli_does_not_release_live_aged_job() -> None:
    sweeper = _load_sweeper()
    engine, sf, path = await _ledger_sessionmaker()
    try:
        async with sf() as session:
            tenant = await _seed_tenant(session)
            job_id = uuid.uuid4()
            ticket = await UsageAdmissionService(session).reserve(
                tenant.id,
                idempotency_key="op-live",
                job_id=str(job_id),
                cost_units=1,
                operation_id="op-live",
                request_fingerprint="fp-live",
            )
            session.add(
                IdentityScanJob(
                    id=job_id,
                    tenant_id=tenant.id,
                    status=JobStatus.RUNNING,
                    media_ids=[1],
                    total_media=1,
                    started_at=datetime.now(tz=UTC),
                )
            )
            await session.flush()
            _age_reservation(await session.get(UsageReservation, ticket.reservation_id), seconds=3600)
            await session.commit()

        async with sf() as session:
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                code = await sweeper.run(
                    ["--stale-after-seconds", "30", "--max-batches", "3", "--batch-size", "10"],
                    session=session,
                )
            output = stderr.getvalue()
        async with sf() as session:
            row = await session.get(UsageReservation, ticket.reservation_id)
            assert row is not None and row.status == UsageReservationStatus.RESERVED
            assert code == 0
            assert "stalled=True" not in output.replace(" ", "")
            assert "released=0" in output
    finally:
        await engine.dispose()
        os.unlink(path)


@pytest.mark.asyncio
async def test_cli_releases_pre_pickup_terminal_and_charges_started() -> None:
    sweeper = _load_sweeper()
    engine, sf, path = await _ledger_sessionmaker()
    try:
        async with sf() as session:
            tenant = await _seed_tenant(session)
            never_id = uuid.uuid4()
            started_id = uuid.uuid4()
            never_ticket = await UsageAdmissionService(session).reserve(
                tenant.id,
                idempotency_key="op-never",
                job_id=str(never_id),
                cost_units=1,
                operation_id="op-never",
                request_fingerprint="fp-never",
            )
            started_ticket = await UsageAdmissionService(session).reserve(
                tenant.id,
                idempotency_key="op-started",
                job_id=str(started_id),
                cost_units=1,
                operation_id="op-started",
                request_fingerprint="fp-started",
            )
            session.add(
                DescribeRun(
                    id=never_id,
                    tenant_id=tenant.id,
                    run_kind=RunKind.BULK,
                    status=DescribeRunStatus.FAILED,
                    phase=DescribeRunPhase.FAILED,
                    media_ids=[1],
                    total_items=1,
                )
            )
            session.add(
                DescribeRun(
                    id=started_id,
                    tenant_id=tenant.id,
                    run_kind=RunKind.BULK,
                    status=DescribeRunStatus.FAILED,
                    phase=DescribeRunPhase.FAILED,
                    media_ids=[2],
                    total_items=1,
                    started_at=datetime.now(tz=UTC),
                    queue_ms=11.0,
                )
            )
            await session.flush()
            _age_reservation(await session.get(UsageReservation, never_ticket.reservation_id), seconds=180)
            _age_reservation(await session.get(UsageReservation, started_ticket.reservation_id), seconds=180)
            await session.commit()

        async with sf() as session:
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                code = await sweeper.run(
                    ["--stale-after-seconds", "30", "--max-batches", "3", "--batch-size", "10"],
                    session=session,
                )
            output = stderr.getvalue()
        async with sf() as session:
            never_row = await session.get(UsageReservation, never_ticket.reservation_id)
            started_row = await session.get(UsageReservation, started_ticket.reservation_id)
            assert never_row is not None and never_row.status == UsageReservationStatus.RELEASED
            assert started_row is not None and started_row.status == UsageReservationStatus.COMMITTED
            assert code == 0
            assert "released=1" in output
    finally:
        await engine.dispose()
        os.unlink(path)


@pytest.mark.asyncio
async def test_cli_status_output_reflects_nonzero_stall() -> None:
    sweeper = _load_sweeper()
    engine, sf, path = await _ledger_sessionmaker()
    try:
        async with sf() as session:
            tenant = await _seed_tenant(session)
            job_id = uuid.uuid4()
            ticket = await UsageAdmissionService(session).reserve(
                tenant.id,
                idempotency_key="op-ambiguous",
                job_id=str(job_id),
                cost_units=1,
                operation_id="op-ambiguous",
                request_fingerprint="fp-ambiguous",
            )
            session.add(
                DescribeRun(
                    id=job_id,
                    tenant_id=tenant.id,
                    run_kind=RunKind.SINGLE,
                    status=DescribeRunStatus.COMPLETED,
                    phase=DescribeRunPhase.COMPLETE,
                    media_ids=[1],
                    total_items=1,
                )
            )
            await session.flush()
            _age_reservation(await session.get(UsageReservation, ticket.reservation_id), seconds=240)
            await session.commit()

        async with sf() as session:
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                code = await sweeper.run(
                    [
                        "--stale-after-seconds",
                        "30",
                        "--max-batches",
                        "4",
                        "--batch-size",
                        "10",
                        "--no-progress-limit",
                        "2",
                    ],
                    session=session,
                )
            output = stderr.getvalue()
        async with sf() as session:
            row = await session.get(UsageReservation, ticket.reservation_id)
            assert row is not None and row.status == UsageReservationStatus.RESERVED
            assert code == 1
            assert "stalled=True" in output.replace(" ", "") or "stalled=True" in output
            assert "fail_closed=" in output or "failed=" in output
    finally:
        await engine.dispose()
        os.unlink(path)


@pytest.mark.asyncio
async def test_cli_zero_progress_on_active_work_is_healthy() -> None:
    sweeper = _load_sweeper()
    engine, sf, path = await _ledger_sessionmaker()
    try:
        async with sf() as session:
            tenant = await _seed_tenant(session)
            job_id = uuid.uuid4()
            ticket = await UsageAdmissionService(session).reserve(
                tenant.id,
                idempotency_key="op-pending",
                job_id=str(job_id),
                cost_units=1,
                operation_id="op-pending",
                request_fingerprint="fp-pending",
            )
            session.add(
                IdentityScanJob(
                    id=job_id,
                    tenant_id=tenant.id,
                    status=JobStatus.PENDING,
                    media_ids=[1],
                    total_media=1,
                )
            )
            await session.flush()
            _age_reservation(await session.get(UsageReservation, ticket.reservation_id), seconds=900)
            await session.commit()

        async with sf() as session:
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                code = await sweeper.run(
                    ["--stale-after-seconds", "30", "--max-batches", "2", "--no-progress-limit", "1"],
                    session=session,
                )
            output = stderr.getvalue()
        async with sf() as session:
            row = await session.get(UsageReservation, ticket.reservation_id)
            assert row is not None and row.status == UsageReservationStatus.RESERVED
            assert code == 0
            assert "stalled=True" not in output
    finally:
        await engine.dispose()
        os.unlink(path)
