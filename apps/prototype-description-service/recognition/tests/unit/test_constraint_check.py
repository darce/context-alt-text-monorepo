"""Service tests for ConstraintCheck using fake repositories."""

from unittest.mock import AsyncMock, Mock

import pytest

from recognition.application.assignment.candidate import AssignmentCandidate
from recognition.application.assignment.checks.constraint import ConstraintCheck
from recognition.domain.identity import MediaIdentity


@pytest.fixture
def mock_constraint_repo():
    return AsyncMock()


@pytest.fixture
def mock_member_repo():
    return AsyncMock()


class TestConstraintCheck:
    """Service tests for ConstraintCheck using fake repositories."""

    @pytest.mark.asyncio
    async def test_passes_when_no_constraints(self, mock_constraint_repo, mock_member_repo):
        """Check passes when no cannot-link constraints exist."""
        check = ConstraintCheck(mock_constraint_repo, mock_member_repo)

        # Setup candidate
        identity = Mock(spec=MediaIdentity)
        identity.id = "identity-1"
        identity.tenant_id = "tenant-1"
        candidate = Mock(spec=AssignmentCandidate)
        candidate.identity = identity
        candidate.cluster_id = "cluster-1"

        # Setup mocks
        mock_member_repo.get_by_cluster.return_value = [Mock(identity_id="member-1")]
        mock_constraint_repo.has_cannot_link.return_value = False

        result = await check.evaluate(candidate)

        assert result.passed is True
        mock_constraint_repo.has_cannot_link.assert_awaited_with(
            tenant_id="tenant-1", identity_id="identity-1", cluster_member_ids=["member-1"]
        )

    @pytest.mark.asyncio
    async def test_fails_on_cannot_link(self, mock_constraint_repo, mock_member_repo):
        """Check fails when cannot-link constraint exists with cluster member."""
        check = ConstraintCheck(mock_constraint_repo, mock_member_repo)

        # Setup candidate
        identity = Mock(spec=MediaIdentity)
        identity.id = "identity-1"
        identity.tenant_id = "tenant-1"
        candidate = Mock(spec=AssignmentCandidate)
        candidate.identity = identity
        candidate.cluster_id = "cluster-1"

        # Setup mocks
        mock_member_repo.get_by_cluster.return_value = [Mock(identity_id="member-1")]
        mock_constraint_repo.has_cannot_link.return_value = True

        result = await check.evaluate(candidate)

        assert result.passed is False
        assert result.reason is not None
        assert "CANNOT_LINK" in result.reason
