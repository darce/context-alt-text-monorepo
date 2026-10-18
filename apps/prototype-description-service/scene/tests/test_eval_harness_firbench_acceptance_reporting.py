"""Reporting evidence boundaries using real R=1 public suites, never invented MC passes."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from scripts.eval_harness import firbench_contract as fc
from scripts.eval_harness import firbench_selftest as selftest

REPO_ROOT = Path(__file__).resolve().parents[4]
MASTER_SEED = 2208172209
SUITE_EVALS = {
    "null": "AE-2b",
    "selection": "selection-control",
    "coverage": "AE-3",
    "power": "AE-4",
    "noninferiority": "H2-branches",
    "mde": "MDE-refusal",
    "floor": "eligibility-floors",
    "stage": "stage-defect",
}
REAL_CLAIMS = {"AE-5": "AE-5", "AE-6": "AE-6-real", "AE-10": "AE-10", "AE-12": "AE-12"}
FIXTURE_EVALS = ("AE-1", "AE-6-fixture", "AE-7", "AE-8", "AE-9")


@pytest.fixture(scope="module")
def params():
    decision = fc.load_decision_manifest(REPO_ROOT / "benchmarks/manifests/fir-bench-decision-v1.json")
    return selftest.load_params(Path(__file__).parent / "fixtures/firbench_sim_v1.json", decision=decision)


@pytest.fixture(scope="module")
def suite_results(params):
    runners = (
        selftest.run_null_suite,
        selftest.run_selection_control,
        selftest.run_coverage_suite,
        selftest.run_power_suite,
        selftest.run_noninferiority_suite,
        selftest.run_mde_suite,
        selftest.run_floor_suite,
        selftest.run_stage_suite,
    )
    return tuple(
        runner(dataclasses.replace(params, suite=suite), replicates=1, seed=MASTER_SEED)
        for suite, runner in zip(SUITE_EVALS, runners, strict=True)
    )


@pytest.mark.parametrize("shape", ("empty", "subset", "eight_rows"))
def test_real_claims_stay_explicitly_pending_and_fixture_evals_stay_unrun(shape, suite_results):
    results = {"empty": (), "subset": suite_results[:1], "eight_rows": suite_results}[shape]
    semantic = selftest.acceptance_report(results)["semantic"]
    assert semantic["full_acceptance_evidence"] is False
    assert semantic["pending"] == selftest._pending_claims()
    for ae_id, pending_id in REAL_CLAIMS.items():
        claim = semantic["evals"][ae_id]
        assert claim["status"] == "pending"
        assert claim["details"] == semantic["pending"][pending_id]
        assert claim["details"]
    for ae_id in FIXTURE_EVALS:
        assert semantic["evals"][ae_id]["status"] == "not_run"
        assert semantic["evals"][ae_id]["details"]
    assert semantic["evals"]["AE-6"] != semantic["evals"]["AE-6-fixture"]


def test_empty_report_has_no_suites_or_synthetic_passes():
    report = selftest.acceptance_report(())
    semantic = report["semantic"]
    assert semantic["schema"] == "firbench-acceptance/v1"
    assert semantic["rows"] == semantic["suites_run"] == []
    assert semantic["suites_missing"] == sorted(SUITE_EVALS)
    assert semantic["full_acceptance_evidence"] is False
    assert all(semantic["evals"][ae_id]["status"] == "not_run" for ae_id in SUITE_EVALS.values())
    assert report["timing"] == {"seconds_total": 0.0, "per_row_seconds": []}


@pytest.mark.parametrize("omitted", (None, *SUITE_EVALS))
def test_actual_small_r_suites_and_subsets_never_become_full_evidence(omitted, suite_results):
    results = tuple(result for result in suite_results if result["semantic"]["suite"] != omitted)
    semantic = selftest.acceptance_report(results)["semantic"]
    assert semantic["suites_run"] == sorted(set(SUITE_EVALS) - {omitted})
    assert semantic["suites_missing"] == ([] if omitted is None else [omitted])
    assert semantic["full_acceptance_evidence"] is False
    assert len(semantic["rows"]) == len(results)
    for suite, ae_id in SUITE_EVALS.items():
        evaluation = semantic["evals"][ae_id]
        if suite == omitted:
            assert evaluation["status"] == "not_run"
        else:
            assert evaluation["status"] == "not_full_evidence"
            assert evaluation["full_acceptance_evidence"] is False
            assert evaluation["replicates_requested"] == evaluation["replicates_completed"] == 1
    assert all(result["semantic"]["passed"] is None for result in results)


def test_no_planning_icc_suite_stays_not_run(params):
    result = selftest.run_null_suite(dataclasses.replace(params, icc=0.05), replicates=1, seed=MASTER_SEED)
    semantic = selftest.acceptance_report((result,))["semantic"]
    assert semantic["suites_run"] == ["null"]
    assert semantic["suites_missing"] == sorted(set(SUITE_EVALS) - {"null"})
    assert all(semantic["evals"][ae_id]["status"] == "not_run" for ae_id in SUITE_EVALS.values())
    assert semantic["full_acceptance_evidence"] is False


def test_actual_report_semantic_identity_excludes_timing_ticks_and_input_order(suite_results):
    first = selftest.acceptance_report(suite_results)
    retimed = selftest.acceptance_report(
        tuple(dict(result, timing={"seconds": float(index + 1)}) for index, result in enumerate(suite_results))
    )
    reversed_report = selftest.acceptance_report(tuple(reversed(suite_results)))
    def canonical(value):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)

    assert canonical(first["semantic"]) == canonical(retimed["semantic"]) == canonical(reversed_report["semantic"])
    assert retimed["timing"]["seconds_total"] == 36.0
    assert retimed["timing"]["per_row_seconds"] == [float(index + 1) for index in range(8)]
