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
        "pair_fmr": {"status": "not_evaluated", "reason": "pair_scores_not_supplied", "data": None},
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


def test_committed_fixture_has_an_honestly_synthetic_decision_path() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    _validate(payload)
    assert payload["schema_version"] == 1
    assert payload["decision_path"] == [
        "synthetic: schema fixture only; no core verdict execution or real evidence",
        "eligibility:insufficient_independent_psus",
    ]


def test_decision_path_is_required_even_when_no_trace_is_available() -> None:
    payload = _payload()
    payload.pop("decision_path", None)
    with pytest.raises(fc.FrameContractError, match="missing required key 'decision_path'"):
        _validate(payload)


@pytest.mark.parametrize("trace", [None, "eligibility:passed", {}, 1, True, ()])
def test_decision_path_requires_an_array(trace: Any) -> None:
    payload = _payload()
    payload["decision_path"] = trace
    with pytest.raises(fc.FrameContractError, match=r"decision_path: expected array"):
        _validate(payload)


@pytest.mark.parametrize("step", [None, 1, 0.5, True, {}, [], ""])
def test_decision_path_steps_require_nonempty_strings(step: Any) -> None:
    payload = _payload()
    payload["decision_path"] = ["synthetic: valid first step", step]
    with pytest.raises(fc.FrameContractError, match=r"decision_path\[1\]:"):
        _validate(payload)


def test_decision_path_preserves_step_order_and_repeated_steps_on_round_trip() -> None:
    payload = _payload()
    trace = ["synthetic: first step", "synthetic: second step", "synthetic: first step"]
    payload["decision_path"] = trace
    restored = json.loads(json.dumps(payload, sort_keys=True))
    _validate(restored)
    assert restored["decision_path"] == trace
    assert restored["verdict"] == payload["verdict"]


def test_explicit_legacy_no_trace_fixture_can_have_an_empty_decision_path() -> None:
    payload = _payload()
    payload["frame_id"] = "synthetic-legacy-no-decision-trace"
    payload["decision_path"] = []
    _validate(payload)
    assert payload["decision_path"] == []


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


def _planning_payload() -> dict[str, Any]:
    payload = _payload()
    # Synthetic tabulated evidence only; no score producer or power calculation.
    payload.update(n_psu=5, min_n_independent=50, cell_floor_n_independent=30, p_d=0.15, power=0.80)
    payload["icc_sensitivity"] = [
        {
            "planning_icc": icc,
            "design_effect": deff,
            "n_eff": float(Fraction(10) / Fraction(str(deff))),
            "n_nonmated_eff": 10.0,
            "primary_resolvable": False,
            "hypotheses": [{"id": "H1", "scored": False, "mde": None,
                            "n_eff": float(Fraction(10) / Fraction(str(deff)))}],
        }
        for icc, deff in [(0.05, 1.5), (0.10, 2.0), (0.20, 3.0)]
    ]
    payload["waterfall"] = [
        {"leg_key": leg, "arm": arm.value, "stage": "embedded", "count": count}
        for leg, count in zip(LEGS, (3, 7), strict=True)
        for arm in fc.Arm
    ]
    return payload


def test_planning_evidence_and_attributed_waterfalls_round_trip(tmp_path: Path) -> None:
    payload = _planning_payload()
    before = copy.deepcopy(payload)
    path = tmp_path / "synthetic-planning-scores.json"
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    restored = json.loads(path.read_text(encoding="utf-8"))
    _validate(restored)
    assert restored == before
    assert restored["schema_version"] == 1
    assert [row["planning_icc"] for row in restored["icc_sensitivity"]] == [0.05, 0.10, 0.20]
    assert {(row["leg_key"], row["arm"]): row["count"] for row in restored["waterfall"]} == {
        (leg, arm.value): count
        for leg, count in zip(LEGS, (3, 7), strict=True)
        for arm in fc.Arm
    }
    for field in ("legs", "primary", "hypotheses", "guardrails", "verdict"):
        assert restored[field] == _payload()[field]


def test_committed_fixture_has_policy_sensitivity_and_waterfall_evidence() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    _validate(payload)
    assert (payload["n_psu"], payload["min_n_independent"], payload["cell_floor_n_independent"]) == (5, 50, 30)
    assert (payload["p_d"], payload["power"]) == (0.15, 0.80)
    assert [row["planning_icc"] for row in payload["icc_sensitivity"]] == [0.05, 0.10, 0.20]
    assert {row["leg_key"] for row in payload["waterfall"]} == set(LEGS)
    assert all(row["arm"] == "native" for row in payload["waterfall"])


