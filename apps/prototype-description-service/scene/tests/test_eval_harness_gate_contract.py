"""RED tests for the FIR-13 open-set gate contract."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path

import pytest

_CONTRACT_FIELDS = (
    "metric",
    "max_fpi",
    "n_nonmated_declared",
    "rubric_version",
    "ratified_by_decision_id",
    "t14_thresholds_declared",
    "t14_thresholds_sha256",
)


def _contract_payload() -> dict[str, object]:
    thresholds = {"buffalo": 0.82, "candidate": 0.77}
    return {
        "metric": "FNIR@FPIR",
        "max_fpi": 3,
        "n_nonmated_declared": 12,
        "rubric_version": "face-label-rule/v1",
        "ratified_by_decision_id": "firplan_d3_operating_point_20260912",
        "t14_thresholds_declared": thresholds,
        "t14_thresholds_sha256": hashlib.sha256(
            json.dumps(thresholds, sort_keys=True).encode("utf-8")
        ).hexdigest(),
    }


def _write_contract(tmp_path: Path, payload: dict[str, object]) -> Path:
    path = tmp_path / "gate-contract.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_load_gate_contract_round_trips(tmp_path: Path) -> None:
    from scripts.eval_harness import gate_contract

    payload = _contract_payload()
    loaded = gate_contract.load_gate_contract(_write_contract(tmp_path, payload))

    assert loaded == gate_contract.GateContract(**payload)
    assert tuple(field.name for field in dataclasses.fields(loaded)) == _CONTRACT_FIELDS
    with pytest.raises(dataclasses.FrozenInstanceError):
        loaded.metric = "not-fnir-at-fpir"  # type: ignore[misc]


def test_load_gate_contract_raises_on_missing_metric(tmp_path: Path) -> None:
    from scripts.eval_harness import gate_contract

    payload = _contract_payload()
    del payload["metric"]

    with pytest.raises(gate_contract.GateContractError):
        gate_contract.load_gate_contract(_write_contract(tmp_path, payload))


def test_load_gate_contract_raises_on_missing_t14_threshold_keys(tmp_path: Path) -> None:
    from scripts.eval_harness import gate_contract

    for missing_key in ("t14_thresholds_declared", "t14_thresholds_sha256"):
        payload = _contract_payload()
        del payload[missing_key]

        with pytest.raises(gate_contract.GateContractError):
            gate_contract.load_gate_contract(_write_contract(tmp_path, payload))


def test_select_gate_point_never_returns_zero_for_unmeasured() -> None:
    from scripts.eval_harness import gate_contract
    from scripts.eval_harness.open_set_identification import IETPoint

    unmeasured = IETPoint(
        tau=0.01,
        fnir=None,
        fpi=0,
        n_mated=0,
        n_fnir_misses=0,
        n_nonmated=0,
        measured=False,
    )
    measured_over_ceiling = IETPoint(
        tau=0.20,
        fnir=0.50,
        fpi=1,
        n_mated=2,
        n_fnir_misses=1,
        n_nonmated=1,
        measured=True,
    )

    selected = gate_contract.select_gate_point(
        [unmeasured, measured_over_ceiling], max_fpi=0
    )

    assert selected is None


def test_select_gate_point_picks_lowest_qualifying_tau() -> None:
    from scripts.eval_harness import gate_contract
    from scripts.eval_harness.open_set_identification import IETPoint

    def measured_point(tau: float, fpi: int) -> IETPoint:
        return IETPoint(
            tau=tau,
            fnir=0.25,
            fpi=fpi,
            n_mated=4,
            n_fnir_misses=1,
            n_nonmated=2,
            measured=True,
        )

    high_tau = measured_point(0.70, 1)
    lowest_qualifying = measured_point(0.40, 2)
    over_ceiling = measured_point(0.20, 5)

    selected = gate_contract.select_gate_point(
        [high_tau, over_ceiling, lowest_qualifying], max_fpi=2
    )

    assert selected is lowest_qualifying
