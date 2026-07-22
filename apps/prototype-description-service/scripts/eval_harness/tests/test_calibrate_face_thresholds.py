"""FIR-6 S3a: calibrate_face_thresholds — determinism, schema fail-fast, pair-level K-fold."""

from __future__ import annotations

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from scripts.eval_harness.calibrate_face_thresholds import (
    DEFAULT_FMR_TARGET,
    REPORT_DOC_KIND,
    REPORT_KIND,
    REPORT_SCHEMA,
    REQUIRED_DECISION_KEYS,
    REQUIRED_REPORT_KEYS,
    S_MAX_NO_MATCH,
    CalibrationError,
    ScoreTrial,
    assert_pair_level_disjointness,
    build_trials,
    calibrate,
    dumps_artifact,
    fit_identities_for_held_fold,
    identity_fold_assignment,
    main,
    media_stratum_index,
    parse_decisions,
    read_identities_for_held_fold,
    run_calibration_paths,
    select_fit_trials,
    select_read_trials,
    select_threshold,
    validate_face_bakeoff_report,
    validate_golden_manifest,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
REPORT_PATH = FIXTURES / "face_bakeoff_report.v1.json"
MANIFEST_PATH = FIXTURES / "golden_manifest_strata.v1.json"
MODULE = "scripts.eval_harness.calibrate_face_thresholds"

# Numeric golden pins from the committed fixture (guards median/mean, walk dir,
# abstain-vs-fail-open, rank-1-miss FNMR, single-count strangers).
GOLDEN_GLOBAL_TAU = 0.66
GOLDEN_GLOBAL_FNMR = 2.0 / 3.0
GOLDEN_GLOBAL_FMR = 0.0
GOLDEN_GLOBAL_N_GENUINE = 24
GOLDEN_GLOBAL_N_IMPOSTOR = 13
GOLDEN_OCCLUSION_TAU = 0.45
GOLDEN_SIMILAR_FNMR = 1.0
GOLDEN_N_EXCLUDED = 1
GOLDEN_N_STRANGERS = 4


@pytest.fixture(scope="module")
def report_doc() -> dict:
    return json.loads(REPORT_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def manifest_doc() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def test_committed_fixture_matches_fir5_envelope(report_doc: dict, manifest_doc: dict) -> None:
    assert validate_face_bakeoff_report(report_doc) == []
    assert validate_golden_manifest(manifest_doc) == []
    assert report_doc["schema"] == REPORT_SCHEMA
    assert report_doc["kind"] == REPORT_DOC_KIND
    assert report_doc["report_kind"] == REPORT_KIND
    assert set(report_doc) >= REQUIRED_REPORT_KEYS
    assert set(report_doc["tau"]) >= {"tau_k", "tau_op"}
    assert report_doc["decisions"]
    # At least one null s_max (FIR-5 -inf encoding) and one excluded row.
    assert any(row["s_max"] is None for row in report_doc["decisions"])
    assert any(row["excluded_single_face_recall"] is True for row in report_doc["decisions"])
    for row in report_doc["decisions"]:
        assert set(row) >= REQUIRED_DECISION_KEYS


def test_golden_numeric_pins_on_committed_fixture(
    report_doc: dict, manifest_doc: dict
) -> None:
    artifact = calibrate(report_doc, manifest_doc, fmr_target=DEFAULT_FMR_TARGET)
    assert artifact["artifact_kind"] == "face_threshold_calibration"
    assert artifact["protocol"]["kind"] == "pair_level_subject_disjoint_kfold"
    assert artifact["protocol"]["strangers_in_fit"] is False
    assert artifact["protocol"]["cross_fold_impostors_excluded"] is True
    assert artifact["protocol"]["oof_read_per_fold_tau"] is True
    assert artifact["protocol"]["zero_fit_impostor_policy"] == "abstain"
    assert artifact["protocol"]["strangers_single_count_by_fold"] is True
    assert artifact["protocol"]["k"] == 3
    assert artifact["protocol"]["n_excluded_single_face_recall"] == GOLDEN_N_EXCLUDED
    assert artifact["protocol"]["n_stranger_decisions"] == GOLDEN_N_STRANGERS

    g = artifact["global"]
    assert g["tau_proposed"] == pytest.approx(GOLDEN_GLOBAL_TAU)
    assert g["fnmr_oof"] == pytest.approx(GOLDEN_GLOBAL_FNMR)
    assert g["fmr_oof"] == pytest.approx(GOLDEN_GLOBAL_FMR)
    assert g["n_genuine_oof"] == GOLDEN_GLOBAL_N_GENUINE
    assert g["n_impostor_oof"] == GOLDEN_GLOBAL_N_IMPOSTOR
    assert g["n_abstained_folds"] == 0
    # Never fail-open to accept-everything.
    assert g["tau_proposed"] is not None and g["tau_proposed"] > 0.0

    assert set(artifact["per_stratum"]) >= {"people", "occlusion", "similar_people", "unknown"}
    occ = artifact["per_stratum"]["occlusion"]
    assert occ["tau_proposed"] == pytest.approx(GOLDEN_OCCLUSION_TAU)
    assert occ["tau_proposed"] is not None and occ["tau_proposed"] > 0.0
    sim = artifact["per_stratum"]["similar_people"]
    # Rank-1-miss genuines remain in FNMR denominator → full miss at high tau.
    assert sim["fnmr_oof"] == pytest.approx(GOLDEN_SIMILAR_FNMR)
    assert sim["n_genuine_oof"] == 3
    # unknown stratum has only stranger impostors → zero fit impostors → abstain.
    unk = artifact["per_stratum"]["unknown"]
    assert unk["tau_proposed"] is None
    assert unk["n_abstained_folds"] == 3

    tax = artifact["fnmr_tax"]
    assert "global_vs_stratum" in tax
    assert "global_oact_coefficient" in tax
    assert tax["global_oact_coefficient"]["coefficient"] == 0.0
    # Non-tautological OACT pin: coefficient 0 keeps elevated_tau == base_tau and tax 0
    # when a base tau exists; abstained strata stay null (not silently zero).
    for name, row in tax["global_oact_coefficient"]["per_stratum_tax"].items():
        if row["base_tau"] is None:
            assert row["tax"] is None, name
            assert row["elevated_tau"] is None, name
        else:
            assert row["elevated_tau"] == pytest.approx(row["base_tau"]), name
            assert row["tax"] == pytest.approx(0.0), name
    # Positive control: non-zero coefficient raises FNMR tax on a stratum with
    # genuines straddling the elevated threshold.
    tax_pos = calibrate(
        report_doc, manifest_doc, fmr_target=DEFAULT_FMR_TARGET, oact_coefficient=0.3
    )
    people_tax = tax_pos["fnmr_tax"]["global_oact_coefficient"]["per_stratum_tax"]["people"]
    assert people_tax["elevated_tau"] == pytest.approx(people_tax["base_tau"] + 0.3)
    # At least some strata show non-negative tax; elevated >= base FNMR.
    assert people_tax["elevated_fnmr"] is not None and people_tax["base_fnmr"] is not None
    assert people_tax["elevated_fnmr"] >= people_tax["base_fnmr"] - 1e-12


def test_select_threshold_unit_behavior() -> None:
    # Zero impostors → abstain (never 0.0).
    assert select_threshold([0.9, 0.8], [], fmr_target=0.01) is None
    # Walk ascending: lowest tau with FMR <= target.
    genuines = [0.9, 0.85, 0.7]
    impostors = [0.2, 0.15, 0.1, 0.05, 0.4]
    tau = select_threshold(genuines, impostors, fmr_target=0.01)
    assert tau is not None
    # At tau=0.4, FMR = 1/5 = 0.2 > 0.01; need higher.
    from scripts.eval_harness.calibrate_face_thresholds import fmr_at

    assert fmr_at(impostors, tau) is not None
    assert fmr_at(impostors, tau) <= 0.01 + 1e-12
    # Candidate just below max impostor would fail; tau must be > max impostor or
    # at a point where none of the 5 pass when target is tight.
    assert tau > max(impostors) or fmr_at(impostors, tau) == 0.0
    # Prefer lower of equal-FMR candidates: all impostors 0.1 → tau 0.1 meets FMR=0? 
    # scores >= 0.1 → all 1 accepted if tau=0.1? 0.1>=0.1 yes. Need tau > 0.1.
    imp2 = [0.1, 0.1, 0.1]
    tau2 = select_threshold([0.9], imp2, fmr_target=0.0)
    assert tau2 is not None and tau2 > 0.1
    # No candidate meets target at fmr_target=0 with impostor at 1.0 → fail-closed >= 1.0.
    tau3 = select_threshold([0.5], [1.0], fmr_target=0.0)
    assert tau3 is not None and tau3 >= 1.0


def test_s_max_null_parses_as_neg_inf(report_doc: dict) -> None:
    decisions = parse_decisions(report_doc)
    null_rows = [d for d in decisions if d.s_max == S_MAX_NO_MATCH]
    assert null_rows, "fixture must include s_max:null"
    assert all(d.true_name is None for d in null_rows)


def test_rank1_miss_emits_genuine_and_impostor(report_doc: dict, manifest_doc: dict) -> None:
    decisions = parse_decisions(report_doc)
    strata = media_stratum_index(manifest_doc)
    trials = build_trials(decisions, strata)
    # Media 301: Alice→Bob wrong_name on similar_people.
    sim_trials = [t for t in trials if t.media_id == 301]
    assert any(t.is_genuine and t.score == S_MAX_NO_MATCH for t in sim_trials)
    assert any(not t.is_genuine and t.gallery_identity == "Bob" for t in sim_trials)


def test_excluded_single_face_recall_skipped(report_doc: dict, manifest_doc: dict) -> None:
    decisions = parse_decisions(report_doc)
    assert any(d.excluded_single_face_recall and d.media_id == 501 for d in decisions)
    trials = build_trials(decisions, media_stratum_index(manifest_doc))
    assert not any(t.media_id == 501 for t in trials)


def test_stranger_single_count_across_folds(report_doc: dict, manifest_doc: dict) -> None:
    decisions = parse_decisions(report_doc)
    identity_folds = identity_fold_assignment(decisions)
    trials = build_trials(decisions, media_stratum_index(manifest_doc))
    strangers = [t for t in trials if t.probe_identity is None]
    assert len(strangers) == GOLDEN_N_STRANGERS
    k = len(report_doc["tau"]["tau_k"])
    pooled = 0
    for held in range(k):
        fit_ids = fit_identities_for_held_fold(identity_folds, held)
        read_ids = read_identities_for_held_fold(identity_folds, held)
        read = select_read_trials(trials, read_ids, fit_ids, held_fold=held)
        pooled += sum(1 for t in read if t.probe_identity is None)
    # Each stranger counted once, not K times.
    assert pooled == GOLDEN_N_STRANGERS


def test_determinism_subprocess_bit_identical(tmp_path: Path) -> None:
    """Bit-identical across real CLI process boundaries (not same-interpreter)."""
    out1 = tmp_path / "c1.json"
    out2 = tmp_path / "c2.json"
    base = [
        sys.executable,
        "-m",
        MODULE,
        "--report",
        str(REPORT_PATH),
        "--manifest",
        str(MANIFEST_PATH),
    ]
    r1 = subprocess.run(
        [*base, "--out", str(out1)],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[3]),
    )
    r2 = subprocess.run(
        [*base, "--out", str(out2)],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[3]),
    )
    assert r1.returncode == 0, r1.stderr
    assert r2.returncode == 0, r2.stderr
    assert out1.read_text(encoding="utf-8") == out2.read_text(encoding="utf-8")
    # Also same as in-process dumps.
    a = run_calibration_paths(REPORT_PATH, MANIFEST_PATH)
    assert out1.read_text(encoding="utf-8") == dumps_artifact(a)


