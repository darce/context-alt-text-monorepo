"""Canonical clustering-related thresholds and heuristics."""

from __future__ import annotations

import math
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
    similarity_threshold: float = 0.75  # Raised from 0.70 - must exceed 0.75 to prevent false positives
    max_reps_per_media: int = 2
    min_diversity_similarity: float = 0.85
    quality_weight: float = 0.7
    diversity_weight: float = 0.3
    borderline_window: float = 0.05
    centroid_match_threshold: float = 0.85  # Raised from 0.78 - must pass same bar as member validation
    ward_sync_batch_limit: int = 20
    normalization_atol: float = 1e-5
    auto_merge_threshold: float = 0.6
    auto_merge_max_iterations: int = 3
    ward_async_max_identities: int = 5000
    auto_merge_enabled: bool = True
    auto_merge_max_identities: int = 2000

    # === Validation Thresholds ===
    borderline_upper_threshold: float = 0.80  # Matches below this trigger validation (raised from 0.75)
    borderline_validation_threshold: float = 0.70  # Centroid similarity must be at least this (raised from 0.65)
    borderline_validation_enabled: bool = True  # Enable centroid validation for borderline matches
    # Member validation (additional check for all rep matches)
    member_validation_enabled: bool = True  # Check similarity with random existing members
    member_validation_sample_size: int = 3  # Number of random members to check
    member_validation_threshold: float = 0.85  # Raised from 0.76 - reject lookalike false positives (0.81-0.84 range)
    # Minimum floor for ANY sampled member (prevents false positive from avg hiding low outlier)
    # If min_member_similarity < this floor, reject even if avg passes
    member_validation_min_floor: float = 0.82  # Raised from 0.74 - any member below this triggers rejection
    # Suggestion tier (borderline matches between suggestion and accept thresholds)
    suggestion_enabled: bool = True  # Enable suggestion tier for borderline matches
    suggestion_threshold: float = 0.55  # Min avg_member_similarity for suggesting (below member_validation_threshold)

    # === Chinese Whispers Settings ===
    cw_threshold: float = 0.82  # Stricter threshold for graph edges (raised from 0.75)
    cw_iterations: int = 20

    # === Confidence Weighting (Option C) ===
    confidence_weighting_enabled: bool = True  # Enable adaptive thresholds based on detection quality
    confidence_midpoint: float = 0.85  # Confidence level at which no adjustment occurs
    threshold_max_adjustment: float = 0.10  # Maximum threshold change in either direction
    min_bbox_area: int = 10000  # Minimum bbox area for full size confidence

    # === Algorithm Selection ===
    use_hdbscan_for_outliers: bool = False  # Use HDBSCAN to recluster singletons
    hdbscan_min_cluster_size: int = 2  # Minimum cluster size for HDBSCAN
    hdbscan_min_samples: int = 1  # Minimum samples for HDBSCAN core points
    hdbscan_max_batch_size: int = 500  # Max batch size for HDBSCAN; larger batches use Chinese Whispers
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

    # === Early Stage Suggestion Guard ===
    # During early training, borderline matches create suggestions instead of auto-merging.
    # This prevents false positives when cluster centroids/representatives aren't stable yet.
    early_stage_suggestion_enabled: bool = True  # Create suggestions for borderline matches during early training
    early_stage_high_confidence_threshold: float = 0.90  # Only auto-assign if similarity >= this during early stage
    # Note: early_stage_maturity_point reuses adaptive_threshold_maturity_point (30 labeled clusters)

    # === Complete-Link Guard ===
    # Structural validation: new faces must match ALL representatives, not just the nearest one.
    # A lookalike might be 0.92 to one photo but 0.80 to another angle—complete-link catches this.
    complete_link_enabled: bool = True  # Enable complete-link validation against all representatives
    complete_link_min_floor: float = 0.75  # Every rep must have similarity >= this (even the worst match)
    complete_link_avg_threshold: float = 0.85  # Average similarity across all reps must be >= this

    # === Adaptive Thresholds (Curriculum Learning inspired) ===
    # Start strict with few clusters, relax as system matures.
    # Rationale: With few examples, false positives are catastrophic and can't be undone.
    # With many clusters, centroids are well-defined and borderline matches can be validated.
    adaptive_threshold_strict: float = 0.88  # Maximum threshold when no clusters exist (raised from 0.85)
    adaptive_threshold_maturity_point: int = 30  # Cluster count at which threshold stabilizes
    adaptive_threshold_decay_rate: float = 3.0  # Exponential decay rate (higher = faster stabilization)

    def compute_adaptive_threshold(self, cluster_count: int) -> float:
        """Compute adaptive similarity threshold based on cluster maturity.

        Uses exponential decay from strict to base threshold as clusters grow.
        Inspired by CurricularFace: "address easy samples first, hard ones later".

        For clustering, we invert this: be strict early (avoid false positives when
        no ground truth exists), relax as the system learns (centroids become reliable).

        Args:
            cluster_count: Number of existing clusters for the tenant.

        Returns:
            Adjusted similarity threshold between base and strict.

        Examples:
            - 0 clusters: 0.88 (maximum strictness)
            - 5 clusters: ~0.82
            - 15 clusters: ~0.77
            - 30+ clusters: ~0.75 (base threshold)
        """
        if cluster_count == 0:
            return self.adaptive_threshold_strict

        # Exponential decay from strict to base threshold
        # At maturity_point clusters, ~95% of adjustment has decayed
        rate = self.adaptive_threshold_decay_rate / self.adaptive_threshold_maturity_point
        adjustment = (self.adaptive_threshold_strict - self.similarity_threshold) * math.exp(-rate * cluster_count)

        return self.similarity_threshold + adjustment

    def compute_adaptive_member_validation_threshold(self, cluster_count: int) -> float:
        """Compute adaptive member validation threshold.

        Member validation threshold follows same adaptive curve but offset slightly
        higher than similarity threshold to maintain validation strictness.
        """
        base_adaptive = self.compute_adaptive_threshold(cluster_count)
        # Member validation threshold is always 0.01 above adaptive similarity threshold
        # but capped at the strict setting
        return min(base_adaptive + 0.01, self.adaptive_threshold_strict)

    def compute_adaptive_cw_threshold(self, cluster_count: int) -> float:
        """Compute adaptive Chinese Whispers edge threshold.

        CW threshold follows same adaptive curve but offset slightly higher
        to ensure graph edges require strong similarity.
        """
        base_adaptive = self.compute_adaptive_threshold(cluster_count)
        # CW threshold is always 0.03 above adaptive similarity threshold
        # but capped at the strict setting
        return min(base_adaptive + 0.03, self.adaptive_threshold_strict + 0.03)

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
            member_validation_min_floor=getattr(cfg, "member_validation_min_floor", cls.member_validation_min_floor),
            suggestion_enabled=getattr(cfg, "suggestion_enabled", cls.suggestion_enabled),
            suggestion_threshold=getattr(cfg, "suggestion_threshold", cls.suggestion_threshold),
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
            hdbscan_max_batch_size=getattr(cfg, "hdbscan_max_batch_size", cls.hdbscan_max_batch_size),
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
            # Early stage suggestion guard
            early_stage_suggestion_enabled=getattr(
                cfg, "early_stage_suggestion_enabled", cls.early_stage_suggestion_enabled
            ),
            early_stage_high_confidence_threshold=getattr(
                cfg, "early_stage_high_confidence_threshold", cls.early_stage_high_confidence_threshold
            ),
            # Adaptive thresholds
            adaptive_threshold_strict=getattr(cfg, "adaptive_threshold_strict", cls.adaptive_threshold_strict),
            adaptive_threshold_maturity_point=getattr(
                cfg, "adaptive_threshold_maturity_point", cls.adaptive_threshold_maturity_point
            ),
            adaptive_threshold_decay_rate=getattr(
                cfg, "adaptive_threshold_decay_rate", cls.adaptive_threshold_decay_rate
            ),
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
