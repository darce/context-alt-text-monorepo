"""Reusable helpers for clustering and embedding normalization."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

import numpy as np

from recognition.domain.embeddings import prepare_embedding

EmbeddingLike = Sequence[float] | np.ndarray


def normalize_embeddings(embeddings: Iterable[EmbeddingLike]) -> np.ndarray:
    """Return a float32 array of unit-normalized 1024D embeddings.

    Handles both legacy 512D and new 1024D embeddings, padding as needed.
    """
    return np.array(
        [prepare_embedding(list(vec) if not isinstance(vec, np.ndarray) else vec) for vec in embeddings],
        dtype=np.float32,
    )


def convert_threshold_to_euclidean(cosine_threshold: float, embeddings: np.ndarray, atol: float = 1e-5) -> float:
    """
    Convert a cosine similarity threshold to a Euclidean distance threshold for Ward linkage.

    Validates unit normalization before conversion because the formula only holds for unit vectors.
    """

    if not 0.0 <= cosine_threshold <= 1.0:
        raise ValueError(f"Cosine threshold must be between 0 and 1, got {cosine_threshold}")

    norms = np.linalg.norm(embeddings, axis=1)
    if not np.allclose(norms, 1.0, atol=atol):
        raise ValueError("Ward clustering requires unit-normalized embeddings")

    return float(np.sqrt(2.0 * (1.0 - float(cosine_threshold))))


def group_identities_by_label(labels: Sequence[int], identities: Sequence[object]) -> dict[int, list[object]]:
    """Zip labels and identities into an in-memory mapping."""

    grouped: dict[int, list[object]] = {}
    for identity, label in zip(identities, labels, strict=False):
        grouped.setdefault(int(label), []).append(identity)
    return grouped
