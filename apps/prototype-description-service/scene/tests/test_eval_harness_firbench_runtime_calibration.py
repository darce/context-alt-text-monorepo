"""MCP16868: used identity provenance, fold galleries and actual private-run binding.

Synthetic media/model kernels come from the public CLI integration fixture; all
S0/S1/S2/S3 producers, calibration, schemas and 10,000-draw inference stay real.
"""

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from scene.tests.test_eval_harness_firbench_cli_integration import run, runtime_files  # noqa: F401
from scripts.eval_harness import firbench_cli as cli
from scripts.eval_harness import firbench_contract as fc
from scripts.eval_harness import firbench_score as core
from scripts.eval_harness import firbench_score_io as io
from scripts.eval_harness.firbench_frames import NonMatedUnit
from scripts.eval_harness.firbench_legs import FaceSearchRecord

ROOT = Path(__file__).resolve().parents[4]
FIT = frozenset({1, 2, 3, 4})
FULL_MAP = {"held-out-unused": 0, **{f"fit-{fold}": fold for fold in FIT}}


def fit_evidence():
    rows, units = [], []
    for fold, score in zip(sorted(FIT), (0.9, 0.7, 0.4, 0.2), strict=True):
        unit = NonMatedUnit(f"background:image-{fold}", fold, f"psu-{fold}", None)
        units.append(unit)
        rows.append(
            FaceSearchRecord(
                face_id=f"alarm-{fold}",
                image_id=f"image-{fold}",
                psu_id=unit.psu_id,
                identity_id=None,
                identity_status=fc.IdentityStatus.unknown,
                fold=fold,
                fold_role=fc.FoldRole.fit,
                cell=("unknown", "unknown"),
                unit_id=unit.unit_id,
                sampling_arm=fc.SamplingArm.probability,
                inclusion_probability=1.0,
                cohort=None,
                leg_key="sface__native__fake-space__cv4__ort1",
                arm=fc.Arm.native,
                arm_availability=fc.ArmStatus.available,
                alignment_mode=fc.AlignmentMode.separable,
                stage_reached=fc.SearchStage.embedded,
                top_k=((f"fit-{fold}", score),),
                gallery_sha256=str(fold) * 64,
                timing_receipt_ref="fake-receipt",
            )
        )
    return rows, units


def calibrate(rows, units, *, mapping=None, boundary=fc.BoundarySemantics.v2):
    return core.calibrate_tau(
        rows,
        units=units,
        calibration_folds=FIT,
        fpir_target=0.25,
        boundary=boundary,
        identity_folds=FULL_MAP if mapping is None else mapping,
    )


@pytest.mark.parametrize("boundary", list(fc.BoundarySemantics))
def test_full_registry_with_unused_test_identity_and_distinct_fit_galleries(boundary):
    rows, units = fit_evidence()
    original = dict(FULL_MAP)
    tau = calibrate(rows, units, boundary=boundary)
    assert tau == pytest.approx(0.8 if boundary is fc.BoundarySemantics.v2 else 0.7)
    point = core.curve(rows, units=units, thresholds=[tau], boundary=boundary)[0]
    assert (point.fpi, point.n_units, point.fpir) == (1, 4, 0.25)
    assert original == FULL_MAP


@pytest.mark.parametrize(
    "change",
    [
        {"top_k": (("held-out-unused", 0.99),)},
        {"top_k": (("unknown-identity", 0.99),)},
        {"fold": 0},
        {"identity_id": "held-out-unused", "identity_status": fc.IdentityStatus.named, "unit_id": None},
        {"identity_id": "fit-2", "identity_status": fc.IdentityStatus.named, "unit_id": None},
    ],
)
def test_used_test_unknown_or_contradictory_identity_provenance_refuses(change):
    rows, units = fit_evidence()
    rows[0] = replace(rows[0], **change)
    with pytest.raises(fc.CalibrationLeakError):
        calibrate(rows, units)


def test_missing_used_identity_provenance_refuses():
    rows, units = fit_evidence()
    with pytest.raises(fc.CalibrationLeakError):
        calibrate(rows, units, mapping={k: v for k, v in FULL_MAP.items() if k != "fit-1"})


def test_mated_face_cannot_be_a_fixed_nonmated_unit():
    rows, units = fit_evidence()
    rows[0] = replace(
        rows[0], face_id=units[0].unit_id, unit_id=None, identity_id="fit-1", identity_status=fc.IdentityStatus.named
    )
    with pytest.raises(fc.FrameContractError, match="mated face"):
        calibrate(rows, units)


