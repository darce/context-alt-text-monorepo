"""Persistence regressions for cluster freshness timestamps."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update

from db.models import ClusterCentroid
from db.models import IdentityCluster as ClusterModel
from recognition.application.suggestions import merge_candidates as merge_candidates_module
from recognition.domain.cluster import IdentityCluster
from recognition.domain.repositories import MemberData
from recognition.infrastructure.repositories.cluster_repository import SqlAlchemyClusterRepository
from recognition.infrastructure.repositories.member_repository import SqlAlchemyMemberRepository

_BASELINE = datetime(2020, 1, 1, tzinfo=UTC)


async def _new_cluster(db_session, tenant_id: str, *, label: str | None = None) -> str:
    cluster_repository = SqlAlchemyClusterRepository(db_session)
    cluster = await cluster_repository.save(
        IdentityCluster(
            id=None,
            tenant_id=tenant_id,
            label=label,
            is_labeled=bool(label),
            identity_count=0,
            created_at=_BASELINE,
        )
    )
    await db_session.execute(
        update(ClusterModel).where(ClusterModel.id == UUID(cluster.id)).values(updated_at=_BASELINE)
    )
    await db_session.flush()
    return str(cluster.id)


async def _updated_at(db_session, cluster_id: str) -> datetime:
    result = await db_session.execute(select(ClusterModel.updated_at).where(ClusterModel.id == UUID(cluster_id)))
    return result.scalar_one()


@pytest.mark.asyncio
async def test_add_member_advances_cluster_updated_at(db_session, tenant, seed_media_identity) -> None:
    cluster_id = await _new_cluster(db_session, str(tenant.id))
    identity_id = str(uuid4())
    await seed_media_identity(identity_id)
    member_repository = SqlAlchemyMemberRepository(db_session, tenant_id=str(tenant.id))

    before = await _updated_at(db_session, cluster_id)
    await member_repository.add_member(cluster_id, identity_id, similarity=0.8)

    assert await _updated_at(db_session, cluster_id) > before


@pytest.mark.asyncio
async def test_add_member_if_not_exists_advances_cluster_updated_at(db_session, tenant, seed_media_identity) -> None:
    cluster_id = await _new_cluster(db_session, str(tenant.id))
    identity_id = str(uuid4())
    await seed_media_identity(identity_id)
    member_repository = SqlAlchemyMemberRepository(db_session, tenant_id=str(tenant.id))

    before = await _updated_at(db_session, cluster_id)
    created = await member_repository.add_member_if_not_exists(cluster_id, identity_id, similarity=0.8)

    assert created is not None
    assert await _updated_at(db_session, cluster_id) > before


@pytest.mark.asyncio
async def test_bulk_add_members_advances_cluster_updated_at(db_session, tenant, seed_media_identity) -> None:
    cluster_id = await _new_cluster(db_session, str(tenant.id))
    members = [MemberData(identity_id=str(uuid4()), similarity=0.8), MemberData(identity_id=str(uuid4()), similarity=0.9)]
    for member in members:
        await seed_media_identity(member.identity_id)
    member_repository = SqlAlchemyMemberRepository(db_session, tenant_id=str(tenant.id))

    before = await _updated_at(db_session, cluster_id)
    created = await member_repository.bulk_add_members(cluster_id, members)

    assert len(created) == len(members)
    assert await _updated_at(db_session, cluster_id) > before


@pytest.mark.asyncio
async def test_bulk_add_members_if_not_exists_advances_cluster_updated_at(db_session, tenant, seed_media_identity) -> None:
    cluster_id = await _new_cluster(db_session, str(tenant.id))
    members = [MemberData(identity_id=str(uuid4()), similarity=0.8), MemberData(identity_id=str(uuid4()), similarity=0.9)]
    for member in members:
        await seed_media_identity(member.identity_id)
    member_repository = SqlAlchemyMemberRepository(db_session, tenant_id=str(tenant.id))

    before = await _updated_at(db_session, cluster_id)
    created, skipped = await member_repository.bulk_add_members_if_not_exists(cluster_id, members)

    assert len(created) == len(members)
    assert skipped == 0
    assert await _updated_at(db_session, cluster_id) > before


@pytest.mark.asyncio
async def test_move_members_advances_source_and_destination_updated_at(db_session, tenant, seed_media_identity) -> None:
    source_id = await _new_cluster(db_session, str(tenant.id), label="source")
    target_id = await _new_cluster(db_session, str(tenant.id), label="target")
    identity_id = str(uuid4())
    await seed_media_identity(identity_id)
    member_repository = SqlAlchemyMemberRepository(db_session, tenant_id=str(tenant.id))
    await member_repository.add_member(source_id, identity_id, similarity=0.8)
    await db_session.execute(
        update(ClusterModel)
        .where(ClusterModel.id.in_([UUID(source_id), UUID(target_id)]))
        .values(updated_at=_BASELINE)
    )
    await db_session.flush()

    source_before = await _updated_at(db_session, source_id)
    target_before = await _updated_at(db_session, target_id)
    assert await member_repository.move_members(source_id, target_id) == 1

    assert await _updated_at(db_session, source_id) > source_before
    assert await _updated_at(db_session, target_id) > target_before


@pytest.mark.asyncio
async def test_remove_member_advances_cluster_updated_at(db_session, tenant, seed_media_identity) -> None:
    cluster_id = await _new_cluster(db_session, str(tenant.id))
    identity_id = str(uuid4())
    await seed_media_identity(identity_id)
    member_repository = SqlAlchemyMemberRepository(db_session, tenant_id=str(tenant.id))
    member = await member_repository.add_member(cluster_id, identity_id, similarity=0.8)
    await db_session.execute(
        update(ClusterModel).where(ClusterModel.id == UUID(cluster_id)).values(updated_at=_BASELINE)
    )
    await db_session.flush()

    before = await _updated_at(db_session, cluster_id)
    await member_repository.remove_member(member.id)

    assert await _updated_at(db_session, cluster_id) > before


@pytest.mark.asyncio
async def test_remove_by_identity_id_advances_cluster_updated_at(db_session, tenant, seed_media_identity) -> None:
    cluster_id = await _new_cluster(db_session, str(tenant.id))
    identity_id = str(uuid4())
    await seed_media_identity(identity_id)
    member_repository = SqlAlchemyMemberRepository(db_session, tenant_id=str(tenant.id))
    await member_repository.add_member(cluster_id, identity_id, similarity=0.8)
    await db_session.execute(
        update(ClusterModel).where(ClusterModel.id == UUID(cluster_id)).values(updated_at=_BASELINE)
    )
    await db_session.flush()

    before = await _updated_at(db_session, cluster_id)
    assert await member_repository.remove_by_identity_id(identity_id) is True

    assert await _updated_at(db_session, cluster_id) > before


@pytest.mark.asyncio
async def test_cluster_conversion_carries_centroid_refresh_into_freshness(db_session, tenant) -> None:
    created = datetime(2026, 1, 1, tzinfo=UTC)
    updated = datetime(2026, 2, 1, tzinfo=UTC)
    centroid_refreshed = datetime(2026, 6, 1, tzinfo=UTC)
    cluster_repository = SqlAlchemyClusterRepository(db_session)
    saved = await cluster_repository.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="centroid",
            is_labeled=True,
            identity_count=0,
            created_at=created,
        )
    )
    model = await db_session.get(ClusterModel, UUID(saved.id))
    assert model is not None
    model.updated_at = updated
    model.centroid_data = ClusterCentroid(
        cluster_id=model.id,
        tenant_id=model.tenant_id,
        centroid=[1.0, 0.0],
        refreshed_at=centroid_refreshed,
    )

    domain = cluster_repository._to_domain(model)
    other = IdentityCluster(
        id=str(uuid4()),
        tenant_id=str(tenant.id),
        is_labeled=False,
        identity_count=0,
        created_at=created,
    )

    assert domain.centroid_refreshed_at == centroid_refreshed
    assert merge_candidates_module._latest_mutation(domain, other) == centroid_refreshed
