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

Regeneration is byte-stable: fixed ``fixture_revision`` / ``canonical_timestamp``
defaults (byte-stability sentinels in fixture_* fields — not live git /
wall-clock provenance; VLM6-F-04 / S4-03 / S4-04), sorted JSON keys, synthetic
embeddings derived only from fixed construction constants.
``provenance.manifest_sha256`` and ``provenance.coverage_gaps`` are always
computed at generation time — never hand-stamped (rg-015). Contract fields
``head_sha`` / ``started_at`` are written as null in pin mode.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import tempfile
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
from scripts.eval_harness.promote_atomic import (
    FACE_PROMOTE,
    atomic_promote,
    recover_promote,
    scavenge_orphan_stages,
)
from scripts.eval_harness.report import build_face_reports, occlusion_inputs_from_record

# Shared promote protocol (HARM-02) — face namespace (RV2-03).
_PROMOTE_NS = FACE_PROMOTE
_PROMOTE_JOURNAL = FACE_PROMOTE.journal_name
_PROMOTE_STAGE_PREFIX = FACE_PROMOTE.stage_prefix
# Structural re-exports so tests can assert caption/face share one implementation.
_atomic_promote_core = atomic_promote
_recover_promote_core = recover_promote

# Fixed defaults so two generator runs on the same tree are byte-identical.
# These are BYTE-STABILITY SENTINELS in fixture_* fields, not live git / wall-clock
# provenance (VLM6-F-04 / rg-015). Never written into contract head_sha as if real.
_DEFAULT_CANONICAL_TIMESTAMP = "2026-08-11T00:00:00Z"
_DEFAULT_FIXTURE_REVISION = "0" * 40
# Back-compat names used by tests / CLI.
_DEFAULT_STARTED_AT = _DEFAULT_CANONICAL_TIMESTAMP
_DEFAULT_HEAD_SHA = _DEFAULT_FIXTURE_REVISION
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
# Anonymous GT at a distinct locus for pure stranger-miss (HARM-05 / HARM-01).
_GT_BOX_STRANGER_FN = {"x": 0.7, "y": 0.1, "w": 0.2, "h": 0.2, "source": "iptc"}
# Second locus used when named+anonymous misses share one image (HARM-05 mixed).
_GT_BOX_STRANGER_FN_B = {"x": 0.7, "y": 0.7, "w": 0.2, "h": 0.2, "source": "iptc"}
# VLM6-R2-G-01 / wF4: mixed-y order_degraded trap. Sibling named boxes share x;
# one carries real y, one omits y. Correct per-box key orders (has-y first);
# pre-G-01 whole-image (x, name) collapse reorders by name and is detectable.
# Null-y + detections is now safe (wG2: associate_detections stamps
# geometry_incomplete_gt instead of float(y)); this media still uses faces=[]
# so the freeze isolates labeled_y_missing_images / order_degraded without also
# exercising association incompleteness on the same item.
_GT_BOX_Y_PRESENT = {"x": 0.5, "y": 0.1, "w": 0.2, "h": 0.2, "source": "iptc"}
_GT_BOX_Y_MISSING = {"x": 0.5, "w": 0.2, "h": 0.2, "source": "iptc"}  # no y key
_LANDMARKS = [[0.0, 0.0]] * 5
_DET_SCORE = 0.95

_ALICE = "Alice Example"
_BOB = "Bob Example"
_COHORT_A = "cohort_a"
_COHORT_B = "cohort_b"

