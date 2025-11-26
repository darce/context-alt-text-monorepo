"""Tests for clustering configuration HTTP endpoints."""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient

from db.models import Tenant, TenantClusteringConfig
from db.session import async_session_factory
from db.tenant_context import clear_tenant_context, set_tenant_context
from recognition.application.clustering.clustering_settings import ClusteringSettings

pytestmark = pytest.mark.usefixtures("require_database")

if os.getenv("ALLOW_RLS_BYPASS_FOR_TESTS") == "1":
    pytest.skip("Skipping config endpoint tests when RLS bypass is enabled", allow_module_level=True)


@pytest.fixture(autouse=True)
def enable_rls_bypass_for_config_tests(monkeypatch):
    """Allow RLS bypass in config endpoint tests."""
    monkeypatch.setenv("ALLOW_RLS_BYPASS_FOR_TESTS", "1")


@pytest_asyncio.fixture()
async def tenant_id() -> str:
    """Create a tenant and return its ID as string."""
    tenant = uuid4()
    async with async_session_factory() as session:
        session.add(Tenant(id=tenant, site_url=f"https://{tenant}.example.com"))
        await session.commit()
    return str(tenant)


class TestGetConfigEndpoint:
    """Tests for GET /recognition/config endpoint."""

    @pytest.mark.asyncio
    async def test_returns_defaults_when_no_config(self, async_client: AsyncClient, tenant_id: str):
        """Should return default settings when no custom config exists."""
        response = await async_client.get("/recognition/config", params={"tenant_id": tenant_id})

        assert response.status_code == 200
        data = response.json()

        # Verify some key defaults
        defaults = ClusteringSettings()
        assert data["similarity_threshold"] == defaults.similarity_threshold
        assert data["cw_threshold"] == defaults.cw_threshold
        assert data["confidence_weighting_enabled"] == defaults.confidence_weighting_enabled
        assert data["two_pass_enabled"] == defaults.two_pass_enabled

    @pytest.mark.asyncio
    async def test_returns_custom_config(self, async_client: AsyncClient, tenant_id: str):
        """Should return custom settings when config exists."""
        from uuid import UUID

        tenant_uuid = UUID(tenant_id)

        # Create custom config
        async with async_session_factory() as session:
            await set_tenant_context(session, tenant_uuid)
            config = TenantClusteringConfig(
                tenant_id=tenant_uuid,
                similarity_threshold=0.75,
                cw_threshold=0.80,
                confidence_weighting_enabled=True,
            )
            session.add(config)
            await session.commit()
            await clear_tenant_context(session)

        response = await async_client.get("/recognition/config", params={"tenant_id": tenant_id})

        assert response.status_code == 200
        data = response.json()
        assert data["similarity_threshold"] == 0.75
        assert data["cw_threshold"] == 0.80
        assert data["confidence_weighting_enabled"] is True

    @pytest.mark.asyncio
    async def test_returns_all_config_fields(self, async_client: AsyncClient, tenant_id: str):
        """Should return all configuration fields in response."""
        response = await async_client.get("/recognition/config", params={"tenant_id": tenant_id})

        assert response.status_code == 200
        data = response.json()

        # Verify all expected fields are present
        expected_fields = {
            # Core thresholds
            "similarity_threshold",
            "member_validation_threshold",
            "cw_threshold",
            # Confidence weighting
            "confidence_weighting_enabled",
            "confidence_midpoint",
            "threshold_max_adjustment",
            "min_bbox_area",
            # Algorithm selection
            "use_hdbscan_for_outliers",
            "hdbscan_min_cluster_size",
            "hdbscan_min_samples",
            "two_pass_enabled",
            "pass1_threshold",
            "pass2_merge_threshold",
            # Auto-tuning
            "auto_tune_enabled",
            "threshold_min",
            "threshold_max",
            "auto_tune_target_acceptance",
            # Session inference
            "session_boost_enabled",
            "session_similarity_threshold",
            "session_boost_amount",
        }

        assert set(data.keys()) == expected_fields


