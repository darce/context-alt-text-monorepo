"""Unit tests for cluster → roster-person candidate ranking (UXW2-5 / R1)."""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import numpy as np
import pytest

from recognition.application.settings import ClusteringSettings
from recognition.application.suggestions.roster_candidates import (
    MAX_ROSTER_CANDIDATES_TOP_K,
    QualityFlag,
    SimilarityBand,
    _quality_flag_from_samples,
    band_for,
    list_roster_candidates,
)


def _normalize(vec: np.ndarray) -> np.ndarray:
    arr = np.asarray(vec, dtype=np.float32)
    return arr / float(np.linalg.norm(arr))


def _rep(
    *,
    embedding: np.ndarray,
    embedding_model: str,
    quality_score: float | None = 1.0,
    landmark_quality: float | None = None,
    det_score: float | None = 0.99,
) -> SimpleNamespace:
    metrics: dict[str, float] = {}
    if landmark_quality is not None:
        metrics["landmark_quality"] = landmark_quality
    if det_score is not None:
        metrics["det_score"] = det_score
    return SimpleNamespace(
        embedding=embedding,
        embedding_model=embedding_model,
        identity_id=str(uuid4()),
        quality_score=quality_score,
        debug_metrics=metrics,
    )


class _FakeRosterRepo:
    """Mirrors production: get_by_id has no representatives; quality lives on ranking rows."""

    def __init__(
        self,
        *,
        probe: SimpleNamespace | None,
        probe_embeddings: list[np.ndarray],
        probe_model: str | None,
        labeled: list[tuple[SimpleNamespace, list[SimpleNamespace]]],
        probe_qualities: list[tuple[float | None, float | None, float | None]] | None = None,
        member_fallback: tuple[list[np.ndarray], str | None, list[tuple[float | None, float | None, float | None]]]
        | None = None,
    ) -> None:
        self._probe = probe
        self._probe_embeddings = probe_embeddings
        self._probe_model = probe_model
        self._labeled = labeled
        if probe_qualities is None:
            self._probe_qualities = [(None, None, None) for _ in probe_embeddings]
        else:
            self._probe_qualities = probe_qualities
        self._member_fallback = member_fallback or ([], None, [])

    async def get_by_id(self, cluster_id: str) -> SimpleNamespace | None:
        if self._probe is None or str(self._probe.id) != str(cluster_id):
            return None
        # Return the probe object so fused_low representatives are visible.
        # Production quality must still come from ranking-row loaders, not these.
        return self._probe

    async def get_representative_embeddings_with_model(
        self, cluster_id: str
    ) -> tuple[list[np.ndarray], str | None]:
        embeddings, model, _ = await self.get_representative_embeddings_with_quality(cluster_id)
        return embeddings, model

    async def get_representative_embeddings_with_quality(
        self, cluster_id: str
    ) -> tuple[list[np.ndarray], str | None, list[tuple[float | None, float | None, float | None]]]:
        if self._probe is None or str(self._probe.id) != str(cluster_id):
            return [], None, []
        return list(self._probe_embeddings), self._probe_model, list(self._probe_qualities)

    async def get_member_fallback_embeddings_with_model(
        self, cluster_id: str, limit: int = 4
    ) -> tuple[list[np.ndarray], str | None]:
        # Independent of the quality loader so preferring with_quality is observable.
        return [], None

    async def get_member_fallback_embeddings_with_quality(
        self, cluster_id: str, limit: int = 4
    ) -> tuple[list[np.ndarray], str | None, list[tuple[float | None, float | None, float | None]]]:
        embeddings, model, qualities = self._member_fallback
        return list(embeddings)[:limit], model, list(qualities)[:limit]

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
        probe=SimpleNamespace(id=probe_id, tenant_id=tenant_id),
        probe_embeddings=[probe_vec],
        probe_model=same_model,
        labeled=labeled,
        probe_qualities=[(1.0, 1.0, 0.99)],
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
    assert result.quality_flag is QualityFlag.OK
    assert not hasattr(result.candidates[0], "quality_flag") or "quality_flag" not in result.candidates[0].__dataclass_fields__


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
        probe=SimpleNamespace(id=probe_id, tenant_id=tenant_id),
        probe_embeddings=[probe_vec],
        probe_model=same_model,
        labeled=labeled,
        probe_qualities=[(1.0, 1.0, 0.99)],
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
        probe=SimpleNamespace(id=probe_id, tenant_id=tenant_id),
        probe_embeddings=[_normalize(np.array([1.0, 0.0]))],
        probe_model=same_model,
        labeled=[],
        probe_qualities=[(1.0, 1.0, 0.99)],
    )

    result = await list_roster_candidates(
        tenant_id, probe_id, cluster_repository=repo, settings=ClusteringSettings(), top_k=10
    )

    assert result.candidates == []
    assert result.embedding_model == same_model
    assert result.model_id == same_model
    assert result.probe_face_count == 1
    assert result.reference_face_count == 0
    assert result.quality_flag is QualityFlag.OK


