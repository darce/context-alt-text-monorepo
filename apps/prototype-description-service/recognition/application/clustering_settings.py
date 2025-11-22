"""Canonical clustering-related thresholds and heuristics."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ClusteringSettings:
    """Centralized knobs for clustering quality and safety."""

    similarity_threshold: float = 0.6
    max_reps_per_media: int = 2
    min_diversity_similarity: float = 0.85
    quality_weight: float = 0.7
    diversity_weight: float = 0.3
    borderline_window: float = 0.05
    ward_sync_batch_limit: int = 100
    normalization_atol: float = 1e-5
    auto_merge_threshold: float = 0.6
    auto_merge_max_iterations: int = 3
    ward_async_max_identities: int = 5000
    auto_merge_enabled: bool = True
    auto_merge_max_identities: int = 2000

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
            normalization_atol=cfg.normalization_atol,
            auto_merge_threshold=cfg.auto_merge_threshold,
            auto_merge_max_iterations=cfg.auto_merge_max_iterations,
            auto_merge_enabled=getattr(cfg, "auto_merge_enabled", True),
            ward_async_max_identities=getattr(cfg, "ward_async_max_identities", cls.ward_async_max_identities),
            auto_merge_max_identities=getattr(cfg, "auto_merge_max_identities", cls.auto_merge_max_identities),
        )
