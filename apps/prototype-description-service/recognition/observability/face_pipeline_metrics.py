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

    def observe_quality_factors(
        self,
        *,
        sharpness: float,
        embedding_norm: float,
        occlusion_severity: float,
    ) -> None:
        """Record per-factor quality breakdown (CAL-09). Optional for older injectors."""
        ...


# Low-cardinality factor histograms (no media/path labels).
_SHARPNESS_BUCKETS: tuple[float, ...] = (1.0, 5.0, 10.0, 25.0, 50.0, 100.0, 250.0, 500.0, 1000.0, 5000.0)
_NORM_BUCKETS: tuple[float, ...] = (0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0)
_OCCLUSION_BUCKETS: tuple[float, ...] = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0)


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
        self.face_pipeline_factor_sharpness = Histogram(
            "face_pipeline_factor_sharpness",
            "Per-face sharpness (variance of Laplacian) under face_pipeline",
            buckets=_SHARPNESS_BUCKETS,
            registry=self.registry,
        )
        self.face_pipeline_factor_embedding_norm = Histogram(
            "face_pipeline_factor_embedding_norm",
            "Per-face pre-normalization embedding L2 norm under face_pipeline",
            buckets=_NORM_BUCKETS,
            registry=self.registry,
        )
        self.face_pipeline_factor_occlusion_severity = Histogram(
            "face_pipeline_factor_occlusion_severity",
            "Per-face occlusion severity [0,1] under face_pipeline",
            buckets=_OCCLUSION_BUCKETS,
            registry=self.registry,
        )

    def observe_submit_wait(self, wait_s: float) -> None:
        """Record admission wait duration (success or timeout path)."""
        self.face_pipeline_submit_wait_seconds.observe(float(wait_s))

    def record_admission_timeout(self) -> None:
        """Increment admission-timeout counter."""
        self.face_pipeline_admission_timeouts_total.inc()

    def observe_quality_factors(
        self,
        *,
        sharpness: float,
        embedding_norm: float,
        occlusion_severity: float,
    ) -> None:
        """Record per-factor quality breakdown (CAL-09)."""
        self.face_pipeline_factor_sharpness.observe(float(sharpness))
        self.face_pipeline_factor_embedding_norm.observe(float(embedding_norm))
        self.face_pipeline_factor_occlusion_severity.observe(float(occlusion_severity))


__all__ = [
    "FACE_PIPELINE_SUBMIT_WAIT_BUCKETS",
    "FacePipelineMetrics",
    "FacePipelineMetricsObserver",
]
