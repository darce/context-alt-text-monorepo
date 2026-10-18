"""Software-only report qualification tests; no human conduct or real proof claimed.

Complete evidence tests use the actual frozen S7 implementation when supplied.
Neither a copied decision nor a fake verifier stands in for that implementation.
"""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from scripts.eval_harness import fir_occ_labels as s7
from scripts.eval_harness import firbench_contract as fc
from scripts.eval_harness import firbench_report as report

FIXTURES = Path(__file__).parent / "fixtures/firbench_interchange_v1"


def load(name):
    return json.loads((FIXTURES / f"{name}-v1.json").read_bytes())


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def inventory(tmp_path):
    """Valid software wire, including scored native, fit, challenge and unresolved."""
    run = tmp_path / "repo/benchmarks/private/firbench/runs/qualification"
    frame, scores = load("frame"), load("scores")
    original_face, original_image = frame["faces"][0], frame["images"][0]
    frame.update(images=[], faces=[], psu_map=[], folds=[], identity_folds=[])
    frame["fold_roles"] = [{"fold": 0, "role": "test"}, {"fold": 1, "role": "fit"}]
    for index, status in enumerate(("named", "unresolved", "named", "unknown")):
        image_id, face_id = f"image-{index}", f"face-{index}"
        fold = 1 if index == 2 else 0
        image = dict(original_image, image_id=image_id, session_id=None)
        if index == 3:
            image.update(sampling_arm="challenge", inclusion_probability=None)
        face = copy.deepcopy(original_face)
        face.update(face_id=face_id, image_id=image_id, identity_status=status,
                    identity_id=f"id-{index}" if status == "named" else None)
        frame["images"].append(image)
        frame["faces"].append(face)
        frame["psu_map"].append({"image_id": image_id, "psu_id": f"psu-{index}"})
        frame["folds"].append({"psu_id": f"psu-{index}", "fold": fold})
        if status == "named":
            frame["identity_folds"].append({"identity_id": face["identity_id"], "fold": fold})
    frame["sampling_arm_counts"] = {"probability": 3, "challenge": 1}
    keys = [leg["leg_key"] for leg in scores["legs"]]
    manifest = {"firbench": {
        "created_at": "2026-10-15T08:00:00Z", "created_at_source": "explicit",
        "leg_keys": keys, "arms": ["native"],
        "gallery_membership": [
            {"leg_key": leg, "fold": fold, "gallery_sha256": "b" * 64,
             "enrolled_identity_ids": ["id-0", "id-2"], "identity_folds": {"id-0": 0, "id-2": 1}}
            for leg in keys for fold in (0, 1)
        ],
    }}
    scores["face_outcomes"] = []
    for leg in keys:
        searches = []
        for index, face in enumerate(frame["faces"]):
            row = load("face-search-record")
            fold = 1 if index == 2 else 0
            row.update(
                face_id=face["face_id"], image_id=face["image_id"], psu_id=f"psu-{index}",
                identity_status=face["identity_status"], identity_id=face["identity_id"],
                unit_id=face["face_id"] if index == 3 else None,
                leg_key=leg, arm="native", arm_availability="available", stage_reached="embedded",
                fold=fold, fold_role="fit" if fold else "test",
                sampling_arm=frame["images"][index]["sampling_arm"],
                gallery_sha256="b" * 64, cell=["unknown", "unknown"], top_k=[["id-0", 0.8]],
            )
            searches.append(row)
            outcome = {key: row[key] for key in (
                "face_id", "image_id", "psu_id", "fold", "fold_role", "sampling_arm",
                "leg_key", "arm", "arm_availability", "stage_reached", "identity_status", "cell",
            )}
            reason = "unresolved_identity" if index == 1 else ("fit_fold_not_scored" if index == 2 else None)
            outcome.update(mated=None if index == 1 else index != 3,
                           outcome=None if reason else ("false_accept" if index == 3 else "rejected"),
                           outcome_available=reason is None, outcome_reason=reason)
            scores["face_outcomes"].append(outcome)
        path = run / "legs" / leg / "searches.jsonl"
        path.parent.mkdir(parents=True)
        path.write_text("".join(json.dumps(row) + "\n" for row in searches))
    write(run / "frame.json", frame)
    write(run / "scores.json", scores)
    write(run / "manifest.json", manifest)
    return run, frame, scores, manifest


