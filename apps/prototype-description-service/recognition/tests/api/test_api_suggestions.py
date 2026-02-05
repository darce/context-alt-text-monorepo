"""API contract tests for suggestion endpoints."""

from __future__ import annotations

import uuid

import pytest

from recognition.domain.suggestion import SuggestedLabelSource
from recognition.interface_adapters.http.schemas.responses import ClusterResponse


def test_list_suggestions_empty_by_default(api_client, tenant_id) -> None:
    resp = api_client.get(
        f"/recognition/identities/{uuid.uuid4()}/suggestions",
        headers={"X-Tenant-ID": tenant_id},
    )

    assert resp.status_code == 200
    assert resp.status_code == 200
    assert resp.json() == {"matches": []}


@pytest.mark.asyncio
@pytest.mark.skip("scaffold")
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
    api_client, tenant_id, fake_suggestion_service, fake_cluster_service
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
