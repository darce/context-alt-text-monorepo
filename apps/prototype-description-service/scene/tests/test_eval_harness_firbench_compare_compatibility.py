"""File-bound comparison policy using default CLI runs and fake model kernels only."""

import ast
import inspect
import json
from dataclasses import replace
from pathlib import Path

import pytest

from scene.tests import test_eval_harness_firbench_cli_integration as integration
from scene.tests.test_eval_harness_firbench_cli_integration import (
    AT,
    runtime_files,
    write_json,
)
from scripts.eval_harness import firbench_cli as cli
from scripts.eval_harness import firbench_contract as fc
from scripts.eval_harness import firbench_legs as legs
from scripts.eval_harness import firbench_score_io as io


@pytest.fixture
def runs(runtime_files, monkeypatch):
    f = runtime_files
    monkeypatch.setattr(cli, "_repo_root", lambda: f.repo)

    def produce(name, *, edit=None, arms="native"):
        monkeypatch.setattr(integration, "ARMS", tuple(fc.Arm(a) for a in arms.split(",")))
        raw = json.loads(f.decision.read_text())
        if edit:
            edit(raw)
        decision = f.decision.with_name(f"{name}.json")
        write_json(decision, raw)
        run = f.private / "run"
        assert cli.main([
            "run", "--frame", "fake-only", "--decision", str(decision),
            "--legs", "sface,auraface,insightface", "--arms", arms,
            "--out", str(run), "--created-at", AT,
        ]) == 0
        assert cli.main(["score", str(run)]) == 0
        destination = f.private / name
        run.rename(destination)
        return destination

    f.produce = produce
    return f


def identity(f, run, treatment=None):
    return cli._run_identity(run, repo_root=f.repo, treatment=treatment)


def compare(f, a, b, treatment=None):
    return cli._comparison_compatibility(identity(f, a, treatment), identity(f, b, treatment), treatment=treatment)


def test_actual_identity_typed_and_exact_wire(runs):
    a, b = runs.produce("a"), runs.produce("b")
    # Comparison may validate persisted evidence, but cannot score/refit or reopen pixels.
    for path in runs.private.glob("*.png"):
        path.unlink()
    runs.source.unlink()
    runs.templates.unlink()
    runs.binding_path.unlink()
    first = identity(runs, a)
    assert first["run_dir"] == a
    assert isinstance(first["decision"], fc.DecisionManifest)
    assert isinstance(first["inventory"], io.Inventory)
    assert first["records"] and isinstance(first["records"][0], legs.FaceSearchRecord)
    result = compare(runs, a, b)
    assert result["state"] == "comparable"
    assert result["differences"] == []
    assert result["analysis_arm_a"] is result["analysis_arm_b"] is fc.Arm.native
    schema = json.loads((Path(fc.__file__).parent / "firbench_schemas/comparison-v1.json").read_text())
    assert set(result["compatibility"]) == set(schema["properties"]["compatibility"]["required"])
    assert len(result["compatibility"]) == 14
    assert result["compatibility"]["annotation_bytes_sha256"]


def test_raw_frame_bytes_never_relaxed(runs):
    a, b = runs.produce("a"), runs.produce("b")
    with (b / "frame.json").open("ab") as stream:
        stream.write(b" ")
    with pytest.raises(fc.FrameContractError, match="frame_bytes_sha256"):
        compare(runs, a, b, "arm")


def test_declared_fpir_only_and_nested_never_ignored(runs):
    a = runs.produce("a")
    b = runs.produce("b", edit=lambda raw: raw["primary"].update(fpir_target=0.05))
    with pytest.raises(fc.FrameContractError, match="fpir_target"):
        compare(runs, a, b)
    assert compare(runs, a, b, "fpir_target")["state"] == "comparable"
    c = runs.produce("c", edit=lambda raw: (raw["primary"].update(fpir_target=0.05), raw["hypotheses"][1].update(margin=0.06)))
    with pytest.raises(fc.FrameContractError, match="hypotheses.1.margin"):
        compare(runs, a, c, "fpir_target")


