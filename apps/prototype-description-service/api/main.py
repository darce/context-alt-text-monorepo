import asyncio
import logging
import math
import os
import socket
import subprocess
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, suppress
from dataclasses import replace
from datetime import UTC, datetime
from enum import StrEnum
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlparse

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
    check_disk_headroom,
    check_face_pipeline_models,
    check_model_cache,
    check_model_space,
    disk_headroom_probe_failure,
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
from recognition.infrastructure.face_pipeline.model_space import ModelSpace, UnhandledModelSpaceError
from recognition.infrastructure.face_pipeline.provenance import MODEL_MANIFEST, PENDING_OPERATOR_FETCH
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
from scene.application.seeded_adapter import SeededDescriptionAdapter
from scene.config.profiles import DescriptionProfile, ProfileSpec, get_profile_spec
from scene.config.settings import _parse_allowlist
from scene.domain.description import DescriptionAdapterKind
from scene.interface_adapters.http import deps as scene_http_deps
from scene.interface_adapters.http.deps import (
    _DEFAULT_GPU_ENDPOINT_ALLOWLIST,
    _hostname_matches_allowlist,
)
from scene.interface_adapters.http.router import router as scene_router
from scene.interface_adapters.http.routers.gpu import router as gpu_router
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


_LOAD_SNAPSHOT_REFRESH_REARM_MAX_SECONDS = 60.0

_DEFAULT_HEALTH_DB_TIMEOUT_SECONDS = 2.0

_ENDPOINT_PRIVACY_TTL_SECONDS = 60.0

_ENDPOINT_PRIVACY_RESOLVE_TIMEOUT_SECONDS = 0.5


class AdapterReadinessReason(StrEnum):
    """Machine-readable /health/detailed description_adapter.reason values (sr-007)."""

    PROFILE_UNAVAILABLE = "profile_unavailable"
    VLM_DEPENDENCIES_MISSING = "vlm_dependencies_missing"
    ENDPOINT_UNCONFIGURED = "endpoint_unconfigured"
    ENDPOINT_INVALID_URL = "endpoint_invalid_url"
    ENDPOINT_NOT_ALLOWLISTED = "endpoint_not_allowlisted"
    ENDPOINT_NOT_PRIVATE = "endpoint_not_private"
    ENDPOINT_RESOLUTION_PENDING = "endpoint_resolution_pending"


class EndpointPrivacyCache:
    """Bounded single-flight cache of GPU endpoint privacy (CARD-09, DIAGNO-M-11)."""

    TTL_SECONDS = _ENDPOINT_PRIVACY_TTL_SECONDS
    RESOLVE_TIMEOUT_SECONDS = _ENDPOINT_PRIVACY_RESOLVE_TIMEOUT_SECONDS

    def __init__(self) -> None:
        self._guard = asyncio.Lock()
        self._host: str | None = None
        self._value: bool | None = None
        self._checked_at: float | None = None
        self._last_attempt_at: float | None = None
        self._in_flight: asyncio.Future[None] | None = None
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="endpoint-privacy")

    def seed(
        self,
        *,
        host: str,
        value: bool | None,
        checked_at: float | None,
        last_attempt_at: float | None = None,
    ) -> None:
        """Install a cached resolution result (tests + timeout fallback)."""
        self._host = host
        self._value = value
        self._checked_at = checked_at
        self._last_attempt_at = last_attempt_at
        self._in_flight = None

    def snapshot(self, host: str) -> tuple[bool | None, float | None]:
        if self._host != host:
            return None, None
        return self._value, self._checked_at

    def _resolve_blocking(self, host: str) -> None:
        try:
            infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        except socket.gaierror:
            return
        except Exception:
            logger.warning("endpoint privacy resolution failed for %s", host, exc_info=True)
            return
        if not infos:
            self._value = False
            self._checked_at = time.time()
            self._host = host
            return
        value = True
        for info in infos:
            sockaddr = info[4]
            try:
                addr = ip_address(sockaddr[0])
            except ValueError:
                value = False
                break
            if not (addr.is_private or addr.is_loopback):
                value = False
                break
        self._value = bool(value)
        self._checked_at = time.time()
        self._host = host

    async def refresh(self, host: str) -> tuple[bool | None, float | None]:
        now = time.time()
        async with self._guard:
            if host != self._host:
                self._host = host
                self._value = None
                self._checked_at = None
                self._last_attempt_at = None
                self._in_flight = None
            in_flight = self._in_flight
            if in_flight is not None and in_flight.done():
                in_flight = None
                self._in_flight = None
            fresh_hit = self._checked_at is not None and (now - self._checked_at) < self.TTL_SECONDS
            can_attempt = self._last_attempt_at is None or (now - self._last_attempt_at) >= self.TTL_SECONDS
            if not fresh_hit and in_flight is None and can_attempt:
                self._last_attempt_at = now
                in_flight = asyncio.get_running_loop().run_in_executor(self._pool, self._resolve_blocking, host)
                self._in_flight = in_flight
            should_wait = in_flight is not None and not in_flight.done() and not fresh_hit

        if should_wait and in_flight is not None:
            await self._await_resolution(in_flight)
        return self.snapshot(host)

    async def _await_resolution(self, in_flight: asyncio.Future[None]) -> None:
        """Bound the health wait without cancelling the executor job.

        ``asyncio.wait_for`` on ``run_in_executor`` waits out the worker on
        timeout (the thread is not cancellable). Wait on an Event instead so
        the handler can return in RESOLVE_TIMEOUT_SECONDS (CARD-09).
        """
        if in_flight.done():
            return
        finished = asyncio.Event()
        in_flight.add_done_callback(lambda _fut: finished.set())
        if in_flight.done():
            return
        try:
            await asyncio.wait_for(finished.wait(), timeout=self.RESOLVE_TIMEOUT_SECONDS)
        except TimeoutError:
            return
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("endpoint privacy resolution wait failed", exc_info=True)


