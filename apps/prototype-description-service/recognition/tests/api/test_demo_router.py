"""API tests for GET /x/{slug} demo resolve + per-IP rate limit (DS-2 / DS-5)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import DemoInstance
from recognition.application.services.demo_provisioning_service import (
    PreScanStateError,
    provision_demo,
    reset_demo_sessions_for_tests,
)
from recognition.interface_adapters.http import deps as dependencies
from recognition.interface_adapters.http.deps import ip_rate_limit
from recognition.interface_adapters.http.routers import demo as demo_routes

_TENANT_DATA_KEYS = ("tenant_id", "seed_bundle", "branding_json", "quota_remaining")


def _reset_ip_limiter() -> None:
    ip_rate_limit._reset_state_for_tests()


def _build_client(
    session: AsyncSession,
    monkeypatch,
    *,
    rpm: str = "100",
    provision_rpm: str = "100",
) -> TestClient:
    monkeypatch.setenv("RECOGNITION_DEMO_RESOLVE_RPM", rpm)
    monkeypatch.setenv("RECOGNITION_DEMO_PROVISION_RPM", provision_rpm)
    _reset_ip_limiter()
    demo_routes._reset_provision_limiter_for_tests()
    reset_demo_sessions_for_tests()

    app = FastAPI()
    app.include_router(demo_routes.router)

    async def _session_dep():
        yield session

    app.dependency_overrides[dependencies.get_session] = _session_dep
    app.dependency_overrides[dependencies.get_optional_session] = _session_dep
    return TestClient(app, base_url="https://testserver")


def _assert_no_tenant_data(resp) -> None:  # noqa: ANN001
    body = resp.json()
    for key in _TENANT_DATA_KEYS:
        assert key not in body
        assert key not in resp.text
    detail = body.get("detail")
    if isinstance(detail, dict):
        for key in _TENANT_DATA_KEYS:
            assert key not in detail


def _cookie_header(resp) -> str:  # noqa: ANN001
    return resp.headers.get("set-cookie", "")


def _mint_session(client: TestClient, slug: str) -> str:
    resp = client.post(f"/x/{slug}/session")
    assert resp.status_code == 201, resp.text
    token = resp.json()["session_token"]
    assert token
    set_cookie = _cookie_header(resp)
    assert "acx_demo_session=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "Secure" in set_cookie
    assert "SameSite=lax" in set_cookie or "SameSite=Lax" in set_cookie
    assert "Path=/x" in set_cookie
    return token


@pytest.mark.asyncio
async def test_demo_router_anonymous_get_returns_401_without_tenant_data(
    db_session: AsyncSession, monkeypatch
) -> None:
    result = await provision_demo(db_session, label="Anon", seed="default", branding={"logo": "hidden"})
    await db_session.commit()

    client = _build_client(db_session, monkeypatch)
    resp = client.get(f"/x/{result.instance.slug}")
    assert resp.status_code == 401
    _assert_no_tenant_data(resp)
    assert str(result.instance.tenant_id) not in resp.text
    assert result.raw_api_key not in resp.text


@pytest.mark.asyncio
async def test_demo_router_session_happy_path_resolves_without_key_material(
    db_session: AsyncSession, monkeypatch
) -> None:
    result = await provision_demo(
        db_session,
        label="Resolve Me",
        seed="default",
        branding={"logo": "acme"},
    )
    await db_session.commit()

    client = _build_client(db_session, monkeypatch)
    token = _mint_session(client, result.instance.slug)
    resp = client.get(f"/x/{result.instance.slug}", headers={"X-Demo-Session": token})
    assert resp.status_code == 200
    body = resp.json()
    assert body["tenant_id"] == str(result.instance.tenant_id)
    assert body["seed_bundle"] == "default"
    assert body["branding_json"] == {"logo": "acme"}
    assert body["quota_remaining"] == result.instance.recognition_quota
    assert "expires_at" in body
    assert body["pre_scan"] == {
        "seeded_media_present": True,
        "scanned_faces": 0,
        "people_count": 0,
    }

    blob = resp.text
    assert result.raw_api_key not in blob
    assert result.instance.api_key_ref not in blob
    assert "api_key" not in body
    assert "api_key_ref" not in body


@pytest.mark.asyncio
async def test_demo_router_cookie_only_get_resolves_without_session_header(
    db_session: AsyncSession, monkeypatch
) -> None:
    result = await provision_demo(db_session, label="CookieOnly", seed="default")
    await db_session.commit()

    client = _build_client(db_session, monkeypatch)
    mint = client.post(f"/x/{result.instance.slug}/session")
    assert mint.status_code == 201, mint.text
    set_cookie = _cookie_header(mint)
    assert "SameSite=lax" in set_cookie or "SameSite=Lax" in set_cookie
    assert "Path=/x" in set_cookie
    assert "X-Demo-Session" not in mint.request.headers

    resp = client.get(f"/x/{result.instance.slug}")
    assert "x-demo-session" not in {k.lower() for k in resp.request.headers.keys()}
    assert resp.status_code == 200, resp.text
    assert resp.json()["tenant_id"] == str(result.instance.tenant_id)


@pytest.mark.asyncio
async def test_demo_router_expired_session_returns_401_without_tenant_data(
    db_session: AsyncSession, monkeypatch
) -> None:
    result = await provision_demo(db_session, label="SessExp", seed="default")
    await db_session.commit()

    from recognition.application.services import demo_provisioning_service as svc

    client = _build_client(db_session, monkeypatch)
    minted = svc.mint_demo_session(
        result.instance.slug,
        ttl_seconds=60,
        now=datetime.now(tz=UTC) - timedelta(seconds=120),
    )
    resp = client.get(
        f"/x/{result.instance.slug}",
        headers={"X-Demo-Session": minted.token},
    )
    assert resp.status_code == 401
    _assert_no_tenant_data(resp)
    assert str(result.instance.tenant_id) not in resp.text


@pytest.mark.asyncio
async def test_demo_router_invalid_session_returns_401_without_tenant_data(
    db_session: AsyncSession, monkeypatch
) -> None:
    result = await provision_demo(db_session, label="BadSess", seed="default")
    await db_session.commit()

    client = _build_client(db_session, monkeypatch)
    resp = client.get(f"/x/{result.instance.slug}", headers={"X-Demo-Session": "not-a-real-token"})
    assert resp.status_code == 401
    _assert_no_tenant_data(resp)


@pytest.mark.asyncio
async def test_demo_router_unknown_seed_bundle_returns_410_without_tenant_data(
    db_session: AsyncSession, monkeypatch
) -> None:
    result = await provision_demo(db_session, label="RetiredBundle", seed="default")
    instance = await db_session.get(DemoInstance, result.instance.slug)
    assert instance is not None
    instance.seed_bundle = "retired-bundle"
    await db_session.commit()

    client = _build_client(db_session, monkeypatch)
    get_resp = client.get(f"/x/{result.instance.slug}")
    assert get_resp.status_code == 410
    _assert_no_tenant_data(get_resp)
    assert str(result.instance.tenant_id) not in get_resp.text

    session_resp = client.post(f"/x/{result.instance.slug}/session")
    assert session_resp.status_code == 410
    _assert_no_tenant_data(session_resp)
    assert str(result.instance.tenant_id) not in session_resp.text


@pytest.mark.asyncio
async def test_demo_router_unknown_slug_returns_uniform_404(db_session: AsyncSession, monkeypatch) -> None:
    client = _build_client(db_session, monkeypatch)
    resp = client.get("/x/notreal1")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "not found"


@pytest.mark.asyncio
async def test_demo_router_expired_returns_410_demo_ended(db_session: AsyncSession, monkeypatch) -> None:
    result = await provision_demo(db_session, label="Expired", seed="default")
    instance = await db_session.get(DemoInstance, result.instance.slug)
    assert instance is not None
    instance.expires_at = datetime.now(tz=UTC) - timedelta(hours=1)
    await db_session.commit()

    client = _build_client(db_session, monkeypatch)
    resp = client.get(f"/x/{result.instance.slug}")
    assert resp.status_code == 410
    detail = resp.json()["detail"]
    assert detail["code"] == "demo_ended"


@pytest.mark.asyncio
async def test_demo_router_revoked_returns_410_demo_ended(db_session: AsyncSession, monkeypatch) -> None:
    result = await provision_demo(db_session, label="Revoked", seed="default")
    instance = await db_session.get(DemoInstance, result.instance.slug)
    assert instance is not None
    instance.revoked = True
    await db_session.commit()

    client = _build_client(db_session, monkeypatch)
    resp = client.get(f"/x/{result.instance.slug}")
    assert resp.status_code == 410
    assert resp.json()["detail"]["code"] == "demo_ended"


@pytest.mark.asyncio
async def test_demo_router_enumeration_burst_returns_429(db_session: AsyncSession, monkeypatch) -> None:
    client = _build_client(db_session, monkeypatch, rpm="3")
    for _ in range(3):
        assert client.get("/x/guess001").status_code in {404, 429}
    # Force a clean under-limit path then breach.
    _reset_ip_limiter()
    for _ in range(3):
        assert client.get("/x/guess002").status_code == 404
    resp = client.get("/x/guess003")
    assert resp.status_code == 429
    assert resp.json()["detail"] == "rate limit exceeded"
    assert "Retry-After" in resp.headers
    assert resp.headers["X-RateLimit-Limit"] == "3"
    assert resp.headers["X-RateLimit-Remaining"] == "0"


@pytest.mark.asyncio
async def test_demo_router_xff_spoof_cannot_evade_ip_limit(db_session: AsyncSession, monkeypatch) -> None:
    """With one trusted proxy hop, varying the left-most (spoofable) XFF token
    must NOT mint a fresh bucket — the right-most (proxy-appended) client is the
    key, so an enumerating attacker still hits 429."""
    monkeypatch.setenv("RECOGNITION_DEMO_TRUSTED_PROXY_HOPS", "1")
    client = _build_client(db_session, monkeypatch, rpm="3")

    # Real client 1.2.3.4 behind Caddy; attacker rotates the left-most token.
    for i in range(3):
        resp = client.get("/x/guessN", headers={"X-Forwarded-For": f"spoof{i}, 1.2.3.4"})
        assert resp.status_code == 404
    resp = client.get("/x/guessN", headers={"X-Forwarded-For": "spoofZ, 1.2.3.4"})
    assert resp.status_code == 429


@pytest.mark.asyncio
async def test_demo_provision_endpoint_returns_slug_without_key_material(
    db_session: AsyncSession, monkeypatch
) -> None:
    client = _build_client(db_session, monkeypatch)
    resp = client.post("/x/provision", json={"label": "Prospect Gallery", "seed": "default"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["seed_bundle"] == "default"
    assert body["demo_url"].startswith("https://demo.altcontext.com/x/")
    assert body["slug"]
    assert body["pre_scan"] == {
        "seeded_media_present": True,
        "scanned_faces": 0,
        "people_count": 0,
    }
    assert "api_key" not in body
    assert "api_key_ref" not in body
    assert "session_token" not in body
    row = await db_session.get(DemoInstance, body["slug"])
    assert row is not None
    assert row.label == "Prospect Gallery"


@pytest.mark.asyncio
async def test_demo_provision_zero_rpm_falls_back_to_default_and_429s(
    db_session: AsyncSession, monkeypatch
) -> None:
    client = _build_client(db_session, monkeypatch, provision_rpm="0")
    for _ in range(3):
        assert client.post("/x/provision", json={"label": "ZeroRpm"}).status_code == 201
    resp = client.post("/x/provision", json={"label": "ZeroRpm"})
    assert resp.status_code == 429
    assert resp.json()["detail"] == "rate limit exceeded"
    assert resp.headers["X-RateLimit-Limit"] == "3"


@pytest.mark.asyncio
async def test_demo_provision_flood_returns_429(db_session: AsyncSession, monkeypatch) -> None:
    client = _build_client(db_session, monkeypatch, provision_rpm="2")
    for _ in range(2):
        assert client.post("/x/provision", json={"label": "Flood"}).status_code == 201
    resp = client.post("/x/provision", json={"label": "Flood"})
    assert resp.status_code == 429
    assert resp.json()["detail"] == "rate limit exceeded"
    assert "Retry-After" in resp.headers
    assert resp.headers["X-RateLimit-Limit"] == "2"
    assert resp.headers["X-RateLimit-Remaining"] == "0"


@pytest.mark.asyncio
async def test_demo_provision_pre_scan_violation_returns_409(
    db_session: AsyncSession, monkeypatch
) -> None:
    async def _boom(*_args, **_kwargs):  # noqa: ANN002, ANN003
        raise PreScanStateError("scanned_faces must be 0, got 1")

    client = _build_client(db_session, monkeypatch)
    monkeypatch.setattr(demo_routes, "provision_demo", _boom)
    resp = client.post("/x/provision", json={"label": "Broken Schema", "seed": "default"})
    assert resp.status_code == 409
    assert "scanned_faces" in resp.json()["detail"]
    _assert_no_tenant_data(resp)


def test_demo_router_mounted_on_create_app() -> None:
    from api.main import create_app

    app = create_app()
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/x/{slug}" in paths
    assert "/x/{slug}/session" in paths
    assert "/x/provision" in paths
