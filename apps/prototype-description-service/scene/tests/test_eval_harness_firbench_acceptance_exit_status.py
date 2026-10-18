"""CLI status/I/O unit replay of frozen full results, plus real R=1 integration.

Recorded dispatch returns are not new statistical/MC evidence. Only the smoke
test executes suites; it replaces no scoring, statistics, bootstrap or RNG.
Counterfactual control/completion tests edit copies and make no MC claims.
"""

from __future__ import annotations

import copy
import importlib.metadata
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.eval_harness import firbench_selftest as selftest

SERVICE_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = SERVICE_ROOT.parents[1]
FIXTURE = Path(__file__).parent / "fixtures/firbench_acceptance_cli_v6.json"
PARAMS = Path(__file__).parent / "fixtures/firbench_sim_v1.json"
DECISION = REPO_ROOT / "benchmarks/manifests/fir-bench-decision-v1.json"


@pytest.fixture
def recorded():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def cli(tmp_path, monkeypatch):
    # Keep artifact I/O under the real private-path validator in isolated /tmp.
    monkeypatch.setattr(selftest, "_REPO_ROOT", tmp_path)
    target = tmp_path / "benchmarks/private/acceptance/acceptance.json"

    def run(*options):
        rc = selftest.main([
            "--params", str(PARAMS), "--decision", str(DECISION),
            "--out", str(target.parent), *options,
        ])
        assert target.is_file(), "the result artifact must survive either exit status"
        return rc, json.loads(target.read_text(encoding="utf-8"))

    return run


@pytest.fixture
def replay(recorded, monkeypatch):
    """Replace only suite dispatch, leaving params, enumeration and report real."""
    calls = []
    cases = recorded["cases"]

    def runner_for(suite):
        def runner(params, *, replicates, seed):
            case = f"{suite}-{round(params.icc * 100):02d}"
            result = copy.deepcopy(cases[case]["result"])
            row = result["semantic"]
            assert (row["suite"], row["icc"]) == (suite, params.icc)
            assert replicates == row["replicates_requested"] == 2000
            assert seed == row["seed"]
            calls.append(case)
            return result
        return runner

    monkeypatch.setattr(selftest, "_SUITE_RUNNERS", {
        suite: runner_for(suite) for suite in selftest.SUITES
    })
    return calls


def assert_raw_report_unchanged(report, recorded, calls):
    assert report == selftest.acceptance_report([
        recorded["cases"][case]["result"] for case in calls
    ])
    assert report["semantic"]["pending"] == selftest._pending_claims()
    assert all(report["semantic"]["evals"][key]["status"] == "pending"
               for key in ("AE-5", "AE-6", "AE-10", "AE-12"))


def test_exact_environment_and_own_module_origins():
    assert len({dist.metadata["Name"] for dist in importlib.metadata.distributions()}) == 130
    assert importlib.util.find_spec("insightface") is None
    assert Path(selftest.__file__).resolve() == SERVICE_ROOT / "scripts/eval_harness/firbench_selftest.py"
    for module in (selftest.fc, selftest.ff, selftest.fl, selftest.fs):
        assert Path(module.__file__).resolve().is_relative_to(SERVICE_ROOT)


def test_recorded_source_and_failed_baselines_remain_explicit(recorded):
    assert recorded["accepted_code_sha"] == "2ff389e72dbb0e9235f7240b26d9d0a17687bcb3"
    assert recorded["source_tree"] == "943a91311dbe9468ed67f28e6d3d5ca51d9cc625"
    assert (recorded["replicates"], recorded["n_boot"], recorded["master_seed"],
            recorded["bootstrap_seed"]) == (2000, 10000, 2208172209, 2429382368)
    assert len(recorded["cases"]) == 15
    for case in recorded["cases"].values():
        row = case["result"]["semantic"]
        assert row["replicates_requested"] == row["replicates_completed"] == 2000
        assert row["n_boot"] == 10000 and row["full_acceptance_evidence"] is True
        assert len(case["source_result_sha256"]) == 64
    null = recorded["cases"]["null-10"]["result"]["semantic"]
    power = recorded["cases"]["power-10"]["result"]["semantic"]
    assert null["passed"] is power["passed"] is False
    assert null["metrics"]["h2_boundary_reject_rate"] == 0.063
    assert power["metrics"]["cell_only"]["clear_mask"]["detect_rate"] == 0.5565


