"""Offline contract tests; all lifecycle examples below are fictional fixtures."""

import copy
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "benchmarks/tools/evalops/simulate.py"
SPEC = importlib.util.spec_from_file_location("evalops_simulate", MODULE)
SIM = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SIM)
CREATE = ["novice", "create", "simple", "none"]
UPDATE = ["operator", "update", "multi_turn", "recover"]
CANCEL = ["novice", "cancel", "multi_turn", "ambiguous"]


def request(*tuples, **changes):
    value = {
        "schema": "evalops.simulate-request.v1",
        "seed": 7,
        "tuples": list(tuples or [CREATE]),
        "budgets": {"steps": 24, "retries": 2, "turns": 12},
        "failures": [],
        "candidate_ids": [],
    }
    value.update(changes)
    return value


def case(axes=CREATE):
    return SIM.generate_cases(request(axes))["cases"][0]


def run(axes=CREATE, failures=None, budgets=None):
    item = case(axes)
    result = SIM.run_case(item, budgets or request()["budgets"], failures or {})
    return item, result


def actions(result):
    return [r for r in result["trace"] if r["kind"] == "action"]


def test_constrained_requested_coverage_and_seed():
    impossible = ["novice", "update", "simple", "ambiguous"]
    req = request(CREATE, UPDATE, CANCEL, impossible)
    first = SIM.generate_cases(req)
    assert first == SIM.generate_cases(copy.deepcopy(req))
    assert first["coverage"]["feasible_requested_tuple_ids"] == sorted("/".join(t) for t in [CREATE, UPDATE, CANCEL])
    assert first["coverage"]["generated_tuple_ids"] == first["coverage"]["feasible_requested_tuple_ids"]
    assert first["coverage"]["rejected_combinations"] == [
        {"tuple_id": "/".join(impossible), "reason": "unsupported_lifecycle_combination"}
    ]
    assert len(first["cases"]) == 3  # no Cartesian expansion
    changed = SIM.generate_cases(dict(req, seed=8))
    assert changed["coverage"] == first["coverage"]
    assert changed["cases"] != first["cases"]
    assert all(c["case_id"].startswith("synthetic:") for c in first["cases"])


@pytest.mark.parametrize(
    "axes,expected,title",
    [
        (CREATE, ["create", "complete"], "Lantern"),
        (["operator", "update", "multi_turn", "none"], ["create", "update", "complete"], "Lantern revised"),
        (CANCEL, ["create", "cancel"], "Lantern"),
    ],
)
def test_fixture_lifecycle_and_visible_actions(axes, expected, title):
    item, result = run(axes)
    assert [r["action"] for r in actions(result)] == expected
    assert result["final_state"]["title"] == title
    assert result["final_state"]["status"] == ("cancelled" if axes[1] == "cancel" else "completed")
    assert SIM.check_goal(item["private_goal"], result["final_state"], result["trace"], {})["status"] == "satisfied"
    assert result["usage"] is result["cost"] is None
    assert result["trace"][-1]["kind"] == "outcome"
    if axes[3] == "ambiguous":
        turns = [r for r in result["trace"] if r["kind"] == "turn"]
        assert [r["role"] for r in turns[:3]] == ["user", "assistant", "user"]
        assert "Which fictional item" in turns[1]["text"]


def test_checker_rejects_wrong_state_missing_actions_and_broken_causality():
    item, result = run()
    result["script_claim"] = "success"
    wrong = dict(result["final_state"], status="active")
    assert SIM.check_goal(item["private_goal"], wrong, result["trace"], {})["status"] == "unsatisfied"
    trace = copy.deepcopy(result["trace"])
    trace[2]["cause"] = 999
    assert SIM.check_goal(item["private_goal"], result["final_state"], trace, {})["status"] == "unsatisfied"
    trace = [r for r in result["trace"] if r.get("action") != "complete"]
    assert SIM.check_goal(item["private_goal"], result["final_state"], trace, {})["status"] == "unsatisfied"


def test_recovery_uses_external_failures_and_preserves_trace():
    item, result = run(UPDATE, {"update": 1})
    events = actions(result)
    assert [(r["action"], r["success"]) for r in events] == [
        ("create", True),
        ("update", False),
        ("retry", True),
        ("recover", True),
        ("update", True),
        ("complete", True),
    ]
    assert events[1]["after"]["status"] == "failed"
    assert events[1]["before"]["title"] == "Lantern"
    assert events[1]["after"]["title"] == "Lantern"
    assert (
        SIM.check_goal(item["private_goal"], result["final_state"], result["trace"], {"update": 1})["status"]
        == "satisfied"
    )
    # A script cannot conceal an externally specified failure behind its success string.
    assert SIM.check_goal(item["private_goal"], result["final_state"], result["trace"], {})["status"] == "unsatisfied"