def render(run):
    report.render_report(run, out_dir=run / "report")
    return json.loads((run / "report/report.json").read_bytes())


def test_unresolved_inventory_does_not_hide_scored_native_cohort(inventory):
    run, frame, scores, manifest = inventory
    originals = {name: (run / name).read_bytes() for name in ("frame.json", "scores.json", "manifest.json")}
    result = render(run)
    rows, pool = result["failures"]["rows"], result["failures"]["pool"]
    assert pool["overall_gt_faces"] == pool["inventory_faces"] == 4
    assert pool["inventory_rows"] == 4 * len(scores["legs"])
    assert pool["fixed_background_source_units"] == 4
    assert pool["primary_background_source_units"] == 2
    assert pool["eligible_faces"] == 1
    for row in rows:
        assert row["default_visible"] is (row["face_id"] == "face-0")
        if row["face_id"] == "face-1":
            assert row["mated"] is row["outcome"] is None
            assert not row["qualified"] and not row["outcome_available"]
        elif row["face_id"] == "face-2":
            assert row["outcome"] is None and row["outcome_reason"] == "fit_fold_not_scored"
    content = (run / "report/index.html").read_text()
    assert "Analytic display withheld" not in content
    assert "Analytic curves withheld" not in content
    assert all((run / name).read_bytes() == raw for name, raw in originals.items())
    assert result["verdict"] == scores["verdict"]
    assert result["failures"]["pool"]["scope_counts"]["unresolved"] == 1


def test_legacy_missing_searches_retain_full_gt_with_null_outcomes(inventory):
    run, frame, scores, manifest = inventory
    del scores["face_outcomes"]
    write(run / "scores.json", scores)
    for path in (run / "legs").glob("*/searches.jsonl"):
        path.write_bytes(path.read_bytes().splitlines()[0] + b"\n")
    result = render(run)
    rows = result["failures"]["rows"]
    assert len(rows) == len(frame["faces"]) * len(scores["legs"])
    assert result["failures"]["pool"]["classification_status"] == "unavailable"
    assert all(row["outcome"] is None and not row["default_visible"] for row in rows)
    assert all(row["stage"] is None for row in rows if row["face_id"] != "face-0")
    assert all(row["mated"] is None for row in rows if row["identity_status"] == "unresolved")
    assert all(row["outcome_reason"] == "legacy_face_outcomes_unavailable" for row in rows)


def test_legacy_no_scope_or_search_keeps_arm_unknown(inventory):
    run, frame, scores, manifest = inventory
    del scores["face_outcomes"]
    manifest["firbench"].pop("arms")
    write(run / "scores.json", scores)
    write(run / "manifest.json", manifest)
    shutil.rmtree(run / "legs")
    result = render(run)
    rows = result["failures"]["rows"]
    assert len(rows) == len(frame["faces"]) * len(scores["legs"])
    assert all(row["arm"] is row["stage"] is row["outcome"] is None for row in rows)


def test_missing_nonmated_labels_do_not_hide_scored_mated_cells(inventory):
    run, frame, scores, manifest = inventory
    # A source-provided scored cell is displayed verbatim; no rate is computed.
    cell = scores["cells"][0]
    cell.update(n_units=40, n_psu=40, n_identities=40, n_eff=40.0, scored=True, fnir=0.123,
                query_occluder="unknown", interval=None)
    frame["faces"][3]["annotation"].update(annotation_tier="a", observation_ref="reference-only")
    write(run / "frame.json", frame)
    write(run / "scores.json", scores)
    render(run)
    assert "FNIR 0.123" in (run / "report/index.html").read_text()
    assert "FNIR 0.123" in (run / "report/cells.csv").read_text()


