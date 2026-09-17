"""
Clustering and assignment thresholds for the recognition service.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Canonical no-op enrollment triple (FIR-6 S3b / EMB-07). Single source for
# QualitySettings defaults, FacePipelineSettings dark defaults, EnrollmentFloors.is_noop,
# and insightface profile-gating of factor floors.
ENROLLMENT_NOOP_FLOOR_SHARPNESS = 0.0
ENROLLMENT_NOOP_FLOOR_EMBEDDING_NORM = 0.0
ENROLLMENT_NOOP_CEILING_OCCLUSION = 1.0


class QualitySettings(BaseModel):
    """Settings for identity quality scoring.

    Controls how detection quality affects clustering thresholds.
    """

    model_config = ConfigDict(frozen=True)

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

    # FIR-6 S1 OACT channel (bridged from FacePipelineSettings via profile helper).
    # Default 0.0 ⇒ dark no-op until S4 calibration apply-commit.
    # ge=0: negative coefficient would *reward* occlusion (FIR6RC-01 / FIR6S1-M-02).
    oact_coefficient: float = Field(
        default=0.0,
        ge=0.0,
        description="Occlusion-adaptive coefficient for threshold_adjustment (0.0 = no-op).",
    )

    # FIR-6 S3b enrollment floors (bridged from FacePipelineSettings; no-op defaults).
    # floors accept everything; ceiling accepts full [0, 1] until S4.
    factor_floor_sharpness: float = Field(
        default=ENROLLMENT_NOOP_FLOOR_SHARPNESS,
        ge=0.0,
        description="Enrollment sharpness floor (0.0 accepts everything until S4).",
    )
    factor_floor_embedding_norm: float = Field(
        default=ENROLLMENT_NOOP_FLOOR_EMBEDDING_NORM,
        ge=0.0,
        description="Enrollment embedding-norm floor (0.0 accepts everything until S4).",
    )
    factor_ceiling_occlusion: float = Field(
        default=ENROLLMENT_NOOP_CEILING_OCCLUSION,
        ge=0.0,
        le=1.0,
        description="Enrollment occlusion ceiling (1.0 accepts full range until S4).",
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
    low_confidence_band_width: float = Field(
        default=0.05,
        description="Derived low-confidence band width below suggestion_floor (effective floor = suggestion_floor - width).",
    )
    low_confidence_suggestion_floor: float | None = Field(
        default=None,
        description="Optional explicit override for low-confidence floor. When unset, derived from suggestion_floor - low_confidence_band_width.",
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
    recovery_merge_enabled: bool = Field(
        default=False,
        description=(
            "ACX_RECOVERY_MERGE_ENABLED. Pairwise recovery merge after singleton HAC. "
            "Default off until the C1 calibration policy is accepted."
        ),
    )
    merge_undo_window_days: int = Field(
        default=7,
        ge=1,
        description="ACX_MERGE_UNDO_WINDOW_DAYS. Receipt undo window in days; never a client constant.",
    )
    recovery_max_residual_size: int = Field(
        default=3,
        ge=1,
        description="Maximum identity_count for a residual cluster eligible for recovery merge.",
    )

    @model_validator(mode="after")
    def _validate_low_confidence_thresholds(self) -> ClusteringSettings:
        """Ensure low-confidence thresholds cannot exceed the primary suggestion floor."""
        if self.low_confidence_band_width < 0:
            raise ValueError("low_confidence_band_width must be >= 0")
        if (
            self.low_confidence_suggestion_floor is not None
            and self.low_confidence_suggestion_floor > self.suggestion_floor
        ):
            raise ValueError("low_confidence_suggestion_floor must be <= suggestion_floor")
        return self

    @property
    def effective_low_confidence_suggestion_floor(self) -> float:
        """Return the effective low-confidence floor used for suggestion surfacing."""
        if self.low_confidence_suggestion_floor is not None:
            return self.low_confidence_suggestion_floor
        return max(0.0, self.suggestion_floor - self.low_confidence_band_width)


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


class CalibrationApplyMode(StrEnum):
    """apply_mode vocabulary for the C1 recovery-calibration policy (sr-007)."""

    DISABLED_UNTIL_ACCEPTED = "disabled_until_accepted"
    ACCEPTED = "accepted"


class CalibrationPolicyStatus(StrEnum):
    """status vocabulary for the C1 recovery-calibration policy (sr-007)."""

    NEEDS_OPERATOR = "needs_operator"
    ACCEPTED = "accepted"


class _ForbidModel(BaseModel):
    """Strict nested policy node: unknown keys fail closed (CALIBR-M-06)."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class CalibrationBinding(_ForbidModel):
    embedding_model_id: str
    embedding_model_revision: str
    embedding_dimensionality: str | int
    distance_metric: str
    dataset_manifest_digest: str
    calibration_run_digest: str
    require_all_runtime_fields_match: bool
    apply_only_when: str


