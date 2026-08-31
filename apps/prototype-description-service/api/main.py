import asyncio
import logging
import os
import subprocess
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path

from fastapi import Depends, FastAPI, Response
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.cors import CORSMiddleware

from api.logging_config import configure_logging
from db.session import get_pool_stats
from recognition.application.health import (
    CheckResult,
    aggregate_status,
    check_active_embedding_model,
    check_breaker,
    check_database,
    check_face_pipeline_models,
    check_model_cache,
)
from recognition.application.scan.capability import (
    embedding_runtime_health_payload,
    read_embedding_runtime_capability,
)
from recognition.config.security import (
    get_security_settings,
    validate_admin_config,
    validate_required_secrets,
)
from recognition.config.settings import RecognitionSettings
from recognition.infrastructure.face_pipeline.provenance import MODEL_MANIFEST
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
from scene.config.settings import DescriptionSettings
from scene.interface_adapters.http.router import router as scene_router
from shared.health import HealthStatus
from shared.image_variant import (
    IMAGE_VARIANT_ARTIFACT,
    IMAGE_VARIANT_ENV,
    ImageVariant,
)
from shared.secrets import validate_oci_vault_boot

# Configure logging to show diagnostic output
configure_logging("INFO")

logger = logging.getLogger(__name__)

_LOAD_SNAPSHOT_REFRESH_REARM_SECONDS = 1.0


async def _supervise_load_snapshot_refresher(session_factory) -> None:
    """Re-arm an unexpectedly stopped refresher while the API remains live."""
    while True:
        try:
            from scene.application.describe_load import refresh_load_snapshot_loop

            await refresh_load_snapshot_loop(session_factory)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - keep freshness armed after a crash
            logger.error("describe load snapshot refresher crashed; re-arming", exc_info=True)
        else:
            logger.error("describe load snapshot refresher stopped unexpectedly; re-arming")
        # Avoid a tight restart loop if an import or implementation regression
        # makes the refresher fail immediately.
        await asyncio.sleep(_LOAD_SNAPSHOT_REFRESH_REARM_SECONDS)


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


# Canonical path + labels live in scripts.verify_vlm_cache (sr-007). Module-level
# alias keeps the historical test monkeypatch surface (api.main._IMAGE_VARIANT_ARTIFACT).
_IMAGE_VARIANT_ARTIFACT = IMAGE_VARIANT_ARTIFACT