_endpoint_privacy_cache = EndpointPrivacyCache()


def _endpoint_hostname(endpoint_url: str | None) -> str | None:
    parsed = _parse_endpoint_url(endpoint_url)
    return parsed.hostname if parsed is not None else None


def _parse_endpoint_url(endpoint_url: str | None):
    if not endpoint_url:
        return None
    try:
        parsed = urlparse(endpoint_url)
        # Accessing ``port`` is validation: urllib.parse defers malformed-port
        # errors until this property is read.
        _ = parsed.port
    except ValueError:
        return None
    return parsed


def _gpu_endpoint_url_is_valid(endpoint_url: str) -> bool:
    parsed = _parse_endpoint_url(endpoint_url)
    return parsed is not None and parsed.scheme in {"http", "https"} and parsed.hostname is not None


def _endpoint_is_allowlisted(host: str, allowlist: tuple[str, ...]) -> bool:
    try:
        addr = ip_address(host)
    except ValueError:
        return _hostname_matches_allowlist(host, allowlist)
    return addr.is_private or addr.is_loopback


def wire_model_id(spec: ProfileSpec) -> str | None:
    """Wire identity the GPU adapter stamps; otherwise the profile model_id."""
    if spec.profile is DescriptionProfile.SEEDED:
        return SeededDescriptionAdapter.model_id
    if spec.adapter_kind is DescriptionAdapterKind.GPU and spec.model_revision:
        return f"{spec.hub_repo or spec.model_id}@{spec.model_revision}"
    return spec.model_id


def _wire_model_version(spec: ProfileSpec, model_id: str | None) -> str | None:
    """Return the version stamped by the active adapter without loading settings."""
    if spec.profile is DescriptionProfile.SEEDED:
        return os.environ.get("ACX_DESCRIPTION_MODEL_VERSION", "1")
    return None if model_id is None else spec.model_version


def _resolve_description_profile() -> DescriptionProfile:
    """Validate the configured description profile before registering routes."""
    raw = os.environ.get("ACX_DESCRIPTION_ADAPTER", DescriptionProfile.SEEDED.value)
    try:
        return DescriptionProfile(raw)
    except ValueError as exc:
        allowed = ", ".join(profile.value for profile in DescriptionProfile)
        raise ValueError(f"ACX_DESCRIPTION_ADAPTER must be one of: {allowed} (got {raw!r})") from exc


