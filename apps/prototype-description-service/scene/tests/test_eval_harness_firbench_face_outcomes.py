"""Actual persisted S3/CLI joins; only synthetic inventory and model assets."""

import hashlib
import json
from collections import Counter
from dataclasses import replace

import numpy as np
import pytest

from scene.tests.test_eval_harness_firbench_cli_integration import (
    runtime_files,  # noqa: F401
)
from scene.tests.test_eval_harness_firbench_cli_integration import (
    test_default_run_and_actual_score as assert_default_run_and_actual_score,
)
from scene.tests.test_eval_harness_firbench_score_io import fake_run  # noqa: F401
from scripts.eval_harness import firbench_contract as fc
from scripts.eval_harness import firbench_frames as frames
from scripts.eval_harness import firbench_legs as legs
from scripts.eval_harness import firbench_score as core
from scripts.eval_harness import firbench_score_io as io
from scripts.eval_harness.firbench_legs import write_searches_jsonl

FIELDS = {
    "face_id",
    "image_id",
    "psu_id",
    "fold",
    "fold_role",
    "sampling_arm",
    "leg_key",
    "arm",
    "arm_availability",
    "stage_reached",
    "identity_status",
    "mated",
    "cell",
    "outcome",
    "outcome_available",
    "outcome_reason",
}


def assert_join(score, frame, manifest, records, decision):
    rows = score["face_outcomes"]
    assert [(r["leg_key"], r["face_id"]) for r in rows] == sorted(
        (key, face.face_id) for key in manifest["firbench"]["leg_keys"] for face in frame.faces
    )
    gt = {f.face_id: f for f in frame.faces}
    images = {i.image_id: i for i in frame.images}
    registry = {(r["leg_key"], r["fold"]): r for r in manifest["firbench"]["gallery_membership"]}
    searches = {(r.leg_key, r.face_id): r for group in records.values() for r in group}
    taus = {r["leg_key"]: None if r["tau"]["data"] is None else r["tau"]["data"]["value"] for r in score["legs"]}
    for row in rows:
        assert set(row) == FIELDS
        face = gt[row["face_id"]]
        record = searches[row["leg_key"], row["face_id"]]
        assert row["image_id"] == face.image_id == record.image_id
        assert row["psu_id"] == frame.psu_map[face.image_id] == record.psu_id
        assert type(row["fold"]) is int and row["fold"] == frame.folds[record.psu_id] >= 0
        assert row["fold_role"] == frame.fold_roles[row["fold"]].value
        assert row["sampling_arm"] == images[face.image_id].sampling_arm.value
        assert row["identity_status"] == face.identity_status.value
        assert row["mated"] == (
            None
            if face.identity_status is fc.IdentityStatus.unresolved
            else face.identity_id in registry[row["leg_key"], row["fold"]]["enrolled_identity_ids"]
        )
        assert row["arm"] == record.arm.value
        assert row["arm_availability"] == record.arm_availability.value
        assert row["stage_reached"] == (None if record.stage_reached is None else record.stage_reached.value)
        assert row["cell"] == list(record.cell)
        parts = row["leg_key"].split("__")
        parts[1] = "native"
        tau = taus.get("__".join(parts))
        if record.fold_role is fc.FoldRole.fit:
            reason = "fit_fold_not_scored"
        elif record.arm_availability is not fc.ArmStatus.available:
            reason = "arm_unavailable"
        elif face.identity_status is fc.IdentityStatus.unresolved:
            reason = "unresolved_identity"
        elif tau is None:
            reason = "calibration_unavailable"
        else:
            reason = None
        expected = None if reason else core._outcome(record, tau, decision.boundary_semantics)
        assert row["outcome"] == (None if expected is None else expected.value)
        assert row["outcome_available"] is (expected is not None)
        assert row["outcome_reason"] == reason
    fc.validate_interchange("scores-v1", score)
    legacy = dict(score)
    del legacy["face_outcomes"]
    fc.validate_interchange("scores-v1", legacy)


