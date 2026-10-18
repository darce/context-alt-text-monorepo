"""Frame annotation wire contract; all labels and references here are synthetic.

No FaceInstance producer exists yet. Exercise the real interchange validator
against the assessment field table, S7 rubric and MCP16735, without mocks.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts.eval_harness import firbench_contract as fc

FIXTURE = Path(__file__).parent / "fixtures" / "firbench_interchange_v1" / "frame-v1.json"
REGIONS = ("left_eye", "right_eye", "nose", "mouth")
ANNOTATION_FIELDS = (
    "occluders",
    "visibility",
    "annotation_tier",
    "exhaustive",
    "provenance_ref",
    "rule_id",
    "observation_ref",
    "qc_ref",
)


def _unknown_annotation() -> dict:
    return {
        "occluders": None,
        "visibility": dict.fromkeys(REGIONS),
        "annotation_tier": None,
        "exhaustive": None,
        "provenance_ref": None,
        "rule_id": None,
        "observation_ref": None,
        "qc_ref": None,
    }


def _frame() -> dict:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["faces"][0]["annotation"] = _unknown_annotation()
    return payload


def test_frame_accepts_explicit_unknown_annotations_without_changing_box_exhaustiveness() -> None:
    payload = _frame()
    before = copy.deepcopy(payload)
    fc.validate_interchange("frame-v1", payload)
    assert payload == before
    assert payload["exhaustive"] is True
    assert payload["faces"][0]["annotation"]["exhaustive"] is None


def test_committed_synthetic_fixture_carries_explicit_unknowns() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    fc.validate_interchange("frame-v1", payload)
    assert payload["faces"][0]["annotation"] == _unknown_annotation()


@pytest.mark.parametrize(
    "occluders",
    [
        None,
        [],
        ["mask"],
        ["sunglasses"],
        ["mask", "sunglasses"],
        ["clear_glasses", "hand", "phone", "hair", "other_object", "mixed"],
    ],
)
def test_frame_accepts_face_specific_multilabel_occluders(occluders: list[str] | None) -> None:
    payload = _frame()
    payload["faces"][0]["annotation"]["occluders"] = occluders
    fc.validate_interchange("frame-v1", payload)


@pytest.mark.parametrize("visibility", [None, "visible", "occluded", "self_occluded", "out_of_frame", "uncertain"])
def test_frame_accepts_anatomical_visibility_without_forcing_certainty(visibility: str | None) -> None:
    payload = _frame()
    payload["faces"][0]["annotation"]["visibility"] = dict.fromkeys(REGIONS, visibility)
    fc.validate_interchange("frame-v1", payload)


@pytest.mark.parametrize(
    "tier,exhaustive", [(None, None), (None, False), ("a", None), ("a", False), ("b", None), ("b", False), ("b", True)]
)
@pytest.mark.parametrize("box_exhaustive", [None, False, True])
def test_label_tier_never_infers_or_erases_box_exhaustiveness(
    tier: str | None, exhaustive: bool | None, box_exhaustive: bool | None
) -> None:
    payload = _frame()
    payload["exhaustive"] = box_exhaustive
    payload["faces"][0]["annotation"].update(annotation_tier=tier, exhaustive=exhaustive)
    fc.validate_interchange("frame-v1", payload)
    assert payload["exhaustive"] is box_exhaustive


@pytest.mark.parametrize("tier", [None, "a"])
def test_only_tier_b_can_claim_exhaustive_pixel_labels(tier: str | None) -> None:
    payload = _frame()
    payload["faces"][0]["annotation"].update(annotation_tier=tier, exhaustive=True)
    with pytest.raises(fc.FrameContractError, match="exhaustive"):
        fc.validate_interchange("frame-v1", payload)


@pytest.mark.parametrize("field", ANNOTATION_FIELDS)
def test_absent_annotation_fields_are_rejected_instead_of_defaulting_clear(field: str) -> None:
    payload = _frame()
    del payload["faces"][0]["annotation"][field]
    with pytest.raises(fc.FrameContractError, match=field):
        fc.validate_interchange("frame-v1", payload)


def test_absent_annotation_object_is_rejected() -> None:
    payload = _frame()
    del payload["faces"][0]["annotation"]
    with pytest.raises(fc.FrameContractError, match="annotation"):
        fc.validate_interchange("frame-v1", payload)


@pytest.mark.parametrize("region", REGIONS)
def test_absent_region_is_rejected_instead_of_defaulting_visible(region: str) -> None:
    payload = _frame()
    del payload["faces"][0]["annotation"]["visibility"][region]
    with pytest.raises(fc.FrameContractError, match=region):
        fc.validate_interchange("frame-v1", payload)


@pytest.mark.parametrize(
    "field,value",
    [
        ("occluders", "mask"),
        ("occluders", ["none"]),
        ("occluders", ["self_occluded"]),
        ("occluders", ["out_of_frame"]),
        ("occluders", [1]),
        ("visibility", None),
        ("visibility", dict.fromkeys(REGIONS, "clear")),
        ("annotation_tier", "gold"),
        ("exhaustive", "true"),
        ("provenance_ref", 1),
        ("rule_id", []),
        ("observation_ref", False),
        ("qc_ref", {}),
        *((field, "") for field in ("provenance_ref", "rule_id", "observation_ref", "qc_ref")),
    ],
)
def test_frame_rejects_malformed_annotations(field: str, value: object) -> None:
    payload = _frame()
    payload["faces"][0]["annotation"][field] = value
    with pytest.raises(fc.FrameContractError, match=field):
        fc.validate_interchange("frame-v1", payload)


@pytest.mark.parametrize("location", ["face", "annotation", "visibility"])
def test_annotation_objects_stay_closed_and_do_not_accept_persisted_mode_stamps(location: str) -> None:
    payload = _frame()
    face = payload["faces"][0]
    target = {"face": face, "annotation": face["annotation"], "visibility": face["annotation"]["visibility"]}[location]
    target["annotation_mode"] = "exhaustive"
    with pytest.raises(fc.FrameContractError):
        fc.validate_interchange("frame-v1", payload)


def test_fake_pair_cell_round_trip_retains_labels_and_evidence_references() -> None:
    payload = _frame()
    query = payload["faces"][0]
    query["annotation"].update(
        occluders=["mask"],
        visibility={"left_eye": "visible", "right_eye": "uncertain", "nose": "occluded", "mouth": "occluded"},
        annotation_tier="a",
        exhaustive=False,
        provenance_ref="synthetic:pre-adjudication-record",
        rule_id="synthetic:face-label-rule/v1",
        observation_ref=None,
        qc_ref="synthetic:qc-record",
    )
    enrolled = copy.deepcopy(query)
    enrolled["face_id"] = "face-0002"
    enrolled["annotation"]["occluders"] = ["sunglasses", "hand"]
    enrolled["annotation"]["visibility"]["left_eye"] = "occluded"
    payload["faces"].append(enrolled)
    restored = json.loads(json.dumps(payload))
    fc.validate_interchange("frame-v1", restored)
    assert restored == payload
    assert [face["annotation"]["occluders"] for face in restored["faces"]] == [["mask"], ["sunglasses", "hand"]]
    assert restored["faces"][0]["annotation"]["observation_ref"] is None
