"""Synthetic kernels, real frozen-source assignment, search records and S3 decisions."""

import hashlib
import json
from dataclasses import asdict

import numpy as np
import pytest

from scripts.eval_harness import firbench_contract as fc
from scripts.eval_harness import firbench_frames as ff
from scripts.eval_harness import firbench_legs as fl
from scripts.eval_harness import firbench_runtime as rt
from scripts.eval_harness import firbench_score as score
from scripts.eval_harness import firbench_views as fv


def leg(process):
    return fl.BuffaloLeg(
        process=process, embedding_dim=512, weights_sha256="b" * 64, opencv_version="fake-cv", ort_version="fake-ort"
    )


def detection(box, identity=0):
    return {"bbox_px": box, "landmarks_px": np.zeros((5, 2)), "det_score": 1.0, "embedding": np.eye(512)[identity]}


def context(process):
    pixels = np.zeros((80, 100, 3), np.uint8)
    image = ff.ImageUnit("image", "a" * 64, fc.SamplingArm.probability, 0.5)
    faces = [
        ff.GtFace("alice", "image", (0, 0, 20, 20), fc.IdentityStatus.named, "id-alice"),
        ff.GtFace("bob", "image", (70, 0, 20, 20), fc.IdentityStatus.named, "id-bob"),
    ]
    gallery = fl.Gallery.enrol({"id-alice": [np.eye(512)[0]], "id-bob": [np.eye(512)[1]]})
    return {
        "leg": leg(process),
        "images": {"image": pixels},
        "image_units": {"image": image},
        "faces": faces,
        "gallery": gallery,
        "psu_by_image": {"image": "psu"},
        "fold_by_psu": {"psu": 0},
        "fold_roles": {0: fc.FoldRole.test},
        "exhaustive": True,
        "top_k": 20,
        "offline": True,
        "policy": fv.ViewPolicy.fixed_overlap,
        "budget": fv.ViewBudget(5, 40000, 5, 100, 100, 30),
        "source_proposals": {
            "image": fv.PersonProposalInput(
                "image",
                "a" * 64,
                fv.oriented_pixels_sha256(pixels),
                "opencv-imread-color-exif",
                "missing",
                "synthetic",
                (),
            )
        },
    }


def test_multiple_people_keep_person_misses_and_background_denominator():
    # Alice never localizes. Bob's strong Alice-name alarm must not identify Alice.
    calls = []

    def process(p):
        calls.append(p.shape)
        return [detection((70, 0, 20, 20), 0), detection((30, 40, 10, 10), 1)] if len(calls) == 1 else []

    result = rt.search_view_policy(**context(process))
    rows = {r.face_id: r for r in result.records}
    assert rows["alice"].stage_reached is fc.SearchStage.missed
    assert rows["alice"].top_k == ()
    assert all(r.inclusion_probability == 0.5 and score._weight(r) == 2 for r in result.records)
    assert score.finish_outcomes([rows["alice"]], 0.5, fc.BoundarySemantics.v2)[0] is fc.FaceOutcome.missed
    assert rows["bob"].top_k[0] == ("id-alice", 1.0)
    assert {r.unit_id for r in result.records if r.unit_id} == {"background:image"}
    assert len(result.ledger) == 2
    assert len(result.evidence["image"]["receipts"]) == 5
    assert result.evidence["image"]["assignments"][0]["face_id"] == "bob"


@pytest.mark.parametrize(
    "error,status", [(RuntimeError, "failed"), (TimeoutError, "timeout"), (FileNotFoundError, "missing")]
)
def test_localization_failure_keeps_all_source_units(error, status):
    def process(_):
        raise error("synthetic")

    args = context(process)
    result = rt.search_view_policy(**args)
    assert all(r.stage_reached is fc.SearchStage.missed for r in result.records if r.face_id in {"alice", "bob"})
    assert len(result.ledger) == 2
    assert all(r["status"] == status for r in result.evidence["image"]["receipts"])
    bg = next(r for r in result.records if r.unit_id == "background:image")
    assert bg.arm_availability is fc.ArmStatus.unavailable


