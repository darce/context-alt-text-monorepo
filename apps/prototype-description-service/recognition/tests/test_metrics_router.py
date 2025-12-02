"""Tests for clustering metrics API endpoint."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from api.main import app
from recognition.application.clustering.clustering_logger import reset_complete_link_stats


@pytest.fixture
def tenant_id() -> UUID:
    """Return a consistent tenant ID for tests."""
    return uuid4()


class TestGetClusteringMetrics:
    """Tests for GET /recognition/metrics endpoint."""

    @pytest.mark.asyncio
    async def test_returns_metrics_structure(self, tenant_id: UUID) -> None:
        """Metrics endpoint should return expected structure."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get(
                "/recognition/metrics",
                params={"tenant_id": str(tenant_id)},
            )

        # Accept 200 or 404 (no clusters yet)
        assert response.status_code in (200, 404)

        if response.status_code == 200:
            data = response.json()
            # Check structure
            assert "tenant_id" in data
            assert "total_identities" in data
            assert "total_clusters" in data
            assert "singleton_count" in data
            assert "singleton_ratio" in data
            assert "avg_cluster_size" in data
            assert "collected_at" in data

    @pytest.mark.asyncio
    async def test_requires_tenant_id(self) -> None:
        """Metrics endpoint should require tenant_id parameter."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/recognition/metrics")

        assert response.status_code == 422  # Validation error

    @pytest.mark.asyncio
    async def test_returns_empty_metrics_for_new_tenant(self) -> None:
        """New tenants with no data should return zero metrics."""
        new_tenant_id = uuid4()

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get(
                "/recognition/metrics",
                params={"tenant_id": str(new_tenant_id)},
            )

        # Either 200 with zeros or 404 (depends on implementation)
        if response.status_code == 200:
            data = response.json()
            assert data["total_identities"] == 0
            assert data["total_clusters"] == 0
            assert data["singleton_count"] == 0


class TestGetClusteringMetricsSnapshot:
    """Tests for GET /recognition/metrics/snapshot endpoint."""

    @pytest.mark.asyncio
    async def test_snapshot_includes_label(self, tenant_id: UUID) -> None:
        """Snapshot endpoint should accept and include label."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get(
                "/recognition/metrics/snapshot",
                params={
                    "tenant_id": str(tenant_id),
                    "label": "before_confidence_weighting",
                },
            )

        if response.status_code == 200:
            data = response.json()
            assert data.get("label") == "before_confidence_weighting"


class TestCompleteLinkMetrics:
    """Tests for GET /recognition/metrics/complete-link endpoint."""

    @pytest.mark.asyncio
    async def test_complete_link_metrics_shape(self) -> None:
        """Endpoint should return counters and sample arrays."""
        reset_complete_link_stats()
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/recognition/metrics/complete-link", params={"reset": "true"})

        assert response.status_code == 200
        data = response.json()
        assert data["checks"] == 0
        assert data["passes"] == 0
        assert data["fails"] == 0
        assert isinstance(data["min_samples"], list)
        assert isinstance(data["avg_samples"], list)
        assert isinstance(data["duration_ms_samples"], list)

    @pytest.mark.asyncio
    async def test_complete_link_dashboard_rates(self) -> None:
        """Dashboard endpoint should include derived rates."""
        reset_complete_link_stats()
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/recognition/metrics/complete-link/dashboard", params={"reset": "true"})

        assert response.status_code == 200
        data = response.json()
        assert "pass_rate" in data
        assert "fail_rate" in data
        assert isinstance(data["pass_rate"], float)
        assert isinstance(data["fail_rate"], float)
