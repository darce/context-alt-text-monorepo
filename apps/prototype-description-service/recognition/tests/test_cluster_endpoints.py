"""Integration tests for cluster label/merge endpoints."""

from __future__ import annotations

import os
from uuid import UUID, uuid4

import numpy as np
import pytest
import pytest_asyncio
from httpx import AsyncClient
from PIL import Image
from sqlalchemy import select, text

from db.models import IdentityCluster, IdentityMember, IdentityScanJob, Tenant
from db.session import async_session_factory
from db.tenant_context import (
    clear_tenant_context,
    disable_rls_bypass,
    enable_rls_bypass,
    set_tenant_context,
)
from recognition.application.identity_clustering_service import IdentityClusteringService
from recognition.application.identity_scan_service import IdentityScanService
from recognition.domain.entities import IdentityDetection, IdentityEmbedding
from recognition.tests.fakes import make_media_identity

pytestmark = pytest.mark.usefixtures("require_database")

if os.getenv("ALLOW_RLS_BYPASS_FOR_TESTS") == "1":
    pytest.skip("Skipping cluster endpoint tests when RLS bypass is enabled", allow_module_level=True)


@pytest.fixture(autouse=True)
def enable_rls_bypass_for_cluster_tests(monkeypatch):
    """Allow RLS bypass in integration-style cluster endpoint tests."""
    monkeypatch.setenv("ALLOW_RLS_BYPASS_FOR_TESTS", "1")


@pytest_asyncio.fixture()
async def tenant_id() -> str:
    tenant = str(uuid4())
    async with async_session_factory() as session:
        session.add(Tenant(id=tenant, site_url=f"https://{tenant}.example.com"))
        await session.commit()
    return tenant


@pytest_asyncio.fixture()
async def sample_cluster(tenant_id: str):
    """Return cluster ID and initial data dict to avoid detached instance errors."""
    async with async_session_factory() as session:
        tenant_uuid = UUID(tenant_id)
        await set_tenant_context(session, tenant_uuid)
        cluster = IdentityCluster(
            tenant_id=tenant_uuid,
            label="cluster-abc",
            identity_count=1,
        )
        session.add(cluster)
        await session.commit()
        await set_tenant_context(session, tenant_uuid)
        await session.refresh(cluster)
        cluster_id = cluster.id
        identity_count = cluster.identity_count
        await clear_tenant_context(session)
        return {"id": cluster_id, "identity_count": identity_count}


@pytest_asyncio.fixture()
async def cluster_with_member(tenant_id: str):
    """Return cluster and identity IDs to avoid detached instance errors."""
    tenant_uuid = UUID(tenant_id)
    async with async_session_factory() as session:
        await set_tenant_context(session, tenant_uuid)
        cluster = IdentityCluster(
            tenant_id=tenant_uuid,
            label="cluster-base",
            identity_count=1,
        )
        identity = make_media_identity(tenant_uuid, media_id=404)
        session.add_all([cluster, identity])
        await session.flush()
        session.add(
            IdentityMember(
                tenant_id=tenant_uuid,
                cluster_id=cluster.id,
                identity_id=identity.id,
                similarity=0.88,
            )
        )
        await session.commit()
        cluster_id = cluster.id
        identity_id = identity.id
        await clear_tenant_context(session)
        return {"cluster_id": cluster_id, "identity_id": identity_id}


async def refresh_centroid_view(session):
    """Refresh the materialized view. Always uses RLS bypass for the refresh operation."""
    # REFRESH MATERIALIZED VIEW needs to read from source tables without RLS
    await enable_rls_bypass(session)
    await session.execute(text("REFRESH MATERIALIZED VIEW mv_identity_cluster_centroids"))
    await disable_rls_bypass(session)


