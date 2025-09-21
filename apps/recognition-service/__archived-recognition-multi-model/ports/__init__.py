"""
Recognition Service Ports Layer
API endpoints and external interfaces for the recognition service.
"""
from .api_router import router
from .models import (
    AnalyzeSceneRequest, AnalyzeSceneResponse, ModelTypeAPI,
    FaceDetectionAPI, RecognitionMatchAPI, FaceResultAPI,
    ErrorResponse, HealthResponse, ModelInfo, ModelsResponse
)
from .dependencies import get_recognition_service, clear_recognition_service

__all__ = [
    # Router
    "router",
    # Models
    "AnalyzeSceneRequest", "AnalyzeSceneResponse", "ModelTypeAPI",
    "FaceDetectionAPI", "RecognitionMatchAPI", "FaceResultAPI",
    "ErrorResponse", "HealthResponse", "ModelInfo", "ModelsResponse",
    # Dependencies
    "get_recognition_service", "clear_recognition_service"
]
