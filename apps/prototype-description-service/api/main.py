import logging
import os
import subprocess
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import Depends, FastAPI, Response
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.cors import CORSMiddleware

from api.logging_config import configure_logging
from db.session import get_pool_stats
from recognition.application.health import (
    aggregate_status,
    check_breaker,
    check_database,
    check_model_cache,
)
from recognition.application.scan.capability import (
    embedding_runtime_health_payload,
    read_embedding_runtime_capability,
)
from recognition.config.security import (
    get_security_settings,
    validate_admin_config,
    validate_production_security,
)
from recognition.config.settings import RecognitionSettings
from recognition.interface_adapters.http import deps as http_deps
from recognition.interface_adapters.http import router as recognition_router
from recognition.interface_adapters.http.deps.auth import require_auth
from recognition.interface_adapters.http.deps.circuit_breaker import (
    get_or_create_session_dependency_circuit_breaker,
    initialize_session_dependency_circuit_breaker,
)
from recognition.interface_adapters.http.deps.clustering_circuit_breaker import (
    initialize_clustering_circuit_breaker,
)
from recognition.interface_adapters.http.exception_handlers import register_exception_handlers
from recognition.interface_adapters.http.middleware.correlation import CorrelationIdMiddleware
from recognition.interface_adapters.http.middleware.metrics import (
    MetricsMiddleware,
    get_default_metrics,
)
from recognition.interface_adapters.http.middleware.upload_size import UploadSizeLimitMiddleware
from recognition.observability.curation_refresh_metrics import get_default_curation_refresh_metrics
from roster.interface_adapters.http.curation_router import router as roster_curation_router
from scene.interface_adapters.http.router import router as scene_router
from shared.health import HealthStatus

# Configure logging to show diagnostic output
configure_logging("INFO")

logger = logging.getLogger(__name__)


def _get_git_info() -> tuple[str, str]:
    """Get the current git commit hash and branch, or 'unknown' if not available."""
    try:
        commit_result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        commit = commit_result.stdout.strip() if commit_result.returncode == 0 else "unknown"

        branch_result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        branch = branch_result.stdout.strip() if branch_result.returncode == 0 else "unknown"

        return commit, branch
    except Exception:
        return "unknown", "unknown"


def _resolve_version_commit_sha() -> str:
    """Prefer the build-arg SHA baked into the image; fall back to git in dev."""
    env_sha = os.environ.get("APP_GIT_COMMIT_SHA", "").strip()
    if env_sha:
        return env_sha
    commit, _ = _get_git_info()
    return commit


def _resolve_version_build_time() -> str:
    return os.environ.get("APP_BUILD_TIME", "").strip() or "unknown"


def _log_startup_info() -> None:
    """Log git commit and branch info at startup."""
    # Use db.startup namespace to pass the RecognitionFilter
    startup_logger = logging.getLogger("db.startup")
    # E15-3a-BR-20: prefer the build-arg APP_GIT_COMMIT_SHA baked into the
    # image (same source /version uses). Inside the Docker container `git
    # rev-parse` has no `.git` dir and returns "unknown", so the old banner
    # read "Git: unknown (unknown)" even though /version reported the real
    # SHA. Branch still comes from _get_git_info for dev ergonomics.
    commit = _resolve_version_commit_sha() or "unknown"
    _, branch = _get_git_info()

    # Get port from environment (set by start script, defaults to 8000)
    port = os.environ.get("PORT", "8000")
    host = os.environ.get("HOST", "127.0.0.1")

    startup_logger.info("=== Application Startup ===")
    startup_logger.info("Git: %s (%s)", commit, branch)
    startup_logger.info("Listening on http://%s:%s", host, port)


