from fastapi import APIRouter

from api.schemas.health import HealthResponse
from recognition.application.health import check_health

router = APIRouter(tags=["recognition"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Recognition subsystem health probe",
)
def recognition_health() -> HealthResponse:
    report = check_health()
    return HealthResponse.model_validate(report.to_dict())
