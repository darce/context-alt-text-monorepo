"""Tests for tenant clustering configuration repository."""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
import pytest_asyncio

from db.models import Tenant, TenantClusteringConfig
from db.session import async_session_factory
from db.tenant_context import clear_tenant_context, set_tenant_context
from recognition.application.clustering.clustering_settings import ClusteringSettings
from recognition.infrastructure.config_repository import (
    delete_tenant_config,
    get_tenant_config,
    save_tenant_config,
    update_tenant_config,
)

pytestmark = pytest.mark.usefixtures("require_database")

if os.getenv("ALLOW_RLS_BYPASS_FOR_TESTS") == "1":
    pytest.skip("Skipping config repository tests when RLS bypass is enabled", allow_module_level=True)


@pytest.fixture(autouse=True)
def enable_rls_bypass_for_config_tests(monkeypatch):
    """Allow RLS bypass in config repository tests."""
    monkeypatch.setenv("ALLOW_RLS_BYPASS_FOR_TESTS", "1")


@pytest_asyncio.fixture()
async def tenant_id():
    """Create a tenant and return its ID."""
    tenant = uuid4()
    async with async_session_factory() as session:
        session.add(Tenant(id=tenant, site_url=f"https://{tenant}.example.com"))
        await session.commit()
    return tenant


class TestGetTenantConfig:
    """Tests for get_tenant_config."""

    @pytest.mark.asyncio
    async def test_returns_defaults_when_no_config_exists(self, tenant_id):
        """When no config exists, should return default ClusteringSettings."""
        async with async_session_factory() as session:
            await set_tenant_context(session, tenant_id)

            settings = await get_tenant_config(session, tenant_id)

            # Verify defaults match ClusteringSettings defaults
            defaults = ClusteringSettings()
            assert settings.similarity_threshold == defaults.similarity_threshold
            assert settings.cw_threshold == defaults.cw_threshold
            assert settings.confidence_weighting_enabled == defaults.confidence_weighting_enabled
            assert settings.two_pass_enabled == defaults.two_pass_enabled

            await clear_tenant_context(session)

    @pytest.mark.asyncio
    async def test_returns_saved_config(self, tenant_id):
        """When config exists, should return saved values."""
        async with async_session_factory() as session:
            await set_tenant_context(session, tenant_id)

            # Create config with custom values
            config = TenantClusteringConfig(
                tenant_id=tenant_id,
                similarity_threshold=0.75,
                cw_threshold=0.80,
                confidence_weighting_enabled=True,
            )
            session.add(config)
            await session.commit()

            # Retrieve config
            await set_tenant_context(session, tenant_id)
            settings = await get_tenant_config(session, tenant_id)

            assert settings.similarity_threshold == 0.75
            assert settings.cw_threshold == 0.80
            assert settings.confidence_weighting_enabled is True

            await clear_tenant_context(session)


class TestSaveTenantConfig:
    """Tests for save_tenant_config."""

    @pytest.mark.asyncio
    async def test_creates_new_config(self, tenant_id):
        """Should create new config when none exists."""
        async with async_session_factory() as session:
            await set_tenant_context(session, tenant_id)

            settings = ClusteringSettings(
                similarity_threshold=0.70,
                confidence_weighting_enabled=True,
                hdbscan_min_cluster_size=3,
            )

            result = await save_tenant_config(session, tenant_id, settings)
            await session.commit()

            assert result.tenant_id == tenant_id
            assert result.similarity_threshold == 0.70
            assert result.confidence_weighting_enabled is True
            assert result.hdbscan_min_cluster_size == 3

            await clear_tenant_context(session)

    @pytest.mark.asyncio
    async def test_updates_existing_config(self, tenant_id):
        """Should update existing config."""
        async with async_session_factory() as session:
            await set_tenant_context(session, tenant_id)

            # Create initial config
            initial_settings = ClusteringSettings(similarity_threshold=0.65)
            await save_tenant_config(session, tenant_id, initial_settings)
            await session.commit()

            # Update config
            await set_tenant_context(session, tenant_id)
            updated_settings = ClusteringSettings(similarity_threshold=0.75)
            result = await save_tenant_config(session, tenant_id, updated_settings)
            await session.commit()

            assert result.similarity_threshold == 0.75

            # Verify only one config exists
            await set_tenant_context(session, tenant_id)
            from sqlalchemy import select

            stmt = select(TenantClusteringConfig).where(TenantClusteringConfig.tenant_id == tenant_id)
            configs = (await session.execute(stmt)).scalars().all()
            assert len(configs) == 1

            await clear_tenant_context(session)


