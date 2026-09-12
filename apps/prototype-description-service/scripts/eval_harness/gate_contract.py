"""Machine-checkable contract for the FIR open-set identification gate.

The contract deliberately keeps the D3 operating point unset in the shipped
manifest.  A later operator decision may fill the nullable fields, but a
consumer must not infer an operating point from an absent or malformed value.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
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
    }
)
_THRESHOLD_KEYS = frozenset({"buffalo", "candidate"})


class GateContractError(Exception):
    """Fail-fast error for an unreadable or malformed gate contract."""


@dataclass(frozen=True)
class GateContract:
    """The seven fields that define the frozen FIR gate contract."""

    metric: str
    max_fpi: int | None
    n_nonmated_declared: int | None
    rubric_version: str
    ratified_by_decision_id: str | None
    t14_thresholds_declared: dict[str, float] | None
    t14_thresholds_sha256: str | None


def _require_non_negative_int(value: object, *, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise GateContractError(f"{name} must be a non-negative integer or null")
    return value


def _require_finite_number(value: object, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GateContractError(f"{name} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise GateContractError(f"{name} must be a finite number")
    return number


def _validate_thresholds(value: object) -> dict[str, float] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise GateContractError("t14_thresholds_declared must be an object or null")
    keys = set(value)
    if keys != _THRESHOLD_KEYS:
        raise GateContractError("t14_thresholds_declared must contain exactly 'buffalo' and 'candidate'")
    return {
        key: _require_finite_number(value[key], name=f"t14_thresholds_declared.{key}")
        for key in ("buffalo", "candidate")
    }


def _validate_sha256(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) != 64:
        raise GateContractError("t14_thresholds_sha256 must be a 64-character hex string or null")
    if any(character not in "0123456789abcdefABCDEF" for character in value):
        raise GateContractError("t14_thresholds_sha256 must be a 64-character hex string or null")
    return value


def _threshold_sha256(thresholds: Mapping[str, float]) -> str:
    try:
        encoded = json.dumps(thresholds, sort_keys=True).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise GateContractError("t14_thresholds_declared is not JSON serializable") from exc
    return hashlib.sha256(encoded).hexdigest()


def load_gate_contract(path: str | Path) -> GateContract:
    """Load and structurally validate a gate contract JSON document.

    Every field is required, including the two T-14 fields that are ``null``
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

    metric = payload["metric"]
    if metric != _METRIC:
        raise GateContractError(f"metric must be {_METRIC!r}, got {metric!r}")

    max_fpi = _require_non_negative_int(payload["max_fpi"], name="max_fpi")
    n_nonmated_declared = _require_non_negative_int(payload["n_nonmated_declared"], name="n_nonmated_declared")

    rubric_version = payload["rubric_version"]
    if rubric_version != RUBRIC_VERSION:
        raise GateContractError(f"rubric_version must be {RUBRIC_VERSION!r}, got {rubric_version!r}")

    ratified_by_decision_id = payload["ratified_by_decision_id"]
    if ratified_by_decision_id is not None and (
        not isinstance(ratified_by_decision_id, str) or not ratified_by_decision_id.strip()
    ):
        raise GateContractError("ratified_by_decision_id must be a non-empty string or null")

    thresholds = _validate_thresholds(payload["t14_thresholds_declared"])
    thresholds_sha256 = _validate_sha256(payload["t14_thresholds_sha256"])
    if (thresholds is None) != (thresholds_sha256 is None):
        raise GateContractError("t14_thresholds_declared and t14_thresholds_sha256 must be both set or both null")
    if thresholds is not None and thresholds_sha256 != _threshold_sha256(thresholds):
        raise GateContractError("t14_thresholds_sha256 does not match t14_thresholds_declared")

    return GateContract(
        metric=metric,
        max_fpi=max_fpi,
        n_nonmated_declared=n_nonmated_declared,
        rubric_version=rubric_version,
        ratified_by_decision_id=ratified_by_decision_id,
        t14_thresholds_declared=thresholds,
        t14_thresholds_sha256=thresholds_sha256,
    )


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
    "load_gate_contract",
    "select_gate_point",
]
