"""
Hierarchical Agglomerative Clustering (HAC) with pairwise constraints.
"""

from __future__ import annotations

import uuid
from uuid import UUID

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import pdist, squareform

from recognition.application.settings.clustering import HACSettings
from recognition.domain.constraints import ConstraintType, IdentityConstraint
from recognition.domain.repositories import IdentityConstraintRepository


def _apply_constraint_to_matrix(
    dist_matrix: np.ndarray,
    constraint: IdentityConstraint,
    id_to_idx: dict[UUID, int],
    penalty: float,
) -> None:
    """Apply a single constraint to the distance matrix (in-place)."""
    i = id_to_idx.get(constraint.identity_a)
    j = id_to_idx.get(constraint.identity_b)

    if i is None or j is None:
        return

    match constraint.constraint_type:
        case ConstraintType.MUST_LINK:
            dist_matrix[i, j] = dist_matrix[j, i] = 0.0
        case ConstraintType.CANNOT_LINK:
            max_val = max(dist_matrix[i, j], penalty)
            dist_matrix[i, j] = dist_matrix[j, i] = max_val
        case _:
            return


class ConstrainedHAC:
    """HAC clustering with user-derived pairwise constraints."""

    def __init__(
        self,
        constraint_repo: IdentityConstraintRepository,
        settings: HACSettings,
    ) -> None:
        self.constraint_repo = constraint_repo
        self.settings = settings

    async def refine_clusters(
        self,
        tenant_id: UUID,
        embeddings: dict[UUID, np.ndarray],
    ) -> dict[UUID, UUID]:
        """Apply HAC to embeddings with constraint penalties.

        Args:
            tenant_id: Tenant scope.
            embeddings: Map of identity ID -> embedding vector.

        Returns:
            Map of identity ID -> new cluster ID (UUID).
        """
        if not embeddings:
            return {}

        ids = list(embeddings.keys())
        # Ensure consistent order
        ids.sort()

        # 1. Compute pairwise distances
        # stack embeddings
        embeddings_matrix = np.stack([embeddings[i] for i in ids])
        condensed_dist = pdist(embeddings_matrix, metric="cosine")
        dist_matrix = squareform(condensed_dist)

        # 2. Apply constraint penalties
        constraints = await self.constraint_repo.get_all(tenant_id)

        # Build index map for faster lookup
        id_to_idx = {uid: i for i, uid in enumerate(ids)}

        for c in constraints:
            _apply_constraint_to_matrix(dist_matrix, c, id_to_idx, self.settings.constraint_penalty)

        # 3. Run HAC
        # Re-condense for linkage
        condensed_final = squareform(dist_matrix)
        linkage_matrix = linkage(condensed_final, method=self.settings.linkage_method)
        labels = fcluster(linkage_matrix, t=self.settings.distance_threshold, criterion="distance")

        # 4. Map labels to UUIDs
        # fcluster returns 1-based integers
        label_to_uuid = {}
        result = {}

        for idx, label in enumerate(labels):
            if label not in label_to_uuid:
                label_to_uuid[label] = uuid.uuid4()
            result[ids[idx]] = label_to_uuid[label]

        return result
