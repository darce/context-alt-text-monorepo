"""API tests for health endpoint."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from recognition.interface_adapters.http import dependencies
from recognition.interface_adapters.http import router as recognition_router
from recognition.interface_adapters.http.deps.circuit_breaker import (
    SessionDependencyCircuitBreaker,
    initialize_session_dependency_circuit_breaker,
)


async def _no_session():
    yield None


async def _session_present():
    yield object()


def _make_client(
    *,
    breaker: SessionDependencyCircuitBreaker | None = None,
    optional_session_override=_no_session,
    observability_session_override=_no_session,
) -> TestClient:
    app = FastAPI()
    initialize_session_dependency_circuit_breaker(app, breaker=breaker)
    app.include_router(recognition_router, prefix="/recognition")
    app.dependency_overrides[dependencies.get_optional_session] = optional_session_override
    app.dependency_overrides[dependencies.get_observability_session] = observability_session_override
    return TestClient(app)


def test_health_returns_minimal(monkeypatch) -> None:
    monkeypatch.setenv("RECOGNITION_AUTH_ENABLED", "1")
    client = _make_client()

    resp = client.get("/recognition/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["database"] == "disconnected"
    assert body["database_detail"] == "connection_unavailable"
    assert body["breaker_state"] == "closed"
    assert set(body["pool_stats"]) == {"business", "observability"}
    assert "timestamp" in body


def test_health_reports_breaker_open_degradation(monkeypatch) -> None:
    monkeypatch.setenv("RECOGNITION_AUTH_ENABLED", "1")
    breaker = SessionDependencyCircuitBreaker(
        failure_threshold=3,
        window_seconds=30,
        half_open_after_seconds=10,
    )
    breaker.force_open()
    client = _make_client(breaker=breaker)

    resp = client.get("/recognition/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["database"] == "disconnected"
    assert body["database_detail"] == "circuit_breaker_open"
    assert body["breaker_state"] == "open"


def test_health_reports_observability_pool_degradation(monkeypatch) -> None:
    monkeypatch.setenv("RECOGNITION_AUTH_ENABLED", "1")
    client = _make_client(
        optional_session_override=_session_present,
        observability_session_override=_no_session,
    )

    resp = client.get("/recognition/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["database"] == "disconnected"
    assert body["database_detail"] == "observability_connection_unavailable"
    assert body["breaker_state"] == "closed"


def test_health_reports_healthy_when_both_pools_are_available(monkeypatch) -> None:
    monkeypatch.setenv("RECOGNITION_AUTH_ENABLED", "1")
    client = _make_client(
        optional_session_override=_session_present,
        observability_session_override=_session_present,
    )

    resp = client.get("/recognition/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "healthy"
    assert body["database"] == "connected"
    assert body["database_detail"] is None


def test_health_pool_requires_auth(monkeypatch) -> None:
    monkeypatch.setenv("RECOGNITION_AUTH_ENABLED", "1")
    client = _make_client()

    resp = client.get("/recognition/health/pool")

    assert resp.status_code == 401


def test_health_pool_returns_business_and_observability_stats(monkeypatch) -> None:
    monkeypatch.setenv("RECOGNITION_AUTH_ENABLED", "0")
    client = _make_client()

    resp = client.get("/recognition/health/pool")

    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"business", "observability"}
    assert "total_capacity" in body["business"]
    assert "total_capacity" in body["observability"]
