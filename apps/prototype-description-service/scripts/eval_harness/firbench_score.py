"""S3 scoring: outcomes, FNIR/FPI curves, frozen-tau calibration, paired PSU intervals and the verdict.

EVAL-16: an upstream miss (undetected or unaligned mate) is a miss, never dropped.
EVAL-18: non-mated probes and a score threshold, never rank.
EVAL-19: FPI counts non-mated source units. Detector alarms never add units or searches.
CAL-07 / EXP-22: calibration uses only identity-disjoint calibration folds.
EXP-23: the interval resamples PSUs, the independent unit, not images.
EXP-12 / CARD-27: MDE is design sensitivity, distinct from the sealed practical margin.

Every binding value (tau, FPIR target, margin, alpha, floors, seeds, power, p_d, ICC) comes from
the decision manifest or the caller. Nothing is a module-level default.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from statistics import NormalDist
from typing import Any, Protocol

import numpy as np
from scipy import stats

from scripts.eval_harness import firbench_contract as fc

# Report-only design sensitivity grid, fixed by the frozen score wire (scores-v1 icc_sensitivity).
ICC_SENSITIVITY_ROWS: tuple[float, ...] = (0.05, 0.10, 0.20)
_CONFIDENCE_LEVEL_FPIR = 0.95


class GuardrailState(StrEnum):
    """Guardrail state, written to scores.json. ``unscored`` gates a veto; it never reads as a pass."""

    pass_ = "pass"
    fail = "fail"
    unscored = "unscored"


class SearchRecord(Protocol):
    """Attributes S3 reads from one face-search-record-v1 row (README table; S2 owns the producer)."""

    face_id: str
    image_id: str
    psu_id: str
    identity_id: str | None
    identity_status: fc.IdentityStatus
    fold: int
    unit_id: str | None
    sampling_arm: fc.SamplingArm
    inclusion_probability: float | None
    cohort: Mapping[str, str | None] | None
    arm: fc.Arm
    arm_availability: fc.ArmStatus
    stage_reached: fc.SearchStage | None
    top_k: Sequence[tuple[str, float]]


class NonMatedUnitLike(Protocol):
    """Attributes S3 reads from one fixed non-mated source unit (S1 Build 7 NonMatedUnit)."""

    unit_id: str
    psu_id: str
    fold: int
    cohort: Mapping[str, str | None] | None


@dataclass(frozen=True)
class CurvePoint:
    """FNIR over mated faces and FPI/FPIR over non-mated source units at one threshold."""

    threshold: float
    fnir: float | None
    fnir_misses: int
    n_mated: int
    fpi: int
    n_units: int
    fpir: float
    spurious_names: int
    spurious_per_1k_images: float | None


@dataclass(frozen=True)
class PairedInterval:
    """Paired PSU-cluster percentile interval for delta = FNIR(a) - FNIR(b), with observed ICC."""

    delta: float
    lower: float
    upper: float
    n_psu: int
    icc: float | None
    level: float
    n_boot: int
    seed: int


@dataclass(frozen=True)
class FpirBound:
    """One-sided 95% FPIR bound. ``approximate`` is true for every clustered or iid-approximate bound."""

    upper: float
    method: str
    approximate: bool
    level: float


@dataclass(frozen=True)
class LegArrays:
    """Mated outcomes for one leg: every GT mate, including explicit upstream misses."""

    leg: fc.LegKind
    face_ids: tuple[str, ...]
    outcomes: tuple[fc.FaceOutcome, ...]
    psu_ids: tuple[str, ...]
    weights: tuple[float, ...]

    def __post_init__(self) -> None:
        n = len(self.face_ids)
        if any(len(values) != n for values in (self.outcomes, self.psu_ids, self.weights)):
            raise fc.FrameContractError("mated face ids, outcomes, PSU ids and weights must align")
        if any(not isinstance(face, str) or not face.strip() for face in self.face_ids):
            raise fc.FrameContractError("every mated face needs a non-empty GT id")
        if len(set(self.face_ids)) != n:
            raise fc.FrameContractError("duplicate mated GT face ids")
        _validate_mated_inputs(self.outcomes, self.outcomes, self.psu_ids, self.weights)


@dataclass(frozen=True)
class GuardrailReading:
    """A guardrail's measured state. ``unscored`` (or absent) on a veto gives required_guardrail_unscored."""

    state: GuardrailState
    value: float | None


@dataclass(frozen=True)
class LegResults:
    """Everything decide reads: the frame, per-leg mated arrays, the fixed unit PSUs and guardrail states.

    ``h2_leg`` names the in-house leg built as the H2 comparison. decide refuses a mismatch with the
    sealed manifest (UndeclaredH2LegError).
    """

    frame: fc.FrameSpec
    legs: Mapping[fc.LegKind, LegArrays]
    unit_psu_ids: tuple[str, ...]
    h2_leg: fc.LegKind
    guardrails: Mapping[str, GuardrailReading] = field(default_factory=dict)


@dataclass(frozen=True)
class HypothesisVerdict:
    """One Holm step: its level, design sensitivity, interval (when read) and state."""

    id: str
    kind: fc.HypothesisKind
    step_index: int
    one_sided_alpha: float
    level: float
    n_eff: float
    mde: float | None
    interval: PairedInterval | None
    state: fc.VerdictState | None
    reason: fc.InconclusiveReason | None


@dataclass(frozen=True)
class Verdict:
    """The verdict: overall state, reason, per-hypothesis states, and the decision path taken."""

    frame_id: str
    state: fc.VerdictState
    reason: fc.InconclusiveReason | None
    hypotheses: tuple[HypothesisVerdict, ...]
    decision_path: tuple[str, ...]