# Corpus-level trap inventory (EVAL-03 / VLM6-R2-C-02). Media exist to trip a
# specific formula or freeze-blindness hazard; detection arithmetic is correct
# for the corpus — the sampling frame must disclose deliberate traps.
# Mirrored into run-record provenance.corpus_traps at generation time.
_CORPUS_TRAPS: list[dict[str, Any]] = [
    {
        "media_id": 9,
        "path": "localwp/uploads/stranger-fn-miss.jpg",
        "kind": "HARM-05_pure_stranger_miss",
        "trips": "pre-HARM-01 named-only detection FN formula (HARM-01 / EVAL-13)",
        # Machine-readable: report.py filters on this field (rg-009 — no kind/id match).
        "affects": ["detection_fn"],
        # fn_count (VLM6-PANEL6L-rvE-01): this trap's own contribution to the
        # corpus-wide detection fn, so the report caveat can state trap_fn=N of
        # fn=M instead of declaring it undeclarable. Per-trap only — never a
        # corpus-total denominator (stays correct as traps are added/removed).
        "fn_count": 1,
        "note": (
            "anonymous GT, zero detections; contributes exactly 1 detection FN. "
            "Without this entry pre- and post-HARM-01 fn agree (blind freeze)."
        ),
    },
    {
        "media_id": 10,
        "path": "localwp/uploads/mixed-fn-miss.jpg",
        "kind": "HARM-05_mixed_named_anonymous_miss",
        "trips": "pre-HARM-01 named-only detection FN formula (HARM-01 / EVAL-13)",
        "affects": ["detection_fn"],
        "fn_count": 2,
        "note": (
            "named Alice GT + anonymous GT, zero detections; contributes named FN "
            "plus stranger FN (2 total). Discriminates identity-agnostic vs "
            "named-only recall."
        ),
    },
    {
        "media_id": 11,
        "path": "celebs01/y-missing-mixed-order.jpg",
        "kind": "VLM6-R2-G-01_mixed_y_order_degraded",
        "trips": "labeled_y_missing_images always-0 freeze blindness (VLM6-R2-G-01 residual)",
        "affects": ["identity_ordering"],
        "note": (
            "named box missing y alongside sibling named box with y; order_degraded "
            "observable so the disclosure counter cannot freeze at structural 0."
        ),
    },
]


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
    # HARM-05: unmatched anonymous GT (stranger miss) — population HARM-01 fn counts.
    stranger_fn_box = {**_GT_BOX_STRANGER_FN, "name": None}
    stranger_fn_box_b = {**_GT_BOX_STRANGER_FN_B, "name": None}
    # VLM6-R2-G-01: Bob has real y; Alice omits y — mixed shape, not all-missing.
    y_present_box = {**_GT_BOX_Y_PRESENT, "name": _BOB}
    y_missing_box = {**_GT_BOX_Y_MISSING, "name": _ALICE}
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
            {
                # HARM-05 pure stranger-miss: anonymous GT, zero detections.
                # Pre-HARM-01 fn=missed_gt (named-only) hides this population.
                "path": "localwp/uploads/stranger-fn-miss.jpg",
                "sha256": "3" * 64,
                "media_id": 9,
                "face_count": 1,
                "present_identities": [],
                "base_caption": "",
                "must_right": [],
                "easy_wrong": [],
                "policy": {"recognition_enabled": True},
                "face_boxes": [stranger_fn_box],
                "provenance": {
                    "source": "localwp",
                    "license": "consented",
                    "publishable": False,
                    "note": emb_note,
                },
            },
            {
                # HARM-05 mixed miss: named Alice GT + anonymous GT, zero detections.
                # Discriminates named-only FN (pre-HARM-01) from identity-agnostic FN.
                "path": "localwp/uploads/mixed-fn-miss.jpg",
                "sha256": "4" * 64,
                "media_id": 10,
                "face_count": 2,
                "present_identities": [_ALICE],
                "base_caption": "",
                "must_right": [],
                "easy_wrong": [],
                "policy": {"recognition_enabled": True},
                "face_boxes": [fn_box, stranger_fn_box_b],
                "provenance": {
                    "source": "localwp",
                    "license": "consented",
                    "publishable": False,
                    "note": emb_note,
                },
                "demographic_cohort": _COHORT_A,
            },
            {
                # VLM6-R2-G-01 / wF4: mixed-y order_degraded trap.
                # Named Bob has y; named Alice omits y (sibling shape).
                # Exists so labeled_y_missing_images can be non-zero on the freeze
                # corpus (pre-extension the counter was structurally always 0).
                # faces=[] on the matching run item is deliberate isolation of
                # the order_degraded counter — not a crash dodge. wG2 made
                # null-y + n_det>0 safe (geometry_incomplete stamp); a future
                # trap may add detections without re-introducing TypeError.
                "path": "celebs01/y-missing-mixed-order.jpg",
                "sha256": "5" * 64,
                "media_id": 11,
                "face_count": 2,
                "present_identities": [_ALICE, _BOB],
                "base_caption": "",
                "must_right": [],
                "easy_wrong": [],
                "policy": {"recognition_enabled": True},
                "face_boxes": [y_present_box, y_missing_box],
                "provenance": {
                    "source": "celeb",
                    "license": "public_domain",
                    "publishable": True,
                    "note": (
                        emb_note
                        + "; TRAP VLM6-R2-G-01 mixed-y order_degraded "
                        "(labeled_y_missing_images freeze observability)"
                    ),
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
    fixture_revision: str,
    canonical_timestamp: str,
    # Legacy aliases (map onto fixture sentinels; not written into contract fields).
    head_sha: str | None = None,
    started_at: str | None = None,
) -> dict[str, Any]:
    """Build a validated face_run_record from synthetic vectors only (PROV-01)."""
    fix_rev = head_sha if head_sha is not None else fixture_revision
    can_ts = started_at if started_at is not None else canonical_timestamp
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
        build_face_run_item(
            media_id=9,
            path="localwp/uploads/stranger-fn-miss.jpg",
            model_id=_MODEL_ID,
            embedding_dim=_EMBEDDING_DIM,
            image_size=_IMAGE_SIZE,
            faces=[],  # HARM-05: unmatched anonymous GT
        ),
        build_face_run_item(
            media_id=10,
            path="localwp/uploads/mixed-fn-miss.jpg",
            model_id=_MODEL_ID,
            embedding_dim=_EMBEDDING_DIM,
            image_size=_IMAGE_SIZE,
            faces=[],  # HARM-05: named + anonymous unmatched in one image
        ),
        build_face_run_item(
            media_id=11,
            path="celebs01/y-missing-mixed-order.jpg",
            model_id=_MODEL_ID,
            embedding_dim=_EMBEDDING_DIM,
            image_size=_IMAGE_SIZE,
            faces=[],  # VLM6-R2-G-01: order_degraded trap; faces=[] isolates counter (null-y+dets safe since wG2)
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
        # Byte-stability sentinels — not git/wall-clock contract fields (VLM6-F-04 / S4-04).
        "fixture_revision": fix_rev,
        "canonical_timestamp": can_ts,
        # Never fabricate git SHA or wall-clock into contract fields (rg-015).
        "head_sha": None,
        "started_at": None,
        "leg": "candidate",
        "model_id": _MODEL_ID,
        "embedding_dim": _EMBEDDING_DIM,
        "generator": "scripts.eval_harness.generate_face_determinism_anchor",
        # EVAL-03 / VLM6-R2-C-02: deliberate trap media + which gate each trips.
        "corpus_traps": list(_CORPUS_TRAPS),
        "note": (
            "synthetic dim=8 unit vectors; no real image/embedding (PROV-01); "
            "fixture_revision/canonical_timestamp are byte-stability sentinels "
            "(not git/wall-clock provenance); "
            "F7 multi-regime corpus (2 identities, FP/FN, wrong-name, "
            "occlusion twin, 2 cohorts; HARM-05 unmatched stranger GT + "
            "mixed named/anonymous miss; VLM6-R2-G-01 mixed-y order_degraded "
            "trap (media 11); failures[] declared gap — score-face "
            "hard-exits on counts.failed>0); see provenance.corpus_traps"
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
    """Identification slice vacuous when claim-unit sampling probability π=0 (VLM6-B-05).

    Vacuity is about probe count, not perfect accuracy: a cell with
    ``n_named_probes>0`` and zero errors still *executed* and must not be listed
    as a coverage gap. Keying on fp/fn/wrong_names==0 confused "error path not
    exercised" with "no sampling frame" (AUDIT-07).
    """
    n_probes = slice_doc.get("n_named_probes")
    if n_probes is not None:
        return int(n_probes) == 0
    # Fallback when older report shapes omit n_named_probes: any activity counts.
    activity = (
        int(slice_doc.get("tp") or 0)
        + int(slice_doc.get("fp") or 0)
        + int(slice_doc.get("fn") or 0)
        + int(slice_doc.get("missed_gt") or 0)
    )
    return activity == 0


def compute_coverage_gaps(report: dict[str, Any]) -> list[str]:
    """Derive still-vacuous slice names from a scored face report (rg-015).

    A green face gate proves byte-stable re-score + that named cells execute.
    It does **not** prove ship-ready floors (UNDER-FLOOR/DIRECTIONAL is expected
    on this tiny synthetic corpus). Gaps name cells with π=0 sampling frame —
    not cells whose error counters happen to be zero (VLM6-B-05).
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

    # Detection is vacuous only when no face was compared (tp+fp+fn==0), not when
    # a perfect detector posts fp=0 / fn=0 (VLM6-B-05).
    detection = report.get("detection") or {}
    det_n = (
        int(detection.get("tp") or 0)
        + int(detection.get("fp") or 0)
        + int(detection.get("fn") or 0)
    )
    if det_n == 0:
        gaps.append("detection")

    if not (report.get("failures") or []):
        gaps.append("failures")

    return sorted(gaps)


class CoverageGapsUnderDeclaredError(RuntimeError):
    """Declared provenance.coverage_gaps omits a still-vacuous computed gap (VLM6-B-04)."""


def validate_coverage_gaps(
    report: dict[str, Any],
    *,
    declared: list[str] | None = None,
) -> list[str]:
    """Runtime guard: declared gaps must cover every still-vacuous computed cell.

    Under-declaring (dropping a still-vacuous gap) raises
    ``CoverageGapsUnderDeclaredError``. Over-declaring a live cell also fails —
    the freeze must not claim a live cell is empty.
    """
    computed = compute_coverage_gaps(report)
    if declared is None:
        declared = list((report.get("provenance") or {}).get("coverage_gaps") or [])
    declared_list = list(declared)
    missing = sorted(set(computed) - set(declared_list))
    extra = sorted(set(declared_list) - set(computed))
    if missing or extra:
        raise CoverageGapsUnderDeclaredError(
            f"coverage_gaps mismatch: missing_declared={missing} extra_declared={extra} "
            f"computed={computed} declared={declared_list}"
        )
    return computed


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


def _recover_promote(dest_dir: Path) -> None:
    """Face-namespaced recover (shared impl — HARM-02 / RV2-03)."""
    recover_promote(dest_dir, _PROMOTE_NS)


def _atomic_promote(src_dir: Path, dest_dir: Path, names: list[str]) -> None:
    """Face-namespaced set-atomic promote (shared impl — HARM-02 / RV2-03)."""
    atomic_promote(src_dir, dest_dir, names, _PROMOTE_NS)


def write_face_anchor(
    *,
    out_dir: Path,
    stem: str,
    manifest_stem: str,
    fixture_revision: str = _DEFAULT_FIXTURE_REVISION,
    canonical_timestamp: str = _DEFAULT_CANONICAL_TIMESTAMP,
    # Back-compat: older callers pass head_sha/started_at as byte-stability sentinels.
    head_sha: str | None = None,
    started_at: str | None = None,
) -> tuple[Path, Path, Path, Path, str]:
    """Generate manifest + run-record + scored face-report pair.

    Builds the full set in a temporary directory, validates coverage_gaps and
    cross-file hashes, then promotes the named set via journaled stage install
    (VLM6-F-05 / VLM6-B-04 / rg-002 / S4-02). After return (or crash + recover)
    the destination is fully old or fully new — never a mixed pairing.

    Returns (manifest_path, run_path, report_json, report_md, manifest_sha).
    """
    # Reclaim orphan stage dirs left by crashes before journal write (RV2-07).
    scavenge_orphan_stages(out_dir, _PROMOTE_NS)

    fix_rev = head_sha if head_sha is not None else fixture_revision
    can_ts = started_at if started_at is not None else canonical_timestamp

    man_name = f"{manifest_stem}.json"
    run_name = f"{stem}.json"
    report_json_name = f"{stem}-face-report.json"
    report_md_name = f"{stem}-face-report.md"

    with tempfile.TemporaryDirectory(prefix="vlm-face-anchor-") as tmp:
        tmp_dir = Path(tmp)
        raw_manifest = build_synthetic_face_manifest()
        (tmp_dir / man_name).write_text(_dumps(raw_manifest))

        # Load through the real loader so sha matches score-time computation (rg-015).
        # Metadata-only: synthetic anchor has no image files; scoring uses roster/face_count/tags only.
        manifest = load_manifest(str(tmp_dir / man_name), skip_hash_verification=True)
        # Computed at generation time from the loaded manifest — never hand-stamped.
        manifest_sha = _manifest_sha(manifest)

        record = build_face_anchor_run_record(
            manifest_sha256=manifest_sha,
            fixture_revision=fix_rev,
            canonical_timestamp=can_ts,
        )

        # Score once to discover still-vacuous cells, then stamp coverage_gaps into
        # run-record provenance and re-score so the freeze matches score-face (rg-015).
        probe_json, _ = _score_face_like_cli(record, manifest, manifest_sha=manifest_sha)
        probe_report = json.loads(probe_json)
        gaps = compute_coverage_gaps(probe_report)
        record.setdefault("provenance", {})["coverage_gaps"] = gaps
        record = validate_face_run_record(record)
        (tmp_dir / run_name).write_text(_dumps(record))

        json_doc, md_doc = _score_face_like_cli(record, manifest, manifest_sha=manifest_sha)
        final_report = json.loads(json_doc)
        # Runtime guard: declared gaps must match computed (VLM6-B-04 / TEST-15).
        validate_coverage_gaps(final_report, declared=gaps)
        # Ensure the scored report also carries the declared list.
        final_report.setdefault("provenance", {})["coverage_gaps"] = gaps
        json_doc = _dumps(final_report) if "coverage_gaps" not in json.loads(json_doc).get("provenance", {}) else json_doc
        # Re-serialize if we had to stamp gaps onto the report.
        if (json.loads(json_doc).get("provenance") or {}).get("coverage_gaps") != gaps:
            final_report["provenance"]["coverage_gaps"] = gaps
            json_doc = json.dumps(final_report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"

        (tmp_dir / report_json_name).write_text(json_doc)
        (tmp_dir / report_md_name).write_text(md_doc)

        # Integrity: re-load and confirm sha + gap agreement before promote.
        reloaded = json.loads((tmp_dir / run_name).read_text())
        if reloaded["provenance"]["manifest_sha256"] != manifest_sha:
            raise RuntimeError("face anchor integrity check failed: manifest_sha256 drift")
        validate_coverage_gaps(json.loads((tmp_dir / report_json_name).read_text()))

        _atomic_promote(tmp_dir, out_dir, [man_name, run_name, report_json_name, report_md_name])

    return (
        out_dir / man_name,
        out_dir / run_name,
        out_dir / report_json_name,
        out_dir / report_md_name,
        manifest_sha,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a synthetic offline face determinism anchor (VLM-6 F6/F7).")
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
        "--fixture-revision",
        default=_DEFAULT_FIXTURE_REVISION,
        help="provenance.fixture_revision byte-stability sentinel (default: 40 zero hex)",
    )
    parser.add_argument(
        "--canonical-timestamp",
        default=_DEFAULT_CANONICAL_TIMESTAMP,
        help=f"provenance.canonical_timestamp sentinel (default: {_DEFAULT_CANONICAL_TIMESTAMP})",
    )
    # Back-compat aliases for older callers / tests (S4-03: demote fabricated head_sha).
    parser.add_argument(
        "--head-sha",
        default=None,
        help="(legacy) maps to --fixture-revision when set; prefer --fixture-revision "
        "(does NOT write provenance.head_sha — that contract field is null in pin mode)",
    )
    parser.add_argument(
        "--started-at",
        default=None,
        help="(legacy) maps to --canonical-timestamp when set; prefer --canonical-timestamp "
        "(does NOT write provenance.started_at — that contract field is null in pin mode)",
    )
    args = parser.parse_args(argv)

    fixture_revision = args.fixture_revision
    canonical_timestamp = args.canonical_timestamp
    if args.head_sha is not None:
        fixture_revision = args.head_sha
    if args.started_at is not None:
        canonical_timestamp = args.started_at

    manifest_path, run_path, report_json, report_md, manifest_sha = write_face_anchor(
        out_dir=args.out_dir,
        stem=args.stem,
        manifest_stem=args.manifest_stem,
        fixture_revision=fixture_revision,
        canonical_timestamp=canonical_timestamp,
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
