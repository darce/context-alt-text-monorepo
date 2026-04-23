"""
Cluster management routes.
"""

from __future__ import annotations

import json
import logging
import time as _time
from datetime import UTC, datetime
from json import JSONDecodeError
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

import db.session as db_session_module
from db.models import Tenant
from db.models.identity import CurationReplayRecord
from db.settings import get_database_settings
from recognition.application.settings import ClusteringSettings
from recognition.application.suggestions.label_inference import infer_suggested_label
from recognition.application.tasks.clustering import run_background_surface_suggestions
from recognition.config import get_settings as get_recognition_settings
from recognition.config.security import get_security_settings
from recognition.domain.constraints import ConstraintSource, ConstraintType
from recognition.domain.job import JobType, SplitJobPayload
from recognition.domain.repositories import ClusterRepository
from recognition.domain.suggestion import SuggestionRefreshReason
from recognition.infrastructure.repositories import (
    SqlAlchemyConstraintRepository,
    SqlAlchemyIdentityClusterBlockRepository,
)
from recognition.interface_adapters.http.dependencies import (
    build_cluster_service,
    get_cluster_repository,
    get_cluster_service_builder,
    get_persisted_cluster_job_service,
    get_session,
    get_suggestion_refresh_service,
    get_suggestion_service,
    require_auth,
    require_write_access,
)
from recognition.interface_adapters.http.deps.clustering_circuit_breaker import (
    get_or_create_clustering_circuit_breaker,
)
from recognition.interface_adapters.http.deps.rate_limit import enforce_rate_limit
from recognition.interface_adapters.http.deps.tenant import get_authenticated_tenant_id
from recognition.interface_adapters.http.job_utils import (
    job_to_clustering_response as _job_to_clustering_response,
)
from recognition.interface_adapters.http.middleware.metrics import get_default_metrics
from recognition.interface_adapters.http.schemas.requests import (
    AssignOutlierRequest,
    ClusteringJobRequest,
    CreateClusterForIdentityRequest,
    MergeClusterRequest,
    PatchClusterRequest,
    PinRepresentativeRequest,
    ReassignIdentityRequest,
    RecoverOrphansRequest,
    RevertMergeClusterRequest,
    SplitClusterRequest,
    SplitTopologyCommandRequest,
)
from recognition.interface_adapters.http.schemas.responses import (
    AsyncSplitClusterResponse,
    ClusterDeltaResponse,
    ClusteringJobStatusResponse,
    ClusterMemberResponse,
    ClusterResponse,
    ClusterSnapshotClusterResponse,
    ClusterSnapshotMemberResponse,
    ClusterSnapshotResponse,
    CreateClusterForIdentityResponse,
    FaceBoxResponse,
    JobProgressResponse,
    OrphanRecoveryResponse,
    ReassignIdentityResponse,
    RepresentativeResponse,
    RevertMergeClusterResponse,
    SplitClusterResponse,
    SplitCommandCreatedCluster,
    SplitCommandMemberDelta,
    SplitTopologyCommandResponse,
)
from recognition.interface_adapters.http.validation import validate_entity_id, validate_label, validate_paging
from recognition.shared.db.dialect import is_postgres
from recognition.shared.ids import generate_id

_logger = logging.getLogger(__name__)

_INFERENCE_CAP = 20

# E15-3a-BR-21 Slice 2: admission fail-fast queries. Documented on the probe
# helper below. The defaults used for the default statement_timeout restore
# are pulled from db.settings (DB_STATEMENT_TIMEOUT) so this stays in sync
# with the global fault-isolation boundary.
_CLUSTERING_ADMISSION_PROBE_SQL = """
SELECT 1
FROM pg_locks l
JOIN pg_stat_activity a ON a.pid = l.pid
WHERE l.relation = 'tenants'::regclass
  AND l.granted = true
  AND a.state = 'idle in transaction'
  AND a.pid <> pg_backend_pid()
LIMIT 1
"""

# Postgres SQLSTATE for a canceled statement (statement_timeout hit or explicit
# pg_cancel_backend). We match by SQLSTATE rather than by asyncpg exception
# type to keep the branch driver-agnostic.
_QUERY_CANCELED_SQLSTATE = "57014"


def _is_query_canceled(exc: DBAPIError) -> bool:
    """Return True if the DBAPIError wraps a Postgres statement_timeout cancel."""
    orig = getattr(exc, "orig", None)
    if orig is None:
        return False
    sqlstate = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    if sqlstate == _QUERY_CANCELED_SQLSTATE:
        return True
    cause = getattr(orig, "__cause__", None)
    cause_sqlstate = getattr(cause, "sqlstate", None) or getattr(cause, "pgcode", None)
    return cause_sqlstate == _QUERY_CANCELED_SQLSTATE


def _raise_admission_unavailable(*, reason: str, retry_after_seconds: int, tenant_id: str) -> None:
    """Emit the BR-21-fast-fail log line and raise the canonical 503 response."""
    _logger.warning(
        "BR-21-fast-fail clustering admission reason=%s tenant_id=%s retry_after=%ss",
        reason,
        tenant_id,
        retry_after_seconds,
    )
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Clustering temporarily unavailable",
        headers={"Retry-After": str(retry_after_seconds)},
    )


async def _clustering_admission_probe(
    session: AsyncSession,
    *,
    tenant_id: str,
    retry_after_seconds: int,
) -> None:
    """Best-effort pg_locks pre-flight check.

    Returns None silently on non-Postgres backends (SQLite, FakeSession) and on
    any probe error so a broken probe never blocks legitimate traffic. When a
    row is found -- meaning another backend is ``idle in transaction`` while
    holding a lock on ``tenants`` -- raises the canonical 503 Retry-After.
    """
    if not is_postgres(session):
        return
    try:
        result = await session.execute(text(_CLUSTERING_ADMISSION_PROBE_SQL))
    except Exception:  # pragma: no cover - probe is best-effort
        _logger.debug("clustering admission probe failed", exc_info=True)
        return
    blocker = None
    try:
        blocker = result.scalar() if result is not None else None
    except Exception:  # pragma: no cover - probe is best-effort
        return
    if blocker is None:
        return
    _raise_admission_unavailable(
        reason="tenants_row_locked_by_idle_in_txn",
        retry_after_seconds=retry_after_seconds,
        tenant_id=tenant_id,
    )


async def _acquire_tenant_lock_fast_fail(
    session: AsyncSession,
    *,
    tenant_id: str,
    lock_timeout_ms: int,
    default_timeout: str,
    retry_after_seconds: int,
) -> None:
    """Run the tenants ``SELECT ... FOR UPDATE`` under a narrow statement_timeout.

    On non-Postgres backends the narrow SET LOCAL is skipped and the SELECT
    runs under whatever timeout the dep already applied. On Postgres, the
    caller's transaction temporarily lowers ``statement_timeout`` so a zombie
    idle-in-transaction row lock fails in ~``lock_timeout_ms`` (not 10 s) and
    is restored to ``default_timeout`` immediately after the SELECT so the
    subsequent active-job lookup and INSERT keep the default safety budget.
    """
    postgres = is_postgres(session)
    if postgres:
        await session.execute(text(f"SET LOCAL statement_timeout = '{int(lock_timeout_ms)}ms'"))
    try:
        await session.execute(select(Tenant.id).where(Tenant.id == tenant_id).with_for_update())
    except DBAPIError as exc:
        if _is_query_canceled(exc):
            _raise_admission_unavailable(
                reason="tenants_for_update_timeout",
                retry_after_seconds=retry_after_seconds,
                tenant_id=tenant_id,
            )
        raise
    finally:
        if postgres:
            try:
                await session.execute(text(f"SET LOCAL statement_timeout = '{default_timeout}'"))
            except Exception:  # pragma: no cover - restore is best-effort
                _logger.debug("SET LOCAL statement_timeout restore failed", exc_info=True)


