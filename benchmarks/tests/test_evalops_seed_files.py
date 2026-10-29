"""Regression checks for the committed evalops v0 labelling/retrieval seed."""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path


SEED_DIR = Path(__file__).resolve().parents[1] / "experiments" / "evalops"
JUDGE = "gpt-6.1-terra/high"
LABELS = ("defect", "not_defect", "unclear")
FINDING_KEYS = set("""
    id finding_db_id finding_id task_ref lane_id severity review_mode file_path
    line_start line_end description failure_scenario fix impact created_at stratum
    stratum_population stratum_sample weight human_label human_note
""".split())
PRELABEL_KEYS = {
    "id", "pre_label", "pre_label_evidence", "pre_label_rationale", "judge",
}
ERROR_KEYS = set("""
    id sample_index source_type task_ref record_id created_at snippet text
    text_source open_codes in_vivo coded_by
""".split())
LESSON_KEYS = {
    "doc_id", "decision_id", "decision", "task_ref", "created_at", "rationale",
}
QREL_KEYS = {
    "query_id", "query", "doc_id", "relevance", "source", "later_doc_id", "evidence",
}


def _load_rows(filename):
    rows = []
    for number, line in enumerate(
        (SEED_DIR / filename).read_text(encoding="utf-8").splitlines(), 1
    ):
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise AssertionError(f"{filename}:{number}: invalid JSON: {exc}") from exc
    return rows


def _schema_rows(rows, keys, violations):
    for number, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            violations.append(f"row {number}: expected an object")
            continue
        if set(row) != keys:
            violations.append(
                f"row {number}: missing keys {sorted(keys - set(row))}; "
                f"unexpected keys {sorted(set(row) - keys)}"
            )
            continue
        yield number, row


def _require(violations, number, condition, rule):
    if not condition:
        violations.append(f"row {number}: {rule}")


def _nonempty_text(value):
    return isinstance(value, str) and bool(value.strip())


def _unique_id(value, seen, violations, number):
    if not isinstance(value, str):
        violations.append(f"row {number}: id must be a string")
        return
    _require(violations, number, value not in seen, f"duplicate id {value!r}")
    seen.add(value)


def check_findings(rows):
    violations = []
    seen = set()
    strata = Counter(
        row["stratum"] for row in rows
        if isinstance(row, dict) and isinstance(row.get("stratum"), str)
    )
    for number, row in _schema_rows(rows, FINDING_KEYS, violations):
        check = lambda condition, rule: _require(violations, number, condition, rule)
        finding_db_id = row["finding_db_id"]
        check(type(finding_db_id) is int, "finding_db_id must be an int")
        check(row["id"] == f"fnd-{finding_db_id}", "id must match finding_db_id")
        _unique_id(row["id"], seen, violations, number)
        check(row["severity"] in ("high", "medium", "low"), "invalid severity")
        check(row["review_mode"] is None or isinstance(row["review_mode"], str),
              "review_mode must be null or a string")
        check(_nonempty_text(row["description"]), "description must be non-empty text")
        check(row["stratum"] == f"{row['severity']}|{row['review_mode'] or 'none'}",
              "stratum must match severity and review_mode")
        population, sample = row["stratum_population"], row["stratum_sample"]
        valid_counts = (
            type(population) is int and type(sample) is int
            and population >= sample >= 1
        )
        check(valid_counts, "stratum_population >= stratum_sample >= 1 must hold for ints")
        if isinstance(row["stratum"], str):
            check(strata[row["stratum"]] == sample, "stratum count must equal stratum_sample")
        if valid_counts:
            check(type(row["weight"]) in (int, float)
                  and row["weight"] == round(population / sample, 4),
                  "weight must equal round(stratum_population / stratum_sample, 4)")
        check(row["human_label"] is None or row["human_label"] in LABELS,
              "invalid human_label")
        check(row["human_note"] is None or isinstance(row["human_note"], str),
              "human_note must be null or a string")
    # Exact schema checking also excludes every pre_label* key and judge, keeping
    # the operator's findings file blind to the separate model prelabels.
    return violations


def check_prelabels(rows, findings):
    violations = []
    actual_ids = [row.get("id") if isinstance(row, dict) else None for row in rows]
    finding_ids = [row.get("id") if isinstance(row, dict) else None for row in findings]
    if actual_ids != finding_ids:
        violations.append("prelabel id sequence must equal findings id sequence")
    for number, row in _schema_rows(rows, PRELABEL_KEYS, violations):
        _require(violations, number, row["pre_label"] in LABELS, "invalid pre_label")
        for field in ("pre_label_evidence", "pre_label_rationale"):
            _require(violations, number, _nonempty_text(row[field]),
                     f"{field} must be non-empty text")
        _require(violations, number, row["judge"] == JUDGE, f"judge must be {JUDGE}")
    return violations


def check_errors(rows):
    violations = []
    seen = set()
    for number, row in _schema_rows(rows, ERROR_KEYS, violations):
        check = lambda condition, rule: _require(violations, number, condition, rule)
        index = row["sample_index"]
        valid_index = type(index) is int and 0 <= index < 441
        check(valid_index, "sample_index must be an int in [0, 441)")
        if valid_index:
            check(row["id"] == f"err-{index:03d}", "id must match sample_index")
        _unique_id(row["id"], seen, violations, number)
        check(row["source_type"] in ("blocker", "lesson"), "invalid source_type")
        check(row["text_source"] in ("full", "snippet"), "invalid text_source")
        check(_nonempty_text(row["text"]) and len(row["text"]) <= 1500,
              "text must be non-empty text of at most 1500 characters")
        check(row["record_id"] is None or type(row["record_id"]) is int,
              "record_id must be null or an int")
        codes = row["open_codes"]
        check(isinstance(codes, list) and 1 <= len(codes) <= 4
              and all(isinstance(code, str)
                      and re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+){1,5}", code)
                      for code in codes),
              "open_codes must contain 1 to 4 kebab-case strings of 2 to 6 parts")
        check(_nonempty_text(row["in_vivo"]), "in_vivo must be non-empty text")
        check(row["coded_by"] == JUDGE, f"coded_by must be {JUDGE}")
    return violations


