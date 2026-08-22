"""Committed S2A determinism anchor is regenerable and load-bearing (VLM-6 F4/F5).

The frozen triple under docs/tasks/vlm/bakeoff-results/ is the artifact the
digest gate (VLM6-S2A-B-06) compares via ``score --check-determinism
--expect-report``. These tests pin:
  - generator byte-stability against the committed files
  - computed provenance.manifest_sha256 equals current golden manifest
  - TEST-15: corrupting a tmp expect-report makes the shipped gate go red
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from scripts.eval_harness.cli import (
    _check_score_determinism_cross_process,
    _determinism_artifact_dir,
    _manifest_sha,
    main,
)
from scripts.eval_harness.generate_determinism_anchor import (
    _CORPUS_TRAPS,
    _DEFAULT_MANIFEST_STEM,
    _DEFAULT_STEM,
    _POS_TRAP_MEDIA_ID,
    _TRAP_MEDIA_ID,
    _coverage_gaps,
    build_caption_anchor_manifest,
    build_run_record,
    write_anchor,
)
from scripts.eval_harness.generate_face_determinism_anchor import write_face_anchor
from scripts.eval_harness.manifest import (
    METRIC_BACKING_SLICE_THRESHOLD,
    SHIPPED_CORPUS_COVERAGE_GAPS,
    AnnotationMode,
    FaceBox,
    GoldenManifest,
    compute_corpus_coverage_gaps,
    legacy_import_lineage,
    load_manifest,
)
from scripts.eval_harness.report import score_run_record

_REPO_ROOT = Path(__file__).resolve().parents[4]  # monorepo root
_SERVICE_ROOT = Path(__file__).resolve().parents[2]  # apps/prototype-description-service
# Shared seed golden (zero face_boxes) — unit tests of helpers; not the freeze corpus.
_GOLDEN = _SERVICE_ROOT / "scene" / "tests" / "seed" / "golden.json"
_ANCHOR_DIR = _REPO_ROOT / "docs" / "tasks" / "vlm" / "bakeoff-results"
_STEM = _DEFAULT_STEM
_MAN_STEM = _DEFAULT_MANIFEST_STEM
# Freeze corpus: golden + media 39 mixed-y trap (wG3) + media 40 centre-x-tie (G-02).
_MAN = _ANCHOR_DIR / f"{_MAN_STEM}.json"
_RUN = _ANCHOR_DIR / f"{_STEM}.json"
_REPORT_JSON = _ANCHOR_DIR / f"{_STEM}-report.json"
_REPORT_MD = _ANCHOR_DIR / f"{_STEM}-report.md"

# File digests of the committed freeze set — update when intentionally regenerating.
# wG3: caption freeze corpus extended with media 39 G-01 mixed-y trap so
# labeled_y_missing_images is freeze-observable (was structural 0 on golden).
# G-02: media 40 centre-x-tie trap so positional_images is freeze-observable
# (was structural 0). Digests rewritten with the G-02 regen.
# VLM6-DELTA-09: regenerated for FIR-11 v3 (annotation_mode required, per-box
# lineage — build_caption_anchor_manifest fix, VLM6-DELTA-04).
_FROZEN_DIGESTS = {
    _MAN.name: "14e5e2e1a017c45acc7c615b3069b31880f011db9c14098e85f9a789a8f4a7a7",
    _RUN.name: "bca65e319c6e942d3cdaac333a9b8bbf0a1f58ef1687c6ec81bbd9d27002c3a4",
    _REPORT_JSON.name: "1d5c35bf9ace9de3b74e4846699905d84be7e22c2a72c4e86f57084bcc4a5f40",
    _REPORT_MD.name: "5131d552f1bc38e6ae3441d8346a35ca560a2412d802008f2e924aeff1ab339c",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _oracle_predicted_face_count(*, face_count: int, seed_index: int) -> int:
    """Independent reimplementation of the generator's face-count seed rules.

    RV3-01: deliberately does **not** import ``_predicted_face_count`` from
    ``generate_determinism_anchor`` — an oracle that shares private helpers with
    the generator under test cannot catch the generator rewriting those helpers
    into a pure GT echo or an exaggerated fixture (TEST-15 / AUDIT-07).
    """
    count = int(face_count)
    if seed_index % 7 == 0 and count > 0:
        return count - 1
    if seed_index % 11 == 0:
        return count + 1
    return count


def _oracle_predicted_identity_names(*, present_identities: list[str], seed_index: int) -> list[str]:
    """Independent reimplementation of the generator's identity seed rules."""
    names = list(present_identities)
    if names and seed_index % 5 == 0:
        names = names[:-1]
    if present_identities and seed_index % 9 == 0 and seed_index % 5 != 0:
        names = names + [f"Fixture-Wrong-{seed_index}"]
    return names


_BOXED_CAPTURE_SESSION_ID = "synthetic-session-determinism-anchor-oracle-golden"


def _boxed_lineage(*, name: str | None):
    """``legacy_import_lineage`` with a real occasion key (exhaustive-safe)."""
    lineage = legacy_import_lineage(name=name)
    lineage["capture_session_id"] = _BOXED_CAPTURE_SESSION_ID
    return lineage


