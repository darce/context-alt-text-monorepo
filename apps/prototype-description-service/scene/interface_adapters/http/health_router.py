from fastapi import APIRouter

from api.schemas.health import HealthResponse
from scene.application.health import check_health

router = APIRouter(tags=["scene"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Scene subsystem health probe",
)
def scene_health() -> HealthResponse:
    report = check_health()
    return HealthResponse.model_validate(report.to_dict())
