"""
Recognition Service Domain Layer
Core business logic and interfaces for face recognition.
"""
from .entities import (
    ModelType, AlignmentStrategy, FaceDetection, FaceEmbedding,
    RecognitionMatch, RecognitionResult, SceneAnalysisResult
)
from .interfaces import (
    FaceAligner, QualityScorer, EmbeddingRouter, CVLFaceAdapter, RecognitionPort
)
from .dto import SceneAnalysisDTO, FaceResultDTO, MatchResultDTO
from .recognition_service import RecognitionService

__all__ = [
    # Entities
    "ModelType", "AlignmentStrategy", "FaceDetection", "FaceEmbedding",
    "RecognitionMatch", "RecognitionResult", "SceneAnalysisResult",
    # DTOs
    "SceneAnalysisDTO", "FaceResultDTO", "MatchResultDTO",
    # Interfaces
    "FaceAligner", "QualityScorer", "EmbeddingRouter", "CVLFaceAdapter", "RecognitionPort",
    # Services
    "RecognitionService",
]
