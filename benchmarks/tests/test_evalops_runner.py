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
