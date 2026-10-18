"""CVUP1-R3-18: domain MediaIdentity carries embedding_model provenance."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from recognition.application.suggestions.embedding_space import (
    choose_embedding_model,
    cluster_embedding_model,
    filter_to_active_embedding_space,
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


def test_choose_embedding_model_majority_and_lex_tie() -> None:
    assert choose_embedding_model(["b", "a", "b"]) == "b"
    assert choose_embedding_model(["b", "a"]) == "a"
    assert choose_embedding_model([None, ""]) is None


def test_filter_to_active_space_fail_closed_when_unresolved() -> None:
    rows = [
        SimpleNamespace(embedding_model="space-a"),
        SimpleNamespace(embedding_model="space-b"),
    ]
    with patch(
        "recognition.application.embedding.manifest.try_active_embedding_model_id",
        return_value=None,
    ):
        assert filter_to_active_embedding_space(rows) == []


def test_filter_to_active_space_never_majority_falls_back() -> None:
    rows = [
        SimpleNamespace(embedding_model="space-a"),
        SimpleNamespace(embedding_model="space-a"),
        SimpleNamespace(embedding_model="space-b"),
    ]
    with patch(
        "recognition.application.embedding.manifest.try_active_embedding_model_id",
        return_value="space-b",
    ):
        kept = filter_to_active_embedding_space(rows)
    assert [row.embedding_model for row in kept] == ["space-b"]


def test_filter_to_active_space_excludes_single_foreign_model() -> None:
    rows = [
        SimpleNamespace(embedding_model="space-a"),
        SimpleNamespace(embedding_model="space-a"),
    ]
    with patch(
        "recognition.application.embedding.manifest.try_active_embedding_model_id",
        return_value="space-b",
    ):
        assert filter_to_active_embedding_space(rows) == []


def test_filter_to_active_space_excludes_unstamped_rows_mixed_with_stamp() -> None:
    unstamped = SimpleNamespace(embedding_model=None)
    active = SimpleNamespace(embedding_model="space-b")
    with patch(
        "recognition.application.embedding.manifest.try_active_embedding_model_id",
        return_value="space-b",
    ):
        assert filter_to_active_embedding_space([unstamped, active]) == [active]


def test_build_domain_identities_preserves_embedding_model_stamp() -> None:
    """Clustering domain mapping must keep provenance the helper already stamps."""
    from uuid import uuid4

    from recognition.application.orchestration.clustering.orchestrator import IncrementalClusteringRunner

    merge_id = uuid4()
    row = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        media_id=7,
        embedding=np.ones(4, dtype=np.float32),
        confidence=0.91,
        bbox_width=12,
        bbox_height=14,
        bbox_x=1,
        bbox_y=2,
        pose_pitch=None,
        pose_yaw=None,
        pose_roll=None,
        image_phash=None,
        sharpness=None,
        embedding_norm=None,
        occlusion_severity=None,
        moved_by_merge_id=merge_id,
        embedding_model="space-a",
    )

    identities = IncrementalClusteringRunner._build_domain_identities([row])  # type: ignore[arg-type]

    assert len(identities) == 1
    assert identities[0].embedding_model == "space-a"
    assert identities[0].moved_by_merge_id == str(merge_id)
