"""Utilities for computing and updating identity cluster centroids."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from recognition.shared.similarity import (
    FACE_EMBEDDING_DIM,
    compute_face_similarity,
    extract_face_embedding,
    normalize_vector,
)


def _to_face_embedding(vec: np.ndarray) -> np.ndarray:
    """
    Extract face embedding portion from an embedding vector.

    If the input is larger than 512D, extract the first 512D.
    If the input is already 512D, return as-is.

    This ensures similarity calculations use only the face identity vector,
    not the metadata portion which can cause false matches.
    """
    if len(vec) >= FACE_EMBEDDING_DIM:
        return extract_face_embedding(vec)
    # Unknown dimension - return as-is and let caller handle
    return vec


def compute_centroid(embeddings: Sequence[Sequence[float] | np.ndarray]) -> np.ndarray:
    """
    Compute the arithmetic centroid for the provided embeddings.

    Returns a normalized centroid (L2 norm == 1.0) suitable for cosine similarity checks.

    Note: This operates on the full embedding (512D) to preserve metadata
    for the centroid representation.
    """
    if not embeddings:
        raise ValueError("Cannot compute centroid for an empty embedding list")

    embeddings_array = np.array(embeddings, dtype=np.float32)
    normalized = np.array([normalize_vector(vec) for vec in embeddings_array], dtype=np.float32)
    centroid = np.mean(normalized, axis=0)
    return normalize_vector(centroid)


def compute_similarity(
    embedding_a: Sequence[float] | np.ndarray,
    embedding_b: Sequence[float] | np.ndarray,
) -> float:
    """
    Return cosine similarity between two embeddings clamped to [0, 1].

    IMPORTANT: Uses only the face embedding portion (first 512D) for similarity.
    This prevents false matches due to metadata attributes (pose, age, etc.)
    """
    vec_a = np.array(embedding_a, dtype=np.float32)
    vec_b = np.array(embedding_b, dtype=np.float32)

    similarity = compute_face_similarity(_to_face_embedding(vec_a), _to_face_embedding(vec_b))
    # Floating point drift may produce values slightly outside the range.
    return max(0.0, min(1.0, similarity))