def _resolve_image_variant() -> str:
    """Build-immutable image variant from ``/app/.image-variant`` (rg-015).

    The Dockerfile bakes ``ImageVariant`` labels into that file at image build.
    Compose ``env_file`` can override ``ACX_IMAGE_VARIANT`` ENV, so ENV alone
    fails open (a VLM image can report as recognition). Source of truth is the
    artifact; a non-empty env claim that disagrees fails closed. When the
    artifact is absent (local dev / unit tests), fall back to env then
    ``ImageVariant.RECOGNITION``. Read/OSError and invalid bake values fail
    closed (match entrypoint) — never report recognition when the bake is
    unreadable or corrupt. Labels are the ``ImageVariant`` enum members only
    (sr-007) — do not reintroduce bare string literals here.
    """
    env_claim = os.environ.get(IMAGE_VARIANT_ENV, "").strip()
    baked = ""
    try:
        if _IMAGE_VARIANT_ARTIFACT.is_file():
            baked = _IMAGE_VARIANT_ARTIFACT.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError(f"cannot read baked image variant at {_IMAGE_VARIANT_ARTIFACT}: {exc}") from exc
    if baked:
        valid = {member.value for member in ImageVariant}
        if baked not in valid:
            raise RuntimeError(f"invalid baked image variant {baked!r} at {_IMAGE_VARIANT_ARTIFACT}")
        if env_claim and env_claim != baked:
            raise RuntimeError(
                f"ACX_IMAGE_VARIANT={env_claim!r} disagrees with baked {baked!r} at {_IMAGE_VARIANT_ARTIFACT}"
            )
        return baked
    return env_claim or ImageVariant.RECOGNITION.value


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


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # WBUX-4 INT-02: the bulk describe worker runs in-process, so a prior restart
    # can strand a run non-terminal (the frontend would then poll it forever).
    # Reclaim orphaned runs to a terminal state before serving. Best-effort:
    # never block boot on a reclaim failure.
    # VLM-5 Slice 4 order after reclaim: retention purge → initial load snapshot.
    # No admission-counter seeding — process-local gate starts at 0 (design (b)).
    try:
        from db.session import async_session_factory
        from scene.application.describe_run_repository import run_startup_reclaim

        reclaimed = await run_startup_reclaim(async_session_factory)
        if reclaimed:
            logging.getLogger("db.startup").info("Reclaimed %d interrupted describe run(s) at startup", reclaimed)
    except Exception:  # noqa: BLE001 - startup reclaim is best-effort
        logging.getLogger("db.startup").warning("describe-run startup reclaim failed", exc_info=True)

    # VLM-5 design (d): purge expired terminal single runs after reclaim.
    # Dedicated RLS-bypassed session (design (c) session discipline) [DIAG-02].
    try:
        from db.session import async_session_factory
        from scene.application.describe_run_repository import run_startup_retention_purge

        purged = await run_startup_retention_purge(async_session_factory)
        if purged:
            logging.getLogger("db.startup").info("Purged %d expired single describe run(s) at startup", purged)
    except Exception:  # noqa: BLE001 - startup retention purge is best-effort
        logging.getLogger("db.startup").warning("describe-run retention purge failed", exc_info=True)

    # VLM-5 design (c): initial DB-derived load snapshot for the GPU idle reaper.
    try:
        from db.session import async_session_factory
        from scene.application.describe_load import run_startup_load_snapshot

        await run_startup_load_snapshot(async_session_factory)
    except Exception:  # noqa: BLE001 - startup load snapshot is best-effort
        logging.getLogger("db.startup").warning("describe load snapshot write failed at startup", exc_info=True)

    # GPUW-1: enqueue/terminal writes leave the dump stale while work is quiet.
    # Refresh well inside the reaper's 120s stale guard so an empty snapshot can
    # remain authoritative long enough for stop-on-drain to fire.
    refresh_task: asyncio.Task[None] | None = None
    try:
        from db.session import async_session_factory

        refresh_task = asyncio.create_task(_supervise_load_snapshot_refresher(async_session_factory))
    except Exception:  # noqa: BLE001 - the API must still boot if task setup fails
        logging.getLogger("db.startup").warning("describe load snapshot refresher failed to start", exc_info=True)

    try:
        yield
    finally:
        if refresh_task is not None:
            refresh_task.cancel()
            # Refresher failures are handled inside the supervisor and must not
            # turn an otherwise-clean application shutdown into a lifespan
            # failure.
            with suppress(asyncio.CancelledError, Exception):
                await refresh_task