# --- record classification and outcomes ----------------------------------------------------


def _is_mated(record: SearchRecord) -> bool:
    return record.unit_id is None and record.identity_id is not None


def _is_unit_record(record: SearchRecord) -> bool:
    return record.unit_id is not None


def _top1(top_k: Sequence[tuple[str, float]]) -> tuple[str, float] | None:
    best: tuple[str, float] | None = None
    for name, score in top_k:
        if not isinstance(name, str) or not name:
            raise fc.FrameContractError("top_k identities must be non-empty strings")
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score):
            raise fc.FrameContractError(f"non-finite or non-numeric top_k score {score!r}")
        value = float(score)
        if best is None or value > best[1]:
            best = (name, value)
    return best


def _accepts(score: float, tau: float, *, nonmated: bool, boundary: fc.BoundarySemantics) -> bool:
    """legacy_v1: non-mated accept iff score > tau, mated iff score >= tau. v2: score >= tau for both."""
    if nonmated and boundary is fc.BoundarySemantics.legacy_v1:
        return score > tau
    return score >= tau


def _above_names(record: SearchRecord, tau: float, boundary: fc.BoundarySemantics) -> int:
    return sum(1 for _, score in record.top_k if _accepts(float(score), tau, nonmated=True, boundary=boundary))


def _mated_outcome(record: SearchRecord, tau: float, boundary: fc.BoundarySemantics) -> fc.FaceOutcome:
    stage = record.stage_reached
    if stage in (fc.SearchStage.missed, fc.SearchStage.detected):
        return fc.FaceOutcome.missed  # a fused-leg detection with no embedding is a miss (S0 FaceOutcome)
    if stage is fc.SearchStage.unaligned:
        return fc.FaceOutcome.unaligned
    if stage is fc.SearchStage.embedded:
        top = _top1(record.top_k)
        if top is None or not _accepts(top[1], tau, nonmated=False, boundary=boundary):
            return fc.FaceOutcome.rejected
        return fc.FaceOutcome.correct if top[0] == record.identity_id else fc.FaceOutcome.wrong_identity
    raise fc.FrameContractError(f"mated record {record.face_id} has stage {stage!r} on an available arm")


def _nonmated_outcome(record: SearchRecord, tau: float, boundary: fc.BoundarySemantics) -> fc.FaceOutcome:
    stage = record.stage_reached
    if stage in (fc.SearchStage.missed, fc.SearchStage.detected, fc.SearchStage.unaligned):
        return fc.FaceOutcome.correct_reject  # no embedding, so no accept
    if stage is fc.SearchStage.embedded:
        top = _top1(record.top_k)
        if top is not None and _accepts(top[1], tau, nonmated=True, boundary=boundary):
            return fc.FaceOutcome.false_accept
        return fc.FaceOutcome.correct_reject
    raise fc.FrameContractError(f"non-mated record {record.face_id} has stage {stage!r} on an available arm")


def _outcome(record: SearchRecord, tau: float, boundary: fc.BoundarySemantics) -> fc.FaceOutcome | None:
    """Finished outcome of a record, or None when it is not an outcome (unavailable arm or duplicate)."""
    _validate_record(record)
    if record.arm_availability is not fc.ArmStatus.available:
        return None
    if _is_mated(record):
        return _mated_outcome(record, tau, boundary)
    if _is_unit_record(record):
        return _nonmated_outcome(record, tau, boundary)
    return None  # duplicate detection over a mated face: spurious names only (S2 Build 5)


def finish_outcomes(
    records: Sequence[SearchRecord], tau: float, boundary: fc.BoundarySemantics
) -> tuple[fc.FaceOutcome, ...]:
    """Final outcome per available mated or non-mated record, in input order (S0 Build 10 signature).

    Unavailable-arm records and duplicate detections are not outcomes. ``excluded_by_arm`` counts them.
    """
    _require_finite_tau(tau)
    _require_boundary(boundary)
    return tuple(o for o in (_outcome(r, tau, boundary) for r in records) if o is not None)


def excluded_by_arm(records: Sequence[SearchRecord]) -> dict[tuple[fc.Arm, fc.ArmStatus], int]:
    """Counts of records whose arm did not run, per (arm, availability). Never imputed as misses."""
    counts: Counter[tuple[fc.Arm, fc.ArmStatus]] = Counter(
        (r.arm, r.arm_availability) for r in records if r.arm_availability is not fc.ArmStatus.available
    )
    return dict(sorted(counts.items(), key=lambda item: (item[0][0].value, item[0][1].value)))


def _require_finite_tau(tau: float) -> None:
    if isinstance(tau, bool) or not isinstance(tau, (int, float)) or not math.isfinite(tau):
        raise fc.FrameContractError(f"tau must be finite, got {tau!r}")


def _require_boundary(boundary: fc.BoundarySemantics) -> None:
    if not isinstance(boundary, fc.BoundarySemantics):
        raise fc.FrameContractError(f"unknown boundary semantics {boundary!r}")


def _require_integer(value: int, label: str, *, minimum: int = 0) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise fc.FrameContractError(f"{label} must be an integer >= {minimum}")


def _require_probability(value: float, label: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0.0 < value < 1.0
    ):
        raise fc.FrameContractError(f"{label} must be finite and in (0, 1)")


def _require_effective_n(value: float, *, allow_zero: bool = False) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
        or (not allow_zero and value == 0)
    ):
        raise fc.FrameContractError("n_nonmated_eff must be finite and positive (or zero for resolvability)")


