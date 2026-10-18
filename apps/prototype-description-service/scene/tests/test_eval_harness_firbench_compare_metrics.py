"""Persisted synthetic evidence through actual S1 inventory, S3 IO and paired inference.

No pools, calibrators, outcomes, bootstrap or interchange validators are replaced.
The sibling compatibility patch is intentionally a separate integration dependency.
"""

import json
import shutil
from collections import Counter
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest

from scene.tests.test_eval_harness_firbench_score_io import fake_run  # noqa: F401
from scripts.eval_harness import firbench_cli as cli
from scripts.eval_harness import firbench_contract as fc
from scripts.eval_harness import firbench_frames as frames
from scripts.eval_harness import firbench_score_io as io


def _identity(path, decision):
    firbench = io._json(path / "manifest.json")["firbench"]
    registry, enrolled = io._registry(firbench, decision)
    frame = io._json(path / "frame.json")
    inventory = io._inventory(frame, decision, enrolled)
    records = io._records(path, firbench, inventory, registry)
    scores = io.score_run(path, decision=decision)
    return {
        "run_id": path.name,
        "run_dir": path,
        "decision": decision,
        "frame_payload": frame,
        "firbench": firbench,
        "inventory": inventory,
        "records": records,
        "scores": scores,
        "legs": {"__".join(k.split("__")[:2]): k for k in firbench["leg_keys"]},
    }


@pytest.fixture
def runs(fake_run, tmp_path):
    source, decision, *_ = fake_run
    paths = []
    for name in ("run-a", "run-b"):
        path = tmp_path / "pair" / name
        path.mkdir(parents=True)
        for file in ("frame.json", "manifest.json", "timings.json"):
            shutil.copyfile(source / file, path / file)
        shutil.copytree(source / "legs", path / "legs")
        paths.append(path)
    return paths, decision


def _metrics(first, second, *, arm_a=fc.Arm.native, arm_b=fc.Arm.native):
    return cli._comparison_metrics(first, second, analysis_arm_a=arm_a, analysis_arm_b=arm_b)


def test_identical_real_producer_cohorts_have_exact_zero_intervals(runs):
    paths, decision = runs
    for path in paths:
        for key in io._json(path / "manifest.json")["firbench"]["leg_keys"]:

            def mutate(rows):
                for row in rows:
                    if row["unit_id"] is not None and row["fold_role"] == "fit":
                        row["top_k"] = [[row["top_k"][0][0], 0.1 + row["fold"] * 0.05]]

            _rewrite(path, key, mutate)
    first, second = (_identity(p, decision) for p in paths)
    assert all(leg["tau"]["data"]["calibration_spread"] > 0 for leg in first["scores"]["legs"])
    result = _metrics(first, second)
    assert decision.interval.n_boot == 10000
    assert len(result["paired_deltas"]) == 3
    for row in result["paired_deltas"]:
        assert row["status"] == "scored" and row["reason"] is None
        assert row["n_searches"] == row["n_psu"] == 80
        assert row["n_eff"] == 80.0
        assert (row["point"], row["lower"], row["upper"]) == (0.0, 0.0, 0.0)
    assert result["delta"] == {"point": 0.0, "lower": 0.0, "upper": 0.0}
    assert len(result["history"]) == 3
    assert all([p["run_id"] for p in h["points"]] == ["run-a", "run-b"] for h in result["history"])
    assert len(result["tau_spread"]) == 6
    for row in result["tau_spread"]:
        assert row["status"] == "unavailable"
        assert row["reason"] == "pooled_fit_threshold_no_per_fold_estimates"
        assert row["values"] == []
        assert row["minimum"] is row["maximum"] is None
    assert cli._comparison_summary(first, second, result, state="comparable") == {
        "label": "paired FNIR(B) - FNIR(A); positive is worse",
        "delta": result["delta"],
        "verdicts": {"run_a": first["scores"]["verdict"]["state"], "run_b": second["scores"]["verdict"]["state"]},
    }
    # Wire assembly unit: the accepted state comes from the sibling compatibility
    # helper. This is not a substitute implementation of that compatibility gate.
    summary = cli._comparison_summary(first, second, result, state="exploratory")
    assert summary == {"label": "exploratory: multi-factor, no verdict", "delta": None, "verdicts": None}
    fixture = Path(__file__).parent / "fixtures/firbench_interchange_v1/comparison-v1.json"
    wire = json.loads(fixture.read_text())
    wire.update(result, **summary, comparison_state="exploratory", differences=["estimand", "fpir_target"])
    fc.validate_interchange("comparison-v1", wire)
    wire.update(
        cli._comparison_summary(first, second, result, state="comparable"),
        comparison_state="comparable",
        differences=[],
    )
    fc.validate_interchange("comparison-v1", wire)


