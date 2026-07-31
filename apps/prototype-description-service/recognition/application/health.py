"""Health probe helpers for the recognition service.

Dep checks live here (not in the HTTP router) so /ready and /health/detailed
(Slice 2.5) can share a single source of truth. The helpers are plain async
functions — the HTTP layer owns wiring them to FastAPI dependencies.
"""

from __future__ import annotations

import contextvars
import hashlib
import logging
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from recognition.infrastructure.face_pipeline.provenance import (
    MODEL_MANIFEST,
    ModelVerifyOutcome,
    verify_face_pipeline_model,
)
from recognition.interface_adapters.http.deps.circuit_breaker import (
    BreakerState,
    SessionDependencyCircuitBreaker,
)
from shared.health import HealthReport, HealthStatus

logger = logging.getLogger(__name__)

# Process-local eager verify cache for face_pipeline readiness ([EMB-05]).
# Keyed by absolute model path; value is last full-verify outcome.
# Lock required once verify may run off the event loop (S3CR-05).
_FACE_PIPELINE_VERIFY_CACHE: dict[str, ModelVerifyOutcome] = {}
_FACE_PIPELINE_VERIFY_CACHE_LOCK = threading.Lock()

# Identity embedding columns that must share configured PGVECTOR_DIM ([EMB-05], [rg-005]).
IDENTITY_VECTOR_COLUMNS: tuple[tuple[str, str], ...] = (
    ("media_identities", "embedding"),
    ("identity_cluster_representatives", "embedding"),
    ("mv_identity_cluster_centroids", "centroid"),
)

# Live pgvector typmod probe: tables + matview via pg_catalog (no convenience guesses).
# atttypmod for pgvector ``vector(N)`` is the dimension N (or -1 when unspecified).
_IDENTITY_VECTOR_TYPMOD_SQL = """
SELECT
  c.relname::text AS table_name,
  a.attname::text AS column_name,
  a.atttypmod AS vector_dim
FROM pg_catalog.pg_attribute AS a
JOIN pg_catalog.pg_class AS c ON a.attrelid = c.oid
JOIN pg_catalog.pg_namespace AS n ON c.relnamespace = n.oid
JOIN pg_catalog.pg_type AS t ON a.atttypid = t.oid
WHERE n.nspname = current_schema()
  AND c.relkind IN ('r', 'm', 'p')
  AND NOT a.attisdropped
  AND a.attnum > 0
  AND t.typname = 'vector'
  AND (
    (c.relname = 'media_identities' AND a.attname = 'embedding')
    OR (c.relname = 'identity_cluster_representatives' AND a.attname = 'embedding')
    OR (c.relname = 'mv_identity_cluster_centroids' AND a.attname = 'centroid')
  )
"""

# Distinct embedding_model probe for the co-located readiness partition check.
# LIMIT bounds result cardinality only; scan cost is controlled by
# idx_media_identities_embedding_model (partial index on embedding_model).
_DISTINCT_EMBEDDING_MODELS_SQL = """
SELECT DISTINCT embedding_model
FROM media_identities
WHERE embedding_model IS NOT NULL
  AND btrim(embedding_model) <> ''
LIMIT 64
"""

# Task-local stash: check_database populates so check_active_embedding_model can
# compare without changing the sync call shape in the HTTP router.
# None  → probe did not run / failed (skip partition; keep prior OK-if-resolved behaviour)
# ()    → table empty or no model_id rows (fresh deploy — not a partition)
# (...) → distinct persisted spaces
_persisted_embedding_models_for_ready: contextvars.ContextVar[tuple[str, ...] | None] = contextvars.ContextVar(
    "persisted_embedding_models_for_ready",
    default=None,
)

# Sentinel: keyword omitted → read contextvar; explicit None → skip partition.
_PERSISTED_MODELS_UNSET: object = object()


@dataclass(frozen=True, slots=True)
class CheckResult:
    """One dependency probe's outcome as it appears in /ready response."""

    name: str
    status: HealthStatus
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "status": self.status.value, "detail": self.detail}


def check_health() -> HealthReport:
    """Return a static health signal for the recognition service."""
    return HealthReport.ok("recognition")


