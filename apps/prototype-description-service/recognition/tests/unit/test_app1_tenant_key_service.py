"""APP-1 tenant API-key lifecycle tests."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import Table, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.base import Base
from db.models import ApiKey, ApiKeyRotationHistory, Tenant, TenantKeyIdempotency
from recognition.application.services.tenant_key_service import (
    IdempotencyKeyReuseError,
    KeyAlreadyRevokedError,
    KeyAlreadyRotatedError,
    TenantKeyService,
)
from recognition.infrastructure.repositories.api_key_repository import SqlAlchemyApiKeyRepository

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _as_utc(dt: datetime) -> datetime:
    """The SQLite test substrate returns naive datetimes; PostgreSQL returns aware ones."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


@pytest_asyncio.fixture(autouse=True)
async def key_lifecycle_tables(db_session: AsyncSession) -> None:
    """Add the portal foundation tables omitted by the broad recognition fixture."""
    connection = await db_session.connection()
    tables = [
        Table("api_key_rotation_history", Base.metadata),
        Table("tenant_key_idempotency", Base.metadata),
    ]
    await connection.run_sync(lambda sync_connection: Base.metadata.create_all(sync_connection, tables=tables))


def _service(session: AsyncSession, tokens: list[str]) -> TenantKeyService:
    remaining = iter(tokens)
    return TenantKeyService(
        session,
        now=lambda: NOW,
        token_factory=lambda: next(remaining),
    )


def _service_with_advancing_clock(session: AsyncSession, tokens: list[str]) -> TenantKeyService:
    remaining = iter(tokens)
    seconds = iter(range(100))
    return TenantKeyService(
        session,
        now=lambda: NOW + timedelta(seconds=next(seconds)),
        token_factory=lambda: next(remaining),
    )


@pytest.mark.asyncio
async def test_create_returns_secret_once_and_rejects_fingerprint_reuse(
    db_session: AsyncSession,
    tenant: Tenant,
) -> None:
    service = _service(db_session, ["first-secret"])

    first = await service.create_key(
        tenant.id,
        idempotency_key="create-1",
        lifetime_seconds=3600,
        rate_limit_tier="standard",
    )
    replay = await service.create_key(
        tenant.id,
        idempotency_key=" create-1 ",
        lifetime_seconds=3600,
        rate_limit_tier="standard",
    )

    assert first.raw_key == "first-secret"
    assert first.replayed is False
    assert replay.raw_key is None
    assert replay.replayed is True
    assert replay.api_key_id == first.api_key_id
    assert replay.tenant_id == tenant.id

    with pytest.raises(IdempotencyKeyReuseError):
        await service.create_key(tenant.id, idempotency_key="create-1", lifetime_seconds=7200)

    key_count = await db_session.scalar(select(func.count(ApiKey.id)).where(ApiKey.tenant_id == tenant.id))
    reservation_count = await db_session.scalar(
        select(func.count(TenantKeyIdempotency.id)).where(TenantKeyIdempotency.tenant_id == tenant.id)
    )
    assert key_count == 1
    assert reservation_count == 1


