"""Within-photo one-to-one conflict resolution for accepted assignment decisions.

Discovery emits ≤1 candidate per face today, so the solver's job is conflict
resolution — when ≥2 faces in one photo hold accepted candidates for the same
cluster, exactly one (highest similarity) keeps it; losers route to the
unknown/new-cluster path. ``linear_sum_assignment`` over faces × distinct
candidate clusters generalizes unchanged if discovery ever emits top-k.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
from scipy.optimize import linear_sum_assignment

from recognition.application.assignment.decision import AssignmentDecision

# Finite sentinel for missing (face, cluster) edges. -inf padding makes the
# Hungarian solver raise; a large finite cost is post-filtered as unassigned.
_UNASSIGNED_COST = 1.0e6


@dataclass(frozen=True, slots=True)
class PhotoConflictResult:
    """Post-joint accepted set plus identity ids that lost their assignment."""

    accepted: list[AssignmentDecision]
    loser_identity_ids: frozenset[str]


def group_accepted_by_media(
    decisions: Sequence[AssignmentDecision],
) -> dict[str, list[AssignmentDecision]]:
    """Group accepted decisions by ``identity.media_id`` (string form)."""
    by_media: dict[str, list[AssignmentDecision]] = {}
    for decision in decisions:
        media_id = str(decision.candidate.identity.media_id)
        by_media.setdefault(media_id, []).append(decision)
    return by_media


def resolve_photo_conflicts(
    decisions_by_media: Mapping[str, Sequence[AssignmentDecision]],
) -> PhotoConflictResult:
    """Resolve within-photo cluster conflicts via linear sum assignment.

    Args:
        decisions_by_media: Accepted ``AssignmentDecision``s grouped by media_id.

    Returns:
        PhotoConflictResult with the post-joint accepted decisions and the set of
        loser identity ids (must flow to new-cluster/unknown, never orphan).
    """
    accepted: list[AssignmentDecision] = []
    losers: set[str] = set()
    for decisions in decisions_by_media.values():
        kept, media_losers = _resolve_one_photo(list(decisions))
        accepted.extend(kept)
        losers.update(media_losers)
    return PhotoConflictResult(accepted=accepted, loser_identity_ids=frozenset(losers))


def _resolve_one_photo(
    decisions: list[AssignmentDecision],
) -> tuple[list[AssignmentDecision], set[str]]:
    """Resolve conflicts among accepted decisions that share one media_id."""
    if not decisions:
        return [], set()
    if len(decisions) == 1:
        return list(decisions), set()

    # Fast path: unique faces and unique clusters ⇒ no conflict possible.
    face_ids_ordered = [d.candidate.identity.id for d in decisions]
    cluster_ids_ordered = [d.candidate.cluster_id for d in decisions]
    if len(set(face_ids_ordered)) == len(decisions) and len(set(cluster_ids_ordered)) == len(decisions):
        return list(decisions), set()

    # Stable face order: higher confidence first, then identity id (tie-break).
    face_ids: list[str] = []
    face_index: dict[str, int] = {}
    face_meta: dict[str, tuple[float, str]] = {}
    for decision in decisions:
        face_id = decision.candidate.identity.id
        conf = float(decision.candidate.identity.confidence)
        face_meta[face_id] = (conf, face_id)
        if face_id not in face_index:
            face_index[face_id] = len(face_ids)
            face_ids.append(face_id)
    face_ids = sorted(face_ids, key=lambda fid: (-face_meta[fid][0], face_meta[fid][1]))
    face_index = {face_id: i for i, face_id in enumerate(face_ids)}

    cluster_ids: list[str] = []
    cluster_index: dict[str, int] = {}
    edge: dict[tuple[int, int], AssignmentDecision] = {}
    for decision in decisions:
        cluster_id = decision.candidate.cluster_id
        if cluster_id not in cluster_index:
            cluster_index[cluster_id] = len(cluster_ids)
            cluster_ids.append(cluster_id)
        fi = face_index[decision.candidate.identity.id]
        ci = cluster_index[cluster_id]
        previous = edge.get((fi, ci))
        if previous is None or _edge_prefers(decision, previous):
            edge[(fi, ci)] = decision

    n_faces = len(face_ids)
    n_clusters = len(cluster_ids)
    if n_clusters == 0:
        return [], set(face_ids)

    cost = np.full((n_faces, n_clusters), _UNASSIGNED_COST, dtype=np.float64)
    for (fi, ci), decision in edge.items():
        # LAP minimizes cost. Primary objective only: higher similarity → lower
        # cost. Confidence + lex id are applied in pure-Python post-solve
        # canonicalization (FIR6V11-01) — micro-offsets in the cost matrix are
        # float64-absorbed inside the Hungarian solver and were inert.
        sim = float(decision.candidate.discovery_similarity)
        if not np.isfinite(sim):
            # Non-finite edges stay at the unassigned sentinel (predrop / LC-11).
            continue
        cost[fi, ci] = -sim

    # Drop faces whose every edge is missing (would be all-below-threshold under top-k).
    active_faces = [fi for fi in range(n_faces) if bool(np.any(cost[fi] < (_UNASSIGNED_COST * 0.5)))]
    if not active_faces:
        return [], set(face_ids)

    sub = cost[np.ix_(active_faces, list(range(n_clusters)))]
    row_ind, col_ind = linear_sum_assignment(sub)

    kept: list[AssignmentDecision] = []
    assigned_faces: set[str] = set()
    for row, col in zip(row_ind, col_ind, strict=True):
        if float(sub[row, col]) >= (_UNASSIGNED_COST * 0.5):
            continue
        face_i = active_faces[int(row)]
        decision = edge.get((face_i, int(col)))
        if decision is None:
            continue
        kept.append(decision)
        assigned_faces.add(face_ids[face_i])

    kept, losers = _canonicalize_lap_ties(
        kept=kept,
        assigned_faces=assigned_faces,
        all_face_ids=face_ids,
        edge=edge,
    )
    return kept, losers


def _canonicalize_lap_ties(
    *,
    kept: list[AssignmentDecision],
    assigned_faces: set[str],
    all_face_ids: list[str],
    edge: dict[tuple[int, int], AssignmentDecision],
) -> tuple[list[AssignmentDecision], set[str]]:
    """Post-solve conf/lex preference among equal-similarity contenders (FIR6V11-01).

    LAP cost encodes only ``-sim``. When multiple faces share the same
    discovery similarity to a cluster, pure Python re-picks the winner by
    higher confidence then lexicographically smaller identity id — without
    relying on float micro-offsets the solver absorbs.
    """
    if not kept:
        return [], set(all_face_ids)

    kept_by_cluster: dict[str, AssignmentDecision] = {
        d.candidate.cluster_id: d for d in kept
    }
    edges_by_cluster: dict[str, list[AssignmentDecision]] = {}
    for decision in edge.values():
        edges_by_cluster.setdefault(decision.candidate.cluster_id, []).append(decision)

    assigned = set(assigned_faces)
    for cluster_id, winner in list(kept_by_cluster.items()):
        win_sim = float(winner.candidate.discovery_similarity)
        if not np.isfinite(win_sim):
            continue
        contenders = [
            d
            for d in edges_by_cluster.get(cluster_id, ())
            if np.isfinite(float(d.candidate.discovery_similarity))
            and float(d.candidate.discovery_similarity) == win_sim
        ]
        if len(contenders) <= 1:
            continue
        preferred = contenders[0]
        for cand in contenders[1:]:
            if _edge_prefers(cand, preferred):
                preferred = cand
        if preferred.candidate.identity.id == winner.candidate.identity.id:
            continue
        pref_id = preferred.candidate.identity.id
        # Promote preferred only when it is currently unassigned (top-1 conflict
        # path). Multi-edge reassignment is out of scope for discovery top-1.
        if pref_id in assigned:
            continue
        kept_by_cluster[cluster_id] = preferred
        assigned.discard(winner.candidate.identity.id)
        assigned.add(pref_id)

    new_kept = list(kept_by_cluster.values())
    losers = set(all_face_ids) - {d.candidate.identity.id for d in new_kept}
    return new_kept, losers


def _edge_prefers(candidate: AssignmentDecision, incumbent: AssignmentDecision) -> bool:
    """True when candidate should replace incumbent on the same (face, cluster) edge.

    Order: higher discovery similarity, then higher confidence, then
    lexicographically smaller identity id (FIR6RC-04 / FIR6V11-01).
    """
    c_sim = float(candidate.candidate.discovery_similarity)
    i_sim = float(incumbent.candidate.discovery_similarity)
    if c_sim != i_sim:
        return c_sim > i_sim
    c_conf = float(candidate.candidate.identity.confidence)
    i_conf = float(incumbent.candidate.identity.confidence)
    if c_conf != i_conf:
        return c_conf > i_conf
    return candidate.candidate.identity.id < incumbent.candidate.identity.id
