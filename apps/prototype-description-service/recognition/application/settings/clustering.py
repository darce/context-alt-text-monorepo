"""
Clustering and assignment thresholds for the recognition service.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class QualitySettings(BaseModel):
    """Settings for identity quality scoring.

    Controls how detection quality affects clustering thresholds.
    """

    model_config = ConfigDict(frozen=True)

    # Pose penalty settings
    pose_penalty_divisor: float = Field(
        default=90.0,
        description="Total angle at which pose_penalty becomes zero.",
    )

    # Size factor settings
    min_face_size: float = Field(
        default=80.0,
        description="Minimum face dimension (pixels) for full size_factor.",
    )

    # Quality adjustment thresholds
    high_quality_threshold: float = Field(
        default=0.9,
        description="Quality score at/above which threshold is loosened.",
    )
    neutral_quality_threshold: float = Field(
        default=0.8,
        description="Quality score at/above which no adjustment is applied.",
    )
    mediocre_quality_threshold: float = Field(
        default=0.6,
        description="Quality score at/above which slight tightening occurs.",
    )

    # Adjustment amounts (positive = stricter, negative = more lenient)
    high_quality_adjustment: float = Field(
        default=-0.05,
        description="Threshold adjustment for high quality faces (negative = lenient).",
    )
    neutral_quality_adjustment: float = Field(
        default=0.0,
        description="Threshold adjustment for neutral quality faces.",
    )
    mediocre_quality_adjustment: float = Field(
        default=0.02,
        description="Threshold adjustment for mediocre quality faces.",
    )
    poor_quality_adjustment: float = Field(
        default=0.05,
        description="Threshold adjustment for poor quality faces (positive = strict).",
    )

    # Scoring weights
    detection_confidence_weight: float = Field(
        default=0.6,
        description="Weight for detection confidence in quality score.",
    )
    face_size_weight: float = Field(
        default=0.4,
        description="Weight for face size in quality score.",
    )

    # Face size scoring thresholds (pixels squared)
    face_size_large_threshold: int = Field(
        default=20000,
        description="Area threshold for large face score.",
    )
    face_size_medium_threshold: int = Field(
        default=5000,
        description="Area threshold for medium face score.",
    )

    # Face size scores
    face_size_large_score: float = Field(
        default=1.0,
        description="Score component for large faces.",
    )
    face_size_medium_score: float = Field(
        default=0.7,
        description="Score component for medium faces.",
    )
    face_size_small_score: float = Field(
        default=0.4,
        description="Score component for small faces.",
    )


class MaturitySettings(BaseModel):
    """Settings for cluster maturity level computation.

    Controls when clusters transition between COLD, NASCENT, and MATURE levels.
    Pose coverage ensures clusters can recognize faces from multiple angles.
    """

    model_config = ConfigDict(frozen=True)

    # Level thresholds
    nascent_min_members: int = Field(
        default=2,
        description="Minimum identity_count for NASCENT level (>1 means at least 2).",
    )
    mature_min_members: int = Field(
        default=11,
        description="Minimum identity_count for MATURE level (>10 means at least 11).",
    )
    mature_min_representatives: int = Field(
        default=3,
        description="Minimum representative_count required for MATURE level.",
    )
    mature_min_pose_coverage: float = Field(
        default=0.3,
        description="Minimum pose bucket coverage (0-1) required for MATURE level. "
        "A value of 0.3 means at least ~4 of 13 pose buckets must be filled.",
    )
    pose_bucket_size: float = Field(
        default=30.0,
        description="Size of pose buckets in degrees for coverage calculation.",
    )
    total_pose_buckets: int = Field(
        default=13,
        description="Total number of pose buckets (pitch x yaw grid cells).",
    )

    # Threshold adjustments per level (negative = more lenient)
    cold_adjustment: float = Field(
        default=0.0,
        description="Threshold adjustment for COLD clusters.",
    )
    nascent_adjustment: float = Field(
        default=0.0,
        description="Threshold adjustment for NASCENT clusters.",
    )
    confirmed_adjustment: float = Field(
        default=-0.02,
        description="Threshold adjustment for user-CONFIRMED clusters.",
    )
    mature_adjustment: float = Field(
        default=-0.05,
        description="Threshold adjustment for MATURE clusters.",
    )


class AutoLabelSettings(BaseModel):
    """Settings for automatic cluster labeling."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = Field(
        default=True,
        description="Enable auto-labeling of high-confidence clusters.",
    )
    min_members: int = Field(
        default=3,
        description="Minimum cluster size to trigger auto-labeling.",
    )
    similarity_floor: float = Field(
        default=0.85,
        description="Minimum average similarity for auto-labeling.",
    )
    prefix: str = Field(
        default="Person",
        description="Prefix for auto-generated labels (e.g., 'Person 1').",
    )