def _check_dev_key_guard() -> None:
    """Fail-closed guard: refuse to start production with dev_api_keys configured.

    Reuses the existing RECOGNITION_RUNTIME_MODE signal; no new env var.
    """
    recognition_settings = RecognitionSettings()
    security_settings = get_security_settings()
    if not security_settings.dev_api_keys:
        return
    if recognition_settings.runtime_mode == "production":
        raise RuntimeError(
            "Refusing to start: RECOGNITION_RUNTIME_MODE=production and dev_api_keys is non-empty "
            "(RECOGNITION_ALLOWED_API_KEYS). Dev keys must never ship to production."
        )
    logger.warning(
        "dev_api_keys is configured (RECOGNITION_ALLOWED_API_KEYS); allowed because runtime_mode=%s",
        recognition_settings.runtime_mode,
    )


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # WBUX-4 INT-02: the bulk describe worker runs in-process, so a prior restart
    # can strand a run non-terminal (the frontend would then poll it forever).
    # Reclaim orphaned runs to a terminal state before serving. Best-effort:
    # never block boot on a reclaim failure.
    try:
        from db.session import async_session_factory
        from scene.application.describe_run_repository import run_startup_reclaim

        reclaimed = await run_startup_reclaim(async_session_factory)
        if reclaimed:
            logging.getLogger("db.startup").info(
                "Reclaimed %d interrupted describe run(s) at startup", reclaimed
            )
    except Exception:  # noqa: BLE001 - startup reclaim is best-effort
        logging.getLogger("db.startup").warning(
            "describe-run startup reclaim failed", exc_info=True
        )
    yield


def create_app() -> FastAPI:
    # Log version info at startup
    _log_startup_info()
    _check_dev_key_guard()

    # Refuse to boot if production is configured with dev-only plaintext API keys.
    validate_production_security()

    app = FastAPI(
        title="Prototype Description Service",
        version="0.1.0",
        description="Experimental rewrite scaffolding for the description service.",
        lifespan=_lifespan,
    )

    security_settings = get_security_settings()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=security_settings.allowed_origins,
        allow_credentials=False,
        allow_origin_regex=None,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "X-Api-Key", "X-Tenant-ID", "Content-Type"],
        max_age=600,
    )
    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(MetricsMiddleware)
    # E15-11: enforce body-size cap on the multipart upload endpoint before
    # FastAPI buffers the body. Path-scoped so the JSON variant on the same
    # base path is unaffected.
    recognition_settings = RecognitionSettings()
    app.add_middleware(
        UploadSizeLimitMiddleware,
        max_bytes=recognition_settings.max_upload_bytes,
        paths={"/recognition/analyze/multipart", "/scene/describe/multipart"},
    )

    initialize_session_dependency_circuit_breaker(app)
    initialize_clustering_circuit_breaker(app)

    app.include_router(recognition_router, prefix="/recognition")
    app.include_router(roster_curation_router, prefix="/roster")
    app.include_router(scene_router, prefix="/scene")

    # Env-gated, fail-closed operator admin surface. Mounted only when explicitly
    # enabled; validate_admin_config refuses to start on a missing/short token (or
    # production without the tailnet-bound ack), and the env/DSN guard refuses a
    # production runtime pointed at a local DB. Nothing is mounted when disabled.
    if security_settings.admin_enabled:
        from recognition.interface_adapters.http.routers.admin import (
            admin_router,
            assert_admin_env_dsn,
        )

        validate_admin_config(security_settings, runtime_mode=recognition_settings.runtime_mode)
        assert_admin_env_dsn(runtime_mode=recognition_settings.runtime_mode)
        app.include_router(admin_router, prefix="/admin")

    register_exception_handlers(app)

    register_health_probes(app)
    register_metrics_route(app)
    register_version_route(app)

    return app


def register_version_route(app: FastAPI) -> None:
    """Unauthenticated identity probe (E15-3a-BR-03).

    Operators and the WordPress plugin need the deployed commit SHA without
    grepping OCI logs. `/version` is liveness-cheap (env lookups only) and
    must stay unauthenticated so clients can compare the deployed SHA against
    a minimum-supported-commit constant *before* authenticating.
    """
    commit_sha = _resolve_version_commit_sha() or "unknown"
    build_time = _resolve_version_build_time()

    @app.get("/version", summary="Deployed identity (E15-3a-BR-03)")
    def version() -> dict[str, str]:
        return {
            "commit_sha": commit_sha,
            "build_time": build_time,
            "version": app.version,
        }


