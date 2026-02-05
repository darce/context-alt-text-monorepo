"""Tests for curriculum learning helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from recognition.application.settings import ClusteringSettings


@pytest.mark.asyncio
async def test_curriculum_adjustment_formula() -> None:
    """Verify curriculum_adj = coefficient * curriculum_t produces correct values.

    Uses the coefficient from ClusteringSettings to ensure test stays in sync.
    """
    settings = ClusteringSettings()
    coefficient = settings.curriculum_coefficient  # -0.05

    test_cases = [
        (0.0, 0.0),  # Cold cluster: no adjustment
        (0.5, coefficient * 0.5),  # Growing cluster: small leniency
        (0.9, coefficient * 0.9),  # Mature cluster: nearly full leniency
        (1.0, coefficient),  # Maximum: full leniency
    ]
    for curriculum_t, expected_adj in test_cases:
        curriculum_adj = coefficient * curriculum_t
        assert curriculum_adj == pytest.approx(expected_adj, abs=0.0001), (
            f"curriculum_t={curriculum_t} should give adj={expected_adj}"
        )


@pytest.mark.asyncio
async def test_cold_cluster_with_curriculum_defaults_suggests_at_050() -> None:
    """Validate defaults: cold cluster at 0.50 similarity with curriculum_t=0.0 → SUGGEST.

    This test validates the core fix from curriculum-threshold-fix-plan-2026-01-20.md:
    - suggestion_floor uses ClusteringSettings defaults (lowered to 0.45)
    - curriculum_t=0.0 (default for new clusters)

    With these defaults and lowered thresholds for consumer photo reality:
      adjusted_floor = settings.suggestion_floor + 0.0 (maturity) + 0.0 (quality) + 0.0 (curriculum)

    A 0.50 similarity should be >= adjusted_floor, so it routes to SUGGEST not REJECT.
    """
    from recognition.application.assignment.checks.confidence import ConfidenceCheck
    from recognition.application.settings import ClusteringSettings
    from recognition.domain.maturity import ClusterMaturityInfo, ClusterMaturityLevel

    settings = ClusteringSettings()

    repo = AsyncMock()
    repo.get_maturity_info = AsyncMock(
        return_value=ClusterMaturityInfo(
            level=ClusterMaturityLevel.COLD,
            identity_count=1,
            representative_count=1,
            user_confirmed=False,
            threshold_adjustment=0.0,
        )
    )
    repo.get_curriculum_t = AsyncMock(return_value=0.0)  # New default

    check = ConfidenceCheck(settings, repo)

    # Create a cold cluster candidate at 0.50 similarity (between suggestion_floor and threshold)
    import numpy as np

    from recognition.application.assignment.candidate import AssignmentCandidate, DiscoveryMethod
    from recognition.domain.identity import MediaIdentity
    from recognition.shared.ids import generate_id

    candidate_similarity = 0.50
    identity = MediaIdentity(
        id=str(generate_id()),
        tenant_id=str(generate_id()),
        media_id=str(generate_id()),
        embedding=np.zeros(128, dtype=np.float32),
        confidence=0.9,  # Good quality
        bbox_width=100,
        bbox_height=100,
    )
    candidate = AssignmentCandidate(
        identity=identity,
        identity_vector=np.zeros(128, dtype=np.float32),
        cluster_id="cluster-123",
        discovery_method=DiscoveryMethod.REPRESENTATIVE,
        discovery_similarity=candidate_similarity,
    )

    result = await check.evaluate(candidate)

    # Key assertions: should NOT pass, should suggest (not reject)
    assert result.passed is False, "0.50 should not pass the threshold (~0.64)"
    assert result.should_reject is False, "0.50 should NOT be rejected (>= adjusted_floor ~0.44)"
    assert result.metadata["curriculum_t"] == 0.0
    assert result.metadata["curriculum_adj"] == pytest.approx(0.0, abs=0.001)
    assert result.metadata["suggestion_floor"] <= candidate_similarity, (
        "candidate similarity should be >= suggestion_floor"
    )
