"""Executable contracts for read-only, time-aware EVALOPS recurrence reporting."""

from __future__ import annotations

import builtins
import hashlib
import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[1] / "tools/evalops/error_recurrence.py"
SEEDS = MODULE.parents[2] / "experiments/evalops"
SINCE = "2026-10-29T13:18:00Z"
UNTIL = "2026-10-29T15:18:00Z"
BOUNDARY = "2026-10-29T14:18:00Z"


@pytest.fixture
def api():
    # Import inside the fixture: missing implementation is an intentional RED,
    # while pytest still collects every behavioral contract.
    spec = importlib.util.spec_from_file_location("error_recurrence", MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def error(at=BOUNDARY, cls="drift", **extra):
    return {"created_at": at, "error_class": cls, **extra}


def report(api, errors, lessons=(), **extra):
    return api.build_report(errors, lessons, since=SINCE, until=UNTIL, now=UNTIL, **extra)


def test_window_boundaries_utc_and_chronological_recurrence(api):
    rows = [error(UNTIL), error(BOUNDARY), error(SINCE), error("2026-10-29T10:19:00-04:00"),
            error("2026-10-29T13:17:59Z"), error(None), error("bad")]
    result = report(api, rows)
    pre, post = result["windows"]["pre"], result["windows"]["post"]
    assert (pre["errors"], post["errors"]) == (1, 2)
    assert result["errors"]["outside_window"] == 2
    assert result["errors"]["unknown_timestamp"] == 2
    assert post["classes"]["drift"]["recurrences_after_prior"] == 2
    assert post["classes"]["drift"]["repeat_excess_in_window"] == 1
    assert result["comparison"]["drift"]["seen_pre_and_post"] is True
    assert result["window"]["boundary"] == BOUNDARY
    assert result["window"]["bounds"] == "[since, until)"


def test_class_denominators_multilabel_unknowns_and_explicit_precedence(api):
    rows = [error(cls=["drift", "transport", "drift"]),
            error(cls="LANE_STATE_PROVENANCE_DRIFT", open_codes=["unknown-code"]),
            error(cls="future_class", open_codes=["phpunit-executable-missing"]),
            error(cls=None, open_codes=["phpunit-executable-missing", "never-mapped"]),
            error(cls=None), error(cls=34)]
    result = report(api, rows)
    post = result["windows"]["post"]
    assert post["rate_denominator"] == 6  # includes unclassified records
    assert post["classes"]["drift"]["count"] == 2
    assert post["classes"]["drift"]["rate"] == pytest.approx(2 / 6)
    assert post["classes"]["transport"]["count"] == 1
    assert post["classes"]["fixture_env"]["count"] == 1
    assert post["classes"]["future_class"]["count"] == 1
    assert post["unknown_classification"] == 2
    assert result["classification"]["unmapped_open_codes"] == {"never-mapped": 1}
    assert result["classification"]["nonbaseline_explicit_classes"] == {"future_class": 1}
    assert result["classification"]["invalid_classification_rows"] == 1
    assert "once per class" in result["policy"]["multi_label"]


def test_rounded_baseline_is_separate_and_zero_denominator_is_null(api):
    result = report(api, [])
    assert result["baseline"] == {
        "n": 441, "rounded": True,
        "proportions": {"drift": .281, "transport": .204, "pytest": .177, "review_loop": .150,
                        "brief": .098, "fixture_env": .068, "tool_shape": .023},
        "counts": None,
    }
    assert result["windows"]["post"]["classes"]["drift"]["rate"] is None
    assert result["comparison"]["drift"]["post_minus_baseline"] is None
    assert result["maturity"]["seven_day_replay_ready"] is False
    assert result["causal_claim"] is False
    for cls in result["baseline"]["proportions"]:
        followup = result["follow_up"][cls]
        assert followup["owner"] and followup["guard"] and followup["check"]


def test_missing_fields_and_equal_time_are_not_invented_recurrences(api):
    result = report(api, [{}, error(), error()])
    assert result["errors"]["unknown_timestamp"] == 1
    assert result["errors"]["unknown_classification"] == 1
    assert result["windows"]["post"]["classes"]["drift"]["recurrences_after_prior"] == 0
    assert result["windows"]["post"]["classes"]["drift"]["repeat_excess_in_window"] == 1


def test_lessons_memory_markers_pre_post_unknown_and_no_substring_false_positive(api):
    lessons = [
        {"decision_id": 1, "created_at": SINCE, "decision": "[recur] error_class=drift", "rationale": ""},
        {"doc_id": "dec-2", "created_at": BOUNDARY, "decision": "recurred: transport", "rationale": ""},
        {"created_at": BOUNDARY, "decision": "lesson", "rationale": "memory: [recurred]"},
        {"created_at": None, "decision": "recur", "error_class": "brief"},
        {"created_at": UNTIL, "decision": "recur: brief"},
        {"created_at": SINCE, "decision": "recursion and precursor are unrelated"},
    ]
    result = report(api, [error()], lessons)
    assert result["lessons"]["marker_rows"] == 5
    assert result["lessons"]["unknown_timestamp"] == 1
    assert result["lessons"]["unknown_classification"] == 1
    assert result["windows"]["pre"]["lesson_markers"] == 1
    assert result["windows"]["post"]["lesson_markers"] == 2
    assert result["windows"]["pre"]["classes"]["drift"]["lesson_markers"] == 1
    assert result["windows"]["post"]["classes"]["transport"]["lesson_markers"] == 1


def test_maturity_requires_elapsed_and_observed_span(api):
    end = "2026-11-05T14:18:01Z"
    rows = [error(), error("2026-11-05T14:18:00Z")]
    kwargs = {"since": BOUNDARY, "until": end, "now": end}
    result = api.build_report(rows, **kwargs)
    assert result["maturity"]["seven_day_replay_ready"] is True
    assert api.build_report(rows[:1], **kwargs)["maturity"]["seven_day_replay_ready"] is False
    assert api.build_report(rows, since=BOUNDARY, until=end, now=UNTIL)["maturity"]["seven_day_replay_ready"] is False


@pytest.mark.parametrize("since,until", [(UNTIL, SINCE), (SINCE, SINCE), ("bad", UNTIL),
                                         ("2026-10-29T13:00:00", UNTIL)])
def test_invalid_windows_fail_loudly(api, since, until):
    with pytest.raises(ValueError):
        api.build_report([], since=since, until=until)


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


def test_real_export_shapes_and_sample_identity(api):
    errors = api.load_jsonl(SEEDS / "errors-v0.jsonl")
    lessons = api.load_jsonl(SEEDS / "lessons-v0.jsonl")
    result = api.build_report(errors, lessons, since="2026-07-01T00:00:00Z", until=UNTIL, now=UNTIL)
    assert result["errors"]["loaded"] == 100
    assert result["lessons"]["loaded"] == 188
    assert result["baseline"]["n"] == 441
    assert result["errors"]["unknown_timestamp"] == 13
    assert result["windows"]["post"]["errors"] == 0
    assert result["classification"]["unmapped_open_codes"]
    assert result["maturity"]["seven_day_replay_ready"] is False


@pytest.mark.parametrize("body", ['{"oops":', '[]\n', 'null\n', '{"x": 1}\n42\n'])
def test_jsonl_invalid_rows_report_location(api, tmp_path, body):
    path = tmp_path / "bad.jsonl"
    path.write_text(body)
    with pytest.raises(ValueError, match=r"bad.jsonl:\d+"):
        api.load_jsonl(path)


def test_jsonl_io_limit_and_unicode_failures(api, tmp_path):
    with pytest.raises(OSError):
        api.load_jsonl(tmp_path / "absent")
    path = write_jsonl(tmp_path / "many.jsonl", [{}, {}])
    with pytest.raises(ValueError, match="limit"):
        api.load_jsonl(path, max_rows=1)
    path.write_bytes(b'\xff')
    with pytest.raises(UnicodeError):
        api.load_jsonl(path)


@pytest.fixture
def db(tmp_path):
    # Synthetic typical agent_errors columns; no handoff package or live DB.
    path = tmp_path / "handoff.db"
    with sqlite3.connect(path) as con:
        con.execute("CREATE TABLE agent_errors (id INTEGER PRIMARY KEY, task_ref TEXT, error_class TEXT, created_at TEXT, error_message TEXT, huge_unused BLOB)")
        con.executemany("INSERT INTO agent_errors VALUES (?, ?, ?, ?, ?, ?)",
                        [(1, "EVALOPS-1", "drift", SINCE, "detail", b"x" * 1000),
                         (2, "EVALOPS-1", "drift", BOUNDARY, "detail", b"x" * 1000)])
    return path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_database_readonly_adaptive_projection_closes_on_success_and_limit(api, db, monkeypatch):
    before = digest(db)
    connect = sqlite3.connect
    traces, connections = [], []

    def observed(database, **kwargs):
        assert "mode=ro" in database and kwargs["uri"] is True
        con = connect(database, **kwargs)
        con.set_trace_callback(traces.append)
        connections.append(con)
        return con

    monkeypatch.setattr(sqlite3, "connect", observed)
    rows = api.load_database(db.as_uri() + "?mode=ro")
    assert report(api, rows)["windows"]["post"]["errors"] == 1
    with pytest.raises(ValueError, match="limit"):
        api.load_database(db, max_rows=1)
    assert digest(db) == before
    assert not any("huge_unused" in q or "error_message" in q for q in traces if q.startswith("SELECT"))
    assert any("LIMIT" in q for q in traces if q.startswith("SELECT") and '"agent_errors"' in q)
    for con in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            con.execute("SELECT 1")


def test_database_open_codes_schema_unknown_times_and_failure_unchanged(api, tmp_path):
    path = tmp_path / "other.db"
    with sqlite3.connect(path) as con:
        con.execute("CREATE TABLE errors (id TEXT, open_codes TEXT)")
        con.execute("INSERT INTO errors VALUES ('e1', ?)", (json.dumps(["phpunit-executable-missing"]),))
    before = digest(path)
    rows = api.load_database(path)
    assert report(api, rows)["errors"]["unknown_timestamp"] == 1
    assert report(api, rows)["errors"]["unknown_classification"] == 0
    assert digest(path) == before
    with sqlite3.connect(path) as con:
        con.execute("DROP TABLE errors")
        con.execute("CREATE TABLE agent_errors (id INTEGER, error_message TEXT)")
    before = digest(path)
    with pytest.raises(ValueError, match="schema"):
        api.load_database(path)
    assert digest(path) == before
    with pytest.raises(ValueError, match="read.only"):
        api.load_database(path.as_uri() + "?mode=rw")
    missing = tmp_path / "absent.db"
    with pytest.raises(sqlite3.Error):
        api.load_database(missing)
    assert not missing.exists()


def test_offline_path_works_without_optional_sqlite_and_db_fails_loudly(api, tmp_path, monkeypatch):
    original = builtins.__import__

    def no_sqlite(name, *args, **kwargs):
        if name == "sqlite3":
            raise ImportError("sqlite unavailable")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_sqlite)
    path = write_jsonl(tmp_path / "errors.jsonl", [error()])
    assert report(api, api.load_jsonl(path))["errors"]["loaded"] == 1
    with pytest.raises(RuntimeError, match="sqlite3.*unavailable"):
        api.load_database(tmp_path / "db")


