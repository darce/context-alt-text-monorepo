import logging
import os
import subprocess

from fastapi import FastAPI

from api.logging_config import configure_logging
from api.schemas.health import HealthResponse
from recognition.application.health import check_health as recognition_health
from recognition.config.cache import configure_dev_cache
from recognition.config.security import validate_production_security
from recognition.interface_adapters.http import router as recognition_router
from recognition.interface_adapters.http.deps.circuit_breaker import initialize_session_dependency_circuit_breaker
from recognition.interface_adapters.http.exception_handlers import register_exception_handlers
from recognition.interface_adapters.http.middleware.correlation import CorrelationIdMiddleware
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


def create_app() -> FastAPI:
    # Log version info at startup
    _log_startup_info()

    # Refuse to boot if production is configured with dev-only plaintext API keys.
    validate_production_security()

    app = FastAPI(
        title="Prototype Description Service",
        version="0.1.0",
        description="Experimental rewrite scaffolding for the description service.",
    )
    app.add_middleware(CorrelationIdMiddleware)
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