def register_metrics_route(app: FastAPI) -> None:
    """Attach auth-gated /metrics route that exposes Prometheus exposition.

    Registered as a FastAPI route (not a Starlette ASGI sub-mount) so the
    require_auth dependency runs; mounting make_asgi_app() would bypass
    FastAPI deps and leave /metrics unauthenticated (PA-05, PR-02).
    """
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

    metrics = get_default_metrics()
    get_default_curation_refresh_metrics(metrics.registry)

    @app.get("/metrics", summary="Prometheus metrics (PA-05 / Slice 3a)")
    def metrics_endpoint(_: object = Depends(require_auth)) -> Response:
        return Response(
            content=generate_latest(metrics.registry),
            media_type=CONTENT_TYPE_LATEST,
        )


def register_health_probes(app: FastAPI, *, model_cache_dir: Path | None = None) -> None:
    """Attach root /health (liveness) + /ready (deps) to the given app.

    Extracted from create_app so tests can mount the probes onto a bare
    FastAPI instance without spinning up every subsystem router.
    """
    settings = RecognitionSettings()
    cache_dir = model_cache_dir or settings.insightface.model_cache_dir
    model_name = settings.insightface.model_name

    commit_sha = _resolve_version_commit_sha() or "unknown"

    @app.get("/health", summary="Liveness probe (PR-01)")
    def liveness() -> dict[str, str]:
        # Liveness is process-up only: no DB, breaker, or disk I/O. The Caddy
        # active probe hits this at 10s so it must never block on a dependency.
        # commit_sha is a static identity string resolved at registration time.
        return {
            "status": HealthStatus.OK.value,
            "timestamp": datetime.now(UTC).isoformat(),
            "commit_sha": commit_sha,
        }

    @app.get("/ready", summary="Readiness probe (PR-01)")
    async def readiness(
        response: Response,
        session: AsyncSession | None = Depends(http_deps.get_observability_session),
    ) -> dict[str, object]:
        breaker = get_or_create_session_dependency_circuit_breaker(app)
        checks = [
            await check_database(session),
            check_breaker(breaker),
            check_model_cache(cache_dir, model_name=model_name),
        ]
        status = aggregate_status(checks)
        # UNHEALTHY flips the HTTP code so load balancers pull the pod.
        # OK and DEGRADED both stay 200 — degraded still serves traffic.
        response.status_code = 503 if status is HealthStatus.UNHEALTHY else 200
        return {
            "status": status.value,
            "checks": [c.to_dict() for c in checks],
            "timestamp": datetime.now(UTC).isoformat(),
        }

    @app.get("/health/detailed", summary="Operator diagnostic (PA-01 / Slice 2.5)")
    async def health_detailed(
        _: object = Depends(require_auth),
        session: AsyncSession | None = Depends(http_deps.get_observability_session),
    ) -> dict[str, object]:
        # Auth-gated diagnostic surface. Returns pool stats + breaker state +
        # model-cache inventory for operators; never hit by load-balancer
        # probes. Shares aggregator + probes with /ready so the two stay in
        # sync without duplicate implementations.
        breaker = get_or_create_session_dependency_circuit_breaker(app)
        db_check = await check_database(session)
        breaker_check = check_breaker(breaker)
        mc_check = check_model_cache(cache_dir, model_name=model_name)
        status = aggregate_status([db_check, breaker_check, mc_check])
        bundle = cache_dir / model_name
        bundle_files = len(list(bundle.glob("*.onnx"))) if bundle.is_dir() else 0
        embedding_runtime = {
            "available": False,
            "reason": "database unavailable",
            "heartbeat_age_seconds": None,
        }
        if session is not None:
            try:
                embedding_capability = await read_embedding_runtime_capability(session)
                embedding_runtime = embedding_runtime_health_payload(embedding_capability)
            except Exception:
                embedding_runtime = {
                    "available": False,
                    "reason": "capability read failed",
                    "heartbeat_age_seconds": None,
                }
        return {
            "status": status.value,
            "timestamp": datetime.now(UTC).isoformat(),
            "pool_stats": get_pool_stats(),
            "breaker_state": breaker.state.value,
            "model_cache": {
                "model_name": model_name,
                "cache_dir": str(cache_dir),
                "bundle_files": bundle_files,
                "status": mc_check.status.value,
                "detail": mc_check.detail,
            },
            "embedding_runtime": embedding_runtime,
        }


app = create_app()
