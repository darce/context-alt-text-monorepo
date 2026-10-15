"""Fake-only S3 -> S5 wire regressions, using the real stdlib validator.

Canon v0.26.2: EVAL-18/19 (IARPA Janus Benchmark-C, section 2.3.4)
require thresholded identification on fixed non-mated source units. CARD-27
(the supplied margin-and-design-effect-before-the-run supplement) keeps raw
counts distinct from effective support and paired hypothesis intervals distinct
from descriptive leg intervals. No scoring implementation or observation is
claimed here. Timing states are synthetic assessment inputs, never measurements.
"""

from __future__ import annotations

import copy
import json
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

from scripts.eval_harness import firbench_contract as fc

FIXTURE = Path(__file__).parent / "fixtures" / "firbench_interchange_v1" / "scores-v1.json"
LEGS = (
    "sface__native__ab12cd__cv4.10.0__ort1.18.0",
    "auraface__native__ef34ab__cv4.10.0__ort1.18.0",
)


def _available(data: Any) -> dict[str, Any]:
    return {"status": "available", "reason": None, "data": data}


def _absent(status: str = "unavailable") -> dict[str, Any]:
    return {"status": status, "reason": "synthetic: evidence not supplied", "data": None}


def _leg(key: str, tau: float, misses: int) -> dict[str, Any]:
    return {
        "leg_key": key,
        "tau": _available(
            {
                "value": tau,
                "calibration_spread": 0.02,
                "pooled_units": 20,
                "fpi_at_tau": {"count": 0, "rate": 0.0},
                "fpi_next_lower": _available(
                    {"threshold": tau - 0.01, "count": 1, "rate": 0.05, "fnir": _available(0.1)}
                ),
            }
        ),
        "operating_point": {
            "fnir": _available(
                {
                    "misses": misses,
                    "n_mated": 10,
                    "n_eff": 5.0,
                    "design_effect": 2.0,
                    "rate": float(Fraction(misses, 10)),
                    "interval": _available(
                        {"lower": 0.0, "upper": 0.8, "level": 0.95, "method": "psu_percentile"}
                    ),
                }
            ),
            "fpir": _available(
                {
                    "fpi": 0,
                    "n_units": 10,
                    "n_nonmated_eff": 10.0,
                    "rate": 0.0,
                    "iid_ucl": _available({
                        "upper": 0.2588655508930523,
                        "level": 0.95,
                        "method": "clopper_pearson",
                        "approximate": True,
                    }),
                    "clustered_ucl": _available(
                        {"upper": 0.3, "level": 0.95, "method": "rule_of_three", "approximate": True}
                    ),
                }
            ),
        },
    }


def _payload() -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload.pop("tau", None)
    payload["legs"] = [_leg(LEGS[0], 0.41, 5), _leg(LEGS[1], 0.67, 2)]
    return payload


def _validate(payload: dict[str, Any]) -> None:
    fc.validate_interchange("scores-v1", payload)


def _at(payload: dict[str, Any], path: str) -> Any:
    target: Any = payload
    for part in path.split("."):
        target = target[int(part)] if isinstance(target, list) else target[part]
    return target


def test_distinct_leg_thresholds_and_operating_points_round_trip(tmp_path: Path) -> None:
    payload = _payload()
    before = copy.deepcopy(payload)
    path = tmp_path / "synthetic-scores.json"
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    restored = json.loads(path.read_text(encoding="utf-8"))
    _validate(restored)
    assert restored == before
    assert [leg["tau"]["data"]["value"] for leg in restored["legs"]] == [0.41, 0.67]
    assert [leg["operating_point"]["fnir"]["data"]["rate"] for leg in restored["legs"]] == [0.5, 0.2]
    assert restored["primary"] == payload["primary"]
    assert restored["hypotheses"] == payload["hypotheses"]


def test_committed_fixture_has_multiple_legs_and_no_shared_tau() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    _validate(payload)
    assert "tau" not in payload
    assert len({leg["leg_key"] for leg in payload["legs"]}) >= 2
    assert len({leg["tau"]["data"]["value"] for leg in payload["legs"]}) >= 2


def test_scalar_tau_payload_is_no_longer_a_valid_multi_leg_contract() -> None:
    payload = _payload()
    payload["tau"] = payload.pop("legs")[0]["tau"]["data"]
    lower = payload["tau"]["fpi_next_lower"]["data"]
    lower.pop("fnir")
    payload["tau"]["fpi_next_lower"] = lower
    with pytest.raises(fc.FrameContractError):
        _validate(payload)


@pytest.mark.parametrize("legs", [[], None, {}, "shared"])
def test_legs_require_a_nonempty_typed_array(legs: Any) -> None:
    payload = _payload()
    payload["legs"] = legs
    with pytest.raises(fc.FrameContractError, match="legs"):
        _validate(payload)


