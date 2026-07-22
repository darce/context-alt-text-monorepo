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

    face_ids: list[str] = []
    face_index: dict[str, int] = {}
    for decision in decisions:
        face_id = decision.candidate.identity.id
        if face_id not in face_index:
            face_index[face_id] = len(face_ids)
            face_ids.append(face_id)

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
        if (
            previous is None
            or decision.candidate.discovery_similarity > previous.candidate.discovery_similarity
        ):
            edge[(fi, ci)] = decision

    n_faces = len(face_ids)
    n_clusters = len(cluster_ids)
    if n_clusters == 0:
        return [], set(face_ids)

    cost = np.full((n_faces, n_clusters), _UNASSIGNED_COST, dtype=np.float64)
    for (fi, ci), decision in edge.items():
        cost[fi, ci] = -float(decision.candidate.discovery_similarity)

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

    losers = set(face_ids) - assigned_faces
    return kept, losers
