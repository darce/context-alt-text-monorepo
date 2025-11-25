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
BorderlineValidationFn = Callable[[MediaIdentity, np.ndarray, UUID, float], Awaitable[bool]]


class RepresentativeMatcher:
    """Assign identities to clusters using representative embeddings (no centroid reliance)."""

    def __init__(
        self,
        threshold: float,
        add_representative_embedding: AddRepFn,
        assign_to_cluster_by_id: AssignFn,
        borderline_validation: BorderlineValidationFn | None = None,
    ) -> None:
        self.threshold = threshold
        self._add_representative_embedding = add_representative_embedding
        self._assign_to_cluster_by_id = assign_to_cluster_by_id
        self._borderline_validation = borderline_validation

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

    def is_borderline_match(
        self,
        similarity: float,
        borderline_upper: float,
    ) -> bool:
        """Check if a similarity score is in the borderline range requiring validation."""
        return self.threshold <= similarity < borderline_upper

    async def match(
        self,
        candidates: list[MediaIdentity],
        representatives_by_cluster: dict[UUID, list[np.ndarray]],
        borderline_upper: float | None = None,
    ) -> tuple[int, list[MediaIdentity], dict[UUID, list[np.ndarray]]]:
        """
        Match candidates to clusters via representatives.

        Args:
            candidates: Identities to match
            representatives_by_cluster: Existing cluster representatives
            borderline_upper: Upper bound for borderline range (e.g., 0.7).
                            Matches between threshold and this value are considered borderline
                            and should be validated via callback if provided.
        """
        assigned_count = 0
        still_unclustered: list[MediaIdentity] = []

        for identity in candidates:
            identity_vector = _normalize_vector(np.array(identity.embedding, dtype=np.float32))
            best_cluster_id, best_similarity = self._find_best_rep_match(
                identity_vector,
                representatives_by_cluster,
            )

            if best_cluster_id and best_similarity >= self.threshold:
                # Check if match is in borderline range (needs validation)
                is_borderline = (
                    borderline_upper is not None
                    and best_similarity < borderline_upper
                    and self._borderline_validation is not None
                )

                # Validate borderline matches before assigning
                if is_borderline:
                    logger.info(
                        "Rep match BORDERLINE: identity=%s, similarity=%.4f, validating...",
                        identity.id,
                        best_similarity,
                    )
                    assert self._borderline_validation is not None  # type narrowing
                    validation_passed = await self._borderline_validation(
                        identity,
                        identity_vector,
                        best_cluster_id,
                        best_similarity,
                    )
                    if not validation_passed:
                        logger.warning(
                            "Rep match REJECTED (borderline validation failed): identity=%s, similarity=%.4f",
                            identity.id,
                            best_similarity,
                        )
                        still_unclustered.append(identity)
                        continue
                    logger.info(
                        "Rep match VALIDATED: identity=%s, similarity=%.4f",
                        identity.id,
                        best_similarity,
                    )

                logger.info(
                    "Rep match ACCEPT%s: identity=%s, similarity=%.4f >= threshold=%.4f, cluster=%s",
                    " (validated)" if is_borderline else "",
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