router = APIRouter(tags=["clusters"], dependencies=[Depends(require_auth), Depends(enforce_rate_limit)])


async def _load_topology_replay(session, tenant_id: str, idempotency_key: str | None) -> dict | None:
    if not idempotency_key:
        return None

    tenant_uuid = UUID(tenant_id)
    result = await session.execute(
        select(CurationReplayRecord).where(
            CurationReplayRecord.tenant_id == tenant_uuid,
            CurationReplayRecord.idempotency_key == idempotency_key,
        )
    )
    record = result.scalar_one_or_none()

    if not isinstance(record, CurationReplayRecord):
        return None

    if not isinstance(record.machine_payload_json, str) or not record.machine_payload_json.strip():
        return None

    try:
        payload = json.loads(record.machine_payload_json)
    except JSONDecodeError:
        return None

    return payload if isinstance(payload, dict) else None


async def _store_topology_replay(session, tenant_id: str, idempotency_key: str | None, payload: dict) -> None:
    if not idempotency_key:
        return

    tenant_uuid = UUID(tenant_id)
    existing = await _load_topology_replay(session, tenant_id, idempotency_key)
    if existing is not None:
        return

    session.add(
        CurationReplayRecord(
            tenant_id=tenant_uuid,
            idempotency_key=idempotency_key,
            result_status="acknowledged",
            backend_version=0,
            machine_payload_json=json.dumps(payload, sort_keys=True),
        )
    )
    await session.flush()


async def _get_cluster_backend_version(cluster_repo, cluster_id: str) -> int:
    cluster = await cluster_repo.get_by_id(cluster_id)
    if cluster is None:
        return 0
    return int(getattr(cluster, "backend_version", 0) or 0)


async def _raise_if_cluster_stale(*, cluster_repo, cluster_id: str, expected_base_version: int) -> None:
    if expected_base_version <= 0:
        return

    backend_version = await _get_cluster_backend_version(cluster_repo, cluster_id)
    if backend_version <= expected_base_version:
        return

    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "conflict_code": "version_conflict",
            "backend_version": backend_version,
            "source_cluster_id": cluster_id,
            "machine_payload": {
                "entity_type": "cluster",
                "entity_key": cluster_id,
                "backend_version": backend_version,
            },
        },
    )


@router.post("/clustering/jobs", response_model=ClusteringJobStatusResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_clustering_job(
    request: ClusteringJobRequest,
    http_request: Request,
    auth=Depends(require_write_access),
    session=Depends(get_session),
    cluster_service_builder=Depends(get_cluster_service_builder),
    job_service=Depends(get_persisted_cluster_job_service),
) -> ClusteringJobStatusResponse:
    """Trigger clustering for unclustered identities."""
    _logger.info("Clustering request: tenant_id=%s, mode=%s", request.tenant_id, request.mode)
    # E15-3a-BR-21 Slice 1: admission-latency floor. Time the full handler so
    # S2's fail-fast claim (<1 s backend-measured) is directly observable in
    # `clustering_admission_latency_ms` once S2 lands.
    _admission_started_at = _time.perf_counter()
    _admission_status: int = status.HTTP_202_ACCEPTED
    try:
        if auth and auth.tenant_claim and auth.tenant_claim != request.tenant_id:
            _admission_status = status.HTTP_403_FORBIDDEN
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant mismatch")

        cluster_service = await cluster_service_builder(request.tenant_id)
        if request.mode == "sync":
            try:
                result = await cluster_service.cluster_unclustered_identities(request.tenant_id)
            except Exception as exc:
                _admission_status = status.HTTP_500_INTERNAL_SERVER_ERROR
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
            finished_at = getattr(result, "finished_at", None)
            completed = getattr(result, "completed", 0)
            total = getattr(result, "total", 0)
            clusters_created = getattr(result, "clusters_created", 0)
            job_id = getattr(result, "job_id", str(generate_id()))
            return ClusteringJobStatusResponse(
                id=str(job_id),
                type=JobType.CLUSTERING.value,
                status="completed",
                progress=JobProgressResponse(completed=completed, total=total),
                started_at=result.started_at if hasattr(result, "started_at") else datetime.now(tz=UTC),
                finished_at=finished_at,
                clusters_created=clusters_created,
                total_identities_clustered=completed,
            )

        # Async mode: create a pending job for background worker to process.
        # Reuse an existing pending/running clustering job for the tenant to avoid
        # duplicate expensive work from repeated clicks or repeated UI effects.
        #
        # E15-3a-BR-21 Slice 2: admission fail-fast. A pg_locks probe is cheap
        # (~ms) and returns a 503 ahead of any lock wait when a zombie idle-in-
        # transaction session is holding the tenants row lock. The SELECT FOR
        # UPDATE below then runs under a narrow statement_timeout so a missed
        # probe still converts into a <1 s 503 instead of the 10 s cliff.
        _db_settings = get_database_settings()
        # E15-3a-BR-21 Slice 3: clustering-dedicated circuit breaker fails fast
        # ahead of any DB work once a run of QueryCanceledError confirms a
        # zombie holder on tenants. PLAN-09: the clustering breaker is the sole
        # fail-fast surface here, not the SLR-3 session-dependency breaker.
        _breaker = get_or_create_clustering_circuit_breaker(http_request.app)
        if not _breaker.allow_request():
            _admission_status = status.HTTP_503_SERVICE_UNAVAILABLE
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error": "clustering_breaker_open",
                    "reason": "clustering admission temporarily unavailable",
                    "tenant_id": request.tenant_id,
                },
                headers={"Retry-After": str(_db_settings.clustering_admission_retry_after_seconds)},
            )
        await _clustering_admission_probe(
            session,
            tenant_id=request.tenant_id,
            retry_after_seconds=_db_settings.clustering_admission_retry_after_seconds,
        )
        try:
            await _acquire_tenant_lock_fast_fail(
                session,
                tenant_id=request.tenant_id,
                lock_timeout_ms=_db_settings.clustering_tenant_lock_timeout_ms,
                default_timeout=_db_settings.statement_timeout,
                retry_after_seconds=_db_settings.clustering_admission_retry_after_seconds,
            )
        except HTTPException as exc:
            # Narrow: a 503 from the lock helper is the QueryCanceledError path
            # (SQLSTATE 57014). Count only that signal toward breaker failures.
            if exc.status_code == status.HTTP_503_SERVICE_UNAVAILABLE:
                _breaker.record_failure()
            raise
        existing_job = await job_service.get_active_clustering_job_for_tenant(request.tenant_id)
        if existing_job is not None:
            _breaker.record_success()
            return _job_to_clustering_response(existing_job)

        # The generic /recognition/jobs/{id}/stream endpoint handles all job types.
        job = await job_service.create_job(JobType.CLUSTERING, tenant_id=request.tenant_id)
        # Do NOT start the job - leave it in pending state for worker to pick up
        _breaker.record_success()
        return _job_to_clustering_response(job)
    except HTTPException as exc:
        _admission_status = exc.status_code
        raise
    except Exception:
        _admission_status = status.HTTP_500_INTERNAL_SERVER_ERROR
        raise
    finally:
        _admission_elapsed_ms = (_time.perf_counter() - _admission_started_at) * 1000
        try:
            get_default_metrics().clustering_admission_latency_ms.labels(status=str(_admission_status)).observe(
                _admission_elapsed_ms
            )
        except Exception:  # pragma: no cover - metrics must never break the handler
            _logger.debug("clustering_admission_latency_ms observation failed", exc_info=True)


