"""FIRBENCH-1 S9 acceptance checks: simulated AE-2b, AE-3 and AE-4 rows and their H2, MDE, floor and stage branches.

The simulator (``scripts.eval_harness.firbench_selftest``) and its committed fixture
(``scene/tests/fixtures/firbench_sim_v1.json``) belong to a separate lane. Until they land, every test that
drives the simulator is an honest RED: it fails at import or at the fixture check, is never skipped, and nothing
here stands in for the simulator, the S0 gate, the S3 classifier, ``decide`` or the bootstrap.

Runs without the simulator: the committed decision policy (real S0 loader), the master seed, the exact binomial
bound, the frozen sizing table, the numeric comparison rule, and the make target wiring.

Synthetic identifiers only. Full-R rates are judged with exact Fraction bounds from the pass-rule table; no
Monte Carlo rate receives a tolerance. Nothing here is real GT, human observation or ratification evidence.
"""

from __future__ import annotations

import dataclasses
import hashlib
import importlib
import json
import math
import os
import shutil
import subprocess
import sys
from collections.abc import Mapping
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

from scripts.eval_harness import firbench_contract as fc
from scripts.eval_harness import firbench_legs as legs
from scripts.eval_harness.firbench_cluster_io import _parse_leg_key

SERVICE_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = Path(__file__).resolve().parents[4]
DECISION_PATH = REPO_ROOT / "benchmarks" / "manifests" / "fir-bench-decision-v1.json"
SIM_FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "firbench_sim_v1.json"
EVALS_MK = REPO_ROOT / "mk" / "evals.mk"
MAKE_TARGET = "fir-bench-acceptance"

MASTER_SEED = 2208172209
MASTER_SEED_LABEL = b"FIRBENCH-1/simulator/v1"
SIM_SCHEMA = "firbench-simulator/v1"
ACCEPTANCE_SCHEMA = "firbench-acceptance/v1"
SUITES = ("null", "selection", "coverage", "power", "noninferiority", "mde", "floor", "stage")
FULL_REPLICATES = 2000

# Pass-rule table bounds, as exact rationals. Monte Carlo rates are compared with these, never with a tolerance.
STEP1_MAX = Fraction(32, 1000)  # AE-2b step 1: superior <= 0.032
STEP2_MAX = Fraction(60, 1000)  # AE-2b step 2 and H2(b): <= 0.060
SELECTION_MIN = Fraction(60, 1000)  # selection control: strictly above 0.060
POWER_MIN = Fraction(77, 100)  # AE-4 and H2(a): >= 0.77
COVERAGE_BAND = (Fraction(93, 100), Fraction(97, 100))  # AE-3
ZERO_EFFECT_MAX_SUPERIOR_OF_200 = 9  # 95% upper quantile of Binomial(200, 0.025); proven by the binomial test below
FLOAT_TOLERANCE = 1e-12  # the only tolerance in this lane: float rounding against a Fraction oracle

# Liveness bound for replicate-heavy checks (each replicate runs decide with the manifest n_boot). It is set to
# bound a hang, not to pass a check; the measured runtime is recorded at join.
LONG_RUN_TIMEOUT_S = 3600

