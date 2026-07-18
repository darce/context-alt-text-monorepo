"""Prometheus request metrics middleware (Slice 3a, PA-06/PA-07/PA-13).

Records one histogram observation, one counter increment, and keeps an
in-flight gauge balanced per request — including on unhandled exceptions.

The ``path`` label resolves to the FastAPI route template
(``scope["route"].path``, e.g. ``/clusters/{cluster_id}``), not the raw URL.
This caps histogram cardinality at the number of registered routes (PA-06).
"""

from __future__ import annotations

import time

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

try:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send
except ImportError:  # pragma: no cover - starlette is a FastAPI dep
    ASGIApp = Receive = Scope = Send = Message = object  # type: ignore[assignment,misc]


# Histogram buckets chosen from the description-service's observed latency
# distribution (~1–30s typical). The default prometheus_client bucket set
# (0.005..10) has a sparse tail for this workload.
DEFAULT_BUCKETS: tuple[float, ...] = (0.25, 0.5, 1, 2, 5, 10, 30, 60)

# Clustering-admission buckets target the E15-3a-BR-21 SLO (<1 s fail-fast,
# admission probe in single-digit ms on the happy path). Values are milliseconds.
CLUSTERING_ADMISSION_BUCKETS_MS: tuple[float, ...] = (
    5,
    10,
    25,
    50,
    100,
    250,
    500,
    1000,
    2500,
    5000,
    10000,
)

# Face-pipeline submit admission waits are usually sub-second under load;
# keep a fine head and a short tail for timeout budgets ([OBS-01][OBS-08]).
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


class MetricsRegistry:
    """Bundle of request metrics bound to a ``CollectorRegistry``.

    A fresh registry per-app keeps tests isolated. Production uses the module
    singleton via :func:`get_default_metrics`.
    """

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self.registry = registry or CollectorRegistry()
        self.request_duration = Histogram(
            "http_request_duration_seconds",
            "HTTP request duration in seconds",
            labelnames=("method", "path", "status"),
            buckets=DEFAULT_BUCKETS,
            registry=self.registry,
        )
        self.requests_total = Counter(
            "http_requests_total",
            "Total HTTP requests by status class",
            labelnames=("method", "status_class"),
            registry=self.registry,
        )
        self.in_flight = Gauge(
            "http_requests_in_flight",
            "HTTP requests currently in flight",
            registry=self.registry,
        )
        # E15-3a-BR-21 Slice 1: clustering write-path admission latency.
        # Labelled by response status so operators can distinguish happy-path
        # 202 Accepted from 503 fail-fast admission rejections.
        self.clustering_admission_latency_ms = Histogram(
            "clustering_admission_latency_ms",
            "Clustering write-path admission latency in milliseconds (E15-3a-BR-21)",
            labelnames=("status",),
            buckets=CLUSTERING_ADMISSION_BUCKETS_MS,
            registry=self.registry,
        )
        self.description_requests_total = Counter(
            "acx_description_requests_total",
            "Total image-description requests by adapter and result",
            labelnames=("adapter", "result"),
            registry=self.registry,
        )
        self.description_cache_hits_total = Counter(
            "acx_description_cache_hits_total",
            "Total image-description cache hits by adapter",
            labelnames=("adapter",),
            registry=self.registry,
        )
        self.description_adapter_duration_seconds = Histogram(
            "acx_description_adapter_duration_seconds",
            "Image-description adapter generation duration in seconds",
            labelnames=("adapter",),
            buckets=DEFAULT_BUCKETS,
            registry=self.registry,
        )
        # FIR4-BR-06: face_pipeline submit admission saturation (low cardinality).
        # No media/url/path labels — series stay process-scoped.
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


_default: MetricsRegistry | None = None


def get_default_metrics() -> MetricsRegistry:
    """Return the process-wide metrics registry used by the production app."""
    global _default
    if _default is None:
        _default = MetricsRegistry()
    return _default


def _resolve_path(scope: Scope) -> str:
    route = scope.get("route")
    template = getattr(route, "path", None)
    if template:
        return template
    return scope.get("path") or "unknown"


class MetricsMiddleware:
    """Pure-ASGI middleware that records request metrics without leaking on error."""

    def __init__(self, app: ASGIApp, metrics: MetricsRegistry | None = None) -> None:
        self.app = app
        self.metrics = metrics or get_default_metrics()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET")
        status_holder: dict[str, int] = {"code": 500}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["code"] = int(message.get("status", 500))
            await send(message)

        self.metrics.in_flight.inc()
        start = time.perf_counter()
        try:
            await self.app(scope, receive, send_wrapper)
        except BaseException:
            elapsed = time.perf_counter() - start
            path = _resolve_path(scope)
            self.metrics.request_duration.labels(method=method, path=path, status="500").observe(elapsed)
            self.metrics.requests_total.labels(method=method, status_class="5xx").inc()
            raise
        else:
            elapsed = time.perf_counter() - start
            path = _resolve_path(scope)
            status = status_holder["code"]
            self.metrics.request_duration.labels(method=method, path=path, status=str(status)).observe(elapsed)
            self.metrics.requests_total.labels(method=method, status_class=f"{status // 100}xx").inc()
        finally:
            self.metrics.in_flight.dec()


__all__ = [
    "CLUSTERING_ADMISSION_BUCKETS_MS",
    "DEFAULT_BUCKETS",
    "FACE_PIPELINE_SUBMIT_WAIT_BUCKETS",
    "MetricsMiddleware",
    "MetricsRegistry",
    "get_default_metrics",
]
