"""FIRBENCH-1 shared contract (S0): names, errors, decision manifest and frame-read gate.

Every other FIRBENCH-1 slice imports its enums, errors and binding values from
here. Binding values (tau, FPIR targets, margins, alpha, floors, seeds, p_d,
power) live in ``benchmarks/manifests/fir-bench-decision-v1.json`` and never in
this module [rg-009]. The manifest is validated at load time and unknown or
missing keys fail fast [rg-008]. Validation raises the named ``FirBenchError``
subclasses, not ``assert`` [sr-006], and states are ``StrEnum`` members [sr-007].

Two gates are kept apart. ``require_verdict_allowed`` gates printing a verdict
(ratified and sealed). ``require_frame_read_allowed`` gates reading a sealed
frame and only an unspent unseal token opens it (EXP-22, EVAL-07).
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import functools
import hashlib
import json
import math
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

__all__ = [
    "Admissibility",
    "Arm",
    "ArmStatus",
    "AlignmentMode",
    "BoundarySemantics",
    "DecisionManifest",
    "Disconfirmer",
    "FaceOutcome",
    "FirBenchError",
    "FoldProtocol",
    "FoldRole",
    "FrameSpec",
    "GalleryLineage",
    "Guardrail",
    "GuardrailRole",
    "Hypothesis",
    "HypothesisDirection",
    "HypothesisKind",
    "IdentityStatus",
    "IntervalMethod",
    "IntervalSpec",
    "InconclusiveReason",
    "LegId",
    "LegKind",
    "Multiplicity",
    "PsuKind",
    "Primary",
    "Ratification",
    "SamplingArm",
    "Seal",
    "SearchStage",
    "UnsealToken",
    "VerdictState",
    "load_decision_manifest",
    "manifest_sha256",
    "require_frame_read_allowed",
    "require_private_output_path",
    "require_verdict_allowed",
    "seal",
    "validate_interchange",
]


# --- errors -----------------------------------------------------------------


class FirBenchError(Exception):
    """Base class for every FIRBENCH-1 contract error."""


class UnratifiedDecisionError(FirBenchError):
    """A verdict needs a ratified, matching seal with resolved input evidence [EXP-22]."""


class SealedFrameReadError(FirBenchError):
    """A sealed input is read without an unspent token for that frame, decision and run [EXP-22, EVAL-07]."""


class CrossSpaceComparisonError(FirBenchError):
    """A vector operation spans two embedding spaces [EMB-01]."""


class RuntimeMismatchError(FirBenchError):
    """OpenCV or ORT versions differ within one leg kind, or a cache key does not match its file."""


class CalibrationLeakError(FirBenchError):
    """A calibration fit uses a probe or gallery identity from a test fold [CAL-07]."""


class NonPrivateOutputError(FirBenchError):
    """An image-bearing or run output path resolves outside ``benchmarks/private/``."""


class ProjectionLeakError(FirBenchError):
    """Projection coordinates are passed to a metric."""


class LinkageMetricError(FirBenchError):
    """Ward, median or centroid linkage is requested on cosine distance."""


class CanaryInSealedRunError(FirBenchError):
    """A canary leg is requested on a sealed frame (AE-5)."""


class CanaryConfigError(FirBenchError):
    """A canary declares fewer than two identities, or its permutation leaves a selected label fixed (AE-5)."""


class FrameContractError(FirBenchError):
    """A frame loader, manifest or interchange payload is missing or malformed [rg-008]."""


class TauInfeasibleError(FirBenchError):
    """The calibration pool is empty, so no threshold can be chosen [CAL-07]."""


class UndeclaredH2LegError(FirBenchError):
    """Results lack the H2 leg named in the sealed manifest, or carry another in-house leg as H2 [EXP-10]."""


# --- shared enums -----------------------------------------------------------


class Admissibility(StrEnum):
    """Frame admissibility, from the frame registry. Confirmatory needs sealed, unexamined frames [EXP-22]."""

    diagnostic = "diagnostic"
    development = "development"
    confirmatory = "confirmatory"


class VerdictState(StrEnum):
    """Printed verdict state. ``inconclusive`` is never a win when an interval spans the boundary [EXP-24]."""

    superior = "superior"
    non_inferior = "non_inferior"
    inconclusive = "inconclusive"
    guardrail_vetoed = "guardrail_vetoed"
    unratified = "unratified"


class InconclusiveReason(StrEnum):
    """Reason for an inconclusive state. Set only together with ``inconclusive`` [CARD-03]."""

    primary_fpir_unresolvable = "primary_fpir_unresolvable"
    required_guardrail_unscored = "required_guardrail_unscored"
    margin_unreachable_mde_gt_delta = "margin_unreachable_mde_gt_delta"
    non_confirmatory_frame = "non_confirmatory_frame"
    insufficient_independent_psus = "insufficient_independent_psus"


class FaceOutcome(StrEnum):
    """Final outcome of one record. Set only by S3 ``finish_outcomes``, never a stage [EVAL-19].

    Mated faces take the first five members. A fused-leg ``detected`` stage finishes as ``missed``.
    Non-mated source units take the last two.
    """

    missed = "missed"
    unaligned = "unaligned"
    wrong_identity = "wrong_identity"
    rejected = "rejected"
    correct = "correct"
    false_accept = "false_accept"
    correct_reject = "correct_reject"


class BoundarySemantics(StrEnum):
    """Acceptance boundary. ``legacy_v1`` is for historical parity only (AE-6); ``v2`` is the decision mode."""

    legacy_v1 = "legacy_v1"
    v2 = "v2"


class Arm(StrEnum):
    """Pipeline arm: how the probe reaches the leg [EMB-01]. Not the sampling arm."""

    native = "native"
    gt_crop_redetect = "gt_crop_redetect"
    cached_yunet_landmark_replay = "cached_yunet_landmark_replay"


class ArmStatus(StrEnum):
    """Written to ``arm_availability``. ``unavailable`` never falls back to another arm."""

    available = "available"
    unavailable = "unavailable"
    unavailable_fused = "unavailable_fused"


class SearchStage(StrEnum):
    """Furthest stage a GT face reached in one (leg, arm) row. Fused legs never write ``unaligned``."""

    missed = "missed"
    detected = "detected"
    unaligned = "unaligned"
    embedded = "embedded"
    unavailable = "unavailable"


class IdentityStatus(StrEnum):
    """Identity status on every GT face. Only ``named`` held-out and exhaustive ``unknown`` faces are non-mated [EVAL-19]."""

    named = "named"
    unknown = "unknown"
    unresolved = "unresolved"


class SamplingArm(StrEnum):
    """Sampling arm of an image unit. The probability and challenge arms are reported separately and never pooled."""

    probability = "probability"
    challenge = "challenge"


class FoldRole(StrEnum):
    """Role of a fold in the identity-disjoint rotation [CAL-07]."""

    fit = "fit"
    test = "test"


class AlignmentMode(StrEnum):
    """Whether a leg aligns faces itself or the leg aligns inside one call."""

    separable = "separable"
    fused_internal = "fused_internal"


class LegKind(StrEnum):
    """Embedding leg. InsightFace is a judge-side reference leg only."""

    sface = "sface"
    auraface = "auraface"
    insightface = "insightface"
    canary = "canary"


class HypothesisKind(StrEnum):
    """Holm hypothesis kind. Superiority needs a lower bound above the margin [EXP-10, EXP-24]."""

    superiority = "superiority"
    non_inferiority = "non_inferiority"


class HypothesisDirection(StrEnum):
    """Which bound of the paired first-minus-second difference is tested against the margin."""

    lower_bound_above_margin = "lower_bound_above_margin"
    upper_bound_below_margin = "upper_bound_below_margin"


class GuardrailRole(StrEnum):
    """``veto`` gates the verdict; ``report_only`` is written and never gates. The per-cohort FPIR veto names the dominant harm, a false match [FAIR-04]."""

    veto = "veto"
    report_only = "report_only"


class IntervalMethod(StrEnum):
    """Interval method. Paired cluster percentile bootstrap [EXP-24]."""

    paired_cluster_bootstrap = "paired_cluster_bootstrap"


class PsuKind(StrEnum):
    """Primary sampling unit for resampling: image-identity component [AUDIT-11]."""

    image_identity_component = "image_identity_component"


class Multiplicity(StrEnum):
    """Fixed-order step-down over the hypotheses [EXP-10]."""

    holm = "holm"


# Legs that count as in-house for H2. InsightFace is the reference, never in-house.
_IN_HOUSE_LEGS = frozenset({LegKind.sface, LegKind.auraface})
_REFERENCE_LEG = LegKind.insightface
_COMPARISON_LEGS = (LegKind.sface, LegKind.auraface)


# --- leg and frame records ----------------------------------------------------

_SAFE_TOKEN = re.compile(r"^(?!.*__)[A-Za-z0-9][A-Za-z0-9._+-]*$")
_FRAME_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MAX_SEED = 2**32


@dataclass(frozen=True)
class LegId:
    """Identity of one leg. Vectors compare only within one ``space_fingerprint`` [EMB-01]."""

    kind: LegKind
    arm: Arm
    space_fingerprint: str
    opencv_version: str
    ort_version: str

    def __post_init__(self) -> None:
        for name in ("space_fingerprint", "opencv_version", "ort_version"):
            _require_safe_token(getattr(self, name), name)

    def key(self) -> str:
        """Stable, path-safe key used for ``legs/<leg_key>/`` directories."""
        return (
            f"{LegKind(self.kind).value}__{Arm(self.arm).value}__{self.space_fingerprint}"
            f"__cv{self.opencv_version}__ort{self.ort_version}"
        )


@dataclass(frozen=True)
class FrameSpec:
    """One registry entry. ``source_sha256`` and ``exhaustive`` stay null until measured [EXP-22]."""

    frame_id: str
    admissibility: Admissibility
    sealed: bool
    source_sha256: str | None
    exhaustive: bool | None

    def __post_init__(self) -> None:
        if not isinstance(self.frame_id, str) or not _FRAME_ID.match(self.frame_id):
            raise FrameContractError(f"frame_id {self.frame_id!r} is not a safe identifier")
        if not isinstance(self.admissibility, Admissibility):
            raise FrameContractError(f"frame {self.frame_id}: admissibility must be an Admissibility member")
        if not isinstance(self.sealed, bool):
            raise FrameContractError(f"frame {self.frame_id}: sealed must be a boolean")
        _require_optional_sha(self.source_sha256, f"frame {self.frame_id}.source_sha256")
        if self.exhaustive is not None and not isinstance(self.exhaustive, bool):
            raise FrameContractError(f"frame {self.frame_id}: exhaustive must be a boolean or null")


@dataclass(frozen=True)
class UnsealToken:
    """Authority to read one sealed frame once, for one decision, run, code and scorer [EVAL-07].

    ``consumed_at`` is null until the first sealed read. ``run_id`` is the basename of the run directory.
    """

    frame_id: str
    frame_sha256: str
    decision_sha256: str
    run_id: str
    code_sha: str
    scorer_sha: str
    consumed_at: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.frame_id, str) or not _FRAME_ID.match(self.frame_id):
            raise FrameContractError(f"token frame_id {self.frame_id!r} is not a safe identifier")
        _require_sha(self.frame_sha256, "token.frame_sha256")
        _require_sha(self.decision_sha256, "token.decision_sha256")
        _require_basename(self.run_id, "token.run_id")
        _require_safe_token(self.code_sha, "token.code_sha")
        _require_safe_token(self.scorer_sha, "token.scorer_sha")
        if self.consumed_at is not None:
            _require_timestamp(self.consumed_at, "token.consumed_at")


# --- decision manifest records ------------------------------------------------


@dataclass(frozen=True)
class FoldProtocol:
    """Identity-disjoint rotating folds [CAL-07]. Null until the seed is declared."""

    k: int | None
    seed: int | None


@dataclass(frozen=True)
class GalleryLineage:
    """Gallery split seed and the template file it was built from [EVAL-07]."""

    split_seed: int | None
    templates_sha256: str | None


@dataclass(frozen=True)
class Primary:
    """Primary estimand. Comparison is ``(first, second)`` and the difference is first minus second."""

    estimand: str
    comparison: tuple[LegKind, LegKind]
    fpir_target: float
    end_to_end: bool


@dataclass(frozen=True)
class Hypothesis:
    """One Holm step. List order is the step order S3 follows [EXP-10]."""

    id: str
    kind: HypothesisKind
    legs: tuple[LegKind, LegKind]
    margin: float
    direction: HypothesisDirection


@dataclass(frozen=True)
class IntervalSpec:
    """Paired cluster percentile bootstrap. No level field: levels follow from ``alpha_family`` [EXP-24]."""

    method: IntervalMethod
    psu: PsuKind
    n_boot: int | None
    seed: int | None


@dataclass(frozen=True)
class Guardrail:
    """A guardrail with its role. ``rule`` stays null until the operator ratifies a threshold."""

    id: str
    metric: str
    rule: str | None
    cohort_scope: str
    role: GuardrailRole


@dataclass(frozen=True)
class Disconfirmer:
    """A dated condition under which the result is downgraded to exploratory [EXP-22]."""

    id: str
    statement: str
    review_date: str


@dataclass(frozen=True)
class Ratification:
    """Operator ratification. Both fields are null until the operator ratifies."""

    decision_ref: str | None
    ratified_at: str | None


@dataclass(frozen=True)
class Seal:
    """Seal over the manifest body, excluding this block. ``sealed_at`` is an explicit literal, never a clock read."""

    sealed_at: str
    sha256: str


@dataclass(frozen=True)
class DecisionManifest:
    """The sealed decision. Binding values only; the gate contract is referenced by path and sha, never copied."""

    decision_id: str
    schema_version: int
    gate_contract_path: str
    gate_contract_sha256: str
    planning_icc: float | None
    p_d: float
    power: float
    fold_protocol: FoldProtocol
    gallery_lineage: GalleryLineage
    primary: Primary
    secondary_fpir_targets: tuple[float, ...]
    hypotheses: tuple[Hypothesis, ...]
    alpha_family: float
    multiplicity: Multiplicity
    interval: IntervalSpec
    min_n_independent: int
    cell_floor_n_independent: int
    guardrails: tuple[Guardrail, ...]
    boundary_semantics: BoundarySemantics
    frames: tuple[FrameSpec, ...]
    disconfirmers: tuple[Disconfirmer, ...]
    ratification: Ratification
    seal: Seal | None

    def frame(self, frame_id: str) -> FrameSpec:
        """Return the registry entry for ``frame_id``, or refuse an unknown frame."""
        for entry in self.frames:
            if entry.frame_id == frame_id:
                return entry
        raise FrameContractError(f"frame {frame_id!r} is not in the decision frame registry")


# --- shared validators ---------------------------------------------------------


def _require_safe_token(value: object, name: str) -> str:
    if not isinstance(value, str) or not _SAFE_TOKEN.match(value):
        raise FrameContractError(f"{name} must be a path-safe identifier, got {value!r}")
    return value


def _require_sha(value: object, name: str) -> str:
    if not isinstance(value, str) or not _SHA256.match(value):
        raise FrameContractError(f"{name} must be a lowercase 64-character sha256")
    return value


def _require_optional_sha(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _require_sha(value, name)


def _require_basename(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or value in {".", ".."} or "/" in value or "\\" in value:
        raise FrameContractError(f"{name} must be a run directory basename")
    return value


def _require_timestamp(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise FrameContractError(f"{name} must be an ISO 8601 timestamp string")
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError as exc:
        raise FrameContractError(f"{name} must be an ISO 8601 timestamp: {exc}") from exc
    if parsed.tzinfo is None:
        raise FrameContractError(f"{name} must carry a timezone offset")
    return value


# --- canonical hash --------------------------------------------------------------


def _to_plain(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {field.name: _to_plain(getattr(value, field.name)) for field in dataclasses.fields(value)}
    if isinstance(value, (tuple, list)):
        return [_to_plain(item) for item in value]
    return value


def manifest_sha256(manifest: DecisionManifest) -> str:
    """Hash the canonical JSON of the manifest body, excluding the ``seal`` block [EVAL-07]."""
    body = _to_plain(manifest)
    body.pop("seal", None)
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


# --- manifest loading --------------------------------------------------------------

_TOP_KEYS = frozenset(
    {
        "decision_id",
        "schema_version",
        "gate_contract_path",
        "gate_contract_sha256",
        "planning_icc",
        "p_d",
        "power",
        "fold_protocol",
        "gallery_lineage",
        "primary",
        "secondary_fpir_targets",
        "hypotheses",
        "alpha_family",
        "multiplicity",
        "interval",
        "min_n_independent",
        "cell_floor_n_independent",
        "guardrails",
        "boundary_semantics",
        "frames",
        "disconfirmers",
        "ratification",
        "seal",
    }
)


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise FrameContractError(f"duplicate key {key!r} in decision manifest")
        result[key] = value
    return result


def _reject_non_finite(name: str) -> object:
    raise FrameContractError(f"non-finite JSON constant {name!r} in decision manifest")


def _mapping(value: object, name: str, keys: frozenset[str]) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise FrameContractError(f"{name} must be an object")
    unknown = set(value) - keys
    if unknown:
        raise FrameContractError(f"{name} has unknown keys {sorted(unknown)}")
    missing = keys - set(value)
    if missing:
        raise FrameContractError(f"{name} is missing required keys {sorted(missing)}")
    return value


def _list(value: object, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise FrameContractError(f"{name} must be a list")
    return value


def _text(value: object, name: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not value.strip():
        raise FrameContractError(f"{name} must be a non-empty string")
    return value


def _integer(
    value: object, name: str, *, minimum: int, maximum: int | None = None, nullable: bool = False
) -> int | None:
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise FrameContractError(f"{name} must be an integer")
    if value < minimum or (maximum is not None and value > maximum):
        raise FrameContractError(f"{name} is out of range")
    return value


def _number(
    value: object,
    name: str,
    *,
    low: float,
    high: float | None,
    nullable: bool = False,
    exclusive_low: bool = False,
) -> float | None:
    """Finite number in ``[low, high)``; ``exclusive_low`` makes the lower bound open (probabilities)."""
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise FrameContractError(f"{name} must be a finite number")
    below = value <= low if exclusive_low else value < low
    if below or (high is not None and value >= high):
        raise FrameContractError(f"{name} is out of range")
    return float(value)


def _probability(value: object, name: str, *, nullable: bool = False) -> float | None:
    """A rate or probability in the open interval (0, 1)."""
    return _number(value, name, low=0.0, high=1.0, nullable=nullable, exclusive_low=True)


def _enum(enum_cls: type[StrEnum], value: Any, name: str) -> Any:
    try:
        return enum_cls(value)
    except ValueError as exc:
        raise FrameContractError(f"{name} must be one of {[m.value for m in enum_cls]}") from exc


def _parse_fold_protocol(value: object) -> FoldProtocol:
    body = _mapping(value, "fold_protocol", frozenset({"k", "seed"}))
    return FoldProtocol(
        k=_integer(body["k"], "fold_protocol.k", minimum=2, nullable=True),
        seed=_integer(body["seed"], "fold_protocol.seed", minimum=0, maximum=_MAX_SEED - 1, nullable=True),
    )


def _parse_gallery(value: object) -> GalleryLineage:
    body = _mapping(value, "gallery_lineage", frozenset({"split_seed", "templates_sha256"}))
    split = _integer(body["split_seed"], "gallery_lineage.split_seed", minimum=0, maximum=_MAX_SEED - 1, nullable=True)
    templates = body["templates_sha256"]
    return GalleryLineage(
        split_seed=split, templates_sha256=_require_optional_sha(templates, "gallery_lineage.templates_sha256")
    )


def _parse_leg_pair(value: object, name: str) -> tuple[LegKind, LegKind]:
    items = _list(value, name)
    if len(items) != 2:
        raise FrameContractError(f"{name} must name exactly two legs")
    return (_enum(LegKind, items[0], f"{name}[0]"), _enum(LegKind, items[1], f"{name}[1]"))


def _parse_primary(value: object) -> Primary:
    body = _mapping(value, "primary", frozenset({"estimand", "comparison", "fpir_target", "end_to_end"}))
    comparison = _parse_leg_pair(body["comparison"], "primary.comparison")
    if comparison != _COMPARISON_LEGS:
        raise FrameContractError("primary.comparison must be [sface, auraface] with difference first minus second")
    if body["end_to_end"] is not True:
        raise FrameContractError("primary.end_to_end must be true")
    return Primary(
        estimand=_text(body["estimand"], "primary.estimand") or "",
        comparison=comparison,
        fpir_target=_probability(body["fpir_target"], "primary.fpir_target") or 0.0,
        end_to_end=True,
    )


def _parse_hypothesis(value: object, name: str) -> Hypothesis:
    body = _mapping(value, name, frozenset({"id", "kind", "legs", "margin", "direction"}))
    return Hypothesis(
        id=_text(body["id"], f"{name}.id") or "",
        kind=_enum(HypothesisKind, body["kind"], f"{name}.kind"),
        legs=_parse_leg_pair(body["legs"], f"{name}.legs"),
        margin=_number(body["margin"], f"{name}.margin", low=0.0, high=None) or 0.0,
        direction=_enum(HypothesisDirection, body["direction"], f"{name}.direction"),
    )


def _parse_hypotheses(value: object) -> tuple[Hypothesis, Hypothesis]:
    entries = _list(value, "hypotheses")
    if len(entries) != 2:
        raise FrameContractError("hypotheses must list H1 then H2")
    first = _parse_hypothesis(entries[0], "hypotheses[0]")
    second = _parse_hypothesis(entries[1], "hypotheses[1]")
    if first.kind is not HypothesisKind.superiority or first.legs != _COMPARISON_LEGS or first.margin != 0.0:
        raise FrameContractError("H1 must be superiority of [sface, auraface] with margin 0")
    if first.direction is not HypothesisDirection.lower_bound_above_margin:
        raise FrameContractError("H1 must test the lower bound above its margin")
    if second.kind is not HypothesisKind.non_inferiority:
        raise FrameContractError("H2 must be non_inferiority")
    in_house = [leg for leg in second.legs if leg in _IN_HOUSE_LEGS]
    if len(in_house) != 1:
        raise FrameContractError(f"H2 must name exactly one in-house leg, got {len(in_house)}")
    if second.legs[1] is not _REFERENCE_LEG:
        raise FrameContractError("H2 must compare the in-house leg against insightface")
    if second.margin <= 0.0:
        raise FrameContractError("H2 margin must be positive")
    if second.direction is not HypothesisDirection.upper_bound_below_margin:
        raise FrameContractError("H2 must test the upper bound below its margin")
    if first.id == second.id:
        raise FrameContractError("hypothesis ids must be unique")
    return (first, second)


def _parse_interval(value: object) -> IntervalSpec:
    body = _mapping(value, "interval", frozenset({"method", "psu", "n_boot", "seed"}))
    return IntervalSpec(
        method=_enum(IntervalMethod, body["method"], "interval.method"),
        psu=_enum(PsuKind, body["psu"], "interval.psu"),
        n_boot=_integer(body["n_boot"], "interval.n_boot", minimum=1, nullable=True),
        seed=_integer(body["seed"], "interval.seed", minimum=0, maximum=_MAX_SEED - 1, nullable=True),
    )


def _parse_guardrails(value: object) -> tuple[Guardrail, ...]:
    entries = _list(value, "guardrails")
    if not entries:
        raise FrameContractError("guardrails must not be empty")
    parsed: list[Guardrail] = []
    for index, entry in enumerate(entries):
        name = f"guardrails[{index}]"
        body = _mapping(entry, name, frozenset({"id", "metric", "rule", "cohort_scope", "role"}))
        parsed.append(
            Guardrail(
                id=_text(body["id"], f"{name}.id") or "",
                metric=_text(body["metric"], f"{name}.metric") or "",
                rule=_text(body["rule"], f"{name}.rule", nullable=True),
                cohort_scope=_text(body["cohort_scope"], f"{name}.cohort_scope") or "",
                role=_enum(GuardrailRole, body["role"], f"{name}.role"),
            )
        )
    if len({guardrail.id for guardrail in parsed}) != len(parsed):
        raise FrameContractError("guardrail ids must be unique")
    return tuple(parsed)


def _parse_frames(value: object) -> tuple[FrameSpec, ...]:
    entries = _list(value, "frames")
    parsed: list[FrameSpec] = []
    for index, entry in enumerate(entries):
        name = f"frames[{index}]"
        body = _mapping(entry, name, frozenset({"frame_id", "admissibility", "sealed", "source_sha256", "exhaustive"}))
        frame = FrameSpec(
            frame_id=str(body["frame_id"]),
            admissibility=_enum(Admissibility, body["admissibility"], f"{name}.admissibility"),
            sealed=_boolean(body["sealed"], f"{name}.sealed"),
            source_sha256=_require_optional_sha(body["source_sha256"], f"{name}.source_sha256"),
            exhaustive=None if body["exhaustive"] is None else _boolean(body["exhaustive"], f"{name}.exhaustive"),
        )
        if frame.admissibility is Admissibility.confirmatory and not frame.sealed:
            raise FrameContractError(f"confirmatory frame {frame.frame_id} must be sealed")
        parsed.append(frame)
    if len({frame.frame_id for frame in parsed}) != len(parsed):
        raise FrameContractError("frame ids must be unique in the registry")
    return tuple(parsed)


def _boolean(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise FrameContractError(f"{name} must be a boolean")
    return value


def _parse_disconfirmers(value: object) -> tuple[Disconfirmer, ...]:
    entries = _list(value, "disconfirmers")
    parsed: list[Disconfirmer] = []
    for index, entry in enumerate(entries):
        name = f"disconfirmers[{index}]"
        body = _mapping(entry, name, frozenset({"id", "statement", "review_date"}))
        review = _text(body["review_date"], f"{name}.review_date") or ""
        if not _ISO_DATE.match(review):
            raise FrameContractError(f"{name}.review_date must be YYYY-MM-DD")
        parsed.append(
            Disconfirmer(
                id=_text(body["id"], f"{name}.id") or "",
                statement=_text(body["statement"], f"{name}.statement") or "",
                review_date=review,
            )
        )
    return tuple(parsed)


def _parse_ratification(value: object) -> Ratification:
    body = _mapping(value, "ratification", frozenset({"decision_ref", "ratified_at"}))
    decision_ref = _text(body["decision_ref"], "ratification.decision_ref", nullable=True)
    ratified_at = body["ratified_at"]
    if (decision_ref is None) != (ratified_at is None):
        raise FrameContractError("ratification.decision_ref and ratified_at must be both set or both null")
    if ratified_at is not None:
        _require_timestamp(ratified_at, "ratification.ratified_at")
    return Ratification(decision_ref=decision_ref, ratified_at=ratified_at)


def _parse_seal(value: object) -> Seal | None:
    if value is None:
        return None
    body = _mapping(value, "seal", frozenset({"sealed_at", "sha256"}))
    return Seal(
        sealed_at=_require_timestamp(body["sealed_at"], "seal.sealed_at"),
        sha256=_require_sha(body["sha256"], "seal.sha256"),
    )


def _parse_manifest(payload: object) -> DecisionManifest:
    body = _mapping(payload, "decision manifest", _TOP_KEYS)
    if body["schema_version"] != 1 or isinstance(body["schema_version"], bool):
        raise FrameContractError("decision manifest schema_version must be 1")
    gate_path = _text(body["gate_contract_path"], "gate_contract_path") or ""
    if Path(gate_path).is_absolute():
        raise FrameContractError("gate_contract_path must be relative to the decision manifest directory")
    hypotheses = _parse_hypotheses(body["hypotheses"])
    alpha = _probability(body["alpha_family"], "alpha_family") or 0.0
    secondary = tuple(
        _probability(item, f"secondary_fpir_targets[{index}]") or 0.0
        for index, item in enumerate(_list(body["secondary_fpir_targets"], "secondary_fpir_targets"))
    )
    return DecisionManifest(
        decision_id=_text(body["decision_id"], "decision_id") or "",
        schema_version=1,
        gate_contract_path=gate_path,
        gate_contract_sha256=_require_sha(body["gate_contract_sha256"], "gate_contract_sha256"),
        planning_icc=_probability(body["planning_icc"], "planning_icc", nullable=True),
        p_d=_probability(body["p_d"], "p_d") or 0.0,
        power=_probability(body["power"], "power") or 0.0,
        fold_protocol=_parse_fold_protocol(body["fold_protocol"]),
        gallery_lineage=_parse_gallery(body["gallery_lineage"]),
        primary=_parse_primary(body["primary"]),
        secondary_fpir_targets=secondary,
        hypotheses=hypotheses,
        alpha_family=alpha,
        multiplicity=_enum(Multiplicity, body["multiplicity"], "multiplicity"),
        interval=_parse_interval(body["interval"]),
        min_n_independent=_integer(body["min_n_independent"], "min_n_independent", minimum=1) or 0,
        cell_floor_n_independent=_integer(body["cell_floor_n_independent"], "cell_floor_n_independent", minimum=1) or 0,
        guardrails=_parse_guardrails(body["guardrails"]),
        boundary_semantics=_enum(BoundarySemantics, body["boundary_semantics"], "boundary_semantics"),
        frames=_parse_frames(body["frames"]),
        disconfirmers=_parse_disconfirmers(body["disconfirmers"]),
        ratification=_parse_ratification(body["ratification"]),
        seal=_parse_seal(body["seal"]),
    )


def load_decision_manifest(path: str | os.PathLike[str]) -> DecisionManifest:
    """Load and validate the decision manifest. Null sealable fields load; ``seal`` refuses them.

    Verifies the sha256 of the gate-contract file that the manifest references by relative path.
    """
    manifest_path = Path(path)
    try:
        text = manifest_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise FrameContractError(f"cannot read decision manifest {manifest_path}: {exc}") from exc
    try:
        payload = json.loads(text, object_pairs_hook=_reject_duplicate_keys, parse_constant=_reject_non_finite)
    except json.JSONDecodeError as exc:
        raise FrameContractError(f"decision manifest {manifest_path} is not valid JSON: {exc}") from exc
    manifest = _parse_manifest(payload)
    gate_path = manifest_path.parent / manifest.gate_contract_path
    try:
        gate_bytes = gate_path.read_bytes()
    except OSError as exc:
        raise FrameContractError(f"cannot read gate contract {gate_path}: {exc}") from exc
    if hashlib.sha256(gate_bytes).hexdigest() != manifest.gate_contract_sha256:
        raise FrameContractError("gate_contract_sha256 does not match the gate contract file")
    return manifest


# --- sealing and the verdict gate ---------------------------------------------------


def _sealable_values(manifest: DecisionManifest) -> dict[str, object]:
    return {
        "planning_icc": manifest.planning_icc,
        "fold_protocol.k": manifest.fold_protocol.k,
        "fold_protocol.seed": manifest.fold_protocol.seed,
        "gallery_lineage.split_seed": manifest.gallery_lineage.split_seed,
        "gallery_lineage.templates_sha256": manifest.gallery_lineage.templates_sha256,
        "interval.n_boot": manifest.interval.n_boot,
        "interval.seed": manifest.interval.seed,
        **{
            f"frames[{frame.frame_id}].{name}": getattr(frame, name)
            for frame in manifest.frames
            for name in ("source_sha256", "exhaustive")
        },
    }


def seal(manifest: DecisionManifest, *, sealed_at: str) -> DecisionManifest:
    """Return a sealed copy whose ``seal.sha256`` is the hash of the unsealed body [EVAL-07].

    Refuses re-sealing and any null sealable field, including every included frame's
    measured source hash and exhaustiveness (MCP16733/16735). Nulls remain loadable;
    sealing cannot turn absent evidence into a pre-run commitment [EXP-22].
    ``sealed_at`` is supplied by the caller.
    """
    if manifest.seal is not None:
        raise FrameContractError("manifest is already sealed; re-sealing is refused")
    unresolved = [name for name, value in _sealable_values(manifest).items() if value is None]
    if unresolved:
        raise FrameContractError(f"cannot seal: unresolved fields {unresolved}")
    _require_timestamp(sealed_at, "sealed_at")
    return dataclasses.replace(manifest, seal=Seal(sealed_at=sealed_at, sha256=manifest_sha256(manifest)))


def require_verdict_allowed(manifest: DecisionManifest, *, frame: FrameSpec) -> None:
    """Gate a verdict on exhaustive evidence matching the sealed frame registry [EXP-22].

    Development frames remain usable for H1; S3 owns H2's confirmatory restriction.
    Does not authorise any read of a sealed frame; see ``require_frame_read_allowed``.
    """
    if frame.sealed and manifest.seal is None:
        raise SealedFrameReadError(f"sealed frame {frame.frame_id} cannot be read under an unsealed manifest")
    if manifest.ratification.decision_ref is None or manifest.ratification.ratified_at is None:
        raise UnratifiedDecisionError("the decision is not ratified")
    if manifest.seal is None:
        raise UnratifiedDecisionError("the decision is not sealed")
    if manifest.seal.sha256 != manifest_sha256(manifest):
        raise UnratifiedDecisionError("the seal hash does not match the manifest")
    unresolved = [name for name, value in _sealable_values(manifest).items() if value is None]
    if unresolved:
        raise UnratifiedDecisionError(f"the sealed decision has unresolved fields {unresolved}")
    if frame != manifest.frame(frame.frame_id):
        raise FrameContractError(f"frame {frame.frame_id} does not match the sealed decision frame registry")
    if frame.exhaustive is not True:
        raise FrameContractError(f"frame {frame.frame_id} lacks exhaustive evidence for a verdict")


# --- frame-read gate ----------------------------------------------------------------

_LEDGER_NAME = "unseal-ledger.jsonl"
_SPENT_DIR = "spent"


def _firbench_private_dir(repo_root: Path) -> Path:
    return Path(repo_root) / "benchmarks" / "private" / "firbench"


def require_frame_read_allowed(
    frame: FrameSpec,
    token: UnsealToken | None,
    *,
    decision_sha256: str,
    run_id: str,
    code_sha: str,
    scorer_sha: str,
    repo_root: Path,
    consumed_at: str,
) -> UnsealToken:
    """Authorise the first and only sealed read of ``frame`` for this run [EXP-22, EVAL-07].

    Call once per frame load and keep the loaded frame for the run. The atomic ``O_EXCL``
    create of the per-frame spent marker is the spend. A failed create, a failed ledger
    append after the spend, or any field mismatch refuses the read. A spent frame stays
    refused for every decision and run.
    """
    if not frame.sealed:
        raise FrameContractError(f"frame {frame.frame_id} is not sealed; use the open read path")
    if token is None:
        raise SealedFrameReadError(f"sealed frame {frame.frame_id} has no unseal token")
    if token.consumed_at is not None:
        raise SealedFrameReadError(f"unseal token for {frame.frame_id} is already consumed")
    _require_timestamp(consumed_at, "consumed_at")
    bindings = (
        ("frame_id", token.frame_id, frame.frame_id),
        ("frame_sha256", token.frame_sha256, frame.source_sha256),
        ("decision_sha256", token.decision_sha256, decision_sha256),
        ("run_id", token.run_id, run_id),
        ("code_sha", token.code_sha, code_sha),
        ("scorer_sha", token.scorer_sha, scorer_sha),
    )
    for name, bound, current in bindings:
        if current is None or bound != current:
            raise SealedFrameReadError(f"unseal token {name} does not match the current {name}")

    root = Path(repo_root)
    private = _firbench_private_dir(root)
    marker = private / _SPENT_DIR / f"{frame.frame_id}.spent"
    ledger = private / _LEDGER_NAME
    require_private_output_path(marker, repo_root=root)
    require_private_output_path(ledger, repo_root=root)

    try:
        (private / _SPENT_DIR).mkdir(parents=True, exist_ok=True)
        fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError as exc:
        raise SealedFrameReadError(f"frame {frame.frame_id} is already spent") from exc
    except OSError as exc:
        raise SealedFrameReadError(f"cannot create spent marker for {frame.frame_id}: {exc}") from exc

    consumed = dataclasses.replace(token, consumed_at=consumed_at)
    row = json.dumps(dataclasses.asdict(consumed), sort_keys=True, separators=(",", ":"))
    try:
        try:
            os.write(fd, (row + "\n").encode("utf-8"))
        finally:
            os.close(fd)
        with ledger.open("a", encoding="utf-8") as handle:
            handle.write(row + "\n")
    except OSError as exc:
        raise SealedFrameReadError(
            f"frame {frame.frame_id} is spent but its consumption could not be recorded: {exc}"
        ) from exc
    return consumed


def require_private_output_path(path: str | os.PathLike[str], *, repo_root: Path) -> Path:
    """Return the resolved path if it lies strictly under ``benchmarks/private/``.

    Relative paths resolve from ``repo_root``. The boundary is the intended private
    directory under the resolved repository, never the target of a redirected
    ``benchmarks`` or ``private`` directory [ARCH-13]. Inner symlinks and ``..``
    segments must also resolve inside that boundary.
    """
    try:
        root = Path(repo_root).resolve()
        private = root / "benchmarks" / "private"
        if private.resolve() != private:
            raise NonPrivateOutputError("benchmarks/private/ is redirected from the intended repository directory")
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = root / candidate
        resolved = candidate.resolve()
    except (OSError, RuntimeError) as exc:
        raise NonPrivateOutputError(f"cannot resolve private output path {path!s}: {exc}") from exc
    if resolved == private or private not in resolved.parents:
        raise NonPrivateOutputError(f"output path {path!s} resolves outside benchmarks/private/")
    return resolved


# --- interchange schemas (stdlib subset checker) -------------------------------------

_INTERCHANGE_NAMES = frozenset({"frame-v1", "face-search-record-v1", "scores-v1", "clusters-v1", "comparison-v1"})
_SCHEMA_DIR = Path(__file__).resolve().parent / "firbench_schemas"
_ANNOTATION_KEYWORDS = frozenset({"$schema", "$id", "$defs", "$comment", "title", "description"})
_VALIDATION_KEYWORDS = frozenset(
    {
        "type",
        "const",
        "enum",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "prefixItems",
        "minItems",
        "maxItems",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "minLength",
        "maxLength",
        "pattern",
        "$ref",
        "if",
        "then",
        "else",
    }
)


@functools.cache
def _load_schema(name: str) -> dict[str, Any]:
    try:
        schema = json.loads((_SCHEMA_DIR / f"{name}.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FrameContractError(f"cannot read interchange schema {name}: {exc}") from exc
    if not isinstance(schema, dict):
        raise FrameContractError(f"interchange schema {name} must be an object")
    return schema


def validate_interchange(name: str, payload: object) -> None:
    """Validate an interchange payload against its versioned schema, or raise ``FrameContractError``."""
    if name not in _INTERCHANGE_NAMES:
        raise FrameContractError(f"unknown interchange schema {name!r}")
    schema = _load_schema(name)
    try:
        _check(schema, payload, schema, "$")
    except FrameContractError as exc:
        raise FrameContractError(f"{name}: {exc}") from exc


def _matches_type(value: object, type_name: str) -> bool:
    if type_name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    if type_name == "boolean":
        return isinstance(value, bool)
    if type_name == "null":
        return value is None
    if type_name == "object":
        return isinstance(value, dict)
    if type_name == "array":
        return isinstance(value, list)
    if type_name == "string":
        return isinstance(value, str)
    raise FrameContractError(f"unsupported schema type {type_name!r}")


def _json_equal(left: object, right: object) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if left is None or right is None:
        return left is right
    return left == right


def _resolve_ref(root: Mapping[str, Any], ref: object) -> Mapping[str, Any]:
    prefix = "#/$defs/"
    if not isinstance(ref, str) or not ref.startswith(prefix):
        raise FrameContractError(f"unsupported schema reference {ref!r}")
    defs = root.get("$defs", {})
    target = defs.get(ref[len(prefix) :])
    if not isinstance(target, dict):
        raise FrameContractError(f"schema reference {ref!r} does not resolve")
    return target


def _is_valid(schema: Mapping[str, Any], value: object, root: Mapping[str, Any]) -> bool:
    try:
        _check(schema, value, root, "$")
    except FrameContractError:
        return False
    return True


def _check(schema: Mapping[str, Any], value: object, root: Mapping[str, Any], path: str) -> None:
    unsupported = set(schema) - _VALIDATION_KEYWORDS - _ANNOTATION_KEYWORDS
    if unsupported:
        raise FrameContractError(f"{path}: unsupported schema keywords {sorted(unsupported)}")
    if "$ref" in schema:
        _check(_resolve_ref(root, schema["$ref"]), value, root, path)
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_matches_type(value, type_name) for type_name in types):
            raise FrameContractError(f"{path}: expected {'|'.join(types)}")
    if "const" in schema and not _json_equal(value, schema["const"]):
        raise FrameContractError(f"{path}: expected constant {schema['const']!r}")
    if "enum" in schema and not any(_json_equal(value, option) for option in schema["enum"]):
        raise FrameContractError(f"{path}: {value!r} is not an allowed value")
    if isinstance(value, dict):
        _check_object(schema, value, root, path)
    if isinstance(value, list):
        _check_array(schema, value, root, path)
    if isinstance(value, str):
        _check_string(schema, value, path)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        _check_number(schema, value, path)
    if "if" in schema:
        branch = schema.get("then") if _is_valid(schema["if"], value, root) else schema.get("else")
        if branch is not None:
            _check(branch, value, root, path)


def _check_object(schema: Mapping[str, Any], value: dict[str, Any], root: Mapping[str, Any], path: str) -> None:
    for key in schema.get("required", []):
        if key not in value:
            raise FrameContractError(f"{path}: missing required key {key!r}")
    properties = schema.get("properties", {})
    additional = schema.get("additionalProperties", True)
    if additional is False:
        unknown = sorted(set(value) - set(properties))
        if unknown:
            raise FrameContractError(f"{path}: unknown keys {unknown}")
    elif additional is not True:
        raise FrameContractError(f"{path}: unsupported additionalProperties form")
    for key, subschema in properties.items():
        if key in value:
            _check(subschema, value[key], root, f"{path}.{key}")


def _check_array(schema: Mapping[str, Any], value: list[Any], root: Mapping[str, Any], path: str) -> None:
    if "minItems" in schema and len(value) < schema["minItems"]:
        raise FrameContractError(f"{path}: needs at least {schema['minItems']} items")
    if "maxItems" in schema and len(value) > schema["maxItems"]:
        raise FrameContractError(f"{path}: allows at most {schema['maxItems']} items")
    prefix = schema.get("prefixItems", [])
    for index, subschema in enumerate(prefix):
        if index < len(value):
            _check(subschema, value[index], root, f"{path}[{index}]")
    items = schema.get("items", True)
    if items is False:
        if len(value) > len(prefix):
            raise FrameContractError(f"{path}: has items beyond the declared tuple")
        return
    if isinstance(items, dict):
        for index in range(len(prefix), len(value)):
            _check(items, value[index], root, f"{path}[{index}]")


def _check_string(schema: Mapping[str, Any], value: str, path: str) -> None:
    if "minLength" in schema and len(value) < schema["minLength"]:
        raise FrameContractError(f"{path}: string is too short")
    if "maxLength" in schema and len(value) > schema["maxLength"]:
        raise FrameContractError(f"{path}: string is too long")
    if "pattern" in schema and re.search(schema["pattern"], value) is None:
        raise FrameContractError(f"{path}: string does not match the pattern")


def _check_number(schema: Mapping[str, Any], value: float, path: str) -> None:
    if "minimum" in schema and value < schema["minimum"]:
        raise FrameContractError(f"{path}: below minimum {schema['minimum']}")
    if "maximum" in schema and value > schema["maximum"]:
        raise FrameContractError(f"{path}: above maximum {schema['maximum']}")
    if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
        raise FrameContractError(f"{path}: must exceed {schema['exclusiveMinimum']}")
    if "exclusiveMaximum" in schema and value >= schema["exclusiveMaximum"]:
        raise FrameContractError(f"{path}: must stay below {schema['exclusiveMaximum']}")
