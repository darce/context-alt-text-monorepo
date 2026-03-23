"""API contract tests for suggestion endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from recognition.domain.suggestion import SuggestedLabelSource
from recognition.infrastructure.repositories.merge_suggestion_repository import SqlAlchemyMergeSuggestionRepository
from recognition.interface_adapters.http.schemas.responses import ClusterResponse
from recognition.tests.api.conftest import FakeNameSuggestion, FakeSuggestion


def test_list_suggestions_empty_by_default(api_client, tenant_id) -> None:
    resp = api_client.get(
        f"/recognition/identities/{uuid.uuid4()}/suggestions",
        headers={"X-Tenant-ID": tenant_id},
    )

    assert resp.status_code == 200
    assert resp.json() == {"matches": []}


@pytest.mark.asyncio
async def test_top_level_suggestions_filter_by_min_confidence(api_client, tenant_id, fake_suggestion_service) -> None:
    high = await fake_suggestion_service.create(
        identity_id=str(uuid.uuid4()),
        cluster_id=str(uuid.uuid4()),
        confidence_score=0.94,
    )
    low = await fake_suggestion_service.create(
        identity_id=str(uuid.uuid4()),
        cluster_id=str(uuid.uuid4()),
        confidence_score=0.35,
    )

    resp = api_client.get(
        "/recognition/suggestions",
        headers={"X-Tenant-ID": tenant_id},
        params={"min_confidence": 0.8},
    )

    assert resp.status_code == 200
    ids = [item["id"] for item in resp.json()]
    assert ids == [high.id]
    assert low.id not in ids


@pytest.mark.asyncio
async def test_top_level_suggestions_apply_min_confidence_before_paging(
    api_client, tenant_id, fake_suggestion_service
) -> None:
    low = await fake_suggestion_service.create(
        identity_id=str(uuid.uuid4()),
        cluster_id=str(uuid.uuid4()),
        confidence_score=0.35,
    )
    high = await fake_suggestion_service.create(
        identity_id=str(uuid.uuid4()),
        cluster_id=str(uuid.uuid4()),
        confidence_score=0.94,
    )

    resp = api_client.get(
        "/recognition/suggestions",
        headers={"X-Tenant-ID": tenant_id},
        params={"min_confidence": 0.8, "limit": 1},
    )

    assert resp.status_code == 200
    ids = [item["id"] for item in resp.json()]
    assert ids == [high.id]
    assert low.id not in ids


@pytest.mark.asyncio
async def test_list_suggestions_filters_by_min_confidence(
    api_client, tenant_id, fake_suggestion_service, fake_cluster_service, fake_cluster_repository
) -> None:
    identity_id = str(uuid.uuid4())
    high_cluster_id = str(uuid.uuid4())
    low_cluster_id = str(uuid.uuid4())
    for cluster_id, label in [(high_cluster_id, "Person High"), (low_cluster_id, "Person Low")]:
        fake_cluster_service.clusters.append(
            ClusterResponse(
                id=cluster_id,
                tenant_id=tenant_id,
                label=label,
                is_labeled=True,
                is_auto_label=False,
                identity_count=1,
                representatives=[],
            )
        )
        fake_cluster_repository.seed(cluster_id, tenant_id=tenant_id, label=label, identity_count=1)

    high = await fake_suggestion_service.create(identity_id=identity_id, cluster_id=high_cluster_id)
    low = await fake_suggestion_service.create(identity_id=identity_id, cluster_id=low_cluster_id)
    high.confidence_score = 0.91
    low.confidence_score = 0.42

    resp = api_client.get(
        f"/recognition/identities/{identity_id}/suggestions",
        headers={"X-Tenant-ID": tenant_id},
        params={"min_confidence": 0.8},
    )

    assert resp.status_code == 200
    matches = resp.json()["matches"]
    assert [item["cluster_id"] for item in matches] == [high_cluster_id]


@pytest.mark.asyncio
async def test_merge_suggestions_apply_min_confidence_before_paging(api_client, tenant_id, monkeypatch) -> None:
    low = SimpleNamespace(
        id=str(uuid.uuid4()),
        cluster_a_id=str(uuid.uuid4()),
        cluster_b_id=str(uuid.uuid4()),
        similarity=0.42,
        status="pending",
        confidence_score=0.31,
        cluster_a_label="Low A",
        cluster_b_label="Low B",
        cluster_a_identity_count=1,
        cluster_b_identity_count=1,
        cluster_a_representative_media_id=None,
        cluster_a_representative_media_url=None,
        cluster_a_representative_bbox=None,
        cluster_b_representative_media_id=None,
        cluster_b_representative_media_url=None,
        cluster_b_representative_bbox=None,
    )
    high = SimpleNamespace(
        id=str(uuid.uuid4()),
        cluster_a_id=str(uuid.uuid4()),
        cluster_b_id=str(uuid.uuid4()),
        similarity=0.91,
        status="pending",
        confidence_score=0.96,
        cluster_a_label="High A",
        cluster_b_label="High B",
        cluster_a_identity_count=3,
        cluster_b_identity_count=4,
        cluster_a_representative_media_id=None,
        cluster_a_representative_media_url=None,
        cluster_a_representative_bbox=None,
        cluster_b_representative_media_id=None,
        cluster_b_representative_media_url=None,
        cluster_b_representative_bbox=None,
    )
    rows = [low, high]

    async def fake_list_pending_with_details(self, tenant_id: str, limit: int, offset: int):  # noqa: ANN001
        assert tenant_id == tenant_id_fixture
        return rows[offset : offset + limit]

    tenant_id_fixture = tenant_id
    monkeypatch.setattr(
        SqlAlchemyMergeSuggestionRepository, "list_pending_with_details", fake_list_pending_with_details
    )

    resp = api_client.get(
        "/recognition/suggestions/merge",
        headers={"X-Tenant-ID": tenant_id},
        params={"min_confidence": 0.8, "limit": 1},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert [item["id"] for item in body] == [high.id]
    assert low.id not in [item["id"] for item in body]


@pytest.mark.asyncio
async def test_name_suggestions_apply_min_confidence_before_paging(
    api_client, tenant_id, fake_suggestion_extension_service
) -> None:
    low = FakeNameSuggestion(
        cluster_id=str(uuid.uuid4()),
        suggested_name="Low Score",
        source="identity",
        confidence_score=0.41,
    )
    medium = FakeNameSuggestion(
        cluster_id=str(uuid.uuid4()),
        suggested_name="Medium Score",
        source="roster",
        confidence_score=0.82,
    )
    high = FakeNameSuggestion(
        cluster_id=str(uuid.uuid4()),
        suggested_name="High Score",
        source="similar_cluster",
        confidence_score=0.94,
    )
    fake_suggestion_extension_service.name_suggestions[low.id] = low
    fake_suggestion_extension_service.name_suggestions[medium.id] = medium
    fake_suggestion_extension_service.name_suggestions[high.id] = high

    resp = api_client.get(
        "/recognition/suggestions/name",
        headers={"X-Tenant-ID": tenant_id},
        params={"min_confidence": 0.8, "limit": 1, "offset": 1},
    )

    assert resp.status_code == 200
    assert [item["id"] for item in resp.json()] == [medium.id]


@pytest.mark.asyncio
@pytest.mark.parametrize("suggestion_type", ["assignment", "merge"])
async def test_bulk_accept_endpoint_skips_expired_pending_suggestions(
    api_client, tenant_id, fake_suggestion_service, suggestion_type: str
) -> None:
    active = await fake_suggestion_service.create(
        identity_id=str(uuid.uuid4()),
        cluster_id=str(uuid.uuid4()),
        confidence_score=0.95,
        expires_at=datetime.now(tz=UTC) + timedelta(hours=1),
    )
    expired = await fake_suggestion_service.create(
        identity_id=str(uuid.uuid4()),
        cluster_id=str(uuid.uuid4()),
        confidence_score=0.97,
        expires_at=datetime.now(tz=UTC) - timedelta(minutes=1),
    )

    resp = api_client.post(
        "/recognition/suggestions/bulk-accept",
        headers={"X-Tenant-ID": tenant_id},
        json={"tenant_id": tenant_id, "suggestion_type": suggestion_type, "min_confidence": 0.8},
    )

    assert resp.status_code == 200
    assert resp.json() == {"accepted_count": 1, "skipped_count": 1}
    assert isinstance(fake_suggestion_service.suggestions[active.id], FakeSuggestion)
    assert fake_suggestion_service.suggestions[active.id].status.value == "accepted"
    assert fake_suggestion_service.suggestions[expired.id].status.value == "pending"


@pytest.mark.asyncio
async def test_suggestion_response_has_suggested_label_fields(
    api_client, tenant_id, fake_suggestion_service, fake_cluster_service
) -> None:
    """Verify that suggestion response includes new suggested_label fields."""
    identity_id = str(uuid.uuid4())
    cluster_id = str(uuid.uuid4())

    # Create a cluster
    fake_cluster_service.clusters.append(
        ClusterResponse(
            id=cluster_id,
            tenant_id=tenant_id,
            label=None,  # Unlabeled
            is_labeled=False,
            is_auto_label=False,
            identity_count=1,
            representatives=[],
        )
    )

    # Create suggestion
    suggestion = await fake_suggestion_service.create(identity_id=identity_id, cluster_id=cluster_id)

    # Mocking suggestion details from the service to include suggested_label
    # Since we are using a fake service in API tests, we might need to update the fake service to support this
    # OR we rely on the fact that the API router just iterates what the service returns.
    # The `fake_suggestion_service` likely returns `AssignmentSuggestion` domain objects.
    # We need to verify that the router handles the mapping if the service returns fields.
    # However, `AssignmentSuggestion` domain object was updated to include these fields.
    # So we can set them on the suggestion object.

    suggestion.suggested_label = "Inferred Label"
    suggestion.suggested_label_source = SuggestedLabelSource.SIMILAR_CLUSTER
    suggestion.suggested_label_confidence = 0.88

    # The list endpoint calls suggestion_service.list_pending
    resp = api_client.get(
        "/recognition/suggestions",
        headers={"X-Tenant-ID": tenant_id},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    found = next((s for s in data if s["id"] == suggestion.id), None)
    assert found is not None
    assert found["suggested_label"] == "Inferred Label"
    assert found["suggested_label_source"] == "similar_cluster"
    assert found["suggested_label_confidence"] == 0.88


@pytest.mark.asyncio
async def test_accept_and_reject_suggestion(
    api_client, tenant_id, fake_suggestion_service, fake_cluster_service, fake_suggestion_refresh_service
) -> None:
    identity_id = str(uuid.uuid4())
    cluster_id = str(uuid.uuid4())
    fake_cluster_service.clusters.append(
        ClusterResponse(
            id=cluster_id,
            tenant_id=tenant_id,
            label="Person A",
            is_labeled=True,
            is_auto_label=False,
            identity_count=1,
            representatives=[],
        )
    )
    suggestion = await fake_suggestion_service.create(identity_id=identity_id, cluster_id=cluster_id)

    accept_resp = api_client.post(
        f"/recognition/suggestions/{suggestion.id}/accept",
        headers={"X-Tenant-ID": tenant_id},
        json={"tenant_id": tenant_id},
    )
    assert accept_resp.status_code == 200
    assert accept_resp.json()["status"] == "accepted"
    assert fake_suggestion_refresh_service.refresh_calls == []

    second_cluster_id = str(uuid.uuid4())
    fake_cluster_service.clusters.append(
        ClusterResponse(
            id=second_cluster_id,
            tenant_id=tenant_id,
            label="Person B",
            is_labeled=True,
            is_auto_label=False,
            identity_count=1,
            representatives=[],
        )
    )
    second = await fake_suggestion_service.create(
        identity_id=str(uuid.uuid4()),
        cluster_id=second_cluster_id,
    )
    reject_resp = api_client.post(
        f"/recognition/suggestions/{second.id}/reject",
        headers={"X-Tenant-ID": tenant_id},
        json={"tenant_id": tenant_id},
    )
    assert reject_resp.status_code == 200
    assert reject_resp.json()["status"] == "rejected"


def test_name_suggestion_list_accept_reject_and_bulk_accept(
    api_client, tenant_id, fake_suggestion_extension_service
) -> None:
    high = FakeNameSuggestion(
        cluster_id=str(uuid.uuid4()),
        suggested_name="Avery Rhodes",
        source="identity",
        confidence_score=0.93,
    )
    medium = FakeNameSuggestion(
        cluster_id=str(uuid.uuid4()),
        suggested_name="Jordan Lee",
        source="roster",
        confidence_score=0.81,
    )
    low = FakeNameSuggestion(
        cluster_id=str(uuid.uuid4()),
        suggested_name="Low Score",
        source="similar_cluster",
        confidence_score=0.41,
    )
    fake_suggestion_extension_service.name_suggestions[high.id] = high
    fake_suggestion_extension_service.name_suggestions[medium.id] = medium
    fake_suggestion_extension_service.name_suggestions[low.id] = low

    list_resp = api_client.get(
        "/recognition/suggestions/name",
        headers={"X-Tenant-ID": tenant_id},
        params={"min_confidence": 0.8},
    )
    assert list_resp.status_code == 200
    assert [item["id"] for item in list_resp.json()] == [high.id, medium.id]

    accept_resp = api_client.post(
        f"/recognition/suggestions/name/{high.id}/accept",
        headers={"X-Tenant-ID": tenant_id},
        json={"tenant_id": tenant_id},
    )
    assert accept_resp.status_code == 200
    assert accept_resp.json()["status"] == "accepted"

    reject_resp = api_client.post(
        f"/recognition/suggestions/name/{medium.id}/reject",
        headers={"X-Tenant-ID": tenant_id},
        json={"tenant_id": tenant_id},
    )
    assert reject_resp.status_code == 200
    assert reject_resp.json()["status"] == "rejected"

    bulk_resp = api_client.post(
        "/recognition/suggestions/bulk-accept",
        headers={"X-Tenant-ID": tenant_id},
        json={"tenant_id": tenant_id, "suggestion_type": "name", "min_confidence": 0.4},
    )
    assert bulk_resp.status_code == 200
    assert bulk_resp.json() == {"accepted_count": 1, "skipped_count": 0}
    assert fake_suggestion_extension_service.name_suggestions[low.id].status.value == "accepted"


def test_accept_name_suggestion_returns_404_when_not_found(
    api_client, tenant_id, fake_suggestion_extension_service
) -> None:
    missing_id = str(uuid.uuid4())
    resp = api_client.post(
        f"/recognition/suggestions/name/{missing_id}/accept",
        headers={"X-Tenant-ID": tenant_id},
        json={"tenant_id": tenant_id},
    )
    assert resp.status_code == 404


def test_reject_name_suggestion_returns_404_when_not_found(
    api_client, tenant_id, fake_suggestion_extension_service
) -> None:
    missing_id = str(uuid.uuid4())
    resp = api_client.post(
        f"/recognition/suggestions/name/{missing_id}/reject",
        headers={"X-Tenant-ID": tenant_id},
        json={"tenant_id": tenant_id},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_accept_rejects_other_pending_suggestions(
    api_client, tenant_id, fake_suggestion_service, fake_cluster_service
) -> None:
    identity_id = str(uuid.uuid4())
    accepted_cluster_id = str(uuid.uuid4())
    other_cluster_id = str(uuid.uuid4())
    for cluster_id, label in [(accepted_cluster_id, "Person A"), (other_cluster_id, "Person B")]:
        fake_cluster_service.clusters.append(
            ClusterResponse(
                id=cluster_id,
                tenant_id=tenant_id,
                label=label,
                is_labeled=True,
                is_auto_label=False,
                identity_count=1,
                representatives=[],
            )
        )
    accepted = await fake_suggestion_service.create(identity_id=identity_id, cluster_id=accepted_cluster_id)
    other = await fake_suggestion_service.create(identity_id=identity_id, cluster_id=other_cluster_id)

    resp = api_client.post(
        f"/recognition/suggestions/{accepted.id}/accept",
        headers={"X-Tenant-ID": tenant_id},
        json={"tenant_id": tenant_id},
    )

    assert resp.status_code == 200
    assert fake_suggestion_service.suggestions[other.id].status.value == "rejected"