class TestUpdateTenantConfig:
    """Tests for update_tenant_config (partial updates)."""

    @pytest.mark.asyncio
    async def test_updates_single_field(self, tenant_id):
        """Should update only the specified field."""
        async with async_session_factory() as session:
            await set_tenant_context(session, tenant_id)

            # Get defaults first
            defaults = await get_tenant_config(session, tenant_id)
            original_cw = defaults.cw_threshold

            # Update single field
            result = await update_tenant_config(session, tenant_id, {"similarity_threshold": 0.72})
            await session.commit()

            assert result.similarity_threshold == 0.72
            assert result.cw_threshold == original_cw  # Unchanged

            await clear_tenant_context(session)

    @pytest.mark.asyncio
    async def test_updates_multiple_fields(self, tenant_id):
        """Should update multiple fields at once."""
        async with async_session_factory() as session:
            await set_tenant_context(session, tenant_id)

            result = await update_tenant_config(
                session,
                tenant_id,
                {
                    "similarity_threshold": 0.70,
                    "cw_threshold": 0.78,
                    "confidence_weighting_enabled": True,
                    "two_pass_enabled": True,
                },
            )
            await session.commit()

            assert result.similarity_threshold == 0.70
            assert result.cw_threshold == 0.78
            assert result.confidence_weighting_enabled is True
            assert result.two_pass_enabled is True

            await clear_tenant_context(session)

    @pytest.mark.asyncio
    async def test_rejects_invalid_field_names(self, tenant_id):
        """Should raise ValueError for invalid field names."""
        async with async_session_factory() as session:
            await set_tenant_context(session, tenant_id)

            with pytest.raises(ValueError, match="Invalid configuration fields"):
                await update_tenant_config(session, tenant_id, {"invalid_field": 0.5})

            await clear_tenant_context(session)

    @pytest.mark.asyncio
    async def test_creates_config_on_first_update(self, tenant_id):
        """Should create config if none exists when updating."""
        async with async_session_factory() as session:
            await set_tenant_context(session, tenant_id)

            # Update without existing config
            result = await update_tenant_config(session, tenant_id, {"similarity_threshold": 0.68})
            await session.commit()

            # Should have custom threshold but defaults for rest
            assert result.similarity_threshold == 0.68
            defaults = ClusteringSettings()
            assert result.cw_threshold == defaults.cw_threshold

            await clear_tenant_context(session)


class TestDeleteTenantConfig:
    """Tests for delete_tenant_config."""

    @pytest.mark.asyncio
    async def test_deletes_existing_config(self, tenant_id):
        """Should delete config and return True."""
        async with async_session_factory() as session:
            await set_tenant_context(session, tenant_id)

            # Create config
            settings = ClusteringSettings(similarity_threshold=0.75)
            await save_tenant_config(session, tenant_id, settings)
            await session.commit()

            # Delete config
            await set_tenant_context(session, tenant_id)
            result = await delete_tenant_config(session, tenant_id)
            await session.commit()

            assert result is True

            # Verify config is deleted (defaults returned)
            await set_tenant_context(session, tenant_id)
            settings = await get_tenant_config(session, tenant_id)
            defaults = ClusteringSettings()
            assert settings.similarity_threshold == defaults.similarity_threshold

            await clear_tenant_context(session)

    @pytest.mark.asyncio
    async def test_returns_false_when_no_config_exists(self, tenant_id):
        """Should return False when no config to delete."""
        async with async_session_factory() as session:
            await set_tenant_context(session, tenant_id)

            result = await delete_tenant_config(session, tenant_id)

            assert result is False

            await clear_tenant_context(session)


class TestConfigPersistence:
    """Integration tests for config round-trip persistence."""

    @pytest.mark.asyncio
    async def test_all_fields_round_trip(self, tenant_id):
        """All ClusteringSettings fields should round-trip through database."""
        async with async_session_factory() as session:
            await set_tenant_context(session, tenant_id)

            # Create settings with all custom values
            original = ClusteringSettings(
                similarity_threshold=0.72,
                member_validation_threshold=0.70,
                cw_threshold=0.78,
                confidence_weighting_enabled=True,
                confidence_midpoint=0.90,
                threshold_max_adjustment=0.08,
                min_bbox_area=15000,
                use_hdbscan_for_outliers=True,
                hdbscan_min_cluster_size=3,
                hdbscan_min_samples=2,
                two_pass_enabled=True,
                pass1_threshold=0.80,
                pass2_merge_threshold=0.60,
                auto_tune_enabled=True,
                threshold_min=0.55,
                threshold_max=0.85,
                auto_tune_target_acceptance=0.75,
                session_boost_enabled=True,
                session_similarity_threshold=0.88,
                session_boost_amount=0.08,
            )

            await save_tenant_config(session, tenant_id, original)
            await session.commit()

            # Retrieve and verify
            await set_tenant_context(session, tenant_id)
            loaded = await get_tenant_config(session, tenant_id)

            # Core thresholds
            assert loaded.similarity_threshold == original.similarity_threshold
            assert loaded.member_validation_threshold == original.member_validation_threshold
            assert loaded.cw_threshold == original.cw_threshold

            # Confidence weighting
            assert loaded.confidence_weighting_enabled == original.confidence_weighting_enabled
            assert loaded.confidence_midpoint == original.confidence_midpoint
            assert loaded.threshold_max_adjustment == original.threshold_max_adjustment
            assert loaded.min_bbox_area == original.min_bbox_area

            # Algorithm selection
            assert loaded.use_hdbscan_for_outliers == original.use_hdbscan_for_outliers
            assert loaded.hdbscan_min_cluster_size == original.hdbscan_min_cluster_size
            assert loaded.hdbscan_min_samples == original.hdbscan_min_samples
            assert loaded.two_pass_enabled == original.two_pass_enabled
            assert loaded.pass1_threshold == original.pass1_threshold
            assert loaded.pass2_merge_threshold == original.pass2_merge_threshold

            # Auto-tuning
            assert loaded.auto_tune_enabled == original.auto_tune_enabled
            assert loaded.threshold_min == original.threshold_min
            assert loaded.threshold_max == original.threshold_max
            assert loaded.auto_tune_target_acceptance == original.auto_tune_target_acceptance

            # Session inference
            assert loaded.session_boost_enabled == original.session_boost_enabled
            assert loaded.session_similarity_threshold == original.session_similarity_threshold
            assert loaded.session_boost_amount == original.session_boost_amount

            await clear_tenant_context(session)
