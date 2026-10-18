"""Unit tests for ConstrainedHAC algorithm."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import numpy as np
import pytest

from recognition.application.clustering.constrained_hac import ConstrainedHAC, _apply_constraint_to_matrix
from recognition.application.settings.clustering import HACSettings
from recognition.domain.constraints import ConstraintSource, ConstraintType, IdentityConstraint


@pytest.fixture
def mock_repo():
    return AsyncMock()


@pytest.fixture
def settings():
    return HACSettings(
        linkage_method="single",  # Use single linkage for simple tests
        distance_threshold=0.5,
        constraint_penalty=10.0,
    )


class TestConstrainedHAC:
    @pytest.mark.asyncio
    async def test_empty_embeddings(self, mock_repo, settings):
        hac = ConstrainedHAC(mock_repo, settings)
        result = await hac.refine_clusters(uuid4(), {})
        assert result == {}

    @pytest.mark.asyncio
    async def test_no_constraints_clustering(self, mock_repo, settings):
        """Test standard clustering without constraints."""
        mock_repo.get_all.return_value = []
        hac = ConstrainedHAC(mock_repo, settings)

        # Create 3 points: A and B close, C far
        # Cosine distance: 1 - roughly 1.0 (identical) = 0
        # A: [1, 0]
        # B: [0.99, 0.01] -> close
        # C: [0, 1] -> orthogonal (dist 1.0)

        id_a, id_b, id_c = uuid4(), uuid4(), uuid4()
        embeddings = {
            id_a: np.array([1.0, 0.0]),
            id_b: np.array([0.9, 0.1]),  # dist ~0.1
            id_c: np.array([0.0, 1.0]),  # dist 1.0
        }

        result = await hac.refine_clusters(uuid4(), embeddings)

        # A and B should be same cluster, C different
        assert result[id_a] == result[id_b]
        assert result[id_a] != result[id_c]

    @pytest.mark.asyncio
    async def test_must_link_constraint(self, mock_repo, settings):
        """MUST_LINK should pull far points together."""
        # A and C are far (dist 1.0), threshold 0.5
        id_a, id_c = uuid4(), uuid4()
        # Sort to ensure constraint matches canonical order if needed (though repo handles it)
        # The logic in class just looks up ID.

        embeddings = {
            id_a: np.array([1.0, 0.0]),
            id_c: np.array([0.0, 1.0]),
        }

        # Define constraint
        constraint = IdentityConstraint(
            id=uuid4(),
            tenant_id=uuid4(),
            identity_a=id_a,
            identity_b=id_c,
            constraint_type=ConstraintType.MUST_LINK,
            source=ConstraintSource.MERGE,
            created_at=datetime.now(UTC),
        )
        mock_repo.get_all.return_value = [constraint]

        hac = ConstrainedHAC(mock_repo, settings)
        result = await hac.refine_clusters(uuid4(), embeddings)

        # With MUST_LINK, dist becomes 0.0 -> merged
        assert result[id_a] == result[id_c]

    @pytest.mark.asyncio
    async def test_cannot_link_constraint(self, mock_repo, settings):
        """CANNOT_LINK should push close points apart."""
        # A and B close (dist 0.1), threshold 0.5
        id_a, id_b = uuid4(), uuid4()
        embeddings = {
            id_a: np.array([1.0, 0.0]),
            id_b: np.array([0.9, 0.1]),
        }

        constraint = IdentityConstraint(
            id=uuid4(),
            tenant_id=uuid4(),
            identity_a=id_a,
            identity_b=id_b,
            constraint_type=ConstraintType.CANNOT_LINK,
            source=ConstraintSource.WRONG_PERSON,
            created_at=datetime.now(UTC),
        )
        mock_repo.get_all.return_value = [constraint]

        hac = ConstrainedHAC(mock_repo, settings)
        result = await hac.refine_clusters(uuid4(), embeddings)

        # With CANNOT_LINK, dist becomes 10.0 -> split
        assert result[id_a] != result[id_b]


def _make_constraint(identity_a, identity_b, constraint_type):  # noqa: ANN001
    return IdentityConstraint(
        id=uuid4(),
        tenant_id=uuid4(),
        identity_a=identity_a,
        identity_b=identity_b,
        constraint_type=constraint_type,
        source=ConstraintSource.MERGE,
        created_at=datetime.now(UTC),
    )


def test_apply_constraint_ignores_missing_ids() -> None:
    dist = np.array([[0.0, 0.2], [0.2, 0.0]], dtype=np.float32)
    original = dist.copy()
    _apply_constraint_to_matrix(dist, _make_constraint(uuid4(), uuid4(), ConstraintType.MUST_LINK), {}, penalty=10.0)
    np.testing.assert_allclose(dist, original)


def test_apply_constraint_updates_matrix() -> None:
    id_a, id_b = uuid4(), uuid4()
    id_map = {id_a: 0, id_b: 1}
    dist = np.array([[0.0, 0.2], [0.2, 0.0]], dtype=np.float32)
    _apply_constraint_to_matrix(dist, _make_constraint(id_a, id_b, ConstraintType.MUST_LINK), id_map, penalty=0.9)
    assert dist[0, 1] == 0.0
    dist = np.array([[0.0, 0.2], [0.2, 0.0]], dtype=np.float32)
    _apply_constraint_to_matrix(dist, _make_constraint(id_a, id_b, ConstraintType.CANNOT_LINK), id_map, penalty=0.9)
    assert dist[0, 1] == 0.9
