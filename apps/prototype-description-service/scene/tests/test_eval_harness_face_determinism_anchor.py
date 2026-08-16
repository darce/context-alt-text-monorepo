"""Committed synthetic face determinism anchor (VLM-6 F6/F7 / B-06).

Pins the offline face freeze under docs/tasks/vlm/bakeoff-results/ and drives
the shipped ``score-face --check-determinism --expect-report`` gate:

  - generator byte-stability against committed artifacts
  - report-side corruption → ANCHOR_MISMATCH (TEST-15)
  - run-record-side embedding corruption → ANCHOR_MISMATCH (TEST-15)
  - same run-record corruption without --expect-report → silent pass (DBG-11)
  - clean freeze → green with matches --expect-report
  - F7: coverage_gaps declare every still-vacuous slice (AUDIT-07)
  - F7: newly-live cells go red when corrupted; old 1-id corpus cannot (DBG-11)
  - F7-01: ANCHOR_MISMATCH artifact lands in out/, never under bakeoff-results/

PROV-01: embeddings are synthetic dim=8 unit vectors; no real face data.
"""

from __future__ import annotations

import hashlib
import json
import math
import tempfile
from pathlib import Path

import pytest

from scripts.eval_harness.cli import (
    OUT_DIR,
    _check_face_determinism_cross_process,
    _determinism_artifact_dir,
    _manifest_sha,
    main,
)
from scripts.eval_harness.generate_face_determinism_anchor import (
    CoverageGapsUnderDeclaredError,
    _DEFAULT_MANIFEST_STEM,
    _DEFAULT_STEM,
    _EMBEDDING_DIM,
    _is_vacuous_id_slice,
    compute_coverage_gaps,
    validate_coverage_gaps,
    write_face_anchor,
)
from scripts.eval_harness.manifest import load_manifest
from scripts.eval_harness.report import build_face_reports, occlusion_inputs_from_record

_REPO_ROOT = Path(__file__).resolve().parents[4]
_SERVICE_ROOT = Path(__file__).resolve().parents[2]
_ANCHOR_DIR = _REPO_ROOT / "docs" / "tasks" / "vlm" / "bakeoff-results"
_STEM = _DEFAULT_STEM
_MANIFEST_STEM = _DEFAULT_MANIFEST_STEM
_MANIFEST = _ANCHOR_DIR / f"{_MANIFEST_STEM}.json"
_RUN = _ANCHOR_DIR / f"{_STEM}.json"
_REPORT_JSON = _ANCHOR_DIR / f"{_STEM}-face-report.json"
_REPORT_MD = _ANCHOR_DIR / f"{_STEM}-face-report.md"