def _row_triple(row: Any) -> tuple[str, str, Any]:
    """Normalize a catalog row to (relation, column, dim)."""
    if isinstance(row, (tuple, list)) and len(row) >= 3:
        return str(row[0]), str(row[1]), row[2]
    # SQLAlchemy Row: indexable / _mapping
    try:
        return str(row[0]), str(row[1]), row[2]
    except Exception as exc:
        raise ValueError(f"malformed vector typmod row: {row!r}") from exc


def validate_identity_vector_dimensions(
    rows: Sequence[Any],
    *,
    configured_dim: int,
) -> CheckResult:
    """Pure validator for live identity-vector typmods vs configured PGVECTOR_DIM.

    Fail closed on empty/missing/duplicate/malformed rows, non-positive dims,
    or any configured-vs-live mismatch. Does not mutate the database.
    """
    expected = set(IDENTITY_VECTOR_COLUMNS)
    if configured_dim <= 0:
        return CheckResult(
            "database",
            HealthStatus.UNHEALTHY,
            f"invalid configured pgvector dimension={configured_dim}",
        )
    if not rows:
        return CheckResult(
            "database",
            HealthStatus.UNHEALTHY,
            (f"missing identity vector schema (no pgvector typmod rows); configured_dimension={configured_dim}"),
        )

    seen: dict[tuple[str, str], int] = {}
    try:
        for raw in rows:
            table, column, raw_dim = _row_triple(raw)
            key = (table, column)
            if key not in expected:
                return CheckResult(
                    "database",
                    HealthStatus.UNHEALTHY,
                    (f"unexpected vector column {table}.{column}; configured_dimension={configured_dim}"),
                )
            if key in seen:
                return CheckResult(
                    "database",
                    HealthStatus.UNHEALTHY,
                    (f"duplicate vector typmod for {table}.{column}; configured_dimension={configured_dim}"),
                )
            try:
                dim = int(raw_dim)
            except (TypeError, ValueError):
                return CheckResult(
                    "database",
                    HealthStatus.UNHEALTHY,
                    (
                        f"malformed vector dimension for {table}.{column}={raw_dim!r}; "
                        f"configured_dimension={configured_dim}"
                    ),
                )
            if dim <= 0:
                return CheckResult(
                    "database",
                    HealthStatus.UNHEALTHY,
                    (
                        f"non-positive vector dimension for {table}.{column}={dim}; "
                        f"configured_dimension={configured_dim}"
                    ),
                )
            seen[key] = dim
    except ValueError as exc:
        return CheckResult(
            "database",
            HealthStatus.UNHEALTHY,
            f"malformed vector typmod rows: {exc}; configured_dimension={configured_dim}",
        )

    missing = expected - set(seen)
    if missing:
        missing_s = ", ".join(f"{t}.{c}" for t, c in sorted(missing))
        return CheckResult(
            "database",
            HealthStatus.UNHEALTHY,
            (f"missing identity vector columns: {missing_s}; configured_dimension={configured_dim}"),
        )

    mismatches = [(f"{t}.{c}", d) for (t, c), d in sorted(seen.items()) if d != configured_dim]
    if mismatches:
        live_s = ", ".join(f"{name}={dim}" for name, dim in mismatches)
        all_live = ", ".join(f"{t}.{c}={d}" for (t, c), d in sorted(seen.items()))
        return CheckResult(
            "database",
            HealthStatus.UNHEALTHY,
            (
                f"pgvector dimension mismatch: configured={configured_dim}, "
                f"live_mismatch={live_s}, live_all=[{all_live}]"
            ),
        )

    return CheckResult(
        "database",
        HealthStatus.OK,
        f"reachable; pgvector_dimension={configured_dim}",
    )


