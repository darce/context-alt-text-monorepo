"""
Embedding service - the seam between Infrastructure and Domain layers.

ARCHITECTURE: Face → Identity Boundary
======================================
This module is the transformation point between:

Infrastructure Layer (Face* nomenclature):
    - FaceDetection: Detected face bounding box (InsightFace-specific)
    - EmbeddingResult: 512D face embedding vector

Domain Layer (*Identity nomenclature):
    - MediaIdentity: Technology-agnostic clusterable entity

The seam is `EmbeddingService.to_media_identities()` which transforms
infrastructure outputs into domain objects.

WHY THIS MATTERS
----------------
The Domain Layer (MediaIdentity, IdentityCluster, ClusterRepresentative)
doesn't care HOW the embeddings were generated. If we swap InsightFace for
YOLO+ArcFace, MediaPipe, or another detection system:

    - Only the Infrastructure Layer changes (new FaceDetector implementation)
    - The Domain Layer remains unchanged
    - This module handles the translation

See: docs/tasks/4.0/4.2.4/uml/architecture-face-identity-boundary.mmd
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np

from recognition.domain.identity import MediaIdentity
from recognition.shared.ids import generate_id


@dataclass
class FaceDetection:
    """Detected face bounding box and confidence for a media asset."""

    media_id: str
    bbox: tuple[int, int, int, int]
    confidence: float


@dataclass
class EmbeddingResult:
    """Embedding output for a detected face."""

    media_id: str
    embedding: np.ndarray
    confidence: float


class EmbeddingService:
    """Deterministic embedding pipeline placeholder for integration tests."""

    def __init__(self, embedding_dim: int = 1024) -> None:
        self.embedding_dim = embedding_dim

    def detect_faces(self, media_ids: Iterable[str]) -> list[FaceDetection]:
        """Return one synthetic detection per media_id."""
        detections: list[FaceDetection] = []
        for media_id in media_ids:
            detections.append(FaceDetection(media_id=media_id, bbox=(0, 0, 1, 1), confidence=0.99))
        return detections

    def generate_embeddings(self, detections: Iterable[FaceDetection]) -> list[EmbeddingResult]:
        """Return deterministic 1024D embeddings for each detection."""
        results: list[EmbeddingResult] = []
        for detection in detections:
            seed = hashlib.sha256(detection.media_id.encode()).digest()
            # Repeat seed to fill the target dimension
            vector = np.frombuffer(seed * ((self.embedding_dim // len(seed)) + 1), dtype=np.uint8)[
                : self.embedding_dim
            ].astype(np.float32)
            norm = np.linalg.norm(vector)
            embedding = vector / norm if norm else vector
            results.append(
                EmbeddingResult(
                    media_id=detection.media_id,
                    embedding=embedding,
                    confidence=detection.confidence,
                )
            )
        return results

    def to_media_identities(self, tenant_id: str, embeddings: Iterable[EmbeddingResult]) -> list[MediaIdentity]:
        """Convert embedding results into domain MediaIdentity objects."""
        identities: list[MediaIdentity] = []
        for result in embeddings:
            identities.append(
                MediaIdentity(
                    id=str(generate_id()),
                    tenant_id=tenant_id,
                    media_id=result.media_id,
                    embedding=result.embedding,
                    confidence=result.confidence,
                    bbox_width=1,
                    bbox_height=1,
                )
            )
        return identities


__all__ = ["EmbeddingService", "EmbeddingResult", "FaceDetection"]