def test_schema_violation_report_exits_nonzero(tmp_path: Path, manifest_doc: dict) -> None:
    bad = deepcopy(json.loads(REPORT_PATH.read_text(encoding="utf-8")))
    del bad["tau"]
    report_path = tmp_path / "bad_report.json"
    manifest_path = tmp_path / "manifest.json"
    report_path.write_text(json.dumps(bad), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest_doc), encoding="utf-8")
    rc = main(["--report", str(report_path), "--manifest", str(manifest_path)])
    assert rc != 0


def test_schema_violation_missing_top_level_key(report_doc: dict) -> None:
    bad = deepcopy(report_doc)
    del bad["gate_proposal"]
    errs = validate_face_bakeoff_report(bad)
    assert errs and "gate_proposal" in errs[0]


def test_schema_violation_manifest_isolated(tmp_path: Path, report_doc: dict) -> None:
    """Manifest schema failure must be the reason — not missing media join.

    Build a minimal valid-enough report whose media_ids are present in the
    intentionally-invalid manifest so a deleted schema check would still pass
    the media-join gate and only fail elsewhere if the schema path works.
    """
    # Manifest missing domain/tags → schema error. Media_id 101 exists in report.
    bad_manifest = {"entries": [{"media_id": 101}]}
    assert validate_golden_manifest(bad_manifest)
    assert "domain" in validate_golden_manifest(bad_manifest)[0] or "tags" in (
        validate_golden_manifest(bad_manifest)[0]
    )

    # CLI: only include report decisions for media_id 101 so join would succeed
    # if schema validation were deleted.
    slim = deepcopy(report_doc)
    slim["decisions"] = [d for d in slim["decisions"] if d["media_id"] == 101]
    report_path = tmp_path / "report.json"
    manifest_path = tmp_path / "bad_manifest.json"
    report_path.write_text(json.dumps(slim), encoding="utf-8")
    manifest_path.write_text(json.dumps(bad_manifest), encoding="utf-8")
    # Capture stderr message to pin the failure mode.
    import io
    from contextlib import redirect_stderr

    buf = io.StringIO()
    with redirect_stderr(buf):
        rc = main(["--report", str(report_path), "--manifest", str(manifest_path)])
    assert rc != 0
    err = buf.getvalue()
    assert "domain" in err or "tags" in err or "stratum" in err
    assert "absent from manifest" not in err


