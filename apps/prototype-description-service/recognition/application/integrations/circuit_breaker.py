"""Reusable in-process circuit breaker for external adapter calls."""

from __future__ import annotations

import time as _time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from threading import Lock
from typing import TypeVar

type TimeSource = Callable[[], float]

ResultT = TypeVar("ResultT")


class AdapterBreakerState(StrEnum):
    """Stable public state names for adapter breakers."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(frozen=True, slots=True)
class AdapterBreakerConfig:
    """Runtime knobs for adapter breaker state transitions."""

    failure_count_threshold: int
    failure_window_seconds: float
    half_open_probe_count: int
    success_close_threshold: int
    open_state_cooldown_seconds: float


@dataclass(frozen=True, slots=True)
class AdapterBreakerSnapshot:
    """Serializable view of current breaker state for tests and logging."""

    state: AdapterBreakerState
    failure_count: int
    is_open: bool


class AdapterBreakerOpenError(RuntimeError):
    """Raised when a breaker rejects calls while open or half-open saturated."""

    def __init__(self, adapter_name: str) -> None:
        super().__init__(f"Adapter circuit breaker is open for {adapter_name}")
        self.adapter_name = adapter_name


@dataclass(slots=True)
class AdapterCircuitBreaker:
    """Guard external adapter calls with an in-process state machine."""

    adapter_name: str
    config: AdapterBreakerConfig
    time_source: TimeSource = _time.monotonic
    state: AdapterBreakerState = AdapterBreakerState.CLOSED
    _failure_timestamps: deque[float] = field(default_factory=deque, init=False, repr=False)
    _opened_at: float | None = field(default=None, init=False, repr=False)
    _half_open_in_flight: int = field(default=0, init=False, repr=False)
    _half_open_successes: int = field(default=0, init=False, repr=False)
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    async def call(self, operation: Callable[[], Awaitable[ResultT]]) -> ResultT:
        """Execute an adapter operation if the breaker currently allows it."""

        self._enter_call()
        try:
            result = await operation()
        except Exception:
            self._record_failure()
            raise
        else:
            self._record_success()
            return result

    def snapshot(self) -> AdapterBreakerSnapshot:
        with self._lock:
            now = self.time_source()
            self._prune_failures(now)
            return AdapterBreakerSnapshot(
                state=self.state,
                failure_count=len(self._failure_timestamps),
                is_open=self.state is AdapterBreakerState.OPEN,
            )

    def _enter_call(self) -> None:
        with self._lock:
            now = self.time_source()
            self._prune_failures(now)

            if self.state is AdapterBreakerState.OPEN:
                if self._opened_at is None or (now - self._opened_at) < self.config.open_state_cooldown_seconds:
                    raise AdapterBreakerOpenError(self.adapter_name)
                self.state = AdapterBreakerState.HALF_OPEN
                self._half_open_in_flight = 0
                self._half_open_successes = 0

            if self.state is AdapterBreakerState.HALF_OPEN:
                if self._half_open_in_flight >= self.config.half_open_probe_count:
                    raise AdapterBreakerOpenError(self.adapter_name)
                self._half_open_in_flight += 1

    def _record_success(self) -> None:
        with self._lock:
            if self.state is AdapterBreakerState.HALF_OPEN:
                self._half_open_in_flight = max(0, self._half_open_in_flight - 1)
                self._half_open_successes += 1
                if self._half_open_successes >= self.config.success_close_threshold:
                    self.state = AdapterBreakerState.CLOSED
                    self._opened_at = None
                    self._half_open_successes = 0
                    self._half_open_in_flight = 0
                    self._failure_timestamps.clear()
                return

            self.state = AdapterBreakerState.CLOSED
            self._opened_at = None
            self._failure_timestamps.clear()

    def _record_failure(self) -> None:
        with self._lock:
            now = self.time_source()
            self._prune_failures(now)

            if self.state is AdapterBreakerState.HALF_OPEN:
                self._half_open_in_flight = max(0, self._half_open_in_flight - 1)
                self._half_open_successes = 0
                self.state = AdapterBreakerState.OPEN
                self._opened_at = now
                self._failure_timestamps.clear()
                self._failure_timestamps.append(now)
                return

            self._failure_timestamps.append(now)
            if len(self._failure_timestamps) >= self.config.failure_count_threshold:
                self.state = AdapterBreakerState.OPEN
                self._opened_at = now

    def _prune_failures(self, now: float) -> None:
        cutoff = now - self.config.failure_window_seconds
        while self._failure_timestamps and self._failure_timestamps[0] < cutoff:
            self._failure_timestamps.popleft()


__all__ = [
    "AdapterBreakerConfig",
    "AdapterBreakerOpenError",
    "AdapterBreakerSnapshot",
    "AdapterBreakerState",
    "AdapterCircuitBreaker",
]