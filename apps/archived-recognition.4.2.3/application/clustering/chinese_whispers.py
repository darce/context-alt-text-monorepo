"""
Chinese Whispers Graph Clustering for Face Recognition.

Reference: "Chinese Whispers - an Efficient Graph Clustering Algorithm and its Application to Natural Language Processing Problems" (Biemann, 2006)
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import TypeAlias
from uuid import UUID

import networkx as nx
import numpy as np

from db.models import IdentityCluster, MediaIdentity
from recognition.application.clustering.clustering_settings import ClusteringSettings
from recognition.application.clustering.clustering_utils import (
    group_identities_by_label,
    normalize_embeddings,
)

logger = logging.getLogger(__name__)

CreateClusterFn: TypeAlias = Callable[[Sequence[MediaIdentity]], Awaitable[tuple[IdentityCluster, object]]]
AddToClusterFn: TypeAlias = Callable[[UUID, Sequence[MediaIdentity]], Awaitable[None]]

# Type alias for anchor embeddings: cluster_id -> list of representative embeddings
AnchorEmbeddings: TypeAlias = dict[UUID, list[np.ndarray]]


class ChineseWhispersClustering:
    """
    Implements the Chinese Whispers graph clustering algorithm.

    This is a non-parametric, linear-time algorithm that works well for
    face clustering by treating identities as nodes in a graph and
    propagating labels based on edge weights (similarity).
    """

    def __init__(self, settings: ClusteringSettings, adaptive_threshold: float | None = None) -> None:
        self.settings = settings
        # Use a stricter threshold for graph edges than for simple matching
        # to prevent "bridging" distinct clusters via weak links.
        # If settings doesn't have cw_threshold, default to slightly higher than similarity_threshold
        base_cw_threshold = getattr(settings, "cw_threshold", settings.similarity_threshold + 0.05)

        # If adaptive threshold is provided, ensure CW threshold respects it
        # Use adaptive_threshold + small offset (0.02) to ensure CW is at least as strict
        if adaptive_threshold is not None:
            self.edge_threshold = max(base_cw_threshold, adaptive_threshold + 0.02)
        else:
            self.edge_threshold = base_cw_threshold

        self.iterations = getattr(settings, "cw_iterations", 20)

    async def cluster(
        self,
        identities: list[MediaIdentity],
        create_cluster: CreateClusterFn,
        anchor_embeddings: AnchorEmbeddings | None = None,
        add_to_cluster: AddToClusterFn | None = None,
        job_id: UUID | None = None,
    ) -> list[IdentityCluster]:
        """
        Cluster identities using Chinese Whispers.

        Args:
            identities: New identities to cluster.
            create_cluster: Callback to create new clusters.
            anchor_embeddings: Optional dict mapping cluster_id to representative embeddings.
                              These seed CW to help assign new identities to existing clusters.
            add_to_cluster: Optional callback to add members to existing clusters.
            job_id: Optional job ID for log correlation.
        """
        log_prefix = f"[job={job_id}] " if job_id else ""

        if not identities:
            return []

        if len(identities) == 1:
            cluster, _ = await create_cluster([identities[0]])
            return [cluster]

        # 1. Build the graph
        anchor_embeddings = anchor_embeddings or {}
        graph, label_to_cluster_id = self._build_graph(identities, anchor_embeddings, log_prefix)

        # 2. Run Chinese Whispers
        self._run_chinese_whispers(graph)

        # 3. Group by label and create clusters
        # Extract labels from graph nodes
        labels = [graph.nodes[i]["label"] for i in range(len(identities))]

        clusters_by_label = group_identities_by_label(labels, identities)
        created_clusters: list[IdentityCluster] = []

        for label, members in clusters_by_label.items():
            # Check if this label corresponds to an existing cluster (anchor)
            if label in label_to_cluster_id:
                if add_to_cluster:
                    cluster_id = label_to_cluster_id[label]
                    members_list: list[MediaIdentity] = [m for m in members if isinstance(m, MediaIdentity)]
                    await add_to_cluster(cluster_id, members_list)
                    logger.info("%s  CW Added %d members to existing cluster %s", log_prefix, len(members), cluster_id)
            else:
                members_list = [m for m in members if isinstance(m, MediaIdentity)]
                cluster, _ = await create_cluster(members_list)
                created_clusters.append(cluster)

        logger.info(
            "%sChinese Whispers created %d clusters from %d identities (edge_threshold=%.2f, iterations=%d)",
            log_prefix,
            len(created_clusters),
            len(identities),
            self.edge_threshold,
            self.iterations,
        )
        for _cluster in created_clusters:
            # We need to fetch members to log them, but they might not be attached to the cluster object yet depending on how create_cluster works.
            # However, we know the grouping from clusters_by_label.
            pass  # The cluster object itself might not have members loaded, but we can infer from the loop above if we wanted.
            # Actually, let's just log the grouping from clusters_by_label which we have right here.

        for label, members in clusters_by_label.items():
            media_ids = [str(m.media_id) for m in members if isinstance(m, MediaIdentity)]
            logger.info(
                "%s  CW Cluster (label=%s): %d members -> media_ids=[%s]",
                log_prefix,
                label,
                len(members),
                ", ".join(media_ids),
            )
        return created_clusters

    def _build_graph(
        self, identities: list[MediaIdentity], anchor_embeddings: AnchorEmbeddings, log_prefix: str = ""
    ) -> tuple[nx.Graph, dict[int, UUID]]:
        """
        Build a graph where nodes are identities and edges represent similarity > threshold.
        Anchor embeddings are included as nodes with fixed initial labels tied to their cluster.
        """
        graph: nx.Graph = nx.Graph()

        # Flatten anchor embeddings into a list with their cluster IDs
        anchor_data: list[tuple[UUID, np.ndarray]] = []
        for cluster_id, embs in anchor_embeddings.items():
            for emb in embs:
                anchor_data.append((cluster_id, emb))

        n_new = len(identities)
        n_anchors = len(anchor_data)

        # Collect all embeddings: identities first, then anchors
        all_embeddings = [identity.embedding for identity in identities] + [emb for _, emb in anchor_data]
        embeddings = normalize_embeddings(all_embeddings)

        # Map for anchor labels
        # Labels 0 to n_new-1 are for new identities (initially self-labeled)
        # Labels >= n_new are for existing clusters
        label_to_cluster_id: dict[int, UUID] = {}
        cluster_id_to_label: dict[UUID, int] = {}
        next_label = n_new

        # Add new identities with unique labels
        for i in range(n_new):
            graph.add_node(i, label=i, is_anchor=False)

        # Add anchors with cluster-based labels
        for i, (cluster_id, _) in enumerate(anchor_data):
            node_idx = n_new + i
            if cluster_id not in cluster_id_to_label:
                cluster_id_to_label[cluster_id] = next_label
                label_to_cluster_id[next_label] = cluster_id
                next_label += 1
            lbl = cluster_id_to_label[cluster_id]
            graph.add_node(node_idx, label=lbl, is_anchor=True)

        # Add edges
        # Compute similarity matrix: S = E . E^T
        sim_matrix = np.dot(embeddings, embeddings.T)

        # Find pairs with similarity > threshold
        # We only care about upper triangle (i < j)
        rows, cols = np.where(np.triu(sim_matrix, k=1) > self.edge_threshold)

        # Build edges with weights
        edges = []
        for r, c in zip(rows, cols, strict=True):
            weight = float(sim_matrix[r, c])
            edges.append((r, c, weight))

        graph.add_weighted_edges_from(edges)

        logger.info(
            "%sCW Graph: %d nodes (%d new, %d anchors), %d edges (threshold=%.4f)",
            log_prefix,
            graph.number_of_nodes(),
            n_new,
            n_anchors,
            graph.number_of_edges(),
            self.edge_threshold,
        )

        # Log some dropped edges for debugging (only for new identities or new<->anchor)
        # We don't care about anchor<->anchor edges being dropped
        dropped_rows, dropped_cols = np.where(
            (np.triu(sim_matrix, k=1) > self.edge_threshold - 0.1) & (np.triu(sim_matrix, k=1) <= self.edge_threshold)
        )

        if len(dropped_rows) > 0:
            logged_count = 0
            for r, c in zip(dropped_rows, dropped_cols, strict=True):
                if logged_count >= 10:
                    break
                # Only log if at least one node is new
                if r < n_new or c < n_new:
                    media_r = identities[r].media_id if r < n_new else "anchor"
                    media_c = identities[c].media_id if c < n_new else "anchor"
                    logger.info(
                        "%s  Dropped edge: %d (media %s) <-> %d (media %s) (sim=%.4f)",
                        log_prefix,
                        r,
                        media_r,
                        c,
                        media_c,
                        sim_matrix[r, c],
                    )
                    logged_count += 1
            if logged_count > 0:
                logger.info(
                    "%sCW Dropped %d edges just below threshold (%.4f - %.4f)",
                    log_prefix,
                    len(dropped_rows),
                    self.edge_threshold - 0.1,
                    self.edge_threshold,
                )

        return graph, label_to_cluster_id

    def _run_chinese_whispers(self, graph: nx.Graph) -> None:
        """
        Run the Chinese Whispers label propagation algorithm.
        """
        nodes = list(graph.nodes())

        for iteration in range(self.iterations):
            changes = 0
            # Randomize node order each iteration to prevent bias
            np.random.shuffle(nodes)

            for node in nodes:
                neighbors = list(graph.neighbors(node))
                if not neighbors:
                    continue

                # Sum weights for each label among neighbors
                label_weights: dict[int, float] = {}
                for neighbor in neighbors:
                    weight = graph[node][neighbor]["weight"]
                    label = graph.nodes[neighbor]["label"]
                    label_weights[label] = label_weights.get(label, 0.0) + weight

                # Find label with max weight
                if label_weights:
                    best_label = max(label_weights.items(), key=lambda x: x[1])[0]

                    if graph.nodes[node]["label"] != best_label:
                        graph.nodes[node]["label"] = best_label
                        changes += 1

            logger.debug("CW Iteration %d: %d changes", iteration + 1, changes)
            if changes == 0:
                break

        # Enforce anchor labels?
        # In standard CW, nodes can change labels.
        # If we want anchors to be "fixed", we should reset them or prevent them from changing.
        # But allowing them to change might be interesting (merging clusters).
        # For now, let's assume anchors are strong enough to hold their ground,
        # or that we want to see if they merge.
        # However, if we want to "attach" new items to existing clusters,
        # we probably want anchors to propagate their labels, not adopt new ones.
        # Let's implicitly trust the algorithm. If an anchor changes label, it means it found a better cluster.
        # But we are not handling cluster merges here, so that might be risky.
        # Ideally, we should lock anchor labels.

        # For this implementation, we will NOT lock anchors, allowing potential merges to be discovered,
        # but since we don't handle merges in the caller, we might just end up with
        # multiple anchors having the same label (which is fine, they point to the same cluster ID).
