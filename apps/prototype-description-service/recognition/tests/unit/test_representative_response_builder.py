"""Unit tests for shared representative HTTP response builder."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import numpy as np

from recognition.domain.representative import ClusterRepresentative
from recognition.interface_adapters.http.face_box import representative_response_from_domain


def _rep(**overrides) -> ClusterRepresentative:
    base = {
        "id": str(uuid4()),
        "cluster_id": str(uuid4()),
        "identity_id": str(uuid4()),
        "embedding": np.zeros(512, dtype=np.float32),
        "created_at": datetime.now(tz=UTC),
        "media_id": 101,
        "media_url": "http://example.test/media/101.jpg",
        "bbox_x": 1,
        "bbox_y": 2,
        "bbox_width": 30,
        "bbox_height": 40,
        "is_user_selected": False,
    }
    base.update(overrides)
    return ClusterRepresentative(**base)


def test_builder_propagates_is_user_selected() -> None:
    response = representative_response_from_domain(_rep(is_user_selected=True))
    assert response.is_pinned is True
    assert response.model_dump(by_alias=True)["is_user_selected"] is True


def test_builder_passes_media_id_through_raw_including_none() -> None:
    with_id = representative_response_from_domain(_rep(media_id=101))
    assert with_id.media_id == "101"

    without_id = representative_response_from_domain(_rep(media_id=None))
    assert without_id.media_id is None
    assert without_id.model_dump(by_alias=True)["media_id"] is None