def test_person_json_states_and_oriented_lineage():
    pixels = np.zeros((8, 9, 3), np.uint8)
    base = {
        "schema": "firbench-person-boxes/v1",
        "source_id": "image",
        "source_sha256": "a" * 64,
        "oriented_pixels_sha256": fv.oriented_pixels_sha256(pixels),
        "orientation": "opencv-imread-color-exif",
        "source_ref": "offline-human-boxes",
        "boxes": [],
    }
    for state in ("missing", "empty", "failed", "timeout"):
        record = fv.person_proposals_from_json(
            {**base, "status": state}, source_id="image", source_sha256="a" * 64, image_bgr=pixels
        )
        assert record.status == state and record.boxes == ()
    with pytest.raises(fc.FrameContractError, match="oriented"):
        fv.person_proposals_from_json(
            {**base, "status": "empty", "oriented_pixels_sha256": "b" * 64},
            source_id="image",
            source_sha256="a" * 64,
            image_bgr=pixels,
        )


from scene.tests.test_eval_harness_firbench_cli_integration import runtime_files  # noqa: E402,F401


@pytest.fixture
def view_files(runtime_files, monkeypatch):
    """Reuse source files, replace only model-facing kernels with actual producer types."""
    from types import SimpleNamespace

    from recognition.application.embedding.manifest import EmbeddingModelManifest
    from recognition.infrastructure.face_pipeline._common import EmbedBatchResult, RawDetection

    f = runtime_files
    f.query_outputs = {}

    def observations(p):
        # The source's one-pixel purpose marker may be absent from a crop.
        # Actual runtime publishes this manifest after enrollment and before ALL
        # query kernels, so scripted query failures must use that stage boundary.
        value = f.query_outputs.get(int(p[0, 0, 0]) - 1) if (f.private / "run/manifest.json").exists() else None
        if isinstance(value, type) and issubclass(value, Exception):
            raise value("synthetic localization failure")
        return value if value is not None else [detection((0, 0, p.shape[1], p.shape[0]), int(p[0, 0, 0]) - 1)]

    def factory(kind, **_):
        dim = 128 if kind is fc.LegKind.sface else 512

        def detect(batch):
            for p in batch:
                if p[0, 0, 1] == 1:
                    manifest = json.loads((f.private / "run/manifest.json").read_text())["firbench"]
                    assert manifest["experimental_view_policy"]["sha256"]
                    assert manifest["similarity_threshold"] is None
            return [
                [
                    RawDetection(np.array(o["bbox_px"], np.float32), o["landmarks_px"], o["det_score"])
                    for o in observations(p)
                ]
                for p in batch
            ]

        return fl.build_face_pipeline_leg(
            kind,
            manifest=EmbeddingModelManifest("fake", kind.value, dim, "l2", "cosine"),
            detector=SimpleNamespace(detect=detect),
            aligner=SimpleNamespace(align=lambda p, _: SimpleNamespace(crop=p)),
            embedder=SimpleNamespace(
                embedding_dim=dim,
                embed=lambda batch: EmbedBatchResult(
                    np.array([np.eye(dim)[int(p[0, 0, 0]) - 1] for p in batch]), np.ones(len(batch))
                ),
            ),
            weights_sha256=hashlib.sha256(kind.value.encode()).hexdigest(),
            preprocessing=None,
            opencv_version="fake-cv",
            ort_version="fake-ort",
        )

    monkeypatch.setattr(fl, "load_pinned_face_pipeline_leg", factory)
    monkeypatch.setattr(rt, "_load_buffalo_leg", lambda _: leg(observations))
    sources = {}
    for image in json.loads(f.source.read_text())["images"]:
        p = rt._pixels(f.repo / f.binding["query_images"][image["image_id"]]["path"], image["sha256"])
        sources[image["image_id"]] = {
            "schema": "firbench-person-boxes/v1",
            "source_id": image["image_id"],
            "source_sha256": image["sha256"],
            "oriented_pixels_sha256": fv.oriented_pixels_sha256(p),
            "orientation": "opencv-imread-color-exif",
            "status": "empty",
            "source_ref": "synthetic-offline",
            "boxes": [],
        }
    recipe = {
        "schema": "firbench-offline-view-policy/v1",
        "policy": "fixed_overlap",
        "budget": asdict(fv.ViewBudget(5, 10000, 5, 100, 100, 30)),
        "quarter_turns": 0,
        "duplicate_tolerance_px": 0.0,
        "sources": sources,
    }
    policy = f.private / "policy.json"
    policy.write_text(json.dumps(recipe))
    f.policy = policy
    f.policy_sha = hashlib.sha256(policy.read_bytes()).hexdigest()
    return f


