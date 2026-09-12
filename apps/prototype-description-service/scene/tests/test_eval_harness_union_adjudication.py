"""RED tests for the FIR-13 T-14 union-adjudication contract."""

from __future__ import annotations

import copy
import hashlib
import json
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
    encoded = json.dumps(thresholds, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _declared_kwargs(thresholds: dict[str, float]) -> dict[str, object]:
    return {
        "metric": "FNIR@FPIR",
        "max_fpi": None,
        "n_nonmated_declared": None,
        "rubric_version": "face-label-rule/v1",
        "ratified_by_decision_id": "firplan_t14_thresholds_20260912",
        "t14_thresholds_declared": thresholds,
        "t14_thresholds_sha256": _threshold_sha256(thresholds),
    }


def _payloads_with_gap(
    synthetic_images: tuple[dict[str, Any], ...], gap_per_100_faces: int
) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            **payload,
            "tp_candidate_i": payload["tp_buffalo_i"]
            - payload["human_true_faces"] // 100 * gap_per_100_faces,
        }
        for payload in synthetic_images
    )


def test_check_conditions_kill_below_005(
    synthetic_images: tuple[dict[str, Any], ...],
) -> None:
    from scripts.eval_harness import gate_contract, union_adjudication

    thresholds = dict(_THRESHOLDS)
    rows = tuple(
        union_adjudication.UnionAdjudicationInput(**payload)
        for payload in _payloads_with_gap(synthetic_images, 4)
    )
    declared = gate_contract.GateContract(**_declared_kwargs(thresholds))
    conditions_met = dict.fromkeys(union_adjudication._REQUIRED_CONDITION_KEYS, True)

    verdict = union_adjudication.check_conditions(
        rows,
        declared=declared,
        signed_decision_id="firplan_t14_run_20260912",
        conditions_met=conditions_met,
        b=2000,
        seed=17,
    )

    assert verdict is union_adjudication.DeadZoneVerdict.KILL


def test_check_conditions_dead_zone_between_005_and_010(
    synthetic_images: tuple[dict[str, Any], ...],
) -> None:
    from scripts.eval_harness import gate_contract, union_adjudication

    thresholds = dict(_THRESHOLDS)
    rows = tuple(
        union_adjudication.UnionAdjudicationInput(**payload)
        for payload in _payloads_with_gap(synthetic_images, 7)
    )
    declared = gate_contract.GateContract(**_declared_kwargs(thresholds))
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
        union_adjudication.UnionAdjudicationInput(**payload)
        for payload in _payloads_with_gap(synthetic_images, 12)
    )
    declared = gate_contract.GateContract(**_declared_kwargs(thresholds))
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
    rows = tuple(
        union_adjudication.UnionAdjudicationInput(**payload)
        for payload in synthetic_images
    )
    declared = gate_contract.GateContract(**_declared_kwargs(thresholds))
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
    rows = tuple(
        union_adjudication.UnionAdjudicationInput(**payload)
        for payload in synthetic_images
    )
    declared_kwargs = _declared_kwargs(thresholds)
    declared_kwargs["t14_thresholds_sha256"] = "0" * 64
    declared = gate_contract.GateContract(**declared_kwargs)
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
    rows = tuple(
        union_adjudication.UnionAdjudicationInput(**payload)
        for payload in synthetic_images
    )
    declared = gate_contract.GateContract(**_declared_kwargs(thresholds))
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


def test_bootstrap_ucl_deterministic_with_seed(
    synthetic_images: tuple[dict[str, Any], ...],
) -> None:
    from scripts.eval_harness import union_adjudication

    rows = tuple(
        union_adjudication.UnionAdjudicationInput(**payload)
        for payload in synthetic_images
    )

    first = union_adjudication.bootstrap_ucl(rows, b=2000, seed=23)
    second = union_adjudication.bootstrap_ucl(rows, b=2000, seed=23)

    assert first == second


def test_miss_inflate_refuses_under_30_exhaustive_images(
    synthetic_images: tuple[dict[str, Any], ...],
) -> None:
    from scripts.eval_harness import union_adjudication

    rows = tuple(
        union_adjudication.UnionAdjudicationInput(**payload)
        for payload in synthetic_images
    )

    with pytest.raises(union_adjudication.UnionAdjudicationError):
        union_adjudication.miss_inflate(
            rows,
            exhaustive_image_ids=frozenset(payload["image_id"] for payload in synthetic_images),
        )


def test_miss_inflate_zero_denominator_returns_factor_one_with_flag(
    synthetic_images: tuple[dict[str, Any], ...],
) -> None:
    from scripts.eval_harness import union_adjudication

    zero_gap_payloads = tuple(
        {**payload, "tp_candidate_i": payload["tp_buffalo_i"]}
        for payload in synthetic_images
    )
    rows = tuple(
        union_adjudication.UnionAdjudicationInput(**payload)
        for payload in zero_gap_payloads
    )

    factor, flag = union_adjudication.miss_inflate(
        rows,
        exhaustive_image_ids=_EXHAUSTIVE_IMAGE_IDS,
    )

    assert (factor, flag) == (1.0, 1.0)


def test_miss_inflate_computed_only_from_exhaustive_subset(
    synthetic_images: tuple[dict[str, Any], ...],
) -> None:
    from scripts.eval_harness import union_adjudication

    subset_payloads = tuple(
        {
            **payload,
            "human_true_faces": 100_000,
            "union_boxes": 90_000,
            "tp_buffalo_i": 80_000,
            "tp_candidate_i": 71_900,
        }
        if payload["image_id"] != "image-5"
        else {
            **payload,
            "human_true_faces": 100_000,
            "union_boxes": 0,
            "tp_buffalo_i": 80_000,
            "tp_candidate_i": 0,
        }
        for payload in synthetic_images
    )
    rows = tuple(
        union_adjudication.UnionAdjudicationInput(**payload)
        for payload in subset_payloads
    )
    before = copy.deepcopy(rows)

    factor, flag = union_adjudication.miss_inflate(
        rows,
        exhaustive_image_ids=_EXHAUSTIVE_IMAGE_IDS - {"image-5"},
    )

    assert factor == 1.2346
    assert flag == 0.0
    assert rows == before