def cli(*args):
    return subprocess.run([sys.executable, str(MODULE), *map(str, args)], capture_output=True, text=True, timeout=10)


def test_cli_offline_output_and_no_input_overwrite(db, tmp_path):
    errors = write_jsonl(tmp_path / "errors.jsonl", [error()])
    lessons = write_jsonl(tmp_path / "lessons.jsonl", [{"created_at": BOUNDARY, "decision": "recur: drift"}])
    output = tmp_path / "report.json"
    args = ["--errors", errors, "--lessons", lessons, "--since", SINCE, "--until", UNTIL]
    result = cli(*args, "--output", output)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "" and result.stderr == ""
    assert json.loads(output.read_text())["windows"]["post"]["lesson_markers"] == 1
    assert cli(*args).returncode == 0
    for source in (errors, lessons):
        before = digest(source)
        result = cli(*args, "--output", source)
        assert result.returncode == 2 and "input" in result.stderr
        assert digest(source) == before
    before = digest(db)
    result = cli("--db", db, "--since", SINCE, "--until", UNTIL, "--output", db)
    assert result.returncode == 2 and digest(db) == before


def test_cli_db_and_failures_are_machine_visible(db, tmp_path):
    result = cli("--db", db, "--since", SINCE, "--until", UNTIL)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["errors"]["loaded"] == 2
    for args in (["--errors", tmp_path / "missing"], ["--db", db, "--errors", "other"],
                 ["--db", db, "--since", SINCE],
                 ["--db", db, "--since", SINCE, "--until", UNTIL, "--output", tmp_path / "absent/out"]):
        result = cli(*args)
        assert result.returncode == 2
        assert result.stderr and not result.stdout