class InclusiveBand(_ForbidModel):
    min_inclusive: float | None = None
    max_inclusive: float | None = None
    max_exclusive: float | None = None


class QualityScoreBandCuts(_ForbidModel):
    high: InclusiveBand
    neutral: InclusiveBand
    mediocre: InclusiveBand
    poor: InclusiveBand


class SimilarityBandCuts(_ForbidModel):
    reject_below: float
    low_confidence_suggestion: InclusiveBand
    suggestion: InclusiveBand
    accept_at_or_above: float


class BandCuts(_ForbidModel):
    quality_score: QualityScoreBandCuts
    similarity: SimilarityBandCuts


class SuggestionBandCuts(_ForbidModel):
    low_confidence_floor: float
    suggestion_floor: float
    suggestion_ceiling: float


class StratumResolution(_ForbidModel):
    key: str
    floor_precedence: list[str]
    rule: str
    abstention: str


class PerStratumFloors(_ForbidModel):
    key_format: str
    base: float
    quality_band_defaults: dict[str, float]
    operating_condition_defaults: dict[str, float]
    cell_overrides: dict[str, float]


class PolicyAcceptance(_ForbidModel):
    reject_all_abstained: bool
    minimum_non_abstained_strata_with_floor: int
    apply_mode_exit_requires: str


class PolicyAbstain(_ForbidModel):
    rule: str


class AbstainedStrata(_ForbidModel):
    key_format: str
    selection: str
    quality_bands: list[str]
    operating_conditions: list[str]


class FalseNameInterval(_ForbidModel):
    method: str
    confidence: float


class FalseNameAcceptanceGate(_ForbidModel):
    max_automatic_false_name_accepts: int
    max_observed_rate: float
    interval: FalseNameInterval
    fail_if: str


class RepresentativeWeights(_ForbidModel):
    occlusion: float
    detector_confidence: float
    face_size: float


class RepresentativePolicy(_ForbidModel):
    status: str
    weights: RepresentativeWeights
    weights_sum: float


class EvaluationPolicy(_ForbidModel):
    calibration_identities_disjoint_from_evaluation: bool
    required_metrics: list[str]
    no_same_image_exemplar_credit: bool
    noise_is_unassigned: bool


class ClusterRecoveryCalibrationPolicy(_ForbidModel):
    """Typed C1 recovery-calibration policy. Unknown keys fail (CALIBR-M-06)."""

    schema_version: int
    rule_version: str
    status: CalibrationPolicyStatus
    apply_mode: CalibrationApplyMode
    binding: CalibrationBinding
    tau_pair: float
    tau_intra: float
    recovery_margin: float
    margin_delta: float
    delta: float
    k: int
    min_agreeing_exemplars: int
    band_cuts: BandCuts
    suggestion_band_cuts: SuggestionBandCuts
    stratum_resolution: StratumResolution
    per_stratum_floors: PerStratumFloors
    acceptance: PolicyAcceptance
    min_pairs: int
    abstain: PolicyAbstain
    abstained_strata: AbstainedStrata
    false_name_acceptance_gate: FalseNameAcceptanceGate
    k_occ: float
    representative: RepresentativePolicy
    evaluation: EvaluationPolicy

    def abstained_cells(self) -> frozenset[str]:
        """Return the closed set of abstained ``<quality_band>×<operating_condition>`` cells."""
        strata = self.abstained_strata
        if strata.selection != "cartesian_product":
            return frozenset()
        return frozenset(
            f"{band}×{condition}" for band in strata.quality_bands for condition in strata.operating_conditions
        )


class EmbeddingSpaceBinding(_ForbidModel):
    """Runtime embedding-space binding compared against the policy (CALIBR-M-05)."""

    embedding_model_id: str
    embedding_model_revision: str
    embedding_dimensionality: int
    distance_metric: str
    dataset_manifest_digest: str
    calibration_run_digest: str


