"""Declared arm inventory versus native summaries, from the actual public CLI."""

from __future__ import annotations

import json
import shutil
from dataclasses import replace
from types import SimpleNamespace

import pytest

from scene.tests import test_eval_harness_firbench_cli_integration as native
from scripts.eval_harness import firbench_cli as cli
from scripts.eval_harness import firbench_contract as fc
from scripts.eval_harness import firbench_report as report


@pytest.fixture(scope="module")
def scored_run(tmp_path_factory):
    # S3 resolves its decision against the source checkout. The existing native
    # fixture owns/cleans its private directory; run this checkout serially.
    with pytest.MonkeyPatch.context() as patch:
        fixture = native.runtime_files.__wrapped__(
            tmp_path_factory.mktemp("native-scope"), patch,
            SimpleNamespace(node=SimpleNamespace(name="test_default_run_and_actual_score")),
        )
        files = next(fixture)
        try:
            patch.setattr(cli, "_repo_root", lambda: files.repo)
            directory = files.private / "run"
            assert fc.load_decision_manifest(files.decision).interval.n_boot == 10000
            # A fake detector misses one actual test-fold query. Classification,
            # calibration, eligibility and all 10000 bootstrap draws stay real.
            from scripts.eval_harness import firbench_legs as legs

            factory = legs.load_pinned_face_pipeline_leg

            def miss_one_query(kind, **kwargs):
                leg = factory(kind, **kwargs)
                detect = leg.detector.detect

                def kernel(batch):
                    detections = detect(batch)
                    if all(pixel[0, 0, 1] != 1 for pixel in batch):
                        return detections
                    frame = read(directory / "frame.json")
                    psus = {r["image_id"]: r["psu_id"] for r in frame["psu_map"]}
                    folds = {r["psu_id"]: r["fold"] for r in frame["folds"]}
                    test_fold = next(r["fold"] for r in frame["fold_roles"] if r["role"] == "test")
                    gallery = next(
                        r for r in read(directory / "manifest.json")["firbench"]["gallery_membership"]
                        if r["leg_key"].startswith("sface__native__") and r["fold"] == test_fold
                    )["enrolled_identity_ids"]
                    target = next(
                        f for f in frame["faces"]
                        if folds[psus[f["image_id"]]] == test_fold and f["identity_id"] in gallery
                    )
                    index = int(target["image_id"].rsplit("-", 1)[1]) + 1
                    return [
                        [] if pixel[0, 0, 1] == 1 and pixel[0, 0, 0] == index else found
                        for pixel, found in zip(batch, detections, strict=True)
                    ]

                return replace(leg, detector=SimpleNamespace(detect=kernel))

            patch.setattr(legs, "load_pinned_face_pipeline_leg", miss_one_query)
            assert cli.main([
                "run", "--frame", "fake-only", "--decision", str(files.decision),
                "--legs", ",".join(k.value for k in native.KINDS),
                "--arms", ",".join(a.value for a in native.ARMS),
                "--created-at", native.AT, "--out", str(directory),
            ]) == 0
            # Downstream stages must consume frozen files, never source/pixels.
            for path in files.private.glob("*.png"):
                path.unlink()
            files.source.unlink()
            files.templates.unlink()
            files.binding_path.unlink()
            assert cli.main(["score", str(directory)]) == 0
            yield directory
        finally:
            fixture.close()


def read(path):
    return json.loads(path.read_bytes())