@pytest.mark.asyncio
async def test_rotation_shortens_old_key_and_preserves_original_lifetime(
    db_session: AsyncSession,
    tenant: Tenant,
) -> None:
    lifetime = 30 * 24 * 60 * 60
    service = _service(db_session, ["first-secret", "replacement-secret", "recovery-secret"])
    first = await service.create_key(tenant.id, idempotency_key="create", lifetime_seconds=lifetime)

    replacement = await service.rotate_key(
        tenant.id,
        first.api_key_id,
        idempotency_key="rotate-1",
        reason="routine",
    )
    old = await SqlAlchemyApiKeyRepository(db_session).get_by_id(first.api_key_id, tenant_id=tenant.id)
    replacement_row = await SqlAlchemyApiKeyRepository(db_session).get_by_id(
        replacement.api_key_id,
        tenant_id=tenant.id,
    )
    history_count = await db_session.scalar(
        select(func.count(ApiKeyRotationHistory.id)).where(ApiKeyRotationHistory.tenant_id == tenant.id)
    )

    assert old is not None
    assert old.revoked_at is None
    assert old.expires_at is not None
    assert _as_utc(old.expires_at) <= NOW + timedelta(days=7)
    assert replacement_row is not None
    assert replacement_row.lifetime_seconds == lifetime
    assert replacement_row.expires_at is not None
    assert _as_utc(replacement_row.expires_at) >= NOW + timedelta(seconds=lifetime)
    assert history_count == 1

    with pytest.raises(KeyAlreadyRotatedError):
        await service.rotate_key(
            tenant.id,
            first.api_key_id,
            idempotency_key="rotate-1-again",
            reason="routine",
        )

    recovered = await service.rotate_key(
        tenant.id,
        replacement.api_key_id,
        idempotency_key="rotate-recovery",
        reason="recovery",
    )
    predecessor = await SqlAlchemyApiKeyRepository(db_session).get_by_id(first.api_key_id, tenant_id=tenant.id)
    current = await SqlAlchemyApiKeyRepository(db_session).get_by_id(replacement.api_key_id, tenant_id=tenant.id)
    usable = await SqlAlchemyApiKeyRepository(db_session).usable_for_tenant(tenant.id, now=NOW)

    assert recovered.lifetime_seconds == lifetime
    assert predecessor is not None and predecessor.revoked_at is not None
    assert current is not None and current.revoked_at is None
    assert len(usable) == 2


@pytest.mark.asyncio
async def test_new_primary_can_rotate_after_all_keys_in_previous_history_are_revoked(
    db_session: AsyncSession,
    tenant: Tenant,
) -> None:
    lifetime = 30 * 24 * 60 * 60
    service = _service_with_advancing_clock(
        db_session,
        ["secret-k1", "secret-k2", "secret-k3", "secret-k4"],
    )

    k1 = await service.create_key(tenant.id, idempotency_key="c1", lifetime_seconds=lifetime)
    k2 = await service.rotate_key(tenant.id, k1.api_key_id, idempotency_key="r1", reason="routine")
    await service.revoke_key(tenant.id, k1.api_key_id, reason="emergency")
    await service.revoke_key(tenant.id, k2.api_key_id, reason="emergency")
    k3 = await service.create_key(tenant.id, idempotency_key="c3", lifetime_seconds=lifetime)

    repository = SqlAlchemyApiKeyRepository(db_session)
    usable_before_rotation = await repository.usable_for_tenant(
        tenant.id,
        now=NOW + timedelta(seconds=5),
    )
    latest_replacement = await repository.latest_replacement_for_tenant(tenant.id)
    k3_history = await repository.get_rotation_history(tenant.id, k3.api_key_id)

    assert {key.id for key in usable_before_rotation} == {k3.api_key_id}
    assert latest_replacement == k2.api_key_id
    assert k3_history is None
    assert await db_session.scalar(select(func.count(ApiKey.id)).where(ApiKey.tenant_id == tenant.id)) == 3
    assert (
        await db_session.scalar(
            select(func.count(ApiKeyRotationHistory.id)).where(ApiKeyRotationHistory.tenant_id == tenant.id)
        )
        == 1
    )
    assert (
        await db_session.scalar(
            select(func.count(TenantKeyIdempotency.id)).where(TenantKeyIdempotency.tenant_id == tenant.id)
        )
        == 3
    )

    # This public rotation should succeed for the sole usable primary. On the
    # reviewed baseline, retained K1→K2 history instead rejects K3 here.
    k4 = await service.rotate_key(tenant.id, k3.api_key_id, idempotency_key="r3", reason="recovery")
    k4_replay = await service.rotate_key(tenant.id, k3.api_key_id, idempotency_key="r3", reason="recovery")

    k3_row = await repository.get_by_id(k3.api_key_id, tenant_id=tenant.id)
    k4_row = await repository.get_by_id(k4.api_key_id, tenant_id=tenant.id)
    k3_rotation = await repository.get_rotation_history(tenant.id, k3.api_key_id)
    usable_after_rotation = await repository.usable_for_tenant(
        tenant.id,
        now=NOW + timedelta(seconds=5),
    )

    assert k4.raw_key == "secret-k4"
    assert k4.replayed is False
    assert k4_replay.api_key_id == k4.api_key_id
    assert k4_replay.raw_key is None
    assert k4_replay.replayed is True
    assert k3_row is not None and k3_row.expires_at is not None
    assert _as_utc(k3_row.expires_at) == NOW + timedelta(seconds=5, days=7)
    assert k4_row is not None
    assert k4_row.lifetime_seconds == lifetime
    assert k4_row.expires_at is not None
    assert _as_utc(k4_row.expires_at) == NOW + timedelta(seconds=5 + lifetime)
    assert k3_rotation is not None and k3_rotation.replaced_by_key_id == k4.api_key_id
    assert {key.id for key in usable_after_rotation} == {k3.api_key_id, k4.api_key_id}


