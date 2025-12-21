"""Unit tests for forced anchor split behavior."""

from __future__ import annotations

import uuid

from db.models import MediaIdentity as MediaIdentityModel
from recognition.application.orchestration.cluster_split import _force_anchor_split


def _make_identity(identity_id: uuid.UUID, media_id: int, embedding: list[float]) -> MediaIdentityModel:
    return MediaIdentityModel(
        id=identity_id,
        tenant_id=uuid.uuid4(),
        media_id=media_id,
        media_url=f"http://example.test/{media_id}.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=1,
        bbox_height=1,
        confidence=0.9,
        embedding=embedding,
    )


def _identity_ids(group: list[MediaIdentityModel]) -> set[str]:
    return {str(identity.id) for identity in group}


def test_force_anchor_split_produces_two_groups_when_all_similar() -> None:
    anchor_id = uuid.uuid4()
    anchor = _make_identity(anchor_id, 1, [1.0, 0.0])
    other_a = _make_identity(uuid.uuid4(), 2, [0.9, 0.1])
    other_b = _make_identity(uuid.uuid4(), 3, [0.8, 0.2])

    result = _force_anchor_split(
        [anchor, other_a, other_b],
        str(anchor_id),
        similarity_floor=0.95,
    )

    assert set(result.keys()) == {0, 1}
    assert str(anchor_id) in _identity_ids(result[0])
    assert len(result[1]) >= 1


def test_force_anchor_split_keeps_similar_identities_with_anchor() -> None:
    anchor_id = uuid.uuid4()
    anchor = _make_identity(anchor_id, 1, [1.0, 0.0])
    similar = _make_identity(uuid.uuid4(), 2, [0.9, 0.1])
    dissimilar = _make_identity(uuid.uuid4(), 3, [0.0, 1.0])

    result = _force_anchor_split(
        [anchor, similar, dissimilar],
        str(anchor_id),
        similarity_floor=0.8,
    )

    anchor_ids = _identity_ids(result[0])
    other_ids = _identity_ids(result[1])

    assert str(anchor_id) in anchor_ids
    assert str(similar.id) in anchor_ids
    assert str(dissimilar.id) in other_ids


def test_force_anchor_split_moves_farthest_identity_when_all_above_threshold() -> None:
    anchor_id = uuid.uuid4()
    anchor = _make_identity(anchor_id, 1, [1.0, 0.0])
    close = _make_identity(uuid.uuid4(), 2, [0.98, 0.05])
    farthest = _make_identity(uuid.uuid4(), 3, [0.8, 0.2])

    result = _force_anchor_split(
        [anchor, close, farthest],
        str(anchor_id),
        similarity_floor=0.6,
    )

    assert str(farthest.id) in _identity_ids(result[1])
