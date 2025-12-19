"""
AssignmentWriter interface for persisting gate decisions (Phase 5).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

import numpy as np

from recognition.application.assignment.decision import AssignmentDecision, AssignmentOutcome
from recognition.application.settings.clustering import ClusteringSettings
from recognition.domain.cluster import IdentityCluster
from recognition.domain.identity import MediaIdentity
from recognition.domain.locator import IdentityLocator
from recognition.domain.repositories import ClusterRepository, MemberData, MemberRepository
from recognition.domain.representative import ClusterRepresentative
from recognition.observability.recognition_runs import RecognitionRunContext
from recognition.shared.similarity import compute_face_similarity, extract_face_embedding


@dataclass(frozen=True)
class IdentityMember:
    """Domain representation of a cluster member."""

    id: str
    cluster_id: str
    identity_id: str
    similarity: float
    tenant_id: str | None = None
    assigned_at: datetime | None = None


def _compute_fingerprint(embedding: np.ndarray) -> str:
    """Compute a stable fingerprint for a face embedding."""
    import hashlib

    # Use face-only portion for fingerprinting
    face_vec = extract_face_embedding(embedding)
    return hashlib.sha256(face_vec.tobytes()).hexdigest()[:8]


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


def _compute_identity_quality(identity: MediaIdentity) -> float:
    """Compute quality score for a media identity.

    Quality is computed from:
    - Detection confidence: 60% (primary signal from InsightFace)
    - Face size: 40% (larger faces = more reliable embeddings)

    Args:
        identity: MediaIdentity with confidence and bbox dimensions.

    Returns:
        Quality score between 0.0 and 1.0.
    """
    # Detection score component (60% weight)
    det_component = identity.confidence * 0.6

    # Face size component (40% weight)
    # Large (>20000 px²) = 1.0, Medium (5000-20000) = 0.7, Small (<5000) = 0.4
    bbox_area = identity.bbox_width * identity.bbox_height
    if bbox_area > 20000:
        size_score = 1.0
    elif bbox_area > 5000:
        size_score = 0.7
    else:
        size_score = 0.4
    size_component = size_score * 0.4

    return round(det_component + size_component, 3)


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
        *,
        run_context: RecognitionRunContext | None = None,
    ) -> None:
        self._settings = settings
        self._clusters = cluster_repository
        self._members = member_repository
        self._run_context = run_context

    def bind_run_context(self, context: RecognitionRunContext | None) -> None:
        """Attach or clear the active recognition run context.

        Args:
            context: Run context for emitting `recognition_events`, or None to disable event emission.
        """
        self._run_context = context

    def _emit_cluster_created_event(
        self,
        *,
        cluster_id: str,
        identities: list[MediaIdentity],
        similarities: list[float],
        algorithm: str,
    ) -> None:
        """Emit a `cluster_created` event when a run context is available.

        Args:
            cluster_id: Newly created cluster UUID (string form).
            identities: Initial member identities for the cluster.
            similarities: Similarity scores aligned with `identities`.
            algorithm: Cluster creation algorithm label (e.g. "graph").
        """
        if self._run_context is None:
            return

        members: list[dict[str, object]] = []
        for identity, similarity in zip(identities, similarities, strict=False):
            member_payload: dict[str, object] = {
                "identity_id": identity.id,
                "similarity": float(similarity),
                "embedding_fingerprint": _compute_fingerprint(identity.embedding),
            }
            locator_payload = _locator_payload(identity)
            if locator_payload is not None:
                member_payload["identity_locator"] = locator_payload
            members.append(member_payload)

        self._run_context.add_event(
            event_type="cluster_created",
            cluster_id=cluster_id,
            payload={
                "creation_method": algorithm,
                "member_count": len(identities),
                "members": members,
            },
        )

    def _emit_representative_selected_event(
        self,
        *,
        cluster_id: str,
        identity: MediaIdentity,
        reason: str,
        quality_score: float | None = None,
        diversity_score: float | None = None,
    ) -> None:
        """Emit a `representative_selected` event when a run context is available.

        Args:
            cluster_id: Cluster UUID (string form).
            identity: Selected representative identity.
            reason: Selection reason (e.g. "fps_seed", "diverse_addition").
            quality_score: Optional quality score for the representative.
            diversity_score: Optional diversity score for the representative.
        """
        if self._run_context is None:
            return

        payload: dict[str, object] = {"reason": reason}
        if quality_score is not None:
            payload["quality_score"] = float(quality_score)
        if diversity_score is not None:
            payload["diversity_score"] = float(diversity_score)

        locator_payload = _locator_payload(identity)
        if locator_payload is not None:
            payload["identity_locator"] = locator_payload

        self._run_context.add_event(
            event_type="representative_selected",
            identity_id=identity.id,
            cluster_id=cluster_id,
            payload=payload,
        )

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
            quality = _compute_identity_quality(decision.candidate.identity)
            rep = ClusterRepresentative(
                id=str(uuid.uuid4()),
                cluster_id=decision.candidate.cluster_id,
                identity_id=decision.candidate.identity.id,
                embedding=full_embedding,
                created_at=datetime.now(tz=UTC),
                tenant_id=decision.candidate.identity.tenant_id,
                quality_score=quality,
            )
            await self._clusters.add_representative(rep)
            self._emit_representative_selected_event(
                cluster_id=decision.candidate.cluster_id,
                identity=decision.candidate.identity,
                reason="diverse_addition",
                quality_score=rep.quality_score,
                diversity_score=rep.diversity_score,
            )
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
        for rep in existing_reps:
            rep_embedding = cast(np.ndarray, getattr(rep, "embedding", rep))
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
        # Handle both raw embedding vectors and full ClusterRepresentative objects
        rep_vecs = [cast(np.ndarray, getattr(r, "embedding", r)) for r in reps]
        stacked = np.stack(rep_vecs)
        mean_vector = np.mean(stacked, axis=0)

        # Normalize
        norm = np.linalg.norm(mean_vector)
        if norm > 0:
            mean_vector = mean_vector / norm

        return cast(np.ndarray, mean_vector)

    async def recompute_representatives(self, cluster_id: str) -> None:
        """Recompute cluster representatives using FPS for diversity."""
        cluster = await self._clusters.get_by_id(cluster_id)
        if not cluster:
            raise ClusterNotFoundError(cluster_id)

        # Clear all stored representatives first to avoid stale/incremental drift.
        await self._clusters.clear_representatives(cluster_id)

        identities = list(await self._clusters.get_member_identities(cluster_id))
        identities = [identity for identity in identities if identity.embedding is not None]
        if not identities:
            cluster.representative_identity_id = None
            await self._clusters.update(cluster)
            return

        selected = _select_diverse_representatives(
            identities,
            self._settings.max_representatives_per_cluster,
        )

        # Promote the first selected rep as the cluster "primary" representative.
        cluster.representative_identity_id = selected[0].id
        await self._clusters.update(cluster)

        for identity in selected:
            quality = _compute_identity_quality(identity)
            rep = ClusterRepresentative(
                id=str(uuid.uuid4()),
                cluster_id=cluster_id,
                identity_id=identity.id,
                embedding=identity.embedding,
                created_at=datetime.now(tz=UTC),
                tenant_id=identity.tenant_id,
                quality_score=quality,
            )
            await self._clusters.add_representative(rep)
            self._emit_representative_selected_event(
                cluster_id=cluster_id,
                identity=identity,
                reason="fps_recompute",
                quality_score=rep.quality_score,
                diversity_score=rep.diversity_score,
            )

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
        self._emit_cluster_created_event(
            cluster_id=cluster.id,
            identities=identities,
            similarities=similarities,
            algorithm=algorithm,
        )

        # Create initial representative(s) using diversity-aware sampling (FPS)
        # to preserve "bridge" faces that connect different pose angles
        if identities:
            diverse_reps = _select_diverse_representatives(
                identities,
                self._settings.max_representatives_per_cluster,
            )
            for identity in diverse_reps:
                quality = _compute_identity_quality(identity)
                rep = ClusterRepresentative(
                    id=str(uuid.uuid4()),
                    cluster_id=cluster.id,
                    identity_id=identity.id,
                    embedding=identity.embedding,
                    created_at=datetime.now(tz=UTC),
                    tenant_id=tenant_id,
                    quality_score=quality,
                    image_phash=identity.image_phash,
                )
                await self._clusters.add_representative(rep)
                self._emit_representative_selected_event(
                    cluster_id=cluster.id,
                    identity=identity,
                    reason="fps_seed",
                    quality_score=rep.quality_score,
                    diversity_score=rep.diversity_score,
                )

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
                for rep in existing_reps:
                    rep_embedding = cast(np.ndarray, getattr(rep, "embedding", rep))
                    rep_sim = compute_face_similarity(identity_vec, rep_embedding)
                    if rep_sim > self._settings.representative_diversity_threshold:
                        is_diverse = False
                        break

            if is_diverse:
                quality = _compute_identity_quality(identity)
                rep = ClusterRepresentative(
                    id=str(uuid.uuid4()),
                    cluster_id=cluster_id,
                    identity_id=identity.id,
                    embedding=identity.embedding,
                    created_at=datetime.now(tz=UTC),
                    tenant_id=identity.tenant_id,
                    quality_score=quality,
                    image_phash=identity.image_phash,
                )
                await self._clusters.add_representative(rep)
                self._emit_representative_selected_event(
                    cluster_id=cluster_id,
                    identity=identity,
                    reason="diverse_addition",
                    quality_score=rep.quality_score,
                    diversity_score=rep.diversity_score,
                )

        # Update member count
        cluster.member_count += 1
        await self._clusters.update(cluster)


class ClusterNotFoundError(Exception):
    """Raised when a cluster lookup fails."""

    def __init__(self, cluster_id: str) -> None:
        super().__init__(f"Cluster not found: {cluster_id}")
        self.cluster_id = cluster_id


def _locator_payload(identity: MediaIdentity) -> dict[str, object] | None:
    if identity.bbox_x is None or identity.bbox_y is None:
        return None
    try:
        return IdentityLocator(
            media_id=int(identity.media_id),
            bbox_x=int(identity.bbox_x),
            bbox_y=int(identity.bbox_y),
            bbox_width=int(identity.bbox_width),
            bbox_height=int(identity.bbox_height),
            crop_hash=None,
        ).to_dict()
    except (TypeError, ValueError):
        return None
