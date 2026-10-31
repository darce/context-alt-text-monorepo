"""Offline multi-view software controls: synthetic pixels, real leg producers, no weights."""

import hashlib
import json
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from recognition.application.embedding.manifest import EmbeddingModelManifest
from recognition.infrastructure.face_pipeline._common import EmbedBatchResult, RawDetection
from recognition.infrastructure.face_pipeline.aligner import AlignmentError
from scripts.eval_harness import firbench_legs as fl
from scripts.eval_harness import firbench_runtime as runtime
from scripts.eval_harness.firbench_contract import Arm, FrameContractError, LegKind, RuntimeMismatchError, SearchStage


def _views():
    from scripts.eval_harness import firbench_views

    return firbench_views


def _budget(**changes):
    return _views().ViewBudget(
        **{
            "max_views": 5,
            "max_pixels": 100_000,
            "max_calls": 5,
            "max_stage_calls": 100,
            "max_candidates": 100,
            "deadline_seconds": 10,
        }
        | changes
    )


def _image():
    return np.arange(60 * 80 * 3, dtype=np.uint8).reshape(60, 80, 3)


def _observation(box=(20, 15, 12, 14), points=None, vector=None):
    if points is None:
        points = np.array([[22, 18], [28, 18], [25, 21], [23, 25], [28, 25]], dtype=float)
    detection = fl.DetectedFace(box, np.array(points, dtype=float), 0.9)
    return fl.Observation.embedded(detection, np.eye(1, 128, dtype=np.float32)[0] if vector is None else vector)


def _leg(observe):
    return fl.BuffaloLeg(
        weights_sha256="b" * 64, opencv_version="5.0.0", ort_version="1.28.0", embedding_dim=128, process=observe
    )


def _produce(leg=None, **changes):
    v = _views()
    return v.produce_views(
        **{
            "leg": leg if leg is not None else _leg(lambda image: []),
            "image_bgr": _image(),
            "source_id": "image-1",
            "source_sha256": "a" * 64,
            "orientation": "decoded-oriented-v1",
            "policy": v.ViewPolicy.fixed_overlap,
            "budget": _budget(),
            "offline": True,
        }
        | changes
    )


def test_policies_are_separate_from_pipeline_arms_and_default_refuses_execution():
    v = _views()
    assert {p.value for p in v.ViewPolicy} == {"scene_only", "fixed_overlap", "person_boxes"}
    assert {a.value for a in Arm} == {"native", "gt_crop_redetect", "cached_yunet_landmark_replay"}
    with pytest.raises(FrameContractError, match="offline=True"):
        _produce(offline=False)


def test_full_scene_plus_four_overlaps_and_explicit_person_proposals():
    v = _views()
    result = _produce()
    assert [r.view.crop_xyxy for r in result.receipts] == [
        (0, 0, 80, 60),
        (0, 0, 60, 45),
        (20, 0, 80, 45),
        (0, 15, 60, 60),
        (20, 15, 80, 60),
    ]
    assert result.pixels_submitted == 4800 + 4 * 2700
    assert result.calls == 5
    proposals = tuple(v.PersonBox(str(i), (i, 2, 20, 30), "detector-v1") for i in range(6))
    result = _produce(policy=v.ViewPolicy.person_boxes, person_boxes=proposals)
    assert [r.view.proposal_id for r in result.receipts[1:5]] == ["0", "1", "2", "3"]
    assert [r.status for r in result.receipts[5:]] == ["view_budget", "view_budget"]
    assert result.calls == 5


