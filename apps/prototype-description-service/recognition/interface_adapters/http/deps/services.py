"""
Service factory dependencies for recognition HTTP API.

This module provides FastAPI dependencies for constructing application services.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from contextlib import suppress
from functools import lru_cache
from typing import Any, Protocol

from fastapi import Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.tenant_context import require_tenant_record, set_tenant_context
from recognition.application.assignment import AssignmentGate
from recognition.application.discovery import CentroidDiscovery, GraphDiscovery, RepresentativeDiscovery
from recognition.application.orchestration import ClusterService
from recognition.application.orchestration.job_service import JobService
from recognition.application.persistence.assignment_writer import AssignmentWriter
from recognition.application.scan.scan_queue_service import ScanQueueService
from recognition.application.scan.service import ScanService
from recognition.application.settings import ClusteringSettings
from recognition.application.suggestions.merge_suggestions import MergeSuggestionService
from recognition.application.suggestions.refresh_service import SuggestionRefreshService
from recognition.application.suggestions.service import SuggestionService
from recognition.config import get_settings as get_recognition_settings
from recognition.infrastructure.embeddings import get_shared_insightface_adapter
from recognition.infrastructure.repositories import (
    SqlAlchemyClusterRepository,
    SqlAlchemyConstraintRepository,
    SqlAlchemyIdentityClusterBlockRepository,
    SqlAlchemyJobRepository,
    SqlAlchemyMemberRepository,
    SqlAlchemyMergeSuggestionRepository,
    SqlAlchemyScanQueueRepository,
    SqlAlchemySuggestionRepository,
)
from recognition.infrastructure.services import SuggestionExtensionService
from recognition.interface_adapters.http.deps.session import (
    get_clustering_session,
    get_observability_session,
    get_optional_session,
    get_session,
)
from recognition.interface_adapters.http.deps.stores import (
    MediaIdentityService,
    get_mem_job_repo,
)
from recognition.interface_adapters.http.deps.tenant import get_tenant_id_optional
from recognition.interface_adapters.http.middleware.metrics import get_default_metrics
from recognition.observability import ClusteringLogger
from recognition.observability.curation_refresh_metrics import get_default_curation_refresh_metrics
from recognition.observability.persistence import ObservabilityRepository

logger = logging.getLogger(__name__)


class RetentionPolicyServiceProtocol(Protocol):
    """Policy read/write surface consumed by the retention router."""

    async def get_policy(self, tenant_id: str) -> dict[str, Any]: ...

    async def update_policy(self, tenant_id: str, retention_mode: str, actor: str) -> dict[str, Any]: ...

    async def apply_preset(self, tenant_id: str, preset_name: str, actor: str) -> dict[str, Any]: ...

    async def apply_disposal_after_ack(
        self,
        tenant_id: str,
        snapshot_generation_id: str | None,
        actor: str,
    ) -> dict[str, Any]: ...


class RetentionExportServiceProtocol(Protocol):
    """Export surface consumed by the retention router."""

    async def count_exportable_identities(self, tenant_id: str) -> int: ...

    async def export_tenant_data(self, tenant_id: str, actor: str) -> dict[str, Any]: ...

    async def start_async_export(self, tenant_id: str, actor: str) -> dict[str, Any]: ...

    async def get_export_status(self, job_id: str, tenant_id: str) -> dict[str, Any]: ...


class RetentionPurgeServiceProtocol(Protocol):
    """Purge surface consumed by the retention router."""

    async def purge_tenant_data(self, tenant_id: str, actor: str, scope: str = "disposed") -> dict[str, Any]: ...


class AuditRepositoryProtocol(Protocol):
    """Audit listing surface consumed by the retention router."""

    async def list_events(
        self, tenant_id: str, limit: int, offset: int, event_type: str | None = None
    ) -> list[dict[str, Any]]: ...

    async def count_events(self, tenant_id: str, event_type: str | None = None) -> int: ...


@lru_cache
def get_settings() -> ClusteringSettings:
    """Provide clustering settings from the recognition config."""
    return get_recognition_settings().clustering


async def get_suggestion_service(
    session: AsyncSession = Depends(get_session), tenant_id: str | None = Depends(get_tenant_id_optional)
) -> SuggestionService:
    """Repository-backed suggestion service scoped to the tenant."""
    tenant = tenant_id or ""
    repo = SqlAlchemySuggestionRepository(session)
    cluster_repo = SqlAlchemyClusterRepository(session)
    SqlAlchemyMemberRepository(session, tenant_id=tenant)
    block_repo = SqlAlchemyIdentityClusterBlockRepository(session, tenant_id=tenant)
    constraint_repo = SqlAlchemyConstraintRepository(session)
    return SuggestionService(
        repo,
        tenant_id=tenant,
        cluster_repository=cluster_repo,
        session=session,
        block_repository=block_repo,
        constraint_repository=constraint_repo,
    )


async def get_suggestion_extension_service(
    session: AsyncSession = Depends(get_session),
) -> SuggestionExtensionService:
    """Infrastructure service for name suggestions and bulk accept flows."""
    return SuggestionExtensionService(session)


async def get_suggestion_refresh_service(
    session: AsyncSession = Depends(get_session), tenant_id: str | None = Depends(get_tenant_id_optional)
) -> SuggestionRefreshService:
    """Suggestion refresh service scoped to the tenant."""
    tenant = tenant_id or ""
    repo = SqlAlchemySuggestionRepository(session)
    cluster_repo = SqlAlchemyClusterRepository(session)
    member_repo = SqlAlchemyMemberRepository(session, tenant_id=tenant)
    block_repo = SqlAlchemyIdentityClusterBlockRepository(session, tenant_id=tenant)
    constraint_repo = SqlAlchemyConstraintRepository(session)
    settings = get_settings()
    gate = AssignmentGate(
        settings=settings,
        cluster_repository=cluster_repo,
        block_repository=block_repo,
        constraint_repository=constraint_repo,
        member_repository=member_repo,
    )
    return SuggestionRefreshService(
        repo,
        tenant_id=tenant,
        cluster_repository=cluster_repo,
        session=session,
        settings=settings,
        gate=gate,
        block_repository=block_repo,
        constraint_repository=constraint_repo,
    )


async def get_cluster_repository(
    session: AsyncSession = Depends(get_session),
) -> SqlAlchemyClusterRepository:
    """Return a cluster repository backed by the current session."""
    return SqlAlchemyClusterRepository(session)


async def get_merge_suggestion_repository(
    session: AsyncSession = Depends(get_session),
) -> SqlAlchemyMergeSuggestionRepository:
    """Return a merge suggestion repository backed by the current session."""
    return SqlAlchemyMergeSuggestionRepository(session)


async def get_observability_repository(
    session: AsyncSession | None = Depends(get_observability_session),
) -> ObservabilityRepository | None:
    """Return DB-backed observability repository when a real session is available."""
    if session is None:
        return None
    return ObservabilityRepository(session)


async def get_media_identity_service(
    session: AsyncSession | None = Depends(get_optional_session),
) -> MediaIdentityService | None:
    """Return a media identity service when a session is available."""
    if session is None or not isinstance(session, AsyncSession):
        return None
    return MediaIdentityService(session)


async def get_retention_policy_service(
    session: AsyncSession | None = Depends(get_optional_session),
) -> RetentionPolicyServiceProtocol:
    """Return the retention policy service, or fail fast with 503 when the DB is unavailable."""
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="retention policy service unavailable: database connection is unavailable",
        )
    from recognition.application.services.retention_policy_service import RetentionPolicyService

    return RetentionPolicyService(session=session)


async def get_retention_export_service(
    session: AsyncSession = Depends(get_session),
) -> RetentionExportServiceProtocol:
    """Return the tenant export service."""
    from recognition.application.services.export_service import TenantExportService

    return TenantExportService(session=session)


async def get_retention_purge_service(
    session: AsyncSession = Depends(get_session),
) -> RetentionPurgeServiceProtocol:
    """Return the tenant purge service."""
    from recognition.application.services.purge_service import TenantPurgeService

    return TenantPurgeService(session=session)


async def get_audit_repository(
    session: AsyncSession = Depends(get_session),
) -> AuditRepositoryProtocol:
    """Return the audit repository."""
    from recognition.infrastructure.repositories.audit_repository import AuditRepository

    return AuditRepository(session)


class TenantImportServiceProtocol(Protocol):
    """Import surface consumed by the retention router."""

    async def validate_and_import(self, data: dict[str, Any], tenant_id: str, actor: str) -> dict[str, Any]: ...


async def get_retention_import_service(
    session: AsyncSession = Depends(get_session),
) -> TenantImportServiceProtocol:
    """Return the tenant import service."""
    from recognition.application.services.import_service import TenantImportService

    return TenantImportService(session=session)


async def build_cluster_service(
    session: AsyncSession,
    tenant_id: str,
    settings: ClusteringSettings | None = None,
) -> ClusterService:
    """Construct a ClusterService wired with SQLAlchemy repositories."""
    settings = settings or get_settings()

    # Require an existing tenant record before clustering work proceeds.
    tenant_uuid = uuid.UUID(tenant_id)

    # Ensure RLS context is set for this tenant
    await set_tenant_context(session, tenant_uuid)

    await require_tenant_record(session, tenant_uuid)

    cluster_repo = SqlAlchemyClusterRepository(session)
    member_repo = SqlAlchemyMemberRepository(session, tenant_id=tenant_id)
    block_repo = SqlAlchemyIdentityClusterBlockRepository(session, tenant_id=tenant_id)
    assignment_writer = AssignmentWriter(settings, cluster_repo, member_repo, session=session)
    constraint_repo = SqlAlchemyConstraintRepository(session)

    gate = AssignmentGate(
        settings=settings,
        cluster_repository=cluster_repo,
        block_repository=block_repo,
        constraint_repository=constraint_repo,
        member_repository=member_repo,
    )

    suggestion_repo = SqlAlchemySuggestionRepository(session)
    suggestion_service = SuggestionService(
        suggestion_repo,
        tenant_id=tenant_id,
        cluster_repository=cluster_repo,
        session=session,
        block_repository=block_repo,
    )
    suggestion_refresh_service = SuggestionRefreshService(
        suggestion_repo,
        tenant_id=tenant_id,
        cluster_repository=cluster_repo,
        session=session,
        settings=settings,
        gate=gate,
        block_repository=block_repo,
        constraint_repository=constraint_repo,
    )
    merge_suggestion_repo = SqlAlchemyMergeSuggestionRepository(session)
    merge_suggestion_service = MergeSuggestionService(
        merge_suggestion_repo,
        cluster_repository=cluster_repo,
        settings=settings,
    )

    # Create HAC settings (can be overridden later via config)
    from recognition.application.settings.clustering import HACSettings

    hac_settings = HACSettings()

    return ClusterService(
        gate=gate,
        representative_discovery=RepresentativeDiscovery(settings=settings),
        centroid_discovery=CentroidDiscovery(settings=settings),
        graph_discovery=GraphDiscovery(settings=settings, algorithm=None),
        assignment_writer=assignment_writer,
        suggestion_service=suggestion_service,
        suggestion_refresh_service=suggestion_refresh_service,
        merge_suggestion_service=merge_suggestion_service,
        block_repository=block_repo,
        constraint_repository=constraint_repo,
        hac_settings=hac_settings,
        logger=ClusteringLogger(),
        session=session,
    )


async def get_cluster_service(
    session: AsyncSession,
    tenant_id: str,
    settings: ClusteringSettings | None = None,
) -> ClusterService:
    """FastAPI-friendly dependency to construct a ClusterService."""
    return await build_cluster_service(session=session, tenant_id=tenant_id, settings=settings)


def get_cluster_service_builder(
    session: AsyncSession = Depends(get_session),
    settings: ClusteringSettings = Depends(get_settings),
) -> Callable[[str], Awaitable[ClusterService]]:
    """Return a builder that can construct a ClusterService for a given tenant.

    Uses ``get_session`` (not ``get_optional_session``) so that FastAPI's DI
    cache gives mutation endpoints the *same* session instance when they also
    inject ``session=Depends(get_session)``.  Without this, explicit
    ``await session.commit()`` in the router would commit the wrong session,
    causing a client-visible race where refetches still see pre-commit data.
    """

    async def _builder(tenant_id: str) -> ClusterService:
        return await build_cluster_service(session=session, tenant_id=tenant_id, settings=settings)

    return _builder


def get_scan_service_builder(
    session: AsyncSession | None = Depends(get_optional_session),
) -> Callable[[str], Awaitable[ScanService]]:
    """Return a builder for ScanService with DB session and embedder.

    Profile-aware via ``build_embedding_runtime`` (insightface default /
    face_pipeline dark). Set RECOGNITION_RUNTIME_MODE=test for stubs.

    HTTP/inline paths intentionally omit a shared httpx client: URL-fetch
    opens a per-image ``AsyncClient`` inside the detector (face_pipeline and
    insightface) by design. The worker injects a process-scoped client for
    connection reuse; wiring request-scoped lifecycle here would need app
    lifespan plumbing and is out of scope for this surface (E2E-08).
    """
    from recognition.config import get_settings as get_recognition_settings
    from recognition.infrastructure.embeddings.runtime_factory import build_embedding_runtime
    from recognition.interface_adapters.http.middleware.metrics import get_default_metrics

    async def _builder(tenant_id: str) -> ScanService:
        if session is None:
            raise RuntimeError("Database session is required for ScanService")

        settings = get_recognition_settings()
        # API process observer: same registry as /metrics (FINALB-06).
        detector, generator = await build_embedding_runtime(
            settings=settings,
            metrics=get_default_metrics().face_pipeline,
        )

        return ScanService(
            session=session,
            detector=detector,
            generator=generator,
        )

    return _builder


def get_scan_queue_service_factory(
    session: AsyncSession,
) -> ScanQueueService:
    """Factory to create ScanQueueService using an existing session.

    Use this when you already have a session from get_optional_session.
    """
    return ScanQueueService(SqlAlchemyScanQueueRepository(session))


async def get_scan_queue_service(
    session: AsyncSession | None = Depends(get_optional_session),
) -> ScanQueueService:
    """Provide a ScanQueueService backed by the database.

    The async scan queue is only available when the database is reachable.
    """
    if session is None:
        raise RuntimeError("Database session is required for ScanQueueService")
    return ScanQueueService(SqlAlchemyScanQueueRepository(session))


async def get_scan_queue_service_optional(
    session: AsyncSession | None = Depends(get_optional_session),
) -> ScanQueueService | None:
    """Optional ScanQueueService provider for endpoints that can fall back.

    Returns None when the database is unavailable.
    """
    if session is None:
        return None
    return ScanQueueService(SqlAlchemyScanQueueRepository(session))


async def get_scan_queue_repo(
    session: AsyncSession = Depends(get_session),
) -> SqlAlchemyScanQueueRepository:
    """Return a scan queue repository backed by the current session."""
    return SqlAlchemyScanQueueRepository(session)


async def get_job_repo(
    session: AsyncSession = Depends(get_session),
) -> SqlAlchemyJobRepository:
    """Return a general job repository backed by the current session."""
    return SqlAlchemyJobRepository(session)


async def get_job_service(
    session: AsyncSession | None = None,
    tenant_id: str | None = None,
    cluster_service_builder=None,
    scan_service_builder=None,
) -> JobService:
    """Repository-backed job service."""
    if session is not None:
        try:
            await session.execute(text("SELECT 1"))
        except Exception:
            session = None

    if session is not None and tenant_id:
        with suppress(ValueError):
            # Ensure RLS context is set if we have a session and tenant
            # This handles cases where tenant_id comes from body, bypassing get_session's check
            await set_tenant_context(session, uuid.UUID(str(tenant_id)))

    if session is None:
        return JobService(repository=get_mem_job_repo(), cluster_service=None, scan_service=None)
    repo = SqlAlchemyJobRepository(session)
    cluster_service = None
    if callable(cluster_service_builder) and tenant_id:
        maybe_cluster = cluster_service_builder(tenant_id)
        cluster_service = await maybe_cluster if hasattr(maybe_cluster, "__await__") else maybe_cluster
    scan_service = None
    if callable(scan_service_builder) and tenant_id:
        maybe_scan = scan_service_builder(tenant_id)
        scan_service = await maybe_scan if hasattr(maybe_scan, "__await__") else maybe_scan
    refresh_metrics = get_default_curation_refresh_metrics(get_default_metrics().registry)
    return JobService(
        repository=repo,
        cluster_service=cluster_service,
        scan_service=scan_service,
        curation_refresh_metrics=refresh_metrics,
    )


async def get_job_service_dependency() -> JobService:
    """FastAPI-friendly dependency wrapper that prefers persistence when available."""
    try:
        return await get_job_service(session=None, tenant_id=None)
    except Exception:
        return await get_job_service(session=None, tenant_id=None)


async def get_persisted_job_service(
    session: AsyncSession | None = Depends(get_optional_session),
    tenant_id: str | None = Depends(get_tenant_id_optional),
    cluster_service_builder=Depends(get_cluster_service_builder),
    scan_service_builder=Depends(get_scan_service_builder),
) -> JobService:
    """Job service backed by a real session (used in pipeline integration)."""
    return await get_job_service(
        session=session,
        tenant_id=tenant_id,
        cluster_service_builder=cluster_service_builder,
        scan_service_builder=scan_service_builder,
    )


async def get_persisted_cluster_job_service(
    session: AsyncSession | None = Depends(get_optional_session),
    tenant_id: str | None = Depends(get_tenant_id_optional),
    cluster_service_builder=Depends(get_cluster_service_builder),
) -> JobService:
    """Job service for clustering/curation routes that do not need scan-service wiring."""
    return await get_job_service(
        session=session,
        tenant_id=tenant_id,
        cluster_service_builder=cluster_service_builder,
        scan_service_builder=None,
    )


# ---------------------------------------------------------------------------
# E15-3a-BR-21 Slice 4: clustering-flavored factories.
#
# These wrap the same ClusterService / JobService constructors as the
# non-clustering factories, but bind to ``get_clustering_session`` so FastAPI's
# dep cache hands the same clustering-pool session to every dep injected into
# ``POST /recognition/clustering/jobs``.
#
# Intentional differences from the non-clustering variants (see task plan
# PLAN-10, PLAN-11, PLAN-12):
#
#   * ``get_cluster_service_builder_clustering`` does *not* pre-await
#     ``build_cluster_service(tenant_id)`` during dep resolution. Invoking the
#     builder emits ``set_tenant_context`` + ``require_tenant_record`` SQL,
#     which would autobegin a transaction on the *bare* clustering session
#     before the route enters ``async with session.begin():``. Instead, we
#     return the builder itself so the route can ``await builder(tenant_id)``
#     inside its own owned transaction (PLAN-12).
#
#   * ``get_persisted_cluster_job_service_clustering`` does *not* delegate to
#     ``get_job_service()``, which autobegins a txn via ``SELECT 1`` +
#     ``set_tenant_context``. Instead, it constructs ``JobService`` directly
#     from ``SqlAlchemyJobRepository(session)`` with ``cluster_service=None``
#     so the route can later assign the cluster service *after* the owned
#     transaction has applied safety settings and tenant context (PLAN-11).
# ---------------------------------------------------------------------------


def get_cluster_service_builder_clustering(
    session: AsyncSession = Depends(get_clustering_session),
    settings: ClusteringSettings = Depends(get_settings),
) -> Callable[[str], Awaitable[ClusterService]]:
    """Clustering-pool builder for the route-owned transaction (PLAN-12).

    Returns a builder bound to the *clustering* session so FastAPI's DI cache
    hands the same session to ``get_persisted_cluster_job_service_clustering``.
    The route invokes the returned builder inside its own ``session.begin()``
    so ``build_cluster_service``'s internal ``set_tenant_context`` +
    ``require_tenant_record`` SQL lands inside the owned transaction.
    """

    async def _builder(tenant_id: str) -> ClusterService:
        return await build_cluster_service(session=session, tenant_id=tenant_id, settings=settings)

    return _builder


async def get_persisted_cluster_job_service_clustering(
    session: AsyncSession = Depends(get_clustering_session),
) -> JobService:
    """Clustering-pool JobService wired without any pre-route SQL (PLAN-11).

    Must not:
      * call ``get_job_service()`` (that helper issues ``SELECT 1`` +
        ``set_tenant_context``, autobegining a txn on the bare clustering
        session before the route's ``session.begin()`` block).
      * pre-await ``cluster_service_builder(tenant_id)`` (that would trigger
        ``build_cluster_service`` SQL on the clustering session).

    Constructs ``JobService`` directly with ``cluster_service=None`` so the
    route assigns the real cluster service *inside* its owned txn block, after
    safety settings + tenant context have been applied.
    """
    repo = SqlAlchemyJobRepository(session)
    return JobService(repository=repo, cluster_service=None, scan_service=None)


__all__ = [
    "get_settings",
    "get_shared_insightface_adapter",
    "get_suggestion_service",
    "get_cluster_repository",
    "get_observability_repository",
    "get_media_identity_service",
    "build_cluster_service",
    "get_cluster_service",
    "get_cluster_service_builder",
    "get_scan_service_builder",
    "get_scan_queue_service_factory",
    "get_scan_queue_service",
    "get_scan_queue_service_optional",
    "get_scan_queue_repo",
    "get_job_repo",
    "get_job_service",
    "get_job_service_dependency",
    "get_persisted_job_service",
    "get_persisted_cluster_job_service",
    "get_cluster_service_builder_clustering",
    "get_persisted_cluster_job_service_clustering",
    "get_merge_suggestion_repository",
]
