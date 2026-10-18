"""S3-02/03 adjudication: synthetic records with the native producer's complete shape.

Non-mated GT records, like S2 _gt_pending, clear identity_id. Gallery identity
fold provenance is independent of which mated probes happened to be emitted.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from fractions import Fraction
from itertools import product

import numpy as np
import pytest

from scripts.eval_harness import firbench_contract as fc
from scripts.eval_harness import firbench_score as fs


@dataclass(frozen=True)
class Record:
    face_id: str = "face"
    image_id: str = "image"
    psu_id: str = "psu"
    identity_id: str | None = None
    identity_status: fc.IdentityStatus = fc.IdentityStatus.unknown
    fold: int = 1
    fold_role: fc.FoldRole = fc.FoldRole.fit
    cell: tuple[str, str] = ("unknown", "unknown")
    unit_id: str | None = "face"
    sampling_arm: fc.SamplingArm = fc.SamplingArm.challenge
    inclusion_probability: float | None = None
    cohort: dict[str, str | None] | None = None
    leg_key: str = "sface__native__fp__cv4__ort1"
    arm: fc.Arm = fc.Arm.native
    arm_availability: fc.ArmStatus = fc.ArmStatus.available
    alignment_mode: fc.AlignmentMode = fc.AlignmentMode.separable
    stage_reached: fc.SearchStage | None = fc.SearchStage.embedded
    top_k: tuple[tuple[str, float], ...] = (("enrolled", 0.7),)
    gallery_sha256: str = "a" * 64
    timing_receipt_ref: str | None = "fake-receipt"


@dataclass(frozen=True)
class Unit:
    unit_id: str = "face"
    fold: int = 1
    psu_id: str = "psu"
    cohort: dict[str, str | None] | None = None


def mate(**kw: object) -> Record:
    return replace(Record(), identity_id="enrolled", identity_status=fc.IdentityStatus.named, unit_id=None, **kw)


def fixture(scores: list[float]) -> tuple[list[Record], list[Unit]]:
    rows = [replace(Record(), face_id=f"f{i}", unit_id=f"f{i}", top_k=(("enrolled", s),)) for i, s in enumerate(scores)]
    return rows, [replace(Unit(), unit_id=r.unit_id) for r in rows]


def calibrate(rows: list[Record], units: list[Unit], **kw: object) -> float:
    options = {
        "units": units,
        "calibration_folds": frozenset({1, 2, 3, 4}),
        "fpir_target": 0.2,
        "boundary": fc.BoundarySemantics.v2,
    }
    options.update(kw)
    return fs.calibrate_tau(rows, **options)


def point(rows: list[Record], units: list[Unit], **kw: object) -> fs.CurvePoint:
    options = {"units": units, "thresholds": [0.5], "boundary": fc.BoundarySemantics.v2}
    options.update(kw)
    return fs.curve(rows, **options)[0]


def test_explicit_gallery_map_needs_no_mated_probe() -> None:
    rows, units = fixture([0.9, 0.7, 0.4, 0.3, 0.2])
    tau = calibrate(rows, units, identity_folds={"enrolled": 2})
    assert 0.7 < tau <= 0.9
    got = point(rows, units, thresholds=[tau])
    assert (got.fpi, got.n_units, got.fpir) == (1, 5, float(Fraction(1, 5)))


def test_complete_mated_provenance_can_derive_default_map() -> None:
    rows, units = fixture([0.9, 0.7, 0.4, 0.3, 0.2])
    assert calibrate(rows + [mate(face_id="m")], units) == pytest.approx(0.8)


@pytest.mark.parametrize("mapping", [None, {}, {"other": 1}, {"enrolled": 0}])
def test_missing_or_test_gallery_provenance_fails_closed(mapping: dict[str, int] | None) -> None:
    with pytest.raises(fc.CalibrationLeakError):
        calibrate([Record()], [Unit()], identity_folds=mapping)


@pytest.mark.parametrize("mapping", [{"enrolled": 2}, {}, {"enrolled": 0}])
def test_explicit_map_validates_probe_identity_fold(mapping: dict[str, int]) -> None:
    with pytest.raises(fc.CalibrationLeakError):
        calibrate([Record(), mate(face_id="m")], [Unit()], identity_folds=mapping)


@pytest.mark.parametrize("mapping", [{"enrolled": True}, {"enrolled": -1}, {"enrolled": 1.5}, {"": 1}])
def test_identity_map_shape_is_validated(mapping: dict[str, int]) -> None:
    with pytest.raises(fc.FrameContractError):
        calibrate([Record()], [Unit()], identity_folds=mapping)


@pytest.mark.parametrize("change", ["unit", "probe", "gallery"])
def test_test_fold_leaks_are_rejected(change: str) -> None:
    rows, units = [Record(), mate(face_id="m")], [Unit()]
    if change == "unit":
        units = [replace(Unit(), fold=0)]
    elif change == "probe":
        rows[0] = replace(rows[0], fold=0)
    else:
        rows[0] = replace(rows[0], top_k=(("test-name", 0.9),))
    with pytest.raises(fc.CalibrationLeakError):
        calibrate(rows, units, identity_folds={"enrolled": 1, "test-name": 0})


@pytest.mark.parametrize("available", [fc.ArmStatus.available, fc.ArmStatus.unavailable])
def test_record_cannot_reference_unit_outside_pool(available: fc.ArmStatus) -> None:
    row = replace(Record(), unit_id="missing", arm_availability=available)
    with pytest.raises(fc.FrameContractError):
        calibrate([row, mate(face_id="m")], [Unit()])


def test_record_and_unit_fold_must_agree_even_inside_fit_pool() -> None:
    with pytest.raises(fc.FrameContractError):
        calibrate([Record(), mate(face_id="m")], [replace(Unit(), fold=2)])


@pytest.mark.parametrize("operation", ["curve", "calibrate"])
def test_mated_face_cannot_be_in_nonmated_pool(operation: str) -> None:
    rows, units = [mate()], [Unit()]
    with pytest.raises(fc.FrameContractError):
        (point if operation == "curve" else calibrate)(rows, units)


def test_calibration_never_mints_units_from_records() -> None:
    with pytest.raises(fc.FrameContractError):
        calibrate([Record(), mate(face_id="m")], [replace(Unit(), unit_id="different")])


@pytest.mark.parametrize("boundary", list(fc.BoundarySemantics))
def test_count_allowance_just_below_integer_has_no_floor_fudge(boundary: fc.BoundarySemantics) -> None:
    rows, units = fixture([0.9, 0.7, 0.4, 0.3, 0.2])
    target = math.nextafter(0.2, 0.0)
    tau = calibrate(rows + [mate(face_id="m")], units, fpir_target=target, boundary=boundary)
    got = point(rows, units, thresholds=[tau], boundary=boundary)
    assert got.fpi == 0 and got.fpir <= target


@pytest.mark.parametrize("cut", [0.5, -0.5, 1e308])
def test_adjacent_float_v2_cut_stays_strictly_above_rejected_score(cut: float) -> None:
    higher = math.nextafter(cut, math.inf)
    rows, units = fixture([higher, cut, cut, cut, cut])
    tau = calibrate(rows + [mate(face_id="m")], units)
    assert math.isfinite(tau) and cut < tau <= higher
    assert point(rows, units, thresholds=[tau]).fpi == 1


def test_v2_max_float_has_no_finite_rejecting_threshold() -> None:
    rows, units = fixture([float.fromhex("0x1.fffffffffffffp+1023")])
    with pytest.raises(fc.TauInfeasibleError):
        calibrate(rows + [mate(face_id="m")], units)


@pytest.mark.parametrize("target", [0.0, 1.0, -0.1, 1.1, math.nan, math.inf, True])
def test_invalid_calibration_target_is_contract_error(target: float) -> None:
    with pytest.raises(fc.FrameContractError):
        calibrate([Record(), mate(face_id="m")], [Unit()], fpir_target=target)


@pytest.mark.parametrize("folds", [frozenset(), frozenset({True}), frozenset({-1}), frozenset({1.5})])
def test_invalid_calibration_folds_fail_closed(folds: frozenset[int]) -> None:
    with pytest.raises(fc.FrameContractError):
        calibrate([Record(), mate(face_id="m")], [Unit()], calibration_folds=folds)


@pytest.mark.parametrize("target", [0.01, 0.001, 0.2])
def test_resolvability_never_accepts_float_below_exact_floor(target: float) -> None:
    floor = 3.0 / target
    assert fs.fpir_resolvable(target, floor)
    assert not fs.fpir_resolvable(target, math.nextafter(floor, 0.0))


@pytest.mark.parametrize(
    "target,n_eff",
    [
        (0, 300),
        (1, 300),
        (-0.1, 300),
        (math.nan, 300),
        (math.inf, 300),
        (True, 300),
        (0.01, math.nan),
        (0.01, math.inf),
        (0.01, -1),
        (0.01, True),
    ],
)
def test_resolvability_validates_finite_inputs(target: float, n_eff: float) -> None:
    with pytest.raises(fc.FrameContractError):
        fs.fpir_resolvable(target, n_eff)


def test_zero_effective_inventory_is_valid_but_unresolvable() -> None:
    assert not fs.fpir_resolvable(0.01, 0)


@pytest.mark.parametrize(
    "change",
    [{"leg_key": "auraface__native__fp__cv4__ort1"}, {"arm": fc.Arm.gt_crop_redetect}, {"gallery_sha256": "b" * 64}],
)
def test_curve_refuses_mixed_leg_arm_or_gallery(change: dict[str, object]) -> None:
    with pytest.raises(fc.FrameContractError):
        point([Record(), replace(Record(), **change)], [Unit()])


def test_pooled_fit_folds_may_snapshot_different_galleries() -> None:
    # Each query fold carries its own gallery snapshot; the pooled fit may mix snapshots across folds.
    rows = [
        replace(Record(), face_id="a0", unit_id="a0", fold=1, gallery_sha256="a" * 64, top_k=(("enrolled", 0.9),)),
        replace(Record(), face_id="a1", unit_id="a1", fold=1, gallery_sha256="a" * 64, top_k=(("enrolled", 0.7),)),
        replace(Record(), face_id="b0", unit_id="b0", fold=2, gallery_sha256="b" * 64, top_k=(("enrolled", 0.8),)),
        replace(Record(), face_id="b1", unit_id="b1", fold=2, gallery_sha256="b" * 64, top_k=(("enrolled", 0.2),)),
    ]
    units = [replace(Unit(), unit_id=r.unit_id, fold=r.fold) for r in rows]
    # Unit maxima are 0.9, 0.7, 0.8, 0.2; m=1 puts the cut at 0.8, and v2 sits midway to 0.9.
    tau = calibrate(rows, units, fpir_target=0.25, identity_folds={"enrolled": 1})
    assert tau == pytest.approx(0.85)
    got = point(rows, units, thresholds=[tau])
    assert (got.fpi, got.n_units) == (1, 4)


def test_one_query_fold_refuses_mixed_gallery_snapshots() -> None:
    rows = [Record(), replace(Record(), face_id="x", unit_id="x", gallery_sha256="b" * 64, top_k=(("enrolled", 0.6),))]
    units = [Unit(), replace(Unit(), unit_id="x")]
    with pytest.raises(fc.FrameContractError):
        point(rows, units)
    with pytest.raises(fc.FrameContractError):
        calibrate(rows, units, identity_folds={"enrolled": 1})


@pytest.mark.parametrize("arm", [fc.Arm.gt_crop_redetect, fc.Arm.cached_yunet_landmark_replay])
def test_attribution_rows_cannot_supply_native_fpir(arm: fc.Arm) -> None:
    with pytest.raises(fc.FrameContractError):
        point([replace(Record(), arm=arm)], [Unit()])


def test_curve_refuses_mixed_sampling_arms_even_if_one_arm_is_unavailable() -> None:
    with pytest.raises(fc.FrameContractError):
        point(
            [
                Record(),
                replace(
                    Record(),
                    sampling_arm=fc.SamplingArm.probability,
                    inclusion_probability=0.5,
                    arm_availability=fc.ArmStatus.unavailable,
                ),
            ],
            [Unit()],
        )


def test_null_cohort_gt_unit_is_not_an_image_denominator() -> None:
    rows = [replace(Record(), top_k=(("a", 0.9), ("b", 0.8)))]
    got = point(rows, [Unit(), replace(Unit(), unit_id="background:image")])
    assert got.spurious_names == 1
    assert got.spurious_per_1k_images == 1000.0
    assert point(rows, [Unit()]).spurious_per_1k_images is None


def test_fixed_pool_undetected_units_remain_in_raw_denominator() -> None:
    got = point([Record()], [Unit(), replace(Unit(), unit_id="undetected")])
    assert type(got.fpi) is int and type(got.n_units) is int
    assert (got.fpi, got.n_units, got.fpir) == (1, 2, float(Fraction(1, 2)))


@pytest.mark.parametrize("operation", ["outcome", "curve", "calibrate"])
@pytest.mark.parametrize("bad_score", [math.nan, math.inf, -math.inf])
def test_every_topk_score_must_be_finite_even_on_missed_rows(operation: str, bad_score: float) -> None:
    rows = [replace(Record(), stage_reached=fc.SearchStage.missed, top_k=(("enrolled", bad_score),))]
    with pytest.raises(fc.FrameContractError):
        if operation == "outcome":
            fs.finish_outcomes(rows, 0.5, fc.BoundarySemantics.v2)
        else:
            (point if operation == "curve" else calibrate)(rows + [mate(face_id="m")], [Unit()])


@pytest.mark.parametrize("status", [fc.IdentityStatus.unknown, fc.IdentityStatus.unresolved])
def test_mated_outcome_requires_named_identity_status(status: fc.IdentityStatus) -> None:
    with pytest.raises(fc.FrameContractError):
        fs.finish_outcomes([replace(mate(), identity_status=status)], 0.5, fc.BoundarySemantics.v2)


def test_unresolved_gt_cannot_be_nonmated() -> None:
    with pytest.raises(fc.FrameContractError):
        point([replace(Record(), identity_status=fc.IdentityStatus.unresolved)], [Unit()])


@pytest.mark.parametrize("probability", [math.nan, math.inf, 0, -0.1, 1.1, True, None, 1e-320])
def test_probability_arm_validates_all_rows_even_nonmated(probability: float | None) -> None:
    with pytest.raises(fc.FrameContractError):
        point([replace(Record(), sampling_arm=fc.SamplingArm.probability, inclusion_probability=probability)], [Unit()])


def test_weighted_probability_fnir_and_raw_fpir_have_separate_estimands() -> None:
    rows = [
        replace(mate(face_id="m1"), sampling_arm=fc.SamplingArm.probability, inclusion_probability=0.25),
        replace(mate(face_id="m2"), sampling_arm=fc.SamplingArm.probability, inclusion_probability=1.0, top_k=()),
        replace(Record(), sampling_arm=fc.SamplingArm.probability, inclusion_probability=0.1),
    ]
    got = point(rows, [Unit(), replace(Unit(), unit_id="unseen")])
    assert got.fnir == float(Fraction(1, 5))
    assert got.fpir == float(Fraction(1, 2)) and got.fpi == 1


@pytest.mark.parametrize("level", [0, 1, -0.1, math.nan, math.inf, True])
def test_clopper_pearson_validates_level_even_when_all_events(level: float) -> None:
    with pytest.raises(fc.FrameContractError):
        fs.clopper_pearson_upper(2, 2, level=level)


def bound(**kw: object) -> fs.FpirBound:
    options = {
        "fpi": 1,
        "n_units": 4,
        "n_nonmated_eff": 3.0,
        "planning_psu_ids": ["a", "b", "c", "c"],
        "unit_false_accept": [True, False, False, False],
        "n_boot": 10000,
        "seed": 2429382368,
    }
    options.update(kw)
    return fs.fpir_upper_bound(**options)


@pytest.mark.parametrize(
    "change",
    [
        {"fpi": True},
        {"fpi": 1.0},
        {"fpi": -1},
        {"fpi": 5},
        {"n_units": True},
        {"n_units": 4.0},
        {"n_units": 0},
        {"n_nonmated_eff": math.nan},
        {"n_nonmated_eff": math.inf},
        {"n_nonmated_eff": 0},
        {"n_nonmated_eff": 5},
        {"n_nonmated_eff": True},
        {"planning_psu_ids": ["a"]},
        {"planning_psu_ids": ["", "b", "c", "c"]},
        {"unit_false_accept": [True]},
        {"unit_false_accept": [1, 0, 0, 0]},
        {"unit_false_accept": [math.nan, False, False, False]},
        {"fpi": 2},
        {"n_boot": 0},
        {"n_boot": True},
        {"n_boot": 1.5},
        {"seed": True},
        {"seed": -1},
        {"seed": 1.5},
    ],
)
def test_fpir_bound_rejects_inconsistent_counts_flags_and_context(change: dict[str, object]) -> None:
    with pytest.raises(fc.FrameContractError):
        bound(**change)


@pytest.mark.parametrize(
    "change", [{"unit_false_accept": [True, False, False, False]}, {"planning_psu_ids": ["a"]}, {"n_units": 0}]
)
def test_zero_event_path_still_validates_supplied_evidence(change: dict[str, object]) -> None:
    with pytest.raises(fc.FrameContractError):
        bound(fpi=0, **change)


def test_zero_event_small_effective_n_is_vacuously_capped_and_labelled() -> None:
    got = bound(fpi=0, n_units=2, n_nonmated_eff=0.5, planning_psu_ids=None, unit_false_accept=None)
    assert got.upper == 1.0 and got.approximate and got.method == "rule_of_three"


def test_unequal_psu_bootstrap_keeps_raw_unit_ratio() -> None:
    # Three equally likely PSUs with sizes 1, 2, 5. Enumerate their resampling law:
    # the 95% upper is 1/2. Averaging PSU rates would give a different upper.
    psus = ["a", "b", "b"] + ["c"] * 5
    flags = [True] + [False] * 7
    sizes, events = [1, 2, 5], [1, 0, 0]
    oracle = [sum(events[i] for i in draw) / sum(sizes[i] for i in draw) for draw in product(range(3), repeat=3)]
    assert np.quantile(oracle, 0.95) == 0.5
    got = bound(n_units=8, n_nonmated_eff=6, planning_psu_ids=psus, unit_false_accept=flags)
    assert got.upper == 0.5 and got.approximate and got.method == "psu_percentile"


def test_probability_arm_raw_inventory_interval_coverage_context() -> None:
    # Coverage is for the declared raw inventory FPIR, separate from IPW FNIR.
    # Conditional on the sampled inventory with unequal inclusion probabilities,
    # exhaust Bernoulli(1/4) outcomes over three independent source PSUs. This
    # checks this small conditional model, not general population/IPW coverage.
    coverage = Fraction(0)
    for flags in product([False, True], repeat=3):
        n_events = sum(flags)
        probability = Fraction(1, 4) ** n_events * Fraction(3, 4) ** (3 - n_events)
        rows, units = fixture([0.9 if flag else 0.1 for flag in flags])
        rows = [
            replace(row, sampling_arm=fc.SamplingArm.probability, inclusion_probability=p, psu_id=psu)
            for row, p, psu in zip(rows, [0.1, 0.5, 1.0], ["a", "b", "c"], strict=True)
        ]
        units = [replace(unit, psu_id=row.psu_id) for unit, row in zip(units, rows, strict=True)]
        observed = point(rows, units)
        assert observed.fpi == n_events and observed.fpir == float(Fraction(n_events, 3))
        got = bound(
            fpi=observed.fpi,
            n_units=observed.n_units,
            n_nonmated_eff=3,
            planning_psu_ids=[unit.psu_id for unit in units],
            unit_false_accept=flags,
        )
        if got.upper >= 0.25:
            coverage += probability
        assert got.approximate and 0 <= got.upper <= 1
    assert coverage >= Fraction(95, 100)


@pytest.mark.parametrize("operation", ["outcome", "curve", "calibrate"])
def test_mated_identity_cannot_be_relabelled_as_a_nonmated_unit(operation: str) -> None:
    row = replace(Record(), identity_id="enrolled", identity_status=fc.IdentityStatus.named)
    with pytest.raises(fc.FrameContractError):
        if operation == "outcome":
            fs.finish_outcomes([row], 0.5, fc.BoundarySemantics.v2)
        else:
            (point if operation == "curve" else calibrate)([row], [Unit()])


def test_unreturned_test_gallery_member_is_not_a_calibration_leak() -> None:
    # The full predeclared map may name held-out identities; only probe and top-k use is gated.
    with_member = calibrate([Record()], [Unit()], identity_folds={"enrolled": 1, "unreturned-test-member": 0})
    assert with_member == calibrate([Record()], [Unit()], identity_folds={"enrolled": 1})