@pytest.mark.parametrize("turn", [0, 1, 2, 3])
def test_rotation_crop_inverse_uses_edges_for_boxes_and_centers_for_landmarks(turn):
    v = _views()
    view = v.View("local", (10, 8, 40, 28), turn, "person-1", "manual-synthetic")
    image = _image()
    rendered = view.render(image)
    np.testing.assert_array_equal(rendered, np.rot90(image[8:28, 10:40], -turn))
    # Independent hand-calculated pixel-center and edge oracles (30x20 crop).
    points = np.array([[12, 10], [30, 10], [21, 15], [14, 23], [30, 23]], dtype=float)
    local_points = [
        [[2, 2], [20, 2], [11, 7], [4, 15], [20, 15]],
        [[17, 2], [17, 20], [12, 11], [4, 4], [4, 20]],
        [[27, 17], [9, 17], [18, 12], [25, 4], [9, 4]],
        [[2, 27], [2, 9], [7, 18], [15, 25], [15, 9]],
    ][turn]
    local_box = [(1, 1, 24, 17), (2, 1, 17, 24), (5, 2, 24, 17), (1, 5, 17, 24)][turn]
    observation = _observation(local_box, local_points)
    mapped = view.to_source(observation)
    assert mapped.detection.bbox_px == pytest.approx((11, 9, 24, 17))
    np.testing.assert_allclose(mapped.detection.landmarks_px, points)
    assert not np.shares_memory(mapped.detection.landmarks_px, observation.detection.landmarks_px)


def test_person_boxes_clip_outward_but_detections_are_not_silently_clipped():
    v = _views()
    boxes = (
        v.PersonBox("truncated", (-2.1, 3.2, 22.5, 20.1), "synthetic"),
        v.PersonBox("outside", (90, 2, 5, 5), "synthetic"),
    )
    result = _produce(policy=v.ViewPolicy.person_boxes, person_boxes=boxes)
    by_proposal = {r.proposal_id: r for r in result.receipts}
    assert by_proposal["truncated"].view.crop_xyxy == (0, 3, 21, 24)
    assert by_proposal["outside"].status == "proposal_miss"
    mapped = by_proposal["truncated"].view.to_source(_observation((-1, -2, 10, 10)))
    assert mapped.detection.bbox_px == (-1, 1, 10, 10)
    assert _produce(policy=v.ViewPolicy.person_boxes).receipts[-1].status == "proposal_missing"


def test_actual_face_pipeline_detect_align_embed_shapes_and_unaligned_outcome():
    v = _views()
    calls = []

    class Detector:
        def detect(self, images):
            calls.append("detect")
            return [
                [
                    RawDetection(np.array([2, 3, 10, 12]), np.arange(10).reshape(5, 2), 0.8),
                    RawDetection(np.array([20, 3, 10, 12]), np.ones((5, 2)), 0.7),
                ]
            ]

    class Aligner:
        def align(self, image, points):
            calls.append("align")
            if points[0, 0] == 1:
                raise AlignmentError("synthetic unsupported transform")
            return SimpleNamespace(crop=image[:8, :8])

    class Embedder:
        embedding_dim = 128

        def embed(self, images):
            calls.append("embed")
            return EmbedBatchResult(np.eye(1, 128, dtype=np.float32), np.ones(1))

    leg = fl.build_face_pipeline_leg(
        LegKind.sface,
        manifest=EmbeddingModelManifest("onnx", "synthetic-sface", 128, "l2", "cosine"),
        detector=Detector(),
        aligner=Aligner(),
        embedder=Embedder(),
        weights_sha256="b" * 64,
        preprocessing={"synthetic": True},
        opencv_version="5.0.0",
        ort_version="1.28.0",
    )
    result = _produce(leg, policy=v.ViewPolicy.scene_only)
    assert calls == ["detect", "align", "embed", "align"]
    assert [c.observation.stage for c in result.candidates] == [SearchStage.embedded, SearchStage.unaligned]
    assert result.leg_key == leg.leg_id(Arm.native).key()
    assert all(c.source_id == "image-1" and c.source_sha256 == "a" * 64 for c in result.candidates)


