"""API tests for cluster endpoints using faked services."""

from __future__ import annotations

import uuid

import pytest

from recognition.tests.api.conftest import seed_cluster


def test_clustering_job_async_returns_status(api_client, tenant_id, fake_job_service) -> None:
    payload = {"tenant_id": tenant_id, "mode": "async"}

    resp = api_client.post("/recognition/clustering/jobs", json=payload)

    assert resp.status_code == 202
    body = resp.json()
    assert body["id"]
    assert body["type"] == "clustering"
    assert body["status"] in {"running", "completed", "pending"}
    assert body["progress"]["total"] == 0
    assert body["id"] in fake_job_service.repository.jobs


def test_clustering_job_sync_returns_completed_status(api_client, tenant_id) -> None:
    payload = {"tenant_id": tenant_id, "mode": "sync"}

    resp = api_client.post("/recognition/clustering/jobs", json=payload)

    assert resp.status_code == 202
    body = resp.json()
    assert body["type"] == "clustering"
    assert body["status"] == "completed"
    assert body["progress"]["total"] == body["progress"]["completed"]


def test_list_clusters_returns_seeded_data(api_client, tenant_id, fake_cluster_service) -> None:
    seeded = seed_cluster(fake_cluster_service, tenant_id)

    resp = api_client.get(
        "/recognition/clusters",
        params={"tenant_id": tenant_id},
        headers={"X-Tenant-ID": tenant_id},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert any(cluster["id"] == seeded.id for cluster in body)


def test_patch_cluster_label_updates_cluster(api_client, tenant_id, fake_cluster_service) -> None:
    cluster = seed_cluster(fake_cluster_service, tenant_id, label=None)

    resp = api_client.patch(
        f"/recognition/clusters/{cluster.id}",
        json={"tenant_id": tenant_id, "label": "test"},
    )

    assert resp.status_code == 200
    assert resp.json()["label"] == "test"


def test_merge_cluster_relabels_target(api_client, tenant_id, fake_cluster_service) -> None:
    target = seed_cluster(fake_cluster_service, tenant_id, label="target")
    source = seed_cluster(fake_cluster_service, tenant_id, label="source")

    resp = api_client.post(
        f"/recognition/clusters/{source.id}/merge",
        json={"tenant_id": tenant_id, "target_cluster_id": target.id, "target_label": "merged"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["label"] == "merged"
    assert all(c.id != source.id for c in fake_cluster_service.clusters)


def test_assign_outlier_to_cluster_via_api(api_client, tenant_id, fake_cluster_service) -> None:
    cluster = seed_cluster(fake_cluster_service, tenant_id, label="target")
    starting_count = cluster.identity_count

    resp = api_client.post(
        f"/recognition/clusters/{cluster.id}/assign",
        json={"tenant_id": tenant_id, "identity_id": str(uuid.uuid4()), "similarity": 0.5},
    )

    assert resp.status_code == 200
    assert resp.json()["identity_count"] == starting_count + 1


def test_include_outliers_flag_is_passed_to_service(api_client, tenant_id, fake_cluster_service) -> None:
    resp = api_client.get(
        "/recognition/clusters",
        params={"tenant_id": tenant_id, "include_outliers": True},
        headers={"X-Tenant-ID": tenant_id},
    )

    assert resp.status_code == 200
    assert any(call.get("include_outliers") for call in fake_cluster_service.calls)


@pytest.mark.asyncio
async def test_reassign_removal_refreshes_suggestions(
    api_client,
    tenant_id,
    fake_cluster_service,
    fake_suggestion_service,
) -> None:
    identity_id = str(uuid.uuid4())
    cluster = seed_cluster(fake_cluster_service, tenant_id, label="source")
    fake_cluster_service.seed_identity_membership(identity_id, cluster.id)

    resp = api_client.post(
        "/recognition/clusters/reassign",
        json={
            "tenant_id": tenant_id,
            "identity_id": identity_id,
            "target_cluster_id": None,
            "block_from_cluster": False,
        },
    )

    assert resp.status_code == 200
    assert len(fake_suggestion_service.refresh_calls) >= 2

    # Check for identity refresh
    identity_refreshes = [c for c in fake_suggestion_service.refresh_calls if c[0] == identity_id]
    assert identity_refreshes, "Identity refresh not found"
    id_ref_id, id_ref_reason = identity_refreshes[0]
    assert getattr(id_ref_reason, "value", str(id_ref_reason)) == "wrong_person"

    # Check for cluster refresh
    cluster_refreshes = [c for c in fake_suggestion_service.refresh_calls if c[0] == cluster.id]
    assert cluster_refreshes, "Cluster refresh not found"
    cl_ref_id, cl_ref_reason = cluster_refreshes[0]
    assert cl_ref_reason == "cluster_refresh"
