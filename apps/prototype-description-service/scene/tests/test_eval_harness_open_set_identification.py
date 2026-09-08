"""Open-set IET (FNIR vs FPI) — EVAL-16/18/19.

TEST-15: the anti-gaming case is proven to go red on a rate-over-n_nonmated scorer.
"""

from __future__ import annotations

import pytest

from scripts.eval_harness.accept_predicate import accepts, is_fnir_miss, is_fpi
from scripts.eval_harness.calibrate_face_thresholds import fmr_at, fnmr_at, select_threshold
from scripts.eval_harness.gallery_split import GalleryName
from scripts.eval_harness.open_set_identification import (
    IETPoint,
    SearchResult,
    fnir_fpi_at_threshold,
    iet_curve,
)

_G = GalleryName.G1
_MID = 1


def _hit(name: str, score: float) -> SearchResult:
    return SearchResult(
        detected=True,
        top1_score=score,
        top1_name=name,
        true_name=name,
        gallery=_G,
        media_id=_MID,
    )


def _miss_wrong_name(*, true_name: str, predicted: str, score: float) -> SearchResult:
    return SearchResult(
        detected=True,
        top1_score=score,
        top1_name=predicted,
        true_name=true_name,
        gallery=_G,
        media_id=_MID,
    )


def _undetected_mated(name: str) -> SearchResult:
    return SearchResult(
        detected=False,
        top1_score=None,
        top1_name=None,
        true_name=name,
        gallery=_G,
        media_id=_MID,
    )


def _nonmated_hit(predicted: str, score: float) -> SearchResult:
    return SearchResult(
        detected=True,
        top1_score=score,
        top1_name=predicted,
        true_name=None,
        gallery=_G,
        media_id=_MID,
    )


def _nonmated_undetected() -> SearchResult:
    return SearchResult(
        detected=False,
        top1_score=None,
        top1_name=None,
        true_name=None,
        gallery=_G,
        media_id=_MID,
    )


def _gamed_fpir(point: IETPoint) -> float:
    """EVAL-19-forbidden rate: FPI / n_nonmated. Test-only; not a module API."""
    return point.fpi / point.n_nonmated


def test_anti_gaming_fpi_does_not_fall_when_false_detections_flood():
    """Looser detector mints extra non-mated searches; count-FPI must not improve.

    Extra spurious detections that fail the score cut grow n_nonmated without
    adding FPI. A rate over that volume falls (the EVAL-19 attack). Integer FPI
    does not decrease. The assertion is live: swapping the gate to the rate
    would fail the ``not-decrease`` check after the rate drop is observed.
    """
    mated = [
        _hit("Alice", 0.90),
        _hit("Bob", 0.80),
    ]
    baseline_nonmated = [
        _nonmated_hit("Alice", 0.85),
        _nonmated_hit("Bob", 0.70),
        _nonmated_hit("Alice", 0.20),
        _nonmated_undetected(),
    ]
    tau = 0.50
    n_enrolled = 10
    baseline = fnir_fpi_at_threshold(
        mated=mated,
        nonmated=baseline_nonmated,
        tau=tau,
        n_enrolled_gallery_subjects=n_enrolled,
    )
    assert baseline.fpi == 2
    assert baseline.n_nonmated == 4
    baseline_rate = _gamed_fpir(baseline)
    assert baseline_rate == pytest.approx(0.5)

    flood = baseline_nonmated + [
        _nonmated_hit("Alice", 0.10),
        _nonmated_hit("Bob", 0.05),
        _nonmated_hit("Alice", 0.00),
        _nonmated_undetected(),
        _nonmated_undetected(),
        _nonmated_undetected(),
    ]
    flooded = fnir_fpi_at_threshold(
        mated=mated,
        nonmated=flood,
        tau=tau,
        n_enrolled_gallery_subjects=n_enrolled,
    )
    assert flooded.fpi >= baseline.fpi
    assert flooded.fpi == 2
    flooded_rate = _gamed_fpir(flooded)
    assert flooded_rate < baseline_rate
    assert flooded_rate == pytest.approx(0.2)
    # External-denominator normalization is unchanged (gallery size is fixed).
    assert baseline.fpi_per_enrolled_subject == pytest.approx(2 / 10)
    assert flooded.fpi_per_enrolled_subject == pytest.approx(2 / 10)


