"""DB-backed tests for the admin tenant + API-key lifecycle router (E15-31 Slice 3).

Drives ``admin_router`` (mounted under ``/admin``) through an in-process
``httpx.AsyncClient`` + ``ASGITransport`` so the route runs in the SAME event
loop as the in-memory ``db_session`` fixture. ``get_admin_session`` is overridden
to yield that shared session; ``require_admin`` is left live and satisfied with a
valid ``X-Admin-Token``. Asserts the full lifecycle, the auth gate, atomic audit
writes, audit-failure rollback, and the full error contract.
"""

from __future__ import annotations

import base64
import hashlib
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ApiKey, AuditEvent
from recognition.application.services.api_key_admin_service import mint_api_key as _mint_symbol
from recognition.application.services.audit_service import AuditService
from recognition.config.security import InsecureProductionConfigError
from recognition.infrastructure.repositories.api_key_repository import SqlAlchemyApiKeyRepository
from recognition.interface_adapters.http.routers import admin as admin_module
from recognition.interface_adapters.http.routers.admin import (
    AdminAuditEvent,
    admin_router,
    assert_admin_env_dsn,
    get_admin_session,
)

_VALID_TOKEN = "z" * 40  # >= 32 chars
_AUTH = {"X-Admin-Token": _VALID_TOKEN}


def _basic_auth() -> dict[str, str]:
    encoded = base64.b64encode(f"admin:{_VALID_TOKEN}".encode()).decode("ascii")
    return {"Authorization": f"Basic {encoded}"}


@pytest_asyncio.fixture
async def admin_client(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AsyncClient]:
    """Async client over the ASGI app; admin session bound to the test db_session."""
    monkeypatch.setenv("RECOGNITION_ADMIN_ENABLED", "1")
    monkeypatch.setenv("RECOGNITION_ADMIN_TOKEN", _VALID_TOKEN)
    monkeypatch.delenv("RECOGNITION_ADMIN_TOKEN_HEADER", raising=False)

    app = FastAPI()
    app.include_router(admin_router, prefix="/admin")

    async def _override_session() -> AsyncIterator[AsyncSession]:
        try:
            yield db_session
        except Exception:
            await db_session.rollback()
            raise

    app.dependency_overrides[get_admin_session] = _override_session
    # raise_app_exceptions=False: an unhandled server error becomes a 500 response
    # (so the audit-failure-rollback test can assert the 500 + DB rollback) rather
    # than re-raising the exception into the test, matching TestClient semantics.
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://admin.test") as client:
        yield client


async def _count(session: AsyncSession, model: object) -> int:
    return int((await session.execute(select(func.count()).select_from(model))).scalar_one())


async def _audit_count(session: AsyncSession, event_type: str) -> int:
    stmt = select(func.count()).select_from(AuditEvent).where(AuditEvent.event_type == event_type)
    return int((await session.execute(stmt)).scalar_one())


