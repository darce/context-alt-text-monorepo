"""Clustering-job admission and orphan-recovery routes.

Concern router split out of the former ``clusters.py`` god-router (Slice 6):
the clustering-job admission path (pg_locks pre-flight, narrow tenant-lock
fast-fail, circuit breaker) plus the orphan re-clustering trigger.
"""

from __future__ import annotations

import logging
import time as _time
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Tenant
from db.settings import get_database_settings
from db.tenant_context import set_tenant_context
from recognition.domain.job import JobStatus, JobType
from recognition.interface_adapters.http.deps import (
    get_cluster_service_builder,
    get_cluster_service_builder_clustering,
    get_clustering_session,
    get_persisted_cluster_job_service_clustering,
    get_session,
    require_auth,
    require_write_access,
)
from recognition.interface_adapters.http.deps.clustering_circuit_breaker import (
    get_or_create_clustering_circuit_breaker,
)
from recognition.interface_adapters.http.deps.demo_quota import enforce_demo_quota
from recognition.interface_adapters.http.deps.rate_limit import enforce_rate_limit
from recognition.interface_adapters.http.deps.session import (
    _apply_postgres_session_safety_settings,
    _resolve_pg_backend_pid,
)
from recognition.interface_adapters.http.job_utils import (
    job_to_clustering_response as _job_to_clustering_response,
)
from recognition.interface_adapters.http.middleware.metrics import get_default_metrics
from recognition.interface_adapters.http.routers.clusters_common import assert_tenant_match
from recognition.interface_adapters.http.schemas.requests import (
    ClusteringJobRequest,
    RecoverOrphansRequest,
)
from recognition.interface_adapters.http.schemas.responses import (
    ClusteringJobStatusResponse,
    JobProgressResponse,
    OrphanRecoveryResponse,
)
from recognition.shared.db.dialect import is_postgres
from recognition.shared.ids import generate_id

_logger = logging.getLogger(__name__)

# SEC-01 / API-05: the caller is on the untrusted side of this boundary. A server
# fault is logged in full server-side and reported outward as this fixed string;
# clustering-service exception text (DB driver messages, SQL fragments, absolute
# paths) never crosses.
INTERNAL_ERROR_DETAIL = "internal server error"

# E15-3a-BR-21 Slice 2: admission fail-fast queries. Documented on the probe
# helper below. The defaults used for the default statement_timeout restore
# are pulled from db.settings (DB_STATEMENT_TIMEOUT) so this stays in sync
# with the global fault-isolation boundary.
# E15-3a-BR-22: narrow the probe to lock modes that actually conflict with
# a SELECT ... FOR UPDATE. SELECT FOR UPDATE acquires a relation-level
# RowShareLock plus a row-level tuple lock. The only relation-level modes
# that conflict with RowShareLock are ExclusiveLock and AccessExclusiveLock
# (readers' AccessShareLock and our own RowShareLock are compatible). The
# row-level conflict shows up in pg_locks with locktype='tuple' on the
# relation. Anything else -- in particular a reader's AccessShareLock held
# by an idle-in-txn backend -- is NOT a blocker and must not trip the probe.
_CLUSTERING_ADMISSION_PROBE_SQL = """
SELECT 1
FROM pg_locks l
JOIN pg_stat_activity a ON a.pid = l.pid
WHERE l.relation = 'tenants'::regclass
  AND l.granted = true
  AND a.state = 'idle in transaction'
  AND a.pid <> pg_backend_pid()
  AND (
    l.locktype = 'tuple'
    OR (l.locktype = 'relation' AND l.mode IN ('ExclusiveLock', 'AccessExclusiveLock'))
  )
LIMIT 1
"""

# Postgres SQLSTATE for a canceled statement (statement_timeout hit or explicit
# pg_cancel_backend). We match by SQLSTATE rather than by asyncpg exception
# type to keep the branch driver-agnostic.
_QUERY_CANCELED_SQLSTATE = "57014"

router = APIRouter(tags=["clusters"], dependencies=[Depends(require_auth), Depends(enforce_rate_limit)])


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