SUITE_RUNNERS = (
    ("null", "run_null_suite"),
    ("selection", "run_selection_control"),
    ("coverage", "run_coverage_suite"),
    ("power", "run_power_suite"),
    ("noninferiority", "run_noninferiority_suite"),
    ("mde", "run_mde_suite"),
    ("floor", "run_floor_suite"),
    ("stage", "run_stage_suite"),
)
ROW_KEYS = frozenset(
    {
        "suite",
        "icc",
        "replicates_requested",
        "replicates_completed",
        "n_boot",
        "seed",
        "full_acceptance_evidence",
        "design",
        "metrics",
        "passed",
    }
)
REQUIRED_METRICS = {
    "null": ("h1_superior_count", "h1_superior_rate", "h2_boundary_reject_count", "h2_boundary_reject_rate"),
    "selection": ("h2_postselection_reject_count", "h2_postselection_reject_rate"),
    "coverage": ("psu_coverage_count", "psu_coverage_rate", "image_coverage_count", "image_coverage_rate"),
    "power": ("h1_detect_count", "h1_detect_rate", "cell_only"),
    "noninferiority": (
        "equal_reject_count",
        "equal_reject_rate",
        "boundary_reject_count",
        "boundary_reject_rate",
        "spanning_noninferior_count",
    ),
    "mde": ("refusal_count", "noninferior_count"),
    "floor": ("below_floor_reason", "below_floor_interval_count", "at_floor_passed", "cell_below_floor_scored"),
    "stage": ("drop_count", "native_attribution_gaps"),
}
# Frozen before outcomes (S9 brief sizing table):
# (name, planning ICC, {mated face size: PSU count}, raw n, n_PSU, M~, n_eff target).
SIZING_TABLE = (
    ("power/0.05", Fraction(1, 20), {1: 59, 7: 4, 8: 3, 9: 3}, 138, 69, 5, 115),
    ("power/0.10", Fraction(1, 10), {1: 46, 4: 23}, 138, 69, 3, 115),
    ("power/0.20", Fraction(1, 5), {1: 26, 2: 14, 3: 9, 4: 20}, 161, 69, 3, 115),
    ("null-coverage/0.05", Fraction(1, 20), {1: 96, 16: 24}, 480, 120, 13, 300),
    ("null-coverage/0.10", Fraction(1, 10), {11: 30, 15: 22}, 660, 52, 13, 300),
    ("null-coverage/0.20", Fraction(1, 5), {11: 37, 12: 2, 13: 12, 14: 2, 15: 27}, 1020, 80, 13, 300),
    ("h2/0.10", Fraction(1, 10), {1: 176, 16: 44}, 880, 220, 13, 400),
)
# Fixture evals run by make fir-bench-acceptance, service-relative. The AE mapping is inferred from each module's
# docstring and checks; the coordinator confirms it at join.
FIXTURE_EVAL_TESTS = (
    "scene/tests/test_eval_harness_firbench_contract.py",  # AE-9 refusals, AE-6 legacy_v1 boundary
    "scene/tests/test_eval_harness_firbench_score.py",  # AE-1 known answers, AE-6
    "scene/tests/test_eval_harness_firbench_clusters.py",  # AE-1 B-cubed counts
    "scene/tests/test_eval_harness_firbench_face_outcomes.py",  # AE-6 legacy_v1 outcomes
    "scene/tests/test_eval_harness_firbench_score_calibration.py",  # AE-9 calibration refusals
    "scene/tests/test_eval_harness_firbench_frames_partition.py",  # AE-9 non-mated pool refusal
    "scene/tests/test_eval_harness_firbench_cache_runtime.py",  # AE-8 cache invalidation
    "scene/tests/test_eval_harness_firbench_compare_compatibility.py",  # AE-8 cross-version refusal
    "scene/tests/test_eval_harness_firbench_compare_seals.py",  # AE-9 seal bindings
    "scene/tests/test_eval_harness_firbench_cli_integration.py",  # AE-7 replay
    "scene/tests/test_eval_harness_firbench_report_binding.py",  # AE-7 receipt-bound report
    "scene/tests/test_eval_harness_firbench_score_timing_semantics.py",  # AE-7 timing veto
)


# --- exact comparison rules (item 11) ------------------------------------------------------------


def assert_count_equal(observed: object, expected: int) -> None:
    """Counts are integers compared with ``==``. A bool or a float never passes as a count."""
    assert type(observed) is int and observed == expected, f"count {observed!r} != {expected}"


def assert_rate_matches(value: float, oracle: Fraction) -> None:
    """A float output against an exact Fraction oracle. The 1e-12 bound covers float rounding only."""
    assert abs(value - float(oracle)) <= FLOAT_TOLERANCE, f"{value!r} differs from oracle {oracle}"


def _in_band(count: int, replicates: int, low: Fraction, high: Fraction) -> bool:
    return low <= Fraction(count, replicates) <= high


def _canonical(payload: object) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _design(sizes: Mapping[int, int], icc: Fraction) -> tuple[int, int, Fraction, Fraction]:
    """Raw n, distinct PSUs, M~ and n_eff for declared mated-face sizes (exact)."""
    raw = sum(size * count for size, count in sizes.items())
    mtilde = Fraction(sum(size * size * count for size, count in sizes.items()), raw)
    deff = 1 + (mtilde - 1) * icc
    return raw, sum(sizes.values()), mtilde, Fraction(raw) / deff