async def _refresh_persisted_embedding_models_for_ready(session: AsyncSession) -> None:
    """Stash distinct persisted embedding_model values for the partition check.

    Failures (missing table, permission, driver errors) clear the stash to
    None so check_active_embedding_model falls back to resolve-only behaviour
    rather than hard-failing readiness on infrastructure it does not own.

    Runs inside a savepoint so a failed advisory probe cannot abort the
    outer observability transaction used by the subsequent typmod probe.
    """
    try:
        async with session.begin_nested():
            result = await session.execute(text(_DISTINCT_EMBEDDING_MODELS_SQL))
            models = tuple(str(row[0]).strip() for row in result.all() if row[0] is not None and str(row[0]).strip())
            _persisted_embedding_models_for_ready.set(models)
    except Exception:
        logger.warning(
            "persisted embedding_model partition probe failed; falling back to resolve-only",
            exc_info=True,
        )
        _persisted_embedding_models_for_ready.set(None)


async def check_database(session: AsyncSession | None) -> CheckResult:
    """Probe DB reachability and live identity-vector width vs PGVECTOR_DIM.

    The session dependency already ran SELECT 1 (or yielded None). This probe
    additionally reads pgvector typmods for identity embedding columns so
    configured-vs-live dimension drift cannot report ready ([EMB-05], [rg-005],
    [OBS-08]). Fail closed; never mutate/heal schema here.

    Also refreshes the task-local distinct embedding_model stash consumed by
    ``check_active_embedding_model`` (embedding-space partition alarm).
    """
    if session is None:
        _persisted_embedding_models_for_ready.set(None)
        return CheckResult("database", HealthStatus.UNHEALTHY, "connection_unavailable")

    await _refresh_persisted_embedding_models_for_ready(session)

    from db.settings import get_database_settings

    configured_dim = int(get_database_settings().pgvector_dimension)
    try:
        result = await session.execute(text(_IDENTITY_VECTOR_TYPMOD_SQL))
        rows = result.all()
    except Exception as exc:
        return CheckResult(
            "database",
            HealthStatus.UNHEALTHY,
            f"vector dimension probe failed: {type(exc).__name__}",
        )

    return validate_identity_vector_dimensions(rows, configured_dim=configured_dim)


def _coarse_space_token(model_id: str) -> str:
    """First 8 hex of sha256(model_id) for public readiness surfaces."""
    return hashlib.sha256(model_id.encode("utf-8")).hexdigest()[:8]


def check_active_embedding_model(
    *,
    persisted_model_ids: Sequence[str] | None | object = _PERSISTED_MODELS_UNSET,
    verbose: bool = False,
) -> CheckResult:
    """Fail-closed readiness: active embedding space must resolve (FIR23-01).

    Read paths filter by embedding_model; without a resolved active model_id the
    service must not advertise ready. Single-model deployments are a no-op once
    the id is known.

    When distinct persisted ``embedding_model`` values are available (explicit
    ``persisted_model_ids``, or the task-local stash filled by
    ``check_database``), degrade if the active id matches **zero** of them and
    the set is non-empty. An empty set is a fresh deploy, not a partition.
    When the probe did not run (no session / table absent), keep the prior
    resolve-only behaviour so readiness does not hard-fail on infrastructure
    this check does not own. Explicit results only (sr-006) — never assert.

    ``verbose=True`` (auth-gated /health/detailed) keeps full space tokens in
    detail; the public /ready path uses coarse hashes/counts only.
    """
    try:
        from recognition.application.embedding.manifest import active_embedding_model_id

        model_id = active_embedding_model_id()
    except Exception as exc:
        return CheckResult(
            "embedding_model",
            HealthStatus.UNHEALTHY,
            f"active embedding_model unresolved: {exc}",
        )
    if not model_id:
        return CheckResult(
            "embedding_model",
            HealthStatus.UNHEALTHY,
            "active embedding_model unresolved: empty model_id",
        )

    if persisted_model_ids is _PERSISTED_MODELS_UNSET:
        resolved_persisted: Sequence[str] | None = _persisted_embedding_models_for_ready.get()
    else:
        resolved_persisted = persisted_model_ids  # type: ignore[assignment]

    coarse = _coarse_space_token(model_id)

    if resolved_persisted is None:
        if verbose:
            return CheckResult("embedding_model", HealthStatus.OK, f"active={model_id}")
        return CheckResult("embedding_model", HealthStatus.OK, f"active_space={coarse}")

    # model_id wire form is ``framework-name@Nd/norm/metric`` (always contains '@').
    # Ignore non-id values so a mis-bound probe result cannot false-alarm.
    persisted = tuple(str(m).strip() for m in resolved_persisted if m is not None and str(m).strip() and "@" in str(m))
    if not persisted:
        # Fresh deployment / empty embeddings table — not a partition.
        if verbose:
            return CheckResult("embedding_model", HealthStatus.OK, f"active={model_id}; persisted=none")
        return CheckResult(
            "embedding_model",
            HealthStatus.OK,
            f"active_space={coarse}; persisted_spaces=0",
        )

    if model_id in persisted:
        if verbose:
            return CheckResult(
                "embedding_model",
                HealthStatus.OK,
                f"active={model_id}; persisted_match=true",
            )
        return CheckResult(
            "embedding_model",
            HealthStatus.OK,
            f"active_space={coarse}; persisted_spaces={len(persisted)}",
        )

    # Active space matches no persisted rows: silent partition after model_id flip.
    if verbose:
        sample = ", ".join(persisted[:8])
        more = "" if len(persisted) <= 8 else f", +{len(persisted) - 8} more"
        return CheckResult(
            "embedding_model",
            HealthStatus.DEGRADED,
            (
                f"active={model_id} matches no persisted embedding_model "
                f"(persisted=[{sample}{more}]); embedding space partition"
            ),
        )
    return CheckResult(
        "embedding_model",
        HealthStatus.DEGRADED,
        (
            f"active_space={coarse} matches no persisted embedding_model "
            f"(persisted_spaces={len(persisted)}); embedding space partition"
        ),
    )