class TestPatchConfigEndpoint:
    """Tests for PATCH /recognition/config endpoint."""

    @pytest.mark.asyncio
    async def test_updates_single_field(self, async_client: AsyncClient, tenant_id: str):
        """Should update single field and return updated config."""
        response = await async_client.patch(
            "/recognition/config",
            params={"tenant_id": tenant_id},
            json={"similarity_threshold": 0.72},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["similarity_threshold"] == 0.72

        # Verify persistence
        get_response = await async_client.get("/recognition/config", params={"tenant_id": tenant_id})
        assert get_response.json()["similarity_threshold"] == 0.72

    @pytest.mark.asyncio
    async def test_updates_multiple_fields(self, async_client: AsyncClient, tenant_id: str):
        """Should update multiple fields at once."""
        response = await async_client.patch(
            "/recognition/config",
            params={"tenant_id": tenant_id},
            json={
                "similarity_threshold": 0.70,
                "cw_threshold": 0.78,
                "confidence_weighting_enabled": True,
                "two_pass_enabled": True,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["similarity_threshold"] == 0.70
        assert data["cw_threshold"] == 0.78
        assert data["confidence_weighting_enabled"] is True
        assert data["two_pass_enabled"] is True

    @pytest.mark.asyncio
    async def test_preserves_unchanged_fields(self, async_client: AsyncClient, tenant_id: str):
        """Should preserve fields not included in update."""
        # Set initial config
        await async_client.patch(
            "/recognition/config",
            params={"tenant_id": tenant_id},
            json={"similarity_threshold": 0.70, "cw_threshold": 0.78},
        )

        # Update only one field
        response = await async_client.patch(
            "/recognition/config",
            params={"tenant_id": tenant_id},
            json={"similarity_threshold": 0.75},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["similarity_threshold"] == 0.75
        assert data["cw_threshold"] == 0.78  # Preserved

    @pytest.mark.asyncio
    async def test_rejects_empty_update(self, async_client: AsyncClient, tenant_id: str):
        """Should return 400 when no fields provided."""
        response = await async_client.patch(
            "/recognition/config",
            params={"tenant_id": tenant_id},
            json={},
        )

        assert response.status_code == 400
        assert "No fields to update" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_validates_threshold_range(self, async_client: AsyncClient, tenant_id: str):
        """Should validate threshold values are in valid range."""
        # Test value too high
        response = await async_client.patch(
            "/recognition/config",
            params={"tenant_id": tenant_id},
            json={"similarity_threshold": 1.5},
        )
        assert response.status_code == 422  # Validation error

        # Test value too low
        response = await async_client.patch(
            "/recognition/config",
            params={"tenant_id": tenant_id},
            json={"similarity_threshold": -0.1},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_validates_integer_fields(self, async_client: AsyncClient, tenant_id: str):
        """Should validate integer field constraints."""
        # hdbscan_min_cluster_size must be >= 2
        response = await async_client.patch(
            "/recognition/config",
            params={"tenant_id": tenant_id},
            json={"hdbscan_min_cluster_size": 1},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_updates_boolean_fields(self, async_client: AsyncClient, tenant_id: str):
        """Should correctly update boolean fields."""
        # Enable features
        response = await async_client.patch(
            "/recognition/config",
            params={"tenant_id": tenant_id},
            json={
                "confidence_weighting_enabled": True,
                "use_hdbscan_for_outliers": True,
                "two_pass_enabled": True,
                "auto_tune_enabled": True,
                "session_boost_enabled": True,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["confidence_weighting_enabled"] is True
        assert data["use_hdbscan_for_outliers"] is True
        assert data["two_pass_enabled"] is True
        assert data["auto_tune_enabled"] is True
        assert data["session_boost_enabled"] is True

        # Disable features
        response = await async_client.patch(
            "/recognition/config",
            params={"tenant_id": tenant_id},
            json={
                "confidence_weighting_enabled": False,
                "two_pass_enabled": False,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["confidence_weighting_enabled"] is False
        assert data["two_pass_enabled"] is False
        # Others should be preserved
        assert data["use_hdbscan_for_outliers"] is True


class TestDeleteConfigEndpoint:
    """Tests for DELETE /recognition/config endpoint."""

    @pytest.mark.asyncio
    async def test_resets_to_defaults(self, async_client: AsyncClient, tenant_id: str):
        """Should reset config to defaults and return 204."""
        # Set custom config
        await async_client.patch(
            "/recognition/config",
            params={"tenant_id": tenant_id},
            json={"similarity_threshold": 0.80},
        )

        # Delete (reset)
        response = await async_client.delete("/recognition/config", params={"tenant_id": tenant_id})

        assert response.status_code == 204
        assert response.content == b""

        # Verify reset to defaults
        get_response = await async_client.get("/recognition/config", params={"tenant_id": tenant_id})
        defaults = ClusteringSettings()
        assert get_response.json()["similarity_threshold"] == defaults.similarity_threshold

    @pytest.mark.asyncio
    async def test_succeeds_when_no_config_exists(self, async_client: AsyncClient, tenant_id: str):
        """Should return 204 even when no custom config exists."""
        response = await async_client.delete("/recognition/config", params={"tenant_id": tenant_id})

        assert response.status_code == 204


class TestConfigIsolation:
    """Tests for tenant isolation of configuration."""

    @pytest.mark.asyncio
    async def test_configs_are_tenant_isolated(self, async_client: AsyncClient):
        """Each tenant should have independent configuration."""
        # Create two tenants
        tenant1 = uuid4()
        tenant2 = uuid4()

        async with async_session_factory() as session:
            session.add(Tenant(id=tenant1, site_url=f"https://{tenant1}.example.com"))
            session.add(Tenant(id=tenant2, site_url=f"https://{tenant2}.example.com"))
            await session.commit()

        # Set different configs for each tenant
        await async_client.patch(
            "/recognition/config",
            params={"tenant_id": str(tenant1)},
            json={"similarity_threshold": 0.60},
        )

        await async_client.patch(
            "/recognition/config",
            params={"tenant_id": str(tenant2)},
            json={"similarity_threshold": 0.80},
        )

        # Verify isolation
        response1 = await async_client.get("/recognition/config", params={"tenant_id": str(tenant1)})
        response2 = await async_client.get("/recognition/config", params={"tenant_id": str(tenant2)})

        assert response1.json()["similarity_threshold"] == 0.60
        assert response2.json()["similarity_threshold"] == 0.80

    @pytest.mark.asyncio
    async def test_delete_only_affects_target_tenant(self, async_client: AsyncClient):
        """Deleting one tenant's config should not affect others."""
        # Create two tenants
        tenant1 = uuid4()
        tenant2 = uuid4()

        async with async_session_factory() as session:
            session.add(Tenant(id=tenant1, site_url=f"https://{tenant1}.example.com"))
            session.add(Tenant(id=tenant2, site_url=f"https://{tenant2}.example.com"))
            await session.commit()

        # Set configs
        await async_client.patch(
            "/recognition/config",
            params={"tenant_id": str(tenant1)},
            json={"similarity_threshold": 0.70},
        )
        await async_client.patch(
            "/recognition/config",
            params={"tenant_id": str(tenant2)},
            json={"similarity_threshold": 0.75},
        )

        # Delete tenant1's config
        await async_client.delete("/recognition/config", params={"tenant_id": str(tenant1)})

        # Verify tenant2's config is unchanged
        response = await async_client.get("/recognition/config", params={"tenant_id": str(tenant2)})
        assert response.json()["similarity_threshold"] == 0.75
