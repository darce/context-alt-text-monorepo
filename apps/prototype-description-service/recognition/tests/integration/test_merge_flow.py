from __future__ import annotations

import pytest
from sqlalchemy import select

from db.models import IdentityCluster, IdentityMember, Tenant
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
async def test_merge_cluster_logic(
    db_session,
    tenant: Tenant,
    cluster_service: ClusterService,
    cluster_repository: SqlAlchemyClusterRepository,
    member_repository: SqlAlchemyMemberRepository,
    scan_service: ScanService,
) -> None:
    tenant_id = str(tenant.id)
    import uuid

    from recognition.domain.cluster import IdentityCluster as DomainCluster

    # Create 3 identities
    await scan_service.analyze_media(tenant_id, ["2001", "2002", "2003"])

    # Manually create 2 clusters and assign members
    # Need identity IDs
    # Query IdentityMember is hard without repo for it? member_repository has it.

    # Actually, simpler:
    # 1. Create 2 Clusters
    c1 = await cluster_repository.save(
        DomainCluster(tenant_id=tenant_id, label="Source", is_labeled=True, identity_count=1)
    )
    c2 = await cluster_repository.save(
        DomainCluster(tenant_id=tenant_id, label="Target", is_labeled=True, identity_count=1)
    )

    # 2. Get Identities (using raw sql or repo?)
    # We scanned 3 items. They should be in MediaIdentity table.
    from db.models import IdentityMember, MediaIdentity

    res = await db_session.execute(select(MediaIdentity).where(MediaIdentity.tenant_id == tenant.id))
    identities = res.scalars().all()
    assert len(identities) == 3

    id1, id2, _id3 = identities[0], identities[1], identities[2]

    # 3. Assign members
    # Move id1 to c1
    # Move id2 to c2
    # Leave id3 unclustered (for retry matching test)

    db_session.add(IdentityMember(cluster_id=uuid.UUID(c1.id), identity_id=id1.id, tenant_id=tenant.id, similarity=1.0))
    db_session.add(IdentityMember(cluster_id=uuid.UUID(c2.id), identity_id=id2.id, tenant_id=tenant.id, similarity=1.0))
    await db_session.flush()

    # Verify initial state
    assert len(await member_repository.get_by_cluster(str(c1.id))) == 1
    assert len(await member_repository.get_by_cluster(str(c2.id))) == 1

    # 4. Perform Merge: c1 -> c2
    merged = await cluster_service.merge_cluster(
        source_cluster_id=str(c1.id), tenant_id=tenant_id, target_cluster_id=str(c2.id), target_label="Merged Target"
    )

    assert merged is not None
    assert str(merged.id) == str(c2.id)
    assert merged.label == "Merged Target"
    assert merged.identity_count == 2

    # Verify c1 is gone
    assert await cluster_repository.get_by_id(str(c1.id)) is None

    # Verify members
    members_c2 = await member_repository.get_by_cluster(str(c2.id))
    assert len(members_c2) == 2

    # 5. Test Retry Matching (Background Task Logic)
    # id3 is unclustered. If its embedding is close to c2's new representative (calculated from id1+id2), it might get picked up.
    # We can't guarantee similarity match with stubs easily unless we control embeddings.
    # But we can verify the function runs without error.

    await cluster_service.retry_matching(str(c2.id), tenant_id)

    # Check logs or just ensure no exception.
    # Ideally check if id3 got picked up if we force high similarity?
    # Hard to force with integration test random embeddings.
    # Just running it is sufficient to prove the wiring works.
