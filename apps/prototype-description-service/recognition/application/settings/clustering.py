"""
Clustering and assignment thresholds for the recognition service.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ClusteringSettings(BaseModel):
    """Threshold configuration for discovery and assignment flows.

    All fields are required in the final implementation; defaults here serve only
    as scaffolding for early wiring. Implement environment-backed loading in the
    next phase per instructions.
    """

    similarity_threshold: float = Field(default=0.85, description="Base similarity threshold for matching.")
    complete_link_min_floor: float = Field(default=0.80, description="Minimum similarity any representative must meet.")
    complete_link_avg_threshold: float = Field(default=0.85, description="Average similarity across representatives.")
    min_representatives_for_maturity: int = Field(default=2, description="Minimum reps before auto-assignment.")
    member_validation_min_floor: float = Field(default=0.75, description="Minimum similarity to any member.")
    member_validation_avg_threshold: float = Field(default=0.85, description="Average similarity to cluster members.")
    early_stage_suggestion_enabled: bool = Field(
        default=True, description="Route borderline matches to suggestions early."
    )
    early_stage_high_confidence_threshold: float = Field(
        default=0.90, description="Confidence threshold for early-stage auto-assign."
    )
    adaptive_threshold_maturity_point: int = Field(default=5, description="Cluster count at which thresholds tighten.")
    hdbscan_max_batch_size: int | None = Field(
        default=None,
        description="Optional upper bound for HDBSCAN batch size.",
    )
    max_representatives_per_cluster: int = Field(
        default=5, description="Maximum number of representatives to maintain per cluster."
    )
    representative_diversity_threshold: float = Field(
        default=0.90, description="Maximum similarity allowed between representatives (lower adds diversity)."
    )

    model_config = ConfigDict(arbitrary_types_allowed=True)
