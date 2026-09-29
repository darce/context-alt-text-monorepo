"""The scan worker sweeps stale usage reservations on a bounded schedule."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import recognition.worker.scan_worker as scan_worker_module
from recognition.application.services.usage_settlement_service import UsageSettlementService
from recognition.worker.scan_worker import ScanWorker, ScanWorkerConfig
from scripts.usage_reservation_sweeper import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_MAX_BATCHES,
    DEFAULT_NO_PROGRESS_LIMIT,
    DEFAULT_STALE_AFTER_SECONDS,
)


class _StopLoop(Exception):
    pass


class _Session:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class _SessionFactory:
    def __init__(self) -> None:
        self.sessions: list[_Session] = []

    def __call__(self) -> _Session:
        session = _Session()
        self.sessions.append(session)
        return session


class _Repository:
    async def reclaim_stale_items(self, **kwargs) -> None:
        return None


class _Queue:
    async def terminate_stalled_jobs_with_identities(self, **kwargs) -> list[object]:
        return []


def _stub_scan_cycle(monkeypatch, worker: ScanWorker, sessions: _SessionFactory, probe_calls: list[int]) -> None:
    async def no_op(*args, **kwargs):
        return None

    async def no_pending(*, session, now) -> bool:
        return False

    async def no_rls_bypass(session) -> None:
        return None

    monkeypatch.setattr(worker, "_session_factory", sessions)
    monkeypatch.setattr(worker, "_refresh_mv_if_needed", no_op)
    monkeypatch.setattr(worker, "_process_pending_clustering_jobs", no_pending)
    monkeypatch.setattr(worker, "_can_claim_scan_items", lambda: False)

    async def probe() -> None:
        probe_calls.append(1)

    monkeypatch.setattr(worker, "_probe_and_publish_embedding_runtime_capability", probe)
    monkeypatch.setattr(scan_worker_module, "enable_rls_bypass", no_rls_bypass)
    monkeypatch.setattr(scan_worker_module, "SqlAlchemyScanQueueRepository", lambda session: _Repository())
    monkeypatch.setattr(scan_worker_module, "ScanQueueService", lambda repo: _Queue())


@pytest.mark.asyncio
async def test_worker_sweeps_first_cycle_then_waits_for_interval(monkeypatch) -> None:
    monotonic_now = 0.0
    probe_calls: list[int] = []
    sweep_calls: list[tuple[float, dict[str, object]]] = []
    sessions = _SessionFactory()
    worker = ScanWorker(
        ScanWorkerConfig(
            postgres_dsn="sqlite+aiosqlite:///:memory:",
            poll_interval_seconds=1,
            usage_sweep_interval_seconds=10,
        ),
        clock=lambda: monotonic_now,
    )
    _stub_scan_cycle(monkeypatch, worker, sessions, probe_calls)

    async def sweep(self, **kwargs):
        sweep_calls.append((monotonic_now, kwargs))
        return SimpleNamespace()

    monkeypatch.setattr(UsageSettlementService, "sweep_stale_reservations", sweep)

    sleeps = 0

    async def advance_clock(seconds: float) -> None:
        nonlocal monotonic_now, sleeps
        sleeps += 1
        monotonic_now += 4
        if sleeps == 4:
            raise _StopLoop

    monkeypatch.setattr(scan_worker_module.asyncio, "sleep", advance_clock)
    try:
        with pytest.raises(_StopLoop):
            await worker.run_forever()
    finally:
        await worker.__aexit__(None, None, None)

    assert len(probe_calls) == 4
    assert [at for at, _ in sweep_calls] == [0.0, 12.0]
    assert sweep_calls[0][1] == {
        "stale_after_seconds": DEFAULT_STALE_AFTER_SECONDS,
        "max_batches": DEFAULT_MAX_BATCHES,
        "batch_size": DEFAULT_BATCH_SIZE,
        "no_progress_limit": DEFAULT_NO_PROGRESS_LIMIT,
    }
    assert sessions.sessions[0].commits == 1


@pytest.mark.asyncio
async def test_failed_sweep_is_logged_and_next_scan_cycle_runs(monkeypatch, caplog) -> None:
    monotonic_now = 0.0
    probe_calls: list[int] = []
    sweep_sessions: list[_Session] = []
    sessions = _SessionFactory()
    worker = ScanWorker(
        ScanWorkerConfig(
            postgres_dsn="sqlite+aiosqlite:///:memory:",
            poll_interval_seconds=1,
            usage_sweep_interval_seconds=10,
        ),
        clock=lambda: monotonic_now,
    )
    _stub_scan_cycle(monkeypatch, worker, sessions, probe_calls)

    async def failing_sweep(self, **kwargs):
        sweep_sessions.append(self._session)
        raise RuntimeError("sweep failed")

    monkeypatch.setattr(UsageSettlementService, "sweep_stale_reservations", failing_sweep)

    sleeps = 0

    async def advance_clock(seconds: float) -> None:
        nonlocal monotonic_now, sleeps
        sleeps += 1
        monotonic_now += 1
        if sleeps == 2:
            raise _StopLoop

    monkeypatch.setattr(scan_worker_module.asyncio, "sleep", advance_clock)
    try:
        with pytest.raises(_StopLoop):
            await worker.run_forever()
    finally:
        await worker.__aexit__(None, None, None)

    assert len(probe_calls) == 2
    assert len(sweep_sessions) == 1
    assert sweep_sessions[0].rollbacks == 1
    assert "[worker] usage reservation sweep failed" in caplog.text


@pytest.mark.parametrize("interval", ["invalid", "0", "-1"])
def test_invalid_usage_sweep_interval_refuses_worker_start(monkeypatch, interval: str) -> None:
    monkeypatch.setenv("RECOGNITION_USAGE_SWEEP_INTERVAL_S", interval)

    with pytest.raises(ValueError, match="RECOGNITION_USAGE_SWEEP_INTERVAL_S"):
        ScanWorkerConfig(postgres_dsn="sqlite+aiosqlite:///:memory:")
