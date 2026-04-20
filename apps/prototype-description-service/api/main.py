import logging
import os
import subprocess

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from api.logging_config import configure_logging
from api.schemas.health import HealthResponse
from recognition.application.health import check_health as recognition_health
from recognition.config.cache import configure_dev_cache
from recognition.config.security import get_security_settings
from recognition.config.settings import RecognitionSettings
from recognition.interface_adapters.http import router as recognition_router
from recognition.interface_adapters.http.deps.circuit_breaker import initialize_session_dependency_circuit_breaker
from recognition.interface_adapters.http.exception_handlers import register_exception_handlers
from roster.application.health import check_health as roster_health
from roster.interface_adapters.http.curation_router import router as roster_curation_router
from roster.interface_adapters.http.health_router import router as roster_router
from scene.application.health import check_health as scene_health
from scene.interface_adapters.http.health_router import router as scene_router

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


def _log_startup_info() -> None:
    """Log git commit and branch info at startup."""
    # Use db.startup namespace to pass the RecognitionFilter
    startup_logger = logging.getLogger("db.startup")
    commit, branch = _get_git_info()

    # Get port from environment (set by start script, defaults to 8000)
    port = os.environ.get("PORT", "8000")
    host = os.environ.get("HOST", "127.0.0.1")

    startup_logger.info("=== Application Startup ===")
    startup_logger.info("Git: %s (%s)", commit, branch)
    startup_logger.info("Listening on http://%s:%s", host, port)

    configure_dev_cache()


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


def create_app() -> FastAPI:
    # Log version info at startup
    _log_startup_info()
    _check_dev_key_guard()

    app = FastAPI(
        title="Prototype Description Service",
        version="0.1.0",
        description="Experimental rewrite scaffolding for the description service.",
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

    initialize_session_dependency_circuit_breaker(app)

    app.include_router(recognition_router, prefix="/recognition")
    app.include_router(roster_router, prefix="/roster")
    app.include_router(roster_curation_router, prefix="/roster")
    app.include_router(scene_router, prefix="/scene")
    register_exception_handlers(app)

    @app.get(
        "/health",
        response_model=list[HealthResponse],
        summary="Aggregate health status for all subsystems",
    )
    def overall_health() -> list[HealthResponse]:
        reports = [
            recognition_health(),
            roster_health(),
            scene_health(),
        ]
        return [HealthResponse.model_validate(report.to_dict()) for report in reports]

    return app


app = create_app()
