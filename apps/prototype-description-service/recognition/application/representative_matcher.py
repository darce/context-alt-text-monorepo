"""Representative-based matching (order-independent)."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from uuid import UUID

import numpy as np

from db.models import MediaIdentity
from recognition.application.centroid_utils import _normalize_vector, compute_similarity

logger = logging.getLogger(__name__)

AssignFn = Callable[[MediaIdentity, np.ndarray, UUID, float], Awaitable[None]]
AddRepFn = Callable[[UUID, MediaIdentity], Awaitable[np.ndarray | None]]


class RepresentativeMatcher:
    """Assign identities to clusters using representative embeddings (no centroid reliance)."""

    def __init__(
        self,
        threshold: float,
        add_representative_embedding: AddRepFn,
        assign_to_cluster_by_id: AssignFn,
    ) -> None:
        self.threshold = threshold
        self._add_representative_embedding = add_representative_embedding
        self._assign_to_cluster_by_id = assign_to_cluster_by_id

    def _find_best_rep_match(
        self,
        identity_vector: np.ndarray,
        representatives_by_cluster: dict[UUID, list[np.ndarray]],
    ) -> tuple[UUID | None, float]:
        best_cluster_id: UUID | None = None
        best_similarity = 0.0

        for cluster_id, reps in representatives_by_cluster.items():
            for rep_vec in reps:
                similarity = compute_similarity(identity_vector, rep_vec)
                if similarity > best_similarity:
                    best_similarity = similarity
                    best_cluster_id = cluster_id

        return best_cluster_id, best_similarity

    def best_match(
        self,
        identity_vector: np.ndarray,
        representatives_by_cluster: dict[UUID, list[np.ndarray]],
    ) -> tuple[UUID | None, float]:
        """Expose best representative match (for diagnostics)."""

        return self._find_best_rep_match(identity_vector, representatives_by_cluster)

    async def match(
        self,
        candidates: list[MediaIdentity],
        representatives_by_cluster: dict[UUID, list[np.ndarray]],
    ) -> tuple[int, list[MediaIdentity], dict[UUID, list[np.ndarray]]]:
        assigned_count = 0
        still_unclustered: list[MediaIdentity] = []

        for identity in candidates:
            identity_vector = _normalize_vector(np.array(identity.embedding, dtype=np.float32))
            best_cluster_id, best_similarity = self._find_best_rep_match(
                identity_vector,
                representatives_by_cluster,
            )

            if best_cluster_id and best_similarity >= self.threshold:
                logger.info(
                    "Rep match ACCEPT: identity=%s, similarity=%.4f >= threshold=%.4f, cluster=%s",
                    identity.id,
                    best_similarity,
                    self.threshold,
                    best_cluster_id,
                )
                await self._assign_to_cluster_by_id(identity, identity_vector, best_cluster_id, best_similarity)
                rep_embedding = await self._add_representative_embedding(best_cluster_id, identity)
                if rep_embedding is not None:
                    representatives_by_cluster.setdefault(best_cluster_id, []).append(rep_embedding)
                assigned_count += 1
            else:
                logger.debug(
                    "Rep match REJECT: identity=%s, similarity=%.4f < threshold=%.4f",
                    identity.id,
                    best_similarity,
                    self.threshold,
                )
                still_unclustered.append(identity)

        return assigned_count, still_unclustered, representatives_by_cluster
