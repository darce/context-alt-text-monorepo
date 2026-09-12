"""RED tests for the FIR-13 T-14 union-adjudication contract."""

from __future__ import annotations

import copy
import math
from typing import Any

import pytest

_THRESHOLDS = {"buffalo": 0.82, "candidate": 0.77}
_EXHAUSTIVE_IMAGE_IDS = frozenset(f"image-{number}" for number in range(1, 32))


@pytest.fixture
def synthetic_images() -> tuple[dict[str, Any], ...]:
    """Five image rows with common pre-run declarations and varied gaps."""
    return (
        {
            "image_id": "image-1",
            "union_boxes": 90,
            "human_true_faces": 100,
            "tp_buffalo_i": 80,
            "tp_candidate_i": 76,
            "matched_fppi_declared": 0.20,
            "thresholds_declared_before_run": dict(_THRESHOLDS),
        },
        {
            "image_id": "image-2",
            "union_boxes": 180,
            "human_true_faces": 200,
            "tp_buffalo_i": 160,
            "tp_candidate_i": 148,
            "matched_fppi_declared": 0.20,
            "thresholds_declared_before_run": dict(_THRESHOLDS),
        },
        {
            "image_id": "image-3",
            "union_boxes": 270,
            "human_true_faces": 300,
            "tp_buffalo_i": 240,
            "tp_candidate_i": 210,
            "matched_fppi_declared": 0.20,
            "thresholds_declared_before_run": dict(_THRESHOLDS),
        },
        {
            "image_id": "image-4",
            "union_boxes": 360,
            "human_true_faces": 400,
            "tp_buffalo_i": 320,
            "tp_candidate_i": 280,
            "matched_fppi_declared": 0.20,
            "thresholds_declared_before_run": dict(_THRESHOLDS),
        },
        {
            "image_id": "image-5",
            "union_boxes": 450,
            "human_true_faces": 500,
            "tp_buffalo_i": 400,
            "tp_candidate_i": 325,
            "matched_fppi_declared": 0.20,
            "thresholds_declared_before_run": dict(_THRESHOLDS),
        },
    )


def _threshold_sha256(thresholds: dict[str, float]) -> str:
    from scripts.eval_harness.gate_contract import threshold_sha256

    return threshold_sha256(thresholds)


def _declared_kwargs(thresholds: dict[str, float]) -> dict[str, object]:
    return {
        "metric": "FNIR@FPIR",
        "max_fpi": None,
        "n_nonmated_declared": None,
        "rubric_version": "face-label-rule/v1",
        "ratified_by_decision_id": None,
        "t14_thresholds_declared": thresholds,
        "t14_thresholds_sha256": _threshold_sha256(thresholds),
    }


def _payloads_with_gap(
    synthetic_images: tuple[dict[str, Any], ...], gap_per_100_faces: int
) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            **payload,
            "tp_candidate_i": payload["tp_buffalo_i"] - payload["human_true_faces"] // 100 * gap_per_100_faces,
        }
        for payload in synthetic_images
    )


def _payload_with_gap(
    image_id: str,
    gap_per_100_faces: int,
    *,
    union_boxes: int = 100,
) -> dict[str, Any]:
    return {
        "image_id": image_id,
        "union_boxes": union_boxes,
        "human_true_faces": 100,
        "tp_buffalo_i": 80,
        "tp_candidate_i": 80 - gap_per_100_faces,
        "matched_fppi_declared": 0.20,
        "thresholds_declared_before_run": dict(_THRESHOLDS),
    }


def test_check_conditions_kill_below_005() -> None:
    from scripts.eval_harness import gate_contract, union_adjudication

    thresholds = dict(_THRESHOLDS)
    rows = tuple(
        union_adjudication.UnionAdjudicationInput(**_payload_with_gap(f"image-{number}", 0)) for number in range(30)
    )
    exhaustive_image_ids = frozenset(row.image_id for row in rows)
    declared = gate_contract.GateContract(
        **_declared_kwargs(thresholds),
        t14_exhaustive_subset_count=len(exhaustive_image_ids),
        t14_exhaustive_subset_sha256=gate_contract.exhaustive_subset_sha256(exhaustive_image_ids),
    )
    conditions_met = dict.fromkeys(union_adjudication._REQUIRED_CONDITION_KEYS, True)

    verdict = union_adjudication.check_conditions(
        rows,
        declared=declared,
        signed_decision_id="firplan_t14_run_20260912",
        conditions_met=conditions_met,
        exhaustive_image_ids=exhaustive_image_ids,
        b=2000,
        seed=17,
    )

    assert verdict is union_adjudication.DeadZoneVerdict.KILL


