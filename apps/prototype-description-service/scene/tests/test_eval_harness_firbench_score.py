"""S3 scoring known answers: outcomes, curves, calibration, intervals, MDE and verdicts.

Synthetic fixtures only. S1 (``firbench_frames``) and S2 (``firbench_legs``) are not in this
checkout, so records and units are local fakes that carry the README and face-search-record-v1
field names. Mated faces have ``unit_id`` None and a ``identity_id``; non-mated GT faces and
background detections carry ``unit_id``; duplicate detections over a mated face have neither.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from scripts.eval_harness import firbench_contract as fc
from scripts.eval_harness import firbench_score as fs
from scripts.eval_harness.open_set_identification import SearchResult, fnir_fpi_at_threshold

SHA = "a" * 64
COMMITTED = Path(__file__).resolve().parents[4] / "benchmarks" / "manifests" / "fir-bench-decision-v1.json"
TAU = 0.5
TOL = 1e-12


@dataclass(frozen=True)
class Rec:
    """Fake of one face-search-record-v1 row (synthetic ids only)."""

    face_id: str
    image_id: str = "image-0001"
    psu_id: str = "psu-0001"
    identity_id: str | None = None
    identity_status: fc.IdentityStatus = fc.IdentityStatus.named
    fold: int = 0
    fold_role: fc.FoldRole = fc.FoldRole.test
    unit_id: str | None = None
    sampling_arm: fc.SamplingArm = fc.SamplingArm.challenge
    inclusion_probability: float | None = None
    cohort: dict[str, str | None] | None = None
    leg_key: str = "sface__native__fp__cv4__ort1"
    arm: fc.Arm = fc.Arm.native
    arm_availability: fc.ArmStatus = fc.ArmStatus.available
    stage_reached: fc.SearchStage | None = fc.SearchStage.embedded
    top_k: tuple[tuple[str, float], ...] = ()
    cell: tuple[str, str] = ("none", "none")


@dataclass(frozen=True)
class Unit:
    """Fake of the S1 non-mated source unit (one per background image or non-mated GT face)."""

    unit_id: str
    psu_id: str
    fold: int = 0
    cohort: dict[str, str | None] | None = None
    sampling_arm: fc.SamplingArm = fc.SamplingArm.challenge
    inclusion_probability: float | None = None


def mated(face: str, identity: str, top: tuple[tuple[str, float], ...], **kw: Any) -> Rec:
    return Rec(face_id=face, identity_id=identity, **{"top_k": top, **kw})


def nonmated_face(face: str, top: tuple[tuple[str, float], ...], **kw: Any) -> Rec:
    kw.setdefault("identity_status", fc.IdentityStatus.named)
    return Rec(face_id=face, unit_id=face, **{"top_k": top, **kw})


def background(image: str, index: int, top: tuple[tuple[str, float], ...], **kw: Any) -> Rec:
    return Rec(face_id=f"det:{image}:{index}", image_id=image, unit_id=f"background:{image}", **{"top_k": top, **kw})


def duplicate(face: str, image: str, top: tuple[tuple[str, float], ...], **kw: Any) -> Rec:
    return Rec(face_id=f"det:{image}:dup", image_id=image, **{"top_k": top, **kw})


def _unit_for(rec: Rec) -> Unit:
    return Unit(unit_id=rec.unit_id or "", psu_id=rec.psu_id, fold=rec.fold)


def _committed() -> fc.DecisionManifest:
    return fc.load_decision_manifest(COMMITTED)


def _sealed(frame_id: str = "confirm-v1", *, ratified: bool = True, seal_it: bool = True) -> fc.DecisionManifest:
    base = _committed()
    frames = tuple(dataclasses.replace(f, source_sha256=SHA, exhaustive=True) for f in base.frames)
    manifest = dataclasses.replace(
        base,
        frames=frames,
        gallery_lineage=fc.GalleryLineage(split_seed=base.gallery_lineage.split_seed, templates_sha256=SHA),
        ratification=fc.Ratification(decision_ref="ref-1", ratified_at="2026-10-01T00:00:00Z")
        if ratified
        else base.ratification,
    )
    return fc.seal(manifest, sealed_at="2026-10-02T00:00:00Z") if seal_it else manifest


# --- outcomes ---------------------------------------------------------------------------


def test_mated_outcomes_follow_identity_and_threshold() -> None:
    records = [
        mated("f1", "id-0001", (("id-0001", 0.9),)),
        mated("f2", "id-0001", (("id-0002", 0.9),)),
        mated("f3", "id-0001", (("id-0001", 0.2),)),
        mated("f4", "id-0001", ()),
        mated("f5", "id-0001", (("id-0001", 0.9),), stage_reached=fc.SearchStage.missed, top_k=()),
        mated("f6", "id-0001", (("id-0001", 0.9),), stage_reached=fc.SearchStage.unaligned, top_k=()),
    ]
    got = fs.finish_outcomes(records, TAU, fc.BoundarySemantics.v2)
    assert got == (
        fc.FaceOutcome.correct,
        fc.FaceOutcome.wrong_identity,
        fc.FaceOutcome.rejected,
        fc.FaceOutcome.rejected,
        fc.FaceOutcome.missed,
        fc.FaceOutcome.unaligned,
    )


def test_fused_detected_stage_finishes_as_missed() -> None:
    fused = mated("f1", "id-0001", (), stage_reached=fc.SearchStage.detected)
    got = fs.finish_outcomes([fused], TAU, fc.BoundarySemantics.v2)
    assert got == (fc.FaceOutcome.missed,)


def test_unavailable_arm_is_excluded_and_counted_per_arm() -> None:
    records = [
        mated("f1", "id-0001", (("id-0001", 0.9),), arm=fc.Arm.gt_crop_redetect),
        mated(
            "f2",
            "id-0001",
            (),
            arm=fc.Arm.gt_crop_redetect,
            arm_availability=fc.ArmStatus.unavailable,
            stage_reached=fc.SearchStage.unavailable,
        ),
        mated(
            "f3",
            "id-0001",
            (),
            arm=fc.Arm.cached_yunet_landmark_replay,
            arm_availability=fc.ArmStatus.unavailable_fused,
            stage_reached=None,
        ),
    ]
    assert fs.finish_outcomes(records, TAU, fc.BoundarySemantics.v2) == (fc.FaceOutcome.correct,)
    excluded = fs.excluded_by_arm(records)
    assert excluded == {
        (fc.Arm.gt_crop_redetect, fc.ArmStatus.unavailable): 1,
        (fc.Arm.cached_yunet_landmark_replay, fc.ArmStatus.unavailable_fused): 1,
    }


def test_boundary_flips_nonmated_score_equal_to_tau_only() -> None:
    nonmated = nonmated_face("u1", (("id-0009", TAU),))
    mated_equal = mated("f1", "id-0001", (("id-0001", TAU),))
    assert fs.finish_outcomes([nonmated], TAU, fc.BoundarySemantics.legacy_v1) == (fc.FaceOutcome.correct_reject,)
    assert fs.finish_outcomes([nonmated], TAU, fc.BoundarySemantics.v2) == (fc.FaceOutcome.false_accept,)
    assert fs.finish_outcomes([mated_equal], TAU, fc.BoundarySemantics.legacy_v1) == (fc.FaceOutcome.correct,)
    assert fs.finish_outcomes([mated_equal], TAU, fc.BoundarySemantics.v2) == (fc.FaceOutcome.correct,)


# --- curves and counts ------------------------------------------------------------------


def _analytic_records() -> tuple[list[Rec], list[Unit]]:
    """10 mated faces: 7 correct, 1 wrong identity, 1 rejected, 1 undetected at tau 0.5 (3 misses)."""
    records: list[Rec] = []
    for i in range(7):
        records.append(mated(f"m{i}", f"id-{i:04d}", ((f"id-{i:04d}", 0.9),)))
    records.append(mated("m7", "id-0007", (("id-0100", 0.8),)))
    records.append(mated("m8", "id-0008", (("id-0008", 0.2),)))
    records.append(mated("m9", "id-0009", (), stage_reached=fc.SearchStage.missed, top_k=()))
    scores = [0.9, 0.6, 0.55, 0.5, 0.45] + [0.1] * 15
    units: list[Unit] = []
    for i, score in enumerate(scores):
        face = f"u{i:02d}"
        records.append(nonmated_face(face, (("id-9999", score),), psu_id=f"psu-n{i:02d}", fold=0))
        units.append(Unit(unit_id=face, psu_id=f"psu-n{i:02d}", fold=0))
    return records, units


def test_analytic_counts_and_rates_match_hand_counts() -> None:
    records, units = _analytic_records()
    assert len(units) == 20
    (point,) = fs.curve(records, units=units, thresholds=[TAU], boundary=fc.BoundarySemantics.legacy_v1)
    assert point.n_mated == 10
    assert point.fnir_misses == 3
    assert point.fpi == 3  # 0.9, 0.6 and 0.55 are strictly above 0.5; the 0.5 tie is not
    assert point.n_units == 20
    assert abs(point.fnir - float(Fraction(3, 10))) <= TOL
    assert abs(point.fpir - float(Fraction(3, 20))) <= TOL
    assert isinstance(point.fpi, int) and isinstance(point.n_units, int)


def test_v2_boundary_adds_the_tied_unit_to_fpi() -> None:
    records, units = _analytic_records()
    (point,) = fs.curve(records, units=units, thresholds=[TAU], boundary=fc.BoundarySemantics.v2)
    assert point.fpi == 4
    assert point.n_units == 20


def test_face_level_curve_equals_fnir_fpi_at_threshold_on_single_face_fixtures() -> None:
    cases = [
        (mated("m", "id-0001", (("id-0001", 0.7),)), SearchResult(True, 0.7, "id-0001", "id-0001", "g", 1)),
        (mated("m", "id-0001", (("id-0002", 0.7),)), SearchResult(True, 0.7, "id-0002", "id-0001", "g", 1)),
        (mated("m", "id-0001", (("id-0001", 0.3),)), SearchResult(True, 0.3, "id-0001", "id-0001", "g", 1)),
    ]
    for threshold in (0.25, 0.5, 0.7, 0.8):
        for rec, search in cases:
            unit = Unit(unit_id="u", psu_id="p")
            non = nonmated_face("u", (("id-9999", 0.6),))
            point = fs.curve([rec, non], units=[unit], thresholds=[threshold], boundary=fc.BoundarySemantics.legacy_v1)[
                0
            ]
            ref = fnir_fpi_at_threshold(mated=[search], nonmated=[], tau=threshold)
            assert abs(point.fnir - ref.fnir) <= TOL
            assert point.fnir_misses == ref.n_fnir_misses


def test_no_face_image_spurious_name_raises_fpi_by_one_and_not_units() -> None:
    """The no-face image's background unit is fixed in the pool before the run (one per frame image)."""
    records, units = _analytic_records()
    background_unit = Unit(unit_id="background:image-0500", psu_id="psu-bg", fold=0)
    pool = units + [background_unit]
    before = fs.curve(records, units=pool, thresholds=[TAU], boundary=fc.BoundarySemantics.legacy_v1)[0]
    extra = background("image-0500", 0, (("id-9999", 0.95),), psu_id="psu-bg", fold=0)
    after = fs.curve(records + [extra], units=pool, thresholds=[TAU], boundary=fc.BoundarySemantics.legacy_v1)[0]
    assert after.fpi == before.fpi + 1
    assert after.n_units == before.n_units == 21