@router.post("/clusters/recover-orphans", response_model=OrphanRecoveryResponse)
async def recover_orphan_identities(
    request: RecoverOrphansRequest,
    auth=Depends(require_write_access),
    session=Depends(get_session),
    cluster_service_builder=Depends(get_cluster_service_builder),
) -> OrphanRecoveryResponse:
    """Re-cluster any orphaned identities for a tenant."""
    if auth and auth.tenant_claim and auth.tenant_claim != request.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant mismatch")

    cluster_service = await cluster_service_builder(request.tenant_id)
    try:
        result = await cluster_service.cluster_unclustered_identities(request.tenant_id)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    return OrphanRecoveryResponse(
        orphans_found=int(getattr(result, "total", 0) or 0),
        recovered=int(getattr(result, "accepted", 0) or 0),
        suggested=int(getattr(result, "suggested", 0) or 0),
        rejected=int(getattr(result, "rejected", 0) or 0),
        clusters_created=int(getattr(result, "clusters_created", 0) or 0),
    )


@router.get("/clusters", response_model=list[ClusterResponse])
async def list_clusters(
    tenant_id: str = Depends(get_authenticated_tenant_id),
    limit: int = Query(50),
    offset: int = Query(0),
    include_outliers: bool = Query(False),
    labeled_only: bool = Query(False),
    search: str | None = Query(None),
    cluster_service_builder=Depends(get_cluster_service_builder),
) -> list[ClusterResponse]:
    """List clusters with paging."""
    settings = get_security_settings()
    validate_paging(limit, offset, settings.max_page_size)
    cluster_service = await cluster_service_builder(tenant_id)
    return await cluster_service.list_clusters(
        tenant_id,
        limit=limit,
        offset=offset,
        include_outliers=include_outliers,
        labeled_only=labeled_only,
        search=search,
    )


def _build_cluster_responses(
    clusters: list,
) -> list[ClusterSnapshotClusterResponse]:
    """Build cluster snapshot responses from domain cluster objects."""
    responses: list[ClusterSnapshotClusterResponse] = []
    for cluster in clusters:
        curation_state = "dismissed" if cluster.dismissed_at else ("confirmed" if cluster.user_confirmed else "active")

        # Get representative thumb path
        representative_thumb_path = None
        representative_id = None
        is_pinned = False
        if cluster.representatives and len(cluster.representatives) > 0:
            # Sort by id for stable fallback if no user-selected representative exists
            # ( mitigates RSWR-IMPL-007: non-deterministic collection ordering )
            reps = sorted(cluster.representatives, key=lambda r: str(r.id))
            rep = next(
                (candidate for candidate in reps if candidate.is_user_selected),
                reps[0],
            )
            if rep.identity_id:
                representative_id = str(rep.identity_id)
                is_pinned = bool(rep.is_user_selected)
                # Format: acx://cluster/{cluster_uuid}/media/{media_id}
                representative_thumb_path = f"acx://cluster/{cluster.id}/media/{rep.media_id}"

        responses.append(
            ClusterSnapshotClusterResponse(
                cluster_uuid=str(cluster.id),
                label=cluster.label,
                curation_state=curation_state,
                is_user_confirmed=cluster.user_confirmed,
                identity_count=cluster.identity_count,
                representative_thumb_path=representative_thumb_path,
                representative_id=representative_id,
                is_pinned=is_pinned,
            )
        )
    return responses


def _build_member_responses(
    members_with_identities: list,
) -> list[ClusterSnapshotMemberResponse]:
    """Build member snapshot responses from member/identity pairs."""
    responses: list[ClusterSnapshotMemberResponse] = []
    for member, identity in members_with_identities:
        # Note: bbox coordinates may be None for some detections; default to 0
        bbox_x = identity.bbox_x or 0
        bbox_y = identity.bbox_y or 0

        # Note: MediaIdentity doesn't store full image dimensions.
        # Consumer resolves dimensions from WordPress media metadata (wp_postmeta).
        image_width = 0
        image_height = 0

        responses.append(
            ClusterSnapshotMemberResponse(
                identity_uuid=identity.id,
                cluster_uuid=member.cluster_id,
                attachment_id=int(identity.media_id),
                bbox=FaceBoxResponse(
                    x=bbox_x,
                    y=bbox_y,
                    width=identity.bbox_width,
                    height=identity.bbox_height,
                ),
                image_width=image_width,
                image_height=image_height,
                thumb_path=f"acx://identity/{identity.id}/attachment/{identity.media_id}",
                similarity=member.similarity,
            )
        )
    return responses


async def _enrich_with_suggested_labels(
    cluster_responses: list[ClusterSnapshotClusterResponse],
    tenant_id: str,
    session: AsyncSession,
    repo: ClusterRepository,
    settings: ClusteringSettings,
) -> None:
    """Best-effort label inference for unlabeled clusters, bounded to top N."""
    unlabeled = [cr for cr in cluster_responses if cr.label is None and not cr.is_user_confirmed]
    unlabeled.sort(key=lambda cr: cr.identity_count, reverse=True)

    for cluster_resp in unlabeled[:_INFERENCE_CAP]:
        try:
            inferred = await infer_suggested_label(
                tenant_id=tenant_id,
                cluster_id=cluster_resp.cluster_uuid,
                session=session,
                cluster_repository=repo,
                settings=settings,
            )
            if inferred:
                cluster_resp.suggested_label = inferred.label
                cluster_resp.suggested_label_source = inferred.source.value
                cluster_resp.suggested_label_confidence = inferred.confidence
                cluster_resp.suggested_target_cluster_id = inferred.target_cluster_id
        except Exception:
            _logger.warning(
                "suggested_label inference failed for cluster %s (tenant %s); skipping enrichment",
                cluster_resp.cluster_uuid,
                tenant_id,
                exc_info=True,
            )


