"""Service tests for suggestion refresh logic."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from recognition.application.assignment.candidate import AssignmentCandidate, DiscoveryMethod
from recognition.application.assignment.decision import AssignmentDecision, AssignmentOutcome
from recognition.application.settings.clustering import ClusteringSettings
from recognition.application.suggestions.refresh_service import SuggestionRefreshService
from recognition.domain.identity import MediaIdentity
from recognition.domain.suggestion import AssignmentSuggestion, SuggestionRefreshReason, SuggestionStatus


def _make_identity_model(identity_id: str, embedding: np.ndarray, *, tenant_id: str | None = None) -> MagicMock:
    model = MagicMock()
    model.id = uuid.UUID(identity_id)
    model.tenant_id = uuid.UUID(tenant_id) if tenant_id else uuid.uuid4()
    model.media_id = "media-1"
    model.embedding = embedding.tolist()
    model.confidence = 0.9
    model.bbox_width = 1
    model.bbox_height = 1
    model.bbox_x = 0
    model.bbox_y = 0
    model.pose_pitch = None
    model.pose_yaw = None
    model.pose_roll = None
    model.image_phash = None
    return model


def _make_candidate(tenant_id: str, cluster_id: str) -> AssignmentCandidate:
    identity = MediaIdentity(
        id="identity-1",
        tenant_id=tenant_id,
        media_id="media-1",
        embedding=np.zeros(512, dtype=np.float32),
        confidence=0.9,
        bbox_width=1,
        bbox_height=1,
    )
    return AssignmentCandidate(
        identity=identity,
        identity_vector=np.zeros(512, dtype=np.float32),
        cluster_id=cluster_id,
        discovery_method=DiscoveryMethod.REPRESENTATIVE,
        discovery_similarity=0.88,
    )


def _make_labeled_cluster_repo(tenant_id: str, cluster_id: str, representative_similarity: float):
    """Return a repo stub with one labeled cluster and one representative vector."""
    rep_vec = np.array(
        [representative_similarity, np.sqrt(1 - representative_similarity**2)],
        dtype=np.float32,
    )
    cluster = MagicMock()
    cluster.id = cluster_id
    cluster.tenant_id = tenant_id
    cluster.label = "Avery Rhodes"
    cluster.user_confirmed = True

    class _ClusterRepoStub:
        async def get_labeled_with_representatives(self, *_args, **_kwargs):
            return [(cluster, [type("Rep", (), {"embedding": rep_vec})()])]

    return _ClusterRepoStub()


def _make_identity_session_stub(
    *,
    tenant_id: str,
    identity_id: str,
    embedding: np.ndarray | None = None,
):
    """Return a session stub that resolves one identity model."""
    identity_embedding = embedding if embedding is not None else np.array([1.0, 0.0], dtype=np.float32)

    class _SessionStub:
        async def get(self, _model, _identity_id):
            return _make_identity_model(identity_id, identity_embedding, tenant_id=tenant_id)

    return _SessionStub()


class TestRefreshForCluster:
    """Tests for SuggestionRefreshService.refresh_for_cluster."""

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
        repo.get_members = AsyncMock(return_value=[])
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
        identity_model = _make_identity_model(identity_id, rep.embedding)
        mock_session.get.return_value = identity_model

        service = SuggestionRefreshService(
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

        service = SuggestionRefreshService(
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

        identity_embedding = np.array([0.905, 0.425, 0.0], dtype=np.float32)
        mock_session.get.return_value = _make_identity_model(identity_id, identity_embedding)

        service = SuggestionRefreshService(
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
    async def test_refresh_updates_scores_without_automatic_transitions(
        self,
        mock_repository: AsyncMock,
        mock_cluster_repo: AsyncMock,
        mock_session: AsyncMock,
        caplog: pytest.LogCaptureFixture,
        settings: ClusteringSettings,
    ) -> None:
        """Score refresh should not auto-resolve user-review suggestions."""
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
        model_match = _make_identity_model(
            identity_id_match,
            np.array([0.86, 0.51, 0.0], dtype=np.float32),
        )
        model_reject = _make_identity_model(
            identity_id_reject,
            np.array([0.0, 0.70, 0.71], dtype=np.float32),
        )

        def mock_get(cls, uid):
            if str(uid) == identity_id_match:
                return model_match
            if str(uid) == identity_id_reject:
                return model_reject
            return None

        mock_session.get.side_effect = mock_get

        service = SuggestionRefreshService(
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

        # Suggestions remain pending; refresh updates scores only.
        mock_repository.update_status.assert_not_called()

        # Verify logging
        assert "[suggestions] refresh_result" in caplog.text
        assert "status=pending" in caplog.text
        assert "updated=true" in caplog.text


class TestRefreshForIdentity:
    """Tests for SuggestionRefreshService.refresh_for_identity."""

    @pytest.mark.asyncio
    async def test_refresh_creates_suggestion_for_band(self) -> None:
        tenant_id = str(uuid.uuid4())
        cluster_id = str(uuid.uuid4())
        identity_id = str(uuid.uuid4())

        suggestion_repo = AsyncMock()
        suggestion_repo.upsert_by_identity_cluster.return_value = AssignmentSuggestion(
            id="s-1",
            identity_id=identity_id,
            cluster_id=cluster_id,
            representative_similarity=0.75,
            member_similarity=0.75,
            status=SuggestionStatus.PENDING,
            created_at=None,
        )

        settings = ClusteringSettings(
            similarity_threshold=0.8,
            suggestion_floor=0.7,
            suggestion_ceiling=0.8,
        )
        service = SuggestionRefreshService(
            suggestion_repo,
            tenant_id=tenant_id,
            cluster_repository=_make_labeled_cluster_repo(tenant_id, cluster_id, representative_similarity=0.75),
            session=_make_identity_session_stub(tenant_id=tenant_id, identity_id=identity_id),
            settings=settings,
        )

        suggestions = await service.refresh_for_identity(
            identity_id=identity_id,
            reason=SuggestionRefreshReason.MANUAL_SPLIT,
        )

        assert len(suggestions) == 1
        suggestion_repo.upsert_by_identity_cluster.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_refresh_respects_gate_rejection(self) -> None:
        tenant_id = str(uuid.uuid4())
        cluster_id = str(uuid.uuid4())
        identity_id = str(uuid.uuid4())

        suggestion_repo = AsyncMock()

        gate = AsyncMock()
        gate.evaluate.return_value = AssignmentDecision(
            outcome=AssignmentOutcome.REJECT,
            candidate=_make_candidate(tenant_id, cluster_id),
            checks_passed=["confidence_check"],
            checks_failed=["block_check"],
        )

        service = SuggestionRefreshService(
            suggestion_repo,
            tenant_id=tenant_id,
            cluster_repository=_make_labeled_cluster_repo(tenant_id, cluster_id, representative_similarity=0.75),
            session=_make_identity_session_stub(tenant_id=tenant_id, identity_id=identity_id),
            settings=ClusteringSettings(similarity_threshold=0.8, suggestion_floor=0.7, suggestion_ceiling=0.8),
            gate=gate,
        )

        suggestions = await service.refresh_for_identity(
            identity_id=identity_id,
            reason=SuggestionRefreshReason.MANUAL_SPLIT,
        )

        assert suggestions == []
        suggestion_repo.upsert_by_identity_cluster.assert_not_awaited()
        gate.evaluate.assert_awaited()

    @pytest.mark.asyncio
    async def test_refresh_surfaces_low_confidence_when_confidence_check_rejects(self) -> None:
        tenant_id = str(uuid.uuid4())
        cluster_id = str(uuid.uuid4())
        identity_id = str(uuid.uuid4())

        suggestion_repo = AsyncMock()
        suggestion_repo.upsert_by_identity_cluster.return_value = AssignmentSuggestion(
            id="s-low-confidence",
            identity_id=identity_id,
            cluster_id=cluster_id,
            representative_similarity=0.65,
            member_similarity=0.65,
            status=SuggestionStatus.PENDING,
            created_at=None,
        )

        gate = AsyncMock()
        gate.evaluate.return_value = AssignmentDecision(
            outcome=AssignmentOutcome.REJECT,
            candidate=_make_candidate(tenant_id, cluster_id),
            checks_passed=[],
            checks_failed=["confidence_check"],
        )

        service = SuggestionRefreshService(
            suggestion_repo,
            tenant_id=tenant_id,
            cluster_repository=_make_labeled_cluster_repo(tenant_id, cluster_id, representative_similarity=0.65),
            session=_make_identity_session_stub(tenant_id=tenant_id, identity_id=identity_id),
            settings=ClusteringSettings(
                similarity_threshold=0.8,
                suggestion_floor=0.7,
                suggestion_ceiling=0.8,
                low_confidence_suggestion_floor=0.6,
            ),
            gate=gate,
        )

        suggestions = await service.refresh_for_identity(
            identity_id=identity_id,
            reason=SuggestionRefreshReason.MANUAL_SPLIT,
        )

        assert len(suggestions) == 1
        suggestion_repo.upsert_by_identity_cluster.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_refresh_creates_suggestion_when_gate_accepts(self) -> None:
        tenant_id = str(uuid.uuid4())
        cluster_id = str(uuid.uuid4())
        identity_id = str(uuid.uuid4())

        suggestion_repo = AsyncMock()
        suggestion_repo.upsert_by_identity_cluster.return_value = AssignmentSuggestion(
            id="s-accept",
            identity_id=identity_id,
            cluster_id=cluster_id,
            representative_similarity=0.85,
            member_similarity=0.85,
            status=SuggestionStatus.PENDING,
            created_at=None,
        )

        gate = AsyncMock()
        gate.evaluate.return_value = AssignmentDecision(
            outcome=AssignmentOutcome.ACCEPT,
            candidate=_make_candidate(tenant_id, cluster_id),
            checks_passed=["confidence_check"],
            checks_failed=[],
        )

        service = SuggestionRefreshService(
            suggestion_repo,
            tenant_id=tenant_id,
            cluster_repository=_make_labeled_cluster_repo(tenant_id, cluster_id, representative_similarity=0.85),
            session=_make_identity_session_stub(tenant_id=tenant_id, identity_id=identity_id),
            settings=ClusteringSettings(similarity_threshold=0.8, suggestion_floor=0.7, suggestion_ceiling=0.8),
            gate=gate,
        )

        suggestions = await service.refresh_for_identity(
            identity_id=identity_id,
            reason=SuggestionRefreshReason.MANUAL_SPLIT,
        )

        assert len(suggestions) == 1
        suggestion_repo.upsert_by_identity_cluster.assert_awaited_once()
        gate.evaluate.assert_awaited()
