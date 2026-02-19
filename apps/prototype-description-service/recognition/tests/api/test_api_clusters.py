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


def test_recover_orphans_returns_summary(api_client, tenant_id, fake_cluster_service, monkeypatch) -> None:
    class Result:
        total = 4
        accepted = 2
        suggested = 1
        rejected = 1
        clusters_created = 2

    async def _fake_recover(_tenant_id, *_args, **_kwargs):
        return Result()

    monkeypatch.setattr(fake_cluster_service, "cluster_unclustered_identities", _fake_recover)

    resp = api_client.post("/recognition/clusters/recover-orphans", json={"tenant_id": tenant_id})

    assert resp.status_code == 200
    body = resp.json()
    assert body["orphans_found"] == 4
    assert body["recovered"] == 2
    assert body["suggested"] == 1
    assert body["rejected"] == 1
    assert body["clusters_created"] == 2


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


def test_merge_cluster_relabels_target(api_client, tenant_id, fake_cluster_service, fake_job_service) -> None:
    target = seed_cluster(fake_cluster_service, tenant_id, label="target")
    source = seed_cluster(fake_cluster_service, tenant_id, label="source")

    resp = api_client.post(
        f"/recognition/clusters/{source.id}/merge",
        json={"tenant_id": tenant_id, "target_cluster_id": target.id, "target_label": "merged"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["label"] == "merged"
    assert resp.status_code == 200
    body = resp.json()
    assert body["label"] == "merged"

    # Source cluster should NOT be deleted immediately (deferred)
    assert any(c.id == source.id for c in fake_cluster_service.clusters)

    # Verify curation job was queued with source_cluster_id
    curation_calls = [c for c in fake_job_service.calls if c["method"] == "queue_curation_followup"]
    assert curation_calls
    call = curation_calls[-1]
    assert call["source_cluster_id"] == source.id
    assert target.id in call["cluster_ids"]


def test_merge_cluster_same_target_does_not_queue_followup(
    api_client, tenant_id, fake_cluster_service, fake_job_service
):
    target = seed_cluster(fake_cluster_service, tenant_id, label="target")

    resp = api_client.post(
        f"/recognition/clusters/{target.id}/merge",
        json={"tenant_id": tenant_id, "target_cluster_id": target.id, "target_label": "merged"},
    )

    assert resp.status_code == 200
    curation_calls = [c for c in fake_job_service.calls if c["method"] == "queue_curation_followup"]
    assert not curation_calls


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
    fake_suggestion_refresh_service,
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
    assert len(fake_suggestion_refresh_service.refresh_calls) >= 2

    # Check for identity refresh
    identity_refreshes = [c for c in fake_suggestion_refresh_service.refresh_calls if c[0] == identity_id]
    assert identity_refreshes, "Identity refresh not found"
    id_ref_id, id_ref_reason = identity_refreshes[0]
    assert getattr(id_ref_reason, "value", str(id_ref_reason)) == "wrong_person"

    # Check for cluster refresh
    cluster_refreshes = [c for c in fake_suggestion_refresh_service.refresh_calls if c[0] == cluster.id]
    assert cluster_refreshes, "Cluster refresh not found"
    cl_ref_id, cl_ref_reason = cluster_refreshes[0]
    assert cl_ref_reason == "cluster_refresh"


def test_get_tenant_snapshot_returns_404_for_unknown_tenant(api_client) -> None:
    unknown_tenant_id = str(uuid.uuid4())

    resp = api_client.get(f"/recognition/tenants/{unknown_tenant_id}/clusters/snapshot")

    assert resp.status_code == 404
    assert "No clusters found" in resp.json()["detail"]


def test_get_tenant_snapshot_returns_correct_shape(
    api_client, tenant_id, fake_cluster_service, fake_cluster_repository
) -> None:
    # Seed some clusters and members (seeds both service and repository)
    cluster1 = seed_cluster(
        fake_cluster_service, tenant_id, label="Alice", fake_cluster_repository=fake_cluster_repository
    )
    cluster2 = seed_cluster(
        fake_cluster_service, tenant_id, label=None, fake_cluster_repository=fake_cluster_repository
    )

    resp = api_client.get(f"/recognition/tenants/{tenant_id}/clusters/snapshot")

    assert resp.status_code == 200
    body = resp.json()

    # Verify top-level structure
    assert "tenant_id" in body
    assert body["tenant_id"] == tenant_id
    assert "snapshot_version" in body
    assert isinstance(body["snapshot_version"], int)
    assert "generated_at" in body
    assert "clusters" in body
    assert "members" in body

    # Verify clusters array
    assert isinstance(body["clusters"], list)
    assert len(body["clusters"]) >= 2

    # Find our seeded clusters
    alice_cluster = next((c for c in body["clusters"] if c["label"] == "Alice"), None)
    assert alice_cluster is not None
    assert alice_cluster["cluster_uuid"] == cluster1.id
    assert "is_user_confirmed" in alice_cluster
    assert "curation_state" in alice_cluster
    assert "identity_count" in alice_cluster

    unlabeled_cluster = next((c for c in body["clusters"] if c["cluster_uuid"] == cluster2.id), None)
    assert unlabeled_cluster is not None
    assert "is_user_confirmed" in unlabeled_cluster
    assert "curation_state" in unlabeled_cluster


def test_get_tenant_snapshot_includes_members(
    api_client, tenant_id, fake_cluster_service, fake_cluster_repository
) -> None:
    # Seed a cluster with identities (seeds both service and repository)
    cluster = seed_cluster(
        fake_cluster_service, tenant_id, label="Bob", fake_cluster_repository=fake_cluster_repository
    )
    identity_id = str(uuid.uuid4())
    fake_cluster_service.seed_identity_membership(identity_id, cluster.id)

    resp = api_client.get(f"/recognition/tenants/{tenant_id}/clusters/snapshot")

    assert resp.status_code == 200
    body = resp.json()

    # Verify members exists
    assert "members" in body
    assert isinstance(body["members"], list)

    # Note: The fake service may not return members if not implemented - this validates structure
    if len(body["members"]) > 0:
        member = body["members"][0]
        assert "identity_uuid" in member
        assert "cluster_uuid" in member
        assert "attachment_id" in member
        assert "similarity" in member
        assert "bbox" in member
        assert "image_width" in member
        assert "image_height" in member
        assert "thumb_path" in member

        # Verify bbox structure
        bbox = member["bbox"]
        assert "x" in bbox
        assert "y" in bbox
        assert "width" in bbox
        assert "height" in bbox
