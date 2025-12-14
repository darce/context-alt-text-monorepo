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
from recognition.shared.similarity import compute_face_similarity, extract_face_embedding


def _normalize_embedding(embedding: np.ndarray) -> np.ndarray:
    """Normalize a face embedding to unit length.

    Args:
        embedding: Raw embedding vector (512D or 1024D).

    Returns:
        Normalized 512D face embedding.
    """
    face_vec = extract_face_embedding(embedding)
    norm = float(np.linalg.norm(face_vec))
    if norm == 0:
        return face_vec.astype(np.float32)
    return face_vec.astype(np.float32) / norm


def _select_diverse_representatives(
    identities: list[MediaIdentity],
    max_reps: int,
) -> list[MediaIdentity]:
    """Select representatives via Farthest-Point Sampling for diversity.

    This algorithm ensures geometric diversity by selecting representatives
    that maximize minimum distance from already-chosen representatives,
    preventing the loss of "bridge" faces that connect different pose angles.

    Args:
        identities: Pool of candidate identities.
        max_reps: Maximum number of representatives to select.

    Returns:
        Selected representatives in insertion order (first is highest confidence).
    """
    if not identities:
        return []
    k = min(max_reps, len(identities))

    # Seed with highest-confidence face
    sorted_by_conf = sorted(identities, key=lambda i: i.confidence, reverse=True)
    selected: list[MediaIdentity] = [sorted_by_conf[0]]
    selected_vecs: list[np.ndarray] = [_normalize_embedding(np.asarray(sorted_by_conf[0].embedding, dtype=np.float32))]
    remaining = set(range(1, len(sorted_by_conf)))

    for _ in range(k - 1):
        if not remaining:
            break
        best_idx: int | None = None
        best_min_dist = -1.0
        for idx in remaining:
            vec = _normalize_embedding(np.asarray(sorted_by_conf[idx].embedding, dtype=np.float32))
            # Distance = 1 - cosine_similarity (since embeddings are normalized)
            min_dist = min(float(1 - np.dot(vec, sv)) for sv in selected_vecs)
            if min_dist > best_min_dist:
                best_min_dist = min_dist
                best_idx = idx
        if best_idx is None:
            break
        selected.append(sorted_by_conf[best_idx])
        selected_vecs.append(_normalize_embedding(np.asarray(sorted_by_conf[best_idx].embedding, dtype=np.float32)))
        remaining.remove(best_idx)

    return selected


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

        # Create initial representative(s) using diversity-aware sampling (FPS)
        # to preserve "bridge" faces that connect different pose angles
        if identities:
            diverse_reps = _select_diverse_representatives(
                identities,
                self._settings.max_representatives_per_cluster,
            )
            for identity in diverse_reps:
                rep = ClusterRepresentative(
                    id=str(uuid.uuid4()),
                    cluster_id=cluster.id,
                    identity_id=identity.id,
                    embedding=identity.embedding,
                    created_at=datetime.now(tz=UTC),
                    tenant_id=tenant_id,
                )
                await self._clusters.add_representative(rep)

            # Recompute and persist the centroid immediately.
            # Without this, CentroidDiscovery cannot find this cluster in subsequent batches.
            new_centroid = await self.recompute_centroid(cluster.id)
            if new_centroid is not None:
                cluster.centroid = new_centroid
                await self._clusters.update(cluster)

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

    async def assign_to_existing_cluster(
        self,
        identity: MediaIdentity,
        cluster_id: str,
        similarity: float,
    ) -> None:
        """Assign an identity to an existing cluster via representative match."""
        cluster = await self._clusters.get_by_id(cluster_id)
        if not cluster:
            raise ClusterNotFoundError(cluster_id)

        # Add as member
        await self._members.add_member(
            cluster_id=cluster_id,
            identity_id=identity.id,
            similarity=similarity,
        )

        # Optionally add as representative if diverse enough
        existing_reps = await self._clusters.get_all_representatives(cluster_id)
        current_count = len(existing_reps) if existing_reps else 0

        if current_count < self._settings.max_representatives_per_cluster:
            is_diverse = True
            if existing_reps:
                identity_vec = np.array(identity.embedding, dtype=np.float32)
                for rep_embedding in existing_reps:
                    rep_sim = compute_face_similarity(identity_vec, rep_embedding)
                    if rep_sim > self._settings.representative_diversity_threshold:
                        is_diverse = False
                        break

            if is_diverse:
                rep = ClusterRepresentative(
                    id=str(uuid.uuid4()),
                    cluster_id=cluster_id,
                    identity_id=identity.id,
                    embedding=identity.embedding,
                    created_at=datetime.now(tz=UTC),
                    tenant_id=identity.tenant_id,
                )
                await self._clusters.add_representative(rep)

        # Update member count
        cluster.member_count += 1
        await self._clusters.update(cluster)


class ClusterNotFoundError(Exception):
    """Raised when a cluster lookup fails."""

    def __init__(self, cluster_id: str) -> None:
        super().__init__(f"Cluster not found: {cluster_id}")
        self.cluster_id = cluster_id
