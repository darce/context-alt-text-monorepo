"""Unit tests for the HTTP session dependency circuit breaker."""

from __future__ import annotations

from recognition.interface_adapters.http.deps.circuit_breaker import BreakerState, SessionDependencyCircuitBreaker


class FakeClock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def test_breaker_opens_after_threshold_failures_within_window() -> None:
    clock = FakeClock()
    breaker = SessionDependencyCircuitBreaker(
        failure_threshold=3,
        window_seconds=30,
        half_open_after_seconds=10,
        time_source=clock,
    )

    breaker.record_failure()
    clock.now = 5
    breaker.record_failure()
    clock.now = 10
    breaker.record_failure()

    snapshot = breaker.snapshot()

    assert snapshot.state is BreakerState.OPEN
    assert snapshot.failure_count == 3
    assert snapshot.is_open is True


def test_breaker_prunes_failures_outside_window() -> None:
    clock = FakeClock()
    breaker = SessionDependencyCircuitBreaker(
        failure_threshold=3,
        window_seconds=10,
        half_open_after_seconds=5,
        time_source=clock,
    )

    breaker.record_failure()
    clock.now = 11
    breaker.record_failure()
    clock.now = 12
    breaker.record_failure()

    snapshot = breaker.snapshot()

    assert snapshot.state is BreakerState.CLOSED
    assert snapshot.failure_count == 2


def test_breaker_allows_single_half_open_probe_after_cooldown() -> None:
    clock = FakeClock()
    breaker = SessionDependencyCircuitBreaker(
        failure_threshold=3,
        window_seconds=30,
        half_open_after_seconds=10,
        time_source=clock,
    )
    breaker.force_open()

    assert breaker.allow_request() is False

    clock.now = 11

    assert breaker.allow_request() is True
    assert breaker.snapshot().state is BreakerState.HALF_OPEN
    assert breaker.allow_request() is False


def test_half_open_success_closes_breaker() -> None:
    clock = FakeClock()
    breaker = SessionDependencyCircuitBreaker(
        failure_threshold=3,
        window_seconds=30,
        half_open_after_seconds=10,
        time_source=clock,
    )
    breaker.force_open()
    clock.now = 11

    assert breaker.allow_request() is True

    breaker.record_success()

    snapshot = breaker.snapshot()
    assert snapshot.state is BreakerState.CLOSED
    assert snapshot.failure_count == 0


def test_half_open_failure_reopens_breaker() -> None:
    clock = FakeClock()
    breaker = SessionDependencyCircuitBreaker(
        failure_threshold=3,
        window_seconds=30,
        half_open_after_seconds=10,
        time_source=clock,
    )
    breaker.force_open()
    clock.now = 11

    assert breaker.allow_request() is True

    breaker.record_failure()

    snapshot = breaker.snapshot()
    assert snapshot.state is BreakerState.OPEN
    assert snapshot.failure_count >= 1
