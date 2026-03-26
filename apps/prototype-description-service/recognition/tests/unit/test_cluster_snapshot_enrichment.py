"""Tests for the _enrich_with_suggested_labels snapshot helper."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from recognition.domain.suggestion import SuggestedLabel, SuggestedLabelSource
from recognition.interface_adapters.http.routers.clusters import (
    _INFERENCE_CAP,
    _enrich_with_suggested_labels,
)
from recognition.interface_adapters.http.schemas.responses import ClusterSnapshotClusterResponse


def _make_cluster(
    cluster_uuid: str,
    label: str | None = None,
    is_user_confirmed: bool = False,
    identity_count: int = 5,
) -> ClusterSnapshotClusterResponse:
    return ClusterSnapshotClusterResponse(
        cluster_uuid=cluster_uuid,
        label=label,
        curation_state="confirmed" if is_user_confirmed else "active",
        is_user_confirmed=is_user_confirmed,
        identity_count=identity_count,
    )


@pytest.mark.asyncio
async def test_enrich_sets_suggested_label_for_unlabeled_cluster(monkeypatch) -> None:
    cluster = _make_cluster("aaa-111", label=None, is_user_confirmed=False)
    mock_infer = AsyncMock(
        return_value=SuggestedLabel(
            label="Alice",
            source=SuggestedLabelSource.SIMILAR_CLUSTER,
            confidence=0.92,
            target_cluster_id="bbb-222",
        )
    )
    monkeypatch.setattr(
        "recognition.interface_adapters.http.routers.clusters.infer_suggested_label",
        mock_infer,
    )

    await _enrich_with_suggested_labels([cluster], "tenant-1", AsyncMock(), AsyncMock(), AsyncMock())

    assert cluster.suggested_label == "Alice"
    assert cluster.suggested_label_source == "similar_cluster"
    assert cluster.suggested_label_confidence == 0.92
    assert cluster.suggested_target_cluster_id == "bbb-222"


@pytest.mark.asyncio
async def test_enrich_skips_user_confirmed_cluster(monkeypatch) -> None:
    """User-confirmed clusters must never receive a suggested_label."""
    cluster = _make_cluster("aaa-111", label=None, is_user_confirmed=True, identity_count=10)
    mock_infer = AsyncMock()
    monkeypatch.setattr(
        "recognition.interface_adapters.http.routers.clusters.infer_suggested_label",
        mock_infer,
    )

    await _enrich_with_suggested_labels([cluster], "tenant-1", AsyncMock(), AsyncMock(), AsyncMock())

    mock_infer.assert_not_called()
    assert cluster.suggested_label is None


@pytest.mark.asyncio
async def test_enrich_skips_already_labeled_cluster(monkeypatch) -> None:
    """Clusters that already have a label do not need inference."""
    cluster = _make_cluster("aaa-111", label="Daniel", is_user_confirmed=False)
    mock_infer = AsyncMock()
    monkeypatch.setattr(
        "recognition.interface_adapters.http.routers.clusters.infer_suggested_label",
        mock_infer,
    )

    await _enrich_with_suggested_labels([cluster], "tenant-1", AsyncMock(), AsyncMock(), AsyncMock())

    mock_infer.assert_not_called()
    assert cluster.suggested_label is None


@pytest.mark.asyncio
async def test_enrich_respects_inference_cap(monkeypatch) -> None:
    """Inference must stop after _INFERENCE_CAP clusters; the rest stay null."""
    clusters = [
        _make_cluster(f"cluster-{i}", label=None, is_user_confirmed=False, identity_count=_INFERENCE_CAP - i)
        for i in range(_INFERENCE_CAP + 5)
    ]
    call_count = 0

    async def _fake_infer(**_kwargs):  # noqa: ANN002
        nonlocal call_count
        call_count += 1
        return None

    monkeypatch.setattr(
        "recognition.interface_adapters.http.routers.clusters.infer_suggested_label",
        _fake_infer,
    )

    await _enrich_with_suggested_labels(clusters, "tenant-1", AsyncMock(), AsyncMock(), AsyncMock())

    assert call_count == _INFERENCE_CAP
    for cluster in clusters[_INFERENCE_CAP:]:
        assert cluster.suggested_label is None


@pytest.mark.asyncio
async def test_enrich_orders_by_identity_count_descending(monkeypatch) -> None:
    """Clusters with the most identities must be enriched first under the cap."""
    low = _make_cluster("low", label=None, is_user_confirmed=False, identity_count=1)
    high = _make_cluster("high", label=None, is_user_confirmed=False, identity_count=100)
    enriched_order: list[str] = []

    async def _fake_infer(*, cluster_id: str, **_kwargs):  # noqa: ANN002
        enriched_order.append(cluster_id)
        return None

    monkeypatch.setattr(
        "recognition.interface_adapters.http.routers.clusters.infer_suggested_label",
        _fake_infer,
    )

    # Pass low before high; expect high to be enriched first
    await _enrich_with_suggested_labels([low, high], "tenant-1", AsyncMock(), AsyncMock(), AsyncMock())

    assert enriched_order == ["high", "low"]
