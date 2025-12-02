"""Tests for the SuggestionService persistence flow.

Tests the suggestion creation, resolution, and query operations
using mocked database sessions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from db.models import IdentitySuggestion
from recognition.application.clustering.suggestion_service import SuggestionService


class FakeAsyncResult:
    """Fake async result for mocking session.execute()."""

    def __init__(self, items: list | None = None, scalar: object = None):
        self._items = items or []
        self._scalar = scalar

    def scalars(self) -> FakeAsyncResult:
        return self

    def all(self) -> list:
        return self._items

    def scalar(self) -> object:
        return self._scalar

    def scalar_one_or_none(self) -> object:
        return self._scalar


class TestSuggestionServiceCreate:
    """Tests for create_suggestion method."""

    @pytest.fixture
    def service(self) -> SuggestionService:
        """Create a SuggestionService with a mock session."""
        session = AsyncMock()
        session.add = MagicMock()
        # Mock execute to return no existing suggestions (so new ones are created)
        session.execute.return_value = FakeAsyncResult(scalar=None)
        tenant_id = uuid4()
        return SuggestionService(session, tenant_id)

    @pytest.mark.asyncio
    async def test_create_suggestion_basic(self, service: SuggestionService) -> None:
        """Test creating a suggestion with basic parameters."""
        identity_id = uuid4()
        cluster_id = uuid4()

        suggestion = await service.create_suggestion(
            identity_id=identity_id,
            cluster_id=cluster_id,
            representative_similarity=0.65,
            avg_member_similarity=0.58,
        )

        assert suggestion is not None
        assert suggestion.tenant_id == service.tenant_id
        assert suggestion.identity_id == identity_id
        assert suggestion.suggested_cluster_id == cluster_id
        assert suggestion.representative_similarity == 0.65
        assert suggestion.avg_member_similarity == 0.58
        assert suggestion.resolution == "pending"
        # Verify session.add was called
        add_mock: MagicMock = service.session.add  # type: ignore[assignment]
        add_mock.assert_called_once_with(suggestion)

    @pytest.mark.asyncio
    async def test_create_suggestion_computes_confidence(self, service: SuggestionService) -> None:
        """Test that confidence score is computed correctly."""
        suggestion = await service.create_suggestion(
            identity_id=uuid4(),
            cluster_id=uuid4(),
            representative_similarity=0.70,
            avg_member_similarity=0.60,
        )

        assert suggestion is not None
        # Confidence = 0.70 * 0.6 + 0.60 * 0.4 = 0.42 + 0.24 = 0.66
        expected_confidence = 0.70 * 0.6 + 0.60 * 0.4
        assert suggestion.confidence_score == pytest.approx(expected_confidence)

    @pytest.mark.asyncio
    async def test_create_suggestion_borderline_values(self, service: SuggestionService) -> None:
        """Test creating suggestions at borderline thresholds."""
        # Just above suggestion threshold (0.55)
        suggestion = await service.create_suggestion(
            identity_id=uuid4(),
            cluster_id=uuid4(),
            representative_similarity=0.60,
            avg_member_similarity=0.55,
        )

        assert suggestion is not None
        assert suggestion.avg_member_similarity == 0.55
        assert suggestion.representative_similarity == 0.60


class TestSuggestionServiceAccept:
    """Tests for accept_suggestion method."""

    @pytest.mark.asyncio
    async def test_accept_suggestion_success(self) -> None:
        """Test successfully accepting a pending suggestion."""
        tenant_id = uuid4()
        suggestion_id = uuid4()

        existing_suggestion = IdentitySuggestion(
            id=suggestion_id,
            tenant_id=tenant_id,
            identity_id=uuid4(),
            suggested_cluster_id=uuid4(),
            representative_similarity=0.65,
            avg_member_similarity=0.60,
            confidence_score=0.63,
            resolution="pending",
        )

        session = AsyncMock()
        session.get = AsyncMock(return_value=existing_suggestion)

        service = SuggestionService(session, tenant_id)
        result = await service.accept_suggestion(suggestion_id)

        assert result is not None
        assert result.resolution == "accepted"
        assert result.resolved_at is not None
        session.get.assert_called_once_with(IdentitySuggestion, suggestion_id)

    @pytest.mark.asyncio
    async def test_accept_suggestion_not_found(self) -> None:
        """Test accepting a non-existent suggestion."""
        session = AsyncMock()
        session.get = AsyncMock(return_value=None)

        service = SuggestionService(session, uuid4())
        result = await service.accept_suggestion(uuid4())

        assert result is None

    @pytest.mark.asyncio
    async def test_accept_suggestion_wrong_tenant(self) -> None:
        """Test that tenant isolation is enforced."""
        tenant_id = uuid4()
        other_tenant_id = uuid4()
        suggestion_id = uuid4()

        existing_suggestion = IdentitySuggestion(
            id=suggestion_id,
            tenant_id=other_tenant_id,  # Different tenant
            identity_id=uuid4(),
            suggested_cluster_id=uuid4(),
            representative_similarity=0.65,
            avg_member_similarity=0.60,
            confidence_score=0.63,
            resolution="pending",
        )

        session = AsyncMock()
        session.get = AsyncMock(return_value=existing_suggestion)

        service = SuggestionService(session, tenant_id)
        result = await service.accept_suggestion(suggestion_id)

        assert result is None

    @pytest.mark.asyncio
    async def test_accept_already_resolved_suggestion(self) -> None:
        """Test accepting an already-resolved suggestion is idempotent."""
        tenant_id = uuid4()
        suggestion_id = uuid4()

        existing_suggestion = IdentitySuggestion(
            id=suggestion_id,
            tenant_id=tenant_id,
            identity_id=uuid4(),
            suggested_cluster_id=uuid4(),
            representative_similarity=0.65,
            avg_member_similarity=0.60,
            confidence_score=0.63,
            resolution="rejected",  # Already resolved
            resolved_at=datetime.now(UTC),
        )

        session = AsyncMock()
        session.get = AsyncMock(return_value=existing_suggestion)

        service = SuggestionService(session, tenant_id)
        result = await service.accept_suggestion(suggestion_id)

        assert result is not None
        assert result.resolution == "rejected"  # Unchanged


class TestSuggestionServiceReject:
    """Tests for reject_suggestion method."""

    @pytest.mark.asyncio
    async def test_reject_suggestion_success(self) -> None:
        """Test successfully rejecting a pending suggestion."""
        tenant_id = uuid4()
        suggestion_id = uuid4()

        existing_suggestion = IdentitySuggestion(
            id=suggestion_id,
            tenant_id=tenant_id,
            identity_id=uuid4(),
            suggested_cluster_id=uuid4(),
            representative_similarity=0.65,
            avg_member_similarity=0.60,
            confidence_score=0.63,
            resolution="pending",
        )

        session = AsyncMock()
        session.get = AsyncMock(return_value=existing_suggestion)

        service = SuggestionService(session, tenant_id)
        result = await service.reject_suggestion(suggestion_id)

        assert result is not None
        assert result.resolution == "rejected"
        assert result.resolved_at is not None

    @pytest.mark.asyncio
    async def test_reject_suggestion_not_found(self) -> None:
        """Test rejecting a non-existent suggestion."""
        session = AsyncMock()
        session.get = AsyncMock(return_value=None)

        service = SuggestionService(session, uuid4())
        result = await service.reject_suggestion(uuid4())

        assert result is None


class TestSuggestionServiceExpire:
    """Tests for expire_suggestions methods."""

    @pytest.mark.asyncio
    async def test_expire_suggestions_for_identity(self) -> None:
        """Test expiring all suggestions for an identity."""
        tenant_id = uuid4()
        identity_id = uuid4()

        mock_result = MagicMock()
        mock_result.rowcount = 3

        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)

        service = SuggestionService(session, tenant_id)
        count = await service.expire_suggestions_for_identity(identity_id)

        assert count == 3
        session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_expire_suggestions_for_cluster(self) -> None:
        """Test expiring all suggestions for a cluster."""
        tenant_id = uuid4()
        cluster_id = uuid4()

        mock_result = MagicMock()
        mock_result.rowcount = 2

        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)

        service = SuggestionService(session, tenant_id)
        count = await service.expire_suggestions_for_cluster(cluster_id)

        assert count == 2
        session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_expire_no_suggestions(self) -> None:
        """Test expiring when no suggestions exist."""
        mock_result = MagicMock()
        mock_result.rowcount = 0

        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)

        service = SuggestionService(session, uuid4())
        count = await service.expire_suggestions_for_identity(uuid4())

        assert count == 0


class TestSuggestionServiceQuery:
    """Tests for query methods."""

    @pytest.mark.asyncio
    async def test_get_pending_suggestions(self) -> None:
        """Test retrieving pending suggestions."""
        tenant_id = uuid4()

        suggestions = [
            IdentitySuggestion(
                id=uuid4(),
                tenant_id=tenant_id,
                identity_id=uuid4(),
                suggested_cluster_id=uuid4(),
                representative_similarity=0.70,
                avg_member_similarity=0.65,
                confidence_score=0.68,
                resolution="pending",
            ),
            IdentitySuggestion(
                id=uuid4(),
                tenant_id=tenant_id,
                identity_id=uuid4(),
                suggested_cluster_id=uuid4(),
                representative_similarity=0.65,
                avg_member_similarity=0.58,
                confidence_score=0.62,
                resolution="pending",
            ),
        ]

        session = AsyncMock()
        session.execute = AsyncMock(return_value=FakeAsyncResult(items=suggestions))

        service = SuggestionService(session, tenant_id)
        result = await service.get_pending_suggestions(limit=10, offset=0)

        assert len(result) == 2
        session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_pending_suggestions_empty(self) -> None:
        """Test retrieving when no pending suggestions exist."""
        session = AsyncMock()
        session.execute = AsyncMock(return_value=FakeAsyncResult(items=[]))

        service = SuggestionService(session, uuid4())
        result = await service.get_pending_suggestions()

        assert result == []

    @pytest.mark.asyncio
    async def test_count_pending_suggestions(self) -> None:
        """Test counting pending suggestions."""
        session = AsyncMock()
        session.execute = AsyncMock(return_value=FakeAsyncResult(scalar=5))

        service = SuggestionService(session, uuid4())
        count = await service.count_pending_suggestions()

        assert count == 5

    @pytest.mark.asyncio
    async def test_count_pending_suggestions_zero(self) -> None:
        """Test counting when no pending suggestions exist."""
        session = AsyncMock()
        session.execute = AsyncMock(return_value=FakeAsyncResult(scalar=0))

        service = SuggestionService(session, uuid4())
        count = await service.count_pending_suggestions()

        assert count == 0

    @pytest.mark.asyncio
    async def test_count_pending_suggestions_none(self) -> None:
        """Test counting handles None result."""
        session = AsyncMock()
        session.execute = AsyncMock(return_value=FakeAsyncResult(scalar=None))

        service = SuggestionService(session, uuid4())
        count = await service.count_pending_suggestions()

        assert count == 0

    @pytest.mark.asyncio
    async def test_get_suggestion_by_id_found(self) -> None:
        """Test getting a suggestion by ID when it exists."""
        tenant_id = uuid4()
        suggestion_id = uuid4()

        existing_suggestion = IdentitySuggestion(
            id=suggestion_id,
            tenant_id=tenant_id,
            identity_id=uuid4(),
            suggested_cluster_id=uuid4(),
            representative_similarity=0.65,
            avg_member_similarity=0.60,
            confidence_score=0.63,
            resolution="pending",
        )

        session = AsyncMock()
        session.get = AsyncMock(return_value=existing_suggestion)

        service = SuggestionService(session, tenant_id)
        result = await service.get_suggestion_by_id(suggestion_id)

        assert result is not None
        assert result.id == suggestion_id

    @pytest.mark.asyncio
    async def test_get_suggestion_by_id_not_found(self) -> None:
        """Test getting a suggestion by ID when it doesn't exist."""
        session = AsyncMock()
        session.get = AsyncMock(return_value=None)

        service = SuggestionService(session, uuid4())
        result = await service.get_suggestion_by_id(uuid4())

        assert result is None

    @pytest.mark.asyncio
    async def test_get_suggestion_by_id_wrong_tenant(self) -> None:
        """Test tenant isolation in get_suggestion_by_id."""
        tenant_id = uuid4()
        other_tenant_id = uuid4()
        suggestion_id = uuid4()

        existing_suggestion = IdentitySuggestion(
            id=suggestion_id,
            tenant_id=other_tenant_id,  # Different tenant
            identity_id=uuid4(),
            suggested_cluster_id=uuid4(),
            representative_similarity=0.65,
            avg_member_similarity=0.60,
            confidence_score=0.63,
            resolution="pending",
        )

        session = AsyncMock()
        session.get = AsyncMock(return_value=existing_suggestion)

        service = SuggestionService(session, tenant_id)
        result = await service.get_suggestion_by_id(suggestion_id)

        assert result is None


