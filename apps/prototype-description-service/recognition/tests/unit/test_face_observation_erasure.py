"""Tenant erasure of append-only FaceObservation rows (CURUX-E1-RET-001)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from db.models import AuditEvent, MediaIdentity, Tenant
from db.models.identity import FaceObservation
from recognition.application.services.purge_service import TenantPurgeService


def _observation(tenant_id, attachment_id: int) -> FaceObservation:
    return FaceObservation(
        id=uuid4(),
        tenant_id=tenant_id,
        identity_namespace_id=uuid4(),
        attachment_id=attachment_id,
        evidence={"source_sha256": f"{attachment_id:064x}"},
    )


def _identity(tenant_id, media_id: int, observation: FaceObservation | None, disposed: bool) -> MediaIdentity:
    return MediaIdentity(
        tenant_id=tenant_id,
        media_id=media_id,
        media_url=f"http://example.test/{media_id}.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=10,
        bbox_height=10,
        confidence=0.9,
        embedding=[1.0] + [0.0] * 511,
        embedding_model="buffalo_l@insightface",
        face_observation_id=observation.id if observation else None,
        disposed_at=datetime.now(tz=UTC) if disposed else None,
    )


async def _seed(db_session, tenant: Tenant) -> dict[str, object]:
    """Tenant A: disposed + live current pointers and one historical row; tenant B: one live pointer."""
    other = Tenant(id=uuid4(), site_url="https://erasure-b.test")
    db_session.add(other)
    await db_session.flush()
    observations = {
        "disposed": _observation(tenant.id, 1),
        "live": _observation(tenant.id, 2),
        "historical": _observation(tenant.id, 1),
        "other": _observation(other.id, 1),
    }
    db_session.add_all(observations.values())
    await db_session.flush()
    db_session.add_all(
        [
            _identity(tenant.id, 1, observations["disposed"], disposed=True),
            _identity(tenant.id, 2, observations["live"], disposed=False),
            _identity(other.id, 1, observations["other"], disposed=True),
        ]
    )
    await db_session.commit()
    return {"other": other, **{key: value.id for key, value in observations.items()}}


async def _observation_ids(db_session) -> set:
    return set((await db_session.execute(select(FaceObservation.id))).scalars().all())


async def _purge(db_session, tenant: Tenant, scope: str) -> dict[str, object]:
    return await TenantPurgeService(db_session).purge_tenant_data(str(tenant.id), "erasure-test", scope=scope)


@pytest.mark.asyncio
async def test_all_scope_erases_current_and_historical_observations_of_tenant_only(db_session, tenant: Tenant) -> None:
    seeded = await _seed(db_session, tenant)

    result = await _purge(db_session, tenant, "all")

    assert result["deleted_counts"]["face_observations"] == 3
    assert await _observation_ids(db_session) == {seeded["other"]}


@pytest.mark.asyncio
async def test_disposed_scope_erases_only_observations_of_disposed_identities(db_session, tenant: Tenant) -> None:
    seeded = await _seed(db_session, tenant)

    result = await _purge(db_session, tenant, "disposed")

    assert result["deleted_counts"]["media_identities"] == 1
    assert result["deleted_counts"]["face_observations"] == 1
    # Live pointer, unattested historical row, and tenant B's disposed pointer survive.
    assert await _observation_ids(db_session) == {seeded["live"], seeded["historical"], seeded["other"]}


@pytest.mark.asyncio
async def test_disposed_scope_without_disposed_identities_erases_no_observations(db_session, tenant: Tenant) -> None:
    observation = _observation(tenant.id, 7)
    db_session.add(observation)
    await db_session.flush()
    db_session.add(_identity(tenant.id, 7, observation, disposed=False))
    await db_session.commit()

    result = await _purge(db_session, tenant, "disposed")

    assert result["deleted_counts"]["face_observations"] == 0
    assert await _observation_ids(db_session) == {observation.id}


@pytest.mark.asyncio
async def test_observation_still_referenced_by_live_identity_is_kept(db_session, tenant: Tenant) -> None:
    shared = _observation(tenant.id, 3)
    db_session.add(shared)
    await db_session.flush()
    db_session.add_all(
        [_identity(tenant.id, 3, shared, disposed=True), _identity(tenant.id, 4, shared, disposed=False)]
    )
    await db_session.commit()

    result = await _purge(db_session, tenant, "disposed")

    assert result["deleted_counts"]["face_observations"] == 0
    assert await _observation_ids(db_session) == {shared.id}


@pytest.mark.asyncio
async def test_tenant_deletion_cascades_to_observations_of_that_tenant_only(db_session, tenant: Tenant) -> None:
    seeded = await _seed(db_session, tenant)

    await db_session.execute(delete(Tenant).where(Tenant.id == tenant.id))
    await db_session.commit()

    assert await _observation_ids(db_session) == {seeded["other"]}


@pytest.mark.asyncio
async def test_ordinary_orm_update_and_delete_remain_rejected(db_session, tenant: Tenant) -> None:
    observation = _observation(tenant.id, 5)
    observation_id = observation.id
    db_session.add(observation)
    await db_session.commit()

    observation.attachment_id = 6
    with pytest.raises(ValueError, match="immutable"):
        await db_session.flush()
    await db_session.rollback()

    await db_session.delete(observation)
    with pytest.raises(ValueError, match="immutable"):
        await db_session.flush()
    await db_session.rollback()
    assert await _observation_ids(db_session) == {observation_id}


@pytest.mark.asyncio
async def test_failed_erasure_records_no_completed_purge(db_session, tenant: Tenant, monkeypatch) -> None:
    tenant_id = tenant.id
    await _seed(db_session, tenant)
    service = TenantPurgeService(db_session)

    async def fail(*_args, **_kwargs):
        raise RuntimeError("erasure failed")

    monkeypatch.setattr(service, "_erase_face_observations", fail)
    with pytest.raises(RuntimeError, match="erasure failed"):
        await service.purge_tenant_data(str(tenant_id), "erasure-test", scope="all")
    await db_session.rollback()

    events = (await db_session.execute(select(AuditEvent.event_type))).scalars().all()
    assert "purge_completed" not in events
    assert (await db_session.get(Tenant, tenant_id)).last_purge_at is None