def test_duplicate_detection_over_mated_face_adds_spurious_name_not_fpi() -> None:
    records = [
        mated("m1", "id-0001", (("id-0001", 0.9),)),
        duplicate("m1", "image-0001", (("id-0001", 0.9), ("id-0002", 0.8))),
    ]
    unit = Unit(unit_id="u0", psu_id="p0")
    point = fs.curve(records, units=[unit], thresholds=[TAU], boundary=fc.BoundarySemantics.legacy_v1)[0]
    assert point.fpi == 0
    assert point.spurious_names == 2


def test_extra_above_threshold_names_in_one_unit_are_spurious_not_fpi() -> None:
    records = [background("image-0001", 0, (("id-0001", 0.9), ("id-0002", 0.8), ("id-0003", 0.1)))]
    unit = Unit(unit_id="background:image-0001", psu_id="p0")
    point = fs.curve(records, units=[unit], thresholds=[TAU], boundary=fc.BoundarySemantics.legacy_v1)[0]
    assert point.fpi == 1
    assert point.spurious_names == 1


def test_detector_alarm_cannot_add_a_unit() -> None:
    stray = background("image-0777", 0, (("id-0001", 0.9),))
    with pytest.raises(fc.FrameContractError):
        fs.curve(
            [stray],
            units=[Unit(unit_id="background:image-0001", psu_id="p0")],
            thresholds=[TAU],
            boundary=fc.BoundarySemantics.v2,
        )