@pytest.mark.parametrize("field", ["n_psu", "min_n_independent", "cell_floor_n_independent", "p_d", "power", "icc_sensitivity"])
def test_planning_root_evidence_is_required(field: str) -> None:
    payload = _payload()
    payload.pop(field, None)
    with pytest.raises(fc.FrameContractError, match=field):
        _validate(payload)


@pytest.mark.parametrize("path", ["icc_sensitivity.0", "icc_sensitivity.0.hypotheses.0", "waterfall.0"])
def test_planning_and_waterfall_rows_are_required_and_closed(path: str) -> None:
    payload = _planning_payload()
    _validate(payload)
    for field in tuple(_at(payload, path)):
        removed = copy.deepcopy(payload)
        del _at(removed, path)[field]
        with pytest.raises(fc.FrameContractError):
            _validate(removed)
    _at(payload, path)["invented"] = 1
    with pytest.raises(fc.FrameContractError, match="invented"):
        _validate(payload)


@pytest.mark.parametrize(
    "path,value",
    [
        ("n_psu", True), ("n_psu", -1), ("n_psu", 5.5), ("n_psu", None),
        ("min_n_independent", False), ("min_n_independent", 0), ("min_n_independent", 50.5),
        ("cell_floor_n_independent", True), ("cell_floor_n_independent", 0),
        ("cell_floor_n_independent", "30"),
        ("p_d", False), ("p_d", 0), ("p_d", 1), ("p_d", float("nan")), ("p_d", None),
        ("power", True), ("power", 0), ("power", 1), ("power", float("inf")), ("power", "0.8"),
        ("icc_sensitivity", None), ("icc_sensitivity", {}), ("icc_sensitivity", []),
        ("icc_sensitivity.0.planning_icc", 0.1),
        ("icc_sensitivity.0.design_effect", 0), ("icc_sensitivity.0.design_effect", False),
        ("icc_sensitivity.0.n_eff", -1), ("icc_sensitivity.0.n_eff", float("inf")),
        ("icc_sensitivity.0.n_nonmated_eff", -1), ("icc_sensitivity.0.n_nonmated_eff", True),
        ("icc_sensitivity.0.primary_resolvable", 0),
        ("icc_sensitivity.0.hypotheses", None), ("icc_sensitivity.0.hypotheses", []),
        ("icc_sensitivity.0.hypotheses.0.id", ""),
        ("icc_sensitivity.0.hypotheses.0.scored", "unscored"),
        ("icc_sensitivity.0.hypotheses.0.n_eff", -1),
        ("waterfall.0.leg_key", ""), ("waterfall.0.leg_key", None),
        ("waterfall.0.arm", "probability"), ("waterfall.0.arm", "challenge"),
        ("waterfall.0.arm", "invented"), ("waterfall.0.count", True),
    ],
)
def test_planning_evidence_and_waterfall_types_and_bounds(path: str, value: Any) -> None:
    payload = _planning_payload()
    _validate(payload)
    if "." in path:
        parent, field = path.rsplit(".", 1)
        _at(payload, parent)[field] = value
    else:
        payload[path] = value
    with pytest.raises(fc.FrameContractError):
        _validate(payload)


@pytest.mark.parametrize("iccs", [[0.05, 0.10], [0.05, 0.10, 0.20, 0.20], [0.05, 0.10, 0.10], [0.20, 0.10, 0.05]])
def test_sensitivity_requires_each_declared_icc_once_in_ascending_order(iccs: list[float]) -> None:
    payload = _planning_payload()
    _validate(payload)
    row = payload["icc_sensitivity"][0]
    payload["icc_sensitivity"] = [dict(row, planning_icc=icc) for icc in iccs]
    with pytest.raises(fc.FrameContractError):
        _validate(payload)


@pytest.mark.parametrize("mde", [None, -0.1, True, "0.05", float("nan"), float("inf")])
def test_scored_sensitivity_requires_a_finite_nonnegative_mde(mde: Any) -> None:
    payload = _planning_payload()
    hypothesis = payload["icc_sensitivity"][0]["hypotheses"][0]
    hypothesis.update(scored=True, mde=0.05)
    _validate(payload)
    hypothesis["mde"] = mde
    with pytest.raises(fc.FrameContractError):
        _validate(payload)