def test_recorded_full_default_failure_returns_error_after_writing(cli, replay, recorded, capsys):
    rc, report = cli()
    # The concurrent enumeration fix may remove a duplicate coverage-30 call.
    assert set(replay) == set(recorded["cases"])
    assert len(replay) in (15, 16)
    assert_raw_report_unchanged(report, recorded, replay)
    semantic = report["semantic"]
    assert semantic["full_acceptance_evidence"] is False
    assert semantic["evals"]["AE-2b"]["status"] == "fail"
    assert semantic["evals"]["AE-4"]["status"] == "fail"
    assert semantic["evals"]["coverage-negative-control"]["status"] == "expected_fail_observed"
    assert rc != 0, "completed gated failures must reach the CLI/make exit status"
    output = capsys.readouterr().out
    assert "wrote " in output and "failed" in output.lower()


@pytest.mark.parametrize("suite, evaluation", [("null", "AE-2b"), ("power", "AE-4")])
def test_recorded_failed_full_subset_also_returns_error(cli, replay, recorded, suite, evaluation):
    rc, report = cli("--suites", suite)
    assert_raw_report_unchanged(report, recorded, replay)
    assert report["semantic"]["evals"][evaluation]["status"] == "fail"
    assert report["semantic"]["suites_missing"]
    assert rc != 0


@pytest.mark.parametrize("suite", ["coverage", "selection"])
def test_recorded_successful_controls_are_zero_but_shards_are_partial(
    cli, replay, recorded, capsys, suite,
):
    rc, report = cli("--suites", suite)
    assert_raw_report_unchanged(report, recorded, replay)
    assert rc == 0
    assert report["semantic"]["full_acceptance_evidence"] is False
    if suite == "coverage":
        control = report["semantic"]["evals"]["coverage-negative-control"]
        assert control["status"] == "expected_fail_observed"
        assert any(row["passed"] is False for row in report["semantic"]["rows"])
    else:
        assert report["semantic"]["evals"]["selection-control"]["status"] == "pass"
    assert "partial" in capsys.readouterr().out.lower()


def test_counterfactual_negative_control_not_failing_is_cli_error(
    cli, replay, recorded, capsys,
):
    # Status branch only: this copy is explicitly NOT a recorded MC outcome.
    row = recorded["cases"]["coverage-30"]["result"]["semantic"]
    row["passed"] = True
    rc, report = cli("--suites", "coverage")
    assert_raw_report_unchanged(report, recorded, replay)
    assert report["semantic"]["evals"]["coverage-negative-control"]["status"] == "not_failed"
    assert rc != 0
    assert "failed" in capsys.readouterr().out.lower()


@pytest.mark.parametrize("icc", [0.05, 0.20])
def test_recorded_failed_sensitivity_is_report_only(recorded, icc):
    case = f"power-{round(icc * 100):02d}"
    result = recorded["cases"][case]["result"]
    assert result["semantic"]["passed"] is False
    report = selftest.acceptance_report([result])
    assert report["semantic"]["findings"] == [f"sensitivity power at icc {icc} failed (report only)"]
    rc, message = selftest._acceptance_cli_status(report, gated_icc=0.10, negative_control_icc=0.30)
    assert rc == 0 and "partial" in message.lower()


@pytest.mark.parametrize("case", ["coverage-10", "coverage-30"])
def test_incomplete_full_case_does_not_pass(cli, replay, recorded, case, capsys):
    # A counterfactual interrupted producer; no metrics are recomputed.
    row = recorded["cases"][case]["result"]["semantic"]
    row["replicates_completed"] -= 1
    rc, report = cli("--suites", "coverage")
    assert_raw_report_unchanged(report, recorded, replay)
    assert report["semantic"]["full_acceptance_evidence"] is False
    assert rc != 0
    assert "failed" in capsys.readouterr().out.lower()


@pytest.mark.parametrize("case", ["coverage-10", "coverage-30"])
def test_counterfactual_unclassified_full_case_is_cli_error(cli, replay, recorded, case):
    recorded["cases"][case]["result"]["semantic"]["passed"] = None
    rc, report = cli("--suites", "coverage")
    assert_raw_report_unchanged(report, recorded, replay)
    assert rc != 0


