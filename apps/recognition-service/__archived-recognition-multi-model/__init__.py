"""
Recognition Service
Face recognition microservice with hexagonal architecture.

This service provides face recognition capabilities using CVLFace models:
- AdaFace IR101 with quality-adaptive margin
- InsightFace W600K with built-in alignment  
- ArcFace IR50 with MTCNN alignment

Architecture follows hexagonal/ports-and-adapters pattern:
- Domain: Core business logic and entities
- Ports: External interfaces (FastAPI router)
- Adapters: External system integrations (models, storage)
"""
from .domain import (
    ModelType, AlignmentStrategy, FaceDetection, FaceEmbedding,
    RecognitionMatch, RecognitionResult, SceneAnalysisResult,
    RecognitionService, RecognitionPort
)
from .ports import router, get_recognition_service
from .config import get_config

__version__ = "1.0.0"

__all__ = [
    # Domain
    "ModelType", "AlignmentStrategy", "FaceDetection", "FaceEmbedding",
    "RecognitionMatch", "RecognitionResult", "SceneAnalysisResult",
    "RecognitionService", "RecognitionPort",
    # Ports
    "router", "get_recognition_service",
    # Config
    "get_config"
]