def _validate_record(record: SearchRecord) -> None:
    _top1(record.top_k)  # Validate every score, including excluded arms and stages without outcomes.
    if record.top_k and record.stage_reached is not fc.SearchStage.embedded:
        raise fc.FrameContractError(f"record {record.face_id} has scores without an embedded stage")
    if record.identity_id is not None and record.identity_status is not fc.IdentityStatus.named:
        raise fc.FrameContractError(f"record {record.face_id} has an identity without named provenance")
    if record.identity_id is not None and record.unit_id is not None:
        raise fc.FrameContractError(f"mated identity on {record.face_id} cannot carry a non-mated unit")
    if record.identity_status is fc.IdentityStatus.unresolved and record.unit_id is not None:
        raise fc.FrameContractError(f"unresolved record {record.face_id} cannot be non-mated")
    _weight(record)


def _weight(record: SearchRecord) -> float:
    """IPW weight 1/inclusion_probability on the probability arm; 1 on the challenge arm (S1 Build 1)."""
    if record.sampling_arm is fc.SamplingArm.challenge:
        return 1.0
    if record.sampling_arm is not fc.SamplingArm.probability:
        raise fc.FrameContractError(f"unknown sampling arm {record.sampling_arm!r}")
    prob = record.inclusion_probability
    if (
        isinstance(prob, bool)
        or not isinstance(prob, (int, float))
        or not math.isfinite(prob)
        or not (0.0 < prob <= 1.0)
        or not math.isfinite(1.0 / prob)
    ):
        raise fc.FrameContractError(f"probability-arm record {record.face_id} needs inclusion_probability in (0, 1]")
    return 1.0 / prob


def _require_single_sampling_arm(records: Sequence[SearchRecord]) -> None:
    arms = {r.sampling_arm for r in records}
    if len(arms) > 1:
        raise fc.FrameContractError("sampling arms are reported separately and never pooled in one curve")


def _index_units(units: Sequence[NonMatedUnitLike]) -> dict[str, NonMatedUnitLike]:
    index: dict[str, NonMatedUnitLike] = {}
    for unit in units:
        if not isinstance(unit.unit_id, str) or not unit.unit_id:
            raise fc.FrameContractError("source unit IDs must be non-empty strings")
        if unit.unit_id in index:
            raise fc.FrameContractError(f"duplicate non-mated source unit {unit.unit_id!r}")
        index[unit.unit_id] = unit
    return index


def _require_native_scope(records: Sequence[SearchRecord]) -> None:
    if any(r.arm is not fc.Arm.native for r in records):
        raise fc.FrameContractError("FPIR curves and calibration require native search records; attribution is separate")
    if len({getattr(r, "leg_key", None) for r in records}) > 1:
        raise fc.FrameContractError("one FPIR curve/calibration must use one native leg and embedding space")
    galleries: dict[int, str | None] = {}
    for record in records:
        gallery = getattr(record, "gallery_sha256", None)
        if galleries.setdefault(record.fold, gallery) != gallery:
            raise fc.FrameContractError("one query fold must use one native gallery snapshot")
    _require_single_sampling_arm(records)


def _require_fixed_pool(records: Sequence[SearchRecord], index: Mapping[str, NonMatedUnitLike]) -> None:
    for record in records:
        if _is_mated(record) and record.face_id in index:
            raise fc.FrameContractError(f"mated face {record.face_id} is in the non-mated pool")
        if record.unit_id is not None:
            if record.unit_id not in index:
                raise fc.FrameContractError(
                    f"record {record.face_id} names unit {record.unit_id!r} outside the fixed pool"
                )
            if record.fold != index[record.unit_id].fold:
                raise fc.FrameContractError(f"record {record.face_id} disagrees with its source unit fold")


# --- curves ---------------------------------------------------------------------------------


def curve(
    records: Sequence[SearchRecord],
    *,
    units: Sequence[NonMatedUnitLike],
    thresholds: Sequence[float],
    boundary: fc.BoundarySemantics,
) -> tuple[CurvePoint, ...]:
    """FNIR over mated faces; FPI and FPIR over the fixed non-mated source-unit pool at each threshold.

    FPI counts units with any false accept (an integer). FPIR = FPI / N_units. A detector alarm that
    names a unit outside the pool is refused, so detector output never changes the denominator (EVAL-19).
    """
    if not units:
        raise fc.FrameContractError("the non-mated source-unit pool is empty; FPIR has no denominator")
    index = _index_units(units)
    _require_boundary(boundary)
    _require_native_scope(records)
    for record in records:
        _validate_record(record)
    _require_fixed_pool(records, index)
    n_units = len(index)
    # S1 reserves one background:<image_id> source unit per exhaustive frame image.
    # A non-mated GT face may have unknown cohort metadata; it is still a face, not an image.
    n_images = sum(unit_id.startswith("background:") for unit_id in index)
    points: list[CurvePoint] = []
    for tau in thresholds:
        _require_finite_tau(tau)
        misses = 0
        n_mated = 0
        weight_total = 0.0
        miss_weight = 0.0
        false_accept_units: set[str] = set()
        names_by_unit: Counter[str] = Counter()
        duplicate_names = 0
        for record in records:
            if record.arm_availability is not fc.ArmStatus.available:
                continue
            if _is_mated(record):
                outcome = _mated_outcome(record, tau, boundary)
                n_mated += 1
                weight = _weight(record)
                weight_total += weight
                if outcome is not fc.FaceOutcome.correct:
                    misses += 1
                    miss_weight += weight
            elif _is_unit_record(record):
                names_by_unit[record.unit_id] += _above_names(record, tau, boundary)
                if _nonmated_outcome(record, tau, boundary) is fc.FaceOutcome.false_accept:
                    false_accept_units.add(record.unit_id)
            else:
                duplicate_names += _above_names(record, tau, boundary)
        spurious = duplicate_names + sum(names_by_unit[u] - 1 for u in false_accept_units)
        fnir = (miss_weight / weight_total) if n_mated else None
        per_1k = (spurious * 1000.0 / n_images) if n_images else None
        points.append(
            CurvePoint(
                threshold=float(tau),
                fnir=fnir,
                fnir_misses=misses,
                n_mated=n_mated,
                fpi=len(false_accept_units),
                n_units=n_units,
                fpir=len(false_accept_units) / n_units,
                spurious_names=spurious,
                spurious_per_1k_images=per_1k,
            )
        )
    return tuple(points)


