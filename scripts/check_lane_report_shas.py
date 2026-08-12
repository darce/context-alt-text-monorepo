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

So verify at the destination instead. Every candidate hex token that is not an
explicitly excluded content digest is resolved against this repo; unresolvable
tokens fail the guard. Missing or unreadable target paths also fail closed
(VLM6-D-03) — CI must not print "N file(s) checked, all resolve" for files that
were never opened.

Narrow content-digest exclusions (justified, per-token — not whole-line vetoes):

* ``sha256:``-prefixed tokens (content digests, not git objects)
* Tokens labelled ``manifest_sha256`` / ``msha=`` (manifest content digests)
* Tokens labelled as fetch/golden/score-time/model_dump sha prefixes
* Tokens that open a ``sha256sum``-style digest listing (``deadbeef…  path``)
* Full-width / ASCII ellipsis truncated digest prefixes in those contexts

Two escapes remain for citations that are deliberately unresolvable:

* HTML comments. A correction annotation ("the lane cited ``ac2740b``, which
  resolves nowhere here") must be able to quote the bad SHA without the guard
  re-flagging the very thing it documents. Only the comment span is skipped —
  a citation *outside* the comment on the same line is still checked (VLM6-D-05).
* An explicit inline ``sha-guard:ignore`` marker on the non-comment portion of
  the line, for prose that names a foreign-repo or sandbox commit on purpose
  and says so.

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

_IGNORE_MARKER = "sha-guard:ignore"
# Case-insensitive: uppercase / mixed-case display forms must not escape (VLM6-D-04).
_HEX = re.compile(r"\b([0-9a-fA-F]{7,40})\b")
# All-digit runs are dates (20260811), not abbreviated objects.
_ALL_DIGITS = re.compile(r"^\d+$")

# Per-token content-digest exclusions. Whole-line keyword vetoes are rejected
# (VLM6-D-05): a line that mentions "digest" must still flag an unresolvable
# commit citation sitting next to that word.
_BEFORE_DIGEST = re.compile(
    r"(?:"
    r"sha256\s*:\s*[`'\"]?"  # sha256: deadbeef
    # Label may be backticked: freeze `manifest_sha256` was `deadbeef`
    r"|manifest_sha256[`'\"]?\s*(?:=|:|\bwas\b|\bis\b)?\s*[`'\"]?"
    r"|\bmsha\s*=\s*[`'\"]?"
    r"|(?:content|image|file)[_\s-]?digest\s*(?:=|:)?\s*[`'\"]?"
    r"|(?:fetch|golden|score-time(?:\s+golden)?|model_dump)\s+sha(?:256)?\s*"
    r"(?:is\s*|was\s*|=|:)?\s*[`'\"]?"
    # "current golden `model_dump` sha is `deadbeef`"
    r"|model_dump[`'\"]?\s+sha(?:256)?\s*(?:is\s*|was\s*|=|:)?\s*[`'\"]?"
    r"|(?:manifest|freeze|golden).{0,60}sha(?:256)?[`'\"]?\s*(?:is|was|=|:)\s*[`'\"]?"
    r")\s*$",
    re.IGNORECASE,
)
# Truncated digest prefix: ``deadbeef…`` / ``deadbeef...`` / ``deadbeef…  path``
_AFTER_DIGEST_LISTING = re.compile(r"^(?:…|\.\.\.)")


def _resolves(repo: Path, token: str) -> bool:
    proc = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "-t", token],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode == 0 and proc.stdout.strip() == "commit"


def _is_content_digest(line: str, start: int, end: int) -> bool:
    """True when this specific token is labelled a content digest, not a commit.

    Exclusion is per-token and prefix-driven (AUDIT-07: name the sampling frame).
    A neighbouring ``digest`` word alone does **not** exempt other tokens on the line.
    """
    before = line[:start]
    after = line[end:]
    if _BEFORE_DIGEST.search(before):
        return True
    # Truncated digest prefix from sha256sum / report tables: token… rest
    if _AFTER_DIGEST_LISTING.match(after):
        return True
    return False


def _strip_html_comments(line: str) -> str:
    """Replace HTML comment spans with spaces (preserve offsets for messaging).

    A citation outside ``<!-- ... -->`` on the same line remains visible to the
    scanner; only the comment body is blanked (VLM6-D-05).
    """
    out: list[str] = []
    i = 0
    n = len(line)
    while i < n:
        open_at = line.find("<!--", i)
        if open_at < 0:
            out.append(line[i:])
            break
        out.append(line[i:open_at])
        close_at = line.find("-->", open_at + 4)
        if close_at < 0:
            # Unclosed comment: blank the rest of the line.
            out.append(" " * (n - open_at))
            break
        # Keep length so column positions stay meaningful; blank the span.
        out.append(" " * (close_at + 3 - open_at))
        i = close_at + 3
    return "".join(out)


def scan_file(repo: Path, path: Path) -> list[str]:
    """Return violation messages for one report file.

    Raises OSError on unreadable paths — callers treat that as a hard failure.
    """
    violations: list[str] = []
    rel = path.relative_to(repo) if path.is_absolute() and repo in path.parents else path
    text = path.read_text(encoding="utf-8")
    in_block_comment = False
    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line
        # Multi-line HTML comments: blank interior lines entirely.
        if in_block_comment:
            if "-->" in line:
                # Close; keep any trailing non-comment text.
                after = line.split("-->", 1)[1]
                in_block_comment = False
                line = after
            else:
                continue
        if "<!--" in line:
            # May open (and possibly close) on this line.
            stripped = _strip_html_comments(line)
            # Detect unclosed open: raw had <!-- and strip blanked through EOL
            # without a closing --> after the last open.
            last_open = line.rfind("<!--")
            last_close = line.rfind("-->")
            if last_open >= 0 and last_close < last_open:
                in_block_comment = True
            line = stripped

        if _IGNORE_MARKER in line:
            continue

        for match in _HEX.finditer(line):
            token = match.group(1)
            if _ALL_DIGITS.match(token):
                continue
            if _is_content_digest(line, match.start(1), match.end(1)):
                continue
            if _resolves(repo, token):
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
    checked = 0
    for path in targets:
        if not path.is_file():
            # VLM6-D-03: missing path is an error, not a silent skip.
            violations.append(
                f"{path}: target is not a readable file — "
                f"refusing to claim SHA citations resolve for an unopened path"
            )
            continue
        try:
            violations.extend(scan_file(repo, path))
        except OSError as exc:
            violations.append(f"{path}: unreadable ({exc}) — refusing to claim resolution")
            continue
        checked += 1

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

    print(f"lane report SHA citations: {checked} file(s) checked, all resolve")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
