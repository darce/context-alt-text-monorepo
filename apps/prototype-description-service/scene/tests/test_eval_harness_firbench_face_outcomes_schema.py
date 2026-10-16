"""Fake-only face_outcomes wire regressions for scores-v1, using the real stdlib validator.

Canon v0.26.2: EVAL-19 (IARPA Janus Benchmark-C, section 2.3.4) keeps detector alarms out of
nonmated denominators, so face_outcomes names GT faces only. MCP16893 makes face_outcomes an
optional root field: version-1 payloads without it stay valid. Test-fold outcomes come from the
actual classifier, firbench_score._outcome, never from a copied rule. Every value here is
synthetic; nothing is measured, observed or claimed about real data.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from scripts.eval_harness import firbench_contract as fc
from scripts.eval_harness import firbench_score as core

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "firbench_interchange_v1"
FIXTURE = FIXTURE_DIR / "scores-v1.json"
FRAME_FIXTURE = FIXTURE_DIR / "frame-v1.json"
LEG_NATIVE = "sface__native__ab12cd__cv4.10.0__ort1.18.0"
LEG_AURAFACE = "auraface__native__ef34ab__cv4.10.0__ort1.18.0"
TAU = 0.5
FIT_REASON = "fit_fold_not_scored"
ROW_KEYS = (
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
)
# Version-1 root required list, frozen before face_outcomes was added.
V1_REQUIRED = (
    "schema_version",
    "decision_sha256",
    "frame_id",
    "admissibility",
    "boundary_semantics",
    "n_psu",
    "min_n_independent",
    "cell_floor_n_independent",
    "p_d",
    "power",
    "planning_icc",
    "design_effect",
    "n_eff",
    "n_units",
    "n_nonmated_eff",
    "icc_sensitivity",
    "legs",
    "primary",
    "verdict",
    "decision_path",
    "hypotheses",
    "guardrails",
    "curves",
    "cells",
    "joint_gaps",
    "waterfall",
)


@dataclass(frozen=True)
class _Record:
    """The SearchRecord attributes that core._outcome reads, as a frozen synthetic record."""

    face_id: str
    image_id: str
    psu_id: str
    identity_id: str | None
    identity_status: fc.IdentityStatus
    fold: int
    unit_id: str | None
    sampling_arm: fc.SamplingArm
    inclusion_probability: float | None
    cohort: None
    arm: fc.Arm
    arm_availability: fc.ArmStatus
    stage_reached: fc.SearchStage | None
    top_k: tuple[tuple[str, float], ...]


def _search(
    face_id: str,
    *,
    identity_id: str | None,
    identity_status: fc.IdentityStatus = fc.IdentityStatus.named,
    unit_id: str | None = None,
    stage: fc.SearchStage | None = fc.SearchStage.embedded,
    top_k: tuple[tuple[str, float], ...] = (),
    arm_availability: fc.ArmStatus = fc.ArmStatus.available,
    fold: int = 1,
) -> _Record:
    return _Record(
        face_id=face_id,
        image_id=f"image-{face_id}",
        psu_id=f"psu-{face_id}",
        identity_id=identity_id,
        identity_status=identity_status,
        fold=fold,
        unit_id=unit_id,
        sampling_arm=fc.SamplingArm.probability,
        inclusion_probability=0.5,
        cohort=None,
        arm=fc.Arm.native,
        arm_availability=arm_availability,
        stage_reached=stage,
        top_k=top_k,
    )


def _wire_row(
    record: _Record,
    *,
    mated: bool | None,
    outcome: fc.FaceOutcome | None,
    reason: str | None,
    fold_role: str = "test",
) -> dict[str, Any]:
    return {
        "face_id": record.face_id,
        "image_id": record.image_id,
        "psu_id": record.psu_id,
        "fold": record.fold,
        "fold_role": fold_role,
        "sampling_arm": record.sampling_arm.value,
        "leg_key": LEG_NATIVE,
        "arm": record.arm.value,
        "arm_availability": record.arm_availability.value,
        "stage_reached": None if record.stage_reached is None else record.stage_reached.value,
        "identity_status": record.identity_status.value,
        "mated": mated,
        "cell": ["clear", "unknown"],
        "outcome": None if outcome is None else outcome.value,
        "outcome_available": outcome is not None,
        "outcome_reason": reason,
    }


def _row(**overrides: Any) -> dict[str, Any]:
    """A valid available test-fold mated row; each override edits one field for a refusal case."""
    row: dict[str, Any] = {
        "face_id": "face-0101",
        "image_id": "image-0101",
        "psu_id": "psu-0101",
        "fold": 1,
        "fold_role": "test",
        "sampling_arm": "probability",
        "leg_key": LEG_NATIVE,
        "arm": "native",
        "arm_availability": "available",
        "stage_reached": "embedded",
        "identity_status": "named",
        "mated": True,
        "cell": ["clear", "unknown"],
        "outcome": "correct",
        "outcome_available": True,
        "outcome_reason": None,
    }
    row.update(overrides)
    return row


def _payload(rows: Any) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["face_outcomes"] = rows
    return payload


def _validate(payload: Any) -> None:
    fc.validate_interchange("scores-v1", payload)


def _assert_refused(rows: Any, path: str) -> None:
    """Refuse at ``path``, after proving the unedited row validates, so the refusal is the edit."""
    _validate(_payload([_row()]))
    with pytest.raises(fc.FrameContractError, match=path):
        _validate(_payload(rows))


def _refused_at(field: str, **overrides: Any) -> None:
    _assert_refused([_row(**overrides)], rf"face_outcomes\[0\]\.{re.escape(field)}")


# Mated and nonmated records, with the expected classifier outcome (None = named null) and reason.
MIXED_CASES = [
    pytest.param(
        _search("face-0101", identity_id="id-0001", top_k=(("id-0001", 0.9),)),
        True,
        None,
        id="correct",
    ),
    pytest.param(
        _search("face-0102", identity_id="id-0001", top_k=(("id-0002", 0.9),)),
        True,
        None,
        id="wrong_identity",
    ),
    pytest.param(
        _search("face-0103", identity_id="id-0001", top_k=(("id-0001", 0.2),)),
        True,
        None,
        id="rejected",
    ),
    pytest.param(_search("face-0104", identity_id="id-0001", stage=fc.SearchStage.missed), True, None, id="missed"),
    pytest.param(
        _search("face-0105", identity_id="id-0001", stage=fc.SearchStage.unaligned),
        True,
        None,
        id="unaligned",
    ),
    pytest.param(
        _search(
            "face-0106",
            identity_id=None,
            identity_status=fc.IdentityStatus.unknown,
            unit_id="face-0106",
            top_k=(("id-0001", 0.9),),
        ),
        False,
        None,
        id="false_accept",
    ),
    pytest.param(
        _search(
            "face-0107",
            identity_id=None,
            identity_status=fc.IdentityStatus.unknown,
            unit_id="face-0107",
            top_k=(("id-0001", 0.2),),
        ),
        False,
        None,
        id="correct_reject",
    ),
    pytest.param(
        _search("face-0108", identity_id="id-0001", arm_availability=fc.ArmStatus.unavailable, stage=None),
        True,
        "arm_unavailable",
        id="unavailable_arm",
    ),
    pytest.param(
        _search("face-0109", identity_id=None, identity_status=fc.IdentityStatus.unresolved, stage=None),
        None,
        "identity_unresolved",
        id="unresolved_identity",
    ),
]


@pytest.mark.parametrize(("record", "mated", "reason"), MIXED_CASES)
def test_each_classifier_outcome_or_named_null_validates_on_the_wire(
    record: _Record, mated: bool | None, reason: str | None
) -> None:
    outcome = core._outcome(record, TAU, fc.BoundarySemantics.v2)
    _validate(_payload([_wire_row(record, mated=mated, outcome=outcome, reason=reason)]))


def test_mixed_test_fold_rows_from_the_actual_classifier_validate_together() -> None:
    rows = [
        _wire_row(
            record,
            mated=mated,
            outcome=core._outcome(record, TAU, fc.BoundarySemantics.v2),
            reason=reason,
        )
        for record, mated, reason in (case.values for case in MIXED_CASES)
    ]
    _validate(_payload(rows))
    assert {row["outcome"] for row in rows} == {*(outcome.value for outcome in fc.FaceOutcome), None}


def test_fit_fold_metadata_rows_carry_null_outcome_and_validate() -> None:
    record = _search("face-0110", identity_id="id-0001", stage=None, fold=0)
    _validate(_payload([_wire_row(record, mated=True, outcome=None, reason=FIT_REASON, fold_role="fit")]))


@pytest.mark.parametrize("outcome", list(fc.FaceOutcome), ids=lambda member: member.value)
def test_every_face_outcome_value_validates_on_an_available_row(outcome: fc.FaceOutcome) -> None:
    _validate(_payload([_row(outcome=outcome.value)]))


def test_version1_payload_without_face_outcomes_still_validates() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload.pop("face_outcomes", None)
    _validate(payload)


def test_root_gains_only_an_optional_face_outcomes_property() -> None:
    schema = fc._load_schema("scores-v1")
    assert schema["required"] == list(V1_REQUIRED)
    assert "face_outcomes" not in schema["required"]
    assert "face_outcomes" in schema["properties"]
    assert schema["additionalProperties"] is False


def test_row_enums_are_the_actual_s0_contract_values() -> None:
    props = fc._load_schema("scores-v1")["$defs"]["faceOutcomeRow"]["properties"]
    assert set(props["outcome"]["enum"]) == {*(member.value for member in fc.FaceOutcome), None}
    assert set(props["stage_reached"]["enum"]) == {*(member.value for member in fc.SearchStage), None}
    assert set(props["arm"]["enum"]) == {member.value for member in fc.Arm}
    assert set(props["arm_availability"]["enum"]) == {member.value for member in fc.ArmStatus}
    assert set(props["identity_status"]["enum"]) == {member.value for member in fc.IdentityStatus}
    assert set(props["sampling_arm"]["enum"]) == {member.value for member in fc.SamplingArm}
    assert set(props["fold_role"]["enum"]) == {member.value for member in fc.FoldRole}


@pytest.mark.parametrize("key", ROW_KEYS)
def test_row_refuses_a_missing_declared_key(key: str) -> None:
    row = _row()
    row.pop(key)
    _assert_refused([row], r"face_outcomes\[0\]: missing required key")


def test_row_refuses_an_unknown_key() -> None:
    _assert_refused([_row(rate=0.5)], r"face_outcomes\[0\]: unknown keys")


@pytest.mark.parametrize("rows", [None, {}, "face-0101", True], ids=["null", "object", "string", "bool"])
def test_face_outcomes_must_be_an_array_when_present(rows: Any) -> None:
    _assert_refused(rows, r"face_outcomes: expected array")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("fold_role", "train"),
        ("fold_role", "Fit"),
        ("sampling_arm", "random"),
        ("arm", "gt_crop"),
        ("arm_availability", "fallback"),
        ("stage_reached", "matched"),
        ("identity_status", "resolved"),
        ("outcome", "match"),
        ("outcome", "Correct"),
        ("outcome", ""),
    ],
)
def test_enum_fields_refuse_values_outside_the_s0_contract(field: str, value: str) -> None:
    _refused_at(field, **{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("face_id", ""),
        ("face_id", 7),
        ("image_id", None),
        ("psu_id", ""),
        ("leg_key", ""),
        ("fold", "0"),
        ("fold", -1),
        ("fold", 1.0),
        ("fold", None),
        ("cell", "clear+unknown"),
        ("cell", ["clear"]),
        ("cell", ["clear", "unknown", "extra"]),
        ("cell", [None, "unknown"]),
        ("cell", ["clear", 0]),
        ("cell", []),
        ("outcome_reason", 0),
        ("outcome_reason", ""),
    ],
)
def test_wrong_types_and_shapes_are_refused(field: str, value: Any) -> None:
    _refused_at(field, **{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("fold", True),
        ("fold", False),
        ("mated", 0),
        ("mated", 1),
        ("mated", "true"),
        ("outcome_available", 0),
        ("outcome_available", 1),
        ("outcome_available", "false"),
        ("outcome_available", None),
    ],
)
def test_bool_values_never_stand_in_for_integers_or_booleans(field: str, value: Any) -> None:
    # Python treats False == 0 and True == 1; the strict checker must not.
    _refused_at(field, **{field: value})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")], ids=["nan", "inf", "-inf"])
def test_nonfinite_fold_is_refused(value: float) -> None:
    _refused_at("fold", fold=value)


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        pytest.param({"outcome": None}, "outcome", id="available_without_outcome"),
        pytest.param({"outcome_reason": "fit_fold_not_scored"}, "outcome_reason", id="available_with_reason"),
        pytest.param(
            {"outcome_available": False, "outcome_reason": "arm_unavailable"},
            "outcome",
            id="unavailable_keeps_outcome",
        ),
        pytest.param(
            {"outcome_available": False, "outcome": None, "outcome_reason": None},
            "outcome_reason",
            id="unavailable_no_reason",
        ),
        pytest.param(
            {"outcome_available": False, "outcome": None, "outcome_reason": ""},
            "outcome_reason",
            id="unavailable_empty_reason",
        ),
    ],
)
def test_outcome_available_conditions_are_enforced(overrides: dict[str, Any], field: str) -> None:
    _refused_at(field, **overrides)


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param(
            {
                "arm_availability": "unavailable_fused",
                "stage_reached": None,
                "outcome": None,
                "outcome_available": False,
                "outcome_reason": "arm_unavailable",
            },
            id="fused_arm_named_null",
        ),
        pytest.param(
            {
                "identity_status": "unresolved",
                "mated": None,
                "stage_reached": None,
                "outcome": None,
                "outcome_available": False,
                "outcome_reason": "identity_unresolved",
            },
            id="unresolved_named_null",
        ),
        pytest.param(
            {
                "stage_reached": None,
                "outcome": None,
                "outcome_available": False,
                "outcome_reason": "calibration_unavailable",
            },
            id="calibration_absent_named_null",
        ),
    ],
)
def test_unavailable_arm_unresolved_identity_and_calibration_absence_are_named_nulls(
    overrides: dict[str, Any],
) -> None:
    _validate(_payload([_row(**overrides)]))


def _frame() -> dict[str, Any]:
    return json.loads(FRAME_FIXTURE.read_text(encoding="utf-8"))


def test_committed_fixture_is_valid_and_fit_only() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    _validate(payload)
    rows = payload["face_outcomes"]
    assert rows
    for row in rows:
        assert row["fold_role"] == "fit"
        assert row["stage_reached"] is None
        assert row["outcome"] is None
        assert row["outcome_available"] is False
        assert row["outcome_reason"] == FIT_REASON
        # Honest: the fixture declares no enrolled-gallery membership, so mated is not claimed.
        assert row["mated"] is None


def test_committed_fixture_covers_every_frame_gt_face_leg_arm_and_fold_once() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    rows = payload["face_outcomes"]
    frame = _frame()
    gt_faces = [face["face_id"] for face in frame["faces"]]
    folds = [fold["fold"] for fold in frame["fold_roles"]]
    expected = {
        (leg["leg_key"], face_id, arm.value, fold)
        for leg in payload["legs"]
        for face_id in gt_faces
        for arm in fc.Arm
        for fold in folds
    }
    keys = [(row["leg_key"], row["face_id"], row["arm"], row["fold"]) for row in rows]
    assert len(keys) == len(set(keys)) == len(expected)
    assert set(keys) == expected
    assert keys == sorted(keys)


def test_committed_fixture_rows_agree_with_frame_foreign_keys_and_fold_roles() -> None:
    rows = json.loads(FIXTURE.read_text(encoding="utf-8"))["face_outcomes"]
    frame = _frame()
    faces = {face["face_id"]: face for face in frame["faces"]}
    images = {image["image_id"]: image for image in frame["images"]}
    psu_of_image = {entry["image_id"]: entry["psu_id"] for entry in frame["psu_map"]}
    fold_of_psu = {entry["psu_id"]: entry["fold"] for entry in frame["folds"]}
    role_of_fold = {entry["fold"]: entry["role"] for entry in frame["fold_roles"]}
    for row in rows:
        face = faces[row["face_id"]]
        assert row["image_id"] == face["image_id"]
        assert row["psu_id"] == psu_of_image[row["image_id"]]
        assert row["fold"] == fold_of_psu[row["psu_id"]]
        assert row["fold_role"] == role_of_fold[row["fold"]]
        assert row["sampling_arm"] == images[row["image_id"]]["sampling_arm"]
        assert row["identity_status"] == face["identity_status"]


def test_committed_fixture_attribution_arms_are_unavailable_as_joint_gaps_state() -> None:
    rows = json.loads(FIXTURE.read_text(encoding="utf-8"))["face_outcomes"]
    availability = {(row["leg_key"], row["arm"]): row["arm_availability"] for row in rows}
    for leg_key in (LEG_NATIVE, LEG_AURAFACE):
        assert availability[(leg_key, "native")] == "available"
        assert availability[(leg_key, "gt_crop_redetect")] == "unavailable"
        assert availability[(leg_key, "cached_yunet_landmark_replay")] == "unavailable"