# File digests of the committed face quadruple — update only when intentionally regenerating.
# Regenerated for VLM6-R2-06: the face markdown carried no fetch-manifest provenance at
# all, so corpus drift was undisclosed on the identity path. Only the .md digest moved —
# manifest, run-record and report JSON are byte-identical, which is the evidence that
# disclosure changed and scoring did not.
# Regenerated fx7 (this lane's branch): head_sha 40-zeros → null + fixture_revision;
# coverage_gaps predicate keys on probe count (perfect ID/detection not listed).
# Manifest digest unchanged (corpus body byte-identical); run/report/md moved.
# Regenerated hx1 (wave-C regen) after gx4 S4-04 pin-mode started_at:null +
# S4-05 MD head_sha null rendering. Manifest digest still unchanged.
# Regenerated fx5 (wave-B): HARM-05 corpus extension (unmatched stranger GT + mixed
# named/anonymous miss) + HARM-01/HARM-09 published metrics (fn folds stranger
# misses; slices.unknown_rejection.missed_stranger_gt). Digests taken from
# sha256sum of generator output — never hand-typed.
# Regenerated wF4: media 11 mixed-y order_degraded trap (VLM6-R2-G-01) +
# provenance.corpus_traps disclosure (VLM6-R2-C-02). Manifest + run digests moved;
# report digests intentionally NOT updated by wF4 (regen stage owns report freezes).
# Regenerated wI2 (Wave I face regen): absorb wF4 corpus counts/traps, wG1
# identity_ordering, wG2 detection.fn/recall (Alice null-y excluded), wH1
# geometry_incomplete_* / association_complete + corrected detection sampling_frame.
# Report digests only — man+run pins unchanged (wF4 inputs).
# Regenerated VLM6-R2-C-02: corpus_traps[].affects + fixture-local detection
# caveat in the face MD. Manifest digest unchanged (corpus body identical);
# run/report/md moved (affects stamp + caveat line).
# Regenerated 2026-08-15 (VLM6-R2-C-02 wording): caveat now states
# "fn=M includes misses from N deliberate trap media" instead of "N of fn=M
# come from" (N is trap MEDIA, not FN share; rg-015). Media 9 note dropped
# the stale "1 of 4" denominator. Manifest digest unchanged (corpus body
# identical); run/report/md moved. Digests from sha256sum of generator output.
_FROZEN_DIGESTS = {
    _MANIFEST.name: "32eff309b37822deb4474ca05dac4b0343e7a2378e4d25ab013020b5c565b5bd",
    _RUN.name: "99c108a74064df76bca7101bb066b9a1a36ea50c7c85d99fddf4f86d24fbd202",
    _REPORT_JSON.name: "9755611fdf8002e11c0e642775919a75257ea8bdf57c8e70ab29f135afca9016",
    _REPORT_MD.name: "851039608dccb4c18302c89b0b4284decd2464ae2a6e26e10aea3af0f4d9489e",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _unit(values: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return [float(v) / norm for v in values]


def _live_slice_names(report: dict) -> set[str]:
    """Slice keys that currently execute (non-vacuous) under compute_coverage_gaps rules."""
    all_candidates = {
        "occlusion.masked",
        "occlusion.sunglasses",
        "occlusion.occlusion_other",
        "clustering.p_diff",
        "demographic.by_cohort",
        "full_corpus_identification",
        "headline_identification",
        "detection",  # whole detection cell (VLM6-B-05: not per-error-path)
        "failures",
    }
    gaps = set(compute_coverage_gaps(report))
    return all_candidates - gaps


# Post-HARM-01 detection literals from the committed freeze (wI2).
# Must stay handwritten — reading them back from the freeze cannot detect a
# laundered regen (VLM6-R2-C-01). Current freeze: tp=6 fp=1 fn=5 → 6/7, 6/11.
_PINNED_DETECTION_TP = 6
_PINNED_DETECTION_FP = 1
_PINNED_DETECTION_FN = 5
_PINNED_DETECTION_PRECISION = 0.8571428571428571
_PINNED_DETECTION_RECALL = 0.5454545454545454


def _oracle_detection_from_assignment(assignment: object) -> dict[str, float | int]:
    """Independent detection counts. Does not call ``_detection_from_assignment``.

    Invariant (HARM-01 / EVAL-16): ``fn == missed_gt + missed_stranger_gt``.
    TP = IoU-accepted pairs. FP = unmatched detections.
    """
    by_media = getattr(assignment, "association_by_media")
    tp = sum(len(assoc.pairs) for assoc in by_media.values())
    fp = int(getattr(assignment, "false_detections"))
    missed_gt = int(getattr(assignment, "missed_gt"))
    missed_stranger_gt = int(getattr(assignment, "missed_stranger_gt", 0) or 0)
    fn = missed_gt + missed_stranger_gt
    precision = (tp / (tp + fp)) if (tp + fp) else 0.0
    recall = (tp / (tp + fn)) if (tp + fn) else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall}


def _anchor_assignment():  # type: ignore[no-untyped-def]
    """Score the committed face man+run into an AssignmentResult (no report formula)."""
    from scripts.eval_harness.face_assignment import score_face_assignment
    from scripts.eval_harness.report import _entries_as_dicts, _entry_index, _gt_by_media

    manifest = load_manifest(str(_MANIFEST), skip_hash_verification=True)
    record = json.loads(_RUN.read_text())
    entries, _, _ = _entries_as_dicts(manifest)
    entry_by_id = _entry_index(entries)
    gt_by_media = _gt_by_media(entries)
    scoreable = []
    for item in record.get("items") or []:
        media_id = int(item["media_id"])
        if entry_by_id.get(media_id) is None:
            continue
        if item.get("error"):
            continue
        scoreable.append(item)
    return score_face_assignment(scoreable, gt_by_media)


@pytest.mark.parametrize("name,expected", list(_FROZEN_DIGESTS.items()))
def test_committed_face_anchor_digests_match_frozen(name: str, expected: str) -> None:
    path = _ANCHOR_DIR / name
    assert path.is_file(), f"missing committed face anchor artifact: {path}"
    assert _sha256(path) == expected


def test_face_generator_regenerates_byte_identical_committed_anchor(tmp_path: Path) -> None:
    """Generator is the source of truth — re-run must match the freeze byte-for-byte."""
    man_path, run_path, report_json, report_md, manifest_sha = write_face_anchor(
        out_dir=tmp_path,
        stem=_STEM,
        manifest_stem=_MANIFEST_STEM,
        head_sha="0" * 40,
        started_at="2026-08-11T00:00:00Z",
    )
    # Metadata-only: synthetic face anchor has no image files; sha over metadata only.
    expected_sha = _manifest_sha(load_manifest(str(_MANIFEST), skip_hash_verification=True))
    assert manifest_sha == expected_sha
    # Prefix of generation-time sha over the wF4 extended corpus (HARM-05 + G-01 trap).
    # Not a digest pin — full digest lives in _FROZEN_DIGESTS[_MANIFEST.name].
    assert manifest_sha.startswith("02003e25")
    assert man_path.read_bytes() == _MANIFEST.read_bytes()
    assert run_path.read_bytes() == _RUN.read_bytes()
    # wI2 regenerated report freezes from the generator; man+run remain wF4 pins.
    assert report_json.read_bytes() == _REPORT_JSON.read_bytes()
    assert report_md.read_bytes() == _REPORT_MD.read_bytes()


def test_face_run_record_is_synthetic_dim8_no_real_embeddings() -> None:
    """PROV-01: committed face run-record holds only synthetic dim=8 vectors."""
    record = json.loads(_RUN.read_text())
    assert record["kind"] == "face_run_record"
    assert record["provenance"]["embedding_dim"] == _EMBEDDING_DIM
    assert record["provenance"]["model_id"] == "synthetic-face-anchor"
    # Metadata-only: provenance sha vs synthetic face manifest; never opens image bytes.
    assert record["provenance"]["manifest_sha256"] == _manifest_sha(
        load_manifest(str(_MANIFEST), skip_hash_verification=True)
    )
    assert len(record["items"]) >= 7  # F7 multi-regime corpus
    for item in record["items"]:
        assert item["embedding_dim"] == _EMBEDDING_DIM
        for face in item.get("faces") or []:
            assert len(face["embedding"]) == _EMBEDDING_DIM


def test_face_anchor_corpus_includes_unmatched_stranger_gt() -> None:
    """HARM-05: corpus must include unmatched anonymous GT (HARM-01 fn population).

    Pre-extension freeze had only a *matched* stranger + a *named* miss — so
    ``fn = missed_gt + missed_stranger_gt`` and ``fn = missed_gt`` agreed, and
    regenerating could not detect a HARM-01 regression (TEST-15 / EVAL-13).
    """
    from scripts.eval_harness.generate_face_determinism_anchor import (
        build_face_anchor_run_record,
        build_synthetic_face_manifest,
    )

    raw = build_synthetic_face_manifest()
    # Pair media_id → detection count from the run-record builder.
    record = build_face_anchor_run_record(
        manifest_sha256="0" * 64,
        fixture_revision="0" * 40,
        canonical_timestamp="2026-08-11T00:00:00Z",
    )
    det_by_media = {int(i["media_id"]): len(i.get("faces") or []) for i in record["items"]}

    pure_stranger_miss = 0
    mixed_named_and_stranger_miss = 0
    for entry in raw["entries"]:
        mid = int(entry["media_id"])
        boxes = list(entry.get("face_boxes") or [])
        anon = [b for b in boxes if not b.get("name")]
        named = [b for b in boxes if b.get("name")]
        n_det = det_by_media.get(mid, 0)
        if anon and n_det == 0 and not named:
            pure_stranger_miss += 1
        if anon and named and n_det == 0:
            mixed_named_and_stranger_miss += 1
    assert pure_stranger_miss >= 1, "need ≥1 pure unmatched-anonymous-GT image (HARM-05)"
    assert mixed_named_and_stranger_miss >= 1, (
        "need ≥1 image mixing named-unmatched + anonymous-unmatched (HARM-05)"
    )


def test_face_anchor_corpus_includes_mixed_y_order_degraded_trap() -> None:
    """VLM6-R2-G-01 / wF4: ≥1 image with named missing-y + sibling named with-y.

    Pre-extension every named box had y, so ``labeled_y_missing_images`` was
    structurally 0 on the freeze corpus — the same class of blindness that let
    G-01 ship green (DBG-11 / TEST-15). Shape must be *mixed* (not all-missing):
    the original bug collapsed the whole image to ``(x, name)`` whenever *any*
    named box lacked y, discarding real y on siblings.
    """
    from scripts.eval_harness.face_metrics import labeled_order, named_box_name
    from scripts.eval_harness.generate_face_determinism_anchor import (
        build_face_anchor_run_record,
        build_synthetic_face_manifest,
    )

    raw = build_synthetic_face_manifest()
    record = build_face_anchor_run_record(
        manifest_sha256="0" * 64,
        fixture_revision="0" * 40,
        canonical_timestamp="2026-08-11T00:00:00Z",
    )
    run_ids = {int(i["media_id"]) for i in record["items"]}

    mixed = 0
    for entry in raw["entries"]:
        mid = int(entry["media_id"])
        assert mid in run_ids, f"manifest media_id={mid} missing from run-record (mutual consistency)"
        boxes = list(entry.get("face_boxes") or [])
        named_with_y = 0
        named_missing_y = 0
        for b in boxes:
            if named_box_name(b) is None:
                continue
            if b.get("y") is None:
                named_missing_y += 1
            else:
                named_with_y += 1
        if named_with_y >= 1 and named_missing_y >= 1:
            lo = labeled_order(boxes)
            assert lo.order_degraded is True
            assert lo.y_missing_count >= 1
            mixed += 1
    assert mixed >= 1, (
        "need ≥1 image with named box missing y + sibling named box with y "
        "(VLM6-R2-G-01 freeze observability)"
    )


def test_labeled_y_missing_constant_zero_goes_red_on_extended_corpus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TEST-15 / wF4 acceptance: constant-0 aggregation must diverge after extension.

    Pre-extension (Task 1 step 4): live counter was 0, so wiring aggregation to
    constant 0 was invisible — freeze stayed green under the regression. Against
    the extended corpus the live counter is ≥1; the same mutation yields 0 and
    is therefore freeze-detectable (the whole point of this lane).
    """
    from scripts.eval_harness.face_metrics import LabeledOrderResult, labeled_order
    from scripts.eval_harness.generate_face_determinism_anchor import (
        build_synthetic_face_manifest,
    )
    from scripts.eval_harness import report as report_mod
    from scripts.eval_harness.report import score_run_record

    raw = build_synthetic_face_manifest()
    entries = list(raw["entries"])
    items = [
        {
            "media_id": e["media_id"],
            "path": e["path"],
            "model_id": "synthetic-face-anchor",
            "describe": {"alt_text_draft": "placeholder"},
            "identity_ordering": "positional",
            "image_width": 100,
            "image_height": 100,
        }
        for e in entries
    ]
    record = {
        "kind": "run_record",
        "schema_version": 1,
        "items": items,
        "provenance": {
            "manifest_sha256": "0" * 64,
            "model_id": "synthetic-face-anchor",
            "leg": "candidate",
        },
    }

    live = score_run_record(record, entries)["faces"]["identity_ordering"]
    live_n = int(live["labeled_y_missing_images"])
    assert live_n >= 1, (
        f"extended corpus must make labeled_y_missing_images non-zero; got {live_n} "
        "(trap media missing or y not actually omitted)"
    )
    assert live.get("labeled_y_missing_paths"), "paths must name the degraded image(s)"

    real_lo = labeled_order

    def _blind_constant_zero(face_boxes):  # type: ignore[no-untyped-def]
        """Regression shape: strip order_degraded (constant-0 counter)."""
        result = real_lo(face_boxes)
        return LabeledOrderResult(
            names=result.names, y_missing_count=0, order_degraded=False
        )

    monkeypatch.setattr(report_mod, "labeled_order", _blind_constant_zero)
    blind = score_run_record(record, entries)["faces"]["identity_ordering"]
    blind_n = int(blind["labeled_y_missing_images"])
    assert blind_n == 0, "mutation must force counter to 0"
    assert blind_n != live_n, (
        f"constant-0 mutation still matches live ({live_n}) — freeze cannot see "
        "labeled_y_missing regressions (TEST-15 blindness not closed)"
    )


def test_corpus_traps_disclose_deliberate_trap_media() -> None:
    """VLM6-R2-C-02 corpus half: trap media inventory on the run-record (EVAL-03).

    detection-recall is depressed by deliberate HARM-05 / G-01 trap entries.
    Operators need the sampling frame (which media, which gate) — arithmetic
    stays correct for the corpus; do not remove traps or change detection math.
    """
    from scripts.eval_harness.generate_face_determinism_anchor import (
        _CORPUS_TRAPS,
        build_face_anchor_run_record,
        build_synthetic_face_manifest,
    )

    raw = build_synthetic_face_manifest()
    record = build_face_anchor_run_record(
        manifest_sha256="0" * 64,
        fixture_revision="0" * 40,
        canonical_timestamp="2026-08-11T00:00:00Z",
    )
    traps = list((record.get("provenance") or {}).get("corpus_traps") or [])
    assert traps, "provenance.corpus_traps must disclose deliberate trap media"
    # Generator constant and run-record stamp must agree (single source).
    assert traps == list(_CORPUS_TRAPS)

    by_id = {int(t["media_id"]): t for t in traps}
    for required_id, kind_substr in (
        (9, "HARM-05"),
        (10, "HARM-05"),
        (11, "VLM6-R2-G-01"),
    ):
        assert required_id in by_id, f"trap inventory missing media_id={required_id}"
        t = by_id[required_id]
        assert kind_substr in str(t.get("kind") or ""), t
        assert t.get("trips"), f"media {required_id} must name the gate/formula it trips"
        assert t.get("path"), f"media {required_id} must name its path"
    assert by_id[9].get("affects") == ["detection_fn"]
    assert by_id[10].get("affects") == ["detection_fn"]
    assert by_id[11].get("affects") == ["identity_ordering"]

    # Every disclosed trap media must exist in the manifest.
    man_ids = {int(e["media_id"]) for e in raw["entries"]}
    for t in traps:
        assert int(t["media_id"]) in man_ids, f"trap media_id={t['media_id']} not in manifest"

    # Committed run-record must carry the same inventory (not just the builder).
    committed = json.loads(_RUN.read_text())
    committed_traps = list((committed.get("provenance") or {}).get("corpus_traps") or [])
    assert {int(t["media_id"]) for t in committed_traps} >= {9, 10, 11}


def test_fixture_local_detection_caveat_present_and_disappears_without_affects() -> None:
    """VLM6-R2-C-02 / TEST-15: published MD caveat must be able to go red.

    Presence-only is rejected: re-render the committed run after stripping
    ``affects`` and the fixture-local line must vanish. A real corpus with no
    ``detection_fn`` traps must not grow a phantom caveat.
    """
    md = _REPORT_MD.read_text()
    assert "fixture-local detection frame" in md
    assert "recall is NOT a population estimate" in md
    assert "9 `localwp/uploads/stranger-fn-miss.jpg`" in md
    assert "10 `localwp/uploads/mixed-fn-miss.jpg`" in md
    assert "fn=5 includes misses from 2 deliberate trap media" in md
    # Defect pin: N is trap MEDIA. "{n} of fn=" reads as an FN share (rg-015).
    assert "2 of fn=" not in md
    assert "the FN share attributable to them is not derivable from this table" in md
    assert "synthetic determinism anchor (11 images)" in md

    record = json.loads(_RUN.read_text())
    traps = list((record.get("provenance") or {}).get("corpus_traps") or [])
    assert traps, "committed run must disclose corpus_traps"

    manifest = load_manifest(str(_MANIFEST), skip_hash_verification=True)
    synth, real = occlusion_inputs_from_record(record, manifest)
    # Live renderer (not just the frozen MD) must emit the trap-media wording
    # so a "N of fn=M" regression goes red (TEST-15).
    _json_doc, live_md = build_face_reports(
        record,
        manifest,
        score_manifest_sha256=_manifest_sha(manifest),
        occlusion_pairs_by_tag=synth,
        real_occlusion_pairs_by_tag=real,
        public=False,
    )
    assert "fn=5 includes misses from 2 deliberate trap media" in live_md
    assert "2 of fn=" not in live_md
    assert "the FN share attributable to them is not derivable from this table" in live_md

    for trap in traps:
        trap.pop("affects", None)
    record["provenance"]["corpus_traps"] = traps
    _json_doc, stripped_md = build_face_reports(
        record,
        manifest,
        score_manifest_sha256=_manifest_sha(manifest),
        occlusion_pairs_by_tag=synth,
        real_occlusion_pairs_by_tag=real,
        public=False,
    )
    assert "fixture-local detection frame" not in stripped_md
    assert "NOT a population estimate" not in stripped_md
    # Detection numbers themselves stay; only the caveat is gated on affects.
    assert "precision: 0.857 recall: 0.545 (tp=6 fp=1 fn=5" in stripped_md
    # Committed freeze still has the caveat (control must not rewrite it).
    assert "fixture-local detection frame" in _REPORT_MD.read_text()


def test_pre_harm01_detection_formula_goes_red_on_extended_freeze(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HARM-05 / TEST-15: pre-HARM-01 named-only FN must under-count post formula.

    Compares live post-HARM-01 vs live pre-HARM-01 on the committed man+run
    (not the report freeze). Report freezes may lag a corpus-extension lane
    (wF4) until the regeneration stage lands; live-vs-live is the durable
    discrimination. Freeze is still checked for the stranger-miss population
    so a freeze that never had HARM-05 stays vacuous-red.

    Watches the assertion fail: if the corpus again lacks unmatched stranger GT,
    pre- and post-HARM-01 formulas agree and this control goes green falsely.
    """
    from scripts.eval_harness import report as report_mod

    def _pre_harm01_detection(assignment):  # type: ignore[no-untyped-def]
        tp = sum(len(a.pairs) for a in assignment.association_by_media.values())
        fp = int(assignment.false_detections)
        # Pre-HARM-01: named misses only — stranger misses invisible to detection.
        fn = int(assignment.missed_gt)
        precision = (tp / (tp + fp)) if (tp + fp) else 0.0
        recall = (tp / (tp + fn)) if (tp + fn) else 0.0
        return {"precision": precision, "recall": recall, "tp": tp, "fp": fp, "fn": fn}

    freeze = json.loads(_REPORT_JSON.read_text())
    # Freeze must itself exercise the stranger-miss population (else control is vacuous).
    unk = (freeze.get("slices") or {}).get("unknown_rejection") or {}
    assert int(unk.get("missed_stranger_gt") or 0) >= 1, (
        "committed freeze has no missed_stranger_gt — corpus extension missing "
        "or freeze not regenerated (HARM-05 vacuity)"
    )

    manifest = load_manifest(str(_MANIFEST), skip_hash_verification=True)
    record = json.loads(_RUN.read_text())
    synth, real = occlusion_inputs_from_record(record, manifest)
    sha = _manifest_sha(manifest)
    post_doc, _ = build_face_reports(
        record,
        manifest,
        score_manifest_sha256=sha,
        occlusion_pairs_by_tag=synth,
        real_occlusion_pairs_by_tag=real,
        public=False,
    )
    post = json.loads(post_doc)
    post_fn = int((post.get("detection") or {}).get("fn") or 0)
    # Live corpus must still carry stranger misses (not only a stale freeze stamp).
    live_unk = (post.get("slices") or {}).get("unknown_rejection") or {}
    assert int(live_unk.get("missed_stranger_gt") or 0) >= 1

    monkeypatch.setattr(report_mod, "_detection_from_assignment", _pre_harm01_detection)
    pre_doc, _ = build_face_reports(
        record,
        manifest,
        score_manifest_sha256=sha,
        occlusion_pairs_by_tag=synth,
        real_occlusion_pairs_by_tag=real,
        public=False,
    )
    pre = json.loads(pre_doc)
    pre_fn = int((pre.get("detection") or {}).get("fn") or 0)
    # Discrimination: named-only FN under-counts vs identity-agnostic live score.
    assert pre_fn < post_fn, (
        f"pre-HARM-01 fn={pre_fn} did not under-count post live fn={post_fn}; "
        "corpus does not discriminate HARM-01 (TEST-15)"
    )
    assert pre["detection"] != post["detection"], (
        "pre-HARM-01 re-score matched post detection — regression undetectable"
    )


def test_detection_oracle_agrees_with_live_and_pins_absolute_counts() -> None:
    """VLM6-R2-C-01: independent oracle must match live; freeze counts are literals.

    The HARM-05 pin only proves pre_fn < freeze.fn against a named-only mutant.
    Any other identity-agnostic-but-wrong formula can launder itself by
    regenerating the freeze. Two independent computations must agree, and the
    post-HARM-01 counts must be pinned as source literals (not read from the
    freeze at runtime).
    """
    from scripts.eval_harness.report import _detection_from_assignment

    assignment = _anchor_assignment()
    oracle = _oracle_detection_from_assignment(assignment)
    live = _detection_from_assignment(assignment)
    live_core = {k: live[k] for k in oracle}
    assert live_core == oracle, (
        f"oracle {oracle} != live _detection_from_assignment {live_core}"
    )

    # Absolute pins: handwritten literals from the current committed freeze.
    assert oracle["tp"] == _PINNED_DETECTION_TP
    assert oracle["fp"] == _PINNED_DETECTION_FP
    assert oracle["fn"] == _PINNED_DETECTION_FN
    assert oracle["precision"] == _PINNED_DETECTION_PRECISION
    assert oracle["recall"] == _PINNED_DETECTION_RECALL
    assert live["tp"] == 6
    assert live["fp"] == 1
    assert live["fn"] == 5
    assert live["precision"] == 0.8571428571428571
    assert live["recall"] == 0.5454545454545454

    freeze = json.loads(_REPORT_JSON.read_text())["detection"]
    assert freeze["tp"] == 6
    assert freeze["fp"] == 1
    assert freeze["fn"] == 5
    assert freeze["precision"] == 0.8571428571428571
    assert freeze["recall"] == 0.5454545454545454


def test_detection_oracle_goes_red_on_wrong_identity_agnostic_formula(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """VLM6-R2-C-01 / TEST-15: fn = missed_gt + missed_stranger_gt + 1 must fail.

    Oracle is computed *after* the monkeypatch. If the oracle secretly called
    ``_detection_from_assignment`` it would pick up +1 and this probe would
    stay green — that is the independence check.
    """
    from scripts.eval_harness import report as report_mod

    assignment = _anchor_assignment()

    def _wrong_plus_one(assignment_arg):  # type: ignore[no-untyped-def]
        tp = sum(len(a.pairs) for a in assignment_arg.association_by_media.values())
        fp = int(assignment_arg.false_detections)
        fn = (
            int(assignment_arg.missed_gt)
            + int(getattr(assignment_arg, "missed_stranger_gt", 0) or 0)
            + 1
        )
        precision = (tp / (tp + fp)) if (tp + fp) else 0.0
        recall = (tp / (tp + fn)) if (tp + fn) else 0.0
        return {"precision": precision, "recall": recall, "tp": tp, "fp": fp, "fn": fn}

    monkeypatch.setattr(report_mod, "_detection_from_assignment", _wrong_plus_one)
    oracle = _oracle_detection_from_assignment(assignment)
    mutated = report_mod._detection_from_assignment(assignment)
    mutated_core = {k: mutated[k] for k in oracle}
    assert mutated_core != oracle, (
        "oracle agreed with fn=missed_gt+missed_stranger_gt+1 — "
        "oracle is not independent (likely calling _detection_from_assignment)"
    )
    assert int(mutated["fn"]) == int(oracle["fn"]) + 1


def test_published_detection_recall_is_fixture_local_not_a_population_estimate() -> None:
    """VLM6-R2-C-02: detection recall is not a population estimate.

    Frame = all complete GT boxes on the synthetic multi-regime fixture.
    Media 9 and 10 are deliberate TEST-15 stranger-miss levers (HARM-05);
    they depress recall by corpus construction, not a model change.
    detection-recall (all complete GT) and headline missed_gt (named-only)
    are different frames — do not read them as the same measurement.
    Numbers are unchanged; this is a labelling pin.
    """
    freeze = json.loads(_REPORT_JSON.read_text())
    det = freeze["detection"]
    assert det["tp"] == 6
    assert det["fp"] == 1
    assert det["fn"] == 5
    assert det["precision"] == 0.8571428571428571
    assert det["recall"] == 0.5454545454545454
    frame = str(det.get("sampling_frame") or "")
    assert frame, "detection must publish a sampling_frame"
    assert "all_gt_boxes" in frame
    assert "missed_stranger_gt" in frame

    md = _REPORT_MD.read_text()
    # Published rounded display — do not change these numbers (C-02).
    assert "precision: 0.857 recall: 0.545 (tp=6 fp=1 fn=5" in md
    assert "detection-recall: 0.545" in md
    assert "missed_gt=2" in md

    committed = json.loads(_RUN.read_text())
    traps = list((committed.get("provenance") or {}).get("corpus_traps") or [])
    by_id = {int(t["media_id"]): t for t in traps}
    for mid in (9, 10):
        assert mid in by_id, f"media {mid} must be a disclosed TEST-15 stranger-miss lever"
        assert "HARM-05" in str(by_id[mid].get("kind") or "")

    couple = (freeze.get("gate_proposal") or {}).get("identification_detection_coupling") or {}
    # Two frames: detection-recall is all complete GT; missed_gt is named-only.
    assert couple["detection_recall"] == det["recall"]
    assert couple["missed_gt"] == 2
    assert couple["missed_gt"] != det["fn"], (
        "headline missed_gt and detection.fn must stay distinct frames "
        "(named-only ID FN vs all-complete-GT detector FN)"
    )


def test_coverage_gaps_enumerate_every_vacuous_or_live_slice() -> None:
    """AUDIT-07 / EVAL-04: every tracked slice is live XOR named in coverage_gaps.

    Derived from the frozen report at test time — no parallel hardcoded inventory.
    """
    report = json.loads(_REPORT_JSON.read_text())
    record = json.loads(_RUN.read_text())
    declared = list((report.get("provenance") or {}).get("coverage_gaps") or [])
    # Run-record provenance must agree (rg-015 single source at generation).
    assert (record.get("provenance") or {}).get("coverage_gaps") == declared

    computed = compute_coverage_gaps(report)
    assert declared == computed, f"stale coverage_gaps: declared={declared} computed={computed}"

    live = _live_slice_names(report)
    # F7 must light up the previously vacuous hard cells (not merely declare them).
    for required in (
        "clustering.p_diff",
        "detection",
        "full_corpus_identification",
        "headline_identification",
        "demographic.by_cohort",
        "occlusion.masked",
    ):
        assert required in live, f"expected live cell still vacuous: {required}"
    # failures[] is an honest declared gap: score-face hard-exits on counts.failed>0.
    assert "failures" in declared

    # Declared gaps must actually be vacuous; live cells must not be declared.
    for g in declared:
        assert g not in live, f"coverage_gaps names live slice {g}"
    for g in computed:
        assert g in declared


def test_id_slice_vacuity_keys_on_probe_count_not_errors():  # VLM6-B-05 / TEST-15
    """Perfect accuracy with n_named_probes>0 is NOT vacuous (sampling frame exists)."""
    live_perfect = {
        "n_named_probes": 5,
        "tp": 5,
        "fp": 0,
        "fn": 0,
        "missed_gt": 0,
        "unmatched_detections": 0,
        "wrong_names": [],
    }
    assert _is_vacuous_id_slice(live_perfect) is False

    empty = {
        "n_named_probes": 0,
        "tp": 0,
        "fp": 0,
        "fn": 0,
        "missed_gt": 0,
        "unmatched_detections": 0,
        "wrong_names": [],
    }
    assert _is_vacuous_id_slice(empty) is True

    # Detection: perfect detector (fp=fn=0, tp>0) must not list detection as a gap.
    perfect_det_report = {
        "slices": {
            "occlusion": {
                "masked": {"synthetic": {"n_eligible": 1, "accuracy": 1.0}},
                "sunglasses": {},
                "occlusion_other": {},
            },
            "clustering": {"p_diff": 1},
            "demographic": {"by_cohort": {"a": {}, "b": {}}},
            "full_corpus_identification": live_perfect,
            "headline_identification": live_perfect,
        },
        "detection": {"tp": 6, "fp": 0, "fn": 0},
        "failures": [],
    }
    gaps = compute_coverage_gaps(perfect_det_report)
    assert "full_corpus_identification" not in gaps
    assert "headline_identification" not in gaps
    assert "detection" not in gaps
    assert "detection.fp" not in gaps
    assert "detection.fn" not in gaps


def test_coverage_gaps_guard_fails_when_gap_list_under_declares(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deleting a still-vacuous gap must fail the runtime guard (VLM6-B-04 / TEST-15).

    Prior test only asserted compute_coverage_gaps(report) != truncated — a
    tautology. The runtime validator is what score/generator paths must call.
    """
    report = json.loads(_REPORT_JSON.read_text())
    # Recompute against the fixed predicate so the test does not depend on a
    # stale freeze list shape after B-05.
    computed = compute_coverage_gaps(report)
    assert computed, "fixture expects at least one honest gap"
    # Happy path: exact match passes.
    validate_coverage_gaps(report, declared=computed)

    # Under-declare: drop one still-vacuous gap → guard must raise.
    truncated = list(computed)[1:]
    with pytest.raises(CoverageGapsUnderDeclaredError, match="missing_declared|coverage_gaps mismatch"):
        validate_coverage_gaps(report, declared=truncated)

    # Also exercise via provenance stamp on the report document.
    report = dict(report)
    report["provenance"] = dict(report.get("provenance") or {})
    report["provenance"]["coverage_gaps"] = truncated
    with pytest.raises(CoverageGapsUnderDeclaredError):
        validate_coverage_gaps(report)


def test_corrupt_face_expect_report_makes_determinism_gate_red(tmp_path: Path) -> None:
    """TEST-15 report-side: corrupted --expect-report → ANCHOR_MISMATCH [score-face]."""
    run_copy = tmp_path / _RUN.name
    run_copy.write_bytes(_RUN.read_bytes())
    payload = json.loads(_REPORT_JSON.read_text())
    payload.setdefault("counts", {})["matched_faces"] = 999
    corrupt_expect = tmp_path / "expect-corrupt-face-report.json"
    corrupt_expect.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    assert _sha256(corrupt_expect) != _FROZEN_DIGESTS[_REPORT_JSON.name]

    before_docs = {p.name: _sha256(p) for p in _ANCHOR_DIR.glob("S2A-face-*")}
    with pytest.raises(SystemExit) as exc:
        _check_face_determinism_cross_process(
            run_copy,
            str(_MANIFEST),
            public=False,
            expect_report=corrupt_expect,
        )
    msg = str(exc.value)
    assert "determinism check ANCHOR_MISMATCH" in msg
    assert "[score-face]" in msg
    assert "generate_face_determinism_anchor" in msg
    assert "do NOT regenerate" in msg
    assert "determinism check FAILED" not in msg
    assert "determinism check ERROR" not in msg
    # F7-01: artifact lands in out/, never beside the run-record / freeze tree.
    artifact = _determinism_artifact_dir() / "determinism-anchor-mismatch-score-face.diff.txt"
    assert artifact.is_file()
    assert str(artifact.resolve()) in msg
    assert not list(tmp_path.glob("determinism-anchor-mismatch*.diff.txt"))
    assert not list(_ANCHOR_DIR.glob("determinism-anchor-mismatch*.diff.txt"))
    assert {p.name: _sha256(p) for p in _ANCHOR_DIR.glob("S2A-face-*")} == before_docs
    assert _sha256(_REPORT_JSON) == _FROZEN_DIGESTS[_REPORT_JSON.name]


def test_corrupt_face_run_record_embedding_makes_determinism_gate_red(tmp_path: Path) -> None:
    """TEST-15 input-side: corrupt embedding → ANCHOR_MISMATCH (not wrong-name).

    landmarks_px / det_score are score-invisible (changing them leaves the
    certified JSON identical). Embedding is the face-path field that changes
    the score without tripping score-face's post-determinism failed-items gate.
    """
    payload = json.loads(_RUN.read_text())
    face = payload["items"][0]["faces"][0]
    emb = list(face["embedding"])
    emb[0] = -abs(emb[0]) - 0.5
    face["embedding"] = _unit(emb)
    run_copy = tmp_path / "run-corrupt.json"
    run_copy.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    expect_copy = tmp_path / _REPORT_JSON.name
    expect_copy.write_bytes(_REPORT_JSON.read_bytes())

    with pytest.raises(SystemExit) as exc:
        _check_face_determinism_cross_process(
            run_copy,
            str(_MANIFEST),
            public=False,
            expect_report=expect_copy,
        )
    msg = str(exc.value)
    assert "determinism check ANCHOR_MISMATCH" in msg
    assert "[score-face]" in msg
    assert "determinism check FAILED" not in msg
    assert "determinism check ERROR" not in msg
    assert "score-face gate failed" not in msg
    artifact = _determinism_artifact_dir() / "determinism-anchor-mismatch-score-face.diff.txt"
    assert artifact.is_file()
    assert str(artifact.resolve()) in msg
    assert not list(tmp_path.glob("determinism-anchor-mismatch*.diff.txt"))
    assert _sha256(_RUN) == _FROZEN_DIGESTS[_RUN.name]
    assert _sha256(_REPORT_JSON) == _FROZEN_DIGESTS[_REPORT_JSON.name]


def test_f7_clustering_corruption_goes_red(tmp_path: Path) -> None:
    """TEST-15: newly-live clustering cell — collapse Bob into Alice axis → red."""
    payload = json.loads(_RUN.read_text())
    report = json.loads(_REPORT_JSON.read_text())
    before_p_diff = report["slices"]["clustering"]["p_diff"]
    assert before_p_diff > 0  # F7 live cell

    # Bob faces are media_id 4 and 5; pin them to Alice's axis so clusters merge.
    alice_axis = _unit([1.0] + [0.0] * (_EMBEDDING_DIM - 1))
    for item in payload["items"]:
        if item.get("media_id") in (4, 5):
            for face in item.get("faces") or []:
                face["embedding"] = list(alice_axis)

    run_copy = tmp_path / "run-cluster-corrupt.json"
    run_copy.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    expect_copy = tmp_path / _REPORT_JSON.name
    expect_copy.write_bytes(_REPORT_JSON.read_bytes())

    with pytest.raises(SystemExit) as exc:
        _check_face_determinism_cross_process(
            run_copy,
            str(_MANIFEST),
            public=False,
            expect_report=expect_copy,
        )
    assert "determinism check ANCHOR_MISMATCH" in str(exc.value)

    # Prove the cell itself moved (not just some other field).
    # Metadata-only: re-score uses tags/face_count from record + manifest; no image bytes.
    manifest = load_manifest(str(_MANIFEST), skip_hash_verification=True)
    synth, real = occlusion_inputs_from_record(payload, manifest)
    json_doc, _ = build_face_reports(
        payload,
        manifest,
        score_manifest_sha256=_manifest_sha(manifest),
        occlusion_pairs_by_tag=synth,
        real_occlusion_pairs_by_tag=real,
        public=False,
    )
    after = json.loads(json_doc)["slices"]["clustering"]
    assert after["p_diff"] != before_p_diff or after["false_merge"] != report["slices"]["clustering"]["false_merge"]


def test_f7_detection_fp_corruption_goes_red(tmp_path: Path) -> None:
    """TEST-15: newly-live detection.fp — drop the unmatched detection → red."""
    payload = json.loads(_RUN.read_text())
    report = json.loads(_REPORT_JSON.read_text())
    assert report["detection"]["fp"] >= 1

    for item in payload["items"]:
        if item.get("media_id") == 7:  # fp-only image
            item["faces"] = []

    run_copy = tmp_path / "run-fp-corrupt.json"
    run_copy.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    expect_copy = tmp_path / _REPORT_JSON.name
    expect_copy.write_bytes(_REPORT_JSON.read_bytes())

    with pytest.raises(SystemExit) as exc:
        _check_face_determinism_cross_process(
            run_copy,
            str(_MANIFEST),
            public=False,
            expect_report=expect_copy,
        )
    assert "determinism check ANCHOR_MISMATCH" in str(exc.value)


def test_old_single_identity_corpus_cannot_detect_clustering_or_fp_bugs() -> None:
    """DBG-11: pre-F7 3-item corpus pins clustering p_diff=0 and detection.fp=0.

    Collapsing 'Bob into Alice' and removing an FP face are invisible on a corpus
    that has neither a second identity nor an unmatched detection — the cells
    stay at their empty values. That is the coverage gap F7 closes.
    """
    # Minimal Alice×2 + stranger (F6 shape), scored twice with a "Bob collapse"
    # that cannot apply and an FP face that does not exist.
    from scripts.eval_harness.face_run_record import (
        build_face_detection,
        build_face_run_item,
        build_face_run_record,
    )

    emb_alice_a = _unit([1.0] + [0.0] * 7)
    emb_alice_b = _unit([0.98, 0.1] + [0.0] * 6)
    emb_stranger = _unit([0.0, 1.0] + [0.0] * 6)
    bbox = [20.0, 20.0, 40.0, 40.0]
    lm = [[0.0, 0.0]] * 5

    def _face(e):
        return build_face_detection(bbox_px=bbox, landmarks_px=lm, embedding=e, det_score=0.95)

    def _old_record(alice_a_emb):
        items = [
            build_face_run_item(
                media_id=1,
                path="celebs01/alice-a.jpg",
                model_id="synthetic-face-anchor",
                embedding_dim=8,
                image_size=[100, 100],
                faces=[_face(alice_a_emb)],
            ),
            build_face_run_item(
                media_id=2,
                path="celebs01/alice-b.jpg",
                model_id="synthetic-face-anchor",
                embedding_dim=8,
                image_size=[100, 100],
                faces=[_face(emb_alice_b)],
            ),
            build_face_run_item(
                media_id=3,
                path="localwp/uploads/stranger-party.jpg",
                model_id="synthetic-face-anchor",
                embedding_dim=8,
                image_size=[100, 100],
                faces=[_face(emb_stranger)],
            ),
        ]
        return build_face_run_record(
            items,
            provenance={
                "manifest_sha256": "0" * 64,
                "head_sha": "0" * 40,
                "started_at": "2026-08-11T00:00:00Z",
                "leg": "candidate",
                "model_id": "synthetic-face-anchor",
                "embedding_dim": 8,
            },
        )

    man = {
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
                "face_boxes": [{"x": 0.4, "y": 0.4, "w": 0.4, "h": 0.4, "source": "iptc", "name": "Alice Example"}],
                "provenance": {
                    "source": "celeb",
                    "license": "public_domain",
                    "publishable": True,
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
                "face_boxes": [{"x": 0.4, "y": 0.4, "w": 0.4, "h": 0.4, "source": "iptc", "name": "Alice Example"}],
                "provenance": {
                    "source": "celeb",
                    "license": "public_domain",
                    "publishable": True,
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
                "face_boxes": [{"x": 0.4, "y": 0.4, "w": 0.4, "h": 0.4, "source": "iptc", "name": None}],
                "provenance": {
                    "source": "localwp",
                    "license": "consented",
                    "publishable": False,
                },
            },
        ],
    }
    with tempfile.TemporaryDirectory() as td:
        mp = Path(td) / "old-man.json"
        mp.write_text(json.dumps(man, indent=2, sort_keys=True) + "\n")
        # Metadata-only: old single-identity corpus score probe; never opens image bytes.
        manifest = load_manifest(str(mp), skip_hash_verification=True)
        sha = _manifest_sha(manifest)

        def score(rec):
            rec = dict(rec)
            rec["provenance"] = {**rec["provenance"], "manifest_sha256": sha}
            synth, real = occlusion_inputs_from_record(rec, manifest)
            j, _ = build_face_reports(
                rec,
                manifest,
                score_manifest_sha256=sha,
                occlusion_pairs_by_tag=synth,
                real_occlusion_pairs_by_tag=real,
                public=False,
            )
            return json.loads(j)

        base = score(_old_record(emb_alice_a))
        # "Bob collapse" analogue on a 1-id corpus: nudge Alice A slightly.
        # Clustering still has p_diff=0 and detection.fp=0 — cell never executes.
        nudged = _unit([0.97, 0.2] + [0.0] * 6)
        after = score(_old_record(nudged))
        assert base["slices"]["clustering"]["p_diff"] == 0
        assert after["slices"]["clustering"]["p_diff"] == 0
        assert base["detection"]["fp"] == 0
        assert after["detection"]["fp"] == 0
        assert base["detection"]["fn"] == 0
        assert after["detection"]["fn"] == 0
        # No second cohort, no wrong_names path from a Bob collapse that never lands.
        assert len(base["slices"]["demographic"]["by_cohort"]) == 1
        assert (base["slices"]["full_corpus_identification"].get("wrong_names") or []) == []


def test_corrupt_face_run_record_without_expect_report_passes_silently(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """DBG-11: same embedding corruption without --expect-report still seed-passes.

    Parent and children re-score the same corrupted file and agree — the hole
    F6 closes. Proves the red path above is new coverage, not a rename.
    """
    payload = json.loads(_RUN.read_text())
    face = payload["items"][0]["faces"][0]
    emb = list(face["embedding"])
    emb[0] = -abs(emb[0]) - 0.5
    face["embedding"] = _unit(emb)
    run_copy = tmp_path / "run-corrupt-no-expect.json"
    run_copy.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n")

    _check_face_determinism_cross_process(
        run_copy,
        str(_MANIFEST),
        public=False,
        expect_report=None,
    )
    out = capsys.readouterr().out
    assert "determinism check passed [score-face]" in out
    assert "matches --expect-report" not in out
    assert "ANCHOR_MISMATCH" not in out


def test_face_expect_report_matches_committed_freeze_green(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Clean --expect-report against the committed face freeze exits green."""
    run_copy = tmp_path / _RUN.name
    run_copy.write_bytes(_RUN.read_bytes())
    expect_copy = tmp_path / _REPORT_JSON.name
    expect_copy.write_bytes(_REPORT_JSON.read_bytes())

    json_doc, _md = _check_face_determinism_cross_process(
        run_copy,
        str(_MANIFEST),
        public=False,
        expect_report=expect_copy,
    )
    out = capsys.readouterr().out
    assert "determinism check passed [score-face]" in out
    assert "matches --expect-report" in out
    assert "ANCHOR_MISMATCH" not in out
    assert json_doc == _REPORT_JSON.read_text(encoding="utf-8")
    assert _sha256(_REPORT_JSON) == _FROZEN_DIGESTS[_REPORT_JSON.name]
    assert _sha256(_RUN) == _FROZEN_DIGESTS[_RUN.name]


def test_cli_score_face_expect_report_requires_check_determinism(tmp_path: Path) -> None:
    """OBS-04: --expect-report alone is a hard exit (no silent half-gate)."""
    run_copy = tmp_path / _RUN.name
    run_copy.write_bytes(_RUN.read_bytes())
    expect_copy = tmp_path / _REPORT_JSON.name
    expect_copy.write_bytes(_REPORT_JSON.read_bytes())
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "score-face",
                "--manifest",
                str(_MANIFEST),
                "--run-record",
                str(run_copy),
                "--expect-report",
                str(expect_copy),
            ]
        )
    assert "--expect-report requires --check-determinism" in str(exc.value)


def test_cli_score_face_expect_report_end_to_end_green(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Shipped CLI: score-face --check-determinism --expect-report against freeze."""
    run_copy = tmp_path / _RUN.name
    run_copy.write_bytes(_RUN.read_bytes())
    expect_copy = tmp_path / _REPORT_JSON.name
    expect_copy.write_bytes(_REPORT_JSON.read_bytes())
    man_copy = tmp_path / _MANIFEST.name
    man_copy.write_bytes(_MANIFEST.read_bytes())

    main(
        [
            "score-face",
            "--manifest",
            str(man_copy),
            "--run-record",
            str(run_copy),
            "--check-determinism",
            "--expect-report",
            str(expect_copy),
        ]
    )
    out = capsys.readouterr().out
    assert "determinism check passed [score-face]" in out
    assert "matches --expect-report" in out
    assert "baseline=randomized; child_seeds=0,1,42" in out
    # Committed freeze tree untouched (CLI wrote beside tmp run-record only).
    assert _sha256(_REPORT_JSON) == _FROZEN_DIGESTS[_REPORT_JSON.name]
    assert _sha256(_RUN) == _FROZEN_DIGESTS[_RUN.name]
    assert _sha256(_MANIFEST) == _FROZEN_DIGESTS[_MANIFEST.name]


def test_f7_01_mismatch_artifact_never_dirties_bakeoff_results(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """F7-01: red gate against committed freeze paths must not write under docs/.

    Operator workflow uses the docs/ freeze as --run-record; pre-fix the
    mismatch artifact was derived from that parent and dirtied the tree.
    """
    # Copy freeze into a docs-like layout under tmp to avoid actually writing
    # reports beside the real freeze; assert the diagnostic still targets OUT_DIR.
    # Also run once with the real committed expect path to prove message path.
    run_copy = tmp_path / _RUN.name
    run_copy.write_bytes(_RUN.read_bytes())
    payload = json.loads(_REPORT_JSON.read_text())
    payload.setdefault("counts", {})["matched_faces"] = 12345
    corrupt_expect = tmp_path / "corrupt-expect.json"
    corrupt_expect.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n")

    before = {p.name for p in _ANCHOR_DIR.iterdir()}
    # Clear any stale mismatch artifact so existence is from this run.
    stale = OUT_DIR / "determinism-anchor-mismatch-score-face.diff.txt"
    if stale.is_file():
        stale.unlink()

    with pytest.raises(SystemExit) as exc:
        main(
            [
                "score-face",
                "--manifest",
                str(_MANIFEST),
                "--run-record",
                str(run_copy),
                "--check-determinism",
                "--expect-report",
                str(corrupt_expect),
            ]
        )
    msg = str(exc.value)
    assert "determinism check ANCHOR_MISMATCH" in msg
    artifact = Path(msg.split("artifact=")[1].split(")")[0].split(";")[0].strip())
    assert artifact.is_file()
    assert artifact.resolve().is_relative_to(OUT_DIR.resolve()) or str(OUT_DIR.resolve()) in str(artifact.resolve())
    assert "bakeoff-results" not in str(artifact.resolve())
    after = {p.name for p in _ANCHOR_DIR.iterdir()}
    assert after == before
    assert not list(_ANCHOR_DIR.glob("determinism-*.diff.txt"))
