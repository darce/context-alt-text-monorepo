"""Bounded, read-only weekly EVALOPS measurements; see docs/runbooks/evalops.md.

Stdlib only. Exit 0 means the measurement executed, never quality acceptance.
Each successful invocation publishes one exclusive report and prints its JSON.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import os
import re
import stat
import subprocess
import sys
import uuid
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SEEDS = ROOT / "benchmarks/experiments/evalops"
MAX_ROWS = 100_000
MAX_BYTES = 64 * 1024 * 1024
SCHEMA = "evalops.runner.v1"
CODE_FILES = [
    "benchmarks/tools/evalops/run.py",
    "benchmarks/tools/evalops/score_judge.py",
    "benchmarks/tools/evalops/score_retrieval.py",
    "benchmarks/tools/evalops/error_recurrence.py",
    "benchmarks/tools/evalops/score_reliability.py",
    "benchmarks/tools/evalops/score_faithfulness.py",
    "mk/evalops.mk",
    "Makefile",
]
CATEGORY_NAMES = ("reliability", "faithfulness")
QUALITY_PINS = {
    "independent_labels",
    "qc",
    "protocol",
    "accepted_baseline",
    "subject",
    "environment",
    "command",
    "inputs",
}
ERROR_FIELDS = {
    "id",
    "task_ref",
    "error_class",
    "open_codes",
    "created_at",
    "sample_index",
    "source_type",
    "record_id",
    "snippet",
    "text",
    "text_source",
    "in_vivo",
    "coded_by",
}
LESSON_FIELDS = {
    "id",
    "task_ref",
    "doc_id",
    "decision_id",
    "decision",
    "rationale",
    "memory",
    "text",
    "content",
    "recur",
    "recurred",
    "error_class",
    "open_codes",
    "created_at",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def object_fields(value, required, allowed, label):
    require(isinstance(value, dict), f"{label}: expected object")
    require(required <= value.keys(), f"{label}: missing fields {sorted(required - value.keys())}")
    require(value.keys() <= allowed, f"{label}: unexpected fields {sorted(value.keys() - allowed)}")


def text(value):
    return isinstance(value, str) and bool(value.strip())


def timestamp(value, *, aware=True):
    require(isinstance(value, str), "timestamp must be an ISO string")
    parsed = datetime.fromisoformat(value)
    require(not aware or parsed.tzinfo is not None, "timestamp requires timezone")
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def iso(value):
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def json_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def invalid_constant(value):
    raise ValueError(f"invalid JSON constant {value}")


def parse_json(data):
    return json.loads(data, object_pairs_hook=json_pairs, parse_constant=invalid_constant)


def file_bytes(path, max_bytes):
    """Read one bounded regular file; FIFOs/devices cannot block the runner."""
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        require(stat.S_ISREG(os.fstat(stream.fileno()).st_mode), f"{path}: expected regular file")
        data = stream.read(max_bytes + 1)
    require(len(data) <= max_bytes, f"{path}: byte limit {max_bytes} exceeded")
    return data


def provenance(path, data, **extra):
    return {
        "status": "supplied",
        "kind": "file",
        "path": str(Path(path).absolute()),
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        **extra,
    }


def load(path, *, lines, max_rows, max_bytes):
    data = file_bytes(path, max_bytes)
    raw = data.decode("utf-8")
    if not lines:
        return parse_json(raw), provenance(path, data)
    rows = []
    for number, line in enumerate(raw.splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = parse_json(line)
            require(isinstance(row, dict), "expected object")
            require(len(rows) < max_rows, f"row limit {max_rows} exceeded")
            rows.append(row)
        except ValueError as exc:
            raise ValueError(f"{path}:{number}: {exc}") from exc
    return rows, provenance(path, data, rows=len(rows))


def category_protocol(value, max_rows):
    """Validate proposed requests, never authenticate or enforce supplied bars.

    No external authority verifier exists at this boundary. Artifact references
    and even complete provenance are declarations, not acceptance receipts.
    """
    object_fields(value, {"schema_version", "categories"}, {"schema_version", "categories"}, "category protocol")
    require(value["schema_version"] == "evalops.category-protocol.v1", "unsupported category protocol version")
    categories = value["categories"]
    object_fields(categories, set(), set(CATEGORY_NAMES), "categories")
    for request in categories.values():
        fields = {"affected_action", "thresholds", "provenance"}
        object_fields(request, fields, fields, "category request")
        action = request["affected_action"]
        object_fields(action, {"kind", "id"}, {"kind", "id"}, "affected action")
        require(
            action["kind"] == "promotion" and text(action["id"]) and len(action["id"]) <= 256,
            "affected action must identify a bounded promotion",
        )
        thresholds = request["thresholds"]
        require(
            type(thresholds) is list and 0 < len(thresholds) <= min(16, max_rows), "thresholds must be bounded array"
        )
        for threshold in thresholds:
            fields = {"metric", "operator", "value"}
            object_fields(threshold, fields, fields, "threshold")
            metric = threshold["metric"]
            require(
                text(metric)
                and metric.startswith("/")
                and len(metric) <= 256
                and re.search(r"~(?![01])", metric) is None,
                "threshold metric must be a bounded native payload JSON pointer",
            )
            require(threshold["operator"] in ("gte", "lte"), "threshold operator must be gte or lte")
            number = threshold["value"]
            require(
                type(number) in (int, float) and math.isfinite(number) and 0 <= number <= 1,
                "threshold value must be finite in 0..1",
            )
        pins = request["provenance"]
        object_fields(pins, set(), QUALITY_PINS, "accepted quality provenance")
        for pin in pins.values():
            if pin is None:
                continue
            fields = {"ref", "sha256", "version"}
            object_fields(pin, fields, fields, "quality artifact reference")
            require(
                text(pin["ref"])
                and text(pin["version"])
                and isinstance(pin["sha256"], str)
                and re.fullmatch(r"[0-9a-f]{64}", pin["sha256"]),
                "invalid quality artifact reference",
            )
    return categories


def score_category(name, request, max_rows):
    """Call the public scorer with its native contract; preserve its full report."""
    if name == "reliability":
        object_fields(request, {"candidates"}, {"candidates", "trials", "design", "artifacts"}, "reliability request")
        arrays = ("candidates", "trials")
    else:
        arrays = ("cases", "pairwise")
        require(isinstance(request, dict), "faithfulness request: expected object")
    for key in arrays:
        if isinstance(request.get(key), list):
            require(len(request[key]) <= max_rows, f"{key} must be bounded array")
    scorer = importlib.import_module(f"benchmarks.tools.evalops.score_{name}")
    return scorer.score(**request) if name == "reliability" else scorer.score(request)


def category_report(name, source, payload, proposal):
    """Keep measurement, quality, product regression and promotion separate."""
    reasons = ["input_not_supplied"] if payload is None else ["accepted_quality_unavailable"]
    if payload is not None and name == "reliability":
        if payload["cohort"] is None:
            reasons.append("matched_trials_unavailable")
    elif payload is not None:
        reasons.append("semantic_labels_unauthenticated")
    gate = {
        "status": "not_requested",
        "disposition": "none",
        "affected_action": None,
        "validity": "unknown",
        "reason_codes": [],
        "request": None,
    }
    if proposal is not None:
        gate_reasons = ["external_verifier_unavailable"]
        if any(proposal["provenance"].get(key) is None for key in QUALITY_PINS):
            gate_reasons.append("accepted_quality_provenance_missing")
        # [EVAL-12/13] AI Engineering, Canon v0.26.2. No flag, role, digest or
        # self-attested QC can establish independent gold or an accepted baseline.
        gate.update(
            status="unavailable",
            disposition="hold_affected_promotion",
            affected_action=proposal["affected_action"],
            reason_codes=sorted(gate_reasons),
            request=proposal,
        )
    return {
        "status": "unavailable" if payload is None else payload["status"],
        "reason_codes": sorted(reasons),
        "quality_acceptance": "not_evaluated",
        "product_regression": "unknown",
        "pins": {"input": source, "scorer_payload": f"/scorers/{name}/payload"},
        "gate": gate,
    }


def validate_recurrence(rows, *, lessons=False):
    """Keep missing dates/classification unknown; reject malformed supplied data."""
    for number, row in enumerate(rows, 1):
        allowed = LESSON_FIELDS if lessons else ERROR_FIELDS
        object_fields(row, set(), allowed, f"{'lesson' if lessons else 'error'} {number}")
        require(bool(row), f"row {number}: empty recurrence object")
        if not lessons:
            require(bool({"error_class", "open_codes"} & row.keys()), f"error {number}: classification field required")
        if row.get("created_at") is not None:
            timestamp(row["created_at"], aware=False)
        if row.get("open_codes") is not None:
            require(
                isinstance(row["open_codes"], list) and all(text(x) for x in row["open_codes"]),
                "open_codes must be string array or null",
            )
        cls = row.get("error_class")
        require(
            cls is None or isinstance(cls, str) or (isinstance(cls, list) and all(text(x) for x in cls)),
            "error_class must be text/array or null",
        )
        for key in (
            "decision",
            "rationale",
            "memory",
            "text",
            "content",
            "task_ref",
            "doc_id",
            "snippet",
            "source_type",
            "text_source",
            "in_vivo",
            "coded_by",
        ):
            require(row.get(key) is None or isinstance(row[key], str), f"{key} must be text or null")
        for key in ("recur", "recurred"):
            require(row.get(key) is None or isinstance(row[key], (str, bool)), f"{key} must be text/bool or null")
        for key in ("id", "decision_id", "record_id", "sample_index"):
            require(row.get(key) is None or type(row[key]) in (int, str), f"{key} must be integer/text or null")


def db_source(source):
    """Use the scorer's public reader, including its URI validation and close path."""
    from urllib.parse import parse_qs, unquote, urlsplit

    if not source.startswith("file:"):
        return Path(source).resolve()
    uri = urlsplit(source)
    require(
        uri.netloc in ("", "localhost")
        and not uri.fragment
        and parse_qs(uri.query, keep_blank_values=True) in ({}, {"mode": ["ro"]}),
        "SQLite URI must use mode=ro only",
    )
    return Path(unquote(uri.path)).resolve()