def test_planted_difference_uses_b_minus_a_and_exact_fraction(runs):
    paths, decision = runs
    first = _identity(paths[0], decision)
    key = first["legs"]["sface__native"]
    path = paths[1] / "legs" / key / "searches.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    changed = 0
    changed_psus = set()
    for row in rows:
        if row["fold_role"] == "test" and row["identity_id"] is not None and changed < 7:
            row["top_k"] = []
            changed_psus.add(row["psu_id"])
            changed += 1
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    second = _identity(paths[1], decision)
    forward, reverse = _metrics(first, second), _metrics(second, first)
    row = next(r for r in forward["paired_deltas"] if r["leg_kind"] == "sface")
    back = next(r for r in reverse["paired_deltas"] if r["leg_kind"] == "sface")
    assert changed == 7
    assert row["n_searches"] == 80
    assert row["point"] == pytest.approx(float(Fraction(7, 80)), abs=1e-12, rel=0)
    assert back["point"] == -row["point"]
    assert (back["lower"], back["upper"]) == (-row["upper"], -row["lower"])
    assert row["lower"] <= row["point"] <= row["upper"]
    # Independent sufficient-statistic oracle, using all 10,000 native PSU draws.
    psus = sorted({r.psu_id for r in first["records"] if r.leg_key == key and r.fold == 0 and r.identity_id})
    misses = np.array([p in changed_psus for p in psus], dtype=int)
    draws = np.random.default_rng(decision.interval.seed).integers(0, 80, size=(10000, 80))
    lower, upper = np.quantile(misses[draws].sum(axis=1) / 80, [0.025, 0.975])
    assert row["lower"] == pytest.approx(lower, abs=1e-12, rel=0)
    assert row["upper"] == pytest.approx(upper, abs=1e-12, rel=0)
    assert forward["delta"] == {k: row[k] for k in ("point", "lower", "upper")}
    assert first["scores"]["legs"][0]["tau"] == second["scores"]["legs"][0]["tau"]


def _rewrite(path, key, mutate):
    target = path / "legs" / key / "searches.jsonl"
    rows = [json.loads(line) for line in target.read_text().splitlines()]
    mutate(rows)
    target.write_text("".join(json.dumps(r) + "\n" for r in rows))


def _resize(path, decision, n_images):
    """A smaller actual S1 population, re-partitioned with the declared protocol."""
    manifest = io._json(path / "manifest.json")
    firbench = manifest["firbench"]
    _, enrolled = io._registry(firbench, decision)
    inventory = io._inventory(io._json(path / "frame.json"), decision, enrolled)
    images = tuple(sorted(inventory.images.values(), key=lambda i: i.image_id)[:n_images])
    ids = {i.image_id for i in images}
    faces = tuple(f for f in inventory.faces.values() if f.image_id in ids)
    psus = frames.build_psu_components(images, faces)
    components = frames.identity_to_component(faces, psus)
    folds = frames.identity_disjoint_folds(psus, components, k=5, seed=decision.fold_protocol.seed)
    identity_folds = {i: folds[p] for i, p in components.items()}
    test = decision.fold_protocol.seed % 5
    pool = frames.build_nonmated_pool(
        faces,
        images,
        folds,
        fold=test,
        component_map=psus,
        exhaustive=True,
        planning_icc=decision.planning_icc,
        enrolled_identity_ids=frozenset(identity_folds),
    )
    frame = frames.Frame(
        inventory.spec,
        images,
        faces,
        psus,
        folds,
        identity_folds,
        dict.fromkeys(range(5), "b" * 64),
        {f: fc.FoldRole.test if f == test else fc.FoldRole.fit for f in range(5)},
        decision.planning_icc,
        1.0,
        float(len(faces)),
        pool.n_units,
        pool.n_nonmated_eff,
        {"probability": len(images), "challenge": 0},
    )
    (path / "frame.json").write_text(frames.frame_json(frame))
    for declaration in firbench["gallery_membership"]:
        fold = declaration["fold"]
        declaration.update(
            identity_folds=identity_folds,
            enrolled_identity_ids=sorted(i for i, f in identity_folds.items() if f == fold),
            enrolled_occluders={i: [] for i, f in identity_folds.items() if f == fold},
        )
    (path / "manifest.json").write_text(json.dumps(manifest))

    def rewrite(rows):
        rows[:] = [r for r in rows if r["image_id"] in ids]
        for row in rows:
            fold = folds[psus[row["image_id"]]]
            row.update(psu_id=psus[row["image_id"]], fold=fold, fold_role="test" if fold == test else "fit")

    for key in firbench["leg_keys"]:
        _rewrite(path, key, rewrite)


