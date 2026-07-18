"""Contract and persistence tests for ClusterRepository (Phase 5, TDD first)."""

from __future__ import annotations

import inspect
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Protocol

import numpy as np
import pytest

from db.models import IdentityCluster as IdentityClusterModel
from db.models import IdentityClusterRepresentative as IdentityClusterRepresentativeModel
from db.models import MediaIdentity as MediaIdentityModel
from db.models import Tenant
from recognition.domain.cluster import IdentityCluster
from recognition.domain.identity import MediaIdentity
from recognition.domain.repositories import ClusterRepository, IdentityMember
from recognition.domain.representative import ClusterRepresentative
from recognition.infrastructure.repositories import (
    SqlAlchemyClusterRepository,
    SqlAlchemyMemberRepository,
)


class DummyClusterRepository(ClusterRepository):
    async def get_by_id(self, cluster_id: str) -> IdentityCluster | None:
        raise NotImplementedError

    async def get_by_tenant(
        self,
        tenant_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
        labeled_only: bool = False,
        search: str | None = None,
    ) -> list[IdentityCluster]:
        raise NotImplementedError

    async def save(self, cluster: IdentityCluster) -> IdentityCluster:
        raise NotImplementedError

    async def update(self, cluster: IdentityCluster) -> IdentityCluster:
        raise NotImplementedError

    async def delete(self, cluster_id: str) -> None:
        raise NotImplementedError

    async def get_members(self, cluster_id: str) -> list[IdentityMember]:
        raise NotImplementedError

    async def get_member_identity_count(self, cluster_id: str) -> int:
        raise NotImplementedError

    async def get_member_identities_with_similarity(
        self,
        cluster_id: str,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[tuple[MediaIdentity, float]]:
        raise NotImplementedError

    async def get_member_identities_for_clusters(self, cluster_ids: Sequence[str]) -> dict[str, list[MediaIdentity]]:
        raise NotImplementedError

    async def get_roster_entry_name(self, roster_id: str) -> str | None:
        raise NotImplementedError

    async def get_singleton_identities(self, tenant_id: str, *, limit: int | None = None):
        raise NotImplementedError

    async def get_delta(
        self,
        tenant_id: str,
        *,
        since_version: int,
    ) -> tuple[list[IdentityCluster], list[tuple[IdentityMember, MediaIdentity]], int]:
        raise NotImplementedError

    async def get_curriculum_t(self, cluster_id: str) -> float | None:
        raise NotImplementedError

    async def set_curriculum_t(self, cluster_id: str, value: float) -> None:
        raise NotImplementedError


def test_cluster_repository_is_protocol() -> None:
    """ClusterRepository must be a typing Protocol."""
    assert issubclass(ClusterRepository, Protocol)


def test_cluster_repository_methods_are_async() -> None:
    """All required methods should be async coroutine functions."""
    for method_name in (
        "get_by_id",
        "get_by_tenant",
        "save",
        "update",
        "delete",
        "get_member_identity_count",
        "get_curriculum_t",
        "set_curriculum_t",
        "get_singleton_identities",
    ):
        method = getattr(DummyClusterRepository, method_name)
        assert inspect.iscoroutinefunction(method)


@pytest.mark.asyncio
async def test_save_and_retrieve_cluster(db_session, tenant) -> None:
    """Clusters should round-trip through the repository."""
    repo = SqlAlchemyClusterRepository(db_session)
    cluster = IdentityCluster(
        id=None,
        tenant_id=str(tenant.id),
        label="Person A",
        is_labeled=True,
        identity_count=0,
        created_at=datetime.now(tz=UTC),
    )

    saved = await repo.save(cluster)
    assert saved.id is not None

    fetched = await repo.get_by_id(saved.id)
    assert fetched is not None
    assert fetched.label == "Person A"
    assert fetched.tenant_id == str(tenant.id)
    assert fetched.identity_count == 0


@pytest.mark.asyncio
async def test_get_by_tenant_respects_pagination(db_session, tenant) -> None:
    """get_by_tenant should apply limit/offset ordering by newest first."""
    repo = SqlAlchemyClusterRepository(db_session)
    older = IdentityCluster(
        id=None,
        tenant_id=str(tenant.id),
        label="Older",
        is_labeled=True,
        identity_count=2,
        created_at=datetime.now(tz=UTC) - timedelta(days=1),
    )
    newer = IdentityCluster(
        id=None,
        tenant_id=str(tenant.id),
        label="Newer",
        is_labeled=False,
        identity_count=1,
        created_at=datetime.now(tz=UTC),
    )

    await repo.save(older)
    await repo.save(newer)

    first_page = await repo.get_by_tenant(str(tenant.id), limit=1, offset=0)
    second_page = await repo.get_by_tenant(str(tenant.id), limit=1, offset=1)

    assert [c.label for c in first_page] == ["Newer"]
    assert [c.label for c in second_page] == ["Older"]


@pytest.mark.asyncio
async def test_update_cluster_label(db_session, tenant) -> None:
    """Updates should persist label and labeled status."""
    repo = SqlAlchemyClusterRepository(db_session)
    cluster = IdentityCluster(
        id=None,
        tenant_id=str(tenant.id),
        label=None,
        is_labeled=False,
        identity_count=0,
        created_at=datetime.now(tz=UTC),
    )
    saved = await repo.save(cluster)

    saved.label = "Updated"
    saved.is_labeled = True
    updated = await repo.update(saved)

    assert updated.label == "Updated"
    assert updated.is_labeled is True

    fetched = await repo.get_by_id(updated.id)
    assert fetched is not None
    assert fetched.label == "Updated"
    assert fetched.is_labeled is True


@pytest.mark.asyncio
async def test_get_member_identities_for_clusters_groups_by_cluster(db_session, tenant, seed_media_identity) -> None:
    repo = SqlAlchemyClusterRepository(db_session)
    member_repo = SqlAlchemyMemberRepository(db_session, tenant_id=str(tenant.id))

    cluster_a = await repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="Cluster A",
            is_labeled=False,
            identity_count=2,
            created_at=datetime.now(tz=UTC),
        )
    )
    cluster_b = await repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="Cluster B",
            is_labeled=False,
            identity_count=1,
            created_at=datetime.now(tz=UTC),
        )
    )

    identity_a1 = str(uuid.uuid4())
    identity_a2 = str(uuid.uuid4())
    identity_b1 = str(uuid.uuid4())

    db_session.add(
        MediaIdentityModel(
            id=uuid.UUID(identity_a1),
            tenant_id=tenant.id,
            media_id=9001,
            media_url="http://example.test/a1.jpg",
            bbox_x=0,
            bbox_y=0,
            bbox_width=100,
            bbox_height=120,
            confidence=0.9,
            embedding=[0.1] * 512,
            embedding_model="buffalo_l@insightface",
            pose_pitch=25.0,
            pose_yaw=-30.0,
            pose_roll=-20.0,
        )
    )
    await db_session.flush()

    await seed_media_identity(identity_a2)
    await seed_media_identity(identity_b1)

    await member_repo.add_member(cluster_a.id, identity_id=identity_a1, similarity=0.91)
    await member_repo.add_member(cluster_a.id, identity_id=identity_a2, similarity=0.92)
    await member_repo.add_member(cluster_b.id, identity_id=identity_b1, similarity=0.93)

    grouped = await repo.get_member_identities_for_clusters([cluster_a.id, cluster_b.id])

    assert set(grouped.keys()) == {cluster_a.id, cluster_b.id}
    assert {identity.id for identity in grouped[cluster_a.id]} == {identity_a1, identity_a2}
    assert {identity.id for identity in grouped[cluster_b.id]} == {identity_b1}
    assert all(identity.cluster_id == cluster_a.id for identity in grouped[cluster_a.id])
    assert all(identity.cluster_id == cluster_b.id for identity in grouped[cluster_b.id])

    identity_a1_domain = next(identity for identity in grouped[cluster_a.id] if identity.id == identity_a1)
    assert identity_a1_domain.pose_pitch == pytest.approx(25.0)
    assert identity_a1_domain.pose_yaw == pytest.approx(-30.0)
    assert identity_a1_domain.pose_roll == pytest.approx(-20.0)


