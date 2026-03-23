"""ACE reflection helpers for instruction-file strategy bullet evolution.

Ownership rule: instruction-file edits (ace_apply_counters) must only be called
from 'make ace-reflect' (__main__ path) or ace_reflect_on_findings() (manual
batch helper). Never from daemon or worker context.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


# Pattern for ACE strategy bullets:
# - [sr-001] helpful=2 harmful=0 :: rule text
# - [rg-013] helpful=1 harmful=0 :: rule text
_BULLET_RE = re.compile(
    r"^\s*-\s+\[(?P<rule_id>(?:sr|rg)-\d{3})\]\s+"
    r"helpful=(?P<helpful>\d+)\s+"
    r"harmful=(?P<harmful>\d+)\s*::\s*(?P<text>.+)$"
)

# Pattern that identifies any ACE rule reference in free text
_RULE_REF_RE = re.compile(r"\[(?:sr|rg)-\d{3}\]")

# Keywords that indicate a finding *contradicts* a rule (as opposed to merely citing it)
_CONTRADICTION_KEYWORDS = frozenset(
    [
        "violat",
        "missing",
        "contradict",
        "breaks",
        "broke",
        "fail",
        "ignored",
        "bypass",
        "incorrect",
    ]
)


def parse_strategy_bullets(filepath: Path) -> dict[str, dict]:
    """Parse ACE strategy bullets from an instruction file.

    Returns a dict keyed by rule_id:
        {
            "sr-001": {
                "helpful": 3,
                "harmful": 0,
                "text": "Do not relax compliance/lint scripts...",
                "line_number": 139,
            },
            ...
        }

    Lines that do not match the ACE bullet format are silently skipped.
    Returns an empty dict if the file does not exist or contains no bullets.
    """
    results: dict[str, dict] = {}
    if not filepath.exists():
        return results
    for line_number, line in enumerate(filepath.read_text(encoding="utf-8").splitlines(), start=1):
        m = _BULLET_RE.match(line)
        if m:
            results[m.group("rule_id")] = {
                "helpful": int(m.group("helpful")),
                "harmful": int(m.group("harmful")),
                "text": m.group("text").strip(),
                "line_number": line_number,
            }
    return results


def detect_rule_references(text: str) -> list[str]:
    """Return all unique ACE rule IDs ([sr-NNN] / [rg-NNN]) found in *text*."""
    found = _RULE_REF_RE.findall(text)
    # Strip brackets, deduplicate, preserve order of first occurrence
    seen: dict[str, None] = {}
    for raw in found:
        key = raw[1:-1]  # remove '[' and ']'
        seen[key] = None
    return list(seen)


def classify_rule_reference(text: str, rule_id: str) -> bool:
    """Return True when *text* indicates that *rule_id* was *contradicted*.

    A reference is classified as a contradiction when the surrounding sentence
    contains a contradiction keyword AND the rule_id itself appears in that
    sentence.  A sentence is considered as the 80-character neighbourhood
    around the rule_id occurrence (left + right).
    """
    pattern = re.compile(re.escape(f"[{rule_id}]"))
    text_lower = text.lower()
    for m in pattern.finditer(text_lower):
        start = max(0, m.start() - 80)
        end = min(len(text_lower), m.end() + 80)
        neighbourhood = text_lower[start:end]
        for kw in _CONTRADICTION_KEYWORDS:
            if kw in neighbourhood:
                return True
    return False


def increment_counter(
    rule_id: str,
    counter: str,  # "helpful" or "harmful"
    filepath: Path,
    dedup_key: str,
) -> bool:
    """Increment *counter* for *rule_id* in *filepath* if *dedup_key* is new.

    *dedup_key* is an opaque string (e.g. ``finding_id:sr-001``) that prevents
    double-counting the same finding for the same rule.  Processed keys are
    stored as JSON in a sidecar file next to *filepath*.

    Returns True when the counter was actually incremented, False when the
    dedup_key was already present (no-op).
    """
    if counter not in ("helpful", "harmful"):
        raise ValueError(f"counter must be 'helpful' or 'harmful', got {counter!r}")

    sidecar = filepath.with_suffix(filepath.suffix + ".ace_dedup.json")

    # Load dedup set
    dedup_set: set[str] = set()
    if sidecar.exists():
        try:
            dedup_set = set(json.loads(sidecar.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, TypeError):
            dedup_set = set()

    if dedup_key in dedup_set:
        return False  # already processed

    # Read file and patch the matching bullet line
    text = filepath.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    modified = False
    for i, line in enumerate(lines):
        m = _BULLET_RE.match(line)
        if m and m.group("rule_id") == rule_id:
            old_val = int(m.group(counter))
            new_val = old_val + 1
            lines[i] = line.replace(
                f"{counter}={old_val}",
                f"{counter}={new_val}",
                1,
            )
            modified = True
            break

    if not modified:
        return False

    filepath.write_text("".join(lines), encoding="utf-8")
    dedup_set.add(dedup_key)
    sidecar.write_text(json.dumps(sorted(dedup_set), indent=2), encoding="utf-8")
    return True


def identify_pruning_candidates(filepath: Path) -> list[dict]:
    """Return bullets where helpful==0 and harmful>=2 (pruning candidates)."""
    bullets = parse_strategy_bullets(filepath)
    return [
        {"rule_id": rid, **info}
        for rid, info in bullets.items()
        if info["helpful"] == 0 and info["harmful"] >= 2
    ]


def ace_reflect_on_findings(
    findings: list[dict[str, Any]],
    instruction_files: list[Path],
    state_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Scan *findings* for ACE rule references and classify them.

    Expects each finding dict to have at least ``id`` and ``description`` keys.
    Returns a list of flat reflection records:
        [{"finding_id": ..., "rule_id": ..., "contradicts": bool}, ...]

    *state_dir* (optional): when provided, this function operates as the manual
    batch path for findings that bypassed the worker daemon:

      1. Appends each record (plus a UTC ``timestamp`` field) to
         ``state_dir/ace_reflect_log.jsonl``.
      2. Calls ``ace_apply_counters`` to process ALL pending log entries
         (including any previously daemon-logged entries).

    When *state_dir* is ``None`` (the default), the function returns records
    without any file I/O — this is the daemon path where the caller writes
    the records itself and counter updates are deferred to ``make ace-reflect``.

    Ownership rule: when *state_dir* is supplied, this function must only be
    called from the orchestrator root.  Never call with *state_dir* from a
    daemon or worker context (prevents concurrent instruction-file edits).
    """
    import datetime as _dt  # noqa: PLC0415

    records: list[dict[str, Any]] = []
    known_rules: set[str] = set()
    for fp in instruction_files:
        known_rules.update(parse_strategy_bullets(fp).keys())

    for finding in findings:
        finding_id = finding.get("id") or finding.get("finding_id", "unknown")
        description = finding.get("description") or finding.get("text") or ""
        refs = detect_rule_references(description)
        for rule_id in refs:
            if rule_id not in known_rules:
                continue
            contradicts = classify_rule_reference(description, rule_id)
            records.append(
                {
                    "finding_id": finding_id,
                    "rule_id": rule_id,
                    "contradicts": contradicts,
                }
            )

    if state_dir is not None and records:
        state_dir.mkdir(parents=True, exist_ok=True)
        reflect_log = state_dir / "ace_reflect_log.jsonl"
        ts = _dt.datetime.now(_dt.timezone.utc).isoformat().replace("+00:00", "Z")
        with reflect_log.open("a", encoding="utf-8") as fh:
            for rec in records:
                entry = dict(rec)
                entry["timestamp"] = ts
                fh.write(json.dumps(entry) + "\n")
        ace_apply_counters(reflect_log, instruction_files)

    return records