def _mated_design(row: Mapping[str, Any]) -> Mapping[str, Any]:
    # Join point: S9 names the mated branch of design "mated" (raw_n, n_psu, size_counts, ...).
    return row["design"]["mated"]


def _leg(record: Any) -> fc.LegKind:
    return _parse_leg_key(record.leg_key)[0]


# --- fixtures ------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def decision() -> fc.DecisionManifest:
    return fc.load_decision_manifest(DECISION_PATH)


@pytest.fixture(scope="module")
def selftest() -> Any:
    """The S9 simulator module. Missing, it is an honest RED here: the dependent test errors, never skips."""
    return importlib.import_module("scripts.eval_harness.firbench_selftest")


@pytest.fixture(scope="module")
def params(selftest: Any, decision: fc.DecisionManifest) -> Any:
    return selftest.load_params(SIM_FIXTURE_PATH, decision=decision)


# --- GREEN without the simulator -----------------------------------------------------------------


def test_committed_decision_policy_values_are_the_frozen_inputs(decision: fc.DecisionManifest) -> None:
    assert decision.decision_id == "fir-bench-decision-v1"
    assert_rate_matches(decision.planning_icc, Fraction(1, 10))
    assert_rate_matches(decision.p_d, Fraction(15, 100))
    assert_rate_matches(decision.power, Fraction(80, 100))
    assert_rate_matches(decision.alpha_family, Fraction(5, 100))
    assert_count_equal(decision.min_n_independent, 50)
    assert_count_equal(decision.cell_floor_n_independent, 30)
    assert_count_equal(decision.interval.n_boot, 10000)
    assert_count_equal(decision.interval.seed, 2429382368)
    by_id = {hypothesis.id: hypothesis for hypothesis in decision.hypotheses}
    assert by_id["H1"].legs == (fc.LegKind.sface, fc.LegKind.auraface)
    assert_rate_matches(by_id["H1"].margin, Fraction(0))
    assert by_id["H2"].legs == (fc.LegKind.auraface, fc.LegKind.insightface)
    assert_rate_matches(by_id["H2"].margin, Fraction(5, 100))
    # S9 never seals or ratifies the real manifest.
    assert decision.seal is None
    assert decision.ratification.decision_ref is None and decision.ratification.ratified_at is None


def test_master_seed_is_the_first_32_bits_of_the_label_digest() -> None:
    digest = hashlib.sha256(MASTER_SEED_LABEL).digest()
    assert_count_equal(int.from_bytes(digest[:4], "big"), MASTER_SEED)


def test_nine_of_200_is_the_95_percent_upper_quantile_of_binomial() -> None:
    p = Fraction(25, 1000)

    def tail(k: int) -> Fraction:
        return sum(Fraction(math.comb(200, i)) * p**i * (1 - p) ** (200 - i) for i in range(k + 1))

    assert tail(ZERO_EFFECT_MAX_SUPERIOR_OF_200 - 1) < Fraction(95, 100) <= tail(ZERO_EFFECT_MAX_SUPERIOR_OF_200)


def test_full_replicate_count_thresholds_are_exact_integers_at_2000() -> None:
    assert STEP1_MAX * FULL_REPLICATES == 64
    assert STEP2_MAX * FULL_REPLICATES == 120
    assert POWER_MIN * FULL_REPLICATES == 1540
    assert COVERAGE_BAND[0] * FULL_REPLICATES == 1860
    assert COVERAGE_BAND[1] * FULL_REPLICATES == 1940


def test_monte_carlo_standard_errors_match_the_pass_rule_table() -> None:
    def se(p: float) -> float:
        return math.sqrt(p * (1 - p) / FULL_REPLICATES)

    assert round(se(0.025), 5) == 0.00349
    assert round(se(0.05), 5) == 0.00487
    assert round(se(0.80), 4) == 0.0089


@pytest.mark.parametrize(
    ("name", "icc", "sizes", "raw_n", "n_psu", "mtilde", "n_eff"),
    SIZING_TABLE,
    ids=[row[0] for row in SIZING_TABLE],
)
def test_frozen_sizing_attains_its_exact_n_eff(
    name: str, icc: Fraction, sizes: dict[int, int], raw_n: int, n_psu: int, mtilde: int, n_eff: int
) -> None:
    raw, psus, observed_mtilde, observed_n_eff = _design(sizes, icc)
    assert_count_equal(raw, raw_n)
    assert_count_equal(psus, n_psu)
    assert observed_mtilde == mtilde
    assert observed_n_eff == n_eff