def test_undetected_mated_probe_counts_as_fnir_miss():
    mated_detected_only = [_hit("Alice", 0.90)]
    mated_with_miss = [_hit("Alice", 0.90), _undetected_mated("Bob")]
    nonmated: list[SearchResult] = []
    tau = 0.50
    detected_only = fnir_fpi_at_threshold(
        mated=mated_detected_only, nonmated=nonmated, tau=tau
    )
    with_miss = fnir_fpi_at_threshold(
        mated=mated_with_miss, nonmated=nonmated, tau=tau
    )
    assert detected_only.fnir == pytest.approx(0.0)
    assert with_miss.fnir == pytest.approx(0.5)
    assert with_miss.n_fnir_misses == 1
    assert with_miss.fnir > detected_only.fnir


def test_detected_false_with_mate_score_is_fnir_miss():
    """EVAL-16: detection miss counts even when a mate score is present.

    The None-score fallback must not be the only path that marks this a miss;
    otherwise deleting ``if not search.detected`` still passes.
    """
    mated = [
        SearchResult(
            detected=False,
            top1_score=0.99,
            top1_name="Bob",
            true_name="Bob",
            gallery=_G,
            media_id=_MID,
        )
    ]
    point = fnir_fpi_at_threshold(mated=mated, nonmated=(), tau=0.50)
    assert point.measured is True
    assert point.n_fnir_misses == 1
    assert point.fnir == pytest.approx(1.0)


def test_nonmated_with_true_name_raises():
    mated = [_hit("Alice", 0.90)]
    misfiled = SearchResult(
        detected=True,
        top1_score=0.90,
        top1_name="Alice",
        true_name="Alice",
        gallery=_G,
        media_id=_MID,
    )
    with pytest.raises(ValueError, match="true_name is None"):
        fnir_fpi_at_threshold(mated=mated, nonmated=[misfiled], tau=0.50)
    misfiled_undetected = SearchResult(
        detected=False,
        top1_score=None,
        top1_name=None,
        true_name="Bob",
        gallery=_G,
        media_id=_MID,
    )
    with pytest.raises(ValueError, match="true_name is None"):
        fnir_fpi_at_threshold(mated=mated, nonmated=[misfiled_undetected], tau=0.50)


def test_fnir_fpi_monotone_in_tau():
    mated = [
        _hit("Alice", 0.80),
        _hit("Bob", 0.40),
        _undetected_mated("Carol"),
    ]
    nonmated = [
        _nonmated_hit("Alice", 0.75),
        _nonmated_hit("Bob", 0.45),
        _nonmated_hit("Alice", 0.15),
        _nonmated_undetected(),
    ]
    thresholds = (0.10, 0.30, 0.50, 0.70, 0.90)
    curve = iet_curve(mated=mated, nonmated=nonmated, thresholds=thresholds)
    fnirs = [p.fnir for p in curve]
    fpis = [p.fpi for p in curve]
    assert fnirs == sorted(fnirs)
    assert fpis == sorted(fpis, reverse=True)
    assert fnirs == [pytest.approx(v) for v in (1 / 3, 1 / 3, 2 / 3, 2 / 3, 1.0)]
    assert fpis == [3, 2, 1, 1, 0]
    assert fnirs[0] < fnirs[-1]
    assert fpis[0] > fpis[-1]


