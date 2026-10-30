"""Behavioral contracts for the read-only weekly runner, using real scorers."""

import builtins
import hashlib
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "benchmarks/tools/evalops/run.py"
SEEDS = ROOT / "benchmarks/experiments/evalops"
NOW = "2026-11-10T00:00:00Z"
SINCE = "2026-10-30T00:00:00Z"
UNTIL = "2026-11-09T00:00:00Z"


def dump(path, value, *, lines=False):
    path.write_text("".join(json.dumps(row) + "\n" for row in value) if lines else json.dumps(value))
    return path


@pytest.fixture
def evidence(tmp_path):
    finding = {
        "id": "fnd-1",
        "finding_db_id": 1,
        "finding_id": "R-1",
        "task_ref": "EVALOPS-1",
        "severity": "high",
        "review_mode": "branch",
        "stratum": "high|branch",
        "stratum_population": 1,
        "stratum_sample": 1,
        "weight": 1,
        "human_label": "defect",
        "human_note": "independent fixture decision",
    }
    values = {
        "findings": [finding],
        "qrels": [{"query_id": "q1", "query": "prior failure", "doc_id": "d1", "relevance": 2}],
        "errors": [
            {"id": 1, "error_class": "drift", "created_at": SINCE},
            {"id": 2, "error_class": "drift", "created_at": "2026-11-07T00:00:00Z"},
        ],
        "lessons": [{"decision": "recur: drift", "created_at": "2026-11-07T00:00:00Z"}],
        "results": [{"query_id": "q1", "doc_ids": ["d1", "unjudged"]}],
    }
    return {key: dump(tmp_path / f"{key}.jsonl", value, lines=True) for key, value in values.items()}


def invoke(tmp_path, evidence=None, *extra, mode="script"):
    command = (
        [sys.executable, str(SCRIPT)] if mode == "script" else [sys.executable, "-m", "benchmarks.tools.evalops.run"]
    )
    command += ["--output-dir", str(tmp_path / "reports"), "--now", NOW, "--since", SINCE, "--until", UNTIL]
    for key, path in (evidence or {}).items():
        command += [f"--{key}", str(path)]
    command += list(extra)
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    return subprocess.run(command, cwd=tmp_path, env=env, text=True, capture_output=True, timeout=30)


def successful(result):
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def coverage(tmp_path, errors, **changes):
    data = {
        "since": SINCE,
        "until": UNTIL,
        "complete": True,
        "gaps": [],
        "source": "fixture capture ledger (synthetic test only)",
        "errors_sha256": hashlib.sha256(errors.read_bytes()).hexdigest(),
    }
    data.update(changes)
    return dump(tmp_path / "coverage.json", data)


def test_seed_missing_human_work_is_successful_measurement(tmp_path):
    report = successful(invoke(tmp_path))
    assert report["execution_status"] == "ok"
    assert report["statistical_acceptance"]["status"] == "not_evaluated"
    judge = report["scorers"]["judge"]
    assert judge["status"] == "needs_labels"
    assert judge["coverage"]["findings"] == 100
    assert judge["aggregate"]["rate"] is None
    assert judge["qc"]["status"] == "not_provided"
    assert judge["protocol"]["unknown_fields"]
    retrieval = report["scorers"]["retrieval"]
    assert retrieval["status"] == "unavailable"
    assert retrieval["payload"] is None
    assert "results" in retrieval["reason"]
    assert report["scorers"]["recurrence"]["errors"]["loaded"] == 100
    assert report["scorers"]["recurrence"]["baseline"]["n"] == 441
    assert report["replay"]["status"] == "unknown"
    assert report["replay"]["seven_day_replay_ready"] is False
    assert report["inputs"]["errors"]["support"] == "coded_sample_100_not_census_441"


