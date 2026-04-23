"""Unit tests for the clustering-dedicated circuit breaker (E15-3a-BR-21 Slice 3).

Separate from the SLR-3 session-dependency breaker -- this breaker counts
``QueryCanceledError`` on ``POST /recognition/clustering/jobs`` and is the sole
fail-fast surface for that route (see task plan PLAN-09).
"""

from __future__ import annotations

import time

import pytest

from recognition.interface_adapters.http.deps.clustering_circuit_breaker import (
    ClusteringBreakerSnapshot,
    ClusteringBreakerState,
    ClusteringCircuitBreaker,
)


class _FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _build_breaker(clock: _FakeClock) -> ClusteringCircuitBreaker:
    return ClusteringCircuitBreaker(
        failure_threshold=3,
        window_seconds=30.0,
        cooldown_seconds=30.0,
        time_source=clock,
    )


def test_closed_breaker_admits_requests() -> None:
    clock = _FakeClock()
    breaker = _build_breaker(clock)

    assert breaker.allow_request() is True
    snapshot = breaker.snapshot()
    assert snapshot.state is ClusteringBreakerState.CLOSED
    assert snapshot.failure_count == 0


def test_three_failures_in_window_opens_breaker() -> None:
    clock = _FakeClock()
    breaker = _build_breaker(clock)

    breaker.record_failure()
    clock.advance(1.0)
    breaker.record_failure()
    clock.advance(1.0)
    breaker.record_failure()

    assert breaker.snapshot().state is ClusteringBreakerState.OPEN
    assert breaker.allow_request() is False


def test_failures_outside_window_do_not_open() -> None:
    clock = _FakeClock()
    breaker = _build_breaker(clock)

    breaker.record_failure()
    clock.advance(15.0)
    breaker.record_failure()
    # Slide past the window so the first failure ages out.
    clock.advance(16.0)
    breaker.record_failure()

    assert breaker.snapshot().state is ClusteringBreakerState.CLOSED
    assert breaker.allow_request() is True


def test_open_breaker_half_opens_after_cooldown_and_closes_on_success() -> None:
    clock = _FakeClock()
    breaker = _build_breaker(clock)
    breaker.force_open()

    # Still open during cooldown.
    clock.advance(29.9)
    assert breaker.allow_request() is False
    assert breaker.snapshot().state is ClusteringBreakerState.OPEN

    # Cooldown elapsed -> half-open admits one trial.
    clock.advance(1.0)
    assert breaker.allow_request() is True
    assert breaker.snapshot().state is ClusteringBreakerState.HALF_OPEN

    breaker.record_success()
    assert breaker.snapshot().state is ClusteringBreakerState.CLOSED
    assert breaker.allow_request() is True


def test_half_open_trial_failure_reopens_breaker() -> None:
    clock = _FakeClock()
    breaker = _build_breaker(clock)
    breaker.force_open()

    clock.advance(31.0)
    assert breaker.allow_request() is True  # transitions to HALF_OPEN
    breaker.record_failure()

    assert breaker.snapshot().state is ClusteringBreakerState.OPEN
    assert breaker.allow_request() is False


def test_record_success_resets_failure_count() -> None:
    clock = _FakeClock()
    breaker = _build_breaker(clock)
    breaker.record_failure()
    breaker.record_failure()

    breaker.record_success()

    snapshot = breaker.snapshot()
    assert snapshot.state is ClusteringBreakerState.CLOSED
    assert snapshot.failure_count == 0


def test_allow_request_fast_path_under_10ms_when_open() -> None:
    clock = _FakeClock()
    breaker = _build_breaker(clock)
    breaker.force_open()

    started = time.perf_counter()
    for _ in range(1000):
        breaker.allow_request()
    elapsed_ms = (time.perf_counter() - started) * 1000

    # Fast-path cost is per-call; budget generously: even 1000 calls comfortably
    # fit under 10ms on CI. The plan's "<10ms" SLO is per-call, this asserts the
    # fast path is not accidentally performing IO.
    assert elapsed_ms < 10, f"1000 open-state admission checks took {elapsed_ms:.2f}ms"


def test_snapshot_is_immutable_view() -> None:
    clock = _FakeClock()
    breaker = _build_breaker(clock)
    breaker.record_failure()

    snap = breaker.snapshot()
    assert isinstance(snap, ClusteringBreakerSnapshot)
    with pytest.raises(Exception):  # frozen dataclass -> FrozenInstanceError / AttributeError
        snap.failure_count = 99  # type: ignore[misc]
