"""Clustering-related background tasks."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from recognition.application.orchestration.protocols import SuggestionRefreshServiceProtocol

logger = logging.getLogger(__name__)


class ClusterServiceProtocol(Protocol):
    """Protocol for background task helpers."""

    suggestion_refresh_service: SuggestionRefreshServiceProtocol | None

    async def retry_matching(self, *, target_cluster_id: str, tenant_id: str) -> None:
        """Retry matching after merge operations."""


async def run_background_retry(
    tenant_id: str,
    cluster_id: str,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    cluster_service_builder: Callable[..., Awaitable[ClusterServiceProtocol]],
) -> None:
    """Execute post-merge matching retry in a background task with fresh session."""
    try:
        async with session_factory() as session:
            cluster_service = await cluster_service_builder(session=session, tenant_id=tenant_id)
            await cluster_service.retry_matching(target_cluster_id=cluster_id, tenant_id=tenant_id)
    except Exception as exc:
        logger.exception("Background merge retry failed for cluster %s: %s", cluster_id, exc)


async def run_background_surface_suggestions(
    tenant_id: str,
    cluster_id: str,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    cluster_service_builder: Callable[..., Awaitable[ClusterServiceProtocol]],
) -> None:
    """Surface suggestions for newly labeled clusters with a fresh session."""
    import asyncio

    # Small delay to ensure the main request's transaction has committed
    await asyncio.sleep(0.5)
    logger.info(
        "[suggestions] Background surfacing starting for cluster_id=%s tenant_id=%s",
        cluster_id,
        tenant_id,
    )
    try:
        async with session_factory() as session:
            cluster_service = await cluster_service_builder(session=session, tenant_id=tenant_id)
            refresh_service = getattr(cluster_service, "suggestion_refresh_service", None)
            surface_fn = getattr(refresh_service, "surface_for_newly_labeled_cluster", None)
            if callable(surface_fn):
                surfaced = await surface_fn(cluster_id)
                logger.info(
                    "[suggestions] Background surfacing completed: cluster_id=%s surfaced=%d",
                    cluster_id,
                    surfaced,
                )
            else:
                logger.warning(
                    "[suggestions] Background surfacing: surface_fn not available for cluster_id=%s",
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
            refresh_service = getattr(cluster_service, "suggestion_refresh_service", None)
            if refresh_service is not None:
                await refresh_service.refresh_for_cluster(cluster_id)
    except Exception as exc:
        logger.exception(
            "Background suggestion refresh failed for cluster %s: %s",
            cluster_id,
            exc,
        )
