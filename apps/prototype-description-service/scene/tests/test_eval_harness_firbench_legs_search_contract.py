"""S2 search regressions; synthetic inputs, receipt clocks, and frozen S1/S0 shapes.

The Cohort contract was checked against the read-only S1 producer firbench_frames.py
(sha256 71e3572be3255d8cf4636edd76f39e7b89d099a0e8ed3d7c5cca6dc380a89922).
The local contract double keeps this suite independent of an unmerged sibling.
"""

from dataclasses import dataclass
from types import SimpleNamespace

import numpy as np
import pytest

from scripts.eval_harness import firbench_legs as search
from scripts.eval_harness.firbench_contract import (
    AlignmentMode,
    Arm,
    ArmStatus,
    CanaryConfigError,
    FoldRole,
    IdentityStatus,
    LegId,
    LegKind,
    SamplingArm,
    SearchStage,
    validate_interchange,
)


@dataclass(frozen=True)
class _Cohort:
    sex: str | None = None
    age_band: str | None = None
    origin: str | None = None

    def to_json(self):
        return {"sex": self.sex, "age_band": self.age_band, "origin": self.origin}


class _Clock:
    def __init__(self):
        self.seconds = 0.0

    def __call__(self):
        return self.seconds

    def spend(self, milliseconds):
        self.seconds += milliseconds / 1000.0


class _Leg:
    def __init__(self, observations, clock, kind=LegKind.sface):
        self.kind = kind
        self.alignment_mode = AlignmentMode.fused_internal if kind is LegKind.insightface else AlignmentMode.separable
        self.observations = tuple(observations)
        self.clock = clock
        self.calls = 0

    def leg_id(self, arm):
        return LegId(self.kind, arm, "a" * 64, "5.0.0", "1.28.0")

    def observe(self, image):
        self.calls += 1
        self.clock.spend(12)
        return self.observations

    def align(self, image, landmarks):
        self.clock.spend(5)
        return image

    def embed(self, aligned):
        self.clock.spend(7)
        return np.array([1.0, 0.0, 0.0])


def _observation(box=(4, 4, 16, 16), vector=(1.0, 0.0, 0.0)):
    detection = search.DetectedFace(box, np.zeros((5, 2)), 0.9)
    return search.Observation.embedded(detection, np.array(vector))


def _face(face_id="face-1", *, identity="id-1", status=IdentityStatus.named, cohort=None, box=(4, 4, 16, 16)):
    return SimpleNamespace(
        face_id=face_id,
        image_id="image-1",
        box=box,
        identity_status=status,
        identity_id=identity,
        cohort=cohort,
    )


def _gallery():
    return search.Gallery.enrol({f"id-{i + 1}": [v] for i, v in enumerate(np.eye(3))})


def _run(leg, faces, *, arm=Arm.native, gallery=None, exhaustive=True, cells=None):
    return search.search_leg_arm(
        leg=leg,
        arm=arm,
        images={"image-1": np.zeros((64, 64, 3), dtype=np.uint8)},
        image_units={"image-1": SimpleNamespace(sampling_arm=SamplingArm.probability, inclusion_probability=0.5)},
        faces=faces,
        gallery=_gallery() if gallery is None else gallery,
        psu_by_image={"image-1": "psu-1"},
        fold_by_psu={"psu-1": 0},
        fold_roles={0: FoldRole.test},
        exhaustive=exhaustive,
        top_k=3,
        cells=cells,
        crop_margin=0.0,
        cached_landmarks={face.face_id: np.zeros((5, 2)) for face in faces},
    )