# --- calibration -------------------------------------------------------------------------


def _calibration_units(scores: list[float], *, fold: int = 0) -> tuple[list[Rec], list[Unit]]:
    records: list[Rec] = []
    units: list[Unit] = []
    for i, score in enumerate(scores):
        face = f"c{fold}-{i:02d}"
        records.append(nonmated_face(face, (("id-0001", score),), psu_id=f"psu-c{i:02d}", fold=fold))
        units.append(Unit(unit_id=face, psu_id=f"psu-c{i:02d}", fold=fold))
    # every top-k identity needs a known fold: a calibration-fold mate defines id-0001
    records.append(mated(f"mate-{fold}", "id-0001", (("id-0001", 0.99),), fold=fold, psu_id="psu-mate"))
    return records, units


TEN = [0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.05]


def test_legacy_tau_is_the_m_plus_first_largest_score() -> None:
    records, units = _calibration_units(TEN)
    tau = fs.calibrate_tau(
        records, units=units, calibration_folds=frozenset({0}), fpir_target=0.2, boundary=fc.BoundarySemantics.legacy_v1
    )
    assert tau == 0.7  # m = 2, third largest; FPI(>0.7) = 2 <= m and FPI(>0.6) = 3 > m


def test_v2_tau_is_midpoint_between_the_cut_and_the_next_score() -> None:
    records, units = _calibration_units(TEN)
    tau = fs.calibrate_tau(
        records, units=units, calibration_folds=frozenset({0}), fpir_target=0.2, boundary=fc.BoundarySemantics.v2
    )
    assert tau == pytest.approx((0.7 + 0.8) / 2, abs=TOL)


