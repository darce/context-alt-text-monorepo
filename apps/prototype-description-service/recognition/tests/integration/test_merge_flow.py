from __future__ import annotations

import pytest
from sqlalchemy import select

from db.models import IdentityMember, Tenant
from recognition.application.orchestration.cluster_service import ClusterService
from recognition.application.scan.service import ScanService
from recognition.infrastructure.repositories.cluster_repository import SqlAlchemyClusterRepository
from recognition.infrastructure.repositories.member_repository import SqlAlchemyMemberRepository


@pytest.mark.asyncio
async def test_merge_and_retry_flow(
    db_session,
    tenant: Tenant,
    scan_service: ScanService,
    cluster_service: ClusterService,
    cluster_repository: SqlAlchemyClusterRepository,
    member_repository: SqlAlchemyMemberRepository,
) -> None:
    """Validate merge flow: Create 2 clusters -> Merge -> Verify -> Retry Matching."""

    tenant_id = str(tenant.id)

    # 1. Create Data: 2 separate clusters
    # Cluster A: 2 members
    # Cluster B: 1 member
    media_ids_a = ["1001", "1002"]
    media_ids_b = ["1003"]

    await scan_service.analyze_media(tenant_id, media_ids_a + media_ids_b)

    # Get valid identity IDs from DB
    from db.models import MediaIdentity

    res = await db_session.execute(select(MediaIdentity).where(MediaIdentity.tenant_id == tenant.id))
    identities = res.scalars().all()
    assert len(identities) == 3
    id1, id2, id3 = identities[0], identities[1], identities[2]

    # Create clusters manually using service to ensure they exist
    # Create Cluster A for id1
    c1 = await cluster_service.create_cluster_for_identity(
        identity_id=str(id1.id), label="Cluster A", tenant_id=tenant_id
    )
    # Assign id2 to Cluster A
    # Easiest: Insert Member directly
    import uuid

    from db.models import IdentityMember

    db_session.add(
        IdentityMember(cluster_id=uuid.UUID(c1.id), identity_id=id2.id, tenant_id=tenant.id, similarity=0.99)
    )
    await db_session.flush()

    # Create Cluster B for id3
    c2 = await cluster_service.create_cluster_for_identity(
        identity_id=str(id3.id), label="Cluster B", tenant_id=tenant_id
    )

    # Verify setup
    assert len(await member_repository.get_by_cluster(str(c1.id))) == 2
    assert len(await member_repository.get_by_cluster(str(c2.id))) == 1

    # 2. Perform Merge: c1 -> c2
    merged = await cluster_service.merge_cluster(
        source_cluster_id=str(c1.id), tenant_id=tenant_id, target_cluster_id=str(c2.id), target_label="Merged Cluster"
    )
    assert merged is not None
    assert merged.id == str(c2.id)
    assert merged.identity_count == 3

    # 3. Retry Matching
    # This just ensures no crash
    await cluster_service.retry_matching(str(c2.id), tenant_id)


@pytest.mark.asyncio
async def test_merge_transaction_ordering(
    db_session,
    tenant: Tenant,
    cluster_service: ClusterService,
    cluster_repository: SqlAlchemyClusterRepository,
    member_repository: SqlAlchemyMemberRepository,
    scan_service: ScanService,
) -> None:
    """Verify that source cluster deletion happens without 404 errors during complex merges."""
    tenant_id = str(tenant.id)
    import uuid

    from recognition.domain.cluster import IdentityCluster as DomainCluster

    # Setup: 2 clusters
    c1 = await cluster_repository.save(
        DomainCluster(tenant_id=tenant_id, label="Source", is_labeled=True, identity_count=1)
    )
    c2 = await cluster_repository.save(
        DomainCluster(tenant_id=tenant_id, label="Target", is_labeled=True, identity_count=1)
    )

    # Ensure they exist
    assert await cluster_repository.get_by_id(str(c1.id)) is not None

    # Perform Merge
    # The key regression test here is that this does NOT raise "Cluster not found"
    # which happened when deletion occurred before commit/flush of dependencies
    await cluster_service.merge_cluster(
        source_cluster_id=str(c1.id), tenant_id=tenant_id, target_cluster_id=str(c2.id), target_label="Merged Safe"
    )

    # Verify final state
    assert await cluster_repository.get_by_id(str(c1.id)) is None
    merged = await cluster_repository.get_by_id(str(c2.id))
    assert merged is not None
    assert merged.label == "Merged Safe"