def ace_apply_counters(
    reflect_log: Path,
    instruction_files: list[Path],
) -> dict[str, int]:
    """Process unprocessed entries in *reflect_log* and increment counters.

    *reflect_log* is a JSONL file where each line is a record written either
    by the worker daemon ACE detection hook or by ``ace_reflect_on_findings``.
    Each record must contain: ``finding_id``, ``rule_id``, ``contradicts``.

    Returns a summary: {total_processed: int, incremented: int, skipped: int}.
    """
    if not reflect_log.exists():
        return {"total_processed": 0, "incremented": 0, "skipped": 0}

    processed = 0
    incremented = 0
    skipped = 0

    lines = reflect_log.read_text(encoding="utf-8").splitlines()
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            skipped += 1
            continue

        finding_id = record.get("finding_id", "unknown")
        rule_id = record.get("rule_id")
        contradicts = record.get("contradicts", False)

        if not rule_id:
            skipped += 1
            continue

        counter = "harmful" if contradicts else "helpful"
        dedup_key = f"{finding_id}:{rule_id}:{counter}"

        did_update = False
        for fp in instruction_files:
            if increment_counter(rule_id, counter, fp, dedup_key):
                did_update = True

        processed += 1
        if did_update:
            incremented += 1

    # Persist the processed-line count so the orchestrator daemon can compute
    # genuinely unprocessed entries without false positives after a successful
    # `make ace-reflect` run.  The offset tracks how many non-empty lines have
    # been seen by this function; new appends to the log appear above the offset.
    total_non_empty = sum(1 for l in lines if l.strip())
    offset_file = reflect_log.with_name(reflect_log.name + ".offset")
    try:
        offset_file.write_text(
            json.dumps({"processed_line_count": total_non_empty}), encoding="utf-8"
        )
    except OSError:
        pass

    return {
        "total_processed": processed,
        "incremented": incremented,
        "skipped": skipped,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply pending ACE counter updates or print a curation report.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--task-ref",
        default="current",
        help="Task reference (used to locate reflect_log inside state-dir).",
    )
    parser.add_argument(
        "--state-dir",
        default=".task-state",
        help="Path to the .task-state directory.",
    )
    parser.add_argument(
        "--instruction-files",
        nargs="+",
        default=[
            "docs/agentic/instructions.md",
        ],
        help="Instruction files that contain ACE strategy bullets.  CLAUDE.md and GEMINI.md are symlinks to instructions.md; do not list them separately.",
    )
    parser.add_argument(
        "--curation-report-only",
        action="store_true",
        help="Print pruning candidates and bullet summary; do not write any files.",
    )
    return parser.parse_args()