def test_empty_mated_is_unmeasured_not_perfect():
    """MLDATA-09: n_mated==0 is a declared-empty cell, never FNIR 0.0."""
    stranger = _nonmated_hit("Alice", 0.80)
    empty_mated = fnir_fpi_at_threshold(mated=(), nonmated=[stranger], tau=0.50)
    assert empty_mated.measured is False
    assert empty_mated.fnir is None
    assert empty_mated.n_fnir_misses == 0
    assert empty_mated.n_mated == 0
    assert empty_mated.fpi == 1
    assert empty_mated.format_fnir() == "not measured"
    hit = _hit("Alice", 0.90)
    empty_nonmated = fnir_fpi_at_threshold(mated=[hit], nonmated=(), tau=0.50)
    assert empty_nonmated.measured is True
    assert empty_nonmated.fnir == pytest.approx(0.0)
    assert empty_nonmated.fpi == 0
    assert empty_nonmated.format_fnir() == "0.000"
    both_empty = fnir_fpi_at_threshold(mated=(), nonmated=(), tau=0.50)
    assert both_empty.measured is False
    assert both_empty.fnir is None
    assert both_empty.fpi == 0
    assert both_empty.format_fnir() == "not measured"
    both_empty_enrolled = fnir_fpi_at_threshold(
        mated=(),
        nonmated=(),
        tau=0.50,
        n_enrolled_gallery_subjects=0,
    )
    assert both_empty_enrolled.measured is False
    assert both_empty_enrolled.fnir is None
    assert both_empty_enrolled.fpi_per_enrolled_subject is None


def test_unmeasured_iet_point_rejects_numeric_fnir():
    with pytest.raises(ValueError, match="must not carry an FNIR number"):
        IETPoint(
            tau=0.50,
            fnir=0.0,
            fpi=1,
            n_mated=0,
            n_fnir_misses=0,
            n_nonmated=1,
            measured=False,
        )
    with pytest.raises(ValueError, match="requires fnir"):
        IETPoint(
            tau=0.50,
            fnir=None,
            fpi=0,
            n_mated=1,
            n_fnir_misses=0,
            n_nonmated=0,
            measured=True,
        )
    with pytest.raises(ValueError, match="n_mated == 0"):
        IETPoint(
            tau=0.50,
            fnir=None,
            fpi=0,
            n_mated=1,
            n_fnir_misses=0,
            n_nonmated=0,
            measured=False,
        )


def test_fpi_uses_strict_gt_fnir_uses_at_or_above():
    """JANUS §2.3.4 inequality split: FPI is score > t; FNIR hit is score >= t."""
    tau = 0.50
    mated_eq = [_hit("Alice", tau)]
    nonmated_eq = [_nonmated_hit("Alice", tau)]
    point = fnir_fpi_at_threshold(mated=mated_eq, nonmated=nonmated_eq, tau=tau)
    assert point.fnir == pytest.approx(0.0)
    assert point.fpi == 0
    nonmated_above = [_nonmated_hit("Alice", tau + 1e-9)]
    above = fnir_fpi_at_threshold(mated=mated_eq, nonmated=nonmated_above, tau=tau)
    assert above.fpi == 1


def test_wrong_name_mated_search_is_fnir_miss():
    mated = [_miss_wrong_name(true_name="Alice", predicted="Bob", score=0.99)]
    point = fnir_fpi_at_threshold(mated=mated, nonmated=(), tau=0.10)
    assert point.fnir == pytest.approx(1.0)
    assert point.n_fnir_misses == 1


def test_iet_curve_preserves_threshold_order():
    thresholds = (0.90, 0.10, 0.50)
    curve = iet_curve(mated=[_hit("Alice", 0.40)], nonmated=(), thresholds=thresholds)
    assert [p.tau for p in curve] == [0.90, 0.10, 0.50]
    assert iet_curve(mated=(), nonmated=(), thresholds=()) == []


def test_non_finite_tau_is_not_a_clean_measurement():
    """EVAL-18: NaN/inf tau must not score as a measured IET point.

    Direct scorer callers (and iet_curve) used to skip the bakeoff score_run
    finite-tau gate. IEEE then makes every NaN comparison false, so tau=nan
    reports fnir=0.0 / measured=True — a perfect system that was never scored.
    """
    mated = [_hit("Alice", 0.90)]
    for tau in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError, match="tau"):
            fnir_fpi_at_threshold(mated=mated, nonmated=(), tau=tau)
        with pytest.raises(ValueError, match="tau"):
            iet_curve(mated=mated, nonmated=(), thresholds=(tau,))


