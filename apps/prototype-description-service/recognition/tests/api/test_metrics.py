"""Slice 3a: Prometheus request metrics middleware + auth-gated /metrics route.

Covers PA-05 (auth), PA-06 (route-template cardinality), PA-07 (version pin),
PA-13 (no metric leak on unhandled exception).
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry
from prometheus_client.parser import text_string_to_metric_families


def _install_healthy_observability_session(app) -> None:
    """Keep integration metrics assertions independent of a live database."""
    from unittest.mock import AsyncMock, MagicMock

    from db.settings import get_database_settings
    from recognition.interface_adapters.http import deps as dependencies

    dim = int(get_database_settings().pgvector_dimension)
    rows = [
        ("media_identities", "embedding", dim),
        ("identity_cluster_representatives", "embedding", dim),
        ("mv_identity_cluster_centroids", "centroid", dim),
    ]
    result = MagicMock()
    result.all = MagicMock(return_value=rows)
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)

    class _NestedTransaction:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    session.begin_nested = MagicMock(return_value=_NestedTransaction())

    async def _session_yielder():
        yield session

    app.dependency_overrides[dependencies.get_observability_session] = _session_yielder


def _build_app_with_metrics(registry: CollectorRegistry):
    """Build an isolated FastAPI app with MetricsMiddleware bound to a fresh registry."""
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

    from recognition.interface_adapters.http.deps.auth import AuthContext, require_auth
    from recognition.interface_adapters.http.middleware.metrics import (
        MetricsMiddleware,
        MetricsRegistry,
    )

    metrics = MetricsRegistry(registry=registry)
    app = FastAPI()
    app.add_middleware(MetricsMiddleware, metrics=metrics)

    @app.get("/clusters/{cluster_id}")
    def get_cluster(cluster_id: str) -> dict[str, str]:
        return {"id": cluster_id}

    @app.get("/boom")
    def boom() -> dict[str, str]:
        raise RuntimeError("boom")

    from fastapi import Depends, Response

    @app.get("/metrics")
    def metrics_endpoint(_: object = Depends(require_auth)) -> Response:
        return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)

    async def _auth_ok() -> AuthContext:
        return AuthContext(token=None, tenant_claim=None, enabled=False)

    # Default: auth passes. Individual tests flip this override.
    app.dependency_overrides[require_auth] = _auth_ok
    return app, metrics


def _collect_samples(text: str, sample_name: str) -> list[tuple[dict[str, str], float]]:
    out: list[tuple[dict[str, str], float]] = []
    for family in text_string_to_metric_families(text):
        for sample in family.samples:
            if sample.name == sample_name:
                out.append((dict(sample.labels), sample.value))
    return out


def test_metrics_requires_auth(monkeypatch) -> None:
    """PA-05: /metrics must be auth-gated via require_auth. Anonymous → 401."""
    monkeypatch.setenv("RECOGNITION_AUTH_ENABLED", "1")

    from recognition.interface_adapters.http.deps.auth import require_auth

    registry = CollectorRegistry()
    app, _ = _build_app_with_metrics(registry)
    # Drop the override so the real require_auth runs.
    app.dependency_overrides.pop(require_auth, None)
    client = TestClient(app)

    resp = client.get("/metrics")
    assert resp.status_code == 401, resp.text


def test_metrics_returns_prometheus_exposition() -> None:
    """With auth satisfied, /metrics returns text/plain exposition format and
    includes the histogram, counter, and gauge series.
    """
    registry = CollectorRegistry()
    app, _ = _build_app_with_metrics(registry)
    client = TestClient(app)

    # Generate one observation first.
    assert client.get("/clusters/abc").status_code == 200

    resp = client.get("/metrics")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/plain")
    body = resp.text
    assert "http_request_duration_seconds_bucket" in body
    assert "http_requests_total" in body
    assert "http_requests_in_flight" in body


def test_histogram_buckets_populated_after_request() -> None:
    """A successful request produces bucket samples on http_request_duration_seconds."""
    registry = CollectorRegistry()
    app, _ = _build_app_with_metrics(registry)
    client = TestClient(app)

    assert client.get("/clusters/abc").status_code == 200

    resp = client.get("/metrics")
    buckets = _collect_samples(resp.text, "http_request_duration_seconds_bucket")
    # At least one bucket sample with le=+Inf must carry count >=1 for our route.
    matching = [
        value
        for labels, value in buckets
        if labels.get("path") == "/clusters/{cluster_id}" and labels.get("le") == "+Inf"
    ]
    assert matching and matching[0] >= 1.0, buckets


def test_path_label_uses_route_template_not_raw_url() -> None:
    """PA-06: two requests to different cluster ids must share the same path label
    (the FastAPI route template), so cardinality stays bounded.
    """
    registry = CollectorRegistry()
    app, _ = _build_app_with_metrics(registry)
    client = TestClient(app)

    assert client.get("/clusters/aaa-111").status_code == 200
    assert client.get("/clusters/bbb-222").status_code == 200

    resp = client.get("/metrics")
    buckets = _collect_samples(resp.text, "http_request_duration_seconds_bucket")
    paths = {labels.get("path") for labels, _ in buckets}
    assert "/clusters/{cluster_id}" in paths
    assert "/clusters/aaa-111" not in paths
    assert "/clusters/bbb-222" not in paths
    count_series = [
        value
        for labels, value in buckets
        if labels.get("path") == "/clusters/{cluster_id}" and labels.get("le") == "+Inf"
    ]
    assert count_series and count_series[0] >= 2.0


def test_exception_path_records_metrics_without_leak() -> None:
    """PA-13: an unhandled exception still produces a histogram observation, a
    status_class=5xx counter increment, and leaves in_flight at its prior value
    (no leak).
    """
    registry = CollectorRegistry()
    app, metrics = _build_app_with_metrics(registry)
    client = TestClient(app, raise_server_exceptions=False)

    before = metrics.in_flight._value.get()
    resp = client.get("/boom")
    assert resp.status_code == 500
    after = metrics.in_flight._value.get()
    assert after == before, "in_flight gauge leaked on exception"

    resp = client.get("/metrics")
    counters = _collect_samples(resp.text, "http_requests_total")
    fivexx = [
        value for labels, value in counters if labels.get("status_class") == "5xx" and labels.get("method") == "GET"
    ]
    assert fivexx and fivexx[0] >= 1.0, counters

    buckets = _collect_samples(resp.text, "http_request_duration_seconds_bucket")
    boom_hits = [value for labels, value in buckets if labels.get("path") == "/boom" and labels.get("le") == "+Inf"]
    assert boom_hits and boom_hits[0] >= 1.0


# ---------------------------------------------------------------------------
# Integration: real create_app() wiring (E15-2-BR-05, E15-2-BR-06)
# ---------------------------------------------------------------------------


def test_production_app_exposes_metrics_endpoint(monkeypatch) -> None:
    """BR-05: `create_app()` must register `/metrics` so the production app
    actually exposes Prometheus exposition. Anonymous calls are rejected by
    `require_auth` (PA-05); an overridden auth dep returns the text exposition
    recorded by the real `MetricsMiddleware` for a prior `/health` request.
    """
    monkeypatch.setenv("RECOGNITION_AUTH_ENABLED", "1")

    from api.main import create_app
    from recognition.interface_adapters.http.deps.auth import AuthContext, require_auth

    app = create_app()
    _install_healthy_observability_session(app)
    client = TestClient(app)

    # Anonymous: 401 from require_auth.
    anon = client.get("/metrics")
    assert anon.status_code == 401, anon.text

    # Hit a real route so the middleware has something to observe.
    assert client.get("/health").status_code == 200

    async def _auth_ok() -> AuthContext:
        return AuthContext(token=None, tenant_claim=None, enabled=False)

    app.dependency_overrides[require_auth] = _auth_ok

    resp = client.get("/metrics")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/plain")
    body = resp.text
    assert "http_request_duration_seconds_bucket" in body
    assert "http_requests_total" in body
    assert "http_requests_in_flight" in body
    # The /health request we made above must appear under its route template.
    assert 'path="/health"' in body