@pytest.mark.parametrize(
    "path",
    [
        "legs.0", "legs.0.tau", "legs.0.tau.data", "legs.0.tau.data.fpi_at_tau",
        "legs.0.tau.data.fpi_next_lower.data", "legs.0.operating_point",
        "legs.0.operating_point.fnir.data", "legs.0.operating_point.fnir.data.interval.data",
        "legs.0.operating_point.fpir.data", "legs.0.operating_point.fpir.data.iid_ucl.data",
        "legs.0.operating_point.fpir.data.clustered_ucl.data",
    ],
)
def test_nested_evidence_is_required_and_closed(path: str) -> None:
    payload = _payload()
    _validate(payload)
    target = _at(payload, path)
    for field in tuple(target):
        removed = copy.deepcopy(payload)
        del _at(removed, path)[field]
        with pytest.raises(fc.FrameContractError):
            _validate(removed)
    target["invented"] = 1
    with pytest.raises(fc.FrameContractError, match="invented"):
        _validate(payload)


@pytest.mark.parametrize("status", ["unavailable", "not_evaluated"])
@pytest.mark.parametrize(
    "path",
    [
        "legs.0.tau", "legs.0.tau.data.fpi_next_lower", "legs.0.tau.data.fpi_next_lower.data.fnir",
        "legs.0.operating_point.fnir", "legs.0.operating_point.fnir.data.interval",
        "legs.0.operating_point.fpir", "legs.0.operating_point.fpir.data.iid_ucl",
        "legs.0.operating_point.fpir.data.clustered_ucl",
    ],
)
def test_explicit_missing_evidence_is_not_imputed_as_zero(path: str, status: str) -> None:
    payload = _payload()
    parent, field = path.rsplit(".", 1)
    _at(payload, parent)[field] = _absent(status)
    _validate(payload)
    assert _at(payload, path)["data"] is None


@pytest.mark.parametrize(
    "evidence",
    [
        {"status": "available", "reason": None, "data": None},
        {"status": "available", "reason": "absent", "data": {}},
        {"status": "unavailable", "reason": None, "data": None},
        {"status": "not_evaluated", "reason": "", "data": None},
        {"status": "unavailable", "reason": "absent", "data": {}},
        {"status": "unknown", "reason": "absent", "data": None},
    ],
)
def test_missing_states_cannot_carry_measurements_or_silent_reasons(evidence: dict[str, Any]) -> None:
    payload = _payload()
    _validate(payload)
    payload["legs"][0]["tau"] = evidence
    with pytest.raises(fc.FrameContractError):
        _validate(payload)


@pytest.mark.parametrize(
    "path,value",
    [
        ("tau.data.value", True), ("tau.data.value", float("inf")),
        ("tau.data.calibration_spread", -0.1), ("tau.data.pooled_units", 1.5),
        ("tau.data.fpi_at_tau.count", False), ("tau.data.fpi_at_tau.rate", 1.01),
        ("tau.data.fpi_next_lower.data.count", -1),
        ("tau.data.fpi_next_lower.data.fnir.data", -0.1),
        ("operating_point.fnir.data.misses", 0.5), ("operating_point.fnir.data.n_mated", 0),
        ("operating_point.fnir.data.n_eff", -1), ("operating_point.fnir.data.design_effect", 0),
        ("operating_point.fnir.data.rate", float("nan")),
        ("operating_point.fnir.data.interval.data.lower", -0.1),
        ("operating_point.fnir.data.interval.data.upper", 1.1),
        ("operating_point.fnir.data.interval.data.level", 1),
        ("operating_point.fnir.data.interval.data.method", "iid"),
        ("operating_point.fpir.data.fpi", 0.5), ("operating_point.fpir.data.n_units", 10.5),
        ("operating_point.fpir.data.n_units", 0), ("operating_point.fpir.data.n_nonmated_eff", 0),
        ("operating_point.fpir.data.rate", -0.01),
        ("operating_point.fpir.data.iid_ucl.data.level", 0.9),
        ("operating_point.fpir.data.iid_ucl.data.method", "rule_of_three"),
        ("operating_point.fpir.data.iid_ucl.data.approximate", False),
        ("operating_point.fpir.data.iid_ucl.data.upper", 1.1),
        ("operating_point.fpir.data.clustered_ucl.data.upper", -1),
        ("operating_point.fpir.data.clustered_ucl.data.level", 0.9),
        ("operating_point.fpir.data.clustered_ucl.data.approximate", False),
    ],
)
def test_per_leg_counts_rates_intervals_and_bound_labels_are_typed(path: str, value: Any) -> None:
    payload = _payload()
    _validate(payload)
    parent, field = path.rsplit(".", 1)
    _at(payload["legs"][0], parent)[field] = value
    with pytest.raises(fc.FrameContractError):
        _validate(payload)


