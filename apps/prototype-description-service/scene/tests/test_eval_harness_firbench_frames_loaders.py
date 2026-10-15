"""S1 loader gate regressions. All names, IDs, paths and hashes are synthetic."""

import json
from pathlib import Path

import pytest

from scripts.eval_harness import firbench_frames as ff
from scripts.eval_harness.firbench_contract import Admissibility, FrameContractError, FrameSpec


def _load(tmp_path: Path, kind: str, payload: dict) -> ff.FrameSource:
    path = tmp_path / f"{kind}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return getattr(ff, f"load_{kind}")(path)


def _manifest(kind: str, names: list[object]) -> dict:
    boxes_key = "face_boxes" if kind == "golden_manifest" else "named_boxes"
    return {
        "entries": [
            {
                "media_id": index,
                "path": f"synthetic/{index}.jpg",
                "sha256": "a" * 64,
                boxes_key: [{"x": 1, "y": 2, "w": 3, "h": 4, "name": name, "source": "operator"}],
            }
            for index, name in enumerate(names, 1)
        ],
        "duplicate_groups": [],
    }


def _population() -> dict:
    return {
        "images": [{
            "image_id": "image-0001", "sha256": "a" * 64,
            "sampling_arm": "probability", "inclusion_probability": 0.5,
            "duplicate_group": None,
        }],
        "faces": [{
            "face_id": "face-0001", "image_id": "image-0001", "box": [1, 2, 3, 4],
            "identity_status": "named", "identity_id": "id-0001", "cohort": None,
        }],
    }


def _frame(source, *, planning_icc=0.1, exhaustive=True):
    return ff.build_frame(
        spec=FrameSpec("frame-fixture", Admissibility.development, False, None, exhaustive),
        images=source.images, faces=source.faces, planning_icc=planning_icc,
        k=2, seed=2406466110, test_fold=0,
        gallery_sha256_by_fold={0: "a" * 64, 1: "b" * 64},
    )


@pytest.mark.parametrize("kind", ["golden_manifest", "corpus_manifest"])
def test_name_whitespace_is_normalized_before_pseudonym_deduplication(tmp_path, kind):
    source = _load(tmp_path, kind, _manifest(kind, ["A", " \tA\n", "B", None]))
    assert [face.identity_id for face in source.faces] == ["id-0001", "id-0001", "id-0002", None]
    assert ff.build_psu_components(source.images, source.faces) == {"1": "1", "2": "1", "3": "3", "4": "4"}
    rendered = json.dumps([face.to_json() for face in source.faces])
    assert '"A"' not in rendered and '"B"' not in rendered


@pytest.mark.parametrize("kind", ["golden_manifest", "corpus_manifest"])
@pytest.mark.parametrize("bad_name", ["", " \t\n", 7, True, ["synthetic-private-name"], {"synthetic-private-name": 1}])
def test_invalid_names_refuse_without_echoing_names(tmp_path, kind, bad_name):
    with pytest.raises(FrameContractError) as caught:
        _load(tmp_path, kind, _manifest(kind, ["synthetic-private-name", bad_name]))
    assert "synthetic-private-name" not in str(caught.value)
    assert caught.value.__cause__ is None


def test_probability_one_is_valid_without_widening_planning_icc(tmp_path):
    payload = _population()
    payload["images"][0]["inclusion_probability"] = 1
    payload["images"].append({**payload["images"][0], "image_id": "image-0002", "sha256": "b" * 64})
    source = _load(tmp_path, "population_draft", payload)
    assert source.images[0].inclusion_probability == 1
    ff.frame_json(_frame(source))  # Includes validation against the frozen frame-v1 schema.
    with pytest.raises(FrameContractError):
        _frame(source, planning_icc=1)
    with pytest.raises(FrameContractError):
        _frame(source, planning_icc=0)


@pytest.mark.parametrize("probability", [0, -0.1, 1.01, True, "0.5", [], float("nan"), float("inf"), 10**400])
def test_population_probability_refuses_invalid_values(tmp_path, probability):
    payload = _population()
    payload["images"][0]["inclusion_probability"] = probability
    with pytest.raises(FrameContractError):
        _load(tmp_path, "population_draft", payload)