def test_under_floor_keeps_actual_counts_and_named_nulls(runs):
    paths, decision = runs
    for path in paths:
        _resize(path, decision, 200)
    first, second = (_identity(p, decision) for p in paths)
    result = _metrics(first, second)
    assert result["delta"] is None
    for row in result["paired_deltas"]:
        assert row["status"] == "not_scored"
        assert row["reason"] == "insufficient_independent_psus"
        assert (row["n_searches"], row["n_psu"], row["n_eff"]) == (40, 40, 40.0)
        assert row["point"] is row["lower"] is row["upper"] is None


@pytest.mark.parametrize(
    "change", ["missing", "duplicate", "psu", "duplicate_gt", "duplicate_psu_binding", "missing_psu_binding"]
)
def test_actual_io_refuses_corrupt_gt_and_psu_before_comparison(runs, change):
    paths, decision = runs
    manifest = io._json(paths[1] / "manifest.json")["firbench"]
    key = manifest["leg_keys"][0]
    reason = {
        "missing": "every GT face",
        "duplicate": "duplicate face/arm",
        "psu": "PSU/fold",
        "duplicate_gt": "duplicate face_id",
        "duplicate_psu_binding": "duplicate image_id",
        "missing_psu_binding": "PSU partition",
    }[change]
    if change in {"duplicate_gt", "duplicate_psu_binding", "missing_psu_binding"}:
        path = paths[1] / "frame.json"
        payload = io._json(path)
        if change == "duplicate_gt":
            payload["faces"].append(payload["faces"][0])
        elif change == "duplicate_psu_binding":
            payload["psu_map"].append(payload["psu_map"][0])
        else:
            payload["psu_map"].pop(0)
        path.write_text(json.dumps(payload))
    else:

        def mutate(rows):
            if change == "missing":
                rows.pop(0)
            elif change == "duplicate":
                rows.append(rows[0])
            else:
                rows[0]["psu_id"] = "unbound-psu"

        _rewrite(paths[1], key, mutate)
    with pytest.raises(fc.FrameContractError, match=reason):
        _identity(paths[1], decision)


def test_two_valid_different_cohorts_refuse_without_intersection(runs):
    paths, decision = runs
    _resize(paths[1], decision, 200)
    first, second = (_identity(p, decision) for p in paths)
    with pytest.raises(fc.FrameContractError, match="fixed native GT/PSU/weights cohort differs"):
        _metrics(first, second)


def test_missing_tau_stays_null_without_refitting(runs):
    paths, decision = runs
    for path in paths:
        firbench = io._json(path / "manifest.json")["firbench"]
        for key in firbench["leg_keys"]:

            def mutate(rows):
                for row in rows:
                    if row["unit_id"] is not None:
                        row["top_k"] = []

            _rewrite(path, key, mutate)
    first, second = (_identity(p, decision) for p in paths)
    result = _metrics(first, second)
    for row in result["paired_deltas"]:
        assert row["reason"] == "tau_infeasible"
        assert row["status"] == "not_scored"
        assert (row["n_searches"], row["n_psu"], row["n_eff"]) == (80, 80, 80.0)
        assert row["point"] is row["lower"] is row["upper"] is None
    for series in result["history"]:
        assert all(p["fnir"] is p["tau"] is None and p["reason"] == "tau_infeasible" for p in series["points"])


