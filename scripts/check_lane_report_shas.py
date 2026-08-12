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
(VLM6-D-03) — CI must not print resolution claims for files that were never
opened.

Narrow content-digest exclusions (justified, per-token — not whole-line vetoes):

* ``sha256:``-prefixed tokens (content digests, not git objects)
* Tokens labelled ``manifest_sha256`` / ``msha=`` (manifest content digests)
* Tokens labelled as fetch/golden/score-time/model_dump sha prefixes
* Tokens that open a ``sha256sum``-style digest listing (``deadbeef…  path``)
* Full-width / ASCII ellipsis truncated digest prefixes **only** when a digest
  label (``_BEFORE_DIGEST``) or sha256sum-listing context also matches (S5-03).
  Bare ``commit `abc1234…``` is still required to resolve.

HTML comments are **not** a skip channel (S5-01). Unresolvable hex inside
``<!-- ... -->`` fails the same way as visible prose. Foreign SHAs that
genuinely must be shown belong in **visible** prose with ``sha-guard:ignore``
scoped to the nearest token (S5-07). An unclosed ``<!--`` is a hard violation
(S5-02) — the guard refuses to claim resolution for a partially scanned file.

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
# sha256sum-style listing remainder: ellipsis, whitespace, path-like token.
_SHA256SUM_LISTING_AFTER = re.compile(r"^(?:…|\.\.\.)\s+\S")


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
    Bare commit + ellipsis is **not** a digest (S5-03) — ellipsis exclusion requires
    a ``_BEFORE_DIGEST`` label or a sha256sum-listing path remainder.
    """
    before = line[:start]
    after = line[end:]
    if _BEFORE_DIGEST.search(before):
        return True
    # Truncated digest prefix only with digest label or sha256sum ``hex…  path``.
    if _AFTER_DIGEST_LISTING.match(after):
        if _BEFORE_DIGEST.search(before):
            return True
        if _SHA256SUM_LISTING_AFTER.match(after):
            return True
    return False


def _ignored_token_spans(line: str) -> set[tuple[int, int]]:
    """Return hex-token spans covered by a nearest-token ``sha-guard:ignore`` (S5-07)."""
    markers = [m.start() for m in re.finditer(re.escape(_IGNORE_MARKER), line)]
    if not markers:
        return set()
    tokens = [(m.start(1), m.end(1)) for m in _HEX.finditer(line)]
    if not tokens:
        return set()
    ignored: set[tuple[int, int]] = set()
    marker_len = len(_IGNORE_MARKER)
    for mp in markers:
        best: tuple[int, int] | None = None
        best_dist: int | None = None
        for ts, te in tokens:
            if te <= mp:
                dist = mp - te
            elif ts >= mp + marker_len:
                dist = ts - (mp + marker_len)
            else:
                dist = 0
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best = (ts, te)
        if best is not None:
            ignored.add(best)
    return ignored


def _comment_state_after_line(line: str, in_block_comment: bool) -> bool:
    """Advance HTML-comment open/close state across one line (S5-02)."""
    i = 0
    n = len(line)
    in_comment = in_block_comment
    while i < n:
        if in_comment:
            close_at = line.find("-->", i)
            if close_at < 0:
                return True
            i = close_at + 3
            in_comment = False
        else:
            open_at = line.find("<!--", i)
            if open_at < 0:
                return False
            i = open_at + 4
            in_comment = True
    return in_comment


def scan_file(repo: Path, path: Path) -> tuple[list[str], int]:
    """Return (violation messages, citation tokens checked) for one report file.

    Raises OSError on unreadable paths — callers treat that as a hard failure.
    HTML comments are scanned (S5-01); an unclosed comment is itself a violation
    (S5-02).
    """
    violations: list[str] = []
    tokens_checked = 0
    rel = path.relative_to(repo) if path.is_absolute() and repo in path.parents else path
    text = path.read_text(encoding="utf-8")
    in_block_comment = False
    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        in_block_comment = _comment_state_after_line(raw_line, in_block_comment)

        ignored = _ignored_token_spans(raw_line)
        for match in _HEX.finditer(raw_line):
            token = match.group(1)
            start, end = match.start(1), match.end(1)
            if _ALL_DIGITS.match(token):
                continue
            if (start, end) in ignored:
                continue
            if _is_content_digest(raw_line, start, end):
                continue
            tokens_checked += 1
            if _resolves(repo, token):
                continue
            violations.append(
                f"{rel}:{lineno}: cited commit `{token}` does not resolve — "
                f"resolve it against `git log` in this worktree, or drop the citation "
                f"(or add `{_IGNORE_MARKER}` on the nearest token if it is deliberately foreign)"
            )

    if in_block_comment:
        violations.append(
            f"{rel}: unclosed HTML comment — refusing to claim SHA citations resolve "
            f"for a partially scanned file"
        )
    return violations, tokens_checked


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

    if args.scan_staged and not targets:
        # S5-04 / AUDIT-07: never claim resolution over an empty sample.
        print("0 staged lane reports; nothing to check")
        return 0

    violations: list[str] = []
    checked = 0
    tokens_checked = 0
    for path in targets:
        if not path.is_file():
            # VLM6-D-03: missing path is an error, not a silent skip.
            violations.append(
                f"{path}: target is not a readable file — "
                f"refusing to claim SHA citations resolve for an unopened path"
            )
            continue
        try:
            file_violations, file_tokens = scan_file(repo, path)
        except OSError as exc:
            violations.append(f"{path}: unreadable ({exc}) — refusing to claim resolution")
            continue
        violations.extend(file_violations)
        tokens_checked += file_tokens
        checked += 1

    if violations:
        print("Lane reports cite commits that do not exist in this repository:", file=sys.stderr)
        for v in violations:
            print(f"  - {v}", file=sys.stderr)
        print(
            "\nA lane's sandbox-clone SHA is not the SHA the work landed under. "
            "Use `git log --diff-filter=A -- <report>` to find the real one. "
            "Do not hide unresolvable tokens in HTML comments — quote them in visible "
            f"prose with `{_IGNORE_MARKER}` on the nearest token if deliberately foreign.",
            file=sys.stderr,
        )
        return 1

    # S5-05: never claim "all resolve" when zero tokens were examined.
    if tokens_checked == 0:
        print(
            f"lane report SHA citations: {checked} file(s), 0 citations found (none to resolve)"
        )
    else:
        print(
            f"lane report SHA citations: {checked} file(s), {tokens_checked} citation(s) resolved"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