@pytest.mark.asyncio
async def test_top_k_returns_exact_ids_from_out_of_rank_seed() -> None:
    """R1-05: insert out of rank order; assert exact surviving top ids (not just length)."""
    tenant_id = str(uuid4())
    probe_id = str(uuid4())
    same_model = "opencv-sface+cv5@128d/l2/cosine"
    probe_vec = _normalize(np.array([1.0, 0.0, 0.0]))
    worst_id = "aaaaaaaa-aaaa-aaaa-aaaa-000000000005"
    mid_id = "bbbbbbbb-bbbb-bbbb-bbbb-000000000003"
    best_id = "cccccccc-cccc-cccc-cccc-000000000001"
    fourth_id = "dddddddd-dddd-dddd-dddd-000000000004"
    # Seed worst-first so a "take first k of insertion order" implementation fails.
    labeled = [
        (
            SimpleNamespace(id=worst_id, label="Worst", tenant_id=tenant_id),
            [_rep(embedding=_normalize(np.array([0.2, 0.98, 0.0])), embedding_model=same_model)],
        ),
        (
            SimpleNamespace(id=fourth_id, label="Fourth", tenant_id=tenant_id),
            [_rep(embedding=_normalize(np.array([0.55, 0.835, 0.0])), embedding_model=same_model)],
        ),
        (
            SimpleNamespace(id=best_id, label="Best", tenant_id=tenant_id),
            [_rep(embedding=_normalize(np.array([1.0, 0.0, 0.0])), embedding_model=same_model)],
        ),
        (
            SimpleNamespace(id=mid_id, label="Mid", tenant_id=tenant_id),
            [_rep(embedding=_normalize(np.array([0.9, 0.435, 0.0])), embedding_model=same_model)],
        ),
    ]
    repo = _FakeRosterRepo(
        probe=SimpleNamespace(id=probe_id, tenant_id=tenant_id),
        probe_embeddings=[probe_vec],
        probe_model=same_model,
        labeled=labeled,
        probe_qualities=[(1.0, 1.0, 0.99)],
    )

    result = await list_roster_candidates(
        tenant_id, probe_id, cluster_repository=repo, settings=ClusteringSettings(), top_k=3
    )

    assert [row.cluster_id for row in result.candidates] == [best_id, mid_id, fourth_id]
    assert worst_id not in {row.cluster_id for row in result.candidates}


