"""FIR-6 S3a: calibrate_face_thresholds — determinism, schema fail-fast, pair-level K-fold."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

import scripts.eval_harness.calibrate_face_thresholds as calibrate_module
from scripts.eval_harness.accept_predicate import accepts, is_fpi
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
    assert_fit_side_impostor_disjointness,
    assert_pair_level_disjointness,
    build_trials,
    calibrate,
    dumps_artifact,
    fit_identities_for_held_fold,
    fmr_at,
    fnmr_at,
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
# Candidate taus are midpoints, keeping the selected operating point off the
# observed scores so JANUS FPI and operational acceptance cannot disagree.
GOLDEN_GLOBAL_TAU = 0.62
GOLDEN_GLOBAL_FNMR = 15.0 / 24.0
GOLDEN_GLOBAL_FMR = 0.0
GOLDEN_GLOBAL_N_GENUINE = 24
GOLDEN_GLOBAL_N_IMPOSTOR = 13
GOLDEN_OCCLUSION_TAU = 0.415
GOLDEN_SIMILAR_FNMR = 1.0
GOLDEN_N_EXCLUDED = 1
GOLDEN_N_STRANGERS = 4
# Non-tautological OACT positive control at coefficient 0.3 (people stratum).
GOLDEN_PEOPLE_OACT_TAX_03 = 3.0 / 7.0


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
    assert "publishable" in REQUIRED_DECISION_KEYS
    for row in report_doc["decisions"]:
        assert set(row) >= REQUIRED_DECISION_KEYS
        assert isinstance(row["publishable"], bool)


def test_golden_numeric_pins_on_committed_fixture(
    report_doc: dict, manifest_doc: dict
) -> None:
    artifact = calibrate(report_doc, manifest_doc, fmr_target=DEFAULT_FMR_TARGET)
    assert artifact["artifact_kind"] == "face_threshold_calibration"
    assert artifact["protocol"]["kind"] == "pair_level_subject_disjoint_kfold"
    assert artifact["protocol"]["strangers_in_fit"] is False
    assert artifact["protocol"]["cross_fold_impostors_excluded"] is True
    assert artifact["protocol"]["fit_side_impostors_require_both_in_fit"] is True
    assert artifact["protocol"]["oof_read_per_fold_tau"] is True
    assert artifact["protocol"]["zero_fit_impostor_policy"] == "abstain"
    assert artifact["protocol"]["all_nonfinite_impostor_policy"] == "abstain"
    assert artifact["protocol"]["strangers_single_count_by_fold"] is True
    assert artifact["protocol"]["strangers_count_under_gallery_fold"] is True
    assert artifact["protocol"]["rank1_miss_genuine_at_neg_inf"] is True
    assert artifact["protocol"]["selection_rule_pre_registered"] is True
    assert artifact["protocol"]["deterministic"] is True
    assert artifact["protocol"]["k"] == 3
    assert artifact["protocol"]["n_excluded_single_face_recall"] == GOLDEN_N_EXCLUDED
    assert artifact["protocol"]["n_stranger_decisions"] == GOLDEN_N_STRANGERS
    # Rank-1-miss treatment must appear in the public disclosure, not only docs.
    disclosure = artifact["protocol"]["disclosure"]
    assert "rank-1-miss" in disclosure.lower() or "rank1" in disclosure.lower()
    assert "-inf" in disclosure or "neg_inf" in disclosure.lower() or "−inf" in disclosure
    assert "insufficient_impostor_evidence" in disclosure
    # FIR6RC-07: pre-registration + determinism lines in the protocol disclosure.
    assert "pre-registered" in disclosure.lower()
    assert "deterministic" in disclosure.lower()
    assert "fit-side" in disclosure.lower() or "fit set" in disclosure.lower()
    # FIR6V11-02: silent-drop + clustering note + named sampling frames + honest tax labels.
    assert artifact["protocol"]["clustering_note"]
    assert "pair-level" in artifact["protocol"]["clustering_note"].lower()
    assert "silent_drop_disclosure" in artifact["protocol"]
    assert "excluded_single_face_recall" in artifact["protocol"]["silent_drop_disclosure"]
    assert "sampling_frames" in artifact["protocol"]
    assert (
        artifact["protocol"]["sampling_frames"]["fnmr_tax_genuine"]
        == "stratum_oof_genuine_non_abstained_folds"
    )
    assert "n_silent_drop_decisions" in artifact["protocol"]
    # FIR6V11-02 / AUDIT-07: every named frame defines population, sampling
    # unit, and observation unit, with undercoverage counted adjacent to the
    # denominators it is dropped from.
    frame_defs = artifact["protocol"]["sampling_frame_definitions"]
    named_frames = set(artifact["protocol"]["sampling_frames"].values())
    assert named_frames <= set(frame_defs)
    for frame_name, frame_def in frame_defs.items():
        assert frame_def["target_population"], frame_name
        assert frame_def["sampling_unit"], frame_name
        assert frame_def["observation_unit"], frame_name
        assert "undercoverage" in frame_def, frame_name
    assert (
        frame_defs["held_fold_genuine_non_abstained"]["undercoverage"][
            "excluded_single_face_recall_rows"
        ]
        == GOLDEN_N_EXCLUDED
    )
    # FIR6V11-02 / AUDIT-11: face-level trial counts vs identity-level fold
    # clustering must be disclosed; raw n is not effective independent n.
    clustering = artifact["protocol"]["trial_clustering_note"]
    assert "face-level" in clustering
    assert "identity level" in clustering or "identity-level" in clustering
    assert "deff" in clustering

    g = artifact["global"]
    assert g["tau_proposed"] == pytest.approx(GOLDEN_GLOBAL_TAU)
    assert g["fnmr_oof"] == pytest.approx(GOLDEN_GLOBAL_FNMR)
    assert g["fmr_oof"] == pytest.approx(GOLDEN_GLOBAL_FMR)
    assert g["n_genuine_oof"] == GOLDEN_GLOBAL_N_GENUINE
    assert g["n_impostor_oof"] == GOLDEN_GLOBAL_N_IMPOSTOR
    assert g["n_abstained_folds"] == 0
    assert g["insufficient_impostor_evidence"] is False
    # Never fail-open to accept-everything.
    assert g["tau_proposed"] is not None and g["tau_proposed"] > 0.0

    assert set(artifact["per_stratum"]) >= {"people", "occlusion", "similar_people", "unknown"}
    occ = artifact["per_stratum"]["occlusion"]
    assert occ["tau_proposed"] == pytest.approx(GOLDEN_OCCLUSION_TAU)
    assert occ["tau_proposed"] is not None and occ["tau_proposed"] > 0.0
    assert occ["insufficient_impostor_evidence"] is False
    sim = artifact["per_stratum"]["similar_people"]
    # Rank-1-miss genuines remain in FNMR denominator → full miss at high tau.
    assert sim["fnmr_oof"] == pytest.approx(GOLDEN_SIMILAR_FNMR)
    assert sim["n_genuine_oof"] == 3
    # unknown stratum has only stranger impostors → zero fit impostors → abstain.
    unk = artifact["per_stratum"]["unknown"]
    assert unk["tau_proposed"] is None
    assert unk["n_abstained_folds"] == 3
    assert unk["insufficient_impostor_evidence"] is True
    assert "insufficient" in json.dumps(artifact)

    tax = artifact["fnmr_tax"]
    assert "global_vs_stratum" in tax
    assert "global_oact_coefficient" in tax
    assert tax["global_oact_coefficient"]["coefficient"] == 0.0
    # FIR6V11-02: honest tax labels + named sampling frames on denominators.
    for name, row in tax["global_vs_stratum"].items():
        assert "stratum_fnmr_at_global_tau" in row, name
        assert row["global_fnmr"] == row["stratum_fnmr_at_global_tau"]
        assert row["sampling_frame"]["genuine_scores"] == (
            "stratum_oof_genuine_non_abstained_folds"
        )
        assert "n_genuine" in row["sampling_frame"]
        # AUDIT-07: impostor pool size published alongside for frame
        # completeness (FNMR denominators remain genuine-only).
        assert "n_impostor" in row["sampling_frame"]
        assert row["sampling_frame"]["n_impostor"] == (
            artifact["per_stratum"][name]["n_impostor_oof"]
        )
    # Non-tautological OACT pin: coefficient 0 keeps elevated_tau == base_tau and tax 0
    # when a base tau exists; abstained strata stay null (not silently zero).
    for name, row in tax["global_oact_coefficient"]["per_stratum_tax"].items():
        if row["base_tau"] is None:
            assert row["tax"] is None, name
            assert row["elevated_tau"] is None, name
        else:
            assert row["elevated_tau"] == pytest.approx(row["base_tau"]), name
            assert row["tax"] == pytest.approx(0.0), name
        assert row["sampling_frame"]["genuine_scores"] == (
            "stratum_oof_genuine_non_abstained_folds"
        )
        assert "n_genuine" in row["sampling_frame"], name
        assert "n_impostor" in row["sampling_frame"], name
    # Positive control: non-zero coefficient raises FNMR tax on a stratum with
    # genuines straddling the elevated threshold — strict numeric pin.
    tax_pos = calibrate(
        report_doc, manifest_doc, fmr_target=DEFAULT_FMR_TARGET, oact_coefficient=0.3
    )
    people_tax = tax_pos["fnmr_tax"]["global_oact_coefficient"]["per_stratum_tax"]["people"]
    assert people_tax["elevated_tau"] == pytest.approx(people_tax["base_tau"] + 0.3)
    assert people_tax["elevated_fnmr"] is not None and people_tax["base_fnmr"] is not None
    assert people_tax["elevated_fnmr"] > people_tax["base_fnmr"]
    assert people_tax["tax"] == pytest.approx(GOLDEN_PEOPLE_OACT_TAX_03)
    assert people_tax["tax"] > 0.0


def test_select_threshold_unit_behavior() -> None:
    # Zero impostors → abstain (never 0.0).
    assert select_threshold([0.9, 0.8], [], fmr_target=0.01) is None
    # All non-finite impostors → abstain (never fail-open to 0.0).
    assert (
        select_threshold([0.9, 0.8], [float("-inf"), float("-inf")], fmr_target=0.01)
        is None
    )
    # Empty genuines still select from impostors only.
    tau_eg = select_threshold([], [0.2, 0.1], fmr_target=0.01)
    assert tau_eg is not None
    assert fmr_at([0.2, 0.1], tau_eg) is not None
    assert fmr_at([0.2, 0.1], tau_eg) <= 0.01 + 1e-12
    # Walk ascending: lowest tau with FMR <= target.
    genuines = [0.9, 0.85, 0.7]
    impostors = [0.2, 0.15, 0.1, 0.05, 0.4]
    tau = select_threshold(genuines, impostors, fmr_target=0.01)
    assert tau is not None
    assert fmr_at(impostors, tau) is not None
    assert fmr_at(impostors, tau) <= 0.01 + 1e-12
    # Tight target needs FMR=0; select the first midpoint above the maximum
    # impostor rather than tying that observed score.
    assert tau == pytest.approx((max(impostors) + 0.7) / 2.0)
    assert fmr_at(impostors, tau) == 0.0
    # One unique finite impostor score is evidence-poor and must abstain.
    imp2 = [0.1, 0.1, 0.1]
    tau2 = select_threshold([0.9], imp2, fmr_target=0.0)
    assert tau2 is None
    # A single finite impostor score also abstains rather than presenting a
    # boundary as a calibrated operating point.
    tau3 = select_threshold([0.5], [1.0], fmr_target=0.0)
    assert tau3 is None


def test_all_negative_impostors_use_open_boundary() -> None:
    tau = select_threshold([0.8], [-0.4, -0.2], fmr_target=0.0)
    assert tau is not None
    assert tau > -0.2
    assert tau != 0.0
    assert fmr_at([-0.4, -0.2], tau) == pytest.approx(0.0)


@pytest.mark.parametrize(
    ("genuine", "impostor"),
    [
        ([0.9, 0.8], [0.2, 0.1]),
        ([0.9, 0.9], [0.2, 0.2, 0.1]),
        ([0.5801, 0.7], [0.58, 0.3]),
    ],
)
def test_selected_tau_is_not_an_observed_score(
    genuine: list[float], impostor: list[float]
) -> None:
    tau = select_threshold(genuine, impostor, fmr_target=0.0)
    assert tau is not None
    assert tau not in genuine + impostor


def test_midpoint_removes_old_fixture_tie_disagreement() -> None:
    genuine = [0.66, 0.72]
    impostor = [0.58, 0.31]
    tau = select_threshold(genuine, impostor, fmr_target=0.0)
    assert tau == pytest.approx((0.58 + 0.66) / 2.0)
    assert all(is_fpi(score, tau) == accepts(score, tau) for score in genuine + impostor)


def test_select_threshold_abstain_and_fail_closed_paths() -> None:
    assert select_threshold([0.8], [], fmr_target=0.0) is None
    assert select_threshold([0.8], [float("-inf")], fmr_target=0.0) is None
    # The upper open boundary rejects an observed peak without tying it.
    tau = select_threshold([], [2.0, 3.0], fmr_target=0.0)
    assert tau is not None and tau > 3.0
    assert fmr_at([2.0, 3.0], tau) == pytest.approx(0.0)


def test_oof_rates_are_rescored_at_published_median_and_keep_tie_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Public OOF rates describe tau_proposed, including strict FPI ties."""
    read_by_fold = {
        held: [
            ScoreTrial(
                score=0.4,
                probe_identity=f"P{held}",
                gallery_identity=f"P{held}",
                fold=held,
                media_id=held,
                strata=("people",),
                is_genuine=True,
            ),
            ScoreTrial(
                score=0.4,
                probe_identity=None,
                gallery_identity=f"P{held}",
                fold=held,
                media_id=100 + held,
                strata=("people",),
                is_genuine=False,
            ),
        ]
        for held in range(3)
    }
    fit_taus = iter([0.2, 0.4, 0.8])
    monkeypatch.setattr(calibrate_module, "select_fit_trials", lambda *_args: [])
    monkeypatch.setattr(
        calibrate_module,
        "select_read_trials",
        lambda _trials, _read_ids, _fit_ids, *, held_fold: read_by_fold[held_fold],
    )
    monkeypatch.setattr(
        calibrate_module,
        "select_threshold",
        lambda *_args, **_kwargs: next(fit_taus),
    )

    raw = calibrate_module._oof_metrics_for_stratum(
        [], {"P0": 0, "P1": 1, "P2": 2}, 3, stratum="people", fmr_target=0.0
    )
    assert raw["tau_proposed"] == pytest.approx(0.4)
    # At fold taus the first fold would miss/accept and the third would miss;
    # at the published median both score ties are hits/non-FPI.
    assert raw["fnmr_oof"] == pytest.approx(0.0)
    assert raw["fmr_oof"] == pytest.approx(0.0)
    assert raw["fold_rows"][1]["fmr_oof_fold"] == pytest.approx(0.0)
    assert raw["fold_rows"][1]["fnmr_oof_fold"] == pytest.approx(0.0)