def test_cli_full_opt_in_producer_to_records_and_experimental_score(view_files, monkeypatch):
    from scripts.eval_harness import firbench_cli as cli

    f = view_files
    monkeypatch.setattr(cli, "_repo_root", lambda: f.repo)
    assert (
        cli.main(
            [
                "run-views",
                "--offline",
                "--frame",
                "fake-only",
                "--decision",
                str(f.decision),
                "--legs",
                "sface,auraface,insightface",
                "--view-policy",
                str(f.policy),
                "--view-policy-sha256",
                f.policy_sha,
                "--created-at",
                "2026-10-15T08:00:00+00:00",
                "--out",
                str(f.private / "run"),
            ]
        )
        == 0
    )
    directory = f.private / "run"
    manifest = json.loads((directory / "manifest.json").read_text())["firbench"]
    assert manifest["experimental_view_policy"]["sha256"] == f.policy_sha
    assert manifest["arms"] == ["native"]
    assert not list(directory.rglob("cache.npz"))
    assert list((directory / "views" / f.policy_sha).glob("*.json"))
    for key in manifest["leg_keys"]:
        rows = [json.loads(x) for x in (directory / "legs" / key / "searches.jsonl").read_text().splitlines()]
        assert len([r for r in rows if not r["face_id"].startswith("det:")]) == 30
        expected = {f"background:{image['image_id']}" for image in json.loads(f.source.read_text())["images"]}
        registry = {(r["leg_key"], r["fold"]): r for r in manifest["gallery_membership"]}
        source_faces = {face["face_id"]: face for face in json.loads(f.source.read_text())["faces"]}
        expected.update(
            r["face_id"]
            for r in rows
            if r["face_id"] in source_faces
            and source_faces[r["face_id"]]["identity_id"] not in registry[key, r["fold"]]["enrolled_identity_ids"]
        )
        assert {r["unit_id"] for r in rows if r["unit_id"]} == expected
        assert all(r["inclusion_probability"] == 1 for r in rows)
    assert cli.main(["score", str(directory)]) == 2
    assert cli.main(["score-views", str(directory)]) == 0
    output = json.loads((directory / "experimental-view-scores.json").read_text())
    assert output["promotion"] == "hold"
    assert output["policy_sha256"] == f.policy_sha
    assert len(output["face_outcomes"]) == 90
    assert all(leg["threshold_source"] == "policy_fit_folds" for leg in output["legs"])
    assert not (directory / "scores.json").exists()


def test_cli_requires_offline_and_does_not_add_arms():
    from scripts.eval_harness import firbench_cli as cli

    assert [a.value for a in fc.Arm] == ["native", "gt_crop_redetect", "cached_yunet_landmark_replay"]
    with pytest.raises(SystemExit):
        cli._build_parser().parse_args(
            [
                "run-views",
                "--frame",
                "x",
                "--decision",
                "x",
                "--legs",
                "sface",
                "--view-policy",
                "x",
                "--view-policy-sha256",
                "a" * 64,
                "--out",
                "x",
            ]
        )


