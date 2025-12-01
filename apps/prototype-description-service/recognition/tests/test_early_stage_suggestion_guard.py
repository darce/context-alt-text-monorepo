"""Tests for early-stage suggestion guard feature.

During early training (< maturity_point labeled clusters), borderline matches
should create suggestions instead of auto-assigning to prevent false positives.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import numpy as np
import pytest

from recognition.application.clustering.clustering_settings import ClusteringSettings
from recognition.application.representatives.representative_matcher import RepresentativeMatcher


def make_test_settings(
    early_stage_suggestion_enabled: bool = True,
    early_stage_high_confidence_threshold: float = 0.90,
    adaptive_threshold_maturity_point: int = 30,
    similarity_threshold: float = 0.75,
) -> ClusteringSettings:
    """Create test settings with early-stage suggestion guard configuration."""
    return ClusteringSettings(
        similarity_threshold=similarity_threshold,
        early_stage_suggestion_enabled=early_stage_suggestion_enabled,
        early_stage_high_confidence_threshold=early_stage_high_confidence_threshold,
        adaptive_threshold_maturity_point=adaptive_threshold_maturity_point,
    )


def make_matcher_for_early_stage_test(
    settings: ClusteringSettings,
    labeled_cluster_count: int,
) -> RepresentativeMatcher:
    """Create a matcher for testing early stage detection (no callbacks needed)."""

    # Simple lambdas for tests that don't call these methods
    async def noop_add_rep(*args: Any) -> None:
        pass

    async def noop_assign(*args: Any) -> None:
        pass

    return RepresentativeMatcher(
        threshold=0.75,
        add_representative_embedding=noop_add_rep,
        assign_to_cluster_by_id=noop_assign,
        settings=settings,
        labeled_cluster_count=labeled_cluster_count,
    )


class TestEarlyStageSuggestionGuard:
    """Tests for the early-stage suggestion guard in RepresentativeMatcher."""

    def test_is_early_stage_with_few_labeled_clusters(self) -> None:
        """Early stage detected when labeled clusters < maturity point."""
        settings = make_test_settings(adaptive_threshold_maturity_point=30)
        matcher = make_matcher_for_early_stage_test(settings, labeled_cluster_count=5)
        assert matcher._is_early_stage() is True

    def test_is_not_early_stage_with_many_labeled_clusters(self) -> None:
        """Not early stage when labeled clusters >= maturity point."""
        settings = make_test_settings(adaptive_threshold_maturity_point=30)
        matcher = make_matcher_for_early_stage_test(settings, labeled_cluster_count=35)
        assert matcher._is_early_stage() is False

    def test_is_early_stage_at_boundary(self) -> None:
        """Early stage at exactly maturity point - 1."""
        settings = make_test_settings(adaptive_threshold_maturity_point=30)
        matcher = make_matcher_for_early_stage_test(settings, labeled_cluster_count=29)
        assert matcher._is_early_stage() is True

    def test_is_not_early_stage_at_maturity(self) -> None:
        """Not early stage at exactly maturity point."""
        settings = make_test_settings(adaptive_threshold_maturity_point=30)
        matcher = make_matcher_for_early_stage_test(settings, labeled_cluster_count=30)
        assert matcher._is_early_stage() is False

    def test_early_stage_disabled_when_no_settings(self) -> None:
        """Early stage detection returns False when no settings provided."""

        async def noop_add_rep(*args: Any) -> None:
            pass

        async def noop_assign(*args: Any) -> None:
            pass

        matcher = RepresentativeMatcher(
            threshold=0.75,
            add_representative_embedding=noop_add_rep,
            assign_to_cluster_by_id=noop_assign,
            settings=None,
            labeled_cluster_count=5,
        )
        assert matcher._is_early_stage() is False


@pytest.mark.asyncio
class TestEarlyStageSuggestionCreation:
    """Tests for suggestion creation during early stage."""

    async def test_early_stage_borderline_creates_suggestion(self) -> None:
        """During early stage, borderline match creates suggestion instead of auto-assign."""
        from types import SimpleNamespace
        from typing import cast

        settings = make_test_settings(
            early_stage_suggestion_enabled=True,
            early_stage_high_confidence_threshold=0.90,
            similarity_threshold=0.75,
        )

        # Track what was called
        assigned_identities: list[Any] = []
        suggestions_created: list[Any] = []

        async def mock_assign(identity: Any, vector: Any, cluster_id: Any, similarity: Any) -> None:
            assigned_identities.append((identity.id, cluster_id, similarity))

        async def mock_add_rep(cluster_id: Any, identity: Any) -> None:
            return None

        async def mock_create_suggestion(identity_id: Any, cluster_id: Any, rep_sim: Any, avg_sim: Any) -> None:
            suggestions_created.append((identity_id, cluster_id, rep_sim, avg_sim))

        matcher = RepresentativeMatcher(
            threshold=0.75,
            add_representative_embedding=mock_add_rep,
            assign_to_cluster_by_id=mock_assign,
            settings=settings,
            create_suggestion=mock_create_suggestion,
            labeled_cluster_count=5,  # Early stage
        )

        # Create a test identity
        identity = SimpleNamespace(
            id=uuid4(),
            tenant_id=uuid4(),
            embedding=np.array([1.0] + [0.0] * 1023, dtype=np.float32).tolist(),
            confidence=0.9,
            media_id=1,
            bbox_width=100,
            bbox_height=100,
        )

        # Create a cluster with a representative that matches at 0.85 (borderline)
        cluster_id = uuid4()
        # This vector will produce ~0.85 similarity with the identity
        rep_vector = np.array([0.85] + [0.0] * 1022 + [0.527], dtype=np.float32)
        rep_vector = rep_vector / np.linalg.norm(rep_vector)

        representatives_by_cluster = {cluster_id: [rep_vector]}

        # Run matching (cast to Any to satisfy type checker in tests)
        assigned, unclustered, _ = await matcher.match(
            candidates=cast(Any, [identity]),
            representatives_by_cluster=representatives_by_cluster,
        )

        # Should create suggestion, not assign
        # Identity is NOT in unclustered because it has a pending suggestion
        # and should not be processed by Chinese Whispers
        assert assigned == 0
        assert len(unclustered) == 0  # Has pending suggestion, not unclustered
        assert len(suggestions_created) == 1
        assert len(assigned_identities) == 0

        # Verify suggestion details
        suggestion = suggestions_created[0]
        assert suggestion[0] == identity.id  # identity_id
        assert suggestion[1] == cluster_id  # cluster_id

    async def test_early_stage_high_confidence_auto_assigns(self) -> None:
        """During early stage, high-confidence match still auto-assigns."""
        from types import SimpleNamespace
        from typing import cast

        settings = make_test_settings(
            early_stage_suggestion_enabled=True,
            early_stage_high_confidence_threshold=0.90,
            similarity_threshold=0.75,
        )

        assigned_identities: list[Any] = []
        suggestions_created: list[Any] = []

        async def mock_assign(identity: Any, vector: Any, cluster_id: Any, similarity: Any) -> None:
            assigned_identities.append((identity.id, cluster_id, similarity))

        async def mock_add_rep(cluster_id: Any, identity: Any) -> None:
            return None

        async def mock_create_suggestion(identity_id: Any, cluster_id: Any, rep_sim: Any, avg_sim: Any) -> None:
            suggestions_created.append((identity_id, cluster_id, rep_sim, avg_sim))

        matcher = RepresentativeMatcher(
            threshold=0.75,
            add_representative_embedding=mock_add_rep,
            assign_to_cluster_by_id=mock_assign,
            settings=settings,
            create_suggestion=mock_create_suggestion,
            labeled_cluster_count=5,  # Early stage
        )

        # Create a test identity
        identity = SimpleNamespace(
            id=uuid4(),
            tenant_id=uuid4(),
            embedding=np.array([1.0] + [0.0] * 1023, dtype=np.float32).tolist(),
            confidence=0.9,
            media_id=1,
            bbox_width=100,
            bbox_height=100,
        )

        # Create a cluster with a representative that matches at 0.95 (high confidence)
        cluster_id = uuid4()
        # This vector will produce ~0.95 similarity with the identity
        rep_vector = np.array([0.95] + [0.0] * 1022 + [0.312], dtype=np.float32)
        rep_vector = rep_vector / np.linalg.norm(rep_vector)

        representatives_by_cluster = {cluster_id: [rep_vector]}

        # Run matching
        assigned, unclustered, _ = await matcher.match(
            candidates=cast(Any, [identity]),
            representatives_by_cluster=representatives_by_cluster,
        )

        # Should auto-assign (high confidence)
        assert assigned == 1
        assert len(unclustered) == 0
        assert len(suggestions_created) == 0
        assert len(assigned_identities) == 1

    async def test_mature_stage_borderline_auto_assigns(self) -> None:
        """During mature stage, borderline match auto-assigns (no suggestion)."""
        from types import SimpleNamespace
        from typing import cast

        settings = make_test_settings(
            early_stage_suggestion_enabled=True,
            early_stage_high_confidence_threshold=0.90,
            similarity_threshold=0.75,
            adaptive_threshold_maturity_point=30,
        )

        assigned_identities: list[Any] = []
        suggestions_created: list[Any] = []

        async def mock_assign(identity: Any, vector: Any, cluster_id: Any, similarity: Any) -> None:
            assigned_identities.append((identity.id, cluster_id, similarity))

        async def mock_add_rep(cluster_id: Any, identity: Any) -> None:
            return None

        async def mock_create_suggestion(identity_id: Any, cluster_id: Any, rep_sim: Any, avg_sim: Any) -> None:
            suggestions_created.append((identity_id, cluster_id, rep_sim, avg_sim))

        matcher = RepresentativeMatcher(
            threshold=0.75,
            add_representative_embedding=mock_add_rep,
            assign_to_cluster_by_id=mock_assign,
            settings=settings,
            create_suggestion=mock_create_suggestion,
            labeled_cluster_count=35,  # Mature stage (> 30)
        )

        # Create a test identity
        identity = SimpleNamespace(
            id=uuid4(),
            tenant_id=uuid4(),
            embedding=np.array([1.0] + [0.0] * 1023, dtype=np.float32).tolist(),
            confidence=0.9,
            media_id=1,
            bbox_width=100,
            bbox_height=100,
        )

        # Create a cluster with a representative that matches at 0.85 (borderline)
        cluster_id = uuid4()
        rep_vector = np.array([0.85] + [0.0] * 1022 + [0.527], dtype=np.float32)
        rep_vector = rep_vector / np.linalg.norm(rep_vector)

        representatives_by_cluster = {cluster_id: [rep_vector]}

        # Run matching
        assigned, unclustered, _ = await matcher.match(
            candidates=cast(Any, [identity]),
            representatives_by_cluster=representatives_by_cluster,
        )

        # Should auto-assign (mature stage)
        assert assigned == 1
        assert len(unclustered) == 0
        assert len(suggestions_created) == 0
        assert len(assigned_identities) == 1

    async def test_early_stage_disabled_auto_assigns(self) -> None:
        """When early_stage_suggestion_enabled=False, borderline matches auto-assign."""
        from types import SimpleNamespace
        from typing import cast

        settings = make_test_settings(
            early_stage_suggestion_enabled=False,  # Disabled
            early_stage_high_confidence_threshold=0.90,
            similarity_threshold=0.75,
        )

        assigned_identities: list[Any] = []
        suggestions_created: list[Any] = []

        async def mock_assign(identity: Any, vector: Any, cluster_id: Any, similarity: Any) -> None:
            assigned_identities.append((identity.id, cluster_id, similarity))

        async def mock_add_rep(cluster_id: Any, identity: Any) -> None:
            return None

        async def mock_create_suggestion(identity_id: Any, cluster_id: Any, rep_sim: Any, avg_sim: Any) -> None:
            suggestions_created.append((identity_id, cluster_id, rep_sim, avg_sim))

        matcher = RepresentativeMatcher(
            threshold=0.75,
            add_representative_embedding=mock_add_rep,
            assign_to_cluster_by_id=mock_assign,
            settings=settings,
            create_suggestion=mock_create_suggestion,
            labeled_cluster_count=5,  # Early stage, but feature disabled
        )

        # Create a test identity
        identity = SimpleNamespace(
            id=uuid4(),
            tenant_id=uuid4(),
            embedding=np.array([1.0] + [0.0] * 1023, dtype=np.float32).tolist(),
            confidence=0.9,
            media_id=1,
            bbox_width=100,
            bbox_height=100,
        )

        # Create a cluster with a representative that matches at 0.85 (borderline)
        cluster_id = uuid4()
        rep_vector = np.array([0.85] + [0.0] * 1022 + [0.527], dtype=np.float32)
        rep_vector = rep_vector / np.linalg.norm(rep_vector)

        representatives_by_cluster = {cluster_id: [rep_vector]}

        # Run matching
        assigned, unclustered, _ = await matcher.match(
            candidates=cast(Any, [identity]),
            representatives_by_cluster=representatives_by_cluster,
        )

        # Should auto-assign (feature disabled)
        assert assigned == 1
        assert len(unclustered) == 0
        assert len(suggestions_created) == 0
        assert len(assigned_identities) == 1
