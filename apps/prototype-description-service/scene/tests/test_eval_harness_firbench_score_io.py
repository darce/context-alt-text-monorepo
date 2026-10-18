"""Fake-only tests of the persisted-run scorer; no pixels or model dependencies."""

from pathlib import Path

import pytest

from scripts.eval_harness import firbench_contract as fc
from scripts.eval_harness import firbench_score_io as io


def test_occluder_composites_preserve_unknown_and_clear():
    assert io.occluder_label(None) == "unknown"
    assert io.occluder_label([]) == "clear"
    assert io.occluder_label(["mask", "glasses", "mask"]) == "glasses+mask"


def test_pair_fmr_uses_nonmated_pairs_only():
    result = io.pair_fmr(
        [
            {"is_mated": True, "score": 0.99},
            {"is_mated": False, "score": 0.8},
            {"is_mated": False, "score": 0.1},
        ],
        tau=0.5,
        boundary=fc.BoundarySemantics.v2,
    )
    assert result["data"] == {"false_matches": 1, "n_nonmated_pairs": 2, "rate": 0.5}
    assert io.pair_fmr(None, tau=0.5, boundary=fc.BoundarySemantics.v2) == {
        "status": "not_evaluated",
        "reason": "pair_scores_not_supplied",
        "data": None,
    }


def test_missing_persisted_frame_is_refused(tmp_path: Path):
    with pytest.raises(fc.FrameContractError, match="frame.json"):
        io.score_run(tmp_path, decision=None)


def test_rule_parser_refuses_unknown_forms_and_wrong_timing_units():
    assert io.parse_rule("p95_ms_per_face <= 10 ms/GT_face", "p95_ms_per_face") == ("<=", 10)
    assert io.parse_rule("<= 10 ms/detection", "p95_ms_per_face") is None
    assert io.parse_rule("<= 10", "p95_ms_per_face") is None
    assert io.parse_rule("looks fast", "p95_ms_per_face") is None
    assert io.parse_rule("worst_pair_cell_fnir <= .3", "worst_pair_cell_fnir") == ("<=", 0.3)


def test_fixed_gt_timing_denominator_includes_extra_work():
    from types import SimpleNamespace

    image = SimpleNamespace(sampling_arm=fc.SamplingArm.probability)
    inventory = SimpleNamespace(
        images={"i": image, "empty": image},
        faces={"f": SimpleNamespace(image_id="i")},
        psus={"i": "p", "empty": "q"},
        folds={"p": 0, "q": 0},
        test_fold=0,
    )
    rows = [
        SimpleNamespace(
            leg_key="leg",
            arm=fc.Arm.native,
            fold=0,
            sampling_arm=fc.SamplingArm.probability,
            timing_receipt_ref=ref,
            image_id="i",
        )
        for ref in ("gt", "extra")
    ]
    receipt = {"timing_receipt_ms": {"gt": 6, "extra": 4, "leg/native/image:empty": 99}}
    assert io.timing_exposure(receipt, rows, inventory, "leg") == (109, None)
    receipt["timing_receipt_ms"]["extra"] = 14
    assert io.timing_exposure(receipt, rows, inventory, "leg") == (119, None)
    del receipt["timing_receipt_ms"]["extra"]
    assert io.timing_exposure(receipt, rows, inventory, "leg")[0] is None


def test_origin_requires_declaration_and_parent_implies_synthetic():
    from types import SimpleNamespace

    image = SimpleNamespace(image_id="i", synthetic_parent_id=None)
    assert io.data_origin(image, {}) == "unknown"
    assert io.data_origin(image, {"data_origin_by_image": {"i": {"origin": "real"}}}) == "unknown"
    declaration = {"data_origin_by_image": {"i": {"origin": "real", "provenance_ref": "fake-fixture"}}}
    assert io.data_origin(image, declaration) == "real"
    image.synthetic_parent_id = "parent"
    assert io.data_origin(image, declaration) == "synthetic"


@pytest.fixture
def calibration_spy(monkeypatch):
    """Observe real calibration calls without replacing selection or statistics."""
    from scripts.eval_harness import firbench_score as fs

    calls = []
    calibrate = fs.calibrate_tau

    def wrapped(records, **kwargs):
        calls.append((frozenset(kwargs["calibration_folds"]), dict(kwargs["identity_folds"])))
        return calibrate(records, **kwargs)

    monkeypatch.setattr(fs, "calibrate_tau", wrapped)
    return calls


