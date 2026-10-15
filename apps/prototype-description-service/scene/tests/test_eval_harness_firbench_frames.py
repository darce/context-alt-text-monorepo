"""FIRBENCH-1 S1 frames: PSU components, design effect, folds, non-mated pool.

Every identity, name, path and hash here is synthetic. Known answers are exact
integers or Fraction oracles; float rates use a 1e-12 tolerance.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from fractions import Fraction
from pathlib import Path

import pytest

from scripts.eval_harness import firbench_contract as fc
from scripts.eval_harness import firbench_frames as ff

TOL = 1e-12
ICC = 0.10


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _img(
    image_id: str,
    *,
    arm: fc.SamplingArm = fc.SamplingArm.challenge,
    pi: float | None = None,
    dup: str | None = None,
    session: str | None = None,
    parent: str | None = None,
) -> ff.ImageUnit:
    return ff.ImageUnit(
        image_id=image_id,
        sha256=_sha(image_id),
        sampling_arm=arm,
        inclusion_probability=pi,
        duplicate_group=dup,
        session_id=session,
        synthetic_parent_id=parent,
    )


def _named(face_id: str, image_id: str, identity_id: str) -> ff.GtFace:
    return ff.GtFace(
        face_id=face_id,
        image_id=image_id,
        box=(1.0, 2.0, 30.0, 40.0),
        identity_status=fc.IdentityStatus.named,
        identity_id=identity_id,
    )


def _unknown(face_id: str, image_id: str) -> ff.GtFace:
    return ff.GtFace(
        face_id=face_id,
        image_id=image_id,
        box=(5.0, 6.0, 20.0, 20.0),
        identity_status=fc.IdentityStatus.unknown,
        identity_id=None,
    )


def _unresolved(face_id: str, image_id: str) -> ff.GtFace:
    return ff.GtFace(
        face_id=face_id,
        image_id=image_id,
        box=(0.0, 0.0, 9.0, 9.0),
        identity_status=fc.IdentityStatus.unresolved,
        identity_id=None,
    )


def _spec(*, exhaustive: bool | None = True, sealed: bool = False) -> fc.FrameSpec:
    return fc.FrameSpec(
        frame_id="frame-fixture-v1",
        admissibility=fc.Admissibility.development,
        sealed=sealed,
        source_sha256=None,
        exhaustive=exhaustive,
    )


def _gallery(k: int) -> dict[int, str]:
    return {fold: _sha(f"gallery-{fold}") for fold in range(k)}


def _pipeline(images, faces):
    component_map = ff.build_psu_components(images, faces)
    identity_map = ff.identity_to_component(faces, component_map)
    return component_map, identity_map


# --- known answers: M-tilde and design effect ---------------------------------


def test_size_weighted_mean_and_deff_known_answer() -> None:
    sizes = [1, 1, 2, 4]
    assert ff.size_weighted_mean(sizes) == pytest.approx(float(Fraction(22, 8)), abs=TOL)
    assert ff.size_weighted_mean(sizes) == pytest.approx(2.75, abs=TOL)
    assert ff.design_effect(sizes, ICC) == pytest.approx(1.175, abs=TOL)


def test_components_of_zero_faces_are_excluded_from_size_statistics() -> None:
    sizes = [0, 1, 1, 2, 4]
    assert ff.size_weighted_mean(sizes) == pytest.approx(2.75, abs=TOL)


def test_effective_n_is_a_float_ratio() -> None:
    assert ff.effective_n(10, 1.175) == pytest.approx(10 / 1.175, abs=TOL)


def test_face_count_m_is_used_not_image_count() -> None:
    images = [_img("image-0001")]
    faces = [_named(f"face-{i}", "image-0001", f"id-000{i}") for i in range(1, 4)]
    component_map, _ = _pipeline(images, faces)
    sizes = ff.psu_face_counts(component_map, faces)
    assert sizes == {"image-0001": 3}
    assert ff.design_effect(list(sizes.values()), ICC) == pytest.approx(1 + (3 - 1) * ICC, abs=TOL)
    assert ff.design_effect(list(sizes.values()), ICC) != pytest.approx(1 + (1 - 1) * ICC, abs=TOL)


# --- observed ICC -------------------------------------------------------------


def test_all_zero_outcomes_return_null_icc() -> None:
    estimate = ff.estimate_icc({"psu-a": [0, 0], "psu-b": [0, 0, 0]})
    assert estimate.icc is None
    assert estimate.n_psu == 2


def test_all_one_outcomes_return_null_icc() -> None:
    estimate = ff.estimate_icc({"psu-a": [1, 1], "psu-b": [1]})
    assert estimate.icc is None


def test_icc_known_answer_perfect_clustering() -> None:
    estimate = ff.estimate_icc({"psu-a": [1, 1], "psu-b": [0, 0]})
    assert estimate.icc == pytest.approx(1.0, abs=TOL)
    assert estimate.n_psu == 2


def test_icc_is_floored_at_zero() -> None:
    estimate = ff.estimate_icc({"psu-a": [1, 0], "psu-b": [1, 0]})
    assert estimate.icc == 0.0


# --- PSU components -----------------------------------------------------------


def test_shared_identities_and_duplicate_pairs_join_one_psu() -> None:
    images = [
        _img("image-0001"),
        _img("image-0002"),
        _img("image-0003"),
        _img("image-0004", dup="dup-1"),
        _img("image-0005", dup="dup-1"),
        _img("image-0006"),
    ]
    faces = [
        _named("face-1", "image-0001", "id-0001"),
        _named("face-2", "image-0002", "id-0001"),
        _named("face-3", "image-0002", "id-0002"),
        _named("face-4", "image-0003", "id-0002"),
    ]
    component_map = ff.build_psu_components(images, faces)
    assert component_map["image-0001"] == component_map["image-0002"] == component_map["image-0003"]
    assert component_map["image-0004"] == component_map["image-0005"] == "image-0004"
    assert component_map["image-0006"] == "image-0006"


def test_psu_id_is_smallest_image_id_in_component() -> None:
    images = [_img("image-0009"), _img("image-0002")]
    faces = [_named("face-1", "image-0009", "id-0001"), _named("face-2", "image-0002", "id-0001")]
    component_map = ff.build_psu_components(images, faces)
    assert set(component_map.values()) == {"image-0002"}


def test_unknown_face_in_shared_image_adds_no_identity_edge() -> None:
    images = [_img("image-0001"), _img("image-0002"), _img("image-0003")]
    named = [_named("face-1", "image-0001", "id-0001"), _named("face-2", "image-0002", "id-0001")]
    with_unknown = named + [_unknown("face-3", "image-0001"), _unknown("face-4", "image-0003")]
    base_map = ff.build_psu_components(images, named)
    unknown_map = ff.build_psu_components(images, with_unknown)
    assert base_map == unknown_map
    assert unknown_map["image-0001"] == unknown_map["image-0002"]
    assert unknown_map["image-0003"] == "image-0003"


def test_unresolved_face_adds_no_identity_edge() -> None:
    images = [_img("image-0001"), _img("image-0002")]
    faces = [_unresolved("face-1", "image-0001"), _unresolved("face-2", "image-0002")]
    component_map = ff.build_psu_components(images, faces)
    assert component_map == {"image-0001": "image-0001", "image-0002": "image-0002"}


def test_image_without_gt_face_is_its_own_component() -> None:
    images = [_img("image-0001"), _img("image-0002")]
    component_map = ff.build_psu_components(images, [])
    assert component_map == {"image-0001": "image-0001", "image-0002": "image-0002"}


def test_shared_session_joins_components() -> None:
    images = [_img("image-0001", session="session-0001"), _img("image-0002", session="session-0001")]
    component_map = ff.build_psu_components(images, [])
    assert component_map["image-0001"] == component_map["image-0002"]


def test_synthetic_sibling_joins_parent_component_and_fold() -> None:
    images = [
        _img("image-0001"),
        _img("image-0002"),
        _img("image-0003", parent="image-0001"),
    ]
    faces = [
        _named("face-1", "image-0001", "id-0001"),
        _named("face-2", "image-0002", "id-0002"),
        _named("face-3", "image-0003", "id-0003"),
    ]
    component_map, identity_map = _pipeline(images, faces)
    assert component_map["image-0003"] == component_map["image-0001"]
    folds = ff.identity_disjoint_folds(component_map, identity_map, k=2, seed=7)
    assert folds[component_map["image-0003"]] == folds[component_map["image-0001"]]


def test_synthetic_parent_must_exist() -> None:
    images = [_img("image-0003", parent="image-missing")]
    with pytest.raises(fc.FrameContractError):
        ff.build_psu_components(images, [])


def test_face_referencing_unknown_image_is_refused() -> None:
    with pytest.raises(fc.FrameContractError):
        ff.build_psu_components([_img("image-0001")], [_named("face-1", "image-9999", "id-0001")])


def test_image_arm_and_inclusion_probability_are_checked() -> None:
    with pytest.raises(fc.FrameContractError):
        _img("image-0001", arm=fc.SamplingArm.probability, pi=None)
    with pytest.raises(fc.FrameContractError):
        _img("image-0001", arm=fc.SamplingArm.challenge, pi=0.5)
    assert _img("image-0001", arm=fc.SamplingArm.probability, pi=0.25).inclusion_probability == 0.25


# --- folds --------------------------------------------------------------------


def test_identities_co_occurring_in_one_image_land_in_one_fold() -> None:
    images = [_img("image-0001"), _img("image-0002")]
    faces = [
        _named("face-1", "image-0001", "id-0001"),
        _named("face-2", "image-0001", "id-0002"),
        _named("face-3", "image-0002", "id-0003"),
    ]
    component_map, identity_map = _pipeline(images, faces)
    folds = ff.identity_disjoint_folds(component_map, identity_map, k=2, seed=11)
    assert identity_map["id-0001"] == identity_map["id-0002"]
    assert folds[identity_map["id-0001"]] == folds[identity_map["id-0002"]]


def _synthetic_dataset(count: int = 24) -> tuple[list[ff.ImageUnit], list[ff.GtFace]]:
    images = []
    faces = []
    for index in range(count):
        image_id = f"image-{index:04d}"
        images.append(_img(image_id))
        identity = f"id-{index % 9:04d}"
        faces.append(_named(f"face-{index:04d}", image_id, identity))
        if index % 4 == 0:
            faces.append(_unknown(f"face-u{index:04d}", image_id))
    return images, faces


def test_folds_are_identity_disjoint_and_never_split_a_psu() -> None:
    images, faces = _synthetic_dataset()
    component_map, identity_map = _pipeline(images, faces)
    folds = ff.identity_disjoint_folds(component_map, identity_map, k=5, seed=2406466110)
    assert set(folds) == set(component_map.values())
    assert set(folds.values()) == set(range(5))
    fold_by_identity: dict[str, set[int]] = {}
    for face in faces:
        if face.identity_id is None:
            continue
        fold_by_identity.setdefault(face.identity_id, set()).add(folds[component_map[face.image_id]])
    assert all(len(holders) == 1 for holders in fold_by_identity.values())
    for identity, holders in fold_by_identity.items():
        assert holders == {folds[identity_map[identity]]}
    for image_id, psu_id in component_map.items():
        assert folds[psu_id] == folds[component_map[image_id]]


def test_fold_assignment_is_deterministic_for_a_seed() -> None:
    images, faces = _synthetic_dataset()
    component_map, identity_map = _pipeline(images, faces)
    first = ff.identity_disjoint_folds(component_map, identity_map, k=5, seed=99)
    second = ff.identity_disjoint_folds(component_map, identity_map, k=5, seed=99)
    assert first == second


def test_fold_count_above_psu_count_is_refused() -> None:
    images = [_img("image-0001"), _img("image-0002")]
    component_map, identity_map = _pipeline(images, [])
    with pytest.raises(fc.FrameContractError):
        ff.identity_disjoint_folds(component_map, identity_map, k=3, seed=1)


# --- non-mated pool -----------------------------------------------------------


def test_pool_has_one_background_unit_per_image_and_no_face_image_has_one() -> None:
    images = [_img("image-0001"), _img("image-0002")]
    faces = [_named("face-1", "image-0001", "id-0001")]
    component_map, identity_map = _pipeline(images, faces)
    folds = ff.identity_disjoint_folds(component_map, identity_map, k=2, seed=3)
    pools = [
        ff.build_nonmated_pool(
            faces,
            images,
            folds,
            fold=fold,
            component_map=component_map,
            exhaustive=True,
            planning_icc=ICC,
        )
        for fold in (0, 1)
    ]
    unit_ids = sorted(unit.unit_id for pool in pools for unit in pool.units)
    # The held-out named face is non-mated in its own fold; background units cover every image.
    assert unit_ids == ["background:image-0001", "background:image-0002", "face-1"]


def test_unknown_faces_join_pool_of_their_component_fold() -> None:
    images = [_img("image-0001"), _img("image-0002")]
    faces = [_unknown("face-u1", "image-0001"), _unknown("face-u2", "image-0002")]
    component_map, identity_map = _pipeline(images, faces)
    folds = ff.identity_disjoint_folds(component_map, identity_map, k=2, seed=5)
    total = 0
    for fold in (0, 1):
        pool = ff.build_nonmated_pool(
            faces, images, folds, fold=fold, component_map=component_map, exhaustive=True, planning_icc=ICC
        )
        assert all(unit.fold == fold for unit in pool.units)
        total += pool.n_units
    assert total == 4


def test_unresolved_face_never_enters_pool_and_is_refused() -> None:
    images = [_img("image-0001")]
    faces = [_unresolved("face-r1", "image-0001")]
    component_map, _ = _pipeline(images, faces)
    folds = {component_map["image-0001"]: 0}
    with pytest.raises(fc.FrameContractError):
        ff.build_nonmated_pool(
            faces, images, folds, fold=0, component_map=component_map, exhaustive=True, planning_icc=ICC
        )


def test_pool_is_refused_without_exhaustive_frame() -> None:
    images = [_img("image-0001")]
    component_map, _ = _pipeline(images, [])
    folds = {component_map["image-0001"]: 0}
    with pytest.raises(fc.FrameContractError):
        ff.build_nonmated_pool(
            [], images, folds, fold=0, component_map=component_map, exhaustive=False, planning_icc=ICC
        )


def test_pool_refuses_malformed_component_and_fold_coverage() -> None:
    images = [_img("image-0001"), _img("image-0002")]
    component_map = {"image-0001": "image-0001"}
    with pytest.raises(fc.FrameContractError):
        ff.build_nonmated_pool(
            [], images, {"image-0001": 0}, fold=0, component_map=component_map, exhaustive=True, planning_icc=ICC
        )
    with pytest.raises(fc.FrameContractError):
        ff.build_nonmated_pool(
            [],
            images[:1],
            {},
            fold=0,
            component_map={"image-0001": "image-0001"},
            exhaustive=True,
            planning_icc=ICC,
        )


def test_pool_takes_no_detector_argument_and_ignores_detector_output() -> None:
    parameters = inspect.signature(ff.build_nonmated_pool).parameters
    assert not {"detector", "detections", "detector_output"} & set(parameters)
    images, faces = _synthetic_dataset()
    component_map, identity_map = _pipeline(images, faces)
    folds = ff.identity_disjoint_folds(component_map, identity_map, k=3, seed=8)
    first = ff.build_nonmated_pool(
        faces, images, folds, fold=0, component_map=component_map, exhaustive=True, planning_icc=ICC
    )
    second = ff.build_nonmated_pool(
        faces, images, folds, fold=0, component_map=component_map, exhaustive=True, planning_icc=ICC
    )
    assert first == second


def test_pool_deff_uses_units_psu_structure_at_planning_icc() -> None:
    images = [_img("image-0001"), _img("image-0002")]
    faces = [_unknown("face-u1", "image-0001"), _unknown("face-u2", "image-0001")]
    component_map, identity_map = _pipeline(images, faces)
    folds = {component_map["image-0001"]: 0, component_map["image-0002"]: 0}
    pool = ff.build_nonmated_pool(
        faces, images, folds, fold=0, component_map=component_map, exhaustive=True, planning_icc=ICC
    )
    assert pool.n_units == 4
    expected_deff = ff.design_effect([3, 1], ICC)
    assert pool.n_nonmated_eff == pytest.approx(4 / expected_deff, abs=TOL)


# --- loaders ------------------------------------------------------------------


def _write(tmp_path: Path, name: str, payload: object) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _golden_payload(*, drop: str | None = None) -> dict:
    box = {"x": 1.0, "y": 2.0, "w": 10.0, "h": 12.0, "name": "name-alpha", "source": "operator"}
    unnamed = {"x": 3.0, "y": 4.0, "w": 8.0, "h": 9.0, "name": None, "source": "detector"}
    if drop:
        box.pop(drop)
    entry = {
        "path": "synthetic/0001.jpg",
        "sha256": _sha("golden-0001"),
        "media_id": 1,
        "face_count": 2,
        "face_boxes": [box, unnamed],
    }
    return {"manifest_version": 2, "roster": [], "entries": [entry]}


def test_golden_loader_maps_named_and_unnamed_boxes(tmp_path: Path) -> None:
    source = ff.load_golden_manifest(_write(tmp_path, "golden.json", _golden_payload()))
    assert [image.image_id for image in source.images] == ["1"]
    assert source.images[0].sampling_arm is fc.SamplingArm.challenge
    assert source.images[0].inclusion_probability is None
    statuses = sorted(face.identity_status.value for face in source.faces)
    assert statuses == ["named", "unknown"]
    named = next(face for face in source.faces if face.identity_status is fc.IdentityStatus.named)
    assert named.identity_id == "id-0001"
    assert all(face.annotation == ff.FaceAnnotation() for face in source.faces)


def test_loader_rejects_manifest_missing_identity_field(tmp_path: Path) -> None:
    path = _write(tmp_path, "golden-missing-name.json", _golden_payload(drop="name"))
    with pytest.raises(fc.FrameContractError, match="name"):
        ff.load_golden_manifest(path)


def test_corpus_loader_rejects_missing_top_level_key(tmp_path: Path) -> None:
    payload = {"manifest_version": 1, "entries": []}
    path = _write(tmp_path, "corpus-missing.json", payload)
    with pytest.raises(fc.FrameContractError):
        ff.load_corpus_manifest(path)


def test_corpus_loader_maps_duplicate_groups_and_named_boxes(tmp_path: Path) -> None:
    entries = []
    for media_id, name in ((10, "name-beta"), (11, "name-beta"), (12, "name-gamma")):
        entries.append(
            {
                "media_id": media_id,
                "path": f"synthetic/{media_id}.jpg",
                "sha256": _sha(f"corpus-{media_id}"),
                "named_boxes": [{"x": 1.0, "y": 1.0, "w": 5.0, "h": 6.0, "name": name, "source": "workbench"}],
                "detected_boxes": [],
            }
        )
    payload = {
        "manifest_version": 1,
        "duplicate_groups": [["synthetic/10.jpg", "synthetic/11.jpg"]],
        "entries": entries,
    }
    source = ff.load_corpus_manifest(_write(tmp_path, "corpus.json", payload))
    groups = {image.image_id: image.duplicate_group for image in source.images}
    assert groups["10"] == groups["11"] is not None
    assert groups["12"] is None
    component_map = ff.build_psu_components(source.images, source.faces)
    assert component_map["10"] == component_map["11"]


def test_population_loader_requires_identity_status(tmp_path: Path) -> None:
    payload = {
        "images": [
            {
                "image_id": "image-0001",
                "sha256": _sha("population-1"),
                "sampling_arm": "probability",
                "inclusion_probability": 0.5,
                "duplicate_group": None,
            }
        ],
        "faces": [
            {
                "face_id": "face-0001",
                "image_id": "image-0001",
                "box": [1, 2, 3, 4],
                "identity_id": None,
                "cohort": None,
            }
        ],
    }
    with pytest.raises(fc.FrameContractError, match="identity_status"):
        ff.load_population_draft(_write(tmp_path, "population.json", payload))


def test_loader_wraps_missing_file_and_malformed_json_as_frame_error(tmp_path: Path) -> None:
    with pytest.raises(fc.FrameContractError):
        ff.load_golden_manifest(tmp_path / "absent.json")
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{not json", encoding="utf-8")
    with pytest.raises(fc.FrameContractError):
        ff.load_corpus_manifest(malformed)


# --- annotation ---------------------------------------------------------------


def test_annotation_defaults_to_unknown_and_preserves_null_versus_empty_occluders() -> None:
    unknown = ff.FaceAnnotation()
    assert unknown.occluders is None
    explicit_none = ff.FaceAnnotation(occluders=())
    assert explicit_none.occluders == ()
    assert unknown != explicit_none


def test_annotation_enums_match_frame_schema() -> None:
    schema = json.loads((fc._SCHEMA_DIR / "frame-v1.json").read_text(encoding="utf-8"))
    annotation = schema["$defs"]["face_annotation"]
    occluder_enum = set(annotation["properties"]["occluders"]["items"]["enum"])
    region_enum = set(schema["$defs"]["region_visibility"]["enum"]) - {None}
    assert frozenset(occluder_enum) == ff.OCCLUDER_VALUES
    assert frozenset(region_enum) == ff.REGION_VALUES


def test_annotation_exhaustive_true_requires_tier_b() -> None:
    with pytest.raises(fc.FrameContractError):
        ff.FaceAnnotation(annotation_tier="a", exhaustive=True)
    assert ff.FaceAnnotation(annotation_tier="b", exhaustive=None).exhaustive is None


# --- frame --------------------------------------------------------------------


def _frame_inputs(k: int = 3, seed: int = 2468935812):
    images, faces = _synthetic_dataset()
    return {
        "spec": _spec(),
        "images": images,
        "faces": faces,
        "planning_icc": ICC,
        "k": k,
        "seed": seed,
        "test_fold": 0,
        "gallery_sha256_by_fold": _gallery(k),
    }


def test_same_inputs_and_seed_give_byte_identical_frame_json_that_validates() -> None:
    first = ff.frame_json(ff.build_frame(**_frame_inputs()))
    second = ff.frame_json(ff.build_frame(**_frame_inputs()))
    assert first == second
    fc.validate_interchange("frame-v1", json.loads(first))


def test_frame_roles_and_counts_are_set_per_rotation() -> None:
    frame = ff.build_frame(**_frame_inputs(k=3))
    assert frame.fold_roles == {0: fc.FoldRole.test, 1: fc.FoldRole.fit, 2: fc.FoldRole.fit}
    assert frame.sampling_arm_counts == {"probability": 0, "challenge": 24}
    pool = ff.build_nonmated_pool(
        frame.faces,
        frame.images,
        frame.folds,
        fold=0,
        component_map=frame.psu_map,
        exhaustive=True,
        planning_icc=ICC,
    )
    assert frame.n_units == pool.n_units
    assert frame.n_nonmated_eff == pytest.approx(pool.n_nonmated_eff, abs=TOL)


def test_frame_refuses_non_exhaustive_spec() -> None:
    inputs = _frame_inputs()
    inputs["spec"] = _spec(exhaustive=None)
    with pytest.raises(fc.FrameContractError):
        ff.build_frame(**inputs)


def test_frame_uses_planning_icc_and_observed_icc_does_not_change_it() -> None:
    frame = ff.build_frame(**_frame_inputs())
    assert frame.planning_icc == ICC
    face_sizes = list(ff.psu_face_counts(frame.psu_map, frame.faces).values())
    assert frame.design_effect == pytest.approx(ff.design_effect(face_sizes, ICC), abs=TOL)
    assert frame.n_eff == pytest.approx(len(frame.faces) / frame.design_effect, abs=TOL)
    first_observed = ff.estimate_icc({"psu-a": [1, 1], "psu-b": [0, 0]})
    second_observed = ff.estimate_icc({"psu-a": [1, 0, 0], "psu-b": [1, 1, 0]})
    assert first_observed.icc != second_observed.icc
    again = ff.build_frame(**_frame_inputs())
    assert again.design_effect == frame.design_effect
    assert again.n_eff == frame.n_eff


def test_frame_refuses_gallery_hash_missing_for_a_fold() -> None:
    inputs = _frame_inputs(k=3)
    inputs["gallery_sha256_by_fold"] = {0: _sha("g0"), 1: _sha("g1")}
    with pytest.raises(fc.FrameContractError):
        ff.build_frame(**inputs)


def test_frame_with_unresolved_face_is_refused_for_non_mated_counts() -> None:
    inputs = _frame_inputs()
    inputs["faces"] = list(inputs["faces"]) + [_unresolved("face-r9", "image-0001")]
    with pytest.raises(fc.FrameContractError):
        ff.build_frame(**inputs)


def test_frame_identity_folds_cover_every_identity() -> None:
    frame = ff.build_frame(**_frame_inputs())
    identities = {face.identity_id for face in frame.faces if face.identity_id is not None}
    assert set(frame.identity_fold) == identities


def test_end_to_end_from_corpus_manifest_to_validated_frame_json(tmp_path: Path) -> None:
    """Fake-only end-to-end check: synthetic manifest, loader, frame, canonical JSON, frame-v1 validation."""
    entries = []
    named = {10: "name-beta", 11: "name-beta", 12: "name-gamma"}
    for media_id in (10, 11, 12, 13):
        boxes = []
        if media_id in named:
            boxes = [{"x": 1.0, "y": 1.0, "w": 5.0, "h": 6.0, "name": named[media_id], "source": "workbench"}]
        entries.append(
            {
                "media_id": media_id,
                "path": f"synthetic/{media_id}.jpg",
                "sha256": _sha(f"corpus-{media_id}"),
                "named_boxes": boxes,
                "detected_boxes": [],
            }
        )
    payload = {
        "manifest_version": 1,
        "duplicate_groups": [["synthetic/10.jpg", "synthetic/11.jpg"]],
        "entries": entries,
    }
    source = ff.load_corpus_manifest(_write(tmp_path, "corpus.json", payload))
    frame = ff.build_frame(
        spec=_spec(),
        images=source.images,
        faces=source.faces,
        planning_icc=ICC,
        k=2,
        seed=5,
        test_fold=0,
        gallery_sha256_by_fold=_gallery(2),
    )
    text = ff.frame_json(frame)
    decoded = json.loads(text)
    fc.validate_interchange("frame-v1", decoded)
    assert decoded["sampling_arm_counts"] == {"probability": 0, "challenge": 4}
    assert decoded["n_units"] == frame.n_units >= 1
    assert "name-" not in text
    assert {entry["identity_id"] for entry in decoded["identity_folds"]} == {"id-0001", "id-0002"}