def check_lessons(rows):
    violations = []
    seen = set()
    for number, row in _schema_rows(rows, LESSON_KEYS, violations):
        check = lambda condition, rule: _require(violations, number, condition, rule)
        decision_id = row["decision_id"]
        check(type(decision_id) is int, "decision_id must be an int")
        check(row["doc_id"] == f"dec-{decision_id}", "doc_id must match decision_id")
        _unique_id(row["doc_id"], seen, violations, number)
        for field in ("decision", "rationale"):
            check(_nonempty_text(row[field]), f"{field} must be non-empty text")
        timestamp = row["created_at"]
        valid_timestamp = isinstance(timestamp, str) and bool(re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}", timestamp
        ))
        if valid_timestamp:
            try:
                datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                valid_timestamp = False
        check(valid_timestamp, "created_at must be a YYYY-MM-DD HH:MM:SS timestamp")
    return violations


def check_qrels(rows, lessons):
    violations = []
    queries = {}
    pairs = set()
    seed_docs = []
    for number, row in _schema_rows(rows, QREL_KEYS, violations):
        check = lambda condition, rule: _require(violations, number, condition, rule)
        query_id, doc_id = row["query_id"], row["doc_id"]
        valid_query_id = isinstance(query_id, str) and bool(re.fullmatch(r"q-\d{3}", query_id))
        check(valid_query_id, "query_id must match q-NNN")
        if valid_query_id:
            if query_id in queries:
                check(queries[query_id] == row["query"], "query_id must have one query text")
            queries[query_id] = row["query"]
        known_doc = isinstance(doc_id, str) and doc_id in lessons
        check(known_doc, f"doc_id {doc_id!r} must exist in lessons")
        if valid_query_id and isinstance(doc_id, str):
            pair = (query_id, doc_id)
            check(pair not in pairs, f"duplicate (query_id, doc_id) pair {pair!r}")
            pairs.add(pair)
        check(type(row["relevance"]) is int and row["relevance"] in (1, 2),
              "relevance must be 1 or 2")
        if query_id == "q-000":
            seed_docs.append(doc_id)
            check(row["source"] == "seed", "q-000 source must be seed")
            check(row["later_doc_id"] is None, "q-000 later_doc_id must be null")
            check(row["relevance"] == 2, "q-000 relevance must be 2")
        else:
            check(row["source"] == f"mined:{JUDGE}", "non-seed source must identify the miner")
            later_doc_id = row["later_doc_id"]
            known_later = isinstance(later_doc_id, str) and later_doc_id in lessons
            check(known_later, f"later_doc_id {later_doc_id!r} must exist in lessons")
            if known_doc and known_later:
                check(lessons[doc_id]["created_at"] < lessons[later_doc_id]["created_at"],
                      "doc created_at must be earlier than later_doc created_at")
    if len(seed_docs) != 2 or any(
        seed_docs.count(doc_id) != 1 for doc_id in ("dec-19034", "dec-20507")
    ):
        violations.append("q-000 must contain exactly dec-19034 and dec-20507")
    return violations


def test_findings_seed():
    rows = _load_rows("findings-v0.jsonl")
    assert len(rows) == 100
    assert check_findings(rows) == []


def test_prelabels_seed():
    rows = _load_rows("findings-v0-prelabels.jsonl")
    assert len(rows) == 100
    assert check_prelabels(rows, _load_rows("findings-v0.jsonl")) == []


def test_errors_seed():
    rows = _load_rows("errors-v0.jsonl")
    assert len(rows) == 100
    assert check_errors(rows) == []


def test_lessons_seed():
    rows = _load_rows("lessons-v0.jsonl")
    assert len(rows) == 188
    assert check_lessons(rows) == []


def test_qrels_seed():
    rows = _load_rows("qrels-v0.jsonl")
    lessons = {row["doc_id"]: row for row in _load_rows("lessons-v0.jsonl")}
    assert len(rows) == 41
    assert check_qrels(rows, lessons) == []
    assert len({row["query_id"] for row in rows}) == 27


def test_checkers_reject_prelabel_leak_and_unknown_document():
    findings = _load_rows("findings-v0.jsonl")
    leaked = dict(findings[0], pre_label="defect")
    violations = check_findings([leaked, *findings[1:]])
    assert any("unexpected keys ['pre_label']" in violation for violation in violations)

    qrels = _load_rows("qrels-v0.jsonl")
    lessons = {row["doc_id"]: row for row in _load_rows("lessons-v0.jsonl")}
    index = next(i for i, row in enumerate(qrels) if row["source"] == f"mined:{JUDGE}")
    invalid = dict(qrels[index], doc_id="dec-0")
    violations = check_qrels([*qrels[:index], invalid, *qrels[index + 1:]], lessons)
    assert any("doc_id 'dec-0' must exist in lessons" in violation for violation in violations)
