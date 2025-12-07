"""Tests for ConfidenceCheck behavior on discovery similarity thresholds."""

from __future__ import annotations

import numpy as np
import pytest

from recognition.application.assignment.candidate import AssignmentCandidate, DiscoveryMethod
from recognition.application.assignment.checks.confidence import ConfidenceCheck
from recognition.application.settings import ClusteringSettings
from recognition.domain.identity import MediaIdentity
from recognition.shared.ids import generate_id


def make_settings(enabled: bool = True) -> ClusteringSettings:
    """Create settings with configurable enablement."""
    return ClusteringSettings(
        similarity_threshold=0.75,
        complete_link_min_floor=0.75,
        complete_link_avg_threshold=0.85,
        min_representatives_for_maturity=2,
        member_validation_min_floor=0.8,
        member_validation_avg_threshold=0.85,
        early_stage_suggestion_enabled=enabled,
        early_stage_high_confidence_threshold=0.9,
        adaptive_threshold_maturity_point=5,
        hdbscan_max_batch_size=None,
    )


def make_candidate(similarity: float) -> AssignmentCandidate:
    """Create a candidate with a specified discovery similarity."""
    identity = MediaIdentity(
        id=str(generate_id()),
        tenant_id=str(generate_id()),
        media_id=str(generate_id()),
        embedding=np.ones(4, dtype=np.float32),
        confidence=0.9,
        bbox_width=10,
        bbox_height=12,
    )
    return AssignmentCandidate(
        identity=identity,
        identity_vector=np.ones(4, dtype=np.float32),
        cluster_id=str(generate_id()),
        discovery_method=DiscoveryMethod.REPRESENTATIVE,
        discovery_similarity=similarity,
    )


@pytest.mark.asyncio
async def test_confidence_passes_when_above_threshold() -> None:
    """Should pass when discovery similarity meets the high-confidence threshold."""
    check = ConfidenceCheck(settings=make_settings(enabled=True))
    result = await check.evaluate(make_candidate(0.95))

    assert result.passed is True
    assert result.is_fatal is False


@pytest.mark.asyncio
async def test_confidence_suggests_when_below_threshold() -> None:
    """Should produce a fatal suggestion when similarity is below threshold."""
    check = ConfidenceCheck(settings=make_settings(enabled=True))
    result = await check.evaluate(make_candidate(0.5))

    assert result.passed is False
    assert result.is_fatal is True
    assert result.should_reject is False
    assert result.reason is not None
    assert result.metadata is not None
    assert result.metadata["discovery_similarity"] == 0.5


def test_confidence_disabled_when_flag_off() -> None:
    """is_enabled should be False when early-stage suggestions are disabled."""
    check = ConfidenceCheck(settings=make_settings(enabled=False))
    assert check.is_enabled() is False