def test_power_010_split_reproduces_the_declared_cell_allocation(decision: fc.DecisionManifest) -> None:
    clear_to_mask = {1: 23, 4: 12}
    clear_to_clear = {1: 23, 4: 11}
    assert_count_equal(clear_to_mask[1] + clear_to_clear[1], 46)
    assert_count_equal(clear_to_mask[4] + clear_to_clear[4], 23)
    assert_count_equal(sum(clear_to_mask.values()), 35)
    assert_count_equal(sum(clear_to_clear.values()), 34)
    for cell in (clear_to_mask, clear_to_clear):
        _, n_psu, _, n_eff = _design(cell, Fraction(1, 10))
        assert n_psu >= decision.cell_floor_n_independent
        # The 115 target is global. A cell's own n_eff is reported and never claimed as 115.
        assert n_eff < 115


def test_numeric_rule_rejects_a_count_off_by_one_and_non_integer_counts() -> None:
    assert_count_equal(41, 41)
    with pytest.raises(AssertionError):
        assert_count_equal(40, 41)
    with pytest.raises(AssertionError):
        assert_count_equal(42, 41)
    with pytest.raises(AssertionError):
        assert_count_equal(True, 1)
    with pytest.raises(AssertionError):
        assert_count_equal(41.0, 41)


def test_numeric_rule_tolerates_only_float_rounding_against_a_fraction_oracle() -> None:
    oracle = Fraction(1, 3)
    assert_rate_matches(float(oracle) + 1e-13, oracle)
    with pytest.raises(AssertionError):
        assert_rate_matches(float(oracle) + 1e-9, oracle)


def test_committed_manifest_and_fixture_eval_modules_are_in_this_checkout() -> None:
    assert DECISION_PATH.is_file()
    assert EVALS_MK.is_file()
    missing = [module for module in FIXTURE_EVAL_TESTS if not (SERVICE_ROOT / module).is_file()]
    assert missing == []


def test_make_target_runs_the_cli_then_the_fixture_evals_under_the_dev_profile() -> None:
    make = shutil.which("make")
    assert make is not None, "make is required to inspect the fir-bench-acceptance recipe"
    dry_run = subprocess.run(
        [make, "-n", "-C", str(REPO_ROOT), MAKE_TARGET], capture_output=True, text=True, check=False
    )
    assert dry_run.returncode == 0, dry_run.stderr
    recipe = dry_run.stdout
    assert "scripts.eval_harness.firbench_selftest" in recipe
    for flag in ("--params", "--decision", "--out", "--suites"):
        assert flag in recipe
    assert ",".join(SUITES) in recipe
    assert "env -u ACX_EVAL_BENCH" in recipe
    assert "ACX_EVAL_BENCH=1" not in recipe
    assert "--extra bench" not in recipe
    assert "-n0" in recipe
    for module in FIXTURE_EVAL_TESTS:
        assert module in recipe


# --- RED until the simulator and its fixture land ------------------------------------------------


def test_committed_simulator_fixture_declares_its_schema() -> None:
    assert SIM_FIXTURE_PATH.is_file(), "firbench_sim_v1.json belongs to the S9 simulator lane and is not in this checkout"
    payload = json.loads(SIM_FIXTURE_PATH.read_text(encoding="utf-8"))
    assert payload["schema"] == SIM_SCHEMA


def test_loader_binds_the_fixture_to_the_committed_manifest(selftest: Any, decision: fc.DecisionManifest) -> None:
    loaded = selftest.load_params(SIM_FIXTURE_PATH, decision=decision)
    assert loaded.decision == decision
    assert loaded.suite == "null"
    assert_rate_matches(loaded.icc, Fraction(1, 10))


def test_loader_rejects_an_unknown_fixture_key(selftest: Any, decision: fc.DecisionManifest, tmp_path: Path) -> None:
    payload = json.loads(SIM_FIXTURE_PATH.read_text(encoding="utf-8"))
    payload["unexpected_key"] = 1
    mutated = tmp_path / "firbench_sim_unknown_key.json"
    mutated.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises((ValueError, fc.FirBenchError)):
        selftest.load_params(mutated, decision=decision)


