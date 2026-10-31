"""HTTP boundary forwards validated filters to both actual producer operations."""

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_filtered_review_forwards_minimum_and_offset(api_client, tenant_id, fake_cluster_repository):
    calls = []

    async def count(tenant, **kwargs):
        calls.append(("count", tenant, kwargs))
        return 4

    async def page(tenant, **kwargs):
        calls.append(("page", tenant, kwargs))
        return []

    fake_cluster_repository.count_top_unlabeled = count
    fake_cluster_repository.get_top_unlabeled = page
    async with AsyncClient(transport=ASGITransport(app=api_client.app), base_url="http://test") as client:
        response = await client.get(
            "/recognition/clusters/top-unlabeled",
            params={"min_photos": 2, "offset": 3, "limit": 1},
            headers={"X-Tenant-ID": tenant_id},
        )
    assert response.status_code == 200
    assert calls == [
        ("count", tenant_id, {"min_identity_count": 2, "min_photos": 2}),
        ("page", tenant_id, {"limit": 1, "min_identity_count": 2, "min_photos": 2, "offset": 3}),
    ]
    assert response.json()["truncated"] is True


@pytest.mark.parametrize("minimum", ["0", "-1", "1.5", "abc", "2147483648"])
@pytest.mark.asyncio
async def test_filtered_review_rejects_invalid_minimum(api_client, tenant_id, minimum):
    async with AsyncClient(transport=ASGITransport(app=api_client.app), base_url="http://test") as client:
        response = await client.get(
            "/recognition/clusters/top-unlabeled", params={"min_photos": minimum}, headers={"X-Tenant-ID": tenant_id}
        )
    assert response.status_code == 400