@pytest.mark.parametrize("slow_detect", [False, True])
def test_compute_budget_stops_between_actual_separable_stages_before_embedding(slow_detect):
    _views()
    calls = []
    clock = [0.0]

    class Detector:
        def detect(self, images):
            calls.append("detect")
            if slow_detect:
                clock[0] = 11.0
            return [[RawDetection(np.array([2, 3, 10, 12]), np.arange(10).reshape(5, 2), 0.8)]]

    class Aligner:
        def align(self, image, points):
            calls.append("align")
            return SimpleNamespace(crop=image[:8, :8])

    class Embedder:
        embedding_dim = 512

        def embed(self, images):
            raise AssertionError("compute budget must refuse the embed call")

    leg = fl.build_face_pipeline_leg(
        LegKind.auraface,
        manifest=EmbeddingModelManifest("onnx", "synthetic-auraface", 512, "l2", "cosine"),
        detector=Detector(),
        aligner=Aligner(),
        embedder=Embedder(),
        weights_sha256="b" * 64,
        preprocessing={"synthetic": True},
        opencv_version="5.0.0",
        ort_version="1.28.0",
    )
    result = _produce(leg, budget=_budget(max_stage_calls=2), clock=lambda: clock[0])
    assert calls == (["detect"] if slow_detect else ["detect", "align"])
    assert result.calls == 1 and result.stage_calls == (1 if slow_detect else 2)
    assert [r.status for r in result.receipts] == (["timeout"] if slow_detect else ["compute_budget"]) * 5
    assert result.candidates == ()


def test_cross_view_dedup_keeps_members_and_overlapping_people_and_no_chaining():
    v = _views()
    # All four boxes overlap. Two different landmark arrangements must stay separate.
    first = _observation()
    second = _observation((21, 15, 12, 14), first.detection.landmarks_px + [6, 0])
    candidates = []
    for view_id, observations in [("whole", [first, second]), ("crop", [first, second])]:
        for index, obs in enumerate(observations):
            candidates.append(v.Candidate(view_id, index, obs, obs, "image-1", "a" * 64, "leg"))
    groups = v.deduplicate(candidates)
    assert sorted(len(g.members) for g in groups) == [2, 2]
    assert sum(len(g.members) for g in groups) == 4
    # Even identical same-view detections are not collapsed into one person.
    assert len(v.deduplicate([candidates[0], replace(candidates[0], detection_index=9)])) == 2
    shifted = [_observation((20 + i, 15, 12, 14), first.detection.landmarks_px + [i, 0]) for i in (0, 0.2, 0.4)]
    chain = [replace(candidates[0], view_id=str(i), observation=obs) for i, obs in enumerate(shifted)]
    assert len(v.deduplicate(chain, tolerance_px=0.25)) == 2, (
        "complete-link consistency must prevent transitive identity collapse"
    )


@pytest.mark.parametrize(
    "changes,status,calls",
    [
        ({"max_views": 1}, "view_budget", 1),
        ({"max_calls": 1}, "call_budget", 1),
        ({"max_pixels": 4800}, "pixel_budget", 1),
        ({"max_pixels": 4799}, "pixel_budget", 0),
    ],
)
def test_budgets_are_checked_before_model_calls(changes, status, calls):
    result = _produce(budget=_budget(**changes))
    assert result.calls == calls
    assert status in [r.status for r in result.receipts]


@pytest.mark.parametrize(
    "error,status",
    [
        (TimeoutError("synthetic"), "timeout"),
        (FileNotFoundError("synthetic"), "missing"),
        (RuntimeError("synthetic"), "failed"),
    ],
)
def test_view_failure_retains_source_and_other_views(error, status):
    calls = []

    def process(image):
        calls.append(image.shape)
        if len(calls) == 1:
            raise error
        return []

    result = _produce(_leg(process))
    assert result.receipts[0].status == status
    assert result.calls == 5
    assert result.source_id == "image-1"
    assert result.candidates == ()


def test_deadline_discards_late_candidates_and_does_not_launch_next_view():
    clock = [0.0]

    def process(image):
        clock[0] = 11.0
        return [
            {"bbox_px": (2, 3, 10, 12), "landmarks_px": np.zeros((5, 2)), "det_score": 0.9, "embedding": np.ones(128)}
        ]

    result = _produce(_leg(process), clock=lambda: clock[0])
    assert result.calls == 1
    assert [r.status for r in result.receipts] == ["timeout"] * 5
    assert result.candidates == ()


def test_deadline_before_fused_admission_does_not_record_unmade_calls_or_pixels():
    v = _views()
    ticks = iter([0.0, 0.0, 11.0])  # start, view admission, fused-stage admission
    calls = []
    result = _produce(
        _leg(lambda image: calls.append(image) or []), policy=v.ViewPolicy.scene_only, clock=lambda: next(ticks, 11.0)
    )
    assert calls == []
    assert result.calls == 0 and result.pixels_submitted == 0 and result.stage_calls == 0
    assert result.receipts[0].status == "timeout"


