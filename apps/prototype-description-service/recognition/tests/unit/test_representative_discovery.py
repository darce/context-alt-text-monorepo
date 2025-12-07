"""Tests for RepresentativeDiscovery candidate generation."""

from __future__ import annotations

import numpy as np
import pytest

from recognition.application.assignment.candidate import AssignmentCandidate, DiscoveryMethod
from recognition.application.discovery.representative import RepresentativeDiscovery
from recognition.application.settings import ClusteringSettings
from recognition.domain.identity import MediaIdentity
from recognition.shared.ids import generate_id


def make_settings(threshold: float = 0.8) -> ClusteringSettings:
    """Create clustering settings for representative discovery tests."""
    return ClusteringSettings(
        similarity_threshold=threshold,
        complete_link_min_floor=0.75,
        complete_link_avg_threshold=0.85,
        min_representatives_for_maturity=2,
        member_validation_min_floor=0.8,
        member_validation_avg_threshold=0.85,
        early_stage_suggestion_enabled=True,
        early_stage_high_confidence_threshold=0.9,
        adaptive_threshold_maturity_point=5,
        hdbscan_max_batch_size=None,
    )


def make_identity(vec: np.ndarray) -> MediaIdentity:
    """Construct a MediaIdentity with the given embedding."""
    return MediaIdentity(
        id=str(generate_id()),
        tenant_id=str(generate_id()),
        media_id=str(generate_id()),
        embedding=vec,
        confidence=0.95,
        bbox_width=100,
        bbox_height=100,
    )


def normalize(vec: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vec))
    return vec.astype(np.float32) / norm


@pytest.mark.asyncio
async def test_representative_discovery_returns_candidate_above_threshold() -> None:
    """Should return a candidate for the best matching cluster above threshold."""
    cluster_id = str(generate_id())
    identity = make_identity(normalize(np.array([1.0, 0.0, 0.0])))
    representatives = {cluster_id: [normalize(np.array([0.9, 0.1, 0.0]))]}

    discovery = RepresentativeDiscovery(settings=make_settings(threshold=0.8))
    candidates = await discovery.discover([identity], representatives)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert isinstance(candidate, AssignmentCandidate)
    assert candidate.cluster_id == cluster_id
    assert candidate.discovery_method is DiscoveryMethod.REPRESENTATIVE
    assert candidate.discovery_similarity >= 0.8


@pytest.mark.asyncio
async def test_representative_discovery_skips_below_threshold() -> None:
    """Should yield no candidates when similarity is below threshold."""
    cluster_id = str(generate_id())
    identity = make_identity(normalize(np.array([1.0, 0.0, 0.0])))
    representatives = {cluster_id: [normalize(np.array([0.0, 1.0, 0.0]))]}

    discovery = RepresentativeDiscovery(settings=make_settings(threshold=0.9))
    candidates = await discovery.discover([identity], representatives)

    assert candidates == []