def test_fmr_at_and_fnmr_at_direct() -> None:
    assert fmr_at([], 0.5) is None
    assert fnmr_at([], 0.5) is None
    # JANUS 2.3.4 FPI: accepted iff score > tau. Tie at 0.4 is not an FPI, so
    # only 0.9 of {0.9, 0.4, 0.1} is accepted (1/3), not 2/3.
    assert fmr_at([0.9, 0.4, 0.1], 0.4) == pytest.approx(1.0 / 3.0)
    assert fmr_at([0.4], 0.4) == pytest.approx(0.0)
    assert fmr_at([0.9, 0.4, 0.1], 0.95) == pytest.approx(0.0)
    assert fmr_at([float("-inf"), float("-inf")], 0.0) == pytest.approx(0.0)
    # JANUS 2.3.4 FNIR: miss iff score < tau. Tie at tau is a mate hit.
    assert fnmr_at([0.9, 0.4, 0.1], 0.5) == pytest.approx(2.0 / 3.0)
    assert fnmr_at([0.4], 0.4) == pytest.approx(0.0)
    assert fnmr_at([0.9, 0.8], 0.5) == pytest.approx(0.0)
    assert fnmr_at([float("-inf")], 0.0) == pytest.approx(1.0)


def test_s_max_null_parses_as_neg_inf(report_doc: dict) -> None:
    decisions = parse_decisions(report_doc)
    null_rows = [d for d in decisions if d.s_max == S_MAX_NO_MATCH]
    assert null_rows, "fixture must include s_max:null"
    assert all(d.true_name is None for d in null_rows)
    assert all(d.name_star is None for d in null_rows)