def test_check_conditions_miss_inflation_can_lift_would_be_kill() -> None:
    from scripts.eval_harness import gate_contract, union_adjudication

    thresholds = dict(_THRESHOLDS)
    rows = tuple(
        union_adjudication.UnionAdjudicationInput(**_payload_with_gap(f"image-{number}", 4, union_boxes=92))
        for number in range(30)
    )
    exhaustive_image_ids = frozenset(row.image_id for row in rows)
    factor, flag = union_adjudication.miss_inflate(
        rows,
        exhaustive_image_ids=exhaustive_image_ids,
    )
    ucl = union_adjudication.bootstrap_ucl(rows, b=2000, seed=17)
    assert factor > 1.0
    assert flag == 0.0
    assert ucl * factor >= 0.05
    declared = gate_contract.GateContract(
        **_declared_kwargs(thresholds),
        t14_exhaustive_subset_count=len(exhaustive_image_ids),
        t14_exhaustive_subset_sha256=gate_contract.exhaustive_subset_sha256(exhaustive_image_ids),
    )
    conditions_met = dict.fromkeys(union_adjudication._REQUIRED_CONDITION_KEYS, True)

    verdict = union_adjudication.check_conditions(
        rows,
        declared=declared,
        signed_decision_id="firplan_t14_run_20260912",
        conditions_met=conditions_met,
        exhaustive_image_ids=exhaustive_image_ids,
        b=2000,
        seed=17,
    )

    assert verdict is not union_adjudication.DeadZoneVerdict.KILL


def test_check_conditions_refuses_kill_without_exhaustive_image_ids(
    synthetic_images: tuple[dict[str, Any], ...],
) -> None:
    from scripts.eval_harness import gate_contract, union_adjudication

    thresholds = dict(_THRESHOLDS)
    rows = tuple(
        union_adjudication.UnionAdjudicationInput(**payload) for payload in _payloads_with_gap(synthetic_images, 4)
    )
    declared = gate_contract.GateContract(
        **_declared_kwargs(thresholds),
        t14_exhaustive_subset_count=None,
        t14_exhaustive_subset_sha256=None,
    )
    conditions_met = dict.fromkeys(union_adjudication._REQUIRED_CONDITION_KEYS, True)

    with pytest.raises(union_adjudication.UnionAdjudicationError, match="exhaustive_image_ids"):
        union_adjudication.check_conditions(
            rows,
            declared=declared,
            signed_decision_id="firplan_t14_run_20260912",
            conditions_met=conditions_met,
            b=2000,
            seed=17,
        )


def test_check_conditions_dead_zone_between_005_and_010(
    synthetic_images: tuple[dict[str, Any], ...],
) -> None:
    from scripts.eval_harness import gate_contract, union_adjudication

    thresholds = dict(_THRESHOLDS)
    rows = tuple(
        union_adjudication.UnionAdjudicationInput(**payload) for payload in _payloads_with_gap(synthetic_images, 7)
    )
    declared = gate_contract.GateContract(
        **_declared_kwargs(thresholds),
        t14_exhaustive_subset_count=None,
        t14_exhaustive_subset_sha256=None,
    )
    conditions_met = dict.fromkeys(union_adjudication._REQUIRED_CONDITION_KEYS, True)

    verdict = union_adjudication.check_conditions(
        rows,
        declared=declared,
        signed_decision_id="firplan_t14_run_20260912",
        conditions_met=conditions_met,
        b=2000,
        seed=17,
    )

    assert verdict is union_adjudication.DeadZoneVerdict.DEAD_ZONE


