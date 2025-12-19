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
    """Mature cluster (-0.03) + High Quality (-0.05) -> Threshold relaxes significantly."""
    settings = make_settings()
    repo = Mock()
    # Mock maturity info: MATURE
    repo.get_maturity_info = AsyncMock(return_value=make_maturity_info(ClusterMaturityLevel.MATURE, -0.03))

    check = ConfidenceCheck(settings, repo)

    # Candidate: High confidence, large face, frontal
    candidate = make_candidate(similarity=0.68, confidence=0.99, bbox_size=200, pose_angle=0)

    # Base: 0.75
    # Maturity Adj: -0.03
    # Quality Adj: -0.05 (for score > 0.9)
    # Final Threshold: 0.75 - 0.08 = 0.67

    # Candidate similarity 0.68 should PASS
    result = await check.evaluate(candidate)

    assert result.passed is True
    assert result.metadata["final_threshold"] == 0.67
    assert result.metadata["maturity_adj"] == -0.03
    assert result.metadata["quality_adj"] == -0.05


@pytest.mark.asyncio
async def test_confidence_cold_cluster_low_quality() -> None:
    """Cold cluster (+0.05) + Low Quality (+0.05) -> Threshold tightens."""
    settings = make_settings()
    repo = Mock()
    # Mock maturity info: COLD
    repo.get_maturity_info = AsyncMock(return_value=make_maturity_info(ClusterMaturityLevel.COLD, 0.05))

    check = ConfidenceCheck(settings, repo)

    # Candidate: Low confidence (but still valid identity), small face
    # Note: Quality logic: small face (<50px) penalty.
    candidate = make_candidate(similarity=0.80, confidence=0.8, bbox_size=40, pose_angle=0)

    # Base: 0.75
    # Maturity Adj: +0.05
    # Quality Adj: +0.05 (for poor quality)
    # Final Threshold: 0.75 + 0.10 = 0.85

    # Candidate similarity 0.80 should FAIL
    result = await check.evaluate(candidate)

    assert result.passed is False
    assert result.metadata["final_threshold"] == 0.85
    assert result.metadata["maturity_adj"] == 0.05
    assert result.metadata["quality_adj"] == 0.05


@pytest.mark.asyncio
async def test_confidence_no_repo_defaults_to_cold() -> None:
    """If repository is missing, assume COLD cluster (+0.05)."""
    settings = make_settings()
    check = ConfidenceCheck(settings, None)

    candidate = make_candidate(similarity=0.79, confidence=0.8, bbox_size=100)  # Neutral quality (0.0)

    # Base: 0.75
    # Maturity Adj: +0.05 (Default COLD)
    # Quality Adj: 0.0 (Neutral)
    # Final: 0.80

    # 0.79 should fail
    result = await check.evaluate(candidate)
    assert result.passed is False
    assert result.metadata["final_threshold"] == 0.80
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
