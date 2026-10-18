"""Similarity search helpers for representative-based matching."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np

from recognition.application.settings import ClusteringSettings
from recognition.application.similarity.batch import batch_similarity_matrix
from recognition.application.similarity.types import MatchResult
from recognition.shared.similarity import normalize_face_embedding


class SimilaritySearch:
    """Find best matching clusters for a query embedding."""

    BATCH_THRESHOLD: int = 10

    def __init__(self, settings: ClusteringSettings) -> None:
        self._settings = settings

    def find_best_match(
        self,
        query_embedding: np.ndarray,
        representatives_by_cluster: Mapping[str, Sequence[np.ndarray] | np.ndarray],
        *,
        min_similarity: float | None = None,
    ) -> MatchResult | None:
        """Return the best match across clusters for a query embedding."""
        matches = self.find_all_matches(
            query_embedding,
            representatives_by_cluster,
            min_similarity=min_similarity,
        )
        return matches[0] if matches else None

    def find_best_matches(
        self,
        query_embeddings: Sequence[np.ndarray],
        representatives_by_cluster: Mapping[str, Sequence[np.ndarray] | np.ndarray],
        *,
        min_similarity: float | None = None,
    ) -> list[MatchResult | None]:
        """Return the best match for each query embedding."""
        if len(query_embeddings) == 0:
            return []

        threshold = min_similarity if min_similarity is not None else self._settings.similarity_threshold
        if len(query_embeddings) < self.BATCH_THRESHOLD:
            return [
                self.find_best_match(query, representatives_by_cluster, min_similarity=threshold)
                for query in query_embeddings
            ]

        return self._batch_search(query_embeddings, representatives_by_cluster, threshold)

    def find_all_matches(
        self,
        query_embedding: np.ndarray,
        representatives_by_cluster: Mapping[str, Sequence[np.ndarray] | np.ndarray],
        *,
        min_similarity: float | None = None,
    ) -> list[MatchResult]:
        """Return best matches for each cluster, sorted by similarity."""
        if not representatives_by_cluster:
            return []

        query_vector = normalize_face_embedding(np.asarray(query_embedding, dtype=np.float32))
        if query_vector.size == 0:
            return []

        threshold = min_similarity if min_similarity is not None else 0.0
        matches: list[MatchResult] = []

        for cluster_id, reps in representatives_by_cluster.items():
            rep_matrix = self._normalize_representatives(reps)
            if rep_matrix.size == 0:
                continue
            similarities = rep_matrix @ query_vector
            best_similarity = float(np.max(similarities))
            if best_similarity < threshold:
                continue
            matches.append(MatchResult(cluster_id=cluster_id, similarity=best_similarity))

        matches.sort(key=lambda match: match.similarity, reverse=True)
        return matches

    def _batch_search(
        self,
        query_embeddings: Sequence[np.ndarray],
        representatives_by_cluster: Mapping[str, Sequence[np.ndarray] | np.ndarray],
        threshold: float,
    ) -> list[MatchResult | None]:
        if not representatives_by_cluster:
            return [None for _ in query_embeddings]

        rep_batches: list[np.ndarray] = []
        rep_cluster_ids: list[str] = []
        for cluster_id, reps in representatives_by_cluster.items():
            rep_matrix = self._normalize_representatives(reps)
            if rep_matrix.size == 0:
                continue
            rep_batches.append(rep_matrix)
            rep_cluster_ids.extend([cluster_id] * rep_matrix.shape[0])

        if not rep_batches:
            return [None for _ in query_embeddings]

        rep_matrix = np.vstack(rep_batches)
        query_matrix = np.stack(
            [normalize_face_embedding(np.asarray(query, dtype=np.float32)) for query in query_embeddings]
        )
        sim_matrix = batch_similarity_matrix(query_matrix, rep_matrix, normalize=False)

        best_indices = np.argmax(sim_matrix, axis=1)
        best_sims = sim_matrix[np.arange(sim_matrix.shape[0]), best_indices]

        results: list[MatchResult | None] = []
        for best_idx, best_sim in zip(best_indices, best_sims, strict=False):
            if best_sim < threshold:
                results.append(None)
            else:
                results.append(MatchResult(cluster_id=rep_cluster_ids[int(best_idx)], similarity=float(best_sim)))
        return results

    @staticmethod
    def _normalize_representatives(representatives: Sequence[np.ndarray] | np.ndarray) -> np.ndarray:
        rep_matrix = np.asarray(representatives, dtype=np.float32)
        if rep_matrix.size == 0:
            return rep_matrix
        if rep_matrix.ndim == 1:
            return normalize_face_embedding(rep_matrix).reshape(1, -1)
        normalized = [normalize_face_embedding(rep) for rep in rep_matrix]
        return np.stack(normalized)