# --- calibration ---------------------------------------------------------------------------


def calibrate_tau(
    records: Sequence[SearchRecord],
    *,
    units: Sequence[NonMatedUnitLike],
    calibration_folds: frozenset[int],
    fpir_target: float,
    boundary: fc.BoundarySemantics,
    identity_folds: Mapping[str, int] | None = None,
) -> float:
    """Freeze tau on fit probes and their per-query-fold galleries, with identity-fold provenance.

    IO passes the complete predeclared identity fold map, which may include unused test identities.
    Every used probe/hit must have fit provenance; gallery snapshots may differ across query folds.
    For older callers, mated records may prove the map only when they cover every referenced
    identity; unknown names never default to fit.
    Unit maxima use only the fixed pool; absent searches score -inf. With m=floor(target*N),
    legacy rejects scores <= the (m+1)-th largest score. v2 uses a finite threshold strictly
    above that cut, including when a midpoint rounds back to the cut.
    """
    _require_probability(fpir_target, "fpir_target")
    _require_boundary(boundary)
    folds = frozenset(calibration_folds)
    if not folds:
        raise fc.FrameContractError("calibration_folds must be non-empty")
    for fold in folds:
        _require_integer(fold, "calibration fold")
    index = _index_units(units)
    _require_native_scope(records)
    for unit in units:
        _require_integer(unit.fold, "source unit fold")
        if unit.fold not in folds:
            raise fc.CalibrationLeakError(f"unit {unit.unit_id} is in a test fold")
    for record in records:
        _require_integer(record.fold, "probe fold")
        if record.fold not in folds:
            raise fc.CalibrationLeakError(f"probe {record.face_id} is in a test fold")
        _validate_record(record)
    _require_fixed_pool(records, index)
    if identity_folds is None:
        identity_fold: dict[str, int] = {}
        for record in records:
            if _is_mated(record):
                identity = record.identity_id
                if identity_fold.setdefault(identity, record.fold) != record.fold:
                    raise fc.CalibrationLeakError(f"identity {identity!r} spans several folds")
    else:
        if not isinstance(identity_folds, Mapping):
            raise fc.FrameContractError("identity_folds must be a mapping")
        identity_fold = dict(identity_folds)
    for identity, fold in identity_fold.items():
        if not isinstance(identity, str) or not identity:
            raise fc.FrameContractError("identity fold map keys must be non-empty identity IDs")
        _require_integer(fold, f"fold of identity {identity}")
    for record in records:
        if record.identity_id is not None and identity_fold.get(record.identity_id) != record.fold:
            raise fc.CalibrationLeakError(f"probe {record.face_id} has missing or contradictory identity fold provenance")
        for name, _ in record.top_k:
            if identity_fold.get(name) not in folds:
                raise fc.CalibrationLeakError(
                    f"probe {record.face_id} has a top-k identity without known calibration-fold provenance"
                )
    unit_score: dict[str, float] = {}
    for record in records:
        if record.arm_availability is fc.ArmStatus.available and _is_unit_record(record):
            top = _top1(record.top_k)
            if top is not None:
                unit_score[record.unit_id] = max(unit_score.get(record.unit_id, -math.inf), top[1])
    pooled = [unit_score.get(unit.unit_id, -math.inf) for unit in units]
    if not pooled:
        raise fc.TauInfeasibleError("the calibration pool is empty")
    m = math.floor(fpir_target * len(pooled))
    ordered = sorted(pooled, reverse=True)
    cut = ordered[m]
    if not math.isfinite(cut):
        raise fc.TauInfeasibleError("fewer calibration units carry a score than the FPIR allowance")
    if boundary is fc.BoundarySemantics.legacy_v1:
        return cut
    greater = [score for score in ordered if score > cut]
    # Halving first avoids overflow; adjacent floats may still round the midpoint to cut.
    tau = (cut / 2.0 + min(greater) / 2.0) if greater else math.nextafter(cut, math.inf)
    if tau <= cut:
        tau = math.nextafter(cut, math.inf)
    if not math.isfinite(tau):
        raise fc.TauInfeasibleError("no finite v2 threshold can reject the calibration cut")
    return tau


def fpir_resolvable(target: float, n_nonmated_eff: float) -> bool:
    """True iff n_nonmated_eff >= 3 / target; the eligibility floor has no tolerance."""
    _require_probability(target, "FPIR target")
    _require_effective_n(n_nonmated_eff, allow_zero=True)
    return n_nonmated_eff >= 3.0 / target


def clopper_pearson_upper(count: int, n: int, *, level: float = _CONFIDENCE_LEVEL_FPIR) -> float:
    """Exact one-sided Clopper-Pearson upper bound on integer count out of integer n (iid approximation)."""
    _require_probability(level, "confidence level")
    if isinstance(count, bool) or isinstance(n, bool) or not isinstance(count, int) or not isinstance(n, int):
        raise fc.FrameContractError("Clopper-Pearson needs integer count and n; never a fractional n_eff")
    if n <= 0 or not 0 <= count <= n:
        raise fc.FrameContractError(f"invalid binomial count {count} of {n}")
    if count == n:
        return 1.0
    return float(stats.beta.ppf(level, count + 1, n - count))


