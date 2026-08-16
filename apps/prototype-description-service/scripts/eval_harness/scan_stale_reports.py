#!/usr/bin/env python3
"""Flag scored identification blocks still published after S2R3-08.

S2R3-08 refuses identification when identity claims carry no per-face box
lineage. An earlier stale-artifact scan treated a block as leftover only
when ``precision`` was numeric. Every remaining leftover published
``precision: null`` with ``recall: 0.0`` and a populated per-identity
table, so that scan reported clean.

This scanner flags **any scored identification block**, however its
fields happen to be populated. A block that matches neither the refused
shape nor the scored shape is reported, never silently passed (rg-008).

Same ``score_manifest_sha256`` with mixed refused/scored verdicts is a
provenance contradiction: a reader comparing two reports at that SHA
sees a model-quality difference that is a scorer-version artifact.

Usage (from ``apps/prototype-description-service``):

    .venv/bin/python -m scripts.eval_harness.scan_stale_reports

Exit 0 if every published identification block is an explicit refusal.
Exit 1 if any scored or unrecognized identification block is found, if
       a provenance group disagrees with itself, or if no report files
       were scanned.
Exit 2 if the git invocation itself fails.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping


SCAN_PREFIXES = ("docs/",)
JSON_SUFFIX = ".json"

EXIT_CLEAN = 0
EXIT_STALE = 1
EXIT_INFRA = 2


class IdentVerdict(StrEnum):
    """Classification of one ``faces.identification`` block."""

    REFUSED = "refused"
    SCORED = "scored"
    UNRECOGNIZED = "unrecognized"


class ScanError(Exception):
    """Infrastructure failure (git, workspace). Not a report finding."""


def is_report_json(rel: str) -> bool:
    """``*-report.json`` and dated twins like ``*-report-20260714.json``."""
    name = Path(rel).name.lower()
    return name.endswith(JSON_SUFFIX) and "-report" in name


def repo_root() -> Path:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ScanError(f"git invocation failed: {exc}") from exc
    text = out.stdout.strip()
    if not text:
        raise ScanError("git rev-parse --show-toplevel returned empty output")
    return Path(text)


def tracked_report_paths(root: Path) -> list[str]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z", "--", "docs"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ScanError(f"git ls-files failed: {exc}") from exc
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


def identification_value(payload: Mapping[str, Any]) -> Any:
    """Return ``faces.identification`` when the key is present.

    A missing faces object or missing identification key is absence
    (``Ellipsis`` sentinel via a dedicated helper). A present value —
    even a non-object — is returned so classify can fail closed.
    """
    faces = payload.get("faces")
    if not isinstance(faces, Mapping):
        return _ABSENT
    if "identification" not in faces:
        return _ABSENT
    return faces["identification"]


_ABSENT = object()


def _per_identity_row_count(ident: Mapping[str, Any]) -> int | None:
    """Row count, or None if the key is missing / not a mapping."""
    if "per_identity" not in ident:
        return None
    table = ident["per_identity"]
    if not isinstance(table, Mapping):
        return None
    return len(table)


# Exact key set emitted by report._refused_identification_metric.
# Drift-tested against that function — do not invent extras (rg-015).
REFUSED_IDENTIFICATION_KEYS: frozenset[str] = frozenset(
    {
        "refused",
        "invariant",
        "precision",
        "recall",
        "macro_precision",
        "macro_recall",
        "per_identity",
        "true_rejections",
        "excluded_images",
        "wrong_names",
        "ignored_wrong_names",
    }
)

# A refused block may publish these as a non-null value. Every other
# present key must be cleared (None, or an empty per_identity mapping).
_REFUSED_STRUCTURAL_KEYS: frozenset[str] = frozenset({"refused", "invariant"})


def _has_metric_fields(ident: Mapping[str, Any]) -> bool:
    """True when the block carries scoring keys, regardless of values.

    Key presence is the scored predicate. A leftover with a null
    precision is still a scored block. Do not gate this on the
    precision *value*.
    """
    return any(key in ident for key in ("precision", "recall", "per_identity"))


def classify_identification(ident: Any) -> tuple[IdentVerdict, str]:
    """Classify one identification value. Never returns a silent pass.

    REFUSED: ``refused is True``, invariant set, and the block matches
    the scorer-emitted refused shape (no additional published metrics).
    SCORED: not an explicit refusal, and at least one metric field is
    present — including ``precision: null`` / ``recall: 0.0`` leftovers.
    UNRECOGNIZED: everything else (wrong types, refused-but-scored,
    greenwashed refusal, empty object with no metric keys).
    """
    if not isinstance(ident, Mapping):
        return (
            IdentVerdict.UNRECOGNIZED,
            f"identification is {type(ident).__name__}, not an object",
        )

    refused_raw = ident.get("refused")
    table = ident.get("per_identity") if "per_identity" in ident else None
    table_is_mapping = isinstance(table, Mapping)
    table_rows = len(table) if table_is_mapping else 0
    table_malformed = "per_identity" in ident and not table_is_mapping

    if refused_raw is True:
        if table_malformed:
            return (
                IdentVerdict.UNRECOGNIZED,
                "refused block has non-object per_identity",
            )
        published: list[str] = []
        for key, value in ident.items():
            if key in _REFUSED_STRUCTURAL_KEYS:
                continue
            if key == "per_identity":
                if table_rows:
                    published.append("per_identity")
                continue
            if value is not None:
                published.append(str(key))
        if published:
            if "precision" in published or "recall" in published:
                return (
                    IdentVerdict.UNRECOGNIZED,
                    "refused block still publishes precision or recall",
                )
            if "per_identity" in published:
                return (
                    IdentVerdict.UNRECOGNIZED,
                    "refused block still publishes a per-identity table",
                )
            named = ", ".join(sorted(published))
            return (
                IdentVerdict.UNRECOGNIZED,
                f"refused block still publishes {named}",
            )
        invariant = ident.get("invariant")
        if not isinstance(invariant, str) or not invariant.strip():
            return (
                IdentVerdict.UNRECOGNIZED,
                "refused block missing invariant",
            )
        return IdentVerdict.REFUSED, "explicit refusal"

    if table_malformed:
        return (
            IdentVerdict.UNRECOGNIZED,
            "per_identity is not an object",
        )
    if not _has_metric_fields(ident):
        return (
            IdentVerdict.UNRECOGNIZED,
            "not refused and no identification metric fields",
        )
    return IdentVerdict.SCORED, "scored identification block"


@dataclass(frozen=True)
class IdentificationHit:
    """One examined identification block (any verdict)."""

    rel: str
    verdict: IdentVerdict
    reason: str
    precision: Any
    recall: Any
    refused: Any
    per_identity_rows: int | None
    invariant: Any
    score_manifest_sha256: str | None

    @property
    def shape(self) -> str:
        sha = self.score_manifest_sha256 or "(missing)"
        return (
            f"refused={self.refused!r} precision={self.precision!r} "
            f"recall={self.recall!r} per_identity={self.per_identity_rows} "
            f"sha={sha}"
        )


def score_manifest_sha256(payload: Mapping[str, Any]) -> str | None:
    prov = payload.get("provenance")
    if not isinstance(prov, Mapping):
        return None
    sha = prov.get("score_manifest_sha256")
    if not isinstance(sha, str) or not sha:
        return None
    return sha


def scan_payload(rel: str, payload: Any) -> IdentificationHit | None:
    """Return a hit when the payload carries an identification value.

    Unreadable / non-object report roots become UNRECOGNIZED hits so
    they cannot pass silently.
    """
    if not isinstance(payload, Mapping):
        return IdentificationHit(
            rel=rel,
            verdict=IdentVerdict.UNRECOGNIZED,
            reason="report root is not an object",
            precision=None,
            recall=None,
            refused=None,
            per_identity_rows=None,
            invariant=None,
            score_manifest_sha256=None,
        )
    ident = identification_value(payload)
    if ident is _ABSENT:
        return None
    verdict, reason = classify_identification(ident)
    ident_map = ident if isinstance(ident, Mapping) else {}
    return IdentificationHit(
        rel=rel,
        verdict=verdict,
        reason=reason,
        precision=ident_map.get("precision") if ident_map else None,
        recall=ident_map.get("recall") if ident_map else None,
        refused=ident_map.get("refused") if ident_map else None,
        per_identity_rows=_per_identity_row_count(ident_map) if ident_map else None,
        invariant=ident_map.get("invariant") if ident_map else None,
        score_manifest_sha256=score_manifest_sha256(payload),
    )


def load_report(root: Path, rel: str) -> tuple[Any | None, str | None]:
    """Return (payload, error). error set means the file is unreadable."""
    path = root / rel
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"unreadable: {exc}"
    try:
        return json.loads(text), None
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc}"


def provenance_contradictions(
    hits: list[IdentificationHit],
) -> dict[str, list[IdentificationHit]]:
    """Groups whose members do not all share one verdict.

    Reports with no ``score_manifest_sha256`` are skipped. Absence is
    not a shared value — two reports that both omit the field are not
    a provenance contradiction.
    """
    groups: dict[str, list[IdentificationHit]] = defaultdict(list)
    for hit in hits:
        sha = hit.score_manifest_sha256
        if sha is None:
            continue
        groups[sha].append(hit)
    return {
        sha: members
        for sha, members in groups.items()
        if len({m.verdict for m in members}) > 1
    }


def format_report(
    *,
    examined: int,
    scanned_files: int,
    hits: list[IdentificationHit],
    contradictions: Mapping[str, list[IdentificationHit]],
) -> str:
    stale = [h for h in hits if h.verdict is not IdentVerdict.REFUSED]
    scored_n = sum(1 for h in hits if h.verdict is IdentVerdict.SCORED)
    unrec_n = sum(1 for h in hits if h.verdict is IdentVerdict.UNRECOGNIZED)
    contrad_n = len(contradictions)
    if not stale and not contrad_n:
        return (
            f"scan_stale_reports: ok — {examined} identification "
            f"block(s) refused ({scanned_files} report files scanned; "
            f"{contrad_n} provenance contradictions)"
        )
    lines = [
        f"scan_stale_reports: {scored_n} scored, {unrec_n} unrecognized "
        f"identification block(s); {contrad_n} provenance contradiction(s) "
        f"(examined {examined} across {scanned_files} files)."
    ]
    for hit in stale:
        lines.append(f"  {hit.verdict.value.upper()}  {hit.rel}  {hit.shape}")
        lines.append(f"    reason: {hit.reason}")
    if contradictions:
        lines.append("PROVENANCE CONTRADICTIONS:")
        for sha, members in contradictions.items():
            counts = defaultdict(int)
            for m in members:
                counts[m.verdict] += 1
            tally = " ".join(
                f"{verdict.value}={counts[verdict]}" for verdict in IdentVerdict
                if counts[verdict]
            )
            lines.append(f"  sha256={sha}  {tally}")
            for m in members:
                lines.append(f"    {m.verdict.value.upper()}  {m.rel}")
    return "\n".join(lines)


def scan_root(root: Path) -> tuple[int, str]:
    """Scan tracked docs reports. Returns (exit_code, message)."""
    paths = tracked_report_paths(root)
    if not paths:
        return (
            EXIT_STALE,
            "scan_stale_reports: no tracked docs/*-report*.json files scanned",
        )
    hits: list[IdentificationHit] = []
    for rel in paths:
        payload, error = load_report(root, rel)
        if error is not None:
            hits.append(
                IdentificationHit(
                    rel=rel,
                    verdict=IdentVerdict.UNRECOGNIZED,
                    reason=error,
                    precision=None,
                    recall=None,
                    refused=None,
                    per_identity_rows=None,
                    invariant=None,
                    score_manifest_sha256=None,
                )
            )
            continue
        hit = scan_payload(rel, payload)
        if hit is not None:
            hits.append(hit)
    examined = len(hits)
    contradictions = provenance_contradictions(hits)
    stale = [h for h in hits if h.verdict is not IdentVerdict.REFUSED]
    message = format_report(
        examined=examined,
        scanned_files=len(paths),
        hits=hits,
        contradictions=contradictions,
    )
    if stale or contradictions:
        return EXIT_STALE, message
    return EXIT_CLEAN, message


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    try:
        root = repo_root()
        code, message = scan_root(root)
    except ScanError as exc:
        print(f"scan_stale_reports: {exc}", file=sys.stderr)
        return EXIT_INFRA
    stream = sys.stdout if code == EXIT_CLEAN else sys.stderr
    print(message, file=stream)
    return code


if __name__ == "__main__":
    sys.exit(main())