@router.get("/tenants/{tenant_uuid}/clusters/snapshot", response_model=ClusterSnapshotResponse)
async def get_tenant_cluster_snapshot(
    tenant_uuid: str,
    auth=Depends(require_auth),
    repo=Depends(get_cluster_repository),
    job_service=Depends(get_persisted_cluster_job_service),
    session=Depends(get_session),
) -> ClusterSnapshotResponse:
    """Get complete cluster snapshot for WordPress plugin projection.

    Returns all clusters and members for a tenant in a single response,
    formatted per contracts/cluster-snapshot-api.md.

    Note: Path param is ``tenant_uuid`` (not ``tenant_id``) to avoid a FastAPI
    collision with ``get_tenant_id_optional`` which declares ``tenant_id`` as
    ``Query`` in the transitive dep chain (get_cluster_repository -> get_session
    -> get_tenant_id_optional). See rule 13 in backend-python-guidelines.
    """
    tenant_id = tenant_uuid  # canonical internal name

    # Verify auth if tenant claim exists
    if auth and auth.tenant_claim and auth.tenant_claim != tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant mismatch")

    # Get snapshot data
    clusters, members_with_identities, snapshot_version, snapshot_generation_id = await repo.get_snapshot(
        tenant_id,
        stamp_export=True,
    )
    latest_clustering_job = await job_service.get_latest_completed_clustering_job_for_tenant(tenant_id)

    if not clusters and not members_with_identities:
        # Return 404 if tenant has no clusters (unknown tenant or empty tenant)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No clusters found for tenant")

    # Build responses
    cluster_responses = _build_cluster_responses(clusters)
    clustering_settings = get_recognition_settings().clustering
    await _enrich_with_suggested_labels(cluster_responses, tenant_id, session, repo, clustering_settings)
    member_responses = _build_member_responses(members_with_identities)

    return ClusterSnapshotResponse(
        tenant_id=tenant_uuid,
        snapshot_version=snapshot_version,
        snapshot_generation_id=snapshot_generation_id,
        source_job_id=latest_clustering_job.id if latest_clustering_job is not None else None,
        generated_at=datetime.now(tz=UTC),
        clusters=cluster_responses,
        members=member_responses,
    )


@router.get("/tenants/{tenant_uuid}/clusters/targeted-snapshot", response_model=ClusterSnapshotResponse)
async def get_tenant_targeted_cluster_snapshot(
    tenant_uuid: str,
    cluster_ids: list[str] = Query(default_factory=list),
    auth=Depends(require_auth),
    repo=Depends(get_cluster_repository),
    job_service=Depends(get_persisted_cluster_job_service),
) -> ClusterSnapshotResponse:
    """Get a targeted cluster snapshot for a subset of cluster ids."""
    tenant_id = tenant_uuid

    if auth and auth.tenant_claim and auth.tenant_claim != tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant mismatch")

    normalized_cluster_ids = [cluster_id.strip() for cluster_id in cluster_ids if cluster_id.strip()]
    if not normalized_cluster_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="cluster_ids required")

    clusters = await repo.get_clusters_by_ids(tenant_id, normalized_cluster_ids)
    members_with_identities = await repo.get_members_by_cluster_ids(tenant_id, normalized_cluster_ids)
    snapshot_version = await repo.get_snapshot_version(tenant_id)
    latest_clustering_job = await job_service.get_latest_completed_clustering_job_for_tenant(tenant_id)

    if not clusters and not members_with_identities:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No clusters found for requested ids")

    return ClusterSnapshotResponse(
        tenant_id=tenant_uuid,
        snapshot_version=snapshot_version,
        source_job_id=latest_clustering_job.id if latest_clustering_job is not None else None,
        generated_at=datetime.now(tz=UTC),
        clusters=_build_cluster_responses(clusters),
        members=_build_member_responses(members_with_identities),
    )


@router.get("/tenants/{tenant_uuid}/clusters/delta", response_model=ClusterDeltaResponse)
async def get_tenant_cluster_delta(
    tenant_uuid: str,
    since_version: int = Query(..., ge=0),
    auth=Depends(require_auth),
    repo: ClusterRepository = Depends(get_cluster_repository),
    session=Depends(get_session),
) -> ClusterDeltaResponse:
    """Get version-filtered cluster updates for incremental projection sync."""
    tenant_id = tenant_uuid

    if auth and auth.tenant_claim and auth.tenant_claim != tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant mismatch")

    clusters, members_with_identities, snapshot_version = await repo.get_delta(tenant_id, since_version=since_version)

    if snapshot_version <= 0 and not clusters and not members_with_identities:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No clusters found for tenant")

    cluster_responses = _build_cluster_responses(clusters)
    clustering_settings = get_recognition_settings().clustering
    await _enrich_with_suggested_labels(cluster_responses, tenant_id, session, repo, clustering_settings)

    return ClusterDeltaResponse(
        tenant_id=tenant_uuid,
        snapshot_version=snapshot_version,
        generated_at=datetime.now(tz=UTC),
        clusters=cluster_responses,
        members=_build_member_responses(members_with_identities),
    )


@router.get("/clusters/top-unlabeled", response_model=list[ClusterResponse])
async def get_top_unlabeled_clusters(
    tenant_id: str = Depends(get_authenticated_tenant_id),
    limit: int = Query(10),
    min_identity_count: int = Query(2, ge=1, description="Minimum identity count (default 2 to skip singletons)"),
    repo=Depends(get_cluster_repository),
    session=Depends(get_session),
) -> list[ClusterResponse]:
    """Fetch top unlabeled clusters by member count for bootstrapping suggestions.

    Includes cluster representatives with face thumbnails for display in the
    suggestion panel.
    """
    clusters = await repo.get_top_unlabeled(
        tenant_id,
        limit=limit,
        min_identity_count=min_identity_count,
    )
    allowed_sources = {"identity", "roster", "similar_cluster", "none"}

    responses: list[ClusterResponse] = []
    clustering_settings = get_recognition_settings().clustering
    for c in clusters:
        suggested_label = getattr(c, "suggested_label", None)

        raw_source = getattr(c, "suggested_label_source", None)
        if hasattr(raw_source, "value"):
            raw_source = raw_source.value
        suggested_label_source = raw_source if isinstance(raw_source, str) and raw_source in allowed_sources else None

        raw_confidence = getattr(c, "suggested_label_confidence", None)
        try:
            suggested_label_confidence = float(raw_confidence) if raw_confidence is not None else None
        except (TypeError, ValueError):
            suggested_label_confidence = None
        raw_target_cluster_id = getattr(c, "suggested_target_cluster_id", None)
        suggested_target_cluster_id = str(raw_target_cluster_id) if raw_target_cluster_id else None

        if not suggested_label and not c.user_confirmed:
            try:
                inferred = await infer_suggested_label(
                    tenant_id=tenant_id,
                    cluster_id=str(c.id),
                    session=session,
                    cluster_repository=repo,
                    settings=clustering_settings,
                )
                if inferred:
                    suggested_label = inferred.label
                    suggested_label_source = inferred.source.value if inferred.source else None
                    suggested_label_confidence = inferred.confidence
                    suggested_target_cluster_id = inferred.target_cluster_id
            except Exception as exc:  # pragma: no cover - best-effort enrichment
                _logger.debug("top-unlabeled label inference failed cluster_id=%s err=%s", c.id, exc)

        responses.append(
            ClusterResponse(
                id=str(c.id),
                tenant_id=tenant_id,
                label=c.label,
                is_labeled=c.is_labeled,
                is_auto_label=c.is_auto_label,
                identity_count=c.identity_count,
                user_confirmed=c.user_confirmed,
                representatives=[
                    RepresentativeResponse(
                        id=str(rep.id),
                        media_id=rep.media_id or 0,
                        thumb_url=None,
                        media_url=rep.media_url,
                        bbox=(
                            FaceBoxResponse(
                                x=int(rep.bbox_x),
                                y=int(rep.bbox_y),
                                width=int(rep.bbox_width),
                                height=int(rep.bbox_height),
                            )
                            if (
                                rep.bbox_x is not None
                                and rep.bbox_y is not None
                                and rep.bbox_width is not None
                                and rep.bbox_height is not None
                            )
                            else None
                        ),
                        is_pinned=rep.is_user_selected,
                    )
                    for rep in (c.representatives or [])
                ],
                suggested_label=suggested_label,
                suggested_label_source=suggested_label_source,
                suggested_label_confidence=suggested_label_confidence,
                suggested_target_cluster_id=suggested_target_cluster_id,
            )
        )

    return responses


