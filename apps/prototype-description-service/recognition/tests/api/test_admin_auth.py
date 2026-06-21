"""Tests for the strictly-separate admin auth gate and fail-closed config guard."""

from __future__ import annotations

import base64

import pytest
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from recognition.config.security import (
    InsecureProductionConfigError,
    SecuritySettings,
    validate_admin_config,
)
from recognition.interface_adapters.http.deps.admin_auth import require_admin, require_same_origin

_VALID_TOKEN = "x" * 40  # >= 32 chars


def _basic_header(password: str, *, username: str = "admin") -> dict[str, str]:
    raw = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
    return {"Authorization": f"Basic {raw}"}


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


# --- HTTP Basic auth (browser path) ---


def test_valid_basic_password_allows_request(monkeypatch: pytest.MonkeyPatch) -> None:
    """A browser without the custom header authenticates via Basic password == token."""
    client = _admin_client(monkeypatch)
    response = client.get("/_t", headers=_basic_header(_VALID_TOKEN))
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_basic_password_ignores_username(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _admin_client(monkeypatch)
    response = client.get("/_t", headers=_basic_header(_VALID_TOKEN, username="anything"))
    assert response.status_code == 200


def test_wrong_basic_password_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _admin_client(monkeypatch)
    response = client.get("/_t", headers=_basic_header("y" * 40))
    assert response.status_code == 401


def test_401_responses_carry_basic_challenge_header(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every 401 includes WWW-Authenticate: Basic so a browser shows a native prompt."""
    client = _admin_client(monkeypatch)

    missing = client.get("/_t")
    assert missing.status_code == 401
    assert missing.headers.get("WWW-Authenticate", "").lower().startswith("basic")

    wrong_basic = client.get("/_t", headers=_basic_header("y" * 40))
    assert wrong_basic.status_code == 401
    assert wrong_basic.headers.get("WWW-Authenticate", "").lower().startswith("basic")


def test_malformed_basic_header_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _admin_client(monkeypatch)
    # Not valid base64, and no scheme padding — must not crash, just 401.
    assert client.get("/_t", headers={"Authorization": "Basic not-base64!!"}).status_code == 401
    assert client.get("/_t", headers={"Authorization": "Basic"}).status_code == 401


# --- BR-01: non-ASCII credentials fail closed (401, not 500) ---


def _request_with_headers(raw_headers: list[tuple[bytes, bytes]]) -> Request:
    """Build a minimal ASGI Request carrying raw (byte) header values.

    A real client/browser can transmit non-ASCII header bytes that Starlette
    decodes (latin-1) into a non-ASCII str — the wire-level case the str-compare
    TypeError bug hit. The TestClient rejects non-ASCII header values before they
    reach the app, so we construct the Request directly to reproduce it.
    """
    return Request({"type": "http", "method": "GET", "path": "/_t", "headers": raw_headers})


@pytest.mark.asyncio
async def test_non_ascii_admin_token_header_returns_401_not_500(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-ASCII X-Admin-Token must fail closed with 401 + Basic challenge, never 500/TypeError.

    Comparing str via secrets.compare_digest raises TypeError on a non-ASCII
    code point; the byte-wise compare must reject it as a plain mismatch.
    """
    monkeypatch.setenv("RECOGNITION_ADMIN_ENABLED", "1")
    monkeypatch.setenv("RECOGNITION_ADMIN_TOKEN", _VALID_TOKEN)
    monkeypatch.delenv("RECOGNITION_ADMIN_TOKEN_HEADER", raising=False)

    non_ascii = ("é" * 40).encode("utf-8")  # raw wire bytes a browser could send
    request = _request_with_headers([(b"x-admin-token", non_ascii)])

    with pytest.raises(HTTPException) as caught:
        await require_admin(request)
    assert caught.value.status_code == 401
    assert caught.value.headers is not None
    assert caught.value.headers.get("WWW-Authenticate", "").lower().startswith("basic")


@pytest.mark.asyncio
async def test_basic_password_decoding_to_non_ascii_returns_401_not_500(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Basic password that decodes to non-ASCII must 401 (with Basic challenge), never 500/TypeError."""
    monkeypatch.setenv("RECOGNITION_ADMIN_ENABLED", "1")
    monkeypatch.setenv("RECOGNITION_ADMIN_TOKEN", _VALID_TOKEN)
    monkeypatch.delenv("RECOGNITION_ADMIN_TOKEN_HEADER", raising=False)

    raw = base64.b64encode(f"admin:{'é' * 40}".encode()).decode("ascii")
    request = _request_with_headers([(b"authorization", f"Basic {raw}".encode("ascii"))])

    with pytest.raises(HTTPException) as caught:
        await require_admin(request)
    assert caught.value.status_code == 401
    assert caught.value.headers is not None
    assert caught.value.headers.get("WWW-Authenticate", "").lower().startswith("basic")


# --- BR-02: require_same_origin CSRF guard on form POSTs ---


def _same_origin_client() -> TestClient:
    """Tiny app with one POST route gated only by require_same_origin."""
    app = FastAPI()

    @app.post("/_form", dependencies=[Depends(require_same_origin)])
    async def _form() -> dict[str, bool]:
        return {"ok": True}

    return TestClient(app)


def test_same_origin_guard_rejects_cross_origin_post() -> None:
    client = _same_origin_client()
    response = client.post(
        "/_form",
        headers={"Origin": "https://evil.example", "Host": "admin.test"},
    )
    assert response.status_code == 403
    assert "cross-origin" in response.json()["detail"]


def test_same_origin_guard_allows_matching_origin() -> None:
    client = _same_origin_client()
    response = client.post("/_form", headers={"Origin": "http://admin.test", "Host": "admin.test"})
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_same_origin_guard_allows_missing_origin_and_referer() -> None:
    """Programmatic header-token clients send neither Origin nor Referer → allowed."""
    client = _same_origin_client()
    response = client.post("/_form", headers={"Host": "admin.test"})
    assert response.status_code == 200


def test_same_origin_guard_falls_back_to_referer_on_mismatch() -> None:
    """When Origin is absent, a cross-origin Referer is still rejected."""
    client = _same_origin_client()
    response = client.post(
        "/_form",
        headers={"Referer": "https://evil.example/page", "Host": "admin.test"},
    )
    assert response.status_code == 403


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
