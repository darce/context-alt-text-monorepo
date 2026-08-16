"""API tests for cluster endpoints using faked services."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from recognition.domain.job import Job, JobStatus, JobType
from recognition.interface_adapters.http import deps as dependencies
from recognition.interface_adapters.http import router as recognition_router
from recognition.tests.api.conftest import FakeSession, seed_cluster


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


def test_clustering_job_async_reuses_existing_active_job(api_client, tenant_id, fake_job_service) -> None:
    existing_job = Job(
        id=str(uuid.uuid4()),
        type=JobType.CLUSTERING,
        tenant_id=tenant_id,
        status=JobStatus.PENDING,
        progress_completed=0,
        progress_total=0,
    )
    fake_job_service.repository.jobs[existing_job.id] = existing_job

    resp = api_client.post("/recognition/clustering/jobs", json={"tenant_id": tenant_id, "mode": "async"})

    assert resp.status_code == 202
    body = resp.json()
    assert body["id"] == existing_job.id
    assert len(fake_job_service.repository.jobs) == 1


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


def test_list_clusters_uses_authenticated_tenant_claim(monkeypatch, tenant_id, fake_cluster_service) -> None:
    captured: dict[str, str] = {}
    monkeypatch.setenv("RECOGNITION_AUTH_ENABLED", "1")

    app = FastAPI()
    app.include_router(recognition_router, prefix="/recognition")

    async def _session_dep():
        yield FakeSession()

    def cluster_builder():
        async def _build(resolved_tenant_id: str):
            captured["tenant_id"] = resolved_tenant_id
            return fake_cluster_service

        return _build

    app.dependency_overrides[dependencies.get_session] = _session_dep
    app.dependency_overrides[dependencies.get_optional_session] = _session_dep
    app.dependency_overrides[dependencies.get_cluster_service_builder] = cluster_builder

    from recognition.interface_adapters.http.deps import auth

    async def _fake_lookup(api_key, settings, session):  # noqa: ANN001
        assert api_key == "good-key"
        return tenant_id, "key-1", "enterprise", False

    monkeypatch.setattr(auth, "_lookup_api_key", _fake_lookup)

    seeded = seed_cluster(fake_cluster_service, tenant_id)
    client = TestClient(app)
    resp = client.get("/recognition/clusters", headers={"Authorization": "Bearer good-key"})

    assert resp.status_code == 200
    assert captured["tenant_id"] == tenant_id
    assert any(cluster["id"] == seeded.id for cluster in resp.json())


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

    merge_calls = [call for call in fake_cluster_service.calls if call.get("method") == "merge_cluster"]
    assert merge_calls
    assert merge_calls[-1]["defer_recompute"] is True
    assert merge_calls[-1]["moved_by_merge_id"] is not None
    uuid.UUID(str(merge_calls[-1]["moved_by_merge_id"]))

    # Source cluster should NOT be deleted immediately (deferred)
    assert any(c.id == source.id for c in fake_cluster_service.clusters)

    # Verify curation job was queued with source_cluster_id
    curation_calls = [c for c in fake_job_service.calls if c["method"] == "queue_curation_followup"]
    assert curation_calls
    call = curation_calls[-1]
    assert call["source_cluster_id"] == source.id
    assert target.id in call["cluster_ids"]


def test_merge_cluster_rejects_reserved_target_label(api_client, tenant_id, fake_cluster_service) -> None:
    from recognition.domain.cluster import ReservedClusterLabelError
    from recognition.interface_adapters.http.exception_handlers import register_exception_handlers

    register_exception_handlers(api_client.app)
    target = seed_cluster(fake_cluster_service, tenant_id, label="target")
    source = seed_cluster(fake_cluster_service, tenant_id, label="source")
    fake_cluster_service.merge_cluster = AsyncMock(side_effect=ReservedClusterLabelError("cluster-forbidden"))

    response = api_client.post(
        f"/recognition/clusters/{source.id}/merge",
        json={"tenant_id": tenant_id, "target_cluster_id": target.id, "target_label": "cluster-forbidden"},
    )

    assert response.status_code == 400
    assert response.json()["error"] == "ReservedClusterLabelError"


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


def test_merge_cluster_is_idempotent_with_idempotency_key(
    api_client, tenant_id, fake_cluster_service, fake_job_service
) -> None:
    target = seed_cluster(fake_cluster_service, tenant_id, label="target")
    source = seed_cluster(fake_cluster_service, tenant_id, label="source")
    payload = {
        "tenant_id": tenant_id,
        "target_cluster_id": target.id,
        "target_label": "merged",
        "idempotency_key": "merge-idem-1",
    }

    first = api_client.post(f"/recognition/clusters/{source.id}/merge", json=payload)
    second = api_client.post(f"/recognition/clusters/{source.id}/merge", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == first.json()

    curation_calls = [c for c in fake_job_service.calls if c["method"] == "queue_curation_followup"]
    assert len(curation_calls) == 1


def test_split_topology_command_returns_typed_result(
    api_client, tenant_id, fake_cluster_service, fake_cluster_repository
) -> None:
    source = seed_cluster(
        fake_cluster_service,
        tenant_id,
        label="source",
        fake_cluster_repository=fake_cluster_repository,
        identity_count=2,
    )
    moved_identity_id = str(uuid.uuid4())
    retained_identity_id = str(uuid.uuid4())
    fake_cluster_repository.seed_member(tenant_id=tenant_id, cluster_id=source.id, identity_id=moved_identity_id)
    fake_cluster_repository.seed_member(tenant_id=tenant_id, cluster_id=source.id, identity_id=retained_identity_id)

    resp = api_client.post(
        "/recognition/topology-commands/split",
        json={
            "tenant_id": tenant_id,
            "cluster_id": source.id,
            "n_clusters": 2,
            "expected_base_version": 0,
            "idempotency_key": str(uuid.uuid4()),
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "applied"
    assert body["original_cluster_id"] == source.id
    assert len(body["new_cluster_ids"]) == 1
    assert body["affected_cluster_ids"][0] == source.id
    assert body["new_cluster_ids"][0] in body["affected_cluster_ids"]
    assert body["moved_counts"] == [1]
    assert body["member_delta"]["source_cluster_id"] == source.id
    assert body["member_delta"]["remaining_identity_ids"] == [moved_identity_id]
    assert len(body["member_delta"]["created_clusters"]) == 1
    assert body["member_delta"]["created_clusters"][0]["cluster_id"] == body["new_cluster_ids"][0]
    assert body["member_delta"]["created_clusters"][0]["identity_ids"] == [retained_identity_id]
    assert isinstance(body["result_snapshot_version"], int)


def test_split_topology_command_is_idempotent(
    api_client, tenant_id, fake_cluster_service, fake_cluster_repository
) -> None:
    source = seed_cluster(
        fake_cluster_service, tenant_id, label="source", fake_cluster_repository=fake_cluster_repository
    )
    idempotency_key = str(uuid.uuid4())
    payload = {
        "tenant_id": tenant_id,
        "cluster_id": source.id,
        "n_clusters": 2,
        "expected_base_version": 0,
        "idempotency_key": idempotency_key,
    }

    first = api_client.post("/recognition/topology-commands/split", json=payload)
    second = api_client.post("/recognition/topology-commands/split", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == first.json()


def test_targeted_snapshot_returns_only_requested_clusters(
    api_client, tenant_id, fake_cluster_service, fake_cluster_repository
) -> None:
    requested = seed_cluster(
        fake_cluster_service, tenant_id, label="requested", fake_cluster_repository=fake_cluster_repository
    )
    ignored = seed_cluster(
        fake_cluster_service, tenant_id, label="ignored", fake_cluster_repository=fake_cluster_repository
    )
    fake_cluster_repository.seed_member(tenant_id=tenant_id, cluster_id=requested.id, identity_id=str(uuid.uuid4()))
    fake_cluster_repository.seed_member(tenant_id=tenant_id, cluster_id=ignored.id, identity_id=str(uuid.uuid4()))

    resp = api_client.get(
        f"/recognition/tenants/{tenant_id}/clusters/targeted-snapshot",
        params=[("cluster_ids", requested.id)],
    )

    assert resp.status_code == 200
    body = resp.json()
    assert [cluster["cluster_uuid"] for cluster in body["clusters"]] == [requested.id]
    assert {member["cluster_uuid"] for member in body["members"]} == {requested.id}


def test_cluster_delta_returns_only_changed_clusters(
    api_client, tenant_id, fake_cluster_service, fake_cluster_repository, monkeypatch
) -> None:
    changed = seed_cluster(
        fake_cluster_service, tenant_id, label="changed", fake_cluster_repository=fake_cluster_repository
    )
    unchanged = seed_cluster(
        fake_cluster_service, tenant_id, label="unchanged", fake_cluster_repository=fake_cluster_repository
    )
    changed_identity_id = str(uuid.uuid4())
    fake_cluster_repository.seed_member(
        tenant_id=tenant_id,
        cluster_id=changed.id,
        identity_id=changed_identity_id,
        media_id="101",
    )
    fake_cluster_repository.seed_member(
        tenant_id=tenant_id,
        cluster_id=unchanged.id,
        identity_id=str(uuid.uuid4()),
        media_id="202",
    )
    fake_cluster_repository.clusters[changed.id].representatives = [
        SimpleNamespace(
            id=str(uuid.uuid4()),
            identity_id=changed_identity_id,
            media_id="101",
            is_user_selected=True,
        )
    ]
    snapshot_version = fake_cluster_repository._snapshot_version

    async def _fake_get_delta(request_tenant_id: str, *, since_version: int):
        assert request_tenant_id == tenant_id
        assert since_version == snapshot_version - 1
        return (
            await fake_cluster_repository.get_clusters_by_ids(tenant_id, [changed.id]),
            await fake_cluster_repository.get_members_by_cluster_ids(tenant_id, [changed.id]),
            snapshot_version,
        )

    monkeypatch.setattr(fake_cluster_repository, "get_delta", _fake_get_delta)

    resp = api_client.get(
        f"/recognition/tenants/{tenant_id}/clusters/delta",
        params={"since_version": snapshot_version - 1},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["tenant_id"] == tenant_id
    assert body["snapshot_version"] == snapshot_version
    assert [cluster["cluster_uuid"] for cluster in body["clusters"]] == [changed.id]
    assert body["clusters"][0]["representative_id"] == changed_identity_id
    assert body["clusters"][0]["is_pinned"] is True
    assert {member["cluster_uuid"] for member in body["members"]} == {changed.id}
    assert [member["identity_uuid"] for member in body["members"]] == [changed_identity_id]


def test_cluster_delta_returns_empty_payload_when_no_clusters_changed(
    api_client, tenant_id, fake_cluster_repository, monkeypatch
) -> None:
    async def _fake_get_delta(request_tenant_id: str, *, since_version: int):
        assert request_tenant_id == tenant_id
        assert since_version == 7
        return ([], [], 9)

    monkeypatch.setattr(fake_cluster_repository, "get_delta", _fake_get_delta)

    resp = api_client.get(
        f"/recognition/tenants/{tenant_id}/clusters/delta",
        params={"since_version": 7},
    )

    assert resp.status_code == 200
    assert resp.json()["clusters"] == []
    assert resp.json()["members"] == []
    assert resp.json()["snapshot_version"] == 9


def test_cluster_delta_returns_404_for_unknown_tenant(
    api_client, tenant_id, fake_cluster_repository, monkeypatch
) -> None:
    async def _fake_get_delta(request_tenant_id: str, *, since_version: int):
        assert request_tenant_id == tenant_id
        assert since_version == 0
        return ([], [], 0)

    monkeypatch.setattr(fake_cluster_repository, "get_delta", _fake_get_delta)

    resp = api_client.get(
        f"/recognition/tenants/{tenant_id}/clusters/delta",
        params={"since_version": 0},
    )

    assert resp.status_code == 404
    assert resp.json()["detail"] == "No clusters found for tenant"


def test_split_topology_command_honors_fixed_count_desired_cluster_ids(
    api_client, tenant_id, fake_cluster_service, fake_cluster_repository
) -> None:
    source = seed_cluster(
        fake_cluster_service,
        tenant_id,
        label="source",
        fake_cluster_repository=fake_cluster_repository,
        identity_count=3,
    )
    desired_cluster_ids = [str(uuid.uuid4()), str(uuid.uuid4())]

    resp = api_client.post(
        "/recognition/topology-commands/split",
        json={
            "tenant_id": tenant_id,
            "cluster_id": source.id,
            "n_clusters": 3,
            "desired_cluster_ids": desired_cluster_ids,
            "expected_base_version": 0,
            "idempotency_key": str(uuid.uuid4()),
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["new_cluster_ids"] == desired_cluster_ids
    assert fake_cluster_service.calls[-1]["desired_cluster_ids"] == desired_cluster_ids


def test_split_topology_command_rejects_desired_cluster_ids_for_auto_mode(
    api_client, tenant_id, fake_cluster_service
) -> None:
    source = seed_cluster(fake_cluster_service, tenant_id, label="source")

    resp = api_client.post(
        "/recognition/topology-commands/split",
        json={
            "tenant_id": tenant_id,
            "cluster_id": source.id,
            "n_clusters": 0,
            "desired_cluster_ids": [str(uuid.uuid4())],
            "expected_base_version": 0,
            "idempotency_key": str(uuid.uuid4()),
        },
    )

    assert resp.status_code == 422
    assert "fixed-count splits" in resp.text


def test_split_topology_command_rejects_wrong_desired_cluster_id_count(
    api_client, tenant_id, fake_cluster_service
) -> None:
    source = seed_cluster(fake_cluster_service, tenant_id, label="source")

    resp = api_client.post(
        "/recognition/topology-commands/split",
        json={
            "tenant_id": tenant_id,
            "cluster_id": source.id,
            "n_clusters": 3,
            "desired_cluster_ids": [str(uuid.uuid4())],
            "expected_base_version": 0,
            "idempotency_key": str(uuid.uuid4()),
        },
    )

    assert resp.status_code == 422
    assert "exactly 2 ids" in resp.text


def test_split_topology_command_rejects_stale_expected_base_version(
    api_client, tenant_id, fake_cluster_service, fake_cluster_repository
) -> None:
    source = seed_cluster(
        fake_cluster_service,
        tenant_id,
        label="source",
        fake_cluster_repository=fake_cluster_repository,
        backend_version=9,
    )

    resp = api_client.post(
        "/recognition/topology-commands/split",
        json={
            "tenant_id": tenant_id,
            "cluster_id": source.id,
            "n_clusters": 2,
            "expected_base_version": 4,
            "idempotency_key": str(uuid.uuid4()),
        },
    )

    assert resp.status_code == 409
    body = resp.json()["detail"]
    assert body["conflict_code"] == "version_conflict"
    assert body["backend_version"] == 9
    assert body["source_cluster_id"] == source.id
    assert body["machine_payload"]["entity_key"] == source.id


@pytest.mark.parametrize(
    ("build_request", "expected_entity_key"),
    [
        (
            lambda tenant_id, source, target: (
                "post",
                f"/recognition/clusters/{source.id}/merge",
                {
                    "tenant_id": tenant_id,
                    "target_cluster_id": target.id,
                    "target_label": "merged",
                    "expected_base_version": 4,
                    "idempotency_key": str(uuid.uuid4()),
                },
            ),
            lambda source, _target: source.id,
        ),
        (
            lambda tenant_id, source, _target: (
                "post",
                "/recognition/clusters/create-for-identity",
                {
                    "tenant_id": tenant_id,
                    "identity_id": str(uuid.uuid4()),
                    "desired_cluster_id": source.id,
                    "label": "Created",
                    "expected_base_version": 4,
                    "idempotency_key": str(uuid.uuid4()),
                },
            ),
            lambda source, _target: source.id,
        ),
        (
            lambda tenant_id, source, _target: (
                "post",
                "/recognition/clusters/reassign",
                {
                    "tenant_id": tenant_id,
                    "identity_id": str(uuid.uuid4()),
                    "target_cluster_id": source.id,
                    "expected_base_version": 4,
                    "idempotency_key": str(uuid.uuid4()),
                },
            ),
            lambda source, _target: source.id,
        ),
        (
            lambda tenant_id, source, _target: (
                "post",
                "/recognition/clusters/revert-merge",
                {
                    "tenant_id": tenant_id,
                    "target_cluster_id": source.id,
                    "moved_identity_ids": [str(uuid.uuid4())],
                    "desired_source_cluster_id": str(uuid.uuid4()),
                    "source_label": "Restored source",
                    "expected_base_version": 4,
                    "idempotency_key": str(uuid.uuid4()),
                },
            ),
            lambda source, _target: source.id,
        ),
        (
            lambda tenant_id, source, _target: (
                "post",
                f"/recognition/clusters/{source.id}/assign",
                {
                    "tenant_id": tenant_id,
                    "identity_id": str(uuid.uuid4()),
                    "similarity": 0.5,
                    "expected_base_version": 4,
                    "idempotency_key": str(uuid.uuid4()),
                },
            ),
            lambda source, _target: source.id,
        ),
    ],
)
def test_topology_endpoints_reject_stale_expected_base_version(
    api_client,
    tenant_id,
    fake_cluster_service,
    fake_cluster_repository,
    build_request,
    expected_entity_key,
) -> None:
    source = seed_cluster(
        fake_cluster_service,
        tenant_id,
        label="source",
        fake_cluster_repository=fake_cluster_repository,
        backend_version=9,
    )
    target = seed_cluster(
        fake_cluster_service,
        tenant_id,
        label="target",
        fake_cluster_repository=fake_cluster_repository,
        backend_version=9,
    )

    method, path, payload = build_request(tenant_id, source, target)
    resp = getattr(api_client, method)(path, json=payload)

    assert resp.status_code == 409
    body = resp.json()["detail"]
    assert body["conflict_code"] == "version_conflict"
    assert body["backend_version"] == 9
    assert body["machine_payload"]["entity_key"] == expected_entity_key(source, target)


def test_assign_outlier_to_cluster_via_api(api_client, tenant_id, fake_cluster_service) -> None:
    cluster = seed_cluster(fake_cluster_service, tenant_id, label="target")
    starting_count = cluster.identity_count

    resp = api_client.post(
        f"/recognition/clusters/{cluster.id}/assign",
        json={
            "tenant_id": tenant_id,
            "identity_id": str(uuid.uuid4()),
            "similarity": 0.5,
            "expected_base_version": 0,
            "idempotency_key": str(uuid.uuid4()),
        },
    )

    assert resp.status_code == 200
    assert resp.json()["identity_count"] == starting_count + 1
    assert "backend_version" in resp.json()


def test_assign_outlier_replays_cached_response(api_client, tenant_id, fake_cluster_service) -> None:
    cluster = seed_cluster(fake_cluster_service, tenant_id, label="target")
    identity_id = str(uuid.uuid4())
    idempotency_key = str(uuid.uuid4())

    first = api_client.post(
        f"/recognition/clusters/{cluster.id}/assign",
        json={
            "tenant_id": tenant_id,
            "identity_id": identity_id,
            "similarity": 0.25,
            "expected_base_version": 0,
            "idempotency_key": idempotency_key,
        },
    )
    second = api_client.post(
        f"/recognition/clusters/{cluster.id}/assign",
        json={
            "tenant_id": tenant_id,
            "identity_id": identity_id,
            "similarity": 0.25,
            "expected_base_version": 0,
            "idempotency_key": idempotency_key,
        },
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()


def test_revert_merge_cluster_via_api(api_client, tenant_id, fake_cluster_service) -> None:
    target = seed_cluster(fake_cluster_service, tenant_id, label="merged target")
    identity_a = str(uuid.uuid4())
    identity_b = str(uuid.uuid4())
    fake_cluster_service.seed_identity_membership(identity_a, target.id)
    fake_cluster_service.seed_identity_membership(identity_b, target.id)

    resp = api_client.post(
        "/recognition/clusters/revert-merge",
        json={
            "tenant_id": tenant_id,
            "target_cluster_id": target.id,
            "moved_identity_ids": [identity_a, identity_b],
            "desired_source_cluster_id": str(uuid.uuid4()),
            "source_label": "Restored source",
            "expected_base_version": 0,
            "idempotency_key": str(uuid.uuid4()),
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["restored_identity_count"] == 2
    assert body["target_cluster_id"] == target.id
    assert body["restored_label"] == "Restored source"
    assert "backend_version" in body


def test_list_cluster_members_returns_canonical_envelope(
    api_client, tenant_id, fake_cluster_service, fake_cluster_repository
) -> None:
    cluster = seed_cluster(
        fake_cluster_service,
        tenant_id,
        label="members",
        fake_cluster_repository=fake_cluster_repository,
    )
    fake_cluster_service.cluster_repository = fake_cluster_repository
    identity_id = str(uuid.uuid4())
    fake_cluster_repository.seed_member(
        tenant_id=tenant_id,
        cluster_id=cluster.id,
        identity_id=identity_id,
        media_id="101",
    )
    fake_cluster_repository.clusters[cluster.id].representative_identity_id = identity_id

    resp = api_client.get(f"/recognition/clusters/{cluster.id}/members", headers={"X-Tenant-ID": tenant_id})

    assert resp.status_code == 200
    body = resp.json()
    assert body["limit"] == 500
    assert body["total"] == 1
    assert body["truncated"] is False
    assert len(body["members"]) == 1
    assert body["members"][0]["identity_id"] == identity_id
    assert body["members"][0]["media_id"] == 101
    assert body["members"][0]["clustering_pending"] is False
    assert body["members"][0]["cluster_id"] == cluster.id
    assert body["members"][0]["cluster_label"] == "members"
    assert body["members"][0]["is_auto_label"] is False
    assert body["members"][0]["is_pinned"] is True
    assert body["members"][0]["detected_at"] is None
    assert body["members"][0]["representative_id"] == identity_id
    assert body["members"][0]["debug_metrics"] is None


def test_list_cluster_members_marks_representative_member_as_pinned(
    api_client, tenant_id, fake_cluster_service, fake_cluster_repository
) -> None:
    cluster = seed_cluster(
        fake_cluster_service,
        tenant_id,
        label="members",
        fake_cluster_repository=fake_cluster_repository,
    )
    fake_cluster_service.cluster_repository = fake_cluster_repository
    identity_id = str(uuid.uuid4())
    fake_cluster_repository.seed_member(
        tenant_id=tenant_id,
        cluster_id=cluster.id,
        identity_id=identity_id,
        media_id="101",
    )
    fake_cluster_repository.clusters[cluster.id].representative_identity_id = identity_id

    resp = api_client.get(f"/recognition/clusters/{cluster.id}/members", headers={"X-Tenant-ID": tenant_id})

    assert resp.status_code == 200
    member = resp.json()["members"][0]
    assert member["is_pinned"] is True
    assert member["representative_id"] == identity_id


def test_list_cluster_members_marks_truncated_at_page_limit(
    api_client, tenant_id, fake_cluster_service, fake_cluster_repository
) -> None:
    cluster = seed_cluster(
        fake_cluster_service,
        tenant_id,
        label="members",
        fake_cluster_repository=fake_cluster_repository,
        identity_count=501,
    )
    fake_cluster_service.cluster_repository = fake_cluster_repository

    for index in range(501):
        fake_cluster_repository.seed_member(
            tenant_id=tenant_id,
            cluster_id=cluster.id,
            identity_id=str(uuid.uuid4()),
            media_id=str(index + 1),
        )

    resp = api_client.get(f"/recognition/clusters/{cluster.id}/members", headers={"X-Tenant-ID": tenant_id})

    assert resp.status_code == 200
    body = resp.json()
    assert body["limit"] == 500
    assert body["total"] == 501
    assert body["truncated"] is True
    assert len(body["members"]) == 500


def test_list_cluster_members_accepts_limit_and_offset_paging(
    api_client, tenant_id, fake_cluster_service, fake_cluster_repository
) -> None:
    cluster = seed_cluster(
        fake_cluster_service,
        tenant_id,
        label="paged-members",
        fake_cluster_repository=fake_cluster_repository,
        identity_count=5,
    )
    fake_cluster_service.cluster_repository = fake_cluster_repository

    identity_ids = [str(uuid.uuid4()) for _ in range(5)]
    for index, identity_id in enumerate(identity_ids):
        fake_cluster_repository.seed_member(
            tenant_id=tenant_id,
            cluster_id=cluster.id,
            identity_id=identity_id,
            media_id=str(index + 1),
        )

    first = api_client.get(
        f"/recognition/clusters/{cluster.id}/members",
        params={"limit": 2, "offset": 0},
        headers={"X-Tenant-ID": tenant_id},
    )
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["limit"] == 2
    assert first_body["total"] == 5
    assert first_body["truncated"] is True
    assert len(first_body["members"]) == 2
    assert first_body["members"][0]["identity_id"] == identity_ids[0]
    assert first_body["members"][1]["identity_id"] == identity_ids[1]

    second = api_client.get(
        f"/recognition/clusters/{cluster.id}/members",
        params={"limit": 2, "offset": 2},
        headers={"X-Tenant-ID": tenant_id},
    )
    assert second.status_code == 200
    second_body = second.json()
    assert second_body["limit"] == 2
    assert second_body["total"] == 5
    assert second_body["truncated"] is True
    assert [member["identity_id"] for member in second_body["members"]] == identity_ids[2:4]

    tail = api_client.get(
        f"/recognition/clusters/{cluster.id}/members",
        params={"limit": 2, "offset": 4},
        headers={"X-Tenant-ID": tenant_id},
    )
    assert tail.status_code == 200
    tail_body = tail.json()
    assert tail_body["limit"] == 2
    assert tail_body["total"] == 5
    assert tail_body["truncated"] is False
    assert [member["identity_id"] for member in tail_body["members"]] == identity_ids[4:]


def test_list_cluster_members_rejects_limit_above_page_cap(
    api_client, tenant_id, fake_cluster_service, fake_cluster_repository
) -> None:
    cluster = seed_cluster(
        fake_cluster_service,
        tenant_id,
        label="members-cap",
        fake_cluster_repository=fake_cluster_repository,
    )
    fake_cluster_service.cluster_repository = fake_cluster_repository

    resp = api_client.get(
        f"/recognition/clusters/{cluster.id}/members",
        params={"limit": 501, "offset": 0},
        headers={"X-Tenant-ID": tenant_id},
    )

    assert resp.status_code == 400
    assert "limit out of range" in resp.json()["detail"]


def test_list_cluster_members_rejects_negative_offset(
    api_client, tenant_id, fake_cluster_service, fake_cluster_repository
) -> None:
    cluster = seed_cluster(
        fake_cluster_service,
        tenant_id,
        label="members-offset",
        fake_cluster_repository=fake_cluster_repository,
    )
    fake_cluster_service.cluster_repository = fake_cluster_repository

    resp = api_client.get(
        f"/recognition/clusters/{cluster.id}/members",
        params={"limit": 10, "offset": -1},
        headers={"X-Tenant-ID": tenant_id},
    )

    assert resp.status_code == 400
    assert "offset must be non-negative" in resp.json()["detail"]


def test_list_cluster_members_includes_face_thumb_url_for_blob_backed_members(
    api_client, tenant_id, fake_cluster_service, fake_cluster_repository
) -> None:
    cluster = seed_cluster(
        fake_cluster_service,
        tenant_id,
        label="members",
        fake_cluster_repository=fake_cluster_repository,
        identity_count=1,
    )
    fake_cluster_service.cluster_repository = fake_cluster_repository

    fake_cluster_repository.members_by_cluster[cluster.id] = [
        (
            SimpleNamespace(similarity=0.9),
            SimpleNamespace(
                id=str(uuid.uuid4()),
                media_id="909",
                confidence=0.97,
                bbox_x=5,
                bbox_y=6,
                bbox_width=20,
                bbox_height=24,
                media_url=f"file:///tmp/blob-root/{tenant_id}/job-24/909.bin",
            ),
        )
    ]

    resp = api_client.get(f"/recognition/clusters/{cluster.id}/members", headers={"X-Tenant-ID": tenant_id})

    assert resp.status_code == 200
    body = resp.json()
    assert body["members"][0]["thumb_url"] == "/recognition/face-thumbs/job-24/909?x=5&y=6&width=20&height=24"


def test_list_cluster_members_does_not_synthesize_missing_crop_coordinates(
    api_client, tenant_id, fake_cluster_service, fake_cluster_repository
) -> None:
    cluster = seed_cluster(
        fake_cluster_service,
        tenant_id,
        label="members",
        fake_cluster_repository=fake_cluster_repository,
        identity_count=1,
    )
    fake_cluster_service.cluster_repository = fake_cluster_repository

    fake_cluster_repository.members_by_cluster[cluster.id] = [
        (
            SimpleNamespace(similarity=0.9),
            SimpleNamespace(
                id=str(uuid.uuid4()),
                media_id="909",
                confidence=0.97,
                bbox_x=None,
                bbox_y=6,
                bbox_width=20,
                bbox_height=24,
                media_url=f"file:///tmp/blob-root/{tenant_id}/job-24/909.bin",
            ),
        )
    ]

    resp = api_client.get(f"/recognition/clusters/{cluster.id}/members", headers={"X-Tenant-ID": tenant_id})

    assert resp.status_code == 200
    member = resp.json()["members"][0]
    assert member["bbox"] is None
    assert member["thumb_url"] is None


def test_list_cluster_members_omits_face_thumb_url_when_crop_exceeds_max_geometry(
    api_client, tenant_id, fake_cluster_service, fake_cluster_repository
) -> None:
    cluster = seed_cluster(
        fake_cluster_service,
        tenant_id,
        label="members",
        fake_cluster_repository=fake_cluster_repository,
        identity_count=1,
    )
    fake_cluster_service.cluster_repository = fake_cluster_repository

    fake_cluster_repository.members_by_cluster[cluster.id] = [
        (
            SimpleNamespace(similarity=0.9),
            SimpleNamespace(
                id=str(uuid.uuid4()),
                media_id="909",
                confidence=0.97,
                bbox_x=5,
                bbox_y=6,
                bbox_width=40_000,
                bbox_height=24,
                media_url=f"file:///tmp/blob-root/{tenant_id}/job-24/909.bin",
            ),
        )
    ]

    resp = api_client.get(f"/recognition/clusters/{cluster.id}/members", headers={"X-Tenant-ID": tenant_id})

    assert resp.status_code == 200
    member = resp.json()["members"][0]
    assert member["thumb_url"] is None


def test_top_unlabeled_omits_invalid_representative_bbox_and_thumb_url(
    api_client, tenant_id, fake_cluster_service, fake_cluster_repository
) -> None:
    cluster = seed_cluster(
        fake_cluster_service,
        tenant_id,
        label=None,
        fake_cluster_repository=fake_cluster_repository,
        identity_count=2,
    )
    fake_cluster_repository.clusters[cluster.id].user_confirmed = False
    fake_cluster_repository.clusters[cluster.id].representatives = [
        SimpleNamespace(
            id=str(uuid.uuid4()),
            media_id="909",
            media_url=f"file:///tmp/blob-root/{tenant_id}/job-24/909.bin",
            bbox_x=5,
            bbox_y=6,
            bbox_width=0,
            bbox_height=24,
            is_user_selected=True,
        )
    ]

    resp = api_client.get(
        "/recognition/clusters/top-unlabeled",
        headers={"X-Tenant-ID": tenant_id},
    )

    assert resp.status_code == 200
    returned_cluster = next(item for item in resp.json() if item["id"] == cluster.id)
    representative = returned_cluster["representatives"][0]
    assert representative["bbox"] is None
    assert representative["thumb_url"] is None


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
    api_client, tenant_id, fake_cluster_service, fake_cluster_repository, fake_job_service
) -> None:
    # Seed some clusters and members (seeds both service and repository)
    cluster1 = seed_cluster(
        fake_cluster_service, tenant_id, label="Alice", fake_cluster_repository=fake_cluster_repository
    )
    cluster2 = seed_cluster(
        fake_cluster_service, tenant_id, label=None, fake_cluster_repository=fake_cluster_repository
    )
    representative_id = str(uuid.uuid4())
    fake_cluster_repository.clusters[cluster1.id].representatives = [
        SimpleNamespace(
            id=str(uuid.uuid4()),
            identity_id=representative_id,
            media_id="101",
            is_user_selected=True,
        )
    ]
    latest_job = Job(
        id=str(uuid.uuid4()),
        type=JobType.CLUSTERING,
        tenant_id=tenant_id,
        status=JobStatus.COMPLETED,
        progress_completed=2,
        progress_total=2,
        payload={"snapshot_version": 99, "source_job_id": str(uuid.uuid4())},
    )
    latest_job.message = "Clustering complete"
    fake_job_service.repository.jobs[latest_job.id] = latest_job

    resp = api_client.get(f"/recognition/tenants/{tenant_id}/clusters/snapshot")

    assert resp.status_code == 200
    body = resp.json()

    # Verify top-level structure
    assert "tenant_id" in body
    assert body["tenant_id"] == tenant_id
    assert "snapshot_version" in body
    assert isinstance(body["snapshot_version"], int)
    assert "snapshot_generation_id" in body
    assert isinstance(body["snapshot_generation_id"], str)
    assert uuid.UUID(body["snapshot_generation_id"])
    assert body["source_job_id"] == latest_job.id
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
    assert alice_cluster["representative_id"] == representative_id
    assert alice_cluster["is_pinned"] is True

    unlabeled_cluster = next((c for c in body["clusters"] if c["cluster_uuid"] == cluster2.id), None)
    assert unlabeled_cluster is not None
    assert "is_user_confirmed" in unlabeled_cluster
    assert "curation_state" in unlabeled_cluster
    assert "representative_id" in unlabeled_cluster
    assert "is_pinned" in unlabeled_cluster


def test_get_tenant_snapshot_prefers_pinned_representative_when_order_is_unsorted(
    api_client, tenant_id, fake_cluster_service, fake_cluster_repository
) -> None:
    cluster = seed_cluster(
        fake_cluster_service, tenant_id, label="Alice", fake_cluster_repository=fake_cluster_repository
    )
    unpinned_representative_id = str(uuid.uuid4())
    pinned_representative_id = str(uuid.uuid4())
    fake_cluster_repository.clusters[cluster.id].representatives = [
        SimpleNamespace(
            id=str(uuid.uuid4()),
            identity_id=unpinned_representative_id,
            media_id="101",
            is_user_selected=False,
        ),
        SimpleNamespace(
            id=str(uuid.uuid4()),
            identity_id=pinned_representative_id,
            media_id="202",
            is_user_selected=True,
        ),
    ]

    resp = api_client.get(f"/recognition/tenants/{tenant_id}/clusters/snapshot")

    assert resp.status_code == 200
    cluster_body = next(c for c in resp.json()["clusters"] if c["cluster_uuid"] == cluster.id)
    assert cluster_body["representative_id"] == pinned_representative_id
    assert cluster_body["representative_thumb_path"] == f"acx://cluster/{cluster.id}/media/202"
    assert cluster_body["is_pinned"] is True


def test_get_tenant_snapshot_includes_members(
    api_client, tenant_id, fake_cluster_service, fake_cluster_repository
) -> None:
    # Seed a cluster with identities (seeds both service and repository)
    cluster = seed_cluster(
        fake_cluster_service, tenant_id, label="Bob", fake_cluster_repository=fake_cluster_repository
    )
    identity_id = str(uuid.uuid4())
    fake_cluster_service.seed_identity_membership(identity_id, cluster.id)
    fake_cluster_repository.seed_member(tenant_id=tenant_id, cluster_id=cluster.id, identity_id=identity_id)

    resp = api_client.get(f"/recognition/tenants/{tenant_id}/clusters/snapshot")

    assert resp.status_code == 200
    body = resp.json()

    # Verify members exists
    assert "members" in body
    assert isinstance(body["members"], list)
    assert len(body["members"]) > 0
    member = body["members"][0]
    assert "identity_uuid" in member
    assert "cluster_uuid" in member
    assert "attachment_id" in member
    assert "similarity" in member
    assert "bbox" in member
    assert "image_width" in member
    assert "image_height" in member
    assert "thumb_path" in member

    bbox = member["bbox"]
    assert "x" in bbox
    assert "y" in bbox
    assert "width" in bbox
    assert "height" in bbox


def test_get_tenant_snapshot_includes_suggested_label_for_unlabeled_cluster(
    api_client, tenant_id, fake_cluster_service, fake_cluster_repository, monkeypatch
) -> None:
    from unittest.mock import AsyncMock

    from recognition.domain.suggestion import SuggestedLabel, SuggestedLabelSource

    cluster = seed_cluster(fake_cluster_service, tenant_id, label=None, fake_cluster_repository=fake_cluster_repository)
    # un-confirm so enrichment is attempted
    fake_cluster_repository.clusters[cluster.id].user_confirmed = False

    inferred = SuggestedLabel(
        label="Alice",
        source=SuggestedLabelSource.SIMILAR_CLUSTER,
        confidence=0.88,
        target_cluster_id="bbb-222",
    )
    monkeypatch.setattr(
        "recognition.interface_adapters.http.routers.clusters_snapshot.infer_suggested_label",
        AsyncMock(return_value=inferred),
    )

    resp = api_client.get(f"/recognition/tenants/{tenant_id}/clusters/snapshot")

    assert resp.status_code == 200
    clusters = resp.json()["clusters"]
    target = next(c for c in clusters if c["cluster_uuid"] == cluster.id)
    assert target["suggested_label"] == "Alice"
    assert target["suggested_label_source"] == "similar_cluster"
    assert target["suggested_label_confidence"] == pytest.approx(0.88, abs=1e-6)
    assert target["suggested_target_cluster_id"] == "bbb-222"


def test_get_tenant_snapshot_has_null_suggested_label_for_confirmed_cluster(
    api_client, tenant_id, fake_cluster_service, fake_cluster_repository, monkeypatch
) -> None:
    from unittest.mock import AsyncMock

    cluster = seed_cluster(
        fake_cluster_service, tenant_id, label="Alice", fake_cluster_repository=fake_cluster_repository
    )
    fake_cluster_repository.clusters[cluster.id].user_confirmed = True

    mock_infer = AsyncMock()
    monkeypatch.setattr(
        "recognition.interface_adapters.http.routers.clusters_snapshot.infer_suggested_label",
        mock_infer,
    )

    resp = api_client.get(f"/recognition/tenants/{tenant_id}/clusters/snapshot")

    assert resp.status_code == 200
    clusters = resp.json()["clusters"]
    target = next(c for c in clusters if c["cluster_uuid"] == cluster.id)
    # Confirmed clusters must never receive a suggested_label
    assert target["suggested_label"] is None
    mock_infer.assert_not_called()


def test_cluster_delta_includes_suggested_label_for_unlabeled_cluster(
    api_client, tenant_id, fake_cluster_service, fake_cluster_repository, monkeypatch
) -> None:
    from unittest.mock import AsyncMock

    from recognition.domain.suggestion import SuggestedLabel, SuggestedLabelSource

    cluster = seed_cluster(fake_cluster_service, tenant_id, label=None, fake_cluster_repository=fake_cluster_repository)
    fake_cluster_repository.clusters[cluster.id].user_confirmed = False
    snapshot_version = fake_cluster_repository._snapshot_version

    inferred = SuggestedLabel(
        label="Bob",
        source=SuggestedLabelSource.ROSTER,
        confidence=0.75,
        target_cluster_id=None,
    )
    monkeypatch.setattr(
        "recognition.interface_adapters.http.routers.clusters_snapshot.infer_suggested_label",
        AsyncMock(return_value=inferred),
    )

    async def _fake_get_delta(request_tenant_id: str, *, since_version: int):
        return (
            await fake_cluster_repository.get_clusters_by_ids(tenant_id, [cluster.id]),
            await fake_cluster_repository.get_members_by_cluster_ids(tenant_id, [cluster.id]),
            snapshot_version,
        )

    monkeypatch.setattr(fake_cluster_repository, "get_delta", _fake_get_delta)

    resp = api_client.get(
        f"/recognition/tenants/{tenant_id}/clusters/delta",
        params={"since_version": snapshot_version - 1},
    )

    assert resp.status_code == 200
    clusters = resp.json()["clusters"]
    assert len(clusters) == 1
    assert clusters[0]["suggested_label"] == "Bob"
    assert clusters[0]["suggested_label_source"] == "roster"
    assert clusters[0]["suggested_label_confidence"] == pytest.approx(0.75, abs=1e-6)
    assert clusters[0]["suggested_target_cluster_id"] is None