def test_ties_at_the_cut_keep_v2_feasible() -> None:
    records, units = _calibration_units([0.9, 0.7, 0.7, 0.7, 0.5])
    legacy = fs.calibrate_tau(
        records, units=units, calibration_folds=frozenset({0}), fpir_target=0.2, boundary=fc.BoundarySemantics.legacy_v1
    )
    v2 = fs.calibrate_tau(
        records, units=units, calibration_folds=frozenset({0}), fpir_target=0.2, boundary=fc.BoundarySemantics.v2
    )
    assert legacy == 0.7
    assert v2 == pytest.approx((0.7 + 0.9) / 2, abs=TOL)
    records, units = _calibration_units([0.7] * 5)
    tie_top = fs.calibrate_tau(
        records, units=units, calibration_folds=frozenset({0}), fpir_target=0.2, boundary=fc.BoundarySemantics.v2
    )
    assert tie_top > 0.7 and np.isfinite(tie_top)


def test_empty_calibration_pool_is_infeasible() -> None:
    with pytest.raises(fc.TauInfeasibleError):
        fs.calibrate_tau(
            [], units=[], calibration_folds=frozenset({0}), fpir_target=0.01, boundary=fc.BoundarySemantics.v2
        )


def test_test_fold_unit_is_a_calibration_leak() -> None:
    records, units = _calibration_units(TEN)
    units.append(Unit(unit_id="c9-test", psu_id="psu-t", fold=4))
    with pytest.raises(fc.CalibrationLeakError):
        fs.calibrate_tau(
            records, units=units, calibration_folds=frozenset({0}), fpir_target=0.2, boundary=fc.BoundarySemantics.v2
        )


def test_test_fold_probe_is_a_calibration_leak() -> None:
    records, units = _calibration_units(TEN)
    records.append(nonmated_face("c-test-probe", (("id-0001", 0.95),), fold=4, psu_id="psu-t"))
    with pytest.raises(fc.CalibrationLeakError):
        fs.calibrate_tau(
            records, units=units, calibration_folds=frozenset({0}), fpir_target=0.2, boundary=fc.BoundarySemantics.v2
        )


def test_calibration_probe_whose_top_k_holds_a_test_fold_identity_leaks() -> None:
    records, units = _calibration_units(TEN)
    records.append(mated("test-mate", "id-9000", (("id-9000", 0.99),), fold=4, psu_id="psu-t"))
    records.append(nonmated_face("c0-leaky", (("id-9000", 0.6),), fold=0, psu_id="psu-c99"))
    units.append(Unit(unit_id="c0-leaky", psu_id="psu-c99", fold=0))
    with pytest.raises(fc.CalibrationLeakError):
        fs.calibrate_tau(
            records, units=units, calibration_folds=frozenset({0}), fpir_target=0.2, boundary=fc.BoundarySemantics.v2
        )


# --- resolvability and FPIR bounds ------------------------------------------------------


@pytest.mark.parametrize(
    ("target", "n_eff", "expected"),
    [(0.01, 207, False), (0.001, 207, False), (0.01, 300, True), (0.001, 3000, True), (0.01, 299.9, False)],
)
def test_fpir_resolvability_threshold(target: float, n_eff: float, expected: bool) -> None:
    assert fs.fpir_resolvable(target, n_eff) is expected


