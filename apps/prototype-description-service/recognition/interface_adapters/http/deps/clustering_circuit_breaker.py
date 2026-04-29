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
from collections.abc import Callable
from dataclasses import dataclass, field

from fastapi import FastAPI

from db.settings import DatabaseSettings, get_database_settings
from recognition.application.integrations.circuit_breaker import (
    AdapterBreakerConfig,
    AdapterBreakerSnapshot,
    AdapterBreakerState,
    AdapterCircuitBreaker,
)

type TimeSource = Callable[[], float]
CLUSTERING_BREAKER_STATE_KEY = "clustering_circuit_breaker"

ClusteringBreakerState = AdapterBreakerState
ClusteringBreakerSnapshot = AdapterBreakerSnapshot


@dataclass(slots=True)
class ClusteringCircuitBreaker:
    """In-process breaker counting clustering write-path cancellations."""

    failure_threshold: int
    window_seconds: float
    cooldown_seconds: float
    time_source: TimeSource = _time.monotonic
    _breaker: AdapterCircuitBreaker = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._breaker = AdapterCircuitBreaker(
            adapter_name="clustering_admission",
            config=AdapterBreakerConfig(
                failure_count_threshold=self.failure_threshold,
                failure_window_seconds=self.window_seconds,
                half_open_probe_count=1,
                success_close_threshold=1,
                open_state_cooldown_seconds=self.cooldown_seconds,
            ),
            time_source=self.time_source,
        )

    def allow_request(self) -> bool:
        """Return True when the caller may attempt the clustering write path."""
        return self._breaker.allow_call()

    def record_success(self) -> None:
        """Reset after a successful admission (202) or half-open trial."""
        self._breaker.record_success()

    def record_failure(self) -> None:
        """Track a ``QueryCanceledError`` on the clustering write path."""
        self._breaker.record_failure()

    def snapshot(self) -> ClusteringBreakerSnapshot:
        return self._breaker.snapshot()

    def force_open(self) -> None:
        """Test helper: drive the breaker into the open state."""
        self._breaker.force_open()


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
