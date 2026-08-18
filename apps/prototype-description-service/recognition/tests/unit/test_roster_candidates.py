"""Unit tests for cluster → roster-person candidate ranking (UXW2-5)."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import numpy as np
import pytest

from recognition.application.settings import ClusteringSettings
from recognition.application.suggestions.roster_candidates import (
    QualityFlag,
    SimilarityBand,
    band_for,
    list_roster_candidates,
)


def _normalize(vec: np.ndarray) -> np.ndarray:
    arr = np.asarray(vec, dtype=np.float32)
    return arr / float(np.linalg.norm(arr))


def _rep(*, embedding: np.ndarray, embedding_model: str, quality_score: float = 1.0) -> SimpleNamespace:
    return SimpleNamespace(
        embedding=embedding,
        embedding_model=embedding_model,
        identity_id=str(uuid4()),
        quality_score=quality_score,
        debug_metrics={"landmark_quality": quality_score, "det_score": 0.99},
    )


class _FakeRosterRepo:
    def __init__(
        self,
        *,
        probe: SimpleNamespace | None,
        probe_embeddings: list[np.ndarray],
        probe_model: str | None,
        labeled: list[tuple[SimpleNamespace, list[SimpleNamespace]]],
    ) -> None:
        self._probe = probe
        self._probe_embeddings = probe_embeddings
        self._probe_model = probe_model
        self._labeled = labeled

    async def get_by_id(self, cluster_id: str) -> SimpleNamespace | None:
        if self._probe is None or str(self._probe.id) != str(cluster_id):
            return None
        return self._probe

    async def get_representative_embeddings_with_model(
        self, cluster_id: str
    ) -> tuple[list[np.ndarray], str | None]:
        if self._probe is None or str(self._probe.id) != str(cluster_id):
            return [], None
        return list(self._probe_embeddings), self._probe_model

    async def get_member_fallback_embeddings_with_model(
        self, cluster_id: str, limit: int = 4
    ) -> tuple[list[np.ndarray], str | None]:
        return [], None

    async def get_labeled_with_representatives(
        self, tenant_id: str
    ) -> list[tuple[SimpleNamespace, list[SimpleNamespace]]]:
        return list(self._labeled)


def test_band_for_uses_live_floor_and_ceiling() -> None:
    settings = ClusteringSettings(suggestion_floor=0.40, suggestion_ceiling=0.70)
    assert band_for(0.70, settings) is SimilarityBand.STRONG
    assert band_for(0.69, settings) is SimilarityBand.POSSIBLE
    assert band_for(0.40, settings) is SimilarityBand.POSSIBLE
    assert band_for(0.39, settings) is SimilarityBand.NONE


@pytest.mark.asyncio
async def test_bands_come_from_injected_settings_not_hardcoded() -> None:
    tenant_id = str(uuid4())
    probe_id = str(uuid4())
    same_model = "opencv-sface+cv5@128d/l2/cosine"
    probe_vec = _normalize(np.array([1.0, 0.0, 0.0]))
    strong_id = str(uuid4())
    possible_id = str(uuid4())
    none_id = str(uuid4())

    labeled = [
        (
            SimpleNamespace(id=strong_id, label="Ada", tenant_id=tenant_id),
            [_rep(embedding=_normalize(np.array([1.0, 0.0, 0.0])), embedding_model=same_model)],
        ),
        (
            SimpleNamespace(id=possible_id, label="Bea", tenant_id=tenant_id),
            [_rep(embedding=_normalize(np.array([0.55, 0.835, 0.0])), embedding_model=same_model)],
        ),
        (
            SimpleNamespace(id=none_id, label="Cyd", tenant_id=tenant_id),
            [_rep(embedding=_normalize(np.array([0.0, 1.0, 0.0])), embedding_model=same_model)],
        ),
    ]
    repo = _FakeRosterRepo(
        probe=SimpleNamespace(id=probe_id, tenant_id=tenant_id, representatives=[]),
        probe_embeddings=[probe_vec],
        probe_model=same_model,
        labeled=labeled,
    )
    settings = ClusteringSettings(suggestion_floor=0.40, suggestion_ceiling=0.80)

    result = await list_roster_candidates(
        tenant_id, probe_id, cluster_repository=repo, settings=settings, top_k=10
    )

    bands = {row.cluster_id: row.band for row in result.candidates}
    assert bands[strong_id] is SimilarityBand.STRONG
    assert bands[possible_id] is SimilarityBand.POSSIBLE
    assert bands[none_id] is SimilarityBand.NONE
    assert result.thresholds.suggestion_floor == 0.40
    assert result.thresholds.suggestion_ceiling == 0.80


@pytest.mark.asyncio
async def test_same_model_guard_excludes_foreign_embedding_space() -> None:
    tenant_id = str(uuid4())
    probe_id = str(uuid4())
    same_model = "opencv-sface+cv5@128d/l2/cosine"
    foreign_model = "buffalo_l@512d/l2/cosine"
    probe_vec = _normalize(np.array([1.0, 0.0, 0.0]))
    same_id = str(uuid4())
    foreign_id = str(uuid4())

    labeled = [
        (
            SimpleNamespace(id=foreign_id, label="Foreign", tenant_id=tenant_id),
            [_rep(embedding=_normalize(np.array([0.99, 0.01, 0.0])), embedding_model=foreign_model)],
        ),
        (
            SimpleNamespace(id=same_id, label="Same", tenant_id=tenant_id),
            [_rep(embedding=_normalize(np.array([0.8, 0.2, 0.0])), embedding_model=same_model)],
        ),
    ]
    repo = _FakeRosterRepo(
        probe=SimpleNamespace(id=probe_id, tenant_id=tenant_id, representatives=[]),
        probe_embeddings=[probe_vec],
        probe_model=same_model,
        labeled=labeled,
    )

    result = await list_roster_candidates(
        tenant_id,
        probe_id,
        cluster_repository=repo,
        settings=ClusteringSettings(suggestion_floor=0.10, suggestion_ceiling=0.90),
        top_k=10,
    )

    ids = [row.cluster_id for row in result.candidates]
    assert same_id in ids
    assert foreign_id not in ids


@pytest.mark.asyncio
async def test_empty_roster_returns_empty_candidates_not_error() -> None:
    tenant_id = str(uuid4())
    probe_id = str(uuid4())
    same_model = "opencv-sface+cv5@128d/l2/cosine"
    repo = _FakeRosterRepo(
        probe=SimpleNamespace(id=probe_id, tenant_id=tenant_id, representatives=[]),
        probe_embeddings=[_normalize(np.array([1.0, 0.0]))],
        probe_model=same_model,
        labeled=[],
    )

    result = await list_roster_candidates(
        tenant_id, probe_id, cluster_repository=repo, settings=ClusteringSettings(), top_k=10
    )

    assert result.candidates == []
    assert result.embedding_model == same_model
    assert result.model_id == same_model


@pytest.mark.asyncio
async def test_top_k_bounds_ranked_candidates() -> None:
    tenant_id = str(uuid4())
    probe_id = str(uuid4())
    same_model = "opencv-sface+cv5@128d/l2/cosine"
    probe_vec = _normalize(np.array([1.0, 0.0, 0.0]))
    labeled = []
    for idx in range(5):
        angle = 0.05 * idx
        labeled.append(
            (
                SimpleNamespace(id=str(uuid4()), label=f"P{idx}", tenant_id=tenant_id),
                [_rep(embedding=_normalize(np.array([1.0 - angle, angle, 0.0])), embedding_model=same_model)],
            )
        )
    repo = _FakeRosterRepo(
        probe=SimpleNamespace(id=probe_id, tenant_id=tenant_id, representatives=[]),
        probe_embeddings=[probe_vec],
        probe_model=same_model,
        labeled=labeled,
    )

    result = await list_roster_candidates(
        tenant_id, probe_id, cluster_repository=repo, settings=ClusteringSettings(), top_k=3
    )

    assert len(result.candidates) == 3
    sims = [row.similarity for row in result.candidates]
    assert sims == sorted(sims, reverse=True)


@pytest.mark.asyncio
async def test_low_quality_probe_sets_quality_flag() -> None:
    tenant_id = str(uuid4())
    probe_id = str(uuid4())
    same_model = "opencv-sface+cv5@128d/l2/cosine"
    labeled_id = str(uuid4())
    repo = _FakeRosterRepo(
        probe=SimpleNamespace(
            id=probe_id,
            tenant_id=tenant_id,
            representatives=[_rep(embedding=_normalize(np.array([1.0, 0.0])), embedding_model=same_model, quality_score=0.05)],
        ),
        probe_embeddings=[_normalize(np.array([1.0, 0.0]))],
        probe_model=same_model,
        labeled=[
            (
                SimpleNamespace(id=labeled_id, label="Ada", tenant_id=tenant_id),
                [_rep(embedding=_normalize(np.array([1.0, 0.0])), embedding_model=same_model)],
            )
        ],
    )
    settings = ClusteringSettings(fatal_quality_floor=0.20)

    result = await list_roster_candidates(
        tenant_id, probe_id, cluster_repository=repo, settings=settings, top_k=10
    )

    assert result.candidates
    assert result.candidates[0].quality_flag is QualityFlag.LOW_QUALITY