def create_app() -> FastAPI:
    # Log version info at startup
    _log_startup_info()

    # RES-13: under oci_vault, eagerly fetch required secrets before binding a
    # port. Unreachable Vault / auth failure / missing secret → VaultBootError
    # (no env fallback, no partial serve). No-op for the env backend.
    validate_oci_vault_boot()

    # Refuse to boot in production when required secrets are unset/dev-default (rg-008).
    validate_required_secrets()

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
        paths={
            "/recognition/analyze/multipart",
            "/scene/describe/multipart",
            "/scene/describe/async",
        },
    )

    initialize_session_dependency_circuit_breaker(app)
    initialize_clustering_circuit_breaker(app)

    app.include_router(recognition_router, prefix="/recognition")
    app.include_router(roster_curation_router, prefix="/roster")
    app.include_router(scene_router, prefix="/scene")

    # DS-2: public demo slug resolve at root (GET /x/{slug}). Not under
    # /recognition — that surface carries require_auth on analyze children.
    from recognition.interface_adapters.http.routers.demo import router as demo_router

    app.include_router(demo_router)

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

    ``image_variant`` distinguishes recognition vs VLM images that share a
    commit SHA (RA-07 / wave3 identity); value is the baked ``/app/.image-variant``.
    """
    commit_sha = _resolve_version_commit_sha() or "unknown"
    build_time = _resolve_version_build_time()
    image_variant = _resolve_image_variant()

    @app.get("/version", summary="Deployed identity (E15-3a-BR-03)")
    def version() -> dict[str, str]:
        return {
            "commit_sha": commit_sha,
            "build_time": build_time,
            "version": app.version,
            "image_variant": image_variant,
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

    Model-cache probe is profile-aware ([OBS-08]): insightface uses the
    existing onnx-count check; face_pipeline uses eager sha256 verification
    with mtime/size drift re-verify ([EMB-05]).

    Settings are constructed once at registration (S3CR-06); only the profile
    env key is re-read per probe (cheap). Invalid profile yields aggregated
    UNHEALTHY 503 on /ready (S3CR-04); create_app still hard-fails on boot.
    """
    commit_sha = _resolve_version_commit_sha() or "unknown"
    # Baked at image build (/app/.image-variant); resolve once like commit_sha.
    image_variant = _resolve_image_variant()
    # Hoist full settings parse once; close over cache/model paths (S3CR-06).
    settings = RecognitionSettings()
    description_settings = DescriptionSettings()
    description_adapter = description_settings.profile.value
    insightface_cache_dir = model_cache_dir or settings.insightface.model_cache_dir
    insightface_model_name = settings.insightface.model_name
    face_pipeline_models_dir = settings.face_pipeline.resolved_models_dir
    _allowed_profiles = frozenset({"insightface", "face_pipeline"})

    def _current_profile() -> str:
        """Cheap per-probe profile re-read (env only; no full settings re-parse)."""
        raw = os.environ.get("RECOGNITION_FACE_PIPELINE_PROFILE", "insightface").strip()
        return raw or "insightface"

    async def _model_probe() -> tuple[CheckResult, Path, str]:
        """Return (CheckResult, cache_dir_for_detail, model_label).

        face_pipeline verification runs off the event loop (S3CR-03).
        Invalid profile → UNHEALTHY CheckResult (S3CR-04), not HTTP 500.
        """
        profile = _current_profile()
        if profile not in _allowed_profiles:
            return (
                CheckResult(
                    "model_cache",
                    HealthStatus.UNHEALTHY,
                    f"invalid face_pipeline profile: {profile}",
                ),
                insightface_cache_dir,
                insightface_model_name,
            )
        if profile == "face_pipeline":
            mc_check = await asyncio.to_thread(check_face_pipeline_models, face_pipeline_models_dir)
            return mc_check, face_pipeline_models_dir, "yunet+sface"
        return (
            check_model_cache(insightface_cache_dir, model_name=insightface_model_name),
            insightface_cache_dir,
            insightface_model_name,
        )

    @app.get("/health", summary="Liveness probe (PR-01)")
    def liveness() -> dict[str, str]:
        # Liveness is process-up only: no DB, breaker, or disk I/O. The Caddy
        # active probe hits this at 10s so it must never block on a dependency.
        # commit_sha / image_variant are static identity strings resolved at
        # registration time from bake artifact + env (rg-015).
        return {
            "status": HealthStatus.OK.value,
            "timestamp": datetime.now(UTC).isoformat(),
            "commit_sha": commit_sha,
            "image_variant": image_variant,
        }

    @app.get("/ready", summary="Readiness probe (PR-01)")
    async def readiness(
        response: Response,
        session: AsyncSession | None = Depends(http_deps.get_observability_session),
    ) -> dict[str, object]:
        breaker = get_or_create_session_dependency_circuit_breaker(app)
        mc_check, _, _ = await _model_probe()
        checks = [
            await check_database(session),
            check_breaker(breaker),
            mc_check,
            check_active_embedding_model(),
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
        """Auth-gated diagnostic surface.

        Contract expansion (S3CR-07): ``model_cache.profile`` is additive so
        operators can see the active face_pipeline profile without a second
        settings parse (reuses registration-time paths + cheap env profile).

        ``description_adapter`` is the active caption producer
        (``DescriptionSettings.profile``), not the face_pipeline profile.
        Resolved once at registration from the settings object; not re-read
        from the environment per request.
        """
        # Returns pool stats + breaker state + model-cache inventory for
        # operators; never hit by load-balancer probes. Shares aggregator +
        # probes with /ready so the two stay in sync without duplicates.
        breaker = get_or_create_session_dependency_circuit_breaker(app)
        db_check = await check_database(session)
        breaker_check = check_breaker(breaker)
        mc_check, cache_dir, model_name = await _model_probe()
        embedding_model_check = check_active_embedding_model(verbose=True)
        status = aggregate_status([db_check, breaker_check, mc_check, embedding_model_check])
        profile = _current_profile()
        if profile == "face_pipeline":
            bundle_files = sum(
                1 for name in ("yunet", "sface") if (cache_dir / MODEL_MANIFEST[name].file_name).is_file()
            )
        else:
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
                "profile": profile,
            },
            "embedding_runtime": embedding_runtime,
            "description_adapter": description_adapter,
        }


app = create_app()
