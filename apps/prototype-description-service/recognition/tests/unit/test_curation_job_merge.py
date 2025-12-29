"""Unit tests for curation_job merge optimization logic."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, Mock

import pytest

from recognition.application.orchestration.curation_job import run_curation_job
from recognition.application.persistence.assignment_writer import AssignmentWriter
from recognition.domain.cluster import IdentityCluster
from recognition.domain.repositories import ClusterRepository


@pytest.mark.asyncio
async def test_run_curation_job_deletes_source_cluster() -> None:
    """Verify run_curation_job deletes source_cluster_id if provided."""
    tenant_id = str(uuid.uuid4())
    cluster_ids = [str(uuid.uuid4())]
    source_cluster_id = str(uuid.uuid4())

    mock_writer = Mock(spec=AssignmentWriter)
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


@pytest.mark.asyncio
async def test_run_curation_job_skips_deletion_if_none() -> None:
    """Verify run_curation_job does not delete if source_cluster_id is None."""
    tenant_id = str(uuid.uuid4())
    cluster_ids = [str(uuid.uuid4())]

    mock_writer = Mock(spec=AssignmentWriter)
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


@pytest.mark.asyncio
async def test_run_curation_job_creates_merge_must_link_constraint() -> None:
    tenant_id = str(uuid.uuid4())
    target_cluster_id = str(uuid.uuid4())
    source_cluster_id = str(uuid.uuid4())

    source_rep_id = str(uuid.uuid4())
    target_rep_id = str(uuid.uuid4())

    mock_writer = Mock(spec=AssignmentWriter)
    mock_writer.recompute_representatives = AsyncMock()
    mock_writer.recompute_centroid = AsyncMock()

    mock_repo = Mock(spec=ClusterRepository)
    mock_repo.delete = AsyncMock()
    mock_repo.get_unclustered = AsyncMock(return_value=[])

    mock_repo.get_by_id = AsyncMock(
        side_effect=lambda cid: (
            IdentityCluster(
                id=source_cluster_id,
                tenant_id=tenant_id,
                label=None,
                is_labeled=False,
                identity_count=0,
                representative_identity_id=source_rep_id,
            )
            if cid == source_cluster_id
            else IdentityCluster(
                id=target_cluster_id,
                tenant_id=tenant_id,
                label=None,
                is_labeled=False,
                identity_count=0,
                representative_identity_id=target_rep_id,
            )
            if cid == target_cluster_id
            else None
        )
    )

    constraint_repo = Mock()
    constraint_repo.create = AsyncMock()
    suggestion_service = Mock()
    suggestion_service.refresh_for_cluster = AsyncMock()

    cluster_service = Mock()
    cluster_service.constraint_repository = constraint_repo
    cluster_service.retry_matching = AsyncMock()
    cluster_service.suggestion_service = suggestion_service

    await run_curation_job(
        tenant_id=tenant_id,
        cluster_ids=[target_cluster_id],
        assignment_writer=mock_writer,
        cluster_repo=mock_repo,
        cluster_service=cluster_service,
        run_incremental_clustering=True,
        source_cluster_id=source_cluster_id,
    )

    constraint_repo.create.assert_awaited_once()
    cluster_service.retry_matching.assert_awaited_once_with(target_cluster_id=target_cluster_id, tenant_id=tenant_id)
    suggestion_service.refresh_for_cluster.assert_awaited_once_with(target_cluster_id)
    mock_repo.delete.assert_awaited_once_with(source_cluster_id)
