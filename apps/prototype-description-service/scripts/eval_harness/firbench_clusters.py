"""S4 cluster diagnostics per embedding space (FIRBENCH-1). Diagnostics only, never the decision.

Everything is computed inside one leg's space [EMB-01]. Projection coordinates are pictures:
they are marked ``diagnostic_only`` and any metric that receives them raises
``ProjectionLeakError`` [VIZ-18, VIZ-19]. The dendrogram cuts at cosine distance ``1 - s`` for
the production similarity ``s``; the acceptance tau is a separate reference line at ``1 - tau``
and never a cluster cut. Average/complete linkage and the cut convention are project policy;
GRPH-18 warns about transitive closure of raw similarity. Mutual kNN
follows [GRPH-17]. Chaining evidence is partition plus verification, not the transitive closure
of a raw threshold [GRPH-22]. Production HDBSCAN settings are metadata; S4 never calls the
tenant-coupled ``prepare_cluster_caches``.
"""

from __future__ import annotations

import json
import math
import os
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from importlib import import_module, metadata
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from scipy.cluster.hierarchy import cophenet, fcluster, linkage
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial.distance import pdist

from scripts.eval_harness.firbench_contract import (
    CrossSpaceComparisonError,
    FrameContractError,
    IdentityStatus,
    LegKind,
    LinkageMetricError,
    ProjectionLeakError,
    validate_interchange,
)

if TYPE_CHECKING:
    from scripts.eval_harness.firbench_frames import GtFace

ALLOWED_LINKAGE = ("average", "complete")
NOISE_LABEL = -1
CUT_CAPTION = "Cut at cosine distance 1 minus the production similarity threshold"
UNCUT_CAPTION = "no production cut recorded"
TAU_LABEL = "acceptance tau (not a cluster cut)"
PROJECTION_CAPTION = "diagnostic projection · distances not meaningful"
NOISE_POLICY = "minus_one_is_unpaired_and_bcubed_singleton"
EXCLUSION_REASONS = (
    "same_verified_identity",
    "unknown_identity",
    "unresolved_identity",
    "unverified_endpoint",
    "not_held_out",
    "missing_vector",
)
HISTOGRAM_KINDS = ("intra_identity_cosine", "inter_identity_cosine", "vector_norm")
HELD_OUT_FOLD_ROLE = "test"
NO_PRODUCTION_SIMILARITY = "no production similarity threshold recorded"


class EvidenceStatus(StrEnum):
    """Explicit result states of the clusters-v1 wire (absent, uncomputed and available are distinct)."""

    available = "available"
    unavailable = "unavailable"
    not_evaluated = "not_evaluated"


@dataclass(frozen=True)
class Evidence:
    """One diagnostic result: available data, or an explicit reason it is absent."""

    status: EvidenceStatus
    reason: str | None
    data: Any = None

    def to_json(self) -> dict[str, Any]:
        return {"status": self.status.value, "reason": self.reason, "data": _jsonable(self.data)}


def available(data: Any) -> Evidence:
    return Evidence(EvidenceStatus.available, None, data)


def unavailable(reason: str) -> Evidence:
    return Evidence(EvidenceStatus.unavailable, reason, None)


def not_evaluated(reason: str) -> Evidence:
    return Evidence(EvidenceStatus.not_evaluated, reason, None)


def _rate(numerator: int, denominator: int, reason: str) -> Evidence:
    """An undefined denominator is unavailable, never a zero rate."""
    if denominator <= 0:
        return unavailable(reason)
    return available(float(numerator) / float(denominator))


def _jsonable(value: Any) -> Any:
    if isinstance(value, Evidence):
        return value.to_json()
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, np.ndarray):
        return _jsonable(value.tolist())
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    return value


