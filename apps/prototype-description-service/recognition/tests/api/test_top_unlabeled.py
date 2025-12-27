"""Integration tests for Curate Top Clusters endpoint."""

import uuid

import pytest
from httpx import AsyncClient

from recognition.tests.api.conftest import seed_cluster


@pytest.mark.asyncio
async def test_get_top_unlabeled_returns_clusters(
    api_client,
    tenant_id,
    fake_cluster_service,
    fake_cluster_repository,
) -> None:
    """Endpoint should return unlabeled clusters ordered by identity count."""
    # Seed some clusters
    # 1. Unlabeled (identity_count=10)
    c1 = seed_cluster(fake_cluster_service, tenant_id, label=None)
    c1.identity_count = 10

    # 2. Labeled (should be excluded)
    c2 = seed_cluster(fake_cluster_service, tenant_id, label="Already Labeled")
    c2.identity_count = 20

    # 3. Unlabeled (identity_count=5)
    c3 = seed_cluster(fake_cluster_service, tenant_id, label=None)
    c3.identity_count = 5

    # Target the fake repository directly
    fake_cluster_repository.seed(c1.id, label=None, identity_count=10)
    fake_cluster_repository.seed(c2.id, label="Already Labeled", identity_count=20)
    fake_cluster_repository.seed(c3.id, label=None, identity_count=5)

    resp = api_client.get(
        "/recognition/clusters/top-unlabeled",
        params={"tenant_id": tenant_id, "limit": 2},
        headers={"X-Tenant-ID": tenant_id},
    )

    assert resp.status_code == 200
    body = resp.json()

    assert len(body) == 2
    assert body[0]["id"] == c1.id
    assert body[0]["identity_count"] == 10
    assert body[1]["id"] == c3.id
    assert body[1]["identity_count"] == 5
    assert not any(c["label"] for c in body)
