"""Representative cache for similarity search."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from recognition.application.suggestions.embedding_space import (
    choose_embedding_model,
    representative_embedding_model,
    same_space_vector,
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

            embeddings: list[np.ndarray] = []
            chosen = choose_embedding_model(representative_embedding_model(rep) for rep in reps)
            for rep in reps:
                if chosen is not None:
                    rep_vec = same_space_vector(rep, chosen)
                else:
                    if representative_embedding_model(rep) is not None:
                        continue
                    raw = getattr(rep, "embedding", rep)
                    rep_vec = np.asarray(raw, dtype=np.float32)
                    if rep_vec.size == 0:
                        rep_vec = None
                if rep_vec is None:
                    continue
                embeddings.append(normalize_face_embedding(rep_vec))

            if embeddings:
                cache[cluster_id] = np.stack(embeddings)

        return cls(cache)

    def get_representatives(self, cluster_id: str) -> np.ndarray | None:
        return self._cache.get(cluster_id)
