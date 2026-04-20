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
    "DEFAULT_BUCKETS",
    "MetricsMiddleware",
    "MetricsRegistry",
    "get_default_metrics",
]
