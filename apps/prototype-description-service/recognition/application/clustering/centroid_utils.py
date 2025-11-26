"""Utilities for computing and updating identity cluster centroids."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np


def compute_centroid(embeddings: Sequence[Sequence[float] | np.ndarray]) -> np.ndarray:
    """
    Compute the arithmetic centroid for the provided embeddings.

    Returns a normalized centroid (L2 norm == 1.0) suitable for cosine similarity checks.
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
    """Return cosine similarity between two embeddings clamped to [0, 1]."""
    vec_a = np.array(embedding_a, dtype=np.float32)
    vec_b = np.array(embedding_b, dtype=np.float32)

    vec_a = _normalize_vector(vec_a)
    vec_b = _normalize_vector(vec_b)

    similarity = float(np.dot(vec_a, vec_b))
    # Floating point drift may produce values slightly outside the range.
    return max(0.0, min(1.0, similarity))


def _normalize_vector(vector: np.ndarray) -> np.ndarray:
    """Normalize a vector, returning the original vector if its norm is zero."""
    norm = float(np.linalg.norm(vector))
    if norm == 0:
        return vector
    return vector / norm