async def _description_adapter_readiness(profile: DescriptionProfile) -> dict[str, object]:
    """Per-request GPU adapter readiness; DNS never runs inline on the loop."""
    spec = get_profile_spec(profile)
    endpoint_url = os.environ.get("ACX_GPU_ENDPOINT_URL") or None
    endpoint_configured = bool(endpoint_url)
    url_valid = endpoint_url is not None and _gpu_endpoint_url_is_valid(endpoint_url)
    host = _endpoint_hostname(endpoint_url) if url_valid else None
    parsed_allowlist = _parse_allowlist(os.environ.get("ACX_GPU_ENDPOINT_ALLOWLIST"))
    effective_allowlist = parsed_allowlist or _DEFAULT_GPU_ENDPOINT_ALLOWLIST
    endpoint_allowlisted = host is not None and _endpoint_is_allowlisted(host, effective_allowlist)
    endpoint_private: bool | None = None
    checked_at: float | None = None
    may_resolve = spec.available and spec.adapter_kind is DescriptionAdapterKind.GPU and url_valid
    if may_resolve and host is not None and endpoint_allowlisted:
        endpoint_private, checked_at = await _endpoint_privacy_cache.refresh(host)
    elif may_resolve and host is not None:
        endpoint_private, checked_at = _endpoint_privacy_cache.snapshot(host)
    now = time.time()
    fresh = checked_at is not None and (now - checked_at) < EndpointPrivacyCache.TTL_SECONDS
    model_id = wire_model_id(spec)
    model_version = _wire_model_version(spec, model_id)
    vlm_dependencies_missing = (
        spec.available
        and spec.adapter_kind is DescriptionAdapterKind.LOCAL_CPU
        and bool(scene_http_deps._missing_vlm_dependencies())
    )
    if not spec.available:
        usable = False
        reason: str | None = AdapterReadinessReason.PROFILE_UNAVAILABLE.value
    elif vlm_dependencies_missing:
        usable = False
        reason = AdapterReadinessReason.VLM_DEPENDENCIES_MISSING.value
    elif spec.adapter_kind is not DescriptionAdapterKind.GPU:
        usable = True
        reason = None
    elif not endpoint_configured:
        usable = False
        reason = AdapterReadinessReason.ENDPOINT_UNCONFIGURED.value
    elif not url_valid:
        usable = False
        reason = AdapterReadinessReason.ENDPOINT_INVALID_URL.value
    elif not endpoint_allowlisted:
        usable = False
        reason = AdapterReadinessReason.ENDPOINT_NOT_ALLOWLISTED.value
    elif endpoint_private is False:
        usable = False
        reason = AdapterReadinessReason.ENDPOINT_NOT_PRIVATE.value
    elif not (endpoint_private is True and fresh):
        usable = False
        reason = AdapterReadinessReason.ENDPOINT_RESOLUTION_PENDING.value
    else:
        usable = True
        reason = None
    return {
        "profile": spec.profile.value,
        "kind": spec.adapter_kind.value,
        "endpoint_configured": endpoint_configured,
        "endpoint_allowlisted": endpoint_allowlisted,
        "endpoint_private": endpoint_private,
        "checked_at": checked_at,
        "fresh": fresh,
        "usable": usable,
        "reason": reason,
        "model_id": model_id,
        "model_version": model_version,
    }


def _resolve_health_db_timeout_seconds() -> float:
    """Parse the pool probe timeout once while registering health routes."""
    raw = os.environ.get("ACX_HEALTH_DB_TIMEOUT_SECONDS")
    if raw is None:
        return _DEFAULT_HEALTH_DB_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"ACX_HEALTH_DB_TIMEOUT_SECONDS must be a positive number (got {raw!r})") from exc
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"ACX_HEALTH_DB_TIMEOUT_SECONDS must be a positive number (got {raw!r})")
    return value


async def _supervise_load_snapshot_refresher(session_factory) -> None:
    """Re-arm an unexpectedly stopped refresher while the API remains live."""
    rearm_seconds = _LOAD_SNAPSHOT_REFRESH_REARM_SECONDS
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
        # makes the refresher fail immediately, and back off so a permanent
        # failure does not emit one traceback per second forever.
        await asyncio.sleep(rearm_seconds)
        rearm_seconds = min(rearm_seconds * 2, _LOAD_SNAPSHOT_REFRESH_REARM_MAX_SECONDS)


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
    description_profile = _resolve_description_profile()
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
    app.include_router(gpu_router, prefix="/scene")

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

    register_health_probes(app, description_profile=description_profile)
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


