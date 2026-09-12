"""Pure arithmetic and bootstrap helpers for the FIR T-14 gate.

T-14 compares detector true-positive counts over the human-verified faces in
the detector proposal union.  Rows are image-level units: the bootstrap must
resample whole rows, never individual faces.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

import numpy as np

from scripts.eval_harness.gate_contract import (
    GateContract,
    canonical_thresholds,
    exhaustive_subset_sha256,
    threshold_sha256,
)

# WHY: benchmarks/protocols/t14-dead-zone-rule.md signs these verdict parameters.
T14_BOOTSTRAP_B = 2000
T14_KILL_BELOW = 0.05
T14_DEAD_ZONE_UPPER = 0.10
T14_BOOTSTRAP_LEVEL = 0.95


@dataclass(frozen=True)
class UnionAdjudicationInput:
    """One image-level T-14 adjudication row."""

    image_id: str
    union_boxes: int
    human_true_faces: int
    tp_buffalo_i: int
    tp_candidate_i: int
    matched_fppi_declared: float
    thresholds_declared_before_run: dict[str, float]


class DeadZoneVerdict(StrEnum):
    """T-14's three possible outcomes at the declared UCL bounds."""

    KILL = "kill"
    DEAD_ZONE = "dead_zone"
    OPEN = "open"


class UnionAdjudicationError(Exception):
    """Fail-closed validation or protocol error for T-14."""


_REQUIRED_CONDITION_KEYS = frozenset(
    {
        "union_uses_human_true_faces",
        "matched_fppi_equal_across_rows",
        "verdict_from_bootstrap_ucl",
        "thresholds_frozen_before_run",
    }
)
_THRESHOLD_KEYS = frozenset({"buffalo", "candidate"})