def test_zero_event_bound_is_rule_of_three_labelled_approximate() -> None:
    bound = fs.fpir_upper_bound(fpi=0, n_units=500, n_nonmated_eff=207.0, planning_psu_ids=None, n_boot=10, seed=1)
    assert bound.method == "rule_of_three"
    assert bound.approximate is True
    assert bound.upper == pytest.approx(3 / 207.0, abs=TOL)


def test_iid_clopper_pearson_zero_events_matches_closed_form() -> None:
    upper = fs.clopper_pearson_upper(0, 300)
    assert upper == pytest.approx(1 - 0.05 ** (1 / 300), abs=1e-9)


# --- paired cluster bootstrap --------------------------------------------------------------


def _outcomes(miss: list[bool]) -> list[fc.FaceOutcome]:
    return [fc.FaceOutcome.missed if m else fc.FaceOutcome.correct for m in miss]


def test_identical_outcomes_give_degenerate_zero_interval_and_null_icc() -> None:
    miss = [i % 3 == 0 for i in range(60)]
    psus = [f"p{i // 3}" for i in range(60)]
    res = fs.paired_cluster_bootstrap(_outcomes(miss), _outcomes(miss), psus, n_boot=200, seed=7, level=0.95)
    assert res.delta == 0.0
    assert res.lower == 0.0 and res.upper == 0.0
    assert res.icc is None
    assert res.n_psu == 20


