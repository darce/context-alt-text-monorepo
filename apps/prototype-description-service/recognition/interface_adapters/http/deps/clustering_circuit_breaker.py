"""Clustering-dedicated circuit breaker for ``POST /recognition/clustering/jobs``.

E15-3a-BR-21 Slice 3. Separate module and separate state from the SLR-3
:class:`SessionDependencyCircuitBreaker` (``deps/circuit_breaker.py``).

Why separate: the SLR-3 breaker guards per-request probe failures at the
generic DB dependency boundary for every router. This one counts
``QueryCanceledError`` specifically on the clustering write path -- it exists
because a single zombie ``idle in transaction`` holder on ``tenants`` can
generate a convoy of identical cancellations that must fail fast without
tripping the shared session breaker and starving the rest of the service.
See task plan PLAN-09 for the composition rationale.
"""

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
CLUSTERING_BREAKER_STATE_KEY = "clustering_circuit_breaker"


class ClusteringBreakerState(StrEnum):
    """Stable public state names for the clustering circuit breaker."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(frozen=True, slots=True)
class ClusteringBreakerSnapshot:
    """Serializable view of current breaker state for logging/metrics."""

    state: ClusteringBreakerState
    failure_count: int
    is_open: bool


@dataclass(slots=True)
class ClusteringCircuitBreaker:
    """In-process breaker counting clustering write-path cancellations."""

    failure_threshold: int
    window_seconds: float
    cooldown_seconds: float
    time_source: TimeSource = _time.monotonic
    state: ClusteringBreakerState = ClusteringBreakerState.CLOSED
    _failure_timestamps: deque[float] = field(default_factory=deque, init=False, repr=False)
    _opened_at: float | None = field(default=None, init=False, repr=False)
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    def allow_request(self) -> bool:
        """Return True when the caller may attempt the clustering write path."""
        with self._lock:
            now = self.time_source()
            self._prune_failures(now)
            if self.state is ClusteringBreakerState.OPEN:
                if self._opened_at is None or (now - self._opened_at) < self.cooldown_seconds:
                    return False
                self.state = ClusteringBreakerState.HALF_OPEN
                return True
            return self.state is not ClusteringBreakerState.OPEN

    def record_success(self) -> None:
        """Reset after a successful admission (202) or half-open trial."""
        with self._lock:
            self.state = ClusteringBreakerState.CLOSED
            self._opened_at = None
            self._failure_timestamps.clear()

    def record_failure(self) -> None:
        """Track a ``QueryCanceledError`` on the clustering write path."""
        with self._lock:
            now = self.time_source()
            self._prune_failures(now)
            self._failure_timestamps.append(now)
            if (
                self.state is ClusteringBreakerState.HALF_OPEN
                or len(self._failure_timestamps) >= self.failure_threshold
            ):
                self.state = ClusteringBreakerState.OPEN
                self._opened_at = now

    def snapshot(self) -> ClusteringBreakerSnapshot:
        with self._lock:
            now = self.time_source()
            self._prune_failures(now)
            return ClusteringBreakerSnapshot(
                state=self.state,
                failure_count=len(self._failure_timestamps),
                is_open=self.state is ClusteringBreakerState.OPEN,
            )

    def force_open(self) -> None:
        """Test helper: drive the breaker into the open state."""
        with self._lock:
            now = self.time_source()
            self.state = ClusteringBreakerState.OPEN
            self._opened_at = now
            self._failure_timestamps.clear()
            self._failure_timestamps.extend([now] * self.failure_threshold)

    def _prune_failures(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._failure_timestamps and self._failure_timestamps[0] < cutoff:
            self._failure_timestamps.popleft()


def create_clustering_circuit_breaker(
    settings: DatabaseSettings | None = None,
    *,
    time_source: TimeSource | None = None,
) -> ClusteringCircuitBreaker:
    """Build the clustering breaker from database settings."""
    resolved = settings or get_database_settings()
    return ClusteringCircuitBreaker(
        failure_threshold=resolved.clustering_breaker_failure_threshold,
        window_seconds=resolved.clustering_breaker_window_seconds,
        cooldown_seconds=resolved.clustering_breaker_cooldown_seconds,
        time_source=time_source or _time.monotonic,
    )


def initialize_clustering_circuit_breaker(
    app: FastAPI,
    *,
    breaker: ClusteringCircuitBreaker | None = None,
) -> ClusteringCircuitBreaker:
    """Attach a clustering breaker instance to FastAPI app state."""
    resolved = breaker or create_clustering_circuit_breaker()
    setattr(app.state, CLUSTERING_BREAKER_STATE_KEY, resolved)
    return resolved


def get_or_create_clustering_circuit_breaker(app: FastAPI) -> ClusteringCircuitBreaker:
    """Return the app-scoped clustering breaker, lazily initializing for tests."""
    breaker = getattr(app.state, CLUSTERING_BREAKER_STATE_KEY, None)
    if breaker is None:
        breaker = initialize_clustering_circuit_breaker(app)
    return breaker


__all__ = [
    "CLUSTERING_BREAKER_STATE_KEY",
    "ClusteringBreakerSnapshot",
    "ClusteringBreakerState",
    "ClusteringCircuitBreaker",
    "create_clustering_circuit_breaker",
    "get_or_create_clustering_circuit_breaker",
    "initialize_clustering_circuit_breaker",
]