@pytest.mark.parametrize("kind", ["golden_manifest", "corpus_manifest"])
@pytest.mark.parametrize("coordinate", [None, "3", "synthetic-private-name", True, [], {}, float("nan"), float("inf"), 10**400])
def test_manifest_geometry_refuses_without_coercion_or_name_leaks(tmp_path, kind, coordinate):
    payload = _manifest(kind, ["synthetic-private-name"])
    key = "face_boxes" if kind == "golden_manifest" else "named_boxes"
    payload["entries"][0][key][0]["x"] = coordinate
    with pytest.raises(FrameContractError) as caught:
        _load(tmp_path, kind, payload)
    assert "synthetic-private-name" not in str(caught.value)


@pytest.mark.parametrize("box", [None, 4, "1234", {}, [1, 2, 3], [1, 2, 0, 4], [1, 2, 3, -1]])
def test_gt_face_rejects_malformed_geometry_as_contract_error(box):
    with pytest.raises(FrameContractError):
        ff.GtFace("face-0001", "image-0001", box, "unknown", None)


@pytest.mark.parametrize("cohort", [{"typo": "value"}, {"sex": []}, [], False])
def test_population_cohort_refuses_malformed_objects(tmp_path, cohort):
    payload = _population()
    payload["faces"][0]["cohort"] = cohort
    with pytest.raises(FrameContractError):
        _load(tmp_path, "population_draft", payload)


@pytest.mark.parametrize("annotation", [
    {"visibility": {"typo": "visible"}},
    {"visibility": {"nose": []}},
    {"visibility": {"nose": "invalid"}},
    {"visibility": []}, {"visibility": False}, {"visibility": ""},
    {"occluders": [[]]}, {"occluders": [True]}, {"occluders": "mask"},
    {"annotation_tier": []}, {"exhaustive": 1}, {"typo": None},
])
def test_population_annotation_refuses_malformed_fields(tmp_path, annotation):
    payload = _population()
    payload["faces"][0]["annotation"] = annotation
    with pytest.raises(FrameContractError):
        _load(tmp_path, "population_draft", payload)


@pytest.mark.parametrize("occluders,expected", [(None, None), ([], []), (["mask", "mask"], ["mask"])])
def test_population_preserves_unknown_clear_and_independent_label_completeness(tmp_path, occluders, expected):
    payload = _population()
    payload["faces"][0]["annotation"] = {
        "occluders": occluders, "visibility": {"nose": "uncertain"},
        "annotation_tier": "b", "exhaustive": None,
    }
    face = _load(tmp_path, "population_draft", payload).faces[0]
    assert face.annotation.to_json()["occluders"] == expected
    assert face.annotation.visibility.nose == "uncertain"
    assert face.annotation.visibility.left_eye is None
    assert face.annotation.exhaustive is None


def test_exhaustive_pixel_labels_do_not_establish_frame_box_coverage(tmp_path):
    payload = _population()
    payload["faces"][0]["annotation"] = {"annotation_tier": "b", "exhaustive": True}
    source = _load(tmp_path, "population_draft", payload)
    with pytest.raises(FrameContractError, match="exhaustive"):
        _frame(source, exhaustive=None)


@pytest.mark.parametrize("location", ["document", "image", "face"])
def test_population_rejects_unknown_keys(tmp_path, location):
    payload = _population()
    target = {"document": payload, "image": payload["images"][0], "face": payload["faces"][0]}[location]
    target["typo"] = None
    with pytest.raises(FrameContractError):
        _load(tmp_path, "population_draft", payload)


@pytest.mark.parametrize("mode", ["roster_only", "exhaustive", None])
def test_golden_rejects_persisted_per_entry_annotation_mode(tmp_path, mode):
    payload = _manifest("golden_manifest", ["A"])
    payload["annotation_mode"] = "roster_only"
    payload["entries"][0]["annotation_mode"] = mode
    with pytest.raises(FrameContractError, match="annotation_mode"):
        _load(tmp_path, "golden_manifest", payload)


@pytest.mark.parametrize("mode", ["roster_only", "exhaustive"])
def test_golden_document_mode_does_not_invent_face_annotations_or_coverage(tmp_path, mode):
    payload = _manifest("golden_manifest", ["A"])
    payload["annotation_mode"] = mode
    source = _load(tmp_path, "golden_manifest", payload)
    assert source.faces[0].annotation == ff.FaceAnnotation()
    assert not hasattr(source, "exhaustive")
