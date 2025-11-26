"""Canonical clustering-related thresholds and heuristics."""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class ClusteringSettings:
    """Centralized knobs for clustering quality and safety.

    Organized into sections:
    - Similarity Thresholds: Core matching thresholds
    - Validation: Borderline and member validation
    - Chinese Whispers: CW-specific parameters
    - Confidence Weighting: Option C adaptive thresholds (NEW)
    - Algorithm Selection: Two-pass and hybrid modes (NEW)
    - Auto-Tuning: Self-adjusting thresholds (NEW)
    - Session Inference: Color histogram sessions (NEW)
    """

    # === Similarity Thresholds ===
    similarity_threshold: float = 0.65  # Raised from 0.60 to prevent false positives
    max_reps_per_media: int = 2
    min_diversity_similarity: float = 0.85
    quality_weight: float = 0.7
    diversity_weight: float = 0.3
    borderline_window: float = 0.05
    centroid_match_threshold: float = 0.73  # Threshold for centroid-based matching fallback
    ward_sync_batch_limit: int = 20
    normalization_atol: float = 1e-5
    auto_merge_threshold: float = 0.6
    auto_merge_max_iterations: int = 3
    ward_async_max_identities: int = 5000
    auto_merge_enabled: bool = True
    auto_merge_max_identities: int = 2000

    # === Validation Thresholds ===
    borderline_upper_threshold: float = 0.70  # Matches below this trigger validation
    borderline_validation_threshold: float = (
        0.60  # Centroid similarity must be at least this (lowered from 0.65 to prevent FNs)
    )
    borderline_validation_enabled: bool = True  # Enable centroid validation for borderline matches
    # Member validation (additional check for all rep matches)
    member_validation_enabled: bool = True  # Check similarity with random existing members
    member_validation_sample_size: int = 3  # Number of random members to check
    member_validation_threshold: float = 0.68  # Raised from 0.65 to prevent cluster drift

    # === Chinese Whispers Settings ===
    cw_threshold: float = 0.75  # Stricter threshold for graph edges
    cw_iterations: int = 20

    # === Confidence Weighting (Option C) ===
    confidence_weighting_enabled: bool = False  # Enable adaptive thresholds based on detection quality
    confidence_midpoint: float = 0.85  # Confidence level at which no adjustment occurs
    threshold_max_adjustment: float = 0.10  # Maximum threshold change in either direction
    min_bbox_area: int = 10000  # Minimum bbox area for full size confidence

    # === Algorithm Selection ===
    use_hdbscan_for_outliers: bool = False  # Use HDBSCAN to recluster singletons
    hdbscan_min_cluster_size: int = 2  # Minimum cluster size for HDBSCAN
    hdbscan_min_samples: int = 1  # Minimum samples for HDBSCAN core points
    two_pass_enabled: bool = False  # Enable two-pass clustering (conservative + HAC merge)
    pass1_threshold: float = 0.75  # Conservative threshold for Pass 1
    pass2_merge_threshold: float = 0.65  # HAC merge threshold for Pass 2

    # === Auto-Tuning ===
    auto_tune_enabled: bool = False  # Enable automatic threshold adjustment
    threshold_min: float = 0.50  # Lower bound for auto-tuned threshold
    threshold_max: float = 0.80  # Upper bound for auto-tuned threshold
    auto_tune_target_acceptance: float = 0.70  # Target suggestion acceptance rate

    # === Session Inference ===
    session_boost_enabled: bool = False  # Boost similarity for same-session faces
    session_similarity_threshold: float = 0.85  # Scene signature similarity for session grouping
    session_boost_amount: float = 0.05  # Amount to boost similarity for same-session faces

    @classmethod
    def from_config(cls, cfg, similarity_override: float | None = None) -> ClusteringSettings:
        """
        Build settings from an IdentityClusteringSettings-like config object.

        similarity_override lets callers respect per-request thresholds while keeping other knobs consistent.
        """

        return cls(
            similarity_threshold=similarity_override if similarity_override is not None else cfg.similarity_threshold,
            max_reps_per_media=cfg.max_reps_per_media,
            min_diversity_similarity=cfg.min_diversity_similarity,
            quality_weight=cfg.quality_weight,
            diversity_weight=cfg.diversity_weight,
            borderline_window=cfg.borderline_window,
            ward_sync_batch_limit=cfg.ward_sync_batch_limit,
            centroid_match_threshold=getattr(cfg, "centroid_match_threshold", cls.centroid_match_threshold),
            normalization_atol=cfg.normalization_atol,
            auto_merge_threshold=cfg.auto_merge_threshold,
            auto_merge_max_iterations=cfg.auto_merge_max_iterations,
            auto_merge_enabled=getattr(cfg, "auto_merge_enabled", True),
            ward_async_max_identities=getattr(cfg, "ward_async_max_identities", cls.ward_async_max_identities),
            auto_merge_max_identities=getattr(cfg, "auto_merge_max_identities", cls.auto_merge_max_identities),
            borderline_upper_threshold=getattr(cfg, "borderline_upper_threshold", cls.borderline_upper_threshold),
            borderline_validation_threshold=getattr(
                cfg, "borderline_validation_threshold", cls.borderline_validation_threshold
            ),
            borderline_validation_enabled=getattr(
                cfg, "borderline_validation_enabled", cls.borderline_validation_enabled
            ),
            member_validation_enabled=getattr(cfg, "member_validation_enabled", cls.member_validation_enabled),
            member_validation_sample_size=getattr(
                cfg, "member_validation_sample_size", cls.member_validation_sample_size
            ),
            member_validation_threshold=getattr(cfg, "member_validation_threshold", cls.member_validation_threshold),
            cw_threshold=getattr(cfg, "cw_threshold", cls.cw_threshold),
            cw_iterations=getattr(cfg, "cw_iterations", cls.cw_iterations),
            # Confidence weighting (Option C)
            confidence_weighting_enabled=getattr(cfg, "confidence_weighting_enabled", cls.confidence_weighting_enabled),
            confidence_midpoint=getattr(cfg, "confidence_midpoint", cls.confidence_midpoint),
            threshold_max_adjustment=getattr(cfg, "threshold_max_adjustment", cls.threshold_max_adjustment),
            min_bbox_area=getattr(cfg, "min_bbox_area", cls.min_bbox_area),
            # Algorithm selection
            use_hdbscan_for_outliers=getattr(cfg, "use_hdbscan_for_outliers", cls.use_hdbscan_for_outliers),
            hdbscan_min_cluster_size=getattr(cfg, "hdbscan_min_cluster_size", cls.hdbscan_min_cluster_size),
            hdbscan_min_samples=getattr(cfg, "hdbscan_min_samples", cls.hdbscan_min_samples),
            two_pass_enabled=getattr(cfg, "two_pass_enabled", cls.two_pass_enabled),
            pass1_threshold=getattr(cfg, "pass1_threshold", cls.pass1_threshold),
            pass2_merge_threshold=getattr(cfg, "pass2_merge_threshold", cls.pass2_merge_threshold),
            # Auto-tuning
            auto_tune_enabled=getattr(cfg, "auto_tune_enabled", cls.auto_tune_enabled),
            threshold_min=getattr(cfg, "threshold_min", cls.threshold_min),
            threshold_max=getattr(cfg, "threshold_max", cls.threshold_max),
            auto_tune_target_acceptance=getattr(cfg, "auto_tune_target_acceptance", cls.auto_tune_target_acceptance),
            # Session inference
            session_boost_enabled=getattr(cfg, "session_boost_enabled", cls.session_boost_enabled),
            session_similarity_threshold=getattr(cfg, "session_similarity_threshold", cls.session_similarity_threshold),
            session_boost_amount=getattr(cfg, "session_boost_amount", cls.session_boost_amount),
        )

    @classmethod
    def with_overrides(cls, base: ClusteringSettings, **overrides) -> ClusteringSettings:
        """Create new settings with specific overrides.

        This is useful for temporarily modifying settings without mutating the original.

        Example:
            >>> base = ClusteringSettings()
            >>> stricter = ClusteringSettings.with_overrides(base, similarity_threshold=0.75)
            >>> stricter.similarity_threshold
            0.75
        """
        return replace(base, **overrides)
