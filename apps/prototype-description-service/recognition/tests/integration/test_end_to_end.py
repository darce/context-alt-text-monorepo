from __future__ import annotations

import pytest

from db.models import Tenant
from recognition.application.orchestration.cluster_service import ClusterService
from recognition.application.scan.service import ScanService
from recognition.infrastructure.repositories.cluster_repository import SqlAlchemyClusterRepository
from recognition.infrastructure.repositories.member_repository import SqlAlchemyMemberRepository


@pytest.mark.asyncio
async def test_full_clustering_flow(
    db_session,
    tenant: Tenant,
    scan_service: ScanService,
    cluster_service: ClusterService,
    cluster_repository: SqlAlchemyClusterRepository,
    member_repository: SqlAlchemyMemberRepository,
) -> None:
    """Validate full flow: Scan -> Persist -> Cluster -> Verify."""

    tenant_id = str(tenant.id)
    media_ids = ["media1", "media2", "media3"]  # Detects 1 face per media -> 3 total identities

    # 1. Analyze Media (Detection + Embedding)
    scan_job = await scan_service.analyze_media(tenant_id=tenant_id, media_ids=media_ids)
    assert scan_job.status == "completed"
    assert scan_job.identities_detected == 3

    # 2. Verify Unclustered Identities
    unclustered = await cluster_repository.get_unclustered(tenant_id)
    assert len(unclustered) == 3

    # 3. Running Clustering
    result = await cluster_service.cluster_unclustered_identities(tenant_id)

    # 4. Verification
    assert result.completed == 3
    assert result.clusters_created >= 1

    # Check Persistence
    clusters = await cluster_repository.get_by_tenant(tenant_id)
    assert len(clusters) >= 1

    first_cluster = clusters[0]
    assert first_cluster.identity_count > 0
    # Algorithm can be "graph" (unified pipeline) or "hdbscan"
    assert first_cluster.clustering_algorithm in ("graph", "hdbscan")

    # Verify members
    members = await member_repository.get_by_cluster(first_cluster.id)
    assert len(members) == first_cluster.identity_count

    # Verify representatives
    # RepresentativeDiscovery should have picked reps for the new cluster
    reps = await cluster_repository.get_all_representatives(first_cluster.id)
    if first_cluster.identity_count > 0:
        assert len(reps) > 0, "New cluster should have at least one representative"