@pytest.mark.parametrize("fpi,method,approximate", [(0, "rule_of_three", True), (2, "psu_percentile", True)])
def test_fpir_ucl_distinguishes_zero_events_from_psu_percentiles(fpi: int, method: str, approximate: bool) -> None:
    payload = _payload()
    fpir = payload["legs"][0]["operating_point"]["fpir"]["data"]
    fpir.update(fpi=fpi, rate=float(Fraction(fpi, fpir["n_units"])))
    bound = fpir["clustered_ucl"]["data"]
    bound.update(method=method, approximate=approximate)
    _validate(payload)
    bound.update(method="psu_percentile" if fpi == 0 else "rule_of_three")
    with pytest.raises(fc.FrameContractError):
        _validate(payload)


def test_raw_zero_event_approximation_can_exceed_one_at_tiny_effective_support() -> None:
    payload = _payload()
    fpir = payload["legs"][0]["operating_point"]["fpir"]["data"]
    fpir["n_nonmated_eff"] = 2.0
    fpir["clustered_ucl"]["data"]["upper"] = 1.5
    _validate(payload)
    assert payload["primary"]["resolvable"] is False


@pytest.mark.parametrize("state", ["pass", "fail", "unscored"])
def test_p95_receipt_keeps_the_real_assessment_state_without_milliseconds(state: str) -> None:
    payload = _payload()
    payload["guardrails"].append(
        {"id": "G4", "metric": "p95_ms_per_face", "role": "veto", "state": state,
         "value": None, "timings_sha256": "a" * 64}
    )
    _validate(payload)
    pinned = json.dumps(payload, sort_keys=True)
    assert json.dumps(json.loads(pinned), sort_keys=True) == pinned
    payload["guardrails"][-1]["value"] = 12.5
    with pytest.raises(fc.FrameContractError):
        _validate(payload)


@pytest.mark.parametrize("state", ["pass", "fail"])
@pytest.mark.parametrize("sha", [None, "", "not-a-sha"])
def test_scored_p95_requires_its_pinned_timing_input(state: str, sha: str | None) -> None:
    payload = _payload()
    _validate(payload)
    payload["guardrails"] = [
        {"id": "G4", "metric": "p95_ms_per_face", "role": "veto", "state": state,
         "value": None, "timings_sha256": sha}
    ]
    with pytest.raises(fc.FrameContractError):
        _validate(payload)


def test_changed_timing_evidence_can_be_represented_as_an_actual_hypothesis_veto() -> None:
    payload = _payload()
    # Synthetic eligible inputs: this checks serialization, not decide() or coverage.
    payload.update(n_units=1000, n_nonmated_eff=1000.0, n_eff=500.0, design_effect=2.0)
    payload["primary"]["resolvable"] = True
    for leg in payload["legs"]:
        fnir = leg["operating_point"]["fnir"]["data"]
        fnir.update(n_mated=1000, misses=int(fnir["rate"] * 1000), n_eff=500.0)
        fpir = leg["operating_point"]["fpir"]["data"]
        fpir.update(n_units=1000, n_nonmated_eff=1000.0)
        fpir["iid_ucl"]["data"]["upper"] = 0.0029912495450953314
        fpir["clustered_ucl"]["data"]["upper"] = 0.003
    payload["guardrails"] = [
        {"id": "G4", "metric": "p95_ms_per_face", "role": "veto", "state": "pass",
         "value": None, "timings_sha256": "a" * 64}
    ]
    payload["verdict"].update(state="superior", reason=None)
    payload["hypotheses"][0].update(
        state="superior", reason=None, n_eff=500.0, mde=0.03,
        interval={"lower": 0.2, "upper": 0.4, "level": 0.95},
    )
    _validate(payload)
    changed = copy.deepcopy(payload)
    changed["guardrails"][0].update(state="fail", timings_sha256="b" * 64)
    changed["verdict"]["state"] = "guardrail_vetoed"
    changed["hypotheses"][0]["state"] = "guardrail_vetoed"
    _validate(changed)
    assert changed != payload  # Full scores replay requires the SAME timing input.
    assert changed["legs"] == payload["legs"]


def test_p95_cannot_be_downgraded_to_report_only_but_missing_receipt_is_explicit() -> None:
    payload = _payload()
    payload["guardrails"] = [
        {"id": "G4", "metric": "p95_ms_per_face", "role": "veto", "state": "unscored",
         "value": None, "timings_sha256": None}
    ]
    _validate(payload)
    payload["guardrails"][0]["role"] = "report_only"
    with pytest.raises(fc.FrameContractError):
        _validate(payload)
