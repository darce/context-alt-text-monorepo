"""
Embedding module - detection and embedding generation.

This module provides the infrastructure seam between raw media and domain identities:
- FaceDetection: Detected face with bounding box and metadata
- EmbeddingResult: Generated embedding vector
- FaceDetectorProtocol / StubFaceDetector / InsightFaceFaceDetector: Detection adapters
- EmbeddingGeneratorProtocol / StubEmbeddingGenerator / InsightFaceEmbeddingGenerator: Embedding adapters
"""

from recognition.application.embedding.detector import (
    DetectionTimeoutError,
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
    EmbeddingTimeoutError,
    InsightFaceEmbeddingGenerator,
    StubEmbeddingGenerator,
)
from recognition.application.embedding.manifest import (
    EmbeddingModelManifest,
    active_embedding_model_id,
    incumbent_embedding_model_manifest,
)

__all__ = [
    # Data classes
    "FaceDetection",
    "EmbeddingResult",
    "EmbeddingModelManifest",
    "active_embedding_model_id",
    "incumbent_embedding_model_manifest",
    # Detection
    "DetectionTimeoutError",
    "FaceDetectorProtocol",
    "StubFaceDetector",
    "InsightFaceFaceDetector",
    "FaceDetector",
    # Embedding generation
    "EmbeddingTimeoutError",
    "EmbeddingGeneratorProtocol",
    "StubEmbeddingGenerator",
    "InsightFaceEmbeddingGenerator",
    "EmbeddingGenerator",
]