def fpir_upper_bound(
    *,
    fpi: int,
    n_units: int,
    n_nonmated_eff: float,
    planning_psu_ids: Sequence[str] | None = None,
    unit_false_accept: Sequence[bool] | None = None,
    n_boot: int,
    seed: int,
) -> FpirBound:
    """Clustered one-sided 95% FPIR bound: PSU percentile when FPI > 0, else 3 / n_nonmated_eff (approximate)."""
    _require_integer(fpi, "fpi")
    _require_integer(n_units, "n_units", minimum=1)
    _require_integer(n_boot, "n_boot", minimum=1)
    _require_integer(seed, "seed")
    _require_effective_n(n_nonmated_eff)
    if fpi > n_units or n_nonmated_eff > n_units:
        raise fc.FrameContractError("FPI and effective inventory cannot exceed n_units")
    if planning_psu_ids is not None and (
        len(planning_psu_ids) != n_units
        or any(not isinstance(psu, str) or not psu.strip() for psu in planning_psu_ids)
    ):
        raise fc.FrameContractError("unit PSU ids must be non-empty strings aligned with n_units")
    if unit_false_accept is not None:
        if len(unit_false_accept) != n_units or any(
            not isinstance(flag, (bool, np.bool_)) for flag in unit_false_accept
        ):
            raise fc.FrameContractError("false-accept flags must be booleans aligned with n_units")
        if sum(unit_false_accept) != fpi:
            raise fc.FrameContractError("false-accept flags disagree with the exact FPI count")
    if fpi == 0:
        return FpirBound(
            upper=min(1.0, 3.0 / n_nonmated_eff),
            method="rule_of_three",
            approximate=True,
            level=_CONFIDENCE_LEVEL_FPIR,
        )
    if planning_psu_ids is None or unit_false_accept is None:
        raise fc.FrameContractError("a positive-FPI clustered bound needs unit PSU ids and false-accept flags")
    psus, codes = np.unique(np.asarray(list(planning_psu_ids), dtype=str), return_inverse=True)
    accepts = np.asarray(unit_false_accept, dtype=float)
    k = len(psus)
    sizes = np.bincount(codes, minlength=k).astype(float)
    events = np.bincount(codes, weights=accepts, minlength=k)
    rng = np.random.default_rng(seed)
    rates = np.empty(n_boot)
    for i in range(n_boot):
        counts = np.bincount(rng.integers(0, k, size=k), minlength=k)
        rates[i] = (counts @ events) / (counts @ sizes)
    upper = float(np.quantile(rates, _CONFIDENCE_LEVEL_FPIR))
    return FpirBound(upper=upper, method="psu_percentile", approximate=True, level=_CONFIDENCE_LEVEL_FPIR)


# --- paired PSU-cluster interval ----------------------------------------------------------


def _validate_mated_inputs(
    outcomes_a: Sequence[fc.FaceOutcome],
    outcomes_b: Sequence[fc.FaceOutcome],
    psu_of: Sequence[str],
    weights: Sequence[float] | None,
) -> np.ndarray:
    n = len(outcomes_a)
    if len(outcomes_b) != n or len(psu_of) != n or (weights is not None and len(weights) != n):
        raise fc.FrameContractError("paired outcomes, PSU ids and weights must be equal length")
    for outcomes in (outcomes_a, outcomes_b):
        if any(
            not isinstance(o, fc.FaceOutcome) or o in (fc.FaceOutcome.false_accept, fc.FaceOutcome.correct_reject)
            for o in outcomes
        ):
            raise fc.FrameContractError("paired inference requires explicit mated FaceOutcome values")
    if any(not isinstance(psu, str) or not psu.strip() for psu in psu_of):
        raise fc.FrameContractError("every mated face needs a non-empty PSU id")
    if weights is not None and any(
        isinstance(w, (bool, np.bool_))
        or not isinstance(w, (int, float, np.integer, np.floating))
        or not math.isfinite(w)
        or w <= 0
        for w in weights
    ):
        raise fc.FrameContractError("weights must be positive finite numbers aligned with the faces")
    return np.ones(n) if weights is None else np.asarray(weights, dtype=float)