@router.post("/clusters/{cluster_id}/dismiss", status_code=204)
async def dismiss_cluster(
    cluster_id: str,
    repo=Depends(get_cluster_repository),
    auth=Depends(require_write_access),
) -> Response:
    """Dismiss a cluster from the naming queue so the next cluster surfaces."""
    validate_entity_id(cluster_id, field_name="cluster_id")
    dismissed = await repo.dismiss_cluster(cluster_id)
    if not dismissed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cluster not found or already dismissed")
    return Response(status_code=204)


@router.delete("/clusters/{cluster_id}/dismiss", status_code=204)
async def undismiss_cluster(
    cluster_id: str,
    repo=Depends(get_cluster_repository),
    auth=Depends(require_write_access),
) -> Response:
    """Undo dismissal so the cluster reappears in the naming queue."""
    validate_entity_id(cluster_id, field_name="cluster_id")
    undismissed = await repo.undismiss_cluster(cluster_id)
    if not undismissed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cluster not found or not dismissed")
    return Response(status_code=204)


@router.get("/clusters/{cluster_id}/members", response_model=list[ClusterMemberResponse])
async def list_cluster_members(
    cluster_id: str,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    cluster_service_builder=Depends(get_cluster_service_builder),
) -> list[ClusterMemberResponse]:
    """List all identities in a cluster with membership data.

    Returns identity details combined with membership similarity scores,
    formatted for the frontend ClusterReviewPanel.
    """
    validate_entity_id(cluster_id, field_name="cluster_id")
    cluster_service = await cluster_service_builder(tenant_id)
    cluster_repo = cluster_service.cluster_repository

    # Get identities with their membership similarity in a single query
    members_with_similarity = await cluster_repo.get_member_identities_with_similarity(cluster_id)

    return [
        ClusterMemberResponse(
            identity_id=str(identity.id),
            media_id=int(identity.media_id),
            similarity=similarity,
            confidence=float(identity.confidence),
            bbox=FaceBoxResponse(
                x=int(identity.bbox_x),
                y=int(identity.bbox_y),
                width=int(identity.bbox_width),
                height=int(identity.bbox_height),
            ),
            media_url=identity.media_url,
        )
        for identity, similarity in members_with_similarity
    ]


@router.patch("/clusters/{cluster_id}", response_model=ClusterResponse)
async def update_cluster(
    cluster_id: str,
    request: PatchClusterRequest,
    background_tasks: BackgroundTasks,
    auth=Depends(require_write_access),
    session=Depends(get_session),
    cluster_service_builder=Depends(get_cluster_service_builder),
) -> ClusterResponse:
    """Update cluster label."""
    import time as _time

    _t_start = _time.perf_counter()

    label = validate_label(request.label)
    validate_entity_id(cluster_id, field_name="cluster_id")
    if auth and auth.tenant_claim and auth.tenant_claim != request.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant mismatch")

    cluster_service = await cluster_service_builder(request.tenant_id)
    cluster_repo = cluster_service.assignment_writer.cluster_repository
    old_cluster = await cluster_repo.get_by_id(cluster_id)
    was_user_confirmed = old_cluster.user_confirmed if old_cluster else False

    cluster = await cluster_service.update_cluster(
        cluster_id,
        request.tenant_id,
        label=label,
        surface_suggestions=False,
    )
    if not cluster:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cluster not found")

    # Commit before returning the response so that any client-side refetch
    # (triggered by invalidateQueries in onSuccess) sees the committed state.
    # Without this, the commit runs in get_session() teardown which executes
    # AFTER the response is sent, creating a race where refetches can read
    # stale pre-commit data — causing intermittent label revert to UUID.
    await session.commit()

    _t_update_done = _time.perf_counter()
    _logger.info(
        "PATCH /clusters/%s: update completed in %.3fs, label='%s' was_user_confirmed=%s",
        cluster_id,
        _t_update_done - _t_start,
        label,
        was_user_confirmed,
    )

    if label and not was_user_confirmed:
        _logger.info(
            "PATCH /clusters/%s: scheduling background suggestion surfacing for label='%s'",
            cluster_id,
            label,
        )
        background_tasks.add_task(
            run_background_surface_suggestions,
            request.tenant_id,
            cluster_id,
            label,  # Pass label directly (optimistic update pattern)
            session_factory=db_session_module.async_session_factory,
            cluster_service_builder=build_cluster_service,
        )

    _t_response = _time.perf_counter()
    _logger.info(
        "PATCH /clusters/%s: returning response in %.3fs total",
        cluster_id,
        _t_response - _t_start,
    )
    return cluster


