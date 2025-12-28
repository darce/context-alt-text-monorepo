"""Unit tests for curation_job merge optimization logic."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, Mock

import pytest

from recognition.application.orchestration.curation_job import run_curation_job
from recognition.application.persistence.assignment_writer import AssignmentWriter
from recognition.domain.repositories import ClusterRepository


@pytest.mark.asyncio
async def test_run_curation_job_deletes_source_cluster() -> None:
    """Verify run_curation_job deletes source_cluster_id if provided."""
    tenant_id = str(uuid.uuid4())
    cluster_ids = [str(uuid.uuid4())]
    source_cluster_id = str(uuid.uuid4())

    mock_writer = Mock(spec=AssignmentWriter)
    # Ensure concurrent refresh is called
    mock_writer.refresh_centroids_view_concurrent = AsyncMock()
    mock_writer.recompute_representatives = AsyncMock()
    mock_writer.recompute_centroid = AsyncMock()

    mock_repo = Mock(spec=ClusterRepository)
    mock_repo.delete = AsyncMock()

    # Mock unclustered check to avoid service call
    mock_repo.get_unclustered = AsyncMock(return_value=[])

    await run_curation_job(
        tenant_id=tenant_id,
        cluster_ids=cluster_ids,
        assignment_writer=mock_writer,
        cluster_repo=mock_repo,
        source_cluster_id=source_cluster_id,  # This triggers the deletion
    )

    # Verify source cluster deletion
    mock_repo.delete.assert_awaited_once_with(source_cluster_id)

    # Verify concurrent refresh called
    mock_writer.refresh_centroids_view_concurrent.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_curation_job_skips_deletion_if_none() -> None:
    """Verify run_curation_job does not delete if source_cluster_id is None."""
    tenant_id = str(uuid.uuid4())
    cluster_ids = [str(uuid.uuid4())]

    mock_writer = Mock(spec=AssignmentWriter)
    mock_writer.refresh_centroids_view_concurrent = AsyncMock()
    mock_writer.recompute_representatives = AsyncMock()
    mock_writer.recompute_centroid = AsyncMock()

    mock_repo = Mock(spec=ClusterRepository)
    mock_repo.delete = AsyncMock()
    mock_repo.get_unclustered = AsyncMock(return_value=[])

    await run_curation_job(
        tenant_id=tenant_id,
        cluster_ids=cluster_ids,
        assignment_writer=mock_writer,
        cluster_repo=mock_repo,
        source_cluster_id=None,
    )

    # Verify delete NOT called
    mock_repo.delete.assert_not_called()

    # Verify concurrent refresh still called
    mock_writer.refresh_centroids_view_concurrent.assert_awaited_once()