def _boxed_exhaustive_manifest(manifest: GoldenManifest) -> GoldenManifest:
    """Boxed+exhaustive variant of ``manifest`` for detection-scoring tests.

    ``golden.json`` is roster_only with zero face_boxes, so ``detection_pr``
    structurally refuses it (VLM6-DELTA-09). ``detection_pr`` is pure
    count-based math over ``face_count`` (face_metrics.py:568-605) — it never
    inspects box geometry — so padding every entry's ``face_boxes`` to exactly
    ``face_count`` (named boxes first from ``present_identities``, then
    anonymous fill) satisfies ``require_exhaustive_box_coverage`` without
    changing any detection or identification arithmetic versus the oracle.
    """
    data = manifest.model_dump(mode="json")
    data["annotation_mode"] = AnnotationMode.EXHAUSTIVE.value
    for entry in data["entries"]:
        face_count = int(entry["face_count"])
        names = list(entry["present_identities"])
        boxes = []
        for index in range(face_count):
            name = names[index] if index < len(names) else None
            boxes.append(
                {
                    "x": 0.1 + 0.05 * index,
                    "y": 0.1,
                    "w": 0.05,
                    "h": 0.05,
                    "name": name,
                    "source": "mwg",
                    "lineage": _boxed_lineage(name=name),
                }
            )
        entry["face_boxes"] = boxes
    return GoldenManifest.model_validate(data)


def _stamp_filled_entries(manifest: GoldenManifest) -> list[dict[str, Any]]:
    """``score_run_record`` resolves mode from per-entry stamps, not the
    document-level ``GoldenManifest.annotation_mode`` (FIR-11-S2-01 /
    S2R2-10). Mirrors the fill-only-when-absent pattern in
    ``cli.py::_cmd_score`` (never clobbers a real per-entry stamp)."""
    rows = []
    for entry in manifest.entries:
        row = entry.model_dump()
        if row.get("annotation_mode") is None:
            row["annotation_mode"] = manifest.annotation_mode
        rows.append(row)
    return rows


def _seeded_deviation_oracle(manifest: GoldenManifest) -> dict[str, int | float]:
    """Independent oracle over the golden corpus + count-based detection math.

    Computes expected detection/wrong-name bounds **from the manifest alone**
    via the inlined seed predicates above — not by importing generator helpers,
    not by reading freeze digests, and not by hardwiring score numbers.
    Score-side checks always run the real ``score_run_record`` (RV3-01 / S4-01).
    """
    det_tp = det_fp = det_fn = 0
    wrong_name_count = 0
    for index, entry in enumerate(manifest.entries):
        pred_faces = _oracle_predicted_face_count(face_count=int(entry.face_count), seed_index=index)
        labeled_faces = int(entry.face_count)
        det_tp += min(pred_faces, labeled_faces)
        det_fp += max(pred_faces - labeled_faces, 0)
        det_fn += max(labeled_faces - pred_faces, 0)
        pred_names = set(
            _oracle_predicted_identity_names(
                present_identities=list(entry.present_identities),
                seed_index=index,
            )
        )
        labeled_names = set(entry.present_identities)
        for name in pred_names:
            if name not in labeled_names:
                wrong_name_count += 1
    det_denom_p = det_tp + det_fp
    det_denom_r = det_tp + det_fn
    return {
        "det_tp": det_tp,
        "det_fp": det_fp,
        "det_fn": det_fn,
        "wrong_name_count": wrong_name_count,
        # Precision/recall of the *seeded* predictions — used only as oracle
        # bounds for the scored document, never as freeze literals.
        "det_precision": (det_tp / det_denom_p) if det_denom_p else 0.0,
        "det_recall": (det_tp / det_denom_r) if det_denom_r else 0.0,
    }


def _assert_scored_matches_oracle(scored: dict, oracle: dict[str, int | float]) -> None:
    """Shared equality/bound pin used by the green path and the mutant RED path."""
    det = scored["faces"]["detection"]
    ident = scored["faces"]["identification"]
    wrong_names = list(ident.get("wrong_names") or [])

    assert int(det["fn"]) >= int(oracle["det_fn"]), (
        f"detection fn={det['fn']} below oracle lower bound {oracle['det_fn']} (scorer may be GT-echoing; VLM6-S4-01)"
    )
    assert int(det["fp"]) >= int(oracle["det_fp"]), (
        f"detection fp={det['fp']} below oracle lower bound {oracle['det_fp']} (scorer may be GT-echoing; VLM6-S4-01)"
    )
    assert len(wrong_names) >= int(oracle["wrong_name_count"]), (
        f"wrong_names={len(wrong_names)} below oracle lower bound {oracle['wrong_name_count']} (VLM6-S4-01)"
    )
    assert det["precision"] is not None and float(det["precision"]) < 1.0, (
        f"detection precision={det['precision']} must be strictly below 1.0 "
        f"(oracle precision={oracle['det_precision']}; VLM6-S4-01 / TEST-15)"
    )
    assert det["recall"] is not None and float(det["recall"]) < 1.0, (
        f"detection recall={det['recall']} must be strictly below 1.0 "
        f"(oracle recall={oracle['det_recall']}; VLM6-S4-01 / TEST-15)"
    )
    # Exact pin — lower bounds alone let an exaggerated record stay green (RV3-01).
    assert int(det["tp"]) == int(oracle["det_tp"])
    assert int(det["fp"]) == int(oracle["det_fp"])
    assert int(det["fn"]) == int(oracle["det_fn"])
    assert float(det["precision"]) == float(oracle["det_precision"])
    assert float(det["recall"]) == float(oracle["det_recall"])
    assert len(wrong_names) == int(oracle["wrong_name_count"])


@pytest.mark.parametrize("name,expected", list(_FROZEN_DIGESTS.items()))
def test_committed_anchor_digests_match_frozen(name: str, expected: str) -> None:
    """Pin machine-diffable digests so a silent rewrite of the freeze goes red (TEST-15 base)."""
    path = _ANCHOR_DIR / name
    assert path.is_file(), f"missing committed anchor artifact: {path}"
    assert _sha256(path) == expected