@router.post("/clusters/create-for-identity", response_model=CreateClusterForIdentityResponse)
async def create_cluster_for_identity(
    request: CreateClusterForIdentityRequest,
    auth=Depends(require_write_access),
    session=Depends(get_session),
    cluster_service_builder=Depends(get_cluster_service_builder),
) -> CreateClusterForIdentityResponse:
    """Create a new labeled cluster for a single identity."""
    validate_entity_id(request.identity_id, field_name="identity_id")
    label = validate_label(request.label)
    cached_response = await _load_topology_replay(session, request.tenant_id, request.idempotency_key)
    if cached_response is not None:
        return CreateClusterForIdentityResponse.model_validate(cached_response)
    if auth and auth.tenant_claim and auth.tenant_claim != request.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant mismatch")

    cluster_service = await cluster_service_builder(request.tenant_id)
    cluster_repo = cluster_service.assignment_writer.cluster_repository
    if request.desired_cluster_id:
        await _raise_if_cluster_stale(
            cluster_repo=cluster_repo,
            cluster_id=request.desired_cluster_id,
            expected_base_version=request.expected_base_version,
        )
    try:
        cluster = await cluster_service.create_cluster_for_identity(
            identity_id=request.identity_id,
            label=label,
            tenant_id=request.tenant_id,
            desired_cluster_id=request.desired_cluster_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    if not cluster or not cluster.id:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Cluster creation failed")

    # Commit before response so client refetches see committed state (see PATCH handler comment).
    response_obj = CreateClusterForIdentityResponse(
        cluster_id=cluster.id,
        label=cluster.label or label,
        identity_id=request.identity_id,
        message="Cluster created",
        backend_version=await _get_cluster_backend_version(cluster_repo, cluster.id),
    )
    await _store_topology_replay(session, request.tenant_id, request.idempotency_key, response_obj.model_dump())
    await session.commit()

    return response_obj


@router.post("/clusters/{cluster_id}/merge", response_model=ClusterResponse)
async def merge_cluster(
    cluster_id: str,
    request: MergeClusterRequest,
    background_tasks: BackgroundTasks,
    auth=Depends(require_write_access),
    session=Depends(get_session),
    cluster_service_builder=Depends(get_cluster_service_builder),
    job_service=Depends(get_persisted_cluster_job_service),
) -> ClusterResponse:
    """Merge cluster into target (by label)."""
    validate_entity_id(cluster_id, field_name="cluster_id")
    validate_entity_id(request.target_cluster_id, field_name="target_cluster_id")
    cached_response = await _load_topology_replay(session, request.tenant_id, request.idempotency_key)
    if cached_response is not None:
        return ClusterResponse.model_validate(cached_response)
    if auth and auth.tenant_claim and auth.tenant_claim != request.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant mismatch")

    cluster_service = await cluster_service_builder(request.tenant_id)
    cluster_repo = cluster_service.assignment_writer.cluster_repository
    await _raise_if_cluster_stale(
        cluster_repo=cluster_repo,
        cluster_id=cluster_id,
        expected_base_version=request.expected_base_version,
    )
    cluster = await cluster_service.merge_cluster(
        source_cluster_id=cluster_id,
        tenant_id=request.tenant_id,
        target_cluster_id=request.target_cluster_id,
        target_label=request.target_label,
        defer_recompute=True,
        moved_by_merge_id=str(generate_id()),
    )
    if not cluster:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cluster not found")

    # Queue curation job for deferred work (replaces background tasks).
    # Skip if source == target (merge becomes a metadata update and should not trigger delete).
    if cluster_id.lower() != request.target_cluster_id.lower():
        await job_service.queue_curation_followup(
            tenant_id=request.tenant_id,
            cluster_ids=[request.target_cluster_id],
            source_cluster_id=cluster_id,
        )

    # Commit before response so client refetches see committed state (see PATCH handler comment).
    response_obj = ClusterResponse.model_validate(cluster)
    response_obj.backend_version = await _get_cluster_backend_version(cluster_repo, request.target_cluster_id)
    await _store_topology_replay(session, request.tenant_id, request.idempotency_key, response_obj.model_dump())
    await session.commit()

    return response_obj


@router.post("/clusters/{cluster_id}/split", response_model=SplitClusterResponse | AsyncSplitClusterResponse)
async def split_cluster(
    cluster_id: str,
    request: SplitClusterRequest,
    response: Response,
    auth=Depends(require_write_access),
    session=Depends(get_session),
    cluster_service_builder=Depends(get_cluster_service_builder),
    suggestion_refresh_service=Depends(get_suggestion_refresh_service),
    job_service=Depends(get_persisted_cluster_job_service),
) -> SplitClusterResponse | AsyncSplitClusterResponse:
    """
    Split a cluster using hierarchical clustering.

    If n_clusters=0 (default), automatically determines the optimal split
    based on face similarity. If n_clusters>=2, forces exactly that many groups.
    The largest group stays in the original cluster; others become new clusters.

    If mode="async", the split is queued and returns 202 Accepted with a job ID.
    """
    validate_entity_id(cluster_id, field_name="cluster_id")
    cached_response = await _load_topology_replay(session, request.tenant_id, request.idempotency_key)
    if cached_response is not None:
        if "job_id" in cached_response:
            return AsyncSplitClusterResponse.model_validate(cached_response)
        return SplitClusterResponse.model_validate(cached_response)
    if auth and auth.tenant_claim and auth.tenant_claim != request.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant mismatch")

    if request.mode == "async":
        if not hasattr(job_service, "queue_split"):
            job_service = await get_persisted_cluster_job_service(
                session=session,
                tenant_id=request.tenant_id,
                cluster_service_builder=cluster_service_builder,
            )
        payload = SplitJobPayload(
            cluster_id=cluster_id,
            n_clusters=request.n_clusters,
            anchor_identity_id=request.anchor_identity_id,
            split_mode=request.split_mode,
        )
        job = await job_service.queue_split(tenant_id=request.tenant_id, payload=payload)
        response.status_code = status.HTTP_202_ACCEPTED
        response_obj = AsyncSplitClusterResponse(
            job_id=job.id,
            status=job.status.value,
            message=f"Split operation queued for cluster {cluster_id[:8]}",
        )
        await _store_topology_replay(session, request.tenant_id, request.idempotency_key, response_obj.model_dump())
        await session.commit()
        return response_obj

    if getattr(suggestion_refresh_service, "tenant_id", None) != request.tenant_id:
        suggestion_refresh_service = await get_suggestion_refresh_service(
            session=session,
            tenant_id=request.tenant_id,
        )

    cluster_service = await cluster_service_builder(request.tenant_id)
    new_ids, counts = await cluster_service.split_cluster(
        cluster_id,
        n_clusters=request.n_clusters,
        anchor_identity_id=request.anchor_identity_id,
        split_mode=request.split_mode,
        recompute=False,
    )
    if new_ids:
        await job_service.queue_curation_followup(
            tenant_id=request.tenant_id,
            cluster_ids=[cluster_id, *new_ids],
        )

    # Build response with both new list format and legacy single-cluster fields
    response_obj = SplitClusterResponse(
        new_cluster_ids=new_ids,
        moved_counts=counts,
        # Legacy fields: use first new cluster if any
        new_cluster_id=new_ids[0] if new_ids else None,
        moved_count=counts[0] if counts else 0,
    )

    # Refresh suggestions for affected clusters
    for cid in [cluster_id, *new_ids]:
        await suggestion_refresh_service.refresh_for_cluster(cid)

    # Commit before response so client refetches see committed state (see PATCH handler comment).
    await _store_topology_replay(session, request.tenant_id, request.idempotency_key, response_obj.model_dump())
    await session.commit()

    return response_obj


@router.post("/topology-commands/split", response_model=SplitTopologyCommandResponse)
async def split_topology_command(
    request: SplitTopologyCommandRequest,
    auth=Depends(require_write_access),
    session=Depends(get_session),
    cluster_service_builder=Depends(get_cluster_service_builder),
    cluster_repo=Depends(get_cluster_repository),
) -> SplitTopologyCommandResponse:
    """Execute a split through the topology-command plane."""
    validate_entity_id(request.cluster_id, field_name="cluster_id")
    cached_response = await _load_topology_replay(session, request.tenant_id, request.idempotency_key)
    if cached_response is not None:
        return SplitTopologyCommandResponse.model_validate(cached_response)
    if auth and auth.tenant_claim and auth.tenant_claim != request.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant mismatch")

    source_cluster = await cluster_repo.get_by_id(request.cluster_id)
    if source_cluster is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cluster not found")

    source_tenant_id = getattr(source_cluster, "tenant_id", None)
    if source_tenant_id and str(source_tenant_id) != request.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cluster not found")

    backend_version = int(getattr(source_cluster, "backend_version", 0) or 0)
    if request.expected_base_version > 0 and backend_version > request.expected_base_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "conflict_code": "version_conflict",
                "backend_version": backend_version,
                "source_cluster_id": request.cluster_id,
                "machine_payload": {
                    "entity_type": "cluster",
                    "entity_key": request.cluster_id,
                    "backend_version": backend_version,
                },
            },
        )

    cluster_service = await cluster_service_builder(request.tenant_id)
    new_ids, counts = await cluster_service.split_cluster(
        request.cluster_id,
        n_clusters=request.n_clusters,
        anchor_identity_id=request.anchor_identity_id,
        split_mode=request.split_mode,
        desired_cluster_ids=request.desired_cluster_ids,
        recompute=False,
    )

    # Ensure the snapshot read sees the split writes before deriving response lineage.
    await session.flush()

    affected_cluster_ids = [request.cluster_id, *new_ids]
    snapshot_members = await cluster_repo.get_members_by_cluster_ids(request.tenant_id, affected_cluster_ids)
    snapshot_version = await cluster_repo.get_snapshot_version(request.tenant_id)
    remaining_identity_ids: list[str] = []
    created_clusters: list[SplitCommandCreatedCluster] = []
    for member, _identity in snapshot_members:
        if member.cluster_id == request.cluster_id:
            remaining_identity_ids.append(member.identity_id)
            continue
        if member.cluster_id in new_ids:
            matching_cluster = next(
                (cluster for cluster in created_clusters if cluster.cluster_id == member.cluster_id),
                None,
            )
            if matching_cluster is None:
                matching_cluster = SplitCommandCreatedCluster(cluster_id=member.cluster_id, identity_ids=[])
                created_clusters.append(matching_cluster)
            matching_cluster.identity_ids.append(member.identity_id)

    response_obj = SplitTopologyCommandResponse(
        command_id=str(generate_id()),
        status="applied",
        original_cluster_id=request.cluster_id,
        new_cluster_ids=new_ids,
        member_delta=SplitCommandMemberDelta(
            source_cluster_id=request.cluster_id,
            remaining_identity_ids=remaining_identity_ids,
            created_clusters=created_clusters,
        ),
        moved_counts=counts,
        affected_cluster_ids=affected_cluster_ids,
        result_snapshot_version=snapshot_version,
    )
    await _store_topology_replay(session, request.tenant_id, request.idempotency_key, response_obj.model_dump())
    await session.commit()
    return response_obj


