"""TDD tests for outlier handling surfaced via cluster listing."""

from __future__ import annotations

import uuid

import pytest

from recognition.domain.cluster import IdentityCluster
from recognition.interface_adapters.http import dependencies


@pytest.mark.asyncio
async def test_outliers_included_when_requested(db_session, tenant) -> None:
    """Outlier clusters (label=-1/noise) should be surfaced when include_outliers=true."""
    cluster_service = await dependencies.build_cluster_service(session=db_session, tenant_id=str(tenant.id))
    cluster_repo = cluster_service.assignment_writer._clusters
    member_repo = cluster_service.assignment_writer._members

    # Persist a normal cluster with one member
    cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="cluster",
            is_labeled=False,
            identity_count=1,
            created_at=None,
        )
    )
    await member_repo.add_member(cluster.id, identity_id=str(uuid.uuid4()), similarity=0.9)

    # Seed an outlier cluster that should be hidden by default
    outlier_cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="-1",
            is_labeled=False,
            identity_count=1,
            created_at=None,
        )
    )

    clusters_with_outliers = await cluster_service.list_clusters(str(tenant.id), include_outliers=True)
    clusters_without_outliers = await cluster_service.list_clusters(str(tenant.id), include_outliers=False)

    assert any(c.id == outlier_cluster.id for c in clusters_with_outliers)
    assert not any(c.id == outlier_cluster.id for c in clusters_without_outliers)