def test_generator_regenerates_byte_identical_committed_anchor(tmp_path: Path) -> None:
    """Generator is the source of truth — re-run must match the freeze byte-for-byte.

    Man+run pin the wG3 extended corpus; report JSON/MD pin the wI1 regeneration
    of that corpus through the live scorer (TEST-15 base for every published field).
    """
    run_path, report_json, report_md, manifest_sha = write_anchor(
        manifest_path=_GOLDEN,
        out_dir=tmp_path,
        stem=_STEM,
        manifest_stem=_MAN_STEM,
        head_sha="0" * 40,
        started_at="2026-08-11T00:00:00Z",
    )
    man_path = tmp_path / _MAN.name
    assert man_path.is_file(), "write_anchor must promote the caption-anchor manifest"
    # Metadata-only: generation-time sha must match the committed freeze man, not bare golden.
    expected_sha = _manifest_sha(
        load_manifest(
            str(_MAN),
            skip_hash_verification=True,
            hash_skip_reason="test metadata-only; image bytes never opened",
            metadata_only=True,
        )
    )
    assert manifest_sha == expected_sha
    assert manifest_sha.startswith("51e9456b")  # VLM6-DELTA-09 v3 regen
    assert man_path.read_bytes() == _MAN.read_bytes()
    assert run_path.read_bytes() == _RUN.read_bytes()
    assert report_json.read_bytes() == _REPORT_JSON.read_bytes()
    assert report_md.read_bytes() == _REPORT_MD.read_bytes()


def test_committed_run_record_identity_rows_are_dicts_and_manifest_sha_computed() -> None:
    """Greenfield shape: no bare-string identities; sha was generation-time computed."""
    record = json.loads(_RUN.read_text())
    # Metadata-only: provenance sha check against freeze man; never opens image bytes.
    assert record["provenance"]["manifest_sha256"] == _manifest_sha(
        load_manifest(
            str(_MAN),
            skip_hash_verification=True,
            hash_skip_reason="test metadata-only; image bytes never opened",
            metadata_only=True,
        )
    )
    assert len(record["items"]) == 39  # golden 37 + G-01 media 39 + G-02 media 40
    assert any(int(i["media_id"]) == _TRAP_MEDIA_ID for i in record["items"])
    assert any(int(i["media_id"]) == _POS_TRAP_MEDIA_ID for i in record["items"])
    for item in record["items"]:
        for row in item["identities"]:
            assert isinstance(row, dict)
            assert "name" in row
        assert (item.get("describe") or {}).get("adapter") == "seeded"
    # Synthetic dim-8 is face-corpus territory; caption run stays seeded describe path.
    assert record["provenance"]["predictions_source"] == "ground_truth_derived_fixture"
    assert record["provenance"]["face_metrics_evidential"] is False


def test_corrupt_expect_report_makes_determinism_gate_red(tmp_path: Path) -> None:
    """TEST-15 / DBG-11: corrupted --expect-report turns the shipped gate red.

    Pre-F5 the guard compared the record to itself across seeds, so a doctored
    freeze was undetectable. This control must fail if ANCHOR_MISMATCH is
    removed or weakened (sr-001).
    """
    run_copy = tmp_path / _RUN.name
    run_copy.write_bytes(_RUN.read_bytes())
    payload = json.loads(_REPORT_JSON.read_text())
    before = (payload.get("verdict") or {}).get("verdict", "pass_ungated")
    payload.setdefault("verdict", {})["verdict"] = "CORRUPTED_FOR_TEST_15"
    corrupt_expect = tmp_path / "expect-corrupt-report.json"
    corrupt_expect.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    assert _sha256(corrupt_expect) != _FROZEN_DIGESTS[_REPORT_JSON.name]

    with pytest.raises(SystemExit) as exc:
        _check_score_determinism_cross_process(
            run_copy,
            str(_MAN),
            rubric_gate="skip",
            expect_report=corrupt_expect,
        )
    msg = str(exc.value)
    assert "determinism check ANCHOR_MISMATCH" in msg
    assert "[score]" in msg
    assert "generate_determinism_anchor" in msg
    assert "do NOT regenerate" in msg
    assert "determinism check FAILED" not in msg
    assert "determinism check ERROR" not in msg
    # F7-01: diagnostic lands in out/, never beside run-record or freeze tree.
    artifact = _determinism_artifact_dir() / "determinism-anchor-mismatch-score.diff.txt"
    assert artifact.is_file()
    assert str(artifact.resolve()) in msg
    assert not list(tmp_path.glob("determinism-anchor-mismatch*.diff.txt"))
    # Committed freeze still intact (TEST-15 restore semantics).
    assert _sha256(_REPORT_JSON) == _FROZEN_DIGESTS[_REPORT_JSON.name]
    assert before != "CORRUPTED_FOR_TEST_15"


@pytest.mark.parametrize("empty_golden", [False, True])
def test_expect_report_matches_committed_freeze_green(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, empty_golden: bool
) -> None:
    """Clean --expect-report against the committed freeze still exits green (discrimination).

    Post-wI1 regen the expect-report path re-scores the wG3 man+run and must
    match the committed report bytes (and pinned digests) exactly.

    empty_golden=True is VLM6-RV3-Q4-01: an existing-but-empty GOLDEN_IMAGES_DIR
    must not turn this metadata-only freeze red.
    """
    if empty_golden:
        empty = tmp_path / "empty"
        empty.mkdir()
        monkeypatch.setenv("GOLDEN_IMAGES_DIR", str(empty))
    run_copy = tmp_path / _RUN.name
    run_copy.write_bytes(_RUN.read_bytes())
    # Copy freeze into tmp so we never risk writing beside committed artifacts.
    expect_copy = tmp_path / _REPORT_JSON.name
    expect_copy.write_bytes(_REPORT_JSON.read_bytes())

    json_doc, _md = _check_score_determinism_cross_process(
        run_copy,
        str(_MAN),
        rubric_gate="skip",
        expect_report=expect_copy,
    )
    out = capsys.readouterr().out
    assert "determinism check passed [score]" in out
    assert "matches --expect-report" in out
    assert "ANCHOR_MISMATCH" not in out
    assert json_doc == _REPORT_JSON.read_text(encoding="utf-8")
    assert _sha256(_REPORT_JSON) == _FROZEN_DIGESTS[_REPORT_JSON.name]
    assert _sha256(_RUN) == _FROZEN_DIGESTS[_RUN.name]


