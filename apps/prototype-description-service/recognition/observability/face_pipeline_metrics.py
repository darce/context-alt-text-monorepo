"""Neutral face-pipeline metrics observers (FINALB-06 / OBS-05 / OBS-08).

Lives under ``recognition.observability`` so infrastructure adapters never
depend on HTTP interface middleware. Collectors use a caller-owned
``CollectorRegistry`` (injected or fresh) with low-cardinality series only —
no media/path/url labels.
"""

from __future__ import annotations

from typing import Protocol

from prometheus_client import CollectorRegistry, Counter, Histogram

# Submit admission waits are usually sub-second under load; fine head + short tail.
FACE_PIPELINE_SUBMIT_WAIT_BUCKETS: tuple[float, ...] = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
)


class FacePipelineMetricsObserver(Protocol):
    """Infrastructure-neutral observer seam for face_pipeline admission metrics.

    Structural protocol: any object implementing these methods (including
    ``FacePipelineMetrics``) may be injected into detectors / workers.
    """

    def observe_submit_wait(self, wait_s: float) -> None:
        """Record admission wait duration (success or timeout path)."""
        ...

    def record_admission_timeout(self) -> None:
        """Increment admission-timeout counter."""
        ...


class FacePipelineMetrics:
    """Process-local face-pipeline saturation collectors.

    Bound to an injected/new ``CollectorRegistry``. Safe to call from the
    detect path: observe/inc failures are swallowed by callers or optional
    thin wrappers — metrics must never break detection.

    Structurally implements :class:`FacePipelineMetricsObserver`.
    """

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self.registry = registry if registry is not None else CollectorRegistry()
        self.face_pipeline_submit_wait_seconds = Histogram(
            "face_pipeline_submit_wait_seconds",
            "Time spent waiting for face_pipeline submit admission (seconds)",
            buckets=FACE_PIPELINE_SUBMIT_WAIT_BUCKETS,
            registry=self.registry,
        )
        self.face_pipeline_admission_timeouts_total = Counter(
            "face_pipeline_admission_timeouts_total",
            "Face pipeline submit admission timeouts (deadline expired before slot)",
            registry=self.registry,
        )

    def observe_submit_wait(self, wait_s: float) -> None:
        """Record admission wait duration (success or timeout path)."""
        self.face_pipeline_submit_wait_seconds.observe(float(wait_s))

    def record_admission_timeout(self) -> None:
        """Increment admission-timeout counter."""
        self.face_pipeline_admission_timeouts_total.inc()


__all__ = [
    "FACE_PIPELINE_SUBMIT_WAIT_BUCKETS",
    "FacePipelineMetrics",
    "FacePipelineMetricsObserver",
]
