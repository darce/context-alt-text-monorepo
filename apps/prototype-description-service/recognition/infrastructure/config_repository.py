"""Repository for tenant clustering configuration."""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import TenantClusteringConfig
from recognition.application.clustering.clustering_settings import ClusteringSettings

logger = logging.getLogger(__name__)


async def get_tenant_config(
    session: AsyncSession,
    tenant_id: UUID,
) -> ClusteringSettings:
    """
    Load tenant-specific clustering configuration.

    If no configuration exists for the tenant, returns default settings.

    Args:
        session: Database session
        tenant_id: Tenant UUID

    Returns:
        ClusteringSettings with tenant-specific values or defaults
    """
    stmt = select(TenantClusteringConfig).where(TenantClusteringConfig.tenant_id == tenant_id)
    result = await session.execute(stmt)
    config = result.scalar_one_or_none()

    if config is None:
        logger.debug("No config found for tenant %s, using defaults", tenant_id)
        return ClusteringSettings()

    # Build ClusteringSettings from database config
    return ClusteringSettings(
        # Core thresholds
        similarity_threshold=config.similarity_threshold,
        member_validation_threshold=config.member_validation_threshold,
        cw_threshold=config.cw_threshold,
        # Confidence weighting
        confidence_weighting_enabled=config.confidence_weighting_enabled,
        confidence_midpoint=config.confidence_midpoint,
        threshold_max_adjustment=config.threshold_max_adjustment,
        min_bbox_area=config.min_bbox_area,
        # Algorithm selection
        use_hdbscan_for_outliers=config.use_hdbscan_for_outliers,
        hdbscan_min_cluster_size=config.hdbscan_min_cluster_size,
        hdbscan_min_samples=config.hdbscan_min_samples,
        two_pass_enabled=config.two_pass_enabled,
        pass1_threshold=config.pass1_threshold,
        pass2_merge_threshold=config.pass2_merge_threshold,
        # Auto-tuning
        auto_tune_enabled=config.auto_tune_enabled,
        threshold_min=config.threshold_min,
        threshold_max=config.threshold_max,
        auto_tune_target_acceptance=config.auto_tune_target_acceptance,
        # Session inference
        session_boost_enabled=config.session_boost_enabled,
        session_similarity_threshold=config.session_similarity_threshold,
        session_boost_amount=config.session_boost_amount,
    )


async def save_tenant_config(
    session: AsyncSession,
    tenant_id: UUID,
    settings: ClusteringSettings,
) -> TenantClusteringConfig:
    """
    Persist tenant clustering configuration to database.

    Creates a new config if one doesn't exist, or updates the existing one.

    Args:
        session: Database session
        tenant_id: Tenant UUID
        settings: ClusteringSettings to persist

    Returns:
        The saved TenantClusteringConfig model
    """
    stmt = select(TenantClusteringConfig).where(TenantClusteringConfig.tenant_id == tenant_id)
    result = await session.execute(stmt)
    config = result.scalar_one_or_none()

    if config is None:
        # Create new config
        config = TenantClusteringConfig(tenant_id=tenant_id)
        session.add(config)
        logger.info("Creating new clustering config for tenant %s", tenant_id)
    else:
        logger.info("Updating clustering config for tenant %s", tenant_id)

    # Update all fields from settings
    config.similarity_threshold = settings.similarity_threshold
    config.member_validation_threshold = settings.member_validation_threshold
    config.cw_threshold = settings.cw_threshold
    config.confidence_weighting_enabled = settings.confidence_weighting_enabled
    config.confidence_midpoint = settings.confidence_midpoint
    config.threshold_max_adjustment = settings.threshold_max_adjustment
    config.min_bbox_area = settings.min_bbox_area
    config.use_hdbscan_for_outliers = settings.use_hdbscan_for_outliers
    config.hdbscan_min_cluster_size = settings.hdbscan_min_cluster_size
    config.hdbscan_min_samples = settings.hdbscan_min_samples
    config.two_pass_enabled = settings.two_pass_enabled
    config.pass1_threshold = settings.pass1_threshold
    config.pass2_merge_threshold = settings.pass2_merge_threshold
    config.auto_tune_enabled = settings.auto_tune_enabled
    config.threshold_min = settings.threshold_min
    config.threshold_max = settings.threshold_max
    config.auto_tune_target_acceptance = settings.auto_tune_target_acceptance
    config.session_boost_enabled = settings.session_boost_enabled
    config.session_similarity_threshold = settings.session_similarity_threshold
    config.session_boost_amount = settings.session_boost_amount

    await session.flush()
    return config


async def update_tenant_config(
    session: AsyncSession,
    tenant_id: UUID,
    updates: dict[str, float | int | bool],
) -> ClusteringSettings:
    """
    Update specific fields in tenant clustering configuration.

    Only updates the fields provided in the updates dict.
    Creates a new config with defaults if one doesn't exist.

    Args:
        session: Database session
        tenant_id: Tenant UUID
        updates: Dict of field names to new values

    Returns:
        Updated ClusteringSettings

    Raises:
        ValueError: If an invalid field name is provided
    """
    # Get current settings (or defaults)
    current = await get_tenant_config(session, tenant_id)

    # Validate field names
    valid_fields = {
        "similarity_threshold",
        "member_validation_threshold",
        "cw_threshold",
        "confidence_weighting_enabled",
        "confidence_midpoint",
        "threshold_max_adjustment",
        "min_bbox_area",
        "use_hdbscan_for_outliers",
        "hdbscan_min_cluster_size",
        "hdbscan_min_samples",
        "two_pass_enabled",
        "pass1_threshold",
        "pass2_merge_threshold",
        "auto_tune_enabled",
        "threshold_min",
        "threshold_max",
        "auto_tune_target_acceptance",
        "session_boost_enabled",
        "session_similarity_threshold",
        "session_boost_amount",
    }

    invalid_fields = set(updates.keys()) - valid_fields
    if invalid_fields:
        raise ValueError(f"Invalid configuration fields: {invalid_fields}")

    # Apply updates using with_overrides
    updated = ClusteringSettings.with_overrides(current, **updates)

    # Persist
    await save_tenant_config(session, tenant_id, updated)

    logger.info(
        "Updated tenant config",
        extra={
            "tenant_id": str(tenant_id),
            "updated_fields": list(updates.keys()),
        },
    )

    return updated


async def delete_tenant_config(
    session: AsyncSession,
    tenant_id: UUID,
) -> bool:
    """
    Delete tenant clustering configuration (revert to defaults).

    Args:
        session: Database session
        tenant_id: Tenant UUID

    Returns:
        True if config was deleted, False if no config existed
    """
    stmt = select(TenantClusteringConfig).where(TenantClusteringConfig.tenant_id == tenant_id)
    result = await session.execute(stmt)
    config = result.scalar_one_or_none()

    if config is None:
        return False

    await session.delete(config)
    await session.flush()
    logger.info("Deleted clustering config for tenant %s (reverted to defaults)", tenant_id)
    return True