def test_unresolved_cannot_carry_a_fabricated_nonmated_outcome(inventory):
    run, frame, scores, manifest = inventory
    outcome = next(row for row in scores["face_outcomes"] if row["face_id"] == "face-1")
    outcome.update(mated=False, outcome="false_accept", outcome_available=True, outcome_reason=None)
    write(run / "scores.json", scores)
    with pytest.raises(fc.FrameContractError):
        render(run)
    assert not (run / "report").exists()


@pytest.mark.parametrize("index", [0, 2, 3])
def test_reference_strings_and_metadata_cannot_qualify_tier_a(inventory, index):
    run, frame, scores, manifest = inventory
    frame["faces"][index]["annotation"].update(
        annotation_tier="a", qc_ref="qc:real-looking", observation_ref="observed.json",
    )
    manifest["firbench"]["observation_evidence"] = {"observed": True, "analysis_eligible": True}
    write(run / "frame.json", frame)
    write(run / "manifest.json", manifest)
    result = render(run)
    affected = [row for row in result["failures"]["rows"] if row["face_id"] == f"face-{index}"]
    assert all(not row["qualified"] and row["outcome"] is None for row in affected)
    assert all("S7" in row["qualification_reason"] for row in affected)
    assert ("Analytic display withheld" in (run / "report/index.html").read_text()) is (index == 0)


@pytest.mark.parametrize("mutation", ["frame", "missing", "hash", "escape", "symlink", "duplicate", "malformed"])
def test_invalid_evidence_is_refused_before_report_writes(inventory, mutation):
    run, frame, scores, manifest = inventory
    name = "label-evidence/benchmarks/private/labels/export.json"
    path = run / name
    sha = write(path, {"schema": "deliberately-incomplete-software-proof"})
    descriptor = {"schema": "firbench-label-evidence/v1",
                  "frame_sha256": hashlib.sha256((run / "frame.json").read_bytes()).hexdigest(),
                  "export_path": name, "queue_path": name, "gold_path": name,
                  "files": [{"path": name, "sha256": sha}]}
    if mutation == "frame":
        descriptor["frame_sha256"] = "0" * 64
    elif mutation == "missing":
        path.unlink()
    elif mutation == "hash":
        path.write_text("{}")
    elif mutation == "escape":
        descriptor["files"][0]["path"] = "label-evidence/../../foreign.json"
    elif mutation == "symlink":
        original = path.with_name("original.json")
        path.rename(original)
        path.symlink_to(original.name)
    elif mutation == "duplicate":
        descriptor["files"].append(dict(descriptor["files"][0]))
    else:
        path.write_text('{"x": 1, "x": 2}')
        descriptor["files"][0]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest["firbench"]["label_evidence"] = descriptor
    write(run / "manifest.json", manifest)
    with pytest.raises(fc.FrameContractError):
        render(run)
    assert not (run / "report").exists()


