"""
Media identity domain model used across recognition workflows.
"""

from dataclasses import dataclass, field
from typing import Any

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
    bbox_x: int | None = None
    bbox_y: int | None = None
    pose_pitch: float | None = None
    pose_yaw: float | None = None
    pose_roll: float | None = None
    image_phash: str | None = None
    # FIR-6 S1 quality factors (NULL under insightface; set by face_pipeline scan)
    sharpness: float | None = None
    embedding_norm: float | None = None
    occlusion_severity: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    cluster_id: str | None = None
    moved_by_merge_id: str | None = None
    # FIR23-01 / CVUP1-R3-18: provenance for the embedding space this vector belongs to.
    # Appended last so existing positional construction sites keep working.
    embedding_model: str | None = None

    def extract_face_embedding(self) -> np.ndarray:
        """Return the face-only portion of the extended embedding vector.

        Returns:
            np.ndarray: Face embedding suitable for similarity checks.
        """
        return _extract_face_embedding(np.asarray(self.embedding, dtype=np.float32))

    @property
    def face_vector(self) -> np.ndarray:
        """Return normalized 512D face embedding for similarity calculations.

        This property extracts the face portion and normalizes it to unit length.
        """
        from recognition.shared.similarity import normalize_face_embedding

        return normalize_face_embedding(np.asarray(self.embedding, dtype=np.float32))