def test_default_cli_native_and_attribution_inventory(scored_run):
    directory = scored_run
    before = {p: p.read_bytes() for p in directory.rglob("*") if p.is_file()}
    assert cli.main(["report", str(directory)]) == 0
    assert {p: p.read_bytes() for p in before} == before
    scores = read(directory / "scores.json")
    frame = read(directory / "frame.json")
    declared = read(directory / "manifest.json")["firbench"]["leg_keys"]
    native_keys = {k for k in declared if k.split("__")[1] == "native"}
    assert len(declared) == 9 and len(native_keys) == len(scores["legs"]) == 3
    assert {r["leg_key"] for r in scores["legs"]} == native_keys
    result = read(directory / "report/report.json")
    rows = result["failures"]["rows"]
    expected = {(k, f["face_id"]) for k in declared for f in frame["faces"]}
    assert len(rows) == len(expected) == 270
    assert {(r["leg_key"], r["face_id"]) for r in rows} == expected
    outcomes = {(r["leg_key"], r["face_id"]): r for r in scores["face_outcomes"]}
    assert len(outcomes) == len(expected)
    assert any(r["default_visible"] and r["outcome"] == "missed" for r in rows)
    for row in rows:
        original = outcomes[row["leg_key"], row["face_id"]]
        assert row["arm"] == row["leg_key"].split("__")[1]
        assert row["outcome"] == original["outcome"]
        assert row["outcome_reason"] == original["outcome_reason"]
        assert row["default_visible"] == bool(
            row["qualified"] and row["is_failure"] and row["arm"] == "native"
            and row["fold_role"] == "test" and row["sampling_arm"] == "probability"
        )
        if row["fold_role"] == "fit":
            assert row["outcome"] is None and row["outcome_reason"] == "fit_fold_not_scored"
        if row["leg_key"].startswith("insightface__") and row["arm"] != "native":
            assert row["arm_availability"] == "unavailable_fused"
            assert row["stage"] is None and row["outcome"] is None
            assert not row["outcome_available"] and not row["default_visible"]
    for key in declared:
        assert f"legs/{key}/searches.jsonl" in result["inputs"]
    assert (directory / "clusters.json").is_file()
    frozen = {p: p.read_bytes() for p in directory.rglob("*") if p.is_file()}
    assert cli.main(["report", str(directory)]) == 0
    assert {p: p.read_bytes() for p in frozen} == frozen


@pytest.fixture
def candidate(scored_run, tmp_path):
    path = tmp_path / "repo/benchmarks/private/firbench/run"
    shutil.copytree(scored_run, path, ignore=shutil.ignore_patterns("report"))
    return path


def render(path):
    return report.render_report(path, out_dir=path / "report")


def write(path, value):
    path.write_text(json.dumps(value))


@pytest.mark.parametrize("mutation,reason", [
    ("missing_file", "declared leg searches unavailable"),
    ("empty", "inventory.*declared scope"),
    ("missing", "inventory.*declared scope"),
    ("duplicate", "duplicate GT search key"),
    ("foreign", "GT inventory.*declared scope"),
    ("extra", "detector-only row cannot mint a GT source unit"),
    ("containing_leg", "containing leg artifact"),
    ("arm", "search arm outside declared scope"),
    ("gallery_sha256", "gallery SHA"),
    ("psu_id", "image/PSU/fold"),
    ("fold", "image/PSU/fold"),
    ("fold_role", "fold role/sampling arm"),
    ("sampling_arm", "fold role/sampling arm"),
    ("image_id", "image/PSU/fold"),
    ("cell", "cell contradicts"),
    ("duplicate_json", "duplicate JSON key"),
    ("nonfinite", "non-finite"),
])
def test_attribution_search_corruptions_refuse(candidate, mutation, reason):
    declared = read(candidate / "manifest.json")["firbench"]["leg_keys"]
    key = next(k for k in declared if k.startswith("sface__gt_crop_redetect__"))
    path = candidate / "legs" / key / "searches.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    if mutation == "missing_file":
        path.unlink()
    else:
        if mutation == "empty":
            rows = []
        elif mutation == "missing":
            rows.pop()
        elif mutation == "duplicate":
            rows.append(dict(rows[0]))
        elif mutation == "extra":
            rows.append(dict(rows[0], face_id="foreign-gt"))
        elif mutation == "foreign":
            rows[0]["face_id"] = "foreign-face"
            rows[0].update(identity_id=None, identity_status="unknown", unit_id=None)
        elif mutation == "containing_leg":
            rows[0]["leg_key"] = key.replace("gt_crop_redetect", "native")
        else:
            values = {
                "arm": "native", "gallery_sha256": "0" * 64, "psu_id": "foreign",
                "fold": 99, "fold_role": "test" if rows[0]["fold_role"] == "fit" else "fit",
                "sampling_arm": "challenge", "image_id": "foreign",
                "cell": ["foreign", "foreign"],
            }
            if mutation in values:
                rows[0][mutation] = values[mutation]
        raw = "".join(json.dumps(row) + "\n" for row in rows)
        if mutation == "duplicate_json":
            raw = raw.replace('"arm": "gt_crop_redetect"', '"arm": "native", "arm": "gt_crop_redetect"', 1)
        elif mutation == "nonfinite":
            raw = raw.replace('"top_k": [', '"top_k": [["foreign", NaN], ', 1)
        path.write_text(raw)
    with pytest.raises(fc.FrameContractError, match=reason):
        render(candidate)
    assert not (candidate / "report").exists()