def test_sensitivity_mde_absence_is_explicit_and_independent_of_verdict_state() -> None:
    payload = _planning_payload()
    _validate(payload)  # unscored MDE is null, including for an inconclusive hypothesis.
    row = payload["icc_sensitivity"][0]
    row["hypotheses"][0].update(scored=True, mde=0.2)
    row["hypotheses"].append({"id": "H2", "scored": True, "mde": 0.25, "n_eff": 4.0})
    before = copy.deepcopy(payload)
    _validate(payload)
    assert payload == before  # Validation does not recompute a verdict from sensitivity.
    row["hypotheses"][0]["scored"] = False
    with pytest.raises(fc.FrameContractError):
        _validate(payload)


def test_mated_search_and_nonmated_source_unit_support_have_distinct_estimands() -> None:
    payload = _planning_payload()
    # Five mated searches in PSU sizes [4, 1]; eight source units in [2, 2, 2, 2].
    # The two pools share two PSUs: distinct union = 4, never 2 + 4 or an image proxy.
    payload.update(n_psu=4, n_units=8)
    for row in payload["icc_sensitivity"]:
        icc = Fraction(str(row["planning_icc"]))
        mated_deff = 1 + (Fraction(17, 5) - 1) * icc
        row.update(design_effect=float(mated_deff), n_eff=float(5 / mated_deff),
                   n_nonmated_eff=float(8 / (1 + icc)))
        row["hypotheses"][0]["n_eff"] = row["n_eff"]
    planning = payload["icc_sensitivity"][1]
    payload.update(design_effect=planning["design_effect"], n_eff=planning["n_eff"],
                   n_nonmated_eff=planning["n_nonmated_eff"])
    _validate(payload)
    assert payload["design_effect"] == pytest.approx(float(Fraction(31, 25)), abs=1e-12)
    assert payload["n_eff"] == pytest.approx(float(Fraction(125, 31)), abs=1e-12)
    assert payload["n_nonmated_eff"] == pytest.approx(float(Fraction(80, 11)), abs=1e-12)
    assert payload["n_eff"] != payload["n_units"] / payload["design_effect"]


def _wire_payload() -> dict[str, Any]:
    """Tabulated synthetic evidence, never a claim of measured gallery outcomes."""
    payload = _payload()
    for leg in payload["legs"]:
        leg["pair_fmr"] = {
            "status": "not_evaluated", "reason": "pair_scores_not_supplied", "data": None,
        }
    payload["joint_gaps"] = [
        {
            "leg_key": LEGS[0], "arm": arm, "scored": False,
            "reason": "synthetic: paired attribution evidence not supplied",
            "n_pairs": 0, "n_psu": 0, "n_eff": 0.0, "delta": None, "interval": None,
            "unavailable_counts": {"native": 2, "attribution": 3},
        }
        for arm in ("gt_crop_redetect", "cached_yunet_landmark_replay")
    ]
    payload["cells"][0].update(
        query_occluder="mask+sunglasses", enrolled_occluder="unknown",
        data_origin="synthetic", n_identities=4, n_eff=5.0, interval=None,
    )
    payload["guardrails"][0]["evidence"] = {
        "leg_key": LEGS[0], "cohort": "synthetic: mask+sunglasses",
        "n_units": 10, "n_psu": 5, "n_eff": 5.0, "limit": 0.01,
        "reason": "synthetic: below declared cell floor",
    }
    return payload


def test_final_wire_round_trip_keeps_explicit_absences_and_synthetic_origin() -> None:
    payload = _wire_payload()
    restored = json.loads(json.dumps(payload, sort_keys=True))
    _validate(restored)
    assert restored == payload
    assert restored["cells"][0]["data_origin"] == "synthetic"
    assert restored["cells"][0]["n_psu"] < restored["cell_floor_n_independent"]
    assert restored["cells"][0]["scored"] is False
    assert all(leg["pair_fmr"]["reason"] == "pair_scores_not_supplied" for leg in restored["legs"])


def test_ordinary_interval_nonrejection_has_no_invented_reason() -> None:
    payload = _payload()
    # The schema cannot compare a paired interval with a sealed margin or check
    # eligibility arithmetic. Those remain producer responsibilities, as do named
    # reasons when a real eligibility check fails. These inputs are synthetic.
    payload.update(admissibility="confirmatory", n_psu=100, n_units=1000,
                   n_nonmated_eff=1000.0, n_eff=500.0)
    payload["primary"]["resolvable"] = True
    payload["guardrails"] = []
    payload["verdict"].update(state="inconclusive", reason=None)
    payload["hypotheses"][0].update(
        state="inconclusive", reason=None, n_eff=500.0, mde=0.03,
        interval={"lower": -0.01, "upper": 0.04, "level": 0.95},
    )
    _validate(payload)
    assert payload["hypotheses"][0]["interval"]["lower"] <= 0