class TestSuggestionServiceConfidenceComputation:
    """Tests for confidence score computation."""

    def test_compute_confidence_equal_weights(self) -> None:
        """Test confidence computation with equal similarity values."""
        session = AsyncMock()
        service = SuggestionService(session, uuid4())

        # 0.7 * 0.6 + 0.7 * 0.4 = 0.42 + 0.28 = 0.70
        confidence = service._compute_confidence(0.7, 0.7)
        assert confidence == pytest.approx(0.70)

    def test_compute_confidence_high_rep_low_member(self) -> None:
        """Test confidence when rep similarity is high but member is low."""
        session = AsyncMock()
        service = SuggestionService(session, uuid4())

        # 0.8 * 0.6 + 0.5 * 0.4 = 0.48 + 0.20 = 0.68
        confidence = service._compute_confidence(0.8, 0.5)
        assert confidence == pytest.approx(0.68)

    def test_compute_confidence_low_rep_high_member(self) -> None:
        """Test confidence when rep similarity is low but member is high."""
        session = AsyncMock()
        service = SuggestionService(session, uuid4())

        # 0.5 * 0.6 + 0.8 * 0.4 = 0.30 + 0.32 = 0.62
        confidence = service._compute_confidence(0.5, 0.8)
        assert confidence == pytest.approx(0.62)

    def test_compute_confidence_minimum_values(self) -> None:
        """Test confidence computation at minimum values."""
        session = AsyncMock()
        service = SuggestionService(session, uuid4())

        confidence = service._compute_confidence(0.0, 0.0)
        assert confidence == pytest.approx(0.0)

    def test_compute_confidence_maximum_values(self) -> None:
        """Test confidence computation at maximum values."""
        session = AsyncMock()
        service = SuggestionService(session, uuid4())

        confidence = service._compute_confidence(1.0, 1.0)
        assert confidence == pytest.approx(1.0)

    def test_compute_confidence_typical_borderline(self) -> None:
        """Test confidence computation for typical borderline case."""
        session = AsyncMock()
        service = SuggestionService(session, uuid4())

        # Typical borderline: rep=0.64, member=0.57
        # 0.64 * 0.6 + 0.57 * 0.4 = 0.384 + 0.228 = 0.612
        confidence = service._compute_confidence(0.64, 0.57)
        assert confidence == pytest.approx(0.612)