@pytest.mark.parametrize("mutation,reason", [
    ("missing", "inventory.*declared scope"),
    ("missing_fit", "inventory.*declared scope"),
    ("duplicate", "duplicate/foreign declared GT key"),
    ("foreign", "duplicate/foreign declared GT key"),
    ("arm", "duplicate/foreign declared GT key"),
    ("fold", "duplicate/foreign declared GT key"),
    ("image_id", "image_id contradicts"),
    ("psu_id", "psu_id contradicts"),
    ("sampling_arm", "sampling_arm contradicts"),
    ("arm_availability", "arm_availability contradicts"),
    ("mated", "mated contradicts"),
    ("fit_scored", "fit fold must remain metadata"),
    ("fused_scored", "unavailable evidence cannot carry"),
])
def test_all_arm_outcome_corruptions_refuse(candidate, mutation, reason):
    path = candidate / "scores.json"
    scores = read(path)
    outcomes = scores["face_outcomes"]
    row = next(r for r in outcomes if r["arm"] == "gt_crop_redetect" and r["fold_role"] == "test")
    if mutation == "missing":
        outcomes.remove(row)
    elif mutation == "missing_fit":
        outcomes.remove(next(r for r in outcomes if r["arm"] != "native" and r["fold_role"] == "fit"))
    elif mutation == "duplicate":
        outcomes.append(dict(row))
    elif mutation in {"fit_scored", "fused_scored"}:
        row = next(r for r in outcomes if (
            r["fold_role"] == "fit" if mutation == "fit_scored"
            else r["fold_role"] == "test" and r["arm_availability"] == "unavailable_fused"
        ))
        row.update(outcome="correct", outcome_available=True, outcome_reason=None)
    else:
        values = {
            "foreign": ("face_id", "foreign"), "arm": ("arm", "native"), "fold": ("fold", 99),
            "image_id": ("image_id", "foreign"), "psu_id": ("psu_id", "foreign"),
            "sampling_arm": ("sampling_arm", "challenge"),
            "arm_availability": ("arm_availability", "unavailable"), "mated": ("mated", not row["mated"]),
        }
        field, value = values[mutation]
        row[field] = value
    write(path, scores)
    with pytest.raises(fc.FrameContractError, match=reason):
        render(candidate)
    assert not (candidate / "report").exists()


def test_legacy_absence_keeps_all_typed_arm_metadata(candidate):
    path = candidate / "scores.json"
    scores = read(path)
    scores.pop("face_outcomes")
    write(path, scores)
    key = next(k for k in read(candidate / "manifest.json")["firbench"]["leg_keys"] if "__gt_crop_redetect__" in k)
    (candidate / "legs" / key / "searches.jsonl").unlink()
    render(candidate)
    rows = read(candidate / "report/report.json")["failures"]["rows"]
    assert len(rows) == 270
    assert all(r["outcome"] is None and not r["outcome_available"] and not r["default_visible"] for r in rows)
    assert {r["outcome_reason"] for r in rows} == {"legacy_face_outcomes_unavailable"}
    assert all(r["stage"] is None for r in rows if r["leg_key"] == key)