@pytest.mark.parametrize("reason", [reason.value for reason in fc.InconclusiveReason])
def test_named_inconclusive_reasons_remain_representable(reason: str) -> None:
    payload = _payload()
    payload["verdict"]["reason"] = reason
    payload["hypotheses"][0]["reason"] = reason
    _validate(payload)


@pytest.mark.parametrize("reason", ["inconclusive", "interval_not_rejected", "", False, {}])
@pytest.mark.parametrize("path", ["verdict", "hypotheses.0"])
def test_no_generic_or_untyped_inconclusive_reason_is_added(path: str, reason: Any) -> None:
    payload = _payload()
    _at(payload, path)["reason"] = reason
    with pytest.raises(fc.FrameContractError):
        _validate(payload)


@pytest.mark.parametrize("path", [
    "joint_gaps.0", "joint_gaps.0.unavailable_counts", "cells.0",
    "legs.0.pair_fmr", "guardrails.0.evidence",
])
def test_final_wire_rows_require_all_fields_and_reject_unknown_fields(path: str) -> None:
    payload = _wire_payload()
    _validate(payload)
    for field in _at(payload, path):
        removed = copy.deepcopy(payload)
        del _at(removed, path)[field]
        with pytest.raises(fc.FrameContractError):
            _validate(removed)
    _at(payload, path)["invented"] = 1
    with pytest.raises(fc.FrameContractError, match="invented"):
        _validate(payload)


def test_joint_gaps_required_but_empty_array_is_explicitly_valid() -> None:
    payload = _wire_payload()
    payload["joint_gaps"] = []
    _validate(payload)
    del payload["joint_gaps"]
    with pytest.raises(fc.FrameContractError, match="joint_gaps"):
        _validate(payload)


@pytest.mark.parametrize("path,value", [
    ("joint_gaps", None), ("joint_gaps", {}), ("joint_gaps.0.leg_key", ""),
    ("joint_gaps.0.arm", "native"), ("joint_gaps.0.arm", "probability"),
    ("joint_gaps.0.scored", 0), ("joint_gaps.0.n_pairs", True),
    ("joint_gaps.0.n_pairs", -1), ("joint_gaps.0.n_psu", 1.5),
    ("joint_gaps.0.n_eff", float("nan")), ("joint_gaps.0.n_eff", -1),
    ("joint_gaps.0.reason", None), ("joint_gaps.0.reason", ""),
    ("joint_gaps.0.delta", 0.0), ("joint_gaps.0.interval", {}),
    ("joint_gaps.0.unavailable_counts.native", False),
    ("joint_gaps.0.unavailable_counts.attribution", -1),
    ("cells.0.data_origin", None), ("cells.0.data_origin", "observed"),
    ("cells.0.data_origin", True), ("cells.0.n_identities", True),
    ("cells.0.n_identities", -1), ("cells.0.n_identities", 1.5),
    ("cells.0.n_eff", -1), ("cells.0.n_eff", float("inf")),
    ("cells.0.n_eff", "5"), ("cells.0.fnir", 0.0), ("cells.0.interval", {}),
    ("guardrails.0.evidence", None), ("guardrails.0.evidence", "opaque"),
    ("guardrails.0.evidence.leg_key", 1), ("guardrails.0.evidence.cohort", []),
    ("guardrails.0.evidence.n_units", True), ("guardrails.0.evidence.n_psu", -1),
    ("guardrails.0.evidence.n_eff", float("inf")),
    ("guardrails.0.evidence.limit", "0.01"), ("guardrails.0.evidence.reason", {}),
])
def test_final_wire_rejects_wrong_types_origins_and_unscored_measurements(path: str, value: Any) -> None:
    payload = _wire_payload()
    _validate(payload)
    if "." in path:
        parent, field = path.rsplit(".", 1)
        _at(payload, parent)[field] = value
    else:
        payload[path] = value
    with pytest.raises(fc.FrameContractError):
        _validate(payload)


@pytest.mark.parametrize("origin", ["real", "synthetic", "unknown"])
def test_cell_origin_and_occluder_strings_preserve_declared_context(origin: str) -> None:
    payload = _wire_payload()
    for query, enrolled in [("unknown", "clear"), ("clear", "unknown"), ("mask+sunglasses", "mask")]:
        payload["cells"][0].update(data_origin=origin, query_occluder=query, enrolled_occluder=enrolled)
        before = copy.deepcopy(payload)
        _validate(payload)
        assert payload == before  # No origin/gallery membership inferred by validation.