def test_unavailable_native_search_never_drops_face_or_imputes_outcome(runs):
    paths, decision = runs
    for path in paths:
        firbench = io._json(path / "manifest.json")["firbench"]
        for key in firbench["leg_keys"]:

            def mutate(rows):
                row = next(r for r in rows if r["identity_id"] is not None and r["fold_role"] == "test")
                row.update(arm_availability="unavailable", stage_reached="unavailable", top_k=[])

            _rewrite(path, key, mutate)
    first, second = (_identity(p, decision) for p in paths)
    result = _metrics(first, second)
    assert result["delta"] is None
    for row in result["paired_deltas"]:
        assert row["reason"] == "native_search_unavailable"
        assert row["status"] == "not_scored"
        assert (row["n_searches"], row["n_psu"], row["n_eff"]) == (80, 80, 80.0)
        assert row["point"] is row["lower"] is row["upper"] is None


def test_derived_comparison_replay_refuses_conflict_and_symlink(tmp_path):
    target = tmp_path / "comparison.json"
    cli._comparison_write(target, "derived\n")
    before = target.stat()
    cli._comparison_write(target, "derived\n")
    assert target.stat().st_mtime_ns == before.st_mtime_ns
    with pytest.raises(fc.FrameContractError, match="conflicting"):
        cli._comparison_write(target, "changed\n")
    assert target.read_text() == "derived\n"
    alias = tmp_path / "alias.json"
    alias.symlink_to(target)
    with pytest.raises(fc.FrameContractError, match="symlink"):
        cli._comparison_write(alias, "derived\n")


def test_clustered_mated_effective_n_and_ipw_are_not_nonmated_counts(runs):
    paths, decision = runs
    for index, path in enumerate(paths):
        manifest = io._json(path / "manifest.json")["firbench"]
        first_key = manifest["leg_keys"][0]
        rows = io._json(path / "frame.json")
        raw_search = [
            json.loads(line) for line in (path / "legs" / first_key / "searches.jsonl").read_text().splitlines()
        ]
        selected = next(r for r in raw_search if r["identity_id"] is not None and r["fold_role"] == "test")
        original = next(f for f in rows["faces"] if f["face_id"] == selected["face_id"])
        extra = dict(original, face_id="extra-mated-face")
        rows["faces"].append(extra)
        next(i for i in rows["images"] if i["image_id"] == original["image_id"])["inclusion_probability"] = 0.5
        psus = {r["image_id"]: r["psu_id"] for r in rows["psu_map"]}
        sizes = Counter(psus[f["image_id"]] for f in rows["faces"])
        deff = 1 + Fraction(1, 10) * (Fraction(sum(s * s for s in sizes.values()), 401) - 1)
        rows.update(design_effect=float(deff), n_eff=float(401 / deff))
        (path / "frame.json").write_text(json.dumps(rows))
        timings = io._json(path / "timings.json")
        for key in manifest["leg_keys"]:

            def mutate(records, original=original, extra=extra, key=key, index=index, timings=timings):
                for record in records:
                    if record["image_id"] == original["image_id"]:
                        record["inclusion_probability"] = 0.5
                source = next(r for r in records if r["face_id"] == original["face_id"])
                added = dict(source, face_id=extra["face_id"], timing_receipt_ref=f"{key}/native/{extra['face_id']}")
                if index == 1 and key.startswith("sface__"):
                    added["top_k"] = []
                timings["timing_receipt_ms"][added["timing_receipt_ref"]] = 2.0
                records.append(added)

            _rewrite(path, key, mutate)
        (path / "timings.json").write_text(json.dumps(timings))
    first, second = (_identity(p, decision) for p in paths)
    result = _metrics(first, second)
    row = next(r for r in result["paired_deltas"] if r["leg_kind"] == "sface")
    assert (row["n_searches"], row["n_psu"]) == (81, 80)
    assert row["n_eff"] == pytest.approx(float(Fraction(81 * 405, 406)), abs=1e-12, rel=0)
    assert row["point"] == pytest.approx(float(Fraction(2, 83)), abs=1e-12, rel=0)
    assert first["scores"]["n_nonmated_eff"] == 80.0
    assert first["scores"]["n_eff"] == pytest.approx(row["n_eff"], abs=1e-12, rel=0)


