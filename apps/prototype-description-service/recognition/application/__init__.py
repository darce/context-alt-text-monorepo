"""Application layer use cases for the recognition service."""

from recognition.application.face_scan_service import FaceScanService
from recognition.application.health import check_health

__all__ = ["FaceScanService", "check_health"]