def test_check_conditions_open_above_010(
    synthetic_images: tuple[dict[str, Any], ...],
) -> None:
    from scripts.eval_harness import gate_contract, union_adjudication

    thresholds = dict(_THRESHOLDS)
    rows = tuple(
        union_adjudication.UnionAdjudicationInput(**payload) for payload in _payloads_with_gap(synthetic_images, 12)
    )
    declared = gate_contract.GateContract(
        **_declared_kwargs(thresholds),
        t14_exhaustive_subset_count=None,
        t14_exhaustive_subset_sha256=None,
    )
    conditions_met = dict.fromkeys(union_adjudication._REQUIRED_CONDITION_KEYS, True)

    verdict = union_adjudication.check_conditions(
        rows,
        declared=declared,
        signed_decision_id="firplan_t14_run_20260912",
        conditions_met=conditions_met,
        b=2000,
        seed=17,
    )

    assert verdict is union_adjudication.DeadZoneVerdict.OPEN


def test_check_conditions_refuses_without_signed_decision_id(
    synthetic_images: tuple[dict[str, Any], ...],
) -> None:
    from scripts.eval_harness import gate_contract, union_adjudication

    thresholds = dict(_THRESHOLDS)
    rows = tuple(union_adjudication.UnionAdjudicationInput(**payload) for payload in synthetic_images)
    declared = gate_contract.GateContract(
        **_declared_kwargs(thresholds),
        t14_exhaustive_subset_count=None,
        t14_exhaustive_subset_sha256=None,
    )
    conditions_met = dict.fromkeys(union_adjudication._REQUIRED_CONDITION_KEYS, True)

    with pytest.raises(union_adjudication.UnionAdjudicationError):
        union_adjudication.check_conditions(
            rows,
            declared=declared,
            signed_decision_id=None,
            conditions_met=conditions_met,
            b=2000,
            seed=17,
        )


def test_check_conditions_refuses_on_threshold_hash_mismatch(
    synthetic_images: tuple[dict[str, Any], ...],
) -> None:
    from scripts.eval_harness import gate_contract, union_adjudication

    thresholds = dict(_THRESHOLDS)
    rows = tuple(union_adjudication.UnionAdjudicationInput(**payload) for payload in synthetic_images)
    declared_kwargs = _declared_kwargs(thresholds)
    declared = gate_contract.GateContract(
        **declared_kwargs,
        t14_exhaustive_subset_count=None,
        t14_exhaustive_subset_sha256=None,
    )
    rows = tuple(
        union_adjudication.UnionAdjudicationInput(
            **{**payload, "thresholds_declared_before_run": {"buffalo": 0.83, "candidate": 0.77}}
        )
        for payload in synthetic_images
    )
    conditions_met = dict.fromkeys(union_adjudication._REQUIRED_CONDITION_KEYS, True)

    with pytest.raises(union_adjudication.UnionAdjudicationError):
        union_adjudication.check_conditions(
            rows,
            declared=declared,
            signed_decision_id="firplan_t14_run_20260912",
            conditions_met=conditions_met,
            b=2000,
            seed=17,
        )


def test_check_conditions_refuses_on_missing_condition_key(
    synthetic_images: tuple[dict[str, Any], ...],
) -> None:
    from scripts.eval_harness import gate_contract, union_adjudication

    thresholds = dict(_THRESHOLDS)
    rows = tuple(union_adjudication.UnionAdjudicationInput(**payload) for payload in synthetic_images)
    declared = gate_contract.GateContract(
        **_declared_kwargs(thresholds),
        t14_exhaustive_subset_count=None,
        t14_exhaustive_subset_sha256=None,
    )
    condition_keys = tuple(union_adjudication._REQUIRED_CONDITION_KEYS)
    conditions_met = dict.fromkeys(condition_keys[:-1], True)

    with pytest.raises(union_adjudication.UnionAdjudicationError):
        union_adjudication.check_conditions(
            rows,
            declared=declared,
            signed_decision_id="firplan_t14_run_20260912",
            conditions_met=conditions_met,
            b=2000,
            seed=17,
        )