def test_schema_violation_missing_decision_key_exits_nonzero(
    tmp_path: Path, report_doc: dict, manifest_doc: dict
) -> None:
    bad = deepcopy(report_doc)
    del bad["decisions"][0]["s_max"]
    report_path = tmp_path / "report.json"
    manifest_path = tmp_path / "manifest.json"
    report_path.write_text(json.dumps(bad), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest_doc), encoding="utf-8")
    assert main(["--report", str(report_path), "--manifest", str(manifest_path)]) != 0


def test_pair_level_disjointness_property(report_doc: dict, manifest_doc: dict) -> None:
    decisions = parse_decisions(report_doc)
    identity_folds = identity_fold_assignment(decisions)
    strata = media_stratum_index(manifest_doc)
    trials = build_trials(decisions, strata)
    k = len(report_doc["tau"]["tau_k"])

    assert all(name is not None for name in identity_folds)
    assert None not in identity_folds

    for held in range(k):
        fit_ids = fit_identities_for_held_fold(identity_folds, held)
        read_ids = read_identities_for_held_fold(identity_folds, held)
        assert fit_ids.isdisjoint(read_ids)
        assert not any(n is None for n in fit_ids)

        fit_trials = select_fit_trials(trials, fit_ids)
        assert all(t.probe_identity is not None for t in fit_trials)
        assert all(t.probe_identity in fit_ids for t in fit_trials)
        for t in fit_trials:
            if not t.is_genuine:
                assert t.gallery_identity in fit_ids

        read_trials = select_read_trials(trials, read_ids, fit_ids, held_fold=held)
        assert_pair_level_disjointness(read_trials, fit_ids)
        for t in read_trials:
            if t.probe_identity is not None:
                assert t.probe_identity not in fit_ids
                assert t.probe_identity in read_ids
            if t.gallery_identity is not None:
                assert t.gallery_identity not in fit_ids