@pytest.mark.asyncio
async def test_fresh_create_after_revoke_rotates_without_history_and_replays_metadata(
    db_session: AsyncSession,
    tenant: Tenant,
) -> None:
    lifetime = 30 * 24 * 60 * 60
    service = _service_with_advancing_clock(db_session, ["secret-k1", "secret-k2", "secret-k3"])
    k1 = await service.create_key(tenant.id, idempotency_key="c1", lifetime_seconds=lifetime)
    await service.revoke_key(tenant.id, k1.api_key_id, reason="emergency")

    replay_service = _service_with_advancing_clock(db_session, [])
    revoked_create_replay = await replay_service.create_key(
        tenant.id,
        idempotency_key="c1",
        lifetime_seconds=lifetime,
    )
    assert revoked_create_replay.api_key_id == k1.api_key_id
    assert revoked_create_replay.raw_key is None
    assert revoked_create_replay.replayed is True
    with pytest.raises(IdempotencyKeyReuseError):
        await replay_service.create_key(tenant.id, idempotency_key="c1", lifetime_seconds=lifetime + 1)

    k2 = await service.create_key(tenant.id, idempotency_key="c2", lifetime_seconds=lifetime)
    repository = SqlAlchemyApiKeyRepository(db_session)
    assert k2.api_key_id != k1.api_key_id
    assert k2.raw_key == "secret-k2"
    assert await repository.latest_replacement_for_tenant(tenant.id) is None
    assert await repository.get_rotation_history(tenant.id, k2.api_key_id) is None

    k3 = await service.rotate_key(tenant.id, k2.api_key_id, idempotency_key="r2", reason="routine")
    assert k3.raw_key == "secret-k3"
    assert k3.api_key_id != k2.api_key_id
    assert await repository.latest_replacement_for_tenant(tenant.id) == k3.api_key_id

    await service.revoke_key(tenant.id, k2.api_key_id, reason="emergency")
    await service.revoke_key(tenant.id, k3.api_key_id, reason="emergency")

    revoked_fresh_create_replay = await replay_service.create_key(
        tenant.id,
        idempotency_key="c2",
        lifetime_seconds=lifetime,
    )
    revoked_rotation_replay = await replay_service.rotate_key(
        tenant.id,
        k2.api_key_id,
        idempotency_key="r2",
        reason="routine",
    )
    assert revoked_fresh_create_replay.api_key_id == k2.api_key_id
    assert revoked_fresh_create_replay.raw_key is None
    assert revoked_fresh_create_replay.replayed is True
    assert revoked_rotation_replay.api_key_id == k3.api_key_id
    assert revoked_rotation_replay.raw_key is None
    assert revoked_rotation_replay.replayed is True
    with pytest.raises(IdempotencyKeyReuseError):
        await replay_service.rotate_key(
            tenant.id,
            k2.api_key_id,
            idempotency_key="r2",
            reason="changed-reason",
        )


