"""Tests for ConfidenceCheck behavior on adaptive thresholds."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import numpy as np
import pytest

from recognition.application.assignment.candidate import AssignmentCandidate, DiscoveryMethod
from recognition.application.assignment.checks.confidence import ConfidenceCheck
from recognition.application.settings import ClusteringSettings
from recognition.domain.identity import MediaIdentity
from recognition.domain.maturity import ClusterMaturityInfo, ClusterMaturityLevel
from recognition.shared.ids import generate_id


def make_settings() -> ClusteringSettings:
    return ClusteringSettings(
        similarity_threshold=0.75,
        suggestion_floor=0.65,
        suggestion_ceiling=0.75,
        early_stage_suggestion_enabled=True,
        early_stage_high_confidence_threshold=0.90,  # Legacy param, mostly unused now
    )


def make_candidate(
    similarity: float,
    confidence: float = 0.9,
    bbox_size: int = 100,
    pose_angle: float = 0.0,
    cluster_id: str = "cluster-1",
) -> AssignmentCandidate:
    """Create a candidate with specific metrics."""
    identity = MediaIdentity(
        id=str(generate_id()),
        tenant_id=str(generate_id()),
        media_id=str(generate_id()),
        embedding=np.zeros(128, dtype=np.float32),
        confidence=confidence,
        bbox_width=bbox_size,
        bbox_height=bbox_size,
        pose_pitch=pose_angle,
        pose_yaw=0.0,
        pose_roll=0.0,
    )
    return AssignmentCandidate(
        identity=identity,
        identity_vector=np.zeros(128, dtype=np.float32),
        cluster_id=cluster_id,
        discovery_method=DiscoveryMethod.REPRESENTATIVE,
        discovery_similarity=similarity,
    )


def make_maturity_info(level: ClusterMaturityLevel, adjustment: float) -> ClusterMaturityInfo:
    return ClusterMaturityInfo(
        level=level, identity_count=10, representative_count=5, user_confirmed=False, threshold_adjustment=adjustment
    )


@pytest.mark.asyncio
async def test_confidence_mature_cluster_high_quality() -> None:
    """Mature cluster (-0.05) + High Quality (-0.05) -> Threshold relaxes significantly."""
    settings = make_settings()
    repo = Mock()
    # Mock maturity info: MATURE
    repo.get_maturity_info = AsyncMock(return_value=make_maturity_info(ClusterMaturityLevel.MATURE, -0.05))
    repo.get_curriculum_t = AsyncMock(return_value=0.5)

    check = ConfidenceCheck(settings, repo)

    # Candidate: High confidence, large face, frontal
    candidate = make_candidate(similarity=0.68, confidence=0.99, bbox_size=200, pose_angle=0)

    # Base: 0.75
    # Maturity Adj: -0.05
    # Quality Adj: -0.05 (for score > 0.9)
    # Curriculum Adj: -0.025 (t=0.5)
    # Final Threshold: 0.75 - 0.125 = 0.625

    # Candidate similarity 0.68 should PASS
    result = await check.evaluate(candidate)

    assert result.passed is True
    assert result.metadata["final_threshold"] == 0.625
    assert result.metadata["maturity_adj"] == -0.05
    assert result.metadata["quality_adj"] == -0.05


@pytest.mark.asyncio
async def test_confidence_cold_cluster_low_quality() -> None:
    """Cold cluster (0.0) + Low Quality (+0.0125) -> Threshold tightens."""
    settings = make_settings()
    repo = Mock()
    # Mock maturity info: COLD
    repo.get_maturity_info = AsyncMock(return_value=make_maturity_info(ClusterMaturityLevel.COLD, 0.0))
    repo.get_curriculum_t = AsyncMock(return_value=0.5)

    check = ConfidenceCheck(settings, repo)

    # Candidate: Low confidence (but still valid identity), small face
    # Note: Quality logic: small face (<50px) penalty.
    candidate = make_candidate(similarity=0.73, confidence=0.8, bbox_size=40, pose_angle=0)

    # Base: 0.75
    # Maturity Adj: 0.0
    # Quality Adj: +0.0125 (for poor quality, dampened by COLD)
    # Curriculum Adj: -0.025 (t=0.5)
    # Final Threshold: 0.75 - 0.0125 = 0.7375

    # Candidate similarity 0.73 should FAIL
    result = await check.evaluate(candidate)

    assert result.passed is False
    assert result.metadata["final_threshold"] == 0.7375
    assert result.metadata["maturity_adj"] == 0.0
    assert result.metadata["quality_adj"] == pytest.approx(0.0125, abs=0.0001)


@pytest.mark.asyncio
async def test_confidence_no_repo_defaults_to_cold() -> None:
    """If repository is missing, assume COLD cluster (0.0)."""
    settings = make_settings()
    check = ConfidenceCheck(settings, None)

    candidate = make_candidate(similarity=0.74, confidence=0.8, bbox_size=100)  # Neutral quality (0.0)

    # Base: 0.75
    # Maturity Adj: 0.0 (Default COLD)
    # Quality Adj: 0.0 (Neutral)
    # Final: 0.75

    # 0.74 should fail
    result = await check.evaluate(candidate)
    assert result.passed is False
    assert result.metadata["final_threshold"] == 0.75
    assert result.metadata["maturity_level"] == "COLD (no_repo)"


@pytest.mark.asyncio
async def test_confidence_anchor_linked_bypass() -> None:
    """Anchor linked candidates bypass checks."""
    check = ConfidenceCheck(make_settings(), None)
    candidate = make_candidate(similarity=0.1)
    candidate.anchor_linked = True

    result = await check.evaluate(candidate)
    assert result.passed is True
    assert result.metadata["bypass_reason"] == "anchor_linked_transitivity"


@pytest.mark.asyncio
async def test_confidence_suggestion_band_returns_suggest() -> None:
    """Similarity within suggestion band should produce a suggest outcome."""
    settings = ClusteringSettings(
        similarity_threshold=0.8,
        suggestion_floor=0.7,
        suggestion_ceiling=0.8,
        early_stage_suggestion_enabled=True,
    )
    check = ConfidenceCheck(settings, None)
    candidate = make_candidate(similarity=0.74, confidence=0.9, bbox_size=100)

    result = await check.evaluate(candidate)

    assert result.passed is False
    assert result.should_reject is False


@pytest.mark.asyncio
async def test_confidence_fatal_quality_failure_rejects() -> None:
    """Extremely low quality should reject before suggestions."""
    settings = ClusteringSettings(
        similarity_threshold=0.8,
        suggestion_floor=0.7,
        suggestion_ceiling=0.8,
        early_stage_suggestion_enabled=True,
    )
    check = ConfidenceCheck(settings, None)
    candidate = make_candidate(similarity=0.78, confidence=0.2, bbox_size=20, pose_angle=0.0)

    result = await check.evaluate(candidate)

    assert result.passed is False
    assert result.should_reject is True
    assert result.reason == "fatal_quality_failure"
    assert result.metadata["fatal_quality_failure"] is True
