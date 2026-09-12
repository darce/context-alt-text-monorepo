"""Machine-checkable contract for the FIR open-set identification gate.

The contract deliberately keeps the D3 operating point unset in the shipped
manifest.  A later operator decision may fill the nullable fields, but a
consumer must not infer an operating point from an absent or malformed value.
Threshold hashes use finite float values serialized as sorted-key JSON with
compact separators (",", ":") and UTF-8 encoding.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.eval_harness.open_set_identification import IETPoint

RUBRIC_VERSION = "face-label-rule/v1"
_METRIC = "FNIR@FPIR"
_REQUIRED_KEYS = frozenset(
    {
        "metric",
        "max_fpi",
        "n_nonmated_declared",
        "rubric_version",
        "ratified_by_decision_id",
        "t14_thresholds_declared",
        "t14_thresholds_sha256",
        "t14_exhaustive_subset_count",
        "t14_exhaustive_subset_sha256",
    }
)
_THRESHOLD_KEYS = frozenset({"buffalo", "candidate"})


class GateContractError(Exception):
    """Fail-fast error for an unreadable or malformed gate contract."""


@dataclass(frozen=True)
class GateContract:
    """The fields that define the frozen FIR gate contract."""

    metric: str
    max_fpi: int | None
    n_nonmated_declared: int | None
    rubric_version: str
    ratified_by_decision_id: str | None
    t14_thresholds_declared: dict[str, float] | None
    t14_thresholds_sha256: str | None
    t14_exhaustive_subset_count: int | None
    t14_exhaustive_subset_sha256: str | None

    def __post_init__(self) -> None:
        metric = self.metric
        if metric != _METRIC:
            raise GateContractError(f"metric must be {_METRIC!r}, got {metric!r}")

        max_fpi = _require_non_negative_int(self.max_fpi, name="max_fpi")
        n_nonmated_declared = _require_non_negative_int(self.n_nonmated_declared, name="n_nonmated_declared")

        rubric_version = self.rubric_version
        if rubric_version != RUBRIC_VERSION:
            raise GateContractError(f"rubric_version must be {RUBRIC_VERSION!r}, got {rubric_version!r}")

        ratified_by_decision_id = self.ratified_by_decision_id
        if ratified_by_decision_id is not None and (
            not isinstance(ratified_by_decision_id, str) or not ratified_by_decision_id.strip()
        ):
            raise GateContractError("ratified_by_decision_id must be a non-empty string or null")

        thresholds = _validate_thresholds(self.t14_thresholds_declared)
        thresholds_sha256 = _validate_sha256(self.t14_thresholds_sha256)
        if (thresholds is None) != (thresholds_sha256 is None):
            raise GateContractError("t14_thresholds_declared and t14_thresholds_sha256 must be both set or both null")
        if thresholds is not None and thresholds_sha256 != threshold_sha256(thresholds):
            raise GateContractError("t14_thresholds_sha256 does not match t14_thresholds_declared")

        d3 = (max_fpi, n_nonmated_declared, ratified_by_decision_id)
        if any(value is None for value in d3) and not all(value is None for value in d3):
            raise GateContractError("D3 ratification fields must be all set or all null")
        count = _require_non_negative_int(self.t14_exhaustive_subset_count, name="t14_exhaustive_subset_count")
        subset_sha = _validate_sha256(self.t14_exhaustive_subset_sha256, name="t14_exhaustive_subset_sha256")
        if (count is None) != (subset_sha is None):
            raise GateContractError("exhaustive subset count and sha256 must be both set or both null")
        if count is not None and count < 30:
            raise GateContractError("t14_exhaustive_subset_count must be at least 30")
        object.__setattr__(self, "t14_thresholds_declared", thresholds)


def _require_non_negative_int(value: object, *, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise GateContractError(f"{name} must be a non-negative integer or null")
    return value


def _require_finite_number(value: object, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GateContractError(f"{name} must be a finite number")
    try:
        number = float(value)
    except OverflowError as exc:
        raise GateContractError(f"{name} must be a finite number") from exc
    if not math.isfinite(number):
        raise GateContractError(f"{name} must be a finite number")
    return number


def _validate_thresholds(value: object) -> dict[str, float] | None:
    if value is None:
        return None
    return canonical_thresholds(value)


def canonical_thresholds(value: Mapping[str, object]) -> dict[str, float]:
    """Validate and normalize the two signed detector thresholds."""
    if not isinstance(value, Mapping):
        raise GateContractError("t14_thresholds_declared must be an object or null")
    keys = set(value)
    if keys != _THRESHOLD_KEYS:
        raise GateContractError("t14_thresholds_declared must contain exactly 'buffalo' and 'candidate'")
    return {
        key: _require_finite_number(value[key], name=f"t14_thresholds_declared.{key}")
        for key in ("buffalo", "candidate")
    }


def _validate_sha256(value: object, *, name: str = "t14_thresholds_sha256") -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) != 64:
        raise GateContractError(f"{name} must be a 64-character hex string or null")
    if any(character not in "0123456789abcdefABCDEF" for character in value):
        raise GateContractError(f"{name} must be a 64-character hex string or null")
    return value


def threshold_sha256(value: Mapping[str, object]) -> str:
    """Hash the compact, sorted JSON encoding of canonical float thresholds."""
    encoded = json.dumps(canonical_thresholds(value), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def exhaustive_subset_sha256(image_ids: Iterable[str]) -> str:
    """Hash sorted, newline-separated exhaustive image ids, rejecting duplicates."""
    ids = list(image_ids)
    if any(not isinstance(image_id, str) for image_id in ids):
        raise GateContractError("exhaustive image ids must be strings")
    if len(set(ids)) != len(ids):
        raise GateContractError("exhaustive image ids must not contain duplicates")
    return hashlib.sha256("\n".join(sorted(ids)).encode("utf-8")).hexdigest()


def load_gate_contract(path: str | Path) -> GateContract:
    """Load and structurally validate a gate contract JSON document.

    Every field is required, including the T-14 fields that are ``null``
    until the operator ratifies that run.  Unknown fields are rejected so a
    future or misspelled key cannot silently change the contract shape.
    """

    contract_path = Path(path)
    try:
        payload: Any = json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GateContractError(f"cannot read gate contract {contract_path}: {exc}") from exc

    if not isinstance(payload, dict):
        raise GateContractError("gate contract must be a JSON object")

    missing = _REQUIRED_KEYS - set(payload)
    if missing:
        raise GateContractError(f"gate contract missing required keys: {sorted(missing)}")
    unknown = set(payload) - _REQUIRED_KEYS
    if unknown:
        raise GateContractError(f"gate contract has unknown keys: {sorted(unknown)}")

    return GateContract(**payload)


def select_gate_point(
    points: Sequence[IETPoint],
    *,
    max_fpi: int,
) -> IETPoint | None:
    """Select the lowest-threshold measured point under an FPI ceiling.

    An unmeasured point is never eligible, even when its placeholder FPI is
    zero.  This preserves the IETPoint invariant that an absent measurement
    cannot become a perfect gate result by threshold selection.
    """

    if isinstance(max_fpi, bool) or not isinstance(max_fpi, int) or max_fpi < 0:
        raise ValueError("max_fpi must be a non-negative integer")

    qualifying = [point for point in points if point.measured and point.fpi is not None and point.fpi <= max_fpi]
    if not qualifying:
        return None
    return min(qualifying, key=lambda point: point.tau)


__all__ = [
    "GateContract",
    "GateContractError",
    "RUBRIC_VERSION",
    "canonical_thresholds",
    "threshold_sha256",
    "exhaustive_subset_sha256",
    "load_gate_contract",
    "select_gate_point",
]