@pytest.mark.parametrize("path", ["joint_gaps.0", "cells.0"])
def test_scored_joint_and_cell_intervals_are_closed_and_typed(path: str) -> None:
    payload = _wire_payload()
    row = _at(payload, path)
    row.update(scored=True, n_psu=40, interval={"lower": -0.1, "upper": 0.3, "level": 0.95})
    if path.startswith("joint"):
        row.update(reason=None, n_pairs=80, n_eff=40.0, delta=0.1)
    else:
        row.update(n_units=80, n_identities=45, n_eff=40.0, fnir=0.1)
        row["interval"]["lower"] = 0.0
    _validate(payload)
    for field in ("lower", "upper", "level"):
        removed = copy.deepcopy(payload)
        del _at(removed, path)["interval"][field]
        with pytest.raises(fc.FrameContractError):
            _validate(removed)
    for field, value in [("lower", False), ("upper", float("inf")), ("level", 0), ("level", 1), ("invented", 0)]:
        changed = copy.deepcopy(payload)
        _at(changed, path)["interval"][field] = value
        with pytest.raises(fc.FrameContractError):
            _validate(changed)
    if path.startswith("joint"):
        for field in ("delta", "interval"):
            changed = copy.deepcopy(payload)
            _at(changed, path)[field] = None
            with pytest.raises(fc.FrameContractError):
                _validate(changed)


def test_pair_fmr_counts_nonmated_pairs_independently_of_search_units() -> None:
    payload = _wire_payload()
    # Seven independently supplied pair scores, versus ten FPIR source units.
    pair_data = {"false_matches": 2, "n_nonmated_pairs": 7, "rate": float(Fraction(2, 7))}
    payload["legs"][0]["pair_fmr"] = _available(pair_data)
    _validate(payload)
    assert pair_data["n_nonmated_pairs"] != payload["n_units"]
    assert pair_data["rate"] == pytest.approx(2 / 7, abs=1e-12)
    for field in pair_data:
        changed = copy.deepcopy(payload)
        del changed["legs"][0]["pair_fmr"]["data"][field]
        with pytest.raises(fc.FrameContractError):
            _validate(changed)
    for field, value in [("false_matches", True), ("false_matches", -1),
                         ("n_nonmated_pairs", 0), ("n_nonmated_pairs", 7.5),
                         ("rate", float("nan")), ("rate", 1.01), ("n_searches", 10)]:
        changed = copy.deepcopy(payload)
        changed["legs"][0]["pair_fmr"]["data"][field] = value
        with pytest.raises(fc.FrameContractError):
            _validate(changed)


@pytest.mark.parametrize("evidence", [
    {"status": "available", "reason": None, "data": None},
    {"status": "available", "reason": "absent", "data": {}},
    {"status": "unavailable", "reason": None, "data": None},
    {"status": "not_evaluated", "reason": "", "data": None},
    {"status": "not_evaluated", "reason": "pair_scores_not_supplied", "data": {}},
    {"status": "unknown", "reason": "absent", "data": None},
])
def test_pair_fmr_absence_obeys_existing_evidence_state_contract(evidence: dict[str, Any]) -> None:
    payload = _wire_payload()
    _validate(payload)
    payload["legs"][0]["pair_fmr"] = evidence
    with pytest.raises(fc.FrameContractError):
        _validate(payload)


@pytest.mark.parametrize("status", ["unavailable", "not_evaluated"])
def test_pair_fmr_explicit_absence_remains_null(status: str) -> None:
    payload = _wire_payload()
    payload["legs"][0]["pair_fmr"] = _absent(status)
    _validate(payload)


def test_optional_guardrail_evidence_has_explicit_nullable_fields() -> None:
    payload = _wire_payload()
    evidence = payload["guardrails"][0].pop("evidence")
    _validate(payload)
    payload["guardrails"][0]["evidence"] = dict.fromkeys(evidence)
    _validate(payload)


def test_committed_fixture_exercises_the_final_synthetic_wire() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    _validate(payload)
    assert all(cell["data_origin"] == "synthetic" for cell in payload["cells"])
    assert {row["arm"] for row in payload["joint_gaps"]} == {
        "gt_crop_redetect", "cached_yunet_landmark_replay",
    }
    assert all(row["delta"] is None and row["reason"] for row in payload["joint_gaps"])
    assert all(leg["pair_fmr"] == {
        "status": "not_evaluated", "reason": "pair_scores_not_supplied", "data": None,
    } for leg in payload["legs"])
