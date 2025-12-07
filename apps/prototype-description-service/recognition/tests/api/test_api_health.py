"""API tests for health endpoint."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from recognition.interface_adapters.http import router as recognition_router


def _make_client() -> TestClient:
    app = FastAPI()
    app.include_router(recognition_router, prefix="/recognition")
    return TestClient(app)


def test_health_returns_ok() -> None:
    client = _make_client()

    resp = client.get("/recognition/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body == {"service": "recognition", "status": "ok"}