def test_psu_interval_is_wider_than_image_level_interval_for_clustered_outcomes() -> None:
    n_psu, size = 30, 4
    psus = [f"p{i // size}" for i in range(n_psu * size)]
    a = [(i // size) % 2 == 0 for i in range(n_psu * size)]  # whole-PSU misses
    b = [(i // size) % 3 == 0 for i in range(n_psu * size)]
    images = [f"img{i}" for i in range(n_psu * size)]
    clustered = fs.paired_cluster_bootstrap(_outcomes(a), _outcomes(b), psus, n_boot=2000, seed=11, level=0.95)
    iid = fs.paired_cluster_bootstrap(_outcomes(a), _outcomes(b), images, n_boot=2000, seed=11, level=0.95)
    assert (clustered.upper - clustered.lower) > (iid.upper - iid.lower)
    assert clustered.icc is not None


def test_bootstrap_seed_is_reproducible_and_changes_percentiles() -> None:
    miss_a = [(i * 37) % 11 < 4 for i in range(200)]
    miss_b = [(i * 53) % 7 < 2 for i in range(200)]
    psus = [f"p{i // 2}" for i in range(200)]
    one = fs.paired_cluster_bootstrap(
        _outcomes(miss_a), _outcomes(miss_b), psus, n_boot=2000, seed=2429382368, level=0.9
    )
    two = fs.paired_cluster_bootstrap(
        _outcomes(miss_a), _outcomes(miss_b), psus, n_boot=2000, seed=2429382368, level=0.9
    )
    other = fs.paired_cluster_bootstrap(_outcomes(miss_a), _outcomes(miss_b), psus, n_boot=2000, seed=1, level=0.9)
    assert (one.lower, one.upper) == (two.lower, two.upper)
    assert (one.lower, one.upper) != (other.lower, other.upper)


# --- minimum detectable effect ------------------------------------------------------------


def test_mde_at_300_searches_exceeds_the_margin_for_h2() -> None:
    mde = fs.minimum_detectable_effect(n_eff=300.0, p_d=0.15, power=0.80, one_sided_alpha=0.05)
    assert mde is not None and mde > 0.05
    assert fs.minimum_detectable_effect(n_eff=368.9, p_d=0.15, power=0.80, one_sided_alpha=0.05) == pytest.approx(
        0.05, abs=1e-3
    )


def test_mde_follows_manifest_power_and_discordance_inputs() -> None:
    base = fs.minimum_detectable_effect(n_eff=400.0, p_d=0.15, power=0.80, one_sided_alpha=0.025)
    more_power = fs.minimum_detectable_effect(n_eff=400.0, p_d=0.15, power=0.90, one_sided_alpha=0.025)
    more_discord = fs.minimum_detectable_effect(n_eff=400.0, p_d=0.20, power=0.80, one_sided_alpha=0.025)
    assert more_power > base
    assert more_discord != base


def test_mde_is_none_when_unreachable() -> None:
    assert fs.minimum_detectable_effect(n_eff=1.0, p_d=0.15, power=0.80, one_sided_alpha=0.025) is None


# --- verdict -------------------------------------------------------------------------------


def _mated_pairs(n_faces: int = 40, size: int = 2, n_units_psus: int = 3000) -> dict[str, Any]:
    psus = [f"mp{i // size:03d}" for i in range(n_faces)]
    return {
        "faces": [f"mf{i:03d}" for i in range(n_faces)],
        "psus": psus,
        "unit_psus": [f"up{i:04d}" for i in range(n_units_psus)],
    }


def _all_veto_pass() -> dict[str, fs.GuardrailReading]:
    return {
        g.id: fs.GuardrailReading(state=fs.GuardrailState.pass_, value=0.0)
        for g in _sealed().guardrails
        if g.role is fc.GuardrailRole.veto
    }


def _results(
    frame_id: str,
    *,
    sface_miss: list[bool],
    auraface_miss: list[bool],
    insight_miss: list[bool] | None = None,
    h2_leg: fc.LegKind = fc.LegKind.auraface,
    guardrails: dict[str, fs.GuardrailReading] | None = None,
    n_units_psus: int = 3000,
    legs: tuple[fc.LegKind, ...] | None = None,
) -> fs.LegResults:
    pairs = _mated_pairs(n_faces=len(sface_miss), n_units_psus=n_units_psus)
    insight = insight_miss if insight_miss is not None else [False] * len(sface_miss)
    arrays = {
        fc.LegKind.sface: fs.LegArrays(
            fc.LegKind.sface,
            tuple(pairs["faces"]),
            tuple(_outcomes(sface_miss)),
            tuple(pairs["psus"]),
            tuple([1.0] * len(sface_miss)),
        ),
        fc.LegKind.auraface: fs.LegArrays(
            fc.LegKind.auraface,
            tuple(pairs["faces"]),
            tuple(_outcomes(auraface_miss)),
            tuple(pairs["psus"]),
            tuple([1.0] * len(sface_miss)),
        ),
        fc.LegKind.insightface: fs.LegArrays(
            fc.LegKind.insightface,
            tuple(pairs["faces"]),
            tuple(_outcomes(insight)),
            tuple(pairs["psus"]),
            tuple([1.0] * len(sface_miss)),
        ),
    }
    if legs is not None:
        arrays = {k: v for k, v in arrays.items() if k in legs}
    return fs.LegResults(
        frame=_sealed().frame(frame_id),
        legs=arrays,
        unit_psu_ids=tuple(pairs["unit_psus"]),
        h2_leg=h2_leg,
        guardrails=_all_veto_pass() if guardrails is None else guardrails,
    )


def _varied(n: int, miss_rate_a: float, miss_rate_b: float) -> tuple[list[bool], list[bool]]:
    a = [(i * 7) % 100 < miss_rate_a * 100 for i in range(n)]
    b = [(i * 13) % 100 < miss_rate_b * 100 for i in range(n)]
    return a, b


def test_unratified_manifest_returns_numbers_without_a_winner() -> None:
    # A sealed frame under an unsealed manifest is refused earlier (SealedFrameReadError), so use a development frame.
    manifest = _sealed(ratified=False, seal_it=False)
    sface, aura = _varied(40, 0.1, 0.3)
    results = _results("fir-occ-v1-prob", sface_miss=sface, auraface_miss=aura)
    verdict = fs.decide(manifest, results)
    assert verdict.state is fc.VerdictState.unratified
    assert all(h.interval is None for h in verdict.hypotheses)


def test_decide_never_calls_holm_bonferroni(monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.bench.score_report as score_report

    def boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("decide must not call holm_bonferroni")

    monkeypatch.setattr(score_report, "holm_bonferroni", boom)
    manifest = _sealed()
    sface, aura = _varied(40, 0.1, 0.3)
    fs.decide(manifest, _results("confirm-v1", sface_miss=sface, auraface_miss=aura))


def test_forty_nine_independent_psus_are_insufficient_before_any_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("no interval may be read before the PSU floor")

    monkeypatch.setattr(fs, "paired_cluster_bootstrap", boom)
    manifest = _sealed()
    sface, aura = _varied(40, 0.1, 0.3)
    # 20 mated PSUs (40 faces, 2 per PSU) plus 29 unit PSUs = 49 distinct PSUs
    results = _results("confirm-v1", sface_miss=sface, auraface_miss=aura, n_units_psus=29)
    verdict = fs.decide(manifest, results)
    assert {h.reason for h in verdict.hypotheses} == {fc.InconclusiveReason.insufficient_independent_psus}
    assert verdict.state is fc.VerdictState.inconclusive


def test_primary_fpir_unresolvable_names_no_winner() -> None:
    manifest = _sealed()
    sface, aura = _varied(40, 0.0, 0.3)
    results = _results("confirm-v1", sface_miss=sface, auraface_miss=aura, n_units_psus=207)
    verdict = fs.decide(manifest, results)
    assert verdict.state is fc.VerdictState.inconclusive
    assert verdict.reason is fc.InconclusiveReason.primary_fpir_unresolvable
    assert all(h.reason is fc.InconclusiveReason.primary_fpir_unresolvable for h in verdict.hypotheses)


def test_null_veto_guardrail_gives_required_guardrail_unscored() -> None:
    manifest = _sealed()
    sface, aura = _varied(40, 0.1, 0.3)
    readings = {
        g.id: fs.GuardrailReading(state=fs.GuardrailState.unscored, value=None)
        for g in manifest.guardrails
        if g.role is fc.GuardrailRole.veto
    }
    verdict = fs.decide(manifest, _results("confirm-v1", sface_miss=sface, auraface_miss=aura, guardrails=readings))
    assert verdict.reason is fc.InconclusiveReason.required_guardrail_unscored


def test_failing_veto_guardrail_gives_guardrail_vetoed_for_h1() -> None:
    manifest = _sealed()
    sface, aura = _varied(40, 0.1, 0.3)
    readings = {
        g.id: fs.GuardrailReading(state=fs.GuardrailState.pass_, value=0.0)
        for g in manifest.guardrails
        if g.role is fc.GuardrailRole.veto
    }
    first = next(iter(readings))
    readings[first] = fs.GuardrailReading(state=fs.GuardrailState.fail, value=1.0)
    verdict = fs.decide(manifest, _results("confirm-v1", sface_miss=sface, auraface_miss=aura, guardrails=readings))
    assert verdict.hypotheses[0].state is fc.VerdictState.guardrail_vetoed


def test_step_one_uses_the_95_percent_level_and_step_two_the_90_percent(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[float] = []

    def fake(
        a: Any, b: Any, psus: Any, *, n_boot: int, seed: int, level: float, weights: Any = None
    ) -> fs.PairedInterval:
        seen.append(level)
        return fs.PairedInterval(
            delta=0.1,
            lower=-0.01 if level > 0.92 else 0.02,
            upper=0.2,
            n_psu=20,
            icc=None,
            level=level,
            n_boot=n_boot,
            seed=seed,
        )

    monkeypatch.setattr(fs, "paired_cluster_bootstrap", fake)
    manifest = _sealed()
    sface, aura = _varied(40, 0.1, 0.3)
    verdict = fs.decide(manifest, _results("confirm-v1", sface_miss=sface, auraface_miss=aura))
    assert seen[0] == pytest.approx(0.95)
    assert verdict.hypotheses[0].state is not fc.VerdictState.superior  # 95% lower bound <= 0


def test_h2_is_reached_only_after_h1_rejects(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake(
        a: Any, b: Any, psus: Any, *, n_boot: int, seed: int, level: float, weights: Any = None
    ) -> fs.PairedInterval:
        calls.append(f"{level:.2f}")
        return fs.PairedInterval(
            delta=0.0, lower=-0.01, upper=0.01, n_psu=20, icc=None, level=level, n_boot=n_boot, seed=seed
        )

    monkeypatch.setattr(fs, "paired_cluster_bootstrap", fake)
    manifest = _sealed()
    sface, aura = _varied(40, 0.1, 0.3)
    verdict = fs.decide(manifest, _results("confirm-v1", sface_miss=sface, auraface_miss=aura))
    assert len(calls) == 1
    assert verdict.hypotheses[1].state is None


def test_h2_non_inferior_only_on_confirmatory_frame(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(
        a: Any, b: Any, psus: Any, *, n_boot: int, seed: int, level: float, weights: Any = None
    ) -> fs.PairedInterval:
        if level > 0.92:
            return fs.PairedInterval(
                delta=0.1, lower=0.02, upper=0.2, n_psu=20, icc=None, level=level, n_boot=n_boot, seed=seed
            )
        return fs.PairedInterval(
            delta=0.0, lower=-0.01, upper=0.01, n_psu=20, icc=None, level=level, n_boot=n_boot, seed=seed
        )

    monkeypatch.setattr(fs, "paired_cluster_bootstrap", fake)
    manifest = _sealed()
    sface, aura = _varied(600, 0.1, 0.3)  # 300 PSUs of 2: n_eff ~ 545, so MDE at H2 is below delta
    mde_ok_results = _results("confirm-v1", sface_miss=sface, auraface_miss=aura)
    confirm = fs.decide(manifest, mde_ok_results)
    assert confirm.state is fc.VerdictState.non_inferior
    assert confirm.hypotheses[1].state is fc.VerdictState.non_inferior
    dev = fs.decide(manifest, _results("fir-occ-v1-prob", sface_miss=sface, auraface_miss=aura))
    assert dev.hypotheses[1].state is fc.VerdictState.inconclusive
    assert dev.hypotheses[1].reason is fc.InconclusiveReason.non_confirmatory_frame


def test_h2_margin_unreachable_overrides_a_rejecting_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(
        a: Any, b: Any, psus: Any, *, n_boot: int, seed: int, level: float, weights: Any = None
    ) -> fs.PairedInterval:
        if level > 0.92:
            return fs.PairedInterval(
                delta=0.1, lower=0.02, upper=0.2, n_psu=20, icc=None, level=level, n_boot=n_boot, seed=seed
            )
        return fs.PairedInterval(
            delta=0.0, lower=-0.01, upper=0.01, n_psu=20, icc=None, level=level, n_boot=n_boot, seed=seed
        )

    monkeypatch.setattr(fs, "paired_cluster_bootstrap", fake)
    manifest = _sealed()
    sface, aura = _varied(40, 0.1, 0.3)
    verdict = fs.decide(manifest, _results("confirm-v1", sface_miss=sface, auraface_miss=aura))
    h2 = verdict.hypotheses[1]
    assert h2.reason is fc.InconclusiveReason.margin_unreachable_mde_gt_delta
    assert h2.state is fc.VerdictState.inconclusive


def test_undeclared_h2_leg_raises() -> None:
    manifest = _sealed()
    sface, aura = _varied(40, 0.1, 0.3)
    with pytest.raises(fc.UndeclaredH2LegError):
        fs.decide(manifest, _results("confirm-v1", sface_miss=sface, auraface_miss=aura, h2_leg=fc.LegKind.sface))
    with pytest.raises(fc.UndeclaredH2LegError):
        fs.decide(
            manifest,
            _results("confirm-v1", sface_miss=sface, auraface_miss=aura, legs=(fc.LegKind.sface, fc.LegKind.auraface)),
        )


def test_verdict_levels_and_mde_are_recorded_per_step() -> None:
    manifest = _sealed()
    sface, aura = _varied(40, 0.1, 0.3)
    verdict = fs.decide(manifest, _results("confirm-v1", sface_miss=sface, auraface_miss=aura))
    assert [h.one_sided_alpha for h in verdict.hypotheses] == pytest.approx([0.025, 0.05])
    assert verdict.hypotheses[0].interval is not None
    assert verdict.hypotheses[0].interval.level == pytest.approx(0.95)
    assert all(h.mde is None or h.mde > 0 for h in verdict.hypotheses)


def test_committed_manifest_power_inputs_are_read_not_defaulted() -> None:
    manifest = _committed()
    assert manifest.p_d == 0.15 and manifest.power == 0.80
    assert manifest.min_n_independent == 50 and manifest.cell_floor_n_independent == 30
    assert manifest.interval.n_boot == 10000 and manifest.interval.seed == 2429382368
    assert fs.step_levels(manifest) == pytest.approx((0.95, 0.90))


def test_end_to_end_fake_pipeline_records_to_verdict() -> None:
    """Fake-only chain: records -> outcomes -> curve -> frozen tau on fit folds -> decision (no real frames)."""
    records, units = _analytic_records()
    outcomes = fs.finish_outcomes(records, TAU, fc.BoundarySemantics.legacy_v1)
    assert len(outcomes) == 30  # 10 mated faces plus 20 non-mated source units
    (point,) = fs.curve(records, units=units, thresholds=[TAU], boundary=fc.BoundarySemantics.legacy_v1)
    assert (point.fpi, point.n_units) == (3, 20)
    cal_records, cal_units = _calibration_units(TEN)
    tau = fs.calibrate_tau(
        cal_records,
        units=cal_units,
        calibration_folds=frozenset({0}),
        fpir_target=0.2,
        boundary=fc.BoundarySemantics.legacy_v1,
    )
    assert tau == 0.7
    sface, aura = _varied(600, 0.1, 0.3)
    verdict = fs.decide(_sealed(), _results("confirm-v1", sface_miss=sface, auraface_miss=aura))
    # SFace has the lower FNIR here, so H1 (SFace minus AuraFace > 0) is not rejected.
    assert verdict.state is fc.VerdictState.inconclusive
    assert verdict.hypotheses[0].interval is not None
    assert verdict.hypotheses[0].interval.delta < 0
