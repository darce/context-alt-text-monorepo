"""
Recognition Domain Module

Domain layer for the InsightFace-only recognition service.
"""

from .entities import (
    FaceDetection,
    FaceEmbedding, 
    EmbeddingEntry,
    MatchResult,
    RecognitionResult
)
from .interfaces import (
    FaceDetectorPort,
    FaceEmbedderPort, 
    EmbeddingRouterPort,
    RecognitionServicePort
)

__all__ = [
    "FaceDetection",
    "FaceEmbedding",
    "EmbeddingEntry", 
    "MatchResult",
    "RecognitionResult",
    "FaceDetectorPort",
    "FaceEmbedderPort",
    "EmbeddingRouterPort", 
    "RecognitionServicePort"
]