def test_repeated_cross_view_duplicate_group_is_one_spurious_alarm():
    offsets = iter([(0, 0), (0, 0), (25, 0), (0, 20), (25, 20)])

    def process(_):
        x, y = next(offsets)
        values = [detection((-x, -y, 20, 20)), detection((1 - x, -y, 20, 20), 1)]
        for row in values:
            row["landmarks_px"] = np.zeros((5, 2)) - np.array([x, y])
        return values

    args = context(process)
    result = rt.search_view_policy(**args)
    # Same-view duplicates cannot merge with each other; each repeats across views.
    assert len(result.evidence["image"]["groups"]) == 2
    duplicate_rows = [r for r in result.records if r.cell == ("duplicate", "duplicate")]
    assert len(duplicate_rows) == 1
    units = [ff.NonMatedUnit("background:image", 0, "psu", None)]
    point = score.curve(result.records, units=units, thresholds=[0.5], boundary=fc.BoundarySemantics.v2)[0]
    assert point.n_units == 1 and point.spurious_names == 1


POLICIES = [fv.ViewPolicy.scene_only, fv.ViewPolicy.fixed_overlap, fv.ViewPolicy.person_boxes]
# Hand-counted sightings of each marker: A whole scene; B adds four 75x60 corner
# crops at (0,0), (25,0), (0,20), (25,20); C adds the two person boxes below.
SIGHTINGS = {
    fv.ViewPolicy.scene_only: {(10, 10): 1, (70, 50): 1},
    fv.ViewPolicy.fixed_overlap: {(10, 10): 2, (70, 50): 5},
    fv.ViewPolicy.person_boxes: {(10, 10): 2, (70, 50): 2},
}
BACKGROUND_CASES = {  # markers {(x, y): gallery identity index}, additional spurious names
    "same_name_two_groups": ({(10, 10): 0, (70, 50): 0}, 1),
    "different_names_two_groups": ({(10, 10): 0, (70, 50): 1}, 1),
    "one_group_repeated_views": ({(70, 50): 0}, 0),
}


def background_scene(markers, policy, fail_call=None):
    """No-GT source; each view reports one face at every visible identity marker.

    Every view maps a marker to the same oriented-source geometry, so its repeated
    sightings are one conservative group. The pool comes from actual S1 producers.
    """
    pixels = np.zeros((80, 100, 3), np.uint8)
    for (x, y), identity in markers.items():
        pixels[y, x, 0] = identity + 1

    def kernel(fail_at):
        calls = []

        def process(p):
            calls.append(p.shape)
            if len(calls) == fail_at:
                raise RuntimeError("synthetic view failure")
            return [
                {
                    "bbox_px": (float(x), float(y), 10.0, 10.0),
                    "landmarks_px": np.tile([x + 2.0, y + 2.0], (5, 1)),
                    "det_score": 0.9,
                    "embedding": np.eye(512)[int(p[y, x, 0]) - 1],
                }
                for y, x in np.argwhere(p[:, :, 0])
            ]

        return leg(process)

    image = ff.ImageUnit("image", "a" * 64, fc.SamplingArm.probability, 1.0)
    components = ff.build_psu_components([image], [])
    folds = dict.fromkeys(components.values(), 0)
    gallery = fl.Gallery.enrol({"id-alice": [np.eye(512)[0]], "id-bob": [np.eye(512)[1]]})
    pool = ff.build_nonmated_pool(
        [],
        [image],
        folds,
        fold=0,
        component_map=components,
        exhaustive=True,
        planning_icc=0.05,
        enrolled_identity_ids=frozenset(gallery.prototypes),
    )
    shared = {
        "images": {"image": pixels},
        "image_units": {"image": image},
        "faces": (),
        "gallery": gallery,
        "psu_by_image": components,
        "fold_by_psu": folds,
        "fold_roles": {0: fc.FoldRole.test},
        "exhaustive": True,
        "top_k": 2,
    }
    person = policy is fv.ViewPolicy.person_boxes
    boxes = (fv.PersonBox("p0", (0, 0, 40, 40), "synthetic"), fv.PersonBox("p1", (50, 30, 50, 50), "synthetic"))
    proposal = fv.PersonProposalInput(
        "image",
        image.sha256,
        fv.oriented_pixels_sha256(pixels),
        "opencv-imread-color-exif",
        "ok" if person else "empty",
        "synthetic",
        boxes if person else (),
    )
    views = rt.search_view_policy(
        **shared,
        leg=kernel(fail_call),
        offline=True,
        policy=policy,
        budget=fv.ViewBudget(5, 40000, 5, 100, 100, 30),
        source_proposals={"image": proposal},
    )
    native = fl.search_leg_arm(**shared, leg=kernel(None), arm=fc.Arm.native)
    return views, native, pool.units


