"""Reject unbounded anonymous provision inputs before any database write."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from recognition.application.services.demo_provisioning_service import KNOWN_SEED_BUNDLES
from recognition.interface_adapters.http.deps import ip_rate_limit
from recognition.interface_adapters.http.routers import demo as demo_routes


@pytest.fixture
def provision_client(monkeypatch):
    monkeypatch.setenv("RECOGNITION_DEMO_RESOLVE_RPM", "100")
    monkeypatch.setenv("RECOGNITION_DEMO_PROVISION_RPM", "100")
    ip_rate_limit._reset_state_for_tests()
    demo_routes._reset_provision_limiter_for_tests()
    provision = AsyncMock(return_value=SimpleNamespace(
        instance=SimpleNamespace(
            slug="bounded-demo", seed_bundle="default", expires_at=datetime.now(UTC)
        ),
        demo_url="https://testserver/x/bounded-demo",
        pre_scan=SimpleNamespace(seeded_media_present=True, scanned_faces=0, people_count=0),
    ))
    monkeypatch.setattr(demo_routes, "provision_demo", provision)
    app = FastAPI()
    app.include_router(demo_routes.router)

    async def session_dep():
        yield None

    app.dependency_overrides[demo_routes.get_session] = session_dep
    with TestClient(app, base_url="https://testserver") as client:
        yield client, provision
    ip_rate_limit._reset_state_for_tests()
    demo_routes._reset_provision_limiter_for_tests()


@pytest.mark.parametrize("body", [
    {"label": "x" * 121},
    {"label": ""},
    {"label": " \t\n "},
    {"label": "Valid", "seed": "../x"},
    {"label": "Valid", "seed": ""},
    {"label": "Valid", "seed": "x" * 65},
    {"label": "Valid", "seed": "Default"},
    {"label": "Valid", "unexpected": True},
])
def test_invalid_provision_never_calls_service(provision_client, body):
    client, provision = provision_client
    assert client.post("/x/provision", json=body).status_code == 422
    provision.assert_not_called()


@pytest.mark.parametrize("label", ["x" * 120, "  " + "x" * 120 + " \t"])
@pytest.mark.parametrize("seed", [None, "default", *sorted(KNOWN_SEED_BUNDLES - {"default"})])
def test_valid_provision_passes_normalized_values(provision_client, label, seed):
    client, provision = provision_client
    body = {"label": label}
    if seed is not None:
        body["seed"] = seed
    assert client.post("/x/provision", json=body).status_code == 201
    provision.assert_awaited_once_with(None, label=label.strip(), seed=seed or "default")
