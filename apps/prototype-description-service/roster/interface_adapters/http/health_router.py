from fastapi import APIRouter

from api.schemas.health import HealthResponse
from roster.application.health import check_health

router = APIRouter(tags=["roster"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Roster subsystem health probe",
)
def roster_health() -> HealthResponse:
    report = check_health()
    return HealthResponse.model_validate(report.to_dict())
