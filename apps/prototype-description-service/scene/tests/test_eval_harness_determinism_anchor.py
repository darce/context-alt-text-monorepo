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
    build_run_record,
    write_anchor,
)
from scripts.eval_harness.manifest import (
    FaceBox,
    GoldenManifest,
    METRIC_BACKING_SLICE_THRESHOLD,
    SHIPPED_CORPUS_COVERAGE_GAPS,
    compute_corpus_coverage_gaps,
    load_manifest,
)
from scripts.eval_harness.report import score_run_record

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
# Regenerated fx7 (this lane's branch) after vacuity honesty + seeded deviation
# + centre-order positional + category-vacuity verdict wiring landed. Headline
# moves: detection/identification leave 1.0, fabricated_fact_rate 0.0→None,
# verdict pass_ungated→fail (seeded wrong names + vacuity), head_sha→null +
# fixture_revision, coverage_gaps structured with demographic_cohort.
# Regenerated hx1 (wave-C regen) after gx2 S2-06/S2-07 vacuity honesty + gx4
# S4-04 pin-mode started_at:null. Cause (2) only — see .s2a/vlm6-hx1-report.md.
_FROZEN_DIGESTS = {
    _RUN.name: "d105f3adccb2f5745e221d518649217562b836436569889b19a2c2471156dbe9",
    _REPORT_JSON.name: "c2fcfa3407ff62254556201cc35dfcb25eb4a46105e0764fe4b25a347423b0e6",
    _REPORT_MD.name: "dc7bf05496e37883bbe3e4cdf336f63a4e5bd489ed14aaf7bfcf439e04e14f3b",
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


def _oracle_predicted_identity_names(
    *, present_identities: list[str], seed_index: int
) -> list[str]:
    """Independent reimplementation of the generator's identity seed rules."""
    names = list(present_identities)
    if names and seed_index % 5 == 0:
        names = names[:-1]
    if present_identities and seed_index % 9 == 0 and seed_index % 5 != 0:
        names = names + [f"Fixture-Wrong-{seed_index}"]
    return names


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
        pred_faces = _oracle_predicted_face_count(
            face_count=int(entry.face_count), seed_index=index
        )
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
        f"detection fn={det['fn']} below oracle lower bound {oracle['det_fn']} "
        "(scorer may be GT-echoing; VLM6-S4-01)"
    )
    assert int(det["fp"]) >= int(oracle["det_fp"]), (
        f"detection fp={det['fp']} below oracle lower bound {oracle['det_fp']} "
        "(scorer may be GT-echoing; VLM6-S4-01)"
    )
    assert len(wrong_names) >= int(oracle["wrong_name_count"]), (
        f"wrong_names={len(wrong_names)} below oracle lower bound "
        f"{oracle['wrong_name_count']} (VLM6-S4-01)"
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


def test_seeded_predictions_are_not_pure_gt_echo():  # VLM6-C-04 / VLM6-S4-01 / TEST-15
    """Fixture face/identity predictions deviate from GT so metrics can go red.

    Existence-of-deviation alone is not enough (S4-01): a scorer that uses GT
    for both predicted and labeled stays green on existence while producing
    perfect detection (P/R 1.0). After build_run_record we score once with the
    **real** scorer and pin bounds from an *independent* oracle over the
    corpus — never from freeze digests, never from generator private helpers
    (RV3-01 / TEST-15).
    """
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

    # Independent seed predicates themselves must be able to go red vs pure echo.
    entry0 = manifest.entries[0]
    pred0 = _oracle_predicted_face_count(
        face_count=int(entry0.face_count), seed_index=0
    )
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

    entries = [e.model_dump() for e in manifest.entries]
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
    manifest = load_manifest(str(_GOLDEN), skip_hash_verification=True)
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
    entries = [e.model_dump() for e in manifest.entries]
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
