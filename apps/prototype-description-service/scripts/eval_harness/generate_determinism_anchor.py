#!/usr/bin/env python3
"""Generate a re-scorable caption determinism anchor from the committed seed corpus.

Offline, model-free: uses ``SeededDescriptionAdapter`` + synthetic image bytes so
the run-record and scored reports are reproducible from the repo alone (no remote
calls, no GOLDEN_IMAGES_DIR). Intended consumer: ``score --check-determinism``
and the future digest gate (VLM6-S2A-B-06).

Default outputs (repo-root relative when run from ``apps/prototype-description-service``)::

    ../../docs/tasks/vlm/bakeoff-results/S2A-determinism-anchor-run-20260811.json
    ../../docs/tasks/vlm/bakeoff-results/S2A-determinism-anchor-run-20260811-report.json
    ../../docs/tasks/vlm/bakeoff-results/S2A-determinism-anchor-run-20260811-report.md

Regeneration is byte-stable: fixed ``fixture_revision`` / ``canonical_timestamp``
defaults, sorted JSON keys, synthetic image material derived only from entry
path/sha/media_id. ``provenance.manifest_sha256`` is always computed via
``cli._manifest_sha`` at generation time — never hand-stamped (rg-015).

Seeded predictions are **ground-truth-derived fixtures** with a fixed seeded
deviation (TEST-15): they are not a pure echo of the manifest, so face detection
and identification metrics can move under corruption. Face numbers from this
anchor are **non-evidential** — they prove scoring-path byte-stability, not
recognition quality. See ``predictions_source`` / ``face_metrics_evidential``
in provenance.

Seeded-stub scoring requires ``--rubric-gate skip`` (vacuity exemption).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scene.application.seeded_adapter import SeededDescriptionAdapter
from scripts.eval_harness.cli import _manifest_sha, _serialize_score_docs
from scripts.eval_harness.manifest import (
    GoldenEntry,
    GoldenManifest,
    compute_corpus_coverage_gaps,
    load_manifest,
    metric_backing_refusals,
)
from scripts.eval_harness.promote_atomic import (
    CAPTION_PROMOTE,
    atomic_promote,
    recover_promote,
    scavenge_orphan_stages,
    validate_live_head_sha,
)
from scripts.eval_harness.report import score_run_record
from scripts.eval_harness.schema import SCHEMA, DocKind

# Shared promote protocol (HARM-02) — caption namespace (RV2-03).
_PROMOTE_NS = CAPTION_PROMOTE
_PROMOTE_JOURNAL = CAPTION_PROMOTE.journal_name
_PROMOTE_STAGE_PREFIX = CAPTION_PROMOTE.stage_prefix
# Structural re-exports so tests can assert caption/face share one implementation.
_atomic_promote_core = atomic_promote
_recover_promote_core = recover_promote

# Fixed defaults so two generator runs on the same tree are byte-identical.
# These are BYTE-STABILITY SENTINELS in fixture_* fields — not git / wall-clock
# provenance (VLM6-F-04 / rg-015). Live head_sha/started_at are recorded separately
# when available and are normalised away at freeze comparison time by the digest
# gate comparing scored report bytes, not these optional live fields.
_DEFAULT_FIXTURE_REVISION = "0" * 40
_DEFAULT_CANONICAL_TIMESTAMP = "2026-08-11T00:00:00Z"
_DEFAULT_BASE_URL = "seeded-stub://offline"
_DEFAULT_STEM = "S2A-determinism-anchor-run-20260811"
_DEFAULT_MANIFEST = "scene/tests/seed/golden.json"
_DEFAULT_OUT_DIR = Path("../../docs/tasks/vlm/bakeoff-results")

# Predictions are ground-truth-derived fixtures, not detector/model output (VLM6-C-04).
_PREDICTIONS_SOURCE = "ground_truth_derived_fixture"


def _synthetic_image_bytes(entry: GoldenEntry) -> bytes:
    """Deterministic fake image bytes (no network, no fixture dir)."""
    material = f"{entry.path}:{entry.sha256}:{entry.media_id}".encode()
    return hashlib.sha256(material).digest() + b"\x89PNG\r\n\x1a\nseeded-anchor"


def _identity_rows(entry: GoldenEntry, *, seed_index: int) -> list[dict[str, Any]]:
    """Dict identity rows derived from present_identities with fixed seeded deviation.

    No invented pixel bboxes (VLM6-C-09 / rg-015): fixture rows are unpositioned.
    A pure GT echo would make identification P/R tautological (TEST-15 / VLM6-C-04);
    drop or inject names on a fixed subset so metrics can move under corruption.
    """
    names = list(entry.present_identities)
    # Fixed seeded deviation (byte-stable):
    # - every 5th named entry: drop last name → identification FN
    # - every 9th named entry (and not also a drop): inject a non-present name → FP
    if names and seed_index % 5 == 0:
        names = names[:-1]
    rows = [{"name": name, "unpositioned": True} for name in names]
    if entry.present_identities and seed_index % 9 == 0 and seed_index % 5 != 0:
        rows.append({"name": f"Fixture-Wrong-{seed_index}", "unpositioned": True})
    return rows


def _predicted_face_count(entry: GoldenEntry, *, seed_index: int) -> int:
    """Face count with fixed seeded deviation so detection is not a pure echo (TEST-15).

    - index % 7 == 0 and face_count > 0 → under-count by 1 (FN)
    - index % 11 == 0 → over-count by 1 (FP)
    Otherwise echo GT. Deterministic; no image geometry consulted.
    """
    count = int(entry.face_count)
    if seed_index % 7 == 0 and count > 0:
        return count - 1
    if seed_index % 11 == 0:
        return count + 1
    return count


def _describe_payload(adapter: SeededDescriptionAdapter, entry: GoldenEntry) -> dict[str, Any]:
    result = adapter.describe(image_bytes=_synthetic_image_bytes(entry), context=None)
    kind = adapter.kind.value if hasattr(adapter.kind, "value") else str(adapter.kind)
    return {
        "adapter": kind,
        "alt_text_draft": result.alt_text_draft,
        "cached": False,
        "model_id": adapter.model_id,
        "model_version": adapter.model_version,
        "visual_facts": {
            "caption": result.caption,
            "objects": list(result.objects),
            "ocr_text": result.ocr_text,
        },
    }


def _git_head_sha() -> str | None:
    """Best-effort real HEAD; None when not in a git tree (never fabricate)."""
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        ).strip()
    except (subprocess.SubprocessError, OSError, FileNotFoundError):
        return None
    if len(out) == 40 and all(c in "0123456789abcdef" for c in out):
        return out
    return None


def build_run_record(
    manifest: GoldenManifest,
    *,
    fixture_revision: str,
    canonical_timestamp: str,
    base_url: str = _DEFAULT_BASE_URL,
    head_sha: str | None = None,
    started_at: str | None = None,
) -> dict[str, Any]:
    """Build an acx-eval/v1 run_record from the seeded stub over the full manifest.

    Face/identity fields are ground-truth-derived fixtures with a fixed seeded
    deviation (not a pure GT echo — VLM6-C-04 / TEST-15). Coverage gaps come from
    ``compute_corpus_coverage_gaps`` (shared with the live path — VLM6-E-07).
    """
    adapter = SeededDescriptionAdapter()
    items: list[dict[str, Any]] = []
    for index, entry in enumerate(manifest.entries):
        items.append(
            {
                "media_id": entry.media_id,
                "path": entry.path,
                "describe": _describe_payload(adapter, entry),
                "identities": _identity_rows(entry, seed_index=index),
                "face_count": _predicted_face_count(entry, seed_index=index),
                "error": None,
            }
        )
    # Computed at generation time from the loaded manifest (rg-015) — never assigned.
    manifest_sha = _manifest_sha(manifest)
    coverage_gaps = compute_corpus_coverage_gaps(manifest.entries)
    backing_refusals = metric_backing_refusals(manifest)
    # head_sha/started_at: explicit None means "resolve live"; pass a value to pin.
    # Callers that want byte-stable freezes pass pin values via write_anchor.
    if head_sha is None:
        live_head: str | None = _git_head_sha()
    else:
        live_head = head_sha or None  # empty string → None (never fabricate zeros)
    if started_at is None:
        live_started: str | None = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        live_started = started_at or None  # empty string → None (S4-04: never pin a fake clock)
    return {
        "schema": SCHEMA,
        "kind": DocKind.RUN_RECORD.value,
        "provenance": {
            "manifest_sha256": manifest_sha,
            "base_url": base_url,
            # Byte-stability sentinels — NOT git/wall-clock contract fields (VLM6-F-04).
            "fixture_revision": fixture_revision,
            "canonical_timestamp": canonical_timestamp,
            # Optional live provenance; may differ across regenerations. Never a
            # fabricated 40-zero SHA (rg-015 / VLM6-F-04).
            "head_sha": live_head,
            "started_at": live_started,
            "generator": "scripts.eval_harness.generate_determinism_anchor",
            "adapter": "seeded",
            "predictions_source": _PREDICTIONS_SOURCE,
            # Face metrics from GT-derived fixtures are non-evidential (VLM6-C-04 / E-04).
            "face_metrics_evidential": False,
            "note": (
                "byte-stability anchor from the seeded offline adapter; no model, no real "
                "image bytes. Proves the scoring path is deterministic and that corruption "
                "goes red — not that captions or faces are good. Face/identity predictions "
                "are ground_truth_derived_fixture with a fixed seeded deviation (TEST-15); "
                "face_metrics_evidential=false. fixture_revision/canonical_timestamp are "
                "byte-stability sentinels, not git/wall-clock provenance. See "
                "eval_harness/README.md § Corpus coverage boundary."
            ),
            "coverage_gaps": coverage_gaps,
            "metric_backing_refusals": backing_refusals,
        },
        "items": items,
    }


# Back-compat alias used by tests (VLM6-R2-03 surface).
def _coverage_gaps(entries: list[Any]) -> dict[str, dict[str, object]]:
    """Delegate to the shared registry-driven helper (VLM6-C-01 / C-02 / E-07)."""
    return compute_corpus_coverage_gaps(entries)


def _dumps(obj: dict[str, Any]) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _recover_promote(dest_dir: Path) -> None:
    """Caption-namespaced recover (shared impl — HARM-02 / RV2-03)."""
    recover_promote(dest_dir, _PROMOTE_NS)


def _atomic_promote(src_dir: Path, dest_dir: Path, names: list[str]) -> None:
    """Caption-namespaced set-atomic promote (shared impl — HARM-02 / RV2-03)."""
    atomic_promote(src_dir, dest_dir, names, _PROMOTE_NS)


def write_anchor(
    *,
    manifest_path: Path,
    out_dir: Path,
    stem: str,
    fixture_revision: str = _DEFAULT_FIXTURE_REVISION,
    canonical_timestamp: str = _DEFAULT_CANONICAL_TIMESTAMP,
    # Back-compat: older callers pass head_sha/started_at as byte-stability sentinels.
    head_sha: str | None = None,
    started_at: str | None = None,
    live_head_sha: str | None = None,
    live_started_at: str | None = None,
    pin_live_provenance: bool = True,
) -> tuple[Path, Path, Path, str]:
    """Generate run-record + scored report pair; return paths and computed manifest sha.

    Builds the full artifact set in a temporary directory, verifies cross-file
    consistency, then promotes the named set via journaled stage install
    (VLM6-F-05 / rg-002 / S4-02). After return (or crash + recover) the
    destination is fully old or fully new — never a mixed pairing.

    When ``pin_live_provenance`` is True (default, for byte-stable regen), live
    ``head_sha``/``started_at`` are nulled so two generator runs match and no
    contract wall-clock/git field holds a fabricated sentinel (S4-04 / rg-015).
    Byte-stability comes only from ``fixture_revision`` / ``canonical_timestamp``.
    Pin mode is gated solely on this flag (RV2-05) — never on whether
    ``live_*`` is ``None`` vs empty string. Pass ``pin_live_provenance=False``
    (CLI ``--no-pin``) to record real values; empty ``live_head_sha`` is refused.
    """
    # Reclaim orphan stage dirs left by crashes before journal write (RV2-07).
    scavenge_orphan_stages(out_dir, _PROMOTE_NS)

    # Metadata-only: uses path/sha256/media_id/present_identities/face_count for synthetic
    # image material + scoring; never opens real fixture bytes (module docstring: no GOLDEN_IMAGES_DIR).
    manifest = load_manifest(str(manifest_path), skip_hash_verification=True)

    # Legacy keyword head_sha/started_at map onto fixture sentinels.
    fix_rev = head_sha if head_sha is not None else fixture_revision
    can_ts = started_at if started_at is not None else canonical_timestamp

    # Pin mode is explicit (RV2-05) — not "live_* is None". Empty live_head_sha
    # is refused so it cannot silently exit pin mode and inject wall-clock.
    if live_head_sha is not None:
        live_head_sha = validate_live_head_sha(live_head_sha)

    if pin_live_provenance:
        # Byte-stable mode: null contract head_sha/started_at (never fabricate).
        # Sentinels live only in fixture_revision / canonical_timestamp (S4-04).
        record = build_run_record(
            manifest,
            fixture_revision=fix_rev,
            canonical_timestamp=can_ts,
            head_sha="",  # empty → None in build_run_record
            started_at="",  # empty → overridden to None below
        )
        record["provenance"]["head_sha"] = None
        record["provenance"]["started_at"] = None
    else:
        record = build_run_record(
            manifest,
            fixture_revision=fix_rev,
            canonical_timestamp=can_ts,
            head_sha=live_head_sha,
            started_at=live_started_at,
        )
    manifest_sha = record["provenance"]["manifest_sha256"]

    run_name = f"{stem}.json"
    report_json_name = f"{stem}-report.json"
    report_md_name = f"{stem}-report.md"

    entries = [e.model_dump() for e in manifest.entries]
    roster = sorted(set(getattr(manifest, "roster", []) or []))
    # Seeded stub is model-free: operator must declare rubric-gate skip (cli:1067).
    scored = score_run_record(
        record,
        entries,
        score_manifest_sha256=manifest_sha,
        manifest_roster=roster,
        rubric_gate="skip",
    )
    # Stamp non-evidential face disclosure onto the scored document too.
    scored.setdefault("provenance", {})
    scored["provenance"]["face_metrics_evidential"] = False
    scored["provenance"]["predictions_source"] = _PREDICTIONS_SOURCE
    scored["provenance"]["coverage_gaps"] = record["provenance"]["coverage_gaps"]
    scored["provenance"]["metric_backing_refusals"] = record["provenance"]["metric_backing_refusals"]
    scored["provenance"]["fixture_revision"] = fix_rev
    scored["provenance"]["canonical_timestamp"] = can_ts

    json_doc, md_doc = _serialize_score_docs(scored)
    # Ensure MD surfaces coverage gaps even if the report renderer omits them
    # (VLM6-E-04) — append a machine-readable block when missing.
    if "coverage_gaps" not in md_doc and "Coverage gaps" not in md_doc:
        gap_lines = [
            "",
            "## Coverage gaps (sampling frame — AUDIT-07)",
            "",
            "Face metrics in this freeze are **non-evidential** "
            f"(predictions_source={_PREDICTIONS_SOURCE}; face_metrics_evidential=false).",
            "This artifact certifies scoring-path byte-stability only.",
            "",
        ]
        for field, info in sorted(record["provenance"]["coverage_gaps"].items()):
            gap_lines.append(f"- `{field}`: {info['reason']}")
        if record["provenance"]["metric_backing_refusals"]:
            gap_lines += ["", "### Metric-backing refusals (require_metric_backing)", ""]
            for field, msg in sorted(record["provenance"]["metric_backing_refusals"].items()):
                gap_lines.append(f"- `{field}`: {msg}")
        md_doc = md_doc.rstrip() + "\n" + "\n".join(gap_lines) + "\n"

    with tempfile.TemporaryDirectory(prefix="vlm-anchor-") as tmp:
        tmp_dir = Path(tmp)
        (tmp_dir / run_name).write_text(_dumps(record))
        (tmp_dir / report_json_name).write_text(json_doc)
        (tmp_dir / report_md_name).write_text(md_doc)
        # Cross-file consistency: re-load run-record and confirm sha matches.
        reloaded = json.loads((tmp_dir / run_name).read_text())
        if reloaded["provenance"]["manifest_sha256"] != manifest_sha:
            raise RuntimeError("anchor generation integrity check failed: manifest_sha256 drift")
        if not reloaded["provenance"].get("coverage_gaps"):
            raise RuntimeError("anchor generation integrity check failed: coverage_gaps missing")
        _atomic_promote(tmp_dir, out_dir, [run_name, report_json_name, report_md_name])

    return out_dir / run_name, out_dir / report_json_name, out_dir / report_md_name, manifest_sha


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a re-scorable offline seeded determinism anchor (VLM-6 F4).")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(_DEFAULT_MANIFEST),
        help=f"golden manifest path (default: {_DEFAULT_MANIFEST})",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=_DEFAULT_OUT_DIR,
        help=f"output directory (default: {_DEFAULT_OUT_DIR})",
    )
    parser.add_argument(
        "--stem",
        default=_DEFAULT_STEM,
        help=f"filename stem without extension (default: {_DEFAULT_STEM})",
    )
    parser.add_argument(
        "--fixture-revision",
        default=_DEFAULT_FIXTURE_REVISION,
        help="provenance.fixture_revision byte-stability sentinel (default: 40 zero hex)",
    )
    parser.add_argument(
        "--canonical-timestamp",
        default=_DEFAULT_CANONICAL_TIMESTAMP,
        help=f"provenance.canonical_timestamp sentinel (default: {_DEFAULT_CANONICAL_TIMESTAMP})",
    )
    # Back-compat aliases for older callers / tests.
    parser.add_argument(
        "--head-sha",
        default=None,
        help="(legacy) maps to --fixture-revision when set; prefer --fixture-revision",
    )
    parser.add_argument(
        "--started-at",
        default=None,
        help="(legacy) maps to --canonical-timestamp when set; prefer --canonical-timestamp",
    )
    parser.add_argument(
        "--pin",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="pin mode: null provenance.head_sha/started_at (default: true). "
        "Pass --no-pin to record live provenance (RV2-05 / S4-04).",
    )
    parser.add_argument(
        "--live-head-sha",
        default=None,
        help="real 40-char git SHA for provenance.head_sha when --no-pin "
        "(refuses empty string, forty zeros, non-hex; RV2-04 / RV2-05 / S4-06)",
    )
    parser.add_argument(
        "--live-started-at",
        default=None,
        help="real ISO-8601 for provenance.started_at when --no-pin (not a sentinel)",
    )
    parser.add_argument(
        "--verify-live-head-sha",
        action="store_true",
        default=False,
        help="also require git rev-parse --verify <sha>^{commit} for --live-head-sha",
    )
    args = parser.parse_args(argv)

    fixture_revision = args.fixture_revision
    canonical_timestamp = args.canonical_timestamp
    if args.head_sha is not None:
        fixture_revision = args.head_sha
    if args.started_at is not None:
        canonical_timestamp = args.started_at

    # Validate / normalise live SHA at parse boundary (RV2-04 / RV2-05).
    live_head = validate_live_head_sha(
        args.live_head_sha,
        verify_git=bool(args.verify_live_head_sha),
    )
    if live_head is not None and args.pin:
        raise SystemExit(
            "--live-head-sha requires --no-pin (pin mode nulls contract head_sha; "
            "RV2-05 / S4-04)"
        )
    if args.live_started_at is not None and args.pin:
        raise SystemExit(
            "--live-started-at requires --no-pin (pin mode nulls contract started_at; "
            "RV2-05 / S4-04)"
        )

    run_path, report_json_path, report_md_path, manifest_sha = write_anchor(
        manifest_path=args.manifest,
        out_dir=args.out_dir,
        stem=args.stem,
        fixture_revision=fixture_revision,
        canonical_timestamp=canonical_timestamp,
        head_sha=args.head_sha,
        started_at=args.started_at,
        live_head_sha=live_head,
        live_started_at=args.live_started_at,
        pin_live_provenance=bool(args.pin),
    )
    print(f"manifest_sha256={manifest_sha}")
    print(f"run_record={run_path}")
    print(f"report_json={report_json_path}")
    print(f"report_md={report_md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
