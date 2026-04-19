"""CORS origin allowlist tests (Slice 2 of E15-1).

Covers:
- allowlisted origin receives matching Access-Control-Allow-Origin
- non-allowlisted origin receives no CORS header
- preflight OPTIONS returns pinned allow_methods / allow_headers / max_age
- empty allowlist (default) blocks all CORS
- Access-Control-Allow-Credentials is absent (allow_credentials=False)
- wildcard '*' in allowed_origins raises at construction
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError


def _build_app(monkeypatch, *, origins: str | None) -> FastAPI:
    if origins is None:
        monkeypatch.delenv("RECOGNITION_ALLOWED_ORIGINS", raising=False)
    else:
        monkeypatch.setenv("RECOGNITION_ALLOWED_ORIGINS", origins)
    # Prevent create_app from raising dev-key / production issues in tests.
    monkeypatch.setenv("RECOGNITION_RUNTIME_MODE", "test")
    monkeypatch.delenv("RECOGNITION_ALLOWED_API_KEYS", raising=False)

    # Build a minimal app that wires just the CORS middleware against the
    # freshly-evaluated SecuritySettings. Mirrors api.main.create_app wiring.
    from starlette.middleware.cors import CORSMiddleware

    from recognition.config.security import get_security_settings

    settings = get_security_settings()
    app = FastAPI()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=False,
        allow_origin_regex=None,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "X-Api-Key", "X-Tenant-ID", "Content-Type"],
        max_age=600,
    )

    @app.get("/probe")
    def _probe() -> dict[str, str]:
        return {"ok": "yes"}

    return app


def test_allowlisted_origin_gets_matching_header(monkeypatch) -> None:
    app = _build_app(monkeypatch, origins="https://ok.example.com")
    client = TestClient(app)
    resp = client.get("/probe", headers={"Origin": "https://ok.example.com"})
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "https://ok.example.com"


def test_non_allowlisted_origin_gets_no_header(monkeypatch) -> None:
    app = _build_app(monkeypatch, origins="https://ok.example.com")
    client = TestClient(app)
    resp = client.get("/probe", headers={"Origin": "https://evil.example.com"})
    assert resp.status_code == 200
    assert "access-control-allow-origin" not in {k.lower() for k in resp.headers}


def test_preflight_returns_pinned_methods_headers_and_max_age(monkeypatch) -> None:
    app = _build_app(monkeypatch, origins="https://ok.example.com")
    client = TestClient(app)
    resp = client.options(
        "/probe",
        headers={
            "Origin": "https://ok.example.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,x-api-key,x-tenant-id,content-type",
        },
    )
    assert resp.status_code == 200
    allow_methods = resp.headers.get("access-control-allow-methods", "")
    for method in ("GET", "POST", "PATCH", "DELETE", "OPTIONS"):
        assert method in allow_methods, f"missing {method} in {allow_methods!r}"
    allow_headers = resp.headers.get("access-control-allow-headers", "").lower()
    for header in ("authorization", "x-api-key", "x-tenant-id", "content-type"):
        assert header in allow_headers, f"missing {header} in {allow_headers!r}"
    assert resp.headers.get("access-control-max-age") == "600"


def test_empty_allowlist_blocks_all_cors(monkeypatch) -> None:
    app = _build_app(monkeypatch, origins=None)
    client = TestClient(app)
    resp = client.get("/probe", headers={"Origin": "https://anywhere.example.com"})
    assert resp.status_code == 200
    assert "access-control-allow-origin" not in {k.lower() for k in resp.headers}


def test_allow_credentials_header_absent(monkeypatch) -> None:
    app = _build_app(monkeypatch, origins="https://ok.example.com")
    client = TestClient(app)
    resp = client.get("/probe", headers={"Origin": "https://ok.example.com"})
    assert resp.status_code == 200
    assert "access-control-allow-credentials" not in {k.lower() for k in resp.headers}

    # Also assert absent on preflight.
    pre = client.options(
        "/probe",
        headers={
            "Origin": "https://ok.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "access-control-allow-credentials" not in {k.lower() for k in pre.headers}


def test_wildcard_origin_rejected_by_config(monkeypatch) -> None:
    from recognition.config.security import SecuritySettings

    with pytest.raises((ValueError, ValidationError)):
        SecuritySettings(allowed_origins=["*"])

    # Env-driven path must also reject.
    monkeypatch.setenv("RECOGNITION_ALLOWED_ORIGINS", "*")
    with pytest.raises((ValueError, ValidationError)):
        SecuritySettings()
