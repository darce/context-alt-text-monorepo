"""Integration tests for Curate Top Clusters endpoint."""

import uuid
from datetime import UTC, datetime

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from recognition.domain.representative import ClusterRepresentative
from recognition.interface_adapters.http import deps as dependencies
from recognition.interface_adapters.http import router as recognition_router
from recognition.tests.api.conftest import FakeSession, seed_cluster


@pytest.mark.asyncio
async def test_get_top_unlabeled_returns_clusters(
    api_client,
    tenant_id,
    fake_cluster_service,
    fake_cluster_repository,
) -> None:
    """Endpoint should return unlabeled clusters ordered by identity count."""
    # Seed some clusters
    # 1. Unlabeled (identity_count=10)
    c1 = seed_cluster(fake_cluster_service, tenant_id, label=None)
    c1.identity_count = 10

    # 2. Labeled (should be excluded)
    c2 = seed_cluster(fake_cluster_service, tenant_id, label="Already Labeled")
    c2.identity_count = 20

    # 3. Unlabeled (identity_count=5)
    c3 = seed_cluster(fake_cluster_service, tenant_id, label=None)
    c3.identity_count = 5

    # Target the fake repository directly
    fake_cluster_repository.seed(c1.id, label=None, identity_count=10)
    fake_cluster_repository.seed(c2.id, label="Already Labeled", identity_count=20)
    fake_cluster_repository.seed(c3.id, label=None, identity_count=5)

    resp = api_client.get(
        "/recognition/clusters/top-unlabeled",
        params={"tenant_id": tenant_id, "limit": 2},
        headers={"X-Tenant-ID": tenant_id},
    )

    assert resp.status_code == 200
    body = resp.json()

    assert len(body) == 2
    assert body[0]["id"] == c1.id
    assert body[0]["identity_count"] == 10
    assert body[1]["id"] == c3.id
    assert body[1]["identity_count"] == 5
    assert not any(c["label"] for c in body)


def test_get_top_unlabeled_uses_authenticated_tenant_claim(
    monkeypatch,
    tenant_id: str,
    fake_cluster_repository,
) -> None:
    captured: dict[str, str] = {}
    monkeypatch.setenv("RECOGNITION_AUTH_ENABLED", "1")
    app = FastAPI()
    app.include_router(recognition_router, prefix="/recognition")

    async def _session_dep():
        yield FakeSession()

    async def _cluster_repo_dep(session=None):  # noqa: ANN001
        return fake_cluster_repository

    app.dependency_overrides[dependencies.get_session] = _session_dep
    app.dependency_overrides[dependencies.get_optional_session] = _session_dep
    app.dependency_overrides[dependencies.get_cluster_repository] = _cluster_repo_dep

    from recognition.interface_adapters.http.deps import auth

    async def _fake_lookup(api_key, settings, session):  # noqa: ANN001
        assert api_key == "good-key"
        return tenant_id, "key-1", "enterprise", False

    monkeypatch.setattr(auth, "_lookup_api_key", _fake_lookup)

    cluster_id = str(uuid.uuid4())
    fake_cluster_repository.seed(cluster_id, label=None, identity_count=3)
    original_get_top_unlabeled = fake_cluster_repository.get_top_unlabeled

    async def _capturing_get_top_unlabeled(resolved_tenant_id: str, *args, **kwargs):  # noqa: ANN001
        captured["tenant_id"] = resolved_tenant_id
        return await original_get_top_unlabeled(resolved_tenant_id, *args, **kwargs)

    fake_cluster_repository.get_top_unlabeled = _capturing_get_top_unlabeled

    client = TestClient(app)
    resp = client.get("/recognition/clusters/top-unlabeled", headers={"Authorization": "Bearer good-key"})

    assert resp.status_code == 200
    assert captured["tenant_id"] == tenant_id
    assert [cluster["id"] for cluster in resp.json()] == [cluster_id]