def test_check_conditions_refuses_unknown_condition_key(
    synthetic_images: tuple[dict[str, Any], ...],
) -> None:
    from scripts.eval_harness import gate_contract, union_adjudication

    thresholds = dict(_THRESHOLDS)
    rows = tuple(union_adjudication.UnionAdjudicationInput(**payload) for payload in synthetic_images)
    declared = gate_contract.GateContract(
        **_declared_kwargs(thresholds),
        t14_exhaustive_subset_count=None,
        t14_exhaustive_subset_sha256=None,
    )
    conditions_met = dict.fromkeys(union_adjudication._REQUIRED_CONDITION_KEYS, True)
    conditions_met["unratified_fifth_condition"] = True

    with pytest.raises(union_adjudication.UnionAdjudicationError, match="unrecognised"):
        union_adjudication.check_conditions(
            rows,
            declared=declared,
            signed_decision_id="firplan_t14_run_20260912",
            conditions_met=conditions_met,
            b=2000,
            seed=17,
        )


def test_bootstrap_ucl_deterministic_with_seed(
    synthetic_images: tuple[dict[str, Any], ...],
) -> None:
    from scripts.eval_harness import union_adjudication

    rows = tuple(union_adjudication.UnionAdjudicationInput(**payload) for payload in synthetic_images)

    first = union_adjudication.bootstrap_ucl(rows, b=2000, seed=23)
    second = union_adjudication.bootstrap_ucl(rows, b=2000, seed=23)
    different_seed = union_adjudication.bootstrap_ucl(rows, b=2000, seed=24)

    assert isinstance(first, float)
    assert math.isfinite(first)
    assert first > 0.0
    assert first == second
    assert different_seed != first


def test_bootstrap_ucl_rejects_duplicate_caller_image_ids(
    synthetic_images: tuple[dict[str, Any], ...],
) -> None:
    from scripts.eval_harness import union_adjudication

    rows = tuple(union_adjudication.UnionAdjudicationInput(**payload) for payload in synthetic_images)
    duplicate_rows = rows + (rows[0],)

    with pytest.raises(union_adjudication.UnionAdjudicationError, match="image-1"):
        union_adjudication.bootstrap_ucl(duplicate_rows, b=32, seed=23)


def test_bootstrap_ucl_rejects_duplicate_reproduction_that_would_cross_kill_boundary() -> None:
    from scripts.eval_harness import union_adjudication

    zero_gap_row = union_adjudication.UnionAdjudicationInput(**_payload_with_gap("image-zero", 0))
    gap_row = union_adjudication.UnionAdjudicationInput(**_payload_with_gap("image-gap", 20))
    two_image_rows = (zero_gap_row, gap_row)
    duplicate_rows = (zero_gap_row,) * 99 + (gap_row,)

    ucl = union_adjudication.bootstrap_ucl(two_image_rows, b=2000, seed=23)
    assert isinstance(ucl, float)
    assert ucl >= 0.05

    with pytest.raises(union_adjudication.UnionAdjudicationError, match="image-zero"):
        union_adjudication.bootstrap_ucl(duplicate_rows, b=2000, seed=23)


def test_bootstrap_ucl_keeps_replacement_resampling_for_unique_image_rows() -> None:
    from scripts.eval_harness import union_adjudication

    rows = tuple(
        union_adjudication.UnionAdjudicationInput(**_payload_with_gap(image_id, gap))
        for image_id, gap in (("image-zero", 0), ("image-gap", 20))
    )

    ucl = union_adjudication.bootstrap_ucl(rows, b=256, seed=23)

    assert isinstance(ucl, float)
    assert math.isfinite(ucl)
    assert ucl == pytest.approx(0.20)


def test_all_caller_adjudicators_reject_duplicate_image_ids() -> None:
    from scripts.eval_harness import union_adjudication

    row = union_adjudication.UnionAdjudicationInput(**_payload_with_gap("image-duplicate", 10))
    duplicate_rows = (row, row)

    with pytest.raises(union_adjudication.UnionAdjudicationError, match="image-duplicate"):
        union_adjudication.detector_gap_bound(duplicate_rows)
    with pytest.raises(union_adjudication.UnionAdjudicationError, match="image-duplicate"):
        union_adjudication.miss_inflate(
            duplicate_rows,
            exhaustive_image_ids=_EXHAUSTIVE_IMAGE_IDS,
        )