# Verbatim C1 machine-readable policy block
# (docs/assessments/GPUFLOW-2-cluster-recovery-calibration-20260916.md).
CLUSTER_RECOVERY_CALIBRATION_POLICY_BLOCK: dict[str, Any] = {
    "schema_version": 1,
    "rule_version": "GPUFLOW-2-C1-provisional-20260916",
    "status": "needs_operator",
    "apply_mode": "disabled_until_accepted",
    "binding": {
        "embedding_model_id": "unbound",
        "embedding_model_revision": "unbound",
        "embedding_dimensionality": "unbound",
        "distance_metric": "cosine",
        "dataset_manifest_digest": "unbound",
        "calibration_run_digest": "unbound",
        "require_all_runtime_fields_match": True,
        "apply_only_when": ("all binding fields match the runtime embedding space and calibration artifacts"),
    },
    "tau_pair": 0.55,
    "tau_intra": 0.45,
    "recovery_margin": 0.05,
    "margin_delta": 0.05,
    "delta": 0.05,
    "k": 2,
    "min_agreeing_exemplars": 2,
    "band_cuts": {
        "quality_score": {
            "high": {"min_inclusive": 0.90, "max_inclusive": 1.00},
            "neutral": {"min_inclusive": 0.80, "max_exclusive": 0.90},
            "mediocre": {"min_inclusive": 0.60, "max_exclusive": 0.80},
            "poor": {"min_inclusive": 0.00, "max_exclusive": 0.60},
        },
        "similarity": {
            "reject_below": 0.30,
            "low_confidence_suggestion": {"min_inclusive": 0.30, "max_exclusive": 0.35},
            "suggestion": {"min_inclusive": 0.35, "max_exclusive": 0.55},
            "accept_at_or_above": 0.55,
        },
    },
    "suggestion_band_cuts": {
        "low_confidence_floor": 0.30,
        "suggestion_floor": 0.35,
        "suggestion_ceiling": 0.55,
    },
    "stratum_resolution": {
        "key": "<quality_band>×<operating_condition>",
        "floor_precedence": [
            "exact cell floor",
            "both quality-band and operating-condition defaults",
            "one quality-band or operating-condition default",
            "base floor",
        ],
        "rule": (
            "most specific floor wins; if both axis defaults apply without an exact cell floor, use the higher floor"
        ),
        "abstention": "any abstained quality or operating axis abstains the cell",
    },
    "per_stratum_floors": {
        "key_format": "<quality_band>×<operating_condition>",
        "base": 0.55,
        "quality_band_defaults": {
            "high": 0.55,
            "neutral": 0.55,
            "mediocre": 0.57,
            "poor": 0.60,
        },
        "operating_condition_defaults": {
            "clear": 0.55,
            "profile": 0.55,
            "sunglasses": 0.55,
            "masked": 0.60,
            "occlusion_other": 0.60,
            "low_res": 0.60,
            "blur": 0.60,
            "similar_people": 0.60,
            "unknown": 0.60,
        },
        "cell_overrides": {},
    },
    "acceptance": {
        "reject_all_abstained": True,
        "minimum_non_abstained_strata_with_floor": 1,
        "apply_mode_exit_requires": (
            "at least one non-abstained <quality_band>×<operating_condition> cell "
            "with a floor and all acceptance gates passing"
        ),
    },
    "min_pairs": 2,
    "abstain": {
        "rule": (
            "abstain the whole residual when any member is in an abstained "
            "<quality_band>×<operating_condition> cell, has fewer than min_pairs "
            "labelled pairs, fails its cell floor, lacks k distinct-media exemplars, "
            "fails tau_intra, misses recovery_margin against the runner-up, or "
            "conflicts with a confirmed named identity"
        ),
    },
    "abstained_strata": {
        "key_format": "<quality_band>×<operating_condition>",
        "selection": "cartesian_product",
        "quality_bands": ["high", "neutral", "mediocre", "poor"],
        "operating_conditions": [
            "clear",
            "profile",
            "sunglasses",
            "masked",
            "occlusion_other",
            "low_res",
            "blur",
            "similar_people",
            "unknown",
        ],
    },
    "false_name_acceptance_gate": {
        "max_automatic_false_name_accepts": 0,
        "max_observed_rate": 0.0,
        "interval": {"method": "Wilson", "confidence": 0.95},
        "fail_if": ("any non-abstained stratum has an observed automatic false-name acceptance or lacks its interval"),
    },
    "k_occ": 0.0,
    "representative": {
        "status": "proposed_not_current_runtime",
        "weights": {
            "occlusion": 0.0,
            "detector_confidence": 0.6,
            "face_size": 0.4,
        },
        "weights_sum": 1.0,
    },
    "evaluation": {
        "calibration_identities_disjoint_from_evaluation": True,
        "required_metrics": [
            "pairwise_precision",
            "pairwise_recall",
            "bcubed_precision",
            "bcubed_recall",
            "false_merges",
            "fragmentation",
            "unknown_absorption",
            "rejected_singleton_fraction",
            "insertion_order_stability",
            "far",
            "frr",
            "false_accept_interval",
        ],
        "no_same_image_exemplar_credit": True,
        "noise_is_unassigned": True,
    },
}

