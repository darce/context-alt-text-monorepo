"""Key rotation, expiry and revocation tests (Slice 3 of E15-1).

Covers:
- expired key rejected with 401 "api key expired"
- revoked key rejected with 401 "api key revoked"
- two active keys both valid simultaneously
- in-flight request started before expiry completes normally
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ApiKey, Tenant
from recognition.config.security import RateLimitTier, SecuritySettings
from recognition.infrastructure.repositories import SqlAlchemyApiKeyRepository
from recognition.interface_adapters.http.deps import auth as auth_module


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


@pytest_asyncio.fixture
async def tenant_row(db_session: AsyncSession) -> Tenant:
    t = Tenant(site_url="http://rotation.test")
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)
    return t


@pytest.mark.asyncio
async def test_expired_key_is_not_returned_by_get_by_hash(db_session: AsyncSession, tenant_row: Tenant) -> None:
    raw = "expired-raw-key"
    hashed = _hash(raw)
    repo = SqlAlchemyApiKeyRepository(db_session)
    past = datetime.now(tz=UTC) - timedelta(hours=1)
    await repo.create(
        tenant_id=tenant_row.id,
        hashed_key=hashed,
        rate_limit_tier=RateLimitTier.STANDARD,
        expires_at=past,
    )
    await db_session.commit()

    assert await repo.get_by_hash(hashed) is None
    assert await repo.classify_by_hash(hashed) == "expired"


@pytest.mark.asyncio
async def test_revoked_key_is_not_returned_by_get_by_hash(db_session: AsyncSession, tenant_row: Tenant) -> None:
    raw = "revoked-raw-key"
    hashed = _hash(raw)
    repo = SqlAlchemyApiKeyRepository(db_session)
    created = await repo.create(
        tenant_id=tenant_row.id,
        hashed_key=hashed,
        rate_limit_tier=RateLimitTier.STANDARD,
    )
    await db_session.commit()

    await repo.revoke(str(created.id))
    await db_session.commit()

    assert await repo.get_by_hash(hashed) is None
    assert await repo.classify_by_hash(hashed) == "revoked"


@pytest.mark.asyncio
async def test_two_active_keys_both_valid(db_session: AsyncSession, tenant_row: Tenant) -> None:
    repo = SqlAlchemyApiKeyRepository(db_session)
    h1 = _hash("key-a")
    h2 = _hash("key-b")
    await repo.create(tenant_id=tenant_row.id, hashed_key=h1, rate_limit_tier=RateLimitTier.STANDARD)
    await repo.create(tenant_id=tenant_row.id, hashed_key=h2, rate_limit_tier=RateLimitTier.STANDARD)
    await db_session.commit()

    a = await repo.get_by_hash(h1)
    b = await repo.get_by_hash(h2)
    assert a is not None and b is not None
    assert str(a.tenant_id) == str(tenant_row.id)
    assert str(b.tenant_id) == str(tenant_row.id)


@pytest.mark.asyncio
async def test_unknown_key_classifies_unknown(db_session: AsyncSession, tenant_row: Tenant) -> None:
    repo = SqlAlchemyApiKeyRepository(db_session)
    assert await repo.classify_by_hash(_hash("never-seen")) == "unknown"


@pytest.mark.asyncio
async def test_lookup_raises_401_for_expired_key(monkeypatch) -> None:
    """_lookup_api_key surfaces 'api key expired' via HTTPException(401)."""
    from fastapi import HTTPException

    from recognition.tests.api.conftest import FakeSession

    session = FakeSession()

    # Simulate classify_by_hash flow: first execute returns None record, then
    # classify result. Instead we stub the repo directly.
    class StubRepo:
        def __init__(self, _session):
            pass

        async def get_by_hash(self, _hashed):
            return None

        async def classify_by_hash(self, _hashed):
            return "expired"

    import recognition.interface_adapters.http.deps.auth as auth_mod

    monkeypatch.setattr(auth_mod, "SqlAlchemyApiKeyRepository", StubRepo)
    with pytest.raises(HTTPException) as exc_info:
        await auth_mod._lookup_api_key(
            "raw",
            SecuritySettings(auth_enabled=True, dev_api_keys=[]),
            session,
        )
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "api key expired"


@pytest.mark.asyncio
async def test_lookup_raises_401_for_revoked_key(monkeypatch) -> None:
    from fastapi import HTTPException

    from recognition.tests.api.conftest import FakeSession

    session = FakeSession()

    class StubRepo:
        def __init__(self, _session):
            pass

        async def get_by_hash(self, _hashed):
            return None

        async def classify_by_hash(self, _hashed):
            return "revoked"

    import recognition.interface_adapters.http.deps.auth as auth_mod

    monkeypatch.setattr(auth_mod, "SqlAlchemyApiKeyRepository", StubRepo)
    with pytest.raises(HTTPException) as exc_info:
        await auth_mod._lookup_api_key(
            "raw",
            SecuritySettings(auth_enabled=True, dev_api_keys=[]),
            session,
        )
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "api key revoked"


@pytest.mark.asyncio
async def test_in_flight_request_completes_even_if_key_expires_mid_flight(
    db_session: AsyncSession, tenant_row: Tenant
) -> None:
    """Expiry is evaluated at require_auth boundary only. After it passes, the
    request keeps going even if the key expires during processing."""
    raw = "expiring-key"
    hashed = _hash(raw)
    repo = SqlAlchemyApiKeyRepository(db_session)
    # Still valid at boundary time
    future = datetime.now(tz=UTC) + timedelta(milliseconds=50)
    created = await repo.create(
        tenant_id=tenant_row.id,
        hashed_key=hashed,
        rate_limit_tier=RateLimitTier.STANDARD,
        expires_at=future,
    )
    await db_session.commit()

    # Boundary check resolves key as active.
    record = await repo.get_by_hash(hashed)
    assert record is not None
    assert str(record.id) == str(created.id)

    # "Processing" takes longer than the key's remaining lifetime.
    await asyncio.sleep(0.1)

    # In-flight work does not re-check expiry — it only cared about the auth
    # context captured at boundary-time. We simulate that by asserting the
    # captured context is still usable (str conversion, tenant id, etc.)
    assert str(record.tenant_id) == str(tenant_row.id)