def test_corrupt_run_record_alt_text_makes_determinism_gate_red(tmp_path: Path) -> None:
    """F5-01 carry-over / TEST-15: corrupt run-record input (not just the freeze).

    F5 landed report-side corruption. The hole the guard exists for is a
    corrupted *run-record* that parent and children re-score identically —
    seed-stability still "passes" without ``--expect-report``. Mutate
    ``items[i].describe.alt_text_draft`` (no content gate watches it alone;
    wrong-name stays clean) so ANCHOR_MISMATCH is the sole detector.
    """
    run_copy = tmp_path / _RUN.name
    payload = json.loads(_RUN.read_text())
    item = payload["items"][0]
    describe = dict(item.get("describe") or {})
    describe["alt_text_draft"] = "CORRUPTED ALT TEXT DRAFT FOR F5-01 INPUT CONTROL"
    item["describe"] = describe
    run_copy.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    expect_copy = tmp_path / _REPORT_JSON.name
    expect_copy.write_bytes(_REPORT_JSON.read_bytes())

    with pytest.raises(SystemExit) as exc:
        _check_score_determinism_cross_process(
            run_copy,
            str(_MAN),
            rubric_gate="skip",
            expect_report=expect_copy,
        )
    msg = str(exc.value)
    assert "determinism check ANCHOR_MISMATCH" in msg
    assert "[score]" in msg
    assert "determinism check FAILED" not in msg
    assert "determinism check ERROR" not in msg
    assert "wrong-name" not in msg.lower()
    artifact = _determinism_artifact_dir() / "determinism-anchor-mismatch-score.diff.txt"
    assert artifact.is_file()
    assert str(artifact.resolve()) in msg
    assert not list(tmp_path.glob("determinism-anchor-mismatch*.diff.txt"))
    # Committed freeze and original run-record untouched.
    assert _sha256(_REPORT_JSON) == _FROZEN_DIGESTS[_REPORT_JSON.name]
    assert _sha256(_RUN) == _FROZEN_DIGESTS[_RUN.name]


def test_committed_anchor_discloses_corpus_coverage_gaps():  # VLM6-R2-03
    """The freeze corpus must name what it leaves unscored, in the anchor itself.

    Freeze man is golden+traps (39 entries). face_boxes is 2/39 (media 39+40) —
    still below the slice threshold, not a certified sampling frame (EVAL-03).
    Other registry fields stay 0/39. golden.json itself remains 0/N face_boxes.
    """
    manifest = load_manifest(
        str(_MAN),
        skip_hash_verification=True,
        hash_skip_reason="test metadata-only; image bytes never opened",
        metadata_only=True,
    )
    gaps = compute_corpus_coverage_gaps(manifest.entries)
    assert set(gaps) == set(SHIPPED_CORPUS_COVERAGE_GAPS)
    assert "demographic_cohort" in gaps  # VLM6-C-02: registry-driven
    assert gaps["face_boxes"]["populated"] == 2  # media 39 + media 40 traps
    assert gaps["face_boxes"]["total"] == 39
    assert gaps["face_boxes"]["below_threshold"] is True  # 2 < 5
    assert gaps["face_boxes"]["pi_zero"] is False
    assert "2/39" in gaps["face_boxes"]["reason"]
    for field in ("spatial_facts", "reference_facts", "demographic_cohort"):
        info = gaps[field]
        assert info["populated"] == 0
        assert info["total"] == 39
        assert info["threshold"] == METRIC_BACKING_SLICE_THRESHOLD
        assert info["below_threshold"] is True
        assert info["pi_zero"] is True
        assert "0/39" in info["reason"]
    assert "right-names-on-wrong-faces" in gaps["face_boxes"]["reason"]
    # Seed golden stays structurally blind (shared fixture not bent).
    golden = load_manifest(
        str(_GOLDEN),
        skip_hash_verification=True,
        hash_skip_reason="test metadata-only; image bytes never opened",
        metadata_only=True,
    )
    g_gaps = compute_corpus_coverage_gaps(golden.entries)
    assert g_gaps["face_boxes"]["populated"] == 0
    assert g_gaps["face_boxes"]["total"] == len(golden.entries)


def test_coverage_gaps_keep_under_sampled_field_after_single_population():  # VLM6-C-01 / TEST-15
    """One schema-valid face_boxes row must NOT silence the gap (VLM6-C-01 / C-08).

    Prior control used an invalid `{width,height}` dict via model_copy (skips
    re-validation) and asserted the key disappeared — locking the wrong boolean
    behaviour. A 1/N population stays below the slice threshold.
    """
    manifest = load_manifest(
        str(_GOLDEN),
        skip_hash_verification=True,
        hash_skip_reason="test metadata-only; image bytes never opened",
        metadata_only=True,
    )
    gaps = _coverage_gaps(manifest.entries)
    assert gaps["face_boxes"]["pi_zero"] is True

    # Schema-valid FaceBox (rg-005): centre x/y + size w/h + source.
    valid_box = FaceBox(x=0.4, y=0.4, w=0.2, h=0.2, source="iptc", name=None)
    entries = list(manifest.entries)
    entries[0] = entries[0].model_copy(update={"face_boxes": [valid_box]})
    # Round-trip through model so the control proves a real population path.
    assert entries[0].face_boxes[0].source == "iptc"
    assert entries[0].face_boxes[0].w == 0.2

    gaps = _coverage_gaps(entries)
    assert "face_boxes" in gaps
    assert gaps["face_boxes"]["populated"] == 1
    assert gaps["face_boxes"]["total"] == len(entries)
    assert gaps["face_boxes"]["below_threshold"] is True  # 1 < threshold
    assert gaps["face_boxes"]["pi_zero"] is False
    # Untouched registry fields still reported.
    assert gaps["spatial_facts"]["pi_zero"] is True
    assert gaps["reference_facts"]["pi_zero"] is True
    assert gaps["demographic_cohort"]["pi_zero"] is True