@router.post("/clusters/reassign", response_model=ReassignIdentityResponse)
async def reassign_identity(
    request: ReassignIdentityRequest,
    auth=Depends(require_write_access),
    session=Depends(get_session),
    cluster_service_builder=Depends(get_cluster_service_builder),
    suggestion_service=Depends(get_suggestion_service),
    suggestion_refresh_service=Depends(get_suggestion_refresh_service),
    job_service=Depends(get_persisted_cluster_job_service),
) -> ReassignIdentityResponse:
    """Reassign an identity to a different cluster.

    This endpoint is used for:
    - Accepting inline suggestions (moving singleton to labeled cluster)
    - Correcting misassigned identities
    - Removing from cluster (set target_cluster_id to null)

    When reassigning to a cluster, any pending suggestion for that identity+cluster
    is automatically marked as accepted.
    """
    validate_entity_id(request.identity_id, field_name="identity_id")
    cached_response = await _load_topology_replay(session, request.tenant_id, request.idempotency_key)
    if cached_response is not None:
        return ReassignIdentityResponse.model_validate(cached_response)
    if request.target_cluster_id:
        validate_entity_id(request.target_cluster_id, field_name="target_cluster_id")
    if auth and auth.tenant_claim and auth.tenant_claim != request.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant mismatch")

    if getattr(suggestion_service, "tenant_id", None) != request.tenant_id:
        suggestion_service = await get_suggestion_service(
            session=session,
            tenant_id=request.tenant_id,
        )
    if getattr(suggestion_refresh_service, "tenant_id", None) != request.tenant_id:
        suggestion_refresh_service = await get_suggestion_refresh_service(
            session=session,
            tenant_id=request.tenant_id,
        )

    cluster_service = await cluster_service_builder(request.tenant_id)
    cluster_repo = cluster_service.assignment_writer.cluster_repository
    if request.target_cluster_id:
        await _raise_if_cluster_stale(
            cluster_repo=cluster_repo,
            cluster_id=request.target_cluster_id,
            expected_base_version=request.expected_base_version,
        )

    # Get identity's current cluster (if any)
    source_cluster_id = await cluster_service.get_identity_cluster_id(request.identity_id)

    if request.target_cluster_id:
        block_repo = SqlAlchemyIdentityClusterBlockRepository(session, tenant_id=request.tenant_id)
        await block_repo.remove_block(
            tenant_id=request.tenant_id,
            identity_id=request.identity_id,
            blocked_cluster_id=request.target_cluster_id,
        )
        # Assign to target cluster
        result = await cluster_service.assign_outlier_to_cluster(
            identity_id=request.identity_id,
            target_cluster_id=request.target_cluster_id,
            tenant_id=request.tenant_id,
            similarity=0.0,  # Not known at this point
        )
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Identity or target cluster not found",
            )

        # Resolve any pending suggestion for this identity+cluster as accepted
        await suggestion_service.resolve_for_identity_exclusive(
            identity_id=request.identity_id,
            accepted_cluster_id=request.target_cluster_id,
            reason="manual_assign",
        )
        await suggestion_refresh_service.refresh_for_identity(
            identity_id=request.identity_id,
            reason=SuggestionRefreshReason.MANUAL_ASSIGN,
        )
    else:
        # Remove from current cluster (make orphan)
        await cluster_service.remove_identity_from_cluster(request.identity_id, recompute=True)
        if source_cluster_id:
            if request.block_from_cluster:
                block_repo = SqlAlchemyIdentityClusterBlockRepository(session, tenant_id=request.tenant_id)
                await block_repo.add_block(
                    tenant_id=request.tenant_id,
                    identity_id=request.identity_id,
                    blocked_cluster_id=source_cluster_id,
                    reason="manual_removal",
                )

                # Create CANNOT_LINK constraint to permanently prevent linking
                try:
                    # We need the cluster's representative to anchor the constraint
                    cluster_repo = cluster_service.assignment_writer.cluster_repository
                    source_cluster = await cluster_repo.get_by_id(source_cluster_id)

                    if source_cluster and source_cluster.representative_identity_id:
                        constraint_repo = SqlAlchemyConstraintRepository(session)
                        await constraint_repo.create(
                            tenant_id=request.tenant_id,
                            identity_a=request.identity_id,
                            identity_b=str(source_cluster.representative_identity_id),
                            constraint_type=ConstraintType.CANNOT_LINK.value,
                            source=ConstraintSource.WRONG_PERSON.value,
                            created_by_user_id=None,  # User ID not currently available in request
                        )
                except Exception as exc:
                    # Don't fail the request if constraint creation fails
                    _logger.warning(
                        "Failed to create CANNOT_LINK constraint for identity %s: %s", request.identity_id, exc
                    )

            await job_service.queue_curation_followup(
                tenant_id=request.tenant_id,
                cluster_ids=[source_cluster_id],
                identity_ids=[request.identity_id],
            )
        if source_cluster_id:
            await suggestion_service.resolve_for_identity(
                identity_id=request.identity_id,
                cluster_id=source_cluster_id,
                resolution="rejected",
            )
        await suggestion_refresh_service.refresh_for_identity(
            identity_id=request.identity_id,
            reason=SuggestionRefreshReason.WRONG_PERSON,
        )

        # Refresh suggestions for the affected clusters
        if source_cluster_id:
            await suggestion_refresh_service.refresh_for_cluster(source_cluster_id)

    # Commit before response so client refetches see committed state (see PATCH handler comment).
    response_obj = ReassignIdentityResponse(
        identity_id=request.identity_id,
        source_cluster_id=source_cluster_id,
        target_cluster_id=request.target_cluster_id,
        success=True,
        backend_version=(
            await _get_cluster_backend_version(
                cluster_repo,
                request.target_cluster_id if request.target_cluster_id else (source_cluster_id or ""),
            )
            if request.target_cluster_id or source_cluster_id
            else 0
        ),
    )
    await _store_topology_replay(session, request.tenant_id, request.idempotency_key, response_obj.model_dump())
    await session.commit()

    return response_obj