@router.post("/clustering/jobs", response_model=ClusteringJobStatusResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_clustering_job(
    request: ClusteringJobRequest,
    http_request: Request,
    auth=Depends(require_write_access),
    # E15-3a-BR-21 Slice 4: all three deps bind to the clustering pool so
    # FastAPI's DI cache hands the same AsyncSession to each. Saturating the
    # clustering pool under contention cannot block unrelated traffic on the
    # business or observability pools (bulkhead).
    session=Depends(get_clustering_session),
    cluster_service_builder=Depends(get_cluster_service_builder_clustering),
    job_service=Depends(get_persisted_cluster_job_service_clustering),
    _demo_quota: object = Depends(enforce_demo_quota),
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

        if request.mode == "sync":
            # Legacy sync mode: build the service on-demand; no owned-txn block.
            cluster_service = await cluster_service_builder(request.tenant_id)
            try:
                result = await cluster_service.cluster_unclustered_identities(request.tenant_id)
            except Exception as exc:
                _admission_status = status.HTTP_500_INTERNAL_SERVER_ERROR
                _logger.exception("Sync clustering failed for tenant %s", request.tenant_id)
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=INTERNAL_ERROR_DETAIL
                ) from exc
            finished_at = getattr(result, "finished_at", None)
            completed = getattr(result, "completed", 0)
            total = getattr(result, "total", 0)
            clusters_created = getattr(result, "clusters_created", 0)
            job_id = getattr(result, "job_id", str(generate_id()))
            return ClusteringJobStatusResponse(
                id=str(job_id),
                type=JobType.CLUSTERING.value,
                status=JobStatus.COMPLETED,
                progress=JobProgressResponse(completed=completed, total=total),
                started_at=result.started_at if hasattr(result, "started_at") else datetime.now(tz=UTC),
                finished_at=finished_at,
                clusters_created=clusters_created,
                total_identities_clustered=completed,
            )

        # Async mode: create a pending job for background worker to process.
        # Reuse an existing pending/running clustering job for the tenant to avoid
        # duplicate expensive work from repeated clicks or repeated UI effects.
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

        # E15-3a-BR-21 Slice 4: route-owned transaction. Wraps the full
        # unit-of-work (pg_locks probe + SELECT FOR UPDATE + lookup + INSERT)
        # in one session.begin() on one connection. Ordering matters:
        #
        #   (1) safety settings  (statement_timeout + idle_in_txn_timeout)
        #   (2) set_tenant_context  (required before any tenant-scoped SQL)
        #   (3) pg_backend_pid      (PLAN-07: resolved inside the owned txn
        #                            so log correlation joins pg_stat_activity
        #                            for *this* connection, not a stale one)
        #   (4) cluster_service builder + reassignment onto job_service
        #       (PLAN-12: builder's set_tenant_context + require_tenant_record
        #        SQL must land inside the owned txn, not during dep resolution)
        #   (5) pg_locks admission probe            (S2)
        #   (6) narrow SET LOCAL statement_timeout  (S2)
        #   (7) SELECT ... FOR UPDATE               (S2)
        #   (8) restore SET LOCAL to default        (PLAN-08)
        #   (9) active-job lookup
        #   (10) INSERT new job row
        #
        # session.begin() commits on clean exit and rolls back on exception.
        tenant_uuid = UUID(request.tenant_id)
        async with session.begin():
            await _apply_postgres_session_safety_settings(session)  # (1)
            await set_tenant_context(session, tenant_uuid)  # (2)
            await _resolve_pg_backend_pid(session)  # (3) PLAN-07
            cluster_service = await cluster_service_builder(request.tenant_id)  # (4) PLAN-12
            job_service.cluster_service = cluster_service
            await _clustering_admission_probe(  # (5)
                session,
                tenant_id=request.tenant_id,
                retry_after_seconds=_db_settings.clustering_admission_retry_after_seconds,
            )
            try:
                await _acquire_tenant_lock_fast_fail(  # (6), (7), (8)
                    session,
                    tenant_id=request.tenant_id,
                    lock_timeout_ms=_db_settings.clustering_tenant_lock_timeout_ms,
                    default_timeout=_db_settings.statement_timeout,
                    retry_after_seconds=_db_settings.clustering_admission_retry_after_seconds,
                )
            except HTTPException as exc:
                # Narrow: a 503 from the lock helper is the QueryCanceledError
                # path (SQLSTATE 57014). Count only that signal toward breaker
                # failures.
                if exc.status_code == status.HTTP_503_SERVICE_UNAVAILABLE:
                    _breaker.record_failure()
                raise
            existing_job = await job_service.get_active_clustering_job_for_tenant(request.tenant_id)  # (9)
            if existing_job is not None:
                _breaker.record_success()
                return _job_to_clustering_response(existing_job)

            job = await job_service.create_job(JobType.CLUSTERING, tenant_id=request.tenant_id)  # (10)
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
    _demo_quota: object = Depends(enforce_demo_quota),
) -> OrphanRecoveryResponse:
    """Re-cluster any orphaned identities for a tenant."""
    assert_tenant_match(auth, request.tenant_id)

    cluster_service = await cluster_service_builder(request.tenant_id)
    try:
        result = await cluster_service.cluster_unclustered_identities(request.tenant_id)
    except Exception as exc:
        _logger.exception("Orphan recovery failed for tenant %s", request.tenant_id)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=INTERNAL_ERROR_DETAIL) from exc

    return OrphanRecoveryResponse(
        orphans_found=int(getattr(result, "total", 0) or 0),
        recovered=int(getattr(result, "accepted", 0) or 0),
        suggested=int(getattr(result, "suggested", 0) or 0),
        rejected=int(getattr(result, "rejected", 0) or 0),
        clusters_created=int(getattr(result, "clusters_created", 0) or 0),
    )
