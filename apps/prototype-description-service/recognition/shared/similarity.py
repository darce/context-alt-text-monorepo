"""
Face-only similarity helpers for embedding handling.
"""

from __future__ import annotations

import numpy as np

from recognition.config import get_settings

# Single source: recognition.config.settings IdentityDetectionSettings.embedding_dimension
FACE_EMBEDDING_DIM = get_settings().identity_detection.embedding_dimension


def extract_face_embedding(embedding: np.ndarray) -> np.ndarray:
    """Return the face identity portion of an embedding vector."""
    if embedding is None:
        raise ValueError("embedding must not be None")

    vector = np.asarray(embedding, dtype=np.float32)
    if len(vector) < FACE_EMBEDDING_DIM:
        # Unknown layout; return as-is to avoid slicing errors
        return vector
    if len(vector) == FACE_EMBEDDING_DIM:
        return vector
    # Take only the face portion if larger
    return vector[:FACE_EMBEDDING_DIM]


def normalize_vector(vector: np.ndarray) -> np.ndarray:
    """Normalize a vector to unit length.

    Args:
        vector: Input vector to normalize.

    Returns:
        Unit-length vector as float32. Returns zero vector unchanged.
    """
    norm = float(np.linalg.norm(vector))
    if norm == 0:
        return vector.astype(np.float32)
    return vector.astype(np.float32) / norm


def normalize_face_embedding(embedding: np.ndarray) -> np.ndarray:
    """Extract face embedding and normalize to unit length.

    Args:
        embedding: Raw embedding (512D).

    Returns:
        Unit-length 512D face embedding as float32.
    """
    return normalize_vector(extract_face_embedding(embedding))


def compute_face_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity using only the face embedding dimensions."""
    face_a = extract_face_embedding(a)
    face_b = extract_face_embedding(b)

    norm_a = float(np.linalg.norm(face_a))
    norm_b = float(np.linalg.norm(face_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0

    face_a = face_a / norm_a
    face_b = face_b / norm_b
    return float(np.dot(face_a, face_b))
