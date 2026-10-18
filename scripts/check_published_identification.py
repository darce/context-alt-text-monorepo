#!/usr/bin/env python3
"""Flag leftover uncomputed identification blocks in published reports.

S2R3-08 closed in code: identification P/R must be refused when identity
claims have no per-face box lineage. An earlier audit walked
``faces.identification`` and treated a block as stale only when
``precision is not None``. Every leftover report published
``precision: null`` with ``recall: 0.0`` and a populated per-identity
table, so that scan reported clean.

This guard flags that leftover shape: an identification block that is
not an explicit refusal (``refused is True``) and has ``precision``
null. A numeric precision is a published score. The report JSON does
not embed annotation_mode, box coverage, or lineage, so this scan
**cannot** decide whether that score was honest — it only rejects the
pre-S2R3-08 uncomputed leftover.

Usage (from repo root):

    python3 scripts/check_published_identification.py

Exit 0 if every published identification block is an explicit refusal,
absent, or a numeric score; 1 if any leftover uncomputed block is
found or no report files were scanned; 2 if the git invocation itself
fails.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

SCAN_PREFIXES = ("docs/",)
JSON_SUFFIX = ".json"


def is_report_json(rel: str) -> bool:
    """``*-report.json`` and dated twins like ``*-report-20260714.json``."""
    name = Path(rel).name.lower()
    return name.endswith(JSON_SUFFIX) and "-report" in name


@dataclass(frozen=True)
class IdentificationHit:
    """One leftover uncomputed identification block (null P, not refused)."""

    rel: str
    precision: Any
    recall: Any
    refused: Any
    per_identity_rows: int
    invariant: Any

    @property
    def shape(self) -> str:
        return (
            f"refused={self.refused!r} precision={self.precision!r} "
            f"recall={self.recall!r} per_identity={self.per_identity_rows}"
        )


def repo_root() -> Path:
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(out.stdout.strip())


def tracked_report_paths(root: Path) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z", "--", "docs"],
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
        if not is_report_json(rel):
            continue
        paths.append(rel)
    return paths


def identification_block(payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
    faces = payload.get("faces")
    if not isinstance(faces, Mapping):
        return None
    ident = faces.get("identification")
    if not isinstance(ident, Mapping):
        return None
    return ident


def is_refused_identification(ident: Mapping[str, Any]) -> bool:
    """True only for an explicit refusal. Missing/null/false are not."""
    return ident.get("refused") is True


def is_leftover_uncomputed_identification(ident: Mapping[str, Any]) -> bool:
    """True for the pre-S2R3-08 leftover: not refused, precision is null.

    A numeric precision is a score. Honesty of that score (annotation
    mode, box coverage, lineage) cannot be judged from the report
    artifact alone — those fields live on the manifest, which published
    reports do not embed.
    """
    if is_refused_identification(ident):
        return False
    return ident.get("precision") is None


def per_identity_rows(ident: Mapping[str, Any]) -> int:
    table = ident.get("per_identity")
    if isinstance(table, Mapping):
        return len(table)
    return 0


def scored_identification_hit(rel: str, ident: Mapping[str, Any]) -> IdentificationHit:
    return IdentificationHit(
        rel=rel,
        precision=ident.get("precision"),
        recall=ident.get("recall"),
        refused=ident.get("refused"),
        per_identity_rows=per_identity_rows(ident),
        invariant=ident.get("invariant"),
    )


def scan_payload(rel: str, payload: Any) -> IdentificationHit | None:
    if not isinstance(payload, Mapping):
        return None
    ident = identification_block(payload)
    if ident is None:
        return None
    if is_refused_identification(ident):
        return None
    if not is_leftover_uncomputed_identification(ident):
        return None
    return scored_identification_hit(rel, ident)


def scan_report_file(root: Path, rel: str) -> IdentificationHit | None:
    path = root / rel
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return scan_payload(rel, payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)

    try:
        root = repo_root()
        paths = tracked_report_paths(root)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(
            f"check_published_identification: git invocation failed: {exc}",
            file=sys.stderr,
        )
        return 2

    if not paths:
        print(
            "check_published_identification: no tracked docs/*-report*.json "
            "files scanned",
            file=sys.stderr,
        )
        return 1

    hits: list[IdentificationHit] = []
    examined = 0
    for rel in paths:
        path = root / rel
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, Mapping):
            continue
        if identification_block(payload) is None and payload.get("kind") != "report":
            continue
        if identification_block(payload) is None:
            continue
        examined += 1
        hit = scan_payload(rel, payload)
        if hit is not None:
            hits.append(hit)

    if hits:
        print(
            f"check_published_identification: {len(hits)} leftover "
            f"uncomputed identification block(s) (null precision, not "
            f"refused; examined {examined} across {len(paths)} files). "
            f"This scan does not judge honesty of a numeric score — "
            f"the report does not embed annotation_mode / boxes / lineage.",
            file=sys.stderr,
        )
        for hit in hits:
            print(f"  SCORED  {hit.rel}  {hit.shape}", file=sys.stderr)
        return 1

    print(
        f"check_published_identification: ok — {examined} identification "
        f"block(s) refused, absent, or numeric "
        f"({len(paths)} report files scanned; numeric scores are not "
        f"judged honest from the report alone)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