@pytest.mark.parametrize("changed_kind", [fc.LegKind.auraface, fc.LegKind.sface])
def test_space_change_with_genuine_derived_gallery_hash(runs, monkeypatch, changed_kind):
    a = runs.produce("a")
    factory = legs.load_pinned_face_pipeline_leg

    def changed(kind, **kwargs):
        model = factory(kind, **kwargs)
        if kind is not changed_kind:
            return model
        embed = model.embedder.embed

        def rotated(batch):
            output = embed(batch)
            output.vectors = output.vectors[:, ::-1].copy()
            return output

        model.embedder.embed = rotated
        return replace(model, space="new-fake-model-contract")

    monkeypatch.setattr(legs, "load_pinned_face_pipeline_leg", changed)
    b = runs.produce("b")
    if changed_kind is fc.LegKind.sface:
        # The basis gallery is stored inside frame.json: even an expected derived
        # vector hash cannot excuse changed actual frame bytes.
        with pytest.raises(fc.FrameContractError, match="frame_bytes_sha256"):
            compare(runs, a, b, "gallery_sha256")
        return
    result = compare(runs, a, b)
    assert result["state"] == "comparable"
    assert result["differences"] == []
    assert result["leg_changes"] == [{
        "leg_kind": "auraface", "leg_key_a": identity(runs, a)["legs"]["auraface__native"],
        "leg_key_b": identity(runs, b)["legs"]["auraface__native"],
        "label": "leg contract changed (expected)",
    }]
    templates = json.loads(runs.templates.read_text())
    templates["templates"].reverse()
    integration.rebind_templates(runs, templates)
    c = runs.produce("c")
    with pytest.raises(fc.FrameContractError, match="gallery_sha256"):
        compare(runs, a, c)


@pytest.mark.parametrize("field,value", [
    ("estimand", "declared alternative FNIR estimand"), ("fpir_target", 0.05),
])
def test_exact_declared_primary_leaf(runs, field, value):
    a = runs.produce("a")
    b = runs.produce("b", edit=lambda raw: raw["primary"].update({field: value}))
    result = compare(runs, a, b, field)
    assert result["state"] == "comparable"
    assert result["differences"] == [field]
    assert identity(runs, a, field)["decision_sha256_without_treatment"] == identity(runs, b, field)["decision_sha256_without_treatment"]


@pytest.mark.parametrize("path,value", [
    (("interval", "seed"), 2429382369),
    (("interval", "n_boot"), 10001),
    (("hypotheses", 1, "margin"), 0.06),
    (("power",), 0.81),
    (("guardrails", 0, "rule"), "fpir <= 0.1"),
    (("secondary_fpir_targets", 0), 0.06),
    (("disconfirmers", 0, "statement"), "A different predeclared disconfirmer"),
])
def test_nested_undeclared_policy_refuses_even_with_two_allowed_changes(runs, path, value):
    a = runs.produce("a")

    def edit(raw):
        raw["primary"].update(fpir_target=0.05, estimand="declared alternative estimand")
        parent = raw
        for key in path[:-1]:
            parent = parent[key]
        parent[path[-1]] = value

    b = runs.produce("b", edit=edit)
    with pytest.raises(fc.FrameContractError, match="\\.".join(str(p) for p in path)):
        compare(runs, a, b, "fpir_target")


def test_multifactor_and_never_fields_precede_outcome_validation(runs):
    a = runs.produce("a")
    b = runs.produce("b", edit=lambda raw: raw["primary"].update(fpir_target=0.05, estimand="alternative estimand"))
    result = compare(runs, a, b)
    assert result["state"] == "exploratory"
    assert set(result["differences"]) == {"fpir_target", "estimand"}
    frame = b / "frame.json"
    frame.write_bytes(frame.read_bytes() + b"\n")
    first, second = identity(runs, a), identity(runs, b)
    with pytest.raises(fc.FrameContractError, match="frame_bytes_sha256"):
        cli._comparison_compatibility(first, second, treatment="fpir_target")


@pytest.mark.parametrize("treatment", ["unknown", "frame_id", "frame_bytes_sha256", "scorer_sha", "boundary_semantics", "interval"])
def test_unknown_or_never_treatment_refuses_before_file_reads(runs, treatment):
    with pytest.raises(fc.FrameContractError, match="treatment"):
        identity(runs, runs.private / "absent", treatment)


