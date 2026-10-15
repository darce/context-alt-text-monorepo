"""Files-only binding regressions; fake metadata, actual versioned contracts."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path

import pytest

from scripts.eval_harness import firbench_contract as fc
from scripts.eval_harness import firbench_report as report

FIXTURES = Path(__file__).parent / "fixtures/firbench_interchange_v1"


def load(name):
    payload = json.loads((FIXTURES / name).read_bytes())
    if name == "scores-v1.json":
        # This common fixture deliberately exercises legacy classification absence.
        # The actual producer integration below supplies the complete new wire.
        payload.pop("face_outcomes", None)
    return payload


@pytest.fixture
def run(tmp_path):
    path = tmp_path / "repo/benchmarks/private/firbench/runs/binding"
    path.mkdir(parents=True)
    for name in ("scores", "frame"):
        (path / f"{name}.json").write_text(json.dumps(load(f"{name}-v1.json")))
    return path


@pytest.fixture
def comparison_run(tmp_path, monkeypatch, request):
    """Actual CLI runs, scores and S6b comparison; only offline assets/kernels fake.

    All input files live in this test's temporary repository. Source deletion
    before report proves the files-only boundary, with original receipts pinned.
    """
    from scene.tests import test_eval_harness_firbench_cli_integration as native
    from scripts.eval_harness import firbench_cli as cli

    monkeypatch.setattr(native, "ARMS", (fc.Arm.native,))
    yield_from = native.runtime_files.__wrapped__(tmp_path, monkeypatch, request)
    files = next(yield_from)
    try:
        monkeypatch.setattr(cli, "_repo_root", lambda: files.repo)
        paths = []
        for name in ("run-a", "run-b"):
            directory = native.run(files)
            assert cli.main(["score", str(directory)]) == 0
            destination = files.private / name
            directory.rename(destination)
            paths.append(destination)
        for path in files.private.glob("*.png"):
            path.unlink()
        files.source.unlink()
        files.templates.unlink()
        files.binding_path.unlink()
        before = {p: p.read_bytes() for directory in paths for p in directory.rglob("*") if p.is_file()}
        comparison = cli.compare_runs(*paths, out_dir=paths[0], treatment=None, repo_root=files.repo)
        assert {p: p.read_bytes() for p in before} == before
        assert comparison == paths[0] / "comparison.json"
        yield paths[0]
    finally:
        yield_from.close()


def search(frame, scores):
    row = load("face-search-record-v1.json")
    face = frame["faces"][0]
    row.update(
        face_id=face["face_id"],
        image_id=face["image_id"],
        identity_id=face["identity_id"],
        identity_status=face["identity_status"],
        psu_id=frame["psu_map"][0]["psu_id"],
        fold=frame["folds"][0]["fold"],
        fold_role=frame["fold_roles"][0]["role"],
        sampling_arm=frame["images"][0]["sampling_arm"],
        leg_key=scores["legs"][0]["leg_key"],
        arm="native",
        arm_availability="available",
        stage_reached="embedded",
        unit_id=None,
    )
    return row


def put_search(run, row):
    path = run / "legs" / row["leg_key"] / "searches.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(row) + "\n")


def render(run, **kwargs):
    report.render_report(run, out_dir=run / "report", **kwargs)
    return json.loads((run / "report/report.json").read_bytes())


def assert_legacy_declared_inventory(rows, frame, scores, recorded):
    """One actual GT face per declared leg, including the unsearched leg."""
    legs = {leg["leg_key"] for leg in scores["legs"]}
    gt_ids = {face["face_id"] for face in frame["faces"]}
    assert len(legs) == 2 and len(gt_ids) == 1
    assert len(rows) == len(legs) * len(gt_ids)
    assert {row["leg_key"] for row in rows} == legs
    for leg in legs:
        assert {row["face_id"] for row in rows if row["leg_key"] == leg} == gt_ids
    assert {row["image_id"] for row in rows} == {face["image_id"] for face in frame["faces"]}
    for row in rows:
        assert row["outcome"] is None and row["outcome_available"] is False
        assert row["outcome_reason"] == "legacy_face_outcomes_unavailable"
        assert row["outcome_ref"] is None and row["is_failure"] is None
        assert row["default_visible"] is False
        if row["leg_key"] == recorded["leg_key"]:
            assert row["arm"] == recorded["arm"]
            assert row["stage"] == recorded["stage_reached"]
            assert row["arm_availability"] == recorded["arm_availability"]
            assert row["ref"] == f"legs/{recorded['leg_key']}/searches.jsonl#/0"
        else:
            assert row["arm"] is row["stage"] is row["arm_availability"] is None
            assert row["top1_identity"] is row["top1_score"] is None
            assert row["ref"] == "frame.json#/faces/0"


def test_legacy_inventory_is_explicitly_unclassified_and_shared_with_page(run, monkeypatch):
    frame, scores = load("frame-v1.json"), load("scores-v1.json")
    recorded = search(frame, scores)
    put_search(run, recorded)
    captured = {}
    page = report._page

    def with_data(title, sections, verdict, *, view_data=None):
        captured.update(view_data or {})
        return page(title, sections, verdict)

    monkeypatch.setattr(report, "_page", with_data)
    result = render(run)
    rows = result["failures"]["rows"]
    assert_legacy_declared_inventory(rows, frame, scores, recorded)
    assert captured["failure_rows"] == rows
    assert captured["failure_pool"] == result["failures"]["pool"]
    assert captured["background"] == result["failures"]["background_units_detector_only"] == 0
    assert captured["files"]["scores.json"] == scores
    assert captured["files"][f"legs/{recorded['leg_key']}/searches.jsonl"] == [recorded]
    assert "_ref" not in captured["files"][f"legs/{recorded['leg_key']}/searches.jsonl"][0]
    for leg in {leg["leg_key"] for leg in scores["legs"]} - {recorded["leg_key"]}:
        assert f"legs/{leg}/searches.jsonl" not in captured["files"]
    assert "classification unavailable" in (run / "report/index.html").read_text()


@pytest.mark.parametrize(
    "field,value",
    [
        ("image_id", "foreign"),
        ("psu_id", "foreign"),
        ("fold", 99),
        ("fold_role", "test"),
        ("identity_status", "unknown"),
        ("identity_id", "foreign"),
        ("sampling_arm", "challenge"),
        ("leg_key", "foreign"),
    ],
)
def test_search_provenance_refuses_before_output(run, field, value):
    row = search(load("frame-v1.json"), load("scores-v1.json"))
    directory_key = row["leg_key"]
    row[field] = value
    path = run / "legs" / directory_key / "searches.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(row) + "\n")
    with pytest.raises(fc.FrameContractError):
        render(run)
    assert not (run / "report").exists()


def test_pool_distinguishes_inventory_selection_and_fixed_background(run):
    frame, scores = load("frame-v1.json"), load("scores-v1.json")
    row = search(frame, scores)
    put_search(run, row)
    result = render(run)
    pool = result["failures"]["pool"]
    assert pool["overall_gt_faces"] == pool["inventory_faces"] == 1
    assert pool["eligible_faces"] == pool["selected_faces"] == 0
    assert pool["fixed_background_source_units"] == 1
    assert pool["classification_status"] == "unavailable"
    assert pool["limit"] is None


@pytest.fixture
def qc_producer_run(tmp_path, monkeypatch, request):
    """Actual QC/runtime/scorer wire; modeled attestations prove no human conduct."""
    from scene.tests import test_eval_harness_firbench_cli_integration as native
    from scene.tests import test_eval_harness_firbench_label_bundle_runtime as evidence
    from scripts.eval_harness import firbench_frames as frames

    monkeypatch.setattr(native, "ARMS", (fc.Arm.native,))
    fixture = native.runtime_files.__wrapped__(tmp_path, monkeypatch, request)
    files = next(fixture)
    try:
        # Choose the QC specimen's scope from the declared folds before outcomes.
        decision = fc.load_decision_manifest(files.decision)
        assert decision.interval.n_boot == 10000
        source = frames.load_population_draft(files.source)
        components = frames.build_psu_components(source.images, source.faces)
        folds = frames.identity_disjoint_folds(
            components, frames.identity_to_component(source.faces, components),
            k=decision.fold_protocol.k, seed=decision.fold_protocol.seed,
        )
        target = next(image for image in sorted(components)
                      if folds[components[image]] == decision.fold_protocol.seed % decision.fold_protocol.k)
        payload = json.loads(files.source.read_bytes())
        for name in ("images", "faces"):
            payload[name].sort(key=lambda row: row["image_id"] != target)
        native.rebind_source(files, payload)
        files, _paths, _observation, originals = evidence.evidence_wire.__wrapped__(files)
        directory = native.run(files)
        native.cli.score_run(directory, repo_root=files.repo)
        # Report replay must requalify the persisted bundle with originals absent.
        for path, raw in originals.items():
            assert path.read_bytes() == raw
            path.unlink()
        for path in (files.source, files.templates, files.binding_path, *files.private.glob("*.png")):
            path.unlink()
        yield directory, target
    finally:
        fixture.close()


def test_actual_qc_replay_separates_known_inventory_from_missing_proof(qc_producer_run):
    """Software-only replay through genuine S7 functions, never an evidence claim."""
    run, target = qc_producer_run
    originals = {p.relative_to(run): p.read_bytes() for p in run.rglob("*") if p.is_file()}
    result = render(run)
    frame = json.loads((run / "frame.json").read_bytes())
    scores = json.loads((run / "scores.json").read_bytes())
    rows, pool = result["failures"]["rows"], result["failures"]["pool"]
    assert pool["status"] == "established" and pool["eligibility_restrictions"] == []
    assert pool["overall_images"] == pool["fixed_background_source_units"] == 30
    assert pool["overall_gt_faces"] == pool["inventory_faces"] == 30
    assert pool["named_faces"] == 29 and pool["unknown_faces"] == 1 and pool["unresolved_identity_faces"] == 0
    assert pool["inventory_rows"] == len(frame["faces"]) * len(scores["legs"])
    assert {r["face_id"] for r in rows} == {f["face_id"] for f in frame["faces"]}
    qualified = [r for r in rows if r["image_id"] == target]
    assert len(qualified) == len(scores["legs"])
    assert all(r["annotation_tier"] == "a" and r["qualified"] and r["mated"] is False for r in qualified)
    assert all(r["fold_role"] == "test" and r["arm"] == "native" for r in qualified)
    # The declared gallery also leaves two named test faces unenrolled. Neither
    # those GT units nor this unknown face may be confused with detector alarms.
    assert pool["nonmated_gt_source_units_by_leg"] == {leg["leg_key"]: 3 for leg in scores["legs"]}
    for leg in scores["legs"]:
        assert {r["face_id"] for r in rows if r["leg_key"] == leg["leg_key"] and r["mated"] is False
                and r["fold_role"] == "test"} == {qualified[0]["face_id"], "face-0018", "face-0021"}
    assert pool["primary_background_source_units"] == 6 and scores["n_units"] == 9
    assert pool["background_detector_rows"] == result["failures"]["background_units_detector_only"] == 3
    assert "Analytic display withheld" not in (run / "report/index.html").read_text()
    assert all((run / name).read_bytes() == raw for name, raw in originals.items())
    frozen = {p.name: p.read_bytes() for p in (run / "report").iterdir()}
    assert render(run) == result
    assert {p.name: p.read_bytes() for p in (run / "report").iterdir()} == frozen

    # Removing proof cannot erase measured GT inventory or authorize analytics.
    manifest = json.loads((run / "manifest.json").read_bytes())
    manifest["firbench"].pop("label_evidence")
    (run / "manifest.json").write_text(json.dumps(manifest))
    withheld = render(run)
    restricted = withheld["failures"]["pool"]
    assert restricted["status"] == "established"
    for key in (
        "overall_images", "overall_gt_faces", "inventory_rows", "inventory_faces", "inventory_images",
        "fixed_background_source_units", "primary_background_source_units", "background_detector_rows",
    ):
        assert restricted[key] == pool[key], key
    assert any("S7" in reason for reason in restricted["eligibility_restrictions"])
    unqualified = [r for r in withheld["failures"]["rows"] if r["image_id"] == target]
    assert len(unqualified) == len(qualified)
    assert all(r["outcome"] is None and not r["qualified"] and not r["outcome_available"] for r in unqualified)
    assert all(not r["default_visible"] and "S7" in r["qualification_reason"] for r in unqualified)
    content = (run / "report/index.html").read_text()
    assert "Analytic display withheld" in content and "Analytic curves withheld" in content
    assert (run / "scores.json").read_bytes() == originals[Path("scores.json")]
    assert (run / "timings.json").read_bytes() == originals[Path("timings.json")]


def test_comparison_uses_expanded_wire_and_preserves_history_and_absent_tau(comparison_run):
    run = comparison_run
    comparison = json.loads((run / "comparison.json").read_bytes())
    fc.validate_interchange("comparison-v1", comparison)
    assert comparison["comparison_state"] == "comparable"
    assert len(comparison["paired_deltas"]) == len(comparison["history"]) == 3
    assert len(comparison["tau_spread"]) == 6
    assert all(
        r["values"] == [] and r["reason"] == "pooled_fit_threshold_no_per_fold_estimates"
        for r in comparison["tau_spread"]
    )
    result = render(run)
    assert result["comparison"] == comparison
    assert result["inputs"]["comparison.json"] == hashlib.sha256((run / "comparison.json").read_bytes()).hexdigest()
    content = (run / "report/index.html").read_text()
    assert comparison["label"] in content
    for row in comparison["tau_spread"]:
        if row["reason"]:
            assert row["reason"] in content
    assert list((run / "report").glob("table-compare-*.csv"))
    for name, sha in result["inputs"].items():
        assert (run / name).is_file() and hashlib.sha256((run / name).read_bytes()).hexdigest() == sha
    frozen = {p.relative_to(run): p.read_bytes() for p in run.rglob("*") if p.is_file()}
    render(run)
    assert {p.relative_to(run): p.read_bytes() for p in run.rglob("*") if p.is_file()} == frozen


def test_malformed_comparison_refuses_without_writes(run):
    (run / "comparison.json").write_text('{"schema_version":1}')
    with pytest.raises(fc.FrameContractError, match="comparison-v1"):
        render(run)
    assert not (run / "report").exists()


def test_real_tier_a_reference_alone_withholds_analytics(run):
    frame, scores = load("frame-v1.json"), load("scores-v1.json")
    frame["faces"][0]["annotation"].update(annotation_tier="a", observation_ref="real-looking", qc_ref="qc")
    (run / "frame.json").write_text(json.dumps(frame))
    put_search(run, search(frame, scores))
    result = render(run)
    assert result["failures"]["rows"][0]["qualified"] is False
    assert "S7" in result["failures"]["rows"][0]["qualification_reason"]
    assert "withheld" in (run / "report/index.html").read_text()


def test_crops_off_never_reads_artifact_or_pixels(run, monkeypatch):
    (run / "crop-artifacts.json").write_text("malformed but crops are disabled")
    original = Path.read_bytes

    def guarded(path):
        assert path.name != "crop-artifacts.json"
        assert path.suffix.lower() not in {".png", ".jpg", ".npy"}
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", guarded)
    result = render(run, include_crops=False)
    assert result["failures"]["pool"]["crop_images_shown"] == 0
    assert "crop-artifacts.json" not in result["inputs"]


def test_every_rendered_table_has_csv_and_pinned_report_replays(run):
    result = render(run)
    before = {p.name: p.read_bytes() for p in (run / "report").iterdir()}
    assert len(result["table_exports"]) == (run / "report/index.html").read_text().count("<table")
    for item in result["table_exports"]:
        rows = list(csv.reader(io.StringIO((run / "report" / item["filename"]).read_text())))
        assert rows and len(rows) - 1 == item["n_rows"]
    render(run)
    assert before == {p.name: p.read_bytes() for p in (run / "report").iterdir()}


def test_default_cli_materializes_files_only_report(tmp_path, monkeypatch, capsys):
    from scene.tests import test_eval_harness_firbench_cluster_io as producer
    from scripts.eval_harness import firbench_cli as cli
    from scripts.eval_harness import firbench_cluster_io

    # Actual S1 frame and S2 packed cache writers. This is a legacy scores run:
    # the materializer owns diagnostics and must not invent classification.
    run = producer._write_run(producer._private_run(tmp_path), leg_keys=(producer.SFACE,))
    scores = json.loads((run / "scores.json").read_bytes())
    scores.pop("face_outcomes", None)
    (run / "scores.json").write_text(json.dumps(scores))
    manifest = json.loads((run / "manifest.json").read_bytes())
    manifest["firbench"].update(created_at="2026-10-15T08:00:00Z", created_at_source="explicit")
    (run / "manifest.json").write_text(json.dumps(manifest))
    monkeypatch.setattr(cli, "_repo_root", lambda: tmp_path)
    inputs = {p.relative_to(run): p.read_bytes() for p in run.rglob("*") if p.is_file()}
    assert callable(firbench_cluster_io.materialize_clusters)
    assert cli.main(["report", str(run)]) == 0
    clusters = json.loads((run / "clusters.json").read_bytes())
    fc.validate_interchange("clusters-v1", clusters)
    assert clusters["legs"][0]["vector_coverage"]["n_gt_faces"] == 4
    assert (run / "report/index.html").is_file()
    assert "index.html" in capsys.readouterr().out
    assert (
        json.loads((run / "report/report.json").read_bytes())["failures"]["pool"]["classification_status"]
        == "unavailable"
    )
    assert {p: (run / p).read_bytes() for p in inputs} == inputs
    frozen = {p.relative_to(run): p.read_bytes() for p in run.rglob("*") if p.is_file()}
    assert cli.main(["report", str(run)]) == 0
    assert {p.relative_to(run): p.read_bytes() for p in run.rglob("*") if p.is_file()} == frozen


def test_exploratory_comparison_never_selects_a_winner(run):
    comparison = load("comparison-v1.json")
    comparison.update(
        comparison_state="exploratory",
        label="exploratory: multi-factor, no verdict",
        differences=["arm", "gallery_sha256"],
        verdicts=None,
        delta=None,
    )
    fc.validate_interchange("comparison-v1", comparison)
    (run / "comparison.json").write_text(json.dumps(comparison))
    result = render(run)
    assert result["comparison"] == comparison
    content = (run / "report/index.html").read_text().split('id="compare"')[1].split("</section>")[0]
    assert comparison["label"] in content
    assert "superior" not in content


def test_pinned_receipt_is_hashed_and_changed_receipt_refuses(run):
    receipt = json.dumps({"timing_receipt_ms": {"work": 2.0}}).encode()
    (run / "timings.json").write_bytes(receipt)
    scores = load("scores-v1.json")
    for row in scores["guardrails"]:
        if row["metric"] == "p95_ms_per_face":
            row["timings_sha256"] = hashlib.sha256(receipt).hexdigest()
    (run / "scores.json").write_text(json.dumps(scores))
    result = render(run)
    assert result["inputs"]["timings.json"] == hashlib.sha256(receipt).hexdigest()
    before = (run / "report/index.html").read_bytes()
    (run / "timings.json").write_text('{"timing_receipt_ms":{"work":200}}')
    with pytest.raises(fc.FrameContractError, match="pinned"):
        render(run)
    assert (run / "report/index.html").read_bytes() == before


def test_crop_opt_in_without_manifest_has_named_reason(run):
    result = render(run, include_crops=True)
    assert result["failures"]["pool"]["crop_reason"] == "crop_artifacts_absent"
    assert "data:image" not in (run / "report/index.html").read_text()


def test_crop_manifest_refuses_query_source_and_hash_mismatch(run):
    frame = load("frame-v1.json")
    face, image = frame["faces"][0], frame["images"][0]
    manifest = {
        "schema": "firbench-crop-artifacts/v1",
        "frame_sha256": hashlib.sha256((run / "frame.json").read_bytes()).hexdigest(),
        "artifacts": [
            {
                "face_id": face["face_id"],
                "image_id": image["image_id"],
                "source_sha256": image["sha256"],
                "path": "source.png",
                "sha256": "0" * 64,
                "mime": "image/png",
            }
        ],
    }
    (run / "crop-artifacts.json").write_text(json.dumps(manifest))
    with pytest.raises(fc.FrameContractError, match="explicit crops"):
        render(run, include_crops=True)
    manifest["artifacts"][0]["path"] = "crops/face.png"
    (run / "crops").mkdir()
    (run / "crops/face.png").write_bytes(b"\x89PNG\r\n\x1a\ninvalid")
    (run / "crop-artifacts.json").write_text(json.dumps(manifest))
    with pytest.raises(fc.FrameContractError, match="MIME/SHA"):
        render(run, include_crops=True)
    manifest["artifacts"][0]["sha256"] = hashlib.sha256((run / "crops/face.png").read_bytes()).hexdigest()
    (run / "crop-artifacts.json").write_text(json.dumps(manifest))
    with pytest.raises(fc.FrameContractError, match="invalid image"):
        render(run, include_crops=True)


def test_duplicate_json_and_artifact_symlinks_refuse(run, tmp_path):
    (run / "comparison.json").write_text('{"schema_version":1,"schema_version":1}')
    with pytest.raises(fc.FrameContractError, match="duplicate"):
        render(run)
    (run / "comparison.json").unlink()
    foreign = tmp_path / "foreign.json"
    foreign.write_text(json.dumps(load("comparison-v1.json")))
    (run / "comparison.json").symlink_to(foreign)
    with pytest.raises(fc.FrameContractError, match="symlink"):
        render(run)


def test_actual_face_outcome_producer_binding(tmp_path):
    schema_path = Path(report.__file__).with_name("firbench_schemas") / "scores-v1.json"
    assert "face_outcomes" in json.loads(schema_path.read_bytes())["properties"]
    # Reuse the actual scorer fixture and its full 10000-draw decision, never a copied classifier.
    from scene.tests.test_eval_harness_firbench_score_io import fake_run
    from scripts.eval_harness import firbench_score_io

    path, decision, manifest, _frame, _records = fake_run.__wrapped__(tmp_path)
    manifest["firbench"].update(arms=["native"], created_at="2026-10-15T08:00:00Z", created_at_source="explicit")
    (path / "manifest.json").write_text(json.dumps(manifest))
    payload = firbench_score_io.score_run(path, decision=decision)
    assert "face_outcomes" in payload, "S0 schema arrived without its actual producer"
    fc.validate_interchange("scores-v1", payload)
    (path / "scores.json").write_text(json.dumps(payload))
    run = path / "repo/benchmarks/private/firbench/runs/actual-producer"
    run.mkdir(parents=True)
    for artifact in ("frame.json", "scores.json", "manifest.json", "timings.json"):
        (run / artifact).write_bytes((path / artifact).read_bytes())
    for source in (path / "legs").glob("*/searches.jsonl"):
        target = run / "legs" / source.parent.name / "searches.jsonl"
        target.parent.mkdir(parents=True)
        target.write_bytes(source.read_bytes())
    result = render(run)
    assert decision.interval.n_boot == 10000
    rows = result["failures"]["rows"]
    assert len(rows) == len(payload["face_outcomes"])
    by_key = {(r["leg_key"], r["arm"], r["fold"], r["face_id"]): r for r in rows}
    for source in payload["face_outcomes"]:
        row = by_key[source["leg_key"], source["arm"], source["fold"], source["face_id"]]
        assert (row["outcome"], row["outcome_available"], row["outcome_reason"]) == (
            source["outcome"],
            source["outcome_available"],
            source["outcome_reason"],
        )
        if source["fold_role"] == "fit":
            assert row["outcome"] is None and row["outcome_reason"] == "fit_fold_not_scored"
            assert row["default_visible"] is False


def test_only_explicit_gt_bound_crop_bytes_are_read_and_hashed(run, monkeypatch):
    from PIL import Image

    frame, scores = load("frame-v1.json"), load("scores-v1.json")
    put_search(run, search(frame, scores))
    buffer = io.BytesIO()
    Image.new("RGB", (1, 1), "red").save(buffer, format="PNG")
    crop = buffer.getvalue()
    path = run / "crops/f.png"
    path.parent.mkdir()
    path.write_bytes(crop)
    manifest = {
        "schema": "firbench-crop-artifacts/v1",
        "frame_sha256": hashlib.sha256((run / "frame.json").read_bytes()).hexdigest(),
        "artifacts": [
            {
                "face_id": frame["faces"][0]["face_id"],
                "image_id": frame["images"][0]["image_id"],
                "source_sha256": frame["images"][0]["sha256"],
                "path": "crops/f.png",
                "sha256": hashlib.sha256(crop).hexdigest(),
                "mime": "image/png",
            }
        ],
    }
    (run / "crop-artifacts.json").write_text(json.dumps(manifest))
    original = Path.read_bytes
    pixels = []

    def guarded(path):
        if path.suffix == ".png":
            pixels.append(path)
            assert path == run / "crops/f.png"
        assert path.suffix != ".npy"
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", guarded)
    result = render(run, include_crops=True)
    assert pixels == [path]
    assert result["inputs"]["crops/f.png"] == hashlib.sha256(crop).hexdigest()
    assert "crop-artifacts.json" in result["inputs"]
    assert result["failures"]["rows"][0]["crop_data_uri"].startswith("data:image/png;base64,")
    assert result["failures"]["pool"]["crop_images_shown"] == 0  # legacy classification has no default selection


def test_detector_and_duplicate_rows_never_enter_gt_inventory(run):
    frame, scores = load("frame-v1.json"), load("scores-v1.json")
    row = search(frame, scores)
    path = run / "legs" / row["leg_key"] / "searches.jsonl"
    path.parent.mkdir(parents=True)
    background = dict(
        row, face_id="det-only", identity_id=None, identity_status="unknown", unit_id="background:" + row["image_id"]
    )
    duplicate = dict(background, face_id="duplicate-detection", unit_id=None)
    path.write_text("".join(json.dumps(r) + "\n" for r in (row, background, duplicate)))
    result = render(run)
    rows = result["failures"]["rows"]
    assert_legacy_declared_inventory(rows, frame, scores, row)
    assert {r["face_id"] for r in rows}.isdisjoint({background["face_id"], duplicate["face_id"]})
    assert result["failures"]["background_units_detector_only"] == 2
    assert result["failures"]["pool"]["background_detector_rows"] == 2
    assert result["failures"]["pool"]["fixed_background_source_units"] == 1
    assert result["failures"]["pool"]["primary_background_source_units"] == 0
    assert result["failures"]["pool"]["overall_gt_faces"] == 1
    assert result["failures"]["pool"]["inventory_faces"] == 1
    assert result["failures"]["pool"]["inventory_rows"] == 2


def test_pair_cell_interval_withheld_even_if_present_below_floor(run):
    scores = load("scores-v1.json")
    cell = scores["cells"][0]
    cell.update(
        scored=True, fnir=0.321987, n_units=40, n_psu=29, interval={"lower": 0.123456, "upper": 0.654321, "level": 0.95}
    )
    (run / "scores.json").write_text(json.dumps(scores))
    render(run)
    content = (run / "report/index.html").read_text().split('id="pair-cells"')[1].split("</section>")[0]
    assert "not scored" in content
    assert "0.321" not in content and "0.123" not in content and "0.654" not in content
    exported = (run / "report/cells.csv").read_text()
    assert "not scored" in exported and "0.321" not in exported


def test_scope_inventory_keeps_challenge_and_attribution_separate(run):
    import copy

    frame, scores = load("frame-v1.json"), load("scores-v1.json")
    base_face, base_image = frame["faces"][0], frame["images"][0]
    frame["images"], frame["faces"], frame["psu_map"], frame["folds"] = [], [], [], []
    frame["fold_roles"] = [{"fold": 0, "role": "test"}]
    for index, sampling in enumerate(("probability", "probability", "challenge")):
        image = dict(base_image, image_id=f"image-{index}", sampling_arm=sampling)
        face = copy.deepcopy(base_face)
        face.update(face_id=f"face-{index}", image_id=image["image_id"])
        if index:
            face.update(identity_status="unknown", identity_id=None)
        frame["images"].append(image)
        frame["faces"].append(face)
        frame["psu_map"].append({"image_id": image["image_id"], "psu_id": f"psu-{index}"})
        frame["folds"].append({"psu_id": f"psu-{index}", "fold": 0})
    frame["sampling_arm_counts"] = {"probability": 2, "challenge": 1}
    (run / "frame.json").write_text(json.dumps(frame))
    keys = [r["leg_key"] for r in scores["legs"]]
    manifest = {
        "firbench": {
            "created_at": "2026-10-15T08:00:00Z",
            "created_at_source": "explicit",
            "leg_keys": keys,
            "arms": ["native", "gt_crop_redetect"],
            "gallery_membership": [
                {
                    "leg_key": leg,
                    "fold": 0,
                    "gallery_sha256": "b" * 64,
                    "enrolled_identity_ids": [base_face["identity_id"]],
                    "identity_folds": {base_face["identity_id"]: 0},
                }
                for leg in keys
            ],
        }
    }
    (run / "manifest.json").write_text(json.dumps(manifest))
    for leg in keys:
        rows = []
        for index, face in enumerate(frame["faces"]):
            for arm in manifest["firbench"]["arms"]:
                row = search(frame, scores)
                row.update(
                    face_id=face["face_id"],
                    image_id=face["image_id"],
                    psu_id=f"psu-{index}",
                    identity_status=face["identity_status"],
                    identity_id=face["identity_id"],
                    unit_id=face["face_id"] if index else None,
                    sampling_arm=frame["images"][index]["sampling_arm"],
                    leg_key=leg,
                    arm=arm,
                    gallery_sha256="b" * 64,
                    cell=["unknown", "unknown"],
                    top_k=[[base_face["identity_id"], 0.9]],
                )
                rows.append(row)
        path = run / "legs" / leg / "searches.jsonl"
        path.parent.mkdir(parents=True)
        path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    result = render(run)
    pool = result["failures"]["pool"]
    assert pool["overall_gt_faces"] == pool["inventory_faces"] == 3
    assert pool["inventory_rows"] == 12
    assert pool["fixed_background_source_units"] == 3
    assert pool["primary_background_source_units"] == 2
    assert pool["eligible_rows"] == pool["selected_rows"] == 0
    for leg in keys:
        assert pool["scope_counts_by_leg"][leg] == {"mated": 1, "nonmated": 1, "unresolved": 0}
        assert pool["nonmated_gt_source_units_by_leg"][leg] == 1


def test_unresolved_face_is_never_nonmated_or_qualified(run):
    frame, scores = load("frame-v1.json"), load("scores-v1.json")
    frame["faces"][0].update(identity_status="unresolved", identity_id=None)
    frame["identity_folds"] = []
    frame["fold_roles"][0]["role"] = "test"
    (run / "frame.json").write_text(json.dumps(frame))
    put_search(run, search(frame, scores))
    result = render(run)
    row = result["failures"]["rows"][0]
    assert row["mated"] is None and row["qualified"] is False and row["default_visible"] is False
    assert result["failures"]["pool"]["scope_counts"] == {"mated": 0, "nonmated": 0, "unresolved": 1}


@pytest.mark.parametrize(
    "corruption,reason",
    [
        ("missing_outcome", "inventory.*declared scope"),
        ("duplicate_outcome", "duplicate/foreign declared GT key"),
        ("foreign_gt", "duplicate/foreign declared GT key"),
        ("foreign_psu", "psu_id contradicts"),
        ("missing_search", "inventory.*declared scope"),
        ("duplicate_search", "duplicate GT search key"),
        ("nonfinite_score", "non-finite"),
    ],
)
def test_corrupt_new_producer_artifacts_reach_consumer_boundary(tmp_path, corruption, reason):
    from scene.tests.test_eval_harness_firbench_report import _make_run

    run = _make_run(tmp_path)
    # Establish that the starting specimen reaches and passes the real consumer.
    render(run)
    original_report = {p.name: p.read_bytes() for p in (run / "report").iterdir()}
    scores = json.loads((run / "scores.json").read_bytes())
    if corruption == "missing_outcome":
        scores["face_outcomes"].pop()
    elif corruption == "duplicate_outcome":
        scores["face_outcomes"].append(dict(scores["face_outcomes"][0]))
    elif corruption == "foreign_gt":
        scores["face_outcomes"][0]["face_id"] = "foreign-gt"
    elif corruption == "foreign_psu":
        scores["face_outcomes"][0]["psu_id"] = "foreign-psu"
    elif corruption == "nonfinite_score":
        scores["legs"][0]["tau"]["data"]["value"] = float("nan")
    else:
        path = next((run / "legs").glob("*/searches.jsonl"))
        row = path.read_bytes()
        path.write_bytes(b"" if corruption == "missing_search" else row + row)
    (run / "scores.json").write_text(json.dumps(scores))
    inputs = {p.relative_to(run): p.read_bytes() for p in run.rglob("*") if p.is_file()}
    with pytest.raises(fc.FrameContractError, match=reason):
        report.render_report(run, out_dir=run / "refused")
    assert not (run / "refused").exists()
    assert {p.relative_to(run): p.read_bytes() for p in run.rglob("*") if p.is_file()} == inputs
    assert {p.name: p.read_bytes() for p in (run / "report").iterdir()} == original_report


@pytest.mark.parametrize("unavailable", ["native_arm", "calibration"])
def test_actual_producer_unavailable_rows_remain_unclassified(tmp_path, unavailable):
    from dataclasses import replace

    from scene.tests.test_eval_harness_firbench_report import AURA, SFACE, _frame, _legacy_scores, _make_run, _search

    frame, scores = _frame(), _legacy_scores()
    searches = {leg: [_search("face-0001", "image-0001", "missed", leg=leg)] for leg in (SFACE, AURA)}
    if unavailable == "native_arm":
        for leg in searches:
            searches[leg] = [
                replace(
                    searches[leg][0],
                    arm_availability=fc.ArmStatus.unavailable,
                    stage_reached=fc.SearchStage.unavailable,
                    timing_receipt_ref=None,
                )
            ]
        expected_reason = "arm_unavailable"
    else:
        for leg in scores["legs"]:
            leg["tau"] = {"status": "unavailable", "reason": "tau_infeasible", "data": None}
        expected_reason = "calibration_unavailable"
    run = _make_run(tmp_path, frame=frame, scores=scores, searches=searches)
    producer = json.loads((run / "scores.json").read_bytes())["face_outcomes"]
    assert producer and all(r["outcome"] is None and r["outcome_reason"] == expected_reason for r in producer)
    result = render(run)
    assert len(result["failures"]["rows"]) == len(producer)
    assert all(
        r["outcome"] is None
        and not r["outcome_available"]
        and not r["default_visible"]
        and r["outcome_reason"] == expected_reason
        for r in result["failures"]["rows"]
    )
    assert result["failures"]["pool"]["eligible_rows"] == 0
    assert result["failures"]["pool"]["classification_status"] == "unavailable"