def test_name_star_s_max_coupling_validation(report_doc: dict) -> None:
    bad = deepcopy(report_doc)
    # Find a null s_max row and set a name_star.
    for row in bad["decisions"]:
        if row["s_max"] is None:
            row["name_star"] = "Alice"
            break
    else:
        pytest.fail("fixture missing s_max:null row")
    errs = validate_face_bakeoff_report(bad)
    assert errs
    assert any("name_star" in e and "s_max" in e for e in errs)


def test_missing_publishable_fails_validation(report_doc: dict) -> None:
    bad = deepcopy(report_doc)
    del bad["decisions"][0]["publishable"]
    errs = validate_face_bakeoff_report(bad)
    assert errs
    assert any("publishable" in e for e in errs)


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


def test_stranger_fold_mismatched_to_gallery_counted_once(
    report_doc: dict, manifest_doc: dict
) -> None:
    """Row fold ≠ name_star fold must not drop the stranger (EVAL-08 / V2-02)."""
    decisions = parse_decisions(report_doc)
    identity_folds = identity_fold_assignment(decisions)
    # Alice is fold 0; put stranger row on fold 2 with gallery Alice.
    mismatched = ScoreTrial(
        score=0.27,
        probe_identity=None,
        gallery_identity="Alice",
        fold=2,  # deliberately not Alice's fold
        media_id=9901,
        strata=("unknown",),
        is_genuine=False,
    )
    k = len(report_doc["tau"]["tau_k"])
    pooled = 0
    held_hits: list[int] = []
    for held in range(k):
        fit_ids = fit_identities_for_held_fold(identity_folds, held)
        read_ids = read_identities_for_held_fold(identity_folds, held)
        read = select_read_trials([mismatched], read_ids, fit_ids, held_fold=held)
        hits = [t for t in read if t.media_id == 9901]
        if hits:
            held_hits.append(held)
            pooled += len(hits)
    assert pooled == 1, f"expected exactly once, got {pooled} at holds {held_hits}"
    assert held_hits == [0], "must count under gallery (Alice) fold 0, not row fold 2"