@pytest.fixture
def software_evidence(inventory):
    """Model a complete production wire, solely to exercise software bindings.

    The observation's required record_kind and applicability fields are test
    inputs, never attestations of an actual inspection or independent conduct.
    No images, models or alias maps are read or persisted.
    """
    from scene.tests import test_eval_harness_fir_occ_labels as labels
    from scene.tests.test_eval_harness_fir_occ_labels_evidence import QC

    run, frame, scores, manifest = inventory
    repo = run.parents[4]
    source = repo / "benchmarks/private/software-label-wire"
    queue, gold = labels._queue_doc(), labels._gold_doc()
    for document in (queue, gold):
        document.pop("data_origin", None)
        for item in document["items"]:
            item.pop("data_origin", None)
            item.pop("fixture_recipe", None)
    queue["qc"] = dict(QC)
    context = {
        "rule": labels.RULE, "instructions": "software-only instructions",
        "operators": ["ann-01"], "collection_workflow": "software-only collection",
        "adjudication_workflow": "software-only review", "tool_behavior": "software-only UI",
    }
    queue["measurement_context"] = context
    target = next(item for index, item in enumerate(queue["items"])
                  if labels._answer_faces(index)[0]["identity_status"] == "unknown")
    target["image_id"] = "image-0"
    qpath, gpath, epath = (source / name for name in ("queue.json", "gold.json", "export.json"))
    queue_sha = write(qpath, queue)
    write(gpath, gold)
    export = labels._export_doc(queue, queue_sha, gold, observation_ref="observation.json")
    export_sha = write(epath, export)
    observation = {
        "schema": "fir-occ-observation/v1", "record_kind": "bounded_human_observation",
        "observer_id": "software-test-actor", "observed_at": "2026-10-15T08:00:00Z",
        "scope": "Software wire only; no human observation claimed",
        "method": "Structural fixture validation only", "operator_accounts": "software-only accounts",
        "limits": "No real analysis proof or human conduct established", "exceptions": [],
        "context": context,
        "applicability": {
            "candidate_sha256": export_sha, "queue_sha256": queue_sha, "run_id": queue["queue_id"],
            "applicable": True, "beyond_scope": False, "uncertain": False,
            "limits": "Software-only modeled applicability; not real evidence",
            "context_assessment": {
                key: {"observed": value, "current": value, "covered": True,
                      "rationale": "Identical modeled software context only"}
                for key, value in context.items()
            },
        },
    }
    write(source / "observation.json", observation)
    rows = s7.to_face_instances(s7.load_label_export(epath), s7.load_queue(qpath, gpath))
    s7.require_real_analysis_rows(rows)
    row = next(row for row in rows if row["image_id"] == "image-0" and row["box"] is not None)
    face = frame["faces"][0]
    face.update(box=row["box"], identity_status=row["identity_status"], identity_id=None,
                annotation=copy.deepcopy(row["annotation"]))
    frame["images"][0]["sha256"] = row["image_sha256"]
    frame["identity_folds"] = [r for r in frame["identity_folds"] if r["identity_id"] != "id-0"]
    query_cell = "+".join(sorted(set(row["annotation"]["occluders"]))) or "clear"
    for leg in scores["legs"]:
        path = run / "legs" / leg["leg_key"] / "searches.jsonl"
        searches = [json.loads(line) for line in path.read_bytes().splitlines()]
        searches[0].update(identity_status="unknown", identity_id=None, unit_id=face["face_id"],
                           cell=[query_cell, "unknown"])
        path.write_text("".join(json.dumps(item) + "\n" for item in searches))
    for outcome in scores["face_outcomes"]:
        if outcome["face_id"] == face["face_id"]:
            outcome.update(identity_status="unknown", mated=False, outcome="false_accept",
                           cell=[query_cell, "unknown"])
    write(run / "frame.json", frame)
    write(run / "scores.json", scores)
    return run, frame, scores, manifest, repo, source, (epath, qpath, gpath), rows


def test_software_wire_uses_actual_s7_readers_without_claiming_human_proof(software_evidence):
    *_, rows = software_evidence
    assert rows and all(row["annotation"]["annotation_tier"] == "a" for row in rows)
    assert any(row["identity_status"] == "unknown" for row in rows)
    # This establishes software shape only, not the truth of modeled attestations.
    assert all(row["observation_evidence"] for row in rows)


def freeze(software_evidence):
    if not all(hasattr(s7, name) for name in ("freeze_label_evidence", "requalify_label_evidence")):
        pytest.skip("actual committed S7 frozen helper absent; offline report join remains pending")
    run, frame, scores, manifest, repo, source, paths, rows = software_evidence
    frame_sha = hashlib.sha256((run / "frame.json").read_bytes()).hexdigest()
    bundle = s7.freeze_label_evidence(*paths, repo_root=repo, frame_sha256=frame_sha)
    for name, raw in bundle.files.items():
        path = run / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as handle:
            handle.write(raw)
    manifest["firbench"]["label_evidence"] = dict(bundle.descriptor)
    write(run / "manifest.json", manifest)
    return bundle


