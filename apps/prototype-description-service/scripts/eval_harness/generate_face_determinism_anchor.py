#!/usr/bin/env python3
"""Generate a re-scorable synthetic face determinism anchor (VLM-6 F6/F7 / B-06).

Offline, model-free, no private images: hand-constructed dim=8 unit vectors and
synthetic bboxes describe no real person. Built via ``build_face_run_record`` —
no detector, no image bytes, no model weights (PROV-01).

``golden.json`` is unsuitable as the score-time manifest: its 37 entries have
``face_count`` / ``present_identities`` but **zero** ``face_boxes``. Face
assignment is IoU-over-GT-boxes; a zero-box corpus yields only unmatched
detections and vacuous slices. This generator therefore emits a small dedicated
synthetic face manifest next to the run-record (does not bend ``golden.json``).

F7 de-vacates the freeze (MLDATA-09): the F6 3-item corpus pinned every hard
cell at empty/zero. This generator extends the corpus so clustering, detection
FP/FN, wrong-name, occlusion eligibility, multi-cohort demographic, and the
error-item exclusion path each execute at least once. Cells that remain
under-floor (n_floor 90–100) stay DIRECTIONAL — that is expected. Whatever is
still vacuous is declared in ``provenance.coverage_gaps`` (AUDIT-07), computed
from the scored report at generation time (rg-015 — never hand-stamped).

Default outputs (repo-root relative when run from ``apps/prototype-description-service``)::

    ../../docs/tasks/vlm/bakeoff-results/S2A-face-determinism-anchor-manifest-20260811.json
    ../../docs/tasks/vlm/bakeoff-results/S2A-face-determinism-anchor-run-20260811.json
    ../../docs/tasks/vlm/bakeoff-results/S2A-face-determinism-anchor-run-20260811-face-report.json
    ../../docs/tasks/vlm/bakeoff-results/S2A-face-determinism-anchor-run-20260811-face-report.md

Regeneration is byte-stable: fixed ``started_at`` / ``head_sha`` defaults
(byte-stability sentinels, not live git provenance), sorted JSON keys,
synthetic embeddings derived only from fixed construction constants.
``provenance.manifest_sha256`` and ``provenance.coverage_gaps`` are always
computed at generation time — never hand-stamped (rg-015).
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
    validate_face_run_record,
)
from scripts.eval_harness.manifest import load_manifest
from scripts.eval_harness.report import build_face_reports, occlusion_inputs_from_record

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
# Offset box for FP detection / multi-box scenes (no GT at this location).
_BBOX_PX_FP = [60.0, 60.0, 20.0, 20.0]
_GT_BOX = {"x": 0.4, "y": 0.4, "w": 0.4, "h": 0.4, "source": "iptc"}
# Secondary GT for missed-detection item (no face will be placed here).
_GT_BOX_FN = {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2, "source": "iptc"}
_LANDMARKS = [[0.0, 0.0]] * 5
_DET_SCORE = 0.95

_ALICE = "Alice Example"
_BOB = "Bob Example"
_COHORT_A = "cohort_a"
_COHORT_B = "cohort_b"


def _unit(values: list[float]) -> list[float]:
    """L2-normalise a synthetic vector (no numpy — pure construction)."""
    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return [float(v) / norm for v in values]


def _synthetic_embeddings() -> dict[str, list[float]]:
    """Hand-constructed dim=8 unit vectors; no real image or person (PROV-01).

    Geometry (axes deliberately far so open-set / wrong-name is controllable):
    - Alice near e0, Bob near e2 (orthogonal), stranger near e1.
    - alice_wrong is Bob's axis so a GT-named Alice probe predicts Bob.
    """
    dim = _EMBEDDING_DIM
    return {
        "alice_a": _unit([1.0] + [0.0] * (dim - 1)),
        "alice_b": _unit([0.98, 0.1] + [0.0] * (dim - 2)),
        "bob_a": _unit([0.0, 0.0, 1.0] + [0.0] * (dim - 3)),
        "bob_b": _unit([0.0, 0.05, 0.98] + [0.0] * (dim - 3)),
        # Alice GT box, Bob embedding → wrong_names non-empty (precision < 1).
        "alice_wrong": _unit([0.0, 0.0, 0.99, 0.1] + [0.0] * (dim - 4)),
        "stranger": _unit([0.0, 1.0] + [0.0] * (dim - 2)),
        # Unmatched detection (no GT box at this location).
        "fp_det": _unit([0.0, 0.0, 0.0, 1.0] + [0.0] * (dim - 4)),
    }


def build_synthetic_face_manifest() -> dict[str, Any]:
    """Dedicated face manifest with multi-identity, multi-cohort, FP/FN levers.

    Not ``golden.json``: golden has face_count/present_identities but no
    face_boxes, so score_face_run_record cannot associate detections usefully.
    """
    emb_note = (
        "synthetic face determinism anchor — no real images; "
        "GT boxes pair with dim=8 unit-vector detections (F7 multi-regime)"
    )
    alice_box = {**_GT_BOX, "name": _ALICE}
    bob_box = {**_GT_BOX, "name": _BOB}
    stranger_box = {**_GT_BOX, "name": None}
    fn_box = {**_GT_BOX_FN, "name": _ALICE}
    return {
        "manifest_version": 2,
        "roster": [_ALICE, _BOB],
        "roster_cohorts": {_ALICE: _COHORT_A, _BOB: _COHORT_B},
        "entries": [
            {
                "path": "celebs01/alice-a.jpg",
                "sha256": "a" * 64,
                "media_id": 1,
                "face_count": 1,
                "present_identities": [_ALICE],
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
                "demographic_cohort": _COHORT_A,
            },
            {
                "path": "celebs01/alice-b.jpg",
                "sha256": "b" * 64,
                "media_id": 2,
                "face_count": 1,
                "present_identities": [_ALICE],
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
                "demographic_cohort": _COHORT_A,
            },
            {
                "path": "celebs01/bob-a.jpg",
                "sha256": "d" * 64,
                "media_id": 4,
                "face_count": 1,
                "present_identities": [_BOB],
                "base_caption": "",
                "must_right": [],
                "easy_wrong": [],
                "policy": {"recognition_enabled": True},
                "face_boxes": [bob_box],
                "provenance": {
                    "source": "celeb",
                    "license": "public_domain",
                    "publishable": True,
                    "note": emb_note,
                },
                "demographic_cohort": _COHORT_B,
            },
            {
                "path": "celebs01/bob-b.jpg",
                "sha256": "e" * 64,
                "media_id": 5,
                "face_count": 1,
                "present_identities": [_BOB],
                "base_caption": "",
                "must_right": [],
                "easy_wrong": [],
                "policy": {"recognition_enabled": True},
                "face_boxes": [bob_box],
                "provenance": {
                    "source": "celeb",
                    "license": "public_domain",
                    "publishable": True,
                    "note": emb_note,
                },
                "demographic_cohort": _COHORT_B,
            },
            {
                # Wrong-name probe: Alice GT, Bob-axis embedding.
                "path": "celebs01/alice-wrong.jpg",
                "sha256": "f" * 64,
                "media_id": 6,
                "face_count": 1,
                "present_identities": [_ALICE],
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
                "demographic_cohort": _COHORT_A,
            },
            {
                # Detection FP: no GT boxes, one unmatched detection.
                "path": "celebs01/fp-only.jpg",
                "sha256": "1" * 64,
                "media_id": 7,
                "face_count": 0,
                "present_identities": [],
                "base_caption": "",
                "must_right": [],
                "easy_wrong": [],
                "policy": {"recognition_enabled": True},
                "face_boxes": [],
                "provenance": {
                    "source": "celeb",
                    "license": "public_domain",
                    "publishable": True,
                    "note": emb_note,
                },
            },
            {
                # Detection FN: named GT box, zero detections (missed_gt).
                "path": "celebs01/fn-miss.jpg",
                "sha256": "2" * 64,
                "media_id": 8,
                "face_count": 1,
                "present_identities": [_ALICE],
                "base_caption": "",
                "must_right": [],
                "easy_wrong": [],
                "policy": {"recognition_enabled": True},
                "face_boxes": [fn_box],
                "provenance": {
                    "source": "celeb",
                    "license": "public_domain",
                    "publishable": True,
                    "note": emb_note,
                },
                "demographic_cohort": _COHORT_A,
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
            # failures[] intentionally not exercised: score-face exits non-zero
            # when counts.failed > 0, which would make the freeze green path red.
            # Declared in provenance.coverage_gaps (AUDIT-07).
        ],
    }


def _face(embedding: list[float], *, bbox_px: list[float] | None = None) -> dict[str, Any]:
    return build_face_detection(
        bbox_px=list(bbox_px) if bbox_px is not None else list(_BBOX_PX),
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
            media_id=4,
            path="celebs01/bob-a.jpg",
            model_id=_MODEL_ID,
            embedding_dim=_EMBEDDING_DIM,
            image_size=_IMAGE_SIZE,
            faces=[_face(emb["bob_a"])],
        ),
        build_face_run_item(
            media_id=5,
            path="celebs01/bob-b.jpg",
            model_id=_MODEL_ID,
            embedding_dim=_EMBEDDING_DIM,
            image_size=_IMAGE_SIZE,
            faces=[_face(emb["bob_b"])],
        ),
        build_face_run_item(
            media_id=6,
            path="celebs01/alice-wrong.jpg",
            model_id=_MODEL_ID,
            embedding_dim=_EMBEDDING_DIM,
            image_size=_IMAGE_SIZE,
            faces=[_face(emb["alice_wrong"])],
        ),
        build_face_run_item(
            media_id=7,
            path="celebs01/fp-only.jpg",
            model_id=_MODEL_ID,
            embedding_dim=_EMBEDDING_DIM,
            image_size=_IMAGE_SIZE,
            faces=[_face(emb["fp_det"], bbox_px=_BBOX_PX_FP)],
        ),
        build_face_run_item(
            media_id=8,
            path="celebs01/fn-miss.jpg",
            model_id=_MODEL_ID,
            embedding_dim=_EMBEDDING_DIM,
            image_size=_IMAGE_SIZE,
            faces=[],  # missed GT
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
    # Document-level synthetic occlusion twin (EVAL-16: never an item).
    # Alice has ≥2 matched faces and Bob is enrolled → multi-identity gallery
    # + distinct-image min-gallery make the twin eligible (n_eligible > 0).
    occlusion_twin_pairs_by_tag = {
        "masked": [
            {
                "media_id": 1,
                "box_index": 0,
                "true_name": _ALICE,
                "kind": "masked",
                "embedding": emb["alice_a"],
            }
        ]
    }
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
            "head_sha/started_at are byte-stability sentinels; "
            "F7 multi-regime corpus (2 identities, FP/FN, wrong-name, "
            "occlusion twin, 2 cohorts; failures[] declared gap — score-face "
            "hard-exits on counts.failed>0)"
        ),
    }
    record = build_face_run_record(items, provenance=provenance)
    record["occlusion_twin_pairs_by_tag"] = occlusion_twin_pairs_by_tag
    return validate_face_run_record(record)


def _is_vacuous_occlusion_cell(cell: dict[str, Any]) -> bool:
    synth = cell.get("synthetic") if isinstance(cell.get("synthetic"), dict) else cell
    if not isinstance(synth, dict):
        return True
    n_eligible = synth.get("n_eligible")
    accuracy = synth.get("accuracy")
    if n_eligible is None:
        return True
    return int(n_eligible) == 0 or accuracy is None


def _is_vacuous_id_slice(slice_doc: dict[str, Any]) -> bool:
    """Identification-style slice vacuous when every error path is pinned at zero."""
    wrong = slice_doc.get("wrong_names") or []
    return (
        int(slice_doc.get("fp") or 0) == 0
        and int(slice_doc.get("fn") or 0) == 0
        and int(slice_doc.get("missed_gt") or 0) == 0
        and int(slice_doc.get("unmatched_detections") or 0) == 0
        and len(wrong) == 0
    )


def compute_coverage_gaps(report: dict[str, Any]) -> list[str]:
    """Derive still-vacuous slice names from a scored face report (rg-015).

    A green face gate proves byte-stable re-score + that named cells execute.
    It does **not** prove ship-ready floors (UNDER-FLOOR/DIRECTIONAL is expected
    on this tiny synthetic corpus). Gaps name cells still pinned at empty/null.
    """
    gaps: list[str] = []
    slices = report.get("slices") or {}

    occ = slices.get("occlusion") or {}
    for tag in ("masked", "sunglasses", "occlusion_other"):
        cell = occ.get(tag)
        if not isinstance(cell, dict) or _is_vacuous_occlusion_cell(cell):
            gaps.append(f"occlusion.{tag}")

    clustering = slices.get("clustering") or {}
    if int(clustering.get("p_diff") or 0) == 0:
        gaps.append("clustering.p_diff")

    demo = slices.get("demographic") or {}
    by_cohort = demo.get("by_cohort") or {}
    if len(by_cohort) < 2:
        gaps.append("demographic.by_cohort")

    for key in ("full_corpus_identification", "headline_identification"):
        cell = slices.get(key) or {}
        if isinstance(cell, dict) and _is_vacuous_id_slice(cell):
            gaps.append(key)

    detection = report.get("detection") or {}
    if int(detection.get("fp") or 0) == 0:
        gaps.append("detection.fp")
    if int(detection.get("fn") or 0) == 0:
        gaps.append("detection.fn")

    if not (report.get("failures") or []):
        gaps.append("failures")

    return sorted(gaps)


def _score_face_like_cli(
    record: dict[str, Any],
    manifest: Any,
    *,
    manifest_sha: str,
) -> tuple[str, str]:
    """Score the same way score-face does (occlusion twins from the record)."""
    synth, real = occlusion_inputs_from_record(record, manifest)
    return build_face_reports(
        record,
        manifest,
        score_manifest_sha256=manifest_sha,
        occlusion_pairs_by_tag=synth,
        real_occlusion_pairs_by_tag=real,
        public=False,
    )


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

    # Score once to discover still-vacuous cells, then stamp coverage_gaps into
    # run-record provenance and re-score so the freeze matches score-face (rg-015).
    probe_json, _ = _score_face_like_cli(record, manifest, manifest_sha=manifest_sha)
    gaps = compute_coverage_gaps(json.loads(probe_json))
    record.setdefault("provenance", {})["coverage_gaps"] = gaps
    record = validate_face_run_record(record)
    run_path.write_text(_dumps(record))

    json_doc, md_doc = _score_face_like_cli(record, manifest, manifest_sha=manifest_sha)
    report_json_path.write_text(json_doc)
    report_md_path.write_text(md_doc)
    return manifest_path, run_path, report_json_path, report_md_path, manifest_sha


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a synthetic offline face determinism anchor (VLM-6 F6/F7)."
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