def test_determinism_subprocess_bit_identical(tmp_path: Path) -> None:
    """Bit-identical across real CLI process boundaries with distinct hash seeds.

    Explicit PYTHONHASHSEED per run: if ambient CI pins the seed, inheriting env
    would make a hash-order probe vacuous. Different seeds that still match prove
    the artifact does not depend on dict/set iteration order.
    """
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
    cwd = str(Path(__file__).resolve().parents[3])
    env1 = {**os.environ, "PYTHONHASHSEED": "0"}
    env2 = {**os.environ, "PYTHONHASHSEED": "1"}
    r1 = subprocess.run(
        [*base, "--out", str(out1)],
        check=False,
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env1,
    )
    r2 = subprocess.run(
        [*base, "--out", str(out2)],
        check=False,
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env2,
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
        # FIR6RC-06: fit-side assertion must pass on the filtered set.
        assert_fit_side_impostor_disjointness(fit_trials, fit_ids)

        read_trials = select_read_trials(trials, read_ids, fit_ids, held_fold=held)
        assert_pair_level_disjointness(read_trials, fit_ids)
        for t in read_trials:
            if t.probe_identity is not None:
                assert t.probe_identity not in fit_ids
                assert t.probe_identity in read_ids
            if t.gallery_identity is not None:
                assert t.gallery_identity not in fit_ids


def test_fit_side_impostor_disjointness_rejects_cross_fit_gallery(
    report_doc: dict, manifest_doc: dict
) -> None:
    """FIR6RC-06: select_fit_trials drops cross-fit impostors; assert would fire if leaked."""
    decisions = parse_decisions(report_doc)
    identity_folds = identity_fold_assignment(decisions)
    # Alice fold 0, Carol fold 1 — cross-fit impostor must not enter fit for held=0.
    cross = ScoreTrial(
        score=0.91,
        probe_identity="Alice",
        gallery_identity="Carol",
        fold=0,
        media_id=9911,
        strata=("people",),
        is_genuine=False,
    )
    stranger = ScoreTrial(
        score=0.2,
        probe_identity=None,
        gallery_identity="Alice",
        fold=0,
        media_id=9912,
        strata=("unknown",),
        is_genuine=False,
    )
    fit_ids = fit_identities_for_held_fold(identity_folds, held_fold=0)
    # When held=0, Alice is in READ not FIT; use held=2 so Alice+Bob in fit if k=3.
    # Use held fold that leaves Alice in fit.
    held_with_alice_in_fit = None
    for held in range(len(report_doc["tau"]["tau_k"])):
        ids = fit_identities_for_held_fold(identity_folds, held)
        if "Alice" in ids and "Carol" not in ids:
            held_with_alice_in_fit = held
            fit_ids = ids
            break
    assert held_with_alice_in_fit is not None, "fixture must place Alice in some fit fold without Carol"

    filtered = select_fit_trials([cross, stranger], fit_ids)
    assert all(t.media_id != 9911 for t in filtered), "cross-fit impostor must be dropped"
    assert all(t.media_id != 9912 for t in filtered), "stranger must never inform fit"
    assert_fit_side_impostor_disjointness(filtered, fit_ids)

    # Positive control: leaking the cross-fit pair into fit_trials must raise.
    with pytest.raises(CalibrationError, match="fit-pair gallery"):
        assert_fit_side_impostor_disjointness([cross], fit_ids)
    with pytest.raises(CalibrationError, match="stranger"):
        assert_fit_side_impostor_disjointness([stranger], fit_ids)


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