@pytest.mark.parametrize(
    "budgets,failures,reason",
    [
        ({"steps": 24, "retries": 0, "turns": 12}, {"update": 1}, "retry_budget"),
        ({"steps": 24, "retries": 1, "turns": 12}, {"update": 3}, "retry_budget"),
        ({"steps": 1, "retries": 2, "turns": 12}, {}, "step_budget"),
        ({"steps": 24, "retries": 2, "turns": 1}, {}, "turn_budget"),
    ],
)
def test_budgets_bound_failures_and_turns(budgets, failures, reason):
    item, result = run(UPDATE, failures, budgets)
    assert result["stop_reason"] == reason
    assert len(actions(result)) <= budgets["steps"]
    assert sum(r["kind"] == "turn" for r in result["trace"]) <= budgets["turns"]
    assert sum(r["action"] == "retry" for r in actions(result)) <= budgets["retries"]
    assert (
        SIM.check_goal(item["private_goal"], result["final_state"], result["trace"], failures)["status"]
        == "unsatisfied"
    )


def test_failed_action_without_recovery_and_cancel_never_completes():
    item, failed = run(CREATE, {"create": 1})
    assert failed["stop_reason"] == "action_failed"
    assert failed["final_state"]["status"] == "failed"
    assert [r["action"] for r in actions(failed)] == ["create"]
    _, cancelled = run(CANCEL)
    assert "complete" not in [r["action"] for r in actions(cancelled)]
    assert cancelled["stop_reason"] == "cancelled"
    assert SIM.check_goal(None, failed["final_state"], failed["trace"], {})["status"] == "unknown"


def test_hidden_goal_cannot_enter_script_or_visible_trace():
    item = case()
    original = SIM.run_case(item, request()["budgets"], {})
    item["private_goal"] = {"secret": "HIDDEN-CHECKER-SENTINEL"}
    changed = SIM.run_case(item, request()["budgets"], {})
    assert changed == original
    assert "HIDDEN-CHECKER-SENTINEL" not in json.dumps(changed)
    assert "private_goal" not in json.dumps(changed["trace"])


def test_adapter_is_pure_and_rejects_invalid_lifecycle():
    initial = {"status": "absent", "title": None, "pending": None, "resume": None}
    saved = copy.deepcopy(initial)
    created = SIM.transition(initial, "create", "Lantern", False)
    assert initial == saved and created["status"] == "active"
    with pytest.raises(ValueError):
        SIM.transition(initial, "complete", None, False)
    with pytest.raises(ValueError):
        SIM.transition(created, "shell", "echo fake", False)


@pytest.mark.parametrize(
    "data",
    [
        b'{"seed":1,"seed":2}',
        b'{"seed":NaN}',
        b'{"seed":Infinity}',
        b'{"seed":1e999}',
        b"[]",
        b"{",
        b"\xff",
        b'{"x":{"a":1,"a":2}}',
    ],
)
def test_strict_json(data):
    with pytest.raises(ValueError):
        SIM.load_request(data)


@pytest.mark.parametrize(
    "change",
    [
        {"extra": True},
        {"schema": "evalops.simulate-request.v2"},
        {"seed": True},
        {"seed": -1},
        {"seed": 2**32},
        {"seed": 1.0},
        {"tuples": [CREATE, CREATE]},
        {"tuples": []},
        {"tuples": [CREATE] * 65},
        {"tuples": [["unknown", "create", "simple", "none"]]},
        {"tuples": [[True] * 4]},
        {"budgets": {"steps": True, "retries": 1, "turns": 12}},
        {"budgets": {"steps": 33, "retries": 1, "turns": 12}},
        {"budgets": {"steps": 2, "retries": -1, "turns": 12}},
        {"budgets": {"steps": 2, "retries": 1, "turns": 17}},
        {"budgets": {"steps": 2, "retries": 1, "turns": 12, "extra": 0}},
        {"candidate_ids": [True]},
        {"candidate_ids": ["x"] * 9},
        {"failures": [{"tuple_id": "/".join(CREATE), "action": "create", "count": True}]},
        {"failures": [{"tuple_id": "/".join(CREATE), "action": "shell", "count": 1}]},
        {"failures": [{"tuple_id": "unrequested", "action": "create", "count": 1}]},
    ],
)
def test_request_validation(change):
    with pytest.raises(ValueError):
        SIM.generate_cases(request(**change))