@router.post("/clusters/revert-merge", response_model=RevertMergeClusterResponse)
async def revert_merge_cluster(
    request: RevertMergeClusterRequest,
    auth=Depends(require_write_access),
    session=Depends(get_session),
    cluster_service_builder=Depends(get_cluster_service_builder),
) -> RevertMergeClusterResponse:
    """Restore moved identities into a recreated source cluster."""
    cached_response = await _load_topology_replay(session, request.tenant_id, request.idempotency_key)
    if cached_response is not None:
        return RevertMergeClusterResponse.model_validate(cached_response)
    if auth and auth.tenant_claim and auth.tenant_claim != request.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant mismatch")

    cluster_service = await cluster_service_builder(request.tenant_id)
    cluster_repo = cluster_service.assignment_writer.cluster_repository
    await _raise_if_cluster_stale(
        cluster_repo=cluster_repo,
        cluster_id=request.target_cluster_id,
        expected_base_version=request.expected_base_version,
    )

    target_cluster = await cluster_repo.get_by_id(request.target_cluster_id)
    if target_cluster is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target cluster not found")

    for identity_id in request.moved_identity_ids:
        current_cluster_id = await cluster_service.get_identity_cluster_id(identity_id)
        if current_cluster_id != request.target_cluster_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="One or more identities are no longer assigned to the target cluster",
            )

    restored_label = request.source_label or ""
    source_cluster_id = request.desired_source_cluster_id or str(generate_id())
    restored_cluster = await cluster_service.create_cluster_for_identity(
        identity_id=request.moved_identity_ids[0],
        label=restored_label,
        tenant_id=request.tenant_id,
        desired_cluster_id=source_cluster_id,
    )

    for identity_id in request.moved_identity_ids[1:]:
        reassigned = await cluster_service.assign_outlier_to_cluster(
            identity_id=identity_id,
            target_cluster_id=restored_cluster.id,
            tenant_id=request.tenant_id,
            similarity=0.0,
        )
        if reassigned is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Identity not found")

    refreshed_target = await cluster_repo.get_by_id(request.target_cluster_id)
    response_obj = RevertMergeClusterResponse(
        restored_cluster_id=restored_cluster.id,
        restored_identity_count=len(request.moved_identity_ids),
        target_cluster_id=request.target_cluster_id,
        target_identity_count=int(getattr(refreshed_target, "identity_count", 0) or 0),
        restored_label=request.source_label,
        backend_version=await _get_cluster_backend_version(cluster_repo, request.target_cluster_id),
    )
    await _store_topology_replay(session, request.tenant_id, request.idempotency_key, response_obj.model_dump())
    await session.commit()
    return response_obj


@router.post("/clusters/{cluster_id}/assign", response_model=ClusterResponse)
async def assign_outlier(
    cluster_id: str,
    request: AssignOutlierRequest,
    auth=Depends(require_write_access),
    session=Depends(get_session),
    cluster_service_builder=Depends(get_cluster_service_builder),
    suggestion_refresh_service=Depends(get_suggestion_refresh_service),
) -> ClusterResponse:
    """Assign an unclustered identity (outlier) to an existing cluster."""
    validate_entity_id(cluster_id, field_name="cluster_id")
    validate_entity_id(request.identity_id, field_name="identity_id")
    cached_response = await _load_topology_replay(session, request.tenant_id, request.idempotency_key)
    if cached_response is not None:
        return ClusterResponse.model_validate(cached_response)
    if auth and auth.tenant_claim and auth.tenant_claim != request.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant mismatch")

    if getattr(suggestion_refresh_service, "tenant_id", None) != request.tenant_id:
        suggestion_refresh_service = await get_suggestion_refresh_service(
            session=session,
            tenant_id=request.tenant_id,
        )

    cluster_service = await cluster_service_builder(request.tenant_id)
    cluster_repo = cluster_service.assignment_writer.cluster_repository
    await _raise_if_cluster_stale(
        cluster_repo=cluster_repo,
        cluster_id=cluster_id,
        expected_base_version=request.expected_base_version,
    )
    cluster = await cluster_service.assign_outlier_to_cluster(
        identity_id=request.identity_id,
        target_cluster_id=cluster_id,
        tenant_id=request.tenant_id,
        similarity=request.similarity,
    )
    if not cluster:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cluster or identity not found")

    # Refresh suggestions for the target cluster
    await suggestion_refresh_service.refresh_for_cluster(cluster_id)

    # Commit before response so client refetches see committed state (see PATCH handler comment).
    response_obj = ClusterResponse.model_validate(cluster)
    response_obj.backend_version = await _get_cluster_backend_version(cluster_repo, cluster_id)
    await _store_topology_replay(session, request.tenant_id, request.idempotency_key, response_obj.model_dump())
    await session.commit()

    return response_obj


@router.patch("/clusters/{cluster_id}/representatives/{representative_id}/pin", status_code=status.HTTP_204_NO_CONTENT)
async def pin_representative(
    cluster_id: str,
    representative_id: str,
    request: PinRepresentativeRequest,
    auth=Depends(require_write_access),
    repo=Depends(get_cluster_repository),
) -> None:
    """Pin or unpin a cluster representative."""
    validate_entity_id(cluster_id, field_name="cluster_id")
    validate_entity_id(representative_id, field_name="representative_id")
    if auth and auth.tenant_claim and auth.tenant_claim != request.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant mismatch")

    await repo.mark_representative_user_selected(
        representative_id=representative_id,
        is_selected=request.is_pinned,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Maintenance endpoints
# ---------------------------------------------------------------------------


@router.get("/clusters/centroid-health")
async def get_centroid_mv_health(
    session=Depends(get_session),
) -> dict:
    """Return centroid MV row count vs identity_clusters for health monitoring.

    Uses RLS bypass so counts reflect all tenants' data, not just the caller's.
    Intended for operator / monitoring use.
    """
    from sqlalchemy import text as sa_text

    from db.tenant_context import enable_rls_bypass as _enable_bypass

    await _enable_bypass(session)
    try:
        mv_count = await session.scalar(sa_text("SELECT COUNT(*) FROM mv_identity_cluster_centroids"))
        cluster_count = await session.scalar(sa_text("SELECT COUNT(*) FROM identity_clusters"))
        healthy = mv_count == cluster_count
        if not healthy:
            _logger.warning(
                "Centroid MV health check divergence: mv_count=%s cluster_count=%s",
                mv_count,
                cluster_count,
            )
        return {
            "mv_count": int(mv_count or 0),
            "cluster_count": int(cluster_count or 0),
            "healthy": healthy,
        }
    except Exception:
        _logger.exception("Centroid health check failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Health check query failed",
        )


@router.post("/clusters/maintenance/refresh-centroids", status_code=status.HTTP_202_ACCEPTED)
async def trigger_centroid_mv_refresh(
    session=Depends(get_session),
    auth=Depends(require_write_access),
) -> dict:
    """Trigger an out-of-band refresh of the centroid materialized view.

    This is the dedicated maintenance path for MV refresh, independent of the
    scan worker's polling loop.  Returns ``ok: true`` on success.
    """
    from recognition.infrastructure.repositories.cluster_repository import SqlAlchemyClusterRepository

    repo = SqlAlchemyClusterRepository(session)
    succeeded = await repo.refresh_centroids_view_concurrent()
    return {"ok": succeeded}


# _job_to_response and _job_to_clustering_response are imported from job_utils