@pytest.fixture
def clock(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(search, "perf_counter", clock)
    original = search._top_k

    def timed_search(*args):
        clock.spend(8)
        return original(*args)

    monkeypatch.setattr(search, "_top_k", timed_search)
    return clock


@pytest.mark.parametrize("cohort", [_Cohort(None, "adult", None), _Cohort(), None])
def test_actual_s1_cohort_dataclass_shape_serializes(clock, cohort):
    (row,) = _run(_Leg([_observation()], clock), [_face(cohort=cohort)]).records
    expected = None if cohort is None else cohort.to_json()
    assert row.to_dict()["cohort"] == expected
    validate_interchange("face-search-record-v1", row.to_dict())


@pytest.mark.parametrize(
    "faces,observations,expected_rows,expected_ms",
    [
        ([_face()], [_observation()], 1, 20),
        ([_face()], [search.Observation.unaligned(_observation().detection)], 1, 12),
        ([_face()], [], 1, 12),
        ([], [_observation()], 1, 20),
        ([_face()], [_observation(), _observation()], 2, 28),
        ([_face()], [_observation(), _observation((40, 40, 8, 8))], 2, 28),
        ([_face(), _face("missed", box=(30, 30, 8, 8))], [_observation()], 2, 20),
    ],
    ids=["one-match", "unaligned", "missed-mate", "background", "duplicate", "match-and-background", "match-and-miss"],
)
def test_native_receipt_allocates_complete_image_search_cost(clock, faces, observations, expected_rows, expected_ms):
    result = _run(_Leg(observations, clock), faces)
    assert len(result.records) == expected_rows
    assert set(result.timings_ms) == {r.timing_receipt_ref for r in result.records}
    assert sum(result.timings_ms.values()) == pytest.approx(expected_ms)
    assert list(result.timings_ms.values()) == pytest.approx([expected_ms / expected_rows] * expected_rows)


def test_empty_native_image_retains_cost_in_image_receipt(clock):
    leg = _Leg([], clock)
    result = _run(leg, [])
    assert result.records == result.ledger == ()
    assert result.timings_ms == {f"{leg.leg_id(Arm.native).key()}/native/image:image-1": pytest.approx(12)}


@pytest.mark.parametrize("arm", list(Arm))
@pytest.mark.parametrize("kind", [LegKind.sface, LegKind.auraface, LegKind.insightface])
def test_canary_applies_gallery_permutation_once_and_binds_changed_snapshot(clock, monkeypatch, arm, kind):
    gallery = _gallery()
    original = {identity: vector.copy() for identity, vector in gallery.prototypes.items()}
    base = _Leg([_observation()], clock, kind)
    canary = search.CanaryLeg(base, canary_identities=["id-1", "id-2"], seed=7)
    relabel = canary.relabel_gallery
    calls = []

    def count_relabels(prototypes):
        calls.append(prototypes)
        return relabel(prototypes)

    monkeypatch.setattr(canary, "relabel_gallery", count_relabels)
    baseline = _run(base, [_face()], arm=arm, gallery=gallery)
    result = _run(canary, [_face()], arm=arm, gallery=gallery)
    repeated = _run(canary, [_face()], arm=arm, gallery=gallery)
    assert len(calls) == 2  # once per invocation; the original input is reusable
    (row,) = result.records
    expected_gallery = search.Gallery.enrol({identity: [vector] for identity, vector in relabel(original).items()})
    assert row.gallery_sha256 == expected_gallery.gallery_sha256 != gallery.gallery_sha256
    assert repeated.records == result.records
    assert row.identity_id == "id-1"  # GT is never relabelled
    if kind is LegKind.insightface and arm is not Arm.native:
        assert row.arm_availability is ArmStatus.unavailable_fused
        assert row.stage_reached is None and row.top_k == ()
    else:
        accepted = {r.face_id: r.identity_id for r in baseline.records if r.top_k[0][0] == r.identity_id}
        changed = sorted(
            r.face_id for r, old in zip(result.records, baseline.records, strict=True) if r.top_k != old.top_k
        )
        assert changed == search.expected_changed_search_ids(accepted, canary.canary_identities) == ["face-1"]
        assert row.top_k[0][0] == "id-2"
    for identity in original:
        np.testing.assert_array_equal(gallery.prototypes[identity], original[identity])
    validate_interchange("face-search-record-v1", row.to_dict())


@pytest.mark.parametrize("arm", list(Arm))
def test_canary_missing_gallery_identity_fails_before_running(clock, arm):
    base = _Leg([_observation()], clock)
    canary = search.CanaryLeg(base, canary_identities=["id-1", "absent"], seed=7)
    with pytest.raises(CanaryConfigError, match="absent"):
        _run(canary, [_face()], arm=arm)
    assert base.calls == 0


def test_canary_changes_exactly_the_declared_accepted_search_ids(clock):
    gallery = _gallery()
    boxes = [(4, 4, 8, 8), (20, 20, 8, 8), (40, 40, 8, 8)]
    faces = [_face(f"face-{i + 1}", identity=f"id-{i + 1}", box=box) for i, box in enumerate(boxes)]
    base = _Leg([_observation(box, vector) for box, vector in zip(boxes, np.eye(3), strict=True)], clock)
    canary = search.CanaryLeg(base, canary_identities=["id-1", "id-2"], seed=7)
    before = _run(base, faces, gallery=gallery)
    after = _run(canary, faces, gallery=gallery)
    accepted = {r.face_id: r.identity_id for r in before.records if r.top_k[0][0] == r.identity_id}
    changed = sorted(
        r.face_id for r, old in zip(after.records, before.records, strict=True) if r.top_k[0][0] != old.top_k[0][0]
    )
    assert changed == search.expected_changed_search_ids(accepted, canary.canary_identities) == ["face-1", "face-2"]
    assert after.records[2].top_k[0][0] == "id-3"


@pytest.mark.parametrize("exhaustive", [False, True])
def test_nonmated_units_and_multilabel_unknown_cells_survive(clock, exhaustive):
    faces = [
        _face("mate"),
        _face("unknown", identity=None, status=IdentityStatus.unknown),
        _face("unresolved", identity=None, status=IdentityStatus.unresolved),
        _face("heldout", identity="absent"),
    ]
    result = _run(_Leg([], clock), faces, exhaustive=exhaustive, cells={"mate": ("mask", "mouth")})
    rows = {r.face_id: r for r in result.records}
    assert len(result.ledger) == 4
    assert rows["mate"].identity_id == "id-1" and rows["mate"].stage_reached is SearchStage.missed
    assert rows["mate"].cell == ("mask", "mouth")
    assert rows["unknown"].unit_id == ("unknown" if exhaustive else None)
    assert rows["unknown"].cell == ("unknown", "unknown")
    assert rows["unresolved"].unit_id is None
    assert rows["heldout"].unit_id == "heldout"


def test_duplicates_add_no_nonmated_units_and_background_detections_share_source_unit(clock):
    observations = [_observation(), _observation(), _observation((40, 40, 8, 8)), _observation((50, 50, 8, 8))]
    result = _run(_Leg(observations, clock), [_face()])
    assert [r.unit_id for r in result.records] == [None, None, "background:image-1", "background:image-1"]
    assert [r.cell for r in result.records] == [
        ("unknown", "unknown"),
        ("duplicate", "duplicate"),
        ("background", "background"),
        ("background", "background"),
    ]
    assert len(result.ledger) == 1


def test_frozen_wire_replays_with_different_receipt_costs(clock, tmp_path, monkeypatch):
    leg = _Leg([_observation()], clock)
    first = _run(leg, [_face(cohort=_Cohort())])
    original = search._top_k

    def slower_search(*args):
        clock.spend(100)
        return original(*args)

    monkeypatch.setattr(search, "_top_k", slower_search)
    second = _run(leg, [_face(cohort=_Cohort())])
    assert next(iter(second.timings_ms.values())) - next(iter(first.timings_ms.values())) == pytest.approx(100)
    paths = [tmp_path / "first.jsonl", tmp_path / "second.jsonl"]
    for result, path in zip((first, second), paths, strict=True):
        search.write_searches_jsonl(path, result.records)
        payload = result.records[0].to_dict()
        assert set(payload) == {
            "schema_version",
            "face_id",
            "image_id",
            "psu_id",
            "identity_id",
            "identity_status",
            "fold",
            "fold_role",
            "cell",
            "unit_id",
            "sampling_arm",
            "inclusion_probability",
            "cohort",
            "leg_key",
            "arm",
            "arm_availability",
            "alignment_mode",
            "stage_reached",
            "top_k",
            "gallery_sha256",
            "timing_receipt_ref",
        }
        assert payload["timing_receipt_ref"] in result.timings_ms
    assert paths[0].read_bytes() == paths[1].read_bytes()
