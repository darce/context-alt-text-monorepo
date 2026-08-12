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

import pytest

from scripts.eval_harness.cli import (
    _check_score_determinism_cross_process,
    _determinism_artifact_dir,
    _manifest_sha,
)
from scripts.eval_harness.generate_determinism_anchor import (
    _coverage_gaps,
    _DEFAULT_STEM,
    _identity_rows,
    _predicted_face_count,
    build_run_record,
    write_anchor,
)
from scripts.eval_harness.manifest import (
    FaceBox,
    METRIC_BACKING_SLICE_THRESHOLD,
    SHIPPED_CORPUS_COVERAGE_GAPS,
    compute_corpus_coverage_gaps,
    load_manifest,
)

_REPO_ROOT = Path(__file__).resolve().parents[4]  # monorepo root
_SERVICE_ROOT = Path(__file__).resolve().parents[2]  # apps/prototype-description-service
_GOLDEN = _SERVICE_ROOT / "scene" / "tests" / "seed" / "golden.json"
_ANCHOR_DIR = _REPO_ROOT / "docs" / "tasks" / "vlm" / "bakeoff-results"
_STEM = _DEFAULT_STEM
_RUN = _ANCHOR_DIR / f"{_STEM}.json"
_REPORT_JSON = _ANCHOR_DIR / f"{_STEM}-report.json"
_REPORT_MD = _ANCHOR_DIR / f"{_STEM}-report.md"

