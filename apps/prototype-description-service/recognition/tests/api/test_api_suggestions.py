"""API contract tests for suggestion endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np
import pytest

from recognition.domain.cluster import ReservedClusterLabelError
from recognition.domain.representative import ClusterRepresentative
from recognition.domain.suggestion import SuggestedLabelSource
from recognition.infrastructure.repositories.merge_suggestion_repository import SqlAlchemyMergeSuggestionRepository
from recognition.interface_adapters.http import deps as dependencies
from recognition.interface_adapters.http.exception_handlers import register_exception_handlers
from recognition.interface_adapters.http.schemas.responses import ClusterResponse
from recognition.tests.api.conftest import FakeNameSuggestion, FakeSession, FakeSuggestion


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
async def test_bulk_accept_assignment_skips_expired_and_performs_assignment(
    api_client, tenant_id, fake_suggestion_service, fake_cluster_service
) -> None:
    cluster_id = str(uuid.uuid4())
    fake_cluster_service.clusters.append(
        ClusterResponse(
            id=cluster_id,
            tenant_id=tenant_id,
            label="target",
            is_labeled=True,
            is_auto_label=False,
            identity_count=1,
            representatives=[],
        )
    )
    active = await fake_suggestion_service.create(
        identity_id=str(uuid.uuid4()),
        cluster_id=cluster_id,
        confidence_score=0.95,
        expires_at=datetime.now(tz=UTC) + timedelta(hours=1),
    )
    expired = await fake_suggestion_service.create(
        identity_id=str(uuid.uuid4()),
        cluster_id=cluster_id,
        confidence_score=0.97,
        expires_at=datetime.now(tz=UTC) - timedelta(minutes=1),
    )

    resp = api_client.post(
        "/recognition/suggestions/bulk-accept",
        headers={"X-Tenant-ID": tenant_id},
        json={"tenant_id": tenant_id, "suggestion_type": "assignment", "min_confidence": 0.8},
    )

    assert resp.status_code == 200
    assert resp.json() == {"accepted_count": 1, "skipped_count": 0}
    assert fake_suggestion_service.suggestions[active.id].status.value == "accepted"
    assert fake_suggestion_service.suggestions[expired.id].status.value == "pending"
    assert fake_cluster_service.identity_cluster_map[active.identity_id] == cluster_id


@pytest.mark.asyncio
async def test_bulk_accept_merge_skips_expired_and_performs_merge(
    api_client, tenant_id, fake_suggestion_extension_service, fake_cluster_service, fake_cluster_repository
) -> None:
    cluster_a_id = str(uuid.uuid4())
    cluster_b_id = str(uuid.uuid4())
    fake_cluster_service.clusters.extend(
        [
            ClusterResponse(
                id=cluster_a_id,
                tenant_id=tenant_id,
                label=None,
                is_labeled=False,
                is_auto_label=False,
                identity_count=2,
                representatives=[],
            ),
            ClusterResponse(
                id=cluster_b_id,
                tenant_id=tenant_id,
                label="labeled_cluster",
                is_labeled=True,
                is_auto_label=False,
                identity_count=1,
                representatives=[],
            ),
        ]
    )
    fake_cluster_repository.seed(cluster_a_id, tenant_id, label=None, identity_count=2)
    fake_cluster_repository.seed(cluster_b_id, tenant_id, label="labeled_cluster", identity_count=1)
    fake_suggestion_extension_service.create_merge_suggestion(
        cluster_a_id=cluster_a_id,
        cluster_b_id=cluster_b_id,
        confidence_score=0.95,
        expires_at=datetime.now(tz=UTC) + timedelta(hours=1),
    )
    fake_suggestion_extension_service.create_merge_suggestion(
        cluster_a_id=str(uuid.uuid4()),
        cluster_b_id=str(uuid.uuid4()),
        confidence_score=0.97,
        expires_at=datetime.now(tz=UTC) - timedelta(minutes=1),
    )

    resp = api_client.post(
        "/recognition/suggestions/bulk-accept",
        headers={"X-Tenant-ID": tenant_id},
        json={"tenant_id": tenant_id, "suggestion_type": "merge", "min_confidence": 0.8},
    )

    assert resp.status_code == 200
    assert resp.json() == {"accepted_count": 1, "skipped_count": 0}
    merge_calls = [c for c in fake_cluster_service.calls if c.get("method") == "merge_cluster"]
    assert len(merge_calls) == 1


@pytest.mark.asyncio
async def test_accept_merge_suggestion_both_placeholder_labels_succeeds(
    api_client,
    tenant_id,
    fake_cluster_service,
    fake_cluster_repository,
    monkeypatch,
) -> None:
    """E21-17-R1-PY47-3 / R2-PY-N1: placeholder merge must not 400 or stamp confirmed."""
    from recognition.domain.suggestion import SuggestionStatus

    cluster_a_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    cluster_b_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    suggestion_id = str(uuid.uuid4())

    fake_cluster_repository.seed(cluster_a_id, tenant_id, label="cluster-aaa", identity_count=5, user_confirmed=False)
    fake_cluster_repository.seed(cluster_b_id, tenant_id, label="cluster-bbb", identity_count=2, user_confirmed=False)
    fake_cluster_service.clusters.extend(
        [
            ClusterResponse(
                id=cluster_a_id,
                tenant_id=tenant_id,
                label="cluster-aaa",
                is_labeled=True,
                is_auto_label=True,
                identity_count=5,
                representatives=[],
            ),
            ClusterResponse(
                id=cluster_b_id,
                tenant_id=tenant_id,
                label="cluster-bbb",
                is_labeled=True,
                is_auto_label=True,
                identity_count=2,
                representatives=[],
            ),
        ]
    )

    suggestion = SimpleNamespace(
        id=suggestion_id,
        cluster_a_id=cluster_a_id,
        cluster_b_id=cluster_b_id,
        similarity=0.91,
        status=SuggestionStatus.PENDING,
        confidence_score=0.91,
        expires_at=None,
        source_job_id=None,
    )

    async def fake_get_by_id(self, tenant_id_arg: str, sid: str):  # noqa: ANN001
        assert tenant_id_arg == tenant_id
        assert sid == suggestion_id
        return suggestion

    async def fake_delete_by_cluster(self, tenant_id_arg: str, cluster_id: str) -> int:  # noqa: ANN001
        return 0

    monkeypatch.setattr(SqlAlchemyMergeSuggestionRepository, "get_by_id", fake_get_by_id)
    monkeypatch.setattr(SqlAlchemyMergeSuggestionRepository, "delete_by_cluster", fake_delete_by_cluster)

    resp = api_client.post(
        f"/recognition/suggestions/merge/{suggestion_id}/accept",
        headers={"X-Tenant-ID": tenant_id},
        json={"tenant_id": tenant_id},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "accepted"
    assert body["target_cluster_id"] == cluster_a_id
    assert body["source_cluster_id"] == cluster_b_id
    merge_calls = [c for c in fake_cluster_service.calls if c["method"] == "merge_cluster"]
    assert merge_calls
    assert merge_calls[-1]["target_label"] is None
    survivor = next(c for c in fake_cluster_service.clusters if c.id == cluster_a_id)
    assert survivor.label == "cluster-aaa"
    # Fake must model user_confirmed so this assertion can catch R2-PY-N1-style stamps.
    assert fake_cluster_repository.clusters[cluster_a_id].user_confirmed is False


@pytest.mark.asyncio
async def test_accept_merge_suggestion_response_carries_source_and_target_ids(
    api_client,
    tenant_id,
    fake_cluster_service,
    fake_cluster_repository,
    monkeypatch,
) -> None:
    """E215-BR-02(a): accept RESPONSE must stamp source/target (endpoint-level pin).

    Red if accept_merge_suggestion reverts to ``_to_merge_response(suggestion)``
    without kwargs after a successful merge.
    """
    from recognition.domain.suggestion import SuggestionStatus

    cluster_a_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    cluster_b_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    suggestion_id = str(uuid.uuid4())

    # B has meaningful label + lower count; rank picks B as survivor, A as source.
    fake_cluster_repository.seed(cluster_a_id, tenant_id, label=None, identity_count=50)
    fake_cluster_repository.seed(cluster_b_id, tenant_id, label="Named Person", identity_count=2)
    fake_cluster_service.clusters.extend(
        [
            ClusterResponse(
                id=cluster_a_id,
                tenant_id=tenant_id,
                label=None,
                is_labeled=False,
                is_auto_label=False,
                identity_count=50,
                representatives=[],
            ),
            ClusterResponse(
                id=cluster_b_id,
                tenant_id=tenant_id,
                label="Named Person",
                is_labeled=True,
                is_auto_label=False,
                identity_count=2,
                representatives=[],
            ),
        ]
    )

    suggestion = SimpleNamespace(
        id=suggestion_id,
        cluster_a_id=cluster_a_id,
        cluster_b_id=cluster_b_id,
        similarity=0.91,
        status=SuggestionStatus.PENDING,
        confidence_score=0.91,
        expires_at=None,
        source_job_id=None,
    )

    async def fake_get_by_id(self, tenant_id_arg: str, sid: str):  # noqa: ANN001
        assert tenant_id_arg == tenant_id
        assert sid == suggestion_id
        return suggestion

    async def fake_delete_by_cluster(self, tenant_id_arg: str, cluster_id: str) -> int:  # noqa: ANN001
        return 0

    monkeypatch.setattr(SqlAlchemyMergeSuggestionRepository, "get_by_id", fake_get_by_id)
    monkeypatch.setattr(SqlAlchemyMergeSuggestionRepository, "delete_by_cluster", fake_delete_by_cluster)

    resp = api_client.post(
        f"/recognition/suggestions/merge/{suggestion_id}/accept",
        headers={"X-Tenant-ID": tenant_id},
        json={"tenant_id": tenant_id},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "accepted"
    # Authoritative pair must be present — red if accept drops kwargs.
    assert body.get("source_cluster_id") is not None
    assert body.get("target_cluster_id") is not None
    assert body["source_cluster_id"] != body["target_cluster_id"]
    assert {body["source_cluster_id"], body["target_cluster_id"]} == {cluster_a_id, cluster_b_id}
    # Label-bearing B is the survivor under default rank (user_confirmed=bool(label)).
    assert body["target_cluster_id"] == cluster_b_id
    assert body["source_cluster_id"] == cluster_a_id


@pytest.mark.asyncio
async def test_accept_merge_suggestion_accepted_replay_stamps_ids(
    api_client,
    tenant_id,
    fake_cluster_service,
    fake_cluster_repository,
    monkeypatch,
) -> None:
    """E215-BR-02(b): non-PENDING ACCEPTED replay stamps authoritative ids via existence."""
    from recognition.domain.suggestion import SuggestionStatus

    cluster_a_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    cluster_b_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    suggestion_id = str(uuid.uuid4())

    # Only survivor (B) remains — A was retired by a prior merge.
    fake_cluster_repository.seed(cluster_b_id, tenant_id, label="Bob", identity_count=52)
    suggestion = SimpleNamespace(
        id=suggestion_id,
        cluster_a_id=cluster_a_id,
        cluster_b_id=cluster_b_id,
        similarity=0.91,
        status=SuggestionStatus.ACCEPTED,
        confidence_score=0.91,
        expires_at=None,
        source_job_id=None,
    )

    async def fake_get_by_id(self, tenant_id_arg: str, sid: str):  # noqa: ANN001
        return suggestion

    monkeypatch.setattr(SqlAlchemyMergeSuggestionRepository, "get_by_id", fake_get_by_id)

    resp = api_client.post(
        f"/recognition/suggestions/merge/{suggestion_id}/accept",
        headers={"X-Tenant-ID": tenant_id},
        json={"tenant_id": tenant_id},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "accepted"
    assert body["source_cluster_id"] == cluster_a_id
    assert body["target_cluster_id"] == cluster_b_id


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


def test_name_suggestions_include_representative_preview_fields(
    api_client, tenant_id, fake_suggestion_extension_service
) -> None:
    cluster_id = str(uuid.uuid4())
    rep_id = str(uuid.uuid4())
    suggestion = FakeNameSuggestion(
        cluster_id=cluster_id,
        suggested_name="Avery Rhodes",
        source="identity",
        confidence_score=0.93,
    )
    suggestion.representatives = [
        ClusterRepresentative(
            id=rep_id,
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
    fake_suggestion_extension_service.name_suggestions[suggestion.id] = suggestion

    resp = api_client.get(
        "/recognition/suggestions/name",
        headers={"X-Tenant-ID": tenant_id},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    rep = body[0]["representatives"][0]
    assert rep["id"] == rep_id
    assert rep["media_id"] == "101"
    assert rep["media_url"] == "/recognition/blobs/job-42/101"
    assert rep["thumb_url"] == "/recognition/face-thumbs/job-42/101?x=12&y=8&width=40&height=30"
    assert rep["bbox"] == {"x": 12, "y": 8, "width": 40, "height": 30}

    accept_resp = api_client.post(
        f"/recognition/suggestions/name/{suggestion.id}/accept",
        headers={"X-Tenant-ID": tenant_id},
        json={"tenant_id": tenant_id},
    )
    assert accept_resp.status_code == 200
    accept_rep = accept_resp.json()["representatives"][0]
    assert accept_rep["id"] == rep_id
    assert accept_rep["bbox"] == {"x": 12, "y": 8, "width": 40, "height": 30}


def test_name_suggestions_without_representatives_return_empty_list(
    api_client, tenant_id, fake_suggestion_extension_service
) -> None:
    suggestion = FakeNameSuggestion(
        cluster_id=str(uuid.uuid4()),
        suggested_name="Jordan Lee",
        source="roster",
        confidence_score=0.81,
    )
    fake_suggestion_extension_service.name_suggestions[suggestion.id] = suggestion

    resp = api_client.get(
        "/recognition/suggestions/name",
        headers={"X-Tenant-ID": tenant_id},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["representatives"] == []


def test_name_suggestions_propagate_user_selected_representative_pin(
    api_client, tenant_id, fake_suggestion_extension_service
) -> None:
    """User-selected reps must serialize wire field is_user_selected=true (E21-17-R1-PY11-2)."""
    cluster_id = str(uuid.uuid4())
    rep_id = str(uuid.uuid4())
    suggestion = FakeNameSuggestion(
        cluster_id=cluster_id,
        suggested_name="Pinned Avery",
        source="identity",
        confidence_score=0.95,
    )
    suggestion.representatives = [
        ClusterRepresentative(
            id=rep_id,
            cluster_id=cluster_id,
            identity_id=str(uuid.uuid4()),
            embedding=np.zeros(512, dtype=np.float32),
            created_at=datetime.now(tz=UTC),
            media_id=202,
            media_url="http://example.test/media/202.jpg",
            bbox_x=1,
            bbox_y=2,
            bbox_width=30,
            bbox_height=40,
            is_user_selected=True,
        )
    ]
    fake_suggestion_extension_service.name_suggestions[suggestion.id] = suggestion

    resp = api_client.get(
        "/recognition/suggestions/name",
        headers={"X-Tenant-ID": tenant_id},
    )

    assert resp.status_code == 200
    rep = resp.json()[0]["representatives"][0]
    assert rep["id"] == rep_id
    assert rep["is_user_selected"] is True
    assert "is_pinned" not in rep


def test_name_suggestions_null_media_id_is_not_fabricated_to_zero(
    api_client, tenant_id, fake_suggestion_extension_service
) -> None:
    """Representatives lacking media_id must serialize media_id=null, never 0 (E21-17-R1-PY11-1)."""
    cluster_id = str(uuid.uuid4())
    suggestion = FakeNameSuggestion(
        cluster_id=cluster_id,
        suggested_name="No Media Avery",
        source="roster",
        confidence_score=0.88,
    )
    suggestion.representatives = [
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
    fake_suggestion_extension_service.name_suggestions[suggestion.id] = suggestion

    resp = api_client.get(
        "/recognition/suggestions/name",
        headers={"X-Tenant-ID": tenant_id},
    )

    assert resp.status_code == 200
    rep = resp.json()[0]["representatives"][0]
    assert rep["media_id"] is None
    assert rep["media_id"] != 0
    assert rep["media_id"] != "0"


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


def test_accept_name_suggestion_rejects_reserved_label_with_400(
    api_client, tenant_id, fake_suggestion_extension_service
) -> None:
    """E21-17-R1-PY47-4: reserved suggested_name must surface 400, not ValueError shadow."""
    register_exception_handlers(api_client.app)
    suggestion = FakeNameSuggestion(
        cluster_id=str(uuid.uuid4()),
        suggested_name="cluster-9",
        source="identity",
        confidence_score=0.9,
    )
    fake_suggestion_extension_service.name_suggestions[suggestion.id] = suggestion
    fake_suggestion_extension_service.accept_name_suggestion = AsyncMock(
        side_effect=ReservedClusterLabelError("cluster-9")
    )

    resp = api_client.post(
        f"/recognition/suggestions/name/{suggestion.id}/accept",
        headers={"X-Tenant-ID": tenant_id},
        json={"tenant_id": tenant_id},
    )

    assert resp.status_code == 400
    assert resp.json()["error"] == "ReservedClusterLabelError"


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
async def test_list_suggestions_top_k_bounds_match_count(
    api_client, tenant_id, fake_suggestion_service, fake_cluster_repository
) -> None:
    """UXP-2 3a: top_k on the per-card route bounds the match count (proxy sends top_k=5 today)."""
    identity_id = str(uuid.uuid4())
    cluster_ids = []
    for index, similarity in enumerate([0.95, 0.90, 0.85]):
        cluster_id = str(uuid.uuid4())
        cluster_ids.append(cluster_id)
        fake_cluster_repository.seed(cluster_id, tenant_id=tenant_id, label=f"Person {index}", identity_count=1)
        suggestion = await fake_suggestion_service.create(identity_id=identity_id, cluster_id=cluster_id)
        suggestion.representative_similarity = similarity

    resp = api_client.get(
        f"/recognition/identities/{identity_id}/suggestions",
        headers={"X-Tenant-ID": tenant_id},
        params={"top_k": 2},
    )

    assert resp.status_code == 200
    matches = resp.json()["matches"]
    assert [item["cluster_id"] for item in matches] == cluster_ids[:2]


@pytest.mark.asyncio
async def test_list_suggestions_without_top_k_returns_all_matches(
    api_client, tenant_id, fake_suggestion_service, fake_cluster_repository
) -> None:
    """Callers that omit top_k keep the current unbounded behavior."""
    identity_id = str(uuid.uuid4())
    for index in range(3):
        cluster_id = str(uuid.uuid4())
        fake_cluster_repository.seed(cluster_id, tenant_id=tenant_id, label=f"Person {index}", identity_count=1)
        await fake_suggestion_service.create(identity_id=identity_id, cluster_id=cluster_id)

    resp = api_client.get(
        f"/recognition/identities/{identity_id}/suggestions",
        headers={"X-Tenant-ID": tenant_id},
    )

    assert resp.status_code == 200
    assert len(resp.json()["matches"]) == 3


def test_list_suggestions_top_k_out_of_range_rejected(api_client, tenant_id) -> None:
    for bad_top_k in (0, -1, 100000):
        resp = api_client.get(
            f"/recognition/identities/{uuid.uuid4()}/suggestions",
            headers={"X-Tenant-ID": tenant_id},
            params={"top_k": bad_top_k},
        )
        assert resp.status_code == 400, f"top_k={bad_top_k} should be rejected"


@pytest.mark.asyncio
async def test_batch_identity_suggestions_keyed_by_identity(api_client, tenant_id, fake_suggestion_service) -> None:
    """UXP-2 3a: GET /identities/suggestions returns the requested subset keyed by identity id."""
    identity_a = str(uuid.uuid4())
    identity_b = str(uuid.uuid4())
    identity_unrequested = str(uuid.uuid4())

    low = await fake_suggestion_service.create(
        identity_id=identity_a,
        cluster_id=str(uuid.uuid4()),
        cluster_label="Person A Low",
        cluster_identity_count=1,
    )
    low.representative_similarity = 0.80
    high = await fake_suggestion_service.create(
        identity_id=identity_a,
        cluster_id=str(uuid.uuid4()),
        cluster_label="Person A High",
        cluster_identity_count=2,
    )
    high.representative_similarity = 0.95
    b_only = await fake_suggestion_service.create(
        identity_id=identity_b,
        cluster_id=str(uuid.uuid4()),
        cluster_label="Person B",
        cluster_identity_count=3,
    )
    await fake_suggestion_service.create(
        identity_id=identity_unrequested,
        cluster_id=str(uuid.uuid4()),
        cluster_label="Not Requested",
        cluster_identity_count=1,
    )

    resp = api_client.get(
        "/recognition/identities/suggestions",
        headers={"X-Tenant-ID": tenant_id},
        params={"identity_ids": f"{identity_a},{identity_b}", "top_k": 1},
    )

    assert resp.status_code == 200
    matches = resp.json()["matches"]
    assert set(matches.keys()) == {identity_a, identity_b}
    assert [item["cluster_id"] for item in matches[identity_a]] == [high.cluster_id]
    assert matches[identity_a][0]["label"] == "Person A High"
    assert [item["cluster_id"] for item in matches[identity_b]] == [b_only.cluster_id]


def test_batch_identity_suggestions_rejects_over_limit(api_client, tenant_id) -> None:
    ids = ",".join(str(uuid.uuid4()) for _ in range(101))
    resp = api_client.get(
        "/recognition/identities/suggestions",
        headers={"X-Tenant-ID": tenant_id},
        params={"identity_ids": ids, "top_k": 1},
    )
    assert resp.status_code == 400


def test_batch_identity_suggestions_accepts_max_limit(api_client, tenant_id) -> None:
    ids = ",".join(str(uuid.uuid4()) for _ in range(100))
    resp = api_client.get(
        "/recognition/identities/suggestions",
        headers={"X-Tenant-ID": tenant_id},
        params={"identity_ids": ids, "top_k": 1},
    )
    assert resp.status_code == 200
    assert resp.json() == {"matches": {}}


def test_batch_identity_suggestions_rejects_invalid_id(api_client, tenant_id) -> None:
    resp = api_client.get(
        "/recognition/identities/suggestions",
        headers={"X-Tenant-ID": tenant_id},
        params={"identity_ids": f"{uuid.uuid4()},not-a-uuid", "top_k": 1},
    )
    assert resp.status_code == 400


def test_batch_identity_suggestions_rejects_out_of_range_top_k(api_client, tenant_id) -> None:
    resp = api_client.get(
        "/recognition/identities/suggestions",
        headers={"X-Tenant-ID": tenant_id},
        params={"identity_ids": str(uuid.uuid4()), "top_k": 0},
    )
    assert resp.status_code == 400


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


def _fake_session_of(api_client) -> FakeSession:  # noqa: ANN001
    """Reach the FakeSession the api_client fixture bound to ``get_session``."""
    session_dep = api_client.app.dependency_overrides[dependencies.get_session]
    for cell in session_dep.__closure__ or ():
        if isinstance(cell.cell_contents, FakeSession):
            return cell.cell_contents
    raise AssertionError("api_client did not override get_session with a FakeSession")


def _seed_merge_pair(fake_cluster_service, fake_cluster_repository, tenant_id):  # noqa: ANN001
    """Seed an unlabelled 50-member A and a labelled 2-member B (ranking picks B)."""
    cluster_a_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    cluster_b_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    fake_cluster_repository.seed(cluster_a_id, tenant_id, label=None, identity_count=50)
    fake_cluster_repository.seed(cluster_b_id, tenant_id, label="Named Person", identity_count=2)
    fake_cluster_service.clusters.extend(
        [
            ClusterResponse(
                id=cluster_a_id,
                tenant_id=tenant_id,
                label=None,
                is_labeled=False,
                is_auto_label=False,
                identity_count=50,
                representatives=[],
            ),
            ClusterResponse(
                id=cluster_b_id,
                tenant_id=tenant_id,
                label="Named Person",
                is_labeled=True,
                is_auto_label=False,
                identity_count=2,
                representatives=[],
            ),
        ]
    )
    return cluster_a_id, cluster_b_id


def _pending_merge_suggestion(cluster_a_id: str, cluster_b_id: str) -> SimpleNamespace:
    from recognition.domain.suggestion import SuggestionStatus

    return SimpleNamespace(
        id=str(uuid.uuid4()),
        cluster_a_id=cluster_a_id,
        cluster_b_id=cluster_b_id,
        similarity=0.91,
        status=SuggestionStatus.PENDING,
        confidence_score=0.91,
        expires_at=None,
        source_job_id=None,
    )


def _bind_merge_repo(monkeypatch, suggestion, *, delete_error: Exception | None = None) -> None:  # noqa: ANN001
    async def fake_get_by_id(self, _tenant_id_arg: str, _sid: str):  # noqa: ANN001
        return suggestion

    async def fake_delete_by_cluster(self, _tenant_id_arg: str, _cluster_id: str) -> int:  # noqa: ANN001
        if delete_error is not None:
            raise delete_error
        return 0

    monkeypatch.setattr(SqlAlchemyMergeSuggestionRepository, "get_by_id", fake_get_by_id)
    monkeypatch.setattr(SqlAlchemyMergeSuggestionRepository, "delete_by_cluster", fake_delete_by_cluster)


@pytest.mark.asyncio
async def test_accept_merge_suggestion_returns_moved_identity_ids(
    api_client,
    tenant_id,
    fake_cluster_service,
    fake_cluster_repository,
    monkeypatch,
) -> None:
    """FEBT1-LD-01(a): the revert set is the ids the merge stamped.

    Red if the endpoint stops calling ``list_identity_ids_moved_by_merge`` and
    returns a fabricated or empty list instead of the fake merge path's stamp.
    """
    cluster_a_id, cluster_b_id = _seed_merge_pair(fake_cluster_service, fake_cluster_repository, tenant_id)
    suggestion = _pending_merge_suggestion(cluster_a_id, cluster_b_id)
    _bind_merge_repo(monkeypatch, suggestion)

    moved = [str(uuid.uuid4()), str(uuid.uuid4())]
    for identity_id in moved:
        fake_cluster_repository.seed_member(
            tenant_id=tenant_id,
            cluster_id=cluster_a_id,
            identity_id=identity_id,
        )
    # Ranking retires A; a target-cluster member must not leak into the revert set.
    fake_cluster_repository.seed_member(
        tenant_id=tenant_id,
        cluster_id=cluster_b_id,
        identity_id=str(uuid.uuid4()),
    )

    resp = api_client.post(
        f"/recognition/suggestions/merge/{suggestion.id}/accept",
        headers={"X-Tenant-ID": tenant_id},
        json={"tenant_id": tenant_id},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["moved_identity_ids"] == moved
    list_calls = [
        call
        for call in fake_cluster_repository.calls
        if call["method"] == "list_identity_ids_moved_by_merge"
    ]
    assert list_calls[-1]["tenant_id"] == tenant_id
    assert list_calls[-1]["merge_id"] == suggestion.id


@pytest.mark.asyncio
async def test_accept_merge_suggestion_rolls_back_merge_when_accept_marking_fails(
    api_client,
    tenant_id,
    fake_cluster_service,
    fake_cluster_repository,
    monkeypatch,
) -> None:
    """FEBT1-LD-01(c): merge + ACCEPTED stamp are one unit of work.

    If the accept-marking half fails, nothing commits, so the merge is rolled back
    and the suggestion stays PENDING. Red if a commit is moved before the stamp
    (ARCH-03: design the failure path, do not leave a half-applied write behind).
    """
    from recognition.domain.suggestion import SuggestionStatus

    cluster_a_id, cluster_b_id = _seed_merge_pair(fake_cluster_service, fake_cluster_repository, tenant_id)
    suggestion = _pending_merge_suggestion(cluster_a_id, cluster_b_id)
    _bind_merge_repo(monkeypatch, suggestion, delete_error=RuntimeError("accept marking failed"))

    fake_session = _fake_session_of(api_client)
    commits_before = fake_session.commit_calls

    with pytest.raises(RuntimeError, match="accept marking failed"):
        api_client.post(
            f"/recognition/suggestions/merge/{suggestion.id}/accept",
            headers={"X-Tenant-ID": tenant_id},
            json={"tenant_id": tenant_id},
        )

    # No commit at all: the merge writes stay inside the aborted transaction.
    assert fake_session.commit_calls == commits_before
    assert suggestion.status == SuggestionStatus.PENDING


@pytest.mark.asyncio
async def test_accept_merge_suggestion_honours_operator_chosen_survivor(
    api_client,
    tenant_id,
    fake_cluster_service,
    fake_cluster_repository,
    monkeypatch,
) -> None:
    """FEBT1-LD-01(b): an explicit target_cluster_id overrides _select_merge_target."""
    cluster_a_id, cluster_b_id = _seed_merge_pair(fake_cluster_service, fake_cluster_repository, tenant_id)
    suggestion = _pending_merge_suggestion(cluster_a_id, cluster_b_id)
    _bind_merge_repo(monkeypatch, suggestion)

    resp = api_client.post(
        f"/recognition/suggestions/merge/{suggestion.id}/accept",
        headers={"X-Tenant-ID": tenant_id},
        json={"tenant_id": tenant_id, "target_cluster_id": cluster_a_id},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Ranking would have retired A (unlabelled); the operator kept it instead.
    assert body["target_cluster_id"] == cluster_a_id
    assert body["source_cluster_id"] == cluster_b_id
    merge_calls = [c for c in fake_cluster_service.calls if c["method"] == "merge_cluster"]
    assert merge_calls[-1]["target_cluster_id"] == cluster_a_id
    assert merge_calls[-1]["source_cluster_id"] == cluster_b_id


@pytest.mark.asyncio
async def test_accept_merge_suggestion_rejects_target_outside_the_pair(
    api_client,
    tenant_id,
    fake_cluster_service,
    fake_cluster_repository,
    monkeypatch,
) -> None:
    """FEBT1-LD-01(b): a survivor id outside the pair must fail loudly, not auto-select."""
    cluster_a_id, cluster_b_id = _seed_merge_pair(fake_cluster_service, fake_cluster_repository, tenant_id)
    suggestion = _pending_merge_suggestion(cluster_a_id, cluster_b_id)
    _bind_merge_repo(monkeypatch, suggestion)

    fake_session = _fake_session_of(api_client)
    commits_before = fake_session.commit_calls

    resp = api_client.post(
        f"/recognition/suggestions/merge/{suggestion.id}/accept",
        headers={"X-Tenant-ID": tenant_id},
        json={"tenant_id": tenant_id, "target_cluster_id": str(uuid.uuid4())},
    )

    assert resp.status_code == 422, resp.text
    assert "target_cluster_id" in resp.text
    assert not [c for c in fake_cluster_service.calls if c["method"] == "merge_cluster"]
    assert fake_session.commit_calls == commits_before