_UNBOUND = "unbound"


def load_cluster_recovery_calibration_policy(
    raw: Mapping[str, Any],
) -> ClusterRecoveryCalibrationPolicy:
    """Parse a calibration policy mapping. Unknown keys fail closed (CALIBR-M-06)."""
    return ClusterRecoveryCalibrationPolicy.model_validate(dict(raw))


def default_cluster_recovery_calibration_policy() -> ClusterRecoveryCalibrationPolicy:
    """Return the verbatim C1 policy block as a typed object."""
    return load_cluster_recovery_calibration_policy(CLUSTER_RECOVERY_CALIBRATION_POLICY_BLOCK)


def _binding_field_matches(policy_value: str | int, runtime_value: str | int) -> bool:
    if isinstance(policy_value, str) and policy_value == _UNBOUND:
        return False
    return str(policy_value) == str(runtime_value)


def calibration_policy_is_applicable(
    policy: ClusterRecoveryCalibrationPolicy,
    runtime: EmbeddingSpaceBinding,
) -> bool:
    """True only when apply_mode is accepted and the embedding-space binding matches.

    Unbound policy fields, a binding mismatch, or an all-abstained policy keep
    apply_mode effectively disabled (CALIBR-M-05). The stored apply_mode is not
    mutated.
    """
    if policy.apply_mode is not CalibrationApplyMode.ACCEPTED:
        return False
    binding = policy.binding
    matches = (
        _binding_field_matches(binding.embedding_model_id, runtime.embedding_model_id)
        and _binding_field_matches(binding.embedding_model_revision, runtime.embedding_model_revision)
        and _binding_field_matches(binding.embedding_dimensionality, runtime.embedding_dimensionality)
        and _binding_field_matches(binding.distance_metric, runtime.distance_metric)
        and _binding_field_matches(binding.dataset_manifest_digest, runtime.dataset_manifest_digest)
        and _binding_field_matches(binding.calibration_run_digest, runtime.calibration_run_digest)
    )
    if binding.require_all_runtime_fields_match and not matches:
        return False
    if not matches:
        return False
    if policy.acceptance.reject_all_abstained and not policy.abstained_cells():
        # Empty abstain set is the test/accepted case: every cell is eligible.
        return True
    if policy.acceptance.reject_all_abstained:
        quality_bands = ("high", "neutral", "mediocre", "poor")
        operating_conditions = tuple(policy.per_stratum_floors.operating_condition_defaults)
        abstained = policy.abstained_cells()
        eligible = [
            f"{band}×{condition}"
            for band in quality_bands
            for condition in operating_conditions
            if f"{band}×{condition}" not in abstained
        ]
        if len(eligible) < policy.acceptance.minimum_non_abstained_strata_with_floor:
            return False
    return True


def quality_band_for_score(score: float, policy: ClusterRecoveryCalibrationPolicy) -> str | None:
    """Map a quality_score onto the policy's quality band, or None if it misses every cut."""
    bands = policy.band_cuts.quality_score
    for name in ("high", "neutral", "mediocre", "poor"):
        cut = getattr(bands, name)
        if cut.min_inclusive is not None and score < cut.min_inclusive:
            continue
        if cut.max_inclusive is not None and score > cut.max_inclusive:
            continue
        if cut.max_exclusive is not None and score >= cut.max_exclusive:
            continue
        return name
    return None


def stratum_cell_key(quality_band: str, operating_condition: str) -> str:
    return f"{quality_band}×{operating_condition}"


def stratum_is_abstained(
    quality_band: str,
    operating_condition: str,
    policy: ClusterRecoveryCalibrationPolicy,
) -> bool:
    return stratum_cell_key(quality_band, operating_condition) in policy.abstained_cells()


def stratum_pair_floor(
    quality_band: str,
    operating_condition: str,
    policy: ClusterRecoveryCalibrationPolicy,
) -> float:
    """Most specific floor wins; both-axis defaults take the higher floor."""
    floors = policy.per_stratum_floors
    cell_key = stratum_cell_key(quality_band, operating_condition)
    if cell_key in floors.cell_overrides:
        return float(floors.cell_overrides[cell_key])
    quality_floor = floors.quality_band_defaults.get(quality_band)
    condition_floor = floors.operating_condition_defaults.get(operating_condition)
    if quality_floor is not None and condition_floor is not None:
        return float(max(quality_floor, condition_floor))
    if quality_floor is not None:
        return float(quality_floor)
    if condition_floor is not None:
        return float(condition_floor)
    return float(floors.base)