def test_coverage_gaps_meet_threshold_when_fully_populated():  # VLM6-C-01 discrimination
    """Only at/above the slice threshold does below_threshold flip false."""
    manifest = load_manifest(
        str(_GOLDEN),
        skip_hash_verification=True,
        hash_skip_reason="test metadata-only; image bytes never opened",
        metadata_only=True,
    )
    box = FaceBox(x=0.4, y=0.4, w=0.2, h=0.2, source="iptc")
    entries = [e.model_copy(update={"face_boxes": [box]}) for e in manifest.entries]
    gaps = compute_corpus_coverage_gaps(entries)
    assert gaps["face_boxes"]["populated"] == len(entries)
    assert gaps["face_boxes"]["below_threshold"] is False
    assert gaps["face_boxes"]["pi_zero"] is False


def test_coverage_gaps_total_tracks_scratch_manifest_length_not_a_stale_constant():
    """TEST-15 / FIR-ORCH-BR-23: total must follow the scored list, not a leftover 37."""
    manifest = load_manifest(
        str(_GOLDEN),
        skip_hash_verification=True,
        hash_skip_reason="test metadata-only; image bytes never opened",
        metadata_only=True,
    )
    truncated = list(manifest.entries)[:3]
    assert len(truncated) == 3
    gaps = compute_corpus_coverage_gaps(truncated)
    assert gaps["face_boxes"]["total"] == len(truncated)
    assert gaps["face_boxes"]["total"] != 37


def test_seeded_predictions_are_not_pure_gt_echo():  # VLM6-C-04 / VLM6-S4-01 / TEST-15
    """Fixture face/identity predictions deviate from GT so metrics can go red.

    Existence-of-deviation alone is not enough (S4-01): a scorer that uses GT
    for both predicted and labeled stays green on existence while producing
    perfect detection (P/R 1.0). After build_run_record we score once with the
    **real** scorer and pin bounds from an *independent* oracle over the
    corpus — never from freeze digests, never from generator private helpers
    (RV3-01 / TEST-15).
    """
    manifest = _boxed_exhaustive_manifest(
        load_manifest(
            str(_GOLDEN),
            skip_hash_verification=True,
            hash_skip_reason="test metadata-only; image bytes never opened",
            metadata_only=True,
        )
    )
    record = build_run_record(
        manifest,
        fixture_revision="0" * 40,
        canonical_timestamp="2026-08-11T00:00:00Z",
        head_sha="",
        started_at="2026-08-11T00:00:00Z",
    )
    assert record["provenance"]["predictions_source"] == "ground_truth_derived_fixture"
    assert record["provenance"]["face_metrics_evidential"] is False
    assert record["provenance"]["head_sha"] is None  # never fabricate 40 zeros (F-04)
    assert "fixture_revision" in record["provenance"]

    # At least one face_count and one identity set must differ from GT.
    face_deviations = 0
    id_deviations = 0
    for index, (entry, item) in enumerate(zip(manifest.entries, record["items"], strict=True)):
        if item["face_count"] != entry.face_count:
            face_deviations += 1
        pred_names = {row["name"] for row in item["identities"]}
        gt_names = set(entry.present_identities)
        if pred_names != gt_names:
            id_deviations += 1
        # C-09: no invented bboxes; always unpositioned.
        for row in item["identities"]:
            assert row.get("unpositioned") is True
            assert "bbox" not in row
    assert face_deviations > 0, "face_count must deviate on a seeded subset (TEST-15)"
    assert id_deviations > 0, "identities must deviate on a seeded subset (TEST-15)"

    # Independent seed predicates themselves must be able to go red vs pure echo.
    entry0 = manifest.entries[0]
    pred0 = _oracle_predicted_face_count(face_count=int(entry0.face_count), seed_index=0)
    assert pred0 != entry0.face_count or entry0.face_count == 0
    if entry0.present_identities:
        names0 = set(
            _oracle_predicted_identity_names(
                present_identities=list(entry0.present_identities),
                seed_index=0,
            )
        )
        assert names0 != set(entry0.present_identities) or len(entry0.present_identities) == 0

    # --- VLM6-S4-01 / RV3-01: independent oracle + real scorer ---
    oracle = _seeded_deviation_oracle(manifest)
    # Seed formula must itself produce imperfect detection / wrong names, else
    # the pin is vacuous (TEST-15: the assertion must be able to fail).
    assert int(oracle["det_fn"]) >= 1
    assert int(oracle["det_fp"]) >= 1
    assert int(oracle["wrong_name_count"]) >= 1
    assert float(oracle["det_precision"]) < 1.0
    assert float(oracle["det_recall"]) < 1.0

    entries = _stamp_filled_entries(manifest)
    roster = sorted(set(getattr(manifest, "roster", []) or []))
    scored = score_run_record(
        record,
        entries,
        score_manifest_sha256=record["provenance"]["manifest_sha256"],
        manifest_roster=roster,
        rubric_gate="skip",
    )
    _assert_scored_matches_oracle(scored, oracle)