def curve_point(records, units):
    return score.curve(records, units=units, thresholds=[0.5], boundary=fc.BoundarySemantics.v2)[0]


@pytest.mark.parametrize("policy", POLICIES, ids=["A", "B", "C"])
@pytest.mark.parametrize("case", sorted(BACKGROUND_CASES))
def test_background_group_alarms_keep_native_s3_multiplicity(policy, case):
    # S3 Build 2: every above-threshold name beyond the first in a unit is spurious;
    # FPI still counts the one fixed background unit once [EVAL-19].
    markers, extra_names = BACKGROUND_CASES[case]
    views, native, units = background_scene(markers, policy)
    evidence = views.evidence["image"]
    assert len(evidence["groups"]) == len(markers)
    assert len(evidence["candidates"]) == sum(SIGHTINGS[policy][m] for m in markers)
    point = curve_point(views.records, units)
    assert point == curve_point(native.records, units)
    assert (point.fpi, point.n_units, point.fpir, point.spurious_names) == (1, 1, 1.0, extra_names)


def test_background_group_rows_share_original_unit_and_walk_back_to_groups():
    views, _, units = background_scene(BACKGROUND_CASES["same_name_two_groups"][0], fv.ViewPolicy.fixed_overlap)
    evidence = views.evidence["image"]
    rows = [r for r in views.records if r.unit_id is not None]
    assert [u.unit_id for u in units] == ["background:image"] and not views.ledger
    assert len(rows) == len(evidence["groups"]) == 2
    for row in rows:
        group = evidence["groups"][int(row.face_id.removeprefix("det:image:background:"))]
        assert row.unit_id == "background:image" and row.cell == ("background", "background")
        assert {a["unit_id"] for a in evidence["assignments"] if a["candidate_index"] in group} == {row.unit_id}
        # Repeated sightings are deduplicated by per-identity maxima, never multiplied.
        assert all(evidence["candidate_hits"][i] == row.top_k for i in group)
        assert row.top_k == (("id-alice", 1.0), ("id-bob", 0.0))


def test_incomplete_source_keeps_every_background_group_row_unavailable():
    markers = BACKGROUND_CASES["same_name_two_groups"][0]
    views, _, _ = background_scene(markers, fv.ViewPolicy.fixed_overlap, fail_call=3)
    evidence = views.evidence["image"]
    assert [r["status"] for r in evidence["receipts"]].count("failed") == 1
    rows = [r for r in views.records if r.unit_id is not None]
    assert len(rows) == len(evidence["groups"]) == 2
    assert all(r.arm_availability is fc.ArmStatus.unavailable for r in rows)
    assert all(r.stage_reached is fc.SearchStage.unavailable for r in rows)