def _rows_tuple(
    rows: Sequence[UnionAdjudicationInput],
    *,
    allow_empty: bool = False,
    require_unique_image_ids: bool = True,
) -> tuple[UnionAdjudicationInput, ...]:
    try:
        normalised = tuple(rows)
    except TypeError as exc:
        raise UnionAdjudicationError("rows must be a sequence of image rows") from exc
    if not normalised and not allow_empty:
        raise UnionAdjudicationError("rows must contain at least one image")

    seen_image_ids: set[str] = set()
    for index, row in enumerate(normalised):
        if not isinstance(row, UnionAdjudicationInput):
            raise UnionAdjudicationError(f"rows[{index}] must be a UnionAdjudicationInput, got {type(row).__name__}")
        if not isinstance(row.image_id, str) or not row.image_id.strip():
            raise UnionAdjudicationError(f"rows[{index}].image_id must be a non-empty string")
        if require_unique_image_ids:
            if row.image_id in seen_image_ids:
                raise UnionAdjudicationError(f"duplicate image_id in rows: {row.image_id!r}")
            seen_image_ids.add(row.image_id)
        for name in (
            "union_boxes",
            "human_true_faces",
            "tp_buffalo_i",
            "tp_candidate_i",
        ):
            value = getattr(row, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise UnionAdjudicationError(f"rows[{index}].{name} must be a non-negative integer")
        for name in ("union_boxes", "tp_buffalo_i", "tp_candidate_i"):
            value = getattr(row, name)
            if value > row.human_true_faces:
                raise UnionAdjudicationError(
                    f"rows[{index}].{name}={value} exceeds human_true_faces={row.human_true_faces}; "
                    "T-14 counts are restricted to human-verified true faces "
                    "(signed condition 'union_uses_human_true_faces')"
                )
        fppi = row.matched_fppi_declared
        if isinstance(fppi, bool) or not isinstance(fppi, (int, float)) or not math.isfinite(float(fppi)):
            raise UnionAdjudicationError(f"rows[{index}].matched_fppi_declared must be a finite number")
        if fppi < 0:
            raise UnionAdjudicationError(f"rows[{index}].matched_fppi_declared must be non-negative")
        thresholds = row.thresholds_declared_before_run
        if not isinstance(thresholds, Mapping) or set(thresholds) != _THRESHOLD_KEYS:
            raise UnionAdjudicationError(
                f"rows[{index}].thresholds_declared_before_run must contain exactly 'buffalo' and 'candidate'"
            )
        for key in ("buffalo", "candidate"):
            value = thresholds[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise UnionAdjudicationError(
                    f"rows[{index}].thresholds_declared_before_run.{key} must be a finite number"
                )
            if not math.isfinite(float(value)):
                raise UnionAdjudicationError(
                    f"rows[{index}].thresholds_declared_before_run.{key} must be a finite number"
                )
    return normalised


def _detector_gap_bound_unvalidated(rows: Sequence[UnionAdjudicationInput]) -> float:
    """Compute a gap from rows already validated by ``_rows_tuple``."""

    denominator = sum(row.human_true_faces for row in rows)
    if denominator <= 0:
        raise UnionAdjudicationError("human_true_faces denominator must be positive")
    return float((sum(row.tp_buffalo_i for row in rows) - sum(row.tp_candidate_i for row in rows)) / denominator)


def detector_gap_bound(rows: Sequence[UnionAdjudicationInput]) -> float:
    """Return ``(TP_buffalo - TP_candidate) / human_true_faces``."""

    normalised = _rows_tuple(rows)
    return _detector_gap_bound_unvalidated(normalised)


def _validate_bootstrap_arguments(*, b: int, seed: int, resampling_unit: str, level: float) -> None:
    if isinstance(b, bool) or not isinstance(b, int) or b <= 0:
        raise UnionAdjudicationError("b must be a positive integer")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise UnionAdjudicationError("seed must be an integer")
    if resampling_unit != "image":
        raise UnionAdjudicationError("resampling_unit must be 'image'")
    if isinstance(level, bool) or not isinstance(level, (int, float)) or not math.isfinite(float(level)):
        raise UnionAdjudicationError("level must be a finite number in (0, 1]")
    if not 0 < level <= 1:
        raise UnionAdjudicationError("level must be a finite number in (0, 1]")


def bootstrap_ucl(
    rows: Sequence[UnionAdjudicationInput],
    *,
    b: int = 2000,
    seed: int,
    resampling_unit: str = "image",
    level: float = 0.95,
) -> float:
    """Return the percentile UCL from an image-level seeded bootstrap."""

    normalised = _rows_tuple(rows)
    _validate_bootstrap_arguments(b=b, seed=seed, resampling_unit=resampling_unit, level=level)
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, len(normalised), size=(b, len(normalised)))
    estimates = np.empty(b, dtype=float)
    for sample_index, selected in enumerate(indices):
        estimates[sample_index] = _detector_gap_bound_unvalidated(
            tuple(normalised[int(row_index)] for row_index in selected)
        )
    return float(np.percentile(estimates, float(level) * 100.0))


def miss_inflate(
    rows: Sequence[UnionAdjudicationInput],
    *,
    exhaustive_image_ids: frozenset[str],
) -> tuple[float, float]:
    """Estimate the union-miss inflation factor from an exhaustive subset.

    The numerator is the number of human-verified faces absent from the union
    (``human_true_faces - union_boxes``).  The denominator is the detector-
    flagged Buffalo-minus-candidate miss count.  Both are accumulated only on
    the declared exhaustive image subset. Returns (factor, degenerate_flag),
    where the flag is 1.0 exactly when the denominator is zero.
    """

    normalised = _rows_tuple(rows, allow_empty=True)
    matched_ids = {row.image_id for row in normalised} & exhaustive_image_ids
    unmatched = exhaustive_image_ids - matched_ids
    if unmatched:
        raise UnionAdjudicationError(
            "declared exhaustive image IDs are absent from the input rows: "
            f"{sorted(unmatched)[:5]}{'...' if len(unmatched) > 5 else ''} "
            f"({len(unmatched)} of {len(exhaustive_image_ids)})"
        )
    exhaustive_rows = tuple(row for row in normalised if row.image_id in exhaustive_image_ids)
    if len(exhaustive_rows) < 30:
        raise UnionAdjudicationError(
            f"at least 30 exhaustive image rows are required for miss inflation, matched {len(exhaustive_rows)}"
        )
    exhaustive_misses = sum(row.human_true_faces - row.union_boxes for row in exhaustive_rows)
    detector_flagged_misses = sum(row.tp_buffalo_i - row.tp_candidate_i for row in exhaustive_rows)
    if detector_flagged_misses == 0:
        return (1.0, 1.0)

    ratio = Decimal(exhaustive_misses) / Decimal(detector_flagged_misses)
    if ratio < Decimal("1.0"):
        ratio_display = format(ratio, "f")
        if "." not in ratio_display:
            ratio_display += ".0000"
        else:
            fractional_digits = len(ratio_display.partition(".")[2])
            ratio_display += "0" * max(0, 4 - fractional_digits)
        raise UnionAdjudicationError(
            "computed miss inflation factor "
            f"{ratio_display} is below 1.0 (exhaustive miss numerator={exhaustive_misses}, "
            f"detector-flagged denominator={detector_flagged_misses})"
        )
    factor = ratio.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return (float(factor), 0.0)


def _validate_conditions(conditions_met: Mapping[str, bool]) -> None:
    if not isinstance(conditions_met, Mapping):
        raise UnionAdjudicationError("conditions_met must be a mapping")
    missing = _REQUIRED_CONDITION_KEYS - set(conditions_met)
    if missing:
        raise UnionAdjudicationError(f"missing required T-14 condition confirmations: {sorted(missing)}")
    unknown = sorted(set(conditions_met) - _REQUIRED_CONDITION_KEYS)
    if unknown:
        raise UnionAdjudicationError(f"unrecognised T-14 condition confirmations: {unknown}")
    failed = sorted(key for key in _REQUIRED_CONDITION_KEYS if conditions_met[key] is not True)
    if failed:
        raise UnionAdjudicationError(f"T-14 condition confirmations are not all true: {failed}")


def check_conditions(
    rows: Sequence[UnionAdjudicationInput],
    *,
    declared: GateContract,
    signed_decision_id: str | None,
    conditions_met: Mapping[str, bool],
    exhaustive_image_ids: frozenset[str] | None = None,
    kill_below: float = 0.05,
    dead_zone_upper: float = 0.10,
    b: int = 2000,
    seed: int,
) -> DeadZoneVerdict:
    """Validate the signed T-14 preconditions and classify its miss-inflated bootstrap UCL.

    The optional ``exhaustive_image_ids`` supplies the miss-inflation correction.
    """

    if not isinstance(signed_decision_id, str) or not signed_decision_id.strip():
        raise UnionAdjudicationError("a signed_decision_id is required before T-14 can be adjudicated")
    if not isinstance(declared, GateContract):
        raise UnionAdjudicationError("declared must be a GateContract")
    _validate_conditions(conditions_met)
    normalised = _rows_tuple(rows)

    thresholds = canonical_thresholds(normalised[0].thresholds_declared_before_run)
    if any(canonical_thresholds(row.thresholds_declared_before_run) != thresholds for row in normalised[1:]):
        raise UnionAdjudicationError("thresholds_declared_before_run must be identical on every row")
    if any(row.matched_fppi_declared != normalised[0].matched_fppi_declared for row in normalised[1:]):
        raise UnionAdjudicationError("matched_fppi_declared must be identical on every row")
    if declared.t14_thresholds_declared is None or declared.t14_thresholds_sha256 is None:
        raise UnionAdjudicationError("T-14 thresholds must be ratified in the declared contract before adjudication")
    if canonical_thresholds(declared.t14_thresholds_declared) != thresholds:
        raise UnionAdjudicationError("run thresholds do not match the declared T-14 thresholds")
    if threshold_sha256(thresholds) != declared.t14_thresholds_sha256:
        raise UnionAdjudicationError("run threshold hash does not match the declared T-14 threshold hash")

    if (
        isinstance(kill_below, bool)
        or not isinstance(kill_below, (int, float))
        or not math.isfinite(float(kill_below))
        or isinstance(dead_zone_upper, bool)
        or not isinstance(dead_zone_upper, (int, float))
        or not math.isfinite(float(dead_zone_upper))
        or not 0 <= kill_below < dead_zone_upper
    ):
        raise UnionAdjudicationError("T-14 bounds must be finite with 0 <= kill_below < dead_zone_upper")

    _validate_bootstrap_arguments(b=b, seed=seed, resampling_unit="image", level=T14_BOOTSTRAP_LEVEL)
    for name, value, fixed in (
        ("b", b, T14_BOOTSTRAP_B),
        ("kill_below", kill_below, T14_KILL_BELOW),
        ("dead_zone_upper", dead_zone_upper, T14_DEAD_ZONE_UPPER),
    ):
        if value != fixed:
            raise UnionAdjudicationError(
                f"T-14 {name} is fixed at {fixed} by the signed protocol; refusing a caller override"
            )

    if exhaustive_image_ids is not None:
        if declared.t14_exhaustive_subset_count is None or declared.t14_exhaustive_subset_sha256 is None:
            raise UnionAdjudicationError(
                "the exhaustive-image subset must be ratified in the declared contract before adjudication"
            )
        if len(exhaustive_image_ids) != declared.t14_exhaustive_subset_count:
            raise UnionAdjudicationError(
                f"run exhaustive-subset count {len(exhaustive_image_ids)} does not match "
                f"declared count {declared.t14_exhaustive_subset_count}"
            )
        if exhaustive_subset_sha256(exhaustive_image_ids) != declared.t14_exhaustive_subset_sha256:
            raise UnionAdjudicationError("run exhaustive-subset hash does not match the declared T-14 subset hash")
    elif declared.t14_exhaustive_subset_count is not None:
        raise UnionAdjudicationError("the ratified exhaustive-image subset requires exhaustive_image_ids")

    ucl = bootstrap_ucl(normalised, b=T14_BOOTSTRAP_B, seed=seed, level=T14_BOOTSTRAP_LEVEL)
    degenerate_flag = 0.0
    if exhaustive_image_ids is not None:
        factor, degenerate_flag = miss_inflate(normalised, exhaustive_image_ids=exhaustive_image_ids)
        bound = ucl * factor
    else:
        bound = ucl

    if bound < T14_KILL_BELOW:
        if exhaustive_image_ids is None:
            raise UnionAdjudicationError(
                "KILL requires the exhaustive-image miss-inflation correction; pass exhaustive_image_ids"
            )
        if (
            degenerate_flag
            and sum(
                row.human_true_faces - row.union_boxes for row in normalised if row.image_id in exhaustive_image_ids
            )
            > 0
        ):
            raise UnionAdjudicationError(
                "the miss-inflation correction is unmeasurable (zero detector-flagged denominator) "
                "while exhaustive misses exist; T-14 cannot return KILL"
            )
        return DeadZoneVerdict.KILL
    if bound < T14_DEAD_ZONE_UPPER:
        return DeadZoneVerdict.DEAD_ZONE
    return DeadZoneVerdict.OPEN


__all__ = [
    "T14_BOOTSTRAP_B",
    "T14_KILL_BELOW",
    "T14_DEAD_ZONE_UPPER",
    "T14_BOOTSTRAP_LEVEL",
    "DeadZoneVerdict",
    "UnionAdjudicationError",
    "UnionAdjudicationInput",
    "_REQUIRED_CONDITION_KEYS",
    "bootstrap_ucl",
    "check_conditions",
    "detector_gap_bound",
    "miss_inflate",
]