def resolve_model_space_probe(
    space: ModelSpace,
    *,
    insightface_cache_dir: Path,
    insightface_model_name: str,
    models_dirs: dict[ModelSpace, Path] | None = None,
) -> tuple[Callable[[], CheckResult], Path, str]:
    """Resolve a deferred readiness probe and its operator-facing store label."""
    if space is ModelSpace.INSIGHTFACE:
        store = insightface_cache_dir

        def probe() -> CheckResult:
            return check_model_cache(store, model_name=insightface_model_name)

        return probe, store, insightface_model_name

    if space is ModelSpace.FACE_PIPELINE:
        settings = RecognitionSettings()
        supplied_store = models_dirs.get(space) if models_dirs is not None else None
        store = supplied_store if supplied_store is not None else settings.face_pipeline.resolved_models_dir

        def probe() -> CheckResult:
            return check_face_pipeline_models(store)

        return probe, store, "yunet+sface"

    if space is ModelSpace.AURAFACE:
        settings = RecognitionSettings()
        supplied_store = models_dirs.get(space) if models_dirs is not None else None
        store = supplied_store if supplied_store is not None else settings.auraface_models_dir

        def probe() -> CheckResult:
            result = check_model_space(space, store)
            entry = MODEL_MANIFEST.get(ModelSpace.AURAFACE.value)
            pending = entry is not None and (
                entry.sha256 == PENDING_OPERATOR_FETCH or entry.license_sha256 == PENDING_OPERATOR_FETCH
            )
            if pending and result.status is HealthStatus.UNHEALTHY:
                return replace(result, status=HealthStatus.DEGRADED)
            return result

        return probe, store, "auraface"

    raise UnhandledModelSpaceError(f"Unhandled model space: {space!r}")