def test_loader_refuses_a_fixture_p_d_that_differs_from_the_manifest(
    selftest: Any, decision: fc.DecisionManifest
) -> None:
    other = dataclasses.replace(decision, p_d=0.20)
    with pytest.raises((ValueError, fc.FirBenchError)):
        selftest.load_params(SIM_FIXTURE_PATH, decision=other)


def test_public_suites_revalidate_a_mutated_decision(selftest: Any, decision: fc.DecisionManifest, params: Any) -> None:
    other = dataclasses.replace(decision, p_d=0.20)
    with pytest.raises((ValueError, fc.FirBenchError)):
        selftest.run_null_suite(dataclasses.replace(params, decision=other), replicates=1, seed=MASTER_SEED)


def test_leg_helper_round_trips_actual_stage_packet_keys(selftest: Any, params: Any) -> None:
    _, control, planted = selftest.simulate(dataclasses.replace(params, suite="stage"), seed=MASTER_SEED)
    for packet in (control, planted):
        records_by_key = {record.leg_key: record for record in packet}
        decoded = set()
        for key, record in records_by_key.items():
            _, _, space, cv, ort = key.split("__")
            kind = _leg(record)
            assert fc.LegId(kind, record.arm, space, cv[2:], ort[3:]).key() == key
            decoded.add((kind, record.arm))
        assert decoded == {
            (kind, arm)
            for kind in (fc.LegKind.sface, fc.LegKind.auraface, fc.LegKind.insightface)
            for arm in fc.Arm
        }


def test_packets_hold_real_s2_records_for_all_three_legs_and_every_mated_gt(selftest: Any, params: Any) -> None:
    frame, control, planted = selftest.simulate(dataclasses.replace(params, suite="power"), seed=MASTER_SEED)
    mated = {face.face_id for face in frame.faces if face.identity_id is not None}
    assert mated
    for packet in (control, planted):
        assert all(type(record) is legs.FaceSearchRecord for record in packet)
        native = [record for record in packet if record.arm == fc.Arm.native]
        assert {_leg(record) for record in native} == {fc.LegKind.sface, fc.LegKind.auraface, fc.LegKind.insightface}
        for leg in (fc.LegKind.sface, fc.LegKind.auraface, fc.LegKind.insightface):
            present = {record.face_id for record in native if _leg(record) is leg}
            assert mated <= present, f"{leg.value} omits mated GT faces; upstream misses must stay"


def test_planted_packet_changes_only_the_sface_observation(selftest: Any, params: Any) -> None:
    _, control, planted = selftest.simulate(dataclasses.replace(params, suite="power"), seed=MASTER_SEED)
    control_by_key = {(record.face_id, _leg(record)): record.to_dict() for record in control if record.arm == fc.Arm.native}
    planted_by_key = {(record.face_id, _leg(record)): record.to_dict() for record in planted if record.arm == fc.Arm.native}
    assert control_by_key.keys() == planted_by_key.keys()
    for (face_id, leg), payload in control_by_key.items():
        if leg is not fc.LegKind.sface:
            assert payload == planted_by_key[(face_id, leg)], f"{leg.value} changed for {face_id}"
    assert any(
        control_by_key[key] != planted_by_key[key] for key in control_by_key if key[1] is fc.LegKind.sface
    ), "the declared SFace treatment did not change any observation"


def test_power_design_at_planning_icc_010_attains_exactly_115(selftest: Any, params: Any) -> None:
    row = selftest.run_power_suite(
        dataclasses.replace(params, suite="power", icc=0.10), replicates=2, seed=MASTER_SEED
    )["semantic"]
    design = _mated_design(row)
    assert_count_equal(design["raw_n"], 138)
    assert_count_equal(design["n_psu"], 69)
    assert {int(size): count for size, count in design["size_counts"].items()} == {1: 46, 4: 23}
    assert_count_equal(design["sum_squared_sizes"], 414)
    assert_rate_matches(design["deff"], Fraction(6, 5))
    assert_rate_matches(design["attained_n_eff"], Fraction(115))
    assert row["metrics"]["cell_only"].keys() >= {"clear_mask", "clear_clear"}


