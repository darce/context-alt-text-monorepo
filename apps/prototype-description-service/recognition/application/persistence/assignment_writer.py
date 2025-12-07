"""
AssignmentWriter interface for persisting gate decisions (Phase 5).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import cast

import numpy as np

from recognition.application.assignment.decision import AssignmentDecision, AssignmentOutcome
from recognition.application.settings.clustering import ClusteringSettings
from recognition.domain.cluster import IdentityCluster
from recognition.domain.identity import MediaIdentity
from recognition.domain.repositories import ClusterRepository, MemberData, MemberRepository
from recognition.domain.representative import ClusterRepresentative
from recognition.shared.similarity import compute_face_similarity


class AssignmentWriter:
    """Persist assignment decisions and cluster updates."""

    def __init__(
        self,
        settings: ClusteringSettings,
        cluster_repository: ClusterRepository,
        member_repository: MemberRepository,
    ) -> None:
        self._settings = settings
        self._clusters = cluster_repository
        self._members = member_repository

    async def persist_assignment(self, decision: AssignmentDecision) -> None:
        """Persist an accepted assignment decision."""
        if decision.outcome is not AssignmentOutcome.ACCEPT:
            raise ValueError(f"Cannot persist non-ACCEPT decision: {decision.outcome}")

        cluster = await self._clusters.get_by_id(decision.candidate.cluster_id)
        if not cluster:
            raise ClusterNotFoundError(decision.candidate.cluster_id)

        await self._members.add_member(
            cluster_id=decision.candidate.cluster_id,
            identity_id=decision.candidate.identity.id,
            similarity=decision.candidate.discovery_similarity,
        )

        if await self._should_add_representative(decision):
            # Store the full 1024D embedding, not the face-only 512D vector
            full_embedding = decision.candidate.identity.embedding
            rep = ClusterRepresentative(
                id=str(uuid.uuid4()),
                cluster_id=decision.candidate.cluster_id,
                identity_id=decision.candidate.identity.id,
                embedding=full_embedding,
                created_at=datetime.now(tz=UTC),
                tenant_id=decision.candidate.identity.tenant_id,
            )
            await self._clusters.add_representative(rep)
            new_centroid = await self.recompute_centroid(decision.candidate.cluster_id)
            if new_centroid is not None:
                cluster.centroid = new_centroid

        cluster.member_count += 1
        await self._clusters.update(cluster)

    async def refresh_centroids_view(self) -> None:
        """Trigger a refresh of the cluster centroids view."""
        # Call repo if it supports it
        refresh = getattr(self._clusters, "refresh_centroids_view", None)
        if callable(refresh):
            await refresh()

    async def _should_add_representative(self, decision: AssignmentDecision) -> bool:
        """Determine if the assigned identity should become a representative."""
        cluster_id = decision.candidate.cluster_id
        current_count = await self._clusters.get_representative_count(cluster_id)

        if current_count >= self._settings.max_representatives_per_cluster:
            return False

        existing_reps = await self._clusters.get_all_representatives(cluster_id)
        if not existing_reps:
            return True

        # Check diversity
        for rep_embedding in existing_reps:
            # Assuming rep_embedding is np.ndarray or similar
            similarity = compute_face_similarity(decision.candidate.identity_vector, rep_embedding)
            if similarity > self._settings.representative_diversity_threshold:
                return False

        return True

    async def recompute_centroid(self, cluster_id: str) -> np.ndarray | None:
        """Recompute cluster centroid from representatives.

        Returns None if no representatives exist for the cluster.
        """
        reps = await self._clusters.get_all_representatives(cluster_id)
        if not reps:
            # No representatives yet - return None to signal no centroid update
            return None

        # Calculate mean vector
        # reps is Sequence[Any], assuming numpy arrays
        stacked = np.stack(reps)
        mean_vector = np.mean(stacked, axis=0)

        # Normalize
        norm = np.linalg.norm(mean_vector)
        if norm > 0:
            mean_vector = mean_vector / norm

        return cast(np.ndarray, mean_vector)

    async def persist_new_cluster(
        self,
        tenant_id: str,
        identities: list[MediaIdentity],
        similarities: list[float],
        algorithm: str = "graph",
    ) -> IdentityCluster:
        """Create a new cluster for the provided identities."""
        if len(identities) != len(similarities):
            raise ValueError("identities and similarities must have the same length")

        cluster = await self._clusters.save(
            IdentityCluster(
                id=None,
                tenant_id=tenant_id,
                label=None,
                is_labeled=False,
                member_count=len(identities),
                created_at=datetime.now(tz=UTC),
                clustering_algorithm=algorithm,
            )
        )
        member_data = [
            MemberData(identity_id=identity.id, similarity=similarity)
            for identity, similarity in zip(identities, similarities, strict=False)
        ]
        if cluster.id is None:
            raise ClusterNotFoundError("new cluster id missing after save")
        await self._members.bulk_add_members(cluster.id, member_data)

        # Create initial representative(s) from the highest-confidence identities
        if identities:
            # Sort by confidence descending and pick top few as representatives
            sorted_identities = sorted(identities, key=lambda i: i.confidence, reverse=True)
            num_reps = min(self._settings.max_representatives_per_cluster, len(sorted_identities))
            for i in range(num_reps):
                identity = sorted_identities[i]
                rep = ClusterRepresentative(
                    id=str(uuid.uuid4()),
                    cluster_id=cluster.id,
                    identity_id=identity.id,
                    embedding=identity.embedding,
                    created_at=datetime.now(tz=UTC),
                    tenant_id=tenant_id,
                )
                await self._clusters.add_representative(rep)

        return cluster

    async def update_cluster_metadata(
        self,
        cluster_id: str,
        label: str | None = None,
        representative_id: str | None = None,
    ) -> IdentityCluster:
        """Update cluster label or representative metadata."""
        cluster = await self._clusters.get_by_id(cluster_id)
        if not cluster:
            raise ClusterNotFoundError(cluster_id)

        cluster.label = label
        cluster.is_labeled = bool(label)
        if representative_id is not None:
            cluster.representative_identity_id = representative_id

        return await self._clusters.update(cluster)


class ClusterNotFoundError(Exception):
    """Raised when a cluster lookup fails."""

    def __init__(self, cluster_id: str) -> None:
        super().__init__(f"Cluster not found: {cluster_id}")
        self.cluster_id = cluster_id
