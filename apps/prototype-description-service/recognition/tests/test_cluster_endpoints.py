"""Integration tests for cluster label/merge endpoints."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest_asyncio

import pytest
from httpx import AsyncClient

from db.models import IdentityCluster, Tenant
from db.session import async_session_factory
from db.tenant_context import clear_tenant_context, set_tenant_context


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