def test_real_scorers_protocol_provenance_and_repeatability(tmp_path, evidence):
    protocol = {
        "model": "fixture-v1",
        "prompt": "sha256:test",
        "rubric": "v1",
        "decoding": {"temperature": 0},
        "seed": 7,
        "order_handling": "shuffle:7",
    }
    pred = dump(
        tmp_path / "predictions.json", {"predictions": [{"id": "fnd-1", "label": "defect"}], "protocol": protocol}
    )
    qc = dump(
        tmp_path / "qc.json",
        {
            "decisions": [
                {
                    "decision_id": "a",
                    "item_id": "fnd-1",
                    "annotator": "person",
                    "field": "label",
                    "label": "defect",
                    "gold_label": "defect",
                }
            ]
        },
    )
    args = (
        "--predictions",
        str(pred),
        "--qc",
        str(qc),
        "--k",
        "2",
        "--pool-depth",
        "10",
        "--pool-contributor",
        "lexical",
    )
    first = successful(invoke(tmp_path, evidence, *args))
    second = successful(invoke(tmp_path, evidence, *args, mode="module"))
    assert first == second
    assert first["scorers"]["judge"]["aggregate"]["rate"] == 1
    assert first["scorers"]["judge"]["prediction_source"] == "explicit"
    assert first["scorers"]["judge"]["protocol"]["unknown_fields"] == []
    assert first["scorers"]["judge"]["qc"]["status"] == "insufficient_support"
    retrieval = first["scorers"]["retrieval"]["payload"]
    assert retrieval["macro"]["2"]["recall_at_k"]["value"] == 1
    assert retrieval["macro"]["2"]["coverage"]["unjudged_at_k"]["value"] == 0.5
    assert retrieval["pool"]["metadata_status"] == "supplied"
    assert first["scorers"]["recurrence"]["windows"]["post"]["classes"]["drift"]["recurrences_after_prior"] == 1
    assert first["statistical_acceptance"]["status"] == "not_evaluated"
    assert first["window"]["duration_seconds"] == 864000
    assert len(first["code"]["tree_sha"]) == 40
    assert (
        first["code"]["tree_sha"]
        == subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD^{tree}"], text=True).strip()
    )
    assert (
        first["code"]["executed_files"]["benchmarks/tools/evalops/run.py"]["sha256"]
        == hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
    )
    for key, path in {**evidence, "predictions": pred, "qc": qc}.items():
        assert first["inputs"][key]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        assert first["inputs"][key]["bytes"] == path.stat().st_size
    artifacts = list((tmp_path / "reports").glob("*.json"))
    assert len(artifacts) == 2
    assert all(json.loads(path.read_text()) == first for path in artifacts)


def test_explicit_empty_rankings_are_distinct_from_missing(tmp_path, evidence):
    evidence["results"].write_text("")
    retrieval = successful(invoke(tmp_path, evidence))["scorers"]["retrieval"]
    assert retrieval["status"] == "scored"
    assert retrieval["payload"]["macro"]["5"]["recall_at_k"]["value"] == 0


@pytest.mark.parametrize("kind", ["unknown", "short", "mature", "gap", "incomplete", "naive", "unknown_time"])
def test_maturity_requires_actual_coverage(tmp_path, evidence, kind):
    extra = []
    changes = {}
    if kind == "short":
        changes["since"] = "2026-11-07T00:00:00Z"
    elif kind == "gap":
        changes["gaps"] = [
            {"since": "2026-11-01T00:00:00Z", "until": "2026-11-02T00:00:00Z", "reason": "capture stopped"}
        ]
    elif kind == "incomplete":
        changes["complete"] = False
    elif kind in ("naive", "unknown_time"):
        rows = [json.loads(line) for line in evidence["errors"].read_text().splitlines()]
        rows[0]["created_at"] = "2026-10-30 00:00:00" if kind == "naive" else None
        dump(evidence["errors"], rows, lines=True)
    if kind != "unknown":
        extra = ["--coverage", str(coverage(tmp_path, evidence["errors"], **changes))]
    report = successful(invoke(tmp_path, evidence, *extra))
    assert report["replay"]["seven_day_replay_ready"] is (kind == "mature")
    assert report["replay"]["status"] == (
        "mature" if kind == "mature" else "unknown" if kind == "unknown" else "insufficient"
    )
    if kind == "short":
        assert report["replay"]["covered_seconds"] == 172800
    if kind == "mature":
        assert report["replay"]["covered_seconds"] == 864000
        assert report["replay"]["timestamp_support"]["valid_aware"] == 2
    if kind == "gap":
        assert report["replay"]["covered_seconds"] == 777600
    if kind == "incomplete":
        assert report["replay"]["covered_seconds"] is None


def test_external_errors_do_not_implicitly_mix_in_seed_lessons(tmp_path, evidence):
    report = successful(invoke(tmp_path, {k: v for k, v in evidence.items() if k != "lessons"}))
    assert report["inputs"]["lessons"]["status"] == "unavailable"
    assert report["scorers"]["recurrence"]["lessons"]["loaded"] == 0


