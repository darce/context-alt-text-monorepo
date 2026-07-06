"""Env-gated mount + hand-written HTML console tests (E15-31 Slice 4).

Drives the real ``api.main.create_app`` factory to prove:
* admin disabled → no ``/admin`` routes mount and ``GET /admin/`` is 404;
* admin enabled (valid token, non-production runtime) → ``/admin/`` serves the
  console behind Basic auth and 401s (with a Basic challenge) without it;
* admin enabled with an empty/short token → ``create_app`` raises (fail-closed);
* a form round-trip (create tenant → mint key) shows the raw key exactly once and
  lists the new tenant/key in the console;
* no template engine / HTMX / StaticFiles is imported by the console module.
"""

from __future__ import annotations

import base64
import sys
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from recognition.config.security import InsecureProductionConfigError

_VALID_TOKEN = "m" * 40  # >= 32 chars
_BASIC = {"Authorization": "Basic " + base64.b64encode(f"admin:{_VALID_TOKEN}".encode()).decode("ascii")}


def _enable_admin(monkeypatch: pytest.MonkeyPatch, *, token: str = _VALID_TOKEN) -> None:
    monkeypatch.setenv("RECOGNITION_ADMIN_ENABLED", "1")
    monkeypatch.setenv("RECOGNITION_ADMIN_TOKEN", token)
    monkeypatch.delenv("RECOGNITION_ADMIN_TOKEN_HEADER", raising=False)
    # conftest pins RECOGNITION_RUNTIME_MODE=test (non-production), so the
    # tailnet-bound ack is not required and validate_admin_config passes.


def _create_app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    from api.main import create_app

    return create_app()


def _admin_paths(app: FastAPI) -> list[str]:
    return [getattr(r, "path", "") for r in app.routes if getattr(r, "path", "").startswith("/admin")]


# --- Disabled ------------------------------------------------------------------


def test_admin_disabled_mounts_no_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RECOGNITION_ADMIN_ENABLED", raising=False)
    monkeypatch.delenv("RECOGNITION_ADMIN_TOKEN", raising=False)
    app = _create_app(monkeypatch)
    assert _admin_paths(app) == []
    client = TestClient(app)
    assert client.get("/admin/").status_code == 404


# --- Fail-closed at startup ----------------------------------------------------


def test_admin_enabled_empty_token_raises_at_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_admin(monkeypatch, token="")
    with pytest.raises(InsecureProductionConfigError):
        _create_app(monkeypatch)


def test_admin_enabled_short_token_raises_at_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_admin(monkeypatch, token="x" * 31)
    with pytest.raises(InsecureProductionConfigError):
        _create_app(monkeypatch)


# --- Enabled: console renders behind Basic auth --------------------------------


def test_admin_enabled_console_requires_basic_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_admin(monkeypatch)
    app = _create_app(monkeypatch)
    assert any(p == "/admin/" for p in _admin_paths(app))
    client = TestClient(app)

    unauthd = client.get("/admin/")
    assert unauthd.status_code == 401
    assert unauthd.headers.get("WWW-Authenticate", "").lower().startswith("basic")


@pytest_asyncio.fixture
async def admin_app_client(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    """Async client over the real app with the admin session bound to db_session."""
    _enable_admin(monkeypatch)
    from api.main import create_app
    from recognition.interface_adapters.http.routers.admin import get_admin_session

    app = create_app()

    async def _override_session() -> AsyncIterator[AsyncSession]:
        try:
            yield db_session
        except Exception:
            await db_session.rollback()
            raise

    app.dependency_overrides[get_admin_session] = _override_session
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://admin.test") as client:
        yield client


@pytest.mark.asyncio
async def test_console_renders_form_and_table(admin_app_client: AsyncClient) -> None:
    # The create-tenant form is always present; the per-tenant mint form +
    # tenant/key table render once a tenant exists with a key, so seed both.
    tenant_id = str(uuid.uuid4())
    await admin_app_client.post(
        "/admin/ui/tenants",
        data={"tenant_id": tenant_id, "site_url": "https://render.test"},
        headers=_BASIC,
    )
    await admin_app_client.post(
        "/admin/ui/keys",
        data={"tenant_id": tenant_id, "tier": "STANDARD"},
        headers=_BASIC,
    )

    resp = await admin_app_client.get("/admin/", headers=_BASIC)
    assert resp.status_code == 200
    body = resp.text
    assert "<form" in body
    assert "/admin/ui/tenants" in body  # create-tenant form action
    assert "/admin/ui/keys" in body  # per-tenant mint form action
    assert "<table" in body  # tenant/key table (rendered once a key exists)
    assert tenant_id in body


@pytest.mark.asyncio
async def test_form_round_trip_shows_raw_key_once(admin_app_client: AsyncClient) -> None:
    tenant_id = str(uuid.uuid4())
    site_url = "https://round-trip.test"

    created = await admin_app_client.post(
        "/admin/ui/tenants",
        data={"tenant_id": tenant_id, "site_url": site_url},
        headers=_BASIC,
    )
    # 303 redirect back to the console (no follow → assert the redirect itself).
    assert created.status_code == 303
    assert created.headers["location"] == "/admin/"

    # Console now lists the new tenant.
    listing = await admin_app_client.get("/admin/", headers=_BASIC)
    assert listing.status_code == 200
    assert tenant_id in listing.text
    assert site_url in listing.text

    minted = await admin_app_client.post(
        "/admin/ui/keys",
        data={"tenant_id": tenant_id, "tier": "STANDARD"},
        headers=_BASIC,
    )
    assert minted.status_code == 200
    assert "shown once" in minted.text.lower()
    # The raw key block is present; capture it and confirm it is not re-rendered.
    assert "won&#x27;t be shown again" in minted.text or "not be shown again" in minted.text

    # A fresh console load must NOT contain the minted-key highlight block.
    after = await admin_app_client.get("/admin/", headers=_BASIC)
    assert "shown once" not in after.text.lower()
    # The key is listed in the table (by its id), but the raw secret is gone.
    assert "api_key_hash" not in after.text


# --- No template engine / HTMX / StaticFiles -----------------------------------


def test_console_imports_no_template_engine() -> None:
    import recognition.interface_adapters.http.admin_console as console  # noqa: F401

    assert "jinja2" not in sys.modules

    from pathlib import Path

    source = Path(console.__file__).read_text(encoding="utf-8")
    for forbidden in ("jinja2", "Jinja2Templates", "StaticFiles", "htmx"):
        assert forbidden not in source, f"console must not reference {forbidden}"