def test_strangers_never_in_fit_scores(report_doc: dict, manifest_doc: dict) -> None:
    decisions = parse_decisions(report_doc)
    identity_folds = identity_fold_assignment(decisions)
    trials = build_trials(decisions, media_stratum_index(manifest_doc))
    fit_ids = fit_identities_for_held_fold(identity_folds, held_fold=0)
    fit_trials = select_fit_trials(trials, fit_ids)
    assert all(t.probe_identity is not None for t in fit_trials)
    assert any(d.true_name is None for d in decisions)
    assert not any(t.probe_identity is None for t in fit_trials)


def test_cross_fold_impostors_excluded_with_positive_control(
    report_doc: dict, manifest_doc: dict
) -> None:
    decisions = parse_decisions(report_doc)
    identity_folds = identity_fold_assignment(decisions)
    trials = build_trials(decisions, media_stratum_index(manifest_doc))

    cross = ScoreTrial(
        score=0.9,
        probe_identity="Alice",  # fold 0
        gallery_identity="Carol",  # fold 1
        fold=0,
        media_id=999,
        strata=("people",),
        is_genuine=False,
    )
    # Positive control: in-fold impostor Alice↔Bob (both fold 0) must be kept.
    same = ScoreTrial(
        score=0.88,
        probe_identity="Alice",
        gallery_identity="Bob",
        fold=0,
        media_id=998,
        strata=("people",),
        is_genuine=False,
    )
    held = 0
    fit_ids = fit_identities_for_held_fold(identity_folds, held)
    read_ids = read_identities_for_held_fold(identity_folds, held)
    assert "Alice" in read_ids and "Bob" in read_ids
    selected = select_read_trials([*trials, cross, same], read_ids, fit_ids, held_fold=held)
    assert not any(
        t.probe_identity == "Alice" and t.gallery_identity == "Carol" and not t.is_genuine
        for t in selected
    )
    assert any(
        t.media_id == 998 and t.probe_identity == "Alice" and t.gallery_identity == "Bob"
        for t in selected
    ), "positive control in-fold impostor must be selected (test isolation)"


def test_calibrate_raises_on_invalid_report(manifest_doc: dict) -> None:
    with pytest.raises(CalibrationError):
        calibrate({"report_kind": "nope"}, manifest_doc)


def test_truncated_report_missing_envelope_keys_fails() -> None:
    """Invented subset (old hand fixture shape) must not validate."""
    truncated = {
        "report_kind": "face_bakeoff",
        "tau": {"tau_k": [0.4, 0.4], "tau_op": 0.4},
        "slices": {"people": {}},
        "counts": {},
        "decisions": [],
    }
    errs = validate_face_bakeoff_report(truncated)
    assert errs
    assert "missing required keys" in errs[0]