def test_arm_profiles_default_native_and_explicit_unambiguous_treatment(runs):
    a = runs.produce("a")
    b = runs.produce("b", arms="native,gt_crop_redetect")
    with pytest.raises(fc.FrameContractError, match="arm"):
        compare(runs, a, b)
    result = compare(runs, a, b, "arm")
    assert result["differences"] == ["arm"]
    assert (result["analysis_arm_a"], result["analysis_arm_b"]) == (fc.Arm.native, fc.Arm.gt_crop_redetect)
    c = runs.produce("c", arms="native,gt_crop_redetect,cached_yunet_landmark_replay")
    assert compare(runs, c, c, "arm")["analysis_arm_a"] is fc.Arm.native
    with pytest.raises(fc.FrameContractError, match="ambiguous.*arm"):
        compare(runs, a, c, "arm")
    manifest = json.loads((c / "manifest.json").read_text())
    manifest["firbench"]["analysis_arm"] = "cached_yunet_landmark_replay"
    write_json(c / "manifest.json", manifest)
    assert compare(runs, a, c, "arm")["analysis_arm_b"] is fc.Arm.cached_yunet_landmark_replay
    manifest["firbench"]["analysis_arm"] = "unknown"
    write_json(c / "manifest.json", manifest)
    with pytest.raises(fc.FrameContractError, match="unknown.*arm"):
        compare(runs, a, c, "arm")


@pytest.mark.parametrize("filename", ["manifest.json", "frame.json", "scores.json", "searches.jsonl", "decision.json"])
@pytest.mark.parametrize("bad", ["duplicate", "nonfinite", "overflow"])
def test_strict_actual_json(runs, filename, bad):
    run = runs.produce("a")
    if filename == "searches.jsonl":
        path = next((run / "legs").glob("*/searches.jsonl"))
    elif filename == "decision.json":
        path = runs.decision.with_name("a.json")
    else:
        path = run / filename
    content = path.read_text()
    prefix = {"duplicate": '"schema_version":1,"schema_version":1,',
              "nonfinite": '"invalid":NaN,', "overflow": '"invalid":1e999,'}[bad]
    if filename == "searches.jsonl" and bad == "overflow":
        assert '"inclusion_probability":1.0' in content
        path.write_text(content.replace('"inclusion_probability":1.0', '"inclusion_probability":1e999', 1))
    else:
        path.write_text(content.replace("{", "{" + prefix, 1))
    if filename == "decision.json":
        # Keep the raw SHA binding current to reach the actual strict JSON reader.
        manifest = json.loads((run / "manifest.json").read_text())
        manifest["firbench"]["decision_sha256"] = cli._file_sha256(path)
        write_json(run / "manifest.json", manifest)
    with pytest.raises(fc.FrameContractError, match="duplicate|finite|JSON|expected number"):
        identity(runs, run)


def test_binding_tampering_is_not_hidden_by_copied_compatibility(runs):
    run = runs.produce("a")
    path = run / "manifest.json"
    original = path.read_bytes()
    for field, value, reason in [
        ("leg_keys", ["../unsafe"], "leg_key"),
        ("scorer_sha256", None, "scorer_sha"),
        ("annotation_bytes_sha256", None, "annotation_bytes_sha256"),
        ("scores_sha256", "a" * 64, "scores_sha256"),
        ("gallery_hash_basis", None, "gallery_hash_basis"),
        ("decision_path", "../../outside.json", "containment"),
    ]:
        manifest = json.loads(original)
        manifest["firbench"][field] = value
        manifest["compatibility"] = {"frame_bytes_sha256": "a" * 64}
        write_json(path, manifest)
        with pytest.raises(fc.FrameContractError, match=reason):
            identity(runs, run)
    path.write_bytes(original)
    manifest = json.loads(original)
    manifest["firbench"]["leg_keys"].append(manifest["firbench"]["leg_keys"][0])
    write_json(path, manifest)
    with pytest.raises(fc.FrameContractError, match="duplicate.*leg"):
        identity(runs, run)


@pytest.mark.parametrize("filename", ["frame.json", "scores.json", "searches.jsonl", "decision.json"])
def test_symlink_containment(runs, filename):
    run = runs.produce("a")
    path = (next((run / "legs").glob("*/searches.jsonl")) if filename == "searches.jsonl" else run / filename)
    if filename == "decision.json":
        path = runs.decision.with_name("a.json")
    outside = runs.repo.parent / "outside.json"
    outside.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(outside)
    with pytest.raises(fc.FrameContractError, match="containment"):
        identity(runs, run)


