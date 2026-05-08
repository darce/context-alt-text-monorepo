"""
Post-curation recompute job runner.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.identity import CurationReplayRecord
from recognition.application.orchestration.cluster_service import ClusterService
from recognition.application.persistence.assignment_writer import AssignmentWriter
from recognition.domain.constraints import ConstraintSource, ConstraintType
from recognition.domain.repositories import ClusterRepository
from recognition.domain.suggestion import SuggestionRefreshReason
from roster.application.curation_sync_service import CurationRefreshStatus

logger = logging.getLogger(__name__)


_REFRESH_SUCCESS_TERMINAL_STATUSES = {
    CurationRefreshStatus.COMPLETED.value,
    CurationRefreshStatus.NO_CANDIDATES.value,
}


def _refresh_result_created_candidates(result: object) -> bool:
    if isinstance(result, bool):
        return result
    if isinstance(result, int):
        return result > 0
    if isinstance(result, Sequence) and not isinstance(result, (str, bytes, bytearray)):
        return len(result) > 0
    return result is not None


async def run_curation_job(
    *,
    tenant_id: str,
    cluster_ids: Sequence[str],
    identity_ids: Sequence[str] | None = None,
    assignment_writer: AssignmentWriter,
    cluster_repo: ClusterRepository,
    cluster_service: ClusterService | None = None,
    run_incremental_clustering: bool = True,
    source_cluster_id: str | None = None,
    refresh_idempotency_key: str | None = None,
    session: AsyncSession | None = None,
) -> dict[str, int]:
    """Execute post-curation cleanup tasks.

    Args:
        tenant_id: Tenant owning the clusters.
        cluster_ids: Clusters to recompute.
        assignment_writer: Writer used to recompute representatives/centroid.
        cluster_repo: Repository used to inspect unclustered identities.
        cluster_service: Optional cluster service for incremental clustering.
        run_incremental_clustering: Whether to re-cluster orphans.
        source_cluster_id: Optional source cluster ID to delete after merge cleanup.
        refresh_idempotency_key: Optional replay key for durable refresh lifecycle updates.
        session: Optional session used to update replay-row refresh state.

    Returns:
        Dict with counts: {"clusters_recomputed": N, "identities_clustered": M}.
    """
    unique_cluster_ids = list(dict.fromkeys(cluster_ids))
    unique_identity_ids = list(dict.fromkeys(identity_ids or []))
    logger.info(
        "[curation_job] START tenant_id=%s cluster_ids=%s",
        tenant_id,
        unique_cluster_ids,
    )

    for cluster_id in unique_cluster_ids:
        await assignment_writer.recompute_representatives(cluster_id)
        await assignment_writer.recompute_centroid(cluster_id)

    identities_clustered = 0
    if run_incremental_clustering and cluster_service is not None:
        unclustered = await cluster_repo.get_unclustered(tenant_id)
        if unclustered:
            result = await cluster_service.cluster_unclustered_identities(tenant_id, commit=False)
            identities_clustered = int(getattr(result, "completed", 0) or 0)

    if source_cluster_id and cluster_service is not None and unique_cluster_ids:
        target_cluster_id = unique_cluster_ids[0]
        constraint_repo = getattr(cluster_service, "constraint_repository", None)
        if constraint_repo is not None:
            try:
                source_cluster = await cluster_repo.get_by_id(source_cluster_id)
                target_cluster = await cluster_repo.get_by_id(target_cluster_id)
                source_rep_id = getattr(source_cluster, "representative_identity_id", None) if source_cluster else None
                target_rep_id = getattr(target_cluster, "representative_identity_id", None) if target_cluster else None
                if source_rep_id and target_rep_id and source_rep_id != target_rep_id:
                    await constraint_repo.create(
                        tenant_id=tenant_id,
                        identity_a=str(source_rep_id),
                        identity_b=str(target_rep_id),
                        constraint_type=ConstraintType.MUST_LINK.value,
                        source=ConstraintSource.MERGE.value,
                    )
            except Exception as exc:
                logger.warning(
                    "[curation_job] must_link create failed tenant_id=%s source_cluster_id=%s target_cluster_id=%s: %s",
                    tenant_id,
                    source_cluster_id,
                    target_cluster_id,
                    exc,
                )

        try:
            await cluster_service.retry_matching(target_cluster_id=target_cluster_id, tenant_id=tenant_id)
        except Exception as exc:
            logger.warning(
                "[curation_job] retry_matching failed tenant_id=%s target_cluster_id=%s: %s",
                tenant_id,
                target_cluster_id,
                exc,
            )

    refresh_service = getattr(cluster_service, "suggestion_refresh_service", None) if cluster_service is not None else None
    replay_session = session
    if replay_session is None and refresh_idempotency_key:
        logger.warning(
            "[curation_job] replay session unavailable tenant_id=%s idempotency_key=%s",
            tenant_id,
            refresh_idempotency_key,
        )
    replay_record: CurationReplayRecord | None = None
    if replay_session is not None and refresh_idempotency_key:
        replay_record = await _load_replay_record(
            session=replay_session,
            tenant_id=tenant_id,
            idempotency_key=refresh_idempotency_key,
        )
    if refresh_service is None:
        logger.warning("[curation_job] refresh service unavailable tenant_id=%s cluster_ids=%s", tenant_id, unique_cluster_ids)
    elif replay_record is not None and replay_record.refresh_status in _REFRESH_SUCCESS_TERMINAL_STATUSES:
        logger.info(
            "[curation_job] refresh already settled tenant_id=%s idempotency_key=%s refresh_status=%s",
            tenant_id,
            refresh_idempotency_key,
            replay_record.refresh_status,
        )
    elif unique_cluster_ids:
        if replay_session is not None and refresh_idempotency_key:
            replay_record = await _set_refresh_status(
                session=replay_session,
                tenant_id=tenant_id,
                idempotency_key=refresh_idempotency_key,
                status=CurationRefreshStatus.RUNNING,
                record=replay_record,
            )
        refresh_failed = False
        refresh_created_candidates = False
        refresh_for_identity = getattr(refresh_service, "refresh_for_identity", None)
        for cluster_id in unique_cluster_ids:
            try:
                refreshed = await refresh_service.refresh_for_cluster(cluster_id)
                cluster_refresh_created = _refresh_result_created_candidates(refreshed)
                if cluster_refresh_created:
                    refresh_created_candidates = True
                if not cluster_refresh_created and unique_identity_ids and callable(refresh_for_identity):
                    for identity_id in unique_identity_ids:
                        identity_refreshed = await refresh_for_identity(
                            identity_id=identity_id,
                            reason=SuggestionRefreshReason.MANUAL_ASSIGN,
                        )
                        if _refresh_result_created_candidates(identity_refreshed):
                            refresh_created_candidates = True
            except TimeoutError as exc:
                logger.warning(
                    "[curation_job] refresh_for_cluster timed out tenant_id=%s cluster_id=%s: %s",
                    tenant_id,
                    cluster_id,
                    exc,
                )
                refresh_failed = True
                if replay_session is not None and refresh_idempotency_key:
                    replay_record = await _set_refresh_status(
                        session=replay_session,
                        tenant_id=tenant_id,
                        idempotency_key=refresh_idempotency_key,
                        status=CurationRefreshStatus.TIMED_OUT,
                        record=replay_record,
                    )
                break
            except Exception as exc:
                logger.warning(
                    "[curation_job] refresh_for_cluster failed tenant_id=%s cluster_id=%s: %s",
                    tenant_id,
                    cluster_id,
                    exc,
                )
                if replay_session is not None and refresh_idempotency_key:
                    replay_record = await _set_refresh_status(
                        session=replay_session,
                        tenant_id=tenant_id,
                        idempotency_key=refresh_idempotency_key,
                        status=CurationRefreshStatus.FAILED,
                        record=replay_record,
                    )
                refresh_failed = True
                break
        if replay_session is not None and refresh_idempotency_key and not refresh_failed:
            replay_record = await _set_refresh_status(
                session=replay_session,
                tenant_id=tenant_id,
                idempotency_key=refresh_idempotency_key,
                status=(
                    CurationRefreshStatus.COMPLETED
                    if refresh_created_candidates
                    else CurationRefreshStatus.NO_CANDIDATES
                ),
                record=replay_record,
            )

    logger.info(
        "[curation_job] COMPLETE tenant_id=%s clusters_recomputed=%d identities_clustered=%d",
        tenant_id,
        len(unique_cluster_ids),
        identities_clustered,
    )

    if source_cluster_id:
        logger.info("[curation_job] cleaning up merged source_cluster=%s", source_cluster_id)
        # Delete source cluster after recomputations are complete
        if cluster_repo:
            merge_suggestion_service = (
                getattr(cluster_service, "merge_suggestion_service", None) if cluster_service else None
            )
            delete_by_cluster = (
                getattr(merge_suggestion_service, "delete_by_cluster", None) if merge_suggestion_service else None
            )
            if callable(delete_by_cluster):
                with contextlib.suppress(Exception):
                    await delete_by_cluster(tenant_id, source_cluster_id)
                    if unique_cluster_ids:
                        await delete_by_cluster(tenant_id, unique_cluster_ids[0])
            await cluster_repo.delete(source_cluster_id)

    return {
        "clusters_recomputed": len(unique_cluster_ids),
        "identities_clustered": identities_clustered,
    }


async def _load_replay_record(
    *,
    session: AsyncSession,
    tenant_id: str,
    idempotency_key: str,
) -> CurationReplayRecord | None:
    result = await session.execute(
        select(CurationReplayRecord).where(
            CurationReplayRecord.tenant_id == UUID(tenant_id),
            CurationReplayRecord.idempotency_key == idempotency_key,
        )
    )
    record = result.scalar_one_or_none()
    return record if isinstance(record, CurationReplayRecord) else None


async def _set_refresh_status(
    *,
    session: AsyncSession,
    tenant_id: str,
    idempotency_key: str,
    status: CurationRefreshStatus,
    record: CurationReplayRecord | None = None,
) -> CurationReplayRecord | None:
    if record is None:
        record = await _load_replay_record(
            session=session,
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
        )
    if record is None:
        return None

    now = datetime.now(tz=UTC)
    record.refresh_status = status.value
    if status is CurationRefreshStatus.RUNNING:
        record.refresh_requested_at = now
        record.refresh_completed_at = None
    elif status in {
        CurationRefreshStatus.NO_CANDIDATES,
        CurationRefreshStatus.TIMED_OUT,
        CurationRefreshStatus.COMPLETED,
        CurationRefreshStatus.FAILED,
    }:
        record.refresh_completed_at = now
    await session.flush()
    return record
