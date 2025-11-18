"""Integration tests for cluster label/merge endpoints."""

from __future__ import annotations

from uuid import UUID, uuid4

import numpy as np
import pytest
import pytest_asyncio
from httpx import AsyncClient
from PIL import Image
from sqlalchemy import select

from db.models import IdentityCluster, IdentityMember, IdentityScanJob, Tenant
from db.session import async_session_factory
from db.tenant_context import clear_tenant_context, set_tenant_context
from recognition.application.identity_clustering_service import IdentityClusteringService
from recognition.application.identity_scan_service import IdentityScanService
from recognition.domain.entities import IdentityDetection, IdentityEmbedding
from recognition.tests.fakes import make_media_identity

pytestmark = pytest.mark.usefixtures("require_database")


@pytest_asyncio.fixture()
async def tenant_id() -> str:
    tenant = str(uuid4())
    async with async_session_factory() as session:
        session.add(Tenant(id=tenant, site_url=f"https://{tenant}.example.com"))
        await session.commit()
    return tenant


@pytest_asyncio.fixture()
async def sample_cluster(tenant_id: str):
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
        await clear_tenant_context(session)
        return cluster


@pytest_asyncio.fixture()
async def cluster_with_member(tenant_id: str):
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
        await clear_tenant_context(session)
        return cluster, identity


@pytest.mark.asyncio
async def test_update_cluster_label(async_client: AsyncClient, tenant_id: str, sample_cluster: IdentityCluster):
    response = await async_client.patch(
        f"/recognition/clusters/{sample_cluster.id}",
        json={"tenant_id": tenant_id, "label": "Named Cluster"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["label"] == "Named Cluster"
    assert payload["identity_count"] == sample_cluster.identity_count


@pytest.mark.asyncio
async def test_update_cluster_label_conflict_returns_409(
    async_client: AsyncClient,
    tenant_id: str,
    sample_cluster: IdentityCluster,
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
        f"/recognition/clusters/{sample_cluster.id}",
        json={"tenant_id": tenant_id, "label": "Existing Label"},
    )
    assert response.status_code == 409

    # Confirm original cluster label was not changed
    async with async_session_factory() as session:
        await set_tenant_context(session, tenant_uuid)
        cluster = await session.get(IdentityCluster, sample_cluster.id)
        assert cluster.label == "cluster-abc"
        await clear_tenant_context(session)


@pytest.mark.asyncio
async def test_merge_cluster(async_client: AsyncClient, tenant_id: str, sample_cluster: IdentityCluster):
    response = await async_client.post(
        f"/recognition/clusters/{sample_cluster.id}/merge",
        json={"tenant_id": tenant_id, "target_label": "Merged Cluster"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["source_id"] == str(sample_cluster.id)
    assert payload["target_id"] != payload["source_id"]
    assert payload["identities_moved"] >= 0


@pytest.mark.asyncio
async def test_merge_creates_target_and_moves_members(
    async_client: AsyncClient,
    tenant_id: str,
    cluster_with_member,
):
    cluster, identity = cluster_with_member
    response = await async_client.post(
        f"/recognition/clusters/{cluster.id}/merge",
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

        member_result = await session.execute(
            select(IdentityMember).where(IdentityMember.identity_id == identity.id)
        )
        member = member_result.scalar_one()
        assert member.cluster_id == target.id

        original = await session.get(IdentityCluster, cluster.id)
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
        labels = sorted(cluster.label for cluster in remaining.scalars().all())
        assert "cluster-c" in labels
        assert len(labels) == 2
        await clear_tenant_context(session)


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
        clusters = await clustering_service.cluster_identities()
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