@pytest.mark.asyncio
async def test_multi_rep_cluster_uses_max_not_mean_or_first() -> None:
    """R1-05: a 2-rep cluster (0.2, 0.9) must rank on 0.9."""
    tenant_id = str(uuid4())
    probe_id = str(uuid4())
    same_model = "opencv-sface+cv5@128d/l2/cosine"
    probe_vec = _normalize(np.array([1.0, 0.0, 0.0]))
    multi_id = str(uuid4())
    repo = _FakeRosterRepo(
        probe=SimpleNamespace(id=probe_id, tenant_id=tenant_id),
        probe_embeddings=[probe_vec],
        probe_model=same_model,
        labeled=[
            (
                SimpleNamespace(id=multi_id, label="Split", tenant_id=tenant_id),
                [
                    _rep(embedding=_normalize(np.array([0.2, 0.98, 0.0])), embedding_model=same_model),
                    _rep(embedding=_normalize(np.array([0.9, 0.435, 0.0])), embedding_model=same_model),
                ],
            )
        ],
        probe_qualities=[(1.0, 1.0, 0.99)],
    )

    result = await list_roster_candidates(
        tenant_id, probe_id, cluster_repository=repo, settings=ClusteringSettings(), top_k=10
    )

    assert len(result.candidates) == 1
    assert result.candidates[0].similarity == pytest.approx(0.9, abs=0.02)
    assert result.reference_face_count == 2


@pytest.mark.asyncio
async def test_quality_flag_ok_when_metrics_above_floor() -> None:
    """R1-05: keep an OK case (not only LOW)."""
    tenant_id = str(uuid4())
    probe_id = str(uuid4())
    same_model = "opencv-sface+cv5@128d/l2/cosine"
    labeled_id = str(uuid4())
    repo = _FakeRosterRepo(
        probe=SimpleNamespace(id=probe_id, tenant_id=tenant_id),
        probe_embeddings=[_normalize(np.array([1.0, 0.0]))],
        probe_model=same_model,
        labeled=[
            (
                SimpleNamespace(id=labeled_id, label="Ada", tenant_id=tenant_id),
                [_rep(embedding=_normalize(np.array([1.0, 0.0])), embedding_model=same_model)],
            )
        ],
        probe_qualities=[(0.9, 0.85, 0.99)],
    )

    result = await list_roster_candidates(
        tenant_id,
        probe_id,
        cluster_repository=repo,
        settings=ClusteringSettings(fatal_quality_floor=0.20, fatal_confidence_floor=0.30),
        top_k=10,
    )

    assert result.quality_flag is QualityFlag.OK
    assert result.candidates[0].band is SimilarityBand.STRONG


@pytest.mark.parametrize(
    "qualities",
    [
        ((None, None, 0.05),),  # det_score-only low
        ((None, 0.05, None),),  # landmark-only low
        ((0.05, None, None),),  # quality_score-only low
    ],
)
@pytest.mark.asyncio
async def test_quality_flag_low_from_single_metric(
    qualities: tuple[tuple[float | None, float | None, float | None], ...],
) -> None:
    """R1-05: parametrize det-only and landmark-only low cases."""
    tenant_id = str(uuid4())
    probe_id = str(uuid4())
    same_model = "opencv-sface+cv5@128d/l2/cosine"
    labeled_id = str(uuid4())
    repo = _FakeRosterRepo(
        probe=SimpleNamespace(id=probe_id, tenant_id=tenant_id),
        probe_embeddings=[_normalize(np.array([1.0, 0.0]))],
        probe_model=same_model,
        labeled=[
            (
                SimpleNamespace(id=labeled_id, label="Ada", tenant_id=tenant_id),
                [_rep(embedding=_normalize(np.array([1.0, 0.0])), embedding_model=same_model)],
            )
        ],
        probe_qualities=list(qualities),
    )

    result = await list_roster_candidates(
        tenant_id,
        probe_id,
        cluster_repository=repo,
        settings=ClusteringSettings(fatal_quality_floor=0.20, fatal_confidence_floor=0.30),
        top_k=10,
    )

    assert result.quality_flag is QualityFlag.LOW_QUALITY


@pytest.mark.asyncio
async def test_quality_flag_fail_closed_when_metrics_missing() -> None:
    """R1-01: missing quality metrics fail closed to low_quality."""
    tenant_id = str(uuid4())
    probe_id = str(uuid4())
    same_model = "opencv-sface+cv5@128d/l2/cosine"
    labeled_id = str(uuid4())
    repo = _FakeRosterRepo(
        probe=SimpleNamespace(id=probe_id, tenant_id=tenant_id),
        probe_embeddings=[_normalize(np.array([1.0, 0.0]))],
        probe_model=same_model,
        labeled=[
            (
                SimpleNamespace(id=labeled_id, label="Ada", tenant_id=tenant_id),
                [_rep(embedding=_normalize(np.array([1.0, 0.0])), embedding_model=same_model)],
            )
        ],
        probe_qualities=[(None, None, None)],
    )

    result = await list_roster_candidates(
        tenant_id, probe_id, cluster_repository=repo, settings=ClusteringSettings(), top_k=10
    )

    assert result.quality_flag is QualityFlag.LOW_QUALITY


