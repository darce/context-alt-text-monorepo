"""Celery-friendly entry points for clustering jobs."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from db.session import async_session_factory
from recognition.application.identity_clustering_service import IdentityClusteringService

logger = logging.getLogger(__name__)


async def batch_cluster_task(tenant_id: UUID, job_id: UUID | None = None) -> dict[str, object]:
    """
    Async task entry point for clustering. Intended to be wrapped by Celery.

    If job_id is provided, process that job; otherwise, enqueue and process immediately.
    """

    async with async_session_factory() as session:
        service = IdentityClusteringService(session=session, tenant_id=tenant_id)

        if job_id is None:
            result = await service.cluster_identities_hybrid()
            job_id_raw = result.get("job_id")
            parsed_job_id: UUID | None
            if isinstance(job_id_raw, str):
                parsed_job_id = UUID(job_id_raw)
            elif isinstance(job_id_raw, UUID):
                parsed_job_id = job_id_raw
            else:
                parsed_job_id = None
        if parsed_job_id is None:
            logger.info("Clustering completed synchronously for tenant %s", tenant_id)
            clusters_raw: Any = result.get("clusters")
            clusters_list: list[Any] = clusters_raw if isinstance(clusters_raw, list) else []
            logger.info(
                "clustering_telemetry: %s",
                {
                    "stage": "sync_complete",
                    "tenant_id": str(tenant_id),
                    "clusters_created": len(clusters_list),
                },
            )
            return {
                "status": "complete",
                "clusters_created": len(clusters_list),
                "job_id": None,
            }
        job_id = parsed_job_id

    # job_id is guaranteed non-None here
    assert job_id is not None
    logger.info("Starting clustering job %s for tenant %s", job_id, tenant_id)
    clusters = await service.process_clustering_job(job_id)
    logger.info(
        "Completed clustering job %s for tenant %s (%d clusters)",
        job_id,
        tenant_id,
        len(clusters),
    )
    logger.info(
        "clustering_telemetry: %s",
        {
            "stage": "async_complete",
            "tenant_id": str(tenant_id),
            "job_id": str(job_id),
            "clusters_created": len(clusters),
        },
    )
    return {"status": "complete", "job_id": str(job_id), "clusters_created": len(clusters)}
