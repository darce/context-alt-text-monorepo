"""Utilities for computing and updating identity cluster centroids."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from recognition.shared.similarity import (
    EXTENDED_EMBEDDING_DIM,
    FACE_EMBEDDING_DIM,
    compute_face_similarity,
    extract_face_embedding,
)


def _to_face_embedding(vec: np.ndarray) -> np.ndarray:
    """
    Extract face embedding portion from an embedding vector.

    If the input is 1024D (extended embedding), extract the first 512D.
    If the input is already 512D, return as-is.

    This ensures similarity calculations use only the face identity vector,
    not the metadata portion which can cause false matches.
    """
    if len(vec) in (EXTENDED_EMBEDDING_DIM, FACE_EMBEDDING_DIM):
        return extract_face_embedding(vec)
    # Unknown dimension - return as-is and let caller handle
    return vec


def compute_centroid(embeddings: Sequence[Sequence[float] | np.ndarray]) -> np.ndarray:
    """
    Compute the arithmetic centroid for the provided embeddings.

    Returns a normalized centroid (L2 norm == 1.0) suitable for cosine similarity checks.

    Note: This operates on the full embedding (1024D or 512D) to preserve metadata
    for the centroid representation.
    """
    if not embeddings:
        raise ValueError("Cannot compute centroid for an empty embedding list")

    embeddings_array = np.array(embeddings, dtype=np.float32)
    normalized = np.array([_normalize_vector(vec) for vec in embeddings_array], dtype=np.float32)
    centroid = np.mean(normalized, axis=0)
    return _normalize_vector(centroid)


def update_centroid_incremental(
    old_centroid: Sequence[float] | np.ndarray,
    old_count: int,
    new_embedding: Sequence[float] | np.ndarray,
) -> np.ndarray:
    """
    Update an existing centroid with an additional embedding using a weighted average.

    Returns a normalized centroid (L2 norm == 1.0) suitable for cosine similarity checks.

    Note: This operates on the full embedding (1024D or 512D) to preserve metadata
    for the centroid representation.
    """
    if old_count < 0:
        raise ValueError("old_count must be non-negative")

    old_vector = np.array(old_centroid, dtype=np.float32)
    new_vector = np.array(new_embedding, dtype=np.float32)
    new_vector = _normalize_vector(new_vector)

    weighted_old = old_vector * float(old_count)
    updated = (weighted_old + new_vector) / float(old_count + 1)
    return _normalize_vector(updated)


def compute_similarity(
    embedding_a: Sequence[float] | np.ndarray,
    embedding_b: Sequence[float] | np.ndarray,
) -> float:
    """
    Return cosine similarity between two embeddings clamped to [0, 1].

    IMPORTANT: Uses only the face embedding portion (first 512D) for similarity.
    This prevents false matches due to metadata attributes (pose, age, etc.)
    that can dominate the normalized 1024D vector.
    """
    vec_a = np.array(embedding_a, dtype=np.float32)
    vec_b = np.array(embedding_b, dtype=np.float32)

    similarity = compute_face_similarity(_to_face_embedding(vec_a), _to_face_embedding(vec_b))
    # Floating point drift may produce values slightly outside the range.
    return max(0.0, min(1.0, similarity))


def _normalize_vector(vector: np.ndarray) -> np.ndarray:
    """Normalize a vector, returning the original vector if its norm is zero."""
    norm = float(np.linalg.norm(vector))
    if norm == 0:
        return vector
    return vector / norm
