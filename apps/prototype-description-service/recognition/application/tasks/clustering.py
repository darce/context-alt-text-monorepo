"""Clustering-related background tasks."""

from __future__ import annotations

import asyncio
import logging
import time as _time
from collections.abc import Awaitable, Callable
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from recognition.application.orchestration.protocols import SuggestionRefreshServiceProtocol
from recognition.application.similarity import RepresentativeCache
from recognition.domain.repositories import ClusterRepository

logger = logging.getLogger(__name__)

_BACKGROUND_SURFACE_SUGGESTIONS_SEMAPHORE = asyncio.Semaphore(3)


class ClusterServiceProtocol(Protocol):
    """Protocol for background task helpers."""

    suggestion_refresh_service: SuggestionRefreshServiceProtocol | None

    @property
    def cluster_repository(self) -> ClusterRepository:
        """Return the cluster repository for query helpers."""

    async def retry_matching(self, *, target_cluster_id: str, tenant_id: str) -> None:
        """Retry matching after merge operations."""


async def run_background_surface_suggestions(
    tenant_id: str,
    cluster_id: str,
    cluster_label: str,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    cluster_service_builder: Callable[..., Awaitable[ClusterServiceProtocol]],
) -> None:
    """Surface suggestions for newly labeled clusters with a fresh session.

    Uses the optimistic update pattern: the caller passes the known label
    rather than re-reading it, avoiding MVCC snapshot isolation issues where
    the background task might see pre-commit data.
    """
    _t_task_start = _time.perf_counter()

    logger.info(
        "[suggestions] Background surfacing starting for cluster_id=%s label=%s tenant_id=%s",
        cluster_id,
        cluster_label,
        tenant_id,
    )
    try:
        # Timeout to prevent background task from blocking too long
        async with asyncio.timeout(30):  # 30 second max
            async with _BACKGROUND_SURFACE_SUGGESTIONS_SEMAPHORE:
                chunk_target = 1000
                async with session_factory() as session:
                    cluster_service = await cluster_service_builder(session=session, tenant_id=tenant_id)
                    refresh_service = cluster_service.suggestion_refresh_service
                    if refresh_service is None:
                        logger.warning(
                            "[suggestions] Background surfacing: surface_fn not available for cluster_id=%s",
                            cluster_id,
                        )
                        return

                    cluster_repository = cluster_service.cluster_repository
                    rep_cache = await RepresentativeCache.load([cluster_id], cluster_repository)
                    rep_embeddings = rep_cache.get_representatives(cluster_id)
                    if rep_embeddings is None:
                        logger.info(
                            "[suggestions] Background surfacing: no representatives cluster_id=%s",
                            cluster_id,
                        )
                        return

                    all_clusters = await cluster_repository.get_by_tenant(tenant_id, limit=1000)
                    unlabeled_clusters = [
                        c
                        for c in all_clusters
                        if c.id != cluster_id
                        and (not c.user_confirmed or not c.label or c.label.startswith("cluster-"))
                    ]

                if not unlabeled_clusters:
                    logger.info(
                        "[suggestions] Background surfacing: no unlabeled clusters to scan cluster_id=%s",
                        cluster_id,
                    )
                    return

                identity_counts = {
                    cluster.id: max(int(cluster.identity_count or 1), 1) for cluster in unlabeled_clusters if cluster.id
                }
                total_estimated_identities = sum(identity_counts.values())

                # Only the newly labeled cluster is preloaded for matching.
                labeled_reps = {cluster_id: rep_embeddings}
                chunks: list[list[str]] = []
                current_chunk: list[str] = []
                current_count = 0
                for unlabeled_cluster in unlabeled_clusters:
                    if not unlabeled_cluster.id:
                        continue
                    identity_count = identity_counts.get(unlabeled_cluster.id, 1)
                    if current_chunk and current_count + identity_count > chunk_target:
                        chunks.append(current_chunk)
                        current_chunk = []
                        current_count = 0
                    current_chunk.append(unlabeled_cluster.id)
                    current_count += identity_count
                if current_chunk:
                    chunks.append(current_chunk)

                logger.info(
                    "[suggestions] Background surfacing: %d unlabeled clusters (est_identities=%d) chunk_target=%d chunks=%d",
                    len(unlabeled_clusters),
                    total_estimated_identities,
                    chunk_target,
                    len(chunks),
                )

                total_surfaced = 0
                for chunk_idx, chunk_ids in enumerate(chunks, start=1):
                    chunk_estimated_identities = sum(identity_counts.get(cluster_id, 1) for cluster_id in chunk_ids)
                    _t_chunk_start = _time.perf_counter()
                    async with session_factory() as session:
                        cluster_service = await cluster_service_builder(session=session, tenant_id=tenant_id)
                        refresh_service = cluster_service.suggestion_refresh_service
                        if refresh_service is None:
                            logger.warning(
                                "[suggestions] Background surfacing: surface_fn not available for cluster_id=%s",
                                cluster_id,
                            )
                            break
                        chunk_surfaced = await refresh_service.surface_for_newly_labeled_cluster(
                            cluster_id,
                            cluster_label=cluster_label,
                            candidate_cluster_ids=chunk_ids,
                            representatives_by_cluster=labeled_reps,
                        )
                        # Background sessions are not wrapped by request-scoped commit middleware.
                        # Explicit commit ensures surfaced suggestions are persisted.
                        await session.commit()
                        total_surfaced += chunk_surfaced
                    chunk_elapsed = _time.perf_counter() - _t_chunk_start
                    logger.info(
                        "[suggestions] Background surfacing chunk %d/%d completed: clusters=%d est_identities=%d surfaced=%d time=%.2fs",
                        chunk_idx,
                        len(chunks),
                        len(chunk_ids),
                        chunk_estimated_identities,
                        chunk_surfaced,
                        chunk_elapsed,
                    )

                total_elapsed = _time.perf_counter() - _t_task_start
                logger.info(
                    "[suggestions] Background surfacing completed: cluster_id=%s surfaced=%d total_time=%.2fs est_identities=%d",
                    cluster_id,
                    total_surfaced,
                    total_elapsed,
                    total_estimated_identities,
                )
    except TimeoutError:
        logger.warning(
            "[suggestions] Background surfacing timed out after 30s: cluster_id=%s",
            cluster_id,
        )
    except Exception as exc:
        logger.exception(
            "Background suggestion surfacing failed for cluster %s: %s",
            cluster_id,
            exc,
        )


