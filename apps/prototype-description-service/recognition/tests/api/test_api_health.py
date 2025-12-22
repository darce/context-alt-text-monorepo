"""API tests for health endpoint."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from recognition.interface_adapters.http import dependencies
from recognition.interface_adapters.http import router as recognition_router


async def _no_session():
    yield None


def _make_client() -> TestClient:
    app = FastAPI()
    app.include_router(recognition_router, prefix="/recognition")
    app.dependency_overrides[dependencies.get_optional_session] = _no_session
    return TestClient(app)


def test_health_returns_minimal(monkeypatch) -> None:
    monkeypatch.setenv("RECOGNITION_AUTH_ENABLED", "1")
    client = _make_client()

    resp = client.get("/recognition/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["database"] == "disconnected"
    assert body["pool_stats"] is None
    assert "timestamp" in body


def test_health_pool_requires_auth(monkeypatch) -> None:
    monkeypatch.setenv("RECOGNITION_AUTH_ENABLED", "1")
    client = _make_client()

    resp = client.get("/recognition/health/pool")

    assert resp.status_code == 401