def database(source, recurrence, limits):
    path = db_source(source)
    paths = [path] + [Path(str(path) + suffix) for suffix in ("-wal", "-shm", "-journal")]

    def snapshot():
        return [provenance(p, file_bytes(p, limits["max_bytes"])) for p in paths if p == path or p.exists()]

    before = snapshot()
    rows = recurrence.load_database(source, max_rows=limits["max_rows"])
    require(before == snapshot(), "SQLite files changed during read; export a stable snapshot and retry")
    digest = hashlib.sha256(
        json.dumps(rows, sort_keys=True, allow_nan=False, separators=(",", ":")).encode()
    ).hexdigest()
    return (
        rows,
        {
            "status": "supplied",
            "kind": "sqlite_read_only",
            "path": str(path),
            "rows": len(rows),
            "sha256": digest,
            "hash_scope": "canonical projected rows (UTF-8 compact sorted-key JSON array)",
            "files": before,
            "support": "bounded exported rows; census completeness unknown",
        },
        paths,
    )


def code_provenance():
    def git(*args):
        return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True, timeout=10).strip()

    commit, tree = git("rev-parse", "HEAD"), git("rev-parse", "HEAD^{tree}")
    entries = git("ls-tree", "-r", "HEAD", "--", *CODE_FILES)
    blobs = {line.split("\t", 1)[1]: line.split()[2] for line in entries.splitlines()}
    executed = {}
    for name in CODE_FILES:
        data = file_bytes(ROOT / name, MAX_BYTES)
        blob = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
        executed[name] = {"sha256": hashlib.sha256(data).hexdigest(), "matches_tree": blobs.get(name) == blob}
    return {
        "commit": commit,
        "tree_sha": tree,
        "executed_files": executed,
        "executed_files_match_tree": all(v["matches_tree"] for v in executed.values()),
        "tracked_worktree_dirty": bool(git("status", "--porcelain", "--untracked-files=no")),
    }