def test_cli_persists_background_group_rows_through_policy_s3_validation(view_files):
    from scripts.eval_harness import firbench_cli as cli

    f = view_files
    source = json.loads(f.source.read_text())
    source["faces"][0]["box"] = [0, 0, 10, 20]
    f.source.write_text(json.dumps(source))
    sha = hashlib.sha256(f.source.read_bytes()).hexdigest()
    f.binding["query_source"]["sha256"] = sha
    f.binding_path.write_text(json.dumps(f.binding))
    decision = json.loads(f.decision.read_text())
    decision["frames"][0]["source_sha256"] = sha
    f.decision.write_text(json.dumps(decision))
    recipe = json.loads(f.policy.read_text())
    f.policy.write_text(json.dumps({**recipe, "policy": "scene_only"}))
    f.policy_sha = hashlib.sha256(f.policy.read_bytes()).hexdigest()
    f.query_outputs = {0: [detection((14, 0, 4, 4)), detection((14, 16, 4, 4))]}
    directory = cli.run_frame(
        frame_id="fake-only",
        decision_path=f.decision,
        legs=(fc.LegKind.sface, fc.LegKind.auraface, fc.LegKind.insightface),
        arms=(fc.Arm.native,),
        subset=None,
        subset_seed=None,
        out_dir=f.private / "run",
        repo_root=f.repo,
        created_at="2026-10-15T08:00:00+00:00",
        view_policy={"path": f.policy.relative_to(f.repo).as_posix(), "sha256": f.policy_sha},
    )
    manifest = json.loads((directory / "manifest.json").read_text())["firbench"]
    for key in manifest["leg_keys"]:
        rows = [json.loads(x) for x in (directory / "legs" / key / "searches.jsonl").read_text().splitlines()]
        background = [r for r in rows if r["unit_id"] == "background:image-0000"]
        assert sorted(r["face_id"] for r in background) == [f"det:image-0000:background:{g}" for g in (0, 1)]
        assert background[0]["top_k"] and background[0]["top_k"] == background[1]["top_k"]
    # Actual cache, IO record and policy S3 validators accept rows sharing one unit.
    assert rt.score_view_policy_run(directory, repo_root=f.repo)["promotion"] == "hold"


def test_cli_multiple_people_failures_and_complete_outcome_ledger(view_files):
    from scripts.eval_harness import firbench_cli as cli

    f = view_files
    source = json.loads(f.source.read_text())
    source["faces"][0]["box"] = [0, 0, 10, 20]
    source["faces"].append(
        {
            "face_id": "stranger",
            "image_id": "image-0000",
            "box": [14, 0, 10, 20],
            "identity_status": "unknown",
            "identity_id": None,
            "cohort": None,
            "annotation": {"occluders": []},
        }
    )
    f.source.write_text(json.dumps(source))
    sha = hashlib.sha256(f.source.read_bytes()).hexdigest()
    f.binding["query_source"]["sha256"] = sha
    f.binding_path.write_text(json.dumps(f.binding))
    decision = json.loads(f.decision.read_text())
    decision["frames"][0]["source_sha256"] = sha
    f.decision.write_text(json.dumps(decision))
    f.query_outputs = {0: [detection((14, 0, 10, 20), 0)], 1: TimeoutError, 2: RuntimeError, 3: FileNotFoundError}
    directory = cli.run_frame(
        frame_id="fake-only",
        decision_path=f.decision,
        legs=(fc.LegKind.sface, fc.LegKind.auraface, fc.LegKind.insightface),
        arms=(fc.Arm.native,),
        subset=None,
        subset_seed=None,
        out_dir=f.private / "run",
        repo_root=f.repo,
        created_at="2026-10-15T08:00:00+00:00",
        view_policy={"path": f.policy.relative_to(f.repo).as_posix(), "sha256": f.policy_sha},
    )
    manifest = json.loads((directory / "manifest.json").read_text())["firbench"]
    for key in manifest["leg_keys"]:
        rows = {
            r["face_id"]: r
            for r in map(json.loads, (directory / "legs" / key / "searches.jsonl").read_text().splitlines())
        }
        for index in range(4):
            assert rows[f"face-{index:04d}"]["stage_reached"] == "missed"
            assert rows[f"face-{index:04d}"]["top_k"] == []
        assert len({r["unit_id"] for r in rows.values() if r["unit_id"]}) == 46
        assert rows["stranger"]["unit_id"] == "stranger"
        ledger = list(map(json.loads, (directory / "ledger" / f"{key}.jsonl").read_text().splitlines()))
        assert len(ledger) == 31
        cache = json.loads((directory / "views" / f.policy_sha / f"{key}.json").read_text())["sources"]
        for image, status in [("image-0001", "timeout"), ("image-0002", "failed"), ("image-0003", "missing")]:
            assert all(r["status"] == status for r in cache[image]["receipts"])
            assert rows[f"det:{image}:background"]["arm_availability"] == "unavailable"
    result = rt.score_view_policy_run(directory, repo_root=f.repo)
    assert result["promotion"] == "hold" and len(result["face_outcomes"]) == 93
    for leg_result in result["legs"]:
        # Calibration refuses missing fit searches instead of borrowing native tau.
        assert leg_result["threshold_source"] == "policy_fit_folds"