class ClusteringSettings(BaseModel):
    """Threshold configuration for discovery and assignment flows.

    Defaults live in the config model. Override by passing explicit values
    when building the RecognitionSettings configuration.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    quality: QualitySettings = Field(
        default_factory=QualitySettings,
        description="Settings for identity quality scoring.",
    )
    maturity: MaturitySettings = Field(
        default_factory=MaturitySettings,
        description="Settings for cluster maturity level computation.",
    )
    auto_label: AutoLabelSettings = Field(
        default_factory=AutoLabelSettings,
        description="Settings for auto-labeling high-confidence clusters.",
    )

    similarity_threshold: float = Field(
        default=0.55,
        description="Discovery threshold for candidate matching. Lowered from 0.65 based on observed similarity distribution (0.42-0.56 for valid matches).",
    )
    complete_link_threshold: float = Field(
        default=0.45,
        description="Complete-link minimum similarity required to validate expansion. Lowered from 0.55 based on observed distribution.",
    )
    complete_link_min_coverage: float = Field(
        default=0.85,
        description="Fraction of members that must pass complete-link threshold.",
    )
    complete_link_enabled: bool = Field(
        default=True,
        description="Enable complete-link verification during graph expansion.",
    )
    complete_link_min_floor: float = Field(
        default=0.40,
        description="Minimum similarity any representative must meet. Lowered from 0.50 based on observed valid matches.",
    )
    complete_link_avg_threshold: float = Field(
        default=0.50,
        description="Average similarity across representatives. Lowered from 0.60 based on observed distribution.",
    )
    min_representatives_for_maturity: int = Field(
        default=0,
        description="Minimum reps before auto-assignment. 0 = disabled.",
    )
    member_validation_min_floor: float = Field(
        default=0.35,
        description="Minimum similarity to any member. Lowered from 0.45 to match suggestion_floor.",
    )
    member_validation_avg_threshold: float = Field(
        default=0.50,
        description="Average similarity to cluster members. Lowered from 0.60 based on observed distribution.",
    )
    early_stage_suggestion_enabled: bool = Field(
        default=True,
        description="Route borderline matches to suggestions early.",
    )
    suggestion_floor: float = Field(
        default=0.35,
        description="Lower bound for suggestion band (below this -> reject). Lowered from 0.45 based on observed valid matches at 0.42+.",
    )
    suggestion_ceiling: float = Field(
        default=0.55,
        description="Upper bound for suggestion band (at/above -> accept). Aligned with similarity_threshold.",
    )
    curriculum_coefficient: float = Field(
        default=-0.05,
        description="Coefficient for curriculum adjustment (curriculum_adj = coefficient * curriculum_t).",
    )
    early_stage_high_confidence_threshold: float = Field(
        default=0.75,
        description="Confidence threshold for early-stage auto-assign. Lowered from 0.90 for embedding reality.",
    )
    hdbscan_max_batch_size: int | None = Field(
        default=None,
        description="Optional upper bound for HDBSCAN batch size.",
    )
    hdbscan_min_cluster_size: int = Field(
        default=2,
        description="Minimum size of clusters for HDBSCAN.",
    )
    hdbscan_min_samples: int = Field(
        default=1,
        description="Minimum samples parameter for HDBSCAN.",
    )
    hdbscan_cluster_selection_epsilon: float = Field(
        default=0.45,
        description="Cluster selection epsilon for HDBSCAN. Distance = 1 - similarity. 0.45 allows 55%+ similarity pairs.",
    )
    max_representatives_per_cluster: int = Field(
        default=10,
        description="Maximum number of representatives to maintain per cluster.",
    )
    pose_diversity_bonus: int = Field(
        default=3,
        description="Extra representatives allowed for novel head poses beyond max_representatives_per_cluster.",
    )
    pose_bucket_size: float = Field(
        default=30.0,
        description="Degrees per pose bucket for novelty detection.",
    )
    representative_diversity_threshold: float = Field(
        default=0.85,
        description="Maximum similarity allowed between representatives (lower adds diversity).",
    )
    anchor_discovery_threshold: float = Field(
        default=0.40,
        description="Relaxed threshold for anchor-linked graph components (lowered from 0.50).",
    )
    anchor_split_similarity_floor: float = Field(
        default=0.60,
        description="Minimum similarity to keep identities with the anchor during forced splits.",
    )
    fatal_confidence_floor: float = Field(
        default=0.30,
        description="Minimum detection confidence below which suggestions are suppressed.",
    )
    fatal_quality_floor: float = Field(
        default=0.20,
        description="Minimum quality score below which suggestions are suppressed.",
    )


class HACSettings(BaseModel):
    """Settings for constrained HAC refinement.

    Per instructions.md: Use pydantic.BaseModel with hardcoded defaults,
    NOT pydantic-settings. Override by instantiation, not .env files.
    """

    model_config = ConfigDict(frozen=True)

    linkage_method: str = Field(
        default="median",
        description="HAC linkage method. 'median' per Apple paper.",
    )
    distance_threshold: float = Field(
        default=0.45,
        description="Maximum distance for cluster formation (regular HAC on noise). 0.45 = 55% similarity. Lowered from 0.25.",
    )
    singleton_distance_threshold: float = Field(
        default=0.55,
        description="Maximum distance for singleton HAC refinement. 0.55 = 45% similarity. Matches observed same-person min similarity.",
    )
    constraint_penalty: float = Field(
        default=1.0,
        description="Distance penalty for cannot-link pairs. Must be > distance_threshold.",
    )
    max_scope_size: int = Field(
        default=500,
        description="Maximum identities in single HAC run (O(n^2) constraint).",
    )
    knn_neighborhood: int = Field(
        default=50,
        description="kNN neighborhood size for scoped HAC.",
    )
