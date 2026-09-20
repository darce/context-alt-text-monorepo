"""APP-1 portal and billing app-mount tests."""

from __future__ import annotations

import inspect

import httpx
import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute

from recognition.infrastructure.billing.polar_provider import PolarBillingProvider
from recognition.interface_adapters.http.deps import session as session_deps
from recognition.interface_adapters.http.deps.auth import require_auth
from recognition.interface_adapters.http.deps.portal_auth import require_portal_principal
from recognition.interface_adapters.http.deps.portal_composition import BillingRepositoryFactory
from recognition.interface_adapters.http.middleware.upload_size import UploadSizeLimitMiddleware
from recognition.interface_adapters.http.routers.billing_webhooks import receive_polar_webhook

_PORTAL_ENV = "RECOGNITION_PORTAL_ENABLED"
_PORTAL_TEST_SETTINGS = {
    "ACX_CLERK_ISSUER": "https://issuer.example.test",
    "ACX_CLERK_JWKS_URL": "https://jwks.example.test/keys",
    "ACX_CLERK_AUTHORIZED_PARTIES": "portal-api",
    "POLAR_WEBHOOK_SECRET": "test-webhook-secret",
    "POLAR_PRODUCT_IDS": "starter=prod_starter",
}
_NEW_ROUTE_SIGNATURES = {
    ("/portal/me", frozenset({"GET"})),
    ("/portal/keys", frozenset({"GET"})),
    ("/portal/keys", frozenset({"POST"})),
    ("/portal/keys/{api_key_id}", frozenset({"GET"})),
    ("/portal/keys/{api_key_id}/rotate", frozenset({"POST"})),
    ("/portal/keys/{api_key_id}/revoke", frozenset({"POST"})),
    ("/portal/usage", frozenset({"GET"})),
    ("/billing/webhooks/polar", frozenset({"POST"})),
}


def _create_app(
    monkeypatch: pytest.MonkeyPatch,
    *,
    enabled: bool,
    configure_enabled: bool = True,
) -> FastAPI:
    monkeypatch.setenv("RECOGNITION_RUNTIME_MODE", "test")
    monkeypatch.delenv("RECOGNITION_ADMIN_ENABLED", raising=False)
    monkeypatch.delenv("RECOGNITION_ADMIN_TOKEN", raising=False)
    if enabled:
        monkeypatch.setenv(_PORTAL_ENV, "1")
        if configure_enabled:
            for name, value in _PORTAL_TEST_SETTINGS.items():
                monkeypatch.setenv(name, value)
    else:
        monkeypatch.delenv(_PORTAL_ENV, raising=False)

    from api.main import create_app

    return create_app()


class _SessionStub:
    bind = None

    async def execute(self, _statement: object) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None

    async def close(self) -> None:
        return None


def _route_signatures(app: FastAPI) -> set[tuple[str, frozenset[str]]]:
    return {
        (route.path, frozenset(route.methods or ()))
        for route in app.routes
        if isinstance(route, APIRoute)
    }


def _dependency_calls(route: APIRoute) -> set[object]:
    pending = list(route.dependant.dependencies)
    calls: set[object] = set()
    while pending:
        dependency = pending.pop()
        if dependency.call is not None:
            calls.add(dependency.call)
        pending.extend(dependency.dependencies)
    return calls


def _route(app: FastAPI, path: str, method: str) -> APIRoute:
    matches = [
        route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path == path and method in (route.methods or set())
    ]
    assert len(matches) == 1, f"expected one {method} {path}, got {len(matches)}"
    return matches[0]


def test_default_gate_keeps_portal_and_billing_routes_unmounted(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _create_app(monkeypatch, enabled=False)
    assert _route_signatures(app).isdisjoint(_NEW_ROUTE_SIGNATURES)


def test_enabled_mount_preserves_existing_routes_and_resolves_auth_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = _create_app(monkeypatch, enabled=False)
    baseline_routes = _route_signatures(baseline)

    app = _create_app(monkeypatch, enabled=True)
    mounted_routes = _route_signatures(app)

    assert baseline_routes <= mounted_routes
    assert mounted_routes - baseline_routes == _NEW_ROUTE_SIGNATURES

    portal_routes = [
        route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith("/portal")
    ]
    assert len(portal_routes) == 7
    for route in portal_routes:
        dependencies = _dependency_calls(route)
        assert require_portal_principal in dependencies, route.path

    webhook = _route(app, "/billing/webhooks/polar", "POST")
    webhook_dependencies = _dependency_calls(webhook)
    assert require_portal_principal not in webhook_dependencies
    assert require_auth not in webhook_dependencies
    assert webhook.endpoint is receive_polar_webhook
    assert "request" in inspect.signature(webhook.endpoint).parameters

    upload_middleware = next(
        middleware
        for middleware in app.user_middleware
        if middleware.cls is UploadSizeLimitMiddleware
    )
    assert "/billing/webhooks/polar" not in upload_middleware.kwargs["paths"]


def test_enabled_mount_has_each_expected_path_and_method_once(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _create_app(monkeypatch, enabled=True)
    assert _route_signatures(app) & _NEW_ROUTE_SIGNATURES == _NEW_ROUTE_SIGNATURES
    for path, methods in _NEW_ROUTE_SIGNATURES:
        for method in methods:
            assert sum(
                1
                for route in app.routes
                if isinstance(route, APIRoute)
                and route.path == path
                and method in (route.methods or set())
            ) == 1


@pytest.mark.asyncio
async def test_enabled_mount_resolves_real_portal_and_billing_composition(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_deps, "async_session_factory", _SessionStub)
    app = _create_app(monkeypatch, enabled=True)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        portal_response = await client.get("/portal/me")
        billing_response = await client.post("/billing/webhooks/polar", content=b"{}")

    assert portal_response.status_code == 401
    assert billing_response.status_code == 401
    assert callable(getattr(app.state.portal_token_verifier, "verify", None))
    assert isinstance(app.state.billing_provider, PolarBillingProvider)
    assert isinstance(app.state.billing_repository, BillingRepositoryFactory)


def test_enabled_mount_fails_before_mounting_when_required_setting_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name, value in _PORTAL_TEST_SETTINGS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("ACX_CLERK_JWKS_URL", raising=False)

    with pytest.raises(ValueError, match="ACX_CLERK_JWKS_URL"):
        _create_app(monkeypatch, enabled=True, configure_enabled=False)
