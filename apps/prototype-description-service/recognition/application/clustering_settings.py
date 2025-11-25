"""Canonical clustering-related thresholds and heuristics."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ClusteringSettings:
    """Centralized knobs for clustering quality and safety."""

    similarity_threshold: float = 0.65  # Raised from 0.60 to prevent false positives
    max_reps_per_media: int = 2
    min_diversity_similarity: float = 0.85
    quality_weight: float = 0.7
    diversity_weight: float = 0.3
    borderline_window: float = 0.05
    centroid_match_threshold: float = 0.73  # NEW: Threshold for centroid-based matching fallback
    ward_sync_batch_limit: int = 20
    normalization_atol: float = 1e-5
    auto_merge_threshold: float = 0.6
    auto_merge_max_iterations: int = 3
    ward_async_max_identities: int = 5000
    auto_merge_enabled: bool = True
    auto_merge_max_identities: int = 2000
    # Validation thresholds
    borderline_upper_threshold: float = 0.70  # Matches below this trigger validation
    borderline_validation_threshold: float = (
        0.60  # Centroid similarity must be at least this (lowered from 0.65 to prevent FNs)
    )
    borderline_validation_enabled: bool = True  # Enable centroid validation for borderline matches
    # Member validation (additional check for all rep matches)
    member_validation_enabled: bool = True  # Check similarity with random existing members
    member_validation_sample_size: int = 3  # Number of random members to check
    member_validation_threshold: float = 0.68  # Raised from 0.65 to prevent cluster drift
    # Chinese Whispers settings
    cw_threshold: float = 0.75  # Stricter threshold for graph edges
    cw_iterations: int = 20

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
        )
