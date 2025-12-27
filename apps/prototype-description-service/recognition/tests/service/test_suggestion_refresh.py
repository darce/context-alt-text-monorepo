"""Service tests for suggestion refresh logic."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from recognition.application.settings.clustering import ClusteringSettings
from recognition.application.suggestions.service import SuggestionService
from recognition.domain.suggestion import AssignmentSuggestion, SuggestionStatus


class TestRefreshForCluster:
    """Tests for SuggestionService.refresh_for_cluster."""

    @pytest.fixture
    def mock_repository(self) -> AsyncMock:
        repo = AsyncMock()
        repo.get_by_cluster = AsyncMock(return_value=[])
        repo.update_scores = AsyncMock()
        repo.update_status = AsyncMock()
        return repo

    @pytest.fixture
    def mock_cluster_repo(self) -> AsyncMock:
        repo = AsyncMock()
        repo.get_by_id = AsyncMock(return_value=MagicMock(id="cluster-1"))
        repo.get_all_representatives = AsyncMock(return_value=[])
        return repo

    @pytest.fixture
    def mock_session(self) -> AsyncMock:
        return AsyncMock()

    @pytest.fixture
    def settings(self) -> ClusteringSettings:
        return ClusteringSettings(
            suggestion_floor=0.75,
            suggestion_ceiling=0.85,
        )

    @pytest.mark.asyncio
    async def test_refresh_updates_changed_scores(
        self,
        mock_repository: AsyncMock,
        mock_cluster_repo: AsyncMock,
        mock_session: AsyncMock,
        settings: ClusteringSettings,
    ) -> None:
        """Suggestions with changed similarity are updated."""
        # Arrange
        cluster_id = str(uuid.uuid4())
        identity_id = str(uuid.uuid4())

        pending_suggestion = MagicMock(spec=AssignmentSuggestion)
        pending_suggestion.id = "sug-1"
        pending_suggestion.identity_id = identity_id
        pending_suggestion.status = SuggestionStatus.PENDING
        pending_suggestion.representative_similarity = 0.5  # Old low score

        mock_repository.get_by_cluster.return_value = [pending_suggestion]

        # Mock representatives (newly added better match)
        rep = MagicMock()
        rep.embedding = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        mock_cluster_repo.get_all_representatives.return_value = [rep]

        # Mock identity model
        identity_model = MagicMock()
        identity_model.embedding = rep.embedding.tolist()  # Perfect match
        mock_session.get.return_value = identity_model

        service = SuggestionService(
            repository=mock_repository,
            tenant_id="tenant-1",
            cluster_repository=mock_cluster_repo,
            session=mock_session,
            settings=settings,
        )

        # Act
        count = await service.refresh_for_cluster(cluster_id)

        # Assert
        assert count == 1
        mock_repository.update_scores.assert_called_once_with(
            "tenant-1",
            "sug-1",
            representative_similarity=pytest.approx(1.0),
            member_similarity=pytest.approx(1.0),
            confidence_score=pytest.approx(1.0),
        )

    @pytest.mark.asyncio
    async def test_refresh_skips_non_pending(
        self,
        mock_repository: AsyncMock,
        mock_cluster_repo: AsyncMock,
        mock_session: AsyncMock,
        settings: ClusteringSettings,
    ) -> None:
        """Already-resolved suggestions are not refreshed."""
        # Arrange
        accepted_suggestion = MagicMock(spec=AssignmentSuggestion)
        accepted_suggestion.status = SuggestionStatus.ACCEPTED

        mock_repository.get_by_cluster.return_value = [accepted_suggestion]

        service = SuggestionService(
            repository=mock_repository,
            tenant_id="tenant-1",
            cluster_repository=mock_cluster_repo,
            session=mock_session,
            settings=settings,
        )

        # Act
        count = await service.refresh_for_cluster("cluster-1")

        # Assert
        assert count == 0
        mock_repository.update_scores.assert_not_called()

    @pytest.mark.asyncio
    async def test_refresh_skips_insignificant_changes(
        self,
        mock_repository: AsyncMock,
        mock_cluster_repo: AsyncMock,
        mock_session: AsyncMock,
        settings: ClusteringSettings,
    ) -> None:
        """Suggestions with minor score changes (<0.01) are not updated."""
        # Arrange
        identity_id = str(uuid.uuid4())
        pending_suggestion = MagicMock(spec=AssignmentSuggestion)
        pending_suggestion.id = "sug-1"
        pending_suggestion.identity_id = identity_id
        pending_suggestion.status = SuggestionStatus.PENDING
        pending_suggestion.representative_similarity = 0.900

        mock_repository.get_by_cluster.return_value = [pending_suggestion]

        rep = MagicMock()
        rep.embedding = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        mock_cluster_repo.get_all_representatives.return_value = [rep]

        identity_model = MagicMock()
        # Create a near match (similarity ~0.905)
        # Cosine similarity = dot(a, b) / (norm(a) * norm(b))
        # For unit vectors: cos(theta) = dot(a, b)
        identity_model.embedding = np.array([0.905, 0.425, 0.0], dtype=np.float32).tolist()
        mock_session.get.return_value = identity_model

        service = SuggestionService(
            repository=mock_repository,
            tenant_id="tenant-1",
            cluster_repository=mock_cluster_repo,
            session=mock_session,
            settings=settings,
        )

        # Act
        count = await service.refresh_for_cluster("cluster-1")

        # Assert (0.905 - 0.900 = 0.005 < 0.01)
        assert count == 0
        mock_repository.update_scores.assert_not_called()

    @pytest.mark.asyncio
    async def test_refresh_triggers_automatic_transitions(
        self,
        mock_repository: AsyncMock,
        mock_cluster_repo: AsyncMock,
        mock_session: AsyncMock,
        caplog: pytest.LogCaptureFixture,
        settings: ClusteringSettings,
    ) -> None:
        """Automatic ACCEPTED/REJECTED transitions occur if thresholds are met."""
        # Arrange
        identity_id_match = str(uuid.uuid4())
        identity_id_reject = str(uuid.uuid4())

        # 1. Suggestion that should be ACCEPTED (0.86 >= 0.85)
        sug_match = MagicMock(spec=AssignmentSuggestion)
        sug_match.id = "sug-match"
        sug_match.identity_id = identity_id_match
        sug_match.status = SuggestionStatus.PENDING
        sug_match.representative_similarity = 0.5

        # 2. Suggestion that should be REJECTED (0.70 < 0.75)
        sug_reject = MagicMock(spec=AssignmentSuggestion)
        sug_reject.id = "sug-reject"
        sug_reject.identity_id = identity_id_reject
        sug_reject.status = SuggestionStatus.PENDING
        sug_reject.representative_similarity = 0.82

        mock_repository.get_by_cluster.return_value = [sug_match, sug_reject]

        # Mock representatives
        # Rep 1: for match (score 0.86)
        rep_match = MagicMock()
        rep_match.embedding = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        # Rep 2: for reject (score 0.70)
        rep_reject = MagicMock()
        rep_reject.embedding = np.array([0.0, 1.0, 0.0], dtype=np.float32)
        mock_cluster_repo.get_all_representatives.return_value = [rep_match, rep_reject]

        # Mock identity models
        model_match = MagicMock()
        model_match.embedding = np.array([0.86, 0.51, 0.0], dtype=np.float32).tolist()

        model_reject = MagicMock()
        model_reject.embedding = np.array([0.0, 0.70, 0.71], dtype=np.float32).tolist()

        def mock_get(cls, uid):
            if str(uid) == identity_id_match:
                return model_match
            if str(uid) == identity_id_reject:
                return model_reject
            return None

        mock_session.get.side_effect = mock_get

        service = SuggestionService(
            repository=mock_repository,
            tenant_id="tenant-1",
            cluster_repository=mock_cluster_repo,
            session=mock_session,
            settings=settings,
        )

        # Act
        with caplog.at_level("INFO"):
            count = await service.refresh_for_cluster("cluster-1")

        # Assert
        assert count == 2

        # Verify status updates
        mock_repository.update_status.assert_any_call("tenant-1", "sug-match", status=SuggestionStatus.ACCEPTED)
        mock_repository.update_status.assert_any_call("tenant-1", "sug-reject", status=SuggestionStatus.REJECTED)

        # Verify logging
        assert "[suggestions] refresh_result" in caplog.text
        assert "status=accepted" in caplog.text
        assert "status=rejected" in caplog.text
        assert "updated=true" in caplog.text
