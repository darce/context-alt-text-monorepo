"""Integration tests for top-unlabeled cluster repository queries."""

import uuid
from datetime import UTC, datetime

import numpy as np
import pytest

from db.models.constraints import IdentitySuggestion
from recognition.domain.cluster import IdentityCluster
from recognition.domain.representative import ClusterRepresentative
from recognition.infrastructure.repositories import SqlAlchemyClusterRepository, SqlAlchemyMemberRepository


@pytest.mark.asyncio
async def test_get_top_unlabeled_size_priority_tenant_wide(db_session, tenant) -> None:
    """get_top_unlabeled should prioritize largest eligible clusters tenant-wide."""
    repo = SqlAlchemyClusterRepository(db_session)
    tenant_id = str(tenant.id)

    # Eligible unlabeled cluster (size 5).
    cluster_a = await repo.save(
        IdentityCluster(
            id=None,
            tenant_id=tenant_id,
            label=None,
            is_labeled=False,
            identity_count=5,
            created_at=datetime.now(tz=UTC),
            user_confirmed=False,
        )
    )
    # Eligible unlabeled cluster (size 3).
    cluster_b = await repo.save(
        IdentityCluster(
            id=None,
            tenant_id=tenant_id,
            label=None,
            is_labeled=False,
            identity_count=3,
            created_at=datetime.now(tz=UTC),
            user_confirmed=False,
        )
    )
    # Singleton should be filtered.
    cluster_c = await repo.save(
        IdentityCluster(
            id=None,
            tenant_id=tenant_id,
            label=None,
            is_labeled=False,
            identity_count=1,
            created_at=datetime.now(tz=UTC),
            user_confirmed=False,
        )
    )
    # User-labeled cluster should be filtered.
    cluster_d = await repo.save(
        IdentityCluster(
            id=None,
            tenant_id=tenant_id,
            label="Labeled",
            is_labeled=True,
            identity_count=4,
            created_at=datetime.now(tz=UTC),
            user_confirmed=False,
        )
    )
    # Auto-labeled cluster should be included as unlabeled.
    cluster_e = await repo.save(
        IdentityCluster(
            id=None,
            tenant_id=tenant_id,
            label="cluster-auto",
            is_labeled=False,
            identity_count=4,
            created_at=datetime.now(tz=UTC),
            user_confirmed=False,
        )
    )

    await db_session.commit()

    # Should prioritize by identity_count DESC across all eligible tenant clusters.
    results = await repo.get_top_unlabeled(tenant_id, limit=10)

    assert len(results) == 3
    assert results[0].id == cluster_a.id
    assert results[1].id == cluster_e.id
    assert results[2].id == cluster_b.id
    assert all(cluster.identity_count > 1 for cluster in results)
    assert cluster_c.id not in [cluster.id for cluster in results]
    assert cluster_d.id not in [cluster.id for cluster in results]


@pytest.mark.asyncio
async def test_get_top_unlabeled_respects_limit(db_session, tenant) -> None:
    """get_top_unlabeled should respect limit after sorting by size."""
    repo = SqlAlchemyClusterRepository(db_session)
    tenant_id = str(tenant.id)

    # Cluster A: largest.
    cluster_a = await repo.save(
        IdentityCluster(
            id=None,
            tenant_id=tenant_id,
            label=None,
            is_labeled=False,
            identity_count=10,
            created_at=datetime.now(tz=UTC),
            user_confirmed=False,
        )
    )
    # Cluster B: second largest.
    await repo.save(
        IdentityCluster(
            id=None,
            tenant_id=tenant_id,
            label=None,
            is_labeled=False,
            identity_count=8,
            created_at=datetime.now(tz=UTC),
            user_confirmed=False,
        )
    )
    await db_session.commit()

    results = await repo.get_top_unlabeled(tenant_id, limit=1)

    assert len(results) == 1
    assert results[0].id == cluster_a.id


@pytest.mark.asyncio
async def test_get_top_unlabeled_falls_back_to_members_when_representatives_missing(
    db_session, tenant, seed_media_identity
) -> None:
    """Clusters without representative rows should still expose thumbnail-capable member fallbacks."""
    cluster_repo = SqlAlchemyClusterRepository(db_session)
    member_repo = SqlAlchemyMemberRepository(db_session, tenant_id=str(tenant.id))
    tenant_id = str(tenant.id)

    cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=tenant_id,
            label=None,
            is_labeled=False,
            identity_count=5,
            created_at=datetime.now(tz=UTC),
            user_confirmed=False,
        )
    )

    identities_by_similarity = [
        (str(uuid.uuid4()), 0.20),
        (str(uuid.uuid4()), 0.95),
        (str(uuid.uuid4()), 0.40),
        (str(uuid.uuid4()), 0.70),
        (str(uuid.uuid4()), 0.30),
    ]
    for identity_id, _similarity in identities_by_similarity:
        await seed_media_identity(identity_id)
    for identity_id, similarity in identities_by_similarity:
        await member_repo.add_member(cluster.id, identity_id=identity_id, similarity=similarity)
    await db_session.commit()

    results = await cluster_repo.get_top_unlabeled(tenant_id, limit=10)

    assert len(results) == 1
    returned = results[0]
    assert returned.id == cluster.id
    assert returned.representatives is not None
    assert len(returned.representatives) == 4
    assert returned.representatives[0].identity_id == identities_by_similarity[1][0]
    assert returned.representatives[0].media_url is not None
    assert returned.representatives[0].bbox_width is not None
    assert returned.representatives[0].bbox_height is not None