@pytest.mark.asyncio
async def test_rotation_recovers_legacy_finite_lifetime_from_absolute_expiry(
    db_session: AsyncSession,
    tenant: Tenant,
) -> None:
    original_lifetime = 31 * 24 * 60 * 60
    legacy = ApiKey(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        api_key_hash=hashlib.sha256(b"legacy-secret").hexdigest(),
        created_at=NOW - timedelta(days=30),
        expires_at=NOW + timedelta(days=1),
        lifetime_seconds=None,
    )
    db_session.add(legacy)
    await db_session.flush()

    replacement = await _service(db_session, ["replacement-secret"]).rotate_key(
        tenant.id,
        legacy.id,
        idempotency_key="rotate-legacy",
        reason="routine",
    )
    replacement_row = await SqlAlchemyApiKeyRepository(db_session).get_by_id(
        replacement.api_key_id,
        tenant_id=tenant.id,
    )

    assert replacement_row is not None
    assert replacement_row.lifetime_seconds == original_lifetime
    assert replacement_row.expires_at is not None
    assert _as_utc(replacement_row.expires_at) == NOW + timedelta(seconds=original_lifetime)


@pytest.mark.asyncio
async def test_rotation_keeps_unlimited_legacy_key_unlimited(
    db_session: AsyncSession,
    tenant: Tenant,
) -> None:
    legacy = ApiKey(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        api_key_hash=hashlib.sha256(b"unlimited-legacy-secret").hexdigest(),
        created_at=NOW,
        expires_at=None,
        lifetime_seconds=None,
    )
    db_session.add(legacy)
    await db_session.flush()

    replacement = await _service(db_session, ["replacement-secret"]).rotate_key(
        tenant.id,
        legacy.id,
        idempotency_key="rotate-unlimited",
        reason="routine",
    )
    replacement_row = await SqlAlchemyApiKeyRepository(db_session).get_by_id(
        replacement.api_key_id,
        tenant_id=tenant.id,
    )

    assert replacement_row is not None
    assert replacement_row.lifetime_seconds is None
    assert replacement_row.expires_at is None


@pytest.mark.asyncio
async def test_revoke_is_immediate_and_repeated_portal_revoke_is_refused(
    db_session: AsyncSession,
    tenant: Tenant,
) -> None:
    service = _service(db_session, ["secret"])
    result = await service.create_key(tenant.id, idempotency_key="create")

    await service.revoke_key(tenant.id, result.api_key_id, reason="emergency")
    with pytest.raises(KeyAlreadyRevokedError):
        await service.revoke_key(tenant.id, result.api_key_id, reason="emergency-again")

    row = await SqlAlchemyApiKeyRepository(db_session).get_by_id(result.api_key_id, tenant_id=tenant.id)
    assert row is not None
    assert _as_utc(row.revoked_at) == NOW


@pytest.mark.asyncio
async def test_list_caps_at_100_and_never_exposes_hash_or_secret(
    db_session: AsyncSession,
    tenant: Tenant,
) -> None:
    for index in range(105):
        db_session.add(
            ApiKey(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                api_key_hash=hashlib.sha256(f"secret-{index}".encode()).hexdigest(),
                created_at=NOW + timedelta(seconds=index),
                lifetime_seconds=None,
            )
        )
    await db_session.flush()

    service = TenantKeyService(db_session, now=lambda: NOW)
    page = await service.list_keys(tenant.id, limit=100)
    next_page = await service.list_keys(tenant.id, cursor=page.next_cursor, limit=100)

    assert page.limit == 100
    assert len(page.data) == 100
    assert page.total == 105
    assert page.next_cursor is not None
    assert len(next_page.data) == 5
    assert next_page.total == 105
    assert all(item.raw_key is None for item in page.data + next_page.data)
    assert all(not hasattr(item, "api_key_hash") for item in page.data + next_page.data)
