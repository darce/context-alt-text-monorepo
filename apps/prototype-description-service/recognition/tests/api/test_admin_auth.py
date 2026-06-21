"""Tests for the strictly-separate admin auth gate and fail-closed config guard."""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from recognition.config.security import (
    InsecureProductionConfigError,
    SecuritySettings,
    validate_admin_config,
)
from recognition.interface_adapters.http.deps.admin_auth import require_admin

_VALID_TOKEN = "x" * 40  # >= 32 chars


def _admin_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Build a tiny app with one route gated by require_admin."""
    monkeypatch.setenv("RECOGNITION_ADMIN_ENABLED", "1")
    monkeypatch.setenv("RECOGNITION_ADMIN_TOKEN", _VALID_TOKEN)
    monkeypatch.delenv("RECOGNITION_ADMIN_TOKEN_HEADER", raising=False)

    app = FastAPI()

    @app.get("/_t", dependencies=[Depends(require_admin)])
    async def _protected() -> dict[str, bool]:
        return {"ok": True}

    return TestClient(app)


# --- require_admin gate ---


def test_valid_admin_token_allows_request(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _admin_client(monkeypatch)
    response = client.get("/_t", headers={"X-Admin-Token": _VALID_TOKEN})
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_wrong_admin_token_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _admin_client(monkeypatch)
    response = client.get("/_t", headers={"X-Admin-Token": "y" * 40})
    assert response.status_code == 401


def test_missing_admin_token_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _admin_client(monkeypatch)
    response = client.get("/_t")
    assert response.status_code == 401


def test_empty_admin_token_header_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _admin_client(monkeypatch)
    response = client.get("/_t", headers={"X-Admin-Token": ""})
    assert response.status_code == 401


def test_tenant_api_key_header_does_not_satisfy_admin_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """A request carrying only tenant-style auth headers (no admin header) is rejected.

    Proves require_admin ignores api_key_header / Authorization entirely.
    """
    client = _admin_client(monkeypatch)
    response = client.get(
        "/_t",
        headers={"Authorization": f"Bearer {_VALID_TOKEN}", "X-Api-Key": _VALID_TOKEN},
    )
    assert response.status_code == 401


def test_admin_gate_honors_custom_header(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RECOGNITION_ADMIN_ENABLED", "1")
    monkeypatch.setenv("RECOGNITION_ADMIN_TOKEN", _VALID_TOKEN)
    monkeypatch.setenv("RECOGNITION_ADMIN_TOKEN_HEADER", "X-Operator-Key")

    app = FastAPI()

    @app.get("/_t", dependencies=[Depends(require_admin)])
    async def _protected() -> dict[str, bool]:
        return {"ok": True}

    client = TestClient(app)

    assert client.get("/_t", headers={"X-Admin-Token": _VALID_TOKEN}).status_code == 401
    assert client.get("/_t", headers={"X-Operator-Key": _VALID_TOKEN}).status_code == 200


# --- validate_admin_config fail-closed guard ---


def test_validate_admin_config_noop_when_disabled() -> None:
    settings = SecuritySettings(admin_enabled=False, admin_token="")
    validate_admin_config(settings, runtime_mode="production")


def test_validate_admin_config_raises_on_empty_token() -> None:
    settings = SecuritySettings(admin_enabled=True, admin_token="")
    with pytest.raises(InsecureProductionConfigError):
        validate_admin_config(settings, runtime_mode="development")


def test_validate_admin_config_raises_on_short_token() -> None:
    settings = SecuritySettings(admin_enabled=True, admin_token="x" * 31)
    with pytest.raises(InsecureProductionConfigError):
        validate_admin_config(settings, runtime_mode="development")


def test_validate_admin_config_raises_in_production_without_tailnet_ack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RECOGNITION_ADMIN_TAILNET_BOUND", raising=False)
    settings = SecuritySettings(admin_enabled=True, admin_token=_VALID_TOKEN)
    with pytest.raises(InsecureProductionConfigError):
        validate_admin_config(settings, runtime_mode="production")


def test_validate_admin_config_passes_in_production_with_tailnet_ack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RECOGNITION_ADMIN_TAILNET_BOUND", "1")
    settings = SecuritySettings(admin_enabled=True, admin_token=_VALID_TOKEN)
    validate_admin_config(settings, runtime_mode="production")


def test_validate_admin_config_passes_outside_production_with_valid_token() -> None:
    settings = SecuritySettings(admin_enabled=True, admin_token=_VALID_TOKEN)
    validate_admin_config(settings, runtime_mode="development")
