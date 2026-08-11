#!/usr/bin/env python3
"""Generate a re-scorable synthetic face determinism anchor (VLM-6 F6 / B-06).

Offline, model-free, no private images: hand-constructed dim=8 unit vectors and
synthetic bboxes describe no real person. Built via ``build_face_run_record`` —
no detector, no image bytes, no model weights (PROV-01).

``golden.json`` is unsuitable as the score-time manifest: its 37 entries have
``face_count`` / ``present_identities`` but **zero** ``face_boxes``. Face
assignment is IoU-over-GT-boxes; a zero-box corpus yields only unmatched
detections and vacuous slices. This generator therefore emits a small dedicated
synthetic face manifest next to the run-record (does not bend ``golden.json``).

Default outputs (repo-root relative when run from ``apps/prototype-description-service``)::

    ../../docs/tasks/vlm/bakeoff-results/S2A-face-determinism-anchor-manifest-20260811.json
    ../../docs/tasks/vlm/bakeoff-results/S2A-face-determinism-anchor-run-20260811.json
    ../../docs/tasks/vlm/bakeoff-results/S2A-face-determinism-anchor-run-20260811-face-report.json
    ../../docs/tasks/vlm/bakeoff-results/S2A-face-determinism-anchor-run-20260811-face-report.md

Regeneration is byte-stable: fixed ``started_at`` / ``head_sha`` defaults
(byte-stability sentinels, not live git provenance), sorted JSON keys,
synthetic embeddings derived only from fixed construction constants.
``provenance.manifest_sha256`` is always computed via ``cli._manifest_sha`` at
generation time — never hand-stamped (rg-015).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

from scripts.eval_harness.cli import _manifest_sha
from scripts.eval_harness.face_run_record import (
    build_face_detection,
    build_face_run_item,
    build_face_run_record,
)
from scripts.eval_harness.manifest import load_manifest
from scripts.eval_harness.report import build_face_reports

# Fixed defaults so two generator runs on the same tree are byte-identical.
# These are BYTE-STABILITY SENTINELS, not live git / wall-clock provenance.
_DEFAULT_STARTED_AT = "2026-08-11T00:00:00Z"
_DEFAULT_HEAD_SHA = "0" * 40
_DEFAULT_STEM = "S2A-face-determinism-anchor-run-20260811"
_DEFAULT_MANIFEST_STEM = "S2A-face-determinism-anchor-manifest-20260811"
_DEFAULT_OUT_DIR = Path("../../docs/tasks/vlm/bakeoff-results")
_MODEL_ID = "synthetic-face-anchor"
_EMBEDDING_DIM = 8
_IMAGE_SIZE = [100, 100]
# det bbox_px [x,y,w,h] = [20,20,40,40] on 100x100 → centre (0.4,0.4) size (0.4,0.4)
_BBOX_PX = [20.0, 20.0, 40.0, 40.0]
_GT_BOX = {"x": 0.4, "y": 0.4, "w": 0.4, "h": 0.4, "source": "iptc"}
_LANDMARKS = [[0.0, 0.0]] * 5
_DET_SCORE = 0.95


def _unit(values: list[float]) -> list[float]:
    """L2-normalise a synthetic vector (no numpy — pure construction)."""
    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return [float(v) / norm for v in values]


def _synthetic_embeddings() -> dict[str, list[float]]:
    """Hand-constructed dim=8 unit vectors; no real image or person.

    Alice near e0, stranger near e1 so open-set reject is natural at typical τ
    (same geometry as ``_face_fixture_corpus`` in test_eval_harness_report.py).
    """
    dim = _EMBEDDING_DIM
    return {
        "alice_a": _unit([1.0] + [0.0] * (dim - 1)),
        "alice_b": _unit([0.98, 0.1] + [0.0] * (dim - 2)),
        "stranger": _unit([0.0, 1.0] + [0.0] * (dim - 2)),
    }


def build_synthetic_face_manifest() -> dict[str, Any]:
    """Small dedicated face manifest with GT centre boxes (IoU-matchable).

    Not ``golden.json``: golden has face_count/present_identities but no
    face_boxes, so score_face_run_record cannot associate detections usefully.
    """
    emb_note = (
        "synthetic face determinism anchor — no real images; "
        "GT boxes pair with dim=8 unit-vector detections"
    )
    alice_box = {**_GT_BOX, "name": "Alice Example"}
    stranger_box = {**_GT_BOX, "name": None}
    return {
        "manifest_version": 2,
        "roster": ["Alice Example"],
        "roster_cohorts": {"Alice Example": "cohort_a"},
        "entries": [
            {
                "path": "celebs01/alice-a.jpg",
                "sha256": "a" * 64,
                "media_id": 1,
                "face_count": 1,
                "present_identities": ["Alice Example"],
                "base_caption": "",
                "must_right": [],
                "easy_wrong": [],
                "policy": {"recognition_enabled": True},
                "face_boxes": [alice_box],
                "provenance": {
                    "source": "celeb",
                    "license": "public_domain",
                    "publishable": True,
                    "note": emb_note,
                },
                "demographic_cohort": "cohort_a",
            },
            {
                "path": "celebs01/alice-b.jpg",
                "sha256": "b" * 64,
                "media_id": 2,
                "face_count": 1,
                "present_identities": ["Alice Example"],
                "base_caption": "",
                "must_right": [],
                "easy_wrong": [],
                "policy": {"recognition_enabled": True},
                "face_boxes": [alice_box],
                "provenance": {
                    "source": "celeb",
                    "license": "public_domain",
                    "publishable": True,
                    "note": emb_note,
                },
                "demographic_cohort": "cohort_a",
            },
            {
                "path": "localwp/uploads/stranger-party.jpg",
                "sha256": "c" * 64,
                "media_id": 3,
                "face_count": 1,
                "present_identities": [],
                "base_caption": "",
                "must_right": [],
                "easy_wrong": [],
                "policy": {"recognition_enabled": True},
                "face_boxes": [stranger_box],
                "provenance": {
                    "source": "localwp",
                    "license": "consented",
                    "publishable": False,
                    "note": emb_note,
                },
            },
        ],
    }


def _face(embedding: list[float]) -> dict[str, Any]:
    return build_face_detection(
        bbox_px=_BBOX_PX,
        landmarks_px=_LANDMARKS,
        embedding=embedding,
        det_score=_DET_SCORE,
    )


def build_face_anchor_run_record(
    *,
    manifest_sha256: str,
    head_sha: str,
    started_at: str,
) -> dict[str, Any]:
    """Build a validated face_run_record from synthetic vectors only (PROV-01)."""
    emb = _synthetic_embeddings()
    items = [
        build_face_run_item(
            media_id=1,
            path="celebs01/alice-a.jpg",
            model_id=_MODEL_ID,
            embedding_dim=_EMBEDDING_DIM,
            image_size=_IMAGE_SIZE,
            faces=[_face(emb["alice_a"])],
        ),
        build_face_run_item(
            media_id=2,
            path="celebs01/alice-b.jpg",
            model_id=_MODEL_ID,
            embedding_dim=_EMBEDDING_DIM,
            image_size=_IMAGE_SIZE,
            faces=[_face(emb["alice_b"])],
        ),
        build_face_run_item(
            media_id=3,
            path="localwp/uploads/stranger-party.jpg",
            model_id=_MODEL_ID,
            embedding_dim=_EMBEDDING_DIM,
            image_size=_IMAGE_SIZE,
            faces=[_face(emb["stranger"])],
        ),
    ]
    provenance = {
        "manifest_sha256": manifest_sha256,
        "head_sha": head_sha,
        "started_at": started_at,
        "leg": "candidate",
        "model_id": _MODEL_ID,
        "embedding_dim": _EMBEDDING_DIM,
        "generator": "scripts.eval_harness.generate_face_determinism_anchor",
        "note": (
            "synthetic dim=8 unit vectors; no real image/embedding (PROV-01); "
            "head_sha/started_at are byte-stability sentinels"
        ),
    }
    return build_face_run_record(items, provenance=provenance)


def _dumps(obj: dict[str, Any]) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_face_anchor(
    *,
    out_dir: Path,
    stem: str,
    manifest_stem: str,
    head_sha: str,
    started_at: str,
) -> tuple[Path, Path, Path, Path, str]:
    """Generate manifest + run-record + scored face-report pair.

    Returns (manifest_path, run_path, report_json, report_md, manifest_sha).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / f"{manifest_stem}.json"
    run_path = out_dir / f"{stem}.json"
    report_json_path = out_dir / f"{stem}-face-report.json"
    report_md_path = out_dir / f"{stem}-face-report.md"

    raw_manifest = build_synthetic_face_manifest()
    manifest_path.write_text(_dumps(raw_manifest))

    # Load through the real loader so sha matches score-time computation (rg-015).
    manifest = load_manifest(str(manifest_path))
    # Computed at generation time from the loaded manifest — never hand-stamped.
    manifest_sha = _manifest_sha(manifest)

    record = build_face_anchor_run_record(
        manifest_sha256=manifest_sha,
        head_sha=head_sha,
        started_at=started_at,
    )
    run_path.write_text(_dumps(record))

    json_doc, md_doc = build_face_reports(
        record,
        manifest,
        score_manifest_sha256=manifest_sha,
        public=False,
    )
    report_json_path.write_text(json_doc)
    report_md_path.write_text(md_doc)
    return manifest_path, run_path, report_json_path, report_md_path, manifest_sha


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a synthetic offline face determinism anchor (VLM-6 F6)."
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
        help=f"run-record filename stem without extension (default: {_DEFAULT_STEM})",
    )
    parser.add_argument(
        "--manifest-stem",
        default=_DEFAULT_MANIFEST_STEM,
        help=f"manifest filename stem (default: {_DEFAULT_MANIFEST_STEM})",
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

    manifest_path, run_path, report_json, report_md, manifest_sha = write_face_anchor(
        out_dir=args.out_dir,
        stem=args.stem,
        manifest_stem=args.manifest_stem,
        head_sha=args.head_sha,
        started_at=args.started_at,
    )
    print(f"manifest_sha256={manifest_sha}")
    print(f"embedding_dim={_EMBEDDING_DIM}")
    print(f"manifest={manifest_path}")
    print(f"run_record={run_path}")
    print(f"report_json={report_json}")
    print(f"report_md={report_md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
