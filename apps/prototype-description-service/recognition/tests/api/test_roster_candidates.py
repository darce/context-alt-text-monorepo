"""API contract tests for GET /recognition/clusters/{id}/roster-candidates."""

from __future__ import annotations

import uuid

from recognition.tests.api.conftest import seed_cluster


def test_roster_candidates_empty_when_cluster_exists_without_roster(
    api_client, tenant_id, fake_cluster_service, fake_cluster_repository
) -> None:
    cluster = seed_cluster(
        fake_cluster_service,
        tenant_id,
        label=None,
        fake_cluster_repository=fake_cluster_repository,
    )

    resp = api_client.get(
        f"/recognition/clusters/{cluster.id}/roster-candidates",
        headers={"X-Tenant-ID": tenant_id},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["candidates"] == []
    assert "model_id" in body
    assert "embedding_model" in body
    assert "computed_at" in body
    assert "reference_face_count" in body
    assert set(body["thresholds"]) == {
        "suggestion_floor",
        "suggestion_ceiling",
        "similarity_threshold",
    }


def test_roster_candidates_missing_cluster_is_404(api_client, tenant_id) -> None:
    resp = api_client.get(
        f"/recognition/clusters/{uuid.uuid4()}/roster-candidates",
        headers={"X-Tenant-ID": tenant_id},
    )
    assert resp.status_code == 404


def test_roster_candidates_rejects_top_k_above_max(api_client, tenant_id, fake_cluster_service, fake_cluster_repository) -> None:
    cluster = seed_cluster(
        fake_cluster_service,
        tenant_id,
        label=None,
        fake_cluster_repository=fake_cluster_repository,
    )
    resp = api_client.get(
        f"/recognition/clusters/{cluster.id}/roster-candidates",
        headers={"X-Tenant-ID": tenant_id},
        params={"top_k": 51},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "top_k out of range"