def test_policy_person_outcomes_proposal_miss_and_extra_trials_keep_units():
    args = context(lambda _: [detection((0, 0, 20, 20))])
    args["policy"] = fv.ViewPolicy.person_boxes
    p = args["source_proposals"]["image"]
    args["source_proposals"]["image"] = fv.PersonProposalInput(
        p.source_id,
        p.source_sha256,
        p.oriented_pixels_sha256,
        p.orientation,
        "ok",
        p.source_ref,
        (fv.PersonBox("outside", (200, 200, 10, 10), "human"),),
    )
    result = rt.search_view_policy(**args)
    assert [r["status"] for r in result.evidence["image"]["receipts"]] == ["ok", "proposal_miss"]
    assert len(result.ledger) == 2 and len(result.records) == 3
    assert len([r for r in result.records if r.unit_id]) == 1


@pytest.mark.parametrize("status", ["missing", "empty", "failed", "timeout"])
def test_person_json_producer_flows_to_runtime_ledger(status):
    args = context(lambda _: [])
    args["policy"] = fv.ViewPolicy.person_boxes
    p = args["source_proposals"]["image"]
    doc = {
        "schema": "firbench-person-boxes/v1",
        "source_id": p.source_id,
        "source_sha256": p.source_sha256,
        "oriented_pixels_sha256": p.oriented_pixels_sha256,
        "orientation": p.orientation,
        "status": status,
        "source_ref": p.source_ref,
        "boxes": [],
    }
    args["source_proposals"]["image"] = fv.person_proposals_from_json(
        doc, source_id=p.source_id, source_sha256=p.source_sha256, image_bgr=args["images"]["image"]
    )
    result = rt.search_view_policy(**args)
    assert [r["status"] for r in result.evidence["image"]["receipts"]] == ["empty", f"proposal_{status}"]
    assert {r.face_id for r in result.records} == {"alice", "bob", "det:image:background"}
    assert all(r.stage_reached is fc.SearchStage.missed for r in result.records if r.face_id in {"alice", "bob"})
    assert all(
        r.stage_reached is fc.SearchStage.unavailable
        for r in result.records
        if r.arm_availability is fc.ArmStatus.unavailable
    )


def test_s3_policy_cache_tamper_refuses(view_files):
    from scripts.eval_harness import firbench_cli as cli

    f = view_files
    directory = cli.run_frame(
        frame_id="fake-only",
        decision_path=f.decision,
        legs=(fc.LegKind.sface, fc.LegKind.auraface, fc.LegKind.insightface),
        arms=(fc.Arm.native,),
        subset=None,
        subset_seed=None,
        out_dir=f.private / "run",
        repo_root=f.repo,
        created_at="2026-10-15T08:00:00+00:00",
        view_policy={"path": f.policy.relative_to(f.repo).as_posix(), "sha256": f.policy_sha},
    )
    cache = next((directory / "views" / f.policy_sha).glob("*.json"))
    cache.write_text(cache.read_text() + " ")
    with pytest.raises(fc.FrameContractError, match="sha256 mismatch"):
        rt.score_view_policy_run(directory, repo_root=f.repo)
    with pytest.raises(fc.FrameContractError, match="promotion is held"):
        cli.report_run(directory, include_crops=False, repo_root=f.repo)
    with pytest.raises(fc.FrameContractError, match="promotion is held"):
        cli.compare_runs(directory, directory, out_dir=f.private / "compare", treatment=None, repo_root=f.repo)


