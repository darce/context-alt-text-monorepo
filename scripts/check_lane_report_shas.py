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
require a digest **shape**, not just an adjacent label (RV4-02):

* ``sha256:``-prefixed tokens (content digests, not git objects)
* Tokens labelled as digests **and** shaped as digests: ≥16 hex, or ellipsis /
  ``sha256sum``-style path remainder
* Tokens that open a ``sha256sum``-style digest listing (``deadbeef…  path``)
* Full-width / ASCII ellipsis truncated digest prefixes **only** when a digest
  label (``_BEFORE_DIGEST``) or sha256sum-listing context also matches (S5-03).
  Bare ``commit `abc1234…``` is still required to resolve.
* A bare 7–12 hex token after ``golden sha is`` / ``fetch sha`` / ``manifest
  sha`` / ``freeze … sha`` is a **commit citation** and must resolve (RV4-02).

Unicode evasion (RV4-03 / VLM6-R2-G-03): each line is NFKC-normalised and Cf
(format) characters (soft hyphen, ZWSP, …) are stripped before scanning.
Markdown emphasis markers interior to hex runs (``dead*beef*1234``) are
collapsed so the raw tokenizer sees the rendered token (RF-11). Homoglyph /
confusable hex-lookalike runs are examined on **every** line unconditionally —
commit vocabulary may annotate context but never gates whether a lookalike SHA
is reported. Both the ASCII and homoglyph paths honour nearest-token
``sha-guard:ignore`` (RF-07).

HTML comments are **not** a skip channel (S5-01). Unresolvable hex inside
``<!-- ... -->`` fails the same way as visible prose. Foreign SHAs that
genuinely must be shown belong in **visible** prose with ``sha-guard:ignore``
scoped to the nearest token (S5-07), or — for fenced verbatim output — an
``sha-guard:ignore-next-block`` directive on the line **immediately before**
the fence opener (blank lines allowed; intervening non-blank content resets
pending suppression — VLM6-R2-G-05 / HARM-08). An unclosed ``<!--`` is a hard
violation (S5-02). An unclosed fenced block is likewise a hard violation
(RF-08) — a suppressor that never ends must not silently pass.

Default walk prunes vendored / cache directory names (``.venv``,
``node_modules``, …) before enumerating markdown (RF-09). A default walk that
finds zero lane reports exits non-zero rather than claiming a vacuous pass
(RF-10); ``--scan-staged`` with an empty index still reports "nothing to check"
and exits 0 (nothing staged is a legitimate empty sample).

Usage:
    scripts/check_lane_report_shas.py [path ...]   # default: **/.s2a/**/*.md
    scripts/check_lane_report_shas.py --scan-staged
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

_IGNORE_MARKER = "sha-guard:ignore"
_IGNORE_NEXT_BLOCK = "sha-guard:ignore-next-block"
# Case-insensitive: uppercase / mixed-case display forms must not escape (VLM6-D-04).
_HEX = re.compile(r"\b([0-9a-fA-F]{7,40})\b")
# All-digit runs are dates (20260811), not abbreviated objects.
_ALL_DIGITS = re.compile(r"^\d+$")

# Explicit sha256: prefix — always a content digest regardless of token length.
_SHA256_PREFIX = re.compile(r"sha256\s*:\s*[`'\"]?\s*$", re.IGNORECASE)

# Per-token content-digest label prefixes. Whole-line keyword vetoes are rejected
# (VLM6-D-05): a line that mentions "digest" must still flag an unresolvable
# commit citation sitting next to that word. A label match alone is NOT enough
# (RV4-02) — see ``_is_content_digest`` shape checks.
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

# Minimum hex length treated as a content-digest shape when a digest label is present.
_DIGEST_MIN_HEX_LEN = 16

# Commit / SHA vocabulary — optional annotation context only (VLM6-R2-G-03).
# Homoglyph detection is unconditional; this pattern must never gate reporting.
_COMMIT_VOCAB = re.compile(
    r"(?i)\b(?:"
    r"commit|sha(?:256)?|sandbox|landing|history-stripped|"
    r"rev-parse|cat-file|git\s+log|landed\s+at|base\s+was|"
    r"golden|manifest|freeze|fetch|model_dump"
    r")\b"
)