def _pairs(counts: Sequence[int] | Any) -> int:
    return sum(count * (count - 1) // 2 for count in counts)


def _refuse_projection(*values: object) -> None:
    for value in values:
        if isinstance(value, ProjectionCoords):
            raise ProjectionLeakError("projection coordinates are diagnostic-only and cannot feed a metric")


def _threshold(value: object) -> float:
    if isinstance(value, bool):
        raise FrameContractError("similarity threshold must be a number, not a bool")
    try:
        similarity = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise FrameContractError(f"similarity threshold must be a number: {exc}") from exc
    if not math.isfinite(similarity) or not -1.0 <= similarity <= 1.0:
        raise FrameContractError("similarity threshold must be finite and lie in [-1, 1]")
    return similarity


def _vectors(values: object) -> np.ndarray:
    _refuse_projection(values)
    try:
        array = np.asarray(values, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise FrameContractError(f"vectors must be a numeric array: {exc}") from exc
    if array.ndim != 2 or array.shape[0] < 1 or array.shape[1] < 1:
        raise FrameContractError("vectors must be a non-empty two-dimensional array")
    if not np.all(np.isfinite(array)):
        raise FrameContractError("vectors must be finite")
    return array


def _unit_rows(values: object) -> np.ndarray:
    array = _vectors(values)
    norms = np.linalg.norm(array, axis=1)
    if np.any(norms == 0):
        raise FrameContractError("a zero-norm vector cannot define cosine similarity")
    return array / norms[:, None]


def _labels_array(values: object, count: int) -> np.ndarray:
    array = np.asarray(values)
    if array.shape != (count,) or not np.issubdtype(array.dtype, np.integer):
        raise FrameContractError(f"labels must be one integer per face ({count} faces)")
    if np.any(array < NOISE_LABEL):
        raise FrameContractError("labels must be -1 (noise) or a non-negative cluster id")
    return array.astype(np.int64)


def _check_k(k: object, count: int) -> int:
    if isinstance(k, bool) or not isinstance(k, int) or not 1 <= k <= count - 1:
        raise FrameContractError(f"k must be an integer between 1 and n-1 (n={count})")
    return k


def _topk_indices(unit: np.ndarray, k: int) -> list[np.ndarray]:
    similarity = unit @ unit.T
    order: list[np.ndarray] = []
    for row in range(unit.shape[0]):
        scores = similarity[row].copy()
        scores[row] = -np.inf
        order.append(np.argsort(-scores, kind="stable")[:k])
    return order


# --- reference clustering and partition metrics ---------------------------------------------


def reference_threshold_cluster(vectors: object, *, similarity_threshold: float) -> np.ndarray:
    """Connected components of the cosine >= s graph. Singletons are noise (-1); labels follow first occurrence."""
    _refuse_projection(vectors)
    threshold = _threshold(similarity_threshold)
    unit = _unit_rows(vectors)
    adjacency = unit @ unit.T >= threshold
    np.fill_diagonal(adjacency, False)
    _, component = connected_components(csr_matrix(adjacency), directed=False)
    sizes = Counter(component.tolist())
    labels = np.full(component.shape, NOISE_LABEL, dtype=np.int64)
    first_seen: dict[int, int] = {}
    for index, cluster in enumerate(component.tolist()):
        if sizes[cluster] == 1:
            continue
        if cluster not in first_seen:
            first_seen[cluster] = len(first_seen)
        labels[index] = first_seen[cluster]
    return labels


@dataclass(frozen=True)
class LegFace:
    """One GT face as seen by one leg: identity status, held-out fold and verification reference."""

    face_id: str
    identity_id: str | None
    identity_status: IdentityStatus
    fold: int | None
    verification_ref: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.face_id, str) or not self.face_id.strip():
            raise FrameContractError("face_id must be a non-empty string")
        try:
            status = IdentityStatus(self.identity_status)
        except ValueError as exc:
            raise FrameContractError(f"face {self.face_id}: identity_status is not an IdentityStatus") from exc
        object.__setattr__(self, "identity_status", status)
        if status is IdentityStatus.named:
            if not isinstance(self.identity_id, str) or not self.identity_id.strip():
                raise FrameContractError(f"face {self.face_id}: a named face needs an identity_id")
        elif self.identity_id is not None:
            raise FrameContractError(f"face {self.face_id}: a {status.value} face carries no identity_id")
        if self.fold is not None and (isinstance(self.fold, bool) or not isinstance(self.fold, int) or self.fold < 0):
            raise FrameContractError(f"face {self.face_id}: fold must be a non-negative integer or null")
        if self.verification_ref is not None and (
            not isinstance(self.verification_ref, str) or not self.verification_ref.strip()
        ):
            raise FrameContractError(f"face {self.face_id}: verification_ref must be a non-empty string or null")

    @classmethod
    def from_gt_face(cls, face: GtFace, *, fold: int | None, verification_ref: str | None) -> LegFace:
        return cls(
            face_id=face.face_id,
            identity_id=face.identity_id,
            identity_status=face.identity_status,
            fold=fold,
            verification_ref=verification_ref,
        )


def partition_metrics(faces: Sequence[LegFace], labels: object) -> Evidence:
    """Pairwise and B-cubed metrics over named GT faces only; noise and unknown rules per S4 Build 1."""
    _refuse_projection(labels)
    lab = _labels_array(labels, len(faces))
    named = [index for index, face in enumerate(faces) if face.identity_status is IdentityStatus.named]
    unknown_faces = sum(face.identity_status is IdentityStatus.unknown for face in faces)
    unresolved_faces = sum(face.identity_status is IdentityStatus.unresolved for face in faces)
    if not named:
        return unavailable("no named faces to score")
    ids = [faces[index].identity_id for index in named]
    named_labels = [int(lab[index]) for index in named]
    predicted = [label for label in named_labels if label != NOISE_LABEL]
    cluster_sizes = Counter(predicted)
    identity_sizes = Counter(ids)
    joint = Counter((ident, label) for ident, label in zip(ids, named_labels, strict=True) if label != NOISE_LABEL)
    co_predicted = _pairs(cluster_sizes.values())
    true_pairs = _pairs(identity_sizes.values())
    co_true = _pairs(joint.values())
    noise_faces = sum(label == NOISE_LABEL for label in named_labels)

    identities_per_cluster: dict[int, set[str]] = defaultdict(set)
    clusters_per_identity: dict[str, set[tuple[str, int]]] = defaultdict(set)
    for position, (ident, label) in enumerate(zip(ids, named_labels, strict=True)):
        if label == NOISE_LABEL:
            clusters_per_identity[ident].add(("noise", position))
            continue
        identities_per_cluster[label].add(ident)
        clusters_per_identity[ident].add(("cluster", label))
    merges = sum(len(members) >= 2 for members in identities_per_cluster.values())
    fragmentation = sum(len(clusters) >= 2 for clusters in clusters_per_identity.values())

    precisions: list[float] = []
    recalls: list[float] = []
    for ident, label in zip(ids, named_labels, strict=True):
        if label == NOISE_LABEL:
            precisions.append(1.0)
            recalls.append(1.0 / identity_sizes[ident])
            continue
        overlap = joint[(ident, label)]
        precisions.append(overlap / cluster_sizes[label])
        recalls.append(overlap / identity_sizes[ident])

    named_cluster_ids = set(predicted)
    unknown_absorbed = sum(
        1
        for index, face in enumerate(faces)
        if face.identity_status is IdentityStatus.unknown and int(lab[index]) in named_cluster_ids
    )
    return available(
        {
            "unit": "gt_face",
            "scored_identity_status": "named",
            "excluded_identity_statuses": ["unknown", "unresolved"],
            "noise_policy": NOISE_POLICY,
            "named_faces": len(named),
            "unknown_faces": unknown_faces,
            "unresolved_faces": unresolved_faces,
            "coassigned_true_pairs": co_true,
            "coassigned_predicted_pairs": co_predicted,
            "true_pairs": true_pairs,
            "merges": merges,
            "fragmentation": fragmentation,
            "unknown_absorbed": unknown_absorbed,
            "noise_faces": noise_faces,
            "pairwise_precision": _rate(co_true, co_predicted, "no co-assigned predicted named pairs"),
            "pairwise_recall": _rate(co_true, true_pairs, "no true named pairs"),
            "bcubed_precision": available(sum(precisions) / len(precisions)),
            "bcubed_recall": available(sum(recalls) / len(recalls)),
            "noise_fraction": _rate(noise_faces, len(named), "no named faces"),
        }
    )


def order_stability(
    cluster_fn: Callable[[np.ndarray], object],
    vectors: object,
    *,
    n_orders: int,
    seed: int,
) -> Evidence:
    """Share of base co-assigned pairs that stay co-assigned when the insertion order is permuted."""
    _refuse_projection(vectors)
    if isinstance(n_orders, bool) or not isinstance(n_orders, int) or n_orders < 2:
        raise FrameContractError("n_orders must be an integer of at least 2")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise FrameContractError("seed must be a non-negative integer")
    array = _vectors(vectors)
    count = array.shape[0]
    base = _labels_array(cluster_fn(array), count)
    base_pairs = _pairs(Counter(label for label in base.tolist() if label != NOISE_LABEL).values())
    rng = np.random.default_rng(seed)
    stable_pairs = 0
    compared_pairs = 0
    for _ in range(n_orders):
        order = rng.permutation(count)
        permuted = _labels_array(cluster_fn(array[order]), count)
        mapped = np.empty_like(permuted)
        mapped[order] = permuted
        both = Counter(
            (left, right)
            for left, right in zip(base.tolist(), mapped.tolist(), strict=True)
            if left != NOISE_LABEL and right != NOISE_LABEL
        )
        stable_pairs += _pairs(both.values())
        compared_pairs += base_pairs
    return available(
        {
            "n_orders": n_orders,
            "seed": seed,
            "stable_pairs": stable_pairs,
            "compared_pairs": compared_pairs,
            "fraction": _rate(stable_pairs, compared_pairs, "no co-assigned pairs to compare"),
        }
    )


# --- neighbours, mutual kNN, dendrogram and PCA ----------------------------------------------


def knn_neighbours(vectors: object, k: int) -> tuple[tuple[int, int, float], ...]:
    """Directed cosine kNN edges (i, j, cos) for each row's top-k neighbours; ties break by index."""
    _refuse_projection(vectors)
    unit = _unit_rows(vectors)
    _check_k(k, unit.shape[0])
    similarity = unit @ unit.T
    edges: list[tuple[int, int, float]] = []
    for row, neighbours in enumerate(_topk_indices(unit, k)):
        for column in neighbours.tolist():
            edges.append((row, column, float(similarity[row, column])))
    return tuple(edges)


def mutual_knn_graph(vectors: object, k: int) -> tuple[tuple[int, int, float], ...]:
    """Undirected reciprocal kNN edges (i < j, cos) [GRPH-17]."""
    _refuse_projection(vectors)
    unit = _unit_rows(vectors)
    _check_k(k, unit.shape[0])
    neighbour_sets = [set(row.tolist()) for row in _topk_indices(unit, k)]
    similarity = unit @ unit.T
    edges: list[tuple[int, int, float]] = []
    for left in range(unit.shape[0]):
        for right in sorted(neighbour_sets[left]):
            if left < right and left in neighbour_sets[right]:
                edges.append((left, right, float(similarity[left, right])))
    return tuple(edges)


@dataclass(frozen=True)
class DendrogramResult:
    linkage: np.ndarray
    cophenetic: float | None
    cut_distance: float | None
    cut_labels: np.ndarray | None


def cosine_dendrogram(vectors: object, *, method: str, similarity_threshold: float | None) -> DendrogramResult:
    """Average or complete linkage on cosine distance; cut at 1 - s, or uncut when s is unrecorded."""
    _refuse_projection(vectors)
    if method not in ALLOWED_LINKAGE:
        raise LinkageMetricError(f"linkage {method!r} is refused on cosine distance; use average or complete")
    threshold = None if similarity_threshold is None else _threshold(similarity_threshold)
    unit = _unit_rows(vectors)
    if unit.shape[0] < 2:
        raise FrameContractError("a dendrogram needs at least two faces")
    distances = np.clip(pdist(unit, metric="cosine"), 0.0, 2.0)
    tree = linkage(distances, method=method)
    correlation, _ = cophenet(tree, distances)
    cophenetic = float(min(1.0, max(-1.0, correlation))) if math.isfinite(correlation) else None
    if threshold is None:
        return DendrogramResult(tree, cophenetic, None, None)
    cut = 1.0 - threshold
    return DendrogramResult(tree, cophenetic, cut, fcluster(tree, t=cut, criterion="distance") - 1)


def pca_spectrum(vectors: object) -> Evidence:
    """Retained nonzero PCA spectrum and effective dimension; the spectrum alone does not establish pair distances."""
    _refuse_projection(vectors)
    array = _vectors(vectors)
    if array.shape[0] < 2:
        return unavailable("fewer than two faces")
    centred = array - array.mean(axis=0)
    singular = np.linalg.svd(centred, compute_uv=False)
    tolerance = max(array.shape) * np.finfo(np.float64).eps * float(singular.max(initial=0.0))
    kept = singular[singular > tolerance]
    if kept.size == 0:
        return unavailable("no variance in the leg space")
    variance = kept**2
    total = float(variance.sum())
    effective = float(total**2 / float((variance**2).sum()))
    return available(
        {
            "explained_variance_ratio": (variance / total).tolist(),
            "effective_dimension": max(1.0, effective),
            "retained_components": int(kept.size),
        }
    )


def linear_cka(left: object, right: object) -> float | None:
    """Linear CKA between matched rows; refuses different dimensions. None when a space has no variance."""
    _refuse_projection(left, right)
    x = _vectors(left)
    y = _vectors(right)
    if x.shape[1] != y.shape[1]:
        raise CrossSpaceComparisonError("linear CKA compares spaces of one dimension only")
    if x.shape[0] != y.shape[0]:
        raise FrameContractError("linear CKA needs the same matched rows in both spaces")
    x = x - x.mean(axis=0)
    y = y - y.mean(axis=0)
    norm_x = float(np.linalg.norm(x.T @ x, "fro"))
    norm_y = float(np.linalg.norm(y.T @ y, "fro"))
    if norm_x == 0.0 or norm_y == 0.0:
        return None
    cross = float(np.linalg.norm(y.T @ x, "fro")) ** 2
    return float(min(1.0, max(0.0, cross / (norm_x * norm_y))))


def knn_jaccard(reference: object, comparison: object, *, k: int) -> float:
    """Mean per-face Jaccard overlap of cosine top-k sets between matched rows of two runs."""
    _refuse_projection(reference, comparison)
    reference_unit = _unit_rows(reference)
    comparison_unit = _unit_rows(comparison)
    if reference_unit.shape != comparison_unit.shape:
        raise FrameContractError("kNN-Jaccard needs matched rows of one shape")
    _check_k(k, reference_unit.shape[0])
    first = _topk_indices(reference_unit, k)
    second = _topk_indices(comparison_unit, k)
    values = [
        len(set(a.tolist()) & set(b.tolist())) / len(set(a.tolist()) | set(b.tolist()))
        for a, b in zip(first, second, strict=True)
    ]
    return float(np.mean(values))


# --- chaining -------------------------------------------------------------------------------


@dataclass(frozen=True)
class ChainingInput:
    """Predeclared held-out GT/audit pairs, unique and canonically ordered by stable face IDs."""

    frame_id: str
    fold: int
    pair_selection_rule: str
    candidate_pairs: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.frame_id, str) or not self.frame_id.strip():
            raise FrameContractError("chaining frame_id must be a non-empty string")
        if isinstance(self.fold, bool) or not isinstance(self.fold, int) or self.fold < 0:
            raise FrameContractError("chaining fold must be a non-negative integer")
        if not isinstance(self.pair_selection_rule, str) or not self.pair_selection_rule.strip():
            raise FrameContractError("chaining pair_selection_rule must be a non-empty string")
        if not isinstance(self.candidate_pairs, (tuple, list)):
            raise FrameContractError("chaining candidate_pairs must be a sequence of face-id pairs")
        pairs: set[tuple[str, str]] = set()
        for pair in self.candidate_pairs:
            if (
                not isinstance(pair, (tuple, list))
                or len(pair) != 2
                or not all(isinstance(face_id, str) and face_id.strip() for face_id in pair)
            ):
                raise FrameContractError("each chaining candidate is a pair of non-empty face ids")
            left, right = sorted(pair)
            if left == right:
                raise FrameContractError("a chaining candidate needs two distinct face ids")
            if (left, right) in pairs:
                raise FrameContractError("duplicate unordered chaining candidate pair")
            pairs.add((left, right))
        object.__setattr__(self, "candidate_pairs", tuple(sorted(pairs)))


