"""Aggregate metrics for post-curation refresh attempts."""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

CURATION_REFRESH_ATTEMPT_BUCKETS: tuple[float, ...] = (0.25, 0.5, 1, 2, 5, 10, 30, 60, 120)


class CurationRefreshMetrics:
    """Prometheus collectors for aggregate post-curation refresh attempts."""

    def __init__(self, registry: CollectorRegistry) -> None:
        self.registry = registry
        self.attempts_total = Counter(
            "curation_refresh_attempts_total",
            "Total post-curation refresh attempts by outcome",
            labelnames=("outcome",),
            registry=registry,
        )
        self.attempt_duration_seconds = Histogram(
            "curation_refresh_attempt_duration_seconds",
            "Duration of post-curation refresh attempts in seconds by outcome",
            labelnames=("outcome",),
            buckets=CURATION_REFRESH_ATTEMPT_BUCKETS,
            registry=registry,
        )
        self.attempts_in_flight = Gauge(
            "curation_refresh_attempts_in_flight",
            "Post-curation refresh attempts currently running",
            registry=registry,
        )

    def attempt_started(self) -> None:
        self.attempts_in_flight.inc()

    def attempt_finished(self, *, outcome: str, duration_seconds: float | None) -> None:
        self.attempts_total.labels(outcome=outcome).inc()
        if duration_seconds is not None:
            self.attempt_duration_seconds.labels(outcome=outcome).observe(duration_seconds)
        self.attempts_in_flight.dec()


_defaults_by_registry: dict[int, CurationRefreshMetrics] = {}


def get_default_curation_refresh_metrics(registry: CollectorRegistry) -> CurationRefreshMetrics:
    registry_key = id(registry)
    metrics = _defaults_by_registry.get(registry_key)
    if metrics is None:
        metrics = CurationRefreshMetrics(registry=registry)
        _defaults_by_registry[registry_key] = metrics
    return metrics


__all__ = [
    "CURATION_REFRESH_ATTEMPT_BUCKETS",
    "CurationRefreshMetrics",
    "get_default_curation_refresh_metrics",
]
