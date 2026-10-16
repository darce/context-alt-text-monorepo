"""FB1-S9-DUP-CASE-01: enumerate the frozen cases without rerunning Monte Carlo.

Seed identities below come from the original mc-full-2ff389e7 case results.
These checks establish software enumeration, not statistical acceptance.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.eval_harness import firbench_contract as fc
from scripts.eval_harness import firbench_selftest as sim

_REPO_ROOT = Path(__file__).resolve().parents[4]
_FROZEN_CASES = (
    ("null", 0.05, 9028649230837492747),
    ("null", 0.10, 8387267477996457809),
    ("null", 0.20, 3867740027499651465),
    ("selection", 0.10, 4273552049319947380),
    ("coverage", 0.05, 17462574518964837781),
    ("coverage", 0.10, 4678032095743926671),
    ("coverage", 0.20, 13903644862214891186),
    ("coverage", 0.30, 8899935271631617076),
    ("power", 0.05, 4675052611165457849),
    ("power", 0.10, 8728033394729764174),
    ("power", 0.20, 957151914021821997),
    ("noninferiority", 0.10, 13829843324852331024),
    ("mde", 0.10, 8025251233748738988),
    ("floor", 0.10, 11821836504878828438),
    ("stage", 0.10, 8765822826597407057),
)


@pytest.fixture(scope="module")
def params() -> sim.SimulationParams:
    decision = fc.load_decision_manifest(_REPO_ROOT / "benchmarks/manifests/fir-bench-decision-v1.json")
    return sim.load_params(Path(__file__).parent / "fixtures/firbench_sim_v1.json", decision=decision)


def test_default_grid_has_all_15_cases_once_in_declared_order(params: sim.SimulationParams) -> None:
    before = json.dumps(params.fixture)
    runs = sim._default_runs(params.fixture, sim.SUITES)
    expected = [(suite, icc) for suite, icc, _ in _FROZEN_CASES]
    assert len(runs) == len(set(runs)) == 15
    assert runs == expected
    assert sim._default_runs(params.fixture, sim.SUITES) == runs
    assert json.dumps(params.fixture) == before


def test_coverage_negative_control_is_declared_and_enumerated_once(params: sim.SimulationParams) -> None:
    assert params.fixture["suite_designs"]["coverage"]["0.30"] == "negative_control_coverage/0.30"
    assert params.fixture["acceptance"]["negative_control_icc"] == 0.30
    assert sim._suite_iccs(params.fixture, "coverage") == (0.05, 0.10, 0.20, 0.30)


def test_repeated_suite_requests_keep_first_request_and_metadata_order(params: sim.SimulationParams) -> None:
    requested = ["power", "coverage", "power", "null", "coverage"]
    expected = [
        (suite, icc)
        for suite in ("power", "coverage", "null")
        for declared_suite, icc, _ in _FROZEN_CASES
        if declared_suite == suite
    ]
    assert sim._default_runs(params.fixture, requested) == expected
    assert requested == ["power", "coverage", "power", "null", "coverage"]
    assert sim._default_runs(params.fixture, ()) == []


def test_enumerated_cases_keep_original_seeds_and_full_run_settings(params: sim.SimulationParams) -> None:
    fixture = params.fixture
    assert fixture["acceptance"]["full_replicates"] == 2000
    assert fixture["policy_mirror"]["n_boot"] == params.decision.interval.n_boot == 10000
    assert fixture["policy_mirror"]["bootstrap_seed"] == params.decision.interval.seed == 2429382368
    assert fixture["seeds"]["master_seed"] == 2208172209
    expected_seeds = {(suite, icc): seed for suite, icc, seed in _FROZEN_CASES}
    runs = sim._default_runs(fixture, sim.SUITES)
    assert set(runs) == set(expected_seeds)
    for suite, icc in runs:
        assert sim._suite_seed(fixture, fixture["seeds"]["master_seed"], suite, icc) == expected_seeds[suite, icc]