def test_rows_reject_union_boxes_above_human_true_faces() -> None:
    from scripts.eval_harness import union_adjudication

    row = union_adjudication.UnionAdjudicationInput(**_payload_with_gap("image-union-overflow", 0, union_boxes=101))

    with pytest.raises(union_adjudication.UnionAdjudicationError, match="union_boxes"):
        union_adjudication.detector_gap_bound((row,))


def test_rows_reject_tp_counts_above_human_true_faces() -> None:
    from scripts.eval_harness import union_adjudication

    for field, human_true_faces, union_boxes, value in (
        ("tp_buffalo_i", 100, 100, 101),
        ("tp_candidate_i", 100, 100, 101),
        ("tp_buffalo_i", 0, 0, 1),
    ):
        payload = _payload_with_gap("image-tp-overflow", 0, union_boxes=union_boxes)
        payload["human_true_faces"] = human_true_faces
        payload[field] = value
        row = union_adjudication.UnionAdjudicationInput(**payload)

        with pytest.raises(union_adjudication.UnionAdjudicationError, match=field):
            union_adjudication.detector_gap_bound((row,))


def test_miss_inflate_refuses_under_30_exhaustive_images(
    synthetic_images: tuple[dict[str, Any], ...],
) -> None:
    from scripts.eval_harness import union_adjudication

    rows = tuple(union_adjudication.UnionAdjudicationInput(**payload) for payload in synthetic_images)

    with pytest.raises(union_adjudication.UnionAdjudicationError):
        union_adjudication.miss_inflate(
            rows,
            exhaustive_image_ids=frozenset(payload["image_id"] for payload in synthetic_images),
        )


def test_miss_inflate_zero_denominator_returns_factor_one_with_flag() -> None:
    from scripts.eval_harness import union_adjudication

    rows = tuple(
        union_adjudication.UnionAdjudicationInput(**_payload_with_gap(f"image-{number}", 0)) for number in range(30)
    )

    factor, flag = union_adjudication.miss_inflate(
        rows,
        exhaustive_image_ids=frozenset(row.image_id for row in rows),
    )

    assert isinstance(factor, float)
    assert factor == 1.0
    assert flag == 1.0
    assert (factor, flag) == (1.0, 1.0)


def test_miss_inflate_rejects_factor_below_one_with_operational_details() -> None:
    from scripts.eval_harness import union_adjudication

    rows = tuple(
        union_adjudication.UnionAdjudicationInput(**_payload_with_gap(f"image-{number}", 10, union_boxes=95))
        for number in range(30)
    )
    exhaustive_image_ids = frozenset(row.image_id for row in rows)

    with pytest.raises(
        union_adjudication.UnionAdjudicationError, match=r"computed miss inflation factor 0\.5000"
    ) as exc_info:
        union_adjudication.miss_inflate(
            rows,
            exhaustive_image_ids=exhaustive_image_ids,
        )

    message = str(exc_info.value)
    assert "exhaustive miss numerator=150" in message
    assert "detector-flagged denominator=300" in message


def test_miss_inflate_rejects_below_one_ratio_that_rounds_up_to_one() -> None:
    from scripts.eval_harness import union_adjudication

    rows = tuple(
        union_adjudication.UnionAdjudicationInput(
            image_id=f"image-{number}",
            union_boxes=20_001,
            human_true_faces=40_001,
            tp_buffalo_i=20_001,
            tp_candidate_i=0,
            matched_fppi_declared=0.20,
            thresholds_declared_before_run=dict(_THRESHOLDS),
        )
        for number in range(30)
    )
    exhaustive_image_ids = frozenset(row.image_id for row in rows)

    with pytest.raises(union_adjudication.UnionAdjudicationError) as exc_info:
        union_adjudication.miss_inflate(
            rows,
            exhaustive_image_ids=exhaustive_image_ids,
        )

    message = str(exc_info.value)
    assert "exhaustive miss numerator=600000" in message
    assert "detector-flagged denominator=600030" in message