def check_breaker(breaker: SessionDependencyCircuitBreaker) -> CheckResult:
    """An OPEN breaker means DB checkout is blocked — /ready fails (local finding BR-02).

    Readiness succeeds only when DB checks pass, the breaker is closed, and
    the model bundle is present. An OPEN breaker violates that contract, so
    the aggregate status flips UNHEALTHY and the handler returns 503 so the
    load balancer pulls the pod until the breaker resets.
    """
    if breaker.state is BreakerState.OPEN:
        return CheckResult("breaker", HealthStatus.UNHEALTHY, "open")
    return CheckResult("breaker", HealthStatus.OK, breaker.state.value)


def check_model_cache(cache_dir: Path, model_name: str = "buffalo_l") -> CheckResult:
    """Stat the InsightFace bundle on every call (PA-10: no caching).

    The bundle must be a directory containing at least one .onnx file;
    a missing directory or empty bundle flips /ready to UNHEALTHY.
    """
    bundle = cache_dir / model_name
    if not bundle.is_dir():
        return CheckResult("model_cache", HealthStatus.UNHEALTHY, f"missing: {bundle}")
    onnx_files = list(bundle.glob("*.onnx"))
    if not onnx_files:
        return CheckResult("model_cache", HealthStatus.UNHEALTHY, f"no_onnx_files: {bundle}")
    return CheckResult("model_cache", HealthStatus.OK, f"{len(onnx_files)} bundle file(s)")


def _stat_file_identity(path: Path) -> tuple[int, int] | None:
    """Return (mtime_ns, size) for an existing file; None on missing/race ([DRIFT-02])."""
    try:
        if not path.is_file():
            return None
        st = path.stat()
        return (int(st.st_mtime_ns), int(st.st_size))
    except OSError:
        return None