def register_health_probes(
    app: FastAPI,
    *,
    model_cache_dir: Path | None = None,
    description_profile: DescriptionProfile | None = None,
    models_dirs: dict[ModelSpace, Path] | None = None,
) -> None:
    """Attach root /health (bounded DB pool check) + /ready (deps) to the given app.

    /health is NOT a liveness probe (HEALTHOBS-1-BR-07): it does a bounded
    database-pool check (``check_database`` under ``health_db_timeout_seconds``)
    and returns HTTP 503 when that check fails. No restart-on-failure consumer
    (e.g. a container orchestrator's liveness/restart probe) should point at
    this route, because a transient database blip would then trigger container
    restarts instead of just failing the health payload. Point restart-on-failure
    checks at a probe that reflects process liveness only, not DB reachability.

    Extracted from create_app so tests can mount the probes onto a bare
    FastAPI instance without spinning up every subsystem router.

    Model-cache probe is profile-aware ([OBS-08]): insightface uses the
    existing onnx-count check; face_pipeline uses eager sha256 verification
    with mtime/size drift re-verify ([EMB-05]); auraface uses its own
    provenance and embedding-space readiness check.

    Settings are constructed once at registration (S3CR-06), including the
    description profile validation; the face model profile is re-read from
    the environment for each probe so profile changes fail closed.
    """
    if description_profile is None:
        description_profile = _resolve_description_profile()
    commit_sha = _resolve_version_commit_sha() or "unknown"
    # Baked at image build (/app/.image-variant); resolve once like commit_sha.
    image_variant = _resolve_image_variant()
    health_db_timeout_seconds = _resolve_health_db_timeout_seconds()
    # Hoist full settings parse once; close over cache/model paths (S3CR-06).
    settings = RecognitionSettings()
    insightface_cache_dir = model_cache_dir or settings.insightface.model_cache_dir
    insightface_model_name = settings.insightface.model_name

    def _current_profile() -> str:
        """Cheap per-probe profile re-read (env only; no full settings re-parse)."""
        raw = os.environ.get("RECOGNITION_FACE_PIPELINE_PROFILE", "insightface").strip()
        return raw or "insightface"

    async def _model_probe() -> tuple[CheckResult, Path, str]:
        """Return (CheckResult, cache_dir_for_detail, model_label).

        face_pipeline verification runs off the event loop (S3CR-03).
        Invalid profile → UNHEALTHY CheckResult (S3CR-04), not HTTP 500.
        """
        raw_profile = _current_profile()
        try:
            profile = ModelSpace(raw_profile)
        except (ValueError, UnhandledModelSpaceError):
            known = ", ".join(member.value for member in ModelSpace)
            return (
                CheckResult(
                    "model_cache",
                    HealthStatus.UNHEALTHY,
                    f"invalid face_pipeline profile: {raw_profile}; known spaces: {known}",
                ),
                insightface_cache_dir,
                insightface_model_name,
            )
        probe, store, label = resolve_model_space_probe(
            profile,
            insightface_cache_dir=insightface_cache_dir,
            insightface_model_name=insightface_model_name,
            models_dirs=models_dirs,
        )
        return await asyncio.to_thread(probe), store, label

    async def _disk_headroom_probe() -> CheckResult:
        """Run the synchronous filesystem probe under the liveness timeout."""
        try:
            return await asyncio.wait_for(
                check_disk_headroom(),
                timeout=health_db_timeout_seconds,
            )
        except TimeoutError:
            return disk_headroom_probe_failure("probe_timeout")
        except Exception as exc:  # noqa: BLE001 - health must fail degraded, never raise
            return disk_headroom_probe_failure(f"probe_failed: {type(exc).__name__}")

    @app.get("/health", summary="Database-backed health probe")
    async def health_pool_check(
        response: Response,
        session: AsyncSession | None = Depends(http_deps.get_observability_session),
    ) -> dict[str, object]:
        # Deploy smoke, verify, status, and uptime checks use /health, so the
        # pool probe is bounded and reflects database availability. This is a
        # dependency check, not process liveness (HEALTHOBS-1-BR-07): do not
        # wire a restart-on-failure consumer to this route, or a transient DB
        # blip will restart a healthy process instead of just failing the check.
        # commit_sha / image_variant are static identity strings resolved at
        # registration time from bake artifact + env (rg-015).
        try:
            database_check = await asyncio.wait_for(
                check_database(session),
                timeout=health_db_timeout_seconds,
            )
            database_payload = database_check.to_dict()
            status = HealthStatus.UNHEALTHY if database_check.status is HealthStatus.UNHEALTHY else HealthStatus.OK
        except TimeoutError:
            database_check = CheckResult("database", HealthStatus.UNHEALTHY, "probe_timeout")
            database_payload = {**database_check.to_dict(), "reason": "timeout"}
            status = HealthStatus.UNHEALTHY
        except Exception as exc:  # noqa: BLE001 - health must fail closed, never raise
            database_check = CheckResult(
                "database",
                HealthStatus.UNHEALTHY,
                f"probe_failed: {type(exc).__name__}",
            )
            database_payload = {**database_check.to_dict(), "reason": "probe_error"}
            status = HealthStatus.UNHEALTHY

        response.status_code = 503 if status is HealthStatus.UNHEALTHY else 200
        return {
            "status": status.value,
            "timestamp": datetime.now(UTC).isoformat(),
            "commit_sha": commit_sha,
            "image_variant": image_variant,
            "database": database_payload,
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
            await _disk_headroom_probe(),
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

        ``description_adapter`` is per-request readiness for the active
        caption producer (``DescriptionSettings.profile`` / kind), not the
        face_pipeline profile. Configuration fields are computed on each
        request; ``endpoint_private`` is a bounded cached DNS result.
        """
        # Returns pool stats + breaker state + model-cache inventory for
        # operators; never hit by load-balancer probes. Shares aggregator +
        # probes with /ready so the two stay in sync without duplicates.
        breaker = get_or_create_session_dependency_circuit_breaker(app)
        db_check = await check_database(session)
        breaker_check = check_breaker(breaker)
        mc_check, cache_dir, model_name = await _model_probe()
        embedding_model_check = check_active_embedding_model(verbose=True)
        disk_headroom_check = await _disk_headroom_probe()
        status = aggregate_status([db_check, breaker_check, mc_check, embedding_model_check, disk_headroom_check])
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
            "description_adapter": await _description_adapter_readiness(description_profile),
            "disk_headroom": disk_headroom_check.payload or {},
        }


app = create_app()