@pytest.mark.asyncio
async def test_quality_does_not_read_get_by_id_representatives() -> None:
    """R1-01: fused reps on get_by_id must not be the quality source."""
    tenant_id = str(uuid4())
    probe_id = str(uuid4())
    same_model = "opencv-sface+cv5@128d/l2/cosine"
    labeled_id = str(uuid4())
    fused_low = _rep(
        embedding=_normalize(np.array([1.0, 0.0])),
        embedding_model=same_model,
        quality_score=0.01,
        landmark_quality=0.01,
        det_score=0.01,
    )
    probe = SimpleNamespace(id=probe_id, tenant_id=tenant_id, representatives=[fused_low])
    repo = _FakeRosterRepo(
        probe=probe,
        probe_embeddings=[_normalize(np.array([1.0, 0.0]))],
        probe_model=same_model,
        labeled=[
            (
                SimpleNamespace(id=labeled_id, label="Ada", tenant_id=tenant_id),
                [_rep(embedding=_normalize(np.array([1.0, 0.0])), embedding_model=same_model)],
            )
        ],
        probe_qualities=[(0.95, 0.95, 0.99)],
    )

    result = await list_roster_candidates(
        tenant_id,
        probe_id,
        cluster_repository=repo,
        settings=ClusteringSettings(fatal_quality_floor=0.20),
        top_k=10,
    )

    assert result.quality_flag is QualityFlag.OK


@pytest.mark.asyncio
async def test_member_fallback_quality_fail_closed_when_metrics_missing() -> None:
    """R1-01: member-fallback path must not unconditionally OK."""
    tenant_id = str(uuid4())
    probe_id = str(uuid4())
    same_model = "opencv-sface+cv5@128d/l2/cosine"
    labeled_id = str(uuid4())
    repo = _FakeRosterRepo(
        probe=SimpleNamespace(id=probe_id, tenant_id=tenant_id),
        probe_embeddings=[],
        probe_model=None,
        labeled=[
            (
                SimpleNamespace(id=labeled_id, label="Ada", tenant_id=tenant_id),
                [_rep(embedding=_normalize(np.array([1.0, 0.0])), embedding_model=same_model)],
            )
        ],
        probe_qualities=[],
        member_fallback=(
            [_normalize(np.array([1.0, 0.0]))],
            same_model,
            [(None, None, None)],
        ),
    )

    result = await list_roster_candidates(
        tenant_id, probe_id, cluster_repository=repo, settings=ClusteringSettings(), top_k=10
    )

    assert result.candidates
    assert result.quality_flag is QualityFlag.LOW_QUALITY
    assert result.probe_face_count == 1


@pytest.mark.asyncio
async def test_member_fallback_prefers_quality_loader() -> None:
    """R2-04: quality loader must be used; with_model is independent and empty."""
    tenant_id = str(uuid4())
    probe_id = str(uuid4())
    same_model = "opencv-sface+cv5@128d/l2/cosine"
    labeled_id = str(uuid4())
    repo = _FakeRosterRepo(
        probe=SimpleNamespace(id=probe_id, tenant_id=tenant_id),
        probe_embeddings=[],
        probe_model=None,
        labeled=[
            (
                SimpleNamespace(id=labeled_id, label="Ada", tenant_id=tenant_id),
                [_rep(embedding=_normalize(np.array([1.0, 0.0])), embedding_model=same_model)],
            )
        ],
        probe_qualities=[],
        member_fallback=(
            [_normalize(np.array([1.0, 0.0]))],
            same_model,
            [(0.95, 0.95, 0.99)],
        ),
    )

    result = await list_roster_candidates(
        tenant_id,
        probe_id,
        cluster_repository=repo,
        settings=ClusteringSettings(fatal_quality_floor=0.20, fatal_confidence_floor=0.30),
        top_k=10,
    )

    assert result.candidates
    assert result.quality_flag is QualityFlag.OK
    assert result.probe_face_count == 1


