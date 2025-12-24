"""
Embedding module - detection and embedding generation.

This module provides the infrastructure seam between raw media and domain identities:
- FaceDetection: Detected face with bounding box and metadata
- EmbeddingResult: Generated embedding vector
- FaceDetectorProtocol / StubFaceDetector / InsightFaceFaceDetector: Detection adapters
- EmbeddingGeneratorProtocol / StubEmbeddingGenerator / InsightFaceEmbeddingGenerator: Embedding adapters
"""

from recognition.application.embedding.detector import (
    FaceDetection,
    FaceDetector,
    FaceDetectorProtocol,
    InsightFaceFaceDetector,
    StubFaceDetector,
)
from recognition.application.embedding.generator import (
    EmbeddingGenerator,
    EmbeddingGeneratorProtocol,
    EmbeddingResult,
    InsightFaceEmbeddingGenerator,
    StubEmbeddingGenerator,
)

__all__ = [
    # Data classes
    "FaceDetection",
    "EmbeddingResult",
    # Detection
    "FaceDetectorProtocol",
    "StubFaceDetector",
    "InsightFaceFaceDetector",
    "FaceDetector",
    # Embedding generation
    "EmbeddingGeneratorProtocol",
    "StubEmbeddingGenerator",
    "InsightFaceEmbeddingGenerator",
    "EmbeddingGenerator",
]