@pytest.mark.parametrize(
    "change",
    [
        {"gallery_sha256": "f" * 64},
        {"leg_key": "auraface__native__fake-space__cv4__ort1"},
        {"leg_key": "sface__native__other-space__cv4__ort1"},
        {"arm": fc.Arm.gt_crop_redetect},
        {"sampling_arm": fc.SamplingArm.challenge, "inclusion_probability": None},
    ],
)
@pytest.mark.parametrize("operation", ["calibration", "curve"])
def test_mixed_scope_within_query_fold_refuses(change, operation):
    rows, units = fit_evidence()
    rows.append(replace(rows[0], face_id="extra-alarm", **change))
    with pytest.raises(fc.FrameContractError):
        if operation == "calibration":
            calibrate(rows, units)
        else:
            core.curve(rows, units=units, thresholds=[0.5], boundary=fc.BoundarySemantics.v2)


@pytest.mark.parametrize(
    "change",
    [
        {"leg_key": "sface__native__other-space__cv4__ort1"},
        {"sampling_arm": fc.SamplingArm.challenge, "inclusion_probability": None},
        {"unit_id": "outside-pool"},
        {"fold": 2},
        {"identity_id": "fit-1", "identity_status": fc.IdentityStatus.named},
    ],
)
def test_cross_fold_leg_sampling_and_fixed_unit_provenance_refuse(change):
    rows, units = fit_evidence()
    rows[0] = replace(rows[0], **change)
    with pytest.raises(fc.FrameContractError):
        calibrate(rows, units)


def test_io_calibration_reports_actual_pooled_fixed_units():
    rows, units = fit_evidence()
    decision = fc.load_decision_manifest(ROOT / "benchmarks/manifests/fir-bench-decision-v1.json")
    decision = replace(decision, primary=replace(decision.primary, fpir_target=0.25))
    tau, result = io._calibrate(rows, units, FULL_MAP, FIT, decision)
    assert tau == pytest.approx(0.8)
    assert result["data"]["pooled_units"] == 4
    assert result["data"]["fpi_at_tau"] == {"count": 1, "rate": 0.25}


def test_actual_default_cli_scores_private_run_in_external_repository(runtime_files):
    files = runtime_files
    assert files.repo != ROOT
    directory = run(files)
    receipt = (directory / "timings.json").read_bytes()
    first = cli.score_run(directory, repo_root=files.repo).read_bytes()
    assert cli.score_run(directory, repo_root=files.repo).read_bytes() == first
    assert (directory / "timings.json").read_bytes() == receipt
    score = json.loads(first)
    fc.validate_interchange("scores-v1", score)
    assert score["verdict"]["state"] == "unratified"
    assert all(row["tau"]["status"] == "available" for row in score["legs"])
    # Persisted producer evidence still enforces PSU and fit/test role binding.
    search = next(
        path for path in sorted((directory / "legs").glob("*/searches.jsonl")) if "__native__" in path.parent.name
    )
    original = search.read_bytes()
    for change in ({"psu_id": "other-psu"}, {"fold_role": "test"}, {"fold_role": "fit"}):
        rows = [json.loads(line) for line in original.splitlines()]
        index = next(i for i, row in enumerate(rows) if any(row[k] != v for k, v in change.items()))
        rows[index].update(change)
        search.write_text("".join(json.dumps(row) + "\n" for row in rows))
        with pytest.raises(fc.FrameContractError, match="PSU/fold binding"):
            io.score_run(directory, decision=fc.load_decision_manifest(files.decision))
        search.write_bytes(original)
    assert (directory / "timings.json").read_bytes() == receipt


@pytest.mark.parametrize("failure", [None, "traversal", "symlink", "hash", "object", "canonical-bypass"])
def test_private_binding_checks_actual_root_bytes_and_object(tmp_path, failure):
    repo = tmp_path / "external-repository"
    directory = repo / "benchmarks/private/firbench/run"
    directory.mkdir(parents=True)
    source = ROOT / "benchmarks/manifests/fir-bench-decision-v1.json"
    decision = fc.load_decision_manifest(source)
    gate = repo / decision.gate_contract_path
    gate.parent.mkdir(parents=True, exist_ok=True)
    gate.write_bytes((source.parent / decision.gate_contract_path).read_bytes())
    target = repo / "decision.json"
    target.write_bytes(source.read_bytes() + b"\n")
    manifest = {
        "decision_path": "decision.json",
        "decision_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "repo_root": str(ROOT),
    }  # An arbitrary manifest root is never authority.
    if failure in {"traversal", "symlink"}:
        outside = tmp_path / "outside.json"
        outside.write_bytes(target.read_bytes())
        if failure == "traversal":
            manifest["decision_path"] = "../outside.json"
        else:
            target.unlink()
            target.symlink_to(outside)
    elif failure == "hash":
        manifest["decision_sha256"] = "f" * 64
    elif failure == "object":
        decision = replace(decision, primary=replace(decision.primary, fpir_target=0.25))
    elif failure == "canonical-bypass":
        manifest["decision_sha256"] = fc.manifest_sha256(decision)
        target.unlink()
    if failure is None:
        io._decision_binding(manifest, decision, directory)
    else:
        with pytest.raises((fc.FrameContractError, OSError)):
            io._decision_binding(manifest, decision, directory)
