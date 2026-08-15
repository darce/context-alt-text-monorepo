#!/usr/bin/env python3
"""Verify every published eval ``head_sha`` resolves in this repository.

Committed run-records and reports stamp ``provenance.head_sha``. A harvest or
rebase that rewrites commits can leave those stamps pointing at a SHA that
``git rev-parse --verify <sha>^{commit}`` cannot resolve here. This guard
walks tracked eval artifacts under ``docs/`` and ``benchmarks/`` and fails
if any published ``head_sha`` is missing.

Usage (from repo root):

    python3 scripts/check_published_head_sha.py

Exit 0 if every stamp resolves; 1 if any stamp is missing; 2 if the git
invocation itself fails.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
MD_HEAD_SHA_RE = re.compile(
    r"head_sha:\s*`?([0-9a-f]{40})`?",
    re.IGNORECASE,
)
JSON_HEAD_SHA_RE = re.compile(r'"head_sha"\s*:\s*"([0-9a-f]{40})"')

SCAN_PREFIXES = ("docs/", "benchmarks/")
SCAN_SUFFIXES = (".json", ".md")


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


def extract_head_shas(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    found: list[str] = []
    if path.suffix == ".json":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            prov = payload.get("provenance")
            if isinstance(prov, dict):
                sha = prov.get("head_sha")
                if isinstance(sha, str) and SHA_RE.fullmatch(sha):
                    found.append(sha)
        # Belt: catch any other published head_sha string in the file.
        for match in JSON_HEAD_SHA_RE.finditer(text):
            if match.group(1) not in found:
                found.append(match.group(1))
    else:
        for match in MD_HEAD_SHA_RE.finditer(text):
            if match.group(1) not in found:
                found.append(match.group(1))
    return found


def resolve_commit(root: Path, sha: str) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", f"{sha}^{{commit}}"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def main() -> int:
    try:
        root = repo_root()
        paths = tracked_artifact_paths(root)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"check_published_head_sha: git invocation failed: {exc}", file=sys.stderr)
        return 2

    checked = 0
    missing: list[tuple[str, str]] = []
    for rel in paths:
        shas = extract_head_shas(root / rel)
        for sha in shas:
            checked += 1
            if not resolve_commit(root, sha):
                missing.append((rel, sha))

    if missing:
        print(
            f"check_published_head_sha: {len(missing)} unpublished head_sha "
            f"stamp(s) (checked {checked} across {len(paths)} files)",
            file=sys.stderr,
        )
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
