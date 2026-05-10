"""Unit tests for curation_job merge optimization logic."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
import uuid
from unittest.mock import AsyncMock, Mock, call

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.identity import CurationReplayRecord
from db.models.tenant import Tenant
from recognition.application.orchestration.curation_job import run_curation_job
from recognition.application.persistence.assignment_writer import AssignmentWriter
from recognition.domain.cluster import IdentityCluster
from recognition.domain.repositories import ClusterRepository
from recognition.domain.suggestion import SuggestionRefreshReason


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
    suggestion_refresh_service = Mock()
    suggestion_refresh_service.refresh_for_cluster = AsyncMock()

    cluster_service = Mock()
    cluster_service.constraint_repository = constraint_repo
    cluster_service.retry_matching = AsyncMock()
    cluster_service.suggestion_refresh_service = suggestion_refresh_service

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
    suggestion_refresh_service.refresh_for_cluster.assert_awaited_once_with(target_cluster_id)
    mock_repo.delete.assert_awaited_once_with(source_cluster_id)


@pytest.mark.asyncio
async def test_run_curation_job_advances_refresh_status_for_replay_row(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid.uuid4()
    cluster_id = str(uuid.uuid4())
    db_session.add(Tenant(id=tenant_id, site_url="http://example.test"))
    await db_session.commit()
    replay_row = CurationReplayRecord(
        tenant_id=tenant_id,
        idempotency_key="refresh-idem-1",
        result_status="acknowledged",
        backend_version=1,
        refresh_status="queued",
        refresh_requested_at=datetime.now(tz=UTC),
    )
    db_session.add(replay_row)
    await db_session.commit()

    mock_writer = Mock(spec=AssignmentWriter)
    mock_writer.recompute_representatives = AsyncMock()
    mock_writer.recompute_centroid = AsyncMock()

    mock_repo = Mock(spec=ClusterRepository)
    mock_repo.get_unclustered = AsyncMock(return_value=[])

    refresh_service = Mock()
    refresh_service.refresh_for_cluster = AsyncMock()

    cluster_service = Mock()
    cluster_service.suggestion_refresh_service = refresh_service

    import recognition.application.orchestration.curation_job as curation_job_module

    original_load_replay_record = curation_job_module._load_replay_record
    load_call_count = 0

    async def counting_load_replay_record(**kwargs):
        nonlocal load_call_count
        load_call_count += 1
        return await original_load_replay_record(**kwargs)

    monkeypatch.setattr(curation_job_module, "_load_replay_record", counting_load_replay_record)

    await run_curation_job(
        tenant_id=str(tenant_id),
        cluster_ids=[cluster_id],
        assignment_writer=mock_writer,
        cluster_repo=mock_repo,
        cluster_service=cluster_service,
        refresh_idempotency_key="refresh-idem-1",
        session=db_session,
    )

    refreshed = await db_session.scalar(
        select(CurationReplayRecord).where(CurationReplayRecord.idempotency_key == "refresh-idem-1")
    )
    assert isinstance(refreshed, CurationReplayRecord)
    assert refreshed.refresh_status == "completed"
    assert refreshed.refresh_completed_at is not None
    assert load_call_count == 1


@pytest.mark.asyncio
async def test_run_curation_job_marks_refresh_no_candidates_when_nothing_is_created(db_session: AsyncSession) -> None:
    tenant_id = uuid.uuid4()
    cluster_id = str(uuid.uuid4())
    db_session.add(Tenant(id=tenant_id, site_url="http://example.test"))
    await db_session.commit()
    replay_row = CurationReplayRecord(
        tenant_id=tenant_id,
        idempotency_key="refresh-idem-no-candidates",
        result_status="acknowledged",
        backend_version=1,
        refresh_status="queued",
        refresh_requested_at=datetime.now(tz=UTC),
    )
    db_session.add(replay_row)
    await db_session.commit()

    mock_writer = Mock(spec=AssignmentWriter)
    mock_writer.recompute_representatives = AsyncMock()
    mock_writer.recompute_centroid = AsyncMock()

    mock_repo = Mock(spec=ClusterRepository)
    mock_repo.get_unclustered = AsyncMock(return_value=[])

    refresh_service = Mock()
    refresh_service.refresh_for_cluster = AsyncMock(return_value=0)

    cluster_service = Mock()
    cluster_service.suggestion_refresh_service = refresh_service

    await run_curation_job(
        tenant_id=str(tenant_id),
        cluster_ids=[cluster_id],
        assignment_writer=mock_writer,
        cluster_repo=mock_repo,
        cluster_service=cluster_service,
        refresh_idempotency_key="refresh-idem-no-candidates",
        session=db_session,
    )

    refreshed = await db_session.scalar(
        select(CurationReplayRecord).where(CurationReplayRecord.idempotency_key == "refresh-idem-no-candidates")
    )
    assert isinstance(refreshed, CurationReplayRecord)
    assert refreshed.refresh_status == "no_candidates"
    assert refreshed.refresh_completed_at is not None


@pytest.mark.asyncio
async def test_run_curation_job_marks_refresh_timed_out_when_executor_times_out(db_session: AsyncSession) -> None:
    tenant_id = uuid.uuid4()
    cluster_id = str(uuid.uuid4())
    db_session.add(Tenant(id=tenant_id, site_url="http://example.test"))
    await db_session.commit()
    replay_row = CurationReplayRecord(
        tenant_id=tenant_id,
        idempotency_key="refresh-idem-timeout",
        result_status="acknowledged",
        backend_version=1,
        refresh_status="queued",
        refresh_requested_at=datetime.now(tz=UTC),
    )
    db_session.add(replay_row)
    await db_session.commit()

    mock_writer = Mock(spec=AssignmentWriter)
    mock_writer.recompute_representatives = AsyncMock()
    mock_writer.recompute_centroid = AsyncMock()

    mock_repo = Mock(spec=ClusterRepository)
    mock_repo.get_unclustered = AsyncMock(return_value=[])

    refresh_service = Mock()
    refresh_service.refresh_for_cluster = AsyncMock(side_effect=TimeoutError("refresh timed out"))

    cluster_service = Mock()
    cluster_service.suggestion_refresh_service = refresh_service

    await run_curation_job(
        tenant_id=str(tenant_id),
        cluster_ids=[cluster_id],
        assignment_writer=mock_writer,
        cluster_repo=mock_repo,
        cluster_service=cluster_service,
        refresh_idempotency_key="refresh-idem-timeout",
        session=db_session,
    )

    refreshed = await db_session.scalar(
        select(CurationReplayRecord).where(CurationReplayRecord.idempotency_key == "refresh-idem-timeout")
    )
    assert isinstance(refreshed, CurationReplayRecord)
    assert refreshed.refresh_status == "timed_out"
    assert refreshed.refresh_completed_at is not None


@pytest.mark.asyncio
async def test_run_curation_job_stops_refresh_loop_after_failure_without_replay_state() -> None:
    tenant_id = str(uuid.uuid4())
    cluster_ids = [str(uuid.uuid4()), str(uuid.uuid4())]

    mock_writer = Mock(spec=AssignmentWriter)
    mock_writer.recompute_representatives = AsyncMock()
    mock_writer.recompute_centroid = AsyncMock()

    mock_repo = Mock(spec=ClusterRepository)
    mock_repo.get_unclustered = AsyncMock(return_value=[])

    refresh_service = Mock()
    refresh_service.refresh_for_cluster = AsyncMock(side_effect=[RuntimeError("boom"), 1])

    cluster_service = Mock()
    cluster_service.suggestion_refresh_service = refresh_service

    await run_curation_job(
        tenant_id=tenant_id,
        cluster_ids=cluster_ids,
        assignment_writer=mock_writer,
        cluster_repo=mock_repo,
        cluster_service=cluster_service,
    )

    assert refresh_service.refresh_for_cluster.await_count == 1


@pytest.mark.asyncio
async def test_run_curation_job_skips_refresh_when_replay_row_already_completed(db_session: AsyncSession) -> None:
    tenant_id = uuid.uuid4()
    cluster_id = str(uuid.uuid4())
    completed_at = datetime.now(tz=UTC)
    db_session.add(Tenant(id=tenant_id, site_url="http://example.test"))
    await db_session.commit()
    replay_row = CurationReplayRecord(
        tenant_id=tenant_id,
        idempotency_key="refresh-idem-completed",
        result_status="acknowledged",
        backend_version=1,
        refresh_status="completed",
        refresh_requested_at=completed_at,
        refresh_completed_at=completed_at,
    )
    db_session.add(replay_row)
    await db_session.commit()

    mock_writer = Mock(spec=AssignmentWriter)
    mock_writer.recompute_representatives = AsyncMock()
    mock_writer.recompute_centroid = AsyncMock()

    mock_repo = Mock(spec=ClusterRepository)
    mock_repo.get_unclustered = AsyncMock(return_value=[])

    refresh_service = Mock()
    refresh_service.refresh_for_cluster = AsyncMock(return_value=1)

    cluster_service = Mock()
    cluster_service.suggestion_refresh_service = refresh_service

    await run_curation_job(
        tenant_id=str(tenant_id),
        cluster_ids=[cluster_id],
        assignment_writer=mock_writer,
        cluster_repo=mock_repo,
        cluster_service=cluster_service,
        refresh_idempotency_key="refresh-idem-completed",
        session=db_session,
    )

    refresh_service.refresh_for_cluster.assert_not_awaited()
    refreshed = await db_session.scalar(
        select(CurationReplayRecord).where(CurationReplayRecord.idempotency_key == "refresh-idem-completed")
    )
    assert isinstance(refreshed, CurationReplayRecord)
    assert refreshed.refresh_status == "completed"
    assert refreshed.refresh_completed_at == completed_at


@pytest.mark.asyncio
async def test_run_curation_job_retry_refresh_updates_attempt_timestamps(db_session: AsyncSession) -> None:
    tenant_id = uuid.uuid4()
    cluster_id = str(uuid.uuid4())
    first_requested_at = datetime.now(tz=UTC) - timedelta(minutes=5)
    first_completed_at = first_requested_at + timedelta(seconds=30)
    db_session.add(Tenant(id=tenant_id, site_url="http://example.test"))
    await db_session.commit()
    replay_row = CurationReplayRecord(
        tenant_id=tenant_id,
        idempotency_key="refresh-idem-retry",
        result_status="acknowledged",
        backend_version=1,
        refresh_status="timed_out",
        refresh_requested_at=first_requested_at,
        refresh_completed_at=first_completed_at,
    )
    db_session.add(replay_row)
    await db_session.commit()

    mock_writer = Mock(spec=AssignmentWriter)
    mock_writer.recompute_representatives = AsyncMock()
    mock_writer.recompute_centroid = AsyncMock()

    mock_repo = Mock(spec=ClusterRepository)
    mock_repo.get_unclustered = AsyncMock(return_value=[])

    refresh_service = Mock()
    refresh_service.refresh_for_cluster = AsyncMock(return_value=1)

    cluster_service = Mock()
    cluster_service.suggestion_refresh_service = refresh_service

    await run_curation_job(
        tenant_id=str(tenant_id),
        cluster_ids=[cluster_id],
        assignment_writer=mock_writer,
        cluster_repo=mock_repo,
        cluster_service=cluster_service,
        refresh_idempotency_key="refresh-idem-retry",
        session=db_session,
    )

    refreshed = await db_session.scalar(
        select(CurationReplayRecord).where(CurationReplayRecord.idempotency_key == "refresh-idem-retry")
    )
    assert isinstance(refreshed, CurationReplayRecord)
    assert refreshed.refresh_status == "completed"
    assert refreshed.refresh_requested_at is not None
    assert refreshed.refresh_requested_at > first_requested_at
    assert refreshed.refresh_completed_at is not None
    assert refreshed.refresh_completed_at > first_completed_at


@pytest.mark.asyncio
async def test_run_curation_job_stops_on_timeout_without_replay_persistence() -> None:
    tenant_id = str(uuid.uuid4())
    cluster_ids = [str(uuid.uuid4()), str(uuid.uuid4())]

    mock_writer = Mock(spec=AssignmentWriter)
    mock_writer.recompute_representatives = AsyncMock()
    mock_writer.recompute_centroid = AsyncMock()

    mock_repo = Mock(spec=ClusterRepository)
    mock_repo.get_unclustered = AsyncMock(return_value=[])

    refresh_service = Mock()
    refresh_service.refresh_for_cluster = AsyncMock(side_effect=[TimeoutError("refresh timed out"), 1])

    cluster_service = Mock()
    cluster_service.suggestion_refresh_service = refresh_service

    await run_curation_job(
        tenant_id=tenant_id,
        cluster_ids=cluster_ids,
        assignment_writer=mock_writer,
        cluster_repo=mock_repo,
        cluster_service=cluster_service,
    )

    refresh_service.refresh_for_cluster.assert_awaited_once_with(cluster_ids[0])


@pytest.mark.asyncio
async def test_run_curation_job_marks_refresh_failed_when_executor_raises(db_session: AsyncSession) -> None:
    tenant_id = uuid.uuid4()
    cluster_id = str(uuid.uuid4())
    db_session.add(Tenant(id=tenant_id, site_url="http://example.test"))
    await db_session.commit()
    replay_row = CurationReplayRecord(
        tenant_id=tenant_id,
        idempotency_key="refresh-idem-fail",
        result_status="acknowledged",
        backend_version=1,
        refresh_status="queued",
        refresh_requested_at=datetime.now(tz=UTC),
    )
    db_session.add(replay_row)
    await db_session.commit()

    mock_writer = Mock(spec=AssignmentWriter)
    mock_writer.recompute_representatives = AsyncMock()
    mock_writer.recompute_centroid = AsyncMock()

    mock_repo = Mock(spec=ClusterRepository)
    mock_repo.get_unclustered = AsyncMock(return_value=[])

    refresh_service = Mock()
    refresh_service.refresh_for_cluster = AsyncMock(side_effect=RuntimeError("boom"))

    cluster_service = Mock()
    cluster_service.suggestion_refresh_service = refresh_service

    await run_curation_job(
        tenant_id=str(tenant_id),
        cluster_ids=[cluster_id],
        assignment_writer=mock_writer,
        cluster_repo=mock_repo,
        cluster_service=cluster_service,
        refresh_idempotency_key="refresh-idem-fail",
        session=db_session,
    )

    refreshed = await db_session.scalar(
        select(CurationReplayRecord).where(CurationReplayRecord.idempotency_key == "refresh-idem-fail")
    )
    assert isinstance(refreshed, CurationReplayRecord)
    assert refreshed.refresh_status == "failed"
    assert refreshed.refresh_completed_at is not None


@pytest.mark.asyncio
async def test_run_curation_job_surfaces_missing_candidates_for_bound_identity_ids() -> None:
    tenant_id = str(uuid.uuid4())
    cluster_id = str(uuid.uuid4())

    mock_writer = Mock(spec=AssignmentWriter)
    mock_writer.recompute_representatives = AsyncMock()
    mock_writer.recompute_centroid = AsyncMock()

    mock_repo = Mock(spec=ClusterRepository)
    mock_repo.get_unclustered = AsyncMock(return_value=[])

    refresh_service = Mock()
    refresh_service.refresh_for_cluster = AsyncMock(return_value=0)
    refresh_service.refresh_for_identity = AsyncMock(side_effect=[[object()], [object()]])

    cluster_service = Mock()
    cluster_service.suggestion_refresh_service = refresh_service

    await run_curation_job(
        tenant_id=tenant_id,
        cluster_ids=[cluster_id],
        identity_ids=["identity-1", "identity-2"],
        assignment_writer=mock_writer,
        cluster_repo=mock_repo,
        cluster_service=cluster_service,
    )

    refresh_service.refresh_for_cluster.assert_awaited_once_with(cluster_id)
    refresh_service.refresh_for_identity.assert_has_awaits(
        [
            call(identity_id="identity-1", reason=SuggestionRefreshReason.MANUAL_ASSIGN),
            call(identity_id="identity-2", reason=SuggestionRefreshReason.MANUAL_ASSIGN),
        ]
    )


@pytest.mark.asyncio
async def test_run_curation_job_delegates_curation_refresh_to_single_entrypoint() -> None:
    tenant_id = str(uuid.uuid4())
    cluster_id = str(uuid.uuid4())

    mock_writer = Mock(spec=AssignmentWriter)
    mock_writer.recompute_representatives = AsyncMock()
    mock_writer.recompute_centroid = AsyncMock()

    mock_repo = Mock(spec=ClusterRepository)
    mock_repo.get_unclustered = AsyncMock(return_value=[])

    refresh_after_curation = AsyncMock(return_value=1)
    cluster_service = Mock()
    cluster_service.suggestion_refresh_service = SimpleNamespace(
        refresh_after_curation=refresh_after_curation
    )

    await run_curation_job(
        tenant_id=tenant_id,
        cluster_ids=[cluster_id],
        identity_ids=["identity-1", "identity-2"],
        assignment_writer=mock_writer,
        cluster_repo=mock_repo,
        cluster_service=cluster_service,
    )

    refresh_after_curation.assert_awaited_once_with(
        cluster_id=cluster_id,
        identity_ids=["identity-1", "identity-2"],
        reason=SuggestionRefreshReason.MANUAL_ASSIGN,
    )


@pytest.mark.asyncio
async def test_run_curation_job_leaves_refresh_row_queued_when_refresh_service_missing(
    db_session: AsyncSession,
    caplog: pytest.LogCaptureFixture,
) -> None:
    tenant_id = uuid.uuid4()
    cluster_id = str(uuid.uuid4())
    db_session.add(Tenant(id=tenant_id, site_url="http://example.test"))
    await db_session.commit()
    replay_row = CurationReplayRecord(
        tenant_id=tenant_id,
        idempotency_key="refresh-idem-missing-service",
        result_status="acknowledged",
        backend_version=1,
        refresh_status="queued",
        refresh_requested_at=datetime.now(tz=UTC),
    )
    db_session.add(replay_row)
    await db_session.commit()

    mock_writer = Mock(spec=AssignmentWriter)
    mock_writer.recompute_representatives = AsyncMock()
    mock_writer.recompute_centroid = AsyncMock()

    mock_repo = Mock(spec=ClusterRepository)
    mock_repo.get_unclustered = AsyncMock(return_value=[])

    caplog.set_level("WARNING")

    await run_curation_job(
        tenant_id=str(tenant_id),
        cluster_ids=[cluster_id],
        assignment_writer=mock_writer,
        cluster_repo=mock_repo,
        cluster_service=Mock(suggestion_refresh_service=None),
        refresh_idempotency_key="refresh-idem-missing-service",
        session=db_session,
    )

    refreshed = await db_session.scalar(
        select(CurationReplayRecord).where(
            CurationReplayRecord.idempotency_key == "refresh-idem-missing-service"
        )
    )
    assert isinstance(refreshed, CurationReplayRecord)
    assert refreshed.refresh_status == "queued"
    assert refreshed.refresh_completed_at is None
    assert "refresh service unavailable" in caplog.text
