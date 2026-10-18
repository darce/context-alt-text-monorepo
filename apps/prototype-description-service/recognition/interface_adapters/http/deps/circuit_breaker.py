"""Circuit breaker state for recognition HTTP session dependencies."""

from __future__ import annotations

import time as _time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from threading import Lock

from fastapi import FastAPI

from db.settings import DatabaseSettings, get_database_settings

type TimeSource = Callable[[], float]
SESSION_DEPENDENCY_BREAKER_STATE_KEY = "session_dependency_circuit_breaker"


class BreakerState(StrEnum):
    """Stable public state names for the session dependency circuit breaker."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(frozen=True, slots=True)
class CircuitBreakerSnapshot:
    """Serializable view of current breaker state."""

    state: BreakerState
    failure_count: int
    is_open: bool


@dataclass(slots=True)
class SessionDependencyCircuitBreaker:
    """Small in-process breaker for the HTTP DB dependency boundary."""

    failure_threshold: int
    window_seconds: float
    half_open_after_seconds: float
    time_source: TimeSource = _time.monotonic
    state: BreakerState = BreakerState.CLOSED
    _failure_timestamps: deque[float] = field(default_factory=deque, init=False, repr=False)
    _opened_at: float | None = field(default=None, init=False, repr=False)
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    def allow_request(self) -> bool:
        """Return True when the caller may attempt the guarded dependency."""
        with self._lock:
            now = self.time_source()
            self._prune_failures(now)
            if self.state is BreakerState.OPEN:
                if self._opened_at is None or (now - self._opened_at) < self.half_open_after_seconds:
                    return False
                self.state = BreakerState.HALF_OPEN
                return True
            return self.state is BreakerState.CLOSED

    def record_success(self) -> None:
        """Reset the breaker after a successful guarded attempt."""
        with self._lock:
            self.state = BreakerState.CLOSED
            self._opened_at = None
            self._failure_timestamps.clear()

    def record_failure(self) -> None:
        """Track a failed guarded attempt and open the breaker when threshold is met."""
        with self._lock:
            now = self.time_source()
            self._prune_failures(now)
            self._failure_timestamps.append(now)
            if self.state is BreakerState.HALF_OPEN or len(self._failure_timestamps) >= self.failure_threshold:
                self.state = BreakerState.OPEN
                self._opened_at = now

    def snapshot(self) -> CircuitBreakerSnapshot:
        """Return a stable snapshot for logging and health reporting."""
        with self._lock:
            now = self.time_source()
            self._prune_failures(now)
            return CircuitBreakerSnapshot(
                state=self.state,
                failure_count=len(self._failure_timestamps),
                is_open=self.state is BreakerState.OPEN,
            )

    def force_open(self) -> None:
        """Test helper for driving the breaker into the open state."""
        with self._lock:
            now = self.time_source()
            self.state = BreakerState.OPEN
            self._opened_at = now
            self._failure_timestamps.clear()
            self._failure_timestamps.extend([now] * self.failure_threshold)

    def _prune_failures(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._failure_timestamps and self._failure_timestamps[0] < cutoff:
            self._failure_timestamps.popleft()


def create_session_dependency_circuit_breaker(
    settings: DatabaseSettings | None = None,
    *,
    time_source: TimeSource | None = None,
) -> SessionDependencyCircuitBreaker:
    """Build the breaker from database settings."""
    resolved_settings = settings or get_database_settings()
    return SessionDependencyCircuitBreaker(
        failure_threshold=resolved_settings.breaker_failure_threshold,
        window_seconds=resolved_settings.breaker_window_seconds,
        half_open_after_seconds=resolved_settings.breaker_half_open_after_seconds,
        time_source=time_source or _time.monotonic,
    )


def initialize_session_dependency_circuit_breaker(
    app: FastAPI,
    *,
    breaker: SessionDependencyCircuitBreaker | None = None,
) -> SessionDependencyCircuitBreaker:
    """Attach a breaker instance to FastAPI app state."""
    resolved_breaker = breaker or create_session_dependency_circuit_breaker()
    setattr(app.state, SESSION_DEPENDENCY_BREAKER_STATE_KEY, resolved_breaker)
    return resolved_breaker


def get_or_create_session_dependency_circuit_breaker(app: FastAPI) -> SessionDependencyCircuitBreaker:
    """Return the app-scoped breaker, creating one on demand for lightweight test apps."""
    breaker = getattr(app.state, SESSION_DEPENDENCY_BREAKER_STATE_KEY, None)
    if breaker is None:
        breaker = initialize_session_dependency_circuit_breaker(app)
    return breaker


__all__ = [
    "BreakerState",
    "CircuitBreakerSnapshot",
    "SESSION_DEPENDENCY_BREAKER_STATE_KEY",
    "SessionDependencyCircuitBreaker",
    "create_session_dependency_circuit_breaker",
    "get_or_create_session_dependency_circuit_breaker",
    "initialize_session_dependency_circuit_breaker",
]