def test_exaggerated_record_mutant_goes_red_against_independent_oracle():  # RV3-01 / TEST-15
    """Reviewer's exaggerated-record mutant must FAIL the oracle pin.

    Pre-fix hole: oracle imported generator helpers and/or hardwired the seed
    scorer so an exaggerated record (face_count=max(0,gt-2), every item gets an
    ALWAYS-WRONG name) still matched oracle-expected {tp:51,fp:3,fn:6,
    wrong_names=4}. Real scorer on that input yields det≈{tp:11,fp:0,fn:46}
    with many wrong_names — the control that proves independence.
    """
    manifest = _boxed_exhaustive_manifest(
        load_manifest(
            str(_GOLDEN),
            skip_hash_verification=True,
            hash_skip_reason="test metadata-only; image bytes never opened",
            metadata_only=True,
        )
    )
    record = build_run_record(
        manifest,
        fixture_revision="0" * 40,
        canonical_timestamp="2026-08-11T00:00:00Z",
        head_sha="",
        started_at="2026-08-11T00:00:00Z",
    )
    # Mutant: under-count faces by 2 and inject a never-present name on every item.
    for entry, item in zip(manifest.entries, record["items"], strict=True):
        item["face_count"] = max(0, int(entry.face_count) - 2)
        rows = list(item.get("identities") or [])
        rows.append({"name": "ALWAYS-WRONG", "unpositioned": True})
        item["identities"] = rows

    oracle = _seeded_deviation_oracle(manifest)
    entries = _stamp_filled_entries(manifest)
    roster = sorted(set(getattr(manifest, "roster", []) or []))
    scored = score_run_record(
        record,
        entries,
        score_manifest_sha256=record["provenance"]["manifest_sha256"],
        manifest_roster=roster,
        rubric_gate="skip",
    )
    det = scored["faces"]["detection"]
    wrong_n = len(list((scored["faces"]["identification"].get("wrong_names") or [])))
    # Sanity: mutant really moved the real scorer away from the oracle.
    assert int(det["tp"]) != int(oracle["det_tp"]) or int(det["fn"]) != int(oracle["det_fn"])
    assert wrong_n != int(oracle["wrong_name_count"])

    with pytest.raises(AssertionError):
        _assert_scored_matches_oracle(scored, oracle)


def test_generator_stamps_metric_backing_refusals():  # VLM6-C-07
    """require_metric_backing is exercised by the generator, not only unit tests.

    Freeze corpus has 2/39 face_boxes (traps) so face_boxes is no longer
    corpus-vacuous for require_metric_backing (is_vacuous ⇔ populated==0). It
    remains under-sampled in coverage_gaps (2 < threshold 5). Other registry
    fields stay refused.
    """
    manifest = load_manifest(
        str(_MAN),
        skip_hash_verification=True,
        hash_skip_reason="test metadata-only; image bytes never opened",
        metadata_only=True,
    )
    record = build_run_record(
        manifest,
        fixture_revision="0" * 40,
        canonical_timestamp="2026-08-11T00:00:00Z",
        head_sha="",
        started_at="2026-08-11T00:00:00Z",
    )
    refusals = record["provenance"]["metric_backing_refusals"]
    assert "face_boxes" not in refusals  # 1 trap entry → not vacuous; still under-sampled
    for field in ("spatial_facts", "reference_facts", "demographic_cohort"):
        assert field in refusals
        assert "vacuous" in refusals[field] or "0/" in refusals[field]
    # Golden-alone path still refuses face_boxes (shared seed untouched).
    golden = load_manifest(
        str(_GOLDEN),
        skip_hash_verification=True,
        hash_skip_reason="test metadata-only; image bytes never opened",
        metadata_only=True,
    )
    g_record = build_run_record(
        golden,
        fixture_revision="0" * 40,
        canonical_timestamp="2026-08-11T00:00:00Z",
        head_sha="",
        started_at="2026-08-11T00:00:00Z",
    )
    assert "face_boxes" in g_record["provenance"]["metric_backing_refusals"]


def test_generator_md_renders_coverage_gaps(tmp_path: Path):  # VLM6-E-04
    """Scored MD must surface coverage_gaps (not only JSON provenance)."""
    _run, _rj, report_md, _sha = write_anchor(
        manifest_path=_GOLDEN,
        out_dir=tmp_path,
        stem=_STEM,
        manifest_stem=_MAN_STEM,
        head_sha="0" * 40,
        started_at="2026-08-11T00:00:00Z",
    )
    md = report_md.read_text()
    assert "Coverage gaps" in md
    assert "face_boxes" in md
    assert "non-evidential" in md
    assert "demographic_cohort" in md


def test_caption_anchor_corpus_includes_mixed_y_order_degraded_trap() -> None:
    """VLM6-R2-G-01 / wG3: ≥1 freeze image with named missing-y + sibling named with-y.

    Pre-extension caption golden had zero face_boxes, so labeled_y_missing_images
    was structurally 0 — the same blindness wF4 closed on the face corpus
    (DBG-11 / TEST-15). Shape must be *mixed* (not all-missing).
    """
    from scripts.eval_harness.face_metrics import labeled_order, named_box_name

    raw = build_caption_anchor_manifest(
        load_manifest(
            str(_GOLDEN),
            skip_hash_verification=True,
            hash_skip_reason="test metadata-only; image bytes never opened",
            metadata_only=True,
        )
    )
    record = json.loads(_RUN.read_text())
    run_ids = {int(i["media_id"]) for i in record["items"]}

    mixed = 0
    for entry in raw["entries"]:
        mid = int(entry["media_id"])
        assert mid in run_ids, f"manifest media_id={mid} missing from run-record"
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
        "need ≥1 image with named box missing y + sibling named box with y (VLM6-R2-G-01 caption freeze observability)"
    )
    # Committed freeze man must carry the same trap (not only the builder).
    committed = load_manifest(
        str(_MAN),
        skip_hash_verification=True,
        hash_skip_reason="test metadata-only; image bytes never opened",
        metadata_only=True,
    )
    assert any(int(e.media_id) == _TRAP_MEDIA_ID for e in committed.entries)