def _curation_report(instruction_files: list[Path]) -> None:
    """Print a curation report for all instruction files."""
    for fp in instruction_files:
        if not fp.exists():
            print(f"  {fp}: not found")
            continue
        bullets = parse_strategy_bullets(fp)
        candidates = identify_pruning_candidates(fp)
        print(f"\n## {fp}")
        print(f"  Total bullets: {len(bullets)}")
        total_helpful = sum(v['helpful'] for v in bullets.values())
        total_harmful = sum(v['harmful'] for v in bullets.values())
        print(f"  helpful sum: {total_helpful}  harmful sum: {total_harmful}")
        if candidates:
            print(f"  Pruning candidates ({len(candidates)}):")
            for c in candidates:
                print(f"    [{c['rule_id']}] helpful={c['helpful']} harmful={c['harmful']} :: {c['text'][:80]}")
        else:
            print("  No pruning candidates.")


def main() -> int:
    args = _parse_args()
    state_dir = Path(args.state_dir)
    instruction_files = [Path(f) for f in args.instruction_files]

    if args.curation_report_only:
        print("# ACE Curation Report")
        _curation_report(instruction_files)
        return 0

    reflect_log = state_dir / "ace_reflect_log.jsonl"
    summary = ace_apply_counters(reflect_log, instruction_files)
    print(
        f"ace-reflect: processed={summary['total_processed']}  "
        f"incremented={summary['incremented']}  skipped={summary['skipped']}"
    )
    if summary["total_processed"] == 0:
        print("  No pending entries in", reflect_log)
    return 0


if __name__ == "__main__":
    sys.exit(main())