@pytest.mark.parametrize(
    ("suite", "icc", "raw_n", "n_eff"),
    (
        ("null", 0.05, 480, 300),
        ("null", 0.20, 1020, 300),
        ("power", 0.05, 138, 115),
        ("power", 0.20, 161, 115),
    ),
    ids=("null-0.05", "null-0.20", "power-0.05", "power-0.20"),
)
def test_planning_icc_sensitivity_rows_keep_the_stated_n_eff(
    selftest: Any, params: Any, suite: str, icc: float, raw_n: int, n_eff: int
) -> None:
    # Sensitivity rows are reported beside the 0.10 gate and are not gated. Their stated n_eff must still hold,
    # which needs recomputed size counts, not a silent change of the target.
    runner = dict(SUITE_RUNNERS)[suite]
    row = getattr(selftest, runner)(dataclasses.replace(params, suite=suite, icc=icc), replicates=1, seed=MASTER_SEED)[
        "semantic"
    ]
    assert row["icc"] == icc
    design = _mated_design(row)
    assert_count_equal(design["raw_n"], raw_n)
    assert_rate_matches(design["attained_n_eff"], Fraction(n_eff))


def test_insightface_attribution_stays_unavailable_fused_in_stage_packets(selftest: Any, params: Any) -> None:
    _, control, planted = selftest.simulate(dataclasses.replace(params, suite="stage"), seed=MASTER_SEED)
    for packet in (control, planted):
        attribution = [
            record for record in packet if record.arm != fc.Arm.native and _leg(record) is fc.LegKind.insightface
        ]
        assert attribution, "the stage scenario must carry explicit InsightFace attribution rows"
        for record in attribution:
            assert record.arm_availability == fc.ArmStatus.unavailable_fused


@pytest.mark.parametrize(("suite", "runner"), SUITE_RUNNERS, ids=[suite for suite, _ in SUITE_RUNNERS])
def test_every_suite_returns_the_frozen_row_and_is_not_full_evidence_at_r1(
    selftest: Any, params: Any, decision: fc.DecisionManifest, suite: str, runner: str
) -> None:
    result = getattr(selftest, runner)(dataclasses.replace(params, suite=suite), replicates=1, seed=MASTER_SEED)
    assert set(result) == {"semantic", "timing"}
    assert "seconds" in result["timing"]
    row = result["semantic"]
    assert set(row) == ROW_KEYS
    assert row["suite"] == suite
    assert_count_equal(row["replicates_requested"], 1)
    assert_count_equal(row["replicates_completed"], 1)
    assert_count_equal(row["n_boot"], decision.interval.n_boot)  # the manifest bootstrap count is never reduced
    assert row["full_acceptance_evidence"] is False
    assert set(REQUIRED_METRICS[suite]) <= set(row["metrics"])


@pytest.mark.timeout(LONG_RUN_TIMEOUT_S)
def test_null_semantic_results_are_byte_identical_across_two_runs(selftest: Any, params: Any) -> None:
    first = selftest.run_null_suite(params, replicates=50, seed=MASTER_SEED)
    second = selftest.run_null_suite(params, replicates=50, seed=MASTER_SEED)
    assert _canonical(first["semantic"]) == _canonical(second["semantic"])


@pytest.mark.timeout(LONG_RUN_TIMEOUT_S)
def test_zero_planted_effect_is_superior_in_at_most_nine_of_200(selftest: Any, params: Any) -> None:
    row = selftest.run_null_suite(params, replicates=200, seed=MASTER_SEED)["semantic"]
    assert_count_equal(row["replicates_completed"], 200)
    assert row["full_acceptance_evidence"] is False
    assert row["metrics"]["h1_superior_count"] <= ZERO_EFFECT_MAX_SUPERIOR_OF_200


@pytest.mark.timeout(LONG_RUN_TIMEOUT_S)
def test_image_level_interval_on_clustered_fixture_fails_the_coverage_band(selftest: Any, params: Any) -> None:
    # ICC 0.3 negative control: the image-level bootstrap treats pseudoreplicated images as independent units.
    clustered = dataclasses.replace(params, suite="coverage", icc=0.30)
    row = selftest.run_coverage_suite(clustered, replicates=50, seed=MASTER_SEED)["semantic"]
    replicates = row["replicates_completed"]
    assert_count_equal(replicates, 50)
    assert not _in_band(row["metrics"]["image_coverage_count"], replicates, *COVERAGE_BAND), (
        "the broken image-level interval must fail the AE-3 band"
    )


