"""
Representative-Only Clustering for Cold Start.

A simple, deterministic clustering algorithm for the first batch of identities
when no clusters exist yet. Instead of using graph-based algorithms that can
create transitive connections, this approach:

1. Creates a singleton cluster for the first identity
2. For each subsequent identity, matches against existing representatives
3. If match found (>= high_confidence_threshold) → add to existing cluster
4. If match found (>= threshold but < high_confidence) → create suggestion
5. If no match → create new singleton cluster

Benefits for cold start:
- Deterministic: same input → same output
- No false fusions from transitive graph edges
- Every cluster starts pure (single source)
- Borderline matches create suggestions for user review
- User can easily merge singletons later
- Builds clean ground truth for future clustering
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from uuid import UUID

import numpy as np
from recognition.application.clustering.clustering_settings import ClusteringSettings

from db.models import IdentityCluster, MediaIdentity

logger = logging.getLogger(__name__)

# Type aliases for clustering callbacks
CreateClusterFn = Callable[[Sequence[MediaIdentity]], Awaitable[tuple[IdentityCluster, object]]]
AddToClusterFn = Callable[[UUID, Sequence[MediaIdentity]], Awaitable[None]]
AnchorEmbeddings = dict[UUID, list[np.ndarray]]
# Callback to create a suggestion: (identity_id, cluster_id, rep_similarity, avg_member_similarity) -> None
CreateSuggestionFn = Callable[[UUID, UUID, float, float], Awaitable[None]]


class RepresentativeOnlyClustering:
    """
    Simple sequential clustering using only representative matching.

    Designed for cold start scenarios where:
    - No existing clusters exist
    - False positives are catastrophic
    - User needs to build ground truth through confirmations

    Algorithm:
        for each identity in batch:
            if matches any existing representative >= high_confidence_threshold:
                add to that cluster (auto-assign)
            elif matches >= suggestion_threshold:
                create suggestion for user review, create singleton
            else:
                create new singleton cluster
    """

    def __init__(
        self,
        settings: ClusteringSettings,
        adaptive_threshold: float | None = None,
        create_suggestion: CreateSuggestionFn | None = None,
    ) -> None:
        self.settings = settings
        # Use adaptive threshold if provided, otherwise base threshold
        self.threshold = adaptive_threshold or settings.similarity_threshold
        # High confidence threshold for auto-assignment during early stage
        self.high_confidence_threshold = settings.early_stage_high_confidence_threshold
        # Suggestion threshold - matches above this create suggestions
        self.suggestion_threshold = self.threshold  # Use same as clustering threshold
        self._create_suggestion = create_suggestion

    async def cluster(
        self,
        identities: list[MediaIdentity],
        create_cluster: CreateClusterFn,
        anchor_embeddings: AnchorEmbeddings | None = None,
        add_to_cluster: AddToClusterFn | None = None,
        job_id: UUID | None = None,
    ) -> list[IdentityCluster]:
        """
        Cluster identities using representative-only matching.

        Args:
            identities: New identities to cluster.
            create_cluster: Callback to create new clusters.
            anchor_embeddings: Optional dict mapping cluster_id to representative embeddings.
                              Pre-existing clusters to match against.
            add_to_cluster: Optional callback to add members to existing clusters.
            job_id: Optional job ID for log correlation.

        Returns:
            List of newly created clusters (singletons if no matches).
        """
        log_prefix = f"[job={job_id}] " if job_id else ""

        if not identities:
            return []

        logger.info(
            "%sRepresentativeOnlyClustering: processing %d identities (threshold=%.4f)",
            log_prefix,
            len(identities),
            self.threshold,
        )

        # Track clusters created during this batch
        # We need to be able to match later identities against earlier ones
        created_clusters: list[IdentityCluster] = []

        # Local representative cache: cluster_id -> list of embeddings
        # Starts with anchor_embeddings (pre-existing clusters)
        local_representatives: dict[UUID, list[np.ndarray]] = {}
        if anchor_embeddings:
            for cluster_id, embs in anchor_embeddings.items():
                local_representatives[cluster_id] = [np.array(e, dtype=np.float32) for e in embs]

        # Track which clusters were created in this batch (for logging)
        batch_cluster_ids: set[UUID] = set()

        # Stats
        matched_to_existing = 0
        matched_to_new = 0
        new_singletons = 0
        suggestions_created = 0

        for identity in identities:
            identity_embedding = np.array(identity.embedding, dtype=np.float32)

            # Normalize if not already
            norm = np.linalg.norm(identity_embedding)
            if norm > 0:
                identity_embedding = identity_embedding / norm

            # Find best matching representative
            best_cluster_id: UUID | None = None
            best_similarity = 0.0

            for cluster_id, rep_embeddings in local_representatives.items():
                for rep_emb in rep_embeddings:
                    similarity = float(np.dot(identity_embedding, rep_emb))
                    if similarity > best_similarity:
                        best_similarity = similarity
                        best_cluster_id = cluster_id

            # Check if we have a high-confidence match (auto-assign)
            if best_cluster_id and best_similarity >= self.high_confidence_threshold:
                # High confidence - auto-add to existing cluster
                if best_cluster_id in batch_cluster_ids:
                    # Cluster was created in this batch - we have the cluster object
                    # Find the cluster in created_clusters
                    for cluster in created_clusters:
                        if cluster.id == best_cluster_id:
                            # Add member via create_cluster callback (it handles members)
                            # Actually we need add_to_cluster callback
                            if add_to_cluster:
                                await add_to_cluster(best_cluster_id, [identity])
                                matched_to_new += 1
                                logger.debug(
                                    "%sMatched identity %s to new cluster %s (sim=%.4f >= high_conf=%.4f)",
                                    log_prefix,
                                    identity.id,
                                    best_cluster_id,
                                    best_similarity,
                                    self.high_confidence_threshold,
                                )
                            else:
                                # No add_to_cluster callback (cold start) - create suggestion
                                # to let user confirm, rather than silently dropping
                                if self._create_suggestion:
                                    await self._create_suggestion(
                                        identity.id,
                                        best_cluster_id,
                                        best_similarity,
                                        best_similarity,
                                    )
                                    suggestions_created += 1
                                    logger.info(
                                        "%sNo add_to_cluster callback - created suggestion: "
                                        "identity %s -> batch cluster %s (sim=%.4f)",
                                        log_prefix,
                                        identity.id,
                                        best_cluster_id,
                                        best_similarity,
                                    )
                                else:
                                    # No suggestion callback either - create singleton
                                    cluster, _ = await create_cluster([identity])
                                    created_clusters.append(cluster)
                                    batch_cluster_ids.add(cluster.id)
                                    local_representatives[cluster.id] = [identity_embedding]
                                    new_singletons += 1
                                    logger.warning(
                                        "%sNo callbacks available - created singleton for identity %s "
                                        "(would have matched cluster %s at sim=%.4f)",
                                        log_prefix,
                                        identity.id,
                                        best_cluster_id,
                                        best_similarity,
                                    )
                            break
                else:
                    # Pre-existing cluster (from anchor_embeddings)
                    if add_to_cluster:
                        await add_to_cluster(best_cluster_id, [identity])
                        matched_to_existing += 1
                        logger.debug(
                            "%sMatched identity %s to existing cluster %s (sim=%.4f >= high_conf=%.4f)",
                            log_prefix,
                            identity.id,
                            best_cluster_id,
                            best_similarity,
                            self.high_confidence_threshold,
                        )
            elif best_cluster_id and best_similarity >= self.suggestion_threshold:
                # Borderline match - create singleton but also create suggestion
                cluster, _ = await create_cluster([identity])
                created_clusters.append(cluster)
                batch_cluster_ids.add(cluster.id)

                # Add to local representatives for matching subsequent identities
                local_representatives[cluster.id] = [identity_embedding]

                new_singletons += 1

                # Create suggestion for the borderline match
                # Only for pre-existing clusters (not clusters created in this batch)
                if self._create_suggestion and best_cluster_id not in batch_cluster_ids:
                    try:
                        await self._create_suggestion(
                            identity.id,  # identity_id - the identity that might belong to target cluster
                            best_cluster_id,  # to_cluster_id (existing cluster)
                            best_similarity,  # representative similarity
                            best_similarity,  # avg_member_similarity (use same for singleton)
                        )
                        suggestions_created += 1
                        logger.info(
                            "%sCreated suggestion: identity %s -> cluster %s (sim=%.4f)",
                            log_prefix,
                            identity.id,
                            best_cluster_id,
                            best_similarity,
                        )
                    except Exception as e:
                        logger.warning(
                            "%sFailed to create suggestion for %s -> %s: %s",
                            log_prefix,
                            cluster.id,
                            best_cluster_id,
                            e,
                        )
                else:
                    logger.debug(
                        "%sCreated singleton cluster %s for identity %s "
                        "(borderline match to %s, sim=%.4f, no suggestion callback or batch cluster)",
                        log_prefix,
                        cluster.id,
                        identity.id,
                        best_cluster_id,
                        best_similarity,
                    )
            else:
                # No match - create new singleton cluster
                cluster, _ = await create_cluster([identity])
                created_clusters.append(cluster)
                batch_cluster_ids.add(cluster.id)

                # Add to local representatives for matching subsequent identities
                # The first member becomes the representative
                local_representatives[cluster.id] = [identity_embedding]

                new_singletons += 1
                logger.debug(
                    "%sCreated singleton cluster %s for identity %s (best_sim=%.4f < threshold)",
                    log_prefix,
                    cluster.id,
                    identity.id,
                    best_similarity,
                )

        logger.info(
            "%sRepresentativeOnlyClustering complete: %d singletons created, "
            "%d matched to new clusters, %d matched to existing clusters, %d suggestions created",
            log_prefix,
            new_singletons,
            matched_to_new,
            matched_to_existing,
            suggestions_created,
        )

        return created_clusters
