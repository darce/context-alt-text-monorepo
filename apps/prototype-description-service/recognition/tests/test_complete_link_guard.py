"""Tests for complete-link validation guard.

The complete-link guard ensures new faces match ALL representatives of a cluster,
not just the nearest one. This catches lookalikes who might match one photo
(e.g., same angle/lighting) but not others.
"""

import numpy as np
import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from recognition.application.clustering.clustering_settings import ClusteringSettings
from recognition.application.representatives.representative_matcher import RepresentativeMatcher


def make_mock_identity(embedding: np.ndarray) -> MagicMock:
    """Create a mock MediaIdentity with the given embedding."""
    identity = MagicMock()
    identity.id = uuid4()
    identity.tenant_id = uuid4()
    identity.confidence = 0.95
    identity.bbox_width = 200
    identity.bbox_height = 200
    identity.embedding = embedding.tolist()
    return identity


def normalize(v: np.ndarray) -> np.ndarray:
    """Normalize a vector to unit length."""
    return v / np.linalg.norm(v)


class TestCompleteLinkGuard:
    """Tests for complete-link validation logic."""

    @pytest.fixture
    def settings_enabled(self) -> ClusteringSettings:
        """Settings with complete-link enabled."""
        return ClusteringSettings(
            complete_link_enabled=True,
            complete_link_min_floor=0.75,
            complete_link_avg_threshold=0.85,
        )

    @pytest.fixture
    def settings_disabled(self) -> ClusteringSettings:
        """Settings with complete-link disabled."""
        return ClusteringSettings(complete_link_enabled=False)

    @pytest.fixture
    def matcher(self, settings_enabled: ClusteringSettings) -> RepresentativeMatcher:
        """Create a RepresentativeMatcher for testing."""
        return RepresentativeMatcher(
            threshold=0.75,
            add_representative_embedding=AsyncMock(return_value=None),
            assign_to_cluster_by_id=AsyncMock(),
            settings=settings_enabled,
            labeled_cluster_count=50,  # Past maturity point
        )

    def test_passes_when_all_reps_similar(self, matcher: RepresentativeMatcher) -> None:
        """Complete-link should pass when candidate matches all representatives well."""
        cluster_id = uuid4()
        
        # Create representatives with similar orientation
        base = normalize(np.array([1.0, 0.0, 0.0] + [0.0] * 509))
        rep1 = normalize(base + normalize(np.random.randn(512)) * 0.1)
        rep2 = normalize(base + normalize(np.random.randn(512)) * 0.1)
        rep3 = normalize(base + normalize(np.random.randn(512)) * 0.1)
        
        representatives_by_cluster = {
            cluster_id: [rep1, rep2, rep3],
        }
        
        # Candidate very similar to base
        candidate = normalize(base + normalize(np.random.randn(512)) * 0.05)
        
        passed, min_sim, avg_sim = matcher._check_complete_link(
            candidate,
            cluster_id,
            representatives_by_cluster,
        )
        
        assert passed is True
        assert min_sim >= 0.75  # All reps above floor
        assert avg_sim >= 0.85  # Average above threshold

    def test_fails_when_one_rep_differs(self, matcher: RepresentativeMatcher) -> None:
        """Complete-link should fail when candidate doesn't match one representative."""
        cluster_id = uuid4()
        
        # Create representatives with different orientations
        rep1 = normalize(np.array([1.0, 0.0, 0.0] + [0.0] * 509))  # Front view
        rep2 = normalize(np.array([0.0, 1.0, 0.0] + [0.0] * 509))  # Side view
        rep3 = normalize(np.array([1.0, 0.0, 0.0] + [0.0] * 509))  # Front view
        
        representatives_by_cluster = {
            cluster_id: [rep1, rep2, rep3],
        }
        
        # Candidate matches front views well but not side view
        candidate = normalize(np.array([0.95, 0.1, 0.0] + [0.0] * 509))
        
        passed, min_sim, avg_sim = matcher._check_complete_link(
            candidate,
            cluster_id,
            representatives_by_cluster,
        )
        
        # Should fail because min_sim to side view rep is low
        assert min_sim < 0.75  # Below floor
        assert passed is False

    def test_skips_when_single_rep(self, matcher: RepresentativeMatcher) -> None:
        """Complete-link should skip when cluster has only one representative."""
        cluster_id = uuid4()
        
        rep = normalize(np.random.randn(512))
        representatives_by_cluster = {
            cluster_id: [rep],
        }
        
        # Candidate is somewhat similar
        candidate = normalize(rep + normalize(np.random.randn(512)) * 0.3)
        
        passed, min_sim, avg_sim = matcher._check_complete_link(
            candidate,
            cluster_id,
            representatives_by_cluster,
        )
        
        # Should skip (pass) when not enough reps for meaningful check
        assert passed is True
        assert min_sim == 1.0  # Sentinel value
        assert avg_sim == 1.0

    def test_skips_when_disabled(self, settings_disabled: ClusteringSettings) -> None:
        """Complete-link should skip when disabled in settings."""
        matcher = RepresentativeMatcher(
            threshold=0.75,
            add_representative_embedding=AsyncMock(return_value=None),
            assign_to_cluster_by_id=AsyncMock(),
            settings=settings_disabled,
            labeled_cluster_count=50,
        )
        
        cluster_id = uuid4()
        
        # Create very different representatives
        rep1 = normalize(np.array([1.0, 0.0, 0.0] + [0.0] * 509))
        rep2 = normalize(np.array([0.0, 1.0, 0.0] + [0.0] * 509))
        
        representatives_by_cluster = {
            cluster_id: [rep1, rep2],
        }
        
        candidate = normalize(np.array([0.95, 0.1, 0.0] + [0.0] * 509))
        
        passed, min_sim, avg_sim = matcher._check_complete_link(
            candidate,
            cluster_id,
            representatives_by_cluster,
        )
        
        # Should skip (pass) when disabled
        assert passed is True

    def test_skips_when_no_settings(self) -> None:
        """Complete-link should skip when no settings provided."""
        matcher = RepresentativeMatcher(
            threshold=0.75,
            add_representative_embedding=AsyncMock(return_value=None),
            assign_to_cluster_by_id=AsyncMock(),
            settings=None,  # No settings
        )
        
        cluster_id = uuid4()
        rep1 = normalize(np.random.randn(512))
        rep2 = normalize(np.random.randn(512))
        
        representatives_by_cluster = {
            cluster_id: [rep1, rep2],
        }
        
        candidate = normalize(np.random.randn(512))
        
        passed, min_sim, avg_sim = matcher._check_complete_link(
            candidate,
            cluster_id,
            representatives_by_cluster,
        )
        
        # Should skip (pass) when no settings
        assert passed is True


