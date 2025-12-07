"""
Deterministic Chinese Whispers implementation with UUID ordering and quality weighting.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from recognition.application.discovery.graph import GraphAlgorithm
from recognition.domain.identity import MediaIdentity


class DeterministicChineseWhispers(GraphAlgorithm):
    """Chinese Whispers clustering with deterministic ordering and tie-breaking."""

    def __init__(
        self,
        threshold: float = 0.88,
        max_iterations: int = 50,
    ) -> None:
        """Initialize deterministic Chinese Whispers parameters.

        Args:
            threshold: Minimum similarity to consider an edge.
            max_iterations: Maximum number of label propagation iterations.
        """
        self.threshold = threshold
        self.max_iterations = max_iterations

    def cluster(
        self,
        embeddings: Sequence[np.ndarray],
        identities: Sequence[MediaIdentity] | None = None,
    ) -> list[int]:
        """Cluster embeddings using deterministic Chinese Whispers.

        Args:
            embeddings: Sequence of embedding vectors.
            identities: Optional identities to inform ordering and tie-breaking.

        Returns:
            list[int]: Cluster labels for each embedding.
        """
        if not embeddings:
            return []

        data = np.array(embeddings, dtype=np.float32)
        n = data.shape[0]
        if identities is not None and len(identities) != n:
            raise ValueError("embeddings and identities length mismatch")

        # Normalize to unit vectors to use cosine similarity.
        norms = np.linalg.norm(data, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        data = data / norms

        sim_matrix = np.matmul(data, data.T)
        # No self influence
        np.fill_diagonal(sim_matrix, 0.0)

        # Deterministic node order sorted by UUID when provided
        if identities is not None:
            node_order = sorted(range(n), key=lambda i: str(identities[i].id))
            qualities = [float(getattr(identity, "confidence", 1.0)) for identity in identities]
        else:
            node_order = list(range(n))
            qualities = [1.0] * n

        labels = list(range(n))

        for _ in range(self.max_iterations):
            updated = False
            for i in node_order:
                neighbors = [j for j, sim in enumerate(sim_matrix[i]) if sim >= self.threshold and i != j]
                if not neighbors:
                    continue

                votes: dict[int, float] = {}
                for j in neighbors:
                    label = labels[j]
                    vote = float(sim_matrix[i, j]) * qualities[j]
                    votes[label] = votes.get(label, 0.0) + vote

                max_vote = max(votes.values())
                best_labels = [lbl for lbl, v in votes.items() if v == max_vote]

                if len(best_labels) == 1 or identities is None:
                    best_label = min(best_labels)
                else:
                    # Tie-break by smallest UUID among nodes sharing the label
                    best_label = min(
                        best_labels,
                        key=lambda lbl: min(
                            str(identities[k].id) for k, current in enumerate(labels) if current == lbl
                        ),
                    )

                if labels[i] != best_label:
                    labels[i] = best_label
                    updated = True

            if not updated:
                break

        # Re-label to consecutive integers for consistency
        unique_labels = {}
        next_label = 0
        final_labels: list[int] = []
        for lbl in labels:
            if lbl not in unique_labels:
                unique_labels[lbl] = next_label
                next_label += 1
            final_labels.append(unique_labels[lbl])

        return final_labels