def test_caption_anchor_corpus_includes_centre_x_tie_positional_trap() -> None:
    """VLM6-R2-G-02: ≥1 freeze image with two named boxes at same x, distinct y.

    Pre-extension positional_images was structurally 0 — no image could
    distinguish a correct (x,y,name) key from a y-reversed one (HARM-06/07
    landed green). Media 40 is additive; media 39 stays the mixed-y trap.
    """
    from scripts.eval_harness.face_metrics import labeled_order, named_box_name
    from scripts.eval_harness.generate_determinism_anchor import (
        _NAME_POS_BOTTOM,
        _NAME_POS_TOP,
    )

    raw = build_caption_anchor_manifest(
        load_manifest(
            str(_GOLDEN),
            skip_hash_verification=True,
            hash_skip_reason="test metadata-only; image bytes never opened",
            metadata_only=True,
        )
    )
    ties = 0
    for entry in raw["entries"]:
        if int(entry["media_id"]) != _POS_TRAP_MEDIA_ID:
            continue
        boxes = list(entry.get("face_boxes") or [])
        named = []
        for b in boxes:
            name = named_box_name(b)
            if name is None or b.get("x") is None or b.get("y") is None:
                continue
            named.append((float(b["x"]), float(b["y"]), name))
        assert len(named) >= 2, "media 40 needs two named boxes with x and y"
        xs = {round(x, 6) for x, _y, _n in named}
        ys = {y for _x, y, _n in named}
        assert len(xs) == 1, f"centre x must tie; got {xs}"
        assert len(ys) >= 2, f"y values must be distinct; got {ys}"
        lo = labeled_order(boxes)
        assert lo.order_degraded is False
        assert lo.names == [_NAME_POS_TOP, _NAME_POS_BOTTOM]
        ties += 1
    assert ties == 1
    committed = load_manifest(
        str(_MAN),
        skip_hash_verification=True,
        hash_skip_reason="test metadata-only; image bytes never opened",
        metadata_only=True,
    )
    assert any(int(e.media_id) == _POS_TRAP_MEDIA_ID for e in committed.entries)


def test_y_reversed_labeled_order_goes_red_on_extended_caption_corpus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TEST-15 / VLM6-R2-G-02 acceptance: the ordering rule must be freeze-visible.

    Pre-extension the freeze had positional_images=0, so reversing the labeled
    L→R key changed nothing the anchor could observe — HARM-06/07 could have
    landed green against a y-blind rule. Media 40 ties centre x and separates y,
    and its run-record prediction is the swapped sequence, so the correct rule
    scores 0/2 with swap_images=1 while a y-reversed rule scores a perfect 2/2.

    Scoped like the labeled_y_missing control above: live vs mutated scoring on
    the committed man+run only, no comparison against the report digest.
    """
    from scripts.eval_harness import report as report_mod
    from scripts.eval_harness.face_metrics import LabeledOrderResult, labeled_order

    manifest = load_manifest(
        str(_MAN),
        skip_hash_verification=True,
        hash_skip_reason="test metadata-only; image bytes never opened",
        metadata_only=True,
    )
    record = json.loads(_RUN.read_text())
    entries = [e.model_dump() for e in manifest.entries]
    roster = sorted(set(manifest.roster))
    sha = record["provenance"]["manifest_sha256"]

    def _positional() -> dict:
        faces = score_run_record(
            record,
            entries,
            score_manifest_sha256=sha,
            manifest_roster=roster,
            rubric_gate="skip",
        )["faces"]
        assert int(faces["identity_ordering"]["positional_images"]) >= 1, (
            "freeze corpus scores no positional image — media 40 missing or its "
            "boxes no longer tie on centre x (mutation would be invisible)"
        )
        return faces["identification"]["positional"]

    live = _positional()
    assert int(live["compared_images"]) == 1
    assert int(live["position_total"]) == 2
    assert int(live["position_hits"]) == 0
    assert int(live["swap_images"]) == 1

    real_lo = labeled_order

    def _y_reversed(face_boxes):  # type: ignore[no-untyped-def]
        """Regression shape: y contributes nothing but sequence direction."""
        result = real_lo(face_boxes)
        return LabeledOrderResult(
            names=list(reversed(result.names)) if result.names else result.names,
            y_missing_count=result.y_missing_count,
            order_degraded=result.order_degraded,
        )

    monkeypatch.setattr(report_mod, "labeled_order", _y_reversed)
    blind = _positional()
    assert int(blind["position_hits"]) != int(live["position_hits"]), (
        f"y-reversed ordering still scores {live['position_hits']}/"
        f"{live['position_total']} — the freeze cannot see ordering-rule "
        "regressions (TEST-15 blindness not closed)"
    )
    assert int(blind["position_hits"]) == 2
    assert int(blind["swap_images"]) == 0


def test_labeled_y_missing_constant_zero_goes_red_on_extended_caption_corpus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TEST-15 / wG3 acceptance: constant-0 aggregation must diverge after extension.

    Pre-extension (Task 1): live counter was 0, so wiring aggregation to constant 0
    was invisible. Against the extended caption freeze man the live counter is ≥1;
    the same mutation yields 0 and is therefore freeze-detectable.

    Separating from pre-existing report-freeze staleness: this control scores
    live vs mutated aggregation on the extended man+run only — it does not
    compare to the committed report digest (regen stage).
    """
    from scripts.eval_harness import report as report_mod
    from scripts.eval_harness.face_metrics import LabeledOrderResult, labeled_order

    manifest = load_manifest(
        str(_MAN),
        skip_hash_verification=True,
        hash_skip_reason="test metadata-only; image bytes never opened",
        metadata_only=True,
    )
    record = json.loads(_RUN.read_text())
    entries = [e.model_dump() for e in manifest.entries]
    roster = sorted(set(manifest.roster))
    sha = record["provenance"]["manifest_sha256"]

    live = score_run_record(
        record,
        entries,
        score_manifest_sha256=sha,
        manifest_roster=roster,
        rubric_gate="skip",
    )["faces"]["identity_ordering"]
    live_n = int(live["labeled_y_missing_images"])
    assert live_n >= 1, (
        f"extended caption corpus must make labeled_y_missing_images non-zero; "
        f"got {live_n} (trap media missing or y not actually omitted)"
    )
    assert live.get("labeled_y_missing_paths"), "paths must name the degraded image(s)"
    # Media 39 is scored-but-disclosed (order_degraded), not folded into absence-only
    # order_unknown. Media 40 is the one positional image (G-02).
    assert int(live["order_unknown_excluded"]) == 38
    assert int(live["positional_images"]) >= 1

    real_lo = labeled_order

    def _blind_constant_zero(face_boxes):  # type: ignore[no-untyped-def]
        """Regression shape: strip order_degraded (constant-0 counter)."""
        result = real_lo(face_boxes)
        return LabeledOrderResult(names=result.names, y_missing_count=0, order_degraded=False)

    monkeypatch.setattr(report_mod, "labeled_order", _blind_constant_zero)
    blind = score_run_record(
        record,
        entries,
        score_manifest_sha256=sha,
        manifest_roster=roster,
        rubric_gate="skip",
    )["faces"]["identity_ordering"]
    blind_n = int(blind["labeled_y_missing_images"])
    assert blind_n == 0, "mutation must force counter to 0"
    assert blind_n != live_n, (
        f"constant-0 mutation still matches live ({live_n}) — freeze cannot see "
        "labeled_y_missing regressions (TEST-15 blindness not closed)"
    )


