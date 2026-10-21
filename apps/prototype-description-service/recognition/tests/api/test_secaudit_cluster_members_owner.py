"""Object authorization for cluster member reads, without database or network IO."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from recognition.interface_adapters.http.routers import clusters_snapshot


TENANT_ID = "abcdefab-1234-4567-89ab-abcdefabcdef"
FOREIGN_TENANT_ID = "12345678-1234-4567-89ab-abcdefabcdef"
CLUSTER_ID = "11111111-1234-4567-89ab-abcdefabcdef"
IDENTITY_ID = "22222222-1234-4567-89ab-abcdefabcdef"


@pytest.mark.parametrize("owner", [None, FOREIGN_TENANT_ID, TENANT_ID, UUID(TENANT_ID), TENANT_ID.upper()])
def test_cluster_members_authorizes_owner_before_member_queries(owner):
    cluster = None if owner is None else SimpleNamespace(tenant_id=owner, label="Owned cluster")
    identity = SimpleNamespace(id=IDENTITY_ID, media_id=101, confidence=0.9)
    repo = SimpleNamespace(
        get_by_id=AsyncMock(return_value=cluster),
        get_member_identity_count=AsyncMock(return_value=1),
        get_member_identities_with_similarity=AsyncMock(return_value=[(identity, 0.95)]),
    )
    builder = AsyncMock(return_value=SimpleNamespace(cluster_repository=repo))
    app = FastAPI()
    app.include_router(clusters_snapshot.router, prefix="/recognition")
    app.dependency_overrides[clusters_snapshot.require_auth] = lambda: None
    app.dependency_overrides[clusters_snapshot.enforce_rate_limit] = lambda: None
    app.dependency_overrides[clusters_snapshot.get_authenticated_tenant_id] = lambda: TENANT_ID
    app.dependency_overrides[clusters_snapshot.get_cluster_service_builder] = lambda: builder

    with TestClient(app) as client:
        response = client.get(f"/recognition/clusters/{CLUSTER_ID}/members")

    builder.assert_awaited_once_with(TENANT_ID)
    repo.get_by_id.assert_awaited_once_with(CLUSTER_ID)
    if owner is None or owner == FOREIGN_TENANT_ID:
        assert response.status_code == 404
        assert response.json() == {"detail": "No clusters found for tenant"}
        repo.get_member_identity_count.assert_not_called()
        repo.get_member_identities_with_similarity.assert_not_called()
    else:
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["members"][0]["identity_id"] == IDENTITY_ID
        assert body["members"][0]["media_id"] == 101
        repo.get_member_identity_count.assert_awaited_once_with(CLUSTER_ID)
        repo.get_member_identities_with_similarity.assert_awaited_once_with(CLUSTER_ID, limit=500, offset=0)