def test_non_finite_detected_score_is_not_a_hit():
    """EVAL-16/18: a NaN top-1 score on a detected search is not a mate hit.

    `top1_score < tau` is False for NaN, so a matching name with score=nan
    used to report fnir=0.0. Inf would silently pass every threshold.
    """
    nan_mated = [
        SearchResult(
            detected=True,
            top1_score=float("nan"),
            top1_name="A",
            true_name="A",
            gallery=_G,
            media_id=_MID,
        )
    ]
    inf_mated = [
        SearchResult(
            detected=True,
            top1_score=float("inf"),
            top1_name="A",
            true_name="A",
            gallery=_G,
            media_id=_MID,
        )
    ]
    nan_foil = [
        SearchResult(
            detected=True,
            top1_score=float("nan"),
            top1_name="A",
            true_name=None,
            gallery=_G,
            media_id=_MID,
        )
    ]
    with pytest.raises(ValueError, match="top1_score"):
        fnir_fpi_at_threshold(mated=nan_mated, nonmated=(), tau=0.50)
    with pytest.raises(ValueError, match="top1_score"):
        fnir_fpi_at_threshold(mated=inf_mated, nonmated=(), tau=0.50)
    with pytest.raises(ValueError, match="top1_score"):
        fnir_fpi_at_threshold(mated=[_hit("Alice", 0.90)], nonmated=nan_foil, tau=0.50)


def test_search_result_requires_gallery_and_media_id():
    """BR-18: a 1:N search is a (probe image, gallery) pair, structurally."""
    with pytest.raises(TypeError):
        SearchResult(
            detected=True, top1_score=0.90, top1_name="Alice", true_name="Alice"
        )
    with pytest.raises(ValueError, match="media_id"):
        SearchResult(
            detected=True,
            top1_score=0.90,
            top1_name="Alice",
            true_name="Alice",
            gallery=GalleryName.G1,
            media_id=True,  # type: ignore[arg-type]
        )


def test_calibrated_tau_agrees_with_published_fpi_and_fnir_off_observation():
    """FIR-12-BR-63: calibration FMR/FNMR at tau equals published FPI/FNIR.

    JANUS 2.3.4: FPI is rank-1 score > t; FNIR miss is a mate strictly below t.
    Those two rules break ties in opposite directions, so no single predicate
    expresses both, and any tau landing exactly on an observed score makes the
    published rule and the operational apply rule (``accepts``, >=) disagree on
    that score. ``select_threshold`` therefore draws candidates from midpoints
    and open boundaries around consecutive unique observations: the tie is
    unreachable by construction for every finite fit observation, and agreement
    is a property of the operating point rather than a tie convention chosen
    after the fact. Held-fold observations remain an independent read
    population.
    """
    impostor_scores = [0.6, 0.55, 0.4]
    genuine_scores = [0.9, 0.55, 0.4]
    fmr_target = 1.0 / 3.0
    tau = select_threshold(genuine_scores, impostor_scores, fmr_target=fmr_target)
    assert tau is not None

    observed = set(impostor_scores) | set(genuine_scores)
    assert tau not in observed
    for score in observed:
        assert is_fpi(score, tau) == accepts(score, tau)
        assert is_fnir_miss(score, tau) != accepts(score, tau)

    cal_fmr = fmr_at(impostor_scores, tau)
    cal_fnmr = fnmr_at(genuine_scores, tau)
    assert cal_fmr is not None and cal_fnmr is not None
    assert cal_fmr <= fmr_target + 1e-12

    point = fnir_fpi_at_threshold(
        mated=[_hit("Alice", s) for s in genuine_scores],
        nonmated=[_nonmated_hit("Alice", s) for s in impostor_scores],
        tau=tau,
    )
    assert cal_fmr * len(impostor_scores) == pytest.approx(point.fpi)
    assert cal_fnmr == pytest.approx(point.fnir)


def test_same_probe_different_gallery_are_distinct_searches():
    """JANUS 2.2: mated-ness is per (probe, gallery), not per still."""
    shared = dict(
        detected=True,
        top1_score=0.90,
        top1_name="Alice",
        true_name="Alice",
        media_id=93,
    )
    against_g1 = SearchResult(gallery=GalleryName.G1, **shared)
    against_g2 = SearchResult(gallery=GalleryName.G2, **shared)
    assert against_g1 != against_g2
    assert against_g1.media_id == against_g2.media_id
    assert against_g1.gallery != against_g2.gallery
