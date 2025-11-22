from urllib.parse import urlparse

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from api.logging_config import configure_logging
from api.schemas.health import HealthResponse
from recognition.application.health import check_health as recognition_health
from recognition.config import get_settings
from recognition.config.cache import configure_dev_cache
from recognition.interface_adapters.http import router as recognition_router
from roster.application.health import check_health as roster_health
from roster.interface_adapters.http.health_router import router as roster_router
from scene.application.health import check_health as scene_health
from scene.interface_adapters.http.health_router import router as scene_router

# Configure logging to show diagnostic output
configure_logging("INFO")

configure_dev_cache()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Prototype Description Service",
        version="0.1.0",
        description="Experimental rewrite scaffolding for the description service.",
    )
    settings = get_settings()

    thumbnail_base = settings.thumbnail.base_url or ""
    thumbnail_path = ""
    if thumbnail_base:
        parsed = urlparse(thumbnail_base)
        if parsed.scheme:
            thumbnail_path = parsed.path or ""
        else:
            thumbnail_path = thumbnail_base

    if thumbnail_path:
        normalized_path = thumbnail_path if thumbnail_path.startswith("/") else f"/{thumbnail_path}"
        thumbnails_dir = settings.thumbnail.storage_dir
        thumbnails_dir.mkdir(parents=True, exist_ok=True)
        app.mount(normalized_path, StaticFiles(directory=thumbnails_dir), name="thumbnails")

    app.include_router(recognition_router, prefix="/recognition")
    app.include_router(roster_router, prefix="/roster")
    app.include_router(scene_router, prefix="/scene")

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