@pytest.mark.asyncio
async def test_get_top_unlabeled_tops_up_partial_representatives_to_four(
    db_session, tenant, seed_media_identity
) -> None:
    """Clusters with fewer than 4 representatives should be topped up from members for thumbnail grids."""
    cluster_repo = SqlAlchemyClusterRepository(db_session)
    member_repo = SqlAlchemyMemberRepository(db_session, tenant_id=str(tenant.id))
    tenant_id = str(tenant.id)

    cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=tenant_id,
            label=None,
            is_labeled=False,
            identity_count=4,
            created_at=datetime.now(tz=UTC),
            user_confirmed=False,
        )
    )

    identities_by_similarity = [
        (str(uuid.uuid4()), 0.95),
        (str(uuid.uuid4()), 0.80),
        (str(uuid.uuid4()), 0.70),
        (str(uuid.uuid4()), 0.60),
    ]
    for identity_id, _similarity in identities_by_similarity:
        await seed_media_identity(identity_id)
    for identity_id, similarity in identities_by_similarity:
        await member_repo.add_member(cluster.id, identity_id=identity_id, similarity=similarity)

    # Persist only 3 representatives to reproduce the 3/4 thumbnail mismatch.
    for identity_id, similarity in identities_by_similarity[:3]:
        await cluster_repo.add_representative(
            ClusterRepresentative(
                id=str(uuid.uuid4()),
                cluster_id=cluster.id,
                identity_id=identity_id,
                tenant_id=tenant_id,
                embedding=np.zeros(512, dtype=np.float32),
                created_at=datetime.now(tz=UTC),
                quality_score=similarity,
            )
        )

    await db_session.commit()

    results = await cluster_repo.get_top_unlabeled(tenant_id, limit=10)

    assert len(results) == 1
    returned = results[0]
    assert returned.representatives is not None
    assert len(returned.representatives) == 4
    returned_identity_ids = {rep.identity_id for rep in returned.representatives}
    assert returned_identity_ids == {identity_id for identity_id, _ in identities_by_similarity}

    topped_up_rep = next(rep for rep in returned.representatives if rep.identity_id == identities_by_similarity[3][0])
    assert topped_up_rep.media_url is not None
    assert topped_up_rep.bbox_width is not None
    assert topped_up_rep.bbox_height is not None


@pytest.mark.asyncio
async def test_get_top_unlabeled_excludes_clusters_with_accepted_member_suggestions(
    db_session, tenant, seed_media_identity
) -> None:
    """Clusters with accepted member suggestions to another cluster should be excluded."""
    cluster_repo = SqlAlchemyClusterRepository(db_session)
    member_repo = SqlAlchemyMemberRepository(db_session, tenant_id=str(tenant.id))
    tenant_id = str(tenant.id)

    source_cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=tenant_id,
            label=None,
            is_labeled=False,
            identity_count=3,
            created_at=datetime.now(tz=UTC),
            user_confirmed=False,
        )
    )
    fallback_cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=tenant_id,
            label=None,
            is_labeled=False,
            identity_count=2,
            created_at=datetime.now(tz=UTC),
            user_confirmed=False,
        )
    )
    target_cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=tenant_id,
            label="Slate Willow",
            is_labeled=True,
            identity_count=10,
            created_at=datetime.now(tz=UTC),
            user_confirmed=True,
        )
    )

    member_identity_id = str(uuid.uuid4())
    await seed_media_identity(member_identity_id)
    await member_repo.add_member(source_cluster.id, identity_id=member_identity_id, similarity=0.81)

    db_session.add(
        IdentitySuggestion(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            identity_id=uuid.UUID(member_identity_id),
            suggested_cluster_id=uuid.UUID(target_cluster.id),
            representative_similarity=0.85,
            avg_member_similarity=0.85,
            confidence_score=0.85,
            resolution="accepted",
        )
    )
    await db_session.commit()

    results = await cluster_repo.get_top_unlabeled(tenant_id, limit=10)
    result_ids = {cluster.id for cluster in results}

    assert source_cluster.id not in result_ids
    assert fallback_cluster.id in result_ids
