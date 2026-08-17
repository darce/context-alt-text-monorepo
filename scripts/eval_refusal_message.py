#!/usr/bin/env python3
"""Print the scorer's actual refusal invariant and a mapped remedy.

Several distinct invariants exit 3. A single hardcoded cause/remedy is
wrong for half of them (S2R5-14). This helper reads the invariant the
scorer produced (report JSON ``faces.*.invariant`` or the score-gate
stderr line) and maps remedy text to that name.

The remediating corpus edit is **not** claimed to be executable on any
in-tree golden (pending R6-B wording). Consent with ``--allow-refused``
is always the no-score alternative.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Iterable

# Canonical ScoreInvariant values (origin: eval_harness.manifest).
# Kept as strings here so this operator helper does not import the scorer.
DETECTION_REQUIRES_ANNOTATION_MODE = "detection_requires_annotation_mode"
DETECTION_REFUSES_ROSTER_ONLY = "detection_refuses_roster_only"
DETECTION_UNRECOGNISED_ANNOTATION_MODE = "detection_unrecognised_annotation_mode"
DETECTION_REFUSES_EMPTY_ENTRIES = "detection_refuses_empty_entries"
DETECTION_REFUSES_MIXED_ANNOTATION_MODE = "detection_refuses_mixed_annotation_mode"
DETECTION_REFUSES_UNCOVERED_FACE_COUNT = "detection_refuses_uncovered_face_count"
DETECTION_REFUSES_EMPTY_OBSERVATIONS = "detection_refuses_empty_observations"
IDENTIFICATION_REFUSES_UNBOXED_IDENTITY_CLAIMS = (
    "identification_refuses_unboxed_identity_claims"
)
IDENTIFICATION_REFUSES_EMPTY_OBSERVATIONS = (
    "identification_refuses_empty_observations"
)

REMEDIES: dict[str, str] = {
    DETECTION_REQUIRES_ANNOTATION_MODE: (
        "Detection P/R is refused because annotation_mode is missing. "
        "Stamp a recognised mode on the scored corpus, or pass "
        "--allow-refused for a no-score report."
    ),
    DETECTION_REFUSES_ROSTER_ONLY: (
        "Detection P/R is refused because annotation_mode is roster_only "
        "(labelled face counts are a lower bound). Honest detection "
        "requires exhaustive boxing; that remediating edit is not claimed "
        "to be executable on the shipped golden. Pass --allow-refused "
        "for a no-score report."
    ),
    DETECTION_UNRECOGNISED_ANNOTATION_MODE: (
        "Detection P/R is refused because annotation_mode is not a "
        "recognised lattice token. Use exhaustive or roster_only, or pass "
        "--allow-refused for a no-score report."
    ),
    DETECTION_REFUSES_EMPTY_ENTRIES: (
        "Detection P/R is refused because the scored entry set is empty. "
        "Score a non-empty corpus, or pass --allow-refused for a no-score "
        "report."
    ),
    DETECTION_REFUSES_MIXED_ANNOTATION_MODE: (
        "Detection P/R is refused because scored entries mix "
        "annotation_mode values. Use one mode for the scored set, or pass "
        "--allow-refused for a no-score report."
    ),
    DETECTION_REFUSES_UNCOVERED_FACE_COUNT: (
        "Detection P/R is refused because a face_count is not covered by "
        "boxes. Cover every counted face or lower the count, or pass "
        "--allow-refused for a no-score report."
    ),
    DETECTION_REFUSES_EMPTY_OBSERVATIONS: (
        "Detection P/R is refused because the run produced zero scorable "
        "detection observations. Pass --allow-refused for a no-score report."
    ),
    IDENTIFICATION_REFUSES_UNBOXED_IDENTITY_CLAIMS: (
        "Identification P/R is refused because identity claims have no "
        "per-face box lineage. An honest score needs boxed named faces "
        "with lineage on the scored population; that remediating edit is "
        "not claimed to be executable on the shipped golden. Pass "
        "--allow-refused for a no-score report."
    ),
    IDENTIFICATION_REFUSES_EMPTY_OBSERVATIONS: (
        "Identification P/R is refused because the run produced zero "
        "scorable identification observations. Pass --allow-refused for "
        "a no-score report."
    ),
}

GATE_PAIR_RE = re.compile(
    r"\b(detection|identification)=([A-Za-z0-9_]+)"
)
UNKNOWN_REMEDY = (
    "No single in-tree remediating edit is assumed for this invariant. "
    "Inspect the report's faces.*.invariant and pass --allow-refused "
    "only if you consent to a no-score report."
)


def invariants_from_report(payload: object) -> list[tuple[str, str]]:
    """Return (metric, invariant) pairs from a scored report JSON."""
    if not isinstance(payload, dict):
        return []
    faces = payload.get("faces")
    if not isinstance(faces, dict):
        return []
    found: list[tuple[str, str]] = []
    for metric in ("detection", "identification"):
        block = faces.get(metric)
        if not isinstance(block, dict):
            continue
        if not block.get("refused"):
            continue
        invariant = block.get("invariant")
        if isinstance(invariant, str) and invariant.strip():
            found.append((metric, invariant.strip()))
    return found


def invariants_from_text(text: str) -> list[tuple[str, str]]:
    """Parse ``detection=INV`` / ``identification=INV`` from scorer text."""
    found: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for match in GATE_PAIR_RE.finditer(text):
        pair = (match.group(1), match.group(2))
        if pair in seen:
            continue
        seen.add(pair)
        found.append(pair)
    return found


def merge_invariants(*groups: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    merged: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for group in groups:
        for pair in group:
            if pair in seen:
                continue
            seen.add(pair)
            merged.append(pair)
    return merged


def format_refusal_message(invariants: list[tuple[str, str]]) -> str:
    lines = [
        "eval: REFUSED (scorer exit 3). Invariant(s) the scorer produced:",
    ]
    if not invariants:
        lines.append("  (none parsed from scorer output or report JSON)")
        lines.append(f"  remedy: {UNKNOWN_REMEDY}")
    else:
        for metric, invariant in invariants:
            remedy = REMEDIES.get(invariant, UNKNOWN_REMEDY)
            lines.append(f"  {metric}: {invariant}")
            lines.append(f"    remedy: {remedy}")
    lines.append(
        "Do not assume a single cause. Consent at the call site with "
        "--allow-refused only if you accept a no-score report."
    )
    return "\n".join(lines)


def _load_report(path: Path) -> object | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def collect_invariants(
    *,
    report: Path | None = None,
    log_text: str = "",
) -> list[tuple[str, str]]:
    from_report: list[tuple[str, str]] = []
    if report is not None and report.is_file():
        payload = _load_report(report)
        if payload is not None:
            from_report = invariants_from_report(payload)
    return merge_invariants(from_report, invariants_from_text(log_text))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="scored report JSON (reads faces.*.invariant)",
    )
    parser.add_argument(
        "--log",
        type=Path,
        default=None,
        help="captured scorer stdout/stderr",
    )
    parser.add_argument(
        "--log-text",
        default="",
        help="scorer text already in memory (a10 wrappers)",
    )
    args = parser.parse_args(argv)
    log_text = args.log_text
    if args.log is not None and args.log.is_file():
        log_text = args.log.read_text(encoding="utf-8") + log_text
    if not log_text and not sys.stdin.isatty():
        log_text = sys.stdin.read()
    invariants = collect_invariants(report=args.report, log_text=log_text)
    print(format_refusal_message(invariants), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
