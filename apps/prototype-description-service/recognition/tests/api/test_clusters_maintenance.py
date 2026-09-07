"""Tests for centroid materialized-view maintenance responses."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_refresh_centroids_reports_headroom_skip(monkeypatch: pytest.MonkeyPatch) -> None:
    from recognition.infrastructure.repositories import cluster_repository
    from recognition.interface_adapters.http.routers import clusters_maintenance

    class _FakeClusterRepository:
        def __init__(self, _session) -> None:
            pass

        async def refresh_centroids_view_concurrent(self):
            return cluster_repository.MvRefreshOutcome.SKIPPED_HEADROOM

    monkeypatch.setattr(cluster_repository, "SqlAlchemyClusterRepository", _FakeClusterRepository)

    response = await clusters_maintenance.trigger_centroid_mv_refresh(
        session=object(),
        auth=object(),
        _demo_quota=object(),
    )

    assert response["ok"] is False
    assert response["outcome"] == "skipped_headroom"
    assert response["reason"] == "insufficient_disk_headroom"
