"""Health probe helpers for the recognition service.

Dep checks live here (not in the HTTP router) so /ready and /health/detailed
(Slice 2.5) can share a single source of truth. The helpers are plain async
functions — the HTTP layer owns wiring them to FastAPI dependencies.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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

# Process-local eager verify cache for face_pipeline readiness ([EMB-05]).
# Keyed by absolute model path; value is last full-verify outcome.
# Lock required once verify may run off the event loop (S3CR-05).
_FACE_PIPELINE_VERIFY_CACHE: dict[str, ModelVerifyOutcome] = {}
_FACE_PIPELINE_VERIFY_CACHE_LOCK = threading.Lock()


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


async def check_database(session: AsyncSession | None) -> CheckResult:
    """Reuse the session dependency's built-in SELECT 1 probe.

    `get_observability_session` already runs SELECT 1 before yielding a live
    session and yields None when the probe fails. A second SELECT 1 here would
    double DB load on every /ready hit (BR-03) without adding signal.
    """
    if session is None:
        return CheckResult("database", HealthStatus.UNHEALTHY, "connection_unavailable")
    return CheckResult("database", HealthStatus.OK, "reachable")


def check_breaker(breaker: SessionDependencyCircuitBreaker) -> CheckResult:
    """An OPEN breaker means DB checkout is blocked — /ready fails (BR-02).

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


def _cached_verify_outcome(name: str, *, models_dir: Path) -> ModelVerifyOutcome:
    """Return last verified outcome, re-running full sha256 on miss or mtime/size drift.

    Never reports OK for bytes that have not passed ``load_verified_model`` at
    least once in this process ([EMB-05], [DRIFT-02]).
    """
    entry = MODEL_MANIFEST[name]
    path = models_dir / entry.file_name
    cache_key = str(path.resolve()) if path.exists() else str(path)

    with _FACE_PIPELINE_VERIFY_CACHE_LOCK:
        cached = _FACE_PIPELINE_VERIFY_CACHE.get(cache_key)
        if path.is_file():
            st = path.stat()
            if cached is not None and cached.mtime_ns == st.st_mtime_ns and cached.size == st.st_size:
                return cached
        elif cached is not None and not cached.ok and cached.mtime_ns == 0 and cached.size == 0:
            # Missing file already verified-failed with no stat; re-check so recovery works.
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
