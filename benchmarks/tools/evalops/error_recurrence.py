"""Read-only EVALOPS error/lesson recurrence, using stdlib only.

Python API::

    errors = load_jsonl("benchmarks/experiments/evalops/errors-v0.jsonl")
    lessons = load_jsonl("benchmarks/experiments/evalops/lessons-v0.jsonl")
    report = build_report(errors, lessons, since="2026-10-29T14:18:00Z",
                          until="2026-10-30T14:18:00Z")
    # Or: errors = load_database("file:/absolute/handoff.db?mode=ro")

CLI::

    python3 benchmarks/tools/evalops/error_recurrence.py \
        --errors benchmarks/experiments/evalops/errors-v0.jsonl \
        --lessons benchmarks/experiments/evalops/lessons-v0.jsonl \
        --since 2026-10-29T14:18:00Z --until 2026-10-30T14:18:00Z \
        --output .task-state/evalops-1-errors/report.json

Replace --errors with --db PATH_OR_READONLY_URI for SQLite. No handoff package,
MCP, git probes, network calls, sleeps, classification models, or DB writes.
load_database projects classification/time/identity fields from agent_errors
(or errors), fetches at most max_rows+1, fails on overflow/unsupported schema,
and closes the connection on every path before returning. Lessons/memory are
optional JSONL, never an implicit scan of large decisions tables.

Canon v0.26.2: [MEAS-23] Make toil visible before automating it (Mastering Site
Reliability Engineering in Enterprise, ch. 6): disclose sources, denominators,
and unknowns. [DIAG-10] Close the learning loop (High Performance SRE, ch. 9):
provide owner/guard/check follow-ups, without claiming they are implemented.
[AGT-10] Degrade loudly (The Art of UNIX Programming, ch. 1): bad I/O/schema
fails visibly; optional sqlite3 import failure leaves the JSONL path usable.
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sys
from urllib.parse import parse_qs, unquote, urlsplit

BOUNDARY = "2026-10-29T14:18:00Z"
MERGE = "569d14b017"
MAX_ROWS = 100_000
BASELINE_PROPORTIONS = {
    "drift": .281, "transport": .204, "pytest": .177, "review_loop": .150,
    "brief": .098, "fixture_env": .068, "tool_shape": .023,
}
ALIASES = {
    "lane_state_provenance_drift": "drift", "remote_transport_infra": "transport",
    "other_(pytest)": "pytest", "other_pytest": "pytest", "review_gate_loop": "review_loop",
    "brief_scope_spec": "brief", "test_fixture_env": "fixture_env", "tool_api_shape": "tool_shape",
}
# Conservative exact lookup v1, not an axial recoding of the 441-row audit.
# In particular, generic "tests-failed" codes do not prove a pytest failure.
OPEN_CODE_MAP = {
    "sleeping-fallback-holds-sqlite-lock": "tool_shape",
    "host-memory-admission-refused": "transport",
    "host-disk-below-admission-floor": "transport",
    "provider-credit-below-dispatch-threshold": "transport",
    "requested-model-excluded-by-allowlist": "transport",
    "requested-model-rejected-by-adapter": "transport",
    "permission-classifier-denies-remote-launch": "transport",
    "phpunit-executable-missing": "fixture_env",
    "zip-executable-missing": "fixture_env",
    "terraform-executable-missing": "fixture_env",
    "vite-config-module-cannot-be-resolved": "fixture_env",
    "javascript-module-cannot-be-resolved": "fixture_env",
    "admin-bundle-missing-from-worktree": "fixture_env",
    "verification-tests-encounter-missing-file": "fixture_env",
    "automatic-review-reuses-finding-identifiers": "review_loop",
    "terminal-finding-collision-aborts-review": "review_loop",
    "model-capacity-prevents-review-artifact": "review_loop",
    "review-claim-not-yet-adjudicated": "review_loop",
    "cpu-pressure-threshold-stalls-queued-review": "review_loop",
    "handoff-summary-below-substance-floor": "brief",
    "guidance-handoff-lacks-attempt-evidence": "brief",
    "task-finished-before-plan-acceptance": "drift",
    "premature-task-finish-deactivates-open-task": "drift",
    "archived-row-lacks-branch-worktree": "drift",
    "legacy-receipts-select-foreign-subject": "drift",
}
FOLLOW_UP = {
    "drift": {"owner": "ACX coordinator / WorkBay", "guard": "Resolve one explicit task and worktree before dispatch.",
              "check": "Replay task resolution; compare weekly drift counts and ambiguous guard share."},
    "transport": {"owner": "ACX coordinator / WorkBay", "guard": "Check fresh-worktree transport readiness before dispatch.",
                  "check": "Replay bootstrap/preflight; count transport_missing and refusals per week."},
    "pytest": {"owner": "ACX implementation lane", "guard": "Pin the service environment and scoped TEST_CMD.",
               "check": "Replay the original failing TEST_CMD; count pytest errors per week."},
    "review_loop": {"owner": "WorkBay / review coordinator", "guard": "Bound review rounds and require a review-pipeline MERGE artifact.",
                    "check": "Measure rounds-to-pass and review-pass to MERGE latency."},
    "brief": {"owner": "ACX dispatch coordinator", "guard": "Validate TEST_CMD, commit authorization and scoped owned paths.",
              "check": "Run manifest checks before dispatch; count brief violations per week."},
    "fixture_env": {"owner": "ACX implementation lane", "guard": "Verify required fixtures, dependencies and environment in the lane.",
                    "check": "Replay original fixture/env failure in a fresh worktree; count weekly failures."},
    "tool_shape": {"owner": "WorkBay / API consumer", "guard": "Verify producer schema and reject unsupported shapes.",
                   "check": "Replay read-only shape contracts and count malformed inputs per week."},
}
MARKER = re.compile(r"(?<![a-z])recur(?:red|s|rence)?(?![a-z])", re.I)
INLINE_CLASS = re.compile(r"\berror_class\s*[:=]\s*([a-z][a-z0-9_-]*)", re.I)
MARKER_CLASS = re.compile(r"\brecur(?:red|s)?\s*:\s*([a-z][a-z0-9_-]*)", re.I)


def _limit(max_rows: int) -> None:
    if type(max_rows) is not int or max_rows < 1:
        raise ValueError("row limit must be a positive integer")


def load_jsonl(path: str | Path, *, max_rows: int = MAX_ROWS) -> list[dict]:
    """Load bounded object rows; report path and line on invalid JSON/shape."""
    _limit(max_rows)
    rows = []
    with Path(path).open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError as exc:
                raise ValueError(f"{path}:{number}: invalid JSON: {exc}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{number}: expected an object")
            if len(rows) >= max_rows:
                raise ValueError(f"{path}:{number}: row limit {max_rows} exceeded; no partial report")
            rows.append(row)
    return rows


def _db_path(source: str | Path) -> Path:
    raw = str(source)
    if not raw.startswith("file:"):
        return Path(raw).resolve()
    uri = urlsplit(raw)
    query = parse_qs(uri.query, keep_blank_values=True)
    if (uri.netloc not in ("", "localhost") or uri.fragment
            or set(query) - {"mode"} or query.get("mode", ["ro"]) != ["ro"]):
        raise ValueError("SQLite URI must be read-only (mode=ro); other URI options are unsupported")
    return Path(unquote(uri.path)).resolve()


def load_database(source: str | Path, *, max_rows: int = MAX_ROWS) -> list[dict]:
    """Adaptively read only agent_errors/errors. Never create a missing DB."""
    _limit(max_rows)
    path = _db_path(source)
    try:
        import sqlite3
    except ImportError as exc:
        raise RuntimeError("sqlite3 is unavailable; use --errors JSONL instead") from exc
    con = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=1.0)
    try:
        con.execute("PRAGMA query_only=ON")
        table = None
        selected = []
        for candidate in ("agent_errors", "errors"):
            columns = {row[1] for row in con.execute(f'PRAGMA table_info("{candidate}")')}
            if columns & {"error_class", "open_codes"}:
                table = candidate
                selected = [key for key in ("id", "task_ref", "error_class", "open_codes", "created_at") if key in columns]
                break
        if table is None:
            raise ValueError("unsupported errors schema: need agent_errors/errors with error_class or open_codes")
        projection = ", ".join(f'"{key}"' for key in selected)
        cursor = con.execute(f'SELECT {projection} FROM "{table}" LIMIT ?', (max_rows + 1,))
        rows = cursor.fetchmany(max_rows + 1)
        if len(rows) > max_rows:
            raise ValueError(f"database row limit {max_rows} exceeded; no partial report")
        result = [dict(zip(selected, row)) for row in rows]
        for row in result:
            for key in ("open_codes", "error_class"):
                value = row.get(key)
                # SQLite may store multi-label arrays as JSON text.
                if isinstance(value, str) and value.lstrip().startswith("["):
                    try:
                        row[key] = json.loads(value)
                    except ValueError as exc:
                        raise ValueError(f"invalid {key} JSON in errors schema") from exc
        return result
    finally:
        con.close()


def _time(value: object, *, require_zone: bool = False) -> datetime | None:
    if not isinstance(value, (str, datetime)):
        return None
    try:
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    except ValueError:
        return None
    if parsed.tzinfo is None:
        if require_zone:
            return None
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _normalize(value: str) -> str:
    key = re.sub(r"[\s-]+", "_", value.strip().lower())
    return ALIASES.get(key, key)


def _classify(row: Mapping) -> tuple[set[str], str, bool, list[str]]:
    explicit = row.get("error_class")
    if explicit is not None and explicit != "" and explicit != []:
        values = [explicit] if isinstance(explicit, str) else explicit
        if not isinstance(values, list) or any(not isinstance(x, str) or not x.strip() for x in values):
            return set(), "explicit", True, []
        return {_normalize(x) for x in values}, "explicit", False, []
    codes = row.get("open_codes", [])
    if codes is None:
        codes = []
    if not isinstance(codes, list) or any(not isinstance(x, str) for x in codes):
        return set(), "open_codes", True, []
    codes = set(codes)
    return {OPEN_CODE_MAP[c] for c in codes if c in OPEN_CODE_MAP}, "open_codes", False, sorted(codes - OPEN_CODE_MAP.keys())


def _prepare(rows: Iterable[Mapping], *, lessons: bool = False) -> list[dict]:
    result = []
    for number, row in enumerate(rows, 1):
        if not isinstance(row, Mapping):
            raise ValueError(f"row {number}: expected an object")
        classes, source, invalid, unmapped = _classify(row)
        text = " ".join(row[key] for key in ("decision", "rationale", "memory", "text", "content") if isinstance(row.get(key), str))
        marker = bool(MARKER.search(text)) or any(
            row.get(key) is True or (isinstance(row.get(key), str) and bool(row[key].strip()))
            for key in ("recur", "recurred")
        )
        if lessons and not classes and source != "explicit" and not invalid:
            classes = {_normalize(m.group(1)) for pattern in (INLINE_CLASS, MARKER_CLASS) for m in pattern.finditer(text)}
        timestamp = _time(row.get("created_at"))
        raw = row.get("created_at")
        naive = isinstance(raw, str) and timestamp is not None and datetime.fromisoformat(raw).tzinfo is None
        result.append({"time": timestamp, "classes": classes, "source": source, "invalid": invalid,
                       "unmapped": unmapped, "marker": marker, "naive_utc": naive})
    return result


def build_report(errors: Iterable[Mapping], lessons: Iterable[Mapping] = (), *,
                 since: str | datetime, until: str | datetime,
                 now: str | datetime | None = None) -> dict:
    """Return JSON-safe report. Bounds require zones; naive export dates mean UTC.

    Each row counts once per class, even if multiple codes map to that class.
    Rates divide by ALL timed error rows in that window (including unknowns),
    never by label assignments, lesson rows, dispatches or the historical 441.
    Unknown timestamps are counted separately and cannot be assigned a window.
    A recurrence needs a strictly earlier same-class error in the loaded source,
    including history outside the requested window. Tied timestamps alone do
    not prove order. Lesson markers are declared recurrence, not inferred links.
    """
    start, end = _time(since, require_zone=True), _time(until, require_zone=True)
    current = datetime.now(timezone.utc) if now is None else _time(now, require_zone=True)
    if start is None or end is None or current is None or start >= end:
        raise ValueError("since/until/now need timezone-aware ISO dates and since < until")
    boundary = _time(BOUNDARY)
    error_rows, lesson_rows = _prepare(errors), _prepare(lessons, lessons=True)
    marked = [row for row in lesson_rows if row["marker"]]
    classes = sorted(set(BASELINE_PROPORTIONS).union(*(r["classes"] for r in error_rows + marked)))
    first = {}
    for row in error_rows:
        if row["time"] is not None:
            for cls in row["classes"]:
                first[cls] = min(first.get(cls, row["time"]), row["time"])
    windows = {}
    for name in ("pre", "post"):
        def belongs(row):
            return row["time"] is not None and start <= row["time"] < end and ((row["time"] < boundary) == (name == "pre"))
        selected = [r for r in error_rows if belongs(r)]
        selected_lessons = [r for r in marked if belongs(r)]
        counts = Counter(cls for row in selected for cls in row["classes"])
        markers = Counter(cls for row in selected_lessons for cls in row["classes"])
        windows[name] = {
            "errors": len(selected), "rate_denominator": len(selected),
            "unknown_classification": sum(not r["classes"] for r in selected),
            "lesson_markers": len(selected_lessons),
            "lesson_unknown_classification": sum(not r["classes"] for r in selected_lessons),
            "classes": {cls: {
                "count": counts[cls], "rate": counts[cls] / len(selected) if selected else None,
                "repeat_excess_in_window": max(0, counts[cls] - 1),
                "recurrences_after_prior": sum(cls in r["classes"] and first[cls] < r["time"] for r in selected),
                "lesson_markers": markers[cls],
            } for cls in classes},
        }
    observed_post = [r["time"] for r in error_rows if r["time"] is not None and max(start, boundary) <= r["time"] < min(end, current)]
    span = (max(observed_post) - min(observed_post)).total_seconds() if observed_post else 0
    elapsed = max(0, (min(end, current) - max(start, boundary)).total_seconds())
    week = timedelta(days=7).total_seconds()
    def totals(rows):
        return {"loaded": len(rows), "unknown_timestamp": sum(r["time"] is None for r in rows),
                "unknown_classification": sum(not r["classes"] for r in rows),
                "naive_timestamps_assumed_utc": sum(r["naive_utc"] for r in rows),
                "outside_window": sum(r["time"] is not None and not start <= r["time"] < end for r in rows)}
    comparison = {}
    for cls in classes:
        pre, post = (windows[w]["classes"][cls] for w in ("pre", "post"))
        comparison[cls] = {
            "seen_pre_and_post": pre["count"] > 0 and post["count"] > 0,
            "post_minus_pre": post["rate"] - pre["rate"] if pre["rate"] is not None and post["rate"] is not None else None,
            "post_minus_baseline": post["rate"] - BASELINE_PROPORTIONS[cls] if post["rate"] is not None and cls in BASELINE_PROPORTIONS else None,
        }
    return {
        "schema": "evalops-error-recurrence/v1",
        "window": {"since": _iso(start), "until": _iso(end), "boundary": BOUNDARY, "merge": MERGE, "bounds": "[since, until)"},
        "baseline": {"n": 441, "rounded": True, "proportions": dict(BASELINE_PROPORTIONS), "counts": None},
        "errors": totals(error_rows),
        "lessons": {**totals(lesson_rows), "marker_rows": len(marked),
                    "unknown_timestamp": sum(r["time"] is None for r in marked),
                    "unknown_classification": sum(not r["classes"] for r in marked)},
        "windows": windows, "comparison": comparison,
        "classification": {
            "mapping_version": "conservative-exact-v1", "open_code_map": dict(OPEN_CODE_MAP), "explicit_aliases": dict(ALIASES),
            "unmapped_open_codes": dict(sorted(Counter(c for r in error_rows for c in r["unmapped"]).items())),
            "rows_with_unmapped_codes": sum(bool(r["unmapped"]) for r in error_rows),
            "invalid_classification_rows": sum(r["invalid"] for r in error_rows),
            "nonbaseline_explicit_classes": dict(sorted(Counter(c for r in error_rows if r["source"] == "explicit" for c in r["classes"] if c not in BASELINE_PROPORTIONS).items())),
        },
        "policy": {
            "multi_label": "Each row counts once per class; class rates can sum above 1. Unknown rows stay in the denominator.",
            "timestamps": "Naive export timestamps assumed UTC, counted explicitly; invalid/missing dates are unknown. CLI/API bounds require a timezone.",
            "recurrence": "A strictly earlier same-class error anywhere in loaded history; duplicate rows are not deduplicated. repeat_excess_in_window = max(count-1, 0), not proof of temporal order.",
            "lesson_markers": "Standalone recur/recurred/recurs/recurrence in decision/rationale/memory/text/content or explicit recur/recurred fields. Class only from explicit error_class, mapped codes or inline error_class=X / recur: CLASS / recurred: CLASS markers; no prose inference.",
            "coverage": "Input rows are the observed sample, not necessarily a census. errors-v0 has 100 coded samples; historical audit n=441 is separate. No population or causal inference.",
        },
        "maturity": {"as_of": _iso(current), "required_days": 7, "elapsed_window_seconds": elapsed,
                     "observed_post_span_seconds": span, "seven_day_replay_ready": elapsed >= week and span >= week,
                     "limitation": "Requires elapsed time and observed error timestamps spanning seven days; does not certify complete capture or prove improvement."},
        "follow_up": {cls: dict(FOLLOW_UP.get(cls, {"owner": "ACX coordinator", "guard": "Review the preserved nonbaseline class.", "check": "Define a class-specific replay before claiming improvement."})) for cls in classes},
        "causal_claim": False,
        "limitations": ["Rates are shares of observed error rows, not errors per dispatch or exposure-adjusted failure rates.",
                        "Mapping is deterministic but provisional; unmapped codes and nonbaseline classes are preserved.",
                        "Baseline proportions are rounded; exact counts are unavailable in this report.",
                        "Short or empty post windows and incomplete input cannot establish a fix's effect."],
    }


def _same_path(left: Path, right: Path) -> bool:
    return left.resolve() == right.resolve() or (left.exists() and right.exists() and left.samefile(right))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--db", help="SQLite path or file: URI; always opened mode=ro")
    source.add_argument("--errors", type=Path, help="exported error JSONL")
    parser.add_argument("--lessons", type=Path, help="optional lesson/memory JSONL")
    parser.add_argument("--since", required=True, help="inclusive timezone-aware ISO timestamp")
    parser.add_argument("--until", required=True, help="exclusive timezone-aware ISO timestamp")
    parser.add_argument("--output", type=Path, help="JSON report path; default stdout")
    parser.add_argument("--max-rows", type=int, default=MAX_ROWS, help="per-input row limit; overflow fails")
    args = parser.parse_args(argv)
    try:
        inputs = [args.errors] if args.errors else [_db_path(args.db)]
        if args.db:
            inputs.extend(Path(str(inputs[0]) + suffix) for suffix in ("-wal", "-shm", "-journal"))
        if args.lessons:
            inputs.append(args.lessons)
        if args.output and any(_same_path(args.output, path) for path in inputs):
            raise ValueError("output must not overwrite an input or SQLite sidecar")
        errors = load_jsonl(args.errors, max_rows=args.max_rows) if args.errors else load_database(args.db, max_rows=args.max_rows)
        lessons = load_jsonl(args.lessons, max_rows=args.max_rows) if args.lessons else []
        result = build_report(errors, lessons, since=args.since, until=args.until)
        result["source"] = {"kind": "sqlite" if args.db else "jsonl", "errors": str(args.db or args.errors),
                            "lessons": str(args.lessons) if args.lessons else None, "max_rows": args.max_rows}
        payload = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
        if args.output:
            args.output.write_text(payload, encoding="utf-8")
        else:
            sys.stdout.write(payload)
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"error_recurrence: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        # sqlite3 is optional: don't import it on the offline path just to name
        # its exception class. Unexpected defects still propagate with traceback.
        if exc.__class__.__module__ != "sqlite3":
            raise
        print(f"error_recurrence: SQLite read failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