# Cyrillic / Greek confusables that render like ASCII hex digits.
# Fullwidth forms are handled by NFKC; Cf (ZWSP, soft hyphen) are stripped.
_CONFUSABLE_TO_ASCII = str.maketrans(
    {
        "\u0430": "a",  # Cyrillic а
        "\u0435": "e",  # Cyrillic е
        "\u043e": "o",  # Cyrillic о
        "\u0440": "p",  # Cyrillic р
        "\u0441": "c",  # Cyrillic с
        "\u0445": "x",  # Cyrillic х
        "\u0410": "A",  # Cyrillic А
        "\u0415": "E",  # Cyrillic Е
        "\u041e": "O",  # Cyrillic О
        "\u0420": "P",  # Cyrillic Р
        "\u0421": "C",  # Cyrillic С
        "\u0425": "X",  # Cyrillic Х
        "\u03bf": "o",  # Greek ο
        "\u039f": "O",  # Greek Ο
        "\u03b1": "a",  # Greek α (weak; still hex-lookalike in mixed runs)
    }
)

_IGNORE_NEXT_BLOCK_RE = re.compile(
    rf"(?:<!--\s*)?{re.escape(_IGNORE_NEXT_BLOCK)}(?:\s*-->)?",
    re.IGNORECASE,
)

# Fence opener/closer (CommonMark-style ``` or ~~~).
_FENCE_RE = re.compile(r"^\s*(```|~~~)")

# Directory basenames the default walk must not descend into (RF-09).
_PRUNE_DIR_NAMES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "dist",
        "build",
        "vendor",
        "site-packages",
        ".eggs",
        "htmlcov",
    }
)

# Hex run with optional interior markdown emphasis (``*`` / ``~``). Underscore is
# intentionally excluded — it appears in identifiers like ``manifest_sha256``.
_MD_EMPHASIS_HEX_RUN = re.compile(
    r"(?<![0-9a-fA-F])(?:[0-9a-fA-F][*~]*){6,}[0-9a-fA-F](?![0-9a-fA-F])",
    re.IGNORECASE,
)


def _collapse_md_emphasis_in_hex_runs(line: str) -> str:
    """Collapse ``*`` / ``~`` markers that sit inside otherwise-hex runs (RF-11).

    ``dead*beef*1234`` renders as ``deadbeef1234``; the tokenizer must see the
    rendered form. Runs without emphasis markers are left unchanged. This lives
    in the shared normaliser so every detection path (ASCII hex, ignore spans,
    homoglyph folding) observes the same token stream.
    """

    def _repl(match: re.Match[str]) -> str:
        raw = match.group(0)
        if "*" not in raw and "~" not in raw:
            return raw
        collapsed = re.sub(r"[*~]+", "", raw)
        if 7 <= len(collapsed) <= 40 and re.fullmatch(r"[0-9a-fA-F]+", collapsed, re.I):
            return collapsed
        return raw

    return _MD_EMPHASIS_HEX_RUN.sub(_repl, line)


def _normalize_scan_line(line: str) -> str:
    """NFKC-normalise, strip Cf chars, collapse interior MD emphasis in hex runs.

    RV4-03: Markdown viewers render ``c9f7\\u00adc6e`` as ``c9f7c6e``; the guard must
    see the same token the reader sees. RF-11: the same rule for ``dead*beef*1234``.
    """
    nfkc = unicodedata.normalize("NFKC", line)
    no_cf = "".join(ch for ch in nfkc if unicodedata.category(ch) != "Cf")
    return _collapse_md_emphasis_in_hex_runs(no_cf)


def _homoglyph_sha_spans(line: str) -> list[tuple[int, int, str]]:
    """Return (start, end, original) for 7–40 char confusable hex-lookalike runs.

    Pure ASCII hex is handled by ``_HEX``; these are the residual lookalike cases
    that would otherwise be invisible to the scanner (RV4-03). Span indices align
    with *line* (confusable fold is 1:1) so ignore-span membership is shared
    with the ASCII path (RF-07).
    """
    if not any(ord(ch) > 127 for ch in line):
        return []
    folded = line.translate(_CONFUSABLE_TO_ASCII)
    runs: list[tuple[int, int, str]] = []
    for match in _HEX.finditer(folded):
        start, end = match.start(1), match.end(1)
        original = line[start:end]
        token = match.group(1)
        # Residual non-ASCII in the original span ⇒ confusable, not real hex.
        if original != token and any(ord(ch) > 127 for ch in original):
            runs.append((start, end, original))
    return runs


def _homoglyph_sha_runs(line: str) -> list[str]:
    """Return original lookalike run strings (compat wrapper around spans)."""
    return [original for _s, _e, original in _homoglyph_sha_spans(line)]