def _rename_space(path):
    manifest = io._json(path / "manifest.json")
    firbench = manifest["firbench"]
    remap = {k: k.replace("__fake__", "__changed-space__") for k in firbench["leg_keys"]}
    timings = io._json(path / "timings.json")
    for key, new in remap.items():

        def mutate(rows, key=key, new=new):
            for row in rows:
                old_ref = row["timing_receipt_ref"]
                row.update(leg_key=new, gallery_sha256="c" * 64, timing_receipt_ref=old_ref.replace(key, new))
                timings["timing_receipt_ms"][row["timing_receipt_ref"]] = timings["timing_receipt_ms"].pop(old_ref)

        _rewrite(path, key, mutate)
        (path / "legs" / key).rename(path / "legs" / new)
    firbench["leg_keys"] = list(remap.values())
    for row in firbench["gallery_membership"]:
        row.update(leg_key=remap[row["leg_key"]], gallery_sha256="c" * 64)
    (path / "manifest.json").write_text(json.dumps(manifest))
    (path / "timings.json").write_text(json.dumps(timings))


def test_changed_vector_space_uses_same_outcomes_and_actual_single_point_history(runs):
    paths, decision = runs
    _rename_space(paths[1])
    first, second = (_identity(p, decision) for p in paths)
    result = _metrics(first, second)
    for row in result["paired_deltas"]:
        assert row["leg_key_a"] != row["leg_key_b"]
        assert (row["point"], row["lower"], row["upper"]) == (0.0, 0.0, 0.0)
    assert len(result["history"]) == 6
    for series in result["history"]:
        assert len(series["points"]) == 1
        point = series["points"][0]
        identity = first if point["run_id"] == "run-a" else second
        score = next(leg for leg in identity["scores"]["legs"] if leg["leg_key"] == series["leg_key"])
        assert point == {
            "run_id": identity["run_id"],
            "fnir": score["operating_point"]["fnir"]["data"]["rate"],
            "tau": score["tau"]["data"]["value"],
            "reason": None,
        }
    assert all(row["values"] == [] for row in result["tau_spread"])


def _add_unavailable_attribution(path):
    manifest = io._json(path / "manifest.json")
    firbench = manifest["firbench"]
    for key in tuple(firbench["leg_keys"]):
        new = key.replace("__native__", "__gt_crop_redetect__")
        target = path / "legs" / new / "searches.jsonl"
        target.parent.mkdir()
        rows = [json.loads(line) for line in (path / "legs" / key / "searches.jsonl").read_text().splitlines()]
        for row in rows:
            row.update(leg_key=new, arm="gt_crop_redetect", timing_receipt_ref=None)
        unavailable = next(row for row in rows if row["fold_role"] == "test" and row["identity_id"] is not None)
        unavailable.update(arm_availability="unavailable", stage_reached="unavailable", top_k=[])
        target.write_text("".join(json.dumps(r) + "\n" for r in rows))
        firbench["leg_keys"].append(new)
        firbench["gallery_membership"].extend(
            dict(row, leg_key=new) for row in tuple(firbench["gallery_membership"]) if row["leg_key"] == key
        )
    (path / "manifest.json").write_text(json.dumps(manifest))


def test_explicit_attribution_availability_is_descriptive_and_never_imputed(runs):
    paths, decision = runs
    _add_unavailable_attribution(paths[1])
    first, second = (_identity(p, decision) for p in paths)
    result = _metrics(first, second, arm_b=fc.Arm.gt_crop_redetect)
    assert result["delta"] is None
    for row in result["paired_deltas"]:
        assert row["status"] == "not_scored" and row["reason"] == "gt_crop_redetect_search_unavailable"
        assert (row["n_searches"], row["n_psu"], row["n_eff"]) == (80, 80, 80.0)
        assert row["point"] is row["lower"] is row["upper"] is None
    assert len(result["history"]) == 6
    unavailable = [s["points"][0] for s in result["history"] if "__gt_crop_redetect__" in s["leg_key"]]
    assert len(unavailable) == 3
    assert all(p["fnir"] is p["tau"] is None for p in unavailable)
    gaps = [gap for gap in second["scores"]["joint_gaps"] if gap["arm"] == "gt_crop_redetect"]
    assert len(gaps) == 3
    assert all(gap["n_pairs"] == 79 and gap["unavailable_counts"] == {"native": 0, "attribution": 1} for gap in gaps)
    # Default scope remains native even when attribution legs are present.
    assert all(r["status"] == "scored" for r in _metrics(first, second)["paired_deltas"])
