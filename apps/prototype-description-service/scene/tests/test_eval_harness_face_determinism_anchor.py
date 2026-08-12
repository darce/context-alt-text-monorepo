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
_FROZEN_DIGESTS = {
    _MANIFEST.name: "1209733ed2b62e837449855690c15931dc0e76fcb24be8a715668020e05c8958",
    _RUN.name: "38a5168d051bc830ec1503a59858ff76e532807b9fbb7a8ccb1aaafadf7c10ff",
    _REPORT_JSON.name: "dcee8efa6aa0846c2ef22f054030bc5ee921093f20043f0d498247d471c29442",
    _REPORT_MD.name: "c29cc8591ba2b9fa560d8504deb3273bafeb499760f27a8475c3168594d59718",
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
    assert manifest_sha.startswith("19861fed")
    assert man_path.read_bytes() == _MANIFEST.read_bytes()
    assert run_path.read_bytes() == _RUN.read_bytes()
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