@pytest.mark.parametrize("mutation,reason", [
    ("scores_missing", "declared native leg scope"),
    ("scores_extra_arm", "declared native leg scope"),
    ("scores_duplicate", "duplicate or missing"),
    ("scores_context", "declared native leg scope"),
    ("declared_duplicate", "duplicate or missing"),
    ("declared_missing_arm", "leg/arm inventory scope"),
    ("declared_missing_native", "declared native leg scope"),
    ("declared_missing", "actual declared leg scope"),
    ("declared_wrong_arms", "leg/arm inventory scope"),
    ("declared_context", "space or runtime context"),
    ("gallery_missing", "cover every declared leg/fold"),
    ("gallery_duplicate", "duplicate/foreign leg/fold"),
    ("gallery_foreign", "duplicate/foreign leg/fold"),
    ("gallery_hash", "gallery SHA"),
    ("gallery_folds", "fold provenance contradicts FRAME"),
    ("foreign_artifact", "artifact outside declared leg scope"),
    ("fused_status", "unavailable fused arm status"),
])
def test_native_summary_and_declared_context_refusals(candidate, mutation, reason):
    score_path, manifest_path = candidate / "scores.json", candidate / "manifest.json"
    scores, manifest = read(score_path), read(manifest_path)
    block = manifest["firbench"]
    attr = next(k for k in block["leg_keys"] if k.startswith("sface__gt_crop_redetect__"))
    native_key = attr.replace("gt_crop_redetect", "native")
    if mutation == "scores_missing":
        scores["legs"].pop()
    elif mutation == "scores_extra_arm":
        scores["legs"].append(dict(scores["legs"][0], leg_key=attr))
    elif mutation == "scores_duplicate":
        scores["legs"].append(dict(scores["legs"][0]))
    elif mutation == "scores_context":
        scores["legs"][0]["leg_key"] += "-foreign"
    elif mutation == "declared_duplicate":
        block["leg_keys"].append(attr)
    elif mutation == "declared_missing_arm":
        block["leg_keys"].remove(attr)
    elif mutation == "declared_missing_native":
        block["leg_keys"].remove(native_key)
    elif mutation == "declared_missing":
        del block["leg_keys"]
    elif mutation == "declared_wrong_arms":
        block["arms"].remove("gt_crop_redetect")
    elif mutation == "declared_context":
        block["leg_keys"][block["leg_keys"].index(attr)] += "-foreign"
    elif mutation.startswith("gallery_"):
        registry = block["gallery_membership"]
        row = next(r for r in registry if r["leg_key"] == attr)
        if mutation == "gallery_missing":
            registry.remove(row)
        elif mutation == "gallery_duplicate":
            registry.append(dict(row))
        elif mutation == "gallery_foreign":
            row["leg_key"] = "foreign"
        elif mutation == "gallery_hash":
            row["gallery_sha256"] = "0" * 64
        else:
            identity = next(iter(row["identity_folds"]))
            row["identity_folds"][identity] = (row["identity_folds"][identity] + 1) % 5
    elif mutation == "foreign_artifact":
        destination = candidate / "legs/foreign/searches.jsonl"
        destination.parent.mkdir()
        shutil.copyfile(candidate / "legs" / attr / "searches.jsonl", destination)
    elif mutation == "fused_status":
        key = next(k for k in block["leg_keys"] if k.startswith("insightface__gt_crop_redetect__"))
        path = candidate / "legs" / key / "searches.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        rows[0].update(arm_availability="available", stage_reached="embedded")
        path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    write(score_path, scores)
    write(manifest_path, manifest)
    with pytest.raises(fc.FrameContractError, match=reason):
        render(candidate)
    assert not (candidate / "report").exists()
