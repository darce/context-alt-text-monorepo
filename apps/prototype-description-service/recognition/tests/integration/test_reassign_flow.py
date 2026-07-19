import uuid

import pytest
from sqlalchemy import select

from db.models import IdentityCluster, IdentityMember, MediaIdentity, Tenant
from recognition.application.orchestration.cluster_service import ClusterService
from recognition.domain.cluster import IdentityCluster as DomainCluster
from recognition.infrastructure.repositories.cluster_repository import SqlAlchemyClusterRepository
from recognition.infrastructure.repositories.member_repository import SqlAlchemyMemberRepository


@pytest.mark.asyncio
async def test_reassign_single_member_preserves_cluster(
    db_session,
    tenant: Tenant,
    cluster_service: ClusterService,
    cluster_repository: SqlAlchemyClusterRepository,
    member_repository: SqlAlchemyMemberRepository,
) -> None:
    """
    Verify that removing a single member from a multi-member cluster
    only removes that specific member and leaves the rest of the cluster intact.
    This characterizes the correct behavior for the 'Wrong Person' feature.
    """
    # Ensure tenant_id is UUID
    tenant_uuid = uuid.UUID(str(tenant.id))
    tenant_id_str = str(tenant_uuid)

    # 1. Setup Data
    # Create valid identities first
    identities = []
    for i in range(3):
        mi = MediaIdentity(
            tenant_id=tenant_uuid,
            media_id=100 + i,
            media_url=f"http://example.com/{i}.jpg",
            confidence=0.9,
            bbox_x=0,
            bbox_y=0,
            bbox_width=10,
            bbox_height=10,
            embedding=[0.1] * 512,
            embedding_model="buffalo_l@insightface",
        )
        db_session.add(mi)
        identities.append(mi)
    await db_session.flush()

    # Create Cluster manually
    domain_cluster = DomainCluster(tenant_id=tenant_id_str, label="Musketeers", is_labeled=True, identity_count=3)
    # Repo saves it. Repo expects Domain object.
    saved_cluster = await cluster_repository.save(domain_cluster)
    cluster_uuid = uuid.UUID(str(saved_cluster.id))

    # Assign members
    member_ids = []
    for mi in identities:
        mi_uuid = uuid.UUID(str(mi.id))
        mem = IdentityMember(cluster_id=cluster_uuid, identity_id=mi_uuid, tenant_id=tenant_uuid, similarity=0.9)
        db_session.add(mem)
        member_ids.append(str(mi_uuid))
    await db_session.flush()

    # Verify initial state
    members = await member_repository.get_by_cluster(str(cluster_uuid))
    assert len(members) == 3

    # 2. Reassign (Remove) ONE member
    victim_id = member_ids[0]
    survivor_ids = member_ids[1:]

    await cluster_service.remove_identity_from_cluster(identity_id=victim_id, recompute=True)

    # 3. Verify Result
    # Victim should be unassigned
    # Survivors should still be in cluster

    # Refresh members
    current_members = await member_repository.get_by_cluster(str(cluster_uuid))
    current_member_ids = [str(m.identity_id) for m in current_members]

    # Normalize IDs to strings for comparison
    assert victim_id not in current_member_ids
    assert len(current_members) == 2
    for survivor in survivor_ids:
        assert survivor in current_member_ids

    # Cluster should still exist
    loaded_cluster = await cluster_repository.get_by_id(str(cluster_uuid))
    assert loaded_cluster is not None
