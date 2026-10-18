"""Unit tests for the shared adapter circuit breaker."""

from __future__ import annotations

import pytest

from recognition.application.integrations.circuit_breaker import (
    AdapterBreakerConfig,
    AdapterBreakerOpenError,
    AdapterBreakerState,
    AdapterCircuitBreaker,
)


class ManualClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.mark.asyncio
async def test_opens_after_failure_threshold_and_fast_fails_while_open() -> None:
    clock = ManualClock()
    breaker = AdapterCircuitBreaker(
        adapter_name="insightface",
        config=AdapterBreakerConfig(
            failure_count_threshold=2,
            failure_window_seconds=60.0,
            half_open_probe_count=1,
            success_close_threshold=1,
            open_state_cooldown_seconds=30.0,
        ),
        time_source=clock,
    )

    async def fail() -> str:
        raise RuntimeError("boom")

    for _ in range(2):
        with pytest.raises(RuntimeError):
            await breaker.call(fail)

    assert breaker.snapshot().state is AdapterBreakerState.OPEN

    with pytest.raises(AdapterBreakerOpenError):
        await breaker.call(fail)


@pytest.mark.asyncio
async def test_half_open_success_closes_breaker() -> None:
    clock = ManualClock()
    breaker = AdapterCircuitBreaker(
        adapter_name="insightface",
        config=AdapterBreakerConfig(
            failure_count_threshold=1,
            failure_window_seconds=60.0,
            half_open_probe_count=1,
            success_close_threshold=1,
            open_state_cooldown_seconds=10.0,
        ),
        time_source=clock,
    )

    async def fail() -> str:
        raise RuntimeError("boom")

    async def succeed() -> str:
        return "ok"

    with pytest.raises(RuntimeError):
        await breaker.call(fail)

    assert breaker.snapshot().state is AdapterBreakerState.OPEN

    clock.advance(11.0)
    result = await breaker.call(succeed)

    assert result == "ok"
    assert breaker.snapshot().state is AdapterBreakerState.CLOSED


@pytest.mark.asyncio
async def test_half_open_failure_reopens_breaker() -> None:
    clock = ManualClock()
    breaker = AdapterCircuitBreaker(
        adapter_name="insightface",
        config=AdapterBreakerConfig(
            failure_count_threshold=1,
            failure_window_seconds=60.0,
            half_open_probe_count=1,
            success_close_threshold=1,
            open_state_cooldown_seconds=10.0,
        ),
        time_source=clock,
    )

    async def fail() -> str:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await breaker.call(fail)

    clock.advance(11.0)

    with pytest.raises(RuntimeError):
        await breaker.call(fail)

    assert breaker.snapshot().state is AdapterBreakerState.OPEN
