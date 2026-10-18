"""Tests for pose coverage in maturity level computation."""

import pytest

from recognition.application.settings.clustering import MaturitySettings
from recognition.domain.maturity import ClusterMaturityLevel, compute_maturity_level


class TestPoseCoverageMaturity:
    """Test that pose coverage affects MATURE level eligibility."""

    def test_cluster_without_pose_coverage_stays_nascent(self) -> None:
        """A cluster with enough members/reps but no pose diversity should not be MATURE."""
        settings = MaturitySettings(
            mature_min_members=10,
            mature_min_representatives=3,
            mature_min_pose_coverage=0.3,  # Require 30% coverage
        )

        # 15 members, 5 reps, but only 1 pose bucket filled (7.7% coverage)
        level = compute_maturity_level(
            identity_count=15,
            representative_count=5,
            user_confirmed=False,
            settings=settings,
            pose_bucket_coverage=0.077,  # 1/13 buckets
        )

        assert level == ClusterMaturityLevel.NASCENT

    def test_cluster_with_pose_coverage_becomes_mature(self) -> None:
        """A cluster meeting all requirements including pose coverage should be MATURE."""
        settings = MaturitySettings(
            mature_min_members=10,
            mature_min_representatives=3,
            mature_min_pose_coverage=0.3,
        )

        # 15 members, 5 reps, 5 pose buckets filled (38% coverage)
        level = compute_maturity_level(
            identity_count=15,
            representative_count=5,
            user_confirmed=False,
            settings=settings,
            pose_bucket_coverage=0.385,  # 5/13 buckets
        )

        assert level == ClusterMaturityLevel.MATURE

    def test_user_confirmed_bypasses_pose_coverage(self) -> None:
        """User confirmation should override pose coverage requirement."""
        settings = MaturitySettings(
            mature_min_pose_coverage=0.3,
        )

        # User confirmed, even with zero pose coverage
        level = compute_maturity_level(
            identity_count=5,
            representative_count=2,
            user_confirmed=True,
            settings=settings,
            pose_bucket_coverage=0.0,
        )

        assert level == ClusterMaturityLevel.CONFIRMED

    def test_edge_case_exactly_at_threshold(self) -> None:
        """Exactly meeting pose coverage threshold should qualify for MATURE."""
        settings = MaturitySettings(
            mature_min_members=10,
            mature_min_representatives=3,
            mature_min_pose_coverage=0.3,
        )

        level = compute_maturity_level(
            identity_count=10,
            representative_count=3,
            user_confirmed=False,
            settings=settings,
            pose_bucket_coverage=0.3,  # Exactly at threshold
        )

        assert level == ClusterMaturityLevel.MATURE

    def test_below_threshold_by_epsilon(self) -> None:
        """Just below pose coverage threshold should NOT qualify for MATURE."""
        settings = MaturitySettings(
            mature_min_members=10,
            mature_min_representatives=3,
            mature_min_pose_coverage=0.3,
        )

        level = compute_maturity_level(
            identity_count=10,
            representative_count=3,
            user_confirmed=False,
            settings=settings,
            pose_bucket_coverage=0.29,  # Just below threshold
        )

        assert level == ClusterMaturityLevel.NASCENT

    def test_default_pose_coverage_zero_still_works(self) -> None:
        """Without pose_bucket_coverage arg, should default to 0 (backward compat)."""
        settings = MaturitySettings(
            mature_min_members=10,
            mature_min_representatives=3,
            mature_min_pose_coverage=0.0,  # Disabled
        )

        # Default pose_bucket_coverage=0.0 should work with disabled requirement
        level = compute_maturity_level(
            identity_count=15,
            representative_count=5,
            user_confirmed=False,
            settings=settings,
            # pose_bucket_coverage defaults to 0.0
        )

        assert level == ClusterMaturityLevel.MATURE

    def test_nascent_not_affected_by_pose_coverage(self) -> None:
        """NASCENT level should not consider pose coverage."""
        settings = MaturitySettings(
            nascent_min_members=2,
            mature_min_members=10,
            mature_min_pose_coverage=0.3,
        )

        # Below mature member count, pose coverage shouldn't matter
        level = compute_maturity_level(
            identity_count=5,
            representative_count=2,
            user_confirmed=False,
            settings=settings,
            pose_bucket_coverage=0.0,  # No coverage
        )

        assert level == ClusterMaturityLevel.NASCENT

    def test_cold_not_affected_by_pose_coverage(self) -> None:
        """COLD level should not consider pose coverage."""
        settings = MaturitySettings(
            nascent_min_members=3,
            mature_min_pose_coverage=0.3,
        )

        level = compute_maturity_level(
            identity_count=1,
            representative_count=1,
            user_confirmed=False,
            settings=settings,
            pose_bucket_coverage=1.0,  # 100% coverage shouldn't help
        )

        assert level == ClusterMaturityLevel.COLD