def replay_report(coverage, errors, source, recurrence, start, end, now, seed):
    support = {"loaded": len(errors), "valid_aware": 0, "naive": 0, "unknown": 0, "in_window": 0}
    for row in errors:
        raw = row.get("created_at")
        if raw is None:
            support["unknown"] += 1
            continue
        parsed = datetime.fromisoformat(raw)
        support["valid_aware" if parsed.tzinfo is not None else "naive"] += 1
        support["in_window"] += start <= timestamp(raw, aware=False) < min(end, now)
    result = {
        "status": "unknown",
        "seven_day_replay_ready": False,
        "required_seconds": 604800,
        "covered_seconds": None,
        "timestamp_support": support,
        "coverage": coverage,
        "observed_post_span_seconds": recurrence["maturity"]["observed_post_span_seconds"],
        "reason": "No capture-coverage evidence supplied; event span is not complete observation.",
    }
    if coverage is None:
        return result
    fields = {"since", "until", "complete", "gaps", "source", "errors_sha256"}
    object_fields(coverage, fields, fields, "coverage")
    a, b = timestamp(coverage["since"]), timestamp(coverage["until"])
    require(a < b, "coverage since must precede until")
    require(type(coverage["complete"]) is bool and isinstance(coverage["gaps"], list), "coverage complete/gaps invalid")
    require(text(coverage["source"]), "coverage source must name capture evidence")
    require(
        isinstance(coverage["errors_sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", coverage["errors_sha256"]),
        "coverage errors_sha256 invalid",
    )
    require(coverage["errors_sha256"] == source["sha256"], "coverage errors_sha256 does not match error input")
    for gap in coverage["gaps"]:
        object_fields(gap, {"since", "until", "reason"}, {"since", "until", "reason"}, "coverage gap")
        require(
            a <= timestamp(gap["since"]) < timestamp(gap["until"]) <= b and text(gap["reason"]), "invalid coverage gap"
        )
    capture_start = max(a, start, timestamp(recurrence["window"]["boundary"]))
    capture_end = min(b, end, now)
    seconds = max(0, (capture_end - capture_start).total_seconds())
    # Count the union of gaps, not their sum (capture interruptions may overlap).
    interruptions = sorted(
        (max(timestamp(g["since"]), capture_start), min(timestamp(g["until"]), capture_end)) for g in coverage["gaps"]
    )
    cursor, missing_seconds = capture_start, 0
    for gap_start, gap_end in interruptions:
        if gap_end > max(cursor, gap_start):
            missing_seconds += (gap_end - max(cursor, gap_start)).total_seconds()
            cursor = gap_end
    covered = max(0, seconds - missing_seconds) if coverage["complete"] else None
    ready = (
        not seed
        and coverage["complete"]
        and not coverage["gaps"]
        and seconds >= 604800
        and not support["naive"]
        and not support["unknown"]
    )
    result.update(
        status="mature" if ready else "insufficient",
        seven_day_replay_ready=bool(ready),
        covered_seconds=covered,
        attested_interval_seconds=seconds,
        reason=(
            "Operator-attested complete capture; not independently audited or evidence of improvement."
            if ready
            else "Need seven post-boundary days of complete, gap-free capture with aware timestamps; seed coverage is unknown."
        ),
    )
    return result


def publish(path, payload):
    """Pin directory descriptors without following symlinks; link a complete new file.

    Exclusive hard-link publication cannot replace an artifact, input or symlink.
    Only our private temporary file is removed, including on failed publication.
    """
    path = Path(os.path.abspath(path))
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    directory = os.open(path.anchor, flags)
    temporary = f".evalops-{uuid.uuid4().hex}.tmp"
    created = False
    try:
        for part in path.parent.parts[1:]:
            with suppress(FileExistsError):
                os.mkdir(part, mode=0o700, dir_fd=directory)
            next_directory = os.open(part, flags, dir_fd=directory)
            os.close(directory)
            directory = next_directory
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        created = True
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path.name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
    finally:
        if created:
            os.unlink(temporary, dir_fd=directory)
        os.close(directory)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("findings", "qrels"):
        parser.add_argument(f"--{name}", type=Path, default=SEEDS / f"{name}-v0.jsonl")
    sources = parser.add_mutually_exclusive_group()
    sources.add_argument("--errors", type=Path)
    sources.add_argument("--db")
    for name in ("lessons", "predictions", "qc", "results", "coverage"):
        parser.add_argument(f"--{name}", type=Path)
    for name in (*CATEGORY_NAMES, "category-protocol"):
        parser.add_argument(f"--{name}", type=Path, help="optional offline JSON; never establishes quality acceptance")
    for name in ("since", "until", "now"):
        parser.add_argument(f"--{name}")
    parser.add_argument("--k", type=int, action="append")
    parser.add_argument("--pool-depth", type=int)
    parser.add_argument("--pool-contributor", action="append")
    parser.add_argument("--max-rows", type=int, default=MAX_ROWS)
    parser.add_argument("--max-bytes", type=int, default=MAX_BYTES)
    parser.add_argument("--output", type=Path, help="exclusive new report path; overrides --output-dir")
    parser.add_argument("--output-dir", type=Path, default=ROOT / ".task-state/evalops/reports")
    args = parser.parse_args(argv)
    try:
        require(
            0 < args.max_rows <= MAX_ROWS and 0 < args.max_bytes <= MAX_BYTES,
            "limits must be positive and at most built-in bounds",
        )
        limits = {"max_rows": args.max_rows, "max_bytes": args.max_bytes}
        now = timestamp(args.now) if args.now else datetime.now(UTC)
        end = timestamp(args.until) if args.until else now
        start = timestamp(args.since) if args.since else end - timedelta(days=7)
        require(start < end, "since must precede until")
        # Direct script invocation from another cwd has the same imports as -m.
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        judge = importlib.import_module("benchmarks.tools.evalops.score_judge")
        retrieval = importlib.import_module("benchmarks.tools.evalops.score_retrieval")
        recurrence = importlib.import_module("benchmarks.tools.evalops.error_recurrence")
        inputs, rows, protected = {}, {}, []
        paths = {
            "findings": args.findings,
            "qrels": args.qrels,
            "predictions": args.predictions,
            "qc": args.qc,
            "results": args.results,
            "coverage": args.coverage,
            "reliability": args.reliability,
            "faithfulness": args.faithfulness,
            "category_protocol": args.category_protocol,
        }
        paths["lessons"] = (
            args.lessons if args.lessons else (None if args.db or args.errors else SEEDS / "lessons-v0.jsonl")
        )
        paths["errors"] = None if args.db else (args.errors or SEEDS / "errors-v0.jsonl")
        for name, path in paths.items():
            if path is None:
                inputs[name] = {"status": "unavailable", "reason": f"{name} not supplied"}
                rows[name] = None
                continue
            input_limits = dict(limits)
            if name in CATEGORY_NAMES:
                scorer = importlib.import_module(f"benchmarks.tools.evalops.score_{name}")
                input_limits["max_bytes"] = min(args.max_bytes, scorer.MAX_BYTES)
            rows[name], inputs[name] = load(
                path, lines=name in ("findings", "qrels", "errors", "lessons", "results"), **input_limits
            )
            protected.append(path)
        proposals = category_protocol(rows["category_protocol"], args.max_rows) if args.category_protocol else {}
        category_scorers, categories = {}, {}
        for name in CATEGORY_NAMES:
            payload = score_category(name, rows[name], args.max_rows) if paths[name] is not None else None
            category_scorers[name] = {
                "status": "unavailable" if payload is None else payload["status"],
                "reason": f"{name} not supplied" if payload is None else None,
                "payload": payload,
            }
            categories[name] = category_report(name, inputs[name], payload, proposals.get(name))
        if args.db:
            rows["errors"], inputs["errors"], db_paths = database(args.db, recurrence, limits)
            protected.extend(db_paths)
        seed = paths["errors"] is not None and paths["errors"].resolve() == (SEEDS / "errors-v0.jsonl").resolve()
        inputs["errors"]["support"] = (
            "coded_sample_100_not_census_441" if seed else "supplied sample; census completeness unknown"
        )
        validate_recurrence(rows["errors"])
        validate_recurrence(rows["lessons"] or [], lessons=True)
        predictions, protocol = None, None
        if args.predictions:
            pred = rows["predictions"]
            object_fields(pred, {"predictions"}, {"predictions", "protocol"}, "predictions file")
            require(
                isinstance(pred["predictions"], list) and len(pred["predictions"]) <= args.max_rows,
                "predictions must be bounded array",
            )
            predictions, protocol = pred["predictions"], pred.get("protocol")
        if args.qc:
            qc = rows["qc"]
            object_fields(qc, {"decisions"}, {"decisions"}, "qc")
            require(
                isinstance(qc["decisions"], list) and len(qc["decisions"]) <= args.max_rows,
                "QC decisions must be bounded array",
            )
        judge_report = judge.score(rows["findings"], predictions, rows["qc"], protocol=protocol)
        ks = args.k or [5, 10]
        require(len(ks) <= 16 and all(0 < k <= 10000 for k in ks), "supply at most 16 k values in 1..10000")
        # Validate qrels/pool even without rankings, but NEVER publish the zero
        # metrics this validation-only call computes for an empty results list.
        ranked = retrieval.score(
            rows["qrels"],
            rows["results"] if args.results else [],
            ks,
            pool_depth=args.pool_depth,
            pool_contributors=args.pool_contributor,
        )
        retrieval_report = {
            "status": "scored" if args.results else "unavailable",
            "reason": None if args.results else "results not supplied; no retrieval run observed",
            "payload": ranked if args.results else None,
            "qrel_support": {k: ranked["counts"][k] for k in ("query_count", "judgment_count", "unknown_qrel_count")},
            "pool": ranked["pool"],
        }
        recurrence_report = recurrence.build_report(
            rows["errors"], rows["lessons"] or [], since=iso(start), until=iso(end), now=iso(now)
        )
        if args.coverage:
            require(isinstance(rows["coverage"], dict), "coverage file must be an object")
        replay = replay_report(
            rows["coverage"], rows["errors"], inputs["errors"], recurrence_report, start, end, now, seed
        )
        report = {
            "schema_version": SCHEMA,
            "task_ref": "EVALOPS-1-RUNNER",
            "umbrella": "EVALOPS-1",
            "execution_status": "ok",
            "observed_at": iso(now),
            "code": code_provenance(),
            "window": {
                "since": iso(start),
                "until": iso(end),
                "bounds": "[since, until)",
                "duration_seconds": (end - start).total_seconds(),
                "source": "explicit" if args.since and args.until else "requested/default window; not capture evidence",
            },
            "inputs": inputs,
            "limits": limits,
            "scorers": {
                "judge": judge_report,
                "retrieval": retrieval_report,
                "recurrence": recurrence_report,
                **category_scorers,
            },
            "categories": categories,
            "replay": replay,
            "statistical_acceptance": {
                "status": "not_evaluated",
                "reason": "No quality floor accepted; independent human labels/QC and a predeclared acceptance protocol are required. QC covers supplied identities only.",
            },
            "limitations": [
                "Seed errors are a coded 100-row sample, not the historical 441-row audit.",
                "Recurrence comparisons use rounded historical proportions; no causal improvement claim.",
                "Use top-level replay readiness for weekly interpretation; nested scorer span does not establish capture coverage.",
                "Coverage is operator attestation bound to error evidence, not an independent capture audit.",
                "Defaults never establish seven days of valid observations; unavailable evidence is not a failed quality gate.",
            ],
        }
        payload = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
        output = args.output or args.output_dir / f"evalops-{now.strftime('%Y%m%dT%H%M%S%fZ')}-{uuid.uuid4().hex}.json"
        require(
            all(output.resolve() != Path(p).resolve() for p in protected),
            "output must not overwrite input or SQLite sidecar",
        )
        publish(output, payload)
        sys.stdout.write(payload)
        return 0
    # [AGT-10] Degrade loudly, The Art of UNIX Programming, ch. 1; Canon v0.26.2.
    except (
        OSError,
        UnicodeError,
        ValueError,
        TypeError,
        RuntimeError,
        ImportError,
        OverflowError,
        subprocess.SubprocessError,
    ) as exc:
        print(json.dumps({"schema_version": SCHEMA, "execution_status": "error", "error": str(exc)}), file=sys.stderr)
        return 2
    except Exception as exc:
        if exc.__class__.__module__ != "sqlite3":
            raise
        print(
            json.dumps({"schema_version": SCHEMA, "execution_status": "error", "error": f"SQLite read failed: {exc}"}),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
