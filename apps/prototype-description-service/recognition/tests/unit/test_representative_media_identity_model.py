"""CVUP1-R3-18: domain MediaIdentity carries embedding_model provenance."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np

from recognition.application.suggestions.embedding_space import (
    cluster_embedding_model,
    models_are_same_space,
)
from recognition.domain.cluster import IdentityCluster
from recognition.domain.identity import MediaIdentity
from recognition.domain.representative import ClusterRepresentative


def test_media_identity_exposes_embedding_model() -> None:
    identity = MediaIdentity(
        id="id-1",
        tenant_id="tenant-1",
        media_id="media-1",
        embedding=np.ones(4, dtype=np.float32),
        confidence=0.9,
        bbox_width=10,
        bbox_height=10,
        embedding_model="opencv-sface+cv5@128d/l2/cosine",
    )

    assert identity.embedding_model == "opencv-sface+cv5@128d/l2/cosine"


def test_media_identity_embedding_model_defaults_to_none() -> None:
    identity = MediaIdentity(
        id="id-1",
        tenant_id="tenant-1",
        media_id="media-1",
        embedding=np.ones(4, dtype=np.float32),
        confidence=0.9,
        bbox_width=10,
        bbox_height=10,
    )

    assert identity.embedding_model is None


def test_cluster_embedding_model_majority_from_reps() -> None:
    cluster = IdentityCluster(
        tenant_id="tenant-1",
        is_labeled=False,
        identity_count=2,
        representatives=[
            ClusterRepresentative(
                id="r1",
                cluster_id="c1",
                identity_id="i1",
                embedding=np.ones(2, dtype=np.float32),
                created_at=datetime.now(tz=UTC),
                embedding_model="space-a",
            ),
            ClusterRepresentative(
                id="r2",
                cluster_id="c1",
                identity_id="i2",
                embedding=np.ones(2, dtype=np.float32),
                created_at=datetime.now(tz=UTC),
                embedding_model="space-a",
            ),
        ],
    )

    assert cluster_embedding_model(cluster) == "space-a"


def test_models_are_same_space_legacy_none_and_mismatch() -> None:
    assert models_are_same_space(None, None) is True
    assert models_are_same_space("a", "a") is True
    assert models_are_same_space("a", "b") is False
    assert models_are_same_space("a", None) is False
    assert models_are_same_space(None, "a") is False