def test_overlapping_capture_gaps_count_once(tmp_path, evidence):
    path = coverage(
        tmp_path,
        evidence["errors"],
        gaps=[
            {"since": "2026-11-01T00:00:00Z", "until": "2026-11-03T00:00:00Z", "reason": "interruption"},
            {"since": "2026-11-02T00:00:00Z", "until": "2026-11-04T00:00:00Z", "reason": "overlap"},
        ],
    )
    report = successful(invoke(tmp_path, evidence, "--coverage", str(path)))
    assert report["replay"]["covered_seconds"] == 604800
    assert report["replay"]["seven_day_replay_ready"] is False


@pytest.mark.parametrize(
    "key,bad",
    [
        ("findings", '{"id":'),
        ("qrels", "{}\n"),
        ("errors", "[]\n"),
        ("lessons", '{"created_at":true}\n'),
        ("results", '{"query_id":"q1","doc_ids":"d1"}\n'),
        ("errors", '{"open_codes":"bad"}\n'),
        ("errors", '{"created_at":"garbage"}\n'),
        ("errors", '{"created_at":null,"created_at":null}\n'),
        ("errors", '{"error_class":NaN}\n'),
    ],
)
def test_malformed_or_truncated_input_fails_loudly(tmp_path, evidence, key, bad):
    evidence[key].write_text(bad)
    result = invoke(tmp_path, evidence)
    assert result.returncode == 2
    assert json.loads(result.stderr)["execution_status"] == "error"
    assert not list((tmp_path / "reports").glob("*.json"))


@pytest.mark.parametrize(
    "key,bad",
    [
        ("predictions", {"predictions": {}}),
        ("qc", {"decisions": [{}]}),
        ("predictions", {"predictions": [], "unexpected": True}),
    ],
)
def test_optional_evidence_schema_is_not_ignored(tmp_path, evidence, key, bad):
    path = dump(tmp_path / f"{key}.json", bad)
    assert invoke(tmp_path, evidence, f"--{key}", str(path)).returncode == 2


@pytest.mark.parametrize("flag", ["--predictions", "--qc", "--coverage", "--results", "--lessons", "--db"])
def test_supplied_missing_paths_are_errors(tmp_path, flag):
    result = invoke(tmp_path, None, flag, str(tmp_path / "absent"))
    assert result.returncode == 2
    assert json.loads(result.stderr)["execution_status"] == "error"


def test_coverage_digest_must_match_evidence(tmp_path, evidence):
    path = coverage(tmp_path, evidence["errors"], errors_sha256="0" * 64)
    result = invoke(tmp_path, evidence, "--coverage", str(path))
    assert result.returncode == 2
    assert "sha256" in result.stderr


@pytest.mark.parametrize("value", [None, [], {}, {"unexpected": True}])
def test_supplied_coverage_cannot_silently_become_missing(tmp_path, evidence, value):
    path = dump(tmp_path / "invalid-coverage.json", value)
    result = invoke(tmp_path, evidence, "--coverage", str(path))
    assert result.returncode == 2
    assert json.loads(result.stderr)["execution_status"] == "error"


def test_bounded_rows_bytes_and_invalid_window(tmp_path, evidence):
    for extra in (("--max-rows", "1"), ("--max-bytes", "10"), ("--since", UNTIL), ("--now", "2026-11-10")):
        assert invoke(tmp_path, evidence, *extra).returncode == 2


def test_database_read_only_snapshot_and_optional_lessons(tmp_path, evidence):
    db = tmp_path / "handoff.db"
    with sqlite3.connect(db) as con:
        con.execute("CREATE TABLE agent_errors(id INTEGER, error_class TEXT, created_at TEXT)")
        con.executemany(
            "INSERT INTO agent_errors VALUES (?, ?, ?)", [(1, "drift", SINCE), (2, "drift", "2026-11-07T00:00:00Z")]
        )
    before = db.read_bytes()
    db.chmod(0o444)
    report = successful(
        invoke(
            tmp_path,
            {k: v for k, v in evidence.items() if k not in ("errors", "lessons")},
            "--db",
            db.as_uri() + "?mode=ro",
        )
    )
    assert db.read_bytes() == before
    assert {p.name for p in tmp_path.glob("handoff.db*")} == {"handoff.db"}
    assert report["inputs"]["errors"]["kind"] == "sqlite_read_only"
    assert report["inputs"]["errors"]["files"][0]["sha256"] == hashlib.sha256(before).hexdigest()
    assert report["inputs"]["lessons"]["status"] == "unavailable"
    assert report["scorers"]["recurrence"]["errors"]["loaded"] == 2
    assert invoke(tmp_path, None, "--db", db.as_uri() + "?mode=rw").returncode == 2
    assert invoke(tmp_path, evidence, "--db", str(db)).returncode == 2