def paired_cluster_bootstrap(
    outcomes_a: Sequence[fc.FaceOutcome],
    outcomes_b: Sequence[fc.FaceOutcome],
    psu_of: Sequence[str],
    *,
    n_boot: int,
    seed: int,
    level: float,
    weights: Sequence[float] | None = None,
) -> PairedInterval:
    """Percentile interval for delta = FNIR(a) - FNIR(b) on the same mated faces, resampling PSUs.

    A face's miss is any outcome other than ``correct``. Weights default to 1. The observed ICC is the
    one-way ANOVA ICC of the paired contrast over PSUs; it is null when the contrast has no variance.
    It never changes n_eff, which uses the manifest planning ICC.
    """
    if isinstance(n_boot, (bool, np.bool_)) or not isinstance(n_boot, (int, np.integer)) or n_boot <= 0:
        raise fc.FrameContractError("n_boot must be a positive integer")
    if isinstance(seed, (bool, np.bool_)) or not isinstance(seed, (int, np.integer)) or seed < 0:
        raise fc.FrameContractError("seed must be a non-negative integer")
    if (
        isinstance(level, (bool, np.bool_))
        or not isinstance(level, (int, float, np.integer, np.floating))
        or not 0.0 < level < 1.0
    ):
        raise fc.FrameContractError(f"interval level must be in (0, 1), got {level!r}")
    n = len(outcomes_a)
    if n == 0:
        raise fc.FrameContractError("paired outcomes must be non-empty")
    w = _validate_mated_inputs(outcomes_a, outcomes_b, psu_of, weights)
    miss_a = np.array([o is not fc.FaceOutcome.correct for o in outcomes_a], dtype=float)
    miss_b = np.array([o is not fc.FaceOutcome.correct for o in outcomes_b], dtype=float)
    psus, codes = np.unique(np.asarray(list(psu_of), dtype=str), return_inverse=True)
    k = len(psus)
    if np.max(w) > np.finfo(float).max / n / k:
        # Extended sums keep even extreme finite face weights and repeated large PSUs finite.
        diff_sum = np.zeros(k, dtype=np.longdouble)
        weight_sum = np.zeros(k, dtype=np.longdouble)
        np.add.at(diff_sum, codes, w.astype(np.longdouble) * (miss_a - miss_b))
        np.add.at(weight_sum, codes, w.astype(np.longdouble))
    else:
        diff_sum = np.bincount(codes, weights=w * (miss_a - miss_b), minlength=k)
        weight_sum = np.bincount(codes, weights=w, minlength=k)
    delta = float(diff_sum.sum() / weight_sum.sum())
    rng = np.random.default_rng(seed)
    deltas = np.empty(n_boot)
    # Consecutive rows consume the same RNG draws as the literal per-replicate loop.
    # Gather fixed face-weighted PSU sufficient statistics, never average PSU rates.
    # Bound temporary arrays even for large galleries (one PSU draw is the minimum).
    chunk_size = max(1, min(n_boot, 262144 // k))
    for start in range(0, n_boot, chunk_size):
        stop = min(start + chunk_size, n_boot)
        draws = rng.integers(0, k, size=(stop - start, k))
        deltas[start:stop] = np.sum(diff_sum[draws], axis=1) / np.sum(weight_sum[draws], axis=1)
    tail = (1.0 - level) / 2.0
    lower, upper = (float(x) for x in np.quantile(deltas, [tail, 1.0 - tail]))
    return PairedInterval(
        delta=delta,
        lower=lower,
        upper=upper,
        n_psu=k,
        icc=_observed_icc(miss_a - miss_b, codes, k),
        level=level,
        n_boot=n_boot,
        seed=seed,
    )


def _observed_icc(contrast: np.ndarray, codes: np.ndarray, k: int) -> float | None:
    n = contrast.size
    if n == 0 or k < 2 or k >= n or np.all(contrast == contrast[0]):
        return None
    sizes = np.bincount(codes, minlength=k).astype(float)
    means = np.bincount(codes, weights=contrast, minlength=k) / sizes
    grand = contrast.mean()
    msb = float(np.sum(sizes * (means - grand) ** 2) / (k - 1))
    msw = float(np.sum((contrast - means[codes]) ** 2) / (n - k))
    m0 = (n - float(np.sum(sizes**2)) / n) / (k - 1)
    denominator = msb + (m0 - 1.0) * msw
    return None if denominator <= 0 else (msb - msw) / denominator


# --- minimum detectable effect and step levels ---------------------------------------------


def minimum_detectable_effect(*, n_eff: float, p_d: float, power: float, one_sided_alpha: float) -> float | None:
    """Smallest Delta > 0 with n_required(Delta) <= n_eff, using the scope § Power formula.

    n_required(Delta) = [z_a * sqrt(p_d) + z_b * sqrt(p_d - Delta^2)]^2 / Delta^2, with z_a the one-sided
    quantile at ``one_sided_alpha`` and z_b the quantile at manifest ``power``. Returns None when no
    Delta in (0, sqrt(p_d)) reaches n_eff. This is design sensitivity, not the practical margin.
    """
    if not (0.0 < p_d < 1.0 and 0.0 < power < 1.0 and 0.0 < one_sided_alpha < 0.5):
        raise fc.FrameContractError("p_d and power in (0, 1), and one-sided alpha in (0, 0.5), are required")
    if not math.isfinite(n_eff):
        raise fc.FrameContractError("n_eff must be finite")
    if n_eff <= 0:
        return None
    z_a = NormalDist().inv_cdf(1.0 - one_sided_alpha)
    z_b = NormalDist().inv_cdf(power)
    root = math.sqrt(p_d)

    def required(delta: float) -> float:
        return ((z_a * root + z_b * math.sqrt(p_d - delta * delta)) / delta) ** 2

    high = root * (1.0 - 1e-12)
    if required(high) > n_eff:
        return None
    low = 1e-12
    for _ in range(200):
        mid = (low + high) / 2.0
        if required(mid) > n_eff:
            low = mid
        else:
            high = mid
    return high


def _one_sided_alpha(manifest: fc.DecisionManifest, step_index: int) -> float:
    total = len(manifest.hypotheses)
    return manifest.alpha_family / (total - step_index + 1)


def step_levels(manifest: fc.DecisionManifest) -> tuple[float, ...]:
    """Two-sided interval level per Holm step: 1 - 2 * one-sided alpha_k, with alpha_k = alpha / (K - k + 1)."""
    return tuple(1.0 - 2.0 * _one_sided_alpha(manifest, k) for k in range(1, len(manifest.hypotheses) + 1))


# --- design sizes -------------------------------------------------------------------------


def _design_effect(psu_ids: Sequence[str], planning_icc: float) -> float:
    sizes = list(Counter(psu_ids).values())
    total = sum(sizes)
    mean_cluster = sum(m * m for m in sizes) / total
    return 1.0 + (mean_cluster - 1.0) * planning_icc


def _n_eff(psu_ids: Sequence[str], planning_icc: float) -> float:
    if not psu_ids:
        return 0.0
    return len(psu_ids) / _design_effect(psu_ids, planning_icc)


# --- verdict ------------------------------------------------------------------------------


def _paired(
    results: LegResults, a: fc.LegKind, b: fc.LegKind
) -> tuple[list[str], list[fc.FaceOutcome], list[fc.FaceOutcome], list[str], list[float]]:
    if a not in results.legs or b not in results.legs:
        raise fc.FrameContractError(f"results lack a leg needed for the paired comparison {a} vs {b}")
    left, right = results.legs[a], results.legs[b]
    if left.leg is not a or right.leg is not b:
        raise fc.FrameContractError("paired leg keys must match their declared leg arrays")
    if set(left.face_ids) != set(right.face_ids):
        raise fc.FrameContractError("paired native legs must contain exactly the same mated GT face ids")
    right_index = {face: i for i, face in enumerate(right.face_ids)}
    faces: list[str] = []
    out_a: list[fc.FaceOutcome] = []
    out_b: list[fc.FaceOutcome] = []
    psus: list[str] = []
    weights: list[float] = []
    for i, face in enumerate(left.face_ids):
        j = right_index[face]
        if left.psu_ids[i] != right.psu_ids[j]:
            raise fc.FrameContractError(f"face {face} carries different PSU ids in the two legs")
        if left.weights[i] != right.weights[j]:
            raise fc.FrameContractError(f"face {face} carries different weights in the two legs")
        faces.append(face)
        out_a.append(left.outcomes[i])
        out_b.append(right.outcomes[j])
        psus.append(left.psu_ids[i])
        weights.append(left.weights[i])
    return faces, out_a, out_b, psus, weights


def _check_h2_leg(manifest: fc.DecisionManifest, results: LegResults) -> None:
    for hypothesis in manifest.hypotheses:
        if hypothesis.kind is not fc.HypothesisKind.non_inferiority:
            continue
        in_house = [leg for leg in hypothesis.legs if leg in (fc.LegKind.sface, fc.LegKind.auraface)]
        if len(in_house) != 1:
            raise fc.UndeclaredH2LegError("the sealed H2 names no single in-house leg")
        declared = in_house[0]
        if results.h2_leg is not declared:
            raise fc.UndeclaredH2LegError(
                f"results were built for {results.h2_leg} but the sealed H2 leg is {declared}"
            )
        for leg in hypothesis.legs:
            if leg not in results.legs:
                raise fc.UndeclaredH2LegError(f"results lack the H2 leg {leg}")


def decide(manifest: fc.DecisionManifest, results: LegResults) -> Verdict:
    """The only verdict rule: step-down over the manifest hypotheses on paired PSU-cluster intervals.

    Order: ratification (numbers only), PSU floor, primary FPIR resolvability, unscored veto guardrails,
    then per step the veto, MDE gate (H2 only), and the step-level bound. Stop at the first non-rejection.
    """
    _check_h2_leg(manifest, results)
    frame = results.frame
    try:
        fc.require_verdict_allowed(manifest, frame=frame)
        ratified = True
    except fc.UnratifiedDecisionError:
        ratified = False
    levels = step_levels(manifest)
    planning_icc = manifest.planning_icc
    if planning_icc is None:
        raise fc.FrameContractError("planning_icc is required to size the verdict")
    psu_pool: set[str] = set(results.unit_psu_ids)
    for leg_arrays in results.legs.values():
        psu_pool.update(leg_arrays.psu_ids)
    n_nonmated_eff = _n_eff(results.unit_psu_ids, planning_icc)
    resolvable = fpir_resolvable(manifest.primary.fpir_target, n_nonmated_eff)
    veto_ids = [g.id for g in manifest.guardrails if g.role is fc.GuardrailRole.veto]
    unscored = [
        gid
        for gid in veto_ids
        if gid not in results.guardrails
        or results.guardrails[gid].state not in (GuardrailState.pass_, GuardrailState.fail)
        or results.guardrails[gid].value is None
        or not math.isfinite(results.guardrails[gid].value)
    ]
    failing = [
        gid for gid in veto_ids if gid in results.guardrails and results.guardrails[gid].state is GuardrailState.fail
    ]

    sizes: list[
        tuple[
            fc.Hypothesis,
            list[str],
            list[fc.FaceOutcome],
            list[fc.FaceOutcome],
            list[str],
            list[float],
            float,
            float | None,
        ]
    ] = []
    for hypothesis in manifest.hypotheses:
        faces, out_a, out_b, psus, weights = _paired(results, hypothesis.legs[0], hypothesis.legs[1])
        n_eff = _n_eff(psus, planning_icc)
        mde = minimum_detectable_effect(
            n_eff=n_eff,
            p_d=manifest.p_d,
            power=manifest.power,
            one_sided_alpha=_one_sided_alpha(manifest, _step_index(manifest, hypothesis)),
        )
        sizes.append((hypothesis, faces, out_a, out_b, psus, weights, n_eff, mde))

    path: list[str] = []
    states: dict[str, tuple[fc.VerdictState | None, fc.InconclusiveReason | None, PairedInterval | None]] = {}
    if not ratified:
        # Numbers only: no interval is read and no hypothesis names a winner.
        path.append("unratified:numbers_only")
        for hypothesis, *_ in sizes:
            states[hypothesis.id] = (None, None, None)
        return _assemble(manifest, frame, (fc.VerdictState.unratified, None), states, sizes, levels, path)
    gate_reason: fc.InconclusiveReason | None = None
    if len(psu_pool) < manifest.min_n_independent:
        gate_reason = fc.InconclusiveReason.insufficient_independent_psus
    elif not resolvable:
        gate_reason = fc.InconclusiveReason.primary_fpir_unresolvable
    elif unscored:
        gate_reason = fc.InconclusiveReason.required_guardrail_unscored
    if gate_reason is not None:
        path.append(f"eligibility:{gate_reason.value}")
        for hypothesis, *_ in sizes:
            states[hypothesis.id] = (fc.VerdictState.inconclusive, gate_reason, None)
        return _assemble(manifest, frame, (fc.VerdictState.inconclusive, gate_reason), states, sizes, levels, path)

    path.append("eligibility:passed")
    for step, (hypothesis, _faces, out_a, out_b, psus, weights, _size_n_eff, mde) in enumerate(sizes, start=1):
        if failing:
            states[hypothesis.id] = (fc.VerdictState.guardrail_vetoed, None, None)
            path.append(f"{hypothesis.id}:guardrail_vetoed")
            break
        interval = paired_cluster_bootstrap(
            out_a,
            out_b,
            psus,
            n_boot=_required(manifest.interval.n_boot, "interval.n_boot"),
            seed=_required(manifest.interval.seed, "interval.seed"),
            level=levels[step - 1],
            weights=weights,
        )
        if hypothesis.kind is fc.HypothesisKind.non_inferiority and (mde is None or mde > hypothesis.margin):
            states[hypothesis.id] = (
                fc.VerdictState.inconclusive,
                fc.InconclusiveReason.margin_unreachable_mde_gt_delta,
                interval,
            )
            path.append(f"{hypothesis.id}:margin_unreachable")
            break
        if hypothesis.kind is fc.HypothesisKind.superiority:
            rejected = interval.lower > hypothesis.margin
            won: fc.VerdictState | None = fc.VerdictState.superior
        else:
            rejected = interval.upper < hypothesis.margin
            won = fc.VerdictState.non_inferior if frame.admissibility is fc.Admissibility.confirmatory else None
        if rejected and won is not None:
            states[hypothesis.id] = (won, None, interval)
            path.append(f"{hypothesis.id}:rejected")
            continue  # the Holm step-down continues to the next hypothesis
        if rejected:
            states[hypothesis.id] = (
                fc.VerdictState.inconclusive,
                fc.InconclusiveReason.non_confirmatory_frame,
                interval,
            )
            path.append(f"{hypothesis.id}:non_confirmatory_frame")
            break
        states[hypothesis.id] = (fc.VerdictState.inconclusive, None, interval)
        path.append(f"{hypothesis.id}:not_rejected")
        break  # stop at the first non-rejection; later hypotheses have no state
    return _assemble(manifest, frame, None, states, sizes, levels, path)


def _step_index(manifest: fc.DecisionManifest, hypothesis: fc.Hypothesis) -> int:
    for index, entry in enumerate(manifest.hypotheses, start=1):
        if entry.id == hypothesis.id:
            return index
    raise fc.FrameContractError(f"hypothesis {hypothesis.id!r} is not in the manifest")


def _required(value: int | None, name: str) -> int:
    if value is None:
        raise fc.FrameContractError(f"{name} must be set on a sealed manifest")
    return value


def _assemble(
    manifest: fc.DecisionManifest,
    frame: fc.FrameSpec,
    overall: tuple[fc.VerdictState, fc.InconclusiveReason | None] | None,
    states: Mapping[str, tuple[fc.VerdictState | None, fc.InconclusiveReason | None, PairedInterval | None]],
    sizes: Sequence[Any],
    levels: Sequence[float],
    path: Sequence[str],
) -> Verdict:
    rows: list[HypothesisVerdict] = []
    for step, (hypothesis, _f, _a, _b, _p, _w, n_eff, mde) in enumerate(sizes, start=1):
        state, reason, interval = states.get(hypothesis.id, (None, None, None))
        rows.append(
            HypothesisVerdict(
                id=hypothesis.id,
                kind=hypothesis.kind,
                step_index=step,
                one_sided_alpha=_one_sided_alpha(manifest, step),
                level=levels[step - 1],
                n_eff=n_eff,
                mde=mde,
                interval=interval,
                state=state,
                reason=reason,
            )
        )
    if overall is None:
        overall = _overall_from(rows)
    return Verdict(
        frame_id=frame.frame_id,
        state=overall[0],
        reason=overall[1],
        hypotheses=tuple(rows),
        decision_path=tuple(path),
    )


def _overall_from(rows: Sequence[HypothesisVerdict]) -> tuple[fc.VerdictState, fc.InconclusiveReason | None]:
    if any(row.state is fc.VerdictState.non_inferior for row in rows):
        return fc.VerdictState.non_inferior, None
    if rows and rows[0].state is fc.VerdictState.superior:
        return fc.VerdictState.superior, None
    for row in rows:
        if row.state is not None:
            return row.state, row.reason
    return fc.VerdictState.inconclusive, None


__all__ = [
    "ICC_SENSITIVITY_ROWS",
    "CurvePoint",
    "FpirBound",
    "GuardrailReading",
    "GuardrailState",
    "HypothesisVerdict",
    "LegArrays",
    "LegResults",
    "PairedInterval",
    "Verdict",
    "calibrate_tau",
    "clopper_pearson_upper",
    "curve",
    "decide",
    "excluded_by_arm",
    "finish_outcomes",
    "fpir_resolvable",
    "fpir_upper_bound",
    "minimum_detectable_effect",
    "paired_cluster_bootstrap",
    "step_levels",
]