# File digests of the committed triple — update only when intentionally regenerating.
# Regenerated VLM6-lb1 after default-on hash verification unblocked the generator
# (manifest_sha256 prefix 83bfdc4e; prior freeze 859a083e was stale vs current golden/schema).
# Regenerated again after the wave-C merge: scoring gained `strata`, `placement`,
# `hallucination`, positional `compared_images`/`excluded_images`, and the
# `wrong_name_images`/`wrong_name_assertions` verdict split. Cause (2) of the
# ANCHOR_MISMATCH message — deliberate scoring change, stale freeze. The run-record
# digest is unchanged (4c80fdbf), which is the evidence that only scoring moved:
# the recorded model output is byte-identical, so this is not corruption.
# Regenerated again for VLM6-R4-03: the markdown now discloses that placement is
# vacuous (claims=0). Run-record and report JSON digests are unchanged — only the
# .md moved, which is the evidence that disclosure changed and scoring did not.
# Regenerated again for VLM6-R2-03: provenance gained `note` + `coverage_gaps`
# (derived from the manifest, not hand-stamped) so an operator reading the anchor
# alone learns which scorers the corpus leaves nothing to assert against. Here the
# .md digest is the one that did NOT move — the disclosure is in the two JSON
# documents' provenance, and the scored markdown is byte-identical.
_FROZEN_DIGESTS = {
    _RUN.name: "978aefef41bca050b278a74c527f9e656367942fab67909e95fee47ff0a5957e",
    _REPORT_JSON.name: "29f72112187b06d5ab21bba1660c6215c7f8bc1fa660b6dffe801c9a8522fc23",
    _REPORT_MD.name: "97d6132b6842175ec624776347af0596248fc702fc05564e6bbb04a5e3856dcb",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("name,expected", list(_FROZEN_DIGESTS.items()))
def test_committed_anchor_digests_match_frozen(name: str, expected: str) -> None:
    """Pin machine-diffable digests so a silent rewrite of the freeze goes red (TEST-15 base)."""
    path = _ANCHOR_DIR / name
    assert path.is_file(), f"missing committed anchor artifact: {path}"
    assert _sha256(path) == expected


def test_generator_regenerates_byte_identical_committed_anchor(tmp_path: Path) -> None:
    """Generator is the source of truth — re-run must match the freeze byte-for-byte."""
    run_path, report_json, report_md, manifest_sha = write_anchor(
        manifest_path=_GOLDEN,
        out_dir=tmp_path,
        stem=_STEM,
        head_sha="0" * 40,
        started_at="2026-08-11T00:00:00Z",
    )
    # Metadata-only: compares generation-time sha to loader sha; never opens image bytes.
    expected_sha = _manifest_sha(load_manifest(str(_GOLDEN), skip_hash_verification=True))
    assert manifest_sha == expected_sha
    assert manifest_sha.startswith("83bfdc4e")
    assert run_path.read_bytes() == _RUN.read_bytes()
    assert report_json.read_bytes() == _REPORT_JSON.read_bytes()
    assert report_md.read_bytes() == _REPORT_MD.read_bytes()


def test_committed_run_record_identity_rows_are_dicts_and_manifest_sha_computed() -> None:
    """Greenfield shape: no bare-string identities; sha was generation-time computed."""
    record = json.loads(_RUN.read_text())
    # Metadata-only: provenance sha check against roster/entries; never opens image bytes.
    assert record["provenance"]["manifest_sha256"] == _manifest_sha(
        load_manifest(str(_GOLDEN), skip_hash_verification=True)
    )
    assert len(record["items"]) == 37
    for item in record["items"]:
        for row in item["identities"]:
            assert isinstance(row, dict)
            assert "name" in row
        assert (item.get("describe") or {}).get("adapter") == "seeded"


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
            str(_GOLDEN),
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


def test_expect_report_matches_committed_freeze_green(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Clean --expect-report against the committed freeze still exits green (discrimination)."""
    run_copy = tmp_path / _RUN.name
    run_copy.write_bytes(_RUN.read_bytes())
    # Copy freeze into tmp so we never risk writing beside committed artifacts.
    expect_copy = tmp_path / _REPORT_JSON.name
    expect_copy.write_bytes(_REPORT_JSON.read_bytes())

    json_doc, _md = _check_score_determinism_cross_process(
        run_copy,
        str(_GOLDEN),
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
            str(_GOLDEN),
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
    """The anchor must name what the corpus leaves unscored, in the anchor itself.

    Generator-side disclosure (fresh run) must include every SHIPPED registry
    field with populated/threshold counts — not a boolean that hides under-
    sampled fields (VLM6-C-01 / C-02).
    """
    # Prefer generator output over the frozen committed artifact (regen deferred).
    manifest = load_manifest(str(_GOLDEN), skip_hash_verification=True)
    gaps = compute_corpus_coverage_gaps(manifest.entries)
    assert set(gaps) == set(SHIPPED_CORPUS_COVERAGE_GAPS)
    assert "demographic_cohort" in gaps  # VLM6-C-02: registry-driven
    for field, info in gaps.items():
        assert info["populated"] == 0
        assert info["total"] == 37
        assert info["threshold"] == METRIC_BACKING_SLICE_THRESHOLD
        assert info["below_threshold"] is True
        assert info["pi_zero"] is True
        assert "0/37" in info["reason"]
    assert "right-names-on-wrong-faces" in gaps["face_boxes"]["reason"]


def test_coverage_gaps_keep_under_sampled_field_after_single_population():  # VLM6-C-01 / TEST-15
    """One schema-valid face_boxes row must NOT silence the gap (VLM6-C-01 / C-08).

    Prior control used an invalid `{width,height}` dict via model_copy (skips
    re-validation) and asserted the key disappeared — locking the wrong boolean
    behaviour. A 1/N population stays below the slice threshold.
    """
    manifest = load_manifest(str(_GOLDEN), skip_hash_verification=True)
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
    assert gaps["face_boxes"]["total"] == 37
    assert gaps["face_boxes"]["below_threshold"] is True  # 1 < threshold
    assert gaps["face_boxes"]["pi_zero"] is False
    # Untouched registry fields still reported.
    assert gaps["spatial_facts"]["pi_zero"] is True
    assert gaps["reference_facts"]["pi_zero"] is True
    assert gaps["demographic_cohort"]["pi_zero"] is True


def test_coverage_gaps_meet_threshold_when_fully_populated():  # VLM6-C-01 discrimination
    """Only at/above the slice threshold does below_threshold flip false."""
    manifest = load_manifest(str(_GOLDEN), skip_hash_verification=True)
    box = FaceBox(x=0.4, y=0.4, w=0.2, h=0.2, source="iptc")
    entries = [
        e.model_copy(update={"face_boxes": [box]}) for e in manifest.entries
    ]
    gaps = compute_corpus_coverage_gaps(entries)
    assert gaps["face_boxes"]["populated"] == 37
    assert gaps["face_boxes"]["below_threshold"] is False
    assert gaps["face_boxes"]["pi_zero"] is False


def test_seeded_predictions_are_not_pure_gt_echo():  # VLM6-C-04 / TEST-15
    """Fixture face/identity predictions deviate from GT so metrics can go red."""
    manifest = load_manifest(str(_GOLDEN), skip_hash_verification=True)
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

    # Predicted helpers themselves must be able to go red vs pure echo.
    entry0 = manifest.entries[0]
    assert _predicted_face_count(entry0, seed_index=0) != entry0.face_count or entry0.face_count == 0
    # seed_index 0 with names → drop last
    if entry0.present_identities:
        rows = _identity_rows(entry0, seed_index=0)
        assert {r["name"] for r in rows} != set(entry0.present_identities) or len(entry0.present_identities) == 0


def test_generator_stamps_metric_backing_refusals():  # VLM6-C-07
    """require_metric_backing is exercised by the generator, not only unit tests."""
    manifest = load_manifest(str(_GOLDEN), skip_hash_verification=True)
    record = build_run_record(
        manifest,
        fixture_revision="0" * 40,
        canonical_timestamp="2026-08-11T00:00:00Z",
        head_sha="",
        started_at="2026-08-11T00:00:00Z",
    )
    refusals = record["provenance"]["metric_backing_refusals"]
    for field in ("face_boxes", "spatial_facts", "reference_facts", "demographic_cohort"):
        assert field in refusals
        assert "vacuous" in refusals[field] or "0/" in refusals[field]


def test_generator_md_renders_coverage_gaps(tmp_path: Path):  # VLM6-E-04
    """Scored MD must surface coverage_gaps (not only JSON provenance)."""
    _run, _rj, report_md, _sha = write_anchor(
        manifest_path=_GOLDEN,
        out_dir=tmp_path,
        stem=_STEM,
        head_sha="0" * 40,
        started_at="2026-08-11T00:00:00Z",
    )
    md = report_md.read_text()
    assert "Coverage gaps" in md
    assert "face_boxes" in md
    assert "non-evidential" in md
    assert "demographic_cohort" in md