@pytest.mark.asyncio
class TestCompleteLinkMatchIntegration:
    """Integration tests for complete-link in the match workflow."""

    async def test_creates_suggestion_when_complete_link_fails(self) -> None:
        """Match should create suggestion instead of auto-assign when complete-link fails."""
        settings = ClusteringSettings(
            complete_link_enabled=True,
            complete_link_min_floor=0.80,  # High floor
            complete_link_avg_threshold=0.90,  # High average
            # Disable early stage guard for this test
            early_stage_suggestion_enabled=False,
        )
        
        create_suggestion = AsyncMock()
        assign_to_cluster = AsyncMock()
        add_representative = AsyncMock(return_value=None)
        
        matcher = RepresentativeMatcher(
            threshold=0.70,
            add_representative_embedding=add_representative,
            assign_to_cluster_by_id=assign_to_cluster,
            settings=settings,
            create_suggestion=create_suggestion,
            labeled_cluster_count=50,  # Past maturity
        )
        
        cluster_id = uuid4()
        
        # Create representatives that are different from each other
        rep1 = normalize(np.array([1.0, 0.0, 0.0] + [0.0] * 509))
        rep2 = normalize(np.array([0.7, 0.7, 0.0] + [0.0] * 509))  # 45 degree angle
        
        representatives_by_cluster = {
            cluster_id: [rep1, rep2],
        }
        
        # Candidate matches rep1 well but not rep2
        candidate_embedding = normalize(np.array([0.98, 0.1, 0.0] + [0.0] * 509))
        candidate = make_mock_identity(candidate_embedding)
        
        assigned, unclustered, _ = await matcher.match(
            [candidate],
            representatives_by_cluster,
            borderline_upper=0.80,
        )
        
        # Should create suggestion, not auto-assign
        assert assigned == 0
        assert create_suggestion.called
        assert not assign_to_cluster.called
        # Candidate not in unclustered because it got a suggestion
        assert len(unclustered) == 0