def test_input_bytes_and_nesting_are_bounded():
    with pytest.raises(ValueError, match="input size"):
        SIM.load_request(b" " * (SIM.MAX_REQUEST_BYTES + 1))
    with pytest.raises(ValueError):
        SIM.load_request(b"[" * 2000 + b"]" * 2000)


def test_pinned_dataset_stays_quarantined_and_reference_only():
    dataset = ROOT / "benchmarks/experiments/evalops/dataset-v1"
    original = json.loads((dataset / "artifacts/candidates.jsonl").read_bytes().splitlines()[0])
    report = SIM.build(request(CREATE, candidate_ids=[original["candidate_id"]]))
    assert report == SIM.build(request(CREATE, candidate_ids=[original["candidate_id"]]))
    ref = report["candidate_references"][0]
    assert ref["candidate"] == original
    assert ref["candidate"]["status"] == "quarantine"
    assert ref["ground_truth"] is None and ref["oracle"] == "unknown"
    assert ref["execution"] == "not_executed"
    assert report["dataset"]["protocol_sha256"] == original["protocol_sha256"]
    assert report["dataset"]["input_lock_sha256"] == original["input_lock_sha256"]
    assert report["dataset"]["independent_gold_status"] == "needs_labels"
    assert report["acceptance"]["production"] is None
    assert report["acceptance"]["independent_checker"] == "unavailable"
    assert report["llm_users"] == "deferred_not_executed"
    assert report["usage"] is report["cost"] is None
    assert report["cases"][0]["provenance"]["kind"] == "synthetic_scripted_fixture"
    assert report["cases"][0]["ground_truth"] is None
    with pytest.raises(ValueError):
        SIM.build(request(candidate_ids=["agent_errors:nonexistent"]))


def test_changed_dataset_contract_rejected(tmp_path):
    # No raw candidate copying needed: a changed manifest must fail before rows are read.
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "artifacts/manifest.json").write_text("{}")
    with pytest.raises(ValueError, match="dataset manifest pin"):
        SIM.build(request(), dataset_dir=tmp_path)


def cli(*args):
    return subprocess.run([sys.executable, str(MODULE), *map(str, args)], capture_output=True, timeout=10)


def test_cli_demo_exclusive_output_and_strict_errors(tmp_path):
    output = tmp_path / "demo.json"
    first = cli("--demo", "--output", output)
    assert first.returncode == 0, first.stderr
    saved = output.read_bytes()
    assert json.loads(saved)["schema"] == "evalops.offline-simulation.v1"
    second = cli("--demo", "--output", output)
    assert second.returncode != 0 and output.read_bytes() == saved
    req = tmp_path / "request.json"
    req.write_text(json.dumps(request()))
    saved_request = req.read_bytes()
    assert cli("--input", req, "--output", req).returncode != 0
    assert req.read_bytes() == saved_request
    req.write_text('{"secret":"DO-NOT-ECHO","seed":NaN}')
    failed = cli("--input", req, "--output", tmp_path / "bad.json")
    assert failed.returncode != 0 and b"DO-NOT-ECHO" not in failed.stderr
    assert not (tmp_path / "bad.json").exists()
    help_result = cli("--help")
    assert help_result.returncode == 0 and b"offline" in help_result.stdout.lower()
    assert b"--input" in help_result.stdout and b"--demo" in help_result.stdout


def test_cli_request_external_fixture_and_repeatable_bytes(tmp_path):
    req = request(UPDATE, failures=[{"tuple_id": "/".join(UPDATE), "action": "update", "count": 1}])
    source = tmp_path / "request.json"
    source.write_text(json.dumps(req))
    outputs = [tmp_path / "one.json", tmp_path / "two.json"]
    for destination in outputs:
        assert cli("--input", source, "--output", destination).returncode == 0
    assert outputs[0].read_bytes() == outputs[1].read_bytes()
    report = json.loads(outputs[0].read_bytes())
    assert report["runs"][0]["fixture_check"]["status"] == "satisfied"
    assert any(not e["success"] for e in actions(report["runs"][0]))


def test_cli_rejects_nonregular_and_oversized_inputs_without_output(tmp_path):
    fifo = tmp_path / "pipe"
    os.mkfifo(fifo)
    oversized = tmp_path / "large.json"
    oversized.write_bytes(b" " * (SIM.MAX_REQUEST_BYTES + 1))
    output = tmp_path / "out.json"
    for source in (fifo, tmp_path, oversized):
        assert cli("--input", source, "--output", output).returncode != 0
        assert not output.exists()
