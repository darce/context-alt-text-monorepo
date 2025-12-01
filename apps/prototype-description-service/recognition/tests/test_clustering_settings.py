"""Tests for ClusteringSettings, especially adaptive threshold computation."""

import pytest

from recognition.application.clustering.clustering_settings import ClusteringSettings


class TestAdaptiveThreshold:
    """Test adaptive threshold computation based on cluster maturity."""

    def test_zero_clusters_returns_strict_threshold(self) -> None:
        """With no clusters, use maximum strictness."""
        settings = ClusteringSettings()
        threshold = settings.compute_adaptive_threshold(0)
        # Should return the configured strict threshold (not a hardcoded value)
        assert threshold == settings.adaptive_threshold_strict

    def test_few_clusters_returns_high_threshold(self) -> None:
        """With few clusters, threshold is closer to strict."""
        settings = ClusteringSettings()
        threshold_5 = settings.compute_adaptive_threshold(5)
        threshold_10 = settings.compute_adaptive_threshold(10)

        # Should be between base and strict
        assert settings.similarity_threshold < threshold_5 < settings.adaptive_threshold_strict
        assert settings.similarity_threshold < threshold_10 < settings.adaptive_threshold_strict

        # More clusters = lower threshold (closer to base)
        assert threshold_10 < threshold_5

    def test_mature_clusters_returns_base_threshold(self) -> None:
        """At maturity point, threshold should be close to base."""
        settings = ClusteringSettings()
        threshold = settings.compute_adaptive_threshold(settings.adaptive_threshold_maturity_point)

        # Should be very close to base threshold (within 0.01)
        assert abs(threshold - settings.similarity_threshold) < 0.01

    def test_many_clusters_returns_base_threshold(self) -> None:
        """Beyond maturity point, threshold converges to base."""
        settings = ClusteringSettings()
        threshold_50 = settings.compute_adaptive_threshold(50)
        threshold_100 = settings.compute_adaptive_threshold(100)

        # Both should be essentially at base threshold
        assert abs(threshold_50 - settings.similarity_threshold) < 0.005
        assert abs(threshold_100 - settings.similarity_threshold) < 0.005

    def test_threshold_monotonically_decreasing(self) -> None:
        """Threshold should decrease as cluster count increases."""
        settings = ClusteringSettings()
        thresholds = [settings.compute_adaptive_threshold(i) for i in range(50)]

        for i in range(1, len(thresholds)):
            assert thresholds[i] <= thresholds[i - 1], (
                f"Threshold should decrease: {thresholds[i - 1]} at {i - 1} vs {thresholds[i]} at {i}"
            )

    def test_custom_settings(self) -> None:
        """Test with custom adaptive threshold settings."""
        settings = ClusteringSettings(
            similarity_threshold=0.70,
            adaptive_threshold_strict=0.90,
            adaptive_threshold_maturity_point=20,
        )

        # Zero clusters = strict
        assert settings.compute_adaptive_threshold(0) == 0.90

        # Maturity point = close to base
        threshold_at_maturity = settings.compute_adaptive_threshold(20)
        assert abs(threshold_at_maturity - 0.70) < 0.01


class TestAdaptiveMemberValidationThreshold:
    """Test adaptive member validation threshold."""

    def test_member_validation_offset(self) -> None:
        """Member validation threshold should be slightly above similarity threshold."""
        settings = ClusteringSettings()

        for cluster_count in [0, 5, 10, 30, 50]:
            sim_threshold = settings.compute_adaptive_threshold(cluster_count)
            member_threshold = settings.compute_adaptive_member_validation_threshold(cluster_count)

            # Member validation should be 0.01 above similarity (capped at strict+0.01)
            expected = min(sim_threshold + 0.01, settings.adaptive_threshold_strict)
            assert abs(member_threshold - expected) < 0.001, (
                f"At {cluster_count} clusters: expected {expected}, got {member_threshold}"
            )