def _hex_like_token_spans(line: str) -> list[tuple[int, int]]:
    """ASCII hex spans plus confusable-folded lookalike spans on the same line.

    Single source of candidate spans for ignore-nearest-token matching so the
    ASCII and homoglyph detection paths cannot drift (RF-07 / RF-11 class).
    """
    spans: list[tuple[int, int]] = [(m.start(1), m.end(1)) for m in _HEX.finditer(line)]
    seen: set[tuple[int, int]] = set(spans)
    for start, end, _original in _homoglyph_sha_spans(line):
        if (start, end) not in seen:
            spans.append((start, end))
            seen.add((start, end))
    return spans


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

    Exclusion is per-token and requires digest **shape** (RV4-02 / AUDIT-07):

    * ``sha256:`` prefix → always digest
    * digest label + (≥16 hex OR ellipsis after the token) → digest
    * sha256sum-style ``hex…  path`` remainder → digest

    A neighbouring ``digest`` / ``golden sha is`` label alone does **not** exempt
    a bare 7–12 hex token. Bare commit + ellipsis is **not** a digest (S5-03).
    """
    before = line[:start]
    after = line[end:]
    token = line[start:end]

    # Explicit sha256: prefix is always a content digest (any length).
    if _SHA256_PREFIX.search(before):
        return True

    has_label = bool(_BEFORE_DIGEST.search(before))
    has_ellipsis = bool(_AFTER_DIGEST_LISTING.match(after))
    has_sha256sum = bool(_SHA256SUM_LISTING_AFTER.match(after))

    # Labelled digest with real digest shape (≥16 hex or truncated with ellipsis).
    if has_label and (len(token) >= _DIGEST_MIN_HEX_LEN or has_ellipsis):
        return True

    # sha256sum-style listing remainder (no label required).
    if has_sha256sum:
        return True

    return False


def _ignored_token_spans(line: str) -> set[tuple[int, int]]:
    """Return hex-like spans covered by a nearest-token ``sha-guard:ignore`` (S5-07).

    Spans include both pure ASCII hex and confusable-folded lookalikes so the
    remediation message printed for homoglyph violations actually works (RF-07).
    """
    markers = [m.start() for m in re.finditer(re.escape(_IGNORE_MARKER), line)]
    # Do not treat ignore-next-block as a nearest-token ignore marker.
    markers = [
        mp
        for mp in markers
        if not line[mp : mp + len(_IGNORE_NEXT_BLOCK)].lower().startswith(
            _IGNORE_NEXT_BLOCK
        )
    ]
    if not markers:
        return set()
    tokens = _hex_like_token_spans(line)
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
    (S5-02). Lines are NFKC-normalised and Cf-stripped before token extraction
    (RV4-03). Fenced blocks are skipped as a whole only when
    ``sha-guard:ignore-next-block`` appears on the line immediately before the
    fence opener (blank lines allowed; VLM6-R2-G-05 / HARM-08). Homoglyph
    lookalikes are examined on every line (VLM6-R2-G-03).
    """
    violations: list[str] = []
    tokens_checked = 0
    rel = path.relative_to(repo) if path.is_absolute() and repo in path.parents else path
    text = path.read_text(encoding="utf-8")
    in_block_comment = False
    in_fence = False
    ignore_this_fence = False
    ignore_next_fence = False

    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        # Fence / block-ignore bookkeeping uses the raw line (delimiter detection).
        if _FENCE_RE.match(raw_line):
            if in_fence:
                in_fence = False
                ignore_this_fence = False
            else:
                in_fence = True
                ignore_this_fence = ignore_next_fence
                ignore_next_fence = False
            # Fence delimiters themselves are never citations.
            in_block_comment = _comment_state_after_line(raw_line, in_block_comment)
            continue

        if not in_fence:
            if _IGNORE_NEXT_BLOCK_RE.search(raw_line):
                # Pending suppression applies only to the next fence; adjacency
                # is "immediately before" with blank lines allowed (VLM6-R2-G-05).
                ignore_next_fence = True
            elif ignore_next_fence and raw_line.strip():
                # Intervening non-blank content severs adjacency.
                ignore_next_fence = False

        if ignore_this_fence:
            # Verbatim capture block marked foreign — do not resolve interior tokens.
            in_block_comment = _comment_state_after_line(raw_line, in_block_comment)
            continue

        line = _normalize_scan_line(raw_line)
        in_block_comment = _comment_state_after_line(line, in_block_comment)

        ignored = _ignored_token_spans(line)
        for match in _HEX.finditer(line):
            token = match.group(1)
            start, end = match.start(1), match.end(1)
            if _ALL_DIGITS.match(token):
                continue
            if (start, end) in ignored:
                continue
            if _is_content_digest(line, start, end):
                continue
            tokens_checked += 1
            if _resolves(repo, token):
                continue
            violations.append(
                f"{rel}:{lineno}: cited commit `{token}` does not resolve — "
                f"resolve it against `git log` in this worktree, or drop the citation "
                f"(or add `{_IGNORE_MARKER}` on the nearest token if it is deliberately foreign)"
            )

        # Homoglyph SHAs: examine every line unconditionally (VLM6-R2-G-03).
        # Commit vocabulary annotates context only — never gates detection.
        # Nearest-token ignore applies here too (RF-07) — same remediation as ASCII.
        for start, end, run in _homoglyph_sha_spans(line):
            if (start, end) in ignored:
                continue
            vocab_note = (
                " adjacent to commit vocabulary"
                if _COMMIT_VOCAB.search(line)
                else ""
            )
            violations.append(
                f"{rel}:{lineno}: homoglyph / non-ASCII hex-lookalike `{run}`"
                f"{vocab_note} — refuse to treat lookalike SHAs as invisible; "
                f"use ASCII hex or mark deliberately foreign tokens with "
                f"`{_IGNORE_MARKER}`"
            )

    if in_block_comment:
        violations.append(
            f"{rel}: unclosed HTML comment — refusing to claim SHA citations resolve "
            f"for a partially scanned file"
        )
    # RF-08: unclosed fence (with or without ignore-next-block) must not silently
    # suppress the rest of the file and exit 0. Mirror the unclosed-comment rule.
    if in_fence:
        violations.append(
            f"{rel}: unclosed fenced block — refusing to claim SHA citations resolve "
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


def _is_lane_report_relpath(name: str) -> bool:
    """True when *name* is a markdown lane report under any-depth ``.s2a/`` (RV4-04).

    Shared by the default walk and ``--scan-staged`` so the two cannot drift (rg-006).
    """
    # Normalise to forward slashes; staged names and globs both use POSIX form.
    normalised = name.replace("\\", "/")
    return "/.s2a/" in f"/{normalised}" and normalised.endswith(".md")


def _default_report_paths(repo: Path) -> list[Path]:
    """Walk the tree; keep only paths accepted by ``_is_lane_report_relpath``.

    Shared implementation with ``--scan-staged`` (rg-006 / VLM6-R2-G-04): a
    hand-maintained glob list (``.s2a/**/*.md`` + ``*/.s2a/**/*.md``) cannot
    reach arbitrary depth above ``*`` and drifts from the staged predicate.

    Prunes known vendored / cache directory basenames during traversal (RF-09)
    so ``.venv`` / ``node_modules`` / etc. are never scanned as lane reports.
    """
    seen: set[Path] = set()
    out: list[Path] = []
    repo = repo.resolve()
    for dirpath, dirnames, filenames in os.walk(repo, topdown=True):
        # In-place prune: prevent descent into vendored / cache trees.
        dirnames[:] = sorted(
            d
            for d in dirnames
            if d not in _PRUNE_DIR_NAMES and not d.endswith(".egg-info")
        )
        base = Path(dirpath)
        for name in sorted(filenames):
            if not name.endswith(".md"):
                continue
            path = base / name
            try:
                rel = path.relative_to(repo).as_posix()
            except ValueError:
                continue
            if not _is_lane_report_relpath(rel):
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            out.append(path)
    out.sort()
    return out


def _staged_reports(repo: Path) -> list[Path]:
    out = subprocess.run(
        ["git", "-C", str(repo), "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [
        repo / name
        for name in out.stdout.split()
        if _is_lane_report_relpath(name)
    ]


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
        targets = _default_report_paths(repo)

    if args.scan_staged and not targets:
        # S5-04 / AUDIT-07: never claim resolution over an empty sample.
        print("0 staged lane reports; nothing to check")
        return 0

    if not args.scan_staged and not args.paths and not targets:
        # RF-10: default walk with zero targets is a vacuous pass if exit 0 —
        # unlike an empty staged index (legitimate), finding no lane reports at
        # all means the walk/predicate regressed or CI invoked us in the wrong
        # tree. Fail closed with an explicit honesty message.
        print(
            "0 lane reports found by default walk; nothing to check — "
            "refusing to claim success over an empty sample",
            file=sys.stderr,
        )
        return 1

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
            f"prose with `{_IGNORE_MARKER}` on the nearest token if deliberately foreign, "
            f"or place `{_IGNORE_NEXT_BLOCK}` immediately before a fenced verbatim block.",
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
