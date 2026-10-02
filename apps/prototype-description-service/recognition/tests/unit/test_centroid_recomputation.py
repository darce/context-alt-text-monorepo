"""Domain completeness tests for centroid recomputation (Task 75vb)."""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from unittest.mock import AsyncMock

import numpy as np
import pytest

from recognition.application.assignment.candidate import AssignmentCandidate, DiscoveryMethod
from recognition.application.assignment.decision import AssignmentDecision, AssignmentOutcome
from recognition.application.persistence.assignment_writer import AssignmentWriter
from recognition.application.settings.clustering import ClusteringSettings
from recognition.domain.cluster import IdentityCluster
from recognition.domain.identity import MediaIdentity
from recognition.domain.repositories import ClusterRepository, MemberRepository


def test_centroid_sql_quality_weights_and_caps_each_media_item_once() -> None:
    """The materialized view weights quality, then averages one vector per media item."""
    migration = (
        Path(__file__).resolve().parents[3]
        / "db"
        / "migrations"
        / "versions"
        / "001_identity_schema.py"
    )
    migration_source = migration.read_text(encoding="utf-8")
    view_match = re.search(
        r"CREATE MATERIALIZED VIEW IF NOT EXISTS mv_identity_cluster_centroids AS"
        r"(?P<query>.*?)\n\s*\"\"\"",
        migration_source,
        flags=re.DOTALL,
    )

    assert view_match is not None, "centroid materialized view SQL must be present"
    query = view_match.group("query")

    assert "GREATEST(0.0, LEAST(1.0, COALESCE(mr.quality_score, 1.0)))" in query
    assert re.search(
        r"media_embeddings AS \(.*?GROUP BY cluster_id, tenant_id, media_id",
        query,
        flags=re.DOTALL,
    )
    assert re.search(
        r"SUM\s*\(\s*unit_embedding\s*\*\s*array_fill\(quality_weight::real,\s*"
        r"ARRAY\[\{EMBEDDING_DIMENSION\}\]\)::vector\s*\)",
        query,
    )
    assert re.search(
        r"\)\s*\*\s*array_fill\(\s*\(1\.0 / SUM\(quality_weight\)\)::real,\s*"
        r"ARRAY\[\{EMBEDDING_DIMENSION\}\]\s*\)::vector",
        query,
    )
    assert not re.search(r"unit_embedding\s*\*\s*quality_weight\b", query)
    assert "AVG(me.media_embedding)" in query


@pytest.fixture
def mock_cluster_repo() -> AsyncMock:
    repo = AsyncMock(spec=ClusterRepository)
    repo.get_representative_count.return_value = 0
    repo.get_all_representatives.return_value = []
    repo.get_curriculum_t.return_value = 0.5
    # Default behavior for update if it exists
    return repo


@pytest.fixture
def mock_member_repo() -> AsyncMock:
    repo = AsyncMock(spec=MemberRepository)
    repo.get_by_cluster.return_value = []
    return repo


@pytest.fixture
def settings() -> ClusteringSettings:
    return ClusteringSettings()


@pytest.fixture
def writer(
    settings: ClusteringSettings,
    mock_cluster_repo: AsyncMock,
    mock_member_repo: AsyncMock,
) -> AssignmentWriter:
    return AssignmentWriter(settings, mock_cluster_repo, mock_member_repo)


def _make_candidate(cluster_id: str) -> AssignmentCandidate:
    vector = np.ones(512, dtype=np.float32)  # Simple vector
    return AssignmentCandidate(
        identity=MediaIdentity(
            id="id-1",
            tenant_id="tenant-1",
            media_id="media-1",
            embedding=vector,
            confidence=0.9,
            bbox_width=1,
            bbox_height=1,
        ),
        identity_vector=vector,
        cluster_id=cluster_id,
        discovery_method=DiscoveryMethod.REPRESENTATIVE,
        discovery_similarity=0.9,
    )


@pytest.mark.asyncio
async def test_centroid_after_addition(
    writer: AssignmentWriter,
    mock_cluster_repo: AsyncMock,
    mock_member_repo: AsyncMock,
) -> None:
    """Test that centroid is recomputed and persisted after a new representative is added."""
    cluster_id = str(uuid.uuid4())
    vector = np.ones(512, dtype=np.float32)
    cluster = IdentityCluster(
        id=cluster_id,
        tenant_id="tenant-1",
        label="Cluster 1",
        centroid=vector,
        created_at=None,
        is_labeled=False,
        identity_count=1,
    )
    mock_cluster_repo.get_by_id.return_value = cluster

    candidate = _make_candidate(cluster_id)
    decision = AssignmentDecision(
        outcome=AssignmentOutcome.ACCEPT,
        candidate=candidate,
        checks_passed=["all"],
        checks_failed=[],
    )

    # Setup: Should add representative
    mock_cluster_repo.get_representative_count.return_value = 0

    # Setup members for centroid calc: includes the new one (simulated)
    # This logic assumes _recompute_centroid fetches all members/reps to compute mean
    mock_cluster_repo.get_all_representatives.return_value = [candidate.identity_vector]

    await writer.persist_assignment(decision)

    # Assert centroid update was triggered
    mock_cluster_repo.update.assert_awaited_with(cluster)
    # Note: mocking objects usually checks reference, ensuring update is called with the same cluster object
    # If the writer creates a new cluster object (immutable update), this assertion might fail if checking identity
    # But usually it's fine for now to just check it was called.
