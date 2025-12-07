"""API contract checks for ID formatting (standard UUIDv7)."""

from __future__ import annotations

import uuid

import pytest

from recognition.interface_adapters.http.validation import is_uuid
from recognition.tests.api.conftest import seed_cluster


def test_job_ids_are_valid_uuids(api_client, tenant_id) -> None:
    """Job IDs returned by the API should be standard UUIDs."""
    resp = api_client.post(
        "/recognition/analyze",
        json={"media_ids": [str(uuid.uuid4())], "tenant_id": tenant_id},
        headers={"X-Tenant-ID": tenant_id},
    )
    job_id = resp.json()["id"]

    assert resp.status_code == 202
    assert is_uuid(job_id), f"Job ID '{job_id}' is not a valid UUID"


@pytest.mark.asyncio
async def test_cluster_and_suggestion_ids_are_valid_uuids(
    api_client, tenant_id, fake_cluster_service, fake_suggestion_service
) -> None:
    """Cluster and suggestion IDs should be standard UUIDs."""
    identity_id = str(uuid.uuid4())
    cluster = seed_cluster(fake_cluster_service, tenant_id)
    suggestion = await fake_suggestion_service.create(identity_id=identity_id, cluster_id=cluster.id)

    resp_clusters = api_client.get(
        "/recognition/clusters",
        params={"tenant_id": tenant_id},
        headers={"X-Tenant-ID": tenant_id},
    )
    resp_suggestions = api_client.get(
        f"/recognition/identities/{identity_id}/suggestions",
        headers={"X-Tenant-ID": tenant_id},
    )

    assert resp_clusters.status_code == 200
    assert resp_suggestions.status_code == 200
    clusters = resp_clusters.json()
    suggestions = resp_suggestions.json()

    assert clusters and is_uuid(clusters[0]["id"])
    assert suggestions and is_uuid(suggestions[0]["id"])
    assert suggestion.id in fake_suggestion_service.suggestions