@pytest.mark.asyncio
async def test_get_member_identities_with_similarity_can_count_and_limit(
    db_session, tenant, seed_media_identity
) -> None:
    repo = SqlAlchemyClusterRepository(db_session)
    member_repo = SqlAlchemyMemberRepository(db_session, tenant_id=str(tenant.id))

    cluster = await repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="Limited members",
            is_labeled=False,
            identity_count=3,
            created_at=datetime.now(tz=UTC),
        )
    )
    identity_ids = [str(uuid.uuid4()) for _ in range(3)]
    for identity_id in identity_ids:
        await seed_media_identity(identity_id)
    for index, identity_id in enumerate(identity_ids):
        await member_repo.add_member(cluster.id, identity_id=identity_id, similarity=0.9 + index * 0.01)

    assert await repo.get_member_identity_count(cluster.id) == 3

    all_members = await repo.get_member_identities_with_similarity(cluster.id)
    assert len(all_members) == 3
    ordered_ids = [str(identity.id) for identity, _similarity in all_members]

    limited = await repo.get_member_identities_with_similarity(cluster.id, limit=2)
    assert len(limited) == 2
    assert [str(identity.id) for identity, _similarity in limited] == ordered_ids[:2]
    assert {round(similarity, 2) for _identity, similarity in limited}.issubset({0.9, 0.91, 0.92})

    paged = await repo.get_member_identities_with_similarity(cluster.id, limit=1, offset=1)
    assert len(paged) == 1
    assert str(paged[0][0].id) == ordered_ids[1]

    tail = await repo.get_member_identities_with_similarity(cluster.id, limit=2, offset=2)
    assert len(tail) == 1
    assert str(tail[0][0].id) == ordered_ids[2]


