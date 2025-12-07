"""
Face-only similarity helpers for embedding handling.
"""

from __future__ import annotations

import numpy as np

# Embedding layout constants
FACE_EMBEDDING_DIM = 512
EXTENDED_EMBEDDING_DIM = 1024


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
    # For extended embeddings, take only the face portion
    return vector[:FACE_EMBEDDING_DIM]


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