def _cached_verify_outcome(name: str, *, models_dir: Path) -> ModelVerifyOutcome:
    """Return last verified outcome, re-running full sha256 on miss or identity drift.

    Cache freshness observes both model and license path identity (existence,
    mtime_ns, size). Stable model+license hits avoid rehashing large ONNX files;
    license-only drift forces full re-verify ([EMB-05], [DRIFT-02]).
    """
    entry = MODEL_MANIFEST[name]
    path = models_dir / entry.file_name
    license_path = models_dir / entry.license_file
    cache_key = str(path.resolve()) if path.exists() else str(path)

    with _FACE_PIPELINE_VERIFY_CACHE_LOCK:
        cached = _FACE_PIPELINE_VERIFY_CACHE.get(cache_key)
        model_id = _stat_file_identity(path)
        license_id = _stat_file_identity(license_path)

        if cached is not None and model_id is not None and license_id is not None:
            if (
                cached.mtime_ns == model_id[0]
                and cached.size == model_id[1]
                and cached.license_mtime_ns == license_id[0]
                and cached.license_size == license_id[1]
            ):
                return cached
        elif (
            cached is not None
            and not cached.ok
            and cached.mtime_ns == 0
            and cached.size == 0
            and cached.license_mtime_ns == 0
            and cached.license_size == 0
            and model_id is None
            and license_id is None
        ):
            # Both artifacts still missing after a prior fail; re-check recovery.
            pass

        outcome = verify_face_pipeline_model(name, models_dir=models_dir)
        # Cache under resolved path when present so renames don't leak stale OK.
        store_key = str(outcome.path.resolve()) if outcome.path.exists() else cache_key
        _FACE_PIPELINE_VERIFY_CACHE[store_key] = outcome
        if store_key != cache_key:
            _FACE_PIPELINE_VERIFY_CACHE[cache_key] = outcome
        return outcome


def check_face_pipeline_models(models_dir: Path) -> CheckResult:
    """Eager profile-aware readiness for YuNet+SFace ([EMB-05], [OBS-08]).

    First probe (or API boot) runs full ``load_verified_model`` per artifact and
    caches (ok|reason, mtime, size). Subsequent probes re-stat only; drift
    triggers full re-verify. UNHEALTHY detail names the failing artifact.

    After model verification passes, also assert three-way embedding dimension
    equality (manifest == pgvector == identity_detection) so a 512-dim env with
    SFace-128 models cannot report ready (E2E-03).

    Finally construct/prove the process-wide shared ORT runtime used by serve
    so hashes+dims alone cannot green-light a broken InferenceSession
    ([local finding GROKHARM-04][SERVE-01]). Healthy readiness populates/reuses
    that singleton.
    """
    root = Path(models_dir)
    failures: list[str] = []
    for name in ("yunet", "sface"):
        outcome = _cached_verify_outcome(name, models_dir=root)
        if not outcome.ok:
            failures.append(f"{name}: {outcome.reason or 'unverified'}")
    if failures:
        return CheckResult(
            "model_cache",
            HealthStatus.UNHEALTHY,
            "; ".join(failures),
        )
    try:
        from recognition.infrastructure.embeddings.face_pipeline_adapter import (
            assert_three_way_embedding_dimensions,
            sface_embedding_model_manifest,
        )

        assert_three_way_embedding_dimensions(sface_embedding_model_manifest())
    except Exception as exc:
        return CheckResult(
            "model_cache",
            HealthStatus.UNHEALTHY,
            f"embedding dimension mismatch: {exc}",
        )
    try:
        from recognition.config import get_settings
        from recognition.infrastructure.embeddings.face_pipeline_adapter import (
            get_shared_face_pipeline_runtime,
        )

        # Face-pipeline readiness only; pass configured thresholds so readiness
        # and serve share the same runtime cache key (profile/models_dir/top-k).
        fp = get_settings().face_pipeline
        get_shared_face_pipeline_runtime(
            profile="face_pipeline",
            models_dir=root,
            score_threshold=float(fp.score_threshold),
            nms_threshold=float(fp.nms_threshold),
            top_k=int(fp.top_k),
        )
    except Exception as exc:
        return CheckResult(
            "model_cache",
            HealthStatus.UNHEALTHY,
            f"runtime unavailable: {exc}",
        )
    return CheckResult("model_cache", HealthStatus.OK, f"verified: yunet+sface @ {root}")


def reset_face_pipeline_verify_cache_for_tests() -> None:
    """Clear the process-local verify cache (unit tests only)."""
    with _FACE_PIPELINE_VERIFY_CACHE_LOCK:
        _FACE_PIPELINE_VERIFY_CACHE.clear()


def aggregate_status(checks: list[CheckResult]) -> HealthStatus:
    """Worst-case aggregation: any UNHEALTHY wins, else any DEGRADED, else OK."""
    if any(c.status is HealthStatus.UNHEALTHY for c in checks):
        return HealthStatus.UNHEALTHY
    if any(c.status is HealthStatus.DEGRADED for c in checks):
        return HealthStatus.DEGRADED
    return HealthStatus.OK