def test_miss_inflate_accepts_exactly_one_ratio() -> None:
    from scripts.eval_harness import union_adjudication

    rows = tuple(
        union_adjudication.UnionAdjudicationInput(**_payload_with_gap(f"image-{number}", 10, union_boxes=90))
        for number in range(30)
    )
    exhaustive_image_ids = frozenset(row.image_id for row in rows)

    factor, flag = union_adjudication.miss_inflate(
        rows,
        exhaustive_image_ids=exhaustive_image_ids,
    )

    assert factor == 1.0
    assert flag == 0.0


def test_miss_inflate_refuses_declared_ids_absent_from_rows() -> None:
    from scripts.eval_harness import union_adjudication

    rows = tuple(
        union_adjudication.UnionAdjudicationInput(**_payload_with_gap(f"image-{number}", 0)) for number in range(30)
    )

    with pytest.raises(union_adjudication.UnionAdjudicationError, match="absent from the input rows"):
        union_adjudication.miss_inflate(
            rows,
            exhaustive_image_ids=frozenset(f"ghost-{number}" for number in range(30)),
        )


def test_miss_inflate_refuses_when_matched_rows_below_thirty() -> None:
    from scripts.eval_harness import union_adjudication

    rows = tuple(
        union_adjudication.UnionAdjudicationInput(**_payload_with_gap(f"image-{number}", 0)) for number in range(40)
    )

    with pytest.raises(union_adjudication.UnionAdjudicationError, match="matched 20"):
        union_adjudication.miss_inflate(
            rows,
            exhaustive_image_ids=frozenset(f"image-{number}" for number in range(20)),
        )


def test_miss_inflate_computed_only_from_exhaustive_subset() -> None:
    from scripts.eval_harness import union_adjudication

    exhaustive_rows = tuple(
        union_adjudication.UnionAdjudicationInput(
            image_id=f"image-{number}",
            union_boxes=90_000,
            human_true_faces=100_000,
            tp_buffalo_i=80_000,
            tp_candidate_i=71_900,
            matched_fppi_declared=0.20,
            thresholds_declared_before_run=dict(_THRESHOLDS),
        )
        for number in range(1, 31)
    )
    excluded_row = union_adjudication.UnionAdjudicationInput(
        image_id="image-excluded",
        union_boxes=0,
        human_true_faces=100_000,
        tp_buffalo_i=80_000,
        tp_candidate_i=0,
        matched_fppi_declared=0.20,
        thresholds_declared_before_run=dict(_THRESHOLDS),
    )
    rows = exhaustive_rows + (excluded_row,)
    before = copy.deepcopy(rows)

    factor, flag = union_adjudication.miss_inflate(
        rows,
        exhaustive_image_ids=frozenset(f"image-{number}" for number in range(1, 31)),
    )

    assert isinstance(factor, float)
    assert factor >= 1.0
    assert factor == 1.2346
    assert flag == 0.0
    assert rows == before


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"b": 100}, "T-14 b is fixed at 2000"),
        ({"kill_below": 0.04}, "T-14 kill_below is fixed at 0.05"),
        ({"dead_zone_upper": 0.11}, "T-14 dead_zone_upper is fixed at 0.1"),
    ],
)
def test_check_conditions_refuses_signed_parameter_override(override, message) -> None:
    from scripts.eval_harness import gate_contract, union_adjudication

    declared = gate_contract.GateContract(
        **_declared_kwargs(_THRESHOLDS),
        t14_exhaustive_subset_count=None,
        t14_exhaustive_subset_sha256=None,
    )
    rows = (union_adjudication.UnionAdjudicationInput(**_payload_with_gap("image", 20)),)
    with pytest.raises(union_adjudication.UnionAdjudicationError, match=message):
        union_adjudication.check_conditions(
            rows,
            declared=declared,
            signed_decision_id="signed",
            conditions_met=dict.fromkeys(union_adjudication._REQUIRED_CONDITION_KEYS, True),
            seed=17,
            **override,
        )


