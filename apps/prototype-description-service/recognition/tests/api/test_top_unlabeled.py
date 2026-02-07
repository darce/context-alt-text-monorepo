"""Integration tests for Curate Top Clusters endpoint."""

import uuid
from datetime import UTC, datetime

import numpy as np
import pytest
from starlette.testclient import TestClient

from recognition.domain.representative import ClusterRepresentative
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


@pytest.mark.asyncio
async def test_get_top_unlabeled_includes_representative_crop_fields(
    api_client: TestClient,
    tenant_id: str,
    fake_cluster_repository,
) -> None:
    cluster_id = str(uuid.uuid4())
    fake_cluster_repository.seed(cluster_id, label=None, identity_count=3)

    fake_cluster_repository.clusters[cluster_id].representatives = [
        ClusterRepresentative(
            id=str(uuid.uuid4()),
            cluster_id=cluster_id,
            identity_id=str(uuid.uuid4()),
            embedding=np.zeros(512, dtype=np.float32),
            created_at=datetime.now(tz=UTC),
            media_id=101,
            media_url="http://example.test/media/101.jpg",
            bbox_x=12,
            bbox_y=8,
            bbox_width=40,
            bbox_height=30,
            thumbnail_url="http://example.test/thumb/101.jpg",
            is_user_selected=False,
        )
    ]

    resp = api_client.get(
        "/recognition/clusters/top-unlabeled",
        params={"tenant_id": tenant_id, "limit": 1},
        headers={"X-Tenant-ID": tenant_id},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    rep = body[0]["representatives"][0]
    assert rep["media_url"] == "http://example.test/media/101.jpg"
    assert rep["bbox"] == {"x": 12, "y": 8, "width": 40, "height": 30}
    assert rep["thumb_url"] == "http://example.test/thumb/101.jpg"


@pytest.mark.asyncio
async def test_get_top_unlabeled_includes_suggested_label_fields(
    api_client: TestClient,
    tenant_id: str,
    fake_cluster_repository,
) -> None:
    cluster_id = str(uuid.uuid4())
    fake_cluster_repository.seed(cluster_id, label=None, identity_count=4)
    cluster = fake_cluster_repository.clusters[cluster_id]
    cluster.suggested_label = "Coral Osborne"
    cluster.suggested_label_source = "similar_cluster"
    cluster.suggested_label_confidence = 0.93
    cluster.suggested_target_cluster_id = str(uuid.uuid4())

    resp = api_client.get(
        "/recognition/clusters/top-unlabeled",
        params={"tenant_id": tenant_id, "limit": 1},
        headers={"X-Tenant-ID": tenant_id},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["suggested_label"] == "Coral Osborne"
    assert body[0]["suggested_label_source"] == "similar_cluster"
    assert body[0]["suggested_label_confidence"] == 0.93
    assert body[0]["suggested_target_cluster_id"] == cluster.suggested_target_cluster_id


@pytest.mark.asyncio
async def test_dismissed_clusters_excluded_from_top_unlabeled(
    api_client: TestClient,
    tenant_id: str,
    fake_cluster_repository,
) -> None:
    """Dismissed clusters should not appear in the top-unlabeled listing."""
    fake_cluster_repository.seed("c-big", label=None, identity_count=20)
    fake_cluster_repository.seed("c-small", label=None, identity_count=5)

    # Dismiss the big cluster
    fake_cluster_repository.clusters["c-big"].dismissed_at = datetime.now(tz=UTC)

    resp = api_client.get(
        "/recognition/clusters/top-unlabeled",
        params={"tenant_id": tenant_id, "limit": 10},
        headers={"X-Tenant-ID": tenant_id},
    )

    assert resp.status_code == 200
    body = resp.json()
    ids = [c["id"] for c in body]
    assert "c-big" not in ids
    assert "c-small" in ids


@pytest.mark.asyncio
async def test_dismiss_cluster_endpoint(
    api_client: TestClient,
    tenant_id: str,
    fake_cluster_repository,
) -> None:
    """POST /clusters/{id}/dismiss should mark cluster as dismissed."""
    cluster_id = str(uuid.uuid4())
    fake_cluster_repository.seed(cluster_id, label=None, identity_count=5)

    resp = api_client.post(
        f"/recognition/clusters/{cluster_id}/dismiss",
        headers={"X-Tenant-ID": tenant_id},
    )

    assert resp.status_code == 204
    assert fake_cluster_repository.clusters[cluster_id].dismissed_at is not None


@pytest.mark.asyncio
async def test_dismiss_cluster_not_found(
    api_client: TestClient,
    tenant_id: str,
) -> None:
    """POST /clusters/{id}/dismiss for unknown ID should return 404."""
    resp = api_client.post(
        f"/recognition/clusters/{uuid.uuid4()}/dismiss",
        headers={"X-Tenant-ID": tenant_id},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_undismiss_cluster_endpoint(
    api_client: TestClient,
    tenant_id: str,
    fake_cluster_repository,
) -> None:
    """DELETE /clusters/{id}/dismiss should clear the dismissed flag."""
    cluster_id = str(uuid.uuid4())
    fake_cluster_repository.seed(cluster_id, label=None, identity_count=5)
    fake_cluster_repository.clusters[cluster_id].dismissed_at = datetime.now(tz=UTC)

    resp = api_client.delete(
        f"/recognition/clusters/{cluster_id}/dismiss",
        headers={"X-Tenant-ID": tenant_id},
    )

    assert resp.status_code == 204
    assert fake_cluster_repository.clusters[cluster_id].dismissed_at is None
