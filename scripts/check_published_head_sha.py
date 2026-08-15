#!/usr/bin/env python3
"""Verify every published eval ``head_sha`` resolves in this repository.

Committed run-records and reports stamp ``provenance.head_sha``. A harvest or
rebase that rewrites commits can leave those stamps pointing at a SHA that
``git rev-parse --verify <sha>^{commit}`` cannot resolve here. This guard
walks tracked eval artifacts under ``docs/`` and ``benchmarks/`` and fails
if any published stamp is missing or unreadable.

A present stamp that is not a resolvable commit (``unknown``, truncated,
uppercase that does not resolve, blank, non-string JSON, or other
garbage) is invalid — not absent. A present ``head_sha`` / ``git_sha``
/ ``commit`` key is a stamp regardless of type or emptiness.
Zero matching artifact files is a failed scan, not a clean pass.

Usage (from repo root):

    python3 scripts/check_published_head_sha.py

A shallow clone cannot see the commits it omitted. This guard then
refuses to classify those stamps MISSING: it exits 1 with
``cannot verify: shallow clone`` and tells the operator to
``git fetch --unshallow``. Never report MISSING for a commit the
object database merely cannot see.

Exit 0 if every stamp resolves; 1 if any stamp is missing/unreadable,
the clone is shallow, or no artifact files were scanned; 2 if the git
invocation itself fails.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

SHA40_RE = re.compile(r"^[0-9a-fA-F]{40}$")
# JSON commit / labeled `commit:` values: hex or the report.py sentinel.
SHA_OR_UNKNOWN_RE = re.compile(r"^(?:unknown|[0-9a-fA-F]{4,40})$", re.IGNORECASE)

JSON_STAMP_RE = re.compile(r'"(head_sha|git_sha|commit)"\s*:\s*"([^"]*)"')
MD_HEAD_OR_GIT_RE = re.compile(
    r"(?m)^(?:[-*]\s*)?(head_sha|git_sha):\s*`?([^\s`]+)`?"
)
MD_COMMIT_LABELED_RE = re.compile(
    r"(?m)^(?:[-*]\s*)?commit:\s*`?(unknown|[0-9a-fA-F]{4,40})`?",
    re.IGNORECASE,
)
MD_COMMIT_LINE_RE = re.compile(
    r"(?m)^(?:[-*]\s*)?commit\s+`?(unknown|[0-9a-fA-F]{7,40})`?\s*$",
    re.IGNORECASE,
)

SCAN_PREFIXES = ("docs/", "benchmarks/")
SCAN_SUFFIXES = (".json", ".md", ".html", ".htm")
JSON_LIKE_SUFFIXES = (".json",)
OPEN_KEYS = ("head_sha", "git_sha")
COMMIT_KEY = "commit"


@dataclass(frozen=True)
class PublishedStamp:
    """One published commit stamp. ``raw`` is the literal value in the file."""

    raw: str
    key: str

    @property
    def well_formed(self) -> bool:
        return bool(SHA40_RE.fullmatch(self.raw))

    @property
    def normalized(self) -> str:
        return self.raw.lower() if self.well_formed else self.raw


def repo_root() -> Path:
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(out.stdout.strip())


def tracked_artifact_paths(root: Path) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z", "--", "docs", "benchmarks"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    paths: list[str] = []
    for rel in out.stdout.split("\0"):
        if not rel:
            continue
        if not rel.startswith(SCAN_PREFIXES):
            continue
        if not rel.endswith(SCAN_SUFFIXES):
            continue
        paths.append(rel)
    return paths


def _is_commit_key_value(value: str) -> bool:
    return bool(SHA_OR_UNKNOWN_RE.fullmatch(value))


def json_stamp_raw(value: object) -> str:
    """Literal display form of a present JSON stamp, including non-strings."""
    if isinstance(value, str):
        return value
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return json.dumps(value)


def _record_stamp(
    found: list[PublishedStamp], seen: set[tuple[str, str]], key: str, raw: str
) -> None:
    # Present keys are stamps even when blank or non-conforming. Do not
    # collapse those into absence (S2R5-20). Strip padding so a well-formed
    # SHA still resolves; a blank stays blank and is UNREADABLE.
    value = raw.strip()
    marker = (key, value)
    if marker in seen:
        return
    seen.add(marker)
    found.append(PublishedStamp(raw=value, key=key))


def _walk_json_stamps(obj: object, found: list[PublishedStamp], seen: set[tuple[str, str]]) -> None:
    if isinstance(obj, dict):
        for key, val in obj.items():
            if key in OPEN_KEYS or key == COMMIT_KEY:
                _record_stamp(found, seen, key, json_stamp_raw(val))
            else:
                _walk_json_stamps(val, found, seen)
    elif isinstance(obj, list):
        for item in obj:
            _walk_json_stamps(item, found, seen)


def _extract_text_stamps(text: str, found: list[PublishedStamp], seen: set[tuple[str, str]]) -> None:
    for match in MD_HEAD_OR_GIT_RE.finditer(text):
        _record_stamp(found, seen, match.group(1), match.group(2))
    for match in MD_COMMIT_LABELED_RE.finditer(text):
        _record_stamp(found, seen, COMMIT_KEY, match.group(1))
    for match in MD_COMMIT_LINE_RE.finditer(text):
        _record_stamp(found, seen, COMMIT_KEY, match.group(1))


def extract_stamps(path: Path) -> list[PublishedStamp]:
    text = path.read_text(encoding="utf-8")
    found: list[PublishedStamp] = []
    seen: set[tuple[str, str]] = set()
    suffix = path.suffix.lower()
    if suffix in JSON_LIKE_SUFFIXES:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = None
        if payload is not None:
            _walk_json_stamps(payload, found, seen)
        for match in JSON_STAMP_RE.finditer(text):
            _record_stamp(found, seen, match.group(1), match.group(2))
    else:
        # Markdown/HTML labeled fields. Do not JSON-scan .md: schema prose
        # like `"git_sha": "optional"` is not a published stamp.
        _extract_text_stamps(text, found, seen)
        if suffix in {".html", ".htm"}:
            for match in JSON_STAMP_RE.finditer(text):
                _record_stamp(found, seen, match.group(1), match.group(2))
    return found


def extract_head_shas(path: Path) -> list[str]:
    """Well-formed SHA strings only (legacy helper). Prefer ``extract_stamps``."""
    return [stamp.normalized for stamp in extract_stamps(path) if stamp.well_formed]


def resolve_commit(root: Path, sha: str) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", f"{sha}^{{commit}}"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def is_shallow_repository(root: Path) -> bool:
    """True when ``git rev-parse --is-shallow-repository`` reports true."""
    result = subprocess.run(
        ["git", "rev-parse", "--is-shallow-repository"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode,
            ["git", "rev-parse", "--is-shallow-repository"],
            output=result.stdout,
            stderr=result.stderr,
        )
    return result.stdout.strip() == "true"


def main() -> int:
    try:
        root = repo_root()
        paths = tracked_artifact_paths(root)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"check_published_head_sha: git invocation failed: {exc}", file=sys.stderr)
        return 2

    if not paths:
        print(
            "check_published_head_sha: no tracked docs/benchmarks artifact "
            "files scanned",
            file=sys.stderr,
        )
        return 1

    try:
        shallow = is_shallow_repository(root)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"check_published_head_sha: git invocation failed: {exc}", file=sys.stderr)
        return 2
    if shallow:
        print(
            "check_published_head_sha: cannot verify: shallow clone; "
            "run git fetch --unshallow (stamps are not reported MISSING "
            "when this repository cannot see them)",
            file=sys.stderr,
        )
        return 1

    checked = 0
    missing: list[tuple[str, str]] = []
    unreadable: list[tuple[str, str, str]] = []
    for rel in paths:
        for stamp in extract_stamps(root / rel):
            checked += 1
            if not stamp.well_formed:
                unreadable.append((rel, stamp.raw, stamp.key))
                continue
            if not resolve_commit(root, stamp.normalized):
                missing.append((rel, stamp.normalized))

    if missing or unreadable:
        print(
            f"check_published_head_sha: {len(missing) + len(unreadable)} "
            f"unpublished or unreadable head_sha stamp(s) "
            f"(checked {checked} across {len(paths)} files)",
            file=sys.stderr,
        )
        for rel, raw, key in unreadable:
            shown = raw if raw else '""'
            print(f"  UNREADABLE  {shown}  {rel}  ({key})", file=sys.stderr)
        for rel, sha in missing:
            print(f"  MISSING  {sha}  {rel}", file=sys.stderr)
        return 1

    print(
        f"check_published_head_sha: ok — {checked} head_sha stamp(s) "
        f"resolve in this repo ({len(paths)} files scanned)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
