"""
Media identity domain model used across recognition workflows.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from recognition.shared.similarity import extract_face_embedding as _extract_face_embedding


@dataclass
class MediaIdentity:
    """Represents a detected face and its associated embedding."""

    id: str
    tenant_id: str
    media_id: str
    embedding: np.ndarray
    confidence: float
    bbox_width: int
    bbox_height: int
    cluster_id: str | None = None

    def extract_face_embedding(self) -> np.ndarray:
        """Return the face-only portion of the extended embedding vector.

        Returns:
            np.ndarray: Face embedding suitable for similarity checks.
        """
        return _extract_face_embedding(np.asarray(self.embedding, dtype=np.float32))
