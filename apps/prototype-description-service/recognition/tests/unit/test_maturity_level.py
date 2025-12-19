"""Tests for cluster maturity level computation."""

import pytest

from recognition.domain.maturity import (
    ClusterMaturityLevel,
    compute_maturity_adjustment,
    compute_maturity_level,
)


class TestComputeMaturityLevel:
    def test_cold_singleton_not_confirmed(self) -> None:
        level = compute_maturity_level(identity_count=1, representative_count=1, user_confirmed=False)
        assert level == ClusterMaturityLevel.COLD

    def test_nascent_small_cluster(self) -> None:
        level = compute_maturity_level(identity_count=3, representative_count=2, user_confirmed=False)
        assert level == ClusterMaturityLevel.NASCENT

    def test_confirmed_overrides_size(self) -> None:
        # Even a singleton becomes CONFIRMED when user confirms
        level = compute_maturity_level(identity_count=1, representative_count=1, user_confirmed=True)
        assert level == ClusterMaturityLevel.CONFIRMED

    def test_mature_large_diverse_cluster(self) -> None:
        level = compute_maturity_level(identity_count=15, representative_count=5, user_confirmed=False)
        assert level == ClusterMaturityLevel.MATURE


class TestComputeMaturityAdjustment:
    @pytest.mark.parametrize(
        "level,expected",
        [
            (ClusterMaturityLevel.COLD, 0.05),
            (ClusterMaturityLevel.NASCENT, 0.02),
            (ClusterMaturityLevel.CONFIRMED, -0.02),
            (ClusterMaturityLevel.MATURE, -0.03),
        ],
    )
    def test_adjustment_values(self, level: ClusterMaturityLevel, expected: float) -> None:
        assert compute_maturity_adjustment(level) == pytest.approx(expected)
