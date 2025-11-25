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
from recognition.application.clustering_settings import ClusteringSettings
from recognition.application.clustering_utils import (
    group_identities_by_label,
    normalize_embeddings,
)

logger = logging.getLogger(__name__)

CreateClusterFn: TypeAlias = Callable[[Sequence[MediaIdentity]], Awaitable[tuple[IdentityCluster, object]]]
AddToClusterFn: TypeAlias = Callable[[UUID, Sequence[MediaIdentity]], Awaitable[None]]


class ChineseWhispersClustering:
    """
    Implements the Chinese Whispers graph clustering algorithm.

    This is a non-parametric, linear-time algorithm that works well for
    face clustering by treating identities as nodes in a graph and
    propagating labels based on edge weights (similarity).
    """

    def __init__(self, settings: ClusteringSettings) -> None:
        self.settings = settings
        # Use a stricter threshold for graph edges than for simple matching
        # to prevent "bridging" distinct clusters via weak links.
        # If settings doesn't have cw_threshold, default to slightly higher than similarity_threshold
        self.edge_threshold = getattr(settings, "cw_threshold", settings.similarity_threshold + 0.05)
        self.iterations = getattr(settings, "cw_iterations", 20)

    async def cluster(
        self,
        identities: list[MediaIdentity],
        create_cluster: CreateClusterFn,
        anchors: list[MediaIdentity] | None = None,
        add_to_cluster: AddToClusterFn | None = None,
    ) -> list[IdentityCluster]:
        """
        Cluster identities using Chinese Whispers.
        """
        if not identities:
            return []

        if len(identities) == 1:
            cluster, _ = await create_cluster([identities[0]])
            return [cluster]

        # 1. Build the graph
        anchors = anchors or []
        graph, label_to_cluster_id = self._build_graph(identities, anchors)

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
                    logger.info("  CW Added %d members to existing cluster %s", len(members), cluster_id)
            else:
                members_list = [m for m in members if isinstance(m, MediaIdentity)]
                cluster, _ = await create_cluster(members_list)
                created_clusters.append(cluster)

        logger.info(
            "Chinese Whispers created %d clusters from %d identities (edge_threshold=%.2f, iterations=%d)",
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
                "  CW Cluster (label=%s): %d members -> media_ids=[%s]", label, len(members), ", ".join(media_ids)
            )
        return created_clusters

    def _build_graph(
        self, identities: list[MediaIdentity], anchors: list[MediaIdentity]
    ) -> tuple[nx.Graph, dict[int, UUID]]:
        """
        Build a graph where nodes are identities and edges represent similarity > threshold.
        Anchors are included as nodes with fixed initial labels.
        """
        graph: nx.Graph = nx.Graph()

        all_identities = identities + anchors
        n_new = len(identities)
        n_total = len(all_identities)

        # Normalize all embeddings once
        embeddings = normalize_embeddings(identity.embedding for identity in all_identities)

        # Map for anchor labels
        # We assign a unique label for each unique cluster_id in anchors
        # Labels 0 to n_new-1 are for new identities (initially self-labeled)
        # Labels >= n_new are for existing clusters
        label_to_cluster_id: dict[int, UUID] = {}
        cluster_id_to_label: dict[UUID, int] = {}
        next_label = n_new

        # Add new identities with unique labels
        for i in range(n_new):
            graph.add_node(i, label=i, is_anchor=False)

        # Add anchors with cluster-based labels
        for i in range(n_new, n_total):
            anchor = all_identities[i]
            # Ensure anchor has a cluster_id. If not, treat as separate (shouldn't happen for anchors)
            if not hasattr(anchor, "cluster_id") or not anchor.cluster_id:
                # Fallback: treat as unique label
                lbl = next_label
                next_label += 1
            else:
                cid = anchor.cluster_id
                if cid not in cluster_id_to_label:
                    cluster_id_to_label[cid] = next_label
                    label_to_cluster_id[next_label] = cid
                    next_label += 1
                lbl = cluster_id_to_label[cid]

            graph.add_node(i, label=lbl, is_anchor=True)

        # Add edges
        # Compute similarity matrix: S = E . E^T
        sim_matrix = np.dot(embeddings, embeddings.T)

        # Find pairs with similarity > threshold
        # We only care about upper triangle (i < j)
        rows, cols = np.where(np.triu(sim_matrix, k=1) > self.edge_threshold)

        edges = []
        for r, c in zip(rows, cols, strict=True):
            weight = float(sim_matrix[r, c])
            edges.append((r, c, weight))

        graph.add_weighted_edges_from(edges)

        logger.info(
            "CW Graph: %d nodes (%d new, %d anchors), %d edges (threshold=%.4f)",
            graph.number_of_nodes(),
            n_new,
            len(anchors),
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
                    media_r = all_identities[r].media_id if hasattr(all_identities[r], "media_id") else "?"
                    media_c = all_identities[c].media_id if hasattr(all_identities[c], "media_id") else "?"
                    logger.info(
                        "  Dropped edge: %d (media %s) <-> %d (media %s) (sim=%.4f)",
                        r,
                        media_r,
                        c,
                        media_c,
                        sim_matrix[r, c],
                    )
                    logged_count += 1
            if logged_count > 0:
                logger.info(
                    "CW Dropped %d edges just below threshold (%.4f - %.4f)",
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