def test_actual_make_stops_before_fixture_pytest_on_recorded_full_failure(tmp_path):
    # Exercise the unchanged make recipe. The uv shim uses this exact interpreter
    # and recorded dispatch only; it neither resolves nor installs dependencies.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    marker = tmp_path / "fixture-pytest-started"
    target = tmp_path / "benchmarks/private/make/acceptance.json"
    shim = bin_dir / "uv"
    shim.write_text(
        f"#!{sys.executable}\n"
        "import copy, json, pathlib, sys\n"
        "args = sys.argv[sys.argv.index('python') + 1:]\n"
        "if args[:2] == ['-m', 'pytest']:\n"
        f"    pathlib.Path({str(marker)!r}).write_text('started')\n"
        "    raise SystemExit(0)\n"
        "assert args[:2] == ['-m', 'scripts.eval_harness.firbench_selftest']\n"
        "from scripts.eval_harness import firbench_selftest as st\n"
        f"assert pathlib.Path(st.__file__).resolve() == pathlib.Path({str(Path(selftest.__file__).resolve())!r})\n"
        f"st._REPO_ROOT = pathlib.Path({str(tmp_path)!r})\n"
        f"cases = json.loads(pathlib.Path({str(FIXTURE)!r}).read_text())['cases']\n"
        "def runner_for(suite):\n"
        "    def run(params, *, replicates, seed):\n"
        "        result = copy.deepcopy(cases[f'{suite}-{round(params.icc * 100):02d}']['result'])\n"
        "        assert replicates == result['semantic']['replicates_requested'] == 2000\n"
        "        assert seed == result['semantic']['seed']\n"
        "        return result\n"
        "    return run\n"
        "st._SUITE_RUNNERS = {suite: runner_for(suite) for suite in st.SUITES}\n"
        "raise SystemExit(st.main(args[2:]))\n",
        encoding="utf-8",
    )
    shim.chmod(0o755)
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", PYTHONPATH=str(SERVICE_ROOT),
               OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    env.pop("ACX_EVAL_BENCH", None)
    completed = subprocess.run([
        "make", "-f", str(REPO_ROOT / "mk/evals.mk"), "fir-bench-acceptance",
        f"ROOT_MAKEFILE_DIR={REPO_ROOT}", f"FIR_BENCH_SIM_PARAMS={PARAMS}",
        f"FIR_BENCH_DECISION={DECISION}", f"FIR_BENCH_ACCEPTANCE_OUT={target.parent}",
    ], cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=90)
    assert target.is_file(), completed.stdout + completed.stderr
    report = json.loads(target.read_text(encoding="utf-8"))
    assert report["semantic"]["evals"]["AE-2b"]["status"] == "fail"
    assert report["semantic"]["evals"]["AE-4"]["status"] == "fail"
    assert completed.returncode != 0, completed.stdout + completed.stderr
    assert not marker.exists(), "make must stop before its second (fixture pytest) recipe"


def test_real_r1_all_suite_cli_smoke_is_partial(cli, capsys):
    # Actual public runners, B=10000 and frozen seeds; no dispatch replacement.
    rc, report = cli("--replicates", "1")
    semantic = report["semantic"]
    assert rc == 0
    assert semantic["suites_missing"] == []
    assert semantic["full_acceptance_evidence"] is False
    assert len(semantic["rows"]) in (15, 16)
    assert len({(row["suite"], row["icc"]) for row in semantic["rows"]}) == 15
    for row in semantic["rows"]:
        assert row["replicates_requested"] == row["replicates_completed"] == 1
        assert row["n_boot"] == 10000
        assert row["full_acceptance_evidence"] is False and row["passed"] is None
    assert all(semantic["evals"][key]["status"] == "not_full_evidence"
               for key in ("AE-2b", "AE-3", "AE-4", "selection-control", "H2-branches",
                           "MDE-refusal", "eligibility-floors", "stage-defect"))
    assert semantic["pending"] == selftest._pending_claims()
    assert "partial" in capsys.readouterr().out.lower()