def test_corpus_traps_disclose_deliberate_caption_trap_media() -> None:
    """VLM6-R2-C-02 / EVAL-03: trap inventory on caption run-record provenance.

    Operators reading labeled_y_missing_images=1 need the sampling frame (which
    media, which gate). GoldenManifest extra=forbid blocks a top-level field —
    inventory lives on run-record provenance (wF4 precedent; do not bend model).
    """
    record = json.loads(_RUN.read_text())
    traps = list((record.get("provenance") or {}).get("corpus_traps") or [])
    assert traps, "provenance.corpus_traps must disclose deliberate trap media"
    # Generator constant filtered to present media must agree with committed stamp.
    present = {int(i["media_id"]) for i in record["items"]}
    expected = [t for t in _CORPUS_TRAPS if int(t["media_id"]) in present]
    assert traps == expected
    by_id = {int(t["media_id"]): t for t in traps}
    assert _TRAP_MEDIA_ID in by_id
    t = by_id[_TRAP_MEDIA_ID]
    assert "VLM6-R2-G-01" in str(t.get("kind") or "")
    assert "labeled_y_missing" in str(t.get("trips") or "")
    assert _POS_TRAP_MEDIA_ID in by_id
    t40 = by_id[_POS_TRAP_MEDIA_ID]
    assert "VLM6-R2-G-02" in str(t40.get("kind") or "")
    assert "positional_images" in str(t40.get("trips") or "")


def test_cli_score_s2a_freeze_ignores_empty_golden_images_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """VLM6-RV3-Q4-01: ``score --freeze-certification`` on the committed S2A pair.

    Existing-but-empty GOLDEN_IMAGES_DIR (fresh eval box) must exit 0.
    Mutation: removing metadata_only=True from _cmd_score / freeze helper
    fails with ManifestError: image file missing.
    """
    from scripts.eval_harness import cli as cli_mod

    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("GOLDEN_IMAGES_DIR", str(empty))
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setattr(cli_mod, "OUT_DIR", out)
    monkeypatch.chdir(tmp_path)
    rc = main(
        [
            "score",
            "--manifest",
            str(_MAN),
            "--run-record",
            str(_RUN),
            "--check-determinism",
            "--expect-report",
            str(_REPORT_JSON),
            "--rubric-gate",
            "skip",
            "--freeze-certification",
        ]
    )
    assert rc is None
    out_text = capsys.readouterr().out.lower()
    assert "freeze-certification" in out_text


def test_write_anchor_ignores_empty_golden_images_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """VLM6-RV3-Q4-01: caption-anchor generator never opens fixture bytes.

    Mutation: removing metadata_only=True from write_anchor load_manifest
    fails with ManifestError: image file missing.
    """
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("GOLDEN_IMAGES_DIR", str(empty))
    run_path, report_json, report_md, manifest_sha = write_anchor(
        manifest_path=_GOLDEN,
        out_dir=tmp_path / "out",
        stem="cap-q4",
        manifest_stem="cap-q4-man",
    )
    assert run_path.is_file()
    assert report_json.is_file()
    assert report_md.is_file()
    assert manifest_sha


def test_write_face_anchor_ignores_empty_golden_images_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """VLM6-RV3-Q4-01: face-anchor generator scores a synthetic roster; no image files.

    Mutation: removing metadata_only=True from write_face_anchor load_manifest
    fails with ManifestError: image file missing.
    """
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("GOLDEN_IMAGES_DIR", str(empty))
    man_path, run_path, report_json, report_md, manifest_sha = write_face_anchor(
        out_dir=tmp_path / "out",
        stem="face-q4",
        manifest_stem="face-q4-man",
    )
    assert man_path.is_file()
    assert run_path.is_file()
    assert report_json.is_file()
    assert report_md.is_file()
    assert manifest_sha