@pytest.mark.asyncio
async def test_update_cluster_label(async_client: AsyncClient, tenant_id: str, sample_cluster: dict):
    response = await async_client.patch(
        f"/recognition/clusters/{sample_cluster['id']}",
        json={"tenant_id": tenant_id, "label": "Named Cluster"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["label"] == "Named Cluster"
    assert payload["identity_count"] == sample_cluster["identity_count"]


@pytest.mark.asyncio
async def test_update_cluster_label_conflict_returns_409(
    async_client: AsyncClient,
    tenant_id: str,
    sample_cluster: dict,
):
    tenant_uuid = UUID(tenant_id)
    async with async_session_factory() as session:
        await set_tenant_context(session, tenant_uuid)
        session.add(
            IdentityCluster(
                tenant_id=tenant_uuid,
                label="Existing Label",
                identity_count=1,
            )
        )
        await session.commit()
        await clear_tenant_context(session)

    response = await async_client.patch(
        f"/recognition/clusters/{sample_cluster['id']}",
        json={"tenant_id": tenant_id, "label": "Existing Label"},
    )
    assert response.status_code == 409

    # Confirm original cluster label was not changed
    async with async_session_factory() as session:
        await set_tenant_context(session, tenant_uuid)
        cluster = await session.get(IdentityCluster, sample_cluster["id"])
        assert cluster is not None
        assert cluster.label == "cluster-abc"
        await clear_tenant_context(session)


@pytest.mark.asyncio
async def test_merge_cluster(async_client: AsyncClient, tenant_id: str, sample_cluster: dict):
    response = await async_client.post(
        f"/recognition/clusters/{sample_cluster['id']}/merge",
        json={"tenant_id": tenant_id, "target_label": "Merged Cluster"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["source_id"] == str(sample_cluster["id"])
    assert payload["target_id"] != payload["source_id"]
    assert payload["identities_moved"] >= 0


@pytest.mark.asyncio
async def test_merge_creates_target_and_moves_members(
    async_client: AsyncClient,
    tenant_id: str,
    cluster_with_member: dict,
):
    cluster_id = cluster_with_member["cluster_id"]
    identity_id = cluster_with_member["identity_id"]
    response = await async_client.post(
        f"/recognition/clusters/{cluster_id}/merge",
        json={"tenant_id": tenant_id, "target_label": "Merged Cluster"},
    )
    assert response.status_code == 200
    payload = response.json()
    target_id = UUID(payload["target_id"])
    assert payload["identities_moved"] == 1

    tenant_uuid = UUID(tenant_id)
    async with async_session_factory() as session:
        await set_tenant_context(session, tenant_uuid)
        target = await session.get(IdentityCluster, target_id)
        assert target is not None
        assert target.label == "Merged Cluster"
        assert target.identity_count == 1

        member_result = await session.execute(select(IdentityMember).where(IdentityMember.identity_id == identity_id))
        member = member_result.scalar_one()
        assert member.cluster_id == target.id

        original = await session.get(IdentityCluster, cluster_id)
        assert original is None
        await clear_tenant_context(session)


@pytest.mark.asyncio
async def test_merge_similar_endpoint_merges_clusters(async_client: AsyncClient, tenant_id: str):
    tenant_uuid = UUID(tenant_id)
    async with async_session_factory() as session:
        await set_tenant_context(session, tenant_uuid)
        identity_a = make_media_identity(tenant_uuid, media_id=501, embedding=[1.0] * 1024)
        identity_b = make_media_identity(tenant_uuid, media_id=502, embedding=[0.99] * 1024)
        identity_c = make_media_identity(tenant_uuid, media_id=503, embedding=[0.0] * 1024)
        session.add_all([identity_a, identity_b, identity_c])
        await session.flush()

        cluster_a = IdentityCluster(
            tenant_id=tenant_uuid,
            label="cluster-a",
            representative_identity_id=identity_a.id,
            identity_count=1,
        )
        cluster_b = IdentityCluster(
            tenant_id=tenant_uuid,
            label="cluster-b",
            representative_identity_id=identity_b.id,
            identity_count=1,
        )
        cluster_c = IdentityCluster(
            tenant_id=tenant_uuid,
            label="cluster-c",
            representative_identity_id=identity_c.id,
            identity_count=1,
        )
        session.add_all([cluster_a, cluster_b, cluster_c])
        await session.flush()
        session.add_all(
            [
                IdentityMember(
                    tenant_id=tenant_uuid,
                    cluster_id=cluster_a.id,
                    identity_id=identity_a.id,
                    similarity=0.9,
                ),
                IdentityMember(
                    tenant_id=tenant_uuid,
                    cluster_id=cluster_b.id,
                    identity_id=identity_b.id,
                    similarity=0.9,
                ),
                IdentityMember(
                    tenant_id=tenant_uuid,
                    cluster_id=cluster_c.id,
                    identity_id=identity_c.id,
                    similarity=0.5,
                ),
            ]
        )
        await session.commit()
        await refresh_centroid_view(session)
        await session.commit()
        await clear_tenant_context(session)

    response = await async_client.post(
        "/recognition/clusters/merge-similar",
        json={"tenant_id": tenant_id, "threshold": 0.95},
    )
    assert response.status_code == 200
    assert response.json()["merges_performed"] == 1

    async with async_session_factory() as session:
        await set_tenant_context(session, tenant_uuid)
        remaining = await session.execute(select(IdentityCluster))
        labels = sorted([cluster.label for cluster in remaining.scalars().all() if cluster.label is not None])
        assert "cluster-c" in labels
        assert len(labels) == 2
        await clear_tenant_context(session)


@pytest.mark.asyncio
async def test_suggest_similar_clusters_returns_matches(async_client: AsyncClient, tenant_id: str):
    tenant_uuid = UUID(tenant_id)
    query_vector = [1.0] * 1024

    async with async_session_factory() as session:
        await set_tenant_context(session, tenant_uuid)
        identity = make_media_identity(tenant_uuid, media_id=610, embedding=query_vector)
        session.add(identity)
        await session.flush()

        cluster = IdentityCluster(
            tenant_id=tenant_uuid,
            label="cluster-suggest",
            representative_identity_id=identity.id,
            identity_count=1,
        )
        session.add(cluster)
        await session.flush()

        session.add(
            IdentityMember(
                tenant_id=tenant_uuid,
                cluster_id=cluster.id,
                identity_id=identity.id,
                similarity=0.99,
            )
        )
        await session.commit()
        await refresh_centroid_view(session)
        await session.commit()
        await clear_tenant_context(session)

    params = [("tenant_id", tenant_id)] + [("embedding", f"{value}") for value in query_vector]
    response = await async_client.get("/recognition/clusters/suggest", params=params)
    assert response.status_code == 200
    matches = response.json()["matches"]
    assert matches
    assert matches[0]["label"] == "cluster-suggest"


class StubEmbeddingProvider:
    async def analyze(self, image):  # noqa: ARG002
        detection = IdentityDetection(bbox=(0, 0, 10, 10), confidence=0.95)
        embedding = np.ones(1024, dtype=np.float32)
        other_detection = IdentityDetection(bbox=(10, 10, 20, 20), confidence=0.9)
        other_embedding = np.concatenate([np.ones(512, dtype=np.float32), np.full(512, 0.9, dtype=np.float32)])
        return [
            IdentityEmbedding(embedding=embedding, detection=detection),
            IdentityEmbedding(embedding=other_embedding, detection=other_detection),
        ]


class StubScanService(IdentityScanService):
    def __init__(self, session, provider, tenant_id):
        super().__init__(session, provider, tenant_id)
        self._image = Image.new("RGB", (16, 16))

    async def _fetch_image(self, url):  # noqa: ARG002
        return self._image


@pytest.mark.asyncio
async def test_end_to_end_scan_to_rename_flow(async_client: AsyncClient):
    tenant_id = uuid4()
    media_id = 888

    async with async_session_factory() as session:
        session.add(Tenant(id=tenant_id, site_url=f"https://{tenant_id}.example.com"))
        await session.commit()
        await set_tenant_context(session, tenant_id)

        job = IdentityScanJob(
            tenant_id=tenant_id,
            status="pending",
            media_ids=[media_id],
            total_media=1,
        )
        session.add(job)
        await session.commit()

        service = StubScanService(session, StubEmbeddingProvider(), tenant_id)
        await set_tenant_context(session, tenant_id)
        await service.scan_identities(
            job,
            [{"media_id": media_id, "media_url": "https://example.com/image.jpg"}],
            user_id=1,
        )

        await set_tenant_context(session, tenant_id)
        clustering_service = IdentityClusteringService(session=session, tenant_id=tenant_id)
        clusters = await clustering_service.cluster_identities_incremental()
        assert clusters
        cluster_id = clusters[0].id
        await clear_tenant_context(session)

    response = await async_client.get(
        "/recognition/media/identities",
        params=[("tenant_id", str(tenant_id)), ("media_ids", str(media_id))],
    )
    assert response.status_code == 200
    payload = response.json()
    initial_label = payload["identities_by_media"][str(media_id)][0]["cluster_label"]
    assert initial_label.startswith("cluster-")

    response = await async_client.patch(
        f"/recognition/clusters/{cluster_id}",
        json={"tenant_id": str(tenant_id), "label": "Test User"},
    )
    assert response.status_code == 200

    response = await async_client.get(
        "/recognition/media/identities",
        params=[("tenant_id", str(tenant_id)), ("media_ids", str(media_id))],
    )
    assert response.status_code == 200
    updated_label = response.json()["identities_by_media"][str(media_id)][0]["cluster_label"]
    assert updated_label == "Test User"
