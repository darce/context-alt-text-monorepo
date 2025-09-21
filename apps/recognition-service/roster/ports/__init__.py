"""
Ports Module

Exports all external interface components (API, models, dependencies).
"""

from .api_router import router
from .models import (
    AddRosterEntryRequest, BulkAddRosterRequest, UpdateRosterEntryRequest,
    RosterEntryDTO, RosterEntryResponse, BulkAddResponse, RosterListResponse,
    RosterStatsResponse, DeleteEntryResponse, HealthCheckResponse, ErrorResponse
)
from .dependencies import get_roster_service, create_roster_service, reset_roster_service

__all__ = [
    "router",
    "AddRosterEntryRequest",
    "BulkAddRosterRequest", 
    "UpdateRosterEntryRequest",
    "RosterEntryDTO",
    "RosterEntryResponse",
    "BulkAddResponse",
    "RosterListResponse",
    "RosterStatsResponse",
    "DeleteEntryResponse",
    "HealthCheckResponse",
    "ErrorResponse",
    "get_roster_service",
    "create_roster_service",
    "reset_roster_service"
]