def test_native_join_replay_preserves_statistics_and_receipt(fake_run):
    path, decision, manifest, frame, records = fake_run
    receipt = (path / "timings.json").read_bytes()
    score = io.score_run(path, decision=decision)
    legacy = {k: v for k, v in score.items() if k != "face_outcomes"}
    digest = hashlib.sha256(json.dumps(legacy, sort_keys=True).encode()).hexdigest()
    # Pinned before the producer join, using the actual 10,000-draw S3 scorer.
    assert digest == "c1cff5b881324b7df73521b286515eb9956c032c449770e996a2f91eecda3947"
    assert decision.interval.n_boot == 10000
    assert_join(score, frame, manifest, records, decision)
    assert score == io.score_run(path, decision=decision)
    assert (path / "timings.json").read_bytes() == receipt
    assert score["n_units"] == frame.n_units
    assert all(not r["face_id"].startswith("det-") for r in score["face_outcomes"])


@pytest.fixture
def mixed_run(fake_run):
    path, decision, manifest, old_frame, old_records = fake_run
    images = [
        replace(im, sampling_arm=fc.SamplingArm.challenge, inclusion_probability=None) if i % 19 == 0 else im
        for i, im in enumerate(old_frame.images)
    ]
    faces = [
        replace(f, identity_id=None, identity_status=fc.IdentityStatus.unknown) if i % 11 == 0 else f
        for i, f in enumerate(old_frame.faces)
    ]
    components = frames.build_psu_components(images, faces)
    identities = frames.identity_to_component(faces, components)
    folds = frames.identity_disjoint_folds(components, identities, k=5, seed=decision.fold_protocol.seed)
    id_folds = {identity: folds[psu] for identity, psu in identities.items()}
    enrolled = {
        fold: sorted(identity for i, (identity, f) in enumerate(sorted(id_folds.items())) if f == fold and i % 13)
        for fold in range(5)
    }
    frame = frames.build_frame(
        spec=old_frame.spec,
        images=images,
        faces=faces,
        planning_icc=decision.planning_icc,
        k=5,
        seed=decision.fold_protocol.seed,
        test_fold=decision.fold_protocol.seed % 5,
        gallery_sha256_by_fold=old_frame.gallery_sha256_by_fold,
        enrolled_identity_ids=frozenset(enrolled[decision.fold_protocol.seed % 5]),
    )
    (path / "frame.json").write_text(frames.frame_json(frame))
    native_keys = list(manifest["firbench"]["leg_keys"])
    keys = [key.replace("__native__", f"__{arm.value}__") for key in native_keys for arm in fc.Arm]
    manifest["firbench"]["leg_keys"] = keys
    registry = [
        {
            "leg_key": key,
            "fold": fold,
            "gallery_sha256": "b" * 64,
            "enrolled_identity_ids": enrolled[fold],
            "identity_folds": id_folds,
            "enrolled_occluders": {identity: [] for identity in enrolled[fold]},
        }
        for key in keys
        for fold in range(5)
    ]
    manifest["firbench"]["gallery_membership"] = registry
    (path / "manifest.json").write_text(json.dumps(manifest))
    image_map = {im.image_id: im for im in images}
    face_map = {f.face_id: f for f in faces}
    records, timings = {}, {}
    stages = (
        fc.SearchStage.embedded,
        fc.SearchStage.embedded,
        fc.SearchStage.embedded,
        fc.SearchStage.missed,
        fc.SearchStage.unaligned,
        fc.SearchStage.detected,
    )
    for key in keys:
        arm = fc.Arm(key.split("__")[1])
        native_key = key.replace(f"__{arm.value}__", "__native__")
        rows = []
        for index, old in enumerate(old_records[native_key]):
            image = image_map[old.image_id]
            face = face_map.get(old.face_id)
            fold = frame.folds[frame.psu_map[image.image_id]]
            mated = face is not None and face.identity_id in enrolled[fold]
            identity = face.identity_id if mated else None
            stage = stages[(index // 2) % len(stages)] if face else fc.SearchStage.embedded
            available = not (arm is not fc.Arm.native and (index // 2) % 7 == 0)
            status = (
                fc.ArmStatus.available
                if available
                else (fc.ArmStatus.unavailable_fused if key.startswith("insightface") else fc.ArmStatus.unavailable)
            )
            top_k = ()
            if stage is fc.SearchStage.embedded and available:
                name = identity if mated and index // 2 % 6 == 0 else next(i for i in enrolled[fold] if i != identity)
                value = (
                    (0.2, 0.4, 0.6)[native_keys.index(native_key)]
                    if face is None
                    else (0.0 if index // 2 % 3 == 2 else 0.95)
                )
                top_k = ((name, value),)
            ref = f"{key}/{arm.value}/{old.face_id}"
            rows.append(
                replace(
                    old,
                    psu_id=frame.psu_map[image.image_id],
                    fold=fold,
                    fold_role=frame.fold_roles[fold],
                    sampling_arm=image.sampling_arm,
                    inclusion_probability=image.inclusion_probability,
                    leg_key=key,
                    arm=arm,
                    arm_availability=status,
                    stage_reached=stage
                    if available
                    else (None if status is fc.ArmStatus.unavailable_fused else fc.SearchStage.unavailable),
                    identity_id=identity,
                    identity_status=face.identity_status if face else fc.IdentityStatus.unknown,
                    unit_id=None if mated else (face.face_id if face else f"background:{image.image_id}"),
                    cell=("clear", "clear" if mated else "unknown") if face else ("unknown", "unknown"),
                    top_k=top_k,
                    timing_receipt_ref=ref,
                )
            )
            timings[ref] = 2.0
        # A duplicate alarm over represented GT has no independent source unit.
        duplicate = next(r for r in rows if r.unit_id is None and r.stage_reached is fc.SearchStage.embedded)
        duplicate_id = "duplicate-" + duplicate.face_id
        ref = f"{key}/{arm.value}/{duplicate_id}"
        rows.append(
            replace(
                duplicate,
                face_id=duplicate_id,
                identity_id=None,
                identity_status=fc.IdentityStatus.unknown,
                unit_id=None,
                cell=("unknown", "unknown"),
                timing_receipt_ref=ref,
            )
        )
        timings[ref] = 0.0
        target = path / "legs" / key / "searches.jsonl"
        target.parent.mkdir(parents=True, exist_ok=True)
        write_searches_jsonl(target, rows)
        records[key] = rows
    (path / "timings.json").write_text(json.dumps({"timing_receipt_ms": timings}, sort_keys=True))
    return path, decision, manifest, frame, records


def test_all_folds_arms_and_sampling_scopes_use_native_outcomes(mixed_run):
    path, decision, manifest, frame, records = mixed_run
    score = io.score_run(path, decision=decision)
    assert_join(score, frame, manifest, records, decision)
    rows = score["face_outcomes"]
    assert {r["outcome"] for r in rows if r["outcome_available"]} == {o.value for o in fc.FaceOutcome}
    assert {r["arm"] for r in rows} == {a.value for a in fc.Arm}
    assert {r["fold"] for r in rows} == set(range(5))
    assert {r["sampling_arm"] for r in rows} == {a.value for a in fc.SamplingArm}
    assert {r["arm_availability"] for r in rows} == {a.value for a in fc.ArmStatus}
    assert len({leg["tau"]["data"]["value"] for leg in score["legs"]}) == 3
    assert any(r["identity_status"] == "named" and r["mated"] is False for r in rows)
    assert any(r["sampling_arm"] == "challenge" and r["outcome_available"] for r in rows)
    for key in manifest["firbench"]["leg_keys"]:
        raw = (path / "legs" / key / "searches.jsonl").read_text()
        assert "duplicate-" in raw and "det-" in raw
    assert not any(r["face_id"].startswith(("duplicate-", "det-")) for r in rows)
    for leg in score["legs"]:
        selected = [
            r
            for r in rows
            if r["leg_key"] == leg["leg_key"]
            and r["fold_role"] == "test"
            and r["sampling_arm"] == "probability"
            and r["mated"]
            and r["outcome_available"]
        ]
        fnir = leg["operating_point"]["fnir"]["data"]
        assert fnir["n_mated"] == len(selected)
        assert fnir["misses"] == sum(r["outcome"] != "correct" for r in selected)


def test_missing_calibration_writes_named_nulls_without_imputation(fake_run):
    path, decision, manifest, frame, records = fake_run
    # No fit nonmated searches embedded: actual calibration has no feasible tau.
    for key, rows in records.items():
        records[key] = [
            replace(r, stage_reached=fc.SearchStage.missed, top_k=())
            if r.fold_role is fc.FoldRole.fit and r.unit_id is not None
            else r
            for r in rows
        ]
        write_searches_jsonl(path / "legs" / key / "searches.jsonl", records[key])
    score = io.score_run(path, decision=decision)
    assert_join(score, frame, manifest, records, decision)
    assert all(r["outcome"] is None and not r["outcome_available"] for r in score["face_outcomes"])
    assert {r["outcome_reason"] for r in score["face_outcomes"]} == {"fit_fold_not_scored", "calibration_unavailable"}
    assert all(leg["tau"]["data"] is None for leg in score["legs"])


def unresolved_run(fake_run, *, emission="accepted", known_false=True, boundary=fc.BoundarySemantics.v2):
    """Rebuild S1 metadata; S2 produces real unresolved ledgers from fake kernels.

    Add faces to existing images, retaining the named identity graph. S1's pool
    accepts resolved faces only; its full-inventory PSU/fold checks run separately.
    No status-only edits to a persisted frame or score/metric/schema replacements.
    """
    path, decision, manifest, old, records = fake_run
    guard = fc.Guardrail(
        "names", "false_names_per_1k_mentions", "<= 2 names/1000_mentions", "all", fc.GuardrailRole.veto
    )
    decision = fc.seal(
        replace(decision, seal=None, guardrails=(guard,), boundary_semantics=boundary),
        sealed_at="2026-01-01T00:00:00Z",
    )
    test = decision.fold_protocol.seed % 5
    selected = {fold: next(im for im in old.images if old.folds[old.psu_map[im.image_id]] == fold) for fold in range(5)}
    extra = [
        frames.GtFace(
            f"unresolved-{fold}",
            im.image_id,
            (20.0, 0.0, 10.0, 10.0),
            fc.IdentityStatus.unresolved,
            None,
            annotation=frames.FaceAnnotation(occluders=()),
        )
        for fold, im in selected.items()
    ]
    if known_false:
        extra.append(
            frames.GtFace(
                "known-nonmate",
                selected[test].image_id,
                (40.0, 0.0, 10.0, 10.0),
                fc.IdentityStatus.unknown,
                None,
                annotation=frames.FaceAnnotation(occluders=()),
            )
        )
    faces = tuple(sorted((*old.faces, *extra), key=lambda f: f.face_id))
    psus = frames.build_psu_components(old.images, faces)
    identities = frames.identity_to_component(faces, psus)
    folds = frames.identity_disjoint_folds(psus, identities, k=5, seed=decision.fold_protocol.seed)
    resolved = tuple(f for f in faces if f.identity_status is not fc.IdentityStatus.unresolved)
    rebuilt = frames.build_frame(
        spec=old.spec,
        images=old.images,
        faces=resolved,
        planning_icc=decision.planning_icc,
        k=5,
        seed=decision.fold_protocol.seed,
        test_fold=test,
        gallery_sha256_by_fold=old.gallery_sha256_by_fold,
        enrolled_identity_ids=frozenset(identities),
    )
    assert rebuilt.psu_map == psus and rebuilt.folds == folds
    sizes = Counter(psus[f.image_id] for f in faces)
    deff = frames.design_effect(list(sizes.values()), decision.planning_icc)
    frame = replace(rebuilt, faces=faces, design_effect=deff, n_eff=frames.effective_n(len(faces), deff))
    (path / "frame.json").write_text(frames.frame_json(frame))
    manifest["firbench"]["decision_sha256"] = fc.manifest_sha256(decision)
    manifest["firbench"]["external_mention_denominators"] = dict.fromkeys(records, 1000)
    (path / "manifest.json").write_text(json.dumps(manifest))
    receipt = json.loads((path / "timings.json").read_text())["timing_receipt_ms"]

    class Kernel:
        alignment_mode = fc.AlignmentMode.separable

        def __init__(self, key, image_faces):
            self.key, self.image_faces = key, image_faces

        def leg_id(self, arm):
            return fc.LegId(fc.LegKind(self.key.split("__")[0]), arm, "fake", "4", "1")

        def observe(self, pixels):
            output = []
            for face in self.image_faces:
                mode = emission if face.identity_status is fc.IdentityStatus.unresolved else "accepted"
                if mode == "fit_only":
                    mode = "missed" if frame.folds[frame.psu_map[face.image_id]] == test else "accepted"
                if mode == "missed":
                    continue
                score = {"accepted": 1.0, "rejected": 0.0, "boundary": 0.2}[mode]
                det = legs.DetectedFace(face.box, np.zeros((5, 2)), 1.0)
                output.append(legs.Observation.embedded(det, np.array([score, np.sqrt(1 - score**2)])))
            return tuple(output)

    for key, rows in records.items():
        for fold, im in selected.items():
            declaration = next(
                r for r in manifest["firbench"]["gallery_membership"] if r["leg_key"] == key and r["fold"] == fold
            )
            gallery = legs.Gallery(
                {identity: np.array([1.0, 0.0]) for identity in declaration["enrolled_identity_ids"]}, "b" * 64
            )
            image_faces = [f for f in extra if f.image_id == im.image_id]
            result = legs.search_leg_arm(
                leg=Kernel(key, image_faces),
                arm=fc.Arm.native,
                images={im.image_id: np.zeros((64, 64, 3), dtype=np.uint8)},
                image_units={im.image_id: im},
                faces=image_faces,
                gallery=gallery,
                psu_by_image=psus,
                fold_by_psu=folds,
                fold_roles=frame.fold_roles,
                exhaustive=True,
                top_k=1,
                cells={f.face_id: ("clear", "unknown") for f in image_faces},
            )
            rows.extend(result.records)
            receipt.update(result.timings_ms)
        # Retain an actual known-mate miss alongside the unjudgeable GT faces.
        mate = next(r for r in rows if r.fold == test and core._is_mated(r))
        records[key] = [
            replace(r, stage_reached=fc.SearchStage.missed, top_k=()) if r.face_id == mate.face_id else r for r in rows
        ]
        write_searches_jsonl(path / "legs" / key / "searches.jsonl", records[key])
    (path / "timings.json").write_text(json.dumps({"timing_receipt_ms": receipt}, sort_keys=True))
    return path, decision, manifest, frame, records


@pytest.mark.parametrize("emission", ["accepted", "rejected", "missed"])
def test_unresolved_core_excludes_names_without_changing_fixed_estimands(fake_run, emission):
    _, decision, _, frame, records = unresolved_run(fake_run, emission=emission)
    test = decision.fold_protocol.seed % 5
    units = frames.build_nonmated_pool(
        [f for f in frame.faces if f.identity_status is not fc.IdentityStatus.unresolved],
        frame.images,
        frame.folds,
        fold=test,
        component_map=frame.psu_map,
        exhaustive=True,
        planning_icc=decision.planning_icc,
        enrolled_identity_ids=frozenset(frame.identity_fold),
    ).units
    for rows in records.values():
        rows = [r for r in rows if r.fold == test]
        known = [r for r in rows if r.identity_status is not fc.IdentityStatus.unresolved]
        kwargs = {"units": units, "thresholds": [0.0, 0.2, 0.5, 1.0], "boundary": decision.boundary_semantics}
        points = core.curve(rows, **kwargs)
        assert points == core.curve(known, **kwargs)
        assert points[2].fpi == 1 and points[2].n_units == frame.n_units
        assert points[2].fnir_misses == 1 and points[2].spurious_names == 0
        unresolved = [r for r in rows if r.identity_status is fc.IdentityStatus.unresolved]
        assert all(
            r.identity_id is None and r.unit_id is None and core._outcome(r, 0.5, decision.boundary_semantics) is None
            for r in unresolved
        )


@pytest.mark.parametrize(
    "emission,known_false",
    [("accepted", True), ("rejected", True), ("missed", True), ("missed", False), ("fit_only", True)],
)
def test_unresolved_public_score_retains_gt_and_truthful_false_name_scope(fake_run, emission, known_false):
    path, decision, manifest, frame, records = unresolved_run(fake_run, emission=emission, known_false=known_false)
    score = io.score_run(path, decision=decision)
    assert_join(score, frame, manifest, records, decision)
    assert decision.interval.n_boot == 10000
    unresolved = [r for r in score["face_outcomes"] if r["identity_status"] == "unresolved"]
    assert len(unresolved) == 15 and {r["fold"] for r in unresolved} == set(range(5))
    assert all(r["mated"] is None and r["outcome"] is None and not r["outcome_available"] for r in unresolved)
    assert {r["outcome_reason"] for r in unresolved} == {"fit_fold_not_scored", "unresolved_identity"}
    assert {r["stage_reached"] for r in unresolved} == (
        {"embedded", "missed"} if emission == "fit_only" else {"missed" if emission == "missed" else "embedded"}
    )
    guard = score["guardrails"][0]
    if emission == "accepted":
        assert guard["state"] == "unscored" and guard["value"] is None
        assert guard["evidence"]["reason"] == "unresolved_identity"
        assert score["verdict"] == {"state": "inconclusive", "reason": "required_guardrail_unscored"}
        assert score["decision_path"] == ["eligibility:required_guardrail_unscored"]
    else:
        assert guard["state"] == "pass" and guard["value"] == int(known_false)
        assert guard["evidence"]["reason"] is None
    for leg in score["legs"]:
        assert leg["tau"]["data"]["value"] == np.nextafter(0.2, np.inf)
        assert leg["operating_point"]["fnir"]["data"]["n_mated"] == sum(
            r.fold_role is fc.FoldRole.test and core._is_mated(r) for r in records[leg["leg_key"]]
        )
        assert leg["operating_point"]["fnir"]["data"]["misses"] == 1
        assert leg["operating_point"]["fpir"]["data"]["fpi"] == int(known_false)
        assert leg["operating_point"]["fpir"]["data"]["n_units"] == frame.n_units


def test_unresolved_legacy_boundary_cannot_assume_nonmated_acceptance(fake_run):
    path, decision, _, _, _ = unresolved_run(fake_run, emission="boundary", boundary=fc.BoundarySemantics.legacy_v1)
    score = io.score_run(path, decision=decision)
    assert all(leg["tau"]["data"]["value"] == 0.2 for leg in score["legs"])
    assert score["guardrails"][0]["state"] == "unscored"
    assert score["guardrails"][0]["value"] is None
    assert score["guardrails"][0]["evidence"]["reason"] == "unresolved_identity"


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("identity", "carries no identity_id"),
        ("identity_fold", "identity fold provenance"),
        ("psu", "PSU partition"),
        ("fold", "folds differ"),
        ("unit", "GT identity/unit"),
        ("record_status", "GT identity/unit"),
        ("record_psu", "PSU/fold binding"),
        ("record_fold", "PSU/fold binding"),
        ("annotation", r"annotation\.exhaustive"),
        ("exhaustive", "exhaustive GT"),
    ],
)
def test_unresolved_inventory_keeps_provenance_refusals(fake_run, mutation, reason):
    path, decision, manifest, frame, records = unresolved_run(fake_run)
    payload = frame.to_payload()
    if mutation == "identity":
        next(f for f in payload["faces"] if f["identity_status"] == "unresolved")["identity_id"] = "invented"
    elif mutation == "identity_fold":
        payload["identity_folds"].pop()
    elif mutation == "psu":
        payload["psu_map"][0]["psu_id"] = "invented"
    elif mutation == "fold":
        payload["folds"][0]["fold"] = (payload["folds"][0]["fold"] + 1) % 5
    elif mutation == "annotation":
        next(f for f in payload["faces"] if f["identity_status"] == "unresolved")["annotation"]["exhaustive"] = True
    elif mutation == "exhaustive":
        decision = fc.seal(
            replace(decision, seal=None, frames=(replace(frame.spec, exhaustive=False),)),
            sealed_at="2026-01-01T00:00:00Z",
        )
        payload["exhaustive"] = False
        manifest["firbench"]["decision_sha256"] = fc.manifest_sha256(decision)
        (path / "manifest.json").write_text(json.dumps(manifest))
    else:
        key = next(iter(records))
        rows = [r.to_dict() for r in records[key]]
        row = next(r for r in rows if r["identity_status"] == "unresolved")
        row.update(
            {
                "unit": {"unit_id": row["face_id"]},
                "record_status": {"identity_status": "unknown"},
                "record_psu": {"psu_id": "invented"},
                "record_fold": {"fold": (row["fold"] + 1) % 5},
            }[mutation]
        )
        (path / "legs" / key / "searches.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (path / "frame.json").write_text(json.dumps(payload))
    with pytest.raises(fc.FrameContractError, match=reason):
        io.score_run(path, decision=decision)


def test_default_run_and_actual_score(runtime_files):  # noqa: F811
    # Reuse the actual CLI's kernel/assets-only fixture and pinned-receipt replay.
    assert_default_run_and_actual_score(runtime_files)
    path = runtime_files.private / "run"
    score = json.loads((path / "scores.json").read_text())
    manifest = json.loads((path / "manifest.json").read_text())["firbench"]
    frame = json.loads((path / "frame.json").read_text())
    rows = score["face_outcomes"]
    assert len(rows) == len(frame["faces"]) * len(manifest["leg_keys"]) == 270
    assert all(set(r) == FIELDS for r in rows)
    assert any(r["arm_availability"] == "unavailable_fused" and not r["outcome_available"] for r in rows)
    assert all(r["outcome"] is None for r in rows if r["fold_role"] == "fit")
