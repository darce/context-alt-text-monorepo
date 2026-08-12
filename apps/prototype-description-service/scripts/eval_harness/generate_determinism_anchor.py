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

Regeneration is byte-stable: fixed ``started_at`` / ``head_sha`` defaults, sorted
JSON keys, synthetic image material derived only from entry path/sha/media_id.
``provenance.manifest_sha256`` is always computed via ``cli._manifest_sha`` at
generation time — never hand-stamped (rg-015).

Seeded-stub scoring requires ``--rubric-gate skip`` (vacuity exemption); the
scored report carries ``verdict=pass_ungated`` by design.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from scene.application.seeded_adapter import SeededDescriptionAdapter
from scripts.eval_harness.cli import _manifest_sha, _serialize_score_docs
from scripts.eval_harness.manifest import GoldenEntry, GoldenManifest, load_manifest
from scripts.eval_harness.report import score_run_record
from scripts.eval_harness.schema import SCHEMA, DocKind

# Fixed defaults so two generator runs on the same tree are byte-identical.
_DEFAULT_STARTED_AT = "2026-08-11T00:00:00Z"
_DEFAULT_HEAD_SHA = "0" * 40
_DEFAULT_BASE_URL = "seeded-stub://offline"
_DEFAULT_STEM = "S2A-determinism-anchor-run-20260811"
_DEFAULT_MANIFEST = "scene/tests/seed/golden.json"
_DEFAULT_OUT_DIR = Path("../../docs/tasks/vlm/bakeoff-results")

# Deterministic face geometry (same step as fusion_runner / suite fixtures).
_BBOX_X0 = 10.0
_BBOX_DX = 60.0
_BBOX_Y = 40.0
_BBOX_W = 50.0
_BBOX_H = 60.0


def _synthetic_image_bytes(entry: GoldenEntry) -> bytes:
    """Deterministic fake image bytes (no network, no fixture dir)."""
    material = f"{entry.path}:{entry.sha256}:{entry.media_id}".encode()
    return hashlib.sha256(material).digest() + b"\x89PNG\r\n\x1a\nseeded-anchor"


def _identity_rows(entry: GoldenEntry) -> list[dict[str, Any]]:
    """Dict identity rows for present_identities (greenfield rejects bare strings)."""
    rows: list[dict[str, Any]] = []
    for index, name in enumerate(entry.present_identities):
        bbox = {
            "x": _BBOX_X0 + index * _BBOX_DX,
            "y": _BBOX_Y,
            "width": _BBOX_W,
            "height": _BBOX_H,
        }
        rows.append({"name": name, "bbox": bbox, "unpositioned": False})
    return rows


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


def build_run_record(
    manifest: GoldenManifest,
    *,
    head_sha: str,
    started_at: str,
    base_url: str = _DEFAULT_BASE_URL,
) -> dict[str, Any]:
    """Build an acx-eval/v1 run_record from the seeded stub over the full manifest."""
    adapter = SeededDescriptionAdapter()
    items: list[dict[str, Any]] = []
    for entry in manifest.entries:
        items.append(
            {
                "media_id": entry.media_id,
                "path": entry.path,
                "describe": _describe_payload(adapter, entry),
                "identities": _identity_rows(entry),
                "face_count": entry.face_count,
                "error": None,
            }
        )
    # Computed at generation time from the loaded manifest (rg-015) — never assigned.
    manifest_sha = _manifest_sha(manifest)
    return {
        "schema": SCHEMA,
        "kind": DocKind.RUN_RECORD.value,
        "provenance": {
            "manifest_sha256": manifest_sha,
            "base_url": base_url,
            "head_sha": head_sha,
            "started_at": started_at,
            "generator": "scripts.eval_harness.generate_determinism_anchor",
            "adapter": "seeded",
        },
        "items": items,
    }


def _dumps(obj: dict[str, Any]) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_anchor(
    *,
    manifest_path: Path,
    out_dir: Path,
    stem: str,
    head_sha: str,
    started_at: str,
) -> tuple[Path, Path, Path, str]:
    """Generate run-record + scored report pair; return paths and computed manifest sha."""
    # Metadata-only: uses path/sha256/media_id/present_identities/face_count for synthetic
    # image material + scoring; never opens real fixture bytes (module docstring: no GOLDEN_IMAGES_DIR).
    manifest = load_manifest(str(manifest_path), skip_hash_verification=True)
    record = build_run_record(manifest, head_sha=head_sha, started_at=started_at)
    manifest_sha = record["provenance"]["manifest_sha256"]

    out_dir.mkdir(parents=True, exist_ok=True)
    run_path = out_dir / f"{stem}.json"
    report_json_path = out_dir / f"{stem}-report.json"
    report_md_path = out_dir / f"{stem}-report.md"

    run_path.write_text(_dumps(record))

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
    json_doc, md_doc = _serialize_score_docs(scored)
    report_json_path.write_text(json_doc)
    report_md_path.write_text(md_doc)
    return run_path, report_json_path, report_md_path, manifest_sha


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
        "--head-sha",
        default=_DEFAULT_HEAD_SHA,
        help="provenance.head_sha (default: 40 zero hex; fixed for byte-stable regen)",
    )
    parser.add_argument(
        "--started-at",
        default=_DEFAULT_STARTED_AT,
        help=f"provenance.started_at ISO-8601 (default: {_DEFAULT_STARTED_AT})",
    )
    args = parser.parse_args(argv)

    run_path, report_json_path, report_md_path, manifest_sha = write_anchor(
        manifest_path=args.manifest,
        out_dir=args.out_dir,
        stem=args.stem,
        head_sha=args.head_sha,
        started_at=args.started_at,
    )
    print(f"manifest_sha256={manifest_sha}")
    print(f"run_record={run_path}")
    print(f"report_json={report_json_path}")
    print(f"report_md={report_md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