@pytest.mark.asyncio
async def test_low_quality_caps_band_at_possible() -> None:
    """R1-09: quality_flag != ok must not emit band=strong."""
    tenant_id = str(uuid4())
    probe_id = str(uuid4())
    same_model = "opencv-sface+cv5@128d/l2/cosine"
    labeled_id = str(uuid4())
    repo = _FakeRosterRepo(
        probe=SimpleNamespace(id=probe_id, tenant_id=tenant_id),
        probe_embeddings=[_normalize(np.array([1.0, 0.0]))],
        probe_model=same_model,
        labeled=[
            (
                SimpleNamespace(id=labeled_id, label="Ada", tenant_id=tenant_id),
                [_rep(embedding=_normalize(np.array([1.0, 0.0])), embedding_model=same_model)],
            )
        ],
        probe_qualities=[(0.05, 0.05, 0.99)],
    )

    result = await list_roster_candidates(
        tenant_id,
        probe_id,
        cluster_repository=repo,
        settings=ClusteringSettings(suggestion_floor=0.35, suggestion_ceiling=0.55, fatal_quality_floor=0.20),
        top_k=10,
    )

    assert result.quality_flag is QualityFlag.LOW_QUALITY
    assert result.candidates[0].similarity >= 0.55
    assert result.candidates[0].band is SimilarityBand.POSSIBLE


@pytest.mark.asyncio
async def test_negative_similarity_returned_as_none_band() -> None:
    """R1-10: min_similarity=-1.0 so negative-cosine labelled clusters are none, not dropped."""
    tenant_id = str(uuid4())
    probe_id = str(uuid4())
    same_model = "opencv-sface+cv5@128d/l2/cosine"
    opposite_id = str(uuid4())
    repo = _FakeRosterRepo(
        probe=SimpleNamespace(id=probe_id, tenant_id=tenant_id),
        probe_embeddings=[_normalize(np.array([1.0, 0.0]))],
        probe_model=same_model,
        labeled=[
            (
                SimpleNamespace(id=opposite_id, label="Opposite", tenant_id=tenant_id),
                [_rep(embedding=_normalize(np.array([-1.0, 0.0])), embedding_model=same_model)],
            )
        ],
        probe_qualities=[(1.0, 1.0, 0.99)],
    )

    result = await list_roster_candidates(
        tenant_id,
        probe_id,
        cluster_repository=repo,
        settings=ClusteringSettings(suggestion_floor=0.35, suggestion_ceiling=0.55),
        top_k=10,
    )

    assert len(result.candidates) == 1
    assert result.candidates[0].cluster_id == opposite_id
    assert result.candidates[0].similarity < 0
    assert result.candidates[0].band is SimilarityBand.NONE


@pytest.mark.asyncio
async def test_tiebreak_is_cluster_id() -> None:
    """R1-10: equal similarity sorts by cluster_id ascending."""
    tenant_id = str(uuid4())
    probe_id = str(uuid4())
    same_model = "opencv-sface+cv5@128d/l2/cosine"
    later_id = "ffffffff-ffff-ffff-ffff-ffffffffffff"
    earlier_id = "00000000-0000-0000-0000-000000000001"
    same_vec = _normalize(np.array([1.0, 0.0]))
    repo = _FakeRosterRepo(
        probe=SimpleNamespace(id=probe_id, tenant_id=tenant_id),
        probe_embeddings=[same_vec],
        probe_model=same_model,
        labeled=[
            (
                SimpleNamespace(id=later_id, label="Zed", tenant_id=tenant_id),
                [_rep(embedding=same_vec, embedding_model=same_model)],
            ),
            (
                SimpleNamespace(id=earlier_id, label="Ann", tenant_id=tenant_id),
                [_rep(embedding=same_vec, embedding_model=same_model)],
            ),
        ],
        probe_qualities=[(1.0, 1.0, 0.99)],
    )

    result = await list_roster_candidates(
        tenant_id, probe_id, cluster_repository=repo, settings=ClusteringSettings(), top_k=10
    )

    assert [row.cluster_id for row in result.candidates] == [earlier_id, later_id]