# --- Full lifecycle ------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_lifecycle_create_list_mint_revoke(admin_client: AsyncClient, db_session: AsyncSession) -> None:
    tenant_id = str(uuid.uuid4())

    resp = await admin_client.post(
        "/admin/tenants", json={"tenant_id": tenant_id, "site_url": "http://t1.test"}, headers=_AUTH
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["tenant_id"] == tenant_id

    resp = await admin_client.get("/admin/tenants", headers=_AUTH)
    assert resp.status_code == 200
    assert any(row["tenant_id"] == tenant_id for row in resp.json())

    resp = await admin_client.post(f"/admin/tenants/{tenant_id}/keys", json={"tier": "PRO"}, headers=_AUTH)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    raw_key = body["api_key"]
    key_id = body["key_id"]
    assert raw_key
    assert body["rate_limit_tier"] == "PRO"
    assert "hash" not in resp.text.lower()

    resp = await admin_client.get(f"/admin/tenants/{tenant_id}/keys", headers=_AUTH)
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["status"] == "active"
    assert rows[0]["key_id"] == key_id
    assert "api_key_hash" not in rows[0]
    assert "api_key" not in rows[0]

    # raw key authenticates a lookup via the repo (hash resolves)
    digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    record = await SqlAlchemyApiKeyRepository(db_session).get_by_hash(digest)
    assert record is not None
    assert str(record.id) == key_id

    resp = await admin_client.post(f"/admin/keys/{key_id}/revoke", headers=_AUTH)
    assert resp.status_code == 200, resp.text
    assert resp.json()["already_revoked"] is False
    assert resp.json()["revoked_at"]

    resp = await admin_client.get(f"/admin/tenants/{tenant_id}/keys", headers=_AUTH)
    assert resp.json()[0]["status"] == "revoked"


# --- Auth gate -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_every_route_requires_admin_token(admin_client: AsyncClient) -> None:
    tenant_id = str(uuid.uuid4())
    key_id = str(uuid.uuid4())
    routes = [
        ("post", "/admin/tenants", {"tenant_id": tenant_id, "site_url": "http://x.test"}),
        ("get", "/admin/tenants", None),
        ("post", f"/admin/tenants/{tenant_id}/keys", {}),
        ("get", f"/admin/tenants/{tenant_id}/keys", None),
        ("post", f"/admin/keys/{key_id}/revoke", None),
    ]
    for method, path, json_body in routes:
        call = getattr(admin_client, method)
        resp = await (call(path, json=json_body) if json_body is not None else call(path))
        assert resp.status_code == 401, f"{method.upper()} {path} should require admin token"


@pytest.mark.asyncio
async def test_json_mutations_reject_browser_basic_auth(admin_client: AsyncClient) -> None:
    """Basic auth is console-only; JSON mutations require the custom header."""
    tenant_id = str(uuid.uuid4())
    key_id = str(uuid.uuid4())
    requests = [
        ("/admin/tenants", {"tenant_id": tenant_id, "site_url": "http://csrf.test"}),
        (f"/admin/tenants/{tenant_id}/keys", {}),
        (f"/admin/keys/{key_id}/revoke", None),
    ]

    for path, json_body in requests:
        response = await admin_client.post(path, json=json_body, headers=_basic_auth())
        assert response.status_code == 401, path


# --- Audit row per mutation ----------------------------------------------------


@pytest.mark.asyncio
async def test_audit_row_written_for_each_mutation(admin_client: AsyncClient, db_session: AsyncSession) -> None:
    tenant_id = str(uuid.uuid4())

    await admin_client.post(
        "/admin/tenants", json={"tenant_id": tenant_id, "site_url": "http://audit.test"}, headers=_AUTH
    )
    assert await _audit_count(db_session, AdminAuditEvent.TENANT_CREATE) == 1

    resp = await admin_client.post(f"/admin/tenants/{tenant_id}/keys", json={}, headers=_AUTH)
    key_id = resp.json()["key_id"]
    assert await _audit_count(db_session, AdminAuditEvent.API_KEY_MINT) == 1

    await admin_client.post(f"/admin/keys/{key_id}/revoke", headers=_AUTH)
    assert await _audit_count(db_session, AdminAuditEvent.API_KEY_REVOKE) == 1


# --- Injected audit failure rolls back the mutation ----------------------------


@pytest.mark.asyncio
async def test_injected_audit_failure_rolls_back_mint(
    admin_client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the audit write raises, the api_keys row must not persist (atomic).

    Monkeypatch target: ``AuditService.record_event`` (the single audit write the
    mint handler performs after the key is flushed). It raises before commit, so
    ``get_admin_session`` rolls back and no api_keys row survives.
    """
    tenant_id = str(uuid.uuid4())
    await admin_client.post(
        "/admin/tenants", json={"tenant_id": tenant_id, "site_url": "http://rollback.test"}, headers=_AUTH
    )

    keys_before = await _count(db_session, ApiKey)

    async def _boom(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise RuntimeError("audit write failed")

    monkeypatch.setattr(AuditService, "record_event", _boom)

    resp = await admin_client.post(f"/admin/tenants/{tenant_id}/keys", json={}, headers=_AUTH)
    assert resp.status_code == 500

    keys_after = await _count(db_session, ApiKey)
    assert keys_after == keys_before  # mint rolled back, no orphaned key


# --- Error contract ------------------------------------------------------------


@pytest.mark.asyncio
async def test_mint_unknown_tenant_returns_404(admin_client: AsyncClient) -> None:
    unknown = str(uuid.uuid4())
    resp = await admin_client.post(f"/admin/tenants/{unknown}/keys", json={}, headers=_AUTH)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_duplicate_site_url_on_second_tenant_returns_409(admin_client: AsyncClient) -> None:
    first = str(uuid.uuid4())
    second = str(uuid.uuid4())
    url = "http://dup.test"
    r1 = await admin_client.post("/admin/tenants", json={"tenant_id": first, "site_url": url}, headers=_AUTH)
    assert r1.status_code == 201
    r2 = await admin_client.post("/admin/tenants", json={"tenant_id": second, "site_url": url}, headers=_AUTH)
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_revoke_unknown_key_returns_404(admin_client: AsyncClient) -> None:
    resp = await admin_client.post(f"/admin/keys/{uuid.uuid4()}/revoke", headers=_AUTH)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_revoke_already_revoked_is_idempotent_no_second_audit(
    admin_client: AsyncClient, db_session: AsyncSession
) -> None:
    tenant_id = str(uuid.uuid4())
    await admin_client.post(
        "/admin/tenants", json={"tenant_id": tenant_id, "site_url": "http://idem.test"}, headers=_AUTH
    )
    mint = await admin_client.post(f"/admin/tenants/{tenant_id}/keys", json={}, headers=_AUTH)
    key_id = mint.json()["key_id"]

    first = await admin_client.post(f"/admin/keys/{key_id}/revoke", headers=_AUTH)
    assert first.status_code == 200
    original_revoked_at = first.json()["revoked_at"]
    assert await _audit_count(db_session, AdminAuditEvent.API_KEY_REVOKE) == 1

    second = await admin_client.post(f"/admin/keys/{key_id}/revoke", headers=_AUTH)
    assert second.status_code == 200
    assert second.json()["already_revoked"] is True
    assert second.json()["revoked_at"] == original_revoked_at  # unchanged, no re-stamp
    assert await _audit_count(db_session, AdminAuditEvent.API_KEY_REVOKE) == 1  # no second audit row


# --- Env/DSN guard -------------------------------------------------------------


def test_assert_admin_env_dsn_raises_production_with_local_dsn() -> None:
    with pytest.raises(RuntimeError):
        assert_admin_env_dsn(runtime_mode="production", dsn="postgresql+asyncpg://user@localhost:5432/db")


def test_assert_admin_env_dsn_passes_non_production_with_local_dsn() -> None:
    # Returns None on agreement; a mismatch would raise. Just call it.
    assert_admin_env_dsn(runtime_mode="test", dsn="postgresql+asyncpg://user@127.0.0.1:5432/db")


def test_config_guard_and_mint_symbol_importable() -> None:
    """Sanity: fail-closed config guard + shared mint helper remain importable."""
    assert InsecureProductionConfigError is not None
    assert admin_module.mint_api_key is _mint_symbol


# --- BR-03: expires_in_days bound (no OverflowError → 500) ----------------------


@pytest.mark.asyncio
async def test_mint_json_out_of_range_expiry_returns_422_not_500(
    admin_client: AsyncClient, db_session: AsyncSession
) -> None:
    tenant_id = str(uuid.uuid4())
    await admin_client.post(
        "/admin/tenants", json={"tenant_id": tenant_id, "site_url": "http://expiry.test"}, headers=_AUTH
    )
    resp = await admin_client.post(
        f"/admin/tenants/{tenant_id}/keys", json={"expires_in_days": 3_000_000}, headers=_AUTH
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_console_mint_form_out_of_range_expiry_returns_400_not_500(
    admin_client: AsyncClient, db_session: AsyncSession
) -> None:
    tenant_id = str(uuid.uuid4())
    await admin_client.post(
        "/admin/tenants", json={"tenant_id": tenant_id, "site_url": "http://expiry-form.test"}, headers=_AUTH
    )
    resp = await admin_client.post(
        "/admin/ui/keys",
        data={"tenant_id": tenant_id, "tier": "STANDARD", "expires_in_days": "3000000"},
        headers={**_AUTH, "Origin": "http://admin.test"},
    )
    assert resp.status_code == 400, resp.text


# --- BR-02: same-origin guard on form routes -----------------------------------


@pytest.mark.asyncio
async def test_console_mint_form_rejects_cross_origin(
    admin_client: AsyncClient, db_session: AsyncSession
) -> None:
    tenant_id = str(uuid.uuid4())
    await admin_client.post(
        "/admin/tenants", json={"tenant_id": tenant_id, "site_url": "http://csrf.test"}, headers=_AUTH
    )
    resp = await admin_client.post(
        "/admin/ui/keys",
        data={"tenant_id": tenant_id, "tier": "STANDARD"},
        headers={**_AUTH, "Origin": "https://evil.example"},
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_console_mint_form_allows_same_origin(
    admin_client: AsyncClient, db_session: AsyncSession
) -> None:
    tenant_id = str(uuid.uuid4())
    await admin_client.post(
        "/admin/tenants", json={"tenant_id": tenant_id, "site_url": "http://ok-origin.test"}, headers=_AUTH
    )
    resp = await admin_client.post(
        "/admin/ui/keys",
        data={"tenant_id": tenant_id, "tier": "STANDARD"},
        headers={**_AUTH, "Origin": "http://admin.test"},
    )
    assert resp.status_code == 200, resp.text


# --- BR-04: console single key query + per-tenant cap --------------------------


@pytest.mark.asyncio
async def test_console_caps_keys_and_renders_note(
    admin_client: AsyncClient, db_session: AsyncSession
) -> None:
    """A tenant with > cap keys renders the 'showing N of M' note and is capped."""
    from recognition.interface_adapters.http.routers.admin import _CONSOLE_KEYS_PER_TENANT

    tenant_id = str(uuid.uuid4())
    await admin_client.post(
        "/admin/tenants", json={"tenant_id": tenant_id, "site_url": "http://cap.test"}, headers=_AUTH
    )

    over_cap = _CONSOLE_KEYS_PER_TENANT + 5
    repo = SqlAlchemyApiKeyRepository(db_session)
    for index in range(over_cap):
        await repo.create(tenant_id=uuid.UUID(tenant_id), hashed_key=f"hash-{index:04d}")
    await db_session.commit()

    resp = await admin_client.get("/admin/", headers=_AUTH)
    assert resp.status_code == 200, resp.text
    body = resp.text
    assert f"Showing {_CONSOLE_KEYS_PER_TENANT} of {over_cap} keys" in body


@pytest.mark.asyncio
async def test_console_loads_keys_in_single_query_no_n_plus_one(
    admin_client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_load_console_model issues ONE key query regardless of tenant count (no N+1)."""
    from recognition.interface_adapters.http.routers import admin as admin_mod

    # Seed several tenants, each with a key, so an N+1 loop would issue many queries.
    tenant_ids = [str(uuid.uuid4()) for _ in range(4)]
    for index, tid in enumerate(tenant_ids):
        await admin_client.post(
            "/admin/tenants", json={"tenant_id": tid, "site_url": f"http://n1-{index}.test"}, headers=_AUTH
        )
        await admin_client.post(f"/admin/tenants/{tid}/keys", json={}, headers=_AUTH)

    # Count list_for_tenant invocations during a console load: the fixed query must
    # NOT loop the repo per tenant.
    calls = {"n": 0}
    original = SqlAlchemyApiKeyRepository.list_for_tenant

    async def _counting(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        calls["n"] += 1
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(SqlAlchemyApiKeyRepository, "list_for_tenant", _counting)

    tenants, keys_by_tenant, totals_by_tenant = await admin_mod._load_console_model(db_session)
    assert calls["n"] == 0  # no per-tenant repo loop
    assert len(tenants) == len(tenant_ids)
    # Every tenant present in both maps (empty list allowed), keys grouped correctly.
    for tid in tenant_ids:
        assert uuid.UUID(tid) in keys_by_tenant
        assert totals_by_tenant[uuid.UUID(tid)] == 1
        assert len(keys_by_tenant[uuid.UUID(tid)]) == 1