@pytest.mark.parametrize("case", ["unratified", "count", "hash", "omitted"])
def test_check_conditions_requires_exact_signed_subset(case) -> None:
    from scripts.eval_harness import gate_contract, union_adjudication

    rows = tuple(union_adjudication.UnionAdjudicationInput(**_payload_with_gap(f"image-{i}", 0)) for i in range(30))
    ids = frozenset(row.image_id for row in rows)
    declared = gate_contract.GateContract(
        **_declared_kwargs(_THRESHOLDS),
        t14_exhaustive_subset_count=None if case == "unratified" else 31 if case == "count" else 30,
        t14_exhaustive_subset_sha256=None
        if case == "unratified"
        else gate_contract.exhaustive_subset_sha256(ids | {"extra"} if case == "hash" else ids),
    )
    messages = {
        "unratified": "subset must be ratified",
        "count": "count 30 does not match declared count 31",
        "hash": "run exhaustive-subset hash does not match",
        "omitted": "ratified exhaustive-image subset requires exhaustive_image_ids",
    }
    with pytest.raises(union_adjudication.UnionAdjudicationError, match=messages[case]):
        union_adjudication.check_conditions(
            rows,
            declared=declared,
            signed_decision_id="signed",
            conditions_met=dict.fromkeys(union_adjudication._REQUIRED_CONDITION_KEYS, True),
            exhaustive_image_ids=None if case == "omitted" else ids,
            seed=17,
        )


def test_check_conditions_matches_integer_thresholds_to_float_rows() -> None:
    from scripts.eval_harness import gate_contract, union_adjudication

    declared = gate_contract.GateContract(
        **_declared_kwargs({"buffalo": 0, "candidate": 1}),
        t14_exhaustive_subset_count=None,
        t14_exhaustive_subset_sha256=None,
    )
    rows = (
        union_adjudication.UnionAdjudicationInput(
            **{**_payload_with_gap("image", 20), "thresholds_declared_before_run": {"buffalo": 0.0, "candidate": 1.0}},
        ),
    )
    assert (
        union_adjudication.check_conditions(
            rows,
            declared=declared,
            signed_decision_id="signed",
            conditions_met=dict.fromkeys(union_adjudication._REQUIRED_CONDITION_KEYS, True),
            seed=17,
        )
        is union_adjudication.DeadZoneVerdict.OPEN
    )


@pytest.mark.parametrize("ucl", [None, 0.07, 0.12])
def test_check_conditions_degenerate_correction_with_real_misses(monkeypatch, ucl) -> None:
    from scripts.eval_harness import gate_contract, union_adjudication

    rows = tuple(
        union_adjudication.UnionAdjudicationInput(**_payload_with_gap(f"image-{i}", 0, union_boxes=80))
        for i in range(30)
    )
    ids = frozenset(row.image_id for row in rows)
    declared = gate_contract.GateContract(
        **_declared_kwargs(_THRESHOLDS),
        t14_exhaustive_subset_count=len(ids),
        t14_exhaustive_subset_sha256=gate_contract.exhaustive_subset_sha256(ids),
    )
    assert union_adjudication.miss_inflate(rows, exhaustive_image_ids=ids) == (1.0, 1.0)
    if ucl is not None:

        def fixed_ucl(*args, **kwargs):
            assert kwargs["b"] == 2000
            assert kwargs["level"] == 0.95
            return ucl

        monkeypatch.setattr(union_adjudication, "bootstrap_ucl", fixed_ucl)
    kwargs = {
        "declared": declared,
        "signed_decision_id": "signed",
        "conditions_met": dict.fromkeys(union_adjudication._REQUIRED_CONDITION_KEYS, True),
        "exhaustive_image_ids": ids,
        "seed": 17,
    }
    if ucl is None:
        with pytest.raises(
            union_adjudication.UnionAdjudicationError,
            match="unmeasurable .*zero detector-flagged denominator.*T-14 cannot return KILL",
        ):
            union_adjudication.check_conditions(rows, **kwargs)
    else:
        expected = (
            union_adjudication.DeadZoneVerdict.OPEN if ucl > 0.10 else union_adjudication.DeadZoneVerdict.DEAD_ZONE
        )
        assert union_adjudication.check_conditions(rows, **kwargs) is expected
