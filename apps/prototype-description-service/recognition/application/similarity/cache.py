"""Representative cache for similarity search."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from recognition.application.suggestions.embedding_space import (
    same_space_representative_vectors,
)
from recognition.domain.repositories import ClusterRepository
from recognition.shared.similarity import normalize_face_embedding


@dataclass
class RepresentativeCache:
    """Pre-normalized representatives for fast similarity search within a job."""

    _cache: dict[str, np.ndarray]

    @classmethod
    async def load(
        cls,
        cluster_ids: list[str],
        cluster_repository: ClusterRepository,
    ) -> RepresentativeCache:
        cache: dict[str, np.ndarray] = {}
        seen: set[str] = set()

        for cluster_id in cluster_ids:
            if cluster_id in seen:
                continue
            seen.add(cluster_id)

            reps = await cluster_repository.get_all_representatives(cluster_id)
            if not reps:
                continue

            _, same_space_vectors = same_space_representative_vectors(reps)
            embeddings = [normalize_face_embedding(vector) for vector in same_space_vectors]

            if embeddings:
                cache[cluster_id] = np.stack(embeddings)

        return cls(cache)

    def get_representatives(self, cluster_id: str) -> np.ndarray | None:
        return self._cache.get(cluster_id)
