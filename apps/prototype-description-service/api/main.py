from fastapi import FastAPI

from api.schemas.health import HealthResponse
from recognition.application.health import check_health as recognition_health
from recognition.interface_adapters.http.health_router import router as recognition_router
from roster.application.health import check_health as roster_health
from roster.interface_adapters.http.health_router import router as roster_router
from scene.application.health import check_health as scene_health
from scene.interface_adapters.http.health_router import router as scene_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="Prototype Description Service",
        version="0.1.0",
        description="Experimental rewrite scaffolding for the description service.",
    )

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
