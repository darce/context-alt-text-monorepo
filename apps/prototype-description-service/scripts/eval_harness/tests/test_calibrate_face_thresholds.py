"""FIR-6 S3a: calibrate_face_thresholds — determinism, schema fail-fast, pair-level K-fold."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from scripts.eval_harness.calibrate_face_thresholds import (
    DEFAULT_FMR_TARGET,
    REPORT_KIND,
    CalibrationError,
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
    validate_face_bakeoff_report,
    validate_golden_manifest,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
REPORT_PATH = FIXTURES / "face_bakeoff_report.v1.json"
MANIFEST_PATH = FIXTURES / "golden_manifest_strata.v1.json"


@pytest.fixture(scope="module")
def report_doc() -> dict:
    return json.loads(REPORT_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def manifest_doc() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def test_committed_fixture_validates(report_doc: dict, manifest_doc: dict) -> None:
    assert validate_face_bakeoff_report(report_doc) == []
    assert validate_golden_manifest(manifest_doc) == []
    assert report_doc["report_kind"] == REPORT_KIND
    assert set(report_doc["tau"]) >= {"tau_k", "tau_op"}
    assert report_doc["decisions"]
    for row in report_doc["decisions"]:
        for key in (
            "media_id",
            "box_index",
            "true_name",
            "predicted_name",
            "decision",
            "s_max",
            "fold",
            "name_star",
            "enrolled",
            "tau_k",
        ):
            assert key in row


def test_golden_on_committed_fixture(report_doc: dict, manifest_doc: dict) -> None:
    artifact = calibrate(report_doc, manifest_doc, fmr_target=DEFAULT_FMR_TARGET)
    assert artifact["artifact_kind"] == "face_threshold_calibration"
    assert artifact["protocol"]["kind"] == "pair_level_subject_disjoint_kfold"
    assert artifact["protocol"]["strangers_in_fit"] is False
    assert artifact["protocol"]["cross_fold_impostors_excluded"] is True
    assert artifact["protocol"]["k"] == 3
    assert "tau_proposed" in artifact["global"]
    assert set(artifact["per_stratum"]) >= {"people", "occlusion", "similar_people"}
    tax = artifact["fnmr_tax"]
    assert "global_vs_stratum" in tax
    assert "global_oact_coefficient" in tax
    assert tax["global_oact_coefficient"]["coefficient"] == 0.0
    # OACT tax at coefficient 0 is zero for every stratum that has OOF genuines.
    for name, row in tax["global_oact_coefficient"]["per_stratum_tax"].items():
        if row["base_fnmr"] is not None:
            assert row["tax"] == pytest.approx(0.0), name


def test_determinism_bit_identical_rerun() -> None:
    a1 = run_calibration_paths(REPORT_PATH, MANIFEST_PATH)
    a2 = run_calibration_paths(REPORT_PATH, MANIFEST_PATH)
    assert dumps_artifact(a1) == dumps_artifact(a2)
    # CLI path also bit-identical across invocations.
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        out1 = Path(tmp) / "c1.json"
        out2 = Path(tmp) / "c2.json"
        assert main(["--report", str(REPORT_PATH), "--manifest", str(MANIFEST_PATH), "--out", str(out1)]) == 0
        assert main(["--report", str(REPORT_PATH), "--manifest", str(MANIFEST_PATH), "--out", str(out2)]) == 0
        assert out1.read_text(encoding="utf-8") == out2.read_text(encoding="utf-8")


def test_schema_violation_report_exits_nonzero(tmp_path: Path, manifest_doc: dict) -> None:
    bad = deepcopy(json.loads(REPORT_PATH.read_text(encoding="utf-8")))
    del bad["tau"]
    report_path = tmp_path / "bad_report.json"
    manifest_path = tmp_path / "manifest.json"
    report_path.write_text(json.dumps(bad), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest_doc), encoding="utf-8")
    rc = main(["--report", str(report_path), "--manifest", str(manifest_path)])
    assert rc != 0


def test_schema_violation_manifest_exits_nonzero(tmp_path: Path, report_doc: dict) -> None:
    bad = {"entries": [{"media_id": 1}]}  # no domain/tags
    report_path = tmp_path / "report.json"
    manifest_path = tmp_path / "bad_manifest.json"
    report_path.write_text(json.dumps(report_doc), encoding="utf-8")
    manifest_path.write_text(json.dumps(bad), encoding="utf-8")
    rc = main(["--report", str(report_path), "--manifest", str(manifest_path)])
    assert rc != 0


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

    # Strangers never in fit identity set.
    assert all(name is not None for name in identity_folds)
    assert None not in identity_folds

    for held in range(k):
        fit_ids = fit_identities_for_held_fold(identity_folds, held)
        read_ids = read_identities_for_held_fold(identity_folds, held)
        assert fit_ids.isdisjoint(read_ids)
        assert not any(n is None for n in fit_ids)

        fit_trials = select_fit_trials(trials, fit_ids)
        # Strangers never in fit trials.
        assert all(t.probe_identity is not None for t in fit_trials)
        assert all(t.probe_identity in fit_ids for t in fit_trials)
        for t in fit_trials:
            if not t.is_genuine:
                assert t.gallery_identity in fit_ids

        read_trials = select_read_trials(trials, read_ids, fit_ids)
        assert_pair_level_disjointness(read_trials, fit_ids)
        # No read-pair touches a fit-fold identity.
        for t in read_trials:
            if t.probe_identity is not None:
                assert t.probe_identity not in fit_ids
                assert t.probe_identity in read_ids or t.probe_identity is None
            if t.gallery_identity is not None:
                assert t.gallery_identity not in fit_ids


def test_strangers_never_in_fit_scores(report_doc: dict, manifest_doc: dict) -> None:
    decisions = parse_decisions(report_doc)
    identity_folds = identity_fold_assignment(decisions)
    trials = build_trials(decisions, media_stratum_index(manifest_doc))
    fit_ids = fit_identities_for_held_fold(identity_folds, held_fold=0)
    fit_trials = select_fit_trials(trials, fit_ids)
    assert all(t.probe_identity is not None for t in fit_trials)
    # Committed fixture includes stranger decisions; they must not appear in fit.
    assert any(d.true_name is None for d in decisions)
    assert not any(t.probe_identity is None for t in fit_trials)


def test_cross_fold_impostors_excluded_from_read(report_doc: dict, manifest_doc: dict) -> None:
    decisions = parse_decisions(report_doc)
    identity_folds = identity_fold_assignment(decisions)
    trials = build_trials(decisions, media_stratum_index(manifest_doc))
    # Construct a synthetic cross-fold impostor that must be dropped.
    from scripts.eval_harness.calibrate_face_thresholds import ScoreTrial

    cross = ScoreTrial(
        score=0.9,
        probe_identity="Alice",  # fold 0
        gallery_identity="Carol",  # fold 1
        fold=0,
        media_id=999,
        strata=("people",),
        is_genuine=False,
    )
    held = 0
    fit_ids = fit_identities_for_held_fold(identity_folds, held)
    read_ids = read_identities_for_held_fold(identity_folds, held)
    selected = select_read_trials([*trials, cross], read_ids, fit_ids)
    assert all(
        not (
            t.probe_identity == "Alice"
            and t.gallery_identity == "Carol"
            and not t.is_genuine
        )
        for t in selected
    )


def test_calibrate_raises_on_invalid_report(manifest_doc: dict) -> None:
    with pytest.raises(CalibrationError):
        calibrate({"report_kind": "nope"}, manifest_doc)