def test_candidate_overflow_fails_view_without_truncated_success():
    row = {"bbox_px": (2, 3, 10, 12), "landmarks_px": np.zeros((5, 2)), "det_score": 0.9, "embedding": np.ones(128)}
    result = _produce(_leg(lambda image: [row, row]), budget=_budget(max_candidates=1))
    assert result.candidates == ()
    assert result.calls == 1
    assert result.receipts[0].status == "candidate_budget"


def test_runtime_aggregates_all_candidates_once_per_original_source_without_mixing_spaces():
    v = _views()
    row = {
        "bbox_px": (2, 3, 10, 12),
        "landmarks_px": np.zeros((5, 2)),
        "det_score": 0.9,
        "embedding": np.eye(1, 128)[0],
    }
    leg = _leg(lambda image: [row])
    gallery = fl.Gallery.enrol({"id-1": [np.eye(1, 128)[0]]})
    kwargs = {
        "leg": leg,
        "image_bgr": _image(),
        "source_id": "image-1",
        "source_sha256": "a" * 64,
        "orientation": "decoded-oriented-v1",
        "policy": v.ViewPolicy.fixed_overlap,
        "budget": _budget(),
        "offline": True,
        "source_search_id": "background:image-1",
        "gallery": gallery,
        "gallery_leg_id": leg.leg_id(Arm.native),
        "top_k": 1,
    }
    result = runtime.experimental_view_search(**kwargs)
    assert result.source_search_id == "background:image-1"
    assert result.top_k == (("id-1", pytest.approx(1.0)),)
    assert len(result.candidate_hits) == 5
    assert len(result.views.candidates) == 5
    assert result.gallery_sha256 == gallery.gallery_sha256
    with pytest.raises(RuntimeMismatchError, match="gallery.*space"):
        runtime.experimental_view_search(
            **(kwargs | {"gallery_leg_id": replace(leg.leg_id(Arm.native), space_fingerprint="c" * 64)})
        )
    with pytest.raises(RuntimeMismatchError, match="dimension"):
        runtime.experimental_view_search(**(kwargs | {"gallery": fl.Gallery.enrol({"bad": [np.ones(512)]})}))
    empty = runtime.experimental_view_search(**(kwargs | {"leg": _leg(lambda image: [])}))
    assert empty.source_search_id == result.source_search_id and empty.top_k == ()


@pytest.mark.parametrize("status", ["empty", "failed", "timeout", "missing"])
def test_upstream_person_proposal_outcomes_survive_without_filtering_source(status):
    v = _views()
    result = _produce(
        policy=v.ViewPolicy.person_boxes, proposal_status=status, proposal_source_ref="synthetic-person-producer/v1"
    )
    assert result.source_id == "image-1" and result.calls == 1
    assert [r.status for r in result.receipts] == ["empty", f"proposal_{status}"]
    assert json.loads(result.recipe_json)["proposal_source_ref"] == "synthetic-person-producer/v1"


def test_evidence_roundtrip_retains_transforms_members_raw_vectors_and_input_hashes():
    v = _views()
    row = {"bbox_px": (2, 3, 10, 12), "landmarks_px": np.zeros((5, 2)), "det_score": 0.9, "embedding": np.ones(512)}
    leg = fl.BuffaloLeg(
        weights_sha256="b" * 64, opencv_version="5.0.0", ort_version="1.28.0", process=lambda image: [row]
    )
    result = _produce(
        leg,
        policy=v.ViewPolicy.person_boxes,
        person_boxes=(v.PersonBox("rotated", (10, 8, 30, 20), "synthetic-proposals"),),
        quarter_turns=1,
    )
    wire = json.loads(json.dumps(result.to_dict(), allow_nan=False))
    assert wire["schema"] == "firbench-offline-view-evidence/v1"
    assert wire["source_sha256"] == "a" * 64
    assert wire["leg_key"] == leg.leg_id(Arm.native).key()
    assert len(wire["candidates"][1]["source"]["embedding"]) == 512
    assert wire["receipts"][1]["view"]["box_inverse"] == [[0, 1, 10], [-1, 0, 28], [0, 0, 1]]
    assert wire["receipts"][1]["view"]["point_inverse"] == [[0, 1, 10], [-1, 0, 27], [0, 0, 1]]
    assert sorted(i for group in wire["groups"] for i in group) == [0, 1]
    assert hashlib.sha256(result.recipe_json.encode()).hexdigest() == result.recipe_sha256
    assert _produce(leg).oriented_pixels_sha256 == result.oriented_pixels_sha256
    changed = _image().copy()
    changed[0, 0, 0] += 1
    assert _produce(leg, image_bgr=changed).oriented_pixels_sha256 != result.oriented_pixels_sha256
    row["landmarks_px"][:] = 99
    assert wire["candidates"][1]["local"]["landmarks_px"] == [[0, 0]] * 5
    assert result.candidates[1].local_observation.detection.landmarks_px.tolist() == [[0, 0]] * 5