def test_actual_score_and_search_context_tampering(runs):
    run = runs.produce("a")
    path = run / "scores.json"
    original = path.read_bytes()
    for field, value in [("frame_id", "wrong"), ("decision_sha256", "a" * 64), ("planning_icc", 0.2)]:
        scores = json.loads(original)
        scores[field] = value
        write_json(path, scores)
        with pytest.raises(fc.FrameContractError, match=field):
            identity(runs, run)
    scores = json.loads(original)
    scores["legs"].append(scores["legs"][0])
    write_json(path, scores)
    with pytest.raises(fc.FrameContractError, match="duplicate.*leg"):
        identity(runs, run)
    path.write_bytes(original)
    search = next((run / "legs").glob("*/searches.jsonl"))
    rows = [json.loads(line) for line in search.read_text().splitlines()]
    original_search = search.read_bytes()
    for field, value, reason in [
        ("psu_id", "wrong", "PSU"), ("fold", (rows[0]["fold"] + 1) % 5, "fold"),
        ("inclusion_probability", 0.5, "sampling"), ("image_id", "outside", "image"),
        ("face_id", "invented-face", "detector-only"), ("gallery_sha256", "a" * 64, "gallery SHA"),
        ("arm", "gt_crop_redetect", "arm"),
    ]:
        rows = [json.loads(line) for line in original_search.splitlines()]
        rows[0][field] = value
        if field == "face_id" and rows[0]["timing_receipt_ref"] is not None:
            rows[0]["timing_receipt_ref"] = f"{rows[0]['leg_key']}/{rows[0]['arm']}/{value}"
        search.write_text("".join(json.dumps(row) + "\n" for row in rows))
        with pytest.raises(fc.FrameContractError, match=reason):
            identity(runs, run)


def test_same_space_gallery_hash_refuses_and_declared_gallery_allows(runs, monkeypatch):
    a = runs.produce("a")
    factory = legs.load_pinned_face_pipeline_leg

    def changed(kind, **kwargs):
        model = factory(kind, **kwargs)
        if kind is fc.LegKind.auraface:
            embed = model.embedder.embed

            def rotated(batch):
                output = embed(batch)
                output.vectors = output.vectors[:, ::-1].copy()
                return output

            model.embedder.embed = rotated
        return model

    monkeypatch.setattr(legs, "load_pinned_face_pipeline_leg", changed)
    b = runs.produce("b")
    with pytest.raises(fc.FrameContractError, match="gallery_sha256"):
        compare(runs, a, b)
    assert compare(runs, a, b, "gallery_sha256")["differences"] == ["gallery_sha256"]


def test_treatment_projection_retains_every_other_actual_policy(runs):
    run = runs.produce("a")
    raw = identity(runs, run)["raw_decision"]
    projected = cli._without_treatment(raw, "fpir_target")
    assert projected["primary"] == {k: v for k, v in raw["primary"].items() if k != "fpir_target"}
    for key in raw.keys() - {"primary"}:
        assert projected[key] == raw[key]
    assert raw["interval"]["n_boot"] == 10000


def test_actual_annotation_bytes_remain_bound_to_face_ids(runs):
    a, b = runs.produce("a"), runs.produce("b")
    frame_path = b / "frame.json"
    frame = json.loads(frame_path.read_text())
    first, second = frame["faces"][:2]
    # Preserve the annotation multiset while changing which actual face owns each label.
    assert first["annotation"] != second["annotation"]
    first["annotation"], second["annotation"] = second["annotation"], first["annotation"]
    labels = {face["face_id"]: io.occluder_label(face["annotation"]["occluders"]) for face in frame["faces"]}
    write_json(frame_path, frame)
    for path in (b / "legs").glob("*/searches.jsonl"):
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        for row in rows:
            row["cell"][0] = labels[row["face_id"]]
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    assert identity(runs, a)["annotation_bytes_sha256"] != identity(runs, b)["annotation_bytes_sha256"]
    with pytest.raises(fc.FrameContractError, match="annotation_bytes_sha256"):
        compare(runs, a, b, "gallery_sha256")


def test_actual_template_lineage_and_split_never_relaxes_frame(runs):
    a = runs.produce("a")
    b = runs.produce("b", edit=lambda raw: raw["gallery_lineage"].update(split_seed=2468935813))
    with pytest.raises(fc.FrameContractError, match="frame_bytes_sha256"):
        compare(runs, a, b, "fold_calibration_policy")
    templates = json.loads(runs.templates.read_text())
    templates["templates"].reverse()
    integration.rebind_templates(runs, templates)
    c = runs.produce("c")
    with pytest.raises(fc.FrameContractError, match="gallery_sha256"):
        compare(runs, a, c)
    assert compare(runs, a, c, "gallery_sha256")["differences"] == ["gallery_sha256"]


