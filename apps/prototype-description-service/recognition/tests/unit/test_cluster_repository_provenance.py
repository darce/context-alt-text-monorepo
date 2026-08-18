"""R3-G2-2 / R3-G1-1: embedding_model provenance across the repository boundary.

Unit tests (no DB). Prove:
1. ``_to_domain`` stamps ``embedding_model`` from a loaded identity.
2. ``_to_domain`` leaves it ``None`` when identity is not loaded (no lazy load).
3. ``get_representative_embeddings_with_model`` returns majority-chosen model and
   embeddings matching ``get_representative_embeddings``.
4. ``get_member_fallback_embeddings_with_model`` returns ``(..., None)`` on empty.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from recognition.infrastructure.repositories.cluster_repository import (
    SqlAlchemyClusterRepository,
    _choose_embedding_model,
    _filter_embedding_pairs_to_single_model,
)

_LEGACY = "opencv-sface@128d/l2/cosine"
_PINNED = "opencv-sface+cv5.0.0.93/ort1.28@128d/l2/cosine"


def _make_identity(*, embedding_model: str | None, disposed_at=None) -> MagicMock:
    identity = MagicMock()
    identity.id = "identity-1"
    identity.media_id = 42
    identity.media_url = "http://example.test/face.jpg"
    identity.bbox_x = 1
    identity.bbox_y = 2
    identity.bbox_width = 30
    identity.bbox_height = 40
    identity.pose_pitch = 5.0
    identity.pose_yaw = -3.0
    identity.pose_roll = 0.5
    identity.confidence = 0.95
    identity.quality_score = 0.9
    identity.disposed_at = disposed_at
    identity.embedding_model = embedding_model
    return identity


def _make_rep(*, identity: MagicMock | None) -> MagicMock:
    rep = MagicMock()
    rep.id = "rep-1"
    rep.cluster_id = "cluster-1"
    rep.identity_id = "identity-1"
    rep.embedding = np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float32)
    rep.created_at = datetime(2026, 1, 1, tzinfo=UTC)
    rep.tenant_id = "tenant-1"
    rep.quality_score = 1.0
    rep.diversity_score = None
    rep.is_user_selected = False
    rep.is_provisional = False
    rep.disposed_at = None
    rep.identity = identity
    return rep


def _make_cluster(*, representatives: list[MagicMock]) -> MagicMock:
    cluster = MagicMock()
    cluster.id = "cluster-1"
    cluster.tenant_id = "tenant-1"
    cluster.label = None
    cluster.identity_count = len(representatives)
    cluster.created_at = datetime(2026, 1, 1, tzinfo=UTC)
    cluster.representative_identity_id = None
    cluster.clustering_algorithm = None
    cluster.user_confirmed = False
    cluster.dismissed_at = None
    cluster.representatives = representatives
    # Avoid centroid_data branch treating MagicMock as truthy loaded data.
    cluster.centroid_data = None
    return cluster


def _patch_instance_state(
    *,
    cluster: MagicMock,
    rep: MagicMock,
    identity_in_dict: bool,
    identity: MagicMock | None,
):
    """Control which relationships appear loaded without a real SQLAlchemy session."""

    def fake_instance_state(obj):
        state = MagicMock()
        if obj is cluster:
            state.dict = {"representatives": list(cluster.representatives)}
        elif obj is rep:
            if identity_in_dict:
                state.dict = {"identity": identity}
            else:
                state.dict = {}
        else:
            state.dict = {}
        return state

    return patch(
        "recognition.infrastructure.repositories.cluster_repository.instance_state",
        side_effect=fake_instance_state,
    )


def test_to_domain_stamps_embedding_model_from_loaded_identity() -> None:
    """R3-G2-2: eager-loaded identity.embedding_model must reach ClusterRepresentative.

    Goes red if the ``embedding_model=...`` stamp in ``_to_domain`` is removed:
    assertion fails with ``None != <model_id>``.
    """
    identity = _make_identity(embedding_model=_PINNED)
    rep = _make_rep(identity=identity)
    cluster = _make_cluster(representatives=[rep])
    repo = SqlAlchemyClusterRepository(MagicMock())

    with _patch_instance_state(
        cluster=cluster,
        rep=rep,
        identity_in_dict=True,
        identity=identity,
    ):
        domain = repo._to_domain(cluster)

    assert len(domain.representatives) == 1
    stamped = domain.representatives[0]
    assert stamped.embedding_model == _PINNED
    assert stamped.media_id == 42
    assert stamped.bbox_width == 30


def test_to_domain_embedding_model_none_when_identity_absent_no_lazy_load() -> None:
    """R3-G2-2: missing identity leaves embedding_model None without lazy-loading."""
    identity_accesses: list[str] = []

    class _LazyGuard:
        """Stand-in that fails closed if identity is accessed for loading."""

        def __bool__(self) -> bool:
            # Pose-bucket loop uses ``if r.identity:`` — treat as unloaded/absent.
            return False

        def __getattr__(self, name: str):
            identity_accesses.append(name)
            raise AssertionError(f"lazy load of identity.{name} must not be triggered")

    rep = _make_rep(identity=None)
    # Pose-bucket loop reads r.identity; keep it falsy and non-loadable.
    rep.identity = _LazyGuard()
    cluster = _make_cluster(representatives=[rep])
    repo = SqlAlchemyClusterRepository(MagicMock())

    with _patch_instance_state(
        cluster=cluster,
        rep=rep,
        identity_in_dict=False,
        identity=None,
    ):
        domain = repo._to_domain(cluster)

    assert len(domain.representatives) == 1
    assert domain.representatives[0].embedding_model is None
    # Provenance/debug path must not have pulled attributes off an unloaded identity.
    assert identity_accesses == []


class _FakeResult:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def all(self):
        return list(self._rows)


@pytest.mark.asyncio
async def test_get_representative_embeddings_with_model_majority_matches_plain() -> None:
    """R3-G1-1: with_model returns majority-chosen model; embeddings match plain API.

    Goes red if chosen model is taken as ``rows[0][1]`` under a minority-first
    ordering, or if the with_model path diverges from the plain embedding list.
    """
    emb_keep_a = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    emb_keep_b = np.array([0.0, 1.0, 0.0], dtype=np.float32)
    emb_drop = np.array([0.0, 0.0, 1.0], dtype=np.float32)
    # Minority model first so a naive rows[0][1] would pick the wrong model.
    rows = [
        (emb_drop, _LEGACY),
        (emb_keep_a, _PINNED),
        (emb_keep_b, _PINNED),
    ]
    expected_filtered = _filter_embedding_pairs_to_single_model(rows)
    expected_model = _choose_embedding_model([m for _, m in expected_filtered])
    assert expected_model == _PINNED  # sanity: majority, not rows[0]

    session = MagicMock()
    session.execute = AsyncMock(return_value=_FakeResult(rows))
    repo = SqlAlchemyClusterRepository(session)

    embeddings, chosen = await repo.get_representative_embeddings_with_model("cluster-1")
    plain = await repo.get_representative_embeddings("cluster-1")

    assert chosen == _PINNED
    assert chosen == expected_model
    assert len(embeddings) == 2
    assert len(plain) == 2
    for got, exp in zip(embeddings, plain, strict=True):
        np.testing.assert_array_equal(got, exp)
    np.testing.assert_array_equal(embeddings[0], emb_keep_a)
    np.testing.assert_array_equal(embeddings[1], emb_keep_b)


@pytest.mark.asyncio
async def test_get_member_fallback_embeddings_with_model_empty_returns_none_model() -> None:
    """R3-G1-1 / R3-G4-5: no rows → ``([], None)`` (fail-closed, no invented model)."""
    session = MagicMock()
    session.execute = AsyncMock(return_value=_FakeResult([]))
    repo = SqlAlchemyClusterRepository(session)

    embeddings, chosen = await repo.get_member_fallback_embeddings_with_model("cluster-1")

    assert embeddings == []
    assert chosen is None


@pytest.mark.asyncio
async def test_get_representative_embeddings_with_quality_returns_aligned_metrics() -> None:
    """R1-01: quality comes from the same representative+identity rows used for ranking."""
    emb_keep = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    emb_drop = np.array([0.0, 0.0, 1.0], dtype=np.float32)
    rows = [
        (emb_drop, _LEGACY, 0.11, 0.12, 0.13),
        (emb_keep, _PINNED, 0.91, 0.81, 0.71),
        (emb_keep, _PINNED, 0.92, 0.82, 0.72),
    ]
    session = MagicMock()
    session.execute = AsyncMock(return_value=_FakeResult(rows))
    repo = SqlAlchemyClusterRepository(session)

    embeddings, chosen, qualities = await repo.get_representative_embeddings_with_quality("cluster-1")

    assert chosen == _PINNED
    assert len(embeddings) == 2
    assert qualities == [(0.91, 0.81, 0.71), (0.92, 0.82, 0.72)]

