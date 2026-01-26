"""API contract tests for WordPress integration endpoints."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from recognition.domain.suggestion import SuggestionDetails
from recognition.tests.api.conftest import FakeMediaIdentityService, seed_cluster


def test_analyze_accepts_media_items(api_client, tenant_id):
    payload = {
        "tenant_id": tenant_id,
        "media_items": [{"media_id": 123, "media_url": "http://example.test/img.jpg"}],
    }

    resp = api_client.post("/recognition/analyze", json=payload)

    assert resp.status_code == 202


def test_top_level_suggestions(api_client, tenant_id, fake_suggestion_service, fake_cluster_service):
    cluster = seed_cluster(fake_cluster_service, tenant_id)
    fake_suggestion_service.suggestions["sugg-1"] = SuggestionDetails(
        id="sugg-1",
        identity_id="identity-1",
        cluster_id=cluster.id,
        representative_similarity=0.9,
        member_similarity=0.9,
        status="pending",
    )
    resp = api_client.get(
        "/recognition/suggestions",
        headers={"X-Tenant-ID": tenant_id},
    )
    assert resp.status_code == 200


def test_media_identities_endpoint(api_client, tenant_id, fake_media_identity_service: FakeMediaIdentityService):
    fake_media_identity_service.add_identity(media_id=111, identity_id="identity-1", cluster_id="cluster-1")

    resp = api_client.get(
        "/recognition/media/identities",
        headers={"X-Tenant-ID": tenant_id},
        params=[("media_ids", 111), ("include_debug", "true")],
    )

    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert body
    assert body[0]["debug_metrics"]["representative_count"] == 1
    assert "pose_buckets" in body[0]["debug_metrics"]
