from datetime import datetime

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Serializable representation of a service health report."""

    service: str = Field(..., description="Service identifier.")
    status: str = Field(..., description="Current status indicator.")
    timestamp: datetime = Field(..., description="UTC timestamp for when the status was generated.")