def test_runtime_swap_between_legs_is_never_treatable(runs, monkeypatch):
    factory = legs.load_pinned_face_pipeline_leg
    versions = {fc.LegKind.sface: "cv-a", fc.LegKind.auraface: "cv-b"}

    def model(kind, **kwargs):
        return replace(factory(kind, **kwargs), opencv_version=versions[kind])

    monkeypatch.setattr(legs, "load_pinned_face_pipeline_leg", model)
    a = runs.produce("a")
    versions[fc.LegKind.sface], versions[fc.LegKind.auraface] = versions[fc.LegKind.auraface], versions[fc.LegKind.sface]
    b = runs.produce("b")
    assert identity(runs, a)["opencv_version"] == identity(runs, b)["opencv_version"]
    with pytest.raises(fc.FrameContractError, match="opencv_version"):
        compare(runs, a, b, "arm")


def test_other_frames_and_primary_siblings_cannot_be_blanket_ignored(runs):
    a = runs.produce("a")

    def extra_frame(raw):
        raw["primary"]["fpir_target"] = 0.05
        raw["frames"].append({**raw["frames"][0], "frame_id": "unused-fake-frame"})

    b = runs.produce("b", edit=extra_frame)
    with pytest.raises(fc.FrameContractError, match="frames"):
        compare(runs, a, b, "fpir_target")
    path = runs.decision.with_name("b.json")
    raw = json.loads(path.read_text())
    raw["primary"]["end_to_end"] = False
    digest = write_json(path, raw)
    manifest = json.loads((b / "manifest.json").read_text())
    manifest["firbench"]["decision_sha256"] = digest
    write_json(b / "manifest.json", manifest)
    with pytest.raises(fc.FrameContractError, match="primary.end_to_end"):
        identity(runs, b, "fpir_target")


def test_scorer_and_boundary_refuse_before_outcomes_even_with_treatment(runs):
    a = runs.produce("a")
    b = runs.produce("b", edit=lambda raw: raw.update(boundary_semantics="legacy_v1"))
    first, second = identity(runs, a), identity(runs, b)
    with pytest.raises(fc.FrameContractError, match="boundary_semantics"):
        cli._comparison_compatibility(first, second, treatment="fpir_target")
    manifest = json.loads((a / "manifest.json").read_text())
    manifest["firbench"]["scorer_sha256"] = "a" * 64
    write_json(a / "manifest.json", manifest)
    with pytest.raises(fc.FrameContractError, match="scorer_sha"):
        cli._comparison_compatibility(first, identity(runs, a), treatment="arm")


def test_timing_receipt_and_actual_outcome_tampering_refuse(runs):
    a, b = runs.produce("a"), runs.produce("b")
    path = b / "scores.json"
    original = path.read_bytes()
    scores = json.loads(original)
    scores["guardrails"][0]["timings_sha256"] = "a" * 64
    write_json(path, scores)
    with pytest.raises(fc.FrameContractError, match="timings_sha256"):
        identity(runs, b)
    scores = json.loads(original)
    fnir = scores["legs"][0]["operating_point"]["fnir"]
    assert fnir["status"] == "available"
    fnir["data"]["rate"] = 0.5
    write_json(path, scores)
    with pytest.raises(fc.FrameContractError, match="FNIR.*outcome"):
        compare(runs, a, b)


def test_actual_face_inventory_and_registry_bindings(runs):
    a = runs.produce("a")
    source = json.loads(runs.source.read_text())
    source["faces"][0]["face_id"] = "replacement-face"
    integration.rebind_source(runs, source)
    b = runs.produce("b")
    with pytest.raises(fc.FrameContractError, match="face_set_sha256"):
        compare(runs, a, b, "arm")
    path = b / "manifest.json"
    original = path.read_bytes()
    manifest = json.loads(original)
    manifest["firbench"]["gallery_membership"].append(manifest["firbench"]["gallery_membership"][0])
    write_json(path, manifest)
    with pytest.raises(fc.FrameContractError, match="duplicate gallery registry"):
        identity(runs, b)
    manifest = json.loads(original)
    folds = manifest["firbench"]["gallery_membership"][0]["identity_folds"]
    folds["id-0000"] = (folds["id-0000"] + 1) % 5
    write_json(path, manifest)
    with pytest.raises(fc.FrameContractError, match="fold provenance"):
        identity(runs, b)


def test_comparison_read_boundary_cannot_score_refit_or_read_pixels():
    functions = (cli._run_identity, cli._comparison_compatibility, cli._compatibility_scores,
                 cli._compatibility_path, cli._compatibility_arm, cli._compatibility_leaf_differences)
    forbidden = {"score_run", "_score_run", "calibrate_tau", "_calibrate", "_pixels", "imread", "refit"}
    for function in functions:
        tree = ast.parse(inspect.getsource(function))
        calls = {node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
                 for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, (ast.Attribute, ast.Name))}
        assert not calls & forbidden, function.__name__
