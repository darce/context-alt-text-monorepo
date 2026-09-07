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


@pytest.mark.asyncio
async def test_refresh_centroids_rejects_a_legacy_boolean_return(monkeypatch: pytest.MonkeyPatch) -> None:
    """A repository that still returns a bool must fail with a named contract error.

    Reading ``.value`` off a bool raised an opaque AttributeError from deep inside
    the response construction, which tells an operator nothing about which
    implementation violated the protocol.
    """
    from recognition.infrastructure.repositories import cluster_repository
    from recognition.interface_adapters.http.routers import clusters_maintenance

    class _LegacyBooleanRepository:
        def __init__(self, _session) -> None:
            pass

        async def refresh_centroids_view_concurrent(self):
            return True

    monkeypatch.setattr(cluster_repository, "SqlAlchemyClusterRepository", _LegacyBooleanRepository)

    with pytest.raises(TypeError) as excinfo:
        await clusters_maintenance.trigger_centroid_mv_refresh(
            session=object(),
            auth=object(),
            _demo_quota=object(),
        )

    message = str(excinfo.value)
    assert "MvRefreshOutcome" in message
    assert "bool" in message
    assert "refresh_centroids_view_concurrent" in message
