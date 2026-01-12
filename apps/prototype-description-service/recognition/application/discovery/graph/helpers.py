"""Helper functions for graph discovery."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from recognition.application.discovery.graph.algorithm import AnchorIdentity
from recognition.domain.identity import MediaIdentity
from recognition.shared.similarity import normalize_face_embedding, normalize_vector


def compute_embedding_stats(vectors: Sequence[np.ndarray]) -> dict[str, object]:
    if not vectors:
        return {"count": 0, "dimension": None, "norm": {"min": None, "max": None, "mean": None, "std": None}}

    norms = np.array([float(np.linalg.norm(vec)) for vec in vectors], dtype=np.float32)
    dimension = int(vectors[0].shape[0]) if getattr(vectors[0], "shape", None) is not None else None

    return {
        "count": len(vectors),
        "dimension": dimension,
        "norm": {
            "min": float(np.min(norms)) if norms.size else None,
            "max": float(np.max(norms)) if norms.size else None,
            "mean": float(np.mean(norms)) if norms.size else None,
            "std": float(np.std(norms)) if norms.size else None,
        },
    }


def resolve_anchor_conflict(anchors: Sequence[AnchorIdentity]) -> str:
    """Resolve which cluster to assign when multiple anchors are present."""
    counts: dict[str, int] = {}
    for anchor in anchors:
        counts[anchor.cluster_id] = counts.get(anchor.cluster_id, 0) + 1
    return max(counts, key=lambda k: counts.get(k, 0))


def compute_avg_similarity(members: Sequence[np.ndarray], anchors: Sequence[np.ndarray]) -> float:
    """Compute average similarity between members and anchors."""
    if not members or not anchors:
        return 0.0

    member_centroid = normalize_vector(np.mean(np.stack(members), axis=0))
    anchor_centroid = normalize_vector(np.mean(np.stack(anchors), axis=0))

    return float(np.dot(member_centroid, anchor_centroid))


def group_by_label(
    identities: Sequence[MediaIdentity | AnchorIdentity],
    face_vectors: Sequence[np.ndarray],
    labels: Sequence[int],
) -> dict[int, list[tuple[MediaIdentity | AnchorIdentity, np.ndarray]]]:
    """Group identities and face embeddings by cluster label, skipping noise."""
    grouped: dict[int, list[tuple[MediaIdentity | AnchorIdentity, np.ndarray]]] = {}
    for identity, face_vec, label in zip(identities, face_vectors, labels, strict=False):
        if label == -1:
            continue
        grouped.setdefault(label, []).append((identity, face_vec))
    return grouped


def match_to_anchor(
    member_vectors: Sequence[np.ndarray],
    anchor_embeddings: dict[str, list[np.ndarray]],
) -> tuple[str | None, float]:
    """Match a clustered group to an existing anchor cluster."""
    best_anchor: str | None = None
    best_similarity = 0.0

    for anchor_id, reps in anchor_embeddings.items():
        if not reps:
            continue
        anchor_vecs = [normalize_face_embedding(np.asarray(rep, dtype=np.float32)) for rep in reps]
        anchor_mean = normalize_vector(np.mean(anchor_vecs, axis=0))

        sims = [float(np.dot(vec, anchor_mean)) for vec in member_vectors]
        avg_sim = float(sum(sims) / len(sims))

        if avg_sim > best_similarity:
            best_similarity = avg_sim
            best_anchor = anchor_id

    return best_anchor, best_similarity


def match_single_to_anchors(
    face_vec: np.ndarray,
    anchor_embeddings: dict[str, list[np.ndarray]],
) -> tuple[str | None, float]:
    """Match a single noise point to existing anchor clusters."""
    best_anchor: str | None = None
    best_similarity = 0.0

    for anchor_id, reps in anchor_embeddings.items():
        if not reps:
            continue
        for rep in reps:
            rep_vec = normalize_face_embedding(np.asarray(rep, dtype=np.float32))
            sim = float(np.dot(face_vec, rep_vec))
            if sim > best_similarity:
                best_similarity = sim
                best_anchor = anchor_id

    return best_anchor, best_similarity


def compute_member_similarities(member_vectors: Sequence[np.ndarray]) -> list[float]:
    """Compute similarity of each member to the group centroid."""
    if not member_vectors:
        return []
    centroid = normalize_vector(np.mean(np.stack(member_vectors, axis=0), axis=0))
    return [float(np.dot(vec, centroid)) for vec in member_vectors]
