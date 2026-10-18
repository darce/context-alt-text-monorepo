"""Anchor-based split helpers."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from db.models import MediaIdentity as MediaIdentityModel
from recognition.config import get_settings as get_recognition_settings
from recognition.domain.cluster import IdentityCluster
from recognition.shared.similarity import compute_face_similarity


def force_anchor_split(
    identities: Sequence[MediaIdentityModel],
    anchor_identity_id: str,
    *,
    similarity_floor: float | None = None,
) -> dict[int, list[MediaIdentityModel]]:
    """Force a two-way split around an anchor identity."""
    if similarity_floor is None:
        similarity_floor = get_recognition_settings().clustering.anchor_split_similarity_floor

    anchor = None
    remaining: list[MediaIdentityModel] = []
    identity_list = list(identities)
    for identity in identity_list:
        if str(identity.id).lower() == anchor_identity_id:
            anchor = identity
        else:
            remaining.append(identity)
    if anchor is None or not remaining:
        return {0: identity_list}

    anchor_vec = np.asarray(anchor.embedding, dtype=np.float32)
    anchor_group: list[MediaIdentityModel] = [anchor]
    other_group: list[MediaIdentityModel] = []
    similarity_by_identity: list[tuple[MediaIdentityModel, float]] = []

    for identity in remaining:
        identity_vec = np.asarray(identity.embedding, dtype=np.float32)
        similarity = compute_face_similarity(anchor_vec, identity_vec)
        similarity_by_identity.append((identity, similarity))
        if similarity >= similarity_floor:
            anchor_group.append(identity)
        else:
            other_group.append(identity)

    if not other_group:
        farthest_identity, _similarity = min(similarity_by_identity, key=lambda item: item[1])
        anchor_group = [member for member in anchor_group if member is not farthest_identity]
        other_group = [farthest_identity]

    if not other_group:
        return {0: identity_list}

    return {0: anchor_group, 1: other_group}


def determine_label_owner(
    *,
    user_label: str | None,
    original_cluster: IdentityCluster,
    anchor_key: str | None,
    identity_to_label: dict[str, int],
    largest_label: int,
    clusters_by_label: dict[int, list[MediaIdentityModel]],
    original_identities: Sequence[MediaIdentityModel],
) -> int | None:
    """Determine which cluster group should inherit the original label."""
    if not user_label:
        return None

    if anchor_key:
        anchor_label = identity_to_label.get(anchor_key)
        if anchor_label is not None:
            return anchor_label

    if original_cluster.representative_identity_id:
        rep_id = original_cluster.representative_identity_id.lower()
        rep_label = identity_to_label.get(rep_id)
        if rep_label is not None:
            return rep_label

    reference_vec = original_cluster.centroid
    if reference_vec is None:
        reference_vec = np.mean(
            np.asarray([identity.embedding for identity in original_identities], dtype=np.float32),
            axis=0,
        )
    else:
        reference_vec = np.asarray(reference_vec, dtype=np.float32)

    reference_norm = float(np.linalg.norm(reference_vec))
    if reference_norm > 0:
        reference_vec = reference_vec / reference_norm

    best_label = None
    best_similarity = -1.0

    for label, group_members in clusters_by_label.items():
        if not group_members:
            continue
        group_vec = np.mean(np.asarray([m.embedding for m in group_members], dtype=np.float32), axis=0)
        group_norm = float(np.linalg.norm(group_vec))
        if group_norm > 0:
            group_vec = group_vec / group_norm

        similarity = float(np.dot(group_vec, reference_vec))
        if similarity > best_similarity:
            best_similarity = similarity
            best_label = label

    if best_label is not None:
        return best_label

    return largest_label