@pytest.mark.asyncio
async def test_curriculum_bias_round_trip(db_session, tenant) -> None:
    repo = SqlAlchemyClusterRepository(db_session)
    cluster = IdentityCluster(
        id=None,
        tenant_id=str(tenant.id),
        label="Bias Cluster",
        is_labeled=True,
        identity_count=0,
        created_at=datetime.now(tz=UTC),
    )

    saved = await repo.save(cluster)
    assert await repo.get_curriculum_t(saved.id) == 0.0

    await repo.set_curriculum_t(saved.id, 0.42)
    assert await repo.get_curriculum_t(saved.id) == pytest.approx(0.42, abs=0.0001)


@pytest.mark.asyncio
async def test_get_snapshot_stamps_generation_id_and_excludes_disposed_rows(db_session, tenant: Tenant) -> None:
    repo = SqlAlchemyClusterRepository(db_session)
    member_repo = SqlAlchemyMemberRepository(db_session, tenant_id=str(tenant.id))

    active_cluster = await repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="Active",
            is_labeled=True,
            identity_count=1,
            created_at=datetime.now(tz=UTC),
        )
    )
    disposed_cluster = await repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="Disposed",
            is_labeled=True,
            identity_count=1,
            created_at=datetime.now(tz=UTC),
        )
    )

    active_identity_id = str(uuid.uuid4())
    disposed_identity_id = str(uuid.uuid4())
    active_identity_uuid = uuid.UUID(active_identity_id)
    disposed_identity_uuid = uuid.UUID(disposed_identity_id)

    db_session.add_all(
        [
            MediaIdentityModel(
                id=active_identity_uuid,
                tenant_id=tenant.id,
                media_id=111,
                media_url="http://example.test/active.jpg",
                bbox_x=0,
                bbox_y=0,
                bbox_width=10,
                bbox_height=10,
                confidence=0.9,
                embedding=[0.1] * 512,
                embedding_model="buffalo_l@insightface",
            ),
            MediaIdentityModel(
                id=disposed_identity_uuid,
                tenant_id=tenant.id,
                media_id=222,
                media_url="http://example.test/disposed.jpg",
                bbox_x=0,
                bbox_y=0,
                bbox_width=10,
                bbox_height=10,
                confidence=0.9,
                embedding=[0.2] * 512,
                embedding_model="buffalo_l@insightface",
                disposed_at=datetime.now(tz=UTC),
            ),
        ]
    )
    await db_session.flush()

    await member_repo.add_member(active_cluster.id, identity_id=active_identity_id, similarity=0.95)
    await member_repo.add_member(disposed_cluster.id, identity_id=disposed_identity_id, similarity=0.85)
    await db_session.flush()

    active_rep = IdentityClusterRepresentativeModel(
        tenant_id=tenant.id,
        cluster_id=uuid.UUID(active_cluster.id),
        identity_id=active_identity_uuid,
        embedding=[0.1] * 512,
        quality_score=0.95,
    )
    disposed_rep = IdentityClusterRepresentativeModel(
        tenant_id=tenant.id,
        cluster_id=uuid.UUID(disposed_cluster.id),
        identity_id=disposed_identity_uuid,
        embedding=[0.2] * 512,
        quality_score=0.85,
        disposed_at=datetime.now(tz=UTC),
    )
    db_session.add_all([active_rep, disposed_rep])
    await db_session.flush()

    disposed_cluster_model = await db_session.get(IdentityClusterModel, uuid.UUID(disposed_cluster.id))
    assert disposed_cluster_model is not None
    disposed_cluster_model.disposed_at = datetime.now(tz=UTC)
    await db_session.commit()

    clusters, members, _snapshot_version, snapshot_generation_id = await repo.get_snapshot(
        str(tenant.id),
        stamp_export=True,
    )

    assert snapshot_generation_id is not None
    assert uuid.UUID(snapshot_generation_id)
    assert [cluster.id for cluster in clusters] == [active_cluster.id]
    assert [member.identity_id for member, _identity in members] == [active_identity_id]

    refreshed_active_cluster = await db_session.get(IdentityClusterModel, uuid.UUID(active_cluster.id))
    refreshed_active_identity = await db_session.get(MediaIdentityModel, active_identity_uuid)
    refreshed_active_rep = await db_session.get(IdentityClusterRepresentativeModel, active_rep.id)
    refreshed_disposed_identity = await db_session.get(MediaIdentityModel, disposed_identity_uuid)
    refreshed_disposed_cluster = await db_session.get(IdentityClusterModel, uuid.UUID(disposed_cluster.id))

    assert refreshed_active_cluster is not None
    assert refreshed_active_identity is not None
    assert refreshed_active_rep is not None
    assert str(refreshed_active_cluster.last_exported_snapshot_id) == snapshot_generation_id
    assert str(refreshed_active_identity.last_exported_snapshot_id) == snapshot_generation_id
    assert str(refreshed_active_rep.last_exported_snapshot_id) == snapshot_generation_id
    assert refreshed_disposed_identity is not None
    assert refreshed_disposed_cluster is not None
    assert refreshed_disposed_identity.last_exported_snapshot_id is None
    assert refreshed_disposed_cluster.last_exported_snapshot_id is None


