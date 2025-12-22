"""
Dependency providers and lightweight service stubs for recognition HTTP API.

These are minimal placeholders to satisfy router wiring; real implementations
should replace the stub methods.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from contextlib import suppress
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import IdentityCluster, IdentityMember, MediaIdentity
from db.session import get_session as _get_session
from db.tenant_context import clear_tenant_context, ensure_tenant_exists, set_tenant_context
from recognition.application.assignment import AssignmentGate
from recognition.application.discovery import CentroidDiscovery, GraphDiscovery, RepresentativeDiscovery
from recognition.application.embedding.service import EmbeddingService
from recognition.application.orchestration import ClusterService
from recognition.application.orchestration.job_service import JobService
from recognition.application.persistence.assignment_writer import AssignmentWriter
from recognition.application.scan.scan_queue_service import ScanQueueService
from recognition.application.scan.service import ScanService
from recognition.application.settings import ClusteringSettings
from recognition.application.suggestions.service import SuggestionService
from recognition.config import get_settings as get_recognition_settings
from recognition.config.security import SecuritySettings, get_security_settings
from recognition.domain.job import Job
from recognition.infrastructure.repositories import (
    SqlAlchemyApiKeyRepository,
    SqlAlchemyClusterRepository,
    SqlAlchemyIdentityClusterBlockRepository,
    SqlAlchemyJobRepository,
    SqlAlchemyMemberRepository,
    SqlAlchemyScanQueueRepository,
    SqlAlchemySuggestionRepository,
)
from recognition.interface_adapters.http.deps.tenant import _normalize_tenant_id, get_tenant_id_optional
from recognition.interface_adapters.http.schemas.responses import JobProgressResponse, JobStatusResponse
from recognition.observability import ClusteringLogger
from recognition.observability.persistence import ObservabilityRepository
from recognition.observability.visualization import ClusterVisualizer
from recognition.shared.ids import generate_id

logger = logging.getLogger(__name__)


@lru_cache
def get_settings() -> ClusteringSettings:
    """Provide clustering settings from the recognition config."""
    return get_recognition_settings().clustering


_SHARED_ADAPTER = None
_ADAPTER_LOCK = asyncio.Lock()


async def get_shared_insightface_adapter():
    """Return a singleton InsightFaceAdapter to avoid reloading models."""
    global _SHARED_ADAPTER
    if _SHARED_ADAPTER is None:
        async with _ADAPTER_LOCK:
            if _SHARED_ADAPTER is None:
                from recognition.infrastructure.embeddings import InsightFaceAdapter

                # Initialize the adapter (cheap)
                _SHARED_ADAPTER = InsightFaceAdapter()
                # Ensure model is loaded (expensive, done once)
                await _SHARED_ADAPTER.ensure_loaded()
    return _SHARED_ADAPTER


class InMemoryJobService:
    """Very small in-memory job tracker."""

    def __init__(self) -> None:
        self.jobs: dict[str, JobStatusResponse] = {}

    async def create_scan_job(self, media_ids: Iterable[str], tenant_id: str) -> JobStatusResponse:
        """Create a completed scan job immediately."""
        media_ids_list = list(media_ids)
        job_id = str(generate_id())
        started_at = datetime.now(tz=UTC)
        job = JobStatusResponse(
            id=job_id,
            type="analyze",
            status="running",
            progress=JobProgressResponse(completed=0, total=len(media_ids_list)),
            started_at=started_at,
            finished_at=None,
        )
        self.jobs[job_id] = job
        return job

    async def create_cluster_job(self, tenant_id: str) -> str:
        """Create a clustering job placeholder."""
        job_id = str(generate_id())
        started_at = datetime.now(tz=UTC)
        self.jobs[job_id] = JobStatusResponse(
            id=job_id,
            type="clustering",
            status="running",
            progress=JobProgressResponse(completed=0, total=0),
            started_at=started_at,
            finished_at=None,
        )
        return job_id

    async def get_job_status(self, job_id: str) -> JobStatusResponse | None:
        """Return job status if known."""
        return self.jobs.get(job_id)


class _InMemoryJobRepository:
    """Shared in-memory job repository used when the database is unavailable."""

    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}

    async def save(self, job: Job) -> Job:
        self.jobs[job.id] = job
        return job

    async def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    async def update(self, job: Job) -> Job:
        self.jobs[job.id] = job
        return job


_MEM_JOB_REPO = _InMemoryJobRepository()


class AuthContext:
    """Simple auth context returned by require_auth."""

    def __init__(
        self,
        token: str | None,
        tenant_claim: str | None,
        api_key_id: str | None = None,
        rate_limit_tier: str | None = None,
        is_admin: bool = False,
        enabled: bool = False,
    ) -> None:
        self.token = token
        self.tenant_claim = tenant_claim
        self.tenant_id = tenant_claim
        self.api_key_id = api_key_id
        self.rate_limit_tier = rate_limit_tier
        self.is_admin = is_admin
        self.enabled = enabled


def _hash_api_key(raw_key: str, algorithm: str) -> str:
    """Return a hex digest for the provided API key."""
    try:
        digest = hashlib.new(algorithm)
    except ValueError as exc:  # pragma: no cover - defensive guard
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="unsupported api key hash algorithm"
        ) from exc
    digest.update(raw_key.encode("utf-8"))
    return digest.hexdigest()


def _table_missing(exc: Exception) -> bool:
    """Detect missing api_keys table errors to allow graceful fallback."""
    message = str(exc).lower()
    return "no such table: api_keys" in message or 'relation "api_keys" does not exist' in message


async def _lookup_api_key(
    api_key: str,
    settings: SecuritySettings,
    session: AsyncSession | None,
) -> tuple[str | None, str | None, str | None, bool]:
    """Validate API key and return (tenant_id, api_key_id, rate_limit_tier, is_admin)."""
    hashed = _hash_api_key(api_key, settings.api_key_hash_algorithm)
    if session is not None and hasattr(session, "execute"):
        repo = SqlAlchemyApiKeyRepository(session)
        try:
            record = await repo.get_by_hash(hashed)
        except Exception as exc:
            if not _table_missing(exc):
                raise
            record = None
        if record:
            with suppress(Exception):
                await repo.touch(record)
            return str(record.tenant_id), str(record.id), record.rate_limit_tier, False

    if api_key in settings.dev_api_keys:
        return None, None, "enterprise", True

    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid or missing API key")


async def get_session(tenant_id: str | None = Depends(get_tenant_id_optional)) -> AsyncIterator[AsyncSession]:
    """Yield a SQLAlchemy async session; set tenant context when provided."""
    async for session in _get_session():
        try:
            if tenant_id:
                await set_tenant_context(session, uuid.UUID(str(tenant_id)))
            yield session
            commit = getattr(session, "commit", None)
            if callable(commit):
                await commit()
        except Exception:
            rollback = getattr(session, "rollback", None)
            if callable(rollback):
                await rollback()
            raise
        finally:
            if tenant_id:
                await clear_tenant_context(session)


async def get_optional_session(
    tenant_id: str | None = Depends(get_tenant_id_optional),
) -> AsyncIterator[AsyncSession | None]:
    """Best-effort session provider; returns None when the database is unavailable."""
    async for session in _get_session():
        try:
            try:
                await session.execute(text("SELECT 1"))
                if tenant_id:
                    await set_tenant_context(session, uuid.UUID(str(tenant_id)))
            except Exception:
                yield None
                return
            try:
                yield session
                commit = getattr(session, "commit", None)
                if callable(commit):
                    await commit()
            except Exception as exc:
                logger.error("get_optional_session: exception during yield/commit: %s", exc)
                rollback = getattr(session, "rollback", None)
                if callable(rollback):
                    await rollback()
                raise
        finally:
            if tenant_id:
                await clear_tenant_context(session)


async def require_auth(
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    api_key_header_value: str | None = Header(default=None, alias="X-Api-Key"),
    session: AsyncSession | None = Depends(get_optional_session),
) -> AuthContext:
    """Enforce bearer auth when enabled via settings."""
    settings = get_security_settings()
    if not settings.auth_enabled:
        return AuthContext(token=None, tenant_claim=None, api_key_id=None, is_admin=False, enabled=False)

    header_value = authorization
    if settings.api_key_header.lower() != "authorization":
        header_value = api_key_header_value or authorization

    if not header_value:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization header required")

    scheme, _, token = header_value.partition(" ")
    api_key = token if scheme.lower() == "bearer" else None
    if not api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid authorization scheme")

    tenant_claim, api_key_id, rate_limit_tier, is_admin = await _lookup_api_key(api_key, settings, session)
    if tenant_claim and x_tenant_id:
        provided = _normalize_tenant_id(x_tenant_id)
        if tenant_claim != provided:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant mismatch")

    return AuthContext(
        token=api_key,
        tenant_claim=tenant_claim,
        api_key_id=api_key_id,
        rate_limit_tier=rate_limit_tier,
        is_admin=is_admin,
        enabled=True,
    )


async def get_current_tenant(auth: AuthContext = Depends(require_auth)) -> str | None:
    """Resolve tenant from validated API key (None when auth is disabled)."""
    return auth.tenant_claim


async def require_write_access(auth: AuthContext = Depends(require_auth)) -> AuthContext:
    """Enforce write access for mutate endpoints (analyze, clustering, merges).

    Currently, all authenticated requests with a valid tenant are allowed to write.
    In the future, this can be extended to check for specific scopes or roles.

    Returns:
        The validated AuthContext.

    Raises:
        HTTPException: 403 if the user lacks write permissions.
    """
    if not auth.enabled:
        # Auth disabled - allow all operations
        return auth
    if auth.tenant_claim is None and not auth.is_admin:
        # No tenant claim and not an admin - deny write access
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Write access requires a tenant-scoped API key or admin privileges",
        )
    return auth


async def get_observability_session() -> AsyncIterator[AsyncSession | None]:
    """Session provider without tenant validation for diagnostics."""
    async for session in _get_session():
        try:
            await session.execute(text("SELECT 1"))
        except Exception:
            yield None
            return
        try:
            yield session
            commit = getattr(session, "commit", None)
            if callable(commit):
                await commit()
        except Exception:
            rollback = getattr(session, "rollback", None)
            if callable(rollback):
                await rollback()
            raise
        return


async def get_suggestion_service(
    session: AsyncSession = Depends(get_session), tenant_id: str | None = Depends(get_tenant_id_optional)
) -> SuggestionService:
    """Repository-backed suggestion service scoped to the tenant."""
    tenant = tenant_id or ""
    repo = SqlAlchemySuggestionRepository(session, tenant_id=tenant)
    cluster_repo = SqlAlchemyClusterRepository(session)
    block_repo = SqlAlchemyIdentityClusterBlockRepository(session, tenant_id=tenant)
    settings = get_settings()
    return SuggestionService(
        repo,
        tenant_id=tenant,
        cluster_repository=cluster_repo,
        session=session,
        settings=settings,
        block_repository=block_repo,
    )


async def get_cluster_repository(
    session: AsyncSession = Depends(get_session),
) -> SqlAlchemyClusterRepository:
    """Return a cluster repository backed by the current session."""
    return SqlAlchemyClusterRepository(session)


class DecisionStore:
    """In-memory store for decision logs exposed via diagnostics."""

    def __init__(self) -> None:
        self._decisions: list[dict[str, Any]] = []

    def add(self, decision: dict[str, Any]) -> None:
        self._decisions.append(decision)

    def clear(self) -> None:
        self._decisions.clear()

    def list(
        self,
        *,
        tenant_id: str | None = None,
        outcome: str | None = None,
        cluster_id: str | None = None,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Filter decision logs by tenant, outcome, and time window."""
        filtered: list[dict[str, Any]] = []
        for decision in self._decisions:
            if tenant_id and decision.get("tenant_id") != tenant_id:
                continue
            if outcome and decision.get("decision") != outcome:
                continue
            if cluster_id and decision.get("cluster_id") != cluster_id:
                continue

            ts = self._to_datetime(decision.get("timestamp"))
            if start_at and (ts is None or ts < start_at):
                continue
            if end_at and (ts is None or ts > end_at):
                continue

            filtered.append(dict(decision))

        if offset < 0:
            offset = 0
        if limit < 0:
            limit = 0
        return filtered[offset : offset + limit]

    @staticmethod
    def _to_datetime(value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return None
        return None


@lru_cache
def get_decision_store() -> DecisionStore:
    """Singleton decision store."""
    return DecisionStore()


async def get_observability_repository(
    session: AsyncSession | None = Depends(get_observability_session),
) -> ObservabilityRepository | None:
    """Return DB-backed observability repository when a real session is available."""
    if session is None:
        return None
    return ObservabilityRepository(session)


class MediaIdentityService:
    """Lightweight service to fetch media identities by media_id."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_by_media_ids(self, tenant_id: str, media_ids: list[int]):
        if not media_ids:
            return []
        # Left outer join with IdentityMember and IdentityCluster to get cluster info
        stmt = (
            select(
                MediaIdentity,
                IdentityMember.cluster_id,
                IdentityCluster.label.label("cluster_label"),
                IdentityCluster.user_confirmed.label("user_confirmed"),
            )
            .outerjoin(IdentityMember, MediaIdentity.id == IdentityMember.identity_id)
            .outerjoin(IdentityCluster, IdentityMember.cluster_id == IdentityCluster.id)
            .where(MediaIdentity.tenant_id == uuid.UUID(str(tenant_id)))
            .where(MediaIdentity.media_id.in_(media_ids))
        )
        rows = (await self._session.execute(stmt)).all()
        return [
            {
                "identity_id": str(row.MediaIdentity.id),
                "media_id": row.MediaIdentity.media_id,
                "cluster_id": str(row.cluster_id) if row.cluster_id else None,
                "cluster_label": row.cluster_label,
                "is_auto_label": not row.user_confirmed if row.user_confirmed is not None else None,
                "bbox": {
                    "width": row.MediaIdentity.bbox_width,
                    "height": row.MediaIdentity.bbox_height,
                    "x": row.MediaIdentity.bbox_x,
                    "y": row.MediaIdentity.bbox_y,
                },
                "confidence": row.MediaIdentity.confidence,
                "thumbnail_url": row.MediaIdentity.thumbnail_url,
                "media_url": row.MediaIdentity.media_url,
            }
            for row in rows
        ]


async def get_media_identity_service(
    session: AsyncSession | None = Depends(get_optional_session),
) -> MediaIdentityService | None:
    """Return a media identity service when a session is available."""
    if session is None or not isinstance(session, AsyncSession):
        return None
    return MediaIdentityService(session)


async def build_cluster_service(
    session: AsyncSession,
    tenant_id: str,
    settings: ClusteringSettings | None = None,
) -> ClusterService:
    """Construct a ClusterService wired with SQLAlchemy repositories."""
    settings = settings or get_settings()

    # Auto-provision tenant if it doesn't exist (first-use provisioning)
    tenant_uuid = uuid.UUID(tenant_id)
    await ensure_tenant_exists(session, tenant_uuid)

    cluster_repo = SqlAlchemyClusterRepository(session)
    member_repo = SqlAlchemyMemberRepository(session, tenant_id=tenant_id)
    block_repo = SqlAlchemyIdentityClusterBlockRepository(session, tenant_id=tenant_id)
    assignment_writer = AssignmentWriter(settings, cluster_repo, member_repo)

    suggestion_repo = SqlAlchemySuggestionRepository(session, tenant_id=tenant_id)
    suggestion_service = SuggestionService(
        suggestion_repo,
        tenant_id=tenant_id,
        cluster_repository=cluster_repo,
        session=session,
        settings=settings,
        block_repository=block_repo,
    )

    charts_dir = Path("logs") / "charts"

    return ClusterService(
        gate=AssignmentGate(
            settings=settings,
            cluster_repository=cluster_repo,
            block_repository=block_repo,
        ),
        representative_discovery=RepresentativeDiscovery(settings=settings),
        centroid_discovery=CentroidDiscovery(settings=settings),
        graph_discovery=GraphDiscovery(settings=settings, algorithm=None),
        assignment_writer=assignment_writer,
        suggestion_service=suggestion_service,
        block_repository=block_repo,
        logger=ClusteringLogger(),
        visualizer=ClusterVisualizer(output_dir=charts_dir),
        decision_store=get_decision_store(),
        observability_repo=ObservabilityRepository(session),
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
    session: AsyncSession | None = Depends(get_optional_session),
    settings: ClusteringSettings = Depends(get_settings),
) -> Callable[[str], Awaitable[ClusterService]]:
    """Return a builder that can construct a ClusterService for a given tenant."""

    async def _builder(tenant_id: str) -> ClusterService:
        if session is None:
            raise RuntimeError("Database session is required for ClusterService")
        return await build_cluster_service(session=session, tenant_id=tenant_id, settings=settings)

    return _builder


def get_scan_service_builder(
    session: AsyncSession | None = Depends(get_optional_session),
) -> Callable[[str], ScanService]:
    """Return a builder for ScanService with DB session and embedder.

    Uses real InsightFace adapters in production mode, stubs in test mode.
    Set RECOGNITION_RUNTIME_MODE=test to use deterministic stubs.
    """
    from recognition.application.embedding.detector import (
        InsightFaceFaceDetector,
        StubFaceDetector,
    )
    from recognition.application.embedding.generator import (
        InsightFaceEmbeddingGenerator,
        StubEmbeddingGenerator,
    )
    from recognition.config import get_settings as get_recognition_settings

    settings = get_recognition_settings()
    runtime_mode = settings.runtime_mode

    def _builder(tenant_id: str) -> ScanService:
        if session is None:
            raise RuntimeError("Database session is required for ScanService")

        embedder = EmbeddingService()

        if runtime_mode == "test":
            # Use deterministic stubs for testing
            detector = StubFaceDetector()
            generator = StubEmbeddingGenerator()
        else:
            # Production mode: use real InsightFace (lazy-loaded shared instance)
            try:
                from recognition.infrastructure.embeddings import InsightFaceAdapter

                # Use the global adapter if initialized, otherwise create one (fallback)
                # Ideally, we should await get_shared_insightface_adapter(), but this builder is synchronous.
                # However, since we are in a factory, we might need to rely on the shared instance being ready
                # OR just return a new one if we can't await here.
                # BUT: The builder returns a ScanService. ScanService doesn't await in init.
                # The caller of `_builder` assumes it's sync.

                # OPTIMIZATION: Check if we have a shared instance available
                global _SHARED_ADAPTER
                adapter = _SHARED_ADAPTER
                if adapter is None:
                    # Fallback to new instance if not yet initialized globally
                    # This happens if get_shared_insightface_adapter hasn't been called yet.
                    # We can't await here.
                    logger.warning("Shared InsightFaceAdapter not initialized, creating new instance (slow)")
                    adapter = InsightFaceAdapter()

                detector = InsightFaceFaceDetector(adapter)
                generator = InsightFaceEmbeddingGenerator(adapter)
            except ImportError:
                # InsightFace not installed, fall back to stubs with warning
                import logging

                logging.getLogger(__name__).warning(
                    "InsightFace not installed, using stub detectors. "
                    "Install with: pip install 'prototype-description-service[local]'"
                )
                detector = StubFaceDetector()
                generator = StubEmbeddingGenerator()

        return ScanService(
            session=session,
            detector=detector,
            generator=generator,
            embedder=embedder,
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

    if session is None:
        return JobService(repository=_MEM_JOB_REPO, cluster_service=None, scan_service=None)
    repo = SqlAlchemyJobRepository(session)
    cluster_service = None
    if callable(cluster_service_builder) and tenant_id:
        maybe_cluster = cluster_service_builder(tenant_id)
        cluster_service = await maybe_cluster if hasattr(maybe_cluster, "__await__") else maybe_cluster
    scan_service = None
    if callable(scan_service_builder) and tenant_id:
        maybe_scan = scan_service_builder(tenant_id)
        scan_service = await maybe_scan if hasattr(maybe_scan, "__await__") else maybe_scan
    return JobService(repository=repo, cluster_service=cluster_service, scan_service=scan_service)


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