def test_existing_artifact_inputs_sidecars_and_symlinks_never_clobbered(tmp_path, evidence):
    existing = tmp_path / "old.json"
    existing.write_text("operator history")
    linked = tmp_path / "linked.json"
    linked.symlink_to(existing)
    directory = tmp_path / "linked-dir"
    directory.symlink_to(tmp_path / "reports")
    for target in (existing, linked, evidence["findings"], directory / "new.json"):
        result = invoke(tmp_path, evidence, "--output", str(target))
        assert result.returncode == 2
    assert existing.read_text() == "operator history"
    assert json.loads(evidence["findings"].read_text())["human_label"] == "defect"
    target = tmp_path / "new.json"
    successful(invoke(tmp_path, evidence, "--output", str(target)))
    old = target.read_bytes()
    assert invoke(tmp_path, evidence, "--output", str(target)).returncode == 2
    assert target.read_bytes() == old


def load_runner():
    assert SCRIPT.is_file(), "weekly integration runner must exist"
    spec = importlib.util.spec_from_file_location("evalops_runner_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_optional_import_failure_is_loud_and_offline_path_survives(tmp_path, monkeypatch, capsys):
    runner = load_runner()
    db = tmp_path / "handoff.db"
    with sqlite3.connect(db) as con:
        con.execute("CREATE TABLE agent_errors(error_class TEXT)")
    original = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name == "sqlite3":
            raise ImportError("fixture sqlite unavailable")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    assert runner.main(["--output-dir", str(tmp_path / "offline")]) == 0
    capsys.readouterr()
    assert runner.main(["--db", str(db), "--output-dir", str(tmp_path / "db")]) == 2
    error = json.loads(capsys.readouterr().err)
    assert error["execution_status"] == "error"
    assert "sqlite3 is unavailable" in error["error"]


def test_database_schema_io_and_sidecar_output_errors(tmp_path, evidence):
    db = tmp_path / "invalid.db"
    db.write_text("not a database")
    result = invoke(tmp_path, None, "--db", str(db))
    assert result.returncode == 2
    assert "SQLite read failed" in json.loads(result.stderr)["error"]
    db.unlink()
    with sqlite3.connect(db) as con:
        con.execute("CREATE TABLE unsupported(id INTEGER)")
    assert "unsupported errors schema" in invoke(tmp_path, None, "--db", str(db)).stderr
    with sqlite3.connect(db) as con:
        con.execute("CREATE TABLE errors(error_class TEXT)")
    for suffix in ("-wal", "-shm", "-journal"):
        target = Path(str(db) + suffix)
        assert invoke(tmp_path, None, "--db", str(db), "--output", str(target)).returncode == 2
        assert not target.exists()


def test_non_regular_and_unreadable_supplied_inputs_fail(tmp_path, evidence):
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    result = invoke(tmp_path, evidence, "--predictions", str(fifo))
    assert result.returncode == 2
    assert "regular file" in json.loads(result.stderr)["error"]
    unreadable = tmp_path / "unreadable.json"
    unreadable.write_text("{}")
    unreadable.chmod(0)
    try:
        result = invoke(tmp_path, evidence, "--qc", str(unreadable))
        assert result.returncode == 2
        assert "Permission denied" in json.loads(result.stderr)["error"]
    finally:
        unreadable.chmod(0o600)


def test_scorer_import_and_output_io_failures_are_loud(tmp_path, monkeypatch, capsys):
    runner = load_runner()
    original = runner.importlib.import_module

    def blocked(name, *args, **kwargs):
        if name.endswith("score_judge"):
            raise ImportError("fixture scorer unavailable")
        return original(name, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(runner.importlib, "import_module", blocked)
        assert runner.main(["--output-dir", str(tmp_path / "import")]) == 2
        assert "fixture scorer unavailable" in capsys.readouterr().err
    blocker = tmp_path / "file-not-dir"
    blocker.write_text("keep")
    assert runner.main(["--output-dir", str(blocker / "nested")]) == 2
    assert json.loads(capsys.readouterr().err)["execution_status"] == "error"
    assert blocker.read_text() == "keep"


def test_make_end_to_end_with_explicit_evidence(tmp_path, evidence):
    args = ["--now", NOW, "--since", SINCE, "--until", UNTIL, "--output-dir", str(tmp_path / "make-reports")]
    for key, value in evidence.items():
        args += [f"--{key}", str(value)]
    result = subprocess.run(
        [
            "make",
            "--no-print-directory",
            "-s",
            "-C",
            str(ROOT),
            "evalops",
            f"EVALOPS_PYTHON={sys.executable}",
            "EVALOPS_ARGS=" + " ".join(args),
        ],
        text=True,
        capture_output=True,
        timeout=30,
    )
    report = successful(result)
    assert report["scorers"]["judge"]["status"] == "scored"
    assert report["scorers"]["retrieval"]["payload"]["counts"]["result_query_count"] == 1
    assert len(list((tmp_path / "make-reports").glob("*.json"))) == 1


def scorer_fixtures():
    """Reuse externally supplied scorer fixtures; never gold or product trials."""
    modules = []
    for name in ("reliability", "faithfulness"):
        path = ROOT / f"benchmarks/tests/test_evalops_score_{name}.py"
        spec = importlib.util.spec_from_file_location(f"runner_synthetic_{name}", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        modules.append(module)
    return modules


def test_category_defaults_do_not_fail_tooling_or_invent_scores(tmp_path):
    report = successful(invoke(tmp_path))
    for name in ("reliability", "faithfulness"):
        category = report["categories"][name]
        assert category["status"] == "unavailable"
        assert category["reason_codes"] == ["input_not_supplied"]
        assert category["quality_acceptance"] == "not_evaluated"
        assert category["product_regression"] == "unknown"
        assert category["gate"]["status"] == "not_requested"
        assert category["gate"]["disposition"] == "none"
        assert report["scorers"][name]["payload"] is None
    assert report["execution_status"] == "ok"
    assert report["statistical_acceptance"]["status"] == "not_evaluated"


def test_runner_uses_native_reliability_api_and_retains_failed_attempts(tmp_path):
    reliability, _ = scorer_fixtures()
    fixture = reliability.Synthetic([(["pass", "pass"], ["fail", "pass"])])
    path = dump(tmp_path / "matched-trials.json", fixture.request())
    report = successful(invoke(tmp_path, None, "--reliability", str(path)))
    payload = report["scorers"]["reliability"]["payload"]
    assert payload == fixture.score()
    assert payload["paired"][0]["metrics"]["2"]["pass_pow_k"]["delta"] == -1
    assert len(payload["attempts"]) == 4
    assert payload["dispatch_infrastructure"]["counts"]["executed"] == 4
    category = report["categories"]["reliability"]
    assert category["product_regression"] == "unknown"  # synthetic negative delta is no product verdict
    assert category["pins"]["input"]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert category["pins"]["scorer_payload"] == "/scorers/reliability/payload"
    assert (
        report["code"]["executed_files"]["benchmarks/tools/evalops/score_reliability.py"]["sha256"]
        == hashlib.sha256(reliability.SCORER.read_bytes()).hexdigest()
    )


def test_generation_judgments_and_pairwise_orders_are_native_diagnostics(tmp_path):
    _, faithfulness = scorer_fixtures()
    a, b = faithfulness.entry("synthetic-A"), faithfulness.entry("synthetic-B")
    supplied = faithfulness.payload(a, b, pairs=[faithfulness.pair(a, b, winners=("first", "first"))])
    path = dump(tmp_path / "generation.json", supplied)
    report = successful(invoke(tmp_path, None, "--faithfulness", str(path)))
    payload = report["scorers"]["faithfulness"]["payload"]
    assert payload == faithfulness.scorer.score(supplied)
    assert payload["pairwise"]["counts"]["inconsistent"] == 1
    assert payload["semantic_rates"]["supported"]["value"] is None
    assert report["categories"]["faithfulness"]["product_regression"] == "unknown"
    assert (
        report["code"]["executed_files"]["benchmarks/tools/evalops/score_faithfulness.py"]["sha256"]
        == hashlib.sha256(faithfulness.SCORER.read_bytes()).hexdigest()
    )


def category_protocol(*, complete=False):
    """Invented threshold request, never an accepted bar or baseline."""
    ref = {"ref": "synthetic-only:untrusted", "sha256": "0" * 64, "version": "synthetic-v1"}
    return {
        "schema_version": "evalops.category-protocol.v1",
        "categories": {
            "reliability": {
                "affected_action": {"kind": "promotion", "id": "synthetic-only:model-B"},
                "thresholds": [{"metric": "/arms/B/2/pass_pow_k/value", "operator": "gte", "value": 0.9}],
                "provenance": dict.fromkeys(
                    (
                        "independent_labels",
                        "qc",
                        "protocol",
                        "accepted_baseline",
                        "subject",
                        "environment",
                        "command",
                        "inputs",
                    ),
                    ref if complete else None,
                ),
            }
        },
    }


@pytest.mark.parametrize("complete", [False, True])
def test_threshold_request_cannot_certify_itself_or_block_generic_merge(tmp_path, complete):
    request = category_protocol(complete=complete)
    path = dump(tmp_path / "proposed-protocol.json", request)
    report = successful(invoke(tmp_path, None, "--category-protocol", str(path)))
    gate = report["categories"]["reliability"]["gate"]
    assert gate["status"] == "unavailable"
    assert gate["disposition"] == "hold_affected_promotion"
    assert gate["affected_action"] == request["categories"]["reliability"]["affected_action"]
    assert gate["validity"] == "unknown"  # a hold does not invent a valid defect
    assert gate["request"] == request["categories"]["reliability"]
    assert "external_verifier_unavailable" in gate["reason_codes"]
    assert ("accepted_quality_provenance_missing" in gate["reason_codes"]) is (not complete)
    assert report["categories"]["faithfulness"]["gate"]["status"] == "not_requested"
    assert report["categories"]["reliability"]["product_regression"] == "unknown"
    assert report["execution_status"] == "ok"
    assert report["statistical_acceptance"]["status"] == "not_evaluated"


def test_synthetic_negative_delta_and_dispatch_refusal_remain_distinct(tmp_path):
    reliability, _ = scorer_fixtures()
    fixture = reliability.Synthetic([(["pass", "pass"], ["fail", "pass"])])
    trial = fixture.trials[-1]
    fixture.bind_trial(trial, fixture.candidates[0], "unknown", status="dispatch_refused")
    path = dump(tmp_path / "dispatch-refused.json", fixture.request())
    proposed = dump(tmp_path / "proposed.json", category_protocol(complete=True))
    report = successful(invoke(tmp_path, None, "--reliability", str(path), "--category-protocol", str(proposed)))
    payload = report["scorers"]["reliability"]["payload"]
    assert payload == fixture.score()
    assert payload["dispatch_infrastructure"]["counts"]["dispatch_refused"] == 1
    assert payload["arms"]["B"]["2"]["pass_pow_k"]["value"] is None
    assert report["categories"]["reliability"]["product_regression"] == "unknown"
    assert report["categories"]["reliability"]["gate"]["status"] == "unavailable"


def test_actual_quarantined_dataset_cannot_become_trials_or_zero_rate(tmp_path):
    candidates = [
        json.loads(line) for line in (SEEDS / "dataset-v1/artifacts/candidates.jsonl").read_text().splitlines()
    ]
    assert len(candidates) == 240
    path = dump(tmp_path / "candidates-only.json", {"candidates": candidates})
    report = successful(invoke(tmp_path, None, "--reliability", str(path)))
    payload = report["scorers"]["reliability"]["payload"]
    assert payload["candidate_coverage"] == {"records": 240, "needs_labels": 240, "unavailable": 240}
    assert payload["cohort"] is None and payload["arms"] == {}
    assert payload["runtime_task_reliability"]["status"] == "unavailable"
    assert "matched_trials_unavailable" in report["categories"]["reliability"]["reason_codes"]


@pytest.mark.parametrize(
    "name,empty",
    [
        ("reliability", {"candidates": []}),
        ("faithfulness", {"schema_version": "evalops.faithfulness-input.v1", "cases": []}),
    ],
)
def test_empty_native_input_is_supplied_but_quality_stays_unavailable(tmp_path, name, empty):
    path = dump(tmp_path / "empty.json", empty)
    report = successful(invoke(tmp_path, None, f"--{name}", str(path)))
    assert report["inputs"][name]["status"] == "supplied"
    assert report["scorers"][name]["payload"] is not None
    assert report["categories"][name]["quality_acceptance"] == "not_evaluated"


def test_native_reliability_optional_nulls_remain_compatible(tmp_path):
    reliability, _ = scorer_fixtures()
    request = {"candidates": [], "trials": None, "design": None, "artifacts": None}
    path = dump(tmp_path / "native-nulls.json", request)
    report = successful(invoke(tmp_path, None, "--reliability", str(path)))
    assert report["scorers"]["reliability"]["payload"] == reliability.MODULE.score(**request)


@pytest.mark.parametrize("name", ["reliability", "faithfulness", "category-protocol"])
@pytest.mark.parametrize("bad", ['{"a":', '{"a":1,"a":2}', '{"a":NaN}', '{"a":1e999}', "null", "{}"])
def test_new_input_malformed_json_and_shapes_refuse_without_report(tmp_path, name, bad):
    path = tmp_path / "bad.json"
    path.write_text(bad)
    result = invoke(tmp_path, None, f"--{name}", str(path))
    assert result.returncode == 2
    assert json.loads(result.stderr)["execution_status"] == "error"
    assert not list((tmp_path / "reports").glob("*.json"))


@pytest.mark.parametrize("name", ["reliability", "faithfulness", "category-protocol"])
def test_new_input_missing_fifo_and_protected_output(tmp_path, name):
    path = tmp_path / "new-input.json"
    assert invoke(tmp_path, None, f"--{name}", str(path)).returncode == 2
    os.mkfifo(path)
    result = invoke(tmp_path, None, f"--{name}", str(path))
    assert result.returncode == 2 and "regular file" in result.stderr
    path.unlink()
    supplied = {
        "reliability": {"candidates": []},
        "faithfulness": {"schema_version": "evalops.faithfulness-input.v1", "cases": []},
        "category-protocol": category_protocol(),
    }[name]
    dump(path, supplied)
    before = path.read_bytes()
    result = invoke(tmp_path, None, f"--{name}", str(path), "--output", str(path))
    assert result.returncode == 2 and "overwrite input" in result.stderr
    assert path.read_bytes() == before


@pytest.mark.parametrize("name", ["reliability", "faithfulness"])
def test_native_arrays_honor_lower_runner_limits(tmp_path, name):
    reliability, faithfulness = scorer_fixtures()
    value = (
        reliability.Synthetic([(["pass", "fail"], ["fail", "pass"])]).request()
        if name == "reliability"
        else faithfulness.payload(faithfulness.entry("A"), faithfulness.entry("B"))
    )
    path = dump(tmp_path / "oversized.json", value)
    # Empty old inputs isolate the new array limit from the 100-row defaults.
    empty = dump(tmp_path / "empty.jsonl", [], lines=True)
    evidence = dict.fromkeys(("findings", "qrels", "errors", "lessons"), empty)
    result = invoke(tmp_path, evidence, f"--{name}", str(path), "--max-rows", "1")
    assert result.returncode == 2 and "bounded array" in result.stderr
    assert not list((tmp_path / "reports").glob("*.json"))


@pytest.mark.parametrize(
    "mutation", ["version", "category", "action", "boolean", "operator", "nonfinite", "pointer", "extra"]
)
def test_category_config_rejects_invalid_or_self_attested_authority(tmp_path, mutation):
    request = category_protocol()
    category = request["categories"]["reliability"]
    if mutation == "version":
        request["schema_version"] = "evalops.category-protocol.v2"
    elif mutation == "category":
        request["categories"]["judge"] = category
    elif mutation == "action":
        category["affected_action"]["kind"] = "merge"
    elif mutation == "boolean":
        category["provenance"]["independent_labels"] = True
    elif mutation == "operator":
        category["thresholds"][0]["operator"] = "execute"
    elif mutation == "nonfinite":
        category["thresholds"][0]["value"] = float("inf")
    elif mutation == "pointer":
        category["thresholds"][0]["metric"] = "/bad~pointer"
    else:
        category["gold_certified"] = True
    path = dump(tmp_path / "invalid-protocol.json", request)
    result = invoke(tmp_path, None, "--category-protocol", str(path))
    assert result.returncode == 2
    assert not list((tmp_path / "reports").glob("*.json"))


def test_root_vm_target_and_remote_forwarding_preserve_environment_defaults(tmp_path):
    reliability = dump(tmp_path / "matched-trials.json", {"candidates": []})
    faithfulness = dump(tmp_path / "generation.json", {"schema_version": "evalops.faithfulness-input.v1", "cases": []})
    protocol = dump(tmp_path / "proposed-protocol.json", category_protocol())
    result = subprocess.run(
        [
            "make",
            "--no-print-directory",
            "-s",
            "-C",
            str(ROOT),
            "evalops-vm",
            f"EVALOPS_PYTHON={sys.executable}",
            f"EVALOPS_RELIABILITY={reliability}",
            f"EVALOPS_FAITHFULNESS={faithfulness}",
            f"EVALOPS_CATEGORY_PROTOCOL={protocol}",
            "EVALOPS_ARGS=--output-dir " + str(tmp_path / "vm-reports"),
        ],
        text=True,
        capture_output=True,
        timeout=30,
    )
    report = successful(result)
    assert report["categories"]["reliability"]["gate"]["status"] == "unavailable"
    for name in ("reliability", "faithfulness", "category_protocol"):
        assert report["inputs"][name]["status"] == "supplied"
    env = dict(os.environ)
    for key in list(env):
        if key.startswith("WORKBAY_REMOTE_GATE_") or key in ("GATE_ENV", "GATE_WORKDIR", "GATE_TARGETS", "TARGETS"):
            del env[key]
    env["WORKBAY_REMOTE_GATE_WORKDIR"] = "."
    result = subprocess.run(
        ["make", "-n", "-C", str(ROOT), "check-remote", "TARGETS=evalops-vm"],
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "bash scripts/remote_gate.sh run evalops-vm" in result.stdout
    assert "OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 ACX_STRICT_GATE=1" in result.stdout
    assert 'w="${WORKBAY_REMOTE_GATE_WORKDIR:-apps/prototype-description-service}"' in result.stdout


@pytest.mark.parametrize("name", ["reliability", "faithfulness", "category-protocol"])
def test_new_inputs_honor_byte_limits_before_parsing(tmp_path, name):
    # Valid JSON preceded by whitespace: the byte reader must refuse this,
    # even though parsing would produce a small, otherwise valid request.
    supplied = {
        "reliability": {"candidates": []},
        "faithfulness": {"schema_version": "evalops.faithfulness-input.v1", "cases": []},
        "category-protocol": category_protocol(),
    }[name]
    path = tmp_path / "large.json"
    path.write_text(" " * 1024 + json.dumps(supplied))
    empty = dump(tmp_path / "empty.jsonl", [], lines=True)
    evidence = dict.fromkeys(("findings", "qrels", "errors", "lessons"), empty)
    result = invoke(tmp_path, evidence, f"--{name}", str(path), "--max-bytes", "1024")
    assert result.returncode == 2 and "byte limit 1024 exceeded" in result.stderr
    assert not list((tmp_path / "reports").glob("*.json"))


@pytest.mark.parametrize(
    "changes,expected",
    [
        ({"WORKBAY_REMOTE_GATE_ENV": "INVALID"}, "entries must be KEY=VALUE"),
        ({"WORKBAY_REMOTE_GATE_WORKDIR": "../wrong"}, "invalid REMOTE_GATE_WORKDIR"),
    ],
)
def test_evalops_vm_remote_config_refusals_are_local(tmp_path, changes, expected):
    # The existing transport validates these before SSH/push. Executable stubs
    # make accidental network dispatch observable without touching a service.
    bindir = tmp_path / "bin"
    bindir.mkdir()
    sentinel = tmp_path / "unexpected-network"
    for command in ("ssh", "git"):
        stub = bindir / command
        if command == "git":
            body = f'#!/bin/sh\nif [ "$1" = "rev-parse" ]; then printf "%s\\n" "{ROOT}/.git"; exit 0; fi\ntouch "{sentinel}"\nexit 99\n'
        else:
            body = f'#!/bin/sh\ntouch "{sentinel}"\nexit 99\n'
        stub.write_text(body)
        stub.chmod(0o700)
    env = {key: value for key, value in os.environ.items() if not key.startswith("WORKBAY_REMOTE_GATE_")}
    env.update(
        PATH=str(bindir) + os.pathsep + env["PATH"],
        WORKBAY_REMOTE_GATE_HOST="gate@synthetic.invalid",
        WORKBAY_REMOTE_GATE_WORKDIR=".",
        WORKBAY_REMOTE_GATE_DIR=f"src/{ROOT.name}",
    )
    env.update(changes)
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/remote_gate.sh"), "run", "evalops-vm"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 2 and expected in result.stderr
    assert not sentinel.exists()