@pytest.mark.asyncio
async def test_delete_cascades_members(db_session, tenant, seed_media_identity) -> None:
    """Deleting a cluster should remove associated members."""
    cluster_repo = SqlAlchemyClusterRepository(db_session)
    member_repo = SqlAlchemyMemberRepository(db_session, tenant_id=str(tenant.id))
    cluster = IdentityCluster(
        id=None,
        tenant_id=str(tenant.id),
        label="With members",
        is_labeled=True,
        identity_count=1,
        created_at=datetime.now(tz=UTC),
    )
    saved_cluster = await cluster_repo.save(cluster)
    member_identity_id = str(uuid.uuid4())
    await seed_media_identity(member_identity_id)
    await member_repo.add_member(saved_cluster.id, identity_id=member_identity_id, similarity=0.92)

    await cluster_repo.delete(saved_cluster.id)
    members = await member_repo.get_by_cluster(saved_cluster.id)

    assert members == []


@pytest.mark.asyncio
async def test_get_by_tenant_filters_other_tenants(db_session, tenant) -> None:
    """Clusters from other tenants should not be returned."""
    repo = SqlAlchemyClusterRepository(db_session)

    other_tenant = Tenant(site_url="http://other.test")
    db_session.add(other_tenant)
    await db_session.commit()
    await db_session.refresh(other_tenant)

    # Cluster for current tenant
    await repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="Mine",
            is_labeled=False,
            identity_count=0,
            created_at=datetime.now(tz=UTC),
        )
    )
    # Cluster for other tenant
    await repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(other_tenant.id),
            label="Theirs",
            is_labeled=False,
            identity_count=0,
            created_at=datetime.now(tz=UTC),
        )
    )

    clusters = await repo.get_by_tenant(str(tenant.id), limit=10, offset=0)

    assert [c.label for c in clusters] == ["Mine"]


@pytest.mark.asyncio
async def test_clear_representatives_removes_all(db_session, tenant, seed_media_identity) -> None:
    """clear_representatives should remove all representative rows for the cluster."""
    cluster_repo = SqlAlchemyClusterRepository(db_session)
    member_repo = SqlAlchemyMemberRepository(db_session, tenant_id=str(tenant.id))

    cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="With reps",
            is_labeled=False,
            identity_count=1,
            created_at=datetime.now(tz=UTC),
        )
    )
    identity_id = str(uuid.uuid4())
    await seed_media_identity(identity_id)
    await member_repo.add_member(cluster.id, identity_id=identity_id, similarity=0.92)

    rep = ClusterRepresentative(
        id=str(uuid.uuid4()),
        cluster_id=cluster.id,
        identity_id=identity_id,
        embedding=np.ones(512, dtype=np.float32),
        created_at=datetime.now(tz=UTC),
        tenant_id=str(tenant.id),
    )
    await cluster_repo.add_representative(rep)
    assert await cluster_repo.get_representative_count(cluster.id) == 1

    await cluster_repo.clear_representatives(cluster.id)
    assert await cluster_repo.get_representative_count(cluster.id) == 0