@pytest.mark.parametrize("producer_error", ["ZeroNormEmbeddingError", "FacePipelineInputError"])
def test_actual_custom_pipeline_failures_stay_in_source_ledger(producer_error):
    from types import SimpleNamespace

    from recognition.application.embedding.manifest import EmbeddingModelManifest
    from recognition.infrastructure.face_pipeline import _common

    def fail(_):
        raise getattr(_common, producer_error)("synthetic actual producer exception")

    model = fl.build_face_pipeline_leg(
        fc.LegKind.sface,
        manifest=EmbeddingModelManifest("fake", "sface", 128, "l2", "cosine"),
        detector=SimpleNamespace(
            detect=lambda batch: [
                [_common.RawDetection(np.array([0, 0, 20, 20]), np.zeros((5, 2)), 1.0)] for _ in batch
            ]
        ),
        aligner=SimpleNamespace(align=lambda p, _: SimpleNamespace(crop=p)),
        embedder=SimpleNamespace(embedding_dim=128, embed=fail),
        weights_sha256="a" * 64,
        preprocessing=None,
        opencv_version="fake-cv",
        ort_version="fake-ort",
    )
    args = context(lambda _: [])
    args["leg"] = model
    args["gallery"] = fl.Gallery.enrol({"id-alice": [np.eye(128)[0]], "id-bob": [np.eye(128)[1]]})
    result = rt.search_view_policy(**args)
    assert len(result.ledger) == 2
    assert all(
        r["status"] == "failed" and r["error_type"] == producer_error for r in result.evidence["image"]["receipts"]
    )
    assert all(r.stage_reached is fc.SearchStage.missed for r in result.records if r.face_id in {"alice", "bob"})
    assert all(
        r.stage_reached is fc.SearchStage.unavailable
        for r in result.records
        if r.arm_availability is fc.ArmStatus.unavailable
    )


def test_unavailable_test_background_does_not_publish_numeric_fpir_curve(view_files):
    from scripts.eval_harness import firbench_cli as cli

    f = view_files
    source = ff.load_population_draft(f.source)
    decision = fc.load_decision_manifest(f.decision)
    components = ff.build_psu_components(source.images, source.faces)
    folds = ff.identity_disjoint_folds(
        components,
        ff.identity_to_component(source.faces, components),
        k=decision.fold_protocol.k,
        seed=decision.fold_protocol.seed,
    )
    image = next(
        i
        for i in source.images
        if folds[components[i.image_id]] == decision.fold_protocol.seed % decision.fold_protocol.k
    )
    f.query_outputs = {int(image.image_id.removeprefix("image-")): TimeoutError}
    directory = cli.run_frame(
        frame_id="fake-only",
        decision_path=f.decision,
        legs=(fc.LegKind.sface, fc.LegKind.auraface, fc.LegKind.insightface),
        arms=(fc.Arm.native,),
        subset=None,
        subset_seed=None,
        out_dir=f.private / "run",
        repo_root=f.repo,
        created_at="2026-10-15T08:00:00+00:00",
        view_policy={"path": f.policy.relative_to(f.repo).as_posix(), "sha256": f.policy_sha},
    )
    output = rt.score_view_policy_run(directory, repo_root=f.repo)
    for model in output["legs"]:
        assert model["calibration"]["status"] == "available"
        assert model["operating_point"]["fpir"]["status"] == "unavailable"
        assert model["curve"] == []