class TestAdaptiveCWThreshold:
    """Test adaptive Chinese Whispers threshold."""

    def test_cw_threshold_offset(self) -> None:
        """CW threshold should be above similarity threshold."""
        settings = ClusteringSettings()

        for cluster_count in [0, 5, 10, 30, 50]:
            sim_threshold = settings.compute_adaptive_threshold(cluster_count)
            cw_threshold = settings.compute_adaptive_cw_threshold(cluster_count)

            # CW threshold should be 0.03 above similarity
            expected = min(sim_threshold + 0.03, settings.adaptive_threshold_strict + 0.03)
            assert abs(cw_threshold - expected) < 0.001, (
                f"At {cluster_count} clusters: expected {expected}, got {cw_threshold}"
            )


class TestWithOverrides:
    """Test ClusteringSettings.with_overrides method."""

    def test_override_single_field(self) -> None:
        """Override a single field."""
        base = ClusteringSettings()
        modified = ClusteringSettings.with_overrides(base, similarity_threshold=0.80)

        assert modified.similarity_threshold == 0.80
        assert modified.adaptive_threshold_strict == base.adaptive_threshold_strict

    def test_override_multiple_fields(self) -> None:
        """Override multiple fields."""
        base = ClusteringSettings()
        modified = ClusteringSettings.with_overrides(
            base,
            similarity_threshold=0.80,
            adaptive_threshold_strict=0.90,
            adaptive_threshold_maturity_point=50,
        )

        assert modified.similarity_threshold == 0.80
        assert modified.adaptive_threshold_strict == 0.90
        assert modified.adaptive_threshold_maturity_point == 50

    def test_base_unchanged(self) -> None:
        """Original settings should remain unchanged after override."""
        base = ClusteringSettings()
        original_threshold = base.similarity_threshold
        _ = ClusteringSettings.with_overrides(base, similarity_threshold=0.99)

        assert base.similarity_threshold == original_threshold


class TestExpectedDefaultThresholds:
    """Document and verify the expected default threshold values.

    These tests serve as documentation and guard against accidental changes.
    If you intentionally change a default, update the corresponding test.
    """

    def test_core_similarity_thresholds(self) -> None:
        """Verify core similarity threshold defaults."""
        settings = ClusteringSettings()

        # Base threshold for representative matching
        assert settings.similarity_threshold == 0.75

        # Chinese Whispers graph edge threshold (stricter than base)
        assert settings.cw_threshold == 0.82

        # Centroid-based matching fallback threshold (raised to match member validation)
        assert settings.centroid_match_threshold == 0.85

    def test_member_validation_thresholds(self) -> None:
        """Verify member validation threshold defaults."""
        settings = ClusteringSettings()

        # Average similarity with existing members to auto-accept
        assert settings.member_validation_threshold == 0.85

        # Minimum floor - any member below this triggers rejection
        assert settings.member_validation_min_floor == 0.82

        # Borderline validation against centroid
        assert settings.borderline_validation_threshold == 0.70

    def test_suggestion_tier_thresholds(self) -> None:
        """Verify suggestion tier threshold defaults."""
        settings = ClusteringSettings()

        # Minimum avg_member_similarity to create a suggestion
        assert settings.suggestion_threshold == 0.55

        # Suggestion feature enabled by default
        assert settings.suggestion_enabled is True

    def test_adaptive_threshold_defaults(self) -> None:
        """Verify adaptive threshold configuration defaults."""
        settings = ClusteringSettings()

        # Strict threshold for cold start (0 clusters)
        assert settings.adaptive_threshold_strict == 0.88

        # Number of labeled clusters to reach maturity
        assert settings.adaptive_threshold_maturity_point == 30

    def test_early_stage_suggestion_guard_defaults(self) -> None:
        """Verify early-stage suggestion guard defaults."""
        settings = ClusteringSettings()

        # Early stage guard enabled by default
        assert settings.early_stage_suggestion_enabled is True

        # High confidence threshold for auto-assign during early stage
        assert settings.early_stage_high_confidence_threshold == 0.90