async def run_background_refresh_suggestions(
    tenant_id: str,
    cluster_id: str,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    cluster_service_builder: Callable[..., Awaitable[ClusterServiceProtocol]],
) -> None:
    """Refresh suggestions for a cluster with a fresh session."""
    try:
        async with session_factory() as session:
            cluster_service = await cluster_service_builder(session=session, tenant_id=tenant_id)
            refresh_service = cluster_service.suggestion_refresh_service
            if refresh_service is not None:
                await refresh_service.refresh_for_cluster(cluster_id)
                await session.commit()
    except Exception as exc:
        logger.exception(
            "Background suggestion refresh failed for cluster %s: %s",
            cluster_id,
            exc,
        )


async def run_background_backfill_suggestions(
    tenant_id: str,
    created_cluster_ids: list[str],
    *,
    fallback_window_minutes: int = 30,
    session_factory: async_sessionmaker[AsyncSession],
    cluster_service_builder: Callable[..., Awaitable[ClusterServiceProtocol]],
) -> None:
    """Backfill suggestions for newly created clusters with a fresh session."""
    if not created_cluster_ids and fallback_window_minutes <= 0:
        logger.info("[suggestions] Background backfill skipped: no created cluster ids tenant_id=%s", tenant_id)
        return

    try:
        async with asyncio.timeout(30):
            async with session_factory() as session:
                cluster_service = await cluster_service_builder(session=session, tenant_id=tenant_id)
                refresh_service = cluster_service.suggestion_refresh_service
                if refresh_service is None:
                    logger.warning(
                        "[suggestions] Background backfill: refresh service unavailable tenant_id=%s",
                        tenant_id,
                    )
                    return

                surfaced = await refresh_service.backfill_for_new_unlabeled_clusters(
                    tenant_id=tenant_id,
                    created_cluster_ids=created_cluster_ids,
                    fallback_window_minutes=fallback_window_minutes,
                )
                await session.commit()
                logger.info(
                    "[suggestions] Background backfill complete tenant_id=%s created_clusters=%d surfaced=%d",
                    tenant_id,
                    len(created_cluster_ids),
                    surfaced,
                )
    except TimeoutError:
        logger.warning("[suggestions] Background backfill timed out after 30s tenant_id=%s", tenant_id)
    except Exception as exc:
        logger.exception("[suggestions] Background backfill failed tenant_id=%s err=%s", tenant_id, exc)