@pytest.mark.asyncio
async def test_dimension_mismatched_reps_are_skipped() -> None:
    """R1-10: dim-mismatched labelled reps must not raise; cluster with no compatible reps dropped."""
    tenant_id = str(uuid4())
    probe_id = str(uuid4())
    same_model = "opencv-sface+cv5@128d/l2/cosine"
    mismatch_id = str(uuid4())
    ok_id = str(uuid4())
    repo = _FakeRosterRepo(
        probe=SimpleNamespace(id=probe_id, tenant_id=tenant_id),
        probe_embeddings=[_normalize(np.array([1.0, 0.0, 0.0]))],
        probe_model=same_model,
        labeled=[
            (
                SimpleNamespace(id=mismatch_id, label="Wide", tenant_id=tenant_id),
                [_rep(embedding=_normalize(np.ones(8)), embedding_model=same_model)],
            ),
            (
                SimpleNamespace(id=ok_id, label="Fit", tenant_id=tenant_id),
                [_rep(embedding=_normalize(np.array([0.8, 0.2, 0.0])), embedding_model=same_model)],
            ),
        ],
        probe_qualities=[(1.0, 1.0, 0.99)],
    )

    result = await list_roster_candidates(
        tenant_id, probe_id, cluster_repository=repo, settings=ClusteringSettings(), top_k=10
    )

    ids = [row.cluster_id for row in result.candidates]
    assert ok_id in ids
    assert mismatch_id not in ids


@pytest.mark.asyncio
async def test_probe_face_count_equals_dim_filtered_length() -> None:
    """R2-06: mixed-dim probe count is the filtered length used for ranking."""
    tenant_id = str(uuid4())
    probe_id = str(uuid4())
    same_model = "opencv-sface+cv5@128d/l2/cosine"
    labeled_id = str(uuid4())
    repo = _FakeRosterRepo(
        probe=SimpleNamespace(id=probe_id, tenant_id=tenant_id),
        probe_embeddings=[
            _normalize(np.array([1.0, 0.0, 0.0])),
            _normalize(np.ones(8)),
            _normalize(np.array([0.0, 1.0, 0.0])),
        ],
        probe_model=same_model,
        labeled=[
            (
                SimpleNamespace(id=labeled_id, label="Ada", tenant_id=tenant_id),
                [_rep(embedding=_normalize(np.array([1.0, 0.0, 0.0])), embedding_model=same_model)],
            )
        ],
        probe_qualities=[(1.0, 1.0, 0.99), (1.0, 1.0, 0.99), (1.0, 1.0, 0.99)],
    )

    result = await list_roster_candidates(
        tenant_id, probe_id, cluster_repository=repo, settings=ClusteringSettings(), top_k=10
    )

    assert result.probe_face_count == 2
    assert result.candidates


def test_php_python_window_matches_python_cap() -> None:
    php = (
        Path(__file__).resolve().parents[5]
        / "apps"
        / "prototype-wp-alt-context"
        / "src"
        / "api"
        / "class-suggestions-controller.php"
    ).read_text(encoding="utf-8")
    m = re.search(r"ROSTER_CANDIDATES_PYTHON_WINDOW\s*=\s*(\d+)\s*;", php)
    assert m is not None, "PHP window constant not found"
    assert int(m.group(1)) == MAX_ROSTER_CANDIDATES_TOP_K


def test_quality_flag_from_empty_samples_fails_closed() -> None:
    settings = ClusteringSettings(fatal_quality_floor=0.20, fatal_confidence_floor=0.30)
    assert _quality_flag_from_samples([], settings) is QualityFlag.LOW_QUALITY
