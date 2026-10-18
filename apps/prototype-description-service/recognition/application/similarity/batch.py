"""Batch vectorized similarity utilities."""

from __future__ import annotations

import numpy as np

from recognition.shared.similarity import normalize_face_embedding


def batch_similarity_matrix(
    queries: np.ndarray,
    representatives: np.ndarray,
    *,
    normalize: bool = True,
) -> np.ndarray:
    """Compute cosine similarity matrix between queries and representatives.

    Returns:
        A matrix shaped (n_queries, n_representatives).
    """
    query_matrix = np.asarray(queries, dtype=np.float32)
    rep_matrix = np.asarray(representatives, dtype=np.float32)

    if query_matrix.size == 0 or rep_matrix.size == 0:
        return np.empty((len(query_matrix), len(rep_matrix)), dtype=np.float32)

    if query_matrix.ndim == 1:
        query_matrix = query_matrix.reshape(1, -1)
    if rep_matrix.ndim == 1:
        rep_matrix = rep_matrix.reshape(1, -1)

    if normalize:
        query_matrix = np.stack([normalize_face_embedding(q) for q in query_matrix])
        rep_matrix = np.stack([normalize_face_embedding(r) for r in rep_matrix])

    return query_matrix @ rep_matrix.T