@pytest.mark.asyncio
async def test_get_top_unlabeled_includes_representative_crop_fields(
    api_client: TestClient,
    tenant_id: str,
    fake_cluster_repository,
) -> None:
    cluster_id = str(uuid.uuid4())
    fake_cluster_repository.seed(cluster_id, label=None, identity_count=3)

    fake_cluster_repository.clusters[cluster_id].representatives = [
        ClusterRepresentative(
            id=str(uuid.uuid4()),
            cluster_id=cluster_id,
            identity_id=str(uuid.uuid4()),
            embedding=np.zeros(512, dtype=np.float32),
            created_at=datetime.now(tz=UTC),
            media_id=101,
            media_url="http://example.test/media/101.jpg",
            bbox_x=12,
            bbox_y=8,
            bbox_width=40,
            bbox_height=30,
            is_user_selected=False,
        )
    ]

    resp = api_client.get(
        "/recognition/clusters/top-unlabeled",
        params={"tenant_id": tenant_id, "limit": 1},
        headers={"X-Tenant-ID": tenant_id},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    rep = body[0]["representatives"][0]
    assert rep["media_url"] == "http://example.test/media/101.jpg"
    assert rep["bbox"] == {"x": 12, "y": 8, "width": 40, "height": 30}


@pytest.mark.asyncio
async def test_get_top_unlabeled_includes_face_thumb_url_for_blob_backed_representative(
    api_client: TestClient,
    tenant_id: str,
    fake_cluster_repository,
) -> None:
    cluster_id = str(uuid.uuid4())
    fake_cluster_repository.seed(cluster_id, label=None, identity_count=3)

    fake_cluster_repository.clusters[cluster_id].representatives = [
        ClusterRepresentative(
            id=str(uuid.uuid4()),
            cluster_id=cluster_id,
            identity_id=str(uuid.uuid4()),
            embedding=np.zeros(512, dtype=np.float32),
            created_at=datetime.now(tz=UTC),
            media_id=101,
            media_url=f"file:///tmp/blob-root/{tenant_id}/job-42/101.bin",
            bbox_x=12,
            bbox_y=8,
            bbox_width=40,
            bbox_height=30,
            is_user_selected=False,
        )
    ]

    resp = api_client.get(
        "/recognition/clusters/top-unlabeled",
        params={"tenant_id": tenant_id, "limit": 1},
        headers={"X-Tenant-ID": tenant_id},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    rep = body[0]["representatives"][0]
    assert rep["thumb_url"] == "/recognition/face-thumbs/job-42/101?x=12&y=8&width=40&height=30"


@pytest.mark.asyncio
async def test_get_top_unlabeled_propagates_user_selected_representative_pin(
    api_client: TestClient,
    tenant_id: str,
    fake_cluster_repository,
) -> None:
    """Shared builder must wire is_user_selected=true for pinned reps (E21-17-R1-PY11-2)."""
    cluster_id = str(uuid.uuid4())
    fake_cluster_repository.seed(cluster_id, label=None, identity_count=3)
    rep_id = str(uuid.uuid4())
    fake_cluster_repository.clusters[cluster_id].representatives = [
        ClusterRepresentative(
            id=rep_id,
            cluster_id=cluster_id,
            identity_id=str(uuid.uuid4()),
            embedding=np.zeros(512, dtype=np.float32),
            created_at=datetime.now(tz=UTC),
            media_id=303,
            media_url="http://example.test/media/303.jpg",
            bbox_x=4,
            bbox_y=5,
            bbox_width=20,
            bbox_height=25,
            is_user_selected=True,
        )
    ]

    resp = api_client.get(
        "/recognition/clusters/top-unlabeled",
        params={"tenant_id": tenant_id, "limit": 1},
        headers={"X-Tenant-ID": tenant_id},
    )

    assert resp.status_code == 200
    rep = resp.json()[0]["representatives"][0]
    assert rep["id"] == rep_id
    assert rep["is_user_selected"] is True
    assert "is_pinned" not in rep


@pytest.mark.asyncio
async def test_get_top_unlabeled_null_media_id_is_not_fabricated_to_zero(
    api_client: TestClient,
    tenant_id: str,
    fake_cluster_repository,
) -> None:
    """Shared builder must not invent media_id=0 when domain media_id is None (E21-17-R1-PY11-1)."""
    cluster_id = str(uuid.uuid4())
    fake_cluster_repository.seed(cluster_id, label=None, identity_count=2)
    fake_cluster_repository.clusters[cluster_id].representatives = [
        ClusterRepresentative(
            id=str(uuid.uuid4()),
            cluster_id=cluster_id,
            identity_id=str(uuid.uuid4()),
            embedding=np.zeros(512, dtype=np.float32),
            created_at=datetime.now(tz=UTC),
            media_id=None,
            media_url=None,
            bbox_x=None,
            bbox_y=None,
            bbox_width=None,
            bbox_height=None,
            is_user_selected=False,
        )
    ]

    resp = api_client.get(
        "/recognition/clusters/top-unlabeled",
        params={"tenant_id": tenant_id, "limit": 1},
        headers={"X-Tenant-ID": tenant_id},
    )

    assert resp.status_code == 200
    rep = resp.json()[0]["representatives"][0]
    assert rep["media_id"] is None
    assert rep["media_id"] != 0
    assert rep["media_id"] != "0"


@pytest.mark.asyncio
async def test_get_top_unlabeled_includes_suggested_label_fields(
    api_client: TestClient,
    tenant_id: str,
    fake_cluster_repository,
) -> None:
    cluster_id = str(uuid.uuid4())
    fake_cluster_repository.seed(cluster_id, label=None, identity_count=4)
    cluster = fake_cluster_repository.clusters[cluster_id]
    cluster.suggested_label = "Pewter Hollow"
    cluster.suggested_label_source = "similar_cluster"
    cluster.suggested_label_confidence = 0.93
    cluster.suggested_target_cluster_id = str(uuid.uuid4())

    resp = api_client.get(
        "/recognition/clusters/top-unlabeled",
        params={"tenant_id": tenant_id, "limit": 1},
        headers={"X-Tenant-ID": tenant_id},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["suggested_label"] == "Pewter Hollow"
    assert body[0]["suggested_label_source"] == "similar_cluster"
    assert body[0]["suggested_label_confidence"] == 0.93
    assert body[0]["suggested_target_cluster_id"] == cluster.suggested_target_cluster_id


@pytest.mark.asyncio
async def test_dismissed_clusters_excluded_from_top_unlabeled(
    api_client: TestClient,
    tenant_id: str,
    fake_cluster_repository,
) -> None:
    """Dismissed clusters should not appear in the top-unlabeled listing."""
    fake_cluster_repository.seed("c-big", label=None, identity_count=20)
    fake_cluster_repository.seed("c-small", label=None, identity_count=5)

    # Dismiss the big cluster
    fake_cluster_repository.clusters["c-big"].dismissed_at = datetime.now(tz=UTC)

    resp = api_client.get(
        "/recognition/clusters/top-unlabeled",
        params={"tenant_id": tenant_id, "limit": 10},
        headers={"X-Tenant-ID": tenant_id},
    )

    assert resp.status_code == 200
    body = resp.json()
    ids = [c["id"] for c in body]
    assert "c-big" not in ids
    assert "c-small" in ids


@pytest.mark.asyncio
async def test_dismiss_cluster_endpoint(
    api_client: TestClient,
    tenant_id: str,
    fake_cluster_repository,
) -> None:
    """POST /clusters/{id}/dismiss should mark cluster as dismissed."""
    cluster_id = str(uuid.uuid4())
    fake_cluster_repository.seed(cluster_id, label=None, identity_count=5)

    resp = api_client.post(
        f"/recognition/clusters/{cluster_id}/dismiss",
        headers={"X-Tenant-ID": tenant_id},
    )

    assert resp.status_code == 204
    assert fake_cluster_repository.clusters[cluster_id].dismissed_at is not None


@pytest.mark.asyncio
async def test_dismiss_cluster_not_found(
    api_client: TestClient,
    tenant_id: str,
) -> None:
    """POST /clusters/{id}/dismiss for unknown ID should return 404."""
    resp = api_client.post(
        f"/recognition/clusters/{uuid.uuid4()}/dismiss",
        headers={"X-Tenant-ID": tenant_id},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_undismiss_cluster_endpoint(
    api_client: TestClient,
    tenant_id: str,
    fake_cluster_repository,
) -> None:
    """DELETE /clusters/{id}/dismiss should clear the dismissed flag."""
    cluster_id = str(uuid.uuid4())
    fake_cluster_repository.seed(cluster_id, label=None, identity_count=5)
    fake_cluster_repository.clusters[cluster_id].dismissed_at = datetime.now(tz=UTC)

    resp = api_client.delete(
        f"/recognition/clusters/{cluster_id}/dismiss",
        headers={"X-Tenant-ID": tenant_id},
    )

    assert resp.status_code == 204
    assert fake_cluster_repository.clusters[cluster_id].dismissed_at is None
