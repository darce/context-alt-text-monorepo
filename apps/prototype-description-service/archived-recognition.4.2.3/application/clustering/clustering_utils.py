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


def group_identities_by_label(labels: Sequence[int], identities: Sequence[object]) -> dict[int, list[object]]:
    """Zip labels and identities into an in-memory mapping."""

    grouped: dict[int, list[object]] = {}
    for identity, label in zip(identities, labels, strict=False):
        grouped.setdefault(int(label), []).append(identity)
    return grouped