def test_actual_frozen_software_wire_requalifies_offline_and_displays(inventory, software_evidence, monkeypatch):
    run, frame, scores, manifest, repo, source, paths, rows = software_evidence
    scores["cells"][0].update(n_units=40, n_psu=40, n_identities=40, n_eff=40.0, scored=True, fnir=0.123,
                              interval=None)
    write(run / "scores.json", scores)
    original_bytes = {str(path.relative_to(repo)): path.read_bytes() for path in source.iterdir()}
    bundle = freeze(software_evidence)
    assert {name.removeprefix("label-evidence/"): raw for name, raw in bundle.files.items()} == original_bytes
    shutil.rmtree(source)
    captured = {}
    page = report._page

    def capture(title, sections, verdict, *, view_data=None):
        captured.update(view_data)
        return page(title, sections, verdict, view_data=view_data)

    monkeypatch.setattr(report, "_page", capture)
    before = {name: (run / name).read_bytes() for name in ("frame.json", "scores.json", "manifest.json")}
    result = render(run)
    selected = [row for row in result["failures"]["rows"] if row["face_id"] == "face-0"]
    assert selected and all(row["qualified"] and row["default_visible"] for row in selected)
    assert all(row["outcome"] == "false_accept" and row["mated"] is False for row in selected)
    for name, raw in bundle.files.items():
        assert captured["files"][name] == json.loads(raw)
        assert result["inputs"][name] == captured["inputs"][name] == hashlib.sha256(raw).hexdigest()
    assert result["label_evidence"] == bundle.descriptor
    assert result["dependencies_pending"] == []
    assert "FNIR 0.123" in (run / "report/cells.csv").read_text()
    assert all((run / name).read_bytes() == raw for name, raw in before.items())
    frozen = {name: (run / "report" / name).read_bytes() for name in ("index.html", "report.json", "cells.csv")}
    assert render(run) == result
    assert all((run / "report" / name).read_bytes() == raw for name, raw in frozen.items())


@pytest.mark.parametrize("mutation", [
    "image_hash", "geometry", "status", "annotation", "alias", "duplicate", "synthetic_frame",
])
def test_actual_s7_join_requires_one_to_one_frame_annotations(software_evidence, mutation):
    run, frame, scores, manifest, repo, source, paths, rows = software_evidence
    face = frame["faces"][0]
    if mutation == "image_hash":
        frame["images"][0]["sha256"] = "f" * 64
    elif mutation == "geometry":
        face["box"] = [0.0, 0.0, 1.0, 1.0]
    elif mutation == "status":
        face.update(identity_status="named", identity_id="id-0")
        frame["identity_folds"].append({"identity_id": "id-0", "fold": 0})
    elif mutation == "annotation":
        face["annotation"]["observation_ref"] = "reference-that-was-not-qualified.json"
    elif mutation == "alias":
        # Equal image bytes under another canonical ID never create a join.
        frame["images"][0]["image_id"] = face["image_id"] = "media-alias"
    elif mutation == "duplicate":
        frame["faces"].append(dict(face, face_id="duplicate-face"))
    else:
        frame["images"][0]["synthetic_parent_id"] = "software-generated-parent"
    write(run / "frame.json", frame)
    bundle = freeze(software_evidence)
    qualification = report._binding_label_evidence(
        run, frame, bundle.descriptor,
        frame_sha256=hashlib.sha256((run / "frame.json").read_bytes()).hexdigest(), files={}, inputs={},
    )
    qualified, reason = report._binding_qualification(face, frame, qualification=qualification)
    assert not qualified and "S7" in reason
