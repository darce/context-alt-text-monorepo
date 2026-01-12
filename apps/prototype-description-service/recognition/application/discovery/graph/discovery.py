"""Graph-based discovery (HDBSCAN) for assignment candidates."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from typing import cast

import numpy as np

from recognition.application.assignment.candidate import AssignmentCandidate, DiscoveryMethod
from recognition.application.discovery.base import DiscoveryAlgorithm
from recognition.application.discovery.graph.algorithm import AnchorIdentity, GraphAlgorithm, GraphDiscoveryResult
from recognition.application.discovery.graph.helpers import (
    compute_avg_similarity,
    compute_embedding_stats,
    compute_member_similarities,
    group_by_label,
    match_to_anchor,
    resolve_anchor_conflict,
)
from recognition.application.discovery.graph.selection import describe_algorithm, hdbscan_available, select_algorithm
from recognition.application.discovery.graph.verification import verify_complete_link
from recognition.application.settings import ClusteringSettings
from recognition.application.similarity import SimilaritySearch
from recognition.domain.identity import MediaIdentity
from recognition.observability.recognition_runs import RecognitionRunContext
from recognition.shared.similarity import normalize_face_embedding

logger = logging.getLogger(__name__)


class GraphDiscovery(DiscoveryAlgorithm):
    """Find candidate assignments via graph clustering outputs."""

    discovery_method = DiscoveryMethod.GRAPH

    def __init__(
        self,
        settings: ClusteringSettings,
        algorithm: GraphAlgorithm | None = None,
        *,
        run_context: RecognitionRunContext | None = None,
    ) -> None:
        """Initialize the graph discovery algorithm."""
        self.settings = settings
        self.algorithm = algorithm
        self._search = SimilaritySearch(settings)
        self._run_context = run_context

    def bind_run_context(self, context: RecognitionRunContext | None) -> None:
        """Attach or clear the active recognition run context."""
        self._run_context = context

    def _emit_graph_run_event(self, payload: dict[str, object]) -> None:
        """Emit a `graph_run` event when a run context is available."""
        if self._run_context is None:
            return
        self._run_context.add_event(event_type="graph_run", payload=payload)

    def set_algorithm(self, algorithm: GraphAlgorithm) -> None:
        """Set the clustering algorithm implementation to use."""
        self.algorithm = algorithm

    @property
    def algorithm_name(self) -> str:
        """Return a human-readable name for the active graph algorithm."""
        if self.algorithm is None:
            return "unknown"
        label, _ = describe_algorithm(self.algorithm)
        return label

    def _apply_complete_link(
        self,
        candidate: AssignmentCandidate,
        anchor_embeddings: dict[str, list[np.ndarray]],
    ) -> AssignmentCandidate:
        if not self.settings.complete_link_enabled or not candidate.cluster_id:
            return candidate

        cluster_members = anchor_embeddings.get(candidate.cluster_id, [])
        passed, min_sim, coverage = verify_complete_link(
            candidate.identity_vector,
            cluster_members,
            min_similarity=self.settings.complete_link_threshold,
            min_coverage=self.settings.complete_link_min_coverage,
        )
        if passed:
            return candidate

        logger.info(
            "[GraphDiscovery] Complete-link REJECTED identity=%s cluster=%s min_sim=%.3f coverage=%.2f",
            candidate.identity.id,
            candidate.cluster_id,
            min_sim,
            coverage,
        )
        candidate.discovery_similarity = min_sim
        candidate.anchor_linked = False
        return candidate

    @staticmethod
    def _build_anchor_injections(
        anchor_embeddings: dict[str, list[np.ndarray]],
        inject_anchors: bool,
    ) -> tuple[list[AnchorIdentity], list[np.ndarray]]:
        if not inject_anchors or not anchor_embeddings:
            return [], []

        anchors: list[AnchorIdentity] = []
        anchor_vecs: list[np.ndarray] = []
        for cluster_id, reps in anchor_embeddings.items():
            for rep in reps:
                anchor = AnchorIdentity(
                    id=f"anchor-{uuid.uuid4()}",
                    cluster_id=cluster_id,
                )
                anchors.append(anchor)
                anchor_vecs.append(normalize_face_embedding(np.asarray(rep, dtype=np.float32)))

        return anchors, anchor_vecs

    async def discover(
        self,
        identities: Sequence[MediaIdentity],
        anchor_embeddings: dict[str, list[np.ndarray]],
        inject_anchors: bool = True,
    ) -> GraphDiscoveryResult:
        """Generate candidates and new-cluster groups via graph algorithms."""
        if not identities:
            return GraphDiscoveryResult([], [])

        anchors, anchor_vecs = self._build_anchor_injections(anchor_embeddings, inject_anchors)

        face_vectors = [identity.face_vector for identity in identities]

        combined_identities = list(identities) + anchors
        combined_vectors = face_vectors + anchor_vecs

        algorithm = select_algorithm(algorithm=self.algorithm, settings=self.settings)
        algorithm_label, algorithm_params = describe_algorithm(algorithm)
        hdbscan_limit = self.settings.hdbscan_max_batch_size or 500
        logger.info(
            "[GraphDiscovery] Starting discovery: identities=%d anchors=%d combined=%d inject_anchors=%s algorithm=%s hdbscan_available=%s hdbscan_limit=%d params=%s",
            len(identities),
            len(anchors),
            len(combined_identities),
            inject_anchors,
            algorithm_label,
            hdbscan_available(),
            hdbscan_limit,
            algorithm_params,
        )
        embedding_stats = compute_embedding_stats(face_vectors)
        labels = algorithm.cluster(combined_vectors, cast(list[MediaIdentity], combined_identities))

        if len(labels) != len(combined_identities):
            raise ValueError("Graph algorithm returned mismatched labels")

        grouped = group_by_label(combined_identities, combined_vectors, labels)

        candidates: list[AssignmentCandidate] = []
        new_clusters: list[tuple[list[MediaIdentity], list[float]]] = []

        for _label, items in grouped.items():
            group_anchors = [item for item, _ in items if isinstance(item, AnchorIdentity)]
            new_members_with_vecs = [(item, vec) for item, vec in items if isinstance(item, MediaIdentity)]

            if not new_members_with_vecs:
                continue

            new_members = [m for m, _ in new_members_with_vecs]
            member_vectors_group = [v for _, v in new_members_with_vecs]

            target_cluster_id: str | None = None
            similarity = 0.0

            if group_anchors:
                target_cluster_id = resolve_anchor_conflict(group_anchors)
                matched_anchor_vecs = [
                    v for item, v in items if isinstance(item, AnchorIdentity) and item.cluster_id == target_cluster_id
                ]
                similarity = compute_avg_similarity(member_vectors_group, matched_anchor_vecs)
            else:
                if not inject_anchors and anchor_embeddings:
                    target_cluster_id, similarity = match_to_anchor(member_vectors_group, anchor_embeddings)

            threshold = (
                self.settings.anchor_discovery_threshold if group_anchors else self.settings.similarity_threshold
            )
            if target_cluster_id and similarity >= threshold:
                for member, member_vec in new_members_with_vecs:
                    candidate = AssignmentCandidate(
                        identity=member,
                        identity_vector=member_vec,
                        cluster_id=target_cluster_id,
                        discovery_method=self.discovery_method,
                        discovery_similarity=similarity,
                        anchor_linked=bool(group_anchors),
                    )
                    candidates.append(self._apply_complete_link(candidate, anchor_embeddings))
            else:
                member_sims = compute_member_similarities(member_vectors_group)
                new_clusters.append((new_members, member_sims))

        noise_identities = [
            (identity, face_vec)
            for identity, face_vec, label in zip(combined_identities, combined_vectors, labels, strict=False)
            if label == -1 and isinstance(identity, MediaIdentity)
        ]

        if noise_identities:
            if anchor_embeddings:
                matches = self._search.find_best_matches(
                    [face_vec for _, face_vec in noise_identities],
                    anchor_embeddings,
                    min_similarity=self.settings.anchor_discovery_threshold,
                )
                for (identity, face_vec), match in zip(noise_identities, matches, strict=False):
                    if match:
                        candidate = AssignmentCandidate(
                            identity=identity,
                            identity_vector=face_vec,
                            cluster_id=match.cluster_id,
                            discovery_method=self.discovery_method,
                            discovery_similarity=match.similarity,
                            anchor_linked=True,
                        )
                        candidates.append(self._apply_complete_link(candidate, anchor_embeddings))
                    else:
                        new_clusters.append(([identity], [1.0]))
            else:
                for identity, _ in noise_identities:
                    new_clusters.append(([identity], [1.0]))

        cluster_count = len({label for label in labels if label != -1})
        noise_count = sum(1 for label in labels if label == -1)
        logger.info(
            "[GraphDiscovery] Completed: algorithm=%s clusters=%d noise=%d candidates=%d new_clusters=%d",
            algorithm_label,
            cluster_count,
            noise_count,
            len(candidates),
            len(new_clusters),
        )
        self._emit_graph_run_event(
            {
                "algorithm": algorithm_label,
                "params": algorithm_params,
                "identity_count": len(identities),
                "anchor_count": len(anchors),
                "combined_count": len(combined_identities),
                "inject_anchors": bool(inject_anchors),
                "embedding_stats": embedding_stats,
                "outputs": {
                    "cluster_count": cluster_count,
                    "noise_count": noise_count,
                    "candidate_count": len(candidates),
                    "new_cluster_count": len(new_clusters),
                },
            }
        )

        return GraphDiscoveryResult(candidates, new_clusters)
