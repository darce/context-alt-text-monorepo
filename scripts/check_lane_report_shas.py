#!/usr/bin/env python3
"""Fail when a committed lane report cites a commit SHA that does not resolve.

Offload lanes work in a sandbox clone whose history is stripped to a synthetic
base. ``git rev-parse HEAD`` succeeds there, so a lane report can truthfully cite
a SHA that ceases to exist the moment the work is transported into the
destination worktree under a different commit. Four briefs in the VLM-6 wave
instructed lanes to take the SHA from ``rev-parse`` after committing, and one
additionally demanded ``git cat-file`` verification; the failure recurred every
time (VLM6-S2A-F2D-01, VLM6-S2A-F3-02). Warnings in the brief cannot fix it —
the lane has no way to know its destination SHA at write time.

So verify at the destination instead. Every hex token this script flags is one a
reviewer would otherwise look up and not find, in the single field they most
need to anchor evidence.

Scoped deliberately: only lines that *present* a token as a commit are checked.
Bare hex elsewhere in a report is usually a manifest ``sha256`` prefix, an
ISO-ish date (``20260811``), or a test fixture (``6666…``) — flagging those
would train readers to ignore the guard. Note the word "sha" alone is *not*
commit vocabulary: these reports say "fetch sha" and "golden sha" about manifest
digests far more often than about commits.

Two escapes exist for citations that are deliberately unresolvable:

* HTML comments. A correction annotation ("the lane cited ``ac2740b``, which
  resolves nowhere here") must be able to quote the bad SHA without the guard
  re-flagging the very thing it documents.
* An explicit inline ``sha-guard:ignore`` marker, for prose that names a
  foreign-repo or sandbox commit on purpose and says so.

Usage:
    scripts/check_lane_report_shas.py [path ...]   # default: **/.s2a/*.md
    scripts/check_lane_report_shas.py --scan-staged
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# A line only counts as a commit citation when it names one. Manifest digests,
# dates and fixtures live outside this vocabulary. "sha" is absent on purpose —
# it is the word these reports use for `manifest_sha256` values.
_CITATION_CONTEXT = re.compile(
    r"(?:\bcommit\b|\bHEAD\b|rev-parse|cat-file|git\s+(?:log|show|checkout)|\bland(?:ed|s)?\b)",
    re.IGNORECASE,
)
# Anything explicitly labelled a content digest is not a commit.
_DIGEST_CONTEXT = re.compile(r"sha256|manifest_sha|digest", re.IGNORECASE)
_IGNORE_MARKER = "sha-guard:ignore"
_HEX = re.compile(r"\b([0-9a-f]{7,40})\b")
# All-digit runs are dates (20260811), not abbreviated objects.
_ALL_DIGITS = re.compile(r"^\d+$")


def _resolves(repo: Path, token: str) -> bool:
    proc = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "-t", token],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode == 0 and proc.stdout.strip() == "commit"


def scan_file(repo: Path, path: Path) -> list[str]:
    violations: list[str] = []
    rel = path.relative_to(repo) if path.is_absolute() else path
    in_comment = False
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        was_comment = in_comment
        if "<!--" in line:
            in_comment = "-->" not in line.split("<!--", 1)[1]
        elif in_comment and "-->" in line:
            in_comment = False
        # A comment that opens on this line covers it too: correction notes quote
        # the unresolvable SHA they exist to document.
        if was_comment or in_comment or "<!--" in line:
            continue
        if _IGNORE_MARKER in line:
            continue
        if not _CITATION_CONTEXT.search(line) or _DIGEST_CONTEXT.search(line):
            continue
        for token in _HEX.findall(line):
            if _ALL_DIGITS.match(token) or _resolves(repo, token):
                continue
            violations.append(
                f"{rel}:{lineno}: cited commit `{token}` does not resolve — "
                f"resolve it against `git log` in this worktree, or drop the citation "
                f"(or add `{_IGNORE_MARKER}` if it is deliberately foreign)"
            )
    return violations


def _repo_root() -> Path:
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(out.stdout.strip())


def _staged_reports(repo: Path) -> list[Path]:
    out = subprocess.run(
        ["git", "-C", str(repo), "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [repo / name for name in out.stdout.split() if "/.s2a/" in f"/{name}" and name.endswith(".md")]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--scan-staged", action="store_true", help="check staged lane reports only")
    args = parser.parse_args(argv)

    repo = _repo_root()
    if args.scan_staged:
        targets = _staged_reports(repo)
    elif args.paths:
        targets = [p if p.is_absolute() else repo / p for p in args.paths]
    else:
        targets = sorted(repo.glob(".s2a/*.md")) + sorted(repo.glob("*/.s2a/*.md"))

    violations: list[str] = []
    for path in targets:
        if path.is_file():
            violations.extend(scan_file(repo, path))

    if violations:
        print("Lane reports cite commits that do not exist in this repository:", file=sys.stderr)
        for v in violations:
            print(f"  - {v}", file=sys.stderr)
        print(
            "\nA lane's sandbox-clone SHA is not the SHA the work landed under. "
            "Use `git log --diff-filter=A -- <report>` to find the real one.",
            file=sys.stderr,
        )
        return 1

    print(f"lane report SHA citations: {len(targets)} file(s) checked, all resolve")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