def _pair_exclusion(faces: Mapping[str, LegFace], left_id: str, right_id: str, fold: int) -> str | None:
    if left_id not in faces or right_id not in faces:
        return "missing_vector"
    left = faces[left_id]
    right = faces[right_id]
    if left.fold != fold or right.fold != fold:
        return "not_held_out"
    if IdentityStatus.unresolved in (left.identity_status, right.identity_status):
        return "unresolved_identity"
    if IdentityStatus.unknown in (left.identity_status, right.identity_status):
        return "unknown_identity"
    if left.verification_ref is None or right.verification_ref is None:
        return "unverified_endpoint"
    if left.identity_id == right.identity_id:
        return "same_verified_identity"
    return None


def _shortest_path(
    adjacency: Sequence[Sequence[int]], start: int, goal: int, *, through: int | None = None
) -> list[int] | None:
    """BFS with ordered neighbours; optionally construct a simple path through one node.

    The through-node witness is NOT necessarily a shortest endpoint path. Two
    vertex-disjoint routes from that node to the endpoints establish existence;
    a unit-capacity split-node flow finds them without enumerating simple paths.
    BFS augmentations and flow decomposition use stable-ID node order. This also
    rejects a third identity in a dangling branch (a walk would revisit its bridge).
    """
    if through is not None and through not in (start, goal):
        count = len(adjacency)
        sink = 2 * count
        source = 2 * through + 1
        capacity: list[dict[int, int]] = [{} for _ in range(sink + 1)]
        for node, neighbours in enumerate(adjacency):
            capacity[2 * node][2 * node + 1] = 1
            if node in (start, goal):
                capacity[2 * node + 1][sink] = 1
            else:
                for neighbour in neighbours:
                    capacity[2 * node + 1][2 * neighbour] = 1
        residual = [row.copy() for row in capacity]
        for node, neighbours in enumerate(capacity):
            for neighbour in neighbours:
                residual[neighbour].setdefault(node, 0)
        for _ in range(2):
            augment = _shortest_path(
                [sorted(neighbour for neighbour, value in row.items() if value > 0) for row in residual],
                source,
                sink,
            )
            if augment is None:
                return None
            for left, right in zip(augment, augment[1:], strict=False):
                residual[left][right] -= 1
                residual[right][left] += 1
        # Decompose the integral flow into two routes. Ignore any residual cycle;
        # vertex capacities ensure the extracted routes share only their source.
        flow = [
            sorted(neighbour for neighbour, value in row.items() if value > residual[node][neighbour])
            for node, row in enumerate(capacity)
        ]
        routes: dict[int, list[int]] = {}
        for _ in range(2):
            route = _shortest_path(flow, source, sink)
            if route is None:
                raise FrameContractError("chaining witness flow cannot be decomposed")
            for left, right in zip(route, route[1:], strict=False):
                flow[left].remove(right)
            nodes = [node // 2 for node in route[:-1] if node % 2 == 1]
            routes[nodes[-1]] = nodes
        return routes[start][::-1] + routes[goal][1:]
    if start == goal:
        return [start]
    parents: dict[int, int | None] = {start: None}
    frontier = [start]
    while frontier:
        next_frontier: list[int] = []
        for node in frontier:
            for neighbour in adjacency[node]:
                if neighbour in parents:
                    continue
                parents[neighbour] = node
                if neighbour == goal:
                    path = [goal]
                    while parents[path[-1]] is not None:
                        path.append(parents[path[-1]])  # type: ignore[arg-type]
                    return path[::-1]
                next_frontier.append(neighbour)
        frontier = next_frontier
    return None


def _node(face: LegFace) -> dict[str, Any]:
    return {
        "face_id": face.face_id,
        "identity_id": face.identity_id,
        "verification_ref": face.verification_ref,
        "identity_status": face.identity_status.value,
    }


def chaining_check(
    vectors: object,
    faces: Sequence[LegFace],
    *,
    similarity_threshold: float,
    chaining: ChainingInput,
) -> Evidence:
    """D/N: geometric links between fixed, held-out verified-different GT pairs.

    C/N counts existence of a simple path through a named, independently verified
    third identity, distinct from both endpoints. An unverified/unknown/unresolved
    node can carry geometry but supplies no identity evidence [GRPH-18: Never trust
    the transitive closure of a raw similarity threshold, Introduction to Information
    Retrieval, § 17.2; GRPH-22: partition-plus-verification, practice label].

    Witness rule: canonical endpoint orientation; try qualifying third faces by
    ascending stable face ID, taking the first feasible split-node flow witness
    (ordered BFS augmentations/decomposition). Otherwise show the shortest D path,
    with stable-ID BFS ties. C is not limited to the shortest path, and the selected
    witness does not claim causal dependence, operational naming, or identity from
    co-clustering. Verification references are supplied audit evidence, never minted
    here. Neither these descriptive counts nor absent evidence establishes zero risk.
    """
    _refuse_projection(vectors)
    if not isinstance(chaining, ChainingInput):
        raise FrameContractError("chaining must be a ChainingInput")
    chaining.__post_init__()
    if not isinstance(faces, Sequence) or isinstance(faces, (str, bytes)):
        raise FrameContractError("chaining faces must be a sequence of LegFace records")
    if any(not isinstance(face, LegFace) for face in faces):
        raise FrameContractError("chaining faces must contain only LegFace records")
    if len({face.face_id for face in faces}) != len(faces):
        raise FrameContractError("chaining face ids must be unique; lookup overwrites are refused")
    threshold = _threshold(similarity_threshold)
    unit = _unit_rows(vectors)
    if len(faces) != unit.shape[0]:
        raise FrameContractError("chaining faces must align one-to-one with vector rows")
    # Reorder faces and their vectors together, never the geometry independently.
    order = sorted(range(len(faces)), key=lambda row: faces[row].face_id)
    faces = tuple(faces[row] for row in order)
    unit = unit[order]
    similarity = unit @ unit.T
    adjacency_matrix = similarity >= threshold
    np.fill_diagonal(adjacency_matrix, False)
    adjacency = [np.flatnonzero(row).tolist() for row in adjacency_matrix]
    by_id = {face.face_id: face for face in faces}
    row_of = {face.face_id: row for row, face in enumerate(faces)}
    exclusions: Counter[str] = Counter()
    eligible: list[tuple[str, str]] = []
    for left_id, right_id in chaining.candidate_pairs:
        reason = _pair_exclusion(by_id, left_id, right_id, chaining.fold)
        if reason is None:
            eligible.append((left_id, right_id))
        else:
            exclusions[reason] += 1
    records: list[dict[str, Any]] = []
    for number, (left_id, right_id) in enumerate(eligible, start=1):
        left = by_id[left_id]
        right = by_id[right_id]
        path = _shortest_path(adjacency, row_of[left_id], row_of[right_id])
        third_identity: str | None = None
        if path is not None:
            for row, middle in enumerate(faces):
                if (
                    middle.identity_status is IdentityStatus.named
                    and middle.verification_ref is not None
                    and middle.identity_id not in (left.identity_id, right.identity_id)
                ):
                    witness = _shortest_path(adjacency, row_of[left_id], row_of[right_id], through=row)
                    if witness is not None:
                        path = witness
                        third_identity = middle.identity_id
                        break
        records.append(
            {
                "pair_id": f"pair-{number:04}",
                "left": {
                    "face_id": left.face_id,
                    "identity_id": left.identity_id,
                    "verification_ref": left.verification_ref,
                },
                "right": {
                    "face_id": right.face_id,
                    "identity_id": right.identity_id,
                    "verification_ref": right.verification_ref,
                },
                "path_linked": path is not None,
                "through_third_identity": third_identity is not None,
                "third_identity_id": third_identity,
                "path": None if path is None else [_node(faces[row]) for row in path],
                "edges": []
                if path is None
                else [
                    {
                        "source_face_id": faces[a].face_id,
                        "target_face_id": faces[b].face_id,
                        "cosine_similarity": float(similarity[a, b]),
                    }
                    for a, b in zip(path, path[1:], strict=False)  # consecutive path edges: n nodes give n-1 edges
                ],
            }
        )
    linked = sum(record["path_linked"] for record in records)
    third = sum(record["through_third_identity"] for record in records)
    no_pairs = "no eligible pairs"
    return available(
        {
            "scope": {
                "frame_id": chaining.frame_id,
                "fold": chaining.fold,
                "fold_role": HELD_OUT_FOLD_ROLE,
                "pair_selection_rule": chaining.pair_selection_rule,
            },
            "input_pairs": len(chaining.candidate_pairs),
            "eligible_pairs": len(eligible),
            "path_linked_pairs": linked,
            "third_identity_linked_pairs": third,
            "D": _rate(linked, len(eligible), no_pairs),
            "C": _rate(third, len(eligible), no_pairs),
            "exclusions": [
                {"reason": reason, "count": exclusions[reason]} for reason in EXCLUSION_REASONS if exclusions[reason]
            ],
            "pairs": records,
        }
    )


# --- projections (pictures only) -------------------------------------------------------------


@dataclass(frozen=True)
class ProjectionCoords:
    """2-D picture coordinates. Diagnostic only: metrics refuse this type with ProjectionLeakError."""

    method: str
    status: EvidenceStatus
    reason: str | None
    coordinates: np.ndarray | None
    seed: int | None
    parameters: Mapping[str, Any]
    versions: tuple[tuple[str, str], ...]
    diagnostic_only: bool = True


def _import_umap() -> Any:
    return import_module("umap")


def _umap_version(module: Any) -> str:
    version = getattr(module, "__version__", None)
    if isinstance(version, str) and version:
        return version
    try:
        return metadata.version("umap-learn")
    except metadata.PackageNotFoundError as exc:
        raise FrameContractError("umap-learn version is unknown; refusing to invent one") from exc


def projection_coords(vectors: object, *, n_neighbors: int, min_dist: float, seed: int) -> ProjectionCoords:
    """UMAP picture when umap-learn imports; otherwise an explicit unavailable state."""
    _refuse_projection(vectors)
    array = _vectors(vectors)
    if isinstance(n_neighbors, bool) or not isinstance(n_neighbors, int) or n_neighbors < 2:
        raise FrameContractError("n_neighbors must be an integer of at least 2")
    if not math.isfinite(float(min_dist)) or float(min_dist) < 0.0:
        raise FrameContractError("min_dist must be finite and non-negative")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise FrameContractError("seed must be a non-negative integer")
    parameters = {"n_neighbors": n_neighbors, "min_dist": float(min_dist)}
    if array.shape[0] < 2:
        return ProjectionCoords(
            "umap", EvidenceStatus.unavailable, "fewer than two faces", None, seed, parameters, (), True
        )
    try:
        module = _import_umap()
    except ImportError:
        return ProjectionCoords(
            "umap", EvidenceStatus.unavailable, "umap-learn is not installed", None, seed, parameters, (), True
        )
    reducer = module.UMAP(n_neighbors=n_neighbors, min_dist=float(min_dist), n_components=2, random_state=seed)
    try:
        coords = np.asarray(reducer.fit_transform(array), dtype=np.float64)
    except Exception as exc:  # the UMAP fit may raise any library error; it must surface, not read as unavailable
        raise FrameContractError(f"UMAP fit failed: {exc}") from exc
    if coords.shape != (array.shape[0], 2) or not np.all(np.isfinite(coords)):
        raise FrameContractError("UMAP must return finite (faces, 2) coordinates")
    return ProjectionCoords(
        "umap", EvidenceStatus.available, None, coords, seed, parameters, (("umap-learn", _umap_version(module)),), True
    )


def pca_projection(vectors: object, *, seed: int | None = None) -> ProjectionCoords:
    """PCA-2 fallback picture, with the original-space neighbour table kept beside it."""
    _refuse_projection(vectors)
    array = _vectors(vectors)
    if array.shape[0] < 2:
        return ProjectionCoords(
            "pca",
            EvidenceStatus.unavailable,
            "fewer than two faces",
            None,
            seed,
            {"n_neighbors": None, "min_dist": None},
            (),
            True,
        )
    centred = array - array.mean(axis=0)
    _, _, components = np.linalg.svd(centred, full_matrices=False)
    coords = centred @ components[:2].T
    if coords.shape[1] < 2:
        coords = np.hstack([coords, np.zeros((array.shape[0], 2 - coords.shape[1]))])
    return ProjectionCoords(
        "pca",
        EvidenceStatus.available,
        None,
        coords,
        seed,
        {"n_neighbors": None, "min_dist": None},
        (("numpy", np.__version__),),
        True,
    )


# --- one leg's diagnostics and the clusters.json writer -------------------------------------------


@dataclass(frozen=True)
class ClusterRunConfig:
    """Run-level settings, all supplied by the caller from the manifest. Production HDBSCAN is metadata only."""

    similarity_threshold: float | None
    linkage: str
    knn_k: int
    histogram_bins: int
    n_orders: int
    order_seed: int
    projection_seed: int
    umap_n_neighbors: int
    umap_min_dist: float
    acceptance_tau: float | None
    production_parameters: tuple[tuple[str, object], ...] = ()

    def __post_init__(self) -> None:
        if self.linkage not in ALLOWED_LINKAGE:
            raise LinkageMetricError(f"linkage {self.linkage!r} is refused on cosine distance; use average or complete")
        if self.similarity_threshold is not None:
            _threshold(self.similarity_threshold)
        if self.acceptance_tau is not None and (
            isinstance(self.acceptance_tau, bool)
            or not isinstance(self.acceptance_tau, (int, float))
            or not math.isfinite(self.acceptance_tau)
        ):
            raise FrameContractError("acceptance tau must be a finite number")
        for name, value, minimum in (
            ("knn_k", self.knn_k, 1),
            ("histogram_bins", self.histogram_bins, 1),
            ("n_orders", self.n_orders, 2),
            ("order_seed", self.order_seed, 0),
            ("projection_seed", self.projection_seed, 0),
            ("umap_n_neighbors", self.umap_n_neighbors, 2),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise FrameContractError(f"{name} must be an integer of at least {minimum}")
        if not math.isfinite(float(self.umap_min_dist)) or float(self.umap_min_dist) < 0.0:
            raise FrameContractError("umap_min_dist must be finite and non-negative")
        for name, value in self.production_parameters:
            if (
                not isinstance(name, str)
                or not name
                or not (value is None or isinstance(value, (str, int, float, bool)))
            ):
                raise FrameContractError("production parameters are scalar name/value metadata")


@dataclass(frozen=True)
class LegInput:
    """One leg's run. ``vectors`` rows align one-to-one with ``faces``; one embedding space only [EMB-01]."""

    leg_key: str
    leg_kind: LegKind
    run_id: str
    faces: tuple[LegFace, ...]
    vectors: np.ndarray
    chaining: ChainingInput | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.leg_key, str) or not self.leg_key.strip():
            raise FrameContractError("leg_key must be a non-empty string")
        try:
            object.__setattr__(self, "leg_kind", LegKind(self.leg_kind))
        except ValueError as exc:
            raise FrameContractError("leg_kind is not a LegKind") from exc
        if not isinstance(self.run_id, str) or not self.run_id.strip():
            raise FrameContractError("run_id must be a non-empty string")
        faces = tuple(self.faces)
        object.__setattr__(self, "faces", faces)
        if len({face.face_id for face in faces}) != len(faces):
            raise FrameContractError("face ids must be unique within a leg")
        vectors = _vectors(self.vectors)
        if vectors.shape[0] != len(faces):
            raise FrameContractError("vector rows must align one-to-one with faces")
        object.__setattr__(self, "vectors", vectors)


def _pair_cosines(similarity: np.ndarray, faces: Sequence[LegFace]) -> tuple[np.ndarray, np.ndarray]:
    named = [index for index, face in enumerate(faces) if face.identity_status is IdentityStatus.named]
    intra: list[float] = []
    inter: list[float] = []
    for position, left in enumerate(named):
        for right in named[position + 1 :]:
            value = float(similarity[left, right])
            (intra if faces[left].identity_id == faces[right].identity_id else inter).append(value)
    return np.asarray(intra, dtype=np.float64), np.asarray(inter, dtype=np.float64)


def _histogram(values: np.ndarray, *, lower: float, upper: float, bins: int, reason: str) -> Evidence:
    if values.size == 0:
        return unavailable(reason)
    counts, edges = np.histogram(np.clip(values, lower, upper), bins=bins, range=(lower, upper))
    return available(
        {
            "bins": [
                {"lower": float(edges[i]), "upper": float(edges[i + 1]), "count": int(counts[i])} for i in range(bins)
            ]
        }
    )


def _companions(leg: LegInput, prior: LegInput, config: ClusterRunConfig) -> dict[str, Evidence]:
    if prior.leg_key != leg.leg_key:
        raise CrossSpaceComparisonError("companions compare runs of exactly one leg key")
    if prior.leg_kind is not leg.leg_kind:
        raise CrossSpaceComparisonError("companions compare runs of one leg kind")
    current_rows = {face.face_id: row for row, face in enumerate(leg.faces)}
    prior_rows = {face.face_id: row for row, face in enumerate(prior.faces)}
    shared = sorted(set(current_rows) & set(prior_rows))
    if len(shared) < 2:
        reason = "fewer than two matched faces across runs"
        return {"knn_jaccard": unavailable(reason), "linear_cka": unavailable(reason)}
    current_matched = leg.vectors[[current_rows[face_id] for face_id in shared]]
    prior_matched = prior.vectors[[prior_rows[face_id] for face_id in shared]]
    if len(shared) >= config.knn_k + 1:
        jaccard = available(
            {
                "reference_run_id": prior.run_id,
                "comparison_run_id": leg.run_id,
                "k": config.knn_k,
                "value": knn_jaccard(prior_matched, current_matched, k=config.knn_k),
            }
        )
    else:
        jaccard = unavailable(f"fewer than {config.knn_k + 1} matched faces for k={config.knn_k}")
    cka = linear_cka(prior_matched, current_matched)
    cka_evidence = (
        unavailable("a space has no variance")
        if cka is None
        else available(
            {
                "reference_run_id": prior.run_id,
                "comparison_run_id": leg.run_id,
                "dimension": int(current_matched.shape[1]),
                "value": cka,
            }
        )
    )
    return {"knn_jaccard": jaccard, "linear_cka": cka_evidence}


def build_leg_diagnostics(leg: LegInput, *, config: ClusterRunConfig, prior: LegInput | None = None) -> dict[str, Any]:
    """One leg's clusters-v1 entry. Metrics use only this leg's vectors; projections never feed metrics."""
    vectors = leg.vectors
    faces = leg.faces
    count = len(faces)
    face_ids = [face.face_id for face in faces]
    threshold = config.similarity_threshold
    unit = _unit_rows(vectors)
    similarity = unit @ unit.T
    has_threshold = threshold is not None

    def _labels_evidence() -> tuple[Evidence, np.ndarray | None]:
        if not has_threshold:
            return unavailable(NO_PRODUCTION_SIMILARITY), None
        labels = reference_threshold_cluster(vectors, similarity_threshold=threshold)
        rows = [
            {"face_id": face_id, "label": int(label)} for face_id, label in zip(face_ids, labels.tolist(), strict=True)
        ]
        return available(rows), labels

    labels_ev, labels = _labels_evidence()
    if labels is None:
        partition_ev = unavailable(NO_PRODUCTION_SIMILARITY)
        order_ev = unavailable(NO_PRODUCTION_SIMILARITY)
        chaining_ev = (
            not_evaluated("no held-out verified pair evidence supplied")
            if leg.chaining is None
            else unavailable(NO_PRODUCTION_SIMILARITY)
        )
    else:
        partition_ev = partition_metrics(faces, labels)
        order_ev = order_stability(
            lambda values: reference_threshold_cluster(values, similarity_threshold=threshold),
            vectors,
            n_orders=config.n_orders,
            seed=config.order_seed,
        )
        chaining_ev = (
            not_evaluated("no held-out verified pair evidence supplied")
            if leg.chaining is None
            else chaining_check(vectors, faces, similarity_threshold=threshold, chaining=leg.chaining)
        )

    if count >= 2 and config.knn_k <= count - 1:
        knn_edges = knn_neighbours(vectors, config.knn_k)
        mutual_ev = available(
            {
                "k": config.knn_k,
                "face_ids": face_ids,
                "edges": [
                    {"source_face_id": face_ids[i], "target_face_id": face_ids[j], "cosine_similarity": cos}
                    for i, j, cos in mutual_knn_graph(vectors, config.knn_k)
                ],
            }
        )
        neighbours_ev = available(
            {
                "k": config.knn_k,
                "metric": "cosine",
                "edges": [
                    {"source_face_id": face_ids[i], "target_face_id": face_ids[j], "cosine_similarity": cos}
                    for i, j, cos in knn_edges
                ],
            }
        )
    else:
        reason = "fewer than knn_k+1 faces"
        mutual_ev = unavailable(reason)
        neighbours_ev = unavailable(reason)

    dendrogram = (
        cosine_dendrogram(vectors, method=config.linkage, similarity_threshold=threshold) if count >= 2 else None
    )
    if dendrogram is None:
        dendrogram_ev = unavailable("fewer than two faces")
    else:
        dendrogram_ev = available(
            {
                "leaf_face_ids": face_ids,
                "linkage": [
                    [int(row[0]), int(row[1]), float(min(2.0, max(0.0, row[2]))), int(row[3])]
                    for row in dendrogram.linkage
                ],
                "cophenetic_correlation": available(dendrogram.cophenetic)
                if dendrogram.cophenetic is not None
                else unavailable("cophenetic correlation is undefined"),
            }
        )

    if has_threshold:
        cut_labels = None
        if dendrogram is not None and dendrogram.cut_labels is not None:
            cut_labels = [
                {"face_id": face_id, "label": int(label)}
                for face_id, label in zip(face_ids, dendrogram.cut_labels.tolist(), strict=True)
            ]
        elif count == 1:
            cut_labels = [{"face_id": face_ids[0], "label": 0}]
        cut = {"distance": 1.0 - threshold, "caption": CUT_CAPTION, "labels": cut_labels}
    else:
        cut = {"distance": None, "caption": UNCUT_CAPTION, "labels": None}

    if config.acceptance_tau is None:
        tau_ev = unavailable("no acceptance tau recorded")
    else:
        # A calibrated reference may lie outside the cosine-distance domain; never clamp it or use it as a cut.
        tau_ev = available({"tau": config.acceptance_tau, "distance": 1.0 - config.acceptance_tau, "label": TAU_LABEL})

    pca_ev = pca_spectrum(vectors)
    intra, inter = _pair_cosines(similarity, faces)
    histograms = [
        {
            "kind": "intra_identity_cosine",
            "result": _histogram(
                intra, lower=-1.0, upper=1.0, bins=config.histogram_bins, reason="no true named pairs"
            ),
        },
        {
            "kind": "inter_identity_cosine",
            "result": _histogram(
                inter, lower=-1.0, upper=1.0, bins=config.histogram_bins, reason="no inter-identity named pairs"
            ),
        },
        {
            "kind": "vector_norm",
            "result": _histogram(
                np.linalg.norm(vectors, axis=1),
                lower=0.0,
                upper=float(np.linalg.norm(vectors, axis=1).max()),
                bins=config.histogram_bins,
                reason="no faces",
            ),
        },
    ]

    if prior is None:
        companions = {
            "knn_jaccard": not_evaluated("no prior run of this leg key recorded"),
            "linear_cka": not_evaluated("no prior run of this leg key recorded"),
        }
    else:
        companions = _companions(leg, prior, config)

    projections = [
        _projection_entry(
            "umap-2d",
            projection_coords(
                vectors, n_neighbors=config.umap_n_neighbors, min_dist=config.umap_min_dist, seed=config.projection_seed
            ),
            faces,
        ),
        _projection_entry("pca-2d", pca_projection(vectors, seed=config.projection_seed), faces),
    ]

    entry = {
        "leg_key": leg.leg_key,
        "config": {
            "similarity_threshold": threshold,
            "metric": "cosine",
            "linkage": config.linkage,
            "production_algorithm": "hdbscan",
            "cluster_selection_epsilon": None if threshold is None else math.sqrt(2.0 * (1.0 - threshold)),
            "production_parameters": [{"name": name, "value": value} for name, value in config.production_parameters],
        },
        "dendrogram_cut": cut,
        "acceptance_tau_reference": tau_ev,
        "partition_metrics": partition_ev,
        "labels": labels_ev,
        "order_stability": order_ev,
        "chaining": chaining_ev,
        "mutual_knn": mutual_ev,
        "neighbours": neighbours_ev,
        "dendrogram": dendrogram_ev,
        "pca_spectrum": pca_ev,
        "histograms": histograms,
        "companions": companions,
        "projections": projections,
    }
    return _jsonable(entry)


def _projection_entry(name: str, coords: ProjectionCoords, faces: Sequence[LegFace]) -> dict[str, Any]:
    if coords.status is EvidenceStatus.available:
        if coords.coordinates is None:
            raise FrameContractError(f"projection {name} is available but holds no coordinates")
        data = [
            {"face_id": face.face_id, "coordinates": [float(x), float(y)]}
            for face, (x, y) in zip(faces, coords.coordinates.tolist(), strict=True)
        ]
        result: Evidence = available(data)
    else:
        result = Evidence(coords.status, coords.reason, None)
    return {
        "name": name,
        "method": coords.method,
        "n_components": 2,
        "seed": coords.seed,
        "diagnostic_only": True,
        "caption": PROJECTION_CAPTION,
        "parameters": dict(coords.parameters),
        "versions": [{"package": package, "version": version} for package, version in coords.versions],
        "result": result,
    }


def build_clusters_payload(entries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Assemble and validate the clusters-v1 document; legs sort by leg_key so the bytes are deterministic."""
    keys = [str(entry["leg_key"]) for entry in entries]
    if len(set(keys)) != len(keys):
        raise FrameContractError("clusters.json holds one entry per leg_key")
    payload: dict[str, Any] = {
        "schema_version": 1,
        "legs": [dict(entry) for entry in sorted(entries, key=lambda entry: str(entry["leg_key"]))],
    }
    validate_interchange("clusters-v1", payload)
    return payload


def write_clusters_json(payload: Mapping[str, Any], path: str | os.PathLike[str]) -> Path:
    """Validate, then write deterministic JSON atomically. Nothing is written when validation fails."""
    validate_interchange("clusters-v1", payload)
    target = Path(path)
    try:
        text = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
    except ValueError as exc:
        raise FrameContractError(f"clusters payload is not finite JSON: {exc}") from exc
    temporary = target.with_name(f".{target.name}.tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, target)
    except OSError as exc:
        if temporary.exists():
            temporary.unlink()
        raise FrameContractError(f"cannot write clusters.json at {target}: {exc}") from exc
    return target