@pytest.fixture
def fake_run(tmp_path):
    import dataclasses as dc
    import json

    from scripts.eval_harness import firbench_frames as ff
    from scripts.eval_harness.firbench_legs import FaceSearchRecord, write_searches_jsonl

    root = Path(__file__).resolve().parents[4]
    decision = fc.load_decision_manifest(root / "benchmarks/manifests/fir-bench-decision-v1.json")
    spec = fc.FrameSpec("fake-only", fc.Admissibility.development, False, "a" * 64, True)
    guard = fc.Guardrail("latency", "p95_ms_per_face", "<= 10 ms/GT_face", "all", fc.GuardrailRole.veto)
    decision = dc.replace(
        decision,
        frames=(spec,),
        guardrails=(guard,),
        primary=dc.replace(decision.primary, fpir_target=0.1),
        gallery_lineage=dc.replace(decision.gallery_lineage, templates_sha256="b" * 64),
        ratification=fc.Ratification("fake-only-declaration", "2026-01-01T00:00:00Z"),
    )
    decision = fc.seal(decision, sealed_at="2026-01-01T00:00:00Z")
    images = [ff.ImageUnit(f"i{i:04d}", "a" * 64, fc.SamplingArm.probability, 1.0) for i in range(400)]
    faces = [
        ff.GtFace(
            f"f{i:04d}",
            im.image_id,
            (0.0, 0.0, 10.0, 10.0),
            fc.IdentityStatus.named,
            f"id{i:04d}",
            annotation=ff.FaceAnnotation(occluders=()),
        )
        for i, im in enumerate(images)
    ]
    psus = ff.build_psu_components(images, faces)
    ids = ff.identity_to_component(faces, psus)
    folds = ff.identity_disjoint_folds(psus, ids, k=5, seed=decision.fold_protocol.seed)
    identity_folds = {i: folds[p] for i, p in ids.items()}
    gallery_ids = frozenset(ids)
    test = decision.fold_protocol.seed % 5
    pool = ff.build_nonmated_pool(
        faces,
        images,
        folds,
        fold=test,
        component_map=psus,
        exhaustive=True,
        planning_icc=0.1,
        enrolled_identity_ids=gallery_ids,
    )
    frame = ff.Frame(
        spec,
        tuple(images),
        tuple(faces),
        psus,
        folds,
        identity_folds,
        dict.fromkeys(range(5), "b" * 64),
        {f: fc.FoldRole.test if f == test else fc.FoldRole.fit for f in range(5)},
        0.1,
        1.0,
        float(len(faces)),
        pool.n_units,
        pool.n_nonmated_eff,
        {"probability": len(images), "challenge": 0},
    )
    (tmp_path / "frame.json").write_text(ff.frame_json(frame))
    keys = [f"{kind}__native__fake__cv4__ort1" for kind in ("sface", "auraface", "insightface")]
    registry = [
        {
            "leg_key": key,
            "fold": f,
            "gallery_sha256": "b" * 64,
            "enrolled_identity_ids": sorted(i for i in gallery_ids if identity_folds[i] == f),
            "identity_folds": identity_folds,
            "enrolled_occluders": {i: [] for i in gallery_ids if identity_folds[i] == f},
        }
        for key in keys
        for f in range(5)
    ]
    manifest = {
        "firbench": {
            "leg_keys": keys,
            "gallery_membership": registry,
            "decision_sha256": fc.manifest_sha256(decision),
            "frame": {
                "frame_id": spec.frame_id,
                "admissibility": spec.admissibility.value,
                "sealed": False,
                "source_sha256": spec.source_sha256,
                "exhaustive": True,
            },
        }
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    timings = {}
    all_rows = {}
    for key in keys:
        rows = []
        for face in faces:
            p = psus[face.image_id]
            fold = folds[p]
            common = {
                "image_id": face.image_id,
                "psu_id": p,
                "fold": fold,
                "fold_role": frame.fold_roles[fold],
                "sampling_arm": fc.SamplingArm.probability,
                "inclusion_probability": 1.0,
                "cohort": None,
                "leg_key": key,
                "arm": fc.Arm.native,
                "arm_availability": fc.ArmStatus.available,
                "alignment_mode": fc.AlignmentMode.separable,
                "stage_reached": fc.SearchStage.embedded,
                "gallery_sha256": "b" * 64,
            }
            for background in (False, True):
                fid = "det-" + face.face_id if background else face.face_id
                ref = f"{key}/native/{fid}"
                record = FaceSearchRecord(
                    **common,
                    face_id=fid,
                    identity_id=None if background else face.identity_id,
                    identity_status=fc.IdentityStatus.unknown if background else fc.IdentityStatus.named,
                    cell=("unknown", "unknown") if background else ("clear", "clear"),
                    unit_id="background:" + face.image_id if background else None,
                    top_k=((face.identity_id, 0.2 if background else 0.9),),
                    timing_receipt_ref=ref,
                )
                rows.append(record)
                timings[ref] = 2.0
        path = tmp_path / "legs" / key / "searches.jsonl"
        path.parent.mkdir(parents=True)
        write_searches_jsonl(path, rows)
        all_rows[key] = rows
    (tmp_path / "timings.json").write_text(json.dumps({"timing_receipt_ms": timings}, sort_keys=True))
    return tmp_path, decision, manifest, frame, all_rows


def test_complete_fake_run_replays_and_changed_receipt_changes_real_veto(fake_run, calibration_spy, monkeypatch):
    import hashlib
    import json

    path, decision, manifest, frame, rows = fake_run
    actual_verdicts = []
    decide = io.core.decide

    def observed_decide(*args, **kwargs):
        verdict = decide(*args, **kwargs)
        actual_verdicts.append(verdict)
        return verdict

    monkeypatch.setattr(io.core, "decide", observed_decide)
    receipt = (path / "timings.json").read_bytes()
    first = io.score_run(path, decision=decision)
    second = io.score_run(path, decision=decision)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert (path / "timings.json").read_bytes() == receipt
    assert first["verdict"] == {"state": "inconclusive", "reason": None}
    assert first["decision_path"] == list(actual_verdicts[0].decision_path) == ["eligibility:passed", "H1:not_rejected"]
    assert decision.interval.n_boot == 10000
    assert decision.min_n_independent == 50 and decision.cell_floor_n_independent == 30
    assert first["hypotheses"][0]["interval"] is not None
    assert first["guardrails"][0]["state"] == "pass"
    assert first["guardrails"][0]["value"] is None
    assert first["guardrails"][0]["timings_sha256"] == hashlib.sha256(receipt).hexdigest()
    assert first["n_units"] == frame.n_units
    assert all(leg["pair_fmr"]["status"] == "not_evaluated" for leg in first["legs"])
    assert all(leg["tau"]["data"]["pooled_units"] == 400 - frame.n_units for leg in first["legs"])
    assert all(0 not in folds for folds, identities in calibration_spy)
    assert all(identities == frame.identity_fold for _, identities in calibration_spy)
    assert all(c["data_origin"] == "unknown" and c["n_identities"] == c["n_units"] for c in first["cells"])
    assert all(not g["scored"] and g["reason"] == "attribution_arm_not_run" for g in first["joint_gaps"])
    changed = json.loads(receipt)
    changed["timing_receipt_ms"] = dict.fromkeys(changed["timing_receipt_ms"], 100)
    (path / "timings.json").write_text(json.dumps(changed))
    last = io.score_run(path, decision=decision)
    assert last["guardrails"][0]["state"] == "fail"
    assert last["verdict"]["state"] == "guardrail_vetoed"
    assert (
        last["decision_path"]
        == list(actual_verdicts[-1].decision_path)
        == ["eligibility:passed", "H1:guardrail_vetoed"]
    )
    assert last["guardrails"][0]["timings_sha256"] != first["guardrails"][0]["timings_sha256"]
    assert last["guardrails"][0]["value"] is None


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("gallery", "gallery SHA"),
        ("fold", "fold binding"),
        ("identity", "GT identity"),
        ("cell", "GT query/enrolled"),
        ("duplicate", "duplicate face/arm"),
        ("drop", "every GT face"),
        ("timing_ref", "receipt reference binding"),
    ],
)
def test_record_provenance_refusals(fake_run, mutation, reason):
    import json

    path, decision, manifest, frame, all_rows = fake_run
    key = manifest["firbench"]["leg_keys"][0]
    target = path / "legs" / key / "searches.jsonl"
    rows = [r.to_dict() for r in all_rows[key]]
    if mutation == "gallery":
        rows[0]["gallery_sha256"] = "c" * 64
    elif mutation == "fold":
        rows[0]["fold"] = (rows[0]["fold"] + 1) % 5
    elif mutation == "identity":
        rows[0]["identity_id"] = "wrong"
    elif mutation == "cell":
        rows[0]["cell"] = ["unknown", "clear"]
    elif mutation == "duplicate":
        rows.append(rows[0])
    elif mutation == "drop":
        rows.pop(0)
    elif mutation == "timing_ref":
        rows[0]["timing_receipt_ref"] = "another-leg/native/borrowed-cost"
    target.write_text("".join(json.dumps(r) + "\n" for r in rows))
    with pytest.raises(fc.FrameContractError, match=reason):
        io.score_run(path, decision=decision)


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("missing", "registry is required"),
        ("membership", "share declared"),
        ("identity_folds", "provenance"),
        ("decision", "decision digest"),
    ],
)
def test_manifest_provenance_refusals(fake_run, mutation, reason):
    import json

    path, decision, manifest, frame, all_rows = fake_run
    f = manifest["firbench"]
    if mutation == "missing":
        del f["gallery_membership"]
    elif mutation == "membership":
        removed = f["gallery_membership"][0]["enrolled_identity_ids"].pop()
        del f["gallery_membership"][0]["enrolled_occluders"][removed]
    elif mutation == "identity_folds":
        f["gallery_membership"][0]["identity_folds"] = {}
    else:
        f["decision_sha256"] = "f" * 64
    (path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(fc.FrameContractError, match=reason):
        io.score_run(path, decision=decision)


def test_explicit_old_score_wire_refuses_new_fields(fake_run, monkeypatch):
    import json

    path, decision, manifest, frame, all_rows = fake_run
    # Explicit pre-decision-trace wire, independent of the installed current schema.
    schema = {
        "type": "object",
        "properties": {name: {} for name in fc._load_schema("scores-v1")["properties"] if name != "decision_path"},
        "additionalProperties": False,
    }
    load_schema = fc._load_schema
    monkeypatch.setattr(fc, "_load_schema", lambda name: schema if name == "scores-v1" else load_schema(name))
    with pytest.raises(fc.FrameContractError):
        io.score_run(path, decision=decision)


def test_guardrail_never_passes_when_a_leg_has_missing_calibration(fake_run):
    path, decision, manifest, frame, all_rows = fake_run
    contexts = {key: {"tau": None, "test": [], "units": []} for key in all_rows}
    output, readings = io._guardrails(decision, manifest["firbench"], contexts, [], {}, None, None, [])
    assert output[0]["state"] == "unscored"
    assert output[0]["evidence"]["reason"] == "calibration_unavailable"


def test_cell_intervals_use_declared_cell_floor_after_global_floor(fake_run):
    import dataclasses as dc

    path, decision, manifest, frame, all_rows = fake_run
    inventory = io._inventory(frame.to_payload(), decision, {f: frozenset(frame.identity_fold) for f in range(5)})
    key = next(iter(all_rows))
    test = [r for r in all_rows[key] if r.fold == 0 and r.unit_id is None]
    assert len(test) >= decision.min_n_independent
    # 30 independent faces in one cell, the remaining GT faces in another cell.
    test = [dc.replace(r, cell=("mask", "clear") if i < 30 else ("clear", "clear")) for i, r in enumerate(test)]
    cells = io._cells(key, test, 0.5, inventory, manifest["firbench"], decision)
    mask = next(c for c in cells if c["query_occluder"] == "mask")
    assert mask["scored"] and mask["n_psu"] == decision.cell_floor_n_independent
    assert mask["interval"] == {"lower": 0.0, "upper": 0.0, "level": 0.95}


def test_joint_gap_pairs_only_available_gt_faces(fake_run):
    import dataclasses as dc

    path, decision, manifest, frame, all_rows = fake_run
    inventory = io._inventory(frame.to_payload(), decision, dict.fromkeys(range(5), frozenset(frame.identity_fold)))
    key = next(iter(all_rows))
    native = [
        dc.replace(r, stage_reached=fc.SearchStage.detected, top_k=())
        for r in all_rows[key]
        if r.fold == 0 and r.unit_id is None
    ]
    attr_key = key.replace("__native__", "__gt_crop_redetect__")
    attr = [
        dc.replace(
            r,
            leg_key=attr_key,
            arm=fc.Arm.gt_crop_redetect,
            stage_reached=fc.SearchStage.embedded,
            top_k=((r.identity_id, 0.9),),
        )
        for r in native[5:]
    ]
    gaps = io._joint_gaps(key, native, attr, 0.5, inventory, decision)
    assert gaps[0]["scored"]
    assert gaps[0]["delta"] == 1.0
    assert gaps[0]["interval"] == {"lower": 1.0, "upper": 1.0, "level": 0.95}
    assert gaps[0]["n_pairs"] == len(native) - 5
    assert gaps[0]["unavailable_counts"] == {"native": 0, "attribution": 5}
    assert not gaps[1]["scored"] and gaps[1]["delta"] is None


def test_guardrail_measurements_and_missing_denominators(fake_run):
    import dataclasses as dc
    from types import SimpleNamespace

    path, decision, manifest, frame, all_rows = fake_run
    inventory = io._inventory(frame.to_payload(), decision, dict.fromkeys(range(5), frozenset(frame.identity_fold)))
    key = next(iter(all_rows))
    rows = [r for r in all_rows[key] if r.fold == 0]
    units = io._units(inventory, 0, fc.SamplingArm.probability)
    contexts = {key: {"tau": 0.5, "test": rows, "units": units}}
    guards = (
        fc.Guardrail("names", "false_names_per_1k_mentions", "<= 2 names/1000_mentions", "all", fc.GuardrailRole.veto),
        fc.Guardrail("cohorts", "per_cohort_fpir", "<= .1 rate", "per_cohort", fc.GuardrailRole.veto),
        fc.Guardrail("cells", "worst_pair_cell_fnir", "<= .2 rate", "pair_cell", fc.GuardrailRole.veto),
        fc.Guardrail(
            "cost",
            "cost_per_accepted_description",
            "<= 5 cost/accepted_description",
            "all",
            fc.GuardrailRole.report_only,
        ),
    )
    decision = dc.replace(decision, guardrails=guards)
    cells = [{"leg_key": key, "query_occluder": "clear", "enrolled_occluder": "clear", "scored": False, "fnir": None}]
    first, _ = io._guardrails(
        decision, manifest["firbench"], contexts, cells, {}, None, inventory, sum(all_rows.values(), [])
    )
    assert all(g["state"] == "unscored" for g in first)
    assert first[0]["evidence"]["reason"] == "external_mention_denominator_missing"
    assert first[1]["evidence"]["reason"] == "cohort_nonmated_units_missing"
    assert first[2]["evidence"]["reason"] == "named_cells_below_floor_or_absent"
    manifest["firbench"]["external_mention_denominators"] = {key: 1000}
    manifest["firbench"]["cost_report"] = {
        "total_cost": 12,
        "accepted_descriptions": 4,
        "provenance_ref": "fake-only-cost",
    }
    cells[0].update(scored=True, fnir=0.1)
    second, _ = io._guardrails(
        decision, manifest["firbench"], contexts, cells, {}, None, inventory, sum(all_rows.values(), [])
    )
    assert second[0]["state"] == "pass" and second[0]["value"] == 0
    assert second[2]["state"] == "pass" and second[2]["value"] == 0.1
    assert second[3]["state"] == "pass" and second[3]["value"] == 3
    # A face cohort cannot borrow the many background units to become resolvable.
    contexts[key]["units"] = units + [SimpleNamespace(unit_id="face-only", psu_id="one", cohort={"sex": "unknown"})]
    third, _ = io._guardrails(
        decision, manifest["firbench"], contexts, cells, {}, None, inventory, sum(all_rows.values(), [])
    )
    assert third[1]["state"] == "unscored" and third[1]["evidence"]["reason"] == "cohort_fpir_unresolvable"


def test_gallery_empty_is_explicit_and_changes_source_units(fake_run):
    import dataclasses as dc

    path, decision, manifest, frame, all_rows = fake_run
    enrolled = dict.fromkeys(range(5), frozenset())
    count = sum(frame.folds[frame.psu_map[i.image_id]] == 0 for i in frame.images)
    changed = dc.replace(frame, n_units=2 * count, n_nonmated_eff=2 * count / 1.1)
    inventory = io._inventory(changed.to_payload(), decision, enrolled)
    pool = inventory.pools[0]
    assert pool.n_units == 2 * count
    assert {u.unit_id for u in pool.units if not u.unit_id.startswith("background:")} == {
        f.face_id for f in frame.faces if frame.folds[frame.psu_map[f.image_id]] == 0
    }


def test_calibration_absence_is_retained_as_unscored_evidence(fake_run):
    import json

    path, decision, manifest, frame, all_rows = fake_run
    for key, records in all_rows.items():
        raw = [r.to_dict() for r in records]
        for r in raw:
            if r["unit_id"] is not None:
                r["top_k"] = []
        (path / "legs" / key / "searches.jsonl").write_text("".join(json.dumps(r) + "\n" for r in raw))
    scores = io.score_run(path, decision=decision)
    assert scores["verdict"] == {"state": "inconclusive", "reason": "required_guardrail_unscored"}
    assert all(
        leg["tau"]["reason"] == "tau_infeasible" and leg["operating_point"]["fnir"]["data"] is None
        for leg in scores["legs"]
    )
    assert scores["guardrails"][0]["evidence"]["reason"] == "calibration_unavailable"


def test_unavailable_native_units_are_not_imputed_as_correct_rejects(fake_run):
    import dataclasses as dc

    path, decision, manifest, frame, all_rows = fake_run
    inventory = io._inventory(frame.to_payload(), decision, dict.fromkeys(range(5), frozenset(frame.identity_fold)))
    rows = [r for r in next(iter(all_rows.values())) if r.fold == 0]
    index = next(i for i, r in enumerate(rows) if r.unit_id is not None)
    rows[index] = dc.replace(
        rows[index], arm_availability=fc.ArmStatus.unavailable, stage_reached=fc.SearchStage.unavailable, top_k=()
    )
    point = io._operating(rows, io._units(inventory, 0, fc.SamplingArm.probability), 0.5, decision)
    assert point["fnir"]["status"] == "available"
    assert point["fpir"] == {"status": "unavailable", "reason": "native_nonmated_search_unavailable", "data": None}


def _rewrite_rows(path, key, records):
    from scripts.eval_harness.firbench_legs import write_searches_jsonl

    write_searches_jsonl(path / "legs" / key / "searches.jsonl", records)


@pytest.mark.parametrize("absent_leg", ["sface", "auraface", "insightface"])
def test_one_leg_tau_absence_preserves_real_support_and_unavailable_evidence(fake_run, absent_leg):
    import dataclasses as dc

    path, decision, manifest, frame, all_rows = fake_run
    key = next(k for k in all_rows if k.startswith(absent_leg + "__"))
    _rewrite_rows(
        path, key, [dc.replace(r, top_k=()) if r.fold != 0 and r.unit_id is not None else r for r in all_rows[key]]
    )
    result = io.score_run(path, decision=decision)
    assert result["verdict"] == {"state": "inconclusive", "reason": "required_guardrail_unscored"}
    assert result["decision_path"] == ["eligibility:required_guardrail_unscored"]
    assert result["n_eff"] == result["n_units"] == frame.n_units
    for leg in result["legs"]:
        if leg["leg_key"] == key:
            assert leg["tau"] == {"status": "unavailable", "reason": "tau_infeasible", "data": None}
            assert all(v["status"] == "unavailable" and v["data"] is None for v in leg["operating_point"].values())
        else:
            assert leg["tau"]["status"] == "available"
            assert leg["operating_point"]["fnir"]["data"]["n_mated"] == frame.n_units
    for declared, actual in zip(decision.hypotheses, result["hypotheses"], strict=True):
        assert actual["interval"] is None
        assert actual["n_eff"] == frame.n_units
        assert (actual["mde"] is None) == (fc.LegKind(absent_leg) in declared.legs)
    for row in result["icc_sensitivity"]:
        for declared, actual in zip(decision.hypotheses, row["hypotheses"], strict=True):
            assert (actual["mde"] is None) == (fc.LegKind(absent_leg) in declared.legs)
            assert actual["scored"] == (actual["mde"] is not None)
    assert all(not c["scored"] and c["fnir"] is c["interval"] is None for c in result["cells"] if c["leg_key"] == key)
    assert next(c for c in result["curves"] if c["leg_key"] == key)["points"] == []


@pytest.mark.parametrize("missing_tau", [False, True])
def test_actual_native_paired_mismatch_is_refused_even_with_tau_absence(fake_run, missing_tau):
    import dataclasses as dc

    path, decision, manifest, frame, all_rows = fake_run
    key = next(iter(all_rows))
    target = next(r.face_id for r in all_rows[key] if r.fold == 0 and r.unit_id is None)
    rows = []
    for r in all_rows[key]:
        if r.face_id == target:
            r = dc.replace(
                r, arm_availability=fc.ArmStatus.unavailable, stage_reached=fc.SearchStage.unavailable, top_k=()
            )
        elif missing_tau and r.fold != 0 and r.unit_id is not None:
            r = dc.replace(r, top_k=())
        rows.append(r)
    _rewrite_rows(path, key, rows)
    with pytest.raises(fc.FrameContractError, match="exactly the same mated GT face ids"):
        io.score_run(path, decision=decision)


@pytest.mark.parametrize("missing_tau", [False, True])
def test_unratified_run_never_sets_hypothesis_states_or_intervals(fake_run, missing_tau):
    import dataclasses as dc
    import json

    path, decision, manifest, frame, all_rows = fake_run
    decision = dc.replace(decision, ratification=fc.Ratification(None, None), seal=None)
    manifest["firbench"]["decision_sha256"] = fc.manifest_sha256(decision)
    (path / "manifest.json").write_text(json.dumps(manifest))
    if missing_tau:
        key = next(iter(all_rows))
        _rewrite_rows(
            path, key, [dc.replace(r, top_k=()) if r.fold != 0 and r.unit_id is not None else r for r in all_rows[key]]
        )
    result = io.score_run(path, decision=decision)
    assert result["verdict"] == {"state": "unratified", "reason": None}
    assert result["decision_path"] == ["unratified:numbers_only"]
    assert all(h["state"] is h["reason"] is h["interval"] is None for h in result["hypotheses"])


@pytest.mark.parametrize("boundary", list(fc.BoundarySemantics))
def test_empirical_curve_exact_ties_endpoints_and_raw_source_unit_rates(fake_run, boundary):
    import dataclasses as dc
    import math
    from fractions import Fraction

    path, decision, manifest, frame, all_rows = fake_run
    decision = dc.replace(decision, boundary_semantics=boundary)
    inventory = io._inventory(frame.to_payload(), decision, dict.fromkeys(range(5), frozenset(frame.identity_fold)))
    rows = [r for r in next(iter(all_rows.values())) if r.fold == 0]
    units = io._units(inventory, 0, fc.SamplingArm.probability)
    # Two alarms on one source unit cannot mint another denominator or FPI.
    alarm = next(r for r in rows if r.unit_id is not None)
    rows += [dc.replace(alarm, face_id="duplicate-alarm")]
    points = io._curve_points(rows, units, 0.5, decision)
    thresholds = [p["threshold"] for p in points]
    assert thresholds == sorted(set(thresholds)) and all(math.isfinite(t) for t in thresholds)
    assert {0.2, 0.5, 0.9} <= set(thresholds)
    assert thresholds[0] < 0.2 and thresholds[-1] > 0.9
    assert len(points) > 3
    # Fixed exact denominator, including source units with no detector output.
    tied = next(p for p in points if p["threshold"] == 0.2)
    assert tied["fpir"] == (1.0 if boundary is fc.BoundarySemantics.v2 else 0.0)
    first_alarm = next(r for r in rows if r.unit_id is not None)
    one_alarm = [r for r in rows if r.unit_id is None] + [first_alarm]
    partial = io._curve_points(one_alarm, units, 0.5, decision)
    assert partial[0]["fpir"] == float(Fraction(1, len(units)))
    assert points[0]["fpir"] == 1 and points[0]["fnir"] == 0
    assert points[-1]["fpir"] == 0 and points[-1]["fnir"] == 1
    at_mate = next(p for p in points if p["threshold"] == 0.9)
    assert at_mate["fnir"] == 0  # mated equality accepts in both semantics
    changed = [
        dc.replace(r, arm_availability=fc.ArmStatus.unavailable, stage_reached=fc.SearchStage.unavailable, top_k=())
        if r is alarm
        else r
        for r in rows
    ]
    assert io._curve_points(changed, units, 0.5, decision) == []


def test_fit_probe_hit_on_held_out_identity_is_refused_with_full_map(fake_run):
    import dataclasses as dc
    import json

    path, decision, manifest, frame, all_rows = fake_run
    test_id = next(i for i, fold in frame.identity_fold.items() if fold == 0)
    key = manifest["firbench"]["leg_keys"][0]
    for row in manifest["firbench"]["gallery_membership"]:
        if row["fold"] != 0:
            row["enrolled_identity_ids"].append(test_id)
    (path / "manifest.json").write_text(json.dumps(manifest))
    # The full map is forwarded unfiltered; the leak is a fit search that actually returns the held-out name.
    target = next(r for r in all_rows[key] if r.fold != 0 and r.unit_id is not None)
    _rewrite_rows(
        path,
        key,
        [dc.replace(r, top_k=((test_id, 0.95),)) if r.face_id == target.face_id else r for r in all_rows[key]],
    )
    with pytest.raises(fc.CalibrationLeakError):
        io.score_run(path, decision=decision)


def test_fit_fold_snapshot_may_differ_from_test_fold_snapshot(fake_run):
    import dataclasses as dc
    import json

    from scripts.eval_harness import firbench_frames as ff

    path, decision, manifest, frame, all_rows = fake_run
    original = io.score_run(path, decision=decision)
    snapshot, fit_fold = "c" * 64, 1
    for row in manifest["firbench"]["gallery_membership"]:
        if row["fold"] == fit_fold:
            row["gallery_sha256"] = snapshot
    (path / "manifest.json").write_text(json.dumps(manifest))
    changed_frame = dc.replace(frame, gallery_sha256_by_fold={**frame.gallery_sha256_by_fold, fit_fold: snapshot})
    (path / "frame.json").write_text(ff.frame_json(changed_frame))
    for key, records in all_rows.items():
        _rewrite_rows(
            path,
            key,
            [dc.replace(r, gallery_sha256=snapshot) if r.fold == fit_fold else r for r in records],
        )
    changed = io.score_run(path, decision=decision)
    assert [leg["tau"] for leg in changed["legs"]] == [leg["tau"] for leg in original["legs"]]
    assert [leg["operating_point"] for leg in changed["legs"]] == [leg["operating_point"] for leg in original["legs"]]
    assert changed["n_units"] == original["n_units"] == frame.n_units


def test_challenge_curves_are_separate_and_test_scores_do_not_refit_tau(fake_run, calibration_spy):
    import dataclasses as dc

    from scripts.eval_harness import firbench_frames as ff

    path, decision, manifest, frame, all_rows = fake_run
    original = io.score_run(path, decision=decision)
    selected = next(r.image_id for r in next(iter(all_rows.values())) if r.fold == 0)
    changed_frame = dc.replace(
        frame,
        images=tuple(
            dc.replace(im, sampling_arm=fc.SamplingArm.challenge, inclusion_probability=None)
            if im.image_id == selected
            else im
            for im in frame.images
        ),
        sampling_arm_counts={"probability": len(frame.images) - 1, "challenge": 1},
    )
    (path / "frame.json").write_text(ff.frame_json(changed_frame))
    for key, records in all_rows.items():
        _rewrite_rows(
            path,
            key,
            [
                dc.replace(
                    r,
                    sampling_arm=fc.SamplingArm.challenge,
                    inclusion_probability=None,
                    top_k=((r.top_k[0][0], 0.95 if r.unit_id else 0.1),),
                )
                if r.image_id == selected
                else r
                for r in records
            ],
        )
    changed = io.score_run(path, decision=decision)
    assert [leg["tau"] for leg in original["legs"]] == [leg["tau"] for leg in changed["legs"]]
    assert all(0 not in folds and identities == frame.identity_fold for folds, identities in calibration_spy)
    for key in all_rows:
        probability = next(c["points"] for c in changed["curves"] if c["leg_key"] == key)
        challenge = next(c["points"] for c in changed["curves"] if c["leg_key"] == key + "::sampling=challenge")
        assert len(probability) > 1 and len(challenge) > 1
        assert next(p for p in probability if p["threshold"] == 0.9)["fnir"] == 0
        assert next(p for p in challenge if p["threshold"] == 0.95)["fnir"] == 1
        tau = next(leg["tau"]["data"]["value"] for leg in changed["legs"] if leg["leg_key"] == key)
        assert next(p for p in probability if p["threshold"] == tau)["fpir"] == 0
        assert next(p for p in challenge if p["threshold"] == tau)["fpir"] == 1
        assert (
            next(leg for leg in changed["legs"] if leg["leg_key"] == key)["operating_point"]["fnir"]["data"]["n_mated"]
            == frame.n_units - 1
        )
    assert all(
        c["n_units"] == 1 and not c["scored"] for c in changed["cells"] if "::sampling=challenge" in c["leg_key"]
    )


def test_actual_s2_named_nonmate_clears_search_identity_and_remains_a_fixed_unit(fake_run):
    import dataclasses as dc
    import json
    from types import SimpleNamespace

    import numpy as np

    from scripts.eval_harness import firbench_frames as ff
    from scripts.eval_harness import firbench_legs as fl

    path, decision, manifest, frame, all_rows = fake_run
    target = next(face for face in frame.faces if frame.folds[frame.psu_map[face.image_id]] == 0)
    membership = next(row for row in manifest["firbench"]["gallery_membership"] if row["fold"] == 0)[
        "enrolled_identity_ids"
    ]
    enrolled = frozenset(membership) - {target.identity_id}
    for row in manifest["firbench"]["gallery_membership"]:
        if row["fold"] == 0:
            row["enrolled_identity_ids"] = sorted(enrolled)
            del row["enrolled_occluders"][target.identity_id]
    (path / "manifest.json").write_text(json.dumps(manifest))
    pool = ff.build_nonmated_pool(
        frame.faces,
        frame.images,
        frame.folds,
        fold=0,
        component_map=frame.psu_map,
        exhaustive=True,
        planning_icc=decision.planning_icc,
        enrolled_identity_ids=enrolled,
    )
    changed_frame = dc.replace(frame, n_units=pool.n_units, n_nonmated_eff=pool.n_nonmated_eff)
    (path / "frame.json").write_text(ff.frame_json(changed_frame))
    for key, records in all_rows.items():

        class NoDetectionLeg:
            alignment_mode = fc.AlignmentMode.separable

            def __init__(self, key):
                self.key = key

            def leg_id(self, arm):
                return SimpleNamespace(key=lambda: self.key)

            def observe(self, image):
                return []

        produced = fl.search_leg_arm(
            leg=NoDetectionLeg(key),
            arm=fc.Arm.native,
            images={target.image_id: np.zeros((16, 16, 3), dtype=np.uint8)},
            image_units={im.image_id: im for im in frame.images},
            faces=[target],
            gallery=fl.Gallery({name: np.array([1.0, 0.0]) for name in enrolled}, "b" * 64),
            psu_by_image=frame.psu_map,
            fold_by_psu=frame.folds,
            fold_roles=frame.fold_roles,
            exhaustive=True,
            top_k=1,
            cells={target.face_id: ("clear", "unknown")},
        ).records[0]
        assert produced.identity_id is None and produced.unit_id == target.face_id
        assert produced.stage_reached is fc.SearchStage.missed
        # Background alarms must also search the changed gallery: the removed
        # identity cannot remain as a result in this synthetic search ledger.
        replacement_name = min(enrolled)
        _rewrite_rows(
            path,
            key,
            [
                produced
                if r.face_id == target.face_id
                else dc.replace(
                    r,
                    top_k=tuple(
                        (replacement_name if name == target.identity_id else name, score) for name, score in r.top_k
                    ),
                )
                if r.image_id == target.image_id
                else r
                for r in records
            ],
        )
    result = io.score_run(path, decision=decision)
    assert result["n_units"] == frame.n_units + 1
    assert result["n_nonmated_eff"] == pool.n_nonmated_eff
    assert all(leg["operating_point"]["fnir"]["data"]["n_mated"] == frame.n_units - 1 for leg in result["legs"])
    assert all(leg["operating_point"]["fpir"]["data"]["fpi"] == 0 for leg in result["legs"])


@pytest.mark.parametrize(
    "gate,reason",
    [
        ("psu", "insufficient_independent_psus"),
        ("fpir", "primary_fpir_unresolvable"),
    ],
)
def test_calibration_absence_preserves_earlier_eligibility_gates(fake_run, gate, reason):
    import dataclasses as dc
    import json

    path, decision, manifest, frame, all_rows = fake_run
    decision = dc.replace(
        decision,
        seal=None,
        **(
            {"min_n_independent": 1000}
            if gate == "psu"
            else {"primary": dc.replace(decision.primary, fpir_target=0.001)}
        ),
    )
    decision = fc.seal(decision, sealed_at="2026-01-01T00:00:00Z")
    manifest["firbench"]["decision_sha256"] = fc.manifest_sha256(decision)
    (path / "manifest.json").write_text(json.dumps(manifest))
    key = next(iter(all_rows))
    _rewrite_rows(
        path, key, [dc.replace(r, top_k=()) if r.fold != 0 and r.unit_id is not None else r for r in all_rows[key]]
    )
    result = io.score_run(path, decision=decision)
    assert result["verdict"] == {"state": "inconclusive", "reason": reason}
    assert result["decision_path"] == ["eligibility:" + reason]
    assert all(h["interval"] is None and h["reason"] == reason for h in result["hypotheses"])