@pytest.mark.timeout(LONG_RUN_TIMEOUT_S)
def test_post_run_selection_inflates_the_boundary_rate_above_the_bound(selftest: Any, params: Any) -> None:
    row = selftest.run_selection_control(
        dataclasses.replace(params, suite="selection"), replicates=100, seed=MASTER_SEED
    )["semantic"]
    assert Fraction(row["metrics"]["h2_postselection_reject_count"], row["replicates_completed"]) > SELECTION_MIN


def test_floor_suite_refuses_49_psus_without_an_interval_and_passes_50(selftest: Any, params: Any) -> None:
    metrics = selftest.run_floor_suite(dataclasses.replace(params, suite="floor"), replicates=3, seed=MASTER_SEED)[
        "semantic"
    ]["metrics"]
    assert metrics["below_floor_reason"] == fc.InconclusiveReason.insufficient_independent_psus.value
    assert_count_equal(metrics["below_floor_interval_count"], 0)
    assert metrics["at_floor_passed"] is True
    assert_count_equal(metrics["cell_below_floor_scored"], 0)  # pair cells under 30 PSUs are not scored


def test_mde_refusal_fires_in_every_replicate_and_never_non_inferior(selftest: Any, params: Any) -> None:
    row = selftest.run_mde_suite(dataclasses.replace(params, suite="mde"), replicates=20, seed=MASTER_SEED)["semantic"]
    assert_count_equal(row["metrics"]["refusal_count"], row["replicates_completed"])
    assert_count_equal(row["metrics"]["noninferior_count"], 0)


def test_h2_interval_spanning_delta_is_inconclusive_never_non_inferior(selftest: Any, params: Any) -> None:
    row = selftest.run_noninferiority_suite(
        dataclasses.replace(params, suite="noninferiority"), replicates=20, seed=MASTER_SEED
    )["semantic"]
    assert_count_equal(row["metrics"]["spanning_noninferior_count"], 0)


def test_stage_defect_drops_exactly_the_floor_of_ten_percent_of_mated_faces(selftest: Any, params: Any) -> None:
    row = selftest.run_stage_suite(dataclasses.replace(params, suite="stage"), replicates=5, seed=MASTER_SEED)["semantic"]
    n_mated = _mated_design(row)["raw_n"]
    assert_count_equal(
        row["metrics"]["drop_count"], math.floor(Fraction(n_mated, 10)) * row["replicates_completed"]
    )


def test_acceptance_report_identity_ignores_timing(selftest: Any, params: Any) -> None:
    results = [selftest.run_null_suite(params, replicates=1, seed=MASTER_SEED)]
    first = selftest.acceptance_report(results)
    retimed = selftest.acceptance_report([dict(results[0], timing={"seconds": 1e6})])
    assert _canonical(first["semantic"]) == _canonical(retimed["semantic"])
    assert first["semantic"]["schema"] == ACCEPTANCE_SCHEMA
    assert first["semantic"]["full_acceptance_evidence"] is False
    assert "timing" in first


def test_acceptance_report_never_turns_an_unrun_or_pending_eval_into_a_pass(selftest: Any, params: Any) -> None:
    report = selftest.acceptance_report([selftest.run_null_suite(params, replicates=1, seed=MASTER_SEED)])["semantic"]
    assert report["full_acceptance_evidence"] is False
    for ae_id in ("AE-3", "AE-4", "AE-5", "AE-10"):
        assert report["evals"][ae_id]["status"] != "pass", f"{ae_id} passed without supplied evidence"


def test_cli_refuses_an_output_directory_outside_benchmarks_private(tmp_path: Path) -> None:
    out = tmp_path / "acceptance"
    env = {key: value for key, value in os.environ.items() if key != "ACX_EVAL_BENCH"}
    env["PYTHONPATH"] = str(SERVICE_ROOT)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.eval_harness.firbench_selftest",
            "--params",
            str(SIM_FIXTURE_PATH),
            "--decision",
            str(DECISION_PATH),
            "--out",
            str(out),
            "--replicates",
            "1",
            "--suites",
            "null",
        ],
        cwd=SERVICE_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert "No module named" not in result.stderr, "the simulator module is missing, so the refusal was not exercised"
    assert result.returncode != 0
    assert not (out / "acceptance.json").exists()
