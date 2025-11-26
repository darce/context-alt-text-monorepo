"""Configuration HTTP routes for clustering settings management."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_session
from db.tenant_context import set_tenant_context
from recognition.infrastructure.config_repository import (
    delete_tenant_config,
    get_tenant_config,
    update_tenant_config,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["config"])


class ClusteringSettingsResponse(BaseModel):
    """Response model for clustering configuration."""

    # Core thresholds
    similarity_threshold: float = Field(description="Base similarity threshold for clustering (0.0-1.0)")
    member_validation_threshold: float = Field(description="Threshold for validating new cluster members")
    cw_threshold: float = Field(description="Chinese Whispers graph edge threshold")

    # Confidence weighting
    confidence_weighting_enabled: bool = Field(description="Enable adaptive thresholds based on detection quality")
    confidence_midpoint: float = Field(description="Confidence level at which no threshold adjustment occurs")
    threshold_max_adjustment: float = Field(description="Maximum threshold change based on confidence")
    min_bbox_area: int = Field(description="Minimum bounding box area for full size confidence")

    # Algorithm selection
    use_hdbscan_for_outliers: bool = Field(description="Use HDBSCAN to recluster singleton identities")
    hdbscan_min_cluster_size: int = Field(description="Minimum cluster size for HDBSCAN")
    hdbscan_min_samples: int = Field(description="Minimum samples for HDBSCAN core points")
    two_pass_enabled: bool = Field(description="Enable two-pass clustering (conservative + HAC merge)")
    pass1_threshold: float = Field(description="Conservative threshold for Pass 1")
    pass2_merge_threshold: float = Field(description="HAC merge threshold for Pass 2")

    # Auto-tuning
    auto_tune_enabled: bool = Field(description="Enable automatic threshold adjustment based on user feedback")
    threshold_min: float = Field(description="Lower bound for auto-tuned similarity threshold")
    threshold_max: float = Field(description="Upper bound for auto-tuned similarity threshold")
    auto_tune_target_acceptance: float = Field(description="Target suggestion acceptance rate for auto-tuning")

    # Session inference
    session_boost_enabled: bool = Field(description="Boost similarity for faces from same photo session")
    session_similarity_threshold: float = Field(description="Scene signature similarity for session grouping")
    session_boost_amount: float = Field(description="Amount to boost similarity for same-session faces")


class ClusteringSettingsUpdate(BaseModel):
    """Request model for updating clustering configuration.

    All fields are optional - only provided fields will be updated.
    """

    # Core thresholds
    similarity_threshold: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Base similarity threshold for clustering",
    )
    member_validation_threshold: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Threshold for validating new cluster members",
    )
    cw_threshold: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Chinese Whispers graph edge threshold",
    )

    # Confidence weighting
    confidence_weighting_enabled: bool | None = Field(
        default=None,
        description="Enable adaptive thresholds based on detection quality",
    )
    confidence_midpoint: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Confidence level at which no threshold adjustment occurs",
    )
    threshold_max_adjustment: float | None = Field(
        default=None,
        ge=0.0,
        le=0.5,
        description="Maximum threshold change based on confidence",
    )
    min_bbox_area: int | None = Field(
        default=None,
        ge=100,
        description="Minimum bounding box area for full size confidence",
    )

    # Algorithm selection
    use_hdbscan_for_outliers: bool | None = Field(
        default=None,
        description="Use HDBSCAN to recluster singleton identities",
    )
    hdbscan_min_cluster_size: int | None = Field(
        default=None,
        ge=2,
        description="Minimum cluster size for HDBSCAN",
    )
    hdbscan_min_samples: int | None = Field(
        default=None,
        ge=1,
        description="Minimum samples for HDBSCAN core points",
    )
    two_pass_enabled: bool | None = Field(
        default=None,
        description="Enable two-pass clustering (conservative + HAC merge)",
    )
    pass1_threshold: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Conservative threshold for Pass 1",
    )
    pass2_merge_threshold: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="HAC merge threshold for Pass 2",
    )

    # Auto-tuning
    auto_tune_enabled: bool | None = Field(
        default=None,
        description="Enable automatic threshold adjustment based on user feedback",
    )
    threshold_min: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Lower bound for auto-tuned similarity threshold",
    )
    threshold_max: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Upper bound for auto-tuned similarity threshold",
    )
    auto_tune_target_acceptance: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Target suggestion acceptance rate for auto-tuning",
    )

    # Session inference
    session_boost_enabled: bool | None = Field(
        default=None,
        description="Boost similarity for faces from same photo session",
    )
    session_similarity_threshold: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Scene signature similarity for session grouping",
    )
    session_boost_amount: float | None = Field(
        default=None,
        ge=0.0,
        le=0.5,
        description="Amount to boost similarity for same-session faces",
    )


def _settings_to_response(settings) -> ClusteringSettingsResponse:
    """Convert ClusteringSettings to response model."""
    return ClusteringSettingsResponse(
        similarity_threshold=settings.similarity_threshold,
        member_validation_threshold=settings.member_validation_threshold,
        cw_threshold=settings.cw_threshold,
        confidence_weighting_enabled=settings.confidence_weighting_enabled,
        confidence_midpoint=settings.confidence_midpoint,
        threshold_max_adjustment=settings.threshold_max_adjustment,
        min_bbox_area=settings.min_bbox_area,
        use_hdbscan_for_outliers=settings.use_hdbscan_for_outliers,
        hdbscan_min_cluster_size=settings.hdbscan_min_cluster_size,
        hdbscan_min_samples=settings.hdbscan_min_samples,
        two_pass_enabled=settings.two_pass_enabled,
        pass1_threshold=settings.pass1_threshold,
        pass2_merge_threshold=settings.pass2_merge_threshold,
        auto_tune_enabled=settings.auto_tune_enabled,
        threshold_min=settings.threshold_min,
        threshold_max=settings.threshold_max,
        auto_tune_target_acceptance=settings.auto_tune_target_acceptance,
        session_boost_enabled=settings.session_boost_enabled,
        session_similarity_threshold=settings.session_similarity_threshold,
        session_boost_amount=settings.session_boost_amount,
    )


@router.get("/config", response_model=ClusteringSettingsResponse)
async def get_clustering_config(
    tenant_id: UUID = Query(..., description="Tenant ID"),
    session: AsyncSession = Depends(get_session),
) -> ClusteringSettingsResponse:
    """
    Get current clustering configuration for a tenant.

    Returns default values if no custom configuration exists.
    """
    await set_tenant_context(session, tenant_id)

    settings = await get_tenant_config(session, tenant_id)
    return _settings_to_response(settings)


@router.patch("/config", response_model=ClusteringSettingsResponse)
async def update_clustering_config(
    updates: ClusteringSettingsUpdate,
    tenant_id: UUID = Query(..., description="Tenant ID"),
    session: AsyncSession = Depends(get_session),
) -> ClusteringSettingsResponse:
    """
    Update clustering configuration for a tenant.

    Only provided fields will be updated. Other fields retain their current values.

    Example:
        PATCH /config?tenant_id=...
        {"similarity_threshold": 0.70, "confidence_weighting_enabled": true}
    """
    await set_tenant_context(session, tenant_id)

    # Convert update model to dict, excluding None values
    update_dict = {k: v for k, v in updates.model_dump().items() if v is not None}

    if not update_dict:
        raise HTTPException(
            status_code=400,
            detail="No fields to update. Provide at least one configuration field.",
        )

    try:
        updated_settings = await update_tenant_config(session, tenant_id, update_dict)
        await session.commit()

        logger.info(
            "Updated clustering config",
            extra={
                "tenant_id": str(tenant_id),
                "updated_fields": list(update_dict.keys()),
            },
        )

        return _settings_to_response(updated_settings)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete("/config", status_code=204, response_class=Response)
async def reset_clustering_config(
    tenant_id: UUID = Query(..., description="Tenant ID"),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """
    Reset clustering configuration to defaults.

    Deletes any custom configuration for the tenant, reverting to system defaults.
    """
    await set_tenant_context(session, tenant_id)

    deleted = await delete_tenant_config(session, tenant_id)
    await session.commit()

    if not deleted:
        logger.debug("No custom config to delete for tenant %s", tenant_id)

    logger.info("Reset clustering config to defaults for tenant %s", tenant_id)
    return Response(status_code=204)