def test_ambiguous_duplicates_and_cross_source_inputs_cannot_collapse_people():
    v = _views()
    obs = _observation()
    base = v.Candidate("whole", 0, obs, obs, "image-1", "a" * 64, "leg")
    ambiguous = [base, replace(base, detection_index=1), replace(base, view_id="local")]
    assert len(v.deduplicate(ambiguous)) == 3
    with pytest.raises(RuntimeMismatchError, match="different sources"):
        v.deduplicate([base, replace(base, view_id="local", source_id="image-2")])


@pytest.mark.parametrize(
    "changes",
    [
        {"image_bgr": np.zeros((2, 2, 3), dtype=float)},
        {"orientation": ""},
        {"source_sha256": "missing"},
        {"quarter_turns": 4},
        {"duplicate_tolerance_px": float("nan")},
    ],
)
def test_invalid_source_geometry_or_recipe_refuses_before_observe(changes):
    calls = []
    with pytest.raises((FrameContractError, ValueError)):
        _produce(_leg(lambda image: calls.append(image) or []), **changes)
    assert calls == []


def test_any_alarm_aggregation_keeps_a_late_false_identity_without_minting_units():
    v = _views()
    calls = []

    def process(image):
        calls.append(image.shape)
        return [
            {
                "bbox_px": (2, 3, 10, 12),
                "landmarks_px": np.zeros((5, 2)),
                "det_score": 0.9,
                "embedding": np.eye(2, 512)[int(len(calls) == 5)],
            }
        ]

    leg = fl.BuffaloLeg(weights_sha256="b" * 64, opencv_version="5.0.0", ort_version="1.28.0", process=process)
    result = runtime.experimental_view_search(
        leg=leg,
        image_bgr=_image(),
        source_id="image-1",
        source_sha256="a" * 64,
        source_search_id="background:image-1",
        orientation="decoded-oriented-v1",
        policy=v.ViewPolicy.fixed_overlap,
        budget=_budget(),
        offline=True,
        gallery=fl.Gallery.enrol({"id-1": [np.eye(2, 512)[0]], "id-2": [np.eye(2, 512)[1]]}),
        gallery_leg_id=leg.leg_id(Arm.native),
        top_k=2,
    )
    assert result.top_k == (("id-1", 1.0), ("id-2", 1.0))
    assert len(result.candidate_hits) == 5
    assert result.candidate_hits[-1][0] == ("id-2", 1.0)
    assert result.source_search_id == "background:image-1"


def test_experimental_search_refuses_canary_instead_of_bypassing_its_gallery_relabel():
    v = _views()
    calls = []
    base = _leg(lambda image: calls.append(image) or [])
    canary = fl.CanaryLeg(base, canary_identities=["id-1", "id-2"], seed=1)
    with pytest.raises(FrameContractError, match="three native model legs"):
        runtime.experimental_view_search(
            leg=canary,
            image_bgr=_image(),
            source_id="image-1",
            source_sha256="a" * 64,
            source_search_id="background:image-1",
            orientation="decoded-oriented-v1",
            policy=v.ViewPolicy.scene_only,
            budget=_budget(),
            offline=True,
            gallery=fl.Gallery.enrol({"id-1": [np.eye(1, 128)[0]]}),
            gallery_leg_id=canary.leg_id(Arm.native),
            top_k=1,
        )
    assert calls == []
