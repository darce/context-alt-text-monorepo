"""Complete-link verification helpers for graph expansion."""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

import numpy as np

from recognition.shared.similarity import normalize_face_embedding


def verify_complete_link(
    candidate_embedding: np.ndarray,
    cluster_member_embeddings: Sequence[np.ndarray],
    *,
    min_similarity: float,
    min_coverage: float = 1.0,
) -> tuple[bool, float, float]:
    """Verify a candidate is sufficiently similar to cluster members.

    Returns:
        (passed, min_similarity_observed, coverage_ratio)
    """
    if not cluster_member_embeddings:
        return True, 1.0, 1.0

    candidate_vec = normalize_face_embedding(np.asarray(candidate_embedding, dtype=np.float32))

    similarities: list[float] = []
    for member_emb in cluster_member_embeddings:
        member_vec = normalize_face_embedding(np.asarray(member_emb, dtype=np.float32))
        similarities.append(float(np.dot(candidate_vec, member_vec)))

    min_sim = min(similarities)
    passing = sum(1 for sim in similarities if sim >= min_similarity)
    coverage = passing / len(similarities)
    passed = coverage >= min_coverage and min_sim >= (min_similarity * 0.9)

    return passed, min_sim, coverage


def batch_verify_complete_link(
    candidate_embeddings: Sequence[np.ndarray],
    cluster_member_embeddings: Sequence[np.ndarray],
    *,
    min_similarity: float,
) -> np.ndarray:
    """Batch verification returning boolean mask per candidate."""
    if not candidate_embeddings:
        return np.array([], dtype=bool)
    if not cluster_member_embeddings:
        return np.ones(len(candidate_embeddings), dtype=bool)

    candidates = np.stack(
        [normalize_face_embedding(np.asarray(candidate, dtype=np.float32)) for candidate in candidate_embeddings]
    )
    members = np.stack(
        [normalize_face_embedding(np.asarray(member, dtype=np.float32)) for member in cluster_member_embeddings]
    )

    sim_matrix = candidates @ members.T
    min_sims = np.min(sim_matrix, axis=1)

    return cast(np.ndarray, min_sims >= min_similarity)
